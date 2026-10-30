# v13 stage 44 `ce_map` 计划评审：对两路生成计划的核对

| 项 | 值 |
|---|---|
| 日期 | 2026-10-09 |
| 评审对象 | `docs/plans/v13-stage44-ce-map-2026-10-09.md`（集成计划） |
| 基线 | `prompt-exports/oracle-plan-2026-10-09-110718-stage-44-ce-map-plan-a50c.md` 的两段生成计划（`### Oracle` ≈:99、`### Oracle 2` ≈:840） |
| 性质 | 评审，不改计划、不改代码 |

## Context / Scope

只核对五类问题：集成时被丢/弱化/泛化的实现性内容；欠规格接缝、未决决策、矛盾、错误引用、缺失依赖；被活体代码否证的细节；两路基线与集成计划都缺席的需求；会改变设计或施工顺序的问题。已知调和项（Unix-socket 门、load_stage hedge、run_psql 抛错、DROP 来源、断言名拆分、owner 不要求显式 ACL 行）已验证，除 §Findings F1 外不重开。

已对活体做过抽查的接缝：`v13/load.py`（`:57-60`、`:103-106`、`:109-112`、`:114-125`、`:128-139`）、`v13/plan_arm/test_plan_arm.py`（approved `:407-416`、stage43 `:448-453`、`allow()` `:508-522`、needle 句、两条 `ce_map` 负例 `:735-762`、检查顺序、`r0_source_scope` `:815-893`）、`v13/external_exec/setup_db.py:61-63`、`test_external_exec.py:466-477`、`:973-978`、`v13_agentctl.sql:4`、`:134-135`、`v13_agentctl_verbs.sql:34-35`、`:61`、`:139`、`v13_core.sql:62`、`:111`、`:210`、`:620-664`、`v13_acl.sql:121`、`:236`、`:245`、`:459`、`:475-481`、`v13_twophase.sql:33`、`:78`、矩阵 `:130`（#89）、台账 `:188`（S43-4）、父计划 E2 `:521-538`。

## Findings

### F1（应改计划）`cmap_execute_grantees_closed` 的期望集被调和改错，活体目录行为否证现措辞

- Oracle 1 原文（导出 `:496` 一带）：显式 EXECUTE grantee **仅属主与 `v13_route`**。
- 集成计划 §3.6：显式 EXECUTE 的 grantee **只有 `v13_route`**，并注「属主是隐式权限，不要求 ACL 行里有属主」。
- 否证：一旦执行 `REVOKE ... FROM PUBLIC; GRANT ... TO v13_route`，`proacl` 非 NULL，且非 NULL ACL 是从 `acldefault('f', owner)` 构造的，**属主条目（含 EXECUTE）实际存在于 `proacl`**。仓库内直接证据：`v13/acl/test_acl.py:175-183` 的 `acl_of` 用 `aclexplode(coalesce(p.proacl, acldefault('f', p.proowner)))`，`:349-352` 对已 REVOKE/GRANT 的 `v13_cancel` / `v13_complete` 断言 grantee 集合 **⊇ {"postgres", "v13_route", "v13_spawn_owner"}**——属主 "postgres" 出现在集合里，且这些函数 `proacl` 非 NULL（`v13_acl.sql:475-481`），说明属主条目来自存储的 ACL 而非默认值兜底。
- 后果：按集成计划字面写 `aclexplode` 的 EXECUTE grantee 集合等于 `{v13_route}`，对正确安装的函数必然失败；实现者会被迫临时发明「排除 proowner」口径，断言名与期望脱节。
- 精确修正：把该行期望改为「`aclexplode` 的 EXECUTE grantee 集合等于 `{current_user, v13_route}`」（等价写法：除 `proowner` 与 `v13_route` 外无 EXECUTE grantee）。安装侧合同（不 `GRANT` 给属主）不变——那半条调和是对的，错的只是断言闭集把属主排除在外。

### F2（轻微，可选）调用窗口丢失逐次归因

