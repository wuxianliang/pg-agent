# 第 8 章：多语言 harness——SQL-only 合同

> 前置：第 2、3、6 章。早期多语言 worker 设计意图；现状仅验收 inline fake adapter，未交付生产多语言 DB 接线。
> 对照上游：`v12/queue`（G6：inline/queue 双模 effect_id 逐字节一致）。

## 8.1 这一章要做什么

目标场景：Python 提供分析工具、Swift 提供系统工具、DuckDB 工作台提供数据/代码工具、
pi 式极简文件工具——**同一个 agent 用 Jev 从统一目录选择，中间产物互通**。

v13 的立场：**多语言不是机制，是推论。** 工具目录是数据（第 6 章）、
effect 总线是语言无关的 SQL 合同（第 2 章）、worker 可围绕 claim/IO/complete 协议设计——
那么语言差异必然被压进 worker 进程内部。**任何语言之间永不直接通信，只通过行交换。
PG 本身就是 harness。**

## 8.2 worker 契约：三个函数，任何语言

```text
一个合法 worker = 能连 libpq + 实现以下三步的进程：

1. v13_claim(worker_id, lease_ms DEFAULT 60000)    → global 领单（route，事务）
   v13_claim_fair(worker_id, lease_ms DEFAULT 60000) → fair 领单（owner，事务）
   CE 的七键 claim 是独立并行面，不接 registry pin
2. 进程内执行全部 IO（网络/文件/工作台）              → 无事务
3. v13_complete(actor, effect_id, attempt, fence, status, → strict 结算（另事务）
                result, context_revision)
   旧五/六参 overload 仍可用，但不做 require_pin=true 的 strict 核对。
   global 精确六键；fair 加 root_session_id 为七键。额外 pin/context/cache/fences
   复核仅由 test_consumer.py 的 inline fake adapter 验收，不是现有生产 driver。

控制订阅是概念性后续合同，不是当前 claim 参数或已接入的生产 worker：
- 当前 `tools` 表只有 `name/description/kind/handler/param_spec/enabled` 六列；没有
  `allowlist` 或 `interruptible` 列。
- `v13_interruptible()` 仍是函数内硬编码名单；`tool_profile` 目前只有注册数据，
  没有消费者。要改变中断或 worktree 名单，需要另行改 SQL/消费者。
- 本章的 fake adapter 可演示协议，不证明现有 Python/Swift/框架 worker 已接入该合同。

附带纪律：
- 请求已冻结：worker 原样发送 request，凭据在进程侧注入，无权改
- 申报不裁决：known/unknown 的分类规则在 v13_complete 的 SQL 里
- 错误信封跨语言统一：{Type, Problem, Solution}（v1 的信封，十二轮未变）
```

Swift 用 PostgresNIO/libpq，Python 用 psycopg，Node 用 pg——各写各的，
互不需要知道对方存在。**一致性锚点是 effect_id 由 SQL 生成（uuid v5）**：
同一逻辑动作由任一 worker 领取时取得同一个 SQL 生成的幂等身份；本章不声称
worker 会自行跨语言推导 ID，也不声称当前生产环境已有多语言 parity。

## 8.3 逐段解释

- **单队列 + 现行 claim 合同**：本阶段 global/fair claim 的真实 SQL 接口没有
  `handlers[]` 参数；worker 通过 route/global 或 fair owner 身份领取。CE claim
  保持独立七键面，不接 registry pin。概念性的按 handler 过滤仍是早期设计意图，
  不是当前生产 worker 接线。
- **lease 是行上的时钟**：Swift（actor 模型）和 Python（协程）心跳节奏不同无所谓——
  lease_until 是 `clock_timestamp()` 算出来的行数据，谁先过期谁被接管，语言无感。
- **崩溃窗口语言无关**：Swift worker 在「外部成功、结算前」崩溃，
  和 Python worker 崩溃是同一个 SQL 现象（claimed + lease 过期），
  走同一条恢复路径（第 11 章）。**恢复逻辑只写一遍，写在 SQL 里。**
- **控制中断仍是边界说明，不是已交付生产接线**：轮询 events、子进程中断和
  `v13_complete` 结算可以作为未来 adapter 的设计；当前 gate 只覆盖 inline fake
  adapter，不能把该模型写成现有 worker 的行为保证。
- **worktree 是既有独立机制**：当前 `v13_requires_worktree()` 名单和 artifact/latch
  路径决定 binding 要求，不读取不存在的目录 mutating/allowlist 列，也不由 registry
  profile 驱动。新增工具若改变该名单必须独立改 SQL；不能据此声称任意目录行自动获得保护。
- **pi 式极简工具仍受现行六列目录约束**：read/write/edit/bash/glob 的 handler、
  kind、param_spec 和 enabled 可由目录行描述；profile/allowlist 等早期概念不是当前
  schema。写操作的既有 artifact/unknown 规则不因此获得新的注册通道。
- **新增工具的边界**：当前目录新增行只改变已实现 handler/catalog 行为。
  若要改变 interruptible 或 worktree 名单，需要独立 SQL/消费者变更；本章的 fake
  worker 练习不证明生产 Swift/Python worker 已接入数据库。

## 8.4 历史验收意图

以下 G6 列表是早期设计目标，不是当前 gate 覆盖或生产 DB worker 的交付声明。
尤其按 handler 分流、跨语言接管和中断均不能由本章的概念模型推出。
当前实际证明范围见 registry README 与独立 consumer gate。

