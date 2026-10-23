## 1. Coverage matrix

证据源：`../designs/v24-pg-agent-2026-10-22.md`（652 行），下文 L 均为该文件行号。本文仅为研究备忘录，不是施工计划或实现；R4 SATISFIED 不等于实现验收（§11，L638–652），全部候选 gate 均未验证。已读取仓库及 v99 worktree 的 AGENTS.md；本轮文档不触发里程碑提交流程（§9，L431）。

每行只有一个主责 stage；“双阶段”仅标同节存在必须分开的交付切面，普通合同消费不重复记覆盖。schema 行指十表完整 DDL 所有权，不代表 S1 已实现各表的领域行为。G2a/b、G3a/b 是本文建议拆分，原规格只有 G2/G3（§9，L436–437）。

| 设计节组 | 主责 | 覆盖切面 / 必要双阶段 |
|---|---|---|
| §2（L59–114） | S1 | advance、G、admission/claim/settlement、delta/resolve/reduce 接口；具体解释器随其所属章节消费 |
| §3.1.1（L122–132） | S1 | scope 创建、不可变路径/路由；**双阶段 S5**：close 排空行为（L128–130） |
| §3.1.2（L134–138） | S1 | runs 列与约束；状态机由 S3 消费 |
| §3.1.3（L140–144） | S1 | effect 身份、状态、token、kind 闭集 |
| §3.1.4（L146–148） | S1 | 两类 pin 的 schema/FK |
| §3.1.5（L150–154） | S1 | episode 身份、唯一性、历史 owner FK 目标 |
| §3.1.6（L156–160） | S1 | fiber 当前投影、控制序号、墓碑 |
| §3.1.7（L162–166） | S1 | slot、不可变 descriptor、占槽身份 |
| §3.1.8（L168–172） | S1 | install 声明、准备态、历史 owner 身份 |
| §3.1.9（L174–176） | S1 | append-only events、游标与唯一性 |
| §3.1.10（L178–180） | S1 | request bytes、response、延迟 FK |
| §3.2（L182–197） | S1 | 必要索引/约束；动态屏障由对应解释器消费 |
| §3.3（L199–203） | S1 | 十表边界、禁止第二事实账 |
| §3.4（L205–207） | S2 | resolve/activation/withdraw/pin；**双阶段 S5**：owner 与 scope 完整排空 |
| §4.1（L211–215） | S3 | 四写两读公共边界、规范请求与 wrapper |
| §4.2（L217–225） | S3 | start、首个 model effect、run pins |
| §4.3（L227–231） | S3 | poll 纯读、授权与 revision |
| §4.4（L233–237） | S3 | wait handle/游标、事务外等待 |
| §4.5（L239–249） | S3 | cancel/generation/seal；**双阶段 S4**：在途 T2 成本与后继资格结算 |
| §4.6（L251–257） | S3 | steer/epoch/pending_steer；**双阶段 S4**：旧 IO 静默后的唯一续链 |
| §4.7（L259–265） | S3 | respond CAS/精确 replay；interaction 生产由 S4 消费合同 |
| §5.1（L269–275） | S4 | model/tool 回合闭环、批次屏障 |
| §5.2（L277–283） | S4 | 预留/结算、硬上限、预算封口 |
| §5.3（L285–291） | S4 | close intent、unknown wall、静默与 pin 释放 |
| §5.4（L293–299） | S4 | 固定 reducer、结构化输出、唯一 continuation |
| §5.5（L301–307） | S4 | spawn intent、child/quota/edge 原子性 |
| §5.6（L309–313） | S4 | 两种 IO effect 的冻结请求与 adapter |
| §6.1（L315–321） | S1 | 生命周期同入口、install→host_prepare 实证 |
| §6.2（L323–329） | S1 | root install/准备协议；**双阶段 S2**：child admission 校验 active owner |
| §6.3（L331–339） | S2 | control/activation、无 owner children 的退役；**双阶段 S5**：递归 children 屏障 |
| §6.4（L341–347） | S2 | 最小 episode 与无 run activation pin 反例 |
| §6.5（L349–355） | S2 | resolve、硬依赖、realm/key 与 withdraw/release |
| §6.6（L357–363） | S5 | owner/dependency 合并 DAG、子优先与贡献 DESC |
| §6.7（L365–369） | S2 | leaf dispose、host_release/inspect；**双阶段 S5**：完整历史 owner 闭包 |
| §6.8（L371–375） | S3 | run 与 episode 边界；spawn/长活 child 判据由 S4/S5 消费 |
| §7（L377–404） | S7 | 三面矩阵及所有双提交序的集成验收 |
| §8（L406–427） | S6 | 十行崩溃窗口、恢复唯一入口及 v99 差异 |
| §9（L429–448） | S7 | 总体验收覆盖汇总；各 gate 主责见第三节，不延后到 S7 才测试 |
| §10（L450–489） | S1 | 非目标、D1–D4 信任边界与证伪合同；后续 stage 持续消费 |
| App A（L609–637） | S1 | kind/ABI、claim 三段协议、唯一写口 |
| App B（L491–606） | S1 | 锁向量、ACL、错误/回放/状态合同；领域与竞态证明由后续 gate 消费 |

