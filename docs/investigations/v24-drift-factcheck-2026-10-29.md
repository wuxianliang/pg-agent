# v24 documented ≠ implemented 漂移：事实核查

- 日期：2026-10-29
- 输入：`docs/investigations/deepseek-harness-design-vs-v24-2026-10-29.md` I0 / S1–S7
- 目的：在修复前逐条确认“文档说什么、代码实际做什么、测试是否覆盖、最小修法是什么、会触碰哪些 gate/工件”
- **修复口径（用户 2026-10-29 明确）**：保持实际实现，只修文档；不改 SQL/host/test。
- 约束：本文件只记录事实与文档修法；核查阶段未改源码。
- **W1 状态（2026-10-29）：完成。** 已按 D1/D2/D3/D4 的精确 old→new 文案完成文档对齐；实现、测试、loader 与 gate 脚本未改。收尾记录见 deviation ledger `D-S1-1`、`D-S3-9`、`D-S4-11`、`D-MR-11` 与 conformance matrix §2.8。
- **M5 状态（2026-11-01）：** D2/D3/D4 的旧结论保留为历史；本轮按各节末尾带日期的 M5 修订对齐 descriptor v2 参数/output 校验、replay 边界与 journal transcript 权威，未改运行时、SQL、host 或测试。

## 核查范围

| ID | 漂移 | 文档 | 代码 |
|---|---|---|---|
| D1 | `turn_no` 语义 | 设计稿 §3.1.2 `:136` | `v24/sql/48_loop.sql:588`、`:1411`；`:1255`、`:1716` |
| D2 | 参数 JSON Schema 校验 | 设计稿 §5.1 `:271`、`:273`、§5.4 `:295`、§5.6 `:309` | `v24/sql/48_loop.sql:296-307`；`30_advance.sql:745-806`；`10_schema.sql:127,190` |
| D3 | 只读工具 `replay_safe` | 设计稿 `:411`、`:576`、`:667`、`:713` | `v24/sql/48_loop.sql:1133`、`:2963`；`49_recovery.sql:351-375` |
| D4 | host journal 作为 transcript/provider id 来源 | 设计稿 `:54`、`:201`、`:295`、`:466`；`v24-db-native-agent-system:67` | `v24/host/worker.py:944`、`:1125-1137`、`:1190-1231`；`journal.py:1-15` |

## D1. turn_no

### 文档声明
设计稿 `:136`：`turn_no bigint` = “已提交模型步骤数”。

### 实现事实
- start/child 初始 0：`40_interpreters.sql:656`、`:2869`。
- **model settlement** +1：`48_loop.sql:588`，写回 `:1255`。
- **tool settlement** +1：`48_loop.sql:1411`，写回 `:1716`。
- applier 强制 `turn_no == r.turn_no + 1`：`48_loop.sql:1978-1991`，应用 `:2905`。
- cancel/steer/respond/poll/wait 不写 `turn_no`。
- cancel-late unknown 只复制原值，不 +1：`49_recovery.sql:126-129`。
- 投影：`47_verbs.sql:21`，poll `:35`，wait `:96`。
- 语义 = **已提交业务 settlement 数**（model + tool 各一次），不是模型步数；§5.1 `:269` 的 effect-turn 定义才是实现。

### 测试覆盖
- `v24/s4/test_g2b.py:941`（model batch 后 `turn_no == 1`）、`:963`（3 个 tool settlement 后 `== index + 2`）、`:973`（`== 4`）、`:990`（`== 5`）。
- `v24/s4/test_g2b.py:1780-1823`：start 0 → model 1 → tool 2 → tool 3；打印“turn_no advances 1->2”。
- `v24/s6/test_g5.py:1307`（model unknown → 1）、`:1377`（cancel-late unknown → 0，不增）。
- `v24/s7/test_g6.py:1616`、`:2699`、`:3126`、`:3208`、`:3303`（一次 settlement → 1）。
- `v24/s8/test_g7.py:352`（child 0）、`:502`（`before + 1`）。
- `v24/s12/test_g11.py:588`（cancel-late seal 保持）。
- 结论：测试全部按“settlement 计数”断言；无“模型步数”语义。

