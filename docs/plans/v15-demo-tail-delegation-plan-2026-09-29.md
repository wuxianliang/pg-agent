# v15 demo / E2E：真实模型尾委托链: Plan

## Goal

用真实 DeepSeek（deepseek-flash）在 v15 全链上跑通一条**尾委托链**（根 → 子，目标深度 ≥3）：模型自主产出合法的 SQL 语句列表（含 `jaz.bind_invoke` 两句尾委托与 `jaz."return"`），验证 §0.2 核心性质（父消费子结果零额外父 LLM 调用）在真栈成立、冻结提示词对真实模型可用；产出可复跑的 demo 驱动与 E2E 证据工件，十道既有 gate 保持全绿。

## Background

### v15 驱动面（探索代理 A，file:line）

- **Worker**：`Worker(db_dsn, fakellm, worker_id, *, lease="30 seconds")`（`v15/worker.py:185`）；**硬约束**：构造时 `seconds < timeout_s + 60` 才 `ValueError`（`:188-192`）——`"180 seconds"` 能过构造，但 mark 之后 `_lease_covers`（`:346-364`）要求剩余 ≥ timeout+60，恰 180s 会在发起前被拒（`v15/provider/README.md:24` 已写明）。demo 用 `"240 seconds"`。`run_until_quiescent(db_dsn, fakellm, worker_id)`（`:793`）单次调用即可驱动任意深度树（`drive` 挂起后回扫描，子优先；三层树 gate 即单调用跑完，`v15/tree/test_tree.py:335`）；步数闸 `CAP=256`（`:30`，`RuntimeError` 在 `:814`）超限 `RuntimeError("quiescent cap")`。每步 `SET LOCAL statement_timeout='30s'`；provider 调用前 `_assert_idle()`。
- **DeepSeekProvider**：构造 `(api_key=None, base_url=None, timeout_s=120.0, transport=None, clock=None)`（`v15/provider/deepseek.py:273`），key 回落 env；`ALLOWLIST` 仅 `deepseek-flash`（`:19`）；`complete` 忽略 digest/n，只发 `request["messages"]`，返回 `{content, prompt_tokens, cost_usd, provider{finish_reason, usage, pricing_revision, peak, priced_at, reasoning_chars, id?, model}}`。
- **冻结提示**：`TAIL_DELEGATION`（两句尾委托教学，`v15/protocol/render_prompt.py:39-49`）、`HISTORY_TEXT`（`:29-37`）、`render_system(*, recursion_available, bindings)`（`:66-73`）是唯一拼装点；`recursion_available=false` 的省略 = RESPONSE_FORMAT 删一行 + TAIL_DELEGATION 整块不出现（`:19-20`、`:69`）——函数名确实不出现，但与规格 §0.25「两处教学」措辞是「一行+一块」的对应关系。每次 attempt 前 worker 重渲染 `seed:system`（`build_base`，`worker.py:163-166`）。
- **断言表面**：`v15_loop_snapshot`（`v15/loop/v15_loop.sql:547`，EXECUTE 仅 v15_worker）返回单 invoke 视图（statements/messages/bindings/attempt-仅 leased）——**没有** invoke 树、attempt 计数、事件、repl_history。「父在子树期间 attempt 数不变」的现成做法 = 超级用户直查（`v15/tree/test_tree.py:118-129` 的 `attempts(cur, iid)` 计数 helper；断言样例 `:249`、三层 `(1,1,1)` `:341-344`、`:779` 无第二次父 LLM）。`llm_attempts`/`llm_requests` 无任何 GRANT SELECT——demo 断言走超管连接（pgembed 超级用户 URI 先例 `:1000`）。
- **open**：`v15_open_invoke(p_invoke_id, p_config_scope_id, p_local_layer_id, p_inputs, p_pool_id, p_ceilings, p_system, p_user)`（`v15_loop.sql:406-415`，须 v15_worker 连接）；**`p_user` 是死参**（函数体从不引用；`seed:inputs` 由 bindings 现拼 `:509-517`）——给模型的任务正文必须走 `p_inputs` 的 `kind='input'` binding。现成辅助：`v15/provider/support.py:39-68` `open_invoke(conn, invoke_id, *, scope_id=SEED_SCOPE, max_io=3, pool_id=None, system=None)`（ceilings 固定 10/8/max_io/30000）与 `seed_flash_profile(cur)`（`:19-37`，FLASH_PROFILE=a2/FLASH_SCOPE=b2）——**全仓唯一的 deepseek-flash seed 在此**，setup_db 都不注册，不 seed 则 open 的 resolve 失败。注意（评审 (c)）：`preflight` 不读库——seed 的作用是让 open 的 `resolve` 得到 `{"model":"deepseek-flash"}`；缺 `FLASH_SCOPE` 时 open 以 `V15_VALUE_INVALID`/P1524 失败（`v15_config.sql:568-570`），不是 `model_missing`。preflight 通过还需非空 key 与 https base（`OPENAI_API_URI` 会覆盖默认端点，见裁决 13）。
- **子的种子**：由 worker `_child_seed` 现渲染经 `v15_suspend_for_child(..., p_child_system, p_child_user)`（`_child_seed` `worker.py:519-531`，调用点 `:623` → `v15_tree.sql:328` 起；`p_child_user` 是 `:336` 处的死参）；子无独立 open 入口。

### demo 先例（探索代理 B，file:line）

- **demo_v13 形态**（`demo_v13/` + `docs/plans/v13-minimal-agent-loop-demo-2026-09-23.md`）：仓库根独立目录（**不在 vN/ 内**——v13 曾因 `test_*.py` 源码扫描把 demo 迁出（`v13/acl/test_acl.py:260` 判例）；当前 v15 gate 无此扫描，放仓库根是预防性的（防未来改名成 `v15/**/test_*.py`）并保持 gitignore 简单）；独立 uv 项目（不污染根 pyproject，计划 `:469-473`）；专属库 `agent_v13_demo*`；驱动与端口解耦（driver 不 import 前端/psycopg，只走 contract 端口，`:497-535`）；fake/real 双模共用 driver（`DEMO_MODE=fake|real`，auto 探测 key，**real 无 key 导入期 RuntimeError 不开 socket**）。
- **跟踪策略**：`.gitignore:31-33` 整目录忽略 demo 树；例外 = 某里程碑交付物就是 demo 源码时 force-add 只动该目录（`da4663e` 先例，`docs/plans/v13-stannum-0.4-utilization-plan-2026-09-26.md:186-190`）。报告/日志本地留（`e2e_report*.md` 不 track）；**tracked 只有**：计划文档、gitignore 行、跑完回填的矩阵/台账行。**demo 报告不是 gate**（`docs/reviews/v13-control-plane-parity-rpce-loopx-2026-09-26.md:44`）。
- **key 纪律**：key 只活在进程环境（不过 REST/DB/日志）；非交互 shell 须 `source ~/.zshrc`；验无 key 退出码必须 `env -u ... UV_NO_ENV_FILE=1`（uv 经 `UV_ENV_FILE` 注 .env，`parity/README.md:5-7`）。
- **v6 对照**：`v6/workbench_demo/` 全 tracked 的 Streamlit 形态——v15 demo 无需交互 UI，不需要这个形态。
- **v15 现状**：`v15/provider/smoke.py` 是唯一真实 socket 入口（AGENTS.md 窄例外）；「手工全链支持但不属于冒烟」README `:24`——demo 将是第一个正规化的手工全链入口。

# 1. Summary

在仓库根新增**不入库**的 headless 驱动 `demo_v15/`，对十文件合运行时库 `agent_demo_v15` 跑一条深度至少为 3 的 echo relay（根 → 中 → 叶）。缺省 `DEMO_MODE=fake`，用有序剧本先证明开根、租约、扫描与 §0.2 断言；`DEMO_MODE=real` 才构造 `DeepSeekProvider`（`deepseek-flash`，`timeout_s=120`，租约 `"240 seconds"`）。任务正文只放在显式 input `note` 里，不包含规范 SQL。硬成功是 `tail_ok`：每个尾委托迭代恰好两句（`bind_invoke` + `return(jaz.var)`）、该迭代恰好一条 `settled` attempt、`jaz.var` 的值等于子 `return_value`、`suspend` 与 `deliver` 之间没有 `repl_exec/exit`。真实模型最多改三次 `note`（不动 §6.5）。证据写入 gitignore 的报告；跟踪提交只有计划、`.gitignore`、AGENTS 例外句、两份 README，以及跑完后的矩阵附录与台账「不新增偏差」节。

# 2. Current-state analysis

## 调用链

