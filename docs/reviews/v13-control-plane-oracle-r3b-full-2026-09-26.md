## Ask Oracle ✅
- Oracle group status: completed
- Oracle group: `6642BC27-FCAF-4120-92C6-8D2A1F8584EC`

### Oracle
- Status: Completed
- Provider: `grokBuild`
- Model: `grok-4.7-build-fast-xhigh`
- Effective effort: Provider default / not specified
- Chat: `new-chat-992E4B`



# R3b 补裁（D4–D6 不重开；补 H / A16 机器形状 / P1 完备性）

## 1. Summary

P1 的两个停工洞都用已有运输层封死，不加表、不加列、不加 effect kind、不加第二个推进函数。Harness 的生产侧采用**具名目录行 `harness_turn`（`kind=tool`）+ 函数体内的名字闭集**：`v13_advance` 在已持有的 session 锁内、调用 `v13_enqueue_effect` 之前把 `logical_turn_id`/`continuation_index` 盖进 request；`enqueue`/`complete` 只做拒收带，不发明 id。续传（未封口的 wait、或带 repair/replan 的 progress）由 advance 直接入队下一枚 harness，不经过 `v13_route`；新 logical turn 仍只在 route 落到该工具时盖章。A16 收据就是 `session/completed|failed|cancelled` 的 payload 本身；`spent` 是四键快照对象，因为活体 ⑤ 只读 `v13_cycle_no`、不写 `turn_no`，经济面没有可扣的余额列，closeout 只冻结投影并保持 `turn_no` 不动。下面 C 表把其余未冻的 payload 全部收成最小闭集。三块裁完可以 **GO**；残留只是安装期事实探针，每条都给了默认，不再构成「语义已裁、形状未裁」。

## 2. Current-state analysis

控制面循环今天是一条链：`v13_parse` 出信封 → `v13_advance(sid, snap)` 持 `sessions` 行锁 → 步 0 用 `v13_probe` 七键决定 `stale` → ① 终态直接 `terminal`；`ready|claimed|unknown` 合成一支，**一律** `UPDATE status='waiting'` 再返回 `waiting` → 其后才是 resolve 失败审计、abandon、`v13_context_fresh`、⑤ `v13_cycle_no` 对 `turn_budget.max_cycles`、judge 入队、`v13_route`、按 `action` 建账。`v13_route` 的动作闭集仍是 `finish|reject|human|sql|tool|llm`，工具身份来自信封 `tools_catalog` 的 `name/kind/handler`，不是来自 effect kind。

`effects.kind` 闭集是 `judge|tool|llm|context_refresh|human`。`tools.kind` 闭集是 `sql|tool|llm`。`v13_tools_guard` 只对 **enabled 且 kind=sql** 的 handler 做 `(uuid,jsonb)→jsonb`、非 VOLATILE、`v13_route` 可执行这三件事；`kind=tool` 的 handler 是 worker 分派键（种子形态 `worker:send_summary_email`），不进波动度守卫。`param_spec` 的键会被 needed 推导成 `param::`/`stated::` 信号，不能拿来塞控制元数据。目录没有 `mutating`、`input_schema`、`allowlist` 列；P1 不许加。

`v13_enqueue_effect` 用整份 request 的 jsonb 文本进 `v13_effect_id`。同 request 同 id；`failed|cancelled` 在 `v13_attempt_ok` 内则 `fence+1` 拉回 `ready`，**不改 request**。`unknown` 上再入队会 RAISE。`v13_complete` 在令牌失配时 `stale`，终态（含 `unknown`）`replay`，非 `claimed` 再 `stale`；成功的 `kind=tool` 同事务写 `tool/result`。没有任何函数更新 `effects.request` / `request_hash`。

`sessions.turn_no` 只在 `v13_append_event` 看见 `user/message` 时 `+1`。⑤ 只读 `v13_cycle_no`（本 user turn 内 `turn/route` 条数）和策略 `turn_budget.max_cycles`（种子 3），**不写 `turn_no`**。DP7 的压力、`R_o`、`v13_judge_spend` 都是查询投影；`v13_pricing` 是目录，不是会话余额。因此「预算终态同事务」在活体上没有可写的余额行，收据只能冻结投影。`v13_append_event` 把 `completed|failed` 在新 `user/message` 上复位成 `ready`，**不复位 `cancelled`，也不碰 `blocked_unknown`**。

`v13_requeue_stale` 的权威正文在 mgraph 加载态（覆盖 judge 与 `mgraph_consolidate` 的回收），不是 `v13/twophase/v13_twophase.sql` 里那一版。a2 把非回收 kind 的过期 `claimed` 打成 `unknown` 且 `fence+1`，不改 `sessions.status`。全树还没有 `harness` 字样、没有 `v13_closeout` / `v13_cancel` / `v13_resolve_unknown`。`events.type` 是开放词表。`events.payload_hash` 与 `effects.request_hash` 都是 `digest(jsonb::text,'sha256')` 小写 hex；jsonb 文本键序稳定，这是本库唯一的规范化序列化。

R3 已冻的、本轮只引用不改的合同：四值 `result_kind`、`wait_reason` 三词、审批两段、human 通道 one-of、`human/responded` 的键、`blocked_unknown` 双射、resolve 清回 `ready`（有 `ready|claimed` human 时 `waiting`）、cancel 不改 `claimed|unknown`、不改 session 终态、closeout 重放短路先行、⑤ 不新增 `turn_no` 写、P1 不装 sessions INSERT 触发器、fold cap 归 P4。R3a 已冻判别器（request 上成对的 logical pair ⇒ harness，且 P1 只许 `kind=tool`）和盖章的**读规则**（新 uuid / 沿用 id 且 index+1 / finish·reject 不续）；没冻的是「哪一次 tool 入队算生产」以及收据 JSON。

## 3. Design

### 3.H Harness 生产侧

**裁定采用 A 的严格形态，不采用 B，不采用 C。** 目录行提供 handler 与 route 落点（与 A17 的 `spawn_subsession` 同构：控制动词是一行 `tools` 数据）。名字是否算 harness 写死在函数里，因为策略行的 active 翻转不在步 0 七键里，而 `tools_revision` 已经在七键里；驱动或模型传「这是 harness」可以被伪造，R3a 已规定服务器是逻辑对的唯一写者。

#### 目录行（数据，不是 schema）

| 列 | 值 |
|---|---|
| `name` | `harness_turn` |
| `description` | `Run one external harness turn. The worker returns a harness_result verdict; the server stamps the logical pair.`（纯 ASCII，过现有 CHECK） |
| `kind` | `tool` |
| `handler` | `worker:harness_turn` |
| `param_spec` | `{}` |
| `enabled` | `true` |

`kind=tool` 所以不进 `v13_tools_guard` 的 VOLATILE/签名检查，也不进 A17 的具名 VOLATILE 例外。外部 IO 的失败语义就是现有 a2：租约过期进 `unknown`。不新增 `mutating` 列；`kind=tool` 已经表示「回滚后外部副作用可能还在」。`param_spec={}` 表示不生成 `param::`/`stated::` 题。已有信号 `tool` 的 pass 带（`default` v1，0.75）够用，**禁止**向已冻结的 `('default',1)` 再插带。

单源谓词（新函数，`IMMUTABLE`，正文里唯一一次字面量 `harness_turn`）：

```text
v13_is_harness_tool(p_name text, p_kind text) → boolean
  p_name = 'harness_turn' AND p_kind = 'tool'
```

扩员 = 改这个函数 + 设计修订 + gate 同发。多插一行别的 tool 不会变成 harness。

#### Request 闭集（仅这一行）

盖章后的 `effects.request` 恰好六键，`jsonb_build_object` 顺序固定为：

```text
tool              = 'harness_turn'
params            = {}          -- 空对象，零键
handler           = 信封冻结目录里该行的 handler 文本
tools_revision    = 信封 tools_revision，JSON 整数
logical_turn_id   = 小写 canonical uuid 文本，36 字符
continuation_index= JSON 整数 0..2147483647，拒绝小数
```

缺一、多一、单边、类型不对、uuid 非小写 canonical、index 越界：RAISE，零行。`params` 里若出现这两个逻辑键，同样 RAISE（不挪到顶层冒充）。普通 tool 的 request 维持今天的四键 `{tool,params,handler,tools_revision}`，两个逻辑键都必须缺席。

身份仍走 `v13_effect_id`：六键进哈希。运输重试必须重建同一份 jsonb，才是同一个 id。

#### 盖章执法点

盖章只发生在 `v13_advance` 里、**已经** `FOR UPDATE` session 之后、调用 `v13_enqueue_effect` **之前**。`v13_route` 保持 `STABLE`，不分配 uuid。`v13_send_work` 只发 `{kind:effect,id}`，看不见 request。`v13_enqueue_effect` **不发明**逻辑对（发明会使同一逻辑动作每次重试得到新 uuid，拆掉「同 request 同 id」）。

`v13_enqueue_effect` 增加的只是带层，签名不变：顶层出现 `logical_turn_id` 或 `continuation_index` 之一或两者时，必须两键都合法，且 `p_kind='tool'` 且 `v13_is_harness_tool(p_tool,'tool')`；否则 RAISE `v13: logical_turn_id required`，不 INSERT、不把 `failed` 拉回 `ready`。两键都缺席则维持今天的行为（judge/llm/human/普通 tool/context_refresh）。

`v13_complete` 增加的带层，同样在写行之前：`tool_name` 是 harness 而 request 无合法对 → RAISE `v13: logical_turn_id required`；有对但 `tool_name` 不是 harness，或 kind 不是 `tool` → RAISE 同一子串；有对则 `p_result` 必须过 `harness_result/v1`。普通 tool 的结果即使长得像四值对象也不进这套校验，advance 的消费查询也不得按「result 里有 `result_kind`」去认 harness。

sql 快路臂：路由到的工具名若是 `harness_turn`，RAISE `v13: harness_turn kind`，不 INSERT。这是配置错误（这一行被改成了 `sql`/`llm`），不是降级成快路。

不 `CREATE OR REPLACE` `v13_tools_guard`。名字闭集放在 enqueue/complete/advance 三处即可，避免整段复制 DP1 守卫、也避免 M1 对守卫正文的耦合。

#### 前驱与「首枚」

前驱查询（session 锁内，`STABLE` 读）`v13_harness_predecessor(p_sid) → uuid`：

- `kind='tool'` 且 `tool_name` 为 harness 名且 `origin_user_seq = v13_last_user_seq(p_sid)` 且 request 两键合法；
- 排序键 = 该 `effect_id` 在本会话 `events.source_effect_id` 上的 `max(seq)`，空则 `NULLS LAST`，再 `created_at DESC`，再 `effect_id DESC`；
- `LIMIT 1`。零行 → 本 user turn 没有 harness。

「首枚」= 该查询为空。它只是 R3a ① 的一种，**不是** index=0 的唯一定义。index=0 还有「前驱是已入账的 material progress」这一种。跨 user turn 的 harness 因为 `origin_user_seq` 对不上，看不见，不续传。

盖章模式（只看这一行前驱；更老的 succeeded wait/progress 若没有后继，先 RAISE `v13: harness tail gap`，禁止挑「最近一条」来掩盖断链）：

| 前驱 | 模式 | 逻辑对 |
|---|---|---|
| 无 | `new` | `gen_random_uuid()`，index `0` |
| `failed` 或 `cancelled` | `retry` | 原样抄前驱 request 的两键。整份六键因此与前驱相同 → 同一 `effect_id`，走现有重挂 |
| `succeeded` 且 `progress` 且该 source 已有 `turn/material_spent` | `new` | 新 uuid，index `0`。这是新 logical turn，不是续传 |
| `succeeded` 且 `progress` 且同批 signals 在、且没有该 source 的 material 收据 | `continue` | 抄 id，index = 前驱+1。溢出 int4 则 RAISE |
| `succeeded` 且 `progress` 且 signals 与收据同时存在 | 账本损坏 | RAISE `v13: material ledger` |
| `succeeded` 且 `wait`，且本格已经满足（approval：对应 human `succeeded`；evidence/quota：本事务已写或即将写 `wake/satisfied`） | `continue` | 同上 |
| `succeeded` 且 `finish` 或 `reject` | 不盖章 | 走 closeout。再入队 RAISE `v13: harness finish/reject does not continue` |
| `unknown` / `ready` / `claimed` | 不可达 | ① 或墙分支已经返回。到达即 RAISE |

R3a ① 里 `interaction_kind ∈ {material_cap,repair_cap,replan_cap}` 的 human 已答 ⇒ 新 uuid，本轮保留为**读规则**：若本 user turn 存在这样的 succeeded human，且其 `human/responded.seq` 大于前驱的 `effect_done.seq`，则模式改 `new`。P1 的 advance **不生产**这三种 human（cap 仍归 P4）。没有这种行时该子句不触发。

`new` 的 uuid 在事务内只生成一次。事务回滚后重来，生成另一个 uuid；已提交的重试走 `retry`/`continue` 的抄录，不再抽签。并发 advance 被 session 行锁串成一列，第二笔在 ① 看见 `ready|claimed` 后返回 `waiting`，不会第二盖章。

#### 续传与 route 的衔接

这是生产侧能落地的关键分叉，R3a 只写了「advance 盖章」没写谁决定入队：

