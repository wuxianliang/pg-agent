# v24 偏差台账（S1–S8 + M-H + M-R）

> 收尾稿：2026-10-24。本文件是 S1/S2/S3/S4/S5/S6/S7/S8 里程碑的收尾工件，记录各计划 §7 的实施偏差。**S5 W1–W4 已实现，W5 为收尾**；**S6 W1–W4 已实现并结项，G5 父门完成（K1–K10 10/10）**；**S8 W1–W3 已实现，W3 收尾并在 closeout 前修复 D-S8-12，G7 父门完成（G7-A…H + N1–N7）**；**S7 W1–W2 已实现并结项，G6 完成（30/30），11/11**；**M-H 已实现，G8 完成（23/23），历史 11/11 不变**（见 §1.16）；**M-R 已实现，G9 完成（11/11），历史 11/11 不变**（见 §1.17）。2026-10-24 S6/S8 收尾轮十个 gate 串行实跑全部退出 0：load、`s1/setup_db.py --self-check`、`s1/test_ddl.py`、`s1/test_g1.py`、`s2/test_g3a.py`、`s3/test_g2.py`、`s4/test_g2b.py`、`s5/test_g4.py`、`s6/test_g5.py`、`s8/test_g7.py`（命令与结果见矩阵 §0）。**Gate 计数口径（9+1=10）**：9 个既有 gate + 无参数全量 G7 = 10 条命令，全部退出 0（10/10）；历史 S6 W1–W3 与 S8 W1/W2 的 `--only` 是增量检查点，不计入十条命令，也不替代父门。S7 收尾轮在既有 10 条 gate 之外追加无参数全量 `v24/s7/test_g6.py`，共 **11/11**（10 条既有 + G6）；历史 10/10 为 S6/S8 收尾口径，保留不变。规则：**每条与设计稿不一致的实现都必须具名落账，不得静默改规格**；规格修改走「设计稿修订 + Oracle 复审」（pre-plan §1.2）。历史失败追加修正结果，不覆盖、不删去。

裁决来源：`docs/reviews/v24-three-doc-consistency-2026-10-23.md`（chat `untitled-chat-1EDE09`，14 项）、W5/W6 实施裁决（chat `untitled-chat-B38EF4`、`untitled-chat-F1CED0`）、S5 计划与逐 W 实施裁决（chat `untitled-chat-DFBC85`，2026-10-24：F1=A、F2=A、F2a=A、F2b=A、F3=A、F3a=A、F4=B′、F5=A、D-S5-1=A）、S6 计划与实施裁决（chat `028D07`，15 项 ACCEPT：CC-1/2/3、D-S6-1…12；S6 W1–W4 实施）。设计稿 652 行、pre-plan 354 行，R5 修订为行内改写，两份文件行号未位移，因此 `L###` 引用继续有效。R6 只追加设计稿附录 C（1–652 行不变），但 pre-plan 增加 S8/C16/O11–O13 等行，pre-plan 的旧 `L###` 引用须按 R5 版本核对；设计稿 1–652 的 `L###` 继续有效。R6（2026-10-24，chat `028D07`）为设计稿规格修订（附录 C，15 项 ACCEPT）；S6 W1–W4 已实施并由 G5 证明（见 §1.9–§1.11、§5）。S8 的 R7（同一 chat 的 Q1–Q7 全 A）见设计稿附录 C.6；D-S8-11 于 W2 由 Oracle 批准（2026-10-24）；D-S8-12 为 W3 评审发现并在收尾前修复的产品缺陷；S8 W1–W3 已实施并由 G7 证明（见 §1.12–§1.14、§5）。

## 1. 规格分歧 D1–D14

| # | 分歧 | 设计稿位置 | 采用 | 落位 / 证据 |
|---|---|---|---|---|
| D1 | `class` 取 5 值（增 `claim`） | §2.1 L70 原为四值且「command 的 claim 必须 null」；§A.2 L619 又把 claim 写成 `class:"command"` | 5 值闭集 | **已并入设计稿正文（R5）**。`T.shapes` 断言 6 个非闭集值各 `invalid_args` 零写；`T` 五分支 dispatch 断言 |
| D2 | `receipt_conflict` 并入错误闭集 | §B.4 L564 使用；§B.3 L554 未列 | 23 码闭集 | **已并入设计稿正文（R5）**。`T.catalog` 逐码接受；`T.claims_and_receipts`、`T.install_settlement_w5` 均产生该码并零写 |
| D3 | `pins.consumer_id` 改为生成列 + 两列 FK | §3.1.4 L148 单列；§3.2 L189 要求 XOR CHECK | 生成列 `consumer_id`，保留 `consumer_episode_id`/`consumer_run_id` | **已并入设计稿正文（R5）**。`D.negatives` 打穿 `c_pins_xor` 与复合 FK；`G1-N` 只断言十表 |
| D4 | 锁向量取 `effect → install → fiber` | §B.1 L509 末句「install 置于 fiber 之后」与同句向量相反 | 取最终向量 | **R5 已删矛盾末句**。`T.catalog` 按源码出现次序断言八段锁语句；`T.locks` 实测 G 首锁与 `objsubid=2` |
| D5 | `effects` 无 `install_id`，绑定靠 `request` jsonb | §3.1.3 L142 列表现状 | 保持现状；加部分表达式索引 + 解释器校验 | 计划 C 类裁决。`T.closure_retry` 证明悬空引用得 `retry_with_closure` 零写、修复后可重交；S5 消费该索引 |
| D6 | S1 的 `scope_control(close)` 只写 `close_requested_at` | §3.1.1 L130 第一步；pre-plan「S1 不做完整 close」 | 只写意图 | **设计稿与 pre-plan 已明确（R5）**。`T.scope_control_w4` 断言 `closed_at IS NULL` 且关闭后 `scope_closed` |
| D7 | 不引入 pgcrypto | — | 核心 `sha256()`/`gen_random_uuid()` | 实施裁决。`00_schema.sql` 做函数可用性断言；`S._assert_closed_catalog` 断言 `extensions == []` |
| D8 | `effect_id` 由 `(principal, request_key, kind)` 确定性派生 | §2.1 L74「客户端选 id」；§B.3 L548–550 wrapper 无该参数 | wrapper 内派生；advance 断言相等 | **已并入设计稿正文（R5）**。`T.command` 用 `effect_id_for` 派生；`T.command_prefix` 断言 C0 先于 replay |
| D9 | `events.entity_type` 闭集 8 值 | §3.1.9 L176 未列闭集 | 8 值 | **已并入设计稿正文（R5）**。`D.negatives` 断言保留列 CHECK；`T` 断言 install entity 的 `seq = [1,2]` |
| D10 | `canonical_bytes` 由 wrapper 计算、advance 复算 | §2.1 L70 列在 body；§A.3 L631 说 wrapper 交原始字节 | wrapper 算 + advance 复算比对 | **已并入设计稿正文（R5）**。`T.shapes` 用篡改的 `canonical_bytes` 得 `invalid_args` 零写 |
| D11 | principal = `md5(session_user)` 派生 uuid | §2.3 L86 只要求 session_user→principal，未定算法 | md5→uuid | 实施裁决。`T.catalog` 断言 `principal_id('example') = md5('example')::uuid`；`T.identities_and_matrix` 断言 `SET ROLE` 不改派生值 |
| D12 | 返回封套增可选 `claim` 成员 | §2.1 L72 原文无该成员；§4.14.2 K2 要求返回 token | 仅 claim+committed 时非 null | **已并入设计稿正文（R5 补充轮）**。`T.expect_envelope` 全分支逐字段断言（G1-R） |
| D13 | `claim_owner = session_user::text` | §B.4 L562「绑定受信 host principal」 | 登录角色名 | 实施裁决（Oracle ①）。`T.identities_and_matrix`、`T.claims_and_receipts` 断言 token.owner=`session_user`；`T.permissions` 断言 SET ROLE 后不变 |
| D14 | 新增迁移角色 `v24_owner`，三个协议角色零表权 | §4.19 原文让 `v24_admin` 兼任 owner 并对它 REVOKE | 四个组角色：`v24_owner` 拥有对象，`v24_admin`/`service`/`operator` 零表权 | **§4.19、§5.4、G1-P 已改写**。实测：对 owner REVOKE 后以它为 DEFINER 的函数写表报 `permission denied for table`。`50_permissions.sql` fail-closed 断言每个函数 owner 与 `search_path`；`T.permissions` 三角色各 30 条 DML 全 `42501`，owner 例外显式断言 |


### 1.1 S2 分歧与实施裁决（D-S2-1…11）

| # | 分歧 | 设计位置 | 采用 | 落位 / 证据 |
|---|---|---|---|---|
| D-S2-1 | successor 可生为 `succeeded`/`failed` | S1 计划 §4.14.4 只列 ready successor | 仅 `fiber_reconcile` 可 born-settled | 同一次 advance 结算一个阶段；`R.fiber_control_activation`、`R.deactivation_barrier` 断言 reconcile 状态与 outcome |
| D-S2-2 | fiber CAS 用 `stale_generation` | §6.3 只说「验 CAS」 | `stale_generation` | 闭集内唯一 CAS 码；`R.fiber_control_activation` 实测 W1 + 领域零写 |
| D-S2-3 | 未结算 reconcile 存在时同向命令继续驱动 | §6.3「目标一致 ⇒ 幂等」 | 解释为「目标已完成」 | 否则 S2 没有合法驱动者；`R.deactivation_barrier` 用新 key 的 off 完成阶段 B |
| D-S2-4 | child install 不要求 scope 等于 owner scope | §6.2 未要求 | 允许子 scope | scope 关闭按 owner 身份枚举；`R.install_fibers` 只校验 owner 身份 |
| D-S2-5 | `check_policy` v1 封闭谓词 | §3.1.7 未给形状 | `{v:1,op:equals,path,value}` | 纯数据、可证伪；`R.fiber_control_activation` 断言非法 shape 在 admission 拒绝、false 在 activation 得 `dependency_unresolved` |
| D-S2-6 | dispose 阻塞返回 committed + dispose_pending | §6.7「保持 dispose_pending/closing」 | committed，无 successor | Oracle 5A；`R.dispose_leaf` 覆盖 active fiber / prepare_unknown 两路 |
| D-S2-7 | install admission 创建一个 inactive fiber | 设计未写 fiber 的创建者 | 每 install 恰一个，`fiber_id=md5(install_id::text\|\|':fiber')` | `fiber_control` 只收 fiber_id；`R.install_fibers` 断言 deterministic 与 replay 不增 |
| D-S2-8 | dispose 写自有 fiber 的墓碑 | §6.7 只说「检查 fibers 已 disposed」 | 义务满足后写 `disposed_at` + `want_on=false` | 设计未给 fiber dispose 动词；off 必须保留 fiber 以便 E1→E2；`R.dispose_leaf` 断言 |
| D-S2-9 | delta 增 `settle[]` 结算既存 reconcile | S1 计划 §4.14.4 只有 insert 型 successor | 只允许 ready `fiber_reconcile` | 续驱结算同一条 effect；`R.deactivation_barrier` 断言 reconcile 计数不增、effect_id 前后相等 |
| D-S2-10 | delta 的 `effect` 补丁可写归属列 | S1 计划 §4.14.4 的 `effect` 只有 status/outcome | 可选 `scope_id`/`fiber_id`/`episode_id`，校验一致 | W1 失败 receipt 也带 fiber 归属；`R` 的 CAS/失败断言 |
| D-S2-11 | 闭包/applier 直接改 30/40 | S2 计划 §4.0 原写「45 覆盖分派函数」 | 45 只放 `resolve`、wrapper、索引 | 复制数百行函数会产生两份定义并漂移；`git diff` 可审 |

### 1.2 S3 分歧与实施裁决（D-S3-1…8）

| # | 分歧 | 设计/计划位置 | 采用 | 落位 / 证据 |
|---|---|---|---|---|
| D-S3-1 | 读面 DEFINER allowlist，并修复 S2 resolve 缺陷 | §B.3 未定 security；S2 `resolve` 为 INVOKER | `resolve/poll/wait_check/run_owner/run_projection` 采用固定 search_path 的只读 DEFINER allowlist；helper 内部且不授予协议角色 | S2 只由 owner 实测 resolve；三个零表权协议角色作为 service 调用会 42501。S3 W1 改为 DEFINER 并补真实 service/operator 调用断言；`run_owner`/`run_projection` 未 GRANT |
| D-S3-2 | effect delta 加 `run_id` | §4.14.4 delta 无 run 归属 | 可选 `run_id` 并校验与 payload 一致 | 支撑 command_start/后继 effect run 归属和 run projection 审计 |
| D-S3-3 | run handle 不扩返回封套 | §4.2 要求 start 返回 handle | `emitted[0]` 是 run_id，registration_generation v1 固定 1 | 保持封套键闭集；poll 回显 registration |
| D-S3-4 | cancel 将 ready effect 置 cancelled | §4.5 要求归档未 claim 后继 | `status=cancelled`、outcome NULL、settled_at 设置 | 符合 `c_effects_outcome`，不增加 archive 表 |
| D-S3-5 | steer 立即续链边界 | §4.6 对旧 claimed 后继的说明 | 无旧 claimed 时立即建 model_call；有 claimed 时 pending_steer，不建 successor | 避免旧/新驱动重叠；applier 先写 effects 更新，再插 successor，以满足 `u_effects_model_call` |
| D-S3-6 | interaction 生产归属 | §4.7 model outcome 路径 | S3 只消费测试 seed interaction，生产归 S4 | S3 不声称生产覆盖 |
| D-S3-7 | owner fiber scope 与 run scope | §4.2 未明确 | start 要求二者 scope 相同 | 防止跨 scope run pin 的歧义 |
| D-S3-8 | claim 曾接受除 `command_*`/`fiber_reconcile`/终态外的任意 kind | §4.16/§7.1 claim 资格；S3 计划未含 model/tool settlement | 临时 allowlist：仅 `host_prepare`/`host_release` 可 claim；其余 kind 一律 W0 `invalid_args` 零写；终态仍拒 | 结算器当前只处理 `host_prepare`/`host_release`；提前 claim `model_call`/`tool_call` 会在 claim COMMIT 后 settle 得 `0A000`，effect 永久 `claimed` 并卡死 run。S4 增加 model/tool settlement 时移除此 allowlist；`V.G2a-11` 断言真实 `model_call`、seeded `tool_call`/`inspect_resource`/`command_*`/`fiber_reconcile` 均拒且十表零写，`host_prepare` 仍可 claim |

### 1.3 S3 实施披露（非额外规格变更）

| 项 | 实际选择 | 状态/边界 |
|---|---|---|
| 可选 `wall_ms` | 缺省使用 86400000 ms | W2 budget 约定；测试应覆盖 omitted 值 |
| steer delta 应用顺序 | 先 effects 更新，再插 successor | 确保唯一索引 `u_effects_model_call` 在同 run successor 创建时可满足 |
| claimed/unknown 引用 pin | cancel 保留被引用 run pin；未知 effect 的静默/完整释放交 S4 | G3b-2 只验证保留；S4 已由 G2b-R/S 完成 terminal 同 advance 释放，unknown 只保留自身 pin |
| G3b-4 双序 | 两条已提交顺序场景 | 不是并发/锁屏障证明 |
| G3b-5 start/off 双序 | 两连接锁屏障，核对 `pg_blocking_pids()` / `pg_locks` | 本轮 `V` 实跑通过；G3b-4 仍只为顺序场景 |

### 1.4 S4 裁决与偏差（D-S4-1…10）

| # | 内容 | 依据 | 落位 / 证据 | 性质 |
|---|---|---|---|---|
| D-S4-1 | `model_call`/`tool_call` 的过期 lease claim 返回 W0 `stale_claim`，**不**做第二次 attempt；host 用 `class=unknown` 或 S6 inspect 解锁 | C18 / Oracle F2 | `30_advance.sql:712-713`；`G2b-T-7` 错 token 与过期 lease 同为零写；host kind 保持 S3 的 reclaim 语义 | 裁决（S6 边界） |
| D-S4-2 | `invalid_outcome` 拆结构 W0 / 语义 C：结构类保持 claimed、无 outcome；语义类结算 `unknown` + 原始 receipt + pin 保留 | F2=D | `G2b-V-1`（两次结构 W0）、`G2b-V-3`（语义 unknown + 原始 success receipt）、`G2b-T-2/T-3/T-5` | 裁决（落地 F2） |
| D-S4-3 | `blocked_unknown` run 的 steer/respond 返回 `blocked_unknown`（而非 `already_terminal`）；同 run 其它 business settlement 也 W0 墙 | C19/§5.7 | `G2b-N`（sibling/steer/respond 三面）、`G2b-T-10`；S3 G2a-7/G2a-8 的终端循环按 §1.7 对齐 | 裁决 + 声明式对齐 |
| D-S4-4 | 预算按 F3=A 字面实现：admission 预扣 steps/tokens，结算退差，tool_calls 批量扣 | F3=A | `G2b-L` 守恒账（5000=40+4096+864 等）、`G2b-J` 三路 budget seal、`G2b-K` 17/16/5 边界 | 裁决（落地 F3） |
| D-S4-5 | applier 对 settlement 采用「一致性 + 边界」校验，不逐字段重算；gate 逐列断言兜底 | 风险 R2 | `G2b-V`/`G2b-T` 的零写与重交；矩阵 §2.4 逐列 | 实施裁决（已知风险） |
| D-S4-6 | spawn intent 在 S4 不半实现；无 spawn 解释器，未建模的 intent/结果键在 C19 结果键闭集或 `v_executable` 守卫处 W0 拒绝，不建 child run | §2.4 | `48_loop.sql` 无 spawn 分支；`G2b-T-8` 验证 unknown+successors 守卫；**未单独构造 spawn 正例**，按边界披露 | 边界（不是已测能力） |
| D-S4-7 | S4 不做 lease 过期后的自动 reclaim / inspect；effect 可永久 claimed | C18 | D-S4-1 的另一面；矩阵 §4 明确“S4 不承诺自动 reclaim”；归 S6 | 边界 |
| D-S4-8 | 设计 §3.1.2/§5.4 补 `request.digests` 三摘要与派生算法；`runs` 不加列、`result` 不承载 | Oracle 补丁 1 | 设计稿已在 `097ffa5` 更新；`G2b-B/L/V` 断言 request digests 全等 | 设计修订（已落稿） |
| D-S4-9 | continuation 的 `parent_effect_id` = 批次 max-ordinal tool；身份与创建者解耦 | F5=A + max-ordinal | `G2b-A`（parent=ordinal 2）、`G2b-F`（creator 随顺序翻转但 parent/continuation 唯一） | 裁决（细化 F5） |
| D-S4-10 | G2b-G 的“第二 model”`invalid_outcome` 预检是**防御性**的、经公共 API 不可达；可观测契约是直接 INSERT 撞 `u_effects_model_call` 得 `23505`，以及已闭合批次上多余 `claimed` tool 得 `invalid_outcome` W0 | W2.1 / Oracle A | `G2b-G`；防御预检不是协议路径，不声称可达 | **非偏差披露** |

> D-S4-10 与 W2.1 的并发证据补齐都是**非偏差**：前者是防御性预检的可观测性说明，后者只补测试证据（两连接 + Barrier + `pg_blocking_pids`），不改产品语义。

### 1.5 S5 裁决与偏差（D-S5-1…11）

S5 的 11 条分歧在计划 §11 登记、在 W1–W4 落地。下表按**实际代码/测试**记录落位；凡计划文字与实现有出入的，以代码为准并在「性质」列标明（D-S5-6、D-S5-8 有备注）。Oracle 裁决：F1=A、F2=A、F2a=A、F2b=A、F3=A、F3a=A、F4=B′、F5=A、D-S5-1=A（`untitled-chat-DFBC85`，2026-10-24）。