`run_until_quiescent` → `Worker.drive` → 迭代 `pending`/`llm` 时 `_llm`：`build_base` 重渲染 `seed:system` 并截断 → `v15_begin_llm`。`action=proceed` 后 `_mark_and_settle`：`v15_mark_call_started` 提交 → `_assert_idle` → `_lease_covers` → **事务外** `provider.complete(logical_digest, n, request, llm_config)` → `statement_payload` + `response_arg` → `v15_settle_llm`。执行阶段 `_bind_invoke` 求值实参，`_child_seed` 渲染子提示，`v15_suspend_for_child` 把父迭代与 invoke 收成 `suspended` 并清空租约，子置 `runnable`。`drive` 看到非本 worker 租约即返回。外层 `v15_next_runnable()` 按 `root_invoke_id, depth DESC, invoke_id` 排序，子先于重新可运行的父。子终态后既有 `v15_io_deliver_child` 把子 `return_value` 写成父的 `kind=var`，父从**下一条已生成语句**继续，不再 `v15_begin_llm`。这就是 §0.2。`test_grandchild` 用一次 `run_until_quiescent` 跑完三层，attempt 计数 `(1,1,1)`。

`complete` 的注入点只有 `Worker` 的第二个参数。`FakeLLM` 与 `DeepSeekProvider` 同形。`FakeLLM` 以 `(logical_digest, n)` 为键，未登记抛 `KeyError`，worker **不** settle。`logical_digest` 在 SQL 里计算，Python 不能靠另一种 jsonb 编码预知它。`test_tree.py` 的 `Script` 不看 digest，按调用顺序吐出 `content`。demo 的 fake 必须沿用这个顺序剧本，而不是 `FakeLLM.register`。

## 租约与时钟

三只时钟保持分离：`_begin` 的 `statement_timeout='30s'` 只包住转移 SQL；FakeLLM 默认租约 `"30 seconds"`；`DeepSeekProvider.timeout_s` 默认 `120`。构造时若对象有 `timeout_s`，租约秒数必须 `>= timeout_s + 60`，否则 `ValueError`。HTTP 前 `_lease_covers` 再要求 `v15_invoke_lease_seconds >= timeout_s + 60`，不足则 **mark 已提交但不调用 provider**，`drive` 返回。attempt 留在 `call_started=true` 且 invoke 仍 `leased`。`next_runnable` 不返回 `leased` 行，于是 `run_until_quiescent` 会当作静止结束。恰好 `"180 seconds"` 在 mark 耗掉时间后过不了第二道检查（`v15/provider/README.md` 已写明）。`_LEASE_RE` 只接受 `"<数字> seconds"` 这种整串。

`CAP=256`：外层每成功 claim 并 `drive` 一次加一，`steps > 256` 抛 `RuntimeError("quiescent cap")`，`finally` 里 `worker.close()`。

## Provider 映射（demo 不改）

`preflight` 失败 → `v15_provider_reject_unstarted`（不 mark，attempt `failed`，invoke `V15_PROVIDER_REJECTED` / `P1539`，`fatal=false`）。`ProviderRejected` → `v15_provider_reject_started`（attempt `unknown`，计 calls 不计 cost，invoke 同一码）。`ProviderUncertain` → `v15_provider_abandon`（attempt `unknown`，request 仍 `open`，`llm_query/retry`，invoke 回到 `runnable`，fence+1）；`http_status=429` 时 worker 再睡 1 秒。一次 attempt 一次 HTTP，适配器内部不重试。`reasoning_content` 只留 `reasoning_chars`（D29）。`temperature` 不上线（D27）。计价只认 `deepseek-flash`，算不出成本就 abandon `unpriced`，不以 0 settle。`cost_used` 是估算（D28）。

无 key 时 `DeepSeekProvider.__init__` 把 key 收成 `""`，**不**开 socket；`preflight` 返回 `credentials_absent`。模块 import 不读环境、不连网。

## 开根与任务正文

`v15_open_invoke` 要求 `session_user = v15_worker`。`p_user` 函数体不读。`seed:inputs` 由 `v15_loop_compose_inputs` 从 `kind=input AND show_in_prompt` 拼出，名字按 UTF-8 字节序。子的显式输入只来自 `bind_invoke` 实参 jsonb 的键；父的 input **不**复制。复制的是 `kind=scope` 以及 `kind=tool AND provenance=scope`。`render_system` 的 scoped 块**不写** scope/var 的 jsonb 值。因此任务散文必须是根的 `kind=input`，子要看见它，只能由模型放进 child jsonb，或由以后的 hook `input_adds` 注入。`p_child_user` 同样是死参。

`support.open_invoke` 把 inputs 写成 `'[]'`，默认 `SEED_SCOPE`（fake 模型），ceilings 固定。`seed_flash_profile` 是全仓唯一的 `deepseek-flash` 种子（`FLASH_PROFILE=…a2`，`FLASH_SCOPE=…b2`），各 stage `setup_db` 都不调用。不 seed 则 open 的 resolve 以 `V15_VALUE_INVALID`/P1524 失败（`preflight` 不读库，见 Background 评审 (c)）。带 inputs 的开根先例是 `test_tree.open_invoke`。

子配置走 `v15_resolve_child_config(父 scope, NULL, depth)`，整棵树同一 `llm.model`。`recursion_available = (depth < effective max_depth)`。`depth > max` 出生即 `V15_RECURSION_EXCEEDED`。调用方 ceilings 只能收紧，放宽是 `P1505`。清单默认 `10 / 8 / 3 / 30000`。

`flash` profile 的 `baseline_hooks` 是 `'[]'`。四只治理 hook 仍由 `v15_loop_install_hooks` 按 ceilings 安装。可选 hook（含 `context_window_warning`、`budget_pool`）不会装上。stage 8 `test_fatal` 只插入 `budget_pools` 并传入 `pool_id`，在没有 `budget_pool` hook 的前缀库上就能把超额 begin 收成 `V15_BUDGET_EXHAUSTED`。**假定**合运行时同样只靠 `pool_id` 记账；fake 路径用 `calls_used` 核对，见下文。

## 断言表面

`v15_loop_snapshot` 没有树、attempt 计数、事件、`repl_history`。`llm_attempts` / `llm_requests` 无 SELECT grant。断言必须用 pgembed 超级用户连接，助手形状沿 `attempts` / `children` / `repl_exec` 开区间查询（`test_tree.py`）。`invoke_events` 只追加，`seq` 从 0 连续。

方言分类的权威是 `split_sql` / `classify_statement` 的 `reject_code`（`V15_DIALECT`、`V15_DDL`、`V15_INVOKE_FORM`、`V15_VALUE_INVALID`）。worker 在切分失败时合成一条失败语句并 continue。未加引号的 `return`/`raise` 在执行前就是 `V15_INVOKE_FORM`（D04）。

## 库生命周期

每个 `v15/*/setup_db.py`（含 provider）会 `DROP DATABASE` 一切 `starts_with(datname, 'agent_v15_')`，并 **DROP 全部 `v15_*` 角色**。`agent_demo_v15` 不匹配该前缀，gate 不会删它。反过来，库对象属主是 `v15_owner`，库还在时 gate 的 `DROP ROLE v15_owner` 会失败。`server.get_server()` 复用仓库根 `.pgdata`，demo 不得 `cleanup()`。

## 跟踪与扫描

`v13/acl` 一类 gate 会 rglob 本版 `test_*.py`。demo 放在 `v15/` 下会被扫进。`.gitignore` 已有 `/demo_v13/`。v13 的 `da4663e` 是「里程碑交付物就是 demo 源码」时才 `git add -f`。本计划的交付物是决策与证据行，不是驱动源码。

AGENTS.md 现在写死唯一真实套接字入口是 `v15/provider/smoke.py --real-provider-smoke`。§0.0 约束的是 `v15/**/test_*.py` 不得开套接字，并点名 smoke 可以开；它没有把 gitignore 目录写进规格。

# 3. Design

本变更是**新的仓库外驱动 + 文档**。不重构 worker / provider / `support.open_invoke`。扩展点已经够用：换 `complete` 的对象、用 worker 连接调用 `v15_open_invoke`。改 `support.py` 会碰到 stage 10 gate，且它的空 inputs 合同不该为 demo 变形。

## 3.1 裁决

