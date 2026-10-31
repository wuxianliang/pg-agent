# v24 Tool/Plugin ABI W6：Node `list` + `search` 收口 Deep Plan

日期：2026-10-31。状态：计划（未执行）。基线：`main` @ `82e5440`（"v24: close out Python read plugin ABI"；W5 已提交，9 files +1579 −80）。scope audit 的钉住点仍为 `c8c4bd0`。本计划是 design §10 M3 在 `list`/`search` 侧的收口子阶段，**不是 M3 完成声明**，也不是 design C.18 的落地。本计划已吸收 `docs/reviews/v24-tool-plugin-abi-w6-plan-critique-2026-10-31.md` 的 15 条 findings 与 Q1/Q2，以及 2026-10-31 Oracle 复核的 21 条意见（CONDITIONAL GO，其中 6 条必改）；逐条处置见 `## 批判意见落实` 与 `## Oracle 复核落实`。

**Assumption（scope；Oracle-adjudicated）**：W6 是 Node 双工具的合规与证据收口，不是从零实现，也不承担 M3 完成声明、Linux real 或 M5 文档修订。该口径是委托裁决下的保守默认。

**基线勘误**：本计划脚手架最初写的基线 `5771ce3` 已过期——那是 W5 的实施基线。W5 收口后 HEAD 为 `82e5440`。本计划所有 diff、untracked 快照、红基线与候选集合均相对 `82e5440`。

## 范围口径：W6 为什么是「收口」而不是「实现」

W4b 一次提交（`80dc0c4`）交付了 `fs_tools.js`。该文件是一个 install `v24.fs.node`、两个 `provides`（`list`、`search`），由帧内 `tool` 在 `fs_tools.js:638-642` 分流。7 条冻结 list 用例与 24 条冻结 search 用例全部通过（`v24/s13/README.md` 的 W4b/W5 小节、W4b 执行记录）。`test_node.py --node` 断言同一 install 的 `prepare`+`list`+`search` 共 3 次 spawn。功能面已经存在，W6 不重写它。

W6 的实质有三块，且都落在同一个生产文件上。

1. **修掉在合法输入上可复现的缺陷**：search 早退守卫拒绝 count-full 页、没有 12 秒扫描预算、slashless glob 用相对路径匹配、大 offset 的算术不是安全整数、list 空页绕过四预算。
2. **补证据**：冻结用例没有覆盖的 cutoff 状态、glob 语义、预检计数、分页边界与 content 计量。
3. **兑现 W4 留下的欠账**：W4 plan 的 O8 二次裁决选了 B（W4b 只声明「M3 实现完成，timing/cutoff pending」），并把「可注入/虚拟时钟的 12 秒 cutoff 用例」记为 C、明确写成「后续 owner 的可选增强」（`docs/plans/v24-tool-plugin-abi-w4-dispatcher-worker-wiring-2026-10-31.md:860-888`）。W6 就是那个后续 owner。

W6 补的是**确定性分支证据**，不推翻 O8=B 的声明措辞，也不把 B 读成「永久禁止时钟 seam」：B 拒绝的是「为了让 M3 完成声明成立而加测试专用时钟缝」，不是「事后补证据」。这个读法是推断（依据是 O8 裁决理由段与 C 的措辞，上引 `:874-888`），因此并入 D1 提交裁决。

「收口」口径同时解释了为什么本阶段只动一个生产文件：`v24/s13/plugins/fs_tools.js`。

## Goal 与范围

**In scope**

1. 把 search 的停止状态从 `stopped`/`scopeExhausted` 两个布尔改为 `stopReason ∈ {eof, sentinel, file-cap, time-cap}`；早退守卫替换为 §5.6 的后置判定：cutoff 页成功当且仅当 count-full（`k=m=limit`）或 `k<m`（观察到后续完整候选），否则 `search_scope_too_large`。
2. 引入 `SCAN_BUDGET_MS = 12000`，只在 work-item 边界读一次单调时钟；超时在 item 边界停止，不打断 hit，不产生半个 context。
3. 修 slashless glob：无 `/` 时匹配 basename，有 `/` 时匹配相对路径；`*`/`**`/`?` 语义不变。
4. 把 offset/limit/cursor 的加法与比较改为 BigInt（或等价的安全整数检查），并让 `offset`/`limit` 走 `Number.isSafeInteger`；同一审计覆盖 `listText`/`searchText` 的 footer 算术（`:213-214`、`:237-238`）。
5. 补 list 侧：空目录页的四预算检查、`entry_too_large` 的可达性、注入 caps 的测试 seam（value/content/meta/frame 四域）、10000 扫描 cap 的计数口径、默认值等价性。
6. 在 `test_tools.py` 增加 11 条 list probe 与 26 条 search probe，并扩展 marker。
7. 留下执行记录：`fs_tools.js` 的 source/artifact sha256、32 行串行表、七项 scope audit。

**Out of scope（不得顺手做）**

- `v24/s13/plugins/fs_read.py`（W5 已收口，sha256 `260274da…5165c` 不得变化）。
- `v24/host/**`、`v24/sql/**`、kernel/replay、冻结向量、design 正文、`DESIGN_SHA256`、`design_conformance.json`。
- design C.18 追加（属 M3 声明阶段，见 D2）。
- Linux real 非 UTF-8 证据；macOS 上 `linux_real=not_run`，Linux `filesystem` 模式不纳入 W6 验收。
- 任何 wall-clock 通过/失败 gate，以及 `sleep(12)`。
- 放宽任何 cap（12s/15s/10000/200/500/40960/41984/4096/64 KiB）。cap 是冻结合同面，放宽等于合同修订。
- `test_vectors.py`、`test_contracts.py`、`test_lifecycle.py`、`test_node.py`、`w1_reference.js`、`w1_reference.py` 的任何编辑。
- `docs/investigations/v24-m3-budget-closeout-2026-10-31.md` 的提交；它只作缺陷复现来源（其 `fs_read.py` 行号为 pre-W5，`fs_tools.js` 行号早于最终文件，均不采用）。

## Done when

1. **count-full file-cap 页（真实子进程）。** 10,001 个 regular files 中恰有 2 个命中、`limit:2`，经 `invoke` 直连真实 Node 子进程返回成功页：`hits` 2 条、`total:2`、`complete:false`、`scanned_files:10000`、`truncated:true`、`next_offset:3`。这是冻结 `cutoff_count_full` 的形状（`v24/s13/vectors/results_v2.json` 的 `budget_domains.expected.prefix_scenarios`），也是已复现缺陷 1 的反例。
2. **四种 stopReason 被确定性证明。** file-cap 覆盖 count-full、byte-full、before-fill、before-offset、empty（S01–S05）；time-cap 覆盖 count-full、before-fill、before-offset、empty（S06–S09）；EOF 优先与 sentinel 优先各有 probe（S10/S11）；无适配前缀与搜索空页得到 `hit_too_large`/`output_too_large`（S12）。
3. **12 秒证据三层齐备且不引入墙钟 gate。**
   - T1：注入时钟经生产函数 `searchTool`（不是重写的测试副本）证明 cutoff 分支。
   - T2：常量断言 `SCAN_BUDGET_MS === 12000`、search descriptor `timeout_ms === 15000`、余量 ≥ 3000 ms，以及源码结构与 artifact 断言（S24）。
   - T3：一次真实时钟观测，断言结果为完整空成功或 `search_scope_too_large`，elapsed 只记录、不作通过条件（S25）。
   - `tool.search_budget_timing_m3_pending` 的 `status` 保持 `m3_pending`；`test_tools.py:713-718` 的既有断言保持。
4. **slashless glob 匹配 basename**（S13）；有 `/` 的 glob 与 `**`/`?` 行为不变（S14/S15）。
5. **所有 offset/limit/cursor 与 footer 算术不会写出不安全整数**（S16）；巨大 `offset` 经帧到达插件时返回闭集内的 `invalid_path`，不产生舍入后的页；`addSafe` 溢出抛 `invalid_tool_output`（§5.6 第 5 步），不泄漏 `TypeError`、不写 JSON。
6. **glob 记账按冻结字节执行**（S17）：glob 排除的 regular file 仍计入 10000 file 预算与 `scanned_files`；`§6.3:871` 的相反措辞记入台账（D3 已被冻结字节判定，不是本轮可选）。
7. **list 侧边界闭环**（L01–L11）：byte-full 的 k<limit 分页、`entry_too_large`/`output_too_large` 经注入 caps 可达（四域）、嵌套 `.git`、hidden 子树、symlink 不跟随、special 计数、根级非 UTF-8 条目（子目录注入是已知限制，见 D16/Q1）、路径 UTF-8 排序、offset/empty 边界、默认值逐字节等价、10000/10001 原始条目 cap、content 逐字节等于 host 渲染。
8. **冻结 74 条用例逐字节不变**；`test_contracts.py`、`test_vectors.py`、`test_vectors.py --node`、`test_registry.py`、`test_line_json.py` 全绿且零 diff。
9. **`test_tools.py` 实现后末行为**：
   ```text
   [passed] W4 fs tools; cases=140; read=16; read_probes=29; list=7; list_probes=11; search=24; search_probes=26; pagination_converged=true; page_contracts_imported=3
   ```
   这是计划编写时的验收目标；实际 inventory 若不同，先改本计划再跑 sweep。Linux 变体不跑 5 条 shim guard，预计 `cases=135`，不在验收内；Linux 上 `[evidence] linux_real=filesystem`，macOS 上 `linux_real=not_run`。
10. **32 条串行命令全部 exit 0**；第 1–31 条末行为命令专属 `[passed]`，第 32 条 exit 0 且输出为空；七项 scope audit（六项钉 `c8c4bd0` + 一项 W6 delta）全过，并在 W6-7 写完文档后、staging 前重跑；无 exit 2/`[SKIP]`；closeout 仍 **11/11**，s13 仍是 extension evidence。

## Current-state analysis（基线 `82e5440`）

本节的行号是**当前文件**的行号（不是 investigation 的旧行号）。六条缺陷中的 #1–#4 已在计划编写时用真实子进程/源码复现；#5 由代码路径与冻结 oracle 场景对照确定；#6 由冻结用例覆盖表确定。

### 调用链与所有权（W6 只动最内层）

```text
model {key:"list"|"search", args}
  → plugins._tool_v2 步 1–7（match_tool / args 大小 / parameters_check / require_artifact / workspace / lease / spawn）
  → line_json._spec_v2：invoke 的 timeout_ms = approved.tool.timeout_ms（list 5000 / search 15000）
  → process_io.run_process：deadline = started + timeout_ms，超时杀进程组
  → fs_tools.js main()：读一行 stdin，解析 v2 帧，按帧内 tool 分流
  → listTool / searchTool(args, root)
  → 插件自己序列化 {ok,v:2,result:{value}} 写一行 stdout
  → host strict parse → 页合同校验 → RENDERERS[*].render → tool_results.measure → 64 KiB 预算
```

- `ApprovedPlugin` 的 `argv`/`cwd`/`environment_allowlist` 是普通字段（`v24/host/registry.py:246-262`）；spawn 在 `v24/host/process_io.py:103-113`；per-tool timeout 由 `v24/host/line_json.py:250-265` 选取。宿主不按语言分支，Node 与 Python 走同一条路径。
- 插件的帧处理：`fs_tools.js:644-699`。`require.main === module` 守卫在 `:701`，所以文件可被 `node -e` 引入而不触发 `main`。
- 默认值由插件执行（descriptor 的 `parameters` 里没有 `default`，`design:886`）：`listTool` 的默认在 `:297-302`，`searchTool` 的在 `:533-550`。

### 已确认缺陷

