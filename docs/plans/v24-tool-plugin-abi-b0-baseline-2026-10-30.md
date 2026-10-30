# v24 Tool/Plugin ABI v1 B0：实施基线与准入证明 Deep Plan

日期：2026-10-30。状态：B0 完成；B0-1…B0-7 已在隔离候选树中完成验收。

## 1. Goal 与边界

B0 建立后续 ABI 实施共同使用的事实基线和准入证明，不改变生产执行路径。它回答四个问题：当前 v1 descriptor、line-JSON frame、provider request、tool message 的哪些 bytes 必须保持不变；现有 SQL 能否承载“一个 install、两个 provides、同一个 run 同时 pin 两个 key”；后续 v2 的分页、字节预算、tool lease 和 `model_text` 应由哪个阶段验证；以及当前工作树上的既有 gate 是否仍然全绿。

B0 只新增 B0 测试资产、固定向量、README、执行证据和本计划的结果记录。不得修改 `v24/host/**`、`v24/sql/**`、`v24/s10/**`、`v24/s11/**`，不得创建 `v24/s13/**`，不得实现 descriptor v2、frame v2、renderer、schema validator、`ApprovedPlugin` 或三个新文件系统工具。B0 也不把 `replay_class`、`concurrency`、tool lease precheck 或新的 `model_text` 返回形状接入生产路径。

历史起草口径（plan-only）保留在版本 provenance 中；本次实施已按授权完成 B0-1…B0-7，实际 gate 结果以 §10 前置条件和执行记录为准。

## 2. Done when

B0 只有在以下条件全部满足后才能标记完成：

1. v1 golden 已按固定期望 bytes 建立并可重复验证，覆盖 descriptor、四种 line-JSON request、Python/Node 原始 stdout、provider 首轮与 continuation request、成功和已知错误 tool message，以及 parser/lease/journal 结构不变量。验证器只读已审查的期望值，不能在 gate 中自动 re-bless。
2. 独立的 DB-only multi-provides 探针通过：同一 install 的同 realm `k0/k1` 激活后恰有两个 slot；同一 run 同时 require 两个 key 后恰有两个 live run pin；两个 pin 分别指向正确 slot、descriptor digest，并共享同一 provider fiber/episode；异 realm 负控不会错误解析。
3. 11 条 closeout、G9、G10、Node、multilingual smoke 和两个 B0 新检查在最终候选树上串行实跑，并记录完整命令、时间、source identity、exit code、实际末行和日志 SHA-256。Node 或 multilingual 的 exit 2/SKIP 是未验证，不能标记完成。
4. `v24/sql/**`、`v24/host/**` 相对于 B0 source snapshot 没有变化；没有修改 journal event set、install/pin schema、loader、既有 gate 或 closeout 计数。
5. B0 plan、`v24/b0/README.md`、conformance matrix、deviation ledger 和 B0 execution record 的事实口径一致；分页、bytes budget、lease、`model_text` 被明确标成“当前事实”或“后续合同、B0 未验证”，没有把 v2 行为伪装成已实现。
6. staged 路径只包含 B0 白名单和本阶段要求的收尾工件；工作区中其他并行 modified/untracked 文件没有被带入提交。

## 3. Current-state analysis

### 3.1 现有调用链和冻结点

当前与 ABI 相关的路径是：

```text
manifest.provides[]
  → command_install / host_prepare / fiber_control(on)
  → slots(descriptor, descriptor_digest)
  → start(requires[]) / v24.resolve
  → run pins(key, slot_id, provider fiber/episode, descriptor, digest)
  → model_call / DeepSeek provider projection
  → model outcome {key,args} / tool_call
  → worker claim / journal
  → PluginDispatcher install+pin+five-field+artifact checks
  → line-json v1 subprocess
  → {status,output,usage}
  → tool_message.content = canonical_json(output)
  → settlement / batch barrier / continuation
```

B0 要冻结的接缝如下：

