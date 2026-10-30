# v24 Tool/Plugin ABI v1 设计稿

- 日期：2026-10-30
- 状态：设计定稿（待评审）；未改源码、未跑 gate
- 任务书：`docs/investigations/v24-tool-plugin-abi-design-brief-2026-10-29.md`
- 上游裁决：`docs/investigations/deepseek-harness-design-vs-v24-2026-10-29.md`（选 C）、`docs/investigations/v24-drift-factcheck-2026-10-29.md`（D2/D3/D4）
- 范围：host / descriptor / spec 层。`v24/sql/**` 零改动；不建第 11 张表；不建第二 claim/queue/recovery；不做 session/spawn/join。

> 命名说明：本文称 **Tool/Plugin ABI v1** 为整套 ABI 的首次发布；其内部数据格式是 **descriptor v2 / frame v2**，因为 descriptor v1 与 frame v1 已经被 `v24/s11` 的 echo 占用。不要把 “ABI v1” 误读成 “descriptor v1”。

---

## 0. Oracle reconciliation

三份独立设计：

| Lane | 模型 | 状态 | 说明 |
|---|---|---|---|
| L1 | `gpt-6.1-sol-xhigh`（Codex，xhigh） | 完整 | 单次 plan 输出 |
| L2 | `claude-opus-5-5`（customAPI，high） | 完整（两段） | group 内单次输出在 A.4 处被 provider stream 截断；随后用同一模型分两段重跑：A+B、C+D。本文把两段视为同一 lane 的完整设计。 |
| L3 | `kimi-code-plan-cn/k3.1-pro`（Kimi Code，plan） | 完整 | 单次 plan 输出 |

### 0.1 逐项复核与处置

“来源”列：1=L1，2=L2，3=L3；同一行只列提出该主张的 lane。证据列是本人直接读到的源码/规格行，不是 lane 的转述。

| # | 主张 | 来源 | 复核证据 | 处置 |
|---|---|---|---|---|
| R1 | host-only 扩展，不改 `v24/sql/**` | 1,2,3 | `48_loop.sql:296-307`（参数只过形状）、`:1376-1415`（结果只过形状） | **accepted** |
| R2 | descriptor v2 放现有 `slots.descriptor` / pin，digest = `jsonb::text` 的 sha256 | 1,2,3 | `30_advance.sql:4-6`（`canonical_json = p_payload::text`）；`registry.py:108-145` | **accepted** |
| R3 | 拆 `ApprovedAdapter`（进程/制品）与 `ApprovedTool`（key/descriptor） | 1,2,3 | `registry.py:148-262` 当前单工具字段；`40_interpreters.sql:3231-3245` 每个 provide 建一个 slot | **accepted**（用两个类，见 §2.3） |
| R4 | 五字段 install key 不变 | 1,2,3 | `registry.py:225-227`（`canonical_key`）、`:296-310`（`lookup_install`） | **accepted** |
| R5 | descriptor 内重复 `tool.key`，与 provide/pin/request/frame 四方比对 | 2,3 | `deepseek.py:355` 现在只认 `v==1`；`49_host_reads.sql:518-530` pin 带 `key` | **accepted**（digest 因此绑定 key） |
| R6 | `concurrency` 与 `replay_class` 进 v2 descriptor | 1,3 | `48_loop.sql:1133`（successor 硬编码 `no_replay`）、`49_recovery.sql:351-375`（只有 host kinds 可 reset_ready） | **accepted**（metadata only）；加“恢复行为不变”回归测试，禁止把它当授权 |
| R7 | `limits` 放工具专属字段（`max_lines`、`max_entries`、`max_hits`…） | 3 | 会把 ABI 焊死到这三个工具；`parameters.limit.maximum` 与 `output_schema.maxItems` 已能表达 | **rejected**；`limits` 只放通用五字段，工具专属上限进 §6 的合同表 |
| R8 | 封闭 schema 子集允许 `oneOf`（L1/L3）、`default`（L1）、`number`（L1/L3） | 1,3 | 组合语义与浮点格式在 Python/Node 间不一致；三个工具只需要 nullable 与 enum | **rejected**；用 `type` 数组表达 nullable，禁 `oneOf/anyOf/allOf/not/default/number` |
| R9 | v2 `output` 固定四字段 `{value,content,meta,error}`，无用侧填 null | 1 | 内核只要求 `output` 是 object；null 会污染 receipt 且无法用 closed schema 表达“成功/失败二选一” | **rejected**；用判别式 envelope（§5.2） |
| R10 | v2 `output` 带 `"v":2` | 2 | descriptor/pin 已经能判别版本；再带一个 `v` 是第三个版本源 | **rejected** |
| R11 | `error.executed`（false/true/null） | 2 | v1 只有只读工具；`invalid_tool_arguments` 与 `invalid_tool_output` 已能区分“没跑/跑了” | **rejected**（for v1）；写工具时再评估 |
| R12 | `render.digest = sha256(inspect.getsource(fn))` | 2 | 注释/格式变化就会改 digest；应绑定投影合同而非裸源码 | **rejected**；用 renderer manifest（id/version/projection/golden_digest）的 digest（§5.3） |
| R13 | timeout cap 240s/294s + 每工具 lease 回调 | 2,3 | `30_advance.sql:175-180` 内核允许 lease ≤300000ms；但 v1 三个工具最长 15s，无需扩 | **rejected**（for v1）；descriptor timeout 5/5/15s，registry cap 25s，tool lease 固定 30s（§3.4） |
| R14 | `read` 支持图片 / image block | 1,2,3 | Pi `read.ts:33` 是 string 或 image 的 union；v1 没有多模态 provider 映射 | **accepted**（deferred）；v1 文本 only，二进制 fail closed |
| R15 | `search` 用 regex | 1,2,3 | JS/Python 正则方言不同；ReDoS 会把 run 打进 `blocked_unknown` | **rejected**（for v1）；literal-only，regex 另立版本（§6.3） |
| R16 | `list` offset 0 基 | 3 | `read` 是 1 基；同一模型面两套编号必然出错 | **rejected**；三工具统一 1 基 |
| R17 | `list` 列出 `.git` | 3 | 与 L3 自己的共享规则冲突；`.git` 可能含凭据 | **rejected**；`.git` 永不遍历/列出 |
| R18 | `search` column 1 基、按 Unicode 码点 | 2,3 | 与 `read` 的 offset 语义一致；JS 需 `Array.from` | **accepted** |
| R19 | 插件必须是单文件 | 2 | `registry.py:229-255` 的 `require_artifact` 只哈希 `argv[1]` | **accepted**；两个插件各自单文件，路径逻辑内联 |
| R20 | `deepseek._tools` 需要接受 v2 | 1,2（均标“待核实”） | **已核实**：`deepseek.py:355` 硬断言 `descriptor.get("v") != 1` → `descriptor_invalid` | **accepted**（required change）；v1 投影字节不变 |
| R21 | 多 `provides` 激活未实测 | 2 | **已核实**：`40_interpreters.sql:3231-3245` 对 `provides[]` 逐项建 slot；host fixture 仍只构造一项 | **accepted**（risk）；G12-A 先证明，再谈回退 |
| R22 | `ToolDispatchResult` / `model_text` 统一 v1/v2 模型文本 | 1,2,3 | `worker.py:1066-1071` 现在无条件 `canonical_json(output)` | **accepted**；v1 的 `model_text` 就等于该函数，字节不变（§5.4） |
| R23 | K1：把 transcript 派生搬进 DB | 1,2,3 均拒绝本轮做 | `worker.py:944`、`:1190-1231`；D4 | **accepted**（deferred）；本轮不动 journal 权威 |
| R24 | 只读工具改 `replay_safe` | 1,2,3 均拒绝本轮做 | `48_loop.sql:1133`、`:2963`、`49_recovery.sql:351-375` | **accepted**（deferred）；见 §8 |
| R25 | `annotations.title` | 3 | 只是 UI 字段，v1 没有消费者 | **rejected**（for v1） |
| R26 | `max_args_bytes` / `max_meta_bytes` | 3 | 与 `max_value/content` 同属通用边界 | **accepted** |
| R27 | 单独的 `max_output_bytes` | 1,3 | 与三组件上限重复；外层 envelope 开销很小 | **rejected**；由 value/content/meta 三项共同约束 |
| R28 | descriptor 内声明 `errors` 闭集 | 上游 K4 建议 | 三个工具的错误集已在 §6 表冻结；descriptor 再加一份会多一个漂移点 | **rejected**（for v1）；错误码闭集由 §6 表 + 测试保证 |

### 0.2 三份设计的主要分歧（裁决理由）

1. **descriptor 是否带 `key`**：L1 不带，L2/L3 带。裁决带。理由：pin 的 `key` 与 descriptor 的 digest 现在是两个独立事实；带 `key` 后，`descriptor_digest` 同时绑定能力名，`match_tool` 可以做四方全等，而不是只看 request/pin。
2. **`replay_class` / `concurrency` 是否进 v2**：L2 主张不进，L1/L3 主张进。裁决进，但明确“仅声明、零行为”，并用测试锁死。理由：这两个字段是工具语义的一部分；如果 v1 不写，等 Pi/RepoPrompt 的写工具迁进来时要再发一版 descriptor，所有 pin 重算。漂移风险用文档 + 回归测试管理，不用删字段管理。
3. **`limits` 的形状**：L3 把 `max_lines`/`max_entries`/`max_hits` 放进 `limits`，L1/L2 放通用字节/时间。裁决通用五字段。理由：`parameters.limit.maximum` 已经约束输入，`output_schema.maxItems` 已经约束输出；ABI 不应为每个工具加专属 limit 键。
4. **schema 子集**：L1/L3 允许 `oneOf`，L2 不允许。裁决不允许，用 `type` 数组表达 nullable。理由：三个工具只需要 “integer|null” 与 enum；`oneOf` 的分支选择语义在 Python/Node 各写一遍，是纯成本。
5. **envelope**：L1 固定四字段，L2/L3 判别式。裁决判别式，且不带 `v`/`executed`。理由：`status` 已经告诉内核成功/失败；`output` 里再放 null 或第三个版本号，只会让 receipt 更难读。
6. **timeout/lease**：L2/L3 把 lease 做成每工具计算，L1 保守地压在 30s 内。裁决 L1 的方向，但把 cap 收到 25s、不改进程 lease 计算。理由：v1 三个工具 5/5/15s，30s lease 足够；改 `_lease_for` 要在 claim 前读 pin/registry，是新的失败面。
7. **search regex**：三份都默认 regex。裁决 literal-only。理由：任务书上游已把 “literal search” 写进 M2 的验收；ReDoS 与方言差异在 v1 不值得。
8. **`list` 的 hidden/`.git`**：L3 内部自相矛盾（共享规则说 `.git` 永远排除，工具表说 `.git` 也列出）。裁决默认排除 dotfiles，`.git` 永不遍历/列出。

### 0.3 三份设计都漏掉、但实现必须处理的点

| 点 | 证据 | 处理 |
|---|---|---|
| `deepseek._tools` 只接受 `v==1` | `deepseek.py:355` | 改成 `v in (1,2)`；v2 时校验 `tool.key == pin.key`；投影仍是 `{name,description,parameters}` |
| `worker` 在调用 handler **之前**写 `dispatch_started` | `worker.py:1040-1050` | v1 保持现状；本文明确 “zero spawn” 以进程计数为准，不以 journal 事件为准。把 preflight 前移是独立 host revision（§9） |
| `require_artifact` 只哈希 `argv[1]` | `registry.py:229-255` | 两个插件都必须是单文件；多文件插件在 v1 直接拒绝 |
| `host_run_pins` 是否带 `key` | `49_host_reads.sql:518-530` | 带；`match_tool` 可直接用 `pin["key"]`，不需要额外读 slot |
| 多 `provides` 的激活 | `40_interpreters.sql:3231-3245` | SQL 支持；host fixture 要扩，G12-A 先证明 |

### 0.4 W1 reviewed contract decisions (2026-10-30)

These rulings are the reviewed design contract for W1 vectors. They settle specification choices only; they do not claim that any vector, reference implementation, production path, or gate has passed.

| Topic | Adopted rule | Confidence and overturn evidence |
|---|---|---|
| Q1 search cutoff / empty page | A complete empty search at `offset=1` is valid. A complete empty set rejects `offset>1`. Budget exhaustion before a page is filled returns `search_scope_too_large`; every successful `complete=false` page is nonempty and advances `next_offset` by the number of returned hits. | Medium. Reopen only if a consumer needs an empty incomplete page and can distinguish it from exhaustion/no-more-results without weakening cursor semantics. |
| Q2 pagination | Return complete items only; cursor advancement is by the actual returned item count. | High. Reopen on a concrete consumer requirement incompatible with complete-item boundaries. |
| Q3 args budget | Measure compact UTF-8 JSON bytes for the args object alone, excluding frame/envelope/LF; host does not inject defaults. | High. Reopen only on evidence that the existing request contract requires another measurement domain. |
| Q4 output budgets | Measure normalized `value`, the complete `content` array, and normalized `meta` independently using their domain-specific compact UTF-8 JSON. Missing meta measures as `{}` (2 bytes), without requiring wire-field injection. `max_meta_bytes` is 2..16384; 0/1 reject. | High. Reopen on a cross-language byte counterexample or a contract that cannot admit empty normalized meta. |
| Q5 renderer budget and cursor | §5.3.1 defines the total projection and exact content counter; §5.6 freezes observations, enumerates every finite nonempty prefix, measures the finalized value/content/meta/frame, then selects the largest fitting prefix. No monotonicity assumption is allowed. Successful incomplete pages require `k≥1` and safe `next_offset=offset+k>offset`; all no-fit, inconsistent, empty, overflow and cutoff cases have explicit failure/complete-empty branches. | Design proof accepted; vector/reference/production evidence pending. Any counter mismatch, uncovered schema-valid branch, unsafe cursor, or empty incomplete success reactivates STOP-R. |
| Request/response framing | Python and Node request references must match the same fixed bytes: compact sorted UTF-8 JSON, no BOM, exactly one terminal LF. Response input is classification corpus: allow JSON SP/HT/CR around one JSON text before exactly one final LF (including CRLF); reject raw extra/non-final LF, BOM, invalid UTF-8 and malformed payloads with the plan's stable reasons. | High for request bytes; medium-high for whitespace classification. Reopen on concrete ambiguity or runtime divergence, never by loosening expected bytes automatically. |
| Vector location and digest order | W1 uses the separate `v24/s13/vectors/` format and leaves B0 pinned files/IDs unchanged. Renderer golden cases are ordered by UTF-8 bytes of case ID; case object keys use the renderer digest's specified compact sorted JSON authority. | Very high for location; high for ordering. Reopen only for an identified ambiguity in the design formula. |
| Renderer digests | Derive provisional digests from reviewed frozen cases and the §5.3 formula; label `provisional-w2-pending`. Full descriptors reference these values only after independent Python/Node recomputation. | Conditional on exact independent recomputation; any mismatch is STOP-D, not permission to re-bless. |

