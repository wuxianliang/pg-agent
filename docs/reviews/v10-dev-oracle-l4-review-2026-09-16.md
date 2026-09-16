# v10-dev 实现规范 Oracle L4 审核链（轮 1 起）

- 对象：`docs/designs/v10-dev.md`（999 行草稿，2026-09-16 成稿）
- 基线：冻结 `docs/designs/v8-dev.md`（871 行）+ 轮 5 准出 `docs/designs/v10-raw.md`（468 行）
- Oracle chat：`new-chat-D11B11`（与 raw 轮 3–5 同链；chat mode）
- 冻结标准（对齐 v8-dev L4 先例）：**无 P0 无 P1 即达标；P2/nit 允许保留但须有明确阶段与验收承接**
- 撰写计划：`prompt-exports/oracle-plan-2026-09-16-112233-new-chat-d11b11-133d.md`（Oracle 注明：撰写计划不是冻结合同，不作为缺口豁免依据）
- 循环记忆：`prompt-exports/loop-orchestrate-v10-dev-l4-runs.md`

---

# 轮 1（2026-09-16，基线全镜头审核）

**总裁决：0 P0 / 9 P1 / 2 P2——未达冻结标准。**主要转换已完成（18 条不变量完整继承、execution/inspection 分离、preparation/PTL 收窄、emergent 生命周期、Feedback 分流、独立发布 receipt、分阶段验收均有实质内容）；阻塞点集中在**新增协议的输入域、授权映射、写入归属和异常出口未完全闭合**。不撤销 raw 轮 5 准出；不重开已裁定范围；19/20 方向保留、随本规范审核后冻结。

## P1 清单（九条，全部规范阶段必改）

