# v24 覆盖矩阵（S1 + S2 + S3）

> 收尾稿：2026-10-24。覆盖 S1、S2、S3。断言口径以各 stage 计划和[设计稿](../designs/v24-pg-agent-2026-10-22.md)为准。以下记录本轮六个 gate 的实际结果；S3 的 G2b 与 G3b-2 完整 claimed/unknown settlement release 仍按边界保留。

## 0. 运行环境与最终证据

本轮于 2026-10-24 按下表顺序串行实跑全部六个命令，均退出 0。`V` 终端输出 `[passed] v24 S3 W1-W7`，具名包含 `G3b-1..5` 与 `claimed/unknown settlement release reserved S4`。

环境：PostgreSQL 18.4（pgembed），Python 3.12，psycopg2 2.9.12，工作树 `.claude/worktrees/v99`，分支 `v24`。

简称：`T`=`v24/s1/test_g1.py`，`D`=`v24/s1/test_ddl.py`，`S`=`v24/s1/setup_db.py`，`L`=`v24/load.py`，`R`=`v24/s2/test_g3a.py`; `V`=`v24/s3/test_g2.py`。`T.state` / `R.state` 对十表做全列全行快照（含 bytea、receipt、claim 字段）。S2 的零写分两级：**W0** = 十表全快照相等；**W1** = 除本次 command 的 `effects`/`requests` receipt 外零 diff。`R` 用 `domain_state`（去掉 effects/requests）断言 W1 的领域零写。

| # | 命令 | 退出码 |
|---:|---|---:|
| 1 | `uv run python v24/load.py` | 0 |
| 2 | `uv run python v24/s1/setup_db.py --self-check` | 0 |
| 3 | `uv run python v24/s1/test_ddl.py` | 0 |
| 4 | `uv run python v24/s1/test_g1.py` | 0 |
| 5 | `uv run python v24/s2/test_g3a.py` | 0（本轮实跑；S2 W1–W6） |
| 6 | `uv run python v24/s3/test_g2.py` | 0（本轮实跑；G2a-0…8/10、G3b-1…5 passed） |

### 0.1 历史失败（追加修正结果，不覆盖）

| 阶段 | 失败 | 根因 | 修正后 |
|---|---|---|---|
| S1 W5 首次 | `T` 退出 1：`AmbiguousColumn: column reference "manifest" is ambiguous` | `interpret_install` 内局部变量与列名重名 | 重命名局部变量为 `parsed_manifest`，同一 gate 转 0 |
| S1 W6 首次 | `T` 退出 1：ACL 探针期望 `42501`，实得 `428C9` | UPDATE 探针取表首列；`events.event_id` 是 `GENERATED ALWAYS AS IDENTITY`，解析期错误先于执行期权限检查 | 探针只选 `attidentity='' AND attgenerated=''` 的列；转 0 |
| S1 W6 第二次 | `T` 退出 1：`permission denied for table effects` | 影子 TEMP 对象在 `SET ROLE` 前创建，属主是 LOGIN 角色；切到组角色后不可读 | 改为 `SET ROLE` → 建影子 → 断言 → DROP → `RESET ROLE`；转 0 |
| S1 W6 第三次 | `T` 挂起（>600s，转后台后终止） | G1-B 回滚注入的触发器在 owner 未提交事务中持有 `v24.scopes` 的 ACCESS EXCLUSIVE，阻塞 admin 的 INSERT | 触发器提交后再注入、探针结束显式 DROP；转 0 |
| S2 W1/W2 | `R` 退出 1：`42702 column reference "k" is ambiguous` | applier 遗留的未使用变量 `k text` 与 `jsonb_object_keys(...) k` 别名冲突 | 删除未使用变量；转 0 |
| S2 W4 | `R` 退出 1：`428C9 cannot insert a non-DEFAULT value into column "consumer_id"` | `INSERT INTO v24.pins SELECT *` 覆盖生成列 | 显式列清单并排除 `consumer_id`；转 0 |
| S2 W4 | `R` 退出 1：`23502 null value in column "opened_at"` | `jsonb_populate_record` 对缺省列写 NULL，绕过 DEFAULT | delta 的 episode 行携带 `opened_at`；转 0 |
| S2 W5 | `R` 退出 1：settle 路径 `invalid_outcome`，随后暴露 `42702 column reference "kind"` | settle 的 `UPDATE v24.effects ... WHERE kind=... AND status=...` 列名与 PL/pgSQL 变量歧义 | `UPDATE ... AS ef` 全部别名限定；转 0 |
| S2 W6 | `R` 退出 1：`request_conflict` | 测试把 scope 与 install 用了同一个 `request_key`；`requests(principal_id,request_key)` 全局唯一 | scope key 改为独立值；转 0 |
| S2 W5 | `R` 退出 1：succeeded reconcile 计数断言失败 | 一次 on + 一次 off 各结算一条，测试却假设只有一条 | 改为断言 ready=0 且存在 `stage=deactivate/result=closed` 的那条；转 0 |

