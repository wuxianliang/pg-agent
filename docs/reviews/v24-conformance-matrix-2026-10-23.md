# v24 S1 覆盖矩阵

> 定稿：2026-10-23。本文件是 S1 里程碑的收尾工件之一。断言口径以 [S1 计划 §5](../plans/v24-s1-kernel-2026-10-23.md) 为准，设计语义以 [设计稿](../designs/v24-pg-agent-2026-10-22.md) 为准。矩阵只记录**本次实跑**看到的证据；未运行、未实现、无生产者的条目一律显式标注，不计为已覆盖。

## 0. 运行环境与最终证据

环境：PostgreSQL 18.4（pgembed），Python 3.12，psycopg2 2.9.12，工作树 `.claude/worktrees/v99`，分支 `v24`。

简称：`T`=`v24/s1/test_g1.py`，`D`=`v24/s1/test_ddl.py`，`S`=`v24/s1/setup_db.py`，`L`=`v24/load.py`，`F`=`v24/s1/fake_host.py`。`T.state` 对十表做全列全行快照（含 bytea、receipt、claim 字段）；`T.rejects_without_writes` 在拒绝后**提交**再比对快照，避免把写入藏在未提交事务里。

| # | 命令 | 退出码 |
|---:|---|---:|
| 1 | `uv run python v24/load.py` | 0 |
| 2 | `uv run python v24/s1/setup_db.py --self-check` | 0 |
| 3 | `uv run python v24/s1/test_ddl.py` | 0 |
| 4 | `uv run python v24/s1/test_g1.py` | 0 |

### 0.1 历史失败（追加修正结果，不覆盖）

| 阶段 | 失败 | 根因 | 修正后 |
|---|---|---|---|
| W5 首次 | `test_g1.py` 退出 1：`AmbiguousColumn: column reference "manifest" is ambiguous` | `interpret_install` 内局部变量与列名重名 | 重命名局部变量为 `parsed_manifest`，同一 gate 转 0 |
| W6 首次 | `test_g1.py` 退出 1：ACL 探针期望 `42501`，实得 `428C9` | UPDATE 探针取表首列；`events.event_id` 是 `GENERATED ALWAYS AS IDENTITY`，解析期错误先于执行期权限检查 | 探针只选 `attidentity='' AND attgenerated=''` 的列；转 0 |
| W6 第二次 | `test_g1.py` 退出 1：`permission denied for table effects` | 影子 TEMP 对象在 `SET ROLE` 前创建，属主是 LOGIN 角色；切到组角色后不可读 | 改为 `SET ROLE` → 建影子 → 断言 → DROP → `RESET ROLE`；转 0 |
| W6 第三次 | `test_g1.py` 挂起（>600s，转后台后终止） | G1-B 回滚注入的触发器在 owner 未提交事务中持有 `v24.scopes` 的 ACCESS EXCLUSIVE，阻塞 admin 的 INSERT | 触发器提交后再注入、探针结束显式 DROP；转 0 |

以上均为**测试夹具/探针缺陷**，不是产品缺陷；四次失败都在同一 S1 提交前修正，未以降低断言的方式绕过。

## 1. 具名断言 G1-A … G1-R

