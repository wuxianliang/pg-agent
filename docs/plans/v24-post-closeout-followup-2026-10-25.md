# v24 收尾后续：开发与发布计划

## Goal

在 `996cb5b` 的已交付基础上，完成 H13 页容量口径、模型选择、真实 provider 证据和分支发布的收尾，并将第二批语言、公平性、跨主机租约、provider 性能与质量明确移交后续独立计划。采用**局部修正与证据补齐**：修复真实 smoke 的结果发现缺陷，复用现有 host、journal 和只读接口；保持九个冻结内核 SQL 与 `996cb5b` 字节一致，正式 closeout 始终为 **11/11**，G8/G9/G10 始终为 extension checks。

**文档归属**：唯一正式计划为主检出的 [`docs/plans/v24-post-closeout-followup-2026-10-25.md`](/Users/wxl/Projects/pg-agent/docs/plans/v24-post-closeout-followup-2026-10-25.md)。v24 worktree 中的同主题未跟踪草稿仅作参考，不作为第二份规范；实施前须将本计划有意带入隔离发布/集成 worktree，不能覆盖主检出工作区。

本次交付仅为计划文档与评审工件；未改实现、未重跑运行时 gate、未访问 provider、未提交或发布。2026-10-25 已用只读命令复核本地 worktree HEAD 和缓存远端引用的 `0 30` 关系；未 fetch，不能据此声称远端实时状态。下文绿色结果来自既有执行记录，实施时必须重新运行。计划文档须在 P0 前按相同仓库相对路径加入 v24 源 worktree 并逐里程碑更新；先检查目标不存在或已是同一计划，不覆盖既有未跟踪草稿。

## Done when

1. **决策已确定**：D1–D7 及跨主机、性能/质量范围均记录 Oracle 裁决、依据、置信度、assumption 与推翻条件；裁决不构成 provider 调用或 main 发布授权。
2. **H13 口径统一**：
   - 七个分页函数继续默认并最多返回 64 项。
   - 所有当前说明均明确：`67,107,712 B` 是指定夹具的实测序列化尺寸，**不是响应字节上限或内存上限**。
   - G8 无参数全量运行 exit 0。
3. **smoke 可正确验收终态**：
   - 使用 `start` 返回的 run id 和历史读取面核验结果。
   - ScriptTransport 覆盖完整 smoke 成功路径，证明模型结算后退出工作列表仍能正确验收。
   - 摘要验证发生在输出之前；删除启动前的失败保留完整 journal，部分删除失败尽力保留剩余证据；成功清理 journal。
   - G9 无参数全量运行 exit 0。
4. **真实 provider 状态如实记录**：matrix、ledger、s10 README 使用同一份记录，明确为通过、失败或未运行。每个未验证记录包含日期、命令或拟执行命令、未运行原因及实际退出码；未执行的命令不编造退出码。
5. **模型合同明确**：继续固定 `deepseek-flash`；不新增 `--model`、构造参数或运行时 allowlist，不修改 `v15/**`。
6. **发布就绪**：最终 `v24` 源码通过冻结 11 条 closeout 和 G8/G9/G10；发布清单准确披露随分支进入的 `v99/core` Phase 0。
7. **发布完成的判据**：获得明确发布授权后，采用一次 `--no-ff --no-commit` 合并；合并候选树验证通过，合并提交及发布记录提交正常推送至 `origin/main`。没有授权时状态为“发布就绪、未发布”，不得写“发布完成”。
8. **历史与未来范围分离**：保留历史 11/11、G8 23/23、G9 11/11、G10 8/8 及 Node 证据；D-S7-2 保持开启，其他延后能力不被任何绿色结果隐含覆盖。

## Execution index

大小：S 为局部文档、验证或小修正；M 为跨组件回归或发布操作。本轮没有 L/XL 实现。

| # | 工作项 | Goal | Done-when | Key files | Deps | Size |
|---|---|---|---|---|---|---|
| P0 | 基线与来源核验，准备检查点 | 固定源码、政策、分支与历史证据 | 基线清单及 11 条 closeout、3 条 extension 的新运行记录完整 | 本计划、已有 matrix/ledger、`AGENTS.md` | 无 | S |
| M-H | H13 处置 | 冻结 64 项合同并纠正容量表述 | G8 全量 exit 0；说明不再称 64 MiB 为上界 | `s9/test_g8.py` 注释、s9 README、前计划、matrix/ledger | P0 | S |
| M-M | 模型选择处置 | 固定 flash，关闭本轮模型扩展问题 | 文档与现有 adapter 一致；G9 exit 0 | s10 README、前计划、matrix/ledger | P0 | S |
| M-S | smoke 局部修正与离线证明 | 修复结算后找不到 model 的缺陷 | 新 smoke 子场景通过；G9 全量 exit 0 | `host/smoke.py`、`s10/test_g9.py`、s10 README、matrix/ledger | P0 | M |
| M-E | opt-in provider 证据登记 | 执行一次获授权调用，或明确未验证 | 三处证据一致；退出码及未运行原因准确 | s10 README、matrix/ledger、本计划 | M-S；真实调用另需授权与凭据 | S |
| M-F | 后续范围登记 | 分开记录四项后续计划 | 触发条件与证明边界完整；D-S7-2 保持开启 | s10/s11 README、ledger、本计划 | P0 | S |
| M-P | 分支发布 | 将已验证源码及 v99 Phase 0 发布至 main | 合并候选验证通过；双亲 merge 已推送 | 隔离发布 worktree、发布记录、matrix/ledger | M-H/M-M/M-S/M-E/M-F；发布授权 | M |
| M-A | 发布审计记录 | 补齐已生成的 merge SHA 与远端确认 | 发布记录已提交、推送，执行树未改变 | `docs/reviews/v24-release-2026-10-25.md`、本计划 | M-P | S |

P0 是准备检查点，不创建空提交；其结果随第一个完成的里程碑提交。P0 前先将本计划有意加入 v24 源 worktree 的相同相对路径，保留主检出原件且不覆盖任何既有文件；它是 M-H 首个源提交的一部分。其余里程碑各自提交并立即推送，不积压多个里程碑。

## Background — Current-state analysis

### 1. 两个检出与证据来源

| 项 | 所附材料中的状态 |
|---|---|
| 主检出 | `/Users/wxl/Projects/pg-agent`，`main @ ab34d69`，跟踪 `origin/main` |
| 主检出 HEAD | 不含 `v24/`、`v99/`；用户工作区存在未提交及未跟踪内容 |
| v24 worktree | `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99` |
| v24 分支 | `v24 @ 996cb5b`，跟踪 `origin/v24`；已跟踪文件干净，另有 21 份未跟踪文档 |
| 分支关系 | merge-base 为 `ab34d69`；`main...v24` 为 `0 30` |
| v99 关系 | `v99` 是 `v24` 祖先；`bddeb81` 为 `v99/core` Phase 0 |
| 发布惯例 | 零 tag；书面先例采用 `--no-ff --no-commit` |

本次计划阶段用只读命令重新核对了本地 HEAD 与缓存远端引用的 `0 30` 关系；未 fetch，因此该值不是实时远端状态。其余细节是提供材料中的基线，P0 必须复核；不得以缓存的 `0 30` 推断 fetch 后仍无冲突。

主检出存在用户工作，发布使用独立 worktree，避免切换、清理或覆盖主检出。发布完成以 `origin/main` 为准；不强行移动仍有用户修改的本地 `main` 检出。

借用 fixture 时的请求键约束依据 `v24/sql/10_schema.sql:248-259`：requests 以 `(principal_id, request_key)` 为主键并保留 response，重复调用可能 replay 已存响应。

本次计划阶段对文件/命令的复核依据包括 `v24/host/smoke.py` 的 `_live()` / `_first_model()`（dispatch 后按 active effect 查询）、`v24/sql/49_host_reads.sql:183-186`（`host_effects` 的 `ready/claimed` 过滤）、`v24/host/journal.py:254-270`（`records_for`、`last`），以及 `v24/s10/test_g9.py:69-70,87-151,287-299,425-458`（11 顶层 ID、网络 deny、start handles 与 ScriptTransport 成功路径）。H13 依据 `v24/s9/test_g8.py:885-922`、`v24/sql/49_host_reads.sql`、`v24/host/db.py`、`v24/host/worker.py` 的分页与请求处理路径。行号以本次读取到的 v24 worktree 为准，P0 复核提交后漂移。

### 2. 已完成的证据

| 层 | 历史结果 | 证明边界 |
|---|---|---|
| 正式 closeout | **11/11，exit 0** | 冻结命令、顺序与计数 |
| G6 | 30/30 ID | 安全性与线性化；不证明公平性 |
| G8 | **23/23，exit 0** | host 只读面、闭包、租约和恢复边界 |
| G9 | **11/11，exit 0** | ScriptTransport；没有真实 provider 网络 |
| G10 | **8/8，exit 0** | Python 本地子进程生命周期 |
| Node 独立生命周期 | exit 0，Node `v24.13.1` | 独立 Node 证据 |
| 同 run multilingual smoke | exit 0 | Python → Node → Node 工具错误 → final；两个 install disposed、scope closed |
| 错误码 | **24 个有生产者，0 个未产生** | 不新增错误码 |
| 真实 provider | **未验证** | 历史无 key 路径只有 `credentials_absent`/2 |

G8 的历史测量：

- 闭包基线 `B=C(0)=3`。
- `H=0,1,2,4,8,16,32` 对应 `C=3,4,5,7,11,19,35`。
- `H=509 → C=512` 可 claim；`H=510 → C=513` 返回 `retry_with_closure`，十表零写。
- H13：64 项、每项 ASCII `input` 长度约 1 MiB，序列化结果 **67,107,712 B，显示为 64.00 MiB**。

D-S6-12、D-S8-7 已关闭；D-S7-2 仍开启。deadline 非硬上界、host 信任和 unknown 屏障等披露仍然有效。

### 3. H13 的控制流与容量边界

`HostDB` 的七个分页包装默认 `limit=64`，调用 `49_host_reads.sql` 对应函数。SQL 将 limit 截到 `[0,64]`，取 `limit+1` 项判断 `has_more`，返回：

