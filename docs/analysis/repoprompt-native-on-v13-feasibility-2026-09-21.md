# 基于 v13 原生仿制 RepoPrompt-CE:可行性调查与方案

> 日期:2026-09-21。性质:调查报告 + 方案草案(**未过评审,不是冻结稿**)。
> **已被 v2 取代**:`repoprompt-native-on-v13-feasibility-v2-2026-09-21.md`
> (Oracle 三轮裁决 + 用户拍板后合成)。本文件 §2/§5 的三处字面合同在 v2 作废:
> 「read_file/tree=sql 快路读盘」「workspace_context 近零新件」「R1 默认锁内行读」。
> 动机:当前 RepoPrompt-CE(MCP server)+ 多 provider 编排的形态,调用失败会
> 导致 agent 过程中断;目标是完全原生化——以 v13(Context on Postgres)为底座
> 重建同类能力,复用多语言成熟工具:
> repoprompt-ce(Swift,Apache-2.0)、sitting_duck / duck_block_utils(DuckDB 扩展)、
> tigerfs(pgembed 已打包)。
> 结论前置:**可行(go),且资产基础超预期;但工程主体不是「仿制层」,
> 是尚未开工的 v13 底座本身。** 另有三项已裁决策与用户设想存在冲突,
> 需在开工前显式收口(§7)。

---

## 0. 一句话结论

> v13 已经把「多语言 worker、effect 账本、工具目录是表、上下文是收据」全部
> 设计成 SQL 合同;RepoPrompt-CE 的功能面几乎每一件都能映射到既有概念件上;
> 真正要新写的只有三块——**文件/工作区平面、写面(编辑授权)、多 provider
> 的 llm effect 策略**——其余是「把 v13 底座先建出来」。

## 1. 痛点的结构解法:为什么原生化能消灭「过程中断」

当前失败链:MCP 桥(Claude ↔ RepoPrompt-CE)× 多 provider oracle × 长会话 =
任何一环超时/取消(MCPToolExecutionCancelledError×6 的血统,v13 轮 2 代行
即为实证)都会打断整个 agent 过程,且中断后进程内状态丢失。

v13 的对应物逐条消解:

| 当前失败模式 | v13 机制 | 为什么不再中断 |
|---|---|---|
| MCP 协议桥失败/取消 | 无桥:loop 住 PG(parse/advance),worker 是哑执行器 | 没有跨进程协议依赖;ch08「PG 本身就是 harness」 |
| provider 超时/限流打断全程 | llm 是 effect 行:claim/lease/fence/unknown | 失败=一次 settle(status=failed),session 状态机永不崩;advance 路由到重试/降级/默认分支 |
| 多 provider 切换与重试逻辑分散在编排层 | provider = 目录/策略行(数据);重试、熔断、降级链 = 版本化策略 | 换 provider=UPDATE 一行;重试策略一处执法(§6.1 证据/动作分离的同构) |
| 中断后过程状态丢失 | 状态全在行(events/effects/decisions) | 任何进程死在任何指令边界,扫描恢复;kill-at-every-boundary 是 gate 不是愿望 |
| 重试导致重复副作用 | effect_id=uuid v5 + idempotency_key + fence CAS | 同一逻辑动作同一身份;迟到结算 stale,重复投递 replay |
| 上下文重建成本 | context artifact + manifest(版本化执行收据) | exact replay 读旧件,零重建 |

**这不是「更稳的编排」,是错误模型的更换**:中断从「异常」变成「账本上一行
可观测的状态」。

## 2. 目标功能面 → v13 映射(仿制的真实形状)

按 RepoPrompt-CE 的工具面逐件映射(载体 = 建议归属;依赖 = 需要的前置):

