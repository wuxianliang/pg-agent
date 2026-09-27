# v13 工具口岸开发规范与 read_tools 修复：实施计划

> 状态：计划（2026-09-27）。**本文件不是规范。** 唯一口岸规范是 `docs/designs/v13-tool-ports.md`（合同版本 `v13/tool-port-contract-1`）。本计划只安排里程碑 S/F 的实施顺序。修复收口已 tombstone 的 `docs/plans/v13-native-read-tools-2026-09-27.md`（处置见 §1 裁决 5）。
> 基线：HEAD=`1d7af6b`（worktree T102，分支 `rp/agent/029d6a4e-agent`）。所有 file:line 为该基线锚点，实施后不保证行号不变。

## §0 执行索引

| 里程碑 | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| **S 冻结规范** | 《v13 工具口岸开发规范》落地为唯一权威文档；文档层级收口（index/README/旧计划） | 规范含全部条款 ID 与检查手段；两道 read_tools gate 仍退出 0；25 个既有测试零失败；一笔提交 | 规范文件（落点见 §1 裁决 1）、`docs/tutorials/v13/index.md`、`docs/plans/v13-native-read-tools-2026-09-27.md`、`v13/read_tools/README.md` | 无（纯文档，零行为变更） | ~250 行新文档 |
| **F 修复全部口岸** | 按规范修复 5 must-fix + 5 suggestion，gate 扩容 | `--contract` 与无旗标全量退出 0；新断言编号实际出现在输出；E4 sweep 零新增失败；受保护路径零 diff；一笔提交 | `read_contract.py`、`read_file_swift.swift`、`read_pi.mjs`、`read_duck_port.py`、`duck_bringup.py`、`test_read_tools.py`、`README.md`、`THIRD_PARTY_NOTICES.md` | S 先行 | ~600 行改动 |

一里程碑一提交、测试实跑全绿才提交（AGENTS.md）。提交信息：`v13: freeze the multi-language tool-port specification` / `v13: align read_tools ports with the tool-port spec`。按路径 `git add`；不 `--no-verify`；推送 `git push -u origin HEAD`（功能分支，不推 main，不 force）。

## §1 裁决（开放问题收口）

**定稿标注：用户已于 2026-09-27 裁决。** 下表第 1、5、6 行是该次裁决的定稿，不再开放。第 2–4 行无分歧，按表执行。

| # | 问题 | 裁决 | 备注 |
|---|---|---|---|
| 1 | 规范落点 | **用户已于 2026-09-27 裁决：A**——`docs/designs/v13-tool-ports.md` 专用文件；`v13-dev.md` 继续留作内核规范占位， tutorials/index.md:72 的预留不动 | 条款内容见 §3 |
| 2 | 未跟踪教程 `how_to_make_a_tool_for_v13.md` | 不纳入、不引用、不从主 checkout 搬入 | 本 worktree 不存在且自述无合同效力；规范必须 fresh-clone 可读 |
| 3 | `FIB_RENDER`/`JS_RENDER` 快照性质 | 保留 measured snapshot；升级演练写进规范条款（clean env → community 安装 → 记录 platform/version/install_path/SHA → 人工审渲染差异 → **同一次提交**更新 manifest/渲染常量/README/NOTICES → 三道验证）；无自动改 pin 的命令 | 换 duckdb 版本/扩展 SHA/platform 后 gate 必须红，人工重钉 |
| 4 | duck 扩展 NOTICES | 信息性归属；补 SPDX 标识符与上游许可证 URL，指向文件内已有 Apache-2.0/MIT 全文，不重复粘贴；明示仓库不分发二进制 | 一旦将来把 `.duckdb_extension` 提交进仓库，同笔提交必须补全文 |
| 5 | 旧计划收口 | **用户已于 2026-09-27 裁决：B**——替换为短 tombstone（只留取代日期+新规范+本计划+README 四指针），不保留过期正文；该文件随 S 首次纳入版本库 | 防止「有 superseded 幡但正文仍被局部引用」的双权威 |
| 6 | E4 回归形态 | **用户已于 2026-09-27 裁决：B**——自动化进无旗标全量 gate：发现 `v13/**/test_*.py`（排除 `v13/read_tools/test_read_tools.py` 自身）排序串行跑，任何非零即红；runner 细节见 Fix 9 | 强制力最强；代价是全量 gate 每次多 ~20 分钟 |

其余裁决（2/3/4）无分歧，按表执行。

## §2 现状锚点（修复对象）

