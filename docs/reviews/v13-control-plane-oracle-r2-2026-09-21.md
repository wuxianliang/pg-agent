# v13 控制面 D1/D2/D3 终裁记录 R2(2026-09-21)

> 输入:R1(`v13-control-plane-oracle-r1-2026-09-21.md`)§0.2 三处分歧 + 三份补充卷宗
> (`prompt-exports/d1-harness-result-dossier.md` / `d2-spawn-kind-dossier.md` / `d3-triage-signals-dossier.md`,
> 三个探针独立收集,含 R1 未记录的新事实)。
> 通道:ask_oracle plan 模式双车道(gpt-5.6-sol@xhigh + grok-4.6@xhigh)R2 全量裁决 →
> 对抗收敛轮(残差质询) → **用户拍板**(D1/D2 各取 A 方案)。
> grok 车道另有独立第二采样(`prompt-exports/r2-grok-ruling.md`,agent_run 通道,与 Oracle 车道结论一致)。
> 完整原文:`prompt-exports/oracle-plan-2026-09-21-172211-*.md`(R2 全量)、
> `oracle-plan-2026-09-21-172845-*.md`(对抗轮)。
> 状态:**R2 终裁完成**。修订按 A15–A21 编号落位,修订后复核见 §9。

## 0. 最终裁决总表

| 题 | 终裁 | 谁定 |
|---|---|---|
| D1 harness result 分类 | **grok 包·四值权威**:`result_kind ∈ {progress,finish,wait,reject}` 是唯一持久化 settle/advance 分派键;LoopX 六值= `delivery_kind` 可选注释,路由永不读;repair/replan 走事件 | 双车道架构收敛 + 用户拍板细节包 |
| D2 spawn 档位 | **grok 线**:`tools` 行 `kind=sql` + `v13_tools_guard` 具名 VOLATILE 例外;父 advance 同事务批量建 N 子;**路径 B(worker 窗口 spawn)双车道一致否决**;不加多会话锁序 | 双车道对抗后仍分裂,gpt 少数意见存档(§7),**用户拍板 A** |
| D3 triage 信号集 | **收敛无需拍板**:首版最小集分 10a/10b 两级;explore 首版=同会话 llm+只读工具面(P2 升级 spawn);单一 `goal/override` 事件;module 数待 §11 步骤 3 | 双车道收敛(gpt 在 R-4 改判接受同会话 explore) |

三方共识底座(R1 共识 1–14 全部保留):零新表零新列;续跑=新 effect_id;审批两段;
`v_routes` 动作闭集不变;Jev 只产证据不授权动作;子 closeout 不持子锁写父事件。

## 1. D1 终裁:四值权威信封(A15)

### 1.1 分层词表(规范)

| 层 | 字段 | 词表 | 谁读 |
|---|---|---|---|
| harness 原始输出 | `candidate_kind` | 开放(harness 土话) | 仅合同校验器 |
| **settle 分派键(权威,持久化)** | `harness_result.result_kind` | **四值** `progress\|finish\|wait\|reject` | `v13_complete` / 下一格 parse+advance / v_routes 消费侧 |
| 对照注释 | `delivery_kind` | LoopX 六值,可空 | 审计/对照/人;**路由不读** |
| fold 信号 | `events.type` | `repair/required`、`replan/required`(开放词表,ch01) | 后续 triage / recover_idle / attention |

四值是相对复核缝 B 三值(finish/reject/wait)的**新增立法**(加 `progress`):无 progress 则
VALIDATED_PROGRESS 只能误用 wait(语义相反)。A15 正文须写明此理由。

### 1.2 语义表(规范)

