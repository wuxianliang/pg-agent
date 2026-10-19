# v13 时空注册面设计：spacetime registry（DB 即 harness × Cordis 注册语义）

> 状态：**v1：核验修正并入（核验报告与 oracle 裁决存档于 `prompt-exports/`，逐项已处置）。**
> 裁决输入：`prompt-exports/oracle-plan-2026-10-17-135208-untitled-chat-380da6-0e1b.md`
> （八问裁决 + 骨架修正清单）；核验输入：`prompt-exports/spacetime-verification-2026-10-17.md`
> （六项矛盾清单）；终裁输入：`prompt-exports/oracle-review-2026-10-17-142744-untitled-chat-380da6-00b9.md`
> （定稿修正清单七条，逐条处置见 §12）。
> 2026-10-17 落地评审 errata 已并入：全局注册时钟取代每 scope 计数、读面加
> `p_actor`、context 输出携 `registry revision + tools_revision` 双标量等，
> 逐条见落地计划 `docs/plans/v13-registry-stage41-2026-10-17.md` §10.3；
> Locked Decisions 以该计划 §10.1 为准。
> 本文只转写裁决、不重新诉讼。本文是设计文档：不改任何代码；文中 DDL 全部是
> **契约级示意形状**，非可执行脚本。

## 1. 命题与价值

**命题**：在 v13 上做「时空组合」整合——DB 即 harness（多语言 worker 共享 SQL
契约）与 Cordis（服务/依赖/可逆注册）真正合一，而不是并排摆放。

**两个轴**：

- **空间轴 = scope**。一个 scope 就是一个 `sessions` 行；父子关系沿用
  `parent_session_id`（`v13/schema/v13_core.sql:23`）。注册行挂在 scope 上，
  子 scope 沿祖先链继承，近端遮蔽远端。
- **时间轴 = revision**。全局 singleton 注册时钟 `v13_registry_clock` 提供
  单调修订号（2026-10-17 裁决 1，§4.2）；一次注册/退役使全局 revision
  前进一步。注册内容由 `(scope, revision)` 编址；完整 context（含可变 tools）
  的缓存身份为 `(scope, registry_revision, tools_revision)`。

**为什么是「注册语义」而不是移植 Cordis 运行时**。本仓对 Cordis 的既有调研
（`docs/investigations/cordis-workbench-plugins-2026-08-22.md`）的结论是：v1 的
`cordis_services` 只是**未接线的注册表存根**（无任何读写引用，见该文
「`cordis_services` is not wired into this path」节），真实机制是
catalog-driven dispatch；Cordis（Koishi）本体是 JS 插件/DI 内核——插件注册进
`Context`、暴露命名服务、隔离副作用、可装卸（同文「Cordis (Koishi) model —
mapping note」节）。这些语义里没有一样需要 JS 运行时才能成立：**可逆注册**、
**按名解析依赖**、**scope 遮蔽**，在 v13 里各自已有已验证的零件（§7）。移植
运行时等于在红基线上盖楼且引入第二真相源；吸收语义只需给既有零件一个统一
编址 `(scope, revision)` 和一个统一读取面。这就是整合的全部工作。

## 2. 基线声明（可证伪）

- **基线 = v99 worktree 已提交 HEAD（`cbf65cf`），工作树干净**。HEAD 版
  `v13/load.py` 的 `SQL_LOAD_ORDER` 恰 **40 项**、
  `STAGE_THROUGH["ce_run"] == 40`，尾部 = `fair_claim:39` → `ce_run:40`。
  本方案注册面在末尾纯追加，**stage 编号 = 41**。
- **ce_run（stage 40）已提交、已收口**（`683ea0e`/`60805fc`/`cbf65cf`，
  47 脚本 + 2 探针全绿，证据链见 `v13/ce_run/README.md`）。本方案与 ce_run
  **并立、不依赖其任何函数**（零 `v13_ce_*` 调用，裁决 3）；ce_run 仅作为
  「注册语义消费方」的形态参考。
- **订正（2026-10-17 v99 复核）**：本节早先版本所述「HEAD 44 项
  （`agentctl`/`agentctl_verbs`/`goal_workflow`/`external_exec`/`ce_map`
  = 40–44）」「ce_run 未提交未收口、W4 红」「工作区 load.py 替换五个已提交
  stage」均属主检出 `7db3526` 线的历史状态，对 v99 全部过时——v99 上旧
  stage 40–44 件已按 P1 退役，ce_run 为唯一 stage 40。第三方复核以
  `git show cbf65cf:v13/load.py` 为准。
- **ch08 教程是意图文档，不是代码事实**。ch08 承诺与现行代码的落差逐条进
  §8 偏差台账；落差由新层吸收，不回填旧表（Q7 裁决）。

## 3. 八问裁决摘要（转写，一句话 + 要点）

- **Q1 统一 vs 并行** → **物理并行，读取统一**：`v13_registrations` 只承载新
  kind；`tools`/`v13_policies`/`thresholds` 永不迁移，`v13_registry_context()`
  输出里以同一形状并入。理由：tools 的守卫链（写入校验→revision bump→信封
  冻结→步 0 比对）是 load-bearing；ce_run 已收口且与本面零交叉引用；Cordis
  可取的语义是「可逆注册 + 依赖解析」而非一张大表。
- **Q2 scope 粒度** → **复用 sessions，删 `ctx_nodes`**：`scope_id =
  session_id`；无 parent 的根 session 即全局 scope；可见性 = 递归 CTE +
  函数层角色谓词（无 RLS 现状下的最简形态）。
- **Q3 generation 系统化** → **全局注册时钟（2026-10-17 裁决 1 修订）**：
  generation 由全局 singleton `v13_registry_clock` 承担（种子 0、写函数显式
  分配，§4.2）；`v13_registry_meta` 降为每 scope「最后触达的全局 revision」
  诊断值，不参与读取寻址；ce_run 三
  generation 列只收编 `registration_generation` 的语义（映射仍可选，§7.4），
  另两列留 ce_run 本地。
  fence（并发令牌）与 revision（有效时间锚）正交，互不吸收。
- **Q4 解析时点** → **独立 `v13_registry_context()`，claim 只回修订号**：
  claim 响应增一个标量 `context_revision`（落点见 §5.2/§11.5），不回 context
  本体；worker 按 registry revision 与 tools_revision 双标量缓存（§4.4）。裁决依据：依赖图坏时内联解析会让**所有**
  claim 停摆；独立函数只坏解析调用，claim 仍发单、worker 持旧版降级工作。
- **Q5 双轴时间** → **不建 bitemporal**：valid-time = 注册行
  `valid_from_rev`/`valid_to_rev` 两列；system-time = 既有 append-only
  `events`；time-travel = `v13_registry_context(scope, as_of_rev)` 一个参数。
- **Q6 服务 DB-first 定义** → **成立，加一条收紧**：service = 命名 SQL 函数
  面 + scope 上的注册行；`provides` 是文本清单、**不做 pg_proc 校验**（tools
  的 ddl_bump 教训：冻结即维护面）；依赖只许依 service、只解析一层、沿祖先
  链近端遮蔽；未命中进 `unresolved` 数组，**不 RAISE**。
- **Q7 ch08 落差** → **记偏差台账 + 新层吸收，不回填旧表**：
  `handlers[]`/`interruptible` 进新 kind `tool_profile` 的注册内容；`mutating`
  已在 spawn metadata，不动。与 ce_run 关系 = 并立。
- **Q8 多语言轴** → **立场成立且被强化**：注册内容按 `(scope, revision)` 寻址，
  完整 context 需固定 tools_revision 与授权分支；同一 SQL 函数产出 ⇒ 跨语言一致
  由构造保证（同一 tools 状态下）；断言落 pg 侧三条
  （§6，H2 终裁收窄）。

**骨架修正清单**（裁决附录）：删 `ctx_nodes`（sessions.parent 即树）；删
`generations` 全局表（2026-10-17 裁决 1 修订：全局 singleton 时钟
`v13_registry_clock` + 每 scope 诊断行 `v13_registry_meta`，§4.2）；
`registrations` 收窄为 3
个 kind——`hook` 缓建（无消费方）、`policy` 永不进（`v13_policies` 已经是）；
解析函数保留强化（终裁定名 `v13_registry_context`）；claim 返 context 本体
改为只回 `context_revision` 标量。

## 4. 设计主体：四个原语 + 一组写函数

