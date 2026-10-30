# Investigation: R0a 文件平面历史设计 × v13 长循环升级后的对齐 × v3 文件平面设计要点

## Summary
R0a（可行性 v2 §2.1/§8，2026-09-21）的四承重件（workspaces/sessions 两列/两层文件表/veto）至今零落地、立法不变；但 v13 已从计划态变为 36 项加载序活体，长循环 Phase A + Phase B（workspace_admit stage 36 + workspace_exec 真写盘）把「工作区操作」与「模型看到文件」拉成两条互不相认的可达路径。**结论：R0a 不变量仍是底座、无需推翻，但其接线假设（旧 advance 内接发现 effect、出生 cutoff 盖全程、注册即出境的门先于任何路径出镜）需要 v3 修订**——共 8 项必裁（真写盘≠文件身份、cutoff 世代语义、R0b 五处单源、I-file-5 措辞重写、增列夹具策略、文件事件×goal 指纹、冷启动钩子一次性授权、出境门补课）、12 项迁移难点（5 阻断/7 结构工作量）。报告即 v3 设计文的骨架素材。

## 调查问题（ Symptoms → Questions ）
- Q1: R0a 文件平面的既有设计是什么（可行性 v2 §2.1/§8.1：workspaces + sessions.ws_id/files_cutoff + 两张文件表 + tips + veto + 七不变量 I-file-1..7；v1→v2 的三处 erratum；A6/A7/A12 立法缝；E-DP8-1 偏差）？
- Q2: v13 自 09-22 起步后已交付 20 个 stage + 控制面 P1–P4（stage 17–20）+ 长循环 Phase A（plan_contract/plan_read/plan_arm/loop_driver/workflow_bind/real_chain）。这些落地改变了哪些 R0a 当年依赖的前提（sessions 增列缝、spawn/fork 语义、SQL_LOAD_ORDER、worktree latch、harness/wake、席位预算）？R0a 条文哪些仍然成立、哪些需要 v3 修订？
- Q3: 迁移 repoprompt-ce 文件面（manage_selection/read_file/apply_edits/file_actions/file_search/get_file_tree/get_code_structure/manage_workspaces 等）到 v13 原生栈的难点（难点=技术阻碍）与设计要点（v3 应裁什么）是什么？

## Background / Prior Research

### B1. R0a 定义与沿革（git 考古探针，2026-09-30）

**定义源**：`docs/analysis/repoprompt-native-on-v13-feasibility-v2-2026-09-21.md` §2.1（L58-83）+ §8（L208-221）。R0a = 静态 `workspaces` 表 + `sessions` 增列（`ws_id NOT NULL`、`files_cutoff jsonb {git_head, worktree_id, max_file_epoch}`，spawn/fork 冻结、fork 复制父值、**不加 ws_revision**=D2 裁决）+ 两层文件表（`file_receipts` 只追加 + `workspace_files` 当前指针，D1 裁决）+ `workspace_git_tips`（D5）+ `v13_file_vetoes` 事件折叠 + 发布检查函数 + `ws_scope_changed` 探针（D2：workspaces 作用域列 DML → tools_revision bump）。七不变量 I-file-1..7 见同文 §1（L25-52）。Gate：表约束/不可变/空语料开放世界。

**沿革 commit 链**：
- e85ebcf（09-21）：可行性 v1+v2 同建（v2 取代 v1；v1 三处 erratum=read_file 违 G-ctx1 / workspace_context 近零新件 / R1 锁内行读）。
- f88f1db（09-21）：控制面 R2 修订；v2 尾部追加 I-file-4 收窄勘误（「parse/advance 只读已冻结行」→「零 FS/git IO；库内写仅具名名单」，errata §5.4 + A17）。
- be0c04a（09-21）：E1–E6 对齐修订落 DP1–DP8+v13.1 五份计划；A6/A7 落 DP3 plan（manifest 根六字段+file section）、A12 落 DP8 plan（sessions files_cutoff、D5 fork 冻结公式、G-file-replay 三回放）。
- 69e5ebb + 89f17f7：A12 **立法缝**落代码——`v13/periphery/v13_periphery.sql:41-43,308-310` 注记 + `README.md:79`（「不落列…激活缝随 R0a」）；`spawn_kind` 列（exact_replay/recompute/fresh_fork）+ 三列不可变触发器已落（L44-59）。
- E-DP8-1（A12 立法≠落地）登记于 `docs/reviews/v13-dp8-impl-l4-review-2026-09-23.md:168` 等——**未跟踪文件，从未提交**。
- DP1 plan「sessions 未来增列缝」节（L3213-3226）：登记 ws_id/files_cutoff 两列，明文不进 DP1 M1 DDL；R0a 与 DP1 加载序协调=纯末尾追加。

### B2. HEAD（2f7d515）现状快照（考古探针）

- **`SQL_LOAD_ORDER` = 36 项**：…periphery(14) mgraph(15) mgraph_assembly(16) control(17) spawn(18) fanout(19) triage(20) seam(21) catalog(22) acl(23) observe(24) handoff(25) should_run(26) quota_window(27) attention(28) govern(29) **plan_contract(30) plan_read(31) plan_arm(32) loop_driver(33) workflow_bind(34) real_chain(35) workspace_admit(36)**。
- **sessions 表活体 = 12 列**（pair 复核修正：core 9 列 + manifest 增 2 列 `context_active_revision`/`context_active_artifact`（`v13/manifest/v13_manifest.sql:96-99`）+ periphery `spawn_kind`（`v13_periphery.sql:44`）；全树 grep：**无 ws_id、无 files_cutoff、无 workspaces/file_receipts/workspace_files/workspace_git_tips 表、无 v13_file_vetoes**。
- 控制面 stage 17–19（control/spawn/fanout）：**零 CREATE/ALTER TABLE**；spawn 建 session 只写原 9 列；席位预算=fail-loud 门；worktree=latches 表 + binding artifact（`v13/fanout/v13_fanout.sql:46-146`）；spawn_subsession 工具行 kind='sql'（`v13/spawn/v13_spawn.sql:1756-1760`）。
- **长循环 Phase A 七 commit（33cd565/633f957/649b1f9/0b18d0a/5b805fe/a3db983/ce3101d）全部纯尾部追加**：无一改 sessions schema、无一碰 spawn/fanout/fork/periphery。
- **长循环 Phase B 已开工**：
  - `v13/workspace_admit/`（**stage 36**，commit 2f7d515 2026-09-30）：`workspace_tool_subset` v1 策略行 + `v13_workspace_policy()` + 工作区 effect 打开者（`v13_tool_effect_open`）+ 结果接受（`v13_tool_result_accept`）+ 路径互斥扫描 + 截断校验；tools 闭集 `edit/write/bash/grep/find/ls`（read_only 标签=`find/grep/ls`）。「无文件系统，无 provider，无第二份 advance」。
  - `v13/workspace_exec/`（**不占 SQL_LOAD_ORDER**）：cs-APFS 挂载点真跑 edit/write/bash/grep/find/ls 的驱动器（hdiutil 三标志分离 + Foo/foo 独占创建碰撞 + NFC/NFD 折叠域外）。
  - `v13/read_tools/`（M1 契约、无 SQL）：四口岸 read 等价合同。