- **装载缺口**：`read_duck_port.py:19-32` 硬编码 `EXPECTED_PLATFORM="osx_arm64"` 与 `EXTENSION_CACHE`；`load_plane`（93-128）哈希缓存路径后按裸名 `LOAD`（112-113），装载后只比 `extension_version`（120-123）。实证（1.5.5）：绝对路径 `LOAD` 合法、`install_path` 精确回报（经 symlink 回报 realpath）、重定向向量是 `extension_directory` **设置**（`connect(config=...)` 可钉）、`DUCKDB_EXTENSION_DIRECTORY` 环境变量惰性、`SET enable_external_access=false` 后连 `duckdb_extensions()` 都抛 PermissionException（断言必须在其之前——现有顺序正确，保留）。
- **bringup 回退**：`duck_bringup.py:31-46` community 失败回退官方渠道（39），WARN 后返回 `"official"`（44-46），`main` 107-108 原样返回子进程码；装后不比对 pin。
- **Node 写帧**：`read_pi.mjs:24-27` `process.stdout.write` + 立即 `process.exit`；另有四处裸 `process.exit(1)`（254/263/266/284 附近）不写帧。Swift（`FileHandle.standardOutput.write`）与 duck（`sys.stdout.buffer.write`+flush）已合规。
- **NUL 进正文**：`read_contract.py:56-58`、`read_file_swift.swift:71-73`、`read_duck_port.py:88-90` 解码后不查 U+0000；Pi 的 `TextDecoder` 成功路径（~200-206）同样放行。成功结果经 hub `json.dumps` 进 `v13_complete` 的 jsonb 被 PG 拒 → `protocol_error`/hub aborted。四个口岸都要修（Pi 同一条缺陷路径）。
- **preflight 连坐**：`test_read_tools.py:79-96`（`toolchain_present` + `duck_toolchain_present`）在 `main` 1467-1471 或在一起，duck 缺席 → A–C（不依赖 duck）整体退出 2；`duck_inventory` 在 test 118-145。
- **文档双权威**：未跟踪旧计划头部仍写「不实现、不提交」/三口岸/预算 5（L3、L10-11、L216/220/257-259），§5 无 F 组，D3 写 +3/+3/+6（实测 +4/+4/+8，test 997）。README 是活台账。
- **围栏分叉**：空白 root——Python `read_contract.py:30-31` / duck `read_duck_port.py:69-70` 拒 `invalid_params`；Swift `read_file_swift.swift:44-58` 无检查（实测空 root 经 URL 解析落到 CWD 当围栏）；Pi `read_pi.mjs:63-82` 无检查（`realpathSync("")` → `read_failed`）。`realpath` OSError（环路/EACCES）在 Python/duck 冒泡为退出 1（`read_contract.py:32-34`、duck 71-73）；Node 已正确映射（46-57）。
- **B 矩阵窄**：B2 仅 `((2,2),(-1,None),(99,None))`（296）；F6 仅 7 输入（1382）。
- **台账健壮性**：tick `<=16`（790-791）恰好饱和（实跑 16 拍）；`completed=True`（867）先于 accepted 判定（868）；E1 只查 `>`（1298-1300）；E2 零自动化；E4 是 README 人工表（169-199）。
- **Pi 负 limit**：`takeInt`（29-35）放行负数，`endLine=Math.min(startLine+limit,len)`（218）——startLine=0 时 `slice(0,-1)` 是「丢末行」、startLine≥1 是空切片，行为分裂不能当合同；归一为 0（空切片+more-lines）。
- **`formatSize` MB 臂**（97-105）：上游 `truncate.ts:61-65` 只钉两臂（B/KB），DEFAULT_MAX_BYTES=51200 永远走 KB；删除 MB 臂恢复上游保真。
- **duck 读序**：`main` 顺序 resolve→read→load→language→render（197-202）；语言只看扩展名，应在读正文之前判。

## §3 规范文档设计

**文件**：见裁决 1。**种类**：冻结实现规范（v8-dev 体例：标题、`>` 定位、`## 0. 不可妥协的不变量`、编号条款、必须/禁止）。**合同版本**：`v13/tool-port-contract-1`（文首声明；变更需 bump）。**范围**：所有 `kind='tool'` 口岸（现有四个 + 未来 JS/TS、Python、Swift、DuckDB/SQL 新口岸）；内核会话机、SQL 阶段不在内。**文首定位四句**：本文是唯一口岸规范；内核规范预留/本文当前只冻结口岸子系统（随裁决 1）；README 是活台账、冲突以本文为准；教程无合同效力。**断言编号由里程碑 F 落进 gate；规范提交不改 gate**（文首写明此窗口）。

