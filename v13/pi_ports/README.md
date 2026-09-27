# v13 pi_ports

> 权威：口岸合同 `docs/designs/v13-tool-ports.md`（`v13/tool-port-contract-1`）。已交付 JS 与 Go 口岸。Swift 与三语言差异报告不在本轮。

独立库 `agent_v13_pi_ports`。`setup_db.py` 用 `load_stage(..., 'seam')`。工具行只在该库运行时 INSERT/DELETE。不改 `v13/**/*.sql`，不改 `v13/load.py`。

## Gate

```bash
UV_FROZEN=1 uv run python v13/pi_ports/test_pi_ports.py
```

node、本地 pi checkout、或 `v13/pi_ports/node_modules` 缺席，或 `go` / 本地 PiG checkout 缺席，则打印 `[SKIP] not_run/toolchain_absent` 并退出 2，不算通过。能跑的组先跑。断言失败退出 1。全绿退出 0。

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

## 环（本轮只到目录行）

`test_pi_ports.py` 的 R0/R1：`setup_db` 建库并加载到 seam，然后 INSERT `read_pi_ext` / `worker:read_pi_ext`，再 DELETE。Go 组同样 INSERT/DELETE `read_pig` / `worker:read_pig`。不跑完整 turn。完整接环留到三语言齐了之后。

## Go 口岸证据

模块：`v13/pi_ports/pig_port`。`go.mod` 用 replace 指向只读 checkout `/Users/wxl/Projects/PiG`，不改 PiG。本机 bootstrap `go` 可以低于 1.26；`toolchain go1.27.1` 由 `GOTOOLCHAIN=auto` 拉起，有效工具链须 ≥1.26。`go` 或 PiG checkout 缺席则 skip，退出 2。

公开面（外部 module 不能 import `internal/`）：

- `coding.NewSession`（`github.com/MichaelKinsy/PiG/coding`）构造会话时调用框架内建 read 工具
- `(*coding.Session).Tools` 取出名为 `read` 的 `agent.AgentTool`
- `agent.AgentTool.Execute` 收到的 `path` 是围栏规范化后的绝对路径

版本证据来自 `coding/pigversion.Version`（`0.2.0+0.87.1`）和 `debug.ReadBuildInfo` 的 module 版本（`go_list=v0.2.0`）。stderr 一行 `pi_ports evidence:`。

合同适配与 JS 口岸同一闭集：`~/` 不展开；负 `limit` 先归一为 0；图像扩展名在调用框架前返回 `image_unsupported`，不把字节放进帧。PiG 的 read 工具本身会把 jpg/png/gif/webp/bmp 做成 image attachment（`internal/codingagent/tools/read.go` 的 `readImage`）；口岸不走那条路径，因为行协议是文本帧。差异报告留到三语言齐了之后。
