# DP10 计划批判（v13-dp10-multilang-tools-plan-2026-09-23）

> 日期：2026-09-23。评审对象：`docs/plans/v13-dp10-multilang-tools-plan-2026-09-23.md`（草稿 v1）。
> 证据基线：`docs/investigations/v13-multilang-tool-call-test-2026-09-23.md`（F1–F22 + N1–N10 + 实机矩阵，其已验证事实当作基线）+ 实际代码库 spot-check。
> 范围：仅限任务指定的 5 类问题。**不改写计划、不扩范围、不重开四项用户终裁**（自有 Swift 脚本无 oracle / 行 JSON 线协议 / M1+M2 两笔 / 默认 gate 含 Swift exit 2）——四项均确认可实施，见 C 节末注。
> 载重 spot-check 全部实跑：v13 SQL 六个锚点、`test_loop.py` 五个助手、RP-CE 两处 readFile/resolvePath、`v12/queue`、`v8/compat`、14 个 stage gate 全量复跑、Swift 脚本模式实机（含 trap/timeout/缓冲行为）。

## 结论摘要

计划整体与调查报告高度一致，契约层面（U1–U15）引用经抽查**全部属实**。但发现 **7 项 P0**，其中两项是硬伤：

1. **§3 的 tools INSERT 用了 `"options": ["hello.txt"]`（数组）**，违反 `decisions.criteria` 的 object CHECK（`v13/schema/v13_core.sql:418-419`），照抄执行会在 parse 阶段炸 decisions INSERT——gate 跑不起来。
2. **"14 个既有 stage gate 复跑全绿" 当前为假**：实测 12/14 绿，`v13/envelope` 与 `v13/twophase` **双双红**，且根因是一个 gitignored 的本地 demo 文件。按 AGENTS.md「gate 红就是红，先修再提交」，M2 里程碑提交被阻断，而修复越出本 plan 的零 SQL 边界。

另有一项结构性遗漏（P0-A6）：新工具的 `stated::`/`param::` 信号在 `thresholds` 里**没有带行**，而参数入 request 恰恰以带命中为前提；且 frozen 策略下无法直接 INSERT 追带。计划 §3 自称"运行时执行的 SQL 全集"，漏掉了这块。

**严重度分布：P0 ×7，P1 ×12，P2 ×17。**

---

## A. Preservation check（调查报告的载重内容被计划省略/削弱/过度泛化）

### P0-A1 · A9/B3 的 CRLF 期望值错，少了一个幻影尾元素

计划 `docs/plans/v13-dp10-multilang-tools-plan-2026-09-23.md:143`（A9）与 `:157`（B3）断言 fixture `alpha\r\nbeta\r\n` 全文读得 `alpha\n\nbeta\n`。

调查报告 N1 实机表与 E5（`docs/investigations/v13-multilang-tool-call-test-2026-09-23.md` N1 行 "crlf.txt 全文 | `a\n\nb\n\n`"、E5 "CRLF 结尾的文件尾产生两个幻影空元素（N1 实机：`a\r\nb\r\n` → `a\n\nb\n\n`）"）给出的是 **`alpha\n\nbeta\n\n`**。

机制核对无误：`MCPDomainCanonicalWorkspaceService.swift:179` 用 `components(separatedBy: .newlines)` 逐字符切，`alpha\r\nbeta\r\n` → `["alpha","","beta","",""]`（5 元素），`:192` join `"\n"` → `alpha\n\nbeta\n\n`。Python 侧 `re.split(r"[\n\r\v\f\x85\u2028\u2029]", ...)` 同构。

连带问题：A4（`:138`）说"带尾换行文件切出 N+1 段"只对 LF 成立，CRLF 尾是 N+2——计划把 LF 结论过度泛化了。

**后果**：照计划写实现，要么口岸必须写错才能匹配断言，要么断言红。修期望值即可，不涉及设计。

### P0-A2 · §3 的 param_spec `options` 用数组，违反 object CHECK，gate 死于 parse 阶段

计划 `:111` 与 `:113`：

```sql
'{"path": {"question": "which file", "stated": "user named the file", "options": ["hello.txt"]}}'
```