- **关键判定（探针）**：R0a 四承重件在 HEAD 一个未落；workspace_admit/exec/read_tools 是长循环工具面新三条腿，复用 effect/ledger 机制但**与 R0a 文件平面零 schema 耦合**——尤其 workspace_exec 真实写盘（edit/write/bash）**不写任何收据/指针、不冻结 content_hash、不推 files_cutoff**，与 I-file-1/3 的关系是 v3 必须裁决的核心张力。

### B3. RP-CE 文件平面机制盘点（探针，2026-09-30；锚=/Users/wxl/Projects/repoprompt-ce）

分层：`RepoPromptDomainRuntime`（28 工具目录/规范/headless 实现）→ `RepoPromptWorkspaceCore`（路径策略）→ `RepoPromptCodeMapCore`（tree-sitter 13 语言）→ app 侧 `WindowTools` providers → `RepoPromptMCP/DirectHeadless*`（无头后端）。

- **manage_selection**：`StoredSelection`={selectedPaths, manualCodemapPaths, slices:[String:[LineRange]], codemapAutoEnabled}，Codable 持久化在 compose tab（WorkspaceModel.swift:125-173）；自动补的 codemap 路径**不落盘**按需重算；8 op（get/add/remove/set/clear/preview/promote/demote）+full/slices/codemap_only（MCPSelectionToolProvider.swift:43-125）；模糊定位=带评分 PathMatcher（fuzzy/suffix/head-trim/根加权，PathLookup/PathMatcher.swift:301-320,2192）；提交后回读 canonical 比对否则 `ArtifactCommitConflict`+一次重试（:144-158,607-703）。
- **read_file**：`WorkspaceExactFileInput.parse`——绝对/`//` 显式根限定（恰一个边界）/\~/ 展开/相对；拒 NUL/拒 `..`（WorkspacePathPolicy.swift:171-207）；literal-first exact；worktree remap=translateInputPath+WorktreeScopeDTO（MCPFileToolProvider.swift:557-560）；已批准外部路径=AgentSupportDirectoryCatalog 白名单+canonical 双路径+symlink+10MB（AgentSupportDirectoryCatalog.swift:43-64）。
- **apply_edits**：rewrite/single/edits[] 三模式互斥；on_missing 仅 rewrite 可 create（显式 `//` 只标识既有文件）；C-style unescape 重试（ApplyEditsEscapeFallback.swift:32-52）；operation_id 仅 correlation 非幂等；postMutationFreshness 重等 ingress；四值可重试失败信封（worktree_scope_unavailable/freshness_timeout/hydrating/route 未解）。
- **file_actions**：create(if_exists)/delete(macOS Trash)/move(选中态随迁)（MCPFileToolProvider.swift:203-282）。
- **file_search**：max_results=50；**48k 字符预算**=max(0,50000-2000) 按行吞入记账溢出即断（:933-1024）。
- **get_file_tree**：renderer 阶梯降级 full→depth3→folders→selected，每档 ~6000 token+每文件夹 100 子项帽（CodeMapExtractor+Snapshots.swift:102-171）。
- **get_code_structure**：13 语言（swift/js/cs/py/c/rs/cpp/go/java/ts/tsx/php/rb），25k 行/1.5M UTF-16 解析帽（CodeMapSyntaxEngine.swift:18-105）；uses/used_by 内部 referencedDefinitions/referrers 改名投影；paths≤256/depth 1..4/size 三档；`_git_data` 别名仅精确、禁模糊/文件夹/codemap/slice，读取需冻结 git review 授权。
- **worktree 选择子**：@current/@main/@main:<branch>/@branch:<name>/@id:<id>/名称/分支/路径；`@wt:<branch>` 显式拒绝（GitRepoTargetResolver.swift:286-315,444-476）。
- **世代/收据/围栏栈（对照基准）**：`DomainRevisionState`(working/saved/dirty 单调整数)每读快照/授权都带（DomainWorkspaceModels.swift:24-40）；codemap `RootEpoch=(rootID,rootLifetimeID)`+7 字段 authority generations 不匹配即 `rootEpochBindingMismatch`；图快照收据 9 字段（WorkspaceCodemapGraphSnapshotModels.swift:9-19）；失效执法点 invalidateModified/Deleted/Renamed/WatcherGap/Checkout（WorkspaceCodemapBindingEngine.swift:1386-1460）；**写围栏** `DomainMutationPathFence`(device,inode)+提交前 revalidate 重开目录 fd（DomainMutationPathFence.swift:4-22,54-79）；journal 状态机 begin→attaching→committing→applied/indeterminateAfterCommit（DomainMutationJournal.swift:120-330）；读工具租约 MCPCodeStructureSettlementRegistry。
- **headless 缺失面（app 专有）**：selection 的 slices/codemap/auto 管理（无头 mutateSelection 只有扁平路径表+6 op）；root-alias 模糊解析（无头只做绝对/单根/多根存在性唯一）；worktree 绑定投影、_git_data 别名、file_tree auto-trim（无头只有 maxDepth 0..32 clamp）、file_search 48k 预算（无头 max 1..1000）、codemap 图扩展（无头单文件签名 backend:"headless"）。



## Investigator Findings

调查日期 2026-09-30，锚 = HEAD `2f7d515` 之后工作区（只读；本节省 pair 追加）。加载权威是 `v13/load.py` 不是 `v8/load.py`（见与 B2 的矛盾）。

