# v24 Tool/Plugin ABI W5：Python `read` 收口 Deep Plan

日期：2026-10-31。状态：W5 Python `read` 收口实测完成（见 Result；提交/推送回执另报）。基线：`main` @ `5771ce3`（W4c 已提交）。本计划是 design §10 M3 的 `read` 侧收口子阶段，**不是 M3 完成**：search 的 12 秒 timing/cutoff 仍 pending，见「W5 不证明什么」。

**Assumption（scope；Oracle-adjudicated）**：W5 是 `read` 的合规与证据收口，不是从零实现，也不承担 M3 的 search timing/cutoff、Linux real 或 M5 文档修订。该口径是委托裁决下的保守默认；若你要的是重写 `read` 或把 M3 剩余项并入 W5，需要另立计划。

## 范围口径：W5 为什么是「收口」而不是「实现」

最初的阶段表把 W4 定义为「运行时接线」、W5 定义为「Python read」、W6 定义为「Node list/search」。实际执行时 W4 被拆成 W4a/W4b/W4c：W4b 已经交付了 `fs_read.py`、`fs_tools.js`、`fixtures.py`、`test_tools.py`，W4c 交付了生命周期与 Node 证据（design 附录 C.11、`docs/reviews/v24-tool-plugin-abi-w4b-execution-2026-10-31.md`、`...-w4c-execution-2026-10-31.md`）。因此 `read` 的功能面已经存在，16 条冻结合同用例已绿；W5 不应重写一遍。

W5 的真实内容是：把 W4b 的实现推进到 design §6.1/§6.2/§5.3.1/§5.6 的合规边界（两处规范内部冲突按台账口径处理，见 D6/D7），修掉四处**在合法输入上可复现**的缺陷，补齐 read 侧从未断言的错误码与边界，并留下可复核的执行记录。这个口径同时解释了为什么本阶段仍然只动一个生产文件：`v24/s13/plugins/fs_read.py`。

## Goal 与范围

**In scope**

1. **修复四处实测缺陷**：合法 1 MiB 输入超过 host 5 s deadline、内存随行数 O(lines)、content 计量漏算续页 footer、空文件绕过四预算。
2. **合规**：`read` 满足 §5.3.1 的可加性计量、§5.6 的有限候选算法与失败次序、§6.1 的路径规则、§6.2 的 read 语义；两处已记录的规范内部冲突（解码窗口措辞、空页 `output_too_large` 与十四码闭集）按台账口径执行，不声称「逐句合规」。
3. **补齐证据**：覆盖 §6.2 十四码中从未断言的五个 code、§5.6 第 6 步的空页 `output_too_large`、以及十余条路径/分页/预算边界。
4. **留下审计记录**：`docs/reviews/v24-tool-plugin-abi-w5-execution-2026-10-31.md`，含 source/artifact digest、32 行串行表、七项 scope audit。

**Out of scope（不得顺手做）**

- `list`/`search` 行为，`fs_tools.js` 零 diff；
- search 的 12 秒扫描预算，`tool.search_budget_timing_m3_pending` 保持 `m3_pending`；
- Linux real 非 UTF-8 文件名证据，`linux_real=not_run` 不变；
- design §7.5 第 1–3 项文档修订（`v24-pg-agent` §5.1/§5.4、`v24-drift-factcheck` D2–D4），属 M5；
- 任何 `v24/host/**`、`v24/sql/**`、kernel/replay 改动、冻结向量改动、design 正文改动。

## Done when

1. `read` 对 1,047,999 B（2000 行 × 523 个 `\x01`）的合法文件经 host 路径 `line_json.run(entry, "invoke", …, tool="read")` 运行，在 descriptor 的 5000 ms deadline 内返回 `success`，不再是 unknown `timeout`；`wall_ms` 写入 evidence 行。
2. 1 MiB 全 `\n` 文件（1,048,576 行）与上述宽行文件的进程内 `tracemalloc` 峰值均 < 8 MiB，且前者 `total_lines == 1048576`、`final_newline == true`。
3. 每个非空候选 k 与空文件候选的 value/content/meta/frame 四域计量，逐字节等于 `w1_reference.budget_measures` 与 `tool_results.measure`；覆盖 footer、`[empty file]`、`null` 与数字位数边界（9/10/99/100/1000）。
4. 空文件分支在 `offset` 检查之后执行四预算检查；注入窄 cap 时返回 `output_too_large`，内建 cap 下冻结 `empty_offset1` 的结果逐字节不变。
5. 冻结的 16 条 read 用例结果逐字节不变；`test_contracts.py`、`test_vectors.py`、`test_vectors.py --node` 全绿且零 diff。
6. `test_tools.py` 新增 29 条 read probe（W5-R01…R29），实现后**期望**末行为：
   ```text
   [passed] W4 fs tools; cases=103; read=16; read_probes=29; list=7; search=24; pagination_converged=true; page_contracts_imported=3
   ```
   这是计划编写时的验收目标；本轮已达成，见 Result。实际 inventory 若不同，先改本计划再跑 sweep。
7. 32 条串行命令全部 exit 0；第 1–31 条末行为命令专属 `[passed]`，第 32 条 exit 0 且输出为空；七项 scope audit（六项钉 `c8c4bd0` + 一项 candidate-only 钉 `5771ce3`）全过，并在 W5-6 写完文档后、staging 前重跑；无 exit 2/`[SKIP]`。
8. `manifest.artifact_digest_pending` 与 `manifest.five_field_key` 的 `status`、`expected` 零改动；实测的 `fs_read.py` sha256 写入执行记录与 evidence 行。
9. `v24/s13/README.md`、matrix、ledger、执行记录四处收尾工件与实测一致；closeout 仍 **11/11**，s13 仍是 extension evidence，不是第 12 条 closeout。
10. 按路径逐项 `git add`、正常 hook、单个 W5 提交并 `git push origin main`；不含任何未跟踪临时文件。

## Current-state analysis（计划编写时的基线分析；先前观测）

本节保留 W5 实施前的分析与旧源码行号。四缺陷表中的 6.742 s/123.9 MiB 是先前观测，不是本轮红基线或最终 sweep 的测量值；本轮实测与边界见 Result 及执行记录。

### 调用链与所有权（W5 只动最内层）

```text
model {key:"read", args}
  → plugins._tool_v2 步 1–7（match_tool / args 大小 / parameters_check / require_artifact / workspace / lease / spawn）
  → line_json._spec_v2：invoke 的 timeout_ms = approved.timeout_ms（read = 5000）
  → process_io.run_process：deadline = started + timeout_ms/1000，超时 SIGKILL 进程组并 reap
  → fs_read.main → read_tool → _resolve → _read_bytes → _read_page → _ok({"value": V})
  → line_json._classify_v2 → plugins 步 10–13（value 大小 → output_check → assert_builtin_meta → validate_page → render → content/meta 预算）
  → worker model_text
```

依据：`v24/host/plugins.py` 的 `_tool_v2` 十三步；`v24/host/line_json.py:250-264`（per-tool timeout）、`:267-298`（`timed_out` → `_unknown("timeout")`）；`v24/host/process_io.py:19-22`（stdin 1 MiB / stdout 64 KiB / stderr 16 KiB）、`:89+`（deadline/kill/reap）；`docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:1287-1395`（C.13/C.16）。

推断：W5 的修复面完全在插件进程内。host 对插件不信任，会独立重算与重渲染（`plugins.py` 步 10–12、`tool_pages.validate_page`），所以插件改动不改变任何 host 合同面。

### 四处已实测缺陷（基线 `5771ce3`）

