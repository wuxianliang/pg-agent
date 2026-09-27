# v13 工具口岸开发规范

> 本文是 v13 `kind='tool'` 口岸的唯一规范。内核规范仍预留在 `docs/designs/v13-dev.md`；本文当前只冻结口岸子系统，不动该占位。`v13/read_tools/README.md` 是活台账；与本文冲突时以本文为准。教程（含 `docs/tutorials/v13/`）无合同效力。
>
> 合同版本：`v13/tool-port-contract-1`。改变行为必须在同一提交 bump 本版本号。已发布条款 ID 禁止复用为不同义务；废止则保留 ID 并标明废止。
>
> **断言编号由里程碑 F 落地**；本规范提交不改 gate。在 F 把所标编号写进 `v13/read_tools/test_read_tools.py` 之前，绿的 gate 不表示每一条已在代码里强制。这是有意窗口，不是豁免。F 落地后，所标编号必须出现在 gate 输出中。编号与条款冲突时以本文为准，同笔提交改测试；禁止为迁就旧实现改条款，禁止把精确相等放宽成不等式。

范围：所有 `kind='tool'` 口岸（现有 `read_pi`、`read_file_swift`、`read_file_py`、`read_duck`，以及未来 JS/TS、Python、Swift、DuckDB/SQL 新口岸）。内核会话机与 SQL 阶段不在本文范围。

检查手段：`gate` = 该测试文件的断言；`source` = 读源码或 git；`manual` = 默认 gate 不跑，命令写在条款里。一条可带多种手段，所列都要满足。

## 0. 不可妥协的不变量

1. **TP-INV-1** 线协议退出码只许 0、3、1，且与 `ok` 旗标一致；不一致即协议错。详见 TP-WIRE-1。检查：行为 B5/C8/F8。
2. **TP-INV-2** 帧必须同步写完才退出。详见 TP-WIRE-3。检查：source C8。
3. **TP-INV-3** 子进程口岸只经 `run_line_json`。详见 TP-SUB-1。检查：source G2；行为 B5/C8/F8。
4. **TP-INV-4** 错误码是闭集，禁止串平面。详见 TP-PLANE-1。检查：gate A/B/C/F。
5. **TP-INV-5** 正文 U+0000 是 `read_failed`；路径含 NUL 是 `path_outside_workspace`。详见 TP-FS-4、TP-FS-5。检查：gate A12/B4/C10/F9。
6. **TP-INV-6** 空白 root 是 `invalid_params`；realpath 系 OSError 是 `read_failed`，子进程退出 3。详见 TP-FS-1、TP-FS-2。检查：gate A13/B8/C6/F6。
7. **TP-INV-7** headless 平面 Swift 文本必须等于 Python；Pi 与 Duck 各钉自己的常量；CRLF 全文必须不相等。详见 TP-PLANE-2、TP-TEXT-1、TP-TEXT-2。检查：gate B、C9、F3。
8. **TP-INV-8** `param_spec.options` 闭合；模型不收自由路径。详见 TP-CAT-3。检查：gate D3/D7。
9. **TP-INV-9** 读盘在 `v13_claim` 提交之后、`v13_complete` 开启之前；`finally` 兜底关连接或回滚。详见 TP-HUB-2。检查：source D14；gate D。
10. **TP-INV-10** 工具链缺席只跳自己的组；退出 2 不是通过。详见 TP-GATE-1、TP-GATE-2。检查：gate G1。
11. **TP-INV-11** 被哈希的扩展文件必须是被 `LOAD` 的文件；community 失败禁止改道。详见 TP-DUCK-3、TP-DUCK-5。检查：gate F1/F11。
12. **TP-INV-12** fork dev 引擎与 released DuckDB 不互载；受保护路径禁止改。详见 TP-DUCK-6。检查：source G2。
13. **TP-INV-13** 渲染常量是带版本标签的实测快照；禁止自动改 pin。详见 TP-SNAP-1、TP-SNAP-2。检查：gate F3/F10。
14. **TP-INV-14** 四份围栏各自独立源码，用相等断言锁；禁止抽共享模块。详见 TP-FS-9。检查：source F2；gate B8/C6/F6。
15. **TP-INV-15** 权威顺序是规范 > 台账 > 归属 > 已取代计划。规范是本文；台账是 `v13/read_tools/README.md`；归属是根 `THIRD_PARTY_NOTICES.md`；已取代计划是 `docs/plans/v13-native-read-tools-2026-09-27.md`（tombstone，禁止引用已删正文）。教程无合同效力。检查：source E3（README 必须提及本文路径以及 `TP-WIRE-3`、`TP-FS-5`、`TP-DUCK-3`）；source G2（`os.path.isfile('docs/designs/v13-tool-ports.md')`）。

## 1. 目录与 handler

