# v16：CLM 上下文自管理 + Jev-Mem 记忆控制面 整合方案（终裁版）

日期：2026-10-01。来源：两篇论文蒸馏（CLM, Shao et al. 2026-09-30；Jev-Mem, Jiang et al. 2026）+ 两轮 Oracle 设计/裁决（O1 = gpt-6-astra-fast-xhigh，O2 = grok-4.7）+ 仓库侧实际审核（对照 `docs/designs/v15-jaz-dev.md` rev 11 与 v15 实现逐项核验）。

**本文件是实现计划与裁决记录，不是行为权威。v16 开工前须先成文 `docs/designs/v16-jaz-dev.md` 并冻结。v15 的规格、gate、码表、SQL 一律不动。**

---

## 0. 结论一句话

另开 **v16 新树**（`v16/`、`v16`/`jaz` schema、`v16_*` 角色、`P16xx` 码段、独立 `SQL_LOAD_ORDER`），在 v15 十三 stage 行为保持端口之上加五个新 stage：**模型可编辑上下文投影（CLM）+ System-One 记忆控制面（Jev）**。存储面（追加不可变行）→ 控制面（Jev 类型化决策，廉价可审计）→ 代理面（模型 SQL revision，昂贵受治）。v15 的 23 张表、P1501–P1545 码表、gate 全部原样保留。

## 1. 裁决记录

### 1.1 版本策略（两轮一致）

开 v16，不做 v15 rev 12。理由：v15 SQLSTATE 硬顶 P1548 仅剩 3 空号（本方案需 4 码）；「stage 13 后不得加表」唯一例外已用掉（本方案需 4 张新表）；`begin_llm` 的 base 对齐合同、协议闭集都要改写——塞进 rev 12 会把已冻结的合运行时变成另一份合同。v16 端口 stage 1–13（行为保持，可选键缺席 = v15 行为），不加载 v15 SQL 文件、不依赖 v15 函数 OID。

### 1.2 D1–D12 终裁

| # | 分歧 | 终裁 |
|---|---|---|
| D1 | 表数 | **4 张新表**（`context_revisions`、`memory_nodes`、`memory_edges`、`memory_decisions`）+ `invokes.memory_scope_id uuid NULL`。不建 spaces/grants/query_runs/query_steps/attempts 表 |
| D2 | 读路径恢复 | **一次 `tool_attempt` 覆盖整次召回遍历**；崩溃走既有 reclaim（unknown→n+1 整次重跑），不落 hop 游标 |
| D3 | revision 并发 | **seq 单调（`max(seq)+1`，单租约下安全）+ 读时折叠**；不采用 base_revision OCC（模型计数能力差，CLM 附录 G）；不存投影快照，每 revision 存 `projection_digest` |
| D4 | revision 门控 | **v1 不门控**。无 `context_revision/validate` phase、无 allow/deny 效应；`memory_guard` 仅 send phase 瞬态 advisory 消息 |
| D5 | 保护窗默认 | **2 个已完成迭代**（对齐 CLM 参考实现 `protect=2`）。`context_protect_iterations` 缺席=2，显式 `>= 0` 整数 |
| D6 | 写路径挂点 | **finish_exec 不碰 memory**；quiescent 扫描器 `v16_next_memory_index` 找「无 canonical node 的 assistant/observation 消息」自愈入队，每步一条，Jev 在事务外 |
| D7 | ContextBench | **O2 的 A–D + O1 的 E（不可信记忆）**；D 的主判据 = `tool_attempts.result` 与送达 binding，不是 `jaz.request_messages` |
| D8 | SQLSTATE | **恰好 4 码**：P1601 `V16_REVISION_FORM`、P1602 `V16_REVISION_DENIED`、P1603 `V16_REVISION_LIMIT`、P1604 `V16_MEMORY_SCOPE`；硬顶 `P1648`；先钉 PG 18.4 errcodes 快照证明 P16 前缀空闲 |
| D9 | revision 失败语义 | P1601–P1603 走 `complete_statement('failed')`、迭代 continue 收束、**不进** §4.9 白名单；P1604 走 bind_tool reject、**必须加入** §4.9 工具拒绝族（否则 reject 后跟 done return 会 `V15_INVALID_TRANSITION`） |
| D10 | 合运行时命名 | **`agent_v16_memory_guard`**（末 stage 命名惯例；`agent_v16_tools`/`agent_v16_memory` 是前缀库） |
| D11 | FakeJev 未登记键 | **宽松防卡死**（Noul→0、Choice→uncertain）+ **反空转断言**（gate 必须证明预期 question_key 被命中；含「登记错误的 key 仍无边」负例） |
| D12 | prepare_statement 键集 | **保持四键**（`statement_fence`/`timeout_ms`/`kind`/`scratch_schema`）。审核证伪了「stage 13 实现已超集返回」——实现与规格一致就是四键；worker 从 settle 的语句行取 `arg_sql`/`tool_name`（bind_invoke/bind_tool 同款路径） |