| # | 缺陷 | 位置 | 规范 | 实测 |
|---|---|---|---|---|
| 1 | 每个候选 k 重新 `"\n".join` 增长文本，再做 3 次 JSON 序列化（`_escaped_len`、`_json_len`×2），整体 O(k²·bytes) | `fs_read.py:229-250`、`:170-180` | §5.3.1 可加性 `E(x+y)=E(x)+E(y)`，「不必创建 T」`design:688-703` | 1,047,999 B 宽行文件 `read_tool` 耗时 **6.742 s** > 5000 ms → host 判 unknown `timeout` |
| 2 | `handle.read(MAX_FILE_BYTES+1)` 整文件物化；`_line_ranges` 为每行建 `(start,end)` 元组 | `fs_read.py:145`、`:157-168` | §6.2「`total_lines` 用字节扫描计数，不把整个文件读进内存」`design:823` | 1 MiB 全 `\n`（1,048,576 行）时 `ranges` 占 **123.9 MiB**（约 124×） |
| 3 | `content_len = 27 + _escaped_len(text)`，漏算续页 footer | `fs_read.py:245` | §5.3.1 计数含续页标记 `design:702`；§6.2 定义 footer `design:825` | `many` 页 host `J(content)` = 86 B，插件算 31 B，**少 55 B** |
| 4 | 空文件直接返回 `_empty_value`，未做任何预算检查 | `fs_read.py:209-212`、`:192-204` | §5.6 第 6 步「照样检查四预算，不适配为 `output_too_large`」`design:778` | 插件内 `output_too_large` / `invalid_tool_output` 无任何路径 |

复现方式（不写入仓库）：把插件按 `importlib` 载入进程内，对 `MAX_FILE_BYTES` 以内的合成文件调用 `read_tool`；缺陷 3 用 `RENDERERS.by_id("v24.fs.read.text", 1).fn(args, value)` 与 `27 + E(text)` 对比；缺陷 2 用 `tracemalloc` 包住 `_line_ranges`。

### 缺陷 3 为何至今未暴露

- 内建 cap 是 value 40960 < content 41984；read 的 value 骨架（path + 8 个字段）本身约 120–170 B，所以对任何 k，`len(J(value))` 都大于 `len(J(content))`。content 预算**永不先于** value 绑定。
- 因此缺陷 3 是 latent deviation：真实 fixture 不能触发选择差异，只能靠差分与注入 `MAX_CONTENT_BYTES` 证明。
- 推论：修正后 16 条冻结用例选中的 k 不变。`test_contracts.py:104-118` 已用含 footer 的真实 render 证明这些冻结 value 的 content ≤ 41984，而 value 计量本身不变。

### 冻结向量是字节权威（不改行为，只记台账）

**解码窗口。** 实现与冻结向量一致，规范措辞冲突只记台账：

- §5.6 第 1 步写「read 试算某前缀时只解码该前缀」`design:773`；§6.2 写「选中窗口严格 UTF-8 解码」`design:824`。
- 冻结用例 `window_bad_utf8`（`b"a\n\xff\n"`，默认 limit）期望 `not_utf8`（`v24/s13/vectors/tool_contracts.json:199-220`）。
- 现实现按 `offset..offset+limit-1` 逐行解码（`fs_read.py:216-228`），且源码注释 `:216-219` 已选择该解释。

**path 长度单位。** 两处都 fail closed，不改：§6.1 按 UTF-8 bytes（`design:793`），schema `maxLength` 按 Unicode scalar（`design:740`）；插件按 bytes 检查（`fs_read.py:78-86`）。

**无 re-bless 路径。** `v24/s13/vectors/README.md` 规定 checker 无 re-bless 路径、增删改 case 需 design/plan 更新与显式审查；`test_contracts.py:71` 断言每个 case `status != 'passed'`；`design_conformance.json` 的 status 词表里没有「verified」一类值。**结论：冻结向量无法在本阶段「提升为通过」**，任何 promotion 都要先改 checker 不变量与词表，属于另一个阶段。

### artifact digest：机制已存在，缺的是证据

- `v24/host/registry.py:60-84` 的 `require_artifact()` 在 spawn 前比较 `sha256(argv[1])` 与 declared digest（`:81-83`），不符即 `artifact_digest_mismatch`。
- `v24/s13/fixtures.py:322-330` 的 `build_spec` 复制插件并在构建时现算 sha256，`V2Spec.artifact_digest` 取该值。
- 推断：每次编辑 `fs_read.py`，fixture 自动重算 digest，不存在需手工同步的旧 sha；唯一风险是某处硬编码了旧值，由 W5-0 的 `grep` 排除。
- `manifest.artifact_digest_pending`（`v24/s13/vectors/manifest_adapter_v2.json:605-623`）的 `expected.digest="M3-pending"` 是 W1 时代的陈述（当时生产插件文件不存在），现在文件已存在；但该 case 的 status 受上面的 no-re-bless 规则保护。

### 未断言的 read 合同面

已断言：

| 来源 | 覆盖 |
|---|---|
| 冻结 16 例 | `offset_out_of_range`（仅空文件）、`not_utf8`、`line_too_long`（仅 16385 B 单行）、`file_too_large` |
| `path_differential`（`test_tools.py:270-286`） | `path_escape`（`../escape`）、`path_excluded`（`.git/config`）、`not_found`、`invalid_path`（NUL）、`symlink_denied`（末组件 `link`） |

未断言：

- §6.2 十四码中的五码：`binary_file`、`not_a_file`、`permission_denied`、`io_error`、`root_unavailable`。
- §5.6 第 6 步的空页 `output_too_large`（与上五码合计为「六项」）。
- 边界：8192 B 之后的 NUL、绝对路径在 root 内/外、symlink 作为中间组件、`./a//b` 折叠、空 path、>1024 B path、多字节 path、非空文件 `offset>total_lines`、请求窗口内后续超长行、lines/bytes 同时绑定、无适配前缀的 `line_too_long`、dotfile 可读、success 不发送 `meta`。
- `test_contracts.py:114-115` 跳过的 7 个 id 对 read 是死代码；其中 `dotdot`/`dotgit`/`nul` 已由 `path_differential` 覆盖，W5 不重复计数。

### 可复用件

| 件 | 用途 |
|---|---|
| `fs_read.select_prefix(lengths, cap)`（`:183-189`） | 无早停枚举器；被 `test_tools.py:187-211` 的 `selector_probe` 依赖。保留签名与语义 |
| `w1_reference.budget_measures` / `escaped_payload_bytes` / `render_count` | 独立 oracle；footer 已含在内（`w1_reference.py:188-232`） |
| `tool_results.measure` / `frame_bytes` | host 侧四域计量（`tool_results.py:243-260`） |
| `tool_pages._check_read` | host 页关系检查，插件 value 必须满足（`tool_pages.py:107-140`） |
| `fixtures.materialize_nodes` | 生成 file/symlink/special 测试树 |
| `invoke` / `expect_error` / `expect_value` / `check_value` / `run_harness_case` | 子进程与 DB 调用（`test_tools.py:143-192`、`:240-267`） |

## 决策记录

D1–D14 已在 2026-10-31 完成裁决（见「Oracle 裁决记录」）；正文保留「推荐」措辞作为决策依据，执行按裁决结果。若后续证据推翻 D6 的错误归属，先停，不自行选择另一套行为。

### D1 — `manifest.artifact_digest_pending` 保持冻结

**推荐**：不改任何向量。新增 W5-R28：断言 `sha256(plugins/fs_read.py) == read_spec.artifact_digest == read_spec.entry.artifact_digest`，`entry.require_artifact()` 通过，打印 `[evidence] read_artifact_sha256=<hex>`，执行记录写入同一 hex。

**理由**：机制已在 `registry.py:81-83` 实现，缺的是证据；`test_contracts.py:71` 禁止 `status='passed'`，词表也没有「verified」，promotion 需要先改 checker 不变量（另一个阶段）；W3 D15 已有「执行 pending case、不改 status」的先例（`docs/plans/v24-tool-plugin-abi-w3-registry-transport-2026-10-31.md:262-270`）。**拒绝**：把 status 改成任何非 pending 值。

### D2 — 两遍式、单 fd、分块扫描

**推荐**（选项 a）：

- **pass 1**：64 KiB 分块计 LF，同时只记录请求窗口需要的 LF 位置（≤ `limit+1` 个整数）。
- **pass 2**：`os.pread` 只读窗口字节（连续区间，≤ 1 MiB）。
- **变更检测**：pass 前、pass 间、window 读后各一次 `fstat`，比较 `(st_dev, st_ino, st_size, st_mtime_ns, st_ctime_ns)`，并要求「扫描字节数 == st_size」「window 短读即失败」。不符返回 `io_error`。