- **`continue` 不调用 `v13_route`。** 若等下一轮判断碰巧又选中 `harness_turn`，逻辑转会停死。advance 在锁内直接入队下一枚 harness。入队前仍追加一条 `turn/route`，payload 恰好为 `{action:"tool", reason:"harness_continuation", tool:"harness_turn", params:{}}`，好让 `v13_cycle_no` 继续计次。`action` 仍在六词闭集里。
- **`new`（含首枚与 material 之后）必须经过现有 route。** 只有 `v13_route` 返回 `action=tool` 且目录 kind/name 通过 `v13_is_harness_tool` 时才盖 `new` 并入队。route 返回 `finish|reject|llm|human|sql` 或别的 tool 时，不造 harness。material 已入账的 progress 之后，控制流落回今天的 context 闸 → ⑤ 周期闸 → judge 缺口 → route，不跳过判断。
- **`retry` 同样只在 route 再次选中 `harness_turn` 时发生。** 失败行不会在背后自动重放。选中后六键与前驱一致，`enqueue` 重挂同一行。

续传入队后若行状态已是 `failed|cancelled`（attempt 封顶、enqueue 拒重挂）：**不** `v13_send_work`，走 closeout `failed`，`turn_end_reason='harness_attempts'`，`attempts_exhausted=true`。普通 tool 臂（`send_summary_email` 等）的「入队后一律 wake + waiting」保持原样，本规则只包 harness 臂和续传臂。

#### 与 attempt 上限

Harness 是 `kind=tool`，共用已有 `effect_attempt_cap.tool = 3`。不加 kind 键，不加策略行。

#### 谁消费

advance 认「待消费尾」的谓词是：本 user turn、`v13_is_harness_tool(tool_name, kind)`、request 对合法、`status='succeeded'`，且它就是 `v13_harness_predecessor`。权威列是 `effects.result`，不是 `tool/result` 事件。`complete` 对 succeeded tool **照旧**写 `tool/result`（recall 要看得见正文），advance 分派不读那条投影。

#### Gate（并入已点名的 `G-ctx10-logical-turn`，不另起平行门）

- 本 user turn 第一次 route 到 `harness_turn`：恰一枚 `kind=tool` effect，index `0`，uuid 小写 canonical，六键闭集，`effect_id` 随两键变化。
- 该 effect 仍 `ready|claimed` 时第二次 advance：零新行，返回 `waiting`。
- `failed` 后同一 route 再入队：同一 `effect_id`，`fence+1`，`attempt_no` 不变，两键不变。
- material 收据已写的 progress 之后，route 再次选中：新 uuid，index `0`。
- wait 或「progress+signal」之后：不调用判断也可出现 index+1 的新 effect，且有一条 `reason=harness_continuation` 的 `turn/route`。
- `session_stats` / `send_summary_email` / judge / llm / human 的 request 带任一逻辑键：enqueue RAISE，零行。
- `send_summary_email` 的 result 即使含 `result_kind=finish` 也不 closeout、不盖章。
- 直接 `enqueue('harness_turn')` 缺对或单边：RAISE。

### 3.A16 Closeout 收据

#### 住哪

收据就是事件 payload，不再套一层 `receipt`。类型是事件 type，不是 payload 里的第二枚举。三型 payload **键集相同**，差别在 type、`sessions.status`、以及 `turn_end_reason` 的取值。

| type | `sessions.status` | 典型 `turn_end_reason` |
|---|---|---|
| `session/completed` | `completed` | route 的 reason（如 `answered`），或 `harness_finish` |
| `session/failed` | `failed` | `injection_veto`、`budget_exhausted`、`resolve_budget`、`judge_attempts`、`context_refresh`、`harness_reject`、`harness_attempts`、`approval_exhausted` |
| `session/cancelled` | `cancelled` | `cancel` |

同事务、在改 status 之前，另写 **一条** 与今天同形的 `turn/end`：`completed` → `{delivered:true, reason}`；`failed|cancelled` → `{delivered:false, reason}`；仅当调用方传入 attempts 耗尽时多一个 `attempts_exhausted:true`（键缺席表示否，不写 `false`）。`attempts_exhausted` **不**进收据。这样 DP1 读 `turn/end` 的人仍能工作。`v13_closeout` 是这两条事件和这三次 status 赋值的唯一写者；换体后的 advance 里不再直接 `append turn/end` 或直接 `UPDATE status` 到这三个终态。

#### 收据键闭集

```text
{
  schema_version: 1,                          -- JSON 数字，恰好 1
  spent: {                                    -- 恰好四键，全是 JSON 整数 ≥ 0
    turn_no,          -- sessions.turn_no 原值抄出
    cycle_no,         -- 此刻 v13_cycle_no(sid)
    max_cycles,       -- 活动策略 turn_budget.max_cycles
    material_count    -- 本会话 turn/material_spent 事件条数（跨 user turn 的累计）
  },
  produced_hashes: [ "<64 lowercase hex>", ... ],  -- 升序、去重；可空数组
  children: [],                               -- P1 恒为空数组，禁止 null
  unconsumed: {                               -- 五键都在，值都是升序去重的小写 uuid 文本数组
    repair_effect_ids,
    replan_effect_ids,
    material_effect_ids,
    wake_pending_effect_ids,
    approval_pending_effect_ids
  },
  state_hash: "<64 lowercase hex>",
  turn_end_reason: "<1..128，字符集 [A-Za-z0-9_./:-]+>"
}
```

未知键 RAISE。`spent` 用对象而不是一个整数：活体里「花费」同时是 user-message 计数列、周期投影和 material 事件，压成一个数会说谎。`turn_no` 这一键就是迁移报告 §8 要抄进收据的那个已提交值。

**`produced_hashes` 算法。** 安装期看目录：若 `artifacts` 有 `content_hash` 与 `produced_by`，取

```text
DISTINCT content_hash
FROM artifacts a
JOIN effects e ON e.effect_id = a.produced_by
WHERE e.session_id = :sid
  AND e.status = 'succeeded'
  AND content_hash ~ '^[0-9a-f]{64}$'
ORDER BY 1
```

若这两列不存在：**不加列**。退化为沿 `sessions.context_active_artifact` 的 `replay.prior_artifact_id` 链（深度上限 64）收集 manifest `sections[].content_hash`，同样的正则、升序去重；并让 wake 的 `artifact` 变体在求值时 RAISE `v13: artifact wake requires content_hash`（与 `children_terminal` 的 P1 拒收同一手法）。两条路都没有可收集的哈希时，数组为 `[]`，closeout 仍可成功。不把 DP7 的 section 哈希和 artifact 行哈希混加两次：有 `content_hash` 列就只走连接查询。

**`children`。** P1 不装子会话汇总。`EXISTS (sessions WHERE parent_session_id = :sid)` 时，任何 outcome 都 RAISE `v13: closeout children require stage 18`，零写入。没有子行才写 `[]`。P2 才允许元素 `{session_id, status, state_hash}`，那是 schema_version 2 的事，P1 不写元素。

**`unconsumed` 谓词（全部限定本会话）。**

- `repair_effect_ids`：`type='repair/required'` 的 `source_effect_id` 全集。P1 没有消费标记，不做减法。P4 若要扣掉已消费项，必须升 `schema_version`，不许悄悄改 v1 的含义。`replan_effect_ids` 对 `replan/required` 同样。
- `material_effect_ids`：R3a 的 material 候选（succeeded harness、对合法、`finish` 或「`progress` 且该 source 没有 repair/replan 事件」）里，尚无 `source_effect_id` 指向自己的 `turn/material_spent` 的那些 effect。
- `wake_pending_effect_ids`：succeeded harness，`result_kind=wait` 且 `wait_reason ∈ {evidence,quota}`，且不存在该 source 的 `wake/satisfied`。
- `approval_pending_effect_ids`：succeeded harness，`wait+approval`，且不存在 `kind=human`、`request->>'interaction_ref' = result->>'interaction_id'`、`status='succeeded'` 的行。

#### 「预算终态同事务」做什么

不做余额更新。具体动作是：在同一事务里把上面的 `spent` 对象写进印章事件，然后 `UPDATE sessions.status`。禁止 `turn_no` 的任何赋值，禁止写 `turn/material_spent`，禁止写 `quota/spent` 或 `quota/voided`，禁止改 `v13_policies`。⑤ 的周期闸仍是「`v13_cycle_no >= max_cycles` 就走 budget human」，与 material 收据并列，互不替代。material 收据只在消费候选的那一格 advance 里追加，closeout 若发现 completed/非逃生 failed 上还有未付候选，是 RAISE 而不是补记。

#### 前置矩阵

函数 `v13_closeout(p_sid uuid, p_outcome text, p_reason text, p_attempts_exhausted boolean DEFAULT false) → jsonb`。`p_outcome ∈ {completed,failed,cancelled}`。锁序：调用方若已持 session 锁则重入；否则函数自己 `FOR UPDATE` session。先于一切计数：

1. **已终态短路。** `status` 已是三终态之一：不查计数、不重算收据。恰好一条 `session/<status>` 事件则返回其 **已存储** payload（jsonb 相等，不重建）。零条 RAISE `v13: closeout missing seal`。多于一条 RAISE `v13: closeout duplicate seal`。传入的 outcome 与现存 type 不一致 RAISE `v13: closeout outcome conflict`。返回后 advance 仍向自己的调用方返回 `'terminal'`。
2. 公共前置（失败则 RAISE `v13: closeout precondition`，带一个稳定尾词，零写入）：
   - `ready|claimed` 且 `kind <> 'human'` 的计数 = 0（**active**）；
   - `status='unknown'` 的计数 = 0；
   - `v13_pending_human(sid)` 为假，谓词 = `kind='human' AND status IN ('ready','claimed')`（与 C1 清回 waiting 用同一函数）；
   - `sessions.status <> 'blocked_unknown'`；
   - 无子会话（上一节的 RAISE）。
3. **严格前置**（`completed`，以及 `failed` 且 reason 属于 `{harness_reject}` 或 route 的否决 reason 如 `injection_veto`）：`material_effect_ids`、`wake_pending_effect_ids`、`approval_pending_effect_ids` 必须全空，且「续传未还」为假。续传未还 = 最新 harness 是「progress+signals」或「已满足的 wait」，并且不存在同一 `logical_turn_id`、index+1 的后继。违者 RAISE `v13: closeout wake pending` / `approval pending` / `unpaid material` / `continuation owed`，对应数组不写入事件。
4. **逃生前置**（`cancelled`，以及 `failed` 且 reason ∈ `{budget_exhausted, resolve_budget, judge_attempts, context_refresh, harness_attempts, approval_exhausted}`）：第 3 步四项**不挡**。收据里的五个数组按实填写，允许非空。active/unknown/pending human/墙/子会话仍挡。

因此：**未满足的 evidence/quota wait 不能完成、也不能以 harness_reject 收场，但可以被 cancel 或预算逃生收场，并且收据里看得到被放下的 effect id。** approval 尚无 succeeded human 时同样。已满足却还没 index+1 的续传，对 completed 是硬拒；advance 必须先走续传臂，而不是在同一格里 closeout。

`active` 把 human 摘出去，是为了让三计数可以分别断言。一个 `ready` human 只落在 pending human 上，不重复计进 active。`unknown` human 只落在 unknown 上。

#### 同事务写序

1. 前置。
2. 计算 `spent`、`produced_hashes`、`children`、`unconsumed`、`turn_end_reason`（此时还没有印章事件）。
3. `v13_append_event(..., 'turn/end', ...)`。
4. 计算 `state_hash`（见下；此刻 `turn/end` 已在日志里，印章事件还不在）。
5. `v13_append_event(..., 'session/'||outcome, receipt)`，`source_effect_id` 为空。
6. `UPDATE sessions SET status = outcome`。不碰 `turn_no`、`next_seq`（append 已经在动 `next_seq`）、策略、effect 行。

任一步 RAISE，整笔事务回滚，不存在「有终态无收据」。

#### `state_hash`

输入是一个 jsonb 数组的 `::text`（与 `request_hash` 同一规范化），再 `sha256` 小写 hex。禁止 `jsonb_pretty`，禁止 `row::text`。所有标量在进入数组前变成 text，避免 `1` 与 `1.0`。

```text
[
  "v1",
  [session_id, turn_no, route_policy_name, route_policy_version,
   goal_hash, tools_revision, candidate_generation_revision,
   max_seq_among_non_seal_events],          -- 无事件则 "-1"
  [ effect 行按 effect_id 文本升序，
    每行 [effect_id, kind, status, attempt_no, fence,
          tool_name 或 "", request_hash, origin_user_seq] ],
  [ 非印章事件按 seq 升序，
    每行 [seq, type, payload_hash, source_effect_id 或 ""] ]
]
```

印章 type 三词不进第四段。`sessions.status` 与 `next_seq` 不进输入（它们会被第 5、6 步改变）。`goal_hash` 与两个 revision 用 `v13_probe` 的同名值，但 `max_event_seq` 改用「排除三枚印章 type 之后的 max(seq)」，这样第 3 步写下的 `turn/end` 算进去，第 5 步的印章不算。哈希因此在提交之后、**任何后续 effect 变更之前**可以重算一致。

R3 允许终态会话上的 a2 继续把 effect 打进墙。那会改变第三段的 `status`。所以 **state_hash 的合同是印章里存下来的那一串**，不是「永远可从活表重算」。Gate 在 closeout 返回前重算一次必须相等；另开一个在 requeue 之前的事务重算必须相等；requeue 之后不再要求相等。

#### 与 advance 各终态臂

