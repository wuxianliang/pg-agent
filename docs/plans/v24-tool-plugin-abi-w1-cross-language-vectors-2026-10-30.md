# v24 Tool/Plugin ABI W1：跨语言向量与合同同步 Deep Plan

日期：2026-10-30。状态：W1 合同、向量及回归验收完成；W1-10 发布待完成。

## Goal 与范围

W1 对应 ABI 设计 §10 的 M1「合同与向量」。它冻结 descriptor v2、line-json v2、renderer、result/`model_text`、封闭 JSON Schema 子集以及 `read`/`list`/`search` 合同的固定向量，并正式处理 B0 留下的 Q1–Q5 候选规则。W1 只交付合同、数据向量、独立测试参考实现与只读 checker；不改生产执行路径，也不声称生产 validator、renderer、dispatcher 或文件系统工具已经实现。

W1 完成后，M2 必须能按固定向量实现生产代码；M3/M4 必须按已同步的工具与生命周期合同验收。任何规则若不能形成可执行、确定的合同，尤其是 Q5 预算责任，W1 应停止并回设计评审，而不是将矛盾推给工具实现阶段。

## Done when

以下条件必须全部满足，才可将 W1 标为完成：

1. 新版 ABI 设计稿正式 ratify 或修订 Q1–Q5；所有矢量、README、计划和 ledger 用同一合同口径。Q5 若无法证明插件能确定性预测 host renderer 的 content 大小并保证游标推进，触发 STOP-R，不得关闭 W1。
2. W1 使用独立版本化向量格式，固定 case ID；`expected_hex` 是唯一 bytes 权威；长度和 SHA-256 只验证向量自洽；checker 只读，不能 re-bless。
3. descriptor canonical bytes 对 Python、Node、PostgreSQL 三方均直接比对相同固定期望 bytes；不以各自产生的 hash 相互比较。Node 覆盖 PG 的 UTF-8 字节长度排序、无符号字节排序、空格和转义规则。
4. 向量包括 ABI 设计 §4.3 的 V1/V2/`{}` 已实算向量、完整三个 v2 descriptor、v2 frame 请求/响应分类、renderer manifest/golden、result/model_text、schema 正反例及三工具合同。renderer 值明确标记为 W2-pending，production renderer 不存在的事实保持清楚。
5. 设计稿中三个 `<*_RENDER_DIGEST>` 占位符均有可审查的向量 case 引用及由固定 golden 输入和公式计算出的 provisional digest；无法从固定输入复算则 STOP，不伪造数值。
6. B0 所有 v1 bytes/结构基线与 checker 不变。`structure.descriptor_v2_rejected` 明确标为 M2 前的现状观察；由于它输入的是不完整 descriptor，不得假设 M2 放宽版本检查后会接受它。
7. `v24/sql/**`、`v24/host/**`、`v24/s10/**`、`v24/s11/**`、`v24/load.py` 相对 candidate source snapshot 零 diff；不新增 SQL，因此不改 `SQL_LOAD_ORDER`。Closeout 仍为 11/11，W1 是 extension evidence，不是第 12 条 closeout。
8. W1 新检查、B0 v1 golden、11 条 closeout、G9、G10、Node 与 multilingual extension checks 在最终候选树中均实际运行并按规定三态判定为通过；无 exit 2/SKIP、`not_run` 或未验证项。
9. W1 README、ABI 设计、conformance matrix、deviation ledger、execution record 与本计划 Result 一致；候选 provenance、每条命令的实际结果和最终路径审计完整。

## Current-state analysis

现有链路是：

```text
manifest.provides[]
  → command_install / host_prepare / fiber_control(on)
  → slots.descriptor + descriptor_digest
  → start(requires[]) / run pins
  → model_call / provider tool projection {name,description,parameters}
  → model outcome {key,args} / tool_call
  → worker claim / journal
  → dispatcher install+pin+five-field+artifact checks
  → line-json v1 subprocess / {status,output,usage}
  → tool_message.content = canonical_json(output)
  → settlement / batch barrier / continuation
```

设计文档描述了 ownership：PostgreSQL 管 effect、pin、claim、receipt、budget、barrier 与 recovery；host registry 管审批制品及工具合同，dispatcher 管参数校验/进程/输出/render，worker 管 journal、外层 outcome 与 settlement（ABI design §2.1–2.2，`:218-247`）。W1 冻结接缝合同，不改变该链路。

| 接缝 | 当前事实与依据 | W1 处理 |
|---|---|---|
| Descriptor canonicalization | `registry.pg_jsonb_text` 和 `descriptor_digest` 在 `v24/host/registry.py:108-145`；SQL canonical 是 `p_payload::text`，见 `v24/sql/30_advance.sql:4-6`。 | 复用现有 Python 函数作被测 producer；PostgreSQL作独立 oracle；新增 W1-only Node producer。三者直比固定 bytes。 |
| v1 frames | `line_json.build_frame` 为 compact sorted JSON + LF，`v24/host/line_json.py:71-87`；parser 使用 `splitlines()` 且成功帧 result 为 JSON object 字符串，`:101-149`。 | v1 不改；v2 vectors 明确按 LF byte framing，W1 不实现 production parser。 |
| Provider projection | `deepseek._tools` 当前要求 `descriptor.v == 1`，投影只含 `{name,description,parameters}`，`v24/host/deepseek.py:341-380`；请求体 bytes 在 `:383-392`。 | 冻结 v2 投影期望；接受 v2 是 M2 工作。B0 的 v1 provider bytes 保持原样。 |
| Tool message / replay | worker 写 `canonical_json(output)` 到 tool message，`:1066-1077`；`_history` 从 journal 重建，`:1190-1231`；当前 handler 只接受二元 tuple 或 `{class,result}`，`:1302-1308`。 | 冻结 v2 `model_text` 与 no-rerender 合同；worker 接线归 M2/M4。 |
| Lease / journal | tool lease 固定 30 秒，`worker.py:86,919-922`；只对 model 做剩余 lease precheck，`:972-979`；六种 journal event 闭集见 `journal.py:26-33`。 | 只记录现状和后续合同，不改 lease、事件或恢复行为。 |
| Tool runtime | 当前 `ApprovedAdapter` 单工具，`registry.py:148-227`；`plugins.py:56-83` 调用 v1 dispatcher。 | 未来 multi-tool/vector 只作为合同数据；ApprovedPlugin 与工具运行行为归 M2/M3。 |
| B0 evidence | B0 有四域 v1 golden、固定 inventory 和只读 checker；完成同 install 两个 provides→两个 slot→同 run 两个 pin 的 DB-only 证明。见 B0 plan `:136-141,195-244` 与 execution record `:233-290`。 | 引用已完成的 multi-provides 证明，不重跑该探针；最终仍重跑 v1 golden 与继承 gates。 |

