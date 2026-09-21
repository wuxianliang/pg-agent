# v13/schema — DP1 M1 核心切片

> Gate:`uv run python v13/schema/test_schema.py`(仓库根,退出码 0 = 通过)。
> 库:`agent_v13_schema`(setup_db DROP/CREATE 自建,**必须超级用户连接**)。
> 计划权威:`docs/plans/v13-dp1-two-phase-advance-plan-2026-09-20.md` §3.1 + §4 M1 表;
> 后续修订优先:「v2 对齐修订」A1–A5、「R2 对齐修订」#50/A17 + A1 + P4a;
> errata:`docs/designs/v13-errata-2026-09-21.md` E2/E4/E6。

## 产出

| 文件 | 内容 |
|---|---|
| `v13/load.py` | `SQL_LOAD_ORDER` / `files_through` / `run_psql` / `load_stage`(机制自 `v12/load.py` 复制,V13 路径,**不 import v12**) |
| `v13/schema/v13_core.sql` | 日志面(ch1)+ effect 账本(ch2)+ 判断面(ch4)最小切片 + tools 最小切片 + 路由策略版本父表/带表 + 策略行载体 + 三角色 ACL 矩阵 + 目录 revision 双 bump 面 |
| `v13/schema/setup_db.py` | DROP/CREATE `agent_v13_schema` + `load_stage(s, DB, "schema")` |
| `v13/schema/test_schema.py` | §4 M1 表 14 条断言(共 182 个 `check`) |

M1 的 `SQL_LOAD_ORDER` 只含 `v13/schema/v13_core.sql`,`STAGE_THROUGH = {"schema": 1}`;
M2/M3/M4 各自**纯末尾追加**自己的 SQL 与 stage 键。

## 部署前置(生产必读)

- **超级用户**:`v13_core.sql` 里 `DO` 块 `CREATE ROLE`(集群级)与两个
  `CREATE EVENT TRIGGER`(`trg_tools_ddl_bump` / `trg_tools_ddl_bump_drop`)都需要超级用户。
  dev setup 以 `postgres` 连接;生产建库/加载同样需要超级用户,之后的运行期连接
  走下面的双登录角色,不需要超级用户。
- **扩展**:`pgcrypto` / `typesafe` / `pgmq`(本仓由 pgembed 0.3.0rc2 打包)。
  `SELECT pgmq.create('v13_work')` 建唤醒队列。
- 角色是集群级对象:`DO` 块只 `IF NOT EXISTS` 创建、只 `GRANT` 不 `DROP`,
  多 stage 库共享同一套角色。

## 六条运营纪律(计划 §4 收尾要求,逐条必读)

1. **调用者必须成对调用 `parse` + `advance`**(§3.4 契约)。解析事务只补判断、
   不碰会话锁;变更事务只建账/路由/扣预算。单调 `parse` 不推进 turn;单调
   `advance` 拿不到当轮判断。两相之间的水位/策略/目录变化由 `advance` 步 0
   的**七键探针**比对检出 → 返回 `'stale'` 弃批,调用者重 `parse` 再 `advance`。
   探针七键固定为 `session_version` / `max_event_seq` / `goal_hash` /
   `route_policy_name` / `route_policy_version` / `tools_revision` /
   `candidate_generation_revision`(A3/D2:**零结构增量,禁第八键
   `ws_revision`**;未来 workspaces 作用域列 DML 并入 `tools_revision` bump +
   `ws_scope_changed` 审计事件)。
2. **驱动必须周期调用 `v13_requeue_stale()`**(M4 落地)。队列 at-least-once
   只是唤醒,消息可丢,表才是真相。lease 过期的 `claimed` 行按 kind 分流:
   `judge` → `ready`(纯判断幂等,可重放);`tool`/`llm`/`human`/
   `context_refresh` → `unknown` **墙**(外部副作用可能已发生,不盲重放,
   ch12 显式 resolve 是唯一出口)。两路只推 **fence**、**不动 `attempt_no`**
   (`attempt_no` 语义=claim 次数,唯一递增点是 `v13_claim`)。judge 的回收受
   共用 `effect_attempt_cap` 约束:超限转**可结算 `failed`**
   (`error->>'code'='lease_exhausted'`)并**唤醒 settle**,由 advance 终结
   turn——不存在「过期→ready→claim」无限循环。
3. **driver/worker GUC 一致性**。判断哈希只用**信封冻结的** `provider`/`model`
   (以及 `route_policy_name`/`version`、`tools_revision`/`tools_catalog`、
   `candidate_generation_revision`),不用调用时的 GUC 现值——worker 换连接、
   换 GUC 都不得让剩余缺口的哈希漂移。`typesafe.mock_response` 与
   `typesafe.timeout_ms` 一类 GUC **只在测试**里设置(事务局部
   `set_config(..., true)`),**禁止随生产配置下发**;生产断言新鲜连接的
   `current_setting('typesafe.mock_response', true) IS NULL`。
