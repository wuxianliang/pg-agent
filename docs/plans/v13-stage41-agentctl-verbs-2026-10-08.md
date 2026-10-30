# v13 Stage 41 / S2：agentctl 三员同笔开发计划

## 1. Summary

在已合入的 stage 40 `agentctl`（HEAD `a19aefc`，`v13: add agentctl observe tool`）之后追加 stage 41 `agentctl_verbs`。同一次**将来的**提交交付三个 VOLATILE DEFINER 包装 `v13_agentctl_steer` / `v13_agentctl_answer` / `v13_agentctl_cancel`、冻结的 `controller` version 1、`controller_surface` version 1，以及只活在新 SQL 文件里的 `v13_named_sql_writer` / `v13_spawn_writer_ok` 替换体。实现是局部追加：复用既有授权、append、六参 complete、两参 cancel 和 sql 臂事务边界。不新增表、列、事件类型、`effects.kind`、分发器或消费者。

**本文是实施规格，不是执行报告。** 本规划任务不写生产代码、不跑 gate、不暂存、不提交。下文命令只给以后获准施工的实现者。

**D-3 正文消费未闭合，但不再挡住本里程碑。** 2026-10-08 对 HEAD `a19aefc` 的复核没有找到把 `steer/injected.payload.text` 送进目标后续消费路径的既有函数。已提交 D-3 要求的是 gate 覆盖，不是预先存在的 `file:line`。生产者可在两条 gate 都退出 0 之后提交。退出码 0 的意思是：三个 DEFINER 动词、`controller` / 1、`controller_surface`、sql 臂夹具，以及身份、授权、零写、watermark 已交付；正文消费公开未闭合。

`CONSUMER` 保持 `None`。九个非消费者保持列出。名为 `actl_steer_body_consumed` 的断言不得通过，也不得改成对事件行、`v13_session_log`、水位或审计三联的通过检查。读回事件行、`v13_session_log`、水位 stale、审计三联、`actl_chain_full` 都不是消费。不发明消费者，不改冻结运行时，不加表，不建第二运行时。矩阵不得写「D-3 已闭合」。台账不得写「已取代 R11」。红的 gate 仍不得留在 `main`。

权威顺序与 stage 40 计划相同：长期循环计划 §2 > 父计划 T0–T7 > 2026-10-03 裁决 > Phase A–D。父合同是 `docs/plans/v13-three-layer-goal-workflow-plan-2026-10-06.md` S2（`:369-466`）与 PR Plan 第 2 项（`:731-745`）。行号以函数名为锚；漂移不换实现路径。

### 范围边界

- 新目录只有四个文件：`v13/agentctl_verbs/v13_agentctl_verbs.sql`、`setup_db.py`、`test_agentctl_verbs.py`、`README.md`。
- `v13/load.py` 只追加 `agentctl_verbs` / 41。
- `CREATE OR REPLACE` 只针对那两个谓词，只写在新 SQL 里。不编辑 `v13/spawn/v13_spawn.sql`，也不编辑任何 stage 1–40 SQL。
- 不改 envelope、triage、parse、advance、ACL、control、real_chain、catalog、任何 driver。不实现 `actl_driver_demoted`。
- 不实现 stage 42–45，不放行 `v13/goal_workflow/`、`external_exec`、`ce_map`、`workflow_project`。
- 不运行真实 provider，不调用 LoopX 写路径，不新增数据库外控制文件。
- `spawn_subsession.enabled` 保持 true。不把「保持 true」写成新能力。
- 三员、政策、谓词替换、装载、测试必须同一次将来的提交。不能先交两员或只交谓词。正文消费未闭合不阻止这一次提交。提交不得声称 D-3 已闭合。

---

## 2. Current-state analysis

### 2.1 装载与放行

`v13/load.py` 尾部已是 `fair_claim` / 39、`agentctl` / 40。`r1_load_append_ok`（`v13/plan_arm/test_plan_arm.py:327` 起）的 approved 元组恰为这两项（`:408-410`）。检查顺序是：纯尾、路径唯一、键唯一（`duplicate stage key`）、编号唯一（`duplicate stage number`）、连续编号、目录键对齐、plus 行对应、最后才是 approved 文案 `append is not fair_claim/39 then agentctl/40`。

`r1_phase_d_prefix_allowance`（`:418` 起）只放行三前缀、`accept_unattended.py`、以及 stage 40 四个精确路径。没有目录前缀放行。合成负例已经把 `v13/agentctl_verbs/` 和 `"agentctl_verbs": 41` 当成非法尾（`:667-713`）。stage 41 必须改 approved 元组，并重锚那些会换失败原因的负例；未来负例改成 `goal_workflow` / 42。`r0_source_scope`（`:716`）不动。`v13/spawn/v13_spawn.sql` 在 `fb295ac6c7459bb98dac57e37883af549d2d8a4c` 的字节保护集内。

### 2.2 写者谓词

`v13_named_sql_writer(text)`（`v13/spawn/v13_spawn.sql:42-49`）是 `LANGUAGE sql IMMUTABLE`，无 `SET search_path`。只对 `v13_spawn_subsession` 与 `public.v13_spawn_subsession` 返回 `{"mutating":false,"write_targets":["artifacts","events","latches","sessions"]}`，其余 NULL。

`v13_spawn_writer_ok(text)`（`:1657-1686`）是 `LANGUAGE sql STABLE`，无自身 `search_path`。合取包括：`(uuid,jsonb)→jsonb`、`provolatile='v'`、`prosecdef`、属主 `v13_spawn_owner`、`proconfig` 恰一条且去空格后为 `search_path=pg_catalog,public`、ACL 非空、PUBLIC 无 EXECUTE、`v13_route` 可 EXECUTE、prosrc 不含 `dblink` / `pg_net` / `copy program` / `lo_import` / `lo_export` / `pg_read_file` / `pg_write_file`。最后一子句要求 named 的返回值与**那份四表 jsonb 精确相等**。

插入触发器活体在 spawn 替换体 `:1631-1641`：VOLATILE 行当 `v13_named_sql_writer(NEW.handler) IS NULL OR NOT v13_spawn_writer_ok(NEW.handler)` 时 `RAISE 'v13: sql writer closed'`。是 `IS NULL`，不是 `IS NOT NULL`。目录守卫 `v13/catalog/v13_catalog.sql:36-52` 在波动率不在 `i/s` 时，只有裸名、named 非 NULL 且 writer_ok 为 true 才豁免，否则 `RAISE 'is VOLATILE'`。

只改其中一个谓词，或让新 handler 的 jsonb 不等于 writer_ok 所比较的对象，三行 tools 都插不进去。stage 40 没有替换这两个函数。`actl_guard_closed` 仍要求 `named_sql_writer('v13_agentctl_observe') IS NULL`；该测试装到 40，看不到 41 的替换。41 的白名单不得加入 observe。

### 2.3 包装要调用的活体

| 函数 | 锚 | 本 stage 要用的合同 |
|---|---|---|
| `v13_append_event(uuid,uuid,text,jsonb,uuid)` | `v13/schema/v13_core.sql:62-93` | INVOKER。拨 `sessions.next_seq`，插入 `events`，返回 seq。只有 `user/message` 才动 `turn_no` / 终态复位 |
| `v13_control_authorized` | `v13/acl/v13_acl.sql:90-118` | 只认直接父会话。自己、缺失、非父为 false。NULL actor 才落到 operator |
| `v13_control_operator` | `:74-87` | `rolsuper OR pg_has_role(current_user,'v13_route','USAGE')` |
| 两参 `v13_cancel` | `:121-234` | 授权失败在持久写之前 `RAISE 'v13: session not found'`。终态在临时表填充之后、持久 UPDATE 之前返回 `replay`（`:201-203`）。非终态且 `v13_unconsumed_cancel` 为假才再插 `cancel/requested`（`:219-225`）。只把 `status='ready'` 的 effect 改成 `cancelled`（`:226-230`）。不改 `sessions.status` |
| 一参 `v13_cancel` | `:236-243` | actor 填 NULL。包装禁止调用 |
| 六参 `v13_complete` | `:245-457` | actor 非空且 kind 不是 human：写之前 RAISE（`:269-275`）。token 不符或 status 不是 claimed：返回 `stale`，不写（`:300-308`）。已终态：`replay`（`:303-305`）。human 成功通道要求 request 含 `interaction_ref`（`:330`）。`unknown` 会抬墙（`:448-449`）；`worktree_release` 成功会记释放（`:453-454`） |
| 五参 `v13_complete` | `:459-470` | actor 填 NULL。包装禁止调用 |
| `v13_unconsumed_cancel` | `v13/control/v13_control.sql:129-142` | 非终态且存在比最后 `session/cancelled` 更新的 `cancel/requested` |
| `trg_v13_control_event_guard` | `:478-482` | WHEN 十类型，不含 `steer/injected`。`cancel/requested` 在列表里，载荷键必须恰为 `schema_version` + `scope=session`（`:434-439`）。包装不要自己插这行 |
| `trg_events_goal` | `v13/manifest/v13_manifest.sql:33-36` | 只在 `user/message` 时投影 `v13_goals` |

