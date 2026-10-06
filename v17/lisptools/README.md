# v17 G4 · lisptools —— world daemon（lisp_eval / lisp_develop / `lisp:` 工具）

Gate: `uv run python v17/lisptools/test_lisptools.py`（退出码 0 = 通过）

## 一句话

**world daemon 是第二种 SBCL worker：它拥有 Python worker 表达不了的那类
effect——在持久 SBCL world 里 develop/execute，而 world 的耐久性是
Postgres。** 它**按表扫描**发现工作，不新增 pgmq 队列、不新增消息
kind、不新增表、不改 v12 一行（计划的硬约束，字面满足）：

```sql
status = 'queued'
 OR (status = 'claimed' AND (lease_until IS NULL OR lease_until < clock_timestamp()))
AND (kind IN ('lisp_eval','lisp_develop') OR tools.handler LIKE 'lisp:%')
```

扫描即恢复路径（与 `v12_requeue_stale` 同思路，且与 `v12_claim_job` 的
认领条件逐字一致）；消息仍是纯唤醒，队列 worker 对 lisp job 的唤醒只
归档不认领，所以混部天然无竞争。

## 崩溃安全（计划 §3.2/§4 的落地）

1. **每个 job 都从 CURRENT revision 起**：新建空 world adapter → 导入
   当前 revision → 才开会话。进程内不携带任何 Lisp 状态跨 job（每 job
   一个新包 `V17-WORLD-<name>-<n>`，包名只需进程内唯一——revision 里的
   defun 打印不带包前缀）。
2. **publish 钩子是崩溃临界组合点**：它跑在会话 worker 线程、自己开连接，
   在一个显式事务里提交：goal 验收 → `publish-world-revision`（INSERT
   + CURRENT CAS）→ 缓冲的 journal → `v12_complete_job`（fence）。
   COMMIT 之前任何位置崩溃 = job 未结算且 world 未前进——jiti 的
   uncertain 窗口由 Postgres 的 COMMIT 关闭，而非 fsync 顺序。
3. **任何非接受结果都恢复 checkpoint 并在自己的事务里结算 failed**
   （journal 记录一起提交；没有状态前进，单个 complete_job 就安全）。
   显式 preview 是例外：它报值后恢复，所以按 succeeded 结算且不发布。

## 验收合同

| 检查 | 门 | 实现 |
|---|---|---|
| invariant | 内核 attempt 内（jiti 同款，违反即恢复 checkpoint） | `%checks` 编译成谓词 |
| goal | **publish 钩子** | jiti 只把 goal 报给交互会话、只门控自己的 loop 退出；job 的调用方点名要了能力，发布了没有它的 world 就是把失败的 effect 当成成功的交付。钩子拒服即 abort → 恢复 → job failed |

未过 goal 的原因串经 `attempt-cell` 的 `failure` 槽从 worker 线程带回
（内核的失败报告会重置 outcome、不带 condition，否则只能说出
"publication-failed"）。

## 合同形状

- `lisp_eval` payload：`{"world":..., "source": "...", "goals":[...], "invariants":[...], "preview":true}`
- `lisp_develop` payload：同上（source 是单个 defun）
- `lisp:` 工具：`tools.handler = 'lisp:<world>:<fn>'`，driver 原样把
  `jobs.kind = <工具名>`、payload `{"params": {...}}` 投来；daemon 组装
  `(<fn> '((:PARAM . "v")))`——**params alist 必须加 quote**，否则
  `((:WHO . "x"))` 里的关键字会被当函数调用（SBCL 只报难解的
  `illegal function call`，这是调试时踩到的真坑）。
- goal/invariant 是与被提交代码同级的可执行检查：走同一道
  parse-one-form + validate-form 政策闸，编译成在世界包里的闭包。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `V17_WORLDD_ID` | `v17-wd-1` | claimed_by 身份 |
| `V17_WORLDD_IDLE_EXIT_MS` | 5000 | 无 owned job 持续多久后退出 |
| `V17_WORLDD_POLL_MS` | 150 | 扫描间隔 |
| `V17_WORLDD_LIMIT` | 8 | 每轮最多处理的 job 数 |
| `V17_WORLDD_LEASE_SECONDS` | 300 | 认领租约 |
| `V17_WORLDD_DEBUG` | 关 | stderr 打印每个 job 与结果 |
| `V17_WORLDD_ALLOW_SUICIDE` | 关 | **仅 gate**：允许 payload 触发「外部副作用后自杀」的 unknown-wall 场景 |

## 八场景

1. `lisp_eval` 端到端：job settled、world 恰好一个 revision、值回报、
   journal 有 operation 记录；
2. `lisp_develop` 耐久性：revision 2 带 definition，**新进程能调用它**
   （Postgres 即恢复面）；
3. preview：值观测到、状态不回写、**一个 revision 都不发布**；
4. goal 未过：job failed、reason 指名 goal、rejected definition 不在
   world 里；
5. invariant 违反：恢复、无 revision、毒键没落地；
6. **崩溃于 claim 之后**（source 带 sleep，kill 落在 attempt 里）：
   租约过期 → 第二 daemon reclaim → 恰好两个 revision（baseline + 一次
   effect）、状态是 5 不是 10；
7. **unknown 墙**：payload `suicide_after_effect` → daemon 先落
   `gate_side_effects` 行再 `sb-ext:quit` → job 停在 claimed →
   经 v12 自己的 API 记录 unknown → `v12_enqueue_effect` 拒绝盲目重投 →
   只有 `v12_resolve_unknown` 能动它 → 副作用仍只有一次；
8. `lisp:` 工具：params alist 直达 Lisp 函数，unicode 无损
   （`{"who": "团队"}` → `hi 团队`）。

## 开发中踩到并固化的坑（都进了代码注释）

- `postmodern:query ... :single` 零行返回 Lisp `NIL`，`:null` 只用于
  行内 SQL NULL：`(eq x :null)` 守卫会放行不存在的行 → `%present-p`。
- yason 的 `*list-encoder*` 在第三层嵌套必坏（`{"(text . 5)":null}`）：
  编码器自己写，落在 pgstore（`ENCODE-JSON`/`JSON-TEXT`）；
  `ENCODE-JSON` 写流而返回原值——用错返回值会把原始 Lisp alist 发给
  cl-postgres（真实发生过）。
- journal 事件是符号键 plist：yason 拒绝符号键；转到自写编码器后还要
  区分「plist 列表」与「pair 列表」（打印值记录曾是重灾区）。
- 提交的 goal 必须在 publish 钩子执行：jiti 的基线 invariant 检查会把
  还没开发出的能力判成 baseline 不合规（"session is closed" 的怪象）。
- 临时 state 文件不能用 `(random ...)` 命名（SBCL 默认种子每次相同 → 上次
  的调用计数残留）；改用 pid + 计数器（queue-suite 因此修过一次）。