```text
{v, items, limit, has_more, next_cursor}
```

公开读取为 `STABLE SECURITY DEFINER`，使用固定 `search_path` 和 scope-owner-or-admin 授权；不取 G、不写表。分页跨调用没有共同快照；worker 依靠重新扫描、id 去重及 claim 资格复核处理重复或扫描期间变化。

容量结论必须区分：

- `64` 是**项数上限**。
- `effects.request` 没有所述大小 CHECK。
- `advance` 的 1 MiB 校验针对 outcome body，不能当作 request 列的全局约束。
- worker 的若干读取路径会累积整轮结果；降低单页项数能降低单页聚合负担，但不限制整轮内存。

仅修改既有函数的页上限不会增加 SQL 文件，也不会改变函数签名或权限集合，因此**不会自行触发 loader 未注册文件错误**。四处 SQL/ACL/loader/G1 原子注册要求适用于此前新增读面，不应错误套用到字面量调整。本轮裁决保持 64，以上文件均无须修改。

### 4. provider 调用链及发现的新阻塞

现有调用链：

```text
smoke.main
  → flag/key 检查
  → _live
  → setup_db + _bootstrap
  → HostDB + DeepSeekAdapter + HostJournal + HostWorker
  → claim / COMMIT
  → 事务外 HTTP
  → durable result
  → settlement / COMMIT
  → smoke 核验与输出
```

PostgreSQL 仍拥有 effect/run 资格和状态；journal 保存执行边界与完整历史。host 同步、单线程执行，最多一个在飞 effect，不在执行中 sweep。此次不改变这些职责。

**所附 `smoke.py` 存在确定的结果发现缺陷**：

1. `_live()` 先执行 `worker.run_until_idle()`。
2. 随后 `_first_model()` 调用 `host_effects(scope)`。
3. 该 SQL 函数只返回 `ready/claimed`。
4. 成功结算的 model 为终态，已经不在该列表。
5. `_first_model()` 因此返回 `None`，`_run_of()` 也返回 `None`，已完成 run 仍会被判失败。

因此不能照旧草稿直接执行 live smoke并将失败归因于 provider。必须先补 M-S；已有 G9 绿色不能证明这个未覆盖的完整入口成功路径。

另一个相关问题：`_assert_no_leak()` 当前发生在成功摘要打印之后，并且检查对象是 reply，不是最终输出。摘要构建与检查必须调整到输出前。

### 5. 模型与插件扩展点

`DeepSeekAdapter` 固定：

- `MODEL="deepseek-flash"`；
- `ENDPOINT="https://api.deepseek.com/chat/completions"`；
- `stream:false`；
- `0 < timeout_s ≤ 239`；
- 复用 v15 的 transport、错误类和 pricing，不复用 `DeepSeekProvider.complete()`。

v24 **没有运行时 allowlist**。引入 v4-pro 需要新增模型配置、验证及计价合同，不属于简单扩充 v15 集合。

`ApprovedAdapter` 是启动时创建的不可变配置；registry 按 install 的五字段身份/digest 匹配，再检查冻结 pin descriptor 和 artifact。当前 `artifact_path` 固定取 `argv[1]`，适合解释器加脚本。直接执行 Go/Swift 编译产物需要重新定义 artifact 与 executable 的关系。固定、无 shell 的 wrapper 并非天然违规，但也需要明确批准与摘要语义，不能当作“加一条 registry entry”处理。DuckDB 路径应单独评估，不自动继承编译型语言的限制。

## Design — Recorded rulings

以下为 2026-10-25 Oracle 对明确决策 slate 作出的正式裁决。D1–D7 与补充范围均选择 A；表内 assumption 是范围/发布策略假设，不代表用户授权真实调用或发布。

| # | 选定方案 | 一句话依据 | 置信度 | 推翻条件 |
|---|---|---|---|---|
| D1：H13 | **A：保持 64 项**；`67,107,712 B` 仅为夹具测量。Assumption：当前部署暂无新容量合同 | 无 RSS、响应预算或代表负载证据支持改值；降低页数也不约束整轮累积 | 高：代码边界；中：运营适配性 | 明确部署预算与代表负载证明当前合同不适用，应重设容量约束，而非机械改页数 |
| D2：真实 provider | **A：opt-in、非发布硬门禁**，可如实登记 `not_run`。Assumption：发布以确定性验收为必需条件 | 历史手工验收可选；有 key 不等于授权，gate 不开真实 socket | 高：政策边界；中高：发布策略 | 发布负责人明确要求特定 live 成功作为发布条件，并提供授权和范围 |
| D3：模型 | **A：保持固定 `deepseek-flash`**。Assumption：本轮不扩大支持模型范围 | 无 v24 模型选择接口；扩展会新增配置、响应验证、计价和支持合同，不引用未经重查的外部型号事实 | 高 | 独立计划明确型号、配置入口、价格处理、拒绝行为与验证标准 |
| D4：发布 | **A：一次 `--no-ff --no-commit` 合并 v24，不打 tag**。Assumption：沿用保留版本 merge 节点的发布策略 | v99 已是 v24 祖先；v15 发布先例采用非快进集成分支流程，可保留拓扑和审查候选树 | 高：拓扑/先例；中高：策略选择 | 明确要求 v99 与 v24 独立发布，或 fetch 后拓扑改变方案适用性 |
| D5：第二批语言 | **A：独立登记，本轮不实施、不建占位计划**。Assumption：维持已交付 Python/Node 范围 | 现有 artifact/argv 合同不能直接代表 Go/Swift 编译产物；DuckDB 需单独定义执行方式 | 高 | 明确授权语言扩展并批准 artifact、执行和工具链合同 |
| D6：公平性 | **A：D-S7-2 保持开启并独立登记**。Assumption：本轮不扩展活性保证 | 安全性和线性化证据不能推出 starvation-free，也不足以永久宣布为非目标 | 高 | 明确负载假设、调度策略、等待目标和可复核活性证据 |
| D7：smoke 修复 | **A：先完成离线局部修复，作为发布前必要条件** | 已确认工作列表只返回 ready/claimed，结算成功的 model 会消失；已有 run 历史读取面足够修复 | 高：根因；实现覆盖仍由 G9 验证 | 调用链已被别的提交修复，或新证据显示局部方案无法覆盖 host 缺陷 |

补充范围裁决：跨主机租约独立登记、不实施（assumption：本轮不承担多主机保证）；provider 延迟/质量独立实验、不实施（assumption：本轮不开展测量）。前者被分区、接管和重复副作用合同推翻，后者被明确样本、指标、预算与实验法推翻。

补充执行决定：

- **smoke 修正为发布前必要工作**；真实调用仍然可选。M-P 对 M-E 的依赖是证据状态已登记，而非 live 成功；已启动的 live 失败必须如实保留，并按失败归因规则判断是否阻断发布。
- **跨主机租约、provider 延迟/质量分别立项**，不与公平性或语言扩展合并。
- **M-P 在 merge 中创建发布记录，M-A 以单独文档提交补齐真实 merge SHA/parents 并推送 main**；不新增计划索引文件，本计划和阶段 README 提供链接。
- 本轮不做数据库 schema、journal 格式、host 调度器或 registry ABI 迁移。

## Baseline corrections and coverage notes

本节记录相对原始 context_builder 生成计划响应的有意修正，以及已保留的前期纠错。原始导出在完整性检查后清理，本计划是持久规范。

- 基线要求历史 effect 顶层 `cause="start"`，但 reader 不暴露该字段。Oracle 改为保存 `start` 已提交返回的 `run_id/model_id`，严格核对 scope/run/effect 身份、终态 final 和绑定 journal reply，保留原验收目的。没有额外要求 `close_reason` 或非空 final 文本。
- 基线已删除 `_run_of`，将 `_first_model` 改成 run 历史查询。本计划进一步简化：删除两者，使用已知 model handle 加 `_verify_completion`；不改变外部 `_live`/`main` 签名，仍覆盖缺失/重复/分页异常。补充 journal mapping 与 settlement final/usage 的逐项一致性检查，不依赖 `stats.last_reply`。
- 基线先打印成功再关闭/删除目录；本计划按 Oracle 裁决改为核验、泄漏检查、关闭资源、确认清理后才输出成功。`ignore_errors=True` 是当前代码的缺陷，不是基线要求；本计划明确拒绝掩盖清理错误。
- 基线已经正确指出“v24 无 runtime allowlist”和“改既有 cap 不触发新增 SQL 注册”；本计划原样保留这两项对前期误解的纠正。
- 基线把 v99 Phase 0 命令列为待确定；P0 已核对具体命令，仍要求发布候选重新执行并记录结果，不把 W1–W4 写成完成。
- 补充 G9 借用既有 fixture 的具体接缝，避免完整 smoke 测试嵌套 DROP/CREATE；M-P 创建候选发布记录，M-A 独立补真实 merge 身份，避免自引用 SHA。
- 设计评审补强了 journal 与已知 run/outcome 的绑定、借用 fixture 的非拥有语义、可观察且唯一的临时目录、取消后 late success 负例、KeyboardInterrupt 行为、M-E 双记录组、最新远端基点及 merge/audit tree 与 ancestry 核验；这些均补入 M-S/M-E/M-P/M-A 与验证命令。评审确认的冲突是结果保留承诺：递归删除一旦部分完成不可回滚。本计划据 Oracle 2026-10-25 裁决，将完整保留保证限定在删除启动前；启动后尽力保留剩余证据并报告可用路径。该选择是保守范围假设，若要求部分删除后仍保留完整 journal，需另行设计完整副本机制。

以上修正保留基线的目标、依赖、失败行为和验证覆盖；若新证据推翻前提，按对应裁决的推翻条件重开决策。

2026-10-25 完成 Phase 7.5 保真核对：逐项覆盖原始生成响应的 Goal/Done-when、执行索引、五组当前状态、裁决与范围、P0/M-H/M-M/M-S/M-E/M-F/M-P/M-A、逐文件影响、风险/回滚、边缘情况、七组验证命令、执行顺序和引用。支持的内容均保留；具体修订及其证据见本节与设计评审。此核对仅证明计划完整性，不构成 runtime gate 或 live 验证结果。原始导出在本核对后清理。

