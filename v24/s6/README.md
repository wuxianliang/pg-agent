# v24 S6 崩溃恢复（G5）

> 状态：S6 W1–W4 已完成，G5 父门完成（K1–K10 10/10）；无参数全量 gate 退出 0，末行恰为 `[passed] v24 S6 W1-W4`。Oracle chat `028D07` 的 15 项裁决（D-S6-1…12、CC-1…3）已落位。本文只记录实现、运行方式与证据口径，合同以 [S6 计划](../../docs/plans/v24-s6-crash-recovery-2026-10-24.md) 和[设计稿](../../docs/designs/v24-pg-agent-2026-10-22.md) §8/§9/附录 C 为准。

## 1. 目的与架构

S6 只回答一个问题：进程在 effect 生命周期的任一提交边界被 `SIGKILL`（K4 为 fixture-only SQL 错误注入）后，重启如何收敛。固定路径只有三段：

```text
resolve(scope, keys)                         -- 既有只读解析面
  -> v24.recoverable_effects(scope, limit)   -- 唯一的过期 claim 只读发现面
  -> v24.command_recover(scope, key, limit)  -- 唯一命令入口，恰好一次 advance
       -> v24.interpret_recover(...)          -- G 下重发现，返回一个 delta
```

架构约束：

- 恢复发现面恰有一个只读 `SECURITY DEFINER` `recoverable_effects`（`STABLE`、零 DML、固定 `search_path`、固定 7 列）；
- 恢复命令恰有一个 `SECURITY INVOKER` `command_recover`（无表权，恰好一次 `v24.advance(`，不直接 `INSERT/UPDATE/DELETE`）；
- 一次 sweep 只有一条 `command_recover` effect、一条 request/receipt、一个 delta；动作 ≤16，`successors=[]`，无 `settle`；
- 没有 recovery 表、队列、lease、cursor；没有第二个 claim 路径；没有第二个状态机；
- `replay_safe` 只回 `ready` 并清 `claim_owner/lease_until`，保留 `attempt_no/fence`，由下一次普通 claim 递增；
- `no_replay` 只结算 `unknown` 并按既有 unknown wall 收敛 run/pin/预算/interaction/install；
- `manual` 只计数（`manual_debt`），不写、不占 16 上界、不使 `has_more` 恒真。

## 2. 文件

| 文件 | 作用 |
|---|---|
| `test_g5.py` | 父进程/监督者：seed、spawn、`SIGKILL`、调用 worker、断言与 cleanup；K1–K10 各一个函数，另含发现面 D1–D6、`command_recover` 合同套件与输出。 |
| `crash_worker.py` | **子进程**：从环境变量 `V24_WINDOW` 取窗口并推进到具名边界，写 `READY` JSON 后阻塞在 go 管道；K4 的 SQL 错误注入子进程也在这里。 |
| `recover_worker.py` | **新 OS 进程**：新连接执行 `resolve` → `command_recover` → host reservation 重投/结算；打印一行 JSON 结果。parent 从不亲自恢复。 |
| `fake_crash_host.py` | fixture host：`prepare()`/`release()`/`inspect()` 以 reservation 复用首次结果；JSONL + `v24_fake.journal` 双写；无网络/套接字。 |
| `g5_support.py` | 小工具：`new_scope()`、`seed_claim()`、`g5_snapshot()`、`fingerprint()`、`jsonl_path()`、`read_jsonl()`、`wait_ready()` 等；不复制 S1–S5 的测试逻辑。 |

不新增 `v24/s6/setup_db.py`：gate 复用 `v24/s1/setup_db.py` 的 `server_helper_scope()`/`setup_db()`。

## 3. 窗口表 K1–K10

> K1–K10 与设计 §8 L410–419 十行一一对应，不增不减、不合并、不改名。K4 是唯一的非 `SIGKILL` 窗口；其余九个窗口都由父进程在子进程到达具名边界后 `SIGKILL`。

