# v24 Tool/Plugin ABI：M3 声明与 M5 收口计划

> 状态：待执行。本文只写计划，不包含已运行 gate 或已产生的完成证据。执行日期以实际运行日（+08:00）为准；下文记录文件按 2026-11-01 命名，若实际执行日不同，在同一提交内统一替换。
>
> 修订：第 3 版（2026-11-01）。第 1–12 条 critique 已在第 2 版落实；本版落实 `docs/reviews/v24-m3-m5-closeout-plan-critique-2026-10-31.md` 的 13–18 条（M5 零 diff 基线、C.18.5 判定次序、C.18.1 done-when 措辞、Resolution 映射、附录 C 必填、M5 artifact digest 实测），逐条见 `## 批判意见落实`。

## 1. Goal 与范围

在 W5（Python read）与 W6（Node list/search）已交付并推送的基础上，用 append-only 的 design Appendix C.18 把 M3 的证据标准、时钟 seam、页填满权威与冻结状态词汇语义固定下来，正式声明 M3 完成；随后执行 M5 收口：补齐 §7.5 遗留的三项文档修订、逐条裁决 10 个 suite / 34 个冻结 `status` 位置、跑完 32 条串行 gate，并按 AGENTS.md 分两次里程碑提交推送。

两个里程碑各自拥有独立候选、独立 sweep、七项 scope audit、独立 execution record 与路径级提交；M3 未成功推送不开始 M5。

### 1.1 In scope

1. EOF 追加 ABI design C.18（七个 `**C.18.n**` 条目，单一 `### C.18` 标题）。
2. 原子修改三处：design 文件、`design_conformance.json.design_input.sha256_at_review`、`test_contracts.py.DESIGN_SHA256`。
3. README、matrix、ledger 的 M3 当前声明；新增 M3 declaration execution record。
4. 已裁决提交 `docs/investigations/v24-m3-budget-closeout-2026-10-31.md`，正文不动，标题下加状态行、文末加 `## Resolution`。
5. §7.5 尚未完成的主设计 §5.1/§5.4 修订与 drift-factcheck D2/D3/D4 标注。
6. 指定 10 个 suite status 与其他 24 个 `status` 位置的逐条证据裁决（只写在文档，不改 JSON）。
7. 两次 32-command 串行 sweep、每轮七项 scope audit、两份 execution record。
8. 两次按明确路径 staging、正常 hook commit、非 force push。

### 1.2 Out of scope（明确不做）

- 任何生产源码、host、SQL、loader、fixture、preload、协议行为修改。
- 除 `DESIGN_SHA256` 常量外的任何测试源码修改；`test_tools.py:1693-1694` 的 `m3_pending` 与 `deterministic_w1_pass is False` 断言保持原样。
- 任何冻结 vector 的 case/input/expected/status/owner/vocabulary/compatibility/pinned-span 元数据修改；`vectors/README.md` 也不改。
- `capture_vectors.py`、独立重捕获、向量重新生成或 promotion。
- 重写 W5/W6 execution record、C.11 表格或 C.16 原文来改写历史。
- 放宽 12s/15s/10000/200/page/40960/41984/4096/64 KiB 任一上限；`sleep(12)`；墙钟 pass/fail gate。
- 改 read 解码窗口（冻结 `window_bad_utf8` 要求完整请求窗口解码）。
- 翻转 `compatibility.production_behavior_claimed` / `gate_pass_claimed`。
- Linux real 运行、真实 provider、网络 smoke、服务端 cursor/snapshot 分页。

## 2. Done when

1. C.18 已追加；追加前 design bytes 是新文件的精确前缀。
2. 新 design SHA 与两个 pin 完全相等；25 处 span 引用 / 23 个唯一 span 的行范围、heading、内容 SHA 全部不变。
3. README、matrix、ledger、M3 record 一致声明：**M3 按 C.18 的证据标准完成**，且不声称硬实时 12s、Linux real 或子目录非 UTF-8 覆盖。
4. §7.5 五项义务都有明确落点；D2/D3/D4 不再被读成当前 v2 行为。
5. 34 个指定 `status` 位置各有冻结值、证据指针、裁决与限制；四个 vector 文件字节零变化（mapping 仅 SHA 一行随 M3 repin 变化，M5 起零变化）。
6. M3、M5 各自 32/32 exit 0：第 1–31 条有完整命令专属末行，第 32 条输出为空；无 exit 2 / `[SKIP]`。
7. 每个里程碑七项 audit 的预检与文档落盘后的最终审计全部通过；`v24/sql` 相对 `c8c4bd0` 零 diff。
8. 两个里程碑分别提交推送；每次推送后记录本地 commit 与 `origin/main` 的实际关系。
9. closeout 始终 **11/11**；s13 始终是 extension evidence，不是第 12 条。

## 3. 当前状态与依据（执行基线）

### 3.1 仓库状态

- `HEAD == origin/main == 2307077`（`v24: close out Node list and search tools`），前一条 `82e5440`（`v24: close out Python read plugin ABI`）。已推送，`git log origin/main..HEAD` 为空。
- 受跟踪工作区干净。未跟踪：`docs/investigations/v24-m3-budget-closeout-2026-10-31.md`、本计划、本计划的 critique、`.ctx-export-*`、`.token-probe*`、`ctx_export_check*`、`v20/experiments/ce_native_d5/`。
- 六项继承 audit 的历史基线是 `c8c4bd0`；每个阶段另加一项 delta audit。W5 以 `5771ce3`、W6 以 `82e5440` 为 delta 基线。

### 3.2 M3 行为已落地（W5 + W6 实测锚点）

- search：`v24/s13/plugins/fs_tools.js:23` `SCAN_BUDGET_MS = 12000`；`:644` 单调时钟 `Number(process.hrtime.bigint())/1e6`；`:257` 第三参数可注入 `budgetMs`；四个终止态 `:265` time-cap、`:568` sentinel、`:614` file-cap、`:671` 补齐 eof；`:676` `complete = stopReason === "eof"`。
- §5.6 后置判定：`:748-755` cutoff 页只在 `selected === candidate.length && selected === limit`（count-full）或 `selected < candidate.length`（观察到后续完整候选）时成功，否则 `search_scope_too_large`；早退守卫 `scopeExhausted && total < offset+limit` 已删除。
- 其他 M3 修复：`:217` `addSafe`（BigInt）、`:473`/`:528` slashless glob 只匹配 basename；`fs_read.py:28` `CHUNK = 65536`、`:162` `_scan` 单 fd 两遍有界扫描。
- Artifact 实测：`fs_read.py` 与 `fs_tools.js` 的 source / installed / approved-entry SHA-256 分别为 `260274daba1efa87f4c33103fe53503c76a65187af68e610d5aedcfadad5165c`、`efd05d63f028f0da4de333684dc3e63f506302f5a1c52a26c95efe36297348e5`。
- 三层证据：T1 注入时钟经生产 `searchTool` 的 S06–S11；T2 常量/descriptor/source 结构 S24（12000、15000、margin 3000）；T3 一次真实时钟观测 S25（`real_clock_elapsed_ms=50.331`，只记录）。W6 明确写“不是 12 秒墙钟保证”。

### 3.3 为什么 M3 仍未声明

- 设计附录止于 C.17（`:1386`）；C.11 的 W4b 行仍写“**M3 实现完成，timing/cutoff pending**”（`:1297`）；C.16 把 12 秒 gate 推迟（`:1380`）。
- 所有阶段记录仍写“not M3”：`v24/s13/README.md:84/104/123/145`；`docs/reviews/v24-conformance-matrix-2026-10-23.md:700/732/753`；ledger `D-ABI-W6-13`；冻结 case `v24/s13/vectors/tool_contracts.json:4417`。
- §7.5 的文档修订从未执行：`docs/designs/v24-pg-agent-2026-10-22.md:275` 仍写“DB 与 host 均不按该 schema 校验参数内容”；`:297` 仍只写 `{status,output,usage}` 形状；`docs/investigations/v24-drift-factcheck-2026-10-29.md:57` D2 仍写“DB 与 host 都没有 schema 校验”，无 v2 host `parameters_check` 例外。
- M5 没有独立执行记录；设计 §10 的 M5 done-when 只有两条：`git diff --exit-code -- v24/sql` 为空、全部 gate exit 0（`:1068`）。

### 3.4 状态词汇与冻结机制（决定“不能 promote”）