### Bytes authority 必须分域

不得统称或互换这些 canonical forms：descriptor digest 使用 `registry.pg_jsonb_text`/PG `jsonb::text`；v1 line-json request 使用 `line_json._canonical`；provider request 使用 `deepseek._canonical`；journal/tool message 使用 `journal.canonical_json`；renderer/adapter/manifest digest 使用其各自约定的 compact sorted JSON。对应实现见 `registry.py:108-145`、`line_json.py:71-87`、`deepseek.py:111-114,383-392`、`journal.py:64-73` 和 B0 plan `:217-223`。

### B0 rejection probe 的生命周期

`v24/b0/test_golden.py:139-149` 的 `structure.descriptor_v2_rejected` 送入 `{"v":2,"tool":{}}`，当前 `_tools` 返回 `descriptor_invalid`。该输入同时缺少完整 v2 descriptor 与合法 `parameters`，所以 M2 放宽 `v in (1,2)` 后它仍可能因形状错误而拒绝。W1 不改 B0 gate；文档须称其为「历史 v1 baseline / pre-M2 结构观察」，不能称为永久 v2 合同或预期必翻转的正向测试。M2 必须新增完整合法 v2 descriptor 的接受/投影断言，同时保留该 malformed input 的拒绝断言并区分原因。

### 现有候选树约束

primary `main` 工作树已有并行 modified/untracked 文件，包含 ABI 设计稿本身及 matrix/ledger 的其他改动。W1 执行必须先记录 HEAD、branch/upstream、完整 status、环境版本和排序后的 source hashes，从明确的 B0 source commit `f990b1d` 建立 candidate/worktree；将设计稿、计划等输入按已记录 SHA 显式引入。不得 stash、reset、覆盖或把并行线内容带入 W1 staged set。B0 的隔离流程见 B0 plan `:144-162`，仓库提交要求见 `AGENTS.md:1-31`。

## W1 boundary and decisions

### W1 冻结什么，后续阶段实现什么

| W1 固定的数据/合同 | 首次生产行为验证 |
|---|---|
| Descriptor v2 完整 JSON、PG canonical bytes/digest、closed-set 正反例 | M2 `descriptor.py` / registry validation |
| Schema whitelist/denylist、schema 自身与 instance 正反例、边界与稳定错误路径 | M2 `tool_schema.py` |
| v2 request frame bytes、response raw-frame classification corpus、unknown reasons | M2 独立 line-json v2 build/parse |
| 三个 renderer 的 `args/value → content/meta` cases、manifest digest 输入与 provisional 值 | M2 `renderers.py` |
| Result envelope、status/class/spawn mapping、usage、model_text bytes | M2 `tool_results.py`、plugins/worker 接线；replay 部分由 M4 验证 |
| read/list/search 参数/output/error contracts、fixture tree 和 expected cases | M3 工具子进程与 M4 lifecycle |
| Q1–Q5 修订后的合同及预算表 | M3 分页/预算行为 |

W1 helper 不得被 `v24/host/**` import。W1 不实现 production validator、renderer、ApprovedTool/ApprovedPlugin/match_tool、v2 worker/dispatcher、`deepseek._tools` v2 接受路径，也不运行真实 read/list/search。设计将 host foundation 放在 M2、工具放在 M3、lifecycle 放在 M4，见 ABI design `:847-903,1005-1013`。

### Vector format decision

使用 `v24/s13/vectors/` 下与 B0 v1 格式分开的 W1 格式，例如 `v24-tool-plugin-abi-w1-vectors-1`。保持 B0 文件和 pinned ID 原样。byte case 至少含 `id,kind,domain,producer,input_id,expected_hex,expected_length,expected_sha256,expected_text/status`；semantic/table case 含稳定 ID、固定 input/expected、状态和后续 owner。Checker 固定每个文件的 `REQUIRED_IDS`，拒绝缺失、重复或额外 ID；不依赖目录 glob 决定 case 数。采纳 B0 原则：非 UTF-8 不要求 expected_text 解码；checker 无 capture/re-bless 开关。B0 先例见 `v24/b0/test_golden.py:15-90`。

Capture 输出只能到显式指定、尚不存在且经 lexical 与 resolved path 检查位于 repo 外的目录；两次独立 capture 全文件逐字节相同，人工审阅后向量与 checker 原子纳入。B0 guard 见 `v24/b0/capture_golden.py:24-38`。向量不得含时间、随机 ID、PID、绝对临时路径、secret 或 Authorization。

### Renderer digest placeholders

生产 `renderers.py` 属 M2（设计 `:847-903`），所以 W1 仅冻结 renderer case 数据和公式：`golden_digest = sha256(UTF-8(compact_sorted_json(cases)))`；`render.digest = sha256(UTF-8(compact_sorted_json({id,version,projection,golden_digest}))`（设计 §5.3）。W1 独立 helper 推导完整、固定的 provisional 值；每个值状态标记为 `provisional-w2-pending`。descriptor case 引用该值，不把它描述为 production renderer 已计算或验证。M2 的 renderer 必须复现同一 golden cases 和 digest；不一致停止 M2，不得改写 W1 expected 来迁就实现。