| 窗口 | 边界 | 崩溃/注入方式 | 重启动作 | 关键断言 | 证据 tag |
|---|---|---|---|---|---|
| **K1** | command 请求已发出、advance COMMIT 前（L410） | child 在 COMMIT 前写 `READY` 并阻塞；父 `SIGKILL` | 新 worker 用同 `effect_id`/`request_key`/canonical bytes 重交原 command | `requests/effects 0→1`；child/worker/parent backend 互异；十表快照 `74fe0f99f1679f657f60f7dc2426010c0447fbe50811015d4792ef01bcb74e39→c31b8048363991c38c440dfea22736807876477ae64e4af5dcc1497af22b372a` | `[G5-K1]` |
| **K2** | claim COMMIT 后、IO 前（L411） | child 提交 `host_prepare`（replay_safe）与 `model_call`（no_replay）两个 claimed，`READY` 后父 `SIGKILL` | `resolve` + `command_recover`：`host_prepare→ready`（保留 attempt/fence）、`model_call→unknown`；随后普通 claim 得 `attempt/fence=2/2`，FakeHost 以同一 reservation 完成 prepare | `applied=['reset_ready','settle_unknown']`；`journal_rows=1`；`effects 6→7`；`has_more=False`；run `blocked_unknown`；快照 `b71eda7105f9b49c756d470362bffd56c09ccd4397e4e40ebac7f21866d57f0b→7a62c31f78044a3ec9aac13b8f4b460748bd10bc9839f581c1c199122c3c7e60` | `[G5-K2]` |
| **K3** | IO 完成、advance 前（L412） | child 对 `host_prepare` 写 JSONL+DB journal，`model_call` 不写 receipt，`READY` 后父 `SIGKILL` | `resolve` + `command_recover`：`host_prepare` 回 ready → 普通 claim → 同 reservation 返回首次 receipt → settle `installed`；`model_call` 转 unknown；迟到 success → `receipt_conflict` W0；cancel-late 只结 unknown、保留 seal；manual 只计数 | `reservation=1 reuse=no-second-io`；`late=receipt_conflict-w0`；`cancel_late=seal-preserved+late-only`；`manual=16/0`；`effects 40→43`；快照 `8224cc50310b8dc2e134f9abb1bbef5cb97e28db09dc2e9734416a8f3d6290e2→98012e97e3e81c4f59cc28f2721e76bc5f653580e2803ba53bc0898747131d75` | `[G5-K3]`、`[G5-control]` |
| **K4** | advance 中途错误（L413） | **非 `SIGKILL`**：`v24_fake.raise_k4()` + `k4_inject BEFORE INSERT ON v24.requests` 注入 `P0001`；child 捕获、`ROLLBACK`、报 `READY` 并 exit 0 | 父删 trigger/function；新 worker 重交原 outcome；唯一约束挡重复 | `sqlstate=P0001`；`tx=rollback->idle`；`requests/effects 0→1`；回滚前后 snapshot 相等 `5d3ef214ff41ea01bd23dbc5fd8e9f335a41222454d9db44399bfa7227d95c16`；重交后 `04e3ccbf37a25cdd072b4d99c1b93a30a3bbf28f80d6da3b347621206cd95e00`；`k4_objects_after=0/0`；`sql_digest=827e1c61515b9e6d5f4f7104d914bd4d53be483d171dc4c548bd8620d15900fd`、`sql_unchanged=true` | `[G5-K4]` |
| **K5** | advance 已 COMMIT、应答丢失（L414） | child 提交 `command_recover`，只发 `COMMITTED`、不序列化 response；父 `SIGKILL` | 两个新 worker 用同 key+bytes replay；第二次 replay 必须零写 | canonical sha `24ee41a8a7689533dc541087667ce76631460048c260eaed04e8ffc519aee18c`；三次 response sha `17d16f00fd32997b76938d630ba78fc55251f91e0a2f46be245262ca39de35b6`/523B、`byte_equal=true`；`requests=1 effects=1 sweep_events=1`；post-kill/replay1/replay2 snapshot 相等 `d517cba67b3ebb5658d964d5fb33c446581e7bb3006f5cf41eb084ce90818b33`；`second_replay_zero_write=true`；`budget=inapplicable(no-run)` | `[G5-K5]` |
| **K6** | provider withdrawn、fiber 未清理（L415） | child 提交 withdraw/retire 起点与 run terminal，未完成 slot/pin，`READY` 后父 `SIGKILL` | `resolve` → `command_recover` + 新 key `fiber_control(off)`；pin 只在 settle/quiesce 后释放 | `resolve_live=False`；`pin_live_at_crash=True`、`pin_released_after=True`；run terminal 保留；`episode retiring→closed`；`slot →released`；快照 `7de709bf079d922938530b935487ef34edaa7f14fdb84d69bbe8afffe2394799→0fa19169b41e48745d726e14c153a11acc7a5684ddb9779ac0cb53bbca2fa472` | `[G5-K6]` |
| **K7** | 子 fiber 已清理、父未清理（L416） | child 提交 child `disposed`+slot release+episode closed，父 episode 仍 retiring，`READY` 后父 `SIGKILL` | `resolve` + 未结算 effect/新 key 控制；父 episode `retiring→closed`，父 slot release | 子 `disposed_at` 不变；父 slot release 晚于 child disposed；`owner_pair=True/True`；`scope_closed_at=None`；快照 `9f43937bbd52850ce2e01dda44977850df399da05eb65966c86fd47211b5367e→82da991aee0d12464f653536463cf093007fb2d5e85b2d309c6b6406823c8ce5` | `[G5-K7]` |
| **K8** | host_prepare IO/receipt 窗口（L417） | child 置 install `preparing`、`host_prepare` claimed、FakeHost prepare 已写 journal，receipt 未提交，`READY` 后父 `SIGKILL` | 先断言 `fiber_control(on)` 被拒 `install_not_ready` W0；`command_recover` 回 ready；普通 claim + 同 reservation prepare；settle success → `installed`；再 `on` 才允许 | `refused=install_not_ready-w0`；`preparing→installed`；`reservation=1`；`journal_attempt/fence=1/1`；activation `028a1e33-15d6-4d4c-9232-226f60ae2d75`；快照 `714b6c83f6027aa22a1e7805ed213c949e0a93521de60404fb8675a2ed13f991→777c17b019ae475409695c4abb91a7acd29c5c9baeddd4a396b4c2fdd4a195eb` | `[G5-K8]` |
| **K9** | scope close/prepare_unknown（L418） | child 写 `close_requested_at`、install `prepare_unknown`、host effect unknown（`resource_quiesced_at IS NULL`），不 inspect，`READY` 后父 `SIGKILL` | `resolve` + `command_recover`（无候选则 noop）+ close 阶段；inspect `absent` 后 dispose；再 close | inspect 前 `closed_at=None`、`scope_closable=False`；`inspect_observed=absent`；`install=disposed`；`closed_at_after_steps=True`；`scope_closed=1`；`close_steps=6`；快照 `32f6a018b61b6997dc99338b6d493ee5e23644140657808d72810ec5bf634496→2e091616dd4a3e117c90243b86b1a7cdbfb4d3e4a14fbb4941a2f758f25746ec` | `[G5-K9]` |
| **K10** | host CAS release 后、DB receipt 前（L419） | child 置 install `dispose_pending`、`host_release` claimed、fake release 已写 journal，`READY` 后父 `SIGKILL`；第二个变体为 release 结果丢失 | `command_recover` 回 ready → 普通 claim → 同 reservation release 返回首次结果 → `disposed`；丢失时对同 reservation inspect，绝不发第二条 release | `release_rows_a=1`；`release_b=lost→inspect`；`target_reservation=v24:host_release:3882a543-5e00-30f5-351b-1dfbd694ec55`；`release_rows_b=1 inspect_rows_b=1`；`disposed=disposed`；快照 a `e6005dfd237b11a1565a2fb78ad47d93291405fa4d017232c19352708bcaf775→9a574b4b86c36e8c1ed6640ecf54203f9d28ce45570e702913dad4e355df6051`、b `8f91c601fc2988e9d389312595828f56914786f03345a227464f5accd3fd9c20→d66aeb853853dab916c4d8baf96cbe8f1bc115921bf981fca5bb6e3488702e9a` | `[G5-K10]` |

