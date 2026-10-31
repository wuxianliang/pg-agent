# v24 Tool/Plugin ABI W4：dispatcher / worker / provider 接线 Deep Plan

日期：2026-10-31。状态：plan-only，未实现。基线 `c8c4bd0`（W3 已提交、26 条串行 gate 全绿）。W4 以 design §10 的 M2 接线子阶段为主体，并承担 design §7.1 中 s13 剩余的全部文件行（M3 的工具实现与 M4 的生命周期证据）。

## Goal 与范围

把 W3 交付的 `ApprovedPlugin` / `match_tool()` / line-json v2 transport / `RendererRegistry` / v2 `output` envelope 接进活的生产路径，并补齐 design §5.6 要求的 host 侧成功页字段关系校验；随后交付三个真实文件系统工具与真实子进程生命周期证据。判据不是「代码写了」，而是：

1. `plugins.py._tool` 对 `ApprovedPlugin` 走 `match_tool()` + `line_json.run(tool=...)`，并在 spawn 前完成 args/artifact/workspace/lease 四类拒绝；
2. `worker._execute_tool` 用 v2 handler 给出的 `model_text` 构造 `tool_message.content`，v1 路径逐字节不变；
3. `deepseek._tools` 接受 v2 descriptor 且投影字段不变，B0 的 `descriptor_v2_rejected` 仍绿；
4. `read`/`list`/`search` 由真实 Python/Node 子进程执行并通过 §6 合同与分页收敛；
5. 完整生命周期（install → prepare → activate → start → model → tool → continuation → final → off → dispose → release → scope close）在真实子进程下跑通，且所有非法 args/tamper 用例以**进程计数**证明零 spawn。

### 里程碑切分：W4a / W4b / W4c

design §7.1 把 `plugins.py`/`worker.py`/`deepseek.py` 与 `s13/plugins/fs_read.py`、`fs_tools.js`、`fixtures.py`、`test_tools.py`、`test_lifecycle.py`、`test_node.py` 列在同一张变更表里；design §10 却把前三个 host 文件归 M2、四个工具/夹具文件归 M3、两个生命周期测试归 M4；§7.4 done-when #1 又写「`test_tools.py`、`test_lifecycle.py`、`test_node.py` 仍归 W3/W4」。这是同一份设计里的三处不同口径，W4 必须显式裁决（D1）。

裁决结果：**W4 是一个交付里程碑，含三个可独立验收的子阶段**。子阶段各自跑完整 gate 表、各自提交推送（AGENTS.md「一个里程碑一次提交」按子阶段执行，先例是 `v8` 的 G7a/G7b/G7c）。M2/M3/M4 是 design 的阶段名，不因 W4 的切分而改名；完成声明分别绑定到子阶段：

| 子阶段 | 内容 | 完成声明 | 对应 design 阶段 |
|---|---|---|---|
| W4a | `tool_pages.py`、`plugins.py`、`worker.py`、`deepseek.py`、`registry.environment()` 的 v2 root 注入、`test_pages.py`、`test_wiring.py`、`w4_stub_plugin.py` | **M2 完成** | M2 |
| W4b | `s13/plugins/fs_read.py`、`s13/plugins/fs_tools.js`、`s13/fixtures.py`、`test_tools.py` | **M3 实现完成，timing/cutoff pending**（O8=B） | M3 |
| W4c | `test_lifecycle.py`、`test_node.py`、mixed batch / replay / crash / legacy 证据 | **M4 完成** | M4 |

W4a 不依赖 W4b；W4b 依赖 W4a；W4c 依赖 W4a+W4b。任一子阶段 gate 红就停在该子阶段，不得用后一子阶段的通过去「抵消」前一子阶段的失败。

### 与 M2 完成判定的关系

W3 明确声明自己不是 M2 完成（`v24/s13/README.md:47`）。W4a 完成后可以宣布 M2 完成，依据是 §10 M2 的 done-when 全部由 W4a 的 gate 覆盖：`test_descriptor`、`test_registry`、`test_line_json` 全绿 + G9/G10/Node 回归全绿 + v1 golden 字节不变。这句话**不含**以下含义：

- 不表示真实文件系统工具已验证（W4b）；
- 不表示 12 秒扫描预算、分页收敛、mixed batch、崩溃重启、replay 已验证（W4b/W4c）；
- 不表示 closeout 从 11/11 增加（仍是 11/11，s13 是 extension evidence）。

## Done when

### W4a

1. 新增 `v24/host/tool_pages.py`：`validate_page(render, args, value)` 覆盖 §5.6 全部字段关系，失败抛 `ToolPageError("invalid_tool_output")`；导入期断言其合同集合恰等于 `RENDERERS` 的三个 renderer id。
2. `plugins._tool` 拆为共享前段 + `_tool_v1`（方法体逐字搬迁）+ `_tool_v2`；v1 的 `last_invocation`、异常映射、结果形状与字节不变。
3. `_tool_v2` 按 D4 的十三步执行；spawn 前四类拒绝（args/schema、artifact、workspace、lease）都是普通 `failure` 且零 spawn。`_tool_v2` 自己对 `AdapterNotFound`/`LineJsonPreflight` 构造 v2 envelope；`parameters_check`/`output_check` 的 `InstanceError` 映射到 `invalid_tool_arguments`/`invalid_tool_output`；`limits` 从 `tool.descriptor["tool"]["limits"]` 读取。
4. `worker._call_tool_handler` 归一为 `(class, result, model_text | None)` 并兼容三种返回；`_execute_tool` 用 `model_text`，legacy 为 None 时在 handler try **之外**回落到 `canonical_json(result.get("output", {}))`（`tool_handler is None` 与 `except` 两条分支也显式赋 `model_text=None`）；`_execute_resource` 忽略第三项；`dispatch_finished` payload 键集不变。
5. `deepseek._tools` 接受 `v in (1,2)`；v2 分支在投影前拒绝 key 缺失/key 与 pin 不等/`agent.spawn`；B0 `structure.descriptor_v2_rejected` 仍为 `descriptor_invalid`。
6. `registry._ApprovedEntry.environment()` 仅在 allowlist 显式包含 `V24_WORKSPACE_ROOT` 时注入该变量（值取 `workspace_root`，绝不读宿主同名环境变量）；v2 fixtures 的 manifest 必须显式包含该名，并有一个缺失该名的失败用例（R14）。
7. `test_pages.py`、`test_wiring.py` 全绿；`test_wiring.py` 的零 spawn 用**进程计数**（`run_process` sentinel + 插件侧 `--spawn-log` 文件）证明，不用 journal 事件数。
8. 全部 29 条测试 gate 命令 exit 0 且末行有命令专属 `[passed]`；6 条 scope audit exit 0 且打印 `[scope] passed`（`[passed]` 只用于测试 gate，不套到 `git diff`/`load.py`）；`v24/sql` 零 diff；scope audit 全部显式钉基线 `c8c4bd0`，且 `registry.py`/`design_conformance.json` 用「还原后逐字节相等」而非行数/标识符白名单（C6）。

### W4b

1. `fs_read.py` 实现 `read` 的 prepare/invoke/release/inspect 四操作与 §6.2 全部边界（空文件、尾换行、offset 越界、Unicode、binary、超长行、1 MiB、symlink、`.git`、分页收敛）。
2. `fs_tools.js` 用**一个** install 同时提供 `list` + `search`，按帧的 `tool` 字段分流；`list` 覆盖排序/递归/hidden/`.git`/symlink/special/非 UTF-8/offset/total，`search` 覆盖 literal/case/glob/context/上限/二进制跳过/column 码点/`complete`/`total`。
3. `fixtures.py` 提供工作区树、两份 v2 manifest（Python read 单工具；Node list+search 双工具）、`ApprovedPlugin` 构造与 `PluginHarness` 复用，不复制 s11 的生命周期驱动。
4. `test_tools.py` 全绿；分页的每个候选都按 §5.6 的「枚举全部前缀、不假设单调」实现，不得用二分或首败即停。
5. 12 秒预算只证「确定性文件数预算 + plugin timeout 被 `_spec_v2` 采用」，不做墙钟 12 秒 gate（D10）；`tool.search_budget_file_count` 被**执行**并实测 `search_scope_too_large`，`tool.search_budget_timing_m3_pending` 保持 pending。**O8=B**：W4b 只宣布「M3 实现完成，timing/cutoff pending」，不宣布 M3 完成；不得把本条读成 cutoff 已验证。

### W4c

1. `test_lifecycle.py` 覆盖 G12-A…H + G12-L：真实 Python/Node 子进程、双 install、mixed batch 屏障、非法 args 零 spawn、非法 output/render 失败、timeout → unknown、tamper 零 spawn、`dispatch_finished` 后崩溃重启不二次 spawn、剩余 lease 不足零 spawn、legacy 字节不变。
2. `test_lifecycle.py` 的 replay 段证明 `result.replay_no_rerender` 与 `lifecycle.journal_replay_no_rerender` 的期望：`replay_source=journal`、`rerender=false`、`second_spawn=false`、`journal_event_types_unchanged=true`。
3. `test_node.py` 全绿；Node 缺失时必须 `[SKIP]` exit 2，不得记为通过。
4. closeout 仍 11/11；`result.replay_no_rerender` 等 `m4_pending` case 被**执行**但其 `status` 字段不改（D13）。

## Current-state analysis

### 当前活路径（v1）与本阶段触点

```text
claim → PluginDispatcher._tool (plugins.py:57-84)
      → _pin / _install → registry.match_pin (registry.py:460-463)
      → entry.tool_key != key → require_artifact → line_json.run(entry,"invoke",...)
      → ("success"|"failure"|"unknown", {"status","output","usage"})
claim → _resource (plugins.py:87-118) / _inspect (plugins.py:121-157)
      → lookup_install → line_json.run(entry, "prepare"|"release"|"inspect", ...)
worker._execute_tool (worker.py:1027-1082)
      → _call_tool_handler (worker.py:1302-1308) → (class,result)
      → tool_message = {"role","tool_call_id","content": canonical_json(result.get("output",{}))}  (worker.py:1066-1070)
      → journal dispatch_finished (payload: outcome, tool_result, tool_message, ...)
```

- `_tool` 在 `plugins.py:65` 调 `match_pin`；`match_pin` 对 `ApprovedPlugin` 直接 `AdapterNotFound("protocol_mismatch")`（`registry.py:460-463`），随后 `plugins.py:67` 读 `entry.tool_key`（`ApprovedPlugin` 没有该字段）。`match_tool()`（`registry.py:433-458`）目前在**生产代码中无调用者**。
- `_resource`/`_inspect` 不经 `match_pin`，把 `lookup_install()` 结果直接交给 `line_json.run`；`line_json.run` 按 `getattr(entry,"protocol",1)` 静态分流（`line_json.py:309-311`）。因此 registry 里一旦出现 `ApprovedPlugin`，这两条路径**已经**发 v2 帧——这是 D-ABI-W3-7 记录的既有耦合。它们的 receipt 仍是 `{"v":1,...}`（`plugins.py:109-115, 148-153`），符合 §5.1 对资源 receipt 的要求。
- `line_json.run(adapter, operation, reservation, args, tool=None)`（`line_json.py:301-302`）：`tool=` 只在 v2 路径被消费（`:309→:268`），invoke 缺 `tool` 是 `bad_request`（`:172-174`），非 invoke 带 `tool` 也是 `bad_request`（`:176-177`）。`_spec_v2`（`:260-275`）在 invoke 时用 `ApprovedTool.timeout_ms`，其余操作沿用 `entry.timeout_ms`。
- `worker._execute_tool` 在调用 handler **之前**写 `dispatch_started`（`worker.py:1042-1046`，handler 在 `:1055-1056`）。这条顺序属于 design §8.3 的 kernel revision 范围，W4 不动。
- 今天 v1 的 `require_artifact` 失败同样发生在 `dispatch_started` 之后；因此「pre-spawn 拒绝没有 `dispatch_started`」不是既有合同，W4 也不把 journal 当作零 spawn 的证据。

### W3 已交付、W4 可直接消费的原语

- `registry.ApprovedTool`（`key/descriptor/descriptor_digest/timeout_ms/render/output_schema` + `init=False` 的 `parameters_check`/`output_check` 闭包）、`ToolBinding`、`ApprovedPlugin`（`protocol=2`，`tools` 1..16，`timeout_cap_ms`）、`ApprovedPlugin.from_manifest()`、`adapter_declaration_digest(language)`、`match_tool()`。
- `ApprovedTool.__post_init__`（`registry.py:177-232`）已对 v2 descriptor 调 `validate_descriptor(provide_key=...)` 并 `compile_schema(kind="parameters"|"output_schema")`；因此 dispatcher **不需要**自己编译 schema，直接调 `tool.parameters_check(args)` / `tool.output_check(value)`（`tool_schema.compile_schema:365-378`，闭包签名 `(instance) -> None`，失败抛 `InstanceError`：`tool_schema.py:83` 定义为 `(path, rule)`，`str()` 形如 `$.path: rule`；`SchemaError` 只用于 schema 自身的 `unsupported_schema`/`duplicate_enum`，**不会**在校验 args/value 时出现）。
- `line_json`：`build_frame_v2`、`_classify_v2`、`_spec_v2`、`run(..., tool=)`。
- `tool_results`：`success_output`/`failure_output`/`unknown_output`、`assert_*_output`、`assert_builtin_meta`、`join_content`（`"\n".join(block["text"])`）、`measure`（args/value/content/meta/frame 五域）、`frame_bytes`、`classify_frame`、`ToolDispatchResult(class_,result,model_text)`。`tool_results.py:5-6` 明确「不实现 W4 的 scenario→error 映射与分页策略」。
- `renderers.RendererRegistry.render(ref, args, value) -> (content, meta)`；异常 `renderer_not_approved`/`render_failed`/`invalid_tool_content`；`RENDERERS` 是模块级不可变 registry，`lookup` 按 (id,version,digest) 三方全等。三个 id 为 `v24.fs.read.text`、`v24.fs.list.text`、`v24.fs.search.text`（`renderers.py:249-272`）。
- `deepseek._tools`（`deepseek.py:340-380`）当前 v1-only：`descriptor.get("v") != 1` → `AdapterFailure("descriptor_invalid")`（`:355-357`）；投影恰 `{name, description, parameters}`，`name = _safe_name(pin["key"])`；请求体由 `_canonical`（`sort_keys=True`、compact、`ensure_ascii=False`）在 `:384` 编码。