Golden cases 必须使用固定对象 shape `{id,args,value,content,meta}`，按 case ID 的 UTF-8 bytes 升序构成 digest 输入数组；数组顺序不可依赖 JSON 对象排序。三个 renderer 的唯一全域语法为 ABI design §5.3.1：一个 text block、read/list footer 前两个 LF；search before→hit→after、summary 前两个 LF、N/N+、continuation 前一个 LF；无合成尾 LF。meta 恒为 `{}`，插件省略/空 meta 均可，非空 meta 为 invalid_tool_output；不得 merge 两个来源。Python/Node reference 各自从固定输入复现字面 content/meta 与 `27+E(T)`/2 计数，host renderer 仍由 M2 实现。按下述 Q5 adversarial obligations 冻结 cases；digest formulas 见 §5.3，不再从原始简写模板另推格式。

### Cross-language vector domains

- `descriptor_v2.json`：除固定设计 §4.3 V1/V2/`{}` bytes外，必须有完整 descriptor-validator semantic inventory：顶层与 tool 每层 missing/extra key；key regex/长度/`agent.spawn`/provide-key 不匹配；description 1/4096 bytes边界、NUL；render id/version/digest边界及 registry mismatch；每项 limits 的 min/max/min−1/max+1（`max_meta_bytes` 0/1拒、2/16384受、16385拒）；concurrency/replay enum；所有 annotation implications；PG bytes 16384/16385；depth16/17；safe integer/float/exponent/-0/lone surrogate。三份完整工具 descriptor 与 digest依赖 renderer vector完成之后生成。Canonical cases固定明文、hex、length、SHA；V2 `<DEL>` 是单字节 `0x7f`。V1/V2 SHA=`c1b10b0a8058cbccfc721f2418b4f5b022f87282e7ff91053265760dcf27039c` / `0ff17e8cd7831181e61773ca0803b1168a9ac78a0692d07d5a4ccd26dc0dcbac`；`{}` SHA=`44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a`（design `:477-499`）。Node helper 按UTF-8 byte length再unsigned byte order排序；不能用JS默认UTF-16 sort。严格检查不能靠 `JSON.parse` 后值识别已丢失的词法差异；需要Node预解析或将该负例明确作为parser-only、不声称它由canonicalizer验证。
- `frames_v2.json`：invoke request 恰有 `{v,operation,reservation,tool,args}`；prepare/release/inspect 不含 `tool`。Python/Node 对同一 `expected_hex` 逐字节相等，compact sorted UTF-8、无 BOM、恰一个 final LF；加入包含 astral key 与 BMP private-use key 的排序陷阱。成功帧按 operation 固定 result：invoke `{value,meta?}`，prepare `{"prepared":true}`，release `{"released":true}`，inspect `{"observed":"known"|"absent"}`；known error 帧 `{ok:false,v:2,error:{code,message}}`，code 符合 `^[a-z][a-z0-9_]{0,63}$`，message ≤1024 UTF-8 bytes，无绝对路径/stack/env/raw stderr；exit 0/3 必须与成功/known-error 帧匹配。Preflight semantic cases 覆盖 prepare 带 tool、invoke 缺 tool、invalid/reserved key（含 `agent.spawn`）、args 非 object。Response corpus 是 language-independent raw bytes→classification/reason，不要求响应 key order 相同；按 Oracle adjudication 接受 leading/trailing SP/HT/CR 和 CRLF，但 stdout 仍必须只有一个 raw LF 且处于末字节，payload 是一个完整 JSON text；拒绝空前缀、BOM、missing/non-final/multiple LF、额外帧、尾部非空白数据、invalid UTF-8、duplicate keys、NaN/Infinity、lone surrogates、wrong version/keys/ok/result/error shape。U+2028/U+2029 在字符串内不切帧；token 外使 JSON 非法。固定 diagnostics：empty stdout=`eof`，multiple raw LF=`extra_frame`，其余 frame-invalid=`bad_frame`，wrong version=`version_mismatch`，invalid UTF-8=`stdout_not_utf8`。Process unknown（timeout/stdout_limit/stderr_limit/abnormal exit）作为 structural/table cases，不伪造 W1 子进程运行证据。设计 v2 细节 `:512-571`；stdout 65536、stderr 16384、stdin 1 MiB，均不得抬高。
- `manifest_adapter_v2.json`：固定 v2 adapter declaration（compact sorted）、Python 单工具 read 与单个 Node install 的 `list,search` 有序 provides、manifest bytes/digest 和五字段 key 输入形状。artifact digest 依赖未来插件文件，标 M3-pending，不伪造。
- `results_v2.json`：成功 `{value,content,meta?}`、普通失败 `{error,content,meta?}`、unknown 仅 `{error}`；`usage` 只允许 `wall_ms`；tool-level errors 不进入 SQL `error_v1` 24 码（`30_advance.sql:19-37`）。记录 v1 model text 与 B0 case ID 的只读关联；v2 `model_text` 为 content text 按 `\n` join、不加尾 LF；meta 不进 model text；restart 只重放 journal、不重新 render。预算域分别是 args object（不含 frame/LF）、normalized value object、完整 content array、normalized meta object 的 deterministic compact UTF-8 JSON bytes；absent meta 与 `{}` 均计2字节但 wire 字段仍可缺省。加入 cap=2 的 absent/empty pass 与 `{"a":1}` (7 bytes) fail；frame target 60000、60001、65536、65537 分类必须分清：≤60000 是内建目标，60001..65536 超目标但仍在 transport hard cap 内，不因此自动 unknown，65537 为 `stdout_limit` unknown。
- `schema_v2.json`：设计 §5.5 白名单每个允许关键字正反例、禁止清单每一项拒绝例；nullable `type` arrays；required 唯一且属于 properties；additionalProperties必须显式boolean；array必须items；enum JSON-distinct（递归 object key order无关、array顺序相关、JSON类型不同不等）；深度16/17、节点256/257、properties128/129、enum64/65；参数根object+additionalProperties false；output_schema `{}` 接受；不注入default。固定实例错误先报一个，遍历次序为 required按schema数组顺序→额外属性按UTF-8 bytes→properties按UTF-8 bytes→数组索引；路径普通键用 `$.name`，其他键用 JSON-string bracket形式；规则闭集为 `type,required,additional,enum,min_length,max_length,minimum,maximum,min_items,max_items`（schema自身错误码另按设计字段表固定）。只检查 inventory/table与稳定输出，不执行 M2 validator。
- `tool_contracts.json`：每条为固定 case ID、声明式 fixture tree（文件内容用bytes hex；symlink目标、special kind、非UTF8 name以平台无关 tagged value表示）、args、expected value/error、renderer case ref、ABI design section和owner。覆盖设计 §6.1–6.3：输出path均root-relative POSIX；root内/外absolute path；词法 `..`、`.git`、dotfile策略、逐组件symlink拒绝、strict UTF-8、NUL probe。read包括空文件offset1/2、尾LF不造空行、CR保留、window外坏UTF8与window内not_utf8、line 16384/16385 bytes、file 1MiB/1MiB+1、`truncated_by` lines/bytes、cursor。list包括nonrecursive/DFS、UTF8 byte排序、file/dir/symlink size、hidden/special/nonUTF8 skip counts、total、10000/10001 entries、分页。search包括literal/每行首个match、ASCII-only fold、Unicode codepoint column、CR剥单个、glob `*`/`**`/`?`与非法 `{ } [ ] \\`、DFS顺序、context≤2、500-codepoint text、six skip counters及定义、10000 files/12s预算、complete/incomplete/offset/stateless rescan。12s wall-clock case标M3 timing gate，不冻结为确定性W1 pass；冻结文件-count budget variant。W1只核合同数据，不执行工具。

