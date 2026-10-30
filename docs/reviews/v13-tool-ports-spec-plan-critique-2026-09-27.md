# v13 工具口岸规范+修复计划 批判（对照双通道 Oracle 出口）

身份：correctness & completeness critic，不是共同作者。不重写计划。

**对象**：`docs/plans/v13-tool-ports-spec-and-fixes-2026-09-27.md`（下称「计划」）。
**基线**：`prompt-exports/oracle-plan-2026-09-27-213606-v13-tool-port-spec-a-d144.md` 的两条生成计划——Oracle 1（grokBuild，`# v13 工具口岸规范与 read_tools 修正：实施计划`）与 Oracle 2（codex，`# 1. Summary`）。组合 prompt 与选区转储不当计划内容。
**代码核对基线**：HEAD=`1d7af6b`（worktree T102）。下文所有 file:line 均按此基线实读核对过，不是转引。

**不重开（用户已裁，下文不论证对错）**：① 规范落点 `docs/designs/v13-tool-ports.md`；② 旧计划替换为短 tombstone；③ E4 自动化进无旗标全量 gate。只追这三个选择合并后留下的缝。

**核对范围（点名接缝）**：`read_contract.py`、`read_file_swift.swift`、`read_pi.mjs`、`read_duck_port.py`、`bridge.py`、`duck_bringup.py` 全文；`test_read_tools.py` 的 L1-145（docstring/import/preflight/duck_inventory）、L206-380（A/B 组）、L540（TOOL_ROWS）、L624-900（run_ring/beat）、L980-1180（D3/D15/D15b）、L1258-1491（D16/E1/E3/run_f/main）；`README.md` 结构与 P2/E4 节；`docs/tutorials/v13/index.md` 全文；旧计划 L1-30、L43、L216-261、L362-392；`v13/load.py`（STAGE_THROUGH）；`git status` 与 `uv.lock` diff。

---

## 1. 出口承重内容：缺失 / 弱化 / 泛化

逐条核对任务点名的十项。结论先行：prepare/seal 顺序、D17 缓存规避、bring-up INNER 单 pin 源、blank-root-before-realpath、回滚顺序五项**完整活下来**；安全整数域、E4 runner、F2 针三处有实质缺口；classify_planes 状态机被计划内部另一节矛盾（见 §2 H1）；A13 有一处措辞错位。

### 1.1 安全整数域与 2^53 边界——规则活下来了，最尖的两组边界用例丢了

计划 §3 第 5 章与 Fix 8 完整保留了 grok 的规则本身（`[-(2^53-1), 2^53-1]`、区间外当缺省、`1.0` 禁止收成 1、Python `_optional_int` L40-43 拒 bool 已核、Swift `optionalInt` L24-32 拒 float 型 NSNumber）。但 B2c 的用例表（grok §5 与计划 Fix 8）只有 `start_line` 侧的浮点/越界（`1.0`、`1.5`、`2**53+1`、`true`、`"2"`），丢了两组区分用例：

- **浮点 `limit` 侧无区分用例。** grok §5 正文有 `start_line=2, limit=1.0`（limit 被收成 1 → 只得第 2 行；缺省 → 第 2 行到文末），但它没进 grok 自己的 B2c 清单，计划 Fix 8 也没有。只测浮点 `start_line` 蒙混得过一个把 `limit=1.0` 收成 1 的 Swift 实现。
- **闭区间端点无对照。** `2**53-1`（域内最大，越界下标 → 返回 `""`）与 `2**53`（域外 → 缺省 → 全文）是可观察区分的一对；现有用例只有 `2**53+1`。注意 `2**53+1` 在 JS `JSON.parse` 下会舍入成 `2**53`，Python `json.loads` 保留精确值——这正是该用例要钉的分叉，但它只测「远大于」，不测「端点含不含」。
- 补一句肯定：计划拒绝 codex Fix 8 的「`2^53` 仍作整数越界返回空串」是对的——那与安全整数域直接矛盾，codex 那条与 grok 那条不能都成立，计划选了自洽的一个。

### 1.2 prepare/seal 顺序约束——完整保留；带错了一处路径模板

