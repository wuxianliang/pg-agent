# v24 三份文档一致性核查与 Oracle 裁决

日期：2026-10-23。状态：**已裁决并已落地**（Oracle chat `untitled-chat-1EDE09`，两轮：裁决 + 文本复审）。

对象：

- 设计稿 `docs/designs/v24-pg-agent-2026-10-22.md`（652 行，R4 SATISFIED）
- pre-plan `docs/plans/v24-pre-plan-2026-10-23.md`（354 行）
- S1 plan `docs/plans/v24-s1-kernel-2026-10-23.md`（1052 行）

裁决方式：分 5 批提交，逐项只给选项不开放作答。**14 项全部选择 ①**，没有一项推翻我的核查判断。
中间有 3 批 MCP 客户端超时，但 Oracle 实际已完成并把答复写入 chat log，从 `oracle_chat_log` 取回。

## 1. 已实测的 PostgreSQL 18.4 事实

本机 pgembed 实测，用于判定哪些要求 DDL 能表达：

| # | 事实 |
|---|---|
| F1 | partial unique index 不能 `DEFERRABLE`；表级 `UNIQUE ... WHERE` 不存在 |
| F2 | 同事务内 partial unique 顺序敏感：E1 未关闭时插 E2 立即 `23505` |
| F3 | `DEFERRABLE` 唯一约束**不能**作为 FK 目标 |
| F4 | `CHECK` 不能含子查询 ⇒ 跨行/跨表不变量不能写成 CHECK |
| F5 | `DEFERRABLE INITIALLY DEFERRED` 的 CONSTRAINT TRIGGER 在 COMMIT 求值并能中止事务 |
| F6 | `pg_advisory_xact_lock(24,1)` 在 `pg_locks` 为 `(classid=24,objid=1,objsubid=2)` |
| F7 | `sha256(bytea)`、`gen_random_uuid()` 均为 `pg_catalog` 核心函数 ⇒ 不需要 pgcrypto |
| F8 | `SET ROLE` 改 `current_user`、不改 `session_user` |

## 2. 裁决表

类别：**A** = 设计稿必须修订（走 R5）；**B** = pre-plan 必须修订；**C** = 不改，S1 plan 内消化并记 deviation ledger；**D** = S1 plan 写错。

