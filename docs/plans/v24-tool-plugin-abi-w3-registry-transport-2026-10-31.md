# v24 Tool/Plugin ABI W3：Registry 与 transport Deep Plan

日期：2026-10-31。状态：W3-1…W3-6 implemented/verified；实测结果见文末 Result，发布按 W3-7 执行。W3 是 M2 子阶段，不是 M2 完成。

基线：`main` @ `e2a1334`（W2 hardening 之后），design SHA-256 `2606aedc7135e7085219d0a9c99d1ccca5c22ee33baee6a82dd6f137ce7cac24`。W3 是 design §10 M2 的 registry/transport 子阶段，**不是 M2 完成**。

---

## Goal 与范围

在 `v24/host/` 内交付两件生产变更，其余都是证据与文档：

1. **v2 审批模型**（`v24/host/registry.py`）：`_ApprovedEntry` 无字段 mixin、`ApprovedTool`、`ToolBinding`、`ApprovedPlugin`、`ApprovedPlugin.from_manifest()`、registry union 索引、`match_tool()`，以及 `match_pin()` 的 v2 拒绝分支。一个 install 的 `provides` 可含 1..16 个工具，全部匹配在 **spawn 之前**完成。
2. **独立 v2 transport**（`v24/host/line_json.py`）：`build_frame_v2()` 与 `_classify_v2()`，按 `entry.protocol` 静态分流，无握手、无降级；v1 构帧/解析/异常 reason 逐字节不变。

W3 **不**交付：`plugins.py` v2 分支、`worker.py` 的 `model_text`、`deepseek._tools` 接受 v2、`v24/s13/plugins/*`、`fixtures.py`、`test_tools.py` / `test_lifecycle.py` / `test_node.py`、artifact digest 实算（M3）、任何真实 provider、数据库或 Node 依赖。

**阶段冲突已裁决**：`docs/reviews/v24-tool-plugin-abi-w2-execution-2026-10-30.md:107` 把 `plugins.py` v2 列入 W3 未证明项；`docs/plans/v24-tool-plugin-abi-w2-host-contracts-2026-10-30.md:101` 给出更精确的依赖方向——W3 只让 `registry.py` 依赖 `descriptor`/`renderers`/`tool_schema`，W4 才让 `plugins.py`/`worker.py` 依赖 `tool_results`。**以 W2 plan 为准**：`plugins.py` v2 属 W4。

---

## Done when

1. `v24/s13/test_registry.py` 与 `v24/s13/test_line_json.py` 两条新命令 exit 0 且末行标记匹配本文 §Gate；W2 的四条 gate 与 W1/B0/closeout/G9/G10/Node/multilingual 全部仍 exit 0（合计 **26** 条串行命令）。
2. `registry.py` 能由 `manifest.one_install_two_provides` 的冻结 semantic `input`（其 `compact_json` 等于 `expected_hex`）构造出 `ApprovedPlugin`，其 `manifest_digest` 逐字节等于 `0ad584415af8743045dd12275a54fa2f43a65395fc8669753416688c9c3e3db5`，`list`/`search` 两个 key 各自匹配到不同 `ApprovedTool`。
3. 六类 `match_tool()` 失败与六类构造失败全部在 **零 spawn**（零 `require_artifact` 调用、零 `run_process` 调用）下返回规定 reason。
4. v2 请求帧 5 个 byte case 与 2 个 response byte case 逐字节等于冻结向量；v1 构帧与解析字节不变（由 B0 gate 与 W3 的 v1 探针共同证明）。
5. `test_line_json.py` 逐行复现 55 行 corpus 分类（46 invalid + 9 whitespace）；模块常量 `STDOUT_LIMIT=65536`、`STDERR_LIMIT=16384` 仍在。
6. 冻结向量零 diff：`v24/s13/vectors/*.json` 除 `design_conformance.json` 的 repin 元数据外无改动；`frames_v2.json` 的 10 个 case 仍为 `m2_pending`。
7. `v24/sql/**` 零 diff；`plugins.py` / `worker.py` / `deepseek.py` / `journal.py` / `db.py` / `process_io.py` 与五个 W2 模块零 diff。
8. closeout 仍 **11/11**；s13 不被称为第 12 条 closeout。

---

## Current-state analysis

### v1 调用链与本阶段触点

```text
startup: ApprovedAdapter(...) → ApprovedAdapterRegistry(entries)      ← W3 扩为 union
claim → PluginDispatcher._tool:      match_pin → tool_key 比较 → require_artifact → line_json.run(v1)
claim → PluginDispatcher._resource:  lookup_install → require_artifact → line_json.run(v1)
line_json.run: build_frame(1) → _spec(adapter) → run_process → timeout→stdout→stderr→exit→_frames(splitlines)→_success/_error
```

- `ApprovedAdapter` 是 **17** 字段 frozen dataclass（`registry.py:67-83`）；`descriptor` 是 property，现场生成 `{v:1, tool:{description, parameters}}`（`:126-130`）；`descriptor_digest` 在 `__post_init__` 重算（`:113-116`）；`require_artifact()`（`:145-171`）与 `environment(source=None)`（`:173-177`）只依赖 `artifact_path`/`artifact_digest`/`cwd`/`environment_allowlist`。
- `ApprovedAdapterRegistry.__init__` 目前**只接受** `ApprovedAdapter`（`:188-189`），按五字段 `canonical_key()` 建索引，拒绝重复 install key（`:191-193`）与重复 `adapter_id`（`:194-195`）；`lookup_install` 缺项 → `adapter_not_approved`（`:223-226`）；`match_pin` 依次比 descriptor 文本与 digest（`:239-250`）。
- `line_json.build_frame` 用 `_canonical`（`sort_keys=True`、compact、`ensure_ascii=False`、`allow_nan=False`）加一个 LF（`:72-86`）；`_frames` 用 `text.splitlines()` 并拒绝第二行（`:107-125`）；`_success_frame` 要求 `result` 是**字符串里的一个 JSON object**（`:128-140`）；`_error_frame` 要求 `{ok,error,message}`（`:143-149`）；`run()` 分类顺序 timeout → stdout_limit → stderr_limit → exit∉{0,3} → 帧解析 → 帧形状（`:152-205`）。

### W2 已交付、W3 复用的原语（hardened 版本）

- `canonical.py`（264 行）：`RegistryError`（无 `.reason`）、`_freeze`、`pg_jsonb_text`、`descriptor_digest`、`compact_json`（显式栈、J 域、`circular_reference`）、`strict_loads`（按位数预拒超安全整数）、`escaped_len`。
- `descriptor.py`（322 行）：`validate_descriptor(descriptor, *, provide_key=None, render_registry=RENDERERS) -> _FrozenDict`，17 步固定顺序，只逃逸四个 `DESCRIPTOR_REASONS`（`invalid_descriptor`、`descriptor_key_mismatch`、`renderer_not_approved`、`renderer_digest_mismatch`）；解码/词法失败一律归一为 `invalid_descriptor`。
- `tool_schema.py`（383 行）：`assert_supported(schema, *, kind)`、`compile_schema(schema, *, kind) -> Callable[[Any], None]`（深冻结 + 返回 closure，**无进程级 cache**，生命周期归调用方）、`validate`、`schema_metrics`。
- `renderers.py`（288 行）：`RendererRef(id, version, digest)`、`RendererRegistry.by_id()`/`.lookup(ref)`（三方全等，否则 `renderer_not_approved`）、`RENDERERS`；`fn` 抛任何异常重分类为 `render_failed`。
- `tool_results.py`（297 行）：`CODE_RE`、`MAX_MESSAGE_BYTES=1024`、`FORBIDDEN_MESSAGE_FRAGMENTS`、`_assert_jsonable`、`_message_is_leaked`、`success_output`/`failure_output`/`unknown_output`、`assert_*_output`、`measure`、`frame_bytes`、`classify_frame`、`ToolDispatchResult`。
- 兼容契约：`v24.host.registry` 仍 re-export `canonical` 的七个名字且**对象身份相同**（W2 record `:67`）。

### W1 冻结向量是 W3 的字节权威

`v24/s13/vectors/frames_v2.json`，10 个 case 全 `m2_pending`：