| 接缝 | 当前事实与证据 | B0 处理 |
|---|---|---|
| descriptor | `registry.py:108-145` 的 `pg_jsonb_text` 复刻 PostgreSQL `jsonb::text`；`ApprovedAdapter` 在 `:148-262` 生成 v1 descriptor；`match_pin` 在 `:312-334` 比对 descriptor bytes/digest | 冻结 bytes、digest，并用 PostgreSQL `v24.canonical_json` 做独立 oracle |
| frame | `line_json.py:77-98` 的 v1 request 是 compact sorted JSON 加一个 LF；`:107-149` 要求成功帧的 `result` 是 JSON object 字符串；`:101-105` 使用 `splitlines()` | 冻结四种 request 和 Python/Node 原始 stdout；不改 v1 parser |
| provider request | `deepseek.py:195-401` 生成 body，`:383-392` 在 `send` 中用 `_canonical(body).encode('utf-8')` 交给 transport；`ScriptedTransport` 在 `plugin_fixtures.py:197-214` 保存原始 payload bytes | 冻结首轮和 continuation body；固定 reserve、messages、tool-call id 和 model script |
| tool message | `worker.py:1066-1077` 将 `canonical_json(result['output'])` 写入 `dispatch_finished.payload.tool_message.content`；`worker.py:1190-1231` 的 `_history` 只从 journal 重放 | 冻结成功/失败 content bytes 和 message shape；不新增 journal 字段 |
| lease | `worker.py:86,919-922` 对 tool 使用固定 30000ms；`:972-979` 只有 model 做 remaining lease precheck；`db.py:204-216` 本地计算剩余 lease | 记录当前事实；W4 才实现 v2 tool precheck |
| journal | `journal.py:26-33` 的 event type 是六项闭集；`dispatch_started` 在 `worker.py:1037-1056`、handler 之前写入 | 记录“不以 journal 事件判断 zero spawn”的限制；不改 event set |

### 3.2 多 provides 的已知证据和组合缺口

现有证据只覆盖两半：`v24/s5/test_g4.py:1843-1867` 已证明一个 install 的多个 provides 可形成多个 slot；`v24/s4/test_g2b.py:895-954` 已证明一次 start 的多个 requires 可形成多个 run pin。但没有测试证明两个事实来自同一 install 和同一个 run，因此 B0 必须补一个组合探针。

SQL 侧的预期行为有直接证据：`v24/sql/40_interpreters.sql:3225-3284` 在 `fiber_control(on)` 中逐个 `provides[]` 创建 slot 并递增 `contribution_seq`；`:2725-2854` 在 start 中对每个 required key 通过 `v24.resolve` 创建 run pin；`v24/sql/45_capability.sql:9-66` 按 realm/key、leaf-first 路由；`v24/sql/10_schema.sql:138,199` 分别约束 live pin 和 live slot 的唯一性。

host 目前明确是单工具模型：`v24/s11/plugin_fixtures.py:107-116` 只生成一个 provide；`registry.py` 的 `ApprovedAdapter` 只有一个 descriptor/tool key；`line_json.py:77-86` 的 v1 frame 没有 tool key。因此 B0 只证明 SQL 组合路径，不能把探针的通过写成 host 已经支持多工具 install。

### 3.3 历史证据与 B0 新证据

历史 matrix/README 的通过记录不能代替 B0 本轮实跑。G9 是 11-case extension check，不是第十二条 closeout；G10、Node、multilingual 是独立 extension evidence；closeout 计数固定为 11/11。依据为 `v24/s10/README.md:1-31,47-80`、`v24/s11/README.md:1-43`、`docs/reviews/v24-conformance-matrix-2026-10-23.md:112-124`。

B0 新增的只有：

- 固定 v1 bytes vectors 和只读检查器；
- 同一 install → 两 slot → 同一 run 两 pin 的 SQL-only 组合探针；
- 当前边界和后续合同的证据化登记；
- 在 B0 候选树上重新执行并记录继承 gates。

## 4. B0 的裁决记录

这些裁决由三条 Oracle lane 在已收集源码证据上共同给出。它们是 B0 的实施约束，不是用户对产品偏好的替代。

### 4.1 Golden 按域分文件

采用四个按域的 JSON 文件，分别保存 descriptor、frame/plugin stdout、provider request 和 tool message；capture 与 check 分离。理由是四类 bytes 的 authority 不同，且 Python/Node stdout 必须按语言独立保存。若未来发现某类必须引用另一类，只增加只读的 digest 交叉引用，不合并成一个隐式 serializer。

### 4.2 B0 不修改 ABI 设计稿

B0 只在本计划、`v24/b0/README.md` 和 deviation ledger 中登记分页/bytes budget 的 downstream candidate，留待 W1/W5 的设计同步和工具 gate。当前设计 §7.5 把文档同步安排在实现收口，且设计稿、matrix、ledger 当前有并行未提交修改；B0 不把未验证的未来语义写成已经批准的设计事实。若 W1 无法在该规则下固化工具 vectors，必须先开独立设计修订，再继续工具阶段。

### 4.3 Gate 顺序

实施顺序固定为：source/scope snapshot → multi-provides structural probe → golden capture/check → boundary record → 11 closeout + G9/G10/Node/multilingual → final audit。SQL probe 是设计风险 1 的硬停止条件，必须先于昂贵的完整回归。golden capture 和 checker 在同一候选树中完整可用后，才能作为基线。

### 4.4 脏工作树隔离

