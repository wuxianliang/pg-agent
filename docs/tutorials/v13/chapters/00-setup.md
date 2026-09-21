# 第 00 章：环境准备

> 目标：把 v13 的运行环境装好，知道 gate 怎么跑、每章产出什么。读完整本教程只需要一个
> PostgreSQL（含 pgmq、pgvector——pgembed 捆绑包已含）、`psql`、Python 3.12 + `uv`。
> 不装消息服务器、不装向量数据库、不装 Node。

## 0.1 前置知识

- SQL：会写 `CREATE TABLE`、事务、`FOR UPDATE`、窗口函数、递归 CTE。
- 理解一个 agent 回合的形状：`user message → 判断 → （工具/生成/人工）→ assistant`。
- 知道 PostgreSQL 的两个基本事实：**行锁只在事务内存在**；**后端进程死则事务回滚**。
  v13 的全部崩溃恢复设计都从这两条推出来。

## 0.2 目录结构

```text
pg-agent/
├── v13/                     ← 本教程逐步构建的版本（规划）
│   ├── schema/core.sql      ← 第 1、2、6、7 章：9 张表 + 触发器（G1 验收）
│   ├── queue/wake.sql       ← 第 3 章：PGMQ 唤醒 + 扫描恢复（G2 部分）
│   ├── decide/decide.sql    ← 第 4 章：决策 + 阈值路由（G2）
│   ├── loop/advance.sql     ← 第 5 章：agent_advance + 预算（G4）
│   ├── effect/claim.sql     ← 第 2、11 章：claim/settle/recover（G3）
│   ├── workbench/           ← 第 9 章：duck bundle manifest
│   ├── worker.py / driver.py← 第 2、3 章：库外进程
│   └── fakes.py             ← FakeJudge/FakeLLM/FakeTool（gate 一律 fake）
├── docs/tutorials/v13/      ← 本手册
└── v1…v12/                  ← 「上游」：十二轮实验，对照用
```

每个 SQL 文件的「第 N 章」归属就是它的手册章节。

## 0.3 跑起来

```bash
# 仓库根目录；gate = 独立可跑脚本，退出码 0 = 通过
uv run python v13/schema/test_schema.py     # G1
uv run python v13/decide/test_decide.py     # G2
uv run python v13/effect/test_effect.py     # G3
# … G1–G7 顺序执行；前一 gate 不过不进下一个
```

每个 stage 的 `setup_db.py` DROP/CREATE 自己的库（`agent_v13_<stage>`），
按 `v13/load.py` 的 `SQL_LOAD_ORDER` 累计加载。同一 stage 的全部 gate 都要跑，
不只是新写的那个——这是仓库级纪律（见 `AGENTS.md`）。

## 0.4 三条学习纪律

1. **先跑 gate，再读 SQL**。测试是「始终成立的性质」清单。
2. **每章完成检查点练习**。小改动 + 断言钉住。
3. **每章末尾「回到 vN 对照」**。只读关键 50 行，体会「思想一样、机器减掉」。

## 0.5 简化立场：与 v8 的差异

v13 是设计收敛，不是 v8 移植。每条差异在对应章节有详细理由：

| v13 | v8（冻结规范） |
|---|---|
| `jsonb` + `sha256` 即幂等键 | canonical profile 字节仪式（JCS/NFC/tagged int/黄金向量） |
| 拒绝落一行 errors 事件，带原文 | 三族拒绝指纹 + occurrence 子表 |
| 只读角色 + 函数入口即边界 | grants/slices/RLS/capability seam 全套 |
| `meta` 版本门（migration + worker digest 不匹配拒绝启动） | 插件世代/registry/readiness/下线七条协议 |
| dispatch 前一行预算复验 | 双实时授权门 + cohort + manifest 快照 |
| 两级锁序（session → effect），一行注释 | 八位锁序 |
| unknown = 一行 resolution + 同事务改状态 | turn-end slots/closers/supersedes 链 |
| 「最近 N 条 + 钉住 summary」一个函数 | compact 三命令协议 |
| ~7 gate / ~180 断言 | 24 gate / ~3000 断言 |
| 单运行时、单租户、可信网络面 | 双运行时 conformance + portable trace |