| # | 缺陷 | 位置 | 规范 | 复现 / 证据 |
|---|---|---|---|---|
| 1 | 早退守卫 `scopeExhausted && total < offset+limit` 拒绝**所有** file-cap cutoff。到 `offset+limit` 个 hit 时 sentinel 必然先停，所以 `scopeExhausted` 恒蕴含 `total < offset+limit`；count-full 页也被拒。现有 `file_count_cutoff` 只测无命中，所以 gate 是绿的。 | `fs_tools.js:575-578` | §5.6 的后置判定（`design:776-778`）：`k=m=limit` 或 `k<m` 才允许 cutoff 页 | 10,001 files + 2 hits + `limit:2` → exit 3 `search_scope_too_large`；冻结 `cutoff_count_full` 要求 2-hit 页 |
| 2 | 完全没有 12 秒扫描预算：无 `Date.now`/`hrtime`/deadline/cutoff，只有 10000 file cap。 | `fs_tools.js:562-574` 只有 `stopped`/`scopeExhausted` | §6.3 `:871`/`:876`、§5.6 `:774`：预算在页未填满前耗尽 → `search_scope_too_large` | `grep` 零命中；`test_tools.py:717-718` 断言 `timing.status == "m3_pending"`，即 gate 在批准缺口 |
| 3 | slashless glob 用相对路径匹配：`^[^/]*$` 测 `relPath`，`*.py` 漏掉 `src/a.py`。 | `fs_tools.js:360-390`、`:442` | §6.3 `:869`：无 `/` 时匹配 basename，有 `/` 时匹配相对路径 | 树 `src/a.py`，`glob:"*.py"` 返回 0 条 |
| 4 | 安全整数：`offset+limit`、`offset+count`、sentinel 比较用普通 JS 数字；`offset` 只校验 `Number.isInteger`，2^53 通过；`listText`/`searchText` 的 footer 也用普通加法。 | `fs_tools.js:478`、`:575`、`:613`、`:623`、`:546`、`:213-214`、`:237-238` | §5.6 `:776`/`:784`；`w1_reference.js:163-186` 的 `pageError` 对不安全 cursor 判 `invalid_tool_output` | 帧内 `offset:9007199254740993` 被 JSON 解析舍入为 2^53 |
| 5 | list 空目录分支在 `:314-328` 直接返回，跳过四预算；注入窄 cap 时仍返回成功页。 | `fs_tools.js:314-328` | §5.6 第 6 步：空页也要过四预算，失败 → `output_too_large`（`w1_reference.js:188-200` 的 `empty_overhead_unfit` 场景） | 代码路径审读；冻结 `empty_overhead_unfit` 期望 `output_too_large` |
| 6 | list 的 `entry_too_large`（`:354-356`）无向量/探针；list byte-full 的 k<limit 分页未断言；10000 cap 是否计入 hidden/`.git`/symlink/special/非 UTF-8 未定义。 | `fs_tools.js:248-294`、`:332-357` | §6.3 `:847`/`:849`；list 错误码表含 `entry_too_large` | 冻结 7 条 list 用例不含这些形状 |

### 不是缺陷的部分（不得「修」）

- **sentinel 记账是对的。** `total` 含 look-ahead sentinel，返回页是 `hits.slice(offset-1, offset-1+limit)`，不含它（`fs_tools.js:602-609`；`design:773`；冻结 `incomplete_nonempty`：两行命中、`limit:1` → 1 hit、`total:2`、`next_offset:2`）。不要「修正」这个语义。
- **content 计量已经含 footer。** `listText`/`searchText` 在 `:212-216`/`:240-244` 追加 footer，调用方用 `27 + escapedLen(...)`（`:347`、`:625`），与 §5.3.1 的 `27+E(T)` 一致。W5 的 footer 缺陷是 read 的，不能照搬到 list/search。
- **render 文本语法已与 §6.3 `:850`/`:877-878` 对齐**：entry 间一个 LF、footer 前两个 LF、无合成尾 LF、context 行重复 path、summary 含 `N`/`N+`。
- **`globRegex` 的 `*`/`**`/`?` 展开与非法字符集是对的**（`:360-390`），坏的只是「用哪个字符串去测」。

### 未验证项（W6-0 必须先读）

| # | 事项 | 状态 |
|---|---|---|
| U1 | glob 排除的 regular file 是否计入 `scanned_files` | **已由冻结字节判定**：`tool_contracts.json` 的 `tool.search.contract` 里 `glob_16`（`src/sub/a.py`，`glob:"src/*.py"`，0 hit）钉死 `scanned_files:1`；所以当前「预检通过即计数、glob 之后再匹配」的行为就是合同行为。D3 据此改写，`§6.3:871` 的「并尝试 literal 匹配」措辞记入台账。 |
| U2 | glob 排除的文件是否消耗 file 预算 | 冻结字节只钉 `scanned_files`，不钉 budget。D3 选择保持 `regular++` 在 glob 之前（保守上限），并用 S17(b) 钉住该选择。 |
| U3 | `docs/reviews/v24-conformance-matrix-2026-10-23.md` 与 `...-deviation-ledger-...:615-623` 的 W6 子节体例 | W6-0 读这两段，W6-7 照体例追加；本计划不复制其正文。 |
| U4 | `fixtures.py:429-447` 的 `install_spawn_log`/`spawn_count` 对同一 install 两次 tool 调用的计数形状 | W6-0 读该段；L05/S11 若用 spawn log，只断言「一次 invoke 一次 spawn」。 |
| U5 | host 是否在 spawn 前拒绝不安全整数 args | **已由代码判定**：`plugins._tool_v2` 第 2 步的 `len(compact_json(args))`（`plugins.py:137-146`）经 `canonical._safe_integer`（`canonical.py:118-120`）对越界整数抛 `CanonicalError("unsafe_integer")`，返回 `invalid_tool_arguments`，零 spawn。所以 S16 的插件分支是**防御性不可达**，只能经 `test_tools.py` 的直连帧（绕开 `_tool_v2`）触达；`D-ABI-W6-8` 必须写明这一点。 |

### 可复用件

| 件 | 位置 | 用途 |
|---|---|---|
| `invoke` / `invoke_raw` | `test_tools.py:151-193` | 直连真实 Node 子进程，手工 v2 帧（不经 `line_json.run`） |
| `check_value` / `expect_error` | `test_tools.py:195-206` | `check_value` 走 `output_check` + `validate_page`；现有 `expect_error` 只断言 `ok is False` 与 code，W6 另加严格 `check_error` 包装（见组件设计） |
| `selector_probe` | `test_tools.py:218-242` | `node -e` + `require` 插件的现成模式（W6 的 JS 层 probe 照此写） |
| `run_harness_case` | `test_tools.py:271-303` | DB-backed 真实 executor（W5 用它证 read 的 5 s deadline） |
| `path_differential` | `test_tools.py:305-322` | 同一组路径错误对三个 tool 做差分 |
| `shim_guard` | `test_tools.py:71-103` | 非 UTF-8 名称的注入/对照差分 |
| `materialize_nodes` | `fixtures.py:112-144` | 声明式树（file/symlink/special、`recipe` 生成大文件） |
| `node_workspace` | 新增（D16） | 调用方提供 nodes 的 `Workspace`，模式同 `read_workspace`（`fixtures.py:267-292`） |
| `node_spec` | `fixtures.py:410-415` | 一个 install、两个 provides；`build_spec`（`:346-396`）复制插件并现算 sha，改文件后 digest 自动更新 |
| `w1_reference.js` | `selectPrefix:154-161`、`pageError:163-186`、`pageDecision:188-200` | 冻结的页决策 oracle；S01/S02/L01 用同一谓词做差分 |
| `w1_reference.py` | `budget_measures`、`render` | 四域计量与 render 的 Python 侧 oracle |
| `tool_pages.validate_page` | host | 重算 `truncated`/`next_offset`/`k≤limit`/空页形状 |
| `tool_results.measure` | host | `27+E(T)`、frame、64 KiB 的独立重算 |

## 决策记录

D1–D17 中，标注「Oracle 裁决」的条目在 `## Oracle 裁决记录` 里给出裁定；其余由代码/冻结字节/仓库约定直接判定。正文的「推荐」是决策依据；裁决后以裁决记录为准。

### D1 — 12 秒证据标准：确定性分支 + 常量 + 真实观测

**推荐**（A）：三层证据，不做墙钟 gate。

- T1（确定性）：`searchTool(args, root, {now, budgetMs})` 只在 work-item 边界读 `now()`；probe 注入「第 N 次调用起 ≥ deadline」的脚本时钟，经生产函数走到 `time-cap`，覆盖 count-full / before-fill / before-offset / empty。
- T2（常量与结构）：`SCAN_BUDGET_MS === 12000`、search descriptor `timeout_ms === 15000`、余量 `15000-12000=3000 ≥ 3000`；`fs_tools.js` 里 `now`/`hrtime` 只出现在 search 路径；`process.env` 只出现在 `rootPath`。
- T3（真实观测）：`budgetMs=50` 扫 10,000 files，用默认 `now`，记录 `real_clock_elapsed_ms` 与过冲；结果只允许「`complete:true,total:0,hits:[]` 的完整空成功」或 `search_scope_too_large`；**不设 elapsed 通过阈值**、不因慢 CI 失败。

**理由**：12 s 常数与分类分支是产品行为，墙钟是环境属性；design 附录 C.16（`:1380-1385`）明确 12 s 是插件内部量、host 只用 15 s timeout，W4 的 D10 与 O8 都拒绝 `sleep(12)` 墙钟 gate。W4 O8 的 C 选项（可注入时钟）被记为「后续 owner 的可选增强」，W6 正是该 owner。**拒绝**：B（硬实时 12 s gate，慢 CI 会误杀且不能证明分类正确）；C（删掉 12 s 合同，需要改 design 与向量，属产品决定）。**注意**：这不是「12 秒已证明」——执行记录必须把三层分开写。**Oracle 裁决：O1=A**（两条 lane 一致；「12 s 已证明」的含义属产品判断，按保守默认取 A）。

### D2 — design C.18 留给 M3 声明阶段

**推荐**：W6 的 design 正文、`DESIGN_SHA256`、`design_conformance.json` 全部零 diff；C.18 的追加与原子 repin 归 M3 声明阶段（本计划的后续阶段），W6 只在 ledger 记录解释。

**理由**：W5 D12 已确立「收口阶段不改 design」；C.18 要绑定 M3 的完成声明与证据标准，而 W6 明确不声明 M3。追加 C.18 会把 design SHA、`design_conformance` 的 `sha256_at_review` 与全部 25 个 pinned span 拖进 W6 的 scope audit，收益与风险不成比例。**拒绝**：在 W6 内追加 C.18 并 repin——那会让「工具收口」混入「M3 合同修订」。**Oracle 裁决：O2=零 diff**（范围判断，按保守默认；clock seam 只在 `module.exports` 与可选第三参数，design §7.1 不约束导出面，因此无需 design 授权）。

### D3 — glob 排除文件的记账：保持冻结字节

**推荐**：`searchFile` 保持「预检通过 → `scannedFiles++` → glob 过滤」的顺序；`regular++` 也保持在 glob 之前，即 glob 排除的文件消耗 10000 file 预算。S17 把这两个事实都钉住。

**理由**：冻结 `glob_16` 用 `src/sub/a.py` + `glob:"src/*.py"`（0 hit）钉死 `scanned_files:1`，即 glob 排除的文件**要**计数；`v24/s13/vectors/README.md` 与 `test_contracts.py:71` 禁止改冻结字节。`§6.3:871` 的「只计通过预检并尝试 literal 匹配的文件」与冻结字节冲突，由冻结字节胜出，记台账 `D-ABI-W6-1`。预算侧没有冻结字节，保持保守（glob 前计数）并用 S17(b) 固定。**拒绝**：把 `scannedFiles++` 移到 glob 之后——那会让 `glob_16` 变红，属 STOP。

### D4 — list 10000 扫描 cap 计入所有原始条目

**推荐**：保持现状：`listScan` 的 `state.scanned += 1` 在 `.git`/hidden/非 UTF-8/symlink/special 判定之前（`fs_tools.js:256-258`），即每个 `readdir` 名字都消耗一个名额；`state.scanned > 10000` 立即 `directory_too_large`。用 L03(c) 钉住。

**理由**：§6.3 `:847` 说的是「扫描超过 10000 项」，不是「输出超过」；cap 是目录扫描的 DoS 边界，不是输出边界。改成「只计被列出的条目」会让一个塞满隐藏文件的目录逃过 cap。**拒绝**：把 hidden/`.git` 排除在计数外。**Oracle 裁决：O4=(a)**；台账 `D-ABI-W6-6` 另记「`state.scanned` 跨递归共享、隐藏子树只计根、`.git` 计 1 次不下降」。

### D5 — 测试 seam：可选第三参数，不是 env/argv

**推荐**：`searchTool(args, root, options)` 与 `listTool(args, root, options)`；`options` 可含 `{now, budgetMs, fileLimit, scanLimit, caps, trace}`，生产路径 `invoke` 调用时不传。`options`、`defaultCaps`、`emptyMeasures` 与 `searchTool`/`listTool`/`ToolError`/`SCAN_BUDGET_MS`/`MAX_SEARCH_FILES`/`MAX_LIST_ENTRIES` 的导出在 W6-2 落地（搜索页决策需要）；`addSafe` 随 W6-4 加入同一导出对象，供 S16(c)/S24 使用。W6-5 只消费 `caps`/`scanLimit`。`options.caps` 与 `defaultCaps()` 合并（浅合并），允许 probe 只覆盖一域。导出 `searchTool`/`listTool`/`ToolError`/`SCAN_BUDGET_MS`/`MAX_SEARCH_FILES`/`MAX_LIST_ENTRIES`/`addSafe` 供 `node -e` 测试；`module.exports` 从 `:703` 扩展。