**TP-CAT-1** 四个 `kind='tool'` 行只在库 `agent_v13_read_tools` 运行时 INSERT/DELETE。`setup_db` 必须 `load_stage(..., 'seam')`，且会 DROP 该库。禁止写入 `v13_core.sql`，禁止追加 `SQL_LOAD_ORDER`，禁止改 `v13/**/*.sql`。`description` 必须满足内核既有 `^[\x20-\x7E]+$`。加一种 handler 只 INSERT 目录行再起进程，SQL 文件改动数必须是 0。

| name | handler | 执行 |
|---|---|---|
| `read_pi` | `worker:read_pi` | `node read_pi.mjs`；环上只送 root/path |
| `read_file_swift` | `worker:read_file_swift` | `swift read_file_swift.swift` |
| `read_file_py` | `worker:read_file_py` | 进程内 `read_text`；不经桥 |
| `read_duck` | `worker:read_duck` | `.duck-venv` 的 python + `read_duck_port.py`；环上只送 root/path；语言由口岸从扩展名推导 |

检查：gate D3/D7；source G2。

**TP-CAT-2** worker 只按冻结的 `request.handler` 分派，禁止查活 `tools` 表决定跑哪个二进制。运行时 INSERT/DELETE 不得改写已冻结请求的 handler。检查：source D14；gate D14。

**TP-CAT-3** options 闭合。前三行 `path.options` 只许 `hello.txt` 与 `crlf.txt`。`read_duck` 只许 `{"fib.py": "Python fixture"}`，禁止 `hello.txt`（纯文本喂不进 AST）。`root` 由 hub 注入。模型不收自由路径。`../`、绝对路径、offset、limit、CRLF 只在直接调口岸时测，不进判断面。检查：gate D3/D7。

**TP-CAT-4** 新口岸确需改 schema 或加列时，必须拆成独立内核变更并 bump 合同版本。禁止在口岸提交里给 `tools` 加 `input_schema` / `mutating` / `allowlist` / `timeout_ms` / `consumes` / `produces`。检查：source G2；manual：对照 TP-ADMIT-1。

## 2. 合同分层

**TP-PLANE-1** 每个口岸必须声明输入、结果类型、错误闭集、路径规则、切分规则、证据来源。闭集之外的码禁止出现。相等平面才可互为 oracle。

| 口岸 | 输入 | 结果 | 错误闭集 | 证据 |
|---|---|---|---|---|
| `read_file_py` | root、path、可选 start_line/limit | `str` 或 `ReadError` | `invalid_params`、`path_outside_workspace`、`read_failed` | RepoPrompt CE headless 子集 + A 组 |
| `read_file_swift` | 同行 JSON | 字符串帧 | 同上三码 | 与 `read_text` 相等（B） |
| `read_pi` | root、path、可选 offset/limit | 字符串帧 | 三码 + `image_unsupported` | pi-coding-agent 0.80.3 `read.ts`/`truncate.ts` + C |
| `read_duck` | root、path | 渲染字符串帧 | 三码 + `language_unsupported`、`parse_failed` | 实测 `FIB_RENDER` + `PIN_LABEL` |

headless 禁止 `image_unsupported` / `language_unsupported` / `parse_failed`。Pi 禁止后两码。Duck 禁止 `image_unsupported`。`protocol_error` 是桥/hub 的映射，禁止写进口岸 `error` 字段。检查：gate A/B/C/F。

**TP-PLANE-2** 只有 headless 平面（Python 与 Swift）可互为 oracle：同参 Swift 结果文本必须等于 `read_text`。Pi 只对照 Pi 文本读矩阵。Duck 只对照带标签的实测快照。禁止三方共用一张矩阵。检查：gate B、C、F3。

**TP-PLANE-3** 独立平面至少一条反合并断言。Pi：`crlf.txt` 全文必须不等于 headless 的 `alpha\n\nbeta\n\n`，且等于只按 `"\n"` 连接的结果（C9）。Duck：围栏内 `hello.txt` 必须 `language_unsupported`（`read_text` 会成功，故这条钉的是 duck 不是 Python）；`fib.py` 含 `print(fib(6))`，渲染结果必须不含这次调用。检查：gate C9、D16、F3。

**TP-PLANE-4** Python 不因进程内调用而成为 Pi 或 Duck 的语义真理。进程内只是 headless 平面的 oracle。检查：gate C9、D16。

## 3. 线协议

**TP-WIRE-1** 子进程口岸一帧一行 JSON，换行结尾。正文在 JSON 字符串里转义，帧仍是一行。

| 结果 | stdout | 退出码 |
|---|---|---|
| 成功 | `{"ok":true,"result":"<text>"}`，`result` 为字符串，含 `""` | 0 |
| 工具错误 | `{"ok":false,"error":"<code>","message":"<detail>"}`，码在该平面闭集内 | 3 |
| 空或全空白 stdin | `invalid_params` 帧 | 3 |
| 坏 JSON、非对象、stdin 非 UTF-8、未捕获非工具异常 | 无帧 | 1 |