先记录当前 checkout 的 HEAD、branch、upstream、modified/untracked 路径和环境，再从明确的 base HEAD 建立 B0-only candidate/worktree 实跑。不要 stash、reset 或覆盖其他并行线。若环境无法在 candidate/worktree 中启动 pgembed，才退回当前树按路径运行，并保留逐文件 hash manifest 和未跟踪路径清单；不能把脏树结果伪装成干净 HEAD 结果。

### 4.5 lease 和 model_text 只冻结现状

B0 不改 host/journal。当前 tool lease 固定 30 秒且无 precheck；W4 的 v2 dispatcher 才使用已 claim 的 `effect['lease_until']` 和 `HostDB.remaining_lease_ms`，要求 `remaining >= descriptor_timeout_ms + 5000`，不足返回普通 failure `lease_insufficient`，zero spawn 以 process sentinel/count 判定。由于 `dispatch_started` 先于 handler，pre-spawn failure 仍可能留下该事件，这是已接受的现状。

W4 的 `model_text` 合同是：dispatcher 产生文本，worker 将最终文本写入现有 `dispatch_finished.payload.tool_message.content`；重启只重放 journal，不重新 render；v1 默认仍逐字节等于 `canonical_json(output)`。 `_call_tool_handler` 也被 `_execute_resource` 共用（`worker.py:1100-1108,1302-1308`），因此 W4 必须保持 resource 的 `(class,result)` 和 receipt shape。B0 不实现这些改动。

### 4.6 未来分页和 bytes budget：冻结为候选合同，B0 不验证

以下规则只作为 W5/W6 的前置合同候选，不应写作 B0 已实现：

- 空文件、空目录、完整搜索无命中时 `offset=1` 成功返回空页；`total=0` 时只有 `offset>1` 越界。完整 search 在 `complete=true` 后同样适用；未完整 search 保持设计中允许的空页/未知 total 规则。
- 分页只切完整 item；`next_offset` 按实际返回 item 数推进；单项在空页也放不下时返回 `line_too_long`、`entry_too_large` 或 `hit_too_large`，不返回无法推进的 cursor。
- `max_args_bytes` 计量独立 compact args object，不含 invoke envelope/LF；host 不注入默认值。
- `max_value_bytes`、`max_content_bytes`、`max_meta_bytes` 分别计量 normalized compact JSON 的 `value`、content array、meta object；缺失 meta 按设计 §5.2 归一为 `{}`，即按两个 bytes 计量。完整 stdout frame 仍受 64 KiB transport limit 约束；host 不静默截断。
- plugin 负责 value 和完整 success frame 的分页/预算；host-owned renderer 负责 content/meta 后置检查。如果 descriptor/render manifest 无法让 plugin 预测 renderer 投影后的预算或保证 cursor progress，W5 必须停止并回设计评审，不新增 RPC、spill store 或 host-driven cursor。

这些规则需要在 W1/M5 的设计同步中正式确认；B0 不修改 `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md`。

## 5. 执行索引

Size 只估人工实现量，不含 gate 等待时间：S < 1 人日，M 约 1–2 人日，L 约 2–3 人日。

| 工项 | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| B0-1 source snapshot | 固定被测 source identity 和 scope | 记录 HEAD/branch/upstream/status、逐文件 hash、Python/uv/PG/Node 版本；candidate tree 只含 B0 允许路径 | B0 plan、执行记录 | 无 | S |
| B0-2 multi-provides probe | 证明同一 install 的两个 provides 能被同一 run 同时 pin | 正例 P1–P7 与异 realm P8 通过；zero spawn=0；失败时停止设计评审 | `v24/b0/test_multi_provides.py` | B0-1 | M |
| B0-3 golden schema/capture | 固定四域 v1 bytes | 两次 capture 候选逐字节一致；固定向量经人工审阅后与 checker 同批落地 | `v24/b0/capture_golden.py`, `golden/` | B0-1；先读 echo.py/echo.js | M |
| B0-4 golden check | 对固定期望 bytes 做可重复验证 | Python/PG 必须通过；Node 可用时 Node 通过；binary parser case 不强制 text decode | `v24/b0/test_golden.py`, `golden/*.json` | B0-3 | M |
| B0-5 boundary record | 将当前事实和下游合同分开 | README/plan/ledger 明确 Q1–Q5、W4/W5/W6 owner 和未验证状态 | `v24/b0/README.md`, plan, ledger | B0-2…4 | S |
| B0-6 inherited gates | 重建本轮 11/11 与 extension evidence | 11 closeout、G9、G10、Node、multilingual 串行实跑并记录；Node/multilingual 不能 SKIP | 执行记录、matrix、ledger | B0-2…5 | L |
| B0-7 final audit | 证明范围和提交集合正确 | SQL/host frozen diff 为空；staged 白名单精确；所有 gate 结果有证据 | git 状态、plan、README、matrix、ledger | B0-6 | S |