**理由**：`test_tools.py:720-724` 已禁止生产插件出现 `W4B_`/`NODE_OPTIONS`，新增 env 开关会与这条守卫和 C.17 的「无生产 seam」原则冲突；argv 开关会被 `require_artifact` 的 `argv[1]` 约束牵动。第三参数只影响测试进程，且 `invoke` 不传就完全走默认。**注意**：`trace` 只写 `stopReason`/`nowCalls`，不写文件、不进 stdout。

### D6 — gate 放 `test_tools.py`，不新建文件

**推荐**：list/search probe 都并入 `v24/s13/test_tools.py` 的 `list_probes`/`search_probes`；marker 增加 `list_probes`/`search_probes` 字段。

**理由**：design §7.1 的文件清单（`:890-936`）把工具合同 gate 绑在 `test_tools.py`；新增文件要改 design 清单、`DESIGN_SHA256` 与 `design_conformance.json`。W5 D4 已有同一先例。

### D7 — marker 数字：`cases=140`

**推荐**：11 list + 26 search = 37 条新 probe；`103 + 37 = 140`。末行字段顺序固定为 `cases; read; read_probes; list; list_probes; search; search_probes; pagination_converged; page_contracts_imported`。

**理由**：现有 `cases` 是「实际执行的用例数」，S24–S26 是证据 probe 但同样执行并断言（S24 断言常量/结构/digest，S25 观测，S26 断言 600 次序列化计数），与 W5 把 R28/R29 计入 29 条的先例一致。**Oracle 裁决：O6=(a)**，`cases=140`；S26 的通过判据按 O6 细化改为 600 次 `JSON.stringify` 计数，`enum_cost_wall_ms` 只记录（见风险 #9）。

### D8 — `stopReason` 状态机与检查点位置

**推荐**：三个停止源互斥，优先级从高到低：

1. `sentinel`：`searchFile` 在 push 完 hit 与 context 后，用 `BigInt(offset)+BigInt(limit)` 与 `hits.length` 比较；命中即置 `sentinel` 并让整条 walk 返回 true。此处**不读时钟**。
2. `file-cap`：`searchWalk` 在 `regular++` 之后、`searchFile` 之前，若 `regular > fileLimit` 置 `file-cap` 并返回 true。
3. `time-cap`：只在两个 work-item 边界读时钟——**C0** 在整个 walk 开始前一次；**C1** 在 `lstat` 分类之后：目录在递归前，regular file 在 `regular++` 与 file-cap 检查之后、`searchFile` 前。`now >= deadline` 即置 `time-cap` 返回 true。这样同一条目同时满足 file-cap 与过期时，file-cap 先返回，符合上面的优先级。
4. 都没有发生则 walk 正常结束，置 `eof`。

**理由**：`design:774` 要求「在 begin/complete item 边界检查预算」，C1 把检查放在「目录递归前或 regular file 的 file-cap 检查之后」，是最小且可复现的解释；不在 hit 边界检查可以让「一个文件内的命中集合」保持原子，避免产出半个 context 或停在一个不能解释的 hit 中间。**注意**：相对需求方的「before/after complete item」列表，这里收窄为 C0+C1 两个点——这是本计划唯一对边界清单的修改，理由与后果（过冲上界 = 一次 `readdir` + 对结果逐条按名过滤 + symlink 的 `lstat`/分类 + 一个 ≤1 MiB 文件的读取与扫描；hidden/`.git`/非 UTF-8 在 `lstat` 前被过滤，只有 symlink 会 `lstat` 后跳过）写进台账 `D-ABI-W6-3`。**Oracle 裁决：O3=(a)**。

### D9 — `output_too_large` 由插件发出

**推荐**：空页（list 空目录、search `eof` 且 `total=0`/`offset=1`）在 `offset` 校验通过后过四预算；任一域超 cap 抛 `output_too_large`。非空页同样过四域（`meta` 按缺省 2 B 计量）；`invalid_tool_output` 的页关系校验仍由 host 负责，安全整数失败见 D11。

**理由**：§5.6 第 6 步指定 `output_too_large`（`w1_reference.js:188-200` 的 `empty_overhead_unfit` 场景即此语义）；但 list 的 12 码与 search 的 13 码闭集都不含它，这是与 W5 D6 同型的规范内部冲突。`line_json.py` 只校验 exit-3 帧的键集，`plugins.py:188` 直接取 `code`，所以 known error 会原样透传。记台账 `D-ABI-W6-4`；**不改 design、不 repin**。

### D10 — `entry_too_large` 保留为防御码

**推荐**：保留 `:354-356` 的 `entry_too_large`；用 L02(a) 的注入 caps 证明可达，不用真实树（合法 path ≤1024 B 时单条 value 远小于 40960，内建 cap 下不可达）。

**理由**：`entry_too_large` 在 list 的 12 码闭集里，是合同的一部分；不可达不等于该删。W5 对空页 `output_too_large` 用了同样的「注入 cap 证明不可达分支」手法。

### D11 — 安全整数：BigInt 比较 + `isSafeInteger` 校验

**推荐**：`offset`/`limit` 的整型校验改 `Number.isSafeInteger`；所有 `offset + count`、`offset + limit`、sentinel 比较用 `BigInt`；`listText`/`searchText` 的 footer 也走 `addSafe`，只在确认 ≤ `2^53-1` 后转回 `number`。仍以 `number` 写回 JSON；无法形成安全整数时抛 `invalid_tool_output`（§5.6 第 5 步的分类），实际不可达。巨大 `offset` 经帧到达时返回 `invalid_path`。页决策的 `offset > total` 分支先于切片：`complete` → `offset_out_of_range`，cutoff → `search_scope_too_large`；`hits.slice` 的 start/end 用 BigInt 计算并 clamp 到 `total`，转回 `number` 前断言 `Number.isSafeInteger`，不把 BigInt 写进 JSON。

**理由**：JSON 数字在 Node 侧是 double，`9007199254740993` 会变成 2^53；host 的 schema 只校验 `integer/minimum`，不会替插件挡住。`w1_reference.js:163-186` 对不安全 cursor 的输出判 `invalid_tool_output`，插件必须保证不写出这种页。`invalid_path` 与 W5 D10 的「非法 offset/limit → invalid_path」先例一致。**注意（Oracle O5 细化）**：`plugins._tool_v2` 第 2 步的 `compact_json(args)` 已对越界整数抛 `CanonicalError("unsafe_integer")` → `invalid_tool_arguments`、零 spawn（`plugins.py:137-146`、`canonical.py:118-120`），所以插件这条分支在生产路径上不可达；S16 只能在直连帧下证明，措辞按「防御性」写，不按「生产可达」写。记台账 `D-ABI-W6-8`。**Q2 裁决**：`addSafe` 溢出取 §5.6 第 5 步的 `invalid_tool_output`，不取 `io_error`；该码不在 list 12 码/search 13 码闭集内，但 §5.6 明确要求，且与 D9 的 `output_too_large` 同型，记台账 `D-ABI-W6-9`。**Oracle 裁决：O5=(a)**。

### D12 — 红基线按 probe 可执行性

**推荐**：W6-1 对 `82e5440` 的旧代码运行所有「旧接口可运行」的 probe，按三类记录：**旧代码可运行且预期红**：S01、S13、S15（`?.txt` 旧码只回 1）、S16(a) 的 raw unsafe-offset、S24 的常量/结构断言；**旧代码可运行且预期绿（回归护栏）**：S14、S17(a)、S18–S23、L01、L03(a)(c)、L04–L07、L08、L09、L10、L11；**需新 seam，旧代码 green-only**：S02–S12、S16(b)(c)(d)、S17(b)、S26、L02、L03(b)、S24 的 digest/host 透传子断言、S25。S03–S05 依赖 `fileLimit`/caps seam，旧码会成功或给 `offset_out_of_range`，不能算绿；S17(a) 是旧行为，不能算红；L02 依赖新导出的 `listTool`/`caps`，不能算红；10,001-entry 的直接调用属旧代码可运行绿，已放在 L03(c)。S16(a) 的 unsafe `limit` 子例旧码也因 `>limit` 返回 `invalid_path`，记旧绿，不记红。

**理由**：W5 D12 的先例；红基线的目的是证明 probe 有判别力，不是凑红数。

### D13 — slashless glob 语义

**推荐**：编译产物从单个 regex 改为 `{regex, basenameOnly}`：`basenameOnly = !glob.includes("/")`；匹配时 `basenameOnly ? regex.test(path.posix.basename(relPath)) : regex.test(relPath)`。`*`/`**`/`?` 的展开与非法字符集不变。

**理由**：§6.3 `:869` 的原文；`glob_16`/`glob_17`/`glob_18` 已钉住有 `/` 与 `?` 的行为，只有 slashless 这一支是缺陷。**拒绝**：把 `**` 也改成 basename 语义。

### D14 — 候选枚举全前缀扫描，不假设单调

**推荐**：保留 `best = value` 的全前缀枚举（`for count=1..m`），不早停、不二分；m ≤ 200，成本 O(m²·bytes) 但由 S26 的 600 次序列化计数钉住。候选循环必须**先无条件计算四域测量值再做合取**，禁止 `&&` 短路（否则 `frameLen` 在 value/content 失败时不会被调用，600 次计数不成立）。S26 在 JS probe 内临时包裹 `JSON.stringify`，`searchTool` 返回后立即还原，再序列化 probe 结果；断言每个候选恰 3 次序列化（`jsonLen(value)`、`escapedLen(searchText(value))`、`frameLen(value)`），200 候选即 600 次。结构计数是唯一硬判据；`enum_cost_wall_ms` 只打印记录，不设墙钟阈值、不作 STOP。

**理由**：§5.6 第 4 步明确「不假设长度单调、不 binary-search、不在第一个失败前缀就停止」；footer 可能让最后一页的 fitness 非单调，因此不能把「最大可行 k」当作可早停的单调上界。全枚举是规范要求，不是实现偏好；真要优化属另一个阶段。

### D15 — 输入校验错误码

**推荐**：`query`/`context`/`offset`/`limit` 非法一律 `invalid_path`（现状），不新增更贴切的码；`glob` 非法仍 `invalid_glob`。

**理由**：list 的 12 码与 search 的 13 码都没有 `invalid_argument`；W5 D10 已有「非法 offset/limit → invalid_path」先例。只把 `Number.isInteger` 换成 `Number.isSafeInteger`。

### D16 — fixtures 纯加法

**推荐**：`fixtures.py` 新增 `node_workspace(root, nodes) -> Workspace`：`_prepare_root` + `materialize_nodes` + `Workspace(realpath, "none")`，等价于 `read_workspace` 的「调用方提供 nodes」版本。不改 `read_spec`/`node_spec`/`build_spec` 签名。

**理由**：S/L probe 需要大量临时树；走 `search_workspace` 会把 case id 写进冻结向量。L07 只用现有 `workspace(root, "list")` 的根级 0xff 条目；preload 只注入配置根 realpath（`w4b_non_utf8_preload.cjs:34-58`），macOS 子目录注入不覆盖，记 `not_run`（Q1 取保守口径）。

### D17 — artifact digest 证据

**推荐**：沿 W5 D1。S24 断言三方 sha 相等（`fs_tools.js` 源、安装副本、`spec.entry.artifact_digest`）并做 tamper 反证：直接调用 `spec.entry.require_artifact()`，在 `try/finally` 中翻转副本 1 B，断言 `artifact_digest_mismatch`；`finally` 还原原始字节并再次校验 digest。实测 sha 在最终编辑后计算，写入执行记录。这是证据，不是向量 promotion。

**理由**：`_ApprovedEntry.require_artifact`（`v24/host/registry.py:57-82`）已实现机制，缺的是证据；`manifest.artifact_digest_pending` 的 `status` 零改动。

## 组件设计

### `v24/s13/plugins/fs_tools.js`（改，单文件，仅标准库）

**保留不变**：`main`（`:644-699`）的帧解析与四操作分派；`rootPath`（`:64-72`）、`pathArgument`（`:74-81`）、`components`（`:84-95`）、`resolvePath`（`:98-126`）、`mapFsError`（`:52-62`）；`escapedLen`/`jsonLen`/`frameLen`；`selectPrefix` 签名；`globRegex` 的字符展开；`listText`/`searchText` 的文本语法；常量 `MAX_FILE_BYTES`、`MAX_LINE_BYTES`、`MAX_LIST_ENTRIES`、`MAX_LIST_LIMIT`、`MAX_SEARCH_HITS`、`MAX_VALUE_BYTES`、`MAX_CONTENT_BYTES`、`FRAME_TARGET`。

