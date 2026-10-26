# Cordis v2 DP2

DP2定向扩展已完成的 Cordis DP1 协议内核，交付声明式安装、scope 创建后果、最小依赖解析、成功的 P0–P4 激活和无活义务的基本 dispose。产品行为由 `docs/designs/cordis-plugin-system-2026-10-25.md` 规定；本 README 记录实现状态与真实 gate 结果。DP1 的历史验收保留在 `v24/cordis/dp1/README.md` 与 `docs/reviews/cordis-v2-dp1-*`，不被本阶段重写。计划见 `docs/plans/v24-cordis-dp2-lifecycle-plan-2026-10-26.md`。

## 当前状态

**B0 已结项：本地验证 + 提交 + 推送 `origin/v24`（B0 关闭提交（subject：`v24: close out Cordis DP2 B0 baseline with gate and frozen evidence`））。W1 已实现、五项 bounded Oracle review 发现全部修复、最终 18 条 gate 全绿；W2–W4 尚未实现、blocked pending 用户对 SQL layout/cap 的裁决，W2–W5 均未运行。不得从 B0/W1 绿色推断 W2–W5 的安装、解析、完整 P0–P4 或 dispose 行为。**

- B0 只做证据与环境核验：固定 worktree/分支/HEAD/upstream、串行实跑既有五条 Cordis DP1 命令、十一条 v24 命令与单列 s9、复核十二个冻结 SQL SHA-256 与冻结 diff，并更新本 README、matrix、ledger 与计划的 B0 证据。
- B0 未修改任何生产实现、未修改冻结目录（`v24/load.py`、`v24/sql/**`、`v24/s1`–`v24/s12`）、未新增 SQL 文件或 helper，也未触碰 `v24/cordis/sql/**`。
- W1 已实现 reserved successor identity、ready child 执行/重放、P0→P1 generation 复验、command closure、typed delta 与真实 applier、terminal receipt guard；生产 spec-valid lifecycle 解释器仍抛 `0A000`，由 disposable probe 驱动 CDP2-K。`test_support.py` 与 CDP2-K 已存在；W2 的 spec-valid active-owner maintenance fixture、CDP2-I/A/B 尚不存在。
- W1 的 `40_advance.sql` 为 1196/1200 物理行（余 4 行）；DDL 前缀 `10`–`17`/`20`/`30` 为 360/900（`30_triggers.sql` 194 行）。冻结的 `v24/load.py`、`v24/sql/**`、`v24/s1`–`v24/s12` 未改。
- 发布授权（2026-10-26 用户给出）：本计划逐里程碑 commit 并 push `origin/v24`；这是任务特定授权，不改写根与 worktree `AGENTS.md` 的 `origin main` 规则。B0 已据此提交并推送，里程碑结项；W1–W5 沿用同一目标。

## Commands

既有命令（B0 已实跑，退出码见 matrix）：

```bash
uv run python v24/cordis/load.py
uv run python v24/cordis/dp1/setup_db.py --self-check
uv run python v24/cordis/dp1/test_environment.py
uv run python v24/cordis/dp1/test_ddl.py
uv run python v24/cordis/dp1/test_kernel.py
```

v24 回归（十一条，B0 已实跑）：

```bash
uv run python v24/load.py
uv run python v24/s1/setup_db.py --self-check
uv run python v24/s1/test_ddl.py
uv run python v24/s1/test_g1.py
uv run python v24/s2/test_g3a.py
uv run python v24/s3/test_g2.py
uv run python v24/s4/test_g2b.py
uv run python v24/s5/test_g4.py
uv run python v24/s6/test_g5.py
uv run python v24/s8/test_g7.py
uv run python v24/s7/test_g6.py
```

单列扩展命令，不计入十一条（B0 已实跑）：

```bash
uv run python v24/s9/test_g8.py
```

DP2 自有 gate（W1 已存在并实跑退出码 0；W2–W4 尚不存在）：

```bash
uv run python v24/cordis/dp2/test_kernel.py      # CDP2-K，W1 — 已通过
uv run python v24/cordis/dp2/test_install.py     # CDP2-I，W2 — 未创建
uv run python v24/cordis/dp2/test_activation.py  # CDP2-A，W3 — 未创建
uv run python v24/cordis/dp2/test_boundaries.py  # CDP2-B，W4 — 未创建
```

## B0 基线证据（2026-10-26）

- worktree `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`，分支 `v24`，HEAD `0590d4703ea1404febbc82d6114fd8d91f385902`（`v24: close out Cordis DP1 with final regression evidence`），upstream `origin/v24`，`origin/v24...v24` = `0 0`。
- DP1 交付提交依次为 `5163b23`（loader/fixture）、`e9ccf30`（DDL）、`69efd38`（kernel/ACL）、`0590d47`（closeout）；`57e2c1e` 是冻结 v24 的比较基线，不是 DP2 预期 HEAD。
- 工作区无已修改/已暂存的跟踪文件；B0 前已有 24 个未跟踪文件且全部位于 `docs/` 下，属用户输入，B0 未暂存、未改写。
- 环境：Python 3.12.11、psycopg2 2.9.12（dt dec pq3 ext lo64）、PostgreSQL 18.4（180004），仅 Unix socket。
- 预算：`v24/cordis/load.py` 仍是十五文件 canonical manifest；`v24/cordis/sql/40_advance.sql` 340 物理行（≤1200）；DDL 前缀 `10`–`17`/`20`/`30` 合计 350 物理行（≤900）。
- 冻结证据：十二个 `v24/sql/*.sql` SHA-256 与 DP1 P0 记录逐一相同；`git diff 57e2c1e -- v24/load.py v24/sql v24/s1..s12` 为空（exit 0）。
- 结项：B0 只按路径暂存四个 DP2 工件（本 README、DP2 conformance matrix、DP2 deviation ledger、DP2 plan），未 `git add -A`、未卷入 24 个未跟踪用户文档；该B0 关闭提交（subject：`v24: close out Cordis DP2 B0 baseline with gate and frozen evidence`）已推送 `origin/v24`（非 force、未跳过 hook）。