4. **worker 出站调用必须携带 `idempotency_key`**。新 effect 行的键恒为
   `'v13:' || effect_id`,**同 ID 重挂(fence+1)不换键**——worker 要把它传给
   外部系统做去重,否则重挂后的重试在外部世界产生第二次副作用。
5. **登录角色:生产强制双登录**。三个 ACL 角色(`v13_recall` / `v13_resolve` /
   `v13_route`)一律 `NOLOGIN`。生产用 `v13_resolve_login`(只入 `v13_resolve`
   组)与 `v13_route_login`(只入 `v13_route` 组)两个**单成员**登录角色:
   跨平面进程(driver/worker)开**双连接池**——判断面(`parse` /
   `resolve_judgments`)走 resolve_login 连接,建账结算面(`advance` / `claim` /
   `complete` / `renew` / `requeue`)走 route_login 连接。两相本就是两笔事务,
   双池零额外代价;`SET ROLE` 越面由数据库直接拒绝(单成员执法,不是应用约定)。
   `v13_worker`(`LOGIN NOINHERIT` 双成员)是**记录在案的退化替代**,仅供无法
   开双登录的部署:隔离纯靠应用约定、**无 DB 执法,不推荐**,gate 不为其背书。
   角色属性由 M1-7(本 stage)/ M2-10 / M3-12 断言。
6. **驱动侧时间护栏**。调用 `advance` 的连接在调用前设 `lock_timeout` /
   `statement_timeout`(建议起点 250ms / 5s)。SQL 函数体内的 `SET LOCAL` 对
   嵌套语句无效,sql 快路 handler 阻塞的执法点只能在调用层。超时结局按触发点
   分流:handler `EXECUTE` 内(唯一捕获块)→ `statement_timeout`(57014)走显式
   `WHEN query_canceled` 分支(**复用 α 分类门**:只有连接已声明
   `statement_timeout` 才吸收;未声明的取消原 SQLSTATE 上抛)、`lock_timeout`
   (55P03)走 `WHEN OTHERS`,已声明面均落 `failed` effect 自愈重路由;
   `advance` 其余位置(无捕获块)→ 任一超时=整条 advance 异常终止+回滚,
   驱动重试。配套:**`effect_attempt_cap` 翻新纪律 = 新版本必含全五键
   (`judge`/`tool`/`llm`/`human`/`context_refresh`)、降 cap 需清场**——运行期
   缺键/降 cap 属运维事故面(`v13_enqueue_effect` 在创建点 fail-loud,
   `claim`/`requeue` 侧 `coalesce` belt 拒领)。

## 与计划正文的机械偏差(逐条)

计划 §3.1 的 SQL 是**纸面校验**稿。实际加载 PG 18.4 时**首次即通过**——类型、
算子、终结符、前向引用、「移动=增+删」四类纸面风险无一触发。以下是实际发生的
改动,全部保留 gate 语义:

| # | 偏差 | 原因 / 影响 |
|---|---|---|
| D1 | **新增 `GRANT SELECT ON effects TO v13_route;`** | 草案 ACL 矩阵写「route = recall ∪ {INSERT/UPDATE effects…}」,而 recall 的只读七表不含 `effects`。PG 要求 `UPDATE … WHERE` / `SELECT … INTO` 引用的列具备 SELECT 权限,故 `v13_enqueue_effect` / `v13_complete` 在 route 手里必然 `permission denied for table effects`,M1-7 的「route → EXECUTE `v13_enqueue_effect` ✓」不可达。只补给 `v13_route`;`v13_recall` / `v13_resolve` 仍无 `effects` 读权,M1-7 的 resolve 负向断言不变 |
| D2 | **`v13_tools_guard` 落 R2 #50/A17 具名例外闭集** | 草案字面只有 `provolatile IN ('i','s')`。按 R2 终裁改为「默认拒 VOLATILE + 具名闭集(`v13_fork` / `v13_spawn_subsession` / `rag_assemble`)五条件全满足才放行」。实现取值:控制角色 = `v13_route`(DB1 的持锁建账角色);条件③ = `prosecdef` ∧ `proconfig` 含 `search_path=` ∧ `pg_get_userbyid(proowner)='v13_route'`;条件④ = `v13_route` 有 EXECUTE ∧ PUBLIC 与 `v13_recall` 均无;条件⑤ = `prosrc !~* '(dblink\|pg_net\|copy[[:space:]].*program)'`。M1 阶段闭集三函数均不存在 ⇒ **例外分支不可达,默认拒面完整生效**;M1-14 仍断言无名 VOLATILE handler 被拒 |
| D3 | **M1-10 源码扫描改测「可执行 SQL」+ 调用语法** | 计划 M1-10 字面是「`typesafe_ask` 不出现在 `v13_core.sql`」,但它要求转写的 §3.1 草案**注释里**就有三处 `typesafe_ask` 散文(远端码契约档案注、ACL 矩阵注、M2 授权落点注)。扫描因此改为:① 剥掉 `--` 注释后的可执行 SQL 中零出现;② 原始全文(含注释)中零 `typesafe_ask(` **调用语法**。不变量 2(唯一 ask 点在 `v13_resolve_judgments`)的执法强度不减——零调用点、可执行 SQL 零出现 |
| D4 | **`SQL_LOAD_ORDER` 只含 core、`STAGE_THROUGH` 只含 `schema`** | 计划 M1 产出行写 `SQL_LOAD_ORDER=[core, resolve, advance, twophase]`,但 `load_stage` 对缺失文件 `FileNotFoundError`,且 turn 7 #46 的加载边界纪律要求「每 stage 只加载到当前 stage」。M2–M4 落地时各自末尾追加(纯末尾追加纪律不变) |
| D5 | `array_to_string(p.proconfig, ',') LIKE '%search_path=%'` 代替 `proconfig::text` | 同一判定,避免数组字面量转义 |

