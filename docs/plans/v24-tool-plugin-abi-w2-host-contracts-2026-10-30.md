# v24 Tool/Plugin ABI W2：纯 host 合同组件 Deep Plan

日期：2026-10-30。状态：implemented and verified（2026-10-30）；W2 四个新 gate 与 24 条串行命令 exit 0；W3/W4 未开始，M2 未完成。

## Goal 与范围

W2 是设计稿 §10 M2「host 基础」的第一个子阶段。它只交付**不依赖运行时、不产生 I/O**的 host 合同组件：

- `v24/host/canonical.py`（新 leaf：PG canonical、deep-freeze、严格 JSON、`J`）
- `v24/host/tool_schema.py`（封闭 JSON Schema 子集）
- `v24/host/descriptor.py`（descriptor v2 关闭集校验 + digest + render 身份）
- `v24/host/renderers.py`（三个 host renderer + 不可变 registry + golden/render digest）
- `v24/host/tool_results.py`（v2 envelope、`model_text`、预算计量、frame 分类）

W2 必须让 W1 冻结的 **40 个 M2 case** 由生产实现逐字节复现（`descriptor_v2` 16、`schema_v2` 9、`renderers` 7、`results_v2` 的 8 个 M2 case），并同步 design §7.1/§7.3/§7.4 与收尾文档。

W2 **不**交付：`ApprovedTool` / `ApprovedPlugin` / `ToolBinding` / `match_tool` / `environment()`、line-json v2 的 build/parse、`plugins.py` v2 分支、`worker._call_tool_handler` 的 `model_text` 接线、`deepseek._tools` 接受 v2、`page_decision` / `page_error` / 文件系统扫描 / 前缀选择、任何 read/list/search 插件或子进程。W2 是 M2 的前置子阶段，不是 M2 完成；发布时不得声称 W3/W4/M3/M4 完成。

## Done when

1. 四条新 gate 实际 exit 0 且打印各自 `[passed]` 末行：`v24/s13/test_descriptor.py`、`test_schema.py`、`test_renderers.py`、`test_results.py`。
2. 40 个 W2 case 全部由生产代码命中：descriptor 16（含 6 个 canonical byte case 与 3 个完整 descriptor）、schema 9（13 allow / 29 deny / 13 invalid-allowed）、renderers 7（含 21 个内嵌 golden 与 3 组 digest）、results 8（含 9 行 exact boundary 与 4 行 frame classification）。
3. v1 行为逐字节不变：`v24/b0/test_golden.py` 两种模式 exit 0；`v24/s13/test_vectors.py` 两种模式 exit 0；`v24.host.registry` 的七个被移走名字仍可 import，`RegistryError` 身份不变，非 dict 的 `descriptor_digest` 仍抛 `RegistryError`。
4. 无意外接线：四个合同模块不 import `plugins`/`worker`/`deepseek`/`line_json`/`db`/`process_io`；生产代码不读 `v24/s13/vectors/*`；`plugins.py`/`worker.py`/`line_json.py`/`deepseek.py`/`journal.py`/`db.py`/`process_io.py` 相对 HEAD 零 diff。
5. design §7.1/§7.3/§7.4 的修订与 `DESIGN_SHA256` / `design_conformance.json` 的 repin 在同一原子步骤完成，两个 W1 conformance checker 随后立即通过。
6. `v24/s13/README.md`、deviation ledger、conformance matrix、W2 execution record 与本计划 Result 一致；只记录真实结果。
7. 24 条串行命令全部 exit 0；无 exit 2/SKIP、无 `not_run`；closeout 仍 11/11；`v24/sql/**` 零 diff。
8. 按 AGENTS.md 单一里程碑提交并 `git push origin main`；无 `git add -A`、无 `--no-verify`、无 force push。

## Current-state analysis

### 现有链路

```text
worker._call_tool_handler            (worker.py:1302-1308)
  → PluginDispatcher.tool_handler    (plugins.py:40-83)
  → registry.match_pin               (registry.py:312-334)
  → ApprovedAdapter.require_artifact (registry.py:229-255)
  → line_json.run(v1)                (line_json.py:101-149)
  → (class, result)
  → tool_message.content = canonical_json(output)   (worker.py:1066-1077)
```

`v24/host/` 现有 12 个模块：`__init__.py`、`db.py`、`deepseek.py`、`journal.py`、`line_json.py`、`plugin_smoke.py`、`plugins.py`、`process_io.py`、`registry.py`、`smoke.py`、`worker.py`。没有 descriptor/schema/renderer/result 生产模块。

`registry.py` 没有 host-module import：只 import 标准库（`hashlib/json/os/stat` 与 `dataclasses/pathlib`，`registry.py:23-28`）。它同时持有本阶段要复用的原语：

- `_FrozenDict` / `_FrozenList` / `_freeze`（`:37-82`），只被 registry 自己使用；
- `_quote`（`:104-106`）与 `pg_jsonb_text`（`:108-137`），descriptor digest 的唯一 PG 形式；
- `descriptor_digest`（`:140-144`），非 dict 输入抛 `RegistryError`；
- `RegistryError` / `AdapterNotFound`（`:84-94`）。

依赖方向：`plugins.py:24` → registry；`worker.py:27-29` → db/deepseek/journal；`line_json.py:31` → process_io。若 W2 让 `descriptor.py` 反向 import registry，W3 再让 registry import descriptor（`ApprovedPlugin.__post_init__` 必须校验 `tool.descriptor`），就会形成 module-level 循环。

`pg_jsonb_text` / `descriptor_digest` 的既有 importer 必须继续工作而不改调用点：`v24/s13/test_vectors.py:17`、`v24/b0/golden_cases.py:22`、`v24/b0/test_multi_provides.py:22`、`v24/s11/plugin_fixtures.py:43-47`、`v24/s11/test_g10.py:44-49`。

### 五种 canonical form 不得互换

| 形式 | 归属 | 用途 |
|---|---|---|
| `pg_jsonb_text` | registry（W2 移入 canonical） | descriptor digest / PG `jsonb::text` |
| `compact_json`（`J`） | W2 新增 `canonical` | renderer digest、args/value/content/meta 预算 |
| `journal.canonical_json` | `journal.py:64-73` | provider 请求、request digest、tool message |
| `deepseek._canonical` | `deepseek.py:111-114` | provider body |
| `line_json._canonical` | `line_json.py:71-87` | v1 frame |

`J` 与 `journal.canonical_json` 今天字节相同（同为 compact sorted JSON），但**属于不同权威**：W2 必须让 `J` 拥有独立函数与独立测试，未来改动 journal 形式不得静默改变预算计量。

### W1 冻结输入

`v24/s13/vectors/` 为 `v24-tool-plugin-abi-w1-vectors-1`，10 suites / 71 case IDs，checker 只读、无 re-bless（`v24/s13/test_contracts.py:1-139`；inventory/SHA/span 断言见 `:10,42-43,53-60`）。W2 域内四套与覆盖数：

| suite | case 数 | W2 覆盖 |
|---|---:|---|
| `descriptor_v2.json` | 16 | 9 byte（6 canonical + 3 完整 descriptor）+ 7 table |
| `schema_v2.json` | 9 | 全部 |
| `renderers.json` | 7 | 3 golden suite（21 内层 case）+ 3 manifest + 1 digest 表 |
| `results_v2.json` | 11 | 8 个 M2 case；另 3 个 `m4_pending` 不执行 |

