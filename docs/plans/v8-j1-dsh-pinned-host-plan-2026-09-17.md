# V8 J1：本地 DSH 固定环境与官方启动开发计划

创建：2026-09-17；决策与收口：2026-09-18（保留创建日期文件名）。  
状态：Mid-flow 决策已确认；有界设计审查已完成并处理（`docs/reviews/v8-j1-dsh-pinned-host-plan-critique-2026-09-18.md`）。**本轮仅修改规划工件，未修改产品代码、安装依赖、构建或运行 DSH。**

## 1. Goal 与完成边界

J1 在已经完成并提交的 J0 基线上，建立一个可复核的 DSH 启动基线：使用独立 detached clone，固定源码、锁文件、Node、pnpm、session format、构建产物及实际合成的 profile；通过官方 built `dsh` CLI／Cordis Loader 启动真实 agent-loop，以纯进程内 fake LLM 和 no-op tool 完成启动级 smoke；保持零 SessionPersistence、零外部网络和零真实 provider。同时发布 provisional 支持义务矩阵，将 J1 作为无数据库 gate 接入累计 runner。采用**局部新增启动测试设施与有限 runner 扩展**，不重构 G13 报告器，不修改 DSH 源码或 V8 SQL，不实施 J2 接合探针、J4 PG provider、J5 ledger bridge。J1 是一个里程碑，全部内部工作项验收完成后只做一次完成提交。

### 1.1 完成声明的边界

J1 可以声明：

- 指定 DSH commit、工具链和构建产物已经实际核验。
- 指定 startup-frozen profile 通过官方 CLI／Loader 启动真实 agent-loop。
- 该启动 smoke 使用进程内 fake LLM/no-op tool，无 session 持久化后端，无真实 provider，无网络访问能力。
- 支持义务清单已经版本化，后续 gate 有明确参加义务和证据去向。

J1 **不能**声明：

- PG adapter、正式 compat profile 或 compat-side canonicalizer 已完成。
- `dispatch_interception=sync_before_io`，或 driver switch 已支持。
- fake smoke 等同 V8 effect 的实际派发验收。
- Native／DSH observable trace 已相等。
- J2、P0C、目标 A 或 V10 开工门已通过。

### 1.2 Mid-flow 四项已确认决策

以下四项决策已由用户于 2026-09-18 确认，作为 J1 实施约束；其他接口与数据设计不再交给实施者自行选择。

| 决策 | 已批准方案 | 理由与边界 |
|---|---|---|
| memory-only 启动边界 | 官方 memory-only session；零 SessionPersistence；仅 create，不 resume | `AgentService.createStoredSession()` 明确支持无后端。提前实现内存 persistence 或 PG stub 会扩大 J1，并混淆 J4 的交付边界 |
| checkout／安装联网 | 独立 detached clone；准备阶段允许显式下载精确版本工具和锁定依赖；运行期始终禁止网络 | 用户 master 不可变，安装下载与 provider 执行是不同授权。下载只发生在准备器，不进入累计 gate；不能降级为半安装 |
| 验收平面 | **built CLI 为硬准出**；源码 CLI 仅诊断，失败不得降级 | 能验证实际 `lib/bin.js`、包 exports 和 Loader 单实例关系。代价是执行官方 host-face 构建，而非只转译几个 fixture |
| 平台范围 | **J1 只验收当前 macOS 实施环境** | 不实现 Linux 启动或 sandbox 策略；保留可移植 pin/证据字段，Linux 留给后续独立验证，不宣称已认证 |


## 2. Background：当前实现与证据

### 2.1 已完成基线

| 项目 | 当前事实 |
|---|---|
| pg-agent HEAD | `11c600cf89e833269d92792f9a9831db21788e4a`，J0 完成提交 |
| J0 产品回归 | 同一 fresh run，24/24 exit 0，未中断、无源漂移 |
| J0 runner 自检 | 45 checks，通过；不计入产品 gate |
| G13 实际报告 | 9 passed／11 blocked／9 partial／1 not_run；三个结论均 false |
| DSH 本地源码 | `/Users/wxl/Projects/deepseek-harness`，clean master，commit `0d1f50007f9bca3f52b06e1c3074fa14d5fb0720` |
| DSH CLI 包 | `@deepseek-ai/dsh@0.1.6-alpha.1` |
| 工具声明 | pnpm `11.7.0`；Node `^22.19.0 || >=24.0.0` |
| 本机调查值 | Node `v24.13.1`；PATH pnpm `10.33.0`，后者不合格 |
| DSH lock SHA256 | `ca131858949bd12b2acfc227b1af7dfa3c8d65e74b234824d5c741e6421010a1` |
| session format | `SESSION_FORMAT_VERSION = 3` |

联合计划中的 `2b0edf64…` 和 23/24 是 **J0 前调查历史**，不是当前失败基线。本轮不重跑 J0，也不要求为规划重做 J0。实施 J1 时仍须对变更后的累计集合执行新 fresh run。

调查开始时工作区有四份无关／上位未跟踪文档；2026-09-18 续接时又出现两份 v6.1 review。本轮不处理这些并行工作，实施前重新看 git status，逐路径确认，不以全量暂存卷入。

### 2.2 pg-agent 当前控制流与阻塞点

现有链路：

```text
v8-gates.json
  → run_baseline.load_manifest()
  → execute_suite() 串行运行本仓 Python gate
  → G13 test_compat.py
  → SQL capability matrix + p0c_report.CATALOG
  → schema-v2 报告和三个独立结论
```

相关职责：

- `test_compat.py`：host 无关数据库合同测试；fake 必跑，真实 provider smoke 显式 opt-in。
- `p0c_report.py`：负责子例身份、报告状态、拒收规则和结论；`blocked` 不能由调用者自报。
- `pinned_host_manifest.json`：当前五件套及 dispatch 前置验证仍未解析；switch 保守为 `unsupported`。
- `setup_db.py`：注册保守 SQL adapter manifest，dispatch 为 NULL+note。**J1 不修改它。**
- `run_baseline.py`：持仓库独占锁，串行运行 gate，处理进程组、超时、证据与源漂移。
- `test_baseline_runner.py`：无数据库自检，已有假子进程、环境哨兵、报告拒收及清理测试。

J1 所需有限扩展：

1. 现有 gate ID 校验只认 `G…`，需要精确接纳 `J1`。
2. `database_group` 按目录推导，无法表示 `compat/test_host_pin.py` 不建库。
3. README inventory 正则只识别 G 编号。
4. source snapshot 只覆盖 Python／SQL／JSON，遗漏新增 TS、YAML 和相关构建配置。
5. 当前累计证据输出固定在 `evidence/j0`；新增累计 run 不应继续标成 J0。
6. runner 尚无 J1 安全结果文件接口。

这些是局部兼容扩展，不需要建立通用任务调度器或允许任意命令。

### 2.3 DSH 官方启动链及变换边界

```text
Node 执行 apps/cli/lib/bin.js
  → bin.ts 对应构建产物解析 profile 参数
  → loadLayeredEnv()
       inherited > cwd/.env > DSH_HOME/.env
  → runProfile()
       安装 proxy 配置
       prepareProfile()/loadProfile()
       解析模块 fallback generation
       合成 bundle/profile/home/overlay/telemetry 层
  → boot() 挂 Cordis Loader
       提供冻结 LaunchEnvironmentSnapshot、cmdline、ready、exit
  → 官方 headless startup/runner
  → AgentService.create()
       无 sessionPersistence → memory-only
  → 官方 agent-loop → fake LLM → no-op tool → fake final
  → 官方 appExit / bounded shutdown → fiber dispose
```

必须保留的事实：

- `prepareProfile()` 会重写空 `cordis.yml`，Loader 也可能写回该文件；不能把它当不可变输入。
- profile 自身、home patch、overlay 都会影响最终树；只 hash `cordis.patch.yml` 不足以固定运行身份。
- 自定义 profile 默认 `patchReload=live`，J1 必须显式指定 `startup`。
- `loadLayeredEnv()` 会读两个 `.env`；只删除两个 API key 不足以隔离开发机。
- profile fallback 会写受控 symlink。必须核实际目标与同一个安装闭包，不能简单禁止所有 symlink，也不能允许链接到用户 master。
- `resume()` 无后端直接拒绝；J1 不实现恢复替身。
- 官方 CLI 的 SIGTERM 路径可能 exit 0，因此**exit 0 单独不能证明 smoke 已完成**。

### 2.4 复用与不复用

复用：

- `LlmAdapter`、`resolveModel()`、`stream()` 的官方类型和注册方式。
- 官方 profile manifest、`composeEntries()`、模块 fallback、Loader 和 headless 生命周期。
- Python runner 的 SHA256、原子 JSON、日志隔离、独占锁和进程组测试模式。
- `p0c_report.CATALOG` 的既有子例 ID、requirement 与报告语义。
- J0 的不可拼接 fresh-run 证据模式。

不直接复用：

- 上游 `cli.patch.yml`：它禁用 headless startup/runner、保留 JSONL，不能作为 J1 完成命令。
- 上游 `CliMockAdapter` 的 shell 工具调用：J1 必须使用无外部副作用的 no-op tool。
- 直接 `new Agent`、测试 boot helper 或 SDK argv：不能替代官方应用启动。
- Python FakeLLM 的执行结果：不能冒充真实 DSH loop 已运行。

---

## 3. 详细设计

### 3.1 工作项与单一里程碑

| 工作项 | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| W1 身份与输入锁定 | 固定可核构建输入和插件集合 | pin、profile 与精确 allowlist 通过结构/负向检查 | host/pins/、host/profile/、host_pin.py | J0 已完成 | M |
| W2 隔离准备与构建 | 建立独立、可复用准备产物 | detached/lock/toolchain 正确；实际安装构建通过，ready 与产物 hash 齐备 | prepare_host.py、host/tsconfig.json | W1 | M |
| W3 官方启动 smoke | 验证 built 官方 loop 的启动和退出 | fake 2 次/no-op 1 次/final/dispose、隔离、信号清理正负向全过 | host/src/、host/sandbox/、test_host_pin.py、test_host_pin_unit.py | W2 | M–L |
| W4 支持义务矩阵 | 固定未来参加义务，不产生虚假结果 | catalog 全量对应、两维六组合/负向/optional 分类通过 | required-support-matrix.v1.json、host_pin.py | W1；可与 W2 的独立文件并行 | M |
| W5 runner 集成 | J1 进入累计回归与源追踪 | 精确 J1/null、报告接口、快照/清理自检通过；README inventory 一致 | regression 三文件、v8/README.md | W3/W4 接口固定 | M |
| W6 准出与收尾 | 单一里程碑交付 | 自检及同一 fresh 25/25；工件一致；逐路径 commit/push | 两 README、覆盖矩阵/台账、J1 报告/evidence | W1–W5 | M |

W1–W6 是内部工作项，不分别宣布里程碑完成，不拆成多次完成提交。

---

### 3.2 身份模型：源码、构建、启动、compat 能力分开

#### 3.2.1 固定输入文件

新增：

`v8/compat/host/pins/dsh-0d1f50007f9b-j1-v1.json`