## 2. Dependency findings

(a) **能力绑定路径是，因而 S2 必须先于 S3 的完整验收。** start 只绑定既有 fiber episode，不激活插件（§4.2，L219–225）；无可用 episode 时先 start 必须失败、零 run，先 activate 才能成功 pin（§7.2，L394–396）。但签名允许 owner=NULL（§4.2，L219），完全无能力依赖的 ownerless start 是否也必须有 episode 为 **uncertain**；不能据此绕过 G3 所需的真实能力绑定前置。

(b) **“唯一”不成立，但 S1 仍应含 root install+host_prepare。** root install 的 owner 可空，且准备 receipt 足以 installed，无须 run/fiber 激活（§6.1–6.2，L321–329）；这是 S1 用领域真实路径验证 command→ready→claim→事务外 Fake IO→settlement 的最短候选。未激活 install 也能 dispose→host_release，prepare_unknown 可经 inspect 收束，同样不要求已有 run/fiber（§6.7，L367–369；§B.4，L578–580）。因此 S1 含 install 是候选边界裁决，不是“只有这一种 host effect”的逻辑必然；本轮不调用真实 host IO，gate 仍 Fake-only（§9，L431）。

(c) **G3 要拆，G2 也要拆。** G3 明列 run pin 挡 release、withdraw 后新 run 失败、claim/close 双序（§9，L437），而 run pin 由 start 原子生成（§4.2，L219–223）；故 S2/G3a 只证明无 run activation consumer、resolve/realm/空 inject，S3/G3b 承担 run/claim 的 pin 屏障。G2 cancel×T2 不只是 command CAS：T2 先需保留成本/事件并取消已生成 successor，cancel 先需接纳原 token 事实/成本但阻后继（§7.2，L398–400）；这需要真实 loop settlement（§5.3，L287–291），归 S4/G2b，S3/G2a 不能宣称完整 G2 已绿。

(d) **建议验收顺序 S1→S2→S3→S4→S5→(S6 ∥ S7)。** S5 完整 drain 消费 S4 的静默/unknown/pin 合同（§5.3，L287–291；§6.6，L359–363）。S6 只扫 resolve/未结算 effect（§8，L421），S7 验命令/receipt 双序（§9，L440、L444–446），在 S5 冻结完整资源合同后可并行；若 S6 发现并修改共享语义，S7 对应证据必须重验。S4 与 S5 可并行准备局部工作，但不能据此并行完成完整 gate。运行期 DB mutation 仍由 G 串行（§B.1，L497–517），不等于施工阶段不能并行。

## 3. Stage table

以下均是候选研究分界，不是已批准计划。每行候选 1 个里程碑＝1 次 commit，共 7；G2a+G3b 同属 S3 一个里程碑。未来完成时须全 stage gate 实跑全绿及收尾工件齐备再按 AGENTS.md 提交推送；本备忘录不构成完成任何里程碑。