`v13/resolve/v13_resolve.sql:110-114` 对 `param::` choice 信号设 `criteria := r_param.spec->'options'`；而 `v13/schema/v13_core.sql:418-419` 的 `v13_decisions_choice_shape` 要求 `jsonb_typeof(criteria)='object' AND criteria <> '{}'`。数组 → CHECK 违约 → decisions INSERT 失败 → `v13_parse` 失败 → 整条 gate 红。

种子先例是对象（`v13/schema/v13_core.sql:940-952`，`"options": {"formal": "...", "friendly": "..."}`）；`v13_resolve_tool_params`（`v13/loop/advance.sql:169-182`）取的是 `->>'choice'` 即**选项键**，所以键必须等于相对路径。

加重情节：`v13_tools_guard`（`v13_core.sql:620-656`）只校验 name/param key 的 `::` 与 sql handler 签名，**不校验 options 形状**——坏的 tools INSERT 会成功，直到 decisions 落行时才炸，属延迟型难排查故障。

调查报告 Recommendations §2 明确写过"单选项**键=相对路径** `hello.txt`"，计划丢了这个语义。正确形状：

```json
{"path": {"question": "...", "stated": "...", "options": {"hello.txt": "the fixture file"}}}
```

### P0-A3 · C5 的前置条件与 C2 的执行顺序自相矛盾

计划 `:174`（C5）要求 A0 "**种子预算不翻新**"（max_cycles=3），但 `:172`（C2）在此之前就"执行两行翻新 → `v13_policy('turn_budget')`=4"。

`turn_budget` 是**库级 active 行**，不是 session 作用域（`v13_core.sql:701-709`；`v13_policy` 读 active 行 `:731-740`），所以"独立短 session"拿不回 max_cycles=3。照表的顺序跑，A0 的第 4 次 advance 会正常走 P0 finish，`budget_exhausted` 断言红。

调查报告 Recommendations §3 步骤 4 显式标注了这个顺序约束（"**种子策略未翻新前**或独立短 session"），计划丢掉了。可选解：(a) A0 提到翻新之前；(b) A0 前把 `active` 翻回 v1（这是唯一被许可的 UPDATE，`v13_core.sql:715-729`），事后再翻回 v2。二选一，计划必须写明。

### P0-A4 · C5 的断言集对不上第 4 次 advance 的真实语义

计划 `:174` 断言"三路由后第 4 次 advance → `turn/end delivered=false` + `status='failed'`"。

`v13/loop/advance.sql:333-355`：`v_cycles >= v_max` 时 enqueue 一个 `human` effect；若该行是**新 ready**，则走 `:352-355` 的 `PERFORM v13_send_work` + `status='waiting'` + `RETURN 'waiting'`。`turn/end delivered=false` + `sessions.status='failed'` 只在 human effect **已 succeeded** 时触发（`:338-343`）。

即正确序列是：advance#4 → `waiting` + human effect ready → hub 结算 human succeeded → 再一次 parse+advance#5 → `terminal` + `turn/end delivered=false`。仓库先例 `v13/loop/test_loop.py:428-437`（M3-7）也只断言到 "budget waiting" + human 的 reason，不断言终态。调查报告 F6 写对了（"需 hub 按 `_do_human` 结算 succeeded 后再一次 parse+advance 才落 turn/end failed"），计划丢了这段。

### P0-A5 · 回归前置为假：14 个既有 gate 里 2 个当前是红的（且根因越界）

计划 `:16`、`:124`、`:197`、`:252` 都要求"提交前 14 个既有 stage gate 复跑全绿"。

**今日实跑**（仓库根，`uv run python v13/<stage>/test_<stage>.py`）：

- exit 0（12 个）：schema、resolve、loop、manifest、chunks、recall、characterize、filter、memory、economy、summary、periphery
- exit 1（2 个）：**envelope**、**twophase**

两处失败同一根因，都是源码扫描断言：

- `v13/envelope/test_envelope.py:2133-2135`：`for p in V13.rglob("*.sql")`（`V13 = AGENT_ROOT/"v13"`，`:20`）断言无 `mock_response`
- `v13/twophase/test_twophase.py:143-147`：同款扫描，且更严（同时拒 `set_config`）

触雷文件是 `v13/demo/sql/demo_api.sql:122,135`（`PERFORM set_config('typesafe.mock_response', ...)`）。而 `v13/demo/` **整体 gitignored**（`.gitignore:32`；`git ls-files v13/demo` → 0 个文件）。

