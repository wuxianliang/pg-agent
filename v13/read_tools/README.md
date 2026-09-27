# v13 read_tools

> 权威：口岸合同以 `docs/designs/v13-tool-ports.md` 为准（合同版本 `v13/tool-port-contract-1`）。本文件是活台账。与规范冲突时以规范为准。条款针：`TP-WIRE-3`、`TP-FS-5`、`TP-DUCK-3`。

M1 离线契约。Python 与 Swift 在 headless 契约上相等；Node 的 Pi 口岸只对照 Pi 文本读矩阵。DuckDB 平面的 `read_duck` 在 `--contract` 的 F 组对照，并作为第四个 `kind='tool'` 行进环（`worker:read_duck`）。单 root。不 spawn `pi`，不 spawn `repoprompt-mcp`。

## Gate

```bash
UV_FROZEN=1 uv run python v13/read_tools/test_read_tools.py --contract
UV_FROZEN=1 uv run python v13/read_tools/test_read_tools.py
```

当前环境（`../pgembed` 带 sqlalchemy `>=2,<2.1` 钉版）下，未冻结的 `uv run` 会改写 `uv.lock`。本 stage 的 gate 按 `UV_FROZEN=1 uv run python v13/read_tools/test_read_tools.py ...` 跑。G2 要求 `uv.lock` 零 diff。待 pgembed 线落定其 sqlalchemy 变更后，此段可移除。

`--contract` 跑 G、A–C 与 F，退出码 0 为通过。无旗标在 ring 之后再跑 E4，退出码 0 为通过。

能跑的组先跑；断言失败退出 1；有跳过才退出 2。G 与 A 无依赖，始终先跑。swift 缺席跳过 B，node 缺席跳过 C，duck `absent` 跳过 F。duck `unpinned` 仍跑 F，由 F1 以 `platform_unpinned` 失败。有跳过则不跑 ring、不跑 E4，打印 `[SKIP] not_run/toolchain_absent`，SKIP 行含 `planes=`，无旗标时还含 `ring`。退出 2 不是通过。原 E2 由 G2 执行。

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
- 负整数 `limit` 在使用前归一为 0，走既有 `limit=0` 路径（空切片 + more-lines）。这是相对上游 JS `slice` 的显式偏差。`offset` 负数不归一。
- `formatSize` 保持上游三臂（B / KB / MB）。2026-09-27 核对 `truncate.ts:61-68` 仍含 MB 臂；1MiB 无换行首行提示渲染 `1.0MB`，`head -c` 仍是 51200。

`truncateHead` 控制流照抄 `truncate.ts`。`limit` 键缺失，以及口岸把 `limit: null` 归一成缺失，才走默认帽。不要向 Node 送 JSON `null` 的 `limit`。

## DuckDB 平面

第四个读工具 `read_duck` 的离线口岸。目录行只在库 `agent_v13_read_tools` 运行时 INSERT/DELETE，不改 `v13/**/*.sql`，不改 `v13/load.py`，不改仓库根 `pyproject.toml` / `uv.lock`。

双平面（v6.1 D1-A）：口岸由 `v13/read_tools/.duck-venv` 里 pin 的 `duckdb==1.5.5` 运行，与仓库 fork dev 引擎隔离。装载：`connect(":memory:", config={"extension_directory": "~/.duckdb/extensions"})`，`SET autoinstall_known_extensions=false`，`SET autoload_known_extensions=false`。`PRAGMA platform` 不在 `PINS_BY_PLATFORM` 则 `platform_unpinned`，退出 1，无成功帧。路径模板是 `~/.duckdb/extensions/v1.5.5/osx_arm64/<name>.duckdb_extension`（目录名带 `v` 前缀）。`LOAD` 用该绝对路径，禁止裸名。seal 之前断言 `duckdb_extensions().install_path` 的 realpath 等于被哈希文件的 realpath。然后 `SET enable_external_access=false`。不 `INSTALL`。不设 `allow_unsigned_extensions`。

### Bring-up

一次性，允许联网：

```bash
uv run python v13/read_tools/duck_bringup.py
```

建 `.duck-venv`（gitignore，CPython 3.12），装 `duckdb==1.5.5`，只 `INSTALL sitting_duck FROM community` 与 `INSTALL duck_block_utils FROM community`。community 失败把错误打到 stderr 并退出 1，不回退官方渠道。装后按当前 `PRAGMA platform` 比对 `PINS_BY_PLATFORM` 的 SHA 与版本。

离线核对（不建 venv、不联网）：