这些 case 的 `status`/`owner` 是 W1 冻结标签（`m2_pending` / `provisional_w2_pending`），W2 **不得编辑**；覆盖事实只写入 W2 的 README/execution record。

本地复算确认的关键事实（实现必须命中，不得重推）：

- `golden_digest` 只对**五键** `{id,args,value,content,meta}` 按 case ID UTF-8 升序做 `sha256(compact_json(...))`；把 `measures` 纳入会得到不同值（read 会变成 `f16af321…`），因此 `measures` 永不进入 digest。
- 三组固定值：

| renderer | golden_digest | render_digest |
|---|---|---|
| `v24.fs.read.text` | `b803bdd5c1cd3fd25ef62f564c949d2aebd6cafdd04dcf8d740d07dc31961a1d` | `ca52198cf6c2edae798f2340ba4f370f658d422fa05f5d529c28510dea0a680c` |
| `v24.fs.list.text` | `a23d757c36073b6d5cd1b609d21a1e0ae41ad8336eccde4ce6eb3bb0f5896a5f` | `5b0bbe8d0fc70ea68c73baeb01b4df1d6be1a4e31e303dc22e3079605376f9c7` |
| `v24.fs.search.text` | `e4075fe195b7f030bd1d335ec37e9ae2a87af3ba4b497fe0a7a3dfc8565b13ac` | `fd2f51e8c3d7328b0af7ceafcbefc21418f799921e9e470f12b3f7b1b6344011` |

- 三个完整 descriptor 的 `tool.render.digest` 就是上表第三列；read/list 的 `limits` 为 5000/16384/40960/41984/4096，search 的 `timeout_ms=15000`。
- descriptor 表 case 的 reason 词表恰为四值：`accepted`（22 行）、`invalid_descriptor`（64 行）、`descriptor_key_mismatch`（1）、`renderer_digest_mismatch`（1）。
- `descriptor.pg_size_depth_integer_unicode_boundaries` 用 `raw_json` 表达 `[9007199254740991]`→accepted，`[9007199254740992]`、`[1.5]`、`[1e3]`、`[-0]`、`["\ud800"]`→invalid。`json.loads` 会把 `-0` 归并为 `0`、把 `1e3` 变成 `1000.0`，所以必须有保留词法判定的解码步骤。
- schema 词表：`accepted`（26）、`unsupported_schema`（53）、`duplicate_enum`（1）、实例错误 `{path,rule}`（9 行，rule 覆盖 `required/additional/type/min_length/max_length/minimum/maximum/min_items/max_items`）。
- 预算：`meta` 缺省与 `{}` 都计 2 bytes；`max_meta_bytes` 2..16384；value/content/meta 上限 40960/41984/4096；frame target 60000，transport 65536，65537 才是 `stdout_limit_unknown`；frame 固定 JSON 开销 48 bytes + 1 LF。

### W2 边界

W2 新增的五个模块是**叶子之上的一层**：只 import 标准库与 W2 内部模块（`canonical`、`tool_schema`、`renderers`）；不 import 任何现有 host 运行时模块，不被任何现有 host 运行时模块 import。W3 才会让 `registry.py` 依赖 `descriptor`/`renderers`/`tool_schema`；W4 才会让 `plugins.py`/`worker.py` 依赖 `tool_results`。

## 决策记录

以下七项已用 W1 向量与现有代码定案；Oracle 裁决记录见文末。它们是实现合同，后续改变按行为变化处理。

### D1：新增 `canonical.py` leaf，`registry.py` 改为 re-export

把 `_FrozenDict`、`_FrozenList`、`_freeze`、`_quote`、`pg_jsonb_text`、`descriptor_digest` **原样搬入** `v24/host/canonical.py`，并同时搬入 `RegistryError`（`descriptor_digest` 对非 dict 输入抛它；留在 registry 会使逐字搬迁不可能）。`registry.py` 只做：

```python
from .canonical import (RegistryError, _FrozenDict, _FrozenList, _freeze,
                        descriptor_digest, pg_jsonb_text)  # noqa: F401
```

`AdapterNotFound(RegistryError)` 仍在 registry 定义。必须断言 `v24.host.registry.RegistryError is v24.host.canonical.RegistryError`。

拒绝方案：`descriptor.py` 直接 import registry（W3 成环）；函数级 lazy import（绕过静态 import 审计，且按 import 顺序产生两个 `_FrozenDict` 身份）。验收：五个 B0 descriptor-v1 byte case、九个 W1 canonical byte case、所有既有 import 语句、非 dict digest 的异常类型全部不变。

### D2：严格 JSON 解码由 W2 拥有

`canonical.strict_loads(raw)` 复现 `w1_reference.strict_loads`（`v24/s13/w1_reference.py:28-62`）：拒绝重复键（`duplicate_key`）、词法 `-0`（`negative_zero`）、任意 float/exponent（`non_integer_number`）、`NaN/Infinity`（`non_json_constant`）、超出 `2^53−1` 的整数（`unsafe_integer`）、孤立 surrogate（`lone_surrogate`）。`descriptor.parse_descriptor(raw)` 调用它，并把任何 `CanonicalError`/`JSONDecodeError`/`UnicodeDecodeError` 统一映射为 `DescriptorError("invalid_descriptor")`。

拒绝方案：留给 W3 的 manifest loader。理由：六个 `raw_json` case 将无法在 W2 执行，`test_descriptor.py` 只能 SKIP（exit 2），W2 无法完成；W3 只是消费者。

边界：strictness 只作用于 descriptor/frame 输入边界；`pg_jsonb_text` 自身行为不变。

### D3：四个模块各一条 gate

新增 `v24/s13/test_descriptor.py`、`test_schema.py`、`test_renderers.py`、`test_results.py`。四个模块拥有四个独立向量文件、四套 reason 词表；合并成一个 gate 无法定位失败，且 design §7.3 一行要描述四种无关合同。

设计修订随之把 s13 变成 **9** 个脚本：W2 四个 + 后续五个（`registry`、`line_json`、`tools`、`lifecycle`、`node`）。W2 不声称后续五个中的任何一个。

具体修订：§7.1 的文件表增加 `canonical.py` 与三个新测试文件，并把 `test_descriptor.py` 的职责缩为 descriptor-only；§7.3 的 `test_descriptor.py` 行同样缩小，新增 `test_schema.py`/`test_renderers.py`/`test_results.py` 三行；§7.4 的 s13 gate 块增加三条命令，done-when 第 1 条改述为「W2 覆盖九个 s13 gate 中的四个，`test_registry`/`test_line_json`/`test_tools`/`test_lifecycle`/`test_node` 仍归 W3/W4」。

### D4：`J` 放 `canonical`，预算入口放 `tool_results`

`canonical.compact_json(value) -> bytes` 是唯一 `J`；`canonical.escaped_len(text) = len(compact_json(text)) - 2` 是 `E(s)`。`tool_results.measure` / `frame_bytes` 是唯一生产预算入口。`renderers.py` 用 `compact_json` 算 digest，但**不得** import `tool_results`。