| ID | 生产者（本次实跑） | 断言要点 | 结果 |
|---|---|---|---|
| G1-A | `T.catalog`（L112–171） | `prosecdef=true` 的函数恰为 `{advance}`；advance 的 `proconfig` 为 `search_path=pg_catalog, v24`；四个纯 helper 均 INVOKER+IMMUTABLE；无 `claim_*`/`lease_*`/`acquire_*`；含 `pg_advisory_xact_lock` 的函数只有 advance；两个 wrapper 为 INVOKER、体内有 `v24.advance(` 且无任何写语句；全部函数属主为 `v24_owner`；`aclexplode` 断言 PUBLIC 无 EXECUTE；advance 源码中 G 的 `PERFORM` 先于 reads 的 `FROM` 与任何 `FOR UPDATE`，八段锁语句的出现次序为 scope→run→effect→install→fiber→episode→slot→pin；函数体无 `http`/`dblink`/`pg_sleep`/`current_setting`/`current_user`；23 个错误码全被 `error_v1` 接受，未知码得 `22023` | 通过 |
| G1-B | `T.scope_control_w4`（L458–508） | 一次 command 提交后：scope 行 +1、effect=`succeeded`、request 行存在且 `effect_id` 相等、恰 1 条事件；另注入 `BEFORE INSERT ON v24.events` 触发器（`23514`）。冻结写序是 domain → effect → request → events，因此失败发生在 scope/effect/request **已写之后**；失败后十表全快照与注入前逐字节相等，证明整事务回滚而非写前拒绝 | 通过 |
| G1-C | `T.install_settlement_w5`（L510–724） | T2 三路故障：delta 预检拒绝（`invalid_outcome`）、事件触发器 `23514`、install CAS 拒绝（`receipt_conflict`）；每路后十表快照相等、effect 仍 `claimed`、无 successor、无 receipt 写 | 通过 |
| G1-D | `T.scope_control_w4`、`T.command_prefix`（L292–329） | 同 request 同 bytes 二次 advance 返回与首次 **byte-equal** 的封套；提交后十表快照相等；事件计数不变 | 通过 |
| G1-E | `T.command_prefix` | 同键不同 payload ⇒ `request_conflict`，`rejects_without_writes` 全快照相等（提交后复检） | 通过 |
| G1-F1 | `T.command_prefix` | fixture 预置同键 request 行后，用一个与派生值不等的 `effect_id` 提交：无论 bytes 相同或不同，均得 `effect_id_conflict`，不得得 `replay`/`request_conflict`；零写 | 通过 |
| G1-F2 | `T.scope_control_w4`、`T.install_settlement_w5` | 同一 `(principal,request_key,kind)` 的 wrapper 两次派生同一 `effect_id`；二次调用返回首次 response；`w5-pure` 的 replay 与首次 byte-equal 且全快照不变 | 通过 |
| G1-G | `T.claims_and_receipts`（L332–392） | 旧 token（attempt/fence 各减 1、或 owner 伪造）对 success/failure/unknown 三类均 `stale_claim` 零写；effect 保持 `claimed` | 通过 |
| G1-H1 | `T.identities_and_matrix`（L240–289） | 真实 LOGIN 连接：`session_user`=LOGIN 角色；`SET ROLE v24_service` 后 `current_user` 变而 principal 不变，且 principal(session_user) ≠ principal(current_user)；claim 的 `owner` 等于 `session_user` | 通过 |
| G1-H2 | `T.claims_and_receipts`、`T.install_settlement_w5` | settlement 的 owner 比对对象是 `effects.claim_owner`：`owner="spoof"` 与历史 token 均 `stale_claim` 零写 | 通过 |
| G1-I | `T.install_settlement_w5` | claim 提交前 FakeHost 拒绝执行（错误文本含 `claim COMMIT`）且 journal=0；提交后 journal=1 而 effect 仍 `claimed`（IO 已返回、T2 未提交）；过期重 claim 得 `attempt=fence=2`；旧 token 结算 `stale_claim`；两个 crash 窗口 journal 分别为 0/1，且都不伪造结算 | 通过 |
| G1-J | `T.install_settlement_w5` | `installed`/`prepare_failed`/`prepare_unknown` 三态各自由 success/failure/unknown 到达；`resource_quiesced_at` 仅 unknown 为 NULL；`claim_owner`/`lease_until` 结算后清空；`attempt_no=fence=1` 保持不变 | 通过 |
| G1-J2 | `T.scope_control_w4` | `create_root`：`route_path=[id]`、`root_id=id`、`parent_id IS NULL`；`create_child`：`route_path = parent.route_path \|\| new_id` 且 `root_id` 继承；`close` 只写 `close_requested_at`，`closed_at` 保持 NULL；关闭后 `create_child`/`install` 得 W1 `scope_closed`（effect=`failed` 且有 request 行保存该错误） | 通过 |
| G1-K | `T.install_settlement_w5`、`D.negatives` | 同 receipt 二次提交不产生第二条 `(effect,entity,kind)` 事件；`install` entity 的 `seq` 恰为 `[1,2]`；append-only 触发器对 UPDATE/DELETE/TRUNCATE 三语句各得 `23514`（DDL 侧） | 通过 |
| G1-L1 | `T.locks`（L414–454） | 阻塞者持 `pg_advisory_xact_lock(24,1)` 后，`pg_locks` 中出现 `(advisory,24,1,objsubid=2)` 且 granted；第二连接调 advance 在该锁上 `NOT granted` 且 `wait_event_type='Lock'`；**未用 sleep 猜顺序**，轮询真实锁证据 | 通过 |
| G1-L2 | `T.locks` | 该 backend 阻塞期间，`pg_locks` 中其 `relation IS NOT NULL AND granted` 的 `v24.*` 行锁计数为 0 | 通过 |
| G1-M | `T.closure_retry`（L395–411） | 引用不存在的 `install_id` ⇒ `retry_with_closure` 零写；补上该 install 行后，**新事务**在 G 下重新发现闭包并成功 claim | 通过 |
| G1-N | `S._assert_closed_catalog`（L540–555） | 应用 schema 恰为 `{v24, v24_fake}` 且属主均为 `v24_owner`；base table + partitioned 恰为十表；view/materialized view 为空；扩展为空；测试另断言创建第三 schema 会被拒 | 通过 |
| G1-O | `D`（整文件，7 组） | owner 身份绕过 ACL 的直接 DML：partial unique 冲突、复合 FK 拒绝、`c_pins_xor`、`c_scopes_path_end`、命令 claim 保留列、append-only、T2–T4 冻结字段、延迟 FK 在 COMMIT 闭合、E1→E2/slot/pin 的「先关旧再插新」次序、缺 request 的 effect 与子 scope 路径在 COMMIT 被拒 | 通过 |
| G1-P | `T.permissions`（L727–848） | 三个协议角色各 30 条 DML（10 表 × INSERT/UPDATE/DELETE）全部 `42501`；已授权 EXECUTE 集合逐角色精确相等（admin 无 install，service/operator 有）；`SET ROLE` 到 owner/其他协议角色/自身及 `SET SESSION AUTHORIZATION` 均 `42501`；`CREATE TABLE v24.*` 与私有 helper 调用 `42501`；TEMP + `search_path=pg_temp,v24` + `pg_temp.principal_id` 影子函数不能改写入口行为；`v24_owner` 真实 LOGIN 可写十表且无协议 EXECUTE 成员资格 | 通过 |
| G1-Q | `T.shapes`（L174–237）、`T.claims_and_receipts` | class 闭集 5 值；6 个非闭集（含 `"COMMAND"`、JSON `null`、`7`）各 `invalid_args` 零写；8 类形状族（command/claim 携非 null claim、>1 MiB、深度>32、键数>200、未知 kind、`lease_ms` 越界、unknown 携 successors/intents、canonical_bytes 不匹配）各零写；`lease_ms ∈ {1, 300000}` 可达且签发 token；五个 class 各达唯一分支 | 通过 |
| G1-R | `T.expect_envelope`（L107–110）及各分支 | 封套精确等于 `{v,disposition,effect_id,emitted,revision,claim}`：仅 claim+committed 时 `claim={attempt,fence,session_user}`；claim 的 deferred 与 command/settlement 全部分支 `claim=null` | 通过 |