| # | 决定 |
|---|---|
| 1 任务 | Echo relay。系统提示词提供唯一合法语法；`note` 只写规则，禁止含 `jaz.bind_invoke` 与 `jaz."return"`。深度由 `hops=3` 倒数逼出两级委托。 |
| 2 双模 | 要。同一 `drive`。缺省 `fake`。**不**按 key 自动升 real。无 key 的 real 在建库和构造 provider 之前退出码 2。 |
| 3 断言 | 硬：`tail_ok`（§0.2 尾形式）。Relay 值相等在 fake 里硬、在 real 里软，除非 `DEMO_STRICT=1`。转录直方图与成本只进报告。报告不是 gate。 |
| 4 迭代 | 授权改 `note` 最多 3 次真实全链。**不**授权改 §6.5 / `render_prompt.py`。规格修订只写进报告，不落地。 |
| 5 形态 | 仓库根 `demo_v15/`，headless，复用根 `uv` 环境。整目录 gitignore。本计划 **不** `git add -f`。 |
| 6 库 | 名 `agent_demo_v15`。demo 自建 bootstrap。只删自己的库。不 DROP 角色，不碰 `agent_v15_*`。 |
| 7 租约 | real：`"240 seconds"`，`timeout_s` 保持 120。fake：`"30 seconds"`，剧本对象不得有 `timeout_s`。 |
| 8 CAP | 捕获 `RuntimeError` 且消息为 `quiescent cap`，分类 `driver_cap`。不改 `CAP`。 |
| 9 例外句 | 真连之前先改 AGENTS.md，把 `demo_v15/drive.py` + `DEMO_MODE=real` 列为第二个入口。不改 §0.0。不把 demo 塞进 `smoke.py`。 |
| 10 成本 | 池 `calls_limit=32`、`cost_limit=2.00`。超限走既有 fatal `V15_BUDGET_EXHAUSTED`，本计划不放宽。 |
| 11 support.py | 不修改。demo 自己的 `open_root` 调用 `seed_flash_profile` 与 `FLASH_SCOPE`。 |
| 12 §0.25 | 不修订。「一行 + 一块」已是「两处教学」的实现。本 demo 的成功叶在 depth 3，`max_depth=4`，叶仍看得到尾委托教学。省略路径已由 protocol/govern gate 证明。 |
| 13 base URL | real 分支构造 provider 时**显式传** `base_url="https://api.deepseek.com/v1"`，不读 `OPENAI_API_URI`（该 env 会覆盖默认端点且 https 的错主机能过 preflight，然后在错误主机上计费——评审问题 1 裁决：钉死，杜绝该类操作者失误）。README 的真连命令注明这一点。 |

### 任务为什么是 echo relay

比较过的四条：

- **单语句就能算完的题**（拼字符串、`WITH RECURSIVE`）：模型不必委托。放弃。
- **把两句规范 SQL 写进 user 输入**：成功率高，不能证明冻结提示词。驱动拒绝含这两段子串的 `note`。
- **自定义 hook 在 `invoke/enter` 注入只有该层知道的 seal**：子输入不由父伪造，信息上更硬。要碰效应闭集与 `P1537` 登记，失败域会从提示词变成 hook。不作为首路径。
- **Echo relay（采用）**：与冻结尾示例同构——下一条就是 `return(jaz.var(...))`，父不需要再调用模型来「加工」子结果。`hops` 只在本层输入里，子看不到父的 input，所以倒计数必须由父写进 child jsonb。这是架构允许的「必要」，不是信息论上的不可作弊。模型若直接 `return` 字面量，硬断言失败，分类 `no_delegation`，用下一版 `note` 处理。

根 inputs（四项都是 `kind=input`、`show_in_prompt=true`、`provenance=explicit`，**不带** `tool_id` 键）：

| name | jsonb 值 |
|---|---|
| `hops` | 数字 `3` |
| `role` | 字符串 `root` |
| `seal` | 字符串，`secrets.token_hex(3)`，即 6 位小写十六进制 |
| `note` | 字符串，下面的 `NOTE_V1` |

`NOTE_V1`（一段、无分号、无撇号、无规范 SQL、绑定名固定为 `down`；含一句「引号是语法不是值的一部分」——`v15_loop_compose_inputs` 按 `value::text` 渲染，模型若把引号字符抄进子 jsonb 会造成 relay 值不等而 `tail_ok` 仍可成立，评审 §4）：

```text
Copy this note to the child unchanged as the note input. The quotes around a value are syntax and are not part of the value. You are the hop given by role. hops counts the hops left, including you. seal is the leaf seal. Pass it down unchanged. When hops is greater than 1, delegate to one child bound as down and return that child result unchanged. The child input object must have note (this same text), hops (your hops minus one), role (mid when you are root, otherwise leaf), and seal (unchanged). When hops is 1, do not delegate. Return a JSON object with keys seal and hops, using your seal and hops 1. A literal JSON return while hops is greater than 1 is wrong. No markdown. No prose.
```

期望链条：

| depth | role | hops | 回复形状 |
|---|---|---|---|
| 1 | root | 3 | 恰好两句：`bind_invoke('down', {note, hops:2, role:mid, seal})` 然后 `return(jaz.var('down'))` |
| 2 | mid | 2 | 同上，子 `hops=1`、`role=leaf` |
| 3 | leaf | 1 | 恰好一句 `return`，对象 `{"seal":"<根 seal>","hops":1}`，无子 |

`down` 写进 `note` 是绑定名，不是语句模板。规范语句仍只出现在 `TAIL_DELEGATION`。绑定名 `down` 不在四项 input 中也不是保留名——`v15_loop_validate_inputs`（`v15/loop/v15_loop.sql:286-364`）接受该形状，`v15_io_deliver_completed`（`v15/io/v15_io.sql:560-568`）对非 input/scope/tool 同名插入 `kind=var`（input 同名才是软 `V15_DELIVERY_CONFLICT`/P1527，非 P1524）。**无需实现期核对**（评审 (a) 已闭合）。`show_in_prompt` 必须是 JSON `true`（`json.dumps` 的布尔），不是字符串 `"true"`。fake 剧本也用 `down`。

Ceilings（相对清单只收紧）：`max_iterations=4`，`max_depth=4`，`max_io_attempts=2`，`max_statement_ms=30000`。

- 迭代 `>= 4` 在租赁前中止，即 0..3 共四轮。够一次坏 continue 再尾委托，不够长循环。
- `max_depth=4`：depth 3 的叶仍 `recursion_available=true`（任务靠 `hops` 停，不靠删教学）。depth 4 关闭递归。depth 5 出生即 `V15_RECURSION_EXCEEDED`。
- `max_io_attempts=2`：同一 request 上 `n=2` 仍可插入，`n=3` 为 `V15_IO_EXHAUSTED`。方言失败是 settle 后的 continue，不消耗这只闸。

无 scope、无工具、无 local layer。`p_user` 传 SQL NULL。`p_system = render_system(recursion_available=True, bindings=[])`。只有 input 时 scoped 块没有数据行，与 worker 第一次重渲染一致。

池（超级用户插入，再把 `pool_id` 交给 open）：`calls_limit=32`，`cost_limit` 数值 `2.00`（插入用十进制文本，不用二进制 float）。32 = 4 个 invoke × 4 迭代 × 2 次 attempt，是天花板的数学上界，正常路径只有 3 次 settle。高峰粗算：单次约 3k miss 输入 + 8k 输出（含思考 token）≈ $0.011，32 次约 $0.34。`$2` 是**事后闸**不是事前拒：无 hook 预留 cost 为 0，`cost_limit` 不拦那一次跨限调用，settle 计账后才 fatal（`v15_io.sql:1515-1523`），`calls_limit=32` 拦的是下一次 begin。两数是选择的上限，不是「树不可能超限」的证明（一个迭代可多次 bind、`max_depth` 封链深不封扇出）。`cost_limit` 不得为 SQL NULL。不登记可选 `budget_pool` hook。

`NOTE_V2` / `NOTE_V3` 不预写。只有上一跑的 `failure_class` 属于「note 可改」时才改 `task.py` 里的常量，并保持：一段英文、无分号、无撇号、无两段禁子串、仍要求绑定名 `down`、仍要求原样转发 `note`。fake 剧本随 note 文本重嵌 SQL 单引号（`'` → `''`）与 JSON 转义后再跑绿，然后才允许下一轮 real。

## 3.2 驱动形态与模块

目录（全部 gitignore）：

```text
demo_v15/README.md
demo_v15/task.py          # NOTE_*、ceilings、池上限、root_inputs(seal)
demo_v15/script.py        # OrderedScript
demo_v15/db.py            # 角色、建库、seed、池、连接、drop
demo_v15/assert_e2e.py    # 超级用户只读查询 → 结果 dict
demo_v15/report.py        # markdown + 擦 key
demo_v15/drive.py         # main
demo_v15/test_harness.py  # 只 fake
```

无 `pyproject.toml`、无 `.env`、无 Chainlit/HTTP 端口。v13 的 port 拆分是因为 REST 与 psycopg 两套传输；这里只有 psycopg + `Worker`。驱动直接调用 `run_until_quiescent` 与 `v15_open_invoke`。每个 `drive.py` / `db.py` 在 import `v15` 之前把仓库根插入 `sys.path`（`Path(__file__).resolve().parent.parent`）。

`drive.py` 顶层禁止 import `v15.provider.deepseek`。只在 real 且 key 已确认存在之后，在函数内部 import。