### Oracle-adjudicated decisions (2026-10-30)

Phase 1 involvement prompt timed out; the documented default was Oracle adjudicates. A first adjudication attempt failed before provider execution because the selected export path could not be resolved; after removing that stale selection, one batched adjudication completed with all three lanes. The lane rulings and evidence are reconciled below. Preference-driven calls remain assumptions; these are engineering rulings.

| Decision | Ruling | Evidence / rationale | Confidence |
|---|---|---|---|
| Q5 renderer budget/cursor | **STOP-R 已由本次静态证明解除为 resolved-design-only。** | ABI design §5.3.1 对全部 schema-valid values 定义投影，并以 §4.2 rule 3 唯一引用转义拼写；`len(J(content))=27+E(T)`、`len(J(meta))=2`。§5.6 冻结快照、枚举全部有限非空前缀，逐个计量同一 finalized value 的 value/content/meta/frame，再选最大适配 k；不依赖长度单调或 value dominance。成功不完整页必有 `k≥1` 且安全 `next_offset=offset+k>offset`，其余语义矛盾、无适配项、空集/越界、search cutoff 均有显式失败/完整空页分支。 | 本次对 ABI §5.3.1/§5.6 的静态审查确认设计可证明；向量、三方实现一致性、生产行为与 gates 均未验证，仍由后续 W1 项负责。 |
| Q1 empty/incomplete search | **Amend toward `search_scope_too_large` when scan budget expires before a page can be filled.** Complete empty searches accept offset 1; complete `total=0` rejects only offset>1. A successful incomplete page must be nonempty and advance by actual hits. | Two lanes preferred preserving B0's empty-incomplete candidate; one preferred strict error. Design §6.3 already says budget exhaustion before page fill is `search_scope_too_large`, while the incomplete `offset > total` branch can imply an empty page. The stricter rule removes that contradiction and avoids presenting a non-cursor empty incomplete result as a successful page. | Medium; revisit only if a consumer contract requires the empty incomplete affordance and distinguishes it from no-more-results. |
| v2 request-frame byte equality | Python and Node references emit the **same fixed request bytes**; response corpus is parser input and does not require canonical key order or cross-language byte equality. | Host request serialization has a single compact-sorted authority; B0's different Python/Node echo stdout is response behavior, not request behavior. Design §5.1 and B0 plan `:228-244`. | High. |
| Vector home | New independent format under `v24/s13/vectors/`; B0 format/checker unchanged. | B0 pins v1 format, case IDs and counts; design §7.1 names the s13 vectors path. | Very high. |
| Renderer digest placeholders | Compute exact provisional digests from reviewed frozen cases after the Q5 revision settles renderer templates; mark `provisional-w2-pending`. | §5.3 digest formula is data-derived and independently recomputable; do not freeze templates before the pending context/rendering revision. | High, conditional on independent Python/Node recomputation. |
| Response whitespace | Accept JSON SP/HT/CR around one JSON text before exactly one final LF; CRLF is accepted; raw multiple/non-final LF, BOM, invalid UTF-8 and trailing non-whitespace reject. | Oracle-adjudicated 2026-10-30; JSON whitespace is not canonical response bytes while single-final-LF framing remains exact. | Medium-high; overturn only with concrete ambiguity or runtime divergence evidence. |
| `max_meta_bytes` lower bound | Amend to 2..16384; absent and explicit `{}` measure 2 bytes, but the wire field stays optional. Values 0/1 reject. | Oracle-adjudicated 2026-10-30; prevents a zero/one-byte cap that cannot admit normalized empty metadata. | High. |
| B0 `descriptor_v2_rejected` | Keep unchanged as malformed pre-M2 observation; M2 adds a valid v2 descriptor acceptance/projection check and retains malformed-shape rejection. | B0 input is `{"v":2,"tool":{}}` and lacks parameters (`v24/b0/test_golden.py:139-149`); version acceptance alone cannot make it valid. | High. |

Q2 ratifies complete-item pagination and advancing by the count actually returned. Q5 refines the too-large decision: enumerate every finalized nonempty prefix first; only if none fits return the item-specific failure. Never infer failure from the first rejected prefix, because removing the final-page footer can make a longer prefix fit. Q3 ratifies standalone compact UTF-8 args bytes excluding envelope/LF and no host default injection. Q4 ratifies separate compact-byte measures for value/content/meta, treats missing meta as `{}` (2 bytes) for measurement without requiring field injection, and changes `max_meta_bytes` to 2..16384. Values 0/1 reject; cap 2 admits absent or explicit empty meta and rejects nonempty meta above two bytes. Oracle adjudicated the 2-byte lower bound on 2026-10-30. These follow B0's recorded candidate boundaries (`B0 plan:236-240`) and design §3.1/§5.2/§5.6.

