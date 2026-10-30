# v13 原生 read 工具计划 —— 批评与修正

> 审查对象：`docs/plans/v13-native-read-tools-2026-09-27.md`（下称「计划」，431 行）。
> 基线：`prompt-exports/oracle-plan-2026-09-27-005736-v13-native-read-tool-1c5d.md` 中三份生成计划
> （Oracle 1 = 230–719 行；Oracle 2 = 729–1797 行；Oracle 3 = 1807–2278 行）。组合提示词与选中文件转储只作背景，不当作计划内容。
> 日期：2026-09-27。范围：只审计划与导出，不改计划、不实现。
> 用户已确认、本审查不复开：闭合 fixture 路径（hello.txt/crlf.txt 仅判断面）；三个口岸围到显式 root（Pi 的 `~` 与绝对路径逃逸是有意偏差）；图片字节不进 jsonb（`image_unsupported`）。

结论先行：计划整体是三者中最好的整合，算术（`max_cycles≥5`）、加载边界（seam）、`offset_out_of_range`、闭选项、失败分类都对。**但计划漏掉了导出里的 4 项承重内容，把 3 项「必做检查」降级为「建议」，并有 2 处引用/事实错误、1 处与已确认裁决自相矛盾。**下列 F1–F12 按「是否改变计划文本」排序：F1–F6 必须改，F7–F9 建议改，F10–F12 供澄清。

---

## 1. 导出中的承重内容在计划里缺失、弱化或泛化

### F1（必须改）· 缺失：`worker:harness_turn` 是第四个已注册工具，负例「三条 route」的算术基础被低估

计划 §2.1 只说「目录里不止种子两行」，列出 `harness_turn` 与三个 worktree 工具，并给出**基线 6 行、needed 9、插入后 15**。本轮实查（`INSERT INTO tools` 全树扫描）确认目录行共 **6** 行：

| 来源 | 行 | name | kind | param_spec |
|---|---|---|---|---|
| `v13_core.sql:932` | 2 | `session_stats`, `send_summary_email` | sql, tool | `{}` / tone+audience |
| `v13_control.sql:92` | 1 | `harness_turn` | tool | `{}` |
| `v13_spawn.sql:1757` | 1 | `spawn_subsession` | sql | `{}` |
| `v13_fanout.sql:1062` | 3 | `worktree_prepare/merge/release` | tool | `{}` |

计划**漏掉了 `spawn_subsession`**（`v13/spawn/v13_spawn.sql:1757`，stage=18，在 fanout=19 与 triage=20 **之前**，因此既然加载到 seam 就一定在库内）。这直接动摇 D3 里「基线 6 行」的断言：**基线是 7 行，不是 6 行**。

更承重的是它对**负例**的影响。计划 §3.5 与 D4 断言「恰好三条 `turn/route`，action 为 tool/tool/tool」。但 `v13_route` 的 P4a 分支（`v13/loop/advance.sql:85`）写的是：`tools.kind='sql'` 且 enabled → `{action:'sql'}`；只有当 intent 的 choice 是 `tool_action` 且 `tool` 信号命中 pass 带时才走 `tool` 分支。`spawn_subsession` 是 `kind='sql'`，会进入 `tool` choice 的 criteria（`v13_resolve.sql:81` 的 `tools.kind IN ('sql','tool')`）。计划 mock 表把 `tool` choice 钉成具体工具名（`read_pi`…），所以路由不会被 `spawn_subsession` 抢走——**这一点是对的**；但计划从未说明「`tool` choice 的 criteria 里现在有 4 个非种子名」，而 R4 的 `V3001` 整批拒绝恰恰由 criteria 内容驱动。若实现者按 Oracle 1 的 P5/mock 表照抄而漏改 criteria 相关断言，`remaining==0` 会以难查的方式红。

**修正**：
- D3 断言改为「基线 = **测量值**（当前预期 7 行）+ 3，needed +6」；把「6 行」改成「7 行」并在 README 记下 `spawn_subsession` 这一行。
- §2.1 的插入列表补上 `v13/spawn/v13_spawn.sql:1757`（`spawn_subsession`，`kind='sql'`，空 param_spec），并明确「`tool` choice criteria 在 seam 前缀里含 4 个非种子工具名」。
- needed 算术：4 固定 + 1 tool + 6 新 + 4（email）+ 0（其余全空 param_spec）= **15**。计划写的 15 仍对，但推导里必须承认基线工具是 7 行（3 个空 spec 的 tool + 1 个空 spec 的 sql），否则「needed 9」这个中间量对不上。