拒绝方案：独立 `budget.py`——`renderers.py` 也需要同一序列化，独立层会导致 `renderers → budget` 的倒置依赖或第三份 `J`。

### D5：不实现完整 §5.2 scenario→class/status/code 映射

`tool_results.py` 只提供 envelope 构造/校验、usage 校验、`join_content`、计量与 frame 分类。spawn 前 registry reason（`adapter_not_approved`、`pin_key_mismatch`、`artifact_*` 等）、line-json unknown reason、lease/workspace 失败仍由 W4 dispatcher 映射。W2 若提前编码这些字符串，会在权威尚不存在时发明合同。

W4 的映射输入已由 W2 提供：`measure` 结果与 descriptor limits 比较得出 `output_too_large`；`RendererError` 得出 `render_failed`/`invalid_tool_content`；`InstanceError.rule` 得出 `invalid_tool_arguments`/`invalid_tool_output`。

### D6：四条新 gate 全部 DB-free、Node-free

`test_descriptor.py` 只用 Python 比较九个 canonical/descriptor byte case 的 `expected_hex`。PostgreSQL `v24.canonical_json` 的同一批 case 继续由继承的 `test_vectors.py` 证明；W2 完成必须包含该 inherited gate 的实际 exit 0。新 gate 不得 import `setup_db`，不得打开数据库、socket 或子进程。

### D7：design §7 修订与 conformance pin 原子 repin

W2 只改 design §7.1（文件清单）、§7.3（测试矩阵）、§7.4（gate/done-when），不改 §3–§6 语义。修订会改变设计 SHA，而 `test_contracts.py:10` 与 `design_conformance.json` 固定该校验值；必须在同一原子步骤：

1. 更新 `test_contracts.DESIGN_SHA256`；
2. 更新 `design_conformance.json.design_input.sha256_at_review`；
3. 重算**所有 line_start 大于首个改动行**的 pinned span 行号：`§7.2`、`§8.2`（出现在 `result_model_text_budget_replay` 与 `result_replay_lifecycle` 两组）、`§8.3`、`Appendix A`；
4. 断言行号变动后每个 span 的 `heading` 与 `sha256` **不变**（只移位，不改内容）；
5. 不改任何 suite、case ID、design_refs、status、owner、expected 值或八个 domain vector 的字节。

这是「vectors 只读」的唯一例外：conformance metadata 维护，不是 re-bless。若任一 pinned span 的**内容**会变，停止并回设计评审。

## 组件设计

### 模块图与通用约束

```text
canonical
├── tool_schema
│   └── descriptor
├── renderers
│   └── (descriptor 通过 RendererRegistry 做身份校验)
└── tool_results

registry ──re-export──> canonical
```

所有 API 同步、纯、确定性：不读时钟/随机/环境/文件/DB/网络，不开子进程，不写日志；异常不留下半构造状态；相同 JSON 输入产生相同输出。W2 不拥有进程级 validator cache；`compile_schema` 返回的 closure 由 W3 的审批对象持有，冻结值与 closure 可跨线程安全读取。

### `v24/host/canonical.py`

```python
SAFE_INTEGER_MAX = 2**53 - 1

class CanonicalError(ValueError): reason: str
class RegistryError(RuntimeError)        # 从 registry 原样移入

_FrozenDict, _FrozenList, _freeze, _quote      # 原样移入
def pg_jsonb_text(value) -> str                # 原样移入
def descriptor_digest(descriptor) -> str       # 原样移入
def compact_json(value) -> bytes               # J
def escaped_len(text: str) -> int              # len(J(text)) - 2
def strict_loads(raw: str | bytes) -> Any
```

`compact_json`（`J`）规则：

- 对象键必须为 string，按**无符号 UTF-8 字节字典序**排序（不是 `pg_jsonb_text` 的「长度优先」）；
- 数组保序；分隔符恰为 `,` 与 `:`，无空白/BOM/尾 LF；
- 字符串转义恰为 `\"`、`\\`、`\b`、`\f`、`\n`、`\r`、`\t`，其余 `< U+0020` 用小写 `\u00xx`；`/`、U+2028/U+2029、非 ASCII 原样 UTF-8；
- 整数用普通十进制（负数带 `-`）；bool 不是 integer；
- 仅接受安全整数、bool、null、str、list、dict；float、NaN/Infinity、unsafe integer、孤立 surrogate、非 string 键、其他 Python 类型一律 `CanonicalError`。

`strict_loads` 的顺序：strict UTF-8 解码 → `object_pairs_hook` 拒绝重复键 → `parse_int` 拒绝 `-0` 与 unsafe → `parse_float` 拒绝全部浮点/指数 → `parse_constant` 拒绝 `NaN/Infinity` → 递归校验 key/value 的 Unicode scalar。不做 NFC/NFD，不注入默认值。

### `v24/host/tool_schema.py`

```python
class SchemaError(ValueError): reason: str        # unsupported_schema | duplicate_enum
class InstanceError(ValueError): path: str; rule: str

def assert_supported(schema, *, kind: str) -> None       # kind in {parameters, output_schema}
def compile_schema(schema, *, kind: str) -> Callable[[Any], None]
def validate(schema, instance) -> None                    # 首个错误即抛 InstanceError
def schema_metrics(schema) -> dict                        # depth/nodes/max_properties/max_enum
```

`kind` 没有默认值：`parameters` 的 root object + `additionalProperties:false` 检查不能被 output 语义静默跳过。

**关键字闭集**：允许 13 个——`type`、`properties`、`required`、`additionalProperties`、`items`、`minItems`、`maxItems`、`minLength`、`maxLength`、`minimum`、`maximum`、`enum`、`description`。其余一律 `unsupported_schema`，包括 29 个明确拒绝项：`$ref`、`$defs`、`definitions`、`$schema`、`$id`、`oneOf`、`anyOf`、`allOf`、`not`、`if`、`then`、`else`、`pattern`、`format`、`default`、`const`、`number`、`patternProperties`、`propertyNames`、`uniqueItems`、`minProperties`、`maxProperties`、`exclusiveMinimum`、`exclusiveMaximum`、`multipleOf`、`contentEncoding`、`readOnly`、`writeOnly`、`examples`。

**结构规则**：

- `type`：单个允许类型，或 2..4 个互异允许类型；取值只能是 `object/array/string/integer/boolean/null`。
- `properties`：object（name → schema）；`required` 必须是无重复 string 数组且每项在 `properties` 中；`required` 不得脱离 `properties`。
- `additionalProperties`：每个 object schema 必须显式写 boolean。
- `items`：单个 schema；`"array"` ∈ type 时必须写。
- `minItems`/`maxItems`：非负安全整数，仅 array；`minLength`/`maxLength`：非负安全整数，按 **Unicode scalar** 计数，仅 string；`minimum`/`maximum`：安全整数（bool 不接受），仅 integer。
- `enum`：1..64 个 **JSON-distinct** 值。distinct 判定用 `compact_json` 的字节：对象键顺序无关，数组顺序有关，`true`/`1`/`"1"`/`null` 互不相等。`enum: []` 与 `enum: [65 项]` 是 `unsupported_schema`；重复值（如两个同形 object）是 `duplicate_enum`。
- `description`：必须是 string。
- 类型相关关键字（`items`/`minItems`/`maxItems`/`minLength`/`maxLength`/`minimum`/`maximum`）在没有 `type` 时只在实例属于对应类型时生效；若声明的 `type` 集合与关键字所需类型完全不相交（例如 `type:"string"` + `minimum`），schema 无效。`type` 为数组时，各约束只作用于匹配的实例类型。
- 不检查 `minimum <= maximum`、`minItems <= maxItems` 之类的跨字段一致性；设计没有要求，冻结向量也不覆盖。
- `enum` 内的数组/对象是**值**，不计入 schema node/depth；node 只数 schema 节点（root、`properties.<k>`、`items`）。
- nullable union（`type:["object","null"]`、`["array","null"]`）必须接受；`null` 分支不触发其他约束。
- `parameters` 根：`type:"object"` 且 `additionalProperties:false`；`output_schema` 根可为 `{}`。
- 不注入 `default`；host 不改写 instance。