这是**版本化输入记录**，不是动态测试结果。字段固定如下：

| 字段 | 类型及含义 |
|---|---|
| `schema_version` | integer，1 |
| `pin_id` | string，`dsh-0d1f50007f9b-j1-v1` |
| `source.repository` | 无凭据 HTTPS Git 来源，`https://github.com/deepseek-ai/deepseek-harness.git` |
| `source.commit` | 完整 40 位 commit |
| `source.lockfile` | `pnpm-lock.yaml` |
| `source.lock_sha256` | 已核验的完整 SHA256 |
| `cli.name` / `cli.version` | `@deepseek-ai/dsh`／`0.1.6-alpha.1` |
| `toolchain.node` | `v24.13.1`，不是范围 |
| `toolchain.pnpm` | `11.7.0` |
| `session_format_version` | integer，3 |
| `profile_id` | `j1-memory-only@1` |
| `fixture_id` | `j1-keyless-fixtures@1` |
| `launch_plane` | `built` |
| `scope` | `bootstrap_only` |

源码 Git tree OID、工作树文件摘要和产物摘要是准备／运行时测量值，写入证据；不能在计划中编造。

版本变更规则：

- commit、工具链版本、profile 语义、fixture 行为改变：新增 pin 版本，不覆盖旧版本。
- 同输入在另一平台重建：新增 build identity 和证据，不覆盖原 build。
- 任何构建产物字节变化都形成新的 build identity；不能仅凭源码版本相同沿用旧产物 hash。

#### 3.2.2 三层身份

| 身份 | 覆盖内容 | 用途 |
|---|---|---|
| Source identity | commit、Git tree、tracked 文件摘要、lock、Node/pnpm、session format | 确认实际构建输入 |
| Build identity | source identity、构建命令、平台/架构/Node ABI、fixture 输入、运行产物清单及摘要 | 确认实际执行文件 |
| Startup identity | build identity、profile 输入、合成树、模块解析目标、固定 app 参数、隔离策略 | 确认本次官方启动配置 |

`fixture_id` **不是** PG adapter identity。J1 记录 native canonicalizer 的目标版本与源摘要，只表示后续对齐目标，不表示 compat canonicalizer 已实现或验证。

#### 3.2.3 `pinned_host_manifest.json` 的有限更新

完成实际准备和首次合格 smoke 后，允许更新：

- `pinned.dsh_package.value`：包名、版本、Git 来源及完整 commit。
- `pinned.node_version.value`：`v24.13.1`。
- 对应 note：说明证据来自 J1 bootstrap，不代表正式 compat 已接合。
- 增加 `j1_bootstrap` 对象：
  - `schema_version: 1`
  - `scope: "bootstrap_only"`
  - `pin_id`
  - `source_pin_ref: {path, sha256}`
  - `profile_lock_ref: {path, sha256}`

继续保留：

- `pinned.profile_digest.value = null`：这里表示**正式 PG compat profile**，不能放 J1 memory-only digest。
- `pinned.adapter_version.value = null`。
- `pinned.canonicalizer_version.value = null`。
- dispatch 前置验证为 null+note。
- switch 为 `unsupported`。
- `test_compat.INITIAL_EXTERNAL_BLOCKED` 中 ①–⑥ 当前 host 阻塞事实不解除；`p0c_report.EXTERNAL_BLOCKED` 的 ①–⑦ 允许来源全集保持不变。⑦仅在显式 smoke 缺凭据时作为诊断来源，不自动加进默认 keyless 报告。两集合职责不同，不能为了统一计数扩充每轮事实。

J1 startup digest 存在 `j1_bootstrap` 引用的证据中。`p0c_report.py` 的接口、catalog、公式和 SQL seed 均不改。

**避免自引用循环：**先产生首次合格 J1 证据，再更新 manifest 引用，最后跑累计 fresh suite。累计 run 生成的新证据不再回写 manifest；文档可以引用最终 run。测试 gate 自身不得修改 manifest 或其他源文件。

---

### 3.3 准备器与独立 checkout

新增两个 Python 模块：

#### `host/host_pin.py`

职责为 J1 共用逻辑，不启动数据库、不导入带 setup 副作用的测试模块。

主要内部接口：

- `load_pin(path) -> PinSpec`：同步解析，未知字段、非法版本拒绝。
- `verify_checkout(root, pin) -> SourceIdentity`：只读核验。
- `make_runtime_environment(paths, toolchain) -> dict[str, str]`：从空环境构造。
- `verify_preparation(cache, pin) -> PreparedHost`：验证 immutable 准备凭证及产物。
- `validate_support_matrix(path) -> SupportMatrix`：校验义务，不生成通过结果。
- `validate_host_report(data, expected) -> HostReport`：跨进程报告严格校验。
- `write_evidence(...)`：复用现有原子 JSON 方式，仅写本次 run 目录。

用 frozen dataclass 表示 `PinSpec`、`SourceIdentity`、`PreparedHost`；解析后不可变。进程执行状态另用本次运行持有的可变记录，不使用跨运行模块级结果缓存。

#### `host/prepare_host.py`

固定 CLI：

```text
prepare_host.py
  --source-repository <local-path-or-recorded-https-url>
  --node-bin <absolute-path>
  --pnpm-bin <absolute-path>
  [--allow-dependency-download]
```

缓存根固定在：

`<pg-agent>/.pgdata/dsh-j1/`

不提供任意构建命令、任意输出仓库路径或“忽略 dirty”开关。

行为：

1. 校验 Node/pnpm 实际版本和执行文件。
2. 获取本仓准备锁，避免两个准备进程写同一 checkout。
3. 在新的 preparation 目录创建独立 clone：
   - 从本地仓库取源也使用独立对象存储，不用 shared clone／alternates。
   - checkout 完整 commit，detached HEAD。
   - 不切换、修改或清理用户 master。
4. 验证 commit、包声明、lock hash、session format。
5. 安装、构建、准备 fixture 和 profile 锁定快照。
6. 再核源码与 lock 未变化。
7. 所有断言通过后写 immutable `ready.json`；失败不产生 ready 凭证。

推荐布局：

```text
.pgdata/dsh-j1/
  prepare.lock
  preparations/<preparation-id>/
    source/                  独立 detached clone
    pnpm-store/              该准备使用的缓存
    build-home/              隔离的安装/构建 HOME
    fixtures/lib/            本仓 fixture 构建产物
    ready.json               仅完整成功后产生
    preparation-report.json  安全摘要；失败也保留
```

`DSH_SOURCE_ROOT` 必须指向某个合格 preparation 的 `source/`。不提供默认回退到 `/Users/wxl/Projects/deepseek-harness` 的路径，也不选“最近一个”目录。多个合格 preparation 可以并存；同 pin 的旧准备只要本次重新核验所有 identity/hash 仍可用，但每次报告必须记录 `preparation_id` 与 `ready_sha256`，不把不同准备的产物拼成一份成功。

**所有权与回收**：准备器独占持有 prepare.lock；gate 对同一锁取共享锁直到所有子进程结束，准备与人工删除必须取独占锁。J1 不建自动淘汰系统。操作者可在独占锁下按精确 preparation-id 删除整目录（禁止跟随 symlink/根路径逃逸，禁止部分删 node_modules 后继续用同一 ready）；先将成功或失败的安全 preparation-report 封存为 `v8/compat/evidence/j1/preparations/<preparation-id>.json`，保留 identity/hash/退出状态，原始日志不复制。正在使用的目录不得删；删除缓存不改历史证据，也不表示该机器还可复跑，复跑须新准备。报告缺失/不安全时先修复安全诊断归档再回收。明确由操作者定期查看磁盘和清理，gate 不自行触发 GC。

#### checkout 核验规则

每次 gate 运行前后均核验：

- HEAD 恰为指定 commit，且 HEAD detached。
- tracked 文件和索引相对 HEAD 无修改。
- 无非忽略的未跟踪文件。
- lock 原字节 hash 正确。
- 运行所用源码／产物不解析到用户工作区或其他 checkout。
- Git tree 中 symlink、gitlink 必须显式记录；不能将工作树普通文件摘要冒充完整 tree。
- ignored 构建目录仅按准备器的预期输出清单接纳；ignored `.env`、用户配置或额外插件不能因此获得读取许可。

工作树摘要使用排序后的相对路径、文件类型、内容 hash／symlink 目标计算。读取文件为流式，时间复杂度为读取字节总量，排序为 `O(n log n)`。

CI 从记录的 Git 来源取得**同一完整 commit**。公开来源可达性必须在有授权的准备环境验证；本地 clone 成功不证明远端可取得。若远端无法提供该 commit，可另行准备并记录 hash 的 Git bundle，但不能改取 latest、master 最新值或相近 tag。

---

### 3.4 安装、构建与缓存纪律

#### 3.4.1 工具链和安装

- Node 固定 `v24.13.1`。
- pnpm 固定 `11.7.0`；PATH 上 `10.33.0` 明确拒绝。
- Node/pnpm 是准备器的显式前置输入；准备器不自动修改全局工具管理器。若本机缺合格工具，操作者可使用本轮已授权的准备下载，将精确版本安装到 `.pgdata/dsh-j1/tools/` 私有路径，不修改全局默认或 shell 初始化。工具获取单独记录官方分发来源、版本、平台、下载与解包摘要；来源或版本无法核实即停，不从 PATH 10.x 自动代用。依赖准备器仍只接收已存在的 `--node-bin`/`--pnpm-bin`，不内建通用工具安装器。
- pnpm 子进程的 PATH 首位放入指定 Node 的目录，并验证其实际使用版本。
- install 的 cwd 固定为 detached checkout。
- 默认命令语义：`pnpm install --frozen-lockfile --offline`。
- 只有显式 `--allow-dependency-download` 才去掉 `--offline`。
- 禁止 `--force`、`legacy-peer-deps`、修改 peer 规则或重写 lock。
- 安装脚本只按 pin 中已有 workspace 策略执行；不对缺失 native 产物临时放宽脚本授权。
- 安装、构建和源码 Git 子进程同样从允许变量清单构造独立环境，不继承 provider key、NODE_OPTIONS、用户 Git/npm/proxy/动态库注入；使用独立 HOME／配置目录，不读取用户 `.npmrc`、token 或 shell 初始化文件。下载仅用记录的无凭据来源与精确工具/lock，不运行真实 provider。
- 依赖安装失败时保留安全错误类别和日志 hash，不把 `node_modules` 存在记为 installed。

如果需要私有 registry、proxy 或额外 CA，当前默认准备失败。此类配置必须成为显式、脱敏、可复核的新准备输入，不能从用户环境暗中继承。

#### 3.4.2 固定构建顺序

在 detached checkout 运行：