## Work items

### P0 — 固定基线与待验证事实

**Goal**：建立可追溯的新执行起点。

**Approach**

1. 核对两个 worktree 的 HEAD、远端关系与 tracked/untracked 状态；不移动、不暂存无关文件。
2. 记录 `996cb5b`、fetch 后的 `origin/main`、P0 时的当前 v24 HEAD、固定历史 `bddeb81` 的完整 SHA；不要求 P0 预先知道未来的最终发布源提交。M-P 在 M-F 完成后固定并记录最终 v24 源提交完整 SHA。
3. 保存九个冻结 SQL 的逐文件摘要；后续比较必须显式以 `996cb5b` 为基准，不能只检查工作区是否干净。
4. 实跑 11 条 closeout，再跑 G8/G9/G10；保存命令、运行日期与时区、源码 SHA、退出码及结果行。
5. 复核届时实际适用的 `AGENTS.md` 是否相对本次已读版本漂移。当前主检出仅列两个入口，v24 worktree 文件在 :76 列第三入口；明确用户指令优先，worktree 文档不得覆盖它。任何调用前都按当时有效授权和政策判断。
6. 复核已定位的 `worker.py`、`journal.py`、`test_g9.py` 接口是否相对计划读取版本漂移，复用下文给出的 journal 查询、fixture 借用及网络守卫接缝实施 M-S。
7. 核对 v99 Phase 0 正式命令：`uv run python v99/core/setup_db.py --self-check`、`uv run python v99/core/test_core.py`，来源为 `docs/plans/v99-core-phase0-2026-10-20.md:1002` 和 `:1255`，matrix 开头也指向最终双命令通过记录。发布时重新串行执行。

**Done-when**：上述记录完整；基线失败已归因。未解决的确定性失败阻断后续交付。

**Key files**：本计划、已有验证工件、实际 worktree `AGENTS.md`。
**Deps**：无。**Size**：S。

### M-H — H13 处置与证据措辞

**Goal**：保持现有分页合同，消除“测量值就是上界”的误读。

**Approach**

- `49_host_reads.sql`、`HostDB`、worker 的默认值与调用值全部保持不变。
- `g8_h13()` 的夹具、64 项断言、`>60 MiB` 断言及 lease=1 claim/settle 断言保持不变。
- 将该测试的“worst-case”标题改为“64-item large-input fixture”；不改行为或用例编号。
- 说明当前 ASCII 夹具的紧凑 JSON 字符长度等于该表示的 UTF-8 字节长度；这不是 PostgreSQL wire size、压缩率或进程 RSS 测量。
- 前计划中的条件决策标为“已由本计划 D1 收口”；历史实测值保留。
- 修正 s9 README 中的 “512-page-cap” 表述：512 是 closure 实体边界，分页上限为 64 项。
- ledger 增加具名披露 `D-PF-1`：request 无已定义的全局字节限额、H13 为夹具测量、worker 整轮累积不受页数限制。

**Done-when**：11 条 closeout 与 G8 全量 exit 0；代码行为不变；当前文档中不存在未决页上限或 64 MiB 硬上界声明。

**Key files**：`v24/s9/test_g8.py`、s9 README、前计划、matrix、ledger、本计划。
**Deps**：P0。**Size**：S。

### M-M — 固定模型选择合同

**Goal**：关闭本轮“v4-pro 是否加入 allowlist”的问题。

**Approach**

- 保留 `DeepSeekAdapter` 的现有构造签名与 `MODEL` 常量。
- 不新增模型参数、环境变量解释、CLI 选项或 allowlist。
- s10 README 明确“v24 固定模型，不消费 v15 allowlist”；前计划开放问题标为 D3 已决定。
- 外部型号、弃用及定价描述保留核查日期，不能当作 2026-10-25 新核验事实。
- 不给已经明确固定模型的 adapter 添加重复注释；`deepseek.py` 无须修改。

**Done-when**：11 条 closeout 与 G9 全量 exit 0；`deepseek.py`、`v15/**` 无 diff；文档不存在本轮参数化的待选分支。

**Key files**：s10 README、前计划、matrix、ledger、本计划。
**Deps**：P0。**Size**：S。

### M-S — 修复 smoke 终态核验并补离线回归

**Goal**：使完整 smoke 能准确区分真实成功、未完成和失败。

#### 接口与状态归属

仅修改 `smoke.py` 内部函数：

| 接口 | Before | After |
|---|---|---|
| `_bootstrap` | 返回 scope id | 返回 `(scope_id, run_id, model_id)`；run/model id 分别来自已提交 `start` 的 `emitted[0]` / `[1]` |
| `_verify_completion` | 不存在；由当前工作列表推断完成 | 新的私有核验函数按 `(db, journal, scope_id, run_id, model_id)` 检查历史 reader、终态、usage 和 journal，返回摘要与 reply |
| `_first_model` | `(db, scope)`，查当前工作列表，可返回 `None` | 删除；不再从 ready/claimed 列表猜测已结算 model |
| `_run_of` | 通过 effect 反查 run | 删除；使用 `start` 返回的权威 run/model handle |
| `main`、`_flagged`、`_live` | 现有签名 | 保持不变 |
| `_assert_no_leak` | 输出后检查 reply | 输出前检查 reply 及待输出摘要 |

更新调用点全部位于 `smoke.py:_live()`；`test_g9.py` 中若有直接调用这些私有 helper，同步调整。没有对外 Python API、SQL API 或持久格式变更。

#### 精确执行流程

1. 保留 flag/key 短路顺序。无 flag 或无 key 时不创建 adapter、数据库或 journal。
2. `_bootstrap()` 校验 create-root 与 start 的成功信封、emitted 数量（分别为 1 和 2）和 scope/run/model UUID；从两次已提交响应提取三者，返回前完成提交，失败不进入 dispatch。每次 invocation 使用唯一 request key；PID 不足以区分同进程共享 fixture 的重复 smoke 子场景。`requests` 以 `(principal_id, request_key)` 为主键并重放已存 response，故碰撞会假通过而不创建新 run。
3. worker 仍按现有同步方式运行，保持 claim commit → IO → journal → settle commit。保留现有 budget（steps=3、tool_calls=0、tokens=5000、wall_ms=60000）、`max_output_tokens=32`、固定提示、`timeout_s=120`、`max_rounds=8`；超 reserve 导致的 unknown 必须验收失败，timeout 不变成硬期限。
4. 验收使用已知 run id：
   - 从 `host_runs(scope_id)` 取得合法信封，要求恰有本次 run、`has_more=false`、`next_cursor=null`、`status="completed"`。
   - 从 `host_run_effects(run_id)` 取得合法信封，要求恰有一项、`has_more=false`、`next_cursor=null`；该项必须为 `model_call`，scope/run/effect id 分别匹配已知 handle，因此不存在 tool effect、重复 model 或被忽略的历史页。读接口不暴露顶层 `cause`，不得增加对不存在字段的校验。两种 reader 都要求 `v=1`、无 error、字段及类型正确；错误信封、缺字段或类型错误不得用默认空集合掩盖。
   - 要求 model `status="succeeded"`、`outcome.class="success"`，`outcome.body.result.final` 为对象且 `final.text` 为字符串；run 的 `result.final_text` 必须与该文本一致。不能把预算耗尽导致的 completed 当作 provider final 成功。
   - 通过 `HostJournal.records_for(model_id)` 核对该 effect 的 `dispatch_started`、`dispatch_finished` 各一次，且开始记录先于完成记录；两条记录的 `run_id` 必须等于本次 start 的 run，`dispatch_finished.payload.outcome` 必须等于历史 effect outcome，整个 `mapping.result` 必须等于 `outcome.body.result`。通过 `last("dispatch_finished", model_id)["payload"]["mapping"]["reply"]` 读取已有 reply 元数据；不新增 journal 事件或并列状态。
5. 摘要使用验证后的数据：
   - model 从 adapter 模块的 `MODEL` 读取，移除 smoke 重复 `_MODEL` 常量。
   - endpoint 仅输出主机名。
   - run/effect 必须为有效 UUID。
   - tokens 为非负整数，排除 bool，并与可信 reply 的 prompt+completion 及 settlement usage 一致。
   - 成功 finish 固定验证为 `stop`；`wall_ms` 取已验证 usage。
   - 不要求模型文本逐字等于提示中的 SQL；本用例验证协议闭环，不新增文本质量门禁。
6. 核对该条 `dispatch_finished.payload.mapping`：`class="success"`，`result.final`、`result.usage` 与数据库结算内容相等，`reply.content` 与 `final.text` 相等，reply finish 为 `stop`。prompt/completion token 与两处 usage.tokens、usage.wall_ms 均须为非负整数（bool 不算整数）；prompt+completion 等于 settlement tokens，reply wall_ms 等于 settlement wall_ms。摘要从这条已绑定的 journal reply 派生，不信任 `stats.last_reply`。允许空 final 文本；不要求 SQL 字面内容、响应 id、费用、reasoning、provider 返回 model 字段或顶层 cause/close_reason。
7. 摘要含义及敏感内容检查通过后，在 fixture 上下文退出前关闭 journal/数据库资源；再退出 fixture、删除私有目录并确认目录不存在；只有这些步骤都成功才打印成功摘要并返回 0。删除开始前的任何初始化、核验、关闭或清理错误均返回 1，且不启动目录删除、保留已生成 journal。删除开始后若递归清理部分成功再失败，删除不可回滚：返回 1、不打印成功、不重试，尽力保留剩余证据并准确报告尚可读取的路径，不声称原 journal 完整保留。失败路径尽力关闭资源。只打印固定原因代码或异常类型及可用 journal 路径，不打印异常消息、响应/请求正文。普通 Python `KeyboardInterrupt` 走 best-effort finally 关闭/保留路径，不转换为成功或 SKIP；SIGTERM/SIGKILL 在未新增信号处理机制时不保证 finally 清理，也不声称测试证明其退出状态。