| # | 落点 | 问题 | 修复方向 |
|---|---|---|---|
| D1-P1-1 | §1.2 L74–95、§3.2 L255–271、§3.4 L314–319、§5.2 L522–537 | canonical 存储表示与 provider wire 字节未分层：v8 §1.3 的 `$` 前缀键加倍转义/tagged integer 会改变工具 schema 语义（`$ref`→`$$ref`）；bytea 不能直接作 JCS 值；解码时点与最终冻结比较的字节未定义 | 分开定义合同 canonical descriptor / 不透明内容字节规范编码 / 最终 provider wire；边界转义、解码、provider 序列化唯一时点；wire 在 seal 前确定、host 不得改写；request_hash 覆盖关系明确；补 `$ref/$defs`、非 ASCII、二进制、大整数边界 vectors |
| D1-P1-2 | §2.4 L203–217、§3.3 L279–281、§4.4 L449–455、§5.3 L547–566、§5.4 L572–584 | "受权读取/发布"不可判定：catalog/artifact/trace/POML 预物化查询未映射到 v8 §2.1 闭合集 capability；artifact/persona/emergent 未入 slice.spec 资源集；publisher/operator 管理权限无受保护记录；emergent 消费授权检查对象不明；seal/dispatch 重验集合未定 | 增加操作 × capability/operator 权限 × subject × resource/slice-membership × 约束 × 线性化点矩阵；每类 source 明确授权定位材料、持久化位置、seal/dispatch 重验集；provenance 可信发布者/证明来源；可复用既有 capability 或显式新增 v10 管理权限协议 |
| D1-P1-3 | §2.1 L128–134、§2.3 L188–196、§6.1 L606–612 | generation 发布增量与 session 内容初始化增量被归"父命令增量"，但 v8 §4 只有流程义务、§3.1.2 无 create_session 命令——命令身份/幂等/拒绝结果未继承完成；session 初始化（persona 指针+model defaults+物化参数+建 session）防响应丢失重复创建无规范答案 | 两条路径各选：引用真实完整接口并冻结必要合同，或 v10 显式补充管理/初始化命令合同（身份域、payload 比较域、权限、锁序、成功/拒绝 receipt、CAS、提交前后 crash）；persona 指针变化与并发初始化线性化；同命令重放不得绑另一版本；修正"F-08 已闭合"自查 |
| D1-P1-4 | §2.2 L175–179、§3.2 L256/264–266、§3.4 L318、§7.3 L790/800 | latch 只有存储合同无触发判定合同：latch_key 声明者、触发谓词与 value 权威来源、同 key 多 proposal 冲突、未选中 section 是否触发、跨 generation 不一致、"本 turn 新触发"窗口均未定义——两实现可合规却冻结不同值 | 版本化 latch declaration + 有限确定触发规则；proposal 生成者/输入域/冲突码/选中与触发关系；本次 firing 与历史 firing 区分；marker 抑制作用窗口；补首次触发/回滚/重复提案/跨 generation/同 turn 后继装配测试 |
| D1-P1-5 | §3.3 L294–299、§3.4 L311、§3.7 L344–348、§7.3 L798–799 | spill 保留与重放已定义，但 spill 变换的规范输出未定义：原 section 替换成什么、SpillReference 字段/字节格式、是否含物理 ID、placeholder/skip/spill 三种表示选择与 token 计量、首版是否承诺读取 | 冻结首版 spill 最小表示合同（输出 section 字节/引用、身份、token 计量、可用条件、trace）；若首版只支持"持久保存原文+确定 placeholder/skip"则直接命名限定；不增加自动 preparation/模型调用/未登记 retrieval；fixture 4 同时断言"新决策实际发出字节"与"冻结重放" |
| D1-P1-6 | §5.3 L553–563、§6.4 L689–700、§7.3 L807–808 | 发布冲突优先级与验收预期不一致：§6.4 要求 ARTIFACT_IDENTITY_CONFLICT 先于 RENDER_IDENTITY_CONFLICT，但 §5.3 与 7-P2a 对"同 render identity 任一产物不同"统一返回 render 冲突——可构造同时命中两码的合法输入，两处答案不同 | 唯一分类裁定（按包类型先判 render aggregate，或保留 artifact 优先并拆 fixture）；区分同 artifact identity 异内容 / 新 artifact identities 同 render identity 异产物 / 同 render 同产物 provenance 不一致；正文、receipt 表、两提交序用例同一结果码 |
| D1-P1-7 | §2.1 L120–150、§2.2 L165、§5.2 L522–530、§6.4 L667–676 | 多个主键允许无界文本/结构（artifact_identity 规范结构、presentation、publication ID 无字节上界）——PG btree 单索引项受页面限制，高熵合法输入只能得到约束异常而非规定接受/稳定拒绝；v8 §3.1.2 J08 已解决同类问题（固定长度 digest 键+完整 canonical 留存列+精确比较） | 全部可索引 identity 统一选：UTF-8 字节上界，或 digest 键+完整 identity 留存+碰撞检查；复合键总长约束、超限稳定结果、检查层级；补长文本/高熵/同摘要异内容测试 |
| D1-P1-8 | §4.2 L398–412、§6.2 L621–638、§7.3 L815 | Feedback 持久绑定冲突有拒绝码但无收束路径：sidecar/sample/profile 均不可变、无合法 operator 修复入口、相同命令只能重放拒绝、新 completion ID 仍遇同一损坏；"operator 修复"不能替代状态出口 | 区分调用输入不合法与持久绑定不变量已损坏；后者明确进入既有 INFRA fail-closed/drain（v8 受控处理）+ 受控入口 + 同事务 + 父层 failure cause 保留；禁止 UPDATE 不可变 sample/profile 或补采旧成功；补拒绝后新命令/恢复扫描/已有终态/响应丢失用例 |
| D1-P1-9 | §3.2 L249–251、§6.5 L705–712、§7.3 L794/800/817、§7.4 L833 | 验收脚本时序不可达：A1 要求"capture 后 grant/slice 撤销 × seal 两序"，但本文协议先取授权锁再捕获、capture 至 seal 同事务——撤销事务无法抢先提交；5-P0/3b 省略使操作合法的前置（完成/工具收束、dispatch/已知失败） | A1 改为：撤销先于授权锁/capture 提交→装配拒绝；装配先持锁 seal 提交→撤销随后提交→下一 dispatch 按当前授权拒绝；CAS 授权实现另列调度点；补齐 5-P0/3b 合法前置；fixture 时序由协议推导 |

## P2 清单

| # | 落点 | 问题 | 承接 |
|---|---|---|---|
| D1-P2-1 | §2.2 L169、§3.4 L317–319 | `provider_markerable` 未接入 marker 资格谓词（字段定义了但算法未消费） | **建议本轮顺手修**：补统一 eligibility 谓词 + false 排除行为 + skipped reason + 仅切换该标志的 vector；最迟 P0 marker 实现与 fixture 8 冻结前 |
| D1-P2-2 | §5.2 L530/533/539、§1.3 L99–101 | tokenizer 测量 metadata 与 render identity 升级关系不清（只升级测量 tokenizer 不改字节时，是否必须改 render profile） | P2 渲染发布 schema/fixture 7-P2 定稿前；二选一：测量 profile 入 render identity，或内容身份与版本化测量记录分层 |

## 五镜头核验结论（摘要）

