# Cordis v2 DP6：公平维护、崩溃恢复与排空切换 Deep Plan

> 状态：Deep Plan，尚未实施、未运行运行时 gate。日期 2026-10-28。本文所有相对路径均以 `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99` 为根；不在 main checkout 实现。权威输入为 `docs/designs/cordis-plugin-system-2026-10-25.md`；DP1–DP5 已完成。规划时工作树为 `v24@fad3a55`，存在用户既有未提交文档；DP5 W5 交付作为已完成前置，不重复施工。执行时必须重核 HEAD、工作区、测试命令、SQL helper 行数和发布目标；DP5 历史实跑不能冒充 DP6 实跑。
>
> **容量行数已获授权（2026-10-28）：** 用户原文「授权无视容量预算要求」。DP6 的 helper 总行数、`43_loop.sql` 单文件行数、领域 DDL 物理行数不再作为准入或 gate 失败条件，仍须实测报告，且不设新的有限上限。语义边界（closure≤512、B≤16、协议 key/depth、ACL、validator/postcondition、replay、事务外 IO）不变。DP5 的 5500/700/900 计量与本文历史 Result 保留并标为历史。

## 1. Goal 与完成边界

DP6 在既有单宿主、单 `advance`、G 锁和八领域表内补上设计要求的**公平维护与崩溃后的重新发现**，使丢失宿主内存与唤醒后，扫描循环可以从已提交事实继续推动 effect、fiber、run、dispatch 和 dispose；遇到外部结果无法判定时安全保留 unknown 债务。DP6 复用 DP1–DP5 的解释器、receipt、closure、event 子行和 teardown planner，不增加第二生命周期引擎。默认 unknown 合同是保留不可变终态、提供可复现的对账/阻塞报告；**不把“对账报告”冒称“债务已清偿”**。需要自动解析 terminal unknown 属明确未闭合项，见 §4.5。

**Done when：**

1. 单一宿主维护循环按公平、有界、可重启的策略扫描所有需推进的 fiber、ready effect、过期 claim、未完成 dispose，并通过原协议驱动；丢弃全部内存游标后仍能重新发现工作。
2. 设计 §11 每个适用崩溃边界有具名生产路径测试，包含 DB 回滚、COMMIT 回执丢失、claim 后宕机、dispatch 半程、dispose 回执丢失和重启后重扫。测试使用 Fake handler，不开网络。
3. 仅按冻结 replay 合同重领外部 effect；未获得明确 replay 权利的外呼不被猜测为安全重放。可信原 receipt、lease、attempt/fence 和 terminal replay-first 语义保持。
4. unknown 被显式发现、分类和记录为待对账债务；不存在基于超时、进程死亡或空响应把 unknown 伪造成成功/失败的路径。若需要变更 terminal unknown 的权威事实表达，须先补设计裁决和 ABI/DDL 方案，本 DP 不暗中改写历史 effect。
5. 复用并验证既有 `dispose_subtree`、`dispose_plan`、`dispose_delta` 与 `p6_plan`，只修复被生产路径 gate 证实的收敛缺口；child fiber 先于 owner 收敛，未知义务阻止谎报 dispose 完成。
6. 实现基于新 install/fiber、旧实例排空、唯一地址释放再激活的 drain-based upgrade/rollback；接受切换空窗，不允许同槽双版本。HMR 若进入 DP6，只是宿主触发该版本切换流程，不做 ESM/状态保持替换。
7. 保持八领域表、两簿记表、三个命令 kind、三个生命周期解释器、后继 B=16、closure≤512、既有协议错误码、`advance` 唯一领域 writer、没有 VIEW/第二调度器；helper 总量、43 单文件与 DDL 行数按授权实测报告，不作准入/gate 失败条件，不设新上限。
8. 每个里程碑独立通过当时全部继承 gate，更新 DP6 README、覆盖矩阵、偏差台账与本文 Result；仅在授权发布目标明确时按仓库规则逐里程碑提交并推送。

**DP6 不声称：**外部 exactly-once、自动消除所有 unknown 债务、公平性由 DB 强制、多宿主正确性、即时事件通知、无缝版本切换、任意 host disposer 可逆。

## 2. 上游合同与 DP6 分工

设计依据：§3.1–3.5 的 advance/replay/G/外呼边界；§4.6 的派生状态；§5 的 reconcile/leave/unload；§6.3 的 pin/live、公平扫描假设 E1–E3；§8.2–8.3 的排空升级及 HMR 边界；§10.1–10.3 的预算、G1–G4 与 S7；§11 的崩溃矩阵；§12 的债务和非目标。

DP1 计划的初始分工表与 DP5 最终 README 对 DP6 背景有更宽的候选列举。按权威设计裁定：

| 项目 | DP6 裁决 | 依据/边界 |
|---|---|---|
| 单宿主公平扫描、目标/live 差异发现 | **核心交付** | §6.3 E1、§7.5、§11；维护循环是唯一扫描器 |
| ready/claimed effect 恢复、receipt replay、dispatch/run 进度重算 | **核心交付** | §3、§6.4、§11；不增持久游标或恢复计划表 |
| unknown effect / `inverse='unknown'` 债务 | **核心交付：显式对账与安全阻塞** | §6.2、§7.2 P2.1、§11–12；不凭猜测改为确定结果 |
| dispose 子树与依赖 drain | **审计并闭合** | §5、§7.3、§11；既有实现先复用，不能重复造清理引擎 |
| 升级、回滚 | **有界交付** | §8.2：新声明/新 fiber、旧版本排空、唯一地址释放后新版本激活；接受空窗 |
| HMR | **触发器边界** | §8.3：只触发版本切换；不做 ESM cache/状态保持热换 |
| `cancel/steer/respond` 独立 API | **不新增** | §1.2 已将六动词收敛为 run 结算和生命周期解释器；若有新产品 ABI 要求另立设计 |
| spawn/child run | **不在本 DP** | 现有 `parent_run_id/spawn_key` 列不等于定义了完整运行语义；child fiber 的 dispose 仍须覆盖 |
| cell/reservation writer | **不在恢复 DP 内顺带实现** | 虽在 §4.4/§6.1 定义 kind/inverse，但与扫描/崩溃恢复无依赖，需独立语义与 gate |
| 多宿主、realm ACL/沙箱、`thisArg`、同步 disposer/next 栈 | **明确不做** | §9.3、§12.3 红项/非目标 |
| 通用 `host_io` 执行与任意外部制品下载 | **明确不做** | 现有 0A000 seam、§8.1、§11 replay 授权；仅报告/阻塞未实现能力 |

DP5 README §“Next action” 的宽范围候选由本表裁决替代：`cancel`/`steer`/`respond` 不新增，spawn/child run、cell/reservation writer、多宿主/realm ACL/`thisArg`/同步 disposer 不做；DP5 README 作为历史不修改。shared artifact gate 为 N/A（无 artifact store/delete path，不新增子系统）。

> **Unknown 口径（设计边界）：**§11 允许在明确 replay 权利下重领，可信 receipt 可按原 token 重交；未知结果可进入对账。§12.2 将 unknown 列为显式债务。当前终态 effect/receipt 不可变。因此 DP6 的默认合同是保留原 `unknown`、记录核验/补偿进度于允许的审计面或宿主报告，并让 barrier 返回 `blocked_unknown`。若业务要求把 terminal unknown 原地解析为成功/失败，先停在相应设计闸门：不能复用普通 receipt replay 伪造一次不同结果，也不能新增表/列/命令或重写历史而不获设计批准。

## 3. Baseline 与现状审计

### 3.1 DP1–DP5 已完成的事实（执行时仍需复核）

DP5 handoff 报告当前实现拥有 40–44 五个 helper 文件、19 项 Cordis loader、5500 helper 行、十张表、三 command kind、24 协议错误、一个 `advance` SECURITY DEFINER；DP5 的 35 条继承与 DP5 gate 曾逐条串行通过。此信息是**交接线索**，不是 DP6 执行前的 HEAD、行数或 gate 证据。

执行者必须在 B0 重新确认实际 checkout 为 `.claude/worktrees/v99` 对应 worktree，辨清 main 与 v24 worktree，并记录：HEAD/branch/upstream、状态与未跟踪路径、DP1–DP5 文档/门禁存在性、canonical loader、冻结路径、当前代码哈希、helper 与 DDL 实测、所有 gate 的真实命令/次序。

### 3.2 已有代码应复用的接缝

| 文件/符号族 | 已有责任 | DP6 做法 |
|---|---|---|
| `40_advance.sql`: `advance`, replay、claim、closure、typed applier | 唯一写口、receipt 接纳、锁序、后继与请求缓存 | 保持 replay-first、G-first、原子 COMMIT；scanner 不直接写表 |
| `41_lifecycle.sql`: install/reconcile interpreters、resolve、successors | O-Insert/Lifecycle P0–P6 计划与注册/激活 | 维护循环只重新发现并提交现有命令，不复制状态机 |
| `42_teardown.sql`: `reconcile_branch`, `p6_plan`, `dispose_subtree`, `dispose_plan`, `dispose_delta` | 失活、inverse、屏障、dispose 子树的有界进度 | 先写缺口测试；保留现有 planner，只有实际反例才能扩 SQL |
| `43_loop.sql`: run reducer/settlement、`claim_contract`, `settlement_seed` | run/model/tool receipt、预算与 pins | 重用 frozen input 与显式 replay 权利 |
| `44_events.sql`: `dispatch_progress`, `dispatch_fold`, listener settlement | listener_call 与 dispatch 的派生进度 | 半程 dispatch 从 child rows 重建，不添加 cursor |
| `effects` / `requests` / `events` | effect、请求幂等、簿记 | 仅从提交事实恢复；事件簿记不变为第二决策表 |
| Host driver 当前手动消费 `emitted/ready_effects` | 外部执行边界 | 加公平 rediscovery；外呼前 COMMIT+IDLE，Fake adapter 测试 |

具体函数签名和 closure seed 在 B0 重读后冻结，不能依据 DP5 计划行号推断实际 HEAD。

### 3.3 容量闸门 B0

**DP5 历史计量（仅历史）：**40=1685、41=1473、42=1020、43=700、44=622，总计 5500；当时另有 5500 总限与 43 单文件 700 限。2026-10-28 授权后，这三项行数只报告、不再构成 DP6 准入条件；历史 Result 保留原判定。

B0 实际测量所有 40–49 helper 的完整物理行（含空行/注释）、领域 DDL 10–17/20/30 前缀、函数/角色/表/ACL 清单；18/19 簿记 DDL 单列，不误算成领域 DDL，计量算法与既有 gate 一致。不得只量 40–44。行数按里程碑报告；独立 planner/validator/postcondition、冻结 input 校验和全部语义负例照旧保留。

**报告口径（不是准入阈值）：**

```text
helper 40–49 total / 43 single-file / domain DDL (+ bookkeeping separate)
= measured and reported every milestone
no authorized cap, no replacement number
```

`closure≤512`、`successor≤16`、协议 key/depth、ACL、validator/postcondition、replay、事务外 IO 继续作为硬边界。三项行数不阻塞，但必须报告。

> 授权原文与范围见 §Result B0 补录；不设新的有限行数上限。

### 3.4 B0 工作区与发布隔离

- 将 DP6 只写到明确的 v99 worktree 根；不改 main checkout。
- 保存 B0 前后 `git status` 与用户既有未提交路径清单。不得清理或覆盖其中任何改动。
- DP1–DP5 历史计划/Result 只读；可在 DP5 README 的 DP6 handoff 有事实漂移时做一条最小链接/状态订正，但不要改写历史结果。
- AGENTS 的 push 指定 `origin main`，而交接工作分支是 `v24`/`origin/v24`；在授权目标明确前，计划只记远程/分支状态，不擅自推到 main 或 v24。提交/推送冲突与失败遵循仓库 AGENTS.md。
- 设计稿 `docs/designs/cordis-plugin-system-2026-10-25.md` 已有用户改动；若日后暂存本次授权，只 stage §10.1 授权 hunk 并检查 `git diff --cached`，不整文件 add。

## 4. 架构合同

### 4.1 维护循环是唯一 host scanner