**新增（签名示意，不是可复制实现）**：

```js
const SCAN_BUDGET_MS = 12000;
const MAX_SEARCH_FILES = 10000;            // 取代 searchWalk 里的字面量
function defaultCaps() { /* {value:40960, content:41984, meta:4096, frame:60000} */ }
function addSafe(a, b) { /* BigInt 求和；> 2^53-1 抛 ToolError("invalid_tool_output", …) */ }
function emptyMeasures(value, text) { /* {value:jsonLen(value), content:27+escapedLen(text), meta:2, frame:frameLen(value)} */ }
module.exports = { selectPrefix, listText, searchText,
                   searchTool, listTool, ToolError,
                   SCAN_BUDGET_MS, MAX_SEARCH_FILES, MAX_LIST_ENTRIES, addSafe };
```

`if (require.main === module) main();`（`:701`）保持，使 `node -e` 可引入而不触发 `main`。

所有候选——非空与空页——都检查四域：`jsonLen(value) <= caps.value`、`27 + escapedLen(text) <= caps.content`、`2 <= caps.meta`、`frameLen(value) <= caps.frame`；四个测量值先无条件计算再逐项比较，禁止 `&&` 短路（S26 依赖这一点）。`defaultCaps()` 的四域就是四个内建常量。footer 里的 `offset + len - 1` 也走 `addSafe`，只在安全后转回 `number`。

#### search 路径

- **入口**（`:532-559`）：路径解析、`query`/`context`/`offset`/`limit` 的校验顺序不变；`offset`/`limit` 改 `isSafeInteger`；`options` 以 `{now: () => Number(process.hrtime.bigint())/1e6, budgetMs: SCAN_BUDGET_MS, fileLimit: MAX_SEARCH_FILES, caps: defaultCaps(), trace: null}` 为底，传入的 `caps` 与 `defaultCaps()` 浅合并。glob 编译为 `{regex, basenameOnly}`。
- **状态**（取代 `:562-570`）：`hits`、`scannedFiles`、`regular`、`skipped`（六项）、`stopReason: null`、`deadline`、`nowCalls`（仅 trace）。
- **`searchWalk`**（`:503-530`）：`.git` → hidden（`skipped.hidden++`）→ 非 UTF-8（`skipped.non_utf8++`）→ `lstat` → symlink（`skipped.symlink++`）→ 目录（C1 后递归）→ 非 regular 跳过 → `regular++` → 超 `fileLimit` 置 `file-cap` → C1 → `searchFile`。任何子调用返回 true 则逐层返回 true。只有目录和 regular file 到 C1；hidden/`.git`/非 UTF-8 在 `lstat` 前被过滤。
- **`searchFile`**（`:406-500`）：预检顺序 size（`too_large`）→ 8192 B NUL（`binary`）→ 严格 UTF-8（`non_utf8`）→ 4096 B 行长（`long_lines`，任一超长行整文件跳过）不变；之后按 D3 做 glob 过滤（`scannedFiles++` 保持在过滤前），再逐行匹配；每个 hit 与 context 构造完并 push 后做 sentinel 的 BigInt 比较。**此处不读时钟。**
- **页决策**（取代 `:573-635`）：删除早退守卫。`stopReason === null` 时置 `eof`。按 §5.6 顺序：源错误已在 walk 内抛出 → `offset > total` 时 `complete ? offset_out_of_range : search_scope_too_large`（先于切片与 `m=0`）→ 计算安全切片（`start=offset-1`，`end=min(total, start+limit)`，用 BigInt 后 clamp，转 `number` 前断言 `Number.isSafeInteger`）→ `m = slice.length`，cutoff 且 `m=0` → `search_scope_too_large` → 枚举 `k=1..m`，`best=null` → `hit_too_large` → cutoff 且非 `(k===m===limit)` 且非 `k<m` → `search_scope_too_large` → 成功。每个候选先无条件计算四域测量值（`jsonLen(value)`、`27+escapedLen(searchText(value))`、`meta=2`、`frameLen(value)`）再做合取，禁止短路；所有 `offset+count` 走 `addSafe`；`truncated`/`next_offset` 用 BigInt 判定。
- **空页**：`eof` 且 `offset==1 && total==0` 时构造规范空 value，过 `emptyMeasures(value, searchText(value))`；四域任一超 cap → `output_too_large`。空 `eof` 且 `offset>1` 仍 `offset_out_of_range`（先于预算检查，沿 W5 D6）。
- **trace**：`options.trace` 存在时在 walk 结束、任何页决策抛错之前写入 `{stopReason, nowCalls}`；成功页与 `search_scope_too_large`/`hit_too_large`/`output_too_large` 都携带它。否则无副作用。

#### list 路径

- **入口**（`:296-310`）：`options` 默认 `{caps: defaultCaps(), scanLimit: MAX_LIST_ENTRIES}`；传入 `caps` 与 `defaultCaps()` 浅合并；`listScan` 的 10000 字面量改为 `scanLimit`，计数口径不变（D4）。
- **空目录**（`:314-328`）：`offset !== 1` 仍 `offset_out_of_range`；否则构造空 value 过 `emptyMeasures(value, listText(value))`；四域任一超 cap → `output_too_large`。
- **候选循环**（`:332-357`）：cap 常量换 `caps.*`；`offset + count` 走 `addSafe`；每个候选先无条件计算四域（`jsonLen`/`27+escapedLen(listText)`/`meta=2`/`frameLen`）再逐项比较；`best === null` → `entry_too_large` 不变（现在可经注入 cap 触达）。

### `v24/s13/fixtures.py`（改，纯加法）

新增 `node_workspace(root, nodes)`（D16）。`build_spec` 在构建时复制插件并现算 sha256（`:346-396`），所以每次编辑 `fs_tools.js` 后 digest 自动重算，不存在手工同步旧值；W6-0 用 grep 确认无硬编码旧 sha。

### `v24/s13/test_tools.py`（改，纯加法）

- 新增 `js_call(script)`：以 `node -e` 引入 `PLUGINS/'fs_tools.js'`，执行脚本、stdout 输出 JSON，Python 侧解析；脚本统一返回完整 v2 envelope：成功 `{ok:true,v:2,result:{value},trace}`，失败 `{ok:false,v:2,error:{code,message},trace}`；`trace` 缺省为 `null`。`js_call` 返回该 envelope；失败供 `check_error` 使用，成功由 Python 侧取 `result.value` 再走 `check_value`。模式照 `selector_probe`（`:218-242`）。
- 新增严格 `check_error(payload, code, root)`：接受上述 envelope；校验 `ok is False`、`set(payload) - {"trace"} == {"ok","v","error"}`、code 精确相等、message UTF-8 ≤1024 B、且不含 workspace 绝对路径；`trace` 若存在必须是 `{stopReason,nowCalls}`。`expect_error` 改为 `invoke` 后调用它，JS 层失败也走同一函数。`output_too_large` 是 §5.6 的 ledgered 码，不额外要求闭集成员。
- 新增 `list_probes(base)`（返回 11）与 `search_probes(base)`（返回 26）；`main` 在 `read_probes` 之后累加（当前 `:695-696`），marker 在 `:734-738` 处扩展。
- 静态守卫（`:720-724`）保持；S24 追加「`process.env` 只在 `rootPath`」「`hrtime`/`Date.now` 只在 search 路径」「`addSafe` 已导出」三条源码断言；tamper 用 `spec.entry.require_artifact()`，`finally` 还原原始字节并复验 digest；host 透传子断言用 `line_json._classify_v2` 解 `output_too_large`/`invalid_tool_output` 的 exit-3 帧并断言 `known_error`，再用 `tool_results.failure_output` 断言 code 原样保留。

### Host、协议与并发边界（不变）

`v24/host/**` 零 diff。W6 不新增帧字段、不改 `line_json` 的 v2 解析、不改 `_spec_v2` 的 timeout 选取、不改租约预检。插件仍只读一行 stdin、写一行 stdout，stdout ≤ 64 KiB、stderr ≤ 16 KiB。

## 测试设计与向量覆盖

### 记号

- **直连**：`invoke(spec, tool, args)`，真实 Node 子进程，手工 v2 帧（`test_tools.py:151-169`）。
- **JS 层**：`js_call` 经 `node -e` 调导出函数，可传 `options`。
- **脚本时钟**：`now` 的第 N 次调用起返回 `>= deadline`；C0 是第 1 次，之后每个目录或 regular file 工作项一次。
- 树简写：`x` = `78 0a`（`"x\n"`），`y` = `79 0a`；同层按 name 的 UTF-8 bytes 排序。

### Search probe（S01–S26，计入 `search_probes`）