- **协议闭合性**：execution/seal 原子、inspection 零写集、needs_preparation 主体成立；对象 receipt 独立域成立但未全闭合；锁序主路径方向正确（管理/初始化父协议未定义完不能证明全部入口无反向边）；Feedback 正常路径成立、异常路径未闭合（P1-8）；streaming final 先到处理确认为正确继承 v8 §1.2 屏障 (b)/(d)。
- **v8 对账**：18 条含括注与 v8-dev §0 L7–24 一致；19/20 方向兼容且未冒充已冻结；八位锁序/初始 seal/manifest/授权双门/generation/capability 矩阵引用准确；管理/初始化命令不能由流程存在推导 receipt 协议存在（P1-3）。
- **raw 一致性**：范围零回退（preparation/PTL/emergent/churn/v9 全部维持）；附录 A.1 抽查十条定位无虚构。
- **DoD A–E**：B/C(18条)/D 通过；A/E 未整体通过（授权映射、父命令、latch/spill、身份长度、异常出口缺口）；A.4 M1–M7 与正文大体对应但"通过"应降为"结构检查完成、协议自查待关闭本轮发现"。
- **内部一致性**：无悬空引用、无双 schema 真相；receipt 优先级须按 P1-6 收口；R5-P2-1 维持"文档处置关闭"。

## 下一轮修订清单（优先级序）

1. P1-2 capability/资源/管理权限映射（§2.4/§5.4）
2. P1-1 canonical/wire/编码分层（§1.2/§3.2/§3.4/§5.2）
3. P1-3 父命令/初始化协议（§6.1 及命令节）
4. P1-4 latch 声明/触发/窗口（§2.2/§3.2/§3.4）
5. P1-5 spill 表示合同（§3.3–3.7）
6. P1-6 冲突优先级统一（§5.3/§6.4/fixture 7）
7. P1-7 索引身份域收口（§2/§5/§6）
8. P1-8 绑定损坏 INFRA 出口（§4.2/§6.2）
9. P1-9 A1 时序修正与前置补齐（§7.3–7.4）

九项均规范阶段必改；可留实现期：DDL/索引/函数、三 spike、POML 隔离实测、golden/并发/kill 测试代码、v8 runtime 接入、D1-P2-2。下轮以九条逐项核验为主，同时防回归（原子 seal、inspection 零写集、Feedback 分流、v8 双实时授权门不得削弱）。

---

# 轮 2（2026-09-16，轮 1 修订版复审）

**总裁决：0 P0 / 4 P1 / 2 P2——尚未达标，但修订有效（9 P1→4 P1）。**轮 1 九条中六条关闭（P1-1/4/5/6/9 + P2-1）、三条部分关闭（P1-2/3/7/8 的残留即本轮 D2-P1-1/2/3/4）。不撤 raw 准出、不重开已裁定范围；D1-P2-2 维持 P2 承接可接受、不阻塞冻结标准。

## P1 清单（四条，规范阶段必改）

| # | 关联 | 落点 | 问题 | 修复方向 |
|---|---|---|---|---|
| D2-P1-1 | D1-P1-2 残留 | §2.4 L212–236、§5.4、§2.1、§6.1 | "已登记 query_id"无权威解析合同：query_id→不可变查询定义/generation 成员/参数 schema/可访问 relation 集/capability 入口的映射未定；"受保护 DB 预物化证明"出口身份与覆盖域未定——实现者可各自选择（host allowlist/硬编码/新表/调用方 SQL 当已登记） | query_id 绑定已发布不可变 generation 成员/具名 SQL handler 或显式新增登记对象（唯一权威源）；冻结映射字段（实现摘要/参数 schema/relation 依赖/输出约束）；具名 capability 入口 + 拒绝结果（未知 query/版本不符/参数越界/实际依赖超声明）；DB 物化证明三选一（只读返回零写集/持久化登记/首版只留可信 builder 签名路径删替代路径）；A3 补换实现/声明不符负向用例 |
| D2-P1-2 | D1-P1-3 残留+修订引入 | §6.1 L627–647、§6.5 | active 指针 CAS 未闭合：指针作用域（workspace/全局）、权威持久对象、首次空建行、revision 写入口全集未定义；新指针锁子序未应用到既有强制下线路径——activate（持 pointer 锁→等 G 锁）× 强制下线（持 G 锁→等 pointer 锁）可构锁环；v8 八位主锁序不含 generation 位内子序 | 指针/revision 唯一持久化定义与作用域；列全写入口（activate/下线回退置空/其他受权切换）；统一子序应用到所有路径（如 sessions→管理许可→active-pointer→generation 行全序→后续主锁，一份答案）；下线保留 v8 全 session 预锁+锁内重扫+整体重试；补 activate×下线/activate×activate/首次空指针用例 |
| D2-P1-3 | D1-P1-7 残留+修订引入 | §2.1 L125–128、§6.4 L719–726、7-K L863 | 1 MiB 上限未覆盖派生键：binding 界内但 receipt 键（W, publication_id, key_kind, key_value）超限时——保存原结果违反上限、保存 IDENTITY_TOO_LARGE 仍用同一超限键、ingress 例外不覆盖派生 receipt 超限——合法命令身份无稳定 receipt 出口 | 推荐：binding 保存完整 publication identity + 固定长度受保护定位键；receipt 身份 = 定位键+typed request key，原 identity 经 binding 保留比对；或叶级 publication ID 更小上限证明派生键有空间；定位键碰撞与内容碰撞各自稳定记录路径；7-K 补复合边界/同 ID 四种结果/丢响应用例 |
| D2-P1-4 | D1-P1-8 残留 | §4.2 L425–431、§6.2 L668–675、9-P0e1–e4 | INFRA 判定时点不唯一：首次成功 decision_only completion + 持久 sidecar 损坏时，"先聚合再 INFRA"（step SUCCEEDED + session failed）与"聚合前定 INFRA"（step drain failed_terminal/INFRA + session failed）两种顺序都满足局部句子——父层状态函数非单值 | 明确顺序：envelope/证据/成功语义校验→**正常成功聚合前**检查 v10 持久绑定→损坏时保留合法 effect 结算事实选 INFRA 收束（不做普通 success 聚合再改写）；"既存终态/cause 保留"指进入本次处理前已持久化的；closing 与含 tools plan 非关闭 decision 分别写三层精确结果（非关闭说明已接受 plan 留存与作废、不开放 tools seal）；e1/e4 断言 effect/step/session 三层状态/code/事件/receipt |

