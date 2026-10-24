# v24 偏差台账（S1–S5）

> 收尾稿：2026-10-24。本文件是 S1/S2/S3/S4/S5 里程碑的收尾工件，记录各计划 §7 的实施偏差。**S5 W1–W4 已实现，W5 为收尾（本台账、矩阵、README 与本地提交）**；2026-10-24 本轮八个 gate 串行实跑全部退出 0：load、`s1/setup_db.py --self-check`、`s1/test_ddl.py`、`s1/test_g1.py`、`s2/test_g3a.py`、`s3/test_g2.py`、`s4/test_g2b.py`、`s5/test_g4.py`（命令与结果见矩阵 §0）。规则：**每条与设计稿不一致的实现都必须具名落账，不得静默改规格**；规格修改走「设计稿修订 + Oracle 复审」（pre-plan §1.2）。历史失败追加修正结果，不覆盖、不删去。

裁决来源：`docs/reviews/v24-three-doc-consistency-2026-10-23.md`（chat `untitled-chat-1EDE09`，14 项）、W5/W6 实施裁决（chat `untitled-chat-B38EF4`、`untitled-chat-F1CED0`）、S5 计划与逐 W 实施裁决（chat `untitled-chat-DFBC85`，2026-10-24：F1=A、F2=A、F2a=A、F2b=A、F3=A、F3a=A、F4=B′、F5=A、D-S5-1=A）。设计稿 652 行、pre-plan 354 行，R5 修订为行内改写，两份文件行号未位移，因此 `L###` 引用继续有效。

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
| D-S5-8 | 30 的 `installs→child installs` 闭包边修正为 root install 展开其 fiber 的 child installs。**实际落地**：该边只对 close 命令加入；`dispose` 仍走既有 sibling 边（root 无 owner 对，不展开），child 由 `dispose_stage` 的 `FOR UPDATE` 在 helper 内自行锁 | 计划 W1 步骤⑤、§10.1 R9、§11 D-S5-8；W1 注记⑥ | `30_advance.sql` close 的 owner-descendant 边（`fibers f ... ci.owner_fiber_id=f.fiber_id`）；`dispose_stage` pass 1 的 `FOR UPDATE`；G4-W1/G4-P 证明 dispose 的 child 锁与 child-before-owner 序；**dispose 闭包边未扩**，锁序留 S7 评估 | 部分落地 + 显式披露（不是全量 D-S5-8） |
| D-S5-9 | `cleanup_cycle` 的 admission 检查是**防御性**的：公共路径不能构造 owner/dependency 环（owner pair 由活 fiber 派生，公共 API 不能改 owner 列）；只有 seeded/外部修复图可达，命中仍 W1 failed receipt + 领域零写 | 计划 F5=A、§10.2、C24；D-S5-9 | `40_interpreters.sql:2869-2873`（owner 活性之后、任何行构造之前）；G4-E 以 seeded 环直接调 `v24.install`，得 `cleanup_cycle`、path 长 4、domain 零写、installs 计数不变；**不声称公共路径可达** | 边界披露（防御性，不是公共负例） |
| D-S5-10 | 跨 scope 的 child install 通过 owner 边递归纳入 close 闭包（`cleanup_close_closure`），不收紧 admission；dependency 邻居不算 close 义务，由 live pin / host effect blocker 表达 | 设计 §2.4/§6.2（admission 不要求同 scope）；计划 C24、R10、D-S5-10 | `cleanup_close_closure` 的递归 owner CTE（无 scope 过滤）；`scope_closable` 的 pins/effects blocker；G4-G 覆盖 scope 父子；**无跨 scope child install 专用 fixture**（代码路径成立，证据缺口留 S7/后续） | 裁决（不收紧 admission）+ 证据缺口披露 |
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

## 2. 实施披露（不是规格偏差）

以下条目改动的是 DDL 细节或测试夹具，不改变设计语义；列在此处是为了让复核者能对着代码找到它们。

