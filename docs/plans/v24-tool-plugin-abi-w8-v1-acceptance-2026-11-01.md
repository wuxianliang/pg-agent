# v24 Tool/Plugin ABI v1 W8：验收声明与系列收口 Deep Plan（2026-11-01）

状态：**计划，未执行**。本文只规定执行规格；sweep、文档落盘、审计与发布都属后续执行者的工作，`## Result` 在执行前保持未填。

2026-11-01 基线重钉：W7 的 v7/v8 follow-up 已提交为 `5dcbf633ca7b08e171255ee3cf2900d0e5dd6008`（"v24: apply W7 lifecycle review fixes and refresh evidence"），W7 execution record 的源码 SHA 表已同步。本计划的活动基线由 `6297246` 重钉到该提交；17 子句、32 命令、8 项裁决、六候选与证据语义均不变，仅更新 W8-0 的 HEAD、源码 SHA 与 `test_lifecycle.py` 的行号锚点。

路径均相对仓库根 `/Users/wxl/Projects/pg-agent`。标注**【观察】**表示已直接核对的代码或文档事实，**【推断】**表示依据已列观察作出的判断。

---

## 1. 为什么 W8 是「验收声明」而不是「补实现」

### 1.1 系列已经交付到什么程度

M1–M4 已声明完成，M5 在 `a41ce22` 关闭，W7 在 `6297246` 关闭恢复收口，其 v7/v8 follow-up 为 `5dcbf63`。所需的运行时证据都已存在：九个 s13 gate、两个 approved install、真实 Python/Node 子进程、B0 v1 字节基线、11 条冻结 closeout 命令。

### 1.2 W8 的实质增量

设计 §7.4（`docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:952-986`）给出 8 条 done-when，是 v1 自己的验收门。**这份清单从未被任何记录逐条断言过。**【观察】

已核的五份下游文档——`m5-closeout-execution`、`w7-execution`、`w6-execution`、矩阵的 M5/W7 小节、台账的 M5/W7 小节——都在追别的轴：§10 的 M 阶段、C.11/C.15 的 W 标签，或 §7.5 的文档义务。矩阵有 `### §7.5 obligations` 表（`docs/reviews/v24-conformance-matrix-2026-10-23.md:774-782`），却没有 §7.4 表。设计内部也只有 C.15（`:1375-1379`）改写 #1 的 W 标签、C.14（`:1370-1374`）补 #5；#2/#3/#4/#6 从未被绑定到任何 W 标签。设计自己在 C.10（`:1283-1286`）警示"不把 §7.4 的完整 ABI done-when 当成 W3 已完成"。

因此 W8 的增量是三件事：把 8 条拆成 17 个可判定子句并各自绑定到**真正承担论证的断言**（不是函数入口）；在最终 HEAD 上用一次完整串行 sweep 取得当轮证据；让仓库里陈述的真相与实测真相一致。

### 1.3 不是什么

- **不是新 M 阶段，不是 M6，不是 M5 重做。** M4 仍按 C.11 完成，M5 仍按 C.18.1/C.18.7 完成；W8 不重新裁决 M5 的 34 个冻结 `status` 位置，只链接它们。
- **不改运行时。** `v24/host/**`、`v24/sql/**`、两个生产插件、全部测试与 fixture、`v24/s13/vectors/**`、两份 design、drift-factcheck、`v24/s7/README.md`、`AGENTS.md` 全部零 diff。
- **不做 promotion。** 四个 pending token 是首次生产证据归属，不是持续状态；C.18.6 明文禁止重新生成、re-bless 或 promotion。
- **不改设计。** `DESIGN_SHA256 = 778b13a4df78f47987626bbe466b70ebada95fe939565253749b7e6105991a2d` 钉在 `v24/s13/test_contracts.py:10` 并由 `:42-43` 逐字节校验；改 design 就要 repin，W8 不做。完成证据按 C.18.6 只写 README/matrix/ledger/record。
- **不新增 aggregate runner。** 仓库里没有 `.sh`/`Makefile`/`run_all*`，也没有任何 gate 枚举其它 gate；历史每次 sweep 都是人工按表执行并转录。

---

## 2. Goal 与范围

### 2.1 Goal

对 §7.4 的 8 条 done-when 作出**有边界的** v1 验收声明：每条给出裁决、当轮实测证据（sweep 行 + 精确末行 + 断言锚点）、反证条件与适用限制。若任一子句未达 `PASS-LIMITED`，则 W8 以**未发布的 STOP 记录**收场，不作出声明。

### 2.2 In scope

| # | 内容 |
|---|---|
| 1 | 17 个子句的只读证据绑定（BOUND/UNBOUND），按断言区间核对，不改测试 |
| 2 | 一次完整串行 sweep：冻结 32 行 + SUP-1 |
| 3 | 8 项裁决与残余债务裁决（§9 十项、§8 三项、六条设计退出条件） |
| 4 | 六个文档路径的落盘：本计划、本计划的批判记录、execution record、matrix、ledger、s13 README |
| 5 | 七项 scope audit 三轮（precheck / final / confirmation），审计器带负控 |
| 6 | 单次提交与普通 push，publication receipt 外置且**不构成验收权威** |

### 2.3 Out of scope（明确不做）

生产代码或测试修复；设计 repin；向量生成、re-bless 或 promotion；聚合 runner；新 M 阶段；重新裁决 M5；扩大平台、replay、并发或内容类型能力；README 大范围重构或章节搬家；OS 级网络隔离。

发现需要上述任何一项才能通过时，按 STOP 处理，另立工作项，不得边扩大 allowlist 边收口。

---

## 3. Done when

1. **W8-0 基线**：现场取得 `HEAD` 与 `origin/main`，均为 `5dcbf633ca7b08e171255ee3cf2900d0e5dd6008`；tracked 工作树干净；untracked 路径 + SHA-256 快照（含本计划）落盘；`which node` 非空；源码 SHA 与 W7 record 表逐字节相等；已用 grep 确认没有 gate 读取 `docs/reviews/` 或 `v24/s13/README.md`。
2. **W8-1 证据绑定**：17 个子句每条都有 `BOUND`，并带**断言区间**（文件 + 起止行 + 文件 SHA-256），不是只写函数名；任一 `UNBOUND` 即 STOP，不进入裁决与声明。
3. **sweep**：32 行命令与顺序和 W7 **逐字节相同**；`expected-last-lines.txt` 中 rows 27/28/31 的 `node=` 路径按本轮 `which node` 更新（命令本身不含该 token）；32/32 exit 0 且末行精确匹配；无 exit 2 / `[SKIP]`。
4. **SUP-1**：`v24/b0/test_multi_provides.py` 单独运行，记录其真实结果。**它是 W8 自加的补充观察，不是 §7.4 要求，也不进入 17 子句的裁决输入**；其失败的处理见 §5.3。
5. **八项裁决**：8 项全部为 `PASS` 或 `PASS-LIMITED`，且每个强制子句都已成立；明细写入 record 的 17 行 register，matrix 只放 8 行投影。
6. **残余债务裁决**：§9 十项 + §8 三项 + 六条设计退出条件各有闭集裁决与当轮依据。
7. **收口工件**：record 新建；matrix 追加 W8 小节且原文为其逐字节前缀；ledger 追加 `D-ABI-W8-*`；s13 README 在 W7 与 `## Execution` 之间插入单一连续块；无任何历史行被改写。
8. **七项 audit**：precheck、final、confirmation 三轮全部 exit 0 且末行匹配（audit 7 按阶段分级，见 §10.3）。
9. **closeout 仍 11/11**；全部新文本不出现 `12/12`，不把 s13 或 SUP-1 称为第十二条。
10. **发布**：单次提交 `v24: close out Tool/Plugin ABI v1 acceptance`，按路径 add 恰好六个候选，普通 push（非 force），receipt 外置于 `/tmp/v24-abi-w8-<UTC>/publication-receipt.txt`。

---

## 4. Current-state analysis（基线 `5dcbf63`）

### 4.1 验收对象与所有权

| 层 | 当前所有权 | W8 如何复用 |
|---|---|---|
| fixture / approved install | `v24/s13/fixtures.py:353 build_spec` 复制插件、算 artifact digest、生成 manifest、构造 `ApprovedPlugin`；`:409 read_spec` 提供 Python `read`，`:417 node_spec` 在**一个** Node install 内提供 `list` + `search` | 只读复用，不另建 fixture |
| tool binding | `registry.py:246 ApprovedPlugin` 持有 install 审批；`ApprovedTool` 持有各工具 descriptor/validator/renderer/limits；install identity 与 tool key 分离 | 验收同一 Node install 的两个 pin |
| DB lifecycle | install → prepare settlement → activation 形成 slot；`start` 解析 requires 并冻结 run pins；effect settlement 推进 run 与 continuation | 以 G12-A/B 与 Node gate 验证，不改 DB wrapper 或 SQL |
| provider projection | `deepseek.py:355 _tools` 分流 v1/v2，legacy 字节必须不变 | 以 B0 与 G12-L/R14 字节比较验证 |
| tool dispatch | `plugins.py:137 _tool_v2` 先绑定工具，再校验 args/artifact/workspace/lease，随后 spawn；输出经 frame → schema → 页关系 → renderer → 预算 | 复用既有 preflight 与真实子进程证据 |
| worker / journal | `worker.py:1027 _execute_tool` 在 handler **之前**写 `dispatch_started`；journal 保存完成 outcome，恢复可重交完成 outcome，但不自动重执行 tool | 零 spawn 用进程计数；恢复证据保留 `no_replay` 边界 |
| 文档 | record 记一次运行；matrix 裁决符合性；ledger 记偏差与解释；README 是阶段入口 | W8 补齐这四层之间的引用与当前状态 |

端到端路径（W8 不改变任何转换边界）：