`v13_spawn_owner` 是 `NOLOGIN NOSUPERUSER`（`v13_spawn.sql:279-280`）。仓库里没有 `GRANT v13_route TO v13_spawn_owner`。DEFINER 里 `v13_control_operator()` 必须为 false。两参 cancel 与六参 complete 的 EXECUTE 已经授给该属主（`v13_acl.sql` 末尾 GRANT）。不要补 route 成员资格。

### 2.4 政策、开会话、目录行

`v13_route_policies` 只能 draft→frozen（`v13_core.sql:464-481`）。`thresholds` 只在父版本为 draft 时可 INSERT。`v13_policies.value` 不可 UPDATE（`:711-725`）。sessions 只能引用已 frozen 的 route policy。`v13_open_session`（`v13_spawn.sql:285-315`）只接受 `{route_policy_name, version}`，不写 `parent_session_id`。不传 spec 时是 `default` / 1。

`default` version 2 的种子与漂移检查在 `v13/real_chain/v13_real_chain.sql:79-160`，字节保持。复制形态见 `v13/agentctl/test_agentctl.py:299-333` 的 `freeze_probe_policy`。产品行名是 `controller` / 1，不是探针名。探针随 stage 40 测试库消失，不能当产品政策。

tools 插入列与 stage 40 相同（`v13/agentctl/v13_agentctl.sql:132-141`）：`name, description, kind, handler, param_spec, enabled`。`param_spec` 每个键只有非空 `question` 与 `stated`，无 `options`。

### 2.5 sql 臂与夹具阻断点

`v13_resolve_tool_params`（`v13/loop/advance.sql:169-182`）只在 stated 命中 pass 时把 param choice 抄成字符串。`mock_from_needed` 对未指定 noul 填 `0.1`（`v13/loop/test_loop.py:126`）。pass 带是 `[0.60, Infinity)`，`0.1` 落在外面。

`v13_advance` 在 route 之前会返回。夹具必须让这些返回都不发生，然后 `v13_triage_steer` 返回 NULL。不要改 triage、envelope、advance，不要加 `triage` 带。

| 阻断 | 活体 | 夹具 |
|---|---|---|
| 调用者有 ready/claimed effect | `v13_plan_arm.sql:404-466` | 直接 spawn，不在根上留这种行 |
| 没有非空 user/message | `v13_triage.sql:93-95,161-164` | 先写，再 spawn（spawn 还要求 `next_seq >= 1`，`v13_spawn.sql:348-349`） |
| 根没有 direct override | `v13_triage.sql:454-456,488` | parse 前 `v13_submit_override`，`source_principal=operator` |
| override 在 parse 之后 | `v13_plan_arm.sql:359-368` | 会 stale。水位七项不含 `context_active_revision` |
| stated noul 0.1 | `advance.sql:177-179` | 每个 stated 显式 0.9 |
| remaining > 0 | `v13_plan_arm.sql:724-736` | parse 后先断言 remaining=0、failed=false |

sql 臂（`v13_plan_arm.sql:771-813`）：先 append `turn/route`（推进调用者 `next_seq`），再在子事务里 `EXECUTE` handler。异常被吸收后直插 failed tool effect，不写 `tool/result`，这次 INSERT 本身不拨 `next_seq`。成功才写 `tool/result`。handler 零写不等于整次 advance 零写。

stage 40 已绿的路由顺序是：parse，然后 `UPDATE sessions SET context_active_revision = v13_context_required(session_id)`，立刻 advance（`v13/agentctl/test_agentctl.py:693-698`）。本 stage 照抄这个位置，不把它挪到 parse 之前。

### 2.6 D-3

没有 live 消费者。字面出现处只写无 text 的事件或只做计数：`v13/control/test_control.py:516-524`、`demo_v13/parity/g_steer.py:98`、`v13/plan_contract/test_plan_contract.py:459-460`。提示与记忆白名单排除该类型：`v13/resolve/v13_resolve.sql` 的 canonical state、`v13/envelope/v13_envelope.sql:519,551`、`v13/memory/v13_memory.sql:113-127`、`v13/triage/v13_triage.sql:161-164`。`v13_session_log`（`v13/observe/v13_observe.sql:130-171`）会读出 payload，但不进入 LLM、工具参数、goal 或 effect。`v13_triage_steer` 是名字碰撞，不读 `steer/injected`。这些位置继续算非消费者。没有新的 file:line 就不新增消费者；这不再挡住生产者提交，也不授权改冻结谓词。

---

## 3. Design

### 3.1 执行索引

W1–W4 写入工作区。W5 是生产者收尾，不是寻找消费者。两条 gate 都退出 0 之后才做 W5 并提交。不得拆成多次提交。正文消费未闭合不是 W5 或 W6 的阻塞条件。

| 项 | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| W0 | 确认仍无正文消费者，且不因此停提交 | README 写明消费未闭合；不新增消费者；不把无消费者写成提交禁令 | 只读 live tree | HEAD 含 `agentctl`/40 | S |
| W1 | 追加装载与精确放行 | 尾项恰为 39、40、41；八个 stage 40/41 路径保留；`goal_workflow` 仍拒绝 | `v13/load.py`；`test_plan_arm.py` 两个函数体 | W0 | M |
| W2 | 安装三员、谓词、政策 | 一个事务里完成替换、三函数、三行、两份政策 | `v13_agentctl_verbs.sql` | 累计装到 40 | L |
| W3 | 一次性库与安装差 | 从 stage 40 基线安装；只允许规定的函数/目录/政策差；失败也只删本进程的库 | `setup_db.py`；测试 | W1、W2 | M |
| W4 | 直接调用、角色、路由链、残项仍开放 | 两条 gate 都退出 0；`CONSUMER` 仍是 `None`；九个非消费者仍在；没有名为 `actl_steer_body_consumed` 的通过断言 | 测试；README 合同段 | W3 | L |
| W5 | 大声记下未关闭的正文消费 | 两 gate 已退出 0。矩阵只声称生产者。台账有 S41-D3 未关闭。parity 只追加勘误，动词不是「取代」。不引用消费者 file:line | README；矩阵；台账；parity 追加段 | W4 两条 gate 退出 0。不依赖已有消费者 | S |
| W6 | 同笔提交 | 最终树重跑两 gate 退出 0；生产者闭集一次提交；不含 stage 42 | §4 的文件 | W5 | S |

### 3.2 三个包装的公共合同

```text
public.v13_agentctl_steer(p_sid uuid, p_spec jsonb)  → jsonb
public.v13_agentctl_answer(p_sid uuid, p_spec jsonb) → jsonb
public.v13_agentctl_cancel(p_sid uuid, p_spec jsonb) → jsonb
```

`LANGUAGE plpgsql VOLATILE SECURITY DEFINER`，`SET search_path = pg_catalog, public`。`ALTER FUNCTION ... OWNER TO v13_spawn_owner`。`REVOKE EXECUTE FROM PUBLIC`。只 `GRANT EXECUTE TO v13_route`。不声明 STRICT。不写 `EXCEPTION ... WHEN` 捕获块。`RAISE EXCEPTION` 是拒绝路径，必须保留。不 `COMMIT`。不动态 `EXECUTE`。actor 传给 complete/cancel 的永远是 `p_sid`，不是 NULL。