退出码 0 仅当 `ok=true` 且 `result` 为字符串。退出码 3 仅当 `ok=false` 且 `error` 为字符串。旗标不一致、退出码不在 `{0,3}`、EOF、空帧，一律 `protocol_error`。检查：行为 B5/C8/F8。

**TP-WIRE-2** stdout 只承载帧。诊断、`fail_internal`、WARN 走 stderr。禁止把诊断写进成功帧。检查：source B5/C8/F2。

**TP-WIRE-3** 必须同步写完整帧才退出。Swift 必须 `FileHandle.standardOutput.write` 加单个 `0x0A`，禁止 `print`；既有 `try?` 不另立错误路径。Node 必须把帧编码成字节后 `fs.writeSync(1, …)` 循环处理 partial write，写完整帧才 `process.exit`；禁止 `process.stdout.write`；写失败 exit 1 且不写第二帧。Python 子进程口岸必须 `sys.stdout.buffer.write` 后 `flush` 再退出。检查：source C8（含 `writeSync`、不含 `process.stdout.write`）；行为 B5/C8/F8（成功与工具错误各断言 stdout 恰好一个非空帧）。

**TP-WIRE-4** 协议失败路径必须 exit 1 且不写帧：stdin 非 UTF-8、JSON 解析失败、非对象、非工具异常的未捕获错误。禁止把这些路径改成 emit。Duck 的版本/SHA 不符、扩展装不上、`platform_unpinned` 同样无成功帧、退出 1，原因打 stderr。检查：行为 B5/C8/F8；source F2。

**TP-WIRE-5** 桥只读首行（第一个 `\n` 之前）。禁止挂起等第二帧。第二帧不得被当成结果。检查：行为 B5/C8/F8；source `run_line_json`。

**TP-WIRE-6** 进程内 Python 口岸不伪造线协议。成功返回字符串；失败抛稳定 `ReadError(code, message)`，`code` 属于 headless 闭集。禁止向 stdout 写 `{"ok":...}`。检查：gate A；行为经 hub 的 D 组。

## 4. 围栏与文本安全

**TP-FS-1** 空白或非字符串的 root 或 path 必须 `invalid_params`，且发生在任何 `realpath`、`realpathSync`、`URL(fileURLWithPath:)` 之前。`""` 与 `"   "` 都是空白。Swift 的检查必须在 `resolvePath` 开头，禁止靠 joinPath 补救。Pi 的检查必须在 `resolveFenced` 调用 `realpathSync(root)` 之前。今天空白 root 落 CWD 或 `read_failed` 都不符合本条。检查：gate B8/C6/F6。

**TP-FS-2** realpath 系 OSError（环路、EACCES，以及平台等价错误）必须映射为 `read_failed`。子进程退出 3。禁止裸 OSError 冒泡为退出 1。Python/duck 把 `realpath` 包进该映射；Swift/Pi 用各自平台 API 达成同表。A 组是进程内，断言最终 `ReadError.code==read_failed`，覆盖「realpath 即抛」与「open 才失败」两条路径。`os.geteuid()==0` 时打印 `[SKIP] A13 euid=0`，不因此退出 2；`finally` 必须恢复权限。平台不能建 symlink 环时，只跳过该 case 并打印原因，禁止跳过整组。检查：gate A13；子进程退出 3 由 F6 锁。

**TP-FS-3** 围栏是 canonical 前缀：`realpath` 之后 `checked == root_real` 或 `checked.startswith(root_real + sep)` 才在围栏内。相对路径拼到 realpath 之后的根上，不先查存在。`~` 禁止展开；`~/…` 是相对字面量，那个路径不存在必须 `read_failed`，且结果不得是家目录文件正文。检查：gate A10/A11/B8/C6/F6。

**TP-FS-4** 路径含 U+0000（含 `a\0b`）必须 `path_outside_workspace`，在 realpath 之前。禁止并进 `invalid_params`。message 禁止回显该 NUL 字节。检查：gate B4/B8/C6/F6。

**TP-FS-5** 严格 UTF-8 解码成功后、任何切分或 parse 之前，正文含 U+0000 必须 `read_failed`，message 固定为 `contains NUL`，禁止回显字节。解码失败仍是 `read_failed` / `not utf-8`，即使字节同时含 `0x00`。四个口岸同一规则。hub 兜底见 TP-HUB-3。检查：gate A12（tmp `b"a\x00b"`）、B4 扩（Swift 同码、退出 3）、C10（Pi 同码、payload 无 `result`、JSON 文本无原始 NUL）、F9 扩（`.py` 含 NUL → `read_failed` 非 `parse_failed`）。fixture 在 tmpdir 生成，禁止提交二进制。

**TP-FS-6** 看似 JSON 的正文仍是字符串。成功帧的 `result` 禁止变成对象。检查：gate A/B 成功帧 `result` 为字符串。

