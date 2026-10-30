# v13 Stage 40 / S1：`agentctl_observe` 开发计划

## 1. Summary

在现有 stage 39 `fair_claim` 后追加 stage 40 `agentctl`，新增一个 `STABLE SECURITY INVOKER` 函数，并登记唯一的新 SQL 工具 `agentctl_observe`。实现采用**局部追加，不做重构**：复用 `v13_observe` 的整批授权和状态读取、`v13_scheduler_hint` 的既有判断，以及 `events` 中已有的 `workflow/pointer`；包装层只负责请求校验、参数归一化和 JSONB 组装。同步收紧装载与文件放行闭集，补齐直接调用和真实 `parse → advance → sql` 臂的 Fake 验证，最后同笔完成文档收尾。

**本文是实施规格，不是执行报告。** 本次不写代码、不修改文件、不运行 gate、不暂存或提交；下文命令供后续实现者执行。

权威顺序保持：长期循环计划 §2 的用户决定 > 父计划 T0–T7 > 2026-10-03 裁决 > Phase A–D 合同。2026-10-08 数据库-only 约束有效；测试期哈希和比较结果留在进程内，不新增控制文件、投影文件或恢复日志。

**2026-10-08 用户确认（本计划，不重开）：** hints 元素是 `{session_id, hint}` 对象；「没有调用」用事务内 `pg_stat_xact_user_functions` 计数，数不到就红；数据库连接跟 fair_claim，不单独检查 URI 是不是 Unix socket。

**范围边界：**
- 不实现 `agentctl_steer/answer/cancel`，不创建 `controller/1` 或 `controller_surface`。
- 不替换 `v13_named_sql_writer`、`v13_spawn_writer_ok` 或任何 stage 1–39 函数。
- 不修改 envelope、parse、triage、advance、ACL、spawn 或任何驱动器。
- 不提前放行 `agentctl_verbs`、`goal_workflow`、`external_exec`、`ce_map`、`workflow_project`。
- 不运行 `GoalSupervisor.tick`，不接入 LoopX 写路径、真实 provider、wake 或第二推进者。

---

## 2. Current-state analysis

### 2.1 装载与冻结边界

`v13/load.py` 当前有 39 个 SQL 装载项，末项为 `fair_claim/v13_fair_claim.sql`，`STAGE_THROUGH["fair_claim"] = 39`。`files_through()` 按位置截取累计前缀，因此新增项必须同时追加到两个容器尾部，目录名、stage 键和编号必须一致。冻结比较的基线 `fb295ac` 停在 `goal_supervise: 38`；`fair_claim: 39` 是其后已合入的追加，不是基线前缀。

`v13/plan_arm/test_plan_arm.py` 的相关责任分开如下：

| 函数 | 当前责任 | Stage 40 的允许变化 |
|---|---|---|
| `r1_load_append_ok`，`:327` 起 | 检查规范加号行、纯尾追加、键与目录一致、连续编号、目录已跟踪 | 只在函数体内把相对 `fb295ac` 的追加收成恰 `fair_claim/39` 然后 `agentctl/40`；36–38 在基线前缀内，不重算成追加 |
| `r1_phase_d_prefix_allowance`，`:409` 起 | 检查相对 `fb295ac` 的新增跟踪路径、Phase D 已知文件字节及合成负例 | 只在函数体内增加四个精确路径；不增加目录前缀 |
| `r0_source_scope`，`:635` 起 | 保护旧函数字节及模块级 AST | 完全不改 |

两个可修改函数在 `fb295ac6c7459bb98dac57e37883af549d2d8a4c` 中不存在；这不是修改旧测试或模块级常量的许可。`r0_source_scope` 的 `changed existing test` 或模块级差异一旦出现，应停止并修正越界编辑，不能增加豁免。

### 2.2 观察与授权

`public.v13_observe(p_actor uuid, p_ids uuid[])` 已经提供完整的读取基础，见 `v13/observe/v13_observe.sql:43-128`：

1. NULL/空数组直接返回。
2. NULL 元素、重复 ID 分别抛出 `v13: observe id`、`v13: observe duplicate`。
3. 逐 ID 调用 `v13_control_authorized`；任一未授权，整次零行。
4. 全部授权后才读取状态、末事件和两个 pending 布尔。

授权唯一所有者仍是 `v13_control_authorized`，见 `v13/acl/v13_acl.sql:90-118`。非空 actor 只能观察直接子会话；自己、兄弟、祖先、非直接后代、缺失目标和不存在的 actor 均不能通过。包装层不得另写亲缘查询，也不得逐项筛掉未授权 ID 后返回部分结果。

包装层要修补的是**输入合同差异**：把底层会抛出的形状错误提前转成 JSONB 失败结果，而不是改变底层接口。

### 2.3 Hint 与 pointer

- 活体 `v13_scheduler_hint(uuid)` 位于 `v13/govern/v13_govern.sql:517-575`，返回 `run_now | wait | dont_notify`；未知会话仍在 `:526-528` 抛错。包装只能对观察实际返回的 ID 调用它。
- `workflow/pointer` 的唯一写者是 `v13_child_pointer`，见 `v13/workflow_bind/v13_workflow_bind.sql:128` 起。事件载荷键在 `:167-172`；同会话唯一索引在 `:124-126`。
- Stage 40 只查询已有 pointer，不创建缺失 pointer，也不调用其写者。

### 2.4 工具目录与调用链

目录插入受 `trg_tools_guard` 保护。其接口约束见 `v13/schema/v13_core.sql:581-666`；stage 18 的替换体保留 STABLE 分支，并单独处理具名 VOLATILE 写者，见 `v13/spawn/v13_spawn.sql:1600-1687`。

因此，新 SQL 的顺序不能倒置：**函数存在 → ACL 就绪 → tools 插入**。

`v13/catalog/v13_catalog.sql:36-64` 对 STABLE 函数直接检查返回类型和 route 执行权限，不需要具名写者豁免。冻结目录会把裸 handler 名转换为限定名称，并附上函数正文 digest。

实际执行链为：

```text
tools 行
  → v13_tools_catalog_frozen / envelope.tools_catalog
  → typesafe.mock_response → v13_parse
  → v13_resolve_tool_params：通过 stated 带后复制 choice 字符串
  → v13_advance → triage direct → v13_route(action=sql)
  → 动态 SELECT handler(p_sid, params)
  → effects.result + tool/result
```

参数字符串化由 `v13/loop/advance.sql:169-182` 的既有逻辑决定。这是 `ids` 必须接受单 UUID 字符串、`hint` 必须接受 `"true"`/`"false"` 的原因，不应修改参数解析器。

