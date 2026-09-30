# v15 D2 轨迹回放（stage 12 replay）实施计划

2026-10-01。Loop Orchestrate turn 3 / D2。方案来源：Oracle 双轨（codex `gpt-6-astra-fast-xhigh` chat 75204C + grok-4.7 chat 6FE62E，group 825CB68A），两轨独立收敛后由主 agent 合成裁定。冻结检查：11+1 道既有 gate 全绿 + 新 gate 绿 + Oracle 双轨 PASS；无真栈判据（replay-only 契约）。

## 0. 已验证的事实基础（主 agent 实跑）

- `llm_requests.logical_digest` 已是 canonical prompt hash：`md5((request - 'attempt_id')::text)`，`request = {attempt_id, messages}`，messages 为 begin 事务内 base→enter→send 折叠后的最终数组（`v15_io.sql` 首试路径）。重试路径已强制与已存摘要相等。**不需要新列/新键/Python 重折叠，刹车线（迁移既有表）不触发。**
- worker 缝（`v15/worker.py:396` 一带）：`provider = self.fakellm`（注入位）；`provider.complete(attempt["logical_digest"], n, attempt["request"], llm_config)` 在任何事务之外调用；`attempt["request"]["attempt_id"]` 可见。ReplayLLM 零 worker 改动即可接入。
- 无任何 gate 对 `v15_govern_known_code`/`v15_io_sqlstate` 全集做快照/计数断言（grep 实证）——追加码安全。
- 这两个函数只有 `v15/provider/v15_provider.sql` REPLACE（govern CREATE 原始体、return_hooks 不碰）——stage 12 超集基线 = provider 文件现行体（含 `V15_VALIDATION_FAILED`/P1540）。
- **唯一硬阻塞**：`v15/return_hooks/test_return_hooks.py:317` 断言 `len(SQL_LOAD_ORDER) == 11`。按 D1 先例（provider gate 的「provider is last SQL」改 `files_through` 前缀形，Oracle 裁定后落地）处理：改为 `files_through("return_hooks")` 前缀恰 11 文件——**同一 stage 的检查强度不变，非放宽**；矩阵记录该断言迁移。

## 1. 设计裁定（双轨共识 + 三处主 agent 裁决）

| # | 裁定 | 依据 |
|---|---|---|
| 1 | **不启用 `supply_llm_response`**。§9.4 五个预留效应每个 phase 仍 `P1506`；gate 必须锁死这条。 | 两轨一致：效应闭集是冻结不变量；settle 已消费 worker 供给的 response，换一个不联网的供给方即可。 |
| 2 | 重放走**既有唯一 worker 路径**：claim → begin（hook/折叠/预留/摘要）→ mark → ReplayLLM.complete（事务外）→ 既有清理/切分/分类 → settle → 执行/子树/送达。不 INSERT settled、不绕过 complete/exit hook。 | 两轨一致。 |
| 3 | 在线分歧只认一条：**`logical_digest` 与 trace 录制的同坐标摘要相等**。assistant 正文是重放输入，经下一轮 base 进入下一摘要；末轮由终局 oracle 断言。不做 jaz 的消息编辑签名/observation 重渲染。 | 两轨一致。 |
| 4 | hash 复用 `llm_requests.logical_digest`；trace 记 `logical_digest`（32 hex）+ digest_scheme 标识。禁止 ALTER 既有表、禁止往 request JSON 塞键。 | 两轨一致；若实现发现摘要公式与 §0 不符 → 停下问用户。 |
| 5 | 记账：`calls_used` 按 settle 现行规则加 `reserved_calls`；`cost_usd`（attempt 与 response 顶层）与池 `cost_used` 增量固定 0；tokens 保留与否不做断言（fake 侧本就无）。trace 保留 `recorded_cost_usd` 仅作对照，重放必须忽略。 | 两轨一致。 |
| 6 | 新 stage `v15/replay/`（12），`SQL_LOAD_ORDER` 末尾追加；不并进 provider（M4 已封口）。无新表、无新列、无 GUC、无会话标志、无 replay_sessions 表。 | 两轨一致。 |
| 7 | 错误码两枚（表尾追加）：`V15_REPLAY_DIVERGED`/`P1541`（摘要/坐标/终局不一致）；`V15_REPLAY_MISSING`/`P1542`（库已进入真实 LLM 尝试、trace 无该坐标帧）。**主 agent 裁决**：采纳 grok 命名；trace **格式**错误（JSON/版本/类型/重复坐标）在驱动侧本地异常拒绝，不进 SQL；SQL 内值形状错误沿用 `P1524`。两码均为回滚类异常，不是 invoke 终态码，不进 §9.5 四个可保留 abort 码；hook 若返回其名，既有归一收成 `V15_HOOK_ABORT`。 | codex 建议 P1542=TRACE_INVALID，grok 建议 MISSING；取后者因格式校验天然在驱动进 SQL 前，SQL 面最小。 |
| 8 | guard/export RPC 全部 `SECURITY DEFINER`、`search_path=pg_catalog`、owner `v15_owner`、revoke PUBLIC、grant `v15_worker`（内部 path helper 只授 owner）；worker 不获得基表 SELECT。 | 两轨一致。 |
| 9 | **主 agent 裁决（v1 范围裁剪）**：trace v1 = grok 导出形状（见 §3），**不做** codex 的完整 NodeEnvironment 捕获——环境同一性由 fixture 纪律（同一 setup 代码建 manifest/hook/pool）+ 摘要传递性（hook 持久消息进折叠进摘要）承担；环境全捕获记为后续项。 | loop 预算现实；两轨都允许「实施时核对 config 投影」，v1 以 fixture 纪律替代。 |
| 10 | 事务边界：guard 函数零写入，可从 complete()（事务外）经独立只读连接调用；**全回滚负例必须在 gate 里直接做**（同一事务 claim+begin+assert 坏摘要 → P1541 → 回滚零残留），不经 worker。经 worker 的 P1541 抛点在 begin 已提交后会留 leased attempt——不为其加补偿终态，gate 不用该路径证明回滚。 | grok 详述，codex 同义。 |