### 0. 与 B1–B3 背景的矛盾（先登记）

| 背景声称 | HEAD 活体 | 判定 |
|---|---|---|
| B2：`SQL_LOAD_ORDER` 在 `v8/load.py`、36 项 | 36 项在 `v13/load.py:17-54`（`workspace_admit` = stage 36）。`v8/load.py:18-122` 只到 v8 closeout，不含 v13 | **REFUTED**（条目数对、文件错） |
| B2：sessions = 9 列 + `spawn_kind` | 核心 9 列 `v13/schema/v13_core.sql:12-26`；manifest 再加 `context_active_revision` / `context_active_artifact`（`v13/manifest/v13_manifest.sql:96-99`）；periphery 加 `spawn_kind`（`v13/periphery/v13_periphery.sql:44-45`）。活体 12 列 | **PARTIAL** |
| B2：长循环 Phase A 纯尾部追加、不改 spawn/fork | `v13_advance` 被 plan_arm 整函替换（stage 32）；fork 活体是 fanout 替换件。sessions DDL 确实未改 | **CONFIRMED**（schema）/ **PARTIAL**（函数体） |
| 迁移策略文「v13/ 零 `listdir`」 | `v13/workspace_exec/adapter.py:218-232` `_list_dir` 调 `os.listdir` | **REFUTED**（该文写于 workspace_exec 之前） |

---

### 1. B1 五出口判定序活体 — CONFIRMED

**出口名与优先级（驱动器，不是 SQL）**

`v13/loop_driver/driver.py:27-28` 钉死五词 `wait | user_action | provider | terminal | stopping`；非出口词 `repair | replan | capability_adapter_handoff` 一律折叠为 `wait`（`collapse_exit_word` `:77-80`）。

`decide_exit` `:95-114` 判定序与 README `:60-61` 一致：

1. `session_status ∈ {completed,failed,cancelled}` → `terminal`（`TERMINAL_STATUS` `:60`）
2. `stop_requested ∧ stop_authorized` → `stopping`
3. `needs_human ∨ dispatch=='operator'` → `user_action`
4. 上游非出口词 → `wait`（只压 provider，不压 human）
5. wait 条件：`not plan_gate` / `not should_run` / `hint ∈ {wait,dont_notify}` / `human_pending` → `wait`
6. `dispatch=='provider' ∧ hint=='run_now' ∧ plan_gate ∧ should_run` → `provider`
7. 其余 → `wait`

`loop_driver` SQL（`v13/loop_driver/v13_loop_driver.sql:1-3,5`）只交 C7 投影 `v13_harness_result_project`，**不**替换 `v13_advance`。

**needs_human 直读 fold**

`driver.py:268-273`：`EXISTS (SELECT 1 FROM v13_plan_todo_fold(v13_plan_map_root(sid)) WHERE task_class IN ('user_gate','user_action','blocker') AND status IN ('pending','runnable','blocked'))`。不读 `v13_selected_todo`。另有独立 `human_pending` `:276-279`（`effects.kind='human' AND status IN ('ready','claimed')`），在判定序里只进入 wait 条件，排在 user_action 之后。

**新 waiting 的 tool effect 能否挡住同拍 LLM effect — CONFIRMED 能挡住**

活体 `v13_advance` 是 `v13/plan_arm/v13_plan_arm.sql:332` 起的 `CREATE OR REPLACE`（stage 32；loop_driver 明文不换体）。主闸 `:399-402`：

```
IF EXISTS (… effects … status IN ('ready','claimed')) THEN
  UPDATE sessions SET status='waiting'; RETURN 'waiting';
END IF;
```

此闸在 `v13_plan_advance_prefix`（可 enqueue `llm`/`read_file_py`）和 `WHEN 'llm'`/`WHEN 'tool'`（`:749-788`）之前。因此未来 `corpus_bootstrap` 只要以 `ready`/`claimed` 挂在本 session，同拍不会再建 LLM effect。

注意与原 `advance.sql` ① 的差：`v13/loop/advance.sql:261-264` 的阻塞集含 `'unknown'`；活体主闸 `:399-402` **不含** `unknown`。`unknown` 走 `v13_raise_unknown_wall`（`v13/control/v13_control.sql:227-246`）把 session 打成 `blocked_unknown`。`ux_v13_effects_single_active`（`v13/schema/v13_core.sql:128-129`）只覆盖 `ready|claimed`，不含 unknown。

**重入 / 幂等 / claim_update_frozen_once**

- Effect 身份：`v13_enqueue_effect` 活体 `v13/control/v13_control.sql:902-938`：`v13_effect_id(sid,kind,request)`；已有 `succeeded|ready|claimed` 直接返回同 id；`failed|cancelled` 在 attempt cap 内复位 `ready`；`unknown` RAISE「resolve explicitly」。
- 驱动器 claim：`driver.py:360-366` 单条 `UPDATE effects SET status='claimed', attempt_no=attempt_no+1, fence=fence+1 … WHERE status='ready' RETURNING`；领取失败 rollback、不 complete（`:368-370`）。
- `claim_update_frozen_once`：`v13/loop_driver/test_loop_driver.py:277-280` 静态计数该 UPDATE 字面在 `driver.py` 恰好 1 次。
- workspace opener 另有 replay：`v13_tool_effect_open` 对已 `succeeded`/`claimed` 同身份行返回 `replayed=true`（`v13/workspace_admit/v13_workspace_admit.sql:413-437`），不递增 attempt/fence。

---

### 2. enqueue 所有权现状 — CONFIRMED

**谁建 effect（stage 36 加载后）**

| 层 | 文件 | 角色 |
|---|---|---|
| 被覆盖的原稿 | `v13/loop/advance.sql:197` `CREATE FUNCTION v13_advance` | 历史；加载后被替换 |
| 控制面替换 | `v13/control/v13_control.sql:1150` | 中间态 |
| **活体** | `v13/plan_arm/v13_plan_arm.sql:332-804` | stage 32 最后一次 `CREATE OR REPLACE v13_advance` |
| 驱动器 | `v13/loop_driver/v13_loop_driver.sql:2-3`；README B6 enqueue 行 | **禁止** INSERT effect；只准调 `v13_advance` |
| opener | `v13_tool_effect_open` `:479` | 工作区六工具走这条，不走 advance ④ |

活体 advance 建账点：