Confidence values describe the decision, not implementation completeness. W1 case IDs, ownership and status are pinned by `v24/s13/vectors/design_conformance.json`; pending entries remain pending until later W1 work supplies and reviews their fixed data.

---

## 1. 决策摘要

| # | 决策 | 选择 | 拒绝的替代 | 理由 |
|---|---|---|---|---|
| D1 | ABI 组成 | descriptor v2 + frame v2 + host result v2；v1 原样 | 原地改 v1 字段 | v1 echo 必须字节不变 |
| D2 | 定义权威 | 完整 descriptor 进 slot/pin；digest 冻结 | 只把 output/render 放 host | 执行时要能核对冻结合同 |
| D3 | 多工具 | `ApprovedAdapter`（v1，进程）/ `ApprovedTool`（工具）/ `ApprovedPlugin`（v2，进程+多工具） | 每工具一个 install | 一个 Node install 提供 `list` + `search` |
| D4 | 五字段 key | 不变 | 加第六项 protocol | protocol/工具集已被 manifest/adapter digest 覆盖 |
| D5 | 参数/输出校验 | host-only 封闭子集 | DB 校验 / 插件各自校验 | 内核冻结；跨语言一致 |
| D6 | 结果 | 判别式 `{value,content,meta?}` / `{error,content,meta?}` | 四字段带 null | 无 null、无第三版本号 |
| D7 | 模型文本 | v2 用 `content` join；v1 仍 `canonical_json(output)` | 全部切 content | legacy 字节不变 |
| D8 | render | host-owned `{id,version,digest}`；digest 绑 renderer manifest | 插件自渲染 / SQL callback | 可审批、可 golden |
| D9 | transport | one-shot；invoke 带 `tool`；v2 独立解析器 | persistent/streaming/MCP | v1 三个工具足够 |
| D10 | timeout/lease | descriptor 5/5/15s；registry cap 25s；tool lease 30s | 每工具 lease 计算 | 不改 claim 前读路径 |
| D11 | replay/concurrency | 声明进 descriptor，行为零变化 | 改 successor/recovery | 需要 kernel revision |
| D12 | 工具面 | `read`（Python）、`list`+`search`（同一 Node install） | 复制 Pi/RepoPrompt 代码 / 包 MCP | 原生实现，行为对齐 |
| D13 | search | literal-only；1 基 column；确定性排序 | v1 regex | ReDoS/方言 |
| D14 | 验收 | 新增 s13 extension checks；closeout 仍 11/11 | 把 s13 算成第 12 条 closeout | 不改变历史口径 |

---

## 2. 现状与边界

### 2.1 现有调用链（只列与 ABI 有关的点）

```text
manifest.provides[] (descriptor)
  → command_install / host_prepare / fiber_control(on)
  → slots.descriptor + descriptor_digest
  → start(input.requires[]) → run pins(key, slot_id, descriptor, descriptor_digest)
  → model_call：provider 只看到 {name, description, parameters}
  → model outcome {key,args}
  → advance 建 tool_call（pin_id, descriptor_digest, batch_digest, replay_policy=no_replay）
  → worker claim COMMIT → 读回 effect/token → journal
  → PluginDispatcher：重读 install/pin → 五字段 match → 比对 descriptor 字节/digest → artifact SHA-256
  → line-json v1（invoke 不带 tool key）
  → {status,output,usage}
  → batch barrier → continuation
```

关键证据：

| 事实 | 证据 |
|---|---|
| 参数只做 `{key,args}` 形状校验 | `48_loop.sql:296-307` |
| tool successor 硬编码 `no_replay` | `48_loop.sql:1133`；校验 `:2650-2651`；applier `:2963` |
| 结果只校验 `{status,output,usage}`，`usage` 只允许 `wall_ms` | `48_loop.sql:1376-1415` |
| provider 只投影 `{name,description,parameters}`，且现在只认 descriptor `v==1` | `deepseek.py:341-380`，特别是 `:355` |
| v1 成功帧的 `result` 必须是“字符串里的一个 JSON object” | `line_json.py:107-149` |
| `ApprovedAdapter` 单工具，`descriptor` 属性固定生成 v1 | `registry.py:148-227` |
| `match_pin` 只比 descriptor 字节 + digest，不校验 key | `registry.py:312-334` |
| `require_artifact` 只哈希 `argv[1]` | `registry.py:229-255` |
| `tool_handler` 现在返回 `(class,result)`；worker 用 `canonical_json(output)` 做 tool message | `plugins.py:40-83`；`worker.py:1027-1077` |
| tool lease 固定 30s（只有 model 走 adapter lease） | `worker.py:86`、`:919-922` |
| 内核接受 lease 1..300000ms | `30_advance.sql:175-180` |
| host journal 是 provider transcript 的唯一持久来源 | `worker.py:944`、`:1190-1231`；D4 |

### 2.2 本文不改变的所有权

- PostgreSQL：effect 身份、pin、claim、receipt、预算、batch barrier、run 状态。
- Host registry：允许执行的制品、argv/cwd/env、workspace root、完整工具定义、renderer 实现。
- Dispatcher：一次已 claim 调用的参数校验、进程执行、输出校验、渲染。
- Worker：journal 证据、外层 outcome、唯一 settlement。
- 插件：只执行一个工具或一个生命周期操作；没有 DB 凭证、没有 claim/recovery 权。

### 2.3 两个 v2 类型（为什么不是改 `ApprovedAdapter`）

`ApprovedAdapter` 是 v1 的 frozen dataclass，现有 s11 fixture 和 G10 都按单工具字段构造。直接给它加 `tools` 会让 v1 构造、`descriptor` 属性、`match_pin` 全部变成双义。本文用两个类：

```python
@dataclass(frozen=True)
class ApprovedTool:
    key: str
    descriptor: dict            # 深冻结
    descriptor_digest: str      # sha256(pg_jsonb_text(descriptor))
    timeout_ms: int
    render: RendererRef | None  # v1 为 None
    output_schema: dict | None  # v1 为 None

@dataclass(frozen=True)
class ApprovedAdapter:          # v1，字段与行为不变
    ...

@dataclass(frozen=True)
class ApprovedPlugin:           # v2
    ...                          # 与 v1 相同的进程/制品字段
    protocol: Literal[2]
    tools: tuple[ApprovedTool, ...]   # 1..16，key 唯一
    workspace_root: str               # 绝对、realpath、已存在目录
    timeout_ms: int                   # 生命周期操作超时，默认 5000
    timeout_cap_ms: int               # 工具超时审批上限，v1 = 25000
```

两者共享一个无字段 mixin 的 `require_artifact()` / `environment()`。`ApprovedAdapterRegistry` 的索引接受 `ApprovedAdapter | ApprovedPlugin`，`lookup_install` 返回 union；`match_tool(install, pin, key)` 返回 `ToolBinding(entry, tool)`：

- v1：`ToolBinding` 用 adapter 的 `tool_key/description/parameters/descriptor_digest` 现造一个 `ApprovedTool`，`render=None`，`timeout_ms=adapter.timeout_ms`。
- v2：从 `plugin.tools` 按 key 取。

`match_pin` 保留给 v1 测试；对 `ApprovedPlugin` 调用时抛 `protocol_mismatch`，不猜。

这样 v1 的 `descriptor` 属性、`match_pin`、G10 的构造全部不动；v2 走新路径。

### 2.4 多工具 install 的 manifest

```json
{
  "identity": "v24.fs.node",
  "version": "1",
  "requires": [],
  "provides": [
    {"realm": "<fixture-realm>", "key": "list",   "descriptor": { "...": "..." }},
    {"realm": "<fixture-realm>", "key": "search", "descriptor": { "...": "..." }}
  ],
  "adapter_digest": "\\x<sha256(adapter declaration)>"
}
```

- `manifest_digest = sha256(manifest bytes)`；`artifact_digest = sha256(plugin file)`；`adapter_digest` 见 §4.4。
- 同一 manifest 的所有 `provides[].descriptor.v` 必须相同；混用 v1/v2 直接 `RegistryError("mixed_descriptor_versions")`。
- `provides[].key` 必须等于 `descriptor.tool.key`；不等则 `RegistryError("descriptor_key_mismatch")`，不安装。
- SQL 不校验这些内部字段；host registry 在构造 `ApprovedPlugin` 时校验。**未批准的 install 在 spawn 前 fail closed**。

---

## 3. Descriptor v2

### 3.1 精确形状

```json
{
  "v": 2,
  "tool": {
    "key": "read",
    "description": "Read a UTF-8 text file ...",
    "parameters": { "type": "object", "...": "..." },
    "output_schema": { "type": "object", "...": "..." },
    "render": {"id": "v24.fs.read.text", "version": 1, "digest": "<64 lowercase hex>"},
    "limits": {
      "timeout_ms": 5000,
      "max_args_bytes": 16384,
      "max_value_bytes": 40960,
      "max_content_bytes": 41984,
      "max_meta_bytes": 4096
    },
    "concurrency": "parallel",
    "replay_class": "read_only",
    "annotations": {
      "read_only": true,
      "destructive": false,
      "idempotent": true,
      "open_world": false
    }
  }
}
```

顶层与 `tool` 都是关闭集：多一个键就拒绝。

| 字段 | 类型 | 必填 | 约束 |
|---|---|---:|---|
| `v` | integer | 是 | 恒为 `2` |
| `tool.key` | string | 是 | `^[a-z][a-z0-9_.-]{0,127}$`；等于 provide/pin/request/frame 的 key；不等于 `agent.spawn` |
| `tool.description` | string | 是 | 1..4096 UTF-8 bytes，无 NUL |
| `tool.parameters` | schema | 是 | 根必须 `type:"object"`，且 `additionalProperties:false` |
| `tool.output_schema` | schema | 是 | 校验 `value`；三个工具都是 object 根 |
| `tool.render.id` | string | 是 | `^[a-z][a-z0-9_.-]{0,127}$` |
| `tool.render.version` | integer | 是 | 1..2^53−1 |
| `tool.render.digest` | string | 是 | 64 位小写 hex；与 host RenderRegistry 的 manifest digest 全等 |
| `tool.limits.timeout_ms` | integer | 是 | 1..`registry.timeout_cap_ms`（v1 cap 25000） |
| `tool.limits.max_args_bytes` | integer | 是 | 1..65536 |
| `tool.limits.max_value_bytes` | integer | 是 | 1..49152 |
| `tool.limits.max_content_bytes` | integer | 是 | 1..65536 |
| `tool.limits.max_meta_bytes` | integer | 是 | 2..16384 |
| `tool.concurrency` | string | 是 | `parallel` / `exclusive` |
| `tool.replay_class` | string | 是 | `read_only` / `idempotent` / `mutating` / `external` |
| `tool.annotations.read_only` | boolean | 是 | — |
| `tool.annotations.destructive` | boolean | 是 | — |
| `tool.annotations.idempotent` | boolean | 是 | — |
| `tool.annotations.open_world` | boolean | 是 | — |

附加规则：

1. descriptor 的 PG canonical bytes ≤ 16384；嵌套深度 ≤16。
2. 所有数值必须是安全整数（`|n| ≤ 2^53−1`）；禁止浮点、指数、`-0`。boolean 不算 integer。
3. 字符串必须是有效 Unicode scalar 序列；拒绝孤立代理项；不做 NFC/NFD。
4. 不注入默认值后再 hash。`parameters` 里的默认语义写在 `description`，由插件执行；`default` 关键字被 schema 子集拒绝。
5. `annotations` 一致性：`replay_class=read_only` ⇒ `read_only=true`、`destructive=false`、`idempotent=true`；`read_only=true` ⇒ `destructive=false`；`concurrency=parallel` ⇒ `read_only=true`。
6. descriptor 不进入 provider 声明；provider 只看 `{name:key, description, parameters}`。

### 3.2 完整 `read` 示例

W1 provisional digest：`ca52198cf6c2edae798f2340ba4f370f658d422fa05f5d529c28510dea0a680c`，由 `v24/s13/vectors/renderers.json` 的 `render.read.golden` 与 `render.manifest.read` 固定输入复算；状态为 `provisional-w2-pending`，不是 production renderer 验证结果。W2 必须复现该值。