### F2（必须改）· 缺失：导出要求逐字钉死上游 LICENSE 全文的来源路径，计划保留但没钉 `repoprompt-ce/LICENSE` 的**可读性前置**

计划 §4 写「`LICENSE` 全文照抄，不凭记忆重打」，出处 `MCPDomainCanonicalWorkspaceService.swift:171-193` 与 `DirectHeadlessDomainContext.swift:302-333`。但没有给出 **RP-CE 的本地 checkout 路径**，而 Oracle 2 §3.4 与 Oracle 3 §3.12 都明确要求「`repoprompt-ce/LICENSE`」作为可执行锚点，且 Oracle 2 §3.6 进一步要求：**若本地 Pi checkout 版本不是 0.80.3，M1 必须 `not_run/source_version_mismatch` 退出 2，不得静默移植别的版本。**

本轮实查：`/Users/wxl/Projects/repoprompt-ce` 与 `/Users/wxl/Projects/pi` 都存在；`pi/packages/coding-agent/package.json` = `@earendil-works/pi-coding-agent` **0.80.3**（吻合）；`pi/LICENSE` = MIT / © 2025 Mario Zechner（吻合）。**但计划完全没有「版本校验」这一步**——Oracle 2 和 Oracle 3 各自把它列为 M1 的**硬前置**（exit 2 `not_run/source_version_mismatch`），计划把它降级没了。

**修正**：§3.2 增一条 preflight（P8 — 上游版本）：读 `pi/packages/coding-agent/package.json` 的 `version`，非 `0.80.3` 即打印 `[SKIP] not_run/source_version_mismatch` 退出 2；P5 的转录前置加上 `test -r /Users/wxl/Projects/pg-agent/../repoprompt-ce/LICENSE`（或环境变量覆盖）。这是 M1 的 gate 前置，不是建议。

### F3（必须改）· 弱化：Pi 的「未知请求键忽略」与「Pi 数值参数类型校验」被计划丢掉

Oracle 2 §3.3（「Rules」）写了三条计划没有的线协议规则：
1. **未知请求键忽略**（unknown request keys ignored）；
2. `root` / `path` 必须是 JSON 字符串，**类型不对 → `invalid_params`**；
3. **Pi 的 `offset` / `limit` 必须是正整数；类型错、0、负数 → `invalid_params`。**

计划 §3.1 只说「非整数或字符串，headless 当 `None`」，对 Pi 一侧的数值类型纪律完全沉默。这不只是措辞：`read.ts:20-24` 用的是 `Type.Number()` schema，而 `offset ? … : 0`（`read.ts:271`）依赖 JS 真值——`0` 与 `NaN` 都落 `0`；**负数**才是 `Math.max(0, offset-1)`。计划 §3.3 已正确记下「负 offset 为真值仍从开头起」，但**没有让岸口把「类型错」与「负数」区分开**。Oracle 2 要求 Pi 侧对 `0`/负数/错类型统一 `invalid_params`；这与上游真值语义冲突（上游 `0` 是从头读，不报错）。

**修正**：明确取计划现有裁决（不采纳 Oracle 2 的「0 → invalid_params」），但在 §3.1 补齐两条被丢的规则：未知键忽略；`root`/`path` 非字符串 → `invalid_params`。并在 §2.4 / R3 的偏差台账里点明「Pi 侧 `offset:0` 与上游一致地从头读，Oracle 2 的 invalid_params 方案被拒，理由：与 `read.ts:271` 真值语义相反」。

### F4（必须改）· 泛化：C 组漏掉 `read.ts:280-288` 的「先切片再截断」字节顺序锁，C3/C4 覆盖不到

计划 C3 只覆盖「用户 limit 小于两个默认帽 → 无默认帽通知、有 more-lines 通知」，C4 只覆盖「撞帽 → 通知」。**两者都没锁住「用户 limit 先于 `truncateHead` 应用」这一顺序**在**字节**维度上的行为：`read.ts:280-288` 是先 `slice(startLine, endLine)` 再 `truncateHead(selectedContent)`，即用户 limit 切出的内容**仍要**过 2000 行 / 50KB 帽。Oracle 3 §3.11 C3 用「3000 行 + limit=5 → 5 行且无通知」锁了行维度；计划 C3 的措辞（「那么多行，没有默认帽通知」）能覆盖行维度，但**若 limit 切出的切片本身超过 50KB**（例如 limit=5 而每行 20KB），先切片后截断会产生字节通知——计划没有这一行。

**修正**：C 组增一行 `C3c`：tmp 文件 5 行 × 20KB，`limit=5` → 走字节截断，出现 `read.ts:302` 的 `(50.0KB limit)` 变体通知（而非 more-lines 通知）。期望字符串取自 §2.4 的源码钉死值。这同时锁住 `formatSize` 的 `50.0KB` 渲染与「先切片」顺序。