sql 臂见 `v13/plan_arm/v13_plan_arm.sql:771-813`：普通 handler 异常会产生 failed tool effect，不写 `tool/result`；正常返回的 `{ok:false, reason:"shape"}` 则仍是一次成功执行的工具结果。取消异常继续遵守该臂现有的 `query_canceled` 分支。

### 2.5 路由夹具的阻断点

以下是夹具必须满足的前提，不是待修改的运行时：

| 阻断点 | 活体位置 | 夹具处理 |
|---|---|---|
| 调用者存在 ready/claimed effect，提前 waiting | `v13_plan_arm.sql:404-466` | 用直接 spawn 建目标，确认调用者无此类 effect |
| 缺少非空 user/message，fold_empty 导致 reject | `v13_triage.sql:93-95,161-164` | 先写非空用户消息 |
| 根没有 direct override，triage fail-closed | `v13_triage.sql:430-431,454-456,488` | parse 前提交 operator/direct override |
| parse 后追加 override，快照过期 | `v13_plan_arm.sql:359-368` | override 必须早于 parse |
| stated 默认 noul=0.1，参数被省略 | `v13/loop/test_loop.py:126` | 两个 stated 信号均显式设为 0.9 |
| remaining>0，提前入队 judge | `v13_plan_arm.sql:724-736` | parse 后先检查 remaining=0、failed=false |

`:454-456` 与 `:488` 是 fail-closed 的不同返回位置，不应把它们描述成一次调用必然入队两次。

---

## 3. Design

### 3.1 执行索引

Size 表示相对工作量，不是工期承诺。W1–W4 构成同一个实现交付，不能先提交放行规则、以后再补实现。

| 项 | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| W1 | 追加 stage 40，并限定文件准入 | 装载前缀不变；四路径获准；新增负例与旧负例均有效 | `v13/load.py`；`v13/plan_arm/test_plan_arm.py` | 现有 stage 39、两个基线提交可读 | M |
| W2 | 新增只读包装和唯一目录行 | 请求/返回合同、ACL、调用顺序全部符合；无历史函数替换 | `v13/agentctl/v13_agentctl.sql` | 现有 observe、hint、ACL、pointer 合同 | M |
| W3 | 建立安全的一次性测试库与安装比较 | 唯一库加载到 39；哈希前后比较完成；失败路径也只清理本进程创建的库 | `v13/agentctl/setup_db.py`；`v13/agentctl/test_agentctl.py` | W2 | M |
| W4 | 证明直接调用与 sql 臂行为 | 必需断言及补充断言通过；两条指定 gate 均退出 0 | `v13/agentctl/test_agentctl.py`；`v13/agentctl/README.md`；`v13/plan_arm/test_plan_arm.py` | W1–W3；四个新路径已跟踪 | L |
| W5 | 完成证据和历史勘误 | README 记实跑；矩阵/台账追加；指定章节只追加已裁说明 | README；§4 列出的五份文档 | W4 两条 gate 通过 | S |
| W6 | 复核最终提交闭集 | 最终内容重跑两 gate 通过；冻结文件无越界差；同笔提交全部交付 | `v13/agentctl/test_agentctl.py`；`v13/plan_arm/test_plan_arm.py`；§4 文件闭集 | W5 | S |

### 3.2 生产组件与接口

#### 新函数

接口形状：

```text
public.v13_agentctl_observe(p_sid uuid, p_spec jsonb) → jsonb
```

| 属性 | 固定设计 |
|---|---|
| 实现类型 | PostgreSQL PL/pgSQL 函数；不新增类型、服务或辅助 SQL 函数 |
| 易变性 | `STABLE` |
| 安全上下文 | `SECURITY INVOKER`，不得使用 DEFINER |
| NULL 调用 | 不声明 STRICT；SQL NULL 的 `p_spec` 必须进入形状失败分支 |
| search_path | 恰为 `pg_catalog, public` |
| 属主 | 保留安装者属主；不创建角色，不改属主到 `v13_spawn_owner` |
| 显式 EXECUTE | 撤销 PUBLIC，只授予 `v13_route`；不新增其他角色授权 |
| 状态 | 仅调用期间的 UUID 数组、hint 布尔和三个 JSONB 数组 |
| 执行模型 | 同步，在当前数据库语句/事务中读取；无后台任务、等待器或外部 IO |
| 既有调用方 | 不修改任何既有调用方；由 tools/envelope/sql 臂动态发现 |
| 新调用点 | `test_agentctl.py` 的直接调用夹具，以及该文件构造的 parse→advance 夹具 |

`p_sid` 原样传给 `v13_observe`，不从 `p_spec` 提取 actor，不把不存在的 actor 转成 NULL。

**SQL NULL actor 的既有语义不另行改写：** `v13_control_authorized(NULL, target)` 会咨询 `v13_control_operator()`。直接 SQL 调用保留这一行为；路由夹具始终传入非空根 session UUID。即使执行角色是 operator，非空 actor 仍按直接父会话规则判断，自身仍被拒绝。

#### 唯一 tools 行

| 列 | 值 |
|---|---|
| `name` | `agentctl_observe` |
| `description` | `Observe authorized child sessions, optional scheduler hints, and existing workflow pointers.` |
| `kind` | `sql` |
| `handler` | 裸名 `v13_agentctl_observe` |
| `enabled` | `true` |
| `param_spec` | 只有 `ids`、`hint` |

`param_spec` 的文本固定为：

| 参数 | `question` | `stated` |
|---|---|---|
| `ids` | `Which session UUID or UUIDs should be observed?` | `Does the user specify the session UUIDs to observe?` |
| `hint` | `Should scheduler hints be included?` | `Does the user explicitly request scheduler hints?` |

不添加 `options`、`required`、身份字段或其他键。`ids` 必填由 handler 执法；不借修改 judgment template 表达。

#### SQL 文件语句顺序

`v13/agentctl/v13_agentctl.sql` 按以下顺序组织：

1. `BEGIN`。
2. 普通 `CREATE FUNCTION public.v13_agentctl_observe`，不是替换历史函数。
3. 对该精确签名撤销 PUBLIC EXECUTE。
4. 对该精确签名授予 `v13_route` EXECUTE。
5. 插入上述唯一 tools 行。
6. 添加该函数的说明 COMMENT，注明只读、整批隐藏、无 pointer 写入。
7. `COMMIT`。

不得在此文件插入 probe policy、产品 policy 或 thresholds。不得更新已有 tools 行，包括 `spawn_subsession`。

安装不是重复执行型 upsert：按累计装载契约，在未安装 stage 40 的库上执行。任何创建、授权或目录守卫失败应使整份安装事务回滚，不捕获后继续。

### 3.3 请求、返回与运行时数据流

#### 请求闭集

`p_spec` 必须是 JSONB object，排序后的键集只允许：

- `["ids"]`
- `["hint","ids"]`