- `design_conformance.json.vocabulary.status` 只有九个值：`planned`、`design_resolved`、`pending_vectors`、`pending_reference`、`provisional_w2_pending`、`m2_pending`、`m3_pending`、`m4_pending`、`not_run`——没有 `passed`/`verified` 终态；`test_contracts.py` 还断言 `case['status'] != 'passed'`。
- `git log -p -- v24/s13/vectors` 显示 status 只会被加入、从未被修改；`capture_vectors.py` 在生成时写死 `status=` 默认值。`manifest_adapter_v2.json:72`/`:607` 的 digest 仍是字面 `"M3-pending"`。
- `test_contracts.py:10` 与 `:42-43` 钉整份 design SHA，`:53-60` 逐 span 校验 `line_start`/`line_end`/`heading`/内容 SHA。当前 25 处引用、23 个唯一 span，**最大 `line_end` 是 1178**（Appendix A），即 C.11–C.17 并未被 span 钉住；C.18 必须 EOF 追加的理由是 exact-prefix 不变量与全文行号引用，不是 span 位移。
- `compatibility.production_behavior_claimed` / `gate_pass_claimed` 被 gate 断言为 `false`；“M3 完成”只能写在文档。

## 4. 已裁决的决定

| ID | 决定 | 依据 |
|---|---|---|
| DM1 | 12 秒证据标准采用调查 Option A：T1 确定性分支 + T2 常量/结构 + T3 真实时钟观测。B（硬实时 CI）与 C（删除 12 秒合同）否决。 | 调查 Recommendations；W6 已按 A 交付（`D-ABI-W6-2`）。 |
| DM2 | 权威：M3 完成 = 设计 §10 M3 done-when + C.18 证据标准。C.18 **按引用取代** C.11 W4b 行与 C.16 的 pending 结论；原文字节保留。 | append-only；C.8 取代 C.2、C.15 取代 §7.4 的先例。 |
| DM3 | 两个里程碑、两个提交、两份记录：`v24-tool-plugin-abi-m3-declaration-execution-2026-11-01.md`、`v24-tool-plugin-abi-m5-closeout-execution-2026-11-01.md`。 | AGENTS.md 一里程碑一提交；仓库每阶段一份 `-execution-` 记录。 |
| DM4 | 四个 pending token（`m2/m3/m4/provisional_w2`）是 **provenance**（首次生产证据归属），不是完成标志，也无终态 token。34 个位置（全部是 pending token）字节全保留，裁决写进 matrix/M5 record；另外五个 vocabulary 值语义不变。 | 九值 vocabulary 无终态；`status != 'passed'`；status 历史只增不改。 |
| DM5 | `linux_real=not_run` 保持显式限制，排除在 M3 声明之外。本轮不跑 Linux。 | C.17 第 5 条；D-ABI-W6-14；当前环境 Darwin/arm64。 |
| DM6 | 提交未跟踪的 M3 调查：正文不动，标题下加状态行，文末加 `## Resolution`，映射各发现到 W5/W6/C.18。 | C.18 的 Option A 直接来自该文件；不提交则被引用的依据不可检索。W6 的排除是该阶段范围。 |
| DM7 | C.18 同时固定 §10 M5 的读法：§7.5 第 1–3 项 + 34 位置裁决 + 32-command sweep + SQL 零 diff + 11/11。M5 不再做第二次 design repin。M5 的 vectors 零 diff 基线是 M5-0 解析出的**实际 M3 commit SHA**，不是 `2307077`；`2307077` 只用于 M3 的“仅 mapping SHA 一行”差分。 | 每次 repin 都要动 `test_contracts.py` 与 audit 3；M3 必然把 mapping 留在新 SHA `S1`，以 `2307077` 作 M5 基线不可能为空。 |
| DM8 | 历史段落不重写：README/matrix/ledger 用追加小节 + 明确“取代上述哪几句”的指针；旧的 not-M3 句子作为阶段记录保留。 | ledger 既有“追加修正、不覆盖”惯例。 |
| DM9 | 记录日期用实际执行日（+08:00）。本文按 2026-11-01 预填；若跨日，同一提交内统一替换所有链接。 | W5/W6 记录均按实际运行日命名。 |
| DM10 | 本计划的 critique（`docs/reviews/v24-m3-m5-closeout-plan-critique-2026-10-31.md`）是发布候选，随 M3 提交入库并只读保留；M3 因此是 **10 路径**。 | 仓库惯例：W1–W6 的 plan critique 均随阶段提交跟踪。 |

## 5. Appendix C.18 的规范内容

**位置与形式**：`### C.18 M3 声明与证据标准（补充 §5.6/§6.3，取代 C.11 W4b 行与 C.16 的 pending 结论）`，追加在 C.17 最后一字节之后；C.18 之下用七个 `**C.18.n**` 粗体条目，不新增 `###` 子标题。下文 `### C.18.n` 只是本计划的说明小节，不是 design 里的标题。C.11/C.16 原文不动；C.18 用“取代”而非“插入”。

### C.18.1 阶段绑定与权威

- W5 的 read 证据 + W6 的 list/search 证据 + 本节，共同完成设计 §10 的 M3。
- 在 C.18 内用一张表重述 C.11 的两行（C.11 原表保留为历史，不原地修改）；两行都写 **done-when 条件**，不是无条件状态断言：

| 阶段标签 | design §10 | done-when（全部满足） | 声明落点 |
|---|---|---|---|
| M3 声明 | M3 | W4b + W5 + W6 的交付证据；C.18.2(a)–(f)；C.18.3 的三层证据；32-command sweep 与七项 audit 全绿 | 由 M3 execution record 按实际运行日记录 **M3 完成** |
| M5 收口 | M5 | §7.5 第 1–3 项；C.18.6 下 34 位置裁决；32-command sweep；`git diff --exit-code -- v24/sql` 为空；closeout 11/11；七项 audit 全绿 | 由 M5 execution record 按实际运行日记录 **M5 完成** |

- 明确不改变 M2（W4a）、M4（W4c）的完成声明，不改变数据库恢复策略。
- C.18 文本本身不构成完成声明；缺少各自 execution record 时，两行都只是待满足条件。

### C.18.2 “M3 完成”的定义

合取项：(a) §10 M3 done-when（`test_tools` 全绿、真实子进程、分页收敛）；(b) 冻结 16 read / 7 list / 24 search 输出逐字节不变；(c) 四个 stop reason 与 §5.6 页填满分支经生产函数证明；(d) read 的合法最坏输入在 5000 ms host deadline 内完成并记录**本轮**观测值；(e) C.18.3 的三层证据；(f) 声明候选的 32-command sweep 与七项 audit 全绿。声明本身以 M3 execution record 的日期与结果为准。

### C.18.3 三层 12 秒证据（不得合并表述）

| 层 | 内容 | 不得外推 |
|---|---|---|
| T1 | S06–S11 经导出的生产 `searchTool` 注入时钟，证明 time-cap 的 count-full / before-fill / before-offset / empty 与 EOF、sentinel 优先 | 不是另写的参考算法；不是帧级时钟注入 |
| T2 | S24 断言 `SCAN_BUDGET_MS=12000`、search `timeout_ms=15000`、余量 3000、`hrtime` 只在 `searchTool`、`process.env` 只在 `rootPath` | 3000 ms 是配置余量，不是扫描/IO 最坏上界 |
| T3 | S25 用真实时钟与小预算，断言结果属于该 probe 允许集合，记录 elapsed/overshoot | 不以 elapsed 判通过；不要求复现 50.331 ms |

另记：file-cap 的五个形态（S01–S05）与“无适配前缀 / offset 优先”（S12）是同一生产函数上的确定性证据，但不属于注入时钟层；不得把它们并入 T1 的证明范围。

写明：`deterministic_w1_pass:false` 是 W1 参考实现的限制，不构成“必须硬实时 CI gate”的要求；三层不得合并成“12 秒已证明”；同步 `readdir`/`readFile` 不可抢占，超过 15000 ms 仍是 `unknown/timeout`。

### C.18.4 时钟起点、检查点与 seam