```json
{
  "v": 2,
  "tool": {
    "key": "read",
    "description": "Read a UTF-8 text file inside the approved workspace. offset is the 1-indexed first line (default 1); limit is the maximum number of lines (default 2000, max 2000). If truncated, continue with next_offset.",
    "parameters": {
      "type": "object",
      "properties": {
        "path":   {"type": "string", "minLength": 1, "maxLength": 1024},
        "offset": {"type": "integer", "minimum": 1},
        "limit":  {"type": "integer", "minimum": 1, "maximum": 2000}
      },
      "required": ["path"],
      "additionalProperties": false
    },
    "output_schema": {
      "type": "object",
      "properties": {
        "path":         {"type": "string"},
        "text":         {"type": "string"},
        "start_line":   {"type": "integer", "minimum": 0},
        "end_line":     {"type": "integer", "minimum": 0},
        "total_lines":  {"type": "integer", "minimum": 0},
        "final_newline":{"type": "boolean"},
        "truncated":    {"type": "boolean"},
        "truncated_by": {"type": ["string", "null"], "enum": ["lines", "bytes", null]},
        "next_offset":  {"type": ["integer", "null"], "minimum": 1}
      },
      "required": ["path", "text", "start_line", "end_line", "total_lines",
                    "final_newline", "truncated", "truncated_by", "next_offset"],
      "additionalProperties": false
    },
    "render": {"id": "v24.fs.read.text", "version": 1, "digest": "ca52198cf6c2edae798f2340ba4f370f658d422fa05f5d529c28510dea0a680c"},
    "limits": {
      "timeout_ms": 5000,
      "max_args_bytes": 16384,
      "max_value_bytes": 40960,
      "max_content_bytes": 41984,
      "max_meta_bytes": 4096
    },
    "concurrency": "parallel",
    "replay_class": "read_only",
    "annotations": {"read_only": true, "destructive": false,
                    "idempotent": true, "open_world": false}
  }
}
```

### 3.3 完整 `list` 示例

W1 provisional digest：`5b0bbe8d0fc70ea68c73baeb01b4df1d6be1a4e31e303dc22e3079605376f9c7`，来源为 `v24/s13/vectors/renderers.json` 的 `render.list.golden` 与 `render.manifest.list`；状态为 `provisional-w2-pending`，W2 production renderer 必须复现。

```json
{
  "v": 2,
  "tool": {
    "key": "list",
    "description": "List entries under a directory inside the approved workspace. Non-recursive by default; symlinks are listed but never followed; entries are sorted by UTF-8 path bytes. offset is 1-based (default 1); limit max 500.",
    "parameters": {
      "type": "object",
      "properties": {
        "path":           {"type": "string", "minLength": 1, "maxLength": 1024},
        "recursive":      {"type": "boolean"},
        "include_hidden": {"type": "boolean"},
        "offset":         {"type": "integer", "minimum": 1},
        "limit":          {"type": "integer", "minimum": 1, "maximum": 500}
      },
      "required": [],
      "additionalProperties": false
    },
    "output_schema": {
      "type": "object",
      "properties": {
        "path":    {"type": "string"},
        "offset":  {"type": "integer", "minimum": 1},
        "entries": {
          "type": "array",
          "maxItems": 500,
          "items": {
            "type": "object",
            "properties": {
              "path": {"type": "string"},
              "kind": {"type": "string", "enum": ["file", "directory", "symlink"]},
              "size": {"type": ["integer", "null"], "minimum": 0}
            },
            "required": ["path", "kind", "size"],
            "additionalProperties": false
          }
        },
        "total":             {"type": "integer", "minimum": 0},
        "truncated":         {"type": "boolean"},
        "next_offset":       {"type": ["integer", "null"], "minimum": 1},
        "skipped_non_utf8":  {"type": "integer", "minimum": 0},
        "skipped_special":   {"type": "integer", "minimum": 0}
      },
      "required": ["path", "offset", "entries", "total", "truncated",
                    "next_offset", "skipped_non_utf8", "skipped_special"],
      "additionalProperties": false
    },
    "render": {"id": "v24.fs.list.text", "version": 1, "digest": "5b0bbe8d0fc70ea68c73baeb01b4df1d6be1a4e31e303dc22e3079605376f9c7"},
    "limits": {
      "timeout_ms": 5000,
      "max_args_bytes": 16384,
      "max_value_bytes": 40960,
      "max_content_bytes": 41984,
      "max_meta_bytes": 4096
    },
    "concurrency": "parallel",
    "replay_class": "read_only",
    "annotations": {"read_only": true, "destructive": false,
                    "idempotent": true, "open_world": false}
  }
}
```

`search` 的完整 descriptor 在 §6.3 的合同表 + 附录 A（与 `list` 同 install，`tool.key="search"`，`render.id="v24.fs.search.text"`，`timeout_ms=15000`）。

### 3.4 Timeout 与 lease

已核实：

- 内核 lease `1..300000ms`（`30_advance.sql:175-180`）。
- worker 默认 `default_lease_ms=30000`（`worker.py:86`）；`_lease_for` 只对 `model_call` 特殊，tool 拿 30s（`worker.py:919-922`）。
- `process_io` 的 timeout 上限也是 300000ms（`process_io.py:70-75`）。

v1 策略：

```text
T = descriptor.tool.limits.timeout_ms            # read/list 5000, search 15000
C = plugin.timeout_cap_ms                        # registry 审批上限，v1 = 25000
require 1 <= T <= C <= 25000
lease = 30000ms (default_lease_ms，不改 _lease_for)
pre-dispatch: remaining_lease_ms >= T + 5000
```

- `T > C` 在 registry 构造时 `RegistryError("timeout_exceeds_cap")`，不静默取 min。
- `remaining < T+5000` 时返回普通 failure `lease_insufficient`，零 spawn。
- 生命周期 `host_prepare`/`host_release`/`inspect` 用 adapter 级 `timeout_ms`（默认 5000），同一 30s lease。
- 未来工具需要 `T > 25000` 时，必须同时设计 claim 前 lease 读取；本文不把它偷渡进 v1。

为什么不是每工具 lease：`_claim_and_execute` 在 claim 前只有 `host_effects` 项；要按工具算 lease，必须在那之前读 pin/registry，增加一个失败面。v1 三个工具的最大 15s 落在 30s 内，固定 lease 是正确的保守选择。

---

## 4. Registry 与 digest

### 4.1 类型与接口

```python
@dataclass(frozen=True)
class ApprovedTool:
    key: str
    descriptor: dict
    descriptor_digest: str
    timeout_ms: int
    render: RendererRef | None
    output_schema: dict | None

@dataclass(frozen=True)
class ToolBinding:
    entry: ApprovedAdapter | ApprovedPlugin
    tool: ApprovedTool
```

| 接口 | 签名 | 失败 reason（全部在 spawn 前） |
|---|---|---|
| `lookup_install` | `(install) -> ApprovedAdapter \| ApprovedPlugin` | `install_invalid`、`adapter_not_approved` |
| `match_tool` | `(install, pin, key) -> ToolBinding` | 上述 + `tool_not_approved`、`pin_key_mismatch`、`descriptor_missing`、`descriptor_digest_missing`、`descriptor_mismatch`、`descriptor_digest_mismatch`、`protocol_mismatch` |
| `match_pin` | `(install, pin) -> ApprovedAdapter`（v1 only） | v1 原有 reason；v2 抛 `protocol_mismatch` |
| `require_artifact` | `() -> None`（两个类都有） | `artifact_missing`、`artifact_outside_cwd`、`artifact_unreadable`、`artifact_not_regular`、`artifact_digest_mismatch` |

`match_tool` 的顺序固定：

1. 五字段 `lookup_install`。
2. `pin["key"] == key`，否则 `pin_key_mismatch`。
3. v1：`entry.tool_key == key`；v2：`key in entry.tools`。
4. `pg_jsonb_text(tool.descriptor) == pg_jsonb_text(pin["descriptor"])`。
5. `tool.descriptor_digest == pin["descriptor_digest"].lower()`。
6. artifact 检查仍在 `require_artifact()`，每次 spawn 前调用。

`ApprovedPlugin.__post_init__` 额外校验：

- `protocol == 2`；`tools` 长度 1..16；key 唯一。
- 每个 `tool.descriptor["v"] == 2`；`tool.descriptor["tool"]["key"] == tool.key`。
- `workspace_root` 是绝对路径、`realpath` 后仍是目录、不是 symlink。
- 每个 `tool.render` 在 RenderRegistry 中存在且 digest 全等。
- 所有 `tool.timeout_ms <= timeout_cap_ms`。
- `manifest_digest` 与 bytes 的 sha256 相等（`from_manifest` 时）。

### 4.2 Canonical descriptor 与 digest

**算法不新造**：`descriptor_digest = sha256(UTF-8(pg_jsonb_text(descriptor)))`，与 `v24.canonical_json(jsonb) = p_payload::text` 逐字节一致（`30_advance.sql:4-6`；`registry.py:108-145`）。

规则：

1. 对象键按 UTF-8 字节长度升序，长度相同按无符号字节序升序。
2. `key: value` 用 `": "`，成员间用 `", "`；数组元素间用 `", "`。
3. 字符串：`\"`、`\\`、`\b`、`\f`、`\n`、`\r`、`\t`；其余 `< U+0020` 用 `\u00xx` 小写；`/`、U+2028、非 ASCII 原样 UTF-8。
4. 无 BOM、无尾换行。
5. 数值只允许安全整数；禁止浮点。
6. 包含 `v` 与所有字段；不排序数组。

**不要混淆**：`journal.canonical_json` 是 compact、`sort_keys=True` 的另一种形式，用于 provider 请求与 `request_digest`；`pg_jsonb_text` 才是 descriptor digest 的形式。`pg_jsonb_text` 在 `registry.py`，`canonical_json` 在 `journal.py`；实现时不要互相替换。

### 4.3 跨语言向量（已实算）

V1：

```text
输入: {"tool":{"name":"读取","a":1,"é":[true,null,"\"q\"\n"]},"v":2}
规范文本: {"v": 2, "tool": {"a": 1, "é": [true, null, "\"q\"\n"], "name": "读取"}}
hex: 7b2276223a20322c2022746f6f6c223a207b2261223a20312c2022c3a9223a205b747275652c206e756c6c2c20225c22715c225c6e225d2c20226e616d65223a2022e8afbbe58f96227d7d
sha256: c1b10b0a8058cbccfc721f2418b4f5b022f87282e7ff91053265760dcf27039c
```

V2（`<DEL>` 是单个 0x7f 字节，不是六个字符；`\u0001` 是 6 个字符的转义）：

```text
输入: {"aa":"\u0001<DEL>😀","b":{"z":[],"y":{}},"k":-9007199254740991}
规范文本: {"b": {"y": {}, "z": []}, "k": -9007199254740991, "aa": "\u0001<DEL>😀"}
hex: 7b2262223a207b2279223a207b7d2c20227a223a205b5d7d2c20226b223a202d393030373139393235343734303939312c20226161223a20225c75303030317ff09f9880227d
sha256: 0ff17e8cd7831181e61773ca0803b1168a9ac78a0692d07d5a4ccd26dc0dcbac
```

空对象：`{}` → `44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a`。

测试要求：Python、Node、PostgreSQL 三方必须对**固定的期望 bytes** 比对，不是各自 hash 自己的输出后互比。PostgreSQL 侧用 `SELECT v24.canonical_json('<json>'::jsonb)`。

### 4.4 adapter digest / manifest digest

- `adapter_digest = sha256(compact_json({"adapter":"v24.line-json","language":"python|node","protocol":"v24.line-json.v2","version":2}))`。这是 **compact sorted JSON**，不是 PG canonical；与 v1 的 `adapter_sha256` 保持同一形式。
- v1 的 `adapter_sha256(language)` 字节不变（`plugin_fixtures.py:89-94`）。
- `manifest_digest = sha256(manifest_bytes)`；`artifact_digest = sha256(plugin file)`；`descriptor_digest = sha256(pg_jsonb_text(descriptor))`。
- 五字段 key 仍是 `(identity, version, manifest_digest, artifact_digest, adapter_digest)`；protocol 和工具集已被后三者覆盖，不加第六项。

---

## 5. Transport 与结果

### 5.1 line-json.v2 帧

协议版本由 approved registry 的 `entry.protocol` 静态决定；没有运行时握手，也没有“先发 v1 失败再降级”的重试。

**invoke 请求**（stdin 一行）：

```json
{"v":2,"operation":"invoke","reservation":"v24:tool_call:<effect_id>","tool":"read","args":{"path":"README.md"}}
```

键集恰为 `{v,operation,reservation,tool,args}`；`v=2`；`tool` 必填且等于 request/pin/descriptor 的 key；`args` 是 object。

**prepare / release 请求**：

```json
{"v":2,"operation":"prepare","reservation":"v24:host_prepare:<reservation>","args":{"install_id":"<uuid>"}}
```

键集恰为 `{v,operation,reservation,args}`；不得带 `tool`。

**inspect 请求**：

```json
{"v":2,"operation":"inspect","reservation":"<target_reservation>","args":{"install_id":"<uuid>","target":"host_prepare"}}
```

**成功帧**（exit 0）：

```json
{"ok":true,"v":2,"result":{"value":{"path":"README.md","text":"..."},"meta":{}}}
```

键集恰为 `{ok,v,result}`；`result` 是 object。invoke 的 `result` 是 `{value, meta?}`；prepare/release/inspect 的 `result` 是操作对象（`{"prepared":true}` / `{"released":true}` / `{"observed":"known"}`）。

**已知错误帧**（exit 3）：

```json
{"ok":false,"v":2,"error":{"code":"not_found","message":"File not found."}}
```

键集恰为 `{ok,v,error}`；`error` 恰为 `{code,message}`；`code` 匹配 `^[a-z][a-z0-9_]{0,63}$`；`message` ≤1024 UTF-8 bytes，不含绝对路径、堆栈、环境变量或原始 stderr。

**字节与解析**：