## B0 orchestration progress (2026-10-30)

- **B0-1 source snapshot: done.** Isolated candidate is based on `a4b7dba5e945af03d04f4145103ddaaff2ee18ec`; original checkout status, source identity, focused dirty paths, environment versions, and source hash manifest are recorded in `docs/reviews/v24-tool-plugin-abi-b0-execution-2026-10-30.md`.
- **B0-2 multi-provides probe: done.** The DB-only probe passed after adding an explicit zero-call process sentinel assertion in `finally` and a direct P8 run-pin count for the fixture scope. Latest command exited 0; actual last line: `[pass] B0-2 DB-only multi-provides probe; zero process spawns`. Latest log SHA-256: `6dedc5969fd3adbb6222825d0293481b48834642ae28d8dc70cf501feb1c2b39`. The execution record retains earlier fixture failure notes and this rerun evidence.
- **B0-3 golden schema/capture: done.** `v24/b0/golden_cases.py` and `capture_golden.py` produce four domain files only in an explicitly named, previously absent external candidate directory; lexical and symlink-resolved repository paths are rejected. Independent captures 14 and 15 were byte-identical across all four files; the reviewed vectors were delivered with the read-only checker. There are 34 byte cases and six separate structural vectors (40 total entries); the checker pins the exact case-ID set. Observed event types, message keys, and dispatch payload keys are derived from worker journal records, and actual `_lease_for` output is observed during the worker claim path then compared with its default. The parser corpus records existing `splitlines()` behavior for EOF, malformed JSON, result type, missing LF, CRLF, extra frames, invalid UTF-8, U+2028, and U+2029. No source/spec conflict or STOP-D/N occurred.
- **B0-4 golden check: done.** `test_golden.py` is read-only, checks vector self-consistency, current producer bytes, PostgreSQL canonical descriptor text, parser behavior, and F6 structural invariants. Python/PostgreSQL passed by default (29 active cases); `--node` passed with Python+Node/PostgreSQL (34 active cases). Exact commands and log hashes are in the execution record. This does not complete B0-5 through B0-7.
- **B0-5 boundary record: done.** `v24/b0/README.md`, this Result, and the deviation ledger distinguish `observed-current`, `proved-by-B0`, and `contract-frozen/behavior-unverified`; Q1–Q5 and W4/W5/W6 ownership are explicit. The external ABI design remains untouched.
- **B0-6 inherited gates: done.** All 18 commands in §6.5 ran serially in this final candidate with credentials removed and exit 0. Closeout remains 11/11; B0 checks, G9, G10, Node, and multilingual are separate checks. Per-command timestamp, source SHA, candidate fingerprint, command, exit, actual last line, merged log SHA-256, and status are in the execution record.
- **B0-7 final audit: done.** Candidate HEAD is the declared base; `v24/host/**`, `v24/sql/**`, `v24/s10/**`, `v24/s11/**`, and `v24/load.py` have no candidate diff. The source manifest and final audit are in the execution record. Publication is a single B0 milestone commit on primary `main`; the original checkout's unrelated worktree changes remain out of scope.

## Result (2026-10-30)

B0 is complete on candidate source `a4b7dba5e945af03d04f4145103ddaaff2ee18ec` plus the B0-only allowlist. The independently inspected golden implementation retains 34 exact byte cases and six structural vectors, a pinned case-ID inventory, read-only fixed expectations, separate Python/Node stdout cases, PostgreSQL descriptor comparison, and the DB-only two-slot/two-pin proof with a `finally` zero-process assertion. All 18 final commands exited 0 in the prescribed serial order; the complete results and hashes are recorded in `docs/reviews/v24-tool-plugin-abi-b0-execution-2026-10-30.md`. No real provider was called. No SQL was added, so `v24/load.py` and `SQL_LOAD_ORDER` remain unchanged. The B0 delivery paths are restricted to `v24/b0/**`, this plan, the B0 execution record, and B0 additions to the v24 conformance matrix and deviation ledger.

## 6. Detailed work items

### 6.1 B0-1：source snapshot 和候选树

在任何 capture 或 gate 前记录：

```bash
git rev-parse --show-toplevel
git rev-parse HEAD
git branch --show-current
git status --short
git diff --name-status
git diff -- v24/host v24/sql
python --version
uv --version
node --version                 # 缺失时记录 not_available
```

对实际执行的 host、SQL、s10/s11 gate、B0 文件和引用的 fixture 生成排序后的 `path + sha256` manifest。HEAD SHA 不能单独代表 dirty tree；执行证据还必须保存原始 status 和 untracked 路径清单。

