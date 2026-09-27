# v13 pi_ports

> 权威：口岸合同 `docs/designs/v13-tool-ports.md`（`v13/tool-port-contract-1`）。已交付 JS、Go 与 Swift 口岸。差异报告：`docs/reviews/v13-pi-ports-trilingual-2026-09-28.md`。

独立库 `agent_v13_pi_ports`。`setup_db.py` 用 `load_stage(..., 'seam')`。工具行只在该库运行时 INSERT/DELETE。不改 `v13/**/*.sql`，不改 `v13/load.py`。

## Gate

```bash
UV_FROZEN=1 uv run python v13/pi_ports/test_pi_ports.py
```

node、本地 pi checkout、或 `v13/pi_ports/node_modules` 缺席，或 `go` / 本地 PiG checkout 缺席，或 `swift` / 本地 PiSwift checkout 缺席，则打印 `[SKIP] not_run/toolchain_absent` 并退出 2，不算通过。能跑的组先跑。断言失败退出 1。全绿退出 0。

首次装运行时依赖（只写本目录，不改 `/Users/wxl/Projects/pi`）：

```bash
npm install --prefix v13/pi_ports
```

`node_modules/` 已 gitignore。

## JS 口岸证据

脚本：`v13/pi_ports/read_pi_ext.mjs`。

本地 checkout `/Users/wxl/Projects/pi` 的 `@earendil-works/pi-coding-agent` 版本是 **0.87.1**（`packages/coding-agent/package.json`）。read_tools 的证据锚是 0.80.3；本口岸用活 checkout，不回退、不改框架仓库。checkout 没有 `dist/`，也没有 `node_modules`。

加载方式：

- `node --experimental-strip-types` 直接 import `packages/coding-agent/src/core/tools/read.ts`
- `pi_resolve_hook.mjs` 把裸说明符解析到本目录 `node_modules`（published 依赖，供 renderer 图用）
- 同名 workspace 包 `@earendil-works/pi-tui`、`pi-ai`、`pi-agent-core` 解析到 checkout 的 `src/index.ts`。published 0.87.1 的 `pi-tui` dist 不导出活源码里的 `colorToOkhsl`，所以不能用 registry 包冒充 checkout

框架调用（成功读文本时 stderr 有一行 `pi_ports evidence:`）：

- `createReadTool(rootReal)`，来自 `packages/coding-agent/src/core/tools/read.ts`
- 返回的 AgentTool 上调用 `execute("pi-ports-read", { path, offset, limit })`
- 截断与 `formatSize` 在框架 `truncateHead` / `read.ts` 内部，本口岸不复制这两段实现

合同适配（相对框架路径解析的显式偏差，与 read_tools Pi 偏差同一闭集）：

- 显式 `root` 围栏：`fs.realpathSync` 加前缀检查。`~/file` 是 root 下的字面相对路径，不展开 `$HOME`
- 不变量：`tool.execute` 收到的 `path` 是围栏规范化后的绝对路径，框架 `resolvePath` 对绝对路径不再做 `~` 展开，解析结果等于围栏验证过的路径。不把原始 `req.path` 交给框架
- 首行超限的 bash 提示里，框架会嵌入它收到的绝对路径。口岸只改写该提示中的路径为调用方原始 `path`，正文不改
- 围栏成功后，扩展名属于 `{jpg,jpeg,png,gif,webp,bmp}` 即 `image_unsupported`，不把字节放进结果，也不调用框架的 image 路径
- 读盘后做 fatal UTF-8 与 NUL 检查，再调用 `createReadTool`
- 负整数 `limit` 在调用框架前归一为 0
- `offset_out_of_range` 的识别正则钉在 checkout 0.87.1 `read.ts` 的措辞 `Offset .+ is beyond end of file`。升级 checkout 必须跟着改这处匹配
- 验证与框架读取之间的符号链接替换（TOCTOU）在本口岸威胁模型之外，与 read_tools 单进程合同一致。传入已 realpath 的绝对路径缩小了「校验后把链接改指向区外」的窗口：框架读的是当时解析到的 inode 路径，不再重新解析调用方的相对路径
- 目录符号链接加 `..`：`out/secret` 在 `out` 指向区外时是 `path_outside_workspace`；`out/../inside` 先按词法折叠 `..`，留在 root 内

帧协议与 read_tools 相同：一行 JSON，`writeSync` 发帧，成功退出 0，工具错误退出 3，坏 JSON 退出 1。

## 环

R0/R1 仍是目录行 INSERT/DELETE roundtrip：每个在场平面各自 `setup_db`，INSERT `worker:<name>`，再 DELETE。另外 `run_ring` 再 `setup_db` 一次，把在场平面放进同一个会话：每行先 `v13_submit_override`（`intent=direct`），然后 `v13_parse` → `v13_advance` → `v13_claim('pi-ports-hub', 120000)` → `dispatch_handler`（只看冻结的 `request.handler`，不查 `tools`）→ `v13_complete`。三平面齐时路由是 `tool, tool, tool, llm, finish`，运行时把 `turn_budget.max_cycles` 提到 `n+2`（三平面为 5）。落库的 `tool/result` 与 `effects.result` 必须等于同 argv 对 `hello.txt` 的直跑结果。工具行仍只在 `agent_v13_pi_ports` 运行时 INSERT/DELETE。