### 1.3 审核证伪/证实记录

- 证实：§4.5.1 base 对齐合同（「message_id 与顺序必须与已存放的 llm_messages 一致」）；`llm_messages` 有 `no_update`/`no_delete` 触发器（55000）；hook 存储侧 `kind = 'persistent_hook'`；§4.9 return 候选的工具拒绝族白名单；§15「可选 hook 只在 govern 文件 CREATE」。
- 证伪：O2 声称 stage 13 实现已超集返回 prepare_statement 四键——实际 `v15/repl/v15_repl.sql` 893–898 行返回恰好四键。v16 端口按四键写合同。

### 1.4 行为裁定（R-V16 系列）

- **R-V16-1** 投影是请求的权威，原始 `llm_messages` 是档案（不可变触发器已保证）。
- **R-V16-2** 第七条规范语句 `jaz.revise_context`；wrapper 实际执行抛 `V15_INVOKE_FORM`（同 bind_invoke/bind_tool 手法）。
- **R-V16-3** 记忆表存活于 invoke scratch 之外；ACL = `memory_scope_id`（invoke 行上的列，子 invoke 复制，模型不可换）。
- **R-V16-4** 新码段 P1601–P1604，硬顶 P1648，钉文件先行。
- **R-V16-5** 记忆索引是 quiescent 的一部分（扫描推导的 pending 集，无状态可丢）。
- **R-V16-6** v1 无 System-Two 摘要生成；consolidation 只审计（merge/promote → `accepted=false, deferred=true, reason=system_two_disabled`）。
- **R-V16-7** `invalidated_chars` 只审计，不进 `reserved_cost`（与 `pricing.py` 实际用量计价避免双计）。
- **R-V16-8**（新增，自 D5）保护窗缺席 = 2；教学段写明冻结的数字，不写含糊的 "recent"。

## 2. 架构

```
存储面  llm_messages / repl_history / memory_nodes / memory_edges（追加不可变，行是权威）
控制面  memory_decisions + FakeJev/Jev（类型化打分，事务外，廉价，可审计成行）
代理面  模型 SQL：jaz.revise_context（投影）+ jaz.bind_tool('memory_recall')（召回）
```

投影链：`llm_messages → v16_projected_messages（读时折叠 revisions）→ render_base → truncate_base（硬上限不变）→ begin_llm`。`jaz.request_messages` 语义不变（= 实发请求）；`jaz.history` 仍是全文。

## 3. 错误码

| 代码 | SQLSTATE | 分类 | 触发 | 落地 stage |
|---|---|---|---|---|
| `V16_REVISION_FORM` | `P1601` | 语句失败 | ops 非长度 1..32 数组 / 元素键错 / 同语句重复 message_id / op 非 drop·replace / replace 无 content 或超 `max_repl_output_length` / 空数组 | 14 |
| `V16_REVISION_DENIED` | `P1602` | 语句失败 | `context_edit` 非 true / 目标不在投影 / 命中保护集（seed、persistent_hook、最近 P 个迭代） | 14 |
| `V16_REVISION_LIMIT` | `P1603` | 语句失败 | 本 invoke 已落地 revision 数达到 `max_context_revisions`（缺省 4） | 14 |
| `V16_MEMORY_SCOPE` | `P1604` | 语句失败（进 §4.9 工具拒绝族） | memory_recall 实参含 scope 类键 / invoke 无 memory_scope_id 却进召回转移 | 17（与 reject 路径、finish 白名单同一提交） |

