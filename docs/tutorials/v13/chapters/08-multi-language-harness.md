# 第 8 章：多语言 harness——SQL-only 合同

> 前置：第 2、3、6 章。产出：worker 契约文档 + `v13/fakes.py` 的双语言验证（G6 验收）。
> 对照上游：`v12/queue`（G6：inline/queue 双模 effect_id 逐字节一致）。

## 8.1 这一章要做什么

目标场景：Python 提供分析工具、Swift 提供系统工具、DuckDB 工作台提供数据/代码工具、
pi 式极简文件工具——**同一个 agent 用 Jev 从统一目录选择，中间产物互通**。

v13 的立场：**多语言不是机制，是推论。** 工具目录是数据（第 6 章）、
effect 总线是语言无关的 SQL 合同（第 2 章）、worker 契约只有三个函数——
那么语言差异必然被压进 worker 进程内部。**任何语言之间永不直接通信，只通过行交换。
PG 本身就是 harness。**

## 8.2 worker 契约：三个函数，任何语言

```text
一个合法 worker = 能连 libpq + 实现以下三步的进程：

1. v13_claim(worker_id, handlers[], lease_ms)        → 领单（事务）
2. 进程内执行全部 IO（网络/文件/工作台）              → 无事务
3. v13_complete(effect_id, attempt, fence, status,   → 结算（事务）
                result)

附带纪律：
- 请求已冻结：worker 原样发送 request，凭据在进程侧注入，无权改
- 申报不裁决：known/unknown 的分类规则在 v13_complete 的 SQL 里
- 错误信封跨语言统一：{Type, Problem, Solution}（v1 的信封，十二轮未变）
```

Swift 用 PostgresNIO/libpq，Python 用 psycopg，Node 用 pg——各写各的，
互不需要知道对方存在。**一致性锚点是 effect_id 由 SQL 生成（uuid v5）**：
同一逻辑动作不管哪个语言的 worker 领取，幂等身份逐字节相同
（v12 G6 已在 inline/queue 两模式间验证过同一性质，跨语言是同一证明的复制）。

## 8.3 逐段解释

- **单队列 + handlers[] 过滤**：所有语言共享 `v13_work` 一条队列，
  claim 按目录的 handler 列过滤（第 2 章 SQL 里的子查询）。不建第二队列——
  「第二队列」在裁决清单上和第二租户/第二运行时同列。
- **lease 是行上的时钟**：Swift（actor 模型）和 Python（协程）心跳节奏不同无所谓——
  lease_until 是 `clock_timestamp()` 算出来的行数据，谁先过期谁被接管，语言无感。
- **崩溃窗口语言无关**：Swift worker 在「外部成功、结算前」崩溃，
  和 Python worker 崩溃是同一个 SQL 现象（claimed + lease 过期），
  走同一条恢复路径（第 11 章）。**恢复逻辑只写一遍，写在 SQL 里。**
- **pi 式极简工具就是一包目录行**：read/write/edit/bash/glob 注册在某个 handler 下，
  allowlist 根目录是目录行的数据（第 6 章）；写操作产物注册为 artifact（第 7 章）；
  bash 标 mutating=true——享受全套 unknown 纪律。**没有为「外部著名工具集」
  开任何特殊通道。**
- **新增一个 Swift 工具的全部动作**：INSERT tools 一行 + 启动 swift-worker 进程。
  决策平面、effect 总线、其他 worker 零改动——第 6 章承诺在这里兑现。

## 8.4 硬性规定与 gate

```text
G6 节选断言：
✓ 双 handler（py fake + swift fake）同队列：各领各的，无一错领
✓ 跨语言 effect_id 一致：同一逻辑键两种语言推导同 uuid
✓ 杀 py worker 后 swift worker 接管其未决 effect（lease 过期）
✓ 错误信封：两种语言的失败结果落账后事件形状完全一致
✓ op_seq 并行纪律：只读 effect 并行执行（op_seq NULL）；
  同 mutation_scope 的变更严格按最小未完成序
```

## 8.5 检查点练习

1. 写第二个 fake worker（模拟 Swift：不同的 sleep 节奏、不同的崩溃概率），
   与 py fake 同跑 G6。断言：所有不变量对两语言同时成立。
2. 故意让 swift fake 慢结算（hold lease 到过期边缘），py fake 接管完成后
   swift fake 的迟到结算返回 stale——断言外部副作用计数 == 1。
3. 用 `tools.handler` 加第三种 handler（如 'node'），只 INSERT 目录行 + 起进程，
   跑通一个 turn。记录：这个练习改了几个 SQL 文件？（应为零。）

## 8.6 回到 vN 对照

- `v12/queue/test_queue.py` 的双模一致性断言（SQL `v12_uuid_v5` == Python `uuid5`）
  是本章跨语言主张的已验证前例。
- v4 的 queue_kinds（embed/sql_heavy/human_inbox 三种队列）：裁决「kind 是一列数据，
  不是拓扑」——v13 用 handlers[] 过滤兑现：队列永远一条，分流在 claim 的 WHERE 里。

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
无关：effect_id 由 SQL 生成 uuid v5，任何语言的 worker 对同一逻辑动作
都推导出逐字节相同的 id——幂等身份不依赖任何一方的运行时，语言之间
永不直接通信，只通过行交换。消息人人可领 ⇒ claim 必须按目录声明的
handler 过滤（handlers[] 对照 tools.handler 数据列的子查询），而不是
按语言或进程亲和认领——分流住在 WHERE 里，队列永远一条。心跳因语言
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