### 文档修法（只改文档）
1. `docs/designs/v24-pg-agent-2026-10-22.md:136`
   - 旧：`` `turn_no bigint` 已提交模型步骤数；``
   - 新：`` `turn_no bigint` 已提交业务 settlement 数（`model_call` 与 `tool_call` 各一次 settlement +1；`cancel`/`steer`/`respond` 与 cancel-late settlement 不增；start/child 初始 0）；``
2. 同文件 `:201`
   - 旧：`turn 是 model effect 与 advance 的序号事实，写在 runs/events/effects。`
   - 新：`turn 是任一 business effect（`model_call`/`tool_call`）的 settlement 与唯一 advance 的序号事实，写在 runs/events/effects。`
3. 可选在 §5.1 `:269` 追加一句：`runs.turn_no` 即此 turn 的已提交计数：model/tool settlement 各 +1（`48_loop.sql:588`、`:1411`），cancel-late unknown 只发布事实不 +1（`49_recovery.sql:126-129`）。

### 触碰面 / gate
- 纯文档；不改 `10_schema`/`47_verbs`/`48_loop`/`49_recovery`，不改测试。
- 无需重跑 closeout；现有测试已经断言 settlement 语义。
- 台账新增一行“S1 文档对齐（wording-only，零代码影响）”；READMEs 不改。

## D2. 参数 schema 校验

### 文档声明
设计稿 `:271` “schema 正确”；`:273` “参数只按冻结 JSON schema 校验”；`:309` “参数过 schema”；`:295` “tool result schema 按 descriptor 固定版本验证”。

### 实现事实
- model settlement 只查：item 是 object、key 集合恰 `{key,args}`、key string 1–256、args object（`48_loop.sql:296-307`）。
- tool request/claim 只查：闭集 9 key、args object、`descriptor_digest` 与 pin 字节相等（`30_advance.sql:745-806`，尤其 `:805-806`）。digest 相等 ≠ schema 校验。
- tool result 只查 `{status,output,usage}` 形状（`48_loop.sql:1376-1387`），不按 descriptor 校验 output。
- `slots.descriptor` 是不透明 jsonb（`10_schema.sql:190`）；`pins` 只有 `descriptor_digest`（`:127`）。
- `parameters` 只被 host 用来渲染 provider 工具列表（`v24/host/deepseek.py:358-372`），仅断言 `type == "object"`；host 派发只查 key/args 形状（`v24/host/plugins.py:57-70`），不校验参数。
- **DB 与 host 都没有 schema 校验**；不能把文档改成“host 校验”。

### 测试覆盖
- `v24/s4/test_g2b.py:2742-2746`（precheck invalid_outcome）、`:2701-2718`（key ∉ pins → invalid_args）、`:2662-2688` / `:1442-1448`（17 tool_calls → invalid_outcome）、`:832`（key outside pins → semantic unknown）。
- `v24/s11/test_g10.py:329-353`（exit 3 → failure）、`:361-406`（bad frame → unknown）。
- 无任何 gate 断言 `parameters` 校验。

### 文档修法（只改文档）
1. `:271`
   - 旧：`advance 校验每项 tool key 存在 run pin、schema 正确、工具预算允许后生成 tool effects`
   - 新：`advance 校验每项 tool key 存在 run pin、{key,args} 形状与工具预算允许后生成 tool effects`
2. `:273`
   - 旧：`tool descriptor 是固定 host adapter id + digest，参数只按冻结 JSON schema 校验`
   - 新：`tool descriptor 是固定 host adapter id + digest；DB 对参数只做形状校验（args 为 JSON object、key 与 descriptor_digest 与 live run pin 相符），slots.descriptor 是不透明 jsonb，其 tool.parameters 只由 host 渲染给 provider，DB 与 host 均不按该 schema 校验参数内容，参数语义由插件自行决定`
3. `:309`
   - 旧：`固定 slot id/descriptor digest/schema/pin，参数过 schema 且 replay 权利明确`
   - 新：`固定 slot id/descriptor digest/pin，参数只过形状门（object）且 replay 权利明确`
4. `:295`
   - 旧：`tool result schema 按 descriptor 固定版本验证`
   - 新：`tool result 只校验 {status,output,usage} 形状，不按 descriptor 校验 output 内容`