**TP-FS-7** duck 错误优先级固定，禁止重排：形状（空 stdin、缺 path、空 path、类型不对）→ 围栏 → 语言 → 读/解码 → render。根内缺 `.txt` 必须 `language_unsupported`；缺 `.py` 必须 `read_failed`；根外 `.png` 必须 `path_outside_workspace`；受支持扩展的 NUL 或非 UTF-8 必须 `read_failed`，禁止 `parse_failed`。检查：gate F5/F6/F9；source F5b（`def main` 之后切片里 `language_for(` 的下标早于 `read_utf8(`）。

**TP-FS-8** B8、C6、F6 共用输入矩阵，期望码相同：相对 fixture 成功；`foo/../fixture` 成功；`../../etc/hosts` 与 `/etc/hosts` 为 `path_outside_workspace`；路径 `a\0b` 为 `path_outside_workspace`；path 或 root 为 `""` / `"   "` 为 `invalid_params`；`~/…` 为 `read_failed` 且不是家目录正文；根内 symlink 指向根外为 `path_outside_workspace`；tmpdir symlink 环为 `read_failed`（不能建环则单 case 跳过）。进程内 Python 与 duck 同码；子进程退出 3。检查：gate B8/C6/F6。

**TP-FS-9** 四份围栏必须独立源码：`read_contract.resolve_path`、Swift `resolvePath`、Pi `resolveFenced`、duck 的 resolve。禁止抽共享围栏模块。duck 禁止 `import read_contract`。相等由 TP-FS-8 的断言锁，不由共享代码锁。检查：source F2（不含 `read_contract`）；gate B8/C6/F6。

## 5. 平面与整数

**TP-TEXT-1** headless 切分以 `read_text` 为 oracle。换行类必须逐字符切 U+000A、U+000B、U+000C、U+000D、U+0085、U+2028、U+2029。Python 必须是 `re.split(r"[\n\r\v\f\x85\u2028\u2029]", text)`。禁止 `splitlines()`，禁止只 `split("\n")`。字节 `alpha\r\nbeta\r\n` 必须得到 `alpha\n\nbeta\n\n`。幻影尾：`hello.txt` 是 `line one\nline two\nline three\n`；尾换行留下空元素；`start_line=-1` 必须是 `""`；`start_line=-2` 忽略 limit，必须是 `line three\n`。`start_line=0` 与负 limit 的结果必须等于现行 `read_text`（0 落到首行起；负 limit 经 `max(0, limit)` 得空切片），禁止另立语义。不是 app 窗口版 `read_file`：禁止移植 10MB 帽、二进制探测、选区副作用、`ReadFileReply`、`offset` 别名；禁止把 `offset` 映射成 `start_line`。`crlf.txt` 的 `text` 属性必须 unset。检查：gate A4/A7/A8/B2/B2b/B3；manual：`git check-attr -a -- v13/read_tools/fixtures/crlf.txt` 必须显示 `text: unset`。

**TP-TEXT-2** Pi 文本只按 `"\n"` 切。空正文的计行结果是 `[]`；以 `\n` 结尾则丢掉末空元素（与 headless 幻影尾不同，这是显式偏差）。`crlf.txt` 全文不得等于 `alpha\n\nbeta\n\n`。`truncateHead` 控制流照抄上游。`limit` 键缺失，以及口岸把 `limit: null` 归一成缺失，才走默认帽（2000 行 / 51200 字节）。禁止向 Node 送 JSON `null` 的 `limit`。围栏成功后，扩展名去点、大小写不敏感，属于 `{jpg,jpeg,png,gif,webp,bmp}` 必须 `image_unsupported`，结果禁止含文件字节。不复制 TUI、高亮、`processImage`。C1b 仍是 Pi offset 矩阵，不是安全整数断言。检查：gate C1/C1b/C9/C3。

**TP-INT-1** headless 与 Swift 的可选整数域是 `[-(2^53-1), 2^53-1]`（即 `[-9007199254740991, 9007199254740991]`）。区间外整数、小数、指数、bool、字符串当缺省。`1.0` 禁止收成 1。Python `_optional_int` 必须拒 `abs > 2**53-1`（bool 已拒；非 `int` 含 float 返回缺省）。Swift `optionalInt` 必须拒 float 型 `NSNumber`（`CFNumberIsFloatType`，Foundation 重导出，不新增包）与超安全区间。经桥的判别用例，Swift 必须等于同参 `read_text`：`start_line=1.0, limit=1` 得全文（若收成 1 则得首行，蒙混不过）；`start_line=1.5` 且 limit 缺省得全文；`start_line=2, limit=1.0` 得第 2 行到文末；`start_line=2**53-1, limit=1` 得 `""`；`start_line=2**53, limit=1` 得全文；`true` 与 `"2"` 得全文。禁止用分不出「缺省 vs start=1」的全文 fixture 充当 `1.0` 用例。B2 在既有 `((2,2),(-1,None),(99,None))` 上必须加 `(0,None),(1,None),(1,0),(-2,1),(2,0)`。B2b：空文件与无尾换行 `one\ntwo`，Swift 等于 Python。检查：gate A14、B2 扩、B2b、B2c。