### 设计稿与 B0 对 W4 的硬约束（逐条可验证）

- design §5.4（`:704-726`）：`tool_handler` 可返回 `{class,result,model_text}`；`_call_tool_handler` 兼容三种形状（2-tuple / `{class,result}` / `{class,result,model_text}`），前两种回落 `model_text = canonical_json(result["output"])`；`_execute_tool` **只用** `model_text` 构造 `tool_message.content`；journal 事件类型/字段/顺序不变；v1 与当前 `worker.py:1066-1071` 逐字节相同；重启后只重放 journal 的 `tool_message`，不重新 render。
- design §5.2（`:592-656`）：v2 `output` 判别式三态 + 八行「情况→class→output→是否 spawn」映射表；`usage` 仍只 `{wall_ms}`；tool 级 code 不进 `v24.error_v1` 24 码闭集。
- design §5.5（`:757-763`）校验顺序：args 大小 → parameters schema → pin/artifact/workspace/lease → spawn → frame → value 大小 → output schema → 内建 meta/字段关系 → render → content/meta 大小 → journal/settle。
- design §5.6（`:765-784`）：四个语义计量域与 64 KiB transport 上限；「成功页的字段关系（host 在 render 前验证，矛盾为 `invalid_tool_output`）」；有限候选枚举算法（不假设单调、不二分、不在首个失败前缀停止）。
- design §6.4（`:880-884`）：provider 只看到 `{name,description,parameters}`；`_tools` 把 `v==1` 放宽为 `v in (1,2)`，v2 校验 `tool.key == pin.key`；投影字段与 v1 完全相同。
- design §7.1（`:890-905`）：`plugins.py` v2 分支 +170 行；`worker.py` +40（`_call_tool_handler` 接受 `model_text`、`_execute_tool` 用它、**lease 逻辑不动**）；`deepseek.py` +15。
- design §7.2（`:929-935`）：v1 install 不迁移；v2 是新 install；v1/v2 互不收对方帧；provider 字节以改动前录制的 `ScriptedTransport.calls[].body` 与 tool message 为 golden，任何差异回退。
- `v24/b0/README.md:13`（contract-frozen/behavior-unverified — W4，逐字）：v2 dispatcher 必须用 claimed effect 的 `lease_until` 与 `HostDB.remaining_lease_ms`，要求 remaining `>= descriptor_timeout_ms + 5000`，不足时返回普通 `lease_insufficient` failure，并用**进程计数**证明零 spawn；W4 还拥有 additive `model_text`、journal-only replay（重启后不 rerender）、v1 对 `canonical_json(output)` 的字节等价、以及与共享 resource handler 的 `(class,result)` 和 receipt 形状兼容。

### 冻结向量中属于 W4 的字节权威

| 向量 | 关键期望 | 状态 | W4 归属 |
|---|---|---|---|
| `results_v2.json:result.model_text_join` | 11 B，`sha256=cdf4e39b…`，`"one\n二\n三"` | `m2_pending` | W4a |
| `results_v2.json:result.meta_excluded_from_model_text` | 同上，meta 不参与 | `m2_pending` | W4a |
| `provider_projection_v2.json:provider.projection.{read,list,search}` | 482/550/796 B，`b3acce24…`/`e0dce404…`/`7668117b…` | `provisional_w2_pending` | W4a |
| `provider_projection_v2.json:provider.safe_name_mapping` | `projection_keys=[name,description,parameters]` | `m2_pending` | W4a |
| `provider_projection_v2.json:provider.key_mismatch` | `pin_key != descriptor_key` 或 `key == agent.spawn` → `descriptor_invalid`；`check_before_projection=true` | `m2_pending` | W4a |
| `provider_projection_v2.json:provider.v1_bytes_unchanged` | 四个 b0 请求体的 length+sha256 | `m2_pending` | W4a |
| `results_v2.json:result.{replay_no_rerender,journal_replay_no_rerender,tool_message_model_text_stable}` | `replay_source=journal`、`rerender=false`、`second_spawn=false`、`journal_event_types_unchanged=true` | `m4_pending` | W4c |
| `manifest_adapter_v2.json:manifest.one_install_two_provides` | 4745 B，`0ad58441…`；`list`=5000 ms / `search`=15000 ms | `provisional_w2_pending` | W4b |

`v24/s13/vectors` 共九个文件（另有 `descriptor_v2`/`schema_v2`/`renderers`/`frames_v2`/`tool_contracts`/`design_conformance`）。W2/W3 先例：gate **执行** pending case 但不改 `status`/`first_production_stage`；无 re-bless 通道。

### W4 必须正面处理的既有耦合

- **D-ABI-W3-7**（`docs/reviews/v24-deviation-ledger-2026-10-23.md:639`）：`_resource`/`_inspect` 已经会发 v2 帧，`_tool` 仍 fail closed。W4 是唯一被授权改 `plugins.py` 的阶段（D11）。
- **tool-side lease precheck 不存在**：`worker._execute_tool` 从不调 `db.remaining_lease_ms`；`HostWorker.lease_ok`（`worker.py:1288-1299`）无生产调用者；`_lease_for` 对非 model effect 固定 `default_lease_ms=30000`（`worker.py:86, 919-922`）。
- **b0 `structure.descriptor_v2_rejected` 固定 `"descriptor_invalid"`**（`b0/test_golden.py:139-149`，做法是 `_tools([{"key":"read","descriptor":{"v":2,"tool":{}}}])`）。放宽 `_tools` 后该 case **必须仍然通过**；不得改 golden、不得改断言（D7）。
- **b0 `structure.tool_lease_ms`** 固定 `worker_default_ms`，锁死 `default_lease_ms` 不得改。
- **12 秒预算**：`search` descriptor `limits.timeout_ms=15000`、`max_args_bytes=16384`、`max_value_bytes=40960`、`max_content_bytes=41984`、`max_meta_bytes=4096`（`manifest_adapter_v2.json`）；design `:871` 规定扫描预算 12s「低于 15s timeout」；§5.6 第 2 步的 12s 截止是**插件内部**预算，host 只执行 `timeout_ms`。B0 把「12-second scan budgets」列为 W5/W6 的未证项（D10）。

### 复核期新发现（本计划与前一稿的差异，均已核对代码）

1. **§5.6 的 host 校验没有任何实现**。`renderers.py` 只做全域投影（`_read`/`_list`/`_search` 对关系矛盾的 value 仍返回 content），`tool_results` 只管 envelope/预算，`descriptor`/`tool_schema` 只管 schema。design §5.5 第 5 步与 §5.6 都要求 host 在 render 前验证，§7.1 却没有对应文件行。W4a 必须新增 `tool_pages.py`（D2）。
2. **`environment()` 没有注入 `V24_WORKSPACE_ROOT`**。`registry.py:85-89` 只做 allowlist 过滤；`ApprovedPlugin` 存了 `workspace_root` 并在 `__post_init__` 校验（realpath 全等 + isdir，`registry.py:295-299`），但不进环境。design §6.1 第 1 条要求注入。W4a 补一个条件注入（D12）。
3. **`w1_reference.page_error(kind, args, v) -> bool`**（`v24/s13/w1_reference.py:280-312`）是 §5.6 字段关系的独立参考实现（`True` = 非法），且 host 从不 import 它。它可以作为 `tool_pages` 的差分 oracle（D2）。
4. **`_call_tool_handler` 今天已经会静默丢弃 `model_text`**：`worker.py:1306-1307` 只检查 `"class" in value and "result" in value`，所以 `{class,result,model_text}` 现在就被接受但第三项丢失。这决定了 D5 的落地顺序（worker 必须先于 plugins 改）。
5. **三个 renderer id 与 `RENDERERS` 的构造**（`renderers.py:249-282`）提供导入期漂移检查的先例；`tool_pages` 用同样写法锁死「合同集合 == renderer 集合」。

### 可复用的 test harness

- `v24/s11/plugin_fixtures.py:274-297` `PluginHarness(fixture, registry, workdir, *, realm=None)`：构造 `HostDB`（admin+service 双连接）、`PluginDispatcher`、`HostJournal`、`HostWorker`，并 `v24.scope_control('create_root',...)`。**必须有 DB**（`v24/s1/setup_db.py` 的 `setup_db()`）。
- `harness.run(script, *, max_rounds=40, timeout_s=30.0)`（`:315-322`）→ `worker.run_until_idle(...)`，返回**聚合后**的 `RoundStats`，不是 per-turn 列表；per-turn 证据靠 `harness._transport.calls`（`{url,body,headers}`）与 DB 读面（`run_row`/`effect_row`/`install_row`/`scope_row`/`count`）。
- `execute_single(harness, spec, args, final_text, *, tool_call_id="call_1")`（`:432-447`）= admit → prepare → activate → start → run([tool_reply, final_reply])，返回 `{install_id, run_id, model_id, stats, transport}`。
- 零 spawn 的既有做法：`test_g10.py:184-200` 的 `_zero_spawn(fn)` 把 `line_json.run_process` 换成记录型 sentinel；是**函数级**拦截，不是进程计数。W4a 起用「sentinel + 插件侧 `--spawn-log` 文件」双证（D4 的测试节 / D15）。
- `start` 的 `requires` 是纯 tool-key 字符串列表，harness 包成 `[{"key": ...}]`（`:354-362`）；pin 由 SQL 解释器从 `input.requires` 经 `v24.resolve` 生成，不由 harness 造。
- B0 已证明：一个 install 产出恰两个同 realm slot、两个 live public pin 共享同一 provider fiber/episode/install（`v24/b0/README.md:11` 的 proved-by-B0 段）。
- **待确认（W4b 开工前一次性探针）**：`PluginSpec`/`build_spec` 是否只接受 `ApprovedAdapter` 形状（`plugin_fixtures.py:64-178`）。若 `build_registry` 只造 v1，则 s13 `fixtures.py` 自建 registry（不复制生命周期驱动），s11 零 diff。

### 文件现状：W4 涉及路径是否已存在

| 路径 | 现状 |
|---|---|
| `v24/host/plugins.py` | 存在，222 行，v1-only |
| `v24/host/worker.py` | 存在，`_execute_tool` 在 1027-1082、`_call_tool_handler` 在 1302-1308 |
| `v24/host/deepseek.py` | 存在，`_tools` 在 340-380 |
| `v24/host/tool_pages.py` | **不存在**（W4a 新增） |
| `v24/s13/plugins/` | **不存在**（无目录；W4b 新增） |
| `v24/s13/fixtures.py` | **不存在**（W4b 新增） |
| `v24/s13/test_tools.py` | **不存在**（W4b 新增） |
| `v24/s13/test_lifecycle.py` | **不存在**（W4c 新增） |
| `v24/s13/test_node.py` | **不存在**（W4c 新增） |
| `v24/s13/test_pages.py` | **不存在**（W4a 新增） |
| `v24/s13/test_wiring.py` | **不存在**（W4a 新增） |
| `v24/s13/w4_stub_plugin.py` | **不存在**（W4a 新增，测试资产） |
| `v24/s11/plugins/` | 存在（echo 插件），W4 只读复用，零 diff |

## 决策记录

### D1：W4 覆盖 s13 剩余全部文件行，内部拆 W4a/W4b/W4c

三处设计口径冲突（§7.1 一张表 / §10 三个阶段 / §7.4 旧 W 标签）。裁决：

- **以任务书与 §7.1 的文件清单为交付范围**：W4 就是「把 ABI 落地成能跑的工具」的最后一段，含三个工具与生命周期测试。
- **以 §10 的阶段归属为完成声明单位**：W4a→M2、W4b→M3、W4c→M4，三次独立 gate + 三次提交。
- §7.4 done-when #1 的「仍归 W3/W4」措辞作废，由附录 C.15 改写为「W4a 覆盖四个 M2 gate 的接线面；`test_tools`/`test_lifecycle`/`test_node` 归 W4b/W4c」。

代价：W4 的 evidence 面比 W2/W3 大，需要三份执行记录或一份三段式记录；收益是每条完成声明都能对上 design 的阶段名。

（Oracle：lane 1/2 主张 B（只做接线）、lane 3 主张 A（W4a/b/c）。任务书原文明确列出 `s13/plugins/*`、`fixtures.py`、`test_tools.py`、`test_lifecycle.py`、`test_node.py`，故取 A 并保留 lane 3 的子阶段结构；lane 1/2 对 M2 边界的措辞全部采纳，见「与 M2 完成判定的关系」与 O7。）

### D2：§5.6 字段关系校验由新模块 `v24/host/tool_pages.py` 承担，排在 render 之前

三条理由：

1. §5.6 明说「host 在 render 前验证、不信任插件」，把校验交给插件就是放弃 fail-closed；
2. 放进 renderer 会把失败归到 `render_failed`/`invalid_tool_content`（§5.3 的 renderer 错误类），而 §5.6 要求的是 `invalid_tool_output`，分类会错；
3. `renderers` 的合同是「对 schema-valid 域全域有定义的投影」（§5.3.1），在投影里加拒绝会破坏那条全域性。

接口：

```python
class ToolPageError(ValueError):
    reason = "invalid_tool_output"

BUILTIN_PAGE_CONTRACTS: Mapping[str, PageContract]   # key = renderer id
def validate_page(render: RendererRef, args: dict, value: Any) -> None
```