| # | 内容 | 依据（设计/计划/Oracle） | 落位/证据 | 性质 |
|---|---|---|---|---|
| D-S5-1 | close 不产生 command successor：drain 只写 `close_intent={kind:'close'}`，不改 run status/ended_at、不发 successor；run 的 terminal 由 `loop_sealable` 在自身结算时收口；close 由新 request_key 逐 phase 推进 | 设计 §3.1.1；计划 §11-1；Oracle F4=B′、D-S5-1=A | `40_interpreters.sql` 的 close drain 分支；G4-G（drain 后以 `parent_effect_id=close effect` 计 successor 为 0、status/ended_at 不变、`pending.runs=1`）；G4-M-1（closed 后新 key `already_terminal`） | 显式分歧（Oracle 裁 A） |
| D-S5-2 | inspect 是**新 effect**，不复用原 host effect：id=`md5(owner_effect::text\|\|':inspect_resource:'\|\|install_id::text\|\|':0')`，request 带 `target`/`target_effect_id`/`target_reservation`/`target_request_digest`。**实际 request 恰 6 键、不携带 inspect 自身的 reservation**：计划 §12.2 所说的 `v24:inspect_resource:<inspect_id>` 只出现在 id 派生/命名空间，不是 request 字段；inspect 只靠 `target_reservation` 引用原 host effect | 设计 §6.7；计划 §11-2、C25；Oracle F2=A | `46_cleanup.sql` 的 `dispose_stage` inspect 分支 + `40_interpreters.sql` inspect claim/settlement；G4-H（request 逐键、target reservation/digest 逐字节相等、确定性 id）、G4-N（7 个 claim 负例 + 真实 claim→settle） | 实施裁决（同 reservation 命名空间，语义等价；自身 reservation 未落 request） |
| D-S5-3 | 「一次 advance 只执行一个有限阶段」从 reconcile 扩展到 dispose/close：stage ≤16 行、≤16 successor、不递归；close 每个新 key 恰一个 phase（request→drain→retire→cascade→barrier→finalize） | 设计 §6.3；计划 §11-3；Oracle F3=A、F3a=A | `dispose_stage` 的 `v_rows>=16`/`v_ordinal>=16` blocked 与 `deactivate_stage` 的 16 行上界；G4-Q（单次 dispose 恰 1 successor、changed rows ≤16、pending 不降证明 stage 边界）、G4-G（每 key 恰 +1 条 `scope_close_phase`，phase 序单调） | 扩展解释（不改规格文字） |
| D-S5-4 | 贡献按 `contribution_seq DESC` **一条一 advance** 释放，不是一批 DESC；consumer pins 先于其 slot 释放；episode 只在最后一条 slot 释放后 closed | 设计 §6.6；计划 §11-4、C27；Oracle F3=A | `deactivate_stage` 的 `cleanup_slots ... LIMIT 1`；G4-D（三次 off 依次 `[2]`→`[2,1]`→`[2,1,0]`，episode 第三次才 closed）、G4-P（`[1,0]`）、G4-C（provider 一次一条 release） | 字面实现 |
| D-S5-5 | `dispose_stage` 是命令/close 内的有界 helper，不是独立 worker：INVOKER、无 GRANT、无后台进程/LISTEN；唯一入口是 `interpret_dispose` 与 close 的 cascade phase | 设计 §6.1；计划 §11-6；Oracle F1=A | `46_cleanup.sql:1-6` 头注；`40_interpreters.sql` 仅两处调用（`:315` close、`:3300` dispose）；G1-A（DEFINER 仍 6 个、advance 唯一可写）、G4-W1/G4-Q（单次调用有界） | 一致（澄清） |
| D-S5-6 | owner 屏障的权威键是固定 `(owner_fiber_id, owner_episode_id)` 对（`cleanup_edges` 的 owner 边、`install_disposed_ok` 义务 4），不联 `current_episode_id`。**备注**：`deactivate_stage` 的 episode-close child 屏障是 fiber 级（该 fiber 的任意 owner 对 child），比 pair 更严，未放宽 | 设计 §3.1.8；计划 §11-7、C24；G4-A/G4-P | `cleanup_edges` owner 边、`install_disposed_ok` 义务 4；G4-A（A→R、B→A）、G4-P（child disposed 前 root 不发 release、不落墓碑）；`deactivate_stage` 的 `ci.owner_fiber_id=p_fiber_id` 屏障（W4 注记，fiber 级） | 实现对齐（pair + 一处更严的 fiber 级屏障） |
| D-S5-7 | host effect 为 `unknown` 且 `resource_quiesced_at IS NULL` 时，dispose 必须先发/复用 inspect，绝不再发第二条 release；未证明静默前不得 `disposed`/`closed_at` | 设计 §6.7；计划 §11-8、C25；Oracle F2b=A | `dispose_stage` 的 `dispose_pending` unknown 分支；G4-I（release unknown→恰一条 inspect、release 计数仍 1；inspect 新 key 新 id）、G4-M-8（只发 inspect）、G4-F（unknown 时 close 恒 `closed_at NULL`） | 补规格未写分支 |
| D-S5-8 | 30 的 `installs→child installs` 闭包边修正为 root install 展开其 fiber 的 child installs。**实际落地**：该边只对 close 命令加入；`dispose` 仍走既有 sibling 边（root 无 owner 对，不展开），child 由 `dispose_stage` 的 `FOR UPDATE` 在 helper 内自行锁 | 计划 W1 步骤⑤、§10.1 R9、§11 D-S5-8；W1 注记⑥ | `30_advance.sql` close 的 owner-descendant 边（`fibers f ... ci.owner_fiber_id=f.fiber_id`）；`dispose_stage` pass 1 的 `FOR UPDATE`；G4-W1/G4-P 证明 dispose 的 child 锁与 child-before-owner 序；**dispose 闭包边未扩**；**S7 评估已完成：N7 + L1/L2 未发现 lock-order/deadlock bug；D-S7-1 未触发** | 部分落地 + 显式披露（不是全量 D-S5-8） |
| D-S5-9 | `cleanup_cycle` 的 admission 检查是**防御性**的：公共路径不能构造 owner/dependency 环（owner pair 由活 fiber 派生，公共 API 不能改 owner 列）；只有 seeded/外部修复图可达，命中仍 W1 failed receipt + 领域零写 | 计划 F5=A、§10.2、C24；D-S5-9 | `40_interpreters.sql:2869-2873`（owner 活性之后、任何行构造之前）；G4-E 以 seeded 环直接调 `v24.install`，得 `cleanup_cycle`、path 长 4、domain 零写、installs 计数不变；**不声称公共路径可达** | 边界披露（防御性，不是公共负例） |
| D-S5-10 | 跨 scope 的 child install 通过 owner 边递归纳入 close 闭包（`cleanup_close_closure`），不收紧 admission；dependency 邻居不算 close 义务，由 live pin / host effect blocker 表达 | 设计 §2.4/§6.2（admission 不要求同 scope）；计划 C24、R10、D-S5-10 | `cleanup_close_closure` 的递归 owner CTE（无 scope 过滤）；`scope_closable` 的 pins/effects blocker；G4-G 覆盖 scope 父子；**无跨 scope child install 专用 fixture**（代码路径成立，当时为证据缺口）；**S7 评估已完成：N7 用真实 `new_child_scope` + `admit_install(owner_fiber=…)` 构造并跑通跨 scope child install，D-S7-3 未触发** | 裁决（不收紧 admission）+ 证据缺口披露 |
| D-S5-11 | `preparing\|prepare_unknown` 的 dispose **先 inspect、保持原态**，不写 `dispose_pending`：known→installed、absent→prepare_failed、unknown 保持；`ready\|claimed` host_prepare 只阻塞、不发 inspect | 设计 §6.7、C7 状态迁移；计划 C25/D-S5-11、A-S5-1/A-S5-9；Oracle F2a=A、F2b=A | `dispose_stage` prepare 分支；G4-H（prepare_unknown→inspect known→installed→release→disposed）、G4-J②（absent→prepare_failed→0 release 直接 disposed）、G4-K（两路 + seeded `dispose_pending` receipt_conflict） | 实施裁决（合同强制） |

Oracle 逐 W 终判与终判时记录的残余风险（run log Turn 10–13；每轮八门最终运行均 0）：

| 工项 | Oracle 终判 | 终判时的 residual risk |
|---|---|---|
| W1 | PASS | 30 的 child-install 闭包边未扩、prepare 仅 intent；W2 必须收敛 inspect |
| W2 | PASS | inspect failure/unknown 不证明外部静默；收敛需要新 request_key；并发面归 S7 |
| W3 | PASS | close 只有串行 request-key 证据；并发/崩溃不外推 |
| W4 | PASS | `cleanup_pending` 非严格递减；close 依赖新 key；不得外推自动收口/并发无饥饿 |

### 1.6 S5 声明式断言对齐（不是放宽）

计划 §9 原列 A-S5-1…7；W2 为执行 C18/C25 的冻结形状又长出 **A-S5-8**（G2a-11 `claimable_kinds()` 4→5）与 **A-S5-9**（G3a-K preparing 子段），计划 §12.2 已补记。本表按实际九条全录（**superset：7 + 2**），每条给原断言、现断言、冻结合同的强制点与「不是削弱」理由。

| # | 原断言（S1–S4） | 现断言（S5） | 冻结合同为何强制 | 不是削弱 |
|---|---|---|---|---|
| A-S5-1 | `s2/test_g3a.py` G3a-K：`prepare_unknown` 的 dispose 后 install 停在 `dispose_pending`、`emitted==[]`、host_release 计数 0 | install 保持 `prepare_unknown`；恰一条 ready `inspect_resource`（确定性 id、target=host_prepare、request 6 键与原 reservation/digest 全等）；host_release 0；G4-H/J/K 继续覆盖 known/absent/unknown 收敛 | C25 规定 dispose 对 `preparing\|prepare_unknown` 只发 inspect、不改状态；C7 只允许 `prepare_unknown→prepare_failed\|installed`（经 inspect），先写 `dispose_pending` 会使 known 后无法合法转 installed，故旧期望在 C25 下不可达 | 旧断言的「零 release」保留，另加「恰一 inspect」与 request 逐键/确定性 id/状态保持；真正的 `dispose_pending` receipt_conflict 改由 G4-K 以 seeded fixture 覆盖，未删断言、未降为零写 |
| A-S5-2 | `s4/test_g2b.py` G2b-C 的 `non_members` 含 `inspect_resource`；G2b-T-1 也以 inspect 作「未打开 kind」代表 | G2b-C `non_members = COMMAND_KINDS + ("fiber_reconcile",)`；G2b-T-1 以 `fiber_reconcile` 为剩余非成员；inspect 的 claim→settle 正例移到 G4-N（6 键形状、target 匹配、ordinal=0、pin NULL） | C18/§5.7 分阶段打开 `claimable_kinds()`；W2 同一提交把 inspect 加入第 5 项并打开 claim+settlement，旧的「inspect 不可 claim」不再是合同 | 仍穷举全部剩余非成员（8 个 command kind + `fiber_reconcile`）且十表零写；inspect 的负例在 G4-N 更严（错键集/错 reservation/已 quiesced/终态/坏 digest/错 id），正例也有真实 claim→settle。覆盖从「一律不可 claim」变为「按冻结形状可 claim、其它形状 W0」 |
| A-S5-3 | `s1/test_g1.py` G1-J2：close 只写 `close_requested_at`（fixture 无 install/run/fiber） | 原断言保留（该 scope 无义务，phase=request）；G4-G 增加有 run/install 的 close，断言 phase 事件序列、`closed_at` 只在 finalize、`child.closed_at < parent.closed_at` | C26 phase 机不改变「request 只写请求时间」；义务为空时无需推进 | 原断言原样保留，新增有义务 fixture，断言只增 |
| A-S5-4 | `s2/test_g3a.py` G3a-F：B off 一次完成 release/close/current 清空（单 slot） | 单 slot 仍一次完成；多 slot 的逐条 DESC 由 G4-D 覆盖（3 条、三次 advance，episode 第三次才 closed） | C24/C27 的「一 advance 一条 contribution」只改变多 slot 的进度，不改变单 slot 终态 | 单 slot 断言未改；多 slot 新证据更严，未删除任何旧断言 |
| A-S5-5 | `s1/test_g1.py` G1-A：DEFINER allowlist 6 个，advance 唯一可写 | 仍 6 个；S5 的 cleanup helper 全部 INVOKER、无 GRANT；`50_permissions.sql` 在 W1–W4 均 0 diff | 计划 §5.1/§5.8 要求 helper 保持 INVOKER，不新增 DEFINER | 断言未动；S5 没有新增可写函数，allowlist 只被复核、未被扩大 |
| A-S5-6 | `s1/test_g1.py` 的 host_prepare claim 正例 | 不变；G4-N 重跑 claim→settle，并追加 inspect 的真实 claim→settle | C18 已允许 host_prepare；S5 不改变 host claim | 原样保留 + 回归重跑；新增 inspect 正例是追加，不是替换 |
| A-S5-7 | `s4/test_g2b.py` G2b-U：`error_v1` 仍接受 23 码 | 不变；`cleanup_cycle` 从「无生产者」变为有生产者，但闭集仍 23 码、逐码接受 | 错误码闭集不因生产者增加而扩；S5 无新码（§5.7） | 23 码逐码接受断言原样保留；生产者增加不减少任何断言 |
| A-S5-8 | `s3/test_g2.py` G2a-11：`claimable_kinds()` 恰 4 项（host_prepare/host_release/model_call/tool_call） | 恰 5 项、顺序固定（追加 `inspect_resource`）；request-less inspect 仍在非成员循环中得 `invalid_args` 十表零写；打印文案同步 | C18/§5.7 冻结 5 项顺序；W2 打开 inspect 的强制结果 | 请求形状循环未动，非成员穷举未减；数组从 4 到 5 是合同增长，不是把某项从负例里删掉——错形状的 inspect 仍是负例（G2a-11 seed 循环 + G4-N） |
| A-S5-9 | `s2/test_g3a.py` G3a-K 的 preparing + ready host_prepare 子段：dispose 写 `dispose_pending`，随后 host_prepare 回执得 `receipt_conflict` | dispose 零后继、保持 `preparing`；host_prepare 回执正常结算为 `installed`（G3a-K）；真正的 `dispose_pending` receipt_conflict 由 G4-K 的 seeded fixture 覆盖（`domain_state` 前后相等、host_prepare 仍 `claimed`） | C25/D-S5-11 要求 preparing 保持原态，ready host_prepare 只阻塞；若先写 `dispose_pending`，回执会与 C7 迁移冲突（A-S5-1 的直接后果） | `receipt_conflict` 没有被删除，只移到合法的 seeded `dispose_pending` 场景（G4-K）；域零写断言更强，旧断言不是被「放宽」而是被合同判定为不可达 |

### 1.7 声明式 S1–S3 断言对齐（不是放宽；S5 收尾时由 §1.5 顺延）

| # | 原断言 | 现断言 | 理由 / 证据 |
|---|---|---|---|
| A-R1 | `test_g2.py:382-384` G2a-1 的 model request 5 key 全等 | C17 全等：旧 5 key + `v/cause/reserve/digests` 逐一断言 | C17 纯追加；信息量增加 |
| A-R2 | `test_g2.py:895-897` G2a-7 steer successor request 5 key | C17 全等 + `cause='steer'` | 同 A-R1 |
| A-R3 | `test_g2.py:1089-1091` G2a-8 respond successor request 5 key | C17 全等 + `cause='respond'` | 同 A-R1 |
| A-R4 | `test_g2.py:567-602` G2a-11 硬编码“仅 host 两 kind 可 claim” | 先断言 `v24.claimable_kinds()` 等于阶段冻结集（host+model+tool），再穷举全部非成员仍 `invalid_args` 零写；`host_prepare` 正例保留 | 覆盖面对“非成员 kind”仍穷举，且把 allowlist 变成可断言对象；**加强** |
| A-R5 | `test_g2.py:356-359`、`:494` start 后 `remaining_* == budget.*` | `steps-1`、`tokens - model_reserve(tokens)`（如 1234→0、7→6）；tool_calls/wall 不变 | F3=A admission 预扣；仍是对派生值的精确相等 |
| A-R6 | `test_g2.py:409` seed model 撞 23505 的探针 | 在已有 ready model 的 run 上保留探针 | 语义不变，构造更贴近真实 |
| A-R7 | `test_g1.py` G1-Q 的 unsupported 代表 | 改为 `inspect_resource`（settlement 仍归 S5） | `test_g1.py:380-381`；代表 kind 与 S4 边界一致 |
| D-S4-3 | S3 G2a-7/G2a-8 的终端循环期望 `already_terminal` | `blocked_unknown` 优先；其它 terminal 断言保留 | 新状态在 S3 不存在，故无旧断言被误伤；`blocked_unknown` 是 S4 的明确优先级 |
| — | S3 把 `interaction_mismatch` 记为 W0 | S4 更正为 **W1**：领域零写 + 一条 failed `command_respond` effect 与其 request receipt | `G2b-I/consumed` 的 `assert_respond_mismatch_w1`；矩阵 §3.1 已改 |

### 1.8 R6 规格修订（2026-10-24；D-R6-1/2 规格层，D-R6-3/4 已实施）

以下四条是 **Oracle 批准的规格修订**，不是实现偏差。D-R6-1/2 仍为规格层；**D-R6-3/4 已由 S6 W1–W4 实施，并由 G5 的 K1–K10 证明**。

| # | 修订 | 设计稿位置 | 采用 | 状态 |
|---|---|---|---|---|
| D-R6-1 | O7 kill 点数不一致：§9 说「7 个 kill 点」，§8 列十行 | §9 G5 行、§8 | §8 十行为权威；§9 行内改为「10 个 kill 点（§8 十行；附录 C.1）」 | Oracle R6 Q1=A；spec revision approved；S6 未改变该规格（G5 仍按 §8 十行） |
| D-R6-2 | spawn/child run 无阶段归属（原计划排到 S5/S6 之后） | §5.5；pre-plan §0/§2.3/§3 | 新增阶段 S8 + gate G7；顺序 S6 → S8 → S7；S7 仍最终验收 | Oracle R6 Q2=A；spec revision approved；**S8/G7 已实施（S8 W1–W3，G7 通过）**；**S7/G6 已完成（S7 W1–W2，30 ID；11/11）** |
| D-R6-3 | 过期 claim 无统一收敛入口、恢复读面 ACL 未定义 | 附录 C.3 | 新增 `command_recover(scope)`（INVOKER wrapper）+ `recoverable_effects(scope)`（只读 `STABLE` DEFINER 发现面，owner `v24_owner`、固定 `search_path`、零 DML）：G 下扫过期 claim，`replay_policy` 分流，≤16 一批、一个事务；所有写经 `advance`；协议角色零表权；无第二状态机 | Oracle R6 Q3=B / Q3a=A；**S6 W1–W4 已实施，G5 通过**（`49_recovery.sql`、`10_schema.sql`、`50_permissions.sql`；K1–K10） |
| D-R6-4 | G5 重启证据不足：同进程新连接不能证明崩溃恢复 | §9.1；附录 C.1 | 每个 kill 点独立 OS 子进程 + 持久 journal；父进程重启仅用 resolve + 未结算 effect 收敛 | Oracle R6 Q4=A；**S6 W1–W4 已实施，G5 通过**（`v24/s6/*`；K1–K10 独立 OS 子进程 + JSONL/journal） |

### 1.9 S6 裁决与偏差（D-S6-1…12、CC-1…3）

S6 的 12 条 D-S6 与 3 条 CC 均为 Oracle `028D07` 的 15 项 ACCEPT；下表按**实际代码与 gate 证据**记录落位。性质列区分「裁决」（合同已批准，实现细化）与「合同变更」（kind/entity/response 形状变化）。

