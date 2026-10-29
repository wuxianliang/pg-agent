# v24 覆盖矩阵（S1–S8 已实现并全绿；G5/G7 已验证；G6 完成（S7 W1–W2，30 ID）；11/11；M-H/G8 扩展验证通过 23/23；M-R/G9 扩展验证通过 11/11；M-P/G10 扩展验证通过 8/8 + Node + multilingual smoke）

> 收尾稿：2026-10-24。覆盖 S1–S8。断言口径以各 stage 计划和[设计稿](../designs/v24-pg-agent-2026-10-22.md)为准。以下记录 S6/S8 收尾轮十个 gate 的历史实际结果（10/10；S7 closeout 的 11/11 追加见 §0.4）；S4 完成后 G2b 全绿，`blocked_unknown` 成为真实生产者，G2 父门完成；**S5 已完成，G4-A…G4-Q 全绿，G4 父门完成（17/17）**。S5 只证串行 request-key 阶段（每个新 key 一个 bounded phase、≤16 行/successor、无 worker/自动推进），**不证**并发面（S7，已由 S7/G6 补证）；**S6 已完成，G5 K1–K10 10/10，全量 G5 末行 `[passed] v24 S6 W1-W4`，G5 父门完成**；S6 只证 FakeHost/journal 下的崩溃恢复合同，**不证**真实 provider/adapter、S7 并发或 S8 spawn（S7 并发已由 G6 补证）。**S8 已完成，G7-A…G7-H + N1–N7 全绿，G7 父门完成**；S8 只证 FakeHost/进程内 fixture 下的 spawn/child-run 合同，**不证**真实 provider/adapter、G6/S7 三面并发（已由 S7/G6 补证）。其余边界见 §4。**当前范围：S1–S8 已实现并全绿；G5/G6/G7 已验证；G6 完成（S7 W1–W2，30 ID）；S7 closeout 11/11（10 既有 + G6），见 §0.4 与 §2.7。M-H 追加 host 只读面与 G8 扩展检查（23/23，见 §0.5）；M-R 追加 host worker/durable journal/DeepSeek adapter 与 G9 脚本化扩展检查（11/11，见 §0.6）；M-P 追加 approved registry/line-JSON/双语言插件与 G10（8/8，见 §0.7），Node 独立全生命周期与同 run multilingual smoke 均实跑 exit 0；历史 11/11 不变，G8/G9/G10 均不计入 closeout 命令数。**

## 0. 运行环境与最终证据

本轮于 2026-10-24 按下表顺序串行实跑全部十个命令，均退出 0（10/10；此为历史 S6/S8 收尾口径，S7 closeout 追加见 §0.4）。`V` 终端输出 `[passed] v24 S3 W1-W7`，具名包含 `G3b-1..5`；`G` 终端输出 `[passed] v24 S4 W1-W6`，具名包含 `G2b-A…V` 与 `G2b-T-1…T-10`；`F` 终端输出 `[passed] v24 S5 W1-W4`，具名包含 `G4-A`…`G4-Q`（17 条全部出现）；`I` 终端输出 `[passed] v24 S6 W1-W4`，具名包含 `[G5-K1]`…`[G5-K10]` 各恰一次（K3 另有 `[G5-control]`）；`J` 终端输出 `[passed] v24 S8 W1-W3 G7-A…H + N1-N7`，具名 `G7-A`…`G7-H` 与 `G7-N1`…`G7-N7` 各恰一次（N1/N2 另有 `[G7-N1-lock]`/`[G7-N2-lock]` 证据行；G7-G 另有 `[G7-G evidence]` 附加证据行，`[G7-G]` 结果行仍恰一次）。**Gate 计数口径（9+1=10）**：9 个既有 gate（load、setup self-check、ddl、g1、g3a、g2、g2b、g4、g5）+ 无参数全量 G7 = **10 条命令，全部退出 0（10/10）**。历史 S6 W1–W3 的 `test_g5.py --only` 曾是增量检查点（旧“+1”），与 S8 W1/W2 的 `--only` 检查点一样，不计入上述十条命令，也不替代父门。

环境：PostgreSQL 18.4（pgembed），Python 3.12，psycopg2 2.9.12，工作树 `.claude/worktrees/v99`，分支 `v24`。

简称：`T`=`v24/s1/test_g1.py`，`D`=`v24/s1/test_ddl.py`，`S`=`v24/s1/setup_db.py`，`L`=`v24/load.py`，`R`=`v24/s2/test_g3a.py`，`V`=`v24/s3/test_g2.py`，`G`=`v24/s4/test_g2b.py`，`F`=`v24/s5/test_g4.py`，`I`=`v24/s6/test_g5.py`，`J`=`v24/s8/test_g7.py`。`T.state` / `R.state` / `G.snapshot` / `F.state` / `I` 的 `g5_snapshot` 对十表做全列全行快照（含 bytea、receipt、claim 字段）；`F.domain_state` 去掉 effects/requests。S2 的零写分两级：**W0** = 十表全快照相等；**W1** = 除本次 command 的 `effects`/`requests` receipt 外零 diff。`R` 用 `domain_state`（去掉 effects/requests）断言 W1 的领域零写；S4 的 `G2b-T-1…T-10` 一律用 W0；S5 的 G4 在每行标明 W0/W1；S6 的 K1–K10 用十表 `g5_snapshot` 与具名列断言；S8 的 G7 用十表快照、具名行/列与 `v24_fake.journal` 计数断言。

| # | 命令 | 退出码 |
|---:|---|---:|
| 1 | `uv run python v24/load.py` | 0 |
| 2 | `uv run python v24/s1/setup_db.py --self-check` | 0 |
| 3 | `uv run python v24/s1/test_ddl.py` | 0 |
| 4 | `uv run python v24/s1/test_g1.py` | 0 |
| 5 | `uv run python v24/s2/test_g3a.py` | 0（本轮实跑；S2 W1–W6） |
| 6 | `uv run python v24/s3/test_g2.py` | 0（本轮实跑；G2a-0…8/10/11、G3b-1…5 passed） |
| 7 | `uv run python v24/s4/test_g2b.py` | 0（本轮实跑；G2b-A…V、G2b-T-1…T-10 passed） |
| 8 | `uv run python v24/s5/test_g4.py` | 0（本轮实跑；G4-A…Q 17/17 passed） |
| 9 | `uv run python v24/s6/test_g5.py` | 0（本轮实跑；K1–K10 各恰一次；末行 `[passed] v24 S6 W1-W4`） |
| 10 | `uv run python v24/s8/test_g7.py` | 0（本轮实跑；G7-A…H、N1–N7 各恰一次；末行 `[passed] v24 S8 W1-W3 G7-A…H + N1-N7: g7_a,g7_b,g7_c,g7_d,g7_e,g7_f,g7_g,g7_h,n1,n2,n3,n4,n5,n6,n7`） |

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
| S6 W4 首次 | `I` 的 K4 退出 1：`NameError: name 'snapshot_diff' is not defined` | K4 使用了未从 `g5_support` 导入的 helper | 加入 `snapshot_diff` import；`--only K4` 与无参数全量 G5 转 0，断言未削弱 |

以上均为**夹具/探针/测试断言缺陷**或局部 SQL 质量问题，不是设计语义变更；全部在对应里程碑提交前修正，未以降低断言的方式绕过。S4 W1–W5 的历史失败与评审阻塞（含 W4 Oracle BLOCK）追加在[台账](v24-deviation-ledger-2026-10-23.md) §4，不在本表重复。S6 W4 的另一项“打印口径清理”（删除重复的初始 `[G5-Kn] journal=...` 行、K3 控制行改 tag 为 `[G5-control]`）只改 print，不改断言，记录在台账 §1.10 的 A-S6-9。

### 0.2 G5 K1–K10 实测证据（S6 W4）

> 无参数 `uv run python v24/s6/test_g5.py` 退出 0；每个 `[G5-Kn]` 恰出现一次；末行恰为 `[passed] v24 S6 W1-W4`。下表 PID、键、时间戳、快照与计数均取该次运行的 `[G5-Kn]` 输出（完整 64 位十六进制值）；journal 仅列 basename。K1 的 parent backend 为 `54875`，K2–K10 为 `54873`。

| 窗口 | 边界 | child / worker（OS pid / backend pid） | journal | 决定性断言与证据 |
|---|---|---|---|---|
| **K1** | command 请求已发出、advance COMMIT 前（§8 L410） | child `54876/54879`；worker `54883/54887` | `K1.jsonl` | `requests=0->1 effects=0->1`；快照 `74fe0f99f1679f657f60f7dc2426010c0447fbe50811015d4792ef01bcb74e39->c31b8048363991c38c440dfea22736807876477ae64e4af5dcc1497af22b372a` |
| **K2** | claim COMMIT 后、IO 前（§8 L411） | child `54893/54899`；worker `54905/54913` | `K2.jsonl` | `applied=['reset_ready','settle_unknown'] has_more=False model=unknown run=blocked_unknown journal_rows=1 journal_attempt/fence=2/2 effects=6->7`；快照 `b71eda7105f9b49c756d470362bffd56c09ccd4397e4e40ebac7f21866d57f0b->7a62c31f78044a3ec9aac13b8f4b460748bd10bc9839f581c1c199122c3c7e60` |
| **K3** | IO 完成、advance 前（§8 L412） | child `54926/54927`；worker `54929/54933` | `K3.jsonl` | `applied=reset_ready+settle_unknown(model/cancel-late) reservation=1 reuse=no-second-io late=receipt_conflict-w0 restore=True model_variant=blocked_unknown+pin cancel_late=seal-preserved+late-only manual=16/0 has_more=False effects=40->43`；快照 `8224cc50310b8dc2e134f9abb1bbef5cb97e28db09dc2e9734416a8f3d6290e2->98012e97e3e81c4f59cc28f2721e76bc5f653580e2803ba53bc0898747131d75`；`[G5-control]` `run_fields=20 byte-equal pins_released=True/True run_events=2/2 effect_columns=equal(4/4) wall=0/0` |
| **K4** | advance 中途错误（§8 L413；**非 SIGKILL**） | child `54950/54960`；worker `54962/54965` | `K4.jsonl` | request `g5-k4-603088ebb2315489`、effect `6a258070-f3c9-500a-415f-2920d4a7795e`；`sqlstate=P0001 tx=rollback->idle`；trigger `k4_inject` created `2026-10-24 19:47:55.625595+08` / dropped `2026-10-24 19:47:55.702859+08`；`requests=0->1 effects=0->1 response=committed`；snapshot before/after rollback 均 `5d3ef214ff41ea01bd23dbc5fd8e9f335a41222454d9db44399bfa7227d95c16`、after resubmit `04e3ccbf37a25cdd072b4d99c1b93a30a3bbf28f80d6da3b347621206cd95e00`；`k4_objects_after=0/0 sql_digest=827e1c61515b9e6d5f4f7104d914bd4d53be483d171dc4c548bd8620d15900fd sql_unchanged=true` |
| **K5** | advance 已 COMMIT、应答丢失（§8 L414） | child `54972/54973`；replay-1 `54974/54979`；replay-2 `54983/54987` | `K5.jsonl` | request `g5-k5-ce334bfcbb53e3dd`、effect `1e837f17-c091-665a-5f54-9610da3119d1`、seed effect `8de300d9-c6e9-462d-97b9-5df300bcb478`；canonical b64 `eyJ2IjogMSwgImxpbWl0IjogMTYsICJzY29wZV9pZCI6ICJkNTE4NDFiYy1iNjkwLTQzMTMtYjMwNy1hYjA0NjM0MzI2MjUifQ==`、decoded `{"v": 1, "limit": 16, "scope_id": "d51841bc-b690-4313-b307-ab0463432625"}`、sha `24ee41a8a7689533dc541087667ce76631460048c260eaed04e8ffc519aee18c`；first/replay-1/replay-2 response sha 均 `17d16f00fd32997b76938d630ba78fc55251f91e0a2f46be245262ca39de35b6`、各 `523` 字节、`byte_equal=true`；`requests=1 effects=1 sweep_events=1 sweep_action=reset_ready successors=0 budget=inapplicable(no-run)`；snapshot before `834182d1420e59eade3a45c652c8d4ab4ea91c7a2e9fa93aaf49461f61b1ed3a`，post-kill/replay-1/replay-2 均 `d517cba67b3ebb5658d964d5fb33c446581e7bb3006f5cf41eb084ce90818b33`、`second_replay_zero_write=true` |
| **K6** | provider withdrawn、fiber 未清理（§8 L415） | child `54995/55001`；worker `55006/55012` | `K6.jsonl` | `resolve_live=False pin_live_at_crash=True pin_released_after=True run_terminal=preserved episode=retiring->closed slot=True->released journal=recover+fiber_control install_disposed=None/None scope_closed_at=None effects=66->72`；快照 `7de709bf079d922938530b935487ef34edaa7f14fdb84d69bbe8afffe2394799->0fa19169b41e48745d726e14c153a11acc7a5684ddb9779ac0cb53bbca2fa472` |
| **K7** | 子 fiber 已清理、父未清理（§8 L416） | child `55021/55025`；worker `55034/55041` | `K7.jsonl` | `resolve_live=False child_disposed_at=2026-10-24T19:47:56.340662+08:00 unchanged=True parent_episode=retiring->closed parent_slot_released=True>child_disposed owner_pair=True/True scope_closed_at=None effects=83->89`；快照 `9f43937bbd52850ce2e01dda44977850df399da05eb65966c86fd47211b5367e->82da991aee0d12464f653536463cf093007fb2d5e85b2d309c6b6406823c8ce5` |
| **K8** | host_prepare IO/receipt 窗口（§8 L417） | child `55052/55053`；worker `55062/55066` | `K8.jsonl` | `refused=install_not_ready-w0(activation-domain) diff={'effects': {'added': 2, 'changed': 0, 'removed': 0}, 'fibers': {'added': 0, 'changed': 1, 'removed': 0}, 'requests': {'added': 1, 'changed': 0, 'removed': 0}} preparing->installed reservation=1 journal_attempt/fence=1/1 activation=028a1e33-15d6-4d4c-9232-226f60ae2d75`；快照 `714b6c83f6027aa22a1e7805ed213c949e0a93521de60404fb8675a2ed13f991->777c17b019ae475409695c4abb91a7acd29c5c9baeddd4a396b4c2fdd4a195eb` |
| **K9** | scope close/prepare_unknown（§8 L418） | child `55074/55078`；worker `55086/55092` | `K9.jsonl` | `child_state=closing/prepare_unknown/unknown-unquiesced closed_at_before_inspect=None scope_closable_ok=False inspect_observed=absent install=disposed host_quiesced=True closed_at_after_steps=True scope_closed=1 close_steps=6 effects=98->109`；快照 `32f6a018b61b6997dc99338b6d493ee5e23644140657808d72810ec5bf634496->2e091616dd4a3e117c90243b86b1a7cdbfb4d3e4a14fbb4941a2f758f25746ec` |
| **K10** | host CAS release 后、DB receipt 前（§8 L419） | child `55108/55109`；worker `55111/55117` | `K10.jsonl`、`K10b.jsonl` | `release_a=success->disposed release_rows_a=1 release_b=lost->inspect target_reservation=v24:host_release:3882a543-5e00-30f5-351b-1dfbd694ec55 disposed=disposed release_rows_b=1 inspect_rows_b=1`；snapshot a `e6005dfd237b11a1565a2fb78ad47d93291405fa4d017232c19352708bcaf775->9a574b4b86c36e8c1ed6640ecf54203f9d28ce45570e702913dad4e355df6051`、b `8f91c601fc2988e9d389312595828f56914786f03345a227464f5accd3fd9c20->d66aeb853853dab916c4d8baf96cbe8f1bc115921bf981fca5bb6e3488702e9a` |