- 默认时钟 `Number(process.hrtime.bigint())/1e6`；起点是 `searchTool` 完成参数检查后的 `started = now()`（`fs_tools.js:645`），不是函数第一条语句。
- **C0 只是这一次初始化读取**：`:645`/`:666` 用 `started + budgetMs` 设 deadline，`nowCalls` 初始为 1，不做比较。真正的截止比较（C1）在目录递归前（`:607`）与 regular file 的 file-cap 检查之后、`searchFile` 之前（`:617`）。因此“进入 `searchTool` 立即判定超时”不是当前行为；C.18 按实现描述，不沿用 W6 README 中 “checks … at C0” 的宽松措辞。
- 同一文件上 file-cap 判定先于 C1（`:613` 在 `:617` 之前），所以 file-cap 在同一交界处优先于 time-cap。
- 一个 C1 单元的工作量是：一次 `readdirSync`、其 `names.sort`、对每个未被名字过滤的条目做 `lstat` 与分类（symlink 记 skipped 后跳过），以及最后一个 C1 之后至多一个 ≤1 MiB 文件的读取与扫描。hidden/`.git`/非 UTF-8 在 `lstat` 前按名过滤，不触发时钟检查。不在行/context 构造中插入检查，不给出毫秒级最坏上界。
- 生产 `invoke` 不传第三参数；`options` 字段为 `now/budgetMs/fileLimit/scanLimit/caps/trace`，只供进程内测试。C.17 §4 的“生产无 seam”针对 env/preload，不禁止显式函数参数；不新增 env/argv/wire 字段。

### C.18.5 §5.6 页填满权威

以 §5.6 的终结候选算法为唯一权威，判定顺序与 `fs_tools.js:680-756` 一致，写死为：

1. **来源错误 / 非法统计或整数** 先于分页：参数、路径、编码、冲突，以及字段关系/统计不一致，按既有映射返回；`offset_out_of_range` 不在本层。
2. **`m=0`**（`total===0`）：先处理 offset——`offset!==1` 时，complete 发 `offset_out_of_range`，否则 `search_scope_too_large`；incomplete 发 `search_scope_too_large`；complete 且 `offset=1` 时构造规范空页并检查四预算，不适配发 `output_too_large`；不得返回空 incomplete 成功页。
3. **非空快照的 offset 与页算术**：`offset > total` 时，complete 发 `offset_out_of_range`，否则 `search_scope_too_large`；该检查在快照校验后、前缀枚举前。随后的 `start`/`end` 越过安全整数发 `invalid_tool_output`。
4. **无任何适配非空前缀** → `hit_too_large`，不被后续 cutoff 判定掩盖。
5. **cutoff 页填满判定**：成功仅允许 `k=m=limit` 或 `k<m`；否则 `search_scope_too_large`。不使用 `scopeExhausted && total < offset+limit` 的预选早退。
6. **成功**：返回所选页。

其中 `m` = 本页完整候选数，`k` = 枚举全部候选前缀后选中的最大适配数；`complete` 当且仅当 `stopReason === 'eof'`，其余为 `sentinel/file-cap/time-cap`。sentinel 是完整观察到的 hit：计入 `total`，不进入本页 `hits`。“页可返回”不等于慢 scope 分页一定收敛。

### C.18.6 冻结标签与字节权威

- 四个 pending token（`m2_pending`/`m3_pending`/`m4_pending`/`provisional_w2_pending`）记录“首次生产证据归属”，不是持续状态；另外五个 vocabulary 值（`planned`/`design_resolved`/`pending_vectors`/`pending_reference`/`not_run`）含义不变。
- `owner`、`first_production_stage`、suite 的 `required_case_ids` 保持原值；suite 内可含后续阶段补齐的证据。
- timing case 的内层 `expected.status` 同样保留；两个 `"M3-pending"` artifact 字符串是 W1 fixture 占位，不是当前 digest。
- `compatibility.*_claimed=false` 保持 W1 语义（“W1 vectors 不作生产声明”）；当前完成证据只写 README/matrix/ledger/record。
- C.18 不授权重新生成、re-bless 或 promotion。

### C.18.7 承接的既有解释、声明边界与 M5 读法

承接（不改行为）：read 完整请求窗口先解码再选前缀；glob 排除的 regular file 仍计 `scanned_files` 且消耗 file 预算；list 扫描 cap 按原始目录项计数；空页预算失败发 `output_too_large`；Node 安全整数失败发 `invalid_tool_output`；平台证据仅 macOS root-level shim。

不证明：硬实时 12s、固定 cutoff 位置、跨平台 timing、慢 scope 分页收敛、真实字节满树的 file-cap 复现（S02 只证 `k<m` 结构）、Linux real、子目录非 UTF-8、恶意并发 workspace、原子文件快照、工具自动重执行、新 provider 行为。

M5 读法：§10 M5 = §7.5 第 1–3 项执行（第 4/5 项已由 W1–W6 增量完成）+ C.18.6 下的 34 位置裁决 + 32-command sweep + `git diff --exit-code -- v24/sql` 为空 + closeout 11/11。

## 6. 原子 repin 程序（M3-2）

1. 记录旧状态：design 字节长度 `L0`，确认 `sha256 == ab4636fcae5361cc237b16cdd893c2c544d80e770e8e13269b3d4205713d528b`。
2. 追加 C.18，计算 `S1 = sha256(new file)`。
3. 同一工作改动内：`design_conformance.json` 的 `design_input.sha256_at_review = S1`；`test_contracts.py:10` 的 `DESIGN_SHA256 = S1`。只改这两个值：JSON 只动该字段，Python 保持单引号风格（audit runner 用 AST 读常量；W5 曾因假定双引号在 runner 内失败）。不改 `source_sha256_imported_from_primary`。
4. 前缀证明：新文件前 `L0` 字节的 sha256 必须等于旧 SHA；两个哈希都写进 M3 record。
5. 立即验证：`test_contracts.py`、`test_vectors.py`、`test_vectors.py --node` 三条 marker 与 W6 表第 9–11 行一致。
6. 差分证明：`git diff --stat -- v24/s13` 恰为两个文件、各 1 insertion / 1 deletion。

## 7. M3 声明工件

### 7.1 README（`v24/s13/README.md`）

追加 `## M3 declaration (2026-11-01)`：

- C.18 是权威；三层证据分列，不合并。
- 两个 artifact SHA；冻结 16/7/24 用例逐字节不变。
- 明确句：“本节取代上文 W4b/W4c/W5/W6 段落中 ‘not an M3-complete declaration’ / ‘M3 timing/cutoff remains pending’ 的表述；那些段落作为阶段记录保留。”
- `tool.search_budget_timing_m3_pending` 在 C.18.6 下保持冻结 token；`linux_real=not_run`；closeout 11/11。

### 7.2 Matrix（`docs/reviews/v24-conformance-matrix-2026-10-23.md`）

追加 `## Post-closeout Tool/Plugin ABI M3 declaration（2026-11-01）`：一行 gate 结果表（复用 32 行结果）、repin 叙述（沿用 W4b 的“旧 bytes 是精确前缀；25 处引用 / 23 个 span 的行范围、heading、内容 SHA 不变”句式）、取代指针（`:700`/`:732`/`:753`）、artifact SHA 与限制。

### 7.3 Ledger（`docs/reviews/v24-deviation-ledger-2026-10-23.md`）

追加 `D-ABI-M3-1…7`，每条引用既有 `D-ABI-W5/W6` 行而非复述：

| 行 | 内容 |
|---|---|
| D-ABI-M3-1 | 权威与取代：C.18 取代 C.11 W4b 行 / C.16 pending 结论 / `D-ABI-W6-13` 的“C.18 留给后续”措辞；原文保留。 |
| D-ABI-M3-2 | 追认 W4b 的过度声明：写“cutoff errors”时 file-cap 页路径无条件拒绝；由 `D-ABI-W6-10` 修正。 |
| D-ABI-M3-3 | 证据标准 Option A；B/C 否决理由。 |
| D-ABI-M3-4 | 时钟 seam 与 C.17 §4 的边界；并修正 W6 README “checks at C0” 的措辞——C0 仅初始化读取，首次截止比较发生在第一个目录/regular file。 |
| D-ABI-M3-5 | 冻结 token 的 provenance 解读；不 promotion；compatibility 保持 false；`"M3-pending"` 占位保留。 |
| D-ABI-M3-6 | 声明边界（C.18.7）。 |
| D-ABI-M3-7 | 调查文件随本提交入库；正文为 pre-W5/W6，行号不作权威。 |

### 7.4 调查文件的 Resolution

标题下加一行状态（仿 `drift-factcheck:8` 的写法）：`**状态（2026-11-01）：已由 W5、W6 与 design C.18 解决；正文为 W5/W6 之前的历史分析，见文末 Resolution。**`