后果两层：

1. **机器相关性**：fresh clone 上没有 demo 树，这两个 gate 绿；任何做过本地 demo 开发的机器上红。这本身就是两个 gate 的既有缺陷（对 gitignored 目录做断言）。
2. **里程碑阻断**：按 AGENTS.md「gate 红就是红，先修再提交。MUST NOT 在没有实跑的情况下声称 gate 通过」，M2 无法提交。而修复要么改 `v13/demo/sql/demo_api.sql`（gitignored，不解决他机），要么改另外两个 stage 的 gate（越出本 plan §1.1「不动 DP1–DP8 任何 gate」与不变量2 的边界）。

计划必须三选一并在 README 偏差台账留痕：(a) 把 E4 收窄为"12 个绿 gate + 2 个既有红的显式豁免"；(b) 一并修那两个扫描（需用户裁定扩边界）；(c) 先由 demo 线的人修。目前计划三者都没做。

### P1-A6 · 新工具的 `stated::`/`param::` 阈值带行缺失，且 frozen 下无法直接补——参数根本进不了 request

计划 `:106` 自称列出"运行时执行的 SQL 全集"，只有 tools INSERT/DELETE、策略 UPDATE/INSERT、GUC。

但 `v13/loop/advance.sql:177` 把参数入 request 的条件定为 `v13_env_hit(p_env, 'stated::'||p_tool||'::'||key, 'pass')`；`v13_env_hit`（`advance.sql:59-66`）经 `v_routes`（`v13/schema/v13_core.sql:564-577`）解析，而该视图对 `thresholds` 是 **INNER JOIN**（`:569-575` LATERAL）。信号没有带行 → 无 `v_routes` 行 → 不命中 → `v_params := '{}'`（`advance.sql:171,182`）→ 口岸收不到 `path` → `invalid_params` → tool effect failed → C6/C7/D1 全红。

种子只给**种子邮件工具**的 4 个信号建了带（`v13_core.sql:972-975`）。tracked 面从没有"新 INSERT 的工具带参数路由"的先例：`v13/loop/test_loop.py:382-397`（M3-11）只跑种子工具 `send_summary_email`，且 M3-5（`:419-427`）只断言 request 含 handler+revision，**从不断言 params**。demo W6（`v13/demo/test_demo_loop.py:334-350`）插 20 工具 ×2 参数但全程不碰 thresholds（`grep thresholds v13/demo/*.py` 零命中），且 W6 只验 judge 慢路、不验参数。

更麻烦的是带行不能直接 INSERT：`v13_thresholds_insert_guard`（`v13_core.sql:526-542`）拒绝任何 parent 非 `draft` 的插入，而 `('default',1)` 已 frozen（`:982-983`）。唯一路径是：新建 draft `v13_route_policies` 版本 → **复制全部种子带**（`v_routes` 按 session 的版本 join，只补 4 行不够）→ 加 4 行新带 → freeze（`:472-473` 是唯一许可转移）→ 让新 session 指向它（`sessions.route_policy_version` 默认 1，`v13_core.sql:22`；`v13_sessions_policy_guard` 要求 frozen，`:547-556`）。且 `route_policy_version` 是七键探针之一（`advance.sql:24-25, 243-253`），必须在任何 parse 之前设好。

**另一条更简单的路**：把 `path` 从 param_spec 拿掉（信号数 13→11），口岸对缺省 path 读固定 fixture。机器少得多，但静默丢掉了计划在 C4 advertise 的"判断面选文件"这一层。两条路都改变实施顺序（策略/带工作必须早于任何 parse），计划必须选一条并写清。

### P1-A7 · C4/R3 缺判断相位答案的具体值——路由真正依赖的那些阈值

计划 `:173` 只说"写满 13 问"。对照种子带（`v13_core.sql:963-981`）与 M3-11 配方（`test_loop.py:382-397`），载重值是：