### 模式与退出码

`DEMO_MODE` 读自传入的 environ（缺省 `os.environ`），缺省值 `fake`。

| 条件 | stdout 一行 | 退出码 |
|---|---|---|
| `fake` 且 `tail_ok` 且 `relay_ok` | `tail_ok relay_ok` | 0 |
| `real` 且 `tail_ok` 且 `relay_ok` | `tail_ok relay_ok` | 0 |
| `real` 且 `tail_ok` 且 relay 软失败 | `tail_ok relay_soft_fail` | 0 |
| 结构失败、CAP、已开打后的异常 | `fail <failure_class>` 或 `demo real run failed` | 1 |
| `real` 且 key 空 | `credentials_absent` | 2 |
| `DEMO_MODE` 不是 `fake`/`real` | `mode_invalid` | 2 |
| `--drop-only` 成功 | `dropped` | 0 |

key 的判定与 `DeepSeekProvider` 相同：`DEEPSEEK_API_KEY`，否则 `OPENAI_API_KEY`，缺席或空串都是无 key。无 key 分支在 `get_server()`、建库、import deepseek、`complete` 之前返回。

已开打（`complete` 已被调用，或 worker 循环已进入）之后的未捕获异常：先尽量写报告，再 `raise RuntimeError("demo real run failed") from None`。禁止降级成退出码 2。stdout/stderr 不打印 key、`Authorization`、`reasoning`、助手 `content`。摘要行也不打印 `return_value`。细节只在报告文件。报告路径打到 stdout 的第二行是允许的（本地路径，无密钥）。

`DEMO_KEEP_DB=1`：结束时留库。`DEMO_STRICT=1`：real 的 relay 断言升为硬失败。

`--drop-only`：只断开连着 `agent_demo_v15` 的后端并删该库，不跑模型。

### OrderedScript

与 `Script` 同职责的小对象，放在 `demo_v15/script.py`，**不** import `test_tree.py`（避免 gate 模块与 `agent_v15_tree` 常量）。

- 状态：剩余 `content` 字符串队列，以及 `calls` 列表 `(logical_digest, n)`。
- `complete(logical_digest, n, request, llm_config=None) -> dict`：队列空则抛专用异常（fake 里算 `harness_bug`）。返回 `{"content": <str>, "prompt_tokens": 1, "cost_usd": 0}`。`cost_usd` 用 int `0`，让 worker 走 `Json` 分支，不碰 Decimal。
- 无 `preflight`，无 `timeout_s`，无 `close`。

Happy-path 队列顺序就是 LLM 调用顺序（子在第一次父回复之前不存在，所以不是「子先调用」）：

1. 根：两句，child hops `2`、role `mid`，note/seal 原样嵌进 jsonb 字面量。
2. 中：两句，child hops `1`、role `leaf`。
3. 叶：`SELECT jaz."return"('{"seal":"<seal>","hops":1}'::jsonb);`

第二只 fixture（只在 `test_harness.py`）把根的第一次回复换成 `SELECT 1;`，第二次才是尾两句，然后中、叶。调用序四次：根 continue、根尾、中、叶。用来锁死「attempt 计数看绑定所在迭代，不看 invoke 一生的总数」。

### open_root

在 **v15_worker** 连接上，形状照 `test_tree.open_invoke`，参数换成：`scope_id=FLASH_SCOPE`，`local_layer` NULL，`pool_id` 为刚插入的池，`ceilings` 为上一节的对象，`inputs` 为四键数组，`p_system` 为渲染结果，`p_user` NULL。调用前 `SET LOCAL lock_timeout='2s'`、`statement_timeout='30s'`，然后 commit。

open 之前超级用户已经 commit 了 `seed_flash_profile` 与池行。real 还要在 open **之前** `preflight({"model":"deepseek-flash"})`。返回非空 dict 则不 open，分类取 `class`（`endpoint_rejected` 等归 `provider_rejected`），关掉 provider，按失败策略删库，退出码 1。

### 主路径顺序

1. 解析模式与 key。real 无 key → 2。
2. `db.setup("agent_demo_v15")`：见 3.3。每次 drive **先删后建**，没有「接着上次 invoke 跑」的模式。
3. 超级用户：`seed_flash_profile`、插入池、commit。
4. real：构造 `DeepSeekProvider(base_url="https://api.deepseek.com/v1")`（默认 timeout 与 clock；base 钉死见裁决 13），`preflight`，失败则停。
5. worker 连接：`open_root`，commit。root id = `uuid4`。
6. `run_until_quiescent(server.get_uri(db), provider, "demo-v15", lease=...)`。fake 租约 `"30 seconds"`，real `"240 seconds"`。
7. `worker.close` 已在 `run_until_quiescent` 的 `finally`。驱动自己的 provider 引用不要再 `complete`。
8. 新的超级用户连接做断言（此时没有打开的 provider，也没有跨着 HTTP 的事务）。
9. 写报告。
10. 成功则删库，除非 `DEMO_KEEP_DB=1`。失败或 CAP 或中断：**留库**，stdout 写明删库命令，以及「下一次任何 v15 gate 的 setup 会先强制删光全部 `agent_v15_*` 库、然后在 `DROP ROLE v15_owner` 处失败——须先 `--drop-only`」（评审 (d)：角色失败发生在 gate 已删完 gate 库**之后**）。

`KeyboardInterrupt`：`failure_class=interrupted`，留库，退出码 1，不另起 worker 去补结算。

### 结果 dict（`assert_e2e` 的返回值）

```text
outcome: "tail_ok" | "fail"
failure_class: str | None
relay_ok: bool
relay_flags: list[str]
root_id: str
nodes: list[{
  invoke_id, depth, parent, status, fatal, error_code,
  return_value,
  inputs: {note, hops, role, seal},   # 缺键则为 null
  bind_iteration: int | None,
  settled_on_bind_iteration: int,
  max_n_on_bind_iteration: int | None,
  settled_n: int | None,
  unknown_attempts: int,
  statement_count_on_bind_iteration: int,
  var_matches_child: bool | None
}]
transcript: {
  assistant_messages, markdown_fence_messages,
  split_failures: {reject_code: n},
  classified: {reject_code_or_empty: n},
  legal_statement_rate
}
cost: {
  sum_cost_usd, cost_used, calls_used, calls_charged,
  calls_limit, cost_limit,
  pricing_revision,   # 能读到才填
  any_peak            # 能读到才填
}
events_ok, scratch_clear, running, leased
```

金额用十进制字符串。比较 `return_value` 与 binding 用 SQL `jsonb =`，不用文本比较。

## 3.3 Bootstrap 与连接

`db.setup` **禁止**复制 `v15/provider/setup_db.py` 的全库删除与角色删除。允许的差异：

- 库名参数化。drive 用 `agent_demo_v15`。`test_harness.py` 用 `agent_demo_v15_harness`。两者都不匹配 `agent_v15_`。
- 删库前只终止 `datname` 等于该库的后端，再 `DROP DATABASE … WITH (FORCE)`。不调用会扫全部 `v15_%` 用户的 `_terminate_role_backends`。
- 角色：按 `HOOK_ROLES` 与 `v15_bootstrap` / `v15_owner` / `v15_worker` / `v15_repl` 的同一批 `CREATE ROLE` 属性，**仅当 `pg_roles` 没有该名**。已存在则不 DROP、不 REVOKE 其他成员关系。
- 若 `v15_worker` 不是 `v15_repl` 的成员，补 `GRANT v15_repl TO v15_worker WITH INHERIT FALSE, SET TRUE`。已是成员则不动。
- 仅当本次创建了 `v15_bootstrap`，结束时 `ALTER ROLE v15_bootstrap NOLOGIN`。已存在的 login 标志保持原样。
- `load_stage(server, dbname, "provider")`，即 `SQL_LOAD_ORDER` 全部十个文件。
- 不 `GRANT` 新权限，不改 `search_path`，不 `ALTER` 表。

`connect_worker` 直接用 `v15.worker.connect_worker(server.get_uri(dbname))`。超级用户用 `psycopg2.connect(server.get_uri(dbname))`。实现时第一条核对查询：worker 连接上 `session_user` 与 `current_user` 都是 `v15_worker`。若 URI 形状让 `connect_worker` 落到原始 DSN（超级用户），open 会在 `v15_repl_require_worker` 处失败；这时停，不要改成 TCP 或改 `pg_hba`。

demo 不调用 `server.cleanup()`。与 gate 串行。并发跑未定义。

成功路径结束删的是 demo 库，角色留下，与 gate 之后的集群一致。失败路径留库是为了查行；操作者在下一次 `v15/*/setup_db.py` 之前必须 `--drop-only`。

## 3.4 断言

超级用户、worker 已关闭之后、单线程、无第二写入者。