全部复刻树内已验证纪律，零新概念。以下 DDL 为**契约级示意**，落 stage 时以
评审后的可执行稿为准。

### 4.1 `v13_registrations`（注册表）

```text
v13_registrations(
  registration_id uuid PK DEFAULT gen_random_uuid(),
  scope_id        uuid NOT NULL REFERENCES sessions(session_id),   -- 空间轴
  kind            text NOT NULL
                  CHECK (kind IN ('service','tool_profile','prompt_section')),
  name            text NOT NULL,
  value           jsonb NOT NULL,                -- 形状按 kind 定（§4.5）
  depends_on      text[] NOT NULL DEFAULT '{}',  -- 服务名清单（仅 kind='service' 消费）
  valid_from_rev  bigint NOT NULL,               -- 生效的全局 revision（时间轴下沿，§4.2 时钟）
  valid_to_rev    bigint,                        -- 退役的全局 revision（NULL = live）
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (scope_id, kind, name, valid_from_rev)
)
-- 部分唯一索引：同一 (scope_id, kind, name) 同时至多一行 live
CREATE UNIQUE INDEX ux_v13_registrations_one_live
  ON v13_registrations (scope_id, kind, name) WHERE valid_to_rev IS NULL;
```

合法状态与写纪律（全部触发器执法）：

- **写路径只有两条**：注册（INSERT，`valid_from_rev` = 写函数算出的新
  revision，见 §4.2）与退役（UPDATE 设 `valid_to_rev` = 新 revision）。
  **退役是唯一许可的 UPDATE**；`scope_id, kind, name, value, depends_on,
  valid_from_rev, registration_id, created_at` 改写与 DELETE 一律 RAISE——
  复刻 `v13_policies_frozen` 的不可变纪律（`v13/schema/v13_core.sql:715-729`：
  name/version/value 改写与 DELETE 拒绝，版本行是审计轨迹），**列名单按
  本表身份列扩齐**（`registration_id`/`created_at` 在 policies 先例的身份
  名单之外，逐字照搬会漏保护——核验发现 M1，已采纳）。`valid_to_rev` 是
  唯一可动列。
- **at-most-one live** 由部分唯一索引执法，照搬
  `ux_v13_policies_one_active`（`v13/schema/v13_core.sql:708-709`）。
- 注册/退役同事务追加 `registry/registered`、`registry/retired` 事件，走
  `v13_append_event`（`v13/schema/v13_core.sql:62-93`）——事件落 **scope 本
  session 的 events 行**（`p_sid = scope`），`p_source_effect` 留 NULL
  （先例：`v13_cancel` 追加 `cancel/requested` 时不传 source，
  `v13/acl/v13_acl.sql:224`）；审计链零新表（Q5）。`v13_append_event` 非
  SECURITY DEFINER、EXECUTE 仅授 `v13_route`
  （`v13/schema/v13_core.sql:874-888` REVOKE、`:897-902` GRANT）——故写面
  合法路由是 **SECURITY DEFINER 写函数以属主身份调用**（§4.6）。
- 交互注记（终检增补，写明以免将来被当 bug 报）：注册/退役事件推进 scope
  本 session 的 `max_event_seq`（步 0 探针七键之一），该 session 的在途
  advance 会判 `stale` 重解析——**这是安全方向且语义正确**（世界变了弃批），
  见 §5.1。

### 4.2 `v13_registry_clock`（全局注册时钟）、`v13_registry_meta`（诊断值）与写函数五步契约

```text
v13_registry_clock(
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  revision  bigint NOT NULL DEFAULT 0 CHECK (revision >= 0)
)
-- 种子：INSERT INTO v13_registry_clock VALUES (true, 0);
-- 种子行缺失 = 配置事故；写面/读面均 RAISE，不做 silent fallback

v13_registry_meta(
  scope_id uuid PK REFERENCES sessions(session_id),
  revision bigint NOT NULL DEFAULT 0 CHECK (revision >= 0)
)
-- 该 scope 最后一次成功写所分配的全局 revision；无写则无行
```

- **全局时钟取代每 scope 计数（2026-10-17 裁决 1）**：早先稿的 AFTER 行级
  bump 触发器**删除不建**；只借 `v13_tools_meta` 的「singleton 行级计数器」
  形态（`v13/schema/v13_core.sql:681-694`），bump 由写函数在五步契约内显式
  执行。
- **`v13_registry_meta` 降级为诊断值**：读路径不依赖它，meta 缺失/落后不
  影响 context 正确性；gate 仍断言其等于该 scope 最后一次成功写的
  `v_new`，防静默腐化。具名消费者：运维漂移审计（按 scope 对账
  `v13_registry_meta.revision` 与 `registry/*` 事件的
  `max((payload->>'revision')::bigint)`）与未来 ce_run
  `registration_generation` 可选映射（§7.4）。

**写函数强制契约**（注册/退役共用，VOLATILE、SECURITY DEFINER、固定
search_path，EXECUTE 仅授 `v13_route`，§4.6；锁序明文：**clock → meta →
sessions（append_event 内）→ registrations**，registry 永不反向先锁
sessions 再锁 clock）：

1. **参数校验**（失败一律 RAISE，零写、时钟不动）：真实 caller 为超级用户
   或 `v13_route` 成员（经 `v13_registry_caller_role()` fail-closed 内查，
   不依赖 ACL 单层）；scope 存在；kind 闭集；name 规则（§4.1）；value 形状
   （§4.5）；`depends_on` 元素点名 kind='service' 注册行的 `name`（不是
   `provides` 条目；元素规则同 §4.1 name：btrim 非空、≤128、无 NULL/空串）、
   去重、≤64 项，且**仅 kind='service' 可非空**；
   `octet_length(p_value::text) <= 1 MiB`。
2. `SELECT revision FROM v13_registry_clock WHERE singleton FOR UPDATE`
   ——全局串行点；零行 = 种子丢失，显式 RAISE（`v13: registry clock seed
   missing`），不继续分配。并发同键注册在此串行，后到者在锁等待后重读见
   live 行，落 `already_live`。
3. **业务冲突判定（分配前）**：注册查同 `(scope,kind,name)` live 行存在→
   返回 `{schema_version:1, ok:false, reason:'already_live',
   registration_id, valid_from_rev}`（携现有 live 行身份）；退役查无 live
   行→返回 `{schema_version:1, ok:false, reason:'not_live'}`。均零写、
   **不分配 v_new、时钟不动**。退役在此取 live 行 `registration_id`。
4. `UPDATE v13_registry_clock SET revision = revision + 1 WHERE singleton
   RETURNING revision` → `v_new`；`INSERT INTO v13_registry_meta ...
   ON CONFLICT (scope_id) DO UPDATE SET revision = v_new`（惰性 upsert，
   meta 行唯一创建时机）。
5. **先事件后行**：注册先生成 `v_id = gen_random_uuid()`，
   `v13_append_event(p_scope, gen_random_uuid(), 'registry/registered',
   {schema_version:1, registration_id, kind, name, revision:v_new}, NULL)`，
   再 INSERT 行（显式 registration_id、`valid_from_rev = v_new`）；退役先
   `registry/retired` 同形事件，再 `UPDATE ... SET valid_to_rev = v_new`。
   任何失败整体回滚。

成功返回 `{schema_version:1, ok:true, registration_id, revision:v_new}`。
request_id 幂等机制**不设**——`already_live`/`not_live` 结构化返回即幂等
语义（裁决 4）。同事务 register+retire 各走一次五步、`v_new` 各自独立，
区间 `[v1,v2)` 无空档（gate：两事件 revision 恰差 1）。

**读侧时钟口径**：`p_rev NULL` 的读取以时钟当前值为准（**不是** scope
meta；时钟零行 = 种子丢失，读面 RAISE，不返回假 revision 0，§4.4）。早先
稿「revision 0 = 空注册面、读方 COALESCE 0」的约定随之作废：`p_rev = 0`
的语义见 §4.4（空注册面但 tools 当前）。运维纪律：时钟行锁持有到事务提交；
注册写事务必须短，不得在事务内做外部 IO/等待；并发注册在 READ COMMITTED
下后到者等待并见 live，REPEATABLE READ 下可能 40001，属安全方向。

### 4.3 `v13_scope_chain`（祖先链函数）