**TP-INT-2** Pi 不参加 TP-INT-1。`takeInt` 仍收有限整数；负 offset 依赖它，禁止改 `takeInt`、禁止把负 offset 归一。检查：gate C1b；source `takeInt`。

**TP-INT-3** Pi 在使用 limit 之前，必须把负整数 limit 归一为 0，走既有 `limit=0` 路径（空切片 + more-lines 文案）。offset 负数不归一。相对上游 JS `slice` 这是显式偏差，台账必须有「Pi 偏差」句（行为句由里程碑 F 与代码同笔写入）。`limit=-1` 与 `limit=-99` 的 result 都必须等于 `limit=0` 的字符串，且不含 `line one`。检查：gate C3e。

**TP-INT-4** `formatSize` 只许两臂：`< 1024` 为 `{n}B`；`>= 1024` 一律 `{bytes/1024.toFixed(1)}KB`，含 ≥ 1MiB。禁止 MB 臂。证据是上游 `truncate.ts` 的 `formatSize`（`@earendil-works/pi-coding-agent` 0.80.3）。实施核对时若该函数已不是两臂，或超长首行的 sed 提示不再渲染 KB，必须停手按实测重钉，禁止预设。1MiB 无换行文件的首行提示必须含 `1024.0KB`、不含子串 `MB`，`head -c` 长度仍是 51200。检查：gate C5b；source `formatSize`。

## 6. 子进程边界

**TP-SUB-1** `run_line_json` 是唯一子进程边界。argv 必须是列表；超时默认 30 秒；`capture_output`；只解析首行；失败封闭为 `ProtocolError`。进程内 `read_text` 不走此函数。检查：source G2；行为 B5/C8/F8。

**TP-SUB-2** 禁止 `shell=True`。本版不加 `env=`，不改 cwd。`DUCKDB_EXTENSION_DIRECTORY` 是惰性的，禁止把「清洗 env」写成装载修复。改签名、env 或 cwd 是合同变更，必须 bump 版本，不是口岸修复。检查：source `bridge.py`；source F2。

**TP-SUB-3** 外部 IO 不得在数据库事务内执行。读盘发生在 claim 已提交、complete 未开启之间。检查：source D14；gate D。

**TP-SUB-4** 子进程超时必须回收子进程并映射为 `protocol_error`。spawn 的 OSError 同样映射为 `protocol_error`。禁止把超时当成工具错退出 3。检查：行为 B5/C8/F8；source `run_line_json`。

## 7. 判断面、环与 hub

**TP-HUB-1** 目录与策略只活在会被 `setup_db` DROP 的库 `agent_v13_read_tools`。种子 `turn_budget.max_cycles` 保持 3，禁止改种子文件。负例仍在种子 3 上跑三条 tool route 后撞墙。幸福路径是 `tool×4 + llm + finish` 共 6 条 route，finish 在 `cycle_no=5` 发出，所以同一事务把 `turn_budget` 从 3 翻到 `max_cycles=6`；翻成 5 会在 finish 前撞 `budget_exhausted`，禁止。策略 v2 复制 v1 带后追加恰好 8 条：`param::` / `stated::` 各一对，工具名为 `read_pi`、`read_file_swift`、`read_file_py`、`read_duck`，信号形如 `param::read_duck::path`。每条 `band_no=1, lo=0.60, hi=Infinity, action=pass`。运行时 INSERT/DELETE 不改种子。检查：gate D3/D7；source G2。

**TP-HUB-2** `beat` 结算顺序必须是：`v13_complete` → 先断言 `got=="accepted"` → `commit` → `completed=True`。accepted 不成立时事务仍开，`finally` 回滚后结算 `failed` 或 `protocol_error`，异常冒泡，进程退出 1。禁止先写 `completed=True` 再看 accepted。检查：source D14 扩（`inspect.getsource(beat)` 中 `got == "accepted"` 的下标早于 `completed = True` 与其后的 `conn.commit()`）；gate D。

**TP-HUB-3** hub 在调用 `v13_complete` 之前必须过 `jsonb_safe_result(status, payload)`。三行表：成功串含 NUL → `failed` 且 payload 为 `{"error":"read_failed","message":"contains NUL"}`；成功串无 NUL → 原样；失败对象的字符串含 NUL → 该字符串换成 `contains NUL`。环上 D17：独立 session，判断面仍选闭合选项，hub 只在这一拍把 path 换成 tmp 的 NUL 文件路径；`effects.status='failed'`，`result->>'error'='read_failed'`，无 `tool/result`，session 不进终态。用户消息必须是未用过的句子（如 `Read the zero byte token file`）。mode 复用 `literal`，swap 手法同 D15/D16。检查：gate G3（`--contract` 也跑）、D17。