**理由**：只有 (a) 使堆占用与行数无关；§6.2 明文禁止为 `total_lines` 整读文件。选项 (b) 单遍保留窗口仍需全文件扫 LF，且不分块时仍持有 1 MiB 缓冲加逐行元组，无法通过 R25 的判别性用例（全 `\n` 文件）。`file_too_large` 保留两处检测：`st_size` 预检 + pass 1 字节数超限（防增长）。

### D3 — deadline 回归守护分三层

**推荐**：

1. **主断言（确定性）**：R27 只在 `read_tool` 范围内包装 `json.dumps`（不包 `main`/`_emit`，最终帧合法包含正文），断言每候选序列化出的 value/frame skeleton 的 `text` 字段为空、每次 payload ≤ `4096 + E(path)` 字节（path 含控制字符时按转义后长度计），调用次数 ≤ `2*limit + 8`。这直接排除「对增长文本重复序列化」。
2. **合同断言**：R26 走 DB-backed `PluginHarness` → `line_json.run(...)`，施加真实的 5000 ms deadline，要求 `success`；这是缺陷 1 后果的直接证明。
3. **辅证**：同一次调用记录 `wall_ms` 并打印 evidence；**不**把 2 s 墙钟做成硬 gate（C.16 拒绝墙钟 gate，慢 CI 会误杀）。

**理由**：计数与 CI 速度无关；真实 harness 是唯一能证明「不再 unknown」的方式；禁止 `sleep()`。

### D4 — 并入 `test_tools.py`；marker 区分冻结与新增

**推荐**：不新建 `test_read.py`；在 `test_tools.py` 增加 `read_probes(base)` 段，marker 增加 `read_probes=29` 字段，`read=16` 继续表示冻结向量数。

**理由**：design §7.1/§7.3 已把 read 工具合同与 `test_tools.py` 绑定；新文件要改 design 文件清单、`DESIGN_SHA256` 与 `design_conformance.json`，代价与收益不成比例。保留 `read=16` 的语义可以防止把 29 条探针误读成 45 条冻结合同用例。

### D5 — 可加、含 footer 的精确计量

**推荐**：替换 `fs_read.py:245`；所有量由窗口行字节算出，不构造 T。

逐行转义长度（行内不含 LF）：

```text
E_line(b) = len(b)
          + #{0x22,0x5C,0x08,0x0C,0x0D,0x09 ∈ b}·1
          + #{其余 0x00–0x1F ∈ b}·5
E_text(k) = Σ_{i≤k} E_line(line_i) + 2·(k−1)          # 每个行间 "\n" 转义为 2 B
footer(k) = "\n\n[Showing lines S-E of T. Use offset=N to continue.]"
content(k) = 27 + E_text(k) + (E(footer) if truncated else 0)
```

- `27 = len(J([{"text":"","type":"text"}]))`；空文件 `content = 27 + E("[empty file]") = 39`。
- value：对每个候选构造 `text=""` 的 value skeleton（其余字段全填），序列化一次取固定长度，再加 `E_text(k)`；**不再**对含正文的 value 做序列化。
- frame：`len(J({"ok":true,"v":2,"result":{"value":<skeleton>}})) + 1`，同样加 `E_text(k)`；等价于 `value_len + 38`，但用 skeleton 现算可避免硬编码。
- meta：恒为 2（插件不发 meta）。
- skeleton 必须已经包含该候选最终的 `end_line`/`truncated`/`truncated_by`/`next_offset`；footer 的长度用 `escaped_bytes_len` 现算，不要为每个候选再 dump 一次 footer。
- 常量不靠手写字面量：`27`、footer 固定部分、`[empty file]` 都在 import 时由同一 `escaped_bytes_len` 从字面 token 算出。

**拒绝**：保留 `27+E(text)` 再补一次全量序列化自检（重新引入 O(k·bytes)）；也拒绝「数字位数手算」方案，因为它复刻 `json.dumps` 的整数格式，脆弱且难审查——skeleton 现算同样精确且更直观。

### D6 — 空页四预算；`output_too_large` 由插件发，`invalid_tool_output` 只由 host 发

**推荐**：

- 判定次序固定为 `offset` 校验 → 空页计量 → 预算失败或成功；空文件 `offset>1` 在任何注入 cap 下仍是 `offset_out_of_range`。空页 value skeleton、`content=27+12`、`meta=2`、frame skeleton 任一超限返回 `output_too_large`。
- 台账同时记录 §5.2 的映射表把 `output_too_large` 列为 host code，以及 §6.2 的十四码表未收录它；这两处共同构成冲突证据。后续若新增「插件错误码必须是十四码子集」的检查，必须显式放行 `output_too_large`。
- **不改 design、不 repin**。在 deviation ledger 记 `D-ABI-W5-4`：§5.6:778 指定的 `output_too_large` 不在 §6.2 的十四码闭集内，这是规范内部不一致；插件按 §5.6 的分页算法执行，`invalid_tool_output` 仍是 host 第 10 步职责。
- 该分支在内建 cap 下不可达（空 value 约 120–150 B，path ≤1024 B，最坏约 6.3 KB），因此只能用注入 cap 的 R22 证明。

**理由**：改 design 要追加附录并原子 repin `DESIGN_SHA256` + `design_conformance.json`，为一个不可达分支引入 pin churn 与额外审查面；台账已能记录「哪一条规范胜出」。若后续有经审查的要求改 design，则本计划追加一个 append-only C.18 工作项（design + 两处 pin），插件行为不变。

**注意**：host 不按 descriptor 的错误码闭集校验 exit-3 帧（`line_json.py:240-247` 只检查键集，`plugins.py:188` 直接取 `code`），所以 `output_too_large` 作为 known error 可被 host 原样传递，不会变成 unknown。

### D7 — 解码窗口保持冻结向量的语义

**推荐**：先严格解码完整请求窗口 `offset..offset+limit-1`（逐行：先查 16384 B 上限，再 strict decode），再选择预算适配的 prefix；窗口内后续行的错误使整页失败。台账记 `D-ABI-W5-5`（§5.6:773 的措辞冲突）。

**理由**：冻结 `window_bad_utf8` 要求 `not_utf8`，即使更短 prefix 可能适配；W3 已确立冻结向量为字节权威。改行为会让 16 条冻结用例之一变红，属 STOP。

### D8 — path 长度单位不改

**推荐**：保留 1024 UTF-8 bytes 上限；R15 用 513 个 `é`（1026 B / 513 scalar）证明插件 fail closed，而 host schema 会放行，作为单位冲突的证据。台账记 `D-ABI-W5-6`。

### D9 — 新 fixture 走 test-only 内联树

**推荐**：`fixtures.py` 新增 `read_workspace(root) -> Workspace`，复用 `_prepare_root` + `materialize_nodes` 生成独立树；不写 `vectors/*`，不改 `read_spec` 签名。

**理由**：`vectors/README.md` 禁止无审查增删 case id；内联树让 29 条探针自包含，不污染 portable 树。

### D10 — 非法 `offset`/`limit` 仍返回 `invalid_path`

**推荐**：保留现状。host 的 `parameters_check` 已在 spawn 前拒绝（`design` C.13 第 3 步），插件内检查不可达；§6.2 十四码没有更贴切的码。台账记 `D-ABI-W5-7`，不新增 code。

### D11 — 打开加固

**推荐**：在 `S_ISREG` 判定之后，用 `os.open(path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK)` 打开，`fstat` 与 `lstat` 比对 `(st_dev, st_ino)`；regular file 上 `O_NONBLOCK` 是 no-op，无需额外清理。

- `ELOOP` → `symlink_denied`；`EACCES` → `permission_denied`；`ENOENT` → `not_found`；其他 `OSError` → `io_error`；identity 不符 → `io_error`。

**理由**：现有 lstat→`S_ISREG`→open 已避免 FIFO 阻塞；`O_NONBLOCK` 再挡 lstat 与 open 之间被换成 FIFO 的情况，使其不会阻塞到 deadline；`O_NOFOLLOW` 关闭末组件被换成 symlink 的窗口。design 风险 #5 视 workspace 为受信，本项只是同成本加固，不扩大合同。