下列今天直接写 `turn/end` + status 的臂，全部改成调用 `v13_closeout`：route `finish`、route `reject`、abandon、budget、context_refresh 封顶、judge attempt 封顶、以及本轮新增的 `harness_finish` / `harness_reject` / `harness_attempts` / `approval_exhausted` / cancel 封印。周期闸和预算 human **不**挡住 `finish|reject` 的封印（那不是新工作）。它们挡住续传、审批 human 入队、以及落回 route 的新工作：周期已满时走 `budget_exhausted` 逃生封印，不入队下一枚 harness。

#### 二次调用的字节语义

第二次：零 `INSERT`、零 `UPDATE`，返回第一次写入的 payload。jsonb 比较与键序无关。函数不读 `p_reason` 去改写已存 reason。advance 的返回词仍是 `'terminal'`，没有新词。

### 3.C 完备性扫掠

上一节的 advance 换体顺序在这里收成一份总账，避免 C 与 H/A16 各写一套。session 锁内：

1. 步 0 七键。不一致 → `stale`。不修漂移。
2. status 已终态 → `terminal`。
3. 存在 `unknown` 或 status 已是 `blocked_unknown`：若 status 不是墙、也不是终态，RAISE `v13: unknown wall drift`（只拒绝，不写回）。若有未消费的 `cancel/requested`，把本会话全部 `ready` effect 收成 `cancelled`（`fence+1`，attempt 不动，`error` 置 NULL，租约清空）。然后 **不更新 session**，返回 `waiting`。今天那句覆盖 `unknown` 的 `SET status='waiting'` 删除。
4. 未消费 cancel，且没有 unknown：先做同一套 ready→cancelled 清扫。仍有 `claimed` → 按今天的 ① 把 session 置 `waiting`（仅当当前是 `ready|waiting`），返回 `waiting`。已无 `ready|claimed|unknown` → `v13_closeout(...,'cancelled','cancel')`。
5. 无 cancel、仍有 `ready|claimed` → 今天的 ①（置 `waiting`，返回 `waiting`）。
6. 若本 user turn 有 harness 前驱，进入消费相（H 的表）：finish/reject 在这里封印并返回，**不受**周期闸阻挡；未满足的 evidence/quota wait 把 status 置 `waiting` 并返回，零新 effect；缺审批 human 则在周期闸允许时入队审批 human，否则预算逃生；该续传则走续传臂；material 候选在这里按 R3a 写或拒绝 `turn/material_spent`（不改 `turn_no`），然后**落回**下面的旧管线。
7. 旧管线，仅当 6 没有 return：`snap.failed` 审计、abandon、context 闸、周期闸、judge 缺口、`v13_route`、各臂。tool 臂里才可能 `new`/`retry` 盖章。`finish`/`reject`/各 attempts 封顶改走 closeout。

无 harness 前驱的会话不进入第 6 步。除了终态臂多写一枚印章事件之外，判断、入队、返回词与今天一致。

返回词闭集仍是 `progressed|waiting|terminal|stale`。再出现别的词就是实现错误，应 RAISE，而不是新增返回值。协议错误一律在写 effect 行之前 RAISE，不烧 attempt/fence，不走 `failed` 降级（llm 空文本降级仍是唯一的「改写成 failed」例外）。

#### 逐项

| 项 | 状态 |
|---|---|
| 部分索引 `effects(session_id) WHERE status='unknown'` | 已冻（R3 §2.1）。名字定为 `ix_effects_unknown`。 |
| `v13_raise_unknown_wall(p_sid uuid) → void` | 已冻（R3 附款）。`INVOKER`，`search_path=pg_catalog,public`。只把 `ready|waiting` 且存在 unknown 的会话改成 `blocked_unknown`；已是墙或终态则不动；绝不拆墙。a1/a1' 不调用。 |
| `v13_requeue_stale` 换体 | 行为主体已冻。**底稿必须是 mgraph 加载态**，回收 kind 集以活体为准，禁止用 twophase 旧体覆盖。本轮只加一条分叉：回收臂（租约过期、attempt 仍允许、活体认定可重放的 kind）若该会话有未消费 cancel，则改成 `cancelled`+`fence+1`+清租约，attempt 不动，`error` NULL，**不**计进 `reclaimed_ready`，**不** `v13_send_work`。返回键集不变，因此这一支不新增计数键。a2 仍按 R3 把非回收 kind 打进墙并抬 session 墙，终态会话上的 effect 允许进墙且不 RAISE（整次清扫不中止）。a1' 仍是 `failed`+`lease_exhausted`。锁序维持 R3：先收集 session_id，按 session_id 升序 `FOR UPDATE`（不用 `SKIP LOCKED`），重检后再改 effect。 |
| `v13_complete` 换体 | 顺序已冻（R3a §6.5）。在「replay/stale 之后、写行之前」插入 H 的逻辑对带层与 v1 校验。`stale`/`replay` 先于一切 schema 错误。human 校验的应用面见下栏 C4，避免把 DP1 的 `{reason}` human 一起拒掉。 |
| `v13_resolve_unknown(p_effect uuid, p_resolution text, p_evidence jsonb) → text` | 效果已冻（报告 §4.1 + C1）。本轮补上证据闭集与事件 payload。成功只返回 `'accepted'`；失败 RAISE，不用 `stale`/`replay` 词。锁：函数自己 session → effect。`confirmed→succeeded` 且 `error=NULL`；`rolled_back|not_happened→failed`。`attempt_no`、`fence`、`request`、`result` 都不改（a2 已经加过 fence；再加会把工人的 `replay` 变成 `stale`）。不入队、不调用外部 IO。清回规则用 `v13_pending_human`：仍有别的 unknown 则保持 `blocked_unknown`；没有、且 status 是墙、且非终态时，有 pending human → `waiting`，否则 `ready`；终态会话不改 status。 |
| `unknown_resolved` payload | **未冻→裁定。** 恰好 `{schema_version:1, effect_id, resolution, evidence_hash}`。`effect_id` 为小写 uuid 文本。`resolution` 三词。`evidence_hash = encode(digest(p_evidence::text,'sha256'),'hex')`，不存正文，不用 `jsonb_pretty`。`source_effect_id` 指向该 effect。`failed` 的两支另外把 `effects.error` 写成 `{code:"unknown_resolved", resolution, evidence_hash}`，仍不放正文；`confirmed` 把 error 清成 NULL。证据闭集：`confirmed` = `{observation:"committed", payload_hash}`，且 `payload_hash` 必须等于 `digest(effects.result::text)`，`result` 为 NULL 则 RAISE；`not_happened` = `{observation:"absent"}` 恰好一键；`rolled_back` = `{observation:"rolled_back", compensation_ref}`，`compensation_ref` 为 1..256 且匹配 `^[A-Za-z0-9_./:-]+$`。多键、缺键、`observation=unknown` 都 RAISE，行与事件零变化。 |
| A16 收据 | **未冻→已在 §3.A16 裁定。** |
| `v13_cancel(p_sid uuid) → text` | 行为已冻，payload 未冻。返回 `'accepted'` 或 `'replay'`。终态 → `replay` 且零写入（封印后不再扫 effect，避免改写已经进 `state_hash` 的那一版；之后的漏网由 requeue 的既有终态规则处理）。非终态：session 锁后按 `effect_id` 升序锁 effect。没有未消费 `cancel/requested` 就追加一条；已有则不再追加，但 **仍然** 把 `ready` 扫成 `cancelled`（否则 requeue 在两次 cancel 之间放回的 judge 会逃掉）。`claimed|unknown` 不动。不改 `sessions.status`。未消费 = 存在 `cancel/requested`，且其 `seq` 大于本会话 `session/cancelled` 的 max(seq)（没有印章则大于 -1），且 status 非终态。 |
| `cancel/requested` payload | **未冻→裁定。** 恰好 `{schema_version:1, scope:"session"}`。`source_effect_id` 为空。P1 没有别的 scope。不带自由文本，避免第二事实源。 |
| advance 换体 | **未冻的部分已在本节开头的 1–7 步裁定。** 步 0 七键、不修漂移、unknown 分支删除写 `waiting`，均是已冻合同的落实。 |
| C4 human 通道 | 通道形状已冻。**应用谓词补一句，否则换体后的 complete 会拒绝一切 DP1 human。** 仅当 `kind='human'` 且 `p_status='succeeded'` 且 `request` 含 `interaction_ref` 时跑 one-of / `schema_version=1` / 字节相等 / 未知键拒绝。不含 `interaction_ref` 的 `{reason}` human：按今天的方式 `succeeded`，**不**写 `human/responded`。审批 human 由 advance 写成恰好 `{schema_version:1, interaction_ref}` 两键（`interaction_id` 逐字节复制；不写 `prompt`，不写 `interaction_kind`，因为 harness 结果里禁止这两键，P1 没有题面来源）。`skip=false` 与缺席等价这句维持 R3。 |
| 审批 human 与「恰一个」 | 已冻。本会话已有 `kind=human AND status IN ('ready','claimed','unknown')` 时再为 approval 入队即 RAISE。表达式唯一索引维持 R3：`UNIQUE (session_id, (request->>'interaction_ref')) WHERE kind='human' AND request ? 'interaction_ref'`。`{reason}` human 不进这个索引。 |
| `human/responded` | 已冻（R3 C5）。`origin_user_seq` **抄 `effects.origin_user_seq` 列，不调用 `v13_last_user_seq` 重算**。未用通道写 JSON null。只在审批通道 `succeeded` 时写一条；`failed|unknown|replay` 与 legacy `{reason}` 都不写。 |
| `turn/material_spent` payload | **未冻→裁定。** 恰好 `{schema_version:1, effect_id}`。`effect_id` 为被 ⑤ 消费的那枚 effect 的小写 uuid 文本。不放 `logical_turn_id` / `continuation_index`。`source_effect_id` 指向同一 effect。计数公式维持 R3a：按 source effect 的 request 对归并到 logical turn。同 source 的部分唯一索引 + `v13_material_spent_guard` 维持 R3a（先锁 session，只 RAISE 不代扣）。 |
| `wake/satisfied` | 已冻键集 `{effect_id, wake_kind}`，不加 `schema_version`。`wake_kind` 值域 = `event|not_before|artifact|children_terminal`。P1 求值器只可能写出前三个；`children_terminal` 在 complete 里 schema 通过后仍 RAISE `v13: children_terminal requires stage 18`。`effect_id` 为小写 uuid 文本。同 source 至多一条。approval 全程零条。 |
| `v13_wake_is_satisfied_v1` | 语义已冻。**波动性更正：** 必须标 `VOLATILE`，因为 `not_before` 用 `clock_timestamp()`，不能标 R3a 草案里的 `STABLE`（规划器会缓存）。只从 advance 调用一次，不放进索引。比较仍是 `clock_timestamp() >= at::timestamptz`，不用 `now()`。 |
| `repair/required`、`replan/required` payload | **未冻→裁定。** 各自恰好 `{schema_version:1}`。不放 effect_id（连接键是 `source_effect_id`），不放逻辑对。complete 按 repair 然后 replan 的固定顺序各写一条。同会话同 source 同 type 至多一条。 |
| `forked` | 已冻在 stage 14 的现有生产者里。P1 不读、不改、不重放。 |
| steer 断言 | **未冻→裁定。** P1 **不**新增 `v13_steer` 生产者。Gate 名 `G-steer-frozen-request`：claim 一枚 tool（含 harness）后记下 `request` 与 `request_hash`；用 `v13_append_event` 写一条 `steer/injected`，payload 恰好 `{"schema_version":1}`，`source_effect_id` 为空；断言 effect 的 request、request_hash、status、fence、attempt_no 都不变；拿旧信封再 advance 得到 `stale`（`max_event_seq` 变了）；用原令牌 `complete` 仍可 `accepted`。不引入 `text` 字段；真要携带转向正文是 schema 2 的事。 |
| pending human 与 C1 | **补谓词，两边共用 `v13_pending_human`。** closeout 的 pending 与 resolve 清回 `waiting` 的条件是同一谓词：`kind='human' AND status IN ('ready','claimed')`。`unknown` human 走 unknown 计数，不把墙清成 `waiting`。`succeeded|failed|cancelled` human 两边都不算 pending。因此「有待答 human 时 closeout 被拒」与「resolve 最后一条墙时改为 waiting」不会对同一行做出相反的终态决定。 |
| G4 负例集 | **未冻→裁定。** 正例只有 `v13_resolve_unknown` 能把 `unknown` 写成 `succeeded|failed`。负例（status、fence、attempt 不变，零 `unknown_resolved`）：`v13_complete` 任何 outcome → `replay`；`v13_requeue_stale` 不更新已是 `unknown` 的行；`v13_cancel` 不更新；`v13_enqueue_effect` 同一 id → 异常且行仍是 `unknown`；`v13_renew_lease` → `false`；`v13_claim` 领不到；`v13_advance` 不改该 effect，也不把墙写成 `waiting`；`v13_closeout` RAISE 且零印章。不设 GUC 来挡表主的裸 `UPDATE`（与 D4 否决 GUC 同一理由）。超级用户裸 SQL 是破玻璃，gate 不覆盖。 |
| `harness_result_schema` 策略行 | **未冻→裁定。** `v13_policies` 一行：`name='harness_result_schema'`，`version=1`，`active=true`。`value` 恰好两键：`dialect` = `"draft-07"`，`schema` = 一份 JSON Schema，其 `$schema` 必须是 `http://json-schema.org/draft-07/schema#`。complete 只在 harness 路径读取活动行；普通 complete 不依赖这行。缺活动行沿用 `v13_policy` 的 RAISE。校验函数 `v13_validate_harness_result_v1(p_result jsonb) → void`，失败 RAISE `v13: harness_result schema`。扩展入口默认 `jsonb_matches_schema(schema, instance)`；安装第一件事探针签名，名字不同就用探针结果，不换库。Schema 正文是 R3a §6.1–6.2 矩阵的机械转写：顶层十键、`additionalProperties:false`、四值 if/then、wake 四变体 oneOf、`format: date-time` 只用于 `wake.at`。SQL 仍只留下 schema 表达不了的部分：逻辑对在 request 上、`children_terminal` 的 P1 RAISE、interaction 字节连接、批次尾 seq、signals 与事件集相等。 |
| 八键里尚未在 R3a 写明类型的三键 | **未冻→默认（安装期若在设计/R1/ch07 找到字面类型，用找到的，本默认作废）。** 找不到则：`harness_session_ref` 字符串 1..256、字符集 `[A-Za-z0-9_./:-]+`，可缺席，禁止 null；`resume_token` 字符串 1..512，可缺席，禁止 null；`partial` 布尔，可缺席，禁止 null。三键加 `delivery_kind`、`content_hash` 都是盲读：改变它们不改变建不建 effect（扩 `G-ctx10-delivery`）。`interaction_id`、`result_kind`、`wait_reason`、`wake`、`signals` **不**盲读。 |
| 双射触发器 | 已冻（R3 C2/C3）。共享函数只 RAISE 不改行。effects 侧覆盖 INSERT/DELETE/`UPDATE OF status, session_id`（session_id 若被改，新旧两侧都查）。sessions 侧覆盖 INSERT/`UPDATE OF status`。非终态上 `EXISTS(unknown) ⇔ status='blocked_unknown'`。终态允许残留 unknown。`DEFERRABLE INITIALLY DEFERRED`。安装顺序维持：回填 → 断言 → `DROP TRIGGER IF EXISTS` → 建触发器 → **然后**才 `CREATE OR REPLACE` 那些会写 `unknown` 的函数。回填只把 `ready|waiting` 且存在 unknown 的行改成 `blocked_unknown`，`RAISE NOTICE` 行数，不写事件；`blocked_unknown` 且零 unknown、或 `ready|waiting` 且仍有 unknown → RAISE 并带上 session_id 列表；`completed|failed|cancelled` 且有 unknown 只 NOTICE。 |
| GRANT | 已冻方向。新函数全部 `REVOKE PUBLIC` 后 `GRANT v13_route`：墙 helper、pending human、predecessor、`v13_is_harness_tool`、closeout、cancel、resolve_unknown、validate、wake、state_hash。不授 `v13_resolve`、不授 `v13_recall`。`OR REPLACE` 的 advance/complete/enqueue/requeue 再执行一次同样的 REVOKE/GRANT（幂等）。触发器函数不 GRANT。 |
| enqueue 与未消费 cancel | **未冻→裁定。** `v13_enqueue_effect` 在插行和重挂之前：该会话有未消费 `cancel/requested` 则 RAISE `v13: unconsumed cancel/requested`，零行、不 `fence+1`。advance 的正常路径在入队前已经转去 cancel 相，不会靠这个异常来控制流；这道带防的是直接调用。 |
| cancel 的 `fence+1` 与 requeue 计数 | **未冻→裁定。** cancel 扫到的是 `ready`，requeue 只看过期 `claimed`，两者不撞同一行。唯一的交叉是：cancel 之后 a1 本会把 judge 放回 `ready`。该交叉由 requeue 的 cancel 分叉收成 `cancelled`，不进 `reclaimed_ready`，也不再被 claim。随后 complete 用旧 fence 得到 `stale`。 |
| `v13_context_fresh` / 七键 / `turn/end` 的 delivered 形状 | 已冻。closeout 复用 delivered 形状，不改探针。 |
| G-ctx10-spend 里「超限 repair 走 human、零新 spawn」 | 语义在 R2，**P1 不实现**（R3a §6.7：cap 归 P4 thresholds）。stage 17 的该门只断言：finish 与无 signal 的 progress 各记 1 条收据；同批 signal 的 progress 记 0；同 source 重放不第二扣；另一枚 effect 复用同一 logical_turn_id 时 RAISE 且收据仍为 1；closeout/complete/resolve/cancel 不写收据、不改 `turn_no`。spawn 断言不在本 stage。 |
| 子树全终态、interruptible、worktree、`v13_open_session`、sessions INSERT 触发器 | 已冻为 P2/P3。stage 17 不装。 |
| `closeout/inbox_residual` | 迁移报告点过名，R3 交付清单没有它。**裁定 P1 不写这个 type。** 残留在收据 `unconsumed` 里。 |
| harness finish 的「验收门」 | R2 有这四个字，没有 P1 谓词。**默认：P1 验收 = closeout 的严格前置，外加 result 已过 v1。** 不读 thresholds，不另做 rubric。 |
| advance 在 `blocked_unknown` 期间 claim 仍可领 `ready` | 已知缝，不是形状洞。P1 不改 `v13_claim`。closeout 仍被 active 计数挡住。 |