**TP-HUB-4** `TICK_CAP=24`，`EXPECTED_TICKS=17`（现 16 拍加 D17 一拍）。守卫 `<= TICK_CAP`，且末尾精确 `== EXPECTED_TICKS`。余量必须 `>= 4`（24 ≥ 17+4）。实跑 `[beat]` 行数不是 17 时，以实跑数为准同笔改常量与本句，禁止放宽成不等式。检查：gate D18。

**TP-HUB-5** `judgment_cache` 按 `request_hash` 全局只写一次，不看本次 mock。场景化用户消息必须互异。负例是 `Read hello.txt`；幸福路径是 `Read hello.txt and fib.py`；失败场景另用新句子。禁止复用已缓存的用户消息去「证明」下一拍问到了模型。检查：gate D；source 各场景消息字面量。

**TP-HUB-6** 重复 complete 是 replay。旧 fence 是 stale。本地读失败必须 `complete failed`，禁止 `unknown`。失败不追加 `tool/result`，session 不因这一拍进入终态。检查：gate D7/D15/D16/D17。

**TP-HUB-7** E1 必须 `end_rev == after_rev + len(TOOL_ROWS)`。现 `TOOL_ROWS` 长度为 4，所以增量是 +4；四名字已不在，count 回到基线。实跑若非 +4，必须停下读 `v13_tools_bump` 定义，再同笔改本句与断言。禁止改成 `>=`。检查：gate E1。

## 8. gate 与 preflight

**TP-GATE-1** 分级：A 无依赖，始终跑。B 依赖 swift。C 依赖 node。F 依赖 duck：`ok` 与 `unpinned` 都跑 F，`unpinned` 由 F1 以 `platform_unpinned` 失败、退出 1；仅 `absent` 跳过 F。G 无依赖，最先跑，缺席时也必须跑。ring 需要全部平面；有跳过则不跑 ring，SKIP 行含 `ring`，且不跑 E4。`--contract` 跑 A–C、F、G，不跑 ring、不跑 E4。无旗标才在 ring 之后跑 E4。检查：gate G1。

**TP-GATE-2** `classify_planes(swift_ok, node_ok, duck_status) -> list[str]` 是纯函数。`duck_status` 只许 `ok` / `absent` / `unpinned`。`unpinned` 不列入跳过。至少：

| swift | node | duck | 跳过 |
|---|---|---|---|
| 在 | 在 | absent | `[duck]` |
| 在 | 在 | ok | `[]` |
| 缺 | 在 | ok | `[swift]` |
| 在 | 缺 | ok | `[node]` |
| 在 | 在 | unpinned | `[]` |

`exit_for(skipped, failed)`：`failed` → 1；`skipped` 非空 → 2；否则 0。至少 `([], False)==0`、`(["duck"], False)==2`、`(["duck"], True)==1`。断言失败退出 1，优先于缺席退出 2。退出 2 不是通过。先跑绿 Python 再退出 2 不算通过。检查：gate G1。

**TP-GATE-3** `main` 顺序：`run_g()`（G1+G2+G3）→ `run_a()` → swift 在则 B、node 在则 C → duck 为 ok 或 unpinned 则 F → 无 `--contract` 且跳过为空才 ring → ring 跑完且无跳过才 E4 → `AssertionError` 打印并返回 1 → 跳过非空则打印含 `[SKIP] not_run/toolchain_absent` 与 `planes=` 后缀并返回 2 → 否则 0。文首 docstring 必须写「能跑的组先跑；断言失败退出 1；有跳过才退出 2」。DB setup/connect 失败只许包装为 `RingInfrastructureError`，禁止用 `OperationalError` 类名字符串判断，禁止吞其他 traceback。检查：gate G1；source `main`。

**TP-GATE-4** E4 进无旗标全量 gate。ring 全部连接关闭后启动。发现命令必须是 `find v13 -name 'test_*.py' -not -path 'v13/read_tools/*' | sort`。禁止写死条数（冻结时清单为 25，含 acl/observe；条数变化不构成豁免，也不构成跳过）。逐个 `uv run python <路径>` 串行，记录 `路径 → 退出码`。任何非零即红。不重试，不豁免，不缓存。用该次输出刷新 README 的 E4 表。超时即失败。排除 `v13/read_tools/*` 以防递归。检查：gate 无旗标全量的 E4 段；manual（F 落地前）：同一发现命令，逐个 `uv run python <路径>`，全部退出 0。

**TP-GATE-5** `duck_probe()` 是短命子进程：`.duck-venv/bin/python` 只 `import duckdb`、`connect(":memory:")`、打印 `__version__` 与 `PRAGMA platform`，禁止 LOAD。venv 或解释器缺失，或该平台扩展文件缺失 → `absent`。版本 ≠ `1.5.5` → 不是 absent，F1 失败退出 1。`PRAGMA platform` 不在 `PINS_BY_PLATFORM` → `unpinned`（F 照跑，退出 1）。新平台不是静默加一行缓存，见 TP-SNAP-3。检查：gate G1/F1。