条款 ID 用稳定前缀（`TP-`，E3 用子串针检查存在性），每条带检查手段标签 **gate**（test_read_tools 断言）/ **source**（读源码或 git）/ **manual**（默认 gate 不跑，命令写进条款）。

| 章 | 条款（摘要） | 检查 |
|---|---|---|
| 0 不变量 | 15 条短句总纲：线协议 0/3/1+旗标一致；同步写帧；只经 `run_line_json`；错误码闭集不串平面；正文 NUL=read_failed、路径 NUL=path_outside_workspace；空白 root=invalid_params、realpath OSError=read_failed 退出 3；headless 相等+Pi/Duck 各钉常量+CRLF 必不等；options 闭合；IO 在 claim 后 complete 前+finally 兜底；缺席只跳自己组+退出 2 不是通过；被哈希文件==被装载文件+community 失败禁止改道；fork dev 与 released 不互载+受保护文件禁改；渲染常量带版本标签快照；四份围栏独立源码+相等断言锁；规范>台账>归属>已取代计划 | E3 针；各章细则 |
| 1 目录与 handler | 目录行/`handler`/零 SQL 默认；worker 只按冻结 `request.handler` 分派不查活表；options 闭合、root 由 hub 注入、模型不收自由路径；新口岸确需 schema 时拆独立 kernel 变更 | gate D3/D7/D14；source G2 |
| 2 合同分层 | 每口岸声明：输入字段/结果类型/错误集/路径规则/切分规则/证据来源（源码行 or 平台快照）；相等平面才可互为 oracle；独立平面至少一条反合并断言（C9 型）；Python 不因进程内调用而隐式成为各方言语义真理 | gate A/B/C/F 矩阵 |
| 3 线协议 | 帧表（成功/工具错/空 stdin/协议错）；stdout 只承载帧、诊断走 stderr；Swift=FileHandle、Node=`fs.writeSync` 循环写整帧、Python=buffer.flush；四处 Node `exit(1)` 不写帧；桥只读首行、禁等第二帧；进程内 Python 口岸不伪造线协议但返回字符串或抛稳定 `ReadError` | source B5/C8/F2 针；行为 B5/C8/F8 |
| 4 围栏与文本安全 | 空白/非字符串 root 或 path → invalid_params（在任何 realpath/URL 构造**之前**）；realpath 系 OSError → read_failed 退出 3；canonical 前缀围栏；`~` 不展开；正文 U+0000（解码成功后、任何切分之前）→ read_failed，message 固定 `contains NUL` 不回显；看似 JSON 的正文仍是字符串；duck 错误优先级固定：形状→围栏→语言→读/解码→render | gate A12/A13/B8/C6/C10/F6/F9/F5；D16 |
| 5 平面与整数 | headless 换行类/幻影尾/start_line 语义钉上游；**安全整数域 `[-(2^53-1), 2^53-1]`**：区间外整数、小数/指数、bool、字符串当缺省（`1.0` 禁止收成 1）；Pi 不参加此规则（takeInt 收有限整数，负 offset 依赖它）；Pi 负 limit 归一为 0（显式偏差写进条款）；`formatSize` 两臂 | gate A14/B2 扩/B2b/B2c/C1b/C3e/C5b |
| 6 子进程边界 | `run_line_json` 唯一边界（argv 列表/30s/capture/首行/fail-closed）；禁 `shell=True`；本计划不加 env=、不改 cwd；外部 IO 不进事务；subprocess 超时必须回收并映射 protocol_error | source G2；行为 B5/C8/F8 |
| 7 判断面/环/hub | 预算 6、8 带、闭合 options、运行时 INSERT/DELETE 不改种子；`beat` 结算顺序 complete→**先断言 accepted**→commit→`completed=True`；hub jsonb 防 NUL 兜底（`jsonb_safe_result`）；tick cap≥期望+4 且精确相等；judgment_cache 全局单写 → 场景化用户消息必须互异；重复 complete=replay、旧 fence=stale、本地读失败用 failed 不用 unknown | gate D 组扩展/D17/D18；source D14 扩 |
| 8 gate/preflight | 分级：A 无依赖；B←swift；C←node；F←duck（ok/unpinned 都跑 F，unpinned 以退出 1 失败；仅 absent 跳过）；G 无依赖最先跑；ring 需全平面；断言失败退出 1 优先于缺席退出 2；**E4 自动化进全量 gate**（发现-排除自身-串行，任何非零即红，见 Fix 9）；`classify_planes`/`exit_for` 纯函数表；tick 余量≥4 | gate G1 |
| 9 duck 供应链 | `PINS_BY_PLATFORM`（键=运行时 `PRAGMA platform`，当前唯一 `osx_arm64`）；`connect(config={"extension_directory": EXTENSION_ROOT})`；哈希→**同一绝对路径** LOAD→seal 前断言 version+loaded+`realpath(install_path)==realpath(被哈希文件)`；seal 后不再查 `duckdb_extensions()`；bring-up 只 community、失败退出 1、装后跑同一 verifier、`--verify-only` 离线模式；`.duck-venv` 与仓库环境隔离、根依赖文件禁改 | gate F1/F2/F11；manual 联网 bring-up |
| 10 快照 | 渲染常量带版本标签（`PIN_LABEL`）；不自动改 pin；新平台=独立规范变更（manifest+实测渲染快照+NOTICES） | gate F3/F10 |
| 11 新口岸准入清单 | 第五语言必须同时交：线协议/闭集错误码/独立围栏+对照或书面偏差/声明平面归属/只经桥/闭合 options+成对带/claim-complete 时序/preflight 只跳自己组/归属入 NOTICES/零 SQL | manual（评审对照） |