```text
v13_scope_chain(p_scope uuid, p_actor uuid DEFAULT NULL)
  RETURNS TABLE(scope_id uuid, depth int)
  -- STABLE, SECURITY DEFINER, SET search_path = pg_catalog, public
  -- 递归 CTE 沿 parent_session_id 自叶向根上行；depth 上限 32；
  -- 环检测：path 数组含当前行即截断（fail-closed，不 RAISE）
```

- **授权（2026-10-17 裁决 3 加 `p_actor`，逐分支复刻 CE 形态）**：
  `p_actor IS NULL` → caller（`v13_registry_caller_role()`，§4.6）必须是
  超级用户或 `v13_route` / `v13_recall` 成员；`p_actor` 非 NULL →
  **不查 caller 角色**，只查 actor 存在且 `p_actor = p_scope OR
  p_actor = parent_session_id`（self-or-parent）。未知 scope、未授权、未知
  actor 一律**返回零行**（不泄露存在性）。亲缘臂在授权上自满足（传
  `p_scope` 自身即可），真实边界是 EXECUTE 授予。**与 stage 23
  `v13_control_authorized` 拒绝 self 的先例不同**，本处跟 CE
  `v13_ce_read_ok` 允许 self——有意分歧，README 记录。**只复刻形态，禁止
  调用任何 `v13_ce_*`**（裁决 3）。
- 私有 `v13_registry_chain_inner(p_scope uuid) RETURNS TABLE(scope_id
  uuid, depth int)`（同语义、无授权、仅属主）供 context 内部复用；公开入口
  授权后委托，不复制 CTE。
- 机制先例在树内：`v13_cancel` 的递归 CTE + path 数组环检测（现行版
  `v13/acl/v13_acl.sql:151-162`，fanout 版 `v13/fanout/v13_fanout.sql:170-181`）。
  两处先例都是**下行**（子树扇出）、depth cap 64、遇环 **RAISE**；本函数是
  **上行**（祖先链）、cap 32、遇环**截断**——差异是起草时有意的：cancel 是
  写面（环=数据损坏，必须响亮），scope_chain 是读面（环退化为「只看已见
  祖先」，fail-closed 不炸解析）。cap 取值差已经 2026-10-17 评审锁定
  （§10 保留点 5，台账 S41R-5）。
- depth cap 的直观依据：fork 场景链长为个位数（非 fresh fork 复制 latch 时
  排除 `worktree` binding，`v13/fanout/v13_fanout.sql:976-982`，树浅而宽），
  32 是 belt 不是估计值。
- `trg_sessions_fork_cols_immutable` 使 parent 写一次后不可改，环经普通
  DML 结构性不可达；环截断是防御性代码，gate 只做源码形态断言 + cap 行为
  断言，不伪造环。

### 4.4 `v13_registry_context`（解析函数，输出闭集冻结）

```text
v13_registry_context(p_scope uuid, p_rev bigint DEFAULT NULL,
                     p_actor uuid DEFAULT NULL) RETURNS jsonb
  -- STABLE, SECURITY DEFINER, SET search_path = pg_catalog, public
```

**输出顶层键闭集（十键，不多不少）**：`schema_version`(=1)、`scope_id`、
`revision`、`tools_revision`、`services`、`tool_profiles`、`prompt_sections`、
`tools`、`unresolved`、`context_hash`。

```text
{ "schema_version": 1,
  "scope_id": <uuid>, "revision": <bigint>, "tools_revision": <bigint>,
  "services":        [ value ⊕ {name, scope_id, registration_id, valid_from_rev,
                                depends_on} ],                  -- ORDER BY name
  "tool_profiles":   [ value ⊕ {name, scope_id, registration_id, valid_from_rev} ],
                                                                -- ORDER BY name
  "prompt_sections": [ value ⊕ {name, scope_id, registration_id, valid_from_rev} ],
                                                                -- ORDER BY name
  "tools":           [ {name, description, kind, handler, param_spec, enabled} ],
                                                                -- ORDER BY name（Q1 读取统一）
  "unresolved":      [ {name, missing: [...]} ],                -- ORDER BY name；missing 升序
  "context_hash":    "<sha256 hex of (输出对象 - context_hash)::text>" }
```

- **provenance 键（2026-10-17 裁决）**：`services` / `tool_profiles` /
  `prompt_sections` 每条目 = 该注册行 `value` 对象并入固定 provenance 键
  `{name, scope_id, registration_id, valid_from_rev}`；`service` 条目另并入
  列值 `depends_on`（升序去重）。value 内含同名键时 provenance 覆盖
  （provenance 是身份，注册内容是数据）。`tools` 行键集恰为
  `{name, description, kind, handler, param_spec, enabled}`，**原样并入全部
  行（含 `enabled = false`）**——Q1 读取统一，消费方自行过滤。
  `unresolved` 条目恰为 `{name, missing}`（`missing` 为缺失服务名数组，
  升序）。
- **确定性与哈希**：所有输出数组 `ORDER BY name`——跨语言一致（§6）与
  `context_hash` 可复算的共同前提；`depends_on` / `missing` 升序。
  `context_hash` = `encode(digest((输出对象 - 'context_hash')::text,
  'sha256'), 'hex')`，复刻 `payload_hash` 纪律（events 落行即哈希，
  `v13/schema/v13_core.sql:87-90`）；jsonb::text 键序稳定的既有论证
  （`v13/schema/v13_core.sql:173-174`）原样适用。**`unresolved` 与
  `tools_revision` 均进 hash**（已锁定：诊断差异即世界差异，§10 保留点 2，
  台账 S41R-9）。
- **revision 语义（裁决 1/2）**：注册行 append-only（退役也是新 revision，
  不 UPDATE 历史内容）⇒ 同一 revision 的注册内容固定；`tools` 是可变的第二
  来源，由 `tools_revision` fence 另行钉版（同语句快照读
  `v13_tools_meta.revision`）。`p_rev NULL` → `v_eff` = 时钟当前值
  （**不是** scope meta；时钟零行 = 种子丢失，读面 RAISE，不返回假
  revision 0）；`p_rev` 非 NULL 为 as_of。**`p_rev = 0` → 空注册面**
  （`valid_from_rev >= 1` 恒空集）：`revision:0`、三个 kind 数组空，
  **`tools` 仍返回全部行、`tools_revision` 当前值**（tools 无时间轴）。
  **`p_rev < 0` → RAISE 参数错**（读面无写；参数校验先于授权，RAISE 文案
  不含 scope 信息）。**`p_rev > 时钟` → 钳制**：`v_eff` = 时钟当前值，
  `revision` 回显时钟值，内容按时钟求值——保证 `revision` 始终是已提交的
  全局值，维持「同 revision 注册内容固定」；完整 context 的缓存键还必须含
    tools_revision，不能据 registry revision 单独复用 tools 内容。
- **as_of 谓词（半开 `[from, to)`，先例 thresholds
  `v13/schema/v13_core.sql:482-485`）**：`valid_from_rev <= v_eff AND
  (valid_to_rev IS NULL OR valid_to_rev > v_eff)`。边界已核验：N-1 不可见、
  N 与 M-1 可见、M 不可见。
- **解析算法（add-only 依赖闭包）**：`v13_registry_chain_inner` 按 depth
  升序逐 scope 取 as_of 可见行；每个 `(kind, name)` 取**第一个**（近端遮蔽
  远端，Cordis 的 scope 语义）。对 service 名集合 `S0`：`resolved = {}`；
  最多迭代 `|S0| + 1` 轮，每轮按 name 升序扫描未解析 service，若其全部
  `depends_on` 已在 `resolved` 中则加入；某轮无新增则停止；未进入
  `resolved` 的 service 全部进 `unresolved`，`missing` = 其 `depends_on`
  中不在 `resolved` 的名字（升序）。该算法从空集加起，**环（A→B→A）永不
  进入 resolved，两者均落 unresolved**；迭代上限是 belt，触顶视为实现
  bug，整批 service 落 unresolved，不 RAISE。`depends_on` 只许点名
  kind='service' 注册行的 `name`（不是 `provides` 条目）；tool_profile /
  prompt_section 不参与依赖。