## P2 清单

- **D1-P2-2 维持**（P2 渲染发布 schema/fixture 7-P2 定稿前二选一，不阻塞冻结标准）。
- **D2-P2-1 新增**（§6.1/§7.2/5-M/5-I）：initialize_context_session 已是基础写入口但完整验收只列 P1——P0 应补基础组（一次创建/同 ID 丢响应/异 ID 同 S 冲突/内容绑定与 receipt 原子性），P1 扩展真实 persona 发布/指针竞争/覆盖/版本变化。承接：P0 验收表冻结前，建议同批修文。

## 轮 1 处置裁决 + 防回归

关闭：D1-P1-1（三层分离+vectors 1d/1e，provider_wire_json@v1 独立规则不改 v8 JCS）、D1-P1-4（latch 声明/触发/冲突/窗口唯一答案）、D1-P1-5（spill_archive@v1 限定+SpillReference 仅审计）、D1-P1-6（先验包完整性再 ARTIFACT→RENDER，三类分开）、D1-P1-9（行锁/CAS 分开+前置补齐）、D1-P2-1（eligibility+8c）。部分关闭：D1-P1-2/3/7/8（残留即上表）。防回归全部通过：18 条含括注未变、19/20 不变量候选适用域正确、canonical 不反向改 v8、授权枚举未扩、preparation/PTL/emergent/churn/v9 零回退、prompt 门与 dispatch 门独立、A.1 抽查九条无虚构、A.4 状态表述准确。

## 下一轮必改清单（优先级序）

1. D2-P1-2 generation 指针与锁图；2. D2-P1-1 查询与证明权威入口；3. D2-P1-4 INFRA 与成功聚合顺序；4. D2-P1-3 派生 identity 边界。D2-P2-1 建议 P0 验收表冻结前同批修文。可下放：DDL/索引/函数/测试代码、三 spike、POML 隔离、v8 runtime 接入、D1-P2-2。防回归清单同轮 1。

> **轮 2 计数勘误（轮 3 补记）**：轮 2 开头摘要"九条中六条关闭、三条部分关闭"为笔误。实际：**五条 P1 关闭**（D1-P1-1/4/5/6/9）+ **四条 P1 部分关闭**（D1-P1-2/3/7/8）+ D1-P2-1 关闭。四条 P1 总裁决不变。

---

# 轮 3（2026-09-16，轮 2 修订版复审）

**总裁决：0 P0 / 2 P1——尚未达标（4→2）。**轮 2 四条中三条关闭（D2-P1-1/2/3）+ D2-P2-1 关闭；D2-P1-4 维持未关闭；新增 D3-P1-1。跨会话一致性专项：查询登记/locator/锁序三链均同一答案；INFRA 链是正文与 fixture **共同**缺时序限定（非 A/B 矛盾）。关键校正：实现侧报告所称"进入本次处理前已持久化"限定与"聚合前核验"措辞**未出现在正文**（L437 是"正常增量前"=Feedback context 增量，L685 无限定语）——不按报告解释替正文关闭。