| # | 目的 | fixture | 路径 | 期望 |
|---|---|---|---|---|
| S01 | file-cap count-full | 10,001 files：`a0.txt`/`a1.txt`=x，`f00000..f09998`=y | 直连，`{"query":"x","limit":2}` | 成功：2 hits、`total:2`、`complete:false`、`scanned_files:10000`、`truncated:true`、`next_offset:3` |
| S02 | file-cap byte-full（`k<m`） | `a0/a1/a2.txt`=x，`z.txt`=y；`fileLimit:3`、`limit:3` | JS 层，`caps.value` 只容 1 条 | 成功：1 hit、`total:3`、`complete:false`、`next_offset:2`、`scanned_files:3` |
| S03 | file-cap before-fill | `a0.txt`=x，`y.txt`=y；`fileLimit:1`、`limit:2` | JS 层 | `search_scope_too_large` |
| S04 | file-cap before-offset | S02 树，`fileLimit:3`、`offset:5`、`limit:3` | JS 层 | `search_scope_too_large` |
| S05 | file-cap empty | `a.txt`/`b.txt`=y，`query:"none"`、`fileLimit:1` | JS 层 | `search_scope_too_large`（不得返回空 incomplete 成功页） |
| S06 | time-cap count-full | `a0/a1.txt`=x，`b0.txt`=y，`limit:2` | JS 层，第 4 次 `now` 起过期 | 成功：2 hits、`complete:false`、`next_offset:3`、`scanned_files:2`、`trace:{stopReason:"time-cap",nowCalls:4}` |
| S07 | time-cap before-fill | 同 S06，`limit:3` | JS 层 | `search_scope_too_large`，`stopReason:"time-cap"` |
| S08 | time-cap before-offset | 同 S06，`offset:5` | JS 层 | `search_scope_too_large` |
| S09 | time-cap empty | `a.txt`/`b.txt`=y，`query:"none"` | JS 层，第 3 次 `now` 起过期 | `search_scope_too_large` |
| S10 | EOF 优先 | (a) 仅 `a0.txt`（x），第 3 次调用起过期；(b) `a0.txt`+`a1.txt`，同一时钟 | JS 层 | (a) 成功、`complete:true`、`total:1`、`trace:{eof,nowCalls:2}`（证明无 walk 后检查点）；(b) 第 3 次调用在 `a1` 的 C1 到期 → `search_scope_too_large`、`nowCalls:3`（m=1 < limit 200） |
| S11 | sentinel 优先 | `a0/a1/a2.txt`=x，`b0.txt`=y；`limit:2` | JS 层，第 **5** 次起过期 | 成功：`a0,a1`、`total:3`、`next_offset:3`、`trace:{sentinel,nowCalls:4}`；`b0` 未被扫描（`scanned_files:3`） |
| S12 | 无适配前缀与搜索空页 | (a) `a0.txt`=x + `z.txt`=y；(b) 空树 | JS 层，`caps.value`/`caps.content`/`caps.meta`/`caps.frame` 各窄一档；另有 `fileLimit:1` 变体 | (a) `hit_too_large`（四域各一次；`fileLimit:1` + 同一窄 cap 时 `z.txt` 触发 file-cap，仍是 `hit_too_large`，先于 cutoff 判定）；(b) `eof,total:0,offset:1` → `output_too_large`（四域各一次）；`offset:2` 同窄 cap → `offset_out_of_range`（先于预算） |
| S13 | slashless glob | `src/a.py`、`src/sub/a.py`、`b.txt` | 直连，`glob:"*.py"`；再 `glob:"*.txt"` | `*.py` 两处都命中；`*.txt` 只命中 `b.txt` |
| S14 | 有 `/` 的 glob | 同 S13 | 直连，`glob:"src/*.py"`；`glob:"src/**/a.py"` | 前者只 `src/a.py`；后者两处 |
| S15 | `?` 与 `**` | `é.txt`、`a/b.txt` | 直连，`glob:"?.txt"`；`glob:"a/**/b.txt"` | `?.txt` 命中 2（`é.txt`、`a/b.txt` 的 basename `b.txt`），`a/**/b.txt` 命中 1（`a/b.txt`）；`?` 匹配单个非 `/` 字符，`**/` 可折叠。旧码 `?.txt` 只回 1，属旧红 |
| S16 | 安全整数输入、footer 与 helper 溢出 | `a.txt`=x | (a) 直连 raw 帧 `offset:9007199254740993` 与 `limit:9007199254740993`（list/search 各两次）；(b) JS 层 `offset:MAX_SAFE-10, limit:200`；(c) JS 层 `addSafe(2**53-1,1)`；(d) JS 层 `listText`/`searchText` 以 `offset:2**53-1` + 2 条记录（`listText` 另置 `truncated:true`） | (a) `invalid_path`；unsafe `offset` 旧代码红（旧码给 `offset_out_of_range`），unsafe `limit` 旧码也返回 `invalid_path`（>200），记旧绿；(b) `offset_out_of_range`，无舍入；(c) `invalid_tool_output`，无 `TypeError`、不写 JSON；(d) `invalid_tool_output`（footer 的 `offset+len-1` 不写出不安全整数） |
| S17 | glob 记账 | `a.txt`、`b.log`、`c.log` 均为 x | (a) 直连 `glob:"*.txt"`；(b) JS 层 `glob:"*.txt"`、`fileLimit:2` | (a) 1 hit、`scanned_files:3`（冻结 `glob_16` 语义）；(b) `search_scope_too_large`（glob 排除的 `b.log`/`c.log` 仍消耗预算；若 `regular++` 在 glob 后则只会看到 1 个 regular，得到成功页） |
| S18 | 预检顺序与单次计数 | `big`（>1 MiB 且含 NUL）、`binnul`（`00 ff`）、`badutf`（`ff`+4097×a）、`long`（单行 4097×a）、`ok.txt`=x | 直连，`query:"x"` | `skipped:{too_large:1,binary:1,non_utf8:1,long_lines:1,…}`、`scanned_files:1`、`total:1` |
| S19 | 超长行整文件跳过 | `longfirst`：`x\n` + 4097×a | 直连，`query:"x"` | `long_lines:1`、`scanned_files:0`、`total:0`、`complete:true` |
| S20 | context 渲染与计量 | `a.txt`：`c1\nx\nc3`，`context:1` | 直连 + host renderer | 文本 `path-1- c1` → `path:2:1: x` → `path-3- c3`；`27+E(text)` 与 `len(J(content))` 逐字节相等；path 每行重复；无尾 LF |
| S21 | column 是码点 | `a.txt`：`😀😀x`；`b.txt`：`éx` | 直连 | `column` 分别为 3 与 2 |
| S22 | 500 码点截断 | `a.txt`：`x` + 500×`😀` | 直连 | `text` 为 500 个码点、`text_truncated:true`；499/500 边界各一例 |
| S23 | hidden 与 `.git` | `.git/x.txt`、`.hidden/y.txt`、`.hid.txt`、`vis.txt` 均 x | 直连，`include_hidden` false/true | false：`skipped.hidden:2`、`total:1`；true：`hidden:0`、`total:3`；两种都绝不遍历 `.git` |
| S24 | 常量/结构/artifact/host 透传 | 源码 + 安装副本 | 进程内 + tamper（`require_artifact` + `try/finally`） | `SCAN_BUDGET_MS===12000`；search `timeout_ms===15000`；`15000-12000>=3000`；`process.env` 只在 `rootPath`；`hrtime`/`Date.now` 只在 search 路径；`addSafe` 已导出；host 透传：`line_json._classify_v2` 对 `output_too_large`/`invalid_tool_output` 的 exit-3 帧返回 `known_error`，`tool_results.failure_output` 保留 code；三方 sha 相等；翻转副本 1 B → `artifact_digest_mismatch`，`finally` 还原并复验 digest |
| S25 | 真实时钟观测 | 10,000 files（`y`），`query:"x"`、`budgetMs:50` | JS 层，默认 `now` | 结果恰为 `{complete:true,total:0,hits:[]}` 完整空成功或 `search_scope_too_large`；打印 `real_clock_elapsed_ms`/过冲；**不设 elapsed 阈值** |
| S26 | 候选枚举成本 | 200 files × 5 行 × ~4,000 B，`context:2`、`limit:200` | JS 层；probe 内临时包裹 `JSON.stringify`，`searchTool` 返回后立即还原，再序列化 probe 结果 | 成功页且 `k<200`；**硬断言是 600 次 `JSON.stringify`**（每候选先无条件计算四域：`jsonLen(value)`、`escapedLen(searchText(value))`、`meta=2`、`frameLen(value)`，再合取；200 候选）；`enum_cost_wall_ms` 只打印记录，不设阈值、不作 STOP |

计数：26 条 search probe。S24–S26 是证据 probe，仍执行并断言，计入 `search_probes`（D7）。

### List probe（L01–L11，计入 `list_probes`）

| # | 目的 | fixture | 路径 | 期望 |
|---|---|---|---|---|
| L01 | byte-full 的 k<limit 分页 | 200 个 255-byte 文件名的文件 | 直连，`limit:500` | `k = w1_reference.selectPrefix(...)` 的最大可行 k 且 `k<500`；`next_offset=k+1`；以 `next_offset` 再取一页能推进且 `total` 一致 |
| L02 | 注入 caps 的四域分支 | (a) 1 文件；(b) 空目录；(c) 空目录 `offset:2` | JS 层，value/content/meta/frame 各窄一档 | (a) `entry_too_large`（四域各一次）；(b) `output_too_large`（四域各一次）；(c) `offset_out_of_range`（先于预算检查） |
| L03 | 嵌套 `.git` 与扫描 cap | (a) `.git/x`、`d/.git/y`、`d/f`；(b) 同树；(c) 10,000 个可见文件；10,001 = 10,000 可见 + 1 hidden | (a) 直连 `recursive:true`；(b) JS 层 `scanLimit`；(c) 直连 `limit:1` | (a) `total:2`（`d`、`d/f`），两棵 `.git` 都不出现；(b) 4 个原始条目（`.git`、`d`、`d/.git`、`d/f`）：`scanLimit:4` 成功，`scanLimit:3` → `directory_too_large`；(c) 10,000 成功、`total:10000`；10,001 → `directory_too_large`（hidden 计入 cap） |
| L04 | hidden 子树 | `.h/a`、`.h/b`、`vis` | 直连 `recursive:true`，`include_hidden` false/true | false `total:1`；true `total:4`（`.h`、`.h/a`、`.h/b`、`vis`） |
| L05 | symlink 不跟随 | `d/f`、`dlink -> d`、`flink -> f` | 直连 `recursive:true` | 列出 `d`、`d/f`、`dlink`、`flink`，不递归进 `dlink`；`kind=symlink` 且 `size:null` |
| L06 | special 计数 | FIFO | 直连非递归 | `skipped_special:1`，FIFO 不出现在 `entries` |
| L07 | 根级非 UTF-8 条目 | 现有 `workspace(root,"list")`（根级 0xff、`a`、`a/child`、`b`、`c`、`.hidden`、`.git/config`、socket） | 直连非递归；macOS `preload_shim` 与 Linux `filesystem` 同断言 | `skipped_non_utf8:1`；0xff 名不在 `entries`；`total:3`（`a`、`b`、`c`）；`skipped_special:1`；**子目录非 UTF-8 不覆盖**（D16/Q1，记 `not_run`） |
| L08 | 路径 UTF-8 排序 | `B`、`a`、`é`、`～`、`😀`、`a-b`、`a/c` | 直连 `recursive:true`；非递归变体 | 递归顺序 `B,a,a-b,a/c,é,～,😀`（按 UTF-8 bytes，无 locale）；非递归只断言 `B,a,a-b,é,～,😀` |
| L09 | offset 与空目录 | 3 个文件的目录；空目录 | 直连 | (a) `offset:3, limit:500` → 1 条、`truncated:false`、`next_offset:null`；(b) `offset:4` → `offset_out_of_range`；(c) 空目录 `offset:1` 成功、`offset:2` → `offset_out_of_range` |
| L10 | 默认值等价 | 2 文件 + 1 子目录 | 直连，同一 spec 两次调用：全省略 vs 显式 `path:"."`、`recursive:false`、`include_hidden:false`、`offset:1`、`limit:500` | 两次 `result.value` 的 canonical JSON 逐字节相等；`total:3`、`truncated:false`、`next_offset:null` |
| L11 | content 逐字节一致 | (a) 非截断；(b) 截断；(c) 空目录 | 直连 + host renderer | `27+E(listText(value))` 与 `len(J(content))` 相等；footer 两 LF；空目录 `[empty directory]`；无尾 LF |

计数：11 条 list probe。L02/L03 的 cap 注入只走 JS 层；L10 是默认值等价；其余直连。

### 冻结覆盖与「不 promotion」

- 74 条冻结用例（`READ_CASES` 16、`LIST_CASES` 7、`SEARCH_INPUTS` 24、path/selector/shim/harness 其余）照旧执行，结果逐字节不变；`test_contracts.py`、`test_vectors.py`、`test_vectors.py --node` 零 diff。
- `tool.list.contract`、`tool.search.contract`、`tool.search_budget_file_count`、`tool.search_budget_timing_m3_pending`、`descriptor.v2.list`、`descriptor.v2.search` 的 `status` 与 `expected` 零改动。W6 只执行它们、记录证据，不 promotion。
- `test_tools.py:713-718` 的 `budget`/`timing` 断言保持原样（`file_count_exceed == search_scope_too_large`、`timing == not_frozen`、`deterministic_w1_pass is False`）。

### 红基线分类（W6-1，针对 `82e5440`）

| 类别 | probe | 说明 |
|---|---|---|
| 旧代码可运行且预期红 | S01、S13、S15、S16(a) raw unsafe-offset、S24 的常量/结构断言 | 用现有 `invoke`/`js_call` 对旧文件跑；记录真实红值。S15 旧码 `?.txt` 只回 1；S16(a) unsafe offset 旧代码给 `offset_out_of_range`，新期望 `invalid_path`。 |
| 旧代码可运行且预期绿（回归护栏） | S14、S17(a)、S18–S23、L01、L03(a)(c)、L04–L07、L08、L09、L10、L11 | 守行为不变；S03–S05 依赖 seam，改列 green-only，不得记红或绿。S16(a) 的 unsafe limit 子例旧码也返回 `invalid_path`，记旧绿。 |
| 需 seam，旧代码 green-only | S02–S12、S16(b)(c)(d)、S17(b)、S26、L02、L03(b)、S24 的 digest/host 透传子断言、S25 | 新 `options`/`caps`/`addSafe`/`emptyMeasures` 不存在；红基线记 `green-only`，不伪造红。S24 的常量断言旧代码红，digest/host 子断言旧代码可运行。 |

## Gate、证据与 scope audit

所有测试命令使用 credential-clearing 前缀：

```bash
ENVPFX="env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1"
```

**串行 32 条**（与 W5 执行记录同一顺序；W6 不新增命令）。每条命令前均加 `$ENVPFX`（包括第 32 条）：