| 信号 | 需要的值 | 依据 |
|---|---|---|
| `intent` | choice `tool_action`，confidence ≥0.75 | pass 带 `v13_core.sql:969` |
| `gate_action` | noul ≥0.75 | pass 带 `:970`；**`mock_from_needed` 的 noul 默认是 0.1**（`test_loop.py:126`），会 FAIL |
| `gate_off_topic` | noul <0.75 | reject 带 `:966`；0.1 正确 |
| `risk` | score <2.25 | reject 带 `:967`；M3-11 用 0.5 |
| `tool` | choice，confidence ≥0.75 | pass 带 `:971` |
| `stated::read_file_*::path` | noul ≥0.60 | `:972-975` 同款；**且需带行**（见 A6） |
| `param::read_file_*::path` | choice = 选项**键** | `advance.sql:178-180` |

调查报告 Recommendations §2 逐条列过（"intent/gate_action/tool confidence 0.9、`gate_off_topic` noul 0.1、`risk` score 0、两个新工具 `stated::…::path` 0.9"），计划整段丢了。缺了它，实施者会在 `low_intent_confidence` / 参数被省略上白烧一轮调试。

### P1-A8 · 计划自造 mock 生成器，丢掉仓库现成的 `mock_from_needed`

计划 `:209`（R3）要求"mock 生成器函数化（输入=相位计数，输出=整批答案 JSON）"。

`v13/loop/test_loop.py:111-130` 已有 `mock_from_needed(cur, sid, **over)`：读 `v13_needed_judgments` 当批信号、逐信号生成合法答案、支持按信号覆盖。相位脚本因此只是 `parse(cur, sid, intent=…, tool=…, **{...})`，且 13 这个数是**推导出来的**而非硬编码——未来工具加参数会自动进 mock（硬编码 13 会悄悄漏信号 → V3001 整批拒）。调查报告 N7 明确点出这一点（"不需要…自造 mock 生成器…比 demo 的 answer_mock 包装更直接"），计划既没引 `mock_from_needed` 也没引 `claim_pinned`。

### P1-A9 · 没有确定性认领策略；`v13_claim` 是全局 oldest-first，无 session/handler 过滤

`v13/schema/v13_core.sql:267-296`：`v13_claim` 跨**所有 session** 取最早一条 ready，`FOR UPDATE SKIP LOCKED LIMIT 1`，无 `handlers[]` 过滤（教程 §8.2 的承诺未实现，调查报告 B2/Q3 已确认）。

计划不变量5（`:82`）让 A0 与幸福路径各自 fresh session，但两者若并存，未排空的 A0 effect 会被幸福路径的 hub 跨 session 认领。仓库先例是 `claim_pinned`（`v13/loop/test_loop.py:78-87`：先把其他 ready 行 cancel 掉再领目标）。计划两者都没提，也没说 session 必须严格顺序且完全排空。

### P1-A10 · `nonutf8.bin` fixture 与不变量8「不提交任何二进制」冲突

计划 `:131`（M1 清单含 `fixtures/nonutf8.bin`，`FF FE 78`）vs `:89`（不变量8 "不提交任何二进制"）。解法：gate 内生成这 3 字节，或把不变量8 收窄为"不提交构建产物/工具链二进制"。

### P1-A11 · A14 的 symlink root 围栏断言没有 fixture，是空转断言

计划 `:148` 提到"symlink root fixture 下 /var→/private/var 类不误判"，但 M1 清单（`:131`）只有 `hello.txt`/`crlf.txt`/`empty.txt`/`nonutf8.bin`。若 gate 传仓库内 fixture 的真实绝对路径，`realpath` 是恒等变换，断言证不了任何事。需要一个 symlink fixture（如 `fixtures/link -> .`），或显式用 `/tmp` 类根（macOS 上 `/tmp` 本就是 symlink）。

### P1-A12 · Swift exit code 契约有信号死亡空洞；`print()` 缓冲会丢成功帧

计划 `:159`（B5）只规定 0/3/1。本机实机（Apple Swift 6.3.2）验证：

- Swift 运行时 trap（如数组越界、对不可信输入 force-unwrap）退出码是 **-5 / 133（SIGTRAP）**，不是 1；
- 脚本先 `print()` 成功帧、随后 trap，**stdout 为空**——帧被 stdio 缓冲吞掉（实测 `exit=-5, stdout=b''`）。

所以计划必须要求：(a) Swift 脚本整体 `do/catch` 包裹、用 `FileHandle.standardOutput.write`（无缓冲）或显式 flush；(b) 桥把"任何不在 {0,3} 的退出码"映射为协议错误；(c) 读不到帧（EOF）是协议错误而非挂住；(d) B 组补一个 trap 用例。