## P1 清单（两条）

| # | 落点 | 问题 | 必改方向 |
|---|---|---|---|
| D2-P1-4（维持） | §4.1 L397、§4.2 L435–441、§6.2 L683–686、9-P0e1–e4 L889–892 | 首次成功 closing decision completion + 可信 sidecar 损坏仍可两读：普通成功聚合后处理损坏（step 已 succeeded 保留 + session failed/INFRA）vs 聚合前定 INFRA（step drain failed_terminal + session failed/INFRA）——同事务消除中间态可见性但未消除最终提交差异；e1/e4 未区分 closing/非关闭两支三层状态 | §6.2 写唯一顺序并由 §4.2 回指：① v8 envelope/证据/成功语义校验 ② **调用普通 step/session 成功聚合之前**核验持久绑定 ③ 损坏时接受合法 effect 结算事实、直接 INFRA 收束、不得先跑普通 success 聚合 ④ "既存终态/cause"限定为**本次处理进入前已持久化**（不含本事务暂写成功态）⑤ 分别冻结 closing decision（effect succeeded + 非终态 step 按 INFRA 收束 + session failed + 不再正常关闭/finish）与非关闭 decision（真实 result/plan 保留、计划作废、不开放 tools seal）⑥ e1/e4 补三层状态/code/事件/turn reducer/父 receipt 精确断言 |
| D3-P1-1（新增） | §6.1 L636/646/653/656–658、§6.4 L712–727、§7.3 L867 | revoke_active 是 (W, publication_id) 身份的 O 命令 + 单事务多 session drain，但 v8 §3.1.2 统一内部子操作审计要求 parent_session_id/parent_command_id/parent_receipt_ref 取自父命令 envelope 且幂等域 = (parent_session_id, parent_command_id, internal_op_ordinal)——O envelope 无唯一"父命令所属 session"，正文未定义各 session 内部审计绑哪个父命令、O identity 与 session command identity 区分、parent_receipt_ref 指向、ordinal 分配、O 重放与审计幂等关联；把 publication_id 填入 parent_command_id / 各目标 S 填入 parent_session_id 不算原样继承 | 建议保持 v8 session 审计域：① 外层 O 命令管管理身份/指针/总结果 ② 每个受影响 session 定义**同事务受控父命令/receipt 身份**（授权、身份派生、请求比较域、与外层 O 关联）③ v8 内部子操作继续绑定该 session 域父 receipt、按原五类顺序与 ordinal 规则 ④ 外层 O result 引用各 session 结果；提交前全回滚、提交后重放不再次 drain/追加审计 ⑤ 若选跨域审计适配须显式定义版本与字段语义。验收补：一个 generation 关联两 session（一方 ready effect/一方 pending unknown 或 compact lock）、逐 session 审计归属与 ordinal 重放、提交前 crash/提交后丢响应/同 O ID 重放、不同 W 同名 ID 不串读 |

## nit

- D3-nit-1：附录 A.4（L1061、L1072–1078）未同步本轮处置集合——开头仍是"逐项补 D1-P1-1..9"，M4 未反映 revoke_active、M1/M5 未登记 query registry 与 locator 例外；更新为 D2 四项+初始化分期承接索引，注明 D2-P1-4 待关闭、登记 D3-P1-1，保持"结构检查完成、协议待 L4"口径。
- D3-nit-2：轮 2 摘要计数笔误——已在上文补勘误（五关闭+四部分，非"六关闭三部分"）。

## 五镜头与防回归（摘要）

原子初始 seal（§0.3 L52、§3.5 L353–357）、inspection 零写集（§3.6 L363–369）、Feedback 正常分流（§4.1 L394–414）、needs_preparation（§6.3 L693–708）全部保持；18 条含括注一致；19/20 未冒称冻结；query 登记/管理许可明确标 v10 新增未扩 v8 闭合集；raw 范围零回退；ARTIFACT→RENDER 序一致（§5.3 L589–595、§6.4 L745–754、7-P2a L877）；locator 81 字节为键载荷非索引元组（正文无混淆）。DoD：B/D 通过，A/C/E 未整体通过（余两接合）。

## 下一轮必改清单

1. **D2-P1-4**（§4.2/§6.2/9-P0e1/e4）：INFRA 唯一聚合顺序 + closing/非关闭两支精确结果。
2. **D3-P1-1**（§6.1 revoke_active/§6.4/§6.5/5-M）：O 父命令到各 session 内部审计/receipt 的合法接合 + 多 session 下线 crash/replay 验收。
同批：A.4 同步（D3-nit-1）。可留：D1-P2-2（P2 承接不变）、DDL/spike/隔离验证/runtime 接入。