```bash
uv run python v13/read_tools/duck_bringup.py --verify-only
```

2026-09-27 作者机实测（`PRAGMA platform` = `osx_arm64`）：

| 组件 | 版本 | SHA-256 |
|---|---|---|
| duckdb | `__version__` = `1.5.5` | wheel，不钉二进制 |
| sitting_duck | `extension_version` = `b8c06a8` | `e031481f864f342b97deb1e985b6ff5f4b27a97de28d7ec37cf1ad64b6483176` |
| duck_block_utils | `extension_version` = `39941a7` | `4a4f6ff8800c23e959198fa62c134da311acd82d81258f85c64aa16ef21cf529` |

社区描述文件另写 sitting_duck 1.11.0、duck_block_utils 3.4.0。gate 不采信描述文件版本，只断言上表的 `__version__` 与 `duckdb_extensions().extension_version`。`duck_block_utils` 的 v1.2.1 / `125662df` 是 v1.4.5 轨道，不是本机 v1.5.5 构建。

### 管线

围栏与读盘在口岸进程里，算法与 headless Python 读者相同（realpath 前缀、strict UTF-8），但口岸不 import 仓库模块。读盘不经过 DuckDB 文件面。扩展名去点、大小写不敏感，对照 `ast_supported_languages().extensions`。然后：

`parse_ast($content, $lang, peek := 'full')` → `ast_to_blocks_from` → `duck_blocks_validate` → `duck_blocks_to_text`。

`ast_to_blocks` / `ast_to_blocks_list` 内部走 `read_ast`。`enable_external_access=false` 之后读文件被拒。口岸用同族的 `ast_to_blocks_from`，吃内存表。两个扩展都必须已 LOAD：`sitting_duck` 提供 `parse_ast` 与 `ast_to_blocks_from`，`duck_block_utils` 提供 `duck_blocks_validate` 与 `duck_blocks_to_text`。社区 3.4.0 没有 `db_blocks_to_text`（1.x 旧名）；实测渲染函数是 `duck_blocks_to_text`。

D3 闭合选项：本工具的 param_spec 只有 `{"fib.py": "Python fixture"}`。纯文本喂不进 AST，所以没有 `hello.txt` 选项。

### 错误分类

与 Swift / Node 同一帧一行 JSON。

| 情况 | error | 退出码 |
|---|---|---|
| 成功 | `ok=true`，`result` 为字符串 | 0 |
| 空 stdin、缺 path、path 空、类型不对 | `invalid_params` | 3 |
| NUL、`../`、根外绝对路径、符号链接逃出 | `path_outside_workspace` | 3 |
| 缺文件、目录、非 UTF-8、`~` 不展开 | `read_failed` | 3 |
| 扩展名不在 `ast_supported_languages()` | `language_unsupported` | 3 |
| 解析或块校验失败 | `parse_failed` | 3 |
| 坏 JSON、版本/SHA 不符、扩展装不上 | 无成功帧 | 1 |

### 与 Pi 口岸的差别

Pi 口岸对照上游源码行钉行为。本口岸不能：装载的是社区签名二进制，不是仓库里的源码行。本地 sitting_duck checkout 与已装载的 `b8c06a8` 不是同一棵树。期望文本以本机实测钉死（`fib.py` 全文渲染常量，断言标签带 `duckdb=1.5.5 sitting_duck=b8c06a8 duck_block_utils=39941a7`），不按 README 列数或源码行号。outline 默认样式只渲染定义：`fib.py` 含 `print(fib(6))`，渲染结果不含这次调用。这是实测结果，不是漏读。

## 环

四个 `kind='tool'` 行只在库 `agent_v13_read_tools` 里运行时 INSERT/DELETE。不写入 `v13_core.sql`，不追加 `SQL_LOAD_ORDER`，不改 `v13/**/*.sql`。`setup_db` 用 `load_stage(..., 'seam')`。hub 只按冻结的 `request.handler` 分派，不查活 `tools` 表。读盘在 `v13_claim` 已提交、`v13_complete` 未开启之间。

| name | handler | 执行 |
|---|---|---|
| `read_pi` | `worker:read_pi` | `node read_pi.mjs`，只送 root/path |
| `read_file_swift` | `worker:read_file_swift` | `swift read_file_swift.swift` |
| `read_file_py` | `worker:read_file_py` | 进程内 `read_text` |
| `read_duck` | `worker:read_duck` | `.duck-venv` 的 python + `read_duck_port.py`，只送 root/path；语言由口岸从扩展名推导 |

