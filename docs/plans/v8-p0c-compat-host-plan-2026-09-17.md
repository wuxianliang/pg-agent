# V8 P0C（dsh-compat 真实运行半边）开发计划 · 2026-09-17

> **定位**：v8 的 `docs/designs/v8-dev.md` 除 P0C 真实运行半边外已全部实现（G1–G19b 共 24 条 gate，见 `v8/README.md` 运行块）。本计划**只**处理 P0C——接入 pinned DSH Node host，证明「一个最小 turn 在两个运行时产生相同 observable trace」。规格原文唯一权威；`docs/analysis/v8-impl-digest/` 只作入口摘要。
>
> **本次调查的关键突破**：长期记为「未确认（用户决策）」的 pinned DSH Node host，**已识别为 DeepSeek Harness**（见 §0.1）。A85 的 blocker 从「不知道是什么」变为「确认走哪条发布线」。§5.2 的 go/no-go 也从「无从下手」变为有明确技术画像（§0.3）。

---

## 0. 调查结论（现状基线）

### 0.1 pinned 上游已识别：DSH = DeepSeek Harness

`@deepseek-ai/dsh-*` npm scope，上游仓库 `github.com/deepseek-ai/deepseek-harness`（维护者 `tianyicui-deepseek@deepseek.com`），内核 `@deepseek-ai/cordis` 4.x。规格 §5 的接口名与之一一对应，可确认规格即照此写成：

| 规格措辞 | DSH 实体 |
|---|---|
| `apply(ctx)` / `ctx.on(..., next)` / Cordis 内核 | `@deepseek-ai/cordis` ^4.0.x |
| `defineTool` / `DefineToolOptions` / `ctx.tools.register` | `@deepseek-ai/dsh-tools` |
| persistence-pg（§1.1「替换 persistence/storage provider」） | `ctx.sessionPersistence`（`@deepseek-ai/dsh-session-persistence`）+ 其 PG 实现 |
| storage-pg / storageDomain | `ctx.storage`（`@deepseek-ai/dsh-storage`） |
| §5.1 全部 DSH/Cordis 输入事件 | `@deepseek-ai/dsh-session` 的 `SessionEventMap` |
| `load()` 合成 tool/result + turn/end interrupted | `turn/end{reason:'interrupted'}`——文档原话「The loop never emits this marker」，即后端合成 |
| §5.2 `PersistenceCoordinator` | `@deepseek-ai/dsh-session-persistence/coordinator` |
| `tests/contract.ts`（storage 合同套件） | `@deepseek-ai/dsh-storage` 的 contract 套件 |

**推论**：`docs/investigations/cordis-workbench-plugins-2026-08-22.md` 记载「web 探测被引向 DeepSeek harnesses、当时判为误引」——**该判断是错的**：DSH 就是 DeepSeek Harness，探测方向正确。该文档的 Cordis 结论（v1 的 Cordis 是 SQL 元编程）仍成立，但两者是不同的东西，勿再混用「Cordis」一词。

### 0.2 包清单与发布线（2026-09-17 实测）

| 包 | 角色 | 发布线（dist-tags） |
|---|---|---|
| `@deepseek-ai/dsh-headless` | **最小 turn runner**——「a direct core Agent/Session runner over dsh-base with no Host, HTTP, or browser layer」 | `latest` 0.0.1-rc.1 / `next` **0.1.5-rc.2** / `alpha` 0.1.6-alpha.1 |
| `@deepseek-ai/dsh-base`、`dsh-agent`、`dsh-session` | 内核（Agent/Session/事件存储） | 同上（`dsh-agent` 的 `latest` 是 0.1.0-rc.6，与家族其余不同） |
| `@deepseek-ai/dsh-session-persistence` | **要实现的 seam** `ctx.sessionPersistence` | 同上 |
| `@deepseek-ai/dsh-storage` | `ctx.storage` hub | 同上 |
| `@deepseek-ai/dsh-tools` | tool registry + 执行管线（含 `tools/pre-execute`） | 同上 |
| `@deepseek-ai/dsh-llm` / `dsh-llm-deepseek` | LLM seam / DeepSeek adapter | 同上 |
| `dsh-postgres-backends` | **第三方**（`weisanju`，非 deepseek-ai scope）PG provider 家族 | 仅 `0.1.0-beta.18` 一条线 |
| `dsh-compat`（`tudamu`） | 社区插件 × DeepSeek Harness 版本兼容矩阵 | 0.0.1 |
| `@deepseek-ai/cordis`、`@deepseek-ai/schemastery` | DI 内核 / 配置 schema | cordis `latest` 4.0.2 |