该路径只新增局部 handle 与摘要数据；资格和终态仍归 PostgreSQL，执行证据仍归 `HostJournal`。运行时间和空间不随完整 scope 历史增长，因为该 disposable smoke 明确限定一条 run/model。

#### G9 回归

复用现有 `ScriptTransport`、fixture、网络 deny 和 patch 机制，覆盖完整 `_live()` 路径；不新增生产注入参数。由于 `setup_db()` 会 DROP/CREATE 测试库，G9 子场景必须借用当前 fixture：在 `smoke.py` 的规范动态导入目标 `v24.s1.setup_db` 与 `v24.host.deepseek.DeepSeekAdapter` 上临时 patch；adapter 替换为原 adapter 类加 ScriptTransport/测试时钟的工厂。借用上下文必须是非拥有的 `nullcontext(fixture)` / `nullcontext()`，绝不返回真实 `StageTestDB` 或 helper context，避免 `__exit__()` 清理共享库或关闭外层连接。使用假 key、独立可观测 journal 子目录，patch `tempfile.mkdtemp` 为每次 invocation 在 G9 workdir 下创建并记录唯一 child path；绝不把共享 workdir 本身作为 smoke 临时目录。用 `redirect_stdout` 捕获输出；所有 patch 在 `finally` 恢复。G9 只用 ScriptTransport 和网络 deny，不新增可真实联网的测试入口，也不新增生产 adapter 注入参数。

保持 G9 的 11 个顶层 ID，在既有对应 ID 中增加子场景；在 `test_g9.py` 中以 keyword-only fixture 参数供 B/F/L 注入借用上下文，并更新同文件 dispatcher，生产 API 不加测试注入参数：

- **G9-B**：固定 stop/final 响应，HTTP dispatch 恰一次；settled model 已不在 `host_effects` 中，完整 smoke 仍 exit 0，摘要正确，连接关闭且 journal 删除。使用捕获的唯一临时路径与 stdout 验证删除和输出时序。
- **G9-F**：length/timeout/拒绝响应、未完成 run、completed 但无成功 final、已取消 run 但 late settlement 留下 succeeded model 均 exit 1；零自动重试。普通失败在删除开始前保留 journal。另以 ScriptTransport 抛出 `KeyboardInterrupt`，断言只尝试一次、无成功输出、资源经 finally 尽力关闭且 journal 保留；不声称此同步注入证明 OS signal 的退出码。
- **G9-L**：无 flag、flag 但两个 key 都缺失时构造短路；输出前泄漏检查；摘要不包含敏感正文；权限、部分初始化/关闭/清理失败，以及缺失、重复、错误 id、异常分页、journal run_id 不匹配和 journal outcome/result 不匹配均拒绝。多个完整入口调用共享同一 fixture 时验证 request key 唯一，确认每次都真实创建其自己的 scope/run，而非拿到按 `(principal_id, request_key)` 缓存的旧响应。捕获每次生成的专属临时目录；清理失败覆盖“先删掉 journal 文件、再抛错”的部分删除情形，验证 exit 1、无成功输出、资源已关闭、未重试、对剩余可用证据的报告准确，并由外层 fixture 最终清理测试目录。
- 直接调用新内部核验逻辑，覆盖缺失、重复 model 和异常分页信封；不为了构造异常而改变内核约束。

**Done-when**：11 条 closeout 与 G9 全量 exit 0；新测试确实覆盖旧缺陷；SQL、worker、journal 格式与 transport 不变。ledger 记录 `D-PF-2`：smoke 结果发现缺陷及修复证据，保留旧 G9 通过记录及其原证明边界。Smoke 的最终顺序为：核验 completion 与摘要 → 泄漏检查 → 关闭 journal/数据库资源 → 成功删除私有目录并验证路径不存在 → 打印成功摘要并返回 0。任一核验、关闭或清理失败都返回 1；删除开始前失败保留完整 journal，递归删除部分完成后失败则尽力保留剩余证据并准确说明可用路径，不能先打印成功。Oracle-adjudicated 2026-10-25：采用此分界（保守范围假设），因为递归文件删除不可回滚；若以后要求部分删除后仍保留完整 journal，须另行设计副本生命周期。

**Key files**：`v24/host/smoke.py`、`v24/s10/test_g9.py`、s10 README、matrix、ledger、本计划。
**Deps**：P0。**Size**：M。

### M-E — 真实 provider 证据登记

**Goal**：形成不可混淆的 live 状态记录。

**Approach**

先执行显式清除凭据的负控；它证明拒绝路径，**不能证明当前环境本来没有 key**。

真实调用只在以下条件全部满足时执行：

- 已有针对本次 live smoke 的明确授权；
- 实际政策允许该入口；
- 环境中存在 `DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY`；
- M-S 已通过；
- 使用固定 endpoint、模型、提示和预算。

凭据只在进程内检查是否存在，不打印值，不通过 `grep "$KEY"` 等方式放入 argv。只运行一次，不循环重试，不尝试 `/v1` 别名。

三处工件采用相同证据字段：

| 字段 | 内容 |
|---|---|
| `executed_at` | 实际日期、时间、时区；未执行则为空 |
| `recorded_at` | 本条记录登记日期 |
| `source_sha` | 被执行源码提交 |
| `command` | 实际命令；未执行时明确标为拟执行命令 |
| `status` | `passed` / `failed` / `not_run` |
| `reason` | 如 `credentials_absent`、`not_authorized`、`provider_unknown` |
| `exit_code` | 实际整数；未执行为 `not_executed` |
| 成功摘要 | endpoint host、model、run/effect、tokens、finish、provider `wall_ms` |
| 外部耗时 | `/usr/bin/time -p` 的 real；与 provider wall 分开 |
| 证明范围 | 一次固定无 tools 的真实协议闭环 |

规则：

- `credentials_absent`/2、`not_requested`/0、toolchain SKIP/2 均表示 live 未验证。
- 无授权时不调用 live 入口；记录 `not_run/not_authorized`，不能伪造 exit 2。
- 确实启动的调用失败必须记 `failed`，不能改成未运行。
- 三处工件均分别包含 `negative_control` 与 `live_attempt` 记录组；前者记录真实执行的 keyless 命令、时间、`credentials_absent`、实测 exit 2，后者独立记录实际 live 命令/时间及 `passed`、`failed` 或 `not_run`。未执行字段使用 `not_executed`，不得把负控 exit 2 复制为 live attempt 结果。
- 外部拒绝、超时等按既有映射正确收口，不升级为确定性 gate；失败当步停止，不自动重试。归因和证据登记是后续独立步骤。暴露 host 缺陷或无法归因的失败，须先完成修复与归因再发布。
- 一次成功不关闭真实工具调用、thinking 历史、性能、质量或计费准确性的证据缺口。

**当前状态（2026-10-25）**：本计划阶段未查询 key 是否存在、未取得真实调用授权，也未发起请求；因此先验状态为 `not_run/not_executed`，不是实测 `credentials_absent`。实施时用实际日期登记，记录实际命令或明确标注拟执行命令；不从本计划文件名推导执行日期。

**Done-when**：11 条 closeout 与 G9 通过；三处证据一致。里程碑可以以“证据登记完成、live 未验证”结束，不把可选项改写为通过。

**Key files**：s10 README、matrix、ledger、本计划。
**Deps**：M-S。**Size**：S。

## 执行记录 — M-E（2026-10-25）

`recorded_at=2026-10-25`，三组记录均基于 source `e869e81`。M-E 仅执行 opt-in 入口负控，未检查实际 key 是否存在；无 flag 命令直接短路，flag 负控显式清除凭据，未取得本次 live smoke 授权，因此没有发起真实请求。负控结果与 live attempt 分开登记：

| 记录组 | executed_at（Asia/Shanghai） | source_sha | command | status | reason | exit_code |
|---|---|---|---|---|---|---|
| `negative_control` | 2026-10-25T11:05:35+08:00 | `e869e81` | `UV_NO_ENV_FILE=1 uv run python -m v24.host.smoke` | passed | `not_requested` | 0 |
| `negative_control` | 2026-10-25T11:05:35+08:00 | `e869e81` | `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python -m v24.host.smoke --real-provider-smoke` | passed | `credentials_absent` | 2 |
| `live_attempt` | `not_executed` | `e869e81` | 拟执行：`UV_NO_ENV_FILE=1 /usr/bin/time -p uv run python -m v24.host.smoke --real-provider-smoke` | `not_run` | `not_authorized` | `not_executed` |

`not_requested` 与 `credentials_absent` 仅证明入口短路行为；它们不证明当前环境本来没有 key，也不证明真实 provider。live attempt 的成功摘要（endpoint/model/run/effect/tokens/finish/provider wall_ms）和外部耗时均为 `not_executed`，证明范围为空。三处工件已同步记录同一组字段。D-S7-2 继续开启。

### M-F — 登记独立后续计划

**Goal**：让延期范围具有明确入口，又不在收尾中半实现。

| 后续计划 | 触发条件 | 必须解决的问题 | 将来的完成证据 |
|---|---|---|---|
| 第二批语言 | 明确需要 Go、Swift 或 DuckDB | 每种语言的执行方式、artifact 摘要、工具链发现及 registry 合同 | 各语言完整生命周期、零 spawn 负例、缺工具链 exit 2；需要时补同 run 证据 |
| D-S7-2 公平性 | 明确跨 scope 调度与服务目标 | 负载假设、等待界限、调度策略、与 G/串行 IO 的关系 | 可复核活性模型与对抗负载证据 |
| 跨主机租约 | 明确多主机部署需求 | journal 所有权、远端副作用去重、fencing、故障与接管边界 | 分区/崩溃/重复执行测试；需要改内核时另走设计修订 |
| Provider 延迟与质量 | 明确测量目标、预算和样本集 | latency 分布、失败率、质量指标、费用与模型版本 | 独立实验报告；不使用一次 smoke 代替 |

这些是后续计划的范围登记，本轮不创建没有内容的占位文件、不修改 registry 或 scheduler。D-S7-2 继续标为开启；跨主机能力和性能研究记录为未验证范围，不虚构为已经编号的内核缺陷。