- `v13_plan_advance_prefix`（`:120+`）：子会话在已有 `workflow/pointer` 且尚无 `read_file_py` 时 enqueue `read_file_py`（`:152-158`）；`dispatch='provider'` → `llm`（`:297-301`）；`dispatch='operator'` → `human`（`:303-305`）。前缀若返回非 NULL，advance `:445-448` 直接 RETURN，不到 CASE。
- `WHEN 'tool'` `:749-781`：从信封 `tools_catalog` 取 `enabled=true` 的 handler，`v13_enqueue_effect` + `v13_send_work`，session → `waiting`。
- `WHEN 'llm'` `:782-786`：同样 enqueue + send_work。
- `WHEN 'sql'` `:707-748`：同事务 EXECUTE handler，**直接 INSERT 终态 effect**（不走 enqueue 队列）。

臂派发 guard：`:280-294` 有未终态 binding 则 `waiting`；`:292-294` `NOT plan_gate OR NOT should_run` → NULL；`:296-297` `dispatch='none'` → NULL。幂等靠 `v13_enqueue_effect` + `v13_plan_apply_id('bind:…')` 写者。返回：`'waiting'` / `NULL`（前缀未接管）/ advance 自身 `'stale'|'terminal'|'progressed'|'waiting'`。

**R1a `corpus_bootstrap` 钩子该落哪一层**

I-file-7 要求：`bootstrap_done=false` 且名字表空 → 建 `corpus_bootstrap(enabled=false, handler SQL 字面量, 不走模型 choice)` 并 `waiting`，**不得同时建 LLM**。

| 候选 | 落点 | 利 | 弊 |
|---|---|---|---|
| **A. 活体 advance、主闸之后 / 前缀之前**（`plan_arm.sql:402` 与 `:445` 之间） | 等价于原 ① 通过后、原 ④ 之前。原编号 **⑤ 是预算**（`advance.sql:330`），**不是**这个缝 | 已有 ready/claimed 仍先 waiting；前缀的 `llm`/`read_file_py` 还没跑；`enabled=false` 本来就不会进 `WHEN 'tool'` 的 catalog 过滤（`:751-752`） | 必须改 plan_arm 这份 advance 副本（后续再 REPLACE 要跟着抄）；bootstrap 条件读的是尚未存在的 ws/名字表 |
| **B. `v13_plan_advance_prefix` 臂** | 与现有 `read_file_py` 冷启动（`:152-158`）同形 | 前缀已会「非模型 choice 的 tool enqueue」；返回 `waiting` 能短路 CASE | 把文件平面冷启动绑进 plan 臂；无 plan 的 session（`plan_gate` 假时前缀 `:292` 直接 NULL）**走不到**这臂，冷启动会漏 |
| **C. loop_driver** | `serve`/`run_turn` 里 INSERT | 无 | B6 明文禁驱动器 INSERT effect（README `:29`；`ALLOWED_CONTROL_SQL` 无 enqueue）。**否决** |

**建议（代码而非想象）**：钩子落 **A**（活体 advance 主闸后、`v13_plan_advance_prefix` 前）。不要落原 ⑤ 预算槽——预算在活体里已拆散，且 ⑤ 本就在 ③④ 之前、语义是 cycle cap 不是冷启动。C 与 B6 冲突。B 会漏无 plan 的根会话。

---

### 3. workspace_admit 合同活体 — CONFIRMED

**`workspace_tool_subset` v1 schema**（`v13/workspace_admit/v13_workspace_admit.sql:5-17` 种子；canonical 校验 `:55-73`）：

闭集键（排序后）：`argv_len_cap=4`，`bash_verbs=[cp,mkdir,mv,rm]`，`find_depth_cap=4`，`labels.read_only.admits=[find,grep,ls]`，`labels.workspace_edit.admits=[bash,edit,find,grep,ls,write]`，`paths_cap=4`，`result_text_cap_bytes=51200`，`schema_version=1`，`tool_open_attempts=2`。漂移或不 active → 装载 RAISE，不 UPDATE（`:27-28`）。

**执法点**

- `v13_tool_effect_open` `:80-500`：label ∈ `{read_only,workspace_edit}`；四 read 名 + `spawn_subsession` → `not_this_opener`（`:212-215`）；六工具闭集（`:217-218`）；`labels[label].admits` 成员（`:220-224`）；声明 `paths` 规范化 + 互斥扫描；然后 `v13_enqueue_effect` + `status='claimed'`, `lease_until=infinity`（`:479-485`）。不调 advance/complete。
- `v13_tool_result_accept` `:502-605`：先锁 session 再锁 effect；只接受 `succeeded|failed`（`:540`，**无 unknown**）；结果八键闭集；超帽 RAISE 不截断；`error_token=ambiguous` RAISE（`:584-585`）；最后 5 参 `v13_complete`（`:599-600`）。

**stage 36 后 `v13_complete` 最终定义 — CONFIRMED 在 acl，不是 core/control**

加载链（`v13/load.py`）：core(1) CREATE 5 参 → control(17) REPLACE → spawn(18) → fanout(19) → seam(21) REPLACE 5 参 → **acl(23)** 定义 6 参体 `v13/acl/v13_acl.sql:245-457` 并把 5 参改成包装 `RETURN v13_complete(NULL::uuid, …)`（`:459-470`）。其后 observe…workspace_admit **不再** REPLACE complete。因此 stage 36 活体 = acl 6 参体 + 5 参包装。

成功结算仍追加本 turn 判断窗事件（沿 origin_user_seq）：

- `effect_done` `:413-414`
- **tool 成功 → `tool/result`** `:415-418`（`payload.result` = 传入 jsonb 原样）
- llm 成功 → `llm/message`；若有 `tool_calls` 才追加 `tool/call`（`:424-427`）
- opener/accept **不写** `tool/call`

失败结算：`v13_complete` 对 `failed` 只写 `effect_done`，不写 `tool/result`。accept 仍把 `p_result` 写入 `effects.result`。

**路径互斥保护的是声明路径，不是实际访问对象 — CONFIRMED**