补充证据：`[G5-W2]` 合同套件（`scope=267fb124-2b62-44c9-9e98-0c12f758e159`，admin/service backend `54873/54874`）证明同 key replay、`conflict_limit=request_conflict`、`conflict_scope=request_conflict`、`candidates_replay=True`、`has_more=True->False`、`limits=invalid_args-w0`、`service=not_found_or_denied-w0`；`[G5-D1]`…`[G5-D6]` 证明发现面只返回 claimed+过期、`(lease_until,effect_id)` 序、limit 0/0/0/16/16、排除 manual、service 对 admin scope 0 行、读前后十表快照不变（`e9740e208eb971447eb789587b18ceebfe9ae37ce3e1f9cb3468d2d98d67815b`）。

### 0.3 G7 spawn/child-run 实测证据（S8 W1–W3）

> 无参数 `uv run python v24/s8/test_g7.py` 退出 0。以下为该次运行的完整输出（36 行，逐字取自本轮 W3 无参数运行）：`[G7-A]`…`[G7-H]` 结果行与 `[G7-N1]`…`[G7-N7]` 各恰出现一次（`[G7-D finite]`/`[G7-D NULL]` 是同一 D 结果的子证据行）；N1/N2 的锁证据行分别为 `[G7-N1-lock]`/`[G7-N2-lock]` 各一次；`[G7-G evidence]` 是 G7-G 的附加证据行，`[G7-G]` 结果行仍只出现一次，因此结果 tag 不重复。末行即 10/10 中的第 10 条 gate 通过行。

```text
[G7] running g7_a
[G7-A] child run+edge+quota+first model+events in one advance; run/effect/quota fault injection rolls the whole advance back
[G7] running g7_b
[G7-B] same (parent,key,bytes) on a new parent outcome: replayed=true, one child/effect/run_spawned, grant deducted once; exact advance replay is the frozen replay envelope with zero writes
[G7] running g7_c
[G7-C] same key/different bytes on a different request_key: 24th code spawn_key_conflict W0, ten tables byte-equal, model effect still claimed
[G7] running g7_d
[G7-D finite] grant=300 reserve=300 child_remaining=0 tokens_before=904 tokens_after=4700 wall_elapsed=19 wall_after=592981
[G7-D NULL] parent/child remaining_tokens=NULL, reserve=0; steps/tool_calls/wall conserved on post-settlement values
[G7-D] grant-reserve child ledger, post-settlement token/wall conservation, NULL tokens exempt, finite+NULL invalid, steps and wall over-budget W0 unchanged
[G7] running g7_e
[G7-E] fibers/installs/slots/episodes unchanged; child has no fiber, no episode pin and no run pin
[G7] running g7_f
[G7-F] no new table/column/index/view/extension; no socket/HTTP; v24_fake.journal gained 0 rows
[G7] running g7_g
[G7-G] effect=f3f9ce0c-c4c4-1e0e-83d9-b956b97c7e4a run=2a2d0546-5c5d-92a1-850e-b154060409ba cause=spawn child_model pin_id=NULL claimed(public:attempt=1/fence=1,owner=v24_s1_27595_868544b06003_service) lease_expired->unknown child_run=running->blocked_unknown ended_at=set interaction=None pending_steer=seeded->None edge=(parent_run_id=0073c2f0-fd13-456a-bab7-c609cc51b844,spawn_key=child-g,spawn_request_digest=aa6ab6a94ee4daaddc09e8ca0a1d4977829d148bc13571fbb3243c3489bf732e) children=1->1 child_effects=1->1 effects_total=45->46(+1 command_recover receipt) parent_quota={'remaining_steps': 2, 'remaining_tokens': 604, 'remaining_tool_calls': 2, 'remaining_wall_ms': 594980}->{'remaining_steps': 2, 'remaining_tokens': 604, 'remaining_tool_calls': 2, 'remaining_wall_ms': 594980} run_pin=8a3039ec-ee58-4740-8090-1390642bd448 released=True released_by_effect=f3f9ce0c-c4c4-1e0e-83d9-b956b97c7e4a
[G7-G evidence] model_pin_id_before_claim=None claim={"attempt": 1, "fence": 1, "owner": "v24_s1_27595_868544b06003_service"} lease_until=2026-10-24T21:35:08.877164+08:00 lease_expired=True effect_status=unknown effect_outcome_class=unknown observed=unknown reason=lease_expired outcome_claim={"attempt": 1, "fence": 1, "owner": "v24_s1_27595_868544b06003_service"} child_status=blocked_unknown ended_at=2026-10-24T21:35:09.877879+08:00 interaction=None pending_steer=None edge={"parent_run_id": "0073c2f0-fd13-456a-bab7-c609cc51b844", "spawn_key": "child-g", "spawn_request_digest": "\\xaa6ab6a94ee4daaddc09e8ca0a1d4977829d148bc13571fbb3243c3489bf732e"} child_counts={"children": 1, "effects": 1, "spawned": 1, "started": 1} parent_quota_before={"remaining_steps": 2, "remaining_tokens": 604, "remaining_tool_calls": 2, "remaining_wall_ms": 594980} parent_quota_after={"remaining_steps": 2, "remaining_tokens": 604, "remaining_tool_calls": 2, "remaining_wall_ms": 594980} run_pin=8a3039ec-ee58-4740-8090-1390642bd448 run_pin_released_at=2026-10-24T21:35:09.877879+08:00 run_pin_released_by=f3f9ce0c-c4c4-1e0e-83d9-b956b97c7e4a
[G7] running g7_h
[G7-H] invalid args / budget_exceeded / provider_unavailable / dependency_unresolved / already_terminal: ten tables byte-equal, effect claimed
[G7] running n1
[G7-N1-lock] G lock held open by a pid=27635 (pg_stat_activity.state='idle in transaction'); b pid=27636 blocked: pg_blocking_pids(27636)={27635}, pg_locks(pid=27636, locktype='advisory', granted=false)=1
[G7-N1] Barrier(2) same effect/bytes: one child; b pid=27636 blocked on pg_blocking_pids={27635} and replayed the frozen envelope; grant deducted once
[G7] running n2
[G7-N2-lock] G lock held open by a pid=27638 (pg_stat_activity.state='idle in transaction'); b pid=27639 blocked: pg_blocking_pids(27639)={27638}, pg_locks(pid=27639, locktype='advisory', granted=false)=1
[G7-N2] concurrent same key/different bytes: one committed child, loser receipt_conflict (G-serialized, no half state); a later outcome with the losing bytes reaches spawn_key_conflict W0
[G7] running n3
[G7-N3] cancelled parent: already_terminal W0, no child, effect claimed
[G7] running n4
[G7-N4] child steps above parent remaining: budget_exceeded W0, parent run row byte-equal, no child
[G7] running n5
[G7-N5] owner-pin spawn: faults at child run / quota update / child effect roll back the child, pin, quota and events; effect stays claimed
[G7] running n6
[G7-N6] same request_key/bytes twice: byte-equal frozen replay envelope, ten tables unchanged, one child and one grant deduction
[G7] running n7
[G7-N7] owner-pin spawn: fibers/installs/slots/episodes unchanged, child is a run with the owner pair and one run pin, never a fiber/install
[passed] v24 S8 W1-W3 G7-A…H + N1-N7: g7_a,g7_b,g7_c,g7_d,g7_e,g7_f,g7_g,g7_h,n1,n2,n3,n4,n5,n6,n7
```

G7-G 的完整 before/after 表、恢复 action 与 `command_recover` 返回值见 [`v24/s8/README.md`](../../v24/s8/README.md) §3.1；该次运行中 owner-pinned child 首 model 的 `pin_id=NULL`，先经真实公共 `claim_effect` 取得 `attempt/fence=1/1`（service login owner），再过期 lease 并由 `v24.command_recover` 结算为 `unknown`；child run 转 `blocked_unknown`、独立 `pins` 行上的 run pin 被释放，父 run 行逐字节不变。全部十个命令串行退出 0：**10/10**（历史 S6/S8 收尾口径；S7 closeout 的 11/11 追加见 §0.4）。

### 0.4 S7 closeout 追加（11/11）

> 历史 S6/S8 收尾口径为 **10/10**：即上表十条命令，当时尚无 G6。S7 closeout 在同一工作树按同一顺序执行既有十条命令，并追加第 11 条无参数全量 G6，全部退出 0，因此为 **11/11（10 既有 + G6）**。既有 10 条命令、顺序、断言与编号均未改，G6 不替代其中任何一条；旧 10 行表保留为历史，不删除也不改写。

| # | 命令 | 退出码 |
|---:|---|---:|
| 1 | `uv run python v24/load.py` | 0 |
| 2 | `uv run python v24/s1/setup_db.py --self-check` | 0 |
| 3 | `uv run python v24/s1/test_ddl.py` | 0 |
| 4 | `uv run python v24/s1/test_g1.py` | 0 |
| 5 | `uv run python v24/s2/test_g3a.py` | 0 |
| 6 | `uv run python v24/s3/test_g2.py` | 0 |
| 7 | `uv run python v24/s4/test_g2b.py` | 0 |
| 8 | `uv run python v24/s5/test_g4.py` | 0 |
| 9 | `uv run python v24/s6/test_g5.py` | 0 |
| 10 | `uv run python v24/s8/test_g7.py` | 0 |
| 11 | `uv run python v24/s7/test_g6.py` | 0（无参数全量；30/30 ID） |

第 11 条 G6 的末行逐字为：

```text
[passed] v24 S7 W1-W2 G6-A…H + N1-N9 + L1-L5: g6_a1,g6_b1,g6_b2,g6_b3,g6_c1,g6_c2,g6_c3,g6_d1,g6_e1,g6_f1,g6_g1,g6_g2,g6_g3,g6_h1,g6_h2,g6_h3,g6_n1,g6_n2,g6_n3,g6_n4,g6_n5,g6_n6,g6_n7,g6_n8,g6_n9,g6_l1,g6_l2,g6_l3,g6_l4,g6_l5
```