- stdin/stdout 都是 UTF-8、无 BOM；stdin 一帧 + `\n`；stdout 恰好一帧 + 一个末尾 `\n`。
- 按 **LF 字节**分帧，不能用 `str.splitlines()`（它会把 U+2028/U+2029 当换行）。v2 要求 stdout 以恰好一个 `\n` 结尾；多一个空行或缺少末尾 LF 都是 `bad_frame`。
- 拒绝重复对象键、非法 JSON、`NaN`/`Infinity`、孤立代理项。
- `stdout` 上限 65536 bytes（含末尾 LF）；`stderr` 上限 16384 bytes；`stdin` 上限 1 MiB。
- v2 请求的 args compact JSON 上限由 `max_args_bytes` 约束。

**unknown（不是 failure）**：EOF、坏 JSON、额外帧、缺末尾 LF、非 UTF-8、stdout/stderr 超限、timeout、非 0/3 exit、异常信号、`v≠2`、键集不符、`ok` 不是 bool。unknown 必须 kill 整个进程组并 reap；插件不能通过错误帧“声明”unknown。

**资源 receipt**：`host_prepare` / `host_release` / `inspect_resource` 的 outcome 仍是 v1 形状（`{"v":1,"adapter_id","language","prepared"|"released"|"observed"}`）；v2 只改 transport 帧，不改资源 receipt。

**v1 兼容**：

- v1 解析器完全不动：`result` 必须是“字符串里的一个 JSON object”，`splitlines()` 行为保留，`{ok,result}` / `{ok,error,message}` 键集保留（`line_json.py:107-149`）。
- v2 用独立解析器，不复用 `_success_frame`，否则 `result` 的类型变化会污染 v1。
- 旧 host 遇到 v2 install：registry 没有该五字段项 → `adapter_not_approved`，零 spawn。即使手工补项，旧 `descriptor` 属性生成 v1 形状，`match_pin` 得到 `descriptor_mismatch`，仍零 spawn。
- v2 插件收到 `v≠2` 时 exit 3 `protocol_version_unsupported`；新 host 不会发这种组合。

### 5.2 v2 `output` envelope

外层保持 SQL 已接受的形状：

```json
{"status":"ok|error","output":{},"usage":{"wall_ms":0}}
```

`usage` 仍只允许 `wall_ms`（`48_loop.sql:1390-1405`）；**不要**往 `usage` 加 tokens/bytes，否则会被判 `invalid_outcome`。需要字节/页数信息时放 `value` 或 `meta`。

v2 `output` 是判别式，不是四字段带 null：

**成功**（`class=success`, `status=ok`）：

```json
{
  "value": {"path": "README.md", "text": "..."},
  "content": [{"type":"text","text":"..."}],
  "meta": {}
}
```

（示例只示意 envelope；实际 `value` 必须满足该工具的 `output_schema`。）

- 必填 `value`、`content`；可选 `meta`；禁止 `error`。
- `content` 是 1..16 个 text block；block 恰为 `{type,text}`；`text` 可为空。
- `meta` 是 object，不进入模型文本；缺省视为 `{}`。

**普通工具失败**（`class=failure`, `status=error`）：

```json
{
  "error": {"code":"invalid_tool_arguments","message":"$.path: required"},
  "content": [{"type":"text","text":"Error [invalid_tool_arguments]: $.path: required"}],
  "meta": {}
}
```

- 必填 `error`、`content`；可选 `meta`；禁止 `value`。
- `error` 恰为 `{code,message}`；`message` 是模型可见诊断，必须无绝对路径。

**协议/执行不确定**（`class=unknown`, `status=error`）：

```json
{"error":{"code":"timeout","message":"tool process exceeded its deadline"}}
```

- 只允许 `error`；禁止 `value/content/meta`。
- 不生成模型 continuation；run 仍按现有 unknown wall 处理。

**映射表**：

| 情况 | class | status | output | 是否 spawn |
|---|---|---|---|---|
| args 非 object / schema 不通过 / 超 `max_args_bytes` | failure | error | `{error:{code:"invalid_tool_arguments",message},content:[text]}` | **否** |
| 未批准 / pin 不符 / artifact 不符 / workspace 不可用 / lease 不足 | failure | error | `{error:{code:<host reason>,message},content:[text]}` | **否** |
| 插件 exit 3 合法错误帧 | failure | error | `{error:{code,message},content:[text]}` | 是，已 reap |
| success frame，但 `value` 不符合 `output_schema` | failure | error | `{error:{code:"invalid_tool_output"},content:[text]}` | 是 |
| renderer 抛错 / 返回非法 content | failure | error | `{error:{code:"render_failed" 或 "invalid_tool_content"},content:[text]}` | 是 |
| `value`/`content`/`meta` 超语义上限 | failure | error | `{error:{code:"output_too_large"},content:[text]}` | 是 |
| 合法 success frame + 合法 value + 合法 render | success | ok | `{value,content,meta?}` | 是 |
| EOF / 坏帧 / 额外帧 / 超 transport / timeout / 异常 exit | unknown | error | `{error:{code:<line_json reason>}}` | 是，已 kill+reap |
| host 内部未分类异常 | unknown | error | `{error:{code:"tool_executor_error"}}` | 视阶段 |

`output.error.code` 不进入 `v24.error_v1` 的 24 码闭集；24 码只描述 effect 级错误（`30_advance.sql:19-37`）。tool 级 code 是 host/tool 词汇。

### 5.3 Renderer

`render` 是 host-owned 的纯函数，不是插件上传的代码，也不是 SQL callback。

```python
@dataclass(frozen=True)
class RendererRef:
    id: str
    version: int
    digest: str

@dataclass(frozen=True)
class Renderer:
    ref: RendererRef
    projection: int
    fn: Callable[[dict, object], tuple[list[dict], dict]]
```

- `RendererRegistry` 在 host 启动时构造，之后不可注册新 renderer。
- `render.digest = sha256(compact_json({"id","version","projection","golden_digest"}))`。这里用 compact sorted JSON 即可；它不是 descriptor digest，不需要 PG 形式。`golden_digest` 是 `renderers.py` 内嵌的 golden cases（`args`/`value` → `content`/`meta`，与 `v24/s13/vectors/renderers.json` 逐字节相同）的 canonical JSON sha256；行为变化必须提升 `version` 并更新 golden/digest，单纯改注释或重构不改变它。
- v1 的三个 renderer 与 descriptor 由同一 host 代码生成；第三方插件只能引用 host 发布的 renderer manifest（id/version/digest），审批时校验，不能自行上传 renderer。
- `ApprovedPlugin.__post_init__` 要求 descriptor 的 `render` 三元组与 registry entry 全等；不等则 `renderer_not_approved` / `renderer_digest_mismatch`，零 spawn。
- renderer 输入是已校验的 `args` 与 `value`；不得访问 DB、文件系统、网络、时钟、随机数。
- 返回 `(content, meta)`；host 校验 content block 形状、数量、`max_content_bytes`、`max_meta_bytes`。三个内建工具的精确投影与插件预算计数合同见 §5.3.1；插件不发送 content，最终渲染仍只由 host 执行。
- renderer 抛错 → `render_failed`；返回非法 block → `invalid_tool_content`；超限 → `output_too_large`。三者都是普通 failure，不是 unknown。

**为什么不是 `sha256(inspect.getsource(fn))`**：注释、格式化、Python 版本都会改源码字节，导致一次无行为变化的 refactor 把所有 pin 的 render digest 打翻。绑 renderer manifest（id/version/projection/golden_digest）能把“投影合同”和“实现文件”分开：golden cases 变了才换 digest，重构不换。

**v1**：`render=None`，走原 `canonical_json(output)`；不经过 renderer。

### 5.3.1 Q5：全域投影与精确预算计数

本节是三个内建 renderer 的规范算法；manifest/golden 必须绑定本节，不能只绑定若干示例。插件可独立实现该语法的 **byte counter**，不调用 host、不上传 renderer、不发送 content，也不新增 frame 字段。审批的单文件插件内固定相同 renderer 合同与 §6 的 limits（40960/41984/4096）；合同或 limits 不匹配不得批准。任意第三方 renderer 不自动取得本证明。

定义 `J(x)` 为本节预算投影专用的 deterministic compact UTF-8 JSON bytes：对象键按 UTF-8 无符号字节字典序，数组保序，无空白/BOM/尾 LF；字符串转义逐项采用 §4.2 Canonical descriptor 与 digest 的规则 3（包括小写 `\u00xx`），其余 Unicode scalar 原样 UTF-8。该引用只复用字符串转义拼写，不复用 descriptor 的键排序或空格规则；本节定义的 compact 形式是 `J` 的唯一序列化规则，不改变 §4.2 descriptor digest authority。整数为无前导零的十进制，零为 `0`；bool/null 用 JSON 字面量。`D(n)` 为数学整数的十进制文本；求和与游标试算先用数学整数，写入 JSON number 的字段/游标必须仍是安全整数，纯文本中的派生数（如 skipped 六项和）可以超过该范围。`E(s)=len(J(s))-2`（不含字符串引号）。`+` 表示文本拼接，`join` 只在相邻元素间放分隔符。

对每一个通过 §3.1 数值/Unicode 规则和该工具 output schema 的 value（包括字段关系不一致的 value），投影均有定义且不读取 args：

- read：若 `total_lines=0`，`T="[empty file]"`，否则 `T=text`；若 `truncated=true`，再追加 `"\n\n[Showing lines "+D(start_line)+"-"+D(end_line)+" of "+D(total_lines)+". Use offset="+D(next_offset)+" to continue.]"`。这里以及下面的可空字段在 schema-valid 但语义不一致时，null 文本固定为 `"null"`，不抛错。
- list：每 entry 依 kind 生成 `path+"/"`、`path+"@"` 或 `path+" ("+D(size)+" B)"`；空 entries 的正文为 `"[empty directory]"`，否则用 `"\n"` join。若 `truncated=true`，追加 `"\n\n[Showing "+D(offset)+"-"+D(offset+len(entries)-1)+" of "+D(total)+". Use offset="+D(next_offset)+" to continue.]"`。
- search：每 hit 按 before 数组原序、hit、after 数组原序生成行。context 行为 `hit.path+"-"+D(context.line)+"- "+context.text`，hit 行为 `path+":"+D(line)+":"+D(column)+": "+text`；missing/empty before/after 都生成零行。所有行用 `"\n"` join；零 hits 的正文为 `"[no matches]"`。正文后恒追加 `"\n\n[hits "+A+"-"+B+" of "+N+"; scanned "+D(scanned_files)+"; skipped "+D(K)+"]"`，非空时 `A=D(offset), B=D(offset+len(hits)-1)`，空时 `A=B="0"`；`N=D(total)`，仅 `complete=false` 时追加 `"+"`；`K` 是六个 skipped 计数的数学和。若 `truncated=true` 再追加 `"\n[Use offset="+D(next_offset)+" to continue.]"`。text/context 即使含 LF、CR、NUL、引号、反斜杠、U+2028/U+2029，也原样拼入 T，不做第二次截断或转义。

三者统一返回 `content=[{"type":"text","text":T}]`，无合成尾 LF（输入 text 自带的 LF 保留），`meta={}`。这是总投影，不代表字段关系不一致的 value 可以作为工具成功页。插件 invoke result 的 meta 只能缺省或显式 `{}`；host 在 render 前拒绝非空 meta 为 `invalid_tool_output`，不合并/覆盖两个 meta 来源。最终 meta 唯一来自 renderer 的 `{}`；缺省 wire meta 不要求注入。

**精确长度恒等式**：`len(J(content)) = 27 + E(T)`，`len(J(meta))=2`。插件按上述 token 序列累加 `E`（包括全部重复 path、context、分隔符、数字、续页标记），不必创建 T；因为 JSON 字符串转义逐 scalar 可加，`E(x+y)=E(x)+E(y)`，故计数与 host 的完整 content array 序列化逐字节长度相同。不存在 value→content 的 dominance 假设。host 仍独立 render、校验并执行预算；不信任插件计数。

### 5.4 模型文本与 worker 接口

`PluginDispatcher.tool_handler` 现在返回 `(class, result)`；改为可返回：

```python
{
  "class": "success" | "failure" | "unknown",
  "result": {"status": "...", "output": {...}, "usage": {"wall_ms": ...}},
  "model_text": "<模型可见文本>"
}
```

`_call_tool_handler`（`worker.py:1302`）兼容三种返回：

1. 2-tuple `(class, result)` → `model_text = canonical_json(result["output"])`。
2. dict `{class,result}` → 同上。
3. dict `{class,result,model_text}` → 用给定的 `model_text`。

`worker._execute_tool` 只用 `model_text` 构造 `tool_message.content`；journal 事件类型、字段、顺序都不变。

- v1 dispatcher 显式设置 `model_text = canonical_json(result["output"])`，与当前 `worker.py:1066-1071` 逐字节相同。
- v2 dispatcher 设置 `model_text = "\n".join(block["text"] for block in content)`。
- 重启后只重放 journal 里的 `tool_message`，**不重新 render**；renderer 变化不能改写已结算 run 的模型文本。

### 5.5 封闭 JSON Schema 子集

校验器只在 host（Python）执行；插件不各自实现 validator。关键字白名单：

| 关键字 | 允许值 / 语义 |
|---|---|
| `type` | 单个字符串，或 2..4 个互异字符串的数组；取值只能是 `object`、`array`、`string`、`integer`、`boolean`、`null` |
| `properties` | object: name → schema |
| `required` | 无重复 string 数组；成员必须在 `properties` 中 |
| `additionalProperties` | 只允许 boolean；每个 object schema 必须显式写 |
| `items` | 单个 schema；`type:"array"` 时必须写 |
| `minItems` / `maxItems` | 非负安全整数；仅 array |
| `minLength` / `maxLength` | 非负安全整数；按 Unicode scalar 计数；仅 string |
| `minimum` / `maximum` | 安全整数；仅 integer |
| `enum` | 1..64 个 JSON-distinct 值；可为 null |
| `description` | string；不参与校验 |