形状失败是 RAISE，不是 observe 那种 `{ok:false, reason:"shape"}`。sql 臂会把 RAISE 收成 failed tool effect。这是合同差异，不要抄观察函数的返回形状。

**固定顺序，用独立 IF，不依赖 SQL 布尔短路：**

1. 形状。`p_spec` 为 SQL NULL，或 `jsonb_typeof` 不是 `object`：`RAISE EXCEPTION 'v13: agentctl args'`。然后用 `v13_json_keys`（`v13_control.sql:102-106`，按键排序）比对闭集。类型、canonical UUID、`btrim`、长度任一失败，同一句文案。不到达政策，也不到达授权。
2. 调用者政策。`SELECT route_policy_name, route_policy_version FROM sessions WHERE session_id = p_sid FOR UPDATE`。无行，或不是恰好 `controller` / 1：`RAISE EXCEPTION 'v13: agentctl policy'`。无行也用这一句，不回显 uuid，不用 `v13: unknown session`。
3. 授权。`v13_control_authorized(p_sid, target)` 不是 true：`RAISE EXCEPTION 'v13: session not found'`。自己、兄弟、祖先、孙辈、缺失目标都是这一句。不另写亲缘查询。

政策放在授权之前，是为了不让非 controller 调用者用「政策错误 vs session not found」确认目标是不是自己的直接子会话。父计划的威胁模型把未授权目标统一成 `v13: session not found`（`v13_acl.sql:109-117` 与父计划安全节）。先授权再政策会把「我是父会话」泄漏给错误政策的调用者。不采用那个顺序。

UUID 只接受 `v13_canonical_uuid` 为 true 的小写 8-4-4-4-12（`v13_control.sql:114-117`）。不 trim、不大写折叠。确认之后才 `::uuid`。`text` / `response` 先默认 `btrim`，再用 `char_length` 检查 1..1024 个字符。按字符，不按字节。不截断。存入库的是 btrim 之后的字符串。额外键包括 `source_principal`、`skip`、`answers`、`interaction_ref`、`schema_version`，都在步骤 1 拒绝。

### 3.3 steer

键恰为排序后的 `["target","text"]`。通过前言后：`v_event := gen_random_uuid()`，只调用 `v13_append_event(target, v_event, 'steer/injected', payload)`。payload 由函数构造，键恰为 `schema_version`（数字 1）、`text`（btrim 后）、`source_principal`（字面量 `'controller'`）。不从 `p_spec` 复制身份，不放调用者 uuid。

返回键恰为 `schema_version`（数字 1）、`caller`（`p_sid` 文本）、`target`、`event_id`（传入 append 的那个 uuid）、`seq`（append 返回的 bigint）。审计三联是 caller、target、event_id。事件行上看不到 caller。直接调用测试必须读返回值。不加列。

成功的直接调用：目标 `next_seq` +1，`turn_no` 与 `status` 不变，`v13_goals` 行数不变。一行 `steer/injected`。`effects` / `artifacts` / `latches` 不变。差集 `["events","sessions"]`。若 `v13_goals` 反而增加，停止，不要把 `v13_goals` 补进 `write_targets`，也不要改 `trg_events_goal`。

不幂等。相同文本再调一次是新的 event_id。没有请求级幂等键。终态目标仍可插入该事件，不表示会话复活。

### 3.4 answer

键恰为排序后的 `["effect_id","response","target"]`。无 `skip`。

前言通过后、任何 effect `UPDATE` 之前，读取并锁定该 effect（先锁目标 session 行，再锁 effect，与六参 complete 的 session→effect 局部顺序一致，`v13_acl.sql:277-308`）。必须同时满足：`effect_id` 匹配、`session_id = target`、`kind = 'human'`、`status = 'ready'`、`request ? 'interaction_ref'`。任一不成立：`RAISE EXCEPTION 'v13: agentctl answer'`，此时还没有 UPDATE。

领用语句固定为：

```text
UPDATE effects
   SET status = 'claimed',
       attempt_no = attempt_no + 1,
       fence = fence + 1,
       lease_owner = 'agentctl_answer',
       lease_until = clock_timestamp() + interval '1 hour'
 WHERE effect_id = <目标>
   AND session_id = <target>
   AND status = 'ready'
   AND kind = 'human'
 RETURNING attempt_no, fence
```

零行：同一句 `v13: agentctl answer`，不调用 complete。不 `COALESCE`。测试用调用前的值 +1，不在包装里写死 1。不调用 `v13_claim`，不取 13002 / 13003。

`p_result` 键恰为 `schema_version`（数字 1）、`interaction_ref`（`effect.request->'interaction_ref'`，jsonb，不是 `->>`，也不从参数复制）、`response`（btrim 后）。不传 `skip` 或 `answers`。`->>` 会把 JSON 数字 `1` 变成文本 `'1'`，与 `request->>'interaction_ref'` 相等，六参 complete 会接受（`v13_acl.sql:343-346`）。

只调用六参 `v13_complete(p_sid, effect, returning_attempt, returning_fence, 'succeeded', result)`。status 位置在源码里必须是字面量 `'succeeded'`，不能是变量。因此 complete 的 `unknown` 臂与 `worktree_release` 臂从本包装不可达；单凭 succeeded 不能解释 worktree 臂不可达，必须同时是 human。

返回文本用 `IS DISTINCT FROM 'accepted'` 判断，不是 `<>`。SQL NULL 也 RAISE `v13: agentctl answer not accepted`。`IF v_word <> 'accepted'` 在 NULL 时不进入，函数会把空返回当成功。该 RAISE 与领用在同一函数、同一事务，没有 `EXCEPTION ... WHEN` 捕获块。`stale` 与 `replay` 是文本返回，不回滚领用；忽略它们会把半次领用收成成功 tool effect。底层自己的 RAISE（例如 interaction_ref 类型）原样传播，同样回滚领用。

成功返回键恰为 `schema_version`、`caller`、`target`、`effect_id`、`outcome`（文本 `accepted`）。不返回 attempt、fence、lease、interaction_ref。token 在 effect 行上，`actl_approval_two_phase` 从行和源码现推，不加列，也不把 token 放进工具返回去绕过「不加列」。caller 必须在返回值里，理由与 steer 相同：事件行没有调用者 uuid。

成功差集 `["effects","events","sessions"]`：领用加上 complete 的 effect 更新、`effect_done` 与 `human/responded`（`v13_acl.sql:441`）。目标 `next_seq` 因两次 append 增加。调用者 `next_seq` 不变。不额外清 lease，不第三次 UPDATE effect。第二次回答同一已成功 effect 在领用前 RAISE，`human/responded` 仍是一条。

### 3.5 cancel

键恰为 `["target"]`。前言通过后只调用两参 `v13_cancel(p_sid, target)`。源码不得写成 `v13_cancel(target)` 或 `v13_cancel(NULL, ...)`。包装不自己插 `cancel/requested`，不改 `sessions.status`，不 closeout，不预先锁取消树。

返回词只接受恰好 `accepted` 或恰好 `replay`，两边都用 `IS DISTINCT FROM`。不用 `NOT IN`：NULL 不会进入 `NOT IN`。其他文本或 NULL：`RAISE EXCEPTION 'v13: agentctl cancel'`。成功返回键恰为 `schema_version`、`caller`、`target`、`outcome`。

期望差集来自「目标上已有一条 ready effect」的直接调用：`["effects","events","sessions"]`。没有 ready 行的那次只有 `events` 与 `sessions`，不得拿来当 named 的期望集合。临时表 `v13_fanout_cancel_tree` 是 `ON COMMIT DROP`（`v13_acl.sql:144-149`），不进差集，不看 `pg_temp`。

`actl_cancel_sticky`：同一条仍非终态的会话再调一次。`v13_unconsumed_cancel` 为真时跳过第二次 `cancel/requested`（`:223-225`），函数末尾仍返回 `accepted`。计数保持 1。返回词不是 `replay`。`next_seq` 不再增加。终态 `replay` 另测：目标 `status` 已是 `completed` / `failed` / `cancelled`。测试用 `UPDATE sessions SET status='cancelled'`，与 `v13/acl/test_acl.py:502` 相同。未知墙对这三个终态直接返回（`v13/control/v13_control.sql:598-600`），不要因这次 UPDATE 会被拦住而停。本包装不 closeout，也不调用 `v13_closeout`。粘性第二次不是这条 `replay`。