扫描 `:446-478`：对本请求 `v_paths`（来自 `p_request.paths`）与库内 `kind='tool' AND status IN ('ready','claimed','unknown') AND request ? 'workspace_root'` 行的 `request.paths` 做前缀段比对（拼 `workspace_root + path`）。零 FS、零 inode。payload 里实际读写的对象必须是声明 `paths` 的成员（write/edit/grep/ls/find 的 `payload.path = ANY(paths)`；bash argv[2+] 同），但互斥比较的仍是声明数组，不是打开后的 `st_dev+st_ino`。跨 session 扫描（README：因 `ux_v13_effects_single_active` 同会话不能两条 ready/claimed）。

---

### 4. workspace_exec 写后失败分类 — CONFIRMED

无 SQL、不占 `SQL_LOAD_ORDER`（README `:3`）。驱动只调三个 admit 函数（`driver.py:1,112-131`）。

**分类矩阵**

| 结局 | 机制 | 是否调 accept | effect 终态 |
|---|---|---|---|
| 读/写前可判定失败（hash_mismatch / missing / exists / not_a_file / not_a_dir / edit_not_unique / bad_utf8 / io_error / escape） | adapter `WorkerFail`/`Escape` → `driver._failed` `:133-147` → `status='failed'` | 是 | `failed` |
| 写盘后崩溃 / rename 失败 / unlink 失败 / `fail_temp_unlink` | `AmbiguousOutcome`（`adapter.py:184-192,212-215,213-216,483-487,536-537`）或裸 `Exception`（`driver.py:86-88`） | **否** | 保持 **`claimed`** |
| `error_token=ambiguous` | accept 直接 RAISE（admit `:584-585`） | 调了也会炸 | 不结算 |

`v13_tool_result_accept` 的 `p_status` 闭集是 `succeeded|failed`（`:540`），**没有 unknown 入口**。驱动从不调用 `v13_complete(..., 'unknown')`，也从不调用 `v13_resolve_unknown`（活体 `v13/seam/v13_seam.sql:590` 替换 control `:831`）。写后不确定 = 行留 `claimed` + 租约 infinity（opener `:482-484`）；README `:3`「崩溃 claimed 行留给 G4」。这与 I-file-1/3「写盘必有收据」的张力仍在：exec **不写** file_receipts / workspace_files / files_cutoff。

**stdout/stderr 是否进模型可见结果 — CONFIRMED 否**

bash 不是 shell（`adapter.py:1,431-446`）：进程内 `mkdir/rm/cp/mv`。成功结果 `text` 对 write/edit 是 `"{path} {nbytes} {sha256}"`（`:234-236`）；bash 成功经常是空串（`:469,488,515,539`）。grep/find/ls 的 `text` 是匹配行/路径/目录名，受 `result_text_cap_bytes` 截断（`:425-428`）。没有 stdout/stderr 字段。失败 `text=""`，模型可见面是 accept 写入的 jsonb（`ok/error_token/text/...`），经 complete 的 `tool/result`。

**修改路径回传 / 收据**

成功 summary 把声明 `path` 放进 `text`；没有独立 `modified_paths[]`，没有 content_hash 列，没有 file_receipts 行。`replayed && succeeded` 不执行、不接受（`driver.py:67-68`）。

读失败 vs 写失败：读侧（grep 打开、hash 预检、edit 读旧文）全部 `WorkerFail` → **failed**。写侧 install/rename/unlink 失败走 **AmbiguousOutcome → 不结算 claimed**，不是 failed，更不是 unknown。

---

### 5. session 出生路径全清单 — CONFIRMED

**生产 SQL INSERT（v13 `*.sql` 仅 3 处真出生 + 1 处负向自检）**

| # | 函数 | 文件:行 | 列清单 |
|---|---|---|---|
| 1 | `v13_open_session` | `v13/spawn/v13_spawn.sql:285-335` INSERT `:311-313` | `status, turn_no, next_seq, route_policy_name, route_policy_version`（无 parent、无 spawn_kind、无 ws_id） |
| 2 | `v13_fork` 原稿 | `v13/periphery/v13_periphery.sql:311-361` INSERT `:357-360` | `status, route_policy_name, route_policy_version, parent_session_id, parent_cutoff_seq, spawn_kind` |
| 3 | **活体 `v13_fork`** | `v13/fanout/v13_fanout.sql:968-972`（stage 19 REPLACE，同列） | 同上 |
| 4 | spawn 负向自检 | `v13/spawn/v13_spawn.sql:1774` | `INSERT INTO sessions (session_id)` 期望 **失败**（`v13_route` 角色） |

`v13_spawn_subsession`（`:318`）**自己不 INSERT sessions**：`:438` `v_child := v13_fork(p_sid, v_cutoff, 'fresh_fork', NULL)`，再 `UPDATE status='ready'` 并写 `spawn/task`（`:439-442`）。

身份入口：`v13_plan_commit_entry` → `v13_open_session`（`v13/plan_contract/v13_plan_contract.sql:176`）。loop_driver 闭集不含 open_session。`v13/real_chain/` 无直接 INSERT。

**增列 `ws_id NOT NULL` + `files_cutoff` 后必改的函数**：`v13_open_session`、活体 `v13_fork`（fanout；periphery 原稿仍加载但随后被替换）、以及任何依赖 fork 列不可变触发器的测试夹具。fork 复制父 `files_cutoff` 是 R0a 立法（periphery 已留缝 `v13_periphery.sql:41-43,308-310`），今天列不存在。open_session 必须有 ws 绑定规则（spec 目前只许 `route_policy_name|version`，`:293-295`）。

**会断的测试（生产路径以外，夹具裸 INSERT）**：全树 `INSERT INTO sessions` 出现在大量 `v13/**/test_*.py`。典型只写 `(session_id)` 的：schema/resolve/loop/envelope/manifest/chunks/recall/filter/memory/economy/summary/periphery/spawn/control/mgraph/mgraph_assembly/characterize 等。写 `parent_session_id`/`spawn_kind` 但不写 ws 的：acl/observe/handoff/attention/govern/plan_contract/plan_read/workflow_bind。`ws_id NOT NULL` 无 DEFAULT 时这些夹具全部 FAIL。v8/v12 的 sessions 是另一张表（`workspace_id` 列），不在 v13 加载链上。

活体 sessions 列（stage 36）：core 9 列 + manifest 2 列 + spawn_kind = **12**。无 `ws_id`、无 `files_cutoff`。

---

### 6. C1 workflow_template v1 冻结面 — CONFIRMED