1. 根 `pnpm run build:lib:host`。
2. 在 `apps/cli` cwd 运行 `pnpm exec tsdown --config tsdown.config.ts`。
3. 使用该安装中的 TypeScript 编译器编译本仓 fixture、profile inspector。
4. 对生成的 fixture 做类型检查及 ESM 导入检查。
5. 记录运行闭包及产物 hash：不仅 CLI 单文件，还包括各解析目标的 package.json/exports、递归 runtime imports 所需 JS/JSON/native addon/资源和本地 fixture；锁文件摘要不能代替已安装依赖字节。动态 require/import 或 worker 必需资源必须列在显式清单，不能只记录正向运行碰巧访问到的文件。包含 symlink 目标和目标内容摘要，执行前后复核同一清单，未列出的实际运行目标拒绝。

明确成本与边界：

- `build:lib:host` 是整个 `tsconfig.host.json` host face，不声称是单个 CLI 的最小 TypeScript 图。
- 不另跑 client face、Electron/desktop 打包、website、全仓 coverage 或真实 API e2e。根 `tsdown.config.ts:19–21` 的 host workspace 实际包含 apps/desktop 与 apps/desktop-host，接受这些由官方 host-face 构建带入的包；不能声称完全未构建 desktop 相关代码。
- `apps/desktop-host` 不是 CLI 构建入口。
- CLI override 的 cwd 必须是 `apps/cli`；其相对入口为 `lib/types/bin.js`。
- 即使根 tsdown 已触发 CLI override，显式 CLI 打包步骤仍保留，以固定可审计的 CLI 产物生成步骤。

必查产物至少包括：

- `apps/cli/lib/bin.js`。
- CLI 运行依赖的 package exports。
- `packages/boot/app-boot/lib/index.js` 及其配置声明的 worker 产物。
- profile 实际加载的 core/headless 包运行 exports。
- 本仓 fixture/inspector 的 JS 产物。

构建面启动不得带 tsx hook，不得解析到 `.ts` 或 `lib/types/*.js` 作为运行入口。`app-boot` 的 Include 内嵌、Loader external 关系保持上游配置，fixture 不打包第二份 Cordis／Loader。

#### 3.4.3 缓存规则

- 默认 J1 gate **只验证和运行准备好的产物，不安装、不重建、不联网**。
- 缓存命中要求：输入 identity、工具链、平台／架构、profile/fixture 源摘要、产物清单与 hash 全部一致。
- 缺 `ready.json`、缺 bin、缺 lib、hash 漂移均为失败，不能现场修复后继续同一 run。
- 准备失败或中断的目录不能转成成功缓存；重新准备产生新 preparation ID。
- 同输入复跑 gate 仍生成全新 run-id，不复用旧 smoke 成功。
- 不宣称不同平台或不同绝对路径的构建天然逐字节可复现；分别保存实际 build identity。

#### 3.4.4 实施时必须补核的源码点

选定材料没有给出以下完整内容，不能据此虚构接口或构建已成功：

- DSH 根 `tsconfig.host.json`、根 tsdown 配置及其包 override 调度。
- `dsh-base`／`dsh-headless` 的 bundle patch 与 headless 插件 exports。
- headless 命令参数、ready／exit 使用方式。
- core 插件 required injection 集合。
- `dsh-tools` 的 `register(definition: ToolDefinition): () => void`、必需 `output {schema, render}`、tool 返回值与 disposer（已核源码 `packages/core/tools/src/index.ts:1043–1071`）；render 固定产生含 `J1_NOOP_OK` 的文本内容供第二轮模型核对，不能只返回裸字符串而省略 output 声明。
- `LlmRuntime.registerAdapter(providers, adapter): AdapterRegistrationHandle`（`packages/llm/llm/src/index.ts:382–417`），fiber 自动撤销、重复 route 的 DUPLICATE_ADAPTER 及 disposer 语义。
- `dsh-cmdline` 的 ready／exit 类型声明。
- pnpm workspace 安装脚本与 native 构建前置。

**验证方法固定：**读取该 commit 下对应 manifest、patch、exports、类型声明和邻接测试，落实到本计划指定的 allowlist／profile／构建清单文件，再执行类型检查和 built smoke。不能用 `any`、直接 boot 或 source-plane fallback 绕过发现的问题。

---

### 3.5 startup profile 与最小插件集合

#### 3.5.1 profile 选择

使用自定义 profile：`j1-memory-only`。

源模板位于：

- `v8/compat/host/profile/package.json`
- `v8/compat/host/profile/cordis.patch.yml`
- `v8/compat/host/profile/plugin-allowlist.json`

manifest 固定：

- `private: true`
- `type: "module"`
- `dsh.profile.bundles: []`
- `dsh.profile.patchReload: "startup"`

采用空 bundles、显式插入已审的必要条目，避免挂整个 `dsh-base` 后依赖大量 disable 维持安全。

保留官方 headless startup／runner 的实际插件实现与配置语义，不自写另一套应用 runner。条目的实际 `name`／export subpath 从该 pin 的官方 headless patch 取得；上游 fixture 中出现的 `headless-startup`、`headless-runner` 两个 ID 不得禁用。

#### 3.5.2 最小闭包的确定算法

不是运行时“缺什么就加什么”，而是在 W1 固定：

1. 根集合：官方 headless startup、headless runner、agent-loop，以及 J1 fixture plugin。
2. 同时读取 entry 的 `inject`、插件模块 `export const inject` 和 Service 的 `static inject`，并核对实际调用使用的服务，递归到闭包稳定；不能只看 YAML entry。官方 headless 模块已声明 `['agentDefaultModel', 'agents', 'sessions']`（`packages/bundle/headless/src/index.ts:38–39`），entry 另要求 `headlessStartup`。`run()` 的 ctx.get 缺失即 return 是关闭竞态保护，不能据此声称这三个服务未声明。preflight 及 ready audit 仍要确认它们存在，防止错误组装只耗尽 timeout。
3. 同一 service 有多个可用提供者时，只采用 pin 的官方 core/headless 组合中对应提供者；不得自行挑选生态插件。
4. optional injection 不因“可能有用”而加入。
5. 将最终 package/export、entry ID、依赖 service、配置、模块来源写入 allowlist。
6. 若闭包必须引入禁止后端或外部动作插件，则 J1 停止，报告 profile 不可满足；不能通过替身 persistence 或私改 loop 绕过。

已确定的核心包括 agent、session、llm、system-prompt、session-projections、tools、agent-loop、agent-default-model；完整集合以该 pin 的 entry/module/class 注入声明与实际消费共同确定。`agent-loop` config 使用 `agents: []`，唯一 Agent 由官方 headless runner 创建，不放入另一个 declarative agent。profile 必须显式挂 `@deepseek-ai/dsh-agent-default-model`，固定 config `provider=j1-fake`、`model=j1-fixed`（该 Service 无 settings provider 仍可工作）；不挂 settings 文件后端。`tools` 固定 `mode=native`，不照搬官方 headless patch 中读取 `process.env.DSH_TOOLS_MODE` 的第四个 `!!js`，不用 PTC 默认或运行环境切换。这些条目和配置进入 allowlist/profile lock，fs 保持缺席，headless 使用隔离 cwd。

必须排除：

- JSONL／SQLite／其他 SessionPersistence provider。
- 真实 LLM provider、自动 retry/fallback provider。
- shell、PTY、spawn、LSP、浏览器、web、MCP。
- telemetry、网络任务、后台 jobs、schedule、subagent、PTC。
- 用户 credentials/settings/instructions/skills 文件读取插件。
- HMR 或 live patch watcher。
- PG provider、J2 probe/shim。

`plugin-allowlist.json` 保存完整允许条目，不接受 glob 包名、目录前缀或“所有 core 包”作为放行条件。官方 launcher 自带的 Loader／Include／Group／PluginPackages 等 bootstrap 条目单独列出，与 profile 条目区分。

#### 3.5.3 外部 fixture 的模块解析

fixture 编译后的 JS 复制到临时 profile 自有目录，例如 `plugins/`，通过相对 entry 加载：

- 不修改 DSH package.json。
- 不在用户仓库建立 node_modules 链接。
- fixture 对 DSH 的 bare imports 由官方 profile fallback 解析。
- 类型检查使用相同 pin 的构建 declarations。
- profile resolver manifest 声明所有需要的 bare 插件依赖，版本取自 pin 的实际 package manifest。
- gate 核验所有解析目标都属于当前 preparation；Cordis／Loader 不得出现第二个实例来源。

允许官方生成的 fallback symlink，但其目标必须在锁定的安装闭包内。不得使用 `--preserve-symlinks` 或未锁定的 `NODE_PATH` 改变解析语义。

#### 3.5.4 合成与实际挂载双重核验

新增 `host/src/profile-inspector.ts`，这是**配置检查程序，不是应用启动器**：

- 复用 `loadProfile()`、`composeEntries()`、官方 resolution generation。
- 不调用 `boot()`、AgentService 或测试 boot helper。
- 检查完整层顺序，并输出可序列化的 composed entries 和模块目标。
- J1 不使用 home patch 或 CLI overlay。唯一允许的 `!!js` 是官方 headless runner 配置的三个固定绑定：`ctx.headlessStartup.task`、`ctx.headlessStartup.sessionId`、`ctx.headlessStartup.json`；逐字段比对原表达式，拒绝其他表达式及任意 process/env/fs 求值。这三项分别由固定 CLI task、无 session-id、非 JSON 输出决定；inspector 保留表达式身份并核对 runtime 实值，不为了静态检查启动 runner。
- profile 中的运行路径由固定字段物化，不允许任意表达式或用户配置注入。

构建期产生 expected profile lock，gate 每次启动前重算并比较；实际启动后 fixture auditor 再检查 `ctx.loader.entries()`、entry 配置和激活状态。

profile lock 分开保存：

1. 原始模板文件 hash。
2. 物化配置 hash。
3. `resolved_tree_digest`。
4. 模块解析清单及产物 hash。
5. 实际激活树摘要。

digest 编码固定为：UTF-8 JSON、对象键稳定排序、数组保留顺序，不使用 locale 排序，不含时间戳或 run-id。

仅对**声明为路径的字段**转换为 `<DSH_SOURCE_ROOT>`、`<RUN_ROOT>` 等逻辑根；不能全局替换字符串，不能改变 prompt、工具参数等语义内容。原始字节 hash 与可移植路径表示的 digest 分开记录。

profile 输入在运行前后必须一致；`cordis.yml` 和官方 fallback 链接属于可预期生成物，另列审计，不混入不可变输入判据。

---

### 3.6 fake LLM、no-op tool 与启动审计

新增：

- `host/src/fake-llm.ts`
- `host/src/noop-tool.ts`
- `host/src/smoke-audit.ts`

#### `J1FakeLlmAdapter`

种类：`LlmAdapter` 子类，实例由 J1 fixture plugin 创建，生命周期属于该 Cordis fiber。

接口沿用：

- `resolveModel(provider, model): Promise<LlmResolvedModelInfo>`
- `stream(options: GenerateOptions): AsyncIterable<StreamChunk>`

固定 provider/model：`j1-fake`／`j1-fixed`。fixture 同步调用 `ctx.llm.registerAdapter(['j1-fake'], adapter)` 注册，保留返回的 disposer；不用 replace 动态换 route。注册已由原 service 纳入 fiber 生命周期，fixture 提前关闭可调用同一 disposer，不建立第二份 adapter registry。profile 的 agent-default-model 必须指向此精确 pair，ready audit 和实际请求均核对，错误 provider/model 直接拒绝。