| RP-CE 功能 | v13 原生载体 | 依赖 | 备注 |
|---|---|---|---|
| 多根 workspace | workspace_id 身份键 + file 表(v6.1 §3.1 合同原样) | 底座 | 隔离键是数据不是路径 |
| `read_file` / `get_file_tree` / `get_code_structure` | **sql 快路**(kind='sql',advance 同事务,零队列往返) | file 平面 | 行读优先;codemap=AST 投影视图 |
| `file_search`(正则/内容/路径) | 两选一:swift worker(RepoPromptRegexCore/PCRE2)或 duck_code;首版可先 PG `regexp`+trigram | file 平面 | 决策点(见 §7-4) |
| codemap(签名级结构) | duck_code:`read_ast`→投影;或 swift worker(RepoPromptCodeMapCore,tree-sitter 11 语言) | v13.1 M4 或 swift worker | 两条路线都通,量级不同 |
| `apply_edits` / `file_actions`(写面) | **mutating=true 工具走 unknown 纪律**;授权=v6.1 operation_authorization 形态 | 写面设计(全新) | 全方案唯一需要新设计文档的部分 |
| `git`(status/diff/log/blame/snapshot) | git worker(handler='git';或并入 swift worker) | worker | 全部外部 IO,账本纪律 |
| prompt / presets / `workspace_context` | **v13 正题近零新件**:selection=manifest sections,export=render 纯函数+策略行,tokens=est_tokens 汇总 | DP3 | 这就是上下文平面本身 |
| `ask_oracle`(多 provider) | llm effect × provider 目录行(模型/定价/缓存类);判断类走 pg_typesafe | 底座 | §5.4 经济学直接可用 |
| `agent_run` / `agent_manage` | sessions.parent_session_id 目标树(ch13)+ worktree worker | ch13+git | 子 agent=子会话,fork=ch14 |
| `manage_worktree` | git worker + workspace 平面 | 同上 | merge preview/apply=effect |
| `history` | events/effects 即查询 | 底座 | 免费件 |
| `ask_user` | kind='human' effect(human 档已在 ch02 词表) | 底座 | 干预面=events INSERT 不被阻塞(G-ctx1) |
| UI | 决策点(§7-1):RP-CE 本体 / dsh web / 先 CLI | — | 不进本方案 P0 |

## 3. 资产盘点(2026-09-21 实测)

### 3.1 设计与计划(全绿,但**零代码**)

- v13 设计冻结稿(2 轮 Oracle 裁决)+ DP1–DP8 八份已验收 plan +
  终检报告(无缺口无重叠)——**仓库无 `v13/` 目录,代码树未开工**。
- v13.1 工作台平面设计草案 v1 + 实施 plan 草案 v1(均 2026-09-21,未过 L4):
  三台两 bundle、逐台 Noul 选台、duck worker 六步合同。
- v1–v12 既有代码可复用(v6 duck 纪律 W1–W9、v8 effect 四件套、v12 双模一致性)。

### 3.2 外部组件(本地实测)