---

# 轮 4（2026-09-16，本次续跑 R1 父级独立 L4）

- Orchestrate：`6C647A3D-2927-4491-BFA5-F63DD1F21AD7`，Completed，无正文修改。
- 父级 Oracle：`new-chat-38B9E6`，**mode=review**，成功返回裁决；git artifact `2026-09-16/1522` 是未跟踪全文，不代表本轮新增。
- 被审稿：1081 行，SHA-256 `9ab33926a67d4fee507e3ff66c1ad03aee55862be833fab0560dd2830357c4b5`（父级 python3 只读复算，exit 0）。v8/raw 哈希与页首冻结值一致。
- 上下文：v10/raw 全文、历史审核；v8 关键合同切片 L1–81、147–169、201–386、435–465、569–604、731–752、786–825。不宣称 v8 全文逐行复核。ignored 的 loop memory/计划不能加入 selection，父级已将完整冻结判据与 DoD A–E 直接提供；不降为 L3。
- 执行者的两次 review 请求因 1,048,576 字符上限失败，随后其 chat 模式判断 0/0/1 不作为最终裁决；父级独立结果优先。

**总裁决：0 P0 / 2 P1 / 1 P2 / 1 nit，未达标。**D3-P1-1 审计接合关闭；D2-P1-4 的控制态顺序已修正，但事件断言仍错；新增 generation 回退生命周期缺口。

| ID | 等级/处置 | 正文证据、可达反例与下一步 |
|---|---|---|
| D2-P1-4（轮4残留） | P1，未关 | §4.2 L437、§6.2 L684–687 已明确普通成功聚合前核验与进入处理前已持久终态；但 L686/9-P0e1 L891 的总 `turn/end+0` 违反冻结 v8 §1.2 L71 唯一 reducer。当前turn已开启、无sticky cancel/unknown/pending、唯一LLM成功但sidecar损坏：effect succeeded、step/session INFRA失败后应产生 `turn/end {interrupted:true,reason:"failed"}`。不得把“不走正常成功关闭”扩大为“不产生失败end”。修正 closing/非closing 的唯一 reducer、事件槽位与e1/e4 crash/replay；无既有end且无阻塞时失败end+1、正常成功end0；保留真实effect成功、无Feedback/finish/completed。 |
| D4-P1-2（新） | P1，未关 | §6.1 允许pointer回指retired且不改其状态，但revoke_active只接收expected_state=active并active→failed。g0 retired→撤销g1回指g0→g0产生新工作→发现g0致命缺陷，所有既定action都不能撤销/drain。v8 §4 L733–745未提供retired→failed。应在不改冻结v8状态边前提下闭合，Oracle建议显式置空后复用旧不可变implementation stage新generation→ready/activate恢复服务；若要增加状态边必须用户裁定。补完整恢复代再次故障、未dispatch/in-flight/crash/replay向量。 |
| D3-P1-1 | 关闭 | §6.1 L657、§6.4/§6.5、5-Md已定义O与session父身份隔离、授权/请求比较、父receipt、ordinal/event_key与两序；此关闭不代表generation生命周期整体通过。 |
| D1-P2-2 | P2保留 | tokenizer测量与render identity分层，P2发布schema/fixture7-P2定稿前二选一；同内容不同测量版本向量，未定/不通过阻止相关P2发布。 |
| D4-nit-1 | nit | 1a写“同逻辑键”却§3.3拒绝重复规范键；P0 fixture1 golden定稿前改互异且跨执行固定的规范键，同scope/priority；重复键另作负向。 |

五镜头：协议未通过；v8继承部分通过但reducer冲突；raw范围通过；DoD A/C未通过、B/D通过、E延期承接充分但未运行；内部/fixture未整体通过。D3-nit-1 A.4同步及D3-nit-2历史计数勘误已处理。

父级已read_file抽查v10 §6.2、5-Md/e1/e4及v8内部审计；file_search命中v8 reducer L71，并读v8 §4完整状态/下线合同。**下一轮仅修INFRA事件收束**；后续另轮解决generation恢复入口。不准no-op/成功停止；本回合P0+P1未降，连续停滞计数1。规范L4不代表fixture、spike或runtime通过。

## 轮 4 后执行记录：R2 未落文，循环 stalled（2026-09-16）