- 用 `render.id` 选合同；未知 ref、id 缺失、version/digest 与 `RENDERERS` 不全等 → `ToolPageError`（fail closed，不静默放行）。取 `RendererRef` 而不是裸 key，是因为 dispatcher 手里只有已审批的 `tool.render`，用它可以顺带把「renderer 身份」与「页合同」绑在一起。
- `args` 只读 offset/limit（缺省 1 / 2000·500·200），**不写回**、不注入默认值（§5.5「不允许 default」）。
- 纯函数：无 I/O、无时钟、无随机数；只依赖 `canonical`（安全整数）与 `renderers`（合同↔renderer 身份）。
- 导入期断言：`set(BUILTIN_PAGE_CONTRACTS) == {entry.ref.id for entry in RENDERERS.entries}`，不一致即 `RuntimeError`（照抄 `renderers.py:282-288` 的写法）。
- `tool_pages` 不 import `v24/s13/**`；差分测试反向 import 参考实现，方向只有测试→生产。

### D3：`_tool` 拆 `_tool_v1` / `_tool_v2`，用 `isinstance` 分流，v1 方法体逐字搬迁

```python
def _tool(self, effect):
    request = _object(effect.get("request"), "request_invalid")
    key = request.get("key"); args = request.get("args")
    if not isinstance(key, str) or not isinstance(args, dict):
        raise PluginError("tool_request_invalid")
    pin = self._pin(effect)
    install = self._install(effect.get("scope_id"), pin.get("provider_install_id"))
    entry = self.registry.lookup_install(install)          # 纯读
    if isinstance(entry, ApprovedPlugin):
        return self._tool_v2(effect, entry, install, pin, key, args)
    return self._tool_v1(effect, install, pin, key, args)
```

- `_tool_v1` 从 `entry = self.registry.match_pin(install, pin)` 起，把 `plugins.py:65-84` 逐字搬入；`last_invocation`、`PluginError`、三元返回形状都不变。
- 多一次 `lookup_install` 不给 v1 增加失败面：`match_pin` 第一步就是同一个 `lookup_install`（`registry.py:461`），reason 与顺序相同。
- 选 A 而非「单函数早返回」：diff 审计时要能一眼确认 v1 方法体未变。
- **偏差（记 `D-ABI-W4-1`）**：`lookup_install` 成功之前发生的失败（request/pin/install 读取失败，含 `adapter_not_approved`）在协议不可知时仍是 v1 形状 `{"status":"error","output":{"code":…}}`；`isinstance(entry, ApprovedPlugin)` 之后的所有失败（包括 `match_tool`/`LineJsonPreflight`）必须由 `_tool_v2` 自己转成 v2 envelope，不能落到 `tool_handler` 的 v1 兜底（见 D4 的 envelope guard）。

### D4：`_tool_v2` 的十三步固定顺序

§5.5 要求「先 args 后 pin」，但 schema 与 per-tool timeout 只有在绑定工具后才可得；因此把纯读、零 spawn 的 `match_tool` 提到最前，其余顺序照 §5.5。

| 步 | 动作 | 失败 code | spawn |
|---|---|---|---|
| 1 | `match_tool(install, pin, key)` → `ToolBinding` | `AdapterNotFound.reason`（`pin_key_mismatch`/`tool_not_approved`/`descriptor_*`/`adapter_not_approved`） | 否 |
| 2 | `len(compact_json(args)) <= _limits(tool)["max_args_bytes"]`（`ApprovedTool` **没有** `limits` 属性；`_limits` 单点读 `tool.descriptor["tool"]["limits"]`，该 dict 已在 `__post_init__` 过 `_check_limits`）；`compact_json` 的 `(CanonicalError, RecursionError, UnicodeError)` 也映射为 `invalid_tool_arguments`（float/非安全整数 args 用例） | `invalid_tool_arguments` | 否 |
| 3 | `tool.parameters_check(args)`；捕获 `InstanceError`（不是 `SchemaError`） | `invalid_tool_arguments`（message = `path: rule`） | 否 |
| 4 | `entry.require_artifact()` | `artifact_missing` / `artifact_outside_cwd` / `artifact_unreadable` / `artifact_not_regular` / `artifact_digest_mismatch` | 否 |
| 5 | workspace 复核：`realpath(root)==root and isdir(root)` | `workspace_unavailable` | 否 |
| 6 | lease 预检（D6） | `lease_insufficient` | 否 |
| 7 | `line_json.run(entry,"invoke",reservation,args,tool=key)`；`LineJsonPreflight` 在 `_tool_v2` 内就地转 failure（不能靠外层 `tool_handler`） | preflight reason（`spawn_failed`/`process_spec_invalid`/`tool_not_approved`） | 否 |
| 8 | `class_name == "unknown"` | `result={status:"error", output:unknown_output(invocation.reason, 固定 message), usage:{wall_ms:invocation.wall_ms}}` 过 `ToolDispatchResult`，`model_text=""` | 是 |
| 9 | `class_name == "failure"`（exit 3 合法错误帧） | 插件给出的 `code`/`message` | 是 |
| 10 | `value` 大小 → `tool.output_check(value)`（捕获 `InstanceError`）→ `assert_builtin_meta` → `validate_page(tool.render, args, value)`；`measure`/`compact_json` 的 `(CanonicalError, RecursionError)` 映射为 `invalid_tool_output` 或 `output_too_large`，不得冒泡 | `output_too_large` / `invalid_tool_output` | 是 |
| 11 | `RENDERERS.render(tool.render, args, value)` | `renderer_not_approved`/`render_failed`/`invalid_tool_content` | 是 |
| 12 | content / meta 预算（`measure`） | `output_too_large` | 是 |
| 13 | `success_output(value, content, meta)` + `model_text = join_content(content)` | — | 是 |

- **envelope guard（C3，必修）**：`_tool_v2` 整体包一层 `try/except (AdapterNotFound, LineJsonPreflight) as exc`，在函数内部构造 `{class:"failure", result:{status,output,usage}, model_text}`（由 `_v2_failure` 生成）并返回；`claim`/`body` 是 worker 的 outcome，不在 handler envelope 里。原因：`tool_handler`（`plugins.py:40-45`）对这两类异常统一走 `_tool_error`（`:207-208`），只会产出 v1 形状 `{"status":"error","output":{"code":...}}`，没有 v2 handler 的 `{class,result,model_text}`（`result` 恰为 `{status,output,usage}`）；若不自己 catch，第 1 步 `match_tool` 的 `pin_key_mismatch`/`tool_not_approved`/`descriptor_*` 与第 7 步 preflight 全部会掉进 v1 形状。`PluginError`/`HostContractError` 仍交给外层（它们只可能来自共享前段或 host bug）。
- 第 3/10 步的 `InstanceError` 必须各步就地转成对应 failure；第 2 步是 `CanonicalError`/`RecursionError`/`UnicodeError`，同样就地转 `invalid_tool_arguments`。不得让它们冒泡到 worker（否则 worker 的 `except` 会把它们映射为 unknown `tool_executor_error`）。

约定：

- 每条结果都构造 `ToolDispatchResult` 自检；构造失败说明是 host bug，直接抛，由 worker 现有 except 映射为 unknown `tool_executor_error`。
- `usage.wall_ms`：1–7 步为 0；8–13 步取 `invocation.wall_ms`。
- 只要发生了调用就更新 `self.last_invocation`。
- failure 的模型可见 content 固定为 `"Error [" + code + "]: " + message` 单 block；unknown 的 message 用固定英文短句（不含路径）。
- 第 10 步的 `assert_builtin_meta` 只对三个内建 renderer 合同生效；第三方 renderer 不在 v1 范围。
- 第 12 步的 `frame` 域只计量、不拒绝：§5.2 的语义域只有四个，60001..65536 依 §5.6 属 transport 合法（D9）；`test_results.py:250-252` 已把 60000/60001/65536/65537 分类为 within/over-target/transport-valid/unknown，D9 与冻结向量一致（R11）。

### D5：`model_text` 由 worker 归一，legacy 分支回落

`worker.py:1302` 改为：

```python
def _call_tool_handler(handler, effect):
    value = handler(effect)
    if isinstance(value, tuple) and len(value) == 2:
        class_name, result = value
        return class_name, result, None
    if isinstance(value, dict) and "class" in value and "result" in value:
        class_name, result = value["class"], value["result"]
        if "model_text" in value:
            if not isinstance(value["model_text"], str):
                raise TypeError("model_text must be a string")
            return class_name, result, value["model_text"]
        return class_name, result, None
    raise TypeError("handler must return (class, result), {class, result} or {class, result, model_text}")
```

- `_execute_tool` 在 handler 调用/异常处理**之外**做 `content = model_text if model_text is not None else canonical_json(result.get("output", {}))`，再写 `tool_message.content`；`_execute_resource`（`:1102`）接三元组但丢弃第三项，receipt 形状不变。
- 这样 v1 的 2-tuple 路径不提前计算 `canonical_json`：它的失败面仍落在 worker 现有 try 之外，逐字节与异常路径与今天相同（R12）。v2 handler 必须给出 `str`（unknown 为空串），因此不会走回落。
- **两条非 handler 分支也赋 `model_text=None`（C4）**：`tool_handler is None`（`worker.py:1050-1053`）与 `except Exception`（`:1054-1062`）在构造 `class_name/result/reason` 后设 `model_text=None`；`content` 的回落仍在 try 之外。否则 `:1069` 会 `UnboundLocalError` 或沿用上一轮值。v1 这两条分支以 `b0/golden/tool_messages_v1.json` 为准，W4a 加 `tool_handler=None` 与 raising handler 两个 case。
- `dispatch_finished` payload 不新增键；`model_text` 只出现在 `tool_message.content`。
- 落地顺序：worker 先于 plugins，否则 v2 的文本会被静默丢弃（今天就是这个状态）。

### D6：v2 lease 预检放在 `_tool_v2` 第 6 步，不动 worker 的 lease 逻辑

- 判定值需要 `ApprovedTool.timeout_ms`，只有 `match_tool` 之后才有；worker 不知道具体工具，放 worker 会把协议知识泄漏给它，且违反 design §7.1「worker lease 逻辑不动」。
- 判定：W4-0 先探针 `_execute_tool` 收到的 `effect` 是否含 `lease_until`（`db.host_effect(effect_id)` 的返回行）。含则直接读 `effect["lease_until"]`；不含则用 `db.host_effect(effect_id)` 在同一 claim 下读回；两条路径都拿不到才按不足处理（fail closed）。判定式：`self.db.remaining_lease_ms(lease_until) >= binding.tool.timeout_ms + 5000`；`remaining_lease_ms` 抛错或返回非 int 也按不足处理。不得用 `now+default_lease_ms` 重算。
- 失败是普通 `failure` + `{"code":"lease_insufficient"}`，`usage.wall_ms=0`，零 spawn。
- **不要求「没有 `dispatch_started`」**：worker 在调用 handler 前就写了它（`:1042-1046`），去掉它是 §8.3 的 kernel revision，且 B0 只要求用**进程计数**证明零 spawn。这与今天 v1 `require_artifact` 失败的行为同构。
- 不套用到 v1 tool；`HostWorker.lease_ok` 继续不接线；`default_lease_ms=30000` 不改（`structure.tool_lease_ms` 冻结）。

### D7：`deepseek._tools` 的 v2 分支用最小自洽检查，不调用 `validate_descriptor`

顺序（在现有 released/key/duplicate 检查之后）：

1. `descriptor` 是 dict、`tool = descriptor.get("tool")` 是 dict，否则 `descriptor_invalid`；
2. `v = descriptor.get("v")`；`type(v) is int and v == 2` → v2 分支；**否则原样走 `v != 1` 的既有判断**（不顺手收紧 `True == 1` 的旧语义）；
3. v2 分支：`tk = tool.get("key")`；`not isinstance(tk,str) or tk != pin["key"] or tk == RESERVED_KEY` → `descriptor_invalid`；
4. 之后进入既有公共检查（`parameters` 是 dict 且 `type=="object"`、`description` 是 str、`_safe_name`、name collision），投影仍是 `{name,description,parameters}`。

`RESERVED_KEY` 从 `descriptor.py:31` 单名导入（`"agent.spawn"`），避免第二份字面量；不导入 `validate_descriptor`——审批权威在 dispatcher 的 `match_tool`，provider 侧只做投影前的自洽检查。**注意**："避免重依赖" 不是理由（`descriptor.py:26` 已经 import `RENDERERS` 与 `tool_schema`，`deepseek` 导入它不会新增依赖环），C10 要求删掉这个错误理由，保留「审批权威不在 provider」这一真实理由。

三行冻结向量的落点：`{"v":2,"tool":{}}` → 第 3 步 key 缺失 → `descriptor_invalid`；`agent.spawn` 两侧相同 → 第 3 步保留字 → `descriptor_invalid`；`read`/`list` 不一致 → 第 3 步 → `descriptor_invalid`。

### D8：v2 failure/unknown 的 envelope 与 `wall_ms` 语义

- 三种 envelope 一律经 `tool_results` 构造器与 `assert_*` 校验，不手写字典。
- `usage` 只 `{wall_ms}`；spawn 前失败 0，spawn 后取进程实际 wall。
- unknown 的 `model_text` 必须是空串（`ToolDispatchResult.__post_init__` 强制）；failure 的 content 是单 text block。
- tool 级 `code` 是 host/tool 词汇，不写入 `v24.error_v1` 的 24 码闭集，不改 SQL。

### D9：frame 超 60000 不是 host 失败

§5.6 只给 transport 65536 的 `stdout_limit` unknown；60001..65536「超内建目标但 transport 合法」。`classify_frame` 只用于证据行，不参与拒绝。host 的四个语义预算（args/value/content/meta）各自独立，任何一个超限才是 `output_too_large`。

### D10：12 秒预算是插件内部预算，W4 不做墙钟 gate