**Q5 proof and sequencing (historical design-only resolution; STOP-R resolved-design-only):** ABI design §5.3.1 defines budget-specific compact bytes J, reuses only the exact string-escape spellings from §4.2 rule 3, and defines additive escaped-string payload E. Every content token contributes once to T; because escaping is scalar-additive, `E(x+y)=E(x)+E(y)`, and the fixed array/object syntax contributes 27 bytes, so `len(J(content))=27+E(T)` exactly. Renderer-produced meta is `{}` (2 bytes). §5.6 freezes scan statistics before candidate construction, enumerates all ≤2000/500/200 complete prefixes without assuming monotonicity, measures the exact finalized value/content/meta/success frame, and chooses the largest fitting prefix. All successful incomplete pages have `k≥1` and safe `next_offset=offset+k>offset`; no fitting item or inconsistent schema-valid value has an explicit failure branch. Empty success is complete/offset1/cursor=null only. Search cutoff is an input observation, not a claim that wall-clock scans repeat deterministically.

This static review accepts the proof and resolves the **design** STOP-R only; it is not W1 completion or a vector/runtime pass. This paragraph records the prior design-only decision and sequencing and remains as history. W1-5 records this resolution before any Q5-dependent W1-6 work; then freeze the §5.3.1 literals and §5.6 selector first, followed by renderer golden/independent counters, provisional digests, full descriptors/manifests, tool-budget cases, capture/check, and the existing W1 closeout sequence. Any counter/projection mismatch, uncovered schema-valid branch, unsafe cursor, or empty incomplete success reactivates STOP-R; never fix it by re-blessing expected bytes. No RPC, spill store, host cursor, new callback/field, SQL/kernel change, code or vectors are part of this design-only revision.

**Q5 adversarial vector obligations (W1-6, not executed here):**

- Exact content bytes and independently counted lengths for all three renderers, both absent/empty plugin meta, rejected nonempty plugin meta, missing vs empty context arrays, all empty outputs, single empty read line vs empty file, every footer/summary/continuation form and final-newline behavior.
- Search with two before/two after lines per hit, repeated long paths and 200 hits; vary one-item and many-item budget failures. Output path/text schemas have no maxLength: include schema-valid strings far beyond filesystem/500-codepoint conventions, plus LF/CR/NUL, all JSON escapes, astral scalars, U+2028/U+2029. Distinguish total projection/meter coverage from source-tool semantic acceptance; do not assume 1024-byte output paths.
- Value/content/meta and actual-frame byte boundary acceptance/rejection; 40960/41984/4096 and 60000/60001/65536/65537 stay separate domains. For built-in meta assert constant2; keep generic Q4 cap2 cases separate. Include byte-full pages below limit, first complete item unfit, all nonempty candidates unfit, common/empty-result overhead unfit, and a rejected shorter prefix followed by a fitting final prefix after footer removal. No monotonicity shortcut.
- Decimal-width changes (offset/end/total/next_offset/scanned/skipped sum), safe-integer edges and cursor overflow, schema-valid contradictory flags/counts/cursors/read text-line counts/file size-null relationships. Assert deterministic ordinary failures and total projection even for values rejected as semantic pages.
- Search EOF/count-full/file-count-cutoff snapshots, complete-but-truncated and incomplete nonempty pages, byte-full after observing an extra complete hit, cutoff before offset or before page fill, and complete total0 at offset1/2. Freeze stats before trying prefixes; choose maximum fitting k and assert `next_offset=offset+k>offset` on every successful incomplete page. 12s timing remains M3 evidence, not deterministic W1 capture.

The two Oracle lanes favoring Q1's empty incomplete page and one lane favoring a strict error were checked against design §6.3. The plan narrows the B0 candidate: budget exhaustion before a page fills is `search_scope_too_large`; a successful `complete=false` page must contain at least one hit and advance by the number returned. Q5 defines filled as count-full or byte-full under the finalized snapshot (ABI design §5.6); it does not permit an arbitrary partial page at cutoff. Complete empty search at offset 1 remains success. This preserves the design's explicit failure rule and avoids a successful empty result that could be mistaken for no further matches. Oracle's alternative empty-incomplete proposal was rejected for this scope because it conflicts with the existing budget-exhaustion rule.



## W1 helper and verification architecture

W1 的 reference functions 是测试资产，不作为生产逻辑，也不 import 尚不存在的 M2/M3 模块。Python 可以调用现有 `registry.pg_jsonb_text` 作 oracle producer；Node 需独立实现 PG canonical bytes；PostgreSQL 用既有 `v24.canonical_json` 参数化查询。每个 producer 都只读 vector 的固定 semantic input，输出与 `expected_hex` 对照。v2 frame reference、renderer digest、model_text join 和预算计量是独立纯变换，必须同时由 Python/Node 对固定期望 bytes 验证（如决定为跨语言同 bytes）。

W1 文件名在本计划内固定，避免文件清单与 checker inventory 不一致：