```text
read_spec / node_spec
→ manifest + ApprovedPlugin / ApprovedTool
→ admit / prepare / activate
→ start(requires = read, list, search)
→ run pins → scripted model tool_calls
→ worker → dispatcher preflight → Python / Node 子进程
→ frame → value/schema/page validation → renderer → model_text
→ journal outcome + DB settlement
→ batch barrier → 一个 continuation → final
→ off → dispose → release → scope close
```

### 4.2 §7.4 的八条原文

`:952-986`，逐条要点：

1. 九个 s13 gate 全部 exit 0；Node 缺失时 `test_node.py` 必须 `[SKIP]` exit 2，**不能记为通过**。
2. 真实 `install→prepare→activate→start→model→tool→continuation→final→off→dispose→release→scope close`，Python 与 Node 都是真子进程。
3. 一个 Node install 同时提供 `list` + `search`；一次 start 的 requires 同时含三个 key。
4. 同一 model batch 三个 tool 只产生一个 continuation。
5. 所有非法 args/tamper 用例证明零 spawn（进程计数，不以 journal 事件计数）。
6. legacy echo 的 provider 请求体、descriptor bytes、tool message 逐字节等于基线。
7. `v24/sql/**` 零 diff；不打开网络、不接真实 provider。
8. closeout 仍 11/11；s13 不被称为第 12 条 closeout。

### 4.3 八条 → 十七个子句 → 断言锚点（已核验）

§7.4 的条目是**异质**的：#3 捆了两个独立断言，#6 捆了三个字节域，#7 捆了 SQL 与网络。#3/#6/#7 里任何一半失败都会被整条掩盖，所以必须拆成子句再汇总。

| 子句 | 强制断言 | 断言锚点【观察】 | 当轮证据 |
|---|---|---|---|
| 1a | 九个 design 命名 gate 全绿 | 九个文件 `main` 的末行 print | rows 3–8、29、30、31 |
| 1b | Node 缺失 → `[SKIP]` exit 2，不计通过 | `test_node.py:75-77` | 静态契约（本轮 Node 存在，不执行该分支） |
| 2a | 全链到 scope close | `g12_a`（`test_lifecycle.py:643`），断言区 `:647-680`；尾部由 `teardown_two_install:162` 的 `disposed`/`disposed_at`/slot-released/`close_scope().closed_at` 断言承担 | row 30 `python=ok node=ok` |
| 2b | Python 与 Node 都是真子进程 | 同上 `:647-680` 内的 `spawn_count(read)==2`、`spawn_count(node)==3`；`test_node.py:120-121` spawn=3 | rows 30、31 |
| 3a | 一个 Node install 提供 list+search | `g12_a:647-680` 的 `pins["list"] == pins["search"]` 且 `!= pins["read"]`；`test_node.py:114-119` 同 `provider_install_id` | rows 30、31 |
| 3b | 一次 start 的 requires 含三个 key | `g12_a` 的 `start_run(..., ["read","list","search"], ...)`（`:647` 起） | row 30 |
| 4a | 三 tool 一个 continuation | `g12_b:689-710`：`kind='model_call' AND request->>'cause'='continuation'` 计数 == 1，transport calls == 2 | row 30 |
| 5a | 非法 args 零 spawn | `g12_c:725-737` + `ZeroSpawn:80` | rows 2、7、30 |
| 5b | tamper 零 spawn | `tamper_case:795`（`:820-831` 的 `with ZeroSpawn()`）+ spawn-log 基线；R11 `:2373-2389`、R12 `:2462-2474` | row 30 |
| 6a | provider 请求体逐字节 | `g12_l:960-1004` 读 `provider_requests_v1.json` 并比 `[body]` | rows 12–13、30 |
| 6b | descriptor bytes 逐字节 | **仅** `v24/b0/test_golden.py:92-106 _compare` | rows 12–13 |
| 6c | tool message 逐字节 | `g12_l:960-1004` 读 `tool_messages_v1.json` 并比 `content.encode("utf-8")` | rows 12–13、30 |
| 7a | `v24/sql/**` 零 diff | `test_wiring.py:801-805`（无 untracked SQL）+ `:869-871`（SQL 零 diff） | row 32 + audit 1/6 |
| 7b | 不打开网络 | 逐行构造清单（§4.4）；另有 `test_multi_provides.py:279-284` 的 `socket.connect`/`create_connection` 负控 | 全轮 ENVPFX + 构造清单 |
| 7c | 不接真实 provider | 逐行构造清单：32 行中无 `--real-provider-smoke`，且各 gate 的 model 路径为脚本化 transport | 命令表 + 构造清单 |
| 8a | 十一条 closeout 命令全通过 | `v24/s7/README.md:215-227` 的顺序 | rows 14–24 |
| 8b | s13 不是第 12 条 | 命令表与全部新文本 | rows 14–24 + 文本审计 |

**三条必须写进 matrix/ledger 的更正与解释：**

- **R09 不能证明 #4。** W7 的 R09（mixed batch timeout）实测 `continuation == 0` 且 run `blocked_unknown`（`test_lifecycle.py:2169-2172`）。它是一致性/超时证据，不是"一个 continuation"的证据；#4 的交叉证据只能用 R10/R15。【观察】
- **tamper 的零 spawn sentinel 是 `ZeroSpawn`，不是 `CountingSpawn`。** `tamper_case`、R11、R12 都用 `with ZeroSpawn()` 配 spawn-log 基线；`CountingSpawn:253` 是**正计数**证据用的。矩阵历史行 `:873` 把它写成 `CountingSpawn` 是错的——W8 **不改那行历史**，但新绑定必须跟代码一致，并在 ledger 记录该更正。【观察】
- **descriptor 字节只由 B0 提供。** `g12_l` 只加载 `provider_requests_v1.json` 与 `tool_messages_v1.json`（`:960-965`），从不比较 descriptor；R14 同理。把 G12-L/R14 当成 6b 的证据会造出一个并不存在的 `BOUND`。【观察】

**`dispatch_started` 既不证明 spawn 也不反驳 spawn**：`_execute_tool` 在 handler 之前写该事件，pre-spawn 拒绝也可能留下它；零 spawn 的权威是进程计数（C.14、§8.3）。

### 4.4 证据绑定要读的断言区间（W8-1 的输入）

W8-1 只读下表区间，逐行写 `evidence-binding.tsv`；**不写测试、不改代码**。

| 子句 | 必读区间 | 目的 |
|---|---|---|
| 1b | `test_node.py:75-77` | 确认 `[SKIP]` + `return 2` 存在，且该路径不计为通过 |
| 2a / 2b / 3a / 3b | `test_lifecycle.py:647-680`、`:141-180` | 全链断言、spawn 计数、同 install 双 pin、三 key start |
| 4a | `test_lifecycle.py:689-710` | continuation 恰 1 与 transport calls == 2 |
| 5a | `test_lifecycle.py:725-737`、`:76-100` | `ZeroSpawn` 负控与 `invalid_tool_arguments` |
| 5b | `test_lifecycle.py:795-831`、`:2373-2389`、`:2462-2474` | 三种 tamper + R11 四形状 + R12 的零 spawn 双证 |
| 6a / 6c | `test_lifecycle.py:960-1004` | 两个字节域的实际比较语句 |
| 6b | `v24/b0/test_golden.py:92-106` | `_compare` 的 descriptor 域 |
| 3a（v2 侧）/ 2c | `test_node.py:91-121` | 两 key start、两 tool batch、同 install pin、spawn=3 |

另外需一次静态排查（不读业务逻辑，只查入口）：确认 32 行中每个 gate 的 model 路径都是脚本化 transport，且没有任何被扫描入口构造真实 provider adapter；结果写进 `claim-evidence.txt` 的 7b/7c 两行。

### 4.5 可复用件

| 复用 | 出处 |
|---|---|
| execution record 体例、32 行表、期望末行 | `docs/reviews/v24-tool-plugin-abi-w7-execution-2026-11-01.md:44-81` |
| 七项 audit 模型与三轮节奏 | 同上 `:83-113`；`docs/plans/v24-tool-plugin-abi-w7-lifecycle-recovery-2026-11-01.md:934-946` |
| 证据目录布局 | W7 plan `:954-966` |
| 提交/推送顺序与外置 receipt | W7 plan `:1091-1114`；W7 Result `:1305-1350` |
| ledger 条目格式 | `docs/reviews/v24-deviation-ledger-2026-10-23.md:700-729` |
| 逐项义务/裁决表格式 | `docs/reviews/v24-tool-plugin-abi-m5-closeout-execution-2026-11-01.md:47-58` |
| 六个继承审计检查 | `v24/s13/test_wiring.py:790-888`（`BASE=c8c4bd0`，打印 `[scope] passed base=c8c4bd0 checks=6`） |
| 11 条 closeout 命令 | `v24/s7/README.md:215-227` |

---

## 5. 决策记录（Oracle 裁决，2026-11-01）

### 5.1 裁决来源与一致性

本节的裁决来自两轮独立的 Oracle 咨询。**必须如实记录分歧，不能笼统写成"两 lane 完全一致"**：

| 决定 | 首轮两道 drafting lane | 后续裁决 | 本计划采纳 |
|---|---|---|---|
| A1 声明性质 | 一致推荐 A | 裁决轮两 lane 一致选 A | A |
| A2 命令执行方式 | 一致推荐 A（不加 runner） | 未送裁（已由证据定） | A |
| A3 #1 的规范 gate 集 | 一致推荐 A（九条） | 未送裁（已由证据定） | A |
| A4 历史 `cases=14` | 一致推荐"不动历史行" | 未送裁（已由证据定） | 采纳 |
| A5 README 位置 | **分歧**：lane 1 插在 `## Execution` 前，lane 2 主张 EOF 追加 | 裁决轮两 lane 一致选"插在 `## Execution` 前" | 插入 |
| A6 SUP-1 组成 | **分歧**：lane 1 视为非必需佐证，lane 2 视为强制 | 裁决轮一致选"独立 SUP-1"；**"是否阻断"两 lane 仍分歧**（见 §5.3） | 独立运行、不阻断 |
| A7 残余债务落点 | 一致推荐 matrix | 未送裁（已由证据定） | matrix |