一个受信 driver 周期性完整扫描 fiber/effect/dispose 事实并以 keyset/cyclic cursor 分页。扫描漏唤醒可在下轮重新发现；cursor 仅为可丢失内存优化，重启从起点也正确。不得用“只看 emitted”替代全量事实扫描。

扫描器只做观察、有限排序、派发调用；**所有决策和写入都再次在 advance 内验证**。现有 `reconcile_payload_valid` 精确支持 on/off/retry/advance；`advance` 动作只接受已有 reserved continuation，`on` 在 want_on=true 时 no-op。DP6 需要补上“发现可推进差异后如何唤醒唯一 `advance` 写口”的协议；当前实现没有 `ensure` 动作，不能把它当成已存在能力。B0 必须先完成 §4.3.1 的接口裁决与文档级相容性证明（B0 已核对信封/零写接入点，但 teardown-vs-failure 次序与 reloading/closing 缺失后继的 invariant fault 两点仍待证明；实现/gate 属 W1）；行数不再阻塞。不得在 Python 中直接将 `want_on`、episode 或 dispose 字段写成 SQL，也不得每轮创建会改变 control_seq 的重复 on/off 命令。

避免单个坏项饿死扫描：每一主题独立 keyset 游标，主题间轮询；单页有上限，`deferred`/`blocked_unknown` 只记录结果并继续其他 item，不在持 G 时等待或对单个 fiber 忙循环。

### 4.2 扫描权限与 actor 身份

**选定实现：独立 observer NOLOGIN 组 + 单一 observer LOGIN、列级只读 grants，不增加第二个 SECURITY DEFINER。** 角色沿用现有随机 family 命名与 OID 安全校验，`setup_db.py` 创建/清理时与原四组分开核验；不以模糊前缀授权。原 admin/service/operator 的 SELECT/DML/EXECUTE 矩阵不变，observer 无 `advance` EXECUTE、无三个协议组 membership、无 CREATE/TEMP 或表 DML；只有 schema USAGE 和明确列 SELECT。observer 不拥有 schema/table/function。所有函数仍 PUBLIC EXECUTE=0。该 observer 为单宿主内受信读取者，其 LOGIN 与调用协议的 actor 是独立连接。

只读列白名单在 W1 按实际查询逐列核证，至少包括：`fibers(id,install_id,owner_id,owner_episode_id,scope_id,want_on,control_seq,current_episode_id,failure,retire_started_at,dispose_requested_at,disposed_at)`；`episodes(id,fiber_id,epoch,state,closed_at)`；`effects(id,parent_id,ordinal,fiber_id,episode_id,run_id,kind,status,input,request_actor,attempt,fence,claim_owner,lease_until,outcome,settled_at)`；`installs(id,scope_id,owner_fiber_id,owner_episode_id,identity,version,artifact_digest,state)`；`requests(principal_id,request_key,request_bytes,request_digest,effect_id,response)`；`runs(id,owner_fiber_id,owner_episode_id,ended_at)`；`contributions(id,fiber_id,episode_id,kind,realm,key,inverse,withdrawn_at,released_at)`；`pins(id,consumer_fiber_id,consumer_episode_id,consumer_run_id,contribution_id,released_at)`。这些列允许扫描、债务诊断与按原请求字节恢复切换身份；replay 合同和执行 descriptor 以 claim/handler 的可信结果核验，不在 host 重写决策。`requests.request_bytes` 和 effect input 可能含业务内容，访问在受信宿主边界内，不能记日志或声称租户隔离。无需 SELECT manifest/overlay/raw descriptor，也不读 events 驱动调度。B0 对照真实字段、实际 SQL 和任何需要恢复的 actor/合同补齐**最小必要列**；列外 SELECT、INSERT/UPDATE/DELETE/TRUNCATE、私有函数与 advance 调用均由真实 LOGIN 负例证明拒绝。

扫描 SQL 只做原始事实分页，不调用未授权私有 helper。DB 诊断/候选重验走 `ensure` 与原 commands；不让 observer 成为 planner。每次读页在短 READ COMMITTED 事务内完成并立即结束；不得跨多页持 snapshot，也不得以 owner/superuser 作为产品 driver。

`advance` principal 来自 `session_user`。确定性后继必须由原 `request_actor` LOGIN 提交；不能假定 `SET ROLE` 就满足身份，也不能让 scanner 冒用 owner。B0 必须说明重连后如何选择 actor connection；缺失凭据是清晰的恢复阻塞，不能跳过或伪造身份。

### 4.3.1 `ensure` 唤醒入口：B0 必须定型，当前不是现有 ABI

已有命令 payload 精确键集只有 `{fiber_id, action, expected_control_seq}`；`action` 仅 `on/off/retry/advance`。`on` 对 `want_on=true` 是 no-op，`advance` 只能消费已有 reserved continuation。因此扫描器不能靠重发 `on` 恢复丢失的 continuation，也不能自行插入 successor。

**拟实现的命令合同**（B0 文档级相容性裁决后才可实施；行数不阻塞）：扩展现有 `command_reconcile` 的 action 枚举为 `ensure`；payload 仍为精确 `{fiber_id,action,expected_control_seq}`，不新增 command kind/解释器。observer 可以粗筛后传 fiber/control_seq，也可保守扫描所有无 slot fiber；live/target、owner、failure 与 closure 的判断只能在 G 下通过既有 selector/resolve 及 validator 重算，host 不需要读取完整 manifest 或猜测依赖映射。

1. 普通 command 授权与 canonical bytes/effect-id 校验不变；replay-first 先查既有 request。`ensure` 使用非 reserved key `cordis/dp6/ensure/<fiber-uuid>/<attempt-uuid>`，不占 `cordis/reconcile/` 前缀。一个尝试在结果未知时始终重交相同 key/bytes；下一次重新发现可以用新 UUID。effect id 仍按现有 principal/key/kind 算法确定，后继 actor 是该次 ensure 的真实 `session_user`。
2. 在 G 下发现并锁定与原 reconcile 等价的 closure，锁后重新验证 membership/target、`expected_control_seq`、唯一 slot 与 selector。只有**当前确有可推进工作、没有未结算 reconcile、未被同代 activation failure 抑制**时，复用 P0 `schedule` delta：领域写集和 events 均为空，恰有一个 ordinal=0 的原格式 `advance` successor；ensure effect、request 与该 successor 原子提交。P6 已有屏障仍由其后继决定。failure 不能阻止已开始的 teardown；activation 的同代 failure 不得自动 retry。dispose 仍由既有 dispose planner 接管。
3. 无工作、同代 activation failure 抑制或 slot 已存在时（teardown 已开始时先由既有 dispose/P6 路径处理，failure 抑制不得抢先；reloading/closing 若按原子合同应有后继而缺失，按 invariant fault，不得归入 `ensure_no_work`），在请求/effect 创建前返回现有 `stale_generation` 错误，`detail.reason` 分别固定为 `ensure_no_work` / `ensure_failure_suppressed` / `ensure_slot_present`；期望序列过期沿用原 stale 语义；未满足依赖沿用 `dependency_unresolved`，closure 变化/超限沿用 `retry_with_closure`。以上均**十表零写**，不缓存 no-op。不得将 `deferred` 用作无工作通知；它只用于已有屏障未满足的 DB refresh。selector 的真正 invariant fault 必须报告并停止该项，不能伪装为 no-op。
4. 无工作时可重复调用且不增长 request；之后 provider 在同一个 `control_seq` 变更，重扫/new UUID 会再次让 DB 判断，因此不会被旧 no-op 缓存掩盖。两个并发 ensure 在 G 下串行，先提交者占用唯一 slot，后者得到零写 `ensure_slot_present`；同一成功 key 返回原 replay，冲突 bytes 返回 `request_conflict`。COMMIT 回执丢失且 host 内存丢失时，扫描到已提交的 ready successor 并继续，不要求凭空恢复 UUID；当 successor 已结算，下一次仅在新的实际差异下生成新尝试。
5. 不改变 `want_on/control_seq`，不自动重试同代 failure。B0 文档级状态：信封/零写接入点已核；failure-vs-teardown 次序与 reloading/closing 缺失后继的 invariant fault 两点未证明，W1 semantic admission pending；不批准替代顺序。`40` 的 payload/preflight、closure seed、delta validator/postcondition 与 `41/42` 的 branch/interpretation 必须作为一个改动审查，仍保留 I7、B=16、锁后重验与原负例。reloading/closing 若因已提交原子事务而**应存在**的后继缺失，先报 invariant fault，不借 ensure 掩盖数据库破损；正常活跃依赖失效与 pending 变可激活等外部状态变化才由 ensure 唤醒。

B0 须证明此方案与既有返回 ABI、failure/teardown 规则和全部语义边界相容；若不能证明，结论为 **W1 semantic admission blocked / 需设计修订**，不可另造持久调度器或直接写表。行数按 2026-10-28 授权只报告、不构成阻塞；ABI、failure/teardown 与语义边界仍须证明。gate 包含同代 provider/live 变化、无工作后变可推进、原 key replay/冲突、并发确保唯一 slot、不断扫描的十表零增长、失效 consumer 的有界唤醒、activation failure 抑制和 teardown 不被抑制。

### 4.3 Fairness 与任务选择

在实际表/命令合同上列出全部扫描谓词，至少覆盖：

- 活 episode 在 reloading/closing 阶段且存在唯一 reconcile successor；
- want_on/current episode/live/target 出现可推进差异，且当前 control_seq 没有被同代 failure 抑制；
- ready command continuation 与 ready 外部 effect；
- lease 已过期且 contract 明确 repeat **且** concurrent 重放权利；
- dispose_pending install/请求退役 fiber；
- dispatch 的现有 ready host child；其 receipt 推进时原子生成下一子项/封口。无新 receipt 时 scanner 不 claim/settle 内部 dispatch，不凭空补 next；若出现“全部可信子项完成但 parent 未封口/next 未创建”，它违反 DP5 原子合同，报 invariant fault，禁止另造进度引擎；
- unknown、unsupported kind、闭环/closure overflow 和缺失 owner 事实，转为诊断债务而非无限重试。

进度证明与测试应表明：任一持续可执行 item 在有限扫描轮次被访问；每轮分页有上限；越过游标新增/更新的低 key 行在下一轮可见；重启丢 cursor 仍从全扫描收敛；一个 deferred/blocked 项不挡住其他 key/主题。E1 公平性和 E2 有限 handler 返回是**宿主假设**，不是 DB 定理。

### 4.4 Claim、外呼、receipt 恢复

维护 driver 对每个外部 effect 严格执行：

1. 以受信 actor 在独立短 `READ COMMITTED` 事务中 claim；
2. COMMIT 成功；确认连接 IDLE；
3. 用冻结 `effects.input` 与 claim execution descriptor 调 Fake/受信 adapter；
4. 在新的短事务把原 token/attempt/fence/owner 的可信 receipt 提交 advance；
5. 若提交确认丢失，重交同一 receipt，由 terminal replay-first 判定；不重新调用 adapter。

恢复分类：

| 已提交 DB 事实 | 允许动作 |
|---|---|
| ready 外部 effect | 只有 frozen input/contract 足以唯一恢复请求时，首次 claim 后事务外执行 |
| claimed、lease 未到期 | 不并发重投；等待下一轮 |
| claimed、lease 已到期、合同 repeat+concurrent 同真 | 合同允许时重领；新 fence 生效后旧 token 不再可发布 |
| claimed、仍由旧 token 持有可信回执 | 在被替代前原 token 可提交；不得只因 lease 经过就拒绝 |
| terminal success/failure/unknown | replay 优先；不重复执行外呼 |
| host_io/无 handler/无 replay 权利 | 显式报告/阻塞；不臆造资格 |

**receipt 持久性：**handler 得到可提交 receipt 后，先在受信宿主的持久 journal 中原子保存完整 outcome、effect id、actor 和 claim token（崩溃一致地写入并落盘），再发起结算；COMMIT 确认或同 receipt replay 成功后才可安全清理。重启先查该 journal 并用原 token/原内容重交；已被新 fence 取代的 token 不能发布。若外呼返回与 journal 落盘之间崩溃，则当作结果未知，按下表的 replay 权限/阻塞处理，绝不宣称已保存 receipt。journal 只是外部证据，不是领域写口或生命周期相位表；journal 读写/外呼均在 DB 事务外，妥善限制权限，不把敏感内容写入日志。