claimed effect 不由本函数结算。底层对子树的处理不等于允许调用者直接控制孙辈。

### 3.6 谓词替换与 tools 行

新文件里 `CREATE OR REPLACE`，签名与语言属性保持：named 仍 IMMUTABLE、非 DEFINER、无自身 `search_path`；writer_ok 仍 STABLE、非 DEFINER、无自身 `search_path`。属主与 ACL 保持原样。

| handler，另接受 `public.` 形式 | mutating | write_targets |
|---|---|---|
| `v13_spawn_subsession` | false | `["artifacts","events","latches","sessions"]` |
| `v13_agentctl_steer` | false | `["events","sessions"]` |
| `v13_agentctl_answer` | false | `["effects","events","sessions"]` |
| `v13_agentctl_cancel` | false | `["effects","events","sessions"]` |
| 其他，含 `v13_agentctl_observe` | named 返回 NULL | writer_ok 返回 false |

`mutating:false` 是既有记号，不是「不写表」。writer_ok 对每个获准名字保留今日全部安全合取，最后一子句按名字比较上表的完整 jsonb。不得改成「包含这些表」或只检查 `mutating`。不改 `v13_tools_guard`，不改 `v13_tools_catalog_frozen`。

正例 `writer_ok = true` 不证明合取还在。在 savepoint 里建一个不是 `tools.handler` 的临时 `(uuid, jsonb) → jsonb` 函数，每个合取一个变体：禁词子串、属主、`provolatile`、`proconfig`、PUBLIC `EXECUTE`、`v13_route` `EXECUTE`、签名。期望 `writer_ok` 为 false，且把它当 handler 插进 tools 被拒。然后回滚。名字不要碰上已有 sql handler：`CREATE OR REPLACE` 会走 `v13_tools_ddl_bump`，把 `tools_revision` +1（`v13/schema/v13_core.sql:1068-1078`），后面的 parse 会 stale。

三个 tools 行：`kind=sql`，`enabled=true`，handler 用裸名。description / question / stated 固定为：

| 工具 | description |
|---|---|
| `agentctl_steer` | `Inject steering text into an authorized child session.` |
| `agentctl_answer` | `Answer a ready human interaction in an authorized child session.` |
| `agentctl_cancel` | `Request cancellation of an authorized child session.` |

| 参数 | question | stated |
|---|---|---|
| steer.target | `Which child session UUID should receive steering text?` | `Does the user specify the child session UUID to steer?` |
| steer.text | `What steering text should be injected?` | `Does the user specify the steering text?` |
| answer.target | `Which child session UUID contains the human interaction?` | `Does the user specify the child session UUID to answer?` |
| answer.effect_id | `Which human effect UUID should be answered?` | `Does the user specify the human effect UUID to answer?` |
| answer.response | `What response should be submitted to the human interaction?` | `Does the user specify the response to the human interaction?` |
| cancel.target | `Which child session UUID should be cancelled?` | `Does the user specify the child session UUID to cancel?` |

### 3.7 政策与 SQL 文件顺序

一个 `BEGIN ... COMMIT`。顺序固定：

1. 替换 `v13_named_sql_writer`。
2. 替换 `v13_spawn_writer_ok`。
3. `CREATE` 三个包装，再 `ALTER OWNER`、`REVOKE`、`GRANT`。
4. 不预写表 GRANT，也不按 `42501` 现场补任意特权。旧函数的 ACL 保持不变，安装比较不放宽。依赖执行权不足时停止并核对，不追授后再跑。禁止 `GRANT v13_route TO v13_spawn_owner`，禁止改 acl/spawn/core，禁止改成 INVOKER，禁止给 append/complete/cancel 加 DEFINER。
5. `INSERT` 三行 tools。
6. 确认 `default` / 2 存在且 frozen。插入 `controller` / 1，状态 draft。复制带用 `v13/agentctl/test_agentctl.py:303-308` 的形状，把身份改成 `controller` / 1：`INSERT INTO thresholds (policy_name, policy_version, signal, band_no, lo, hi, action) SELECT 'controller', 1, signal, band_no, lo, hi, action FROM thresholds WHERE policy_name = 'default' AND policy_version = 2`。不要 `SELECT *` 把 `default` / 2 的主键原样插回去：会撞主键，或因已 frozen 的父版本被拒。再为四个工具的每个 param/stated 插入 pass 带：`band_no=1`，`lo=0.60`，`hi=Infinity`，`action=pass`。共 16 行：observe 的 `ids`、`hint`；steer 的 `target`、`text`；answer 的 `target`、`effect_id`、`response`；cancel 的 `target`。信号名是 `param::<tool>::<key>` 与 `stated::<tool>::<key>`。不加 `triage` 带。核对带集恰等于源带集加这 16 行。然后 `state=frozen`。冻结后不得再插带。
7. 插入 `v13_policies`：`name=controller_surface`，`version=1`，`active=true`。value 恰为 `schema_version` 数字 1、`route_policy_name` `"controller"`、`route_policy_version` 数字 1、`tools` 数组顺序固定为四个名字。没有 goal、授权结论或结算事实。
8. COMMENT 写在函数体外。三个包装的 `$fn$` 体内，包括注释，不得出现 writer_ok 要扫描的 IO 子串，也不得出现 `v13_claim`、`13002`、`13003`。
9. `COMMIT`。

不做 upsert。任一对象已存在或守卫失败，整笔回滚。不改 `default` / 2。不改既有 session 的政策。新 tools 使目录 revision 增加；按行触发器计，期望 +3。若活体不是每插一行 +1，停止并核对 `v13_tools_bump`，不改那个触发器，也不改 candidate revision。旧 parse 快照按既有规则 stale，处理方式是重新 parse。

三个写函数读的是调用者 session 的 `route_policy_name` / `version`，不读 `controller_surface` 来授权。observe 不增加政策门。非 controller 会话仍可能在目录里看见这四个名字。缓解是写函数 fail-close，不是改信封。

### 3.8 直接调用差集与 sql 臂窗口

差集窗口只包住直接 `SELECT` 包装的那一条语句。夹具序言（`user/message`、`goal/override`、`child-created`、enqueue）在窗口外。sql 臂自己的 tool effect 不进 handler 的集合。

窗口前对 `sessions` 全列、`events`（event_id、session_id、seq、type、payload）、`effects` 状态列、`artifacts` 计数、`latches` 计数做有序快照。调用后再拍。有插入或持久列变化的表，名字排序后必须等于该 handler 的 `write_targets`。再断言裸名与 `public.` 限定名的 named jsonb 都等于这份对象，且 writer_ok 为 true。spawn 的四表 jsonb 与 writer_ok 仍为 true。observe 的 named 为 NULL，writer_ok 为 false。

拒绝路径：`SAVEPOINT`，调用，期望 RAISE，`ROLLBACK TO SAVEPOINT`。目标 `next_seq`、`steer/injected` 计数、effect 状态与调用前相同。单靠回滚后行相等不能证明「写之前拒绝」；形状、授权、政策失败还要用 `pg_stat_xact_user_functions` 证明 append / complete / cancel 的增量为 0。`v13_json_keys` 与 `v13_canonical_uuid` 是 IMMUTABLE，可能被内联，不靠它们的计数。

sql 臂上的 handler RAISE：advance 仍返回 `progressed`。调用者 `next_seq` 只因 `turn/route` +1。一条 failed tool effect，`error` 含原消息，没有 `tool/result`。目标业务行回到 handler 执行前。不要把 `turn/route` 的推进算给 failed-effect INSERT。

### 3.9 根路由夹具