1. `$ENVPFX uv run python v24/s13/test_pages.py`
2. `$ENVPFX uv run python v24/s13/test_wiring.py`（内置六项 scope audit）
3. `$ENVPFX uv run python v24/s13/test_descriptor.py`
4. `$ENVPFX uv run python v24/s13/test_schema.py`
5. `$ENVPFX uv run python v24/s13/test_renderers.py`
6. `$ENVPFX uv run python v24/s13/test_results.py`
7. `$ENVPFX uv run python v24/s13/test_registry.py`
8. `$ENVPFX uv run python v24/s13/test_line_json.py`
9. `$ENVPFX uv run python v24/s13/test_contracts.py`
10. `$ENVPFX uv run python v24/s13/test_vectors.py`
11. `$ENVPFX uv run python v24/s13/test_vectors.py --node`
12. `$ENVPFX uv run python v24/b0/test_golden.py`
13. `$ENVPFX uv run python v24/b0/test_golden.py --node`
14. `$ENVPFX uv run python v24/load.py`
15. `$ENVPFX uv run python v24/s1/setup_db.py --self-check`
16. `$ENVPFX uv run python v24/s1/test_ddl.py`
17. `$ENVPFX uv run python v24/s1/test_g1.py`
18. `$ENVPFX uv run python v24/s2/test_g3a.py`
19. `$ENVPFX uv run python v24/s3/test_g2.py`
20. `$ENVPFX uv run python v24/s4/test_g2b.py`
21. `$ENVPFX uv run python v24/s5/test_g4.py`
22. `$ENVPFX uv run python v24/s6/test_g5.py`
23. `$ENVPFX uv run python v24/s8/test_g7.py`
24. `$ENVPFX uv run python v24/s7/test_g6.py`
25. `$ENVPFX uv run python v24/s10/test_g9.py`
26. `$ENVPFX uv run python v24/s11/test_g10.py`
27. `$ENVPFX uv run python v24/s11/test_node.py --node`
28. `$ENVPFX uv run python -m v24.host.plugin_smoke --multilingual-smoke`
29. `$ENVPFX uv run python v24/s13/test_tools.py` — 唯一 marker 变化（Done when #9）
30. `$ENVPFX uv run python v24/s13/test_lifecycle.py`
31. `$ENVPFX uv run python v24/s13/test_node.py --node`
32. `$ENVPFX git diff --exit-code c8c4bd0 -- v24/sql`

三态：命令 1–31 需 exit 0 且末行为命令专属 `[passed]`；命令 32 需 exit 0 且输出为空，没有 `[passed]` 标记。exit 2/`[SKIP]` 阻塞 W6。closeout 仍 **11/11**；s13 不是第 12 条 closeout。

**Scope audit（七项）**：

1–6 沿用 W4c/W5 的六项，钉 `c8c4bd0`：冻结模块与 s13 测试、冻结向量（除 design 元数据）、`design_conformance` 还原相等、`registry.py` D12 精确 patch、host import purity、SQL 零 diff。第 3 项按 W4c 的还原相等执行：把当前 design SHA 行替换回 `c8c4bd0` 的值后逐字节相等；W6 不改 design，所以该行相对 HEAD 也应零 diff。

7（W6 新增）：W6-0 先用 `git ls-files --others --exclude-standard` 枚举 untracked 文件，并快照每个文件的 sha256（`baseline-untracked.txt`，每行 `<sha256>  <path>`）；审计算 W6 delta = `git diff --name-only 82e5440 --` ∪ `{当前 untracked 中路径或 sha256 与快照不同的文件}`（新增、内容变化、以及快照中已消失的路径都算 delta）。delta 必须是 candidate 路径的子集，否则 STOP。candidate 集合：

- `v24/s13/plugins/fs_tools.js`
- `v24/s13/fixtures.py`
- `v24/s13/test_tools.py`
- `v24/s13/README.md`
- `docs/reviews/v24-conformance-matrix-2026-10-23.md`
- `docs/reviews/v24-deviation-ledger-2026-10-23.md`
- `docs/reviews/v24-tool-plugin-abi-w6-execution-2026-10-31.md`
- `docs/reviews/v24-tool-plugin-abi-w6-plan-critique-2026-10-31.md`
- `docs/plans/v24-tool-plugin-abi-w6-node-list-search-2026-10-31.md`

**证据目录** `/tmp/w6-<UTC>/`：

- `provenance.txt`（HEAD/branch/upstream/uv/python/node/OS 版本）
- `git-status-porcelain.txt`（初始与最终）
- `source-sha256.txt`（candidate 路径，含 `fs_tools.js` 的 source/copy/entry sha）
- `baseline-untracked.txt`（W6-0 的 untracked 文件快照，每行 `<sha256>  <path>`；audit 7 的路径与内容差分基线）
- `credential-scan.txt`（脱敏）
- `red-baseline.log`（W6-1）
- `01.log`–`32.log`、`results.tsv`（命令、UTC 开始、exit、真实末行、log sha256）、`merged.log`
- `scope-audit.tsv`、`scope-1..7.log`

执行记录体例照搬 W4c：Result、Candidate and provenance、Implementation and coverage、Scope and compatibility audits、Deviations、Limits、Publication。**不得**记录 API key；凭据扫描命中即 STOP。

## 工作项与执行索引

| # | Goal | Done when | Key files | Deps | Size |
|---|---|---|---|---|---|
| W6-0 | candidate、provenance、基线确认 | HEAD `82e5440`、porcelain 与 untracked **路径+sha256** 快照已记录；确认三个改动文件不在 frozen 列表；grep 无硬编码旧 sha；复核 `tool_contracts.json`/`results_v2.json`：无 slashless glob 配嵌套树，`glob_18 '?.txt'` 仅根级；读完 U1–U5（U1/U5 已由本计划判定，只需复核）；核对本计划引用的 file:line | 证据目录、本计划 | — | S |
| W6-1 | 红基线（按 probe 可执行性） | S01/S13/S15/S16(a) raw unsafe-offset/S24 常量断言对旧代码记录真实红值；S03–S05 归 green-only（旧码成功或 `offset_out_of_range`）；S17(a)、L01、L03(a)(c)、L04–L11 等绿组作为回归护栏；green-only 组标记清楚；冻结 74 例先跑一遍确认基线绿 | `test_tools.py`（草稿）、`fixtures.py` | W6-0 | S |
| W6-2 | search 停止状态机、页决策与测试 seam | `stopReason` 四态；删除早退守卫；§5.6 后置判定与失败次序；`options`/`defaultCaps`/`emptyMeasures`/`caps.meta`/基础导出（`addSafe` 随 W6-4）；S01–S05（file-cap 五类）、S12、S26 绿 | `fs_tools.js`、`test_tools.py`（probe 接线） | W6-1 | L |
| W6-3 | 12 秒预算与时钟 seam | `SCAN_BUDGET_MS`、C0/C1、injected clock、trace；S06–S11、S24（常量部分）、S25 绿 | `fs_tools.js` | W6-2 | M |
| W6-4 | glob 与安全整数 | `{regex,basenameOnly}`；BigInt/`isSafeInteger`；`addSafe` 导出；S13–S17 绿 | `fs_tools.js` | W6-2 | M |
| W6-5 | list 侧边界 | 空页四预算；`caps`/`scanLimit` 消费；L02–L11 绿（S12 已在 W6-2） | `fs_tools.js`、`fixtures.py` | W6-2、W6-3、W6-4 | M |
| W6-6 | 全量 sweep（预检） | 32 条命令全绿；marker 与 Done when #9 一致；七项 audit 预检通过 | `test_tools.py` | W6-5 | S |
| W6-7 | 收尾工件与最终 audit | README、matrix、ledger、执行记录落盘；七项 audit 在 staging 前重跑；Result 只填实测值 | 五个文档 | W6-6 | M |
| W6-8 | 提交与推送 | 按路径逐个 `git add`、正常 hook、单个 `v24: close out Node list and search tools` 提交、非 force 推送 | — | W6-7 | S |

依赖图：

```text
W6-0 → W6-1 → W6-2 → { W6-3 → W6-5 , W6-4 → W6-5 } → W6-6 → W6-7 → W6-8
```

- W6-3 与 W6-4 改同一文件的不同函数，串行落地；它们的 probe 可并行起草。
- W6-5 依赖 W6-2（`options`/`caps`/`emptyMeasures`）、W6-3（时钟）与 W6-4（`addSafe`/glob），所以放在三者之后。
- W6-6 只有在 W6-5 全绿后才能写「实测」字样；W6-7 的 Result 不得预填。

## File-by-file impact

| 文件 | 变更 | 依据 | 顺序 |
|---|---|---|---|
| `v24/s13/plugins/fs_tools.js` | `stopReason` 状态机、post-selection 页决策、`SCAN_BUDGET_MS`/C0/C1、`{regex,basenameOnly}`、`addSafe`/`isSafeInteger`（含 footer）、空页四预算、`caps`/`scanLimit`、导出 | §5.6 `:765-787`、§6.1 `:790-801`、§6.3 `:827-878`、§3.4 `:409-435` | W6-2 → W6-3 → W6-4 → W6-5 |
| `v24/s13/fixtures.py` | 新增 `node_workspace(root, nodes)` | D16；模式同 `read_workspace:267-292` | W6-5 |
| `v24/s13/test_tools.py` | `js_call`（v2 envelope）、`check_error`、`list_probes`（11）、`search_probes`（26）、L10 默认值、S26 600 次断言、S24 host 透传、marker/静态守卫扩展 | D6/D7；`design:890-936` 的 §7.1 清单 | W6-1 起草，W6-2/W6-5 完成 |
| `v24/s13/README.md` | 追加 W6 小节：marker、37 条 probe、三层 12 s 证据、`linux_real` 取值 | W4b/W5 小节体例 | W6-7 |
| `docs/reviews/v24-conformance-matrix-2026-10-23.md` | 追加 W6 子节：list/search 覆盖、timing/cutoff 行、M3 仍 pending | 该文件 W2/W5 子节体例 | W6-7 |
| `docs/reviews/v24-deviation-ledger-2026-10-23.md` | 追加 `D-ABI-W6-1..14` | `:615-623` 体例 | W6-7 |
| `docs/reviews/v24-tool-plugin-abi-w6-execution-2026-10-31.md` | 新建执行记录（W4c 体例） | `AGENTS.md` 收尾工件要求 | W6-7 |
| `docs/plans/...-w6-node-list-search-2026-10-31.md` | 填 Result、Oracle 裁决记录 | 本计划 | W6-7 |

**Ledger 条目**（写入 deviation ledger，W6-7）：

| 条目 | 内容 |
|---|---|
| `D-ABI-W6-1` | §6.3 `:871` 说 `scanned_files` 只计「尝试 literal 匹配」的文件；冻结 `glob_16` 钉死 glob 排除文件 `scanned_files:1`。冻结字节胜出；插件保持「预检通过即计数」。 |
| `D-ABI-W6-2` | 12 s 预算的证据标准是「确定性注入时钟分支 + 常量断言 + 一次真实观测」，不是墙钟保证；`tool.search_budget_timing_m3_pending` 保持 `m3_pending`。 |
| `D-ABI-W6-3` | 预算检查点收窄为 C0（walk 前）+ C1（目录递归前、regular file 的 file-cap 检查后）；过冲上界是「一次 `readdir` + 对结果逐条按名过滤（hidden/`.git`/非 UTF-8 不 `lstat`）+ symlink 的 `lstat`/分类 + 一个 ≤1 MiB 文件的读取与扫描」；hidden/`.git`/非 UTF-8 在 `lstat` 前被过滤，只有 symlink 会 `lstat` 后跳过。 |
| `D-ABI-W6-4` | §5.6 的空页 `output_too_large` 不在 list 12 码/search 13 码闭集内；插件按 §5.6 发出，host 原样透传。`invalid_tool_output` 的页关系校验仍由 host 负责；§5.6 第 5 步的安全整数失败由插件发出，见 `D-ABI-W6-9`。 |
| `D-ABI-W6-5` | `entry_too_large` 在内建 cap 与合法 path（≤1024 B）下不可达，保留为防御码；仅经注入 caps 证明。 |
| `D-ABI-W6-6` | list 的 10000 扫描 cap 计入所有 `readdir` 原始条目（含 `.git`/hidden/symlink/special/非 UTF-8）；`state.scanned` 跨整个递归共享，`include_hidden=false` 时不下降进隐藏子树、只计隐藏根一条，`.git` 计 1 次且不下降。 |
| `D-ABI-W6-7` | glob 排除的 regular file 消耗 10000 file 预算（`regular++` 在 glob 前）；与「文件数量预算包含因预检跳过的 regular files」一致。 |
| `D-ABI-W6-8` | 2^53 级 `offset` 由 `isSafeInteger` 判为 `invalid_path`；生产路径实际不可达（`_tool_v2` 第 2 步已用 `canonical._safe_integer` 返回 `invalid_tool_arguments`、零 spawn），该分支只由直连帧证明，属防御性。 |
| `D-ABI-W6-9` | §5.6 第 5 步的「无法形成安全整数 cursor/统计」由插件发 `invalid_tool_output`；该码不在 list 12 码/search 13 码闭集内，与 `D-ABI-W6-4` 同型，host 原样透传。Q2 裁决；`addSafe` 溢出只经 JS probe 证明，生产不可达。 |
| `D-ABI-W6-10` | 早退守卫 `scopeExhausted && total < offset+limit` 由 §5.6 的后置页判定取代：cutoff 页只在 `k=m=limit` 或 `k<m` 时成功，`complete` 只在 `stopReason==="eof"` 时为 true。 |
| `D-ABI-W6-11` | slashless glob 只匹配 `basename(relPath)`；含 `/` 的 glob 仍匹配 `relPath`；`*`/`**`/`?` 展开不变。 |
| `D-ABI-W6-12` | 测试 seam 是可选第三参数 `options`（`now`/`budgetMs`/`fileLimit`/`scanLimit`/`caps`/`trace`），不引入 env/argv 开关；`module.exports` 仅为 `node -e` 测试扩展，生产路径不传 `options`。 |
| `D-ABI-W6-13` | W4 O8=B 的后续 owner 落地：W6 补可注入/虚拟时钟的 cutoff 证据，但不改 O8=B 的「M3 实现完成，timing/cutoff pending」声明措辞；`tool.search_budget_timing_m3_pending` 仍 `m3_pending`。 |
| `D-ABI-W6-14` | `linux_real` 在 macOS 为 `not_run`，Linux `filesystem` 模式为 `filesystem`；W6 验收在 macOS 执行，不把 Linux real 结果纳入。L07 只证明根级非 UTF-8 条目，子目录注入不覆盖（Q1）。 |