#### 新索引（与 R3a 已点名的那些一起建）

- `ix_effects_unknown (session_id) WHERE status='unknown'`
- `ux_events_wake_satisfied (session_id, source_effect_id) WHERE type='wake/satisfied'`
- `ux_events_signal (session_id, source_effect_id, type) WHERE type IN ('repair/required','replan/required')`
- `ux_events_material (session_id, source_effect_id) WHERE type='turn/material_spent'`
- `ix_events_source_type (source_effect_id, type)`
- `ux_effects_approval_interaction (session_id, (result->>'interaction_id'))`，WHERE 为 succeeded tool、request 含 `logical_turn_id`、`result_kind=wait`、`wait_reason=approval`
- human `interaction_ref` 唯一索引：R3 原文
- `ix_effects_harness_pair (session_id, (request->>'logical_turn_id'), ((request->>'continuation_index')::int)) WHERE kind='tool' AND request ? 'logical_turn_id'`

`BEFORE INSERT` 触发器 `v13_control_event_guard`，`WHEN` 限制在 `wake/satisfied`、`repair/required`、`replan/required`、`turn/material_spent`、`human/responded`、`unknown_resolved`、三枚 `session/*`、`cancel/requested`。只 RAISE：该有 `source_effect_id` 的 type 不许空；payload 键集必须等于上面各栏。`v13_material_spent_guard` 仍只负责「至多一条 + 候选资格」，不负责别的 type。两触发器都不改行、不入队。

#### 安装探针（写进 stage 17 事务开头的 `DO`）

`pg_jsonschema` 装不上就让 `CREATE EXTENSION` 失败退出。用活动 schema 接受 `2026-09-26T00:00:00Z` 与 `2026-09-26T00:00:00+00:00`，拒绝无时区字符串和纯数字 epoch。拒绝失败则 RAISE `v13: pg_jsonschema draft-07 date-time not enforced`，整笔安装回滚。不降级成 CHECK。

## 4. File-by-file impact

| 文件 | 变更 | 为何 | 顺序 |
|---|---|---|---|
| `v13/control/v13_control.sql` | **新文件**，自带与 `v13_economy.sql` 相同的 `BEGIN/COMMIT`。内容：扩展探针、`harness_result_schema` 种子、`harness_turn` 种子、§3 的新函数与两个事件守卫、§3.C 的索引、C3 回填与双延迟约束触发器、`CREATE OR REPLACE` 于 `v13_advance`、`v13_complete`、`v13_enqueue_effect`、`v13_requeue_stale`、GRANT/REVOKE。 | 迁移报告：新行为只追加 stage，不改 1–16 的文件字节。 | 依赖 1–16 已加载。文件内部顺序就是 C3：种子与索引 → 回填 → 断言 → 触发器 → 函数换体。 |
| `v13/load.py`（符号名以活体 `SQL_LOAD_ORDER` 为准） | 在末项 `mgraph_assembly` 之后追加这一文件为 stage 17。不重排前 16 项。 | 前缀加载必须看不见 stage 17。 | 与新文件同时落地。 |
| `v13/control/test_control.py` | **新文件**。覆盖 R3 §2 已点名各门，加上 §3.H 并入 `G-ctx10-logical-turn` 的生产者断言、§3.A16 的收据字节与重放、`G-steer-frozen-request`、`G-cancel-requeue`（cancel 之后 requeue 不再把 judge 放回 ready）、G4 负例表、C4 对 `{reason}` human 的兼容断言（succeeded、零 `human/responded`）。 | 门是本轮的执法面。 | 可在 SQL 加载之后单独跑。 |
| `docs/designs/v13-context-on-pg.md` §6.8 与 §10 | 追加：生产者是 `harness_turn`、六键 request、续传不经 route、收据键集与 `state_hash` 算法、`spent` 四键、wake 的 `VOLATILE` 更正、三注解键的默认类型、fold-cap/children/inbox_residual 的 P1 边界。§10 的 G-ctx10-spend 标注「超限 repair」不在 stage 17。 | R3a §6.5 已要求设计同步；不改会让下一轮再停在文档与 SQL 不一致上。 | 与 SQL 同一变更，不阻塞编译。 |
| `docs/reviews/v13-control-plane-oracle-r3b-2026-09-26.md` | 把本裁定原文落入仓库。 | 与 R2/R3 同级，实施时只引用不重开。 | 可与代码同时。 |
| `v13/schema/v13_core.sql`、`v13/loop/advance.sql`、`v13/twophase/v13_twophase.sql`、`v13/economy/v13_economy.sql`、mgraph 下的 requeue 源文件 | **不改字节。** | 前缀 gate 加载这些文件。换体只出现在 stage 17。 | — |

`v13_enqueue_effect` 的调用点（advance 各臂，以及 stage 17 的续传/审批 human）签名不变，靠 request 形状选带层。`v13_complete`、`v13_advance`、`v13_requeue_stale` 的外部签名与 requeue 的 jsonb 键集不变。

## 5. Risks and migration

- **C4 若不加「仅当 request 含 `interaction_ref`」这个应用谓词，stage 17 一加载就会让所有 `{reason}` human 无法 `succeeded`。** 这是与 DP1 的兼容线，不是新通道。
- **终态臂全部改道 closeout 之后，全量加载（含 stage 17）的旧测试若精确计数 `turn/end` 且不允许多一条 `session/*`，会红。** 前缀 1–16 不受影响。实施时搜 `turn/end` 的断言，全量测试改为期待 `turn/end` 加恰好一条印章。
- **`state_hash` 在 seal 之后不是活不变量。** R3 的「终态会话 effect 仍可进墙」会改 effect status。Gate 只在 requeue 之前重算。
- **续传跳过 `v13_route` 是有意的义务，不是第二套调度器。** 它仍写 `turn/route`、仍占 `effect` 行、仍受 `turn_budget.max_cycles` 限制。漏写这条 `turn/route` 会让续传不烧周期。
- **mgraph 活体 requeue 若被 twophase 文本覆盖，会丢掉 `mgraph_consolidate` 的回收。** 换体前先 `pg_get_functiondef`。
- **`artifacts.content_hash` / `produced_by` 若并不存在，wake 的 artifact 变体在 P1 不可用，`produced_hashes` 走 manifest 链。** 不加列。这是事实分支，不是再开一轮裁决。
- **三注解键的类型默认可以被仓库里已有的 R1 字面推翻，但不能被实施者第三种写法推翻。**
- **策略 schema 在 effect 飞行中被换成新 version 时，complete 按新 schema 拒旧结果。** 这是 fail-closed，不把 schema 版本塞进七键。
- **`gen_random_uuid` 不可在测试里写死。** 断言格式、同事务稳定、以及 retry 时 id 不变。
- **双 `BEGIN`。** `v13_economy.sql` 自带事务，loader 因此接受文件内 `BEGIN/COMMIT`。若活体 loader 已经在外面包了一层，嵌套会在第一次加载即失败；那时删掉文件内包装，保留「回填到换体同一事务」，不要改语义。
- **stage 17 的 `INSERT INTO tools` 会拨 `v13_tools_meta.revision`。** 断言继续用相对比较。它不拨 `candidate_generation_revision`（没有替换 `v13_needed_judgments`）。
- **回填不写事件、不改终态残留。** 与「终态可以带着 unknown 重放印章」一致。先挂触发器再换 `v13_complete` 会让旧函数写 `unknown` 却不抬墙，提交被双射打回；所以换体必须和触发器同一事务且在其后。

## 6. Implementation order