| 文件/组 | 职责 |
|---|---|
| `v24/s13/vectors/*.json` | 独立 W1 format 的 canonical、frame、renderer、descriptor/manifest/provider projection、result、schema、tool-contract vectors。 |
| `v24/s13/w1_reference.py`、`w1_reference.js` | Python/Node 独立测试参考实现：Node PG canonicalizer、domain-specific compact JSON serializers、request frame bytes、renderer digest、model_text和预算measure。不得被host import。 |
| `v24/s13/vectors/design_conformance.json` | ABI design input SHA + 每条设计章节/行→固定 suite/case ID/status/owner/first production stage映射；checker校验覆盖和输入SHA。Inventory v1 是固定审查输入，新增/删改 ID 需显式版本化复核。 |
| `v24/s13/capture_vectors.py` | repo 外、新目录、拒绝覆盖的候选 capture；不作为 gate、不提供 re-bless。 |
| `v24/s13/test_vectors.py`、`test_contracts.py` | 固定 inventory/self-consistency/三方 byte comparisons/合同覆盖检查；只读、无生产行为声称。`test_vectors.py` 自己确保 PG fixture 已加载，不依赖调用者先手动运行 setup。 |
| `v24/s13/README.md` 与 `vectors/README.md` | 范围、byte authorities、状态标签、capture/check 命令、三态、owner 和 STOP-R；不称第12条closeout。 |
| `docs/reviews/v24-tool-plugin-abi-w1-execution-2026-10-30.md` | primary/candidate provenance、哈希清单、每命令实测、capture 双跑与最终审计。 |

若 helper 使用 Python/Node 各自实现同一变换，case expected 必须固定，不能由 helper 在 checker 运行时生成。capture 的候选生成与 check 必须是分开的命令/路径；人工审核后才冻结 expected。

## Work items and execution index

人工量级沿用 B0：S < 1 人日，M 约1–2人日，L约2–3人日；不含 gates 等待。

| Work item | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| W1-0 source isolation | 固定基线与候选路径 | **完成于候选 worktree**：记录完整 HEAD/branch/upstream/status、排序源 SHA、Python/uv/Node/PG 版本；candidate=`f990b1d`；两个输入按 SHA 显式导入；没有 stash/reset | execution record、计划、外部 evidence manifest | 无 | S |
| W1-1 已裁决项落计划 | 落下 Q1–Q4、request/response framing、vector home、digest 次序决策 | **完成（设计合同）**：Oracle rulings/confidence/overturn evidence同步到ABI design与plan；Q5原STOP-R历史、resolved-design-only结论及重新激活条件保留 | ABI design、plan、execution record | W1-0 | S |
| W1-2 vector schema 与 ID inventory | 建立隔离的 W1 数据格式 | **完成**：format/version、byte/table shape、固定 required suite/case-ID set、status/owner vocabulary、design section/span/hash map、B0 兼容边界；pending 标签只描述后续生产验证 | `v24/s13/vectors/README.md`, `design_conformance.json` | W1-1 | S |
| W1-3 canonical/reference helpers | 证明generic descriptor canonical bytes三方对齐 | **完成**：9 个 canonical cases 的 Python/Node/PostgreSQL 均逐项匹配固定 bytes | `w1_reference.py/js`, canonical vectors | W1-2 | M |
| W1-4 unblocked frames/schema/non-budget contracts | 冻结不依赖 Q5 的合同 | **完成**：frame、response corpus、schema 和 result/model_text 固定向量已纳入并通过只读检查 | frame/schema/result vectors | W1-2 | M |
| W1-5 Q5 design resolution | 证明预算责任可执行 | **完成（design-only）**：ABI §5.3.1/§5.6 总投影、精确 byte counter、全前缀枚举/失败次序、安全 cursor 不变量及 adversarial obligations 已审查，状态 `design_resolved`；若后续发现反例则重新 active STOP-R。此项不生成代码/向量/gate/closeout/commit | ABI design §5.3.1/§5.6/§6、plan | W1-1（设计审查已完成；执行计划中先于 W1-6） | L |
| W1-6 Q5-dependent renderer/descriptors/manifests/tool-budget vectors | 生成依赖模板与预算的固定期望 | **完成**：renderer、provisional digests、完整 descriptors/manifests、工具合同和 Q5 exact boundary/prefix cases 均由 Python/Node 固定期望复算 | renderer/descriptor/manifest/result/tool vectors | W1-5=resolved-design-only | L |
| W1-7 capture & read-only checker | 原子纳入全套审查向量与 checker | **完成**：两次独立外部 capture 逐字节一致；10 suites/71 IDs、design span/hash、fixture关系及 Python/Node/PostgreSQL 对照通过 | capture/test helpers、vectors | W1-3,W1-4,W1-6 | M |
| W1-8 docs and execution evidence | 同步阶段收尾工件 | **完成**：s13 README、ABI design、matrix、ledger、execution record 与本计划同步；只记录真实结果 | README、设计、reviews、plan | W1-7 passed | S |
| W1-9 inherited gates & final audit | 证明无回归与范围边界 | **完成**：20 条最终串行命令全 exit 0；frozen paths 零 diff；allowlist/secret 审计通过 | execution record、matrix/ledger、git diff/status | W1-8 | L |
| W1-10 publish milestone | 发布单独里程碑 | path-only staging→status复查→commit→`git push origin main`完成，无force；STOP-R时禁止到达此项 | W1 allowlist | W1-9 | S |

## Capture, gates, and evidence

### Candidate provenance

在捕获或 gate 前记录 `git rev-parse --show-toplevel/HEAD`、branch/upstream、`git status --short`、diff paths、环境版本和排序后的源文件 SHA manifest。candidate 从已知 B0 base commit 建立，不能以 primary 的脏工作树直接声称干净基线。ABI design 与 W1 plan 在输入树中按 SHA 显式纳入；若 SHA 与登记的输入不一致，先停止核实来源。不得 stash/reset、不得把其他 modified/untracked 路径带入 W1 白名单。

### Capture and checker

