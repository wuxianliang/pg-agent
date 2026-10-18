# v13 Stage 41 `registry`：时空注册面开发计划

| 项 | 值 |
|---|---|
| 日期 | 2026-10-17 |
| 状态 | W0–W3 已实现；2026-10-18 W4 提交前完整 50 项符合预期，收尾工件已填；集成静态 review 已完成，setup 字符串身份 P1 已按裁决修复，registry 16/16、481 checks 绿；修复后提交前完整 50 项符合预期；提交、净树复验与推送待执行 |
| 基线 | `v99` worktree HEAD `cbf65cf`，工作树干净；Stage 40 `ce_run` 已收口（`683ea0e`/`60805fc`/`cbf65cf`，47 脚本 + 2 探针全绿）；`v13/load.py` 恰 40 项，尾部 `fair_claim`/39 → `ce_run`/40 |
| 架构 | 纯增量 Stage 41：三表（`v13_registrations` / `v13_registry_clock` / `v13_registry_meta`）+ 全局时钟写面 + 两个读面函数；零既有对象改动、零删除 |
| 权威 | 设计 `docs/designs/v13-spacetime-registry-2026-10-17.md`；本计划 §10 Locked Decisions（Oracle 裁决转写）优先于设计正文；设计 errata 见 §11 |
| 清理裁决 | 无退役；与 ce_run 零交叉引用 |
| 提交信息 | `v13: add spacetime registry stage 41` |

## 1. Goal & Summary

在 v99 基线上追加 Stage 41 `v13/registry`：以 `(scope, revision)` 编址的时空注册面。空间轴复用 `sessions.parent_session_id` 祖先链（`v13/schema/v13_core.sql:23`）；时间轴用全局 singleton 时钟 `v13_registry_clock`（裁决 1，取代设计 §4.2 的每 scope 计数与 AFTER bump 触发器）。交付注册/退役两个写面函数与 `v13_scope_chain` / `v13_registry_context` 两个读面函数；context 输出携 `registry revision + tools_revision` 双标量（裁决 2）。

本阶段不实现消费侧：`v13_claim` / `v13_claim_fair` 加键、advance 第八键、superseded 吸收全部留在设计 §11.5 后续提案；`v13/fair_claim/test_fair_claim.py:55` 的 `SIX` 常量与 `:654` 精确键集断言本里程碑零改动。新增 `v13/registry/{v13_registry.sql, setup_db.py, test_registry.py, README.md}` 四文件，形态照搬 Stage 40 四件套；改 `v13/load.py` 纯尾追加；精确适配六个冻结守卫文件（§5.3）。

唯一交付里程碑是 Stage 41：全部核心及保留 v13 回归门禁绿、收尾工件更新后一次提交、净树复验、推送 `origin v99`。

## 0. 执行进度（编排器维护）

| 项 | 状态 | 备注 |
|---|---|---|
| W0 | ✅ 完成 | §10.3 全部 11 条 errata 落入设计文档 |
| W1 | ✅ 完成 | load.py 纯尾追加 + 六守卫适配；`CE_RUN_TIP = cbf65cfc3e32cf82e51cafbb71162ac7649bd507`；fair_claim `stage_bytes` 实跑 PASS（§5.3.2 容忍度验证通过）；唯一 FAIL 为 `stage 41 path is not tracked`（预期中间态红，W2/W3 建文件后消除） |
| W2 | ✅ 完成 | 3 表 + 8 函数；`setup_db.py --probe-session-owner` 退出码 0；delta 验证 PASS（sequences +0、ACL 矩阵相等）；额外两组实库探针 0；SQL 零 `v13_ce_` 引用 |
| W3 | ✅ 完成 | 16/16 探针绿（473 checks）、import-safe；plan_arm 104 checks 绿；两处旧负例撞号（`ce_run:40→41`、旧 future `not_scheduled:41`）变异不变、期望 reason 改为 `duplicate stage number`（S41R-13 记）；README 含 W4 占位节 |
| W4 | ⬜ | 首次 50 项回归在第 16 项 `goal_supervisor/test_goal_supervisor.py` 因 cached-only `tracked` 不含未跟踪 registry 而中断；Oracle 2026-10-18 裁决采用 `r1_load_append_ok` 精确 registry 四文件脏树例外，定向验证 merged/cached-only 及 13 纯内存案例绿；第二次序列第 17 项被 runner 过严尾部规则误判（实际 exit 1/ask_user 正确），仅修 ignored runner 后从 1 重跑。P1 修复前历史 precommit3 全 50 项符合预期：48×0 + 1/2；registry 16/16、473，CE 665，plan_arm 104；工件已填；集成静态 review 已完成（导出 oracle-review-2026-10-18-145510-untitled-chat-e8a84c-9ab2.md），设计双 fence 残留措辞已修正；setup 字符串库名连接与 TestDatabase 身份差异 P1 经 Oracle 追加裁决纳入本里程碑：删除固定 ROLE_ALIASES，两种入口均解析 per-database 临时角色，None 使用 URI 身份、显式角色直通；native_static_setup 新增八项真实身份/缺 server 精确文案检查，独立 gate 16/16、481 checks 绿。precommit3 仅为修复前历史证据；修复后从第 1 项重跑的 precommit4-p1 全 50 项符合预期（48×0 + 1/2），每项 trace 恢复，独立与 E4 registry 均 16/16、481 checks；人工 diff 与 AST 屏蔽复核仅 r1_* 体内变化、r0_source_scope 原样，CE setup/goal_supervisor 调用点无 diff。提交后同清单净树复验待执行。未暂存/提交/推送 |

## 2. Execution Index

| 工作包 | 内容 | 完成条件 | 依赖 |
|---|---|---|---|
| W0 | 设计文档 errata（§11）修订；本计划定稿 | 设计 §2/§4.2/§4.3/§4.4/§4.6/§5.2/§6/§10/§11 与本计划一致；不独立提交，随里程碑一并入库 | 无 |
| W1 | `v13/load.py` 尾部追加 registry/41；六个冻结守卫文件按 §5.3 精确适配 | 适配本身不放宽任何既有断言；中间态（registry 四文件未建）红灯不称完成 | 无 |
| W2 | `v13_registry.sql` 三表/触发器/时钟/写面/读面/ACL + `setup_db.py` | 装载、前后 delta、ACL 矩阵、写面五步契约可测试 | W1 |
| W3 | `test_registry.py` 十六组具名探针 + `README.md` | §9.2 全部探针 exit 0；import-safe | W2 |
| W4 | 全量回归（48 脚本 + goal_supervisor 两额外探针 = 50 项）、矩阵/台账收尾、集成静态 review、人工核对、提交、净树复验、推送 | §9.3 全绿；提交后同一清单净树复验全绿后 `git push origin v99` | W3 |

提交纪律（沿用 Stage 40 §8.1 与 AGENTS.md）：逐路径 `git add`（含新增四文件、设计文档、本计划、矩阵、台账），禁止 `git add -A` / `git add .`；`git diff --cached` 与 `git status` 核对；不跳 hook；不 force/reset；失败停步不推送，修正后追加修复提交。本计划/设计文档若尚未跟踪，交付时显式逐路径加入，不收拢无关 untracked。

## 3. Background & Current-State Analysis

### 3.1 v99 基线事实（替代设计 §2 的过时声明）