| Stage / goal | Design sections | Owned gate/sub-gate | Prerequisites | Frozen contracts published | Frozen contracts consumed | Milestone count |
|---|---|---|---|---|---|---|
| S1 内核(advance+schema+scope/install/host_prepare)=G1 | §2、§3.1–3.3、§6.1–6.2 root、§10、App A/B | G1：以 root install/host_prepare 覆盖 command+host、事务回滚、token、replay、零写负例（§9，L435、L446） | 第一批合同缺口裁决；无实现 stage 前置 | 十表 DDL/FK、唯一写口与 ACL、G/closure 顺序、canonical request/receipt、错误写类、delta/reducer 接缝、claim/fence、reservation/inspect ABI、scope create/路由与 prepare 状态 | 规格与 AGENTS.md | 1 |
| S2 能力面(fiber/episode/slot/pin/resolve/fiber_control/leaf dispose)=G3a | §3.4 能力部分、§6.2 child、§6.3–6.5、§6.7 leaf | G3a：无 run activation pin、realm/key、空/缺 inject、原子失败；leaf release/inspect 基础负例 | S1；retry、FK 顺序冻结 | resolver/live predicate、activation pin、episode E1→E2、control CAS/reconcile、withdraw/release、leaf dispose、child admission 的历史 owner 身份 | S1 DDL、delta、claim、reservation、错误写类 | 1 |
| S3 六动词+run 状态机=G2a+G3b | §4.1–4.7 命令/读面、§6.8 | G2a：四写两读、generation/interaction CAS、terminal steer、零写读；G3b：start run-pin、close/claim 双序、新 run 拒绝；完整 T2 排空留 G2b | S1+S2；真实 activation/resolve 可供 start 消费 | run handle、registration/epoch/driving generation、start pins/首 effect、interaction 消费、pending_steer、cancel 发布权与 terminal/资源静默分离 | S1 admission/replay；S2 episode、pin、resolver、withdraw | 1 |
| S4 loop=G2b | §5.1–5.6；§4.5–4.6 的 settlement 切面 | G2b：闭环、并行 tool batch、唯一 model、预算、unknown/seal、cancel×T2、pending_steer 续链；与 G2a 合成完整 G2（§9，L436） | S3；预算/输出/reducer 合同冻结 | chat_tool_v1、model/tool outcome、批次身份/continuation、预留与成本结算、静默后 pin 释放、spawn/quota 原子性、close intent | S1 receipt/delta/token；S2 固定能力；S3 run/interaction/generation/pin 合同 | 1 |
| S5 owner 级联/scope close/dispose 闭包=G4 | §3.1.1 close、§3.4 排空、§6.3 级联、§6.6、§6.7 闭包 | G4：≥3 节点合并图、cleanup_cycle、子优先/贡献 DESC、失败不 closed；追加 scope/prepare_unknown 屏障（§9，L438、L440、L446） | S4，及 S2 leaf 基础 | 固定历史 owner 闭包、有限清理阶段、全 scope/install 排空、prepare/release debt、无 inspect 永远 pending/closing | S1 closure 锁/有界后继；S2 生命周期/leaf；S3 cancel；S4 settlement/静默/unknown | 1 |
| S6 崩溃恢复=G5 | §8；消费 §10.2、App B 回放权利 | G5：按十行窗口验证重启收敛、持久 Fake IO journal、response/后继不重复；“7 点”先裁决（§8，L410–421；§9，L439、L446） | S5；kill 行与 T1/T2 术语已冻结 | 唯一扫描/replay/inspect 恢复接口、窗口→证据映射；无自有 queue/claim/lease | S1 token/replay/reservation；S2 resolver；S3–S5 全领域状态/资源屏障 | 1 |
| S7 并发矩阵=G6 | §7、§9 总体验收；App B.2 证据 | G6：所有列举双序、scope/owner/child/spawn 负例；双连接屏障+pg_blocking_pids 证明（§9，L440、L444–446；§B.2，L531） | S5；可与 S6 并行，最终总体验收需二者全绿 | 双提交序预期/证据矩阵、跨面合同一致性结论 | S1 G/锁/ACL；S2–S5 能力/控制/IO/闭包合同；消费 S6 的共享合同修订（若有） | 1 |