复用 `v13_json_keys(jsonb)`，见 `v13/control/v13_control.sql:102-106`；不要另写键集提取逻辑。

| 字段 | 接受 | 拒绝 |
|---|---|---|
| `ids` | 单个规范 UUID 字符串；非空 UUID 字符串数组 | 缺失、JSON null、空数组、非字符串元素、嵌套数组、对象、数字、布尔 |
| UUID 文本 | `v13_canonical_uuid(text)` 接受的小写 8-4-4-4-12 | 大写、带空白、无连字符、其他 PostgreSQL 可能宽松接受的 UUID 写法 |
| 重复 ID | 不接受 | 不去重，不排序修复 |
| `hint` | 缺省、JSON boolean、精确字符串 `"true"`/`"false"` | JSON null、其他字符串、数字、数组、对象 |

字符串化的 JSON 数组，例如 `ids` 是字符串 `'["…"]'`，不二次解析，按非规范 UUID 拒绝。`hint` 不做 trim、大小写折叠或 PostgreSQL 宽松 boolean 转换。

#### 形状失败

所有可在已类型化参数内判定的形状失败，返回恰好：

```json
{
  "schema_version": 1,
  "ok": false,
  "reason": "shape",
  "rows": [],
  "hints": [],
  "pointers": []
}
```

该路径不得调用 `v13_observe`、`v13_scheduler_hint` 或读取 pointer。

无效 JSON 文本在转换成 JSONB 前的错误、传入非 UUID 文本转换 `p_sid` 的错误，不属于函数内可转换的形状失败；不承诺吞掉 PostgreSQL 参数转换错误。

#### 成功返回

成功顶层键恰为 `schema_version, ok, rows, hints, pointers`，不带 `reason`：

```json
{
  "schema_version": 1,
  "ok": true,
  "rows": [],
  "hints": [],
  "pointers": []
}
```

**`rows`：** 每项恰为以下 11 个活体列名，不改名、不删 NULL 字段：

```text
ordinal, session_id, parent_session_id, status, spawn_kind,
is_terminal, turn_no, last_event_seq, last_event_type,
pending_human, cancel_pending
```

UUID 序列化为文本；数值和布尔保留 JSON 类型。无事件时保留 `last_event_seq=-1`、`last_event_type=null`。顺序按 `ordinal`，即调用者输入顺序。

**`hints`：** 本计划固定数组元素的序列化形状，便于消费者按 ID 对齐：

```text
{session_id: UUID文本, hint: "run_now" | "wait" | "dont_notify"}
```

只有两个键。请求 hint 时，每条已返回观察行恰对应一个元素，顺序同 `rows`；否则为空数组。

**`pointers`：** 每项恰为：

```text
{session_id: UUID文本, event_id: UUID文本, seq: JSON整数, payload: 原始JSONB}
```

只从已返回 session ID 对应的 `events` 中读取 `type='workflow/pointer'`。`payload` 原样返回，不重建其中字段。按观察行 ordinal、事件 seq、event_id 排序；缺失 pointer 不生成占位项。

#### 算法与调用顺序

1. 单独检查 `p_spec` 是否为 object，再调用键集 helper。
2. 单独检查 `ids` 类型；只有确认是数组后才展开或取长度。
3. 将单字符串归一化为一元素序列；逐元素验证字符串类型和 canonical UUID，再转换为 UUID。
4. 检查非空与重复。不要在遍历中逐次搜索已积累数组，采用集合计数比较，避免无谓的平方级去重检查。
5. 校验 `hint` 并归一化为布尔。**上述全部校验完成前，不调用观察函数。**
6. **仅调用一次** `v13_observe(p_sid, normalized_ids)`，按 ordinal 聚合并物化为本地 JSONB 变量；聚合无行时显式归一为 `[]`。
7. 观察结果为空，立即返回空成功，不执行 hint 或 pointer 查询。
8. hint=true 时，从物化结果提取 session ID，调用 `v13_scheduler_hint`；不得重新使用原请求数组枚举。
9. 从同一物化结果提取 ID，查询已有 pointer。
10. 返回成功对象。

使用带 `ORDER BY` 的聚合组装数组，不反复拼接不断增长的 JSONB 数组。包装层额外空间随请求和输出大小线性增长；重复检查和排序成本通常为 O(n log n)，底层观察与 hint 的查询成本沿用既有函数。不给请求偷偷增加数量上限或截断结果。

**执行安全：** JSON 类型检查与危险展开/转换必须分成独立控制流步骤，不依赖 SQL `AND/OR` 的求值顺序。UUID helper 的结果必须明确为 true 才允许 cast，不能让 SQL NULL 穿过校验。

#### 状态、并发与重复调用

- 直接调用不写表、不推进 `sessions.next_seq`、不持有显式行锁或咨询锁。
- STABLE 读取沿用调用语句的快照；并发提交的新事件可能到下一次调用才可见。
- 不维护缓存、游标、watermark、receipt 或“上次观察”状态。
- 重复调用在数据库未变化时返回相同内容；数据库变化后的不同结果是正常快照差异。
- 响应丢失后可重新读取；不存在需要恢复的包装层持久状态。
- 调用失败或取消时不生成局部成功结果。依赖函数的真实异常原样传播，不用 `WHEN OTHERS` 转成 shape 或空成功。
- 经 advance 执行时，外层 sql 臂仍会写 `turn/route`、tool effect 和成功时的 `tool/result`；这不违背 **handler 自身零写**。测试必须分开这两个窗口。

### 3.4 装载与精确路径放行

#### `v13/load.py`

只增加两条尾项：

- SQL 文件：`V13_ROOT / "agentctl" / "v13_agentctl.sql"`
- stage 映射：`"agentctl": 40`

不改注释、导入、已有行、`files_through`、`run_psql` 或 `load_stage`。

#### `r1_phase_d_prefix_allowance()`

在函数体内定义 Stage 40 的精确集合：

```text
v13/agentctl/v13_agentctl.sql
v13/agentctl/setup_db.py
v13/agentctl/test_agentctl.py
v13/agentctl/README.md
```

保留原有三个 `prefixes`，不追加 `"v13/agentctl/"`。路径接纳条件为：

- 原先允许的三个前缀及其既有 known/fresh 规则；或者
- 上述四个精确路径之一。

既有 `fresh_ok` 中的 `accept_unattended.py` 继续保留。Phase D 已知文件的字节比较、README 追加规则和旧测试比较逻辑不放宽。完整 Stage 40 交付检查还须确认四个路径都在 tracked 集合中。

#### `r1_load_append_ok(...)`

保持原签名与现有纯尾追加算法，在函数体内明确限定本次获准的追加。

