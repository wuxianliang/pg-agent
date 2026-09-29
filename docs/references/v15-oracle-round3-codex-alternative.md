# v15 Chunk C — codex 轨道备选稿（未采用，供评审对照）

## §9　Hook 事件、效应与黑板

### 9.1　唯一 dispatcher 与阶段边界

`v15_on_phase` 是 v15 唯一的 Hook dispatcher。Stage 9 MUST 在 `v15/govern/v15_govern.sql` 中以 `CREATE OR REPLACE FUNCTION` 替换前缀阶段的 scaffold body；其他 SQL 文件 MUST NOT 再定义或替换该函数（§0「Hook 效应闭集」；§3 `hook_defs`、`invoke_hooks`）。

其规范接口为：

```text
v15_on_phase(
  p_invoke_id uuid,
  p_span text,
  p_phase text,
  p_io jsonb DEFAULT '{}'::jsonb
) → v15_phase_effect
```

调用方 MUST 已按 §4 锁定 invoke、验证 lease/fence，并在涉及预算池时按 §11.4 先锁定预算池。`v15_on_phase` MUST 在调用方事务内执行；MUST NOT 自行提交、开启自治事务或在异常后保留事务外副作用。

每次调用 MUST 依次执行：

1. 调用 `v15_assert_invoke_manifest(p_invoke_id)`。
2. 验证 `(p_span, p_phase)` 属于 §9.5 的闭集。
3. 解析本阶段 active hooks（§9.2）。
4. 构造一次不可变 phase snapshot（§9.3）。
5. 向 `invoke_events` 追加本次 span/phase 事实；seq MUST 使用该 invoke 的唯一顺序分配器（§0「事件 append-only」；§3 `invoke_events`）。
6. 在互相隔离的子事务中调用每个 handler（§9.4）。
7. 验证并组合全部返回效应（§9.6—§9.8）。
8. 由 dispatcher 执行预算 reserve/settle/refund；handler MUST NOT 直接更新 `budget_pools`（§11.4）。
9. 在所有 handler 已返回且效应组合成功后，统一应用 blackboard writes，并至多递增一次 generation（§9.9）。
10. 返回一个 `v15_phase_effect`；状态机对该结果的解释以 §4 为准，dispatcher MUST NOT 越权执行 invoke 状态转移。

上述任一步骤以回滚类错误失败时，本次 phase event、审计事件、预算变更和 blackboard 变更 MUST 全部回滚。

### 9.2　Activation resolution

Active hook 顺序 MUST 由数据库状态确定，MUST NOT 依赖查询计划、OID 大小、JSON 对象键顺序或 Python 容器顺序。

解析顺序固定为：

1. **baseline**：由当前 manifest 指定并在 invoke open 时安装的 baseline hooks，按 `invoke_hooks.ordinal` 升序；
2. **propagating**：从最外层祖先到当前 invoke，即按 `source_depth` 升序，再按各来源中的 `ordinal` 升序；
3. **local**：仅当前 invoke 的 local hooks，按 `ordinal` 升序。

完全排序键为：

```text
(channel_rank, source_depth, ordinal, invoke_hook_id)
```

其中 `channel_rank` 固定为 `baseline=0`、`propagating=1`、`local=2`。`invoke_hook_id` 仅作为最后的确定性 tie-breaker；正常写入路径 MUST 拒绝同一 channel/source/ordinal 的重复项。

baseline hook MUST 来自 singleton manifest 的 baseline 列表。调用方不能删除、替换、重排或遮蔽 baseline hook；尝试这样做 MUST 以 `V15_BASELINE_IMMUTABLE` 失败（§0「强制治理清单」；§3 `governance_manifest`、`invoke_hooks`）。

propagating hook 的来源链在 child open 时冻结。祖先随后发生的 hook 变更 MUST NOT 追溯修改已创建 child。local hook MUST NOT 传播给 child（§8「child inheritance」）。

### 9.3　不可变 phase snapshot

同一次 dispatch 的所有 handler MUST 接收字节语义相同的 snapshot。较早 handler 的返回效应 MUST NOT 改写较晚 handler 所见 snapshot；效应只能在全部 handler 返回后组合。

snapshot 顶层形状冻结为：

```json
{
  "schema_version": 1,
  "phase": {
    "span": "invoke|llm_query|repl_exec",
    "name": "enter|send|complete|exit",
    "event_seq": 0
  },
  "invoke": {
    "invoke_id": "uuid",
    "root_invoke_id": "uuid",
    "parent_invoke_id": "uuid-or-null",
    "depth": 0,
    "status": "text",
    "iteration_no": 0,
    "statement_ordinal": null
  },
  "io": {},
  "config": {
    "digest": "sha256-hex",
    "value": {}
  },
  "inputs": [
    {
      "name": "text",
      "kind": "input|scope|var",
      "value": null,
      "show_in_prompt": true,
      "revision": 0
    }
  ],
  "messages": [
    {
      "message_id": "uuid",
      "role": "system|user|assistant|observation",
      "content": "text",
      "persistent": true
    }
  ],
  "exec_result": null,
  "recursion_available": true,
  "blackboard": {
    "generation": 0,
    "values": {}
  },
  "active_hooks": [
    {
      "invoke_hook_id": "uuid",
      "name": "text",
      "channel": "baseline|propagating|local",
      "source_depth": 0,
      "ordinal": 0,
      "handler_oid": 0,
      "handler_digest": "sha256-hex",
      "baseline": false
    }
  ]
}
```

下列规则适用：

- `io` MUST 是调用阶段的冻结 I/O 事实；不存在的字段 MUST 缺席，MUST NOT 以虚构的零值冒充。
- `config.value` MUST 等于 invoke open 时冻结的解析结果；`config.digest` MUST 等于 `invokes.config_digest`（§8）。
- `inputs` MUST 包含 hidden bindings；`show_in_prompt=false` 只影响 prompt rendering，不剥夺 Hook 或 `jaz.var` 的寻址能力（§7）。
- `blackboard.values` MUST 来自 snapshot generation 对应的完整可见值。
- `active_hooks` MUST 列出本阶段实际参与解析的完整有序列表，包括当前 handler 自身。
- snapshot 构造后 MUST 视为不可变值；dispatcher MUST NOT 把 handler 的表写入、临时表或 session GUC 作为隐式输入。

### 9.4　Handler 注册与调用合同

每个 `hook_defs.handler` MUST 是精确签名为下列形状的 regprocedure：

```text
hook_name(p_snapshot jsonb) RETURNS jsonb
```

注册函数 MUST 验证 `pg_proc` 与 `pg_language`，并拒绝不满足以下任一条件的 handler：

- `provolatile = 's'`，即 STABLE；VOLATILE 与 IMMUTABLE 均 MUST NOT 注册；
- language 只能是 `sql` 或 `plpgsql`；`c`、`internal`、未受信任过程语言及扩展语言 MUST NOT 注册；
- owner 必须是 NOLOGIN 角色 `v15_hook_<normalized-hook-name>`；
- handler 必须是 `SECURITY DEFINER`；
- `proconfig` 必须将 `search_path` 精确固定为 `pg_catalog`，不得附带可写 schema；
- owner 对 v15 kernel tables MUST 没有直接 `INSERT`、`UPDATE`、`DELETE`、`TRUNCATE` 或 `REFERENCES` 权限；
- PUBLIC MUST 没有该 handler 的 EXECUTE 权限；
- 参数必须恰为一个 `jsonb`，返回值必须恰为 `jsonb`，MUST NOT 返回 set。

注册时 MUST 计算 handler digest。digest 输入至少包括 identity arguments、返回类型、language、`provolatile`、`prosecdef`、owner、`proconfig` 与 `pg_get_functiondef(oid)` 的 UTF-8 表示。`hook_defs.handler_digest`、`invoke_hooks.handler_digest` 与运行时重算结果必须一致。

dispatcher MUST 通过已存 regprocedure OID 生成限定调用，等价于：

```text
format('SELECT %s($1)', handler_oid::regprocedure)
```

调用解析 MUST NOT 依赖 dispatcher 的 `search_path`。同一数据库 session 中发生的 `CREATE OR REPLACE` 必须在下一次 dispatch 可见；dispatcher MUST 每次重验 digest，MUST NOT 仅依赖已缓存的 OID 或 prepared-plan 元数据。

