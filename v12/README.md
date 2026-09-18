# v12 —— Jev 进 pgembed 的极简 agent

> 计划：`docs/plans/v12-jev-pgembed-minimal-plan-2026-09-18.md`
> 调研结论：TypeSafe Jev（System One 模型）返回类型化概率决策，
> 官方哲学「AI 驱动的软件而非 agent」——与本项目「PG 拥有状态机、
> worker 只执行已持久化的 effect」的方向天然互补。

## 设计一句话

**SQL 管算术与顺序，Jev 管语义与判断，LLM 只管生成。**

- 提问是 INSERT（问题即行）、回答是 INSERT（答案即行）、路由是
  带阈值的 VIEW（阈值是数据不是代码）。
- Jev 调用是纯函数：`request_hash` 命中即缓存重放、可审计、失败重问。
- 只有真副作用（外部工具、LLM 生成）走 effect 纪律：
  稳定 effect_id / fence CAS / lease（clock_timestamp）/ unknown 显式解决。

## 三平面（8 张表）

| 平面 | 表 | 职责 |
|---|---|---|
| 日志 | `sessions` `events` | append-only、无洞 seq |
| 决策 | `jev_batches` `jev_questions` `jev_decisions` `thresholds` | Jev 问答全落库 + 阈值路由 |
| 行动 | `tools` `jobs` | 目录 + effect 总线 |

## Stage / Gate

| Stage | Gate（`uv run python …`，exit 0 = 过） | 内容 |
|---|---|---|
| G1 schema | `v12/schema/test_schema.py` | 三平面 DDL、append-only、ASCII 问题约束、形状 CHECK |
| G2 decide | `v12/decide/test_decide.py` | 批次生命周期、hash 幂等缓存、答案校验、路由带 |
| G3 act | `v12/act/test_act.py` | effect_id 幂等、fence/lease/接管、unknown 墙 |
| G4 turn | `v12/turn/test_turn.py` | 有界 turn 端到端（sql/tool/llm/human/护栏/预算/崩溃恢复） |
| G5 fanout | `v12/fanout/test_fanout.py` | 一个 Choice 排 ≤255 行、两遍窗口、存在性 Noul |

每个 stage 的 `setup_db.py` DROP/CREATE 自己的库（`agent_v12_*`），
按 `v12/load.py` 的 `SQL_LOAD_ORDER` 累计加载（纯末尾追加）。

## 目录

```
v12/
  load.py          SQL_LOAD_ORDER + STAGE_THROUGH
  jev_client.py    Jev 客户端：OpenRouter 为主 provider，TypeSafe 直连为备
  probe_jev.py     一次性探针（手动跑，非 gate）：测定 OpenRouter 的请求格式
  fake_jev.py      确定性脚本化 Jev（gate 专用）
  worker.py        TurnRunner：唯一发生外部 IO 的地方
  schema/ decide/ act/ turn/ fanout/
```

## Provider 配置（OpenRouter 为主）

`JevClient` 按「显式参数 > OPENROUTER_API_KEY > TYPESAFE_API_KEY」选择后端，
`ask(state, questions)` 接口与 FakeJev 完全一致，gate 不受影响。

- **OpenRouter（主）**：模型 `typesafe/jev-1.13`（`~typesafe/jev-latest`
  是前端别名，API 只认规范 id），modality `text->decisions`，
  $0.042/M input、output $0，2026-09-18 上架。其请求映射尚无官方文档，
  客户端内置三种模式（wrapped / native / system_user）——
  首次使用先跑一次 `OPENROUTER_API_KEY=... uv run python v12/probe_jev.py`
  （约 $0.00004），按输出的建议 `export V12_JEV_OPENROUTER_MODE=<mode>` 固定。
- **TypeSafe 直连（备）**：`api.typesafe.ai/v1/systemone` 原生格式，
  设 `TYPESAFE_API_KEY` 即启用；字段保真的参考实现。
- 注意：OpenRouter 聚合目录（`GET /api/v1/models`）截至 2026-09-18
  尚未收录该模型，依赖 models 列表做校验的 SDK 可能报「未知模型」——
  直接指定 model id 调用即可。

## 风险规避（对应 Jev 已知短板）

| 短板 | 机制 |
|---|---|
| CJK 准确率低 | 问题/判据 ASCII-only 由 DDL CHECK 强制；中文只进 state |
| 数学/日期/计数弱 | 派生数值全部 SQL 预计算进 `state.derived` |
| 概率无跨题恒等式 | 逐题阈值路由，永不组合 p 与 1−p |
| 对抗内容不设防 | gate_off_topic 注入否决 + LLM 出站护栏三题 |
| 无限循环 | 预算持久化（turn/route 事件计数），放弃零 Jev 调用 |
| 不能生成 | 生成独占 LLM effect；护栏不过不交付 |

## 与历史版本的关系

不继承 v8/v10/v11 任何 SQL；继承仓库不变量（外部 IO 不进事务、
DB 扫描可恢复、FakeX 测试）与 v8 内核思想的最小子集
（append-only 日志、fence/lease、unknown 不盲目重放）。
对比：v8 37 张表 / 24 gate / ~4.6 万行；v12 8 张表 / 5 gate。