已核对：`fb295ac6c7459bb98dac57e37883af549d2d8a4c` 的 `STAGE_THROUGH` 末项是 `goal_supervise: 38`，不是 39，也不包含 `fair_claim`。`workspace_admit` / `frontier_gap` / `goal_supervise`（36–38）在这份基线前缀里，必须作为前缀保持字节一致，不得把它们再算进追加项。

本次交付后，相对该基线的追加恰为两项，顺序不可换：

| 目录/stage 键 | SQL 文件 | 编号 | 属于 |
|---|---|---:|---|
| `fair_claim` | `v13_fair_claim.sql` | 39 | 已在 HEAD；必须保留 |
| `agentctl` | `v13_agentctl.sql` | 40 | 本次里程碑 |

不要断言「追加项等于 36–40 那五行」。那会把基线内的 36–38 误判成缺失追加。也不要把任意规范新目录自动视为获准：合法的 stage 41 追加也必须拒绝。

继续保留：
- 不允许删除行或在容器外新增代码。
- 规范行正则、目录与键匹配、SQL 路径/键/编号唯一。
- 编号连续及 stage 顺序检查。
- 追加目录必须已被跟踪；Stage 40 的 SQL 精确路径也必须在 tracked 集合内。
- diff 加号行与解析出的追加项逐项对应。

#### 合成测试

全部在内存中构造，不落临时源文件。保留原有负例，并增加：

路径类走 `r1_phase_d_prefix_allowance` 里的 `allow()`，用内存中的 tracked 集合，不落临时文件。装载类走 `r1_load_append_ok`，输入是相对 `fb295ac` 的合法追加对再改一处。第 1 项两个函数都要过。不要把路径拒绝只写进 load 函数，也不要把 load 拒绝只写进 `allow()`。

1. 合法 `fair_claim/39` + `agentctl/40`，四路径都在 tracked：两个函数都接受。
2. `allow()`：`v13/not_allowed/x.py` 拒绝。
3. `allow()`：`v13/agentctl/extra.py` 拒绝。
4. `allow()` / tracked：只有 README、SQL 未跟踪，拒绝。
5. `r1_load_append_ok`：`"agentctl": 40a,` 按非规范行拒绝，不执行、不解析成 Python。
6. `r1_load_append_ok`：agentctl 编号为 41，按跳号拒绝。
7. `r1_load_append_ok`：agentctl 使用其他 SQL 文件名，拒绝。
8. `r1_load_append_ok`：SQL 目录与 stage 键不一致，拒绝。
9. `r1_load_append_ok`：合法对之后再追加任一未来 stage，即使形式合法，拒绝。
10. `allow()`：用闭集外路径替换任一必需文件，拒绝。

新增负例以合法 stage 40 输入为起点，每次只改变一个条件，并检查对应失败原因，避免所有负例仅因“缺少 stage 40”而偶然通过。

### 3.5 一次性测试库、安装证明与 harness

#### `v13/agentctl/setup_db.py`

沿用 `v13/fair_claim/setup_db.py` 的生命周期，不调用旧 `v13/observe/setup_db.py.prepare()`，因为后者会 DROP 固定名字的库。

保留以下模块职责与接口：

| 名称 | 责任 |
|---|---|
| `DB` | 进程内生成一次的 `ll_agentctl_{pid}_{hex}`；hex 为 `secrets.token_hex(3)` |
| `CREATED` | 初始 false，仅 CREATE DATABASE 成功后设为 true |
| `probe_extension(server) → None` | 检查 `stannum`、`pg_jsonschema`，缺失即失败 |
| `name_exists(server) → bool` | 只检查数据库是否已存在 |
| `main() → int` | 检查名字、创建新库、累计加载到 `fair_claim`，不应用 stage 40 |

必须拒绝 `agent_v13_` 前缀及既有保护库名；同名库已存在就退出，不 DROP、不接管。存在性检查和 CREATE 之间若发生重名竞争，CREATE 失败时 `CREATED` 保持 false。

测试主程序从 setup 开始就进入清理保护范围，避免加载或连接失败后遗留测试库。所有连接关闭后，只有 `setup_mod.CREATED` 为 true 才能 DROP 本次生成的 DB；清理失败单独报告并使 gate 失败，不输出成功结论。

连接方式与 `v13/fair_claim/setup_db.py` 相同：`get_server()` 的本地 URI，不另写 TCP/Unix 判断。不调用 `poison()`，不使用 HTTP 探针或真实 provider。测试进程不为此打开网络套接字。

#### 安装前后比较

`test_agentctl.py.main()` 的顺序固定为：

1. 源码和文件闭集检查。
2. setup 加载 stage 1–39。
3. 读取安装前基线，保存于内存；提交读取事务。
4. 用 `run_psql` 应用 `v13_agentctl.sql`。
5. 新语句读取安装后基线并比较。
6. 通过安装比较后，才建立 probe policy 和行为夹具。

安装比较覆盖：
- 已存在的 `public.v13_*` 函数及 `public.v_goal_tree`：以精确签名为键比较 `pg_get_functiondef` 的 SHA-256，并比较属主、ACL、安全属性。
- 尤其包含 observe、authorized、scheduler_hint、child_pointer、advance、两个目录守卫谓词、spawn、claim 和 fair_claim；不能仅检查 advance 一项。
- 新增函数集合恰为 `public.v13_agentctl_observe(uuid,jsonb)`。
- tools 新增集合恰为一个 `agentctl_observe`；已有行逐项不变。
- 允许既有 tools 触发器使 `v13_tools_meta.revision` 增加 1；`candidate_generation_revision` 不变。
- `v13_policies`、`v13_route_policies`、thresholds 不变；没有产品 controller 行。
- 没有新增表、列、索引或触发器；没有安装期新增 events/effects。

字节冻结直接复用 `v13.plan_arm.test_plan_arm.r0_source_scope()`，不复制出另一套宽松判断。由于该函数读取跟踪集合，四个新文件应在运行 **两条 gate 之前** 就按路径暂存。

#### 测试复用与新助手

- 从 `v13.loop.test_loop` 复用 cursor-only 的 `mock_from_needed`、`set_mock`；不调用它的 setup/main、`new_session`、`claim_pinned` 或 `poison`。
- 新 harness 使用绑定本次 DB 的连接及清理逻辑，不能复用绑定固定库名的旧 `connect()`。
- `check`、savepoint 错误捕获、哈希和直接读取窗口按 observe/fair_claim 的小型模式实现。本地保留这些少量助手，是为了隔离 DB 与清理所有权，不另建跨 stage 测试框架。

新测试助手的职责固定为：
- `freeze_probe_policy(cur)`：只负责下节的测试政策。
- `prepare_routed_case(cur, with_override)`：建根、消息、直接子会话及可选 override，不 parse、不 advance。
- `parse_observe_case(cur, root, ids_choice, hint_choice)`：填完整 mock 并调用 parse。
- `observe_direct(cur, actor, spec)`：直接调用新函数；SQL NULL spec 单列用例，不能与 JSON null 混同。
- `function_call_counts(cur)`：读取指定函数的当前事务调用数。
- `snapshot_read_window(cur)`：读取直接调用窗口的业务行与元数据，用于前后比较。

