# v17 G3 · queue —— Lisp queue worker 对 v12 队列合同的完整复现

Gate: `uv run python v17/queue/test_queue.py`（退出码 0 = 通过）

## 一句话

**SBCL worker 是 `QueueWorker` 的 drop-in 替代**：同队列（`v12_work`）、
同消息形状（`{"kind":"jev"|"job","id":uuid}`）、同常数
（VT=180 / RETRY_VT=2 / MAX_READ_CT=5 / LEASE=300）、同 CAS/fence
语义。driver 仍是 Python `QueueDriver`（SQL-only，不动）。

## 新组件（`v17/lisp/src/`）

| 文件 | 职责 |
|---|---|
| `pgmq.lisp` | `pgmq.read/archive/set_vt` 轮询协议（参数全显式 cast，计划 §2.1） |
| `jev.lisp` | Jev 客户端：dexador→OpenRouter decisions 端点（真实，gate 不测）+ 文件脚本 fake（gate 用；规则按序首匹配，`transient_failures` 计次；调用计数落 state 文件供跨进程断言，等价 v12 `fake.calls`） |
| `llm.lisp` | LLM 生成 effect 客户端：`V17_FAKE_LLM_TEXT` fake + dexador chat 真实版；未配置时 llm job 失败（同 `llm_fn` 缺失语义） |
| `worker.lisp` | pump 主循环：`do-batch`/`do-job` 逐条对齐 `queue_worker.py`；claim→execute→complete 同事务（psycopg2 版本的等价物）；工具注册表（`send_summary_email` demo 写 `gate_side_effects` + `echo` 往返工具） |

运行方式（`run-worker.lisp`，env 驱动）：
- `V17_PUMP_MODE=once`：一个 read 周期，`ARCHIVED=n`，退出（精确断言用）；
- `V17_PUMP_MODE=daemon`：泵到空闲 `V17_IDLE_EXIT_MS` 后退出
  （与 driver 并发推进用）；`V17_PUMP_LIMIT` / `V17_WORKER_ID`。

## 九场景

1. 队列模式 tool 路由端到端 + 跨模式 effect_id 一致 + 消息全部归档
   （副作用恰好一次经 `gate_side_effects` 跨进程断言）；
2. 瞬时失败 VT 重投（首泵 archived=0、批次仍 ready、>2s 后二次成功，
   `total_calls=2`）；
3. 重复唤醒去重（两消息全归档、一次 ask）；
4. 确定性答案失败 → 批次 failed + 单次尝试 + turn 转人工；
5. 丢消息 → `v12_requeue_stale` 扫描恢复；
6. LLM + 护栏全走队列（draft → guardrail → 交付，`llm_calls=1`、
   两个 answered 批次）；
7. 同会话多 turn 不串轮；
8. **jsonb canary**：echo 工具对嵌套/unicode/CJK/NULL 载荷字节保真
   往返（postmodern `$1::jsonb`/`::text` cast 纪律的回归锚）；
9. **跨语言混跑**：Python `QueueWorker`（线程）与 Lisp daemon 同抢
   `v12_work`——3 个 tool 路由会话全部交付；每批次恰好 answered 一次
   （'ready' CAS）；每 job 副作用恰好一次（fence）：
   `lisp_effects + python_effects == succeeded_jobs == 3`。

外加 fiveam `queue` 套件（fake jev/llm 契约与 JSON alist 形状，随
gate 跑）。

## 与 v12 G6 的断言差异（有据）

- 「副作用恰好一次」的观察面从进程内 list 换成 `gate_side_effects`
  表（Lisp worker 在子进程，跨进程只能经库断言）；
- daemon 模式的空转退出（4s）替代 `run_until_idle` 的进程内 worker；
  once 模式保留逐泵精确断言。

## 真实 provider

`jev.lisp`/`llm.lisp` 的真实 OpenRouter 后端不是 gate（v12 的
`probe_jev.py` 手动探针模式）；无 `OPENROUTER_API_KEY` 时 llm 客户端
为 NIL，jev 客户端首调即报错——gate 全程 `V17_FAKE_*` 离线确定性。
