# v12 G4 · turn —— 有界 turn 流水线（Jev 判断 → 确定性路由 → effect 执行）

Gate: `uv run python v12/turn/test_turn.py`（退出码 0 = 通过）

## 一个 turn 的形状（不是 while 循环 agent）

```
user/message ─► decide ─► turn/route ─► execute ─► tool/result / llm/message ─► turn/end
                                │
                                └─ llm: turn/llm_draft ─► guardrail 批 ─► 交付或转人工
```

每一步都先落库再执行下一步；worker 崩溃后新实例从事件续跑
（G4 场景 9：decide 完成后崩溃，救援 worker 不再调 Jev、effect_id
确定性推导使 job 恰好一行）。

## 分工的落点

- **SQL 管算术**：`v12_fold_state` 把 message_count / open_jobs /
  session_age_seconds 全部算好放进 `state.derived`——Jev 永不计数、
  永不比日期（其已知短板）。
- **Jev 管语义**：一次 turn 批问 9 个英文问题（intent Choice、
  gate_action / gate_off_topic Noul、risk Score(0..3)、tool Choice、
  每工具参数 param Choice + stated Noul）；护栏批再问 3 个正向 Noul。
- **代码管路由**：`v12_route_turn` 是纯 SQL 策略——
  注入否决（gate_off_topic=act）> intent 置信带 > 人工升级 >
  read_only→sql / side_effect+risk≥2.25→人工 / 其余→tool / 兜底→llm。
- **参数不猜**：`v12_resolve_tool_params` 只在 stated Noul 过 act 带时
  纳入该参数，否则省略、由工具默认值兜底（function_calling cookbook 语义）。
- **预算持久化**：`v12_turn_cycles` = 已落库的 turn/route 事件数；
  超 MAX_CYCLES（3）强制人工——放弃本身零 Jev 调用。

## 风险规避对应表（计划 §2 的落点）

| 风险 | G4 场景 |
|---|---|
| 注入（gate_off_topic） | 4：intent 0.95 仍被否决，零执行 |
| 高危副作用（risk Score） | 5：score 2.6 → risk_veto，无 job |
| 低置信（intent 带） | 3：review 带以下 → awaiting_human |
| LLM 出站内容 | 6/7：护栏三题全 act 才交付；PII 0.05 → 草稿留存、不交付 |
| 无限循环 | 8：预算耗尽 → 人工，Jev 调用 0 次 |
| 崩溃恢复 | 9：决策已落库 → 不重复问；effect_id 确定性 → 不重复执行 |

## 开发中修的两个真 bug（已固化）

1. **lease 用 `clock_timestamp()`**（G3）：`now()` 事务内固定，lease 永不过期。
2. **Score 信号 = 分数值而非 confidence**（本 stage 触发）：否则
   risk 阈值（0..3 量表上 2.25）永远达不到，风险否决形同虚设——
   信号必须是题目的「测量值」：choice→confidence、score→score、noul→noul。