#### “没有调用”的证明方式

不能只比较空返回值，也不能替换冻结函数为 spy。

每个测量连接用会话级 `SET track_functions = all`，不用 `SET LOCAL`。`pg_stat_xact_user_functions` 只计当前事务，而且只在这个 GUC 开着时计数。政策 `COMMIT` 会清掉 `SET LOCAL`；提交前的探针不能给后面的事务武装。每次测量事务里、被测调用之前，再跑一次可回滚探针。探针看不到这些 PL/pgSQL 的 calls 差，gate 硬失败，不降级成只看结果，也不替换冻结函数做 spy。

计数对象：
- `v13_agentctl_observe`
- `v13_observe`
- `v13_scheduler_hint`
- `v13_child_pointer`
- `v13_append_event`

参考值计算和夹具写入都在计数窗口外。

### 3.6 路由夹具：精确步骤与结果

#### 测试政策

`freeze_probe_policy(cur)` 在 stage 40 安装验证完成后执行：

1. 插入 `agentctl_observe_probe` version 1，默认 draft。
2. 复制 `default` version 2 的全部 thresholds，不复制 version 1。
3. 追加四条 `band_no=1, lo=0.60, hi=Infinity, action=pass`：

| signal |
|---|
| `param::agentctl_observe::ids` |
| `stated::agentctl_observe::ids` |
| `param::agentctl_observe::hint` |
| `stated::agentctl_observe::hint` |

4. 检查其带集恰等于源带集加这四行，没有 `triage` 带。
5. UPDATE 状态为 frozen；此后不追加阈值。
6. 可以提交该测试夹具政策，便于后面的事务看见它。它随一次性数据库销毁，不进入生产 SQL。提交不是 ACL 证明的前提：`actl_acl_closed` 留在同一条连接上，属主建好子会话后 `SET ROLE v13_route`，调用结束 `RESET ROLE`。不另开第二条连接。若提交了，测量事务必须按上一节重新武装计数，不能复用提交前的探针。

#### `actl_observe_routed` 正例

分别用 hint choice `"true"` 和 `"false"` 建立独立根夹具，避免上一例的 effect/事件影响下一例。

1. `v13_open_session` 的 spec 恰为：
   `{"route_policy_name":"agentctl_observe_probe","version":1}`。
2. 根上通过 `v13_append_event` 写一条非空 `user/message`，其 `payload.text` 去空白后非空。
3. 直接调用 `v13_spawn_subsession`。参数键恰为 `children` 与 `schema_version`（`v13/spawn/v13_spawn.sql:331-334`），`schema_version` 为数字 1，`children` 为非空数组。不要加第三个参数键。数组恰一项，元素走既有 `v13_spawn_children` 合同：新的 `tool_call_id` 与非空 `task`。成功返回的键是 `replay_kind, parent_session_id, children, reservation`（`:459-463`），返回里没有 `schema_version`。从 `children[0].session_id` 取目标 UUID。不要拿参数键集去断言返回。`next_seq < 1` 时函数 RAISE `v13: spawn requires prefix`（`:347-348`），所以第 2 步的 `user/message` 必须留在 spawn 之前。
4. 检查调用者根上没有 ready/claimed effect；不通过创建后再清掉 effect 绕过此条件。
5. 在 parse 前调用 `v13_submit_override`，载荷恰为：
   `{"intent":"direct","reason":"","schema_version":1,"source_principal":"operator"}`。
6. 用 `mock_from_needed` 填齐其余问题，并显式覆盖：
   - intent choice：`sql_answer`，confidence 0.9，probabilities 含该键。
   - tool choice：`agentctl_observe`，confidence 0.9，probabilities 含该键。
   - gate_action noul：0.9。
   - gate_off_topic noul：0.1。
   - risk score：0.5，confidence 0.9。
   - 两条 `stated::agentctl_observe::*`：`{"type":"noul","noul":0.9}`。
   - ids param choice：子 UUID 文本，confidence 0.9，probabilities 含该 UUID 键。
   - hint param choice：精确字符串 `"true"` 或 `"false"`，confidence 0.9，probabilities 含该字符串键。
7. 在任何 `v13_parse` 之前，按 `v13/spawn/test_spawn.py:136-137` 做会话级设置，不写进生产 SQL：
   `set_config('typesafe.provider', 'mock', false)` 与 `set_config('typesafe.model', 'jev-mock', false)`。
   活体 `v13_parse` 会调用 `v13_judgment_envelope`（`v13/resolve/v13_resolve.sql:665`）。其替换体第一步就调 `v13_guc_required`（`v13/filter/v13_filter.sql:485-489`）。缺任一 GUC 时 `v13_guc_required` RAISE `V3002`（`v13/envelope/v13_envelope.sql:321-327`），到不了 `remaining`。不要加 `endpoint` 或 `api_key`。然后设置非空 `typesafe.mock_response`，再调用 `v13_parse(root)`。
8. 在 Python 中检查返回 JSONB 的 `remaining == 0`、`failed is false`、`abandon is false`，并确认冻结政策为 probe/1。
9. 下一条变更调用立即执行 `v13_advance(root, 整份parse结果)`；不重建 snap，不在中间追加事件。

正例必须证明：
- advance 返回 `progressed`。
- `turn/route` 的 `action=sql`、`tool=agentctl_observe`。
- 新 tool effect 恰一条，状态 succeeded，error 为 NULL。
- effect 的 `request.params` 恰为子 UUID 字符串和 hint 字符串，不是 `{}`，也不是把 ids 包成数组。
- `effects.result` 与对应 `tool/result.payload.result` 相等，观察到的是该子会话。
- 根上保留恰一条 `goal/override`。
- 没有 human effect；没有新增 `workflow/pointer`。
- 子会话状态、事件和 `next_seq` 不因 handler 改变。

#### 无 override 负例

使用同一准备顺序，但省略第 5 步；其他 mock 和 parse 条件保持正确：

- advance 返回 `waiting`。
- 根上出现 `reason=triage_fail_closed` 的 ready human effect。
- 没有 agentctl_observe tool effect 或它的 `tool/result`。
- handler 调用计数增量为 0。
- 不修改 triage，不增加 triage 带，也不使用非根调用者绕开。

此例命名为 `actl_routed_without_override`，属于 `actl_observe_routed` 的配套反证。

#### 路由形状失败

再建独立根，保留 override，把 ids choice 改为非 UUID 字符串：