### Gate fixture 层面的机械选择(非语义变更)

- **负向探针不用 `SAVEPOINT sp`**:M1-2 并发 append 与 M1-12 `INSERT ∥ freeze`
  串行化都要求已提交状态对并发连接可见,故测试连接走 `autocommit=True`,
  负向探针按语句捕获异常(每条仍断言具体错误串)。v12 的 `check()` /
  `fails_with()` 形态与 PASS/FAIL 打印保留。
- **M1-9 版本化断言用一次性策略名 `gate_probe`**,不改动种子行——否则后续
  断言会消费被翻掉的 `active` 行。「四行 v1 种子 active」「`effect_attempt_cap`
  含全五键」是独立断言,未弱化。
- **M1-8 相邻带/边界值需要同信号 ≥2 带**,而种子每信号恰一带(低段留空以落
  human 兜底)。gate 因此另建一次性 frozen 版本 `('t_bands',1)` 放两条相邻带,
  并用真实 `v_routes` 链路断言边界 0.75 只命中后带。全带集不重叠断言仍覆盖
  含种子在内的**所有**行。
- **M1-5(i) 缺键 fail-loud** 按 turn 10 #64 的顺序(先 INSERT v2 `active=false`
  → 翻 v1 off → 翻 v2 on → `enqueue` RAISE),用 `finally` 还原成 v1 active。
- `v13_claim` 无 session 入参(全局领取最旧 ready 行),gate 因此在每次 claim
  后断言领到的正是目标 effect,并在块结束前把 fixture effect 推到终态/删除,
  保证下一块 claim 的确定性。

### PG 18.4 实测核对(草案声称、本轮复验为真)

- `oidvectortypes(oidvector)` 存在于 `pg_catalog`(签名比较可用,免 OID 硬编码)。
- `'CREATE ROUTINE'` **被接受**为 event trigger 的 `WHEN tag` 过滤值(belt 预置
  不会让 `CREATE EVENT TRIGGER` 失败),但 `CREATE OR REPLACE ROUTINE` 是
  **语法错误** ⇒ 该 tag 当前不可达(M1-13 以负向断言锚住这条引擎契约)。
- `ALTER ROUTINE` 的 command tag 就是 `'ALTER ROUTINE'`;`DROP ROUTINE` 经
  `sql_drop` 面触发。
- `pg_event_trigger_dropped_objects().object_name` 对函数**恒 NULL**,身份只能
  取 `address_names[1]`(schema)/`[2]`(name)——草案写法正确。
- 上下文守卫矩阵:`pg_event_trigger_ddl_commands()` 在 `sql_drop` 上下文返回
  **空集不报错**;`pg_event_trigger_dropped_objects()` 在 `ddl_command_end`
  上下文报 **39P03**,被 `EXCEPTION WHEN SQLSTATE '39P03'` 接住。
- `numeric >= double precision` 走隐式提升(`v_routes` 的 `v13_signal` × 带比较成立);
  `'Infinity'::double precision` 作顶带上界可用;`'^[\x20-\x7E]+$'` 正确拒 CJK。

## 本 stage **不做**的事(避免与后续 DP 混淆)

- 不实现 `v13_visible_tools`(v2 A2 / E6:登记给后续 R0b,**不是 M1–M4 里程碑**)。
- 不加 `sessions.ws_id` / `files_cutoff` / `ws_revision`(R0a 未来增列缝;A3 明文
  禁第八键)。
- 不加 file corpus 存在性 Noul(A4 / E2:`bootstrap_done=false` 开放世界禁发)。
- `candidate_set_hash` 定义不变 = `hash(needed)`;`source_epoch` / git HEAD /
  `files_cutoff` **禁入** csh 材料(A5 + L4 F1)。
- M2 的 `v13_resolve.sql`、M3 的 `advance.sql`、M4 的 `v13_twophase.sql` 及其
  gate 全不在本 stage;本 stage 的断言只引用**已加载**对象(turn 7 #46 加载
  边界纪律),故 `candidate_generation_revision` 在 M1 恒为 0(它的 bump 源
  `v13_needed_judgments` 是 M2 对象)。
- P4a 的 `reason:'in_db_handler'`(R2 更名,原 `'read_only_handler'`)属 M3
  `v13_route` 面,本 stage 无落点。