顺带验证通过的一项：`subprocess.run(capture_output=True, timeout=…)` **会干净回收整个 `swift` → `swift-frontend` 进程树**（1.5s 超时后 `ps` 零残留），R5 的超时处理照写即安全。

### P2-A13 · 裁决1 的冷启动数字与实测差 ~6×

计划 `:51`、`:160`、`:263` 写"冷 2.158s/热 0.18s"。本机实测：冷（新文件）≈0.34s，热 ≈0.19s。B6 的 10s 护栏两种数字下都绰绰有余，但引用值应重测或标注机器相关。

### P2-A14 · A13 的多 root 分支没有 Swift 对应物，构成未声明的契约不对称

计划 `:146` 把多 root 歧义当作"口岸单测"（Python only），而裁决2 的线协议只有单个 `"root"`。即 Swift 脚本是单 root 子集。作为设计可以（调查报告 F15 也这么建议），但计划应把它写成显式的契约差异，而不是让两个实现的 API 面静默不对等。

### P2-A15 · 附录B 把 README 偏差台账引成 E4，实为 E3

计划 `:252` vs `:196`。

### P2-A16 · §7 第 10 条把 conformance-matrix 问题当成已定，DP2 其实显式挂起了它

计划 `:236`（§7.10）称"v8 专属机制…家法如此"。`docs/plans/v13-dp2-judgment-envelope-plan-2026-09-20.md:1632,1714` 原文是 "v13 的 conformance-matrix/deviation-ledger 评审工件 DP1 未建制…是否为 v13 建制评审工件属父 loop 统一决策,不在本 DP 单方引入"。实际也只有 v8 有这两个工件（`docs/reviews/v8-p0ab-conformance-matrix-2026-09-16.md`、`v8-p0ab-deviation-ledger-2026-09-16.md`）。计划应说明是沿用 DP1/DP2 的挂起，并指出 AGENTS.md 仍把两者列为里程碑前置——这个张力被计划一句话抹掉了。

### P2-A17 · 裁决2 没区分"空 stdin 帧"

按计划自己的分类法，空/空白 stdin 帧是"坏 JSON"→ exit 1，但实施者完全可能映射成 `invalid_params`/exit 3。两端必须一致，计划应写明。

### P2-A18 · README 内容清单缺 app/headless 分歧与 `offset` 注记

计划 `:196` 未包含调查报告 N5 要求记录的"不要用 offset"与"契约锚定 headless 裸字符串而非 `ReadFileReply`"。Swift 侧改为自研口岸后优先级下降，但"刻意没有移植什么"的清单仍有留存价值。

---

## B. Seams & correctness（欠定接缝、矛盾、file:line 失准、缺失依赖、gate 数假设）

### P0-B1 ·「15 号槽留空」为假；`v13/load.py` 已经是脏的

计划 `:81`（不变量2）称 "`v13/load.py` `SQL_LOAD_ORDER` 零追加（15 号槽留空）"。

工作区实测：`git status` 显示 `M v13/load.py`，diff 为 `STAGE_THROUGH` 增加 `"mgraph": 15`（现 `v13/load.py:49`）。`SQL_LOAD_ORDER` 仍只有 14 项（`:17-32`），于是 `files_through("mgraph")` 只返回 14 个文件，而 `v13/mgraph/setup_db.py` 的 docstring 写 "load through mgraph (15 files)" 且调用 `load_stage(s, DB, "mgraph")`——DP9 未提交工作在途的自相矛盾。

另：DP9 的**计划**已提交（`af8e23d v13: add dp9 mgraph development plan`），所以"DP9 计划态未实现"只对实现成立；`v13/mgraph/`（未跟踪，含 38KB SQL + setup_db.py）与 load.py 的改动就在旁边，"无交集"不成立。

### P0-B2 · E2 的「git status 零改动」自查会假红，并诱导破坏性"修复"

计划 `:195`。`v13/load.py` 在 DP10 动手前就已被修改（见 B1），E2 按字面执行必然失败。更危险的是最自然的"修复"——`git checkout v13/load.py`——会静默回滚 DP9 在途的 `mgraph: 15`。

