# 给 v13 写一个工具：实操教程

> 回答一个问题：**「给 v13 加一个工具，到底要写哪几件东西？」**
> 概念依据：`docs/tutorials/v13/chapters/06-tool-catalog.md`（目录是表，可见性是查询）。
> 本文按**当前已落地的代码**（DP1–DP8 + DP9 在途，`v13/` 15 个 stage）写，每条带源码锚点；
> 教程 ch6 描绘的"目标形态"列（`input_schema`/`mutating`/`allowlist`/`timeout_ms`/`consumes`/`produces`）
> **尚未落地**（DP10 §7.3 明确列为不做）——不要照着它们写。

---

## 0. 三十秒心智模型

**工具不是代码注册，是 `tools` 表里的一行。** 除这一行外，你要写的全部东西属于四类：

| 要写的东西 | sql 档 | tool 档 |
|---|---|---|
| ① 目录行（`INSERT INTO tools`） | ✅ 必写 | ✅ 必写 |
| ② handler 落点 | SQL 只读函数 `(uuid,jsonb)->jsonb` | worker 进程里的一个分派分支 |
| ③ 参数的阈值带（仅当有参数） | ✅ | ✅ |
| ④ gate 测试 | ✅ | ✅ |

**框架零改动**：判断面自动把你的工具编进问题集（`v13_needed_judgments`）、
路由自动能选中它（`v13_route` P4）、建账/结算/事件/恢复全部自动。
「新增工具 = INSERT 一行 + 起一个 worker（如果是新 handler）」在 v13 是字面成立的。

两档的分界**是有无外部 IO**，不是 SELECT vs 写库：

| | `kind='sql'` | `kind='tool'` |
|---|---|---|
| 外部 IO | 禁止（守卫拒 VOLATILE） | 就是为此存在 |
| 执行者 | `v13_advance` 变更事务内同事务直跑（P4a 快路） | 库外 worker（P4c 慢路） |
| 队列 | 不进 | effects 账本 + pgmq 唤醒（消息可丢） |
| handler 含义 | SQL 函数名（目录即 allowlist） | worker 处理键，如 `worker:read_file_py` |
| 崩溃语义 | 整笔回滚（原子性白送） | 账本 + at-least-once + 幂等 |
| 失败恢复 | 异常落 failed effect，下一轮重路由自愈 | `complete failed/unknown`；unknown 是墙 |

> `kind='llm'` 在 CHECK 里是预留位；判断面的 `tool` choice 只收 `sql`/`tool` 行
> （`v13/resolve/v13_resolve.sql` needed 里 `kind IN ('sql','tool')`）。不要手工注册 llm 行。
> 教程 ch6.3 的「具名写允许名单」（`v13_fork`/`v13_spawn_subsession`）也未落地：
> **当前 sql 档 = 绝对只读**，没有例外闭集。

---

## 1. 动笔前的四个决定

1. **有无外部 IO？** 有 → `tool` 档；纯库内读 → `sql` 档。（AGENTS.md 不变量 4：外部 IO 一律不进事务。）
2. **要不要参数？** 要 → `param_spec` 必写，且**必须**为新参数加阈值带（§4，最容易被漏的一块）；
   不要 → `param_spec='{}'`，后面省一路。
3. **失败时副作用确定没发生吗？** 确定 → `complete failed`（自愈重试）；不确定（超时但请求可能已发出）→ 
   `complete unknown`（墙，等人工 resolve）。这个决定写在 worker 里，不是目录里。
4. **落库形态？** 运行时 DML（零 SQL 文件，DP10 已证的路线）还是新 stage SQL 文件
   （只能**追加**进 `v13/load.py` 的 `SQL_LOAD_ORDER` 末尾）？工具通常用前者。

---

## 2. 档位一：`kind='sql'`（库内只读函数）

### 2.1 你要写的三件东西

**(1) handler 函数。** 统一契约 `(session_id uuid, params jsonb) -> jsonb`，只读，毫秒级：

```sql
CREATE FUNCTION v13_tool_event_counts(p_sid uuid, p_params jsonb) RETURNS jsonb
LANGUAGE sql STABLE AS $$
  SELECT jsonb_build_object(
    'user_messages',  count(*) FILTER (WHERE type = 'user/message'),
    'tool_results',   count(*) FILTER (WHERE type = 'tool/result'),
    'routes',         count(*) FILTER (WHERE type = 'turn/route'))
  FROM events WHERE session_id = p_sid;
$$;
```