- `P1605`–`P1648` 不分配不预占。`V16_*` 不进 hook abort 可保留闭集。
- 折叠时目标 id 已不在投影：`V15_INVALID_TRANSITION`（回滚类，库损坏）。SQL NULL 与 jsonb `null`：`V15_VALUE_INVALID`。与 FORM 互斥，不得两码都可能。
- **先钉 `v16/errcodes-pinned.txt`**（首行 `postgres 18.4`，§17 同款探针）；P16 前缀被占用则整段换前缀（连续无空号），然后才写 `RAISE`。
- `v16_io_sqlstate` 与 `v16_govern_known_code` 在引入该码的 stage 末尾 `CREATE OR REPLACE`，签名与 oid 不变。

## 4. 协议

第七规范语句：

```sql
SELECT jaz.revise_context(<jsonb-expr>);
```

- 分类 `kind = 'revise_context'`，`bind_name`/`tool_name` 为 SQL NULL，抽取 `arg_sql`。wrapper 实际执行 → `V15_INVOKE_FORM`。
- `context_edit = false` 时分类器仍识别（形状合法方言）、提示词不出现函数名；执行期 `v16_apply_revision` 抛 `P1602`。与 `recursion_available = false` 省 `bind_invoke` 同手法。
- 实参顶层恰一键 `ops`；元素闭集 `{"op":"drop","message_id":...}` / `{"op":"replace","message_id":...,"content":...}`。无 keep、无新增、无重排；drop 不带 content；消息顺序仍由 `msg_seq` 决定；replace 保留原 id 与位置。
- 只允许目标当前 invoke 已结束迭代的 `assistant`/`observation`。
- 三个可选 protocol 键（都不进 config 必填集，不加第五个 manifest 上限；其余新键仍 `V15_VALUE_INVALID`）：
  - `context_edit`：布尔，缺席 false。
  - `context_protect_iterations`：整数 `>= 0`，缺席 **2**。
  - `max_context_revisions`：整数 `>= 1`，缺席 **4**。
- 教学段仅 `context_edit = true` 时逐字出现在历史段之后，写明本 invoke 冻结的 P 与配额数字；缺席时渲染结果不出现 `revise_context` 字样。打开标志会改变 system 字节与 digest——预期行为。

## 5. `context_revisions` 与投影

```text
context_revisions(
  invoke_id, revision_seq, iteration, stmt_index, statement_fence,
  ops, changes_digest, before_chars, after_chars,
  earliest_msg_seq, invalidated_chars, trivial,
  projection_digest, created_at,
  PRIMARY KEY (invoke_id, revision_seq),
  UNIQUE (invoke_id, iteration, stmt_index)
)
```

- `revision_seq` 同 invoke 内从 1 连续（`max+1`）；只 INSERT，触发器拒 UPDATE/DELETE。行版本计数列 `revision` 沿用 v15 惯例。
- `projection_digest` = 应用本次 revision 后当时折叠结果的 `md5`（信封同 §4.5.1 base 信封，元素 `{msg_seq, message_id, role, kind, content}`，kind 用存储列）——是落地瞬间校验，不等于下一轮 `logical_digest`。
- `trivial = true` 当且仅当：无 drop 且字符改动绝对值之和 `< max(32, floor(0.01 * editable_chars))`（字符口径，对应 CLM 32-token/1%；不接 tokenizer）。trivial 仍落地，bench 有效编辑计数不计。
- `earliest_msg_seq` / `invalidated_chars`：审计列（被重预填的后缀），**不进 reserved_cost**（R-V16-7）。

**应用事务**（同 bind_tool 实参求值路径，但不挂起、不改 invoke 状态、不加 fence、不关 repl_exec）：