文末 `## Resolution (2026-11-01)` 逐项映射：Finding 1（search）→ W6 的 `D-ABI-W6-9`（`addSafe`/安全整数）、`D-ABI-W6-10/11/12`（cutoff 后置判定、glob、seam）与 `D-ABI-W6-2/3`（三层 timing、C0/C1），artifact `efd05d63…`；Finding 2（read）→ W5 的 `D-ABI-W5-1…5`，artifact `260274da…`；对账表 #15（glob 排除文件的 `scanned_files` 记法）→ `D-ABI-W6-1` / S17 / C.18.7 承接句；#16（byte-full file-cap 复现）→ W6 S02 的 `k<m` 页与 `D-ABI-W6-10`，只作结构/失败次序证明；#17/#18/#19 保留既有否决/纠正结论；Option A → C.18 采纳；B/C → 否决；W5/W6 证据 → 各自 execution record；正文 `fs_read.py`/`fs_tools.js` 行号为 pre-W5/W6，不作权威。

### 7.5 M3 execution record

`docs/reviews/v24-tool-plugin-abi-m3-declaration-execution-2026-11-01.md`，章节沿用 W6 record：Result、Candidate/provenance、Declaration-and-evidence mapping、Scope audits、32-row table、Deviations、Limits、Publication。记录内不写自身 SHA 或未来 commit SHA；最终候选摘要、commit SHA、push 结果放外部 publication receipt。

## 8. M5 §7.5 文档修订

### 8.1 主设计原位修订（正文同行改写 + 文末附录条目）

按内容定位，不依赖 drift-factcheck 的旧行号（`:271/:273/:309/:295` 已过期）。

- **§5.1（含“DB 与 host 均不按该 schema 校验参数内容”，当前 `:275`）**：保留“DB 只做形状校验、`slots.descriptor` 不透明”的事实；补版本区分——descriptor v1 的 host 行为不变；v2 descriptor 由 host 在 spawn 前按 `ApprovedTool.parameters_check` 执行封闭 schema 子集；host 不注入默认值；DB 未新增 schema validator。
- **§5.4（含 `{status,output,usage}`，当前 `:297`）**：结果外层形状校验仍归 DB；补 v2——host 校验 `value` 的 output schema、内建页关系、renderer 与预算；success 为 `{value,content,meta?}`，known failure 为 `{error,content,meta?}`，unknown 仅 `{error}`；provider 原始明细与渲染后的 tool message 仍由 journal 持久化。
- 该文件已有 `## 附录 C：R6 修订（2026-10-24）`（`:656`），且 `:786` 明确“行内修订 + 文末追加；正文 1–652 行的既有 `L###` 锚点保持有效”。因此 §5.1/§5.4 的正文行仍在 1–652 内同行改写（`git diff --word-diff` 只动这两行），修订记录作为附录 C 的新条目追加在文末；`wc -l` **会**增加，不能以行数不变作为判据，判据改为“正文 1–652 行除这两行外零 diff、既有 `L###` 锚点仍有效”。另 `rg 'v24-pg-agent-2026-10-22' v24/` 确认无 gate 哈希该文件（当前无命中）。

### 8.2 Drift-factcheck D2/D3/D4

在每节 `### 触碰面 / gate` 末尾追加 `- **M5 修订（2026-11-01）：**`，并在 `:8` 的 W1 状态行下加一行当前状态：

- **D2**：原“DB 与 host 都没有 schema 校验”明确为 descriptor v1/DB 的事实；v2 descriptor 的参数与 output 已由 host 封闭子集校验，并引用**本次修订后的**主设计 §5.1/§5.4 与 ABI §5.5/C.13；`plugins.py:57-70` 的描述属 `_tool_v1`。
- **D3**：`replay_class` 仍是 metadata；tool successor 仍 `no_replay`；W4c 的已完成 outcome 重交不等于未决工具自动重执行。
- **D4**：v2 `model_text` 经 `tool_message` 持久化，journal 仍是 transcript 权威；重启不重新 render。

历史结论与修法表不重写；新引用用章节名与当前内容锚点，旧行号仅作历史记录。

## 9. 34 个冻结 status 位置的逐条裁决

**范围**：10 个 suite + 8 个 `tool_contracts` 位置 + 5 个 `manifest_adapter_v2` 位置 + 11 个 `results_v2` 位置 = 34。位置由脚本解析 JSON 定位（不手抄行号）；执行时必须先把解析出的 34 个 JSON 指针（文件 + 指针 + case/suite id）落成清单并断言总数，同时断言：`design_conformance` 的 10 个全部匹配 `immutable_required_suites[*].status`，另 2 个 `design_resolved` 匹配 `reviewed_design_decisions[*].status`；再逐行裁决，禁止只按本表的人工分组计数。

M5 record 的每行至少含这些列：`文件 + JSON 指针`、`case/suite id`、`冻结 token`、`first_production_stage`、`满足阶段`、`本轮证据（sweep 行号 + marker/probe + 本轮实测数值/digest）`、`裁决`、`限制`、`冻结字节 audit 结果`。下文表格给出其中稳定的三列（token / 证据 / 裁决），其余列在执行时补齐。artifact 两行必须写本轮 row-29 R28/S24 的实际 SHA-256，不得只写“复用 W5/W6”。

计数校验：

```bash
python3 - <<'PY'
import json, collections
PENDING={"m2_pending","m3_pending","m4_pending","provisional_w2_pending"}
total=0
for f in ("tool_contracts","design_conformance","manifest_adapter_v2","results_v2"):
    c=collections.Counter()
    def walk(o):
        if isinstance(o,dict):
            for k,v in o.items():
                if k=="status" and isinstance(v,str): c[v]+=1
                walk(v)
        elif isinstance(o,list):
            for v in o: walk(v)
    walk(json.load(open(f"v24/s13/vectors/{f}.json")))
    p={k:v for k,v in c.items() if k in PENDING}
    total+=sum(p.values())
    print(f, p, "pending=", sum(p.values()), "other=", {k:v for k,v in c.items() if k not in PENDING})
print("pending_total=", total)
PY
```

预期逐文件 pending 数为 `tool_contracts=8`、`design_conformance=10`、`manifest_adapter_v2=5`、`results_v2=11`，`pending_total=34`；`design_conformance` 另有 2 个 `design_resolved`，必须位于 `reviewed_design_decisions[*].status`，不计入 34，也不在本轮裁决范围。

**裁决词表**（只写文档，绝不写回 JSON）：

- `E-SAT`：证据已满足，token 作为 provenance 保留。
- `E-SAT-T`：在 C.18.3 三层标准下满足，不是墙钟声明（timing case 与 `filesystem_tool_contracts`）。
- `E-SAT-PH`：由记录的 artifact digest 满足，`"M3-pending"` 占位保留（两个 manifest artifact 位置）。
- `FROZEN-EXPECTED`：timing case 的内层 `expected.status`，是冻结期望数据，不是独立状态。

### 9.1 10 个 suite status（`design_conformance.json`）

| Suite selector | 冻结 token | 应绑定证据 | 裁决 |
|---|---|---|---|
| `canonical_descriptor_bytes` | `m2_pending` | descriptor gate + Python/PG/Node vectors | E-SAT |
| `descriptor_v2_contract` | `m2_pending` | descriptor、registry、wiring | E-SAT |
| `line_json_v2_frames` | `m2_pending` | line-json corpus；真实生命周期由 lifecycle 另证 | E-SAT |
| `adapter_manifest_v2` | `m2_pending` | registry；M3 artifact 项另绑 R28/S24 | E-SAT |
| `provider_projection_v2` | `m2_pending` | wiring、B0、G9 的 v1/v2 投影 | E-SAT |
| `renderer_goldens_and_digest` | `provisional_w2_pending` | renderers 的 21 goldens / 三组 digest；活渲染由 tools 补证 | E-SAT |
| `result_model_text_budget_replay` | `m2_pending` | results、wiring；replay 子项绑 lifecycle | E-SAT |
| `closed_schema_subset` | `m2_pending` | schema + wiring | E-SAT |
| `filesystem_tool_contracts` | `m3_pending` | tools、W5/W6 probes、C.18；保留平台限制 | E-SAT-T |
| `result_replay_lifecycle` | `m4_pending` | lifecycle；只证明 journal outcome replay 范围 | E-SAT |

### 9.2 `tool_contracts.json`（8）