### `tail_ok`（fake 与 real 都是硬条件）

树从 root 沿 `parent_invoke_id` 走全。

1. 存在 depth 1、2、3 的节点，且有一条根—子—孙的父指针链。根 `depth=1`。
2. 这条链上三个节点都是 `status=completed`、`fatal=false`、`return_value` 非 NULL。允许更深的节点也 completed；不要求「恰好三个」才算 `tail_ok`。
3. 每个有 `kind=bind_invoke AND status=done AND child_invoke_id IS NOT NULL` 的 invoke，这样的语句**恰好一条**。记其 `(iteration, stmt_index)` 为绑定点。
4. 该迭代上的语句**恰好两条**：`stmt_index` 0 为这条 bind，1 为 `kind=return`、`status=done`。return 的 `sql` 在删去空白后含 `jaz.var('` + `bind_name` + `')` 或双引号变体 `jaz.var("` + name + `")`。
5. 该迭代 `result_kind=return`，且不存在更大的 `iteration`。更早的 `continue` 迭代允许存在。
6. 该迭代的 request 上：`status=settled` 的 attempt **恰好 1**；不存在 `status=leased`；`max(n)` 等于这条 settled 的 `n`（更小 `n` 的 `unknown`/`failed` 是产生这句回复之前的传输重试，允许）。
7. 父 binding `name=bind_name AND kind=var` 的 `value` 与子 `return_value` 在 jsonb 相等意义上相同。
8. 该父的 audit：存在 `payload->>'op'='suspend'` 与 `'deliver'`，且 suspend 的 `seq` 小于 deliver 的 `seq`。两者之间没有 `event_class=span AND span=repl_exec AND phase=exit`。
9. 最深节点没有子行，其完成迭代是 `return`，且该迭代没有 `done` 的 `bind_invoke`。
10. 全库 `statements.status='running'` 为 0；树内没有 `suspended` / `leased` / `pending` / `runnable` invoke。
11. 树内没有 `error->>'code' = 'V15_PROVIDER_REJECTED'`，没有 `fatal=true`。
12. 每个树内 invoke 的 `invoke_events.seq` 从 0 连续无洞。
13. 每个 `completed` 节点的 `scratch_schema` 在 `pg_namespace` 中的行数为 0。

第 6 条是 §0.2 的操作化：禁止的是绑定迭代上成功回复之后又一次 LLM，不是禁止传输重试，也不是禁止更早的 continue。第 4、7、8 条一起证明「同一迭代的下一条已生成语句用 `jaz.var` 读到了子结果」，并且等待期间 `repl_exec` 没有 exit。

`run_until_quiescent` 正常返回但第 10 条失败，且存在 `call_started` 仍 `leased` 的 attempt：这就是 `_lease_covers` 拒绝发起后的假静止。`failure_class=lease_skip`。不要干等 240 秒去回收。

### Relay（fake 硬；real 软，`DEMO_STRICT=1` 时硬）

- 树上 invoke **恰好 3**，每个委托节点恰好 1 个子。
- 输入：depth1 `role=root,hops=3`；depth2 `role=mid,hops=2`；depth3 `role=leaf,hops=1`。三层 `seal` 都等于驱动生成的根 seal。三层 `note` 都等于本跑的 note 字符串。
- 三层 `return_value` 都 jsonb 等于 `{"seal": <根 seal>, "hops": 1}`，因此父值等于子值。
- fake happy path 额外：`calls_used = 3`，`cost_used = 0`，根上 attempt 总数为 1。第二只 fixture：根 attempt 总数为 2，绑定迭代 settled 仍为 1，`calls_used = 4`。`calls_used` 对不上就是 `harness_bug`，禁止进入 real。这是对「只靠 `pool_id` 就记账」这一假定的检验。

real 额外硬条件：每条 `settled` attempt 的 `prompt_tokens >= 1` 且 `cost_usd > 0`。否则 `cost_missing`（防止把 fake 结果当成真连）。

### 只记录、不单独决定退出码

- 助手消息走 `split_sql` / `classify_statement`：`split_failures`、`reject_code` 直方图、`legal_statement_rate`。
- 含三个反引号的助手消息计数（markdown）。
- `sum(llm_attempts.cost_usd)`、`budget_pools.cost_used` / `calls_used`、以及 response 里若仍在的 `provider.pricing_revision`、`provider.peak`、`provider.finish_reason` 计数。settle 是否保留未知键是实现期核对项；缺了就记 `provider_meta=absent`，不为此改 `v15_settle_llm`。
- D28 一句：`cost_used` 不是发票；工作日假日按高峰多报。
- `finish_reason=length` 记入 `relay_flags`，类名 `finish_length`。

明确不当硬断言：SQL 全文与黄金文件逐字相等、延迟、token 下限、`finish_reason` 必须是 `stop`、跑完之后 `seed:system` 仍等于 `render_system(bindings=[])`（出现 var 之后 worker 会重渲染，种子行本身不可变，两者本来就可以不同）。

### 失败类优先级

`outcome=tail_ok` 时 `failure_class` 为空。否则按序取第一个成立的：

1. `driver_cap` — 捕获到消息 `quiescent cap`
2. `interrupted`
3. `open_failed` — open 或 seed 的数据库异常（报告带 `pgcode`，不带 DSN 密码；pgembed 本地 trust 无密码）
4. `provider_rejected` — preflight 非空，或任一 invoke `V15_PROVIDER_REJECTED`
5. `lease_skip`
6. `budget_cap` — `V15_BUDGET_EXHAUSTED`
7. `iteration_ceiling` — `V15_ITERATION_EXCEEDED`
8. `recursion_ceiling` — `V15_RECURSION_EXCEEDED`
9. `provider_uncertain` — `V15_IO_EXHAUSTED`，或没有成功 bind 且存在 `unknown` attempt
10. `child_error` — 父语句 `V15_CHILD_ERROR`，或子 `status=failed`
11. `bind_name_collision` — `V15_DELIVERY_CONFLICT`
12. `print_and_return` — `V15_PRINT_AND_RETURN`
13. `no_delegation` — 无子行
14. `shallow_chain` — 有子但没有 depth ≥ 3
15. `bad_tail_shape` — 有 depth ≥ 3 但某一环不满足两句尾形式 / var / 事件序 / attempt 谓词
16. `markdown_fence`
17. `unquoted_return` — 直方图里有 `V15_INVOKE_FORM`，且对应 sql 经分类器是未加引号的 return/raise
18. `prose_or_empty` — 空助手消息，或执行期 `42601` 且没有 bind
19. `dialect_reject` — 其余 `V15_DIALECT` / `V15_DDL` / `V15_VALUE_INVALID`
20. `mission_not_forwarded` — 子 input 缺 `note` 或 `hops` 不是父 hops−1
21. `cost_missing` — 仅 real，settled 行没有正成本
22. `harness_bug` — fake 队列耗尽、`calls_used` 不符、或其他断言器不变量

`relay_flags` 始终可带 `mission_not_forwarded`、`over_delegation`（节点数 > 3 或任一节点多于一个子）、`finish_length`、`extra_unknown_attempts`、`relay_value_mismatch`。`tail_ok` 且节点数 > 3 时主结果仍是 `tail_ok`，`relay_ok=false`。

## 3.5 失败归属与 §18

| 类 | 归属 | 本计划内的动作 |
|---|---|---|
| `no_delegation`、`shallow_chain`、`over_delegation`、`mission_not_forwarded`、`bad_tail_shape`、`markdown_fence`、`unquoted_return`、`prose_or_empty`、`print_and_return`、`bind_name_collision` | demo `note` | 改 note。冻结段落已经禁止围栏、散文和未加引号的 return；note 只是再强调任务规则 |
| `dialect_reject` 且模型写了 `DO` / `ALTER` / 事务控制 | demo `note` | 同上 |
| 冻结示例那两行被 `classify_statement` 拒绝，或原样执行失败 | 产品缺陷 | **停止** note 循环。用 FakeLLM 在既有 `v15/**/test_*.py` 加一条复现，修 `split_sql` 或执行路径。那是另一个里程碑，十道 gate 全绿后单独提交。不得夹在 demo 文档提交里 |
| 合法尾两句在真栈上拆坏租约、Decimal、送达 | 产品缺陷 | 同上，复现必须无网络 |
| `lease_skip` | 驱动租约 | 只许把 demo 的租约从 240 再加大，**不**改 worker 公式。本计划的预定值就是 240，加大前先确认不是时钟被手动改过。不消耗 note 次数 |
| `driver_cap` | 驱动闸 | 不改 `CAP`。留库。不自动再启动（会继续烧调用） |
| `provider_rejected` | 操作者（401/402/模型名/URL） | 停止。不改提示词 |
| `provider_uncertain` | 网络或供应商 | 不改 note 的前提下，允许在三次 note 预算**之外**整库重跑一次。仍失败则停止 |
| `budget_cap` | 天花板已生效 | 不提高 `$2` / 32。停止 |
| `iteration_ceiling`、`recursion_ceiling` | note 或模型停不下来 | 改 note，不放宽 ceilings |
| `finish_length` 且因此没到 `tail_ok` | demo 库内的 profile，仍不是 §6.5 | 不消耗 note 次数。下一跑在 **demo 库**对已有 flash profile 原地 `v15_update_profile`（`v15_register_profile` 是 INSERT，重用 id 会撞主键；新注册 profile 而不换 scope 则无人引用）：模型仍是 `deepseek-flash`，增加 `max_output_tokens=4096`，repl/protocol 不变，`FLASH_SCOPE` 与 `open_root` 都不动。不改 `support.py`。4096 仍把内容截空则停，分类保持 `finish_length`（评审问题 2 裁决：原地更新而非新 profile+scope） |
| 三次 note 后仍无 `tail_ok`，且失败形态是模型在按冻结英文的一种可读误解输出 | §18 **提案** | 只写报告。不改 `render_prompt.py`、设计文档、protocol gate |