| `result_kind` | advance 行为 | material spend(同 logical_turn_id ≤1 次) | 可伴随事件 |
|---|---|---|---|
| `progress` | 不终结,下一格 parse+advance | **是,除非同批存在 repair/required 或 replan/required**(真进展不附修复信号;防「progress+repair」双义) | 可带 repair/replan |
| `finish` | 走验收门;过则 closeout completed | 是 | 禁止 repair/replan |
| `wait` | 零新 harness/llm/tool effect;`wait_reason=approval` 恰建一个 human | 否 | 可带 repair/replan |
| `reject` | closeout failed | 否 | 禁止把 unknown 伪装成 reject |

- `wait_reason ∈ {approval|evidence|quota}` **normative**(进 pg_jsonschema;缺省非法)。
  approval 的 wake=human settle;evidence/quota 必带**机器可判定 wake condition**
  (事件类型/not_before/artifact 到达/子终态),缺失 → `v13_complete` 拒收(收编 R1:254)。
- `USER_ACTION` 不设独立 result_kind:并入 `wait+wait_reason=approval`,该 turn 若出现
  `delivery_kind=USER_ACTION_REQUIRED` 则**必须**同时满足 `result_kind=wait` 且
  `wait_reason=approval`,且审批 interaction_ref 必填,缺则拒收。
- `VALIDATED_COMPLETION`(delivery 对照)仍须过 session acceptance gates,harness 不得单方面 closeout。
- candidate→accepted 验证链保留:原始输出不得直接授权(设计 §6.1「版本化 SQL 策略独占动作授权」)。
- **wait 三层消歧(教程必修)**:`sessions.status='waiting'`(会话等外部)≠ advance 返回
  `'waiting'`(本格已建 effect)≠ `result_kind=wait`(本格零新 harness/llm/tool
  effect,`wait_reason=approval` 时恰建一个 human)。

### 1.3 repair/replan 消费与上限

异步 fold:repair/required → 下一格路由既有 `sql`(库内修复)或 `human`(超限);
replan/required → 路由既有 `llm`(重 triage/编排)或 `human`。上限=thresholds 行
(`harness.repair_count`/`harness.replan_count` 信号,按 ch04 既有信号命名风格)+
本会话事件计数 fold,带满 → human 或 reject。recover_idle 可把未消费 repair/replan
视为可恢复工作输入,不建修复状态机。

### 1.4 gate

- **G-ctx10-delivery**:乱填/置空 `delivery_kind`,同 `result_kind` 下 v_routes 输出与
  是否建 effect **逐字节相同**。
- **G-ctx10-wait-lexicon**:三层 wait 各自断言(wait 的 turn 零新 harness/llm/tool
  effect,wait_reason=approval 恰建一个 human;
  advance='waiting' 的 turn 恰有一个 ready|claimed)。
- **G-ctx10-wake**:缺 wake 的 evidence/quota wait 被 complete 拒。
- **G-ctx10-spend**:同 logical_turn_id material 次数=1;progress+repair 批零 spend;
  超限 repair 后零新 spawn、走 human/reject。

## 2. D2 终裁:kind=sql + guard 具名例外(A17)

### 2.1 目录与函数

- `tools` 新行:`spawn_subsession`,`kind='sql'`,`mutating=false`,
  `allowlist.write_targets ⊆ {sessions,events,latches,artifacts}`(目录声明,审计用)。
- 执行函数 `v13_spawn_subsession` 与 `v13_fork` **同一 primitive**(两列+forked 事件+
  validate-spawn+预算准入);服务端派生字段(parent/cutoff/fence/prefix identity/quota)
  模型不可提供(R1 共识 11)。
- 物理分界回归 ch06 §6.7 原文:「sql 档的全部效果就是数据库自身状态」——两档分界是
  **有无外部 IO**,不是 SELECT vs INSERT。教条改写:
  「sql 快路=库内、零外部 IO、零队列;默认只读;**具名写允许名单**内函数可写
  sessions/events/latches/artifacts 指针」。

### 2.2 guard 具名例外(DP1 #50 修订,与 A17 同发)

- `v13_tools_guard` 默认仍拒 VOLATILE;**具名核心函数闭集例外**:
  `v13_fork`、`v13_spawn_subsession`、ch10 装配函数(实现时核对真名)。