30 ID 构成：16 条矩阵（A1；B1–B3；C1–C3；D1；E1；F1；G1–G3；H1–H3）+ N1–N9（9 条负例）+ L1–L5（5 条锁序）。18 格映射、格 2 的 G3b-5 closeout 重跑证据与其精确证据行见 §2.7；完整证据见 [`v24/s7/README.md`](../../v24/s7/README.md) 与 [`v24/s7/test_g6.py`](../../v24/s7/test_g6.py)。**历史 S6/S8 收尾为 10/10；S7 closeout 追加 G6 后为 11/11。**

### 0.5 M-H extension check（G8）— 2026-10-24

> 裁决 5-B：G8 是 **extension check**，不改历史 11/11、不称 closeout gate。M-H 只实现 G8；G9 由 M-R 实现并见 §0.6，G10 由 M-P 实现并见 §0.7；历史 11/11 或 G8 都不得被解读为已证明 G9/G10。

| extension | 命令 | 状态 | 证据 |
|---|---|---|---|
| G8 | `uv run python v24/s9/test_g8.py` | **通过 23/23，exit 0** | 本文 §0.5；[`v24/s9/README.md`](../../v24/s9/README.md) |
| G9 | `uv run python v24/s10/test_g9.py` | **通过 11/11，exit 0** | 本文 §0.6；[`v24/s10/README.md`](../../v24/s10/README.md) |
| G10 | `uv run python v24/s11/test_g10.py` | **后续 M-P 通过 8/8，exit 0** | 本文 §0.7；[`v24/s11/README.md`](../../v24/s11/README.md) |

M-H 的 23 个 ID 全部实跑：`G8-H1`…`H13`（13）、`G8-C1`/`C2`（2）、`G8-L1`…`L3`（3）、`G8-R1`（1）、`G8-D1a`/`D1b`（2）、`G8-D2`（1）、`G8-W1`（1）。末行：

```text
[passed] v24 G8 host reads / closure / lease / recovery: 23 case(s)
```

关键实测值：

- ACL：17 个 DEFINER；27 条 `GRANT EXECUTE`；逐角色 EXECUTE **admin 26 / service 27 / operator 27**；`host_scope_allowed` 无 GRANT；admin 仍被拒 `install`。
- 闭包：`B=C(0)=3`；`H=0,1,2,4,8,16,32` 的 `C=3,4,5,7,11,19,35`，每个相邻区间的 C 增量等于 H 增量（每加一条历史 host effect 恰好 +1 个实体）。`H_ok=512-3=509` → `C=512` 普通 claim committed；`H_bad=513-3=510` → `C=513` 返回 `retry_with_closure`、无 token、十表逐字节不变、重试仍拒。
- H13：64 个各带 ~1 MiB `model_call.input` 的项，实测整页 **67,107,712 bytes（64.00 MiB）**；64 上限未放宽、request 未脱敏。真实 lease=1 claim/settle 通过。
- H11：持 G 且未提交变更时九个读函数 ~5 ms 完成且只见已提交 snapshot；reader 无 advisory lock、不进 `pg_blocking_pids`；并发 `advance(claim)` 确实被 G 阻塞后提交。
- D-S6-12：`G8-D1a` 用「已关闭 scope + 真实过期/已 claim/非 manual 候选」得到精确 `settle_unknown`/`install_not_preparing`，scope/install/fiber/run 未复活；**该债务关闭**。
- D-S8-7：`G8-D2` 四种 spawn 混用均 `invalid_outcome`、十表零写、原 claim 不变，随后同 key 合法 spawn 提交；**该债务关闭**。
- 公共路径增长（证据，非 gate）：真实 install/prepare + 32 次 `fiber_control(on/off)` 后 effects 4/18/34/66、reconcile 1/8/16/32、episodes 1/4/8/16、pins 0；逐命令闭包 6…38（非单调，因探针指向不同形状的 latest effect）。`unknown→inspect` 分支在 M-H 未生成，实际返回 `[]`，不以 owner 插入冒充公共路径。
- 边界：W1 只证 SQL/session 前置（30s/5s/5s、READ COMMITTED、两连接 IDLE、在飞时不 sweep）；worker 循环属 M-R。无 starvation/fairness 证明（D-S7-2 原样保留）。

M-H 落地范围：新增 `v24/sql/49_host_reads.sql`；修改 `50_permissions.sql`、`v24/load.py` 的两个元组、`v24/s1/setup_db.py` 的 `expected_canonical`、`v24/s1/test_g1.py` 的两处精确 ACL 断言；新增 `v24/s9/{test_g8.py,h_support.py,README.md}`。九个冻结内核 SQL（`10_schema`、`20_triggers`、`30_advance`、`40_interpreters`、`45_capability`、`46_cleanup`、`47_verbs`、`48_loop`、`49_recovery`）的 `git diff --exit-code` 为 0；当前 HEAD `d8155f4`（M-H 改动未提交时）。11 条已冻结 closeout 命令在改动后再次依序实跑，全部 exit 0（**11/11 不变**）。

### 0.6 M-R extension check（G9）— 2026-10-24

> G9 是 **extension check**，不是第 12 条 closeout gate，也不改写历史
> 11/11。M-R 只实现 host worker、durable journal、DeepSeek adapter 与
> opt-in smoke；G10 由后续 M-P 完成（§0.7）。

| extension | 命令 | 状态 | 证据 |
|---|---|---|---|
| G9 | `uv run python v24/s10/test_g9.py` | **通过 11/11，exit 0** | 本节；[`v24/s10/README.md`](../../v24/s10/README.md) |

无参数实跑覆盖 11 个 ID：`G9-A`、`G9-B`、`G9-C`、`G9-D`、`G9-E`、
`G9-F`、`G9-L`、`G9-J1`、`G9-J2`、`G9-J3`、`G9-R`。末行：

```text
[passed] v24 G9 M-R: 11 case(s): G9-A, G9-B, G9-C, G9-D, G9-E, G9-F, G9-L, G9-J1, G9-J2, G9-J3, G9-R
```

关键实测：

- **传输**：全部响应来自脚本化 `ScriptTransport`；`socket.socket.connect`、
  `socket.create_connection`、`urllib.request.urlopen` 与
  `v15.provider.deepseek.build_opener` 在 fixture 前被 deny、在 `finally`
  恢复；静态扫描拒绝 `v24/s10/*.py` 与 host worker/journal 的 socket/HTTP
  import。G9 没有真实网络、没有 API key。
- **映射**：`G9-A` 证明 descriptor key 先净化/截断，再拼 `_` 与 sha256
  前 8 位；journal 的 `tool_map.by_provider`/`by_key` 可逆；第二轮请求回传
  assistant `reasoning_content` 与 `tool_call_id`，且无 `tool_choice` /
  `parallel_tool_calls`。`G9-C` 证明 provider 顺序是 tool effect 的
  `ordinal`，worker 按 effect UUID 执行也不改变 continuation 中 tool
  message 的顺序；batch barrier 只产生一个 continuation；重复 provider
  call id 是 failure，不是 replay。
- **分类**：`G9-D` 的 bad args、未知 tool、缺 id、>16、零调用均
  `failure`（真实 usage，零 tool effect）；矛盾 finish/message、空
  choices、非 JSON、不可信 usage 均 `unknown`。`G9-E` 的 `length` 为
  `unknown` 且截断文本不成为 final；usage 超过 reserve 保留映射后的
  success 与真实 usage，由内核转 semantic `unknown`。
- **失败/恢复**：`G9-F` 的 preflight 无 key 为 failure 且零 HTTP、零
  reserve 消耗；400 为 failure；3xx/408/429/5xx、timeout、连接中断均为
  unknown 且仅一次尝试。`G9-J1` 在 `dispatch_finished` 后崩溃，重启只重交
  journal 中同一 outcome、零 HTTP、无重复 model effect；其 `prepared`
  子场景在无 `dispatch_started` 时重读 DB 资格并执行一次，不重复写
  `effect_prepared`。`G9-J2` 先由
  `command_recover` 转 unknown，旧 journal success 记为 conflict，不能
  复活。`G9-J3` 在 `dispatch_started` 后崩溃，live lease 隔离、零 HTTP；
  过期后一次 recovery sweep 转 unknown，仍零 HTTP。
- **journal/会话**：`G9-L` 实测 `READ COMMITTED`、30s/5s/5s、两连接
  `TRANSACTION_STATUS_IDLE`、`0 < timeout_s ≤ 239`、lease 61/180/299s、
  短 lease 不发 HTTP；journal 目录 0700/文件 0600、第二写者被 POSIX lock
  拒绝、未知 version 与内部 corruption 失败、截断尾被裁剪、secret 被拒。
- **封闭面**：`G9-R` 的 catalog 仍是十表闭集，无 queue/claim/journal 表；
  `run_until_idle(max_rounds=1)` 对两个 ready effect 只执行一个，剩余一个
  明确不作为 fairness 承诺。

边界：G9 不证明真实 provider 的延迟/可用性/费用/模型质量（opt-in smoke
另计且非 gate）；不证明 starvation/fairness（D-S7-2 保持未关闭）；不证明
跨主机 lease、多主机或 M-P plugin/registry。`v24/host/process_io.py` 只是
后续 plugin host 的 scaffolding。


### 0.7 M-P extension check（G10 / Node / multilingual smoke）— 2026-10-24

> G10、`test_node.py --node` 与 `plugin_smoke.py --multilingual-smoke` 都是
> **extension check**，不是第 12 条 closeout gate，也不改写历史 11/11。
> G10 只证 Python 生命周期；Node 与同一 run 多语言是两份独立证据。

| extension | 命令 | 状态 | 证据 |
|---|---|---|---|
| G10（Python） | `uv run python v24/s11/test_g10.py` | **通过 8/8，exit 0** | 本节；[`v24/s11/README.md`](../../v24/s11/README.md) |
| Node 全生命周期 | `uv run python v24/s11/test_node.py --node` | **通过，exit 0**（Node v24.13.1） | 本节；独立 install→…→dispose |
| 同 run 多语言 | `uv run python -m v24.host.plugin_smoke --multilingual-smoke` | **通过，exit 0** | 本节；单 run Python→Node→final |

无参数 G10 实跑覆盖 8 个 ID：`G10-A`、`G10-B`、`G10-C`、`G10-D`、
`G10-E`、`G10-F`、`G10-G`、`G10-H`。末行：

```text
[passed] v24 G10 M-P Python: 8 case(s): G10-A, G10-B, G10-C, G10-D, G10-E, G10-F, G10-G, G10-H
```

关键实测：

- **registry/生命周期**：`G10-A` 用真实 artifact/manifest/descriptor digest
  构造 frozen entry，五字段 lookup 命中，重复/篡改/目录 artifact 在 spawn
  前拒绝；`G10-B` 完成 Python `install → host_prepare → fiber_control(on) →
  start → 真实子进程 Unicode echo → final → off → dispose → host_release →
  disposed`，slot/pin 释放且 scope closed。
- **错误映射**：`G10-C` 的 exit 3 是 `failure`
  `{status:error,code:echo_tool_error}`，无 forced release/unknown→success，
  run 仍可 final 且 install 可 dispose；`G10-D` 的坏帧是 `unknown`，run
  `blocked_unknown`，install 仍 `installed`、`disposed_at NULL`、零
  `host_release`（pin/资源屏障保留）。
- **三个 digest 负例**：`G10-E` 分别用 artifact / adapter / descriptor
  不匹配的 registry 替换，在工具派发前拒绝，patch 的 `run_process` 断言
  **零 spawn**；三例各自先以正确 registry 完成 prepare，避免把 prepare
  失败冒充工具零 spawn。`G10-F` 在 pin digest 字段仍匹配时篡改 slot
  descriptor 字节，spawn 前零进程。
- **幂等与进程边界**：`G10-G` 重复 prepare/release reservation 各只产生
  一行 `host_prepare`/`host_release`，第二次 dispose 不重复副作用；
  `G10-H` 覆盖 success、exit 3、坏帧、第二帧、EOF、stdout 64 KiB 超限、
  stderr 16 KiB 超限、异常退出、timeout、非 object result，所有 started
  进程均有 returncode 且被 reap；超限/超时为 `unknown`（`stdout_limit`/
  `stderr_limit`/`timeout`）。
- **Node**：`test_node.py --node` 独立跑完整 Node 生命周期（Unicode、转义
  换行、空字符串），并断言 Node exit 3 → failure `echo_tool_error`；无
  `--node` 打印 `not_requested` exit 0，Node 缺失打印
  `[SKIP] not_run/toolchain_absent planes=node` exit 2（SKIP 不算通过）。
- **多语言**：`plugin_smoke.py --multilingual-smoke` 在**一个 fixture、一个
  scope、一个 run** 内依次执行 Python 成功（Unicode `'héllo 世界'`）→ Node
  成功（`'line1\nline2'`、空字符串）→ Node exit 3 工具错误 → final；两个
  install 都 `disposed`、`disposed_at` 非空、scope `closed`。最近一次实跑
  `run_id=05651597-40f3-4004-a940-3d5b2cf1a982`。