- W4a 证明的是「per-tool timeout 被 `_spec_v2` 采用」：捕获 `ProcessSpec`，断言 invoke `list`=5000 ms、`search`=15000 ms、生命周期操作=`entry.timeout_ms`；并用一个 `timeout_ms=300` 的 stub 用例证明真超时 → unknown `timeout` + 进程组 reap。
- W4a 还证明 lease 预检用的是**该工具**的 timeout：同一 install 内 15000 ms 的工具在剩余 19999 ms 时拒绝、5000 ms 的工具通过。**用例必须构造 claim 的 `lease_until` 为 `now+19999ms`**（默认 `_lease_for` 固定 30s，正常派发永远到不了这个边界，C7）；用 spy 包 `db.remaining_lease_ms` 断言传入值就是 claim 读回的 `lease_until`，不是 `now+30000`，并另测「`lease_until` 缺失 → fail closed」。
- W4b 用**确定性文件数预算**（10000 files 上限）执行 `tool.search_budget_file_count`：`expected.file_count_exceed="search_scope_too_large"`、`expected.timing="not_frozen"`，因此只断言文件数超限的那条路径，不断言墙钟；`tool.search_budget_timing_m3_pending` 的 `deterministic_w1_pass=false` 保持不变。
- W4 明确不证明：插件内部 12 秒截止、cutoff 时页填满判定的时序、跨平台墙钟抖动。`tool.search_budget_timing_m3_pending` 保持 pending。

### D11：资源路径不改，只加覆盖

`_resource`/`_inspect` 继续 `lookup_install` + `line_json.run`，receipt 继续 `{"v":1,...}`；它们在 `ApprovedPlugin` 上已经发 v2 帧（D-ABI-W3-7）。W4c 增加「v2 帧 + v1 receipt」的显式用例，把既有耦合从「已知」变成「有 gate」。不新增 receipt 版本、不改 SQL 对 receipt 的形状校验。

### D12：`environment()` 的 v2 root 注入是条件式

```python
def environment(self, source=None):
    source = os.environ if source is None else source
    env = {key: source[key] for key in self.environment_allowlist if key in source}
    root = getattr(self, "workspace_root", None)
    if root is not None and "V24_WORKSPACE_ROOT" in self.environment_allowlist:
        env["V24_WORKSPACE_ROOT"] = root
    return env
```

精确 patch（scope audit 的 expected 输入；`+5/−1`）：

```diff
-    return {key: source[key] for key in self.environment_allowlist if key in source}
+    env = {key: source[key] for key in self.environment_allowlist if key in source}
+    root = getattr(self, "workspace_root", None)
+    if root is not None and "V24_WORKSPACE_ROOT" in self.environment_allowlist:
+        env["V24_WORKSPACE_ROOT"] = root
+    return env
```

- 条件式是为了不打破 W3 gate：`test_line_json.py:171-178` 用 `entry.environment_allowlist` 现算 `expected_env`，其 `env_names = ("PATH","HOME","V24_W3_UNSET_TEST_VARIABLE")` 不含该名，因此 v1/v2 的 ProcessSpec 断言不受影响。
- 宿主同名环境变量**永不**被采纳（值只取注册表里的 `workspace_root`）；allowlist 缺该名时插件拿不到 root，属安装配置错误，测试应当发现。v2 fixtures 必须显式把 `V24_WORKSPACE_ROOT` 放进 `environment_allowlist`；`test_wiring` 加一个缺失该名的失败用例（R14）。
- 这是 `registry.py` 在 W4 的唯一改动（+5/−1）；scope audit 用「D12 精确 patch + 还原后整文件逐字节相等」表达（见 Gate 节）。

### D13：冻结向量只执行、不改状态

`s13/vectors/*.json` 零 diff（`design_conformance.json` 的整文档 SHA 元数据除外）。gate 执行 pending case 并把实测结果写进执行记录，不修改 `status`/`first_production_stage`/期望字节。W4a 之后 `results_v2` 的六个 m2 case、`provider_projection_v2` 的六个 case 仍标 `m2_pending`/`provisional_w2_pending`。

### D14：design 修订一律追加附录 C.11–C.16，原子 repin

正文不原地改，保持所有 pinned span 的行号/heading/content SHA 不变。新增：

- C.11：W 标签 ↔ M 阶段对照表（取代 §7.4 done-when #1 的旧措辞）；
- C.12：`tool_pages.py` 的合同与调用位置（补充 §5.6）；
- C.13：v2 dispatcher 的十三步与 host reason 表（补充 §5.5/§5.2）；
- C.14：pre-spawn 失败的 `dispatch_started` 语义与零 spawn 证明方式（补充 §7.4 #5）；
- C.15：§7.4 done-when 的 W 标签改写；
- C.16：12 秒预算的证明边界（补充 §5.6）。

追加后整文档 SHA 变化 → `test_contracts.py:10` 的 `DESIGN_SHA256` 与 `vectors/design_conformance.json` 的 `sha256_at_review` 同批更新，并重跑 `test_contracts.py`/`test_vectors.py` 证明 span 集合未变。若任一 pinned span 的 SHA 变化 → STOP 回退。

### D15：spawn 证据日志走 approved argv 的 `--spawn-log`，不写 install cwd（C8）

`registry.py:63-74` 要求 artifact 在 cwd 内、真实插件的 cwd 就是 install 目录；若 stub/插件向 `cwd/spawn.log` 追加，W4b/W4c 会污染源码树（`v24/s13/plugins/`）。`environment()`（`registry.py:85-89`）只按 allowlist 从单一 `os.environ` 选值，**没有** per-entry 环境值通道，因此 `V24_SPAWN_LOG` 方案不可实现。W4-0 定死：

- 每个 install 的 approved argv 末尾追加 `--spawn-log <绝对路径>`（`ApprovedPlugin` 只要求 argv[0]/argv[1] 绝对，额外参数合法）；路径指向 `/tmp/w4*-.../spawn/<install_id>.log`；
- 插件只在该 flag 存在时追加 `<pid> <operation>`；未提供则不写任何文件（生产路径零副作用）；
- argv 不参与 descriptor/digest/canonical key，但属于审批面；测试 manifest 必须显式包含该 flag，生产 manifest 不得包含；
- 与 `V24_WORKSPACE_ROOT` 分开：后者仍按 D12 走 allowlist；spawn 日志不再进 environment_allowlist。

`spawn_count(harness, install_id)` 从该 install 的 argv 取路径（G12-A 的 Python/Node 两个 install identity 不同，不会撞 `canonical_key`）；W4a 的 `w4_stub_plugin.py` 同样遵守。

### D16：macOS-first 非 UTF-8 文件名 fixture 采用 test-only preload

APFS 拒绝原始非 UTF-8 文件名（`EILSEQ`）；HFS+/HFS/MS-DOS 镜像把非法字节转义成 `%FF`。macOS 是首要运行平台，不能在 `workspace() -> None` 后直接 SKIP。W4b 采用探测驱动的双模式：

- `fixtures.workspace` 总是返回 `Workspace` 描述（`root`、`non_utf8_mode`、可选 `preload`/`ledger`），不再返回 `None`。先创建并回读 `b"\xff"`；精确读回为 `filesystem`，`EILSEQ`/`ENOTSUP`/转义为 `preload_shim`，其他 `OSError` 为 fixture 故障。
- macOS 的 `preload_shim` 通过插件子进程的 `NODE_OPTIONS=--require <absolute>` 加载 `v24/s13/w4b_non_utf8_preload.cjs`，只给 realpath 精确匹配的 root 的 buffer `fs.readdirSync` 追加一个 `Buffer.from([0xff])`；不创建 fake 文件，不包装 `lstat/readFile`，不改变其他 entry/排序/分页。
- Linux 必须创建真实 `b"\xff"` 名称并使用 `filesystem`；真实创建失败不得自动回退 shim。`W4B_FORCE_NON_UTF8_MODE=preload_shim` 仅用于 Linux 交叉验证，不能把模式强制为 `filesystem`。
- 生产插件不新增任何测试 seam；scope audit 断言 `v24/s13/plugins/` 不出现 `W4B_*`/`NODE_OPTIONS`/preload 引用。
- 冻结向量 `expected`/`status` 完全不变：list 的 `skipped_non_utf8=1`、search `skip_counters.non_utf8=2` 仍由真实插件逻辑产生（一个 shim 名称 + 一个真实坏内容文件）。
- 只有 Node 缺失、preload 不可用或 runner 明确不支持 `NODE_OPTIONS` 才允许 `[SKIP] exit 2`；preload 已加载后的注入/目录/返回类型错误和插件断言失败均为 FAIL。SKIP 不计为 W4b PASS。
- macOS 执行记录写 `non_utf8_source=preload_shim`，并记录 `linux_real=not_run`（若未在 Linux 运行）；Linux 记录 `non_utf8_source=filesystem`，并做 shim 交叉验证。shim 证据只覆盖插件对非法目录项的处理，**不证明 APFS 文件系统能力**。

---

## 组件设计

### `v24/host/tool_pages.py`（新，约 200 行）

只依赖 `canonical`（`SAFE_INTEGER_MAX`）与 `renderers`（`RENDERERS`、`RendererRef`）。公开面：

```python
class ToolPageError(ValueError):
    reason = "invalid_tool_output"

@dataclass(frozen=True)
class PageContract:
    renderer_id: str
    kind: str            # "read" | "list" | "search"
    default_limit: int   # 2000 | 500 | 200

BUILTIN_PAGE_CONTRACTS: Mapping[str, PageContract]
def validate_page(render: RendererRef, args: dict, value: Any) -> None
```

`validate_page` 按 `render.id` 取合同并逐条实现 §5.6「成功页的字段关系」，全部拒绝都抛 `ToolPageError`：

- 通用：value 必须是 object；`value` 内任何整数必须是安全整数；`next_offset` 非 null 时必须 `> offset` 且为安全整数。
- read：空文件唯一形状（`total_lines=0,start_line=0,end_line=0,text="",final_newline=false,truncated=false,truncated_by=null,next_offset=null`，`path` 除外）；非空时 `start_line == offset`、`1 ≤ start ≤ end ≤ total`、`k = end−start+1 ≤ limit`、`text.split("\n")` 恰 k 段、每段 ≤ 16384 UTF-8 bytes、`truncated_by` 按 `(truncated, k==limit)` 三态、`next_offset` 与 `truncated` 全等。
- list：`offset` 等于请求值（缺省 1）、`k ≤ limit`、非空时 `offset+k−1 ≤ total`、`truncated == (offset+k−1 < total)`、`next_offset` 全等；`kind=file` ⇔ `type(size) is int`，其余 `size is None`。
- search：同 list 的 offset/k/total 关系，且 `truncated == (offset+k−1 < total or not complete)`；`complete=false` 时 `k` 必须 > 0；`skipped` 六个计数都是非负安全整数。
- 空集合只允许 `offset==1 and total==0`（search 还要求 `complete`），否则 `offset_out_of_range` 语义由插件给出，host 侧一律判 `invalid_tool_output`（插件已返回矛盾值时）。

导入期断言（照 `renderers.py:282-288`）：

```python
if set(BUILTIN_PAGE_CONTRACTS) != {entry.ref.id for entry in RENDERERS.entries}:
    raise RuntimeError("page contract drift")
```

### `v24/host/plugins.py`（改，约 +200 行）

结构：

```text
tool_handler                 # 不变（异常兜底仍是 v1 形状）
  _tool                      # 共享前段 + isinstance 分流（D3）
    _tool_v1                 # 逐字搬迁 plugins.py:65-84
    _tool_v2                 # D4 十三步
  _resource / _inspect       # 一字不改
```

`_tool_v2` 的辅助：

- `_v2_failure(code, message, wall_ms) -> dict`：`failure_output` + `ToolDispatchResult(class_="failure", ...)` 自检，返回 `{class,result,model_text}`。
- `_v2_unknown(invocation) -> dict`：`unknown_output(invocation.reason or "unknown", _UNKNOWN_MESSAGE)`，`model_text=""`。
- `_HOST_MESSAGE`：固定英文短句表，不含任何路径（附录 C.13 冻结）：

| code | message |
|---|---|
| `invalid_tool_arguments` | `arguments do not match the approved tool schema` |
| `lease_insufficient` | `remaining effect lease is shorter than the approved tool timeout` |
| `workspace_unavailable` | `the approved workspace root is not available` |
| `invalid_tool_output` | `tool output does not satisfy the approved contract` |
| `output_too_large` | `tool output exceeds the approved size budget` |
| `render_failed` | `the host renderer rejected the tool value` |
| `invalid_tool_content` | `the renderer produced an invalid content block` |
| `renderer_not_approved` | `the approved renderer is not available` |
| （未列出的 `AdapterNotFound`/`LineJsonPreflight`/artifact reason） | `tool dispatch failed before execution` |
| （unknown 固定文本） | `tool process did not produce a decidable outcome` |

失败 message 若来自 `InstanceError`，形如 `"$.path: rule"`（`exc.path`/`exc.rule`）。`exc.path` 可能嵌入模型提供的属性名，**不得**假定它无路径/无实参：若 `len(exc.path) > 256`，或 `failure_output` 因泄漏检查/1024 B 上限拒绝，退化为 `"$: " + exc.rule` 再构造一次；再失败即视为 host bug 上抛。补一个键名为 `/etc/passwd` 的用例，断言 message 不含该串。

`_tool_v2` 不读 `entry.tool_key`、不调 `match_pin`；`entry.require_artifact()` 只在第 4 步调用一次。

### `v24/host/worker.py`（改，约 +20 行）

只动三处（D5）：

1. `_call_tool_handler` 返回 `(class, result, model_text | None)` 并兼容三种 handler 形状；legacy 两形态返回 `None`；
2. `_execute_tool` 的 `class_name, result, model_text = ...`，在 try 外回落 `content = model_text if model_text is not None else canonical_json(result.get("output", {}))`，再写 `tool_message["content"]`；
3. `_execute_resource` 接三元组、丢弃第三项。

不动：`_execute_model`、`_lease_for`、`default_lease_ms`、`lease_ok`、journal 事件、`_settle`、`_no_http_*`。