**明确不变**：`v24/host/**`、`v24/sql/**`、`v24/s13/vectors/**`、`docs/designs/**`、`v24/s13/plugins/fs_read.py`、`w1_reference.js`/`w1_reference.py`、`test_lifecycle.py`/`test_node.py`、`test_contracts.py`/`test_vectors.py`、`manifest_adapter_v2.json` 的 `m3_pending`、`design_conformance.json`。

## 风险、STOP 与回滚

| # | 风险 | 触发 | 处置 |
|---|---|---|---|
| 1 | 改坏 sentinel 记账 | `total` 不再含 sentinel，或页含 sentinel | STOP：冻结 `incomplete_nonempty`/`cutoff_count_full` 会红；按 `design:773` 恢复 |
| 2 | 把 `scannedFiles++` 移到 glob 之后 | S17(a) 得到 1 而非 3，`glob_16` 红 | STOP：D3 已由冻结字节判定，回滚该改动 |
| 3 | 预算检查点过密 | 在 hit/line 边界读时钟，产出半个 context 或 flaky | STOP：只保留 C0/C1；若确需更密，先改 D8 与台账再实现 |
| 4 | 页决策顺序错 | 先判 cutoff 再判 `m=0`，或先判 `hit_too_large` 再判 cutoff | STOP：按 §5.6 六步与 S06–S12 的顺序断言 |
| 5 | BigInt 混用 | 把 BigInt 写进 JSON（`JSON.stringify` 抛 TypeError） | STOP：只在比较/算术前用 BigInt，写回前转 `Number` 并断言安全；无法安全则 `invalid_tool_output`，不得写回舍入值 |
| 6 | 注入 seam 泄漏到生产 | `process.env`/argv 新开关；静态守卫红 | STOP：seam 只能是第三参数；守卫保持 |
| 7 | 墙钟 gate 混入 | 断言 12 s 内完成 | STOP：C.16/W4 D10 明确禁止；S25 只记录 |
| 8 | 改 design/向量「让 gate 变绿」 | `DESIGN_SHA256`、`design_conformance`、`vectors/**` 出现 diff | STOP：scope audit 第 2/3 项会红；回滚 |
| 9 | 候选枚举退化 | S26 的 `JSON.stringify` 计数不等于 600（`enum_cost_wall_ms` 仅记录，不作 gate） | STOP 并人工复核；不得靠放宽 cap 或跳过候选解决 |
| 10 | host deadline 先到 | 同步 `readdir`/`readFile` 无法中途取消，越过 15000 ms；host 判 unknown `timeout`，不是 `search_scope_too_large` | STOP：保留 journal 与证据，人工复核；不得抬 cap 或改成墙钟 gate |
| 11 | S01/冻结 10k 用例受真实 12 s 预算影响 | 慢盘/CI 上 12000 ms 先到，S01 得到 `time-cap` 而非 `scanned_files:10000` | 记录为环境异常并复跑；不放宽 cap、不改 S01 断言、不伪造计数；复跑仍红则 STOP |

**回滚**：W6 只动一个生产文件；任何 STOP 都先 `git checkout -- v24/s13/plugins/fs_tools.js`（以及 `fixtures.py`/`test_tools.py`）回到 `82e5440`，保留证据目录与红基线日志，不 reset 其他路径。

## 提交与推送

按 `AGENTS.md`：测试全绿 → 更新收尾工件 → 按路径 `git add` → 复查 staged → commit → `git push origin main`。提交信息：`v24: close out Node list and search tools`。**不得** `git add -A`/`git add .`，**不得** `--no-verify`，**不得** force-push。

**不得进入提交**：`docs/investigations/v24-m3-budget-closeout-2026-10-31.md`、`prompt-exports/`、`.ctx-export-*.txt`、`.token-probe*.txt`、`ctx_export_check*.txt`、`v20/experiments/ce_native_d5/`。

## W6 不证明什么

- 不声明 M3 完成；`tool.search_budget_timing_m3_pending` 仍 `m3_pending`，C.18 与 M3 声明属后续阶段。
- 不证明 12 秒墙钟保证；只证明分类分支、常量与一次观测。
- 不证明 Linux real 非 UTF-8；macOS `linux_real=not_run`，Linux `filesystem` 模式仅打印 `linux_real=filesystem`，W6 验收不纳入 Linux 结果。
- 不证明 macOS 子目录非 UTF-8 注入；L07 只覆盖根级 0xff 条目（`D-ABI-W6-14`）。
- 不证明同步 `readdir`/`readFile` 可被取消：越过 host 15 s deadline 的结果是 unknown `timeout`，不是插件 cutoff；出现即 STOP。
- 不 promotion 任何冻结向量的 `status`；不把「执行 pending case」读成「case 已验证」。
- 不证明服务端游标/快照分页；`design:874` 的 O(n²) 重扫仍是 v1 语义。
- 不证明慢盘/巨目录下的分页收敛；S25 只记录一次真实观测。

## 批判意见落实

来源：`docs/reviews/v24-tool-plugin-abi-w6-plan-critique-2026-10-31.md`。15 条 findings 与 Q1/Q2 全部落实；未改变已冻结的 D3、`27+E(text)`、O1–O6、`cases=140`。

| # | 级别 | 处置 |
|---|---|---|
| 1 | blocker | 32 条命令全部加 `$ENVPFX` 前缀（1–31 为 `uv run python`，第 32 条为 `git diff`）；命令 28 改为 `$ENVPFX uv run python -m v24.host.plugin_smoke --multilingual-smoke`；顺序/条数不变。 |
| 2 | blocker | S10(a) 注入第 3 次调用过期（实际只到 `nowCalls:2`）；S11 改为第 5 次过期，保留 `nowCalls:4`/`sentinel`。 |
| 3 | blocker | L03(a) 期望改为 `total:2`（`d`、`d/f`）；同树 4 个原始条目，`scanLimit:4` 成功、`3` 失败。 |
| 4 | blocker | L08 改 `recursive:true`，并保留非递归根层变体。 |
| 5 | blocker | L07 改为根级 0xff（现有 workspace/shim）；子目录注入不覆盖，记 `D-ABI-W6-14`；Q1 取保守口径。 |
| 6 | blocker | S25 结果集改为「完整空成功或 `search_scope_too_large`」，删除 incomplete 空成功；无 elapsed gate。 |
| 7 | should-fix | L10 恢复为省略 vs 显式默认值的逐字节等价；10000/10001 cap 移入 L03(c)。 |
| 8 | should-fix | D12 红基线重建为三类；S15 归旧红，S17(a)、L01、L08、L09、L10 归旧代码绿；S03–S05、S26、L02、L03(b) 归 green-only；S16(a) raw 与 S24 常量归红。 |
| 9 | should-fix | D11 覆盖 footer；导出 `addSafe`；S16(c) 断言 `invalid_tool_output`；S16(d) 覆盖 renderer overflow。 |
| 10 | should-fix | `emptyMeasures(value,text)`；四域都检查（含 `meta=2`）；L02/S12 参数化四域；S12 增加 search 空页 `output_too_large` 与 offset 优先级。 |
| 11 | should-fix | D14 删除 monotonic 依据，改为全前缀枚举 + S26 600 次 `JSON.stringify` 结构断言；结构计数是唯一硬判据，`enum_cost_wall_ms` 只记录，不设墙钟阈值。 |
| 12 | should-fix | 新增严格 `check_error`（envelope/code/message/path），`expect_error` 与 `js_call` 共用。 |
| 13 | should-fix | 证据目录加 `baseline-untracked.txt`（路径+sha256）；ledger 扩到 `D-ABI-W6-1..14`，补五类被窄化主题。 |
| 14 | should-fix | 风险 #10 与「不证明」补 host deadline unknown `timeout`；不抬 cap、不改墙钟 gate。 |
| 15 | nit | S24 tamper 用 `require_artifact()` + `try/finally` 还原并复验 digest。 |
| Q1 | 已决 | 取「根级 + 显式子目录限制」；不扩 test-only shim 与 candidate 集合。 |
| Q2 | 已决 | 取 §5.6 的 `invalid_tool_output`，不取 `io_error`；记 `D-ABI-W6-9`。 |

## Oracle 复核落实（2026-10-31，CONDITIONAL GO）

来源：2026-10-31 Oracle 复核（2/2 lanes：`claude-opus-5-5`、`gpt-6.1-sol-xhigh`）。裁决 **CONDITIONAL GO**：无 NO-GO 级合同冲突，O1–O6/Q1/Q2 不变；21 条中 6 条必改、14 条应修、1 条驳回。下表逐条落实到正文；均为计划文本/证据契约修正，不改变 `cases=140`、D3、`27+E(text)` 与冻结向量，也不要求改 `fs_tools.js` 产品代码。

| # | 级别 | 处置 |
|---|---|---|
| 1 | 必改 | S15 与 D13 冲突：`?.txt` 期望改为 2（`é.txt`、`a/b.txt` 的 basename `b.txt`），S15 从旧绿移到旧红；见 S15/D12。 |
| 2 | 必改 | S03–S05 依赖 `fileLimit`/caps seam，从旧绿移到 green-only；S26 同样归 green-only；见 D12。 |
| 3 | 必改 | S26 的候选循环先无条件计算四域再做合取，禁止 `&&` 短路；S26 指定到 W6-2；见 D14/S26/W6-2。 |
| 4 | 必改 | `js_call` 统一返回完整 v2 envelope；`check_error` 接受 envelope；`searchTool` 在 walk 结束后、页决策抛错前写 trace；见组件设计/test_tools。 |
| 5 | 必改 | W6-2/W6-5 重切：`options`/`defaultCaps`/导出面/`emptyMeasures`/`caps.meta`/S12 搜索空页归 W6-2；W6-5 只做 list 侧，依赖改为 W6-2+W6-3+W6-4；见工作项。 |
| 6 | 必改 | S17(b) 补 `glob:"*.txt"`；没有 glob 时 3 个 regular 也会触发 file-cap，无法区分「glob 排除文件是否消耗预算」；见 S17。 |
| 7 | 应修 | 错误路径 trace：`search_scope_too_large`/`hit_too_large`/`output_too_large` 也要带 `{stopReason,nowCalls}`；由第 4 条统一解决。 |
| 8 | 应修 | S17(b) 补 glob 的具体断言；由第 6 条解决。 |
| 9 | 应修 | C1 原先在 file-cap 之前，违反 D8 的 file-cap > time-cap 优先级；改为目录递归前、regular file 的 file-cap 检查后；见 D8/searchWalk。 |
| 10 | 应修 | S01/冻结 10k 用例受真实 12 s 预算影响；记风险 #11，慢环境复跑，不放宽 cap。 |
| 11 | 应修 | W6-0 增加冻结 glob 审计：`tool_contracts.json`/`results_v2.json` 无 slashless glob 配嵌套树，`glob_18 '?.txt'` 仅根级；见 W6-0。 |
| 12 | 应修 | host 对 `output_too_large`/`invalid_tool_output` 的透传无 probe；S24 增加 exit-3 帧的 `_classify_v2` + `failure_output` 子断言。 |
| 13 | 应修 | `hits.slice(offset-1, offset-1+limit)` 仍是普通数；slice 改用 BigInt 计算 + clamp，并写明非空 complete 的 `offset>total` 分支；见 D11/页决策。 |
| 14 | 应修 | `$ENVPFX` 未实际加到命令；32 条命令全部加前缀（含第 32 条）。 |
| 15 | 驳回 | U4 是「若用 spawn log」条件句，不是事实断言；不改。 |
| 16 | 应修 | D14/S26 的 1500 ms 人工 STOP 读起来像墙钟阈值；删除，结构计数是唯一硬判据。 |
| 17 | 应修 | Linux 上 `linux_real` 实际打印 `filesystem`；改为 macOS `not_run`、Linux `filesystem`，并同步 Done when #9、D-ABI-W6-14、「不证明」。 |
| 18 | 应修 | untracked 基线只记路径不能发现内容变化；改为 `<sha256>  <path>`，audit 7 比较路径与 sha256。 |
| 19 | 应修 | S16 补 unsafe `limit` 直连变体；unsafe `limit` 旧码也返回 `invalid_path`，记旧绿。 |
| 20 | 应修 | `D-ABI-W6-3` 误称 hidden/`.git`/非 UTF-8 的 `lstat` 计入过冲；这些在 `lstat` 前按名过滤，只有 symlink 会 `lstat`；已改正。 |
| 21 | 应修 | 批判落实抽核发现 #11 仍有 1500 ms 残留；由第 16 条修正，并在 `## 批判意见落实` 同步。 |