行为：

1. 第一次请求只产生一个 `j1_noop` tool call，固定 call ID、固定 JSON 参数。
2. 第二次请求必须包含该 tool 的预期结果，然后产生固定 final 文本 `J1_KEYLESS_OK`。
3. 不匹配的 provider/model、缺 tool、错误结果、第三次请求或额外工具调用均失败。
4. 无 fetch、socket、文件读取、子进程、时间随机源或真实凭据读取。
5. 不注册 request-error retry，不复制上游 reasoning waterfall；J1 不需要改变请求链。

生成次数由本次实例持有；不得以旧实例计数满足新运行。stream 的中止只结束该次生成，不能补造成功。

#### `j1_noop`

- 通过该 pin 的公共 `ctx.tools.register` 接口注册。
- 输入只接受固定 fixture 参数；模型 JSON 入口仍做类型／值校验。ToolDefinition 同时提供 input schema、output.schema 和 output.render；输出 schema 接受固定结果字符串，render 转成标准 text 内容，第二轮 fake 验证标准 tool result 而非私有内存计数。
- 返回固定结果 `J1_NOOP_OK`。
- 不执行 shell、文件或网络操作。
- 每次执行计数，成功 smoke 必须恰好一次。
- disposer 通过 `ctx.effect()` 管理，卸载时撤销注册。

#### `smoke-audit` plugin

种类：测试专用 Cordis plugin，负责注册上述两项并观察官方 loop，不调度 loop。

本次实例持有状态：

```text
phase:
  mounted → ready_verified → turn_observed → disposed
  任意阶段 → failed

observations:
  llm_calls
  noop_calls
  final_seen
  session_format_version
  session_persistence_absent
  resolved_tree_digest
  failure_code
```

约束：

- 所有注册、事件监听和 ready 回调都有 disposer。
- mount 时同步注册 `appReady.onReady(listener)` 及 disposer，但绝不在 plugin apply 中等待 ready。listener 在启动提交后同步核验完整树并 resolve/reject 本次 `ready_verified` promise；若需异步核验，在 listener 内启动任务、捕获错误后结算 promise，不能以 async listener 返回值当作 launcher 会 await 的承诺。
- 官方 headless runner 只等待 Loader，不等待 appReady（DSH `packages/bundle/headless/src/index.ts:309–312`）；不能依靠兄弟插件激活先后。fake adapter 的首次生成及 no-op 执行入口须 await 同一 ready promise，dispose/abort/超时拒绝它。注册适配器本身不等待，以免 Loader 与 ready 循环等待。ready 前零 fake 输出、零工具执行，失败后不自动 retry。
- 核验 `ctx.get("sessionPersistence") === undefined`，并在执行入口与结束前复核。
- 观察真实 session／agent 事件确认 final；不能仅凭 adapter 计数宣布 turn 完成。
- 不调用 `new Agent`、`AgentService.create()` 或 submit 来替代 headless startup/runner。
- 正常退出由官方 headless 生命周期请求；审计插件仅在失败时请求非零退出。
- 关闭 disposer 写明是否确实执行。输出是安全统计摘要，不序列化整份 session log，不建立可恢复的 session 存储。

启动成功要求全部满足：

- 官方 CLI 正常退出，exit 0。
- ready 核验完成。
- 2 次 fake LLM、1 次 no-op。
- 观察到预期 final。
- SessionPersistence 始终不存在。
- tree 和输入摘要符合锁定值。
- 正常 dispose 完成。
- 未收到外部停止、未超时、无残留子进程。

**SIGTERM 导致的 exit 0、只打印成功文本、只调用 fake 两次，均不足以通过。**

这段 turn 仅发生在 memory-only DSH 内存对象中，没有 V8 session、effect、dispatch 或数据库写入；不能登记到 `p0c-minimal-turn-dual-runtime` 或任何真实 I/O 子例。

---

### 3.7 环境、网络与生命周期隔离

#### 3.7.1 环境从 allowlist 构造

J1 Node 子进程不使用 `os.environ.copy()` 后有限删 key，而是从空环境构造：

- 指定 Node 的受控 PATH。
- 独立 `HOME`、`USERPROFILE`。
- 独立 `DSH_HOME`、`DSH_AGENTS_HOME`。
- 独立 `XDG_CONFIG_HOME`、`XDG_CACHE_HOME`、`XDG_DATA_HOME`。
- 私有 TMPDIR。
- `TZ=UTC`、固定 locale。
- `DSH_TELEMETRY_DISABLED=1`。
- 明确的 J1 输出文件位置及固定 fixture 配置。

以下均不继承：

- provider key、base URL、model override。
- 大小写 proxy 变量。
- `NODE_OPTIONS`、`NODE_PATH`、额外 CA/TLS override。
- `DSH_SNAPSHOT`、其他 DSH/XDG 覆盖项。
- 动态库注入、shell startup、Git config/SSH/askpass 注入。
- 用户 npm 配置、credentials/settings 路径。

cwd 是新建的空私有目录，**不是 pg-agent 根，也不是 DSH checkout 根**。运行前确认 cwd/.env、DSH_HOME/.env、home patch 均不存在；测试只在自己创建的目录中放置哨兵，不打开用户真实 secret 文件。

启动环境证据只记录允许变量名、固定非秘密设置和层来源；不序列化完整 `LaunchEnvironmentSnapshot.values`。

#### 3.7.2 运行网络是强制禁止，不靠无 key 推断

仅新增 `host/sandbox/macos.sb`：固定 macOS 运行期禁网络策略，不提供任意策略或命令模板。

平台选择：

- macOS：`sandbox-exec`，禁止所有网络操作。
- Linux 及其他平台在 J1 未认证，不启动；平台不符或策略不可用均记 `NETWORK_ISOLATION_UNAVAILABLE`，exit 2，不跑 smoke。
- 不提供 `--unsafe-no-sandbox`。

J1 使用纯进程内 fakes，运行期连 loopback 网络也不需要。策略作用于 gate 内**全部 Node 程序**，包括版本/产物检查、profile-inspector、正负向 CLI，而非只包最后一条 CLI；先确认隔离策略可用及自检通过，再导入任何 DSH/fixture 运行模块。安装／构建不使用这份运行网络策略，其下载授权单独记录。

先执行隔离策略自检：隔离子进程访问父进程临时 loopback listener 必须失败，父端无接受连接；再启动 DSH。这个自检只验证 sandbox，不是 compat I/O probe。

JS 网络替身可作为测试哨兵，但不能替代 OS 网络隔离。证据只声明“网络策略已强制执行及自检通过”，没有实际观测来源时不编造“网络尝试次数为 0”。

#### 3.7.3 进程、信号及清理

- Python gate 同步串行管理配置检查、sandbox 自检、built CLI。
- Node 官方 loop 在单进程事件循环中执行；不引入 worker 调度或后台服务。
- J1 gate 的 Node 子进程**继承 gate 的进程组，不另建 session**。这样累计 runner 的现有进程组清理能覆盖它们，避免嵌套 `start_new_session=True` 逃出外层超时清理。
- 默认 gate 不执行 pnpm/install/build；这些有子进程树的操作只在独立准备器中执行。
- 运行 profile 禁止 subprocess provider；macOS supervisor 负责启动子进程及其关闭核验。
- gate 捕获 SIGINT/SIGTERM，停止后续阶段，终止并等待当前子进程；清理失败不得写 passed。
- gate 的本地关闭等待上限短于外层 runner 的 3 秒 SIGTERM→SIGKILL 升级窗口；固定为 2 秒，之后强制终止。
- 正向 smoke 进程上限 60 秒；default runner 240 秒仍作为整 gate 外层上限，准备构建不占此预算。内部阶段上限：准备产物/源前后核验共 80 秒，profile 合成/隔离自检 30 秒，正向 60 秒，全部负向合计 30 秒，清理/证据写入 10 秒，共 210 秒，外层保留 30 秒余量。核验超预算以 TIMEOUT 拒绝，不跳过 hash；每次报告保存分阶段时长。
- 超时负向用固定“已启动但不完成”fixture，在收到 private ready 标记后启动 ≤5 秒的测试倒计时；等待其启动另有 ≤10 秒上限，不能因冷启动慢而误伤目标分支。信号用例也在目标状态标记后发 SIGTERM/SIGINT。静态恶意 profile 和统计拒收使用纯校验，不为每条另起一个 60 秒 CLI。用例短预算是测试内部固定配置，不开放用户缩短正式 smoke 准出标准。

临时目录 mode 0700。清理顺序：

1. 停止并等待子进程。
2. 保存脱敏统计与原始日志 hash，检查输入/产物前后摘要。
3. 删除临时 HOME／DSH_HOME／cwd／profile 并确认成功；清理失败记录失败，不先封存 passed。
4. 将进程和文件清理结果一起封存为本次证据。
5. 原始日志留在单独 mode-0700 诊断目录，不提交。

若进程存活状态无法确认，不删除其工作目录、不释放“已安全结束”的结论；报告 `cleanup_unconfirmed`。外层 runner 停止后续 gate。强制杀死后，下次运行始终新建目录，不恢复旧 session 或旧测试状态。

---

### 3.8 支持义务矩阵

新增：

`v8/compat/required-support-matrix.v1.json`

J1 发布为 **provisional**。它描述后续义务，不描述当前通过情况，不是 SQL capability matrix 的第二实现。

#### 3.8.1 数据结构

顶层：

- `schema_version: 1`
- `matrix_id: "v8-dsh-required-support@1"`
- `lifecycle: "provisional"`
- `spec_refs`
- `spec_sha256`
- `catalog_ids`
- `rows`
- `scope_exclusions`

每条 leaf obligation：

| 字段 | 含义 |
|---|---|
| `case_id` | 稳定 leaf ID，格式为 `<现有 subcase_id>::<语义后缀>` |
| `report_subcase_id` | 必须命中 `p0c_report.BY_ID` |
| `clause` | Conformance 编号；4 标记并入 3，不伪造新条目 |
| `boundary` | 使用 `p0c_report.DB`／`p0c_report.REAL` 的实际字符串值，与所属 catalog 行逐字一致，禁止另起缩写 |
| `drivers` | 明确 `native`、`dsh-compat` 或两者，不由 profile 推导 |
| `obligation` | `mandatory_supported`／`mandatory_negative_rejection`／`optional_smoke` |
| `capability_conditions` | 仅冻结的 dispatch／switch 条件 |
| `objective_a_required` | 是否属于目标 A 的不可降级义务 |
| `owner_gate` | 单一主要验收责任 gate：G13 或 J2–J7；跨 gate 回归另用 `verification_gates` 数组列出，不能用斜线字符串代替责任 |
| `spec_refs` | 规范条款 |
| `acceptance` | 该 leaf 必须断言的安全语义，不填执行结果 |

`scope_exclusions` 单列目标外插件能力，必须含规范依据和入口拒绝的验收去向；不能借此排除 catalog 必跑行。