### `v24/host/deepseek.py`（改，约 +14 行）

在 `_tools` 的 pin 循环里插入 v2 分支（D7）。`_safe_name`、`by_provider`/`by_key`/`descriptors` 的构造与投影一字不改；`send()` 的 `_canonical` 编码路径不动。

### `v24/host/registry.py`（改，约 +5/−1 行）

只改 `_ApprovedEntry.environment()` 的条件注入（D12）。`ApprovedAdapter.environment()` 的实际输出不变（其 allowlist 不含该名时完全等价）。

### `v24/s13/w4_stub_plugin.py`（新，测试资产，约 180 行）

一个 v2 单文件插件，供 W4a 的 `test_wiring.py` 使用，不属 M3：

- argv 固定 `[sys.executable, <this file>, "serve"]`，测试 manifest 再追加 `--spawn-log <abs path>`（D15）；从 stdin 读一行 frame，按 `operation` 处理 prepare/release/inspect/invoke（`line_json.py:164-180` 的帧键是 `operation`，不是 `op`），写一行 frame + LF，exit 0/3。
- 行为由 `args["scenario"]` 驱动（`scenario` 在 descriptor 的 parameters 里显式声明，`additionalProperties:false`，所以不会污染生产合同）：`ok`、`known_error`、`bad_frame`、`extra_frame`、`no_lf`、`timeout`、`nonempty_meta`、`bad_value`、`bad_relation`、`huge_value`、`crash`。
- descriptor 的 `render` 必须绑定一个内建 renderer（如 `read` v1），否则第 11 步只会得到 `renderer_not_approved`，第 10/12/13 步不可测。
- 每次进程启动向 `--spawn-log` 指定的文件追加一行 `<pid> <operation>\n`（进程计数证据；未提供 flag 则不写，见 D15）。
- 不实现文件系统语义；不为它写 §6 合同测试。

### `v24/s13/plugins/fs_read.py`（新，约 320 行）

实现 design §6.2。要点：

- 单文件、仅标准库；`argv=[sys.executable, __file__, "serve", "--spawn-log", <abs path>]`，`cwd`=install 目录，`V24_WORKSPACE_ROOT` 由 host 注入（D12）；未带 `--spawn-log` 时不写日志（D15）。
- 帧循环：读一行 → 严格解析 → `operation` 分派（prepare/release/inspect/invoke）→ 写一行结果 + LF。prepare/release/inspect 返回 §5.3 规定的形状；invoke 返回 `{value}` 或 `{error}`。
- `read` 的 §5.6 候选枚举：先字节扫描得 `total_lines`/`final_newline`，再按 §5.6 第 1–5 步枚举 `k=1..min(limit,m)`，逐候选构造完整 value 并用**内联 byte counter**（`§5.3.1` 的 `27+E(T)` 恒等式）计算 content 长度，不创建 T；选满足四预算的最大 k。
- 错误码闭集见 §6.2；所有 message 只用相对路径。
- 只按 `\n` 切行、`\r` 保留、无合成尾换行；空文件形状唯一。

### `v24/s13/plugins/fs_tools.js`（新，约 520 行）

实现 design §6.3 的 `list` + `search`，一个 install 两个 provides：

- argv 为 `[node, <fs_tools.js>, "serve", "--spawn-log", <abs path>]`；帧里 `tool` 字段决定分派；`prepare/release/inspect` 与 `tool` 无关。
- `list`：完整过滤/排序/计 total 后切页；非递归默认；`recursive` DFS；symlink 只列不跟随；special/非 UTF-8 计数跳过；10000 项上限 → `directory_too_large`。
- `search`：literal-only、ASCII case fold、glob `*`/`**`/`?`；DFS 前序；每次从起点重扫（无状态分页）；`complete`/`total` 快照语义；10000 files / 200 hits / 12s 三个预算里**只有前两个**进入 W4b 的确定性 gate。
- 与 `fs_read.py` 共享的 §6.1 路径/编码/排序规则必须逐条一致（两语言差分用例在 `test_tools.py` 里交叉断言）。
- content 语法严格按 §5.3.1；`search` 的 summary 行与 continuation 行不得多一个 LF。

### `v24/s13/fixtures.py`（新，约 280 行）

- `workspace(...)`：构造确定性测试树（ASCII/Unicode/空文件/尾换行/超长行/超过 1 MiB/`.git`/symlink/hidden/special/非 UTF-8 名），返回 `Workspace(root, non_utf8_mode, preload, ledger)`；root 为 `os.path.realpath`（macOS 的 `/tmp`、`/var/folders` 都是 symlink，`ApprovedPlugin` 要求 `realpath(root)==root`）。非 UTF-8 名优先真实创建并回读验证；APFS 拒绝时使用 D16 的 test-only preload（`preload_shim`），不返回 `None`。
- `read_spec(...)` / `node_spec(...)`：两份 v2 manifest（`identity` 分别为 `v24.fs.python`/`v24.fs.node`），`provides` 的 key 与 descriptor key 对齐，`adapter_digest = adapter_declaration_digest(language)`，`artifact_digest = sha256(plugin file)`；两份 manifest 的 `argv` 末尾都带该 install 的 `--spawn-log <abs path>`（D15）。
- `plugin_registry(specs)`：构造只含 `ApprovedPlugin` 的 `ApprovedAdapterRegistry`（不依赖 s11 的 `build_registry`，避免 v1 假设）。
- `open_harness(...)`：复用 `v24/s11/plugin_fixtures.PluginHarness`（`sys.path` 导入），不复制 admit/prepare/activate/start/off/dispose 驱动。
- `spawn_count(harness, install_id)`：读该 install 的 `--spawn-log` 文件行数；`install_spawn_log(install_id)` 从该 install 的 argv 解析路径；`open_harness` 为每个 install 生成独立的 `/tmp` 路径并写进 manifest argv（D15）。

### `v24/s13/test_pages.py`（新，W4a gate，约 220 行，无 DB）

- 对 `w1_reference.page_error` 做差分（C5，必修）：
  - (a) 21 个 renderer golden 的 `{args,value}`；(b) `tool_contracts.json` 的全部具体成功 value；(c) 对每个**通过 `tool.output_check`** 的合法 value 做逐字段变异（±1、`truncated` 翻转、cursor 置 null/越界、`size` 类型互换、`complete` 翻转）；(d) `results_v2` 的 prefix 场景候选。
  - 等价断言 `validate_page` 拒绝 ⇔ `page_error == True` **只对 `tool.output_check` 通过的值成立**；`output_check` 拒绝的变异不进 `validate_page` 差分，只单边断言 host 在第 10 步被 `output_check` 拒绝（`invalid_tool_output`）。
  - 两个已知参考实现缺口必须从 ⇔ 排除并单边断言：空 read 且 `offset>1`（`page_error` 对空文件直接返回 false，不看 offset；design §6.2:819 要求 `offset_out_of_range`，host 的 `validate_page` 必须拒绝）；`skipped` 为负数（`page_error` 只查安全整数，不查非负；host 必须拒绝）。两类记入执行记录的 `oracle_gap` 行，不得为了对齐而放宽 host。
  - 其余任何 ⇔ 失败都是 gate 红。
- 断言合同集合 == renderer 集合；import 方向检查放在**子进程**里（只 import `v24.host.tool_pages`，断言 `w1_reference` 不在 `sys.modules`），父进程再 import `w1_reference` 做差分，避免同进程自相矛盾（R5）。
- 断言 `ToolPageError.reason == "invalid_tool_output"`，未知 renderer id / 缺 version / digest 不符均拒绝。

### `v24/s13/test_wiring.py`（新，W4a gate，约 560 行，需 DB）

分四段：

1. **provider 投影（无 DB）**：逐字节比 `provider.projection.{read,list,search}` 的 `expected_hex`/length/sha256；`safe_name_mapping` 三行；`key_mismatch` 两行；`v1_bytes_unchanged` 四行（从 `b0/golden/provider_requests_v1.json` 读，只读）；`descriptor_v2_rejected` 仍为 `descriptor_invalid`。
2. **handler 归一（无 DB）**：2-tuple / `{class,result}` / `{class,result,model_text}` 三种；`model_text` 非 str → TypeError → worker 映射 unknown `tool_executor_error`；v1 回落字节 == `canonical_json(output)`。
3. **`_tool_v2` 十三步（有 DB + stub 子进程）**：每个失败分支一个 case，断言 `(class, code)`、`--spawn-log` 行数、`dispatch_finished.payload` 键集与 `tool_message.content`。零 spawn 的 6 条路径（args 超大/schema 失败/artifact 五 reason/workspace 消失/lease 不足/match_tool 三类失败）全部用 sentinel + `--spawn-log` 双证。**新增（C3/C4/C7/R4/R8/R13）**：(a) `match_tool` 的 `pin_key_mismatch`/`tool_not_approved`/`descriptor_*` 与 `LineJsonPreflight` 必须返回 handler 形状 `{class,result,model_text}`（`result` 恰为 `{status,output,usage}` 并通过 `tool_results.assert_*`；`claim/body` 只在 `dispatch_finished.outcome` 里断言），且**不是** v1 的 `{"status":"error",...}`；(b) `parameters_check`/`output_check` 的 `InstanceError` 映射到 `invalid_tool_arguments`/`invalid_tool_output`，不是 unknown；加 float args 与 `CanonicalError` 用例；(c) `tool_handler=None` 与 raising handler 两条 worker 分支产出与 `b0/golden/tool_messages_v1.json` 相同的 content；(d) 19999 ms lease 用例按 D10 构造 claim（`HostWorker(default_lease_ms=19999)`）；(e) `InstanceError.path` 含 `/etc/passwd` 形键名时，message 退化为 `$: rule` 且不含路径。
4. **端到端 v2（有 DB + 真子进程）**：单 install 单工具，`execute_single` 走完 start → model → tool → continuation → final；断言 `model_text` 11 B 向量（`result.model_text_join`）、`meta_excluded_from_model_text`、`tool_message.content` 与 journal 一致；资源路径在 `ApprovedPlugin` 上发 v2 帧但 receipt 仍是 `{"v":1,...}`（D11）。

### `v24/s13/test_tools.py`（新，W4b gate，约 550 行，需 DB + 真子进程）

按 design §7.3 的 `test_tools` 行逐项；每个用例读 `--spawn-log` 文件证明真的起过进程；分页用例断言「枚举全部前缀、不假设单调」的行为（构造一个长前缀失败、短前缀成功、再长前缀又成功的 value，证明实现不是首败即停）。
- `preload_shim` 模式在正式向量前跑 preload preflight，并增加差分守护：同一 root 带/不带 shim 的 list 除 `skipped_non_utf8`（1 vs 0）外完全相等，search `skip_counters` 除 `skipped.non_utf8`（2 vs 1）外完全相等；最小页长逐页比较；control 目录不注入；ledger 无 mismatch。证据行 `[evidence] non_utf8_source=preload_shim|filesystem`，不改变 W4 fs tools marker。

### `v24/s13/test_lifecycle.py`（新，W4c gate，约 480 行）

G12-A…H + G12-L（design §7.3 表）。其中：

- G12-C/G12-F 的零 spawn 用 `--spawn-log` 行数 + sentinel 双证；
- G12-G 用 `harness.worker.crash_after="finished"` 后重建 worker，断言 `second_spawn=false`、不二次 receipt、journal 事件序列前缀不变；
- replay 段把 renderer 的 `RendererRef` 换成不同 digest（只改测试内存对象），重放 journal 后断言 `tool_message.content` 不变（`rerender=false`）；
- G12-L 的 legacy 字节与 B0 golden 逐字节比。

### `v24/s13/test_node.py`（新，W4c gate，约 160 行）

Node 缺失 → 打印 `[SKIP]` exit 2；存在则跑 Node 合同 + 一次完整生命周期。与 `v24/s11/test_node.py` 的 `--node` 语义一致。

---

## 测试设计与向量覆盖

### 零 spawn / 零子进程的证明方式

W4 起统一用**双证**，不再只用 `_zero_spawn(fn)` 的函数级 sentinel：

1. `line_json.run_process` 的计数 sentinel：记录每次调用（成功/失败都记），`before/after` 差为 0；
2. 插件侧 `--spawn-log` 文件：真实进程启动时追加一行，`wc -l` 为 0；未提供该 flag 时断言文件不存在（D15）。

两个数字必须一致。对必须 spawn 的用例（timeout、exit 3、坏帧），断言 sentinel 计数 == `--spawn-log` 行数 == 1（或预期值），避免「没起进程但断言通过」的空转。

### pending case 的执行方式

W4a/W4b/W4c 的 gate **执行**对应 pending case（在 `test_wiring.py`/`test_lifecycle.py` 内以 case id 命名并打印实测值），但不修改 `v24/s13/vectors/*.json` 的 `status`。执行结果写进执行记录，例如：

```text
m2 result.model_text_join            executed actual=11B cdf4e39b… expect=11B cdf4e39b… pass
m2 provider.projection.read          executed actual=482B b3acce24… expect=482B b3acce24… pass
m2 provider.key_mismatch             executed 2/2 rejected-before-projection pass
m4 result.replay_no_rerender         executed replay=journal rerender=false pass
m4 lifecycle.journal_replay_no_rerender executed second_spawn=false pass
```

### 三态与证据

- exit 0 且末行有该命令专属 `[passed]` → passed；
- exit 2 / `[SKIP]` / `not_requested` → unverified，**阻断**该子阶段完成；
- exit 1 / 异常 / 缺 marker / 异常退出 → failed。

每条命令清空四项凭据前缀并设 `UV_NO_ENV_FILE=1`（与 W3 相同）：

```bash
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python <cmd>
```

证据目录 `/tmp/w4a-<UTC 时间戳>/`、`/tmp/w4b-…/`、`/tmp/w4c-…/`，每个含 `provenance.txt`、`source-sha256.txt`、`credential-scan.txt`、`NN.log`、`results.tsv`、`merged.log`、`scope-audit.txt`。