政策行：`v13/workflow_bind/v13_workflow_bind.sql:10-28`，`name=workflow_template` version=1 active。canonical 键闭集（`:51-52`）：`allowed_tools, chain, labels, layers, parent_tools, schema_version`。

**冻结了什么**

- 四层非空文本 `layers.{assertion,assembly,judgment,workflow}`；`v13_workflow_resolve` 只返回这四键（`:82-87`），不拼 SYSTEM_PROMPT。
- `labels = ["read_only"]`（解析器拒其他标签）。
- `allowed_tools = [read_pi, read_file_swift, read_file_py, read_duck]`（真链驱动器允许名单，**不是** tools 目录交付）。
- `parent_tools = [spawn_subsession]`。
- `chain = first_real_chain`。

**没冻结什么**

- 工具子集（README：子集在 Phase B；本行不碰 `workspace_tool_subset`）。
- `tools.enabled` / 目录行（`no_tool_flag_update`）。
- explore 的 RAISE。
- spawn SQL（开工只重读；子会话写 `spawn/task` 不是 `user/message`，`v13/spawn/v13_spawn.sql:441`）。
- plan canonical / 父事件正文（C3 pointer 载荷闭集不含这些）。

**与 spawn 的关系**：`parent_tools` 把 `spawn_subsession` 交给活体 spawn 臂，workflow_bind 不调用 spawn、不调用 `v13_child_pointer`（生产调用者是将来的 `real_chain/chain.py`）。plan_arm 前缀在子会话已有 pointer 时 enqueue `read_file_py`（见 §2），那是 plan 臂行为，不是 C1 冻结面。

---

### 7. visible_tools 现状 — CONFIRMED（单源不存在；并排过滤）

**`v13_visible_tools` / `v13_wb_visible_tools`：v13 SQL 零命中**（与迁移策略文一致）。I-file-5 未落地。

**needed 怎么读工具集**

活体 `v13_needed_judgments` = `v13/envelope/v13_envelope.sql:334-336` DROP+CREATE（resolve 的早期定义被覆盖）。tool Choice 候选 `:422-426`：

```
FROM tools WHERE enabled AND tools.kind IN ('sql','tool')
```

只看 `tools.enabled`，不看 `workspace_tool_subset`，不看 `workflow_template.allowed_tools`。

**advance ④ 怎么读**

原稿注释在 `advance.sql:384-398`：`v13_route` + 信封 `tools_catalog` 且 `(t->>'enabled')::boolean`。活体同一过滤在 `plan_arm.sql:715-717`（sql）和 `:751-752`（tool）。`v13_tools_catalog_frozen` 活体是 catalog 替换件（`v13/catalog/v13_catalog.sql:3-77`）：**全表** `FROM tools ORDER BY name`，每条带 `enabled` 布尔，disabled sql 行透传不校验 handler。信封冻的是全集+标志，advance 再滤 enabled。

**`workspace_tool_subset` vs `tools.enabled`：并排，不是单源**

- `tools.enabled`：needed / catalog / advance ④。
- `workspace_tool_subset`：仅 `v13_workspace_policy` + opener 的 label.admits。零 `tools` DML（admit README）。
- `workflow_template.allowed_tools`：真链允许名单，另一份。

三份过滤器并存。edit/write/bash 要被 opener 用，但若 `enabled=false` 则 needed 不会把它们放进 tool Choice——这正是 R1a「enabled=false、不走模型 choice」能寄生的现状。

**R0b 单源要动几处（下限）**

DP1 计划已点名的换体点今天仍在：

1. `v13_needed_judgments` tool map（`envelope.sql:422-426`）
2. 信封 `tools_catalog` 物化（`v13_tools_catalog_frozen`，catalog.sql + 各 snapshot 组装：envelope/filter/recall/manifest）
3. 活体 advance ④ enabled 谓词（`plan_arm.sql:715-717,751-752`；历史副本还在 govern/should_run/triage/spawn/fanout/control/advance.sql，加载后以 plan_arm 为准）
4. opener 的 `labels.*.admits`（否则 I-file-5 与 C2 子集继续并列）
5. `workflow_template.allowed_tools` 是否并入同一函数（C1 声称「标签不选择端点」）

`v13_canonical_state` 仍是 resolve 首定义、无后续 REPLACE（`v13/resolve/v13_resolve.sql:17,39`：`FROM tools WHERE enabled`）。R0b 换体清单应加上这一处。不含 loop_driver（它不读工具目录建账）。


## Investigation Log

| 阶段 | 手段 | 结果 |
|---|---|---|
| Phase 1.5 | 2×haiku explore（RP-CE 盘点 / pg-agent 考古） | B1-B3 落盘；发现 Phase B 已开工（workspace_admit=stage 36） |
| Phase 2 | context_builder + codex oracle（gpt-6-astra-fast-xhigh） | 初判：R0a 未被取代但接入点已变；列出待核实清单 |
| Phase 3 | pair（grok-4.6 effort=high） | 七项全部 CONFIRMED，file:line 齐备；纠正 sessions=12 列 |
| 抽查 | 主会话 grep 复核 | 活体 advance=plan_arm:332（33-36 无替换）✓；活体 complete=acl:245/459+tool/result:416 ✓；manifest 两列 ✓ |
| Phase 4 | 双车道 oracle（codex + grok-4.7） | 收敛：钩子落 A 槽；I-file-5 措辞重写；cutoff 世代语义必裁；分歧 2 处登记（见 Recommendations 注） |

## Root Cause（对齐差距结论）

**总判定：R0a 的七不变量与两层收据数据模型没有被长循环取代，仍是文件身份与可见性的必要底座；但 R0a 当年假设的接线位置（「在旧 advance 内接上发现 effect」）已经不足。** 长循环升级把 v13 从「DP1-DP8 计划态」变成 36 项加载序的活体，并且 Phase B 已经提供了**真实文件操作入口**——「工作区操作」与「模型看到文件」今天是两条实际可达、互不相认的路径。v3 的核心任务 = 闭合两条路径之间的授权、收据、发布与 replay 接缝，而不是另建循环或照搬 RP-CE 工具包装。

### 逐件对齐判定（合并双车道 oracle，证据锚=Investigator Findings）