### 5.2 决定表

| ID | 决定 | 采用 | 依据 | 性质 |
|---|---|---|---|---|
| **A1** | 声明性质 | 有声明的验收 | C.18.1 要求声明由 execution record 按实际运行日记录；M3/M5/W7 都作了肯定声明；任务是补齐 §7.4 这道从未被断言的验收门 | **含范围判断**：是否声明属 scope call |
| **A2** | 命令执行方式 | 人工按精确表串行，不加 runner | 仓库无聚合 runner；W7 冻结 32 行；runner 会成为新的 untracked 路径 | 工程 |
| **A3** | #1 的规范 gate 集 | 设计点名的九条；其余四个 s13 文件作为继承回归仍必须跑 | §7.4 #1 要求的就是那九条 | 工程 |
| **A4** | 历史 `cases=14` | 不动历史行，由 W8 小节取代其"当前查询"用途 | 三个工件全部追加式；M5 行在其运行日正确 | 工程 |
| **A5** | README 组织 | 不重构；在 W7 之后、`## Execution` 之前插入单一连续块 | W5–W7、M3、M5 都插在该边界前，EOF 追加会破坏五阶段模式 | **含编辑偏好** |
| **A6** | SUP-1 组成与强度 | **独立运行、独立记录、不进入裁决输入、不单独阻断**；其失败若与某子句谓词矛盾，则通过该子句记 `FAIL` | 3a 已由 rows 30/31 完整绑定；强制阻断需执行者临场判断"是否相关"，违反 fail-closed 纪律；无条件忽略红又违反 AGENTS.md | **含政策成分** |
| **A7** | 残余债务裁决落点 | matrix W8 小节，record 摘要并链接 | matrix 已承载 §7.5 与 34 位置裁决；record 从不复制裁决表 | 工程 |

### 5.3 A6 的合成规则（为什么不是简单强制或简单忽略）

- **不进入裁决输入。** 3a 的裁决只由 rows 30/31 派生，SUP-1 不参与 §6.4 的汇总。
- **不采用"红就阻断"。** 否则一个与 ABI 无关的 pgembed/环境抖动就能否决一份九 gate 全绿的声明。
- **也不采用"看了再决定是否相关"。** 那等于把裁量交回执行者，正是本计划要避免的。
- **改用矛盾规则。** SUP-1 失败时，执行者只需回答一个可审计的问题：**它的失败是否与某个子句的谓词直接矛盾？**
  - 矛盾（例如 `_positive` 里第二个 pin 缺失，直接反驳 3a）→ 该子句记 `FAIL`，声明停止。
  - 不矛盾（例如 socket helper / pgembed 环境失败）→ 记 `SUP-1: unrelated-infrastructure`，并在 record 里写明为什么与任何子句谓词无关。**没有解释的失败不得被标为 unrelated。**
- **口径**：报告 `32/32; SUP-1 <result>; closeout 11/11`，不强制写 "SUP-1 PASS"。

**A6 是 W8 自加的范围，不是设计的要求。** §7.4 从未要求这道探针；运行它是为了多一层 DB 层观察，其非必需地位必须明说。

---

## 6. §7.4 验收矩阵设计

### 6.1 唯一落点与单一真相

```text
本计划：执行规格
→ execution record：本轮原始测量 + 17 行 clause register（唯一权威裁决）
→ matrix W8 小节：8 行投影 + 残余债务唯一裁决
→ ledger：决定、解释与限制
→ README：当前状态入口 + 历史阅读规则
```

- **17 行 register 只存在于 execution record**，列固定为：`clause · required predicate · file:line span · BOUND|UNBOUND · 本轮证据 · verdict · limitation · falsifier`。
- **matrix 只放 8 行投影**，内嵌子句 token。投影由 register 派生，不第二次独立裁决。
- **`evidence-binding.tsv` 只是外部工作文件**，17 行、只有 `BOUND`/`UNBOUND`；它不是裁决，也不是 register 的替代物。register 是它的超集。
- 所有行绑定同一个 `HEAD_sweep`、同一份执行源码指纹和同一个 attempt；不得混用不同 attempt 的成功行。

**规范 token 序列化**（审计器与人工都必须能复现）：

- 子句 ID 全小写，按 `1a,1b,2a,2b,3a,3b,4a,5a,5b,6a,6b,6c,7a,7b,7c,8a,8b` 升序；
- 每项写作 `<id>=<VERDICT>`，`VERDICT` 用大写原样；
- 以 `; `（分号 + 单空格）连接，无尾随空格；
- matrix 的项级裁决由审计器**按 §6.4 规则从这 17 个 token 重新计算**，再与 matrix 里写的项裁决比对——只比对内嵌 token 不足以发现项级汇总错误。

**"四个 W8 小节"** 明确定义为：execution record 的 Result、matrix 的 W8 小节、ledger 的 W8 小节、s13 README 的 W8 块。本计划的 `## Result` 不计入这四处，它由 §17 的独立门槛约束。

### 6.2 十七个子句与裁决目标

下表是**执行后的验收目标与取证规则**，不是已作出的通过声明；`预期` 在执行时替换为实测值。

| # | 预期 | 限制（`PASS-LIMITED` 时必须在此行写全） | 反证条件 |
|---|---|---|---|
| 1a | PASS | — | 任一行未运行、exit 2、`[SKIP]`、非零退出或末行不符 |
| 1b | PASS | 静态契约：本轮 Node 存在，缺失分支未执行 | Node 缺失却记 PASS |
| 2a | PASS | 环境注记（不缩小谓词）：本地 PostgreSQL、脚本化 model transport、macOS | 链中任一阶段缺断言；仅 in-process 调用；未完成 release/scope close |
| 2b | PASS | — | spawn 计数为 0；语言缺失 |
| 3a | PASS | — | 拆成两个 install；pin 指向不同 install |
| 3b | PASS | — | requires 长度 ≠ 3 |
| 4a | PASS | — | continuation 为 0 或 >1；三 tool 来自不同 batch |
| 5a | PASS-LIMITED | "所有非法 args"读作设计与既有 gate 枚举的集合；不声称恶意并发 workspace 安全 | 仅凭 journal 事件计数；失败阶段发生真实 spawn |
| 5b | PASS | — | 双证缺一；恢复后的成功 invoke 被混入失败阶段 |
| 6a | PASS | — | 任一字节差；只比解析后 JSON；重生成 golden 后再通过 |
| 6b | PASS | — | 同上 |
| 6c | PASS | — | 同上 |
| 7a | PASS | — | SQL 有差异；存在 untracked SQL |
| 7b | PASS 或 `NOT-DEMONSTRATED` | **不给 `PASS-LIMITED` 出口**：§7.4 #7 是硬要求；构造清单有缺口即 `NOT-DEMONSTRATED` | gate 构造真实 adapter；联网下载依赖；清单无法覆盖某一行 |
| 7c | PASS 或 `NOT-DEMONSTRATED` | 同上 | sweep 含 `--real-provider-smoke`；某 gate 构造真实 provider |
| 8a | PASS | — | 条目数 ≠ 11；跳过或替换既有命令 |
| 8b | PASS | — | 把 s13 或 SUP-1 写为第十二条 |

**绑定与裁决是两件事。** `BOUND` 只表示存在直接检查该断言的代码，不表示它通过。静态契约（1b）按"观察到的构造性证据"记，不伪称本轮执行过缺失分支。

### 6.3 裁决词汇（闭集）

| 裁决 | 规则 |
|---|---|
| `PASS` | 本子句所有强制断言都被当轮证据满足 |
| `PASS-LIMITED` | 强制断言全部成立，但**谓词本身被一个具名非声明收窄**，且限制写在本行 |
| `NOT-DEMONSTRATED` | 没有完成本子句所需的观察（含 `UNBOUND`、构造清单缺口） |
| `BLOCKED` | 前置缺失或出现 exit 2 / `[SKIP]` |
| `FAIL` | 断言失败、非预期退出、marker 缺失或不匹配、审计矛盾 |

规则：

1. exit 0 **不单独构成通过**，命令专属末行也必须匹配。
2. exit 2 / `[SKIP]` 不能产生任何 pass 系裁决。
3. exit 0 但缺 marker 一律 `FAIL`，不得改记 SKIP。
4. `PASS-LIMITED` 只用于**谓词被收窄**的情形（如 5a 的"所有"读作枚举集合），不能给 §7.4 的硬要求开口子：九 gate、真实双语言子进程、三 key、单 continuation、零 spawn、legacy 字节、SQL/无网络、11/11 都不允许用 `PASS-LIMITED` 豁免。
5. Node 在 W8-0 缺失即 STOP，sweep 不启动——不存在"条件通过"。

### 6.4 汇总算法

1. **输入**：`results.tsv`（rows 1–32；**SUP-1 不在此列**）与 `evidence-binding.tsv`（17 行 `BOUND`/`UNBOUND`）。
2. **子句裁决**：任一引用行为 `FAIL` → `FAIL`；否则任一 `BLOCKED` → `BLOCKED`；否则该子句 `UNBOUND` → `NOT-DEMONSTRATED`；否则谓词被收窄 → `PASS-LIMITED`；否则 `PASS`。
3. **项裁决**：对其子句取最差，序为 `FAIL < BLOCKED < NOT-DEMONSTRATED < PASS-LIMITED < PASS`。
4. **声明门槛（两个独立的合取项）**：