## W1 证据（2026-10-26，本地）

- 范围：reserved successor identity、ready child 执行与持久 replay、P0→P1 generation 复验、command closure 接线、九种 typed delta 的闭合结构/上下文校验与真实 applier、terminal effect/receipt guard、CDP2-K。
- 变更：`v24/cordis/sql/40_advance.sql`（340→1196 物理行）、`v24/cordis/sql/30_triggers.sql`（+10 行）、DP1 的 `test_ddl.py`/`test_kernel.py` 预期、新 `v24/cordis/dp2/test_support.py` 与`test_kernel.py`。未改 `v24/load.py`、`v24/sql/**`、`v24/s1`–`v24/s12`，十五文件 manifest 不变。
- 实跑：`uv run python v24/cordis/dp1/test_ddl.py` 退出 0（113 个零写 DDL probe；terminal attempt/fence 的 +1/-1 均为 `55000`）；`uv run python v24/cordis/dp1/test_kernel.py` 退出 0（66 个 committed zero-write assertions）；`uv run python v24/cordis/dp2/test_kernel.py` 退出 0，打印 K1–K8 与 K4b 的具名断言。最终 18 条命令在同一轮串行复跑，逐条 `EXIT 0`（完整 18 行状态见 matrix「Actual W1 exit codes」）。
- Intermediate failure（诚实记录）：第一轮 post-review 全量复跑在 `[5] uv run python v24/cordis/dp1/test_kernel.py` 返回 `EXIT 1`，`test_kernel.py:428` 报 `KeyError: 'disposition'`；根因是 strict event validator 拒绝了 DP1 probe 的 synthetic `receipt` event。保留 `receipt` 的 object-only 形状后，CDP1-K 与最终 18 条均恢复 0；失败轮不作为通过证据。
- CDP2-K 证明的是真实 `advance`/`validate_delta`/`validate_domain`/`validate_and_apply_delta`；install/reconcile/dispose 的 *生产* 解释器仍是 `0A000`，probe 只替换解释器并位于一次性 DB。K2/K5/K6/K7 用 owner snapshot 证明 replay 与失败路径不新增行。
- Wire v1：`command_dispose` command payload 严格 `{install_id}`（`fiber_ids` 仅内部 `basic_dispose` delta，由 DB 派生）；root scope 严格 `{mode,id,realm_overrides}`，existing `{mode,id}`，仅 child 有 `parent_id`。`test_kernel.py` 在 fixture import 前显式插入 `Path(__file__).resolve().parents[1] / 'dp1'`，K2 的 event cursor 是带断言的 `[0,1,2,3]`；K2 还覆盖 child 非 NULL `episode_id` 的 closed / 不再 current 负例（`effect_id_conflict`/`continuation_binding`，零写）。
- 预算：1196/1200，仅余 4 行；W2–W4 的共享新增无法可靠塞入 4 行，**blocked pending 用户对 SQL layout/cap 的裁决**（未移动 helper 到预算外，也未把代码藏进 JSON）。
- Full bounded Oracle review：**已完成**，五项 actionable findings（P1.1 event null/type、P1.2 successor prevalidation、P1.3 dispose closure 513、P1.4 dispose timestamp preservation、P2 cross-fiber event/successor/p1_context）均已修复并有 CDP2-K/CDP1 证据。早期 focused chat 另确认 parent-fiber predicate 与 terminal guard 的 ready→succeeded/terminal 拒绝，并指出 attempt/fence 顺序问题（已修复）；full-file review 请求曾在 `codex_custom_gpt-6-astra-xhigh` 上超时，该 timeout 不被冒充为完整 full-file review，但不否定 bounded review 已完成。
- Bounded review 的五项修复：六种 event 的嵌套类型/null 由 `event_payload_valid` 校验（分支用 `IS DISTINCT FROM`，DP1 `receipt` 保留 object-only）；lifecycle successor 在 DML 前要求 command_reconcile/ordinal 0/精确 input；closure 结果 `LIMIT 513` 并在 append 后检查；dispose 只补未 tombstone fiber 的时间戳，保留已有 `dispose_requested_at/disposed_at`；P2 cross-fiber 负例补合法 event/successor 并断言 `p1_context`。
- W1 边界：生产 install/resolver（W2）、完整 P0–P4（W3）、生产 dispose（W4）仍未实现，且 W2–W4 blocked pending 用户对 SQL layout/cap 的裁决；`effects_one_reconcile` 仍限制每个 fiber 同时一个 ready/claimed reconcile，CDP2-K 的 16 个 successor 结构上限主要覆盖其他 kind。continuation 仍要求与创建者同一 LOGIN（child ID/request principal 由 `session_user` 派生），这是 DP2 的部署假设，不是跨 LOGIN 身份分离。P1/P2 unsupported 失败后 child 保持 `ready` 且无 request，K7 证明同一 child 可重试一次且 replay 不重复写。

## 边界

DP2 不实现：target drift 处理、失败记录与自动 retry；closing/divert/error、leave/unload、withdraw/release、inverse 执行；完整 live 失效传播、drain/barrier、公平扫描与恢复；run/reducer/model/tool/dispatch/listener 执行；`intercept`、overlay 合并与外部制品准备。这些路径保留 `0A000` 或现有 DP1 行为，不提前实现 DP3。