### F5（必须改）· 缺失：Oracle 1 的 P3「finish / closeout 字面量必须在**实际加载的那个 advance** 上核实」被计划保留，但计划把 P3 的**结论**当成已知

计划 §3.5 幸福路径断言「最后一次 advance 是 `terminal`，`turn/end` 且 `delivered=true`；一条非空 `llm/message`」。计划 R9 只说 R9 = 停在 triage，却没在 §3.2 P3 之外把「finish 臂」列为**必须实机确认**的项。Oracle 1 §3.2 P3 明确说：这是 `test_loop.py` M3-6 **只在 loop stage 证明过**的东西；triage 的 `v13_advance` 覆盖了 loop 的版本（`v13/load.py`：`loop/advance.sql` 在前，`triage/v13_triage.sql:561` 在后），**loop stage 的 finish 行为不是 triage 的证明**。

本轮实查确认了这条风险是真的：`v13_advance` 有 **5 个**定义（`loop/advance.sql:197`、`fanout:480`、`spawn:998`、`control:1150`、`triage:561`），加载到 seam 时生效的是 triage（spawn 在 triage 之前，control 也在之前）。计划 R9 已经对，但**没有把「finish 臂存在且返回 terminal」列为 P3 的显式检查项**——它只列在 Oracle 1 的 P3，计划 §3.2 里没有 P3。

**修正**：计划 §3.2 增 **P9 — finish 臂确认**：在 seam 前缀实际加载的 `v13_advance` 上核实「`llm/message` 锚定在 `origin_user_seq = last user seq` → 返回 `terminal` 且 closeout `sessions.status='completed'`」；若该臂缺失或语义不同，D6 的第五条 route 断言（`finish`）按实测改写。**这不是可选检查**：幸福路径的收尾断言直接依赖它。

### F6（必须改）· 与已确认裁决矛盾：计划 D3 把 `crlf.txt` 放进判断面 options，但 D3 用户确认的原文是「闭合 fixture path」

计划 §3.4 的 `param_spec.options` 是 `{"hello.txt": …, "crlf.txt": …}`，且 §1 明确「D3（闭合 fixture path）… 已于 2026-09-27 由用户确认」。用户确认的是**闭合**（枚举式，不是自由字符串），**不限定枚举几个**——所以把 `crlf.txt` 放进去**并不违反**确认。但计划 §3.4 自己的编排第 3 步「在一次性 session 上量 needed 基线」与 §3.5 的 mock 表「param choice = `hello.txt`」+ D7「`params={"path":"hello.txt"}`」意味着：**`crlf.txt` 这个 choice 在环上永远不被选中，它存在的唯一作用是让 needed 多一个 `param::…::path` 的 choice 值。** 这不是矛盾，是**未言明的设计意图**：计划没有说明为什么 options 里要有 `crlf.txt`（Oracle 1 §3.6 同样列了两个，但也没解释）。

**修正**（澄清，非纠错）：§3.4 补一句「options 含 `crlf.txt` 是为了让判断面的 choice criteria 与 fixture 集合一致（D3 的闭合语义），环上永不选中；CRLF 语义由 C9/A7 直接调口岸覆盖。」若实现期决定去掉 `crlf.txt` 以缩小 criteria，则 needed 基线改为 +3 个信号、D3 断言同步改——**二者选一，必须写死，不能留给实现者**。

---

## 2. 欠规定的接缝、未决的实质决策、矛盾、错误引用、缺失依赖

### F7（建议改）· 错误引用：`v13_complete` 的 fanout 定义已被 seam 替换，计划 §2.2 引用**两处**都点 fanout

计划 §2.2 正确写了「`v13_complete` 的最后定义在 `v13/seam/v13_seam.sql:419`」，这很好。但同一节的 `v13_claim` 引用 `v13/fanout/v13_fanout.sql:266` 是对的（seam **不**替换 claim——本轮实查 `grep v13_claim` 只有 fanout:266 与 `v13_core.sql:267` 两处，无 seam 定义），而 `v13_advance` 引用写了 `v13/triage/v13_triage.sql:947-978` 的 `WHEN 'tool'`——正确（triage:561 是最后定义者，seam 不替换 advance）。**但 §5 的 R9 与 §3.2 的加载字串把「seam 替换了 `v13_complete`」当成唯一替换**，而 Oracle 1 P1 与 Oracle 3 Step 0 都要求对 `v13_advance`/`v13_claim`/`v13_complete`/`v13_route`/`v13_enqueue_effect`/`v13_needed_judgments`/`v13_closeout` **全部**做「谁最后定义」检查。