**禁止**：`$ref`、`$defs`、`definitions`、`$schema`、`$id`、`oneOf`、`anyOf`、`allOf`、`not`、`if/then/else`、`pattern`、`format`、`default`、`const`、`number`、`patternProperties`、`propertyNames`、`uniqueItems`、`minProperties`、`maxProperties`、`exclusiveMinimum`、`exclusiveMaximum`、`multipleOf`、`contentEncoding`、`readOnly`、`writeOnly`、`examples`。

- `type` 为数组时，`minimum`/`maxLength`/`items` 等约束只作用于匹配的实例类型；`null` 不参与这些约束。

边界：

- schema 深度 ≤16；节点 ≤256；`properties` ≤128；`enum` ≤64。
- `parameters` 根必须 `type:"object"` 且 `additionalProperties:false`。
- `output_schema` 可以是 `{}`（任意 JSON），但三个 v1 工具都用具体 object schema。
- 不允许 `default`：默认值只写在 `description`，由插件执行；host 不改写 args。这样模型看到的 args 与实际执行的 args 不会分叉。
- 校验失败只返回稳定 code + `$` 路径，不把整份 args/value 写进模型文本或日志。

**校验顺序**：

1. descriptor 关闭集 / 大小 / 数值 / Unicode。
2. schema 子集自身合法。
3. render 三元组在 registry 中存在且 digest 全等。
4. 深冻结并缓存 validator。
5. 调用时：args 大小 → parameters schema → pin/artifact/workspace/lease → spawn → frame → value 大小 → output schema → 内建工具 meta/成功页字段关系（§5.3.1/§5.6）→ render → content/meta 大小 → journal/settle。

### 5.6 截断、分页与 64 KiB

- transport 硬上限：stdout 65536 bytes（含末 LF）、stderr 16384 bytes、stdin 1 MiB（`process_io.py:19-21`）。
- 语义计量域分别为 `len(J(value))`、`len(J(完整 content array))`、`len(J(meta))`；不计外层 output。三个内建工具的上限分别为 40960 / 41984 / 4096；args 是单独的 `len(J(args))`，不含 frame/LF，host 不注入默认值。descriptor 的 `max_meta_bytes` 范围为 2..16384；缺省 meta 仅计量时视为 `{}`，为 2 bytes，因此缺省与显式 `{}` 均可通过最低预算。
- 插件自己分页；实际发出的成功帧固定为 `J({"ok":true,"v":2,"result":{"value":V}})+LF`（省略 meta），逐字节计量并要求 ≤60000 bytes。60001..65536 超内建目标，但 transport 本身不因此判 unknown；>65536 才是 `stdout_limit` unknown。host 不截断、不改 value；任何组件超语义上限仍为普通 failure `output_too_large`。

**有限候选算法（Q5，§5.3.1 为唯一投影语法）**：

1. 固定本次扫描观察到的有序完整项及统计快照；完整项为 read 行（含空行）、list entry、search hit 连同其全部 before/after。read 先用字节扫描取得 total/final_newline，最多取从 offset 起的 limit 行；list 完整过滤/排序/计 total 后最多取 limit 项。路径、源文件/目录上限等原有失败先处理；read 试算某前缀时只解码该前缀，并要求其每行≤16384 UTF-8 bytes，窗口外坏 UTF-8/超长行不使本页失败。不可拆分 item。
2. search 从头无状态重扫，数过 offset−1 个 hit 后收集最多 limit 个候选 hit，并继续到 EOF、扫描预算耗尽，或完整观察到第 offset+limit 个 hit（该 hit 是 look-ahead sentinel，不是本页候选）三者中首次发生处冻结快照；同一边界已确认 EOF 优先。若 offset+limit 超安全整数，则用数学整数比较，绝不把不安全数写入 value/cursor。完整 hit/context 构造完才算观察到该 hit；未完成的 item 不计入快照。EOF 则 complete=true，否则 false；total 为这次快照已发现的所有 hit 数（包括 offset 前及 sentinel），scanned/skipped 也固定于此处，不因候选长度改变。固定快照上的分页/计数是确定的；12s 截止本身随运行时变化，不声称同一文件树必有相同 cutoff。
3. 若有 m 个可返回项，枚举 **每个** `k=1..min(limit,m)` 的前缀，先填完候选 V 的所有字段再计量。read 的 start=offset、end=offset+k−1；list/search 的 offset 保持请求值。read/list 的 truncated 当且仅当还有未返回项；search 的 truncated 当且仅当 `complete=false` 或 `offset+k−1<total`。truncated 时 next_offset=offset+k，否则 null。read 的 truncated_by：不截断为 null；截断且 k=limit 为 `"lines"`，否则 `"bytes"`。不得用估计 footer、前一候选的 total/cursor 或扫描中的临时统计计量。
4. 候选须同时满足 schema、上述字段关系、所有输出整数安全，以及 value/content/meta/frame 四个预算；content/meta 用 §5.3.1 精确计数。选满足条件的最大 k；**不假设长度单调、不 binary-search、不在第一个失败前缀就停止**。search 在扫描预算耗尽且未到 EOF 时，只有所选 k=m=limit（count-full），或所选 k<m（已观察到不适配的完整下一候选；sentinel 也可证明 page 后尚有 hit）才算页已填满；否则返回 `search_scope_too_large`。到达 offset+limit sentinel 同样可证明本页有后续 hit。由此 cutoff 不会返回不足 limit 且没有后续证据的 incomplete 页。
5. 没有适配的非空前缀时，不伪造空成功页：若首行违反 UTF-8/16384-byte 行上限，分别返回 `not_utf8`/`line_too_long`；否则在合法的 cursor/统计范围内返回 `line_too_long` / `entry_too_large` / `hit_too_large`（完整项连同必需 envelope/footer 不适配）。该结论必须在枚举全部终结候选后作出：最后一页移除 footer 可能使更长前缀重新适配。无法形成安全整数 cursor/统计或字段关系不一致为 `invalid_tool_output`，不是成功页。search 若因扫描预算尚未发现 offset 处的项，返回 `search_scope_too_large`。
6. m=0 只允许真实空且完整的集合在 offset=1 成功；read 空文件、list 空目录、search complete=true/total=0 生成各自规范空 V 并照样检查四预算，不适配为 `output_too_large`。完整非空集合 offset 越界，以及空集合 offset>1，均 `offset_out_of_range`。判定次序固定为：源错误/非法统计或整数→m=0 分支→无适配前缀的 item 错误→search 扫描预算未填满→成功；不借后续分支掩盖前一失败。

**成功页的字段关系（host 在 render 前验证，矛盾为 `invalid_tool_output`）**：read 空文件采用 §6.2 的唯一形状；非空时 start_line 等于请求 offset，`1≤start_line≤end_line≤total_lines`，`k=end_line−start_line+1≤limit`，text 按 LF 分割恰有 k 行、每行≤16384 UTF-8 bytes；list/search 的 offset 等于请求 offset，`k=len(entries/hits)≤limit`，非空时 `offset+k−1≤total`。三者 truncated/next_offset 与第3步的公式全等，read truncated_by 也全等；只有真实空集合允许 k=0。list 非 file 的 size 必须为 null、file 必须为整数；search 不允许 complete=false/k=0。这里“真实”指 value 宣称的 total/complete 与这些关系一致；host 不重扫文件系统来认证来源。任何 schema-valid 但关系矛盾的 value 都走上述普通失败，而非修补/改写；§5.3.1 的投影与精确计数仍在整个 schema-valid 域有定义。

**不变量与终止证明**：有限项/有限 scalar 串上的投影和枚举总会终止；read≤2000、list≤500、search≤200 个候选（另至多一个 look-ahead sentinel，不进入 value.hits）。选中的 V 与计数的 V 完全相同，所以 `len(J(content))=27+E(T)≤41984`、meta=2≤4096、value≤40960、实际 frame≤60000<65536，host 无须改变页。每个成功的不完整页都有 k≥1 和安全整数 `next_offset=offset+k>offset`；空成功页一定完整且 cursor=null。对稳定、有限来源，这个 rank 严格增加；scan/error 可终止遍历，不承诺任意 search 都能跨扫描预算穷尽。失败和 schema-valid 但矛盾的值都有显式分支，因此不是只对常见短路径/200-hit 示例的证明。

插件不发送计数或 content；最终渲染、所有检查与失败分类仍由 host 掌握。无 RPC、spill store、host cursor、callback/new field 或 SQL/kernel 改动。host 对不合规/恶意插件继续独立 fail closed；本证明只保证遵守已批准合同的插件所发成功页。

---

## 6. 三个工具的合同

### 6.1 共享路径、编码、排序规则

1. `workspace_root` 只来自 approved registry；v2 plugin 在 `environment()` 中注入 `V24_WORKSPACE_ROOT`，模型不能提供 cwd/root/argv/env。
2. `path` 是 string，1..1024 UTF-8 bytes，无 NUL；绝对路径必须在 root 内，命中则剥成相对路径；相对路径从 root 解析。
3. 词法：按 `/` 切分，丢弃空段与 `.`；出现任何 `..` 一律 `path_escape`（不做词法消解，即使结果仍在 root 内）。
4. 任一组件等于 `.git` 一律 `path_excluded`；`include_hidden=false` 时跳过以 `.` 开头的组件，但 root 自身除外。
5. symlink：从 root 向下逐组件 `lstat`；目标路径任一组件是 symlink → `symlink_denied`；遍历中遇到 symlink → 跳过并计数，不跟随。
6. 只接受严格 UTF-8；read 的前 8192 bytes 含 NUL → `binary_file`；list/search 中非 UTF-8 文件名不进输出，只计数。
7. `list` 的排序键是相对 POSIX path 的 UTF-8 bytes；`search` 的遍历顺序是 DFS 前序（同层兄弟按 name 的 UTF-8 bytes），再按 line、column。两者都不用 locale，不做 NFC/NFD。
8. 路径错误消息只用相对路径；不得把真实绝对路径或 errno 文本直接回给模型。
9. 静态 symlink 检查与打开之间仍有 TOCTOU 窗口；v1 把 workspace 视为受信、非并发敌手，sandbox 另立设计（§9）。

### 6.2 `read`（Python）

| 项 | 合同 |
|---|---|
| key | `read` |
| language | Python，单文件 `v24/s13/plugins/fs_read.py` |
| parameters | `path` 必填 string 1..1024；`offset` integer ≥1 默认 1；`limit` integer 1..2000 默认 2000 |
| output | `{path,text,start_line,end_line,total_lines,final_newline,truncated,truncated_by,next_offset}` |
| render | `v24.fs.read.text` v1 |
| limits | timeout 5000；args 16384；value 40960；content 41984；meta 4096 |
| annotations | read_only=true, destructive=false, idempotent=true, open_world=false |
| 错误码 | `invalid_path,path_escape,path_excluded,symlink_denied,not_found,permission_denied,not_a_file,binary_file,not_utf8,file_too_large,offset_out_of_range,line_too_long,io_error,root_unavailable` |

语义：

- 只按 `\n` 切行；`\r` 保留在行内；文末 `\n` 不产生额外空行；空文件 0 行。
- `text` 是选中行用 `\n` 连接，不加合成尾换行；`final_newline` 表示整个文件最后字节是否为 `\n`。
- 空文件：`total_lines=0,start_line=0,end_line=0,text="",final_newline=false,truncated=false,truncated_by=null,next_offset=null`；`offset=1` 合法，`offset>1` 为 `offset_out_of_range`。
- 非空文件 `offset>total_lines` → `offset_out_of_range`。
- 按 §5.6 的终结候选算法同时检查 value/content/meta/frame；还有后续行时 `truncated=true,next_offset=end_line+1`，否则 false/null。`truncated_by` 按 §5.6 固定为 lines/bytes/null；limit 是上限。
- 单行 UTF-8 bytes > 16384 → `line_too_long`，不返回半行。
- 文件 >1 MiB → `file_too_large`；`total_lines` 用字节扫描计数，不把整个文件读进内存。
- 选中窗口严格 UTF-8 解码；失败 → `not_utf8`（窗口外的坏字节不影响本页）。
- content：`text`；空文件 `[empty file]`；分页时追加 `\n\n[Showing lines S-E of T. Use offset=N to continue.]`。

### 6.3 `list` 与 `search`（同一 Node install）

一个 install `v24.fs.node`，manifest `provides` 两项：`list`、`search`；同一个 `fs_tools.js` 按帧里的 `tool` 分流。这是“plugin identity ≠ tool identity”的验收点。

#### `list`

| 项 | 合同 |
|---|---|
| key | `list` |
| parameters | `path` 可选默认 `"."`；`recursive` 默认 false；`include_hidden` 默认 false；`offset` 1 基默认 1；`limit` 1..500 默认 500 |
| output | `{path,offset,entries,total,truncated,next_offset,skipped_non_utf8,skipped_special}` |
| entry | `{path,kind,size}`；`kind` ∈ `file`、`directory`、`symlink`；非 file 的 `size=null` |
| render | `v24.fs.list.text` v1 |
| limits | timeout 5000；args 16384；value 40960；content 41984；meta 4096 |
| 错误码 | `invalid_path,path_escape,path_excluded,symlink_denied,not_found,permission_denied,not_a_directory,directory_too_large,offset_out_of_range,entry_too_large,io_error,root_unavailable` |

语义：