### D12 — 不改 design、不 repin

**推荐**：`DESIGN_SHA256` 与 `design_conformance.json` 零 diff；所有歧义以 ledger 记录。依赖 D6 的裁定；若 D6 后续被推翻为「改 design」，本条作废并按该 append-only 工作项执行。

### D13 — 拒绝「emit 后帧长自检」

已排除：host 已独立重算；计数漂移由 R23 差分在 CI 捕获；运行时自检会把一个合法页降级成错误。

### D14 — 权限探针的 root 处理

**推荐**：`os.geteuid() == 0` 时不做 chmod 真实探针，改用进程内 `mock.patch("os.open", side_effect=PermissionError)` 验证 `permission_denied` 映射，并打印 `[evidence] permission_probe=mock_root`；非 root 时走真实子进程 + `chmod 000`（`finally` 恢复）。**任何情况都不把整个 gate 变成 SKIP。**

**理由**：「root 时整 gate `[SKIP]` exit 2」会把一次可用的 32 条 sweep 变成未验证；三态规则允许 SKIP 单条 probe，不允许拿它当通过，但没必要因此牺牲整条 gate。mock 只影响测试进程，不新增生产 seam。

## 组件设计

### `v24/s13/plugins/fs_read.py`（改，单文件，仅标准库）

**保留不变**：`main` 的帧解析与四操作分派（`:268-320`）；`_path_arg`（`:78-88`）、`_components`（`:90-96`）、`_resolve`（`:98-126`）；`select_prefix` 签名与语义（`:183-189`，被 `selector_probe` 依赖）；常量；`_emit`/`_ok`/`_error`。

**删除**：`_read_bytes`（`:128-153`）、`_line_ranges`（`:157-168`）、`_frame_len`（`:179-180`），以及 `_read_page` 里的旧候选循环（`:229-250`）。`_escaped_len`/`_json_len` 保留但只用于小对象（skeleton、footer），不再用于正文。

**新增内部函数**（签名示意，不是可复制实现）：

```python
CHUNK = 65536

def escaped_bytes_len(raw: bytes) -> int: ...
def _caps() -> dict: ...                 # 每次调用读模块常量，便于注入 cap
def _open_regular(target, info) -> tuple[int, os.stat_result]: ...
def _scan(fd, st, offset, limit) -> tuple[int, bool, list[tuple[int, int]]]: ...
def _read_window(fd, st, bounds) -> list[bytes]: ...
def page_measures(relative, offset, limit, total, final_newline, line_e) -> list[dict]: ...
def empty_measures(relative) -> dict: ...
def choose_k(measures, caps) -> int: ...  # overflow = max(m[d]-caps[d])；select_prefix(overflows, 0)
```

**`_scan` 算法**（输入 fd、首个 fstat、offset、limit；输出 total、final_newline、窗口边界）：

1. `nl = 0`、`bytes_seen = 0`、`last = b""`；需要收集的 LF 序号为 `[offset-1, offset-1+limit]`，其中第 0 个 LF 位置定义为 `-1`（首行起点）。
2. 每块 `chunk = os.read(fd, CHUNK)`，`bytes_seen += len(chunk)`；若 `bytes_seen > MAX_FILE_BYTES` → `file_too_large`。
3. 若本块的 LF 序号区间与目标区间相交，用 `chunk.find(b"\n", i)` 循环取绝对位置；否则只做 `nl += chunk.count(b"\n")`。非空块才更新 `last = chunk[-1:]`。
4. EOF：`total = 0 if bytes_seen == 0 else nl + (0 if last == b"\n" else 1)`；`final_newline = last == b"\n"`；`bytes_seen != st.st_size` → `io_error`。空文件必须走 `total == 0`，不能让空文件变成 1 行（冻结 `empty_offset1/2` 会立刻红）。
5. 由收集到的 LF 位置构造每个窗口行的 `[start, end)`：`start = LF_{i-1} 的绝对位置 + 1`，`end = LF_i 的绝对位置`；最后一行无 LF 时 `end = bytes_seen`。不变量：`len(bounds) == min(limit, total - offset + 1)`，堆占用 O(limit)。
6. 时间为 O(size)，以 C 速度的 `count` 为主；`find` 循环至多 `limit+1` 次。

**窗口读取与解码**：

1. 同一 fd，`os.pread(fd, bounds[-1][1] - bounds[0][0], bounds[0][0])`，短读 → `io_error`。
2. 按 bounds 切片；逐行先查 `len > MAX_LINE_BYTES` → `line_too_long`，再 strict decode → `not_utf8`。第一个失败行决定错误码，与现实现的优先级一致。
3. 每行只算一次 `E_line`（D5 公式），得到 `E_text(k)` 前缀和。

**候选选择**：

1. 对每个 `k = 1..len(bounds)` 填全 `start_line/end_line/total_lines/final_newline/truncated/truncated_by/next_offset`；`truncated = offset+k-1 < total`；`truncated_by = ("lines" if k == limit else "bytes") if truncated else None`；`next_offset = offset+k if truncated else None`（与 `tool_pages._check_read` 一致）。
2. 构造 `text=""` 的 value skeleton 并序列化一次；`value_len = len(skeleton) + E_text(k)`。
3. 构造 `text=""` 的 frame skeleton 并序列化一次；`frame_len = len(frame_skeleton) + E_text(k)`。
4. `content_len = 27 + E_text(k) + (E(footer(k)) if truncated else 0)`（footer 用 `escaped_bytes_len` 现算）；`meta_len = 2`。
5. 四域全部 ≤ cap 的候选里取最大 k；不得首败退出（`select_prefix` 的无早停语义）。
6. 最终只对选中的 k 做一次 `"\n".join(decoded[:k])` 构造 V。
7. 若无 k 适配：首行超 16384 → `line_too_long`（与 §5.6 第 5 步一致）；否则仍是 `line_too_long`（read 无 `entry_too_large`/`hit_too_large`）。

**`read_tool` 新顺序**（错误优先级与现实现一致）：

1. `_path_arg` + `offset`/`limit` 校验（D10 不变）。
2. `_resolve`；路径类错误不变。
3. `lstat`：非 regular → `not_a_file`；`st_size > MAX_FILE_BYTES` → `file_too_large`；symlink → `symlink_denied`（`_resolve` 已覆盖逐组件）。
4. `_open_regular`（D11），`finally` 关闭 fd。
5. `os.pread(fd, 8192, 0)` 含 NUL → `binary_file`。
6. `_scan`；`fstat` 与首个签名比对，不符 → `io_error`。
7. 分支：`total == 0` → `offset != 1` 为 `offset_out_of_range`，否则 `empty_measures` 过四预算（不适配 `output_too_large`）；`offset > total` → `offset_out_of_range`。
8. `_read_window`；第三次 `fstat` 比对，不符 → `io_error`。
9. 逐行检查/解码 → 前缀和 → `page_measures` → `choose_k` → 构造 V → `_ok({"value": V})`。

**数据流不变**：成功帧仍为 `{"ok":true,"v":2,"result":{"value":V}}`，无 meta；错误帧走 `_error`，exit 3；`v != 2` 仍 `bad_request`（不可达：host 不会发送 v≠2，记入台账）。

### `v24/s13/fixtures.py`（改，纯加法）

新增 `read_workspace(root) -> Workspace`，调用 `_prepare_root` + `materialize_nodes`：

| 节点 | 内容 | 用于 |
|---|---|---|
| `empty` | 0 B | R22 |
| `binary` | `61 00 62` | R01 |
| `nul_late` | 8192×`a` + `\x00` + `\n` | R08 |
| `dir/f` | `x\n` | R02、R11 |
| `fifo` | `kind="special"`，`mkfifo` | R03 |
| `noperm` | `x`，测试中 `chmod 000` 并 `finally` 恢复 | R04 |
| `three` | `a\nb\nc\n` | R09、R17 |
| `long_after` | `a\n` + 16385×`z` + `\n` + `c\n` | R18 |
| `ctrl16384` | 16384×`\x01` | R21 |
| `nine5` | 5 行 × 9000×`a`，无尾 LF | R19、R20 |
| `.hidden` | `h` | R16 |
| `wide` | 2000 行 × 523×`\x01`，共 1,047,999 B | R25、R26、R27 |
| `newlines_1m` | 1,048,576×`\n` | R25 |
| `dirlink` | symlink → `dir` | R11 |