**`run_start` 特殊恢复合同：**当前 frozen input 仅含 `v/fiber_id/episode_id/contract`；请求文本/业务内容与步数来自 host success receipt，并不在 effect input 中。预部署 handler 的受信请求源必须在首次确认消费前，以 `effect_id + contract_version + handler_digest` 原子固定原始请求与初始步数，持久保存绑定和完整性摘要；重启用相同绑定找回原内容并验证，不能从后续事件、默认值或新模型请求推断。若请求源能可靠证明从未分配，则可按其已定义的入队合同等待/接收新请求；来源缺失、损坏、重复绑定或无法证明时显式阻塞。claim 已提交后的重领还必须满足冻结合同 `repeat=true` 且 `concurrent=true`；否则等待可信原 receipt/人工处理。测试覆盖分配前后与 journal 写前后 kill、source 缺失/摘要不符、合法重领与原步数一致；首次无请求时不捏造输入或认定失败。

每个 gate 使用 Fake provider/tool/listener，断言执行期间数据库事务已结束。不得运行真实 socket smoke 作为 gate。

### 4.5 Unknown 与 inverse 债务

将两类 unknown 区分清楚：

1. **effect outcome unknown**：外呼已开始但没有可验证 receipt；effect 以 unknown 终态承载债务，现有屏障 `blocked_unknown`。仅按合同安全重放或提交已保存的可信 receipt；永久不能判定就保持阻塞。
2. **contribution inverse unknown**：L-Unload 发现外部资源 inverse 不可验证；不得声称 Recovery Exactness，保留债务与稳定诊断，不能静默释放贡献并让 owner 标记完成。

DP6 不把 timeout、host 死亡、lease 到期、空 response 或“幂等键存在”视为成功证据。对账程序可以检查外部凭据并建议补偿，但补偿 IO 在事务外；任何新的 terminal unknown resolution ABI/持久化权威事实必须先改设计稿并新增可证明的合同。没有此批准的交付只做到 debt discovery、fair retry of explicitly replayable effects、safe blocked drain。

### 4.6 Dispose 子树收敛

DP4 的 `42_teardown.sql` 已包含 `dispose_subtree`、`dispose_plan`、`dispose_delta`，DP5 的 child/source/provider barriers 已接入。DP6 不重写这些对象。先增加基于生产 install/dispose/child fiber 的多层 owner 树路径，逐项检查：

- 父 dispose admission 封住后代准入；
- 子 install/fiber 逐个处理，后继受 B=16；
- child/consumer/run/listener effect 排空后才释放贡献/pin；
- consumer-provider 混合图无环；closure 缺失/超512稳定返回 retry/block，而非越权补锁；
- inverse unknown/terminal effect unknown 持续阻止墓碑；
- shared artifact 仍被其他 install 引用时不删（**N/A**：仓库无 artifact store/delete path；DP6 不新增子系统、不设该 gate）；
- 历史行/episode 身份保留；重复 dispose command 可 replay；墓碑不可逆、不复活。

只有 gate 暴露的 DP4 gap 才改 42 或既有 DDL；每个具体改动要有独立正反例及全量回归证据。

### 4.7 Upgrade、rollback 与 HMR

升版采用设计 §8.2 的**先释放再占位**：新版本是不可变新 install/fiber；旧 provider 先 withdrawn，旧 pins/runs/effects 排空，释放唯一 service 地址，再激活新版本。空窗可见且被测试；任何双版本同时 live 都是失败。

**持久身份与恢复：**由受信调用方提供 operation UUID 和目标 fiber UUID，固定操作 actor；开始前核验 source/target 同一 scope、identity、owner/owner episode 与预期 digest，source 为当前在用版本。首个成功的 `command_install` request key 采用 `cordis/dp6/switch/v1/<U|R>/<operation-uuid>/<source-fiber-uuid>/<target-fiber-uuid>/<source-control-seq>/start`，target install id、版本、digest 与声明由该请求的 canonical payload 固定；键长须≤512。该 request、install/fiber 和效果同事务提交，observer 通过 request key/bytes 联结 effect `request_actor` 与两个 fiber/install 重建关系；`U` 为升级、`R` 为显式回滚。后续 key 以相同 operation UUID 加固定 `off/<source-seq>`、`on/0` 阶段构造，固定原 LOGIN 与 canonical bytes；重启对已提交动作 replay 或观察其后继，在相应 control_seq 重验后只前进一次。若 crash 在首个事务提交前，DB 没有该意图，调用方须以同一 UUID/key 重交；不能声称扫描器能恢复未持久化意图。发现不同 payload 复用同操作身份、不同 actor 重名操作、同一槽多个未完成操作、缺 actor 凭据或源/目标关系不可唯一验证时停止并报告，绝不猜测。

**升级步骤：**(1) 用首个 U 请求创建新 version 的 install 和 `want_on=false, control_seq=0` 新 fiber；(2) 使用首请求 key 冻结的 source seq 发 `off`；(3) 公平推进旧 episode，直至已关闭、相关 contribution 地址已释放、pins/runs/effects 及 child 义务按原 P6 清空；(4) 检查 target 仍为同一未启动新 fiber、seq=0，再提交 `on/0`；(5) 由 DB 事实确认新 episode active 且地址归属新 generation 后标成功。恢复时由这些事实派生步骤，不存第二套 phase。外部 actor 改动 control_seq、目标已被独立启用、依赖不可用或出现 unknown 时停在安全状态；陈旧操作不得自动改用新 seq。源版本仅 off，不 dispose，旧 install 保持可供回滚的不可变声明；空窗是正常状态。

**复用声明的新 fiber 合同（当前不存在）：**现有 `(scope_id,identity,version)` 唯一约束禁止重复旧 install，原 install request replay 也只返回旧 fiber。拟扩展同一个 `command_install`，为 R 的首请求提供另一精确 payload `{mode:'reuse',install_id,fiber_id,expected_digest}`。G 下锁旧 install、其 scope、固定 owner/owner episode 与相关 child/同 install fibers；确认 install.state=`installed`、digest 匹配、scope 与 owner lineage 仍开放、owner episode 仍为 live 当前代，旧版本的其他 fibers 均已 off 且 obligations 清空；root/所有权不满足现有约束时拒绝。声明的 scope、owner、manifest、contracts、overlay、policy 与 digest 直接取不可变旧 install，绝不由 payload 改写或跨 owner 重挂。

在同一 delta 中只创建新 fiber（引用原 install，want_on=false、seq=0），并对非 root owner 沿用现有 `child` contribution、`dispose_child` inverse 与 episode_progress 规则；产生对应可审计 event，不创建/修改 install，不复活旧 fiber。必须同步扩展 install payload preflight、closure seed、interpreter、delta whitelist、独立 domain validator/postcondition 和 request replay；仍满足 owner/episode、I7、唯一地址、B/closure、scope/unique root 与 dispose 子树约束。同 install 多 fiber 会让 dispose 覆盖全部历史实例，须用生产路径测试证明旧 child contribution、新实例与后续 dispose 都安全。`dispose_pending/disposed` 的旧 install、owner episode 已变或无法满足上述验证时报告不可回滚；不能伪造同版本新 install。

**回滚策略：**新版本失败时不自动无限切换；由受信操作方提交一个全新的 R operation，源为当前需排空的 fiber，目标为旧 install，并按上述步骤先排空、再对复用声明创建的新 fiber `on`。若 B0 无法证明此 ABI、全部 validator/closure 和十表约束相容，W4 为设计阻塞，不能宣称完整 rollback。行数按 2026-10-28 授权只报告，不构成 W4 阻塞；ABI、validator/closure 与十表约束仍须证明。每个边界的 kill、stale seq、dependency unresolved 与 unknown 都有 gate；未知债务阻止提前释放。

HMR 仅是 watcher 检测到已预部署新 digest 后调用相同 upgrade 请求；无下载/安装脚本、ESM cache 失效、对象身份保持或进程内状态搬运。

## 5. 工作包与里程碑

| 里程碑 | Goal | Gate / Done when | 主要触及面 | 依赖 | 规模 |
|---|---|---|---|---|---|
| B0 | 当前代码交接、容量与恢复 seam 核证 | 全部继承 gate 实跑；完整 helper/DDL 实测，行数按授权报告、不设上限；dispose/unknown/scan 谓词清单；ensure/actor/pagination/reuse 文档级裁决；W1 semantic admission 另判。历史 blocked 判定见 §Result | DP6 plan/matrix/ledger；只读实现 | DP1–DP5 | M |
| W1 | 单宿主公平发现与维护循环 | CDP6-S：丢 cursor/重启可 rediscover；分页/轮转无 starvation；唯一 advance 写口、权限最小化；quiet 无循环写；Fake handler | host scanner、只读 discovery surface（若需要）、ACL/loader 原子配套；行数不阻塞 | B0 | L |
| W2 | receipt/claim/dispatch/run 崩溃恢复 | CDP6-R：§11 适用 kill points 全有真实事务/进程故障注入；重复 receipt/replay 权限矩阵正确；dispatch progress 从子行恢复；IO 事务外 | host executor、scan selectors、必要的最小 interpreter fixes | W1 | L |
| W3 | Unknown 债务和 dispose 全收敛 | CDP6-U/D：outcome unknown、inverse unknown、跨 owner/provider/listener/run 阻塞有正确诊断；operator 不可伪写；confirmed safe replay 可继续；dispose tree 逐级完成或诚实 blocked | 42/43/44 若有实证缺陷；driver/诊断测试 | W2 | L |
| W4 | drain-based upgrade、rollback、HMR trigger | CDP6-H：新版本等旧贡献释放；空窗；两版失败切换；rollback 新 episode；各相位杀进程重启可继续；watcher 仅发同一 upgrade request | host upgrade/watch driver、如必要的 install payload | W3 | M/L |
| W5 | 最终边界、合规与总收尾 | CDP6-B 与所有 DP1–DP6 scripts 串行全绿；所有预算、ACL、冻结面和债务清单以实测值收尾 | DP6 scripts/README/matrix/ledger/plan Result | W4 | M |

每个 W 都是独立里程碑：本里程碑全部 gate 与之前全部已交付 gate 实际全绿，收尾工件先更新，然后逐路径 add/commit/push。目标分支冲突按 AGENTS 停止并提交具体结果，不以 DP4/DP5 历史 local commit 推断发布授权。

## 6. Gate specification

### 共用验证纪律

- 独立脚本 `uv run python v24/cordis/dp6/test_*.py`；不是 pytest；FakeLLM/FakeTool/FakeListener，不开网络套接字。
- 每个被预期拒绝的调用都真实提交尝试并断言 protocol error/SQLSTATE + 十表快照零差异；合法 failure、unknown、deferred 及受限诊断有其合同限定写集，不能统一要求零写。
- 每次故障注入须验证断连后的数据库事实，并在全新 driver 实例（空内存）从 canonical loader 初始化的同一数据库重启。
- 不并行 DROP/CREATE 同一 gate 数据库；DP1–DP5 gate 全部顺序串行。

### CDP6-S — scanner 与公平性

1. 大于 page size 的 fibers/effects/disposals；最终每个持续可执行项均被访问并推进；页边界无跳行/重复副作用。
2. 在 cursor 后新增和在 cursor 前新增记录；下一轮或有限 wrap 内均被发现。
3. 向 scanner 注入 duplicate、out-of-order、stale row；`advance` 重验后只有合法推进，request replay 不增副作用。
4. 永久 deferred、blocked_unknown、超512 closure、bad actor credential 的首项不阻塞其后项与其他主题。
5. 公平循环没有事务内 sleep、外部 IO、持 G 等待、数据库直接写；失败后停止当前 item，不 tight-loop 重试。
6. 检查 scheduler 不会自动 retry 同 control_seq failure、不为 quiet fiber 产生无界 request、不改变 want_on/control_seq 来“修复”状态。
7. 只读 discovery 的 ACL（如果实现）与纯度：除 advance 外没有额外 domain writer；没有 public EXECUTE/未授权 SELECT。
8. `host_io`、unsupported kind 和不满足 replay 权利的外呼只出现为可诊断 blocked/debt，不进入 Fake handler。

### CDP6-R — 崩溃恢复与回执