1. **只读核对（可单独做完，不改文件）。** 读 loader 的事务包裹方式；`pg_get_functiondef` 取加载态的 `v13_advance`、`v13_complete`、`v13_enqueue_effect`、`v13_requeue_stale`（确认定义在 mgraph 里）；`\d artifacts` 看 `content_hash` 与 `produced_by`；探针 `jsonb_matches_schema` 的真名；在设计文档、R1、ch07 搜 `harness_session_ref` / `resume_token` / `partial` 的类型句。只有「活体 ⑤ 其实在写 `turn_no`」或「advance 的 unknown 分支其实没有那句 `SET waiting`」这种与本裁定前提相反的事实才停。列缺失、函数名不同、R1 有更具体的类型，都按 §3.C 的默认分支继续。
2. **新文件的前半：扩展、探针 `DO`、策略种子、工具种子、纯函数与索引。** 此时还没有换体，库可加载到这一段之前（用临时截断验证编译）并看到 `harness_turn` 与 schema 行。工具种子不要求新 threshold。
3. **同一事务的后半（与步骤 2 原子提交）：** 回填 → 断言 → 两个延迟约束触发器 → 按加载态正文换 `v13_enqueue_effect`（加逻辑对带与 cancel 带）、`v13_complete`（加 H 带层；C4 只覆盖带 ref 的 human）、`v13_requeue_stale`（在 mgraph 正文上加 cancel 分叉与 a2 抬墙）、`v13_advance`（§3.C 的 1–7 步；终态臂改 `v13_closeout`；删除 unknown 上的 `SET waiting`）。然后 GRANT。
4. **`test_control.py`。** 先跑不依赖并发的单会话门（逻辑对、C4 决策表、收据重放、G4 负例、`{reason}` human 兼容），再跑双射的真 `COMMIT`、以及 cancel/requeue/complete/renew 的锁序。
5. **回归。** 前缀只加载 1–16，既有 gate 全绿且那 16 个文件字节不动。再全量加载到 17，跑 `test_control.py`。
6. **设计文档 §6.8/§10 与 R3b 记录文件**与步骤 3 同一变更提交。

步骤 3 内部不可拆开上线：触发器已在而 complete 仍是旧体的窗口，就是 C3 禁止的窗口。

## 7. GO / NO-GO

**GO。** H 的生产入口、盖章点、首枚/续传/重试、与普通 tool 的隔离都有了谓词；A16 的键、哈希输入、前置矩阵、重放字节、以及「⑤ 不写 `turn_no` 时预算终态是什么」都有了算法；C 表里原先只存在于散文里的 payload 都有了闭集。下一轮不应再因为「语义已裁、机器形状未裁」停工。

留在实施期、且**不必再叫 Oracle** 的事实探针（默认已写死）：

| 残留 | 默认 |
|---|---|
| `artifacts` 没有 `content_hash` 或 `produced_by` | `produced_hashes` 走 manifest 链；`artifact` wake RAISE `artifact wake requires content_hash`；不加列 |
| `jsonb_matches_schema` 真名不同 | 用探针到的名字 |
| R1 里有三注解键的字面类型 | 字面赢，否则用 §3.C 的字符串/布尔默认 |
| loader 已包事务导致双 `BEGIN` | 去掉文件内包装，保持单事务原子性 |
| mgraph requeue 的 kind 集比 twophase 多 | 保留活体 kind 集，只加 cancel 分叉 |

不在本轮打开、也不要在 stage 17 里顺手做的：`v13_open_session`、spawn、`v_goal_tree`、`v13_recover_idle`、interruptible、worktree、fold/repair 的 threshold 帽、`quota/spent`、`closeout/inbox_residual`、steer 的正文、`children_terminal` 的真求值。

### Oracle 2
- Status: Completed
- Provider: `openCode`
- Model: `xai/grok-4.7`
- Effective effort: Provider default / not specified
- Chat: `new-chat-oracle-2-993FBF`

R3b 需要对照活体 SQL 把生产侧入口、收据算法和未冻键钉死。我先核对 tools 目录、advance 入队、artifacts 与 requeue 换体落点。

### Oracle 3
- Status: Completed
- Provider: `codex`
- Model: `gpt-5.6-sol`
- Effective effort: `xhigh`
- Chat: `new-chat-oracle-3-040FC0`



# 1. Summary

R3b 对 P1 的两个 STOP 点作如下终裁：**H 取 A**，新增并种子化唯一具名目录工具 `harness_turn`，只有 `v13_advance` 在该工具的 `action='tool'` 建账路径中可以盖 `logical_turn_id` / `continuation_index`；普通工具不得携带逻辑对，driver 不获得任何 harness 布尔参数或逻辑对输入面。**A16 收据直接作为 `session/completed|failed|cancelled` 事件的顶层 payload**，冻结完整键集、预算投影、产物/子会话/未消费工作算法和可重算的 SHA-256 状态摘要；现有 economy 没有可终态化的预算行，因此 closeout 不写 `turn_no` 或新预算状态，只把既有事件/调用投影冻结进收据。完备性扫掠同时冻结 `cancel/requested`、`unknown_resolved`、material、wake、signal、steer、closeout residual 等剩余事件形状及负向执法。结论为 **GO**：R3b 后没有仍需架构裁决的 P1 机器形状；实现仍须机械地以加载 1–16 后的 `v13_advance` 和 mgraph 版 `v13_requeue_stale` 为换体底稿。

---

# 2. Current-state analysis

## 2.1 现有职责与数据流

当前控制链为：

1. `v13_parse(session_id)` 在锁外构造 snapshot/envelope。
2. `v13_advance(session_id, snapshot)`：
   - 锁 `sessions` 行；
   - 用 `v13_probe` 比对七键水位；
   - 检查现有 effect；
   - 执行预算投影；
   - 调 `v13_route`；
   - 根据 `action ∈ {sql,tool,llm,human,finish,reject}` 同事务执行 SQL 快路或建 effect。
3. 外部 worker 通过 `v13_claim` 获得冻结 `request`、`attempt_no`、`fence`。
4. `v13_complete` 以 session→effect 锁序和 fence CAS 完成 effect，追加 `effect_done`，并为成功 tool/llm 写语义事件。
5. `v13_requeue_stale` 负责 lease 到期恢复；活体最终定义位于 mgraph stage，而非所选的 `v13/twophase/v13_twophase.sql` 旧体。

`effects.request` 已经是 effect 身份和幂等性的组成部分：`v13_effect_id` 使用 request hash，且 enqueue 不允许同一 ID 覆盖 request。因此逻辑对必须在 effect ID 生成前盖入 request，不能放在 `v13_send_work` 或 worker 侧。

## 2.2 H 的现有缺口

现有 queued tool request 由 `v13_advance` 的 `WHEN 'tool'` 分支生成，形如：

- `tool`
- `params`
- `handler`
- `tools_revision`

现有代码没有：

- harness 工具目录行；
- harness 与普通 tool 的生产侧判别；
- 逻辑对的生成入口；
- “首枚”“续传”“材料消费后新 logical turn”的查询算法；
- 普通工具不得携带逻辑对的 DDL/函数带层。

R3a 已冻结消费侧判别器——“`kind='tool'` 且 request 带合法逻辑对”——但未指定哪一次 tool enqueue 可以产生这对字段。

## 2.3 A16 的现有缺口

当前 finish/reject 直接：

- 追加 `turn/end`；
- 更新 `sessions.status`；
- 返回 `terminal`。

它没有 `session/completed|failed|cancelled` 事件，也没有 closeout 收据、重放事件返回、未消费工作投影或 `state_hash`。

现有 economy 相关事实为：

- `turn_budget.max_cycles` 由 `v13_cycle_no` 查询当前 user turn 的 `turn/route` 数量；
- `v13_advance` 的预算步骤只读该投影，不写 `turn_no`；
- `sessions.turn_no` 由新 `user/message` 增加，是生命周期 turn 锚，不是可扣减余额；
- judgment 花费权威为 `judgment_calls`；
- material 花费在 R3a 后以 `turn/material_spent` 事件作为消费收据；
- 没有需要在 closeout 时“封状态”的预算行。

因此 A16 所称“预算终态同事务”只能解释为：**与 session 终态同事务冻结预算投影及已落消费收据，不做第二次扣减**。

## 2.4 unknown 与 advance 的冲突

当前 `v13_advance` 在发现 `ready|claimed|unknown` 时统一写 `sessions.status='waiting'`。R3 D5 已要求：

- 非终态 session 存在 unknown 时必须是 `blocked_unknown`；
- unknown 分支不得改写 session status；
- `v13_resolve_unknown` 关闭最后一堵墙后才清回 `ready`，有人类待答时为 `waiting`。

因此 stage 17 的 advance 换体必须删除 unknown→waiting 的旧写入，而不是新增漂移修复写者。

## 2.5 变更范围判断

这是一个**目标明确的 stage 17 增量**，不需要重构现有 schema 或新增调度平面：

- 复用 `tools` 目录作为 harness 指定源；
- 复用 `effects.request` 作为逻辑对载体；
- 复用开放的 `events.type` 作为消费和 closeout 收据；
- 通过 `CREATE OR REPLACE` 换体现有 `v13_advance`、`v13_complete` 和最终版 `v13_requeue_stale`；
- 通过索引、触发器和新 helper 补齐结构带层。

不得回改 stage 1–16 文件；否则既有前缀加载 gate 的语义会变化。

---

# 3. Design

## 3.1 R3b 的规范地位

本节应作为 `docs/reviews/v13-control-plane-oracle-r3-2026-09-26.md` 的 **§7 R3b** 追加：

- 与 R3 §0–§5、R3a §6 同级；
- 不重开 D1–D6 或 A15–A21；
- 只补充 H 的生产侧、A16 的机器收据及 P1 剩余 payload/算法；
- 若与迁移报告或设计草案的未冻结措辞冲突，以 R3b 为准；
- `result_kind` 四值、wait 三值、effect kind、route action 均不扩词。

---

## 3.2 H：harness effect 的生产侧指定

### 3.2.1 方案终裁

**选择 A：固定种子目录行 `harness_turn`。**

否决：

- **B 策略名单**：会产生“tools 行声明一种身份、policy 再声明一次 harness 身份”的双真相源，并要求把 policy 版本纳入更多水位。
- **C driver 参数**：driver 可伪造 harness 分类或逻辑对，破坏服务器唯一写者与 request identity。

`harness_turn` 是 v1 唯一 harness 工具名。扩展第二个 harness 名称不是数据操作，必须重新打开 H：不得仅通过 `INSERT tools` 或 policy 翻版扩员。

### 3.2.2 `harness_turn` 目录行

基于所给 `tools` 表，种子行的物理字段冻结为：

| 字段 | 值/约束 |
|---|---|
| `name` | `harness_turn` |
| `description` | ASCII 非空；语义必须说明“运行当前会话的一个外部 harness continuation”，不得宣称是 SQL 工具 |
| `kind` | `tool` |
| `handler` | `worker:harness_turn` |
| `param_spec` | `{}` |
| `enabled` | `true` |

### 3.2.3 `input_schema` 与 `mutating` 的语义

所给 core DDL 没有独立 `tools.input_schema` 或 `tools.mutating` 列，且 R3b 禁止新增列。因此：

- v1 的**有效 input schema**为严格空对象：
  - tool 参数必须为 JSON object；
  - 必须逐字节等价于 `{}`；
  - 不允许模型提供任何参数键；
  - 特别禁止模型通过 `params` 提供 `logical_turn_id`、`continuation_index`、`mutating`、handler 或 route 信息。
- `param_spec={}` 负责“无判断参数”的目录声明；
- `v13_advance`/harness request 校验负责 `params={}` 的 fail-closed 执法，不能把 `param_spec={}` 单独当作 JSON Schema 校验器。
- `harness_turn` 的 `mutating` 分类固定为 `true`，由服务器在冻结 request 中写入；它表示外部执行可能留下 rollback 后仍存在的副作用。
- `mutating=true` 与 PostgreSQL `provolatile='v'` 无关：
  - `v13_tools_guard` 的 VOLATILE 检查只适用于 `kind='sql'`；
  - `harness_turn` 是 `kind='tool'`，handler 是 worker key，不解析成 `pg_proc`，也不进入 A17 的具名 SQL VOLATILE 例外。
- P1 不实现 P3 的 interrupt worker 第四务，但 mutating 标记从第一版即冻结；将来中断该 effect 必须走 unknown，不得改其 request。

若加载 1–16 后已存在额外的工具 schema 元数据载体，种子必须把同一个严格空对象契约写入该既有载体；不得因此添加新列或改变上述 request 约束。

### 3.2.4 Harness request 的闭集

`harness_turn` effect 的冻结 request 顶层键恰为：

| 键 | 类型/值 |
|---|---|
| `tool` | 字符串，必须为 `harness_turn` |
| `params` | 空 object `{}` |
| `handler` | 字符串，来自冻结目录，v1 必须为 `worker:harness_turn` |
| `tools_revision` | 非负 JSON integer，来自 envelope 冻结值 |
| `mutating` | JSON boolean，必须为 `true` |
| `logical_turn_id` | canonical 小写 UUID 字符串 |
| `continuation_index` | JSON integer，范围 `0..2147483647` |

未知顶层键拒绝。逻辑对仍按 R3a 进入整个 request 的 hash，不能放入 result、params 或独立表。

普通 tool request 保持现有形状，不增加 `mutating` 或逻辑对。

### 3.2.5 唯一盖章点

逻辑对只在 `v13_advance` 的变更相内盖章，具体位置为：

1. 已持 `sessions ... FOR UPDATE`；
2. 步 0 七键水位已通过；
3. 所有 unknown、cancel、wake、material 前置已处理；
4. `v13_route` 已返回 `action='tool' AND tool='harness_turn'`；
5. 在调用 `v13_enqueue_effect` 和计算 `v13_effect_id` **之前**；
6. 将完整 request 一次性构造并冻结。

明确禁止：

- 在 `v13_route` 内生成 UUID；该函数保持 STABLE/read-only；
- 在 `v13_send_work` 中添加字段；发送时 effect ID 和 request hash 已确定；
- 在 worker/driver 侧补字段；
- complete 时反向推断逻辑对；
- enqueue 后 UPDATE request。

