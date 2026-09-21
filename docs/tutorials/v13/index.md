# pg-agent v13 教程 — Postgres-Native Agent 底座

> 用 **9 张表、9 条不变量、7 个 gate**，从 0 到 1 讲清一个 Postgres-native agent 底座的设计。
> 章节组织参照 mini-deepseek-harness-python 的教程结构；讲解对象是本仓库自己收敛出的 v13 设计，与该项目实现无关。

## 这是什么

一句话：**v12 的三平面 + v8 的 effect 脊柱 − 为第二个租户、第二个运行时、第二个 driver 付的全部税。**

Postgres 拥有全部持久化状态、合法状态转移与 effect 决策；worker 只执行已持久化的 effect，
外部 IO 一律不进事务。判断（Jev 或 LLM）落成行，路由是视图，阈值是数据，
工具是目录行，中间产物是内容寻址的行。

本教程的目标不是移植 v8 的 24 gate / 3000 断言，而是掌握约定：

| 保留（技术核心） | 跳过（v8/v10/v11 已裁） |
|---|---|
| append-only 事件 + 无洞 seq | canonical 字节仪式 / 黄金向量 |
| effect 四件套（稳定 id / fence / lease / unknown） | grant 帝国 / 插件世代 / 双授权门 |
| 队列只是唤醒 + 扫描恢复 | 八位锁序 / reconcile / driver epoch |
| 判断即行、阈值即数据、路由即视图 | compact 协议 / 流式 chunk ABI / audit 指纹 |
| 工具目录是数据、artifacts 内容寻址 | 六角色 ACL / 双运行时 compat 面 / POML 管线 |

## 「上游」是谁

mini-dsh 的上游是 deepseek-harness；本教程的上游是**本仓库自己的十二轮实验**。
每章末尾的「回到 vN 对照」指向该思想的出处：

| 版本 | 贡献的承重件 |
|---|---|
| v1/v2 | 工具即 SQL 函数、结构化错误信封、只读角色执法 |
| v3 | 队列切分：SQL 入队意图 / worker 独占 IO / apply 幂等 |
| v4/v5 | named tools、prompt 从表装配、SQL 永不调模型 HTTP |
| v6 | enqueue-only 工具 + op_seq + fail-closed（DUCK_SESSION_LOST） |
| v8 | effect 纪律四件套 + kill-at-every-boundary 仪式 |
| v9 | freshness 是谓词不是管线 |
| v12 | 三平面 + 判断即行 + 阈值是数据 |
| loopx / Dream-RSI / v11 | 长时运行与 RSI 的余量缝（两列 + 开放事件类型） |

## 学习地图

```text
00 环境 ─────────── 跑起来、纪律、简化立场
01 日志平面 ─────── sessions/events：行是唯一真相
02 行动账本 ─────── effects 四件套 + worker 三步合同
03 队列只是唤醒 ─── PGMQ 可丢可重，扫描恢复
04 决策平面 ─────── 判断即行，路由即视图
05 turn 与推进 ──── agent_advance 五步 + 预算即策略
06 工具目录 ─────── 目录是表，可见性是查询
07 artifacts 平面 ─ 中间产物内容寻址、不可变
08 多语言 harness ─ SQL-only 合同，语言差异进 worker
09 超级工作台 ───── 一个 duck bundle，三层唯一性
10 RAG 即工具 ──── chunk=artifact，相关性=判断
11 崩溃与混沌 ──── kill-at-every-boundary
12 干预面 ──────── cancel / human / resolve_unknown
13 长时运行 ─────── 目标树、quota、tick（loopx 映射）
14 fork 与回放 ──── RSI 余量：读者+创建者纪律
15 版本门与边界 ── meta、观察视图、YAGNI 台账
```

## 三条学习纪律

1. **先看 gate 想验证什么，再读 SQL**。每个 gate 是「始终成立的性质」清单；
   测试比实现更接近设计意图。
2. **每章完成检查点练习**。练习都是 10~20 行的小改动——加一列、写一个视图、
   构造一个竞态——改完要么让 gate 通过，要么新增断言钉住你的行为。
3. **每章末尾「回到 vN 对照」**。打开对应版本目录只读关键 50 行，
   体会「思想一样、机器减掉」在哪里。

## 与仓库工件的关系

- 实现规范（冻结后）：`docs/designs/v13-dev.md`
- 版本裁决依据：本仓库 `docs/designs/v8-dev.md`、`v10-dev.md`、`v12/README.md`
  及两轮 Oracle 批判（2026-09-18）
- 教程本身不产生合同效力；与规范冲突时以冻结规范为准