**结构边界**（`schema.schema_bounds` 固定）：depth ≤16（root schema node = 1，`properties.<k>` 与 `items` 各 +1）；总 schema node ≤256；任一单个 `properties` map ≤128 键（per-object 解释，写入模块文档）；任一 `enum` ≤64。

`compile_schema` 先 `assert_supported`，再把 schema 深冻结为不可变表示并返回闭包；**不做进程级缓存**，由调用方（W3 的 `ApprovedTool`）持有并复用该闭包。这样缓存生命周期与审批对象绑定，W2 不引入无主全局状态；`validate(schema, instance)` 每次自行 compile。

**实例遍历顺序**（只报第一个错误，rule 优先级固定）：

```text
type → required → additional → enum → min_length → max_length
→ minimum → maximum → min_items → max_items
```

- object：先按 schema `required` **数组原序**报缺失；再按 key 的无符号 UTF-8 字节升序报额外属性；再按 property name 的 UTF-8 字节升序递归。
- array：按 index 升序递归。
- `integer` 排除 bool，只接受安全整数；union type 中 `null` 不触发其他约束。

**路径格式**：root `$`；匹配 `^[A-Za-z_][A-Za-z0-9_]*$` 的键写 `$.name`，其他键写 `$["<canonical escaped key>"]`；数组元素追加 `[<i>]`。冻结向量只钉了 `$.z`、`$.x`、`$.items[0]`、`$["a-b"]` 与空 key，其余边界是本计划的显式选择。

### `v24/host/descriptor.py`

```python
class DescriptorError(ValueError): reason: str
    # 恰四值：invalid_descriptor | descriptor_key_mismatch
    #        | renderer_not_approved | renderer_digest_mismatch

def parse_descriptor(raw: str | bytes) -> dict
def validate_descriptor(descriptor, *, provide_key=None,
                        render_registry=RENDERERS) -> _FrozenDict
def descriptor_depth(value) -> int          # root container=1; child container=parent+1
def descriptor_pg_bytes(descriptor) -> int
```

**关闭集**：顶层恰 `{v, tool}`；`tool` 恰 `{key,description,parameters,output_schema,render,limits,concurrency,replay_class,annotations}`；`render` 恰 `{id,version,digest}`；`limits` 恰 `{timeout_ms,max_args_bytes,max_value_bytes,max_content_bytes,max_meta_bytes}`；`annotations` 恰 `{read_only,destructive,idempotent,open_world}`。

**字段约束**：`key` 匹配 `^[a-z][a-z0-9_.-]{0,127}$`、非 `agent.spawn`、无 NUL；`description` 1..4096 UTF-8 bytes、无 NUL；`limits` 范围 `timeout 1..25000`、`args 1..65536`、`value 1..49152`、`content 1..65536`、`meta 2..16384`；`render.id` 匹配 `^[a-z][a-z0-9_.-]{0,127}$`；`render.version` 1..`2^53−1`；`render.digest` 64 位小写 hex；`concurrency ∈ {parallel,exclusive}`；`replay_class ∈ {read_only,idempotent,mutating,external}`；annotations 四项皆 bool。

**annotation implications**：`replay_class=read_only` ⇒ `read_only=true`、`destructive=false`、`idempotent=true`；`read_only=true` ⇒ `destructive=false`；`concurrency=parallel` ⇒ `read_only=true`。

**固定验证顺序**（无冻结 case 覆盖多故障优先级，因此该顺序是稳定 API 行为）：

1. 顶层 object + 顶层关闭集；
2. `type(v) is int and v == 2`（bool 不算 integer）；
3. `tool` object + tool 关闭集；
4. key；
5. description；
6. `parameters` → `tool_schema.assert_supported(..., kind="parameters")`；
7. `output_schema` → `assert_supported(..., kind="output_schema")`；
8. render 结构/id/version/digest；
9. limits 结构 + 范围；
10. concurrency / replay_class；
11. annotations 结构 + bool；
12. implications；
13. `descriptor_depth ≤ 16`；
14. 全文 safe-integer / Unicode scan（parse 阶段已做的词法项不重复）；
15. `len(pg_jsonb_text(descriptor).encode()) ≤ 16384`（必须在 14 之后，且只在已证明是安全 JSON 后序列化）；
16. `provide_key` 与 `tool.key` 不等 → `descriptor_key_mismatch`；
17. `render_registry.by_id(id, version)`：缺席 → `renderer_not_approved`；digest 不等 → `renderer_digest_mismatch`。

步骤 6–15 的任何 `SchemaError`、`CanonicalError`、`TypeError`/`ValueError`/`AttributeError`（例如 in-process dict 带非 string 键时 `pg_jsonb_text` 会失败）都必须归一为 `DescriptorError("invalid_descriptor")`；只允许四个 reason 逃逸，异常消息不带原始文本、filesystem path 或 traceback。

`render_registry` 默认为 `renderers.RENDERERS`（fail-closed：忘了传也仍校验），**不提供 `None` bypass**。拒绝「默认 None + duck typing」方案：漏传会静默跳过 render 身份校验。测试用 `RendererRegistry` 构造篡改条目覆盖 `renderer_not_approved` 与 `renderer_digest_mismatch`，不靠关闭检查。

`validate_descriptor` 返回深冻结副本，永不修改输入、不注入默认值。`parse_descriptor` 只接受 JSON object；所有解析失败统一 `invalid_descriptor`，不泄露原始文本。

### `v24/host/renderers.py`

```python
@dataclass(frozen=True)
class RendererRef: id: str; version: int; digest: str

@dataclass(frozen=True)
class Renderer:
    ref: RendererRef
    projection: int
    fn: Callable[[dict, dict], tuple[list[dict], dict]]   # (args, value)

class RendererError(ValueError): reason: str
    # renderer_not_approved | render_failed | invalid_tool_content

class RendererRegistry:
    def __init__(self, entries: tuple[Renderer, ...]) -> None   # 拒绝重复 (id, version)
    @property
    def entries(self) -> tuple[Renderer, ...]
    def __len__(self) -> int
    def by_id(self, renderer_id: str, version: int) -> Renderer | None   # 忽略 digest
    def lookup(self, ref: RendererRef) -> Renderer   # id/version/digest 全等，否则 renderer_not_approved
    def render(self, ref, args: dict, value: dict) -> tuple[list[dict], dict]

RENDERERS: RendererRegistry                     # 三个内建，import 时构造
def golden_digest(cases: Sequence[Mapping]) -> str
def render_digest(renderer_id, version, projection, cases) -> str
```