1. `v16_prepare_statement` 对该 kind 只 `GRANT USAGE`（`v16_repl_grant_scratch` 第二参数在 `bind_invoke`/`revise_context` 为假），四键返回不变。
2. worker 保存点内 `SET LOCAL ROLE v16_repl` 执行 `SELECT (<arg_sql>)`；恰一行 jsonb 对象，否则 `V15_VALUE_INVALID`。
3. `RESET ROLE` 后调 `v16_apply_revision(p_invoke_id, p_fence, p_owner, p_stmt_index, p_statement_fence, p_ops)` → `{"action":"applied","seq":...,"trivial":...}`。捕获集（回保存点、failed、COMMIT）：`P1601`/`P1602`/`P1603`/`V15_VALUE_INVALID`/`V15_INVOKE_FORM`；此外回滚整笔、语句留 pending 由 worker 重试。
4. 成功：保存点外 `complete_statement('done')`，`resume_stmt = stmt_index + 1`，invoke 保持 leased。投影在下一次 `v16_begin_llm` 才进请求。

**保护集**（`v16_apply_revision` 插入前判定，命中 `P1602`，整批不落）：

- `seed:system`、`seed:inputs`、`kind IN ('seed','persistent_hook')` 的每一行（模型删不掉 `budget_forcing`）；
- 当前执行迭代 `I`：`iter:<I>:assistant`，以及 `kind IN ('assistant','observation')` 且 `iteration >= I - P` 的行；
- 瞬态 hook 不在 `llm_messages`，指向它们 = 不在投影 = DENIED。

**折叠**：`v16_projected_messages(p_invoke_id)`（STABLE、definer、只授 v16_owner）是唯一折叠权威——按 `msg_seq` 取全量，按 `revision_seq` 升序应用 drop（included=false）/replace（只换 content），过滤后返回有序投影。Python 侧 `v16/protocol/project_context.py` 只作对照测试，不成为第二权威。`Worker.build_base` 先折叠再 `truncate_base`；`v16_begin_llm` 的 id/顺序校验改为对齐投影的存活 id。**stage 14 第一条测试：零修订时投影 id 序列 == `llm_messages`，端口行为不漂移。**

**边界**：P=2 时任务 A 的 drop 必须发生在迭代 3（阈值 `iteration >= I-2`：I=3 时 iter:0 可改、iter:1 不可）；stage 14 两条都断言。

**`jaz.context_budget()`**：invoker+definer，返回 `{projected_chars, limit_chars, revision_seq, protected_chars}`（无修订 seq=0；无 exec_context 抛 `V15_INVALID_TRANSITION`）——CLM 附录 G「长度意识」的 SQL 落点。

**子 invoke**：修订行不复制；`jaz.prior_history` 仍全文；`context_edit` 经 config 折叠继承（local 层只作用本 invoke）。

**replay**：导出含每步已应用 `seq`/`ops`/`projection_digest`，请求侧带 `context_revision_seq`/`context_projection_digest`；不一致沿用 `P1541`。未接受的候选 patch 不进轨迹。

## 6. 记忆控制面（写路径）

### 6.1 表

```text
memory_nodes(  node_id PK, memory_scope_id, source_invoke_id, source_message_id,
  source_iteration, source_msg_seq, message_kind CHECK IN ('assistant','observation'),
  body, content_digest, entities jsonb, created_at,
  revision bigint DEFAULT 0,
  UNIQUE (source_invoke_id, source_message_id))          -- 只追加

memory_edges(  edge_id PK, memory_scope_id, src_id FK, dst_id FK,
  rel CHECK IN ('entity','temporal','semantic','causal'),
  score numeric NULL, rule CHECK IN ('same_entity','time_adjacent','jev'),
  decision_id uuid NULL, revision bigint DEFAULT 0,
  UNIQUE (src_id, dst_id, rel))                          -- 只追加；高分不 UPDATE 旧边

memory_decisions(  decision_id PK, memory_scope_id,
  source_invoke_id NULL, source_message_id NULL,
  phase CHECK IN ('write_type','write_edge','consolidate','read_route','read_assess','read_stop'),
  question_key, response jsonb, accepted boolean, created_at, revision bigint DEFAULT 0,
  UNIQUE (memory_scope_id, phase, question_key))         -- 只追加
```