- **封闭面**：新增只落在 `v24/host/{registry,line_json,plugins,plugin_smoke}.py`
  与 `v24/s11/**`；无产品 SQL/loader/表/列/错误码改动。九个冻结内核 SQL、
  `v24/sql/49_host_reads.sql`、`v15/**`、`v13/**`、`v99/**` diff 为空；
  G10/Node/smoke 运行期间 socket/opener 被 deny，模型仍是 scripted
  transport（无真实网络/provider）。
- **11/11 复跑**：`v24/load.py`、`s1/setup_db.py --self-check`、
  `s1/test_ddl.py`、`s1/test_g1.py`、`s2/test_g3a.py`、`s3/test_g2.py`、
  `s4/test_g2b.py`、`s5/test_g4.py`、`s6/test_g5.py`、`s8/test_g7.py`、
  `s7/test_g6.py` 在最终树上依序 exit 0（11/11）。

边界：G10 使用真实本地解释器子进程，是设计 §9.1 的显式字面偏差
（D-MP-1：本地、确定性、无网络，Python 必然存在）；不证明 Go/Swift/DuckDB、
真实网络 provider、跨主机 lease、starvation/fairness 或多主机；Node 缺失
时的 SKIP 不构成通过。


## 1. S1 具名断言 G1-A … G1-R

| ID | 生产者（本次实跑） | 断言要点 | 结果 |
|---|---|---|---|
| G1-A | `T.catalog`（L112–176） | S1 时 `prosecdef=true` 恰为 `{advance}`；S3 W1 后封闭 DEFINER allowlist 为 `{advance, resolve, run_owner, run_projection, poll, wait_check}`；S6 W1 再加入只读 `recoverable_effects`，advance 仍是唯一可写 DEFINER，其余只读、STABLE、固定 `search_path=pg_catalog, v24`；S1 的四个纯 helper 均 INVOKER+IMMUTABLE（S6 新增 helper 仍 INVOKER）；无 `claim_*`/`lease_*`/`acquire_*`；含 `pg_advisory_xact_lock` 的函数只有 advance；全部函数属主为 `v24_owner`；`aclexplode` 断言 PUBLIC 无 EXECUTE；advance 源码中 G 的 `PERFORM` 先于 reads 的 `FROM` 与任何 `FOR UPDATE`，八段锁语句的次序为 scope→run→effect→install→fiber→episode→slot→pin；函数体无 `http`/`dblink`/`pg_sleep`/`current_setting`/`current_user`；**24 个错误码**（S8/R7 加入第 24 码 `spawn_key_conflict`）全被 `error_v1` 接受，未知码得 `22023` | 通过（本轮 G1 gate；S6 W1 的 allowlist 重述见 §1.1） |
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
| G1-P | `T.permissions` | 三角色各 30 条 DML 全 `42501`；EXECUTE 集合逐角色精确（admin 无 install）；S6 W1–W2 的期望集合加入 `recoverable_effects`/`command_recover`，ACL 闭集增长但 PUBLIC 仍无 EXECUTE；`SET ROLE`/`SET SESSION AUTHORIZATION`/`CREATE TABLE v24.*`/私有 helper 均 `42501`；TEMP 影子不能改写入口；owner 真实 LOGIN 可写十表 | 通过 |
| G1-Q | `T.shapes`、`T.claims_and_receipts` | class 闭集 5 值；6 非闭集与 8 形状族各零写 `invalid_args`；`lease_ms` 边界可达；五 class 各达唯一分支 | 通过 |
| G1-R | `T.expect_envelope` 及各分支 | 封套精确六键；仅 claim+committed 时 `claim={attempt,fence,session_user}`；其余 `claim=null` | 通过 |

### 1.1 G1-A 的断言细化（披露，不是放行）

S1 的 W5 需要一个与 advance 共享 delta 应用的 INVOKER helper `validate_and_apply_install_delta`；S2 的 `settle[]` 又让主 applier `validate_and_apply_delta` 含 `UPDATE v24.effects`。G1-A 的静态检查因此细化为：

- S6 W1 起 `prosecdef=true` 恰为 `{advance, recoverable_effects, resolve, run_owner, run_projection, poll, wait_check}`；advance 是唯一可写 DEFINER，其余为 STABLE、固定 search_path、零 DML/无 advisory lock 的封闭读面 allowlist；
- S6 W2 起 wrapper 元组为 `{scope_control, install, start, cancel, steer, respond, command_recover}`；每个 wrapper 都必须 INVOKER、含 `v24.advance(`、不含 `INSERT INTO`/`UPDATE v24.`/`DELETE FROM`/`pg_advisory_xact_lock`；`command_recover` 的 `recoverable_effects` 预读只产生 `body.candidates`，权威集合在 G 下重读；
- 含 `UPDATE v24.effects` 的函数允许 `{advance, validate_and_apply_install_delta, validate_and_apply_delta}`；三者中只有 advance 是 DEFINER，另两个必须 INVOKER、无任何 EXECUTE 授权、且不可被协议角色调用；
- 含 `pg_advisory_xact_lock` 的仍只允许 advance。

即：放宽的是「源码里只能出现一处 UPDATE 文本」，未放宽「只有一个可写 DEFINER、只有一个可调用写入口」。当前只读 DEFINER allowlist 由 S3 W1 明确加入，S6 W1 再加入 `recoverable_effects`；`run_owner`/`run_projection` 为内部 helper，不授予协议角色 EXECUTE。

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

`V` 包含 G2a-0（读面 ACL/resolve）、G2a-1…8、G2a-10、G2a-11；G2a-9（四写共用 advance、每个 command effect 同事务 settled + request response、poll/wait 零写）由各 verb receipt/replay、事件及十表快照断言覆盖。以下新增断言均由本轮 `V` 实跑通过。`run_owner`/`run_projection` 是内部 DEFINER helper，不授予协议角色 EXECUTE；仅 poll/wait_check 等公共读入口获准调用。`runs` 自 S3 start 起有写入者；revision 从 1 起并在可见状态变化时递增，不再恒为 0。

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
| G2a-11 | claim 仅允许 `host_prepare`/`host_release`；真实 `model_call` 与 seeded `tool_call`/`inspect_resource`/`command_*`/`fiber_reconcile` 一律 `invalid_args` 十表零写；`host_prepare` 仍可 claim。S6 把 command kind 数组扩到 9 项（含 `command_recover`），逐项仍 `invalid_args` + 十表零写；S4/S5 已另开 model/tool/inspect 的 claim，故该行按历史阶段读 | `V.claim_guard`；通过 |
| G3b-1 | run pin 挡 provider release；无引用 run cancel 后释放并允许 off/close | `V`；通过 |
| G3b-2 | claimed tool_call 引用 pin 时 cancel 保持 claimed+cancel_requested、pin 留存；完整静默释放归 S4 | cancel/pin 留存断言通过；完整 claimed/unknown settlement release **未验证 / S4** |
| G3b-3 | withdraw 后新 start 得 `dependency_unresolved`，已存在 run pin/run 仍有效 | `V`；通过 |
| G3b-4 | start→off/deferred→dispose blocked→cancel→off→dispose；dispose→tombstone/episode closed→start `provider_unavailable` | `V`；两条已提交顺序场景通过，不作为并发/锁屏障证明 |
| G3b-5 | start/off 两种顺序；两连接锁屏障证明 advisory G 序列化 | `V`；两连接锁屏障、`pg_blocking_pids()` 与 `pg_locks` 断言通过 |

### 2.3 G2 父门状态

| 父门 | 子门 | 状态 |
|---|---|---|
| G2 | G2a | 完成：本轮 `V` 全绿 |
| G2 | G2b | **完成**：本轮 `G` 的 G2b-A…V 全绿，G2b-T-1…T-10 十条具名零写负例通过 |
| G2 | 父门 | **完成（G2a+G2b）** |

### 2.4 S4 具名断言 G2b-A … G2b-V

`G` 驱动真实协议（LOGIN 角色 + `start`/`claim`/settlement），FakeLLM/FakeTool 只在两次 advance 之间于进程内计算，无套接字、无 sleep。每条断言同时核对 effect 唯一结算、successor 条数、事件、pin 集合与读请求前后快照。

| ID | 生产者（`G`） | 证据要点 | 结果 |
|---|---|---|---|
| G2b-A | `model_only_spine`（`[G2b-A/w1]`）、`tool_batch_spine`（`[G2b-A]`） | W1 纯文本续链 + W2 完整脊柱：start→model→3 条 ready tool（ordinal 0..2、确定性 id、pin 绑定、同一 `batch_digest`）→各自 claim/settle→恰 1 条 continuation（parent=max-ordinal tool、ordinal=0）→final completed；turn/tokens/effect 计数逐步断言 | 通过 |
| G2b-B | `real_claim_settle` | 真实 model claim 得 `{attempt:1,fence:1,owner}`；success 结算后 succeeded、`resource_quiesced_at` 非空、turn=1、无 requests 行 | 通过 |
| G2b-C | `stage_guard` | `claimable_kinds()` 恰为 host 两 kind+model+tool；`inspect_resource`/`command_*`/`fiber_reconcile` 逐一 `invalid_args` 十表零写；`host_prepare` 仍可 claim。S6 的 `COMMAND_KINDS` 为 9 项、`non_members` 同步扩项，`command_recover` 仍 claim-rejected | 通过 |
| G2b-D | `tool_settlement_counters` | 批次内 tool success/failure 各 claim→settle；effect 状态/receipt、turn+1、`tool_call_settled`/`tool_call_failed` 事件 | 通过 |
| G2b-E | `tool_batch_claims_and_guards` | 4 个 fresh fixture、两连接+Barrier 的同 tool 并发 claim：恰一个 token、一个 `deferred`、attempt=1；结算后再 claim `invalid_args`；`pg_blocking_pids`/未授予 advisory lock 证明 G 阻塞 | 通过 |
| G2b-F | `tool_batch_settlement_order` | 2 个 fresh fixture、两连接分别 claim 同批两个不同 tool：两个都拿 token、effect_id 不同、attempt 各 1；继续结算后 continuation 唯一且父为 max-ordinal；creator 随顺序翻转 | 通过 |
| G2b-G | `tool_batch_claims_and_guards` | 同 run 第二条 ready model 直接 INSERT 撞 `u_effects_model_call` 得 `23505`（整事务回滚）；已闭合批次上多余 `claimed` tool → `invalid_outcome` W0、十表相等、该 effect 仍 `claimed`；第二 model 预检是防御性的（D-S4-10） | 通过 |
| G2b-H | `interaction_production` | model success 带 interaction ⇒ run `waiting`、`runs.interaction` 六字段全对（id=origin=model id）、0 successor、1 条 `interaction_created`；同 receipt replay 字节相等 | 通过 |
| G2b-I | `interaction_respond_chain` | respond 消费 ⇒ running、generation+1、恰 1 条 cause=respond model（response/origin/digests）、`interaction_responded`；第二 key ⇒ `interaction_mismatch` **W1**（领域零写 + 一条 failed `command_respond` + receipt） | 通过 |
| G2b-J | `steps_budget_and_admission` | steps=1/tokens=0/continuation 准入三路：不建 reserve-0 model，写 completed+`close_reason='budget_exhausted'`，0 successor | 通过 |
| G2b-K | `tool_call_budget` | 17 个 tool_calls ⇒ `invalid_outcome` W0、无部分批次；16 个照常准入；5 个但只剩 2 ⇒ budget seal、0 tool effect、model 仍 succeeded | 通过 |
| G2b-L | `reserve_conservation` | 准入 reserve=4096 预扣、usage 40 退 4056；守恒账 `initial=spent+active+remaining`；usage>reserve 属语义 unknown（不是 W0）、unknown 不退；token-0 steer/respond 封口；NULL budget 豁免 | 通过 |
| G2b-M | `pending_final_seal` | final 但有 ready tool ⇒ 只写 `close_intent={kind:'final'}`、status 不变、0 successor；drain 后同一 close_intent 封 completed，`final_text` 取自 final receipt，预算快照冻结 | 通过 |
| G2b-N | `tool_unknown_wall` | tool unknown ⇒ effect unknown + 原始 receipt + `resource_quiesced_at IS NULL`、run blocked_unknown、pending/interaction NULL、0 successor、自身 pin 保留；再 claim `invalid_args`；sibling settlement/steer/respond 均 `blocked_unknown` W0 | 通过 |
| G2b-O | `cancel_t2_two_orders`、`cancel_t2_tool_unknown` | 两序均两连接 + held-G advisory barrier + `pg_blocking_pids()`：①settle→cancel：事实保留、cancel seal；②cancel→settle：claimed 变 cancel_requested、late success 只记事实/成本、0 successor；cancel-late tool unknown 保留 cancelled/close_intent/result、`resource_quiesced_at=NULL`、只发 `tool_call_unknown(late=true)`、0 successor、自身 pin 保留 | 通过 |
| G2b-P | `pending_steer_consumption` | claimed tool 使 steer 写 pending、0 model；latest wins；该 tool 结算 ⇒ 恰 1 条 cause=steer model（epoch/generation/instruction/input/reserve/digests 全等）、pending 清空、`pending_steer_consumed`、无旧 continuation；再次 steer 只消费最新 | 通过 |
| G2b-Q | `pending_steer_unknown` | 旧代 tool unknown ⇒ blocked_unknown、pending 清空、0 model、无 continuation、无 consumed 事件 | 通过 |
| G2b-R | `completed_pin_release` | final model 使 run completed 的同一次 advance 释放全部 run pin，`released_by_effect`=该 final effect | 通过 |
| G2b-S | `settlement_pin_release` | 最后一条 tool 成功封 completed 时同 advance 释放全部 pin；unknown tool 只保留自己那条 pin，其余已结算 sibling 的 pin 释放 | 通过 |
| G2b-T | `zero_write_negatives`（`[G2b-T-1]`…`[G2b-T-10]`） | 十条具名十表零写负例，见 §2.4.1；每条 `snapshot(owner)` 前后逐字节相等 | 通过 |
| G2b-U | `regression_surface` | `error_v1` 仍接受其**历史 23 码子集**（`ERROR_CODES` 常量，逐码接受；该 gate 是 S4 回归面，不声称全局闭集；全局 24 码由 G1-A 断言）；host_prepare claim→settle；poll/wait 顶层与投影键集不变；resolve 两次 live 读零写；steer 同 key replay 字节相等；FakeLLM/FakeTool 契约；socket 守卫与源码 import 扫描 | 通过 |
| G2b-V | `structural_retry_and_semantic`（`[G2b-V-1..4]`）、`unknown_path`（`[G2b-V/unknown-wall]`/`[G2b-V/replay]`/`[G2b-V/receipt-conflict]`） | ①同一非法结构 receipt 连交两次均 `invalid_outcome`、十表相等、预算/turn 不变；②随后同一 token 合法 receipt 正常成功结算；③model 的 tool key ∉ live pins 属语义类（effect unknown + 原始 success receipt + run blocked_unknown + pin 保留 + `model_call_unknown{reason:'semantic_violation'}`）；④语义类后同 digest replay、异 digest `receipt_conflict` | 通过 |