| 类别 | case | 关键事实 |
|---|---|---|
| build | `frame.request.invoke` | 115 B，`sha256=67632bc3…adc757c`，键集 `{v,operation,reservation,tool,args}` |
| build | `frame.request.prepare` / `release` / `inspect` | 各 122 B，**无 `tool` 键**，`args` 只含 `install_id` |
| build | `frame.request.utf8_sort_trap` | 110 B，`sha256=b358802f…3bb88c48`，args 键序 `a` < U+E000 < U+10000 |
| parse | `frame.response.success` | 68 B，`{"ok":true,"result":{"meta":{},"value":{"path":"README.md"}},"v":2}\n` |
| parse | `frame.response.known_error` | 76 B，`{"error":{"code":"not_found","message":"File not found."},"ok":false,"v":2}\n` |
| table | `frame.response.whitespace_corpus` | **9 行**，全 `success`：SP/HT 前缀、CRLF 结尾、`u2028_string`、`prepare_True`/`release_True`/`inspect_known`/`inspect_absent` |
| table | `frame.response.invalid_corpus` | **46 行**，reason 闭集 `{eof, extra_frame, bad_frame, version_mismatch, stdout_not_utf8}` |
| table | `frame.process.unknown_outcomes` | `outcomes=[timeout,stdout_limit,stderr_limit,abnormal_exit]`；limits `stdin=1048576/stdout=65536/stderr=16384`；**5 条 build 侧 `bad_request`** |

`manifest_adapter_v2.json` 的 5 个 case：`manifest.adapter.python_read`（89 B，`90c4dca5…`）、`manifest.adapter.node_list_search`（87 B，`06451360…`）、`manifest.one_install_two_provides`（4745 B，`0ad58441…`，status `provisional_w2_pending`，provides = `list`/`search`）、`manifest.five_field_key`（**`m3_pending`**，artifact digest 未实算）、`manifest.artifact_digest_pending`（`m3_pending`）。

向量状态口径沿用 W2 先例：gate **执行** `m2_pending` case 但不改 `status`（W2 `test_results.py` 对 `m4_pending` 正是显式断言保持 pending）。W3 不新增、不改写、不 re-bless 任何 vector case。

### 设计稿对本阶段的硬约束

- §2.3（`:163-199`）：v2 用两个**新类**，不改 `ApprovedAdapter`；两者共享无字段 mixin 的 `require_artifact()`/`environment()`；`lookup_install` 返回 union；`match_tool(install, pin, key)` 返回 `ToolBinding`；v1 binding 现场合成 `render=None` 的 `ApprovedTool`；`match_pin(v2)` 抛 `protocol_mismatch`。
- §2.4（`:200-221`）：多工具 manifest 的 `provides[]`；`descriptor.v` 混用 → `mixed_descriptor_versions`；`provides[].key != descriptor.tool.key` → `descriptor_key_mismatch`；SQL 不校验，host 构造期校验，未批准 install 在 spawn 前 fail closed。
- §4.1（`:456-479`）：四个接口的签名与全部失败 reason；`match_tool` 固定六步；`ApprovedPlugin.__post_init__` 六项附加校验（protocol、tools 1..16 且 key 唯一、每个 `descriptor["v"]==2` 且 `tool["key"]==key`、`workspace_root` 绝对/realpath/非 symlink、每个 `render` 在 RenderRegistry 中存在且 digest 全等、`timeout_ms <= timeout_cap_ms`）。
- §3.4（`:409-440`）：`1 <= T <= C <= 25000`，`timeout_cap_ms` 默认 25000。
- §5.1（`:531-591`）：v2 键集、按 **LF 字节**分帧、禁止 `splitlines()`、stdout 65536（含末尾 LF）/stderr 16384/stdin 1 MiB、v1 解析器完全不动、v2 用独立解析器。
- 附录 C（`:1183` 起，2026-10-31 规范补充）：C.2 规定「语法合法但数值越出 `J` 域的 success `value`，**W3 按普通 failure `invalid_tool_output` 处理，不判 unknown**」；C.3 规定 renderer 失败分类；C.6 规定 `J` 深度与循环。（C.2 的 W3 failure 映射经 Phase 6 批评后撤回，见 D14/C.8。）

### 三态 gate 约定

`v24/s13/README.md:30`：exit 0 + 命令专属 `[passed]` 末行 = 通过；exit 2/`[SKIP]` = 未验证（阻断完成）；exit 1 或缺标记 = 失败。基线是 W2 hardening 的 24 条串行命令（`docs/reviews/v24-tool-plugin-abi-w2-execution-2026-10-30.md:74` 起），W3 追加两条后为 26 条。

---

## 决策记录

每条给「选择 / 拒绝方案 / 证据 / 验收」。

### D1：`double_lf` 归 `extra_frame`，以冻结向量为准，经附录 C 修正

**选择**：`raw.count(b"\n") > 1` 一律 `extra_frame`；缺末尾 LF、LF 后有尾部垃圾、BOM、非法 JSON/重复键/NaN/Infinity/孤立代理项一律 `bad_frame`。设计 §5.1 `:576` 的「多一个空行……都是 `bad_frame`」是错句；修正以 **附录 C.7** 形式追加，**不**原地修改 §5.1。

**拒绝方案**：

- 把 `double_lf` 判成 `bad_frame` —— 与冻结向量冲突，且向量无 re-bless 通道。
- 原地改 §5.1 —— §5.1 是 pinned span（`design_conformance.json:immutable_required_suites[2].design_sections[0]`，531–591，`sha256=b684580fffa94456a9e376a47d5836be141f66cd95ce0f15c40dbe9c9e53b738`）。同一日 W2 hardening 已确立做法：pinned span 不原地改，规范补充进附录 C，只 repin 整文档 SHA（`docs/reviews/v24-tool-plugin-abi-w2-execution-2026-10-30.md:118`）。原地改会让 span 内容 SHA 变化，等于改动已评审文本。

**证据**：`frames_v2.json` 的 `double_lf` 与 `extra_frame` 两行都是 `extra_frame`；`w1_reference.classify_response` 的 LF 计数检查先于 `endswith`；W2 hardening 的附录 C 先例。

**验收**：46 行 invalid corpus 逐行一致；附录 C.7 写入后 `test_contracts.py`/`test_vectors.py` exit 0，且**所有 span 的 heading、行号、内容 SHA 与 repin 前完全相同**（只有整文档 SHA 变）。

### D2：`ApprovedPlugin.from_manifest()` 是 W3 生产 API

**选择**：W3 拥有它，签名 `from_manifest(manifest, *, language, artifact_digest, adapter_id, argv, cwd, environment_allowlist, workspace_root, timeout_ms=5000, timeout_cap_ms=25000, stdout_limit=65536, stderr_limit=16384)`；`manifest` 接受 `dict | bytes | str`。`language` 既填入 `ApprovedPlugin.language`，也用于派生 `adapter_declaration_digest(language)`。

**拒绝方案**：只做 `__post_init__`，把 manifest digest / mixed-version / provide-key 校验散到 W4 fixtures —— digest 会漂到 fixture 里，`test_registry.py` 无法证明 digest 与构造校验，且 W4 会出现第二份 `compact_json` 调用点。

**证据**：§2.4 明说「host registry 在构造 `ApprovedPlugin` 时校验」；`manifest.one_install_two_provides` 的 `first_production_stage` 是 M2。

**验收**：用生产 API 复现 4745 B manifest 与 `0ad58441…` digest；`mixed_descriptor_versions`/`descriptor_key_mismatch`/`timeout_exceeds_cap` 各一条负例。

**边界**：`artifact_digest` 由调用方传入；`from_manifest` 不读取 artifact 字节、不执行插件、不实算 artifact digest（M3）。路径元数据检查仍会发生：`cwd` 必须是已存在的绝对目录，`workspace_root` 必须 absolute/realpath/isdir。

**digest 输入语义**：`bytes` 用原始字节；`str` 先 UTF-8 编码；`dict` 用 `compact_json(manifest)`。冻结向量以 `case["input"]`（dict）为门禁输入，`compact_json(input)` 等于 `expected_hex`，故 `0ad58441…` 可复现。该语义与 design §4.4 的 `sha256(manifest_bytes)` 一致（byte 输入以字节为权威），不采用 lane 2 的「一律 canonical」写法。

### D3：v2 错误帧复用 `tool_results.assert_unknown_output()`