- **授权与规范空形（裁决 3）**：scope 不存在、未授权、`p_actor` 不存在 →
  返回**规范空 context**：`{schema_version:1, scope_id:null, revision:0,
  tools_revision:0, services:[], tool_profiles:[], prompt_sections:[],
  tools:[], unresolved:[], context_hash:<该固定形状的确定性哈希>}`。
  **已知但空注册的授权 scope 不走规范空形**：回真实 `scope_id`、当前
  `revision` / `tools_revision`、空 kind 数组与全部 `tools` 行——两种空形
  在 `scope_id` / `revision` / `tools` 三处可区分，gate 逐键断言。私有
  `v13_registry_read_ok(p_actor uuid, p_scope uuid) RETURNS boolean` 逐分支
  复刻 `v13_ce_read_ok` 形态（NULL 查 caller 角色；非 NULL 只查
  self/parent），但**零 `v13_ce_*` 调用**；所有 NULL 比较 fail-closed 返回
  false。
- **append-only ⇒ 同 revision 注册内容固定**：`v13_registry_context(scope,
  rev)` 仍读取当前 tools，不是仅由两个参数决定的纯函数；同一授权分支与
  tools_revision 下才有完整内容确定性。worker 必须按
  `(scope, revision, tools_revision)` 内容寻址缓存——与信封冻结同一论证（信封在同一语句快照读 (revision, 目录全集) 并
  冻结，`v13/schema/v13_core.sql:668-680` 注）。
- **unresolved 不 RAISE**：一个坏服务不炸整个 scope；降级是数据（数组元
  素），不是异常。与「缺 active 策略行 fail-closed RAISE」（`v13_policy`）
  是有意不同的两面：策略是路由承重件、缺失必须炸；服务注册是外围能力、缺
  失降级。

### 4.5 三个 kind 的 value 形状

- `service`（Q6 收紧后的形状）：
  `{ "provides": ["fn_a","fn_b"], "config": {...}, "schema_version": 1 }`。
  `provides` 是公开函数名的**文本清单，不做 pg_proc 校验**——校验在消费方；
  注册行不冻结函数体（tools 的 DDL event trigger 维护面，
  `v13/schema/v13_core.sql:1058-1120`，是「冻结即维护面」的既有教训）。
  **显式不做**：无生命周期回调（start/stop 是 worker 进程内的事——连池/资源
  在进程里，语言内部管）、无 facade、无 driver 抽象类。
- `tool_profile`：`{ "handlers": [...], "interruptible": "...", ... }`——
  ch08 意图的数据化落点（§8），是 tools 目录的**数据补充**而非新过滤参数。
- `prompt_section`：提示词段的注册形态（本草稿不细化形状，随首个消费方
  定型；保留开放点，§10）。
- `hook` **缓建**（无消费方）；`policy` **永不进**（`v13_policies` 已经是
  可逆注册/换版的 DB 形态，append-only + at-most-one-active +
  `v13_policy()` 单源读，`v13/schema/v13_core.sql:701-740`）。

### 4.6 角色、caller 与 ACL 矩阵（零新角色）

照搬三角色组（`v13_recall`/`v13_resolve`/`v13_route`，创建于
`v13/schema/v13_core.sql:814-844`）与列举式 REVOKE/GRANT 纪律
（`v13/schema/v13_core.sql:873-908`；ce_run 的整族 REVOKE + 按角色 GRANT
形态见 `v13/ce_run/v13_ce_run.sql:1122-1149`）。创建与 REVOKE 同事务，
避免默认 PUBLIC EXECUTE 窗口：

- 表：`v13_registrations`/`v13_registry_meta` REVOKE ALL FROM PUBLIC；
  SELECT 授 `v13_recall` + `v13_route`；**写面不授任何角色的表级 DML**——
  注册/退役只经 SECURITY DEFINER 写面函数（§4.2 五步契约）。
  **`v13_registry_clock` 是内部表：全部权限零角色、仅属主**（时钟只能经
  写面函数推进）。
- 函数：注册/退役写面函数 REVOKE PUBLIC 后只授 `v13_route`；
  `v13_scope_chain`/`v13_registry_context` 只授 `v13_recall` +
  `v13_route`（读面）；`v13_registry_caller_role`/`v13_registry_read_ok`/
  `v13_registry_chain_inner` 与 frozen 触发器函数**零角色、仅属主**。
- **读面是有意收窄的两角色**（M2 终裁）：较 `v13/schema/v13_core.sql:854-856`
  的三角色读面先例**少 `v13_resolve`，属有意收窄**——注册面是能力面、判断
  面无消费者，最小授权优先。**不变量句（写入 SQL 注释与 gate）：
  `v13_resolve` 对全部 registry 函数 42501**。recall 拿不到写面，route 能写
  注册面但读不出越权数据（读面函数内部做角色/scope 谓词）。
- `v13_registry_caller_role()`：`current_setting('role')` 为 NULL/空串/
  `'none'` 时回落 `session_user`，否则取之；验证角色存在；不接受 caller
  参数，不看 definer 的 `current_user`。
- 部署前提沿用 stage 40：专用库收回宿主/继承角色的数据库 TEMPORARY 与
  public schema CREATE（setup 验证），不泛化到其他 stage 库。

## 5. 时空语义

### 5.1 valid 区间与换装

- `valid_from_rev`/`valid_to_rev` 是全局 revision 轴上的**半开区间**
  `[from, to)`（§4.2 时钟；§4.4 边界已核验）。半开区间先例：thresholds 带
  `[lo, hi)`（`v13/schema/v13_core.sql:482-485` 注）。
- 换装 = 一次注册或退役 = 全局时钟 revision +1（§4.2）。注册/退役**不取消**在途
  effect——外部 IO 不可撤销，fence 已保证至多一次结算（CAS，
  `v13/acl/v13_acl.sql:300-302`）。
- **安全方向注记（终检增补）**：注册/退役事件落 scope 本 session 的
  events（§4.1），推进其 `max_event_seq`——步 0 探针七键含
  `max_event_seq`（`v13/loop/advance.sql:16-30`），故该 session 的在途
  advance 会判 `stale` 重解析。这是**安全方向且语义正确**（世界变了弃批），
  不是 bug；本注记存在的意义就是防止将来有人把它当 bug 报。

### 5.2 claim 面：`context_revision` 标量与三份面的对齐分工

**现状（2026-10-17 v99 复核）**：claim 面共**三份，均已提交**（ce_run 已随
stage 40 收口；起草时漏报公平层一份，核验发现 H1，已采纳）：

1. `v13_claim`（全局；live：`v13/fanout/v13_fanout.sql:266-303`，响应五键
   `{effect_id, attempt_no, fence, kind, request}`，`:301-302`；原始定义
   `v13/schema/v13_core.sql:267`）；
2. `v13_claim_fair`（公平层；`v13/fair_claim/v13_fair_claim.sql:421`，响应
   六键含 `root_session_id`，自建于 `:582-593`，**不内部调 `v13_claim`**；
   它是被全树唯一精确键集断言钉住的 worker 面——
   `v13/fair_claim/test_fair_claim.py:55` 的 `SIX` 常量 + `:654` 的
   `sorted(got.keys()) == sorted(SIX)`）；
3. `v13_ce_claim_bound_effect`（ce_run scoped 内部函数，与注册面并立；
   `v13/ce_run/v13_ce_run.sql:252-278`，响应七键含 `idempotency_key`）。

**对齐分工（H1 终裁：修正版 (a)）**：

- **stage 41 的 `v13_registry_context` 输出已携 `registry revision +
  tools_revision` 双标量**（裁决 2，§4.4 十键闭集）；本里程碑 claim 加键
  不动，仍归 §11.5。
- `context_revision` 加键**不进 stage 41**——stage 41 的全部回滚论证建立在
  「纯增量、零既有对象改动」上，`CREATE OR REPLACE v13_claim` 一改就要加
  脚注；且该键在 superseded 吸收（消费侧提案）落地前无消费者，提前加键是
  纯面扩张。加键移到 **§11.5 消费侧提案**，与 advance 第八键、语义事件锚列
  同批。
- 届时**两份已提交面在同一 changeset 各加一键**；`test_fair_claim.py` 的
  `SIX → SEVEN` 常量与提案同 changeset 修改，**常量处加一行注释指向本文档**
  ——该断言存在的目的就是拦静默漂移，明着改它正是它在工作。其余消费面是
  子集读（`v13/loop/test_loop.py:83`、`v13/pi_parity/test_pi_parity.py:446`、
  `v13/fanout/test_fanout.py:418/443`，核验逐项），加键不破。
- ce_run 面维持并立（ce_run 已收口），映射对齐留 §7.4 可选复核。
- worker 缓存契约（设计 §11.5 消费侧后续提案，尚未强制）：以
  `(scope, registry_revision, tools_revision)` 为进程内缓存键，任一标量变化
  都必须重取；不得在 registry revision 不变时复用已变更的 tools 内容。
  未来 claim 需携双标量，读取 registry 时钟与 tools meta；本阶段 claim 零改动。