`invokes.memory_scope_id uuid NULL`：root 由可信宿主在 open 传入（`v16_open_invoke` 增可空参数），子 invoke 在 `v16_suspend_for_child` 原样复制；NULL = 不启用记忆；模型 SQL 不可写。**scope 是 bearer 凭据**（OP-3）：视图只滤本 invoke 行上的列，模型读不到他人 scope 不是因为 uuid 难猜。

索引范围：scope 非空的 assistant/observation 消息；不索引 seed 与 hook。节点 body 来自 `llm_messages` 全文（非截断投影）。

### 6.2 扫描与恢复

- `v16_next_memory_index()` 只读返回首个「无 node 的待索引消息」对；worker 循环顺序：`reclaim → 至多一条记忆索引 → drive_tools → claim/drive`；`steps > 256` 仍 RuntimeError。
- 索引步：事务外跑打分 → `v16_store_memory_write` 一次提交（node + 边 + decision 同事务）。
- 崩溃面：提交前崩溃 → 下次扫描再看見；两 worker 竞争 → `UNIQUE` 吸收，后提交者视为已索引，不把 invoke 打失败。Jev 故障 = 记忆降级态，不是机器故障，不写 llm attempt。
- 每满 20 个 node 追加一条 `phase='consolidate'` decision；merge/promote → `accepted=false, deferred=true, reason='system_two_disabled'`（R-V16-6），不生成摘要节点。

### 6.3 写算法与阈值

- 实体：确定性规则（长度 ≥3 标识符 + 标准 uuid 文本，上限 32），不做 NER。
- 候选：同 scope、`created_at` 更早、horizon 500 内；词法 Jaccard（切词、小写、长度 ≥3）+ 共享实体 + 时间邻近，Top 10。
- 确定性边（不调 Jev）：共享实体 → `rel=entity, rule=same_entity`；同 invoke 迭代差 ≤1 → `rel=temporal, rule=time_adjacent`。
- Jev 边：候选每对至多两问（semantic/causal Noul），`score >= 0.60` 落 `rule=jev` 边；本节点 Jev 硬顶 14 次（4 类型 + 10 边），到顶 `truncated_candidates=true`，节点仍插入。
- 四类型分（episodic/semantic/procedural/preference）都要问；≥0.60 写入 `write_type.response.types`。

### 6.4 FakeJev / 真 Jev

```text
FakeJev.noul(question_key) -> Decimal        # 量化 0.01，ROUND_HALF_UP
FakeJev.choice(question_key, options) -> (label, distribution)
```

- `question_key = sha256(phase + '\n' + question + '\n' + sorted(source_message_ids))[:32]`（SQL/Python 同一纯函数拼）。
- 未登记：Noul→0，Choice→`uncertain`（概率 1）。无时钟、无随机、无套接字；非法 response fail-closed。
- **反空转 gate 三条**（stage 16 缺一不可）：①不登记 → 有节点、无 jev 边、types 空；②用同款纯函数算 key 登记分数 ≥0.60 → 边分数与 decision 一致；③登记一个**别的** key → 仍无 jev 边（防 key 推导 bug 假绿）。
- 真 Jev（`v16/memory/jev_client.py`）：opt-in、无打开事务、超时 15s、凭据在宿主配置不入库；`--real-jev-smoke` 冒烟非 gate。一个库的 worker 池同质（全 Fake 或同一真端点）。

## 7. `memory_recall`（读路径）