- 例外条件全满足才放行:`provolatile='v'`、签名 `(uuid,jsonb)→jsonb`、
  `SECURITY DEFINER`+固定 `search_path`+owner=控制角色+`REVOKE PUBLIC`+
  GRANT EXECUTE 只给控制角色(模型角色无 EXECUTE;在 advance 已持父 FOR
  UPDATE 的事务内执行。理由=**sessions 唯一写路径可执法性**:INVOKER 下执行
  角色须持 sessions INSERT,「该角色直接 INSERT 被拒」无法执法;DEFINER
  收权后执行角色零表权,直写即拒——修订复核裁决,取代早稿「不用 DEFINER
  避免提权」句)、
  `prosrc` 不含 dblink/pg_net/COPY PROGRAM 等 IO 通道。
- 扩员=guard 源码改+设计修订+部署 gate 同发;**禁止** `UPDATE tools` 扩员,
  禁止「有 write_targets 键即放行任意 VOLATILE」。
- 模型 SQL 与只读角色执法(ch06:121–123)不动:只约束模型生成的 SQL 文本。

### 2.3 调用路径(唯一路径 A;路径 B 否决)

```
llm/harness effect 内模型产 tool_call{name:spawn_subsession,args}
→ complete(succeeded, tool_call artifact)      -- 零 sessions 写
→ 下一格 parse 识别待分派目录工具
→ advance:父 FOR UPDATE(已持)内同事务调 v13_spawn_subsession
   reserved 准入 + validate-spawn + INSERT child(ren) + child forked
   + parent child-created + reservation 载荷
→ 禁止入队;禁止 worker 在 claim 窗口写控制面(路径 B 双车道一致否决:
   流式期间写控制面与 steer/cancel 窗口互撞,孤儿 child 风险)
```