**已实测的版本线冲突（重要）**：裸 `npm install @deepseek-ai/dsh-headless dsh-postgres-backends` **解析失败（ERESOLVE）**——`dsh-headless`（`latest` 线）peer 钉 `^0.0.1-rc.1` 家族，而 `dsh-postgres-backends@0.1.0-beta.18` 的 peer 钉 `@deepseek-ai/dsh-invariants ^0.1.0-rc.7`（解析到 0.1.0-rc.8）。改用 `next` 线（`@deepseek-ai/dsh-headless@0.1.5-rc.2`）**仍然冲突**：npm 的 prerelease 规则使 `^0.1.0-rc.7` 只接受 `[0,1,0]` 同位 prerelease，不含 0.1.5-rc.2。

→ 结论：**pinned 不是 `npm install` 一句话**。C1 必须显式钉版本并裁定冲突处理（见 §3-D4）。

### 0.3 §5.2 的技术画像（决定 go/no-go）

§5.2 要求：P0C 开始**之前**须验证官方集成点能否在**外部 IO 发出之前**把对应 effect 落成 `dispatch_started`。读上游类型声明得到：

- **tools 维有真 pre-IO hook**：`dsh-tools` 的 `'tools/pre-execute'(exec, next)` 文档原话 *"Allow, deny, or ask before dispatch."*；`'tools/execute'` 是 around-dispatch waterfall，`next()` 才跑 body。→ 监听 `pre-execute`、在调用 `next()` 前完成 v8 持久化，**即得 sync-before-IO**。
- **LLM 维只有 around-call**：`'llm/stream'(options, next)` 是「Waterfall around every streaming model call」；**不存在**独立的 `llm/request` pre-dispatch 事件。`next()` 之前 await 仍可行，但语义上是「调用的周围」而非「之前」。
- **会话日志本身不保证 sync-before-IO**：默认走 `SessionWriteBehind` 批写（`DEFAULT_WRITE_BATCH_MAX_DELAY_MS = 200`，后台写 + `flush()` barrier）；`turn/end` 文档原话 *"The loop does not await a flush at turn boundaries: `dsh-session-checkpoint-policy` owns the per-request durability checkpoint"*。
- **但存在合法逃生口**：`dsh-session-persistence` 模块文档原话 *"Third-party backends may implement the public persistence seam directly."* → v8 backend 可**不走 coordinator/write-behind**，直接实现 `SessionPersistence`，令 `append()` 在 v8 SQL 提交后才 resolve。
- **未探明项**：`dsh-session-checkpoint-policy`（`turn/end` 指名它 owns per-request durability checkpoint）不在本次探针集内，C2 必须补查——它很可能就是「IO 前落盘」的官方机制所在。

**初判**：tools 维可得 `sync_before_io`；LLM 维需 C2 实证。C2 的判定就是「三行表落哪一行」。

### 0.4 要实现的接口与事件词表

`SessionPersistence`（abstract class，`Context` 增补 `sessionPersistence`）九方法，**无 delete / 无 close**：
`locate(meta)`、`create(meta)`、`append(id, events)`（*"resolves only after durability"*）、`prepare(id, signal?)`、`load(id)`、`inspect(id, signal?)`、`readFrom(id, fromSeq, signal?)`、`list(signal?)`、`listSnapshots(signal?)`。

`PersistenceBackend`（coordinator 侧最小原语）为另一条路径：`loadStored` / `readStoredRevision` / `loadStoredFrom?` / `appendBatch`（*"MUST commit ATOMICALLY"*）/ `commitRepair` / `list` / `close?`。

DSH 事件词表（§5.1 映射源）：