E2 必须改写为"本 stage 无可归因改动"（例如对 `v13/load.py` 做前后 diff，或断言唯一 diff 是既有的 `mgraph` 行），并显式禁止 revert。

### P1-B3 ·「14 个 gate」数目对，但 E4 的枚举漏了 `schema`

计划 `:197` 列了 13 个 stage 名（loop/resolve/twophase/envelope/manifest/chunks/recall/characterize/filter/memory/economy/summary/periphery）。实际带 gate 的 tracked stage 目录是 **14** 个，差 `v13/schema/test_schema.py`。14 个 stage README 均已记录各自 gate 命令（逐一核实）。`v13/mgraph/` 有 setup_db.py 无 test，不算 gate，排除正确。

### P1-B4 · pgmq 全程未提；hub 的认领/轮询模型没写

`v13_send_work`（`v13/loop/advance.sql:487-491`、`:510`、`:516`）往 `pgmq.q_v13_work` 发消息，但 `v13_claim` 读的是 `effects` **表**（`v13_core.sql:267-296`）。计划应写明 mini-hub 轮询 `v13_claim`、忽略 pgmq，且只因为它以超级用户连接跑才免授权（调查报告 F19；计划只在 C1 隐晦提到"超级用户连接"）。否则实施者可能平白造一个 pgmq consumer。

### P2-B5 · file:line 漂移清单（载重论断全部核实为真，仅跨度微偏）

| 计划引用 | 实际 | 判定 |
|---|---|---|
| `test_loop.py:20-25`（`check()` 风格，`:124`） | `def check` 在 **:25** | 偏 5 行 |
| `v13/loop/setup_db.py:18-27`（`:46,:178`） | `get_server()` 在 **:17**；DROP/CREATE/load_stage/run_probes 本体 **:16-23** | 偏 1–4 行 |
| `demo/test_demo_loop.py:381-391`（W6 恢复，`:194`） | DELETE + `tools_left == 2` + revision bump 在 **:377-383** | 偏 4 行 |
| `v8/compat/test_compat.py:1131-1170`（`:48`） | `test_real_provider_smoke` 起于 **:1133**；not_run 分支 **:1137-1142** / **:1146-1153** | 偏 2 行 |
| `v13_core.sql:623-698`（U1 guard+revision，`:32`） | `v13_tools_guard` 在 **:620** | 偏 3 行 |

**核实无误的载重引用**：`v13_core.sql:753`（种子 max_cycles=3）、`:161-166`（`v13_cycle_no`）、`:701-729`（policies + frozen trigger）、`:964-981`（阈值带）、`:418-423`（decisions ASCII/shape）、`:564-577`（`v_routes`）、`:267-296`/`:300+`（claim/complete）；`advance.sql:330-337`（预算步⑤）、`:387`（turn/route）、`:503-508`（request 冻结）、`:169-182`（`v13_resolve_tool_params`）、`:59-66`（`v13_env_hit`）；`v13_resolve.sql:97-119`（tool/param/stated）；`test_loop.py:67-68`、`:155`、`:111-130`、`:78-87`；`MCPDomainCanonicalWorkspaceService.swift:171-193`（readFile 每个子锚点精确：UTF-8 `:178`、`.newlines` `:179`、负尾 `:183-184`、1-based `:186`、越界 `:187`、join `:192`）；`DirectHeadlessDomainContext.swift:302-333`（resolvePath 每个子锚点精确：空白拒 `:306`、绝对直用 `:310`、歧义 `:319`、standardize+symlink `:323-326`、前缀围栏 `:328`）；`v12/queue/test_queue.py:145-151`（uuid5 恒等断言在 `:150-151`）；`v13/demo/setup_db.py:11-12`（零 SQL 声明）；`.gitignore:32`。

### P2-B6 · U8 把 `test_loop.py:64-68` 当作 provider/model GUC 先例，但该文件从不设 `typesafe.provider`

`test_loop.py` 只有 `:155` 的 `SET typesafe.model`（会话级）与 `:68` 的 `mock_response`（事务级）。它能跑通是因为 loop stage 只载 3 个文件，没装 envelope 的 `v13_guc_required`（`v13/envelope/v13_envelope.sql:321-331`，V3002）。DP10 载到 envelope，**两个 GUC 都要**；真正的先例是计划也引了的 `test_envelope.py:128-131`（`guc()`）。