## 2. 明确不做（负空间）

- 不重放 `n>1`、`failed`/`unknown` attempt、provider reject/abandon、未终态树、一树多池（导出拒绝）。
- 不改：`v15_schema.sql`、`v15_io.sql`、`v15_provider.sql`、`v15/worker.py`、`v15/fake_llm.py`、return_hooks 行为、旧 gate 断言（除 §0 的 317 行前缀化迁移）。
- 不做崩溃后续播；中断走既有 reclaim 语义（reclaim 产生 n=2 → trace 无该坐标 → 失败，重建库重跑）。
- 不把 trace 写进 `invoke_events`；不在重放里调 `v15_io_terminal` 伪造终态。

## 3. Trace v1 格式（`v15_replay_export` 产出）

```
{ version: 1,
  pool: null | {calls_limit, cost_limit},
  pool_outcome: null | {calls_used, cost_used},
  invokes: [ { path, depth, status, fatal, error_code, return_value,
      steps: [ { iteration, result_kind,
          logical_digest,        -- 32 hex 或 null（无 LLM 迭代）
          response_content,      -- settled attempt response->>'content' 或 null
          recorded_cost_usd,     -- 文本；重放忽略
          statements: [ {stmt_index, sql_digest, kind, status, bind_name} ],
          repl_output, repl_exception_code } ],
      bindings: [ {name, kind, provenance, tool_name, value} ],
      blackboard: [ {key, value} ] } ] }
```

- 排序固定：invokes 按 path、steps 按 iteration、statements 按 stmt_index、bindings 按 name、blackboard 按 key。
- path：根=空串；子=父 path + `/` + `iteration:stmt_index:bind_name`（沿父 statements 上 `child_invoke_id` 命中行；非恰好一行 → `P1523`；禁 uuid 拼接）。
- 导出资格：闭包（`v15_repl_closure`）内全部终态；无 open request；每 request 恰一 attempt 且 `n=1` `settled`；全树同一 pool（可全 null）；否则 `P1523`/`P1524`。**不丢失败 attempt 只留成功**。
- 驱动索引键 `(path, iteration)`；重复键=fixture 损坏，驱动侧拒绝。禁止按摘要找帧（同 prompt 不同轨迹）。

## 4. SQL 面（`v15/replay/v15_replay.sql`）

| 函数 | 合同 |
|---|---|
| `v15_replay_invoke_path(uuid) RETURNS text` | 内部 STABLE DEFINER，只授 owner。 |
| `v15_replay_attempt_context(p_attempt_id) RETURNS jsonb` | worker 只读；键闭集 `{attempt_id, invoke_id, iteration, logical_digest, lease_owner, path, call_started}`；非 leased → `P1523`。 |
| `v15_replay_assert_digest(p_attempt_id, p_owner, p_expected_digest) RETURNS void` | 锁序=invoke→attempt FOR UPDATE；复用 settle 前置检查（终态 `P1502`、fence/holder/request open/迭代 llm 既有码）；摘要非 32 小写 hex → `P1524`；不等 → `P1541`（DETAIL 只放两摘要）；相等零写入幂等返回。 |
| `v15_replay_missing(p_attempt_id, p_owner) RETURNS void` | 同上前置后无条件 `P1542`。 |
| `v15_replay_export(p_root) RETURNS jsonb` | STABLE DEFINER worker 可执行；资格校验+§3 形状。 |
| `CREATE OR REPLACE v15_io_sqlstate` / `v15_govern_known_code` | 以 provider 现行体为基线的超集 + 两新码；装载后 `V15_PROVIDER_REJECTED`→P1539、`V15_VALIDATION_FAILED`→P1540 等全部保持。 |