前三行的 options 仍是 `hello.txt` / `crlf.txt`。`read_duck` 的 options 闭合为 `{"fib.py": "Python fixture"}`。

策略 v2：把 v1 带复制过来后追加 8 条，`band_no=1, lo=0.60, hi=Infinity, action=pass`。六条是前三个工具的 `param::` / `stated::`，另两条是 `param::read_duck::path` 与 `stated::read_duck::path`。

预算：负例仍在种子 `max_cycles=3` 上跑三条 tool route 后撞墙，结构不动。幸福路径是 `tool×4 + llm + finish = 6` 条 route，finish 在 `cycle_no=5` 发出，所以同一事务把 `turn_budget` 从 3 翻到 `max_cycles=6`。`read_duck` 的解码结果必须等于 `test_read_tools.py` 的 `FIB_RENDER`（F 组实测常量，标签 `duckdb=1.5.5 sitting_duck=b8c06a8 duck_block_utils=39941a7`），不重新发明渲染文本。

ch8 练习 3：用 `tools.handler` 加一种 handler，只 INSERT 目录行再起进程，跑通一个 turn。这个练习改了几个 SQL 文件？答案是零 SQL 文件。

预算 v2（`turn_budget.max_cycles=6`）和路由策略 v2 只活在会被 `setup_db` DROP 的库 `agent_v13_read_tools` 里，不进入其他 stage 的库。

## 偏差台账

### P1

活体 `v13_needed_judgments`（`v13/triage/v13_triage.sql:1005`）在无 `goal/override` 的根会话上多发一个 `triage` choice。`v13_triage_steer` 在没有 `triage` pass 带时对根会话 fail-closed，enqueue `human` / `triage_fail_closed`。种子 v1 与本 stage 的 v2 都不加这条带（D2 仍是 v1 带数 + 8）。环上每个 session 在首次 `v13_parse` 前调用 `v13_submit_override`，`intent=direct`。这让 `v13_triage_decide` 返回 `direct`，并抑制 `triage` 信号。不改 SQL 文件。

### P2

计划钉的行号与加载清单有漂移，以实施时核对为准：

- `v13_complete` 活体在 `v13/seam/v13_seam.sql:409`（计划写 419）。判定串是 `v13_record_worktree_released`。
- `v13_advance` 活体在 `v13/triage/v13_triage.sql:561`，含 `WHEN 'finish'` 与 `v13_triage_prework`。`v13_claim` 在 `v13/fanout/v13_fanout.sql:266`。`v13_closeout` 在 `v13/spawn/v13_spawn.sql:585`，`turn/end.delivered` 在 `:748`。
- `SQL_LOAD_ORDER` 现为 24 项（acl/observe 在 catalog 之后追加，均在 seam 之后），末项是 `v13/observe/v13_observe.sql`。`STAGE_THROUGH['seam']=21`，`load_stage(..., 'seam')` 仍停在 seam，不加载 catalog/acl/observe。计划写的「21 项、末项 seam」已过期。
- `turn_budget` 种子仍是 `{"max_cycles": 3}`（`v13/schema/v13_core.sql:753`）。幸福路径在本库把它翻成 `max_cycles=6`，不改种子文件。`batch_questions` 仍是 32。加载到 seam 后 `tools` 基线是 7 行，含 `spawn_subsession`。裸根会话的 needed 是 10，不是计划写的 9（多一条 P1 的 `triage`）；D3 量的是插入前后的差 +8，不把 9 写死。插入后 needed 18，`18 <= batch_questions`（32）。

resolve 的 `run_probes`（unreachable、timeout）未跳过。加载 seam 不需要额外 `stannum` GRANT。

停在 seam 时，`v13_tools_catalog_frozen` 还没有 catalog stage 对 `v13_spawn_subsession` 的 VOLATILE 豁免。与 `v13/seam/test_seam.py` 的 `open_routed` 相同：parse 前 `UPDATE tools SET enabled=false WHERE name='spawn_subsession'`。行还在，`count(*)` 基线仍是 7。这是运行时 DML，不改 SQL 文件。

`v13_context_fresh` 比对 `v13_context_required` 与 `sessions.context_active_revision`。新会话该列为空，advance 会先 enqueue `context_refresh` 而不是 tool。每次 advance 的同一事务里把它写成 `v13_context_required`。这一列不在步 0 探针里，不会把 snap 判成 `stale`。