### 3.2.6 “最近 harness effect”的确定性定义

当前 user turn 锚为 `v13_last_user_seq(p_sid)`。

候选 effect 必须同时满足：

- `session_id=p_sid`；
- `origin_user_seq` 等于当前 user 锚；
- `kind='tool'`；
- `tool_name='harness_turn'`；
- request 中逻辑对合法；
- request 的 `tool='harness_turn'`。

“最近”不用 `created_at`，而按该 effect 的 `effect_done` 事件 `seq DESC` 取第一条；若 effect 没有 `effect_done`，账本不完整，RAISE，不按 recency 猜测。

### 3.2.7 首枚、新 logical turn 与续传算法

在准备新 harness effect 时按以下优先级执行：

1. **本 user turn 没有任何 harness effect 行**  
   生成新 UUID，`continuation_index=0`。这才是字面“首枚”。

2. **最近 harness effect 仍是 ready/claimed/unknown**  
   不得建新 effect；分别走 waiting 或 unknown 墙路径。

3. **最近 harness effect 是 failed/cancelled**  
   其结果未形成可续传控制状态；新逻辑动作使用新 UUID、index 0。常规运输重试仍发生在同一 effect 的 claim/attempt 内，不由此分支制造。

4. **最近 succeeded 结果为 `progress` 且同批没有 repair/replan signal**  
   它是 material 候选。只有其 `turn/material_spent` 收据已在本事务存在后，下一 harness 才使用新 UUID、index 0。

5. **最近 succeeded 结果为 `progress` 且同批有 repair/replan signal**  
   沿用前驱 `logical_turn_id`，index 加 1。加法溢出即 RAISE，禁止回零。

6. **最近 succeeded 结果为 `wait+approval`**  
   只有精确 interaction 链对应的 human 已成功并存在 `human/responded` 后才续传；沿用 ID，index 加 1。未回答返回 `waiting`，零新 harness。

7. **最近 succeeded 结果为 `wait+evidence|quota`**  
   只有同 source effect 的 `wake/satisfied` 已落后才续传；沿用 ID，index 加 1。未满足时返回 `waiting`。

8. **已回答的 cap human**  
   `interaction_kind ∈ {material_cap,repair_cap,replan_cap}` 时，下一 harness 为新 UUID、index 0。P1 不产生这些 cap human，但读侧规则先冻结。

9. **最近 succeeded 结果为 `finish|reject`**  
   不允许再 enqueue harness；应进入 closeout。若 route 仍要求 `harness_turn`，RAISE 账本/控制流错误。

所有查询限定当前 `origin_user_seq`。新 `user/message` 永远开新 UUID/index 0，不继承上一 user turn 的逻辑对。

### 3.2.8 普通工具隔离

增加 effect request 带层，约束如下：

- 任意顶层出现 `logical_turn_id` 或 `continuation_index` 时，两键必须成对；
- 带逻辑对的行必须同时满足：
  - `kind='tool'`；
  - `tool_name='harness_turn'`；
  - request 的 `tool='harness_turn'`；
  - 完整 harness request 闭集；
- `harness_turn` tool effect 反向必须携带合法逻辑对；
- `judge|llm|human|context_refresh|sql 快路 tool` 不得携带逻辑对；
- `session_stats`、`send_summary_email` 等普通工具不得携带逻辑对；
- effect 的 `request` 与 `request_hash` 创建后不可修改。增加 UPDATE guard；steer 只能追加 event，不能改在途 request。

R3a 的消费侧判别仍是“合法逻辑对 + kind=tool”；H 保证该判别在生产侧只可能来自 `harness_turn`。

### 3.2.9 H gates

新增或扩展 `G-ctx10-logical-turn`：

1. 首枚 `harness_turn` 得 canonical UUID/index 0。
2. 同 request 的 claim/运输重试保持同 effect ID 和逻辑对。
3. 新 user turn 不继承旧 ID。
4. progress+无 signal 在 material 收据后使用新 ID/index 0。
5. progress+signal 沿用 ID/index+1。
6. approval human 回答后沿用 ID/index+1。
7. evidence/quota wake 后沿用 ID/index+1。
8. finish/reject 后尝试再 enqueue harness 必须 RAISE。
9. 普通 tool 携任一逻辑键拒绝。
10. harness 缺任一逻辑键、非 canonical UUID、负 index、溢出 index、非空 params、`mutating<>true` 均拒绝。
11. llm/human/judge/context_refresh 携逻辑对拒绝。
12. driver 提交的所谓 harness 标志或逻辑对没有 API 入口。
13. `v13_send_work` 前后 request/request_hash 完全不变。
14. tools row disable 后 route 必须走既有 `tool_unavailable`，不能仍盖逻辑对。
15. tools revision 变化使旧 snapshot `stale`。

---

## 3.3 A16：closeout 收据机器形状

### 3.3.1 新 callable interface

新增内部控制函数：

```text
v13_closeout(
  p_sid uuid,
  p_terminal_status text,
  p_reason jsonb
) -> jsonb
```

- 同步、事务内执行；
- `p_terminal_status ∈ {completed,failed,cancelled}`；
- 只授 `v13_route`；
- 它不是新推进函数：只封账，不 parse、不 route、不 enqueue、不调用外部 IO；
- `v13_advance` 的 finish/reject/cancel 终结路径统一调用它，禁止保留平行的直接 status UPDATE 路径。

返回 JSON 是已有或新建 terminal event 的稳定投影：

```text
{event_id, seq, type, payload}
```

首次 closeout 与后续 replay 返回逐 JSON 字节相同的对象。

### 3.3.2 收据住所

收据直接是下列事件的**顶层 payload**，不再嵌套 `receipt`：

- `session/completed`
- `session/failed`
- `session/cancelled`

事件 type 已表达 terminal outcome，payload 不重复 `outcome` 或 `status`。

### 3.3.3 Terminal payload 闭集

三类 terminal event 的 payload 顶层键恰为：

| 键 | 类型 |
|---|---|
| `schema_version` | JSON integer，固定 `1` |
| `origin_user_seq` | JSON integer；completed/failed 必须 `>=0`，cancelled 允许 `-1` |
| `spent` | 下述闭集 object |
| `produced_hashes` | 排序、去重后的 SHA-256 字符串数组 |
| `children` | child summary 数组；P1 新 closeout 必为 `[]` |
| `unconsumed` | 下述闭集 object |
| `state_hash` | 64 位小写十六进制 SHA-256 |
| `reason` | 下述闭集 object |

未知键拒绝；缺键拒绝；空集合一律编码为 `[]`，不用 JSON null。

### 3.3.4 `reason` 形状

`reason` 恰有：

| 键 | 类型/规则 |
|---|---|
| `code` | 1..128 字符的小写 token，匹配 `[a-z0-9][a-z0-9_./:-]*` |
| `source_effect_id` | canonical UUID 字符串或 JSON null |
| `request_event_id` | canonical UUID 字符串或 JSON null |

按 terminal type 约束：

- `session/completed`
  - `request_event_id=null`；
  - `source_effect_id` 可为触发 finish 的 harness/llm effect，也可为 null。
- `session/failed`
  - `request_event_id=null`；
  - `code` 必须明确失败原因，如 `rejected`、`budget_exhausted`、`attempts_exhausted`；
  - `source_effect_id` 可空。
- `session/cancelled`
  - `code='cancel_requested'`；
  - `source_effect_id=null`；
  - `request_event_id` 必须指向当前未消费的 `cancel/requested`。

若 source/request event 不属于该 session，RAISE。

### 3.3.5 `spent` 的权威定义

`spent` 恰有：

| 键 | 算法 |
|---|---|
| `session_turn_no` | closeout 锁下读取 `sessions.turn_no`；它只是生命周期锚，不称作扣费余额 |
| `route_cycles_current_turn` | `v13_cycle_no(p_sid)` |
| `material_units_current_turn` | `turn/material_spent` JOIN source effect，限定 source effect 的 `origin_user_seq` 为当前 user 锚后的数量 |
| `judgment_calls_session` | `judgment_calls WHERE session_id=p_sid` 的累计数量，不使用随墙钟变化的 day count |
| `turn_budget_policy_version` | `v13_policies` 中 active `turn_budget` 的 version |
| `judge_spend_policy_version` | active `judge_spend_gate` 的 version |

所有计数为非负 JSON integer；两个版本必须为正整数。

**预算终态动作：**

- closeout 不更新 `turn_no`；
- 不追加第二条 material receipt；
- 不更新 policy 或新增余额行；
- 不重复扣 cycle；
- 仅把以上投影与 terminal event、`sessions.status` 原子提交。

这与当前 economy 的纯查询模型兼容，也落实 A16 的“不二次扣”。

### 3.3.6 `produced_hashes`

来源为：

- `artifacts.produced_by = effects.effect_id`；
- producer effect 属于该 session；
- producer effect 当前 `status='succeeded'`；
- `artifacts.content_hash` 必须为 64 位小写 SHA-256。

算法：

1. 取整个 session 的上述 hash；
2. `DISTINCT`；
3. 按 hash 字典升序；
4. 聚合成数组；
5. 无行时为 `[]`；
6. 任一非法 hash 使 closeout RAISE，不静默忽略。

不扫描事件 payload 猜产物，也不把 transcript 正文复制进收据。

### 3.3.7 `children`

P1：

- 任何新 closeout 若发现直接 child session，RAISE 稳定错误 `children require stage 18`；
- 因而 P1 收据固定为 `[]`。

P2 启用后，每个直接 child entry 恰为：

```text
{
  session_id,
  status,
  terminal_event_id,
  state_hash
}
```

约束：

- `status ∈ {completed,failed,cancelled}`；
- terminal event 必须和 child 当前 terminal episode 对应；
- `state_hash` 抄 child terminal 收据；
- 按 `session_id` 升序；
- direct child state hash 递归承诺整个子树；
- 任一 child 非终态、缺 terminal receipt 或 terminal receipt 多行时，父 closeout 失败。

### 3.3.8 `unconsumed`

`unconsumed` 恰有：

| 键 | 类型 |
|---|---|
| `material_effect_ids` | UUID 字符串数组 |
| `signals` | `{event_id,type}` object 数组 |
| `waits` | `{effect_id,wait_reason}` object 数组 |
| `unknown_effect_ids` | UUID 字符串数组 |

排序：

- UUID 数组按 UUID 文本升序；
- `signals` 按 `event_id`；
- `waits` 按 `effect_id`；
- 均去重。

谓词：

1. **material**
   - effect 满足 R3a material 候选谓词；
   - 不存在同 `source_effect_id` 的 `turn/material_spent`；
   - 加入 `material_effect_ids`。

2. **repair/replan signal**
   - `repair/required` 或 `replan/required` 事件；
   - 不存在引用该 signal `event_id` 的对应 `repair/consumed` 或 `replan/consumed`；
   - 加入 `signals`。

3. **wait**
   - succeeded harness result 为 `wait+evidence|quota`，但不存在同 source effect 的 `wake/satisfied`；
   - 或 succeeded harness result 为 `wait+approval`，但不存在通过 interaction 链匹配的成功 `human/responded`；
   - 加入 `waits`。

4. **unknown**
   - session 下所有 `effects.status='unknown'`；
   - 正常新 closeout 的前置使数组必为空；
   - 该键保留用于审计和 R3 C3 所允许的历史 terminal+unknown 表示。

结果约束：

- `completed`：四个集合必须全部为空，否则 RAISE；
- `failed`：可携 residual，但必须写 `closeout/inbox_residual`；
- `cancelled`：可携 residual，但必须写 `closeout/inbox_residual`；
- evidence/quota wait 未满足时不能 closeout completed；只有显式 failed/cancelled 路径可终止并记录它。

### 3.3.9 Signal 消费标记

为了使 “unconsumed repair/replan” 可判定，P1 同时冻结：

- `repair/consumed`
- `replan/consumed`

payload 恰为：

```text
{
  schema_version: 1,
  signal_event_id: <uuid>,
  consumer_effect_id: <uuid>
}
```

规则：

- signal 与 consumer effect 必须同 session、同 `origin_user_seq`；
- `consumer_effect_id` 必须是 advance 为处理该 signal 建立或 SQL 快路落成的 effect；
- event 的 `source_effect_id` 设为 consumer effect；
- 每个 signal event 至多一个 consumed event，由部分唯一索引执法；
- advance 在创建 consumer effect 的同一事务追加；
- consumer 后续 worker 失败不“取消消费”：其重试仍由 effect ledger 承担。

### 3.3.10 `state_hash`

不用 `jsonb_pretty`、timestamp 或数据库行的未排序文本。

先构造一个**不持久化的 canonical JSONB state document**，顶层键恰为：

- `schema_version`
- `session`
- `probe`
- `events`
- `effects`
- `decisions`
- `spent`
- `produced_hashes`
- `children`
- `unconsumed`
- `reason`

各部分如下。

#### `session`

包含：

- `session_id`
- `status_before`
- `target_status`
- `turn_no`
- `origin_user_seq`
- `parent_session_id`
- `parent_cutoff_seq`
- `spawn_kind`（若活体已有该列）
- `route_policy_name`
- `route_policy_version`
- `context_active_artifact`
- `context_active_revision`

可空字段显式为 JSON null。

#### `probe`

在 `turn/end` 和可选 residual 已追加、terminal event 尚未追加时调用 `v13_probe`，完整包含七键：