值得点名：`guc()` 用的是 `set_config(..., true)`（**事务级**），而计划 R6 规定的是 `set_config(..., false)`（会话级）。计划的规定更安全、也与调查报告 F10 一致，但所引先例的机制与之相反——在一 RPC 一提交的 hub 上，事务级 provider 会在首次 commit 后静默消失 → V3002。这一点应显式写出，别让实施者照抄 `guc()`。

---

## C. Simplification / disproof（代码推翻的计划细节；同等验证覆盖的更简设计）

### P1-C1 · `mock_from_needed` + `claim_pinned` 一对替换计划的自造生成器，同时消掉跨认领风险

见 A8/A9。同样的验证覆盖、行数更少，且额外拿到"信号集由 `v13_needed_judgments` 推导"的鲁棒性：未来工具加参数，mock 自动跟上；硬编码"13 问"则会漏信号 → V3001 整批拒。

### P2-C2 · B6 的 10s 冷启护栏近乎空转

实测 0.19–0.34s。2s 仍安全，且真能抓到时序回归（例如误触发 SPM 解析）。

### P2-C3 · D6 的 `judgment_calls ≥ 4` 偏弱

恰好 4 次 parse 时可断言 `== 4`，同等成本、更强约束。

### 关于四项用户终裁的可实施性（未重开，仅记录）

四项均确认可按字述实施，其中两项有代码级后果的已实测：

- **每调用 spawn**：可行。热 0.19s ≪ `LEASE_MS=180000`（`v13/demo/settings.py:25`）；`swift file.swift` 脚本模式**不在 CWD 留任何产物**（实测 `ls` 干净），裁决1 的"无 SPM/无 .build 残留"为真；`subprocess.run(timeout=30)` 干净回收进程树（见 A12）。
- **行 JSON 线协议**：文件正文含换行的情况由 JSON 字符串转义保证帧仍为一行，R5 的"stdout 只读一行"是正确纪律——只差把不变体显式写出来（见 A12）与空帧语义（见 A17）。

未发现"照写即不可能"的情形。

---

## D. Absent requirements（计划与调查报告都缺的边角、失败行为、可测性、归属）

### P1-D1 · mini-hub 没有 tick/迭代上限

调查报告 F22(ii) 要求镜像 `MAX_TICKS=16`（`v13/demo/settings.py:27`），其流程步骤 6 写 "tick 上限 8–16"。计划全文无上限——路由一出 bug，gate 从"红断言"退化成"永久挂住"。应加硬上限并响亮失败。

### P1-D2 · 没有 PG 连接中断的失败行为

计划未说 `psycopg2.OperationalError` 中途发生怎么办（PG 重启、pgembed 拆库）。至少应给出清晰失败而非 traceback。`setup_db.py` 对上次中断残留的 `agent_v13_multilang` 的容忍度由照抄的 `DROP DATABASE ... WITH (FORCE)`（`v13/loop/setup_db.py:18`）保证 ✓，但计划没点明。

### P2-D3 · 未声明 hub 单线程 / 并发 spawn 行为

不变量3 隐含了，但没写死。既然每调用 spawn + `subprocess.run(timeout=30)`，并发本无必要；写明"hub 严格顺序、一次一个 effect"即可闭环，也与 `claim_pinned` 的单 worker 假设一致。

### P2-D4 · THIRD_PARTY_NOTICES / Apache-2.0 合规深度

仓库根无 `LICENSE`、也无现成 `THIRD_PARTY_NOTICES.md`。Apache-2.0 §4(a)-(b) 要求向接收者提供许可证文本并声明已修改。计划（`:89`、R8、§1.4）只写"归属 repoprompt-ce Apache-2.0"。应指明：覆盖哪些文件、上游项目/版本/URL、显式的"ported/modified"声明、以及许可证全文或指向。放置位置（根 vs `v13/multilang/`）可以放根，但要说清为什么。

### P2-D5 · fixture 的放置/授权/提交方式未定

fixture 是提交还是 gate 内生成？`nonutf8.bin` 与不变量8 的冲突见 A10。若提交，`crlf.txt` 必须保住 CRLF 字节（他机 autocrlf 可能归一化）——值得显式加 `.gitattributes` 或在 README 记一笔。