- v99 HEAD `cbf65cf` 工作树干净；`v13/load.py` 的 `SQL_LOAD_ORDER` 恰 40 项、`STAGE_THROUGH["ce_run"] == 40`。Stage 41 是下一连续编号：列表尾追加 `V13_ROOT / "registry" / "v13_registry.sql"`，字典尾追加 `"registry": 41`。
- 设计 §2 的「HEAD 44 项（agentctl 40–44）」「ce_run 未提交、W4 红」「工作区 load.py 替换五个 stage」均属于主检出 `7db3526` 线的历史状态，对 v99 全部过时；v99 上 Stage 40–44 旧件已按 P1 退役、ce_run 为唯一 Stage 40 且已收口。列入 §11 设计 errata 第 1 条。
- 设计文档原本在主检出 untracked，已复制进本 worktree；里程碑提交一并纳入。

### 3.2 已验证接缝（file:line，实施时复核）

- `v13_append_event`（`v13/schema/v13_core.sql:62-93`）：invoker、`p_source_effect` 可 NULL、EXECUTE 仅授 `v13_route`（`:874-902`）；注册/退役事件落 scope 本 session，`p_source_effect NULL`（先例 `v13/acl/v13_acl.sql:224`）。
- 不可变纪律先例：`v13_policies_frozen`（`v13/schema/v13_core.sql:715-729`）；at-most-one 部分唯一索引先例 `ux_v13_policies_one_active`（`:708-709`）。
- 计数器纪律先例：`v13_tools_meta` singleton + AFTER bump（`:681-694`）；本阶段只借「singleton 行级计数器」形态，bump 由写函数显式执行（裁决 1 删除触发器）。
- `jsonb::text` 键序稳定、哈希确定的既有论证：`v13/schema/v13_core.sql:173-174` 注。
- 递归 CTE + path 环检测先例（下行、cap 64、遇环 RAISE）：`v13/acl/v13_acl.sql:151-179`、`v13/fanout/v13_fanout.sql:170-199`；本阶段上行、cap 32、遇环截断（差异系有意，见 §4.3）。
- 读面谓词形态先例：`v13_ce_read_ok`（`v13/ce_run/v13_ce_run.sql:146-164`）；caller 形态先例 `v13_ce_caller_role`（同文件 `:119-127` 区段）。**只复刻形态，禁止调用任何 `v13_ce_*`**（裁决 3）。
- 角色与列举式 ACL：`v13/schema/v13_core.sql:805-914`；整族 REVOKE + 按角色 GRANT 形态 `v13/ce_run/v13_ce_run.sql:1122-1151`。
- sessions 写者纪律：`v13_sessions_insert_owner` 触发器（`v13/spawn/v13_spawn.sql:567-579`）对超级用户直插同样 RAISE——registry 读面只 SELECT sessions，不 INSERT，无需 owner 例外；测试夹具建链路径见 §9.2 探针 8。
- advance 步 0 七键探针 `v13_probe`（`v13/loop/advance.sql:14-31`）：注册/退役事件推进 scope 的 `max_event_seq` / `session_version`，在途 advance 判 `stale` 重解析——安全方向、语义正确，写文档防误报（设计 §4.1/§5.1 注记，本计划 §6.3）。
- claim 面三份现状（本阶段零改动）：`v13_claim` 五键（`v13/fanout/v13_fanout.sql:266-303`）、`v13_claim_fair` 六键（`v13/fair_claim/v13_fair_claim.sql:421-599`，SIX 断言 `v13/fair_claim/test_fair_claim.py:55` + `:654`）、`v13_ce_claim_bound_effect` 七键（`v13/ce_run/v13_ce_run.sql:252-278`）。

### 3.3 硬约束与冻结门禁机制

1. **纯尾追加**：`r1_load_append_ok`（`v13/plan_arm/test_plan_arm.py:350-455`）只接受相对 `fb295ac6` 的纯尾追加，approved 尾列表当前为 fair_claim/39 → ce_run/40 两项；Stage 41 必须把它扩为三项，并保持全部负例（非规范行、跳号、重复键、未跟踪 stage、未来 stage）在新尾部仍然拒绝（§5.3.1）。`plan_arm` 的 `allow()` 调用路径把 cached 与非忽略 untracked 合并；`goal_supervisor.test_stage_bytes` 直接传 `git ls-files -- v13` 的 cached-only 集合。后者仅在 stage 前缀完全缺失时允许两个精确磁盘例外：CE 的单 SQL 文件，或 registry 的四文件固定名单全部存在；未知 tuple、缺任一文件、错误文件名均保持原文案拒绝。该例外由局部纯内存判定器及表驱动负例证明，不修改 `tracked`。
2. **四文件闭集**：`r1_phase_d_prefix_allowance` 的 `stage40` 集合（`:463-468`）与「stage 40 path is not tracked」负例（`:983-1008`）须对 `stage41` 集合镜像；越界文件 `v13/registry/extra.py` 必须拒绝。
3. **字节冻结**：`r0_source_scope`（`:1011-1282`）只遍历 base 提交路径，`v13/load.py` 已豁免；新增文件不需要新豁免。pi_parity/pi_ports/read_tools 的 `protected_dirty` / `run_guard` / `run_g` 已在 body-only 白名单内（Stage 40 §10.8 修正案），本阶段只做函数体内 planned 集合追加，签名/decorator/模块级字节不变。
4. **loader 尾部断言**：`v13/ce_run/test_ce_run.py:615-616`（40 + 尾两项）与 `v13/fair_claim/test_fair_claim.py:400-405`（40 / `ce_run==40`）必须改为 41/三项形态；`test_reread`（`:495-509`）的 `[37]/[38]/[39]` 索引追加后仍有效，**裁决：不修改 `test_reread`**，避免 `fair_test_ok` 的 `loader_old→loader_new` 精确替换串连锁改动（§5.3.2）。
5. **E4 自动收录**：`E4_DISCOVER = "find v13 -name 'test_*.py' -not -path 'v13/read_tools/*' | sort"`（`v13/read_tools/test_read_tools.py:65`）与 `run_e4`（`:2039-2082`，每条 `uv run python <path>`、`UV_FROZEN=1`、600s、exit 0、逐条恢复 pi_parity trace）自动收录 `v13/registry/test_registry.py`；本阶段 gate 必须在该环境下 exit 0。

## 4. Component & Interface Design

全部对象在 public schema；函数 `SECURITY DEFINER`、`SET search_path = pg_catalog, public`、完整限定表名；属主 = 受信超级用户（setup 验证 `rolsuper` 与既有 `v13_control_operator()` 均为真，同 Stage 40 约定）。标识 UUID、计数 bigint 非负、时间 timestamptz。

### 4.1 三表

**`v13_registrations`**（注册表，append-only + 退役唯一 UPDATE）：

```text
registration_id uuid PK DEFAULT gen_random_uuid()
scope_id        uuid NOT NULL REFERENCES sessions(session_id)
kind            text NOT NULL CHECK (kind IN ('service','tool_profile','prompt_section'))
name            text NOT NULL CHECK (btrim(name) <> '' AND octet_length(name) <= 128)
value           jsonb NOT NULL CHECK (jsonb_typeof(value) = 'object')
depends_on      text[] NOT NULL DEFAULT '{}'
                CHECK (array_position(depends_on, NULL) IS NULL
                       AND NOT ('' = ANY(depends_on))
                       AND (kind = 'service' OR cardinality(depends_on) = 0))
valid_from_rev  bigint NOT NULL CHECK (valid_from_rev >= 1)
valid_to_rev    bigint CHECK (valid_to_rev IS NULL OR valid_to_rev > valid_from_rev)
created_at      timestamptz NOT NULL DEFAULT now()
UNIQUE (scope_id, kind, name, valid_from_rev)
-- at-most-one live（先例 ux_v13_policies_one_active）:
CREATE UNIQUE INDEX ux_v13_registrations_one_live
  ON v13_registrations (scope_id, kind, name) WHERE valid_to_rev IS NULL;
```