grok §9 的七步顺序（sys.prefix realpath 包含检查 → 版本 → `connect(config={"extension_directory": EXTENSION_ROOT})` → 立即关 autoinstall/autoload → `PRAGMA platform` → 逐扩展存在+SHA → 绝对路径 `LOAD` → **seal 前**查 `loaded`/`extension_version`/`realpath(install_path)==realpath(被哈希文件)` → seal 并读回为假）在计划 Fix 1 里逐项都在，含「路径含 `'` 即 fail_internal」与「`main` finally 关连接」。实读确认现状代码已具备其中 sys.prefix/版本/SHA/关自动装载/seal 读回五件（`read_duck_port.py:97-100、101-102、103-109、111-112、125-128`），本次真正新增的是 config 钉目录、绝对路径 LOAD、PRAGMA platform、install_path 同一性四件——计划的「拆 prepare/seal」表述准确。

**带错的细节**：grok §9 的 pin 文件路径模板写作 `EXTENSION_ROOT/1.5.5/<platform>/`，丢了 `v` 前缀；实际缓存布局是 `~/.duckdb/extensions/v1.5.5/osx_arm64/`（`read_duck_port.py:30-32`，已核）。计划 Fix 1 没给路径模板（沉默而非错误），但规范 §9 将从本章展开——**规范必须写 `v<version>` 的真是布局**，否则把出口的笔误冻结成合同。

### 1.3 F2 针原子替换——核对后基本成立，一处需要点破

实读 `test_read_tools.py` F2（L1334-1356）：现行正针确有 `LOAD sitting_duck`/`LOAD duck_block_utils` 两个字面量（L1346-1347，证实「必须同批换针」），禁针 `INSTALL `/`allow_unsigned_extensions`（L1355）、`read_contract`（L1356）俱在。**关键事实：`SET enable_external_access=false` 已是现行正针（L1350）**——所以计划 Fix 1 的「改含四根新针（`extension_directory`/`install_path`/`platform_unpinned`/`PRAGMA platform`）」配合「其余不动」是完整的，grok 把 seal 针列进新增清单反而多余。计划应点破一句「现行正针（两个 autoload SET、`parse_ast`、`ast_to_blocks_from`、`duck_blocks_*`、`enable_external_access=false`）全部保留」，否则「改含四根」读起来像正针全集只有四根。

两处残留弱化（都不阻塞，见 §2）：① codex 的「seal 晚于一切装载断言」**位置**不变量两条通道都没落成源码针（只有存在性针，没有顺序针）；② 没有任何针强制绝对路径 LOAD——加引号的裸名 `LOAD 'sitting_duck'` 能过全部针。核对结论：这不构成洞，因为 F1 的 `realpath(install_path)==realpath(被哈希文件)` 是行为锁，LOAD 形式只是纵深；但规范 §9 应写明这层纵深论证，免得后来者以为针集合本身就是全部保证。

### 1.4 D17 的 judgment_cache 规避——完整保留，且机制已核实

计划 Fix 4 保留了三件：新用户句子（`Read the zero byte token file`）、`literal` mode 复用、root/path swap 手法。机制已核实：swap 的 root/path 注入在 `beat` L837-843（已读）；D15 用 `swap={"path": ...}`（L1067）、D16 用 `swap={"root": ..., "path": ...}`（L1264），同款手法；README P2（L158、L167）明确「`judgment_cache` 按 request_hash 全局只写一次、负例与幸福路径必须用不同用户消息」——规避设计的依据是实台账，不是推测。

一个值得写进规范的性质（两条通道都没说破）：D17 的断言（`effects.status=failed`、`error='read_failed'`、无 `tool/result`、session 不进终态，同 D15 的 L1097-1099 形状）**对「口岸先拒」与「hub 兜底改写」两条路径给出同一张绿**——口岸回归删掉 NUL 检查时 D17 仍绿（被 `jsonb_safe_result` 兜住），所以 D17 锁的是 PG 边界结局，不是哪一层出手；层归属由 A12/B4 扩/C10/F9 扩/G3 分别钉。这是设计优点，但规范应明说，否则后来者会误以为 D17 在测口岸。

### 1.5 classify_planes / duck_probe 状态机——状态定义活了，被 §6 自己矛盾

五态规则（venv 缺/跑不起来→absent；版本≠1.5.5→不缺席、进 F 由 F1 红；platform 不在 manifest→unpinned；有 pin 但缺扩展文件→absent；unpinned 不列入跳过）在计划 Fix 5 逐项保留，G1 的五行表也在。**但计划 §6 风险表同一条件写了相反的处置**，见 §2 H1——这是计划内部矛盾，不是出口丢失。