R26 用 `read_spec(base, read_workspace(...).root)` 构造 install；`build_spec` 仍复制 `fs_read.py` 并现算 digest，所以 R28 覆盖的是真实 artifact bytes，而不是手工常数。

### `v24/s13/test_tools.py`（改，纯加法）

- `invoke_raw(spec, tool, args, *, drop_root=False)`：在 `spec.entry.environment(source)` 之后 `pop("V24_WORKSPACE_ROOT")`（`environment()` 总会注入，见 `registry.py:86-95`）。
- `run_harness_case(..., result_check=None)`：回调在取得 `payload["tool_result"]` 之后、读取 `output["value"]` 之前调用；带回调的非 `ok` 路径在回调后返回，不进入 `check_value`；既有成功返回与所有既有调用点不变。
- `read_probes(base)`：返回 29；每项走上面的表。
- 成功 probe 统一断言 `set(payload["result"]) == {"value"}`（不发送 meta）。
- 错误 probe 统一断言 `tool_results` 的 error 校验三项（`_assert_error`：code 正则、message ≤1024 B、无绝对路径泄漏）。
- `main` 在 `path_differential`/`selector_probe` 之后累加，并在 marker 前打印：
  ```text
  [evidence] read_artifact_sha256=<hex>; read_1m_wall_ms=<n>; read_peak_kib=<n>; permission_probe=real|mock_root
  ```

### Host、协议与并发边界（不变）

Host 仍负责参数 schema、descriptor limits、value schema、内建 meta、页关系、render、最终预算与 model text；插件只发 `{value}` 或 known error，不发 content/meta。每次调用仍是独立子进程、单请求帧；插件不持有跨请求状态，也不新增 cursor/journal 字段。两遍扫描期间检测到文件变化一律 `io_error`，不返回「统计来自 pass 1、文本来自 pass 2」的混合页。依据：`v24/host/plugins.py`、`tool_pages.py:107-140`、`tool_results.py:243-260`、`design:592-787`、`design:1287-1395`。

## 测试设计与向量覆盖

### 探针 inventory（29 条，计入 marker 的 `read_probes`）

| # | Probe | 方式 | 期望 |
|---|---|---|---|
| R01 | `binary` | 子进程 | `binary_file` |
| R02 | `dir` | 子进程 | `not_a_file` |
| R03 | `fifo` | 子进程，60 s 直接 timeout 不触发 | `not_a_file`，不阻塞 |
| R04 | `noperm` | 非 root：子进程 + chmod；root：进程内 mock `os.open` | `permission_denied` |
| R05 | `io_error` | 进程内 mock `os.open` → `OSError(EIO)` | `io_error` |
| R06 | root 缺失 | `invoke_raw(drop_root=True)` | `root_unavailable` |
| R07 | `three` offset=4 | 子进程 | `offset_out_of_range`（非空） |
| R08 | `nul_late` | 子进程 | success；text 含 `\x00` |
| R09 | `<root>/three` 绝对路径 | 子进程 | success，`path=="three"` |
| R10 | `<base>/outside.txt` | 子进程 | `path_escape`，message 无绝对路径 |
| R11 | `dirlink/f` | 子进程 | `symlink_denied`（中间组件） |
| R12 | `./dir//f` | 子进程 | success，`path=="dir/f"` |
| R13 | `""` | 子进程 | `invalid_path` |
| R14 | `"a"*1025` | 子进程 | `invalid_path` |
| R15 | `"é"*513` | 子进程 | `invalid_path`（单位冲突证据） |
| R16 | `.hidden` | 子进程 | success |
| R17 | `three` | 子进程 | `result` 恰为 `{"value"}`，无 wire meta |
| R18 | `long_after` | 子进程 | `line_too_long`（窗口内后续超长行） |
| R19 | `nine5` limit=4 | 子进程 | k=4，`truncated_by="lines"`（lines/bytes 同时绑定，lines 优先） |
| R20 | `nine5` limit=5 | 子进程 | k=4，`truncated_by="bytes"` |
| R21 | `ctrl16384` | 子进程 | `line_too_long`（无适配前缀） |
| R22 | `empty` + 分别收窄四个 cap | 进程内在 `_caps()` 读取处注入 | 每个子例 `output_too_large`；恢复后 `empty_offset1` 不变 |
| R23 | 计数差分 | 进程内；bytes→str 适配；`render("read", V_k)` 后比四域 | `escaped_bytes_len(raw)` 对 `escaped_payload_bytes(raw.decode())`；`page_measures` 对两个 oracle 的 value/content/meta/frame |
| R24 | footer 参与选择 | 进程内注入 `MAX_CONTENT_BYTES` | 选中 k 小于「不含 footer」公式会选的 k |
| R25 | `newlines_1m`、`wide` | 进程内 `tracemalloc` | 峰值 < 8 MiB；`total_lines==1048576` |
| R26 | `wide` | DB-backed `run_harness_case`（新增 `result_check` 回调取 `usage.wall_ms`） | 真实 executor 下 `success`，`wall_ms` 记录，无 unknown timeout |
| R27 | `wide` | 进程内只包 `read_tool` 的 `json.dumps` | skeleton 的 text 为空；每次 ≤4096+E(path)；次数 ≤2·limit+8 |
| R28 | artifact digest | 进程内 | 源/副本/entry 三方 sha 相等且 `require_artifact()` 通过；翻转副本 1 B 后 `artifact_digest_mismatch` |
| R29 | 变更检测 | 进程内包装 `_scan`：返回前追加 1 B；另一子例改写同 size 并恢复 mtime | `io_error`（ctime 变化被捕获） |

计数：29 条新 probe；`cases = 74 + 29 = 103`（macOS shim 模式）。Linux 变体不跑 5 条 shim guard，预计为 98；W5 不运行 Linux，该数字不在验收内；`linux_real=not_run` 不变。

### 差分与红基线

- **R23 计数差分**：先对全部 0x00–0x7F 单字节及多字节样本（é、😀、U+2028/U+2029、DEL）断言 `escaped_bytes_len(raw) == w1_reference.escaped_payload_bytes(raw.decode("utf-8", "strict"))`（后者只接受 str，不能直接传同一个对象）；再取合成行集（引号、反斜杠、`\b\f\r\t`、`\x01`、`\x1f`、行末 CR、非 ASCII、空行）与位数边界（offset/total 9/10/99/100/1000），对每个 k 先构造完整的 `V_k`，`content, meta = w1_reference.render("read", V_k)`，再比较 `page_measures` 与 `w1_reference.budget_measures(args, V_k, content, meta)`、`tool_results.measure(args, V_k, content, meta)` 的 value/content/meta/frame 四域（两个 oracle 同时返回 args 计量，不作为本项比较域）。物化候选只用于合成小样本与 k≤32；宽行文件只验证选中的 k 与少量边界，避免测试自身 O(n²)。
- **红基线（W5-1）按 probe 定义可执行性**（不要求 29 条全红）：R21/R24/R25/R26/R27 可通过既有接口对旧行为运行；R22 直接调用旧 `_read_page()` 并在测试内临时替换模块 cap 常量，记录它返回空 value 而不检查预算；R23 直接对比旧的 `27 + _escaped_len(text)` 与含 footer 的参考值；R29 是修复后才存在的 green-only probe（旧代码没有 `_scan` 可包），以一次同 size 改写反证代替；R28 及其 tamper 反证在基线上已是 green。`6.742 s` 与 `123.9 MiB` 是**先前观测**，不是 W5-1 必须复现的数值；日志记录本次实测值与「旧代码经 host path 得到 unknown timeout」这一事实。
- **冻结覆盖**：16 条冻结 read 用例照旧执行（`test_tools.py:314-322`），结果逐字节不变；`test_contracts.py`/`test_vectors.py` 不改代码，继续守护冻结期望。

### 缺陷 → 探针映射