任一 active handler 的 OID 消失、签名改变、owner/config 改变或 digest 漂移，MUST 以 `V15_MANIFEST_DIGEST` fail-closed。对 optional hook 也采用同一码，因为 active hook definition 是 invoke 冻结治理输入的一部分，MUST NOT 另设同义 drift 错误码。

每个 handler 调用 MUST 位于独立 PL/pgSQL exception block 所形成的子事务中；实现 MUST 使用该机制获得 SAVEPOINT 语义，MUST NOT 在函数中执行 SQL transaction-control 命令。

- 非 baseline handler 抛出异常时，dispatcher MUST 回滚该子事务，丢弃该 handler 的全部效应和数据库副作用，追加一条 `V15_HANDLER_FAILED` 审计事件，然后继续下一个 handler。
- 审计 payload MUST 包含 `invoke_hook_id`、hook name、原始 SQLSTATE、经长度限制的 message 与 message digest；MUST NOT 包含 snapshot、secret binding 或完整 provider payload。
- baseline handler 抛出异常时，dispatcher MUST 转换为 `V15_GOVERNANCE_FAULT` 并使整个 phase 事务失败；MUST NOT 降级继续。
- handler 正常返回 SQL `NULL`、非对象 JSON、未知 schema version 或无效字段时，视为 `V15_HOOK_EFFECT`，不视为 handler exception。

### 9.5　Span × phase 与效应 allowlist

合法阶段与效应闭集如下。表中未列出的 span/phase MUST 以 `V15_INVALID_TRANSITION` 失败；未列出的效应 MUST 以 `V15_EFFECT_FORBIDDEN` 失败。

| Span | Phase | 允许的 Hook 效应 | budget directive |
|---|---|---|---|
| `invoke` | `enter` | `abort`、`disable_recursion`、`add_inputs`、`drop_inputs`、`blackboard_write` | 无 |
| `invoke` | `exit` | `blackboard_write` | 无 |
| `llm_query` | `enter` | `abort`、`add_messages`、`drop_messages`、`blackboard_write` | `reserve` |
| `llm_query` | `send` | `abort`、`add_messages`、`drop_messages`、`blackboard_write` | `reserve` 的确认或缩紧 |
| `llm_query` | `complete` | `abort`、`add_messages`、`drop_messages`、`blackboard_write` | `settle`、`refund`、`unknown_charge` |
| `llm_query` | `exit` | `blackboard_write` | 无 |
| `repl_exec` | `enter` | `abort`、`blackboard_write` | `statement_timeout_ms` |
| `repl_exec` | `send` | `abort`、`blackboard_write` | `statement_timeout_ms` |
| `repl_exec` | `complete` | `abort`、`modify_exec_result`、`blackboard_write` | 无 |
| `repl_exec` | `exit` | `blackboard_write` | 无 |

`invoke/exit` 除 `blackboard_write` 外 MUST 接受零效应；即使效应值看似 no-op，也 MUST 按字段存在性拒绝。

下列名称为保留效应，在 v15 的任何 span/phase 都 MUST 被拒绝：

- `supply_llm_response`
- `supply_invoke_result`
- `modify_invoke_result`
- `supply_exec_result`
- `modify_llm_response`

保留名称 MUST NOT 被忽略、透传或解释为普通 JSON；出现即 `V15_EFFECT_FORBIDDEN`（§0「效应代数闭集」）。

### 9.6　Handler response 形状

handler response 顶层 MUST 是 JSON object，且只允许以下键：

```json
{
  "schema_version": 1,
  "action": "continue|abort",
  "fatal": false,
  "error": {
    "code": "V15_*",
    "message": "text",
    "detail": {}
  },
  "messages": [
    {
      "op": "add|drop",
      "message_id": "uuid-or-null",
      "role": "system|user|observation",
      "content": "text-or-null",
      "persistence": "transient|persistent"
    }
  ],
  "exec_result": {},
  "recursion_available": false,
  "input_adds": [
    {
      "name": "text",
      "value": null,
      "show_in_prompt": true
    }
  ],
  "input_drops": ["name"],
  "blackboard_writes": {
    "key": null
  },
  "budget": {
    "operation": "reserve|settle|refund|unknown_charge",
    "pool_id": "uuid",
    "amount": 0,
    "statement_timeout_ms": 0
  }
}
```

除 `schema_version` 与 `action` 外，其余键可缺席。字段存在性具有语义；MUST NOT 把“缺席”与 JSON `null` 自动合并。

规则如下：

- `action='continue'` 时 `fatal` 默认为 `false`，`error` MUST 缺席。
- `action='abort'` 时 `error.code` 与 `error.message` MUST 存在；`fatal` 默认为 `false`。
- `error.code` MUST 是 §13 中已冻结的符号代码。
- `recursion_available` 若存在，值只能为 `false`；hook MUST NOT 重新启用已被禁用的递归。
- `messages.op='add'` 时必须提供 role、content、persistence；`message_id` 必须缺席。
- `messages.op='drop'` 时必须只提供已存在于 snapshot 的 `message_id`。
- persistent message 在组合成功后写入 `llm_messages`；transient message 只进入本次 attempt request，MUST NOT 写入 `llm_messages`。
- `budget` 不是第九种普通 Hook 效应，而是 dispatcher 专用 directive。只有内置治理 handler 可以返回；optional/custom handler 返回该键 MUST 以 `V15_EFFECT_FORBIDDEN` 失败。
- 未知顶层键、未知嵌套键、负数 amount、零或负 timeout、非法 UUID、非法 binding name 或超出 manifest 大小上限的值，均 MUST 以 `V15_HOOK_EFFECT` 失败。

### 9.7　效应组合

dispatcher MUST 按 §9.2 的 activation 顺序收集效应，并在全部 handler 返回后一次组合。组合规则冻结如下：

1. **abort**  
   多个 abort MUST 合并为一个 abort。`fatal` 使用逻辑 OR；任一 `fatal=true` 即最终 fatal。`error` 形成按 handler 顺序排列的数组，外层错误 message 为稳定的分组摘要，MUST NOT 只保留最后一个错误。

2. **add_messages**  
   按 handler 顺序及各 response 内数组顺序追加。完全相同的 JSON message 不去重，因为顺序和重复均可影响模型输入。

3. **drop_messages**  
   以 `message_id` 集合合并；重复 drop 合并为一次。drop 不得指向 system bootstrap message、当前 explicit user input message或不在 snapshot 中的 message。

4. **add 与 drop 冲突**  
   同一 dispatch 中不得先添加再删除逻辑相同的 message；无法用 snapshot `message_id` 表达的目标 MUST 拒绝。冲突为 `V15_EFFECT_CONFLICT`。

5. **disable_recursion**  
   采用单调 AND；任何 `false` 使结果为 `false`，后续 hook 不能恢复。

6. **input_adds**  
   同名、JSONB 值与 `show_in_prompt` 均相等时 coalesce 为一次；同名但任一内容不等时 `V15_INPUT_CONFLICT`。

7. **input_drops**  
   以规范化 name 集合合并。相同 name 同时被 add 与 drop 时 `V15_INPUT_CONFLICT`。

8. **modify_exec_result**  
   一个 response 中出现 `exec_result` 即表示完整替换候选。多个候选按 JSONB equality 相等时 coalesce；不等时 `V15_EFFECT_CONFLICT`。MUST NOT 做深合并。

9. **blackboard_write**  
   同 key 的 JSONB 值相等时 coalesce；不等时 `V15_BLACKBOARD_CONFLICT`。JSON `null` 是合法值，不表示删除。

10. **budget directive**  
    必须来自唯一适用的内置治理 hook。多个不同 pool、operation、amount 或 timeout 值不得按宽松规则合并；不相等即 `V15_EFFECT_CONFLICT`。

所有 equality 均为 PostgreSQL `jsonb` equality；MUST NOT 使用文本序列化、对象插入顺序或 host-language identity。

### 9.8　消息、输入与执行结果的应用时点

组合后的变更 MUST 按下列顺序应用：

1. 验证最终 abort 与 fatal；
2. 执行预算 directive；
3. 应用 persistent message 变更；
4. 形成仅供本次 attempt 使用的 transient message 列表；
5. 应用 invoke-enter input add/drop；
6. 形成 `exec_result` 替换值；
7. 应用 blackboard writes；
8. 返回 `v15_phase_effect`。

任何步骤失败时，之前步骤必须随事务回滚。transient messages 即使事务成功也只存在于 `llm_attempts.request_payload`，MUST NOT污染后续 iteration 的 `llm_messages`。