### 1.1 G1-A 的断言细化（披露，不是放行）

W5 需要一个与 advance 共享 delta 应用的 INVOKER helper `v24.validate_and_apply_install_delta`，其体内含 `UPDATE v24.effects`。为保持「单一写权威」的可证伪性，G1-A 的静态检查细化为：

- `prosecdef=true` **仍恰为** `{advance}`（这是唯一写权威）；
- 含 `UPDATE v24.effects` 的函数只允许 `{advance, validate_and_apply_install_delta}`，且后者必须 INVOKER、不属于可授权入口（`has_function_privilege` 断言）；
- 含 `pg_advisory_xact_lock` 的仍只允许 advance。

即：放宽的是「源码里只能出现一处 UPDATE 文本」，未放宽「只有一个 DEFINER、只有一个可调用写入口」。

## 2. 错误码覆盖（23 码）

`error_v1` 接受全部 23 码（签名冻结，G1-A 已逐码断言）。**能产生**与**能接受**是两件事，下表分开记。

### 2.1 S1 有生产者的 10 码

| 码 | 写类 | 生产者证据 |
|---|---|---|
| `invalid_args` | W0 | `T.shapes`（6 非闭集 + 8 形状族）、`T.command_prefix`（malformed scope payload）、`T.claims_and_receipts`（对已结算/取消 effect 发 claim） |
| `unauthorized` | W0 | `T.identities_and_matrix`（admin 以外提交 create_root；非 service 提交 claim/settlement） |
| `request_conflict` | W0 | `T.command_prefix`（同键异 payload） |
| `effect_id_conflict` | W0 | `T.command_prefix`（C0 先于 replay）、`T.claims_and_receipts`（claim/settlement 的派生 id 不匹配） |
| `receipt_conflict` | W0 | `T.claims_and_receipts`（已结算异 digest）、`T.install_settlement_w5`（install 已非 preparing） |
| `stale_claim` | W0 | `T.claims_and_receipts`（attempt/fence/owner 四组合）、`T.install_settlement_w5`（spoof owner、旧 crash token） |
| `retry_with_closure` | W0 | `T.closure_retry`（悬空 install 引用） |
| `scope_closed` | W1 | `T.scope_control_w4`、`T.install_settlement_w5`（关闭后 create_child / install，receipt 与 effect 同事务落盘） |
| `install_identity_conflict` | W1 | `T.install_settlement_w5`（artifact digest 或 manifest 字节不同；二次提交返回同一错误） |
| `invalid_outcome` | W1（计划）/ S1 零写 | `T.install_settlement_w5`（delta 预检拒绝，十表快照不变、effect 仍 `claimed`）。S1 唯一可达生产者是结算预检，返回前不写任何行；W1 的「可审计确定失败」需要 request/effect 落盘路径，要到 S3 的 tool_calls 超限场景才存在。记台账 I7 |