**选择**：`line_json` 导入 `tool_results`，对 exit 3 的 `{ok,v,error}` 调 `assert_unknown_output({"error": error})`，捕获 `ToolResultError` 归一为 `bad_frame`。依赖方向 `line_json → tool_results → canonical`。

**拒绝方案**：在 `line_json` 内复制 `CODE_RE`/`MAX_MESSAGE_BYTES`/泄漏词表 —— 两套词表必然漂移；`tool_results.unknown_output` 已把错误信封定义成恰为 `{"error":{"code","message"}}` 的闭集。

**证据**：`tool_results` 的 `_assert_error`/`_message_is_leaked` 覆盖 code regex、1024 B、绝对路径、盘符、UNC、堆栈、环境变量、NUL；`invalid_corpus` 的 11 行错误 shape/leak 用例与之重合。

**验收**：11 行 → `bad_frame`；`safe_error_26..29` → `known_error`；`import v24.host.line_json` 无环。

### D4：设计修订范围与原子 repin

**选择**：同一变更集完成（a）附录 C.7（LF 分帧）与 C.8（transport 层 `J` 域不可达，见 D14）追加，（b）§4.1 增补 closure 所有权与构造 reason 词表，（c）§7.1/§7.3/§7.4 措辞更新（三者非 pinned），（d）整文档 SHA 重算并同步 `test_contracts.py:DESIGN_SHA256` 与 `design_conformance.json:design_input.sha256_at_review`。

**拒绝方案**：留到 M5 —— M3/M4 会照与向量矛盾的规格实现；只改实现不改文档 —— 下一阶段读到反例。**也拒绝**修改 `test_contracts.py` 的断言逻辑或删除 span 检查。

**证据**：W2 与 W2 hardening 两次都以原子 repin 收口（`docs/reviews/v24-tool-plugin-abi-w2-execution-2026-10-30.md:57-59`、`:118`）。

**验收**：`git diff --stat` 显示 design + 两个 pin 文件同批；`test_contracts.py`、`test_vectors.py` 立即 exit 0；执行记录列出旧/新 design SHA。

### D5：v2 帧序列化 = `canonical.compact_json` + 单个 LF

**选择**：`build_frame_v2` 用 `compact_json(frame)`，再追加恰一个 `b"\n"`。

**拒绝 `line_json._canonical`**：它放行 float/指数、放行 `|n| > 2^53-1`、对孤立代理项会产出无法 UTF-8 编码的值；`compact_json` 对这三类显式抛 `CanonicalError`。

**拒绝 `pg_jsonb_text`**：它输出 `{ "k": v }`（`, ` 与 `: ` 分隔）且键按「UTF-8 字节长度优先、再字节序」排序，与 7 个冻结帧字节完全不同。

**证据**：`w1_reference.frame_request` 用 `compact()`；5 个请求 case 的 `expected_text` 都是无空格、键序与 `compact_json` 一致的 compact JSON。

**验收**：5 个 byte case 的 `expected_hex`/`expected_length`/`expected_sha256` 逐字节相等；float、unsafe integer、lone surrogate 的 args 归一为 `bad_request`，不泄漏 `CanonicalError`。

### D6：v2 只按 LF 字节分帧，禁用 `splitlines()`

**选择**：`_classify_v2` 只用 `raw.count(b"\n")`、`raw.endswith(b"\n")`、最后 LF 切分与 `.strip(" \t\r")`。

**拒绝 `str.splitlines()`**：它把 U+2028/U+2029/U+000B/U+000C/U+0085 也当行边界，会把 `u2028_string` 这个合法成功帧误判为 `extra_frame`，也无法表达「LF 不在末尾」。v1 的 `splitlines()` 行为必须保留（B0 冻结），两套 parser 不共用。

**验收**：9 行 whitespace 全 `success`；55 行 corpus 分类与向量逐行一致。

### D7：静态协议分流用 `getattr(entry, "protocol", 1)`

**选择**：`_protocol(entry)` 读 `getattr(entry, "protocol", 1)`，只接受精确整数 1 或 2，其余（含 bool）抛 `LineJsonPreflight("protocol_mismatch")`。

**拒绝 `isinstance(entry, ApprovedPlugin)`**：会让 `line_json` 反向 import `registry`。**拒绝给 `ApprovedAdapter` 加 `protocol` 字段**：破坏 v1 构造签名与 17 字段基线。

**验收**：v1 entry 字节与分类不变；v2 走 v2；`protocol=3` 在 spawn 前失败。

### D8：schema closure 由 `ApprovedTool` 自己编译并持有

**选择**：`parameters_check`/`output_check` 为 `field(init=False, default=None, compare=False, hash=False, repr=False)`；`__post_init__` 在 descriptor 校验冻结后调 `compile_schema`，用 `object.__setattr__` 装入。

**拒绝方案**：把 closure 作为 init 字段由 `from_manifest` 注入 —— 调用方可以塞入与冻结 descriptor 不一致的校验器；`dataclasses.replace` 也不会重算。

**证据**：`compile_schema` docstring 明确 closure 生命周期归调用方且无进程级 cache；`_FrozenDict` 不可 hash，故 `descriptor`/`output_schema` 需 `hash=False`。

**验收**：两个相同 descriptor 的 `ApprovedTool` 相等（closure 不参与比较）；`replace(cwd=…)` 等无关字段后 `__post_init__` 重跑、closure 仍与 descriptor 一致；只改 `descriptor` 而不同步 `descriptor_digest`/`timeout_ms`/`render`/`output_schema` 必须 `approved_tool_invalid`；v2 closure 对合法 args/value 不抛、对非法实例抛 `InstanceError`；v1 合成项两个 closure 均为 `None`。

### D9：`ApprovedPlugin` 字段集与五字段 key 不变

**选择**：复制 `ApprovedAdapter` 的进程/制品字段，另加 `tools: tuple[ApprovedTool, ...]`（**必填**，1..16）、`workspace_root: str`（**必填**）、`timeout_ms=5000`、`timeout_cap_ms=25000`、`stdout_limit`/`stderr_limit`、`protocol=2`。**不设** plugin 级 `descriptor_digest`/`tool_key`/`description`/`parameters`。

**拒绝方案**：在 plugin 上加「digest of digests」；给 `tools`/`workspace_root` 空默认值（空值本就非法，默认值只会把错误推迟到别处）。

**证据**：§4.4 规定五字段 key 已覆盖 protocol 与工具集身份；单工具事实属于 `ApprovedTool`。

**验收**：`canonical_key()` 仍返回五元组；`manifest.five_field_key` 的字段闭集复现。

### D10：无字段 mixin `_ApprovedEntry` 承载四个共享成员

**选择**：普通 class（非 dataclass、无字段、无注解），把现有 `artifact_path`（property）、`canonical_key()`、`require_artifact()`、`environment(source=None)` 原样移入；`ApprovedAdapter` 与 `ApprovedPlugin` 都继承它。

**拒绝方案**：复制两份方法（安全逻辑双份漂移）；改成模块级函数（要改 `plugins.py` 调用点，且 `plugins.py` 属 W4）。

**验收**：`dataclasses.fields(ApprovedAdapter)` 名字序列与当前 17 项完全一致；两类 entry 的 artifact reason 与 allowlist 行为一致。

### D11：v1 `match_tool()` 复用 `match_pin` 语义，且绝不编译 v1 schema

**选择**：v1 分支现场合成 `ApprovedTool(key=entry.tool_key, descriptor=entry.descriptor, descriptor_digest=entry.descriptor_digest, timeout_ms=entry.timeout_ms, render=None, output_schema=None)`，两个 closure 为 `None`；比较顺序与 `match_pin` 同序。

**拒绝方案**：用 v2 validator 重新解释 v1 descriptor —— s11 的 v1 `parameters` 带 `additionalProperties: true`，`assert_supported(kind="parameters")` 会抛 `unsupported_schema`，所有 v1 install 会立即不可用。

**证据**：`v24/s11/plugin_fixtures.py` 的 v1 descriptor 形状；`tool_schema.assert_supported` 的根约束。

**验收**：v1 binding 的 descriptor bytes/digest 与 `plugin_fixtures` 一致；G10-A 全绿。

### D12：构造失败用 `RegistryError(<token>)`，匹配失败用 `AdapterNotFound.reason`