| DSH 事件键 | payload |
|---|---|
| `turn/start` | `{turn}` |
| `turn/end` | `{turn, reason}`（`TurnEndReason` = `completed` / `aborted{cause}` / `blocked` / `error` / `max-tokens` / `interrupted`） |
| `step/start`、`step/end` | `{turn, step}` |
| `user/message` | `UserMessage`（surface 事件；三来源：人类 prompt / `agent.inject()` / goal 续轮） |
| `assistant/chunk` | `{turn, step, chunk}` |
| `assistant/message` | `{turn, step, message, usage?}` |
| `tool/call` | `{turn, step, callId, name, arguments}`（arguments 是**未经解析的模型原始串**） |
| `tool/result` | `{turn, step, message, error?, meta?}` |
| `todo/write` | `{todos}`（整表快照、last-write-wins） |
| `request/header` | `{header, reason}`（`initial`/`resume`/`change`）——文档注 *"appended inside its step before dispatch"* |
| `request/context` | `RequestContext` |
| `session/end-seed` | `{}` |

`compact/start`、`compact/end` **不在**核心词表内，由插件 merge 进来。

**映射缺口（本计划须裁定，见 §3-D9）**：§5.1 十六行表**没有** `step/start`、`step/end`、`request/header`、`request/context`、`todo/write` 五行。它们既不能静默丢弃（§5.1 末句禁止静默丢弃未知类型），也未必进 portable 比较。须逐行裁定去向（不落盘 / audit / compat-only / 扩表记偏差）。

### 0.5 现状基线

**已交付（G13，`v8/compat/`，偏差 A82–A89）**：

> **基线复跑（2026-09-17，本计划实测）**：`uv run python v8/compat/test_compat.py` → 退出码 0、**155 PASS / 0 FAIL**。文档侧记 **153**（`docs/reviews/v8-p0ab-conformance-matrix-2026-09-16.md` 表头、memory）——存在 +2 计数差异，**C1 对账时核正**（`v8/README.md` L74 已记该 gate 曾出现环境相关瞬时失败，疑为计数重立时点差异，非确定性回归）。

- `compat_adapter_manifests` 表 + `v_compat_manifest_register`（两维 capability 创建后不可变、NULL+note 配对、compat-only 显式清单）。
- `v_compat_unmapped_audit`（§5.1 未知类型统一 audit 命令，零控制态、不写语义结果事件）。
- `v_compat_matrix_blocked` / `v_compat_participation`（§5.2 两维矩阵 **SQL 单源**；GUC seam 仅驱动矩阵逻辑）。
- `v_compat_fork_cutoff_stable` / `v_compat_fork`（Conformance 11 (a) 三断言验收孪生）、`v_compat_begin_switch`（A83 已由 G18 收敛进共享 core）。
- **P0C 报告器** `v8/compat/p0c_report.py`：subcase catalog × 测试边界（DB / REAL）× 两维 capability；六类拒收；blocked 仅允许来自矩阵或 7 项外部 allowlist。
- §5.1 十六行映射**数据库层**、DeepSeek 凭据门控协议层（A87）。
- `pinned_host_manifest.json`：五件套 + §5.2 前置验证项**全部 null+note**。

**未交付（本计划范围）**：

1. **compat 侧 DB 层生命周期套件未接线**——报告器 catalog 中 clause 2/3/5/6/7/8/9/13/15 的 DB 行标 `implemented=False`（🟡 partial），gap 注记多为「compat 生命周期套件未接线」。
2. **§5.2 前置验证本体**（P0C 的硬前置，见 §2.1）。
3. **真实 compat host 本体**（Node host + v8 persistence/storage provider + §5.1 映射层 + dispatch 拦截）。
4. **跨运行时 trace 等值 harness**（同一 fake provider、同一 canonicalizer、双运行时比较）。
5. **全部真实 I/O 层子用例**（catalog 中 `REAL` 行）与 P0C 终签。

**环境事实**：本机 Node **v24.13.1** / npm **11.8.0** 可用；仓库**无** `package.json` / `tsconfig.json` / `node_modules` / vendored SDK。`v8-revision.md:380` 冻结的**外部兼容清单**（`zcordis-pgembed`、`pg_cordis`、DSH packages、`PersistenceCoordinator`、`DefineToolOptions`、`tests/contract.ts`、`deepseek-harness-sdk`）各项须落「用途 / 适用范围 / 版本·commit / 接口摘要 / 验证证据」，未知一律 `null + note`，未解析项存在时 P0 禁止宣称 compat contract 已过。