以上均为**夹具/探针/测试断言缺陷**或局部 SQL 质量问题，不是设计语义变更；全部在对应里程碑提交前修正，未以降低断言的方式绕过。

## 1. S1 具名断言 G1-A … G1-R

| ID | 生产者（本次实跑） | 断言要点 | 结果 |
|---|---|---|---|
| G1-A | `T.catalog`（L112–171） | S1 时 `prosecdef=true` 恰为 `{advance}`；S3 W1 后当前封闭 DEFINER allowlist 为 `{advance, resolve, run_owner, run_projection, poll, wait_check}`，其中 advance 是唯一可写 DEFINER，其余只读、STABLE、固定 `search_path=pg_catalog, v24`；四个纯 helper 均 INVOKER+IMMUTABLE；无 `claim_*`/`lease_*`/`acquire_*`；含 `pg_advisory_xact_lock` 的函数只有 advance；全部函数属主为 `v24_owner`；`aclexplode` 断言 PUBLIC 无 EXECUTE；advance 源码中 G 的 `PERFORM` 先于 reads 的 `FROM` 与任何 `FOR UPDATE`，八段锁语句的次序为 scope→run→effect→install→fiber→episode→slot→pin；函数体无 `http`/`dblink`/`pg_sleep`/`current_setting`/`current_user`；23 个错误码全被 `error_v1` 接受，未知码得 `22023` | 通过（本轮 G1 gate） |
| G1-B | `T.scope_control_w4`（L458–508） | 一次 command 提交后：scope 行 +1、effect=`succeeded`、request 行存在且 `effect_id` 相等、恰 1 条事件；另注入 `BEFORE INSERT ON v24.events` 触发器（`23514`）。冻结写序是 domain → effect → request → events，因此失败发生在 scope/effect/request **已写之后**；失败后十表全快照逐字节相等，证明整事务回滚而非写前拒绝 | 通过 |
| G1-C | `T.install_settlement_w5`（L510–724） | T2 三路故障：delta 预检拒绝（`invalid_outcome`）、事件触发器 `23514`、install CAS 拒绝（`receipt_conflict`）；每路后十表快照相等、effect 仍 `claimed`、无 successor、无 receipt 写 | 通过 |
| G1-D | `T.scope_control_w4`、`T.command_prefix` | 同 request 同 bytes 二次 advance 返回与首次 **byte-equal** 的封套；提交后十表快照相等；事件计数不变 | 通过 |
| G1-E | `T.command_prefix` | 同键不同 payload ⇒ `request_conflict`，`rejects_without_writes` 全快照相等（提交后复检） | 通过 |
| G1-F1 | `T.command_prefix` | fixture 预置同键 request 行后，用与派生值不等的 `effect_id` 提交：无论 bytes 相同或不同，均得 `effect_id_conflict`，不得得 `replay`/`request_conflict`；零写 | 通过 |
| G1-F2 | `T.scope_control_w4`、`T.install_settlement_w5` | 同一 `(principal,request_key,kind)` 的 wrapper 两次派生同一 `effect_id`；二次调用返回首次 response；`w5-pure` 的 replay 与首次 byte-equal 且全快照不变 | 通过 |
| G1-G | `T.claims_and_receipts` | 旧 token（attempt/fence 各减 1、或 owner 伪造）对 success/failure/unknown 三类均 `stale_claim` 零写；effect 保持 `claimed` | 通过 |
| G1-H1 | `T.identities_and_matrix` | 真实 LOGIN：`session_user`=LOGIN 角色；`SET ROLE` 后 `current_user` 变而 principal 不变；claim 的 `owner` 等于 `session_user` | 通过 |
| G1-H2 | `T.claims_and_receipts`、`T.install_settlement_w5` | settlement 的 owner 比对对象是 `effects.claim_owner`：`owner="spoof"` 与历史 token 均 `stale_claim` 零写 | 通过 |
| G1-I | `T.install_settlement_w5` | claim 提交前 FakeHost 拒绝执行且 journal=0；提交后 journal=1 而 effect 仍 `claimed`；过期重 claim 得 `attempt=fence=2`；旧 token 结算 `stale_claim`；两个 crash 窗口 journal 分别为 0/1 | 通过 |
| G1-J | `T.install_settlement_w5` | `installed`/`prepare_failed`/`prepare_unknown` 三态由 success/failure/unknown 到达；`resource_quiesced_at` 仅 unknown 为 NULL；`claim_owner`/`lease_until` 结算后清空 | 通过 |
| G1-J2 | `T.scope_control_w4` | `create_root`：`route_path=[id]`、`root_id=id`、`parent_id IS NULL`；`create_child`：`route_path = parent.route_path \|\| new_id`；`close` 只写 `close_requested_at`；关闭后 `create_child`/`install` 得 W1 `scope_closed` | 通过 |
| G1-K | `T.install_settlement_w5`、`D.negatives` | 同 receipt 二次提交不产生第二条同 `(effect,entity,kind)` 事件；`install` entity 的 `seq` 为 `[1,2]`；append-only 触发器对 UPDATE/DELETE/TRUNCATE 各得 `23514` | 通过 |
| G1-L1 | `T.locks` | 阻塞者持 `pg_advisory_xact_lock(24,1)` 后 `pg_locks` 出现 `(advisory,24,1,objsubid=2)`；第二连接在该锁上 `NOT granted` 且 `wait_event_type='Lock'`；**未用 sleep 猜顺序** | 通过 |
| G1-L2 | `T.locks` | 该 backend 阻塞期间在 `v24.*` 上无任何 granted 行锁 | 通过 |
| G1-M | `T.closure_retry` | 悬空 `install_id` ⇒ `retry_with_closure` 零写；补行后**新事务**在 G 下重新发现闭包并成功 claim | 通过 |
| G1-N | `S._assert_closed_catalog` | schema 恰为 `{v24, v24_fake}` 且属主 `v24_owner`；base+partitioned 恰十表；view 为空；扩展为空；第三 schema 被拒 | 通过 |
| G1-O | `D`（7 组） | owner 直写 DDL 约束反例：partial unique、复合 FK、`c_pins_xor`、`c_scopes_path_end`、保留列、append-only、T2–T4 冻结字段、COMMIT 闭合、E1→E2/slot/pin 顺序、缺 request 的 effect | 通过 |
| G1-P | `T.permissions` | 三角色各 30 条 DML 全 `42501`；EXECUTE 集合逐角色精确（admin 无 install）；`SET ROLE`/`SET SESSION AUTHORIZATION`/`CREATE TABLE v24.*`/私有 helper 均 `42501`；TEMP 影子不能改写入口；owner 真实 LOGIN 可写十表 | 通过 |
| G1-Q | `T.shapes`、`T.claims_and_receipts` | class 闭集 5 值；6 非闭集与 8 形状族各零写 `invalid_args`；`lease_ms` 边界可达；五 class 各达唯一分支 | 通过 |
| G1-R | `T.expect_envelope` 及各分支 | 封套精确六键；仅 claim+committed 时 `claim={attempt,fence,session_user}`；其余 `claim=null` | 通过 |