- `tool_catalog` 注册名 `memory_recall`，`external=true`，角色 `v16_tool_memory_recall`；同步调用 `P1517`；模型写 `SELECT jaz.bind_tool('<ident>', 'memory_recall', <jsonb>);`。
- 实参只允许一键 `query`（文本，≤ `max_invoke_input_length`）；多键/缺键/scope 类键 → `v16_suspend_for_tool` 拒绝分支提交 `P1604`，invoke 仍 leased 可继续。scope 为空 → 不发放 grant → 既有 `V15_TOOL_UNAUTHORIZED`。
- grant 发放逻辑在 stage 17 对 `v16_open_invoke`/`v16_suspend_for_child` 的 `CREATE OR REPLACE` 里（scope 非空才发），oid 不变。
- **一次 `tool_attempt` 覆盖整次遍历**：短事务 claim → 提交 `call_started` → 无事务跑完整检索 → 短事务写 result → binding 送达。崩溃（call_started 已提交）→ reclaim 收 `unknown` → `n+1` 整次重跑直到 `governance_io`。FakeJev 下幂等；真 Jev 不幂等与 provider unknown 同代价。
- 遍历（`v16/memory_recall/runner.py`）：开始时一条只读查询载入该 scope 候选（horizon 限制），期间不再读库。路由（四视图 Noul ≥0.60 激活 + 多跳 Choice + 新近性 Noul；全低于阈值则激活最高者）→ 预算 80 节点按激活视图分配 → RRF（k=60）锚点 → expand/assess（beam 10；候选三问：相关性/关系有用性/新颖性；证据支持用实体重合 0/1 不问 Jev）→ 停止（`sufficient>=0.95 ∧ missing<0.15 ∧ contradiction<0.15`，或 `continue_useful<0.15`，或硬顶：深度 8/节点 60/边 2400/Jev 16 次/15 秒单调时钟）。
- result：`{"ok":true,"value":{"nodes":[{node_id,source_message_id,body,rel}],...}}`；`nodes[].body` 截到剩余预算、序列化超 `max_repl_output_length` 从尾部丢节点且 `stopped="cap"`（仍 ok:true）。异常收 `{"ok":false}` 走 `V15_TOOL_FAILED`。
- **`P1604` 加入 `v16_finish_exec` 的 return 切点前可跳过失败码集合**（与四个 `V15_TOOL_*` 并列；D9）。
- `jaz.memory_nodes` / `jaz.memory_edges`：`security_barrier` 视图，按本 backend `exec_context.invoke_id` 找 scope 过滤；scope 空返回空表、无 exec_context 抛 `V15_INVALID_TRANSITION`；基表对 repl/worker/PUBLIC 全 REVOKE。
- **replay**：含 `memory_recall` 的树继续 `P1524` 拒绝导出（工具回放是 stage 19 级后续立项，不动 `logical_digest`）。

## 8. `memory_guard`（advisory hook）

- 可选 hook，`hook_key='memory_guard'`，config 恰一键 `contradiction_ceiling`（0 < x <= 1）。默认不进任何 profile。
- 只在 `llm_query/send` 行动：读本 scope 最新一条 `phase='read_assess'` 且 accepted 的 decision；`contradiction` 达阈值 → 追加一条 `persistent=false` user 消息，id `memory_guard:<ordinal>`（两段，不进 forcing 计数族）。无 decision → proceed。不 abort、不写表、不调 Jev、**不注入 node 原文**。
- 放置例外写入 v16 规格：baseline 四 hook 仍在 govern 文件 CREATE；其后的可选 hook 只在引入它的 stage 文件 CREATE 且不得 `CREATE OR REPLACE` `v16_on_phase`。`memory_guard` 只在 `v16/memory_guard/v16_memory_guard.sql`。

## 9. Stage/Gate 计划

stage 1–13 = v15 端口（目录/文件名同构，`v16_` 前缀；端口允许差异仅：角色与 schema 名、`v16_open_invoke` 多可空 `p_memory_scope_id`、`invokes.memory_scope_id`、`statements.kind` 第一天含 `revise_context`（端口期无应用函数，夹具不发）。端口 gate 证明「可选键缺席 = v15 行为」；不把 open 参数列表做成与 v15 字节相同断言）。