| # | 披露 | 计划原文 | 实际 | 理由 / 证据 |
|---|---|---|---|---|
| I1 | `f_effects_parent`、`f_events_effect` 为 DEFERRABLE | 计划列为普通 FK | DEFERRABLE | 与同组 FK 的延迟策略一致；`D.deferred` 证明延迟 FK 在 COMMIT 闭合 |
| I2 | `c_installs_ident` 重命名为 `c_installs_identity_len` | 计划用 `c_installs_ident` | 改名 | 与唯一索引 `u_installs_ident` 重名，PG 允许但审计易混；`D.catalog` 断言约束名 |
| I3 | 夹具 schema 闭集为 `{v24, v24_fake}` | 计划只列 `v24` | 加入 FakeHost journal schema | journal 必须与十表分离；`S._assert_closed_catalog` 仍断言第三 schema 被拒 |
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
| W1（`a89d936`，6 文件） | `46_cleanup.sql` **NEW** +552；`40_interpreters.sql` +75/−107；`load.py` +2；`s1/setup_db.py` +1；`s5/test_g4.py` **NEW** +619；计划 +964。`30`/`50`/S1–S4 test 0 diff | `cleanup_edges`/`cleanup_closure`/`cleanup_cycle`/`cleanup_graph`/`cleanup_pending`/`cleanup_slots` + `dispose_stage`（7 个 INVOKER，无 GRANT）；`interpret_dispose` 改为委托；`command_dispose` validator 扩到 install + owner 后代 / install-scoped release id / 0..n−1 ordinal / 后代事件，footprint 仍 `installs|fibers` 且无 insert | 合并 DAG 的 `depth` 用 longest-path-to-sink rank；pass 1 parent-first 写 intent、pass 2 反向 child-before-owner 判 release；stage error 用 `write:true` + failed command；cascade 在 `dispose_stage` 内自行锁 child |
| W2（`d4dfe92`，9 文件） | `48_loop.sql` +4/−4；`30_advance.sql` +64；`40_interpreters.sql` +407/−18；`46_cleanup.sql` +212/−40；`s2/test_g3a.py` +47/−9；`s3/test_g2.py` +9/−6；`s4/test_g2b.py` +14/−9；`s5/test_g4.py` +692/−4；计划 +21/−2 | **无新函数名**；inspect 结算 **INLINED** 在既有 `validate_and_apply_install_delta`；`dispose_stage` 增 prepare-inspect / release-unknown / direct-tombstone 分支；`claimable_kinds()` 追加第 5 项 `inspect_resource` | inspect request 冻结为 6 键、`ordinal=0`、确定性 id；claim 闸门校验 target kind/status/quiesced/install/reservation/digest/id/parent/pin；`prepare_failed` 直墓碑为 G4-J② 的最小实现 |
| W3（`1ae1b85`，5 文件） | `30_advance.sql` +64；`40_interpreters.sql` +705/−21；`46_cleanup.sql` +117/−3；`s5/test_g4.py` +348/−2；计划 +17/−1 | `cleanup_close_closure`、`scope_closable`；`dispose_stage` 接受 `mode='close'`；40 的 close phase 机（request→drain→retire→cascade→barrier→finalize）；30 的 close 闭包发现（child scopes/runs/installs、owner 后代、全 episodes、pins） | close 校验 **INLINED** 在 `validate_and_apply_delta`；`fiber_control(on)` 的 `scope_closed` 早退只写 `failure_seq/failure`；30 锁序未改；旧 `dispose_stage(...,'close')` 负例改正向 |
| W4（`2272b71`，4 文件） | `46_cleanup.sql` +548/−40；`40_interpreters.sql` +319/−99；`s5/test_g4.py` +904/−16；计划 +11 | `install_disposed_ok`（install/effect/quiesced/assumed_fibers 四参）、`install_disposed_ok_except_release`（install/release/assumed_fibers 三参）、`deactivate_stage`；`dispose_stage` 增 release/close 纤维阶段 | 每阶段 ≤16 行（`v_rows + stage_rows > 16` 即 blocked）；close cascade 对 `dispose_pending` 且无 ready/claimed release/inspect 的 install 重入；release failure 新 key 新 id/reservation；close-only 阶段不并发 release |

关键实施选择（与计划草稿/命名有出入的，按代码记录）：

- **`cleanup_graph.depth` = longest-path-to-sink rank**：计划草稿的 seed depth 无法保证 scope-seeded 端点顺序；实现改为对闭包内简单路径取最长 rank（0 为 sink），`ORDER BY depth DESC, node_id` 保证每条边 u→v 满足 rank(u)>rank(v)。G4-A（B<A<R、A<P）与 G4-E（65-chain depth≤64）是证据。
- **stage error 用 `write:true` + failed command**：`dispose_stage` 返回 `{error}` 时，`interpret_dispose` 以 `write:true` 只写 failed command effect + request receipt，丢弃整个 stage delta（`40_interpreters.sql:3301-3306`）；这采用 raw W1/G4-E 的写类，**不是** §5.2 草稿的 `write:false`。close cascade 同形（`:315-318`）。G4-E/G4-M-5 断言 domain 零写 + effect/request 各 +1。
- **W2 inspect 结算 INLINED 在既有 install delta applier**：G1-A 把「可写 `v24.effects` 的函数」钉死为 allowlist，`test_g1.py` 又不在本轮允许修改路径；因此不复用计划 §5.5 的 `validate_and_apply_inspect_delta` 函数名，逻辑内联在 `validate_and_apply_install_delta`。**没有** `inspect_effect_id` 函数——id 公式直接写在 `dispose_stage` 的两处 inspect 分支里。
- **W3 close 校验同样 INLINED**：`command_scope_control` 的 close delta 校验/落库内联在 `validate_and_apply_delta`，没有 `validate_and_apply_scope_delta` 函数名；原因同上（G1-A allowlist）。语义仍按 §5.4 的七表白名单。
- **30 的 child-install 闭包边未在 W1 扩展（W1 注记⑥）**：`dispose` 仍用既有 sibling 边；W3 只给 close 命令加了 owner-descendant 边。`dispose` 的 child 由 `dispose_stage` pass 1 的 `FOR UPDATE` 自行锁。这是 D-S5-8 的**部分落地**，锁序影响留 S7 评估（见 §1.5 D-S5-8）。
- **未创建 `v24/s5/fake_cleanup_host.py`**：计划 §8.2/W5 列为 NEW，实际没有该文件。host_prepare/host_release 回执由 `settle_release()` 直接提交（claim + success body `{}`）；inspect 回执由 `inspect_receipt()` 从存储的 6 键 request 生成冻结 body 后提交；负例/边界用 seeded effect 或已 claim 的 effect。属夹具合并，先例是 S4 的 `FakeTool` 与 `FakeLLM` 同置 `fake_llm.py`、未单独建 `fake_tool.py`；矩阵 §2.5 与 `v24/s5/README.md` 也按「回执直接经 `advance` 提交、无独立 host 进程」记录。
- **`test_g4.py` 打印 `[passed] v24 S5 W1-W4`**（计划 §7 草稿写的是 W1-W5）：W5 只做收尾，不新增断言；终判由控制器在八个 gate 全 0 后给出。G4-A…Q 17 个 tag 全部出现。
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