#### 2.4.1 G2b-T 十条零写负例

| ID | 场景 | 路径 / 判定 | 结果 |
|---|---|---|---|
| G2b-T-1 | 未打开 kind claim（`inspect_resource`） | 公共 claim → `invalid_args`；attempt/fence 仍 0；十表相等 | 通过 |
| G2b-T-2 | 缺 `body.kind` | model settlement → `invalid_outcome`；effect 仍 `claimed` | 通过 |
| G2b-T-3 | 17 个 `tool_calls` | model settlement → `invalid_outcome`；无部分批次；effect 仍 `claimed` | 通过 |
| G2b-T-4 | tool key 不在 run pins | 公共 claim 的 C18 pin 门 → `invalid_args`；与 G2b-V-3 的结算期语义 unknown 是两条不同路径 | 通过 |
| G2b-T-5 | 重复 ordinal | `v24.validate_and_apply_loop_delta` 的防御性预检（用真实 delta 复制 successor 0 直达；公共 `advance` 不可达）→ `invalid_outcome` | 通过 |
| G2b-T-6 | 确定性 id 冲突 | 公共 claim：新 tool 行 ordinal/request.ordinal 与 `tool_effect_id(parent,ordinal)` 不符 → `invalid_args` | 通过 |
| G2b-T-7 | 错 token | 公共 settlement → `stale_claim`；effect 仍 `claimed` | 通过 |
| G2b-T-8 | unknown 带 successor | `advance` 信封 `v_executable` 守卫（class=unknown + 任一嵌套 `successors` 对象，30_advance.sql:132–147）→ `invalid_args`；effect 仍 `claimed` | 通过 |
| G2b-T-9 | 有 ready effect 时 seal | `v24.loop_sealable(...)` 返回 false、无 `run_completed`、十表相等；结算级“只写 close_intent”由 G2b-M 覆盖（按设计不是零写） | 通过 |
| G2b-T-10 | 已 `blocked_unknown` run 再结算 | 公共 tool settlement → `blocked_unknown`；十表相等 | 通过 |

旧标签映射：本文件此前只有 `[G2b-T-1]`（unknown wall）、`[G2b-T-2]`（replay）、`[G2b-T-3]`（receipt conflict）三个标签，均属 G2b-V 证据；W6 将其改名为 `[G2b-V/unknown-wall]`、`[G2b-V/replay]`、`[G2b-V/receipt-conflict]`（断言未动），把 `T-1…T-10` 留给上表十条零写负例。

### 2.5 S5 具名断言 G4-A … G4-Q

`F` 串行驱动真实协议（LOGIN 角色 + `start`/`fiber_control`/`dispose`/`close`/claim/settlement）；release/inspect 回执由测试直接构造并通过 `advance` 提交（无独立 host 进程），无套接字、无 sleep、无 worker。以下证据均按 `g4_*` 的实际断言记录，不按计划书的愿景措辞。

| ID | 生产者（`F` 函数名 + `[G4-X]` tag） | 证据要点 | 结果 |
|---|---|---|---|
| G4-A | `g4_a` `[G4-A]` | `cleanup_graph(scope)` 恰 **4 节点/3 边**：owner A→R、B→A，dependency A→P；首现序 B<A<R、A<P；`cleanup_closure` 同为 4 个 install；`cleanup_cycle(R)=[]`；`cleanup_slots(A fiber)` 为 `[2,1,0]`；`cleanup_pending(scope)=8`；读前后 `state` 与 `domain_state` 逐字节相等（W0 读面）。 | 通过 |
| G4-B | `g4_b` `[G4-B]` | seeded live activation pin 使 `install_edges(A)` 含 dependency A→P，图首现序 A<P；读前后 `state` 相等；直接 seed 释放该 pin 后 `install_edges(A)=[]`，图中不再有 dependency 边（seeded fixture，非公共路径）。 | 通过 |
| G4-C | `g4_c` `[G4-C]` | provider 有 live consumer pin 时 dispose：`emitted=[]`、P 保持 `dispose_pending`/`disposed_at NULL`、slot `released_at NULL`、pin 未释放、`host_release=0`；consumer off 后 pin 释放且 `released_by_effect` 非空、episode `closed`；再 ≤7 个 dispose stage 内恰 1 条 release，settle 后 P `disposed`+`disposed_at`、slot released、`host_release=1`。 | 通过 |
| G4-D | `g4_d` `[G4-D]` | 同 fiber 3 条贡献 seq `[0,1,2]` 初始全未 released/withdrawn；三次 off 每次恰 +1 released，顺序 `[2]`→`[2,1]`→`[2,1,0]` 且相邻 `released_at` 严格递增；每次 off 后 withdrawn 全为真；episode 前两次 `retiring`/`closed_at NULL`，第三次 `closed`/`closed_at` 非空。 | 通过 |
| G4-E | `g4_e` `[G4-E]` | seeded 3-install owner 环（公共路径无法构造，属 seeded defect）：`cleanup_cycle` 路径长 4、首尾同节点；dispose 得 `cleanup_cycle`，detail path 长 4、`install_id` 指向根，`domain_state` 零写、events 不变、+1 failed effect/+1 request；`v24.install` admission 对同一环同样拒绝（防御性检查），path 长 4、domain 零写、installs 计数不变；queued dependency 环 path 3 且根 `installed` 未被污染；65 节点链返回 `{head}` sentinel、graph depth ≤64。 | 通过 |
| G4-F | `g4_f` `[G4-F]` | release `unknown`（`resource_quiesced_at NULL`）→ install `dispose_pending`、`disposed_at NULL`、`scope_closable.ok=false`；连续 7 次 close 均 `closed_at NULL`、`close_requested_at` 非空、closable false；inspect success `absent` 置 target `resource_quiesced_at`、inspect 自身 NULL、install 仍 pending；新 key 发新 release（新 id/reservation），settle 后 `disposed`；随后 close 到 `closed_at` 且 closable true；另一 fixture 的 prepare failure 得 `prepare_failed`、`disposed_at NULL`、`install_disposed=0`、scope 不 closed。 | 通过 |
| G4-G | `g4_g` `[G4-G]` | parent phase 事件恰 8 条：`request,drain,retire,cascade,barrier,barrier,barrier,finalize`（每个新 key +1；deferred 阶段均 `closed_at NULL`，finalize 后才非空），child phase 单调且末项 `finalize`；parent barrier `pending.children>0`；`child.closed_at < parent.closed_at`；parent/child 各恰 1 条 `scope_closed`；同 key replay 字节相等、十表相等、无新 phase；新 key `already_terminal` 且 domain 不变；drain seeded running run 只改 `close_intent={kind:'close'}`（status/ended_at/0 successor 不变）；retire 使 episode `retiring`、slot `withdrawn_at` 非空而 `released_at NULL`、fiber `want_on=false, control_seq=2`。 | 通过 |
| G4-H | `g4_h` `[G4-H]` | prepare_unknown → dispose 恰 1 条 ready inspect：request 恰 6 键（target=`host_prepare`、`target_reservation=v24:host_prepare:<hp>`、`target_request_digest` 为 hex64）、id=`md5(owner_effect::text\|\|':inspect_resource:'\|\|install::text\|\|':0')`；第二个 key 复用同 inspect（计数仍 1）；claim 仅 effects 行变（其余九表相等）；known 结算后 install `installed`、target 仅 `resource_quiesced_at` 变、inspect 自身 NULL；再 dispose 发确定性 release，settle 后 `disposed`、`host_release=1`、`install_disposed=1`。 | 通过 |
| G4-I | `g4_i` `[G4-I]` | release unknown → dispose 恰 1 条 inspect（`host_release` 仍 1）；inspect unknown → install 保持 `dispose_pending`/`disposed_at NULL`、target 与自身 quiesced 均 NULL、`install_disposed=0`；新 key 发不同 inspect id（确定性公式）、inspect 计数 2、仍 pending；同 receipt replay `disposition=replay` 且十表快照相等。 | 通过 |
| G4-J | `g4_j` `[G4-J]` | ① release unknown → inspect `absent` 置 target quiesced、install 仍 pending → 新 key 新 release（新 id + 新 reservation）、`host_release=2`；settle 后 `disposed`、`install_disposed=1`；② prepare_unknown → inspect `absent` → `prepare_failed` → 新 key dispose **0 条 host_release**、直接 `disposed`、`install_disposed` 恰 1 条且 payload `{released:false,state:'disposed'}`、fiber `disposed_at` 非空。 | 通过 |
| G4-K | `g4_k` `[G4-K]` | prepare_unknown 两分支均走通：known→`installed`→release→`disposed`；absent→`prepare_failed`→0 条 release 直接 `disposed`。seeded `dispose_pending` + ready host_prepare 回执 → `receipt_conflict`，`domain_state` 前后相等、install 仍 `dispose_pending`、host_prepare 仍 `claimed`。 | 通过 |
| G4-L | `g4_l` `[G4-L]` | 同 dispose key replay：response 逐字节相等、十表相等、effects/requests/events 计数不变；release failure（quiesced 非空）→ 仍 pending、`host_release=1`；新 key 新 release（id/reservation 均新）→ settle → `disposed`、`install_disposed=1`；disposed 后新 key `already_terminal` W1（domain 零写、+1 failed effect/request、events 不变、`host_release` 仍 2）；inspect-emitting dispose 同 key replay 字节相等；inspect settlement replay `disposition=replay`、`effect_id` 同、`emitted=[]`、十表相等。 | 通过 |
| G4-M | `g4_m` `[G4-M]` | 8 条按实际写类：M-1 close 已 closed / M-2 dispose 已 disposed / M-5 seeded owner 环 → **W1**（domain 字节相等、+1 failed effect/request、events 不变；M-5 path 长 4 首尾同）；M-3 inspect target 已 quiesced 或非 unknown、M-4 release success 但 install 非 pending、M-7 非法 inspect outcome（`observed='weird'`）→ **W0**（十表字节相等；M-4/M-7 effect 仍 `claimed`）；M-6 6 次 close 在存在未结算 ready release 时仍 `closed_at NULL`、closable false、install pending；M-8 unknown release 后 dispose 只发 inspect（`host_release` 仍 1、install pending、`disposed_at NULL`）。 | 通过 |
| G4-N | `g4_n` `[G4-N]` | host_prepare claim→settle 仍通；`error_v1` 仍接受其**历史 23 码子集**（逐码接受；S5 回归面，不声称全局闭集；全局 24 码由 G1-A 断言）；leaf dispose 同 key replay 全等、新 key `already_terminal`；fiber_control on/off（off 后 `want_on=false`/`current=NULL`/episode `closed`）；start→poll 顶层键集 `{v,revision,changed,run,events}`、run running/owner_fiber 正确、run pin 指向 provider slot 且未释放、model ready；inspect claim 7 个负例（已 quiesced target、终态 target、缺 `v` 的键集、错/缺 `target_reservation`、坏 digest、错确定性 id）均 `invalid_args`、十表字节相等、attempt/fence 0；真实 inspect claim→settle 仅 effects 行变，known 后 `installed`、target quiesced、自身 NULL。 | 通过 |
| G4-O | `g4_o` `[G4-O]` | `close_requested_at` 写入后：create_child/install/start 均 `scope_closed` 且 `domain_state` 与请求前相等；fiber_control(on) `scope_closed`，除 effects/requests/fibers 外十表相等、fiber diff 恰 `{failure_seq,failure}`（`failure_seq=1`、code=`scope_closed`、`want_on=false`、`control_seq=0`）、0 episode/slot/pin；非 owner close 仍 `unauthorized` 且 domain 零写。 | 通过 |
| G4-P | `g4_p` `[G4-P]` | root 2 条贡献 `[0,1]` + 1 child；root dispose 首阶段只发 child release，child settle 后 `disposed`，root 仍 pending；推进到 root release 时 pre-settle：root `dispose_pending`/`disposed_at NULL`、fiber `disposed_at` 非空、slots 顺序 `[1,0]` 全释放、episode `closed`、child `disposed`、root `install_disposed=0`、`host_release=1`；settle 后 root `disposed`+`disposed_at`、fiber disposed、`install_disposed` root=1/child=1、`host_release` root=1/child=1。 | 通过 |
| G4-Q | `g4_q` `[G4-Q]` | seeded 3 层 owner 链初始 `cleanup_pending=6`；单次 root dispose：emitted=1（≤16）、五张 domain 表 changed rows ≤16 且 >0、三层全 `dispose_pending`/无 `disposed_at`、仅 leaf 1 条 release、pending 仍 6；settle leaf → 4；后续每阶段 command 后 pending 持平（4→4、2→2）、settle 清掉计数的 install/effect 义务后下降（4→2、2→0）；最终序列 **`[6,6,4,4,2,2,0]`（单调不增，non-increasing；仅在计数义务清除时严格下降）**，最终 0、三层全 `disposed`。 | 通过 |