| # | 设计/附录原文 → 不足 | 采用（代码位置） | 证据 | 性质 |
|---|---|---|---|---|
| **D-S6-1** | C.3 L711「确定序 `(claimed_at, effect_id)`」→ `effects` 没有 `claimed_at` 列（只有 `created_at/settled_at/lease_until`），照写会引用不存在的列 | 改用 `(lease_until, effect_id)`，不新增列；`49_recovery.sql` 的 `recoverable_effects` 按此 `ORDER BY` | `[G5-D2]` 同 lease 下 UUID 升序 `b2,c3,a1,d4`；`[G5-D6]` 读前后十表快照不变 | 裁决 |
| **D-S6-2** | C.3 L710–712「先把每个 recovery 动作经 `advance` 提交」→ 字面是 N 次 `advance` = N 条 request/effect，无法满足「一次 sweep 一个 request/receipt」与 sweep 级 `has_more` 出处 | 一次 `advance` + `command_recover` kind；`interpret_recover` 在 G 下重发现并返回一个 delta（≤16 动作）。`30_advance.sql` allowlist/candidate closure；`49_recovery.sql` wrapper/interpreter；`40_interpreters.sql` dispatcher/footprint/applier | `[G5-K2]` 两个动作同一 delta；`[G5-K5] requests=1`；`[G5-W2] has_more=True->False` | 裁决 + 合同变更（D-S6-2/CC-1） |
| **D-S6-3** | C.3 L713 只提 `replay_safe`/`no_replay`，未提 `manual` → manual 若进入扫描会占用 16 上界并让 `has_more` 恒 true；自动处理又违反 B.4 L572 | 发现面 `WHERE replay_policy <> 'manual'`；`manual_debt` 只读计数，不写、不占上界。`49_recovery.sql` 的 `recoverable_effects` 与 `interpret_recover` 第 6 步 | `[G5-D4]` manual 被排除、replay_safe 返回；`[G5-K3] manual=16/0 has_more=False` | 裁决 |
| **D-S6-4** | C.3 L713「`replay_safe` 作为新的 ready attempt（新 attempt/fence）」→ recovery 自己 bump 会成为第二个 claim 写者，与 B.4 L560 冲突 | reset 只清 `claim_owner/lease_until`，保留 `attempt_no/fence`；下一次普通 claim 递增。`49_recovery.sql` 的 reset delta；`30_advance.sql` 既有 claim 路径 | `[G5-K2]` reset 后普通 claim `journal_attempt/fence=2/2`；`[G5-K3] reservation=1` | 裁决 |
| **D-S6-5** | C.3 L710 `command_recover(p_scope, p_limit DEFAULT 16)` → 追加 `p_request_key` 后默认参数后跟必填参数，PostgreSQL 不可执行 | 冻结为 `(p_scope uuid, p_request_key text, p_limit integer DEFAULT 16)`；`49_recovery.sql` | `[G5-K2]`/`[G5-K5]` 真实调用；`[G5-W2]` 同 key 异 limit 得 `request_conflict` | 裁决（签名修正） |
| **D-S6-6** | C.3 L710 只说「scope auth」，未定义谓词 → 无法写 gate，也无法防越权读 | `scopes.owner_principal = principal_id(session_user)` 或 `pg_has_role(session_user,'v24_admin','USAGE')`；发现面不匹配 0 行，命令不匹配 `not_found_or_denied` W0。`49_recovery.sql` | `[G5-D5]` service 对 admin scope 0 行；`[G5-W2] service=not_found_or_denied-w0` | 裁决 |
| **D-S6-7** | B.4 L566「记录 host journal 引用并将 effect 标为 unknown」→ `receipt_conflict` 的 DB `detail` 恒 `{}`，既有 gate 精确断言，DB 不能凭空填 host 路径 | `detail` 保持 `{}`；journal 引用由 JSONL 的 `(effect_id,attempt,fence,reservation)` 记录并打印路径；`30_advance.sql` 终态分支不变 | `[G5-K3] late=receipt_conflict-w0`、journal `K3.jsonl` | 裁决 |
| **D-S6-8** | C.3 L714「`has_more` 只是提示，不是 cursor/queue/job」→ 未定义计算口径，易落库或误算 | `has_more` = 同 scope 内非 manual、claimed、过期、且不在本次 applied 的 effect 存在；每次重算、不持久化。`49_recovery.sql` 第 6 步 | `[G5-W2] has_more=True->False`（limit=1 后新 key）；`[G5-K3]` manual 不使其恒真 | 裁决 |
| **D-S6-9** | C.3 L710–714 未定义收敛后同 key 重放 → 候选进 digest 会使丢应答重试变 `request_conflict`；不进 digest 又需说明同 key 不同候选 | canonical bytes 只含 `{v,scope_id,limit}`；`candidates` 仅 body 元数据；同 key 异 scope/limit `request_conflict`；重复 sweep 用新 key。`49_recovery.sql` wrapper/interpreter；`40_interpreters.sql` request response | `[G5-K5]` canonical sha `24ee41a8a7689533dc541087667ce76631460048c260eaed04e8ffc519aee18c`、三次 response 均 `17d16f00fd32997b76938d630ba78fc55251f91e0a2f46be245262ca39de35b6`/523B、`byte_equal=true`；`[G5-W2] candidates_replay=True conflict_limit=request_conflict` | 裁决 + 合同变更（D-S6-9/CC-2） |
| **D-S6-10** | C.3 L711「`LIMIT <= 16`」→ 未定义 `NULL`/0/负/>16 | wrapper 对 `NULL`/<1/>16 返回 `invalid_args` W0；发现面 `NULL`/<1→0 行、>16→16。`49_recovery.sql` | `[G5-D3]` `NULL/0/-7/17/16 -> 0/0/0/16/16` 行；`[G5-W2] limits=invalid_args-w0` | 裁决 |
| **D-S6-11** | §3.1.9 L176 的 `entity_type` 未给闭集；`10_schema.sql:241` 实际闭集不含 `effect` → 逐 action 的 recovery 事件没有合法 entity_type | `c_events_entity` 增加 `effect`；逐 action 事件 `entity_type='effect'`、`entity_id=target effect_id`。`10_schema.sql`；`49_recovery.sql` 事件 | `[G5-K2]`/`[G5-K3]` 的 effect 事件；`test_ddl.py` 的 `effect` 正例与 `bogus` 负例 | 合同变更（D-S6-11/CC-1b） |
| **D-S6-12** | C.3 未说明 closed scope 上调用 `command_recover` 的行为 → 实现可能误用 `scope_closed` 或拒绝清理债务 | 不新增 closed-scope 拒绝；无候选即 noop；不用 `scope_closed` 阻断恢复。`49_recovery.sql` 只校验存在性/owner，无 `closed_at` 分支 | `[G5-K9]` 覆盖 closing scope 的 close/恢复阶段；**未单独构造 closed-scope 非空候选**（边界见 `v24/s6/README.md` §7） | 裁决（最小行为） |
| **CC-1** | C.3 L710–712 + §3.1.3/§A.1 + §3.1.9：无 `command_recover` kind、无 `effect` entity → 新命令与逐 action 出处无合法行 | 新增 `command_recover` kind + `events.entity_type='effect'`；接线 `10_schema.sql`、`30_advance.sql` allowlist/closure、`40_interpreters.sql` dispatcher/footprint/applier、`50_permissions.sql` wrapper 合同、`test_g1.py`/`test_ddl.py`/`test_g2.py`/`test_g2b.py` | `[G5-K4]`/`[G5-K5]` 的 command_recover 行与 effect 事件；G1-A/G2a-11/G2b-C/DDL 全绿（8 既有 gate） | 合同变更（CC-1，028D07） |
| **CC-2** | C.3 未定 `candidates` 是否进 `canonical_bytes`/digest → 进则 commit 丢应答后的重试必 `request_conflict`，wrapper 自身无法 replay | `candidates` 不进 canonical bytes/digest；只作 `body` 元数据；解释器在 G 下重发现。`49_recovery.sql`；`30_advance.sql` 既有 canonical bytes 校验 | `[G5-K5]` 三次 response 字节相等、`requests=1`、`second_replay_zero_write=true`；`[G5-W2] candidates_replay=True` | 合同变更（CC-2，028D07） |
| **CC-3** | 标准 envelope 无处返回 sweep 的 `applied/skipped/manual_debt/has_more` → Done when 5 无法直接断言 | response 增加 `recovery:{scope_id,limit,candidates,applied,skipped,manual_debt,has_more}`；`49_recovery.sql` 的 `v_response`；`40_interpreters.sql` request response | `[G5-K2]` applied/has_more；`[G5-K3]` applied/skipped/manual_debt；`[G5-K5]` recovery envelope 重放 | 合同变更（CC-3，028D07） |

### 1.10 S6 声明式断言对齐（A-S6-1…9，不是放宽）

S6 对既有 gate 的改动只增不减：ACL 闭集、command kind 数组和 DDL 正负例都随 CC-1 扩大；K3 的 cancel-late 子断言与打印口径不新增窗口。下表按实际 diff 记录。

| # | 原断言（S1–S5） | 现断言（S6） | 冻结合同为何强制 | 不是削弱 |
|---|---|---|---|---|
| **A-S6-1** | `s1/test_g1.py` G1-A：`read_definers` 5 项（`resolve`/`run_owner`/`run_projection`/`poll`/`wait_check`）；`prosecdef=true` 恰为 `{advance}` ∪ 5 | 加 `recoverable_effects`，共 6 个只读 DEFINER；`50_permissions.sql` 的 DEFINER allowlist 数组同步加入 | C28 要求只读发现面能读 `effects`，而三个协议角色零表权，必须 DEFINER；G1-A 必须穷举每个 DEFINER | 新增的是 `STABLE`、零 DML、固定 `search_path`、无 advisory 的只读函数；`advance` 仍是唯一可写 DEFINER；PUBLIC 仍无 EXECUTE |
| **A-S6-2** | `test_g1.py` 的 wrapper 元组 6 项：`scope_control`/`install`/`start`/`cancel`/`steer`/`respond` | 7 项，追加 `command_recover`；仍断言 INVOKER、含 `v24.advance(`、不含 `INSERT INTO`/`UPDATE v24.`/`DELETE FROM`/`pg_advisory_xact_lock` | C29/CC-1 规定 `command_recover` 是唯一恢复命令入口，恰好一次 `advance` | 新 wrapper 无表权、无直接写、无 advisory lock；旧 6 项断言原样保留 |
| **A-S6-3** | `test_g1.py` 的 G1-P 逐角色 EXECUTE 期望集合不含两个新函数 | 期望集合加入 `recoverable_effects`/`command_recover`；三角色逐角色精确断言不变 | C28/C29 要求三个协议角色可调用发现面与恢复命令 | ACL 闭集增长而非放开：PUBLIC 无 EXECUTE、表 DML 仍全 `42501`、非成员函数仍不可调用 |
| **A-S6-4** | `s3/test_g2.py` G2a-11：`command_kinds` 8 项、`len==8` | 9 项、`len==9`，追加 `command_recover`；仍逐项断言 claim 得 `invalid_args` + 十表零写 | CC-1 新增 command kind；`claimable_kinds()` 仍恰 5 项 | 循环仍穷举每个 command kind；新增项只扩大覆盖，未删除任何非成员 |
| **A-S6-5** | `s4/test_g2b.py` 的 `COMMAND_KINDS` 8 项、`len==8`；`non_members=COMMAND_KINDS+("fiber_reconcile",)` | 9 项、`len==9`；`non_members` 同步扩到 10 项；`inspect_resource` 仍是第 5 个可 claim kind | 同步 kind 闭集；C18 的 claimable 5 项不因新 command kind 改变 | 每个非成员仍 `invalid_args` 十表零写；inspect 真实 claim→settle 正例仍在 G4-N |
| **A-S6-6** | `s1/test_ddl.py` 的 command claim 循环只有 `command_scope_control`/`command_install`；无 `command_recover` 正例/`effect` entity 正例 | 循环加入 `command_recover`（`attempt_no=1` 仍被 `c_effects_command_claim` 拒绝）；新增 `command_recover` `attempt_no=0` 正例、`events.entity_type='effect'` 正例、`bogus` entity 负例；正例放在 savepoint 内，避免 deferred event FK 影响后续 TRUNCATE 探针 | CC-1/CC-1b 要求 kind 与 entity 闭集同时容纳新命令/出处 | 负例、正例都增加；`bogus` 仍被 `c_events_entity` 拒绝；无表/视图断言变化 |
| **A-S6-7** | 计划未把 wrapper 的 `candidates` 冻结为纯 hint；`has_more` 无计算口径 | 解释器只处理 `body.candidates`；hint 之外新过期的行本次不处理，只让 `has_more=true` 留给下一个 key；无 cursor/queue/table。`[G5-W2]` 合同套件断言 `has_more=True->False` | D-S6-8/CC-2：候选集不进 digest，权威集合必须在 G 下重读；否则丢应答重试会 `request_conflict` | 没有放宽授权集合：G 下仍按 `(lease_until,effect_id)` 重读并对已结算/未过期行记 `skipped`；不持久化任何状态，下一 key 重新发现 |
| **A-S6-8** | K3 原有 host_prepare 重投 + model_call unknown 证据；无 cancel-late 子断言 | K3 追加：cancel seal 列逐字节保留、只发 `model_call_unknown(late=true)`、pin 由正在结算的 effect 释放；`[G5-control]` 打印归一化对照；不新增/改名窗口 | D4/§B.5 的 cancel-late 语义要求 unknown 不洗白取消事实；控制对照证明 recovery-unknown 与正常 unknown 同形 | 原 K3 断言全部保留，只追加子断言；K 窗口仍为 K1–K10，未新增 K11 或改名 |
| **A-S6-9** | W1–W3 每个窗口先打印 `[G5-Kn] journal=...`，再打印汇总行，导致同一 tag 出现两次；K3 控制行也用 `[G5-K3]` | 每个窗口恰打印一行 `[G5-Kn]`，journal 并入最终行；K3 控制行改 tag 为 `[G5-control]`；无参数全量 gate 复跑 | 收尾证据要求「`[G5-K1]`…`[G5-K10]` 各恰一次」，重复 tag 会让证据计数歧义 | 只改 print 与 tag，不改任何断言、窗口或失败条件；断言集与通过条件不变 |

### 1.11 S6 W1–W3 实施披露（非新增规格）

| 项 | 实际选择 | 状态/边界 |
|---|---|---|
| **(a) W1 guard 后移除** | W1 的 `50_permissions.sql` 块曾为尚不存在的 `command_recover` 加存在性 guard；W2 落地函数后删除 guard，改为直接 GRANT + DEFINER allowlist + wrapper 合同。**当前 SQL 没有 guard** | 历史实施顺序，不是当前合同；当前 `50_permissions.sql` 的 GRANT/allowlist 与 `test_g1.py` 的期望集合一致 |
| **(b) G1-P EXECUTABLE 增项** | `recoverable_effects`/`command_recover` 加入三角色期望 EXECUTE 集合 | ACL 闭集增长，不是放宽：PUBLIC 仍无 EXECUTE，协议角色仍零表权；见 A-S6-3 |
| **(c) W2 最小 no_replay 被 W3 取代** | W2 只把 effect 结算为 unknown；W3 新增 `unknown_wall_delta`，补齐 run/pin/预算/interaction/install 收敛与 `[G5-control]` 对照 | 旧断言保留并加强：K2 的 unknown 证据仍在，K3 追加控制对照；没有删除 W2 的 effect 级断言 |
| **(d) W3 `has_more` hint + cancel-late 子断言** | `has_more` 只处理 wrapper hint 内的候选；cancel-late 只在 K3 内加子断言 | 见 A-S6-7/A-S6-8。有界：每次最多处理 hint 内 ≤16 行；安全：G 下按 `(lease_until,effect_id)` 重读，hint 外新过期的行只置 `has_more=true` 留给下一 key，不落 cursor/queue/table；cancel-late 只加 K3 子断言，不新增窗口 |



### 1.12 S8 裁决与偏差（D-S8-1…12）

S8 的 12 条 D-S8 中，D-S8-1…8 是 R7 Q1–Q7 与计划 §7 的冻结裁决；**D-S8-9/10 来自 W1 Oracle BLOCK** 后的 token/wall 规格修订；**D-S8-11 来自 W2 的物理列/摘要事实修正，并由 Oracle `028D07` 于 2026-10-24 批准**；**D-S8-12 是 W3 评审发现的 owner run pin 误绑 child 首 `model_call` 的产品缺陷，在 closeout 前修复**。代码位置按实际文件与函数记录，不虚构行号。`23 码` 在 D1–D14、§1.6 的 A-S5-7 与 §1.9 中是 S1/S6 时点状态；S8/R7 后当前闭集为 **24**，以 D-S8-1、§1.13 A-S8-1 与 G1-A 为准。