## Oracle 裁决记录

裁决日期 2026-10-31；两条 lane（`claude-opus-5-5`、`gpt-6.1-sol-xhigh`）均完成，六项一致采纳推荐，无冲突。偏好/范围型判断已标注，并按保守默认取值；用户可覆盖。

| # | 决策 | 裁决 | 依据 | 置信度 | 推翻条件 |
|---|---|---|---|---|---|
| O1 | D1 12 s 证据标准 | **A**：注入时钟经生产 `searchTool` + 常量断言 + 一次真实观测，无墙钟 gate | C.16 `:1380-1385` 把 12 s 定为插件内部量；W4 D10 拒 `sleep(12)`；`deterministic_w1_pass:false` 描述的是 W1 证不了耗时，不是要求实时 gate | 工程 高 / 意图 中（**产品判断**：「12 s 已证明」指什么） | 用户明确要求实时保证（B），或决定 v1 删掉 12 s（C，需改 design 与向量） |
| O2 | D2 design C.18 | **design 零 diff**，C.18 留给 M3 声明阶段 | W6 不声明 M3；clock seam 是第三参数，不触碰 C.17 §4 的 env/argv 禁令与 `test_tools.py:720-724` 守卫，W6 无须 design 授权；repin 会把 25 个 span 拖进 audit | 高（**范围判断**，保守默认） | W6 因其他原因必须改 design（届时把 C.18 一并折入并原子 repin），或用户把 M3 声明并入 W6 |
| O3 | D8 检查点 | **(a)** 只用 C0 + C1 | `design:774` 要求在 item 边界检查；hit/context 构造（`fs_tools.js:444-482`）必须原子；(b)/(c) 会把 stopReason 落进单文件内部，破坏「完整 hit 才算观察到」 | 中-高 | S25 实测过冲 ≥ 3000 ms 余量；或出现单个工作项无界的证据 |
| O4 | D4 list cap 口径 | **(a)** 每个 `readdir` 原始条目都计数 | `fs_tools.js:256-258` 现状；§6.3 `:847` 写的是「扫描超过」；(b) 让堆满隐藏/特殊条目的目录绕过 DoS 边界 | 中-高 | design 或冻结向量把 cap 定义为过滤后计数；或某冻结 case 含 hidden 条目且总数 >10000 却期望成功 |
| O5 | D11 不安全 offset | **(a)** `Number.isSafeInteger` 拒绝 → `invalid_path` | 现插件对非法 offset/limit 已用 `invalid_path`（`:546` 同段），W5 D10 同例；(b) 会对舍入值作答；(c) 不在 12/13 码闭集 | 高 | 经审查的码表修订引入参数类错误码；或冻结向量钉死不安全 offset 的另一分类 |
| O6 | D7 marker | **(a)** 计入，`cases=140`（103+11+26） | W5 R28/R29 证据 probe 计入 `cases=103`；`cases` 是实际执行并断言的数 | 高（**计数惯例**，按先例） | 用户要求 marker 只计行为 probe（改为 137，并同步 Done when #9） |

**批判 Q1/Q2 的补充裁决（2026-10-31）**

- **Q1 = 根级 + 显式子目录限制。** W6 是收口而非扩 fixture：现有 `workspace(root,"list")` 已提供根级 0xff，preload 只注入配置根 realpath；为子目录注入新增 shim 改动会把 test-only 资产扩进 candidate 集合。L07 只证明根级，macOS 子目录记 `not_run`；`linux_real` 在 macOS 为 `not_run`，Linux `filesystem` 模式为 `filesystem`（`D-ABI-W6-14`）。
- **Q2 = `invalid_tool_output`。** `addSafe` 溢出属 §5.6 第 5 步「无法形成安全整数 cursor/统计」，该条明确判 `invalid_tool_output`；`io_error` 虽在闭集内但不符合该条。该码与 `output_too_large` 同型地由插件发出、host 原样透传，记 `D-ABI-W6-9`。两者都不改变 O1–O6。

**裁决附带的验证细化（已并入正文）**

1. `D-ABI-W6-3` 的过冲上界改正为「一次 `readdir` + 对结果逐条按名过滤 + symlink 的 `lstat`/分类 + 一个 ≤1 MiB 文件的读取与扫描」；hidden/`.git`/非 UTF-8 在 `lstat` 前被过滤，只有 symlink 会 `lstat` 后跳过（O3）。
2. S26 的硬判据改为 **600 次 `JSON.stringify`**（每候选先无条件计算四域，再合取；200 候选），`enum_cost_wall_ms` 只打印记录，不设阈值（O6）。
3. `D-ABI-W6-8` 写明生产路径不可达：`_tool_v2` 第 2 步的 `compact_json(args)` 经 `canonical._safe_integer` 返回 `invalid_tool_arguments`、零 spawn（`plugins.py:137-146`、`canonical.py:118-120`）；插件分支只由直连帧证明（O5）。
4. `D-ABI-W6-6` 写明 `state.scanned` 跨递归共享、隐藏子树只计根、`.git` 计 1 次不下降（O4）。
5. `D-ABI-W6-2` 写明：C.18 应在 M3 声明阶段追加，绑定三层证据并显式接受「第三参数 seam」，后续阶段不必重新论证（O2）。

## References

- `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md`：§3.4 `:409`、§5.2、§5.3.1 `:688`、§5.6 `:765`、§6.1 `:790`、§6.3 `:827`、§7.1 `:890`、§7.3 `:937`、§7.4 `:952`、附录 C.11–C.17 `:1185-1395`、C.16 `:1380`、C.17 `:1386`。
- `docs/plans/v24-tool-plugin-abi-w5-python-read-2026-10-31.md`（同体例先例）。
- `docs/plans/v24-tool-plugin-abi-w4-dispatcher-worker-wiring-2026-10-31.md`（W4a/b/c 切分、O8 裁决 `:860-888`、D10）。
- `docs/reviews/v24-tool-plugin-abi-w4b-execution-2026-10-31.md`、`...-w4c-execution-2026-10-31.md`、`...-w5-execution-2026-10-31.md`。
- `docs/reviews/v24-conformance-matrix-2026-10-23.md`（W2/W5 子节）、`docs/reviews/v24-deviation-ledger-2026-10-23.md:615-623`。
- `docs/reviews/v24-tool-plugin-abi-w6-plan-critique-2026-10-31.md`（本计划已落实的 15 条 findings 与 Q1/Q2）。
- `v24/s13/plugins/fs_tools.js`、`v24/s13/fixtures.py`、`v24/s13/test_tools.py`、`v24/s13/test_node.py`、`v24/s13/w1_reference.js`、`v24/s13/w1_reference.py`。
- `v24/host/{tool_pages,tool_results,line_json,process_io,plugins,registry}.py`。
- `v24/s13/vectors/{README.md,tool_contracts.json,results_v2.json,descriptor_v2.json,manifest_adapter_v2.json,design_conformance.json}`。
- `docs/investigations/v24-m3-budget-closeout-2026-10-31.md`（未跟踪；只作缺陷复现来源，不进入提交；其行号不采用）。
- `AGENTS.md`。

## Result

**执行完成（2026-10-31）。** 基线为 `main` @ `82e5440012c2fa38a9ec63f86acc8c676a7ab500`（W5 closeout）；候选为 9 个路径，证据目录 `/tmp/w6-20261031T113313Z/`。

- **32 条命令：** 第一条 `2026-10-31T11:43:16Z` 开始，第 32 条 `2026-10-31T11:45:24Z` 开始；32/32 exit 0。第 1–31 条末行为各自命令专属 `[passed]`；第 32 条为 `git diff --exit-code c8c4bd0 -- v24/sql`，exit 0、输出为空、无 `[passed]`。无 exit 2/`[SKIP]`。命令、UTC、exit、末行与 log SHA 见 W6 execution record 的 32 行表。
- **实际 marker：** `[passed] W4 fs tools; cases=140; read=16; read_probes=29; list=7; list_probes=11; search=24; search_probes=26; pagination_converged=true; page_contracts_imported=3`。
- **`fs_tools.js` SHA-256：** source、installed copy、approved entry 均为 `efd05d63f028f0da4de333684dc3e63f506302f5a1c52a26c95efe36297348e5`（S24 三方相等；翻转副本 1 B 得 `artifact_digest_mismatch`，`finally` 还原并复验）。`fixtures.py` 为 `f2b5b84d9539ad9580645cabb15bf92dd169bb6a75b00c2eb1f25f069ac99bf5`，`test_tools.py` 为 `4df195f18d9583d920e64b1e5a5715d3626b97abdc00ffb0313651879d992d92`。
- **七项 audit：** precheck 与文档后 final 均 7/7 exit 0，末行分别为 `[scope] passed frozen_modules_and_untracked`、`vectors_except_design_conformance`、`design_conformance_restore`、`registry_exact_patch`、`host_import_purity`、`sql_zero_diff`、`w6_candidate_only`。前六项钉 `c8c4bd0`；第 7 项为 `82e5440` 的 tracked delta ∪ changed/new/removed untracked（path+sha256）且为 9-path candidate 子集。
- **S25 / S26：** S25 `real_clock_elapsed_ms=50.331`，过冲 `0.331`（`budgetMs=50`），结果落在允许集；只记录，不设墙钟阈值。S26 `enum_cost_wall_ms=126.674`，硬断言为 200 候选 × 3 域 = **600 次 `JSON.stringify`**。
- **U1–U4：** U1 由冻结 `glob_16` 确认 glob 排除文件仍计 `scanned_files`（D3 保持预检后计数）；U2 无冻结 budget 断言，D3 保守地保持 `regular++` 在 glob 前，并由 S17(b) 钉住；U3 按 matrix/ledger 的 W5 子节体例追加 W6 子节；U4 `install_spawn_log`/`spawn_count` 按 `--spawn-log` 行数计数，W6 只在需要时断言一次 invoke 一次 spawn。U5 复核确认 `_tool_v2` 的 `compact_json(args)` 经 `canonical._safe_integer` 对 2^53 级整数返回 `invalid_tool_arguments`、零 spawn，故 S16(a) 的插件分支只由直连帧证明（D-ABI-W6-8）。
- **实际偏差：** 未改任何 cap（12s/15s/10000/200/500/40960/41984/4096/64 KiB）、design、向量、host、SQL、`fs_read.py` 或 frozen tests；未新增 env/argv 开关；未写墙钟通过条件；未 `sleep(12)`。D-ABI-W6-1…14 记录 §6.3 措辞与冻结 `glob_16` 的冲突（冻结字节胜出）、三层 12 s 证据标准、C0/C1 收窄、空页 `output_too_large` 与 `addSafe` 的闭集外码、`entry_too_large` 的注入可达性、list 10000 cap 的原始条目口径、glob 排除文件消耗 file budget、2^53 offset 的生产不可达性、早退守卫替换、slashless glob、第三参数 seam、W4 O8=B 后续 owner 与 `linux_real`/子目录非 UTF-8 边界。无 STOP 条件触发。

三层 12 秒证据分开记录：T1 为 S06–S11 的注入时钟经生产 `searchTool` 的确定性 cutoff 分支；T2 为 S24 的常量（12000/15000/余量 3000）与源码结构断言；T3 为 S25 的一次真实时钟观测（elapsed/过冲只记录）。**这不是「12 秒已证明」**，也不是 M3 完成声明：`tool.search_budget_timing_m3_pending` 保持 `m3_pending`，C.18 属后续 M3 声明阶段；`linux_real=not_run`，L07 只覆盖根级非 UTF-8。真实提交 SHA 与推送结果由发布回执报告，本文件不嵌入自身提交哈希。