**Done-when**：ledger、s10/s11 README 与本计划一致；11 条 closeout、G9 和 G10 全量 exit 0。Node 与 multilingual 两条 opt-in 命令在 M-P 的发布候选上必须 exit 0。

## 执行记录 — M-F（2026-10-25）

M-F 完成四项后续范围登记，未创建占位实现、未修改 registry/scheduler，D-S7-2 保持开启。当前 v24 源提交 `74b3c30` 上的 G10、Node 和 multilingual 检查均通过；M-P 仍需在最终发布候选树上重跑同两条 Node 相关命令。

| 命令 | executed_at（Asia/Shanghai） | source_sha | exit | 结果 |
|---|---|---|---:|---|
| `uv run python v24/s11/test_g10.py` | 2026-10-25T11:11:31+08:00 | `74b3c30` | 0 | `[passed] v24 G10 M-P Python: 8 case(s): G10-A, G10-B, G10-C, G10-D, G10-E, G10-F, G10-G, G10-H` |
| `uv run python v24/s11/test_node.py --node` | 2026-10-25T11:11:31+08:00 | `74b3c30` | 0 | `[passed] v24 G10 M-P Node: node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` |
| `uv run python -m v24.host.plugin_smoke --multilingual-smoke` | 2026-10-25T11:11:31+08:00 | `74b3c30` | 0 | `[passed] v24 multilingual smoke python=ok node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node final=ok` |

上述结果仍只覆盖已交付 Python/Node 插件平面；第二批语言、跨主机租约、D-S7-2 公平性和 provider 性能/质量均未验证。

**Key files**：s10/s11 README、ledger、本计划。
**Deps**：P0。**Size**：S。

### M-P — 发布到 main

**Goal**：发布已经验证的分支内容，并保留准确的版本边界。

**Approach**

1. 在最终 `v24` 源提交上重跑 11 条 closeout、G8/G9/G10，固定完整 SHA。
2. 准备可审阅发布清单：全部入站路径、源提交、main 基点、v99 Phase 0 范围、各层证据及所有未验证项。当前规划请求不构成发布授权。
3. 从最新 `origin/main` 创建独立发布 worktree 和临时发布分支。保留用户主检出的全部修改和未跟踪文件。
4. 按固定源 SHA 执行一次 `--no-ff --no-commit` merge。合并期间不 rebase、squash、cherry-pick 或打 tag。
5. 在合并候选树上执行：
   - 冻结 11 条 closeout；
   - G8/G9/G10；
   - Node 独立生命周期及 multilingual smoke；
   - P0 抄录的两条 v99 Phase 0 正式命令。
6. 本次发布维持既有 Python+Node 交付范围，因此发布候选的两个 Node 检查要求 exit 0；缺工具链时保留历史证据，但本次发布验证未完成，不将 exit 2 当作通过。
7. 比较冻结九文件与 `996cb5b`；核对合并引入的 `v99` 仅有已声明 Phase 0 及其文档，不宣称 W1–W4 完成。
8. 测试通过后更新 matrix、ledger、阶段 README、本计划及发布记录初稿。记录被测试的源 SHA、main 基点和候选执行树；此时 merge SHA 尚未生成，不填假值。
9. 检查完整 merge 暂存区，确认其中所有已声明入站源码和文档均属于候选；另外按路径暂存本次证据文档，不能把“只按路径暂存文档”误作把 merge 变成 docs-only。比较已测试候选 tree 与最终 merge tree，差异只能包含声明过的文档路径，执行文件必须完全相同。以 `v24: merge the closeout line into main` 创建 merge commit；提交前检查暂存区，正常运行 hooks。
10. 从隔离发布分支正常推送 `HEAD:refs/heads/main`，等价于发布到 main，不修改 dirty 主检出。推送成功后立即要求 `origin/main` 恰等于 merge SHA；将真实 merge SHA/parents 补入发布记录的 M-A 文档提交。

M-P 创建发布候选前必须重新 `git fetch origin`，以最新 `origin/main` 为基点，不使用可能陈旧的本地 `main`；P0 的 fetch 不足以代表数个里程碑后的发布时点。若 push 被拒因 main 推进，丢弃未发布候选并从新 `origin/main` 重建同一单次 merge，再运行全部适用候选检查。发布后的父提交验证必须精确比较 merge commit SHA、main base、固定 v24 source SHA 的顺序；M-P push 后确认 `origin/main` 恰等于 merge SHA，M-A push 后再次 fetch 并验证 merge 与 audit SHA 均为远端祖先。远端已分叉且不能安全继续时，依 `AGENTS.md` 停止发布并请求处理决定；不得 force 或 reset 用户分支。

**Done-when**：双亲 merge 已推送；发布的执行树与验证树一致；所有必需检查 exit 0。真实 provider 仍可为明确的未验证或已归因失败状态。

**Key files**：隔离发布 worktree、发布记录、matrix、ledger、s9/s10/s11 README、本计划。
**Deps**：前述收尾里程碑；明确发布授权。**Size**：M。

### M-A — 发布记录最终化

**Goal**：记录已经产生的提交身份，避免文档自引用 SHA。

**Approach**

- 将 M-P 的真实 merge SHA、两个有序 parent SHA、源分支 SHA、远端核验日期补入发布记录。
- 保留逐条命令退出码和每项证据的来源提交；不把“未运行”改成通过。
- 检查 merge→audit commit 的 tree 差异仅包含发布记录与本计划；执行文件及 SQL 摘要必须与 M-P 的已测树一致。
- 从隔离发布分支按路径提交并执行 `git push origin HEAD:refs/heads/main`；随后 fetch，确认 merge SHA 与 audit SHA 都是 `origin/main` 祖先。
- 此步验证为文档/提交身份/执行树一致性检查，不声称重新运行了 runtime gates；并确认 merge commit 到 audit commit 的 tree 差异仅是发布记录与本计划。
- 按路径提交并立即推送 main；最终核对远端包含 merge 与审计提交。

**Done-when**：发布记录已推送；记录中的 merge 与 parents 顺序精确相符；merge 与 audit commit 均在 fetch 后的 `origin/main` 历史中；执行树未变化。

**Key files**：`docs/reviews/v24-release-2026-10-25.md`、本计划。
**Deps**：M-P。**Size**：S。

## File-by-file impact

以下路径均相对于承载该提交的仓库根；源码工作在 v24 worktree，发布工作在隔离发布 worktree。

| 文件 | 变更 | 原因与依赖 |
|---|---|---|
| `docs/plans/v24-post-closeout-followup-2026-10-25.md` | 完整计划、裁决、执行记录、最终发布链接 | 唯一正式后续计划；P0 起持续更新 |
| `v24/s9/test_g8.py` | 仅修改 H13 的 worst-case 注释/标题 | D1；不改断言、编号或运行行为 |
| `v24/s9/README.md` | 64 项合同、夹具尺寸边界、修正 512 混淆 | M-H；随后追加发布验证 |
| `v24/host/smoke.py` | `_bootstrap` 返回 run/model handles；新增 `_verify_completion`；删除 `_first_model`、`_run_of` 和重复模型常量；验证摘要后关闭资源、确认清理再输出成功 | M-S；不改 host 调度或 SQL |
| `v24/s10/test_g9.py` | 在既有 ID 内追加完整 smoke 回归与异常子场景 | 与 smoke 修正原子落地；复用 ScriptTransport |
| `v24/s10/README.md` | 固定模型、smoke 合同、live 三态、未来性能计划边界 | M-M/M-S/M-E/M-F |
| `v24/s11/README.md` | 第二批语言的真实接入边界；追加发布时 Node 证据 | M-F/M-P；插件实现不变 |
| `docs/reviews/v24-conformance-matrix-2026-10-23.md` | 追加新运行结果、smoke 修复和 live 状态 | 保留旧记录及 11/11；不得覆盖历史 |
| `docs/reviews/v24-deviation-ledger-2026-10-23.md` | `D-PF-1` 容量披露、`D-PF-2` smoke 缺陷；保留 D-S7-2 | M-H/M-S；后续证据追加 |
| `docs/plans/v24-closeout-real-provider-multilingual-2026-10-24.md` | 将页上限/模型/语言开放项指向本计划裁决；补充 smoke 缺陷说明 | 保留原执行结果，不回写成当时已验证 |
| `docs/reviews/v24-release-2026-10-25.md` | 新增发布清单、验证表、边界；M-A 补真实 merge SHA | M-P 创建，M-A 完成 |

**不修改**：九个冻结内核 SQL、`49_host_reads.sql`、`50_permissions.sql`、loader、`expected_canonical`、G1 ACL 集合、`host/db.py`、`worker.py`、`journal.py`、`deepseek.py`、`registry.py`、参考插件、`v13/**`、`v15/**`、`v99/**` 源码，以及 s7 的 11 条命令与顺序。

`AGENTS.md` 当前不计划修改。P0 若发现实际 worktree 缺少第三入口，则 live 保持未执行；政策修订必须单独明确，不能依据 D-MR-9 的文字推定文件已经正确。

## Risks and rollback

| 风险 | 判断信号 | 处理 |
|---|---|---|
| 已成功 model 被误判失败 | model 不在 `host_effects`，却存在于历史 | M-S 回归固定该场景；不改变工作发现 SQL |
| completed 被误当 final 成功 | run completed，但 model 无合法 final | smoke 失败，保留 journal |
| 64 MiB 被当作安全上限 | 文档出现 worst-case bound 或 memory-safe | 修正文档；本轮不声称内存治理完成 |
| 凭据进入输出/argv | 输出前检查失败或测试哨兵可见 | 不打印成功摘要；不提交敏感工件；不使用 secret 作为 shell 参数 |
| journal 清理失败 | 目录删除启动前失败，或递归删除中途失败 | 前者不启动删除并保留完整 journal；后者不可回滚，返回失败并准确报告剩余证据，不声称原 journal 完整 |
| live 失败被降格为 SKIP | 已 dispatch，却记录 not_run | 保留 failed、真实退出码及 journal |
| v99 被误报全部完成 | 发布说明没有 Phase 0 限定 | 发布清单逐项区分 Phase 0 与 W1–W4 |
| 用户工作被合并卷入 | 暂存区包含主检出未提交文件 | 使用隔离 worktree，按路径暂存 |
| 远端 main 漂移 | push 非快进拒绝 | fetch、重新归因；不 force、不 reset 用户分支 |
| 仅以干净工作区证明冻结 | 检查未指定 `996cb5b` | 改为显式基线比较，覆盖已提交修改 |