| # | 设计/计划原文 → 不足 | 采用（代码位置） | 证据 | 性质 |
|---|---|---|---|---|
| **D-S8-1** | 设计 §B.3/§5.5 的 23 码闭集没有 spawn 专用冲突码；同 `(parent_run_id,spawn_key)` 异 canonical bytes 无合法错误可返回 | `30_advance.sql` 的 `error_v1` 闭集加入第 24 码 `spawn_key_conflict`；`48_loop.sql` 的 `interpret_model_settlement` 在既有 child 的 `spawn_request_digest` 不相等时、任何 DML 之前返回该码 | `G7-C` 同 key 异 bytes（不同 request_key）得 24 码、十表 byte-equal、model effect 仍 `claimed`；`G7-N2` 的随后新父 outcome 携带败者 bytes 同样 W0；`G1-A` 的 `codes` 为 24、逐码接受 | 合同变更（R7 Q1=A） |
| **D-S8-2** | C19 把 `tool_calls[]` 每项当 tool：计入 `max_tool_calls`/`v_n_tools` 并做 pin 成员检查；`agent.spawn` 会被误判为无 pin 的 tool | `48_loop.sql` 的 `interpret_model_settlement` 在 C19.0 先识别 `key='agent.spawn'`：不计 tool、不进 `v_n_tools`、跳过 pin 循环；`v_spawn_count<=1`；spawn 与普通 tool/final/interaction 互斥；spawn 不是 effect。`validate_and_apply_loop_delta` 拒绝没有 `spawn` handle 回显的 spawn outcome | `G7-A` spawn 在同一 advance 成功建 child；`G7-E` child 是 run、无 fiber/install；`G7-F` 无新表/无 socket、journal 0 行；`G7-H` 非法/越界/owner/terminal 五类 W0；`G7-C` 冲突时 model effect 仍 claimed | 合同变更（R7 Q2=A） |
| **D-S8-3** | C17 的 cause 闭集为 `start\|steer\|respond\|continuation`；spawn 的首 model 无合法 cause/request 形状 | `30_advance.sql` 的 model request 校验把 cause 扩为 `start\|steer\|respond\|continuation\|spawn`，spawn 请求键集为 `input/spawn_key/parent_run_id`，并校验父 effect 为 `model_call`、`parent_run_id` 指向父 run、child effect 为确定性 id、child run 的 parent/scope/key/status 匹配；`48_loop.sql` 写 child request 的 `cause='spawn'` | `G7-A`/`G7-G` 的 child request `cause='spawn'`、`parent_effect_id` 指向父 model、`spawn_key`/`parent_run_id` 正确；`G7-B`/`G7-H` 的 replay 与 W0 分支 | 合同变更（R7 Q3=A） |
| **D-S8-4** | Q4 只说“child quota 四项”；`tokens` 的 NULL 规则、child 初始值与首 model reservation 的关系未冻结，四种配额是否统一扣减也未写 | `48_loop.sql` 的 spawn args 校验要求 `budget` 四键齐全、`steps/tool_calls/wall_ms` 为正整数、`tokens` 为正整数或 JSON null 且仅当父 `remaining_tokens IS NULL`；父 finite + child null 在 args 阶段 `invalid_outcome`；四项统一对 post-settlement 余额检查并扣减；`remaining_tokens = grant - model_reserve(grant)`（null 保持 null） | `G7-D finite`（grant=300/reserve=300/child_remaining=0）与 `G7-D NULL`（父子 null、reserve=0、steps/tool_calls/wall 守恒）；`G7-H` 的 `invalid_outcome`/`budget_exceeded`；`G7-A` 的 steps/tool_calls/wall 等式 | 裁决（Q4=A；D-S8-9/10 细化） |
| **D-S8-5** | Q5 只写 owner pair 可选；未冻结成对规则、live activation pin 唯一性、child run pin 的 provider 元组来源与失败码 | `48_loop.sql` 的 `interpret_model_settlement` 与 `validate_and_apply_loop_delta`：owner pair 同时有/无；fiber `want_on=true` 且 `current_episode_id=owner_episode`；episode `active`；install `installed`；同 `(consumer_episode_id,consumer_epoch)` **恰一条** live activation pin；child run pin 取该 activation 的 slot/provider 三列与 `descriptor_digest`；0/>1 条 activation pin → `dependency_unresolved`，fiber/episode 不 active → `provider_unavailable` | `G7-E` ownerless child 无 pin；`G7-N5` owner-pin 故障回滚 child/pin/quota/events；`G7-N7` child 有 owner pair 和一条 run pin、不是 fiber/install；`G7-G` child pin 随 recovery 释放；`G7-H` 的 `dependency_unresolved`/`provider_unavailable` | 裁决（Q5=A）+ D-S8-11 物理映射 |
| **D-S8-6** | 设计 §2.1 的 model settlement 六键 envelope 冻结；Q7 要加可选 `spawned`，但未定义其与 replay/六键的关系 | `48_loop.sql` 的 interpreter 返回 `spawn` handle，`validate_and_apply_loop_delta` 从存储 child 行独立重算 fresh/replay 并校验；`v_response` 仅对 spawn settlement 追加 `spawned:[{run_id,spawn_key,child_effect_id,replayed}]`，其余仍六键；fresh `replayed=false`，新父 outcome 复用 child `true` | `G7-A`/`G7-B` 的 `set(response)==OWNER_KEYS\|{'spawned'}`；`G7-B` 新父 outcome `replayed=true`；`G7-B`/`G7-N6` 同 effect 同 bytes 的 `advance` receipt replay 等于冻结六键信封且零写；G1-R 未改 | 合同变更（R7 Q7=A）+ D-S8-11 `replayed` 两义 |
| **D-S8-7** | v1 未限制一个 outcome 的 spawn 数，也未禁止 spawn 与普通 tool/final/interaction 混用 | `48_loop.sql` 的 C19 分流：`v_spawn_count<=1`；spawn 存在时 `tool_calls` 长度必须为 1；spawn 与 `final`/`interaction` 互斥；违反者为 `invalid_outcome` W0（DML 之前） | 代码路径在 `48_loop.sql` 的 `v_spawn_count`/`tool_calls` 长度检查；`G7-H` 的 `invalid_outcome` 类覆盖非法 args、`G7-C` 冲突 W0；**没有专门的多 spawn/混用 fixture**（边界披露，不声称 G7 已单独构造该路径） | 裁决（v1 限制；Q2=A / 计划 §4.1） |
| **D-S8-8** | 计划 §7 把 `spawn_key_conflict` 的写类列为待决；若必须 W1，会留下 failed receipt/半状态 | 定为 **W0**：digest 冲突在 domain 写前返回；model effect 保持 `claimed`，无 child/edge/quota/event/effect | `G7-C` 十表逐字节相等、effect 仍 `claimed`；`G7-N2` 随后的新父 outcome 同样 W0；`G7-H` 的 W0 类同形 | 裁决（Q1=A；计划 §4.0） |
| **D-S8-9** | Q4 的“child 首 reservation 含在 child 初始 quota”可被实现成：child 初始 = grant、父扣 grant、首 model 再从 child 余额/父余额预留 → child 余额出现 `2*grant-usage` | **W1 Oracle BLOCK 后的修订**：`v_child_reserve := coalesce(v24.model_reserve(v_child_tokens),0)`；child `remaining_tokens = grant - v_child_reserve`（grant null → null）；父从 post-C19-refund 的 `v_tokens` 扣**完整 grant**；`validate_and_apply_loop_delta` 独立重算 `v_post_tokens`，要求 child reserve=`model_reserve(grant)`、父 `remaining_tokens = v_post_tokens - grant` | `G7-D finite` 断言 grant=300 reserve=300 child_remaining=0、`child_remaining+reserve=grant`、父从 post-refund `v_tokens` 扣完整 grant；`G7-B` 新父 outcome replay 不再二次扣 grant；`G7-N1` 并发同 bytes 只扣一次。`child 成功结算只返还 reserve-usage` 是 C.6 的合同结论；G7 未单独结算该 child（边界） | **合同修订（W1 Oracle BLOCK）**；设计 C.6 D-S8-9 |
| **D-S8-10** | Q4 的“child wall ≤ parent remaining_wall_ms”按原始余额检查，忽略父 model effect 已消耗的 elapsed；验收时无法守恒 | **W1 Oracle BLOCK 后的修订**：令 `elapsed=(now()-父 model effect.created_at)` 毫秒、`v_wall=greatest(0,remaining_wall_ms-elapsed)`；child wall ≤ `v_wall`；成功后 `remaining_wall_ms=greatest(0,v_wall-child_wall)`；守恒 `Q_parent_before - elapsed = Q_parent_after + child_wall`；applier 用同一 elapsed/`v_wall` 重算 | `G7-D finite` 的 `wall_elapsed=22 wall_after=592978`；`G7-D NULL` 的 steps/tool_calls/wall 守恒；`G7-A` 的 `before - elapsed = after + child` 精确等式 | **合同修订（W1 Oracle BLOCK）**；设计 C.6 D-S8-10 |
| **D-S8-11** | 计划 §4.6 写 run pin 的 `consumer_episode_id=owner_episode`，与 `c_pins_xor`（run pin 的 episode 必须 NULL）冲突；`model_digests(child)` 看不到尚未插入的 pin；`replayed` 同时被用来指“新父 outcome 复用 child”和 receipt replay | **W2 事实修正 + Oracle `028D07` 于 2026-10-24 批准**：run pin 存为 `consumer_type='run'`、`consumer_run_id=child`、**`consumer_episode_id=NULL`**、`consumer_epoch=owner_episode.epoch`，owner episode 由 child run 的 `owner_episode_id` 承载；要求恰一条 live activation pin（0/>1 → `dependency_unresolved`）；child 首 model 的 `toolset` 按**预期 run pin 的单元素数组**、同 key/hex 序计算，settlement 后与 `v24.model_digests(child)` 逐字节相同；同 effect 同 bytes 的 receipt replay 用 S2/S4 冻结六键信封（**无 `spawned`**），`replayed:true` 只用于新父 outcome | `G7-E`/`G7-N7` 的 child run pin `consumer_episode_id=NULL`、owner pair 在 child 行；`G7-A`/`G7-D`/`G7-N7` 的 `assert_child_run` 断言 `request.digests == v24.model_digests(child)`、toolset 逐字节；`G7-G` 断言 child pin 随 recovery 释放；`G7-B`/`G7-N6` 的 receipt replay 精确等于冻结信封且零写；`G7-N2` 的 `receipt_conflict`/随后 `spawn_key_conflict` 分工 | **事实修正 + Oracle 批准（W2）**；设计 C.6 D-S8-11 |
| **D-S8-12** | 设计/实现最初把 owner run pin id 绑到 child 首 `model_call` 的 `effects.pin_id`；但 `effects.pin_id` 只供真正消费 pin 的 `tool_call` 使用，`model_call` 必须恒为 NULL。公共 claim 门（`30_advance.sql` 的 model claim 校验）与 `48_loop.sql` 的 settlement 守卫都会拒绝任何带 pin 的 model_call，因此 owner-pinned child 的首 model 无法经公共路径 claim/settle；旧 G7-G 的 seeded claim 掩盖了该缺陷 | **W3 评审发现并在收尾前修复**：`48_loop.sql` 的 child 首 `model_call` 插入 `'pin_id',NULL`；owner run pin 仍为独立 `v24.pins` 行（`consumer_type='run'`、`consumer_run_id=child`、`consumer_episode_id=NULL`、`consumer_epoch=owner_episode.epoch`、`key='run'`、provider tuple/digest 与 `created_by_effect` 不变）；applier 改为单条件要求 `v_child_effect.pin_id IS NULL`，同时仍校验恰一条 run pin 行的 consumer/epoch/key/provider tuple/digest/`created_by_effect`；claim 与 settlement 的 pin 守卫不放松 | `G7-G` 在 `pin_id=NULL` 的 owner-pinned child 首 model 上走真实公共 claim，得 `attempt/fence=1/1`（service login owner）；随后 `expire_claim` 使 lease 过期，`v24.command_recover` 结算 `unknown`、child `blocked_unknown`、spawn edge/child 计数/父 quota 不变、run pin 释放；无 seeded claim；G7 全绿、十门 10/10 | **产品缺陷（W3 评审发现，closeout 前修复）**；无新对象/新错误码；设计语义不变，只纠正 effect 与 pin 的绑定 |

### 1.13 S8 声明式断言对齐（A-S8-1…6，不是放宽）

S8 对既有 gate 的测试代码改动只有 `v24/s1/test_g1.py` 的 G1-A 23→24；其余是既有断言口径的澄清、G7 新 gate 的精确断言，以及打印 tag 的去重。W3 另按 D-S8-12 修产品 SQL `v24/sql/48_loop.sql`（child 首 model `pin_id=NULL` + applier 要求 child effect `pin_id IS NULL`），不改既有 gate 的断言口径。下表按实际 diff/代码记录，每条说明为何不是削弱。

| # | 原断言（S1–S7） | 现断言（S8） | 冻结合同为何强制 | 不是削弱 |
|---|---|---|---|---|
| **A-S8-1** | `s1/test_g1.py` G1-A 的 `codes` 为 23 项，`assert len(codes)==23`；未知码 `22023` | `codes` 追加 `spawn_key_conflict`，`assert len(codes)==24`；仍逐码 `error_v1` 接受、未知码仍 `22023` | R7 Q1=A 要求第 24 码进入闭集；G1-A 是全局闭集的权威断言 | 只增加一个码，未删除任何既有码；`22023` 负例保留；G1-A 与 G2b-U/G4-N 的历史子集分工见 A-S8-3 |
| **A-S8-2** | G1-R/`expect_envelope` 要求所有响应恰六键 `{v,disposition,effect_id,emitted,revision,claim}`；model settlement 无 `spawned` | 非 spawn 分支仍恰六键；spawn settlement 为六键 + 可选 `spawned`，由 `G7-A`/`G7-B` 断言 `set(response)==OWNER_KEYS\|{'spawned'}`；`G7-B` 的同 effect receipt replay 仍为冻结六键 | R7 Q7=A 把 `spawned` 定为六键外的唯一可选成员；applier 从 child 行独立重算，不能信任回显 | 六键全部保留且逐一被断言；`spawned` 只在 spawn 路径出现，receipt replay 明确无 `spawned`；G1-R 没有被改写为宽松集合 |
| **A-S8-3** | `s4/test_g2b.py` G2b-U 与 `s5/test_g4.py` G4-N 各自有 23 项 `ERROR_CODES`/`codes` 列表与 `len==23`（S4/S5 回归面） | 两个 gate **保持原 23 项列表与 `len==23` 不变**；文档把它们读作“历史 23 码子集”，不把 `len==23` 升级为全局闭集；全局 24 码由 G1-A 断言 | 这两个 gate 是 S4/S5 的回归面，构造时错误码集就是 23；S8 只新增第 24 码，不能要求历史 gate 冒充全局闭包 | 它们仍逐码接受各自的 23 项（G2b-U 另有未知码 `22023` 断言）；新增的 `spawn_key_conflict` 由 G1-A（接受）与 G7-C/N2（产生）覆盖；没有删除或弱化任何既有码 |
| **A-S8-4** | `v24/s8/test_g7.py` 的 W1/W2 版本在 N1/N2 先打印 `[G7-N1]`/`[G7-N2]` 锁证据，再打印同 tag 结果行，导致同一 tag 出现两次 | 锁证据行改 tag 为 `[G7-N1-lock]`/`[G7-N2-lock]`；结果行保留 `[G7-N1]`/`[G7-N2]`，每个结果 tag 恰一次 | W3 收尾要求 `[G7-N1]`…`[G7-N7]` 各恰一次；重复 tag 使证据计数歧义 | 只改 tag/print；`serialized_race` 的 `pg_blocking_pids()`、未授予 advisory lock、`idle in transaction` 断言原样保留；N1/N2 的 child/quota/replay 断言未动 |
| **A-S8-5** | G7-G 不存在；S6 G5 的 `seed_claim` 用 owner DML 预置 claimed 行，公共恢复入口处理 | G7-G 不再 seed claim：owner-pinned child 首 model 的 `model_call.pin_id=NULL`，用真实公共 `claim_effect` 取得 `attempt=1/fence=1`（service login owner），随即 `expire_claim` 令 lease 过期，再只调用真实公共 `v24.command_recover`；断言 effect→unknown（`reason=lease_expired`、`observed=unknown`）、child run→`blocked_unknown`、`ended_at` 设置、`interaction/pending_steer` 清空、spawn edge 三列/child 计数/父 run 行逐字节不变、run pin 释放且 `released_by_effect`=child effect | D-S8-12：`effects.pin_id` 只用于 tool_call；child model 带 run pin 会被公共 claim 门（`invalid_args`）与 settlement 守卫拒绝。修复后 model `pin_id=NULL`、run pin 为独立 `pins` 行，G7-G 必须验证真实 claim 路径，seed claim 会再次掩盖该缺陷 | 断言只增不减：原恢复收敛断言全部保留，另新增 `pin_id=NULL`、真实 claim token `attempt/fence=1/1`、claim owner 与 service login 一致、lease 过期先于 recovery；不再有 seeded claim 或残余 claim 路径债务 |
| **A-S8-6** | S2/S4 冻结 receipt replay 为六键 `{v,disposition:'replay',effect_id,emitted:[],revision:0,claim:null}`；旧 gate 未涉及 spawn | G7-B 断言新父 outcome 复用既有 child 时返回六键 + `spawned`（`replayed=true`）；同 effect 同 bytes 的 `advance` 重放断言精确等于上述冻结六键信封且十表零写；G7-N1/N6 同形 | D-S8-11 的两义要求把“新父 outcome replay”和“receipt replay”分开，否则会把 `spawned` 写进冻结信封 | 两条路径都做逐字节/精确集合断言，没有把 receipt replay 放宽为“允许 `spawned`”；applier 从存储 child 行重算，不信任 delta 的 `replayed` |

### 1.14 S8 W1/W2/W3 实施披露（非新增规格）

| 项 | 实际选择 | 状态/边界 |
|---|---|---|
| **(a) W1/W2 不提交，W3 单次提交** | W1/W2 的 `30_advance.sql`、`48_loop.sql`、`v24/s1/test_g1.py` 与 `v24/s8/test_g7.py` 留在工作树；W3 补 G7-G、D-S8-12 的 pin 修复与收尾工件，里程碑由 W3 一次提交 | 本台账/矩阵编辑时 HEAD 仍 `a13ba77`，S8 W1–W3 未 commit/push；提交由控制器在十门全绿后按路径执行 |
| **(b) W1 Oracle BLOCK：token ledger** | child 首 model 的 reserve 从 child grant 中预留（`grant - model_reserve(grant)`）；父在 post-C19-refund 的 `v_tokens` 上扣完整 grant；child 成功只返还 `reserve-usage`，不出现 `2*grant-usage`；applier 独立重算 | 见 D-S8-9；`G7-D finite/NULL`、`G7-B`、`G7-N1` 是证据 |
| **(c) W1 Oracle BLOCK：parent wall** | 父 wall 用 `v_wall = greatest(0, remaining_wall_ms - elapsed)`；elapsed 取父 model effect 的 `created_at` 到 `now()` 的毫秒；成功后 `remaining_wall_ms=greatest(0,v_wall-child_wall)`；守恒 `before-elapsed=after+child` | 见 D-S8-10；`G7-D finite`（elapsed=22）、`G7-D NULL`、`G7-A` 是证据 |
| **(d) W2 `c_pins_xor` → `consumer_episode_id=NULL`** | spawn run pin 物理存为 run consumer，episode 列为 NULL；owner episode 由 child run `owner_episode_id` 承载；owner epoch 进 `consumer_epoch`；激活 pin 必须恰一条 live | 见 D-S8-5/D-S8-11；`G7-E`/`G7-N7`/`G7-G`；不新增列/约束 |
| **(e) W2 prospective toolset digest** | child 首 model 的 `digests.toolset` 在插入前按预期 run pin（或 ownerless 空集）计算；settlement 后 `v24.model_digests(child)` 必须逐字节相同；applier 用同一预期值校验 `inserts.pins` | 见 D-S8-11；`G7-A`/`G7-D`/`G7-N7` 的 `assert_child_run` 逐字节比对；`model_digests` 看不到未插入 pin，所以不能用插入后的函数回填 |
| **(f) W2 冻结 receipt-replay envelope** | 同 effect 同 bytes 的 `advance` 重放返回 S2/S4 冻结六键 replay 信封（`emitted=[]`、`revision=0`、`claim=null`），不含 `spawned`；只有新父 outcome 复用既有 child 时才返回 `spawned` 且 `replayed=true` | 见 D-S8-6/D-S8-11；`G7-B`（第二次新父 outcome + 第三次 receipt replay）、`G7-N1`/`G7-N6`；没有“首响应存储” |
| **(g) W2 N2 的 receipt-conflict 分工** | 并发同 key 异 bytes 的败者先撞同一父 model effect 的 receipt/claim（G 串行）得 `receipt_conflict`；第 24 码 `spawn_key_conflict` 由随后的新父 outcome 携带败者 bytes 产生；两者均不留下半 child/quota | 见 D-S8-8；`G7-N2` 的 `receipt_conflict` 与随后 `spawn_key_conflict` W0；不是把 `receipt_conflict` 改名为 24 码 |
| **(h) W3 评审发现并修复：child 首 model 的 pin 绑定** | 设计/实现最初把 owner run pin id 放在 child 首 `model_call` 的 `effects.pin_id`；公共 claim 门与 settlement 守卫都会拒绝带 pin 的 model_call，导致 owner-pinned child 首 model 无法经公共路径 claim/settle（旧 G7-G 的 seeded claim 掩盖了它） | **已在收尾前修复（D-S8-12）**：child 首 model `pin_id=NULL`，owner run pin 仅存于 `v24.pins`；applier 单条件要求 child effect `pin_id IS NULL`，同时仍校验一条 run pin 行；G7-G 改走真实公共 claim（`attempt/fence=1/1`），恢复断言全部保留；无新对象/错误码，claim/settlement 守卫未放宽 |
| **(i) W3 的产品 SQL 改动（D-S8-12）** | W3 改 `v24/s8/test_g7.py`（新增 `g7_g`、`expire_claim`，加入 `CHECKS`/`DEFAULT_ONLY`；删除旧的 seeded-claim 测试 helper）与 `v24/sql/48_loop.sql`（child 首 model `'pin_id',NULL`；applier 要求 `v_child_effect.pin_id IS NULL`，仍校验 run pin 行/consumer/provider/digest），其余为收尾文档；无新表/列/索引/视图/函数/DEFINER/GRANT | `G7-F` 重新断言封闭 catalog；错误码仍 24，无第 25 码；claim/settlement 守卫未改 |
| **(j) 无真实 provider** | G7 全部使用 FakeHost/进程内 fixture；无 socket/HTTP、无 provider 调用；`G7-F` 断言 `v24_fake.journal` 新增 0 行 | 不是 transport/adapter 证明；真实 provider 仍只在 v15 的显式 real 入口，不在本 gate |



### 1.15 S7 结项（D-S7-1…3、O-S7-1…6、W1/W2、G6 30/30）

S7 是 v24 的阶段总验收（三面并发矩阵）。W1 完成 18 格、9 条强制负例与 5 条锁序负例的矩阵落位；W2 完成无参数全量 G6 与收尾工件。2026-10-24 控制器实跑 `uv run python v24/s7/test_g6.py`（无参数）退出 0，**30/30 ID**；既有 10 条 gate 加 G6 共 **11/11**；`v24/sql/**` 与 `v24/load.py` 无 diff，错误码仍 **24 个有生产者 / 0 个未产生**。S7 为 **evidence-only**，没有产品改动。

**D-S7-1…3 状态**