- **钉版条款（终检新增的 TOCTOU 纪律）**：worker **必须**以 claim 返回的
  `context_revision` 钉版调 `v13_registry_context(scope, rev)`，并核对返回的
  tools_revision 与 claim 第二 fence 一致，不一致则拒用并重新领取/解析
  （具体消费侧协议留 §11.5）；tools 没有历史读取能力。`p_rev NULL`
  仅限调试/即席。否则 claim 与 context 两次调用间存在 TOCTOU：revision 前进
  后 worker 拿到比 claim 新的世界却以为自己持旧版，§5.3 的 superseded 吸收
  锚因此失效。
- fail-closed 方向：worker 持旧 context 继续干活无害（结果按 §5.3 吸收）；
  持旧 context **领新单**不可能——claim 响应里的 revision 由 DB 当下给出。

### 5.3 迟到结算按 superseded 吸收（origin_user_seq 先例的复刻）

**先例已核实存在**（裁决引用的「turn 4 先例」，核验确认语义一致）：

- 列与契约注释：`effects.origin_user_seq`，「创建时 last_user_seq……迟到
  完成锚点——完成语义事件携它，消费侧（finish 判定/失败计数/判断投影）按
  origin=当前 turn 过滤」（`v13/schema/v13_core.sql:105-108`）。
- 生产侧：结算时语义事件 payload 携锚——live `v13_complete` 的
  `tool/result`（`v13/acl/v13_acl.sql:415-419`）、`llm/message`
  （`v13/acl/v13_acl.sql:420-423`）、judge 失败审计 `resolve/failed`
  （`v13/acl/v13_acl.sql:443-447`）。
- 消费侧：`v13_route` 的 finish 判定只认 `origin_user_seq = 当前
  last_user_seq` 的语义事件（`v13/loop/advance.sql:123-128`，设计注
  「turn A 迟到完成的 llm/message……不参与判定」见 advance.sql:103-106）；
  advance 失败审计落点同样锚到当前 `last_user_seq`
  （`v13/loop/advance.sql:271-277`）。

本方案的复刻（零新机制）：

1. 换装不取消在途 effect；其 `v13_complete` 照常接受（台账为真）。
2. complete 时把 worker 申报的 `context_revision` 记入语义事件 payload——
   与 `origin_user_seq` 完全同构的**第二个锚**。
3. advance/投影侧对 `context_revision <> 当前全局 registry revision`（§4.2
   时钟）的迟到结算按 **superseded** 处理：**不判失败、不触发重试、仅审计**——
   与跨 turn 迟到结算「不触发 finish、事件仍入日志」同一模式。
4. 落点是**独立后续提案**（§11.5）：`v13/loop/advance.sql` 步 0 比对集
   （现行七键探针 `v13_probe`，`v13/loop/advance.sql:14-31`；锁内比对在
   live advance `v13/fanout/v13_fanout.sql:501-511`）增第八键
   `registry_revision`；语义事件 payload 增锚列。不属 stage 41 范围。

### 5.4 time-travel

`v13_registry_context(scope, as_of_rev)` 即最小形态（Q5）。调试问题永远是
「当时 worker 看到哪版」，而 worker 看到的版本由 revision 编址；墙钟→
revision 的映射可从 `registry/*` 事件的 `at` 列（events 自带，
`v13/schema/v13_core.sql:40`）事后重建，不进 schema。

## 6. 多语言轴（H2 终裁重写）

- **立场不变**：语言不进拓扑；注册历史由 `(scope, revision)` 寻址。
  完整 context 还依赖当前 tools_revision 与授权分支，不是二元纯函数；
  相同授权结果、相同双标量、相同 tools 状态才保证完整内容一致。
- **证明措辞（按终裁原文）**：跨语言逐字节一致**由构造保证**——所有语言的
  worker 经 libpq 调同一个 SQL 函数，无第二实现可漂移；pg 侧确定性断言验证
  该函数本身。框架 driver（pi/pig/piswift）当前零 DB 连接
  （persisted=memory，见 `v13/pi_parity/README.md`「持久化证据链」节），其
  端对端复跑属**未来 worker-parity stage**（框架 driver 接 DB），不在本方案
  接受标准内。
- **断言收窄为 pg 侧三条**（各自落进对应 gate，不动 pi_parity 现有结构）：
  1. **context 确定性**（stage 41 gate，落 `v13/registry/test_registry.py`
     探针 9 native_context_determinism）：同一 `(scope, revision)` 在**两个
     独立连接**在 tools 无并发变更窗口、同一授权结果下各调一次
     `v13_registry_context`，并确认 tools_revision 相同，输出逐字节相等且
     `context_hash` 相等——这是单源 SQL 的一致性证明，不是旧 tools 可重建证明。
  2. **换装可见性**（消费侧提案 gate）：注册/退役一次 → 下一次 claim 响应的
     `context_revision` 翻转；翻转时点 = claim 边界，pg 侧确定性可断言。
  3. **superseded 吸收**（消费侧提案 gate）：持旧 revision 结算，语义事件
     锚列形状与投影过滤行为符合契约——全部落点在 SQL，pg 侧即可断言。
- pi_parity 的既有纪律原样沿用（跳过打 `[SKIP]` 不改退出码、严格模式
  `PI_PARITY_REQUIRE_ALL=1`、字节稳定先例断言——「gate 语义」节）；本方案
  对它**零改动**。

## 7. 与现有机制的关系

### 7.1 tools（目录即 allowlist）

**不动**。它已经是一张注册表：双守卫触发器（signal 语法 + sql handler 写入
校验，`v13/schema/v13_core.sql:620-666`）、AFTER 行级 revision bump
（`:687-694`）、handler 函数体漂移的 DDL event trigger（`:1058-1120`）、
信封冻结 + advance 步 0 比对消费（`v13/loop/advance.sql:241-254`；live 比
对在 `v13/fanout/v13_fanout.sql:501-511`）。物理收编 = 重写这套链 + 迁移
seeds + 改 advance 探针，收益为零。`v13_registry_context()` 输出把 tools
目录行以同一形状并入（Q1「读取统一」）。

### 7.2 v13_policies / thresholds

**不动**。`v13_policies` 已是 Cordis「可逆注册/换版」的 DB 形态：append-only
版本行 + `ux_v13_policies_one_active` 部分唯一索引 + `v13_policy()` 单源读
（`v13/schema/v13_core.sql:701-740`）——只是没有 scope 维度。thresholds /
`v13_route_policies` 是 draft→frozen 两态、冻结后 INSERT 拒的内容寻址版本
先例（`:455-562`）。`policy` kind 永不进 registrations（避免双真相源）。
scope 维度上的策略覆写是否值得做，留给首个真实需求驱动（YAGNI 台账条目）。

### 7.3 相关但不同的「context」（命名已裁定）

- `v13_context_fresh(p_sid)` 是 DP3 新鲜度缝，恒 true stub
  （`v13/loop/advance.sql:1-5`）——语义正交。
- `sessions.context_active_artifact`/`context_active_revision` 是上下文
  **artifact** 指针（`v13/manifest/v13_manifest.sql:97-98` 加列），指
  ContextPipe 血统的装配产物——本方案的解析函数是**注册面**，两者是「装配
  什么内容」与「哪些能力已注册」两个面。
- 命名冲突风险经终裁关闭（§12 M-终检）：解析函数定名
  **`v13_registry_context`**，避让 `v13_context_fresh`/`context_active_*` 的
  「context」占用；不取 `v13_resolve_context`——resolve 已是判断面专用词。

### 7.4 ce_run 三 generation 列的去向

ce_run（stage 40，已在 v99 收口）的 `v13_ce_runs` 带
`registration_generation` / `owner_generation` / `continuity_generation`
（`v13/ce_run/v13_ce_run.sql:8-11`）：

- `registration_generation`：**可选择**映射到 `v13_registry_meta.revision`
  （诊断值，§4.2），不强制（Q7 并立声明）；本阶段对 ce_run 零触碰
  （台账 S41R-12）。
- `owner_generation`（backend pid 所有权）与 `continuity_generation`（epoch
  语义）：**永不收编**，留在 ce_run 本地——它们是进程生命周期概念，与注册
  修订是两种东西，合并是伪统一（Q3）。