本轮实查结论（供计划直接采用，不必再查）：
- `v13_complete` → **seam:409**（最后）
- `v13_advance` → **triage:561**（最后；seam 无）
- `v13_claim` → fanout:266（最后）
- `v13_route` → `loop/advance.sql:110`（唯一）
- `v13_needed_judgments` → **triage:1005**（最后；`v13_resolve.sql:55`、`envelope:336`、`spawn:1437` 均被覆盖）
- `v13_parse` → `resolve/v13_resolve.sql:661`（最后；`economy:353` 被覆盖）
- `v13_closeout` → `spawn:585`（最后；`control:618` 被覆盖）

**修正**：把 §3.2 的加载判定从「只查 seam 是否替换 advance/claim/complete」改成 Oracle 1 P1 的完整函数清单，并把上表结论作为**已核实的 preflight 输出**写进计划（省去实现者重查）。特别提示：`v13_needed_judgments` 的最后定义是 **triage:1005**，不是 `v13_resolve.sql:55`——计划 §2.1 引用 `:55-148` 讲信号形状，信号形状没错，但**判断面信号生成的生效版本是 triage 的**，实现者若去读 `v13_resolve.sql` 的版本会读到被覆盖的那份。这是**错误引用的实质风险**（Oracle 3 §2.1 就已经对 `v13_needed_judgments` 做了 triage 覆盖的提醒）。

### F8（建议改）· 未决：`v13_complete` 的 `result` 绑定「jsonb 字符串」在 hub 侧的具体拼装未钉

计划 §3.1 说「成功：`v13_complete(..., 'succeeded', to_jsonb(text))`」，§3.5 的 llm 分支说 `result {"text": ...}`，human 分支说 `{"reason": ...}`。但 `v13_complete(p_effect, p_attempt, p_fence, p_status, p_result jsonb)` 的 `p_result` 是 **jsonb 参数**，Python 侧要先 `json.dumps(text)` 再 `%s::jsonb`（Oracle 3 §3.7 与 §3.9 都点明「bare Python str 会被当 JSON 文档解析」）。计划写了 `to_jsonb(text)`——那是**SQL 侧函数**的写法，不是 psycopg2 绑定的写法。**计划 §3.5 的伪码是 SQL 语义，未说 hub 用哪个 Python 表达式。** 这是实现期最易错的一处（文件正文恰为 `true`/`42`/`{…}` 时静默改型）。

**修正**：§3.5 补一句确切绑定式：`cur.execute("SELECT v13_complete(%s,%s,%s,'succeeded',%s::jsonb)", (eid, attempt, fence, json.dumps(text)))`，并保留 D8 的 `jsonb_typeof(result)='string'` 断言。同时把「文件正文看起来像 JSON」的**反例 fixture** 加进 D 组或 A 组：`read_text` 对内容为 `true` 的文件返回字符串 `"true"`——计划 §3.1 提了这条要求但**没有任何一行断言测试它**。

### F9（建议改）· 未决：`v13_requeue_stale` 不调用的**唯一**依据是「gate 不调」，但子进程 30s 超时 > 租约 60000ms 的一半，且**崩溃路径**未覆盖

计划 §3.5：租约 60000 ms、子进程超时 30 s、不调 `v13_renew_lease`、不调 `v13_requeue_stale`。§3.11 说「Lease is 60000 ms. Subprocess timeout is 30 s」——但 **hub 的每拍含 parse + advance + claim + IO + complete**，若 IO 用满 30 s，加上前两拍的事务时间，**接近但不超过 60 s**，看起来安全。真正未覆盖的是**崩溃**：`test_read_tools.py` 在 claim 已提交、complete 未开启之间被 Ctrl-C 或断言异常时，claim 留在 `claimed` 且租约 60 s 后过期，`v13_requeue_stale`（若被别的 stage 或人工触发）会把它收成 `unknown` —— 而计划 §8 明确「不结算 `unknown`」。Oracle 1 §3.11 用 `finally` 覆盖了「幸福路径在 finally 里 complete」，计划 §3.5 只写了「每次 advance 前 SET LOCAL…」，**没有写 finally 的 complete 兜底**。

**修正**：§3.5 补「每拍 IO 用 `try/finally` 包住；`finally` 里以同一 `(attempt, fence)` 调 `v13_complete(..., 'failed', {"error":"protocol_error", ...})`，确保进程异常退出时行不留在 `claimed`」；并明确「若 finally 也失败，则接受残留（下次 `setup_db` DROP 库），但 gate 必须 exit 1，不得静默」。