### P2-D6 · C1 的 GUC 负例措辞可能掩盖 GUC 未设

计划 `:171` 写"（缺则 V3002 复现一条负例断言）"。若读成"gate 容忍 GUC 缺失、靠断言报错了事"，坏掉的前置也可能"通过"。应拆成两条无歧义断言：(i) 正例——GUC 就位时主路径跑通；(ii) 负例——把 `typesafe.provider` 置空复现 V3002（`test_envelope.py:686-688` 形态）。

### P2-D7 · E1 的"种子值"口径不明

计划 `:194`。应对着 INSERT 前捕获的计数断言（demo 先例断言字面量 `2`，`v13/demo/test_demo_loop.py:381`），而不是一个未绑定的"种子值"。

### P2-D8 · 未记录：未来加 SQL 的语言移植会踩另外两个 stage 的源码扫描

`v13/twophase/test_twophase.py:143-147` 拒任何 `v13/**/*.sql` 里的 `mock_response` **和** `set_config`；`v13/envelope/test_envelope.py:2133-2135` 拒 `mock_response`。DP10 零 SQL 所以今天安全，但 ch08 练习 3 的后继者（"加第三种语言"）会撞上。README 记一句。

### P2-D9 · `advance` 的锁/语句超时被丢掉

调查报告 Recommendations §3 步骤 6 规定 `SET LOCAL lock_timeout='250ms', statement_timeout='5s'`。廉价的挂死保险，计划未收。

---

## E. Material questions（答案会改变设计或实施顺序）

1. **A6（P0）**：gate 会新建 draft→frozen 路由策略版本、带上 4 行新 `stated::`/`param::` 带外加全量种子带复制，还是把 `path` 从 param_spec 移除？前者保住"判断面选文件"与 13 信号数，后者机器少得多但静默削弱示例。**直接决定实施顺序**——策略/带工作必须早于任何 parse。
2. **A3（P0）**：A0 提到 `turn_budget` 翻新之前，还是翻回 v1 跑完再翻回 v2？决定 gate 内部编排。
3. **A5/B2（P0）**：两个红 gate（envelope E5、twophase G-ctx1-5(b)）谁修？它们既有、由 gitignored 本地文件引起、且越出本 plan 零 SQL 边界。若答案是"DP10 不许碰"，E4 必须收窄为 12 绿 + README 显式豁免，否则 AGENTS.md 下 M2 无法提交。
4. **A12（P1）**：Swift 脚本用 `FileHandle.standardOutput.write`（无缓冲）还是 `print()`？这决定成功帧能否在后续 trap 后存活，从而决定 B5 还能不能断言 "ok:true→0"。
5. **A9/A11（P1）**：CRLF 与 symlink root fixture 是提交（配 `.gitattributes`）还是 gate 内生成？影响 M1 清单与不变量8。
6. **B6（P2）**：provider/model 用会话级 `set_config(...,false)` 还是事务级 `...,true`？计划规定前者；在一 RPC 一提交的 hub 上这是唯一正确选择——确认 hub 不会把 parse 包进一个连 GUC 一起提交掉的事务。

---

## 建议的最小修正集（按依赖序）

1. 改 §3 SQL：`options` 改对象、键为相对路径（A2）；同步改 C4 的信号计数说明。
2. 定 A6 的路线（新路由策略版本 vs 去 `path`），并把相应 DML 补进 §3 的"运行时 SQL 全集"与不变量2 的允许清单（A6）。
3. 重排 gate 内部顺序并显式写 A0 的前置（A3），把 A0 断言集改成 advance#4→waiting→结算 human→advance#5→terminal（A4）。
4. 修 A9/B3 期望值为 `alpha\n\nbeta\n\n`（A1），补 symlink fixture（A11）。
5. 把 E4/E5 按实测基线重述，并处理两个既有红 gate 的归属（A5/B2）；E2 改为"本 stage 无可归因改动"（B2）。
6. C4/R3 换成 `mock_from_needed` + `claim_pinned`，并列出 A7 的全部答案值（A7/A8/A9）。
7. 裁决2 补：无缓冲写帧、退出码全集映射（含信号死亡）、空帧语义、hub tick 上限、hub 严格顺序（A12/D1/D3/A17）。