- `session_version`
- `max_event_seq`
- `goal_hash`
- `route_policy_name`
- `route_policy_version`
- `tools_revision`
- `candidate_generation_revision`

这一定义同时冻结 terminal event 之前的 event 尾 seq。

#### `events`

取当前 session、`seq <= probe.max_event_seq` 的所有事件，按 seq 升序。每项恰为：

- `seq`
- `event_id`
- `type`
- `turn_no`
- `payload_hash`
- `source_effect_id`

排除 `at`；payload 内容由已存 `payload_hash` 承诺。

#### `effects`

按 `effect_id` 升序，每项恰为：

- `effect_id`
- `kind`
- `tool_name`
- `request_hash`
- `idempotency_key`
- `origin_user_seq`
- `attempt_no`
- `fence`
- `status`
- `op_seq`
- `mutation_scope`
- `result_hash`
- `error_hash`

`result_hash`/`error_hash` 分别为对应 jsonb 的 canonical `jsonb::text` SHA-256；SQL NULL 使用固定 JSON `null` 文本参与哈希。排除 `created_at`、`lease_owner`、`lease_until`。

#### `decisions`

按 `decision_id` 升序，每项恰为：

- `decision_id`
- `signal`
- `kind`
- `request_hash`
- `status`
- `context_hash`
- `answer_hash`

`context_hash` 和 `answer_hash` 使用同样的 canonical jsonb SHA-256 规则；NULL answer 使用固定 null 表示。

#### 哈希算法

1. 所有 object 用 JSONB 构造；
2. 所有数组显式排序；
3. 空数组为 `[]`，可空标量为 JSON null；
4. 使用 PostgreSQL `jsonb::text` 作为 canonical serialization；
5. 对 UTF-8 字节执行 SHA-256；
6. `encode(...,'hex')` 得 64 位小写 hex。

terminal event 本身不进入自己的 `state_hash`，但其前面的 `closeout/inbox_residual` 和 `turn/end` 会进入。

### 3.3.11 Closeout 顺序与前置

持 session 行锁后：

1. **terminal replay 短路**
   - 若 session 已终态，按当前 terminal episode 找唯一对应 `session/*`；
   - 不重算计数、收据、hash，也不检查当前 unknown；
   - 返回原 event 投影；
   - 0 行或多行是账本损坏，RAISE；
   - 即使本次调用参数不同，也返回已提交 terminal truth，不生成第二 commit。

2. **计数前置**
   - active：`status IN ('ready','claimed')` 数量必须为 0；
   - unknown：`status='unknown'` 数量必须为 0；
   - pending human：`kind='human' AND status IN ('ready','claimed')` 数量必须为 0；
   - `sessions.status <> 'blocked_unknown'`；
   - pending human 谓词与 D5 resolve 清回 `waiting` 的例外完全相同。

3. **sticky cancel**
   - 存在当前未消费 `cancel/requested` 时，只允许 target `cancelled`；
   - target cancelled 必须找到唯一该事件。

4. **children**
   - P1 发现 child 即拒。

5. **unconsumed**
   - 计算完整结构；
   - completed 要求全空；
   - failed/cancelled 可保留。

6. **residual event**
   - failed/cancelled 且 unconsumed 非空时，先追加唯一 `closeout/inbox_residual`。

7. **turn/end**
   - 由 closeout 统一追加，不再由各 advance terminal 分支自行追加。

8. **state hash**
   - 在 residual/turn-end 后、terminal event 前生成。

9. **terminal event + status**
   - 追加 `session/*`；
   - 更新 `sessions.status`；
   - 同事务返回 event 投影。

任一步失败，所有新事件和 status UPDATE 一起回滚。

### 3.3.12 `turn/end` 与 residual payload

新的 `turn/end` payload 恰为：

```text
{
  schema_version: 1,
  delivered: <boolean>,
  reason: <reason.code>,
  origin_user_seq: <bigint>
}
```

- completed：`delivered=true`
- failed/cancelled：`delivered=false`

`closeout/inbox_residual` payload 恰为：

```text
{
  schema_version: 1,
  origin_user_seq: <bigint>,
  terminal_status: "failed" | "cancelled",
  unconsumed: <与 terminal receipt 完全相同的 object>
}
```

每个 session/current origin 至多一个 `turn/end`、一个 terminal event、一个 residual event，由表达式/部分唯一索引执法。

### 3.3.13 A16 gates

至少覆盖：

- active/unknown/pending human 任一非零时新 closeout 失败；
- `blocked_unknown` 保险带；
- evidence/quota wake 未满足时 completed 失败；
- 同状态第二次 closeout 返回完全相同 event JSON；
- replay 不受终态残留 unknown 影响；
- closeout 不改 `turn_no`，不新增 material receipt，不新增 judgment call；
- `spent` 与权威查询相等；
- produced hashes 排序去重；
- P1 child 存在时拒绝；
- state hash 对任一纳入字段变化都会变化，对 timestamps/lease metadata 变化不敏感；
- terminal event 写入失败时 status 不变；
- terminal status UPDATE 失败时事件回滚；
- failed/cancelled residual 事件与 terminal payload 的 `unconsumed` JSON 完全相等。

---

## 3.4 C：P1 完备性扫掠

### 3.4.1 R3 §2 与 R3a §6.5 逐项状态

| 项 | 状态 | R3b 裁定 |
|---|---|---|
| unknown 部分索引 | 已冻（R3） | `effects(session_id) WHERE status='unknown'`；无新 payload |
| `v13_raise_unknown_wall` | 已冻（R3） | 仅 ready/waiting→blocked_unknown；终态不改；只抬不清 |
| 最终版 `v13_requeue_stale` | 已冻但有实现基线风险 | 必须从 mgraph 最终定义换体；不能从 twophase 旧体复制 |
| `v13_complete` unknown 出口 | 已冻（R3） | accepted unknown 后抬墙；stale/replay/llm 降级不抬 |
| human answer 校验 | 已冻（R3 C4） | 严格 one-of、未知键拒绝、协议错误 RAISE |
| `human/responded` | 已冻（R3 C5） | origin 必须抄 `effects.origin_user_seq`，不调用 `v13_last_user_seq` 重算 |
| `v13_resolve_unknown` | 部分未冻 → 本节冻结 | `unknown_resolved` payload 与 evidence hash 如下 |
| A16 closeout | 未冻 → §3.3 冻结 | 无残留 |
| `v13_cancel` | payload 未冻 → 本节冻结 | 如下 |
| `v13_advance` A15 | H 与 closeout 前未完备 → 已冻结 | H、wake、material、cancel、terminal 全有单一路径 |
| unknown 双射回填/触发器 | 已冻（R3 C2/C3） | 保持，不加 advance 漂移修复 |
| ACL | 已冻 | 新 callable REVOKE PUBLIC，仅 GRANT v13_route |
| harness schema policy | draft 标识未冻 → 本节冻结 | policy row 与 draft-07 如下 |
| wake payload | 值域未完全冻 → 本节冻结 | `wake_kind` 为四值 |
| material payload | 版本标识未冻 → 本节冻结 | 仅 `{schema_version:1}` |
| signal payload | 版本标识未冻 → 本节冻结 | 仅 `{schema_version:1}` |
| steer gate | 断言方法未冻 → 本节冻结 | effect request immutability + before/after 比对 |
| advance 返回词 | 已冻并再次确认 | 仅 `progressed|waiting|terminal|stale`，不新增 `wake_pending` 等词 |

R3b 后没有仍未机器冻结的 P1 payload 或判别器。

---

### 3.4.2 事件 payload 注册表

#### `cancel/requested`

payload 恰为：

```text
{
  schema_version: 1,
  origin_user_seq: <bigint>,
  reason: <1..128 小写 token>
}
```

- 默认 reason 为 `requested`；
- `source_effect_id=null`；
- `v13_cancel` 返回词只允许 `accepted|replay`；
- session 已终态或当前 origin 已有未消费 cancel 时返回 `replay`，不二插；
- “未消费”指该 event 尚未被 `session/cancelled.reason.request_event_id` 引用。

#### `unknown_resolved`

payload 恰为：

```text
{
  schema_version: 1,
  effect_id: <uuid>,
  resolution: "confirmed" | "rolled_back" | "not_happened",
  evidence_hash: <sha256>,
  origin_user_seq: <bigint>
}
```

- `source_effect_id=p_effect`；
- origin 抄 effect 行；
- `evidence_hash = sha256(p_evidence::jsonb::text UTF-8)`，小写 hex；
- 不复制 evidence 正文。

`p_evidence` 本身为闭集：

- `confirmed`：
  - `{schema_version:1, observation:'committed', payload_hash:<sha256>}`
  - payload hash 必须等于已落 `effects.result` 的 canonical hash；
  - result 不存在时拒绝。
- `not_happened`：
  - `{schema_version:1, observation:'absent'}`
- `rolled_back`：
  - `{schema_version:1, observation:'rolled_back', compensation_ref:<非空字符串>}`

`observation='unknown'`、未知键、错配 resolution 均 RAISE。接受后：

- confirmed → `succeeded`
- 其余 → `failed`
- 返回 `accepted`
- status 已不为 unknown 的调用拒绝，不新写 event。

#### `turn/material_spent`

payload 恰为：

```text
{schema_version: 1}
```

- `source_effect_id` 是被消费的 material harness effect；
- 不重复 effect ID、logical turn ID 或 index；
- guard 通过 source effect request JOIN 获取逻辑对；
- 每个 source effect 至多一条；
- 同 session+logical turn 不得有不同 source 的第二条。

#### `wake/satisfied`

R3a 的“payload 只含两键”保持，恰为：

```text
{
  effect_id: <uuid>,
  wake_kind: "event" | "not_before" | "artifact" | "children_terminal"
}
```

- 不添加 `schema_version`；
- `effect_id` 必须等于 `source_effect_id`；
- P1 不会接受 children_terminal harness result，因此 P1 不会生成该 kind，但词表现在即冻结；
- 每个 source effect 至多一条。

#### `repair/required` 与 `replan/required`

两者 payload 均恰为：

```text
{schema_version: 1}
```

- `source_effect_id` 为产生 signal 的 harness effect；
- 不复制 logical turn；
- 同 source+type 至多一条；
- 写入顺序固定：repair 在前，replan 在后。

#### `repair/consumed` 与 `replan/consumed`

采用 §3.3.9 的三键 payload；这是 R3b 为“unconsumed”投影补的唯一新消费收据。

#### `human/responded`

保持 R3 C5 的闭集：

```text
{
  schema_version: 1,
  interaction_ref: <string>,
  skip: <boolean>,
  response: <scalar 或 null>,
  answers: <object 或 null>,
  origin_user_seq: <bigint>
}
```

- origin 抄 `effects.origin_user_seq`；
- skip 通道时 `skip=true`，其余通道固定 false；
- 未用的 response/answers 显式 JSON null；
- `source_effect_id` 指 human effect。

#### `steer/injected`

P1 冻结最小 payload：

```text
{
  schema_version: 1,
  content: <btrim 后非空字符串>
}
```

payload 自身的 `events.payload_hash` 已承诺正文，不再重复 content hash。它只改变 event 水位，不允许 UPDATE claimed effect。

#### `turn/end`、`closeout/inbox_residual`、`session/*`

按 §3.3 冻结。

---

### 3.4.3 Harness schema policy row

新增 immutable policy version：

| 列 | 值 |
|---|---|
| `name` | `harness_result_schema` |
| `version` | `1` |
| `active` | `true` |
| `value` | 完整 JSON Schema draft-07 文档 |

`value` 必须：

- 顶层包含 `"$schema": "http://json-schema.org/draft-07/schema#"`；
- `type=object`；
- `additionalProperties=false`；
- required/optional 键和 R3a §6.1 完全一致；
- 用 `oneOf` / `if-then` 表达 result/wait/wake/signals 交叉矩阵；
- `not_before.at` 同时使用 `format:date-time` 和必须带 `Z|±HH:MM` 的 pattern；
- lower sha、canonical UUID、数组唯一性均在 schema 表达；
- SQL 只保留 schema 无法表达的 ledger JOIN、stage 18 child 拒收和来源校验。

不在 harness result 中新增 `schema_version`；schema 版本由 policy row `(name,version)` 表达。

### 3.4.4 `v13_cancel` 与 requeue 的交互

单会话 cancel：

- ready effect → `cancelled`；
- `fence=fence+1`；
- `attempt_no` 不变；
- 清 lease owner/until；
- `error=NULL`；
- claimed/unknown 不动；
- session status 不改。

因此：

- cancelled 行不符合 `v13_requeue_stale` 的 `status='claimed'` 谓词；
- 不计入 reclaimed、walled、lease_exhausted 或 wake 计数；
- 增 fence 仅使任何错误持有的旧 token 失效；
- sticky cancel event 保留，待 claimed 结算或 unknown resolve 后由 advance 走 cancelled closeout；
- cancel 不得把 unknown 改成 cancelled，也不得清 `blocked_unknown`。

### 3.4.5 Steer 的执法与 gate

增加 effect request immutability guard：

- UPDATE 时 `request` 或 `request_hash` 变化立即 RAISE；
- 正常状态、result、error、lease、attempt、fence 更新不受影响。

`G-steer-request-frozen`：

1. claim 一个 harness effect；
2. 保存 effect ID、request、request_hash、attempt、fence；
3. 追加合法 `steer/injected`；
4. 断言在途 effect 的上述 request 身份字段完全不变；
5. 原 token 仍仅受正常 lease/fence 规则影响；
6. 旧 parse snapshot 因 event 水位变化而 stale；
7. 后续 steer 只可体现在新的 successor request/effect ID，不得覆盖旧 effect。