## §4 十项修复设计

断言归属原则：**各平面合同进各平面组；hub 纯函数与 git 不变量进新 G 组（无 PG、无口岸依赖、缺席时也必须跑）；环控制流进 D/E。**

### Fix 1 duck 装载（must-fix 1）

**开工前置（两个里程碑共同）**：`git status` 检查受保护路径。当前工作区有一处**预存脏文件**：`uv.lock` 被改为 `sqlalchemy >=2,<2.1`（另一条工作线所为，与本计划无关，会话开始前已存在）。处置：在 worktree 内 `git checkout -- uv.lock` 还原（主 checkout 的同一改动不受影响，由其归属会话处置）；若用户另有交代则停下问。
- `read_duck_port.py`：删 `EXPECTED_PLATFORM`/`EXTENSION_CACHE`；新增 `EXTENSION_ROOT=~/.duckdb/extensions` 与 `PINS_BY_PLATFORM`（pin 唯一来源，顶层仍不 import duckdb——仓库 venv 的测试要 import 它）。`load_plane` 拆 `prepare`/`seal`：prepare=版本/sys.prefix 检查→`connect(":memory:", config={"extension_directory": str(EXTENSION_ROOT)})`→关 autoinstall/autoload→`PRAGMA platform`（不在表内 `fail_internal("platform_unpinned: …")`）→逐扩展：文件存在+SHA==pin（路径模板 `EXTENSION_ROOT / "v1.5.5" / platform / f"{name}.duckdb_extension"`，**注意 `v` 前缀**，现 `read_duck_port.py:31` 即如此）→`LOAD '<绝对路径>'`（路径含 `'` 即 fail_internal，不手写转义）→seal **之前**查 `duckdb_extensions()` 断言 `loaded`+`extension_version`==pin+`realpath(install_path)==realpath(被哈希文件)`；seal=`SET enable_external_access=false`+读回为假。裸名 LOAD 禁止。
- `duck_inventory`（test 118-145）改调 `prepare`，禁止再裸 LOAD；F1 增 install_path realpath 断言。测试侧同批迁移的其余消费点：`PIN_LABEL` 构造（59-63）、F2 的 SHA/.info 路径（1336-1341）、F10 平台针（~1447）、`duck_inventory` 的 sys.path 插入机制。
- F2 针原子替换：删「含 `LOAD sitting_duck`/`LOAD duck_block_utils`」两根旧针，改含 `extension_directory`、`install_path`、`platform_unpinned`、`PRAGMA platform`，且不含裸 `LOAD sitting_duck"`/`LOAD duck_block_utils"`；`INSTALL `/`allow_unsigned_extensions`/`read_contract` 禁针保留。
- 桥不加 env=（环境变量惰性，实证）；禁止把「清洗 env」写成修复。
- `main` finally 关连接。