```text
declare ⇔ ( 8 项全部 ∈ {PASS, PASS-LIMITED} )  ∧  ( SUP-1 未与任何子句谓词矛盾 )
```

SUP-1 不在第一项里；它的角色只在第二项的"矛盾"判定（§5.3）。
5. **失败处置**：任一不满足 → STOP，且只把失败状态写进 execution record，**不写** matrix/ledger/README。

### 6.5 声明的前提、权威与自动回落

- **权威**：execution record 是验收权威。matrix/ledger/README 是**有界的复述与链接**，本计划的 `## Result` 是同一条声明的摘要。不得出现四处各自独立措辞、互相不一致的"声明"。
- **不依赖 `/tmp`**：任何裁决都不得以只在 `/tmp/v24-abi-w8-<UTC>/` 中存在的事实为依据。所有决定性测量、末行、digest 与裁决都必须在 record 内可读（§9.2、§11）。
- 声明写在 record，以**实际运行日**为准（C.18.1）；同时写下 `HEAD_sweep` 与最终候选指纹——单写 HEAD 不足以标识未提交的文档状态。
- 发布 commit SHA、push 结果与六路径最终 digest 只进外置 receipt，且被归类为**发布日志**，不是验收证据（git 历史本身即持久证明）。
- **预登记自动回落 = 未发布的 STOP 收场**：若任一子句落到 `NOT-DEMONSTRATED` 或更差，W8 不产出可发布的验收包——只产出一份 STOP record 与其证据目录，六个候选文档中除 record 外都不落盘。这不是"换一种方式交付成功"。

---

## 7. W8 串行 sweep

### 7.1 ENVPFX 与执行身份

每一行都从仓库根执行，形态严格为 `$ENVPFX <command>`：

```bash
ENVPFX="env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1"
```

正式执行前固定：`HEAD_sweep`、`origin/main`、分支、候选清单、`U0` untracked 基线、uv/Python/Node/PostgreSQL/OS 版本、`which node` 的字面路径，以及执行源码指纹（全部受验收的 tracked 源码、测试、插件、golden 与 ABI design；唯一排除的是允许修改的 `v24/s13/README.md`）。

依赖全部本地就绪后以离线模式运行（父环境 `UV_OFFLINE=1`），验收过程中不得联网安装或更新依赖——这是 #7 的一部分，不是可选项。

**平台口径**：沿用既有 macOS-first 范围。row 29 预期 `cases=140`、`non_utf8_source=preload_shim`、`linux_real=not_run`。若执行平台不同（例如 Linux 会得到不同的 case 计数），**先修订计划**，不得临场用 Linux 数字替代本计划目标。

"最终"指正式运行时固定的 checkout HEAD 与最终源码，不指尚不存在的 W8 文档提交。sweep 之后只允许六个文档路径变化；执行源码或 HEAD 变化即作废本轮 sweep，不能只补审计。

### 7.2 32 行命令表

命令、参数与顺序与 W7 逐字节相同。每行前置 `$ENVPFX`。

| # | Command |
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

约束：

- **rows 14–24 必须与 `v24/s7/README.md:215-227` 的十一条命令逐字相同且同序**。
- **rows 1–2、9–11** 是继承回归行，不是 §7.4 条目；matrix 里如此标注。
- **rows 27/28/31 的命令不含 `node=`**；该 token 只出现在它们的**期望末行**里，按本轮 `which node` 更新（§7.3）。命令本身仍是逐字节相同。
- **row 2** 日志中会出现中间审计 `[scope] passed base=c8c4bd0 checks=6`，它**不能**代替该命令自己的最终 `[passed]` 末行。
- **row 29** 的 `[evidence]` 行（`read_artifact_sha256`、`read_1m_wall_ms`、`read_peak_kib`、`non_utf8_source`、`linux_real`）与 S25/S26 的 `[probe]` 行只作信息，须**逐字**进 record（非声明引用 `linux_real=not_run`），不作 gate。
- **row 32** 无 marker，必须 exit 0 且输出为零字节。

**关于 §7.4 #7 的读法**（写进 ledger）：设计原文的检查是 `git diff --exit-code -- v24/sql`，只覆盖未提交差异；row 32 以 `c8c4bd0` 为基线覆盖自 SQL 冻结以来的全部变化，叠加 audit 1 的无 untracked 检查，**严格强于**设计原文。这是解释问题，不新增第 33 行。

### 7.3 预期末行的冻结方法

W8-0 先从 W7 record 的 32 行表提取独立清单，存为 `expected-last-lines.txt`。**清单必须在运行前建立，不得从当轮实际输出反推。**

- rows 1–31 用 W7 对应行的完整字面末行。
- rows 27/28/31 只把**期望末行**里的 Node 路径换成本轮 `which node` 的字面值；其余字节不变。不得用通配或前缀匹配。
- row 32 期望 exit 0、零字节、空末行。
- 三行关键 marker 必须逐字保留：

```text
[passed] W4 fs tools; cases=140; read=16; read_probes=29; list=7; list_probes=11; search=24; search_probes=26; pagination_converged=true; page_contracts_imported=3
[passed] W4 lifecycle; cases=30; recovery_probes=16; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true; no_replay=true
[passed] W4 node contract; node=<本轮 which node 的字面路径>
```

### 7.4 SUP-1（补充观察）

row 32 通过后、写正式裁决前执行：

```bash
$ENVPFX uv run python v24/b0/test_multi_provides.py
```

- 期望 exit 0，末行精确等于 `[pass] B0-2 DB-only multi-provides probe; zero process spawns`。**这里是 `[pass]`，不是 `[passed]`；`v24/b0` 在冻结范围内，W8 不改拼写、不改文件。**
- 保存正向与跨 realm 拒绝的输出。
- 独立记为 **SUP-1**：写 `sup-1.log` 与 `supplementary/results.tsv`，**不占 row 33**、不进 `01.log`–`32.log`、不改变 11/11 计数、**不进入 §6.4 的裁决输入**。
- **它是 W8 自加的范围，不是 §7.4 要求。** §7.4 #3 的裁决只依赖 rows 30/31。
- 它唯一提供、而冻结表不直接提供的内容是：slot 级 `contribution_seq`、`descriptor_digest` 与 `pg_jsonb_text` 的关系、`resolve()`、跨 realm 拒绝，以及"零进程"的 DB 侧观察——**不是**"唯一的 one-install→two-pins 证明"（`g12_a` 的 `run_pins` 与 `test_node.py` 的 `host_run_pins` 也读 DB pin）。
- 其失败处置见 §5.3：与子句谓词矛盾 → 该子句 `FAIL`；不矛盾 → 记 `unrelated-infrastructure` 并写明理由。

### 7.5 记录格式、取消与失败重跑

- `results.tsv` 列：`row, utc_start, utc_end, command, exit, last_line, expected_match, log_sha256`。
- 记录的是 **producer 自己的退出码**，不得用 `tail`/`tee` 等消费者的退出码。
- 严格串行；会重建测试库的 gate 不得并行。
- **取消**：SIGINT/SIGTERM/执行者主动取消都使该 attempt **失效**——保留日志、阻断发布，并在重跑 row 1 之前做一次进程/环境清洁检查（无残留插件进程、无残留测试库）。不得把被打断的 attempt 与后续 attempt 拼在一起。
- 任一命令失败即终止该正式 attempt。修复环境后从 row 1 重跑完整 sweep，使用新的 attempt 子目录并重跑 SUP-1；**不得从多次运行拼出"32/32"**。失败日志保留。
- W8 不新增墙钟通过阈值。记录真实起止时间，但不把相邻命令的起止差当作精确 gate 耗时；测试自身的 deadline 与断言仍然有效。
- 参照量级：W7 的整轮窗口约 2.5 分钟。

---

## 8. 残余债务裁决

### 8.1 落点与词汇

只在 matrix 的 W8 小节、八项表之后追加三张表：`§9 risk disposition`（恰 10 行）、`§8 deferred revisions`（恰 3 行）、`Design exit conditions`（恰 6 行）。record 只摘要并链接。

裁决词汇（闭集，三张表共用）：

- `MITIGATED`：当前范围的触发因素有直接防护与本轮证据；不表示未来永不发生。
- `ACCEPTED-LIMITATION`：v1 明确承接的限制。
- `DEFERRED-REVISION`：需要独立设计/host/kernel 修订，W8 不交付。
- `NOT-TRIGGERED`：该停工/退出条件在本轮未被触发。
- `TRIGGERED-STOP`：本轮已触发，不得声明验收。

### 8.2 §9 十项风险

原始表在 `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:1034-1059`。下表是**裁决目标**；执行时须填入本轮行号、日志与实际观察，不能原样预填为既成结果。

| 原风险 | 目标裁决 | 本轮依据与剩余边界 |
|---|---|---|
| #1 多 `provides` 激活 | `MITIGATED` | 主依据是 rows 30/31 的 `g12_a` 与 `test_node.py` 同 install 双 pin；SUP-1 只作 DB 层佐证。若第二个 pin 缺失则 `TRIGGERED-STOP`，不得拆 install 绕过 |
| #2 v2 投影破坏 v1 bytes | `MITIGATED` | rows 12–13 与 G12-L/R14 字节比较；任何差异停止，不得更新 B0 基线 |
| #3 真实成功帧超 64 KiB | `MITIGATED` | row 29 四预算与分页、row 1 页关系、row 8 transport 边界；60000 是内建目标、65536 是 transport 硬上限，不得抬 cap。此裁决不证明任意未来不可分页单结果 |
| #4 preflight 的保守 unknown | `ACCEPTED-LIMITATION` | `dispatch_started` 先于 handler；K1/K2 无可信完成 outcome 时 unknown；零 spawn 用进程计数 |
| #5 Node TOCTOU | `ACCEPTED-LIMITATION` | workspace 仍受信；preflight 与 R11/R12 不构成恶意并发安全证明；需要时转独立 sandbox/host 设计 |
| #6 renderer digest 漂移 | `MITIGATED` | row 5 三组 digest/golden、rows 9–11 冻结检查；行为变更必须升 renderer version 并更新 golden，源码注释格式化不算行为修订 |
| #7 工具 timeout > 25s | `DEFERRED-REVISION` | 当前 read/list 5000、search 15000，registry cap 不变；未来超范围需 claim 前 lease 读取设计，不能靠 W8 放宽 |
| #8 `replay_class` 被当授权 | `MITIGATED` | row 30 `no_replay=true`；完成 outcome 的 reconcile 与重新执行 tool 必须分开陈述 |
| #9 非 UTF-8 的平台差异 | `ACCEPTED-LIMITATION` | 原风险表的"SKIP exit 2"措辞由 C.17 的探测+shim 规定取代；本轮为 macOS root-level shim，`linux_real=not_run`，不覆盖子目录真实非法名称。真实 SKIP 仍阻断 W8 |
| #10 10001 entry 用例耗时 | `MITIGATED`（以实跑为条件） | row 29 的 L03 有真实 10000/10001 边界；若因过慢失败或被跳过则 STOP，不得引用原表的 SKIP 处置把验收记成通过 |