本轮没有数据迁移。smoke 的私有函数返回类型改变与调用点、测试必须同一提交；journal 格式保持兼容。

尚未提交的失败合并使用 `git merge --abort`。已经提交的合并不能用 abort 撤销；已发布需要回滚时使用经授权的 `git revert -m 1 <merge_sha>`，追加回滚记录，不改写 main 历史。文档或 smoke 修正按对应提交 revert；失败 journal 不作为代码回滚的一部分删除。

## Edge cases

- **无 flag、环境有 key**：仍 `not_requested`/0；不创建执行资源。
- **只有 `OPENAI_API_KEY`**：按既有 fallback 解析；仍需显式授权。
- **负控清除了 key**：只能证明负控路径，不能据此记录“实际环境缺 key”。
- **没有授权**：live 未执行，退出码为 `not_executed`，不是 2。
- **成功 model 已退出工作列表**：通过历史读取核验。
- **空、重复、错误 run 的 model**：smoke 失败，不选取“第一条看起来可用”的记录。
- **provider 返回 length、unknown 或超 reserve usage**：保留既有映射，不产生假 final，不续写、不重发。
- **HTTP 成功但验收或日志检查失败**：整体 exit 1；若目录删除尚未启动则保留完整 journal，递归删除已部分开始时则尽力保留剩余证据并准确报告；不得再调用一次以获得绿色。
- **lease 已过期但 receipt 仍被接纳**：沿用既有 late settlement 合同；不将 timeout 描述为硬期限。
- **分页期间插入、重复或遗漏**：本轮不改变 worker 的重新扫描、去重和 claim 复核；不新增持久 cursor。
- **Node 不存在**：exit 2，当前发布验证未完成；保留历史 Node 通过记录及其日期。
- **旧计划或 AGENTS 文件与合并路径冲突**：隔离发布 worktree避免主检出冲突；不删除或覆盖未跟踪原件。
- **执行日期晚于文件名日期**：文件名保持计划标识；每条执行记录使用真实日期。
- **测试后有源码变化**：相关运行证据失去对新树的覆盖，必须重新验证后再提交。
- **KeyboardInterrupt**：走 Python finally 的 best-effort 关闭和删除启动前 journal 保留路径；SIGTERM/SIGKILL 不承诺在无信号处理器时执行清理。
- **递归删除部分失败**：不可回滚；exit 1、无成功摘要、不重试，报告仍可用的证据路径，不宣称完整 journal 仍存在。

## Verification commands

### 1. 基线与冻结检查

在 v24 worktree 执行，记录实际结果：

```bash
git rev-parse HEAD
git status --short
git rev-list --left-right --count origin/v24...v24
git merge-base origin/main v24
git rev-list --left-right --count origin/main...v24
git merge-base --is-ancestor v99 v24
git tag --list
```

原提供基线分别为 `996cb5b`、v24 tracked 干净、`0 0`、`ab34d69`、`0 30`、ancestor exit 0、空 tag 列表。所有远端拓扑比较均以 fetch 后的 `origin/main`、`origin/v24` 为准；本地 `main` 可有意保持陈旧。本次仅重查了本地 HEAD 与缓存拓扑；本节是实施时待执行清单，不是本次完整执行结果。P0 先 `git fetch origin`，再记录最新远端及差异；fetch 后的偏离须审查，不能机械要求仍等于旧值。

冻结检查在源树和合并候选树执行，**期望 exit 0**：

```bash
git diff --exit-code 996cb5b -- \
  v24/sql/10_schema.sql \
  v24/sql/20_triggers.sql \
  v24/sql/30_advance.sql \
  v24/sql/40_interpreters.sql \
  v24/sql/45_capability.sql \
  v24/sql/46_cleanup.sql \
  v24/sql/47_verbs.sql \
  v24/sql/48_loop.sql \
  v24/sql/49_recovery.sql
```

### 2. Tier 1：冻结 closeout，恰 11 条

按以下顺序逐条执行、逐条记录退出码；全部期望 **0**：

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

### 3. Tier 2：extension checks

全部期望 **0**；不并入 closeout 计数：

```bash
uv run python v24/s9/test_g8.py

env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL \
  UV_NO_ENV_FILE=1 uv run python v24/s10/test_g9.py

uv run python v24/s11/test_g10.py
```

保持 G8 23 个、G9 11 个、G10 8 个顶层 ID；M-S 在 G9 既有 ID 内增加覆盖。`--only` 仅用于开发定位，不替代全量验收。

### 4. opt-in 入口负控

```bash
UV_NO_ENV_FILE=1 uv run python -m v24.host.smoke
```

期望 `not_requested`、exit **0**；真实 provider **未验证**。

```bash
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI \
  UV_NO_ENV_FILE=1 uv run python -m v24.host.smoke --real-provider-smoke
```

期望 `credentials_absent`、exit **2**；真实 provider **未验证**。不建库、不构造 adapter 的断言由 M-S 的离线测试证明。

### 5. 获授权且有凭据时的唯一真实调用

```bash
UV_NO_ENV_FILE=1 /usr/bin/time -p \
  uv run python -m v24.host.smoke --real-provider-smoke
```

- exit **0**：本次固定 smoke 通过。
- exit **1**：失败，保留证据并归因。
- exit **2**：未验证，记录凭据缺失。
- 信号中断：记录实际进程状态，不归入通过或 SKIP。

### 6. 多语言发布验证

```bash
uv run python v24/s11/test_node.py --node
uv run python -m v24.host.plugin_smoke --multilingual-smoke
```

M-P 要求两条均 exit **0**。exit **2** 表示当前工具链下未验证。

v99 Phase 0 的正式命令（M-P 均要求 exit **0**）：

```bash
uv run python v99/core/setup_db.py --self-check
uv run python v99/core/test_core.py
```

### 7. 发布形状与远端核验

发布操作采用已固定的源 SHA：

```text
创建隔离 worktree，基于最新 origin/main
→ git merge --no-ff --no-commit <固定的 v24 源 SHA>
→ 运行验证
→ 更新并按路径暂存证据
→ 创建 merge commit
→ git push origin HEAD:refs/heads/main
```

核验：

```bash
test "$(git show -s --format='%H %P' <merge_sha>)" = "<merge_sha> <recorded_main_base> <fixed_v24_source_sha>"
test "$(git rev-parse origin/main)" = "<merge_sha>"
git merge-base --is-ancestor <v24_source_sha> origin/main
git merge-base --is-ancestor bddeb81 origin/main
git ls-tree origin/main v24 v99
```

期望 merge 恰有两个 parent，ancestor 检查 exit **0**，`v24` 与 `v99` 为普通 tree，非 submodule。

## Implementation order

1. **P0**：核验来源、政策与基线，登记新运行结果；不修改用户主检出。
2. **M-H**：落实 64 项裁决及容量披露；验证、更新工件、单次提交、推送 `origin/v24`。
3. **M-M**：关闭模型扩展问题；验证并独立提交、推送。
4. **M-S**：smoke 内部接口、调用点及 G9 回归**原子落地**；验证后提交、推送。
5. **M-E**：根据真实授权与凭据状态执行一次 smoke 或登记未执行；完成证据提交、推送。
6. **M-F**：完成四项后续范围登记，独立提交、推送。
7. **M-P**：固定最终源 SHA，准备发布清单；M-E 已登记状态即可，不要求 live 成功。获得发布授权后在隔离 worktree 合并、验证、创建发布记录、提交并推送 main。
8. **M-A**：补 merge SHA、parents 与远端确认，检查执行树不变后提交、推送。

所有里程碑遵守：

```text
必需测试实际通过
→ 更新收尾工件
→ 按路径 git add
→ 检查暂存区
→ 单次 commit
→ 正常 push
```

禁止 `git add -A`、`git add .`、force-push、`--no-verify`。步骤失败停在该步骤；不得通过改口径或降低断言继续。

## Open questions

本轮设计选择已全部确定。实施前仍需验证的输入为：

1. **操作授权**：是否已有真实 provider 调用和 main 发布的明确授权；没有时分别记录未运行、发布就绪。
2. **实时环境**：实际 key 是否存在、Node 是否可用、当前远端 main 是否仍满足基线。
3. **政策衔接**：v24 worktree `AGENTS.md:76` 已列第三入口，主检出 `AGENTS.md` 仍只列两个。计划阶段不调用网络；实施时先确认届时适用的用户指令与 worktree 政策，不能让分支旧文档覆盖明确用户约束。journal 查询接口、G9 顶层 ID 和 v99 命令已在本计划列明，P0 复核是否漂移。

这些输入都有确定的处理路径，不要求实施者重新选择模型、页上限或发布拓扑。DeepSeek 当前外部可用性保持待证，不以历史文档代替 live 结果。

## References

- `docs/plans/v24-closeout-real-provider-multilingual-2026-10-24.md`：Oracle 5-B、M-H/M-R/M-P 合同与历史执行记录。
- `docs/plans/v24-closeout-followup-2026-10-25.md`：本稿采用并修正的未跟踪草稿。
- `docs/reviews/v24-conformance-matrix-2026-10-23.md`：§0.4–§0.7、§3、§4。
- `docs/reviews/v24-deviation-ledger-2026-10-23.md`：§1.15–§1.18、D-S7-2、D-MR-9/10、D-MP-1。
- `v24/s7/README.md`：冻结 11 条命令。
- `v24/s9/test_g8.py:g8_h13`、`v24/s9/README.md`。
- `v24/sql/49_host_reads.sql`、`v24/host/db.py`。
- `v24/host/smoke.py`、`deepseek.py`、`worker.py`、`journal.py`。
- `v24/s10/test_g9.py`、`v24/s10/README.md`。
- `v24/host/registry.py`、`v24/s11/plugin_fixtures.py`、`v24/s11/README.md`。
- `docs/plans/v15-merge-main-plan-2026-09-30.md`：发布拓扑先例。
- `docs/reviews/v24-post-closeout-followup-plan-critique-2026-10-25.md`：本计划的 bounded completeness / design critique；修订已按证据吸收。
- `docs/reviews/v99-core-phase0-conformance-matrix-2026-10-20.md`：Phase 0 范围与正式命令。
- `docs/plans/v99-core-native-plugin-plane-2026-10-20.md`：v24 worktree 的未跟踪非发布工作参考，仅用于理解未实现 W1–W4；不得在发布记录保留不可解析的引用。发布清单必须自行说明 v99 Phase 0 范围及 W1–W4 未完成，或明确将该文件列为入站文档。
- 实际工作树中的 `AGENTS.md`：里程碑、提交推送与真实网络入口纪律。


