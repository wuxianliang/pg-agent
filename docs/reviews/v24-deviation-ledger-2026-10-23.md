# v24 偏差台账（S1–S4）

> 收尾稿：2026-10-24。本文件是 S1/S2/S3/S4 里程碑的收尾工件，记录各计划 §7 的实施偏差。2026-10-24 本轮七个 gate 串行实跑全部退出 0（命令与结果见矩阵 §0）。规则：**每条与设计稿不一致的实现都必须具名落账，不得静默改规格**；规格修改走「设计稿修订 + Oracle 复审」（pre-plan §1.2）。历史失败追加修正结果，不覆盖、不删去。

裁决来源：`docs/reviews/v24-three-doc-consistency-2026-10-23.md`（chat `untitled-chat-1EDE09`，14 项）、W5/W6 实施裁决（chat `untitled-chat-B38EF4`、`untitled-chat-F1CED0`）。设计稿 652 行、pre-plan 354 行，R5 修订为行内改写，两份文件行号未位移，因此 `L###` 引用继续有效。

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
| D-S4-3 | `blocked_unknown` run 的 steer/respond 返回 `blocked_unknown`（而非 `already_terminal`）；同 run 其它 business settlement 也 W0 墙 | C19/§5.7 | `G2b-N`（sibling/steer/respond 三面）、`G2b-T-10`；S3 G2a-7/G2a-8 的终端循环按 §1.5 对齐 | 裁决 + 声明式对齐 |
| D-S4-4 | 预算按 F3=A 字面实现：admission 预扣 steps/tokens，结算退差，tool_calls 批量扣 | F3=A | `G2b-L` 守恒账（5000=40+4096+864 等）、`G2b-J` 三路 budget seal、`G2b-K` 17/16/5 边界 | 裁决（落地 F3） |
| D-S4-5 | applier 对 settlement 采用「一致性 + 边界」校验，不逐字段重算；gate 逐列断言兜底 | 风险 R2 | `G2b-V`/`G2b-T` 的零写与重交；矩阵 §2.4 逐列 | 实施裁决（已知风险） |
| D-S4-6 | spawn intent 在 S4 不半实现；无 spawn 解释器，未建模的 intent/结果键在 C19 结果键闭集或 `v_executable` 守卫处 W0 拒绝，不建 child run | §2.4 | `48_loop.sql` 无 spawn 分支；`G2b-T-8` 验证 unknown+successors 守卫；**未单独构造 spawn 正例**，按边界披露 | 边界（不是已测能力） |
| D-S4-7 | S4 不做 lease 过期后的自动 reclaim / inspect；effect 可永久 claimed | C18 | D-S4-1 的另一面；矩阵 §4 明确“S4 不承诺自动 reclaim”；归 S6 | 边界 |
| D-S4-8 | 设计 §3.1.2/§5.4 补 `request.digests` 三摘要与派生算法；`runs` 不加列、`result` 不承载 | Oracle 补丁 1 | 设计稿已在 `097ffa5` 更新；`G2b-B/L/V` 断言 request digests 全等 | 设计修订（已落稿） |
| D-S4-9 | continuation 的 `parent_effect_id` = 批次 max-ordinal tool；身份与创建者解耦 | F5=A + max-ordinal | `G2b-A`（parent=ordinal 2）、`G2b-F`（creator 随顺序翻转但 parent/continuation 唯一） | 裁决（细化 F5） |
| D-S4-10 | G2b-G 的“第二 model”`invalid_outcome` 预检是**防御性**的、经公共 API 不可达；可观测契约是直接 INSERT 撞 `u_effects_model_call` 得 `23505`，以及已闭合批次上多余 `claimed` tool 得 `invalid_outcome` W0 | W2.1 / Oracle A | `G2b-G`；防御预检不是协议路径，不声称可达 | **非偏差披露** |

> D-S4-10 与 W2.1 的并发证据补齐都是**非偏差**：前者是防御性预检的可观测性说明，后者只补测试证据（两连接 + Barrier + `pg_blocking_pids`），不改产品语义。