参照种子 `v13_tool_session_stats`（`v13/schema/v13_core.sql:918-925`）。
必须 `IMMUTABLE` 或 `STABLE`、返回 jsonb、`v13_route` 有 EXECUTE
（演示级只读函数保留 PUBLIC EXECUTE 也行——种子就这么做的）。
它跑在 **advance 的会话行锁内**，所以禁止 LOCK/长扫描/任何写。

**(2) 目录行。**

```sql
INSERT INTO tools (name, description, kind, handler, param_spec) VALUES
('event_counts',
 'Answer questions about event type counts in this conversation.',
 'sql', 'v13_tool_event_counts', '{}'::jsonb);
```

**(3) gate 断言**（至少这几条，见 §6/§9）：
INSERT 后 `v13_tools_meta.revision` 上升；`v13_advance` 无需任何代码变更即可路由到它
（mock `intent=sql_answer`、`tool=event_counts` → 路由 action='sql'，effect 直接终态 + `tool/result` 事件）；
`enabled=false` 后路由落 `tool_unavailable`。

### 2.2 守卫替你拦什么（写错了 INSERT 直接失败）

`v13_tools_guard`（`v13_core.sql:620-666`，BEFORE 触发器）：

- name 非空、不含 `::`；`param_spec` 每个 key 非空、不含 `::`
  （signal 身份是 `param::<tool>::<key>` 拼接式，含 `::` 会撞行）；
- description 全 ASCII（`~ '^[\x20-\x7E]+$'`）；
- **kind='sql' 且 enabled=true 的行**：handler 必须按 `(proname, 参数类型 'uuid, jsonb')`
  在 pg_proc 恰好命中一行（0=缺失、>1=跨 schema 歧义都 RAISE），且
  `provolatile IN ('i','s')`、返回 jsonb、`has_function_privilege('v13_route',…,'EXECUTE')`。

所以**顺序**：先 CREATE 函数，再 INSERT 目录行。disabled 行不校验（方便先下架再清理 handler），
但 `enabled=false→true` 的 UPDATE 必过守卫——启用时刻 fail-closed。

### 2.3 运行时链路（你一行都不用写）

```
user/message ─→ v13_parse（冻结目录+派生判断，快路 ≤1 批 32 问）
            ─→ decisions 落行（intent=sql_answer、tool=event_counts、双 gate pass）
            ─→ v13_advance → v13_route P4a → action='sql'（reason='in_db_handler'）
            ─→ 同事务 EXECUTE format('SELECT %s($1,$2)') USING sid, params   ← 你的函数
            ─→ effects 直接写终态行（kind='tool'，request={tool,params}）
            ─→ 成功：tool/result 事件；失败：handler 异常被捕获落 failed effect
            ─→ 返回 'progressed' → 驱动再 parse+advance → 收敛到 finish/llm
```

handler 的运行期错误**不会抛穿变更事务**（`v13/loop/advance.sql` ④ sql 分支的
EXCEPTION 块）：turn/route 照常提交、cycle 消耗、下一轮重路由，`turn_budget.max_cycles`（种子 3）封顶。
超时结局分流：连接声明过 `statement_timeout` 的 57014 → failed effect 自愈；
未声明分类的取消 → 原样上抛整笔回滚。**护栏执法点在驱动**：调 advance 前设
`lock_timeout≈250ms / statement_timeout≈5s`。

---

## 3. 档位二：`kind='tool'`（有外部 IO）

### 3.1 你要写的五件东西

**(1) 目录行。** handler 是开放词表的 worker 处理键：

```sql
INSERT INTO tools (name, description, kind, handler, param_spec, enabled) VALUES
('read_file_py', 'read a file (python native port)', 'tool', 'worker:read_file_py',
 '{"path": {"question": "which file",
            "stated": "user named the file",
            "options": {"hello.txt": "the fixture file to read"}}}'::jsonb, true);
```

（DP10 裁决过的形状，`docs/plans/v13-dp10-multilang-tools-plan-2026-09-23.md` §3。）
注意 `options` **必须是 object 且键=选项 choice**（decisions 的 CHECK 要求 choice 的 criteria 是 object）。

**(2) 路由策略新版本 + 阈值带**（仅当有参数；§4 详解）。种子带（intent/gate/risk/tool…）必须逐行复制。

**(3) worker 分派分支。** hub 习语（最小骨架）：