| 缺陷 | 关门探针 |
|---|---|
| 1 deadline | R26（成功）、R27（不再序列化正文） |
| 2 内存 | R25 |
| 3 footer | R23（三方相等）、R24（选择差异） |
| 4 空页预算 | R22 |
| 未断言错误码 | R01–R07 |
| 路径/分页边界 | R08–R21 |
| artifact 证据 | R28 |
| 并发变更 | R29 |

## Gate、证据与 scope audit

所有测试命令使用 credential-clearing 前缀：

```bash
ENVPFX="env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1"
```

**串行 32 条**（顺序与 W4c 执行记录一致；W5 不新增命令，故没有插在 SQL 行之前的新行）：

1. `v24/s13/test_pages.py`
2. `v24/s13/test_wiring.py`（内置六项 scope audit）
3. `v24/s13/test_descriptor.py`
4. `v24/s13/test_schema.py`
5. `v24/s13/test_renderers.py`
6. `v24/s13/test_results.py`
7. `v24/s13/test_registry.py`
8. `v24/s13/test_line_json.py`
9. `v24/s13/test_contracts.py`
10. `v24/s13/test_vectors.py`
11. `v24/s13/test_vectors.py --node`
12. `v24/b0/test_golden.py`
13. `v24/b0/test_golden.py --node`
14. `v24/load.py`
15. `v24/s1/setup_db.py --self-check`
16. `v24/s1/test_ddl.py`
17. `v24/s1/test_g1.py`
18. `v24/s2/test_g3a.py`
19. `v24/s3/test_g2.py`
20. `v24/s4/test_g2b.py`
21. `v24/s5/test_g4.py`
22. `v24/s6/test_g5.py`
23. `v24/s8/test_g7.py`
24. `v24/s7/test_g6.py`
25. `v24/s10/test_g9.py`
26. `v24/s11/test_g10.py`
27. `v24/s11/test_node.py --node`
28. `python -m v24.host.plugin_smoke --multilingual-smoke`
29. `v24/s13/test_tools.py` — 唯一 marker 变化（Done when #6）
30. `v24/s13/test_lifecycle.py`
31. `v24/s13/test_node.py --node`
32. `git diff --exit-code c8c4bd0 -- v24/sql`

三态：命令 1–31 需 exit 0 且末行为命令专属 `[passed]`；命令 32 需 exit 0 且输出为空，没有 `[passed]` 标记。exit 2/`[SKIP]` 阻塞 W5。closeout 仍 **11/11**；s13 不是第 12 条 closeout。

**Scope audit（七项）**：

1–6 沿用 W4c 的六项，钉 `c8c4bd0`：冻结模块与 s13 测试、冻结向量（除 design 元数据）、`design_conformance` 还原相等、`registry.py` D12 精确 patch、host import purity、SQL 零 diff。第 3 项仍按 W4c 的还原相等执行：把当前 design SHA 行替换回 `c8c4bd0` 的值后逐字节相等；W5 不改 design，所以该行相对 HEAD 也应零 diff。

7（W5 新增）：W5-0 先快照当时的 untracked 路径（`baseline-untracked.txt`），审计算 W5 delta = `git diff --name-only 5771ce3 --` ∪（当前 untracked − W5-0 快照）。delta 必须是 candidate 路径的子集，否则 STOP；只算 `git diff --name-only` 会漏掉新建的执行记录，而把全量 untracked 都算进来又会被仓库里既有的 `.ctx-export-*`、`v20/experiments/ce_native_d5/**` 等无关文件误判为越界。**七项 audit 必须在 W5-6 写完所有文档后、W5-7 staging 之前完整重跑一次**；W5-5 的那次是预检。打印 `[scope] passed w5_candidate_only`。candidate 集合：

- `v24/s13/plugins/fs_read.py`
- `v24/s13/fixtures.py`
- `v24/s13/test_tools.py`
- `v24/s13/README.md`
- `docs/reviews/v24-conformance-matrix-2026-10-23.md`
- `docs/reviews/v24-deviation-ledger-2026-10-23.md`
- `docs/reviews/v24-tool-plugin-abi-w5-execution-2026-10-31.md`
- `docs/reviews/v24-tool-plugin-abi-w5-python-read-plan-critique-2026-10-31.md`
- `docs/plans/v24-tool-plugin-abi-w5-python-read-2026-10-31.md`

**证据目录** `/tmp/w5-<UTC>/`：

- `provenance.txt`（HEAD/branch/upstream/uv/python/node/OS 版本）
- `git-status-porcelain.txt`（初始与最终）
- `source-sha256.txt`（candidate 路径，含 `fs_read.py` 的 artifact sha）
- `credential-scan.txt`（脱敏）
- `red-baseline.log`（W5-1）
- `01.log`–`32.log`、`results.tsv`（命令、UTC 开始、exit、真实末行、log sha256）、`merged.log`
- `scope-audit.tsv`、`scope-1..7.log`

执行记录体例照搬 W4c：Result、Candidate and provenance、Implementation and coverage、Scope and compatibility audits、Deviations、Limits、Publication。**不得**记录 API key；凭据扫描命中即 STOP。

## 工作项与执行索引

| # | Goal | Done when | Key files | Deps | Size |
|---|---|---|---|---|---|
| W5-0 | 建立 candidate、provenance、基线确认 | HEAD `5771ce3`、porcelain 与 untracked 快照 `baseline-untracked.txt` 均已记录；确认三个改动文件不在 frozen 列表；`grep` 无硬编码旧 sha；核对本计划引用的 file:line 与冻结路径 | 证据目录、本计划 | — | S |
| W5-1 | 红基线（按 probe 可执行性） | 可对旧代码运行的 R21/R24/R25/R26/R27 与旧 `_read_page` 的 R22、旧 content 计量的 R23 记录预期红；R29 记为 green-only；R28 记为基线 green；`6.742 s`/`123.9 MiB` 只作先前观测 | `test_tools.py`（草稿）、`fixtures.py` | W5-0 | S |
| W5-2 | 两遍 I/O、open 加固、变更检测 | R01–R07、R25、R29 绿；冻结 16 例不变 | `fs_read.py` | W5-1 | M |
| W5-3 | 可加计量、`choose_k`、空页预算 | R20–R24、R27 绿；冻结 16 例不变 | `fs_read.py` | W5-2 | M |
| W5-4 | 其余边界与 digest | R08–R19、R28 绿；marker 达到 `cases=103; read=16; read_probes=29` | `test_tools.py`、`fixtures.py` | W5-1（可与 W5-2 并行） | M |
| W5-5 | 全量 sweep 与七项 audit（预检） | 32/32 exit 0；七项 audit 过；无 SKIP；此轮不替代 W5-7 前的最终重跑 | 证据目录 | W5-3、W5-4 | M |
| W5-6 | 收尾工件 | ledger、matrix、README W5 小节、执行记录、plan Result 只填实测值 | docs、README | W5-5 | S |
| W5-7 | 提交与推送 | 先完整重跑七项 audit（W5-6 之后），再按路径 add、复查 staged diff、正常 hook、非 force push | allowlist | W5-6 | S |

依赖图：

```text
W5-0 → W5-1 → { W5-2 → W5-3 , W5-4 } → W5-5 → W5-6 → W5-7
```

W5-1 与 W5-4 可以并行；W5-3 依赖 W5-2 的窗口读取接口；W5-6 只有在 W5-5 全绿后才能写「实测」字样。

## File-by-file impact