---

## Gate、证据与 scope audit

### W4a 串行命令表（29 条 gate + 6 条 scope audit）

表中每条命令实际执行时统一加凭据清除前缀：`env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1`。

```bash
# --- W4a 新增 ---
uv run python v24/s13/test_pages.py
uv run python v24/s13/test_wiring.py
# --- W2/W3 s13 继承 ---
uv run python v24/s13/test_descriptor.py
uv run python v24/s13/test_schema.py
uv run python v24/s13/test_renderers.py
uv run python v24/s13/test_results.py
uv run python v24/s13/test_registry.py
uv run python v24/s13/test_line_json.py
# --- W1 向量 ---
uv run python v24/s13/test_contracts.py
uv run python v24/s13/test_vectors.py
uv run python v24/s13/test_vectors.py --node
# --- B0 ---
uv run python v24/b0/test_golden.py
uv run python v24/b0/test_golden.py --node
# --- closeout 11 ---
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
# --- extension ---
uv run python v24/s10/test_g9.py
uv run python v24/s11/test_g10.py
uv run python v24/s11/test_node.py --node
uv run python -m v24.host.plugin_smoke --multilingual-smoke
# --- 冻结面 ---
git diff --exit-code -- v24/sql
```

新 gate 的期望末行（逐字）：

```text
[passed] W4 page contract; contracts=3; cases=<N>; oracle_differential=<N>; unknown_ref_rejected=true
[passed] W4 dispatch wiring; cases=<N>; zero_spawn_paths=6; model_text_bytes=11; v1_bytes_unchanged=true; resource_receipt_v1=true
```

### W4b 追加（+1，共 30 条 gate）

```bash
uv run python v24/s13/test_tools.py
```

```text
[evidence] non_utf8_source=preload_shim|filesystem
[passed] W4 fs tools; cases=<N>; read=<N>; list=<N>; search=<N>; pagination_converged=true; page_contracts_imported=3
```

### W4c 追加（+2，共 32 条 gate）

```bash
uv run python v24/s13/test_lifecycle.py
uv run python v24/s13/test_node.py --node
```

```text
[passed] W4 lifecycle; cases=<N>; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true
[passed] W4 node contract; node=<path>
```

### Scope audit（W4a 起每条串行表末尾执行）

```bash
# 所有 diff 显式钉基线 c8c4bd0：裸 git diff 只比 HEAD，发现不了已提交的越界改动（C6）
BASE=c8c4bd0
# 1. 冻结模块零 diff（W2 五模块、W3 transport、B0、s10、s11、load.py）
git diff --exit-code "$BASE" -- v24/b0 v24/s10 v24/s11 v24/load.py \
    v24/host/canonical.py v24/host/descriptor.py v24/host/tool_schema.py \
    v24/host/renderers.py v24/host/tool_results.py v24/host/line_json.py \
    v24/host/journal.py v24/host/db.py v24/host/process_io.py
# 1b. 冻结目录不得有新增未跟踪文件（git diff 看不到）
test -z "$(git ls-files --others --exclude-standard -- v24/b0 v24/s10 v24/s11 v24/sql v24/s13/vectors)"
# 2. 冻结向量零 diff（design_conformance.json 单列，见第 3 条）
git diff --exit-code "$BASE" -- v24/s13/vectors ':!v24/s13/vectors/design_conformance.json'
# 3/4. 由 test_wiring.py 的 _scope_audit("$BASE") 在每次运行末尾自动执行，打印 [scope] 行，失败即 gate 红
# 5. 生产代码不得读向量，也不得反向 import 测试参考实现
if grep -rn "v24/s13/vectors" v24/host; then echo "[scope] failed 5 vector_import"; exit 1; fi
if grep -rn "w1_reference" v24/host; then echo "[scope] failed 5 oracle_import"; exit 1; fi
# 6. SQL 零 diff（Done-when 与提交前置条件都要求）
git diff --exit-code "$BASE" -- v24/sql
```

第 3 条不再用 `--numstat` 的 1 insertion / 1 deletion（单行改动可伪造计数）：`_scope_audit()` 断言 `design_conformance.json` 相对基线的 diff 只有两行（1 `-` / 1 `+`），且两行都只改 `sha256_at_review` 的值；把当前值替换回基线值后，整文件必须与 `git show c8c4bd0:<path>` 逐字节相等。

第 4 条不再用标识符白名单（D12 的实现行含 `env`/`root`/`source`/`getattr`/`allowlist`，旧白名单自相矛盾）：`_scope_audit()` 用 `git show c8c4bd0:v24/host/registry.py` 加 D12 的精确 patch 构造 expected，`cmp` 当前文件；同时 `git diff -U0 "$BASE"` 必须只有一个 hunk，`+` 行逐字等于 D12 的五行。两者都过才算通过。

任何一条审计失败都打印 `[scope] failed <n> <reason>` 并非零退出；全部通过时打印 `[scope] passed base=c8c4bd0 checks=6`。`--numstat`/人工比对不再作为通过依据。

### 证据要点

- 每条命令的时间戳、exit code、实际末行、日志 SHA-256 进 `results.tsv`；
- `source-sha256.txt` 覆盖本子阶段改动与冻结文件；
- W4a 额外记录 `registry.py` 的 diff hunk 与 `git diff c8c4bd0` 的 hunk；`design_conformance.json` 的还原后 SHA；
- W4b/W4c 额外记录 Node 版本、真实子进程 PID 与 `--spawn-log` 行数。

---

## 工作项与执行索引

| 序号 | 子阶段 | 工作项 | 依赖 | 完成信号 |
|---:|---|---|---|---|
| W4-0 | W4a | provenance、design 附录 C.11–C.16 草案定稿（含 host message 表、十三步）、cwd/artifact 布局、`--spawn-log` 约定（D15）与 `_call_tool_handler`/`_execute_resource:1102` 调用点 grep 确认 | — | 文档评审通过 |
| W4-1 | W4a | `tool_pages.py` + `test_pages.py` | W4-0 | `test_pages.py` 绿 |
| W4-2 | W4a | `deepseek._tools` v2 分支 + provider 段测试 | W4-0 | B0 两条 gate 仍绿 |
| W4-3 | W4a | `worker._call_tool_handler` 三元组 | W4-0 | G10 回归绿 |
| W4-4 | W4a | `plugins.py` 分流与 `_tool_v2` | W4-1/3 | `test_wiring.py` 绿 |
| W4-5 | W4a | `registry.environment()` 条件注入 | W4-4 | v2 端到端用例拿到 root |
| W4-6 | W4a | design 附录 + 两处 SHA repin，重跑 contracts/vectors | W4-1…5 | span SHA 不变 |
| W4-7 | W4a | 29 条 gate + 6 条审计 + README/matrix/ledger/执行记录 → 提交推送 | W4-6 | 29/29 |
| W4-8 | W4b | `fixtures.py` + 两个插件 + `test_tools.py` | W4-7 | 30/30 |
| W4-9 | W4b | README/matrix/ledger/执行记录 → 提交推送 | W4-8 | M3 实现完成声明（timing/cutoff pending） |
| W4-10 | W4c | `test_lifecycle.py`（G12-A…H + L + replay） | W4-9 | 32/32 |
| W4-11 | W4c | `test_node.py` + Node 缺失 SKIP 路径 | W4-10 | 32/32 |
| W4-12 | W4c | README/matrix/ledger/执行记录 → 提交推送 | W4-11 | M4 完成声明 |

---

## File-by-file impact

| 文件 | 变更 | 依据 |
|---|---|---|
| `v24/host/tool_pages.py` | 新，约 200 行：`PageContract`、`BUILTIN_PAGE_CONTRACTS`、`validate_page`、导入期合同↔renderer 断言 | D2 |
| `v24/host/plugins.py` | 改，约 +200/−6：`_tool` 分流、`_tool_v1` 搬迁、`_tool_v2` 十三步、host message 表、v2 构造辅助 | D3/D4/D5/D6/D8/D9 |
| `v24/host/worker.py` | 改，约 +18/−6：`_call_tool_handler` 三元组、`_execute_tool` 用 `model_text`、`_execute_resource` 丢弃第三项 | D5 |
| `v24/host/deepseek.py` | 改，约 +14/−2：`_tools` v2 分支与保留字检查 | D7 |
| `v24/host/registry.py` | 改，约 +5/−1：`environment()` 条件注入 `V24_WORKSPACE_ROOT` | D12 |
| `v24/s13/w4_stub_plugin.py` | 新，约 180 行：测试用 v2 插件（11 个 scenario + `--spawn-log`） | D4 测试节 / D15 |
| `v24/s13/test_pages.py` | 新，约 220 行，无 DB；差分含 schema-invalid 单边与两处 oracle gap | D2 / C5 |
| `v24/s13/test_wiring.py` | 新，约 560 行，需 DB；含 envelope/分支/lease 新 case 与 `_scope_audit()` | D3–D12 / C3,C4,C6,C7 |
| `v24/s13/plugins/fs_read.py` | 新，约 320 行，§6.2 | D1 |
| `v24/s13/plugins/fs_tools.js` | 新，约 520 行，§6.3 | D1 |
| `v24/s13/fixtures.py` | 新，约 280 行（含 `--spawn-log` 路径注入与 `spawn_count`） | D1 / D15 |
| `v24/s13/test_tools.py` | 新，约 550 行，需 DB | D1/D10 |
| `v24/s13/test_lifecycle.py` | 新，约 480 行，需 DB | D1/D11 |
| `v24/s13/test_node.py` | 新，约 160 行 | D1 |
| `v24/s13/README.md` | 改：W4a/W4b/W4c 三节、命令表、三态、M2/M3/M4 边界 | D1 |
| `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md` | 改：只追加附录 C.11–C.16 | D14 |
| `v24/s13/test_contracts.py` | 改：`DESIGN_SHA256` 一行 | D14 |
| `v24/s13/vectors/design_conformance.json` | 改：`sha256_at_review` 一行 | D14 |
| `docs/reviews/v24-deviation-ledger-2026-10-23.md` | 改：`D-ABI-W4-1…6` | 见下 |
| `docs/reviews/v24-conformance-matrix-2026-10-23.md` | 改：W4a/W4b/W4c 小节，closeout 仍 11/11 |  |
| `docs/reviews/v24-tool-plugin-abi-w4-execution-2026-10-31.md` | 新：三段式执行记录 |  |

**零 diff**：`v24/sql/**`、`v24/load.py`、`v24/b0/**`、`v24/s10/**`、`v24/s11/**`、`v24/s13/vectors/**`（`design_conformance.json` 的 SHA 元数据除外）、`v24/host/{canonical,descriptor,tool_schema,renderers,tool_results,line_json,journal,db,process_io}.py`、`v24/s13/{test_descriptor,test_schema,test_renderers,test_results,test_registry,test_line_json,test_contracts,test_vectors,capture_vectors,w1_reference}.py`（`test_contracts.py` 的 SHA 常量除外）。

**偏差台账新增**（`D-ABI-W4-*`）：

| id | 偏差 | 处置 |
|---|---|---|
| D-ABI-W4-1 | `lookup_install` 之前的失败仍是 v1 形状（协议不可知） | 接受；`test_wiring.py` 固化该边界 |
| D-ABI-W4-2 | `match_tool` 被提到 args 校验之前（§5.5 字面是 args 先） | 接受；schema/per-tool timeout 只有绑定后可得 |
| D-ABI-W4-3 | pre-spawn 拒绝仍已有 `dispatch_started`（worker 先写） | 接受；零 spawn 用进程计数，不用 journal |
| D-ABI-W4-4 | host 不拒绝 60001..65536 的 frame | 接受；§5.6 只把 >65536 判 `stdout_limit` |
| D-ABI-W4-5 | `environment()` 只在 allowlist 含名时注入 root | 接受；避免改 W3 gate 的 `expected_env` |
| D-ABI-W4-6 | `tool_pages.py` 不在 design §7.1 原表内 | 接受；D14 的 C.12 补入 |

---

## 风险、STOP 与回滚

1. **v1 字节变化**（provider 请求体、tool message、line-json 帧、descriptor）：任一 B0 断言变红 → STOP，回退 `deepseek.py`/`worker.py` 改动，先证明 v1 逐字节不变再继续。
2. **`dispatch_payload_keys` 变化**：`dispatch_finished` payload 多键即 STOP —— `model_text` 只能进 `tool_message.content`。
3. **`descriptor_v2_rejected` 变红**：`_tools` 的判定顺序错 → 回到 D7 的三步序列，不得改 golden 或断言。
4. **v2 帧超 64 KiB**：`stdout_limit` unknown → 缩页/缩预算；**禁止**抬高 transport 上限。
5. **`tool_pages` 与 `page_error` 差分不一致**：以 design §5.6 文本裁决，不以参考实现为准；`w1_reference.py` 属冻结面（零 diff），若它错，**不得在 W4 修改它**，而是把差异记成 `oracle_gap` 并让 host 按 design 拒绝（C5）。
6. **`registry.py` diff 超出 D12 精确 patch**：STOP，回退并改用不改 registry 的方案（插件从 `cwd` 取 root 并把该偏差写台账）。
7. **Node 缺失 / 平台非 UTF-8 名称能力**：`test_node.py` 必须 `[SKIP]` exit 2；`test_tools.py` 仅在 Node 缺失、preload 不可用或 runner 明确不支持 `NODE_OPTIONS` 时 SKIP/exit 2，不计通过；macOS 的 APFS `EILSEQ` 由 D16 的 `preload_shim` 处理，不是 SKIP 原因。Linux 真实名称失败必须 FAIL/STOP，不得回退 shim。任何 SKIP 都阻断 W4b 完成声明，W4c 同样阻断。
8. **12 秒墙钟用例**：不得进 gate。出现 `time.sleep(12)` 类用例 → 拒收。
9. **pinned span SHA 变化**：附录追加后任一 span 的 content SHA 变 → 说明改到了正文，回退。
10. **fake/real 边界**：`v24/s13/**` 不得打开网络套接字、不得构造真实 provider；只能起本地插件子进程。