冻结触发器 `v13_registrations_frozen`（BEFORE UPDATE OR DELETE，逐行）：DELETE 一律 RAISE；UPDATE 仅允许把 `valid_to_rev` 从 NULL 设为非 NULL；**不可变列名单八列**：`registration_id`、`scope_id`、`kind`、`name`、`value`、`depends_on`、`valid_from_rev`、`created_at` 改写一律 RAISE（M1：`registration_id` / `created_at` 在 policies 先例名单之外，必须显式入列）。退役只能经写面函数；直接 UPDATE `valid_to_rev` 在属主/超级用户手下技术上可行，属运维面，不授权任何宿主角色表 DML（§4.6）。

**`v13_registry_clock`**（全局注册时钟，裁决 1）：

```text
singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton)
revision  bigint NOT NULL DEFAULT 0 CHECK (revision >= 0)
-- 种子：INSERT INTO v13_registry_clock VALUES (true, 0);
-- 种子行缺失 = 配置事故；写面/读面均 RAISE，不做 silent fallback
```

**`v13_registry_meta`**（每 scope 诊断值，裁决 1 降级：不再用于读取寻址）：

```text
scope_id uuid PK REFERENCES sessions(session_id)
revision bigint NOT NULL DEFAULT 0 CHECK (revision >= 0)
-- 该 scope 最后一次成功写所分配的全局 revision；无写则无行
```

设计 §4.2 的 AFTER 行级 bump 触发器**删除不建**；meta 由写函数在五步契约内显式 upsert。读路径不依赖 meta，因此 meta 缺失/落后不影响 context 正确性；gate 仍断言其等于该 scope 最后一次成功写的 `v_new`，防静默腐化。具名消费者：运维漂移审计（按 scope 对账 `v13_registry_meta.revision` 与 `registry/*` 事件的 `max((payload->>'revision')::bigint)`）与未来 ce_run `registration_generation` 映射；探针 3 实现该对账。

### 4.2 写面五步契约（注册/退役共用）

```text
v13_registry_register(p_scope uuid, p_kind text, p_name text,
                      p_value jsonb, p_depends_on text[] DEFAULT '{}') RETURNS jsonb
v13_registry_retire(p_scope uuid, p_kind text, p_name text) RETURNS jsonb
```

均 VOLATILE、SECURITY DEFINER、EXECUTE 仅授 `v13_route`（§4.6）。单次调用只写一行 registrations；request_id 幂等机制**不设**——`already_live` / `not_live` 结构化返回即幂等语义（裁决 4）。步骤（锁序 **clock → meta → sessions（append_event 内）→ registrations**；registry 永不反向先锁 sessions 再锁 clock）：

1. **参数校验**（失败一律 RAISE，零写、时钟不动）：真实 caller 为超级用户或 `v13_route` 成员（经 `v13_registry_caller_role()` fail-closed 内查，不依赖 ACL 单层）；scope 存在；kind 闭集；name 规则；value 形状（§4.5）；`depends_on` 元素点名 kind='service' 注册行的 `name`（不是 `provides` 条目；元素规则同 §4.1 name：btrim 非空、≤128、无 NULL/空串）、去重、≤64 项，且**仅 kind='service' 可非空**；`octet_length(p_value::text) <= 1 MiB`。
2. `SELECT revision FROM v13_registry_clock WHERE singleton FOR UPDATE`——全局串行点；零行 = 种子丢失，显式 RAISE（`v13: registry clock seed missing`），不继续分配。并发同键注册在此串行，后到者在锁等待后重读见 live 行，落 `already_live`。
3. **业务冲突判定（分配前）**：注册查同 `(scope,kind,name)` live 行存在→返回 `{schema_version:1, ok:false, reason:'already_live', registration_id, valid_from_rev}`（携现有 live 行身份）；退役查无 live 行→返回 `{schema_version:1, ok:false, reason:'not_live'}`。均零写、**不分配 v_new、时钟不动**。退役在此取 live 行 `registration_id`。
4. `UPDATE v13_registry_clock SET revision = revision + 1 WHERE singleton RETURNING revision` → `v_new`；`INSERT INTO v13_registry_meta ... ON CONFLICT (scope_id) DO UPDATE SET revision = v_new`（惰性 upsert，meta 行唯一创建时机）。
5. **先事件后行**：注册先生成 `v_id = gen_random_uuid()`，`v13_append_event(p_scope, gen_random_uuid(), 'registry/registered', {schema_version:1, registration_id, kind, name, revision:v_new}, NULL)`，再 INSERT 行（显式 registration_id、`valid_from_rev = v_new`）；退役先 `registry/retired` 同形事件，再 `UPDATE ... SET valid_to_rev = v_new`。任何失败整体回滚。

成功返回 `{schema_version:1, ok:true, registration_id, revision:v_new}`。同事务 register+retire 各走一次五步、`v_new` 各自独立，区间 `[v1,v2)` 无空档（gate：两事件 revision 恰差 1）。

### 4.3 `v13_scope_chain`（上行祖先链）

```text
v13_scope_chain(p_scope uuid, p_actor uuid DEFAULT NULL)
  RETURNS TABLE(scope_id uuid, depth int)   -- STABLE, SECURITY DEFINER
```

- 授权（逐分支复刻 CE 形态）：`p_actor IS NULL` → caller（`v13_registry_caller_role()`）必须是超级用户或 `v13_route` / `v13_recall` 成员；`p_actor` 非 NULL → **不查 caller 角色**，只查 actor 存在且 `p_actor = p_scope OR p_actor = parent_session_id`（self-or-parent）。未知 scope、未授权、未知 actor 一律**返回零行**（不泄露存在性）。亲缘臂在授权上自满足（传 `p_scope` 自身即可），真实边界是 EXECUTE 授予；与 stage 23 `v13_control_authorized` 拒绝 self 的先例不同，本处跟 CE `v13_ce_read_ok` 允许 self，README 记录该分歧。
- 语义：自叶向根递归 CTE，含 `p_scope` 自身（depth 0）第一行；depth 上限 32（截断不 RAISE）；环检测 = path 数组含当前行即截断（fail-closed，不 RAISE）。与下行先例（cap 64、遇环 RAISE，`v13/acl/v13_acl.sql:151-179`）的形态差系有意：cancel 是写面（环=数据损坏须响亮），本函数是读面（环退化为「只看已见祖先」）。`trg_sessions_fork_cols_immutable` 使 parent 写一次后不可改，环经普通 DML 结构性不可达；环截断是防御性代码，gate 只做源码形态断言 + cap 行为断言。
- 私有 `v13_registry_chain_inner(p_scope uuid) RETURNS TABLE(scope_id uuid, depth int)`（同语义、无授权、仅属主）供 context 内部复用；公开入口授权后委托，不复制 CTE。

### 4.4 `v13_registry_context`（解析函数，输出闭集冻结）

```text
v13_registry_context(p_scope uuid, p_rev bigint DEFAULT NULL, p_actor uuid DEFAULT NULL)
  RETURNS jsonb   -- STABLE, SECURITY DEFINER
```

**输出顶层键闭集（十键，不多不少）**：`schema_version`(=1)、`scope_id`、`revision`、`tools_revision`、`services`、`tool_profiles`、`prompt_sections`、`tools`、`unresolved`、`context_hash`。