`v15_phase_effect` 至少 MUST 表达：

```text
action
fatal
grouped_error
messages
exec_result
recursion_available
input_adds
input_drops
blackboard_generation
budget_result
```

其解释由 `v15_begin_llm`、`v15_settle_llm`、`v15_begin_exec` 与 `v15_finish_exec` 完成（§4）；dispatcher MUST NOT自行执行 provider I/O、模型 SQL 或 child delivery。

### 9.9　Blackboard generation barrier

blackboard 是按 invoke 隔离的持久状态（§3 `blackboard`）。一次 dispatch 必须：

1. 读取并锁定当前 invoke 的 blackboard generation；
2. 以该 generation 构造所有 handler 共用 snapshot；
3. 等待全部 handler 返回；
4. 组合全部 writes；
5. 若 writes 为空，不修改 generation；
6. 若 writes 非空，在同一事务中应用全部 key/value，并把 generation 精确加一。

应用更新必须包含旧 generation 条件。若更新时 generation 已变化，说明违反一个 leaseholder 或锁顺序不变量，MUST 以 `V15_INVALID_TRANSITION` fail-closed，MUST NOT静默重读并重跑 handlers。

一个 phase 内不允许 handler 看见另一 handler 的新值；下一 phase 才能观察递增后的 generation（§0「黑板代际屏障」）。

---

## §10　内置 Hook

### 10.1　分类与安装

v15 随发行物提供九个 `hook_defs` 行：

- 四个 mandatory baseline governance hooks；
- 五个 optional JAZ-parity hooks。

四个 baseline hooks MUST 由 manifest 指定，并在每个 invoke open 时安装（§4 `v15_open_invoke`；§8 child inheritance）。五个 parity hooks 只在 profile/scope/local 声明后安装，MUST NOT 被默认偷偷启用。

所有内置 handler 均须满足 §9.4 的注册合同，并各自由同名 NOLOGIN owner 角色持有。

### 10.2　Baseline governance hooks

| Hook name | 合法 channel | 阶段 | 行为与效应 | 持久事实 |
|---|---|---|---|---|
| `governance_iterations` | 仅 `baseline` | `llm_query/enter` | 在创建 attempt lease 之前检查 `iteration_no >= effective_max_iterations`；成立时返回 fatal abort `V15_ITERATION_LIMIT` | `iterations` 与 `invoke_events` |
| `governance_depth` | 仅 `baseline` | `invoke/enter` | `depth = effective_max_depth` 时返回 `disable_recursion`；`depth > effective_max_depth` 时 fatal abort `V15_RECURSION_EXCEEDED` | `invokes.depth` 与 `invoke_events` |
| `governance_io` | 仅 `baseline` | `llm_query/enter`、`llm_query/complete`、工具调用计数点 | 在新 I/O 前检查 attempts/tool calls；超限 fatal abort `V15_IO_LIMIT`。unknown attempt MUST 计为已消耗 | `llm_attempts`、`hook_counters` |
| `governance_statement` | 仅 `baseline` | `repl_exec/enter`、`repl_exec/send` | 返回非零 `statement_timeout_ms`，值为请求值与 manifest 最大值的较小者；请求缺席或为零时使用 manifest 最大值。该 hook 是不可禁用的 timeout backstop | `statements`、`hook_counters` |

baseline hooks **就是** manifest ceilings 的执行机制，MUST NOT 仅记录警告。handler 返回 abort 后，§4 状态机必须在对应 I/O 或 SQL 执行之前停止。

`governance_depth` 在等于最大深度时只关闭新的递归，不终止当前 invoke；大于最大深度表示持久状态已违反 open-time 前置条件，因此 MUST fatal。

`governance_statement` 产生的数据库 `statement_timeout` 是后备边界；worker Python deadline 仍为权威取消边界（§17.9）。

### 10.3　Optional JAZ-parity hooks

| Hook name | 合法 channel | 阶段 | 参数与效应 | 持久状态 |
|---|---|---|---|---|
| `iteration_limit` | `propagating`、`local` | `llm_query/enter` | 参数 `max_iterations` 必须为正整数；与上层及 manifest 取最小值；达到上限时 abort `V15_ITERATION_LIMIT` | 计数来自 `iterations`；触发次数写 `hook_counters` |
| `recursion_limit` | `propagating`、`local` | `invoke/enter` | 参数 `max_depth` 只能收紧；本地 `recursion_limit` 明确允许，用于只收紧当前 invoke。等于上限时 disable，超过时 fatal abort | 深度来自 `invokes`；触发记录写 `hook_counters` |
| `budget_pool` | `propagating`、`local` | `llm_query/enter|complete` | 绑定唯一 `pool_id`；enter 请求 reserve，complete 请求 settle/refund/unknown charge | 金额在 `budget_pools`；attempt 关联与触发记录在 `llm_attempts`、`hook_counters` |
| `budget_forcing` | `propagating`、`local` | `llm_query/send` | 当剩余额度低于 `force_at` 时添加一次 transient forcing message；参数只能收紧阈值 | 每 iteration 是否已发出写 `hook_counters` |
| `context_window_warning` | `propagating`、`local` | `llm_query/send` | 当估算上下文达到阈值时添加 transient warning；不得删除历史或改写模型响应 | 阈值触发记录写 `hook_counters` |

同一 invoke 最多只能有一个 effective `budget_pool`。多个 hook 指向相同 pool 且参数完全相等时 coalesce；指向不同 pool 或不同计价单位时 MUST 以 `V15_EFFECT_CONFLICT` 失败。

local `recursion_limit` MUST 被允许，但其值只能小于或等于已生效的祖先限制和 manifest ceiling；增大限制 MUST 以 `V15_HOOK_EFFECT` 失败。

### 10.4　Forcing 与 context warning 文本

`budget_forcing` 的冻结 transient 文本为：

> Budget is nearly exhausted. Finish with `SELECT jaz."return"(<jsonb-expr>);`, or delegate with the two-statement tail: `SELECT jaz.bind_invoke(...);` followed by `SELECT jaz."return"(jaz.var(<result-name>));`.

`context_window_warning` 的冻结 transient 文本为：

> Context window pressure is high. Full prior observations remain available through `jaz.history` and `jaz.prior_history(...)`. If you delegate, use the two-statement tail: `SELECT jaz.bind_invoke(...);` followed by `SELECT jaz."return"(jaz.var(<result-name>));`.

上述消息 MUST 只加入即将发送的 attempt request，MUST NOT 写入 `llm_messages`。同一 hook、invoke、iteration、threshold band 最多发送一次；去重事实写入 `hook_counters`。

其他 hook 若显式返回 `persistence='persistent'`，dispatcher 才把消息写入 `llm_messages`。persistent 与 transient 的差异 MUST 在 `llm_attempts.request_payload` 中可审计。

### 10.5　内置 Hook 不得旁路权限

内置 handler 与 custom handler 一样 MUST 没有 kernel table 写权限。其预算、counter、message 与 blackboard 请求只能经 `v15_on_phase` 应用。内置身份不能作为任意 SQL 权限旁路（§0「grants-not-convention」；§2 权限矩阵）。

---

## §11　治理与预算

### 11.1　Singleton manifest

`governance_manifest` 必须永远恰有一行 singleton 记录（§3 `governance_manifest`）。下列函数为唯一 manifest assertion 接口：

```text
v15_assert_manifest() → text
v15_assert_invoke_manifest(p_invoke_id uuid) → text
```

返回值为当前 `manifest_digest`。二者 MUST 是 `SECURITY DEFINER`，固定 `search_path=pg_catalog`，并只能向内核角色授予 EXECUTE。

`v15_assert_manifest()` MUST：

1. 验证 singleton 行存在且唯一；
2. 对所有治理字段、baseline hook identity/digest、受治理 tool policy 与 operator fuses 进行规范序列化；
3. 重算 SHA-256；
4. 与存储的 `manifest_digest` 比较；
5. 不相等时以 `V15_MANIFEST_DIGEST` 失败。

`v15_assert_invoke_manifest()` 还 MUST 锁定或读取目标 invoke，并验证 `invokes.manifest_digest` 与当前 singleton digest 相等。运行中的 invoke 不允许自动升级到新 manifest；operator 必须显式 drain/reopen。

### 11.2　Tighten-only 算术

所有治理叠加 MUST 只能收紧：