`v15/replay/setup_db.py`：照 return_hooks 的 bootstrap（含 `v15_hook_return_type` 与 govern hook 角色全集）+ `load_stage(..., "replay")`。

## 5. Python 面

- `v15/replay/trace.py`：TraceV1 校验（version/类型/闭集/坐标唯一）、`export_trace(conn, root)`（REPEATABLE READ 只读事务）、`load/write_trace`、比较投影的**唯一 normalizer**（JSON 数字无损，不经 float）。
- `v15/replay/replay.py`：`ReplayLLM`——构造时持 trace 索引与 owner；`complete(logical_digest, n, request, llm_config)`：取 `request.attempt_id` →（独立只读连接）`attempt_context` → `(path, iteration)` 查帧：无 → 调 `v15_replay_missing`（其异常透传）；有 → `assert_digest` → 通过则返回 `{"content": 帧内容, "cost_usd": 0}` 副本。replay 异常必须先于 ProviderRejected/ProviderUncertain 被识别透传，不得转 reject/abandon，不得 fallback FakeLLM。
- gate 内录制用测试本地完成器（可返回非零 cost_usd 对照），**不改 `v15/fake_llm.py`**。

## 6. 实施顺序

0. 只读核验：return_hooks/provider SQL 里两个函数最终体；worker `complete()`/settle 的 cost_usd 消费与 §0 假设一致；317 行断言现状。任一不符 → 停下问用户。
1. `v15_replay.sql` + `load.py` 追加（原子）：装载后 SELECT 验证超集无丢码、`supply_llm_response` 在 send 仍 `P1506`。
2. `test_return_hooks.py:317` 前缀化迁移（`files_through("return_hooks")` 恰 11）。
3. path/context/export + `setup_db.py`：单 invoke 手动短流程验证导出摘要==库列；n=2 行拒绝导出。
4. assert/missing 两函数：同事务负例最小形式跑通（P1541 回滚零残留）。
5. `trace.py`/`replay.py` + 双库 happy path（根+一子、两轮 LLM、enter hook 持久消息、非零录制费）。
6. `test_replay.py` 全断言面 + README/矩阵/规格表尾/台账。
7. 回归 11+1 gate + 新 gate；一次里程碑提交推送。

## 7. gate 断言面（`uv run python v15/replay/test_replay.py`）

Happy：双库录制→重放，投影逐字段（§3 全字段+span 投影 llm_query enter/send/complete/exit、无 provider_rejected 事件、attempt settled/call_started/calls_charged/n=1、calls_used 相等、cost 全 0 且 recorded_cost_usd≠0、同摘要双节点按坐标正确供给、父绑定 provenance=delivery、无新 v15 表）。同 fixture 二次重放幂等。空 statements（散文 continue）迭代可导出重放。
负例：坏摘要→P1541 零残留（同事务）；hook 多写一条持久消息→摘要变→P1541；非 32hex→P1524；缺帧同事务→P1542 零残留；settled 后 assert→P1502；非 worker 角色→P1522；owner 不符→既有码；导出未终态/n≠1/两池→P1523/P1524；已结算迭代二次 begin→P1523；hook 发 `supply_llm_response`→P1506；重放后 trace 有剩帧→测试失败；坏 JSON/版本/重复坐标→驱动本地异常。
安全：worker 不能 SELECT 基表；repl/PUBLIC 不能执行 replay RPC；函数属性（owner/search_path/grants）断言。

## 8. 文档落点

- 规格 `docs/designs/v15-jaz-dev.md`：错误码表尾 +2 行（注明非终态码、不入 §9.5 保留集）；§9.4 不动；stage 清单/装载序提及 stage 12。
- `docs/reviews/v15-conformance-matrix-2026-09-29.md`：新行（replay 不变量 + 317 行断言迁移记录）。
- 偏差台账：一句「D2 不启用 supply_llm_response，摘要复用 logical_digest」。
- `v15/README.md`：12 文件装载序与新 gate 命令。