- **provenance 键裁决**：`services` / `tool_profiles` / `prompt_sections` 每条目 = 该注册行 `value` 对象并入固定 provenance 键 `{name, scope_id, registration_id, valid_from_rev}`；`service` 条目另并入列值 `depends_on`（升序去重）。value 内含同名键时 provenance 覆盖（provenance 是身份，注册内容是数据）。`tools` 行键集恰为 `{name, description, kind, handler, param_spec, enabled}`，**原样并入全部行（含 `enabled = false`，Q1 读取统一；消费方自行过滤）**。`unresolved` 条目恰为 `{name, missing}`（`missing` 为缺失服务名数组，升序）。
- **确定性与哈希**：所有输出数组 `ORDER BY name`；`depends_on` / `missing` 升序；`context_hash` = `encode(digest((输出对象 - 'context_hash')::text, 'sha256'), 'hex')`，jsonb::text 键序稳定（`v13/schema/v13_core.sql:173-174`）。`unresolved` 与 `tools_revision` 均**进** hash（裁决：诊断差异即世界差异）。
- **revision 语义（裁决 1/2）**：注册行 append-only（退役也是新 revision，不 UPDATE 历史内容）⇒ 同一 revision 的注册内容固定；`tools` 是可变的第二来源，由 `tools_revision` fence 另行钉版。`p_rev NULL` → `v_eff` = 时钟当前值（**不是** scope meta；时钟零行 = 种子丢失，读面 RAISE，不返回假 revision 0）；`p_rev` 非 NULL 为 as_of。`p_rev = 0` → 空注册面（`valid_from_rev >= 1` 恒空集）：`revision:0`、三个 kind 数组空，**`tools` 仍返回全部行、`tools_revision` 当前值**（tools 无时间轴）。`p_rev < 0` → RAISE 参数错（读面无写，不适用「零写」措辞；参数校验先于授权，RAISE 文案不含 scope 信息）。`p_rev > 时钟` → **钳制**：`v_eff = 时钟当前值`，`revision` 回显时钟值，内容按时钟求值；保证 `revision` 始终是已提交的全局值，维持「同 revision 必同内容」与钉版缓存键契约（review P1-1；不属于四条 Locked Decisions）。
- **as_of 谓词（半开 `[from, to)`，先例 thresholds `:482-485`）**：`valid_from_rev <= v_eff AND (valid_to_rev IS NULL OR valid_to_rev > v_eff)`。边界 gate：N-1 不可见、N 与 M-1 可见、M 不可见。
- **解析算法（add-only 依赖闭包）**：`v13_registry_chain_inner` 按 depth 升序逐 scope 取 as_of 可见行；每个 `(kind, name)` 取**第一个**（近端遮蔽远端）。对 service 名集合 `S0`：
  1. `resolved = {}`；
  2. 最多迭代 `|S0| + 1` 轮；每轮按 name 升序扫描未解析 service，若其全部 `depends_on` 已在 `resolved` 中，则加入；
  3. 某轮无新增则停止；
  4. 未进入 `resolved` 的 service 全部进 `unresolved`，`missing` = 其 `depends_on` 中不在 `resolved` 的名字（升序）。
  该算法从空集加起，**环（A→B→A）永不进入 resolved，两者均落 unresolved**；迭代上限是 belt，触顶视为实现 bug，整批 service 落 unresolved，不 RAISE。`depends_on` 只许点名 kind='service' 注册行的 `name`（不是 `provides` 条目）；tool_profile / prompt_section 不参与依赖。
- **授权与规范空形**：scope 不存在、未授权、`p_actor` 不存在 → 返回**规范空 context**：`{schema_version:1, scope_id:null, revision:0, tools_revision:0, services:[], tool_profiles:[], prompt_sections:[], tools:[], unresolved:[], context_hash:<该固定形状的确定性哈希>}`。**已知但空注册的授权 scope 不走规范空形**：回真实 `scope_id`、当前 `revision` / `tools_revision`、空 kind 数组与全部 `tools` 行——两种空形在 `scope_id` / `revision` / `tools` 三处可区分，gate 逐键断言。私有 `v13_registry_read_ok(p_actor uuid, p_scope uuid) RETURNS boolean` 逐分支复刻 `v13_ce_read_ok` 形态（NULL 查 caller 角色；非 NULL 只查 self/parent），但零 `v13_ce_*` 调用；所有 NULL 比较 fail-closed 返回 false（吸收 Stage 40 §10.7 教训）。

### 4.5 value 形状校验（写面第 1 步，全失败 RAISE）

| kind | 规则 |
|---|---|
| `service` | 键集 ⊆ `{schema_version, provides, config}`；`provides` 必填：数组 1–64 项、去重、每项匹配 `^[A-Za-z_][A-Za-z0-9_]*$` 且长 1–63（**不做 pg_proc 校验**，裁决 Q6）；`config` 可选且须为 object；`schema_version` 若现须 = 1 |
| `tool_profile` | 键集 ⊆ `{schema_version, handlers, interruptible}`；`handlers` 若现为去重非空字符串数组（1–64 项、每项 ≤128）；`interruptible` 若现 ∈ `('required','best_effort','unsupported')`；两内容键至少居一 |
| `prompt_section` | 只要求是 object；形状随首个消费方定型（保留开放点 3，台账 S41R-10） |

`tool_profile` 与 `v13_interruptible()`（`v13/fanout/v13_fanout.sql:37-44`）优先级（开放点 1 关闭）：**函数优先、profile 为覆盖面**；本阶段 profile 无消费者，SQL 注释与 README 写明，静态探针断言注释存在。

### 4.6 角色、caller 与 ACL 矩阵

| 对象 | PUBLIC | v13_worker | v13_resolve | v13_recall | v13_route |
|---|---|---|---|---|---|
| `v13_registrations` DML | 无 | 无 | 无 | 无 | 无 |
| `v13_registrations` SELECT | 无 | 无 | 无 | SELECT | SELECT |
| `v13_registry_meta` DML | 无 | 无 | 无 | 无 | 无 |
| `v13_registry_meta` SELECT | 无 | 无 | 无 | SELECT | SELECT |
| `v13_registry_clock` 全部 | 无 | 无 | 无 | 无 | 无（内部表，仅属主） |
| register / retire | 无 | 无 | 无 | 无 | EXECUTE |
| scope_chain / context | 无 | 无 | 无 | EXECUTE | EXECUTE |
| caller / read_ok / chain_inner / frozen trigger | 无 | 无 | 无 | 无 | 无（仅属主） |

- 读面授两角色是**有意收窄**（M2）：较 `v13/schema/v13_core.sql:854-856` 三角色读面先例少 `v13_resolve`——注册面是能力面、判断面无消费者，最小授权优先。不变量句写入 SQL 注释与 gate：`v13_resolve` 对全部 registry 函数 42501。
- 创建与 REVOKE 同事务，避免默认 PUBLIC EXECUTE 窗口；整族 REVOKE + 按角色 GRANT 形态照搬 `v13/ce_run/v13_ce_run.sql:1122-1151`。
- `v13_registry_caller_role()`：`current_setting('role')` 为 NULL/空串/`'none'` 时回落 `session_user`，否则取之；验证角色存在；不接受 caller 参数，不看 definer 的 `current_user`。
- 部署前提沿用 Stage 40：专用库收回宿主/继承角色的数据库 TEMPORARY 与 public schema CREATE（setup 验证），不泛化到其他 stage 库。

## 5. File-by-File Impact

### 5.1 新增四文件（形态照搬 Stage 40 四件套）