- 非递归只列直接子项；`recursive=true` 用 DFS 列整棵子树，`entry.path` 是相对起点的 POSIX 路径。
- 排序按 `entry.path` UTF-8 bytes；先完整排序，再切 offset/limit。
- `total` 是过滤后、分页前的精确数量；扫描超过 10000 项 → `directory_too_large`，不返回假 total。
- symlink 只列 `kind=symlink`，不跟随；special file 跳过并计 `skipped_special`；非 UTF-8 名跳过并计 `skipped_non_utf8`。
- 空目录 offset=1 成功；空目录 offset>1 或非空目录 offset>total 为 `offset_out_of_range`。按 §5.6 同时检查四预算，可能少于 limit；仅还有余项时 `next_offset=offset+len(entries)`。
- content 与 meta 的完整语法为 §5.3.1（entry 间一个 LF、footer 前两个 LF、无合成尾 LF）；空目录 `[empty directory]`。

#### `search`

| 项 | 合同 |
|---|---|
| key | `search` |
| parameters | `query` 必填 string 1..512；`path` 默认 `"."`；`glob` 可选 1..256；`ignore_case` 默认 false；`context` 0..2 默认 0；`include_hidden` 默认 false；`offset` 1 基默认 1；`limit` 1..200 默认 200 |
| output | `{path,offset,hits,total,complete,scanned_files,skipped,truncated,next_offset}` |
| hit | `{path,line,column,text,text_truncated,before?,after?}`；`before/after` 是 `{line,text}` 数组 |
| skipped | `{hidden,symlink,binary,too_large,non_utf8,long_lines}`，六个 integer |
| render | `v24.fs.search.text` v1 |
| limits | timeout 15000；args 16384；value 40960；content 41984；meta 4096 |
| 错误码 | `invalid_path,path_escape,path_excluded,symlink_denied,not_found,permission_denied,not_a_directory,invalid_glob,search_scope_too_large,offset_out_of_range,hit_too_large,io_error,root_unavailable` |

语义：