## 4. 运行命令与数据库生命周期

```bash
# 父门口径：无参数全量 K1–K10
uv run python v24/s6/test_g5.py

# 增量检查点：只跑指定窗口（历史 W1–W3 用过；不是第十条 gate）
uv run python v24/s6/test_g5.py --only K1,K4,K5
```

- **数据库**：`main()` 内 `with server_helper_scope(), setup_db() as db:`；`setup_db()` 每次建唯一临时库并按 loader 顺序加载全部 SQL，退出时 `DROP DATABASE ... WITH (FORCE)`。没有独立的 S6 setup 脚本，也不需要手工建库。
- **网络**：`main()` 先调用 `_assert_no_network_imports()`，扫描 `v24/s6/*.py` 的 `socket`/`http`/`urllib`/`requests` 等 import 与 `time.sleep`；断言失败即 gate 失败。
- **期望末行**：退出码 0，最后一行 stdout 恰为 `[passed] v24 S6 W1-W4`。
- **运行时**：本机一次约数秒到数十秒，未单独基准化；首次 pgembed 启动不计入该估计。

## 5. 证据格式

每个 K 在成功时打印一行 `[G5-Kn] key=value …`：

- 通用字段：`child_pid`、`child_backend_pid`、`worker_pid`、`worker_backend_pid`、`parent_backend_pid`、`journal`、`snapshot`（或 `snapshot_before/after`）、`requests`/`effects`、`applied`、`has_more`；
- K3 另打印 `[G5-control]` 控制对照（run 归一化投影、pin 释放、事件、cancel-late 出处、manual 计数）；
- K4 另含 `request_key`、`effect_id`、`sqlstate=P0001`、`tx=rollback->idle`、`trigger=k4_inject`、`trigger_created`/`trigger_dropped`（DB `clock_timestamp()`）、`k4_objects_after=0/0`、`sql_digest`、`sql_unchanged=true`；
- K5 另含 `canonical_b64`/`canonical_sha256`、`first_commit_sha256/bytes`、`replay1_sha256/bytes`、`replay2_sha256/bytes`、`byte_equal`、`requests/effects/sweep_events`、`sweep_action`、`successors`、`budget=inapplicable(no-run)`、`second_replay_zero_write`；
- 发现面与合同：`[G5-D1]`…`[G5-D6]`、`[G5-W2]`。