**选择**：v2 审批构造的 **14 个专用 token 闭集**（`RegistryError(token)`，以 `token` 为唯一参数）：

| 新增 token（W3 引入） | 复用既有 token |
|---|---|
| `approved_tool_invalid` | `invalid_descriptor` |
| `protocol_invalid` | `descriptor_key_mismatch` |
| `tools_invalid` | `renderer_not_approved` |
| `duplicate_tool_key` | `renderer_digest_mismatch` |
| `workspace_root_invalid` | `mixed_descriptor_versions` |
| `timeout_cap_invalid` | `timeout_exceeds_cap` |
| `manifest_invalid` | |
| `adapter_digest_mismatch` | |

**闭集边界**：14 token 只覆盖 v2 构造的**新增判定点**；`_hex64` 与 descriptor-digest 不一致仍用 v1 已有的 prose 消息，`ApprovedPlugin` 的进程/制品字段校验也逐字沿用 v1 prose。因此不得把该词表表述为「所有构造失败都归一为 token」；gate 对这两类分别断言 token 与 prose 子串。

匹配期失败仍只走 `AdapterNotFound.reason`：`install_invalid`、`adapter_not_approved`、`pin_key_mismatch`、`tool_not_approved`、`descriptor_missing`、`descriptor_digest_missing`、`descriptor_mismatch`、`descriptor_digest_mismatch`、`protocol_mismatch`。

**拒绝方案**：把构造失败也塞进 `AdapterNotFound`（启动失败与派发失败混成一个面）；给 `RegistryError` 加 `.reason`（W2 的对象身份与 v1 自由文本 raise 依赖它当前形状）；用 `protocol_mismatch` 表示构造期协议错误（与匹配期 reason 撞名）。

**证据**：`RegistryError` 无 `.reason`；`plugins.py:43-45` 只捕获 `AdapterNotFound`，所以构造错误不会被吞成 failure receipt。

**验收**：`str(exc)` 恰为 token（`exc.args == (token,)`）；14 个 token 各至少一条探针；`AdapterNotFound` 的 9 个 reason 一字不改。

**Ledger**：8 个新增 token 无向量证据，属 W3 新造 host 内部合同，必须写入 `docs/reviews/v24-deviation-ledger-2026-10-23.md` 的 `D-ABI-W3-*`，并声明「不进 wire、不进 SQL effect code 闭集、不进 dispatcher reason」。

### D13：v2 成功帧的 `result` 按 operation 封闭

| operation | `result` 精确约束 |
|---|---|
| `invoke` | `{"value"} ⊆ keys ⊆ {"value","meta"}`；`meta` 出现时必须是 dict |
| `prepare` | 恰 `{"prepared"}`，值必须是 bool `True`（`1` 不接受） |
| `release` | 恰 `{"released": true}` |
| `inspect` | 恰 `{"observed"}`，值 ∈ {`known`,`absent`} |

**拒绝方案**：只检查 `result` 是 dict —— `prepare_shape_41` 等五个 shape 负例将无法拒绝。

**证据**：`invalid_corpus` 的五条 shape 行与 `whitespace_corpus` 的四种 operation 成功行。

**验收**：5 条 shape 负例全 `bad_frame`；4 条操作成功行全 `success`。

### D14：撤回 transport 层 `J` 域 failure，改由附录 C.8 澄清

**选择**：v2 帧解析使用 `strict_loads`，因此 float、指数、超安全整数、`NaN`/`Infinity`、孤立代理项、重复键在解码阶段就已是 `bad_frame`（unknown）；**不存在**「语法合法但越出 `J` 域」的 success `value`，附录 C.2 最后一句在 transport 层不可达。W3 撤回「`J` 域越界 → failure `invalid_tool_output`」的映射，并在附录 C.8 明确：`invalid_tool_output` 的 failure 映射属于 W4 的 envelope 构造（值来自 Python 对象而非字节流）。

**拒绝方案**：（a）在 `strict_loads` 之后再加一次 `compact_json` 探测 —— 不可达，永不触发；（b）改用宽松解码器再按位置回退 —— 需要两套解码语义，且会让 §5.1 明确拒绝的 float/NaN 帧变成 failure，超出 W3 范围且无向量覆盖。

**证据**：`canonical.strict_loads` 用 `parse_float=no_float`、`parse_constant=no_constant`、位数预检拒超安全整数；`invalid_corpus` 的 `nan`/`infinity` 行都要求 `bad_frame`。

**验收**：新增 2 条探针（float value、超安全整数 value）断言 `bad_frame`；55 行 corpus 分类不变；C.8 落地后与 C.2 的措辞冲突在同一变更集内消除。

### D15：`manifest.five_field_key` 维持 `m3_pending`

**选择**：执行其五字段 `expected` 断言，但不实算 artifact digest、不改 `status`/`first_production_stage`、不计入 M3 证据。

**拒绝方案**：跳过该 case（丢五字段与 manifest 的联动）；把它改标成 M2 已完成（违反无 re-bless 规则）。

---

## 组件设计

### `v24/host/registry.py`

新增 import：`from .descriptor import DescriptorError, validate_descriptor`、`from .renderers import RENDERERS, RendererRef`、`from .tool_schema import SchemaError, compile_schema`。三者都不 import `registry`，不成环。

#### `_ApprovedEntry`（无字段 mixin）

```python
class _ApprovedEntry:
    @property
    def artifact_path(self) -> str: ...      # argv[1]
    def canonical_key(self) -> tuple[str, str, str, str, str]: ...
    def require_artifact(self) -> None: ...  # 原样搬迁，reason 五项不变
    def environment(self, source=None) -> dict[str, str]: ...
```

#### `ApprovedTool`

```python
@dataclass(frozen=True)
class ApprovedTool:
    key: str
    descriptor: dict = field(hash=False)
    descriptor_digest: str
    timeout_ms: int
    render: RendererRef | None
    output_schema: dict | None = field(hash=False)
    parameters_check: Callable | None = field(init=False, default=None, compare=False, hash=False, repr=False)
    output_check: Callable | None = field(init=False, default=None, compare=False, hash=False, repr=False)
```

`__post_init__` 固定顺序：

1. 形状：`key` 非空 str；`descriptor` dict；`timeout_ms` 为非 bool int 且 `(0, 300000]`（宽界用于 v1 合成项与 lifecycle；v2 工具超时随后被 descriptor 的 `(1, 25000]` 与 plugin cap 双重收窄）；`render` 为 `None|RendererRef`；`output_schema` 为 `None|dict`。否则 `RegistryError("approved_tool_invalid")`。
2. `descriptor_digest` 过 `_hex64`。
3. `v = descriptor.get("v")`；`type(v) is not int` → `RegistryError("invalid_descriptor")`（缺失 `v` 不得泄漏 `KeyError`）。按 v 分支：
   - **v==1**（仅 v1 合成项）：要求 `render is None and output_schema is None`，否则 `approved_tool_invalid`；`_freeze` descriptor；两个 closure 保持 `None`。**不得调用 `compile_schema`**。
   - **v==2**：`frozen = validate_descriptor(descriptor, provide_key=key)`；`DescriptorError` → `RegistryError(e.reason)`（四个 reason 原样透传）。随后一致性：`timeout_ms == frozen["tool"]["limits"]["timeout_ms"]`、`render == RendererRef(**frozen["tool"]["render"])`、`output_schema == frozen["tool"]["output_schema"]`，任一不等 → `approved_tool_invalid`。再 `object.__setattr__` 写回 `descriptor=frozen`、`output_schema=frozen["tool"]["output_schema"]`（**必须换成冻结副本**，否则调用方的可变 schema 会留在冻结审批对象里）、`parameters_check=compile_schema(frozen["tool"]["parameters"], kind="parameters")`、`output_check=compile_schema(frozen["tool"]["output_schema"], kind="output_schema")`；`SchemaError` → `RegistryError("invalid_descriptor")`。
   - 其它 v → `RegistryError("invalid_descriptor")`。
4. `descriptor_digest(self.descriptor) == self.descriptor_digest`，否则沿用 `registry.py:115-116` 的 prose 消息。