| 文件 | 变更 | 依据 | 顺序 |
|---|---|---|---|
| `v24/s13/plugins/fs_read.py` | 删 `_read_bytes`/`_line_ranges`/`_frame_len` 与旧候选循环；加 `escaped_bytes_len`/`_caps`/`_open_regular`/`_scan`/`_read_window`/`page_measures`/`empty_measures`/`choose_k`；改 `read_tool` 编排；空分支过四预算 | D2/D5/D6/D11 | W5-2→W5-3 |
| `v24/s13/fixtures.py` | 加 `read_workspace`（纯加法，不动既有 `read_spec`/`build_spec`） | D9 | W5-1 |
| `v24/s13/test_tools.py` | 加 `invoke_raw`、`read_probes`（R01–R29）、evidence 行与 `read_probes` marker 字段 | D1/D3/D4/D14 | W5-1、W5-4 |
| `v24/s13/README.md` | 加 W5 小节：命令不变、新 marker、M3 仍 timing pending、closeout 11/11 | AGENTS 收尾工件 | W5-6 |
| `docs/reviews/v24-deviation-ledger-2026-10-23.md` | 新增 `D-ABI-W5-1…7` | 见下 | W5-6 |
| `docs/reviews/v24-conformance-matrix-2026-10-23.md` | 新增 W5 小节，体例同 W4b/W4c | 体例 | W5-6 |
| `docs/reviews/v24-tool-plugin-abi-w5-execution-2026-10-31.md` | 新建 | Gate 节 | W5-6 |
| `docs/reviews/v24-tool-plugin-abi-w5-python-read-plan-critique-2026-10-31.md` | 新建（独立评审记录，含 10 条 finding 与 resolution） | 评审 | W5-6 |
| `docs/plans/v24-tool-plugin-abi-w5-python-read-2026-10-31.md` | 填 Oracle 裁决与 Result | — | W5-6 |

**Ledger 条目**（编号在 W5-6 落笔时按实际顺序确认）：

| 条目 | 内容 |
|---|---|
| D-ABI-W5-1 | 四缺陷修复与实测（deadline/memory/footer/empty） |
| D-ABI-W5-2 | 可加计量公式与三方差分证据 |
| D-ABI-W5-3 | 打开加固与变更检测（`io_error`）；比较 dev/ino/size/mtime_ns/ctime_ns；best-effort：能同时恢复全部元数据的改写仍检测不到，属受信 workspace 边界 |
| D-ABI-W5-4 | 空页 `output_too_large`：§5.6 指定、§6.2 十四码未收录、§5.2 又把它列为 host code；插件按 §5.6 执行 |
| D-ABI-W5-5 | 解码窗口按冻结向量（§5.6:773 vs §6.2:824） |
| D-ABI-W5-6 | path 长度单位（bytes vs scalar） |
| D-ABI-W5-7 | 非法 `offset`/`limit` 的 `invalid_path` 与 artifact digest 证据边界 |

**明确不变**：

- `v24/host/**`、`v24/sql/**`、`v24/s10/**`、`v24/s11/**`、`v24/b0/**`、`v24/load.py`；
- `v24/s13/vectors/**`（含 `design_conformance.json` 与两个 pending case）；
- `v24/s13/plugins/fs_tools.js`、`w4b_non_utf8_preload.cjs`、`w1_reference.py`；
- `test_contracts.py`、`test_vectors.py`、`test_registry.py`、`test_pages.py`、`test_wiring.py`、`test_lifecycle.py`、`test_node.py`；
- `docs/designs/**`。

## 风险、STOP 与回滚

| # | 风险 | 触发 | 处置 |
|---|---|---|---|
| 1 | 冻结 16 例任一结果改变 | W5-2/W5-3 后 `expect_value`/`expect_error` 红 | **STOP**。回到 D5/D7 对齐；不得改向量 |
| 2 | 计数差分有任一行不等 | R23 三方不一致 | **STOP**。先修计量，不允许放宽 oracle |
| 3 | 真实 harness 仍超 5 s | R26 unknown/timeout | **STOP**。定位剩余成本（UTF-8/序列化/host），不得扩大 descriptor timeout，不得把 timeout 当成功 |
| 4 | 两遍期间文件变化 | 签名/长度不一致 | 返回 `io_error`，不返回混合页；不得用「重试一次」掩盖 |
| 5 | 内存仍随行数增长 | R25 峰值 > 8 MiB | **STOP**。检查是否仍保留全量 ranges 或整文件 bytes |
| 6 | 权限探针在 root 下不可用 | `geteuid()==0` | 走 mock 分支并打 evidence；不得整 gate SKIP |
| 7 | 向量/design 漂移 | 任一 semantic vector 或 design 字节变化 | **STOP**。D12 明确不改；保留原文件 |
| 8 | 证据缺失 | 任一命令无末行/无 log sha | 重跑该命令，整表重记；不得补写 |

**回滚**：无 DB/schema migration。若 gate 失败，按同一提交整体回滚插件、测试、fixtures 与文档；不做部分撤销导致 marker/记录自相矛盾。`fs_read.py` 每次重建 fixture 都会重算 digest，无需数据库迁移。

## 提交与推送

`AGENTS.md`：测试实际全绿 → 更新收尾工件 → 按路径 `git add` → 复查 `git status` 与密钥 → `commit` → `push origin main`；禁止 `git add -A`/`git add .`、`--no-verify`、force push。

W5-7 只在 W5-6 完成后执行：先完整重跑七项 audit（含 W5-0 的 untracked 快照差分），再复查 status 与 candidate hash，按 File-by-file 的 allowlist 逐项 add；再次检查 staged diff 与 credential scan；提交信息建议 `v24: close out Python read plugin ABI`；随后 push。push 被拒时按 `AGENTS.md` 的 fetch/rebase 规则处理，不 force。无关的 `.ctx-export-*`、`.token-probe*`、`ctx_export_check*`、`docs/investigations/v24-m3-budget-closeout-2026-10-31.md`、`v20/experiments/ce_native_d5/**` 不得进入提交。

## W5 不证明什么

- 不证明 M3 完成：`tool.search_budget_timing_m3_pending` 仍 `m3_pending`，search 的 12 秒扫描预算与 cutoff timing 未验证。
- 不证明 Linux real 非 UTF-8 文件名支持；`linux_real=not_run` 不变。
- 不证明 `list`/`search` 行为、Node install、kernel/replay 改动、恶意并发 workspace 防护或真实 provider 行为。
- 不证明冻结向量的 pending 状态已关闭：`manifest.artifact_digest_pending` 仍是 `m3_pending`，只补了 read 侧的实测 digest 证据。
- 不把 closeout 从 11/11 改写；s13 仍是 extension evidence，不是第 12 条 closeout。

## Oracle 裁决记录

2026-10-31。本节记录**裁决轮**，它与生成计划时的 context_builder export 是两件事：生成轮 lane 1（`claude-opus-5-5`）在中途 provider 错误后 partial、lane 2（`gpt-6.1-sol-xhigh`）完整，且 lane 2 对空页错误建议追加 design C.18；裁决轮是在草案写完之后单独发起的一次 `ask_oracle`，两条 lane 均完整返回，结论一致为六项 A（含 ledger-only、不 repin）。因此下表是对生成轮建议的**证据性覆盖**，不是对其结论的转述。

| # | 决策 | 裁决 | 理由（一行） | Confidence | 何种证据可推翻 |
|---|---|---|---|---|---|
| O1 | 空页 `output_too_large` 归属 | **A**：插件发码 + 台账，不改 design、不 repin | §5.6:778 是最具体的分页算法；host 只校验键集、不校验十四码闭集（`line_json.py:240-247`、`plugins.py:188`）；C 会误报原因，B 为不可达分支付 pin 成本 | high | 若某处实际强制 descriptor 错误码列表，或另因他事必须 repin（则把 C.18 一并折入） |
| O2 | 候选计量实现 | **A**：逐行可加 `E_text(k)` + 每候选 `text=""` skeleton | skeleton 携带真实整数，位数变化被测量而不是被建模；约 1 MB 的小对象序列化相对 6.7 s 缺陷可忽略 | high | R23 在位数边界出现不等；或 profile 显示修掉正文重复后 skeleton 仍是 deadline 主因 |
| O3 | 扫描架构 | **A**：单 fd 两遍 + 64 KiB 分块 + 一次 `pread` 窗口 | B 仍要全文件计行、最终坍缩成 A；mmap 在截断时 SIGBUS 会被 host 归 unknown | high | 目标平台无 `pread`；或 R25 峰值 >8 MiB 而分块单遍可达标 |
| O4 | deadline 回归守护 | **A**：真实 harness 成功 + R27 + `wall_ms` 仅作证据 | C.16 拒绝墙钟 gate；R27 与机器速度无关，是硬件无关的主守护；host 5 s kill 才是唯一 deadline | medium-high | 出现明确的 2000 ms 支持环境延迟要求（需可重复测量与测量边界） |
| O5 | artifact digest 向量 | **A**：冻结向量 + 三方 digest 断言 + tamper 反证 + 记录实测值 | `test_contracts.py:71` 禁止 `passed`；`test_registry.py:233` 钉的是 `manifest.five_field_key.status`（不是本 case），本 case 由向量规则与自身字节/status 保持冻结；promotion 需先改 checker 不变量与词表 | high | 另经审查的向量/词表修订定义新状态语义与 checker 变更（属另一阶段） |
| O6 | W5 范围口径 | **A**：收口框架；用户范围判断，采保守默认 | W4b 已交付功能面且 16 条冻结用例绿；重写无收益且危及冻结用例；B 需要 C.16 已拒绝的 timing gate 设计与本机没有的 Linux 硬件 | high（工程）/ medium（意图） | 你明确要求 ground-up 重写，或要求 W5 承担 M3 timing/cutoff / Linux 证据 |