> 写类注：§4.16 把 `invalid_outcome` 标为 W1，但 S1 的可达路径是解释器/应用器的预检拒绝，**实测零写**。设计稿 L279 要求该类拒绝进入「可审计确定失败」，即应有稳定失败 receipt；S1 尚无承载它的 request 行（结算路径不写 request）。这不是设计语义被改动，而是 S1 只实现了防御性预检分支；S3 引入 `tool_calls` 超限时必须补上稳定失败 receipt，已记台账 I7。

### 2.2 S1 **不能产生**的 13 码（不得计为已覆盖）

| 码 | 预定阶段 | S1 状态 |
|---|---|---|
| `not_found_or_denied` | S3 | 未产生：S1 无读函数 |
| `stale_generation` | S3 | 未产生：无 generation CAS |
| `registration_stale` | S3 | 未产生：无 wait handle |
| `already_terminal` | S3 | 未产生：无 terminal 动词；claim 对已结算效果按裁决返 `invalid_args` |
| `owner_closing` | S2 | 未产生：无 child install admission |
| `install_not_ready` | S2 | 未产生：无 `fiber_control(on)` |
| `interaction_mismatch` | S3 | 未产生：无 respond |
| `provider_unavailable` | S3 | 未产生：无 start/episode 选择 |
| `dependency_unresolved` | S2 | 未产生：无依赖求解 |
| `provide_conflict` | S2 | 未产生：无活 slot 冲突语义 |
| `budget_exceeded` | S4 | 未产生：无预算准入 |
| `blocked_unknown` | S4 | 未产生：无 unknown wall（S1 的 unknown 只到 `prepare_unknown` 状态） |
| `cleanup_cycle` | S5 | 未产生：无清理 DAG |

## 3. S1 无写入者 / 不适用

| 项 | 处理 |
|---|---|
| 十表中 `runs`/`fibers`/`episodes`/`slots`/`pins` 的领域行为 | S1 无生产者（计划 §4.12）。只做 (a) catalog 存在性、(b) owner 直写 DDL 约束反例（G1-O）、(c) 夹具 seed 行。**不做**任何「advance 会如何维护它们」的行为断言 |
| 读请求零写 | **N/A**：S1 无读函数。S3 有读面后启用，不得写成「已覆盖」 |
| 并发矩阵 | 只证 G1-L 的 G 排他 + G 是首锁；完整双提交序矩阵归 S7 的 G6 |
| 真实 host IO / 网络 | FakeHost 纯进程内、无套接字（`F`），不是 transport 证明；真实套接字入口不在本 stage |
| 崩溃恢复 | 只测两个 journal 窗口（before/after journal）；完整 recovery 归后续 stage |
| `advance` 的 `revision` | S1 恒为 0（不写 runs），是 C2 的已知空洞；S3 开工前必须回写 |
| DDL 语义 vs advance 语义 | G1-O 证明 DDL 能拒绝，不证明 advance 会正确拒绝；两者在矩阵中分列 |

## 4. 结论

- S1 的具名断言 G1-A…G1-R 全部有生产者、全部实跑通过；四个 gate 退出码均为 0。
- 13 个错误码、五张领域表的领域行为、读面零写与完整并发/恢复矩阵**未在 S1 验证**，已在 §2.2、§3 显式标注，不计入覆盖。
- 已知残余风险：`revision=0` 的 C2 空洞（S3 前回写）；FakeHost 非真实 transport；G1-A 的源码文本检查已按 §1.1 细化。