按设计 §11 逐条映射 kill 点：COMMIT 前回滚、COMMIT 后 scan 前、L-Iter batch 中、claim COMMIT 后/IO 前/中/后、receipt 提交确认丢失、dispatch 半程、withdrawn 未卸载、dispose COMMIT 后确认丢失。至少增加：

- receipt COMMIT 成功但 driver 看不到响应，再提交完全相同 receipt → replay 且无二次 reducer/child/event；冲突 receipt 零写。
- claim lease 过期但原 token 未被替换仍可交可信结果；重领后旧 fence 被拒；重复/并发重领只有一条新 fence。
- repeat/concurrent 2×2 权限矩阵；缺字段/错误 digest/replay=false 均不外呼重领。
- 每个 dispatch mode 在部分 child settled 后丢失 scanner 内存；从已结算子行继续。unknown 不 joined，不捏造 `acc` 或 seal。
- `run_start` 在请求分配、claim、receipt journal 落盘及提交的各边界 kill；仅可信 request source 与合同 repeat/concurrent 双授权可重领；source 缺失、重复或摘要损坏时明确 blocked，原请求与步数不可变化。
- 所有 Fake/外部 handler 调用期间数据库连接处于 IDLE；advance 调用本身必须在短事务内。回滚点覆盖 receipt、successor、事件和 request cache。
- 外部 adapter 不会在 DB 事务中执行；真实套接字调用数为 0。

### CDP6-U/D — unknown 与 disposal

1. effect outcome unknown 与 contribution inverse unknown 分开构造；分别确认 debt 记录/稳定诊断、blocked_unknown 屏障与重启可见。
2. elapsed lease/worker death/empty response 不升级为成功；无授权的 replay 不发生；存在可信 receipt 时只提交原内容。
3. 同一 unknown 反复扫描不会制造新 command/effect 或清除原 outcome；不存在私有旁路 UPDATE 绕过不可变触发器。
4. dispose child tree：深度与扇出边界、多个 sibling、外部 consumer pins、ready/claimed listener_call、dispatch parent unknown、inverse unknown；每个 parent 只在全部 obligation 清零后墓碑。shared artifact gate 为 N/A（无 artifact store/delete path，不新增子系统）。
5. 子树中间任一事务 kill 后重启公平驱动收敛；窗口内没有 owner 被提前 released，墓碑和历史行不删除。
6. 独立验证 owner 与 dependency 图分别及混合环；超 closure/B 边界稳定拒绝，无无界 fanout。
7. 若“unknown 已人工核验并完成补偿但数据库仍保留 blocked debt”是产品不可接受情形，gate 记录设计阻塞而非偷加状态列/第九表；需要先设计变更获批。

### CDP6-H — drain upgrade / rollback

1. 新/旧声明身份不同、artifact digest 不变；attempt 原地覆盖 install 被拒。
2. 旧 run/activation pin/已创建 listener child 阻止旧 provider 释放；withdrawn 后旧 pin 可读，释放后新 resolve 只指向新 generation。
3. 同槽 live provider 唯一索引全程成立；空窗存在且可观测；新 provider 不早于旧 release 激活。
4. crash/restart 覆盖首请求 COMMIT 前后、新 install、旧 off、旧 P6 drain、地址 release、新 on、失败/rollback 每个边界；同 request 重放不重复安装或推进步骤；请求记录可唯一关联 source/target 与 operation id；首提交前只能由调用方重交。
5. 相同 operation 不同 payload/actor、同槽并发 operation、独立控制序变更、旧 owner episode 变化、重复 fiber id 与 digest 不匹配均被拒绝或稳定阻塞，不能误推进其他 fiber。
6. rollback 证明复用旧 install 新建 fiber 的 `command_install` validator/closure/postcondition 全链路、原声明不变、所有旧 fiber 的屏障、child inverse 和之后整个 install 的 dispose；disposed install 或旧 owner 不再 live 均不可复活。
7. stale control_seq 和外部 unknown 均安全停止切换；不得清除未知债务或复活 disposed fiber。
8. rollback 使用新 fiber/episode，恢复 old digest；升级声明与事件 listener 同时覆盖，mixed generation snapshot 不混代。
9. watcher 不下载代码、不做 ESM 替换，只提交同一个稳定 upgrade 请求；缺省无 watcher 时手工流程仍可用。

### CDP6-B — 总边界与兼容

- 十张当前表不变；无 view/materialized view/extension；无第四 interpreter/第二调度器；command kind 仍 3、错误码仍 24（除非另有经批的方案）。
- `advance` 仍唯一 `SECURITY DEFINER` writer，PUBLIC EXECUTE 0，运行 actor 无裸 DML；若有只读函数，其权限/纯度独立证明。
- helper 总行数、43 单文件、DDL 行数按 2026-10-28 授权实测报告，不设上限、不作失败条件；真实谓词 boundary 只对语义边界（closure 512/513、successor 16/17、协议 200/201 keys、depth 32/33 等）要求 N 通过/N+1 拒绝。不能仅比常量或从 DP5 日志抄数。
- closure 512/513、successor 16/17、协议 200 keys/depth32、dispatch children 等 DP1–DP5 边界保持。
- 三个 lifecycle interpreters / 三 command kinds / B=16 /唯一 G / replay-first / 屏障 deferred 零写 /外呼 IDLE 全通过。
- frozen `v24/load.py`, `v24/sql/**`, `v24/s1`–`s12` SHA256 与允许 diff 不变；Cordis 自有 `load.py` 与预算 manifest 顺序唯一正确。
- 所有既有 gate 和 DP6 gate 串行实跑、逐条记录 HEAD/命令/耗时/退出码；没有 skip 或“预计通过”。

## 7. File impact 与约束

所有以下 SQL 修改都以 B0 文档级相容性裁决为前提；行数不阻塞。实际 helper 放置点须按 parsed SQL body 依赖顺序和现有 canonical order 核实，不得为预算移出 40–49。

| 路径 | 计划责任 | 限制 |
|---|---|---|
| `v24/cordis/dp6/driver.py`（新增） | 单一公平 scanner、actor 连接选择、事务外 Fake/真实 adapter 接缝、upgrade orchestration | 不含 lifecycle 决策/直接 DML；真实 adapter不是 gate |
| `v24/cordis/dp6/README.md`（新增） | 操作合同、启动/重启、阻塞/unknown 与 upgrade runbook | 只记实测，不把假设写成完成 |
| `v24/cordis/dp6/test_scanner.py`（新增） | CDP6-S | 用已部署测试数据库和独立 driver 进程 |
| `v24/cordis/dp6/test_recovery.py`（新增） | CDP6-R | 连接断开/子进程终止，不用 sleep 超过短 lease 测试 |
| `v24/cordis/dp6/test_dispose.py`（新增） | CDP6-U/D | 先测既有 planner，必要时最小修 42 |
| `v24/cordis/dp6/test_upgrade.py`（新增） | CDP6-H | 不创建生产 HMR 模块系统 |
| `v24/cordis/dp6/test_boundaries.py`（新增） | CDP6-B | 保留 DP1–DP5 全部原断言 |
| `v24/cordis/sql/45_maintenance.sql`（条件新增） | 只读发现/诊断或 advance 私有 helper，按实际需要定型 | 只有接口裁决通过后才创建；行数不阻塞；无空 scaffold |
| `v24/cordis/sql/40_advance.sql`–`44_events.sql` | 只在必要时扩现有 interpreter/selector/dispatch facts | 先证明当前实现缺口；每个新分支独立 validator/applier/postcondition |
| `v24/cordis/sql/50_permissions.sql` | 精确 maintenance/observer ACL（若需要） | 不能放宽 existing actor；不加额外写者 |
| `v24/cordis/load.py`, `helper_budget.py` | 新 SQL 若实施则同一提交注册，manifest 校验与预算计量同步 | loader、预算与代码原子交付，冻结 v24 loader 不碰 |
| DP1–DP5 gate 源文件 | 仅在新 loader/catalog/ACL事实必需时精确更新布局断言 | 不可删除旧拒绝/回归保护 |
| `docs/reviews/cordis-v2-dp6-conformance-matrix-2026-10-28.md`（新增） | command、HEAD、环境、结果、冻结与容量证据 | 每里程碑更新 |
| `docs/reviews/cordis-v2-dp6-deviation-ledger-2026-10-28.md`（新增） | debt、条件定理、明确偏差与未完成项 | 不把 blocked/未跑写成完成 |
| 本文 | Result 追加、计划变化与依据 | 保留旧Result，不重写历史 |

**不默认修改：**设计稿、DP1–DP5 SQL/计划/验收记录、冻结 `v24/load.py` 与 `v24/sql/**`、其他主 checkout 文件。设计/预算需要变更时，先独立呈报与授权，再把批准的新合同写入设计和计划后开始实现。

## 8. 风险、发布与回退

- **容量行数**已由 2026-10-28 授权解除；当前阻断是 W1 语义准入（ensure/actor/pagination/reuse 的文档级证明）。发布目标已明确为 `origin/v24`。B0 audit 不等于 runtime 实现。
- **scanner 的读权限**采用独立 observer 列授权；不新增 read DEFINER。角色 family 校验、setup/cleanup 与原 ACL 负例必须一起交付，不能把 observer 加入协议角色或扩大原三组 SELECT。
- **命令 actor 身份**可能使自动恢复不能仅靠一个 LOGIN；不能为了便利将 `request_actor` 替换成宿主身份。
- **`ensure` 无工作零写与扫描竞态**尚无现成 ABI；若无法证明请求 replay-first、现有错误码和唯一 slot 相容，或无法证明无工作扫描不写表，W1 必须阻塞。
- **旧声明的新 fiber 回滚**与现有 install interpreter“一次创建 install+fiber”不匹配；先验证可复用声明合同，不可把旧 install request replay误称为新 fiber。
- **永久 unknown**会安全阻塞 unload/upgrade；这是活性债务，不得为了进度强行释放 pin/contribution。
- **E1–E3 是前提**：driver持续运行、外部 handler有限返回、有限 reconcile sequence；挂起 handler 需取消/隔离策略而非默认“杀掉即失败”。
- **切换空窗不可消除**；若要求无损 traffic switch，会牵动 I1/Confluence，应另行修订设计，不在本 DP 中双版本占位。
- **未知结果对账 ABI 未被当前正文精确闭合**；本计划采取保留 terminal unknown 的保守合同。若未来要求 debt 可清偿且对 DB 可见，先补权威持久化机制与证明。
- **回退**先停唯一 scanner/upgrade driver，再停外部 adapter；保留全部 effects、unknown receipts、pins 和墓碑。不得清库、手改 lifecycle 行或删除未知债务；旧版 runtime 不得继续处理新格式，先确定兼容策略。
- **发布**按 AGENTS 里程碑顺序。分支/远程目标冲突未解时可完成测试和收尾工件，但不能擅自 push 到 `origin/v24` 替代 `origin main`；若无法安全合并按规则停并报告。

## 9. 命令索引、工件与执行顺序

### 9.1 B0 命令索引

B0 必须从 DP5 最终 matrix/README 核取当时仍存在的 35 条继承命令及顺序，不手抄旧临时日志作为当前结果。其后按脚本职责追加 DP6 已交付 gate。各里程碑重跑全部已交付 DP1–DP6 脚本，独立进程、串行执行；同一个 setup_db 会 DROP/CREATE 自己的测试库，不并行运行。

标准新增命令（仅在文件存在且对应 gate 已实现后登记为 required）：

```bash
uv run python v24/cordis/dp6/test_scanner.py
uv run python v24/cordis/dp6/test_recovery.py
uv run python v24/cordis/dp6/test_dispose.py
uv run python v24/cordis/dp6/test_upgrade.py
uv run python v24/cordis/dp6/test_boundaries.py
```

若 B0 语义准入未完成，以上命令作为 future index 标 `not implemented/not run`，不可声称 green。

### 9.2 每个里程碑收尾

每次按顺序：

```text
当前里程碑全部 gate + 全部此前 gate 实跑全绿
→ 更新对应 dp6/README、conformance matrix、deviation ledger、本计划 Result
→ git status 查看完整工作区
→ 按路径逐项 git add，仅暂存本里程碑文件
→ git status 与 staged diff 复核，无凭据/无无关文件
→ git commit
→ 经授权目标普通 push
```