不把“capability-blocked”存成可随意挑选的 obligation。是否允许 blocked 由 `capability_conditions` 和权威能力事实推导，从而避免把未实现、未运行与能力降级混为一谈。

#### 3.8.2 catalog 对应和最低 leaf 集合

30 个现有 catalog ID 必须全部出现，不能仅每个 clause 放一个占位行。下表“去向”的**斜线首项是 owner_gate，其余项按出现顺序写入 verification_gates 数组**；单项则 verification_gates=[]。这是文档展示简写，不允许 JSON 存斜线值。各 leaf 保留表中明确验收语义及这些责任，不能用 profile 实际挂载情况重分配。

| 既有 report ID／组 | 必须列出的 leaf 义务 | 去向 |
|---|---|---|
| `c1-db-receipt-idempotency` | append/create/complete receipt 重放、冲突、seq 无洞、首 attempt、seal 原子性、无持久 planned | J3/J4 |
| `c1-db-occurrence-identity` | 同名同参不同 slot、非流 occurrence、chunk 四元组身份 | J3/J4 |
| `c1-real-retry-single-batch` | 官方 loop 重试不重复 batch/effect/completion，透明重试禁止 | J5/J7 |
| `c2-db-stale-writes` | session/job fence、epoch、superseded、接管快照、有效旧 job lease | J3 |
| `c3-db-scan-recovery` | wait 复检、timer/claim 扫描、NOTIFY 丢失/重复/乱序 | J3 |
| `c3-real-dispatch-unknown-recovery` | dispatch 后中断、unknown、合法恢复、旧 writer 拒绝 | J5/J7 |
| `c5-db-classification-orthogonal` | known/unknown 证据分类、声明不作权威、混合 sibling、repair/retry | J3 |
| `c5-real-cancel-unknown-classification` | provider 确认取消与本地 abort/timeout 区分 | J5/J7 |
| `c6-db-cancel-compact` | cancel/dispatch 两序、compact 冲突矩阵、锁序、terminal abort | J3 |
| `c6-real-cancel-linearization` | 官方 loop cancel/dispatch 两序及零外部动作断言 | J7 |
| `c7-db-parallel-ordinal` | 两个同名同参 slot、反序完成、ordinal 和 trace 稳定 | J3/J6 |
| `c8-db-generation` | refresh 失败、冻结旧代、新代 readiness、revoke/drain、seal/retry 竞态 | J3 |
| `c9-db-hook-gates` | mandatory 缺席/超时/错误拒绝、advisory 降级、插件直表拒绝 | J3/J7 |
| `c10-db-s5-mapping` | §5.1 映射、结果写入口、stream/chunk/golden/迟到冲突、格式拒绝 | J4/J7 |
| `c11-db-fork-cutoff` | 三个 cutoff 稳定性断言、固定前缀、子控制态不继承 | J3 |
| `c11-db-switch-positive` | 四 guard、quiescing 闭合、finish CAS 屏障、epoch 推进 | J3/J5/J7 |
| `c11-db-unsupported-negative` | UNSUPPORTED、mode/fence/intent 不变、幂等重放 | G13/J3 |
| `c11-real-inflight-switch-closure` | 真实 loop in-flight 收束；不得由 SQL 正向替代 | J7 |
| `c12-db-fake-suite` | 固定 fake、clock/seed/locale；后续两 runtime 共用向量 | G13/J6 |
| `c12-db-real-provider-protocol` | 唯一 optional smoke；J1 不请求 | G13 |
| `c13-db-yield-workspace` | yield 换 worker、checkpoint/materialize、WORKSPACE_LOST 拒绝 | J3 |
| `c13-real-workspace-lost-inflight` | 官方 loop in-flight completion/unknown | J7 |
| `c14-db-grant-denied` | grant/slice 参数约束、撤权门、双 grant、租户隔离 | J3 |
| `c14-real-revoke-dispatch` | 两提交序、授权前零外部动作 | J5/J7 |
| `c15-db-cancel-fixtures` | reducer 资格 guard、before/after、unknown→repair、唯一 closer | J3 |
| `c15-real-cancel-unknown-fixture` | 双 runtime 取消/unknown fixture 字节级比较 | J6/J7 |
| `c16-db-unmapped-audit` | 未知类型 audit/fixture 失败、幂等、adapter identity、禁止静默丢弃 | G13/J4 |
| `c16-db-matrix-logic` | 两维全部六组合、blocked 并集、强制负向、报告拒收 | G13/J7 |
| `real-io-unlisted-forms` | LLM/tool 分别 sync、必需路径无旁路；未准入 PTC/嵌套/后台动作入口拒绝 | J2/J5/J7 |
| `p0c-minimal-turn-dual-runtime` | 无 tool 最小 turn及工具往返 fixture，同一 canonicalizer 对比 | J6 |

规则：

- 所有 `real` 行要求 `sync_before_io`；DB 行不因 dispatch 缺失免测。
- switch 正向 DB 行要求 `supported`。
- switch unsupported 时对应负向必须通过。
- fork 不依赖任一能力维。
- optional 只允许既有 real-provider smoke ID。
- 目标 A 至少要求真实 loop 最小 turn、LLM/tool sync、取消/unknown；T0 降级不能使目标 A 通过。
- 所有 row 的 profile 裁剪均不改变 obligation。

当前 `c1-real-retry-single-batch`、最小双 loop 等行还受 G13 external block ② 保护。J1 不移除 external blocks，不借新矩阵改变 `effective_blocked()`。后续 reporter 接入必须显式处理全部 REAL 行，不能仅复制当前 `DISPATCH_REAL_ROWS` 的子集后漏掉这些行。

#### 3.8.3 provisional→锁定

- J1 验证文件完整、引用有效、分类符合规范，计算 SHA256。
- J2 补实际能力证据后产生新的锁定版本，例如 `required-support-matrix.v2.json`。
- J7/J8 明确读取版本和 hash，不能读取“目录中最新文件”。
- 分类、范围改变必须新版本、附规范依据和审查记录，旧版本与旧报告保留。
- J1 不在 `p0c_report.py` 新增结果来源，也不把矩阵校验 passed 写成 compat 子例 passed。

---

### 3.9 J1 gate、证据与错误接口

新增正式入口：

`v8/compat/test_host_pin.py`

CLI：

```text
test_host_pin.py [--report-json <path>]
```

- 默认读取唯一 J1 pin、`DSH_SOURCE_ROOT` 和准备凭证。
- 不接收任意 Node argv、profile 名称、patch 或真实 provider 开关。
- 不安装、不构建、不重试。
- `--report-json` 是累计 runner 的安全摘要接口，不替代独立证据目录。

#### 执行顺序

```text
输入校验
 → support matrix 校验
 → checkout/build 字节核验（Python，只读）
 → 新建私有运行目录
 → profile 物化（Python 只处理受控文件）
 → 网络隔离自检
 → 受相同策略保护的 toolchain 版本检查 / preflight composition / Node 产物核验
 → 官方 built CLI
 → 校验 ready/turn/dispose 摘要
 → 前后 source/profile/artifact 比较
 → 清理确认
 → 原子封存报告
```

错误类别使用单一 `HostPinError(code, phase)`，不存原始异常文本。稳定 code 至少包括：

- `SOURCE_ROOT_INVALID`
- `PIN_MISMATCH`
- `SOURCE_DIRTY`
- `LOCK_MISMATCH`
- `TOOLCHAIN_MISMATCH`
- `PREPARATION_MISSING`
- `ARTIFACT_MISSING`
- `ARTIFACT_DRIFT`
- `PROFILE_INVALID`
- `PROFILE_DRIFT`
- `PLUGIN_NOT_ALLOWED`
- `PERSISTENCE_PRESENT`
- `NETWORK_ISOLATION_UNAVAILABLE`
- `NETWORK_ISOLATION_FAILED`
- `SMOKE_INCOMPLETE`
- `SMOKE_FAILED`
- `TIMEOUT`
- `EXECUTION_INTERRUPTED`
- `CLEANUP_UNCONFIRMED`
- `EVIDENCE_WRITE_FAILED`

退出码：

| 退出 | 含义 |
|---|---|
| 0 | 本次完整 J1 gate 通过 |
| 1 | 已开始验证后断言、运行、漂移、清理或证据失败 |
| 2 | 输入／工具／准备／隔离前置不可用，目标未执行 |
| 130 | 用户中断 |

exit 2 不是合法 capability blocked。累计 runner 将它记为失败，不能据此准出。

#### 证据布局

```text
v8/compat/evidence/j1/<run-id>/
  source-pin.json
  build-report.json
  profile-lock.json
  startup-report.json
  report.json
```

这些文件均在本次运行生成，不预填 passed。准备、profile 或启动前置失败时，仅生成已取得真实事实的工件；缺失工件在 report 中显式 null/not_run，不能为保持五件齐全编造身份。passed 则要求五件全部有效并互相 hash 绑定。

`report.json` 固定字段：

- `schema_version: 1`
- `gate_id: "J1"`
- `run_id`、`invocation_id`
- `scope: "bootstrap_only"`
- UTC 起止与 duration
- `pin_id`
- `preparation_id`、`ready_sha256`（准备缺失的失败报告允许 null）
- `state: passed | failed | not_run`
- `failure_code`：无失败为 null
- `source_identity`
- `build_identity`
- `profile_identity`
- `support_matrix_ref`
- `checks`：固定必填 ID `pin`、`toolchain`、`build_artifacts`、`support_matrix`、`profile_composition`、`network_isolation`、`official_turn`、`negative_profile`、`negative_result`、`interrupt_timeout`、`no_drift`、`cleanup`；每项恰一次且状态为 passed/failed/not_run，实际子例摘要挂本检查之下，不增删必填集合
- `startup`：固定摘要字段，失败时可为 null
- `cleanup_confirmed`
- `source_drift`、`artifact_drift`
- `artifact_refs`：相对路径及 SHA256
- `claims`：
  - `official_cli_bootstrap_passed`
  - `pg_adapter_verified: false`
  - `dispatch_interception_verified: false`
  - `dual_runtime_trace_verified: false`
  - `p0c_complete: false`

报告通过公式固定为：进程 exit0、所有必填 checks passed、startup 的 ready/final/dispose 和 2 LLM/1 no-op 成立、source_drift=false、artifact_drift=false、cleanup_confirmed=true、必要工件有效；只有满足全部条件，`state=passed` 且 `official_cli_bootstrap_passed=true`。前置 exit2 对应 not_run，运行/断言/超时/清理失败对应 failed；其余四个能力 claims 恒 false。失败和未运行也尽力写安全报告；证据写入失败自身为 exit 1，不回退为 stdout-only 成功。每个新 run 目录独占创建，不覆盖已有 run。运行中的 checkpoint 可原子更新，封存后不可再改。