| Selector | 冻结 token | 证据与边界 | 裁决 |
|---|---|---|---|
| `tool.shared_paths_encoding_order.status` | `m3_pending` | tools 的共享路径/排序用例；非恶意并发 workspace | E-SAT |
| `tool.read.contract.status` | `m3_pending` | 16 冻结 read + 29 read probes | E-SAT |
| `tool.list.contract.status` | `m3_pending` | 7 冻结 list + 11 list probes | E-SAT |
| `tool.search.contract.status` | `m3_pending` | 24 冻结 search + 26 search probes | E-SAT |
| `tool.fixture_tree.portable_nodes.status` | `m3_pending` | fixture materialization + tools；不外推 Linux real | E-SAT |
| `tool.search_budget_file_count.status` | `m3_pending` | 文件数预算与 S01–S05；`timing:"not_frozen"` 保留 | E-SAT |
| `tool.search_budget_timing_m3_pending.expected.status` | `m3_pending` | C.18 对冻结期望的解释；非新增测试 | FROZEN-EXPECTED |
| `tool.search_budget_timing_m3_pending.status` | `m3_pending` | T1/T2/T3；`deterministic_w1_pass:false` 保留 | E-SAT-T |

### 9.3 `manifest_adapter_v2.json`（5）

| Selector | 冻结 token | 证据与边界 | 裁决 |
|---|---|---|---|
| `manifest.adapter.python_read.status` | `m2_pending` | 固定 adapter bytes/digest + registry | E-SAT |
| `manifest.adapter.node_list_search.status` | `m2_pending` | 固定 adapter bytes/digest + registry | E-SAT |
| `manifest.five_field_key.status` | `m3_pending` | registry 五字段匹配 + 实际 artifact；输入占位不变 | E-SAT-PH |
| `manifest.one_install_two_provides.status` | `provisional_w2_pending` | 固定 manifest bytes + 真实 Node 双工具 lifecycle | E-SAT |
| `manifest.artifact_digest_pending.status` | `m3_pending` | R28/S24 的 source/copy/entry 相等及 tamper；expected 占位不变 | E-SAT-PH |

真实 artifact 以本轮 row-29 的 R28/S24 重算值为准：R28 从完整 log 取 `read_artifact_sha256`；Node 侧记录 `fs_tools.js` 源文件的只读 SHA-256，并以 S24 在 row-29 内断言的 source/copy/entry 三者相等作为安装副本与 approved entry 的等价证据（测试临时目录在退出时删除，不伪称事后重测安装副本）。W5/W6 的 `260274da…`/`efd05d63…` 只作历史交叉核对，不得写成“不当作新实测”。若本轮值与历史值不同，按实测记录并在发布前 STOP 查明原因。

### 9.4 `results_v2.json`（11）

| Selector | 冻结 token | 证据 | 裁决 |
|---|---|---|---|
| `result.success_envelope.status` | `m2_pending` | results + wiring success | E-SAT |
| `result.failure_envelope.status` | `m2_pending` | results + wiring known failure | E-SAT |
| `result.unknown_envelope.status` | `m2_pending` | results + line-json/lifecycle unknown | E-SAT |
| `result.usage_wall_ms.status` | `m2_pending` | results + wiring；usage 闭集不变 | E-SAT |
| `result.model_text_join.status` | `m2_pending` | results + wiring 的 11-byte model text | E-SAT |
| `result.meta_excluded_from_model_text.status` | `m2_pending` | results + wiring 的 meta 排除 | E-SAT |
| `result.budget_domains.status` | `m2_pending` | results、page、tools 四域与候选选择 | E-SAT |
| `result.frame_60000_60001_65536_65537.status` | `m2_pending` | results/transport；60000 目标 ≠ 65536 cap | E-SAT |
| `result.replay_no_rerender.status` | `m4_pending` | lifecycle 已记录 outcome 的 replay | E-SAT |
| `lifecycle.journal_replay_no_rerender.status` | `m4_pending` | lifecycle：无 handler / 无二次 spawn / 无 rerender | E-SAT |
| `lifecycle.tool_message_model_text_stable.status` | `m4_pending` | lifecycle/legacy tool-message bytes | E-SAT |

**零字节证明**：34 计数通过；M3 中 `git diff --exit-code 2307077 -- v24/s13/vectors` 只能是 `design_conformance.json` 的 SHA 一行；M5 中 `git diff --exit-code <M3-commit-SHA> -- v24/s13/vectors` 必须为空——`<M3-commit-SHA>` 在 M5-0 由 `git rev-parse HEAD` 解析并写入证据目录，不得改用 `2307077`。不得把 stub 证据、直接函数调用、真实子进程、DB lifecycle 混写成同一证据层。

## 10. 32-command 串行 sweep

M3 与 M5 各自完整执行一次，分别写入自己的证据目录。仓库根执行，每条加前缀：

```text
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1
```

| # | 命令 |
|---:|---|
| 1 | `uv run python v24/s13/test_pages.py` |
| 2 | `uv run python v24/s13/test_wiring.py` |
| 3 | `uv run python v24/s13/test_descriptor.py` |
| 4 | `uv run python v24/s13/test_schema.py` |
| 5 | `uv run python v24/s13/test_renderers.py` |
| 6 | `uv run python v24/s13/test_results.py` |
| 7 | `uv run python v24/s13/test_registry.py` |
| 8 | `uv run python v24/s13/test_line_json.py` |
| 9 | `uv run python v24/s13/test_contracts.py` |
| 10 | `uv run python v24/s13/test_vectors.py` |
| 11 | `uv run python v24/s13/test_vectors.py --node` |
| 12 | `uv run python v24/b0/test_golden.py` |
| 13 | `uv run python v24/b0/test_golden.py --node` |
| 14 | `uv run python v24/load.py` |
| 15 | `uv run python v24/s1/setup_db.py --self-check` |
| 16 | `uv run python v24/s1/test_ddl.py` |
| 17 | `uv run python v24/s1/test_g1.py` |
| 18 | `uv run python v24/s2/test_g3a.py` |
| 19 | `uv run python v24/s3/test_g2.py` |
| 20 | `uv run python v24/s4/test_g2b.py` |
| 21 | `uv run python v24/s5/test_g4.py` |
| 22 | `uv run python v24/s6/test_g5.py` |
| 23 | `uv run python v24/s8/test_g7.py` |
| 24 | `uv run python v24/s7/test_g6.py` |
| 25 | `uv run python v24/s10/test_g9.py` |
| 26 | `uv run python v24/s11/test_g10.py` |
| 27 | `uv run python v24/s11/test_node.py --node` |
| 28 | `uv run python -m v24.host.plugin_smoke --multilingual-smoke` |
| 29 | `uv run python v24/s13/test_tools.py` |
| 30 | `uv run python v24/s13/test_lifecycle.py` |
| 31 | `uv run python v24/s13/test_node.py --node` |
| 32 | `git diff --exit-code c8c4bd0 -- v24/sql` |

**Runner 纪律**：一次只跑一个 producer（脚本会重建测试库）；直接捕获 exit，不用 pipeline/`tail`/合成 marker；执行前把 W6 record 第 1–31 行末行固化为外部 `expected-markers` 清单（Node 路径以本次预检实际解释器路径填入）；每行记录完整展开命令、UTC 起始、exit、真实末行、log SHA-256；记录实际 Python/Node/uv/OS/PostgreSQL 版本，不复制 W5/W6 的数值。

**接受条件**：1–31 条末行与清单逐字节相等；第 29 条精确为

```text
[passed] W4 fs tools; cases=140; read=16; read_probes=29; list=7; list_probes=11; search=24; search_probes=26; pagination_converged=true; page_contracts_imported=3
```

第 32 条 exit 0 且 log 为零字节、无末行。另单独运行 `git diff --exit-code -- v24/sql` 并记录。第 29 条的完整 log 还必须抓出 `[evidence] read_artifact_sha256=…; read_1m_wall_ms=…; read_peak_kib=…` 与 `[probe] W6-S25 real_clock_elapsed_ms=…` 两行，作为 C.18.2(d) 与 T3 的本轮证据；缺任一行即视为该条不完整。任一 exit 2 / `[SKIP]`、marker 不符或非零退出即停；修复本计划范围内的原因后从第 1 条重跑。C.18、pin 或测试输入在 sweep 后改变，原运行不再覆盖最终候选，必须重跑。

## 11. 证据、七项 audit 与记录

### 11.1 阶段 0 快照（每个里程碑各一份 `/tmp/v24-abi-<m3|m5>-<UTC>/`）

HEAD/upstream/branch/porcelain；全部 untracked 的路径、存在状态与 SHA-256；候选路径清单与初始摘要；design 原 bytes 与两个旧 pin；插件、`fixtures.py`、`test_tools.py` 摘要；计划版本/SHA；环境、Node 路径、marker 清单。计划文件与本次 plan critique 即使在 untracked 快照里也仍是显式候选。