### F10（建议改）· 未决：hub 不注入 `start_line`/`limit` 时送 `null` 与「缺键」的语义差在 headless 上等价，但**对 Pi 不等价**

计划 §3.1：「判断面只选出 `path` 时，hub 给 Swift 送 `start_line: null, limit: null`，给 Node 送 `offset: null, limit: null`。null 或缺失走全文/默认截断。」对 headless（Swift `intValue` nil → 走全文）成立。对 Pi：`offset: null` 走 `offset ? … : 0` → 0 → 从头读（对）；`limit: null` → `limit !== undefined`？**`null !== undefined` 为真**，所以 `read.ts:281` 的 `if (limit !== undefined)` 会**进入 limit 分支**，`Math.min(startLine + null, …)` = `Math.min(0, len)` = 0 → **空切片**！计划 §3.1 只说了「null 或缺失走全文/默认截断」，**没有区分 Pi 的 `limit: null` 会命中真值分支**。这是**具体的行为错误**：`read_pi.mjs` 若直接把 `JSON.parse` 出来的 `null` 交给 Pi 逻辑，`limit:null` 会返回空串而非全文。

**修正**：§3.3（Pi 算法）明确：**`limit` 为 `null`/缺失时省略该键**（或归一化为 `undefined`），不得传 `null`；`offset` 为 `null` 等价于 0（可从头读），但实现上同样建议省略。C 组增一行：`{"root","path","offset":null,"limit":null}` → 全文（锁住「null 不得当作 `limit=0`」）。顺带把「`limit:0` → 空切片，不抛」（计划 C3b）与「`limit:null` → 全文」并列，防止二者混淆。

### F11（澄清）· 依赖缺失：`v13_advance(sid, snap)` 的 `snap` 来源与「stale」处置在负例的第二次 parse 之后未写

计划 §3.5 第 2 步 `v13_parse` → 第 3 步 `v13_advance(sid, snap)`；负例的第二次 parse（human 结算后）需要**新的 snap**。计划 §3.7 的编排写了「再 parse+advance」，但 §3.5 的每拍伪码把 `snap` 当作拍内产物。Oracle 1 §3.7 明确 `r = SELECT v13_advance(sid, snap)` 并在 `stale` 时 fail。计划 §3.5 说「`stale` 或 `progressed` 即红（本脚本在 parse 与 advance 之间不改目录）」——对，但**human 结算那一拍之后目录没变，snap 却是新的**。实现者需要知道：**每拍用当拍 parse 返回的 snap**，不能复用上一拍的。计划没写。

**修正**：§3.5 补一句「`snap` 一律取当拍 `v13_parse` 的返回值，跨拍不复用」。

### F12（澄清）· 矛盾/冗余：计划 §2.1「needed 15 ≤ batch 32」与 D3「needed ≤ 当前 batch_questions」重复且第二个更弱

§2.1 说「若实测 needed 超过 `batch_questions`，gate 红，本计划不提高 batch」；D3 说「needed ≤ 当前 `batch_questions`」。二者一致，但 §2.1 的推导给出**具体数 15** 与「6 行工具、needed 9」的中间量（F1 已指出 6→7 的错）。D3 的措辞「needed ≤ 当前 batch_questions」若只断言不等式，**无法发现 `spawn_subsession` 这类新增**（它不加信号）。建议 D3 同时断言「needed == 基线 needed 测量值 + 6」，两条件并存。

**修正**：D3 = ①`count(*)` 增量 +3；②needed 增量 +6；③needed ≤ `batch_questions`。三条缺一不可。

---

## 3. 代码否证的、任务不需要的、更简单设计完全取代的

### F13（必须改）· 代码否证：`v13_requires_worktree` 只对 `worktree_merge`/`worktree_release` 为真——计划引用正确，但**结论被过度外推**

计划 §2.2 说「`v13_requires_worktree` 只对 `worktree_merge` / `worktree_release` 为真（`v13_fanout.sql:46-48`），这三个 read 工具不需要 worktree latch」。**引用与结论都对**（本轮实查 `v13_requires_worktree` = `coalesce(p_name IN ('worktree_merge','worktree_release'), false)`），但计划没有回答「那么 `v13_claim` 的 worktree latch 分支对这三个工具会怎样」——`v13_claim` 的谓词包含 worktree latch（计划 §2.2 自己说「The predicate is status, `v13_attempt_ok`, `op_seq`/`mutation_scope`, and a worktree latch」）。既然 latch 不适用，claim 对 read 工具的**实际谓词**是什么？计划没有把这句话落到「所以 read 工具的 effect 在 claim 时不被 latch 拦」。这不是错，是**留给实现者的未知**，而 D4/D6 的「恰好一条 ready」断言依赖它。