失败时每个 K 的 `except` 会把临时目录保留在 `/var/folders/.../T/v24-s6-g5-*`，向 stderr 打印 `[G5-Kn] retained journal=<path>`；子进程/worker 的 stderr 会进入断言消息。成功时临时目录删除。

## 6. FakeHost 与持久 journal

- **reservation 幂等**：`CrashHost.prepare()/release()/inspect()` 先按 `(payload->>'reservation', op)` 查 `v24_fake.journal`；命中即返回首次结果，**不再插入第二行、不再执行第二次外部动作**。
- **JSONL**：`append_jsonl()` 用 `os.open(path, O_APPEND|O_CREAT|O_WRONLY)` + `os.write` + `os.fsync` 追加一行 JSON；路径由父进程 `tempfile.mkdtemp(prefix='v24-s6-g5-')` 生成后经环境变量交给 child/worker，不经 argv。
- **DB 镜像**：同一动作写 `v24_fake.journal`（fixture schema，随临时库 DROP）；文件是 receipt 的持久证据，DB 行用于 SQL join。
- **无网络**：`fake_crash_host.py` 不 import `socket`/`http`/`urllib`/`requests`，不开套接字；K 间用 READY/go 管道与 `waitpid` 排序，不用 `sleep`。
- **seeded expiry**：K2/K3 的 lease 过期由 owner 连接执行 `UPDATE v24.effects SET lease_until = now() - interval '1 second'`，只改 `lease_until`，不改 status/claim；这是 fixture，不是公共恢复路径。
- **K4 trigger**：`v24_fake.raise_k4()` 与 `k4_inject` 只存在于测试期，`try/finally` 删除；gate 断言删除后 trigger/function 计数 `0/0`。

## 7. 边界与已知债务

- **`has_more` 是提示，不是游标**：解释器只处理 wrapper 传入的 `candidates`；hint 之外新过期的行本次不处理，只让 `has_more=true`，留给下一个 key。没有 cursor/queue/job/表（A-S6-7）。
- **没有真实 provider/transport**：FakeHost + JSONL 只证明恢复合同（reservation 复用、receipt、journal），不证明真实 adapter 的幂等；生产 adapter 必须自己按 reservation 复用，否则 `replay_safe` 可能产生第二次外部动作（设计 §10.2 D1/D2、R6）。
- **K2/K3 的 lease 过期是 seeded fixture**：不是真实时间流逝；产品路径仍只读 `lease_until <= now()`。
- **K5 是 host-only**：不创建 run 行，`runs` 不变，预算断言明确为 `inapplicable(no-run)`，不是“预算零写”的实测。
- **K4 trigger 是 test-only**：不进入产品 SQL；`v24/sql/**` 在 K4 前后 digest 相等（`827e1c…`）。
- **S6 不覆盖 S7 并发**：K1–K10 是单写者顺序窗口，不是三面并发矩阵；G6 仍归 S7。
- **S6 不覆盖 S8 spawn/child run**：G7 仍归 S8，S6 无 spawn 解释器。
- **运行时未基准化**：不声称固定秒数或性能指标。

## 8. 链接

- [S6 计划（合同、W1–W4、D-S6/CC）](../../docs/plans/v24-s6-crash-recovery-2026-10-24.md)
- [G5 测试](test_g5.py)
- [覆盖矩阵](../../docs/reviews/v24-conformance-matrix-2026-10-23.md)（G5 行与 §0.2 证据表）
- [偏差台账](../../docs/reviews/v24-deviation-ledger-2026-10-23.md)（§1.9–§1.11）