**一个必须先暴露的路线风险**：若 §5.2 判定 `after_io_only` 或 `none`，则**全部真实 I/O 层子用例与 P0C 主目标永久 blocked**，P0C 缩到「非执行型 T0 接口」——即本计划 C3–C6 整体作废，只剩 C0/C1/C2。因此 **C2 必须最先做**，用最小代价买下 go/no-go。

---

## 1. Stage 总表

Stage 命名用 `C0`–`C6`（与既有 `G*` 命名空间隔离）。C0–C1 **不阻塞**、现在即可做；C2 起阻塞于发布线裁定。

| Stage | 交付物 | 验收内容 | 阻塞 |
|---|---|---|---|
| **C0** | `v8/compat/lifecycle.py` + `v8/compat/test_lifecycle.py`（DB `agent_v8_compat`，复用 G13 库与加载集） | **compat 侧 DB 层生命周期套件接线**：以 compat driver（`dsh-compat`）身份经**共享命令面**（completion facade / seal / dispatch / cancel / repair / reconcile / append）驱动 clause 2/3/5/6/7/8/9/13/15 的 DB 层形态，逐条产出结果。**只接线、不改共享 SQL**——既有 24 条 gate 零回归 | 否 |
| **C1** | `v8/compat/p0c_report.py`（catalog 对账）+ `v8/compat/test_compat.py`（结果集补齐）+ `pinned_host_manifest.json`（包清单落值） | **catalog 对账 + pinned 包清单落值**：G10/G11/G17/G18/G19b 合并后 gap 理由已 stale 的行（见 §4）逐条翻新；`implemented` 标志按 C0 实况翻转；**G13 断言计数 153→155 差异核正**；`compat_contract_passable` 判据收紧裁定（§3-D1）；把 §0.1/§0.2 的包清单与其 dist-tag 落入 manifest（`dsh_package` 等仍待 C2 确定具体版本） | 否 |
| **C2** | `docs/investigations/p0c-pinned-host-2026-09-*.md` + `pinned_host_manifest.json`（五件套转实证）+ `v8/compat/probe/`（Node 探针） | **pinned 五件套落值与 §5.2 前置验证（go/no-go）**：钉定发布线与版本 → 补查 `dsh-session-checkpoint-policy` → 实测「外部 IO 发出之前经 persistence 持久化 dispatch_started」的**三行判定**（tools 维 / LLM 维分别出结论）→ manifest `dispatch_interception` 从 `null+note` 转实证值；`v8-revision.md:380` 外部清单七项落「用途/范围/版本/接口/证据」 | **是（发布线裁定）** |
| **C3** | `v8/compat/host/`（Node/TS 工程）+ `v8/compat/test_p0c.py`（Python 伞形 gate） | **host 骨架 + 两个 provider**：`apply(ctx)` / `ctx.on(..., next)` / `defineTool`（对齐 `DefineToolOptions`）；**v8 persistence provider**（实现 `ctx.sessionPersistence`，直接 seam 不走 write-behind，见 §3-D7）；**v8 storage provider**（过官方 `tests/contract.ts`）；`sessions.driver='dsh-compat'` | 是 |
| **C4** | `v8/compat/host/src/mapping/` + `dispatch/` | **§5.1 映射层 + dispatch 拦截先于 IO**：十六行映射表逐行实现（写入路径列 MUST 遵守：语义结果类走 ledger facade、输入/观测类走公开 append、未知类型走 `compat_unmapped_audit`）；§3-D9 的五行星号缺口逐行落处置；`turn_id`/`step_id`/`effect_id`/`source_event_seqs` 分配；`tools/pre-execute` 监听器落 `dispatch_started` **先于**外部 IO | 是 |
| **C5** | `v8/compat/host/src/providers/` + `v8/compat/host/tests/trace/` | **同一 fake provider + 同一 canonicalizer + 双运行时 trace harness**：JS 侧 `FakeLLM`/`FakeTool` 与 Python 侧字节等价（seed = `sha256(seed_text)`，见 §3-D3）；JS 侧 canonical profile 与 G1 golden 字节等价（§3-D2）；同一 fixture 产出 native trace 与 compat trace，经同一 `normalize` 比较（chunk 折叠进所属 `assistant/message`） | 是 |
| **C6** | 真实 I/O 层执行 + P0C 报告终签 | **Conformance 真实 I/O 层执行 + T0–T4 参加面实测 + P0C 终签**：catalog `REAL` 行跑成 passed/failed；T0–T4 分级对社区包的参加面实测；报告 `compat_contract_passable == True`；**P0C 主目标**：最小 turn 双运行时同 observable trace | 是 |