- parse 仍须 `remaining=0`、`failed=false`；criteria 为 NULL 不拒绝该自由字符串，见 `v13/resolve/v13_resolve.sql:590-594`。
- advance 返回 `progressed`。
- tool effect 是 succeeded，result 为精确 shape 失败对象，且存在 `tool/result`。
- `v13_observe`、hint 调用增量均为 0。

命名为 `actl_shape_routed`。它直接证明“业务形状失败不是 sql 臂执行失败”。

### 3.7 验证设计：直接调用、错误与边界

直接调用测试不借 advance 生成结果。夹具准备与测量窗口严格分离；窗口内只调用观察函数。

| 断言名 | 必测输入/场景 | 必须证明 |
|---|---|---|
| `actl_catalog_rows` | 安装前后 tools 差；冻结目录 | 新 SQL 名恰为一个；行值正确；冻结 handler 为限定名且有 digest；param_spec 只有两键且无 options |
| `actl_actor_gate` | 父→子；多子逆序；自身、兄弟、祖先、孙辈、缺失目标、缺失非空 actor；合法+非法混合 | 正例保持输入顺序；拒绝一律空成功；混合整批隐藏；随后合法单 ID 仍可读。同一计数窗口里，未授权、自身、缺失目标这三例 `v13_observe` 调用数 = 1；形状失败 = 0；一次授权成功 = 1。本地直接返回空成功、不调用 `v13_observe`，算失败 |
| `actl_guard_closed` | 具名写者查询、ACL、目录拒绝、形状负例 | observe 不在 named writer 豁免；spawn 原例外仍成立；缺失 handler 的目录插入被拒；原守卫未替换 |
| `actl_observe_no_pointer` | 没有 pointer；已有 pointer；其他根的 pointer | 不自动创建；已有行准确返回；非返回 ID 的 pointer 不泄漏；写者调用增量为 0 |
| `actl_observe_no_hint_on_empty` | 未授权、自身、合法 UUID 但目标不存在，均 hint=true；所有形状失败 | hint 调用增量为 0；shape 时 observe 增量也为 0 |
| `actl_observe_routed` | §3.6 两个正例及配套反证 | 确实经过 parse、route 和既有 sql 臂，而非 Python 直调伪装 |
| `actl_spawn_enabled_true` | 安装前、安装后、行为测试后 | `spawn_subsession.enabled` 始终 true，整行未被安装修改 |
| `actl_acl_closed` | 同一连接上 `SET ROLE`，不另开连接 | route 可执行；PUBLIC 无直接 EXECUTE；recall/resolve/worker/spawn_owner 无新权限。`v13_route` 的真调用必须是授权子会话、`hint=true` 的合法 spec，返回 `ok=true`、一行、一个 hint 元素。形状失败只证明包装的 EXECUTE，不算这条。recall 调用为 42501。`v13_advance` 是 INVOKER（`v13/plan_arm/v13_plan_arm.sql:332` 起无 DEFINER），属主跑路由夹具不能代替这次 `SET ROLE` |
| `actl_shape_closed` | 下列完整形状矩阵 | 精确失败 JSONB，无异常，无底层观察/hint 调用 |
| `actl_hint_returned_only` | hint 缺省、两种 false、两种 true；多个授权 ID | false 类零 hint 调用；true 类每返回 ID 一次，值等于既有 hint 函数，顺序同 rows |
| `actl_hint_unknown_raises` | 直接调用 `v13_scheduler_hint(不存在UUID)` | 保留 `v13: unknown session <uuid>` 异常，不经包装吞掉 |
| `actl_read_zero_write` | 正常、空成功、shape、重复读取 | 业务行、next_seq、tools revision 不变；观察调用不发事件 |
| `actl_frozen_unchanged` | 源码冻结及安装前后函数比较 | 历史定义、ACL、属主、守卫及冻结文件未改变 |
| `actl_no_io` | 新函数的 `pg_get_functiondef` | 不含禁止 IO、写者、claim、wake 或锁类号；不含动态执行或异常吞错路径 |

**形状矩阵至少包括：**
- SQL NULL spec、JSON null spec、数组/字符串/数字/布尔 spec。
- 空对象、只有 hint、额外键；额外键包括 `source_principal`。
- ids 为 JSON null、空数组、数字、布尔、对象。
- 数组中 NULL、数字、布尔、对象、嵌套数组。
- 非 UUID、空文本、大写 UUID、带首尾空白 UUID、无连字符 UUID。
- 重复规范 UUID。
- hint 为 JSON null、数字、数组、对象、`"TRUE"`、`"False"`、`"yes"`、空字符串。
- 合法单 UUID 与一元素数组结果等价。
- 多元素合法数组保持输入顺序，不按 UUID 排序。

**pointer 正例的准备：** 在测量窗口之前调用现有 `v13_child_pointer`。`p_root` 用 `v13_plan_map_root(child)`。`p_up_to_seq` 传 `0`。空根上 `max(seq)` 是 NULL，函数会 RAISE `v13: workflow pointer: payload`（`v13/workflow_bind/v13_workflow_bind.sql:148-150`）。不要对没有事件的根取 `max(seq)`。若改用 `max(seq)`，必须先在根上追加一条事件，再取非负值。`todo_uuid` 只是格式合法标识，不据此声称已展开工作流。记录四个输出字段及载荷后再开始观察窗口；不得用 events 直插绕过唯一写者，也不得在 wrapper 中调用写者。

**零写证明：** 对夹具范围内的 sessions、events、effects、artifacts、latches 做有序行快照，并检查 tools/meta 和政策行不变。比较必须包含更新，不只检查行数；尤其要比较 `sessions.next_seq`。重复观察的 JSONB 与行快照均应一致。

**禁止记号检查仅针对新生产函数正文：**

```text
dblink, pg_net, lo_import, lo_export, pg_read_file, pg_write_file,
COPY PROGRAM, v13_append_event, v13_child_pointer,
v13_claim, v13_claim_fair, v13_wake_is_satisfied_v1, 13002, 13003
```

按大小写归一及空白归一检查 IO 词组。测试文件可以包含用于断言的禁词字符串，不能因此把扫描范围扩大后误判。

### 3.8 文档收尾

README 在首次 gate 前必须已经存在并跟踪，包含接口、数组顺序、权限、零写边界和 gate 命令，但状态标为“未实跑”。两条 gate 通过后才补实际运行日期、退出码、检查数量及清理结果。

不得出现 stage 42 的完整声称句；Stage 40 只能说明授权范围内的 PG 只读工具及其 Fake 路由证明，不声称 CE 进程 wait/poll、wake、目标工作流或无人值守已实现。