### 1.6 E4 runner 的递归/连接守卫——守卫视在， runner 在 `main` 里没有位置

计划 Fix 9 保留了 codex 的四条守卫：排除自身（`find ... -not -path 'v13/read_tools/*'`）、ring 连接全部关闭后启动、串行记录 `路径→退出码`、不重试不豁免、超时即失败（§6）。已核实发现集恰为 25 项（含 `v13/acl/test_acl.py`、`v13/observe/test_observe.py`），与裁决 6 的备注一致。

**缺口**：裁决 6 把 E4 从 grok 的 manual 改成全量 gate 自动化，但 Fix 5 的 `main` 顺序（grok 的八步：G→A→B/C→F→ring→失败聚合一一对应退出码）是 grok 为「E4 不进 gate」写的，**整条序列没有 E4 步骤**。Fix 9 只说「runner 在 ring 全部连接关闭后启动」，没说它挂在 `main` 序列的哪一格、ring 被跳过时（工具链缺席、PG 仍在）E4 跑不跑、E4 红与跳过并存在时退出码怎么聚合。这是裁决 6 合并后留下的主缝，必须在 F 开工前补进 Fix 5（见 §5 Q3）。

### 1.7 bring-up INNER 单 pin 源——完整保留

`sys.path` 插 `v13/read_tools`、INNER 在 venv 解释器里 import `PINS_BY_PLATFORM`/`EXPECTED_DUCKDB_VERSION`、装后按**当前** `PRAGMA platform` 比对 SHA+版本、不符退出 1 并打印期望与实得、禁止第二张 SHA 表、`--verify-only` 不建 venv 不联网、`main(argv)` 未知 flag 非零+usage——均在计划 Fix 2。已核实现状：回退 INSTALL 在 INNER L40、WARN 在 L45、`return "official"` 在 L47、`main` 返回子进程码在 L107-108，计划的「删 38-46」锚点偏一两行但目标块唯一。

小缺：`--verify-only` 在 `.duck-venv` 不存在时的行为两条通道都没写（verifier 要 import duckdb，只能跑在 venv 解释器里；venv 缺席应当打印 absent 并非零退出，还是按缺席退出 2 语义，需要一句话）。

### 1.8 blank-root-before-realpath 顺序——完整保留且已核实

Swift `resolvePath`（L44-58）确无 root 检查、空 root 经 `URL(fileURLWithPath: "")` 落到 CWD 围栏（L51-52，已核）；Pi `resolveFenced`（L62-79）的 `realpathSync(root)` 在 L68、失败已正确映射 `read_failed`（L69-72），空白 root 今天落 `read_failed` 与计划 §2 一致；Python（L30-31）/duck（L69-70）已拒。计划 Fix 7 的「检查发生在任何 realpath/URL 构造之前、Swift 不靠 joinPath 补救」逐字成立。

### 1.9 A13 双路径断言语义——语义保留，一句措辞错位

「realpath 即抛」与「open 才失败」两条路径都算过的双路径断言，计划 Fix 7 保留了。但计划把「退出 3」写进了 A13——A13 在 A 组是**进程内** `read_text` 调用，没有退出码；退出 3 属于 F6 的子进程半边（`run_line_json` 不得抛 `ProtocolError`）。措辞应拆开：A13 断言 `ReadError` 且 `code==read_failed`；F6 断言退出码 3。

补充一个加强双路径设计的事实（两条通道都没写）：macOS 上 `os.path.realpath(strict=False)` 对 ELOOP/ENOENT/EACCES 基本不抛（尽量解析后拼回），所以「realpath 即抛」这条路径在作者机上可能**不可达**，实际失败点是 `open()`（`read_contract.py:51-54` 已包 OSError→read_failed）。双路径断言因此不是保守而是必须——且规范应写明哪半边在哪个平台期望可达，免得以后有人把「不可达半边」当死代码删掉。

### 1.10 回滚顺序——完整保留

「`git revert` 先 F 后 S；S 不可单独 revert 进发布线」（计划 §6）保住了两条通道的共同结论（grok §5、codex §5「发布回滚必须按相反顺序」）。见 §4 对正向合并规则的低级缺口。

---

## 2. 欠规格 / 自相矛盾 / 错引用 / 缺依赖