`typesafe.provider` 是占位 GUC。连接上第一次 `typesafe_ask` 会清掉它，之后再 `set_config` 报 reserved prefix。所以每次 `v13_parse` 用一条新连接，会话级设一次 provider/model，事务级设 mock，提交后关掉。advance/claim/complete 留在不调用 typesafe 的主连接上。这与计划「每事务重设 GUC」冲突，以活的 pg_typesafe 为准。

`judgment_cache` 按 `request_hash` 全局只写一次，不看本次 mock。失败的 tool 不追加 `tool/result`，上下文哈希不变，下一拍会复用上一拍的 `tool_action`。失败场景用另一句用户消息，并在失败结算后再追加一条 user/message，下一拍的 `llm_generate` 才会真正被问到。

### M4

- 预算 v2 是 `max_cycles=6`。负例仍用种子 3。幸福路径六条 route，finish 在 `cycle_no=5` 发出；翻成 5 会在 finish 前撞 `budget_exhausted`。
- 策略 v2 带数是 v1 带数 + 8。多出来的两条是 `param::read_duck::path` 与 `stated::read_duck::path`。
- duck `absent`（`.duck-venv` 或该平台扩展文件缺失）只跳过 F 与 ring，打印 `[SKIP] not_run/toolchain_absent`，退出 2，不算通过。G 与 A 仍先跑。`unpinned` 不跳过。
- 幸福路径 `read_duck` 的解码值抄 F 组实测常量 `FIB_RENDER`，不按源码行重算。outline 不含 `print(fib(6))`。
- `read_duck` 失败拍是独立 session：判断面仍选闭合选项 `fib.py`，hub 只在这一拍把 path 换成围栏内 `hello.txt`。口岸返回 `language_unsupported`（`read_text` 会成功读这个文件，所以这条断言钉的是 duck 口岸，不是 Python 读者）。`complete failed` 落 `effects.status='failed'`，无 `tool/result`，session 不进终态。续跑到 finish 的证明仍在 D15（`read_file_py` + `missing.txt`）。tick 守卫是 `TICK_CAP=24`；D18 精确等于 `EXPECTED_TICKS=14`（2026-09-27 实跑 `[beat]` 行数，不是 `beat()` 调用次数 17）。
- 幸福路径的用户消息是 `Read hello.txt and fib.py`，不与负例的 `Read hello.txt` 相同。`judgment_cache` 按上下文哈希全局只写一次：负例在三条 `tool/result` 后的 parse 已经缓存了 `llm_generate`。同一句用户消息会让幸福路径的第四拍复用那条缓存，跳过 `read_duck`。

### E4

无旗标全量在 ring 全部连接关闭后自动跑 `find v13 -name 'test_*.py' -not -path 'v13/read_tools/*' | sort`，逐个 `uv run python`，不重试不豁免。2026-09-27 里程碑 F 实跑 25 项，退出码全部为 0（含 acl/observe）。旧手工表的 23 项基线不再作为豁免。

| 路径 | 退出码 |
|---|---|
| `v13/acl/test_acl.py` | 0 |
| `v13/catalog/test_catalog.py` | 0 |
| `v13/characterize/test_characterize.py` | 0 |
| `v13/chunks/test_chunks.py` | 0 |
| `v13/control/test_control.py` | 0 |
| `v13/economy/test_economy.py` | 0 |
| `v13/envelope/test_envelope.py` | 0 |
| `v13/fanout/test_fanout.py` | 0 |
| `v13/filter/test_filter.py` | 0 |
| `v13/loop/test_loop.py` | 0 |
| `v13/manifest/test_manifest.py` | 0 |
| `v13/memory/test_memory.py` | 0 |
| `v13/mgraph_assembly/test_mgraph_assembly.py` | 0 |
| `v13/mgraph/test_mgraph.py` | 0 |
| `v13/mgraph/test_stannum_usage.py` | 0 |
| `v13/observe/test_observe.py` | 0 |
| `v13/periphery/test_periphery.py` | 0 |
| `v13/recall/test_recall.py` | 0 |
| `v13/resolve/test_resolve.py` | 0 |
| `v13/schema/test_schema.py` | 0 |
| `v13/seam/test_seam.py` | 0 |
| `v13/spawn/test_spawn.py` | 0 |
| `v13/summary/test_summary.py` | 0 |
| `v13/triage/test_triage.py` | 0 |
| `v13/twophase/test_twophase.py` | 0 |

## CRLF fixture

`.gitattributes` 是仓库根新建文件，唯一一行 `v13/read_tools/fixtures/crlf.txt -text`。

```text
$ git check-attr -a -- v13/read_tools/fixtures/crlf.txt
v13/read_tools/fixtures/crlf.txt: text: unset
```