| 文档 | 追加内容 |
|---|---|
| 覆盖矩阵 | 新增 Stage 40 小节及一行，保持 `#｜条文｜状态｜测试落点｜缺口`；按所给快照下一号为 86，实施时若已有追加则确定性使用当前最大数字号+1；只记录实跑结果 |
| 偏差台账 | 新增 Stage 40 交付边界行及 `S40-D2` 勘误行；不改两处历史 F22 记录 |
| parity R6 | 在 §6 表之后追加指向 R6 `:236` 的 D-2 勘误：原 enabled=false 描述过时，活体为 true，本次保持 true 而非交付“启用”；保留原句 |
| 设计 §7 | 追加“已裁”说明，逐项对应 D-1–D-5；不删除五个原问题 |
| 设计 §8 | 追加 OQ-J1→D-6、J2→D-7、J3→D-8、J4→D-9 的映射；注明裁决不等于本 stage 实现 |
| 调查 §8.2 | 追加 D-A 已裁甲、否决乙起步甲收敛及权威模式开关的说明 |
| 调查 §8.4 | 对相关权威归属、外部身份方向、投影/store 选择追加已裁说明；不把 I1–I4 等未决项一并标成关闭 |

已裁说明引用 2026-10-03 裁决，并说明 2026-10-08 父计划不采用历史 file sink、stage 45 明确不交付。不得回写裁决文件，也不得把历史描述改成“从未裁过 file sink”。

D-2 勘误不涉及 parity R11 `:240`；正文消费属于以后 S2 的独立完成条件，不是 Stage 40 的阻塞项。

### 3.9 Tradeoffs

- **薄包装而非修改 observe：** 新工具需要非抛错形状合同，旧 observe 的重复/NULL 异常仍是已验证接口。
- **INVOKER 而非 DEFINER：** 既有 route 读权限已经覆盖依赖，不需要增加权限边界或专用属主。
- **一次观察物化而非三次重复查询：** 授权结果成为 rows/hints/pointers 的共同输入，避免部分泄漏和重复工作。
- **shape 返回对象而非宽泛异常捕获：** 既满足 sql 臂的成功记账，又保留真实依赖故障的可见性。
- **测试政策而非提前冻结 controller：** Stage 40 证明路由链，不提前封版尚未完整的产品工具面。
- **沿用既有快照而非缓存/持久投影：** 重读即恢复，不新增需要治理的状态。
- **精确路径而非目录前缀：** 下一 stage 必须另行获得准入，不能借 Stage 40 放行后续实现。

---

## 4. File-by-file impact

本次实现的文件闭集为以下 **11 个文件**。本计划文件本身不进这个闭集，也不随里程碑提交。

| 文件 | 变更 | 原因与依赖 |
|---|---|---|
| `v13/agentctl/v13_agentctl.sql` | 新增一个函数、其 ACL、一个 tools 行及 COMMENT | W2；依赖累计 stage 39 |
| `v13/agentctl/setup_db.py` | 新增唯一测试库生命周期与加载到 39 的 setup | W3；参考 fair_claim，不调用旧固定库 setup |
| `v13/agentctl/test_agentctl.py` | 新增安装比较、直接调用、函数计数、角色、路由及静态断言 | W3/W4；依赖 SQL、setup 和修改后的闭集守卫 |
| `v13/agentctl/README.md` | 新增接口与边界说明；绿后追加实跑记录 | 首轮 gate 前必须跟踪；证据依赖 W4 |
| `v13/load.py` | 仅两个容器尾部追加 agentctl/40 | W1；与新目录同笔 |
| `v13/plan_arm/test_plan_arm.py` | 仅修改 `r1_phase_d_prefix_allowance`、`r1_load_append_ok` 函数体 | W1；保留所有其他函数与模块级 AST |
| `docs/reviews/v13-control-plane-conformance-matrix-2026-09-26.md` | 追加 Stage 40 行 | W5；依赖两条 gate 实跑 |
| `docs/reviews/v13-control-plane-deviation-ledger-2026-09-26.md` | 追加交付边界及 D-2 勘误 | W5；F22 原文不动 |
| `docs/reviews/v13-control-plane-parity-rpce-loopx-2026-09-26.md` | 追加 R6 勘误 | W5；R6 原句、R11 不动 |
| `docs/designs/v13-agent-control-minimal-form-2026-10-02.md` | §7/§8 追加已裁注记 | W5；不改历史问题 |
| `docs/investigations/v13-phase-d-reopen-reference-survey-2026-10-02.md` | §8.2/§8.4 追加限定范围的已裁注记 | W5；不将延期项标成实现 |

以下仅为依赖、保持不变：父计划、裁决记录、长期循环计划、stage 1–39 SQL、旧 observe/fair_claim 测试与 setup、所有 driver 文件。尤其不能为了消除旧 `test_fair_claim.py` 的 stage 数量假设而顺手修改它；本里程碑指定 gate 是新 agentctl gate 与 plan_arm gate。

---

## 5. Risks

| 风险 | 处置与停止条件 |
|---|---|
| 对非 object/非 array 直接展开，或 cast 非规范 UUID，意外 RAISE | 分段类型检查；完整 shape 矩阵必须证明底层调用数为 0 |
| 授权结果为空却按原请求取 hint/pointer | 观察结果先物化，空结果立即返回；使用调用计数和混合授权负例 |
| parse 参数被省略、triage 提前返回或快照 stale | 固定夹具顺序；检查 stated、remaining、实际 request.params；不得改冻结运行时 |
| 新工具全局可见，被误认为所有政策都已支持其参数路由 | 不改 default/2；仅 probe policy 证明路由；README 明确产品政策未交付 |
| 工具安装使旧快照失效 | 沿用 tools revision 检测；旧快照返回 stale 后按既有流程重 parse，不做兼容旁路 |
| 闭集守卫被扩大或负例虚假通过 | 精确四路径、获准尾段、单因素负例及失败原因检查 |
| 测试失败后误删已有库 | 生成唯一名字；CREATE 成功才置 CREATED；不预先 DROP；finally 只清理本进程创建的库 |
| 把外层 sql 臂写入误判为 handler 写入 | 直接调用用于零写证明；路由用例另行检查既有 effect/event 记账 |
| 文档提前标绿、把 true 保持写成新能力 | 两 gate 通过后再收尾；最终状态再次重跑；保留历史原句 |

**实施环境核验项，不是新的产品问题：**
- 两个基线提交必须能由 Git 读取：`fb295ac6c7459bb98dac57e37883af549d2d8a4c` 与 `78e77c710bf06a0a1c771b822a3837c5db4c66d0`（`r1_phase_d_prefix_allowance` 已引用，`v13/plan_arm/test_plan_arm.py:414`）。缺失则停止，不能换成 HEAD。
- 导入 cursor-only 测试助手不得触发旧 setup/main；先做导入检查。
- PostgreSQL 必须能提供上述事务局部调用计数；不能观测就报告验证环境阻塞。
- 连接方式与 fair_claim 相同，不另加 URI 协议检查；不调用 `poison()`，不改用 TCP 探针或真实 provider。
- 所给行号来自 scaffold 的核对结果；实施时以同名函数/章节为锚验证位置漂移，不借此重新选择实现路径。