多子扇出:**一个 orchestrator turn 的 N 个 tool_call 冻结后,下一格 advance 同事务
批量建 N 子**,一次聚合准入(Σ requested ≤ 剩余可分配,循环内用更新后的
subtree_reserved 复核;并发 sibling 防超售=根事务咨询锁
`pg_advisory_xact_lock(<spawn_budget 类号>, hashtext(root_session_id))`
(两参形式分 lock class,与解析相 recall 的 hash(查询×候选集) 咨询锁互不串扰;
ch01/ch13 sessions DDL 无 reserved 列,单语句 CAS 方案作废。仅 spawn 准入
路径持此锁,closeout/recover 不得取;不引入 root **行**锁序——咨询锁是锁图
中的命名节点,所有预算写路径按同一 root key 取锁,顺序一致无环)。
单活跃只挡并发 effect,不挡同事务 N 次库内 spawn。

### 2.4 回执与恢复

- 回执=同事务的 child 行+child `forked` 事件+parent `child-created` 事件+reservation
  载荷(parent/child/replay_kind/reservation/source tool_call id)。缺任一 → gate 红。
  库内动作的回执是事件+行(与 v13_append_event 同构),不是 claim/settle。
- `mutating=false`:该列语义=「外部副作用能否在 rollback 后仍在」;sql 档崩溃即回滚,
  unknown 路径不适用。恢复扫描不见 sql 行(G3 不适用)。
- 幂等:同 source tool_call id 重放返回同一 child(request hash 匹配);
  不匹配 → 拒。
- 锁序:**不新增** root→parent 多会话锁序(gpt 方案被否决的独立理由);
  spawn 只用已持有的父行锁;禁止持 child 锁再锁 parent(共识 7 仍在)。
  ch02 锁序注释加一句「spawn 只锁父」。

### 2.5 同发修订清单(漏改即部署红)

DP1 `#50`(guard 例外)/A1 与 I-file-4(「只读已冻结行」→「零 FS/git IO;库内写仅具名
名单」)/P4a `reason:'read_only_handler'` 更名(如 `in_db_handler`);ch05:85,131;
ch06:37-43,§6.7;ch10:284;ch14(spawn=fork primitive+sessions 唯一写路径);ch02 锁序注释;
设计 §6.8 交叉引用。**sessions 唯一写路径立法**:除 `v13_fork`/`v13_spawn_subsession`
(及批量子)外任何角色 INSERT sessions 被拒(harness fake 自插 → 红)。

### 2.6 gate

- **G-sql-write-closed**:具名闭集外 VOLATILE sql 工具 enable → 红;write_targets 缺键
  而 VOLATILE → 红;prosrc 含 IO 通道 → 红。
- **G-ctx1-spawn**:路径 A 持锁时长上限(沿用 G-ctx1 毫秒级口径);超限改函数/索引,
  不得改回队列「自愈」。
- **G-spawn-unique-writer**:非名单函数/角色 INSERT sessions → 拒。
- **G-spawn-fanout**:N tool_call 一格建 N 子;预算不足 → 全不建(fail-closed,
  零部分建);并发 sibling 压测无超售。

## 3. D3 终裁:triage 证据/动作分离(A20)

### 3.1 triage.v1 首版投影(声明字段闭集)

10a(不依赖树,可与 A15 同批):`task_content_hash`、`task_est_tokens`(中间带特征,
根上不作硬拆)、`user_intent_override`、`has_mutating_hint`、`policy_version`、
`explore_evidence_hash`(无探索则 null)。
10b(依赖 A17+A21):`ancestor_depth`、`n_nonterminal_children`、`remaining_turns`、
`quota_remaining`、`subtree_reserved`。
**10a 中树字段声明但值为 null → 规则 5–6 不点火(null ≠ 0)**。
Jev 首版输出仅 `Choice{direct,decompose,human}` + confidence,不输出 9 项 rubric。

### 3.2 优先级阶梯(规范,替代「最高优先」口头)

```
1 空 fold → reject
2 duty_cycle=0 → 不建工作
3 硬安全:depth≥max_spawn_depth 或剩余<min_child_max_turns → 禁 decompose
  (override=decompose 也不得裂变 → human/waiting;禁止静默 direct 假装已拆)
4 override=direct → direct(不经 Jev)
5 override=decompose 且过 3 → llm 编排(工具面含 spawn),不经 Jev
6 ancestor_depth≥1 且无 override → SQL 默认 direct
7 其余(根、无 override)→ Jev thresholds 映射;无/超时/失败 → fail-closed
```

override 事件:**单一 `goal/override`**,载荷 `intent ∈ {direct,decompose}` +
`schema_version`/`source_principal`(仅 user/operator;模型不得自写)+可选 `reason`;
同 type 按 seq 取最后一条。排序低于深度/预算硬安全。

### 3.3 explore_then_retry(策略,非路由结果)

- **首版=同会话 `llm` + 只读 explore 工具面**:不 spawn、不占 ancestor_depth/reserved;
  usage 正常记账。review 带(有答案、置信度居中)且根上未探索过 → 允许一次;
  已探索仍 review → human。
- **P2 升级=只读 explore child 走完整 spawn 准入**(depth+1,超深不豁免)。
- `explore_then_retry`/`orchestrate`/`decompose` **永不出现**在 `thresholds.action`
  (G-triage-action-closed);四分类词只作 decision context/策略标签。
- explore 证据回流=evidence artifact(+可选 explore/completed 事件);
  `explore_evidence_hash` 变 → request_hash 变 → 新 decision 行(不复用旧 verdict,
  也不强行改写 candidate_set_hash——探索证据不是召回结果)。

### 3.4 direct 条件与 fail-closed

- gpt 8 条件中 rubric 依赖项(work_unit atomic/acceptance simple/independent
  workstreams/deliverable 数等)**不进首版**;保留 SQL 可判定项。
- **无 Jev 证据时**:根+无 override → 不得静默 direct,走 human;
  depth≥1 → 默认 direct;override=direct 且硬门过 → direct。
- 超时/缺失:decision 不落行(ch05 既有);根→human,depth≥1→direct,零 child。
- review 带:走**版本化默认策略行**(设计:256–257 先例),种子=根 human/子 direct,
  改种子=插新 thresholds 版本,不改函数。永不默认 decompose。
- module 数:**首版不进**。§11 步骤 3(T0 recall+chunks 投影)后先加
  `candidate_source_count`(候选集去重 source 数,与 candidate_set_hash 同快照,
  纯 SQL 聚合已落行,禁新解析相 IO);版本化 module_key 存在后才加
  `candidate_module_count`;不用 manifest 装配数(时序倒置+选择偏差)。

### 3.5 gate

G-triage-action-closed(thresholds.action 仍属闭集)/G-triage-explore-depth
(超深零 explore child)/G-triage-evidence-hash(新证据必新 request_hash)/
G-triage-10a-null-tree(null 树字段不点火,根不得 SQL-direct)/
override 打穿预算 → 零 child+human/超时根零 decompose。

## 4. 交叉一致性(同尺三行)

| 尺 | 落点 |
|---|---|
| 动作闭集 | 四值不是 action;spawn=tools.kind='sql' 分派;triage 分类映射 llm/human/sql;**信封枚举不是动词,CASE 它的代码才是** |
| 谁在锁内写 sessions | 仅 advance 变更相(持父 FOR UPDATE)+ guard 具名闭集;worker/harness/子进程否 |
| 回执 | 库内动作=同事务事件+行;外部 IO=effect claim/settle |

建会话只有一个动词实现(v13_spawn_subsession);D1 不另造 repair 会话,D3 explore
不占深度=不是子会话——三题咬合。

## 5. A15–A21 分配总表

| 号 | 一句话 | 主要文件 |
|---|---|---|
| **A15** | 控制面信封族:四值 result_kind 权威+normative wait_reason/wake+delivery_kind 对照+repair/replan 事件+续跑新 effect_id+审批两段+handoff+三层 wait 消歧+G-ctx10 族 | 设计 §3.1/§6.8/§10/§12;ch05/ch07/ch12;ch01 事件;复核缝 B 收口 |
| **A16** | closeout 三终结事件+对账收据(spent/hashes/children/unconsumed/state_hash)与终态、预算终态同事务;前置 fail-closed;closeout 不再扣预算 | ch05 练习 1 升格;ch13;设计 §10 |
| **A17** | spawn_subsession=v13_fork primitive,kind=sql+guard 具名例外+批量扇出+mutating=false+不加锁序+sessions 唯一写路径;DP1/A1/P4a/ch05/ch06/ch10/ch02/ch14 同发改写 | DP1;ch02/05/06/10/14;设计 §6.8/§13;I-file-4 勘误;复核缝 C 收口 |
| **A18** | worker 第四务(控制订阅)+目录 interruptible(required/best_effort/unsupported)+核心不杀进程+mutating 中断→unknown+父 cancel 子树扇出 | ch08/ch11/ch12;G6 |
| **A19** | worktree=latch(name='worktree')+binding artifact+prepare/merge/release 走 FS effect;零列;子不继承;mutating 无 binding 拒 claim;**prefix identity 用版本化 latch 名单,worktree 默认排除** | ch07/ch08/ch13/ch14;设计 §5.1 |
| **A20** | triage 证据/动作分离:10a/10b 分级最小集+goal/override 事件+Jev Choice+同会话 explore(P2 spawn)+module 数后置+G-triage 族 | ch01/ch04/ch05/ch13;设计 §6.5/§6.8/§11/§12;thresholds 种子 |
| **A21** | 参数化 v_goal_tree(root)(STABLE SRF,非 VIEW 非物化)+子树预算递归聚合+recover_idle 扩「子齐父未验收」+repair/replan 可恢复工作输入 | ch13/ch05;设计 §10/§11 |

注册落位:A15–A21 全局编号沿用 A1–A14 惯例,登记进 `docs/designs/v13-errata-2026-09-21.md`
新增节;各受影响计划文档(DP1 等)的修订节引用对应 A 号。

## 6. 文档 bug 修复清单(与修订同发)

| # | 位置 | 改为 |
|---|---|---|
| B1 | 设计 §10 G-ctx6「跨 turn 成立」 | 「单 Plan 内单调;跨 turn 走 hysteresis/cooldown」 |
| B2/B3 | ch05:85,131 与 ch06:37-43「纯只读」 | 按 §2.1 教条改写(零外部 IO;默认只读;具名名单) |
| B4 | ch10:284 vs :35-49 | 284 改「同事务、零外部 IO;assemble ∈ 写允许名单,写本库 artifacts 指针」 |
| B5 | wait 三层同名 | ch01/ch05/§6.8 对照表消歧 |
| B6 | 复核缝 B/C 未决语 | B=A15 四值收口;C=A17 sql 收口 |
| B7 | R1 gpt 稿「路由 repair/accepted 六分类进路由」 | 以 R2 为准作废;文档不写入 |
| B8 | ch04:89 | 加一句「harness 结果与 triage 分类都不是第 7 个 action」 |
| B9 | DP1 #50/A1 | guard 具名例外;A1 禁 FS/git 不禁名单内库内写 |
| B10 | 「candidate-module 已在水位内」 | 删除;水位=candidate_set_hash,module 数待步骤 3 |
| B11 | v13_fork 无实现 | A17 与 ch14 练习 1 同一 PR(落地前 grep v13_fork) |
| B12 | ch10 装配函数真名 | 实现时核对,guard 名单用真名 |
| B13 | handler='pg-control' | 已否决,不得写入任何文档;R1 留作否决记录 |
| B14 | errata E4 字面 | 加指针「R2 收窄 A1 字面」;性质不变(禁 lock 内盘) |
| B15 | **新**:设计 §5.1/§5.6「所有 latch 参与 prefix identity」vs R1「worktree latch 排除」 | A19 立版本化 latch 名单,worktree 默认排除 |
| B16 | **新**:v_goal_tree 表述不一 | 统一「参数化 STABLE set-returning function」,非 VIEW 非物化 |
| B17 | R1 §0.2「10 项」计数 | 改为「确定性事实 12+判断证据 9」两组原文 |
| B18 | goal/direct、goal/decompose 双事件(R1:1376) | 以 R2 单一 `goal/override`(intent 字段)为准 |

## 7. 少数意见存档(gpt 车道,复访触发条件)

- **D2**:gpt 坚持 ledgered batch effect+handler='pg-control'+root→parent→effect 锁序,
  最强判据「kind='sql' 应能被结构 guard 证明绝无 VOLATILE,开例外即滑道」。
  复访触发:若 guard 具名闭集出现第三次扩员诉求,或 G-ctx1-spawn 持锁时长无法压回
  毫秒级(树大时预算聚合 O(n) 打穿)——届时 spawn 档位重开。
- **D1 R-1/R-2/R-3**:gpt 主张六值唯一持久化、USER_ACTION 独立值、VALIDATED_PROGRESS
  必扣。复访触发:若 delivery_kind 注释在实践中无人写(审计链退化),或
  progress+repair 不扣被用于免费进展刷 turn——届时升 material 判定为 delivery 事实。

## 8. 过程与证据

1. 三探针(engineer/opus max)独立收集 D1/D2/D3 卷宗 → `prompt-exports/d*-*.md`
   (各 ≤150 行,全部带路径行号;新事实:D1 四值亦新造+LoopX 六值内部分层;
   D2 DP1 #50 guard 拒 VOLATILE+ch10 第三处张力;D3 水位≠module 可得+最小集非零依赖)。
2. Oracle 双车道 R2 全量裁决(grok 车道首次调用遭 Cursor 侧模型元数据故障,
   重试后恢复;gpt 车道确认 Oracle 读不到 gitignored 路径,卷宗全文内嵌进消息)。
3. grok 第二采样(agent_run/pair 通道,xhigh)独立复核 → `r2-grok-ruling.md`,
   与 Oracle 车道结论一致(细节更细:双调用点、guard 例外条件、10a 空树纪律)。
4. 对抗收敛轮:G-1..G-3/K-1..K-3/R-1..R-6。grok 让步:砍路径 B;gpt 让步:承认
   trusted 引擎可写、batch effect 化、R-4 改判同会话 explore。D2 档位与 D1 信封
   细节仍两分 → 用户拍板均取 A。
5. D3 无需拍板(全收敛)。

## 9. 实施顺序(修订 agent 遵循;每步可独立验收)

1. 设计文档冻结:§3.1 尺子+§6.8 信封族+G-ctx6 修正+§10 gates(G-ctx10/G-sql-write/
   G-triage 族)+§11 控制面与承重件并行+§12 YAGNI(六值升格/rubric 9 项/module 数/
   看板物化/explore-spawn)。
2. errata 注册 A15–A21+B14/B15。
3. A16 closeout(ch05 练习 1 升格)。
4. A17 原子切片:DP1 #50/A1/P4a+ch02/05/06/10/14+tools 行+guard 例外。
5. A21 goal tree+recover_idle 谓词(与 A16 原子于「有子树的 turn」测试)。
6. A15 信封族落地文(ch07 schema+ch12 审批+ch01 事件登记)。
7. A18 interruptible+cancel 传导。
8. A19 worktree latch+binding。
9. A20a override 事件+SQL 短路+fail-closed(零 child 断言)。
10. A20b 树信号+Jev Choice(不得早于步骤 4)。
11. 修订完成后 Oracle 复核轮(是否引发新问题)——记录追加本文档 §10。

## 10. 修订后 Oracle 复核(2026-09-21,已完成)

- **复核轮**(双车道,原文 `prompt-exports/oracle-review-2026-09-21-181853-*.md`):
  gpt=修后放行(4 P0);grok=放行(9 P1,无 P0)。重叠 3 项(spawn schema 暴露 parent/
  根预算 CAS 无落点/interruptible 列);gpt 独有:ch02 锁序、ch12 claimed-cancel 掩埋
  unknown;grok 独有:G-ctx10-wait-lexicon 与审批两段矛盾、B15 漏落 ch14、A19/A21 细则漏落。
- **修复轮**:20 项合并清单全清(P0+P1+廉价 P2;两处主持者修法:根预算防超售=两参咨询锁
  `pg_advisory_xact_lock(<spawn_budget 类号>, hashtext(root))`;SECURITY INVOKER→DEFINER
  安全模式,理由=唯一写路径可执法——**此两条为复核轮对 R2 §2.2/§2.3 的修订性修正,
  已回写本文档正文**)。
- **确认轮**(原文 `prompt-exports/oracle-review-2026-09-21-183509-*.md`):全部 P0 ✓;
  残差 6+2 处(修复自身引入:R2 §2.3 CAS 旧句、咨询锁未分 class、ch07 盲读句无条件、
  ch06 DEFINER 调用链、ch04 review/explore 顺序、设计 §10 gate 登记、R2 §1.2/§1.4
  旧句)已按双车道一致修法清零,验证通过。
- **终判:放行。** 复核发现的全部 P0/P1 已修复并经确认轮验证;无遗留 P0/P1。
- B17 处置:R1 为存档记录不回改,「10 项」误计数以本记录 §3 与 B17 条目为准(superseded)。
- 未入库:本文档群(docs/ 设计+教程+errata+DP1+复核+R2)按仓库惯例随下一个相关里程碑
  按路径逐项提交。
