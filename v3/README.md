# pg-agent v3：库内 PGMQ + 库外 worker

独立库 `agent_v3`，不改 v1/v2。

**循环拆在 SQL 边界上：**
- `agent_start` → `prepare_llm_request` → `pgmq.send('llm_requests')`，立即返回 `run_id`
- 库外 `AgentWorker` 调 LiteLLM（429/超时在同一步内重试）
- `apply_llm_response` 解析、跑工具 SQL、需要的话再入队
- 每个 `run_id` **粘住一条连接**，`session_set` / `session_get`（TEMP KV）跨轮次可见
- 读出后崩溃：visibility timeout 到期整步重放；`apply` 按内容 hash 幂等
- `read_ct` 超限：进 `llm_requests_dlq`，`fail_run` 标 error

HTTP 的 `agent_run` 只留给 `compare.py` 对照占用，不是 v3 主路径。

```bash
uv run python v3/setup_db.py
uv run python v3/test_v3.py            # 1–3 的门闩
uv run python v3/compare.py            # 占用对照（mock）
uv run python v3/worker.py             # 常驻 worker
```