三个内建：`v24.fs.read.text`、`v24.fs.list.text`、`v24.fs.search.text`，均 version 1 / projection 1。`fn(args, value)` 采用设计 §5.3 的双参数签名，三个内建函数忽略 `args`（§5.3.1 的投影只依赖 `value`）；这是对 W1 reference 单参数 `render(kind, value)` 的适配。

`registry.render`：先 `lookup`，再调用 `fn`；`fn` 抛任何普通异常 → `render_failed`；返回 content 必须是 1..16 个恰为 `{type:"text",text:str}` 的 block、meta 必须是 object，否则 `invalid_tool_content`。预算校验不在本模块。

投影算法以设计 §5.3.1 为唯一权威，实现必须逐字节复现，不自创新格式。实现要点（供 code review 对照，不替代 §5.3.1）：

- `D(x)` = 十进制文本，`None` → `"null"`；不合成尾 LF；
- read：`total_lines==0` 用 `[empty file]`，否则用 `text`；`truncated` 时追加 `\n\n[Showing lines S-E of T. Use offset=N to continue.]`；
- list：directory 后缀 `/`、symlink 后缀 `@`、file 后缀 ` (N B)`；`\n` join；空 entries 用 `[empty directory]`；footer 为 `\n\n[Showing O-E of T. Use offset=N to continue.]`，`E=offset+len(entries)-1`；
- search：每 hit 依 before 原序、hit、after 原序展开；context 行 `path-line- text`，hit 行 `path:line:column: text`；零 hits 正文 `[no matches]`；正文后恒追加 `\n\n[hits A-B of N; scanned S; skipped K]`，空页 `A=B="0"`，`complete=false` 时 `N` 后缀 `+`，`K` 是六个 skipped 的数学和；`truncated` 再追加 `\n[Use offset=N to continue.]`；
- 三者统一返回 `([{"type":"text","text":T}], {})`。

text/context 即使含 LF、CR、NUL、引号、反斜杠、U+2028/U+2029，也原样拼入 T，不做第二次转义或截断。

**digest**：`golden_digest` 先把每个 case 投影为五键 `{id,args,value,content,meta}`（`measures` 永不参与），按 case ID UTF-8 升序，`sha256(compact_json(ordered))`；`render_digest = sha256(compact_json({"id","version","projection","golden_digest"}))`。

生产代码**内嵌** 21 个五键 golden（read 8 / list 5 / search 8），**不得**在运行时读 `v24/s13/vectors/*`。三组 digest 必须命中上表；不符即 STOP，不得改向量或把 `measures` 纳入 digest。

### `v24/host/tool_results.py`

```python
class ToolResultError(ValueError): reason: str
    # invalid_outcome | invalid_tool_output

@dataclass(frozen=True)
class ToolDispatchResult:
    class_: str          # success | failure | unknown
    result: dict         # 外层 {status, output, usage}
    model_text: str

def success_output(value, content, meta=None) -> dict
def failure_output(code, message, content, meta=None) -> dict
def unknown_output(code, message) -> dict
def assert_success_output(obj) -> None
def assert_failure_output(obj) -> None
def assert_unknown_output(obj) -> None
def assert_usage(usage) -> None
def assert_builtin_meta(meta) -> None
def join_content(content) -> str
def measure(args, value, content, meta=None) -> dict
def frame_bytes(value) -> int
def classify_frame(total: int) -> str
```

**envelope**：

- success 键集恰 `{value,content}` 或加 `meta`；禁止 `error`。
- failure 键集恰 `{error,content}` 或加 `meta`；禁止 `value`。
- unknown 键集恰 `{error}`；禁止 `value/content/meta`。
- constructor 对 success/failure 把缺省 meta materialize 为 `{}`；validator 同时接受省略与显式 `{}`。
- content 1..16 个 block，每个恰 `{type,text}` 且 `type=="text"`、text 为 string（可为空）。
- error 恰 `{code,message}`；code 全匹配 `^[a-z][a-z0-9_]{0,63}$`；message ≤1024 UTF-8 bytes。message 必须拒绝：NUL；`Traceback (`；`stack trace`；`DEEPSEEK_API_KEY=`；`OPENAI_API_KEY=`；任何以 `/` 开头的空白分隔 token（Unix absolute path）、Windows drive 路径（`[A-Za-z]:` 后接反斜杠或 `/`）、以两个反斜杠开头的 UNC 路径。该谓词是构造期纪律的 backstop（生成消息一律只带相对路径），不是安全边界；测试需有正反例，包括 `File not found.` 与 `/etc/passwd`。
- `usage` 必须恰为 `{wall_ms}`；`wall_ms` 必须是非 bool、非负、安全的整数；任何额外键（如 `tokens`）→ `invalid_outcome`。
- `invalid_outcome` 只用于 `usage` 形状错误；envelope 键集、content block、error/code/message、meta、builtin meta 任一不合规均为 `invalid_tool_output`；`measure` 遇到非 JSON 值或 `CanonicalError` 也归一为 `invalid_tool_output`。渲染器返回非法 block 用 `renderers.RendererError("invalid_tool_content")`，不归 `ToolResultError`。

**meta 语义**：插件 wire meta 可缺省；host success/failure output materialize `{}`；计量把缺省规范化为 `{}`（2 bytes）；不向 wire frame 注入默认值。`assert_builtin_meta` 只允许 `None`/`{}`，拒绝非空 object——这是三个内建插件的 W4 policy，不是通用 envelope 规则。

**model text**：`join_content(content)` 校验 content shape，按 `"\n"` join，返回 **str**，不加尾 LF，不含 meta。返回 str 而不是 bytes，是因为唯一消费者 `tool_message["content"]` 是 JSON string（`worker.py:1069`），byte 比较由测试 `.encode("utf-8")` 完成。固定期望是 `one\n二\n三` 的 11 bytes。unknown result 的 `model_text` 恒为空串、不生成模型 continuation；该语义属于 `ToolDispatchResult` 构造合同，W2 只定义、不接线。

**计量**：

```text
measure = {
  "args":    len(J(args)),
  "value":   len(J(value)),
  "content": len(J(content)),
  "meta":    len(J({} if meta is None else meta)),
  "frame":   frame_bytes(value),
}
frame_bytes(value) = len(J({"ok":true,"v":2,"result":{"value":value}})) + 1
classify_frame: <=60000 within_builtin_target
                60001..65536 over_builtin_target_transport_valid
                >65536 stdout_limit_unknown
```

measure 自身不截断、不拒绝；调用方把 value/content/meta/args 与 descriptor limits 比较，超限是普通 `output_too_large`，不是 unknown。`frame_bytes` 必须真实序列化，不得用 48/49 常量估算。

## 测试设计与向量覆盖