### Fix 2 bringup（must-fix 2）
- 删 `duck_bringup.py:38-46` official 回退；community 失败 → stderr 打印错误 → `sys.exit(1)`；禁 WARN 后退出 0。
- INNER（venv 内解释器，`sys.path` 插 `v13/read_tools`）import `PINS_BY_PLATFORM`/`EXPECTED_DUCKDB_VERSION` 单一 pin 源；装后按**当前** `PRAGMA platform` 比对 SHA+版本，不符或平台不在表 → 退出 1 并打印期望与实得；禁止第二张 SHA 表。
- 新增 `--verify-only`：不建 venv、不联网，只跑同一 verifier；供 gate 用；venv 缺失时退出 1 并打印原因（基础设施错，不扮缺席跳过）。`main(argv)` 处理参数，未知 flag 非零+usage。
- gate F11（source，无网络）：不含无 `FROM community` 的回退与 `used official`；含 `PINS_BY_PLATFORM`。联网重跑 bring-up = manual。
- 风险：现有缓存若曾被 official 渠道填充，新 verifier 会红——报 identity mismatch、保留文件、按升级演练人工确认，不自动删。

### Fix 3 Node 同步写帧（must-fix 3）
- `read_pi.mjs` `emit`（24-27）：帧编码 bytes 后 `fs.writeSync(1, …)` 循环处理 partial write，写完整帧才 `process.exit`；删 `process.stdout.write`；写失败即 exit 1 不写第二帧。四处协议 `exit(1)` 保持不写帧。
- C8 source 针：含 `writeSync`、不含 `process.stdout.write`；行为用例（垃圾/EOF/旗标/空 stdin）保留；另起一次成功+一次工具错误各断言 stdout 恰好一个非空帧。

### Fix 4 正文 NUL（must-fix 4）
- 四口岸在严格 UTF-8 解码**成功后、任何切分/parse 之前**查 U+0000 → `read_failed`，message 固定 `contains NUL`（不回显字节）。解码失败仍是 `read_failed`/`not utf-8`（即使字节同时含 0x00）。
- hub 兜底 `jsonb_safe_result(status, payload)`（`test_read_tools.py` 纯函数，`beat` 在 `v13_complete` 前调用）：成功串含 NUL → 改 `failed`+`{"error":"read_failed","message":"contains NUL"}`；失败对象字符串含 NUL → 该字符串换成 `contains NUL`。
- gate：A12（tmp `b"a\x00b"`，Python）、B4 扩（Swift 同码退出 3）、C10（Pi 同码、payload 无 result、JSON 文本无原始 NUL）、F9 扩（`.py` 含 NUL → `read_failed` 非 `parse_failed`，证明检查在 render 前）、G3（`jsonb_safe_result` 三行表：成功含 NUL→failed 对象；成功无 NUL→原样；failed 对象字符串含 NUL→message 换 `contains NUL`。`--contract` 也跑）、D17（环上独立 session，hub 把闭合选项换成 tmp 的 NUL 文件路径，`effects.status='failed'`、`result->>'error'='read_failed'`、无 tool/result、session 不进终态——PG 边界回归所以进 D）。D17 用户消息用新句子（如 `Read the zero byte token file`），防 `judgment_cache` 撞车（README P2）；mode 复用 `literal`、swap 手法同 D15/D16。
- fixture 全部 tmpdir 生成，不提交二进制。

### Fix 5 preflight 分级（must-fix 5）
- 纯函数（`test_read_tools.py`）：`classify_planes(swift_ok, node_ok, duck_status) -> list[str]`（duck_status ∈ ok/absent/unpinned；unpinned 不列入跳过）与 `exit_for(skipped, failed)`（failed→1；skipped 非空→2；否则 0）。
- `duck_probe()`：短命子进程 `.duck-venv/bin/python` 只 `import duckdb`+`connect(":memory:")`+打印 `__version__` 与 `PRAGMA platform`，不 LOAD。venv/解释器缺失或该平台缓存缺扩展文件 → absent；版本≠1.5.5 → 不当 absent（F1 失败退出 1）；platform 不在 `PINS_BY_PLATFORM` → unpinned。
- `main` 顺序：`run_g()`（G1+G2+G3）始终最先→`run_a()` 始终→swift 在则 B、node 在则 C→duck 为 ok/unpinned 都跑 F（unpinned 由 F1 以 `platform_unpinned` 失败）→无 `--contract` 且 skipped 空才 ring（有跳过则 SKIP 行含 `ring`；**ring 被跳过时不跑 E4**——退出 2 已非通过，避免空转）→ring 跑完且无跳过后跑 E4 runner（Fix 9）→`AssertionError` 打印并返回 1（优先于跳过）→skipped 非空打印含 `[SKIP] not_run/toolchain_absent` 与 `planes=…` 后缀返回 2→否则 0。
- 文首 docstring 改「能跑的组先跑；断言失败退出 1；有跳过才退出 2」。
- gate G1：`classify_planes` 至少五行表（(T,T,absent)→[duck]、(T,T,ok)→[]、(F,T,ok)→[swift]、(T,F,ok)→[node]、(T,T,unpinned)→[]）+ `exit_for` 三例（(["duck"],True)==1、(["duck"],False)==2、([],False)==0）。**新组 G 理由**：无 PG、无口岸依赖，恰在「最需要分级」的缺席场景必须执行；塞进 F/E 会被跳过。
- 替换 `main` 里 `OperationalError` 类名字符串判断为类型化 `RingInfrastructureError`（只在 DB setup/connect 边界包装，不吞其他 traceback）。