### 1.1 G1-A 的断言细化（披露，不是放行）

S1 的 W5 需要一个与 advance 共享 delta 应用的 INVOKER helper `validate_and_apply_install_delta`；S2 的 `settle[]` 又让主 applier `validate_and_apply_delta` 含 `UPDATE v24.effects`。G1-A 的静态检查因此细化为：

- 当前 `prosecdef=true` 恰为 `{advance, resolve, run_owner, run_projection, poll, wait_check}`；advance 是唯一可写 DEFINER，其余为 STABLE、固定 search_path、零 DML/无 advisory lock 的封闭读面 allowlist；
- 含 `UPDATE v24.effects` 的函数允许 `{advance, validate_and_apply_install_delta, validate_and_apply_delta}`；三者中只有 advance 是 DEFINER，另两个必须 INVOKER、无任何 EXECUTE 授权、且不可被协议角色调用；
- 含 `pg_advisory_xact_lock` 的仍只允许 advance。

即：放宽的是「源码里只能出现一处 UPDATE 文本」，未放宽「只有一个可写 DEFINER、只有一个可调用写入口」。当前只读 DEFINER allowlist 由 S3 W1 明确加入；`run_owner`/`run_projection` 为内部 helper，不授予协议角色 EXECUTE。

## 2. S2 具名断言 G3a-A … G3a-L