```python
row = cur.execute("SELECT v13_claim(%s, %s)", (worker, 60_000)).fetchone()[0]
# row = {effect_id, attempt_no, fence, kind, request}
req = row["request"]        # {tool, params, handler, tools_revision}
key = req["handler"].split(":", 1)[1]     # 只按 request 冻结值分派，不查活 tools 表
result = DISPATCH[key](req["params"])     # ← 全部外部 IO 在这里，两笔 DB 事务之间
cur.execute("SELECT v13_complete(%s,%s,%s,'succeeded',%s::jsonb)",
            (row["effect_id"], row["attempt_no"], row["fence"], json.dumps(result)))
```

**(4) 失败/幂等姿势。** 出站请求带幂等键（用 `effect_id`——它由 turn+cycle+request 哈希派生，
同逻辑重试同 id）；超时而副作用可能已发生 → `complete … 'unknown'`，绝不猜成 failed。

**(5) gate**（§6/§9）。

### 3.2 worker 合同速查（都是现成函数，照抄语义）

| 函数 | 语义 | 锚点 |
|---|---|---|
| `v13_claim(worker, lease_ms=60000)` | 领**全局最旧** ready 行（跨 session、无 handler 过滤——分派是 hub 的事）；SKIP LOCKED；返回 `{effect_id, attempt_no, fence, kind, request}`；attempt_no/fence 各 +1 | `v13_core.sql:267` |
| `v13_renew_lease(effect, fence, ms)` | 心跳续租；返回 false=旧 fence 已失效，**立即放弃**本 effect | `v13/twophase/v13_twophase.sql:78` |
| `v13_complete(effect, attempt, fence, status, result)` | `status ∈ succeeded/failed/unknown`；令牌 CAS（`IS DISTINCT FROM`）+ 必须 claimed；锁序 session→effect；成功且 kind='tool' 时 **SQL 自动落 `tool/result` 事件**（payload 带 `origin_user_seq`）；返回 `accepted/stale/replay` | `v13_core.sql:300` |
| `v13_requeue_stale()` | 周期调；过期 judge 在 cap 内回 ready，超 cap 转 failed；**其余 kind 过期转 unknown（墙）** | `v13_twophase.sql:33` |

重启纪律：先用行上残留的 `(attempt_no,fence)` 把自己的 claim 结算成 failed，
**再**跑 `v13_requeue_stale`——顺序反了会把可救的行收成永久 unknown。
pgmq（`v13_work`）只是唤醒，消息可丢；**认领以 effects 表为准**，不订阅队列。

### 3.3 request 的冻结形状

排队路径的 request 是 `{tool, params, handler, tools_revision}`（`advance.sql` ④ tool 分支，turn 6 #42）：
创建 effect 时 handler 与 tools_revision 已从信封冻结面抄进 request，
worker **只按 request 分派、零活表依赖**。目录后来怎么改，在飞行的这一单仍按授权时点语义执行；
变更经 `tools_revision` 让下一次 parse 弃批生效。

---

## 4. 参数与判断面（最容易漏的一块）

### 4.1 判断问自动从目录派生

`v13_needed_judgments`（`v13/resolve/v13_resolve.sql:55`）每个 turn 生成：

| signal | kind | 来源 |
|---|---|---|
| `intent` | choice | 固定（sql_answer/tool_action/llm_generate/human_escalate） |
| `gate_action` / `gate_off_topic` | noul | 固定 |
| `risk` | score | 固定（0..3 档） |
| `tool` | choice | **目录里有 enabled 的 sql/tool 行才生成**；criteria = `{name: description} ∪ {none:…}` |
| `param::<tool>::<key>` | choice | **你的 param_spec 每个键自动两问** |
| `stated::<tool>::<key>` | noul | 同上 |

所以 INSERT 一行目录，判断面的问题集自动变——不需要（也不允许）去改判断代码。
改 `v13_needed_judgments` 函数体会被 DDL event trigger 记入
`candidate_generation_revision`（探针第七键），触发保守弃批。

### 4.2 参数闭环：没有带 = 参数永远不进 request

`v13_resolve_tool_params`（`advance.sql:59-77`）的规则：某参数仅当
`stated::<tool>::<key>` 的 noul **命中 pass 带**才收 `param::<tool>::<key>` 的 choice；
否则省略该参数、工具默认值生效（**绝不猜值**）。
而 `v_routes` 对 thresholds 是 INNER JOIN——**没有带行=不命中=参数静默丢失，worker 收不到 path**。

### 4.3 带只能加在 draft 版本（完整序列）

thresholds 挂在路由策略版本上；`v13_thresholds_insert_guard` 只许往 draft 插带，
sessions 只能引用 frozen 版本（`v13_core.sql:449-473, 526-556`）。种子顺序即部署教程：