1. **`v13/registry/v13_registry.sql`**：`BEGIN…COMMIT` 单事务；三表 + 部分唯一索引 + frozen 触发器 + 时钟种子 + 写面两函数 + 读面两函数 + 三个私有 helper + 整族 REVOKE/GRANT。不 `CREATE OR REPLACE` 任何既有函数，零交叉引用 ce_run（静态断言无 `v13_ce_` 字符串）。
2. **`v13/registry/setup_db.py`**：以 `v13/ce_run/setup_db.py` 全文为模板改名适配——库名 `ll_registry_<pid>_<6hex>`（`_NAME_RE` 同步），`EXPECTED_TABLES` = 三个 registry 表；**零新 sequence**（无 bigserial；`validate_delta` 断言新增 sequence 数 == 0，区别于 ce_run 的 1）；装载序：`load_stage(server, name, "ce_run")`（经 40 个文件）→ 建宿主角色 → `restrict_database` → 部署约束/属主验证 → before 快照 → 局部 helper `load_registry(server, db)` 仅执行 `v13_registry.sql` 一次（禁止 `load_stage(…,"registry")` 重跑 1–40）→ after 快照 → `validate_delta`：新增函数名匹配 `v13_registry_*` 或 `v13_registrations_frozen` 或 `v13_scope_chain`（编排裁决 2026-10-18：§4.3/裁决 3 锁定的公开名 `v13_scope_chain` 不匹配前两模式，delta 名单显式补一项；不放宽任何既有断言）、属主超级用户、definer + 固定 search_path、ACL 矩阵与 §4.6 逐项相等；角色/OID/名称生命周期守卫与 cleanup 语义原样保留。对象入口使用 database.roles，字符串入口要求 server 并使用 _role_names(name)，四个 alias 均选择 per-database 临时宿主角色；role=None 不传 user，其他显式角色名原样直通，不重试/回退或新增名称校验。
3. **`v13/registry/test_registry.py`**：§9.2 十六组探针；import-safe（导入零副作用，`__main__` 才建库）；harness 头部约定（`sql` / `idle` helper、`load_module`、BASE/PHASE_D 常量）照搬 `v13/ce_run/test_ce_run.py:1-90`；新增常量 `CE_RUN_TIP` = v99 里程碑前 HEAD 全 SHA（W1 实施时记录，当前即 `cbf65cf` 的全形），用于 `v13/ce_run/v13_ce_run.sql`（及 setup/README）字节钉；`test_ce_run.py` 是 W1 要改的守卫文件，**不纳入该字节钉**；探针 1 用 `git diff CE_RUN_TIP -- v13/ce_run/test_ce_run.py` 的 hunk 范围断言改动仅限 `native_load_untouched` 的 loader 尾部断言，并在 S41R 台账记录。
4. **`v13/registry/README.md`**：范围（纯注册面、无消费侧）、时钟/区间语义、权限矩阵、双标量钉版预告（消费侧提案落地前无强制）、偏差索引、真实门禁命令与结果（W4 填入）。

### 5.2 `v13/load.py`

`SQL_LOAD_ORDER` 尾追加一行 `V13_ROOT / "registry" / "v13_registry.sql",`；`STAGE_THROUGH` 尾追加 `"registry": 41,`。纯尾追加，无删除行。

### 5.3 六个冻结守卫文件的精确适配

1. **`v13/plan_arm/test_plan_arm.py`**（全部改动在 `r1_*` 函数体内，属既允许重写范围）：
   - `r1_load_append_ok`（`:350-455`）：`approved` 追加 `("registry", "v13_registry.sql", "registry", 41)`；失败文案改为 `"append is not fair_claim/39 then ce_run/40 then registry/41: " + str(got)`。`order_names` 不变（尾部位置已由 approved 相等性钉死）。「append stage is not tracked」的 ce_sql 特例原样保留。2026-10-18 Oracle 事实订正：`allow()` 路径合并 cached + untracked，但 `goal_supervisor.test_stage_bytes` 直接传 `git ls-files -- v13` cached-only。仅在 tracked 无该 stage 前缀时，新增精确 `("registry", "v13_registry.sql")` 磁盘例外，要求相对 AGENT_ROOT 的 SQL/setup/test/README 四个固定路径全部 is_file；未知 tuple、错误文件名或缺任一文件仍拒绝，不修改 tracked。局部纯判定器表驱动证明四个缺文件、单文件、错误名、未知 stage、CE 存在/缺失边界；结构断言、顺序与 allow 四文件闭集均不变。
   - 负例重锚（`:930-1008` 区）：保留现有全部 ce_run 锚负例；新增/改锚到新尾部——`'"registry": 41,'` → `41a` 拒（非规范追加）；→ `42` 拒（不连续）；`"v13_registry.sql"` → `"v13_registry_extra.sql"` 拒（approved 不匹配）；`'"registry": 41,'` → `'"ce_run": 41,'` 拒（重复 stage key）；registry 之后再追加 `not_scheduled`/42 的 future 样本拒（approved 文案新形）。
   - `r1_phase_d_prefix_allowance`（`:456-1008`）：新增 `stage41 = {四个 registry 路径}`；`allow()` 放行条件扩为 `name.startswith(prefixes) or name in stage40 or name in stage41`；**fresh-file 差集断言（`:702`）改为 `extra - known_names - stage40 - stage41 <= fresh_ok`**，并加合成负例证明仅 stage41 放行、其他新路径仍拒；`stage41 - tracked` 非空拒 `"stage 41 path is not tracked"`；越界负例增 `v13/registry/extra.py`（随 `v13/ce_run/extra.py` 同组）。
   - `r0_source_scope`：**零改动**（新文件非 base 路径；`v13/load.py` 已豁免；piswift driver 精确字节证明不受影响）。
2. **`v13/fair_claim/test_fair_claim.py`**：仅 `test_stage_bytes`（`:400-406`）的 `tail_ok` 做最小增量——保留原有前两个 `files_through("fair_claim")` 合取，只把 `len(SQL_LOAD_ORDER) == 40` 改为 `== 41`，并在 `STAGE_THROUGH["ce_run"] == 40` 后追加 `STAGE_THROUGH["registry"] == 41`。**不得删除既有合取项**（`fair_test_ok` 对该函数 `continue` 豁免，无结构守卫兜底）。`test_reread`、`SIX`、`:654` sorted 比对零改动。`r1_load_retirement_ok` 的容忍度已核验：纯追加时 `removed == []` 必过（`v13/plan_arm/test_plan_arm.py:336-340`），Stage 40 先例同；该项不再是未知风险。
3. **`v13/ce_run/test_ce_run.py:615-616`**（`native_load_untouched`）：`len(load.SQL_LOAD_ORDER) == 41` 且 `[-2:] == ["v13_ce_run.sql", "v13_registry.sql"]`；`[:39]` 冻结字节循环语义不变。
4. **`v13/pi_parity/test_pi_parity.py`**：`protected_dirty` planned 集（`:132-160`）追加 registry 路径（最小必要为 `v13/registry/v13_registry.sql`；四个路径全加是无害超集）。函数体编辑，在 r0 body-only 白名单 `{protected_dirty, run_guard}` 内。`FROZEN_PREFIXES`（`:73`）与 `historical_frozen` / `stage40_committed_guards`（`:191-200`）不含 registry，无需 committed 面放行。
5. **`v13/pi_ports/test_pi_ports.py`**：`protected_dirty` planned 集（`:58-85`）追加 registry 路径（最小必要为 `v13/registry/v13_registry.sql`；四个路径全加是无害超集）。必需性：G2 查 `git diff HEAD^ HEAD`（`:110-121`），里程碑提交后 registry 文件进入该窗口。
6. **`v13/read_tools/test_read_tools.py`**：`protected_dirty` planned 集（`:1958-1983`）追加 registry 路径（最小必要为 `v13/registry/v13_registry.sql`；四个路径全加是无害超集）。E4 收录见 §3.3.5，不改 `run_e4`（`:2039-2082`）/ `E4_DISCOVER`（`:65`）。