| # | 位置 | 冲突 | 裁决 | 改法 |
|---|---|---|---|---|
| Q1 | 设计 §2.1 L70 vs §A.2 L619 | `class` 四值且「command 的 claim 必须 null」，§A.2 又把 claim 写成 `class:"command"` | **A** | 扩为 5 值（增独立 `claim`），改 §A.2 L619；§2.1 的 claim 规则改为「command/claim 的 claim 必须 null」 |
| Q2 | 设计 §B.1 L509 | 末句「install 置于 fiber 之后」与同句向量 `effect→install→fiber` 相反；§2.3 L88、§B.2 反例一支持 install 在前 | **A** | 删去「置于 fiber 之后、episode 之前」半句，以最终向量为准 |
| Q3 | 设计 §2.1 L74 vs §B.3 L548–550 | 说客户端选 `effect_id`，八个 wrapper 签名却没有该参数；不改则同键重试换 id、replay 失效 | **A** | wrapper 以 `f(principal,request_key,kind)` 派生，`advance` 断言相等，ABI 不变 |
| Q4 | 设计 §B.4 L564 vs §B.3 L554 | `receipt_conflict` 被使用但不在错误闭集 | **A** | 并入闭集（23 码），与 `request_conflict` 区分 |
| Q5 | 设计 §3.1.4 L148 vs §3.2 L189 | 单列 `consumer_id` 写不出「消费者 XOR CHECK」，也挂不了两个真实 FK | **A** | 增 `consumer_episode_id`/`consumer_run_id`，`consumer_id` 改生成列；§3.2 明确 XOR、索引、外键 |
| Q6 | S1 plan §4.19 | wrapper 为 INVOKER 且调纯 helper，授权清单漏授 ⇒ `42501` | **D** | 已修：四个纯 helper（`canonical_json`/`effect_id_for`/`principal_id`/`error_v1`）一并授给三个应用角色 |
| Q7 | pre-plan §6.1 L243 | 写「DROP/CREATE 自己的临时库」；v99 实际是唯一库名 + template0 + OID 复核后 FORCE DROP | **B** | 改 pre-plan 为 v99 实践；AGENTS.md 同一措辞宜同步 |
| Q8 | 设计 §3.1.9 L176 | `seq` 语义只覆盖 run，唯一约束却覆盖所有 entity | **A** | 补通用规则：同事务 MAX+1、G 串行、回滚重用、不承诺无空洞、replay 不重分配 |
| Q9 | 设计 §3.1.3 L142 + §6.7 L367 | `effects` 无 `install_id`，host effect 与 install 只能靠 jsonb 绑定、无索引 | **C** | 不动表：加部分表达式索引 `((request->>'install_id')) WHERE kind IN ('host_prepare','host_release')`，绑定校验放解释器 |
| Q10 | 设计 §9 L435 / pre-plan §2.3 L84 | G1 含「T1 前 IO 失败」但 T1 无定义；pre-plan 的 G1 判据漏了这句 | **A + B** | 设计稿定义「T1 = ready→claimed 资格提交，T2 = 外部结果接纳」；pre-plan 补回「claim 未提交前不得有 IO」 |
| Q11 | pre-plan S1 卡 L110 | 「不实现完整 dispose/close」与允许写 `close_requested_at` 的边界未写清 | **B** | 改为「不实现完整 close（排空与 `closed_at` 属 S5）；允许 `close` 只写关闭意图」 |
| Q12 | 设计 §3.1.1 L128 | 「CHECK/复合 FK 保证路径端点」实测做不到（F4） | **A** | 改为「本行端点用 CHECK；父子前缀与同 root 由 advance 在 G 下校验，延迟约束触发器兜底」 |
| Q13 | 设计 §3.2 L187 | 把跨行/跨表排空不变量列在「必要约束」下 | **A** | 拆两类：可 DDL 表达的留 §3.2；排空屏障移到 §3.1.1 语义段并注明 advance-only |
| Q14 | pre-plan §5.3 L232 | 写「loader 拒绝缺口」，v99 无数字缺口检查 | **B** | 改为「拒绝非声明前缀、symlink、未登记文件」 |

统计：A 类 9 项（Q1、Q2、Q3、Q4、Q5、Q8、Q10-设计半边、Q12、Q13），B 类 4 项（Q7、Q10-pre-plan 半边、Q11、Q14），C 类 1 项（Q9），D 类 1 项（Q6，已修）。

## 3. R5 复审的最小集合

Oracle 裁决：若只能改三处，选 **Q1、Q3、Q5**（其原话按当轮标号为 `Q1、Q3、Q6`，即 class 闭集、wrapper effect_id、pins 拆列）——理由是**先冻结 ABI、幂等身份与核心表结构**。

这三项确实是 S3–S7 全部消费的冻结合同，其余 A 类项是措辞与约束表达精度，可并入同一次 R5，不必单独开轮。

## 4. 连带影响（Oracle 给出）

改 Q1/Q3/Q5 时，设计稿还需同步以下节：

| 节 | 为什么要动 |
|---|---|
| §2.1、§A.2 | 把 `claim` 定为独立 class；改为由 wrapper 派生 `effect_id` |
| §2.3、§A.3、§B.3 | 说明派生规则；在 request replay 检查**之前**校验 `effect_id` |
| §B.5、§A.1 | §B.5 的 `claim` 状态转换对齐 `ready→claimed`；§A.1 的 kind 闭集**不变** |
| §3.1.4、§3.2 | 增消费者两列与生成列，明确 XOR、索引与对应外键 |
| §6.5 | run 消费者改写为 `consumer_run_id`，保持 activation/run XOR 描述 |
| §3.4 | **不必改**——拆列不改变现有 pin 生命周期不变量 |

这条「§A.1 kind 闭集不变」值得注意：它确认 `spawn` 仍不是 effect kind，S1 plan 的 kind 闭集无需调整。

## 5. 与 S1 plan 的关系