**运行命令**（C0/C1 沿用既有约定；C3 起新增伞形 gate）：

```bash
uv run python v8/compat/test_lifecycle.py   # C0（compat DB 层生命周期套件）
uv run python v8/compat/test_compat.py      # G13 回归 + C1 对账
uv run python v8/compat/test_p0c.py         # C3–C6（伞形：驱动 host npm test + 报告器）
```

---

## 2. 依赖与顺序

### 2.1 C2 是唯一的 go/no-go 门

§5.2 原文：「**P0C 开始之前必须验证**：官方 Cordis / DSH 的公共集成点，能否在 LLM 或 tool 的外部 IO 发出之前，经 persistence-pg 把对应 effect 写成 `dispatch_started`」。三行判定结果直接决定 P0C 的**支持面**：

| 判定 | 后果 |
|---|---|
| `sync_before_io` | 全参加——C3–C6 全部按计划执行 |
| `after_io_only` / `none` | **真实 I/O 层整体 blocked**（含不含 in-flight tool 的单 turn fixture 的实际执行形态）；compat 支持面缩到**非执行型 T0 接口**（persistence/storage 契约测试 = 数据库层）；P0C 主目标不可达成，须向用户呈报并重新裁定范围 |

顺序**不可颠倒**：C0/C1（不阻塞，先清账）→ **C2（go/no-go）** → C3 → C4 → C5 → C6。C2 判定为降级时，C3–C6 立即停止，转为「降级运行时参加面」交付（manifest 落 `after_io_only`/`none` + 报告按矩阵记 blocked + 向用户呈报）。

**注意 tools 维与 LLM 维可能分离**（§0.3 初判：tools 可得、LLM 待证）。若最终为「tools 可 sync、LLM 不可」，须在 C2 报告里显式裁定这是否等价于 `sync_before_io`（矩阵是单一维度的 `dispatch_interception` 值，没有「半参加」形态）——**不得自行发明第五种取值**。

### 2.2 C0 与 C1 的关系

C0 交付「接线的套件」，C1 交付「对账后的 catalog/报告」。二者共改 `v8/compat/` 但**文件不重叠**（C0 新增 `lifecycle.py`/`test_lifecycle.py`；C1 改 `p0c_report.py` 的 catalog 与 `test_compat.py` 的结果集），可并行；合并序 C0 → C1（C1 的 `implemented` 翻转依赖 C0 实况）。

### 2.3 C3–C6 的工程轴

首次向仓库引入 Node 工具链，需一次性裁定并落定（见 §3-D4）：工程落点、锁文件是否入库、`node_modules` 进 `.gitignore`、Python 伞形 gate 如何驱动 `npm ci && npm test` 并把结果回灌 `p0c_report.build_report`。

---

## 3. 关键设计决策与需裁定项

**D1 — `compat_contract_passable` 判据是否收紧（建议：收紧）**
现状 `contract_passable = (not unresolved) and failed==0 and blocked==0`——**🟡 partial 行不参与判据**。C0/C1 完成后若仍有 partial 行，报告可宣称 passable 却存在未实现子句，与 P0C「完整报告」要求张力。**建议**：终签判据追加 `counts["partial"] == 0`，即每条 subcase 必须 passed 或来自矩阵的合法 blocked。

**D2 — canonicalizer 的跨语言归属（建议：JS 实现 + G1 golden 字节核对）**
规格要求「同一 canonicalizer」。三条路径：(a) JS/TS 重实现 canonical profile（step 0 转义 / NFC / tagged integer / JCS / SHA-256 / ES6 number 文本）；(b) 规范化下沉 DB（SQL 侧已有部分键函数）；(c) helper 进程调用 Python。**建议 (a)**——canonical 算法可移植，且 G1 已有跨语言 golden vectors 可直接作字节级核对输入；须显式处理 Python 侧已记录的偏差（NFC 顺序、闰秒、`$int` 歧义等，见 `v8/README.md` 已知边界末段），逐条对齐或记偏差。