1. Capture 两次，目标是不同的、尚不存在的 repo 外目录；比较全目录 raw bytes。任何差异为 STOP-N，禁止重序列化、删 case 或自动更新 expected 消差。每次重试使用新的唯一目录并保留失败目录与日志，不清理旧 evidence。
2. 人工复核 fixed input、expected text/hex、SHA、case inventory、provisional/owner 标签及 design-to-case mapping 后，将 vectors 与只读 checker 原子加入 candidate。每组 vector 标 ABI 设计 §/行号、case IDs、status、first production verification stage；checker 对 design input SHA 和映射表做一致性检查，变更设计 SHA 时要求逐组 review，不允许静默 green。
3. Checker 校验 format/domain、ID exact set、重复 ID、hex/length/SHA 自洽、UTF-8 expected_text、状态值域、跨文件引用和覆盖完整性；失败只输出 case ID、首个 byte diff offset、length/SHA，不打印完整 payload。
4. Python、Node、PG canonical cases 都直接与 `expected_hex` 比。PG checker 使用与 B0 同样的只读 fixture setup：创建/加载专用数据库使 `v24.canonical_json` 存在，参数化执行 `SELECT v24.canonical_json(%s::jsonb)`，读回 bytes 后 rollback/关闭连接。全部 PG query 完成并关闭/rollback 连接后才启动 Node 子进程；任何时间都不在打开的 DB transaction 中执行外部 IO。可复用 `v24/b0/test_golden.py:153-168` 与 `golden_cases.py:44-51,256-269`。
5. Node 子进程固定 argv/timeout，捕获 stdout/stderr，拒绝未知/重复/缺失 case IDs；无 Node 是 exit2/SKIP，不算通过。compact JSON reference 必须定义：对象 key 的 UTF-8 byte order（length then unsigned lexicographic 或每个 domain 明确采用其 authority）、arrays preserve order、UTF-8 raw non-ASCII、exact escape policy、safe integer-only 数值、float/exponent/-0/NaN/Infinity 处理、duplicate-key 词法入口。PG canonical JSON 另按 `pg_jsonb_text`，不可与 compact domain 合并。
6. W1 checker只验证 vectors 和数据合同完整性；不会调用生产 descriptor/schema validator、renderer、dispatcher或实际 read/list/search。

### W1 gates

Q5 exact-counter 修订已由静态 review 接受，STOP-R 状态为 `design_resolved`，不是 W1 pass。候选执行已完成 W1-0 至 W1-9，W1-10 发布待完成。此前版本中“本次范围仅两份设计/计划文档”的描述保留为历史，不限制本次获授权的 W1 执行。最终 serial run、冻结路径审计、allowlist 与 secret audit 的实际结果见 execution record。W1-10 发布须遵循本计划与仓库提交约定；若出现无法安全解决的远端分歧，停止发布并向用户说明。

下面脚本是 W1 规划的独立 gate 名称；具体命令在实现文件命名冻结后保持一致。所有带 provider 可能性的 gate 清除凭据，禁止网络 socket；DB 类测试串行执行：

```bash
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_contracts.py
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_vectors.py
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_vectors.py --node

env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/b0/test_golden.py
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/b0/test_golden.py --node
```

Capture commands are candidate-generation steps, not gates. Each retry selects two new unique repo-external paths; preserve old candidate directories and logs rather than deleting them to satisfy the absent-destination guard:

```bash
uv run python v24/s13/capture_vectors.py --output <fresh-outside-repo-dir-A>
uv run python v24/s13/capture_vectors.py --output <fresh-outside-repo-dir-B>
diff -rq <fresh-outside-repo-dir-A> <fresh-outside-repo-dir-B>
```

After W1 and B0 vectors, rerun the inherited closeout commands serially in this order (matrix `:108-133`):

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

Then run independent extension checks (G9/G10/etc. do not change closeout count):

```bash
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s10/test_g9.py
uv run python v24/s11/test_g10.py
uv run python v24/s11/test_node.py --node
uv run python -m v24.host.plugin_smoke --multilingual-smoke
```

For all gate commands, use the credential-cleared prefix where applicable. Record per command: ISO timestamp with timezone, source SHA, candidate fingerprint, exact command, exit, actual last line, merged-log SHA-256, status and note. Logs stay outside repo. Status rules: exit0 plus command-specific pass marker = passed; exit2/SKIP = unverified, blocks W1 completion; exit1/traceback/missing marker/abnormal exit = failed. Never substitute historical B0 pass evidence for this candidate's rerun. B0 multi-provides probe is already proven and is not repeated unless the frozen inputs or SQL contract change.

## File-by-file impact

### New W1 allowlist

- `v24/s13/vectors/README.md`: format, status vocabulary, byte authorities, design-to-case conformance map and pending owners.
- `v24/s13/vectors/descriptor_v2.json`: canonical cases, full descriptors, closed-set and cross-field validation case table.
- `v24/s13/vectors/frames_v2.json`: v2 request bytes and language-independent response classification corpus.
- `v24/s13/vectors/manifest_adapter_v2.json`: adapter declaration and one-Node-install/two-provides manifest bytes/digests; artifact digest remains M3-pending.
- `v24/s13/vectors/provider_projection_v2.json`: read/list/search projection expected bytes, safe-name mapping cases, key mismatch and v1-byte-stability expectations.
- `v24/s13/vectors/renderers.json`: three renderer golden case arrays, fixed case shapes/order, canonical digest input and provisional digests.
- `v24/s13/vectors/results_v2.json`: envelope, model_text, usage, budget (including 60000/60001/65536/65537), and replay contract cases.
- `v24/s13/vectors/schema_v2.json`: schema keyword/instance/boundary cases, deterministic error path/rule ordering and enum equality rules.
- `v24/s13/vectors/tool_contracts.json`: read/list/search fixture trees and expected contract tables, with symlink/special/non-UTF8 nodes represented explicitly and deterministically.
- `v24/s13/vectors/design_conformance.json`: reviewed ABI design input SHA and section/line-to-case-ID/status/first-production-stage mapping; the checker verifies coverage and rejects a stale design SHA.
- `v24/s13/README.md`: scope, commands, three-state results, extension-check status, M2/M3 ownership and STOP-R behavior.
- `v24/s13/w1_reference.py`, `w1_reference.js`: independent test helpers only.
- `v24/s13/capture_vectors.py`: guarded external candidate capture only.
- `v24/s13/test_vectors.py`, `test_contracts.py`: read-only checker(s), no re-bless.
- `docs/reviews/v24-tool-plugin-abi-w1-execution-2026-10-30.md`: actual source/candidate provenance and command evidence; never prefill passing results.

### Updated closeout documents