| # | 内容 | 状态 | 证据 / 边界 |
|---|---|---|---|
| D-S7-1 | dispose 闭包锁序（D-S5-8 的 dispose 闭包边未扩） | **未触发** | N7 + L1/L2 两连接/锁向量实跑未发现产品 lock-order/deadlock bug；D-S5-8 的 dispose-closure 锁序问题由 N7/L1/L2 回答，不另立产品修复 |
| D-S7-2 | 无 starvation/fairness 证明 | **仍是显式债务** | G6 只证安全性与线性化，不证活性/公平；不宣称 starvation-free，需专门设计与证据 |
| D-S7-3 | 跨 scope child install 不可构造 | **不需要 / 未触发** | N7 用真实 `new_child_scope` + `admit_install(owner_fiber=…)` 构造并跑通跨 scope child install；证据已交付，D-S5-10 的证据缺口由此关闭 |

**O-S7-1…6 落位**

| # | 冻结口径 | 落位 / 证据 |
|---|---|---|
| O-S7-1 | 18 格（6 行 × 3 列）为权威；“9”只指 §9 的 9 条强制负例 | 18 格口径未改，无空格；30 ID = 16 条矩阵 + N1–N9 + L1–L5 |
| O-S7-2 | 默认全部 evidence-only；只有稳定复现产品 bug 才停手报告 | 无产品 SQL 改动；`v24/sql/**`、`v24/load.py` 0 diff；无新表/列/函数/错误码 |
| O-S7-3 | 可消费既有证据，但只重跑交点；除格 2 外由 G6 自产结果行 | 仅格 2 重跑 `G3b-5`（closeout 重跑，证据命令 `uv run python v24/s3/test_g2.py` 退出 0），其余 17 格由 G6 自产结果行；格 2 不是 G6 body，不计为第 31 个 ID |
| O-S7-4 | 只做同 scope spawn（N9）+ 跨 scope child install（N7） | N9 覆盖同 scope same-key/different-bytes；N7 覆盖跨 scope child install；不做跨 scope spawn |
| O-S7-5 | D-S5-8、跨 scope child install、无 starvation 的归类 | 见上表：D-S7-1 未触发、D-S7-3 未触发、D-S7-2 保持显式债务；D-S5-8/D-S5-10 的旧披露由 N7/L1/L2 关闭 |
| O-S7-6 | 新建 `v24/s7/` 三件套，不新建 `setup_db.py`、不新增 SQL | `v24/s7/{g6_support.py,test_g6.py,README.md}`；0 个新 SQL 文件、0 行产品 SQL |

**W1/W2 checkpoint 与里程碑提交**

| 阶段 | 内容 | commit |
|---|---|---|
| W1 | 18 格矩阵落位 | `c5fe8e3` |
| W1 | evidence notes | `ddabdcd` |
| W2 | handoff checkpoint | `19764eb` |

W1/W2 为 checkpoint commit；**里程碑提交仍未发生，属控制器**。本台账不写“已提交/已推送”。

**H2 测试期望修正（3→2，非产品）**

H2 的 `requests` 期望由 3 改为 2，最终为 `(2,0,0)`。这是**测试期望 bug，不是产品 bug**；无产品改动。

**N6b / N8b 语义**

- **N6b**：`prepare_unknown` + inspect `absent` 的真实产品路径是 `prepare_failed → direct tombstone（0 host_release）→ closed`，与既有 **G4-J2** 一致。计划 §5.3 的简写“inspect absent + release → disposed → closed”必须按这条真实路径读；这是**文档澄清**，不是削弱断言。
- **N8b**：`model_call.pin_id` 为 **NULL**；run pin 由被 claim 的 tool child 持有（**G2b-O 形状**），只有该 tool 静默后才释放。

**G6 30/30 与 11/11**

30 ID = 16 条矩阵（A1；B1–B3；C1–C3；D1；E1；F1；G1–G3；H1–H3）+ N1–N9（9 条负例）+ L1–L5（5 条锁序）。两序子 tag（`A1/A1b`、`N1a/N1b`、`N2a/N2b`、`N5a/N5b`、`N6a/N6b`、`N7a/N7b`、`N8a/N8b`、`L1a/L1b`…`L5a/L5b`）不是额外 ID；每个结果行恰出现一次。末行逐字为：

```
[passed] v24 S7 W1-W2 G6-A…H + N1-N9 + L1-L5: g6_a1,g6_b1,g6_b2,g6_b3,g6_c1,g6_c2,g6_c3,g6_d1,g6_e1,g6_f1,g6_g1,g6_g2,g6_g3,g6_h1,g6_h2,g6_h3,g6_n1,g6_n2,g6_n3,g6_n4,g6_n5,g6_n6,g6_n7,g6_n8,g6_n9,g6_l1,g6_l2,g6_l3,g6_l4,g6_l5
```

11/11 = 10 条既有 gate + 无参数全量 G6，全部退出 0；命令与顺序见 [`v24/s7/README.md`](../../v24/s7/README.md)。历史 S6/S8 收尾的 **10/10** 保留为当时口径（“当时无 G6”），不删除、不改写；G6 不替代任何一条既有 gate。

**边界（不 overclaim）**

Fake-only；无真实 provider/网络；无跨主机 lease；无 starvation/fairness；无 G5 崩溃窗口重测；无多主机。S7 是 **evidence-only**，不替代 S1–S8 的既有证据，也不证明真实 transport/adapter。

### 1.16 M-H 落地（2026-10-24；G8 23/23）

**基线（M-H-1）**：worktree `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`，branch `v24`，HEAD `d8155f4`（`v24: add concurrency matrix (G6)`），`v24/` 除 M-H 改动外无未提交项。九个冻结内核 SQL（`10_schema`、`20_triggers`、`30_advance`、`40_interpreters`、`45_capability`、`46_cleanup`、`47_verbs`、`48_loop`、`49_recovery`）按文件顺序拼接的 SHA256 为 `407dc75ae79524f890db894a135ad716766f4ad35fb6a38ad5a274a8a7284420`；本轮 `git diff --exit-code` 对这九个文件为 0。

**advance 取 G 前读 `v24.fibers` 的披露（计划 M-H-1 要求）**：`30_advance.sql:208-213` 在 `PERFORM pg_advisory_xact_lock(24,1)`（`:247`）之前，对 `command_install` 且 `owner_fiber_id` 非 NULL 的请求做一次 `NOT EXISTS (SELECT 1 FROM v24.fibers …)`。这是**只读存在性检查**，用于把不存在的 owner fiber 在 W0 阶段返回 `invalid_args`，不参与闭包、锁序或可写状态决策；`fibers` 从不删除，因此该读不会因并发删除而失效。它确实发生在 G 之前，按计划登记为披露，不视为第二写口或锁序变更。

**实现与计划对齐**：新增 `v24/sql/49_host_reads.sql`（9 个公开 `host_*` + 未 GRANT 的 `host_scope_allowed`），全部 `STABLE SECURITY DEFINER`、`SET search_path = pg_catalog, v24`、不取 G、不写表、不调用 `advance`、无动态 SQL、公开投影无 `SELECT *`；`host_scope_allowed` 只做 owner 或 `v24_admin` 的 USAGE 判断。`50_permissions.sql` 的 DEFINER 白名单按 `proname` 排序（17 个），GRANT 语句 27 条，逐角色 EXECUTE 为 **admin 26 / service 27 / operator 27**；`host_scope_allowed` 无 GRANT。`v24/load.py` 的两个元组与 `v24/s1/setup_db.py` 的 `expected_canonical` 把 `49_host_reads.sql` 放在 `49_recovery.sql` 之后、`50_permissions.sql` 之前；`v24/s1/test_g1.py` 的两处精确集合同步扩展。

**G8 实测**：无参数 `uv run python v24/s9/test_g8.py` 实跑 **23/23 ID，exit 0**，末行 `[passed] v24 G8 host reads / closure / lease / recovery: 23 case(s)`。闭包 probe 选计划选项 (a)：fixture-only PL/pgSQL `v24_fake.closure_probe` 内嵌从 `30_advance.sql` 完整提取的递归 CTE，冻结 SHA256 `e9b15387dd41fd1621ec2aaec964e70c900cea8a0468b03242fd8b46528efba5`；实测 `B=3`，`H=0,1,2,4,8,16,32` → `C=3,4,5,7,11,19,35`，每个相邻区间 C 增量等于 H 增量；`H_ok=509` → `C=512` 普通 claim committed，`H_bad=510` → `C=513` `retry_with_closure`（无 token、十表逐字节不变、重试仍拒）。H13 用 64 个各带 ~1 MiB `model_call.input` 的项实测整页 **67,107,712 bytes（64.00 MiB）**，未下调 64、未脱敏；真实 lease=1 claim/settle 通过。H11 持 G + 未提交变更下九个读完成且只见已提交 snapshot，写调用仍受 G 串行。

**债务关闭与未关闭**：

| # | 状态 | 证据 / 口径 |
|---|---|---|
| D-S6-12 | **关闭** | `G8-D1a`：已关闭 scope + 真实过期、已 claim、非 manual 的候选，`command_recover` 精确 applied=1 `settle_unknown`/`install_not_preparing`，scope/install/fiber/run 未复活；不是 noop fixture |
| D-S8-7 | **关闭** | `G8-D2`：双 spawn、spawn+普通 tool、spawn+`final`、spawn+`interaction` 均 `invalid_outcome` + 十表零写 + 原 claim 不变；随后同 key 合法 spawn committed |
| D-S7-2 | **仍未关闭** | G8 不写 starvation/fairness 用例；无活性/公平性证明 |
| G9/G10 | **后续完成** | G9 由 M-R 通过 11/11（§1.17），G10 由 M-P 通过 8/8（§1.18）；不得用 G8 或 11/11 代替 |

**边界与不 overclaim**：`G8-H12` 在开放 keyset 扫描中把一行移到自己 cursor 之后，确定性地观察到同一行 **2 次**（`duplicates=1`），再按 `effect_id` 去重得到完整 8 行集合；这只证 worker 必须按 id 去重，不声称任意并发状态改变都会产生重复。公共路径 `unknown→inspect` 分支在 M-H **未生成**，实际返回 `[]`；没有用 owner 插入补成公共路径证据。公共路径 32 次 `fiber_control(on/off)` 的 counts 为 effects 4/18/34/66、reconcile 1/8/16/32、episodes 1/4/8/16、pins 0；逐命令闭包 6…38（非单调，因探针指向不同形状的 latest effect）。`G8-W1` 只证 M-H 可用的 SQL/session 前置（READ COMMITTED、30s/5s/5s、两连接 IDLE、在飞时不 sweep）；worker 循环/真实 provider 属 M-R，不在本里程碑。所有 G8 fixture 无网络；socket 仅被 monkeypatch 后 deny/restore。

**历史 closeout 不变**：M-H 改动后 11 条冻结命令再次依序实跑，全部 exit 0（**11/11**）；G8 是 extension check，不计入第 12 条，也不改写历史 10/10 或 11/11。

### 1.17 M-R 落地（2026-10-24；G9 11/11）

**范围**：新增 `v24/host/{__init__,db,worker,journal,process_io,deepseek,smoke}.py`
与 `v24/s10/{test_g9.py,README.md}`；更新 `AGENTS.md` 第三真实套接字入口、
本矩阵/台账与 `v24/s7/README.md`。**无产品 SQL、无 loader、无新表/列/错误
码**；九个冻结内核 SQL、`v24/sql/49_host_reads.sql`、`v15/**`、`v13/**`、
`v99/**` 均零 diff。G9 是 extension check，不是第 12 条 closeout gate；
历史 11/11 不变。

| # | 计划/合同 | 实际 | 理由 / 证据 |
|---|---|---|---|
| D-MR-1 | 过期候选的检测可按计划提 `recoverable_effects` | worker **不调用** `recoverable_effects`；只用九个公开 reader（`host_effects` 的 claimed + `lease_until`）识别过期，再对 scope 调一次 `command_recover` | 用户硬合同限定 control 连接“只九读 + `command_recover`”；`host_effects` 已含过期 claimed 行，避免额外 RPC。`G9-J3` 实跑：live lease 零 HTTP 隔离，过期后一次 sweep 转 unknown |
| D-MR-2 | control 连接可做时钟/lease helper | `remaining_lease_ms` 改为纯本地计算（解析 `lease_until` ISO/`datetime`），不再发 `clock_timestamp`/`recoverable_effects` | 保持 control 面严格为九读 + `command_recover`；`G9-L` 断言短 lease 零 HTTP，`G9-J*` 的过期路径仍正确 |
| D-MR-3 | 同类 effect 按 effect UUID 执行；结果中 tool_calls 按 provider 顺序 | 执行顺序仍按 effect UUID；`_history` 按 parent + `ordinal` 重排 tool message，保证 continuation 的 assistant/tool 顺序与 provider 调用一致 | 不改内核/claim 排序；`G9-C` 用两个 tool call 证明 provider 顺序、batch barrier 与唯一 continuation |
| D-MR-4 | 成功响应应带可信 usage | `interpret` 对 200 响应要求 usage 为对象且 `prompt_tokens`/`completion_tokens` 均为整数；缺失或不可信 → `unknown`，不伪造 usage | 计划映射表要求“不可信 usage → unknown”；`G9-D/bad-usage` 实测 |
| D-MR-5 | `max_output_tokens` 默认 256、clamp [1,512] | 非整数/bool → `failure`；整数先 clamp 到 [1,512] 再按 reserve 截断 | 避免配置越界被误判为 host 失败；`G9-A` 断言 1≤max_tokens≤64 |
| D-MR-6 | journal 事件集封闭、两边界 fsync、未知版本失败、秘密/DSN 拒绝 | `HostJournal` 只接受 `effect_prepared`/`dispatch_started`/`dispatch_finished`/`settlement_committed`/`journal_conflict`；目录 0700、文件 0600、POSIX flock、逐条 fsync + read-back；截断尾只裁最后不完整行 | `G9-L` 实测 0700/0600、第二写者拒绝、version 2 与内部 corruption 失败、截断尾恢复、secret 拒绝 |
| D-MR-7 | `process_io.py` 为 M-P scaffolding | 提供 `ProcessSpec`/`ProcessResult`/`run_process`：无 shell、固定 cwd/env、有界 stdin/stdout/stderr、进程组 kill + reap、timeout 标记；G9 只做静态/间接检查 | M-R 不实现 plugin host；边界写入 `v24/s10/README.md` 与矩阵 §0.6 |
| D-MR-8 | 真实 provider 只允许显式 opt-in | `v24/host/smoke.py` 无 flag 打印 `not_requested` exit 0；flag 无 key 打印 `credentials_absent` exit 2，且不构造 adapter、不打开 DB；有 key 才执行一次短 start→model→final | 2026-10-24 实跑两条无 key 路径，退出码 0/2；2026-10-29 有 key 路径已实跑一次并通过（`live_success`，exit 0，见 §Post-closeout M-E live），入口仍非 gate |
| D-MR-9 | `AGENTS.md` 历史上只列两个真实套接字入口 | 按 M-R 要求追加第三个 `v24/host/smoke.py --real-provider-smoke` | 用户本轮明确要求；入口仍非 gate、调用时不得有打开事务。`AGENTS.md` diff 仅该条 |
| D-MR-10 | `timeout_s` 是 deadline，但不保证硬上界 | 沿用 `StdlibTransport`：socket timeout 只在打开连接时按剩余时间设置一次，`read_bounded` 只在每次读前后检查 deadline；慢速滴灌响应可超出约 2× `timeout_s`，DNS 解析不受 socket timeout 覆盖。host 侧仍以“剩余租约 ≥ timeout + 5s”作启发式前置检查 | 正确性不依赖硬 deadline：结算不查 `lease_until`，host 在飞时不 sweep，挂死进程经 journal 与 `command_recover` 收敛 unknown；只影响活性。计划明确要求把该点登记为披露 |

**G9 实测**：无参数 `uv run python v24/s10/test_g9.py` 实跑 **11/11 ID，
exit 0**，末行
`[passed] v24 G9 M-R: 11 case(s): G9-A, G9-B, G9-C, G9-D, G9-E, G9-F, G9-L, G9-J1, G9-J2, G9-J3, G9-R`。
所有 provider 响应为脚本化 `(status, raw)`；fixture 前 deny
`socket.socket.connect`、`socket.create_connection`、`urllib.request.urlopen`
与 `v15.provider.deepseek.build_opener`，`finally` 恢复；无真实套接字、无
API key。

**无 key smoke 实测**（2026-10-24）：

```text
$ python -m v24.host.smoke
not_requested                  # exit 0
$ python -m v24.host.smoke --real-provider-smoke
credentials_absent             # exit 2
```

**未证明 / 未运行**：有 key 的真实 provider 路径未运行（环境无
`DEEPSEEK_API_KEY`），因此不声称真实网络、延迟、费用或模型质量；G9 不证明
starvation/fairness（D-S7-2 保持未关闭）、跨主机 lease、多主机或 M-P
plugin/registry。`v24/host/process_io.py` 只是 scaffolding，G9 不把它当作
plugin host 的运行时证明。

（2026-10-29 更新：有 key 的真实 provider 路径已实跑一次并通过，`live_success`/exit 0，见 §Post-closeout M-E live；上述「未运行」是 2026-10-24 当次状态，本段其余边界继续有效。）


### 1.18 M-P 落地（2026-10-24；G10 8/8、Node 独立通过、multilingual smoke 通过）

**范围**：新增 `v24/host/{registry,line_json,plugins,plugin_smoke}.py`、
`v24/s11/{plugins/echo.py,plugins/echo.js,plugin_fixtures.py,test_g10.py,
test_node.py,README.md}`；更新本矩阵/台账与 `v24/s7/README.md`。**无产品 SQL、无 loader、无新表/列/错误码**；九个冻结
内核 SQL、`v24/sql/49_host_reads.sql`、`v15/**`、`v13/**`、`v99/**` 均零
diff。G10 是 extension check，不是第 12 条 closeout gate；历史 11/11 不变。

| # | 计划/合同 | 实际 | 理由 / 证据 |
|---|---|---|---|
| D-MP-1 | 设计 §9.1「所有 gate 外部适配器为 Fake」 | G10、`test_node.py` 与 `plugin_smoke.py` 的 plugin 都是**真实本地解释器子进程**（`sys.executable`/`node`），不是 Fake 进程；但模型仍是 scripted transport，且 fixture 前 deny socket/opener | 本地、确定性、无网络，Python 解释器必然存在，判为可接受的 §9.1 字面偏差；口径固定为「真实**网络** IO 不进 gate」。G10-H 实测超时/超限杀进程组并 reap，G10-B/Node 实测真实 stdin/stdout 帧 |
| D-MP-2 | `descriptor_digest` 的规范字节未指定序列化 | `registry.pg_jsonb_text()` 复刻 PostgreSQL `jsonb::text`：key 按 UTF-8 字节长度后字节序、`", "`/`": "` 间距；`v24.canonical_json(jsonb)` 就是 `p_payload::text` | 用宿主语言 compact JSON 会与内核 `descriptor_digest` 不一致；G10-A 用真实 slot/pin digest 断言，G10-F 在 pin 字节被改而 digest 字段仍匹配时零 spawn |
| D-MP-3 | 三个 digest 负例要求零 spawn | artifact/adapter 不匹配会让 `host_prepare` 先失败，无法到达 tool dispatch；G10-E 因此先用**正确** registry 完成 install/prepare/activate，再在工具派发前替换为不匹配 registry，并用 patch 的 `run_process` 断言零 spawn | 隔离被测量的边界（工具派发），而不是把 prepare 失败冒充工具零 spawn；三个负例各自独立 scope/workdir、独立不匹配字段 |
| D-MP-4 | 工具回执按 parent model effect + ordinal 关联，不按 key | `plugins.tool_handler` 只把 `effect_id` 传给 line-JSON reservation；`worker` 已有 parent/ordinal 关联，dispatcher 不按 key 查回执 | G10-C/G10-D/G10-G 与 multilingual smoke 的重复 Node key（成功 + exit 3）均按 parent/ordinal 正确落位，未覆盖先前回执 |
| D-MP-5 | unknown tool 保持 pin/资源屏障，不强制释放 | G10-D 断言 run `blocked_unknown`、install 仍 `installed`、`disposed_at NULL`、零 `host_release`；dispatcher 对 timeout/EOF/坏帧/第二帧/超限/异常退出一律 `unknown` | 不新增 `unknown→success` 或 forced release 路径；G10-H 的每个 started 进程都有 returncode/reaped 证据 |
| D-MP-6 | `prepare`/`release`/`inspect` 沿用既有 host effect 结果形状 | `plugins.py` 复用 `{v:1,prepared|released|observed,...}` 形状，不新增 lifecycle receipt；reservation 直接取 effect request 的既有值 | 与 `v24/s6/fake_crash_host.py` 的可执行规范一致；G10-G 证明重复 reservation 幂等且只一行 host_prepare/host_release |
| D-MP-7 | M-P-3 要求同一 run Python → Node → final | `plugin_smoke.py --multilingual-smoke` 单 fixture/单 scope/单 run：Python Unicode 成功 → Node 转义换行+空字符串成功 → Node exit 3 工具错误 → final；两个 install 均 disposed、scope closed | 2026-10-24 实跑 exit 0（run_id/证据见矩阵 §0.7）；`test_node.py --node` 只是独立 Node 全生命周期，不替代本项 |