| ID | 生产者（本次实跑） | 断言要点 | 结果 |
|---|---|---|---|
| G3a-A | `R.resolver_contract`、`resolver_shape_and_writes`、`resolver_routing`、`resolver_live_predicate`、`resolver_limit`、`acl` | 六列、输入序；未知 key `live=false` 且零写；leaf-first realm、同 key 不同 realm 并存、无跨 realm fallback；withdrawn/released/retiring/disposed/closing 全 `live=false`；257 key → `22023`；三角色 EXECUTE、PUBLIC 无。S2 时为 STABLE/INVOKER；S3 W1 修复为 DEFINER | S2 历史 gate 通过；S3 G2a-0 本轮 service/operator/admin LOGIN 回归通过 |
| G3a-B | `R.fiber_control_activation` | 空 inject：`on` → 一个 active episode（epoch=1）、`current_episode_id` 指向它、无 activation pin、无贡献 slot、reconcile succeeded；事件恰 `fiber_activated`+`episode_opened` | 通过 |
| G3a-C | `R.fiber_control_activation` | 有 requires/provides：activation pin 的 consumer episode/epoch/key/slot/provider 全对；provide slot 的 realm/key/contribution_seq/descriptor digest 正确；`next_contribution_seq` 递增 | 通过 |
| G3a-D | `R.fiber_control_activation` | 缺依赖 / policy=false ⇒ W1 `dependency_unresolved`；无 episode/slot/pin；fiber 写 `want_on=true/control_seq+1/failure_seq/failure`，`current_episode_id=NULL`；补 provider 后 retry 成功并 pin 到正确 slot/episode | 通过 |
| G3a-E | `R.fiber_control_activation` | 同 realm/key 已有 live slot ⇒ W1 `provide_conflict`；目标 fiber 无 episode/slot；fiber failure 记录 | 通过 |
| G3a-F | `R.deactivation_barrier` | A pin B 的 slot → B off：slot `withdrawn_at` 非空、`released_at` NULL、episode retiring、reconcile ready、`deferred`；A off 释放 pin；B 再 off 完成 release/close/current 清空 | 通过 |
| G3a-G | `R.fiber_control_activation`、`R.deactivation_barrier` | E1→E2：off 完成后再次 on 得 `epoch=E1.epoch+1` 的 E2；E1 行与旧 pin 行保留；无 partial unique 冲突；旧 child install 的 owner 列不变（G3a-J） | 通过 |
| G3a-H | `R.fiber_control_activation` | 错 `expected_control_seq` ⇒ W1 `stale_generation`，除本次 receipt 外零 diff；已完成 on 再 on（新 key）⇒ committed、除 receipt 外零 diff、无新 reconcile；同 key replay byte-equal 且不新增行 | 通过 |
| G3a-I | `R.fiber_control_activation` | 有 failure ⇒ retry 清 `failure_seq/failure`、`control_seq+1`、新 reconcile；无 failure ⇒ no-op；`installs.state` 始终不变 | 通过 |
| G3a-J | `R.install_fibers` | 每个新 install 恰一条 deterministic inactive fiber（`want_on=false`、`current=NULL`、owner 继承）；replay/identity reuse 不增 fiber；child 写固定 `(owner_fiber_id,owner_episode_id)`；E1→E2 后旧行不变；disposed/`owner_closing`/`install_not_ready`/不存在 owner 四类拒绝的原子性 | 通过 |
| G3a-K | `R.dispose_leaf` | release 后继与 reservation 确定性；success → `disposed+disposed_at`+`install_disposed`；同 key replay；新 key `already_terminal`；active fiber 阻塞→off→二次 dispose；`prepare_unknown` 停在 dispose_pending；release failure 不写 disposed；`dispose_pending` 拒收 host_prepare（`receipt_conflict`） | 通过 |
| G3a-L | `R.acl`、`T.catalog`、`T.permissions` | S2 时 `resolve` 为 STABLE/INVOKER 且只由 migration owner 实测；这是 S2 缺陷，S3 W1 改成 DEFINER 并以真实 service/operator LOGIN 验证。`fiber_control`/`dispose` 仍 INVOKER；PUBLIC 无 EXECUTE；三角色 EXECUTE 集合由 S2 gate 回归 | S2 历史 gate 通过；S3 G2a-0 本轮 ACL/真实角色回归通过 |