5. 台账新增 `D-S4-11`（post-closeout spec-layer revision）：DB/host 均不执行 parameters/output schema；文档降级；无 gate 断言。
6. `docs/plans/v24-s4-agent-loop-2026-10-24.md:187`、`:512` 的 “result schema / 参数 schema” 表述加注“历史计划；实现已降级为形状校验，见台账 D-S4-11”，或不动计划仅在台账说明（agent 选一种，优先台账）。

### 触碰面 / gate
- 纯文档；不改 `48_loop`/`30_advance`/`10_schema`。
- 无需重跑 gate；G2b/G8/G10 全部只断言形状。
- **M5 修订（2026-11-01）：** 原“DB 与 host 都没有 schema 校验”只作为 descriptor v1 / DB 层的事实保留。v2 descriptor 的参数与 output 已由 host 在 spawn 前按封闭 schema 子集校验；引用本次修订后的主设计 §5.1/§5.4 与 ABI §5.5/C.13。`v24/host/plugins.py:57-70` 的描述属于 `_tool_v1`，不覆盖 v2 `_tool_v2` 的第 2/3/10 步；DB 仍未新增 schema validator。

## D3. replay_safe

### 文档声明
设计稿 `:576` 允许纯读取/确定输出的 tool 声明 `replay_safe`；`:411`、`:667`、`:713` 描述 `replay_safe` 恢复分流。

### 实现事实
- tool successor 唯一构造点硬编码 `no_replay`：`48_loop.sql:1133`；applier 也硬编码：`:2963`。
- 其他 model successor（continuation/steer/respond/spawn）同样 `no_replay`：`48_loop.sql:930`、`:1178`、`:1581`、`:1639`；`40_interpreters.sql:669`、`:1032`、`:2889`。
- `replay_safe` 只用于 host kinds 与 recover/install：`40_interpreters.sql:2357`、`:2375`、`:4072`、`:4083`；`49_recovery.sql:351-368` 只对 `replay_safe + host_prepare/host_release` 或 `inspect_resource` 做 reset。
- `no_replay + model_call/tool_call` → `settle_unknown` + `blocked_unknown`：`49_recovery.sql:369-371`。
- `replay_safe` 的其他 kind 落到 `:372-375` `skipped{kind_unsupported}`，既不 reset 也不 unknown。
- 无任何工具路径是 `replay_safe`。

### 测试覆盖
- 工具 `no_replay`：`v24/s4/test_g2b.py:1900`、`:2149`、`:2563`、`:2710`、`:2766`、`:2843` 只是种子行，不是 successor 断言；`v24/s8/test_g7.py:375`（child model no_replay）、`:1426`（applied settle_unknown）；`v24/s9/test_g8.py:900`、`v24/s7/test_g6.py:1054`、`:1578`、`v24/s1/test_ddl.py:34` 为种子/DDL。
- `replay_safe` 行为全部是 host kinds：`v24/s6/test_g5.py:754`、`:1046`、`:1048`、`:1601`、`:2717`、`:2728`；`v24/s6/g5_support.py:61`、`:183`、`:202`；`v24/s12/test_g11.py:234`；`v24/s9/h_support.py:361`、`:397`、`:413`。
- 无 gate 断言“工具可 replay_safe”。

### 文档修法（只改文档）
1. `:576`
   - 旧：`tool 若是纯读取且输出确定，可以按 adapter 和目标资源版本声明 replay_safe；写工具只有目标系统提供稳定 idempotency key 或可验证 inspect 才可进入该类。`
   - 新：`v1 的 tool_call successor 一律为 no_replay：tool effect 由 model settlement 同事务构造并硬编码该策略（48_loop.sql:1133；applier 48_loop.sql:2963），不读 descriptor。因此 lease 过期或宿主崩溃的 tool effect 只走 unknown 收敛（run blocked_unknown），不重投。若要允许纯读取工具声明 replay_safe，必须先有 spec revision，并同时修改 successor 构造、successor 校验闭集（48_loop.sql:2650-2651）与 command_recover 的 replay_safe 分流（49_recovery.sql:351-375）。`