```sql
-- ① 建新版本（draft）
INSERT INTO v13_route_policies (policy_name, policy_version) VALUES ('default', 2);
-- ② 逐行复制全部种子带（intent/gate/risk/tool/既有 param…一条都不能少）
INSERT INTO thresholds (policy_name, policy_version, signal, band_no, lo, hi, action)
  SELECT 'default', 2, signal, band_no, lo, hi, action FROM thresholds
   WHERE policy_name='default' AND policy_version=1;
-- ③ 追加你的参数带（镜像种子形状 v13_core.sql:972-975）
INSERT INTO thresholds (policy_name, policy_version, signal, band_no, lo, hi, action) VALUES
 ('default',2,'param::read_file_py::path',    1,0.60,'Infinity','pass'),
 ('default',2,'stated::read_file_py::path',   1,0.60,'Infinity','pass');
-- ④ 冻结（draft→frozen 是唯一许可的 UPDATE）
UPDATE v13_route_policies SET state='frozen'
 WHERE policy_name='default' AND policy_version=2;
-- ⑤ 新 session 在**首次 parse 之前**指向 v2（七键探针含 route_policy_version）
INSERT INTO sessions (session_id, route_policy_name, route_policy_version)
VALUES (gen_random_uuid(), 'default', 2);
```

不带参数的工具（`param_spec='{}'`）不需要这一步——种子 ('default',1) 已经够了。
`risk` 的 reject 带（≥2.25→human）种子就有：tool 档路由前先过风险否决（P4b）。

---

## 5. 改目录/改 handler 的后果（revision 与 stale）

- **任何 tools DML**（INSERT/UPDATE/DELETE，含改 description、disable）→
  `v13_tools_meta.revision` 行级 bump（`v13_core.sql:687-698`）→
  parse 与 advance 之间在途信封探针失配 → advance 返回 `stale` → 调用方重 parse。
  通常零新增判断调用、一轮收敛；新 turn 自然按新目录出题。
- **sql handler 的 `CREATE OR REPLACE`/`DROP`** → DDL event trigger 也会 bump revision
  （`v13_core.sql:987-1106`）——换函数体不换目录行，逃不过弃批。
- 下架：`UPDATE tools SET enabled=false`（handler 已丢也允许，disabled 行不校验）；
  目录行保留时路由落 `human/tool_unavailable`（fail-closed）。DELETE 也行（DP10 E1 习语：
  删后 count 恢复、revision 再 bump）。

---

## 6. 跑通最小剧本（gate 怎么写）

gate = 独立可跑脚本，`uv run python v13/<stage>/test_<name>.py`，退出码 0 = 通过（不是 pytest）。
现成助手都在 `v13/loop/test_loop.py`（有 main guard，可直接 import）：

```python
from v13.loop.test_loop import mock_from_needed, claim_pinned   # :78-130

# GUC 三件套（envelope 级加载起，缺 provider/model → V3002 响亮失败）：
#   typesafe.provider / typesafe.model —— 会话级 set_config(..., false)
#   typesafe.mock_response            —— 每个 parse 前事务级 set_config(..., true)
snap = parse(cur, sid,                       # parse() = set_mock(mock_from_needed(...)) + v13_parse
    intent      ={"type":"choice","choice":"tool_action","probabilities":{"tool_action":0.9},"confidence":0.9},
    gate_action ={"type":"noul","noul":0.9},   # mock 默认 noul=0.1 会 FAIL，必须覆盖
    risk        ={"type":"score","score":0,"confidence":0.9},
    tool        ={"type":"choice","choice":"read_file_py","probabilities":{"read_file_py":0.9},"confidence":0.9},
    **{"stated::read_file_py::path":{"type":"noul","noul":0.9},
       "param::read_file_py::path":{"type":"choice","choice":"hello.txt",
                                    "probabilities":{"hello.txt":0.9},"confidence":0.9}})
assert snap["remaining"] == 0                # tripwire：目录变大时快路装不下会 >0（judge 慢路）
r = cur.execute("SELECT v13_advance(%s,%s::jsonb)", (sid, json.dumps(snap))).fetchone()[0]
assert r == "waiting"                        # tool 档 → enqueue + 唤醒
row = cur.execute("SELECT v13_claim('w1',60000)").fetchone()[0]
assert row["request"]["params"] == {"path": "hello.txt"}   # ← 参数闭环的证据
```