### 2.1 G3 父门状态

| 父门 | 子门 | 状态 |
|---|---|---|
| G3 | G3a | **完成**：上表 A–L 全绿 |
| G3 | G3b（run-pin 半部） | **完成**：G3b-1…5 本轮 `V` 全通过；G3b-4 为两条已提交顺序场景，G3b-5 由两连接锁屏障/`pg_blocking_pids()`/`pg_locks` 证明序列化 |
| G3 | 父门 | **完成（G3a+G3b）** |

§9 G3 的两条 run 相关负例（provider close 先/claim 后、claim 先/close 后；withdraw 后旧 pin 排空但新 run 失败）**没有**在 S2 运行；S2 只证了无 run activation-pin 屏障（G3a-F）与 withdraw 后新 resolve 不可见（G3a-A）。

## 2.2 S3 具名断言 G2a / G3b

`V` 包含 G2a-0（读面 ACL/resolve）、G2a-1…8、G2a-10；G2a-9（四写共用 advance、每个 command effect 同事务 settled + request response、poll/wait 零写）由各 verb receipt/replay、事件及十表快照断言覆盖。以下新增断言均由本轮 `V` 实跑通过。`run_owner`/`run_projection` 是内部 DEFINER helper，不授予协议角色 EXECUTE；仅 poll/wait_check 等公共读入口获准调用。`runs` 自 S3 start 起有写入者；revision 从 1 起并在可见状态变化时递增，不再恒为 0。