## 执行记录 — P0（2026-10-25）

正式计划从主检出同路径完整复制，目标原先不存在；保留主检出原件及 21 份既有未跟踪草稿。`git fetch origin` exit 0。v24 tracked 起点干净；主检出有 v20 用户修改及未跟踪文档，未移动、暂存或覆盖。

- source: `996cb5bc86f38fe5cbc21d058e93df54b4923620`, exit 0。
- main: `ab34d6972a17f688c4a11adba89e363d74adbe81`, exit 0。
- remote_main: `ab34d6972a17f688c4a11adba89e363d74adbe81`, exit 0。
- remote_v24: `996cb5bc86f38fe5cbc21d058e93df54b4923620`, exit 0。
- baseline: `996cb5bc86f38fe5cbc21d058e93df54b4923620`, exit 0。
- phase0: `bddeb815608de37bc21594a372085fe1e591db85`, exit 0。
- source_relation: `0	0`, exit 0。
- base: `ab34d6972a17f688c4a11adba89e363d74adbe81`, exit 0。
- relation: `0	30`, exit 0。
- ancestor: `(empty)`, exit 0。
- tags: `(empty)`, exit 0。

`git diff --exit-code 996cb5b -- <九冻结 SQL>` exit 0；SHA-256：

| 文件 | SHA-256 |
|---|---|
| `v24/sql/10_schema.sql` | `a365a235edefe49258038bef4b28a3cd5f8204ab22a71336e892efc706cbae76` |
| `v24/sql/20_triggers.sql` | `1c75ce97c79abdba9151bd8dfd22bb7b1167c10e256ed8fa54d4adf927da5af1` |
| `v24/sql/30_advance.sql` | `087a5bcdb4b9132e25b2d04bc0a31606d429fba5d5cfbb0a257f0a2440715870` |
| `v24/sql/40_interpreters.sql` | `2ebefff558f243891a613787a47ef68dcfb825b1bcc16b78f019e328f982c5f9` |
| `v24/sql/45_capability.sql` | `f629ddd511754a4828da4b4dc4da278c1a4bfcb2359f15f00fd6634f9e4f332e` |
| `v24/sql/46_cleanup.sql` | `bb32336bf6e262f62a55a78d55bf3ac7b649c06a50bdda9eda6263f96ed083ef` |
| `v24/sql/47_verbs.sql` | `5c5bdc611f33f5b37d1652f29aeda97323882487c27cf800ac53371a76ea0265` |
| `v24/sql/48_loop.sql` | `f23a93cdd5c14966442bf30eb1339b6e110c3b1c279b95650704aa9e12870f30` |
| `v24/sql/49_recovery.sql` | `b46abde9f5fc4259f9ea833440ca0c0815a4a14a578e058b861f59990d90af8d` |

worktree AGENTS.md 已包含第三个真实入口，用户提供约定亦如此；本轮 P0 无 provider 调用。worker/journal/G9 接缝与计划一致，records_for/last 可用，11 个顶层 G9 ID 未漂移。v99 Phase 0 两条正式命令已核对为 core/setup_db.py --self-check 与 core/test_core.py；留待发布候选执行。

基于 source HEAD `996cb5bc86f38fe5cbc21d058e93df54b4923620`（源码未改）；其后只追加证据文档。

| 命令 | 开始时间（Asia/Shanghai +08:00） | exit | 结果行 |
|---|---|---|---|
| `uv run python v24/load.py` | 2026-10-25T10:32:29.572989+08:00 | 0 | `[passed] v24 loader self-check` |
| `uv run python v24/s1/setup_db.py --self-check` | 2026-10-25T10:32:30.253887+08:00 | 0 | `[passed] v24/s1 setup self-check` |
| `uv run python v24/s1/test_ddl.py` | 2026-10-25T10:32:31.949233+08:00 | 0 | `[passed] v24 W2 G1-O owner DDL probes (no advance/ACL/lifecycle claim)` |
| `uv run python v24/s1/test_g1.py` | 2026-10-25T10:32:33.514042+08:00 | 0 | `[passed] v24 G1 kernel, commands, claim, locks, host_prepare settlement and ACL` |
| `uv run python v24/s2/test_g3a.py` | 2026-10-25T10:32:36.027661+08:00 | 0 | `[passed] v24 S2 W1-W6: resolve, infra, admission, activation, deactivation, dispose` |
| `uv run python v24/s3/test_g2.py` | 2026-10-25T10:32:37.829291+08:00 | 0 | `[passed] v24 S3 W1-W7: read surface + start + poll/wait_check + cancel + steer + respond (G2a-0/1/2/3/4/5/6/7/8/10/11; G3b-1..5; claimed/unknown settlement release reserved S4)` |
| `uv run python v24/s4/test_g2b.py` | 2026-10-25T10:32:43.213847+08:00 | 0 | `[passed] v24 S4 W1-W6` |
| `uv run python v24/s5/test_g4.py` | 2026-10-25T10:32:47.005077+08:00 | 0 | `[passed] v24 S5 W1-W4` |
| `uv run python v24/s6/test_g5.py` | 2026-10-25T10:32:50.196536+08:00 | 0 | `[passed] v24 S6 W1-W4` |
| `uv run python v24/s8/test_g7.py` | 2026-10-25T10:32:53.883665+08:00 | 0 | `[passed] v24 S8 W1-W3 G7-A…H + N1-N7: g7_a,g7_b,g7_c,g7_d,g7_e,g7_f,g7_g,g7_h,n1,n2,n3,n4,n5,n6,n7` |
| `uv run python v24/s7/test_g6.py` | 2026-10-25T10:32:56.410179+08:00 | 0 | `[passed] v24 S7 W1-W2 G6-A…H + N1-N9 + L1-L5: g6_a1,g6_b1,g6_b2,g6_b3,g6_c1,g6_c2,g6_c3,g6_d1,g6_e1,g6_f1,g6_g1,g6_g2,g6_g3,g6_h1,g6_h2,g6_h3,g6_n1,g6_n2,g6_n3,g6_n4,g6_n5,g6_n6,g6_n7,g6_n8,g6_n9,g6_l1,g6_l2,g6_l3,g6_l4,g6_l5` |
| `uv run python v24/s9/test_g8.py` | 2026-10-25T10:33:02.835700+08:00 | 0 | `[passed] v24 G8 host reads / closure / lease / recovery: 23 case(s)` |
| `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s10/test_g9.py` | 2026-10-25T10:33:13.235698+08:00 | 0 | `[passed] v24 G9 M-R: 11 case(s): G9-A, G9-B, G9-C, G9-D, G9-E, G9-F, G9-L, G9-J1, G9-J2, G9-J3, G9-R` |
| `uv run python v24/s11/test_g10.py` | 2026-10-25T10:33:15.316181+08:00 | 0 | `[passed] v24 G10 M-P Python: 8 case(s): G10-A, G10-B, G10-C, G10-D, G10-E, G10-F, G10-G, G10-H` |


## 执行记录 — M-H（2026-10-25）

已落实 D1；七个分页函数默认且最多 64 项，SQL/HostDB/worker 无变更。H13 仅修正标题，夹具与断言未改。`67,107,712 B` 是指定 ASCII 夹具的紧凑 JSON 尺寸，不是响应字节或内存上限；512 是闭包实体边界。正式 closeout 11/11、G8 23/23 均 exit 0。

基于 source HEAD `996cb5bc86f38fe5cbc21d058e93df54b4923620` 的未提交本里程碑树；其后只追加证据文档。

| 命令 | 开始时间（Asia/Shanghai +08:00） | exit | 结果行 |
|---|---|---|---|
| `uv run python v24/load.py` | 2026-10-25T10:33:52.969544+08:00 | 0 | `[passed] v24 loader self-check` |
| `uv run python v24/s1/setup_db.py --self-check` | 2026-10-25T10:33:53.462550+08:00 | 0 | `[passed] v24/s1 setup self-check` |
| `uv run python v24/s1/test_ddl.py` | 2026-10-25T10:33:55.204012+08:00 | 0 | `[passed] v24 W2 G1-O owner DDL probes (no advance/ACL/lifecycle claim)` |
| `uv run python v24/s1/test_g1.py` | 2026-10-25T10:33:56.812083+08:00 | 0 | `[passed] v24 G1 kernel, commands, claim, locks, host_prepare settlement and ACL` |
| `uv run python v24/s2/test_g3a.py` | 2026-10-25T10:33:59.267656+08:00 | 0 | `[passed] v24 S2 W1-W6: resolve, infra, admission, activation, deactivation, dispose` |
| `uv run python v24/s3/test_g2.py` | 2026-10-25T10:34:01.059690+08:00 | 0 | `[passed] v24 S3 W1-W7: read surface + start + poll/wait_check + cancel + steer + respond (G2a-0/1/2/3/4/5/6/7/8/10/11; G3b-1..5; claimed/unknown settlement release reserved S4)` |
| `uv run python v24/s4/test_g2b.py` | 2026-10-25T10:34:06.184088+08:00 | 0 | `[passed] v24 S4 W1-W6` |
| `uv run python v24/s5/test_g4.py` | 2026-10-25T10:34:09.880940+08:00 | 0 | `[passed] v24 S5 W1-W4` |
| `uv run python v24/s6/test_g5.py` | 2026-10-25T10:34:13.030239+08:00 | 0 | `[passed] v24 S6 W1-W4` |
| `uv run python v24/s8/test_g7.py` | 2026-10-25T10:34:16.695987+08:00 | 0 | `[passed] v24 S8 W1-W3 G7-A…H + N1-N7: g7_a,g7_b,g7_c,g7_d,g7_e,g7_f,g7_g,g7_h,n1,n2,n3,n4,n5,n6,n7` |
| `uv run python v24/s7/test_g6.py` | 2026-10-25T10:34:19.020490+08:00 | 0 | `[passed] v24 S7 W1-W2 G6-A…H + N1-N9 + L1-L5: g6_a1,g6_b1,g6_b2,g6_b3,g6_c1,g6_c2,g6_c3,g6_d1,g6_e1,g6_f1,g6_g1,g6_g2,g6_g3,g6_h1,g6_h2,g6_h3,g6_n1,g6_n2,g6_n3,g6_n4,g6_n5,g6_n6,g6_n7,g6_n8,g6_n9,g6_l1,g6_l2,g6_l3,g6_l4,g6_l5` |
| `uv run python v24/s9/test_g8.py` | 2026-10-25T10:34:25.196009+08:00 | 0 | `[passed] v24 G8 host reads / closure / lease / recovery: 23 case(s)` |