从记录的 base HEAD 创建 B0-only candidate/worktree，候选树只加入 B0 计划允许的新增文件和必要收尾文档。B0 不修改其他并行线。若发现 `v24/host/**` 或 `v24/sql/**` 在 source snapshot 已经 dirty，必须把该事实写入 evidence，并在继续前明确 candidate 的基线；不能 stash/reset 或把已有改动归入 B0。

### 6.2 B0-2：DB-only multi-provides probe

新增 `v24/b0/test_multi_provides.py`，不修改 `v24/s11/plugin_fixtures.py`。不得实例化 `PluginHarness`，因为其构造函数会创建 `PluginDispatcher` 和 `HostWorker`（`plugin_fixtures.py:274-287`），违反 DB-only 边界。只复用 setup_db、descriptor/manifest builder、s2/s4/s5 的 command/start helper，以及 `HostDB.claim/settle` 和 owner 只读连接。

#### 正例步骤 P1–P7

1. 创建隔离 root scope，固定本用例 realm `R`。
2. 通过 public `command_install` admit 一个 install，manifest 只有同 realm 的 `k0`、`k1` 两项 provides；descriptor 使用既有 v1 形状但 description 不同，使两项 digest 可区分。artifact 不会被 spawn，可复用合法 digest。
3. 找到唯一 `host_prepare` effect，使用 `HostDB.claim(30000)` 和成功 `HostDB.settle(..., "success", ..., "host_prepare", {})` 结算。G4-D 的 `settle_effect` 形状（`v24/s5/test_g4.py:160-171,1843-1867`）是参考；不得用 dispatcher 代替。
4. 通过真实 `v24.fiber_control(...,'on',...)` 激活 fiber。
5. owner 只读断言该 fiber 的 live slots 恰为两条：keys 是 `k0/k1`，按 provides 顺序 `contribution_seq=[0,1]`，realm 相同，descriptor 与输入相等，descriptor digest 等于 `sha256(pg_jsonb_text(descriptor))`，两个 digest 不同，active episode 相同，未 released/withdrawn。用 `v24.resolve` 交叉核对两个 key 均可解析到这些 slot。
6. 通过 public `start`，一次 requires 同时传 `k0`、`k1`；不运行 worker/model/tool。
7. 通过 public `HostDB.host_run_pins` 作为主要读面断言恰有两个 live run pins。

`v24/sql/49_host_reads.sql:480-547` 已明确返回 `key`、`slot_id`、`provider_fiber_id`、`provider_episode_id`、`provider_install_id`、`descriptor`、十六进制 `descriptor_digest`、release 字段；按 key 对应 slot，两个 pin 共享同一 provider fiber/episode 且 provider install 等于该 install，consumer 是本 run/epoch 1。

#### P8 异 realm 负控

在独立 fixture 中构造不同 realm 的 provides，scope 默认 realm 只能解析其中一个。start 同时 require 两个 key 时，预期 `dependency_unresolved`；不创建成功 run 或 run pins，但允许存在失败 command 的 effect/request receipt。该控制复用既有 G3a 的 resolver 证据（`v24/s2/test_g3a.py:203-220`），不是新的 closeout gate，可作为探针的一部分记录。

#### zero spawn 和停止条件

整个探针禁止构造 dispatcher/worker，patch `v24.host.line_json.run_process`（该模块在 `line_json.py:37` 持有导入绑定），必要时同时 patch lower-level process binding，并拒绝 socket。finally 中断言 sentinel 调用计数为 0。owner 读只能用于证据，禁止直接 INSERT/UPDATE slots/pins。

若 slot/pin 数量、seq、digest、fiber/episode 关系不符，`host_run_pins` shape 不符，异 realm 错误命中，或必须直接写领域表才能通过，先排除 fixture 错误后立即 STOP-S：保留公共 RPC、只读查询、source hash，回设计评审；不改 SQL、不拆成两个 install、不放宽断言。

### 6.3 B0-3/B0-4：v1 golden

产物目录固定为：

```text
v24/b0/
├── README.md
├── capture_golden.py          # 只能写非提交候选目录
├── golden_cases.py            # capture/check 共用输入构造与比较 helper
├── test_golden.py             # gate，只读固定 vectors
├── test_multi_provides.py
└── golden/
    ├── descriptor_v1.json
    ├── frames_v1.json
    ├── provider_requests_v1.json
    └── tool_messages_v1.json
```