- 正整数最大值：取 `min`；
- 允许集合：取交集；
- 布尔能力：取逻辑 AND；
- 最大 statement runtime：取所有非零上限的 `min`；
- budget capacity：取较小 capacity；
- recursion availability：只允许 `true → false`；
- fatal：取逻辑 OR。

零值不得被解释为 unlimited，除非 manifest 对该字段明确把零定义为禁止；配置层、Hook 参数和模型 SQL均不能把 manifest ceiling 扩大。

每个 invoke 的 effective ceilings 由以下不可变输入确定：

```text
manifest ceilings
⊗ baseline hook parameters
⊗ propagating hook parameters
⊗ local tightening parameters
```

结果不作为普通配置键，也不得通过 §8 config fold 覆盖。其可重放事实由 `manifest_digest`、冻结的 `invoke_hooks` 行及各 hook 参数共同组成。

### 11.3　预算池锁顺序

任何同时访问 `budget_pools` 与 `invokes` 的转移 MUST：

1. 按 `pool_id` 升序锁定所有相关 `budget_pools` 行；
2. 再按 `depth`、`invoke_id` 顺序锁定 invokes；
3. 再锁定 attempts、iterations 与 counters。

该规则优先于 §4 的普通 invoke-first 顺序。调用 `v15_on_phase` 前必须已完成所需 pool lock；dispatcher MUST NOT 在持有 invoke lock 后首次发现并锁定新 pool。

有效 `budget_pool` 必须能从冻结的 `invoke_hooks` 预解析。运行时 handler 返回不同 pool ID 必须以 `V15_EFFECT_CONFLICT` 失败。

### 11.4　Reserve

在 `llm_query/send` 之前，dispatcher MUST 为本 attempt 保留最坏情况计费量 `p_amount`。规范更新为：

```sql
UPDATE budget_pools
SET reserved_amount = reserved_amount + p_amount,
    revision = revision + 1
WHERE pool_id = p_pool_id
  AND p_amount > 0
  AND spent_amount + reserved_amount + p_amount <= limit_amount
RETURNING revision;
```

没有返回行时，dispatcher MUST 区分不存在的 pool 与额度不足；前者为 `V15_HOOK_EFFECT`，后者为 committed fatal `V15_BUDGET_EXHAUSTED`。

reserve 与 `llm_attempts.reserved_amount`、`llm_attempts.pool_id` 的写入 MUST 在同一事务。一个 attempt MUST 至多 reserve 一次；重复 reserve 请求若金额完全相同必须返回既有 reservation，不得二次增加。不同金额为 `V15_EFFECT_CONFLICT`。

### 11.5　Settle、refund 与 unknown charge

已收到可信 provider usage 时，规范 settle 更新为：

```sql
UPDATE budget_pools
SET reserved_amount = reserved_amount - p_reserved,
    spent_amount = spent_amount + p_charged,
    revision = revision + 1
WHERE pool_id = p_pool_id
  AND reserved_amount >= p_reserved
RETURNING spent_amount, limit_amount, revision;
```

settle MUST 记录实际 `p_charged`，即使 provider 报告值超过 reservation 或使 `spent_amount > limit_amount`。真实支出不得因 ceiling 而丢失；超额后当前 invoke MUST 以 `V15_BUDGET_EXHAUSTED` fatal 终止。

明确确认请求未离开 worker、provider 未受理或已确认零计费时，规范 refund 为：

```sql
UPDATE budget_pools
SET reserved_amount = reserved_amount - p_reserved,
    revision = revision + 1
WHERE pool_id = p_pool_id
  AND reserved_amount >= p_reserved
RETURNING revision;
```

attempt 进入 `unknown` 时必须保守计费：

```sql
UPDATE budget_pools
SET reserved_amount = reserved_amount - p_reserved,
    spent_amount = spent_amount + p_reserved,
    revision = revision + 1
WHERE pool_id = p_pool_id
  AND reserved_amount >= p_reserved
RETURNING revision;
```

unknown 后若 operator 获得可验证 provider receipt，只能通过显式 reconciliation 事件校正；普通 retry MUST NOT 自动退款（§0「unknown 保守核算」；§12）。

所有金额 MUST 为非负整数。负值、溢出、reserved 下穿零或 revision 不连续为 `V15_GOVERNANCE_FAULT`。

### 11.6　Fatal 传播

任一治理 hook、预算结算或 child 结果产生 `fatal=true` 时：

- 当前 invoke 必须进入 fatal terminal；
- 所有仍非 terminal 的祖先必须在同一 delivery/closure 事务中进入 aborted；
- 每个被关闭 span 必须追加 complete/exit 事件；
- 祖先 remaining statements MUST 标记 skipped；
- lease、lease owner 与 lease expiry MUST 被清空；
- 已知可退款 reservation MUST refund；unknown reservation MUST 保守计费；
- 已完成 child 与已提交历史 MUST 保留，MUST NOT 物理删除。

fatal bit 一旦为真 MUST NOT 被后续 hook、child delivery 或 operator retry 清除（§0「fatal bit 单调」；§4 child terminal delivery）。

### 11.7　Stub-hook fuse

stub handler 只允许 stage gate 使用。启用必须同时满足：

1. 当前角色是 `v15_operator`；
2. manifest 的 `operator_fuses.allow_stub_hooks` 为 `true`；
3. 当前事务以 transaction-local 设置显式启用 `jaz.v15_test_stub_hooks=on`；
4. 数据库名匹配 `agent_v15_*` gate 数据库约束。

缺少任一条件时，注册或激活 stub MUST 以 `V15_HOOK_SIGNATURE` 失败。生产 manifest MUST 将 fuse 固定为 false。该 fuse 不是配置键，MUST NOT 经 `config_layers` 或模型 SQL设置。

---

## §12　I/O 与 unknown

### 12.1　Request/attempt 生命周期

LLM I/O 的规范状态如下；详细转移写入以 §4.5 与 §4.10 为准。

| 时点 | `llm_requests` | 当前 `llm_attempts` | 事务边界 | 不变量 |
|---|---|---|---|---|
| 逻辑请求建立 | `pending` | 无 | 内核事务 | 每个 iteration 至多一个当前 logical request |
| `v15_begin_llm` | `leased` | `leased` | 提交后才可 I/O | request payload、logical digest、attempt ordinal、lease/fence 已持久化 |
| worker 调 provider | `leased` | `leased` | 数据库事务外 | provider 调用 MUST NOT 持有数据库事务或行锁 |
| 已知成功 settle | `completed` | `succeeded` | 单个 settle 事务 | 响应、usage、预算 settle 与 messages 同时提交 |
| 已知失败 settle | `retryable` 或 `failed` | `failed` | 单个 settle 事务 | 明确未计费才允许 refund |
| lease 过期且结果未知 | `retryable` | `unknown` | `v15_reclaim_expired` 事务 | reservation 按全额保守计费 |
| retry | `leased` | 新 ordinal 的 `leased` | 新 begin 事务 | 旧 attempt 不修改回 leased |
| terminal exhaustion | `failed` | 无新 attempt | 单个终止事务 | 追加 span closure，清 lease |

`unknown` 是永久历史事实，MUST NOT 改写为 failed、succeeded 或 cancelled。后续 receipt reconciliation 必须追加事件和独立校正记录，不能覆盖原 attempt。

`v15_reclaim_expired` 只能标记 unknown、保守核算并使 logical request 可重试；MUST NOT 在数据库函数中调用 FakeLLM、真实 provider 或任意 host callback（§0「scan-not-listen」）。

### 12.2　扫描，不依赖通知

worker 必须以 `v15_next_runnable()` 扫描 runnable invokes，再调用 `v15_claim`。`LISTEN/NOTIFY` 可以作为非权威 wake hint，但丢失通知不得影响正确性；没有通知时扫描仍必须取得全部可运行工作（§3 `invokes`；§4 claim）。

### 12.3　FakeLLM

Gate 使用的 FakeLLM 必须运行在 worker 侧。其输出键固定为：

```text
(logical_digest, attempt_ordinal)
```

相同键必须产生相同响应、usage 与故障注入结果；不同 attempt ordinal 可以产生预先声明的不同结果。FakeLLM MUST NOT 读取 wall clock、随机数、数据库行物理顺序或进程 PID。

空消息、prose-only 消息、SQL statement-list 消息与 timeout 必须作为不同 fixture 明确登记。FakeLLM 不得绕过 splitter、classifier、prompt rendering 或 settle 路径。