**回滚**：三个子阶段都是增量。W4a 回滚 = **先排空在飞 effect**（等 `dispatch_started` 的 claim 全部 settle，不新接 v2 派发），再删 `tool_pages.py` 与两 gate、恢复 `plugins.py`/`worker.py`/`deepseek.py`/`registry.py`；v1 行为从未改变，v2 install 在旧 host 上走 `match_pin` 的 `AdapterNotFound("protocol_mismatch")`（`registry.py:460-463`，零 spawn），**不是** `adapter_not_approved`（C11）。W4b/W4c 回滚 = 删新增文件与 README 小节。无 SQL/schema 迁移，无数据回滚。

---

## 提交与推送

按 `AGENTS.md`，每个子阶段独立完成「测试全绿 → 更新收尾工件 → 逐路径 `git add` → 复查 `git status` 与密钥 → `commit` → `push origin main`」。**不得** `git add -A`/`git add .`；不得 `--no-verify`；不得 force push。

| 子阶段 | 提交信息 |
|---|---|
| W4a | `v24: wire v2 dispatcher, worker model_text and provider projection` |
| W4b | `v24: add v2 filesystem read/list/search tools with page contracts` |
| W4c | `v24: add v2 lifecycle, replay and Node extension gates` |

每次提交前必须复跑该子阶段的完整串行表（W4a 29 条、W4b 30 条、W4c 32 条 gate，外加 6 条 scope audit），并确认 `v24/sql` 零 diff、冻结向量零 diff、凭据扫描无命中。

---

## W4 不证明什么

- 不宣布 M3 完成；W4b 只声明「M3 实现完成」，`tool.search_budget_timing_m3_pending` 仍 pending（O8=B）。
- 不证明 design 里除 M2/M3/M4 之外还有别的阶段完成；不证明 §8 的 kernel revision（`replay_safe` 只读重投、`dispatch_started` 前移）已做。
- 不证明 12 秒扫描预算的墙钟行为、cutoff 的页填满判定、跨平台计时一致性（D10）。
- 不证明第三方插件、任意 renderer、沙箱、恶意并发 workspace、二进制/图片内容块（§9 的退出条件）。
- 不证明真实 provider 调用；所有 gate 用 FakeLLM/`ScriptedTransport`，不打开网络。
- 不证明 `replay_class` 是授权；它仍是 metadata only，successor 仍 `no_replay`。
- 不把 closeout 从 11/11 改写；s13 的九个 gate 仍是 extension evidence，不是第 12 条 closeout。
- 不证明 `tool.search_budget_timing_m3_pending`、`manifest.artifact_digest_pending` 等在 W1 就标 pending 的项；它们各有自己的 owner。

---

## Oracle 裁决记录（2026-10-31）

第一轮三条 lane（`claude-opus-5-5`、`gpt-6.1-sol-xhigh`、`kimi-code-plan-cn/k3.1-pro`）。初次记录曾把第三 lane 标为「交互超时、仅部分内容」，但第二轮复审时三条 lane 均完整返回；O1 的「lane 3 只给部分内容」与 O8 的「合并采纳」均已作废/改写（见第二轮）。以下逐项记录第一轮的采纳与不采纳，理由基于代码证据而非 lane 顺序。

| # | 决策 | 裁决 | 采纳/不采纳说明 |
|---|---|---|---|
| O1 | W4 范围 | lane 1/2：只做接线；lane 3：W4a/b/c | **取 lane 3 的结构 + lane 1/2 的边界措辞**。任务书明确列出 `s13/plugins/*`、`fixtures.py` 与三个 test 文件，故 W4 含全部；完成声明按子阶段拆开（D1、O7） |
| O2 | §5.6 校验归属 | 三 lane 一致：新增 `tool_pages.py`，排在 render 前 | 全部采纳。lane 1 的差分 oracle 建议（`w1_reference.page_error`）经代码核实存在，采纳 |
| O3 | `_tool` 分流 | 三 lane 一致：拆 `_tool_v1`/`_tool_v2` | 采纳；v1 方法体逐字搬迁 |
| O4 | `model_text` 接口 | lane 1/2：worker 归一三元组，v1 handler 不改 | 采纳。lane 1「新函数、不动 `_call_tool_handler`」与 lane 2「直接改 `_call_tool_handler`」的差异不影响字节；取直接改，因 `_call_tool_handler` 只有两个调用点且都在 `worker.py` |
| O5 | lease 预检位置 | lane 1：dispatcher（`dispatch_started` 之后）；lane 2：worker（之前） | **取 lane 1**。理由：design §7.1 明写「worker lease 逻辑不动」；lane 2 的做法需要给 worker 加 dispatcher 协议并把检查搬进 worker，改动面更大。lane 2 指出的「dispatcher 在 `dispatch_started` 之后」是真事实，但不构成违约：B0 只要求进程计数，且 v1 `require_artifact` 今天就是这样 |
| O6 | `_tools` v2 判定 | lane 1：最小自洽检查；lane 2：调 `validate_descriptor` | **取 lane 1**，但保留字常量从 `descriptor.py:31` 单名导入，避免第二份字面量。不取 lane 2 的理由：provider 侧只做投影前自洽，审批权威在 `match_tool`。「避免重依赖」不是理由——`descriptor.py:26` 已 import `RENDERERS` 与 `tool_schema`，此处按 C10 删掉该措辞 |
| O7 | M2 完成声明 | 三 lane 一致：可以宣布，但必须带边界 | 采纳；边界措辞见「与 M2 完成判定的关系」 |
| O8 | 12 秒预算 / M3 完成口径 | **第一轮记录不准确**：本轮 lane 3 明确反对在 cutoff 未证时宣布 M3；lane 2 的虚拟时钟不是「备选」；lane 1 接受带边界声明 | **已二次裁决：B（2/3）**，见下。无争议部分保留：W4a 证 per-tool timeout + lease 用该 timeout；W4b 执行确定性文件数预算；不做 `sleep(12)` 墙钟 gate |
| O9 | design 修订形态 | lane 1：附录 C.11–C.16 + 原子 repin；lane 2：直接改 §7.1/§7.3/§7.4 | **取 lane 1**。lane 2 的原地改会移动所有 pinned span 行号，破坏 `test_contracts.py` 的行锚定断言 |
| O10 | `environment()` root 注入 | 三 lane 均未单独裁决（复核期新发现） | 本计划新增 D12：条件式注入，理由是不打破 W3 的 `expected_env` 现算断言 |

**未决假设**（实现时必须在执行记录里点名，不得默认成立）：

1. `PluginHarness` 能否直接承载 `ApprovedPlugin`（`build_registry` 是否 v1-only）。若不支持，s13 `fixtures.py` 自建 registry，s11 零 diff。
2. `effect` 字典传给 handler 时是否带 `lease_until`（`worker.py:824` 与 `:973` 对同一 claim 读回的 effect 直接用 `effect["lease_until"]`；`_execute_tool` 路径需 W4-0 实测）。D6 已定两条路径：带则直读，不带则 `db.host_effect(effect_id)` 读回；探针二选一后写进执行记录，不得两条都留成实现分支，也不新增 journal 字段。
3. `test_line_json.py` 的 `env_names` 不含 `V24_WORKSPACE_ROOT`（已核对为 `("PATH","HOME","V24_W3_UNSET_TEST_VARIABLE")`，此处仅作复跑前提醒）。

---

## 第二轮共识修订（2026-10-31）

第二轮复审（三条 lane 均完整返回）确认了 11 条代码层共识；本节记录它们落到计划哪一处。所有条目都以代码/规格证据为准，不以 lane 多数为准。

| # | 共识（证据） | 计划落点 |
|---|---|---|
| C1 | `parameters_check`/`output_check` 抛 `InstanceError`（`tool_schema.py:83`，`(path, rule)`），不是 `SchemaError`；后者只用于 schema 定义错误 | D2 事实句、D4 第 3/10 步、W4a Done-when #3、`test_wiring` 新增 (b) |
| C2 | `ApprovedTool` 没有 `limits` 属性（`registry.py:165-176`）；limits 在 `tool.descriptor["tool"]["limits"]`，且 `__post_init__` 已校验 | D4 第 2 步的 `_limits(tool)`、W4a Done-when #3 |
| C3 | `tool_handler` 会把 `AdapterNotFound`/`LineJsonPreflight` 压成 v1 形状（`plugins.py:40-45` → `_tool_error` `:207-208`），没有 v2 envelope | D4 的 envelope guard、D3 偏差说明、W4a Done-when #3、`test_wiring` 新增 (a) |
| C4 | worker 的 `tool_handler is None` 与 `except` 两条分支没有 `model_text`（`worker.py:1050-1062`），`:1069` 却要用它 | D5 新增分支条款、W4a Done-when #4、`test_wiring` 新增 (c) |
| C5 | 差分域混入 schema-invalid 值；`page_error` 对空 read 不看 offset、对 `skipped` 不查非负（`w1_reference.py:280-312`；design §6.2:819） | `test_pages` 差分只对 `output_check` 通过值做 ⇔、两处 `oracle_gap` 单边、风险 #5 |
| C6 | scope audit 没有固定基线；`#4` 标识符白名单与 D12 实现矛盾；`#3` 的 numstat 1/1 可被单行改动伪造 | Scope audit 全部钉 `c8c4bd0`、`#3/#4` 改为还原后逐字节相等、风险 #6 |
| C7 | 默认 30s lease、T≤15s，正常派发永远到不了 19999ms 的边界（`design §3.4:423-430`、`_lease_for` 固定 30s） | D10 的 lease 用例改为构造 claim 的 `lease_until`，并用 spy 断言传入值；`test_wiring` 新增 (d) |
| C8 | 插件向 `cwd/spawn.log` 追加会写进 install/源码目录；artifact 又必须在 cwd 内（`registry.py:63-74`） | 新增 D15：日志只走 approved argv 的 `--spawn-log <abs path>`；W4-0 定死 cwd/artifact 布局；测试/夹具/stub 全部改路径 |
| C9 | v2 帧键是 `operation` 不是 `op`（`line_json.py:164-180`）；descriptor 必须绑定内建 renderer 才能测第 10/12/13 步 | stub 小节与 `fs_read` 小节改 `operation`；stub 显式绑定 `read` renderer |
| C10 | D7 的「避免重依赖」不成立（`descriptor.py:26` 已 import `RENDERERS`/`tool_schema`） | D7 与 O6 行删掉该理由，保留「审批权威不在 provider」 |
| C11 | 旧 host 对 v2 install 抛 `protocol_mismatch` 而非 `adapter_not_approved`（`registry.py:460-463`）；回滚须先排空在飞 effect | 回滚段改写、D3 偏差说明 |

### O8 二次裁决：W4b 能否宣布 M3 完成

这是第二轮唯一未收敛的实质分歧，交回三条 Oracle lane 裁决。事实基础：

- design §10 的 M3 done-when 只写「`test_tools` 全绿；真实子进程；分页收敛」，**没有**列 12 秒 cutoff（`docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:1066`）；
- 但 `v24/s13/vectors/tool_contracts.json:4414-4423` 的 `tool.search_budget_timing_m3_pending` 的 `first_production_stage=M3`、`status=m3_pending`；
- design §6.3:871 规定扫描预算 12s、低于 15s timeout；§5.6:776 规定 cutoff 时不得返回「不足 limit 且无后续证据」的 incomplete 页。

备选：

| 选项 | 声明 | 代价 / 风险 |
|---|---|---|
| A（最小改动） | 保留 M3 完成，但声明逐字限定为 design §10 的三条 done-when；timing case 是 M3-owned 但不在 done-when，保持 pending | lane 1 满意；lane 2 可能接受；lane 3 仍反对（认为会让读者误以为 cutoff 已验证） |
| B（保守） | W4b 只声明「M3 实现完成，timing pending」，不宣布 M3 完成 | lane 2/3 满意；代价是 design §10 的 M3 在 W4 结束时仍不算完成 |
| C（最严谨） | 加一个可注入/虚拟时钟的 12 秒 cutoff 用例，覆盖 cutoff 快照、sentinel、页填满规则（禁止 `sleep(12)`），然后保留 M3 完成 | 唯一可能 3/3 全绿；W4b 增加约 100–150 行测试与一个可注入时钟的插件接口，且仍不证明真实墙钟 |

### 二次裁决结果（2026-10-31）

三 lane 全部完成，未再超时：

| lane | 模型 | verdict | O8 |
|---|---|---|---|
| 1 | `claude-opus-5-5`（xhigh） | approve-with-fixes | **C** |
| 2 | `gpt-6.1-sol-xhigh`（xhigh） | approve-with-fixes | **B** |
| 3 | `kimi-code-plan-cn/k3.1-pro` | request-changes | **B** |

**最终取 B**：C 的虚拟时钟能覆盖 cutoff 快照/sentinel/页填满，但仍不能证明 12 秒墙钟；为了让 M3 完成声明成立而增加一个测试专用时钟缝，属于用「可注入」换「可声明」，不改变 `tool.search_budget_timing_m3_pending` 的 pending 事实。B 与 design §10 的 M3 done-when 不冲突（W4b 仍完成 `test_tools`/真实子进程/分页收敛），只是拒绝把它写成 M3 完成。C 作为后续 owner 的可选增强记录，不进入 W4b 的完成条件。

因此：D1 表、W4b Done-when #5、W4-9 的完成信号统一为「M3 实现完成，timing/cutoff pending」；`v24/s13/vectors/*.json` 的 status 不改（D13）。

### 第二次 Oracle must-fix 处置