不使用 `git add -A`、`git add .`、`--no-verify`、force push 或 `reset --hard`。计划文件本身是规划交付，不属于已完成运行里程碑；除非用户明确要求，不因只写计划而提交/推送。

## 10. References 与交接

- 权威设计：`docs/designs/cordis-plugin-system-2026-10-25.md` §§3–8、§10、§11–12。
- DP1 职责/上游合同：`docs/plans/v24-cordis-dp1-foundation-plan-2026-10-25.md`，尤其 DP1–DP6 分工表与 dispose/recovery 边界。
- DP2/DP3/DP4 plans：`docs/plans/v24-cordis-dp2-lifecycle-plan-2026-10-26.md`、`v24-cordis-dp3-teardown-plan-2026-10-27.md`、`v24-cordis-dp4-run-settlement-plan-2026-10-27.md`；执行前现查具体名字/HEAD。
- DP5 final plan / README / conformance matrix / deviation ledger：`docs/plans/v24-cordis-dp5-events-resolution-plan-2026-10-28.md`、`v24/cordis/dp5/README.md` 与对应 review 文件；DP5 曾确认 W1–W5、35/35 回归及 5500 历史计量；DP6 行数按授权报告，执行时复测。
- 实现接缝：`v24/cordis/sql/40_advance.sql`–`44_events.sql`、`42_teardown.sql` 中 `dispose_subtree`/`dispose_plan`/`p6_plan`、`v24/cordis/sql/50_permissions.sql`、`v24/cordis/load.py`、`helper_budget.py`。
- Repository instructions：根 `AGENTS.md` 及 worktree `.claude/worktrees/v99/AGENTS.md`。里程碑 push 规则与目标分支冲突按其要求处理。

### Result

规划完成（2026-10-28）。本文件只规划 DP6；未改代码/schema/loader/budget，未创建空 SQL/test scaffold，未运行任何 gate，未提交或推送。已将容量 R=0、终态 unknown 的权限边界、DP4 已有 dispose 子树能力和 DP1/DP5 范围冲突显式列入准入/实现合同。

### B0 Result（2026-10-28，执行审计；历史记录，容量判定已被补录取代）

**结论：blocked at admission，W1 未启动。**（该容量准入结论已被同日用户授权补录取代；原始判定与全部计量保留如下。）初始审计时本文件之外只新增了 B0 矩阵、偏差台账与 `v24/cordis/dp6/README.md` 审计工件；同日授权补录另在 `docs/designs/cordis-plugin-system-2026-10-25.md` §10.1 追加授权段。未改任何 SQL、loader、budget、runtime、test scaffold，未 commit/push。

执行环境：worktree `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`，branch `v24`，HEAD `fad3a55800d8ccb9548ec720886e07ad8fcc2c13`，upstream `origin/v24`（fetch 后 `0 0`）；main checkout `main@ab34d697` 未触碰。工作区基线为 10 modified + 27 untracked（含本计划文件），37 个路径已逐一 SHA-256 存档；35 条 gate 跑完后 status 与 hash 全部一致，未覆盖任何用户改动。

容量实跑：40=1685、41=1473、42=1020、43=700、44=622，**total 5500，R=0**；`43` 同时顶满 700 单文件上限。领域 DDL `10`–`17`+`20`+`30`=**465**≤900；簿记 `18`+`19`=**22** 单列不混算。manifest 19、十表、`pg_proc` 170（162 helper + 8 trigger guard）、唯一 DEFINER `advance`、public EXECUTE 0、无 VIEW/EXTENSION、3 command kinds、24 错误码、closure 512/B=16。十二个冻结 `v24/sql` SHA-256 与 `57e2c1e` frozen diff、`git diff --check` 均 exit 0。独立 disposable DB catalog 查询复核了上述 catalog/ACL（admin/service/operator 无表授权，仅 `advance` EXECUTE）。

继承 gate：按 DP5 W5 矩阵的 35 条真实顺序（保留 s8-before-s7），每条独立 `uv run python` 进程串行，**35/35 exit 0**，per-command 合计 199.9 s，wall 201.0 s；逐条命令/退出码/耗时见 B0 矩阵，日志 `/tmp/dp6_b0/gates/`。无 skip、无 gate 修改、无真实 provider socket。

ABI 核证：`ensure` 不存在（payload 仅 `on/advance/off/retry`）；reuse 声明不存在（install payload 11 exact keys、`UNIQUE(scope_id,identity,version)`、validator 强制 `install_create`+`fiber_create`）；observer 角色/列级 SELECT 不存在（50_permissions 仅三组且无表授权）；无 scanner/sweep/recover。`dispose_subtree`/`dispose_plan`/`dispose_delta`/`p6_plan` 与 terminal-effect 不可变触发器已存在，可在 W3 先复用并要求实证 gap；仓库无 artifact store，故“共享 artifact 不删除”一项为 N/A。

准入公式：`5500 − 0 + (380–560) ≤ 5500` 不成立，`R_eff=−560`（最好 −380）。估算含 ensure 85–120、reuse 175–260、可选 SQL 诊断 0–60、维修余量 120；observer ACL 在 50_permissions/fixture 中约 40–70 行但不计入 40–49 helper，不能救 helper 预算。因无任何已证明语义等价回收，判定 blocked。重裁建议（未执行）：(1) 另立 DP6.0 等价重构，实测回收 ≥560 helper 行并跑全 35 gate；(2) 由设定 5500 的授权方把上限修订到 ≥6060 并同步预算合同；(3) 设计性 descope ensure/reuse，并明确 W1/W4 因此 blocked。不得以压行、移出计量、弱化 validator/gate 或偷加 scaffold 通过。（上述重裁建议为授权前草案；三项行数容量部分已由 2026-10-28 用户授权取代，不采用 ≥6060 或任何新上限。）

发布（历史记录：当时尚未授权；2026-10-28 后续已授权 `origin/v24`，见补录）：`origin/v24==HEAD==fad3a55`（0 0），`origin/main=4635b4a` 且 `origin/main...HEAD=4 32`，无 fast-forward 路径；AGENTS 的 `origin main` 与本 worktree 的 `origin/v24` 冲突，当时未 commit/push。DP5 README §Publication 仍称 W5 未推送、`origin/v24=7aa32ca`，与实际 fetch 结果漂移，已在矩阵/台账记录但未改 DP5 历史文件。

### B0 Result 补录：容量行数授权（2026-10-28）

用户原文：「授权无视容量预算要求」。授权范围覆盖 DP6 的三项行数容量预算：helper 总行数、`43_loop.sql` 单文件可读性行数、领域 DDL 物理行数；**不覆盖** `closure<=512`、`successor<=16`、协议 key/depth、ACL、validator/postcondition、replay、事务外 IO 等语义边界。

据此的 B0 裁决：

- **容量准入：pass under explicit user authorization。** 原 `R=0`、helper 5500、43=700、DDL=465 的实测与 “blocked at admission” 判定保留为历史证据，不再构成 DP6 准入阻塞。
- **不设新的有限行数上限。** 三项行数仍须逐里程碑实测并报告；行数不再是 DP6 准入或 gate 失败条件。
- **B0 状态：baseline + capacity done；W1 semantic admission pending。** 容量豁免不等于 W1 语义准入。完整文档级裁决见 B0 矩阵 §“W1 semantic admission”。
- **`ensure`：仅信封相容，语义准入 pending。** 可复用现有 `command_reconcile`；需在 40/41 增加 action token、seed action 过滤与 interpret 分支。锁/closure、replay-first、唯一 slot 与零写接入点已核。**两点未证明**：(a) same-generation failure 不得阻止已开始的 teardown，不能把 failure 检查置于 teardown 之前；(b) reloading/closing 若按原子合同应存在后继而缺失，必须报 invariant fault，不能一律 `ensure_no_work`。B0 不批准替代顺序，W1 须先补证明与 gate。
- **actor：必须原 LOGIN 直连。** 从 `effects.request_actor` 经受信凭据映射取真实 LOGIN，校验 `session_user`；不得 `SET ROLE`/`SET SESSION AUTHORIZATION`；缺凭据 blocked，不冒充 owner/observer。
- **pagination：只读原始事实。** scanner 按主题 keyset 分页，live/target/failure 等语义仍由 `advance` 决定；predicate 表见 matrix。
- **reuse：非 root 条件可闭合，W4 pending。** root 因 `unique_root` 拒绝；非 root 仍缺 4-key payload、fiber-only delta/validator、seed/lock 与 `command_binding` owner 来源裁决（未闭合 ABI 点）。
- **语义边界不变。** closure 512/513、successor 16/17、协议 200/201 keys、depth 32/33、ACL、validator/postcondition、replay-first、事务外 IO 等继续按原 gate 执行。
- **W1 原子落实预算/gate 配套。** 只解除三项行数断言；保留 19 项 canonical manifest/缺失/重复/未登记/符号链接校验、必需 helper 文件校验与全部语义/ACL/文件负例；旧 line-only probes 按授权废止。B0 不改这些代码。
- **当前仅完成 B0 baseline/capacity。** W1–W5 未开始；W1 semantic admission pending。
- **发布授权（2026-10-28）：** 目标明确为当前分支 `origin/v24`，允许正常提交与普通 push；只发布本 B0 的 5 个 DP6 工件。设计稿只暂存本次授权 hunk，既有用户 5500 改写不随提交。35 条继承 gate 先前已全绿，纯 docs 改动无需无因重跑。

### W1 semantic admission Result（2026-10-28，Oracle 裁决；实现前记录）

**结论：`ensure` 语义准入通过（admit-with-corrections）；W1 可实施。** B0 的两点 pending 已按 Oracle 双 lane 裁决闭合，未采用 B0 已撤回的 failure-before-teardown / 全 closing→`ensure_no_work` 草案。设计记录：`docs/reviews/cordis-v2-dp6-w1-oracle-design-2026-10-28.md`；Oracle group `D2EED4FF-ECCC-44C2-803A-7CA520DFC462`（primary `codex/gpt-6.1-sol-xhigh` chat `new-chat-AB0DCA`，additional `openCode/kimi-code-plan-cn/k3.1-pro` chat `new-chat-oracle-2-BD1ACF`）；导出 `prompt-exports/oracle-chat-2026-10-28-232411-new-chat-ab0dca-d52e.md`（gitignored）。

最终裁决要点：

1. `ensure` 只扩展既有 `command_reconcile` 的 payload action 枚举，payload 仍精确为 `{fiber_id,action,expected_control_seq}`；non-reserved key `cordis/dp6/ensure/<fiber>/<attempt-uuid>`。不加 command kind/表/列/错误码/解释器/第二 writer。
2. 顺序：当前 episode 一致性（含 NULL episode + 非空 `retire_started_at` → `0A000/phase_drift`）→ persisted-emission invariant → reloading/closing 缺失后继 invariant → expected seq stale → slot → terminal → 递归 `advance` selector。只有递归结果为 `p1` 时才检查同代 failure；`leave`/`p6` 永不读 failure，故 teardown 不被 failure 抑制。
3. 缺失后继的精确证据是两类，均在 no-work 之前：成功 command_reconcile 父（以及由 `install_dispose_progress` 证明本 fiber 为 `fiber_requested`/`work_scheduled` 目标的 command_dispose 父）的 `requests.response->'emitted'` 指向不存在的 effect；或 reloading 无 slot / closing 已存在本 episode 的 `contributions_released`/`pins_released` 但无 slot。均 `0A000/missing_reconcile_successor`。空 emitted 与合法 `successors:[]` 不会误报。
4. 工作路径返回 `{kind:'p0',mode:'schedule',control_seq:f.control_seq}`，复用 `p0_delta`；`validate_domain` 现有 exact `p_delta IS NOT DISTINCT FROM p0_delta(f,v_expected)` 即 validator；apply 仍是唯一写入点。无工作/故障在 `validate_and_apply_delta` 前返回或 raise，十表零写且不缓存 no-op。`reconcile_command_seed` 仅把 contributions/runs/pins 的 action 过滤扩为 `IN ('advance','ensure')`；activation-candidate refs 保持 `advance`-only。
5. Observer：独立 NOLOGIN group + LOGIN、schema USAGE + 列级 SELECT（不回退为表级）、无 advance EXECUTE/DML/函数 EXECUTE；`role_family` 纳入 observer 组但 `role_allowed` 不纳入。TEMP 是数据库级 PUBLIC 默认，fixture 需从 PUBLIC revoke 并只回授原四组，observer 无 TEMP；`dp1/test_kernel` 的 hostile temp negative 显式给其 foreign service login TEMP 以保留原语义断言。
6. Scanner：只读 observer 原始事实分页（每主题独立 keyset、LIMIT 64、每页短 READ COMMITTED 事务、页尾不跳过、short page wrap、轮询）；只通过 `advance` 决策/写入；ensure 用配置的真实 admin/service/operator LOGIN，reserved continuation 按 `effects.request_actor` 直连并核验 `session_user`，缺凭据 `blocked_actor_credential`，不冒充。W1 不执行外部 effect（W2 负责 claim/receipt/crash recovery）；Fake handler 只用于证明未调用。