### 12.4　FakeTool

FakeTool 必须作为 `tool_catalog` 中的普通纯 SQL regprocedure 注册，通过同步 `jaz.tool(name,args)` 调用。其结果只能由规范化 args 与 fixture 数据决定。

FakeTool MUST 遵守真实工具的双重授权：

- 当前 invoke 的 `tool_grants` 包含 tool；
- 当前 exec_context 中存在允许该 tool 的 binding/capability。

FakeTool 不得作为 worker 外部 I/O adapter，也不得实现 v15 已拒绝的 external tool continuation（§5 `jaz.tool`；§0「grants-not-convention」）。

---

## §13　错误码表

### 13.1　总则

下表是 v15 唯一权威错误码表。SQLSTATE 从 `P1501` 连续编号，无空洞；`P1546` 之后未分配。任何 SQL、PL/pgSQL、Python worker、gate 或文档 MUST NOT 定义别名、同义码或表外 `V15_*` 代码。

“回滚类”表示当前内核转移事务整体失败；“提交类”表示错误作为状态、事件或 terminal 结果提交；“语句失败”表示当前模型语句的子事务回滚，但内核可提交该语句的失败记录。

| 代码 | SQLSTATE | 触发条件 | 分类 |
|---|---|---|---|
| `V15_CONTEXT` | `P1501` | 模型 API 找不到唯一 active `exec_context` | 回滚类 |
| `V15_ROLE` | `P1502` | `current_user`、session role 或 exec_context role 不符合模型 API 合同 | 语句失败 |
| `V15_BINDING_NAME` | `P1503` | binding 名称不符合冻结 grammar | 语句失败 |
| `V15_RESERVED_NAME` | `P1504` | 使用保留 binding 名称或保留前缀 | 语句失败 |
| `V15_BINDING_KIND` | `P1505` | binding kind 不合法或与操作所需 kind 不符 | 语句失败 |
| `V15_ASSIGN_KIND` | `P1506` | `jaz.assign` 尝试修改 input、scope 或其他不可赋值 binding | 语句失败 |
| `V15_HISTORY_SCOPE` | `P1507` | 历史访问跨 root/invoke 可见边界或请求未来 iteration | 语句失败 |
| `V15_SCOPE_CONFLICT` | `P1508` | child open 时复制的 scope 名与显式 input/既有名称冲突 | 回滚类 |
| `V15_DEPTH_SELF` | `P1509` | depth-specific config 非法应用于定义它的同一深度 | 回滚类 |
| `V15_CONFIG_SHAPE` | `P1510` | profile、scope、layer 或 resolved config 形状/类型非法 | 回滚类 |
| `V15_CONFIG_LOCAL` | `P1511` | local layer 被传播、继承或用于 child open | 回滚类 |
| `V15_BASELINE_IMMUTABLE` | `P1512` | 删除、替换、重排或遮蔽 baseline hook/治理项 | 回滚类 |
| `V15_INVOKE_FORM` | `P1513` | `bind_invoke` 或控制形式不符合 canonical sole-form/tail-form grammar | 语句失败 |
| `V15_INVOKE_EXPR_WRITE` | `P1514` | `bind_invoke` 参数只读求值尝试写入或调用非只读操作 | 语句失败 |
| `V15_DIALECT` | `P1515` | statement 使用被禁 SQL 类别、transaction control 或 scratch 外 DDL | 语句失败 |
| `V15_TOOL_NOT_FOUND` | `P1516` | `jaz.tool` 名称不在 active tool catalog | 语句失败 |
| `V15_TOOL_DENIED` | `P1517` | tool grant 与 binding/capability 双重要求未同时满足 | 语句失败 |
| `V15_EXTERNAL_TOOL` | `P1518` | v15 调用 `tool_catalog.external=true` 的工具 | 语句失败 |
| `V15_TOOL_SIGNATURE` | `P1519` | catalog regprocedure 签名、owner、volatility 或返回类型不合法 | 语句失败 |
| `V15_RETURN_AFTER_PRINT` | `P1520` | 同一 statement/iteration 违反 print-and-return 排他合同 | 语句失败 |
| `V15_RAISE` | `P1521` | 模型执行 canonical `jaz."raise"` | 语句失败 |
| `V15_HOOK_SIGNATURE` | `P1522` | Hook 注册、owner、language、volatility、security 或 fuse 合同不合法 | 回滚类 |
| `V15_HOOK_EFFECT` | `P1523` | handler response shape、字段类型、参数或单调性非法 | 回滚类 |
| `V15_EFFECT_FORBIDDEN` | `P1524` | phase 不允许该效应，或使用 v15 保留效应 | 回滚类 |
| `V15_EFFECT_CONFLICT` | `P1525` | 多个非相等、不可组合的一般效应相互冲突 | 回滚类 |
| `V15_BLACKBOARD_CONFLICT` | `P1526` | 同 phase 对同一 blackboard key 写入不相等 JSONB | 回滚类 |
| `V15_INPUT_CONFLICT` | `P1527` | 同 phase 对同一 input 名发生不相等 add 或 add/drop 冲突 | 回滚类 |
| `V15_ITERATION_LIMIT` | `P1528` | effective iteration ceiling 已达到 | 提交类 |
| `V15_RECURSION_EXCEEDED` | `P1529` | invoke depth 大于 effective maximum depth | 提交类 |
| `V15_IO_LIMIT` | `P1530` | effective LLM/tool attempt ceiling 已达到 | 提交类 |
| `V15_BUDGET_EXHAUSTED` | `P1531` | reserve 无额度或 settle 后确认超出 pool limit | 提交类 |
| `V15_CHILD_ERROR` | `P1532` | non-fatal child 失败被交付给 parent continuation | 提交类 |
| `V15_GOVERNANCE_FAULT` | `P1533` | baseline handler、治理算术、预算账本或治理不变量失败 | 回滚类 |
| `V15_INVALID_TRANSITION` | `P1534` | 状态、phase、generation 或前置条件不允许请求的转移 | 回滚类 |
| `V15_STATEMENT_TIMEOUT` | `P1535` | worker deadline 或数据库 statement timeout 取消模型语句 | 语句失败 |
| `V15_HANDLER_FAILED` | `P1536` | non-baseline handler exception 被子事务隔离并审计 | 提交类 |
| `V15_MANIFEST_DIGEST` | `P1537` | singleton、invoke、baseline/active handler 或 tool 治理摘要漂移 | 回滚类 |
| `V15_DELIVERY_CONFLICT` | `P1538` | child terminal result 已以不同内容交付，或 resume target 不一致 | 回滚类 |
| `V15_VALUE_INVALID` | `P1539` | 值不是允许的 JSONB 域、超限或 host serialization 非规范 | 语句失败 |
| `V15_STALE_FENCE` | `P1540` | worker、fence 或 lease 与受保护行不匹配 | 回滚类 |
| `V15_STATEMENT_FAILED` | `P1541` | 未由更具体 P15xx 覆盖的模型 SQL 错误 | 语句失败 |
| `V15_ATTEMPT_UNKNOWN` | `P1542` | reclaim 将过期且外部结果未知的 attempt 永久标记 unknown | 提交类 |
| `V15_LLM_FAILED` | `P1543` | 已知 provider failure 达到 retry/attempt 上限 | 提交类 |
| `V15_MESSAGE_INVALID` | `P1544` | 模型、Hook 或 prompt message role/content/size 不合法 | 回滚类 |
| `V15_SCRATCH_VIOLATION` | `P1545` | 模型访问、创建或修改 scratch 边界外对象 | 语句失败 |
| `V15_INTERNAL` | `P1546` | 已验证为不可归入更具体条件的内核不变量故障 | 回滚类 |

`V15_INTERNAL` MUST NOT 用于隐藏已知条件。新增错误条件前必须按 §18.5 执行 stop-and-renumber；MUST NOT 直接占用 `P1547` 或 `P1548`。

空模型消息和 prose-only 模型消息是 §4/§6 的协议路径，不自动产生新的错误码；其结果必须通过既有 observation/continue 或 `V15_DIALECT` 规则表达。

---

## §14　偏差台账

### 14.1　冻结偏差