**升级触发器**（出现任一项，重新引入对应 v8 机制）：
普通用户可直连数据库 → 最小权限角色 + grant；
多 workspace → workspace 域；第三方插件热升级 → 世代域；
合规审计 → audit 指纹族；第二运行时 → canonical 合同。

## 0.6 一个 turn 的鸟瞰

后面每章都在造这个流程的一段：

```text
输入事件（user 消息）
→ agent_advance（第 5 章）：
    context gate（revision 匹配？）
→ decisions（第 4 章）：判断落行，阈值路由
→ tools（第 6 章）：目录选工具 → effects（第 2 章）落账
→ PGMQ 唤醒（第 3 章）→ worker claim（第 8 章任意语言）
→ 事务外执行（IO/duck 工作台/LLM）
→ settle：fence CAS + 结果 artifact（第 7 章）+ 事件
→ 预算扣减 → 继续 or 终态
```

核心信念只有一条，第 1 章开始建立：

> **PG 行是唯一真相。队列只是唤醒，worker 只是手脚，视图只是投影。**

## 0.7 内在合理性：前因后果

这一章没有机制，只有立场——但立场不是口味，是被两条物理事实和一条成本结构逼出来的。

**作用力。** 物理事实一：**后端进程死则事务回滚，且死法对同伴不可观测**——崩溃
可以发生在任何两条指令之间，没有「优雅退出」的保证。物理事实二：**事务边界是
唯一的一致性边界**——两个系统之间不存在共享事务，数据库行与任何库外状态都
无法原子地一起变化；于是每多一个有状态组件，就多一个无法与表对账的状态域。
成本结构：**常驻组件的维护成本每天照付，与它本周是否提供了正确性无关**——
装了消息服务器就要养它的版本、端口、磁盘与备份，而它承载的功能（待办暂存）
在表里一列 status 就能承担。正确性收益只在特定威胁出现时兑现；威胁不出现，
期望收益为零，成本恒为正。

**推导。** 极简依赖集（一个 PG、psql、一个 Python）由此得证：PG 已提供仅有的
两个原子性原语（事务提交、事务内行锁），任何第二状态域都在制造新的故障类别。
gate 即退出码：脚本能可靠消费的信号只有退出码，「前一 gate 不过不进下一个」
的顺序必须由机器执行——人类注意力不可复现，也就不可组合。fail-closed（版本
不匹配拒绝启动）：fail-open 把「要不要继续」推给运行现场的操作员，而那个时刻
上下文最少、压力最大；在启动边界崩溃，把同一决定移到设计期，可被测试钉住。
0.5 差异表每一族裁减都是同构推理：canonical 字节仪式防第二运行时的字节分歧，
grants/RLS 防租户互看，插件世代防热升级共存，审计指纹防海量模式检索，双授权门
防多方并发改预算，八位锁序防任意顺序加锁的死锁环，三命令压缩协议防并发压缩
竞态——每件的威胁条件都列在升级触发器里；**条件不成立的部署形态中，防守是
纯成本**。

**反事实：去掉 fail-closed。** 周五 18:00 部署：schema 已升级，某台 worker 的
digest 仍是旧的；fail-open 下它带着 warning 启动，用旧语义解读新的状态集合，
18:05 领取一个 effect 并「成功」结算——结果在新语义下含义错误，且账面干净得
像什么都没发生。周一的排查者面对的是一行合法数据而非崩溃堆栈：错误被推迟到
最难归因的位置。对称地，若 gate 退化成「跑一下、人工看看输出」，日志层的一个
seq 洞会静默下传，在离成因最远的下游爆发——回放与分叉都以 seq 连续为前提。

**被拒替代。** 「第一天就装全生产栈」：读者在写第一行 SQL 前先调消息服务器
的端口与版本兼容，学习信号被基础设施噪声淹没；买到的是当前威胁条件下不存在
的冗余。纪律换成「文档约定 + 评审」：append-only、seq 无洞是机器可判定的
性质，交给人执行则不可复现；后续章节层层依赖这些性质，一环靠人，整链靠人。