无业务表 schema 迁移，也不转换既有事件。安装事务失败可整体回滚；已交付后的修正必须另走获批前向追加，不重写历史 stage 或冻结政策。

---

## 6. Implementation order and verification

### 6.1 实施顺序

1. **确认施工基线。**  
   确认工作区没有需保留但会混入本提交的修改；确认 stage 39 尾部、两个 Git 基线及冻结文件。只记录本次文件闭集，不改任何旧 gate 来适配。

2. **完成 W1–W3 的可运行内容。**  
   新建四个 agentctl 文件，README 先写合同、不写成功结论；实现 SQL、setup、安装比较。同步追加 loader，并只在两个获准函数体内修改守卫。此阶段不得单独提交放行规则。

3. **完成 W4 的所有用例。**  
   包括直接 shape/授权/hint/pointer、ACL、未知 hint 异常、安装冻结、两个路由正例、无 override 负例和路由 shape 失败。所有夹具使用 mock，不执行真实 provider。

4. **在首次 gate 前按精确路径暂存。**

   ```bash
   git add -- \
     v13/agentctl/v13_agentctl.sql \
     v13/agentctl/setup_db.py \
     v13/agentctl/test_agentctl.py \
     v13/agentctl/README.md \
     v13/load.py \
     v13/plan_arm/test_plan_arm.py
   ```

   README 虽尚未记实跑结果，其路径此时必须已经进入 `git ls-files`。禁止 `git add -A`、`git add .` 或提前暂存后续 stage 路径。

5. **顺序执行两条必需 gate。**

   ```bash
   UV_FROZEN=1 uv run python v13/agentctl/test_agentctl.py
   UV_FROZEN=1 uv run python v13/plan_arm/test_plan_arm.py
   ```

   任一非 0 就停止收尾；按失败断言修根因，再暂存相同路径并重跑。若出现 `changed existing test`，立即撤回越界编辑，不改 `r0_source_scope` 或 AST 例外。

6. **两条都绿后完成 W5。**  
   README 补实际证据；矩阵、台账、parity 和两个历史文档只做规定的追加。按精确路径暂存：

   ```bash
   git add -- \
     v13/agentctl/README.md \
     docs/reviews/v13-control-plane-conformance-matrix-2026-09-26.md \
     docs/reviews/v13-control-plane-deviation-ledger-2026-09-26.md \
     docs/reviews/v13-control-plane-parity-rpce-loopx-2026-09-26.md \
     docs/designs/v13-agent-control-minimal-form-2026-10-02.md \
     docs/investigations/v13-phase-d-reopen-reference-survey-2026-10-02.md
   ```

7. **验证最终状态。**  
   对最终 README 和代码再次运行第 5 步两条命令；检查 `git diff --check`、暂存差异、文件闭集和未暂存差异。不得引用文档更新前的结果代替最终检查。

8. **同一个实现里程碑提交。**  
   仅后续获得施工授权的实现者执行：

   ```bash
   git commit -m "v13: add agentctl observe tool"
   git push origin main
   ```

   不使用 `--no-verify`、force-push 或历史重写。hook 失败修根因，不跳过。Stage 41 不随本笔交付。

### 6.2 最终验收清单

只有同时满足以下条件，Stage 40 才可标为完成：

- 两条指定 gate 在最终文件状态下均退出 0，一次性库已清理。
- 装载项恰到 `agentctl: 40`，stage 1–39 前缀不变，未来路径未获准。
- 生产新增恰一个 STABLE INVOKER 函数和一个 enabled SQL 工具行；没有产品 policy、表、列、事件类型或历史函数替换。
- 形状失败为精确 JSONB 返回，底层 observe/hint 零调用；未授权为整批空成功。
- rows 使用 `parent_session_id` 等活体列名；hint 与 pointer 只依赖实际返回 ID。
- handler 直接调用零持久写、零 pointer 创建；未知会话直接 hint 的异常仍可见。
- 路由正例证明 handler 收到 UUID 文本；无 override 负例证明 handler 未执行；shape 路由例不产生 failed tool effect。
- `spawn_subsession.enabled` 始终 true；PUBLIC/recall 未获得新函数执行权限。
- 两个冻结谓词之外没有修改旧测试或模块级 AST；所有原有合成拒绝继续有效。
- 文档只记录 Stage 40 实跑事实；D-2 仅追加 R6 勘误，F22、R11 与历史裁决正文保持不变。

**交付结论只能是：Stage 40 的授权只读观察工具及其 Fake sql 臂调用链已验证。不能据此声称 Stage 41–45、CE 进程控制、wake、真实 provider 或无人值守能力已经交付。**

## References

- 父计划：`docs/plans/v13-three-layer-goal-workflow-plan-2026-10-06.md`（S1、PR Plan 第 1 项、Rollout）
- 权威顺序：`docs/plans/v13-long-loop-plan-2026-09-28.md` §2 > 父计划 T0–T7 > `docs/reviews/v13-agentctl-da-rulings-2026-10-03.md` > Phase A–D 合同
- 已裁注记：`docs/designs/v13-agent-control-minimal-form-2026-10-02.md` §7（`:365`）、§8（`:390`）；`docs/investigations/v13-phase-d-reopen-reference-survey-2026-10-02.md` §8.2（`:158`）、§8.4（`:208`）
- D-2 勘误：`docs/reviews/v13-control-plane-parity-rpce-loopx-2026-09-26.md:236`（R6，追加不改原句）；`:240`（R11，不改）
- 矩阵与台账：`docs/reviews/v13-control-plane-conformance-matrix-2026-09-26.md`（末行号 85，追加时用当前最大号 + 1）；`docs/reviews/v13-control-plane-deviation-ledger-2026-09-26.md:99`（F22 已关闭，不改）
- 活体：`v13/load.py`、`v13/observe/v13_observe.sql`、`v13/acl/v13_acl.sql`、`v13/govern/v13_govern.sql`、`v13/catalog/v13_catalog.sql`、`v13/schema/v13_core.sql`、`v13/plan_arm/v13_plan_arm.sql`、`v13/plan_arm/test_plan_arm.py`、`v13/loop/advance.sql`、`v13/loop/test_loop.py`、`v13/triage/v13_triage.sql`、`v13/spawn/v13_spawn.sql`、`v13/workflow_bind/v13_workflow_bind.sql`、`v13/real_chain/v13_real_chain.sql`、`v13/control/v13_control.sql`、`v13/fair_claim/setup_db.py`