## Go 口岸证据

模块：`v13/pi_ports/pig_port`。`go.mod` 的 replace 钉的是作者机 PiG checkout 绝对路径，他机不能独立构建；这与既有的本地集成模型一致，不改 PiG。本机 bootstrap `go` 可以低于 1.26；`toolchain go1.27.1` 由 `GOTOOLCHAIN=auto` 拉起，有效工具链须 ≥1.26。`go` 或 PiG checkout 缺席则 skip，退出 2。

公开面（外部 module 不能 import `internal/`）：

- `coding.NewSession`（`github.com/MichaelKinsy/PiG/coding`）构造会话时调用框架内建 read 工具
- `(*coding.Session).Tools` 取出名为 `read` 的 `agent.AgentTool`
- `agent.AgentTool.Execute` 收到的 `path` 是围栏规范化后的绝对路径

版本证据来自 `coding/pigversion.Version`（`0.2.0+0.87.1`）和 `debug.ReadBuildInfo` 的 module 版本（`go_list=v0.2.0`）。stderr 一行 `pi_ports evidence:`。

围栏先 `filepath.Abs` 再 `EvalSymlinks`，包含关系用 `filepath.Rel`（`..` 或以 `../` 开头才拒）。字符设备、块设备、fifo 在读正文前 `Stat` 拒绝为 `read_failed`；普通文件仍全文校验后再交给框架，与 JS/Python 平面同性质。

合同适配与 JS 口岸同一闭集：`~/` 不展开；负 `limit` 先归一为 0；图像扩展名在调用框架前返回 `image_unsupported`，不把字节放进帧。PiG 的 read 工具本身会把 jpg/png/gif/webp/bmp 做成 image attachment（`internal/codingagent/tools/read.go` 的 `readImage`）；口岸不走那条路径，因为行协议是文本帧。差异见 `docs/reviews/v13-pi-ports-trilingual-2026-09-28.md`。

## Swift 口岸证据

包：`v13/pi_ports/piswift_port`。`Package.swift` 以本地路径依赖作者机 PiSwift checkout（`/Users/wxl/Projects/PiSwift`），他机不能独立构建；这与 Go 口岸的本地集成模型一致，不改 PiSwift。平台要求 macOS 15+ / Swift 工具链 6.2+。`swift` 或 PiSwift checkout 缺席则 skip，退出 2。gate 用 `swift build --build-path <repo>/.piswift-build`（仓库根，已 gitignore）。不能把构建目录放在 `v13/` 下：`test_read_tools.py` 的 E4 会 `find v13 -name test_*.py`，SwiftPM checkout 里的 `test_*.py` 会把全量 gate 打红。

公开面（外部 package 可 import，不改框架）：

- `createReadTool(cwd:)`（`PiSwiftCodingAgent`，`Sources/PiSwiftCodingAgent/Core/Tools/ReadTool.swift`）
- 返回的 `AgentTool.execute`（`PiSwiftAgent`）收到的 `path` 是围栏规范化后的绝对路径
- 版本常量 `PiSwiftCodingAgent.VERSION`（`Sources/PiSwiftCodingAgent/Config.swift`，本 checkout 为 `0.87.1`）

stderr 一行 `pi_ports evidence: module=PiSwift version=<VERSION> function=createReadTool tool=read execute=AgentTool.execute path=fenced-absolute`。

围栏先词法绝对化（不展开 `~`、不解符号链接），再 `realpath`，包含关系用相对路径（`..` 或以 `../` 开头才拒），不用字符串前缀。`~/file` 是 root 下的字面相对路径。非 regular 文件（目录、fifo、设备）在读正文前拒绝为 `read_failed`。

合同适配与 JS/Go 同一闭集：负 `limit` 先归一为 0；`offset`/`limit` 键存在但非整数、NaN/Inf 或超 `Int` 范围 → `invalid_params`；图像扩展名在调用框架前返回 `image_unsupported`，框架结果里的图像附件再做一道闸。`offset_out_of_range` 的识别正则钉在 PiSwift 0.87.1 `ReadTool.swift` 的措辞 `Offset .+ is beyond end of file`。升级 checkout 必须跟着改这处匹配。

PiSwift 0.87.1 的续读提示是 `to continue]`，共享矩阵锁的是 pi TS 的 `to continue.]`。口岸只在最终单行 trailer 上补这个句点，不复制截断实现。

PiSwift 的 `split(separator: "\n")` 按 Swift 字素切。`\r\n` 是一个字素，CRLF 文件不会被切开，`limit` 因此失效。探测：`String(contentsOfFile:encoding: .utf8)` 对含 `U+0000` 的文件成功并保留该标量；`ReadTool.swift` 的文本路径就是这个 API，之后没有 NUL 拒绝。因此口岸用字节中性替换：已校验快照里的 `\r\n` 换成 `\0\n`（等长），只把该副本交给 `execute`，并且只在这条副本路径上把结果里的 `\0` 还原成 `\r`。无 CRLF 的文件不走副本，字面 `U+E000` 不会被改写。evidence 在副本路径上写 `path=fenced-derived-copy`，否则 `path=fenced-absolute`。副本写失败是 `read_failed` 帧、退出 3。差异见 `docs/reviews/v13-pi-ports-trilingual-2026-09-28.md`。