- ce_run 字段本身无六动词 producer（`v13/ce_run/README.md:15` 自述），
  本方案不为其背书、不依赖其函数。

### 7.5 「不迁移旧表」的论证

三条，任意一条独立成立（Q1 裁决转写）：

1. tools 守卫链是 load-bearing 的——重写它违反「不破坏单写者纪律」且收益
   为零；它已经是注册表，只是 DDL 不同。
2. ce_run 在 v99 已收口（47 脚本 + 2 探针全绿），其对象由冻结守卫钉住；
   再叠一次核心表迁移 = 推翻已收口基线，收益为零。
3. Cordis 调研（§1）的可取语义是「可逆注册 + 依赖解析」，不是「一张大表」；
   v1 的 `cordis_services` 存根恰恰是「一张大表但无语义」的反例。

回滚面：全部新增对象、零旧表改动 ⇒ 回滚 = DROP 新对象，无数据迁移；注册
行 append-only，无「新代码读旧数据」之外的面。

## 8. ch08 偏差台账（逐条）

| ch08 承诺（file:line） | 现行代码事实 | 本方案兑现位置 |
|---|---|---|
| `v13_claim(worker_id, handlers[], lease_ms)` 领单（`docs/tutorials/v13/chapters/08-multi-language-harness.md:21`；§8.3「按目录的 handler 列过滤」） | live `v13_claim(p_worker text, p_lease_ms integer DEFAULT 60000)`，**无 handlers[] 参数**（`v13/fanout/v13_fanout.sql:266-303`；原始定义 `v13/schema/v13_core.sql:267`）；过滤只有 worktree latch 面 | 新 kind `tool_profile` 的注册内容（`value.handlers text[]`）；claim 侧过滤仍走 `tools.handler` 列的既有 WHERE——profile 是**数据补充**而非新参数；是否进 claim WHERE 是独立后续提案 |
| 订阅档位是目录数据 `tools.allowlist` 的 `interruptible` 键（ch08:28-29、66-67） | `tools` 表无 `allowlist` 列（列集 = name/description/kind/handler/param_spec/enabled，`v13/schema/v13_core.sql:581-593`）；interruptible 是 **IMMUTABLE 函数** `v13_interruptible(text)`，硬编码 CASE 三档，缺省 `unsupported`（`v13/fanout/v13_fanout.sql:37-44`） | `tool_profile.value.interruptible` 与函数并存：**函数优先、profile 为覆盖面**（裁决方向已定，评审锁定，§10）；落 stage 前文档须写明 |
| mutating 语义：bash 标 `mutating=true` 享受 unknown 纪律（ch08:73-74）；「中断后副作用不明 → settle unknown」（ch08:34-35） | **机制已在、形态不同**：`v13_complete` 的 cancelled 出口对 `kind=tool 且 tier=required` 拒收、要求 settle unknown（live：`v13/acl/v13_acl.sql:309-313`；fanout 版 `v13/fanout/v13_fanout.sql:335-339`）；`mutating` 作为元数据键已存在于 spawn metadata（`v13/spawn/v13_spawn.sql:46`） | 不动（Q7：`mutating` 已在 spawn metadata）。unknown 墙纪律由本方案原样继承，不经 registrations 转述 |
| mutating harness 缺 worktree binding 拒 claim（ch08:68-70） | **已兑现**：`v13_requires_worktree(tool_name)`（硬编码名单，`v13/fanout/v13_fanout.sql:46-49`）+ latches 存在性检查进 live claim WHERE（`:294-298`） | 不动。若未来「要求 worktree」要数据化，候选落点是 tool_profile 注册内容——YAGNI 台账，不立本方案 |
| 目录数据化总纲：「新增一个 Swift 工具 = INSERT tools 一行 + 启动进程」（ch08:76-77） | 部分成立：tools 行确是数据；但 interruptible/worktree 要求都是**函数内硬编码名单**，加工具若需这两档就得改 SQL 函数体 | 这正是 `tool_profile` kind 的存在理由：把这两类 per-tool 数据从函数体搬进注册行，ch08 意图由新层兑现、tools 表不动 |
| pi 式极简工具 = 一包目录行，allowlist 根目录是目录行数据（ch08:72-74） | 无 allowlist 列；`param_spec` 是现成 jsonb 容器（`v13/schema/v13_core.sql:589-590`） | `prompt_section`/`tool_profile` 的 value jsonb 即容器；具体键名随首个消费方定型（§10） |

台账纪律（Q7）：本文档专列本节；未来 ch08 教程修订在偏差收敛后同步措辞，
不回填旧表、不改教程先于机制落地。

另：stage 41 实施偏差使用独立命名空间台账 S41R-1…S41R-13（全局时钟取代每
scope 计数、`tools_revision` 入 hash、读面两角色收窄等），见落地计划
`docs/plans/v13-registry-stage41-2026-10-17.md` §5.4；v13 行号面基线以
v99 `cbf65cf` 为准。

## 9. 优势分析（定稿）

### 9.1 对照现状（无注册面的 v13）

今天的 v13 里，「能力」有三种住处，互不认识：tools 目录行（带整套守卫链）、
函数体内硬编码名单（`v13_interruptible` 的 CASE 三档、`v13_requires_worktree`
的名单，`v13/fanout/v13_fanout.sql:37-49`）、策略行（`v13_policies`）。热换
检测只有 `v13_tools_meta` 一个**全库单点** revision——没有 scope 维度，任何
目录变更对**所有** session 的在途信封一律弃批；想给某个项目换一套工具面而
不惊动别人，做不到。加一类能力（比如 ch08 的订阅档位）要改 SQL 函数体并
重新部署。本方案把后两类搬进注册行，revision 轴由全局注册时钟承担（裁决
1），按 `(scope, revision)` 编址沿祖先链求值：能力变更的爆炸半径从「全库
弃批」缩到「该 scope 的注册读取面」（消费侧 claim 加键见 §11.5）。

### 9.2 对照 Cordis/Minato 运行时（借什么、拒什么）

- **借**：命名服务（`kind='service'` 的注册行）、`depends_on` 依赖声明与
  一层传递闭包解析、scope 遮蔽（近端覆盖远端）、可逆注册（退役 = 设
  `valid_to_rev`，可逆可查）。
- **拒**：JS 运行时本体——Context 容器、插件加载器、disposable 生命周期、
  facade。服务 = **函数面 + 注册行**：函数体住在 `pg_proc`，注册行的
  `provides` 是不冻结函数体的文本清单，二者之间没有第二真相源（校验在消费
  方，§4.5）。v1 的 `cordis_services` 存根证明了「一张大表但无语义」毫无
  价值；本方案的每个 kind 都有明确的解析算法与消费方。

### 9.3 对照参考项目（各借了什么、拒了什么）

- **DBOS**（工作流状态全在 PG）：v13 已有其内核——effects 台账 + fence CAS
  + lease 回收，步骤行可检查、可修复、可重放。本方案补的是 DBOS 没有的
  一层：**带有效时间维度的能力注册**（DBOS 的注册是进程启动时的代码注
  册，改代码即改世界，无 as_of）。拒：其应用运行时——v13 的 worker 契约
  只是几个 SQL 函数，不引入框架进程模型。
- **XTDB**（bitemporal）：借 valid-time 区间与 as_of 查询形态
  （`valid_from_rev`/`valid_to_rev`、`p_rev` 参数）；拒 record-time 第二
  时间轴——system-time 已由 append-only `events` 承担（注册动作即事件），
  再建一张双时间表是集中序列的税（Q5）。
- **LangGraph**（checkpoint / fork-not-rollback）：v13 的 `v13_fork`
  （`v13/fanout/v13_fanout.sql:920`）已是同构——历史不覆写、新分支新行。
  本方案的 time-travel 与之同族：**回到过去是一次 as_of 查询，不是状态
  变异**；注册行 append-only 使「当时的注册面」永远可重建。拒：图执行
  运行时进 DB——不建第二执行面，注册面只回答「有什么」，不回答「怎么跑」。

### 9.4 对 agent 底座的长期意义

1. **跨语言一致由构造保证**：固定授权结果和 tools 状态的单源 SQL，无第二实现可漂移（§6）；
   「Swift 和 Python 看到同一个世界」从测试主张升格为定理。
2. **时间旅行调试**：「这个 worker 当时以为自己在哪个世界」=
   `v13_registry_context(scope, rev)` 配合 `registry/*` 事件可重建过去的
   注册内容，但返回当前 tools；完整过去世界须另存 tools 快照，本阶段不提供。