- fresh Orchestrate R2：`519F5C14-7F4C-43A5-AE42-045BDA751429`；目标仅修 D2-P1-4 的失败 turn/end、9-P0e1/e4。
- 执行状态 **Failed / agent_error**。原始错误：`Codex ran out of room in the model's context window. Start a new thread or clear earlier history before retrying.`
- 父级读取执行日志：执行者在只读获取基线/正文与等待探针阶段耗尽，未见 apply_edits；两次 shell JSON 输出包含整份文档，增加了上下文负担。不能把只读探针替换稿当实际落文。
- R2 只读探针 `B08CDE6C-EE11-4C34-A8B8-250FA6FAE061` 已 Completed，建议未应用、未经新 L4；不是准出依据。父级未替代执行者修改规范。
- 父级 `python3` 只读指纹断言（exit 0）确认 v10 仍1081行/SHA256 `9ab33926a67d4fee507e3ff66c1ad03aee55862be833fab0560dd2830357c4b5`；v8/raw亦与冻结hash一致。`UNCHANGED=True` 三项、`PASS: reviewed document and frozen inputs unchanged; prior L4 verdict remains applicable. No runtime tests executed.`
- 因被审正文与冻结输入未变，**沿用父级轮4 L4判决 0 P0 / 2 P1 / 1 P2 / 1 nit**；没有伪称新的Oracle复审或运行测试。R1计数不降、R2失败且零改动，连续无可测进展2，触发已冻结刹车。
- **终态 stalled，不是success/no-op。**本次使用2/5新Orchestrate attempts，提前停止；不为同一失败回合换会话绕过停滞刹车。没有规范改动或回滚，只有父级审核/记忆追加及必要git artifacts。
- 后续需用户启动新续跑：先以窄片段修 D2-P1-4 并父级 L4，再处理 D4-P1-2；避免把完整文档作为转义JSON重复灌入执行上下文。D1-P2-2和D4-nit-1仍按既定阶段承接。

---

# 轮 5（2026-09-16，用户授权续跑 S1 父级 L4）

- Orchestrate `CAF29851-04B4-448C-B886-E6E0B4F337AA` Completed；本轮仅修v10-dev的INFRA事件收束，1081→1086行。
- 父级Oracle `new-chat-38B9E6`，mode=review，artifact `2026-09-16/1608`；父级read_file核§6.2/e1/e4，并用python3复算当前SHA256 `13f57721b5f5b4096d17d1374e0b4be8c991d7f823f5e00d592fc9f6e4ca8077`，exit0；v8/raw冻结hash不变。
- **独立裁决：0 P0 / 1 P1 / 1 P2 / 1 nit。D2-P1-4关闭，D3-P1-1维持关闭；D4-P1-2未关，不能冻结。**

D2-P1-4关闭依据：§6.2 L686–692保留成功聚合前核验、真实effect succeeded、step/session INFRA、进入前已持久cause；两分支共享原reducer优先级(4)，plan作废；无已有end/unknown/pending/cancel/续行工作时failed interrupted end+1、正常成功end0，其余回到原三段与槽位/repair规则，不作无条件总end断言。9-P0e1 L896与e4 L899明确合法前置、三层状态、canonical槽位、crash全回滚及原accepted receipt/context_failure重放零end增量。上一轮反例已排除。

D4-P1-2仍在：retired可直接回指为服务目标但无retired→failed撤销入口。Oracle确认**合法dev方向**为“显式置空→复用旧不可变implementations stage新generation identity→新包/readiness→activate”；v8 §4允许置空与复用实现，无需新增状态边。下一轮必须同步§6.1目标域/payload/guard与5-Ma等，禁止stage旧retired identity充当复活；新成员/v10引用及readiness绑定新包；补恢复代产生工作后再次下线的未dispatch/in-flight、CAS/revision、逐sessionreceipt/audit、crash/replay向量。不得改retired既有工作规则。该方向只是指导，尚未关项。

五镜头：协议/A仍被D4阻塞；C继承防回归通过所核条款，B raw映射/D范围保持，E延期承接充分；内部fixture已修e1/e4，仍待D4与1a。未发现新增P0/P1，原子seal、retry、双门、Feedback排除面等无本轮回归。D1-P2-2继续P2发布schema/7-P2前二选一及测量向量、不通过不发布；D4-nit-1继续P0 fixture1 golden前澄清互异规范键与重复键负向。

验证覆盖同轮4：v10/raw全文、v8关键合同切片；不是v8全文逐行认证，更非runtime验收。执行者局部静态断言/git diff --check exit0；全仓hash审计exit1发现并行5个v8代码文件改变（cancel/test_closure.py、effect/v8_effect.sql、events/canonicalizer.py、retry/test_takeover.py、retry/v8_retry.sql），未归因本轮亦未回退。不声称全仓仅目标文件变化。S1进展2→1，停滞归零。

---

# 轮 6（2026-09-16，S2 父级独立 L4 终裁）