### Fix 6 单一文档权威（suggestion 1）
- 规范落地（§3）；`docs/tutorials/v13/index.md` 工件节加子弹：口岸规范已冻结于 `docs/designs/v13-tool-ports.md`（合同版本 `v13/tool-port-contract-1`）。旧计划**替换为短 tombstone**（裁决 5=B：取代日期+规范+本计划+README 四指针，正文不保留）。README 文首加权威指针段（里程碑 S 只加指针；行为句留 F 与代码同笔改）。
- E3 针追加规范路径与代表性 `TP-` 条款 ID（至少 `TP-WIRE-3`、`TP-FS-5`、`TP-DUCK-3`，存在性本身由 G2 的 isfile 锁）；现针全保留。F10 追加 README 新句针（`extension_directory`/`install_path`/`platform_unpinned` 要真的写进 README）。
- 本计划文件在 S 提交时在 §1 表格补上「用户已于 2026-09-27 裁决」的定稿标注（裁决内容已折入），并在文首标注本计划非规范。

### Fix 7 围栏一致错误面（suggestion 2）
- 四份 `resolve*`：空白/非字符串 root → `invalid_params`，发生在任何 realpath/`URL(fileURLWithPath:)` **之前**（Swift 加在 `resolvePath` 开头 44，不靠 joinPath 补救；Pi 加在 `resolveFenced` 62 的 `realpathSync(root)` 之前——今天空白 root 落 `read_failed`，合同改 `invalid_params`）。
- Python/duck 把 realpath 包进 OSError→`read_failed`（退出 3）；Swift/Pi 用各自平台 API 达成同表。
- 禁止抽共享围栏模块；duck 禁 import `read_contract`（F2 禁针保留）。
- 输入矩阵（B8/C6 扩/F6 扩共用语义）：相对 fixture 成功；`foo/../fixture` 成功；`../../etc/hosts`、`/etc/hosts` → path_outside_workspace；`a\0b` → path_outside_workspace；`""`/`"   "`（path 或 root）→ invalid_params；`~/…` → read_failed 非正文；根内 symlink 指向根外 → path_outside_workspace；tmpdir symlink 环 → read_failed（平台不允许建环则单 case 跳过并打印原因，不跳整组）。
- gate：A13（chmod 0o000 目录：最终必须 `code==read_failed` 的 `ReadError`——A 是进程内组无退出码，子进程退出 3 由 F6 锁；不得裸 OSError；断言覆盖「realpath 即抛」与「open 才失败」两条路径；`os.geteuid()==0` 打 `[SKIP] A13 euid=0` 不因此退出 2；finally 恢复权限）、B8（Swift 经桥对照 Python 全输入矩阵，空白 root 期望 invalid_params）、C6 扩、F6 扩（进程内 Python 与 duck 同码 + 子进程退出 3）。

### Fix 8 B 矩阵扩容（suggestion 3）
- B2 循环加 `(0,None),(1,None),(1,0),(-2,1),(2,0)`（oracle 仍 `read_text`）；B2b：tmp 空文件 + 无尾换行 `one\ntwo`，Swift==Python；B2c：经桥送 JSON `start_line=1.0,limit=1`（期望全文——若被收成 1 则得首行，蒙混不过）、`1.5`、`start_line=2,limit=1.0`（浮点 limit 被缺省 → 第 2 行到文末，区分 start 与 limit 的分型）、`start_line=2**53-1,limit=1`（安全域内巨数 → 越界 `""`）、`start_line=2**53,limit=1`（越安全域 → 缺省全文，与上一条构成边界对）、`true`、`"2"`，Swift == 同参 `read_text`。
- 安全整数规则落 §3 第 5 章并改两端：`read_contract._optional_int`（40-43）拒 `abs>2**53-1`（bool 已拒）；Swift `optionalInt`（24-31）拒 float 型 NSNumber（`CFNumberIsFloatType`，Foundation 重导出，不新增包）与超安全区间。
- gate A14 锁 Python oracle。Pi `takeInt` 不动（负 offset 语义依赖它）。