Renderer 权威固定为模块级 `RENDERERS`，**无注入参数**。便利构造 `from_descriptor(descriptor, *, key)` 是 `from_manifest` 的唯一入口：**先** `validate_descriptor(descriptor, provide_key=key)` 取冻结副本，**再**从冻结副本派生 `descriptor_digest`/`timeout_ms`/`render`/`output_schema`；派生期任何 `TypeError`/编码/递归错误归一为 `invalid_descriptor`，不得在未校验的原始对象上算 digest。

#### `ToolBinding`

```python
@dataclass(frozen=True)
class ToolBinding:
    entry: ApprovedAdapter | ApprovedPlugin
    tool: ApprovedTool
```

#### `ApprovedPlugin`

字段顺序：`adapter_id, language, identity, version, manifest_digest, artifact_digest, adapter_digest, argv, cwd, environment_allowlist, tools, workspace_root` 为必填；`timeout_ms=5000, timeout_cap_ms=25000, stdout_limit=65536, stderr_limit=16384, protocol=2` 有默认值。

`__post_init__` 固定顺序：

1. 进程/制品字段：与 `ApprovedAdapter.__post_init__` 同构、prose 消息逐字照抄，去掉 `tool_key`/`description`/`parameters`/`descriptor_digest` 四项。
2. `type(protocol) is int and protocol == 2`，否则 `protocol_invalid`。
3. `tools` 是 tuple、长度 1..16、每项是 `ApprovedTool`，否则 `tools_invalid`；key 重复 → `duplicate_tool_key`。
4. 每个 `tool.descriptor["v"] == 2`，否则 `invalid_descriptor`。
5. `workspace_root` 为 str、绝对、`os.path.realpath(root) == root`、`os.path.isdir`，否则 `workspace_root_invalid`。
6. `timeout_cap_ms` 为非 bool int 且 `1..25000`，否则 `timeout_cap_invalid`；任一 `tool.timeout_ms > timeout_cap_ms` → `timeout_exceeds_cap`（不静默取 min）。

`tool_for(key) -> ApprovedTool | None`：≤16 项线性扫描；`key` 非 str 返回 `None`。

#### `adapter_declaration_digest()` 与 `from_manifest()`

```python
def adapter_declaration_digest(language: str) -> str:
    # sha256(compact_json({"adapter":"v24.line-json","language":language,
    #                      "protocol":"v24.line-json.v2","version":2}))
```

`from_manifest` 固定顺序：

1. 解析：`dict` → `raw = compact_json(manifest)`；`bytes` → `raw = 原始字节`（再 `strict_loads`）；`str` → 先 UTF-8 编码为 `raw`，再 `strict_loads`。任何 `CanonicalError`/`ValueError`/`UnicodeError`/`RecursionError` → `manifest_invalid`。解析结果非 dict → `manifest_invalid`。
2. 顶层键集恰为 `{identity, version, requires, provides, adapter_digest}`，否则 `manifest_invalid`；`identity`/`version` 非空 str；`requires` 为 list；`provides` 为 **1..16** 个元素的 list（越界 → `manifest_invalid`；直接构造 `ApprovedPlugin` 越界才是 `tools_invalid`）。
3. 每个 provide 是 dict，键集恰为 `{realm, key, descriptor}`；`realm`/`key` 非空 str，`descriptor` dict；否则 `manifest_invalid`。key 与 descriptor 的一致性由 step 6 的 `validate_descriptor` 校验，不一致归 `descriptor_key_mismatch`；descriptor 自身 key 规则违规归 descriptor 校验 reason。
4. 版本一致：`{(type(v), v) for v in ...}` 长度 > 1 → `mixed_descriptor_versions`；全部非 2 → `manifest_invalid`（用元组避免 `{1, True}` 坍缩）。
5. `manifest["adapter_digest"]` 必须是裸 64 位小写 hex（v2 不接受 v1 的 `\x` 前缀），否则 `manifest_invalid`；`!= adapter_declaration_digest(language)` → `adapter_digest_mismatch`。
6. `tools = tuple(ApprovedTool.from_descriptor(p["descriptor"], key=p["key"]) for p in provides)`，保留 provides 原顺序；`descriptor_key_mismatch`/`renderer_*`/`invalid_descriptor` 从这一步透出。
7. `manifest_digest = sha256(raw).hexdigest()`（`raw` 为输入原始字节；dict 输入取 `compact_json` 结果）。
8. `identity`/`version` 取自 manifest，调用 `cls(...)` 进入 `__post_init__`。

`from_manifest` 不读取 artifact 内容、不实算 artifact digest；调用 `cls(...)` 时仍校验 cwd/workspace 的路径元数据。`artifact_digest` 只做 `_hex64` 形状校验。

#### Registry union、`lookup_install`、`match_tool`、`match_pin`

- `__init__`：`isinstance(entry, (ApprovedAdapter, ApprovedPlugin))`，否则 `RegistryError("registry entries must be ApprovedAdapter or ApprovedPlugin")`；重复 key/adapter_id 逻辑与消息不变。
- `lookup_install`：行为不变，返回 union。
- `match_tool(install, pin, key)` 固定六步：`lookup_install` → `pin` 非 dict、`not isinstance(key, str)`、或 `pin.get("key") != key` → `pin_key_mismatch` → 取 tool（v1 要求 `entry.tool_key == key`；v2 用 `tool_for`），未命中 → `tool_not_approved` → `pin["descriptor"]` 非 dict → `descriptor_missing` → `pin["descriptor_digest"]` 非 str → `descriptor_digest_missing` → `pg_jsonb_text` 不等 → `descriptor_mismatch` → `tool.descriptor_digest != pin["descriptor_digest"].lower()` → `descriptor_digest_mismatch`。**不调用 `require_artifact()`**。
- `match_pin`：`lookup_install` 后若 `isinstance(entry, ApprovedPlugin)` → `AdapterNotFound("protocol_mismatch")`；其余 v1 代码一字不改。

#### reason 归属

| 类别 | 异常 | 可见面 |
|---|---|---|
| v2 构造的 W3 新增判定点（`ApprovedTool`/`ApprovedPlugin`/`from_manifest`） | `RegistryError(token)` | `str(exc)`，14 token 闭集；既有字段校验仍用 prose |
| v1 构造/registry 类型 | `RegistryError(prose)` | prose 不变 |
| install/pin/tool 匹配 | `AdapterNotFound` | `.reason`，9 项 + artifact 5 项 |

### `v24/host/line_json.py`

v1 的 `Invocation`、`LineJsonPreflight`、`_canonical`、`build_frame`、`_spec`、`_frames`、`_success_frame`、`_error_frame` 与 `run` 的 v1 路径**一字不改**。新增：

```python
V2_OPERATIONS = ("prepare", "invoke", "release", "inspect")
RESERVED_TOOL_KEY = "agent.spawn"
TOOL_KEY_RE = re.compile(r"[a-z][a-z0-9_.-]{0,127}")   # 必须等于 descriptor.KEY_RE.pattern（gate 断言）

def _protocol(entry) -> int
def build_frame_v2(operation, reservation, args, tool=None) -> bytes
def _classify_v2(raw, *, operation, exit_code) -> tuple[str, dict | None]
def _spec_v2(entry, operation, tool) -> ProcessSpec
def run(adapter, operation, reservation, args, tool=None) -> Invocation
```

`build_frame_v2` 校验顺序（失败一律 `LineJsonPreflight("bad_request")`）：operation ∈ 四操作 → reservation 非空 str 且无 NUL → args 为 dict → invoke 要求 `tool` 为匹配 `TOOL_KEY_RE` 且 ≠ `agent.spawn` 的 str，非 invoke 要求 `tool is None` → 组帧（invoke 五键，其余四键；**不注入 `target`**）→ `compact_json` → 追加一个 LF → 总字节 > 1 MiB 拒绝。`CanonicalError`/`UnicodeError`/`RecursionError` 全部归一，不泄漏。

`_classify_v2` 固定顺序：