| 编号 | JAZ 行为 | v15 行为与理由 | 可观察后果 |
|---|---|---|---|
| V15-D01 | Python code REPL | 使用 statement-list SQL REPL，使事务、角色与 PostgreSQL 目录成为执行边界 | 模型输出由 SQL splitter 分句，不执行 Python |
| V15-D02 | Python 对象和值可携带 identity | 所有跨边界值规范化为 JSONB | 对象 identity、aliasing、custom class 不保留 |
| V15-D03 | Python exception 控制 `return`/`raise` | 使用 `jaz."return"` 与 `jaz."raise"`；引号为 canonical grammar 的一部分 | unquoted 控制名即使某版本可解析也按 `V15_INVOKE_FORM` 拒绝 |
| V15-D04 | REPL 通常按代码块执行 | 每条 SQL statement 独立原子提交/失败，iteration 再统一收尾 | 前一成功 statement 可在后一 statement 失败后保留 |
| V15-D05 | Python globals 提供临时命名空间 | 使用 bindings 与 invoke 专属 scratch schema | child、并发 invoke 与其他角色看不到彼此 scratch |
| V15-D06 | 工具可由 host 异步执行 | v15 `jaz.tool` 仅同步调用纯 SQL regprocedure；external tools 推迟 | `external=true` 固定失败 `V15_EXTERNAL_TOOL` |
| V15-D07 | invoke 可通过 host coroutine 等待 | `jaz.bind_invoke` 建立数据库 continuation，child terminal 后恢复 statement cursor | parent 不阻塞数据库连接或事务 |
| V15-D08 | Hook 是 Python 对象/回调 | Hook 是受注册约束的 STABLE SQL/PLpgSQL handler，返回闭合效应代数 | 任意 Python side effect 不存在 |
| V15-D09 | Hook 可直接修改运行对象 | 所有效应先收集后组合，handler 共享不可变 snapshot | handler 顺序影响追加顺序，但不产生 read-after-write |
| V15-D10 | 非基线 Hook exception 可沿 Python stack 传播 | non-baseline exception 回滚到 handler savepoint、审计并继续 | 单个 optional hook 故障不会丢失整个 phase |
| V15-D11 | 运行时配置来自 Python merge/object graph | 配置按 base、depth、propagating ordinal、local 做 whole-component fold 后冻结 | child 不观察 parent 后续 config 修改 |
| V15-D12 | History 是 REPL 内对象 | 提供 security-barrier view `jaz.history` 与 `jaz.prior_history` | 跨 invoke/root 查询按 `current_user` 与 exec_context 拒绝 |
| V15-D13 | print 可由 host stdout 捕获 | `jaz.print` 追加到 `iterations.capture` | capture 事务性持久化且受输出长度上限 |
| V15-D14 | Hook/phase 可由进程内 call stack 隐含 | 所有 span/phase 事实进入 append-only `invoke_events` | 不另建 spans、phases、turns 表 |
| V15-D15 | Provider retry 可由 client library 隐含 | 每次 attempt 有独立行、lease、fence 和 unknown 状态 | crash 后可能保守重复计费，但不会假装确定失败 |
| V15-D16 | 调度可依赖进程队列/condition | 权威调度使用 `v15_next_runnable()` 扫描与 `SKIP LOCKED` claim | 丢失 NOTIFY 不影响活性或正确性 |
| V15-D17 | Python 名称查找可动态沿 scope 链 | child open 时复制 scope bindings 与 tool grants | 已创建 child 不观察祖先后续赋值或授权 |
| V15-D18 | 模板可使用 Jinja 或 Python formatting | prompt 使用固定 renderer 与结构化转义，无 Jinja | 模板表达能力更小，但输入不能执行模板代码 |
| V15-D19 | 上下文压缩可能改写完整 transcript | 只截断送模 observation 文本，数据库保留完整值 | `jaz.history` 可检索未截断历史 |
| V15-D20 | Python 权限常由调用约定保证 | 由角色、grant、owner、SECURITY DEFINER 与 event trigger 强制 | 缺少物理 grant 即失败，不接受“调用方不会做” |
| V15-D21 | `DO`/动态代码不是参考核心问题 | `DO` 只算一个 plain statement，但仍受角色、event trigger、scratch 边界与 timeout 限制 | splitter 不拆 `DO` body；违规 DDL 仍失败 |
| V15-D22 | `EXPLAIN` 可作为普通语言功能 | v15 不把 `security_barrier` 或 EXPLAIN 文本当作隔离边界 | 机密保护依赖 ACL/RLS/视图边界，不依赖计划隐藏 |
| V15-D23 | Hook 或工具替换可随进程代码热更新 | active regprocedure 由 OID 与 digest 冻结；漂移 fail-closed | 未同步 manifest 的 `CREATE OR REPLACE` 会中止 dispatch |
| V15-D24 | reference runtime 可直接调用外部对象 | v15 所有模型可见能力必须同时具备 catalog entry 与 invoke grant/binding | capability 是数据库事实，可审计、可回放 |

### 14.2　有意保留的 JAZ 性质

下列行为不是偏差，v15 MUST 保留：

1. harness 本身构成模型可操作语言，而非只是一段系统提示。
2. 模型每次 continuation 观察上一轮执行结果并决定下一步。
3. child 结果直接恢复 parent continuation；parent 消费 child result **不增加额外 parent LLM call**。
4. Hook activation 保持 baseline、外层传播、内层传播、local 的确定顺序。
5. 输入、scope 与 var 的语义类别保持可区分。
6. print 是 observation/capture，不等价于 return。
7. return 与 raise 是互斥控制结果，不能与普通 continuation 混淆。
8. 历史对模型仍可检索，即使 prompt 为控制上下文而截断 observation。
9. recursion、iteration、I/O 与预算限制是运行时强制，不是提示建议。
10. child non-fatal failure可作为 parent 的 `V15_CHILD_ERROR` observation 继续；fatal failure 必须传播。

---

## §15　Stage/Gate 计划

### 15.1　九阶段

| Stage | 目录 | 累积 SQL 文件 | Gate script | Gate 必须证明 |
|---:|---|---|---|---|
| 1 | `v15/schema/` | `v15/schema/v15_core.sql` | `v15/schema/gate.py` | §3 全部表、类型、PK/FK/CHECK、status enum、singleton、append-only seq、lease/fence 与 `v15_next_runnable()` 基础形状 |
| 2 | `v15/namespace/` | `v15/namespace/v15_namespace.sql` | `v15/namespace/gate.py` | §2 角色矩阵、`jaz` schema、PUBLIC revoke、scratch ownership、current_user 边界与 exec_context 唯一性 |
| 3 | `v15/config/` | `v15/config/v15_config.sql` | `v15/config/gate.py` | §7—§8 binding/scope/value 域、四层 fold、whole-component replace、freeze/digest 与 child inheritance |
| 4 | `v15/protocol/` | `v15/protocol/v15_protocol.sql` | `v15/protocol/gate.py` | §6 splitter 全词法状态、canonical sole forms、quoted `"return"`/`"raise"` parser probe、dialect classifier 与 prompt fixture |
| 5 | `v15/repl/` | `v15/repl/v15_repl.sql` | `v15/repl/gate.py` | §5 全部 `jaz.*` API、语句原子性、capture、scratch grant/revoke、timeout、print-and-return 拒绝 |
| 6 | `v15/io/` | `v15/io/v15_io.sql` | `v15/io/gate.py` | §12 request/attempt、lease-before-I/O、settle、unknown reclaim、FakeLLM 确定性与保守核算 |
| 7 | `v15/loop/` | `v15/loop/v15_loop.sql` | `v15/loop/gate.py` | §4 单 invoke 的 open→claim→LLM→split→exec→continue/return/raise 全链、空消息与 prose 路径 |
| 8 | `v15/tree/` | `v15/tree/v15_tree.sql` | `v15/tree/gate.py` | bind continuation、child delivery、resume_stmt、无额外 parent LLM call、non-fatal/fatal 传播与 delivery idempotence |
| 9 | `v15/govern/` | `v15/govern/v15_govern.sql` | `v15/govern/gate.py` | §9—§13 dispatcher 最终 body、九个内置 hooks、预算、manifest、错误码、digest drift、SAVEPOINT 隔离与全部治理 ceilings |

每个 gate 必须同时验证本 stage 新能力与所有前缀 stage 的核心不变量。Stage 9 是唯一完整 v15；前缀数据库只是可测试 scaffold（§18.4）。

### 15.2　Loader 合同

`v15/load.py` MUST 复用 v13 的累积加载模式，但使用独立常量：