**TP-GATE-6** G2 必须执行：`git diff --name-only HEAD -- v13 pyproject.toml uv.lock` 与 `git ls-files --others --exclude-standard` 的同范围并集，禁止出现 `v13/load.py`、`pyproject.toml`、`uv.lock`、`v13/**/*.sql`。并断言 `os.path.isfile('docs/designs/v13-tool-ports.md')`。失败必须打印路径。README 必须写「原 E2 由 G2 执行」（该句由 F 与代码同笔写入）。检查：source G2。

## 9. duck 供应链

**TP-DUCK-1** pin 的唯一来源是 `PINS_BY_PLATFORM`，键是运行时 `PRAGMA platform`。当前唯一键 `osx_arm64`。`EXPECTED_DUCKDB_VERSION` 必须是 `1.5.5`。禁止第二张 SHA 表。禁止保留 `EXPECTED_PLATFORM` / `EXTENSION_CACHE` 作为 pin 源。顶层禁止 `import duckdb`（仓库 venv 的测试要 import 本模块）。社区描述文件写的 sitting_duck 1.11.0、duck_block_utils 3.4.0 不是权威。`duck_block_utils` 的 v1.2.1 / `125662df` 是 v1.4.5 轨道，禁止当成本 pin。

| 组件 | 钉什么 | 值 |
|---|---|---|
| duckdb | `__version__` | `1.5.5`（wheel，不钉二进制） |
| sitting_duck | `extension_version` / SHA-256 | `b8c06a8` / `e031481f864f342b97deb1e985b6ff5f4b27a97de28d7ec37cf1ad64b6483176` |
| duck_block_utils | `extension_version` / SHA-256 | `39941a7` / `4a4f6ff8800c23e959198fa62c134da311acd82d81258f85c64aa16ef21cf529` |

检查：gate F1/F3；source F2/F10。

**TP-DUCK-2** `EXTENSION_ROOT` 是 `~/.duckdb/extensions`。连接必须是 `connect(":memory:", config={"extension_directory": str(EXTENSION_ROOT)})`。若该配置键被拒，连接后第一条语句必须是 `SET extension_directory`，仍先于一切 `LOAD`，并同笔改本句；禁止改回裸名 `LOAD`，禁止改去洗 env。然后 `SET autoinstall_known_extensions=false` 与 `SET autoload_known_extensions=false`。`PRAGMA platform` 不在表内必须 `fail_internal("platform_unpinned: …")`，退出 1，无成功帧。路径模板是 `EXTENSION_ROOT / "v1.5.5" / platform / f"{name}.duckdb_extension"`，目录名必须带 `v` 前缀。检查：gate F1/F2；source F2（含 `extension_directory`、`PRAGMA platform`、`platform_unpinned`）。

**TP-DUCK-3** 被哈希的文件必须就是被装载的文件。逐扩展：文件存在且 SHA-256 等于 pin → `LOAD '<绝对路径>'`（路径含 `'` 则 `fail_internal`，禁止手写转义）→ seal 之前查 `duckdb_extensions()`，断言 `loaded`、`extension_version` 等于 pin、且 `realpath(install_path) == realpath(被哈希文件)`。禁止裸名 `LOAD`（含 `LOAD sitting_duck` 与 `LOAD duck_block_utils`）。禁止只比 basename。`install_path` 经 symlink 回报 realpath，断言必须 realpath 对 realpath。不等则停，把实得路径写进失败信息。检查：gate F1；source F2（含 `install_path`，不含裸 `LOAD sitting_duck"` / `LOAD duck_block_utils"`，不含 `INSTALL `、`allow_unsigned_extensions`、`read_contract`）。

**TP-DUCK-4** seal 是 `SET enable_external_access=false` 且读回为假。seal 之后禁止再查 `duckdb_extensions()`（该设置下连此视图都抛 PermissionException；需要该视图的断言必须在 seal 之前——现有顺序正确，必须保留）。`main` 的 `finally` 必须关连接。读序必须是：解析帧 → `resolve_path` → `load_plane` → `language_for(resolved)` → `read_utf8` → `render`。读盘在口岸进程，不经过 DuckDB 文件面。管线必须是 `parse_ast($content, $lang, peek := 'full')` → `ast_to_blocks_from` → `duck_blocks_validate` → `duck_blocks_to_text`。禁止 `ast_to_blocks` / `ast_to_blocks_list`（内部走 `read_ast`，seal 后必失败）。禁止旧名 `db_blocks_to_text`。两个扩展都必须已 LOAD：`sitting_duck` 提供 `parse_ast` 与 `ast_to_blocks_from`，`duck_block_utils` 提供后两个函数。口岸禁止 import 仓库模块。检查：gate F5；source F5b/F2。