S1 plan §7 的 D1–D11 是**披露**，不能替代规格修订。R5 修订落地后：

- **已并入设计稿正文**：D1（class 5 值）、D2（`receipt_conflict`）、D3（pins 生成列）、D8（`effect_id` 派生）、D9（`entity_type` 闭集）、D10（`canonical_bytes` 归属）。
- **已由设计稿或 pre-plan 明确**：D4（锁向量 install 在前）、D6（S1 `close` 只写意图）。
- **保留为实施裁决**：D5（`effects` 无 install_id，按 C 类加部分表达式索引）、D7（不引入 pgcrypto）、D11（principal 派生算法）。

开工顺序：W1–W7 全部解除阻塞。W1（骨架）与 W2（十表 DDL）不消费 `advance` ABI，可立即开工；W3 起依赖 `class` 闭集与错误闭集，待本节第 6 节的复审结论确认后开工（复审已完成，3 个问题均已修正）。

## 6. R5 修订落地与文本复审

2026-10-23 同日完成 13 处修订，**全部为行内改写**：设计稿仍 652 行、pre-plan 仍 354 行，行号零位移，因此三份文档与 `v24-stage-decomposition` 里的所有 `L###` 引用继续有效。

修订清单：设计稿 §2.1 L70/L74、§2.3 L89/L90、§3.1.1 L128、§3.1.4 L148、§3.1.9 L176、§3.2 L187/L189、§6.5 L353、§7.1 L381、§B.1 L509、§B.3 L554、§A.2 L619、§A.3 L631；pre-plan L3、L84、L110、L232、L244、L328、L330。

**文本复审发现 3 个由改写本身引入的问题**（Oracle 第二轮）：

| # | 问题 | 修正 |
|---|---|---|
| E1/E11 | `class` 增了 `claim`，但 §2.3 的执行次序仍只分 command/host，第 4 步还统一「验证 claim token」——claim 此刻尚未签发 token | §2.3 L89 改为按 class 分流：`claim` 不校验 token、只校验可被 claim 并签发资格；§2.3 L90 补 `claim` 不运行解释器、不产生 delta |
| E6 | L187 写「只由 advance 强制」，与 L128 的「延迟约束触发器兜底」互相矛盾 | L187 改为「由 advance 在 G 下强制、并以 DEFERRABLE 约束触发器兜底」 |
| E8 | 把 host 回执纳入 T2，但 pre-plan 的 O9 仍列为未决 | O9 关闭（pre-plan L330、S1 plan 同步）；O7 同时收窄为只剩 kill 点数 |

这三条正是「改 A 处会推翻 B 处」的实例，说明只做逐项裁决不够，必须对改后文本再跑一轮一致性检查。

## 8. W3 开工前的 5 项裁决（chat `untitled-chat-F3BCDF`，2026-10-23）

W3 的实现级调查发现计划自相矛盾（claim 分支归属、token 返回位置、死字段 `receipt_key`）。五项均裁为 ①：

| # | 问题 | 裁决 | 落地 |
|---|---|---|---|
| 1 | claim 归 W3 还是 W5 | W3 = 解释器之前的一切；claim 归 W3，W5 只做 settlement | 计划新增 §4.21 归属表与 8 条 Done-when |
| 2 | claim token 从哪返回 | 返回封套增可选 `claim` 成员，仅 class=claim ∧ committed 时非空 | 设计 §2.1 L72（行内改写）；计划 §4.13 与 §4.14.2；记 D12 |
| 3 | 死字段 `receipt_key` | 所有 class 可省略，不参与匹配；receipt 身份 = `effect_id` + outcome digest | 设计 §2.1 L70（行内改写） |
| 4 | 对已结算 effect 发 claim | `invalid_args`（不是 `already_terminal`） | 设计 §B.5 L588；计划 §4.14.2 K2 与 §4.21 第 6 条 |
| 5 | `claim_owner` 存什么 | `session_user::text`（登录角色名） | 设计 §B.4 L562；计划 §4.13 claim body 与 §4.14.2 |

设计稿本轮仍是**行内改写**：4 处（L70、L72、L562、L588），文件仍 652 行，行号未位移。