**修正**：§2.2 补一句「因此 claim 对 read 工具走下文的通用谓词分支（status + attempt_ok + op_seq/mutation_scope），无 worktree latch 参与；D4/D6 的 ready 行可见性以此为据」。若实现期实测发现 latch 分支仍介入（例如全表 FOR UPDATE），记 README。

### F14（必须改）· 更简单设计取代：Oracle 2 的**多 root 歧义分支**被计划 D9 正确砍掉，但计划没有把「Oracle 2 的 `resolve_path(root_or_roots, raw)` 签名」列进「不做」清单

计划 D9 说「Python 独有的多 root / 歧义分支。本 stage 没人调用它」——即拒绝。但计划 §4 的 `read_contract.py` 接口写的是 `resolve_path(root, raw)`（单 root，**优于** Oracle 2 的 `root_or_roots`），这个正确选择在 §8「明确不做」里**没有出现**。Oracle 2 §3.4 的 `resolve_path(root_or_roots, raw_path)` 是**更复杂且任务不需要**的设计（它的存在理由是「lock RepoPrompt’s multi-root ambiguity behavior」，而任务与用户确认都说单 root）。

**修正**：§8 增一条「不移植 `DirectHeadlessDomainContext.swift:311-318` 的多 root 歧义分支（`roots.count == 1` 之外的两分支）；wire 协议只有单个 `root`」。这样实现者不会因为读到 Oracle 2 的签名而把多 root 逻辑带进来。

### F15（建议改）· 任务不需要：Oracle 3 §3.11 的 **D14「gate 的 dispatch 函数不得包含 `FROM tools` 查询（源码扫描）」**被计划丢掉——这条**应该保留**

Oracle 3 的 D14 是「对 gate 文件做源码扫描，断言 dispatch 里没有 `FROM tools`」，理由是「mirrors the M3-12 `advance.sql has no FROM tools` scan」。计划 §8 写了「worker 不查活 `tools` 表来分派」，但**没有任何机械断言**。这与仓库既有实践一致（M3-12 做过同类扫描），且成本极低。

**修正**：D 组增 `D14`：读 `v13/read_tools/test_read_tools.py` 源码，断言 `request["handler"]` 的 dispatch 分支所在的函数体内不含 `FROM tools`。这是**把「不做」变成可验证的 gate**，正合仓库风格。

---

## 4. 导出与计划**都缺**的需求、边界、依赖、架构问题

### F16（必须改）· **失败路径端到端从未被驱动**：三个口岸的 `failed` completion（taxonomy JSON、无 `tool/result`）在环上一行断言都没有

计划 §3.1 定义了失败形状，D 组 13 行断言**全部**只覆盖幸福路径与负例的「预算墙」，**没有任何一行让一个工具在环上失败**（例如把 `path` 指向围栏内不存在的文件）。这意味着：`{"error": code, "message": detail}` 经 `v13_complete(..., 'failed', …)` 落库的形状、`effects.error` 的键、以及「失败不追加 `tool/result`」这三条**从未被验证**。计划 R11 只说「幸福路径在 `finally` 里 complete」。Oracle 2 §3.9 的「No `tool/result` event should exist for failed effects」也是**规定无断言**；Oracle 1/3 同样没有。

这是本计划**最大的覆盖缺口**：失败分类（D7 裁决「读失败 `complete failed`，带分类 JSON。绝不 `unknown`」）是 §1 的核心裁决之一，却零验证。

**修正**：D 组增一个**失败场景**：新 session → 一拍内让 mock 选 `read_file_py` 且 `path` 为 `hello.txt`（环上只能选闭合选项），然后**在 hub 侧**把 `params["path"]` 改成围栏内不存在的名字再调 `read_text` → `ReadError('read_failed')` → `complete failed` → 断言：`effects.status='failed'`、`effects.error->>'code'='read_failed'`、**无** `tool/result` 行、`sessions` 仍 `waiting` 且该 session 的下一拍 advance 返回 `waiting`（失败后 session 继续，不 terminal——**需实测确认**，若 triage 的失败臂会 closeout，按实测改写）。这一条同时回答了「失败之后 agent 会怎样」这个**计划完全没回答**的生命周期问题。

### F17（必须改）· **失败后的 session 生命周期**：计划没说 advance 看到 `failed` effect 会做什么