| ID | 断言 | 当前证据/状态 |
|---|---|---|
| G2a-0 | 真实 service/operator/admin LOGIN 读面；resolve live/miss 零写；内部 helper 拒绝 42501；PUBLIC 无 EXECUTE | `V`；本轮通过 |
| G2a-1 | owner start/run fields/pins/one model_call/events/replay/uniqueness | `V.owner_start`；通过 |
| G2a-2 | ownerless start 无 episode/pin；nonempty requires invalid_args | `V.ownerless_start`；通过 |
| G2a-3 | start failures（scope/provider/dependency/budget/auth）零领域写 | `V.start_failures`；通过 |
| G2a-4 | poll projection/auth/revision/event cap/zero writes/no row or G lock | `V.poll_contract`；通过 |
| G2a-5 | wait registration/event/terminal/interaction/epoch wake + cursor/zero writes | `V.wait_check_contract`；通过 |
| G2a-6 | cancel CAS/replay/ready cancelled/claimed cancel_requested/pin handling | `V.cancel_contract`；通过 |
| G2a-7 | steer immediate vs pending branch, epoch/generation/revision/pins | `V.steer_contract`；通过 |
| G2a-8 | respond interaction consumption/mismatch/terminal/replay | `V.respond_contract`；通过 |
| G2a-9 | four write verbs share advance receipt/replay; poll/wait ten-table snapshots unchanged | `V` per-verb assertions；通过 |
| G2a-10 | budget bounds/defaults, malformed inputs, requires limits | `V.start_boundaries`；通过 |
| G3b-1 | run pin 挡 provider release；无引用 run cancel 后释放并允许 off/close | `V`；通过 |
| G3b-2 | claimed tool_call 引用 pin 时 cancel 保持 claimed+cancel_requested、pin 留存；完整静默释放归 S4 | cancel/pin 留存断言通过；完整 claimed/unknown settlement release **未验证 / S4** |
| G3b-3 | withdraw 后新 start 得 `dependency_unresolved`，已存在 run pin/run 仍有效 | `V`；通过 |
| G3b-4 | start→off/deferred→dispose blocked→cancel→off→dispose；dispose→tombstone/episode closed→start `provider_unavailable` | `V`；两条已提交顺序场景通过，不作为并发/锁屏障证明 |
| G3b-5 | start/off 两种顺序；两连接锁屏障证明 advisory G 序列化 | `V`；两连接锁屏障、`pg_blocking_pids()` 与 `pg_locks` 断言通过 |

### 2.3 G2 父门状态

| 父门 | 子门 | 状态 |
|---|---|---|
| G2 | G2a | 完成：本轮 `V` 全绿 |
| G2 | G2b | 未验证 / S4：完整 T2/unknown wall |
| G2 | 父门 | **部分（G2a 绿；G2b 保留 S4）** |

## 3. 错误码覆盖（23 码）

`error_v1` 接受全部 23 码（签名冻结，G1-A 已逐码断言）。**能产生**与**能接受**是两件事。

### 3.1 有生产者的 21 码