`--report-json` 目标必须位于本次新建私有目录、预先不存在且路径不经过 symlink；不删除调用者已有文件以便“清旧结果”，旧文件/目录/链接均前置拒绝。最终同目录临时文件+rename 原子写出 `report.json` 的同一安全结构。runner 为每次 J1 调用在 child env 设置随机非秘密 `V8_J1_INVOCATION_ID`（仅此 gate），报告必须原样携带；直接执行由 gate 生成新 invocation_id。reader 校验 invocation_id、时间窗、schema、全部固定 checks、pin/preparation/ready 摘要及 claims，缺项/重复/未知字段拒收。artifact_refs 只许本次 evidence run 目录的相对常规文件，不随 JSON 打开的任意绝对/越界路径；不允许读取外部敏感文件验证 hash。消除 stale 结果的验证覆盖不变，但不引入删除任意路径的副作用。

不提交：

- 原始 stdout/stderr。
- 实际环境值、真实 `.env`、用户配置。
- 本机绝对 home 路径、URI 凭据。
- session 原始事件日志或可供 resume 的文件。

---

### 3.10 累计 runner 的有限扩展

#### 注册表

`v8/regression/v8-gates.json` 保持 schema 1，在现有 24 条后追加：

- `gate_id = J1`
- `argv = ["uv", "run", "python", "v8/compat/test_host_pin.py"]`
- `database_group = null`
- `required = true`

运行时计数从 manifest 推导，新累计集合为 25。runner 自检、J1 基础设施自检都不计为产品 gate。

#### 校验接口

`load_manifest(path, root=ROOT)` 签名不变，规则改为：

- 原 G ID／脚本路径规则保留。
- **仅**接受精确 `J1 ↔ v8/compat/test_host_pin.py ↔ database_group=null`。
- 不开放任意 `J\d+`、Node 命令、额外 argv 或任意 null DB。
- README inventory 只额外接纳 J1。
- G13 身份绑定仍保持。

#### source snapshot

`source_snapshot(root=ROOT)` 签名不变，增加：

- `.ts`、`.mts`、`.js`、`.mjs`
- `.yaml`、`.yml`
- 本次安全策略 `.sb`
- `.lock`
- JSON 本来已覆盖，因此 package/tsconfig/pin/matrix 自动进入

保留既有 evidence／.git／.claude／.venv／__pycache__ 排除语义，但**不新增按裸目录名 lib/dist/cache/.cache 的全局排除**。J1 编译、依赖和缓存全在 `.pgdata/dsh-j1`（本来就在 v8 扫描范围外）；v8 下出现 lib/dist 等源目录仍须按源后缀入快照。若在本仓 v8 下发现意外 node_modules，前置失败而非递归扫描依赖或静默忽略。后续真正新增仓内生成目录须显式登记相对路径前缀并附测试，禁止以宽泛目录名豁免源。

新增 `.lock` 后缀只服务 v8 内未来声明式依赖锁输入，与已显式包含的根 `uv.lock` 同类；本次主要 TS 依赖锁是外部 pin 的 pnpm-lock.yaml，由 J1 身份验证单独覆盖。进程 `prepare.lock` 永远在 .pgdata，不属于源。自检在临时 fixture 中增删一个声明式 `.lock` 验证过滤规则，不为测试新增无用产品锁文件。

外部 detached checkout 不纳入本仓 source snapshot；其身份由 J1 source/build 证据核验。快照策略标识升级为 2，历史 J0 digest 保留原含义，不重新解释。

#### 报告消费与累计记录

新增：

`read_j1(path, started, ended, reason, *, invocation_id) -> (report | None, reason)`

由 `execute_suite()` 仅对 J1 自动附加 `--report-json <private-run-dir>/j1-report.json`。manifest 中仍只有四段 argv。

- 缺失／无效／timeout：`j1_report=null`，reason 为 missing/invalid/timeout。每个被审摘要同时核 private invocation_id，不把同一时间窗的其他成功文件当本轮证据。
- `cleanup_confirmed=false` 的有效报告，或实际仍有后代存活/终止状态不明，必须把该 entry 记失败并停止后续 gate；J1 是当前尾项也保留此通用停止规则。不能只有 child exit 非零就继续收集，遗漏 J1 自报的清理不确定事实。
- 子进程 exit 0 但报告缺失、非 passed 或 claims 不符：entry 改为 failed。
- 子进程非零不能被 passed 报告覆盖。
- 不把报告缺失升级成 runner 输入错误。
- G13 原三个结论保持独立，不由 J1 claim 覆写。

累计证据：

- 新 record `schema_version=2`。
- 新增 `source_snapshot_policy_version=2`、`j1_report`、`j1_report_reason`。
- 保留 G13 字段和其他现有字段。
- 新 run 输出到 `v8/regression/evidence/<run-id>.json`。
- 历史 `v8/compat/evidence/j0/` 原样保留。

`execute_suite()`、`run_child()` 的公开签名不因 J1 改成通用执行框架。J1 自己负责外部 DSH 核验与启动，runner 仍只运行本仓 Python gate。

---

### 3.11 测试与验收

新增基础设施自检入口：

`uv run python v8/compat/test_host_pin_unit.py`

它不访问 PG、不要求安装 DSH、不联网，用临时 Git 仓库、假 executable、假报告和进程哨兵验证。

#### A. pin／准备器自检

- 正确 commit、detached、lock、工具链通过。
- 错 commit、attached HEAD、tracked dirty、额外未跟踪文件拒绝。
- pnpm 10.33.0 拒绝，不自动改用或下载另一版本。
- 缺 ready、缺 bin/lib、产物被改拒绝。
- 只有安装目录、没有成功凭证不能通过。
- 本地 clone 不修改源仓 branch／index／worktree。
- offline 缺缓存明确失败；下载 flag 不影响运行网络策略。
- 中断准备不产生 ready，失败目录不可续写成成功。
- 多个合格 preparation 的选择严格来自 DSH_SOURCE_ROOT；记录对应 id/ready hash，不取最新、不跨目录混用。准备/运行共享锁与人工清理独占锁互斥；运行目录不能被清理，封存安全准备报告后整目录回收不删历史证据。

#### B. profile／矩阵自检

- 未知 entry、额外 provider、JSONL/SQLite、live reload、home patch、overlay、三个 headless 固定绑定之外的 `!!js` 均拒绝；三个固定绑定还需逐字段核 runtime 实值。
- 缺 agents/agentDefaultModel/sessions 任一服务的 profile，或 agent-default-model 指向错误 provider/model，preflight 或 ready audit 必须给 PROFILE_INVALID；不以等到全局超时作为目标拒收证据。测试还覆盖只读取 YAML inject 而漏模块/static inject 的错误闭包。
- 同样 YAML 文本但模块目标不同必须改变或拒绝 startup identity。
- 配置变化、顺序变化、source/build 平面混用拒绝。
- runtime fallback 不得指向用户 master、其他 checkout 或第二 Cordis。
- catalog ID 缺失／重复／未知、错误 boundary、DB 加 dispatch 条件拒绝。
- optional 除唯一 smoke 外拒绝。
- 删除 UNSUPPORTED 负向或将 mandatory 改为 scope exclusion 拒绝。
- 六种能力组合产生规范允许的参加义务，Native passed 不替代 compat。
- J1 smoke 不能写入最小双 loop 的 passed。

#### C. 环境与证据自检

- 父环境放 provider、proxy、NODE_OPTIONS、DSH_HOME 等哨兵，Node 子进程只看到 allowlist。
- 父环境不被修改。
- 假用户 HOME、cwd、DSH_HOME 中的毒化配置不能被实际 smoke 读取。
- 原始日志打印哨兵后，仓库 JSON／报告中无原值。
- stale／truncated／未知字段/缺 mandatory check/重复 check/错误 invocation_id 报告拒收；既有或 symlink --report-json 目标与越界 artifact_refs 拒收，不读取或删除目标原内容。
- 原子写失败不返回成功。
- 新 run 不读取旧结果；失败记录不被成功 run 覆盖。

#### D. 实际 J1 验收

正式 `test_host_pin.py` 内完成：

1. 正向 built 官方 CLI smoke。
2. sandbox 隔离自检。
3. 独立临时负向 profile：额外 persistence／未允许插件在启动前被拒。
4. fake 未完成、额外调用、缺 final 的统计拒收。
5. 官方 CLI 中断／超时用例按 §3.7.3 短预算执行：从目标 ready 标记后计时/发信号，不能把 SIGTERM exit 0 记为完成；不把冷启动未达目标阶段误认为中断测试通过。
6. 前后输入与产物 hash 无漂移。
7. dispose、子进程结束、临时运行目录清理确认。

负向运行均使用本次临时配置和固定 fake，不更改正式 pin，也不调用真实 provider。关闭测试证明的是 host 生命周期，不是 V8 provider-confirmed cancellation。

#### E. runner 回归

更新 `test_baseline_runner.py`：

- 25 条精确 ID／顺序，原 24 条顺序不变。
- J1 唯一特殊绑定及 null DB。
- 拒绝 J2、外部 Node argv、其他 compat 脚本 null DB。
- TS/YAML/声明式 lock/sandbox 文件增删改进入 snapshot；名为 lib/dist/cache 的非产物源目录也必须进入；真正产物只落 .pgdata，不进入源快照。意外 v8/node_modules 拒绝，不能把依赖或漏测源当正常。
- J1 正常／缺失／无效／timeout／exit0 假报告；缺必填 check、换 invocation_id、越界引用拒收；cleanup_unconfirmed 即使 child 已退出也让后续假 gate 不启动。
- 外层 runner 超时能结束 J1 Node 子进程，无嵌套进程组泄漏。
- 原 G13 round-trip、环境、失败、中断及 fresh 语义全部保留。

不预设新的 PASS 行数量；实施后记录实际值。

---

## 4. 逐文件影响

下列是实施文件清单。DSH 仓所有文件只读，不产生上游修改。

