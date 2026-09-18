# v12 · Jev 进 pgembed 的极简 agent —— 实施计划

> 日期：2026-09-18。前置调研：TypeSafe Jev（System One 模型，`POST /v1/systemone`，
> 三原语 Choice/Score/Noul，批量问题共享一个 state，返回类型化概率与置信度）。
> 定位：v12 **不继承** v8/v10/v11 的任何 SQL；只继承仓库级不变量与工程仪式
> （stage/gate、setup_db DROP-CREATE、FakeX 不碰真实 provider、外部 IO 不进事务）。

## 0. 设计一句话

**SQL 管算术与顺序，Jev 管语义与判断，LLM 只管生成。**
决策即行（提问是 INSERT、回答是 INSERT、路由是带阈值的 VIEW），
行动才需要 effect 纪律（稳定 effect_id / fence / lease / unknown 不盲目重放）。

## 1. 三平面模型（约 8 张表）

| 平面 | 表 | 职责 |
|---|---|---|
| 日志 | `sessions`, `events` | append-only、无洞 seq（继承 v8 不变量 1 的极简形态） |
| 决策 | `jev_batches`, `jev_questions`, `jev_decisions`, `thresholds` | Jev 问答全落库；`request_hash` 幂等缓存；阈值是数据不是代码 |
| 行动 | `tools`, `jobs` | 目录 + effect 总线；**只有**真副作用工具与 LLM 生成走这里 |

## 2. 分工与劣势规避（对应调研结论）

| 风险 | 规避机制 | 落点 |
|---|---|---|
| CJK 准确率低 | 问题/判据一律英文，DDL 级 CHECK 禁非 ASCII 进 questions；中文只允许出现在 state | G1 CHECK、G2/G4 断言 |
| 不擅长数学/日期/计数 | 派生数值（计数、年龄、开放任务数）由 SQL 在 fold_state 里算好，Jev 只读现成字段 | G4 |
| 概率无恒等式 | 路由只逐题比对 thresholds，永不组合 p 与 1−p | G2 |
| 对抗内容不设防 | `gate_off_topic` 注入检测题 + LLM 出站护栏三题（PII/切题/安全） | G4 |
| 无限 agent 循环 | 有界 turn：`turn/route` 事件计数即步数预算（durable），超限强制人工 | G4 |
| 供应商锁定/不可审计 | 请求/答案/用量原样落库，`request_hash` 命中即缓存重放，不重打 API | G2 |
| 外部副作用重复执行 | effect_id 唯一 + fence CAS + lease + unknown 显式 resolution（仅限 jobs 平面） | G3 |

## 3. 里程碑与 gate

每个 gate：`uv run python v12/<stage>/test_<name>.py`，退出码 0 = 通过；
提交前该 stage 及**之前全部** stage 的 gate 都要跑（防回归）。

- **M1 schema（G1）**：三平面 DDL + 不变量（append-only 触发器、无洞 seq、
  effect_id 唯一、英文 CHECK、criteria 形状 CHECK、thresholds CHECK）。
- **M2 decide（G2）**：批次生命周期 open→ready/answered/cached；request_hash
  幂等缓存；答案逐题校验（形状/选项/值域/覆盖）；信号提取 + 阈值路由 VIEW。
- **M3 act（G3）**：enqueue 幂等（succeeded 幂等返回 / failed 重试复用身份 /
  unknown 拒绝重入）；claim/fence/lease；过期接管；CAS 完成；unknown 显式解决。
- **M4 turn（G4）**：有界 turn 流水线端到端（FakeJev/FakeLLM/FakeTool）：
  sql / tool（闭集参数 + stated 省略）/ llm（护栏）/ human / 低置信 /
  注入否决 / 风险否决 / 预算耗尽 / 崩溃恢复（决策缓存 + effect_id 幂等续跑）。
- **M5 fanout（G5）**：行集排序演示（semantic_find 模式）：≤255 行单遍
  Choice 排序 + 存在性 Noul；>255 行两遍（窗口 Choice → 窗内排序）。
  DuckDB 以 postgres_scanner 读同一批表的扩展点记录于 README，不在 gate 内。

## 4. 收尾工件（每里程碑）

- 新 SQL 追加进 `v12/load.py` 的 `SQL_LOAD_ORDER`（纯末尾追加）；
- 对应 stage 的 `README.md` 更新。

## 5. 明确不做

- 第二队列、driver/compat、插件世代、字节级 canonical/流完整性（v8 已裁）；
- 自由文本生成交给 Jev（明确禁止，LLM effect 独占）；
- pgvector/嵌入检索（fanout 演示 Choice 排序即可覆盖 demo 场景）；
- 真实 Jev/LLM 调用进 gate（`v12/jev_client.py` 仅供生产，测试一律 Fake）。