每个 case 至少包含 `id`、`domain`、`producer`、固定输入标识、`expected_hex`、`expected_length`、`expected_sha256` 和可选 `expected_text`/semantic expectation。`expected_hex` 是唯一 bytes authority；length/SHA 只检查 vector 自洽。只有有效 UTF-8 case 才要求 `expected_text` 等于 hex 解码结果；非 UTF-8 parser input 必须使用 binary-only case 或 `text: null`，不能要求无效 bytes decode。

capture 只能写显式的非提交候选目录；目标已存在时拒绝覆盖。连续两次 capture 的所有 raw bytes 必须一致，失败即 STOP-N，不能通过 parse/re-serialize、删字段或更新 expected 来掩盖非确定性。审核候选后，checker 与 vectors 作为一个原子交付，gate 不能提供自动 `--force`/re-bless 路径。

#### canonical authority

| domain | authority | 冻结对象 |
|---|---|---|
| `descriptor_pg_jsonb` | `registry.pg_jsonb_text`，并用 PostgreSQL `v24.canonical_json(jsonb)` 独立比对 | v1 descriptor bytes/digest；设计 §4.3 的 V1/V2/`{}` 固定向量 |
| `line_json_v1_request` | `line_json.build_frame` 的 raw bytes | prepare/invoke/release/inspect 四种 request，含末尾 LF |
| `plugin_v1_stdout` | Python/Node echo 子进程 `Invocation.stdout` raw bytes | 各语言独立的 success、exit-3 known-error、生命周期 response |
| `provider_request` | `DeepSeekAdapter.send` 传给 `ScriptedTransport.post` 的 raw payload bytes | 首轮和 continuation body；固定 reserve/max_tokens/tool-call id |
| `tool_message` | `dispatch_finished.payload.tool_message.content.encode('utf-8')`，另存完整 message semantic shape | success 和 known-error content/message；不冻结随机 effect id |

禁止把 `pg_jsonb_text`、`deepseek._canonical`、`journal.canonical_json` 和 `line_json._canonical` 统称为一个 canonicalizer。它们分别来自 `registry.py:108-145`、`deepseek.py:383-392`、`journal.py:64-73`、`line_json.py:72-86`。

#### case matrix

- descriptor：既有 Python/Node echo descriptor、descriptor digest、adapter declaration 和固定 PG vectors；descriptor text 必须同时等于固定 hex 和 PostgreSQL oracle。
- request frame：四个 operation，固定 reservation；args 覆盖 Unicode、换行、空串、U+2028、整数 0 和嵌套 object。
- raw stdout：Python/Node 分开保存成功帧和 exit-3 known-error；不要求两语言 bytes 相同或不同。parser matrix 另外覆盖 EOF、坏 JSON、非 object result、missing LF、CRLF、extra frame、非 UTF-8、U+2028/U+2029 的当前 `splitlines()` 分类。
- provider：固定 start request、history、tool descriptor、reserve token budget、provider tool-call id、final response。至少保存初始 body 和包含 assistant/tool message 的 continuation body；不要保存 Authorization 或真实 key。
- tool message：保存 success 和 known-error 的 `content` bytes 及 `{role,tool_call_id,content}` shape。F6 结构向量记录六项 journal event set、现有 dispatch payload/message key set、30000ms tool lease、transport limits 和当前 v2 descriptor rejection，但不将结构向量误称为 bytes golden。

失败输出只显示 case id、首个差异 offset、双方 length/SHA，不打印完整 body、args、header 或敏感值。

### 6.4 B0-5：边界记录

在 `v24/b0/README.md` 和本计划的 Result 中用三种标签记录：`observed-current`、`proved-by-B0`、`contract-frozen/behavior-unverified`。至少写入：

- 空集合和 offset 的候选规则，明确 B0 没有 v2 工具，不能验证；W5/W6 必须覆盖空页、offset 越界、分页收敛。
- args/value/content/meta 的候选计量域和 renderer ownership，明确 `meta` 缺省按 `{}` 的候选解释尚待设计同步；不能在 B0 改设计稿。
- tool lease 当前固定 30 秒、无 precheck；W4 负责 v2 dispatcher 的 `lease_insufficient` 和 process-count zero spawn。
- 当前 worker 先写 `dispatch_started`，当前 journal 是 transcript 权威；W4 负责 additive `model_text` shape、resource handler 兼容和 restart no-rerender。
- `replay_class`/`concurrency` 只是声明，B0 不把它们接入 no-replay successor 或 recovery。

### 6.5 B0-6：继承 gate runbook

所有命令在最终 B0-only candidate tree 中串行运行；数据库 gate 不并发 DROP/CREATE。G9 和 smoke negative control 使用凭据清除前缀，避免误开真实 provider：

```bash
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 <command>
```

先运行 B0 新检查：