四条 gate 都是独立脚本：`main()` 返回 int / `SystemExit`；exit 0 + 命令专属 `[passed]` 行 = 通过；exit 2 / `[SKIP]` = 未验证并阻塞 W2；exit 1 = 失败。全部 DB-free、Node-free、socket-free、无 capture、无 re-bless；期望值一律来自 `v24/s13/vectors/*`，不得由生产输出反推。`test_renderers.py` 允许 import `w1_reference.render_count` 作为**测试侧独立计数器**交叉验证；生产代码不得 import 它。

| Gate | 覆盖 | 断言要点 | 通过末行 |
|---|---|---|---|
| `test_descriptor.py` | `descriptor_v2.json` 16 case | 9 个 byte case 逐字节比 `expected_hex`；`descriptor_digest` 与 3 个完整 descriptor 一致；table case 用测试侧 deep-copy + delete/replace/add-extra 应用；`raw_json` 用唯一占位符拼回原文再走 `parse_descriptor`（不得先 `json.loads`）；内建 registry 通过路径 + 篡改 registry 的 unknown id/version 与 digest 不符探针；只有四个 reason 会逃逸；accepted 返回冻结副本且不改输入；不建 DB 连接；另加非向量负例：多故障优先级、深层重复键、`NaN`/±`Infinity`、非法 UTF-8、非 object 输入、`J` 的非 string 键/float/unsafe/lone surrogate | `[passed] W2 descriptor contract; cases=16; canonical_python=9; reasons=4` |
| `test_schema.py` | `schema_v2.json` 9 case | 13 allow / 29 deny / 13 invalid-allowed；nullable union；required/additional/items；JSON-distinct enum；depth/nodes/properties/enum 四组边界；Unicode-scalar 长度；root parameters/output；每条 first-error/path probe；无 default 注入；compiled closure 在多个 instance 上复用（无进程级缓存） | `[passed] W2 schema contract; cases=9; first_error_order=frozen; defaults_injected=false` |
| `test_renderers.py` | `renderers.json` 7 case + 21 内层 golden | 内嵌五键 case 与向量逐项相等（不含 `measures`）；每个 golden 的 content/meta 逐字节相等；`measure` 复现每个冻结 `measures`；`len(J(content))==27+escaped_len(T)` 对全部 21 例成立；manifest 字节、golden_digest、render_digest 命中三组固定值；registry 不可变、未知 ref、renderer 抛错、非法 content 的内部探针；`by_id` 忽略 digest 与 `lookup` 全等的区分；生产源码不含向量文件读取 | `[passed] W2 renderer contract; cases=7; golden_cases=21; digest_pairs=3` |
| `test_results.py` | `results_v2.json` 8 个 M2 case | success/failure/unknown 三个 envelope 逐字节；`usage` 三行（含 `tokens` → `invalid_outcome`）；两个 11-byte model_text 与 meta 排除；builtin meta 三态；9 行 cap−1/cap/cap+1；args 不含 frame/LF；四个 frame boundary；对 `prefix_scenarios` 的每个 candidate 复现冻结的 content/meta/measures；**不**实现或断言 `page_decision`/扫描/字段关系/选前缀；断言 3 个 M4 case 仍 `m4_pending`；负例 envelope 探针（多余键、缺 content、非法 code/message、非 object meta） | `[passed] W2 result contract; cases=8; envelope_bytes=3; frame_boundaries=4; replay_claimed=false` |

非向量负例探针不计入 40 case，但属于合同：descriptor 多故障优先级（17 步顺序）、深层重复键、`NaN`/±`Infinity`、非法 UTF-8、非 object 输入；`J` 的非 string 键、float、unsafe integer、lone surrogate；renderer 的 unknown id / unknown version / digest 不符；envelope 的多余键、缺 content、非法 code/message、非 object meta。这些探针只断言稳定 reason，不固定实现细节。

## 工作项与执行索引

人工量级沿用 B0：S < 1 人日，M 约 1–2 人日，L 约 2–3 人日；不含 gate 等待。

| Work item | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| W2-0 provenance | 固定基线 | 记录 HEAD/branch/upstream、`git status --porcelain=v2`、排序后的 tracked-file SHA manifest、Python/uv/Node/PG 版本、design/plan 输入 SHA；不再 stash/reset/checkout primary | execution record、仓库外 evidence | 无 | S |
| W2-1 canonical | 建立唯一 canonical leaf 与兼容 shim | 七个旧名字从 `registry.py` 移除并由 `canonical.py` 提供；`registry.RegistryError is canonical.RegistryError`；B0 与 W1 canonical 检查在未改调用点的情况下通过；`J`/`strict_loads`/`escaped_len` 有独立单测 | `canonical.py`、`registry.py` | W2-0 | S |
| W2-2 schema | 封闭 schema 子集 | `schema_v2.json` 9 case 全部命中；四组边界、first-error 顺序、path 格式、enum distinct、无 default 注入通过；`test_schema.py` exit 0 | `tool_schema.py`、`test_schema.py` | W2-1 | M |
| W2-3 descriptor | descriptor v2 校验 | `descriptor_v2.json` 16 case 全部命中（9 byte + 7 table，含 6 个 `raw_json`）；17 步顺序固定；四 reason 封闭；`test_descriptor.py` exit 0 | `descriptor.py`、`test_descriptor.py` | W2-1, W2-2, W2-4 | M |
| W2-4 renderers | 三个 renderer + registry + digest | 21 个 golden 的 content/meta/measures 全等；三组 digest 命中；`renderers.py` 不读向量、不 import `tool_results`；`test_renderers.py` exit 0 | `renderers.py`、`test_renderers.py` | W2-1 | M |
| W2-5 results | envelope + 预算 | 8 个 M2 case 命中；9 行 boundary、4 行 frame、2 个 model_text 全等；`page_decision` 未实现；`test_results.py` exit 0 | `tool_results.py`、`test_results.py` | W2-1（完整测量依赖 W2-4） | S |
| W2-6 design/README | 同步文件清单、gate 与 pin | design §7.1/§7.3/§7.4 修订；`DESIGN_SHA256` + `design_conformance.json` 原子 repin；span 只移位不改内容；`test_contracts.py` 与 `test_vectors.py` 立即复跑通过；README/ledger/matrix 结构更新 | 设计、README、ledger、matrix、`test_contracts.py`、`design_conformance.json` | W2-2..W2-5 | S |
| W2-7 serial evidence | 全量真实运行 | 24 条命令串行 exit 0 且末行匹配；记录 ISO 时间、source SHA、command、exit、末行、merged-log SHA-256、status；scope/credential/vector-diff 审计通过；无 exit 2 | execution record、外部日志 | W2-6 | M |
| W2-8 publish | 单一里程碑发布 | 按路径 `git add`；`git status` 复查暂存与凭据；commit `v24: add pure tool ABI host contract components`；`git push origin main` 成功；无 force | W2 allowlist | W2-7 | S |

依赖图：

```text
W2-0 → W2-1 → W2-2 ─┐
             ├→ W2-4 ┴→ W2-3
             └→ W2-5（完整测量断言需 W2-4）
W2-2/W2-3/W2-4/W2-5 → W2-6 → W2-7 → W2-8
```

W2-3 依赖 W2-4：descriptor 默认校验内建 registry。W2-4 与 W2-5 可并行实现；W2-5 的完整测量断言必须在 W2-4 落地后跑。

## Gate、证据与 scope audit

所有 Python 命令使用凭据清除前缀：

```bash
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1
```