三次的定义：三次 `DEMO_MODE=real` 且至少发生过一次 `complete` 的全链。`credentials_absent`、preflight 失败、`lease_skip`、纯 `provider_uncertain` 重跑、`finish_length` 的 4096 应急跑，都不计。一旦 `tail_ok`，**停止**，不为了 `relay_ok` 把剩余次数花掉。

§18 提案若写，必须包含：哪一段冻结原文、模型实际输出的类别（不是大段原文粘贴）、最小改动句子、要重跑的 gate（至少 `v15/protocol/test_protocol.py`，若措辞进入 §0.25 还要 govern 的窗口警告）。错误码不预占。`v15_on_phase` 与四只治理 handler 的函数体位置不动。

## 3.6 报告、矩阵、台账

报告路径：`demo_v15/reports/e2e_report-<UTC 时间戳>.md` 与 `demo_v15/reports/latest.md`。目录在 `/demo_v15/` 忽略之下。内容：

- 时间、模式、note 修订号、库名、root uuid、租约、ceilings、池上限
- `outcome`、`failure_class`、`relay_ok`、`relay_flags`
- 节点表：id、depth、四项 input、status、error code、各迭代 attempt 数、`return_value`（小 jsonb，保留）
- 每条委托边的 §0.2 核对：绑定迭代、settled 数、max n、下一条 kind、var 相等、suspend/deliver seq、区间内 repl_exec exit 数
- 转录直方图与 `legal_statement_rate`
- 成本字段与 D28 一句
- 助手 `content` 只留每条前 120 个字符，供围栏诊断
- 例外节：无 §18 提案则写「no spec change」

擦除：若环境里 key 非空，写文件前从全部字符串里去掉该子串。不写 `Authorization`、不写 `reasoning_content`、不写 `provider.id`、不写完整 `request.messages`、不写 DSN。`finish_reason` 与 token 计数可以写。

矩阵（`docs/reviews/v15-conformance-matrix-2026-09-29.md`）在文末追加，**不**进入 10.x，**不**标 ✅：

```text
## Demo evidence（不是 gate）

| 跑次 | 模式 | 结果 | 落点 | 断言的行为 |
|---|---|---|---|---|
| <UTC 日期> <NOTE_Vn> | DEMO_MODE=real deepseek-flash lease 240s | tail_ok 或 fail <class> | gitignore 的 demo_v15/reports/（不入库） | 链深度 ≥3 时核过的那些硬条件：绑定迭代恰好两句且下一条 return 读到子 var；该迭代恰好一条 settled 且 max(n) 等于它；suspend 与 deliver 之间无 repl_exec exit。十道 gate 不导入该驱动。 |
```

未达到 `tail_ok` 也写这一行，结果栏写 `未证明` 与 `failure_class`。禁止写成合同已覆盖。

台账文末：

```text
## Demo

尾委托 demo 不新增 V15-D 行。它不修改渲染器、切分器、worker 或 provider。真实调用的计价、无幂等与思考文本仍由 D27–D30 覆盖。
```

`SQL_LOAD_ORDER` 不追加。不新增 stage README。`v15/provider/README.md` 只改「手工全链」那段的操作句：示例租约改为 `"240 seconds"`，并写明正规全链入口是 `demo_v15/drive.py`、库名 `agent_demo_v15`、冒烟脚本仍然不建库。保留「恰好 180s 过不了发起前检查」这句。`v15/README.md` 在 gate 命令后加一句：该 demo 不是 gate；库名避开 `agent_v15_`；留下 `agent_demo_v15` 会挡住 stage setup 的 `DROP ROLE`。

## 3.7 AGENTS.md 例外句

用下面这段替换「唯一真实调用入口是 `v15/provider/smoke.py --real-provider-smoke`」那一整条 bullet：

```text
- **外部 IO 一律不进数据库事务**（v8 不变量 4）。测试用 FakeLLM / FakeTool，不调真实 provider。`v15/**/test_*.py` 仍然如此，不得打开网络套接字。真实套接字只允许两个入口，二者都不是 gate，也不是合运行时证明；调用当时不得有打开的数据库事务：
  1. `v15/provider/smoke.py --real-provider-smoke`
  2. 仓库根 `demo_v15/drive.py`，且环境变量 `DEMO_MODE=real`。该目录在 `.gitignore`。无 key 时驱动打印 `credentials_absent`、退出码 2，不构造 `DeepSeekProvider`，不调用 `complete`。`DEMO_MODE` 缺省为 `fake`。
```

这条必须在**第一次** `DEMO_MODE=real` 之前进入 `main`。不修改 `docs/designs/v15-jaz-dev.md`。理由：§0.0 禁止的是 gate 开套接字；demo 不在 `v15/**/test_*.py`，也不是合运行时证明。把 gitignore 路径写进冻结规格会让规格依赖一份故意不跟踪的树。

smoke 与 demo 的关系：只复用退出码政策（0 / 2 / 已开打后 1 且不降级）和 key 擦除。demo 不调用 smoke，不增加 `--real-provider-smoke`。smoke 继续不建库、不开 invoke。

无 key 核对命令（操作者，防 uv 经 `UV_ENV_FILE` 注入 `.env`）：

```bash
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL \
  UV_NO_ENV_FILE=1 \
  DEMO_MODE=real \
  uv run python demo_v15/drive.py
```

期望 stdout `credentials_absent`，退出码 2，且集群里没有新建 `agent_demo_v15`。

`test_harness.py` 用 `sys.executable` 起子进程跑同一入口，从子环境删掉上述四变量和 `UV_ENV_FILE`，并设 `UV_NO_ENV_FILE=1`。用 `sys.executable` 是为了避免子进程再次被 uv 注入 `.env`。期望退出码 2。父进程若已持有 key，必须在子环境里删掉，不能靠「自己没 export」来假设。

非交互 shell 要 key 时，操作者自己 `source ~/.zshrc` 后再 `DEMO_MODE=real uv run python demo_v15/drive.py`。驱动不读文件、不把 key 写入数据库或报告。

## 3.8 并发、生命周期、错误

驱动主线程是串行的。语句取消仍用 worker 里已有的 daemon `Timer`，demo 不新起线程、不新起第二个 worker。断言发生在 `run_until_quiescent` 返回之后，timer 只存在于语句执行期间，与断言不重叠。

没有第二个写入者，因此不存在断言读到半条事件序。`invoke_events` 的触发器拒绝跳号与更新。崩溃中断留下的是最后一次已提交转移；报告读这份前缀，类为 `interrupted` 或进程死掉则没有报告。不自动重放同一 invoke。下一跑永远是新库新 uuid。

provider 调用点的事务状态由 worker 的 `_assert_idle` 保证。驱动不得把 open、run、assert 包进同一个未提交事务。`open_root` 自己 commit。断言连接在 run 之后才打开。

`OrderedScript` 耗尽、`KeyError`、`ProviderPreflight`：fake 归 `harness_bug`；real 的 preflight 在 open 前处理。worker 对 `ProviderRejected` / `ProviderUncertain` 已有映射，驱动只读结果行。

边界：空 note、note 含禁子串、seal 不匹配 `^[0-9a-f]{6}$` → 退出码 2，stdout `note_invalid` 或 `seal_invalid`，不建库。`hops` 不是 JSON 数字 3 的根输入同样在开根前拒绝。

## 3.9 实现期核对