以上为 admission 证据；实现、CDP6-S gate 与 W1 Result 待后续记录。B0 原 pending 判定保留为历史。

### W1 Result（2026-10-28，实现、修正后的 CDP6-S 与 36-gate 串行实跑）

**结论：W1 Done-when 与修正后的 CDP6-S 已实现；最终 36/36 gate 串行 exit 0；本会话仅交付 W1 范围并返回父级验证，W2–W5 未开始。** 实现起点 HEAD `78e21500cc716203ae5d978d7e2948aa4bcf66e0`，分支 `v24`。Oracle 设计记录 `docs/reviews/cordis-v2-dp6-w1-oracle-design-2026-10-28.md`；矩阵新增 §W1 implementation and gate evidence。

过程中父级验收指认：临时 36-green 运行的 S6 只用“缺失后继 fiber + 无关 unknown 诊断”打印 blocked/deferred，缺少独立进程重启/丢 cursor、重复/乱序/陈旧 raw row 注入、真实 deferred/`blocked_unknown`/closure>512/bad actor 首项公平、cursor 之后插入、事务 IDLE 与 dispose 父级缺失后继覆盖。该指认成立；以下为修正后的实测结果，不把临时运行冒充 Done-when。

实现面：

- **`ensure`**：`reconcile_payload_valid`/`interpret_reconcile` 接受新 action；`reconcile_command_seed` 仅将 contributions/runs/pins 过滤扩为 `('advance','ensure')`；42 新增 `ensure_emission_missing` 与 `ensure_branch`；工作路径复用 `p0_delta` 的 schedule，`validate_domain` 的原 exact `p0_delta` 校验不变。未加 command kind/表/列/错误码/validator 分支/第二 writer。
- **selector 顺序**：episode 一致性（含 NULL episode + retire → `0A000/phase_drift`）→ emitted-missing → reloading/closing 缺失后继 → expected stale → slot → terminal → 递归 `advance`。同代 failure 只在 `p1` 检查，`leave`/`p6` 先行，故 teardown 不被抑制。
- **observer ACL**：独立 NOLOGIN group + LOGIN；schema USAGE + 8 张表的列级 SELECT；无表级 SELECT/DML/函数 EXECUTE/CREATE；`role_family` 纳入 observer、`role_allowed` 排除；fixture 创建/核验/清理，TEMP 从 PUBLIC revoke 并只回授原四组。
- **scanner**：`v24/cordis/dp6/driver.py` 7 个独立 keyset topic、LIMIT 64、每页短 READ COMMITTED 事务、轮询/旋转起点、页尾处理与 wrap、可丢 cursor；只发 `advance`；reserved continuation 按 `effects.request_actor` 直连并核验 `session_user`；缺凭据 `blocked_actor_credential`；W1 外部 effect 仅诊断。
- **budget/gate**：`helper_budget.py` 改为 measurement-only + required-file negative；DP1–DP5 旧 5500/5501、43≤700、DDL≤900 断言移除，measured print 保留；DP5 B6 私有 helper/`pg_proc` 计数 162/170→164/172（新增两个 helper）。

CDP6-S 修正后覆盖（逐项均由生产 install/reconcile/dispose 路径 + 真实 observer/service/admin LOGIN 驱动；fault fixture 只用 owner DML 破坏被证明的对象）：

- `[CDP6-S1f/S7]` observer NOLOGIN group + LOGIN、schema USAGE、列级 SELECT；真实 LOGIN 负例覆盖表 SELECT/DML/TRUNCATE、advance EXECUTE、CREATE/TEMP、`SET ROLE`；fixture 创建/核验/精确清理。
- `[CDP6-S2/S4/S11]` ensure quiet/slot/stale/work/replay/conflict/并发唯一 slot；teardown-before-failure 与同代 activation failure suppression；provider 撤出在 consumer 同 control_seq 下被 ensure 唤醒并收敛；重复 quiet 扫描十表零增长。
- `[CDP6-S3/S3b]` reconcile 父级 emitted-missing、reloading 无 slot、closing 已释放无 slot、retire-without-episode；以及 `command_dispose` 的 `fiber_requested`/`work_scheduled` emitted-missing（由 `install_dispose_progress` 事件限定目标），均为 `0A000/missing_reconcile_successor` 或 `phase_drift` 零写；无关 dispose 父级不误报。
- `[CDP6-S5a/S5b/S5c]` >page fibers/ready commands/dispose installs；在 cursor 之后和之前分别插入新 fiber，均在有限 wrap 内重新发现并推进；页边界无跳项。
- `[CDP6-S6]` 最低 key 的 >512 closure fiber、真实 deferred closing fiber、真实 `blocked_unknown` closing fiber、坏 actor continuation 与 deferred dispose install 同页时，同一 commands 页中的健康项仍提交；unknown/external/inverse 债务仍被其他 topic 诊断；重复 quiet pass 十表零增长且每个 blocked 项每 pass 至多尝试一次。
- `[CDP6-S8/S9/S9b]` host_io/unknown/expired/ready-external/inverse 仅诊断，Fake handler 零调用、零写；缺凭据 `blocked_actor_credential`；真实但错误的 LOGIN 由 `session_user` 校验拒绝，ready effect 保持零写，正确绑定的 sibling 仍推进。
- `[CDP6-S12]` duplicate、out-of-order、stale raw row 交给 item handler；`advance` replay/revalidate 后无重复 request/effect，stale fiber seq 零写。
- `[CDP6-S13]` 独立 driver 子进程在同一 canonical DB 上正常退出，第二个子进程完成一页后被 SIGKILL，第三个空内存进程从头 rediscover 并收敛；无持久 cursor。
- `[CDP6-S14]` 每个 observer read / advance 事务在 close 前 commit/rollback 到 IDLE；无残留 session、无 idle-in-transaction；driver 源码无直接 DML/sleep/socket/thread。

Oracle review group `6B696214-99CB-48A0-BEC6-131CBDE8508F`（primary `codex/gpt-6.1-sol-xhigh` chat `new-chat-7BEF5C`；additional `openCode/kimi-code-plan-cn/k3.1-pro` chat `new-chat-oracle-2-ABB6CD`）对修正后的 staged diff 给出双 lane **ACCEPT WITH CORRECTIONS**；两条修正（dispose 父级缺失后继、真实错误 LOGIN 的 `session_user` 校验）已落实为 S3b/S9b，未放宽 driver/SQL 语义。

补充实测：`test_scanner.py` 1311 行、`driver.py` 326 行（report-only，无新上限）。

实跑：36 条命令（35 条继承 + `test_scanner.py`）逐条独立 `uv run python` 串行，**36/36 exit 0**；per-command 合计 **216.5 s**，wall ≈**217.0 s**；日志 `/tmp/dp6_w1_final3/gates/`，汇总 `/tmp/dp6_w1_final3/gates.tsv`。逐条命令/退出码/耗时见矩阵。无 skipped gate、无弱化语义/ACL/manifest 负例、无真实 provider socket；W1 仅按授权更新 physical-line-only 断言并新增 scanner 覆盖；每个 DB 为 disposable pgembed。

实测：40=1685、41=1481、42=1112、43=700、44=622，total **5600**（report-only，无替代上限）；领域 DDL **465**；簿记 18+19=**22** 分列；manifest 19、tables 10、`pg_proc` **172**（164 helper + 8 trigger guard）、唯一 DEFINER `advance`、public EXECUTE 0、无 VIEW/EXTENSION、3 command kinds、24 错误码、closure 512/B=16。冻结 `v24/load.py`、`v24/sql/**`、`v24/s1`–`s12` 与 `57e2c1e` diff 仍 exit 0，`git diff --check` exit 0。

剩余限制：W1 不执行外部 effect（W2）；无 receipt journal/crash injection/dispatch/run 恢复；reuse/rollback W4 未准入；slot 身份由 `continuation_state` 在推进时重验，ensure 不重复；observer 不读 `events`；既有数据库部署需先 provision observer group（fixture 已做）；无界对抗性低 key 插入下 UUID keyset 只给 E1/E2 假设下的有限公平。

发布状态：本 Result 与实现同属 W1 里程碑变更，仅 stage W1 文件；设计稿 mixed file 的用户 5500 改写不 stage。按父级本轮指令，先返回父级验证，**本会话尚未 commit/push**；验证后再按仓库规则普通提交并 push `origin/v24`（不 force、不 `--no-verify`）。提交/远程 SHA 在父级发布后由交接报告（本文件不自引用自身提交）。

### W2 Result（2026-10-28，实现、CDP6-R 与 37-command 串行实跑）

**结论：W2 Done-when 已实现；最终 37/37 gate 串行 exit 0；本会话仅接受/收尾 W2 范围，W3–W5 未开始。** 起点 HEAD `8d475eaf4032e008952fea5675a64ec277f5b1d3`，分支 `v24`。仅改 `v24/cordis/dp6/driver.py` 与新增 `v24/cordis/dp6/test_recovery.py`；未改 SQL、loader、permission、manifest、设计稿或冻结面。

实现面：

- **external executor**：`Executor` 通过既有 `advance` 提交 `claim`，COMMIT 后核验 `TRANSACTION_STATUS_IDLE` 并关闭连接；Fake/受信 handler 在零 DB 连接下执行；完整 receipt 先原子写入 fsync journal，再在新短事务以原 attempt/fence/owner 提交 `advance`。`host_io`、非 host listener、unsupported 路径不调用 handler。
- **receipt journal**：`ReceiptJournal` 每 effect/token 一个 0600 JSON，目录 0700；临时文件写入 + file/dir fsync + `os.replace`；规范化 SHA-256；torn/duplicate/conflict 显式阻断。`committed`/`replay` 后才 `confirm`；`stale_claim`/`receipt_conflict` 移入 `.dead` 隔离，不静默解析。
- **`run_start` source**：`RunStartSource` 以 `effect_id + contract_version + handler_digest + request + steps + digest` 固定原始请求和初始步数；inbox 只消费一次；missing/corrupt/duplicate/conflicting/mismatch 在 claim 前或 claim 后明确阻断，不从 adapter/events/default 推断。
- **dispatch recovery**：`_dispatch` 只读已提交 child 行；unknown 不 join、不封口；pending child 继续；全部可信 child 已终态但 parent 仍 ready 时只报 invariant，不补 `acc`/next/seal。
- **replay 权限**：仅冻结合同 `repeat=true` 且 `concurrent=true` 可过期重领；原 token 在未被替换前仍可交可信结果；新 fence 使旧 token `stale_claim`；terminal replay-first、冲突零写；host 不猜测。

CDP6-R 覆盖（`test_recovery.py`，真实子进程 kill/restart，Fake handler，无网络）：

- `[R1..R7]` run_start→model→final 生产链；claim 前/COMMIT 后、IO 中、journal 前后、settle COMMIT 前后的 kill；journal replay 与 COMMIT 确认丢失零重复 reducer/event。
- `[R8..R12]` terminal receipt replay/冲突；不可变触发器；repeat/concurrent 2×2；并发重领唯一新 fence；旧 token 过期后仍可结算。
- `[R13..R16]` run_start source missing/corrupt/duplicate/mismatch、allocation 前 kill；L-Iter batch 回滚/重放；install COMMIT ack loss。
- `[R17..R20]` unknown 债务、P6 阻塞；缺凭据/错误真实 LOGIN；torn/duplicate journal 阻断；所有连接 IDLE、handler 零连接、无 idle-in-transaction、文件 0600/0700、driver 无 socket/thread/DML。
- `[R21..R23]` 五种 dispatch mode 半程重启、unknown 不 join、settled-parent invariant。
- `[R24..R28]` withdraw/dispose COMMIT ack loss、adapter 返回后 journal 前 kill、无 replay 权限、digest mismatch、install pre-COMMIT 回滚。