### 3.4.6 G4：“只有 resolve_unknown 能离开 unknown”

负例集必须逐一覆盖：

- `v13_complete` 对 unknown 返回 replay，零变化；
- `v13_enqueue_effect` 命中 unknown RAISE；
- `v13_requeue_stale` 忽略已有 unknown；
- `v13_cancel` 不改 unknown；
- `v13_advance` 不改 unknown 或 session 墙；
- closeout 非 replay 路径因 unknown count 拒绝；
- human response 不能结算 unknown human；
- user/message 不清 `blocked_unknown`；
- ready/failed/cancelled 重挂路径不能命中 unknown；
- raw status UPDATE 使 unknown 离墙但没有匹配 `unknown_resolved` 时，提交必须被延迟约束/状态 guard 拒绝。

正例只允许：

- `v13_resolve_unknown` 验证 evidence；
- 同事务写 `unknown_resolved`；
- 按 resolution 改 succeeded/failed；
- 若是最后一堵墙，按 R3 C1 清 session overlay。

### 3.4.7 Pending human 与 D5 的统一谓词

全系统唯一 pending-human 谓词为：

```text
kind='human' AND status IN ('ready','claimed')
```

消费点：

- D5 resolve 最后一堵墙后：存在则 session→waiting，否则→ready；
- A16 closeout 前置：数量必须为 0；
- approval enqueue：已有 human `ready|claimed|unknown` 时拒绝创建第二枚；这里额外包含 unknown 是“同 interaction 不得重问”的建账约束，不改变 pending-human 定义；
- active count 已包含 ready/claimed，但 closeout 仍单独计算 pending human，作为语义审计带。

### 3.4.8 Advance 返回词闭集

stage 17 后 `v13_advance` 仍只返回：

- `progressed`
- `waiting`
- `terminal`
- `stale`

明确禁止新增：

- `wake_pending`
- `blocked_unknown`
- `cancelled`
- `replay`
- 任意 harness 专用返回词

具体映射：

- unknown 墙：`waiting`，且不写 status；
- wake 未满足：`waiting`，session 置 waiting；
- approval 未答：`waiting`；
- 新 effect 建账：`waiting`；
- closeout 成功或 terminal replay：`terminal`；
- signal/material 消费后可继续本轮：`progressed` 或继续执行既有 route；
- 水位失配：`stale`。

---

## 3.5 Concurrency、生命周期与错误模型

### 锁序

所有新增路径遵守：

1. session 行锁；
2. effect 行锁；
3. event/effect/artifact 查询或写入。

`v13_requeue_stale` 必须按 R3：

1. 无锁收集候选 session IDs；
2. session_id 升序锁 session，不用 `SKIP LOCKED`；
3. 等锁后重检 lease/status/fence；
4. 更新 effect；
5. 对实际 a2 session 调 `v13_raise_unknown_wall`。

`v13_closeout` 持 session 锁后，active=0 保证不会和 accepted complete 同时封账；complete 必须先取得同一 session 锁。

### 协议错误

下列均 RAISE 并回滚，不把 effect 降级成 failed，也不烧结算 token：

- harness request/逻辑对形状错误；
- harness result schema 错误；
- human response one-of 错误；
- interaction ref 不匹配；
- unknown resolution evidence 错误；
- state receipt 输入出现非法 hash/重复 terminal event；
- material 第二 source 消费同一 logical turn；
- finish/reject 后仍请求 harness continuation。

`stale`、`replay` 仍只用于已有 CAS/终态协议，不吞 shape 错误；但 complete 必须先执行 stale/replay 守卫，再校验 result，保持 R3a 已裁顺序。

### 取消与中断

P1 的 SQL 层 cancel 只记 sticky intent 和收 ready；不杀 worker。claimed harness 完成后由下一次 advance 消费 cancel。若 claimed 变 unknown，cancel 保留但不能越墙，必须先 resolve unknown。

---

# 4. File-by-file impact

## `docs/reviews/v13-control-plane-oracle-r3-2026-09-26.md`

- 追加 **§7 R3b**：
  - H 取 A；
  - `harness_turn` 行/request/盖章/续传算法；
  - A16 terminal receipt；
  - payload 注册表；
  - 完备性结论与 GO。
- 不改 §0–§6 的历史文字；必要处仅加 “由 §7 补齐” 指针。

**依赖：** 本计划全部设计裁决。

## `docs/designs/v13-context-on-pg.md`

- §6.8：
  - 将 H 生产侧、逻辑对盖章和普通工具隔离并入 A15；
  - 加入 A16 receipt/state hash；
  - 明确 economy 为投影、closeout 不写 `turn_no`。
- §10：
  - 扩 `G-ctx10-logical-turn`；
  - 扩 `G-ctx10-spend`；
  - 增 closeout state hash/replay/residual gates；
  - 增 steer request immutability、G4 负例集。
- 不扩 route action、effect kind 或 wait 词表。

**依赖：** Oracle 记录先冻结术语。

## `v13/control/v13_control.sql`（新增）

单事务 stage 17，包含：

- `pg_jsonschema` 前置与 draft-07 schema policy seed；
- `harness_turn` tools seed；
- harness request/逻辑对校验 helper；
- effect request immutability guard；
- unknown 部分索引、wall helper、双射触发器和回填；
- 从 mgraph 最终态复制并换体 `v13_requeue_stale`；
- 换体 `v13_complete`；
- `v13_resolve_unknown`；
- `v13_cancel`；
- `v13_closeout`；
- wake/material/signal/terminal 相关 guard 和部分唯一索引；
- 从加载 1–16 后最终态复制并换体 `v13_advance`；
- 所有 REVOKE/GRANT；
- 安装期断言。

文件必须显式 `BEGIN/COMMIT`；回填、触发器和函数换体原子落地。

**依赖：** 必须先确认 mgraph 版 requeue 和最终 `v13_advance` 的活体定义。

## `v13/control/test_control.py`（新增）

覆盖 R3 §2、R3a §6.5 及本计划的所有 gates，尤其：

- H seed/request/逻辑 turn；
- ordinary-tool isolation；
- wake 四变体；
- material exactly-once；
- signal consumed；
- human answer矩阵；
- unknown/session 双射；
- cancel sticky；
- closeout receipt/hash/replay/residual；
- steer immutability；
- complete/requeue/renew 并发；
- ACL 下 recall 可见 human response 但不可读 effects。

## `v13/load.py`

- 在现有 16 stage 后追加 stage 17；
- stage 17 必须以一个事务加载；
- 失败时整个 stage 回滚；
- 保持 stage 1–16 顺序和文件字节不变。

## 明确不修改

- `v13/schema/v13_core.sql`
- `v13/loop/advance.sql`
- `v13/twophase/v13_twophase.sql`
- `v13/economy/v13_economy.sql`

stage 17 用后置 `CREATE OR REPLACE` 和新对象覆盖行为，保留旧前缀测试。

---

# 5. Risks and migration

## 5.1 Harness 工具改变候选集

插入 `harness_turn` 会 bump tools revision，并可能进入 `v13_needed_judgments` 的 tool 候选。其影响是设计内的：

- 在途 snapshot 因 tools revision stale；
- 新 parse 才能选择该工具；
- description 必须足够精确，避免普通 side-effect 请求误选 harness。

不得通过 policy 名单再做第二层筛选。

## 5.2 Stage 17 存量断言

除 R3 C3 已裁 unknown 回填外，安装还应断言：

- 不存在带单边逻辑对的 effect；
- 不存在非 `harness_turn` tool 带逻辑对；
- 不存在名为 `harness_turn` 的冲突 tools 行；
- 不存在旧 `turn/material_spent`；
- 不存在重复 succeeded approval interaction ID；
- 不存在 signal/result 集不一致；
- 不存在一个 current terminal episode 多条 `session/*`。

这些异常不自动修复。

## 5.3 历史 terminal session

stage 1–16 可能已有 terminal session，却没有 A16 `session/*` receipt。不能把它冒充为新原子 closeout。

支持策略：

- stage 17 安装只对全新 closeout 强制 A16；
- 若部署保留 stage≤16 的 terminal 数据，应在安装事务中以明确 `reason.code='migration_backfill'` 生成一次迁移收据，并保留 terminal+unknown 于 `unconsumed.unknown_effect_ids`；
- 迁移收据不是“原终态同事务”的历史证明，运维文档必须标明它只证明 stage 17 安装时快照；
- 新运行期绝不允许使用该 reason code；
- 若现有父子终态无法按 child receipt 自底向上生成，安装应列出 session IDs 后中止，不得写不完整 children。

预发布/测试数据库可选择重建，但这是部署操作，不是另一种运行时语义。

## 5.4 `state_hash` 成本

A16 state hash 扫描 session 的 events/effects/decisions，时间复杂度为：

- `O(E + F + D + A)`；
- 临时空间取决于 JSON 聚合大小。

这是零新表/零新列约束下可审计 state commitment 的代价。closeout 频率低，先采用；gate 必须测大 session 的持锁时间。若超出既有毫秒级控制面目标，只能后续引入经裁决的增量链 hash，不得本轮偷偷删字段或仅 hash 尾 seq。

## 5.5 Schema extension

已确认 pg_jsonschema 0.3.4：

- oneOf、if/then、pattern 可用；
- `format:date-time` 必须通过 `$schema` 固定 draft-07。

部署仍需扩展安装权限。安装失败时 stage 17 整体 NO-GO，禁止改用临时 PL/pgSQL 子集校验 harness result。

## 5.6 最终函数体复制风险

`v13_requeue_stale` 的最终活体在 mgraph。若从 `v13/twophase/v13_twophase.sql` 复制，将丢失 mgraph-consolidate 行为。实施时必须：

1. 完整加载 stage 1–16；
2. 用 `pg_get_functiondef` 保存最终函数体；
3. 以该体为基线仅加入 R3/R3b 增量；
4. 对返回 JSON 的既有键做逐字回归。

同样方式确认 `v13_advance` 的最终加载体；不能只根据早期 `v13/loop/advance.sql` 假定没有后续换体。

---

# 6. Implementation order

1. **冻结文档。**  
   先把本裁决追加为 R3 §7，并同步设计 §6.8/§10；后续实现不得自行改词表或 payload。

2. **做加载态机械核验。**  
   完整加载 stage 1–16，记录：
   - `tools` 最终列形状；
   - 最终 `v13_advance`；
   - mgraph 最终 `v13_requeue_stale`；
   - `artifacts`、`judgment_calls`、session context/spawn 列的实际名称；
   - pg_jsonschema draft-07 fixture。  
   这一步只校对名称和复制底稿，不产生新的设计选择。

3. **建立 stage 17 骨架和 schema seeds。**  
   在一个事务中先创建：
   - harness schema policy；
   - `harness_turn` seed；
   - helper、索引和 guard；
   - 安装期数据断言。  
   尚不提交。

4. **原子实现 unknown 面。**  
   加入 index、wall helper、最终版 requeue 换体、complete unknown 路径、resolve、回填和两个 deferred triggers。此组必须和 complete/requeue 换体同一次提交。

5. **实现 A15/H 完整链。**  
   在最终版 advance 上加入：
   - unknown 分支删除 status 写；
   - harness 工具识别；
   - 逻辑对算法；
   - wake；
   - signal 投影/消费；
   - material receipt；
   - approval human；
   - request immutability。  
   complete 同时加入 harness result 校验和 signal 投影。

6. **实现 cancel 与 closeout。**  
   新增 `v13_cancel`、`v13_closeout`，把 advance 的 finish/reject/cancel 终态路径统一接到 closeout；移除平行 terminal status 写法。

7. **完成 ACL。**  
   新函数全部先 `REVOKE PUBLIC`；只把控制 callable 授给 `v13_route`。触发器函数不授业务角色。保持 recall 无 effects SELECT。

8. **一次性提交 stage 17。**  
   回填、触发器、函数换体、seed 和 ACL 必须原子提交；不得分批上线。

9. **运行 stage 17 gate。**  
   先运行新控制 tests，再运行 stage 1–16 全量回归，并验证每个旧前缀单独加载仍通过。

10. **运行并发与性能 gate。**  
    覆盖 complete/requeue/renew、closeout/complete、signal/material 双消费和大 session state hash。

---

# P1 重开判定

## **GO**

H、A16 和 P1 剩余机器形状已全部冻结；下一轮不得再因以下事项 STOP：

- 哪个 tool 是 harness；
- 逻辑对在哪盖章；
- 首枚/续传/材料后新 turn 如何判；
- 普通 tool 是否可带逻辑对；
- terminal receipt 住哪、有哪些键；
- budget snapshot 抄什么；
- produced/children/unconsumed/state hash 如何计算；
- unresolved wake 是否能 closeout；
- cancel、unknown、material、wake、signal 的 payload；
- human origin 锚；
- steer 如何证明不改 request；
- advance 是否新增返回词。

剩余事项仅为机械验证，不是设计分叉：

1. 从加载 1–16 后的数据库取得最终函数体；
2. 将已裁逻辑映射到活体最终列名；
3. 确认扩展和权限前置；
4. 若存在历史 terminal 数据，按本计划的 `migration_backfill` 规则处理。

不得用机械核验结果自行改成 policy 名单、driver harness flag、第二推进函数、新 effect kind、新表或新列。