`actl_chain_full` 跑三次独立根夹具，动词分别是三个写工具。三次的根 `session_id` 两两不同。测试用一张登记表加同一套 `prepare → parse → advance`，不写「先 steer 再 answer 再 cancel」的直线调用。登记表不是生产分发器。Python 只记录执行。另设 `actl_controller_observe_routed`：根开在 `controller` / 1 上，照抄 `actl_observe_routed`（`v13/agentctl/test_agentctl.py:693-698`）走 parse → 对齐 `context_active_revision` → advance。`ids` 与 `hint` 的 stated noul 为 0.9。期望 `action=sql`、`tool=agentctl_observe`、`request.params` 不是 `{}`。数 threshold 行或直接调用 observe 都不读带，不算这条。不改 stage 40 包装，也不代替三条写链。

每一次写动词：

1. `v13_open_session`，spec 恰为 `{"route_policy_name":"controller","version":1}`。
2. 根上非空 `user/message`。
3. `v13_spawn_subsession`，键恰为 `schema_version`（数字 1）与 `children`（恰一项，含新的 `tool_call_id` 与非空 `task`）。这是 `v13_spawn.sql:330-331` 的闭集。从 `children[0].session_id` 取目标。返回键是 `replay_kind`、`parent_session_id`、`children`、`reservation`（对照 `test_agentctl.py:366-368`）。
4. 根上 ready/claimed effect 数为 0。
5. answer 与 cancel：在子会话上 `v13_enqueue_effect(child, 'human', {"schema_version":1,"interaction_ref": ref})`（`v13/acl/test_acl.py:115-119`）。steer 不放 effect。cancel 的这条 human 只是为了准备 ready 行。
6. parse 之前 `v13_submit_override`，键恰为 `intent=direct`、`reason=""`、`schema_version` 数字 1、`source_principal=operator`。不是 `controller`。
7. `mock_from_needed` 覆盖：`intent=sql_answer`（0.9）、`tool=<动词>`（0.9）、`gate_action` noul 0.9、`gate_off_topic` noul 0.1、`risk` score 0.5 confidence 0.9；该动词每个 stated 为 `{"type":"noul","noul":0.9}`；每个 param choice 为规范字符串。steer 的 text 与 answer 的 response 用无首尾空格的短字符串。
8. 会话级 GUC：`typesafe.provider=mock`，`typesafe.model=jev-mock`，`track_functions=all`。然后 `v13_parse`。断言 `remaining=0`、`failed=false`、`abandon=false`，snap 的政策是 `controller` / 1。
9. `UPDATE` 根的 `context_active_revision = v13_context_required(session_id)`，立刻 `v13_advance(root, 整份 parse jsonb)`。不重建 snap，中间不再追加事件。这一步省掉时，`v13_context_fresh` 为假（`v13/manifest/v13_manifest.sql:207-208`），advance 入队 `context_refresh` 并返回 `waiting`（`v13/plan_arm/v13_plan_arm.sql:693-705`）。这不是 `triage_fail_closed`。不要改 triage、envelope 或 advance 去「修」它。也不要把这次 UPDATE 挪到 parse 之前：parse 会插 decisions，事前写的 revision 到 advance 时已经过期。

正例：`progressed`；最新 `turn/route` 的 `action=sql` 且 `tool` 等于该动词；恰一条 succeeded tool effect，error NULL；`request.params` 是那些规范字符串，不是 `{}`；`effects.result` 等于 `tool/result.payload.result`；根上恰一条 `goal/override`，它不是 `steer/injected`，不进 write_targets。目标上的差与直接调用相同。子会话 status 不被包装改成终态。

同一函数内的反证，仍然三次独立根：

- 省掉 override：advance `waiting`；根上 human reason 为 `triage_fail_closed`；该 tool effect 数为 0；包装调用增量为 0。`:454-456` 与 `:488` 是不同分支，不写成一次调用必定入队两次。
- `target` choice 为 `not-a-uuid`：parse 仍 remaining=0、failed=false；advance `progressed`；tool effect `failed`；无 `tool/result`；目标零写。

非根、不提交 override 的通路存在。S2 不选它。

### 3.10 必需断言

| 断言 | 必须证明 |
|---|---|
| `actl_write_targets` | 三份规定的直接成功夹具差集等于各自 named jsonb；spawn 四表不变；无 ready 的 cancel 不拿来当期望集合；临时表不计 |
| `actl_chain_full` | 三个独立写动词的 parse→advance→sql 正例；无 Python 控制序列 |
| `actl_approval_two_phase` | 见下。RETURNING 的 token 被使用；不是 `accepted` 就 RAISE；领用回滚 |
| `actl_steer_watermark` | 子会话上的 user message 与在途 effect 先写完，再 parse，再存 request / request_hash / attempt / fence / lease，再由父会话 steer，再用那份快照 advance。期望 `stale`，`next_seq` 只因 steer +1，那些 effect 列不变，stale 调用本身零业务写。子会话也要有 `typesafe.provider=mock` 与 `typesafe.model=jev-mock`。这不是正文消费 |
| `actl_cancel_sticky` | 非终态第二次：计数仍为 1，返回不是 `replay`。终态 `replay` 另测 |
| `actl_no_io` | 只扫描三个新函数的 `pg_get_functiondef`，不扫描 writer_ok（它体内故意写着禁词），不扫描测试源码。禁 `dblink`、`pg_net`、`copy program`、`lo_import`、`lo_export`、`pg_read_file`、`pg_write_file`、`v13_claim`、`13002`、`13003`、动态 `EXECUTE`。禁止的是 `EXCEPTION ... WHEN` 捕获块，不是裸子串 `EXCEPTION`：`RAISE EXCEPTION` 必须能过。steer 必须能看到 `v13_append_event`；answer 与 cancel 不得自己调用它 |
| `actl_steer_reject_zero_event` | 形状、越权、政策失败都无目标 steer、无 `next_seq` 变化。路由失败的外层账目分开断言 |
| `actl_no_null_actor` | 源码里 complete/cancel 的第一参是 `p_sid`；没有一参 cancel、五参 complete。超级用户例的调用者必须已是 `controller` / 1，目标不是它的直接子会话，才得到 `v13: session not found` 且零写。`default` / 1 与测试库里的 `controller` version 2 留在 `actl_policy_fail_close`。对照：同一条一次性会话上，超级用户直接 `v13_cancel(NULL, sid)` 可以走 operator 路径。用过的会话不再复用 |
| `actl_owner_not_operator` | `rolsuper` false；`pg_has_role('v13_spawn_owner','v13_route','USAGE')` false；`SET ROLE v13_spawn_owner` 后 operator 谓词为 false。新 SQL 全文不得含 `GRANT v13_route TO v13_spawn_owner` |
| `actl_policy_fail_close` | 三个动词：合法形状、真实子会话、调用者是 `default` / 1，都 RAISE `v13: agentctl policy` 且零写。测试库里再冻结一份零带的 `controller` version 2，开会话指向它，同样是这句。version 2 不进生产 SQL。observe 不参与：默认政策与 `controller` / 1 都能直接观察到授权子会话 |
| `actl_steer_body_residual_open` | `main` 最后调用。通过条件只有：`CONSUMER is None`，`NON_CONSUMERS` 与 §2.6 的九项逐字相同，README 含「正文消费未闭合」且不含「不得退出 0」「已取代 R11」。没有名为 `actl_steer_body_consumed` 的 `check`。给 `CONSUMER` 赋值则失败。这不是消费证明 |

补充：`actl_catalog_rows`、`actl_controller_policy`、`actl_controller_observe_routed`、`actl_acl_closed`、`actl_shape_closed`、`actl_guard_closed`、`actl_install_delta`、`actl_frozen_unchanged`、`actl_spawn_enabled_true`。不实现 `actl_driver_demoted`。

`actl_approval_two_phase` 四段都要有，不能互相替代：