- `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md`: ratify/amend Q1–Q5 and the adjudicated frame policy; define budget domains, provisional renderer digest source, precise edge cases. Do not label production behavior verified.
- `docs/plans/v24-tool-plugin-abi-w1-cross-language-vectors-2026-10-30.md`: this plan and a Result only after gates run.
- `v24/s13/README.md`: actual command and status result, extension-check label, M2/M3 ownership.
- `docs/reviews/v24-conformance-matrix-2026-10-23.md`: append W1 post-closeout evidence; maintain closeout 11/11.
- `docs/reviews/v24-deviation-ledger-2026-10-23.md`: append ABI W1-specific deviations/assumptions separately from the existing S-series “W1 document alignment” entry.
- `v24/b0/README.md` may receive a narrow note that `structure.descriptor_v2_rejected` is pre-M2 observation and malformed input; do not modify `v24/b0/**` checker/golden. If exact path scoping cannot preserve existing parallel edits, record the handoff in W1 docs and leave B0 README untouched.

### Explicitly unchanged

`v24/host/**`, `v24/sql/**`, `v24/s10/**`, `v24/s11/**`, `v24/load.py`, B0 vectors/checker/probe, and all M2/M3/M4 runtime files. No new SQL, effect kind, journal event, claim/queue/recovery path, database table, provider/network socket, production tool or host callback.

## Risks, STOP conditions, and rollback

| Stop | Trigger and action |
|---|---|
| STOP-R | 当前由本次静态审查确认 ABI §5.3.1/§5.6 可证明，状态 resolved-design-only；必须证明 exact content/meta 计量、有限全部前缀枚举、显式失败和安全 cursor 推进。不得引入 RPC/spill/host cursor/new callback/field/SQL/kernel 改动。发现具体反例、计量偏差、未覆盖 schema-valid 分支或不安全 cursor 时立即重新 active。Active 时 W1-6及之后 blocked/not_run，禁止 capture/promote/closeout/publish；resolved-design-only 不代表任何向量或 gate 已通过；本 work item 的 vectors/gates 仍 pending/not_run。 |
| STOP-D | Python, Node or PG bytes differ from fixed expectations; preserve actual bytes, case ID and source hashes; do not auto-rebless. |
| STOP-N | Independent captures differ or vectors contain random/time/path/credential data; locate nondeterminism before freezing. |
| STOP-V | Inventory, domain, references or schema/tool coverage incomplete; fix source vectors and repeat review/capture. |
| STOP-W | Candidate provenance unclear, frozen path changed, or unrelated work staged; stop, preserve dirty state and re-isolate; never stash/reset. |
| STOP-G | Any W1/inherited gate fails or lacks its required pass marker; later commands `not_run`; milestone incomplete. |
| STOP-E | Node or PostgreSQL unavailable / exit2; mark unverified, restore toolchain and rerun in same candidate. |
| STOP-B | B0 fixed v1 vectors or structural baseline changes; W1 cannot alter them to hide regression. |
| STOP-S | A contract implies SQL/kernel change (new table, effect kind, replay policy, settlement-time argument validation); return to design/kernel review. |

W1 adds no persisted data or production API, so no data migration is needed. Before commit, uncommitted rollback is limited to W1 allowlist paths; after commit use a new revert commit. Preserve failure evidence and never rewrite history.

## Current execution result (2026-10-30 candidate)

W1-0 through W1-9 are complete in the isolated candidate; W1-10 publication remains pending. Two fresh external captures matched byte-for-byte; the read-only checker validates 10 suites/71 IDs and exact design-section hashes; Python, Node, and PostgreSQL matched all nine descriptor canonical cases. The final W1/B0/inherited gate results, source fingerprint, per-command timestamps, log hashes, frozen-path audit, and secret audit are recorded in `docs/reviews/v24-tool-plugin-abi-w1-execution-2026-10-30.md`. Production behavior remains owned by M2/M3/M4; renderer digests remain provisional W2-pending, artifact digest/timing remain M3-pending, and replay remains M4-pending. Closeout count remains 11/11.

## Commit and push prerequisites

Repository `AGENTS.md` requires all tests green, closeout artifacts updated, explicit path-by-path staging, status review, one W1 commit, then push. Never use `git add -A`, `git add .`, `--no-verify`, force push, or reset to resolve divergence. Stage only the W1 allowlist. The candidate is isolated from the dirty primary checkout; publication must not alter unrelated primary work. If the remote cannot accept a safe append-only publication from this candidate, stop and report the exact divergence rather than force or rewrite history. No gate may be reported green without a real run.

## References

- ABI design authority: `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md` §§2–10, especially §3–6, §7.1/7.3/7.4/7.5, §9–10 and Appendix A.
- B0 plan: `docs/plans/v24-tool-plugin-abi-b0-baseline-2026-10-30.md` §§3–10, especially `:136-141` (completed multi-provides probe), `:195-244` (vectors and boundary candidates), `:236-240` (Q1–Q5 ownership), `:321-327` (stop conditions), and `:330-350` (execution and publish order).
- B0 execution evidence: `docs/reviews/v24-tool-plugin-abi-b0-execution-2026-10-30.md`.
- B0 golden assets: `v24/b0/golden_cases.py`, `capture_golden.py`, `test_golden.py`, `golden/*.json`.
- Host seams: `v24/host/registry.py:108-145`, `line_json.py:71-149`, `deepseek.py:341-392`, `journal.py:26-73`, `plugins.py:56-83`, `worker.py:86,919-979,1027-1077,1190-1308`, `process_io.py:18-77`.
- PostgreSQL canonical: `v24/sql/30_advance.sql:4-6,19-37,175-180`.
- Fixture/provider harness: `v24/s11/plugin_fixtures.py:89-116,197-214`; Node echo `v24/s11/plugins/echo.js:11-14`.
- Gates: `docs/reviews/v24-conformance-matrix-2026-10-23.md:108-133,163-289,619-623`; `v24/s10/README.md`; `v24/s11/README.md`.
- Repository contract: `AGENTS.md:1-79`.