### 1.5 声明式 S1–S3 断言对齐（不是放宽）

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

## 3. 非偏差声明

- **子门拆分不是规格偏差**：S1 内部按 W1–W6 串行拆分，是计划的工项划分，不改变设计稿的任何合同。原 W6（解释器）已由 Oracle 裁决（chat `untitled-chat-B38EF4`）解散，`scope_control` 归 W4、`install`/`host_prepare`/settlement 归 W5，ACL 顺延为 W6；这是**排期**调整，不是语义变更。
- **T1/T2 术语不是偏差**：T1 = 资格提交（claim 的 COMMIT）、T2 = 外部结果接纳（settlement 事务），由设计稿 §7.1 定义，R5 已写入正文；计划与矩阵沿用该定义。
- **W5 判据不回填 claim**：claim 的判据由 W3 gate 守住（Oracle 裁决 ①）；W5 只保留 S4–S6，不是覆盖率下降。
- **G3 子门拆分不是规格偏差**：G3a 归 S2、G3b 归 S3，是 pre-plan §2.2 已冻结的施工口径；S2 当时只证 activation-pin 半部；S3 本轮 G3b-1…5 实跑通过后父门为「完成（G3a+G3b）」；claimed/unknown 完整 settlement release 已由 S4 的 G2b-R/S 补齐（terminal 同 advance 释放、unknown 保留自身 pin），不再悬空。
- **S1 夹具/ACL 对齐不是放宽**：S2 把 canonical 列表从 6 文件扩到 7、`test_g1.py` 的 G1-A 允许 `validate_and_apply_delta` 含 `UPDATE v24.effects`、ACL 期望集合加入 `resolve`/`fiber_control`/`dispose`。三者都是「新函数集合」的必然对齐，断言只增不减；S3 W1 后 `T` 断言 advance 是唯一可写 DEFINER，另有封闭只读 DEFINER allowlist；`run_owner`/`run_projection` 内部且不授予协议角色 EXECUTE。

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

S1 四次是夹具缺陷；S2 六次是夹具/测试断言缺陷或局部 SQL 质量问题；S4 五次是评审发现/测试证据缺口与一次守卫修复（W4 BLOCK）。均非设计语义变更，修正后同一 gate 退出 0，未删断言、未降低断言强度。

## 5. 验收结果与仍未关闭的披露

本轮七个 gate 依序退出 0/0/0/0/0/0/0（矩阵 §0）；G2 父门为**完成（G2a+G2b）**，G3 父门为**完成（G3a+G3b）**。`runs` 已有 S3 start writer，revision 从 1 起并随可见状态变化递增。错误码为 **22 个有生产者、1 个未产生**：`blocked_unknown` 由 S4 新增；`cleanup_cycle` / S5 仍无生产者。`blocked_unknown` 的 W0 墙与 W1 结算写类分列见矩阵 §3.1。

- **G2b 已完成**：G2b-A…V 全绿，G2b-T-1…T-10 十条具名零写负例通过。
- **G3b-2 完整 pin 排空已完成**：G2b-R/S 证明 terminal 同 advance 释放；unknown 只保留自身 pin。
- **inspect 收敛未验证**：S4 仍不打开 `inspect_resource` claim；完整收敛归 S5。
- **owner 级联/scope close/完整 dispose 闭包未验证**：S4 不扩展清理闭包；其余归 S5。
- **FakeLLM/FakeTool/FakeHost 不是 transport 证明**：纯进程内、无套接字；真实 IO 不在 gate 内。
- **完整 recovery / 并发矩阵**：覆盖两个 journal 窗口、G1-L、G3a-F、G3b-5、G2b-E/F/O；G3b-4 是顺序场景；完整 recovery 归 S6，三面并发矩阵归 S7。
- **S4 不做自动 reclaim/inspect**：过期 lease 只 `stale_claim`，effect 可永久 claimed（D-S4-1/D-S4-7）。