接 F16。计划 §2.2 描述 `v13_complete` 的返回（`stale`/`replay`/`accepted`），§3.5 的 hub 假设 complete 之后「下一拍 advance 继续」。但对 `kind='tool'` 的 **failed** effect，triage 的 advance 是否会 `closeout`（像 human 的 `failed`/`cancelled` 臂那样，`v13_triage.sql:849-851`）？计划未查、未写。Oracle 1/2/3 都没查。`v13_triage.sql:846-851` 只在**预算**分支里有 `v_est IN ('failed','cancelled')` 的 closeout，那是 human 行的；**tool 行的 failed 走哪条路未知**。

**修正**：并入 F16 的失败场景断言：「记录并断言 tool failed 之后 advance 的返回（`waiting` 或 `terminal`），以实机为准写进 README/台账」。这是**必须实机确认**的，不能猜——它决定失败场景的后续拍怎么排。

### F18（建议改）· **取消（cancellation）的边界在计划里只有一句「不结算 cancelled」，但没回答「cancel/requested 事件存在时 claim/advance 会怎样」**

计划 §2.2 说「`cancelled` 对 `v13_interruptible` 默认档 `unsupported`（`v13_fanout.sql:37-44`，未知工具名走 ELSE）会 RAISE。本 stage 不结算 `cancelled`。」本轮实查确认 `v13_interruptible` = `CASE p_name WHEN 'fanout_required' THEN 'required' WHEN 'fanout_best_effort' THEN 'best_effort' ELSE 'unsupported' END`。**计划没说的是**：`v13_advance` 的前置分支（`v13_triage.sql:836-838` 之上）是否检查 `cancel/requested` 并提前返回。既有代码里 `v13_session_cancelled`（`v13_fanout.sql:30` 附近）读 `cancel/requested` 事件。若 gate 不产生 cancel 事件，理论上不触发——但**计划应显式写「gate 不产生 `cancel/requested`，故该臂不参与」**，否则实现者会在 README 里含糊。

**修正**：§3.5 或 §8 补一句「gate 不追加 `cancel/requested`；claim/advance 的取消臂不在本 stage 覆盖范围，README 台账记一行」。

### F19（澄清）· **可测试性**：`v13_advance` 有 5 个定义、`v13_needed_judgments` 有 4 个——计划没有任何「断言生效版本」的机制

F7 已列函数清单。更进一步：**gate 应在库里断言「生效的 `v13_complete` 是 seam 那份」**。可行的机械断言：`SELECT prosrc FROM pg_proc WHERE proname='v13_complete'` 含 seam 独有的字符串（例如 `v13_cap_answer_anchor` 或 seam 的某个常量）。Oracle 1 §3.2 P1 说「re-read the replacement before coding the hub」，但没给断言。pa-agent 的既有 gate 用过 `pg_get_functiondef` 抽计划（见 memory 里 v13-stannum-usage-audit），所以这是**仓库既有能力**。

**修正**：§3.6 或 D 组增一行：`setup_db` 后断言 `pg_get_functiondef('v13_complete'::regproc)` 含 seam 特有标记（并断言 `v13_advance` 的定义体是 triage 那份）。这把 F7 的「引用正确」变成**库内可验证**。

### F20（澄清）· **归属与生命周期**：`THIRD_PARTY_NOTICES.md` 在仓库根**不存在**，计划说「新，仓库根」正确；但 `.gitattributes` 也**不存在**，计划说「追加 `v13/read_tools/fixtures/crlf.txt -text`」是**追加到不存在的文件**

本轮实查：`/Users/wxl/Projects/pg-agent/.gitattributes` **不存在**（`ls` 报 No such file；`find -maxdepth 2` 无命中）。计划 §4 文件表写「`.gitattributes` — 追加 `v13/read_tools/fixtures/crlf.txt -text`」，M1「这是 M1 唯一改到的既有文件」——**错误**：它**会创建一个新文件**，仓库根没有既有 `.gitattributes`。Oracle 3 §4 已经正确写了「If the file does not exist, create it with that single line」（并把「modified」列成「**plus one conditional**」）。

**修正**：§4 与 §5 的「唯一改到的既有文件」改为「**新建**根 `.gitattributes`（仓库当前无此文件）」；M1 的提交信息与 README 台账同步。另：`git check-attr -a v13/read_tools/fixtures/crlf.txt` 应在 M1 落盘后跑一次并记 README（Oracle 3 Step 5 有这条，计划没有）。

---

## 5. 会实质改变设计或实施顺序的问题

按「答案改变计划文本」的可变性排序：