```text
V15_ROOT
SQL_LOAD_ORDER
STAGE_THROUGH
files_through(stage)
load_stage(server, database, stage)
```

`SQL_LOAD_ORDER` 必须严格按 §15.1 的九个 SQL 文件排列。新 stage 只能在列表尾部追加；MUST NOT 在已有 stage 中间插入、重排或条件加载。

`STAGE_THROUGH` 固定映射：

```text
schema=1
namespace=2
config=3
protocol=4
repl=5
io=6
loop=7
tree=8
govern=9
```

每个 stage 的 `setup_db.py` 必须：

1. `DROP DATABASE IF EXISTS agent_v15_<stage> WITH (FORCE)`；
2. 创建同名数据库；
3. 从空库加载 `files_through(<stage>)`；
4. 安装该 gate 所需的受控角色与 fixture；
5. 运行或打印唯一 gate 入口。

SQL 文件使用普通 `CREATE`；MUST NOT 以 `IF NOT EXISTS` 隐藏重复定义或 load-order 错误。

### 15.3　Worker test harness

唯一 worker harness 路径冻结为：

```text
v15/worker.py
```

所有 stage gate MUST 导入该文件中的相同 worker loop、deadline 实现、FakeLLM 与 FakeTool adapter。MUST NOT 在各 stage 目录复制一份行为不同的本地 worker。

stage gate 可提供 fixture 数据，但不得重新实现 claim、begin/settle、split、deadline 或 delivery 算法。FakeLLM 的确定性合同以 §12.3 为准。

### 15.4　Milestone discipline

每个 stage 是一个独立 milestone，并 MUST 遵守根目录 `AGENTS.md` 的提交纪律：

- 一个 stage 的 SQL、setup、gate 与必要文档更新必须同一 milestone 完成；
- 每个 stage 至少一个独立 commit；
- milestone 完成时同步更新 conformance matrix；
- 影响 JAZ 可观察行为时同步更新 §14 偏差台账；
- 影响运行、加载或 gate 命令时同步更新 v15 README；
- gate 未通过时不得宣称 stage 完成；
- 后续 stage 不得通过削弱前序 gate 来“修复”实现。

---

## §16　非权威清单

以下材料可用于解释、测试或历史追溯，但不具有覆盖本文规范的权力：

1. JAZ paper 中与本文冻结行为冲突的实现建议；其语义目标仍是设计来源。
2. jaz Python reference core 的具体类布局、异常类型、async 调度细节与模板实现。
3. v1—v13 的 schema、函数名、调度策略、权限习惯与错误文本。
4. `v15-oracle-round1.md`、`v15-oracle-round2.md` 中已被本文吸收或由 K-rulings 调和的候选表述；它们保留为 adjudication provenance，不再形成第二套运行规范。
5. stage scaffold body、临时 stub hook、gate fixture 与 FakeLLM 示例响应。
6. SQL `EXPLAIN` 输出、planner 选择、heap physical order、OID 数值与 wall-clock timing。
7. README 摘要、注释、tutorial、issue、review 和记忆中的口头约定。
8. `LISTEN/NOTIFY`、日志、metrics 与 tracing；它们可以帮助唤醒或诊断，但不是状态事实来源。
9. provider SDK 的默认 retry、timeout、token accounting 或错误分类。
10. prompt 中除本文明确冻结段落和 renderer 规则之外的示例措辞。
11. 未列入 §13 的任意 `V15_*` 符号或 P15xx SQLSTATE。
12. 未被九阶段 loader 加载的实验 SQL、临时 migration 与本地 role grant。

发生冲突时，本文、singleton manifest、已冻结 schema 约束和通过的 gates 按此顺序形成实现依据；任何一项都不能以非权威材料为理由放宽 fail-closed 条件。

---

## §17　PostgreSQL 18.4 实现险点

### 17.1　Splitter 的 dollar quote 与 nested comment

`v15/protocol/split_sql.py` 的 gate MUST 包含至少以下独立 fixture：

- standard string 中的 `;`、`--`、`/*`；
- `E''` 中反斜杠转义后的 quote 与 semicolon；
- `U&''` 及其 `UESCAPE` 邻接形式；
- quoted identifier 中的 `""` 与 semicolon；
- line comment 终止于 LF、CRLF 与 EOF；
- 两层以上 nested block comments；
- `$$...;...$$`；
- `$tag$...;...$tag$`；
- dollar body 内出现不同 tag；
- 外层 SQL 中连续出现不同 tag；
- 未闭合 string、identifier、comment 与 dollar quote；
- `DO $outer$ ... $inner$ ... $outer$` 形式。

PostgreSQL dollar-quoted body 只由相同 tag 终止；不同 tag 在 body 内是文本，不得错误弹栈。所谓“distinct tags nesting” gate 必须验证 splitter 与 PG 18.4 parser 的实际词法一致，而不是发明不同于服务器的嵌套语法（§6 splitter）。

### 17.2　`jaz."return"` 与 `jaz."raise"` parser probe

Stage 4 必须在 PG 18.4 实际执行：

- quoted function definition/call；
- unquoted `return`；
- unquoted `raise`；
- schema-qualified与非 schema-qualified变体；
- prepared statement 与 plain query 变体。

probe 必须记录服务器对 unquoted 拼写的实际行为，但 canonical grammar 只允许：

```sql
SELECT jaz."return"(<jsonb-expr>);
SELECT jaz."raise"(<text-expr>);
```

即使某个 parser context 接受 unquoted 拼写，classifier 仍 MUST 在执行前以 `V15_INVOKE_FORM` 拒绝（§0「方言权威」；§6 canonical forms）。

### 17.3　`DO`、`SET` 与 `set_config`

`DO` 被 splitter 视为一个 plain statement，不表示其 body 获得额外权限。Gate 必须证明模型角色不能通过以下方式改变安全边界：

- `SET ROLE`、`SET SESSION AUTHORIZATION`；
- `SET search_path` 指向攻击者 schema；
- `PERFORM set_config(...)`；
- dynamic SQL 执行 transaction control 或 scratch 外 DDL；
- 改写 `statement_timeout`、`lock_timeout`、`row_security`；
- 启用 stub-hook fuse。

bootstrap 必须显式审计并按可撤销性处理 `pg_catalog.set_config(text,text,boolean)` 的 PUBLIC EXECUTE；仅靠 classifier 搜索字符串 MUST NOT 作为防线。内核设置必须由 SECURITY DEFINER transition 在受控位置执行，并在 statement 后恢复。

### 17.4　Scratch 的逐语句 USAGE

模型角色对 invoke scratch schema 的 `USAGE` MUST 只在当前 statement 的执行窗口授予：

1. 更新 `exec_context`；
2. `GRANT USAGE`；
3. `SET LOCAL ROLE`；
4. 在子事务中执行 statement；
5. 捕获成功或失败；
6. `RESET ROLE`；
7. `REVOKE USAGE`；
8. 写入 statement outcome 并提交。

Gate 必须覆盖成功、普通 SQL error、timeout、worker cancel 与连接丢失。reclaim 后不得残留可复用 grant；角色 membership 本身 MUST NOT永久获得所有 scratch schema 的 USAGE（§0「scratch isolation」）。

### 17.5　`exec_context` 不得放入 GUC 或 temp table

active execution identity 必须来自持久 `exec_context` 行，并由 backend/session identity、invoke、iteration、statement、worker 与 fence 联合校验。MUST NOT 使用：

- custom GUC 作为权威 context；
- temp table 作为唯一 context；
- application_name；
- current_schema；
- backend PID 单独识别。

GUC 可携带非权威 test fuse，但不能决定 binding、history、tool grant 或 scratch ownership（§3 `exec_context`；§5 current_user checks）。

### 17.6　Event trigger 覆盖与 TEMP revoke

安全 gate 必须逐项验证 event trigger 或 ACL 对以下命令族的覆盖：

- `CREATE`、`ALTER`、`DROP` schema/object；
- `CREATE TABLE AS`、`SELECT INTO`；
- function/procedure、operator、cast、type、domain、extension；
- trigger、rule、policy、publication、subscription；
- role/database/tablespace 等 shared object；
- `ALTER SYSTEM`；
- `GRANT`、`REVOKE`；
- `COMMENT`、`SECURITY LABEL`；
- table rewrite；
- dynamic SQL 与 `DO` 内执行的 DDL。

event trigger 不覆盖或不能可靠识别的命令 MUST 由 ACL/revoke 阻断。尤其必须验证：