裁决附带的验证细化（已并入正文）：

- **R27**：包装范围限定 `read_tool`，不包 `main`/`_emit`；判据改为检查 skeleton 的 `text` 字段为空（而非在序列化字节里搜正文子串）；大小界改为 `4096 + E(path)`，因为含控制字符的合法 path 转义后会膨胀；footer 用字节计数器，不再额外 dump。
- **R28**：三方 digest 相等本身有同义反复成分（fixture 从副本现算），因此必须加 tamper 反证：翻转已安装副本 1 B，要求 `require_artifact()` 抛 `artifact_digest_mismatch`。实测 digest 在 `fs_read.py` 最终编辑之后计算，并声明它是证据、不是向量 promotion。
- **R26**：必须走真实 DB-backed executor，不得换成 fake；`run_harness_case` 增加可选 `result_check` 回调以读取 `usage.wall_ms`，既有调用点与返回值不变。
- **R22**：四个 cap 分别收窄成子例，统一在 `_caps()` 读取处注入，不经 env/argv。
- **D-ABI-W5-3**：签名比较含 dev/ino/size/mtime_ns/ctime_ns；best-effort：能同时恢复全部元数据的改写仍检测不到；这是受信 workspace 边界，不是原子快照保证。
- **D-ABI-W5-4**：同时记录 §5.2 把 `output_too_large` 列为 host code、§6.2 未收录、§5.6 指定三者并存；不得新增「插件码必须是十四码子集」的断言。

评审后补入（已并入正文）：签名比较恢复 `st_ctime_ns`，R29 增加「同 size + 恢复 mtime」子例；R19/R20 用同一 `nine5` 的 limit=4/5 对照隔离 lines/bytes；W5-1 红基线按 probe 可执行性定义，`6.742 s`/`123.9 MiB` 只作先前观测；candidate-only audit 用 W5-0 的 untracked 快照做差分，并在 W5-6 之后重跑。

## References

- `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md` §4.4、§5.2–§5.6、§6.1–§6.2、§7.1/§7.3/§7.4、附录 C.11–C.17。
- `docs/plans/v24-tool-plugin-abi-w4-dispatcher-worker-wiring-2026-10-31.md`（W4a/W4b/W4c 切分与 W4b 组件设计）。
- `docs/reviews/v24-tool-plugin-abi-w4b-execution-2026-10-31.md`、`...-w4c-execution-2026-10-31.md`。
- `docs/reviews/v24-tool-plugin-abi-w5-python-read-plan-critique-2026-10-31.md`（本计划的独立评审；其 blocker 已由裁决轮解决）。
- `v24/s13/plugins/fs_read.py`、`v24/s13/test_tools.py`、`v24/s13/fixtures.py`、`v24/s13/w1_reference.py`、`v24/s13/test_contracts.py`、`v24/s13/test_registry.py`。
- `v24/host/{canonical,tool_pages,tool_results,registry,line_json,process_io,plugins}.py`。
- `v24/s13/vectors/{README.md,tool_contracts.json,manifest_adapter_v2.json,design_conformance.json}`。
- `docs/reviews/v24-conformance-matrix-2026-10-23.md`、`docs/reviews/v24-deviation-ledger-2026-10-23.md`、`AGENTS.md`。

## Result

2026-10-31，W5 Python `read` 收口已按裁决执行；D1–D14 / O1–O6 不变。W5-0…W5-4 复用已完成且经 orchestrator 验证的实现与证据，本轮只执行 W5-5…W5-7，不重做实现、不改冻结权威。

**W5-5 实测：** 在 `main` @ `5771ce3809dea8bf979a617fef3fdbf03f07a340`，第 1 条于 2026-10-31T07:29:24Z 开始、第 32 条于 07:31:31Z 开始（是命令起始时间，不作端到端耗时），按本文顺序、凭据清除前缀串行运行全部 32 条命令，32/32 exit 0。第 1–31 条具有其命令专属真实末行；第 32 条 `git diff --exit-code c8c4bd0 -- v24/sql` 的输出为 0 B、真实末行为空，无 `[passed]`。无 exit 2/`[SKIP]`。最终工具 marker：

```text
[passed] W4 fs tools; cases=103; read=16; read_probes=29; list=7; search=24; pagination_converged=true; page_contracts_imported=3
```

本轮 R26 `success`，`read_1m_wall_ms=113`，未更改 5000 ms host deadline；R25 `read_peak_kib=3959.904`，两类 1 MiB 文件均 <8 MiB；`permission_probe=real`。W5-4 已验证的 92–93 ms 作为先前执行证据保留，不伪装成本轮值。本轮继承的红基线为 `unknown`/`timeout`、`wall_ms=5006`，旧峰值 `128043.177 KiB`、footer 漏算 55 B、增长正文序列化 2000 次、空页绕过预算。16 条冻结 read 输出逐字节相同，R01…R29 全绿。

`fs_read.py` 源/副本/entry SHA-256 为 `260274daba1efa87f4c33103fe53503c76a65187af68e610d5aedcfadad5165c`；tamper 反证已通过。七项 audit 预检全过；全部文档落盘后、staging 前再次完整执行七项，最终日志与时间由该重跑生成到 `scope-final/`，并替换顶层 `scope-audit.tsv`、`scope-1..7.log`；重跑前顶层文件仅为预检副本，重跑后的表与发布回执为最终状态权威。第 1–6 项钉 `c8c4bd0`，第 7 项按 `5771ce3` tracked delta ∪（当前 untracked − `baseline-untracked.txt`）检查九路径 allowlist。已存在的无关 untracked 不作为 W5 输出，也不进入提交。

**W5-6 工件：** ledger 增加 D-ABI-W5-1…7；matrix、s13 README 增加 W5 小节；新建 [W5 execution record](../reviews/v24-tool-plugin-abi-w5-execution-2026-10-31.md)，保留 32 行串行表、七项审计、source/artifact/evidence digests；critique 保留原十条 finding 与既有 resolution，并追加逐条实施结果。证据复用 `/tmp/w5-20261031T063812Z/`，保留原 provenance、基线与 handoff，新增逐命令日志、TSV、merged log、预检/最终审计、最终 source/status 清单与脱敏 credential scan。

**W5-7 发布规则：** 文档完成后重跑全部七项 audit，再逐路径暂存九个 candidate，复查 status/staged diff 与凭据扫描，正常 hook，单个 `v24: close out Python read plugin ABI` 提交及非 force `git push origin main`；真实 SHA/推送结果由发布回执报告，本文件不嵌入自身提交哈希。

**不升级边界：** closeout 仍 **11/11**；s13 是 extension evidence，不是第 12 条。W5 不表示 M3 完成；search 12 秒 timing/cutoff 仍 pending，`tool.search_budget_timing_m3_pending` 保持 `m3_pending`，`linux_real=not_run`。`manifest.artifact_digest_pending` / `manifest.five_field_key` 的 status/expected、全部向量、design/pins、host、SQL、Node 插件与指定冻结测试均保持 W5 零 diff。规范内部冲突继续由 D-ABI-W5-4…6 记录，不改 design、不 repin、不 re-bless。