断言面建议（对照 DP10 C/D 组）：revision bump、路由 action 序列（tool→…→llm→finish）、
`request.params` 内容、`tool/result` 事件 payload、effect 终态、幂等（重复 complete 返回 `replay`）、
目录恢复（DELETE 后 count 回基线）。提交前 14 个既有 stage gate 复跑（12 必绿；
envelope/twophase 的已知 demo 扫描红按 DP10 裁决 7 豁免核对）。
提交纪律照 AGENTS.md：按路径 add、`v13: <祈使句摘要>`、push 不 force。

---

## 7. 常见误区（不要写的东西）

- ❌ **注册代码/装饰器/摘要拼装**——目录是表；判断、路由、派发读的都是表/信封。
- ❌ **sql 档函数里做写或外部 IO**——守卫拒 VOLATILE；provolatile 只是声明，STABLE wrapper
  也别阻塞（跑在会话锁内）。
- ❌ **worker 查活 tools 表分派**——只按 `request.handler`（冻结值）。
- ❌ **改 `v13_needed_judgments` 给工具硬编码信号**——目录行自动派生；函数体漂移会 bump cgr。
- ❌ **往 frozen 策略版本加带**——被拒；新带=新版本 draft→插→freeze→session 指过去。
- ❌ **忘了 session 要指向新策略版本**——七键探针含 `route_policy_version`，旧版本无你的带，参数永远丢。
- ❌ **超时猜成 failed**——副作用可能已发生时必须 `unknown`；`mutating` 列式的分流在 v13 落在
  worker 的 complete 姿势里，不在目录里。
- ❌ **在 SQL 文件里写 `set_config('typesafe.mock_response',…)`**——envelope/twophase 的
  源码扫描 gate 会红；mock 只在测试进程里。
- ❌ **以为要动 `SQL_LOAD_ORDER`**——纯工具交付是零 SQL 文件（运行时 DML）；
  只有新 stage 的结构性 SQL 才追加表尾。

---

## 8. 源码锚点速查

| 部件 | 位置 |
|---|---|
| tools DDL + 双守卫 + revision | `v13/schema/v13_core.sql:579-698` |
| 种子目录（sql/tool 两行范本）+ 种子带 | `v13_core.sql:911-984` |
| needed 派生（问题集从目录长出来） | `v13/resolve/v13_resolve.sql:55-148` |
| 目录冻结 + sql handler 结构执法（冻结半边） | `v13_resolve.sql:192` 起 `v13_tools_catalog_frozen` |
| 路由 P4a/P4b/P4c/P4d + 参数闭环 | `v13/loop/advance.sql`（`v13_route`/`v13_resolve_tool_params`） |
| advance ④：sql 快路 EXECUTE/异常出口；tool 慢路 request 冻结 | `advance.sql` `v13_advance` |
| claim / complete | `v13_core.sql:267 / :300` |
| requeue_stale / renew_lease | `v13/twophase/v13_twophase.sql:33 / :78` |
| DDL event trigger（handler 漂移 bump） | `v13_core.sql:987-1106` |
| 完整实战蓝本 | `docs/plans/v13-dp10-multilang-tools-plan-2026-09-23.md`（read_file_py/swift 全流程） |
| 本地活样例（gitignored） | `v13/demo/`（Chainlit + PostgREST + hub 拨格） |
| 测试助手 | `v13/loop/test_loop.py:53-130`（`parse`/`mock_from_needed`/`claim_pinned`） |

---

## 9. 交付检查清单

- [ ] 档位选对：外部 IO → `tool`；纯库内读 → `sql`（先建函数再 INSERT，守卫要验）
- [ ] name / param key 无 `::`；description、question、stated 全 ASCII；`options` 是 object 且键=choice
- [ ] 带参数：策略新版本（复制全部种子带 → 追加 param/stated 带 → freeze → 新 session 指定版本）
- [ ] tool 档：worker 按 `request.handler` 分派；外部 IO 全部在两笔 DB 事务之间；出站带幂等键
- [ ] 失败姿势想清楚：确定无副作用 → failed；不确定 → unknown
- [ ] gate 断言：revision bump、零代码路由、参数进 request、终态、幂等 replay
- [ ] 14 个既有 stage gate 复跑达基线
- [ ] 提交：按路径 `git add`、`v13: <祈使句摘要>`、`git push origin main`（不 force）

---

*与规范冲突时以冻结设计（`docs/designs/v13-context-on-pg.md` 及 errata）为准；
本文只是把它们拼成「照着写就能过」的顺序。*