```text
REVOKE TEMP ON DATABASE ... FROM model roles
```

确实阻止 temp object 旁路。MUST NOT 假设 event trigger 捕获所有 TEMP、shared-object 或 extension 行为。

### 17.7　`security_barrier` 的边界

`jaz.history` 可使用 `security_barrier` view 降低 predicate pushdown 风险，但它不是保密或权限隔离的充分条件。

Gate 必须以 hostile functions、EXPLAIN、错误消息、row estimates 与 planner variations 验证 ACL/RLS/exec_context 条件。EXPLAIN 输出不是隔离边界，且该限制已记入 V15-D22。

### 17.8　Regprocedure late binding

`CREATE OR REPLACE FUNCTION` 通常保留 OID，但改变定义、owner 可见性或 plan invalidation 行为。Stage 9 gate 必须在同一 database session 中：

1. 注册 handler 并成功 dispatch；
2. `CREATE OR REPLACE` 改变 body；
3. 不更新 digest，再次 dispatch，期望 `V15_MANIFEST_DIGEST`；
4. 在受控治理事务中同步更新合法 definition 与 digest；
5. 再次 dispatch，观察新 body；
6. DROP/recreate 产生新 OID，旧 active row必须 fail-closed。

dispatcher MUST 重算定义 digest，不能把 regprocedure OID 稳定误认为实现稳定（§9.4）。

### 17.9　只读 bind 参数求值

`jaz.bind_invoke` 的 JSONB 参数表达式必须在 READ ONLY 求值边界中执行。任何 INSERT、UPDATE、DELETE、MERGE、DDL、sequence mutation、volatile write helper 或 writable CTE 均映射为：

```text
V15_INVOKE_EXPR_WRITE / P1514
```

`V15_INVOKE_FORM` 只用于文本形状与 canonical placement 错误，MUST NOT 再用于“形状正确但求值发生写入”的条件。该区分统一 §6 classifier 与 §4 suspend 路径。

### 17.10　Worker deadline 与 `statement_timeout`

worker Python deadline 是权威超时：

- worker 必须先启动 deadline；
- deadline 到达时调用 libpq cancel；
- 数据库 `statement_timeout` 使用稍后的受治理 backstop；
- 二者触发均规范化为 `V15_STATEMENT_TIMEOUT`；
- cancel 后必须完整 drain connection result，再决定连接是否可复用；
- 不能确认连接干净时必须丢弃连接；
- timeout statement 的子事务全部回滚，外层内核事务提交失败 outcome。

数据库 timeout 不得大于 manifest ceiling；模型不能设为零或延长。worker deadline 与数据库 timeout 的相对裕量必须是 manifest 治理值，不是用户 config。

### 17.11　P15xx 与 `errcodes.txt`

Stage 1 和 Stage 9 gate 必须读取当前 PG 18.4 安装对应的 `errcodes.txt` 或等价服务器目录信息，验证 `P1501`—`P1546` 未与服务器定义冲突，并验证自定义 SQLSTATE 可由 PL/pgSQL `RAISE ... USING ERRCODE` 发出。

若任一码冲突，MUST 停止实现并执行 §18.5 的整表重编号；MUST NOT 只移动冲突行形成空洞。

### 17.12　同事务 `exec_context` 与 statement rollback

模型 statement 必须在外层内核事务中的 PL/pgSQL exception 子事务执行。Gate 必须证明：

- statement 对 bindings、capture、scratch 与工具副作用在失败时一并回滚；
- statement 之前写入的 active `exec_context` 仍可供异常处理读取；
- statement failure outcome、错误 digest 与后续 cleanup 可在外层事务提交；
- cleanup 后 `exec_context` 不再 active；
- 成功 statement 与失败 statement 均不泄漏 role/grant。

不得把整个外层事务交给模型 SQL直接 abort，否则无法持久化 `statements.status='failed'`。

### 17.13　Baseline 与 non-baseline SAVEPOINT

PL/pgSQL function 不能执行任意 SQL `SAVEPOINT`/`ROLLBACK TO SAVEPOINT` transaction control。实现必须使用嵌套 `BEGIN ... EXCEPTION ... END` 建立子事务。

Gate 必须同时证明：

- non-baseline handler 的表写入与效应在 exception 后回滚，审计事件在外层写入并提交；
- baseline handler exception 转换为 `V15_GOVERNANCE_FAULT` 后，整个 phase 事务回滚；
- 一个 handler 的失败不会把前一 handler 的内存效应误提交；
- handler exception 后 blackboard generation 不递增；
- handler exception 后 budget 不发生部分 reserve/settle。

---

## §18　冻结协议

### 18.1　权威修改单位

本文冻结后，任何规范变化必须：

1. 提升文档头中的 design revision；
2. 在同一 commit 修改规范正文；
3. 在同一 commit 更新受影响 stage gate；
4. 在同一 commit 更新 conformance matrix；
5. 若改变 JAZ 可观察行为，在同一 commit 更新 §14 偏差台账；
6. 若改变运行或加载方式，在同一 commit 更新 v15 README；
7. 重新计算并记录引用指纹。

只修改代码、只修改测试或只修改 README 均不能改变规范。

### 18.2　Gate 不得迁就实现

当实现与 gate 冲突时，工程师必须先判断本文是否要求该 gate。若是，MUST 修复实现；MUST NOT：

- 删除断言；
- 放宽 expected status；
- 把 fail-closed 改成 warning；
- 用 sleep 或重试掩盖竞态；
- 把确定性 fixture 改为接受多个结果；
- 通过新增特权 grant 使测试通过；
- 将真实失败改标为 xfail/skip。

若规范本身必须改变，先按 §18.1 修改设计和台账，再修改 gate 与代码。

### 18.3　`v15_on_phase` 的唯一最终定义

`v15_on_phase` 的最终 `CREATE OR REPLACE` body 只能位于：

```text
v15/govern/v15_govern.sql
```

Stage 1—8 可以定义签名兼容的 scaffold，但 scaffold 必须显式标记为非最终实现，且不得声称满足 §9—§11。任何其他文件替换最终 body 都是 load-order 违规。

handler 的合法 `CREATE OR REPLACE` 必须与对应 digest、manifest revision 和 gate 更新在同一治理事务或同一部署原子单元完成。

### 18.4　前缀加载只是 scaffold

`files_through(stage)` 创建的前缀数据库只证明截至该 stage 的合同。它们不是可部署的 v15 runtime，也不得被应用连接字符串、生产 migration 或兼容性声明引用。

只有完整加载九个 stage、通过 Stage 9 gate、安装 production manifest 且 stub fuse 为 false 的数据库，才能标识为 pg-agent v15。

### 18.5　P15 stop-and-renumber

若实现期间发现：

- PG 18.4 `errcodes.txt` 与现有 P15xx 冲突；
- §13 漏掉了已经冻结且不可合并的独立条件；
- 两个现有行实际为同义条件；
- 总数将超过 `P1548`；

实现必须立即停止新增错误码。设计作者必须在一个原子设计 revision 中：

1. 重新合并条件，确保一条件一行、无同义词；
2. 从 `P1501` 开始重新连续编号；
3. 保证最后一个码不大于 `P1548`；
4. 同步修改 SQL、worker、gates、fixtures、conformance matrix、偏差台账与文档；
5. 全仓搜索旧 symbolic code 和旧 SQLSTATE，结果必须为零；
6. 重新运行 Stage 1—9 gates。

MUST NOT 临时使用其他 SQLSTATE、保留空洞、追加别名或把冲突码留待后续版本处理。

### 18.6　冻结完成条件

v15 仅在以下条件全部满足时视为冻结：

- 九阶段从空库按 `SQL_LOAD_ORDER` 可重复加载；
- 每个 stage gate 独立通过；
- Stage 9 完整链通过并证明 manifest、hook、budget、unknown、tree delivery 与 error-code 合同；
- §13 与实现中的全部 `V15_*`、P15xx 一一对应；
- §14 覆盖全部已知 JAZ 偏差；
- production manifest digest 可重算且 baseline handler digest 无漂移；
- PUBLIC、model roles、hook owners 与 worker roles 的 ACL audit 无多余 grant；
- stub fuse 关闭；
- 没有未登记的外部工具路径、async tool 路径、旁路 dispatcher 或第二套状态表。

冻结后，任何破坏上述条件的变化都必须进入新的 design revision；不得以普通重构名义改变可观察语义。