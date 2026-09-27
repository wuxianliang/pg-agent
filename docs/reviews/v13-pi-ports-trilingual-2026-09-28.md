# v13 pi_ports 三语言差异对照（2026-09-28）

本轮把 `read_pi_ext` / `read_pig` / `read_piswift` 接进 seam 真实 turn，并对照三口岸与三框架源码。行号是本工作区与本地 checkout 的当前文本。未实测的时长不写成数字。

## Gate

工作区 `v13-pi-ports`，命令在仓库根、`UV_FROZEN=1`。时间是 UTC。

| 命令 | 退出码 | 计数 | 墙钟 |
|---|---|---|---|
| `uv run python v13/pi_ports/test_pi_ports.py` | 0 | 302 PASS，0 FAIL，0 SKIP | 20:17:22–20:18:03（41s） |
| `uv run python v13/read_tools/test_read_tools.py --contract` | 0 | 237 PASS，0 FAIL，0 SKIP | 20:18:03–20:18:22（19s） |
| `uv run python v13/read_tools/test_read_tools.py` | 0 | 末行 `[PASS] E4`；子进程 `[E4] v13/pi_ports/test_pi_ports.py → 0` | 20:18:22–20:23:59（337s） |

环日志（同一次 pi_ports 运行）：

```
[ring] read_pi_ext direct_len=29
[ring] read_pig direct_len=29
[ring] read_piswift direct_len=29
[beat] tool worker:read_pi_ext
[beat] tool worker:read_pig
[beat] tool worker:read_piswift
[beat] llm None
```

`direct_len=29` 与 fixture `hello.txt` 的字节数一致（`line one\nline two\nline three\n`）。H3/H4 要求落库 `tool/result` 与 `effects.result #>> '{}'` 等于这次直跑，按 `tool_name` 对齐，不按 `created_at` 排序。三平面都过了。同一次运行还过了 JS-F2、JS-TAKE、JS-BODY、GO-BODY、SW-NUL、Hoverride。R0/R1 目录行 roundtrip 仍在，没有拿环替换掉。

无旗标全量的 PASS 行数含 E4 子进程，不能当成 read_tools 自身断言数。合同面仍是 237 PASS，与接环前台账一致。

## 框架入口

| 平面 | 调用 | 版本证据 | 集成 |
|---|---|---|---|
| pi TS | `createReadTool(rootReal)` 然后 `execute`。口岸 `v13/pi_ports/read_pi_ext.mjs:158-160`。框架函数 `packages/coding-agent/src/core/tools/read.ts:201` | checkout `package.json` `"version": "0.87.1"`。证据行带 `version=${piVersion()}`，gate 针 `version=0.87.1`（EVID PASS） | `node --experimental-strip-types` 直接 import checkout 源码。`package.json` 把 `@earendil-works/pi-agent-core` / `pi-ai` / `pi-tui` 钉在 0.87.1，供 renderer 图。`pi_resolve_hook.mjs` 把同名 workspace 包指回 checkout `src/index.ts` |
| PiG | `coding.NewSession`（`ActiveBuiltinTools: {"read"}`）→ `sess.Tools()` 取 `Name()=="read"`。`v13/pi_ports/pig_port/main.go:224-232`。证据行 `main.go:87` 写 `execute=agent.AgentTool.Execute`，GO-EVID PASS | `coding/pigversion/pigversion.go:7-17`：`PigVersion="0.2.0"`，`UpstreamVersion="0.87.1"`，`Version = PigVersion + "+" + UpstreamVersion`。gate 针 `version=0.2.0+0.87.1` 与 `go_list=v0.2.0` | `go.mod` `require ... v0.2.0`，`replace github.com/MichaelKinsy/PiG => /Users/wxl/Projects/PiG`（`go.mod:51`）。他机不能独立构建 |
| PiSwift | `createReadTool(cwd:)`，`Sources/PiSwiftCodingAgent/Core/Tools/ReadTool.swift:48`。口岸证据 `main.swift:293-296` 写 `execute=AgentTool.execute`，SW-EVID PASS | `Sources/PiSwiftCodingAgent/Config.swift:6` `VERSION = "0.87.1"` | `Package.swift:8` `.package(path: "/Users/wxl/Projects/PiSwift")`，tools 6.2，macOS 15。他机不能独立构建 |

三口岸都把围栏后的绝对路径交给框架。不把调用方原始 `req.path` 交给 `resolvePath`，所以框架侧的 `~` 展开不会再发生。

## 语义差异

### CRLF

- pi：`textContent.split("\n")`（`read.ts:136`）。按 `\n` 切，行上的 `\r` 留下。
- PiG：`strings.Split(textContent, "\n")`（`internal/codingagent/tools/read.go:102`）。同样保留 `\r`。
- PiSwift：`split(separator: "\n", omittingEmptySubsequences: false)`（`ReadTool.swift:113`）。按字素切。`\r\n` 是一个字素，CRLF 文件不会被切开，`limit` 因此失效。