| R0a/I-file 承重件 | 判定 | 对齐结论 |
|---|---|---|
| I-file-4 事务边界（零 FS/git IO，库内写仅具名名单） | ✅ | workspace_exec 在 claim/complete 事务外跑 FS，与勘误后措辞相容；应纳入「事务外 effect worker」清单 |
| I-file-2 开放世界 | ✅ | 仍成立（needed 今天不发 file 存在性 Noul）；落地时闸仍是「bootstrap_done=false 期间计数=0」 |
| workspace_git_tips | ✅/🔧 | 表设计仍成立；与 worktree latch/binding artifact 不是同一合同，v3 写明 R0a 只立法 tips |
| I-file-6 三种群+veto | ✅/⚠️ | 仍无载体也无违例；但 find/grep/ls 不知 population 不读 veto——工作区路径准入≠文件语料准入，两道门 v3 必须分立 |
| v13_file_vetoes/ws_scope_changed 探针 | ✅/⚠️ | 七键探针维持；新张力：文件事件会进 v13_goal_fingerprint 排除名单外→挡 v13_goal_resume（见阻断点 5） |
| 静态 workspaces 表 | 🔧 | 必要基础；但 tool_scope 今天落下去=第四份过滤器；write_grant 留列与 workspace_tool_subset 标签并排需消歧 |
| sessions.ws_id | ⚠️ | sessions 活体 12 列无 ws_id；生产出生仅 open_session（spawn:311-313）与活体 fork（fanout:968-972）两处；~20 个 stage 裸 INSERT(session_id) 夹具会断 |
| sessions.files_cutoff | ⚠️/🔧 | 出生冻结语义仍立，但长循环根跨 tick 不 re-fork：出生天花板盖不住后续注册，世代规则必裁（Q2-②） |
| file_receipts+workspace_files 两层 | ⚠️ | 仍是身份载体；但 Phase B 成功写入零收据：edit/write 的 "{path} {nbytes} {sha256}" 只是 tool/result 文本，不得升格为收据 |
| I-file-1 身份冻结 | ⚠️ | 立法仍是目标；活体写路径不满足；spawn_kind 三值已在而 files_cutoff 未冻，G-file-replay 尚不能声称 |
| I-file-3 注册即出境 | ⚠️（最大张力） | grep 正文/find/ls 名字经普通 tool/result 直出判断窗（acl:415-418），无 secret 扫描无 veto——路径在注册门之前已出镜；v3 写明这是 Phase B 已知出境 + R1 秘密门不得把历史 tool/result 扫进 chunks/manifest |
| I-file-5 单源可见性 | 🔧 | 原句不足：现实=tools.enabled（needed/catalog/advance④/canonical_state 四读点）+workspace_tool_subset（opener）+workflow_template.allowed_tools（chain）三份并排；且 enabled=false 系统 effect 已有先例（read_file_py 前缀）——须拆「模型可见集」与「系统 effect 授权」两句 |
| I-file-7 冷启动 | 🔧/⚠️ | 不变量成立且活体主闸（plan_arm:399-402）天然支持 ready/claimed 挡同拍 LLM；钩子落 A 槽（主闸后/前缀前，只对根）；前缀臂会漏无 plan 根，loop_driver 被 B6 禁；**但这次钩子=再一次 REPLACE plan_arm 的 advance，而 Phase B/C/D 把「再替换 advance」写成停点——v3 必须单独一次性授权** |
| 发布检查函数 | 🔧 | 仍要；挂活体 advance 具名函数、根锁内翻标志零 FS；不进 opener 事务、不造第二份 complete |

## Recommendations（v3 文件平面设计要点）

### A. v3 必裁项（建议方向+置信度；双车道分歧处标注）

1. **真写盘 vs I-file-1/3：物理操作≠文件身份（高）**。六工具成功文本维持 Phase B 合同不升格收据，禁止从 text 解析 sha256 INSERT 收据；R0a 预留「结算缝」（具名函数、先锁 session 再锁 effect、仅 lease_owner=v13_workspace_opener 且已成功时允许写收据），R0a 不实现写；ambiguous 行保持 claimed+infinity 留 G4，不补收据不标 unknown（accept 闭集 succeeded|failed 无 unknown 入口）。produced_by=effect_id 作审计关联；**语料分型分歧**：codex 主张区分 provenance 与 population（agent 对既有源码的 edit 更像 dirty 工作文件，一律 generated 会废掉下一轮召回），grok 主张按可行性 v2 字面（produced_by 非空默认 corpus='generated' 不进源 IDF）——v3 必须显式裁决，倾向 codex 的分型（否则长循环编码代理自食其果）。
2. **files_cutoff 世代语义（中高）**。原则：会话行上的 files_cutoff 一次写入永不 UPDATE，fork 复制父值；corpus_epoch/git_tips 在 workspace 上前进；根会话跨 tick 要看新世代时不改根行——新可见集绑定在新计划世代或新子 fork 出生快照上（**载体二选一留给 R0a 开工裁**：新 plan/committed 上的天花板声明 vs fresh_fork 出生抄当时 tip）；exact=replay 冻结 hash；recompute=新冻结快照不改历史；fresh_fork=可取新发布水位（修订「fork 复制父 cutoff」对 fresh_fork 的适用性）。
3. **R0b 合并顺序（高）**。R0a 先行（workspaces+可空 ws_id，无可见性函数）→ v13_visible_tools(p_sid) 只替换模型可见读点（needed/canonical_state/catalog_frozen/advance④，未绑 ws 时 tool_scope 合取为真、已绑且空才 fail-closed）→ opener 继续只读 workspace_tool_subset（标签准入，不并进模型函数）→ allowed_tools 保持真链名单+加断言 ⊆ visible_tools 输出。换体下限 5 处（见 Investigator Findings §7）。
4. **I-file-5 措辞重写（高）**。拆两句：①模型可见/可调用工具只来自唯一授权解析；②系统内部 effect 不进模型 choice，由具名 SQL 派发闭集+guard+独立 gate 授权。enabled=false 只说明不向模型开放，不足以授权或禁止系统 enqueue。
5. **增列与夹具策略（高）**。列加在 R0a 新阶段表尾 ALTER（不改 stage 1-36 文件字节），ws_id/files_cutoff 无哨兵 DEFAULT；同一新阶段 REPLACE v13_open_session 与活体 fork（新行必须带 ws_id；files_cutoff 出生写入并入 fork 不可变触发器列清单，守卫函数在新阶段 CREATE OR REPLACE 不改 periphery 文件）；全链新测试自传 workspace；**终态分歧**：codex 主张最终收敛 NOT NULL（可空→确定性回填→加约束三步，存量不可归属行 fail-closed），grok 主张 R0a 期保持可空+函数强制——可合并为「R0a 可空+函数必填，NOT NULL 收敛作为 R0a 内部 gate 或紧随其后的一次性迁移」，不设语义不明的生产 DEFAULT。
6. **文件事件 vs goal 指纹（高，grok 新发现）**。file_select/file_deselect/ws_scope_changed 写根流会改 v13_goal_fingerprint→挡 v13_goal_resume；R0a 开工前二选一：事件上根流且接受 resume 受阻，或一次已审核的指纹排除名单替换；禁止 v3 直接改 govern 排除名单。
7. **冷启动钩子的一次性授权（高，grok 新发现）**。授权仅一次、仅 plan_arm 加载后的那份 advance、仅增加对具名函数调用（根上、主闸后 plan_arm:402、前缀前 :445，入队 corpus_bootstrap enabled=false handler SQL 字面量；bootstrap 已成功后的下一拍 advance 调发布检查）。不改 spawn 臂/收据臂/WHEN 'tool' 内部；做不到就停。Phase B 真链的子会话 read_file_py 前缀路径不受影响（闭合摘录≠空名字表冷启动）。
8. **出境门补课（高）**。在登记门存在前，树/搜索投影只读已冻结指针；新发现类结果只许摘要+计数，路径只进收据；R1 秘密门不得把历史 tool/result 扫进 chunks/manifest。