四条新 gate：

```bash
uv run python v24/s13/test_descriptor.py
uv run python v24/s13/test_schema.py
uv run python v24/s13/test_renderers.py
uv run python v24/s13/test_results.py
```

四条新 gate 与下列 20 条继承命令合计 24 条；继承命令必须串行、按此顺序跑（`test_contracts`/`test_vectors` 在 design repin 后立即跑一次，最终全量再跑）：

```text
v24/s13/test_contracts.py
v24/s13/test_vectors.py
v24/s13/test_vectors.py --node
v24/b0/test_golden.py
v24/b0/test_golden.py --node
v24/load.py
v24/s1/setup_db.py --self-check
v24/s1/test_ddl.py
v24/s1/test_g1.py
v24/s2/test_g3a.py
v24/s3/test_g2.py
v24/s4/test_g2b.py
v24/s5/test_g4.py
v24/s6/test_g5.py
v24/s8/test_g7.py
v24/s7/test_g6.py
v24/s10/test_g9.py
v24/s11/test_g10.py
v24/s11/test_node.py --node
python -m v24.host.plugin_smoke --multilingual-smoke
```

三态：exit 0 + 命令专属 pass marker = passed；exit 2 / `[SKIP]` = unverified，阻塞 W2，不得记为通过；exit 1 / traceback / 缺 marker / 异常退出 = failed。每条命令记录 ISO 时间（带时区）、source SHA、candidate fingerprint、完整命令、exit、实际末行、merged-log SHA-256、status 与 note；日志留在 repo 外。

Scope audit：

```bash
git diff --exit-code -- v24/sql v24/s10 v24/s11 v24/load.py v24/b0
git diff --exit-code -- \
  v24/host/plugins.py v24/host/worker.py v24/host/line_json.py \
  v24/host/deepseek.py v24/host/journal.py v24/host/db.py \
  v24/host/process_io.py
```

另外必须逐项确认：八个 domain vector 字节未变；`design_conformance.json` 的差异只在 `design_input.sha256_at_review` 与受影响 span 的 `line_start/line_end`；所有 pinned span 的 heading 与 sha256 未变；生产源码无 `v24/s13/vectors` 读取；四个合同模块无运行时 import 边；closeout 仍 11/11，W2 是 extension evidence，不是第 12 条。

## File-by-file impact

### 新增生产模块

| 文件 | 内容 | 依赖 |
|---|---|---|
| `v24/host/canonical.py`（~180） | `SAFE_INTEGER_MAX`、`CanonicalError`、移入的 `RegistryError`/冻结类型/`pg_jsonb_text`/`descriptor_digest`、`compact_json`、`escaped_len`、`strict_loads` | 仅 stdlib |
| `v24/host/tool_schema.py`（~320） | 关键字闭集、结构/边界检查、compiled closure、first-error 实例校验、path 格式 | `canonical` |
| `v24/host/descriptor.py`（~280） | strict parse、关闭集/limits/annotations/depth/bytes、schema 委派、provide/render 身份、冻结返回 | `canonical`、`tool_schema`、`renderers` |
| `v24/host/renderers.py`（~300 + 内嵌数据） | 三个纯投影、不可变 registry、21 个五键 golden、两组 digest | `canonical` |
| `v24/host/tool_results.py`（~220） | envelope 构造/校验、usage、`join_content`、`measure`/`frame_bytes`/`classify_frame`、`ToolDispatchResult` | `canonical` |

实际行数会因内嵌 golden 数据高于设计稿的初始估算；估算不构成验收条件。

### 修改

| 文件 | 变更 | 约束 |
|---|---|---|
| `v24/host/registry.py` | 删除七个被移走的定义（含 `RegistryError`），改为 re-export | `ApprovedAdapter`、`descriptor` property、`match_pin`、artifact/environment 行为不变；`RegistryError` 身份不变 |
| `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md` | 仅 §7.1/§7.3/§7.4 | 不改 §3–§6；不把任何 gate 描述成已通过 |
| `v24/s13/test_contracts.py` | 仅 `DESIGN_SHA256` | 不弱化 inventory/span 断言 |
| `v24/s13/vectors/design_conformance.json` | 仅 design SHA + 受影响 span 行号 | 不改 case/status/expected |
| `v24/s13/README.md` | 四条命令、W2 scope、三态、非证明声明 | closeout 11/11 措辞保留 |
| `docs/reviews/v24-deviation-ledger-2026-10-23.md` | 追加 W2 小节 | 与既有 post-closeout 结构一致 |
| `docs/reviews/v24-conformance-matrix-2026-10-23.md` | 追加 W2 小节 | 只写实际结果 |
| `docs/reviews/v24-tool-plugin-abi-w2-execution-2026-10-30.md` | 新建 execution record | 不预填通过结果 |

### 新增测试

`v24/s13/test_descriptor.py`（~300）、`test_schema.py`（~260）、`test_renderers.py`（~260）、`test_results.py`（~200）。

规划评审：`docs/reviews/v24-tool-plugin-abi-w2-plan-critique-2026-10-30.md` 是 planning artifact（不是 gate 证据），与计划一起提交。

### 明确不变

`v24/sql/**`、`v24/s10/**`、`v24/s11/**`、`v24/load.py`、`v24/b0/**`、`v24/s13/test_vectors.py`、八个 domain vector、`vectors/README.md`、`v24/host/{plugins,worker,line_json,deepseek,journal,db,process_io}.py`、`v24/s13/plugins/**`、`v24/s13/fixtures.py`。设计稿 §5.4/§5.1 的文档修订属 M5；W2 不改 `v24-pg-agent-2026-10-22.md` 与 `v24-drift-factcheck-2026-10-29.md`。

## 风险、STOP 与回滚

无数据库/持久化/线格式迁移；兼容风险集中在 v1 字节与 conformance metadata。

| Stop | 触发与处置 |
|---|---|
| STOP-DG digest mismatch | 任一 golden/render digest 与冻结值不符。先查 `J` 的 key 顺序、转义、`measures` 是否误入；**不得**改向量、重 bless 或把 `measures` 加进 digest。 |
| STOP-D2 vector drift | 任一 domain vector 被改，或 `design_conformance.json` 出现超出 SHA/行号 repin 的差异。 |
| STOP-W wiring | 任一合同模块 import 运行时 host 模块，或生产代码读取 `v24/s13/vectors/*`。 |
| STOP-C cycle | `canonical` import 其他 host 模块，或 `registry` import 任一合同模块。 |
| STOP-V1 v1 变化 | B0 字节、provider/tool-message 字节或非 dict digest 异常类型变化。立即回退 extraction，不改 B0。 |
| STOP-S schema 歧义 | 某个冻结 case 无法由设计 §5.5 + 本计划的选择一致推出。停止并回设计评审，不为变绿而挑解释。 |
| STOP-SHA pin 冲突 | design、`DESIGN_SHA256`、mapping SHA、span 无法在不弱化断言、不改 pinned 内容的前提下自洽。停止 W2-6，不得继续 gate/commit/push。 |
| STOP-G 继承回归 | 任一继承命令失败，或必需的 Node 检查变成 unverified。 |
| STOP-X scope expansion | 实现需要 registry v2 类型、transport、dispatcher 映射、worker/provider 改动或子进程工具。 |
| STOP-B budget 合同 | 某个冻结 candidate 无法复现其 measures，或 W2 代码看起来必须实现选页逻辑。回设计，不把 W4 行为塞进 W2。 |