1. 源码：领用 UPDATE、六参调用、字面量 `'succeeded'`、返回词不是 `accepted` 就 `RAISE EXCEPTION`、没有 `EXCEPTION ... WHEN` 捕获块。
2. 底层 stale：`SAVEPOINT` 里执行与包装相同的领用，再六参 complete，fence 用 RETURNING 值 +1。返回 `stale`。回滚后 effect 仍 `ready`，attempt/fence 与 `next_seq` 回到原值。这证明底层，不证明包装。
3. 包装在领用之后 RAISE：human 的 `interaction_ref` 用 JSON 数字 `1`（`?` 仍为真）。包装必须把 `request->'interaction_ref'` 原样放进 `p_result`，不能 `->>`。直接调用异常文本以 `v13: human interaction_ref mismatch` 开头（`v13_acl.sql:343-346`）。不要断言 submitted 与 current 不同：SQL `OR` 不短路，数字仍会格式化成 `submitted=1, current=1`。回滚后仍 `ready`。只看到异常加 `ready` 不够：领用前的 `v13: agentctl answer` 也会留下同一行。同一失败走 sql 臂：`progressed`、failed tool effect、无 `tool/result`、human 仍 `ready`、调用者 `next_seq` 只 +1、目标 `next_seq` 不变。
4. 包装对非 `accepted` 文本返回的 RAISE：在行为测试的 `SAVEPOINT` 里读取新函数的 `pg_get_functiondef`，只把传给六参的 fence 实参改成 RETURNING fence 减 1，恰改一处。事务内替换这一个新函数，不改 stage 1–40。直接调用必须 RAISE `v13: agentctl answer not accepted`，回滚后 effect 仍 `ready`。路由例的替换必须在 parse 之前，因为 `CREATE OR REPLACE` 会把 `tools_revision` +1（`v13/schema/v13_core.sql:1068-1078`），步 0 比的是这一列（`v13/plan_arm/v13_plan_arm.sql:360-368`），不是 handler digest。parse 之后再替换会返回 `stale`，证不了这条。外层 savepoint 回滚后，函数定义、属主、ACL、proconfig 与注入前相等。不得把故障定义留到最终成功检查，不得给产品 API 加 fault 参数。

调用计数沿 stage 40：`SET track_functions = all`，不用 `SET LOCAL`。每个测量事务先用一次可回滚的 `v13_control_authorized` 探针。探针看不到增量就报告环境阻塞，不降级，不把冻结函数换成 spy。`COMMIT` 会清掉事务内计数，提交之后要重新武装。

形状矩阵至少包括：SQL NULL、JSON null、数组、标量、空 object、缺键、额外键 `source_principal`、非字符串 UUID、大写、空白、无连字符、空串、纯空格、1025、非字符串 text/response、answer 的 `skip`。1024 与 `"  hi  "`（存成 `hi`）在成功例里。多字节按字符数。亲缘负例：自己、兄弟、祖先、孙辈、缺失目标。answer effect：缺失、属于另一目标、非 human、已领走、终态、缺 `interaction_ref`。

`actl_acl_closed`：`v13_route` 对三个签名可 EXECUTE；`public`、`v13_recall`、`v13_worker`、`v13_resolve` 不可。`SET ROLE v13_route` 做一次成功的授权 steer，返回含 `event_id`。这证明的是包装的 EXECUTE，不是表权限：函数是 DEFINER，体内 `current_user` 是 `v13_spawn_owner`。不要再加两次 role 成功调用去证表 ACL。answer 的直接成功已经要求属主能 `UPDATE effects`。`SET ROLE v13_recall` 得 `42501`。形状 RAISE 不算 route 的成功证明。不建持久登录角色。

`actl_spawn_enabled_true`：安装前、安装后、行为测试后，`spawn_subsession.enabled` 都是 true，该行其余列不变。

### 3.11 装载与合成负例

`v13/load.py` 只在两个容器末尾各加一行。不改注释、导入、`files_through`、`run_psql`、`load_stage`。

`r1_load_append_ok` 的 approved 改为三项：fair_claim/39、agentctl/40、agentctl_verbs/41。失败文案改为 `append is not fair_claim/39 then agentctl/40 then agentctl_verbs/41`。`order_names` 不改。36–38 不重算成追加。

`r1_phase_d_prefix_allowance` 增加精确集合，不把 `"v13/agentctl_verbs/"` 放进 `prefixes`：

```text
v13/agentctl_verbs/v13_agentctl_verbs.sql
v13/agentctl_verbs/setup_db.py
v13/agentctl_verbs/test_agentctl_verbs.py
v13/agentctl_verbs/README.md
```

`allow()` 的路径条件变为：三个前缀，或 stage40 四路径，或 stage41 四路径。`extra - known_names - stage40 - stage41 <= fresh_ok`。两个集合都必须是 tracked 的子集。拒绝文案保持 `outside the three prefixes`，旧 needle 继续有效。

重锚（依据 `:360-410` 的检查顺序）：

| 现构造 | 41 之后 | 新 needle |
|---|---|---|
| `"agentctl": 40` 改成 `"agentctl": 41` | 与 verbs 的 41 重复 | `duplicate stage number` |
| `"agentctl": 40` 改成 `"agentctl_verbs": 40` | 键重复 | `duplicate stage key` |
| `replace("v13_agentctl.sql", "v13_agentctl_extra.sql", 1)` | 不命中 verbs 文件名；元组不匹配 | 新的三项文案 |
| 合法尾后再追加 agentctl_verbs/41 | 那已是合法尾 | 改为追加 `goal_workflow` / `v13_goal_workflow.sql` / 42，tracked 含该 SQL，needle 为三项文案 |

另加，每次只改一个条件：`v13/agentctl_verbs/extra.py` 与 `v13/goal_workflow/test_goal_workflow.py` 仍是 `outside the three prefixes`；tracked 去掉 verbs SQL，needle 固定为 `stage 41 path is not tracked`，不要复用 stage 40 那句；`"agentctl_verbs": 42` 而 SQL 仍是该项，needle 为 `stage number is not the next contiguous value`；`"agentctl_verbs": 41a` 仍是非规范加号行。旧的 `v13/agentctl/extra.py`、缺 stage 40 文件、`40a`，全部保留。

`r0_source_scope` 一字不改。出现 `changed existing test` 或 `changed module setup` 就撤回越界编辑。

### 3.12 一次性库

`setup_db.py` 沿 `v13/agentctl/setup_db.py`，不调用会 DROP 固定库名的旧 `prepare()`。

- `DB = ll_agentctl_verbs_{pid}_{secrets.token_hex(3)}`。
- 拒绝 `agent_v13_` 前缀和 `agent_v13_longloop_p0_probe`。
- `probe_extension`：`stannum`、`pg_jsonschema` 缺一即失败。
- 同名已存在则退出，不 DROP、不接管。`CREATED` 仅在 `CREATE DATABASE` 成功后为 true。不预先 DROP。
- `load_stage(..., "agentctl")`，装到 40。41 的 SQL 由 gate 在安装前快照提交之后 `run_psql`。
- 连接用 `get_server()` 的本地 URI。不另查是不是 Unix socket。不调用 `poison()`，不用真实 provider。
- 测试从 setup 之前进入 try/finally。只在 `CREATED` 时 `DROP DATABASE ... WITH (FORCE)`。清理失败使进程非 0。不要在 DROP 成功前打印最终成功结论。

可以导入 `mock_from_needed`、`set_mock`、`r0_source_scope`。不调用旧 setup/main。本地保留 connect、check、savepoint、快照和计数助手。

安装比较在行为夹具之前：

- 既有 `public.v13_*` 与 `v_goal_tree` 的定义哈希、属主、DEFINER、ACL、波动率：除两个谓词外全部不变。两个谓词只允许函数体变化。
- 新增函数恰为三个包装。tools 新增恰三个名字；`agentctl_observe` 与其余旧行逐列不变。
- revision +3；candidate revision 不变。
- 无新表、列、索引、触发器。安装期 `events` 与 `effects` 计数不变。
- route policy 新增恰 `controller` / 1 且 frozen。thresholds 新增恰为 default/2 副本加 16 条，无 `triage`。`default` / 2 带集不变。
- `v13_policies` 新增恰 `controller_surface` / 1，active，value 与 §3.7 的 JSON 相等。
- 冻结目录含三个新 sql 名，调用目录函数不得 `RAISE 'is VOLATILE'`。
- 自身 gate 再断言 stage 40 的四个路径相对 `a19aefc` 未偏离。不得改 `test_agentctl.py` 去适配 41。

`main` 开头调用 `r0_source_scope()`。因此跑 verbs gate 之前四个新路径必须已经 `git add`。

### 3.13 取舍