**TP-DUCK-5** bring-up 只走 community：`INSTALL sitting_duck FROM community` 与 `INSTALL duck_block_utils FROM community`。community 失败必须把错误打到 stderr 并 `sys.exit(1)`。禁止官方渠道回退，禁止 WARN 后退出 0，禁止 `used official`。venv 内解释器（`sys.path` 插入 `v13/read_tools`）必须 import `PINS_BY_PLATFORM` 与 `EXPECTED_DUCKDB_VERSION`，禁止第二张 SHA 表。装后按当前 `PRAGMA platform` 比对 SHA 与版本；不符或平台不在表内 → 退出 1，并打印期望与实得。`--verify-only` 不建 venv、不联网，只跑同一 verifier；venv 缺失时退出 1 并打印原因（基础设施错，禁止扮缺席跳过）。`main(argv)` 处理参数；未知 flag 非零并打印 usage。缓存若曾被 official 渠道填充，verifier 必须红：报 identity mismatch、保留文件、按 TP-SNAP-2 人工裁决，禁止自动删。检查：source F11（不含无 `FROM community` 的回退，不含 `used official`，含 `PINS_BY_PLATFORM`）；manual：`uv run python v13/read_tools/duck_bringup.py`（联网）；`uv run python v13/read_tools/duck_bringup.py --verify-only`（离线，退出 0 才算钉住）。

**TP-DUCK-6** `.duck-venv` 与仓库 venv 隔离，gitignore，禁止提交。fork dev 引擎与 released `1.5.5` 禁止互载扩展。受保护路径相对本里程碑基线零 diff：`v13/**/*.sql`、`v13/load.py`、`pyproject.toml`、`uv.lock`。禁止为装 duckdb 改根依赖文件。仓库不分发 `.duckdb_extension` 二进制。检查：source G2。

## 10. 快照

**TP-SNAP-1** 渲染常量必须带版本标签。`PIN_LABEL` 固定为 `duckdb=1.5.5 sitting_duck=b8c06a8 duck_block_utils=39941a7`。`FIB_RENDER` 与 `JS_RENDER` 是实测快照；本版不改它们的值。幸福路径 `read_duck` 的解码值必须等于 `FIB_RENDER`，禁止按源码行或 README 列数重算。本地 sitting_duck checkout 与已装载的 `b8c06a8` 不是同一棵树，禁止拿 checkout 当 oracle。outline 不含 `print(fib(6))` 是实测结果，不是漏读。检查：gate F3/F10。

**TP-SNAP-2** 禁止自动改 pin 的命令。换 duckdb 版本、扩展 SHA 或 platform 之后，gate 必须红，由人重钉。升级演练必须按序做完，禁止跳步：干净环境 → community 安装 → 记录 platform、version、install_path、SHA → 人工审渲染差异 → **同一次提交**更新 manifest（`PINS_BY_PLATFORM`）、渲染常量、README、NOTICES → 三道验证全部退出 0：`uv run python v13/read_tools/test_read_tools.py --contract`、`uv run python v13/read_tools/test_read_tools.py`、`uv run python v13/read_tools/duck_bringup.py --verify-only`。检查：manual：上列演练；gate F3/F10（未演练时 pin 值不得变）。

**TP-SNAP-3** 新平台是独立规范变更，不是给缓存补文件。同一提交必须同时有：`PINS_BY_PLATFORM` 新键、该平台实测渲染快照（带新 `PIN_LABEL`）、NOTICES 归属。未进 manifest 的平台是 `unpinned`，不是 `absent`。检查：source F10；gate F1。

**TP-SNAP-4** duck 扩展在 NOTICES 里是信息性归属。必须补 SPDX 标识符与上游许可证 URL，指向文件内已有的 Apache-2.0 / MIT 全文，禁止再粘贴一遍全文。必须明示仓库不分发二进制。一旦把 `.duckdb_extension` 提交进仓库，同笔提交必须补上对应许可证全文。检查：source `THIRD_PARTY_NOTICES.md`；manual：评审对照本条。

## 11. 新口岸准入清单

**TP-ADMIT-1** 第五种语言（或同语言的第二个方言平面）必须在同一变更里交齐下列各项，缺一不准入。检查：manual：评审逐项对照。

1. 线协议：TP-WIRE-1 至 TP-WIRE-3；协议失败不写帧。
2. 闭集错误码，且不串已有平面的专有码。
3. 独立围栏源码，加对照矩阵，或书面偏差（偏差必须写进本规范并 bump 版本）。
4. 声明平面归属：并入已有相等平面，或独立平面并至少一条反合并断言。
5. 子进程只经 `run_line_json`；进程内只返回字符串或稳定类型化错误，不伪造帧。
6. 闭合 options，以及成对的 `param::` / `stated::` 带；root 由 hub 注入。
7. claim 提交之后、complete 开启之前做 IO；`finally` 兜底。
8. preflight 只跳自己的组；缺席是退出 2，不是通过。
9. 归属写入 `THIRD_PARTY_NOTICES.md`。
10. 零 SQL 文件、零 `SQL_LOAD_ORDER` 追加、零受保护路径改动。