回滚：删除五个新模块与四个测试，恢复 `registry.py` 的原始实现，恢复 README/design/ledger/matrix/metadata。design 编辑、SHA 常量与 conformance metadata 必须一起回滚（只回滚一侧会故意留下红 gate）。不得删除/重写 W1 vector payload，不得 `git reset --hard` 或 force push。

实现期必须现场核对的两点：

1. 编辑 design §7 前先确认没有 pinned span 覆盖被改文本；只允许行号移位，span 内容 SHA 必须不变。
2. 读全 `descriptor_v2.json` 的 bounds 构造、renderer golden 与 `prefix_scenarios`，测试迭代真实数据，不按摘要重建期望值。

## 提交与推送

按 AGENTS.md：24 条 gate 全绿 → W2 收尾文档完成 → 按路径逐项 `git add`（新增五个模块、四个测试、README、design、`test_contracts.py`、`design_conformance.json`、ledger、matrix、execution record、本计划、plan critique）→ `git status` 复查暂存与凭据 → `git commit -m "v24: add pure tool ABI host contract components"` → `git push origin main`。禁止 `git add -A`、`git add .`、`--no-verify`、force push；远端分歧时 `git fetch` 后按需 rebase，无法安全合并则停下问用户。

## W2 不证明什么

- 不证明 M2 完成，也不证明 W3（registry/multi-tool/line-json v2）或 W4（dispatcher/worker/provider）任何行为。
- 不证明 renderer 在生产 dispatcher 中运行、不证明 content/meta 预算在真实调用中被执行。
- 不证明 read/list/search 的文件系统语义、分页收敛、12s 扫描预算或任何子进程行为。
- 不证明 replay/`no_replay`、journal 重放、tool message 字节稳定性（M4）。
- 新 gate 的 DB-free 不削弱 cross-language 证据：PostgreSQL 侧继续由 inherited `test_vectors.py` 证明。

## Oracle 裁决记录（2026-10-30）

三个 lane 中 `gpt-6.1-sol-xhigh` 与 `kimi-code-plan-cn/k3.1-pro` 完成，`claude-opus-5-5` 因 provider 401 失败。两条完成 lane 在 D1–D5 上完全一致；本计划采纳并补强如下：

- **D1**：两 lane 都要求提取 leaf。补强：同时移入 `RegistryError`（否则 `descriptor_digest` 的逐字搬迁会改异常合同），并加身份断言。
- **D2**：两 lane 都要求 W2 拥有 strict decoder。采纳；`raw_json` 六例是硬证据。
- **D3**：两 lane 都要求四条 gate。采纳，并把 design §7 的 gate 总数从 6 改为 9。
- **D4**：两 lane 都拒绝 `budget.py`。采纳。
- **D5**：两 lane 都拒绝完整映射表。采纳。
- **D6**：两条 lane 都要求四条 gate DB-free，并把 PostgreSQL 证据留给 inherited `test_vectors.py`（`E:1127-1134`）。采纳；W2 不重复 `setup_db()`。
- **D7**：lane 2 提出、lane 3 细化了 design SHA repin。采纳，并列出必须重算行号的 span 清单（§7.2、§8.2、§8.3、Appendix A）。
- **`join_content` 返回类型**：两 lane 都写 bytes；本计划改为 **str**。依据：设计 §5.4 写的是字符串 join，唯一消费者 `tool_message["content"]` 是 JSON string（`worker.py:1069`）；byte 比较在测试侧 `.encode("utf-8")` 完成。这是对 lane 建议的有据修正，不是遗漏。
- **renderer registry 默认值**：lane 2 用 duck-typed `render_registry`，lane 3 用不 import 的接口。本计划改为 `render_registry=RENDERERS` 的 fail-closed 默认：漏传也必须校验，避免 render 身份检查被静默跳过。

## References

- ABI 设计权威：`docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md` §3.1（descriptor 形状/limits）、§4.1–4.4（registry 类型、canonical/digest、向量）、§5.2（envelope）、§5.3/§5.3.1（renderer、`J`、`27+E(T)`）、§5.4（model text）、§5.5（schema 子集与顺序）、§5.6（预算）、§7.1/§7.3/§7.4（文件/测试/gate）、§10（M2）。
- 冻结向量：`v24/s13/vectors/{descriptor_v2,schema_v2,renderers,results_v2}.json`；格式与状态词表：`v24/s13/vectors/README.md`、`design_conformance.json`。
- W1 独立参考（仅测试可 import）：`v24/s13/w1_reference.py:28-62,82-96,153-239,314-315`。
- W1 计划与证据：`docs/plans/v24-tool-plugin-abi-w1-cross-language-vectors-2026-10-30.md`、`docs/reviews/v24-tool-plugin-abi-w1-execution-2026-10-30.md`。
- host 接缝：`v24/host/registry.py:23-145,148-256`、`plugins.py:24,40-83`、`worker.py:1027-1077,1302-1308`、`line_json.py:107-149`、`deepseek.py:341-392`、`journal.py:64-73`、`process_io.py:18-77`。
- 测试/文档约定：`AGENTS.md:1-79`、`v24/s13/README.md:1-17`、`v24/s13/test_contracts.py:1-139`、`v24/s13/test_vectors.py:283-288`、`v24/s11/test_node.py:143-169`。

## Result

W2 已按本计划完成并验证（2026-10-30）。

- 五个生产模块落地：`v24/host/{canonical,tool_schema,renderers,descriptor,tool_results}.py`；`registry.py` 只做 canonical 提取与 re-export，七个旧名字身份不变。
- 四条新 gate 实测 exit 0 并命中各自 marker：descriptor 16（9 byte：6 canonical + 3 descriptor；7 table）、schema 9、renderers 7（21 内嵌 golden + 3 manifest + 1 digest 表）、results 8（3 个 `m4_pending` 未执行）。
- design §7.1/§7.3/§7.4 已修订；design SHA-256 更新为 `0de115c947967cc92a5e15ec7bf7c53f38abe78bcfcc89f77e06042be1313d04`；`DESIGN_SHA256` 与 `design_conformance.json` 原子 repin；§7.2/§8.2/§8.3/Appendix A 只发生行号移位，heading/span SHA 未变；八个 domain vector 字节未变。
- 24 条串行命令全部 exit 0，无 exit 2/SKIP/`not_run`；closeout 仍 11/11；`v24/sql/**`、`v24/s10/**`、`v24/s11/**`、`v24/load.py`、`v24/b0/**` 与七个运行时 host 文件零 diff；四个合同模块无运行时 import 边，生产代码不读 `v24/s13/vectors/*`。
- 证据、命令、末行与日志 SHA 见 [`W2 execution record`](../reviews/v24-tool-plugin-abi-w2-execution-2026-10-30.md)；本计划与 plan critique 作为 planning artifacts 一并提交。
- W2 不证明 M2 完成、W3 registry/line-json v2、W4 dispatcher/worker/provider、文件系统工具语义或 replay；这些仍按设计归后续阶段。