Swift 口岸不改框架。已校验快照里的 `\r\n` 换成等长 `\0\n`，只把副本交给 `execute`，只在这条路径上把结果里的 `\0` 还原成 `\r`（`prepareFrameworkPath`，`main.swift:304` 起）。无 CRLF 不走副本。字面 `U+E000` 不改写（SW-E000 PASS）。

### 续读 trailer

- pi：`to continue.]`（`read.ts:169`、`:178`）。
- PiG：`to continue.]`（`read.go:144`、`:154`）。
- PiSwift：`to continue]`，无句号（`ReadTool.swift:149`、`:151`、`:158`）。

共享矩阵锁的是带句号的 pi 措辞。Swift 口岸只在最终单行 trailer 上补句号（`alignContractTrailer`，`main.swift:244-272`），三个锚定模式之外的正文不动（SW-TRAIL PASS）。不复制截断实现。

### 51200 帽的测量面

三框架的帽都是 `50 * 1024`，作用在 **offset/limit 切完之后的选中文本**，不是原始文件字节：

- pi：`truncate.ts:13` `DEFAULT_MAX_BYTES`，`truncateHead` 用 `Buffer.byteLength(content, "utf-8")`（`truncate.ts:82`）。
- PiG：`tools.go:31` `DefaultMaxBytes`，`TruncateHead` 用 `len(content)`（`truncate.go:161`）。Go string 的 `len` 是字节数。
- PiSwift：`Truncate.swift:4` `DEFAULT_MAX_BYTES`，`truncateHead` 用 `content.utf8.count`（`Truncate.swift:47`）。

ASCII 上三者对齐。非 ASCII 时测量面都是 UTF-8 字节，不是 UTF-16 码元，也不是 Swift 字素数。Swift 的 CRLF 字素切会让「一行」吞掉整个文件，帽因此打在未分行的块上；`\0\n` 副本是为了让切行和帽回到与 pi 相同的行面。SW-CAP 锁了 CRLF 文件的 51200/51201 边界，本轮 PASS。

### offset / limit 与越界

合同闭集相同：负 `limit` 在进框架前归一为 0，由 C3e / GO-C3e / SW-C3e 锁住（JS `read_pi_ext.mjs:226`，Swift `main.swift:409`）。GO-P2 留给 `offset=1e20` → `invalid_params`，不是负 limit。越界措辞都来自框架 `Offset … is beyond end of file`，口岸映射成 `offset_out_of_range`，其余框架错误收成 `read_failed`。

差异在参数面和正则锚：

- JS `takeInt` 丢掉非整数，不因此报 `invalid_params`。越界正则不锚定。
- Go `optionalInt` 要求有限且落在 `int` 内的精确整数，否则 `invalid_params`（`1e20` 是 GO-P2）。越界正则不锚定，同时看 Execute 错误和 `IsError` 的 `Content`。
- Swift 拒绝 bool 和非精确浮点。`2**53+1` 与 `2**63-1` 是 `offset_out_of_range`，`2**63` 是 `invalid_params`（SW-P2 PASS）。越界正则锚定整句（`main.swift:219`）。因此正文恰好是那句越界提示时仍当文本返回（SW-BODY PASS）。

判断面只有闭集 `hello.txt`。`../`、绝对路径、offset、limit、CRLF 只在口岸直跑，不进 mock judgment（TP-CAT-3）。

### 图像与非 regular 文件

框架自己会把图像做成附件（pi `read.ts` 的 image 路径；PiG `read.go` 的 image 结果；PiSwift `ReadTool.swift:100-110` 的 `.image` block）。行协议是文本帧，口岸不走那条路径。

- 三口岸都在调用框架前按扩展名 `{jpg,jpeg,png,gif,webp,bmp}` 返回 `image_unsupported`（JS `read_pi_ext.mjs`；Go `main.go:336`；Swift `main.swift:414`）。
- 三口岸都在读盘前拒绝非 regular：JS `fs.lstatSync` / `not a regular file`（`read_pi_ext.mjs:111`，JS-F2 锁 fifo 与 `/dev/zero`）；Go `os.Stat` + `IsRegular`（`main.go:181`，GO-F2）；Swift `lstat` + `S_IFREG`（`main.swift:201`，SW-F2）。
- JS 仍没有结果侧图像闸。Go 用 `len(result.Images)>0`（`main.go:273`）。Swift 用 `hasImageAttachment`（`main.swift:277`、`:365`）。

## 口岸工程差

### 围栏

- Node：`fs.realpathSync` 成功即绝对路径（`read_pi_ext.mjs:93`）。包含关系是 `checked === rootReal || checked.startsWith(rootReal + sep)`。
- Go：`filepath.EvalSymlinks` 不保证绝对，所以先 `filepath.Abs` 再 `EvalSymlinks`（`main.go:102-107`、`:148-152`）。包含关系用 `filepath.Rel`，拒 `..` 与 `../` 前缀，不用字符串前缀。
- Swift：先词法绝对化（不展开 `~`、不解链接），再 `realpath`，包含关系用相对路径分量（`main.swift:92`、`:168-178`）。不用字符串前缀。