1. `raw == b""` → `("eof", None)`
2. UTF-8 strict decode 失败 → `("stdout_not_utf8", None)`
3. `raw.count(b"\n") > 1` → `("extra_frame", None)`
4. 不以 LF 结尾、或 LF 数不是 1、或文本以 BOM 开头 → `("bad_frame", None)`
5. 去末尾 LF，只 `.strip(" \t\r")`
6. `strict_loads` 失败 / 非 dict → `("bad_frame", None)`
7. `obj.get("v") != 2` → `("version_mismatch", None)`
8. `type(obj.get("ok")) is not bool` → `("bad_frame", None)`
9. `ok is True`：exit 必须 0、键集恰 `{ok,v,result}`、result 为 dict，再按 D13 的 operation 形状；通过后返回 `("success", result)`。`J` 域越界已在 step 6 由 `strict_loads` 归为 `bad_frame`（D14/C.8），不再增加域探测或 `invalid_tool_output` failure 分支。
10. `ok is False`：exit 必须 3、键集恰 `{ok,v,error}`、`assert_unknown_output({"error": error})` 通过（`ToolResultError` → `bad_frame`），否则 `("known_error", {"code","message"})`。

`run()` 分工：保留既有首参数名 `adapter`（兼容 `run(adapter=...)`），按 `_protocol(adapter)` 分流。`_protocol(entry)` 为 1 → 原 v1 路径（忽略 `tool`）；为 2 → v2 路径（`build_frame_v2` + `_spec_v2` + `run_process` + 上述分类）；其它 → `LineJsonPreflight("protocol_mismatch")`。分类优先级仍是 timeout → stdout_limit → stderr_limit → exit∉{0,3} → 帧解析 → 帧形状。

失败位置保持 v1 的既有分工：`build_frame_v2` 抛出的 `LineJsonPreflight`（`bad_request`/`protocol_mismatch`/`tool_not_approved`）**原样上抛**，零 `run_process` 调用、不生成 `Invocation`；`_spec_v2` 的 `AttributeError`/`ProcessError` → `LineJsonPreflight("process_spec_invalid")`；`run_process` 的 `ProcessError` → `LineJsonPreflight("spawn_failed")`（与 `line_json.py:160-171` 的 v1 位置一致）。只有进程已创建后的传输缺陷才变成 `Invocation("unknown", …)`。

`_spec_v2`：prepare/release/inspect 用 `entry.timeout_ms`；invoke 按 `tool` 在 `entry.tools` 中取 `ApprovedTool.timeout_ms`（这是 §3.4 的 per-tool timeout 在 transport 层的落地）；tool 语法合法但不在 `entry.tools` → `LineJsonPreflight("tool_not_approved")`，零 spawn。`argv`/`cwd`/`env`/limits 全部来自 entry。

`Invocation` 复用：v2 success 的 `result` 是**整个 result 对象**；failure 的 `result` 是 `{code,message}`。

---

## 测试设计与向量覆盖

### 零 spawn / 零子进程的证明方式

- `test_registry.py`：把 `ApprovedAdapter.require_artifact` 与 `ApprovedPlugin.require_artifact` patch 成「记录并抛错」的 sentinel；任何匹配/构造失败路径若触发 sentinel 即失败。另 patch `v24.host.line_json.run_process` 为记录型 stub，断言调用数 0。
- `test_line_json.py`：只 patch `v24.host.line_json.run_process`，stub 记录 `ProcessSpec` 并返回预置 `ProcessResult`；断言 stdin 字节等于冻结 bytes、argv/cwd/env 来自 entry、`subprocess.Popen` 未调用。timeout/limit/abnormal-exit 由 stub result 驱动。
- 两个 gate 都做静态扫描：不得 import 九个网络模块（`v24/s11/test_g10.py:64-65` 的 `FORBIDDEN_IMPORTS`）、不得出现 `time.sleep`、`line_json.py` 不得含 `shell=True`；不得调用 socket/DB/Node。

### `test_registry.py`（17 case）

| # | 覆盖 | 断言 |
|---:|---|---|
| 1 | Python adapter declaration | 89 B；`90c4dca5b11d830300e898129e2a6210cf694f5c1f31dd67985a444448a0f7cf` |
| 2 | Node adapter declaration | 87 B；`06451360abe502b96b23115973a5797af50954909a9555a8d4e0a0a9fd9a60ec` |
| 3 | 一 install 两 provides | 4745 B；`0ad584415af8743045dd12275a54fa2f43a65395fc8669753416688c9c3e3db5`；`list`/`search` 各匹配到不同 `ApprovedTool` |
| 4 | 五字段 key | 复现字段闭集；断言该 case 仍 `m3_pending` |
| 5 | v1 descriptor 与 `match_pin` | B0/`plugin_fixtures` 字节与 v1 reason 不变；17 字段名字序列不变 |
| 6 | tools 数量 | 1 与 16 接受；直接构造 0/17 → `tools_invalid`；`from_manifest` 的 provides 数量越界 → `manifest_invalid` |
| 7 | key 唯一 | 重复 key → `duplicate_tool_key` |
| 8 | 混合 descriptor 版本 | `mixed_descriptor_versions` |
| 9 | provide key ≠ descriptor key | `descriptor_key_mismatch` |
| 10 | timeout 超 cap | `timeout_exceeds_cap`；cap 越界（0/25001/bool）→ `timeout_cap_invalid` |
| 11 | workspace root | 相对/不存在/symlink → `workspace_root_invalid`（平台无法建 symlink 时 exit 2） |
| 12 | renderer 身份 | 未知 id → `renderer_not_approved`；digest 篡改 → `renderer_digest_mismatch` |
| 13 | `match_tool` 六类失败 | `tool_not_approved`/`pin_key_mismatch`/`descriptor_missing`/`descriptor_digest_missing`/`descriptor_mismatch`/`descriptor_digest_mismatch`，零 spawn |
| 14 | `match_pin(v2)` | `AdapterNotFound.reason == "protocol_mismatch"` |
| 15 | union registry | 重复 key/adapter_id 拒绝；`entries` 为 tuple；`by_id` 返回 union |
| 16 | install digest 失配 | 三个 digest 分别篡改 → `adapter_not_approved`，零 spawn |
| 17 | mixin 与 closure | artifact 五 reason 一致；allowlist 一致；v1 合成项 closure 为 `None`；v2 closure 对合法 args/value 通过、对非法实例抛 `InstanceError`；`replace(cwd=…)` 后 closure 仍与 descriptor 一致；只改 descriptor 不同步派生字段 → `approved_tool_invalid` |

### `test_line_json.py`

| 分区 | 行数 | 断言 |
|---|---:|---|
| v2 request byte | 5 | `expected_hex`/`length`/`sha256`/单 LF |
| v2 response byte | 2 | success / known_error 分类与 result 对象 |
| whitespace corpus | 9 | 全 `success`；U+2028 不误分帧 |
| invalid corpus | 46 | 逐行分类与向量一致；`double_lf`/`extra_frame` → `extra_frame` |
| build preflight | 5 | 全 `LineJsonPreflight("bad_request")`，stub 调用 0 |
| process unknown | 4 | timeout/stdout_limit/stderr_limit/abnormal_exit |
| v1 探针 | 3 | v1 成功/失败/unknown 分类不变；v1 请求字节等于 `build_frame` 输出 |
| 协议分流 | 3 | v1 / v2 / `protocol=3` → `protocol_mismatch` |
| `J` 域探针（D14/C.8） | 2 | float value、超安全整数 value → `bad_frame` |

**55 行 corpus（46 + 9）必须逐行复现，不做抽样。** 其中 11 条错误 shape/leak 行同时验证 D3 的复用；5 条 shape 行验证 D13；4 条安全 error 行验证「复用不误杀」。

---

## Gate、证据与 scope audit

命令（credential-clearing 前缀与 W2 一致）：

```bash
ENVPFX="env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1"
$ENVPFX uv run python v24/s13/test_registry.py
$ENVPFX uv run python v24/s13/test_line_json.py
```

期望末行（实现后必须真实出现，计划不得预称通过）：

```text
[passed] W3 registry contract; cases=17; manifest_bytes=3; zero_spawn_paths=6; construction_reasons=14
[passed] W3 line-json v2 contract; cases=10; frame_bytes=7; parse_rows=55; preflight_rejections=5; unknown_outcomes=4; v1_bytes_unchanged=true
```