```bash
uv run python v24/b0/test_multi_provides.py
uv run python v24/b0/test_golden.py
uv run python v24/b0/test_golden.py --node
```

随后严格按 frozen order 运行 11 条 closeout：

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

最后运行既有 extension checks：

```bash
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s10/test_g9.py
uv run python v24/s11/test_g10.py
uv run python v24/s11/test_node.py --node
uv run python -m v24.host.plugin_smoke --multilingual-smoke
```

`--only` 只可作调试，不替代无参数 gate。不要运行真实 provider smoke 作为 B0 gate。三态判定必须按每个命令的 README：exit 0 且有该命令要求的 `[passed]` 是 passed；exit 2/SKIP 或 `not_requested` 是 unverified/not requested，不是 pass；exit 1、traceback、缺少预期末行或异常退出是 failed。11 条 closeout 的 extension check 不改变 11/11 计数；G10 Python、Node、multilingual 必须分别记录。

每条命令写入 `docs/reviews/v24-tool-plugin-abi-b0-execution-2026-10-30.md`：

| # | executed_at (+08:00) | source_sha | candidate_fingerprint | command | exit | last_line | log_sha256 | status | note |
|---:|---|---|---|---|---:|---|---|---|---|

原始 stdout/stderr 合并日志放临时目录，只提交 digest 和末行；不提交 secrets。若某条 gate 失败，停止后续完成流程，剩余项记 `not_run`；若 Node/toolchain 缺失为 exit 2，B0 保持未完成，不能提交“全绿”。

## 7. File-by-file impact

### 新增 B0 文件

- `v24/b0/README.md`：B0 范围、canonical authority、命令顺序、三态、已登记偏差和执行记录模板；明确 B0 不是 closeout，也不是 s13。
- `v24/b0/golden_cases.py`：固定输入和 capture/check 共用 helper；不写生产路径。
- `v24/b0/capture_golden.py`：只写非提交候选目录；双跑确定性检查；无自动 re-bless。
- `v24/b0/test_golden.py`：固定 hex 主断言、向量自洽校验、PG oracle、Python/Node 分支；非 UTF-8 case 不强制 text decode。
- `v24/b0/test_multi_provides.py`：DB-only P1–P8、owner evidence reads、zero-spawn sentinel；不构造 `PluginHarness`、`PluginDispatcher` 或 `HostWorker`。
- `v24/b0/golden/descriptor_v1.json`、`frames_v1.json`、`provider_requests_v1.json`、`tool_messages_v1.json`：四域 fixed expected bytes。
- `docs/reviews/v24-tool-plugin-abi-b0-execution-2026-10-30.md`：本轮 source identity、逐命令结果和失败/未验证记录；不要预填通过。

### 必须更新的收尾工件

- `v24/b0/README.md`：实施完成后填入真实命令、结果和 B0 Result。
- `docs/reviews/v24-conformance-matrix-2026-10-23.md`：增加 B0 golden/probe 与继承 evidence 行，保留 closeout 11/11，不把 B0 算第十二条。
- `docs/reviews/v24-deviation-ledger-2026-10-23.md`：登记 B0 的 local subprocess 偏差沿用、固定 canonical authority、zero-spawn 判据、未验证的分页/bytes/lease/model_text 边界和任何实际发现；历史失败追加，不覆盖。
- 本计划：只在 gate 实跑后填写 Result，不提前写“通过”。

### 明确不修改

`v24/host/**`、`v24/sql/**`、`v24/s10/**`、`v24/s11/**`、`v24/load.py`、既有 setup/gate helper、设计稿的 v2 条款、以及其他并行工作线。设计稿是 B0 输入；未来分页/bytes budget 若需要正式变更，另开设计修订后再进入 W1/W5。

## 8. Risks、停止条件与回退

| ID | 触发条件 | 处置 |
|---|---|---|
| STOP-S | slot/pin 数量、seq、digest、fiber/episode、realm routing 或 public `host_run_pins` shape 不符 | 保存 source、RPC、只读查询和日志；停止，回设计评审；不改 SQL、不拆 install |
| STOP-D | 固定 descriptor vector 与 Python 或 PostgreSQL bytes 不符 | 停止 golden；检查 canonical authority 和 source identity；设计数值或源码需要独立评审 |
| STOP-W | candidate 无法与脏树/并行线区分，或 B0 期间 host/sql 被外部修改 | 停止 capture/gate；记录状态，重新建立明确 base candidate；不 stash/reset |
| STOP-N | 两次 capture 不一致，或 provider/frame 含随机 ID、时间、PID、secret | 不冻结该 case；定位非确定性；不规范化掩盖，不修改生产路径 |
| STOP-G | 任一继承 gate exit 1、异常或缺少预期末行 | 保留失败日志，剩余命令记 not_run；B0 不完成，不用历史 pass 抵消 |
| STOP-R | renderer/content budget 或空集合规则无法形成下游可执行合同 | 标为 W1/W5 design blocker，先设计评审；B0 不修改设计稿、不新增 RPC |
| STOP-E | Node 缺失或 multilingual SKIP exit 2 | 标为 unverified，B0 不关闭；安装/恢复工具链后在同一 candidate 重跑 |