**#9 与 #10 的处置不豁免 §7.4 #1**：原风险表允许记录未验证情形，但完整验收要求九条全部 exit 0；C.17 授权的是有限 shim 证据，不是把 SKIP 变成 PASS。

### 8.3 §8 三项独立修订

| 修订 | 裁决 | v1 承接行为与将来触发条件 |
|---|---|---|
| §8.1 只读工具 `replay_safe` | `DEFERRED-REVISION` | tool successor 仍 `no_replay`，lease 过期转 unknown。若要自动重投，必须原子修改 `48_loop.sql` 的 successor/validator/applier、`49_recovery.sql` 的 recovery 闭集，并同步合同、gate、文档；W8 不实现其中任何部分 |
| §8.2 K1 transcript 派生 | `DEFERRED-REVISION` | journal 仍是 transcript 权威；没有 `derive_model_messages(run_id)`，也没有"删掉 journal 仍能复现请求"的声明。此处"K1"是 §8.2 的设计标签，**不与 W7 的 crash-window K1 混用** |
| §8.3 preflight / `dispatch_started` 顺序 | `DEFERRED-REVISION` | 接受 preflight 窗口可能保守 unknown；将来需要 host 侧 `tool_preflight` 钩子。按 §8.3 自身说明这是**host 修订**，不能误称已交付的 SQL 修订 |

### 8.4 六条设计退出条件（带裁决列）

| # | 条件 | 裁决 | W8 当前处理 | 一旦提出或观察到 |
|---:|---|---|---|---|
| 1 | 非法 args 必须在 model settlement 拒绝、不建 tool effect | `NOT-TRIGGERED` | 不提出；保持 spawn 前拒绝 | STOP，另立 effect/model 边界设计 |
| 2 | 真正只读 replay、写工具、交互 approval、资源撤销、in-flight cancel | `NOT-TRIGGERED` | 均不在本轮 | STOP，独立协议/kernel 设计 |
| 3 | 合法不可分页单结果必然超 64 KiB | `NOT-TRIGGERED` | 当前内建工具依赖有限候选分页 | STOP，不抬 transport cap |
| 4 | 图片或二进制 content block | `NOT-TRIGGERED` | 仍为既有文本合同 | STOP，独立内容协议设计 |
| 5 | 不可信插件或恶意并发 workspace | `NOT-TRIGGERED` | workspace 仍受信 | STOP，独立隔离/权限设计 |
| 6 | PostgreSQL `jsonb::text` 与 Python/Node 在接受输入上不一致 | `NOT-TRIGGERED` | 跑既有三方 canonical vectors；不宣称有限向量穷尽所有输入 | 任一反例即 STOP，不 re-bless |

### 8.5 必须随声明保留的非声明范围

README、record、matrix 统一使用下面这段，不把各层证据合并：

> 不声明硬实时 12 秒上界；C.18.3 的 T1/T2/T3 保持分层。`linux_real=not_run`；非 UTF-8 文件名证据仅为 macOS root-level shim，不覆盖子目录真实非法名称。不声明工具自动重执行，tool 仍为 `no_replay`。不承诺慢 scope 的分页收敛。不调用真实 provider，不进行 gate 对外网络访问；"无网络"是逐行构造论证，不是 OS 级隔离证明。

另需保留 W7 的具体边界：R03 的插件清理由测试侧完成，R13 才证明 host 的 timeout 进程组清理；未覆盖 model response 前的全部崩溃窗口、fair-worker recovery debt、blocked 兄弟 effect 的自动恢复。

---

## 9. 收尾工件对账

### 9.1 六个候选路径

```
docs/plans/v24-tool-plugin-abi-w8-v1-acceptance-2026-11-01.md        （新建，本文）
docs/reviews/v24-tool-plugin-abi-w8-plan-critique-2026-11-01.md     （新建，计划期批判）
v24/s13/README.md
docs/reviews/v24-conformance-matrix-2026-10-23.md
docs/reviews/v24-deviation-ledger-2026-10-23.md
docs/reviews/v24-tool-plugin-abi-w8-execution-2026-11-01.md         （新建）
```

批判记录是**计划期**产物，与 W8 的执行结果无关，因此它不进入任何裁决，只作为本轮设计评审的存档随里程碑一起提交（仓库既有惯例：`docs/reviews/` 下的 plan-critique 随对应阶段提交）。它在 audit 7 里只是"允许出现在候选集内"，不参与 (b)–(f)。

### 9.2 execution record（新建）

#### 9.2.1 证据权威

> 本 execution record 是验收权威。声明不依赖 `/tmp/v24-abi-w8-<UTC>/` 的存续；该目录由执行者保留，日志摘要用于在保留期内复核。

`/tmp` 只是可复现性辅助，**不是**验收依据。任何裁决都不得以只在该目录中存在的事实为依据。hash 只能标识原始日志，不能保存其内容——因此权威必须在仓库内。

#### 9.2.2 必须自带的内容（使任何裁决都不依赖 `/tmp`）

- **Provenance**：`HEAD` 与 `origin/main` 完整 SHA、工具版本、Node 字面路径、实际日期与时区。
- **执行源码指纹**：逐文件 SHA-256 表。
- **32 行表 + SUP-1 行**：实际命令、UTC 起止、producer exit、精确末行、log SHA-256。
- **row 29 的 `[evidence]` 与 `[probe]` 行逐字**（非声明引用 `linux_real=not_run`）。
- **17 行 register** 与 8 项裁决；`results.tsv` 与 `evidence-binding.tsv` 的 SHA-256。
- **precheck/final 审计表**：label、exit、末行、log SHA；审计器定义的 SHA-256。
- **SUP-1 的实际结果**及其"矛盾/无关"判定与理由。

#### 9.2.3 其余章节

1. **Result**（见 §17）。
2. **Candidate and provenance**：六路径、环境、证据目录、源码指纹。
3. **32-command serial sweep**。
4. **SUP-1**：独立结果表。
5. **Acceptance and residual-debt disposition**：链接 matrix，概述声明边界。
6. **Scope audits**：precheck/final 表；confirmation 只记外置位置。
7. **Deviations / Limits / Publication**。

本轮 `read_1m_wall_ms`、`read_peak_kib`、S25 elapsed/overshoot 等值**必须从本轮 row 29 读取**，不得复制 M5/W7 的历史数值；artifact digest 即使相同也要重算并标为本轮观察。不持久化 API key 或原始 DSN。

### 9.3 matrix W8 小节

EOF 追加 `## Post-closeout Tool/Plugin ABI W8 v1 acceptance（2026-11-01）`，内容为：

1. **8 行 §7.4 投影表**，内嵌 canonical token；
2. **gate 集说明**：九个 design 命名 gate，加四个继承回归行（rows 1–2、9–11），并注明 s13 十三个文件 / 十四次 s13 调用的区别；
3. **§9 / §8 / 退出条件**三张裁决表；
4. **陈旧查询面说明**（§9.6）；
5. 当前 row-29/30/31 marker、限制、record 链接。

原文必须是新文件的**逐字节前缀**。

### 9.4 ledger 条目

EOF 追加同标题小节与 `D-ABI-W8-1…9`：

| Entry | 内容 |
|---|---|
| `D-ABI-W8-1` | §7.4 首次逐项验收；声明性质、范围与逐字非声明；A1 属 scope call；record 为权威、其余为有界复述 |
| `D-ABI-W8-2` | 九 gate / 十三文件 / 十四次 s13 调用的区分；#1 的 W 措辞按 C.11/C.15 |
| `D-ABI-W8-3` | 冻结 32 不变；SUP-1 独立、非 §7.4 要求、不进入裁决输入、不单独阻断（A6 政策）；无 runner；11/11 不变 |
| `D-ABI-W8-4` | 历史 `cases=14` 在其运行日有效；W8 提供当前查询入口 |
| `D-ABI-W8-5` | README 单一连续插入；A5 属编辑偏好；精确 supersedes 范围 |
| `D-ABI-W8-6` | 残余债务裁决的落点与闭集词汇（A7，含 `NOT-TRIGGERED`）；#7 的 row-32 读法强于设计原文 |
| `D-ABI-W8-7` | 无 promotion：34 位置、四个 pending token、两个 `"M3-pending"` 占位、`compatibility.*_claimed=false`、design SHA 全部冻结 |
| `D-ABI-W8-8` | 零 spawn 的进程双证用 `ZeroSpawn`（矩阵 `:873` 的 `CountingSpawn` 为历史误记，不追改）；R09 是 `continuation=0` 故不用于 #4；完成 outcome replay ≠ tool 重执行；descriptor 字节只由 B0 提供 |
| `D-ABI-W8-9` | 当轮 provenance、六路径 scope、三轮审计与负控、外置 receipt 属发布日志而非验收权威、`/tmp` 不构成依赖 |

