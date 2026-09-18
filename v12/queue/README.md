# v12 G6 · queue —— PGMQ 模式（v3–v6 架构回归 v12）

Gate: `uv run python v12/queue/test_queue.py`（退出码 0 = 通过）

## 两种运行方式，同一套表与不变量

| | inline（G4，保留） | queue（本 stage，新增） |
|---|---|---|
| 状态机 | `TurnRunner` 进程内直驱 | `QueueDriver` 纯 SQL 步进 |
| 外部 IO | `TurnRunner` 进程内调用 | `QueueWorker` 轮询 PGMQ，访问 OpenRouter→Jev / 工具 / LLM |
| 部署形态 | 单进程最简 | driver 与 worker 可分机；worker 可多副本 |
| effect_id | Python `uuid5` | SQL `v12_effect_id`（`v12_uuid_v5`，G6 断言两者逐字节相等） |

PG 内部视角：**提问 = INSERT 批次 + `v12_send_work` 入队；答案 = worker 落库行；
路由/推进 = driver 的 SQL 事务**。消息只是唤醒（不变量 8 血统）——
丢失消息只拖慢不损坏，`v12_requeue_stale()` 从表本身重建积压。

## 消息协议

- 队列 `v12_work`，消息 `{"kind": "jev"|"job", "id": uuid}`。
- **jev**：worker 取 `v12_request_payload` 组装的请求 → 调 Jev →
  `v12_record_answers`（'ready' CAS 天然去重重复消息）→ archive。
  瞬时失败（网络/429/529，`JevError.transient`）→ `set_vt(2s)` 重投，
  `read_ct >= 5` 或确定性失败 → 批次置 `failed` + archive（driver 随即转人工）。
- **job**：worker 经 G3 纪律执行（claim/fence → 执行 → complete）→ archive；
  lease 被他人持有 → 延后重试。

## G6 场景

1. 队列模式 tool 路由端到端 + effect id 跨模式一致 + 消息全部归档；
2. 瞬时失败 VT 重投（read_ct 2 次后成功）；
3. 重复唤醒去重（一次 ask）；
4. 确定性答案失败 → 批次 failed + 单次尝试 + turn 转人工；
5. 丢消息 → `v12_requeue_stale` 扫描恢复；
6. LLM + 护栏全走队列（draft → guardrail → 交付）；
7. 同会话多 turn（批次按"最后一条用户消息之后"过滤，不串轮）。

## 开发中修的三个真 bug（已固化）

- `pump` 循环拿到 True 后漏调 `_archive`——消息只被 VT 藏住并未归档，
  "队列已空"是假阴性（必须直查 `pgmq.q_v12_work`）；
- UPDATE 误走只给 SELECT 用的 `_one()` → `no results to fetch`；
- SQL 手写 RFC 4122 v5 时版本位/变体位的字节位置（byte 7 / byte 9），
  由"与 Python uuid5 逐字节相等"的断言逼出修正。