## 4. Gap list

“freeze now”指在首个消费 stage 之前裁决合同，不是在本轮修改设计；“defer”也不免除未来 Fake gate 的实证责任。

| Gap | § / line evidence and finding | Freeze now or defer recommendation |
|---|---|---|
| (a) 不存在的 request 行如何锁 | §2.3 L87 要锁 request 身份；§B.1 L498 已说“身份行或唯一键冲突槽”，但不存在行的具体 SQL 机制未定义；§B.1 L497、L511 的 G 已排除协议 writer 竞争，不能声称 SELECT FOR UPDATE 锁住空行。 | **freeze now / S1**：明确以 G 串行首次查无→插入、主键兜底与既有行锁定；“冲突槽”若另有所指则标 uncertain，禁止暗增资格锁。 |
| (b) 非 run events.seq 来源 | §3.1.9 L176 只明确每 run 单调，却用所有 entity 的 UNIQUE(entity_type,entity_id,seq)；§B.1 L507 只规定最后写序列，不给非 run 分配算法。 | **freeze now / S1**：给所有可发事件 entity 冻结同一事务内 seq 分配/回滚/replay 规则，不新增第十一表。 |
| (c) 错误闭集无逐码 write-class | §B.3 L554–556 仅给闭集和概括分类；§B.5 L592–598 补语义失败/start receipt，但 generation 等仍无完整逐码表；§B.4 L564 的 receipt_conflict 还不在 L554 闭集。 | **freeze now / S1**：逐码标无写拒绝、稳定失败 receipt、SQL 回滚及 replay 优先级，同时对齐 receipt_conflict。 |
| (d) fiber current ↔ episode FK 环 | §3.1.5 L152 的 episode.fiber_id、§3.1.6 L158 的 current 指针与 §3.2 L188 组成身份/当前投影环；不能误报成 R3 已修的“历史 owner FK 指 current”问题；§11 L650–652 明留 DDL/更新顺序债务。 | **freeze now / S1，S2 实证**：冻结可空 current→插 episode→设 current 及关闭后清 current 的约束时点；实际 FK 延迟策略目前 uncertain。 |
| (e) fiber_control retry 语义 | §6.3 L333 给 on/off/retry，但仅说明目标一致/no-op 和 reconcile；§3.1.6 L160 只要求未 dispose 且递增 control_seq；§B.5 L602 只细化 on/off；install 的准备 retry 另见 §3.1.8 L172。 | **freeze now / S2**：明确 retry 的目标、failure_seq 清理、CAS/no-op、未知资源门槛与唯一 reconcile；不得推定它同时重试 install prepare。 |
| (f) G5 7 点 vs 十行；T1/T2 | §9 L439 写 7 个，§8 L410–419 实列十行；§9 L435、L439 使用 T1/T2；T2 并非完全未定义，§7.1 L381 明确为 model/tool outcome advance，T1 无对应定义；host prepare/release 是否也叫 T2 为 uncertain。 | **freeze now / S1 术语、S6 验收清单**：明确 claim COMMIT/IO/settlement 各边界及命名适用范围，逐行覆盖十窗口；若聚合成七点须给完整对应，不能丢三行。 |
| (g) parent effect/ordinal 无 DB 约束？ | **该缺口不成立**：§2.6 L112 已要求同父/ordinal 唯一，§3.2 L186 明列 effects 的必要唯一约束；§5.4 L299 再用于 continuation 去重。缺实现 DDL 符合 spec-only 状态，不等于规格缺约束。 | **defer 实现证据至 S1 / S4**：S1 落实唯一约束及 NULL/ordinal 适用边界，S4 验 batch/continuation 重放；无需新增语义要求。 |