| 码 | 写类 | 生产者证据 |
|---|---|---|
| `invalid_args` | W0 | `T.shapes`/`T.command_prefix`/`T.claims_and_receipts`；`R` 的 manifest 形状、CAS 参数、缺 owner 等 |
| `unauthorized` | W0 | `T.identities_and_matrix` |
| `request_conflict` | W0 | `T.command_prefix` |
| `effect_id_conflict` | W0 | `T.command_prefix`、`T.claims_and_receipts` |
| `receipt_conflict` | W0 | `T.claims_and_receipts`、`T.install_settlement_w5`；`R.dispose_leaf`（dispose_pending 期间的 host_prepare） |
| `stale_claim` | W0 | `T.claims_and_receipts`、`T.install_settlement_w5` |
| `retry_with_closure` | W0 | `T.closure_retry`、`R.closure_fail_closed_and_seam` |
| `scope_closed` | W1 | `T.scope_control_w4`、`T.install_settlement_w5`、`R.fiber_control_activation` |
| `install_identity_conflict` | W1 | `T.install_settlement_w5` |
| `invalid_outcome` | W0（实测） | `T.install_settlement_w5`、`R` 的 delta 预检；S3 未新增该 W1 receipt 证据；model/tool outcome 的 tool_calls 超限路径归 S4（台账 I7） |
| `stale_generation` | W1 | `R.fiber_control_activation`（fiber CAS） |
| `already_terminal` | W1 | `R.install_fibers`（disposed fiber）、`R.dispose_leaf`（disposed install） |
| `install_not_ready` | W1 | `R.install_fibers`（child owner 无 active episode）、`R.fiber_control_activation`（install 非 installed） |
| `owner_closing` | W1 | `R.install_fibers`（owner `want_on=false`） |
| `dependency_unresolved` | W1 | `R.fiber_control_activation`（缺 slot / policy=false） |
| `provide_conflict` | W1 | `R.fiber_control_activation` |
| `not_found_or_denied` | W0 | `V.poll_contract` / `V.wait_check_contract`；本轮通过 |
| `registration_stale` | W0 | `V.wait_check_contract`；本轮通过 |
| `interaction_mismatch` | W0 | `V.respond_contract`；本轮通过 |
| `provider_unavailable` | W1 | `V.start_failures`、G3b-4；本轮通过 |
| `budget_exceeded` | W1 | `V.start_failures` / `V.start_boundaries`；本轮通过 |

### 3.2 仍**不能产生**的 2 码（不得计为已覆盖）

| 码 | 预定阶段 | 状态 |
|---|---|---|
| `blocked_unknown` | S4 | 未产生：unknown wall 归 S4 |
| `cleanup_cycle` | S5 | 未产生：清理 DAG 归 S5 |

## 4. 无写入者 / 不适用 / 未验证

| 项 | 处理 |
|---|---|
| `runs` 的领域行为 | S3 `start` 是首个 writer；revision 从 1 开始，后续可见变化递增；G2a assertion 在 `V` 本轮通过 |
| run pin 半部 | G3b-1…5 在 `V` 本轮通过；claimed/unknown 完整释放留待 S4 |
| `inspect_resource` 收敛 | **未验证 / S5**：S2 只把 `prepare_unknown` 停在 `dispose_pending`，不实现 inspect |
| owner 级联 / scope close / 完整 dispose 闭包 | **未验证 / S5**：S2 只做 leaf dispose |
| `resolve` 只读 | S2 gate 曾以 owner 测试；S3 W1 将它改为 DEFINER，并在 `V` 通过真实 service/operator/admin LOGIN 验证；poll/wait 同样由 `V` 验证 |
| 并发矩阵 | 已证 G1-L 的 G 排他/首锁、G3a-F pin 屏障与 G3b-5 start/off 两连接锁屏障；G3b-4 为顺序场景；完整并发矩阵归 S7/G6 |
| 真实 host IO / 网络 | FakeHost 纯进程内、无套接字；不是 transport 证明 |
| 崩溃恢复 | 只测两个 journal 窗口；完整 recovery 归 S6 |
| `advance.revision` | S3 `start` 写 `revision=1`，可见状态变化由 advance 更新；已不再是常量 0 |
| DDL 语义 vs advance 语义 | G1-O 证明 DDL 能拒绝；advance 语义由 G1/G3a/G2a/G3b 的具名断言分列 |

## 5. 结论

- 本轮六个 gate 全部实际退出 0（见 §0）；G2a 与 G3b-1…5 的结果来自 `V` 本轮通过输出。
- G2 父门：**部分（G2a 绿；G2b 保留 S4）**。G3 父门：**完成（G3a+G3b）**。
- 尚无生产者的只有 `blocked_unknown`（S4）与 `cleanup_cycle`（S5）；完整 claimed/unknown run pin 释放留待 S4。