2. `:411` / `:667`：在“只有显式 replay_safe kind 可在资格过期后重投”后加 `（v1 仅 host_prepare/host_release/inspect_resource 可为 replay_safe）`。
3. `:713`：`replay_safe 置回 ready…` → `replay_safe 且 kind ∈ {host_prepare,host_release,inspect_resource} 才置回 ready…；其他组合记 skipped{reason:'kind_unsupported'}，既不 reset 也不结算 unknown。`
4. 台账新增一行“设计 §B.4 L576 工具 replay_safe 条款经文档降级关闭；v1 全工具 no_replay”，并注明“工具 successor 的 replay_policy 无 gate 断言（G2b 仅种子）”是既有证据缺口。

### 触碰面 / gate
- 纯文档；不改 `48_loop`/`49_recovery`。
- 无需重跑；G5 K2/K3 证明的正是“host replay_safe 重投、model/tool no_replay → unknown”。
- **M5 修订（2026-11-01）：** `replay_class` 仍是 metadata；tool successor 仍硬编码 `no_replay`，本轮没有新增工具 replay 权。W4c 证明的是**已完成 outcome** 经 journal replay 不重渲染、不二次 spawn，不等于未决工具自动重执行，也不等于 `tool_call` 可 `replay_safe`。

## D4. host journal / transcript 权威

### 文档声明
- `v24-db-native-agent-system-2026-10-22.md:67`：宿主 journal 是外部证据副本；丢失不能改变 DB 已知/未知。
- `v24-pg-agent-2026-10-22.md:466`（D1 债务）：host durable journal 是最小代价的一部分。
- `v24-pg-agent-2026-10-22.md:201`：turn 的序号事实写在 runs/events/effects。

### 实现事实
- `worker.py:944` 调 `_history(run_id)`；`_history` 只读 journal（`:1190-1231`）：`effect_prepared.seed_messages/appended_messages`、`dispatch_finished.assistant_message/tool_message`。
- `worker.py:1125-1137` 从 journal 的 `assistant_message.tool_calls[ordinal]` 取 provider `tool_call_id`。
- journal 是 fsync + append-only + 单写者（`journal.py:1-15`），事件集是 effect lifecycle，不是通用 transcript。
- DB 缺：provider `tool_call_id`、assistant raw message（含 `reasoning_content`）、provider tool name/原始 `arguments` 字符串、渲染后的 tool message。
- 删除 journal 后：`_history()` 返回 `[]`；非 start/spawn 的 model call 在 `deepseek.py:257-258` 抛 `history_missing` → `_no_http_failure` → `failure`；续链不可重建。无 gate 覆盖此场景。
- 结论：journal 是 provider 对话原文的唯一持久处；DB 只有语义投影与提交顺序。文档的“IO 证据副本”错误。

### 文档修法（只改文档，先修当前错误；DB 派生 transcript 另立设计）
1. `v24-db-native-agent-system-2026-10-22.md:67`
   - 旧：`宿主 journal 是外部证据副本；它丢失不能改变数据库中的已知/未知边界。`
   - 新：`宿主 journal 是外部 IO 回执、provider 侧明细与该 run 后续 model 请求对话原文的唯一持久处；它丢失不改变任何十表行与已知/未知边界，但使该 run 的续链不可重建（history_missing → failure），只能经 command_recover 转 unknown。`
2. `v24-pg-agent-2026-10-22.md:54` 追加：`[规格] 同理，DB 不拥有 provider 对话原文；跨 turn 的 assistant/tool 消息由受信 host journal 承载，DB 只拥有其语义投影与提交顺序。`
3. 同文件 `:201` 追加：`…写在 runs/events/effects；但 turn 的内容分居两处：语义投影在十表（effects.outcome.body.result 与 tool 的 {status,output,usage}），provider 原始形态（assistant reasoning_content、provider tool_call_id、provider tool name 与原始 arguments 字符串、渲染后的 tool message）只在 host journal。DB 不承诺可从中重建下一次 provider 请求字节。`
4. 同文件 `:295` 追加：`该形状是有损投影：provider tool_call_id、reasoning_content、provider tool name 与原始 arguments 字符串不入库，只在 host journal。`
5. 同文件 `:466` 追加：`…；且 host journal 同时是该 run 后续 model 请求的唯一对话来源，丢失即阻断续链（不只丢 receipt）。`
6. `v24/s10/README.md:29` 追加一句：`跨 turn 请求重建以 host journal 为唯一来源；DB 只有语义投影。`
7. 台账 `:417` 的 I3：`journal 必须与十表分离` 后加 `（指夹具 schema 闭集，不指权威归属）`；新增 `D-MR-11`：host journal 是 provider 对话原文唯一持久处；DB 仅有语义投影；G9-A/B 的 reasoning_content/tool_call_id 回传即证据。
8. 矩阵 §0.6（`:188-190`）的映射 bullet 追加：`因此跨 turn 请求重建以 journal 为唯一来源。`
9. 明确**不**在本轮做 `derive_model_messages`/新增 outcome 字段；那是设计变更，另立计划。