### 5.4 收尾评审工件

- `docs/reviews/v13-control-plane-conformance-matrix-2026-09-26.md`：新增 `## Stage 41 (registry, 新实现)` 节（W4 跑绿后填真实日期/命令/检查数）。命名调和规则：既有 `## Stage 41` 节（旧 agentctl_verbs，P1 退役行 #87）**保留原标题不动**；新节以 `(registry, 新实现)` 后缀消歧——与 Stage 40 退役行和 `## Stage 40 (ce_run, 新实现)` 并存的先例一致。
- `docs/reviews/v13-control-plane-deviation-ledger-2026-09-26.md`：文末追加 `## Stage 41 (registry) 偏差台账`（与矩阵同规则），行号用独立命名空间 `S41R-1…S41R-13`，避免与在册旧 `## Stage 41` 的 `S41-1/S41-2/S41-D3` 撞名撞号。表格沿用 S40 格式：S41R-1 全局时钟取代每 scope 计数（meta 降级诊断）；S41R-2 `tools_revision` 第二 fence 入 hash；S41R-3 读面两角色、resolve 拒（有意收窄，非 `:854-856` 同构）；S41R-4 caller/read_ok 复刻 CE 形态但零 `v13_ce_*` 调用；S41R-5 上行 cap 32 + 环截断 vs 下行 cap 64 RAISE 先例；S41R-6 claim 加键留 §11.5，SIX 不动；S41R-7 注册事件推进 `max_event_seq` 致在途 advance stale 系有意；S41R-8 `v13_interruptible()` 函数优先、profile 覆盖；S41R-9 `unresolved` 入 hash；S41R-10 `prompt_section` 形状缓议；S41R-11 `p_rev` 负数 RAISE / 0 空面 / 大于时钟钳制；S41R-12 ce_run `registration_generation` 映射仍可选、本阶段零触碰；S41R-13 六守卫适配（含 `:702` fresh-file 差集与 fair_claim 合取保留）。
- 设计文档与本计划随里程碑提交（W0 不独立提交，见 §2）。

## 6. State & Data Flow

### 6.1 时间轴

单次写调用一个 `v_new`；区间半开 `[valid_from_rev, valid_to_rev)`；同事务 register+retire 区间 `[v1,v2)` 无空档。时钟只被成功分配推进；`already_live` / `not_live` / 参数 RAISE 均不动时钟（gate 断言前后时钟值相等）。批量多行共享 `v_new` 的情形本阶段不存在（单写调用一行），文档注明未来批量入口须同值共享。时钟号是全局的：某 scope 长期无写时其 meta（诊断值）落后全局时钟是常态，不是漂移故障。

- **运维纪律**：时钟行锁持有到事务提交；注册写事务必须短，不得在事务内做外部 IO/等待。并发注册在 READ COMMITTED 下后到者等待并见 live；REPEATABLE READ 下可能 40001，属安全方向，README 记录。

### 6.2 读路径

`context(scope, NULL, actor)` → 同事务快照读时钟与 `v13_tools_meta.revision`（STABLE 函数内全部查询共享调用语句快照，保证两标量与行集同点）→ 授权/存在性（不通过→规范空形）→ 链（depth 升序）→ as_of 可见行 → 近端遮蔽 → service 依赖闭包 → tools 并入 → `ORDER BY name` → hash。STABLE、零写、零锁（读面不加 FOR UPDATE）、零 notify。并发写进行中时两读可能不同时刻不同结果——这是时钟语义本身，不是 race；确定性 gate 用钉版 `p_rev` 或无并发写窗口断言逐字节相等。

### 6.3 事件与 advance 交互（有意行为）

注册/退役事件经 `v13_append_event` 推进 scope 的 `next_seq`（`session_version`）与 `max_event_seq`（`v13_probe` 七键之二，`v13/loop/advance.sql:16-30`）；该 scope 的在途 advance 步 0 比对判 `stale` 重解析——世界变了弃批，安全方向。README 与台账 S41R-7 写明，探针 14 只断言探针键变化，不跑 advance。CE run 作 scope 时 CE 驱动不消费七键探针，互不影响。

### 6.4 零写拒绝与 RAISE 边界

- RAISE（写面）：caller 非 route/超级用户、未知 scope、kind 越集、name 空/超长、value 形状违例、`depends_on` 越规、value 超 1 MiB。结构化返回（零写、时钟不动）：`already_live`、`not_live`。
- RAISE（读面）：`p_rev < 0`（参数校验先于授权，文案不含 scope/actor）与时钟种子缺失。其余拒绝路径 = 规范空形/零行，不 RAISE、不泄露存在性。
- 非预期数据库故障一律传播、整体回滚；写面无 `WHEN OTHERS`。
- 边界：空 `depends_on` 默认 `{}`；`p_rev` 恰等于某行 `valid_to_rev` → 该行不可见（半开上界）；链长恰 32 → 全返回，33+ → 截断至 depth 31；scope 为根（无父）→ 链单行；`p_rev > clock` → **钳制到时钟当前值**，回显时钟值（确定性 gate 断言）。

## 7. Tradeoffs, Risks & Non-Goals

- **全局时钟是串行点**：所有注册写在时钟行上串行；注册是低频管理面操作，换取 as_of 寻址的单调全局轴与无空档区间，优于每 scope 计数的跨 scope 不可比性。时钟行无 bump 触发器，写路径单一可审。
- **空 revision 无害**：时钟只 +1/次成功调用，无跳号；即便未来批量引入空隙，as_of 命中空集即空面，语义无损（设计 §10 论证沿用）。
- **meta 降级为诊断**：读路径不依赖它，漂移（如未来某写路径漏 upsert）不影响正确性；gate 仍断言其等于最后触达值以防静默腐化。
- **tools 无时间轴**：`tools` 是就地可变冻结表，as_of 旧 revision 仍返回当前 tools；`tools_revision` 是第二 fence，消费方必须按双标量钉版。这是本阶段最明确的半开语义，README/台账记录。
- **环截断分支结构性不可达**（parent 写一次不可改）：保留为防御；gate 只做源码形态断言 + cap 行为断言，不伪造环。
- **与 ce_run 并立**：零函数互调；ce_run 三 generation 列去向不变（`registration_generation` 可选映射留 ce_run 后续，`owner/continuity` 永不收编）。未来消费侧若在 INVOKER 的 `v13_probe` / `v13_claim` / `v13_claim_fair` 内读时钟，需授 SELECT 或加 definer helper；本阶段不做，台账备查。
- **非目标**：消费侧（claim 加键、advance 第八键、superseded 吸收、worker 钉版契约）全部留设计 §11.5 后续提案；`hook` kind 缓建；`policy` kind 永不进；无 RLS、无 notify/waiter 面、无 TTL/GC；注册面不取消在途 effect。

## 8. Implementation Order