| 文件 | 新增／修改内容及原因 | 依赖 |
|---|---|---|
| `docs/plans/v8-j1-dsh-pinned-host-plan-2026-09-17.md` | 用完整计划替换调查稿；记录 Mid-flow 与审查结果，不伪写实施完成 | 本文 |
| `v8/compat/host/pins/dsh-0d1f50007f9b-j1-v1.json` | 固定 source/tool/session/profile/fixture 输入身份 | W1 |
| `v8/compat/host/host_pin.py` | pin、准备凭证、环境、hash、matrix、报告校验共用逻辑 | pin/schema |
| `v8/compat/host/prepare_host.py` | 独立 clone、冻结安装、构建、immutable ready 凭证 | 共用模块 |
| `v8/compat/host/tsconfig.json` | fixture/inspector 严格 ESM 编译；不打包 Cordis | pin 的 declarations |
| `v8/compat/host/profile/package.json` | 自定义 startup profile；空 bundles、明确 resolver dependencies | 静态闭包核验 |
| `v8/compat/host/profile/cordis.patch.yml` | 显式最小 core、官方 headless、J1 fixture 条目；无 persistence | allowlist |
| `v8/compat/host/profile/plugin-allowlist.json` | 完整 bootstrap/profile entry、service 和模块来源允许清单 | 静态闭包核验 |
| `v8/compat/host/src/profile-inspector.ts` | 复用官方合成及解析 API；输出 profile lock，不启动应用 | profile、built app-boot |
| `v8/compat/host/src/fake-llm.ts` | 两次确定性生成的 `LlmAdapter` | pin LLM 类型 |
| `v8/compat/host/src/noop-tool.ts` | 无副作用工具注册及 disposer | pin tools 类型 |
| `v8/compat/host/src/smoke-audit.ts` | fixture 注册、ready/tree/session/final/dispose 观察；安全摘要 | 前两 fixture、headless 生命周期 |
| `v8/compat/host/sandbox/macos.sb` | macOS runtime 禁网络策略 | runtime supervisor |
| `v8/compat/required-support-matrix.v1.json` | provisional 义务全集；只引用受控 catalog ID | 规范、现有 catalog |
| `v8/compat/test_host_pin.py` | J1 正式独立 Python gate；官方 built CLI smoke 和证据 | 准备器、profile、matrix |
| `v8/compat/test_host_pin_unit.py` | 无 DB／无 DSH 基础设施自检 | 共用模块、gate 接口 |
| `v8/compat/pinned_host_manifest.json` | 仅填验证过的 package/Node，链接 bootstrap 证据；保留 compat 未解析 | 首次合格 smoke |
| `v8/regression/run_baseline.py` | 精确 J1 接纳、snapshot 扩展、read_j1、schema-v2 累计记录和新输出目录 | J1 报告接口 |
| `v8/regression/test_baseline_runner.py` | 新清单／快照／报告／进程树拒收测试；保留原自检 | runner 变更 |
| `v8/regression/v8-gates.json` | 原 24 条后追加 J1，DB=null | J1 gate |
| `v8/compat/README.md` | J1 准备/运行命令、隔离、memory-only 边界、证据解释 | 最终实际结果 |
| `v8/README.md` | 25 条累计 inventory、J1 命令、准备前置和新证据目录 | manifest/runner |
| `docs/reviews/v8-p0ab-conformance-matrix-2026-09-16.md` | #12/#16 等引用 J1 事实；真实 compat/IO 缺口不升绿 | 最终证据 |
| `docs/reviews/v8-p0ab-deviation-ledger-2026-09-16.md` | 追加 J1 边界与剩余义务，保留历史记录；实施时按现有编号续写 | 最终证据 |
| `docs/reviews/v8-j1-dsh-pinned-host-<实施日期>.md` | 人读实跑报告、命令、hash、失败/恢复历史、准出限制；用实际实施日期，不回填成计划创建日 | 最终有效 run |
| `v8/compat/evidence/j1/<run-id>/*.json` | 实施时生成的 source/build/profile/startup/report 五件记录 | 每次真实 gate |
| `v8/compat/evidence/j1/preparations/<preparation-id>.json` | 准备报告安全副本、不可变 identity/hash/退出状态；缓存回收不删它 | 每次准备封存 |
| `v8/regression/evidence/<run-id>.json` | 实施时生成的 25-gate fresh 累计证据 | runner |

明确不改：

- `v8/compat/p0c_report.py`
- `v8/compat/test_compat.py`
- `v8/compat/setup_db.py`
- `v8/load.py`、任何 V8 SQL、生产 runtime
- `docs/designs/v8-dev.md`／V10 冻结正文
- 用户 DSH master、DSH AGENTS 或 package manifests
- J0 历史证据和实跑报告

已核查 `v8/compat/test_compat.py:1323–1326`：实际断言是 pinned_unresolved 非空且三结论 false，并非固定六项计数。因此本计划不需要修改 G13 测试；继续以直接 G13 回归验证保留的未解析项和 REAL blocked。未来若源码另有变化，先重新核对，不能因此放松报告公式或能力声明。

---

## 5. 风险、兼容与取舍

### 5.1 报告兼容

- 产品 P0C 报告继续 schema v2，字段和公式不变。
- 累计 runner 记录升级 schema v2，原因是新增 J1 报告及快照策略；历史 schema-v1 JSON 只读保留。
- 新 runner 不把旧 source digest 与新策略 digest 直接比较。
- 旧 runner 看到新增 J1 manifest 应明确拒绝，而不是跳过 J1 后宣布累计通过。
- 不涉及数据库或 DSH session format 迁移；J1 不产生 durable session。

### 5.2 主要风险及处理

| 风险 | 处理 |
|---|---|
| headless 的 required closure 隐含持久化／网络插件，或漏 module/static inject 与 model selection | W1 核全部声明和消费，ready 检查 agents/agentDefaultModel/sessions；缺项给 PROFILE_INVALID，不等到 timeout；禁止后端不可替身绕过 |
| host-face 构建比预期大或需要未列 native 前置 | 报告真实失败和缺失项；不临时改为 source 准出，不默认扩到全仓 build/test |
| 复制 fixture 后解析到错误 Cordis/Loader | 记录 realpath、exports 和产物 hash；双实例来源拒绝 |
| profile dump 与实际挂载不同 | preflight compose 与 runtime Loader entries 双检，fake 执行前 ready 门 |
| 环境无 key 但加载用户 `.env`／proxy | 空环境 allowlist、临时 cwd/HOME/DSH_HOME、OS 禁网络 |
| SIGTERM exit0 被误判成功 | 额外要求 final、统计、dispose 和非中断事实 |
| Node 子进程逃出 runner 清理组 | gate 内不新建 session；真实进程树回归 |
| 新 evidence 引用引发 source hash 循环 | 首次证据用于固定 manifest；最终累计 run 不回写源 manifest |
| J1 smoke 被冒充 compat 最小 turn | 独立 `bootstrap_only` schema，相关产品 claims 固定 false |
| 支持矩阵随 profile 缩小 | obligation 与 capability 条件分离；所有 catalog ID 参加，分类变更新版本 |
| 同源码不同构建被当同一产物 | build identity 按实际产物摘要区分；缓存 hash 不匹配拒绝 |

### 5.3 取舍

- **memory-only 优于临时 persistence provider**：既复用官方能力，又不提前决定 J4 的事件权威与恢复模型。
- **显式小 profile 优于对 shipped base 做大面积 disable**：新增默认插件不会悄悄进入启动范围。
- **built CLI 优于 source-only smoke**：覆盖实际 exports、bundle 和单实例关系，但接受 full host-face 构建成本。
- **准备与 gate 分离优于 gate 自动安装**：累计回归无下载副作用，失败可重复定位。
- **OS 禁网络优于只删凭据**：无 key 也可能存在外部任务或网络副调用。
- **复用 catalog ID、另列 leaf obligations 优于改写 reporter**：J1 能固定未来覆盖要求，又不创造第二套当前通过结论。
- **V8 专用 runner 精确加一个 J1 特例优于通用任务 schema**：当前只需一个无 DB 的 host gate，没有通用执行平台需求。

---

## 6. 实施顺序、验收与提交

以下均是**实施阶段的命令与顺序，不表示本轮已执行**。

### 1. 核对四项已批准决策与设计审查

- 记录批准或修订结果。
- 检查 pg-agent HEAD/status，保留所有无关未跟踪文档。
- 不重跑 J0 来证明已有历史事实。
- 确认没有其他进程运行共享 V8 测试库。

### 2. 固定 W1 输入与最小闭包

只读核验缺失源码点，完成：

- pin JSON。
- profile manifest／patch／allowlist。
- fixture 与 inspector 的类型依赖。
- provisional support matrix。

先实现纯解析／校验及无副作用测试：

```bash
uv run python v8/compat/test_host_pin_unit.py
```

这一步可独立测试；没有 DSH 准备产物时不得假跑正式 smoke。

### 3. 实现准备器并执行冻结准备

Node/pnpm 路径为实施机器实际安装位置，必须分别返回精确版本。使用不合格 PATH pnpm 时准备器应立即失败。

```bash
uv run python v8/compat/host/prepare_host.py \
  --source-repository /Users/wxl/Projects/deepseek-harness \
  --node-bin "$NODE_24_13_1" \
  --pnpm-bin "$PNPM_11_7_0"
```

上述是不下载的诊断方式。用户已于 2026-09-18 授权准备阶段显式下载；正式准备推荐使用下面带 flag 的命令，不需要因普通锁定依赖下载再次询问。权限只覆盖精确工具版本及锁定依赖，不授权真实 provider 调用或更换 pin：

```bash
uv run python v8/compat/host/prepare_host.py \
  --source-repository /Users/wxl/Projects/deepseek-harness \
  --node-bin "$NODE_24_13_1" \
  --pnpm-bin "$PNPM_11_7_0" \
  --allow-dependency-download
```

准备器内部固定执行冻结安装、host build、CLI override、fixture 编译。原始日志只在私有目录；输出合格 `DSH_SOURCE_ROOT` 和 preparation ID，不打印敏感环境。

构建失败修根因后新建 preparation，不在失败目录追加成功凭证。

### 4. 实现并运行 W3 官方启动 gate

```bash
export DSH_SOURCE_ROOT="<准备器输出的独立 source 目录>"

uv run python v8/compat/test_host_pin_unit.py
uv run python v8/compat/test_host_pin.py
```

必须取得 built 官方 CLI、网络隔离、memory-only、tree、final、dispose 和清理证据。

源码 CLI 只可作为隔离环境中的诊断运行；诊断结果不能替代本步骤。

### 5. 固定 bootstrap 引用并执行 G13 直接回归

首次合格 J1 证据产生后：

- 更新 `pinned_host_manifest.json` 的 package／Node 及 bootstrap 引用。
- 保留三个正式 compat pin 项、dispatch 未解析和 switch unsupported。
- 禁止 test gate 自动更新该文件。

运行：

```bash
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u UV_ENV_FILE \
  UV_NO_ENV_FILE=1 uv run python v8/compat/test_compat.py
```

核对：

- keyless fake 仍 passed。
- optional smoke 仍 not_run/not_requested。
- REAL 行不被 J1 解锁。
- 三个结论仍 false。

### 6. 原子落地 W5 runner 集成

以下必须一起保持一致：

- `run_baseline.py`
- `test_baseline_runner.py`
- `v8-gates.json`
- `v8/README.md` inventory
- J1 `--report-json` 固定接口

运行：

```bash
uv run python v8/regression/test_baseline_runner.py
uv run python v8/compat/test_host_pin_unit.py
```

不得先提交新 manifest、后提交不能识别 J1 的 runner。

### 7. 执行变更后的完整累计 fresh suite

准备产物已经就绪，累计 runner 不负责安装：

```bash
uv run python v8/regression/run_baseline.py \
  --manifest v8/regression/v8-gates.json
```

准出要求：

- 同一 fresh run 的 25 个 required entry 全部 passed。
- 每项只有一次 attempt，无自动 retry、无 resume。
- G13 与 J1 安全报告有效。
- 无中断、source drift、artifact drift 或 cleanup_unconfirmed。
- J1 未访问数据库；原 24 项仍按原顺序串行重建各自测试库。

有红项时保留该 run，修复后另起完整 fresh run，不拼接不同 run 的绿项。pnpm 缺失、sandbox 不可用或报告缺失也不能作为 skip 准出。

### 8. 收尾文档与证据封存

更新：

- compat README、总 README。
- Conformance 矩阵和偏差台账。
- 新 J1 人读报告。
- 计划的实际验收状态。

人读报告必须包含：