### B. RP-CE 功能迁移难点排序（阻断>结构>工作量）

1. 【阻断】登记门缺失而路径已出镜（file_search/get_file_tree/manage_selection 的模型可见结果不能再走全文 tool/result；I-file-3）
2. 【阻断】冷启动钩子×「禁止再替换 advance」的一次性授权（Q2-7；树/搜索/注册冷启动全挂这颗钩子）
3. 【阻断】三份可见性过滤器并存（R0b 合并前，任何新工具名同时撞「模型选不中」+「opener 拒」两套门；read 四名已被 opener 判 not_this_opener，与 plan 臂 read_file_py 前缀是两条读路径）
4. 【阻断】session 出生×cutoff 不可变（manage_workspaces 静态绑定要换 open/fork；长寿根无世代载体前 get_file_tree SQL 投影无稳定世代）
5. 【阻断】指纹吃进新事件（veto 事件卡 goal resume；规划态已可证明）
6. 【结构】写路径无 unknown 无收据（accept 只收 succeeded|failed；Phase B edit=单一唯一匹配/write=整文件/bash=进程内 mkdir/rm/cp/mv ≠ RP-CE 三模式 edits/Trash/选中态随迁；F20/F28 不迁 grant/journal；结算缝+G4 前不把六名字包装成 apply_edits/file_actions）
7. 【结构】路径身份（声明字符串前缀互斥 vs RP-CE PathMatcher fuzzy/suffix/~/展开/worktree remap——后者不进注册键；身份=规范相对路径+content_hash）
8. 【结构】file_search 名字占用（R1 search_hits 账本已占逻辑名；自由字符串另裁前只许系统入队；RP-CE 48k 预算/ICU 与 v13 51200 帽/max_hits≤200 不同合同；物理引擎版本化 worker:file_search_*_v1）
9. 【结构】get_file_tree vs 已有 ls（树文本进 tool/result=已被否决的环上列目录；投影在 R6，full_tree 默认关；ls 是一层名字可截断，阶梯降级不同）
10. 【结构】read_file 双平面（四口岸 headless 窄合同已在；工作区读继续走 plan 臂前缀或新系统 effect 读已注册 hash；窗口版 10MB/选区/offset 不并进 opener 六工具）
11. 【工作量】get_code_structure（S4 门=R6 三 gate 绿；ce 内一次性 executable 链 CodeMapCore，13 语言/25k 行帽/uses-used_by 不在 pg-agent 重写；不加宽 read_duck 冒充）
12. 【结构·后置】manage_workspaces 动态半边（switch/create/hide、@current/@main/@branch 选择子、动态三表按可行性 v2 §6 后置）

### C. v3 明确不裁（只登记缝，防过度设计）

新世代载体二选一（Q2-2）；指纹排除名单是否纳文件事件（Q2-6）；receipt stat_* 键集/skip_reason 扩展/白皮书清单/prior_cap 数值；秘密扫描器与 deny glob 词表；full_tree 策略行形状与 p95 测量脚本；file_search 物理引擎与 golden；CodeMap --version 四件套/EditCore 拆分/write_grant 执法时点；结算缝函数名（只要求「具名、锁序同 accept、R0a 不写盘」）；动态三表放行数字；Phase D 第二路径谓词/global_concurrency/not_single_tree 去留；不把 files_cutoff 塞进 Phase A canonical 闭集、不把文件缺口塞进 B4 gap_kind、不把选择集做成 todo。

已裁不重开：两层收据表、不加 ws_revision、探针七键、读盘非 sql 快路、veto 单源、enabled=false 系统冷启动、F20/F28 不建 grant/journal、不建 v13_agent_run、环上列目录不进模型上下文、explore 维持 RAISE、bash 非系统 shell。

## Preventive Measures

- **不把计划当运行时**：Phase C/D（G4 恢复、监督进程、公平领用）未进加载序；不得把「崩溃 claimed 行留给 G4」写成「已有 unknown 恢复」。
- **不把摘要当收据**：tool/result 文本、sha256 字符串、路径列表不是文件身份/授权/manifest；操作_id 非幂等键。
- **新端口四问护栏沿用**（09-27 策略）：谁 enqueue/params 是否闭合/结果算不算身份/崩溃进 failed 还是 unknown，缺一不开工。
- **v3 收口句**（双车道一致）：R0a 七不变量与数据模型仍是底座，但长循环与 Phase B 已把「工作区操作」和「模型看到文件」拉成两条实际可达路径；v3 必须先闭合两路径间的授权、收据、发布与 replay 接缝，再逐项承接 RP-CE 功能。
- **里程碑纪律**：R0a 仍是下一正式里程碑（顺序 R0a→R0b→R1a→R1b→R1c→R6 不动）；v3 是设计修订不是新范围；一刀一提交、SQL 只尾部追加。
