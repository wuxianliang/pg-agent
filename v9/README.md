# pg-agent v9 · context_early（早期上下文包）

一句话定位：任务创建时即投机构建 context pack（context_early）——源变更（其他任务落地）通过 commit 通知精确标脏受影响切片并增量刷新，任务启动前由 gate 判定新鲜度（fresh / sync_refresh / drift_delta）。

实现契约：`docs/plans/v9-context-early-spec-2026-09-15.md`（FROZEN，逐字遵守）。

## 阶段顺序与 gate

| Gate | 目录 / 测试 | 数据库 | 验证内容 |
|---|---|---|---|
| W1 | `kernel_freeze/test_kernel_freeze.py` | `agent_v9_kernel_freeze` | 只读加载 v3–v6 的 21 个 SQL，基线零复制零修改 |
| W2 | `ctx_schema/test_ctx_schema.py` | `agent_v9_ctx_schema` | ctx 状态表（ctx_sources / context_packs / context_slices / slice_dependencies / ctx_operations …） |
| W3 | `ctx_queue/test_ctx_queue.py` | `agent_v9_ctx_queue` | `ctx_heavy` PGMQ 队列 + `apply_ctx_result` 经继承的 `apply_queue_result` 分发 |
| W4 | `ctx_lifecycle/test_ctx_build.py` | `agent_v9_ctx_lifecycle` | 任务 → pack → build 消息 → apply → FRESH（含幂等与乱序拒绝） |
| W5 | `ctx_lifecycle/test_ctx_staleness.py` | `agent_v9_ctx_lifecycle` | commit 精确标脏、pending_refresh、无关变更空转 |
| W6 | `ctx_lifecycle/test_ctx_refresh.py` | `agent_v9_ctx_lifecycle` | 增量刷新只重建脏切片、尾巴消费自动续 refresh |
| W7 | `ctx_lifecycle/test_ctx_gate.py` | `agent_v9_ctx_lifecycle` | gate fresh / sync_refresh / drift_delta / RETIRED |
| W8 | `ctx_worker/test_ctx_worker.py` | `agent_v9_ctx_worker` | 库外 Python worker：build / refresh / 投毒 DLQ / read_ct 超限 |
| W9 | `integration/test_v9.py` | `agent_v9_integration` | 全链路：build → 标脏 → gate → 刷新 → 崩溃重放 → retire |

W4–W7 共用 `agent_v9_ctx_lifecycle` 库；每个测试先跑自己的 `setup_db.py` 重建库，可独立重复运行。gate 按 W1→W9 顺序执行，前一 gate 不过不进下一个；任一失败即停止，不用 fallback 版本、不跳过失败阶段、不把“代码已写”当作“功能已验证”。

## 运行命令

仓库根 `/Users/wxl/Projects/pg-agent`，全部 `uv run python ...`，退出码 0 = 通过：

```bash
uv run python v9/kernel_freeze/test_kernel_freeze.py   # W1
uv run python v9/ctx_schema/test_ctx_schema.py         # W2
uv run python v9/ctx_queue/test_ctx_queue.py           # W3
uv run python v9/ctx_lifecycle/test_ctx_build.py       # W4
uv run python v9/ctx_lifecycle/test_ctx_staleness.py   # W5
uv run python v9/ctx_lifecycle/test_ctx_refresh.py     # W6
uv run python v9/ctx_lifecycle/test_ctx_gate.py        # W7
uv run python v9/ctx_worker/test_ctx_worker.py         # W8
uv run python v9/integration/test_v9.py                # W9
```

常驻 worker（可选，独立进程轮询 `ctx_heavy_requests`）：

```bash
uv run python v9/ctx_worker/worker.py --db agent_v9_integration
# env：PG_AGENT_DB（缺省 agent_v9_integration）、PG_AGENT_WORKER_ID（缺省 v9-ctx-1）
```

## 边界

- 基于 v6 代码基线：v3–v6 的 21 个 SQL 文件按路径只读加载，零修改、零复制，不 `import v4/v5/v6`。
- 队列：PGMQ `ctx_heavy_requests` + `ctx_heavy_requests_dlq`，queue kind `ctx_heavy`；结果经继承的 `apply_queue_result(p_queue_name, p_msg_id, p_run_id, p_result)` 分发到 `apply_ctx_result`。
- 任务锚点 = `agent_runs.run_id`（parked run：有 run 行、零 step，不 enqueue LLM）。
- Worker 是纯 Python 库外进程：轮询队列、按 `ctx_sources` 白名单快照读源表、产切片、单事务 apply + archive。
- 所有 SQL 幂等可重放（CREATE TABLE IF NOT EXISTS / CREATE OR REPLACE）；所有函数 SECURITY INVOKER；错误包形状统一 `{'success':false,'Type':…,'Problem':…,'Solution':…}`。
- 不修改 v1–v6、pgembed、pyproject、server.py；只新增 `v9/` 目录与本规格文档。

## 与 docs/designs/v10-raw.md 的关系

`docs/designs/v10-raw.md` 是一份**未开工**的 ContextPipe 装配管线设计稿（catalog / optimizer / statistics / EXPLAIN 五阶段，poml 声明层）。本目录的 v9 与该设计**无实现关联**：这里按用户指令实现 context_early（任务创建即建包 + commit 精确标脏 + 启动前 gate），仅版本号沿用 v9——该用法已对照 v10-raw.md 的命名检查（其 §5.6：v10-dev 定名前检查与 v1–v9 既有 schema 无冲突）确认与 v1–v7 既有 schema 无冲突。

## 当前验证结果

2026-09-15 在本地环境(macOS arm64 / CPython 3.12 / pgembed PostgreSQL 18.4)完成 W1→W9 顺序复跑,全部通过:

```text
W1 kernel_freeze    passed
W2 ctx_schema        passed
W3 ctx_queue         passed
W4 ctx_build         passed
W5 ctx_staleness     passed
W6 ctx_refresh       passed
W7 ctx_gate          passed
W8 ctx_worker        passed
W9 integration       passed  (36/36 checks)
```

| Gate | 结果 | 日期 |
|---|---|---|
| W1 kernel_freeze | passed | 2026-09-15 |
| W2 ctx_schema | passed | 2026-09-15 |
| W3 ctx_queue | passed | 2026-09-15 |
| W4 ctx_build | passed | 2026-09-15 |
| W5 ctx_staleness | passed | 2026-09-15 |
| W6 ctx_refresh | passed | 2026-09-15 |
| W7 ctx_gate | passed | 2026-09-15 |
| W8 ctx_worker | passed | 2026-09-15 |
| W9 integration | passed | 2026-09-15 |
