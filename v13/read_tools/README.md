# v13 read_tools

M1 离线契约。Python 与 Swift 在 headless 契约上相等；Node 的 Pi 口岸只对照 Pi 文本读矩阵。单 root。不 spawn `pi`，不 spawn `repoprompt-mcp`。

## Gate

```bash
uv run python v13/read_tools/test_read_tools.py --contract
uv run python v13/read_tools/test_read_tools.py
```

`--contract` 跑 A–C，退出码 0 为通过。无旗标在 M2 跑 A–E。

`swift --version` 或 `node --version` 失败：在 `setup_db` 之前、在任何绿色断言之前打印 `[SKIP] not_run/toolchain_absent` 并退出 2。先跑绿 Python 再退出 2 不算通过。退出 2 不是通过。断言失败退出 1。

## 工具链（R1）

2026-09-27 作者机实测：

- `swift --version`：swift-driver version 1.148.6，Apple Swift version 6.3.2 (swiftlang-6.3.2.1.108 clang-2100.1.1.101)
- `node --version`：v24.13.1

前置：macOS 上的 `swift` 与 `node`。M1 不需要 PostgreSQL。

## 行 JSON 与退出码

Swift 与 Node 共用一帧一行 JSON，换行结尾。正文在 JSON 字符串里转义，帧仍是一行。

| 结果 | stdout | 退出码 |
|---|---|---|
| 成功 | `{"ok":true,"result":"<text>"}`，`result` 是字符串，含 `""` | 0 |
| 工具错误 | `{"ok":false,"error":"<code>","message":"<detail>"}` | 3 |
| 空或全空白 stdin | `invalid_params` | 3 |
| 坏 JSON、未捕获异常 | 脚本 `exit(1)` | 1 |

桥：退出码不在 `{0, 3}`，或读不到帧（EOF），一律 `protocol_error`。成功帧要求 `ok=true` 且 `result` 为字符串；退出码 3 要求 `ok=false` 且 `error` 为字符串。退出码 0 仅当 `ok=true`。旗标不一致也是协议错误。不挂起等第二帧。Swift 发帧用 `FileHandle.standardOutput.write` 加单个 `0x0A`，不用 `print`。

## Headless

不是 app 窗口版 `read_file`。不要移植 10MB 帽、二进制探测、选区副作用、`ReadFileReply`、`offset` 别名。headless 返回纯字符串。不要把 `offset` 映射成 `start_line`。

换行类逐字符切：U+000A、U+000B、U+000C、U+000D、U+0085、U+2028、U+2029。Python 必须是 `re.split(r"[\n\r\v\f\x85\u2028\u2029]", text)`。禁止 `splitlines()`，禁止只 `split("\n")`。

字节 `alpha\r\nbeta\r\n` → `alpha\n\nbeta\n\n`。

幻影尾：`hello.txt` 是 `line one\nline two\nline three\n`。尾换行留下空元素，`start_line=-1` → `""`。`start_line=-2` 忽略 `limit`，得到 `line three\n`。

单 root。线协议只有一个 `root`。相对路径拼到 realpath 之后的根上，不先查存在。`~/hello.txt` 不展开，当相对字面量；那个目录不存在就是 `read_failed`。

## Pi 偏差

相对上游 `read.ts` / `truncate.ts`（`@earendil-works/pi-coding-agent` 0.80.3）：

- 显式 `root` 围栏：`fs.realpathSync` 加前缀检查。不调用 `resolveReadPathAsync`，不展开 `~`。`../` 与根外绝对路径是 `path_outside_workspace`。
- 围栏成功后，扩展名（大小写不敏感）属于 `{jpg, jpeg, png, gif, webp, bmp}` 即 `image_unsupported`。结果里不放文件字节。不复制 TUI、高亮、`processImage`。
- 文本只按 `"\n"` 切，所以 `crlf.txt` 全文不得等于 `alpha\n\nbeta\n\n`。

`truncateHead` 控制流照抄 `truncate.ts`。`limit` 键缺失，以及口岸把 `limit: null` 归一成缺失，才走默认帽。不要向 Node 送 JSON `null` 的 `limit`。

## CRLF fixture

`.gitattributes` 是仓库根新建文件，唯一一行 `v13/read_tools/fixtures/crlf.txt -text`。

```text
$ git check-attr -a -- v13/read_tools/fixtures/crlf.txt
v13/read_tools/fixtures/crlf.txt: text: unset
```