**D3 — 「同一 fake provider」的等价边界（需在 C5 冻结）**
`FakeLLM` 输出由 `sha256(seed_text)` 唯一决定，且在 `prompt.tool_results` 非空 / `TOOL_MARKER` 两分支间切换。JS 侧复刻须同时满足：(i) 同一 seed 来源——即 compat 侧的 assembled prompt 必须与 native 侧**同源**（建议直接消费同一 SQL assemble 函数，而非在 host 内另建组装逻辑）；(ii) 同一 `prompt.tool_results` 判据。否则「同一 fake provider」名存实亡。

**D4 — 发布线钉定与依赖冲突处理（阻塞 C2，需用户裁定）**
§0.2 实测：`latest` 与 `next` 两条线互斥，且第三方 `dsh-postgres-backends` 钉在更旧的 prerelease 区间，裸装 ERESOLVE。三条路径：(a) 全量钉 `next` = `0.1.5-rc.2` 并用 `--legacy-peer-deps`/`overrides` 压过 peer 区间——**风险**：第三方后端对 0.1.5 线可能真实 API 漂移；(b) 全量钉 `latest` 陈旧线并自研 PG 后端——**风险**：`dsh-agent` 的 `latest` 与家族不一致；(c) 向上游确认「哪条线配套、第三方后端何时跟进」。**建议 (c) 优先、(a) 兜底**；无论哪条，C1 落锁文件、C2 出实证。另需裁定：锁文件入库、`node_modules` 入 `.gitignore`、`npm ci` 而非 `npm install`。

**D5 — `driver_switch_capability` 声明（需裁定）**
G13 种下保守声明 `unsupported`（A85）。G18 已交付完整正向切换，**数据库层**的 `c11-db-switch-positive` 现在可达；但声明 `supported` 会让矩阵要求真实 I/O 层的 in-flight 切换收束子用例。**建议**：C2 判定后一并裁定——`sync_before_io` 成立则声明 `supported`（全参加），否则维持 `unsupported`（强制负向 `UNSUPPORTED` 照常）。

**D6 — compat host 是否复用 native loop 代码（建议：不复用）**
规格明确 compat 跑**官方 loop**；复用 `v8/loop/runtime.py` 套壳即等于「以 Native 冒充 portable」（报告器 fail-class 3）。host 只经 SQL 协议连库、`driver='dsh-compat'`。

**D7 — 自研 v8 persistence provider，而非复用 `dsh-postgres-backends`（建议：自研）**
`dsh-postgres-backends` 是**第三方**实现，且写**它自己的** schema（自有 sessions 行 + batch 事件行），peer 实现而非桥接。而 §5.1 要求事件写入 **v8 自己的表**、且语义结果类必须**经 v8 命令路由**（completion/repair facade）。故 v8 provider 必须自研，实现 `ctx.sessionPersistence` 九方法；`dsh-postgres-backends` 降级为**参考实现**（以及 console/migration 的可选复用）。
附带收益：模块文档明确允许第三方**直接实现公共 seam**，从而绕开 coordinator 的 write-behind，令 `append()` 在 v8 SQL 提交后才 resolve——这正是 §5.2 所需（§0.3）。

**D8 — T0–T4 分级参加面的实测口径（C6 冻结）**
`docs/designs/v8.md` §3.2 的分级表（T0 零改挂 compat / T1 改配置 / T2 改走 storageDomain / T3 留 host 状态入库 / T4 替换或排除）需在 C6 落成可复现的实测清单，作为 `blocked:compat-only-t0-t4-participation` 的解锁证据。

**D9 — §5.1 事件词表五行缺口（需裁定）**
`step/start`、`step/end`、`request/header`、`request/context`、`todo/write` 五行**不在** §5.1 十六行映射表内。§5.1 末句禁止对未知 DSH 类型静默丢弃（须走 `compat_unmapped_audit` 或显式 `compat-only`），但这五行是**已知的官方事件**，不是「未知类型」。须逐行裁定：不落盘（如 fiber/isolate 先例）/ 落 `compat/unmapped` audit / 声明 `compat-only` / 扩表并记偏差。**不得沉默通过**。