`F` 另有一个 `g4_cascade` 函数打印 `[G4-W1]`（**不是** A–Q 之一）：首 stage 标记 3 个 install（installs+fibers 合计 ≤16）、恰 1 successor（指向 child A）、events ≤64；child A 先 release，active 兄弟 B 阻塞 root，B off/dispose/settle 后 root 才发唯一 release 且 `created_at` 晚于 A/B 的 `disposed_at`。它是 owner 级联的补充运行证据，不冒充 G4-B（G4-B 只记录 dependency 边）。`G4-M`/`G4-N` 的子标签（如 `G4-N wrong key set`）是同一函数的细分，不新增 ID。

### 2.6 G4 父门状态

| 父门 | 子门 | 状态 |
|---|---|---|
| G4 | G4-A…G4-Q（17 条具名断言） | **完成**：本轮 `F` 全部通过（17/17） |
| G4 | 父门 | **完成（G4-A…Q）**，17/17 |

### 2.7 G5 / G6 / G7 父门状态

G5 已由 S6 W1–W4 完成并实跑；G6 已由 S7 W1–W2 完成并实跑（30/30 ID）；G7 已由 S8 W1–W3 完成并实跑。三面并发矩阵由 G6 补齐，S7 closeout 为 **11/11（10 既有 + G6）**，G5/G6/G7 三父门均完成。

| 父门 | 状态 | 断言来源 | 证据 / 边界 |
|---|---|---|---|
| G5 crash/replay | **完成（S6 W1–W4，K1–K10 10/10）** | 设计稿 §9 G5 行 + 附录 C.1（K1–K10）+ 附录 C.3；[S6 计划](../plans/v24-s6-crash-recovery-2026-10-24.md)；[`v24/s6/test_g5.py`](../../v24/s6/test_g5.py) | 无参数全量 gate 退出 0，`[G5-K1]`…`[G5-K10]` 各恰一次，末行 `[passed] v24 S6 W1-W4`；每窗口 child/worker/parent backend PID 互异；K4 的 trigger 注入/回滚/删除、K5 的三次 response 字节相等见 §0.2。边界：FakeHost + 持久 journal 证明合同，**不证明**真实 provider/adapter 的 reservation 复用；K2/K3 的 lease 过期是 seeded fixture；K5 为 host-only、预算不适用；`has_more` 仅提示；S6 本身无 S7 并发、无 S8 spawn 证据（S8 见下行） |
| G7 spawn/child run | **完成（S8 W1–W3，G7-A…H + N1–N7）** | 设计稿 §5.5 + 附录 C.2（G7-A…H 与强制负例）+ 附录 C.6（R7/D-S8-9…12）；[S8 计划](../plans/v24-s8-spawn-2026-10-24.md)；[`v24/s8/test_g7.py`](../../v24/s8/test_g7.py) | 无参数全量 gate 退出 0（S6/S8 收尾轮第 10 条命令），`[G7-A]`…`[G7-H]` 与 `[G7-N1]`…`[G7-N7]` 各恰一次（N1/N2 另有 `[G7-N1-lock]`/`[G7-N2-lock]` 证据行，G7-G 另有 `[G7-G evidence]` 附加证据行、`[G7-G]` 结果行仍一次），末行 `[passed] v24 S8 W1-W3 G7-A…H + N1-N7: g7_a,g7_b,g7_c,g7_d,g7_e,g7_f,g7_g,g7_h,n1,n2,n3,n4,n5,n6,n7`；完整输出见 §0.3。**边界**：① FakeHost/进程内 fixture，**不调真实 provider**；② owner pin 受 `c_pins_xor` 约束存为 `consumer_type='run'`、`consumer_run_id=child`、**`consumer_episode_id=NULL`**，owner episode 由 child run 的 `owner_episode_id` 承载，激活 pin 必须恰一条 live（0/>1 → `dependency_unresolved`）；③ child 首 model 的 `toolset` 按**预期 run pin** 计算并在 settlement 后与 `v24.model_digests(child)` 逐字节比对（prospective digest）；④ N2 同 key 异 bytes 的并发败者在 G 串行下得 `receipt_conflict`，第 24 码 `spawn_key_conflict` 由随后携带败者 bytes 的**新父 outcome**产生；⑤ 同 effect 同 bytes 的 receipt replay 返回 S2/S4 冻结 replay 信封（**无 `spawned`**），仅新父 outcome 复用既有 child 时 `spawned.replayed=true`；⑥ child 首 `model_call` 的 `effects.pin_id=NULL`，owner run pin 是独立的 `v24.pins` 行；G7-G 经真实公共 claim 路径（`attempt/fence=1/1`，service login owner）取得 claimed，过期 lease 后由 `v24.command_recover` 结算 unknown、child `blocked_unknown`、spawn edge/child 计数/父 quota 不变、run pin 释放；这是 D-S8-12，不再 seed claim，也无残余 claim 路径债务；⑦ S8 **不证** G6/S7 三面并发（已由 S7/G6 补证），也不证明真实 provider/adapter |
| G6 三面并发 | **完成（S7 W1–W2，30 ID）** | 设计稿 §9 G6 行 + §7 矩阵（6 行 × 3 列 = 18 格）+ 附录 C.2 的 spawn 负例；[S7 计划](../plans/v24-s7-concurrency-2026-10-24.md)；[`v24/s7/README.md`](../../v24/s7/README.md)；[`v24/s7/test_g6.py`](../../v24/s7/test_g6.py) | 无参数全量 `uv run python v24/s7/test_g6.py` 退出 0，**30/30 ID** = 16 条矩阵（A1；B1–B3；C1–C3；D1；E1；F1；G1–G3；H1–H3）+ N1–N9（9 条负例）+ L1–L5（5 条锁序审计）；末行逐字为 `[passed] v24 S7 W1-W2 G6-A…H + N1-N9 + L1-L5: g6_a1,g6_b1,g6_b2,g6_b3,g6_c1,g6_c2,g6_c3,g6_d1,g6_e1,g6_f1,g6_g1,g6_g2,g6_g3,g6_h1,g6_h2,g6_h3,g6_n1,g6_n2,g6_n3,g6_n4,g6_n5,g6_n6,g6_n7,g6_n8,g6_n9,g6_l1,g6_l2,g6_l3,g6_l4,g6_l5`；18 格全部落位、无空格（格 1 = `G6-A1`，格 3 = `G6-N1`，格 4–18 = `G6-B1`–`G6-H3`）；格 2 = **G3b-5 closeout 重跑，仅此**（非 G6 body，不计第 31 ID），证据命令 `uv run python v24/s3/test_g2.py` 退出 0，证据行逐字为 `[G3b-5] two fresh fixtures/two connections: pg_blocking_pids + waiting advisory pg_locks prove G serialization; start-first/off deferred; off-first/start dependency_unresolved with no run/pin`；S7 closeout 为 **11/11（10 既有 + G6）**。**边界**：Fake-only、无真实 provider/网络、无跨主机 lease、无 starvation/公平性证明、无 G5 崩溃窗口重测、无多主机；evidence-only，无产品改动（24/0 不变）。 |

## 3. 错误码覆盖（24 码）

`error_v1` 接受全部 24 码（签名冻结，G1-A 已逐码断言）。**能产生**与**能接受**是两件事；S5 收口后 23 码均有实测生产者，S8/R7 新增第 24 码 `spawn_key_conflict` 并由 G7 产生，因此当前 **24 码均有实测生产者，未产生集合为空**。S6 **不新增错误码**，G5 只使用既有码：`[G5-D3]`/`[G5-W2]` 的 `invalid_args`、`[G5-W2]` 的 `not_found_or_denied`/`request_conflict`、`[G5-K3]` 的 `receipt_conflict` 均为 W0。S8 只新增 R7 的 `spawn_key_conflict`（W0），其余 23 码不变。

### 3.1 有生产者的 24 码

| 码 | 写类 | 生产者证据 |
|---|---|---|
| `invalid_args` | W0 | `T.shapes`/`T.command_prefix`/`T.claims_and_receipts`；`R` 的 manifest 形状、CAS 参数、缺 owner 等；S4 claim 前闸门 `G2b-T-1`/`G2b-T-4`/`G2b-T-6` 与 `G2b-T-8` 的 unknown+successor 信封守卫；S5 `G4-N`/`G4-M-3`（inspect claim 的键集/reservation/digest/id 与 target 状态）均 W0 十表零写 |
| `unauthorized` | W0 | `T.identities_and_matrix`；`G4-O` 非 owner close 仍 `unauthorized`，domain 零写 |
| `request_conflict` | W0 | `T.command_prefix` |
| `effect_id_conflict` | W0 | `T.command_prefix`、`T.claims_and_receipts` |
| `receipt_conflict` | W0 | `T.claims_and_receipts`、`T.install_settlement_w5`；`R.dispose_leaf`（dispose_pending 期间的 host_prepare）；`G4-K`/`G4-M-4`（seeded dispose_pending 与 release success 但 install 非 pending） |
| `stale_claim` | W0 | `T.claims_and_receipts`、`T.install_settlement_w5`；S4 对 model/tool 过期 lease 与错 token 同样零写（D-S4-1，`G2b-T-7`） |
| `retry_with_closure` | W0 | `T.closure_retry`、`R.closure_fail_closed_and_seam` |
| `scope_closed` | W1 | `T.scope_control_w4`、`T.install_settlement_w5`、`R.fiber_control_activation`；`G4-O`（close_requested_at 后 create_child/install/start/fiber_control(on) 均命中） |
| `install_identity_conflict` | W1 | `T.install_settlement_w5` |
| `invalid_outcome` | W0（实测） | `T.install_settlement_w5`、`R` 的 delta 预检；S4 扩展到 loop 的真实结构路径：`G2b-T-2`（缺 body.kind）、`G2b-T-3`（17 tool_calls）、`G2b-T-5`（重复 ordinal，applier 防御预检）、`G2b-K`、`G2b-V-1`；S5 `G4-M-7`（非法 inspect outcome，effect 仍 claimed）。语义类不返回此码（结算为 unknown，见 `G2b-V-3`） |
| `stale_generation` | W1 | `R.fiber_control_activation`（fiber CAS） |
| `already_terminal` | W1 | `R.install_fibers`（disposed fiber）、`R.dispose_leaf`（disposed install）；`G4-L`/`G4-N`/`G4-M-1`/`G4-M-2`（disposed install 或 closed scope 的新 key） |
| `install_not_ready` | W1 | `R.install_fibers`（child owner 无 active episode）、`R.fiber_control_activation`（install 非 installed） |
| `owner_closing` | W1 | `R.install_fibers`（owner `want_on=false`） |
| `dependency_unresolved` | W1 | `R.fiber_control_activation`（缺 slot / policy=false） |
| `provide_conflict` | W1 | `R.fiber_control_activation` |
| `not_found_or_denied` | W0 | `V.poll_contract` / `V.wait_check_contract`；本轮通过 |
| `registration_stale` | W0 | `V.wait_check_contract`；本轮通过 |
| `interaction_mismatch` | **W1**（S4 更正） | `G2b-I`：领域零写，但写一条 failed `command_respond` effect 与其 request receipt；S3 的 `V.respond_contract` 只覆盖不匹配拒绝，S4 补齐 receipt 写类 |
| `provider_unavailable` | W1 | `V.start_failures`、G3b-4；本轮通过 |
| `budget_exceeded` | W1 | `V.start_failures` / `V.start_boundaries`；S4 的预算耗尽走 `close_reason='budget_exhausted'`，不新增该码生产者 |
| `blocked_unknown` | W0（墙）/ W1（结算） | S4 新增：`G2b-N`（tool unknown 使 run blocked_unknown；sibling settlement/steer/respond 的 W0 墙）、`G2b-T-10`（已 blocked run 再结算 W0）、`G2b-Q`（pending steer + unknown，0 model）、`G2b-O/tool-unknown`（cancel-late unknown 保留 cancelled，不产生本码） |
| `cleanup_cycle` | W1 | `v24.cleanup_cycle` helper（`46_cleanup.sql:148`），由 `dispose_stage` 的根检查（`46_cleanup.sql:852`）、级联队列逐节点检查（`46_cleanup.sql:879`）与 `interpret_install` 的 admission 检查（`40_interpreters.sql:2871`）抛出；`G4-E`（seeded owner 环 + queued dependency 环）与 `G4-M-5` 实跑触发：failed command effect/request 各 +1、domain 零写。环是 seeded defect，公共路径不可构造（D-S5-9） |
| `spawn_key_conflict` | W0 | S8/R7 第 24 码。`G7-C`：同 `(parent_run_id,spawn_key)` 异 canonical bytes、即使 request_key 不同，返回该码，十表逐字节相等、model effect 仍 `claimed`；`G7-N2`：并发同 key 异 bytes 的败者先得 `receipt_conflict`（G 串行），随后携带败者 bytes 的**新父 outcome**再产生本码，同样十表 W0；G1-A 逐码接受 |