| 选择 | 不用的另一头 | 理由 |
|---|---|---|
| 新文件里替换两个谓词 | 改 `v13_spawn.sql`，或只改其中一个 | spawn 文件字节被钉住。触发器是 `IS NULL OR NOT writer_ok`，只改一个会在插入或目录冻结时失败 |
| 按成功夹具分支 jsonb | 三个 handler 共用四表 jsonb | writer_ok 做精确相等。共用四表会把没写过的 `artifacts` / `latches` 记成目标 |
| 形状 / 政策 / 授权用 RAISE | observe 的 `{ok:false}` | 成功 JSON 会被 sql 臂记成 succeeded。写失败必须进异常子事务 |
| 政策先于授权 | 先 `v13_control_authorized` 再查政策 | 后一种顺序会用不同错误词确认目标是不是直接子会话 |
| 统一文案 `v13: agentctl args` / `v13: agentctl policy` | 按动词拆文案，或回显 `unknown session %` | 测试 needle 稳定；不回显 uuid |
| 返回值带 caller，不带 attempt/fence | 答案返回省略 caller，或把 RETURNING token 放进 jsonb | 事件行没有 caller。token 已在 effect 行上。父计划禁止为了补 uuid 加列，同样不把 token 塞进返回去扩闭集 |
| 领用写在包装里 | `v13_claim` 或锁 13002 | 那是 I4。包装要的是这一行的 attempt/fence，交给六参 complete |
| 不是 `accepted` 就 RAISE | 把 `stale` / `replay` 当成成功 | 那两个词不回滚已经发生的领用 |
| 测试事务里临时改新函数的 fence 实参 | 给产品加 fault 参数，或只测底层 complete | 父计划要求证明包装本身。替换必须在 parse 之前，因为它拨 `tools_revision`，不是因为 digest。故障定义必须回滚，不得进提交 |
| parse 之后再对齐 `context_active_revision` | 挪到 parse 之前 | stage 40 已绿的位置就是 parse 之后（`test_agentctl.py:693-698`）。省掉则 `v13_context_fresh` 失败，advance 返回 `waiting`，不是 triage 失败。水位七项不含这一列 |
| 三次独立路由 | Python 里 steer→answer→cancel | 那会变成第三条写通道。场景（stage 42）不走这套 parse |
| 生产者可提交，正文消费保持未关闭 | 找到消费者之前禁止提交，或把消费断言改成通过 | 已提交 D-3 要的是覆盖，不是预先存在的读者。名为消费已发生的断言不得通过。红的 gate 仍不得留在 `main`。残项记在台账 |
| 不实现 `actl_driver_demoted` | 改冻结的 `driver.py` | S2 范围合同没有这项 |

---

## 4. File-by-file impact

本计划文件不进实现提交。生产者提交的代码闭集是前六个文件。两条 gate 都退出 0 之后，同一提交再加入矩阵、台账，以及 parity 上追加的勘误段。正文消费闭合不是加入这三份文档的条件。不加入 `v13/goal_workflow/`。

| 文件 | 变更 | 原因 |
|---|---|---|
| `v13/agentctl_verbs/v13_agentctl_verbs.sql` | 新文件：两个替换、三函数与 ACL、三行 tools、两份政策 | W2。不编辑 spawn |
| `v13/agentctl_verbs/setup_db.py` | 新文件：库名 `ll_agentctl_verbs_*`，装到 `agentctl` | W3。不应用本 stage SQL |
| `v13/agentctl_verbs/test_agentctl_verbs.py` | 新文件：安装差、§3.8–3.10 的断言；最后一项是残项仍开放，`CONSUMER` 保持 `None` | W4 |
| `v13/agentctl_verbs/README.md` | 新文件：合同，以及「正文消费未闭合。退出码 0 不表示 payload.text 已被消费，也不授权『取代 R11』」。实跑记录留到 W5 | 首轮 gate 前必须被跟踪 |
| `v13/load.py` | 两个容器尾部各一行 | W1 |
| `v13/plan_arm/test_plan_arm.py` | 仅两个函数体 | W1。`r0_source_scope` 不动 |
| `docs/reviews/v13-control-plane-conformance-matrix-2026-09-26.md` | 仅 W5。`## Stage 41` 与一行。现末号 86，实施时用当前最大 +1 | 两 gate 都退出 0 之后 |
| `docs/reviews/v13-control-plane-deviation-ledger-2026-09-26.md` | 仅 W5。新开 `## Stage 41`，含 S41-D3 未关闭。不改 F22，不改 S40-1 / S40-D2。不写「已取代 R11」 | 同 W5 |
| `docs/reviews/v13-control-plane-parity-rpce-loopx-2026-09-26.md` | 仅 W5。在 D-2 勘误段之后追加 R11 勘误段。不改 R11 表行，不改 D-2 段，不用「取代」 | 同 W5 |

不修改：`v13/spawn/v13_spawn.sql`、`v13/agentctl/**`、`v13/acl/**`、`v13/real_chain/**`、`v13/plan_arm/v13_plan_arm.sql`、`v13/catalog/**`、envelope、triage、memory、resolve、drivers、设计稿、裁决记录、调查报告。R11 原句（`docs/reviews/v13-control-plane-parity-rpce-loopx-2026-09-26.md:241`）与既有 D-2 勘误句保持不动。parity 只在 W5 追加勘误段，不改 R11 表行，不改 D-2 段。不写取代关系。

W5 的矩阵行格式与第 86 行相同：`# | 条文 | 状态 | 测试落点 | 缺口`。条文只写生产者：三个 DEFINER 写动词、`controller` / 1、`controller_surface`、Fake 根夹具打到 sql 臂、`spawn_subsession.enabled` 仍为 true。状态 ✅ 只在两条命令都退出 0 之后填写。退出码 0 不表示正文已被消费。缺口写明：注入事件不证明消费；R11 未被取代；不得写成「D-3 已闭合」或「S2 全链 gate 已满足 D-3」；不实现 stage 42–45；不实现 `actl_driver_demoted`；不证明 CE 进程控制、wake 或无人值守。

W5 的台账至少三行：交付边界（三员、两份政策、谓词只在新文件替换，spawn 字节未改）；`2026-10-03 双车道复访，父签认关闭。本次扩 v13_named_sql_writer 不重开 spawn 档。`；`S41-D3 未关闭`：九个非消费者照列，处置是不发明消费者。不写「已取代 R11」，不写「D-3 已闭合」。parity 只追加勘误段，不改 R11 原句，不改 F22。

README 在 W4 就写清签名、DEFINER、actor、请求键、载荷键、1..1024、三份 jsonb、fail-close 文案、两个窗口的差别、两条 gate 命令，以及「正文消费未闭合。退出码 0 不表示 payload.text 已被消费，也不授权『取代 R11』」。删掉「本 gate 不得退出 0，不得提交」。

---

## 5. Risks

| 风险 | 处置 |
|---|---|
| 用读回事件、session_log、watermark，或给 `CONSUMER` 赋值来冒充正文消费 | 残项检查要求 `CONSUMER is None` 且九个非消费者原样列出。不得新写消费者来换绿 |
| 只替换一个谓词，或共用四表 jsonb | 插入时 `sql writer closed`，或差集不等。两个函数同事务，在 tools INSERT 之前 |
| observe 被写进白名单 | 替换之后再断言 named 为 NULL |
| DEFINER 被当成 operator | 不授予 route 成员。非子会话零写。actor 是 `p_sid` |
| 属主缺某条特权，包装 42501 | 停止并核对。不追授旧函数，不放宽安装比较。不授予 route 成员 |
| sql 臂的 `turn/route` 和 failed effect 被算进 write_targets | 差集只取直接调用成功窗口 |
| stated 留在 0.1，或省掉 override，用改 envelope 修绿 | 停在夹具顺序上 |
| 形状失败做成 JSON，sql 臂记成成功 | 写动词 RAISE。路由形状例的 effect 是 failed |
| `stale` 被当成成功，领用残留 | 不是 `accepted` 就 `RAISE EXCEPTION`，函数内无 `EXCEPTION ... WHEN` 捕获块 |
| 函数体内注释写出禁词，writer_ok 拒绝插入 | 说明写在 `$fn$` 外 |
| `replace` 误伤 `v13_agentctl_verbs.sql` | 文件名负例使用 `count=1` |
| 未来负例仍追加 verbs/41，放行被自己的负例打红 | 未来目录固定 `v13/goal_workflow/`，编号 42 |
| 测试库清理误删已有库 | 唯一名字；`CREATED` 仅在 CREATE 成功后为真 |
| 矩阵 ✅ 写在两条 gate 退出 0 之前，或 ✅ 的条文声称正文已被消费 | W5 只在两次退出码 0 之后。条文只写生产者。缺口写明消费未闭合、R11 未被取代 |