**G10 实测**（2026-10-24，最终树）：无参数
`uv run python v24/s11/test_g10.py` 实跑 **8/8 ID，exit 0**，末行
`[passed] v24 G10 M-P Python: 8 case(s): G10-A, G10-B, G10-C, G10-D, G10-E, G10-F, G10-G, G10-H`。
`uv run python v24/s11/test_node.py --node` 实跑 **exit 0**（Node
`v24.13.1`），覆盖 Unicode、转义换行、空字符串与 Node exit 3。
`uv run python -m v24.host.plugin_smoke --multilingual-smoke` 实跑
**exit 0**：同一 run 内 Python → Node → final，两个 install disposed，
scope closed。

**未证明 / 未运行**：Go/Swift/DuckDB 不在本轮范围；G10 不证明真实网络
provider、跨主机 lease、starvation/fairness（D-S7-2 保持未关闭）或多主机；
Node 缺失时 `test_node.py --node`/`--multilingual-smoke` 打印 SKIP 并
exit 2，SKIP 不算通过。


### 1.19 W1 文档对齐（2026-10-29；实现不变）

本节记录文档与已实现 v24 行为的 wording-only 对齐；不改 SQL、host、tests、loaders 或 gate，亦不重新宣称未有 gate 证据的能力。

| ID | 文档漂移 | 文档修正 | 证据 / 性质 |
|---|---|---|---|
| D-S1-1 | `turn_no` 被写成“已提交模型步骤数”，与 model/tool settlement 计数实现不符 | 设计稿改为已提交业务 settlement 数；cancel/steer/respond 与 cancel-late 不增；§3.3/§5.1 同步说明 | `48_loop.sql:588,1411`、`49_recovery.sql:126-129`；纯文档修正，零代码影响 |
| D-S3-9 | 设计允许 tool successor 声明 `replay_safe`，实现对 tool successor 硬编码 `no_replay` | §B.4 改为 v1 tool_call successor 一律 no_replay；可被 claim 的 replay_safe 恢复闭集收紧为 host_prepare/host_release/inspect_resource | `48_loop.sql:1133,2963`、`49_recovery.sql:351-375`；工具 replay_policy 无独立 gate 断言，既有证据缺口保留 |
| D-S4-11 | 设计声称参数与 tool output 按 descriptor JSON Schema 校验 | 设计稿降级为 `{key,args}` / `{status,output,usage}` 形状校验；`slots.descriptor` 不透明，DB/host 不执行 parameters/output schema | `48_loop.sql:296-307,1376-1387`、`30_advance.sql:745-806`、`10_schema.sql:127,190`；post-closeout spec-layer revision，无 gate assertion |
| D-MR-11 | 设计把 host journal 写成外部证据副本，未明确其为 provider transcript 来源 | 两份设计稿、矩阵与 S10 README 明确 journal 是后续 model 请求对话原文唯一持久来源；DB 仅保留语义投影，journal 丢失导致 history_missing → failure，再经 command_recover 转 unknown | `v24/host/worker.py:944,1125-1137,1190-1231`、G9-A/B/C；纯文档对齐，未做 derive_model_messages 或新增 outcome 字段 |

## 2. 实施披露（不是规格偏差）

以下条目改动的是 DDL 细节或测试夹具，不改变设计语义；列在此处是为了让复核者能对着代码找到它们。

| # | 披露 | 计划原文 | 实际 | 理由 / 证据 |
|---|---|---|---|---|
| I1 | `f_effects_parent`、`f_events_effect` 为 DEFERRABLE | 计划列为普通 FK | DEFERRABLE | 与同组 FK 的延迟策略一致；`D.deferred` 证明延迟 FK 在 COMMIT 闭合 |
| I2 | `c_installs_ident` 重命名为 `c_installs_identity_len` | 计划用 `c_installs_ident` | 改名 | 与唯一索引 `u_installs_ident` 重名，PG 允许但审计易混；`D.catalog` 断言约束名 |
| I3 | 夹具 schema 闭集为 `{v24, v24_fake}` | 计划只列 `v24` | 加入 FakeHost journal schema | journal 必须与十表分离（指夹具 schema 闭集，不指权威归属）；`S._assert_closed_catalog` 仍断言第三 schema 被拒 |
| I4 | G1-A 允许 INVOKER `validate_and_apply_install_delta` 含 `UPDATE v24.effects` | 计划「只有 advance 体内出现 UPDATE」 | 允许该具名、不可授权的 INVOKER helper | W5 需要与 advance 共享 delta 应用；S1 时 `prosecdef=true` 恰为 `{advance}`；S3 W1 后加入只读 DEFINER allowlist，advance 仍为唯一可写 DEFINER（矩阵 §1.1） |
| I5 | settlement mode 由 `p_outcome.class` 推断 | 计划未指定推断来源 | class 决定 success/failure/unknown | 避免 delta 自选执行域；`T.install_settlement_w5` 三态断言 |
| I6 | `install` 的 `preparing` vs `installed` 由 manifest 决定 | 计划只写状态机 | 空 `provides` + 零长 artifact ⇒ 纯声明 `installed` | 让 `host_prepare` 三态都可达；`T.install_settlement_w5` 覆盖 |
| I7 | S1 的 `invalid_outcome` 是**零写预检**，不是 W1 稳定失败 receipt | §4.16 错误表标 W1；设计稿 L279 要求「可审计确定失败」 | S1 保持零写；S3 未新增该 W1 receipt 证据，model/tool outcome 路径归 S4 | S1 唯一可达生产者是结算 delta 预检（`validate_and_apply_install_delta` 直接返回 error，未进入 DML），结算不写 request 行，没有承载 receipt 的位置。S1 未实现 `tool_calls` 超限路径，因此该 W1 分支不可达。`T.install_settlement_w5` 实测该路径十表快照不变、effect 仍 `claimed`；矩阵 §3.1 已分列 W0 实测与未验证的 W1 receipt |

### 2.1 S4 实施披露（W1–W6）

| 工项 | 披露 | 证据 / 边界 |
|---|---|---|
| W1 | 新增 `48_loop.sql`（14 个 INVOKER helper；无新 DEFINER、无新表/列）；`model_call.request` 增加 `digests` 三摘要；start/steer/respond 准入预扣 reserve；token-0 steer/respond 封口；`FakeLLM` 与 `FakeTool` 同置 `fake_llm.py`，未单独建 `fake_tool.py` | `097ffa5`；G1-A 的 DEFINER allowlist 未变；`G2b-B/L/U`；测试 import 为 `from fake_llm import FakeLLM, FakeTool` |
| W2 | tool settlement + pin 绑定 + `batch_digest`；16 条上限；continuation parent=max-ordinal tool；同批唯一 continuation；G2b-G 防御预检 | `fc3e6da`；`G2b-A/D/E/F/G/K/N` |
| W2.1 | 仅补并发证据：两连接 + `Barrier` + held-G advisory + `pg_blocking_pids()`/`pg_locks`；**无产品改动** | `52eaeef`；`G2b-E` 4 trials、`G2b-F` 2 trials |
| W3 | model outcome 生产 `runs.interaction` 六字段 + `waiting`；respond 真链路；`blocked_unknown` 优先级；`interaction_mismatch` 实际为 W1 | `040e6f2`；`G2b-H/I/N` |
| W4 | `loop_sealable` 增 `p_excluded`/`p_from_waiting`；cancel-late 的 policy/schema digest 例外；cancel-late tool unknown 保留 cancel seal；`turn_no` 只在已提交 settlement +1 | `220117f`；`G2b-J/M/O`、`[G2b-O/tool-unknown]` |
| W5 | `steer_model_effect_id`/`steer_consumable`；两个 interpreter 消费 pending；applier 用同一 helper 重算；`30_advance` 接受消费型 steer 形状 | `a2c8d7d`；`G2b-P/Q/R/S` |
| W6 | 测试-only：新增 `G2b-T-1…T-10` 十条具名零写负例；旧 `[G2b-T-1/2/3]` 标签改名为 `[G2b-V/*]`（断言未动）；收尾工件与计划状态 | 本 commit；`v24/s4/test_g2b.py` 263 insertions / 5 deletions |

### 2.2 S5 实施披露（W1–W4）

| 工项 | 实际文件增量（`git show --numstat`） | helper / 结构新增 | 实施选择与说明 |
|---|---|---|---|
| W1（`a89d936`，6 文件） | `46_cleanup.sql` **NEW** +552；`40_interpreters.sql` +75/−107；`load.py` +2；`s1/setup_db.py` +1；`s5/test_g4.py` **NEW** +619；计划 +964。`30`/`50`/S1–S4 test 0 diff | `cleanup_edges`/`cleanup_closure`/`cleanup_cycle`/`cleanup_graph`/`cleanup_pending`/`cleanup_slots` + `dispose_stage`（7 个 INVOKER，无 GRANT）；`interpret_dispose` 改为委托；`command_dispose` validator 扩到 install + owner 后代 / install-scoped release id / 0..n−1 ordinal / 后代事件，footprint 仍 `installs\|fibers` 且无 insert | 合并 DAG 的 `depth` 用 longest-path-to-sink rank；pass 1 parent-first 写 intent、pass 2 反向 child-before-owner 判 release；stage error 用 `write:true` + failed command；cascade 在 `dispose_stage` 内自行锁 child |
| W2（`d4dfe92`，9 文件） | `48_loop.sql` +4/−4；`30_advance.sql` +64；`40_interpreters.sql` +407/−18；`46_cleanup.sql` +212/−40；`s2/test_g3a.py` +47/−9；`s3/test_g2.py` +9/−6；`s4/test_g2b.py` +14/−9；`s5/test_g4.py` +692/−4；计划 +21/−2 | **无新函数名**；inspect 结算 **INLINED** 在既有 `validate_and_apply_install_delta`；`dispose_stage` 增 prepare-inspect / release-unknown / direct-tombstone 分支；`claimable_kinds()` 追加第 5 项 `inspect_resource` | inspect request 冻结为 6 键、`ordinal=0`、确定性 id；claim 闸门校验 target kind/status/quiesced/install/reservation/digest/id/parent/pin；`prepare_failed` 直墓碑为 G4-J② 的最小实现 |
| W3（`1ae1b85`，5 文件） | `30_advance.sql` +64；`40_interpreters.sql` +705/−21；`46_cleanup.sql` +117/−3；`s5/test_g4.py` +348/−2；计划 +17/−1 | `cleanup_close_closure`、`scope_closable`；`dispose_stage` 接受 `mode='close'`；40 的 close phase 机（request→drain→retire→cascade→barrier→finalize）；30 的 close 闭包发现（child scopes/runs/installs、owner 后代、全 episodes、pins） | close 校验 **INLINED** 在 `validate_and_apply_delta`；`fiber_control(on)` 的 `scope_closed` 早退只写 `failure_seq/failure`；30 锁序未改；旧 `dispose_stage(...,'close')` 负例改正向 |
| W4（`2272b71`，4 文件） | `46_cleanup.sql` +548/−40；`40_interpreters.sql` +319/−99；`s5/test_g4.py` +904/−16；计划 +11 | `install_disposed_ok`（install/effect/quiesced/assumed_fibers 四参）、`install_disposed_ok_except_release`（install/release/assumed_fibers 三参）、`deactivate_stage`；`dispose_stage` 增 release/close 纤维阶段 | 每阶段 ≤16 行（`v_rows + stage_rows > 16` 即 blocked）；close cascade 对 `dispose_pending` 且无 ready/claimed release/inspect 的 install 重入；release failure 新 key 新 id/reservation；close-only 阶段不并发 release |

关键实施选择（与计划草稿/命名有出入的，按代码记录）：

- **`cleanup_graph.depth` = longest-path-to-sink rank**：计划草稿的 seed depth 无法保证 scope-seeded 端点顺序；实现改为对闭包内简单路径取最长 rank（0 为 sink），`ORDER BY depth DESC, node_id` 保证每条边 u→v 满足 rank(u)>rank(v)。G4-A（B<A<R、A<P）与 G4-E（65-chain depth≤64）是证据。
- **stage error 用 `write:true` + failed command**：`dispose_stage` 返回 `{error}` 时，`interpret_dispose` 以 `write:true` 只写 failed command effect + request receipt，丢弃整个 stage delta（`40_interpreters.sql:3301-3306`）；这采用 raw W1/G4-E 的写类，**不是** §5.2 草稿的 `write:false`。close cascade 同形（`:315-318`）。G4-E/G4-M-5 断言 domain 零写 + effect/request 各 +1。
- **W2 inspect 结算 INLINED 在既有 install delta applier**：G1-A 把「可写 `v24.effects` 的函数」钉死为 allowlist，`test_g1.py` 又不在本轮允许修改路径；因此不复用计划 §5.5 的 `validate_and_apply_inspect_delta` 函数名，逻辑内联在 `validate_and_apply_install_delta`。**没有** `inspect_effect_id` 函数——id 公式直接写在 `dispose_stage` 的两处 inspect 分支里。
- **W3 close 校验同样 INLINED**：`command_scope_control` 的 close delta 校验/落库内联在 `validate_and_apply_delta`，没有 `validate_and_apply_scope_delta` 函数名；原因同上（G1-A allowlist）。语义仍按 §5.4 的七表白名单。
- **30 的 child-install 闭包边未在 W1 扩展（W1 注记⑥）**：`dispose` 仍用既有 sibling 边；W3 只给 close 命令加了 owner-descendant 边。`dispose` 的 child 由 `dispose_stage` pass 1 的 `FOR UPDATE` 自行锁。这是 D-S5-8 的**部分落地**；S7 评估已完成，N7 + L1/L2 未发现 lock-order/deadlock bug，D-S7-1 未触发（见 §1.5 D-S5-8、§1.15）。
- **未创建 `v24/s5/fake_cleanup_host.py`**：计划 §8.2/W5 列为 NEW，实际没有该文件。host_prepare/host_release 回执由 `settle_release()` 直接提交（claim + success body `{}`）；inspect 回执由 `inspect_receipt()` 从存储的 6 键 request 生成冻结 body 后提交；负例/边界用 seeded effect 或已 claim 的 effect。属夹具合并，先例是 S4 的 `FakeTool` 与 `FakeLLM` 同置 `fake_llm.py`、未单独建 `fake_tool.py`；矩阵 §2.5 与 `v24/s5/README.md` 也按「回执直接经 `advance` 提交、无独立 host 进程」记录。
- **`test_g4.py` 打印 `[passed] v24 S5 W1-W4`**（计划 §7 草稿写的是 W1-W5）：W5 只做收尾，不新增断言；终判由控制器在八个既有 gate 全 0 后给出。G4-A…Q 17 个 tag 全部出现。
- **`50_permissions.sql` 在 W1–W4 均 0 diff**：没有新 DEFINER/GRANT；`cleanup_*`/`install_disposed_ok*`/`deactivate_stage` 全部 INVOKER，由 owner 连接或 DEFINER `advance` 调用。
- **计划 §5.8 的三个标识符未落地**：`inspect_effect_id`、`validate_and_apply_inspect_delta`、`validate_and_apply_scope_delta` 均不存在（前两者内联，第三者被 `validate_and_apply_delta` 的 close 分支吸收）；反过来，实现新增了 §5.8 未列的 `cleanup_slots` 与 `cleanup_close_closure`。

## 3. 非偏差声明

- **子门拆分不是规格偏差**：S1 内部按 W1–W6 串行拆分，是计划的工项划分，不改变设计稿的任何合同。原 W6（解释器）已由 Oracle 裁决（chat `untitled-chat-B38EF4`）解散，`scope_control` 归 W4、`install`/`host_prepare`/settlement 归 W5，ACL 顺延为 W6；这是**排期**调整，不是语义变更。
- **T1/T2 术语不是偏差**：T1 = 资格提交（claim 的 COMMIT）、T2 = 外部结果接纳（settlement 事务），由设计稿 §7.1 定义，R5 已写入正文；计划与矩阵沿用该定义。
- **W5 判据不回填 claim**：claim 的判据由 W3 gate 守住（Oracle 裁决 ①）；W5 只保留 S4–S6，不是覆盖率下降。
- **G3 子门拆分不是规格偏差**：G3a 归 S2、G3b 归 S3，是 pre-plan §2.2 已冻结的施工口径；S2 当时只证 activation-pin 半部；S3 本轮 G3b-1…5 实跑通过后父门为「完成（G3a+G3b）」；claimed/unknown 完整 settlement release 已由 S4 的 G2b-R/S 补齐（terminal 同 advance 释放、unknown 保留自身 pin），不再悬空。
- **S1 夹具/ACL 对齐不是放宽**：S2 把 canonical 列表从 6 文件扩到 7、`test_g1.py` 的 G1-A 允许 `validate_and_apply_delta` 含 `UPDATE v24.effects`、ACL 期望集合加入 `resolve`/`fiber_control`/`dispose`。三者都是「新函数集合」的必然对齐，断言只增不减；S3 W1 后 `T` 断言 advance 是唯一可写 DEFINER，另有封闭只读 DEFINER allowlist；`run_owner`/`run_projection` 内部且不授予协议角色 EXECUTE。
- **S5 `cleanup_pending` 是「非增」不是「严格递减」**：实现与 G4-Q 实测序列为 `6→6→4→4→2→2→0`（`test_g4.py:2501` 的 `assert sequence == [6, 6, 4, 4, 2, 2, 0]`）。只有**被计数的** install / fiber / host-effect 义务清除时才严格下降；retire 与单条 release 阶段不计 slot/pin，因此可以持平。计划 §7 的该行仍写「严格递减」，但同表示例 `(1,1,0…)` 与 §7 末的 W5 注记都按非增读；Oracle `DFBC85` 接受了实现的非增语义。这是**披露**（计划措辞需按实现读），不是削弱断言——G4-Q 对每个阶段的 `pending <= previous` 与最终 0 都做了精确断言。
- **「close-only」阶段的 release 顺延到下一个 key**：一个阶段若只 retire、只释放非末条贡献、或只 close（无 slot 释放），不发 `host_release`；release 由后续 dispose key 发出，保留 W1 的 G4-W1 时序。这不是无界停顿：下一个 request_key 是文档化的驱动器（C26/C27 与矩阵 §4 均写明「每次新 key 推进一个 phase」），`dispose_stage` 也会在下一 key 重新选 fiber。
- **provider pin 屏障**：live consumer pin 阻止 provider dispose；provider **从不**释放不属于自己的 pin——只有 consumer 侧的 `deactivate_stage` 释放本 episode 持有的 consumer pins。G4-C 是证据：provider dispose 时 `emitted=[]`、slot `released_at NULL`、pin 未释放、host_release 0；consumer off 后 pin 才释放，provider 再 dispose 才发唯一 release。

## 4. 历史失败（追加，不覆盖）