```text
历史 G6 节选断言（非现状保证）：
✓ 双 handler（py fake + swift fake）同队列：各领各的，无一错领
✓ 跨语言 effect_id 一致：同一逻辑键两种语言推导同 uuid
✓ 杀 py worker 后 swift worker 接管其未决 effect（lease 过期）
✓ 错误信封：两种语言的失败结果落账后事件形状完全一致
✓ op_seq 并行纪律：只读 effect 并行执行（op_seq NULL）；
  同 mutation_scope 的变更严格按最小未完成序
✓ 未来 adapter 可按 cancel 事件实现中断与结算；本章不宣称生产 worker 已接线
✓ mutating 中断后副作用不明 → settle unknown；用 cancelled 掩埋 unknown → 红
✓ 中断 turn 的 partial artifact 只进审计断言集，不过 completion gate
✓ 目录声明工作面的 mutating effect 无 worktree binding → harness 拒 claim（零执行）
```

## 8.5 检查点练习

前两项是未来 adapter 的设计练习，不是现有双语言 DB gate，也不应以迟到结算
stale 推出外部副作用 exactly-once。第三项须保持当前 schema 与独立名单边界。

1. 写第二个 fake worker（模拟 Swift：不同的 sleep 节奏、不同的崩溃概率），
   与 py fake 同跑 G6。断言：所有不变量对两语言同时成立。
2. 故意让 swift fake 慢结算（hold lease 到过期边缘），py fake 接管完成后
   swift fake 的迟到结算返回 stale——断言外部副作用计数 == 1。
3. 用 `tools.handler` 加第三种 handler（如 'node'），在现行六列 schema 下验证目录
   行和已有 catalog 行为。若要改变中断/worktree名单，记录所需的独立 SQL/消费者变更；
   不能把练习写成“只 INSERT 且零 SQL 文件”。

## 8.6 回到 vN 对照

- `v12/queue/test_queue.py` 的双模一致性断言（SQL `v12_uuid_v5` == Python `uuid5`）
  是本章跨语言主张的已验证前例。
- v4 的 queue_kinds（embed/sql_heavy/human_inbox 三种队列）：裁决「kind 是一列数据，
  不是拓扑」。当前 v13 claim 不接收 `handlers[]`；分流依赖现行 handler/catalog
  行为和调用身份，不能把早期 handlers 过滤描述成已装载接口。

## 8.7 内在合理性：前因后果

**作用力。** 先列事实——它们关于运行环境，不关于任何设计偏好：
**语言之间没有共同的内存表示**——Python 对象、JS 对象、Rust 结构体
互不可见，一个进程引用不了另一个进程堆上的数据，进程一退出，其内部
状态随之消失；各语言唯一确定共有的能力，是连 libpq、读写行。
**共享队列里消息可见即可被任何 worker 消费**——行不知道自己该归谁，
「语言亲和」在队列的层面并不存在。**外部 IO 与结算之间没有原子性**：
副作用可能已在外面发生而本地尚未落账，且进程可能在任何指令边界
崩溃。**心跳节奏是语言的属性**——actor 模型与协程的定时精度不同，
但「租约没续上」必须是同一个客观事实，否则接管无从谈起。

**推导。** 这些力逼出本章的合同。内存互不可见 ⇒ 一致性锚点必须语言
无关：effect_id 由 SQL 生成 uuid v5，任何语言的 worker 从领取结果取得
同一个幂等 id，不自行推导——身份不依赖任何一方的运行时，语言之间
永不直接通信，只通过行交换。当前 claim 只接 worker/lease，不接 `handlers[]`；
按 handler 过滤只是早期设计意图，不能从共享队列推导出已有生产分流。心跳因语言
而异 ⇒ lease_until 是 `clock_timestamp()` 算出来的行数据，不是任何
进程的内部状态：谁先过期谁被接管，续租与回收走同一套超时逻辑，谁也
不必知道别人的节奏。崩溃窗口语言无关 ⇒ 恢复逻辑只写一遍、写在
SQL 里（claimed 且 lease 过期即同一条恢复路径）；worker 只申报事实、
不做分类——known/unknown 的规则住在结算那一步的 SQL 里，错误信封
{Type, Problem, Solution} 跨语言同形。

**反事实。** 假如恢复与分类由每种语言各写一套，失败时序：第 1 步，
Swift worker 在外部 IO 成功、结算落账前崩溃——claimed 且 lease 过期，
三种语言看到的是同一个 SQL 现象；第 2 步，py 版恢复代码把这单标成
known（外部可能已生效），swift 版直接当成功结案，node 版判为失败并
重放——外部副作用被再执行一次，计数翻倍；第 3 步，事后对账 SELECT
台账，同一种崩溃在不同语言的 worker 名下呈现三种口径，谁也回答不了
「这单到底成了没有」；第 4 步，修一个分类边角要在每种语言里各改
一遍、各发一版，窗口期内口径继续分叉——而规则住在 SQL 里时只需
一处 UPDATE，所有语言同时继承。

**被拒替代。** 其一，**每语言一条队列**：语言从 WHERE 里的一列数据
升格成拓扑——N 份队列、N 套监控，跨语言的同一逻辑动作要跨队列对账，
逐字节一致的 effect_id 反而失去用武之地。其二，**共享 SDK 库**：把
领单、续租、恢复收进一个库，语言准入从此被库的运行时锁定，新语言要
等库移植；且库仍是各自进程内的代码，分类行为照样随版本漂移。其三，
**中心调度服务**：让一个常驻进程统一派单与恢复——语言无关性从
SQL 里的一处，变成一个自身要处理崩溃、要被监控的独立系统，恰好
重建了它本来要解决的问题，还多出一个会崩溃的部件。