### H1【高·矛盾】unpinned 平台的处置，Fix 5 与 §6 互相打架

- Fix 5：`duck_probe` 把「platform 不在 `PINS_BY_PLATFORM`」归为 `unpinned`；`classify_planes` 不把 unpinned 列入跳过；`main` 对 ok/**unpinned** 都跑 F，由 F1 以 `platform_unpinned` 失败 → **退出 1**。§3 第 8 章规范行同（「unpinned 以退出 1 失败」）。G1 表有 `(T,T,unpinned)→[]`。
- §6 风险表同一行却写：「其他平台：gate 侧 **absent 跳 F/D、最终退出 2**」。

这是 codex 方案（runtime platform 不在 manifest → absent → 跳过）的残句，与已采纳的 grok 方案直接冲突。后果是实的：同一台 linux/arm64 机器，按 Fix 5 全量 gate 红，按 §6 跳过。必须裁一个并同笔改三处（Fix 5/G1/§6/规范 §8）。候选和解：platform 不在 manifest → absent（跳 2，符合「这台机器不是 duck 主机」的语义）；manifest 有该平台但 SHA/版本不符 → 进 F 红（pin 失败不是缺席）。此和解下 `unpinned` 状态没有生产者，G1 表相应减行——所以这属于 §5 Q2，不是直接修。

### H4【高·缺依赖】`uv.lock` 现在就是脏的，G2 第一天就红

`git status` 实测：`uv.lock` 有一行改动（`sqlalchemy` specifier `>=2` → `>=2,<2.1`，与 read_tools 无关）。G2 的禁表含 `uv.lock`，计划 §6 风险行只说「受保护路径脏则停下问」——但该行的触发不是假设而是当前事实。计划应把它列为**开工前置项**（revert / 独立提交 / 归属其他工作线，三选一），否则里程碑 F 的 G2 与 §8「受保护路径零 diff」从第一天起就不可达。里程碑 S 的按路径 add 不受其污染（已核 S 的五文件清单不含它）。

### H5【高·错模板】扩展缓存路径的 `v` 前缀

见 §1.2：规范 §9 必须写 `~/.duckdb/extensions/v1.5.5/<platform>/<name>.duckdb_extension`（`v` 前缀，`read_duck_port.py:30-32`），不能照抄 grok §9 的 `1.5.5` 模板。

### H3【高·欠规格】E4 在 `main` 序列里无位置、与跳过语义无交规则

见 §1.6。Fix 5 的八步顺序需插入 E4 步骤并回答：ring 因工具链缺席被跳过时 E4 是否仍跑（E4 只依赖 PG）；E4 红与 skipped 非空并存时 `exit_for` 的输入是什么（断言失败优先退出 1 的原则应覆盖 E4 子测试非零）；`--contract` 不跑 E4（裁决 6 已含，写进序列即可）。

### M1【中·缺依赖】Fix 1 的测试侧迁移漏了四个编译期消费点

计划 Fix 1 只点名 import 行（L29-34）与 F1 的 platform 断言。实读 `test_read_tools.py`，`EXPECTED_PLATFORM`/`EXTENSION_CACHE`/`EXPECTED_EXTENSIONS` 的全部消费点：

| 位置 | 现状 | 迁移要求 |
|---|---|---|
| L59-63 `PIN_LABEL` | import 期从 `EXPECTED_EXTENSIONS` 拼标签 | 改 `PINS_BY_PLATFORM` 后需要一个 platform 键才能构造——该键探测前未知；落到 run_f 内构造或取唯一键，计划未指定 |
| L90-95 `duck_toolchain_present` | 用 `EXTENSION_CACHE` 判在 | 被 `duck_probe` 取代（Fix 5 隐含，未点名） |
| L118-145 `duck_inventory` | 内嵌脚本裸 `LOAD`（L125-126） | 改调 `prepare`；计划未写 sys.path 插入机制（grok 只对 bring-up INNER 写了） |
| L1336-1341 F2 前半 | `EXTENSION_CACHE / ...` 算 SHA、读 `.info` | 路径表达式必须迁到 `EXTENSION_ROOT / "v1.5.5" / <platform>`；计划未点名 |
| ~L1447 F10 针 | 直接引用 `EXPECTED_PLATFORM` 常量 | 常量删除后针要么改字面量要么从 `PINS_BY_PLATFORM` 键取；计划只写了「F10 追加新针」 |

漏掉任何一处都是运行期 `NameError`（响亮失败，不是静默绿），但计划的 file-by-file 表应当列全。

### M2【中·弱化】B2c 缺浮点 limit 用例与闭区间端点对

见 §1.1。修正：B2c 加 `start_line=2, limit=1.0`（期望第 2 行到文末）与 `start_line=2**53-1, limit=1`（期望 `""`）对照既有 `2**53+1`（期望全文）。

### M3【中·矛盾/悬指引】§3 第 8 章检查列的「E5 调度矩阵」

E5 在计划里没有任何定义：Fix 5 的 gate 是 G1，§8 完成判据的新编号清单（A12/A13/A14、B2b/B2c/B8、C3e/C5b/C10、D17/D18、F5b/F11、G1/G2/G3）也不含 E5。它是 codex Fix 5/9 的 `CapabilityStatus`+E5 调度器方案的残名——该方案已被更简单的 `classify_planes`/`exit_for`/G1 纯函数表整体替代（§3 裁得好：G1 五行表就是那张调度矩阵，且 G 组在 `--contract` 下可达，E 组活在 run_ring 里不可达）。**精确修正：§3 第 8 章检查列删「E5 调度矩阵」，只留 G1。**

### M4【中·错引用】三处锚点偏得值得改（另有一批系统性 ±1-2）

逐一核对后的更正（计划文头已声明行号是基线锚点，±1-2 不逐条列）：

| 计划锚 | 实际（HEAD=1d7af6b） | 偏差 |
|---|---|---|
| `duck_inventory`（test 107-139） | `test_read_tools.py:118-145` | 起点偏 11，且没盖住函数尾 |
| D3 差分（test 989-992） | `test_read_tools.py:997`（`after_rev == base_rev + 4`） | 偏 5-8 |
| 旧计划「D3 写 +3/+3/+6」引 L216/220/257-259 | 旧计划 L364（L216/220/257-259 是预算 3→5 与场景段，不含 +3/+3/+6） | 引错段落 |

已核实无误的关键锚（勿再动）：B2 三对 L296；tick 守卫 L790-791；`completed=True` L867 先于 accepted 检查 L868；E1 L1298-1300；F6 七输入 L1382；F2 针 L1346-1356；main 合并预检 L1469-1471；`OperationalError` 类名判断 L1483；README E4 节 L169-199；index.md 内核预留 L72；16 拍构成 = 负例 5（L1019 循环×3+L1021+L1028）+ 失败 3（L1067/L1106/L1108）+ duck 失败 1（L1124）+ 幸福 6（L1173×5+L1174）+ D16 1（L1264），D17 加一拍得 17 的算术成立。E1 的 +4 依据成立：`TOOL_ROWS`（L540）恰四行 + 旧计划 L43「行级 bump 每行 +1」+ D3 已测 INSERT +4。

系统性 ±1-2 清单（一笔带过即可，不值得逐条修）：`load_plane` 实 94-129（计划 93-128）；裸 LOAD 实 113-114；`formatSize` 实 98-106；`takeInt` 实 29-34；四处裸 `exit(1)` 实约 255/264/267/285（grok 已自重数过一遍）。

### M6【中·弱化】E3 的规范针只证「README 提到路径」，不证规范存在

E3 的机制是把针子串对 README 全文做包含检查（L1304-1325）。Fix 6 的「E3 针追加 `docs/designs/v13-tool-ports.md`」因此锁的是「README 写了这个路径」；README 指向不存在文件照样绿。codex 的设计（E3 断言规范文件存在+合同版本+关键 ID）更强。修正成本一行：E3 加 `AGENT_ROOT / "docs/designs/v13-tool-ports.md"` 的存在性断言（S 里程碑结束时该文件已入库，时序无冲突）。

### 低·编辑缺陷

- §8 完成判据第 4 条与第 6 条逐字重复（「规范含合同版本、全部条款 ID 与检查手段；README/规范/测试三处 pin 数字一致」×2）。
- Fix 7 矩阵里 symlink 环的跳过条件写「平台不允许建环则单 case 跳过」——建环在所有目标平台都允许，失败发生在解析期；条件应写「创建失败则跳过」。
- §3 第 0 章 15 条不变量没给逐条 TP- 编号（codex 有 56 条 ID 的全枚举）；E3 到底钉哪几个 ID 未指定。规范写作时自定即可，但 E3 针的 ID 集合应在 Fix 6 里点名，哪怕只点三个样例。

---

## 3. 代码证伪 / 超任务 / 已被更简单设计替代

### H2【高·被代码部分证伪的论据】`formatSize` MB 臂：删除方向系于一份无法仓内核实的上游引用

计划 §2/Fix 10 删 MB 臂，论据两句：「上游 `truncate.ts:61-65` 只钉两臂」与「`DEFAULT_MAX_BYTES=51200` 永远走 KB」。第二句被所引代码证伪一半：`formatSize` 有三个调用点——sed 提示里的 `formatSize(Buffer.byteLength(首行))`（`read_pi.mjs:227`，参数无界，≥1MiB 可达）与两处 `formatSize(DEFAULT_MAX_BYTES)`（L228、L237，恒 `50.0KB`）。**MB 臂在当前口岸里确实可达**（codex Fix 10 的可达性主张为真），「永远走 KB」只对后两个调用点成立。于是删除的唯一真实依据是上游保真——而 Pi 0.80.3 的 `truncate.ts` 不在本仓、不在本工作区，无法核实；口岸文件头的 Deviation 清单（`read_pi.mjs:5-7`）只登记了围栏、图片、TUI 三项，**没有**登记 MB 臂是后加的，这弱化了「口岸多出来的分支」的推断。codex 的反方向决定（保留 MB 臂、C5 钉 `1.0MB`）与计划不能都对。这不是要求换方向，是要求在 F 开工前把方向钉在可查证的证据上——见 §5 Q1。若最终确认上游确为两臂，C5b 的「含 `1024.0KB`、不含子串 `MB`」自洽（已核 sed 提示其余文本无 `MB`）；若上游实为三臂，删除 MB 臂是在制造新偏差而非清除旧偏差。

### 已被更简单设计正确替代（只登记，不请回）

- codex 的 `CapabilityStatus`/E5 调度器 → grok 的 `classify_planes`/`exit_for`/G1。替代成立，残留物只有 M3 的悬指引。
- codex 的「不新增 G 组」→ 计划的 G 组。计划的理由更硬：E 组今天活在 `run_ring` 内部（E1/E3 在 L1296-1325、teardown 段），`--contract` 摸不到；G2（git 不变量）恰恰需要在无 PG、无口岸、`--contract` 时也跑。codex 把 E2 自动化留在 E 组的方案在 `--contract` 下够不着。此裁决正确。
- grok 的「旧计划留正文+文首幡」+「人工审 diff 只有文首段」manual 检查 → 用户已裁 tombstone。计划 §7 正确地没有带入那条文首-diff 检查，无残留矛盾。
- codex 的规范落点 `v13-dev.md` → 用户已裁 `v13-tool-ports.md`。计划 §1 裁决 1 的理由（index.md:72 的预留是给「9 张表、9 条不变量」的内核全文，口岸规范占用它会让「冲突以冻结规范为准」指向只有口岸的文档）与 grok 一致且成立；index.md L68-75 已核。

### 任务未要求、出口有、计划正确地没收

codex Fix 9.9 的 `RingInfrastructureError`（替换 main L1483 的类名字符串判断）计划 Fix 5 收了，这是对的；codex 其余的超额件（E5 synthetic 矩阵组、发布分支合并门禁条款）属于治理扩张，计划未收，不超任务。

---

## 4. 出口与计划都缺的东西

均为低级，按 ownership / lifecycle / failure / cancellation / testability 归口：

1. **cancellation 非目标句**（lifecycle/cancellation）：codex §3.5 有一句「本 stage 不恢复 stale lease、不发送 cancel、不产生 unknown——不是 read_tools 的责任」，规范 ch 7 没收。旧计划 L432 也有同义句。规范应有这一条非目标，否则下一个口岸会自己发明 cancel 语义。
2. **正向合并纪律**（lifecycle）：codex 有「S 提交不得单独进发布分支」的正向规则；计划只有反向（§6 回滚先 F 后 S、S 不可单独 revert 进发布线）。补一句正向的。
3. **`--verify-only` 遇 venv 缺席**（failure）：见 §1.7，一句话的事。
4. **`jsonb_safe_result` 递归深度**（failure）：G3 三行表只定义了顶层字符串；失败 payload 里嵌套结构的 NUL（如 `{"error":..., "detail":{"raw":"a\0b"}}`）换不换、换哪层，未定义。现实触发面是浅层（error/message 两个顶层键），规范写「浅层即可」或「递归」都行，但要写死。
5. **E4 日志基线文件的处置**（ownership）：自动化后 `.e4-baseline-2026-09-27.log`/`.e4-post-rebase-2026-09-27.log`（仓根未跟踪）变成死引用；README E4 节重写时顺手一句「基线日志作废」。
6. **duck 口岸连接关闭的失败语义**（lifecycle）：Fix 1 的 `main` finally 关连接——`con.close()` 自身抛错时（比如 LOAD 后连接已坏）压不压原异常，一句话。

---

## 5. 其答案会实质改变设计或顺序的问题

| # | 问题 | 为什么改变设计/顺序 | 严重度 |
|---|---|---|---|
| Q1 | Pi 0.80.3 `truncate.ts` 的 `formatSize` 到底两臂还是三臂？ | 翻转 Fix 10 的删除方向与 C5b 的期望串（`1024.0KB` vs `1.0MB`）；若在 F 中途翻案，C5b 与 README「Pi 偏差」同笔返工 | 高，F 开工前必须钉死 |
| Q2 | 未知平台（不在 `PINS_BY_PLATFORM`）该红还是该跳？ | 见 H1；决定 `duck_probe` 状态集（要不要 `unpinned`）、G1 行数、F1 的失败文案、§6 行与规范 §8 句 | 高，S 写规范前必须裁 |
| Q3 | E4 runner 在 `main` 序列的位置，以及 ring 被跳过（PG 在、工具链缺）时 E4 跑不跑？ | 决定 Fix 5 的序列图与 `exit_for` 的输入定义；也决定「缺 swift 的 CI 机器是否每次为 25 个 PG 套件付 ~20 分钟」 | 高，F 开工前裁 |
| Q4 | 当前 `uv.lock` 脏行（sqlalchemy `<2.1`）如何处置？ | G2/§8 的前置可达性；若归其他工作线，本计划两个里程碑的开工检查都要先确认它已清 | 中，S 开工前清 |
| Q5 | E3 的规范针：钉哪几个 TP- ID 做样例？加不加文件存在性针？ | 只影响 Fix 6 的针清单，不影响结构 | 低 |

---

## 严重度汇总

| 严重度 | 条目 | 一句话 |
|---|---|---|
| 高 | H1 | Fix 5 与 §6 对 unpinned 平台一个说红一个说跳，必须先裁（Q2） |
| 高 | H2 | MB 臂删除方向系于无法仓内核实的上游引用，且「永远走 KB」被 L227 调用点证伪一半（Q1） |
| 高 | H3 | E4 自动化已裁，但 `main` 序列没有 E4 的位置与跳过交规（Q3） |
| 高 | H4 | `uv.lock` 现在就是脏的，G2 与「受保护路径零 diff」从第一天不可达（Q4） |
| 高 | H5 | 规范 §9 必须写 `v1.5.5` 带 `v` 的真实缓存布局，别冻结出口的笔误 |
| 中 | M1 | Fix 1 测试侧迁移漏 PIN_LABEL/F2 路径表达式/F10 平台针/duck_inventory 机制四个消费点 |
| 中 | M2 | B2c 缺浮点 limit 区分用例与 `2^53-1`/`2^53` 端点对 |
| 中 | M3 | 「E5 调度矩阵」悬指引，删 |
| 中 | M4 | duck_inventory/D3/旧计划 +3+3+6 三处锚点更正；其余 ±1-2 系统性漂移 |
| 中 | M6 | E3 规范针只证 README 提及，加一行文件存在性 |
| 低 | 编辑 | §8 重复一条；建环跳过条件措辞；TP- ID 针集合未点名；A13「退出 3」错位到进程内断言；§4 六条小缺口 |

**总体判断**：计划的合并质量高——grok 的条款粒度与 codex 的自动化/收口裁决各取所长，且拒绝了 codex 的 `2^53` 越界语义与 E5 调度器这两个更弱/更重的方案。五项承重机制（prepare/seal、D17 缓存规避、INNER 单 pin 源、blank-root 顺序、回滚顺序）完整。阻塞项集中在四处：H1 的内部矛盾、H2 的上游证据、H3 的 E4 落位、H4 的现实脏文件——全是开工前裁决/核实类，不是返工类。