| 时间 | 失败 | 根因 | 修正 |
|---|---|---|---|
| W5 首次 | `test_g1.py` 退出 1：`AmbiguousColumn: column reference "manifest" is ambiguous` | `interpret_install` 局部变量与列名重名 | 重命名为 `parsed_manifest` |
| W6 首次 | ACL 探针期望 `42501`，实得 `428C9` | UPDATE 探针取 `events.event_id`（identity 列），解析期错误先于权限检查 | 探针只选 `attidentity='' AND attgenerated=''` 的列 |
| W6 第二次 | `permission denied for table effects` | 影子 TEMP 对象在 `SET ROLE` 前创建，属主是 LOGIN 角色 | 先 `SET ROLE` 再建影子；DROP 后再 `RESET ROLE` |
| W6 第三次 | gate 挂起 >600s | 回滚注入的触发器在 owner 未提交事务中持 ACCESS EXCLUSIVE，阻塞 admin | 触发器提交后注入，探针结束显式 DROP |
| S2 W1/W2 | `R` 退出 1：`42702 column reference "k" is ambiguous` | applier 遗留未使用变量 `k text` 与 `jsonb_object_keys(...) k` 别名冲突 | 删除未使用变量 |
| S2 W4 | `R` 退出 1：`428C9 cannot insert into generated column consumer_id` | `INSERT INTO v24.pins SELECT *` 覆盖生成列 | 显式列清单排除 `consumer_id` |
| S2 W4 | `R` 退出 1：`23502 opened_at NOT NULL` | `jsonb_populate_record` 对缺省列写 NULL，绕过 DEFAULT | episode delta 携带 `opened_at` |
| S2 W5 | `R` 退出 1：settle 路径 `invalid_outcome`，随后暴露 `42702 column reference "kind"` | settle 的 `UPDATE v24.effects ... WHERE kind=... AND status=...` 列名与变量歧义 | `UPDATE ... AS ef` 别名限定 |
| S2 W6 | `R` 退出 1：`request_conflict` | 测试把 scope 与 install 用同一个 `request_key`（全局唯一） | scope key 改为独立值 |
| S2 W5 | `R` 退出 1：succeeded reconcile 计数断言失败 | 一次 on + 一次 off 各结算一条，测试假设只有一条 | 改为断言 ready=0 且存在 `stage=deactivate/result=closed` |
| S4 W1 | 无 gate 失败；控制器评审发现 unknown 语义未完全闭环 | 语义 unknown 若被当作 claim 依据会重复计费 | W2 保留原始 outcome receipt、不升级为 claim；`G2b-V-3` |
| S4 W2 | 七门全 0，但 G2b-E/F 只有顺序证据 | 未构造双连接并发 | Oracle 裁 A；W2.1 补两连接 + Barrier + `pg_blocking_pids()`/`pg_locks`；`G2b-E/F` |
| S4 W3 | Oracle `DFBC85` 初判 **BLOCK** | 把 `interaction_mismatch` 误读为全库 W0 | 更正为 W1（领域零写 + 一条 failed `command_respond` + receipt）；PASS |
| S4 W4 | Oracle `CC3E40` **BLOCK** | cancel-late tool unknown 覆盖 cancel seal | 加 cancel-late 守卫（保留 cancelled/close_intent/result、`late=true`、0 successor）；`G2b-O/tool-unknown`；PASS |
| S4 W5 | 评审风险：pending_steer 消费 vs cancel 竞态未单独构造 | 未新增独立并发 fixture | 由 G2b-O 两序 + terminal guard 组合覆盖；不单独声称；PASS |
| S5 W1（**pre-gate 实施修正，非 gate 红**） | 无 gate 红。实现期修正：`cleanup_graph` 的 draft seed-depth 不能保证 scope-seeded 端点的 child-before-owner；stage error 的草稿写类为 `write:false` | depth=0 起点在同一 scope 的 owner/dependency 端点混合时排序不唯一；`write:false` 会让 `cleanup_cycle` 没有 failed command receipt，与 G4-E/raw W1 的写类冲突 | `depth` 改为 longest-path-to-sink rank（每条边 u→v ⇒ rank(u)>rank(v)，`ORDER BY depth DESC`）；stage error 统一 `write:true` + failed command（`40_interpreters.sql:3301-3306`）；G4-A/G4-E 断言 |
| S5 W2（**pre-gate 实施修正，非 gate 红**） | 无 gate 红。实现期修正：inspect claim 需精确 `ordinal=0`；direct-tombstone 的 16 行预算未计入同一 stage 的 install 行，曾可写出 17 行 | inspect id 公式固定 `:0`，claim 不校验 ordinal 会接受伪造的 ordinal≠0 effect；预算只算 fiber/slot 行时丢掉 install 的 +1 | claim 加 `effect.ordinal = 0` 精确校验；预算把 install 行 +1 计入（`v_direct`），`v_rows + ... > 16` 即 blocked；G4-N/G4-J② |
| S5 W3（**合同对齐，非 gate 红**） | 无 gate 红。旧 G4 断言 `dispose_stage(...,'close')` 得 `invalid_args`；W3 把它改成 accepted positive | C26 的 close cascade 复用 `dispose_stage(mode='close')`；旧负例基于 W1 的 `command\|cascade` 闭集 | `test_g4.py` 的 close 探针改断言 `error` 不存在且 `installs` 非空；这是合同变更，不是放宽（§1.6/§2.2） |
| S5 W4（**pre-gate 实施修正，非 gate 红**） | 无 gate 红。实现期修正：stage 预算合并时未在写第 17 行前拒绝；close cascade 对永久 barrier 的 `dispose_pending` install 会停在 barrier | `deactivate_stage` 返回行数与已累计行数需在 merge 前判；barrier 阶段只看到 pending install 时没有 phase 再进 cascade | `v_rows + stage_rows > 16` 即 blocked（不写第 17 行）；cascade 重入条件加 `dispose_pending` 且无 ready/claimed release/inspect；G4-Q/G4-F/G4-M-6 |
| S6 W4 | `s6/test_g5.py --only K4` 退出 1：`NameError: name 'snapshot_diff' is not defined` | K4 使用了未从 `g5_support` 导入的 helper | 加入 `snapshot_diff` import；`--only K4` 与无参数全量 G5 转 0，断言未削弱 |
| S6 W4（**打印口径，非 gate 红**） | W1–W3 每个窗口打印两行 `[G5-Kn]`（初始 journal 行 + 汇总行），K3 控制行也用 `[G5-K3]` | 收尾要求每个 `[G5-Kn]` 恰出现一次，重复 tag 使证据计数歧义 | 删除初始行、journal 并入最终行、K3 控制行改 `[G5-control]`；只改 print，不改断言；全量 gate 复跑（A-S6-9） |
| S8 W3（**评审发现，closeout 前修复**） | 无既有 gate 红；W3 评审发现 owner-pinned child 首 `model_call` 携带 owner run pin id，公共 claim 因此返回 `invalid_args`，child model 无法被 claim（旧 G7-G 以 seeded claim 掩盖） | `effects.pin_id` 只供消费 pin 的 `tool_call` 使用；`model_call` 误绑 run pin，触发公共 claim 的 `pin_id IS NOT NULL -> invalid_args` 与 settlement 的同形守卫 | 修 `v24/sql/48_loop.sql`：child 首 model `'pin_id',NULL`，run pin 仍为独立 `pins` 行；applier 要求 child effect `pin_id IS NULL`，run pin 行/consumer/provider tuple/digest 校验保留；G7-G 改走真实公共 claim（`attempt/fence=1/1`），全部门禁复跑 10/10；无新对象/错误码 |

**S5 的诚实口径**：在记录的 S5 W1–W4 轮次中，八门在每轮**最终运行**均退出 0（controller L1），**没有可记录的 gate 红**，也没有 S4 W3/W4 那样的 Oracle BLOCK。上表四条是 **pre-gate 实施修正**（提交前由实现者发现并修，或 W3 的合同对齐），不是 gate 失败；「gate 红」与「pre-gate 实施修正」不得混为一谈。

S1 四次是夹具缺陷；S2 六次是夹具/测试断言缺陷或局部 SQL 质量问题；S4 五次是评审发现/测试证据缺口与一次守卫修复（W4 BLOCK）；S5 W1–W4 无 gate 红，四条均为 pre-gate 实施修正或合同对齐（见上）；S6 W4 一次是 K4 helper 未导入（测试缺陷，修正后全量 G5 通过），另一次是只改 print 的 tag 去重。均非设计语义变更，修正后同一 gate 退出 0，未删断言、未降低断言强度。

## 5. 验收结果与仍未关闭的披露

S6/S8 收尾轮十个 gate 依序退出 0/0/0/0/0/0/0/0/0/0（load、`s1/setup_db.py --self-check`、`s1/test_ddl.py`、`s1/test_g1.py`、`s2/test_g3a.py`、`s3/test_g2.py`、`s4/test_g2b.py`、`s5/test_g4.py`、`s6/test_g5.py`、`s8/test_g7.py`；矩阵 §0）。**Gate 计数口径（9+1=10）**：9 个既有 gate + 无参数全量 G7 = 10 条命令，全部退出 0（10/10）；历史 S6 W1–W3 与 S8 W1/W2 的 `--only` 是增量检查点，不计入十条命令，也不替代父门。G2 父门**完成（G2a+G2b）**，G3 父门**完成（G3a+G3b）**，**G4 父门完成（G4-A…Q 17/17）**，**G5 父门完成（S6 W1–W4，K1–K10 10/10；末行 `[passed] v24 S6 W1-W4`）**，**G7 父门完成（S8 W1–W3，G7-A…H + N1–N7；末行 `[passed] v24 S8 W1-W3 G7-A…H + N1-N7: g7_a,g7_b,g7_c,g7_d,g7_e,g7_f,g7_g,g7_h,n1,n2,n3,n4,n5,n6,n7`）**；**G6 已完成（S7 W1–W2，30/30 ID；11/11）**。S7 收尾在既有十条之外追加无参数全量 G6，为 11/11；上方 10/10 保留为 S6/S8 收尾口径。`runs` 的 S3 start writer、revision 语义不变。错误码为 **24 个有生产者、0 个未产生**：`cleanup_cycle` 现有三个生产者——`v24/sql/46_cleanup.sql:852`（`dispose_stage` 根检查）、`46_cleanup.sql:879`（队列逐节点检查）、`v24/sql/40_interpreters.sql:2871`（admission 防御检查）；第 24 码 `spawn_key_conflict` 由 `G7-C` 与 `G7-N2` 的随后新父 outcome 产生；`blocked_unknown` 的 W0 墙与 W1 结算写类分列见矩阵 §3.1。S6 不新增错误码；S8 只新增 R7 的第 24 码。

- **G4/G5/G6/G7 已完成**：`s5/test_g4.py` 打印 `[passed] v24 S5 W1-W4`，G4-A…Q 全部出现；`s6/test_g5.py` 无参数打印 `[G5-K1]`…`[G5-K10]` 各恰一次（K3 另有 `[G5-control]`），末行 `[passed] v24 S6 W1-W4`；`s8/test_g7.py` 无参数打印 `[G7-A]`…`[G7-H]` 与 `[G7-N1]`…`[G7-N7]` 各恰一次（N1/N2 的锁证据行为 `-lock` tag），末行如上；`v24/s7/test_g6.py` 无参数打印 30 条 ID（末行见 §1.15），S7 收尾 11/11。
- **G5 证据**：K1–K10 的 child/worker 都是独立 OS 进程，child/worker/parent 的 `pg_backend_pid()` 互异；K4 是 fixture-only `P0001` 注入 + `ROLLBACK`（trigger `k4_inject` 删除后 `0/0`、十表快照回滚前后相等），K5 是 commit 后丢应答 + 两次 fresh replay（三次 response `byte_equal`、`second_replay_zero_write=true`）；完整值见矩阵 §0.2。
- **G7 证据**：无参数 gate 退出 0，完整输出（36 行，含附加 `[G7-G evidence]` 行）见矩阵 §0.3；`[G7-G]` 的 owner-pinned child 首 model `pin_id=NULL`，经真实公共 claim 得 `attempt/fence=1/1`（service login owner）；随即过期 lease，由真实公共 `v24.command_recover` 结算 `unknown`（`reason=lease_expired`、`observed=unknown`），child run `running`→`blocked_unknown`、`ended_at` 设置、`interaction/pending_steer` 清空；spawn edge/child 计数/父 run 行/父 quota 逐字节不变；owner run pin 是独立 `pins` 行，回收时释放且 `released_by_effect`=child effect；无 seeded claim。完整 before/after 见矩阵 §0.3 与 [`v24/s8/README.md`](../../v24/s8/README.md) §3.1。边界：FakeHost/进程内 fixture、**不调真实 provider**；owner pin 受 `c_pins_xor` 约束（`consumer_episode_id=NULL`，owner episode 在 child run），激活 pin 恰一条 live，child 首 model 的 `toolset` 为预期 pin 摘要；N2 并发败者先得 `receipt_conflict`，24 码由随后新父 outcome 产生；receipt replay 是冻结六键信封（无 `spawned`）。
- **S6 W4 范围（历史）**：代码只改 `v24/s6/{crash_worker.py,recover_worker.py,test_g5.py}`；**无产品 SQL 改动**，`v24/sql/48_loop.sql` 未动，`v24/sql/**` digest 在 gate 前后均为 `827e1c61515b9e6d5f4f7104d914bd4d53be483d171dc4c548bd8620d15900fd`；HEAD 仍 `45877b0`，未 commit/push。
- **S8 范围**：W1/W2 按计划不提交，W3 为单一里程碑提交；本台账/矩阵编辑时 HEAD 仍 `a13ba77` + 未提交 S8 W1–W3；W3 代码改 `v24/s8/test_g7.py`，并按 D-S8-12 修 `v24/sql/48_loop.sql`（child 首 model `pin_id=NULL` + applier 条件），其余为收尾文档；无新对象/新错误码（§1.14(i)）。
- **S5 已封闭的 S4 披露**：inspect 收敛（G4-H/I/J/K/N）、owner 级联/child-before-owner（G4-A/B 与 `[G4-W1]` cascade）、consumer-before-provider（G4-C）、贡献 DESC 与墓碑（G4-D/P/Q）、scope close phase 机与 close 后无新准入（G4-G/O）、失败/unknown 不写终态（G4-F/L/M）。
- **S5/S6/S8 边界（历史；G6/S7 已由 §1.15 补证）**：S5 只证串行 request-key 阶段（每个新 key 一个 bounded phase、≤16 行/successor、无 worker/自动推进）；S6 只证 FakeHost/journal 下的崩溃恢复合同（命令驱动、无 recovery 表/队列/lease/cursor、无第二 claim 路径），**不证**真实 provider/adapter 的 reservation 幂等、S7 三面并发或 S8 spawn（S7 三面并发已由 G6 补证）；S8 只证 FakeHost/进程内 fixture 下的 spawn/child-run 合同，**不证**真实 provider/adapter 或 G6/S7 三面并发（G6/S7 已由 S7 W1–W2 补证）。`cleanup_pending` 非严格递减、close 依赖新 key（§3），不得外推为「自动收口」；S6 的 `has_more` 只是提示，K2/K3 的 lease 过期是 seeded fixture，K5 为 host-only、预算不适用；G7-G 的 claim 走真实公共 claim 路径（D-S8-12），不是 seeded fixture。
- **FakeLLM/FakeTool/FakeCleanupHost/FakeCrashHost/FakeHost 不是 transport 证明**：纯进程内、无套接字；S5 没有 FakeCleanupHost 文件（§2.2），S6 的 `CrashHost` 只写 JSONL 与 `v24_fake.journal`；S8 的 G7 同样无 socket/HTTP，`v24_fake.journal` 新增 0 行；真实 IO 不在 gate 内。
- **仍未关闭的披露**：**D-S7-2 仍为显式债务（无 starvation/fairness 证明）**；A-S5-1…9 的逐条理由见 §1.6，A-S6-1…9 见 §1.10，A-S8-1…6 见 §1.13；G7-G 的 owner-pinned child 首 model 公共 claim 已由 D-S8-12 修复，不再列为未关闭债务。**D-S6-12 已由 `G8-D1a` 关闭，D-S8-7 已由 `G8-D2` 关闭（见 §1.16）**；D-S5-8 与 D-S5-10 的旧披露已由 S7 评估关闭：N7 + L1/L2 未发现 lock-order/deadlock bug（D-S7-1 未触发），N7 以真实跨 scope child install 补足证据（D-S7-3 未触发）；见 §1.5、§1.15。
- **M-H 验收（2026-10-24）**：G8 **23/23** exit 0；`B=3`、`H_ok=509`、`H_bad=510`、`C=512/513`；H13 64.00 MiB；ACL 17 DEFINER / 27 GRANT / 26-27-27；九个冻结内核 SQL diff 为空；11 条既有 closeout 复跑 **11/11**。G10 后续由 M-P 完成（§0.7/§1.18）；G8 不改变历史 closeout 计数，也不提供 starvation/fairness 或 host worker 证据（§1.16）。
- **M-R 验收（2026-10-24）**：G9 **11/11** exit 0；脚本化 transport、零真实套接字；无 key smoke `not_requested` 0 / `credentials_absent` 2；九个冻结内核 SQL、`v15/**`、`v13/**`、`v99/**` diff 为空；11 条既有 closeout 复跑 **11/11**。真实 provider 有 key 路径当次未运行（2026-10-29 已补一次 live 证据，见 §Post-closeout M-E live）；G9 不改变历史 closeout 计数，也不提供 starvation/fairness、跨主机 lease 或 M-P 证据（§1.17）。
- **M-P 验收（2026-10-24）**：G10 **8/8** exit 0（G10-A…H）；`test_node.py --node` 独立 **exit 0**（Node v24.13.1）；`plugin_smoke.py --multilingual-smoke` **exit 0**：同一 run 内 Python → Node → final，Unicode/转义换行/空字符串/exit 3 全覆盖，两个 install disposed、scope closed；九个冻结内核 SQL、`v15/**`、`v13/**`、`v99/**` diff 为空；11 条既有 closeout 复跑 **11/11**。G10 不改变历史 closeout 计数；D-MP-1 为显式 §9.1 偏差（真实本地子进程），D-MP-3 记录三个 digest 负例的隔离方式（§1.18）。
- **历史口径更新**：S4 的「22 个有生产者、1 个未产生」由本节更新为 23/0；S8 再更新为 **24/0**；S1–S4 的其它验收结论与边界（FakeLLM/FakeTool、真实 IO、S6/S7）继续有效。
- **R6/R7 规格修订已入账**（D-R6-1…4，§1.8；D-S8-1…12，§1.12）：D-R6-1 仍为规格层（S6 未改变十窗口）；D-R6-2 已由 S8/G7 实施；D-R6-3/4 已由 S6 W1–W4 实施并由 G5 证明；D-S8-12 为 W3 评审修复的产品缺陷（非规格修订）。**G5、G6 与 G7 已完成**（G6 由 S7 W1–W2 证明：30/30 ID、11/11），S7 已结项，S1–S8 全部收口。


## Post-closeout M-H（2026-10-25）

**D-PF-1（持续容量披露）**：七个分页函数默认且最多 64 项。H13 的 67,107,712 B 是特定 ASCII 夹具紧凑 JSON 字符/UTF-8 字节数，不是 PostgreSQL wire size、压缩率或进程 RSS，也不是响应字节/内存上限。effects.request 无已定义全局字节限额，advance 的 1 MiB outcome body 校验不约束 request；worker 可累积整轮结果，页项数不限制整轮内存。保持 64 的裁决已完成，容量治理仍未证明。M-H closeout 11/11、G8 23/23 exit 0；P0 三组 extension 全绿，记录见正式后续计划。D-S7-2 保持开启。


## Post-closeout M-M（2026-10-25）

D3：v24 固定 `deepseek-flash`；无运行时 allowlist，不消费 v15 allowlist。本轮不新增模型参数、环境 override 或 CLI，不修改 adapter 与 v15。closeout 11/11、G9 11/11 均 exit 0；逐命令时间/source/result 见正式后续计划。外部型号与计价事实没有重新查询。

## Post-closeout M-S（2026-10-25）

**D-PF-2（smoke 终态核验）**：旧入口在 worker 结算后从 `host_effects` active 工作列表寻找 model，会把已成功结算的 model 误判为缺失。M-S 改为使用 `start` 已提交的 run/model handles，从 `host_runs`/`host_run_effects` 历史读取面核验 completed/succeeded、final、usage 与 scope/run/effect 身份，并逐项绑定 journal dispatch 记录和 reply metadata；成功输出延后到资源、fixture、目录清理全部成功之后。失败路径保留或报告可用 evidence，不重试、不泄漏正文、header 或 key。