计划侧同步：新增 §4.13.4（优先级表，修好了 §2.2 C4 指向不存在锚点的问题）与 §4.21（W3 归属与判据）；重写 W3 行；§4.14 拆出 E1–E4、A3.5 补 `canonical_bytes` 复算、C3/K1 改正锁序（原来在 scope/run 之前就对 effects 取 FOR UPDATE，违反 B.1）；G1 表拆分 G1-F/F1/F2、G1-H/H1/H2、G1-L/L1/L2 并新增 G1-Q、G1-R；记 D12、D13。

## 9. 实现进展

- W1、W2 已完成并由编排方逐条实跑验证（三个 gate 退出码均为 0），详见计划 §1 的进度段。
- W3 已完成：`30_advance.sql` + `test_g1.py`，四个 gate 全绿（含 W2 回归）。

## 10. W4/W6 次序问题的裁决（chat `untitled-chat-B38EF4`，2026-10-23）

发现的问题比原先报的更大：W4 的判据（replay 返回首次 response、全库 diff 为空）需要 `interpret_command`；而 **W5 剩余的实质工作（S4–S6）需要 `interpret_settlement`** —— 两者都在 W6，W6 却排在它们之后，次序倒置。此外 W5 原判据（首次 claim 1/1、过期重 claim 2/2、`stale_claim`、replay）与 W3 已绿项重叠。

| # | 问题 | 裁决 |
|---|---|---|
| 1 | 工项边界 | **② 解散 W6**，按「谁先需要」拆：`scope_control` → W4；`install` + `host_prepare` + FakeHost + `interpret_settlement` → W5 |
| 2 | W4 的 scope_control 范围 | **① 全套三 action**（create_root / create_child / close），一次冻结 scope 路由与关闭合同 |
| 3 | W5 判据与 W3 重叠 | **① 只保留 S4–S6**；claim 相关删除，回归由 W3 的 gate 守住 |

落地：W4 = admission + `scope_control`；W5 = install + host_prepare + FakeHost + settlement；原 W7 重编号为 **W6**（ACL/收尾）。计划 §1 工项表、§3 映射表、§4.21 归属表、开工顺序已同步。

## 11. W6 的 owner/协议角色拆分（chat `untitled-chat-F1CED0`，2026-10-23）

W6 做 ACL 时停工上报了两个真问题：

1. **`v24.scope_control` wrapper 不存在**。W4 只实现了 `interpret_command` 的 scope 分支，但计划与 ACL 都把它当成已存在的公开入口，于是 `GRANT EXECUTE ON FUNCTION v24.scope_control(...)` 使整个 manifest 加载失败。属 W4 交付缺口，由 W6 补齐。
2. **§4.19 会直接弄坏 `advance`**。原文对 `PUBLIC, v24_admin, v24_service, v24_operator` 统一 `REVOKE ALL ON ALL TABLES`，而 `v24_admin` 是 `advance` 的 SECURITY DEFINER owner。本机 PG 18.4 实测：对 owner 回收表权后，以它为 DEFINER 的函数写表报 `permission denied for table t`。

根因是我把设计 §B.3 L542 区分的两个身份（「受信 service role」与「迁移 owner」）写成了同一个名字。

| # | 问题 | 裁决 |
|---|---|---|
| 1 | 角色模型 | **① 新增 `v24_owner`**（NOLOGIN，拥有 schema 与全部对象与 `advance` 的 DEFINER，保留 DML/DDL）；三个协议角色零表权 |
| 2 | `create_root` 归属 | **① 仍留 `v24_admin`**，三行矩阵不变 |

落地：§4.19 角色表与授权块、§5.4 fixture、G1-P 断言均重写；记 D14。

## 12. 本轮未做的事

- 未提交任何文件。
- 未修改 `v24-db-native-agent-system-2026-10-22.md`（旧稿明确「保留为研究基线，不删除、不改写」）。
- 未修改 AGENTS.md 中与 Q7 同源的「DROP/CREATE 自己的库」措辞——它描述的是 v8 时代约定，是否同步留给仓库维护者决定。