Oracle 1 §3.5 窗口 2 是三点快照（首次前 → 首次后 → 重复后），能把「第一次调用写、第二次不写」与「第二次才写」分开；集成计划 §3.5 收成「第一次 SELECT 之前 → 第二次 SELECT 之后」一段窗口，任何一次调用写入仍会红，但失败时不再指出是哪一次。事实没有丢（已知调和允许拆分改名），只丢归因粒度。可选修：在两次 `SELECT` 之间加一次计数，成本一行。不重写也可接受。

### F3（缺席于三份文档，提问）无网络源扫描是否应覆盖 `setup_db.py`

`cmap_test_no_network` 只扫 `test_ce_map.py`（两路基线同）。`setup_db.py` 是本 stage 新增的另一半产品门代码，同样可以打开套接字。把它纳入同一份禁令扫描成本为零（它只用 `psycopg2`，天然通过）。不阻塞施工；若采纳，在 §3.6 该行加「与 setup_db.py」即可。

## 已验证、不重开的调和与引用（抽样结论）

- 装载尾、切片与抛错：`load.py` 尾四项 `:57-60`、`"external_exec": 43` `:103-106`、`files_through` 切片 `:109-112`、`run_psql` 在 `:116-124` 抛 `RuntimeError`、`load_stage` 只遍历切片 `:129-131`——全部与计划一致，Oracle 2 的 load_stage hedge 删除正确。
- `plan_arm`：approved 五项与文案 `:407-416`、stage43 四路径 `:448-453`、`allow()` 条件与缺跟踪消息格式（`"stage N path is not tracked: " + str(sorted(missing))`，`:515-522`）、`"append stage is not tracked: " + stage`（`:397`）、重复编号先于连续编号、两者先于 approved——全部属实；两条 `ce_map` 负例在 `:735-739`、`:748-762`；`r0_source_scope` 只逐函数比 `fb295ac` 已存在的函数体并允许新增 `r0_`/`r1_` 名（`:874-893`），「只改两个函数体」成立。
- stage 43 形状：`setup_db.py:61` 是 `CREATE DATABASE`、`:63` 是 `load_stage(..., "goal_workflow")`（计划的过期行针修正正确）；测试快照后 `run_psql`（`install_compare` `:466-477`）；`finally` 里 `CREATED` 时 `DROP DATABASE ... WITH (FORCE)`（`:975-978`）。
- 被映射对象：observe `:4`（STABLE，`:134-135` REVOKE/GRANT 仅 `v13_route`）、steer `:61`、answer `:139`、enqueue 四参 `:210`（第四参 DEFAULT）、append 五参 `:62`（第五参 DEFAULT NULL）、租约两列 `:111` 无 NOT NULL、两参 cancel `:121`、一参 `:236`、六参 complete `:245`、五参委托 `:459`、requeue `:33`、renew `:78`、tools 守卫 `(uuid,jsonb)` 检查 `:639-641`——全部与计划一致。
- 矩阵 #89 在 `:130`、台账 S43-4 在 `:188`；父计划 E2 `:521-538` 的映射格、两链分开、`shutdown` 字面量均被忠实收录。

### 其余两路基线内容的落点（无丢失）

Oracle 1 的 `cmap_body_literal_only` → `cmap_prosrc_one_select`；`cmap_function_*` 系列 → 集成计划同义名；断言名拆分（shutdown typeof/值、cancel/complete 的 exists/unmapped、零写十行、repeat）事实保留。Oracle 1 的「sidecar/缓存」拒绝由集成 §1 非目标与 §3.9「不写控制文件、projection、receipt、水位」覆盖。声称句取 Oracle 2 版本属选型而非丢事实。`v13_spawn_writer_ok` 的 `proconfig` 比较写法（`agentctl_verbs.sql:34-35`）引用正确。

## Recommendations

1. 按 F1 修 `cmap_execute_grantees_closed` 一行期望（闭集含属主，或显式排除 `proowner`）。这是唯一必须改的。
2. F2 可选；F3 是待答问题，默认维持现状也能施工。
3. 其余内容按现计划施工即可，未发现第二处被代码否证的陈述。