| 组件 | 状态 | 对本方案的意义 |
|---|---|---|
| repoprompt-ce | **开源 Apache-2.0**,本地 checkout,SPM 工程 1647 个 Swift 文件;targets 含 CodeMapCore(swift-tree-sitter,C/Go/Java/JS/Python/Rust/TS/Ruby/C#/C++/PHP)、WorkspaceCore、RegexCore(CSwiftPCRE2)、Shared、Executable、MCP;平台 macOS 26+ | Swift worker 的复用主体;核心 targets 疑似可 headless 链接(Executable 先例),需 spike 确认 |
| sitting_duck | 本地 checkout,MIT;`read_ast` 21 列 AST 表函数、ast 宏族、semantic_type、runtime 语言注册、完整 mkdocs | v13.1 duck_code 的引擎;文档有漂移,gate 按实测断言 |
| duck_block_utils | **无本地 checkout(缺口)** | v13.1 bundle B 依赖;需 clone+预构建+SHA-256 入 manifest |
| tigerfs v0.7.0 | Go 单二进制 CLI,pgembed 已打包(四平台 SHA-256 钉死),本机可运行;mount/unmount 生命周期 | 与现行裁决冲突,见 §7-2 |
| duckdb-swift | 本地存在(Swift↔DuckDB 绑定) | 潜在让 Swift worker 直载 duck 扩展;ABI/装载面需 spike |
| pgembed | 0.3.0rc2 / PG 18.4 / 14 扩展打包 | 部署单元 |
| deepseek-harness(dsh) | DeepSeek 官方开源 harness(TS/Cordis,一切皆插件,web UI) | 可选前端/UI 参考;P0C 的 C2 go/no-go 未做 |
| pg_typesafe | pre-alpha(Jev 原语 SQL 化) | 判断平面依赖;FakeJev/mock_response 可离线起步 |

## 4. 难点清单(按硬度排序)

1. **v13 底座未实施——工作量主体**。DP1–DP8 + v13.1 M1–M5 全部是计划态。
   仿制层站在其上;任何「先做仿制层」的路线都会旁路承重件(违反 §8 元原则)。
   缓解:计划已全部成文且经评审,实施是执行不是设计;按 §5 阶段序推进。
2. **写面(apply_edits/file_actions)是唯一的新设计**。v13.1 不变量 5 明确
   数据面只读;v6.1 B005/B006 裁决写能力需用户显式批准+独立 gate。文件编辑
   还要消化:授权粒度(路径/内容 digest)、检查点(enqueue 前/claim 后/提交边界)、
   mutating=true 的 unknown 纪律、CAS 合同(挂载点与行内容统一字节)。
   duck_block 的「编辑」能力在此面下才能启用(它负责结构化块变换,
   落盘仍走写面授权)。
3. **tigerfs 定位与现行裁决冲突**。ch7 已裁「文件=artifacts(行),tigerfs 台账」;
   用户设想 tigerfs 作 workspace_context 载体。两条路(§7-2)都要显式收口,
   不得静默违反冻结裁决。
4. **Swift worker 的工程形态**。ch08 合同只要三个函数(claim/IO/settle),
   但:RP-CE 核心库能否脱离 app 目标 headless 链接(spike);macOS 26+ 限制;
   libpq vs PostgresNIO 选型;与 duckdb-swift 组合时的 ABI 面(与 duck_codex
   bundle 的 released duckdb 对齐则可同载,需实测)。
5. **ABI 墙的运行时承载**。两 bundle 两 handler 已裁;duck_block_utils 缺
   预构建 runbook(风险表 §6-1)。
6. **Jev provider 未定**。判断平面在真环境需要 pg_typesafe + 一个 Jev 血统
   provider;DeepSeek 是否胜任是 P0C C2 的 go/no-go,未做。缓解:FakeJev/
   mock_response 起步,gate 全离线;C2 结论不阻断底座与工作台。
7. **MCP 兼容期(可选)**。若仍要给 Claude Code 等客户端用,可做「MCP 出口
   worker」把 v13 工具面反向暴露——是适配器不是承重件,不进 P0。
8. **grant/多租户**。单租户自用可缓(v8 grant 帝国已砍,只读角色执法保留)。

## 5. 方案:阶段与里程碑

```
Phase 0  决策收口(§7 四问,半天级)
Phase 1  v13 底座实施(DP1→DP8;按设计 §11 交付序:两阶段 advance→信封→
         manifest 骨架→stannum 刻画(并行)→chunks→经济学件→latch/软门控)
Phase 2  v13.1 工作台平面(M1–M5;WB2 是 go/no-go:ABI 墙实测+延迟刻画)
Phase 3  v13.2 仿制层(R1–R7,见下)
Phase 4  混沌与对照(kill 矩阵;与 RP-CE 并行 shadow diff)
```

v13.2 仿制层里程碑(一里程碑一提交,照 AGENTS.md):

| # | 内容 | 关键件 |
|---|---|---|
| R1 | workspace/file 平面:v6.1 §3.1 身份键 DDL + 只读工具族(sql 快路:read/tree/glob/search-基础) | 行读默认;路径规范化 CHECK |
| R2 | swift worker v1(只读):file_search(RegexCore/PCRE2)、codemap(CodeMapCore)、read 大文件分片 | ch08 三函数合同;G6 双语言断言 |
| R3 | 写面(独立设计文档 + L4):operation_authorization + 检查点 + mutating 纪律;apply_edits(精确替换+多段)与 file_actions(Trash 语义) | B005 显式批准;kill-at-boundary 下外部副作用≤1 |
| R4 | git worker:status/diff/log/show/blame/snapshot;worktree 生命周期 | snapshot=effect;锁序 |
| R5 | oracle 面:llm effect × provider 目录行(定价/缓存类/降级链)+ prompt/preset=策略行 | 重试/熔断=版本化策略;E(r) 记账 |
| R6 | 上下文面接线:selection/presets/workspace_context ≈ manifest/render/est_tokens(DP3 既有件) | 近零新件;export=render 纯函数 |
| R7(可选) | agent 面(子会话/worktree 路由)+ MCP 出口桥 | 不进 P0 |

## 6. 风险表

| # | 风险 | 缓解 |
|---|---|---|
| 1 | duck_block_utils 无 checkout/预构建 | M4 前收口 runbook(clone/构建/SHA-256/升级演练) |
| 2 | RP-CE 核心库不可 headless 链接 | spike 先行(Phase 0 附带);失败则 swift worker 自写薄层或走 duck_code 路线 |
| 3 | 双 duckdb 环境依赖管理 | v13.1 风险 2 已列;marker 制 gate 不依赖其形态 |
| 4 | Jev provider 不达标 | FakeJev 起步不阻断;C2 go/no-go 单独做 |
| 5 | 写面设计反复(v6.1 该部分未过 L4) | 独立 L4 循环;授权模型先冻结再写码 |
| 6 | 范围蔓延(UI/多租户/分布式) | §7-1 台账化;YAGNI 纪律逐条触发条件 |

## 7. 开放决策(Phase 0 必须收口)

1. **UI 形态**:RP-CE 本体保留为壳(它已经是成品)vs dsh web vs 纯 CLI 驱动。
   建议:先 CLI/SQL 驱动跑通闭环,UI 后置——v13 的「观察即视图」使任何前端
   都是查询,不锁死。
2. **tigerfs 定位**:A) 遵循 ch7 裁决——文件=artifacts,tigerfs 留台账
   (人/外部工具需要真路径访问时再启用);B) 翻案——tigerfs 作为路径面
   (mount 给人与 CLI 工具),artifacts 仍是真相源。建议 A 起步:行读已覆盖
   全部 agent 侧需求,避免 mount 生命周期/FUSE 权限进入 P0。