**M-S 测试偏差与补强**：G9 仍只有 11 个顶层 ID，完整 smoke 子场景集中在 G9-B/F/L；新增空 final、同进程唯一 request key、malformed history/分页/journal、结算后 active list 为空、取消后的 late success、初始化/close/fixture/delete/partial-delete 失败，以及 cleanup 期间普通异常与 `KeyboardInterrupt` 的关闭顺序。`HostDB.close()` 只关闭 control 后抛错时，raw service connection 仍由外层 cleanup 关闭；evidence path 探测异常被 best-effort 脱敏。该补强不改变生产 SQL、journal 格式、worker 或 transport。

M-S 在 source `6df64440299b4e6035e9e587bebd5f09eb9d9cbe` 的未提交树上重跑冻结 closeout 11/11 与 G9 11/11，全部 exit 0；逐命令时间、结果行和日志路径见正式后续计划执行记录。真实 provider 当次仍未授权、未执行（2026-10-29 已授权并实跑一次，见 §Post-closeout M-E live）；D-S7-2 继续开启。

## Post-closeout M-E（2026-10-25）

`recorded_at=2026-10-25`。M-E 记录真实 provider 入口的三态证据。两条负控已实跑；未检查实际 key 是否存在，无 flag 命令直接短路，flag 负控显式清除凭据；live attempt 因未授权而未执行，使用 `not_executed`，不借用负控 exit 2。

| record_group | executed_at | source_sha | command | status | reason | exit_code |
|---|---|---|---|---|---|---|
| `negative_control` | 2026-10-25T11:05:35+08:00 Asia/Shanghai | `e869e81` | `UV_NO_ENV_FILE=1 uv run python -m v24.host.smoke` | passed | `not_requested` | 0 |
| `negative_control` | 2026-10-25T11:05:35+08:00 Asia/Shanghai | `e869e81` | `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python -m v24.host.smoke --real-provider-smoke` | passed | `credentials_absent` | 2 |
| `live_attempt` | `not_executed` | `e869e81` | 拟执行：`UV_NO_ENV_FILE=1 /usr/bin/time -p uv run python -m v24.host.smoke --real-provider-smoke` | `not_run` | `not_authorized` | `not_executed` |

该记录只关闭入口短路证据，不证明当前环境本来没有 key，不关闭真实 provider、性能、质量、费用、跨主机或公平性债务。live attempt 的成功摘要（endpoint/model/run/effect/tokens/finish/provider wall_ms）和外部耗时均为 `not_executed`，证明范围为空。

## Post-closeout M-E live（2026-10-29）

`recorded_at=2026-10-29`。用户明确授权一次真实 provider 调用；`live_attempt` 已运行并通过，不再是 `not_executed`。

| record_group | executed_at | source_sha | command | status | reason | exit_code |
|---|---|---|---|---|---|---|
| `live_attempt` | 2026-10-29T16:31:07+08:00 Asia/Shanghai | `45886fe` | `UV_NO_ENV_FILE=1 /usr/bin/time -p uv run python -m v24.host.smoke --real-provider-smoke` | passed | `live_success` | 0 |

唯一输出：`[smoke] endpoint=api.deepseek.com model=deepseek-flash run=bd944a8f-e2b4-4859-a97b-46d7de40bbdd effect=fc328faf-5312-ef02-e16d-d2ab92262c69 tokens=57 finish=stop wall_ms=1206 result=completed`；外部耗时 `real 4.30`。

该记录只关闭「有 key 的真实 provider 路径能否跑通」这一项；真实网络延迟/可用性/费用/模型质量、D-S7-2、跨主机 lease、第二批语言仍未证明。D-MR-8 的三态合同不变，入口仍非 gate、调用时不得有打开事务。

## Post-closeout M-F（2026-10-25）

四项后续范围分别登记，均不在本轮实现：

| 范围 | 当前状态 | 触发与完成证据 |
|---|---|---|
| 第二批 Go/Swift/DuckDB | 未验证，未建占位实现 | 明确语言需求后先冻结 artifact/argv/工具链合同，再跑完整生命周期与零 spawn 负例 |
| D-S7-2 公平性 | **仍开启** | 需要负载假设、等待目标、调度策略和对抗负载活性证据；G6 安全/线性化结果不关闭它；M-F1 仅登记有限 host-only FC 子合同与 Fake-only 证据 |
| 跨主机租约 | 未验证 | 明确多主机部署后验证分区、接管、fencing、journal 所有权与重复副作用 |
| Provider 延迟/质量 | 未验证 | 明确样本、指标、预算和模型版本后独立实验；一次 smoke 不替代实验 |

当前源 `74b3c30` 的 G10 Python、Node 与 multilingual 检查均 exit 0；M-P 候选仍须重跑 Node 两条命令。


## Post-closeout M-P release candidate (2026-10-25)

The candidate at source `6d53a2d05a2e5439e7694125d4751ba053acb147` was tested on main base `ab34d6972a17f688c4a11adba89e363d74adbe81`; all 18 required candidate commands exited 0. `bddeb815608de37bc21594a372085fe1e591db85` is already an ancestor of main, so v99 Phase 0 is inherited rather than newly introduced; W1–W4 remain open.

No live provider request was made. D-S7-2 remains open, and cross-host lease, second-language, and provider performance/quality scopes remain unverified. Candidate state is release ready but unpublished.

Full candidate evidence and manifest: [release record](v24-release-2026-10-25.md).

The full main-to-candidate whitespace check reports three preexisting source-line issues: EOF blank lines in the v24 oracle brief and frozen `40_interpreters.sql`, plus trailing whitespace in G6. These are unchanged from the fixed source. The seven declaration changes pass the source-relative whitespace check; frozen SQL is preserved.
## Post-closeout M-F1（2026-10-25）

M-F1 31/31 命令 exit 0，结果覆盖 G11 全量及 A…L、既有 v24 回归、G8/G9/G10、Node、smoke 负控和 multilingual smoke。S12 的证据严格限定为有限 Fake-only host 调度合同；不关闭 D-S7-2 广义债务。执行日志与哈希见 [`v24-d-s7-2-fairness-execution-2026-10-25.md`](v24-d-s7-2-fairness-execution-2026-10-25.md)。

## Post-closeout Tool/Plugin ABI B0（2026-10-30）

B0 is an evidence baseline, not a production ABI implementation. The four golden files preserve distinct canonical authorities and fixed bytes; the checker has no re-bless path. B0 proved the SQL composition `one install → two same-realm slots → one run → two live pins`, including descriptor digests, provider fiber/episode/install identity, and an explicit zero-process assertion in `finally`. The cross-realm control remained `dependency_unresolved` with no run or pins. Historical B0 fixture failures and their corrections remain in the execution record; none weakened a gate or changed production code.

- **D-B0-1 (observed-current / proved-by-B0):** v1 descriptor, frame, provider, and tool-message bytes are fixed by 34 byte cases plus six structural vectors. Python/PostgreSQL and Python+Node/PostgreSQL checks exit 0. Parser cases preserve current `splitlines()` behavior, including U+2028/U+2029; this is evidence of current behavior, not a v2 approval.
- **D-B0-2 (contract-frozen/behavior-unverified; Q1/Q2; W5/W6 owner):** empty-page/offset and cursor-progress rules are candidate contracts only. B0 has no v2 tool and does not test empty files, empty directories, complete-search no-hit pages, offset overflow, or pagination convergence.
- **D-B0-3 (contract-frozen/behavior-unverified; Q3/Q4/Q5; W5/W6 owner after W1 design synchronization):** args/value/content/meta byte domains, absent-meta `{}` normalization, and plugin-versus-renderer budget ownership remain downstream contracts. B0 does not verify them and does not modify the external design.
- **D-B0-4 (contract-frozen/behavior-unverified; W4 owner):** v2 lease precheck, `lease_insufficient`, process-count zero spawn, additive `model_text`, journal-only no-rerender replay, and shared resource handler compatibility remain unimplemented and unverified. Current 30s tool lease, `dispatch_started` ordering, and journal transcript authority remain observed facts.
- **D-B0-5 (scope):** the final 18-command serial runbook all exited 0 with credentials removed. Closeout remains 11/11; G9/G10/Node/multilingual and B0 checks are extension evidence. No Node or multilingual SKIP/exit 2 occurred. No real provider was called. No host, SQL, loader, s10, s11, or design file changed.

## Post-closeout Tool/Plugin ABI W1（2026-10-30）

- **D-ABI-W1-1 (contract/reference verified; production pending):** Q1 uses `search_scope_too_large` when cutoff cannot fill a count-full or byte-full page; incomplete success must be nonempty and advance by actual hits. Q2 complete-item pagination, Q3 standalone args bytes, Q4 separate value/content/meta domains and normalized `{}` metadata (2 bytes), and Q5 total renderer/count/all-prefix selection are synchronized with the design. Fixed Python/Node references validate adversarial counters and cursors; M2/M3 still own production validation and tool behavior.
- **D-ABI-W1-2 (provisional W2-pending):** read/list/search renderer digests are computed from fixed `{id,args,value,content,meta}` goldens and independently reproduced. They are not production-renderer evidence; M2 must match them without re-blessing W1.
- **D-ABI-W1-3 (M3/M4 pending):** plugin artifact digest depends on future tool files; 12-second timing is a future timing gate. Journal-only replay/no-rerender and additive model text remain M4 behavior contracts. No real filesystem tool or provider was invoked by W1 checks.
- **D-ABI-W1-4 (compatibility/scope):** B0 bytes and checker are unchanged. `structure.descriptor_v2_rejected` is a malformed pre-M2 observation, not a permanent v2 rejection rule; M2 adds complete valid v2 acceptance. W1 adds no SQL, kernel object, runtime callback, or journal event. Frozen paths have zero diff from `f990b1d`; closeout remains 11/11.
- **D-ABI-W1-5 (evidence):** final serial W1/B0/closeout/G9/G10/Node/multilingual checks passed, with no exit2/SKIP. The [W1 execution record](v24-tool-plugin-abi-w1-execution-2026-10-30.md) preserves capture review, design SHA/spans, command identity/results, and audits. Gate results are recorded separately from downstream pending vector labels.

## Post-closeout Tool/Plugin ABI W2（2026-10-30）

W2 在纯 host 层落地五个合同模块，并完成 design §7 的 W2 修订与 conformance repin。它不接线 registry v2/line-json v2/plugins/worker/deepseek，也不证明 M2 完成。

- **D-ABI-W2-1 (implemented/verified; pure host):** `canonical.py` 统一 PG canonical、`J`、`strict_loads`、deep-freeze 与 `RegistryError`；`tool_schema.py` 只接受 13 个关键字并固定 first-error 顺序；`renderers.py` 提供三个纯投影、不可变 registry、21 个内嵌 golden 与三组 digest；`descriptor.py` 按 17 步顺序校验 v2 descriptor；`tool_results.py` 提供 v2 envelope、`join_content`、五域计量与 frame 分类。所有模块无 I/O、无 clock/random/env、无进程级 cache。
- **D-ABI-W2-2 (contract-covered; 40 cases):** descriptor 16、schema 9、renderers 7（21 内层 golden）、results 8 由生产代码命中；results 的 3 个 `m4_pending` 明确不执行。`registry.py` 只做七个名字的 re-export；`RegistryError` 身份、非 dict digest 异常与 B0/W1 字节保持不变。
- **D-ABI-W2-3 (design repin):** §7.1/§7.3/§7.4 增加 `canonical.py`、拆分四条 s13 gate、增加三条 gate 命令并改述 done-when #1。design SHA-256 由 `976567da…` 变为 `0de115c9…`；`DESIGN_SHA256` 与 `design_conformance.json.design_input.sha256_at_review` 同步更新；§7.2/§8.2/§8.3/Appendix A 只移位，pinned heading 与 span SHA 未变；八个 domain vector 与 case/status/expected 未改。
- **D-ABI-W2-4 (not proved; downstream):** W2 不证明 M2 完成、W3 registry/multi-tool/line-json v2、W4 dispatcher/worker/provider 接线、read/list/search 文件系统语义、分页收敛、12s 扫描预算、replay/journal 重放或真实 provider 行为。renderer golden 来自内嵌固定数据，不是真实工具调用。
- **D-ABI-W2-5 (evidence/scope):** 24 条命令串行 exit 0，无 exit 2/SKIP；closeout 11/11；`v24/sql/**`、`v24/s10/**`、`v24/s11/**`、`v24/load.py`、`v24/b0/**` 与七个运行时 host 文件零 diff；合同模块无运行时 import 边，生产代码不读 `v24/s13/vectors/*`。命令、时间、末行与日志 SHA 见 [W2 execution record](v24-tool-plugin-abi-w2-execution-2026-10-30.md)。
- **D-ABI-W2-6 (post-review hardening; 2026-10-31):** 三 lane Oracle 复审后的加固不改变 40 个 vector case、21 个 golden、gate 数字或 closeout 计数。代码侧：strict decode 归一 `RecursionError`/超长整数字面量；`J` 改显式栈并接受有限深 JSON（循环引用为 `circular_reference`）；success value/content/meta 增加 `J` 值域检查；`ToolDispatchResult` 校验外层三键、class/status、usage 与 class-specific envelope；renderer 的 `fn` 自抛 `RendererError` 统一为 `render_failed`；无 `type` 的 object-shaped schema 必须显式 `additionalProperties`。文档侧：design 新增附录 C 承载 §3.1/§5.2–§5.5 的规范澄清（正文 pinned span 未改），design SHA-256 由 `0de115c9…` 变为 `2606aedc…`，span 行号/heading/内容 SHA 全部保持不变；W2 plan、README、matrix 与 execution record 同步补充。加固后 24 条命令再次全部 exit 0，证据见 execution record 的 “W2 hardening supplement” 节；旧运行保留为历史记录。

## Post-closeout Tool/Plugin ABI W3（2026-10-31）

复审修正后最终证据为 `/tmp/w3-20261031T032503/`，完整 26 条再次串行通过。首轮 `/tmp/w3-20261031T030237/` 仅覆盖复审前 candidate，不外推到最终源码。补齐非规范 bytes/等价 UTF-8 str 的 raw-digest 探针、成功 `ApprovedTool` replace 后两 closure 重编译探针，并恢复 `line_json.run(adapter=...)` 首参数名；v1 keyword 与既有 positional 路径均通过。marker 数字与 design SHA 不变，未放宽 gate。复审逐项裁决见 execution record。


W3 交付 registry 审批模型与独立 line-json v2 transport；26 条指定命令串行全部 exit 0，末行均有命令专属 `[passed]`，无 exit 2/SKIP。registry 实测 17 cases / 3 manifest byte cases / 14 construction reasons / 6 zero-spawn match paths；transport 实测 10 cases / 7 frame byte cases / 55 parse rows / 5 preflight rejections / 4 unknown outcomes，v1 bytes unchanged。证据见 [W3 execution record](v24-tool-plugin-abi-w3-execution-2026-10-31.md)。W3 是 extension evidence，closeout 仍 **11/11**，不是 M2 完成。

- **D-ABI-W3-1 (D1; frozen-vector authority):** `double_lf` 与第二帧均为 `extra_frame`（unknown）；以冻结 `frames_v2.json` 为字节权威。设计 §5.1 的冲突句由附录 C.7 取代，原 pinned span 不改；55 行 corpus 已逐行通过，不修改或 re-bless 向量。
- **D-ABI-W3-2 (D2; production API / digest bytes):** `ApprovedPlugin.from_manifest()` 属 W3 生产 API，统一 manifest 校验与审批构造。bytes 用原始字节，str 先 UTF-8，dict 用 `compact_json`；不是一律 canonical。冻结 4745 B manifest 重现 digest `0ad584415af8743045dd12275a54fa2f43a65395fc8669753416688c9c3e3db5`；非规范 bytes 探针保持原字节身份。artifact digest 仍由调用方提供，未实算（M3）；cwd/workspace 路径元数据校验仍存在。
- **D-ABI-W3-3 (D8; closure ownership):** `ApprovedTool` 在校验与深冻结 descriptor 后自行编译并持有 `parameters_check`/`output_check`；两字段 `init=False`、不参与 equality/hash/repr，调用方不可注入。`dataclasses.replace` 重跑校验和编译；v1 合成项不编译，两个 closure 为 `None`；无进程级 cache。探针覆盖合法/非法实例、派生字段不一致与重建。
- **D-ABI-W3-4 (D12; bounded 14-token vocabulary):** W3 新增八个 host 内部 token：`approved_tool_invalid`、`protocol_invalid`、`tools_invalid`、`duplicate_tool_key`、`workspace_root_invalid`、`timeout_cap_invalid`、`manifest_invalid`、`adapter_digest_mismatch`；复用六个：`invalid_descriptor`、`descriptor_key_mismatch`、`renderer_not_approved`、`renderer_digest_mismatch`、`mixed_descriptor_versions`、`timeout_exceeds_cap`。14 个专用 token 均实测，使用 `RegistryError(token)` 且唯一参数为 token；该闭集只覆盖 W3 新增判定点。`_hex64`、descriptor-digest 不一致及既有进程/制品字段继续保留 v1 prose，不能声称全部构造失败均归一为 token。不增加 `.reason`；新增 token 不进 wire、不进 SQL effect-code 闭集、不进 dispatcher reason。匹配仍属 `AdapterNotFound.reason`，同名复用不改变异常归属。
- **D-ABI-W3-5 (D14; transport J boundary / C.8):** 撤回 C.2 的 W3 `J` 越界 → failure 映射。transport 的 `strict_loads` 在解码时已拒绝 float/指数/unsafe integer/NaN/Infinity/孤立代理项/重复键，归 `bad_frame`（unknown），其后 `J` 越界 success 分支不可达。附录 C.8 明确覆盖 C.2 的该句；float 与 unsafe-int value 探针已通过。Python 对象的 `invalid_tool_output` envelope 兜底仍属 W4，不换宽松 decoder。
- **D-ABI-W3-6 (D15; pending evidence retained):** `manifest.five_field_key` 五字段 expected 被执行，但 status 仍 `m3_pending`；artifact digest 未实算，不计作 M3 证据。`frames_v2.json` 十个 case 仍 `m2_pending`；通过 W3 gate 不更改冻结 status 或 first-production-stage。
- **D-ABI-W3-7 (risk #9; implicit dispatcher coupling):** `plugins.py` 的 `_resource`/`_inspect` 将 `lookup_install()` 结果直接传给 `line_json.run()`。registry 一旦含 `ApprovedPlugin`，这两个路径会按 protocol 自动发 v2 帧；`_tool` 仍经 `match_pin()`，对 v2 以 `protocol_mismatch` fail closed。W3 不改 dispatcher；该既有耦合须由 W4 接线与生命周期 gate 处理，本轮不是 dispatcher v2 完成证据。
- **D-ABI-W3-8 (append-only deviation / pinned spans):** 计划 D4/W3-5/File-by-file 原拟在 §4.1/§7 原地澄清；为保留行锚定 pinned spans，实际追加 C.9（closure/构造 reason）与 C.10（§7 阶段/证据措辞），并追加 C.7/C.8。正文前缀逐字节不变；23 个唯一 span（25 处引用）的行范围、heading、content SHA 全部不变。design SHA `2606aedc7135e7085219d0a9c99d1ccca5c22ee33baee6a82dd6f137ce7cac24` → `269e6bada20c6c18331cc681f385808d638bd6ac9403dd7b484352175f57e4b0`；两个 pin 同批更新，仅 `design_conformance.json` SHA 元数据有 vectors diff。
- **D-ABI-W3-9 (scope / measured limits):** 指定 SQL、六个 W4 文件、五个 W2 模块零 diff；四条 scope audit 均 exit 0，vectors stat 仅一文件 1 insertion/1 deletion。两条 W3 gate 使用 stub，不打开 DB/network/Node；继承 gate 的 PostgreSQL/Node/v1 subprocess 检查照常执行，不能外推为 W3 Node、真实生命周期、文件系统、12 秒预算、renderer 活派发、artifact 或 replay 证明。全部测试使用四项凭据清除前缀与 `UV_NO_ENV_FILE=1`，未调用真实 provider。