### 11.2 七项 audit

| # | 名称 | 接受条件 |
|---:|---|---|
| 1 | `frozen_modules_and_untracked` | 复用既有六项 audit 的受跟踪路径清单；`test_contracts.py` 只允许 `DESIGN_SHA256` 归一化差异。另对阶段基线检查整个 `v24/host/**`、`v24/sql/**`、`v24/s13/**`：M3 仅豁免 README、mapping 的 SHA、测试常量；M5 仅豁免 README。新增/删除文件同样检查。 |
| 2 | `vectors_except_design_conformance` | 除 mapping 的已授权 SHA 外，整个 vectors 目录与阶段基线及继承基线一致（含 `vectors/README.md`）；M5 的 mapping 也必须完全不变。 |
| 3 | `design_conformance_restore` | M3：把新 SHA 单独替换回 `ab4636fc…` 后，mapping 与 `test_contracts.py` 分别与 `2307077` 原 bytes 完全相等；继承检查另用 `c8c4bd0` 自己的旧 pin 归一化。M5：与 M5-0 解析出的实际 M3 commit 逐字节相等，**不得用 `2307077` 作基线**。 |
| 4 | `registry_exact_patch` | 保留 `c8c4bd0` + D12 的 +5/−1 内存重建比较；当前 registry 同时与阶段基线完全相等。 |
| 5 | `host_import_purity` | 原 host 不依赖 s13 vector/reference 的审计通过；本轮不修改 host。 |
| 6 | `sql_zero_diff` | `git diff --exit-code c8c4bd0 -- v24/sql` 为空；快照排除未跟踪新增 SQL。 |
| 7 | `m3_candidate_only` / `m5_candidate_only` | 阶段基线的 tracked delta 加 untracked 新增/修改/删除只能落在该阶段候选集合；M3 另证 design 原 bytes 是精确前缀、全部 span 元数据不变。 |

**执行前必须确认**（只读检查，不改仓库）：audit runner 位于 `/tmp/w6-20261031T113313Z/`，需复制到新证据目录；确认 audit 3 动态读取当前 SHA 而非硬编码 `ab4636fc…`。若硬编码，只改 runner 并记录，这不是产品 STOP。若 `test_wiring.py` 的继承 audit 有额外硬编码导致无法只改单常量，保留失败证据并 STOP，不编辑测试绕过。

七项 audit 在 sweep 后预检一次，全部文档落盘后、staging 前再完整跑一次；staging 后核对 staged 路径与候选摘要。

### 11.3 记录结构

两份 record 均含：Result（只填本轮实测）、Candidate/provenance、Declaration-and-evidence mapping、Scope audits（预检 + 最终）、32-row table、Deviations、Limits、Publication。M5 record 另含 §7.5 五项完成映射与 34 行裁决表；matrix 收录同一张裁决表，record 引用 matrix 章节并绑定其最终文件摘要，避免两份不同裁决。

## 12. File-by-file impact

### 12.1 M3 提交（10 路径）

| 文件 | 变更 | 顺序 |
|---|---|---|
| `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md` | EOF 追加 C.18；追加前字节不动 | M3-2 首个 |
| `v24/s13/vectors/design_conformance.json` | 仅 `design_input.sha256_at_review → S1` | 与 design、test 原子 |
| `v24/s13/test_contracts.py` | 仅 `DESIGN_SHA256 → S1` | 原子 |
| `docs/investigations/v24-m3-budget-closeout-2026-10-31.md` | 标题状态行 + 文末 Resolution；正文不动 | M3-4 |
| `v24/s13/README.md` | 追加 M3 declaration 小节 | M3-4 |
| `docs/reviews/v24-conformance-matrix-2026-10-23.md` | 追加 M3 declaration 小节 | M3-4 |
| `docs/reviews/v24-deviation-ledger-2026-10-23.md` | 追加 `D-ABI-M3-1…7` | M3-4 |
| `docs/reviews/v24-tool-plugin-abi-m3-declaration-execution-2026-11-01.md` | 新增 record | M3-4 |
| `docs/plans/v24-tool-plugin-abi-m3-m5-closeout-2026-10-31.md` | 本计划；M3 Result 填入 | M3-0 / M3-5 |
| `docs/reviews/v24-m3-m5-closeout-plan-critique-2026-10-31.md` | 本计划的 critique；随计划入库，执行时只读 | M3-0 |

### 12.2 M5 提交（7 路径）

| 文件 | 变更 | 顺序 |
|---|---|---|
| `docs/designs/v24-pg-agent-2026-10-22.md` | §5.1/§5.4 同行改写；**必填**：附录 C 文末新增带日期修订条目 | M5-1 |
| `docs/investigations/v24-drift-factcheck-2026-10-29.md` | D2/D3/D4 带日期注记 + 状态行 | M5-2 |
| `docs/reviews/v24-conformance-matrix-2026-10-23.md` | 追加 M5 小节 + 34 行裁决表 | M5-5 |
| `docs/reviews/v24-deviation-ledger-2026-10-23.md` | 追加 `D-ABI-M5-1…3` | M5-5 |
| `docs/reviews/v24-tool-plugin-abi-m5-closeout-execution-2026-11-01.md` | 新增 record | M5-5 |
| `v24/s13/README.md` | 追加 M5 closeout 小节 | M5-5 |
| `docs/plans/v24-tool-plugin-abi-m3-m5-closeout-2026-10-31.md` | M5 Result 填入 | M5-5 |

M5 的 ledger 行：`D-ABI-M5-1` §7.5 文档对齐（DB/host/journal 所有权不变）；`D-ABI-M5-2` 34 位置逐条裁决、冻结字节无 promotion；`D-ABI-M5-3` 本轮 32-command、七项 audit、11/11 与限制。

**明确不改**：两个插件、`fixtures.py`、`test_tools.py`、其余测试/参考实现、preload、`capture_vectors.py`、其他 vector 文件、`v24/host/**`、`v24/sql/**`、loader、W5/W6 records、矩阵/台账中 W1–W6 的历史文字。

## 13. 风险、STOP 与回滚

| 风险 | 处置 |
|---|---|
| 执行前用户/产品否决 DM1 的 Option A | STOP；B（硬实时）下 M3 保持 blocked，C（删除 12 秒合同）需另立范围缩减与 C.18 重写，不能沿用本计划 |
| 起始 HEAD/upstream 不是 `2307077`，或出现无法解释的 tracked 改动 | STOP；保存差异，先修订基线与候选，不静默沿用旧 audit |
| M5 的 vectors 零 diff 或 audit 3 误用 `2307077` 而非实际 M3 commit | STOP；改用 M5-0 解析出的完整 SHA 重跑，不修改历史 |
| C.18 不是 EOF 追加，或 design 旧 bytes 不是精确前缀 | STOP；恢复原 bytes，只追加，不改 span 元数据 |
| 三处 pin 不一致，或 mapping 归一化后仍有差异 | STOP；检查授权字段，不扩大允许差异 |
| 把 `m3_pending`、占位 digest、compatibility 改成完成状态 | STOP；撤销差异，证据只写文档 |
| 既有 gate 出现新的硬编码不兼容（如 `test_wiring` 继承 audit） | STOP；保存日志；不改未授权测试 |
| gate exit 2、缺完整 marker、Node/preload 不可用 | 未验证；不得声明完成 |
| 真实 IO 过慢导致 S01/10k 用例触发 time-cap | 按 W6 风险记录重跑一次；再红则 STOP，绝不抬 cap |
| M5 把 v2 host 校验写成 DB 校验，或把 journal replay 写成工具自动重执行 | 修正文档并重审该段；不改运行时 |
| staged 出现候选外路径，或 untracked 路径未变但内容已变 | STOP；按 path + SHA 查明，不整体清理工作区 |
| push 被拒 / hook 失败 | 停在该步；保留 hook。远端变更先 `git fetch`，必要时 `git pull --rebase origin main`；禁止 force/reset-hard；历史分叉无法安全合并时问用户 |

**回滚**：提交前只按阶段 0 快照恢复本轮候选编辑，保留外部证据；已推送后只追加 revert 提交，不 reset/force。M3 已落地后若必须撤回，design、两个 pin 与声明必须同一次提交一起回退；M5 已依赖 C.18 时先回退 M5。

## 14. 工作项与执行索引

只有 **M3**、**M5** 是发布里程碑；下列编号是执行检查点，不各自触发提交。

| # | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| M3-0 | 固定候选、基线与证据输入 | `HEAD == origin/main == 2307077`；porcelain 与 untracked path+SHA 存入 `/tmp/v24-abi-m3-<UTC>/`；design 旧 SHA 与 `L0` 已记录；四个 vector 摘要已记录；audit runner 已复制并检查；Node 可用 | 证据目录、只读源码 | — | S |
| M3-1 | 起草 C.18 | 七个 `C.18.n` 条目齐全，每条事实都能对回 `fs_tools.js`/W5/W6 锚点 | ABI design（草稿） | M3-0 | M |
| M3-2 | 追加并原子 repin | §6 六步全过：前缀哈希、两个 pin 相等、25/23 span 不变、三条 marker 不变、`git diff --stat -- v24/s13` 恰两文件各 ±1 行 | design、mapping、`test_contracts.py` | M3-1 | S |
| M3-3 | M3 sweep 与 audit 预检 | 32/32 通过（1–31 marker 逐字节、32 空输出）；7/7 audit 通过；从第 29 条完整 log 提取本轮 `read_1m_wall_ms`/`read_peak_kib`/`read_artifact_sha256` 与 S25 `real_clock_elapsed_ms`/overshoot，并确认 R26 在 5000 ms 下为 success；不得照抄 W5 的 113 ms | 外部 runner/log | M3-2 | S |
| M3-4 | M3 声明工件 | README 小节、`D-ABI-M3-1…7`、调查 Resolution、matrix 小节与 M3 record 全部写入，数字取 M3-3 实测 | README、ledger、investigation、matrix、record | M3-3 | M |
| M3-5 | 定稿与最终 audit | plan Result 只含实测；文档落盘后最终 7/7 audit 通过 | plan、M3 record | M3-4 | S |
| M3-6 | 发布 M3 | 10 路径逐个 staging 并复查；凭据扫描干净；正常 hook commit `v24: declare Tool/Plugin ABI M3 complete`；非 force push；外部 receipt 记录 commit 与 `origin/main` 关系 | M3 十路径 | M3-5 | S |
| M5-0 | 固定 M5 基线并复核证据源 | M3 已推送；把 `git rev-parse HEAD` 的完整 SHA 写入证据目录并用于 vectors 零 diff 与 audit 3；新建 `/tmp/v24-abi-m5-<UTC>/` 快照；只读复核 W1–W4 execution records、W4/W5 计划与 W5/W6 critiques，形成 34 行证据层的绑定依据 | 本计划、证据目录、W1–W4 records、W4/W5 计划、W5/W6 critiques | M3-6 | M |
| M5-1 | 主设计 §5.1/§5.4 修订 | 正文 1–652 行内同行改写，`word-diff` 只动这两行；附录 C 新增一条带日期记录；既有 `L###` 锚点仍有效 | `v24-pg-agent`、ledger 草稿 | M5-0 | S |
| M5-2 | drift-factcheck D2/D3/D4 | 三条带日期注记 + 状态行；历史文字未改；D2 引用已修订的主设计 | drift-factcheck | M5-1 | S |
| M5-3 | 34 位置裁决 | matrix 表 34 行完整，脚本计数=34，每行有证据指针与裁决；相对实际 M3 commit 的 vectors 零 diff 证明通过 | matrix、M5 record、ledger | M5-0 | M |
| M5-4 | M5 sweep 与 audit 预检 | 本轮独立 32/32；`git diff --exit-code -- v24/sql` 为空；从 row 29 完整 log 取 `read_artifact_sha256` 与 S25 elapsed/overshoot，并记录 `fs_tools.js` 源文件的本轮 SHA-256（安装副本以 S24 的三者相等断言为证）；7/7 audit（delta 基线 = 实际 M3 commit SHA） | 外部 runner/log | M5-1, M5-2, M5-3 | S |
| M5-5 | 定稿 M5 收口 | README/matrix/ledger/record/plan 只填实测；34 行与 §7.5 映射一致；最终 7/7 audit | README、matrix、ledger、record、plan | M5-4 | M |
| M5-6 | 发布 M5 | 7 路径逐个 staging 并复查；凭据扫描干净；正常 hook commit `v24: close out Tool/Plugin ABI M5`；非 force push；receipt 完整 | M5 七路径 | M5-5 | S |

依赖顺序：

```text
M3-0 → M3-1 → M3-2 → M3-3 → M3-4 → M3-5 → M3-6 → M5-0
M5-0 → M5-1 → M5-2 ─┐
M5-0 → M5-3 ────────┴→ M5-4 → M5-5 → M5-6
```

M5-3 与 M5-1/M5-2 文件不重叠，可与 M5-1 并行，并与 M5-2 一同进入 M5-4；M5-2 依赖 M5-1（D2 必须引用修订后的主设计）；sweep 必须串行。

## 15. 提交与推送

**顺序不可颠倒**：测试实跑全绿 → 收尾工件更新 → 按路径 `git add` → 复查 staged → 凭据扫描 → commit → push。

M3：

```bash
git add docs/plans/v24-tool-plugin-abi-m3-m5-closeout-2026-10-31.md \
        docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md \
        v24/s13/vectors/design_conformance.json \
        v24/s13/test_contracts.py \
        v24/s13/README.md \
        docs/reviews/v24-conformance-matrix-2026-10-23.md \
        docs/reviews/v24-deviation-ledger-2026-10-23.md \
        docs/reviews/v24-tool-plugin-abi-m3-declaration-execution-2026-11-01.md \
        docs/investigations/v24-m3-budget-closeout-2026-10-31.md \
        docs/reviews/v24-m3-m5-closeout-plan-critique-2026-10-31.md
git commit -m "v24: declare Tool/Plugin ABI M3 complete"
git push origin main
```

M5：

```bash
git add docs/plans/v24-tool-plugin-abi-m3-m5-closeout-2026-10-31.md \
        docs/designs/v24-pg-agent-2026-10-22.md \
        docs/investigations/v24-drift-factcheck-2026-10-29.md \
        v24/s13/README.md \
        docs/reviews/v24-conformance-matrix-2026-10-23.md \
        docs/reviews/v24-deviation-ledger-2026-10-23.md \
        docs/reviews/v24-tool-plugin-abi-m5-closeout-execution-2026-11-01.md
git commit -m "v24: close out Tool/Plugin ABI M5"
git push origin main
```

禁止 `git add -A` / `git add .`、`--no-verify`、force-push。绝不 staging：`.ctx-export-*`、`.token-probe*`、`ctx_export_check*`、`v20/experiments/ce_native_d5/**`、`prompt-exports/`、任何 `.env`。M3 未成功推送不开始 M5；每次推送后记录本地 commit 与 `origin/main` 的实际关系。

## 16. 本计划不证明什么

- 任意文件系统上的硬实时 12 秒上界、固定 cutoff 位置或相同 overshoot。
- 任意慢 scope 的分页穷尽。
- Linux real 非 UTF-8、macOS 子目录非法名称注入。
- 跨平台 timing、恶意并发 workspace 隔离、原子文件快照。
- 新的工具 replay 权、DB transcript 派生、真实 provider 行为。
- 冻结向量获得新的终态 token。
- 本文未执行的任何 gate 或 publication 已成功。

closeout 仍然是 11/11，s13 仍然是 extension evidence。

## 17. References

- `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:765-887`（§5.6/§6 工具合同）、`:952-1068`（§7.4/§7.5/§10）、`:1286-1395`（C.11–C.17）。
- `docs/reviews/v24-tool-plugin-abi-w6-execution-2026-10-31.md`（32 行表、七项 audit、D-ABI-W6-1…14、Limits）。
- `docs/reviews/v24-m3-m5-closeout-plan-critique-2026-10-31.md`（18 条 findings；逐条落实见 `## 批判意见落实`）。
- `docs/reviews/v24-tool-plugin-abi-w5-execution-2026-10-31.md`（read 收口、AST 读取常量的 runner 记录）。
- `docs/investigations/v24-m3-budget-closeout-2026-10-31.md`（Option A/B/C 与最小收尾序列）。
- `docs/investigations/v24-drift-factcheck-2026-10-29.md:42-186`（D2/D3/D4 历史核查与修法表）。
- `docs/designs/v24-pg-agent-2026-10-22.md:269-309`（待修订主设计）。
- `docs/plans/v24-tool-plugin-abi-w6-node-list-search-2026-10-31.md:23-66`、`:451-533`、`:622-648`（house style）。
- `v24/s13/test_contracts.py:1-139`、`v24/s13/vectors/README.md:1-11`（冻结与只读 checker）。
- `docs/reviews/v24-conformance-matrix-2026-10-23.md:619-753`、`docs/reviews/v24-deviation-ledger-2026-10-23.md:597-698`（追加格式与既有措辞）。
- `AGENTS.md:5-79`（里程碑、路径级 add、push 与外部 IO 约束）。