B0 生产路径无迁移和数据回滚。未提交时回退只删除 `v24/b0/**`、B0 execution record 和本计划的新增内容；已提交后使用新的 revert commit，不使用 `reset --hard` 或 force push。任何失败证据必须保留，不能通过删除日志或重录 vectors 消除。

## 9. Implementation order

1. 记录 source snapshot、当前脏树和环境；建立 candidate/worktree 与 B0 allowlist。
2. 先实现并运行 DB-only multi-provides probe；确认 SQL 组合路径，否则立即 STOP-S。
3. 读完整 `v24/s11/plugins/echo.py`、`echo.js`，实现 capture/check；生成四域候选 vectors，连续两次确认 bytes 一致，人工审阅后原子纳入 vectors+checker。
4. 运行 golden checker，完成 PostgreSQL descriptor oracle 和 Python/Node 分支。
5. 写 B0 README、plan Result、conformance matrix/deviation ledger 的边界和待验证项；不修改 ABI 设计稿。
6. 在最终 candidate 中先运行两个 B0 checks，再按 frozen order 跑 11 closeout、G9、G10、Node、multilingual；逐条保存 evidence。
7. 做 final audit：source/candidate fingerprint、SQL/host frozen diff、B0 allowlist、日志 digest、无 secrets、无 SKIP/未验证。
8. 只有所有 gates 全部 exit 0、收尾工件更新、工作区路径已逐项核对后，才按仓库规则提交并推送。B0 实施者不得把其他并行改动一并提交。

## 10. 提交与推送前置条件

这是本次已授权实施的出口约束；全部测试与收尾工件完成后，按 AGENTS.md 将 B0-only 变更在 primary `main` 上单次提交并推送 `origin/main`。

- 11 closeout、G9、G10、Node、multilingual、B0 golden/probe 全部在同一最终 candidate 实跑并 exit 0；没有 exit 2、`not_run` 或“预计通过”。
- B0 README、conformance matrix、deviation ledger、execution record 和本计划 Result 已更新为实测结果。
- `git diff --exit-code -- v24/sql` 与 `git diff --exit-code -- v24/host` 相对于 source snapshot 为空；任何 SQL 结构问题已经停止并未被修补。
- `git diff --check` 通过；`git status` 已审阅；暂存路径仅为 `v24/b0/**`、本计划、B0 README/evidence，以及本阶段明确更新的 matrix/ledger，不使用 `git add -A` 或 `git add .`。
- 不提交 `.env`、key、Authorization、临时日志、候选目录、`.DS_Store` 或其他并行线文件。
- 提交信息遵循 `<版本>: <祈使句摘要>`，例如 `v24: establish Tool/Plugin ABI B0 baseline and admission proof`；不使用 `--no-verify`。
- 按仓库 `AGENTS.md` 的顺序：测试全绿 → 收尾工件更新 → 按路径 add → status 复查 → commit → `git push origin main`。push 冲突时 fetch/rebase，禁止 force push；本计划本身不授权现在执行这些动作。

## 11. References

- 设计权威：`docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md`，尤其 §2、§4、§5、§7、§8、§9、§10。
- 现有 host：`v24/host/registry.py`、`line_json.py`、`deepseek.py`、`plugins.py`、`worker.py`、`journal.py`、`db.py`、`process_io.py`。
- 现有 gates：`v24/s7/README.md:210-227`、`v24/s10/README.md`、`v24/s11/README.md`、`v24/s10/test_g9.py`、`v24/s11/test_g10.py`、`v24/s11/test_node.py`、`v24/host/plugin_smoke.py`。
- 多 provides/pins：`v24/sql/10_schema.sql:120-199`、`v24/sql/40_interpreters.sql:2725-2854,3225-3284`、`v24/sql/45_capability.sql`、`v24/sql/49_host_reads.sql:480-547`、`v24/s4/test_g2b.py:895-954`、`v24/s5/test_g4.py:1843-1867`。
- 参考 fixture：`v24/s11/plugin_fixtures.py:89-116,197-214,274-287`、`v24/s5/test_g4.py:160-171`。
- 收尾工件：`docs/reviews/v24-conformance-matrix-2026-10-23.md`、`docs/reviews/v24-deviation-ledger-2026-10-23.md`。