无新表、无事件回填、无 `default` / 2 迁移。已冻结的 `controller` / 1 若将来要改带，用新的 `(name, version)`，不 UPDATE value，不回 draft。

实施时核对，不构成新产品选择：两个基线 `fb295ac6c7459bb98dac57e37883af549d2d8a4c` 与 `78e77c710bf06a0a1c771b822a3837c5db4c66d0` 必须能 `git cat-file`。缺失则停止，不换成 HEAD。导入 `mock_from_needed` 不得跑进 `test_loop` 的 `main`。`pg_stat_xact_user_functions` 不可用时报告环境阻塞。

---

## 6. Implementation order and verification

### 6.1 实施顺序

1. 确认工作区没有会混进将来那一次提交的无关修改。`v13/load.py` 尾部是 `agentctl: 40`。两个 Git 基线可读。`v13/spawn/v13_spawn.sql` 与 `fb295ac` 字节相同。不改旧 gate 去适配。

2. W1–W3 一起写到可运行。四个新文件同时出现。README 先写合同，以及「正文消费未闭合。退出码 0 不表示 payload.text 已被消费，也不授权『取代 R11』」。删掉「本 gate 不得退出 0，不得提交」。`load.py` 只追加两行。`test_plan_arm.py` 只改两个函数体，含 §3.11 的 needle 重锚。不得单独提交放行。

3. W4 的全部断言。`main` 最后调用 `actl_steer_body_residual_open`。`CONSUMER` 保持 `None`。没有名为 `actl_steer_body_consumed` 的 `check`。全部 mock。

4. 首次 gate 前按路径暂存：

```bash
git add -- \
  v13/agentctl_verbs/v13_agentctl_verbs.sql \
  v13/agentctl_verbs/setup_db.py \
  v13/agentctl_verbs/test_agentctl_verbs.py \
  v13/agentctl_verbs/README.md \
  v13/load.py \
  v13/plan_arm/test_plan_arm.py
```

禁止 `git add -A`、`git add .`，禁止暂存 `v13/goal_workflow/`、`v13/spawn/v13_spawn.sql` 或 stage 40 文件的新改动。本计划文件不暂存。

5. 按这个顺序跑：

```bash
UV_FROZEN=1 uv run python v13/agentctl_verbs/test_agentctl_verbs.py
UV_FROZEN=1 uv run python v13/plan_arm/test_plan_arm.py
```

当前合法结果：两条命令都退出 0。`plan_arm` 退出 0。verbs gate 的最后一项是残项仍开放，不是消费已发生。其他失败先修根因，再暂存同一组路径重跑。`changed existing test` 出现时撤回越界编辑。禁止把残项检查改成读事件行、`v13_session_log` 或 watermark。禁止设置 `CONSUMER`。

6. 仅当第 5 步两条命令都已退出 0，才做 W5，并且与生产者同一次提交。矩阵追加 Stage 41 行，条文只写生产者，缺口写明注入事件不证明消费、R11 未被取代、不交付 stage 42–45。台账新开 Stage 41，含「2026-10-03 双车道复访，父签认关闭。本次扩 v13_named_sql_writer 不重开 spawn 档。」以及 **S41-D3 未关闭**。parity 在 D-2 勘误段之后追加一段，不改 R11 表行，不改 D-2 段，不用「取代」。不写「D-3 已闭合」。不写「S2 全链 gate 已满足 D-3」。一次性库由 gate 的 `finally` DROP。不把本计划文件或 `v13/goal_workflow/` 加进提交。

7. 按路径暂存 W5 的矩阵、台账、parity 与已经改过的 README。对最终树重跑第 5 步两条命令，两者都退出 0。然后才允许：

```bash
git commit -m "v13: add agentctl steer answer cancel"
git push origin main
```

不使用 `--no-verify`，不改写历史，不 force-push。hook 失败修根因。stage 42 不在这一笔里。本规划任务不执行该提交。

### 6.2 验收清单

生产者提交前，工作区必须已经成立的：

- 装载尾是 `agentctl_verbs: 41`，1–40 前缀不变，`v13/goal_workflow/` 仍被合成负例拒绝。
- 生产新增恰三个 VOLATILE DEFINER 函数、三行 enabled sql 工具、`controller` version 1 冻结、`controller_surface` version 1 active。
- 两个谓词的替换只在新 SQL 里；spawn 字节仍等于 `fb295ac`；observe 的 named 仍是 NULL；`mutating` 仍是 false。
- 三份成功差集分别是 `["events","sessions"]`、`["effects","events","sessions"]`、`["effects","events","sessions"]`。临时表不在集合里。
- 形状、政策、授权都在写之前 RAISE，文案分别为 `v13: agentctl args`、`v13: agentctl policy`、`v13: session not found`。
- answer 不调用 `v13_claim`；complete 的 status 字面量是 `succeeded`；非 `accepted` 与领用后的异常都让 effect 回到 `ready`。
- 粘性第二次 cancel 不增加 `cancel/requested`，返回不是 `replay`。
- 三条路由夹具彼此独立；无 override 时 handler 不被调用。
- `v13_spawn_owner` 不是 superuser，也没有 `v13_route` 的 USAGE。包装源码没有一参 cancel 和五参 complete。
- `spawn_subsession.enabled` 仍为 true。`r0_source_scope` 未改。

提交前必须已经成立的：

- `test_agentctl_verbs.py` 与 `test_plan_arm.py` 都退出 0。
- 矩阵 Stage 41 行在那两次退出 0 之后才标 ✅，条文不声称正文已被消费。
- 台账有 S41-D3 未关闭，没有「已取代 R11」。

必须仍然不成立的：

- 任何「steer 正文已被目标消费」「D-3 已闭合」「S2 全链 gate 已满足 D-3」的句子。
- `CONSUMER` 不是 `None`。
- 名为 `actl_steer_body_consumed` 的断言通过。
- 本提交含 `v13/goal_workflow/`。

**交付结论只能是：三员、政策行和写者分支已交付；D-3 的身份、授权、零写、watermark 已覆盖；正文消费未闭合。退出码 0 不是「D-3 已闭合」。不能据此声称 stage 42–45、CE 进程控制、wake、真实 provider 或无人值守已经交付。**

## References

- 父计划：`docs/plans/v13-three-layer-goal-workflow-plan-2026-10-06.md`（夹具顺序 `:185`，S2 `:369`，PR Plan 第 2 项 `:731`）
- 对照写法：`docs/plans/v13-stage40-agentctl-observe-2026-10-08.md`
- 裁决：`docs/reviews/v13-agentctl-da-rulings-2026-10-03.md`
- 矩阵末号 86、台账 F22 与 Stage 40 节、parity R11 `:241`
- 调查：`docs/investigations/v13-s1-s2-e-i-four-step-survey-2026-10-06.md`
- 活体：`v13/load.py`、`v13/plan_arm/test_plan_arm.py:327-713`、`v13/spawn/v13_spawn.sql:42-49,279-315,1631-1686`、`v13/catalog/v13_catalog.sql:36-52`、`v13/acl/v13_acl.sql:74-470`、`v13/schema/v13_core.sql:62-93,455-519,701-725`、`v13/control/v13_control.sql:102-142,421-482`、`v13/manifest/v13_manifest.sql:33-36`、`v13/real_chain/v13_real_chain.sql:79-160`、`v13/agentctl/test_agentctl.py:299-333,356-368,693-698`、`v13/plan_arm/v13_plan_arm.sql:359-368,404-466,771-813`、`v13/loop/advance.sql:169-182`、`v13/acl/test_acl.py:115-119`
