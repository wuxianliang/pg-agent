# v8 G9 流式地基与观测路径（stream）

冻结合同：`docs/designs/v8-dev.md` §1.2 流完整性屏障（行 53）与 Conformance 10、§3.2.2 grammar（行 850 段）；
抽取摘要：`docs/analysis/v8-impl-digest/s2-planes-grants.md` §1.1/§1.2/§2、
`s31b-command-table.md` §2.8/§3.1、`s32b-effect-ledger.md` §3.2、`s32c-completion-evidence.md`（L4-R03/F5、S04）。
计划：`docs/plans/v8-native-lifecycle-plan-2026-09-16.md` G9 节（G9a 地基 + G9b 观测路径）。

库 `agent_v8_stream`（`setup_db.py` 重建；`v8/load.py` 中 `stream` stage 累计加载 schema → keys → **stream** → events → effect → tools → closure → retry → takeover）。

## 交付件

### G9a（流式地基）

| 件 | 落点 |
|---|---|
| session_events 增列 | `v8_stream.sql` §1：`stream_id`/`chunk_index`/`observation_ordinal` + 三个列级 CHECK + ordinal 唯一部分索引 |
| 最小 slice/grant stub | `v8_stream.sql` §2/§3：`slices`、`grants`（复合 FK 租户一致性）、`v8_slices_immutable`/`v8_grants_immutable` 触发器 |
| 有效 grant 谓词 | `v8_stream.sql` §4：`v_grant_valid(p_session_id, p_grant_id, p_capability)`、`v_grant_subject` |
| chunk 六项归属补全 | `v8/events/v8_append.sql`：第 (2) 已结算 attempt 臂、(3) stream_id 归属、(6) 三合取；调用方身份参数 |
| 字段矩阵 + 计数 ABI | `v8/effect/v8_effect.sql`：四步序第 (iii) 步替换 `STREAMING_LATER` |
| gate | `test_stream.py`（67 PASS） |

### G9b（观测路径 + 五款状态门 + 等值生命周期 + partial 合成 + Conformance 10）

| 件 | 落点 |
|---|---|
| 五款状态门 + observation receipt | `v8_stream.sql` §5 `v_stream_observe(...)`：拒绝优先序 `SESSION_TERMINAL` → superseded（`rejected_stale`）→ attempt 四终态（`STREAM_CLOSED`）→ unknown/窗口耗尽（`REPAIR_REQUIRED`）→ 接受；接受写集 = observation receipt + `stream_progress` 观测事件（控制态零修改 AF01）；receipt `observation_identity` 三元组 `(attempt_no, observation_ordinal, payload_digest)`（Q04）；`complete_effect` 的 (iii)/(iv) 分支改调该子操作 |
| 认证流事实持久化 | `v8_stream.sql` §6 `stream_completions` 表 + `v_stream_record_completion`（(i) 形态结算时写入 N/C/final_text，供等值生命周期与 F4 范围检查读取） |
| 收齐判据统一提取 | `v8_stream.sql` §7 `v_stream_flow_indices`：仅消费已接受 chunk 事件（S04 clause 2），返回 index 集合 (count/min/max) + 按 chunk_index 序合并文本 |
| 冲突事实持久化 | `v8_stream.sql` §8 `v_stream_conflict_fact`（幂等 `CANONICALIZER_CONFLICT` audit）；`v_stream_incomplete_fact`（§9 `STREAM_INCOMPLETE` audit reason） |
| 等值 / F4 判定 | `v8_stream.sql` §8 `v_stream_equivalence`：集合精确相等（不物化 {0..N}）、F4 超范围直接记冲突且**不执行**等值断言、final 未到/缺 index → pending、等值失败 → 冲突事实 |
| 迟到 chunk 等值补齐 | `v8/events/v8_append.sql`：终局 effect 的合法迟到 chunk 接受后重跑 `v_stream_equivalence`（屏障 (d) 第二事实） |
| 窗口耗尽收束 | `v8/retry/v8_takeover.sql`：流式 attempt 接管结算 unknown 时记 `STREAM_INCOMPLETE`（grammar (7)） |
| quiescing 注记 | `v8/effect/v8_effect.sql`：非终局观测不受 quiescing 阻（五款门唯一裁定）；终局 completion 在 `driver_mode='quiescing'` 下仍 `DRIVER_QUIESCING`（W01） |
| payload 分层（S04） | `v8/events/canonicalizer.py`：`stream_progress`/`attempt/heartbeat` 接受但**排除**于 normalize 输入/输出与 reducer 聚合（count 字段仅审计） |
| partial 合成补全 | `v8/events/canonicalizer.py`：sticky cancel（`cancelled_after_dispatch`）分支补 `assistant/partial` 合成（有前缀输出一条、无前缀不输出）；unknown 路径既有合成 |
| canonicalizer 侧引擎 | `v8/stream/observation.py`：`flow_state`/`equivalence`/`three_representations_agree`/`partial_text`/`portable_verify` + 持久化/读取 helper（SQL 判定的确定性 Python 镜像） |
| gate | `test_observation.py`（72 PASS） |