## 批判意见落实

来源：`docs/reviews/v24-m3-m5-closeout-plan-critique-2026-10-31.md`（会话 `00B9043B-247D-4659-978F-A8539A96C506`）。第 1–12 条针对上一版、已在第 2 版落实；第 13–18 条针对第 2 版、由本版修正。下表同时复核 1–12 的当前落点。

| # | 级别 | 本版处置 | 落点 |
|---:|---|---|---|
| 1 | blocker | `design_conformance` 的 10 个只按 `immutable_required_suites[*].status` 计；2 个 `design_resolved` 属 `reviewed_design_decisions`，不计入 34；先落 34 指针清单并断言 8/10/5/11 | §9 范围、计数校验 |
| 2 | blocker | 附录 C 的带日期条目为必填；判据为正文 1–652 除两行外零 diff + `L###` 锚点有效，不以 `wc -l` 不变为判据 | §8.1、M5-1 |
| 3 | major | S06–S11 只绑注入时钟的 time-cap/EOF/sentinel；S01–S05 绑 file-cap，S12 绑候选失败次序 | C.18.3 |
| 4 | major | 过冲单元写明 readdir + sort + 逐条 lstat/分类 + 至多一个 ≤1 MiB 文件读取/扫描 | C.18.4 |
| 5 | major | 补全终结判定次序：源错误/非法整数 → m=0 → offset → 无前缀 → cutoff → 成功 | C.18.5 |
| 6 | minor | provenance 只用于四个 pending token；另外五个 vocabulary 值语义不变 | C.18.6 |
| 7 | major | M3 row-29 完整 log 取本轮 read 证据与 S25 probe；确认 R26 在 5000 ms 下 success，不抄 W5 的 113 ms | C.18.2(d)、§10、M3-3 |
| 8 | major | 裁决行含 JSON 指针/case id、token、两个 stage、本轮证据、裁决、限制、字节 audit | §9 列定义 |
| 9 | major | M5-0 先只读复核 W1–W4 records、W4/W5 计划、W5/W6 critiques | M5-0 |
| 10 | major | D2 引用修订后的主设计；M5-2 依赖 M5-1，仅 M5-3 并行 | §8.2、M5-2、依赖图 |
| 11 | major | critique 列为发布候选，进入快照/候选/audit/staging；M3 为 10 路径 | DM10、§11.1、§12.1、§15 |
| 12 | minor | C.18.1 恢复 M5 continuation 行 | C.18.1 |
| 13 | blocker | `2307077` 只用于 M3 的 mapping-SHA 一行；M5 用实际 M3 commit SHA 作空 vectors 零 diff 基线 | DM7、§9、audit 3、M5-0、M5-4 |
| 14 | major | `offset_out_of_range` 移出源错误层；空快照在 m=0 处理，非空快照在快照校验后、前缀枚举前处理 | C.18.5 |
| 15 | major | C.18.1 两行改为 done-when，声明以 execution record 为准；M5 行补 SQL 零 diff + 11/11 | C.18.1、C.18.7 |
| 16 | major | Resolution 增加 #15→W6-1/S17/C.18.7、#16→S02/W6-10；Finding 1 补 W6-9 与 W6-2/3 | §7.4 |
| 17 | minor | 主设计 M5 修订记录改为必填带日期附录 C 条目 | §8.1、§12.2、M5-1 |
| 18 | minor | M5 以 row-29 本轮 R28/S24 实测 digest 为准；W5/W6 值仅历史交叉核对 | §9 列定义、§9.3、M5-4 |

## Result

**M3 与 M5 均已执行（2026-11-01 +08:00）。**

M3 的 32 条串行命令在 `main` @ `23070776b0ac16749a7ff87729bb1782fb331f27` 上运行：第 1 条于 2026-10-31T16:38:23Z 开始，第 32 条于 16:40:30Z 开始（命令起始时间，不作端到端耗时），32/32 exit 0。第 1–31 条末行为各自命令专属真实 `[passed]`；第 32 条 `git diff --exit-code c8c4bd0 -- v24/sql` exit 0、输出为空、无 `[passed]`。无 exit 2/`[SKIP]`。第 29 条实际 marker：

```text
[passed] W4 fs tools; cases=140; read=16; read_probes=29; list=7; list_probes=11; search=24; search_probes=26; pagination_converged=true; page_contracts_imported=3
```

本轮 read 证据为 `read_artifact_sha256=260274daba1efa87f4c33103fe53503c76a65187af68e610d5aedcfadad5165c`、`read_1m_wall_ms=97`、`read_peak_kib=3959.904`，R26 在 5000 ms deadline 下 `success`；T3 S25 为 `real_clock_elapsed_ms=50.463`、overshoot `0.463`，只记录。C.18 追加使 design 从 113843 → 121521 bytes、`ab4636fc…` → `778b13a4…`；旧 bytes 是精确前缀，25 处引用 / 23 个 span 的行范围、heading、内容 SHA 不变，mapping 与 `test_contracts.py` 各只改一行且都等于新 SHA。七项 audit 预检与文档后 final 均 7/7 exit 0；final 起始时间 2026-10-31T16:42:59Z。证据目录 `/tmp/v24-abi-m3-20261031T163642Z/`。

M3 的声明工件已写入：C.18、README、`D-ABI-M3-1…7`、调查状态行与 Resolution、matrix 小节、M3 execution record。发布单元为 §12.1 的 10 路径；按路径 staging、正常 hook、非 force push，真实 commit SHA 与推送结果由外部回执报告，本文不嵌入自身提交哈希。

M5 在 M3 commit `e58204c29afacd27b72e35e9e7eaeb6e32c11dac` 上独立运行 32 条串行命令：第 1 条 2026-10-31T16:45:18Z 开始，第 32 条 16:47:28Z 开始，32/32 exit 0；第 32 条 SQL diff 输出为空。第 29 条 marker 与 M3 相同；本轮 `read_artifact_sha256=260274daba1efa87f4c33103fe53503c76a65187af68e610d5aedcfadad5165c`、`read_1m_wall_ms=97`、`read_peak_kib=3959.904`，S25 `real_clock_elapsed_ms=50.635` / overshoot `0.635`。34 个冻结 `status` 位置由脚本定位并逐条裁决：`tool_contracts=8`、`design_conformance=10`、`manifest_adapter_v2=5`、`results_v2=11`；2 个 `design_resolved` 不计入；裁决为 E-SAT 28 / E-SAT-T 3 / E-SAT-PH 2 / FROZEN-EXPECTED 1，JSON 零字节变化。M5 的 vectors 零 diff 基线是实际 M3 commit，不是 `2307077`；`git diff --exit-code e58204c -- v24/s13/vectors` 为空，`v24/sql` 对 `c8c4bd0` 与 M3 commit 均为空。七项 audit 预检与文档后 final 均 7/7；closeout 仍 11/11。主设计 786 → 795 行，正文 1–652 除 275/297 两行外零 diff，附录 C.7 带日期追加；drift D2/D3/D4 已加注。证据目录 `/tmp/v24-abi-m5-20261031T164407Z/`。

M5 的 34 行裁决表在 matrix 的 `## Post-closeout Tool/Plugin ABI M5 closeout (2026-11-01)` 小节，M5 record 绑定其文件摘要 `f7209fc292b36af2741bae05215416cf9e8777b67d0058cec1517a10621191a6`（以最终落盘为准）。发布单元为 §12.2 的 7 路径；真实 commit SHA 与推送结果由外部回执报告。

| 里程碑 | Gate | Scope audit | 工件 | Commit / push |
|---|---|---|---|---|
| M3 declaration | 32/32 exit 0；第 29 条 marker 与接受条件逐字节相等；第 32 条空输出 | 7/7 precheck + 7/7 final | C.18、README、ledger、matrix、investigation Resolution、M3 record 已写入 | 10 路径，结果见外部回执 |
| M5 closeout | 32/32 exit 0；第 29 条 marker 与接受条件逐字节相等；第 32 条空输出 | 7/7 precheck + 7/7 final | §7.5 文档、34 行裁决、README、ledger、M5 record 已写入 | 7 路径，结果见外部回执 |

完成后只填本轮实际结果；W5/W6 的通过、耗时、digest 与发布状态不得代填。