| # | 目录 | SQL | gate 证明 |
|---:|---|---|---|
| 1–13 | schema…tools | `v16_<stage>.sql` ×13 | v15 对应行为等价（状态机/事务边界/unknown 墙/fence/预算/replay/工具）；prepare 四键；gate 零套接字 |
| 14 | `v16/context` | `v16_context.sql` | **第一条：零修订对齐**；分类/保护集 P1602/形状 P1601/配额 P1603；成功后 `llm_messages` 不变、`context_revisions` 一行、下一 settled attempt 的 request 不含 dropped id、含 replace 正文、`logical_digest` 改变；`jaz.history` 仍全文；`context_edit` 缺席调用 → P1602 零行；trivial 与 invalidated_chars；失败不终态化 invoke；迭代 3 上 drop iter:0 成功 + drop iter:1 为 P1602；`jaz.context_budget` |
| 15 | `v16/context_bench` | 注释文件（加载成功不建表） | 任务 A（迭代 3 drop 旧观测；效果分=下一实发 request）/ B（4 字符 replace，trivial=true）/ C（drop seed:system → P1602、零行、非终态、下一轮仍有重渲染 system）。不做 D/E |
| 16 | `v16/memory` | `v16_memory.sql` | 四表约束（只追加）；finish 不插节点；扫描自愈（崩溃未写节点仍返回该消息）；**反空转三条**；确定性边不依赖 Jev；0.60 阈值；第 20 节点 consolidate 且 deferred；Jev 故障不影响 invoke/canonical；零套接字 |
| 17 | `v16/memory_recall` | `v16_recall.sql` | external 注册；同步 P1517；实参带 scope 键 → P1604 且无 request 行；finish 白名单含 P1604；同 scope 第二 invoke 的 tool result 含种子节点 id；另一 scope nodes 为空且不含该 id；`jaz.memory_nodes` 跨 scope 滤除；硬顶（FakeJev 永不 sufficient）→ stopped=cap 且 jev_calls<=16；call_started 后杀进程+reclaim → unknown、n=2；**任务 D（主分=tool result+var binding）与任务 E（不可信记忆：result 含 node_id 且 body 原文；召回机械不把正文写成 seed/hook/system；正文进下一轮 request 仅当剧本 print）** |
| 18 | `v16/memory_guard` | `v16_memory_guard.sql` | send 瞬态消息注入；contradiction 低于阈值 → request 无 `memory_guard:<ordinal>`；不增 hook_counters；不 abort；不改 `v16_on_phase` oid |

- 合运行时 = `agent_v16_memory_guard`（18 文件全加载）。前缀库：`agent_v16_tools`（13）、`agent_v16_memory`（16）。
- `v16/load.py` 独立 `SQL_LOAD_ORDER`（18 文件，只许末尾追加），不导入 v15 loader；`setup_db.py` 清理范围仅 `agent_v16_*` 库与 `v16_*` 角色。
- gate 命令 `uv run python v16/<stage>/test_<stage>.py`，退出码 0 通过；一 stage 一提交（AGENTS.md 纪律）；M-里程碑矩阵另文。

## 10. go/no-go 与实施顺序

**硬 no-go（FakeLLM/FakeJev gate 任一触发即停）**：原文被 UPDATE/DELETE；revision 改到 seed/hook/保护窗；失败 revision 留行；prepare 返回超四键；重复 canonical node；unknown 被结算成功；跨 scope 读取；事务中调 Jev；未登记 key 假绿；P1604 不在 finish 白名单。

**DeepSeek context-edit 人工关卡（OP-1/OP-2，非 gate）**：`v16/context/smoke.py --real-provider-smoke`（默认拒绝构造传输；无打开事务；隔离数据）。缺省 P=2 下任务须跑到迭代 3。门槛：四题 ≥2 题分类为 `revise_context` 且 reject_code 空、≥1 题下一轮投影字符严格变小、0 题 aborted、seed/保护零违规、**人工签字**。未过 → `context_edit` 保持 false（机制代码可留），不放宽分类器凑数。

**实施顺序**（标注原子的步骤必须一起落地）：

1. 钉 `v16/errcodes-pinned.txt`，证明 P16 空闲；被占则换前缀后再写 SQL。不建库对象。
2. 端口 stage 1–13。每 stage 单独提交、gate 绿；与 v15 行为差仅限 §9 允许清单。
3. **原子**：分类器第七式 + `v16_context.sql`（projection_digest、保护窗缺省 2）+ worker `_revise_context`（从语句行读 arg_sql）+ `build_base` 先折叠 + prepare 仅改 scratch grant 条件。stage 14 绿（第一条 = 零修订对齐）。
4. stage 15（A–C；A 的 drop 在迭代 3）。
5. 人工烟测（步骤 9 的条件，不是本步骤后续代码的条件）。
6. **原子**：`limits.py` + `fake_jev.py` + `index.py` + `v16_memory.sql` + quiescent 索引一步。stage 16 绿（含反空转三条）。
7. **原子**：`recall.py` + `v16_recall.sql`（finish 白名单 + P1604 + grant 按 scope 发放）。stage 17 绿（补 D/E）。
8. stage 18 memory_guard；合运行时 `agent_v16_memory_guard`。
9. 仅当 OP-1/OP-2 双签字后的单独提交，才把种子 profile `context_edit` 改 true，并断言教学段含数字 2 与函数名。

