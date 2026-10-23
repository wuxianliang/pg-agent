# v24 偏差台账（S1 + S2）

> 定稿：2026-10-23。本文件是 S1/S2 里程碑的收尾工件，分别是 [S1 计划 §7](../plans/v24-s1-kernel-2026-10-23.md) 与 [S2 计划 §7](../plans/v24-s2-capability-2026-10-23.md) 的落位记录。规则：**每条与设计稿不一致的实现都必须具名落账，不得静默改规格**；规格修改走「设计稿修订 + Oracle 复审」（pre-plan §1.2）。历史失败追加修正结果，不覆盖、不删去。

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

## 2. 实施披露（不是规格偏差）

以下条目改动的是 DDL 细节或测试夹具，不改变设计语义；列在此处是为了让复核者能对着代码找到它们。

| # | 披露 | 计划原文 | 实际 | 理由 / 证据 |
|---|---|---|---|---|
| I1 | `f_effects_parent`、`f_events_effect` 为 DEFERRABLE | 计划列为普通 FK | DEFERRABLE | 与同组 FK 的延迟策略一致；`D.deferred` 证明延迟 FK 在 COMMIT 闭合 |
| I2 | `c_installs_ident` 重命名为 `c_installs_identity_len` | 计划用 `c_installs_ident` | 改名 | 与唯一索引 `u_installs_ident` 重名，PG 允许但审计易混；`D.catalog` 断言约束名 |
| I3 | 夹具 schema 闭集为 `{v24, v24_fake}` | 计划只列 `v24` | 加入 FakeHost journal schema | journal 必须与十表分离；`S._assert_closed_catalog` 仍断言第三 schema 被拒 |
| I4 | G1-A 允许 INVOKER `validate_and_apply_install_delta` 含 `UPDATE v24.effects` | 计划「只有 advance 体内出现 UPDATE」 | 允许该具名、不可授权的 INVOKER helper | W5 需要与 advance 共享 delta 应用；`prosecdef=true` 仍恰为 `{advance}`，唯一写权威未放宽（矩阵 §1.1） |
| I5 | settlement mode 由 `p_outcome.class` 推断 | 计划未指定推断来源 | class 决定 success/failure/unknown | 避免 delta 自选执行域；`T.install_settlement_w5` 三态断言 |
| I6 | `install` 的 `preparing` vs `installed` 由 manifest 决定 | 计划只写状态机 | 空 `provides` + 零长 artifact ⇒ 纯声明 `installed` | 让 `host_prepare` 三态都可达；`T.install_settlement_w5` 覆盖 |
| I7 | S1 的 `invalid_outcome` 是**零写预检**，不是 W1 稳定失败 receipt | §4.16 错误表标 W1；设计稿 L279 要求「可审计确定失败」 | S1 保持零写；S3 补稳定失败 receipt | S1 唯一可达生产者是结算 delta 预检（`validate_and_apply_install_delta` 直接返回 error，未进入 DML），结算不写 request 行，没有承载 receipt 的位置。S1 未实现 `tool_calls` 超限路径，因此该 W1 分支不可达。`T.install_settlement_w5` 实测该路径十表快照不变、effect 仍 `claimed`；矩阵 §2.1 已分列「计划 W1 / S1 零写」 |

## 3. 非偏差声明

- **子门拆分不是规格偏差**：S1 内部按 W1–W6 串行拆分，是计划的工项划分，不改变设计稿的任何合同。原 W6（解释器）已由 Oracle 裁决（chat `untitled-chat-B38EF4`）解散，`scope_control` 归 W4、`install`/`host_prepare`/settlement 归 W5，ACL 顺延为 W6；这是**排期**调整，不是语义变更。
- **T1/T2 术语不是偏差**：T1 = 资格提交（claim 的 COMMIT）、T2 = 外部结果接纳（settlement 事务），由设计稿 §7.1 定义，R5 已写入正文；计划与矩阵沿用该定义。
- **W5 判据不回填 claim**：claim 的判据由 W3 gate 守住（Oracle 裁决 ①）；W5 只保留 S4–S6，不是覆盖率下降。
- **G3 子门拆分不是规格偏差**：G3a 归 S2、G3b 归 S3，是 pre-plan §2.2 已冻结的施工口径；S2 只证 activation-pin 半部，run-pin 半部在矩阵标「未验证 / S3」，不计入覆盖。
- **S1 夹具/ACL 对齐不是放宽**：S2 把 canonical 列表从 6 文件扩到 7、`test_g1.py` 的 G1-A 允许 `validate_and_apply_delta` 含 `UPDATE v24.effects`、ACL 期望集合加入 `resolve`/`fiber_control`/`dispose`。三者都是「新函数集合」的必然对齐，断言只增不减；`T` 仍断言唯一 DEFINER 是 advance。

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

S1 四次是夹具缺陷；S2 六次是夹具/测试断言缺陷或局部 SQL 质量问题，均非设计语义变更。修正后同一 gate 退出 0，未删断言、未降低断言强度。

## 5. 仍未关闭的披露

- **`revision = 0` 的 C2 空洞**：S1/S2 不写 `runs`，`advance` 返回 0。S3 开工前必须回写 C2，否则 poll 游标语义会错。
- **G3b 未验证**：run pin、withdraw 后新 run、claim/close 双序归 S3；S2 只证 activation-pin 半部。
- **inspect 收敛未验证**：S2 只把 `prepare_unknown` 停在 `dispose_pending`；完整收敛归 S5。
- **owner 级联/scope close/完整 dispose 闭包未验证**：S2 只做 leaf dispose；其余归 S5。
- **FakeHost 不是 transport 证明**：纯进程内、无套接字；真实 IO 归后续 stage。
- **完整 recovery / 并发矩阵**：只覆盖两个 journal 窗口、G1-L 与 G3a-F；其余归 S6/S7。