### Fix 9 hub 台账（suggestion 4）
- `beat` 顺序：`v13_complete` → 先 `check got=="accepted"` → `commit` → `completed=True`。accepted 不成立时事务仍开，`finally` 回滚后结算 `failed`/`protocol_error`，异常冒泡退出 1。
- `TICK_CAP=24`、`EXPECTED_TICKS=17`（现 16 拍+D17 一拍）；守卫 `<= TICK_CAP` + 末尾 D18 精确 `== EXPECTED_TICKS`；实跑 `[beat]` 行数不是 17 就改常量与规范句，禁止放宽成不等式。
- E1：`end_rev == after_rev + len(TOOL_ROWS)`（现 +4）+ 四名字已不在 + count 回基线断言保留；实跑若非 +4 停下读 `v13_tools_bump` 定义再同笔改规范与断言，禁改 `>=`。
- D14 扩（source）：`inspect.getsource(beat)` 中 `got == "accepted"` 下标早于 `completed = True` 与其后 `conn.commit()`。
- E2 自动化 → **G2**：`git diff --name-only HEAD -- v13 pyproject.toml uv.lock` ∪ `git ls-files --others --exclude-standard` 同范围，禁出现 `v13/load.py`/`pyproject.toml`/`uv.lock`/`v13/**.sql`；另断言规范文件真实存在（`os.path.isfile('docs/designs/v13-tool-ports.md')`——E3 只能证明 README 提及路径，存在性由 G2 锁）；失败打印路径；README 写「原 E2 由 G2 执行」。
- E4 自动化进无旗标全量 gate（裁决 6=B）：runner 在 ring 全部连接关闭后启动；`find v13 -name 'test_*.py' -not -path 'v13/read_tools/*' | sort` 发现清单（当前 25 项含 acl/observe，不写死数字）；逐个 `uv run python <路径>` 串行，记 `路径 → 退出码`；任何非零即 E4 红（不重试不豁免）；用该次输出刷新 README E4 表。
- G 组三件套放 `run_g()`，`main` 在 A 之前调。

### Fix 10 Pi 负 limit / MB / duck 读序（suggestion 5）
- Pi：`readText` 在用 limit 之前把负整数 limit 归一为 0，走现有 `limit=0` 路径（空切片+more-lines）；`offset` 负数不归一。相对上游 JS slice 是显式偏差，写进规范第 5 章与 README「Pi 偏差」。C3e：`limit=-1` 与 `limit=-99` 的 result 都等于 C3b 的 `limit=0` 字符串且不含 `line one`。
- `formatSize` 删 MB 臂（`>=1024` 一律 KB，含 ≥1MiB）；C5b：1MiB 无换行 tmp 首行 → sed 提示含 `1024.0KB`、不含子串 `MB`、`head -c` 后仍 `51200`。实施前先核对本地 `/Users/wxl/Projects/pi/packages/coding-agent/src/core/tools/truncate.ts:61-65` 仍是两臂且 sed 提示调用点对超长首行同样渲染 KB；上游已变则停手按实测重钉，不预设。
- duck `main` 顺序改：解析帧 → `resolve_path` → `load_plane` → `language_for(resolved)` → `read_utf8` → `render`。错误优先级：根内缺 `.txt` → `language_unsupported`；缺 `.py` → `read_failed`；根外 `.png` → `path_outside_workspace`；受支持扩展的 NUL/非 UTF-8 → `read_failed`。gate F5 行为用例 + F5b（source）：`def main` 之后切片里 `language_for(` 下标 < `read_utf8(`（chmod 法在 root 下分不出顺序，不用）。

## §5 明确不做

不改 `bridge.py`（签名/env/cwd）、`setup_db.py`、`__init__.py`、fixtures、`.gitattributes`、`v13/**/*.sql`、`v13/load.py`、根 `pyproject.toml`/`uv.lock`、`FIB_RENDER`/`JS_RENDER`/SHA 的**值**、Pi `takeInt`/负 offset/`limit=0` 文案/图片集/`truncateHead` 控制流、Swift `emitAndExit` 的 `try?` 错误处理、幸福路径 6 route/预算 6/8 带/D15(D15b) 错误码、四处 Node `exit(1)` 不改成 emit、不抽跨语言共享围栏、不给 gate 加插件框架、不做自动改 pin 的 bless 命令、E4 不缓存结果。

## §6 风险与回滚

