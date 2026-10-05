# v13 stage 40（agentctl）+ D-A 权威归属 Oracle 裁决记录（2026-10-03）

**性质：双车道 Oracle 裁决记录。** 送裁清单：`prompt-exports/v13-stage40-da-ruling-checklist-2026-10-03.md`（gitignored，13 条）。父指令（2026-10-03）：全部由 Oracle 裁决。车道一 `untitled-chat-B5F1CA`（默认模型，逐条裁决）；车道二 `untitled-chat-599301`（对抗复核）。本记录合并两车道结论；设计稿 §7/§8 与调查报告 §8 的「已裁」标注随首里程碑提交时同笔回填。

**权威顺序**：用户既有决定（Phase 0 §2）> Phase 0 T0–T7 > R2/R3/R4 裁决链 > Phase A–D 合同 > 设计稿倾向（非约束）。

## 一、逐条终裁（两车道合并守卫后）

| # | 终裁 | 合并守卫（两车道共同或收紧后） |
|---|---|---|
| D-1 | **A**：UA 先行，agentctl 后跟 | 同一原子交付内完成「冻结中心变更（`r1_load_append_ok` 追加项闭集收紧版）+ `SQL_LOAD_ORDER` 追加 + gate」，不得先改冻结规则后补 stage；不扩 UA 的时长/provider/人工动作授权；不动 stage 1–16 |
| D-2 | **确认**勘误 | S1 收尾同笔修正 parity R6 + 台账勘误记录（F22 真问题=catalog 具名例外）；盘点快照不回改；dispatch 零 DDL、不得把「翻 true」记作交付 |
| D-3 | **甲**：允许 `source_principal=controller` | 身份由当前 `p_sid` 可信路由上下文派生，**拒绝/覆盖模型自报的 source_principal**；`v13_control_authorized` 硬前置且不得扩为任意后代；审计三联（调用者/目标/注入事件）；gate 覆盖伪造 operator/越权零写/watermark/正文消费；不得绕过 skip/plan_commit 禁令 |
| D-4 | **丙→条件准入**（限界复访结论=S1 observe 先行 + S2 三员同笔部署） | 见「残余父决 R-1」——复访结论本体两车道一致（三员仅封装既有动词、库内事务写、无外部 IO、维持 spawn SQL 档），但**是否正式满足 R2 §7 重开条件**车道二裁定 Oracle 不得自我豁免，须父签认。技术守卫（两车道一致，S2 gate 必含）：write_targets 按实际调用图核实（含 answer→complete 的传递写、触发器、closeout/unknown 路径、拒绝路径零写），非手写声明；DEFINER 属主不得隐式升级调用者为 operator（授权在可信调用者上下文完成）；四件套纪律（DEFINER/固定 search_path/专用 NOLOGIN 属主/REVOKE PUBLIC）；不豁免未来扩员复访 |
| D-5 | **乙**：版本化策略行区分，零新标记 | 策略版本随 request 冻结入快照；策略只决定工具面/路由，**不得持有 goal/授权/结算事实**（防第二状态源）；gate 校验实际 envelope 而非仅四行入表 |
| D-6 | **确认**（改动后裁）：版本化带判别标签的消费合同 | 闭集 `choice\|score\|noul` + schema_version + 问题键；选项集/量尺绑定冻结 request（拒绝模型临时发明）；数值有限性/范围/分布校验，容限版本化、禁静默修补；阈值与执行结论留 SQL；confidence 按未校准处理除非可验证；非法判断沿既有失败/等待合同；gate 覆合法三分支/越界/未知选项/分布错/键错配 |
| D-7 | **确认**：首期 llm 档，judge 档随后 | D-6 非 S1 前置；gate 须证动词选择来自模型输出（Python 不得硬编码控制序列）；judge 档启用前置=D-6+确定性消费合同（Choice≠完整工具调用）；不新增 effects.kind/route 动作 |
| D-8 | **否决原案**，采纳最小替代合同（经车道二收紧） | 「冻结前绑定、冻结后不变」保留；**「合法新 effect 边界」闭集化**（车道二修正）：retry/超时重试/stale recovery/replay/repair 不得换档；新 effect_id 本身不构成换档资格；reject/无效 tool action/重复 wake/no-op advance 不是换档边界；换档边界=既有推进结果的闭集（steer/answer/wake 导致的新 effect 是否属于边界须逐类裁明，禁实现者自由解释）；judge 若参与选档，judge 自身档位固定可审计（禁递归自选）；gate 四条（同 effect retry 同档同 digest/stale 保持/正常完成后可按策略重选/伪造边界被拒） |
| D-9 | **确认**：两落点立项排 I 系列 | (a) 前置 D-6+UA 收口，N/阈值版本化，双 Noul 仅判断证据；(b) 不破坏 tier 单调性/证据保留/输入信任边界；各自 Fake-provider gate+失败保守处理；不以「更便宜」为唯一通过标准 |
| D-A | **甲**：v13 唯一权威（否决「乙起步甲收敛」） | 用户既有决定高于调查报告建议；LoopX 可提供交互/投影/**建议**，其 should-run 等结果不能未经 PG 合同裁定直接变成执行授权；未内化能力标记 unsupported 并 fail-closed，不得以外部文件权威临时补洞；**E3 语义改写（车道二修正）**：「LoopX should-run → v13 admission 转发」改为「LoopX 建议，PG 独立重跑 admission/quota/claim/fence/授权合同」；LoopX lease/registry 只作适配输入，不授 operator 例外、不替代 PG claim；投影单向（PG→LoopX）、事务外、幂等、可由 events/fold 重建、文件编辑不回流 |
| D-A.1 | **确认**：受限新政策行方向 | 注册只建立可识别外部执行者，不自动获 operator 例外；身份由可信适配入口绑定（provider payload/工具参数自报一律拒）；政策版本入 request 快照防漂移；载体不可表达时走 R4 四问；身份合同是外部可写入口的前置门 |
| D-A.2 | **确认**：v13 fold → LoopX 文件投影（不用 postgresql_v0 同库共存） | 事务外、以事件水位/收据身份幂等、防倒退；投影失败不回滚/不改写 PG 事实；文件可重建且编辑不回流；不调 LoopX 会另建权威的写路径（todo/quota/settlement）；重复投影不得二次结算；gate 覆盖重复写/崩溃重放/乱序/删除/人工改写；本期不启用 LoopX 独立 authority store |
| D-A.3 | **否决**模式开关（甲下不适用） | 允许以部署/调用配置停止重复自主 tick（**liveness 开关**，非治理权威切换）；不建模式状态表/列；replan 确认/lease/claim/fence/准入/stop 仍 PG 执法；notify 可委托外部传输但控制结论出自 PG；同一部署不得同时存在 supervisor 与外部 driver 两个独立推进者；gate 对照自驱与外部 tick 的控制结果 |

## 二、收敛统计

13 条中 11 条两车道直接一致；D-4、D-8 经对抗后方向一致、守卫收紧合并。D-A 两车道一致裁甲（车道二确认「不必然阻塞近期接入，前提是近期目标定义为 PG 已支持子集」）。

## 三、残余父决（车道二明示必须回父，Oracle 不可自决）

**【已决 2026-10-03】父答：R-1=α、R-2=α。** 生效推论：R2 §7 重开条件由本次双车道限界复访正式关闭（台账随 S2 记「2026-10-03 双车道复访，父签认关闭」）；近期交付目标定为「交互/周期驱动的 PG 已支持子集，完整多日无人值守等 I1–I4 内化」。执行首刀解锁：UA 复审 + 三提交（D-1=A）→ S1 agentctl-observe。

### R-1（源自 D-4）：限界复访是否正式关闭 R2 §7 重开条件【已决：α】

两车道结论一致（三员可准入、S1/S2 可推进），分歧仅程序：车道一认为裁决内复访即关闭；车道二认为 R2 §7 触发是规范性条件，Oracle 不得自我豁免。**须父一句签认**：
- 选项 α：接受本次限界复访为正式关闭（台账记录「2026-10-03 双车道复访，父签认关闭」）；
- 选项 β：另立 spawn 档位复访收尾记录（一小段文书工作，S1 不受阻，S2 前完成）。

### R-2（源自 D-A）：近期交付目标的定义

甲裁决下近期可达的是「交互/周期驱动的 PG 已支持子集」（E1 外部契约+E2 RP-CE 承载+E3 单向投影）；完整多日无人值守（LoopX quota/wake/outcome_floor 语义生效）须等 I1–I4 内化。**须父确认**：
- 选项 α：接受「先 PG 子集、完整 unattended 后置」；
- 选项 β：要求立即完整 unattended——则须显式接受工期推迟（不能由 LoopX 文件临时补权威），或重开 D-A。

## 四、裁决生效与解锁表（更新版）

| 条件 | 解锁 |
|---|---|
| 本记录 + R-1/R-2 父决 | UA 复审与三提交（D-1=A 首刀） |
| UA 收口 | S1（agentctl-observe，含 D-2 勘误落件） |
| + R-1 关闭 | S2（agentctl-write 三员 + 复访记录 + 全链 gate） |
| D-6 里程碑 | judge 载荷合同；此后 D-7 judge 档、D-9 两落点（I 系列） |
| R-2 父决 | E1–E3 计划成文（按 D-A 甲 + E3 改写形状） |

## 五、程序备注

- 两车道均未运行任何 gate；本记录不构成真实 provider 或多日运行授权。
- 车道二对 D-1 的「同一原子交付」要求已并入 D-1 守卫；对 D-A 的 E3 改写已并入 D-A 守卫。
- 本记录随首里程碑按路径提交；设计稿 §7/§8、调查报告 §8.2/§8.4 的「已裁」标注同笔回填。