### 9.5 s13 README 插入位置与 supersedes 范围

**位置**：W7 小节之后、`## Execution`（`:209`）之前，插入**单一连续块** `## W8 v1 acceptance（2026-11-01）`。不移动、不重排任何既有章节。

块内必须写明：当前 M1–M5 与 W7 状态及其既有 authority；W8 是 v1 验收收口、不是 M6、不是 M5 重做；本轮有边界的声明、日期、`HEAD_sweep`、32/32、SUP-1 的实际结果（分别陈述）、七项审计与八项表链接；当前 row-29/30/31 marker；§8.5 的统一非声明范围；以及下面这组**只作用于"当前状态查询"用途**的 supersedes 声明（原文保留、不改字节）：

- 开篇 "dispatcher/worker/provider wiring and filesystem-tool behavior remain downstream work"；
- W1 的 artifact/timing/replay pending 当前状态表述（冻结 token 的 provenance 含义仍保留）；
- W4a 的 W4b/W4c downstream 表述；
- W4b/W4c/W5 的 "M3 timing/cutoff remains pending"；
- W6 的 "not an M3-complete declaration" 与"C.18 仍待后续声明"；
- W4c 小节的 `cases=14` marker（`:100`）。

**不要**把"W2 单独不能证明 M2"这类真实的**阶段证据边界**改错——W8 只更新整个系列的当前状态读法，不抹掉历史阶段本身的有限证明范围。

### 9.6 陈旧查询面

两处 `cases=14` 都是其所在阶段的真实测量，本身没错，错的是被当作"当前值"来查：

| 位置 | 性质 | 处置 |
|---|---|---|
| `docs/reviews/v24-conformance-matrix-2026-10-23.md:805`（M5 的 `result_replay_lifecycle` 行） | M5 当轮测量 | W8 小节显式标注为 M5 时点的查询面，给出当前 `cases=30; recovery_probes=16`；**不改原行** |
| `v24/s13/README.md:100`（W4c 小节） | W4c 当轮测量 | 同上；由 W8 块的 supersedes 声明覆盖其当前状态用途 |
| `docs/reviews/v24-conformance-matrix-2026-10-23.md:708`（W4c 小节） | W4c 当轮测量 | 同上，仅由 W8 小节点名，不改 |
| `docs/reviews/v24-conformance-matrix-2026-10-23.md:873`（W7 小节，`CountingSpawn`） | 对 sentinel 的历史误记 | 由 `D-ABI-W8-8` 记录更正；**不改原行** |

当前权威值来自 `v24/s13/README.md:184` 与 W7 record 的 row 30。

---

## 10. Scope audit

### 10.1 基线与继承

- **W8 delta 基线**：`5dcbf633ca7b08e171255ee3cf2900d0e5dd6008`（完整 SHA）。
- **继承审计基线**：仍为 `c8c4bd0`。
- `test_wiring.scope_audit()` 的六项检查必须**原样复用**，包括其旧基线下的向量排除/设计 SHA 还原、registry 精确 D12 patch（−1/+5）、host import purity。W8 的全量冻结检查**叠加**在其上，不得用新基线替换旧断言——否则等于悄悄放宽。
- 允许在证据目录内用一个只读审计记录器产生每项日志与 marker；它只检查断言与快照，不枚举、不调度 gate，不进入仓库。必须保存其定义与其 SHA-256。

### 10.2 七项语义

| # | Label | 必须检查 | 成功末行 |
|---:|---|---|---|
| 1 | `frozen_modules_and_untracked` | 继承 `c8c4bd0` 的 frozen 检查；`5dcbf63` 基线下 `v24/**` 除 `v24/s13/README.md` 外 tracked 字节零 diff；受保护目录无新增非忽略源码文件 | `[scope] passed frozen_modules_and_untracked` |
| 2 | `vectors_zero_diff` | `v24/s13/vectors/**` 相对 `5dcbf63` 与 `e58204c` 均零 diff（含 `design_conformance.json`） | `[scope] passed vectors_zero_diff` |
| 3 | `design_pins_zero_diff` | ABI design、`test_contracts.py`、`test_vectors.py`、`design_conformance.json` 相对 `5dcbf63` 字节相等；design SHA 必须为 `778b13a4…1a2d`；两个 pin 值一致 | `[scope] passed design_pins_zero_diff` |
| 4 | `registry_exact_patch` | 继承 `c8c4bd0` 的整文件替换相等、一个 hunk、−1/+5；registry 相对 `5dcbf63` 零 diff | `[scope] passed registry_exact_patch` |
| 5 | `host_import_purity` | 继承"host 不依赖 vectors / `w1_reference`"检查；`v24/host` 相对 `5dcbf63` 零 diff | `[scope] passed host_import_purity` |
| 6 | `sql_zero_diff` | 相对 `c8c4bd0` 与 `5dcbf63` 零 diff；另跑规范的 `git diff --exit-code -- v24/sql`；并检查 index 与非忽略 untracked SQL | `[scope] passed sql_zero_diff` |
| 7 | `w8_candidate_only` | **按阶段分级**，见 §10.3 | `[scope] passed w8_candidate_only phase=<precheck\|final\|confirmation> checks=<n>` |

第 5 项不得被描述成"所有 host 模块都没有 file/db/network/clock import"——那些职责在 host 里本来就有。它继承的真实检查是禁止测试向量/oracle 依赖，加上本轮的整个 host 冻结。

**README 的额外机械检查**：`git diff --numstat` 对 README 必须显示零删除、单 hunk，且该 hunk 位于 `## Execution` 之前；再加"删掉插入块等于旧字节"的等式检查。

### 10.3 audit 7 的分级断言

audit 7 是唯一与文档内容相关的审计，因此**必须按阶段分级**；否则 precheck 会要求尚不存在的文档。

| 阶段 | 检查项 | 说明 |
|---|---|---|
| **precheck** | 仅 (a) | tracked delta ∪ untracked delta ⊆ 六路径；此时矩阵/README/record 尚未写入，只能查范围 |
| **final** | (a)–(f) | 全量 |
| **confirmation** | (a)–(f) | 全量，结果外置 |

完整断言集：

- **(a) 候选范围**：tracked delta ∪ untracked 路径+内容 delta ⊆ 六路径。
- **(b) 历史前缀**：matrix/ledger 以 `5dcbf63` 原文为逐字节前缀。
- **(c) README 可逆**：删掉插入块后等于基线字节。
- **(d) closeout 口径**：新增行无 `12/12`；四个 W8 小节各含 `11/11`（四处定义见 §6.1）。
- **(e) 表结构**：matrix W8 小节恰 8 行投影、10 行 §9、3 行 §8、6 行退出条件。
- **(f) token 一致**：matrix 的 canonical token 序列与 record register 的 17 个 token 逐 token 相等，**且**按 §6.4 重新计算出的 8 个项裁决与 matrix 所写一致。

precheck 的末行带 `phase=precheck checks=1`；final/confirmation 带 `checks=6`。

### 10.4 untracked 差分算法

W8-0 用 `git ls-files --others --exclude-standard -z` 枚举，保存路径 + SHA-256 得 `U0`；同时把六个候选（含已存在但未跟踪的本计划与批判文档）的执行前副本存进 `baseline-candidates/`，不存在的路径记 `absent`。**`U0` 的条目数与路径以本轮实采为准，不得引用任何历史计数。**

每次 audit 7：

1. 取相对 `5dcbf63` 的完整 tracked 变化，含 staged 与 unstaged；rename 的新旧路径都计入。
2. 枚举当前非忽略 untracked 文件。
3. 同时检查 `U0` 中每个路径是否仍存在、字节是否变化——即使它已被 staging 或其忽略状态变化。
4. 新增、内容变化、真正消失都计入 delta；已 staging 但文件仍存在不得误报为"消失"。
5. 并集必须是六路径子集；输出 added/changed/removed 的数量与路径，不输出文件内容。
6. 符号链接记录链接类型与目标字节摘要，不跟随到工作区外；类型变化也算变化。

不递归扫描 `.venv` 等忽略树。

### 10.5 三轮审计与负控

- **Precheck**：基线与取证完成后、正式 sweep 之前（audit 7 只查 (a)）。
- **Final**：record、README、matrix、ledger、本计划 Result 的实测内容全部写完之后（audit 7 全量）。
- **Confirmation**：写入 final 审计表等最后一批文档修改之后再跑一次；结果**只写外置 receipt**，不再回写仓库，以终止自引用循环。若 confirmation 之后再次编辑候选文档，重跑 confirmation。

**审计器的负控（必需）**：在 `scope-<phase>/negatives/` 下用合成输入证明审计**确实会失败**，每条给 exit 非零与失败行：

1. 一个被篡改的 matrix token（与 register 不一致）→ (f) 必须报错；
2. 一个候选集之外的 untracked 内容变化 → (a) 必须报错。

负控只在证据目录内运行，不新增仓库测试、不改冻结文件。没有负控，"审计通过"只是审计器没有能力的证据。

---

## 11. Evidence 与 execution record

证据目录：`/tmp/v24-abi-w8-<UTC>/`。有重试时每个 attempt 保留独立的 32 行日志与结果，record 只引用最终完整成功的那一次。

**`/tmp` 不是验收权威**（§9.2.1）；它存放原始日志、审计器定义与负控、以及 publication receipt。