| # | 指控 | 处置 | 落点 |
|---|---|---|---|
| R1 | `V24_SPAWN_LOG` 无法按 install 注入（allowlist 只传变量名） | **接受**；改为 approved argv 的 `--spawn-log <abs path>`，每 install 独立 | D15、stub、fixtures、test_wiring/lifecycle |
| R2 | D6 与「未决假设 #2」对 `lease_until` 缺失的处理矛盾 | **接受**；W4-0 探针定论：effect 带则直读，不带则 `db.host_effect` 回读，两者都失败才 fail closed | D6、未决假设 #2 |
| R3 | v2 envelope 写成「五键」与 handler `{class,result,model_text}` 矛盾 | **接受**；三键 + `result={status,output,usage}`；claim/body 属 worker outcome | D4 guard、test_wiring (a)、C3 |
| R4 | `compact_json(args)` 对 float 抛 `CanonicalError` 会变 unknown | **接受**；捕获 `(CanonicalError, RecursionError, UnicodeError)` → `invalid_tool_arguments`；输出侧 → `invalid_tool_output`/`output_too_large` | D4 #2/#10、test_wiring (b) |
| R5 | `test_pages` 的 `sys.modules` 检查与同进程 import oracle 冲突 | **接受**；import 方向检查放子进程，父进程再 import oracle | test_pages |
| R6 | D12 补丁是 +5/−1 不是 +6/−1；审计「五行」需统一 | **接受**；统一 +5/−1，精确 patch 文本进 C.12 | D12、file-by-file、scope audit |
| R7 | scope audit 的 `! grep`、untracked 文件、`[passed]` 口径 | **接受**；改 `if grep…then exit 1`、加 `git ls-files --others` 检查、`[passed]` 只用于测试 gate | scope audit、Done-when #8 |
| R8 | `InstanceError.path` 可含模型提供的长键名/`/etc/...`，泄漏检查会拒 | **接受**；path>256 或 failure_output 拒绝时退化为 `$`+rule；加 `/etc/passwd` 形键名用例 | D4 host message、test_wiring |
| R9 | Node 缺失时 W4b 仍可能宣布完成 | **接受**；Node 部分 SKIP → W4b 不得完成 | 风险 #7 |
| R10 | `fixtures.workspace` 未 realpath，macOS `/tmp`、`/var` 是 symlink | **接受**；返回 `os.path.realpath` 后的根 | fixtures |
| R11 | D9 的 60001..65536 可能撞冻结向量 | **驳回**：`test_results.py:250-252` 已把 60000/60001/65536/65537 分类为 within/over-target/transport-valid/unknown，D9 与之一致 | D9（补证据引用） |
| R12 | D5 在 `_call_tool_handler` 内提前算 canonical_json，会把 v1 失败面挪进 try | **接受**；legacy 返回 `model_text=None`，`_execute_tool` 在 try 外回落 | D5、C4 |
| R13 | `unknown_output` 无 wall_ms 参数 | **接受**；`_v2_unknown` 构造 `result={status,output,usage}` 后过 `ToolDispatchResult` | D4 #8、D8 |
| R14 | D12 条件注入的 allowlist 缺失需要显式失败 | **接受**；v2 fixtures 强制 allowlist 含 `V24_WORKSPACE_ROOT`，并加缺失失败用例 | D12、Done-when W4a #6 |

---

## References

- `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md`（§5.2、§5.3、§5.3.1、§5.4、§5.5、§5.6、§6.1–§6.4、§7.1–§7.4、§8、§9、§10、附录 C.7–C.10）
- `docs/plans/v24-tool-plugin-abi-w3-registry-transport-2026-10-31.md`、`docs/plans/v24-tool-plugin-abi-w2-host-contracts-2026-10-30.md`
- `docs/reviews/v24-tool-plugin-abi-w3-execution-2026-10-31.md`、`docs/reviews/v24-tool-plugin-abi-w2-execution-2026-10-30.md`
- `docs/reviews/v24-deviation-ledger-2026-10-23.md`（D-ABI-W3-1…9、D-B0-4）、`docs/reviews/v24-conformance-matrix-2026-10-23.md`
- `v24/b0/README.md`（W4 contract-frozen 段）、`v24/b0/golden/{tool_messages,provider_requests}_v1.json`、`v24/b0/test_golden.py`
- `v24/s13/README.md`、`v24/s13/vectors/{results_v2,provider_projection_v2,manifest_adapter_v2,frames_v2,descriptor_v2}.json`
- `v24/host/{plugins,worker,deepseek,registry,line_json,tool_results,renderers,tool_schema,canonical,process_io,journal,db}.py`
- `v24/s11/{plugin_fixtures.py,test_g10.py}`、`v24/s1/setup_db.py`、`AGENTS.md`

---

## Result

### W4a（2026-10-31，实测完成）

基线与候选：`main`，HEAD `c8c4bd09acf87ff3338477c8e18d4933df64d87c`；authoritative sweep 2026-10-31T02:59:06Z–03:00:40Z，scope audit 03:00:51Z–03:00:53Z。29 条串行命令全部 exit 0；第 1–28 条末行为命令专属 `[passed]`，第 29 条是计划表中的 `git diff --exit-code c8c4bd0 -- v24/sql`（空输出，无 `[passed]`）。无 exit 2/SKIP/缺 marker。两条 marker 原文：

```text
[passed] W4 page contract; contracts=3; cases=5417; oracle_differential=4281; unknown_ref_rejected=true
[passed] W4 dispatch wiring; cases=56; zero_spawn_paths=6; model_text_bytes=11; v1_bytes_unchanged=true; resource_receipt_v1=true
```

第 14–24 条为 11 条冻结 closeout：**closeout 仍 11/11**，s13 不是第 12 条。六项 scope audit 全部 exit 0（冻结模块与 untracked、vectors 除 design 元数据、design 还原后逐字节相等、registry D12 +5/−1、host import purity、SQL 零 diff），全部显式钉 `c8c4bd0`。design 只追加 C.11–C.16：旧 `269e6bada20c6c18331cc681f385808d638bd6ac9403dd7b484352175f57e4b0` → 新 `15afb72dfb8f4f274d36b1722ad3b50501388abbe2a6a0d0ce6e6eeba12f7800`，旧字节是新字节的精确前缀，25 处引用的 23 个 pinned span 的行范围/heading/content SHA 全部不变；`test_contracts.py` 仅改 `DESIGN_SHA256`，`design_conformance.json` 仅改 `sha256_at_review`。

实现与覆盖：`tool_pages.py` 三合同、5417 page cases、4281 差分、两处 oracle gap 单边；`plugins._tool` 分流、`_tool_v2` 十三步与 envelope guard；`worker` 三形态归一与 try 外回落；`deepseek._tools` v2 投影（v2-only `name:key`，v1 保持 `_safe_name` 哈希）；`registry.environment()` 条件注入。`test_wiring` 56 cases，六类零 spawn（sentinel + `--spawn-log` 双证）、11 个 stub scenario、19999 ms lease spy、per-tool timeout、11 B model text、v1 resource receipt。证据目录 `/tmp/w4a-20261031T025906/`（`provenance.txt`、`git-status-porcelain.txt`、`source-sha256.txt`、`credential-scan.txt`、`01.log`–`29.log`、`results.tsv`、`merged.log`、`scope-audit.tsv`、六个 scope 日志）；逐条时间/exit/末行/日志 SHA 见 [W4a execution record](../reviews/v24-tool-plugin-abi-w4-execution-2026-10-31.md)。

偏差：`D-ABI-W4-1…7` 已写入 [deviation ledger](../reviews/v24-deviation-ledger-2026-10-23.md)。D-ABI-W4-7 记录 v2 provider 命名分叉（v2 安全 key 使用 `name:key`，否则回退 `_safe_name`；v1 完全保留 `_safe_name`），触发点是首轮第 25 条 G9-A 对全局改名报红，回退后从 01 完整重跑全绿，失败证据 `/tmp/w4a-20261031T025653/` 不作最终证据。

done-when #8 的 registry 审计按等价判据关闭：原文 `git diff -U0` 单 hunk 字面要求因基线 `return` 是两行而不可满足；实际以「`git show c8c4bd0` + D12 替换后逐字节相等」为主判据，并以 `git diff -U1` 断言一个 hunk、1 deletion/5 additions（同一处 +5/−1，hunk 数不同仅因零上下文会以第二行作上下文）。该替代判据记录于 ledger 的「审计方法记录（非 ABI 编号）」段，未放宽 gate，也未改变代码或 design。

未决假设：(a) `ApprovedAdapterRegistry` 接受 `ApprovedPlugin`，但 `build_spec`/`build_adapter` 只产 v1；W4b 自建 v2 registry，s11 零 diff。(b) 实测 `_execute_tool` 收到的 effect 含 `lease_until`（`status=claimed`、`kind=tool_call`），实现直读该字段，无 `db.host_effect` 回读分支；缺失/非字符串 fail closed。(c) `test_line_json.py` 的 `env_names` 仍是 `("PATH","HOME","V24_W3_UNSET_TEST_VARIABLE")`（定义在 118 行；计划 171–178 是 `expected_env` 现算处）。

**M2 完成声明（带边界）**：W4a 完成 M2。该声明不表示真实文件系统工具、分页收敛、mixed batch、崩溃重启、replay、12 秒预算已验证；closeout 仍 11/11，s13 不是第 12 条 closeout。

### W4b（2026-10-31，实测完成；M3 实现完成，timing/cutoff pending）

基线与候选：`main`，HEAD `3d95d5fa7ceeb593942b2a76275f69cff962b577`；30 条串行命令全部 exit 0，第 30 条 `test_tools.py` 同时打印 `[evidence] non_utf8_source=preload_shim; linux_real=not_run` 与 marker：

```text
[passed] W4 fs tools; cases=74; read=16; list=7; search=24; pagination_converged=true; page_contracts_imported=3
```

第 14–24 条为 11 条冻结 closeout：**closeout 仍 11/11**，s13 不是第 12 条。六项 scope audit 全部 exit 0，全部显式钉 `c8c4bd0`；frozen 检查已扩展到 s13 测试文件，并断言 `test_contracts.py` 只改 `DESIGN_SHA256`。design 只追加 C.17：旧 `15afb72dfb8f4f274d36b1722ad3b50501388abbe2a6a0d0ce6e6eeba12f7800` → 新 `ab4636fcae5361cc237b16cdd893c2c544d80e770e8e13269b3d4205713d528b`，旧字节是新字节的精确前缀，25 处引用的 23 个 pinned span 全部不变；`test_contracts.py` 仅改 `DESIGN_SHA256`，`design_conformance.json` 仅改 `sha256_at_review`。

实现与覆盖：`fs_read.py` 全部 16 个 read 输入；`fs_tools.js` 全部 7 个 list 与 24 个 search 输入（含 10000/10001 文件预算、10000 list 项、10000 files search 快照、sentinel 不完整页、glob/context/Unicode/skip 计数）；`fixtures.py` 复用 s11 `PluginHarness`；`test_tools.py` 74 cases，含 15 个跨语言 path 错误、4 个 selector 非单调前缀探针、3 个 DB harness 端到端、5 个 shim 差分/control 守护。分页枚举全部前缀、不假设单调、不二分、不在首败停止；没有 `sleep(12)` 或墙钟 gate。macOS APFS 拒绝原始非 UTF-8 名称，按 D16/C.17 使用 test-only preload；生产插件无测试 seam；Linux real 模式尚未运行，记录 `linux_real=not_run`，不得写成已验证。

证据目录 `/tmp/w4b-20261031T043334/`；逐条时间/exit/末行/日志 SHA、scope audit、shim 边界与局限见 [W4b execution record](../reviews/v24-tool-plugin-abi-w4b-execution-2026-10-31.md)。

**M3 实现完成声明（带边界）**：W4b 完成 M3 实现；timing/cutoff pending，`tool.search_budget_timing_m3_pending` 仍为 `m3_pending`。**不宣布 M3 完成**；不表示 12 秒墙钟、cutoff 页填满时序、跨平台计时或 Linux real 证据已验证。W4c 仍是 downstream。

### W4c（2026-10-31，实测完成）

基线与候选：`main`，HEAD `80dc0c45f5f7618fecb1a97f09cbe67b2caef109`；32 条串行命令全部 exit 0。W4c markers：

```text
[passed] W4 lifecycle; cases=14; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true
[passed] W4 node contract; node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node
```

第 14–24 条为 11 条冻结 closeout：**closeout 仍 11/11**，s13 不是第 12 条。六项 scope audit 全部 exit 0，全部显式钉 `c8c4bd0`；W4c 不改 design/design_conformance/test_contracts/生产 host/向量，design SHA 仍为 `ab4636fcae5361cc237b16cdd893c2c544d80e770e8e13269b3d4205713d528b`。

覆盖：G12-A 双 install、三 key、真实 Python/Node 子进程、完整 off/dispose/release/scope close；G12-B 同一 model batch 三工具、屏障后恰一个 continuation、list/search 同一 install；G12-C/D/E/F/H 的非法 args、非法 output/render、timeout、tamper、lease 不足路径；G12-G `dispatch_finished` 后崩溃后重建 journal/worker，`_reconcile` 只重放 journal；G12-L success/known_error 的 B0 provider/tool-message 字节逐字节相等。replay 断言 `replay_source=journal tool_message`、`rerender=false`、`second_spawn=false`、`journal_event_types_unchanged=true`；三个 replay 相关 `m4_pending` case 只执行、`status` 不变。Node 缺失时 `test_node.py --node` 打印 `[SKIP]` exit 2，不是 PASS；最终运行 Node `v24.13.1` 存在。

**M4 完成声明（带边界）**：W4c 完成 M4。该声明不回溯使 W4b 的 M3 timing/cutoff 完成；`tool.search_budget_timing_m3_pending` 仍为 `m3_pending`，不表示 12 秒墙钟、cutoff 时序或跨平台计时已验证。closeout 仍 11/11，s13 不是第 12 条。证据目录 `/tmp/w4c-20261031T044427/`；逐条时间/exit/末行/日志 SHA、scope audit 与 replay 细节见 [W4c execution record](../reviews/v24-tool-plugin-abi-w4c-execution-2026-10-31.md)。