串行集合 **26** 条：W3 两条 → W2 四条（`test_descriptor`/`test_schema`/`test_renderers`/`test_results`）→ W1/B0 五条（`test_contracts`、`test_vectors`、`test_vectors --node`、`test_golden`、`test_golden --node`）→ 11 条冻结 closeout（`load.py`、`s1/setup_db.py --self-check`、`s1/test_ddl`、`s1/test_g1`、`s2/test_g3a`、`s3/test_g2`、`s4/test_g2b`、`s5/test_g4`、`s6/test_g5`、`s8/test_g7`、`s7/test_g6`）→ G9/G10/s11 Node/multilingual 四条。每条记录起始时间、完整命令、exit、实际末行、日志 SHA-256。

scope audit：

```bash
git diff --exit-code -- v24/sql
git diff --exit-code -- v24/host/plugins.py v24/host/worker.py v24/host/deepseek.py \
    v24/host/journal.py v24/host/db.py v24/host/process_io.py
git diff --exit-code -- v24/host/canonical.py v24/host/descriptor.py v24/host/tool_schema.py \
    v24/host/renderers.py v24/host/tool_results.py
git diff --stat -- v24/s13/vectors   # 只允许 design_conformance.json
```

证据目录在仓库外（`/tmp/w3-<timestamp>/`），含 `provenance.txt`、`results.tsv`、`01.log`–`26.log`、`merged.log`、allowlist 源码 SHA-256 清单、环境版本、credential scan。执行记录新建 `docs/reviews/v24-tool-plugin-abi-w3-execution-2026-10-31.md`，体例沿用 W2。

---

## 工作项与执行索引

| # | Goal | Done when | Key files | Deps | Size |
|---|---|---|---|---|---|
| W3-0 | 建立 candidate 与 provenance | 记录 HEAD/branch/porcelain-v2/排序源码 SHA/环境；primary 无 stash/reset | 证据目录 | — | S |
| W3-0.5 | 规范澄清定稿 | 附录 C.7/C.8 与 D14 取舍、manifest digest 字节语义先于 W3-2/W3-4 定稿 | design 草案 | W3-0 | S |
| W3-1 | `ApprovedTool` + v1 合成项 | 17 字段基线不变；closure 自编译；`replace` 重算；v1 closure 为 `None` | `registry.py` | W3-0 | M |
| W3-2 | `ApprovedPlugin` + `from_manifest` | 4745 B manifest 与 digest 复现；14 token 各一条探针；cap 与 workspace 校验 | `registry.py` | W3-1 | M |
| W3-3 | union registry + `match_tool`/`match_pin` | 9 个匹配 reason + 六类失败零 spawn | `registry.py` | W3-1 | S |
| W3-4 | v2 build/parse + 分流 | 5+2 byte case、55 行 corpus、5 preflight、4 outcome、3 分流 | `line_json.py` | W3-0 | M |
| W3-5 | 设计修订与原子 repin | 附录 C.7 + §4.1/§7 措辞；`DESIGN_SHA256` 与 `design_conformance.json` 同批；所有 span SHA 不变 | design、`test_contracts.py`、`design_conformance.json` | W3-2、W3-4 | S |
| W3-6 | 两份 gate 与证据 | 26 条串行全绿；ledger/matrix/README/执行记录只填真实结果 | 两个 gate、三份 review、README | W3-3、W3-4、W3-5 | M |
| W3-7 | 提交与推送 | 按路径 `git add`、`git status` 复查、`<版本>: <祈使句>`、无 `--no-verify`、非 force push | — | W3-6 | S |

依赖图：`W3-0 → W3-0.5 → {W3-1, W3-4} → {W3-2, W3-3} → W3-5 → W3-6 → W3-7`。W3-1 与 W3-4 可并行（不同文件、不同 gate）；规范澄清必须先于 W3-2/W3-4 定稿。

---

## File-by-file impact

| 文件 | 变更 | 依赖/顺序 |
|---|---|---|
| `v24/host/registry.py` | 加 `_ApprovedEntry`、`ApprovedTool`、`ToolBinding`、`ApprovedPlugin`、`from_manifest`、`adapter_declaration_digest`、`match_tool`；`__init__` 接受 union；`match_pin` 加 v2 分支 | 依赖 `canonical`/`descriptor`/`renderers`/`tool_schema`；先于 W3-6 |
| `v24/host/line_json.py` | 加 `V2_OPERATIONS`/`TOOL_KEY_RE`/`_protocol`/`build_frame_v2`/`_classify_v2`/`_spec_v2`；`run` 加 `tool=None` 与分流 | 依赖 `canonical`、`tool_results`；不得 import `registry` |
| `v24/s13/test_registry.py` | 新增（约 320 行），17 case | W3-3 后 |
| `v24/s13/test_line_json.py` | 新增（约 300 行） | W3-4 后 |
| `v24/s13/README.md` | 加 W3 小节：两条命令、三态、六/九覆盖、closeout 11/11、W3 非 M2 完成 | W3-5 后 |
| `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md` | 追加附录 C.7；增补 §4.1 closure 所有权与 14 token；更新 §7.1/§7.3/§7.4 措辞 | 与两个 pin 同批 |
| `v24/s13/test_contracts.py` | 仅 `DESIGN_SHA256` 一行 | 与 design 同批 |
| `v24/s13/vectors/design_conformance.json` | 仅 `design_input.sha256_at_review` | 与 design 同批 |
| `docs/reviews/v24-deviation-ledger-2026-10-23.md` | 新增 `D-ABI-W3-*`：D1 向量权威、D2 `from_manifest` 归属、D8 closure、D12 词表、D14 `J` 域撤回与 C.8、D15 pending | 实测后填 |
| `docs/reviews/v24-conformance-matrix-2026-10-23.md` | 新增 W3 两行 gate 表与实测数据；closeout 不变 | 实测后填 |
| `docs/reviews/v24-tool-plugin-abi-w3-execution-2026-10-31.md` | 新增执行记录 | 最后生成 |

**明确不变**：`v24/sql/**`、`v24/s10/**`、`v24/s11/**`、`v24/load.py`、`v24/b0/**`、`plugins.py`、`worker.py`、`deepseek.py`、`journal.py`、`db.py`、`process_io.py`、五个 W2 模块、`v24/s13/plugins/**`、`fixtures.py`、除 `design_conformance.json` 外的全部 vector。

---

## 风险、STOP 与回滚

1. **帧字节不一致**（任一 `expected_hex`/length/SHA 不符）：查 compact 键序、转义、LF；**禁止改向量**。
2. **分类不一致**：核对 LF 计数 → `endswith` → BOM → strip → `strict_loads` 的顺序；禁止改向量或放宽 corpus。
3. **向量漂移**：除 `design_conformance.json` 外任何 vectors diff（含空白、键序、status）→ 停止。
4. **v1 变化**：B0 v1 bytes / parser 分类 / descriptor / provider request / tool message 任一改变 → 停止并回退 `line_json` 改动。
5. **意外接线**：出现计划外 import 边、W4 文件 diff、生产代码读 `v24/s13/vectors/*` → 停止。
6. **静态守卫失败**：出现禁用网络 import、`time.sleep`、`shell=True` → 停止（注意 docstring/注释里的字符串也会被文本扫描命中）。
7. **`deepseek._tools` 被放宽**：B0 的 `descriptor_invalid` 必须保持，那是 W4。
8. **span SHA 变化**：附录 C.7 追加后若任一 pinned span 的 content SHA 变化 → 说明改到了正文，回退。
9. **`plugins.py` 的隐式行为变化**：`_resource`/`_inspect` 把 `lookup_install` 结果直接交给 `line_json.run`（`plugins.py:87-125`），因此一旦 registry 里出现 `ApprovedPlugin`，资源操作会自动发 v2 帧，而 `_tool` 会因 `match_pin` 的 `protocol_mismatch` fail closed。W3 不改 `plugins.py`；这是 W4 接线前必须知道的既有耦合，写入 ledger，不得据此在 W3 改 dispatcher。
10. **reason 泄漏**：14 token 只能出现在 `RegistryError`；不得出现在 `AdapterNotFound`、SQL effect code 闭集或 wire message。
11. **附录 C.2 与严格解码的冲突**：若实现者按 C.2 字面添加 `compact_json` 复检，会得到永不触发的分支；W3 的裁决是撤回该映射并写 C.8。若 C.8 未随变更集落地 → 停止。
12. **manifest digest 语义分歧**：`bytes` 用原始字节、`dict` 用 `compact_json`。若改成「一律 canonical」，冻结向量仍能过，但非规范字节输入会得到不同 digest —— 必须按 D2 的语义并补一条非规范 `bytes` 探针。