- **literal-only**：`query` 是普通子串；`ignore_case` 只做 ASCII A-Z/a-z 折叠（跨语言一致）；不做 regex、不做 Unicode case folding。regex 是 deferred。
- 逐行匹配；行不含 `\n`，并剥离单个行尾 `\r`；每行只记第一个 match；`column` 是 1 基 Unicode 码点。遍历顺序是 DFS 前序（同层兄弟按 name 的 UTF-8 bytes），不是全局 path 字节序；分页按这个顺序推进。
- `glob` 只支持 `*`（不跨 `/`）、`**`（跨 `/`）、`?`（一个非 `/` 字符）；含 `{ } [ ] \` → `invalid_glob`；无 `/` 时匹配 basename，有 `/` 时匹配相对路径。
- 文件 >1 MiB → `too_large`；前 8192 bytes 含 NUL → `binary`；严格 UTF-8 失败 → `non_utf8`；行 >4096 bytes → 不匹配，计入 `skipped.long_lines`。
- 最多检查 10000 个 regular files、200 个 hit/页；扫描预算 12s（低于 15s timeout）。文件数量预算包含最终因预检而跳过的 regular files。`scanned_files` 只计通过预检并尝试 literal 匹配的文件；读取前缀、解码和行长预检不计入该字段。`skipped.hidden` 按隐藏 entry/subtree 根计一次（`.git` 无条件排除且不计 hidden）；`symlink` 按 entry；`binary/too_large/long_lines` 按跳过的文件；`non_utf8` 按非 UTF-8 名称 entry 或不可解码文件。regular file 的预检顺序固定为 size→NUL→UTF-8→4096-byte line cap，命中首个原因只计一次；任一超长行令整个文件跳过。隐藏/符号链接/非 UTF-8 名称不进入文件预检。
- `.git` 永远排除且不计入 `skipped.hidden`（与共享排除规则一致）；`include_hidden=true` 也不遍历 `.git`。
- 扫描/候选终结顺序按 §5.6；complete 只表示扫描完整，不表示所有 hit 已在本页返回。complete=true 时 total 精确，否则是快照已发现数（renderer 用 `N+`）。四预算可能让本页少于 limit；所有成功不完整页非空，`truncated=true,next_offset=offset+len(hits)`。
- 分页无状态：每次从起点重扫，按 DFS 顺序数到 `offset`；v1 接受重复扫描的 O(n²)，服务端游标/快照 deferred。
- 扫描完整且 total=0 时仅 offset=1 为空成功；完整的非空集合 offset>total 为 `offset_out_of_range`。未完整且未发现 offset 处的 hit 为 `search_scope_too_large`，不返回空 incomplete 成功页。
- 扫描预算在页未填满前耗尽 → `search_scope_too_large`；count-full / byte-full 的精确定义与失败优先次序见 §5.6。
- `hit.text` 与 context 行截到 500 码点，`text_truncated=true`；`before/after` 最多 2 行。
- content/meta 按 §5.3.1：before→hit→after 原序，path 在每个 context 行重复；summary 含 N/N+，truncated 时另有 continuation 行；无命中正文 `[no matches]` 仍有 summary。不得另加省略号或尾 LF。

### 6.4 工具面与 provider 投影

- provider 只看到 `{name:key, description, parameters}`；`output_schema/render/limits/concurrency/replay_class/annotations` 不进 provider 声明。
- `deepseek._tools` 要把 `v==1` 断言放宽为 `v in (1,2)`，并在 v2 时校验 `tool.key == pin.key`；投影字段与 v1 完全相同，所以 v1 的 provider 请求字节不变。
- 三个工具的 `parameters` 里不写 `default`；插件按 §6 的合同表执行默认值。

---

## 7. 工程落地

### 7.1 文件清单

`v24/sql/**` 零改动；以 `git diff --exit-code -- v24/sql` 为证。

| 文件 | 变更 | 职责 / 依赖 | 量级 |
|---|---|---|---:|
| `v24/host/canonical.py` | 新 | PG canonical、deep-freeze、严格 JSON（`J`/`strict_loads`/`escaped_len`）与 `RegistryError`；仅依赖标准库 | ~220 |
| `v24/host/descriptor.py` | 新 | v2 descriptor 关闭集校验、字段约束、render 身份比对、digest 重导出；依赖 `canonical`、`tool_schema`、`renderers` | ~280 |
| `v24/host/tool_schema.py` | 新 | 封闭 schema 子集（`assert_supported`/`compile_schema`/`validate`/`schema_metrics`）；依赖 `canonical` | ~320 |
| `v24/host/renderers.py` | 新 | 三个 host renderer + 不可变 registry + 21 个内嵌 golden + manifest digest；依赖 `canonical` | ~300 + 数据 |
| `v24/host/tool_results.py` | 新 | `ToolDispatchResult`、v2 envelope 构造/校验、`join_content`、预算计量与 frame 分类；依赖 `canonical` | ~220 |
| `v24/host/registry.py` | 改 | W2 把七个 canonical 名字移入 `canonical` 并 re-export；W3 再加 `ApprovedTool`、`ApprovedPlugin`、共享 mixin、registry union、`match_tool`、`environment()`；v1 `ApprovedAdapter`/`match_pin` 不动 | W2 −93/+9；W3 +200/−20 |
| `v24/host/line_json.py` | 改 | v2 build/parse；`run(entry, operation, reservation, args, tool=None)`；v1 解析器原样 | +150 |
| `v24/host/plugins.py` | 改 | v2 分支：match_tool → args 预校验 → lease → invoke → value 校验 → render → envelope；v1 分支原样 | +170 |
| `v24/host/worker.py` | 改 | `_call_tool_handler` 接受 `model_text`；`_execute_tool` 用它；lease 逻辑不动 | +40 |
| `v24/host/deepseek.py` | 改 | `_tools` 接受 `v in (1,2)`，v2 校验 `tool.key==pin.key`；投影不变 | +15 |
| `v24/s13/plugins/fs_read.py` | 新 | Python `read` 单文件插件（prepare/invoke/release/inspect） | ~320 |
| `v24/s13/plugins/fs_tools.js` | 新 | Node `list` + `search` 单文件插件；按 frame `tool` 分流 | ~520 |
| `v24/s13/fixtures.py` | 新 | 工作区树、v2 manifest/descriptor、`ApprovedPlugin` 构造、复用 s11 `PluginHarness` | ~280 |
| `v24/s13/vectors/*.json` | 新 | descriptor/frame/工具契约的固定期望 bytes、sha256、renderer golden cases、负例 | 数据 |
| `v24/s13/test_descriptor.py` | 新 | descriptor-only：canonical 向量、关闭集、limits/description/key 边界、render 身份、四 reason、strict parse | ~300 |
| `v24/s13/test_schema.py` | 新 | 13 allow / 29 deny / 13 invalid-allowed、结构边界、first-error 顺序、path、enum distinct | ~260 |
| `v24/s13/test_renderers.py` | 新 | 21 个 golden 的 content/meta/measures、三组 digest、registry 身份 | ~260 |
| `v24/s13/test_results.py` | 新 | 8 个 M2 case、envelope bytes、9 行 boundary、4 行 frame | ~200 |
| `v24/s13/test_registry.py` | 新 | 多工具匹配、五字段、protocol、workspace、tamper、零 spawn | ~300 |
| `v24/s13/test_line_json.py` | 新 | v1 golden、v2 帧/解析/unknown 矩阵 | ~300 |
| `v24/s13/test_tools.py` | 新 | read/list/search 文件系统边界与分页 golden | ~550 |
| `v24/s13/test_lifecycle.py` | 新 | 全生命周期、mixed batch、invalid args/output、render failure、timeout、tamper、crash、legacy | ~480 |
| `v24/s13/test_node.py` | 新 | Node 合同 + 生命周期；Node 缺失 SKIP exit 2 | ~160 |
| `v24/s13/README.md` | 新 | 命令、三态、extension-check 声明、非 closeout | ~150 |
| `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md` | 新 | 本文 | — |
| `docs/designs/v24-pg-agent-2026-10-22.md` | 改 | §5.1/§5.4 的 v1 描述加“v2 host 校验”注记 | ~10 |
| `docs/reviews/v24-deviation-ledger-2026-10-23.md` | 改 | 新增 `D-S13-*`：host-only schema、replay_class 无行为、journal 权威不变 | ~30 |
| `docs/reviews/v24-conformance-matrix-2026-10-23.md` | 改 | s13 extension checks；closeout 11/11 不变 | ~30 |

s13 的 `fixtures.py` 复用 `v24/s1/setup_db.py`（通过 `sys.path`）与 `v24/s11` 的 `PluginHarness`；不复制生命周期驱动。

**不新增**：`v24/sql/**`、第 11 张表、新的 effect kind、新的 journal 事件类型、新的 claim/queue/recovery、新的 session/spawn 表。

### 7.2 v1 兼容与迁移

- v1 install 不迁移：manifest/descriptor/adapter digest 原样；`ApprovedAdapter`、`match_pin`、`line_json` v1 解析器、`worker` 的 `canonical_json(output)` 路径全部保留。
- v2 是新 install：新 identity/version/adapter digest；旧 host 因五字段不匹配 `adapter_not_approved`，零 spawn。
- v1 回滚：删掉 v2 registry 项即可；已存在的 v2 install 先用新 host `dispose` 排空，再回滚。旧 host 对 v2 install 的 `host_release` 会 `adapter_not_approved`，硬回滚会卡在 `dispose_pending`——所以“先排空再回滚”是硬条件。
- provider 字节：改动前录制 s11 echo 的 `ScriptedTransport.calls[].body` 与 tool message 作为 golden；改动后逐字节比对。任何差异都回退。
- v2 工具不接受 v1 帧；v1 工具不接受 v2 帧。协议由 registry 静态决定，不做运行时探测。

### 7.3 测试矩阵

| 测试 | 关键断言 |
|---|---|
| `test_descriptor.py` | V1/V2/`{}` 的 bytes+sha256 三方一致；descriptor 关闭集多/少键拒绝；浮点/孤立代理项/超 16 KiB 拒绝；render id/digest 不匹配拒绝；annotations 一致性；四 reason 封闭；strict parse（重复键/`NaN`/非法 UTF-8/非 object）；深嵌套与超长整数字面量 → `invalid_descriptor` |
| `test_schema.py` | 13 allow / 29 deny / 13 invalid-allowed；nullable union；required/additional/items；JSON-distinct enum；depth/nodes/properties/enum 上限；Unicode-scalar 长度；根 parameters/output；first-error/path 顺序；无 default 注入；无 `type` 的 object-shaped 须显式 `additionalProperties`，裸 `{}` 仍合法 |
| `test_renderers.py` | 21 个内嵌 golden 与向量五键逐项相等；content/meta/measures 逐字节；`27+E(T)`；三组 golden/render digest；registry 不可变、未知 ref、renderer 抛错、非法 content；21 个 golden 逐例比对生产 `measure`；`fn` 自抛 `RendererError` → `render_failed`；非 `J` 域 content/meta → `invalid_tool_content` |
| `test_results.py` | success/failure/unknown envelope 逐字节；usage 三行；11-byte model_text 与 meta 排除；builtin meta 三态；9 行 cap−1/cap/cap+1；4 个 frame boundary；prefix candidate 复现；不实现 `page_decision`；`J` 值域负例、有限深值与循环容器；`ToolDispatchResult` 外层三键/class-status/usage 错配 |
| `test_registry.py` | v1 `.descriptor` 字节不变；v2 多工具 key 唯一；混用 v1/v2 拒绝；`tool.key != provide.key` 拒绝；`timeout > cap` 拒绝；workspace root 缺失/symlink 拒绝；`match_tool` 的 key/pin/bytes/digest/artifact 五类失败都零 spawn；`match_pin(v2)` 抛 `protocol_mismatch` |
| `test_line_json.py` | v1 四操作请求/成功/失败/unknown 的 golden bytes 不变；v2 invoke 带 `tool`；prepare/release/inspect 不带 `tool`；缺 LF/多帧/坏 JSON/重复键/NaN/超 stdout/超 stderr/timeout → unknown；v1/v2 解析器互不串线 |
| `test_tools.py` | read 空文件/尾换行/offset 越界/Unicode/binary/超长行/1 MiB/符号链接/`.git`/continuation 收敛；list 排序/递归/hidden/`.git`/symlink/special/非 UTF-8/offset/total；search literal/case/glob/context/上限/二进制跳过/column 码点/`complete`/`total` |
| `test_lifecycle.py` | **G12-A**：Python read + Node list/search 两个 install，三 key start，真实子进程，完整生命周期；**G12-B**：同一 model batch 三个 tool，屏障后恰一个 continuation，list/search 的 pin 指向同一 install；**G12-C**：非法 args 零 spawn（进程计数）；**G12-D**：非法 output/render 失败；**G12-E**：timeout → unknown + blocked；**G12-F**：artifact/descriptor/digest 篡改零 spawn；**G12-G**：`dispatch_finished` 后崩溃，重启重交，不二次 spawn、不二次 receipt；**G12-H**：剩余 lease 不足 → failure 零 spawn；**G12-L**：legacy echo provider/tool-message 字节不变 |
| `test_node.py` | Node 合同与生命周期；Node 缺失 → `[SKIP]` exit 2，不算通过 |
| 回归 | `v24/s10/test_g9.py`、`v24/s11/test_g10.py`、`v24/s11/test_node.py --node`、`python -m v24.host.plugin_smoke --multilingual-smoke`、11 条 closeout |

### 7.4 Gate 与 done-when

```bash
uv run python v24/s13/test_descriptor.py
uv run python v24/s13/test_schema.py
uv run python v24/s13/test_renderers.py
uv run python v24/s13/test_results.py
uv run python v24/s13/test_registry.py
uv run python v24/s13/test_line_json.py
uv run python v24/s13/test_tools.py
uv run python v24/s13/test_lifecycle.py
uv run python v24/s13/test_node.py --node

# 回归（不得因 v2 改动而红）
uv run python v24/s10/test_g9.py
uv run python v24/s11/test_g10.py
uv run python v24/s11/test_node.py --node
uv run python -m v24.host.plugin_smoke --multilingual-smoke

git diff --exit-code -- v24/sql
```

三态规则同 s11：exit 0 通过；exit 2 = 未验证（不算通过）；exit 1 失败。

Done-when：

1. W2 覆盖九个 s13 gate 中的四个（`test_descriptor.py`、`test_schema.py`、`test_renderers.py`、`test_results.py`）且全部 exit 0；`test_registry.py`、`test_line_json.py`、`test_tools.py`、`test_lifecycle.py`、`test_node.py` 仍归 W3/W4。上述 s13 九条全部 exit 0；Node 缺失时 `test_node.py` 必须 SKIP exit 2，不能记为通过。
2. 真实 install→prepare→activate→start→model→tool→continuation→final→off→dispose→release→scope close 跑通，Python 与 Node 都是真子进程。
3. 一个 Node install 同时提供 `list` + `search`；一次 start 的 requires 同时包含三个 key。
4. 同一 model batch 的三个 tool 只产生一个 continuation。
5. 所有非法 args/tamper 用例证明零 spawn（进程计数，不以 journal 事件计数）。
6. legacy echo 的 provider 请求体、descriptor bytes、tool message 逐字节等于基线。
7. `v24/sql/**` 零 diff；不打开网络、不接真实 provider。
8. closeout 仍 11/11；s13 不被称为第 12 条 closeout。

### 7.5 必须同步的文档修订

实现落地时，以下文档必须同一次改动更新，否则就是新的 documented≠implemented：

1. `docs/designs/v24-pg-agent-2026-10-22.md` §5.1（`:275`）：现在写“DB 与 host 均不按该 schema 校验参数内容”。改为“v1 仍只做形状校验；v2 descriptor 由 host 执行封闭子集，DB 仍只做形状校验”。
2. 同文件 §5.4（`:297`）：tool result 现在只描述 `{status,output,usage}` 形状；补一句 v2 的 `output` 判别式 envelope。
3. `docs/investigations/v24-drift-factcheck-2026-10-29.md`：D2 增加“v2 host 校验”；D3 重申“replay_class 只是声明，successor 仍 no_replay”；D4 重申 journal 仍是 transcript 权威。
4. `docs/reviews/v24-deviation-ledger-2026-10-23.md`：新增 s13 条目。
5. `docs/reviews/v24-conformance-matrix-2026-10-23.md`：新增 s13 小节，closeout 计数不变。

---

## 8. Kernel revision required（不在 v1）

### 8.1 只读工具的 `replay_safe`

如果要求“只读工具在 claim 后、settlement 前宿主崩溃/lease 过期时自动重投”，最小改动必须原子完成：

1. `48_loop.sql:1133`：tool successor 不再硬编码 `no_replay`，而是从**已冻结 pin descriptor** 读取经验证的 replay 合同。
2. `48_loop.sql:2650-2651`：successor 校验闭集接受该合同。
3. `48_loop.sql:2963`：applier 同步接受并复核。
4. `49_recovery.sql:351-375`：允许闭集内的 `replay_safe + tool_call` `reset_ready`；其余仍 unknown。
5. 明确 reservation 仍是 `v24:tool_call:<effect_id>`；重投不得产生第二业务副作用。
6. 更新设计 §B.4、G2b successor 断言、G5 crash/restart、G7 recovery、conformance matrix、deviation ledger。

**不做的后果**：v1 的 `replay_class="read_only"` 只是声明；任何 tool lease 过期仍转 unknown 并阻断 run。host 自行重投即协议违规。

### 8.2 K1：transcript 派生

如果要把 provider 对话原文从 journal 迁进 DB，需要：

- model outcome 增加可选 `assistant`（`content`、`reasoning_content`、`tool_calls[{provider_id,arguments,key,args}]`）；
- tool outcome 的 `output` 采用 `{value,content,meta}`，其中 `content` 是模型可见文本；
- 只读 `v24.derive_model_messages(run_id)` 从 effect/outcome 重建；
- host `_history`/`_parent_tool_call` 改读 DB；
- 验收：删掉 journal 后跑同一步，provider request 字节一致。

这不加第 11 张表，但改 SQL 与 host，属于独立 spec revision；本轮不做。

### 8.3 `dispatch_started` 前移

现在 `worker._execute_tool` 在调用 `tool_handler` **之前**写 `dispatch_started`（`worker.py:1040-1050`）。因此 pre-spawn 失败也会留下该事件；若 host 在 preflight 窗口崩溃，recovery 会把一个“从未 spawn”的只读调用判成 unknown。

v1 接受这个保守结果，并明确：**“零 spawn”以进程计数为准，不以 journal 事件为准**。如果要修，新增 `tool_preflight` 钩子，在 `dispatch_started` 之前完成 install/pin/args/artifact/lease 检查；这是 host 修订，不是 SQL 修订。本文不把它混进 v1。

---

## 9. 风险与退出条件

| # | 风险 | 触发条件 | 处置 |
|---|---|---|---|
| 1 | 多 `provides` 激活未实测 | G12-A 只建出一个 slot，或第二个 pin 缺失 | **停**：要么拆成两个 install（违背任务书“一个 Node install 两个工具”），要么走 kernel revision；二选一必须回设计 |
| 2 | `deepseek._tools` 放宽 v2 后 v1 字节变化 | legacy golden 不一致 | **停**：回退 `_tools` 改动，先证明 v1 投影不变 |
| 3 | v2 帧在真实 fixture 超 64 KiB | `stdout_limit` unknown | **停**：缩小页/预算；禁止抬高 transport 上限 |
| 4 | `dispatch_started` 假 unknown | 崩溃窗口测试命中 | v1 记录为已知限制；不在 host 里偷重投 |
| 5 | Node 无 `openat` 的 TOCTOU | 恶意并发 workspace | v1 把 workspace 视为受信；sandbox 另立设计 |
| 6 | renderer digest 频繁漂移 | 改注释/格式化就换 digest | 用 manifest（id/version/projection/golden_digest）；行为变化必须升 version 并更新 golden |
| 7 | 未来工具 timeout >25s | descriptor 被 registry 拒绝 | 先设计 claim 前 lease 读取；不在 v1 偷渡 |
| 8 | `replay_class` 被误当授权 | 有人把 declaration 接进 recovery | 回归测试锁死 `no_replay`；文档三处声明“metadata only” |
| 9 | 非 UTF-8 文件名在 macOS/Linux 行为不同 | list/search 计数不一致 | 测试只在支持创建非法字节名的平台跑；不支持则 SKIP exit 2，不伪造通过 |
| 10 | `directory_too_large` 测试创建 10001 个文件太慢 | CI 超时 | 用稀疏目录/分批创建；仍慢则把该用例标 SKIP，不降低 cap |

**必须停下来改设计/内核的条件**：

- 需要非法 args 在 **model settlement** 就拒绝（不创建 tool effect），而不是 spawn 前拒绝。
- 需要真正的只读 replay、写工具、交互 approval、资源撤销、in-flight cancel。
- 合法单结果无法用分页表达且必然超过 64 KiB。
- 需要图片/二进制内容块。
- 不可信插件或恶意并发 workspace 进入范围。
- PostgreSQL `jsonb::text` 与 Python/Node 在任一接受输入上不一致。

---

## 10. 实施顺序

| 步 | 内容 | Done when |
|---|---|---|
| M1 合同与向量 | 本文定稿；`v24/s13/vectors/*.json` 固化 descriptor/frame/工具契约的期望 bytes；Python/Node/PostgreSQL 三方对齐 | 向量全绿；无源码执行路径改动 |
| M2 host 基础 | `descriptor.py`、`tool_schema.py`、`renderers.py`、`tool_results.py`；registry 拆 `ApprovedTool`/`ApprovedPlugin`；`line_json` v2；`plugins`/`worker`/`deepseek` 接线 | `test_descriptor`、`test_registry`、`test_line_json` 全绿；G9/G10/Node 回归全绿；v1 golden 字节不变 |
| M3 三个工具 | `fs_read.py`、`fs_tools.js`、`s13/fixtures.py`；read/list/search 合同测试 | `test_tools` 全绿；真实子进程；分页收敛 |
| M4 生命周期 | s13 harness、mixed batch、invalid args/output、render failure、timeout、tamper、crash、legacy | `test_lifecycle`、`test_node` 全绿；closeout 11/11 不变 |
| M5 收口 | 更新 §7.5 的文档/台账/矩阵；全量回归；按 AGENTS.md 提交推送 | `git diff --exit-code -- v24/sql` 为空；全部 gate exit 0 |

---

## 附录 A：`search` 完整 descriptor

W1 provisional digest：`fd2f51e8c3d7328b0af7ceafcbefc21418f799921e9e470f12b3f7b1b6344011`，由 `v24/s13/vectors/renderers.json` 的 `render.search.golden` 与 `render.manifest.search` 固定输入复算；状态为 `provisional-w2-pending`，不是 production renderer 验证结果。W2 必须复现该值。

```json
{
  "v": 2,
  "tool": {
    "key": "search",
    "description": "Search UTF-8 text files under a directory inside the approved workspace using literal substring matching. Hits follow DFS pre-order with siblings sorted by UTF-8 name bytes, then line, then column. offset is 1-based (default 1); limit max 200. If truncated, continue with next_offset.",
    "parameters": {
      "type": "object",
      "properties": {
        "query":          {"type": "string", "minLength": 1, "maxLength": 512},
        "path":           {"type": "string", "minLength": 1, "maxLength": 1024},
        "glob":           {"type": "string", "minLength": 1, "maxLength": 256},
        "ignore_case":    {"type": "boolean"},
        "context":        {"type": "integer", "minimum": 0, "maximum": 2},
        "include_hidden": {"type": "boolean"},
        "offset":         {"type": "integer", "minimum": 1},
        "limit":          {"type": "integer", "minimum": 1, "maximum": 200}
      },
      "required": ["query"],
      "additionalProperties": false
    },
    "output_schema": {
      "type": "object",
      "properties": {
        "path":    {"type": "string"},
        "offset":  {"type": "integer", "minimum": 1},
        "hits": {
          "type": "array",
          "maxItems": 200,
          "items": {
            "type": "object",
            "properties": {
              "path":           {"type": "string"},
              "line":           {"type": "integer", "minimum": 1},
              "column":         {"type": "integer", "minimum": 1},
              "text":           {"type": "string"},
              "text_truncated": {"type": "boolean"},
              "before": {
                "type": "array", "maxItems": 2,
                "items": {
                  "type": "object",
                  "properties": {"line": {"type": "integer", "minimum": 1},
                                 "text": {"type": "string"}},
                  "required": ["line", "text"],
                  "additionalProperties": false
                }
              },
              "after": {
                "type": "array", "maxItems": 2,
                "items": {
                  "type": "object",
                  "properties": {"line": {"type": "integer", "minimum": 1},
                                 "text": {"type": "string"}},
                  "required": ["line", "text"],
                  "additionalProperties": false
                }
              }
            },
            "required": ["path", "line", "column", "text", "text_truncated"],
            "additionalProperties": false
          }
        },
        "total":        {"type": "integer", "minimum": 0},
        "complete":     {"type": "boolean"},
        "scanned_files":{"type": "integer", "minimum": 0},
        "skipped": {
          "type": "object",
          "properties": {
            "hidden":    {"type": "integer", "minimum": 0},
            "symlink":   {"type": "integer", "minimum": 0},
            "binary":    {"type": "integer", "minimum": 0},
            "too_large": {"type": "integer", "minimum": 0},
            "non_utf8":  {"type": "integer", "minimum": 0},
            "long_lines":{"type": "integer", "minimum": 0}
          },
          "required": ["hidden", "symlink", "binary", "too_large", "non_utf8", "long_lines"],
          "additionalProperties": false
        },
        "truncated":    {"type": "boolean"},
        "next_offset":  {"type": ["integer", "null"], "minimum": 1}
      },
      "required": ["path", "offset", "hits", "total", "complete",
                    "scanned_files", "skipped", "truncated", "next_offset"],
      "additionalProperties": false
    },
    "render": {"id": "v24.fs.search.text", "version": 1, "digest": "fd2f51e8c3d7328b0af7ceafcbefc21418f799921e9e470f12b3f7b1b6344011"},
    "limits": {
      "timeout_ms": 15000,
      "max_args_bytes": 16384,
      "max_value_bytes": 40960,
      "max_content_bytes": 41984,
      "max_meta_bytes": 4096
    },
    "concurrency": "parallel",
    "replay_class": "read_only",
    "annotations": {"read_only": true, "destructive": false,
                    "idempotent": true, "open_world": false}
  }
}
```

---

## 附录 B：一句话总结

**v1 的边界是：host 扩展、descriptor v2、frame v2、三个只读工具、一个 Node install 两个工具、literal search、30 秒 lease、host-only 封闭 schema、v1 字节不变、SQL 零改动。** 任何越界（replay、写工具、session、regex、图片、streaming、sandbox）都不在本文，不得靠“顺手加个字段”偷渡。

---

## 附录 C：W2 合同加固规范补充（2026-10-31）

本附录是规范性补充，细化 §3.1、§5.2–§5.5 的接受域与错误分类；正文其他条款不变。若正文措辞与本附录冲突，以本附录为准。

### C.1 Descriptor 原文解码（补充 §3.1）

- 顶层非 object，以及全部 JSON 解码/词法失败，统一为 `invalid_descriptor`：重复键、非法 UTF-8/JSON、浮点/指数、`-0`、`NaN`/`Infinity`、孤立代理项、过深嵌套导致的 `RecursionError`、任意长度的超安全整数字面量。
- 实现可在 `int()` 转换前按位数预拒绝必然越界者（安全整数绝对值最多 16 位十进制），但不得改变安全整数的接受域，也不得向外泄漏 `ValueError`/`RecursionError`。
- `parse_descriptor` 的四个公开 reason 不变；解码失败仍只报 `invalid_descriptor`。

### C.2 结果 `J` 值域（补充 §5.2）

- success 的 `value`、`content` 与 failure 的 `content`、`meta` 还必须处于 §5.3.1 的 `J` 值域：object 键必须是 string，数值只能是安全整数，字符串必须是 Unicode scalar，容器只能是 list/object，标量只能是 boolean/null。
- float、`NaN`/`Infinity`、unsafe integer、孤立代理项、非 JSON 类型、非 string 键与循环引用一律 `invalid_tool_output`。
- success `value` 仍另须满足该工具的 `output_schema`；`J` 域检查是 envelope 层兜底，不替代 schema 校验。
- 帧层面：语法上非 JSON、`NaN`/`Infinity`、孤立代理项仍按 §5.1 的 unknown 处理；语法合法但数值越出 `J` 域的 success `value`，W3 按普通 failure `invalid_tool_output` 处理，不判 unknown。

### C.3 Renderer 失败分类（补充 §5.3）

`RendererRegistry.render` 的固定顺序：

1. 按完整 ref 执行 `lookup`；失败为 `renderer_not_approved`。
2. 通过 lookup 后调用 `fn`；`fn` 抛出的任何 `Exception`（包括 `RendererError` 自身）统一重分类为 `render_failed`。
3. 返回值 content/meta 形状或 `J` 域不合法 → `invalid_tool_content`。
4. 预算超限 → `output_too_large`（由调用方执行）。

`lookup` 在 `try` 之外，因此审批错误不会被 `fn` 的异常分类吞并；返回值校验在 `try` 之后，因此非法返回不会被误报为 `render_failed`。

### C.4 `ToolDispatchResult` 构造合同（补充 §5.4）

`ToolDispatchResult` 仅用于 v2，不用于 v1 路径（v1 继续返回 2-tuple 或 `{class,result}`）。构造时必须验证：

- `result` 恰为 `{status,output,usage}`，`status ∈ {ok,error}`，且 `class=success` 当且仅当 `status=ok`；
- `usage` 符合 §5.2 的 `{wall_ms}` 闭集；
- `model_text` 是 str；`class=unknown` 时必须是空串；
- 通过上述外层检查后，按 class 调用对应的 `assert_success_output`/`assert_failure_output`/`assert_unknown_output`。

外层结构、class/status、usage 与 `model_text` 错误为 `invalid_outcome`；class-specific envelope（value/content/error/meta）错误为 `invalid_tool_output`。该构造合同只定义容器校验，worker 接线仍属 W4。

### C.5 Object schema 判定（补充 §5.5）

本节所称 object schema 包括：

- `type` 为 string 或数组且含 `object` 的节点；
- 未声明 `type`，但出现 `properties` 或 `required` 的节点。

两类节点都必须显式写出 boolean `additionalProperties`。该判定只影响结构审批，不注入 `type:"object"`，对象约束仍只作用于对象实例；裸 `{}` 不是 object schema，仍是合法的 any-JSON schema。

### C.6 `J` 的深度与循环（补充 §5.3.1）

`J` 的编码使用显式栈，不以 Python 调用栈递归；有限深度的 JSON 不因深度被拒绝，字节计数仍按 §5.3.1 的公式。循环引用不是合法 JSON，统一报 `circular_reference`：公开结果入口（`success_output`/`ToolDispatchResult`/`measure`/`frame_bytes`）归一为 `invalid_tool_output`；descriptor 原文解码来自 JSON，不会产生循环引用。帧的字节上限与语义预算不变。

### C.7 LF 字节分帧（补充 §5.1）

v2 stdout 只按 LF 字节分帧：UTF-8 严格解码通过后，`raw.count(b"\n") > 1` 一律为 `extra_frame`（unknown），包括第二个 LF 只构成尾部空行的 `double_lf`；不是 `bad_frame`。缺少末尾 LF、LF 后有尾部垃圾、BOM 或非法帧仍为 `bad_frame`。冻结向量 `frames_v2.json` 的 `double_lf` / `extra_frame` 分类是本条的字节权威；§5.1 关于“多一个空行……都是 `bad_frame`”的句子在此范围内被本条取代。

v2 禁止复用 `str.splitlines()`；只计数 LF 字节、检查末尾 LF、移除该 LF，并仅剥除帧外 SP/HT/CR。字符串内的 U+2028/U+2029 不构成帧边界。v1 的 `splitlines()` 行为保留，两个协议使用独立解析路径。

### C.8 transport 层 `J` 域不可达（补充 §5.2，修订 C.2）

v2 transport 使用 `strict_loads` 解码：float、指数、unsafe integer、`NaN`/`Infinity`、孤立代理项与重复对象键在解码阶段即被拒绝，归为 `bad_frame`（unknown）。因此 transport 层不存在“语法合法但越出 `J` 域”的 success `value`；不得在严格解码后增加不可达的 `J` 域复检或 `invalid_tool_output` failure 分支，也不得为此换用宽松解码器。

`J` 域不合法 → failure `invalid_tool_output` 的映射属于 W4 envelope 构造：该层的值来自 Python 对象，而非 transport 字节流，仍须执行 C.2 的 envelope 兜底。C.2 最后一句中“语法合法但数值越出 `J` 域的 success `value`，W3 按普通 failure `invalid_tool_output` 处理，不判 unknown”的映射在 transport 层由本条明确取代；其余 envelope 值域与 schema 要求不变。

### C.9 Registry 构造合同补充（补充 §4.1）

`ApprovedTool` 自己持有与冻结 descriptor 一致的 schema closure：`parameters_check` / `output_check` 均为 `field(init=False, default=None, compare=False, hash=False, repr=False)`。`ApprovedTool.__post_init__` 先校验并深冻结 v2 descriptor，再在内部调用 `compile_schema`，通过 `object.__setattr__` 装入两个 closure；不得由调用方通过构造参数注入校验器。closure 不参与 equality/hash/repr；`compile_schema` 不设进程级 cache，closure 生命周期由调用方（持有它的 `ApprovedTool`）管理。`dataclasses.replace` 必须重跑构造校验与编译；descriptor 与 digest/timeout/render/output_schema 不一致时拒绝。v1 合成项不编译 v2 schema，两个 closure 均为 `None`。

v2 构造的 **14-token 词表只覆盖 W3 新增判定点**，不代表所有构造失败均被归一为 token。新增判定点使用 `RegistryError(token)`，且 `exc.args == (token,)`、`str(exc) == token`；不为 `RegistryError` 增加 `.reason`。

| W3 新增的 8 个 token | 复用的 6 个 token |
|---|---|
| `approved_tool_invalid` | `invalid_descriptor` |
| `protocol_invalid` | `descriptor_key_mismatch` |
| `tools_invalid` | `renderer_not_approved` |
| `duplicate_tool_key` | `renderer_digest_mismatch` |
| `workspace_root_invalid` | `mixed_descriptor_versions` |
| `timeout_cap_invalid` | `timeout_exceeds_cap` |
| `manifest_invalid` | |
| `adapter_digest_mismatch` | |

`_hex64` 的格式校验、descriptor-digest 不一致，以及进程/制品字段校验继续沿用既有 v1 prose 消息，不强制纳入上述 token。reason 所有权如下：

| 类别 | 异常与可见面 |
|---|---|
| v2 构造的 W3 新增判定点（`ApprovedTool` / `ApprovedPlugin` / `from_manifest`） | `RegistryError(token)`；上述 14-token 闭集 |
| 既有构造校验、进程/制品字段、registry 类型检查 | `RegistryError(prose)`；既有 prose 不变 |
| install/pin/tool 匹配 | `AdapterNotFound.reason`：`install_invalid`、`adapter_not_approved`、`pin_key_mismatch`、`tool_not_approved`、`descriptor_missing`、`descriptor_digest_missing`、`descriptor_mismatch`、`descriptor_digest_mismatch`、`protocol_mismatch`；另保留 §4.1 的五个 artifact reason |

构造 token 只用于 host 内部构造合同，绝不进入 wire、SQL effect-code 闭集或 dispatcher reasons；与匹配期 reason 拼写相同的复用 token，也不改变各自异常类型与所属判定点。

### C.10 §7 措辞修订

§7.1、§7.3、§7.4 中仍沿用早期工作划分的文字，以本节为权威读法；原文保留用于 immutable span 的行号与内容校验。

- **§7.1 文件职责与阶段**：W3 的生产改动仅为 `registry.py` 的审批模型/union/匹配与 `line_json.py` 的独立 v2 transport。registry 的 `environment()` 是既有共享行为，移入无字段 mixin；`ApprovedAdapter` 的 17 字段与 v1 行为不变，`match_pin` 仅新增对 v2 的 `protocol_mismatch` 拒绝分支。`ApprovedPlugin.from_manifest()` 属 W3 生产 API，不留给 fixture；manifest 为 bytes 时以原始字节计算 digest，为 str 时先 UTF-8 编码，为 dict 时以 `compact_json` 字节计算。`plugins.py` v2 分支、`worker.py` 的 `model_text` 与 `deepseek._tools` 接受 v2 均属 W4；插件文件、fixtures、`test_tools.py` / `test_lifecycle.py` / `test_node.py` 不由 W3 交付，artifact digest 实算属 M3。
- **§7.3 registry 证据**：`match_tool` 的六类失败为 `tool_not_approved`、`pin_key_mismatch`、`descriptor_missing`、`descriptor_digest_missing`、`descriptor_mismatch`、`descriptor_digest_mismatch`，均须证明零 `require_artifact` 调用、零 `run_process` 调用。artifact 的五个失败 reason 独立验证，不是 `match_tool` 的一步；真正 spawn 前仍须执行 `require_artifact()`。构造探针同时覆盖 C.9 的 14 token 与保留的 prose，closure 自编译、v1 不编译、`replace` 重算；`match_pin(v2)` 拒绝不变。
- **§7.3 transport 证据**：W3 执行冻结的 5 个请求与 2 个响应 byte case，逐行复现 46 条 invalid + 9 条 whitespace corpus，覆盖 5 条 build preflight、4 类进程 unknown、v1 字节/分类与静态协议分流。`double_lf` 为 `extra_frame`；float/unsafe-int success value 为 `bad_frame`，以 C.7/C.8 为准。v1 保留原解析器；W3 gate 使用 stub，不打开网络、数据库或 Node，也不证明真实子进程生命周期。
- **§7.4 阶段 done-when**：W2 的四条 s13 gate、W3 的 `test_registry.py` / `test_line_json.py` 与后续工具/生命周期/Node gate 分阶段交付。W3 是 design §10 M2 的 registry/transport 子阶段，不等于 M2 完成；W3 验收为两条新 gate 加既有回归共 26 条串行命令全部通过，不把 §7.4 的完整 ABI done-when 当成 W3 已完成。真实生命周期、多工具 mixed batch、崩溃恢复与 provider/tool-message 字节接线仍须后续 gate 证明。冻结向量不得 re-bless；`frames_v2.json` 的 case 保持 `m2_pending`，五字段 key 的 artifact 证据保持 `m3_pending`。
- **§7.4 gate 三态与范围**：exit 0 且命令专属 `[passed]` 末行才算通过；exit 2 / `[SKIP]` 为未验证，阻断完成；exit 1 或缺通过标记为失败。保留 SQL 零 diff、无真实 provider/网络、closeout 11/11，s13 仍是 extension evidence，不是第 12 条 closeout；本节规范修订本身不构成 gate 通过声明。