实跑：CDP6-R 单条 `uv run python v24/cordis/dp6/test_recovery.py` **exit 0**，29 个 R 标签，45.33 s；随后 37 条命令（35 条继承 + `test_scanner.py` + `test_recovery.py`）逐条独立 `uv run python` 串行，**37/37 exit 0**；per-command 合计 **244.5 s**，wall **245.2 s**；日志 `/tmp/dp6_w2_verify/gates/`，汇总 `/tmp/dp6_w2_verify/gates.tsv`。无 skipped gate、无真实 provider socket、每个 DB 为 disposable pgembed。

实测：40=1685、41=1481、42=1112、43=700、44=622，total **5600**（report-only，无替代上限）；领域 DDL **465**；簿记 18+19=**22** 分列；manifest 19、tables 10、`pg_proc` 172、唯一 DEFINER `advance`、public EXECUTE 0、3 command kinds、24 错误码、closure 512/B=16。W2 代码 `driver.py` **1028** 行、`test_recovery.py` **1737** 行（report-only）。冻结 `v24/load.py`、`v24/sql/**`、`v24/s1`–`s12` 与 `57e2c1e` diff 仍 exit 0，`git diff --check` exit 0。

审查状态：验收开始时未发现已落盘的 W2 Oracle review（`docs/reviews/` 最新仍为 W1 工件，无 W2 export）；上一 review wrapper 在写出结果前被停止，故本会话未重复启动 review，记录直接代码审计 + 37 条实跑。现有 W2 残余限制：terminal unknown/inverse unknown 仍为 W3 债务；`host_io`/非 host listener 仍 unsupported；journal `.dead` 隔离文件未单独 gate 覆盖，属人工对账面；`run_start` handler 无可发布 receipt 时保持 claimed，不伪造 unknown 终态。

发布状态：W2 仅 stage 本里程碑 6 个文件（driver、test_recovery、DP6 README、matrix、ledger、本 Result）。用户既有 10 modified + 26 untracked 路径不 stage；无 SQL/设计/loader 变更。按父级本轮指令，**本会话尚未 commit/push**；父级验证后按仓库规则普通提交并 push `origin/v24`（不 force、不 `--no-verify`）。

### W3 Result（2026-10-29，unknown/inverse 债务与 dispose 全收敛）

**结论：W3 Done-when 与 CDP6-U/D 已实现；最终 38/38 gate 串行 exit 0；W4/W5 未开始。** 起点 HEAD `4aa1390`，分支 `v24`。仅改 `v24/cordis/sql/42_teardown.sql`（+7 物理行）、`v24/cordis/dp6/driver.py`（债务诊断）并新增 `v24/cordis/dp6/test_dispose.py`；未改 40/41/43/44、loader、permission、manifest、设计稿或冻结面；未新增 command kind/表/列/错误码/解释器/第二 writer。

审计先行（以生产路径证伪，不凭猜测改 SQL）：

- **实证缺陷：inverse-unknown 的 dispose 反复写。** 一棵生产树（child install 的 grandchild fiber 上有未释放 `inverse='unknown'` 贡献）在 `dispose_pending` 后 5 次 quiet pass 产生 **+5 个 `command_dispose` effect、+9 个 request、+3 个 event**：`dispose_plan` 看不到 inverse 债务，返回 `wait_slot` 写空 receipt，而 P6 successor 永久被 `blocked_unknown` 拒绝。加 `dispose_plan` 的 sealed-subtree inverse 谓词后，同一树稳定为 `blocked_unknown/inverse` 且十表零写（`[CDP6-U2]`、`[CDP6-U6]`）。
- **候选修复被既有 gate 否决：`wait_slot → deferred/slot`。** 该候选让 in-flight slot 的 dispose refresh 也零写，但 `v24/cordis/dp3/test_dispose.py` `[CDP3-D5]` 断言 coalesced dispose refresh 必须是 committed no-op（空 emitted）。完整串行在第 25 条 `dp3/test_dispose.py` 失败（`gate 25 exit=1`），因此回退该谓词，不改既有生命周期断言；残余的每 pass 空 receipt 记入台账 DP6-D41/D44，不隐藏。
- **环在 committed 状态不可达。** `fibers_owner_id_fkey` 为立即 FK、owner 身份不可变（55000）、延迟 `fibers_graph` constraint trigger 拒绝 pin/owner/mixed 环（23514 `fiber graph cycle`）与 512 边深链（23514 `fiber graph validation limit`）。因此未给 `dispose_subtree` 加防御性环 guard；`[CDP6-D4]` 证明四种拒绝 + 64 深合法链在 statement timeout 内终止。
- **`dispose_subtree` 的 path-row 计数。** 函数按路径出行，原始 `count(*)` 大于 distinct fiber 数；callers 用 `IN (SELECT id ...)`/`GROUP BY install_id`，语义无害。`min(depth)` 去重被证明错误（base row 恒为 0）并回退；记录为 DP6-D45，未改 SQL。

实现面：

- **driver**：`unknown`/`inverse_unknown` topic 仅读 observer 已授权的原始列（fiber/episode/run/install/runs），诊断含 owner scope、`fiber_disposed`、`install_state`、raw-fact `blocks` 与 `debt_digest`；debt 资源/补偿内容不复制到诊断，不做调度决策。
- **42**：`dispose_plan` 在 host_io/effect-unknown 之后、ready/run 之前，对整个 sealed subtree 的未释放 `inverse='unknown'` 返回 `blocked_unknown/inverse`；`dispose_delta` 在 barrier 处零写。
- **测试**：CDP6-U1–U6、D1–D4，共 10 个标签；真实 `advance`/scanner/单个 SIGKILL 子进程，Fake handler，无网络。

实跑：

- `uv run python v24/cordis/dp6/test_dispose.py` exit 0，10 个 U/D 标签。
- 之后 38 条命令（35 继承 + `test_scanner.py` + `test_recovery.py` + `test_dispose.py`）逐条独立 `uv run python` 串行，**38/38 exit 0**；per-command 合计 **257.8 s**，wall ≈**258.5 s**；日志 `/tmp/dp6_w3/gates/`，汇总 `/tmp/dp6_w3/gates.tsv`。逐条命令/退出码/耗时见矩阵 §38-command serial gate evidence。
- **Attempt 1**：第 16 条 `v24/s4/test_g2b.py` 出现锁等待可见性 flake（`pg_blocking_pids` 尚未记录 waiter；冻结面未改）；该 gate 单独 3/3 通过且最终全量通过。**Attempt 2**：第 25 条 `dp3/test_dispose.py` 抓到候选 `wait_slot` 改动的真实回归，回退后通过。**Attempt 3（最终）** 为回退后的干净 38/38；三次证据均保留在 `/tmp/dp6_w3/`，未用重跑掩盖回归。

实测：40=1685、41=1481、42=**1119**、43=700、44=622，total **5607**（report-only，无替代上限）；领域 DDL **465**；簿记 18+19=**22** 分列；manifest 19、tables 10、`pg_proc` 172（164 private helpers + 8 trigger guards）、唯一 DEFINER `advance`、public EXECUTE 0、3 command kinds、24 错误码、closure 512/B=16。`driver.py` **1076**、`test_dispose.py` **956**（report-only）。冻结 `v24/load.py`、`v24/sql/**`、`v24/s1`–`s12` 与 `57e2c1e` diff 仍 exit 0，`git diff --check` exit 0。

剩余限制：

- **terminal unknown 自动解析仍为设计闸门。** 人工核验/补偿无批准 ABI，W3 保持 blocked 并记录（`[CDP6-U6]`、DP6-D40），不新增状态列/表/命令，不改写 terminal outcome。
- **>256 withdraw closure 的 coalesced refresh 仍有写放大。** `wait_slot` 契约保留，因此永久 stuck slot 每 pass 写一条空 `command_dispose` receipt；无 release/close/tombstone，非债务伪造，记 DP6-D44。
- **`dispose_subtree` path-row 计数语义未改**（DP6-D45）；owner/pin/mixed 环在 committed 状态不可达，故未加环 guard。
- `host_io`/非 host listener 仍 unsupported；无真实 adapter/socket。W3 未触发 scoped Oracle design（无真正设计阻塞），也未启动 Oracle review；验收为直接代码审计 + 38 条实跑（DP6-D47）。

发布状态：仅 stage 本 W3 的 6 个文件（`42_teardown.sql`、`driver.py`、`test_dispose.py`、DP6 README、matrix、ledger）与本 Result；用户既有 10 modified + 26 untracked 不 stage；未 commit/push，父级验收后按仓库规则普通提交并 push `origin/v24`（不 force、不 `--no-verify`）。

### W4 Result（2026-10-29，drain upgrade / rollback / HMR 与 CDP6-H）

**结论：W4 Done-when 与 CDP6-H 已实现；最终 39/39 gate 串行 exit 0；W5 未开始。** 起点 HEAD
`d58a6ee5a88057a33c462cbe24918d02f63980f1`，分支 `v24`，`origin/v24` 同 SHA。本会话只改
`v24/cordis/sql/40_advance.sql`（+7 物理行）、`v24/cordis/sql/41_lifecycle.sql`（+204）与
`v24/cordis/dp6/driver.py`，并新增 `v24/cordis/dp6/test_upgrade.py`；未改 42/43/44、loader、
permission、manifest、设计稿或冻结面；未新增表/列/command kind/错误码/解释器/第二 writer。

**语义准入（实现前文档级证明，未触发 Oracle）：**reuse 是既有 `command_install` 的第二种精确
payload `{mode:'reuse',install_id,fiber_id,expected_digest}`。证明覆盖：payload 精确键集与 canonical
bytes/effect id；closure seed（install+scope+owner fiber/episode+owner episode contributions+该
install 全部 fibers）与 G-first 锁序/锁后重验；validator（零 scope/install create、恰一
fiber/contribution/progress、owner 字段、child inverse、`install_reused` event、`successors:[]`）；
既有 `assert_delta_applied` postcondition；owner/episode live+current、iterator/seq 上界、live
resolve 与同代 failure；I7（reuse 是 command_install，不占 reconcile slot）；唯一地址仍由
`contributions_service_addr` 与 P2/P4 仲裁；`dispose_subtree(install)` 覆盖该 install 的全部历史
fiber；operation UUID/actor/source/target/source-seq/digest 由首个 request key/bytes 固定；无 phase
table/cursor。**root install 因单 root 不变量结构性不可复用**，admission 返回
`invalid_args/install_reuse_root`、driver 返回 `switch_target_install_exists`，作为受 gate 的拒绝
记录，不伪造可回滚；非 root child install 完整支持。证明表见矩阵 §W4。

**实现面：**

- **driver**：`SwitchPlan` 固定 kind/operation/actor/source/target/source_seq/install/digest/payload/
  provides；`SwitchDriver` 以 observer 只读事实派生
  `start_pending→off_pending→draining→on_pending→activating→complete|failed|blocked`；
  `start`/`off`/`on` 只提交既有 `command_install`/`command_reconcile`，drain 仅由 W1
  `Maintainer` 推进；`resume` 从已提交 start request 重建（U 读 declaration，R 从 source fiber
  保留的 service 历史派生 expected keys），首提交前无 DB intent 时只能由调用方重交；slot/actor/
  payload/stale-seq/target-moved 冲突均停止而不猜测。
- **41**：reuse admission/delta/validator/seed/preflight/references/binding 分支；新 fiber 引用
  不可变 install 的 scope/owner，append 既有 child contribution（`dispose_child` inverse）与
  episode_progress；不创建/修改 install，不复活旧 fiber。
- **40**：`event_payload_valid` 增加 `install_reused` 精确 payload；未改任何 command kind/错误码/
  表/列。