**回退**：关 `context_edit`/不传 scope → v16 = v15 行为 + 固定截断；Jev 故障 → 记忆降级（recall 明确 unavailable，不伪造空成功）；不动 v15。

## 11. 开放点（留仓库所有者）与后续立项

**编码前须签字（无「先编码后补签」空间）：**

- **OP-1** 烟测通过后是否把种子 profile `context_edit` 改 true（打开 = 另一次提交 + 人签）。
- **OP-2** 门槛是否维持「≥2/4 合法、≥1 变短、0 aborted」（发布标准，非代码结构）。
- **OP-3** `memory_scope_id` 是 bearer 凭据：谁持有 uuid 谁的 invoke 可读该 scope。对外宣称「记忆隔离」前须接受：uuid 不得进提示词与日志；「猜不到 uuid」不是安全边界。多租户需每租户角色/签名 token/独立库，另立裁定。

**产品/政策类（v1 按默认编码，改口需另裁定）：**

- OP-4 canonical payload 隐私边界（是否存全文/脱敏/保留期/删除权与不可变节点的冲突——Jev「观测不丢弃」vs 隐私删除是直接冲突，上线前必须裁）。
- OP-5 可编辑目标长期边界（是否收紧到仅 observation）。
- OP-6 revision 策略（是否开放 fit 增长模式/更大配额/trivial 豁免）。
- OP-7 候选发现是否引入 pgvector/embedding（v1 无：扩展需超级用户，gate 镜像会变）。
- OP-8 真 Jev API 契约（预算 80 的单位、批量 shape、认证、超时、幂等）——接入前必须服务方确认，不得臆造。
- OP-9 阈值校准（0.60/0.85/0.95/0.15 皆「未校准实验默认」，`limits.py` 注释写明；上线重校准需人批）。
- OP-10 v15 transcript → v16 canonical node 的正式 importer（若做：来源标签/scope/脱敏/不可 replay 声明）。

**后续立项（不预加表/列/码）：** System-Two 摘要节点（derived node + 可追溯类型 + 单独裁定）；pgvector；`memory_recall` 回放（stage 19，仍不把记忆图进 `logical_digest`）；召回正文过滤/信任标签。

## 12. 文件清单（全部新建；`v15/**`、`v13/**`、`v8/**` 零修改）

```text
docs/designs/v16-jaz-dev.md            行为权威（开工前冻结；含 D1–D12、R-V16-1..8、§9 stage 合同）
v16/load.py  v16/support.py  v16/worker.py  v16/limits.py  v16/errcodes-pinned.txt
v16/{schema,namespace,config,protocol,repl,io,loop,tree,govern,provider,return_hooks,replay,tools}/…
v16/protocol/split_sql.py  v16/protocol/render_prompt.py  v16/protocol/project_context.py
v16/context/{v16_context.sql,test_context.py,smoke.py}
v16/context_bench/test_context_bench.py（SQL 仅注释）
v16/memory/{v16_memory.sql,fake_jev.py,jev_client.py,index.py,runner.py,test_memory.py}
v16/memory_recall/{v16_recall.sql,runner.py,test_memory_recall.py}
v16/memory_guard/{v16_memory_guard.sql,test_memory_guard.py}
v16/fake_jev.py（若并列于 fake_llm.py 则 memory/ 下不再放）
```

权限要点：`v16_apply_revision` EXECUTE 只给 v16_worker；`v16_projected_messages` 只给 v16_owner；`jaz.context_budget`/`jaz.memory_nodes`/`jaz.memory_edges` 给 v16_repl；memory 三表对 PUBLIC/repl/worker 全 REVOKE，worker 只经存储函数写。