### 3.2 未产生的错误码：0 码（无未产生错误码）

S8 收口后，`error_v1` 的 24 码闭集与生产者集合相同：**没有**「仅白名单、无调用点」的码。`cleanup_cycle` 已由 S5 接入（见 §3.1 的 `cleanup_cycle` 行与 `G4-E`/`G4-M-5`）；第 24 码 `spawn_key_conflict` 已由 S8 的 `G7-C` 与 `G7-N2` 的随后新父 outcome 接入（见 §3.1 末行）。§3.1 现有 24 行生产者证据，§3.2 为空集（0 码）。

## 4. 无写入者 / 不适用 / 未验证

| 项 | 处理 |
|---|---|
| `runs` 的领域行为 | S3 `start` 是首个 writer；revision 从 1 开始，后续可见变化递增；G2a assertion 在 `V` 本轮通过 |
| run pin 半部 | **已验证**：G2b-R 证明 completed 同 advance 释放全部 pin；G2b-S 证明最后一条 tool 封 completed 与 unknown 只保留自身 pin；G3b-2 的“claimed/unknown 完整释放”不再悬空 |
| `inspect_resource` 收敛 | **已验证（S5）**：`inspect_resource` 已在 W2 打开 claim 并列入 `claimable_kinds()`；G4-H（prepare_unknown→inspect known→installed→release→disposed）、G4-I（release unknown→inspect unknown 保持 pending，新 key 新 id）、G4-J（absent 两分支）、G4-K（prepare_unknown 两分支 + `receipt_conflict`）、G4-N（inspect claim 7 个负例 + 真实 claim→settle）逐条通过 |
| owner 级联 / scope close / 完整 dispose 闭包 | **已验证（S5）**：G4-A（4 节点/3 边合并 DAG、child-before-owner 首现序）、G4-C（consumer 先于 provider）、G4-P（墓碑只在 child/贡献/episode 义务清零后）、G4-Q（有界阶段）；child 先于 owner 的 dispose 级联另由 `g4_cascade` 的 `[G4-W1]` 断言（首 stage 标记 3 个 install、installs+fibers 合计 ≤16、1 successor、root release 晚于 child `disposed_at`）。scope close 由 G4-G/G4-O 覆盖（phase 序、`child.closed_at < parent.closed_at`、close 后无新准入） |
| **S5 证明边界** | **仅串行 request-key 阶段**：每个新 key 推进一个 bounded phase（≤16 行、≤16 successor），无 worker、无自动推进；G4 的命令/回执串行执行，release/inspect 回执直接提交，无外部 host 进程。S5 本身**不证**崩溃/恢复/reclaim，也**不证**并发面（S7）；崩溃/恢复已由 S6 的 G5 补证（见 §0.2），并发仍归 S7（已由 S7/G6 补证，见 §2.7） |
| **S6 证明边界** | **仅 FakeHost/journal 下的崩溃恢复合同**：K1–K10 是单写者顺序窗口，恢复只经 `resolve` + `recoverable_effects` + `command_recover`，无 recovery 表/队列/lease/cursor、无第二 claim 路径。**不证**真实 provider/transport 的 reservation 幂等（真实 adapter 必须自行复用 reservation），**不证** S7 三面并发或 S8 spawn（S7 并发已由 G6 补证，见 §2.7）；K2/K3 的 lease 过期是 seeded fixture，K5 为 host-only 且预算不适用 |
| **M-P 证明边界** | **真实本地子进程 + scripted model + 真实 PostgreSQL fixture**：G10-A…H 证明 approved registry、line-JSON 边界、两个参考插件的 Python 全生命周期、dispose 屏障与三个 digest 零 spawn 负例；`test_node.py --node` 是独立 Node 全生命周期；`plugin_smoke.py --multilingual-smoke` 才是同一 run Python → Node → final。**不证**真实网络/provider（D-MP-1 为 §9.1 字面偏差）、Go/Swift/DuckDB、跨主机 lease、starvation/fairness（D-S7-2 保持）。 |
| **M-R 证明边界** | **仅脚本化 transport + 真实 PostgreSQL fixture**：G9-A…R 证明 host worker 的 claim/re-read/lease/journal/重启对账、DeepSeek wire 映射和 opt-in 入口；所有 provider 响应是脚本化的，**不证**真实网络/延迟/费用/模型质量，也**不证** starvation/fairness（D-S7-2 保持）、跨主机 lease、多主机或 M-P plugin/registry。真实套接字只出现在 `v24/host/smoke.py --real-provider-smoke`，它不是 gate；G9 运行期间 socket/opener 被 deny。 |
| interaction 生产 | **已验证（S4）**：G2b-H 由 model outcome 真实生产 `runs.interaction` 与 `waiting`；S3 仅 seed 消费 |
| spawn / child run | **已验证（S8/G7）**：G7-A…H + N1–N7 全绿（无参数 gate 退出 0，见 §0.3/§2.7）。同一 advance 原子创建 child run + spawn edge 三列 + 父 quota 扣减 + child 初始 quota + 可选 owner run pin + child 首 `model_call`；同 key 同 bytes replay 同 child、不二次扣 quota；同 key 异 bytes 得 `spawn_key_conflict` W0；child 是 run，不是 fiber/install。边界：FakeHost/进程内 fixture、**无真实 provider**；owner pin 受 `c_pins_xor` 约束（run pin `consumer_episode_id=NULL`，owner episode 记在 child run），激活 pin 恰一条 live，child 首 model 的 `toolset` 按预期 pin 计算；N2 并发败者先得 `receipt_conflict`（G 串行），24 码由随后携带败者 bytes 的新父 outcome 产生；同 effect 同 bytes 的 receipt replay 是冻结六键信封（无 `spawned`）；G7-G 的 child 首 model 走真实公共 claim 路径（`pin_id=NULL`、`attempt/fence=1/1`，service login owner），过期后经 `command_recover` 结算 unknown；owner run pin 是独立 `pins` 行（D-S8-12，无 seeded claim/claim 路径债务）；S8 **不证** G6/S7 三面并发（已由 S7/G6 补证） |
| 完整崩溃恢复 / reclaim | **已验证（S6/G5）**：K1–K10 证明 `SIGKILL`（K4 为 SQL 错误注入）后由新 `recover_worker.py` 进程收敛；`replay_safe` 回 ready、`no_replay` 只转 unknown、`manual` 只计数；没有自动 reclaim worker/定时器，恢复入口是命令驱动的 `command_recover`。S4 的“过期 lease 不产生第二次 attempt”与 S5 的命令驱动 inspect 仍有效；S8 的 G7-G 复用该入口处理 child 首 model |
| `resolve` 只读 | S2 gate 曾以 owner 测试；S3 W1 将它改为 DEFINER，并在 `V` 通过真实 service/operator/admin LOGIN 验证；poll/wait 同样由 `V` 验证 |
| 并发矩阵 | S4 新增 G2b-E（同 tool claim 并发）、G2b-F（同批两 tool 并发）、G2b-O（cancel×T2 两序）三组两连接 + Barrier/held-G + `pg_blocking_pids()` 证据；G1-L、G3a-F、G3b-5 仍有效；G3b-4 为顺序场景；**S5 的 G4 与 S6 的 G5 均为串行窗口，不新增并发证据**；S8 的 G7-N1/N2 新增 spawn 的两连接 + Barrier/held-G + `pg_blocking_pids()` 证据（同 key 同 bytes / 同 key 异 bytes），但仅证明 G 串行下的两条 spawn 负例，**不是**三面并发矩阵；**完整三面并发矩阵：G6 完成（S7 W1–W2，30 ID）**，S7 的 18 格、30 ID、9 负例与 5 锁序证据见 §0.4/§2.7；S7 closeout 为 **11/11（10 既有 + G6）** |
| 真实 host IO / 网络 | FakeHost/FakeLLM/FakeTool 纯进程内、无套接字；S6 的 `CrashHost` + JSONL + `v24_fake.journal` 同样无网络，只证明 reservation 复用/持久 receipt 的合同，**不是 transport 证明**；S8 的 G7 仍为进程内 fixture，`[G7-F]` 断言无 socket/HTTP 且 `v24_fake.journal` 新增 0 行；M-H 的 G8 同样无网络，socket 仅被 monkeypatch 后 deny/restore |
| **host 只读面 / D-S6-12 / D-S8-7** | **已验证（M-H/G8）**：9 个公开 host 读者 + 隐藏 helper 的 ACL/键闭集/游标/拒绝/只读/held-G 证据由 `G8-H1`…`H13` 覆盖；D-S6-12 由 `G8-D1a` 的 closed-scope 非空候选关闭，D-S8-7 由 `G8-D2` 的四种 spawn 混用关闭。边界：无 host worker/真实 provider（M-R）；W1 只证 SQL/session 前置；starvation/fairness 仍归 D-S7-2 |
| `advance.revision` | S3 `start` 写 `revision=1`，可见状态变化由 advance 更新；已不再是常量 0 |
| **P1/S3.1 claim guard → C18 阶段 allowlist** | S3.1 的临时 guard 仅允许 host 两 kind；S4 W1/W2 按 C18 打开 `model_call`/`tool_call`；S5 W2 再打开 `inspect_resource`，真相源为 `v24.claimable_kinds()`（恰 host 两 kind+model+tool+inspect，5 项）。S6 新增 `command_recover` 为第 9 个 command kind，但**仍不可 claim**；仍关闭的 `command_*`/`fiber_reconcile` 一律 W0 `invalid_args` 十表零写（`G2b-C`、`G2b-T-1` 的剩余非成员；`G4-N` 覆盖 inspect claim；`G2a-11`/`G2b-C` 的 command 数组已扩到 9 项）。S4/S5/S6 都不以“取消 guard”放行，而是把阶段集合变成可断言对象 |
| DDL 语义 vs advance 语义 | G1-O 证明 DDL 能拒绝；advance 语义由 G1/G3a/G2a/G3b 的具名断言分列 |

## 5. 结论