- 两仓身份、Node/pnpm、session format。
- preparation/build/startup identity。
- profile 与 support matrix 版本/hash。
- 实际命令、退出码、时间、清理状态。
- J1 单独证据及最终累计 JSON 路径/hash。
- J0 历史基线和本次新基线的区别。
- 尚未完成的 PG adapter／dispatch／dual-loop／P0C 范围。
- 实际发生的失败与重跑，不抹除诊断历史。

纯文档收尾后重新比较 `run_baseline.source_snapshot()` 与 final JSON 的 snapshot，检查证据 hash 和 README inventory。若 Python／TS／YAML／pin／matrix／manifest 等被测源变化，必须重新自检并跑完整 fresh suite。

```bash
git diff --check
git status
```

### 9. J1 一次完成提交与推送

仅在测试全绿且收尾工件齐备后：

```bash
git add <逐个明确列出的 J1 文件路径>
git status
git diff --cached --check
git diff --cached
git commit -m "v8: pin DSH host and verify keyless official startup"
git push origin main
```

- 禁 `git add .`／`git add -A`。
- 不提交 `.pgdata`、准备 checkout、node_modules/lib、原始日志或任何疑似凭据。
- 不提交无关／上位未跟踪文档。
- 不跳 hook、不 force push。
- push 被拒先 fetch 核对；若上游改变被测源，按影响重新验证。无法安全处理分歧时停止。
- 最终 commit/push 结果写实施交付消息，不回填证据形成自引用提交循环。

### J1 准出清单

- [x] 四项 Mid-flow 决策已落实，设计审查意见已处理。
- [ ] 独立 detached clone、完整 commit／tree／lock／工具链身份核验通过。
- [ ] 冻结安装、host-face／CLI／fixture 构建实际完成，产物摘要可复核。
- [ ] 官方 built CLI／Loader／headless／agent-loop 完成 startup smoke。
- [ ] memory-only、零 SessionPersistence、无第二 session 真相。
- [ ] 临时环境、禁网络策略、无真实凭据、profile 输入与模块来源验证通过。
- [ ] final、调用次数、正常 dispose、超时／信号清理正负向通过。
- [ ] provisional 支持义务矩阵完整，未借 profile 裁剪减少义务。
- [ ] PG adapter、正式 compat profile/canonicalizer、dispatch 前置验证仍诚实未完成。
- [ ] runner 与 J1 基础设施自检通过；同一 fresh run 25/25，源与产物无漂移。
- [ ] README／覆盖矩阵／偏差台账／人读报告与同一有效证据一致。
- [ ] J1 按路径一次完成提交并推送；DSH 用户 master 未修改。

## 7. 参考与接缝索引

DSH 路径以下均相对 `/Users/wxl/Projects/deepseek-harness`，对应固定 commit；pg-agent 路径相对交付仓。行号用于定位，身份以文件摘要和符号为准。

| 来源 | 约束／接缝 |
|---|---|
| pg-agent `AGENTS.md:9–76` | gate 全绿、工件、按路径提交推送；外部 IO 不进事务 |
| `docs/plans/v8-dsh-v10-joint-readiness-plan-2026-09-17.md` §4 J1/J2、证据 E01 | 本计划上位范围；J2 dispatch/resume/event 探针不提前做 |
| `docs/reviews/v8-j0-keyless-baseline-2026-09-17.md:5–19,55–73`；commit `11c600cf89e833269d92792f9a9831db21788e4a` | J0 实跑证据已提交，本轮不重新宣称运行 |
| `docs/designs/v8-dev.md:753–812,819–838,858–871` | pin、两维能力、P0C 和禁止把降级当 portable |
| `v8/compat/p0c_report.py`：`CATALOG`、`effective_blocked`、`pinned_unresolved_items` | catalog/blocked/未解析约束的唯一既有来源 |
| `v8/regression/run_baseline.py:78–128`：`load_manifest`、`source_snapshot` | J1 精确注册、DB=null、TS/YAML/策略快照扩展 |
| DSH `AGENTS.md` 的 Application launch/源码与产物平面规则；`package.json:1–25` | 官方 profile 启动、固定工具链和 host-face 构建 |
| DSH `tsdown.config.ts:16–32`；`apps/cli/tsdown.config.ts:1–18` | host workspace 含 desktop 包；CLI override bundle 入口 |
| DSH `apps/cli/src/bin.ts:27–64`；`apps/cli/src/profile-boot.ts:48–67,231–253,299–413` | CLI、profile 合成、冻结环境、启动/关闭、appReady |
| DSH `packages/boot/app-boot/src/profile.ts`：`PROFILE_TEMPLATES`、`loadProfile`、`composeEntries` | startup profile、fallback、合成及路径身份 |
| DSH `packages/bundle/headless/cordis.patch.yml:20–31`；`src/index.ts:309–399`；`src/startup.ts:95–120` | 官方 headless 两插件与固定配置绑定、task、whenIdle、flush、退出 |
| DSH `packages/boot/cmdline/src/index.ts:43–91` | appReady.onReady 是同步 void listener，不是 awaitable hook |
| DSH `packages/core/agent-loop/src/index.ts:729–735,849–862`；`packages/core/session/src/types.ts:88` | 无后端 create、resume 拒绝、session format=3 |
| DSH `apps/cli/tests/profiles/headless/tests/fixtures/cli.patch.yml:1–37` | 禁用 runner、保留 JSONL 的上游 smoke 不能当本计划入口 |

## 8. 基线内容覆盖与纠正台账

本表只记录可审查的覆盖关系，不包含原始 agent 输出。原 context_builder export 已用于设计审查与最终 fidelity 核对并在核对通过后清理；只有生成计划正文是保留基线，prompt/选中文件回显不是计划。

| Export 基线 | 本计划落点 | 保留／纠正依据 |
|---|---|---|
| §1 完成边界、三项待决 | §1 | 完成/禁止声明全保留；用户 2026-09-18 四项确认覆盖原待决，并将 Linux 实施移出范围 |
| §2 基线、链路、runner 6处差距、复用与禁用 | §2/§7 | 全保留；补 J0 已提交、当前并行文件事实及可核代码定位 |
| §3.1 工作项 | §3.1 | 六内部工作项及依赖全保留；增加 Goal/Done when/Key files/Dependencies/Size 执行索引 |
| §3.2 pin/schema/三层身份/manifest/自引用 | §3.2 | 具体字段、immutable 版本、bootstrap 与正式 compat 分层、先证据后累计全保留 |
| §3.3 准备接口/锁/clone/layout/源摘要/CI来源 | §3.3 | 全保留；本地成功不冒充远端可取同 commit |
| §3.4 工具/安装/构建/缓存/待核源码 | §3.4 | 全保留；host-face 实际含 desktop 包，纠正“不构建 desktop”；下载授权已获批，不重复等待普通依赖授权 |
| §3.5 profile/闭包/解析/合成hash | §3.5 | 全保留；原 blanket 禁 !!js 与官方 headless 三绑定冲突，改精确允许这三个绑定并核实值 |
| §3.6 fake/noop/audit/ready/dispose | §3.6 | 调用次数、final、实例所有权全保留；补 appReady 同步 listener 与 headless 不等待它的真实顺序，要求执行入口 promise 门且 apply 不等待 |
| §3.7 环境/OS网络/信号/进程组/日志/清理 | §3.7 | 安全与生命周期义务全保留；仅按用户平台决议删除 Linux 策略实现，不降低 macOS 禁网络与负向验证 |
| §3.8 matrix schema/30ID leaf/六能力组合/版本 | §3.8 | 全保留；boundary 使用真实 catalog 值，owner_gate/verification_gates 明确主责与回归责任 |
| §3.9 CLI/20错误码/退出/证据5件/失败归档 | §3.9 | 全保留，安全报告不是第二 session 日志；用“既有输出拒绝+本次 invocation_id”取代删除任意旧文件，同样防 stale，增加字段/工件完整性及清理后封存 |
| §3.10 runner 注册/快照/报告/输出迁移 | §3.10 | 全保留，旧schema和证据不覆写，J1/null特例不泛化；所有生成物在 .pgdata，不再用全局 lib/dist 裸名排除被测源 |
| §3.11 A–E测试 | §3.11 | pin、profile/matrix、secret、进程、runner各验证点保留；对应具体纠正同步更新 |
| §4文件所有权、不改清单 | §4 | 全保留适用文件；G13 实际只核 unresolved 非空，不需要预留改变其断言的口子 |
| §5风险/兼容/7取舍 | §5 | 全保留；不把动态未知写成已证实 |
| §6顺序/9步/准出/一次提交 | §6 | 全保留；四项已批准决策与明确准备下载命令同步；本轮仅计划不触发实施完成提交 |

## 9. 审查收口与剩余问题

一次 design 审查于 2026-09-18 完成。原审查记 2 P1、4 P2、2 P3；父级逐项核验并处理，不把原 finding 原封不动当作事实，也不声称做了第二轮独立复审。

| 项 | 最终处置 |
|---|---|
| F1 闭包 | headless 模块本就声明三项 required 服务，纠正审查“未声明”前提；计划明确合并 entry/module/static inject 并核实际服务，增加缺项拒收 |
| F2 selection | 固定 agent-default-model、fake route/disposer、agent-loop 空 roster、tool output/render，补错误 selection 测试 |
| F3 第四个表达式 | tools.mode 固定 native；环境读取表达式明确排除，只有官方三绑定可用 |
| F4 责任归属 | 矩阵表首项主责、余项验证数组，规则可机械生成，禁止 JSON 斜线值 |
| F5 漂移漏源 | 生成物全部在 .pgdata，不用全局 lib/dist 排除；同名源目录及声明式锁加入自检 |
| F6 缓存生命周期 | 精确 preparation 选择/id/hash、读写锁、人工整目录回收、安全报告保留 |
| F7 blocked 计数 | 区分 G13 当前①–⑥与 reporter允许①–⑦，不自动注入 optional 凭据诊断 |
| F8 时间预算 | 内部210秒、外层240秒，短负向倒计时以状态标记为起点，不因冷启动制造假绿 |

最终 fidelity 已逐项核对 §8：适用基线内容均保留或按代码／用户决议作具名纠正。附加安全细化为全部 runtime Node 子程序禁网络、已安装依赖/资源闭包摘要、先确认清理后封存、私有 invocation_id 与完整 checks 校验；不改变 J1 产品范围。

**无仍需用户裁定的材料性设计问题。** 精确插件闭包清单、构建/native 前置的实际可用性、sandbox 自检与时长是实施必须产出的测量，不是当前已通过；任何不满足按明确失败条件停止，不私改 upstream、不退回 source-only，不提前解锁 PG/dispatch/dual-loop/P0C。下一工作流建议 `rp-build` 按 W1–W6 串行实施；如用 `rp-orchestrate`，仅并行不共享写入文件的准备工作，公共 runner/manifest/README 集成保持单写者。

本轮只交付本计划及流程审查工件，不暂存/提交产品里程碑，不修改两仓代码；未来 J1 全绿、收尾齐备后须按 §6 立即一次提交并推送。