- **HMR**：`HmrTrigger` 仅读预部署 JSON descriptor（identity/version/digest/operation_uuid/
  source_fiber_id/install_id/target_fiber_id/manifest/contracts/policy_ref/overlay），与运行中
  install 的 version+digest 比较后提交同一 frozen switch request；重复 tick replay，descriptor
  形状/identity 不符为诊断；无下载/import/ESM cache/进程内状态搬运，手工 driver 流程不依赖 watcher。

**CDP6-H 覆盖：**H1（新声明身份/digest 不变/原地覆盖被 command、driver、immutable trigger 拒绝，
重复 scope+identity+version 零写）；H2（open run、activation pin、已创建 host listener child 分别
阻止旧地址释放；withdrawn 后 pin/contribution 历史仍可读，release 后 resolve 只指向新代）；H3（全程
单 live provider 唯一索引；空窗 0 live/无 resolve/旧行仍可读；新 provider 不早于 release 激活）；
H3b（release 前 on → `provide_conflict` 失败、无双 live，之后显式 rollback 成功）；H3c（依赖
`missing-svc` 不满足 → on successor `dependency_unresolved` 零写、无 episode/failure、地址为空、
switch 保持 activating，随后显式 rollback 成功）；H4a–H4d（首请求 COMMIT 前回滚无 intent；
start/off COMMIT 后、mid-P6、address-release、on COMMIT 后真实 SIGKILL，空内存新 driver 从已提交
事实恢复，三相位各恰一 request、无重复 install/fiber/episode）；H5（同 operation 不同 bytes/actor、
同槽未完成操作、独立 control seq、目标被独立启用、重复 fiber、digest 不匹配、旧 owner episode 变化
均拒绝或稳定 blocked，零写）；H6（rollback 新 fiber/episode、旧 fiber 不复活、旧声明不变、新地址
归属新 episode；整个旧 install dispose 覆盖两个历史实例；disposed install 不可再复用/回滚；R start
与 R on 真实 SIGKILL 恢复）；H7（terminal unknown 使 upgrade 持续 draining、地址不释放、debt 行
byte-stable、quiet pass 零写、rollback reuse `blocked_unknown/install_reuse_debt` 零写）；H8（升级后
service 与 event listener 均只指向新代，空窗与 dispatch child 不混代）；H9（HMR 首 tick 提交 frozen
request，重复 tick replay，current descriptor 零写，malformed/mismatch 诊断，无 download/ESM 路径）。

**实跑：**`uv run python v24/cordis/dp6/test_upgrade.py` exit 0，14 个 H 标签；随后 39 条命令
（35 继承 + `test_scanner.py` + `test_recovery.py` + `test_dispose.py` + `test_upgrade.py`）逐条独立
`uv run python` 串行，**39/39 exit 0**；per-command 合计 **283.3 s**，wall ≈**306.2 s**；日志
`/tmp/dp6_w4_final2/gates/`，汇总 `/tmp/dp6_w4_final2/gates.tsv`。最终串行后又单独重跑一次 `test_upgrade.py`，
仍 exit 0。无 skipped gate、无真实 provider socket、每个 DB 为 disposable pgembed；14 个 H 测试各用
独立数据库，崩溃用例使用真实子进程 SIGKILL（start 前回滚、start/off、mid-P6、release、on、R
start/R on）。

**实测：**40=**1692**、41=**1685**、42=1119、43=700、44=622，total **5818**（report-only，无替代
上限）；领域 DDL **465**；簿记 18+19=**22** 分列；manifest 19、tables 10、`pg_proc` **172**
（164 private helpers + 8 trigger guards）、唯一 DEFINER `advance`、public EXECUTE 0、无 VIEW/
EXTENSION、3 command kinds、24 错误码、closure 512/successor 16/I7/唯一地址不变。`driver.py`
**1868**、`test_upgrade.py` **1215**（report-only）。冻结 `v24/load.py`、`v24/sql/**`、`v24/s1`–`s12`
与 `57e2c1e` diff 仍 exit 0，`git diff --check` exit 0。

**剩余限制：**

- **root install rollback 不支持**：单 root 不变量使第二条 ownerless fiber 不可创建；已作为
  `install_reuse_root`/`switch_target_install_exists` 拒绝记录，非 root child install 完整支持。
- **R resume 的 expected keys 从 source fiber 保留的 service 历史派生**；若地址集合在无 source
  contribution 的情况下变化，报告 `blocked/switch_address_missing`，不猜测。
- **未知债务仍安全阻塞**：terminal unknown 使 upgrade 持续 draining，rollback reuse 返回
  `blocked_unknown/install_reuse_debt`，不清理、不改写 terminal 事实；人工对账 ABI 仍是设计闸门。
- **HMR 是宿主侧预部署 descriptor 触发器**：operation/target UUID 由部署步骤固定，不下载、不
  import、不失效 ESM、不搬运进程内状态；descriptor 不是 DB 表。
- 无 W4 Oracle design/review：reuse 合同已按既有 ABI 证明，root 为显式拒绝，无真正设计阻塞。
- W5（`CDP6-B` 与 DP6 总收尾）未开始。

**发布状态：**仅 stage 本 W4 的 7 个文件/工件（`40_advance.sql`、`41_lifecycle.sql`、`driver.py`、
`test_upgrade.py`、DP6 README、matrix、ledger）与本 Result；设计稿、DP1–DP5 与用户既有 10 modified
+ 26 untracked 路径不 stage。按父级本轮指令，**本会话尚未 commit/push**；父级验收后按仓库规则普通
提交并 push `origin/v24`（不 force、不 `--no-verify`）。W5 由下一位 fresh pair agent 负责。

### W5 Result（2026-10-29，最终边界、CDP6-B 与 DP6 收尾）

**结论：W5 Done-when 与 CDP6-B 已实现；最终 40/40 gate 串行 exit 0；DP6 计划的 W1–W5 五个里程碑
均已交付并各自通过当时继承 gate。** 起点 HEAD `ea2a18ca235d69a24b188311e247b8fd137a3d0e`，分支
`v24`，`origin/v24` 同 SHA；main checkout 未触碰。本会话仅新增
`v24/cordis/dp6/test_boundaries.py`（690 行）并更新 DP6 README、matrix、ledger 与本 Result；未改
SQL、loader、permission、manifest、driver、设计稿或冻结面，未新增表/列/command kind/错误码/
解释器/第二调度器/第二 writer。

**CDP6-B 实现与证据：**

- **B1**：19 项 canonical manifest 与缺失/重复/乱序/未注册/符号链接/目录负例；helper 5818、DDL
  465、簿记 22（只报告、无上限）；十表、无 view/materialized view/extension；3 command kind；3 个
  lifecycle interpreter（`interpret_install`/`interpret_reconcile`/`interpret_dispose`）由
  `interpret_command` 唯一映射；6 个 IMMUTABLE 只读 helper 的纯度与无执行/RAISE/网络/文件/COPY token；24 错误码闭合；唯一 `advance` SECURITY DEFINER、PUBLIC EXECUTE 0；
  唯一 G（`24,1`）——真实持锁使并发 `advance` 以 `57014` 取消，释放后同一调用返回
  `not_found_or_denied`，十表字节相等。
- **B2**：observer LOGIN 仅一个 NOLOGIN 组 membership；八表列白名单逐列与 catalog 相等；表级
  SELECT、白名单外列、DML/TRUNCATE、TEMP、CREATE、`advance` EXECUTE、协议角色全部 42501；原
  admin/service/operator 无任何表/列权限、仅 `advance` EXECUTE、无 owner membership，所有直接
  DML/`SET ROLE owner` 均 42501 且十表零写。
- **B3**：真实 `command_install`/`command_reconcile`/`command_dispose` 各提交成功，三解释器全部
  活路径；第四 kind `command_unknown` 为 `invalid_args` 且十表零写。
- **B4**：唯一 ready reconcile 后继；开放 slot 上 `ensure` 为
  `stale_generation/ensure_slot_present` 零写；消费后继后相同字节 replay 返回缓存响应且零写；
  不同字节/外部 LOGIN 分别 `request_conflict`/`effect_id_conflict` 零写；terminal effect/request
  UPDATE 均 55000；第二个 ready 后继 `23505`。
- **B5**：真实 body 200/201 keys、32/33 depth；`validate_delta` 16/17 与重复 ordinal；真实
  `discover_closure` 512/513 与 delta-write closure；15 listeners 提交 16 effects，16 listeners/
  17 successors 为 `invalid_outcome/budget` 且无 dispatch/child 行。
- **B6**：十二个冻结 `v24/sql` SHA-256、冻结 `v24/load.py`/`v24/sql/**`/`v24/s1`–`s12` 对
  `57e2c1e` diff、`git diff --check` 均 exit 0；冻结 v24 loader 12 项 self-check 与五个拒绝探针
  通过。

**实跑：**`uv run python v24/cordis/dp6/test_boundaries.py` 作为独立进程 exit 0（3.463 s，B1–B6 标签）；
随后 40 条命令（35 继承 + `test_scanner.py` + `test_recovery.py` + `test_dispose.py` +
`test_upgrade.py` + `test_boundaries.py`）逐条独立 `uv run python` 串行，**40/40 exit 0**；
per-command 合计 **284.449 s**，wall **284.5 s**；日志 `/tmp/dp6_w5/gates/gate-01..40.log`，汇总
`/tmp/dp6_w5/gates.tsv`。无 skip、无并发、无真实 provider socket，全部 DB 为 disposable pgembed。
**Attempt history：**首次自测只暴露两个 gate 局部期望错误（observer 对全列授权表的 `SELECT *`
应成功；多列 `one()` 只返回首列），均在测试内修正，未改产品/SQL/冻结/继承 gate；最终 40/40 干净。

**实测：**40=**1692**、41=**1685**、42=**1119**、43=**700**、44=**622**，total **5818**
（report-only，无替代上限）；领域 DDL **465**；簿记 18+19=**22** 分列；manifest 19、tables 10、
`pg_proc` **172**（164 private helpers + 8 trigger guards）、唯一 DEFINER `advance`、public
EXECUTE 0、无 VIEW/EXTENSION、3 command kinds、24 错误码、3 lifecycle interpreters、唯一 G、
closure 512、successor 16。`driver.py` **1868**、`test_boundaries.py` **690**（report-only）。
`git diff --check` exit 0；冻结面 diff 对 `57e2c1e` exit 0。

**W4 Oracle review 诚实记录：**未发现任何已落盘的 W4 Oracle review/design 结果；该次 review 尝试
在产生结果/export 前因控制器失效而终止，故 **不能称为 review passed**。W4 的验收依据是文档级
admission proof 与 39 条实跑；W5 未重复启动 review，也未把“尝试过”写成“已审查通过”。

**剩余限制（W5 不解决、不冒称完成）：**

- terminal unknown 与 inverse-unknown 债务仍按设计 §6.2/§12.2 保留为 `blocked_unknown`；人工对账
  ABI 仍是设计闸门（DP6-D16/D40），W5 未新增状态列/表/命令或改写终态事实。
- 多宿主正确性、数据库强制的全局公平、外部 exactly-once、无缝进程内 HMR 均**未实现**且不在
  DP6 声称范围内；HMR 仍只是宿主侧预部署 descriptor 触发同一 version switch。
- root install rollback 仍因单 root 不变量被拒绝；非 root child install 完整支持。`host_io` 仍
  unsupported/`0A000`；无真实 adapter。
- `>256` withdraw closure 的 coalesced dispose refresh 仍每 pass 写一条空 receipt（DP6-D44）；
  owner/pin/mixed 环在 committed 状态不可达，未新增防御 guard（DP6-D43/D45）。

**发布状态：**仅暂存 W5 的 5 个文件/工件（`v24/cordis/dp6/test_boundaries.py`、DP6 README、
matrix、ledger 与本 Result）。启动时工作区为 10 modified + 26 untracked，均为用户既有路径；DP6
plan 是 HEAD 已跟踪的里程碑工件，随本 Result 一并暂存。上述 10 modified + 26 untracked 用户路径
不 stage。设计稿、DP1–DP5 与冻结面不 stage。按父级本轮指令，**本会话不 commit/push**；父级验收后
按仓库规则普通提交并 push `origin/v24`（不 force、不 `--no-verify`）。