1. **tool 行失败后 `v13_advance` 返回什么（`waiting` / `terminal` / `closeout`）？**（F16/F17）——决定失败场景的后续拍数、D 组断言行数，以及 README 的「失败后 session 去哪」一节。**只能实机测**。
2. **seam 前缀里 `v13_needed_judgments` 的生效版本是 triage:1005——它的信号形状与 `v13_resolve.sql:55` 是否**完全一致**？**（F7）——若 triage 版多/少信号，needed 基线（15）与 `remaining==0` 都要重算。
3. **finish 臂在 triage 的 `v13_advance` 上是否存在且 `delivered=true`？**（F5）——决定 D6 第五条 route 与 `turn/end` 断言能否成立。
4. **`read_pi.mjs` 的 `limit:null` 行为**（F10）——决定 hub 是否必须省略键，以及 C 组行数。
5. **`options` 是否保留 `crlf.txt`**（F6）——决定 needed 基线是 +6 还是 +3，D3 断言随动。
6. **失败场景要不要进 M2 的默认 gate**（F16）——若进，M2 的 D 组从 13 行变 16 行左右，实施顺序 8 步不变但工作量增。

---

## 6. 计划相对三份导出**更正确**的地方（保留，勿改）

为避免「只挑刺」的偏差，以下计划裁决**优于**导出，应原样保留：

- **`max_cycles ≥ 5`**（§2.3）——三个导出都对，计划最干净；`v13_triage.sql:839-847` 的 `v_cycles >= v_max` 在 append 前求值，第 N 条 route 在 `cycle_no=N-1` 时发出，5 条 route 需 `max_cycles≥5`。DP10 的 4 是两工具的数。
- **`offset_out_of_range` 是 `""` 之外的独立码**（§2.4/§3.1）——Oracle 1 与 Oracle 3 都把它当错误，计划明确「不是 `""`，也不是协议错误」。
- **`image_unsupported` 只在 Pi 平面**（§3.1）——Oracle 1 §3.3 与计划一致；计划进一步写「合法 UTF-8 的 `.png` 在 headless 平面是文本读成功或 `read_failed`」，这是正确的有意分歧。
- **`v13_complete` 用 seam 那份**（§2.2）——三个导出里只有 Oracle 1 完全说对（它把 fanout:305-465 与 seam:419 的关系点明），计划沿用了它。
- **Pi 的 `offset=0`/负 offset 从第 0 行起**（§2.4）——与 `read.ts:271` 的 `offset ? … : 0` 真值语义一致；比 Oracle 2 的「0/负数 → invalid_params」更准确（见 F3）。
- **`head -c` 后是原始 `51200`，不是 `50.0KB`**（§2.4）——`read.ts:293` 与 `truncate.ts:61-65` 的 `formatSize` 分工正确。
- **`.gitattributes` 与 `THIRD_PARTY_NOTICES.md` 进 M1**（§5 R12）——Oracle 1/3 都对，计划保留。

---

## 7. 修改清单（按路径）

- `docs/plans/v13-native-read-tools-2026-09-27.md`
  - §2.1：基线工具 6→**7** 行，补 `v13/spawn/v13_spawn.sql:1757`（`spawn_subsession`，`kind='sql'`）。
  - §3.2：增 **P3（finish 臂）**、**P8（上游版本）**、**P9（生效函数清单）** 三条 preflight，并入第 2 节的实查结论表。
  - §3.1/§3.3：补线协议「未知键忽略」「`root`/`path` 非字符串 → `invalid_params`」；补 Pi `limit:null` 必须省略或归一化。
  - §3.5：补 `json.dumps` 绑定式、`snap` 每拍取新、每拍 IO 的 `finally` complete 兜底。
  - §3.4/§4/§5：`.gitattributes` 与 `THIRD_PARTY_NOTICES.md` 均改为「**新建**」；补 `git check-attr` 一步。
  - §8：增「不移植多 root 歧义分支」。
  - D 组：D3 三条断言化；增 **D14（无 `FROM tools` 扫描）**、**失败场景**（F16）、**C3c**（先切片后字节截断）、**`limit:null` 全文**、**`pg_get_functiondef` 生效版本断言**。
  - 增一节「失败后的 session 生命周期」，以实机结果为准填写。

上游文件核对（本轮已查，结论可直接采用）：`pi/packages/coding-agent/package.json` = 0.80.3；`pi/LICENSE` = MIT © 2025 Mario Zechner；`pi/.../read.ts:271,274-276,280-288,290-310`；`truncate.ts:11-12,61-65`；`repoprompt-ce/.../MCPDomainCanonicalWorkspaceService.swift:171-193`；`DirectHeadlessDomainContext.swift:302-333`（NUL→`pathOutsideWorkspace`，空白→`invalidParams`，单 root 相对=拼接无存在性检查，`standardizedFileURL` 再 `resolvingSymlinksInPath` 含叶子，前缀围栏）。以上全部与计划 §2.4 一致。