3. **零迁移、可回滚**：纯增量对象，回滚 = DROP；注册行 append-only，
   无数据迁移面（§7.5）。
4. **统一对齐面**：公平层（`v13_claim_fair`）与 ce_run 未来都在
   `(scope, revision)` 编址上对齐（§5.2 三份面的分工）——一个编址体系
   收编所有 worker 面，而不是每面一套版本词。
5. **审计零新表**：system-time 与动作链全部走既有 `events`（§4.1），
   注册面自身只有 valid-time 两列。

## 10. 风险与开放点

**保留开放点（原 5 条；1/2/5 已经 2026-10-17 评审锁定，见落地计划
§10.2）**：

1. **tool_profile 与 `v13_interruptible()` 的优先级**——**已锁定**：函数
   优先、profile 为覆盖面；SQL 注释与 README 写明，静态探针断言注释存在
   （台账 S41R-8）。
2. **`unresolved` 是否进 `context_hash`**——**已锁定：进**（诊断差异即世界
   差异，台账 S41R-9；探针 11）。
3. **`prompt_section` value 形状**——随首个消费方定型，本阶段不立法
   （只要求是 object；台账 S41R-10）。
4. **ce_run `registration_generation` 映射复核**——ce_run 已收口；映射仍
   可选、本阶段零触碰，留消费侧/运维复核（§7.4，台账 S41R-12）。
5. **depth cap 32 vs 先例 64、环截断 vs 先例 RAISE 的形态差**——**已锁定**
   （读面 fail-closed vs 写面响亮，台账 S41R-5；§4.3，探针 8）。

**已定（原开放点，终裁关闭）**：

- ~~全局 scope 注册入口~~ → **已定（M3）**：sessions 的写者纪律是
  spawn_owner 属主写者 + `BEFORE INSERT` 触发器执法
  （`v13/spawn/v13_spawn.sql:567-579` 的 `v13_sessions_insert_owner`：
  `current_user` 必须为 `v13_spawn_owner`；唯一写者三函数由 gate 钉住，
  `v13/spawn/test_spawn.py:148`）。全局锚 session 经既有
  `v13_open_session`（`v13/spawn/v13_spawn.sql:285`）建立，作为**运维种子
  步骤写进部署 runbook**，非 schema 变更；约定 uuid 候选已删除。
- ~~解析函数命名冲突~~ → **已定（终检）**：定名 `v13_registry_context`（§7.3）。
- ~~claim 面对齐范围~~ → **已定（H1）**：三份面的分工见 §5.2。

**风险（维持）**：

- **全局时钟是串行点**：所有注册写在时钟行上串行（锁持有到事务提交）；
  注册是低频管理面操作，换取 as_of 寻址的单调全局轴与无空档区间，优于每
  scope 计数的跨 scope 不可比性。时钟无 bump 触发器（裁决 1），写路径单一
  可审。**空 revision 无害**：时钟只 +1/次成功调用，无跳号；即便未来批量
  入口引入空隙，as_of 命中空集即空面，语义无损（核验结论沿用）。
- **meta 降级为诊断**：读路径不依赖它，漂移（如未来某写路径漏 upsert）不
  影响正确性；gate 仍断言其等于最后触达值以防静默腐化。
- **tools 无时间轴**：`tools` 是就地可变冻结表，as_of 旧 revision 仍返回
  当前 tools；`tools_revision` 是第二 fence，消费方必须按双标量钉版。
- **ce_run 漂移**：ce_run 已在 v99 收口且三 generation 语义未改硬；§7.4
  可选映射与「其余两列永不收编」结论不变，留消费侧复核（台账 S41R-12）。

## 11. 落地顺序

1. **本文档**（已落）：裁决转写 + 契约级 DDL + 偏差台账 + 核验记录。
2. ~~**评审锁定** §10 保留项 1/2/5~~（已锁定，2026-10-17；见 §10 各条注记
   与落地计划 §10.2）。
3. **（后续任务）`v13/registry/v13_registry.sql`（stage 41）**：
   `v13_registrations` + `v13_registry_clock`（含种子行）+
   `v13_registry_meta`（诊断值）+ frozen 触发器 + `v13_scope_chain` +
   `v13_registry_context` + 注册/退役写面函数（§4.2 五步契约）+ 三个私有
   helper + ACL（§4.6）。**纯增量、零既有对象改动**——claim 加键不在此步
   （§5.2 分工）。**依赖**：只依赖既有 sessions/events/`v13_append_event`
   与 tools 目录/`v13_tools_meta`（只读）；与 ce_run 零交叉引用；`load.py`
   追加顺序放**末尾**以便独立评审。Gate 形式建议：独立
   `v13/registry/test_registry.py`（`uv run python`，退出码 0 = 通过；复用
   v13 gate 既有框架——每 stage 的 `setup_db.py` DROP/CREATE 自有库并按
   `SQL_LOAD_ORDER` 累计加载），断言至少含：frozen 纪律负例全列名单（含
   **改 `registration_id` 拒**，M1）、at-most-one live、retire 唯一 UPDATE、
   **时钟单调**（仅成功分配 +1；同事务 register+retire 区间无空档）、
   **`already_live`/`not_live` 结构化零写且时钟不动**、chain 环截断与
   depth cap、**context 确定性（两个独立连接同 (scope,rev)、同授权结果、tools 无并发
   变更且 tools_revision 相同，逐字节等 + `context_hash` 相等，§6 断言 1，落探针 9）**、as_of 边界与 **`p_rev`
   三边界**（<0 RAISE / =0 空注册面但 tools 当前 / >clock 钳制并回显时钟
   值，§4.4）、unresolved 不 RAISE、「revision 0 = 空注册面」、**规范空形
   vs 已知空注册 scope 逐键区分**、ACL 矩阵（route 写 / recall+route 读 /
   **resolve 拒** / PUBLIC 拒 / clock 零角色）。
4. **（未来 stage，不在本方案接受标准内）worker-parity**：框架 driver
   （pi/pig/piswift）接 DB 后的端对端复跑（§6 声明）。
5. **（后续任务，独立提案）消费侧**：advance 步 0 比对集增第八键
   `registry_revision`（`v13_probe`）；语义事件 payload 增 `context_revision`
   锚 + superseded 吸收；**claim 加键——`v13_claim` 与 `v13_claim_fair` 同
   changeset 各加 `context_revision`，`test_fair_claim.py` 的 `SIX→SEVEN`
   常量同 changeset 修改并在常量处加注释指向本文档**；ce_run 的
   `v13_ce_claim_bound_effect` 维持并立、随消费侧提案对齐（ce_run 已收口）。
   Gate：loop/
   fanout/fair_claim 既有回归 + 换装翻转可见性（§6 断言 2）+ superseded
   吸收（§6 断言 3）。**与 stage 41 不原子捆绑**——注册面先落，无消费方
   时 registrations 只是惰性行，空跑无害；worker 钉版契约随本步生效。
6. **ch08 教程措辞收敛**：偏差台账（§8）收敛后同步，不先于机制落地。
   **2026-10-19 当前状态**：Stage 41 已由 `69e118d`/`5be562d` 交付，消费侧
   Phase 2 已由 `937a864`/`93d05f1` 交付。上列 3/5 保留设计历史；as-built 使用
   attempt/fence side-table 锚而非新增业务 payload 键，fair prefix 仍 SIX、overlay
   为 SEVEN，CE 仍独立。教程 ch02/03/06/08/12 按实际 worker/lease 签名、tools
   六列与函数名单收敛，不声称 profile/prompt 消费或生产 strict worker 已交付。
   部署仅支持隔离库装载/只读核验，不将 §9.4 的“DROP 回滚”当生产操作流程。
   最终证据/限制见 `docs/plans/v13-registry-phase3-closeout-2026-10-19.md` 与
   `docs/reviews/v13-registry-phase3-closeout-2026-10-19.md`；两轮验收及 A/B 交付状态以计划 §11 和最终报告为准。
7. **（后续可选复核）ce_run 侧**：ce_run 已在 v99 收口；
   `registration_generation` → `v13_registry_meta.revision` 的可选映射
   （§7.4，台账 S41R-12）与 `v13_ce_claim_bound_effect` 响应对齐（§5.2）
   均留消费侧提案复核，本阶段零触碰。

## 12. 核验与裁决记录