| 事实 | 核对方法 |
|---|---|
| ~~pool_id 记账假定~~ | 已闭合（评审）：无 hook 的 begin 预留 `(pool_id,1,0)`（`v15_io.sql:1251-1276`），settle/reclaim 都走 `v15_io_pool_release`。`calls_used=3` 是确认不是探针；**为 0 即停**。**禁止**为凑数安装 `budget_pool` hook（hook 分支不预留、release 会 `P1523`；`test_govern.py:887` 期望与现行 SQL 不符是既有问题，不在本计划修） |
| ~~deliver 对 input 同名~~ | 已闭合（评审）：非 input/scope/tool 同名一律插 `var`；`down` 安全 |
| settle 是否保存 `provider` 对象 | 第一跑 real 读 `llm_attempts.response`。没有该键则报告记 absent |
| `connect_worker` 的 `session_user` | setup 后立刻查，必须是 `v15_worker` |
| 超级用户可执行 `seed_flash_profile` 与 `INSERT budget_pools` | 第一只 fake 库上直接做。权限失败则改由已有 EXECUTE 的角色调用，不新增 GRANT |
| `v15/provider` 的 import 是否连网 | keyless 子进程退出码 2，且该进程路径上不构造 `DeepSeekProvider`。deepseek 模块即使被间接 import，`post` 也只在 `complete` |
| ~~迭代钩核对~~ | 已闭合（评审）：`v15_govern.sql:581` 与 `v15_begin_llm` 的 `v_iter >= v_max_iter` 都在租赁前拒；`max_iterations=4` 即 0..3 四轮，fake 不烧第 5 轮 |
| 角色已存在与角色不存在两种集群 | 先在跑过 gate 的集群上建 demo 库（角色已在）。缺角色分支靠「不存在才 CREATE」的 SQL 审查。不要为了演练而 DROP 现有 `v15_*` 角色 |
| 留库挡住 gate | 手动一次：留着 `agent_demo_v15` 跑 provider `setup_db.py`，期望 `DROP ROLE` 失败；`--drop-only` 后再跑，期望 `[ready] agent_v15_provider`。这会删掉其他 `agent_v15_*` 库，只在操作者接受 gate 库重建时做 |

# 4. File-by-file impact

## 跟踪文件

| 文件 | 变更 | 为何 | 依赖 |
|---|---|---|---|
| `.gitignore` | 在 `/demo_v13/` 旁追加 `/demo_v15/` | rglob 与密钥、报告都不入库 | 必须先于创建 demo 文件的那次提交 |
| `docs/plans/v15-demo-tail-delegation-plan-2026-09-29.md` | 保留 Goal / Background / References；写入本计划；M3 追加一节 Run record（日期、NOTE 修订、`tail_ok` 或 `未证明`、failure_class） | 决策跟仓库走 | M0 写入正文；Run record 等 M2 之后 |
| `AGENTS.md` | 替换真实套接字那一条 bullet 为 3.7 的两入口文案 | demo 是第二个真实入口 | fake 与 keyless 已绿，且早于第一次 real。与两份 README 同一次提交 |
| `v15/provider/README.md` | 手工全链示例租约改为 240s；指向 `demo_v15/drive.py` 与库名；保留 180s 警告；声明不是冒烟、不是 gate | 现有 180s 示例与同页警告矛盾，操作者会抄错 | 与 AGENTS 同一提交 |
| `v15/README.md` | gate 命令后两句：demo 入口、库名前缀、留库会挡住 DROP ROLE | 避免有人把它当成 stage 11 或 `agent_v15_*` | 与 AGENTS 同一提交 |
| `docs/reviews/v15-conformance-matrix-2026-09-29.md` | 文末 Demo evidence 表一行 | 证据落点，不是新合同行 | 至少一次 real 结束（成功或三次用尽或不能证明） |
| `docs/reviews/v15-deviation-ledger-2026-09-29.md` | 文末 Demo 节，不新增 D 编号 | 收尾清单里的台账有明确「无新偏差」 | 与矩阵同一提交 |

## 明确不改

`v15/**/*.sql`、`v15/load.py`、`v15/**/setup_db.py`、`v15/**/test_*.py`、`v15/worker.py`、`v15/fake_llm.py`、`v15/protocol/render_prompt.py`、`v15/protocol/split_sql.py`、`v15/provider/{deepseek,errors,pricing,support,smoke,v15_provider.sql}.py` 与 sql、`server.py`、根 `pyproject.toml`、`v8/**`、`v13/**`、`docs/designs/v15-jaz-dev.md`。

不新增 `SQL_LOAD_ORDER` 项，因此 AGENTS 里「SQL 已追加进 load 序」对本计划是空操作。不新增 stage README。

## 只存在于忽略目录的文件

| 文件 | 内容 | 依赖 |
|---|---|---|
| `task.py` | `NOTE_V1`、禁子串检查、ceilings、池上限、`root_inputs(seal)`、`child_payload` 描述（给剧本用的 hops/role 递减） | 无 v15 运行时 |
| `script.py` | `OrderedScript`；`happy_replies(note, seal)`；`continue_then_tail_replies(note, seal)` | task |
| `db.py` | 幂等角色、只删指定库、`load_stage(..., "provider")`、seed、插池、worker/超级用户连接、`--drop-only` | `server.get_server`、`v15.load`、`v15.provider.support.seed_flash_profile` |
| `assert_e2e.py` | 3.4 的查询与优先级分类。无网络、无 provider import | 已静止的库 |
| `report.py` | 3.6 的 markdown 与擦除 | 结果 dict |
| `drive.py` | 模式、key、顺序 3.2、租约、CAP 捕获、退出码 | 以上全部；deepseek 仅 real 分支内部 import |
| `test_harness.py` | fixture 1 happy、fixture 2 continue-then-tail、keyless 子进程。库 `agent_demo_v15_harness`，结束必删 | drive 的库与断言函数，两个 fixture 之间整库重建 |
| `README.md` | 命令、退出码、`source ~/.zshrc`、禁止 `.env`、留库与 gate 的关系、报告不入库 | 无 |

`git add -f` 这些文件不在本计划的任何提交里。以后若要发布驱动，另写计划，只 force-add 上表路径，排除 `reports/` 与任何 `.env`。

# 5. Risks and migration

没有线上迁移，没有新表，没有新错误码。回退 = 停掉正在跑的 drive、`demo_v15/db.py --drop-only`、还原 M0/M1/M3 的文档提交。`agent_v15_*` 与十道 gate 的行为保持原样。

| 风险 | 表现 | 处理 |
|---|---|---|
| 模型不委托，直接字面量 `return` | `no_delegation` | 改 note，最多三次。不把 SQL 贴进 note |
| 只委托一层 | `shallow_chain` | note 写明 hops 3 要两次委托才允许字面量 |
| 叶继续委托 | 节点数 > 3，或 `recursion_ceiling` | `tail_ok` 仍可能成立；relay 失败。note 强调 hops 1 停止。`max_depth=4` 封顶 |
| 围栏、未加引号 return、散文、`DO` | 对应 failure_class | 三次 note。之后只写 §18 提案 |
| 不转发 note | 子 input 缺 note，`mission_not_forwarded` | 缩短 note，重复「原样复制 note」这一句。仍失败则停，不在本计划做 hook |
| 绑定名撞 input | `V15_DELIVERY_CONFLICT` 或语句 `P1524` | note 已指定 `down`。核对 3.9 |
| 思考 token 把单次调用拉得很长 | 成本升高或 `finish_length` | 池 `$2`；length 时才用 demo 私有 profile 的 `max_output_tokens=4096` |
| 高峰 / 假日多报 | `cost_used` 高于发票 | 报告引用 D28，不改 `pricing.py`，不加节假日日历 |
| 无幂等下 abandon 再试 | 供应商可能双计，`calls_used` 含 unknown | 接受。`max_io_attempts=2`。不在适配器里重试 |
| 429 | worker 睡 1 秒后同进程继续 | 不读 `Retry-After`，不另写节流 |
| 网络抖动 | `provider_uncertain` | note 预算外整库重跑一次 |
| 恰好 180s 租约 | mark 之后 `_lease_covers` 为假，函数「成功」返回，attempt 仍 leased | 使用 240s。断言把残留 leased 打成 `lease_skip` |
| CAP | `RuntimeError("quiescent cap")` | 捕获，留库，不加大 `CAP`，不自动重启 |
| 假静止 | 无 runnable 但有 leased | `lease_skip`，退出码 1 |
| 留着 demo 库去跑 gate | `DROP ROLE v15_owner` 失败 | 默认成功后删库；失败则打印警告。bootstrap 本身不删 gate 库 |
| 抄了 provider `setup_db` 的全量 DROP | 毁掉 `agent_v15_*` 或角色 | 3.3 的禁止项是实现约束 |
| 一个库里混用 FakeLLM 与 DeepSeek | 违反同质性 | 一次 drive 只有一个 provider 对象 |
| key 进报告或 git | 泄漏 | 擦除；gitignore；提交前 `git status`；禁止 `git add -A` |
| 把 demo 放进 `v15/` | gate rglob 扫到 `test_harness.py` | 路径固定在仓库根 `demo_v15/` |
| 为通过模型去改冻结提示 | 把证据跑成另一份规格 | 本计划没有这个步骤 |
| 深度 3 在预算内仍撞 CAP | 每层多轮失败 + reclaim 空转 | ceilings 会先用 `V15_ITERATION_EXCEEDED` / `V15_IO_EXHAUSTED` 收束。CAP 是最后的进程闸。预期 happy path 约十几步，四轮 × 四层量级仍远小于 256 |
| 子配置不是 flash | preflight `model_missing` 或 `model_not_allowlisted` | 根用 `FLASH_SCOPE`；子 `v15_resolve_child_config` 继承同一 scope。fake 的 `calls_used` 通过后，real 的第一跳 preflight 再挡一次 |
| `p_user` 被拿来塞任务 | 模型看不到 mission | 驱动传 NULL。任务只在 input `note` |
| 工作日 10 分钟服务端断连 | 本驱动 120s 先 abandon | 不加大 timeout。加大 timeout 必须同时加大租约，使租约 ≥ timeout+60 且覆盖 mark 损耗；那是另一处改动，默认不做 |