回滚范围：仅回退本 candidate 产生的两个 host 文件、三份 review、README、design、两个 pin 与两个新 gate；不得改冻结向量，不得 force/reset primary。

---

## 提交与推送

按 `AGENTS.md`：26 条全绿 → 更新 README/matrix/ledger/执行记录 → 按路径 `git add`（**不得** `git add -A`/`git add .`）→ 复查 `git status` 与密钥 → `git commit -m "v24: add W3 registry approval model and line-json v2 transport"` → `git push origin main`。里程碑一次提交，不拆多个；不得 `--no-verify`，不得 force push。

---

## W3 不证明什么

不证明 M2 完成；不证明 `plugins.py` v2 分支、`worker.py` 的 `model_text` 接线、`deepseek._tools` 接受 v2；不证明 `test_tools.py`/`test_lifecycle.py`/`test_node.py` 覆盖的文件系统语义、分页收敛、12 秒预算、真实子进程生命周期、mixed batch 屏障、崩溃重启、二次 spawn、replay/`no_replay`、tool message 字节稳定性；不证明 artifact digest 实算（M3）或 renderer 在活 dispatcher 下按预算运行；不证明 Node 侧任何行为。closeout 仍 **11/11**，s13 是 extension evidence 而非第 12 条 closeout。

---

## Oracle 裁决记录（2026-10-31）

三个 lane 对四项开放决策一致选择 A；以下为落地取用与两处偏离。

| # | 决策 | 裁决 | 说明 |
|---|---|---|---|
| O1 | `ApprovedTool` closure 所有权 | A：`init=False` 自编译 | 三 lane 一致；补充 `compare=False/hash=False/repr=False`、`object.__setattr__`、v1 不编译 |
| O2 | v2 构造 reason | A：14 token 闭集 | lane 3 另提 `manifest_digest_mismatch`；以多数（lane 1/2）为准，digest 不符归 `manifest_invalid`；`invalid_descriptor` 原样透传（lane 3 主张改映射，未采纳） |
| O3 | `from_manifest` renderer 注入 | A：只用模块级 `RENDERERS` | 三 lane 一致；`validate_descriptor` 的低层注入参数保留给契约测试 |
| O4 | `timeout_cap_ms` 上界 | A：`1..25000` | 三 lane 一致；生命周期 `timeout_ms` 继承 `(0,300000]`（lane 1 建议一并收紧到 25000，未采纳，记为假设）。宽界是 process/v1/lifecycle 的通用界，v2 工具超时另被 descriptor `(1,25000]` 与 cap 收窄 |
| O5 | `double_lf` 修正路径 | 附录 C.7（非原地改 §5.1） | lane 2/3 主张原地改并重算 span SHA；以 lane 1 的 pinned-span 论证与同日 W2 hardening 的既有做法为准 |
| O6 | 附录 C.2 的 W3 failure 映射 | 撤回，改 C.8 | 三 lane 原裁决要求 W3 映射；Phase 6 批评指出 `strict_loads` 先于形状检查，该分支不可达。以代码证据撤回，不是偏好 |
| O7 | manifest digest 字节语义 | `bytes` 原字节 / `dict` canonical / `str` UTF-8 | lane 2 主张一律 canonical；design §4.4 写 `sha256(manifest_bytes)`，冻结向量两者不可区分。取字节权威并补非规范探针 |

**未决假设**：v2 生命周期 `timeout_ms` 仍按 v1 的 `(0, 300000]` 校验；若 W4 证明 30 秒 lease 无法容纳，需要一次显式设计修订。

---

## References

- `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md`（§2.3、§2.4、§3.4、§4.1–§4.4、§5.1、附录 C、§7.1–§7.4）
- `docs/plans/v24-tool-plugin-abi-w2-host-contracts-2026-10-30.md`、`docs/reviews/v24-tool-plugin-abi-w2-execution-2026-10-30.md`（含 hardening supplement）
- `docs/reviews/v24-tool-plugin-abi-w1-execution-2026-10-30.md`、`v24/s13/vectors/README.md`
- `v24/host/{registry,line_json,canonical,descriptor,tool_schema,renderers,tool_results}.py`
- `v24/s13/{test_contracts,test_vectors}.py`、`v24/s11/{plugin_fixtures.py,test_g10.py}`、`AGENTS.md`
- `docs/reviews/v24-tool-plugin-abi-w3-plan-critique-2026-10-31.md`（Phase 6 批评，已并入）

---

## Result

W3 registry/transport candidate 在 `main` 基线 `e2a13349b894078a8127942f39d866f9dbb7cfb1` 上完成实测。2026-10-31T03:25:04+08:00 开始，严格按 §Gate 顺序串行执行 26 条命令；26/26 exit 0 且每条末行有命令专属 `[passed]`，无 exit 2、SKIP 或缺标记。证据目录 `/tmp/w3-20261031T032503/` 包含 provenance、排序源码 SHA 清单、credential scan、`01.log`–`26.log`、`results.tsv`、`merged.log` 与 scope/span 审计。完整 26 行时间/命令/exit/实际末行/日志 SHA 见 [W3 execution record](../reviews/v24-tool-plugin-abi-w3-execution-2026-10-31.md)。

两条 W3 实际末行：

```text
[passed] W3 registry contract; cases=17; manifest_bytes=3; zero_spawn_paths=6; construction_reasons=14
[passed] W3 line-json v2 contract; cases=10; frame_bytes=7; parse_rows=55; preflight_rejections=5; unknown_outcomes=4; v1_bytes_unchanged=true
```

- 指定四条 scope audit exit 均为 0：SQL、六个 W4 文件、五个 W2 模块零 diff；vectors stat 只列 `design_conformance.json`（1 insertion / 1 deletion），无未跟踪 vector。
- design SHA `2606aedc7135e7085219d0a9c99d1ccca5c22ee33baee6a82dd6f137ce7cac24` → `269e6bada20c6c18331cc681f385808d638bd6ac9403dd7b484352175f57e4b0`。旧 design 全文为新 design 的逐字节前缀；23 个唯一 pinned span（25 处 suite 引用）的行号、heading、content SHA 全部相同。`test_contracts.py` 只改 `DESIGN_SHA256`；`design_conformance.json` 只改整文档 SHA 元数据。
- **计划偏差**：D4/W3-5/File-by-file 原拟在 §4.1/§7 原地澄清，实际为附录 C.9/C.10；C.7/C.8 同样追加。这样保留所有行锚定 span 身份。D1/D2/D8/D12/D14/D15、风险 #9 与此偏差已写入 ledger `D-ABI-W3-1…9`。无 gate/向量标准被放宽。
- README、matrix、ledger 与执行记录已按本次实测更新；源码/数据在运行后未改，后续只更新收尾文档。凭据扫描无命中；每条测试使用四项凭据清除前缀和 `UV_NO_ENV_FILE=1`，未调用真实 provider。
- closeout 保持 **11/11**，W3 仅为 extension evidence；`frames_v2` 保持 `m2_pending`，五字段 artifact 证据保持 `m3_pending`。不证明本计划 §W3 不证明什么 中的 M2 完成、W4 接线、M3 工具/artifact/预算、M4 replay 或 W3 Node 行为。

- **复审修正与重跑**：第一次 `/tmp/w3-20261031T030237/` 的 26/26 只证明复审前 candidate。复审发现缺少非规范 bytes/str manifest 实参探针、成功 `ApprovedTool` replace 重编译探针，以及 `run(adapter=...)` 首参数改名的兼容回归；已补齐两类探针并恢复 `adapter` 首参数名，用 v1 keyword 调用验证。本文 step 9 的旧 `J` failure、filesystem-free 说法、reason 边界与 key 校验位置同步纠正。随后完整重跑 26/26；本 Result 所列 `/tmp/w3-20261031T032503/` 才是最终源码/gate 证据，设计 SHA 与 marker 数字均未变。未把首轮证据外推到修正后的源码。

W3-7 按 §提交与推送 的精确提交信息、逐路径暂存、正常 hooks 与非 force `git push origin main` 发布；commit/push 的实际结果另由发布证据与 Git 历史记录，避免把本文件的自引用 commit SHA 当作运行时来源。