设计被独立核验 agent 逐条对照 v13 代码核验（核验报告
`prompt-exports/spacetime-verification-2026-10-17.md`），六项矛盾经 oracle
终裁（`prompt-exports/oracle-review-2026-10-17-142744-*.md`）全部处置：

| # | 发现（核验） | 裁决（oracle 终裁） | 处置位置 |
|---|---|---|---|
| H1 | 「恰有两份 live claim」漏已提交基线的 `v13_claim_fair`（`v13/fair_claim/v13_fair_claim.sql:421`，响应六键自建于 `:582-593`；精确键集断言 `test_fair_claim.py:55` SIX + `:654` sorted 比对） | 修正版 (a)：两份已提交 claim 同 changeset 各加 `context_revision`，**移到 §11.5 消费侧提案**（保 stage 41 纯增量回滚论证）；ce_run 面并立；SIX→SEVEN 常量同改并加注释指向本文 | §5.2、§11.5 |
| H2 | pi_parity 三断言按草稿措辞不可零新机制表达（框架 driver 零 DB 连接，persisted=memory） | 选 (a)：断言收窄为 pg 侧三条，证明措辞重写（「由构造保证」），增「未来 worker-parity stage」声明 | §6 |
| H3 | 写面锁序 + meta 行创建时机缺失：并发 off-by-one；首注册前 `context_revision` 无定义 | 全盘采纳写函数五步契约（惰性 upsert → FOR UPDATE → v_new → INSERT/UPDATE → AFTER bump 同值）；锁序 meta→sessions→registrations；「revision 0 = 空注册面」+ 读方 COALESCE 0（**2026-10-17 裁决 1 改写本行**：AFTER bump 触发器删除不建、锁序改为 clock→meta→sessions→registrations、「COALESCE 0」约定作废，见 §4.2/§4.4） | §4.2、§4.4、§5.2 |
| M1 | frozen「逐字照搬」漏保护 `registration_id`/`created_at` | 采纳：不可变列名单扩齐八列，`valid_to_rev` 唯一可动；gate 增「改 registration_id 拒」负例 | §4.1、§11.3 gate |
| M2 | 读面授两角色却称与 `:854-856`（三角色）同构 | 采纳但取「有意收窄」：recall+route，resolve 不授；删「同构」措辞 | §4.6 |
| M3 | 全局 scope 入口措辞不准（实际写者纪律：spawn_owner 属主 + BEFORE INSERT 触发器，`v13/spawn/v13_spawn.sql:567-579`；gate `test_spawn.py:148`） | 采纳：spawn_owner 触发器执法 + `v13_open_session`（`v13/spawn/v13_spawn.sql:285`）作运维种子（runbook 非 schema）；删约定 uuid 候选 | §10「已定」 |

终裁另增补三条（核验未抓/记录缺口），已并入：

- **TOCTOU 钉版条款**：worker 必须以 claim 返回的 `context_revision` 钉版调
  解析函数，`p_rev NULL` 仅限调试/即席 → §5.2。
- **`max_event_seq` 安全方向注记**：注册/退役事件推进 scope 水位 → 在途
  advance 判 stale 重解析，是特性 → §4.1、§5.1。
- **基线声明补全**（主检出 `7db3526` 线）：该线未提交 load.py 同时替换五个
  已暂存 stage → §2、附录（附录已按 v99 线另列 40 项基线）。

核验报告另确认（无需处置）：sessions PK/FK 形状、`v13_append_event` 签名与
ACL、tools_meta 纪律、policies frozen 形态、递归 CTE 先例、`v13_ce_read_ok`
形态、origin_user_seq 先例语义、三角色矩阵、as_of 半开边界、命名无冲突
（仅混淆风险）——附录速查表复核通过。**失实两处**（按主检出 `7db3526`
线记录，属该线历史状态）：claim 份数（H1，已裁决处置）；该线 HEAD 版
load.py 尾部构成（「终于 fair_claim:39」——该线实为 44 项至 `ce_map:44`，
2026-10-17 主检出复核订正，见 §2；对五个已提交 stage 的命名冲突复查仍无
冲突）。另记（同属 `7db3526` 线）：该线 HEAD 上 fair_claim 的
`stage_bytes` 冻结断言因该尾部构成而红（自 agentctl 五件套提交后潜伏，非
本方案引入）。**v99 线事实**：HEAD `cbf65cf` 恰 40 项、尾部
`fair_claim:39` → `ce_run:40`，fair_claim `stage_bytes` 按 ce_run 形态
断言、在 `cbf65cf` 全绿。

---

### 附：本文引用的核实基线

| 声明 | file:line |
|---|---|
| 主检出 `7db3526` 线：HEAD 版 load.py = 44 项（stage 1–39 + agentctl/agentctl_verbs/goal_workflow/external_exec/ce_map = 40–44）——**该线历史事实，对 v99 过时** | （2026-10-17 主检出复核所得：`git show` 该线 HEAD，`fair_claim` 行 56、`"fair_claim": 39` 行 103，其后续五行至 `"ce_map": 44`；该线工作区版 = 39 + ce_run（40），替换上述五个已提交 stage） |
| v99 线基线：HEAD `cbf65cf` 版 load.py 恰 40 项、尾部 `fair_claim:39` → `ce_run:40`，stage 40 已收口 | `git show cbf65cf:v13/load.py`；`v13/ce_run/README.md`「47 条全量回归」节 |
| 主检出 `7db3526` 线：ce_run 未提交（该线历史事实；v99 上 ce_run 已随 `683ea0e`/`60805fc`/`cbf65cf` 收口） | （2026-10-17 主检出 `git status --porcelain`：`?? v13/ce_run/`、` M v13/load.py`） |
| tools 列集无 allowlist/interruptible/mutating | `v13/schema/v13_core.sql:581-593` |
| 三份 claim 面（v99 上均已提交） | `v13/fanout/v13_fanout.sql:266-303`（五键，`:301-302`）；`v13/fair_claim/v13_fair_claim.sql:421`（六键，`:582-593`）；`v13/ce_run/v13_ce_run.sql:252-278`（七键） |
| claim_fair 精确键集断言 | `v13/fair_claim/test_fair_claim.py:55`（SIX 常量）、`:654`（sorted 比对） |
| interruptible 是函数非列 | `v13/fanout/v13_fanout.sql:37-44` |
| worktree binding 拒 claim 已在 live claim | `v13/fanout/v13_fanout.sql:294-298` |
| origin_user_seq 迟到结算先例 | `v13/schema/v13_core.sql:105-108`、`v13/acl/v13_acl.sql:415-447`、`v13/loop/advance.sql:123-128` |
| v13_tools_meta 纪律 | `v13/schema/v13_core.sql:668-694` |
| v13_policies 可逆注册形态 | `v13/schema/v13_core.sql:701-740` |
| 递归 CTE + 环检测先例（下行、cap 64、RAISE） | `v13/acl/v13_acl.sql:151-179`、`v13/fanout/v13_fanout.sql:170-199` |
| SECURITY DEFINER + 钉 search_path 形态 | `v13/ce_run/v13_ce_run.sql` 全文件（如 :104-114、:146-162） |
| ACL 三角色与列举式 REVOKE/GRANT | `v13/schema/v13_core.sql:794-908`、`v13/ce_run/v13_ce_run.sql:1122-1149` |
| v13_append_event 非 DEFINER、EXECUTE 仅 route | `v13/schema/v13_core.sql:874-888`、`:897-902` |
| sessions 唯一写者纪律 | `v13/spawn/v13_spawn.sql:567-579`（BEFORE INSERT 触发器）、`:285`（`v13_open_session`）、`v13/spawn/test_spawn.py:148` |
| ce_run 三 generation 列 | `v13/ce_run/v13_ce_run.sql:8-11`；无 producer 自述 `v13/ce_run/README.md:15` |
| v13_ce_read_ok parent 直查未递归 | `v13/ce_run/v13_ce_run.sql:146-162` |
| v13_parse 活线在 economy | `v13/economy/v13_economy.sql:353` |
| mutating 键已在 spawn metadata | `v13/spawn/v13_spawn.sql:46` |
| pi_parity 断言结构/字节稳定先例/零 DB 框架面 | `v13/pi_parity/README.md`「gate 语义」「持久化证据链」节 |
| Cordis 调研结论（cordis_services 存根、Koishi 映射） | `docs/investigations/cordis-workbench-plugins-2026-08-22.md` Summary、§1、Root Cause |