## 9. 停止条件（停下问用户）

- 发现摘要公式/worker 缝与 §0 不符且无法零改动接入。
- 需要新表/新列/GUC 才能继续（刹车线）。
- 除 317 行外发现任何既有 gate 断言必须改动才能装载 stage 12。

## 10. Orchestration record (turn 3)

### Step 0 verification (PASS)

- `v15_io_sqlstate` / `v15_govern_known_code` last REPLACE: `v15/provider/v15_provider.sql`. `V15_VALIDATION_FAILED`→P1540 stays in `v15_loop_sqlstate`; provider io map omits P1540 (locked by `test_provider.py`). Stage 12 supersets copy provider bodies + P1541/P1542 only.
- Worker seam: `v15/worker.py:362` `provider = self.fakellm`; mark via `_run` then `_assert_idle`; `:396` `complete(logical_digest, n, request, llm_config)` with idle connection. Digest `md5((request-'attempt_id')::text)`. ReplayLLM plugs in with zero worker edits. Settle writes `response.cost_usd` onto the attempt and into pool `cost_used`; replay returns `0`.
- `test_return_hooks.py:317` is `len(SQL_LOAD_ORDER) == 11 and len(full) == 11`.

### Line 320 ruling (user, turn 3)

320 (`files_through("return_hooks") == SQL_LOAD_ORDER`) is the same last-stage family as 317. Allowed prefixization:
- 317 → `check("return_hooks prefix has eleven files", len(full) == 11)`
- 320 → `check("stage through return_hooks", files_through("return_hooks") == full)`
- 318/319 unchanged. Drop unused `SQL_LOAD_ORDER` import if it becomes unused.
- New gate MUST take the global shape: `len(SQL_LOAD_ORDER)==12`, last file `v15_replay.sql`, `files_through("replay") == SQL_LOAD_ORDER`, first 11 == `files_through("return_hooks")`.
- Matrix records both 317+320 (global→prefix, D1 precedent, not a relaxation).
- Any further existing-gate assertion that must change → stop and ask.

### Work items

- [x] Item 1: `v15/replay/` SQL+Python+setup, `load.py` append, 317/320 migration, `test_replay.py` §7 surface, docs (§8), 12+1 gates green
- [ ] Item 2: milestone commit + push `rp/agent/3e700836-agent`

### Run record (Item 1, 2026-10-01)

Serial `uv run python v15/<stage>/test_<stage>.py` after prefixizing 317/320. `setup_db.py` drops every `agent_v15_` DB; gates were not overlapped.

| gate | command | exit |
|---|---|---|
| schema | `uv run python v15/schema/test_schema.py` | 0 |
| namespace | `uv run python v15/namespace/test_namespace.py` | 0 |
| config | `uv run python v15/config/test_config.py` | 0 |
| protocol | `uv run python v15/protocol/test_protocol.py` | 0 |
| repl | `uv run python v15/repl/test_repl.py` | 0 |
| io | `uv run python v15/io/test_io.py` | 0 |
| loop | `uv run python v15/loop/test_loop.py` | 0 |
| tree | `uv run python v15/tree/test_tree.py` | 0 |
| govern | `uv run python v15/govern/test_govern.py` | 0 |
| provider | `uv run python v15/provider/test_provider.py` | 0 |
| return_hooks | `uv run python v15/return_hooks/test_return_hooks.py` | 0 |
| replay | `uv run python v15/replay/test_replay.py` | 0 |

Key measured assertions (`test_replay.py`):

- load order 12; last file `v15_replay.sql`; `files_through("replay")` = `SQL_LOAD_ORDER`; first 11 = `files_through("return_hooks")`
- `v15_io_sqlstate` maps P1541/P1542, omits P1540; loop map keeps P1540
- same-txn bad digest → P1541 (DETAIL two hex digests `bb1ca411…` vs `0000…`), attempt count 0 after rollback
- same-txn missing → P1542, attempt count 0 after rollback
- recording `cost_used=3.75` with `recorded_cost_usd=['1.25','1.25','1.25']`; replay `cost_used=0`; `calls_used` equal `(3, 3)`
- digest_scheme `md5((request-'attempt_id')::text)`; same-digest twins both `bb1ca4113140537d19da7662e348a768` supplied by `(path, iteration)`
- `supply_llm_response` still P1506; extra persistent hook message → P1541; leftover frame `[('', 9)]`
- no new v15 tables (21 names)

Stop conditions did not fire. Item 2 (commit/push) deferred.