### `~`

三口岸都不把 `~/file` 展开成 `$HOME`。它是 root 下的字面相对段。P0 在三平面都 PASS。

### 错误闭集与吸收点

口岸错误闭集：`invalid_params`、`path_outside_workspace`、`read_failed`、`offset_out_of_range`、`image_unsupported`。框架原生错误在口岸结果闸吸收，不原样出帧：越界正则命中 → `offset_out_of_range`；其余 → `read_failed`。围栏失败在进框架前结束。Swift 的锚定正则是吸收点收得更窄的一处，用 SW-BODY 锁住「正文碰撞」。

### evidence

成功读文本时 stderr 一行 `pi_ports evidence:`。

- JS：`path=fenced-absolute` 恒定（`read_pi_ext.mjs:160`）。
- Go：`path=fenced-absolute` 恒定（`main.go:87`），并带 `go_list=`。
- Swift：无 CRLF 副本时 `path=fenced-absolute`，走 `\0\n` 副本时 `path=fenced-derived-copy`（`main.swift:293-296`）。SW-CAP 锁了副本路径上不得出现 `path=fenced-absolute`。

## 构建与运行时

- 本轮 pi_ports gate 44s 跑完，含 warm `swift build` 与 `go build`。没有清 `.piswift-build`，**冷编译时长本轮未测**，不写秒数。
- `build_piswift` 的 `swift build` 超时是 600s（`test_pi_ports.py:1251`）。E4 每个子进程超时也是 600s（`test_read_tools.py` 的 `run_e4`）。冷编译若落在 E4 子进程里，可能被外层 600s 杀掉。因此构建目录必须先被本 gate 暖好，再跑无旗标全量。本轮顺序就是这样，E4 子进程 exit 0。
- 构建目录是仓库根 `.piswift-build`，不在 `v13/` 下。E4 的发现命令是 `find v13 -name 'test_*.py' -not -path 'v13/read_tools/*'`（`test_read_tools.py:65`）。SwiftPM checkout 若落在 `v13/` 内，其中的 `test_*.py` 会把全量打红。
- Go 是 `go build` 出一个二进制再被环调用。Node 没有单独编译步，每次 `node --experimental-strip-types` 启动。环上的超时是 JS 60s、Go/Swift 90s；claim 租约 120000 ms，避免 90s 子进程还在跑时租约先过期。

## 接环

`run_ring` 在 `agent_v13_pi_ports` 上再 `setup_db` 一次。在场平面各 INSERT 一行，`param_spec.options` 仍只有 `hello.txt`。`v13_submit_override` 的返回 seq 必须对上落库的一条 `goal/override`（`intent=direct`，Hoverride）。然后 `v13_parse` → `v13_advance` → `v13_claim('pi-ports-hub', 120000)` → 测试内 `dispatch_handler`。这个函数查的是进程内 `WORKERS` 字典，源码断言不含 `FROM tools`（H7）。它证明的是状态机与口岸适配器的 harness 集成，不是生产 worker 的注册或分发接线。`accepted` 检查、`conn.commit()`、`completed = True` 的顺序被 H8 锁住。effects 按 `tool_name` 对齐直跑结果，不依赖 `created_at` 顺序（H4）。三平面齐时 `turn_budget.max_cycles` 运行时提到 5（`n+2`）。工具行结束时 DELETE，revision 增量等于行数（H6）。零 SQL 文件改动，不改 `v13/load.py`。

## 结论

多语言 harness 论题成立，边界就是上面的差异清单。

成立的证据：三个口岸都经各自框架的原生工具入口（`createReadTool` / `coding.NewSession`+`Tools` / `createReadTool(cwd:)`）过同一契约矩阵。seam turn 里的 `dispatch_handler` 是测试内的 `WORKERS` 字典：它按冻结的 `request.handler` 把活叫到对应口岸子进程，证明的是状态机与适配器的 harness 集成，不是生产 worker 的注册或分发接线。落库 `tool/result` 等于同 argv 直跑。既有 read_tools 合同面与 E4（含本 gate 子进程）为零回归。

边界：CRLF 切行、Swift trailer 句号、51200 的测量 API、offset 正则锚与整数域、JS 没有结果侧图像闸、三套围栏、`~` 的字面语义、evidence 的副本标签。非 regular 预检三语言都已有（JS-F2 / GO-F2 / SW-F2）。这些是口岸适配，不是框架行为已经相同。

接受残留，本里程碑不改：

- `THIRD_PARTY_NOTICES.md` 只记载 `@earendil-works/pi-coding-agent` 0.80.3 用于 `v13/read_tools/read_pi.mjs`（该文件 `:218-222`）。0.87.1 活 checkout、PiG、PiSwift 没有条目。TP-ADMIT-1 的归属应在读过各 checkout LICENSE 之后另交，不在这里猜 SPDX，也不把 0.80.3 的 MIT 块挪来冒充。
- `go.mod` replace 与 SwiftPM `path:` 钉作者机绝对路径。与既有本地集成模型一致。
- 冷 Swift 编译时长未在本轮重测。