1. **W0**：修订设计文档 errata（§11）；本计划与设计对齐。
2. **W1**：load.py 追加 + 六守卫精确适配；先实跑 `test_fair_claim.py` 验证 §5.3.2 未知项。
3. **W2**：`v13_registry.sql`（三表 → 触发器 → 写面 → 读面 → ACL）+ `setup_db.py`，定向实库交接。
4. **W3**：十六组探针 + README。
5. **W4**：全量 50 项顺序回归（48 脚本 + 2 额外 goal_supervisor 探针；逐条恢复 pi_parity trace，首个不符合预期退出码/语义即停；两额外探针预期 1/2）→ 矩阵/台账填真实结果 → 集成静态 review → 人工核对 `git diff cbf65cf -- v13/plan_arm/test_plan_arm.py` 确认改动只在 `r1_*` 体内 → 逐路径提交 → 同清单净树复验 → `git push origin v99`。

## 9. Verification: Gate Matrix

### 9.1 命令约定

每个 stage test 是独立脚本：`UV_FROZEN=1 uv run python <path>`，退出码 0 = 通过（仓库约定）。`v13/registry/test_registry.py` 必须 import-safe（导入零副作用；仅 `__main__` 建库），并在 E4 嵌套扫描下 exit 0。

### 9.2 十六组具名探针（`v13/registry/test_registry.py`）

| # | 探针 | 必须验证 |
|---|---|---|
| 1 | native_load_untouched | Stage 1–39 字节钉（base/phase_d）；`v13/ce_run/v13_ce_run.sql`（及 setup/README）对 `CE_RUN_TIP` 字节钉；`test_ce_run.py` 的 `git diff CE_RUN_TIP` hunk 仅限 loader 尾部断言；before/after 快照 delta 仅三个新表 + registry 函数/ACL，既有函数/表/角色/ACL 不变；loader 尾 41 与尾两项；静态断言 registry SQL 无 `v13_ce_` |
| 2 | native_plan_arm_closed_set | 四文件闭集；plan_arm 全部负例在新尾部仍拒；缺文件/extra.py/越界 stage；fresh-file 差集负例（`:702`，仅 stage41 放行） |
| 3 | native_register_happy | 三 kind 各一；五步顺序（事件先于行：事件 payload.revision == 行 valid_from_rev）；meta 惰性 upsert 与值；meta 对 registry 事件 `max((payload->>'revision')::bigint)` 的运维对账；返回四键 |
| 4 | native_retire_no_gap | 同事务 register+retire 两事件 revision 恰差 1；区间 `[v1,v2)`；`valid_to_rev > valid_from_rev` |
| 5 | native_already_live_not_live | 双结构化返回零写（含 `already_live` 携现有 registration_id/valid_from_rev）；前后时钟、meta、行数、事件数全等；重复调用不产生副作用 |
| 6 | native_frozen_matrix | 八列不可变各一改（含 `registration_id`、`created_at`）均 RAISE；DELETE RAISE；`valid_to_rev` 外 UPDATE RAISE；函数路径外直接 UPDATE 仅属主可达 |
| 7 | native_one_live_concurrency | 双连接同 `(scope,kind,name)` 并发 register 恰一胜一 `already_live`；复用 `ThreadCall` / `wait_blocked` 屏障（`v13/ce_run/test_ce_run.py:535-590`），不用 sleep；部分唯一索引 23505 属主直插背板 |
| 8 | native_chain | 自身 depth 0、叶→根序；33 深链截断 32 行；源码含 path 数组环守卫（静态针）；夹具建链走属主连接 `SET ROLE v13_spawn_owner` 直插（fork 列写一次，仅夹具） |
| 9 | native_context_determinism | 两独立连接同 `(scope, rev)` 钉版调用逐字节等 + hash 等；乱序注册输出仍 `ORDER BY name`；**祖先 scope 在 rev 之后新增注册：旧 `(child, rev)` 输出逐字节不变，live 输出包含新祖先行**（全局时钟核心证明） |
| 10 | native_as_of_boundaries | N-1 不见、N 与 M-1 见、M 不见；`p_rev=0` 空面但 tools/tools_revision 当前；`p_rev>clock` 钳制且回显时钟值（确定性断言）；`p_rev<0` RAISE |
| 11 | native_unresolved | 缺依赖 service 落 unresolved 不 RAISE；传递未解析（A 依 B、B 缺 C → A、B 均落）；**环 A→B→A → 两者均 unresolved**；注册补齐后消失；unresolved 变化而 live 行不变时 hash 变（入 hash 证明） |
| 12 | native_value_shape | §4.5 全负例矩阵 + 1 MiB 上限 + 非 service 携 `depends_on` 拒 |
| 13 | native_acl_roles | route 写真；recall/resolve/PUBLIC/worker 写 42501；recall+route 读真、resolve 读 42501；三表直 DML 全拒（clock 表零角色访问）、registrations/meta SELECT 两角色；SET ROLE 降权；`p_actor` NULL 角色臂真、非 NULL actor 不查角色（self/parent 真、grandparent/sibling/陌生/未知 actor 规范空形）；已知空 scope 输出与规范空形逐键可区分 |
| 14 | native_events_and_probe | 事件类型/payload 键集/`source_effect_id` NULL；落 scope 本 session；`v13_probe` 的 `session_version`/`max_event_seq` 前移（有意 stale 注记） |
| 15 | native_static_setup | 四 wrapper 字符串入口真实 session_user/current_user 等于记录的临时角色；默认 route、None 与 owner 相同、显式 plain 名直通、缺 server 精确 ValueError；成功连接 closing+idle、只查身份；import-safe、无网络/pg_sleep；库名/OID 生命周期；同名拒建、创建失败不误删、cleanup 异常不遮蔽原错误；时钟种子缺失时写/读均 RAISE |
| 16 | native_tools_revision | context `tools_revision` == `v13_tools_meta.revision`；属主插一行 enabled tool 后输出 tools 数组与 hash 同步变；**disabled 行仍原样出现在 tools 数组且 `enabled=false`**；tools 无时间轴：钉版旧 rev 仍见新 tools（README/台账注明） |

覆盖矩阵须把每条探针与设计 §11.3 的 gate 断言逐项映射；未覆盖项写缺口，不得用「源码在场」代替实跑。

### 9.3 回归集合（提交前后均 exit 0）

核心集合：

```bash
UV_FROZEN=1 uv run python v13/registry/test_registry.py
UV_FROZEN=1 uv run python v13/ce_run/test_ce_run.py
UV_FROZEN=1 uv run python v13/plan_arm/test_plan_arm.py
UV_FROZEN=1 uv run python v13/fair_claim/test_fair_claim.py
UV_FROZEN=1 uv run python v13/pi_parity/test_pi_parity.py
UV_FROZEN=1 uv run python v13/pi_ports/test_pi_ports.py
UV_FROZEN=1 uv run python v13/read_tools/test_read_tools.py
UV_FROZEN=1 uv run python v13/spawn/test_spawn.py
UV_FROZEN=1 uv run python v13/acl/test_acl.py
UV_FROZEN=1 uv run python v13/twophase/test_twophase.py
```

十道是核心集合，不是回归全集。提交前后均跑 Stage 40 收口清单 47 脚本（逐条清单见 `v13/ce_run/README.md`「47 条全量回归」节）+ registry = **48 脚本**，外加两个 goal_supervisor 额外探针（`--unattended-continuation` exit 1 拒绝尾部、非法参数 exit 2 usage；默认 `test_goal_supervisor.py` 已含在 48 脚本内），共 **50 项**。逐条独立执行、逐条恢复 `v13/pi_parity/traces/pg.jsonl`、首个无效即停。最终路径/命令/退出码清单写入 README；不得以失败过滤缩小集合。E4 嵌套收录见 §3.3.5——registry gate 同时在 read_tools gate 内被执行。W4 不要求 `PI_PARITY_REQUIRE_ALL=1`（registry 无框架面，默认模式足够）；若环境已有严格模式证据，可另行记录，不作为本里程碑条件。