# 6. Implementation order

两次跟踪提交：M0、M1。M2 是本地真连，无提交。M3 是证据回填提交。M1/M2 不把 `demo_v15/**` 放进 `git add`。禁止 `git add -A` / `git add .`，禁止 `--no-verify`，禁止 force-push。提交说明沿用 `<版本>: <祈使句>`。

实现中若必须改 `v15` 的 py/sql：停下 demo 提交，另开里程碑，先用 FakeLLM 复现，串行跑受影响 stage 的**全部**既有 gate（provider 变更则至少 `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v15/provider/test_provider.py`，退出码 0），再单独提交。不得与 M0/M1/M3 混。

1. **M0（原子提交）**  
   把本计划写入计划文件。`.gitignore` 追加 `/demo_v15/`。此时还没有 demo 文件。  
   `git add` 只这两条路径。`git status` 确认无 `.env`、无 `demo_v15`。  
   提交：`v15: plan the deepseek tail-delegation demo`，推 `origin/main`。  
   无运行时文件，不重跑十道 gate，提交说明里不声称 gate 通过。

2. **本地库闸**  
   实现 `db.py`。`uv run python demo_v15/db.py` 打印 `[ready] agent_demo_v15`，超级用户能查到 `FLASH_SCOPE` 的 `llm.model = deepseek-flash`，且 `v15.v15_provider_abandon` 存在。worker 连接的 `session_user` 是 `v15_worker`。`--drop-only` 之后该库不存在，任一 `agent_v15_*` 库仍在（若之前有）。

3. **Fake happy path**  
   实现 `task.py`、`script.py`、`open_root`、`assert_e2e.py`、`report.py`、`drive.py` 的 fake 分支。  
   ```bash
   env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL \
     UV_NO_ENV_FILE=1 DEMO_MODE=fake \
     uv run python demo_v15/drive.py
   ```  
   退出码 0，stdout 含 `tail_ok relay_ok`，`calls_used=3`，报告落在 `demo_v15/reports/`，默认删库。`calls_used` 不为 3 则按 3.9 停，不进入第 4 步。

4. **Harness fixture 2 + keyless**  
   实现 `test_harness.py`。  
   ```bash
   env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL \
     UV_NO_ENV_FILE=1 \
     uv run python demo_v15/test_harness.py
   ```  
   退出码 0。覆盖：happy 的 `tail_ok`+`relay_ok`；`SELECT 1` 之后再尾委托时，绑定迭代 settled 为 1、根 attempt 总数为 2、`calls_used=4`；子进程 `DEMO_MODE=real` 无 key 退出码 2 且 stdout 为 `credentials_absent`。两只 fixture 用 `agent_demo_v15_harness`，结束必删。

5. **M1（原子提交，早于任何 real `complete`）**  
   按 3.7 改 `AGENTS.md`，按 3.6 改两份 README。  
   `git add AGENTS.md v15/provider/README.md v15/README.md`。  
   提交：`v15: allow the tail-delegation demo as a second real entry`，推 `origin/main`。  
   前置：第 3、4 步退出码已亲眼看到。这三份都是散文，不重跑十道 gate。

6. **M2 真连（本地，无提交）**  
   key 只来自环境。每次改 note 之前重跑第 3 步。最多三次计费全链，规则见 3.5。成功标准：退出码 0 且 stdout 以 `tail_ok` 开头。`relay_soft_fail` 仍算本里程碑通过。三次失败或 `未证明` 也进入第 7 步，不改提示词冻结文本。  
   命令：`DEMO_MODE=real uv run python demo_v15/drive.py`（非交互时先 `source ~/.zshrc`）。当时驱动自己不得持有未提交事务；这一点由 open 的 commit 与 worker 的 `_assert_idle` 保证。

7. **M3（原子提交）**  
   矩阵附录、台账 Demo 节、计划文件的 Run record 按实际结果填写。未证明就写未证明。  
   `git add` 只这三份：  
   `docs/reviews/v15-conformance-matrix-2026-09-29.md`  
   `docs/reviews/v15-deviation-ledger-2026-09-29.md`  
   `docs/plans/v15-demo-tail-delegation-plan-2026-09-29.md`  
   `git status` 确认没有 `demo_v15/`、没有报告、没有 `.env`。  
   提交：`v15: record the tail-delegation demo evidence`，推 `origin/main`。  
   不重跑十道 gate（无 py/sql 变化）。不把报告内容抄进矩阵，只抄结果词与日期。

---

## 执行索引

| 工作项 | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| M0 计划入库 | 计划 + gitignore 行进入仓库 | 两路径提交成功，无 demo 文件、无 .env 混入 | 本文件、`.gitignore` | 无 | 小 |
| 本地库闸 | demo 自建库（幂等角色、只删己库、十文件全载、flash seed） | `uv run python demo_v15/db.py` 打印 `[ready] agent_demo_v15`；worker 连接 session_user=v15_worker；`--drop-only` 后己库消失、agent_v15_* 不受影响 | `demo_v15/db.py`（gitignored） | M0 | 小 |
| Fake happy path | 有序剧本驱动三层链全绿 | `DEMO_MODE=fake` 退出码 0、stdout `tail_ok relay_ok`、calls_used=3、报告落盘、默认删库 | `task.py`/`script.py`/`assert_e2e.py`/`report.py`/`drive.py` fake 分支 | 库闸 | 中 |
| Harness | fixture-2（continue 后尾委托）+ keyless 子进程 | `test_harness.py` 退出码 0（绑定迭代 settled=1、根 attempt=2、calls_used=4；无 key real 退出码 2） | `test_harness.py`（库名 `_harness`，结束必删） | fake path | 小 |
| M1 例外句提交 | AGENTS 两入口文案 + 两份 README 对齐 | 三散文文件提交推送，早于任何真连 `complete` | `AGENTS.md`、`v15/provider/README.md`、`v15/README.md` | fake+harness 绿 | 小 |
| M2 真连（本地无提交） | deepseek-flash 跑通尾委托链 | 退出码 0 且 stdout 以 `tail_ok` 开头（relay_soft_fail 也算过）；最多三次计费全链 | `drive.py` real 分支（环境 key） | M1 | 中（含迭代） |
| M3 证据回填 | 矩阵 Demo evidence 行 + 台账 Demo 节 + 计划 Run record | 三文档按实况提交（未证明就写未证明），无 demo_v15/ 混入 | 矩阵、台账、本文件 | M2 结束（无论成败） | 小 |

## References

- 冻结规格：`docs/designs/v15-jaz-dev.md` rev 9（§0.2/§0.25/§4.5.5/§6.5/§18）
- provider 计划与实现：`docs/plans/v15-real-provider-deepseek-plan-2026-09-29.md`、`v15/provider/`
- demo 先例：`demo_v13/`（README）、`docs/plans/v13-minimal-agent-loop-demo-2026-09-23.md`、`.gitignore:31-33`、`da4663e`
- 断言先例：`v15/tree/test_tree.py` attempts helper
- DeepSeek 事实：`docs/plans/v15-real-provider-deepseek-plan-2026-09-29.md` Background（模型名/计价/无幂等/并发限额）

## Run record

- 日期：2026-09-29
- note：NOTE_V1；首次实跑通过，真实全链预算用 1/3，note 修改 0 次
- 结果：`tail_ok relay_ok`
- failure_class：无
- 成本：$0.001257786
- 调用数：calls_used=3
- codex 评审附注：报告模板断言明细块已随后补入驱动；本跑报告为旧模板，逐条断言由已评审的 assert_e2e 层合取得出。
