# v13 read_tools

M1 离线契约。Python 与 Swift 在 headless 契约上相等；Node 的 Pi 口岸只对照 Pi 文本读矩阵。单 root。不 spawn `pi`，不 spawn `repoprompt-mcp`。

## Gate

```bash
uv run python v13/read_tools/test_read_tools.py --contract
uv run python v13/read_tools/test_read_tools.py
```

`--contract` 跑 A–C，退出码 0 为通过。无旗标跑 A–E，退出码 0 为通过。

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

## 环

三个 `kind='tool'` 行只在库 `agent_v13_read_tools` 里运行时 INSERT/DELETE。不写入 `v13_core.sql`，不追加 `SQL_LOAD_ORDER`，不改 `v13/**/*.sql`。`setup_db` 用 `load_stage(..., 'seam')`。hub 只按冻结的 `request.handler` 分派，不查活 `tools` 表。读盘在 `v13_claim` 已提交、`v13_complete` 未开启之间。

ch8 练习 3：用 `tools.handler` 加一种 handler，只 INSERT 目录行再起进程，跑通一个 turn。这个练习改了几个 SQL 文件？答案是零 SQL 文件。

预算 v2（`turn_budget.max_cycles=5`）和路由策略 v2 只活在会被 `setup_db` DROP 的库 `agent_v13_read_tools` 里，不进入其他 stage 的库。

## 偏差台账

### P1

活体 `v13_needed_judgments`（`v13/triage/v13_triage.sql:1005`）在无 `goal/override` 的根会话上多发一个 `triage` choice。`v13_triage_steer` 在没有 `triage` pass 带时对根会话 fail-closed，enqueue `human` / `triage_fail_closed`。种子 v1 与本 stage 的 v2 都不加这条带（D2 仍是 v1 带数 + 6）。环上每个 session 在首次 `v13_parse` 前调用 `v13_submit_override`，`intent=direct`。这让 `v13_triage_decide` 返回 `direct`，并抑制 `triage` 信号。不改 SQL 文件。

### P2

计划钉的行号与加载清单有漂移，以实施时核对为准：

- `v13_complete` 活体在 `v13/seam/v13_seam.sql:409`（计划写 419）。判定串是 `v13_record_worktree_released`。
- `v13_advance` 活体在 `v13/triage/v13_triage.sql:561`，含 `WHEN 'finish'` 与 `v13_triage_prework`。`v13_claim` 在 `v13/fanout/v13_fanout.sql:266`。`v13_closeout` 在 `v13/spawn/v13_spawn.sql:585`，`turn/end.delivered` 在 `:748`。
- `SQL_LOAD_ORDER` 现为 22 项，末项是 `v13/catalog/v13_catalog.sql`。`STAGE_THROUGH['seam']=21`，`load_stage(..., 'seam')` 仍停在 seam，不加载 catalog。计划写的「21 项、末项 seam」已过期。
- `turn_budget` 种子仍是 `{"max_cycles": 3}`（`v13/schema/v13_core.sql:753`）。`batch_questions` 仍是 32。加载到 seam 后 `tools` 基线是 7 行，含 `spawn_subsession`。裸根会话的 needed 是 10，不是计划写的 9（多一条 P1 的 `triage`）；D3 量的是插入前后的差 +6，不把 9 写死。插入后 needed 16，`16 <= batch_questions`（32）。

resolve 的 `run_probes`（unreachable、timeout）未跳过。加载 seam 不需要额外 `stannum` GRANT。

停在 seam 时，`v13_tools_catalog_frozen` 还没有 catalog stage 对 `v13_spawn_subsession` 的 VOLATILE 豁免。与 `v13/seam/test_seam.py` 的 `open_routed` 相同：parse 前 `UPDATE tools SET enabled=false WHERE name='spawn_subsession'`。行还在，`count(*)` 基线仍是 7。这是运行时 DML，不改 SQL 文件。

`v13_context_fresh` 比对 `v13_context_required` 与 `sessions.context_active_revision`。新会话该列为空，advance 会先 enqueue `context_refresh` 而不是 tool。每次 advance 的同一事务里把它写成 `v13_context_required`。这一列不在步 0 探针里，不会把 snap 判成 `stale`。

`typesafe.provider` 是占位 GUC。连接上第一次 `typesafe_ask` 会清掉它，之后再 `set_config` 报 reserved prefix。所以每次 `v13_parse` 用一条新连接，会话级设一次 provider/model，事务级设 mock，提交后关掉。advance/claim/complete 留在不调用 typesafe 的主连接上。这与计划「每事务重设 GUC」冲突，以活的 pg_typesafe 为准。

`judgment_cache` 按 `request_hash` 全局只写一次，不看本次 mock。失败的 tool 不追加 `tool/result`，上下文哈希不变，下一拍会复用上一拍的 `tool_action`。失败场景用另一句用户消息，并在失败结算后再追加一条 user/message，下一拍的 `llm_generate` 才会真正被问到。

### E4

改前基线 `.e4-baseline-2026-09-27.log`（2026-09-27）：23 个路径退出码全部为 0。无既有红，不豁免 envelope / twophase。

改后同一清单（不含 `v13/read_tools`）全部仍为 0。零新增失败。

| 路径 | 改前 | 改后 |
|---|---|---|
| `v13/catalog/test_catalog.py` | 0 | 0 |
| `v13/characterize/test_characterize.py` | 0 | 0 |
| `v13/chunks/test_chunks.py` | 0 | 0 |
| `v13/control/test_control.py` | 0 | 0 |
| `v13/economy/test_economy.py` | 0 | 0 |
| `v13/envelope/test_envelope.py` | 0 | 0 |
| `v13/fanout/test_fanout.py` | 0 | 0 |
| `v13/filter/test_filter.py` | 0 | 0 |
| `v13/loop/test_loop.py` | 0 | 0 |
| `v13/manifest/test_manifest.py` | 0 | 0 |
| `v13/memory/test_memory.py` | 0 | 0 |
| `v13/mgraph_assembly/test_mgraph_assembly.py` | 0 | 0 |
| `v13/mgraph/test_mgraph.py` | 0 | 0 |
| `v13/mgraph/test_stannum_usage.py` | 0 | 0 |
| `v13/periphery/test_periphery.py` | 0 | 0 |
| `v13/recall/test_recall.py` | 0 | 0 |
| `v13/resolve/test_resolve.py` | 0 | 0 |
| `v13/schema/test_schema.py` | 0 | 0 |
| `v13/seam/test_seam.py` | 0 | 0 |
| `v13/spawn/test_spawn.py` | 0 | 0 |
| `v13/summary/test_summary.py` | 0 | 0 |
| `v13/triage/test_triage.py` | 0 | 0 |
| `v13/twophase/test_twophase.py` | 0 | 0 |

## CRLF fixture

`.gitattributes` 是仓库根新建文件，唯一一行 `v13/read_tools/fixtures/crlf.txt -text`。

```text
$ git check-attr -a -- v13/read_tools/fixtures/crlf.txt
v13/read_tools/fixtures/crlf.txt: text: unset
```