| 工件 | 内容 |
|---|---|
| `provenance.txt` | 完整 HEAD、upstream、分支、环境版本、Node 字面路径、实际日期、离线状态 |
| `git-status-initial.txt` / `git-status-final.txt` | 初始与最终完整 porcelain |
| `baseline-untracked.txt` | 本轮实采的 `U0` 路径 + 摘要 |
| `baseline-candidates/` | 六候选执行前副本 |
| `expected-last-lines.txt` | 运行前冻结的 marker 清单 |
| `source-sha256-precheck.txt` | 执行源码、design、goldens、初始候选摘要 |
| `source-sha256.txt` | confirmation 后的最终六候选与受验收源码摘要 |
| `01.log`–`32.log` | 单次正式 sweep 的 producer 输出 |
| `results.tsv` / `merged.log` | 逐行结果与按序合并日志 |
| `sup-1.log`、`supplementary/results.tsv` | SUP-1 独立结果 |
| `claim-evidence.txt` | 17 子句的绑定与 7b/7c 的逐行构造清单，区分观察与推断 |
| `evidence-binding.tsv` | 17 行 `BOUND`/`UNBOUND` 工作文件 |
| `scope-precheck/`、`scope-final/`、`scope-confirmation/` | 七项日志、结果 TSV、继承六项日志、`negatives/` |
| `credential-scan.txt` | 扫描结果；命中只记脱敏位置 |
| `publication-receipt.txt` | **发布日志**（非验收证据）：最终摘要、审计确认、提交与 push 结果；不入 repo |

---

## 12. STOP、回滚与发布

### 12.1 STOP 条件

出现任一情况立即停止当前正式 attempt 或发布流程：

- `which node` 为空；任一命令 exit 2 或出现 `[SKIP]`。
- `HEAD` 或 `origin/main` 不是 `5dcbf63`；W8-0 的源码 SHA 与 W7 表不符。
- 任一 W8-1 子句为 `UNBOUND`；7b/7c 的构造清单无法覆盖某一行（记 `NOT-DEMONSTRATED`）。
- 任一 producer 非预期退出、末行缺失或不匹配；row 32 有输出。
- SUP-1 的失败与某子句谓词矛盾（该子句记 `FAIL`）。
- design SHA 不符、pin 漂移、向量/golden 被修改或重新生成。
- 任一 scope audit（任一轮）失败、负控未按预期报错、候选集越界、历史前缀被重写。
- 八项中任一项的实际断言不足或不成立。
- closeout 不是 11/11，或文档把 s13/SUP-1 写成第十二条。
- gate 打开真实 provider、对外网络或联网安装依赖。
- 凭据扫描命中。
- 需要通过改生产/测试代码、放宽 cap、删除断言、改设计或 promotion 才能通过。

**Node 不可用时即使正确打印 SKIP，仍然是声明被阻断**，不得发布"条件通过"。

发现缺陷时保留失败的 record 与日志；必要修复另立工作项，完成后重订验收基线。W8 不设类似 W7-8 的条件式 host fix。

### 12.2 回滚

W8 是纯文档阶段：

1. **先把失败的尝试写进 record 的 Result 并复制进证据目录**；回滚前必须确认这份失败记录已落盘，不能被回滚静默抹掉。
2. 若已 staging，先只撤销六个候选的 staging。
3. 对基线已 tracked 的 README/matrix/ledger 用按路径的 `git checkout --` 恢复。
4. 对本来 untracked 的本计划，恢复 `baseline-candidates/` 的原始副本；**不能对 untracked 路径假定 `git checkout --` 有效**。
5. 新建的 record 先移入证据目录，确认所有权后再移除仓库副本。
6. 不用 `reset --hard`、`git clean` 或全工作区恢复；不动既有 untracked 文件。
7. 若候选中出现执行者以外的新修改，停止自动恢复并保留现场。已发布后的撤销走正常追加历史的 revert，不重写 main。

### 12.3 发布前置条件（顺序不可颠倒）

```text
32/32 全绿（SUP-1 结果已按 §5.3 判定）
→ 八项验收与残余债务裁决完成
→ README / matrix / ledger / record / 计划 Result 全部更新
→ final audit 全绿 → confirmation audit 全绿
→ git fetch origin，确认 origin/main 仍为 5dcbf63
→ git status → 逐路径 git add 六个候选 → git status / git diff --cached --stat 复查
→ staged bytes 与证据的凭据扫描
→ 单次 commit：v24: close out Tool/Plugin ABI v1 acceptance
→ git push origin main
→ 外置 publication receipt
```

规则：

- 六个路径必须构成实际发布单元，不夹带其它文件；只用按路径 `git add`；禁止 `-A`/`.`/`--no-verify`/force push。
- staging 后复核路径、内容与指纹；hook 若改文件则重查范围，文档变化要重跑 confirmation，执行源码变化则 sweep 作废。
- **rebase 不能靠指纹修复。** 本计划把 `5dcbf63` 钉成受验收基线；任何 rebase 都改变 HEAD 与（可能）源码，因而**使本轮 sweep 作废**。此时要么按 §12.1 停止发布，要么重订基线后从 W8-0 重跑完整流程。不能"确认指纹后继续"。
- push 被拒先 `fetch` 看差异；若远程已分叉且无法安全合并，按 AGENTS.md 停下来问用户；不得 force 或 reset。
- push 失败只记"已提交、未发布"，不能写 published。

---

## 13. 工作项与执行索引

下表是**一个 W8 里程碑内的执行步骤**，不是多个可独立提交的里程碑；六个文档必须作为一个完整收口单元一起发布。

| # | Goal | Done when | Key files | Deps | Size |
|---|---|---|---|---|---|
| W8-0 | 基线与取证 | HEAD/upstream 为 `5dcbf63`；porcelain 与 `U0` 快照（含本计划）落盘；源码 SHA 与 W7 表一致；`which node` 非空；已用 grep 确认没有 gate 读取 `docs/reviews/` 或 `v24/s13/README.md` | 外置 provenance / snapshots | — | S |
| W8-1 | 证据绑定 | 17 行 register 全部 `BOUND`，每行带**断言区间**与文件 SHA；7b/7c 的逐行构造清单闭合 | `test_lifecycle.py`、`test_node.py`、`test_golden.py`、`test_wiring.py`、`fixtures.py`（只读） | W8-0 | M |
| W8-2 | precheck 审计 | 七项 exit 0、末行匹配；audit 7 以 `phase=precheck checks=1` 通过；负控按预期报错 | 外置 `scope-precheck/` | W8-1 | S |
| W8-3 | 正式 sweep | rows 1–32 串行全绿、末行精确匹配；SUP-1 独立运行并记录 | 外置 logs / results | W8-2 | S |
| W8-4 | 裁决 | 8 项汇总完成且均为 pass 系；SUP-1 已判定；十风险 / 三修订 / 六退出条件完成 | `results.tsv`、`evidence-binding.tsv` | W8-3 | M |
| W8-5 | 收口工件 | record、matrix、ledger、README、计划 Result 一致；历史前缀保留；冻结 token 无变化 | 六候选 | W8-4 | M |
| W8-6 | final 与 confirmation | final 全量审计通过；写 final 表后 confirmation 全量通过；最终源码指纹不变 | 外置 audits / receipt | W8-5 | S |
| W8-7 | 提交与发布 | staged 六路径准确、凭据扫描干净、hook 成功；单次普通 push；receipt 记录真实结果 | 六候选 + receipt | W8-6 | S |
| W8-X | 条件 STOP | 由 §12.1 触发；产出未发布的 STOP record，提出独立工作项 | — | 任一 | — |

固定顺序：W8-0 → W8-1 → W8-2 → W8-3 → W8-4 → W8-5 → W8-6 → W8-7。**不得先声明再补证据**：`PASS`/`PASS-LIMITED` 只能在 W8-4 依当轮测量填写。

---

## 14. File-by-file impact

| 路径 | 变化 | 原因与依赖 |
|---|---|---|
| `docs/plans/v24-tool-plugin-abi-w8-v1-acceptance-2026-11-01.md` | 本文（已含执行规格）；执行后只在 `## Result` 登记实测与裁决 | 唯一执行规格 |
| `docs/reviews/v24-tool-plugin-abi-w8-plan-critique-2026-11-01.md` | **新建**（计划期已完成）；本计划采纳的批判意见与出处 | 设计评审存档；不含执行结果 |
| `docs/reviews/v24-tool-plugin-abi-w8-execution-2026-11-01.md` | **新建**；W7 体例 + 17 行 register + §9.2.2 的自带证据 | 验收权威；依赖 W8-3/W8-4 |
| `docs/reviews/v24-conformance-matrix-2026-10-23.md` | EOF 追加 W8 小节：8 行投影、gate 集说明、三张裁决表、陈旧查询面 | 符合性权威；依赖 register 与裁决 |
| `docs/reviews/v24-deviation-ledger-2026-10-23.md` | EOF 追加 `D-ABI-W8-1…9` | 保存决定、解释与冻结纪律 |
| `v24/s13/README.md` | 在 W7 与 `## Execution` 之间插入单一连续块 | 当前状态入口；依赖裁决与实测 |

没有新增或修改运行时类型、函数签名、协议字段、DB schema、序列化规则、actor/thread 边界或持久化迁移。外置证据文件是执行工件，不是生产 API，不进候选提交。

以下全部零 diff：`v24/host/**`、`v24/sql/**`、所有测试与 fixture、两个生产插件、B0 golden、`v24/s13/vectors/**`、两份 design、drift-factcheck、`v24/s7/README.md`、`v24/b0/test_multi_provides.py`、`AGENTS.md`。

---

## 15. 风险

没有数据迁移，也没有破坏性变更。风险都是"陈述的真相"层面的：