**S5 的诚实口径**：在记录的 S5 W1–W4 轮次中，八门在每轮**最终运行**均退出 0（controller L1），**没有可记录的 gate 红**，也没有 S4 W3/W4 那样的 Oracle BLOCK。上表四条是 **pre-gate 实施修正**（提交前由实现者发现并修，或 W3 的合同对齐），不是 gate 失败；「gate 红」与「pre-gate 实施修正」不得混为一谈。

S1 四次是夹具缺陷；S2 六次是夹具/测试断言缺陷或局部 SQL 质量问题；S4 五次是评审发现/测试证据缺口与一次守卫修复（W4 BLOCK）；S5 W1–W4 无 gate 红，四条均为 pre-gate 实施修正或合同对齐（见上）。均非设计语义变更，修正后同一 gate 退出 0，未删断言、未降低断言强度。

## 5. 验收结果与仍未关闭的披露

本轮八个 gate 依序退出 0/0/0/0/0/0/0/0（load、`s1/setup_db.py --self-check`、`s1/test_ddl.py`、`s1/test_g1.py`、`s2/test_g3a.py`、`s3/test_g2.py`、`s4/test_g2b.py`、`s5/test_g4.py`；矩阵 §0）。G2 父门**完成（G2a+G2b）**，G3 父门**完成（G3a+G3b）**，**G4 父门完成（G4-A…Q 17/17）**。`runs` 的 S3 start writer、revision 语义不变。错误码为 **23 个有生产者、0 个未产生**：`cleanup_cycle` 现有三个生产者——`v24/sql/46_cleanup.sql:852`（`dispose_stage` 根检查）、`46_cleanup.sql:879`（队列逐节点检查）、`v24/sql/40_interpreters.sql:2871`（admission 防御检查）；`blocked_unknown` 的 W0 墙与 W1 结算写类分列见矩阵 §3.1。

- **G4 已完成**：`s5/test_g4.py` 打印 `[passed] v24 S5 W1-W4`，G4-A…Q 全部出现；17 条具名断言无 skip/TODO。
- **S5 已封闭的 S4 披露**：inspect 收敛（G4-H/I/J/K/N）、owner 级联/child-before-owner（G4-A/B 与 `[G4-W1]` cascade）、consumer-before-provider（G4-C）、贡献 DESC 与墓碑（G4-D/P/Q）、scope close phase 机与 close 后无新准入（G4-G/O）、失败/unknown 不写终态（G4-F/L/M）。
- **S5 残差（S6/S7）**：崩溃/恢复/自动 reclaim 与 inspect 的外部真实性归 **S6**；三面并发矩阵与锁序/无饥饿证明归 **S7**。S5 只证串行 request-key 阶段（每个新 key 一个 bounded phase、≤16 行/successor、无 worker/自动推进）；`cleanup_pending` 非严格递减、close 依赖新 key（§3），不得外推为「自动收口」。
- **FakeLLM/FakeTool/FakeCleanupHost 不是 transport 证明**：纯进程内、无套接字；S5 甚至没有 FakeCleanupHost 文件（§2.2），回执直接经协议提交。真实 IO 不在 gate 内。
- **仍未关闭的披露**：D-S5-8 的 dispose 闭包边未扩（锁序留 S7）；D-S5-10 无跨 scope child install 专用 fixture（代码路径成立，证据缺口）；A-S5-1…9 的逐条理由见 §1.6。
- **历史口径更新**：S4 的「22 个有生产者、1 个未产生」由本节更新为 23/0；S1–S4 的其它验收结论与边界（FakeLLM/FakeTool、真实 IO、S6/S7）继续有效。