- S6/S8 收尾轮十个 gate 全部实际退出 0（历史 **10/10**，见 §0）；G2a/G3b 来自 `V`，G2b-A…V 与 G2b-T-1…T-10 来自 `G` 本轮通过输出，G4-A…G4-Q（17/17）来自 `F` 本轮通过输出，G5 K1–K10（10/10）来自 `I` 本轮通过输出，G7-A…H + N1–N7 来自 `J` 本轮通过输出。**历史 Gate 计数口径（9+1=10）**：9 个既有 gate + 无参数全量 G7 = 10 条命令，全部退出 0（10/10）；历史 S6 W1–W3 与 S8 W1/W2 的 `--only` 是增量检查点，不计入上述 gate 计数，也不替代父门。**S7 closeout 追加第 11 条无参数全量 G6 后为 11/11（10 既有 + G6）**，见 §0.4。
- G2 父门：**完成（G2a+G2b）**。G3 父门：**完成（G3a+G3b）**。G4 父门：**完成（G4-A…Q，17/17）**。G5 父门：**完成（S6 W1–W4，K1–K10 10/10）**；无参数全量 G5 末行恰为 `[passed] v24 S6 W1-W4`。**G7 父门：完成（S8 W1–W3，G7-A…H + N1–N7）**；无参数全量 G7 末行恰为 `[passed] v24 S8 W1-W3 G7-A…H + N1-N7: g7_a,g7_b,g7_c,g7_d,g7_e,g7_f,g7_g,g7_h,n1,n2,n3,n4,n5,n6,n7`。**G6 父门：完成（S7 W1–W2，30 ID）**；无参数全量 G6 末行恰为 `[passed] v24 S7 W1-W2 G6-A…H + N1-N9 + L1-L5: g6_a1,g6_b1,g6_b2,g6_b3,g6_c1,g6_c2,g6_c3,g6_d1,g6_e1,g6_f1,g6_g1,g6_g2,g6_g3,g6_h1,g6_h2,g6_h3,g6_n1,g6_n2,g6_n3,g6_n4,g6_n5,g6_n6,g6_n7,g6_n8,g6_n9,g6_l1,g6_l2,g6_l3,g6_l4,g6_l5`；S7 closeout 为 **11/11（10 既有 + G6）**。
- 错误码：**24/0（24 个有生产者、0 个未产生）**。S5 把 `cleanup_cycle` 接入（`46_cleanup.sql:148` helper，`:852`/`:879` 与 `40_interpreters.sql:2871` 抛出；`G4-E`/`G4-M-5` 触发）；S8/R7 新增第 24 码 `spawn_key_conflict`（W0），由 `G7-C` 与 `G7-N2` 的随后新父 outcome 产生；`blocked_unknown` 由 S4 新增，`invalid_outcome` 从 install 预检扩展到 loop 结构路径。S6 不新增码，只使用既有码；S8 只新增 R7 的这一码。
- S5 边界：inspect 收敛、owner 级联/scope close/完整 dispose 闭包已由 G4 验证；仅覆盖**串行 request-key 阶段**（每个新 key 一个 bounded phase、≤16 行/successor、无 worker/自动推进）。S6 边界：崩溃/恢复合同已由 G5 在 FakeHost/journal 下验证（命令驱动，无 recovery 表/队列/lease/cursor），但**不证明真实 provider/adapter 的 reservation 幂等**；K2/K3 的 lease 过期是 seeded fixture，K5 为 host-only、预算不适用，`has_more` 只是提示。S8 边界：spawn/child-run 合同已由 G7 在 FakeHost/进程内 fixture 下验证，**不调真实 provider**；owner pin 的物理映射为 `consumer_episode_id=NULL`、激活 pin 恰一条 live、child 首 `toolset` 为预期 pin 摘要；N2 的并发败者是 `receipt_conflict`，`spawn_key_conflict` 由随后新父 outcome 产生；receipt replay 是冻结六键信封；G7-G 的 child 首 model 走真实公共 claim（`pin_id=NULL`、`attempt/fence=1/1`），owner run pin 是独立 `pins` 行，过期后由 `command_recover` 结算 unknown（D-S8-12，无 seeded claim 债务）。**S8 不证** G6/S7 三面并发（已由 S7/G6 补证）；完整并发矩阵归 S7 并已由 G6 补齐，真实 provider/网络仍不作证明。
- S6 W4 范围（历史）：代码只改 `v24/s6/{crash_worker.py,recover_worker.py,test_g5.py}`；**无产品 SQL 改动**，`v24/sql/48_loop.sql` 未动，`v24/sql/**` digest 在 gate 前后均为 `827e1c61515b9e6d5f4f7104d914bd4d53be483d171dc4c548bd8620d15900fd`；HEAD 仍 `45877b0`，未 commit/push。S8 W1/W2 按计划不提交，W3 为单一里程碑提交；本收尾稿编辑时 HEAD 仍 `a13ba77` + 未提交 S8 W1–W3；W3 除 `v24/s8/test_g7.py` 与收尾文档外，还按 D-S8-12 修改 `v24/sql/48_loop.sql`（child 首 `model_call` 的 `pin_id=NULL`，applier 要求 child effect `pin_id IS NULL`），**无新对象/新错误码**（deviation ledger §1.14(i)）。
- **M-H 结项（2026-10-24）**：host 只读面 9 个公开函数 + `host_scope_allowed` 已落地；DEFINER 17、GRANT 27、逐角色 EXECUTE 26/27/27；G8 **23/23** exit 0；闭包 `B=3`、`H_ok=509`、`H_bad=510`、`C=512/513`；H13 实测 64.00 MiB 页；D-S6-12 由 `G8-D1a` 关闭，D-S8-7 由 `G8-D2` 关闭；九个冻结内核 SQL 的 diff 为空；11 条既有 closeout 在改动后复跑 **11/11**。G8 是 extension check，不改变历史 closeout 计数；G9 已运行 11/11（§0.6），G10 后续由 M-P 完成（§0.7）。
- **M-P 验收（2026-10-24）**：G10 **8/8** exit 0；`test_node.py --node` 独立 exit 0（Node v24.13.1）；`plugin_smoke.py --multilingual-smoke` exit 0：同一 run Python → Node → final，Unicode/转义换行/空字符串/exit 3 全覆盖，两个 install disposed、scope closed；九个冻结内核 SQL、`v15/**`、`v13/**`、`v99/**` diff 为空；11 条既有 closeout 复跑 **11/11**。D-MP-1 为 §9.1 字面偏差（真实本地子进程），见台账 §1.18。
- 结项状态：G7（S8）已**完成**；G6（S7）已**完成（S7 W1–W2，30 ID）**，三面并发矩阵已由 S7 补齐，S7 closeout 为 **11/11（10 既有 + G6）**；M-H（G8）已**完成（23/23）**；M-R（G9）已**完成（11/11）**；M-P（G10）已**完成（8/8 + Node + multilingual smoke）**。本矩阵仍不宣称真实 provider/网络（仅 opt-in smoke）、跨主机 lease、starvation/公平性、G5 崩溃窗口重测或多主机证据；顺序 S6 → S8 → S7 → M-H → M-R → M-P，S7 的 11/11 保持冻结。


## Post-closeout M-H / P0（2026-10-25）

P0 重新运行 closeout 11/11、G8 23/23、G9 11/11、G10 8/8，全部 exit 0；M-H 再跑 closeout 11/11 与 G8 23/23，全部 exit 0。逐命令时间、源码身份、结果行与九 SQL SHA-256 见正式后续计划的执行记录。历史记录保留，G8/G9/G10 仍为 extension checks。H13 67,107,712 B 仅为夹具序列化尺寸，不是响应/内存上限；分页仍为 64 项。


## Post-closeout M-M（2026-10-25）

D3：v24 固定 `deepseek-flash`；无运行时 allowlist，不消费 v15 allowlist。本轮不新增模型参数、环境 override 或 CLI，不修改 adapter 与 v15。closeout 11/11、G9 11/11 均 exit 0；逐命令时间/source/result 见正式后续计划。外部型号与计价事实没有重新查询。

## Post-closeout M-S（2026-10-25）

M-S 修复 smoke 终态核验：保存 `start` 已提交的 scope/run/model handles，完成后从 `host_runs` 与 `host_run_effects` 历史读取面核验 run/effect 身份、completed/succeeded outcome、final 文本、usage 及 journal 的 `dispatch_started`/`dispatch_finished` 绑定。成功摘要在泄漏检查、journal/DB/原始连接关闭、fixture 退出、临时目录删除并确认不存在后才打印；删除启动前失败保留完整 journal，部分删除失败报告剩余证据，不重试。G9-B/F/L 新增并覆盖结算后 model 离开 active work list、空 final、唯一 request key、未完成/取消后的 late success、异常历史/分页/journal、初始化和清理失败、partial deletion，以及 cleanup interrupt；网络 deny、ScriptTransport、borrowed fixture 与 11 个顶层 ID 保持不变。

| extension | 命令 | 状态 | 证据 |
|---|---|---|---|
| closeout | 11 条冻结命令（见正式计划执行记录） | **通过 11/11，exit 0** | source `6df64440299b4e6035e9e587bebd5f09eb9d9cbe` 的 M-S 树；各结果行见计划 |
| G9 | `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s10/test_g9.py` | **通过 11/11，exit 0** | 同上；无真实网络、无 API key |

M-S 不改变九个冻结 SQL、host worker/journal/transport 格式或 closeout 计数；真实 provider smoke 仍为 opt-in，当次未授权且未执行。（2026-10-29 更新：已取得授权并实跑一次 live 并通过，见下文「Post-closeout M-E live」。）

## Post-closeout M-E（2026-10-25）

`recorded_at=2026-10-25`。M-E 的两条入口负控已实际执行；未检查实际 key 是否存在，无 flag 命令直接短路，flag 负控显式清除凭据；没有取得 live 授权。`negative_control` 与 `live_attempt` 独立登记，未把负控的 exit 2 复制为 live 结果。

| record_group | executed_at | source_sha | command | status | reason | exit_code |
|---|---|---|---|---|---|---|
| `negative_control` | 2026-10-25T11:05:35+08:00 Asia/Shanghai | `e869e81` | `UV_NO_ENV_FILE=1 uv run python -m v24.host.smoke` | passed | `not_requested` | 0 |
| `negative_control` | 2026-10-25T11:05:35+08:00 Asia/Shanghai | `e869e81` | `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python -m v24.host.smoke --real-provider-smoke` | passed | `credentials_absent` | 2 |
| `live_attempt` | `not_executed` | `e869e81` | 拟执行：`UV_NO_ENV_FILE=1 /usr/bin/time -p uv run python -m v24.host.smoke --real-provider-smoke` | `not_run` | `not_authorized` | `not_executed` |

这组结果证明入口短路行为，不证明当前环境本来没有 key，也不证明真实 provider 成功、失败、延迟、费用或模型质量。live attempt 的成功摘要（endpoint/model/run/effect/tokens/finish/provider wall_ms）和外部耗时均为 `not_executed`，证明范围为空；D-S7-2 继续开启。

## Post-closeout M-E live（2026-10-29）

`recorded_at=2026-10-29`。用户明确授权一次真实 provider 调用；`live_attempt` 由 `not_run/not_authorized/not_executed` 更新为已运行并通过。同日复跑两条负控仍为 `not_requested`/0 与 `credentials_absent`/2。

| record_group | executed_at | source_sha | command | status | reason | exit_code |
|---|---|---|---|---|---|---|
| `live_attempt` | 2026-10-29T16:31:07+08:00 Asia/Shanghai | `45886fe` | `UV_NO_ENV_FILE=1 /usr/bin/time -p uv run python -m v24.host.smoke --real-provider-smoke` | passed | `live_success` | 0 |

唯一输出行：`[smoke] endpoint=api.deepseek.com model=deepseek-flash run=bd944a8f-e2b4-4859-a97b-46d7de40bbdd effect=fc328faf-5312-ef02-e16d-d2ab92262c69 tokens=57 finish=stop wall_ms=1206 result=completed`；外部耗时 `real 4.30`。

证明边界：只证明一次真实 `start → model → final` 链路可用、终态核验正确；不证明延迟/可用性/成本/质量的统计结论，也不评模型质量。D-S7-2、跨主机租约、第二批语言与 provider 性能/质量债务保持开启；live smoke 不是 gate，不改变 closeout 11/11、G8 23/23、G9 11/11、G10 8/8 计数。

## Post-closeout M-F（2026-10-25）

四项后续范围已分别登记，均不在本轮实现：第二批 Go/Swift/DuckDB、D-S7-2 公平性、跨主机租约、provider 延迟/质量。当前源 `74b3c30` 的 G10 Python、Node 与同 run multilingual 检查均 exit 0；最终发布候选仍须重跑 Node 与 multilingual 两条命令。


## Post-closeout M-P release candidate (2026-10-25)

The clean candidate uses v24 source `6d53a2d05a2e5439e7694125d4751ba053acb147` on main base `ab34d6972a17f688c4a11adba89e363d74adbe81`, with tested execution tree `da983510998ee2c2121cb69f86ae597122465818`. The 11 frozen closeout commands, G8 23/23, G9 11/11, G10 8/8, Node, multilingual smoke, and both v99 Phase 0 commands all exited 0.

`bddeb815608de37bc21594a372085fe1e591db85` (v99 Phase 0) already belongs to the main-base ancestry, so this candidate does not newly introduce v99. W1–W4 remain incomplete. The candidate is **release ready, not published**; no merge SHA or remote-main claim exists.

Full candidate evidence and manifest: [release record](v24-release-2026-10-25.md).
## Post-closeout M-F1（2026-10-25）

M-F1 在 v24 未提交执行树上完成并通过 31/31 命令：G11 全量、G11-A…L 单 case、loader/DB/既有 gate、G8、G9、G10、Node、smoke 负控与 multilingual smoke。新增 S12 证明的是有限 opportunity-dense host-only FC 子合同及其 Fake-only 对抗证据；不改历史 closeout 11/11、G8 23/23、G9 11/11 或 G10 8/8 计数。完整命令、时间、source/tree 摘要和日志 SHA-256 见 [`v24-d-s7-2-fairness-execution-2026-10-25.md`](v24-d-s7-2-fairness-execution-2026-10-25.md)。D-S7-2 广义债务仍开启：开放到达、墙钟等待/debt 有界、跨崩溃/多主机和真实 provider 公平性未由本批次证明。