1. **过度声明 #2/#3b/#4。** 缓解：W8-1 的 fail-closed 绑定，`UNBOUND` 即 STOP。已核验 `g12_a:643` 含三 key start、三 tool batch、同 install 双 pin 与 `teardown_two_install:162` 的全链；`g12_b:689-710` 断言 continuation == 1。
2. **把既有 untracked 条目卷进提交。** 缓解：audit 7 的 `U0` 差分 + 按路径 add。**不引用任何历史计数**；数量与路径以 W8-0 实采为准。
3. **改文档时顺手重写历史。** 缓解：(b) 前缀检查 + (c) 删块等式 + numstat 零删除。
4. **SUP-1 的处置被用来做临场裁量。** 缓解：§5.3 把问题收敛成"是否与某子句谓词矛盾"，并要求写明理由。
5. **audit 7 在 precheck 阶段误判。** 缓解：§10.3 的分级断言 + 负控。
6. **验收依赖 `/tmp` 存续。** 缓解：§9.2.2 要求 record 自带全部决定性测量。

---

## 16. W8 不证明什么

- **不证明硬实时 12 秒上界。** C.18.3 的 T1/T2/T3 保持分层，不合并成"12 秒已证明"。
- **不证明 Linux real。** `linux_real=not_run`。
- **不证明子目录非 UTF-8。** 平台证据仅为 macOS root-level shim。
- **不证明工具自动重执行。** 所有 tool effect 仍 `no_replay`；完成 outcome 的 journal reconcile 不是重投。
- **不证明慢 scope 的分页收敛。**
- **不证明恶意或并发 workspace 安全。** 不覆盖 `require_artifact` 与 spawn 之间的 TOCTOU、symlink race、恶意插件。
- **不证明 OS 级网络隔离。** "无网络/无真实 provider"是逐行构造论证加凭据清空，不是内核级证明。
- **不产生新的代码级证据。** W8 重新断言既有 gate，新增的只有逐项绑定与当轮测量。
- **不是 M6，不是第 12 条 closeout，不改变 M4/M5 的既有声明。**
- **不重新裁决 M5 的 34 个冻结 `status` 位置**，只链接。
- **不因 SUP-1 而获得额外保证。** 它是 W8 自加的补充观察，不是 §7.4 的组成部分。

---

## 17. References

- `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md`
  - §5.5–§5.6 封闭 schema 与分页/64 KiB（`:728-790`）
  - §6.3 一个 Node install 两工具、§6.4 provider 投影（`:827-882`）
  - §7.3 测试矩阵（`:937-951`）、**§7.4 gate 与 done-when（`:952-986`）**、§7.5 文档义务（`:987-998`）
  - §8.1–8.3 kernel revision（`:999-1033`）、§9 十项风险与退出清单（`:1034-1059`）、§10 M 阶段（`:1060-1071`）
  - C.10（`:1283-1286`）、C.11（`:1287-1298`）、C.14（`:1370-1374`）、C.15（`:1375-1379`）、C.16（`:1380-1386`）、C.17（`:1387-1397`）、C.18.1–C.18.7（`:1398-1437`）
- `docs/reviews/v24-conformance-matrix-2026-10-23.md` — M5 小节（`:770-848`，陈旧 `:805`）、W7 小节（`:850-879`，误记 `:873`）、W4c 小节（`:708`）
- `docs/reviews/v24-deviation-ledger-2026-10-23.md` — M5（`:712-718`）、W7（`:720-729`）
- `docs/reviews/v24-tool-plugin-abi-m5-closeout-execution-2026-11-01.md:47-100`
- `docs/reviews/v24-tool-plugin-abi-w7-execution-2026-11-01.md:1-180`
- `docs/reviews/v24-tool-plugin-abi-w8-plan-critique-2026-11-01.md`（本计划应用的批判意见与来源）
- `docs/plans/v24-tool-plugin-abi-w7-lifecycle-recovery-2026-11-01.md`（体例模板；`:904-1133`、`:1305-1350`）
- `v24/s13/test_lifecycle.py:643`（`g12_a`，断言 `:647-680`）、`:685`（`g12_b`，断言 `:689-710`）、`:715`（`g12_c`）、`:795`（`tamper_case`，`ZeroSpawn` 块 `:820-831`）、`:836`（`g12_f`）、`:959`（`g12_l`，比较 `:960-1004`）、`:162`（`teardown_two_install`）、`:80`（`ZeroSpawn`）、`:253`（`CountingSpawn`，正计数用）、`:2169-2172`（R09 continuation=0）、`:2373-2389`（R11）、`:2462-2474`（R12）
- `v24/s13/test_node.py:75-77`（SKIP 分支）、`:91-121`（两 key start、两 tool batch、同 install pin、spawn=3）
- `v24/s13/test_contracts.py:10`、`:42-43`（`DESIGN_SHA256`）；`v24/s13/test_vectors.py:22,38`
- `v24/s13/test_wiring.py:790-888`（六项继承审计，`BASE=c8c4bd0`）
- `v24/s13/fixtures.py:353`、`:409`、`:417`、`:425`
- `v24/b0/test_golden.py:92-106`（`_compare`）、`:177`（marker）；`v24/b0/test_multi_provides.py:279-284`（socket/process 负控）、`:292`（`[pass]` marker）
- `v24/s7/README.md:215-227`（十一条 closeout 命令）
- `v24/s13/README.md:100`、`:184`、`:187`、`:209`
- `AGENTS.md`（里程碑、按路径提交、禁 force、无真实 provider）

---

## Result

实际执行日期 **2026-11-01**（+08:00；证据目录 UTC 标记 `/tmp/v24-abi-w8-20261101T033123Z/`）。sweep HEAD **`5dcbf63`**（`5dcbf633ca7b08e171255ee3cf2900d0e5dd6008`），`origin/main` 同点；工作区只含本计划的六路径候选。

**32/32**：第 1–31 条串行命令全部 exit 0 且有命令专属 `[passed]` 末行，第 32 条 `git diff --exit-code c8c4bd0 -- v24/sql` exit 0、输出为空；无 exit 2/`[SKIP]`。第 14–24 条仍是 11 条 closeout 命令，closeout **11/11** 不变，s13 不是第 12 条。

SUP-1 在 row 32 之后独立运行：exit 0，末行 `[pass] B0-2 DB-only multi-provides probe; zero process spawns`；正向行为 `one install -> two live slots -> one run -> two matching pins`，跨 realm 行为 `cross-realm requirement is unresolved; no run or pin`。它是 W8 自加的补充观察，不是 §7.4 要求，不占 row 33，不进入八项裁决；本轮通过且与任何子句谓词无矛盾。

八项：1 PASS、2 PASS、3 PASS、4 PASS、5 PASS-LIMITED、6 PASS、7 PASS、8 PASS。17 个 canonical token：

```text
1a=PASS; 1b=PASS; 2a=PASS; 2b=PASS; 3a=PASS; 3b=PASS; 4a=PASS; 5a=PASS-LIMITED; 5b=PASS; 6a=PASS; 6b=PASS; 6c=PASS; 7a=PASS; 7b=PASS; 7c=PASS; 8a=PASS; 8b=PASS
```

row 29/30/31 的实际 marker：

```text
[passed] W4 fs tools; cases=140; read=16; read_probes=29; list=7; list_probes=11; search=24; search_probes=26; pagination_converged=true; page_contracts_imported=3
[passed] W4 lifecycle; cases=30; recovery_probes=16; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true; no_replay=true
[passed] W4 node contract; node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node
```

七项 scope audit：precheck 7/7（audit 7 `phase=precheck checks=1`）；final 7/7（audit 7 `phase=final checks=6`，final 表见 [execution record](../reviews/v24-tool-plugin-abi-w8-execution-2026-11-01.md)）；confirmation 只记外置 receipt。负控按预期失败：token 不一致与候选集外 untracked 变化都使审计非零退出。

声明门槛成立：8 项全部属于 `{PASS, PASS-LIMITED}`，且 SUP-1 未与任何子句谓词矛盾。声明句：

> 在本记录所列实际运行日，基于 `HEAD_sweep` 与最终一致的执行源码，按设计 §7.4 done-when 1–8 宣告 v24 Tool/Plugin ABI v1 通过有边界验收。M4、M5 的既有完成声明继续有效；W8 不新增 M 阶段。closeout 仍为 11/11，s13 为 extension evidence。SUP-1 是 W8 自加的补充观察，不是本次验收的组成部分。具体限制以本轮 matrix 与 execution record 为准。

统一非声明范围：

> 不声明硬实时 12 秒上界；C.18.3 的 T1/T2/T3 保持分层。`linux_real=not_run`；非 UTF-8 文件名证据仅为 macOS root-level shim，不覆盖子目录真实非法名称。不声明工具自动重执行，tool 仍为 `no_replay`。不承诺慢 scope 的分页收敛。不调用真实 provider，不进行 gate 对外网络访问；"无网络"是逐行构造论证，不是 OS 级隔离证明。

六路径发布清单：

1. `docs/plans/v24-tool-plugin-abi-w8-v1-acceptance-2026-11-01.md`（本文件）
2. `docs/reviews/v24-tool-plugin-abi-w8-plan-critique-2026-11-01.md`（计划期批判）
3. `v24/s13/README.md`
4. `docs/reviews/v24-conformance-matrix-2026-10-23.md`
5. `docs/reviews/v24-deviation-ledger-2026-10-23.md`
6. `docs/reviews/v24-tool-plugin-abi-w8-execution-2026-11-01.md`

未发生 STOP 或声明阻断。唯一的执行前文档修正是 untracked W8 plan 的 7a/5b/`g12_a` 锚点修正与随后 `U0` 刷新，不改任何执行源码；预检使用 audit harness revision 1，final/confirmation 使用补上 (d)–(f) 的 revision 2，两者定义与 SHA-256 都保存在外置证据目录。这是取证工具修正，不是放宽 gate。

发布：单次提交、按路径 add 六个候选、普通 push；commit SHA、push 退出码、远端 ref 与六路径最终 digest 只进外置 `/tmp/v24-abi-w8-20261101T033123Z/publication-receipt.txt`。本节不嵌自身最终 digest 或 W8 提交 SHA。