3. **Jev provider**:DeepSeek(C2 待验)vs pg_typesafe mock 起步 vs 推迟
   判断平面(纯规则路由)。建议:mock 起步,C2 并行验证。
4. **file_search 引擎**:swift(PCRE2,复用)vs duck(duck_code,同 bundle)
   vs PG 原生(trigram+regexp 起步)。建议:PG 原生起步,R2 时对比再定。

## 8. 与既有裁决的冲突清单(显式处理,不得静默违反)

| 冲突 | 现行裁决 | 处置 |
|---|---|---|
| tigerfs 作载体 | ch7:文件=artifacts,tigerfs 台账 | §7-2 二选一;翻案需 erratum |
| duck_block 负责编辑 | v13.1 不变量 5:duck 工具 mutating=false;写=B005 台账 | 编辑落盘走 R3 写面;duck_block 只做块变换 |
| MCP 出口 | 元原则:不造第二 IO 通道 | 出口桥是适配器且可选,不进承重件 |
| thresholds action='pass' 复用 | v13.1 风险 4(呈报设计侧) | 沿用其裁决路径 |

---

## 附:证据索引

- v13 设计:`docs/designs/v13-context-on-pg.md`(§0 一句话/§6.1 证据动作分离/§8 元原则/§11 交付序)
- v13.1:`docs/designs/v13.1-workbench-plane.md` + `docs/plans/v13.1-workbench-plane-plan-2026-09-21.md`(§1.2 四裁决/§1.4 不变量/§3.3 worker 六步/§7 台账)
- v6.1 调研:`docs/plans/v6.1-code-file-workbench-plan-2026-09-17.md`(§2.4 tigerfs 现状/§3.1 身份键/§3.3 授权检查点/B005)
- 教程:`docs/tutorials/v13/chapters/`(ch08 多语言合同/ch09 超级工作台/ch07 artifacts)
- 本地:`~/Projects/repoprompt-ce`(Package.swift targets;11 个 tree-sitter 语法)、
  `~/Projects/sitting_duck`(API_REFERENCE.md:read_ast 21 列)、`~/Projects/pgembed`、
  `~/Projects/deepseek-harness`(README:dsh 架构)