### 触碰面 / gate
- 纯文档；不改 `worker.py`/`journal.py`/`48_loop`/`10_schema`。
- 无需重跑；但修复 agent 必须用 `git diff --exit-code -- v24/sql v24/host` 证明代码零变更。
- **M5 修订（2026-11-01）：** v2 的 `model_text` 经 `tool_message` 持久化；journal 仍是 provider 对话原文与 transcript 权威，DB 仍只有语义投影。重启只从 journal replay 已记录 outcome，不重新 render；W4c 的 `rerender=false`、`second_spawn=false`、`journal_events_unchanged=true` 是当前证据。

## 核查结论汇总

| ID | 事实成立？ | 修文档 / 修代码 / 改设计 | 最小改动 | 需要跑的 gate | 需要更新的工件 |
|---|---|---|---|---|---|
| D1 | 成立 | 修文档 | `turn_no` 措辞（`:136`，`:201`，可选 `:269`） | 无 | 设计稿、台账一行 |
| D2 | 成立，且更强：DB/host 都不校验 | 修文档 | `:271`/`:273`/`:309`/`:295` 降级为形状校验 | 无 | 设计稿、台账 `D-S4-11`、S4 计划注记（可选） |
| D3 | 成立 | 修文档 | `:576` 主改；`:411`/`:667`/`:713` 收紧 kind 闭集 | 无 | 设计稿、台账一行 |
| D4 | 成立 | 先修文档；DB 派生 transcript 另立设计 | `:54`/`:201`/`:295`/`:466` + 旧稿 `:67` + ledger/matrix/s10 README | 无 | 两份设计稿、台账 `D-MR-11`、矩阵、s10 README |

## 修复工作项（建议单 agent 一次完成，避免多处文档冲突）

**W1 文档对齐（唯一工作项）**
- 读本文件 + 报告 I0/S1–S7。
- 按上面的 old→new 精确修改：
  - `docs/designs/v24-pg-agent-2026-10-22.md`
  - `docs/designs/v24-db-native-agent-system-2026-10-22.md`
  - `docs/reviews/v24-deviation-ledger-2026-10-23.md`
  - `docs/reviews/v24-conformance-matrix-2026-10-23.md`
  - `v24/s10/README.md`
  - `docs/plans/v24-s4-agent-loop-2026-10-24.md`（仅加注，不重写历史）
  - `docs/investigations/v24-drift-factcheck-2026-10-29.md`（把本文件标记完成）
  - `docs/investigations/deepseek-harness-design-vs-v24-2026-10-29.md`（给 S1/S2/S3/S7 加“doc-only resolved”注记，不改历史结论）
- 遵守设计稿的修订惯例：行内改写在原处，文末/台账记录修订；不要静默改 `[规格]` 而不留痕。
- 不改任何 `v24/sql/**`、`v24/host/**`、`v24/s*/test_*.py`、`v24/load.py`。
- 完成条件：
  1. 上述 old→new 全部落地，且语义与实现逐条一致。
  2. `git diff --exit-code -- v24/sql v24/host v24/s1 v24/s2 v24/s3 v24/s4 v24/s5 v24/s6 v24/s7 v24/s8 v24/s9 v24/s10 v24/s11 v24/s12` 为空（代码零变更）。
  3. `git diff --stat` 只含文档；`git diff --check` 无空白错误。
  4. 台账/矩阵/README 的交叉引用行号正确。
- 不需要跑 closeout gate；在汇报里明确“纯文档，未重跑”。