| 风险 | 处置 |
|---|---|
| S 与 F 之间规范严于代码 | 有意窗口（文首写明断言编号由 F 落地）；两会话内先后完成缩小窗口 |
| `connect(config={"extension_directory"})` 被拒 | 实证已过；若 F1 报配置键错 → 连接后**第一条** `SET extension_directory`（仍先于一切 LOAD），同笔改规范 §9 句；禁改回裸 LOAD、禁改去洗 env |
| 绝对路径 LOAD 后 install_path ≠ 该文件 | 停，把实得路径写进失败信息；禁改成只比 basename |
| Swift `1.0` NSNumber 桥接与 `CFNumberIsFloatType` 不符 | B2c 全绿为完成条件；禁用分不出「缺省 vs start=1」的用例（如全文 hello.txt）蒙混 |
| realpath 在 chmod 0 时不抛、open 才失败 | A13/F6 断言「最终错误码」，两条路径都算过；反面是裸 OSError/ProtocolError |
| E1 DELETE 增量非 +4 | 停，读 `v13_tools_bump` 定义，再同笔改规范与断言 |
| D18 实跑非 17 | 以 `[beat]` 行数为准更新常量与规范句 |
| G2 被无关 SQL 脏文件打红 | 这就是不变量；开工先 `git status`，受保护路径脏则停下问 |
| 缓存曾被 official 渠道填充 | 新 verifier 红 → 报 mismatch、保留文件、按升级演练人工裁决，不自动删 |
| 动态平台只有 osx_arm64 一个 manifest | 两档区分：**unpinned**（venv 在、`PRAGMA platform` 不在 manifest）→ F 照跑、F1 以 `platform_unpinned` 失败退出 1；**absent**（venv/解释器/该平台扩展文件缺失）→ 跳 F 与 ring、最终退出 2。新平台=独立规范变更 |
| E4 自动化耗时与库冲突（裁决 6=B） | 排除 read_tools 自身防递归；ring 连接关闭后再跑；串行；不重试不豁免；超时即失败 |
| 回滚 | 无 schema 迁移；`git revert` 先 F 后 S；S 不可单独 revert 进发布线 |

## §7 实施顺序

**里程碑 S**：① 写规范（§3 全部条款+检查手段+manual 命令）。② index 工件子弹；旧计划替换为 tombstone；README 只加权威指针段；本计划 §1 落定。③ 跑两道 read_tools gate（期望仍 0）+ 手动跑一遍 E4 清单（25 项 0；自动化 runner 属 F）。④ 按路径 add 五文件（规范/index/旧计划 tombstone/README/本计划）提交推送。

**里程碑 F**（一笔提交；F2 针与 load_plane、测试 import 与 pin 重命名必须同批落盘）：① `read_contract.py`（OSError+NUL+安全整数）→ 跑 A。② Swift + B2/B2b/B2c/B4/B5/B8。③ `read_pi.mjs` + C3e/C5b/C6/C8/C10。④ `read_duck_port.py`+`duck_bringup.py`+F 组（先 `--contract`）+ `--verify-only` 跑通。⑤ `classify_planes`/`duck_probe`/`main`/`run_g` → `--contract` A–C/F/G 全绿。⑥ `beat` 顺序/`jsonb_safe_result`/D17/`TICK_CAP`/E1 → 无旗标全量；D18/E1 数不符按风险表停手核对。⑦ README 行为段+F10/E3 新针+NOTICES；再跑两道。⑧ 无旗标全量已含 E4 runner；用该次输出刷新 README E4 表（含 acl/observe）。⑨ G2 自检受保护路径零 diff。⑩ 按路径 add 八文件（若 ⑥ 改了规范句加规范文件）提交推送。

## §8 完成判据

- 两笔独立提交（S→F），均已推送 `rp/agent/029d6a4e-agent`，未 force。
- `--contract` 与无旗标全量（含自动 E4，当前 25 项零失败）均退出 0；输出实际含新编号：A12/A13/A14、B2b/B2c/B8、C3e/C5b/C10、D17/D18、F5b/F11、G1/G2/G3；README E4 表与该次 gate 输出一致。
- `uv run python v13/read_tools/duck_bringup.py --verify-only` 退出 0（不联网）。
- 规范含合同版本、全部条款 ID 与检查手段；README/规范/测试三处 pin 数字一致。
- 受保护路径（`v13/**/*.sql`、`v13/load.py`、`pyproject.toml`、`uv.lock`）相对 `1d7af6b` 零 diff；未暂存 `.duck-venv`/扩展二进制/凭据。