## 执行记录 — M-M（2026-10-25）

D3 已落实为文档合同：固定 deepseek-flash；v24 无 runtime allowlist，不消费 v15 allowlist；不加模型参数、环境 override 或 CLI。外部事实保留 2026-10-24 核查日期。本次顺带清理复制计划中的 Markdown 行尾空格，未改主检出原件。deepseek.py、v15/** diff 为空。closeout 11/11、G9 11/11 均 exit 0。

基于 source HEAD `01890298bc380d28903243e52cb61474ddfe2bc1` 的未提交本里程碑树；其后只追加证据文档。

| 命令 | 开始时间（Asia/Shanghai +08:00） | exit | 结果行 |
|---|---|---|---|
| `uv run python v24/load.py` | 2026-10-25T10:36:15.016202+08:00 | 0 | `[passed] v24 loader self-check` |
| `uv run python v24/s1/setup_db.py --self-check` | 2026-10-25T10:36:15.556942+08:00 | 0 | `[passed] v24/s1 setup self-check` |
| `uv run python v24/s1/test_ddl.py` | 2026-10-25T10:36:17.243026+08:00 | 0 | `[passed] v24 W2 G1-O owner DDL probes (no advance/ACL/lifecycle claim)` |
| `uv run python v24/s1/test_g1.py` | 2026-10-25T10:36:18.887811+08:00 | 0 | `[passed] v24 G1 kernel, commands, claim, locks, host_prepare settlement and ACL` |
| `uv run python v24/s2/test_g3a.py` | 2026-10-25T10:36:21.361664+08:00 | 0 | `[passed] v24 S2 W1-W6: resolve, infra, admission, activation, deactivation, dispose` |
| `uv run python v24/s3/test_g2.py` | 2026-10-25T10:36:23.152703+08:00 | 0 | `[passed] v24 S3 W1-W7: read surface + start + poll/wait_check + cancel + steer + respond (G2a-0/1/2/3/4/5/6/7/8/10/11; G3b-1..5; claimed/unknown settlement release reserved S4)` |
| `uv run python v24/s4/test_g2b.py` | 2026-10-25T10:36:28.373543+08:00 | 0 | `[passed] v24 S4 W1-W6` |
| `uv run python v24/s5/test_g4.py` | 2026-10-25T10:36:32.311538+08:00 | 0 | `[passed] v24 S5 W1-W4` |
| `uv run python v24/s6/test_g5.py` | 2026-10-25T10:36:35.953402+08:00 | 0 | `[passed] v24 S6 W1-W4` |
| `uv run python v24/s8/test_g7.py` | 2026-10-25T10:36:40.285082+08:00 | 0 | `[passed] v24 S8 W1-W3 G7-A…H + N1-N7: g7_a,g7_b,g7_c,g7_d,g7_e,g7_f,g7_g,g7_h,n1,n2,n3,n4,n5,n6,n7` |
| `uv run python v24/s7/test_g6.py` | 2026-10-25T10:36:42.915408+08:00 | 0 | `[passed] v24 S7 W1-W2 G6-A…H + N1-N9 + L1-L5: g6_a1,g6_b1,g6_b2,g6_b3,g6_c1,g6_c2,g6_c3,g6_d1,g6_e1,g6_f1,g6_g1,g6_g2,g6_g3,g6_h1,g6_h2,g6_h3,g6_n1,g6_n2,g6_n3,g6_n4,g6_n5,g6_n6,g6_n7,g6_n8,g6_n9,g6_l1,g6_l2,g6_l3,g6_l4,g6_l5` |
| `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s10/test_g9.py` | 2026-10-25T10:36:50.074039+08:00 | 0 | `[passed] v24 G9 M-R: 11 case(s): G9-A, G9-B, G9-C, G9-D, G9-E, G9-F, G9-L, G9-J1, G9-J2, G9-J3, G9-R` |

## 执行记录 — M-F1（2026-10-25）

M-F1 是 D-S7-2 独立设计之后的唯一实现里程碑，a/b/c 作为内部步骤一次收口。v24 源 worktree 的完整 31 命令验证全部 exit 0：G11 全量、G11-A…L、loader/DB/既有回归、G8、G9、G10、Node、smoke 负控与 multilingual smoke。新增调度实现保持 12 个 SQL、loader、HostDB、HostJournal 格式及 legacy 单 scope 入口冻结；未调用真实 provider。详细证据（source HEAD、执行树 digest、逐命令时间/exit/结果摘要/日志 SHA-256）见 [`docs/reviews/v24-d-s7-2-fairness-execution-2026-10-25.md`](../reviews/v24-d-s7-2-fairness-execution-2026-10-25.md)。

M-F1 只登记有限 opportunity-dense host-only FC 子合同及 Fake-only 证据；D-S7-2 广义债务仍开启。下一步 M-P/M-A 在隔离候选 worktree 完成 merge、候选树复验、推送与最终审计记录。

## 执行记录 — M-S（2026-10-25）

M-S 已完成。基于 source SHA `6df64440299b4e6035e9e587bebd5f09eb9d9cbe`，修复 smoke 在成功结算后从 active effect 列表重新发现 model 的缺陷：`_bootstrap` 返回已知的 run/model handles，完成核验改读历史分页面，并将摘要核验、泄漏检查、资源关闭和私有目录清理置于成功输出之前。清理失败不会被吞掉；删除启动前保留完整 journal，递归删除部分完成后报告剩余证据路径。G9 增加了成功、失败、取消后迟到成功、KeyboardInterrupt、初始化/关闭/清理故障、历史/证据畸变及 flag/key 负控覆盖；不调用真实 provider。

| 命令 | 开始时间（Asia/Shanghai +08:00） | exit | 结果行 |
|---|---|---:|---|
| `uv run python v24/load.py` | 2026-10-25T10:57:33.560819+08:00 | 0 | `[passed] v24 loader self-check` |
| `uv run python v24/s1/setup_db.py --self-check` | 2026-10-25T10:57:34.228547+08:00 | 0 | `[passed] v24/s1 setup self-check` |
| `uv run python v24/s1/test_ddl.py` | 2026-10-25T10:57:35.962049+08:00 | 0 | `[passed] v24 W2 G1-O owner DDL probes (no advance/ACL/lifecycle claim)` |
| `uv run python v24/s1/test_g1.py` | 2026-10-25T10:57:37.555897+08:00 | 0 | `[passed] v24 G1 kernel, commands, claim, locks, host_prepare settlement and ACL` |
| `uv run python v24/s2/test_g3a.py` | 2026-10-25T10:57:40.009714+08:00 | 0 | `[passed] v24 S2 W1-W6: resolve, infra, admission, activation, deactivation, dispose` |
| `uv run python v24/s3/test_g2.py` | 2026-10-25T10:57:41.857238+08:00 | 0 | `[passed] v24 S3 W1-W7: read surface + start + poll/wait_check + cancel + steer + respond (G2a-0/1/2/3/4/5/6/7/8/10/11; G3b-1..5; claimed/unknown settlement release reserved S4)` |
| `uv run python v24/s4/test_g2b.py` | 2026-10-25T10:57:46.944494+08:00 | 0 | `[passed] v24 S4 W1-W6` |
| `uv run python v24/s5/test_g4.py` | 2026-10-25T10:57:50.698726+08:00 | 0 | `[passed] v24 S5 W1-W4` |
| `uv run python v24/s6/test_g5.py` | 2026-10-25T10:57:53.867467+08:00 | 0 | `[passed] v24 S6 W1-W4` |
| `uv run python v24/s8/test_g7.py` | 2026-10-25T10:57:57.540373+08:00 | 0 | `[passed] v24 S8 W1-W3 G7-A…H + N1-N7: g7_a,g7_b,g7_c,g7_d,g7_e,g7_f,g7_g,g7_h,n1,n2,n3,n4,n5,n6,n7` |
| `uv run python v24/s7/test_g6.py` | 2026-10-25T10:57:59.890315+08:00 | 0 | `[passed] v24 S7 W1-W2 G6-A…H + N1-N9 + L1-L5: g6_a1,g6_b1,g6_b2,g6_b3,g6_c1,g6_c2,g6_c3,g6_d1,g6_e1,g6_f1,g6_g1,g6_g2,g6_g3,g6_h1,g6_h2,g6_h3,g6_n1,g6_n2,g6_n3,g6_n4,g6_n5,g6_n6,g6_n7,g6_n8,g6_n9,g6_l1,g6_l2,g6_l3,g6_l4,g6_l5` |
| `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s10/test_g9.py` | 2026-10-25T10:58:06.053677+08:00 | 0 | `[passed] v24 G9 M-R: 11 case(s): G9-A, G9-B, G9-C, G9-D, G9-E, G9-F, G9-L, G9-J1, G9-J2, G9-J3, G9-R` |