**需用户裁定（阻塞 C2 开启）**：
- **发布线**（§3-D4）：走 `next` 线 + 压 peer 区间，还是等上游确认配套版本？
- 若 §5.2 判定降级：P0C 是否接受缩到「非执行型 T0 接口」并把主目标标为不达成。

---

## 4. C1 对账清单（gap 注记 stale 明细，2026-09-17 复核）

`p0c_report._catalog()` 中以下行的 gap 理由已被后续合并作废，C1 必须逐条翻新并复核 `implemented`：

| subcase | 现 gap 注记 | 实际状态 |
|---|---|---|
| `c8-db-generation` | 「P1 世代域（G11，本分支未合并）」 | **G11 已合并**（`v8/plugin/`，207 PASS） |
| `c13-db-yield-workspace` | 「workspace_handles 属 G10（本分支未合并）」 | **G10 已合并**（`v8/grant/`，144 PASS） |
| `c6-db-cancel-compact` | 「compact 三命令未实现（LATER）」 | **G17 已交付**（`v8/compact/`） |
| `c3-db-scan-recovery` | 「NOTIFY/队列唤醒层未实现」 | **G19b 已交付**（`v_wait_scan` 恢复权威） |
| `c9-db-hook-gates` | 「§4 runtime 完整面 LATER；RLS 面随 G10」 | RLS 面 **G10 已交付**；hook 超时仍 LATER（如实保留） |
| `c7-db-parallel-ordinal` | 「compat tools 套件未接线」 | 共享 SQL 合同 **G6 已交付**；缺的是 compat 侧接线（C0） |
| `c2-db-stale-writes` | 「compat 生命周期套件未接线」 | 共享 fence 合同 **G4/G7a 已交付**；缺 C0 |
| `c5-db-classification-orthogonal` | 「compat 侧分类套件未接线」 | 共享判定函数已交付；缺 C0 |
| `c15-db-cancel-fixtures` | 「fixture 字节级双运行时比较需真实 loop」 | DB 层 reducer 单元合同可先交付（C0）；字节级比较随 C5 |
| `c11-db-switch-positive` | 「driver 切换正向机制另行排期」 | **G18 已交付** `v_begin_switch_core` / `v_finish_switch_core`——见 §3-D5 |

**注意**：C1 是**对账**，不是「把 🟡 一律改 ✅」。凡 gap 理由仍成立的（hook 超时、真实 loop 依赖）如实保留；凡理由已作废且 C0 已接线的才翻绿。

---

## 5. 文件所有权

- **C0**：新建 `v8/compat/lifecycle.py`、`v8/compat/test_lifecycle.py`；只读全部既有 SQL。
- **C1**：`v8/compat/p0c_report.py`（catalog 与判据）、`v8/compat/test_compat.py`（结果集补齐）、`v8/compat/pinned_host_manifest.json`（包清单落值）；`v8/README.md` G13 行、Conformance 矩阵 `#16` 行、偏差台账 G13 块。
- **C2**：`v8/compat/pinned_host_manifest.json`、新建 `docs/investigations/p0c-pinned-host-*.md`、新建 `v8/compat/probe/`（Node 探针，不入 `v8/load.py`）；`v8/compat/setup_db.py` 中的 manifest seed 行（`dispatch_interception`/`driver_switch_capability` 随判定改写）。
- **C3–C6**：新建 `v8/compat/host/`（Node/TS 工程）、`v8/compat/test_p0c.py`；`.gitignore`（`node_modules` 等）；`v8/README.md` 运行块与已知边界、Conformance 矩阵 `#16`、偏差台账。
- **不改**：`v8/schema`、`v8/grant`、`v8/events`、`v8/effect`、`v8/tools`、`v8/retry`、`v8/repair`、`v8/cancel`、`v8/stream`、`v8/plugin`、`v8/gates`、`v8/audit`、`v8/compact`、`v8/drain`、`v8/reconcile`、`v8/assemble`、`v8/closeout` 的**任何生产 SQL 与测试**——P0C 是**消费方**，不得为迁就 compat 而改动已冻结合同。若发现共享面缺陷，**停下并单独立项**。

---