## 加载序与 STAGE_THROUGH 重编号

`stream/v8_stream.sql` **必须排在 events 之前**：公开 append 路径消费新列（INSERT 写 `stream_id`/`chunk_index`）与 `v_grant_valid`，且 session_events 的列级 CHECK 在 chunk 行插入时即生效；G9b 的 `v_stream_observe`/`v_stream_equivalence` 等子操作同为 append/effect 阶段所消费。因此 `SQL_LOAD_ORDER` 在 `schema/v8_keys.sql` 之后、`events/v8_append.sql` 之前插入 stream 文件；`STAGE_THROUGH` 相应重编号：

```
schema 2 · events 4 · stream 9 · effect 5 · tools 6 · retry 9 · loop 5 · repair 10 · cancel 11
```

`stream` stage 取到 takeover（9）——gate 需覆盖 events（append 六项 + 迟到 chunk 补齐）、effect（字段矩阵 + 观测子操作）、retry/takeover（非 known_success 豁免负向、窗口耗尽 `STREAM_INCOMPLETE`）三处消费者。

## 作用域声明（P0A 最小 stub）

`v8_stream.sql` §2/§3 只实现 chunk 六项第 (3)(6) 项与 event_append/stream_ingest 基础能力所需的**可判定最小模型**。§2.1 完整模型——授权线性化点（`SELECT ... FOR UPDATE` 固定锁序 `(workspace_id, slice_id, grant_id)` 或 `revocation_version` CAS）、seam 清单、RLS、operator 通道、`constraints` 参数级求值（path/command/target/TTL/max_bytes/max_rows）、`workspace_handles` 五状态机与 WORKSPACE_LOST drain——**归 P1**。`constraints` 在本 stage 仅作不透明 jsonb 携带。

### 观测路径的阶段模型边界（G9b）

- **等待窗口**＝lease/超时语义（s32b (7)），真实 sweep 属 LATER；本 stage 以事务局部 GUC `v8.stream_window_exhausted`（`'on'` 即耗尽，同 `v8.slot_protected_write` 通道）作为该语义的**可判定输入**，默认活性窗口。
- **`reconcile` 入口**：遇 (iii)/(iv) 形态 MUST NOT 终局结算、MUST NOT 写 stream_progress，固定拒绝 `OBSERVATION_WRONG_ENTRY`——本 stage `reconcile` 未实现，常量落在 `observation.py`，**结构注记**。
- **等值断言时序**：final 先到、尾部 chunk 未到 → 处 pending（completion 不因等值阻塞、照常收束）；尾部 chunk 窗口内到达即补齐；失败 → 仅记冲突审计事实，业务终态不可改写（(d) 两事实拆分）。全文等值按 final message 的 `text` 分量与合并 chunk 文本比较（canonical 表示层）。
- **窗口耗尽后迟到终局经 repair**：证据经既有证据分类路径（`REPAIR_REQUIRED`、观测/审计留存），A23/A33 deferred 注记不变。

### 向后兼容约定（append 调用方身份腿）

`v_append_events` 新增 4 个 **DEFAULT NULL** 参数（`p_caller_subject`/`p_caller_driver`/`p_caller_epoch`/`p_caller_grant_id`）。当目标 effect **未被 grant 绑定**（`effect_requests.grant_id IS NULL`）且四个调用方腿全缺省时，按 legacy P0B 路径（注记降级）放行第 (3)(6) 项；一旦 effect 被绑定或任一腿被提供，则 (3)+(6) 全部合取强制（缺任一 → `CHUNK_ATTRIBUTION_INVALID` 零落盘）。这是 grant 模型的 opt-in 语义：既有 events gate 的 chunk 用例（未绑定 effect）不受影响，本 stage 的负向向量经显式绑定 + 传参行使。

## 已知余量（后续）

- `reconcile` 入口与本 stage 五款门的接线（结构注记已就位）。
- 跨 attempt 残留（被取代 attempt 的 chunk 仅 observational 留存；合并只取终局/unknown attempt）与 `stream_completions` 的跨 attempt 清理。
- 真实 lease/超时窗口 sweep 与 `STREAM_INCOMPLETE` 的接管触发条件细化（当前按流式 attempt 接管结算 unknown 即记）。
- 审计指纹三键 golden（audit 里程碑）。