**总裁决：0 P0 / 0 P1 / 1 P2 / 1 nit——达到本链规范冻结标准，Loop 终态 success。**D4-P1-2关闭；D2-P1-4、D3-P1-1维持关闭。按冻结合同立即停止，不为非阻断项扩轮。

## 交付与执行证据

- fresh Orchestrate S2：`85C62A53-A2B8-4069-B311-FB45234F78CB`。编辑已落文，静态检查/报告阶段发生 `Failed/agent_error`：`Codex ran out of room in the model's context window. Start a new thread or clear earlier history before retrying.` 不把执行状态当作正文通过/失败依据。
- 父级已get_log确认写入、read_file核§6.1及5-Me–Mi，并用执行者本地before副本重新做限定差异、旧错误表述消除、五个fixture唯一性和行数断言；**exit0**。差异只在旧L644–660、779、873、877、1068、1082相关条款及其展开；最大单行字符870→899，未以大规模压行替代协议。
- v10-dev：**1086→1098行**，SHA-256 **`1bfe744c1c90358813dbeefb66b7e85e0a0e70933c3a3fa0de0f6d41f895a445`**；父级实际python3复算exit0。v8-dev/raw哈希与冻结值相同。
- 父级Oracle：`new-chat-38B9E6`，mode=review，artifact `2026-09-16/1637`（untracked全文快照，不是新增1098行）。以当前正文独立裁定，不依赖失败执行者或探针摘要；关项所需合同不需补片。
- 验证等级为**L4**，read_file/hash/局部静态断言为辅助，不是fixture/runtime执行。上下文含v10/raw全文与冻结v8相关切片；不声称v8 871行全文逐行认证。并行代码改动不纳入本审、不回退。

## D4-P1-2 关闭依据

1. §6.1非NULL指针仅同W已发布active代；revoke_active显式NULL-only，目标必须当前指针，原retired直接恢复服务反例不再可构造。
2. 恢复必须新generation identity、新成员/新代v10归属/完整包digest及重新绑定的readiness，仅复用同键同digest全局不可变implementations；不新增retired→active/failed，恢复代仍building→active→failed，能再次下线。
3. stage仅首次建空行，不重置已有revision；activate/revoke完整指针+revision CAS，5-Me/Mf的r→r+1→r+2→r+3→r+4轨迹唯一。
4. 再次下线未dispatch effect/attempt同事务取消，step/session仅原三合取满足才失败；in-flight保留pending走原completion/repair；retired旧工作不因新禁令受限。
5. §6.5全session预锁、pointer→generation、READ COMMITTED重扫/整体重试不变；5-Mg保留O/逐session父receipt/audit/drain/指针原子性及各action crash/replay。
6. 5-Mh拒非NULL replacement、旧retired identity复活、错包归属/旧证明；5-Mi历史accepted receipt在当前管理授权后优先新guard，原结果重放零写，不把历史成功当当前许可。

该方案选择v8 §4允许的显式置空及新代复用发布分支，不改冻结状态边或retired既有工作规则；不等于实现/运行通过v8全部回退分支。

## 五镜头/DoD终裁与防回归

协议、所核v8继承、raw范围、DoD A–E、主协议与fixture一致性均达到本链规范冻结门；保留1a措辞nit。原子seal、retry冻结、双实时授权门、canonical/ABI/event_key、Feedback排除面、query登记、81字节receipt键例外、ARTIFACT→RENDER顺序均未发现新增P0/P1。D2-P1-4原reducer/事件槽位及D3-P1-1逐session父审计域保持闭合。A.4/M4已有S2登记；正文原“待父级L4”属被审时点，不在终裁后改正文指纹，最终效力以本归档为准。

## 保留项与硬验收门

| 项目 | 阶段 | 必需产物/失败处置 |
|---|---|---|
| D1-P2-2（P2）测量tokenizer与render identity | P2渲染发布schema/fixture7-P2定稿前 | 二选一schema决定；相同内容字节、不同测量版本的发布/冲突/重放向量。未定或不通过阻止相关P2发布，不得原地覆盖旧metadata。 |
| D4-nit-1（nit）1a同逻辑键歧义 | P0 fixture1 golden定稿前 | a/b互异且各自跨执行稳定的规范键正向排序/物理ID扰动向量，另列重复键拒绝向量。未澄清不得标1a通过，不得放宽§3.3拒绝规则。 |

S续跑使用2/5 attempts，权威P1 **2→1→0**，停滞0；无产品回滚。三spike、runtime/命名接入、POML隔离、golden/crash/capability仍待各自阶段验证，**规范L4成功不等于运行或产品发布验收成功**。