## 10. Locked Decisions 与开放点裁决记录

### 10.1 Locked Decisions（2026-10-17 Oracle 裁决，优先于设计正文）

1. **全局注册时钟取代每 scope 计数寻址**：singleton `v13_registry_clock` 种子 0；写函数先 `FOR UPDATE` 锁时钟、校验业务冲突，再 `UPDATE … RETURNING` 分配全调用共享的 `v_new`；`v13_registry_meta` 降级为「最后触达的全局 revision」诊断值；删除设计 §4.2 的 AFTER 行级 bump 触发器，写函数显式 upsert meta；锁序 clock → meta → sessions → registrations；`p_rev NULL` 读时钟。
2. **`tools_revision` 为第二 fence**：context 输出增 `tools_revision`（同语句快照读 `v13_tools_meta.revision`）并入 `context_hash`；缓存/钉版身份 = `(scope, registry_rev, tools_revision)`；未来 claim 合同携双标量，加键仍留设计 §11.5。
3. **读面加 `p_actor`**：`v13_scope_chain(p_scope, p_actor DEFAULT NULL)`、`v13_registry_context(p_scope, p_rev DEFAULT NULL, p_actor DEFAULT NULL)`；NULL = 只读 operator（真实 caller 为超级用户或 route/recall 成员），非 NULL 须为自身或直接父；未知 scope/未授权/未知 actor 统一规范空形（context）或零行（chain）；私有 `v13_registry_read_ok` 复刻 CE 谓词形态但禁止调用任何 `v13_ce_*`。
4. **写面契约**：SECURITY DEFINER、固定 search_path、仅 route EXECUTE；校验失败 RAISE；`already_live` / `not_live` 结构化零写且不分配 revision；冲突在分配 `v_new` 前判定；分配后先 `registry/*` 事件（`p_source_effect NULL`）后写行；失败整体回滚；同事务 register+retire 各自分配、区间无空档。

### 10.2 scaffold 开放点关闭记录（每条 = 规则 + gate）

| 原开放点 | 裁决 | gate |
|---|---|---|
| context provenance 键集与 tools 列集 | §4.4 十键顶层闭集；kind 条目 = value ⊕ `{name, scope_id, registration_id, valid_from_rev}`（service 另加 `depends_on`）；tools 恰 `{name, description, kind, handler, param_spec, enabled}` 且**全部行**（含 disabled） | 探针 9/13/16 逐键闭集断言 |
| 已知但空注册 scope 输出 | 回真实 `scope_id`、当前 `revision`/`tools_revision`、空 kind 数组 + 全部 tools；规范空形只用于未知/未授权/未知 actor | 探针 13 两形逐键区分 |
| `p_rev` 越界 | `> clock` **钳制到时钟当前值并回显时钟值**（Oracle §1 的自然求值被 review P1-1 收紧，以维持无条件「同 revision 必同内容」；不属四条 Locked Decisions）；`< 0` RAISE；`= 0` 空注册面（tools 仍当前） | 探针 10 |
| 设计修订落点与 W0 边界 | §10.3 的 11 条 errata；W0 不独立提交，随里程碑一并入库（Stage 40 先例） | 里程碑提交文件清单核对 |
| 设计 §10 保留点 1/2/5 | 函数优先于 profile（S41R-8）；`unresolved` 入 hash（S41R-9，探针 11）；cap 32 + 环截断确认（S41R-5，探针 8） | 见各行 |

### 10.3 设计文档 errata（W0 精确落点）

1. **§2 基线段重写**：v99 `cbf65cf`、40 项尾 `fair_claim/39 → ce_run/40`、Stage 40 已收口、registry = 41；删除「44 项/ce_run 未提交/W4 红/替换五 stage」表述并注明其属主检出 `7db3526` 线的过时状态。
2. **§4.2**：删 AFTER bump 触发器段；改写为时钟 + 五步契约 + 锁序 clock→meta→sessions→registrations；meta 诊断声明与具名消费者（运维对账/未来 ce_run 映射）；时钟种子缺失写/读均 RAISE；`already_live` 返回携 live 行身份。
3. **§4.3**：签名加 `p_actor`；逐分支谓词（NULL 查 caller 角色；非 NULL 只查 actor 存在 + self/parent，不查角色）；零行拒绝语义；上行 cap 32/截断与先例差异注；与 stage 23 self-deny 先例的分歧记录。
4. **§4.4**：签名加 `p_actor`；输出十键闭集与 provenance 键；`tools_revision` 入列/入 hash；`tools` 全部行；`p_rev NULL` 读时钟；`p_rev > clock` 钳制 / `<0` RAISE / `=0` 空面三规则；规范空形与已知空形区分；add-only 依赖闭包与环 unresolved；`depends_on` 点名 service 注册 `name`。
5. **§4.6**：补 `v13_registry_clock` 内部表零角色访问；补「`v13_resolve` 对全部 registry 函数 42501」不变量句，删「同构」措辞的残余含义。
6. **§5.2**：注明 stage 41 的 context 输出已携双标量；claim 加键不动、仍归 §11.5。
7. **§6/§10/§11 对齐**：断言 1（两连接逐字节等 + hash 等）落本 stage 探针 9；保留点 1/2/5 标「已锁定」并指向 §10.2；§11.3 gate 清单扩入 already_live/not_live 零写不动时钟、时钟单调、两连接确定性、`p_rev` 三边界、规范空形 vs 已知空形区分。
8. **§8 台账**：追加一行指向本计划 S41R 段（v13 行号面基线以 v99 为准）。
9. **§12 附录基线表**：「HEAD 版 load.py = 44 项」等行标注为 `7db3526` 线事实，v99 线另列 40 项基线。
10. **§1 / §3 Q3 / §9.1**：把「每个 scope 一个单调注册修订号」「generation 降级为每 scope 修订号」「把单点 revision 按 scope 分片」改为全局时钟；§4.1 列注「生效的 scope 修订号」改为全局 revision。
11. **全文通则**：凡「ce_run 未提交/未收口」表述（§3 Q1、§5.2.3、§7.4、§7.5 等）按 v99 事实改写；凡「每 scope 修订号」按 §4.2 新口径读。

## 11. 提交边界与推送

唯一里程碑提交内容：`v13/registry/` 四文件、`v13/load.py`、六个守卫文件、设计文档（含 errata）、本计划、矩阵、台账。逐路径 `git add`；提交信息 `v13: add spacetime registry stage 41`。提交后同一 50 项清单净树复验全绿后 `git push origin v99`；失败停步、修正后追加修复提交，不 force/reset。economy H1 历史根因诊断、PiSwift 0f44e03 适配、消费侧 §11.5 提案均为独立后续变更，不并入本里程碑。

## 12. References

- 设计：`docs/designs/v13-spacetime-registry-2026-10-17.md`（errata 见 §10.3）；裁决记录即本计划 §10.1（主检出 `prompt-exports/` 导出不作为本 worktree 交付依赖）。
- 结构模板与 Stage 40 证据：`docs/plans/v13-ce-run-six-verbs-2026-10-15.md`、`v13/ce_run/README.md`。
- 工件：`docs/reviews/v13-control-plane-conformance-matrix-2026-09-26.md`、`docs/reviews/v13-control-plane-deviation-ledger-2026-09-26.md`；本计划的设计评审：`docs/reviews/v13-registry-stage41-plan-review-2026-10-17.md`。
- 代码接缝：见 §3.2 逐条 file:line。