## 6. 收尾工件与提交规则

沿用 AGENTS.md 与既有计划：每 Stage 交付后 (1) `v8/load.py` 注册（本计划**预期不新增 SQL 文件**；若 C0 需新 SQL 才追加）；(2) Conformance 矩阵（`#16` 及其余受影响行）；(3) 偏差台账（G13 块续 A 系、消解 A85 的 null+note 项）；(4) `v8/README.md`（G13 边界句、运行块、已知边界）；另加 **C1 起新增**：`p0c_report.py` catalog 对账记录。

提交：一 Stage 一提交；提交前本 Stage 全部 gate + 直接受影响既有 gate 实跑全绿（C2 起含 `v8/compat/test_compat.py` 回归）；`git add` 逐路径（MUST NOT `-A`/`.`）；消息 `<版本>: <祈使句摘要>（CXX …）`；尾行 `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`；`git push origin main`（禁 force）。顺序不可颠倒：测试全绿 → 工件更新 → add → commit → push。

---

## 7. 准出判据

1. C0/C1 的 gate 实跑退出码 0，且**既有 24 条 gate 零回归**；
2. C2 产出三行判定并落 manifest 实证值；若判定降级，产出降级裁定报告并停止 C3–C6；
3. C3–C6（仅 `sync_before_io` 成立时）：`v8/compat/test_p0c.py` 退出码 0；
4. P0C 报告 `compat_contract_passable == True`（无 unresolved pinned 项、`failed == 0`、`blocked == 0`、且按 D1 裁定 `partial == 0`）；
5. **P0C 主目标**：最小 turn 在 native 与 compat 两运行时产生**字节等价**的 observable trace；
6. 每条 Stage 一提交、已 push origin main。

---

## 8. 风险

| 风险 | 说明 | 缓解 |
|---|---|---|
| **R1 §5.2 判定降级** | 官方集成点做不到 IO 前落 `dispatch_started` → 真实 I/O 层整体 blocked、主目标不达成 | C2 前置，用最小代价买 go/no-go；降级即重新裁定范围而非硬凑 |
| **R2 发布线冲突（已实测）** | `latest`/`next`/第三方后端三条 prerelease 线互斥，裸装 ERESOLVE；上游全为 rc/beta，随时可能再动 | C1 钉死版本 + 锁文件入库；C2 出实证；必要时向上游确认配套线（D4） |
| **R3 tools 维可 sync、LLM 维不可** | 矩阵只有单一 `dispatch_interception` 值，无「半参加」形态 | C2 报告显式裁定；不得发明第五种取值（§2.1） |
| **R4 canonicalizer 跨语言字节等价** | ES6 number 文本、JCS、NFC、tagged integer 的边角（含 Python 侧已记录的偏差） | 复用 G1 golden vectors 做字节核对；逐条对齐或记偏差，禁止「差不多」 |
| **R5 fake provider 不同源** | compat 侧若自建 assemble，DB truth seed 与 native 分叉 → 「同一 fake provider」失效 | D3：compat 侧直接消费同一 SQL assemble 函数 |
| **R6 仓库首次引入 Node 工具链** | 打破「纯 Python gate」约定；锁文件/依赖可复现性 | D4 一次性裁定；伞形 gate 保持退出码语义；`npm ci` 而非 `npm install` |
| **R7 为迁就 compat 改动冻结合同** | 共享面被改动 → 既有 24 gate 回归 | §5 文件所有权「不改」清单；发现缺陷单独立项 |
| **R8 §5.1 五行缺口沉默通过** | `step/*`、`request/*`、`todo/write` 未裁定即实现，可能以「未知类型丢弃」违反 §5.1 末句 | D9 逐行裁定并落台账；`compat_unmapped_audit` 为兜底，不得静默 |

---

## 9. 明确不做

- v10 上下文装配轨（另见 `docs/designs/v10-dev.md`）与 v8 的其余面——本计划**只**做 P0C。
- 把 compat host 做成第三个 native 循环（规格禁止：compat 是参考实现，不是第二条路线）。
- 为通过报告而放宽六类拒收、把 Native 绿记作 portable，或以 GUC seam 伪造 `sync_before_io`（A86 已明令）。
- `v8-revision.md:380` 外部清单之外的依赖引入。
