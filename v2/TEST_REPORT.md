# pg-agent data_analysis 里程碑测试

日期：2026-08-22 · 环境：macOS · LLM：DeepSeek `deepseek-chat`
标签：**窄 PostgreSQL data-analysis 里程碑**，不是 InfiniSynapse 协议兼容。

## 范围

- 与 v1 隔离：库名 `da_agent`，文件在 `v2/`。
- 加载：`pg_agent_functional.sql` → `pg_agent_rlm.sql` → `pg_agent_data_analysis.sql`。
- 入口：`agent_run_data_analysis` 建 `paradigm=data_analysis` run，循环走共用 `rlm_loop`。
- SQL 仍走既有 `rlm_eval` → `exec_sql_readonly`。
- 运行时拒绝「未成功 SELECT 就 final_answer」。

## 结果

`uv run python v2/setup_db.py && uv run python v2/test_data_analysis.py` → **23/23 通过**。

| 组 | 内容 |
|---|---|
| F0 | 函数存在；原 `make_rlm_prompt` 未 REPLACE；`make_da_prompt` 以 `information_schema` 为主 |
| F1 | 空 question 抛错 |
| F2 | 可选捷径 `da_list_tables` / `da_show_create` / `da_sample` 对 fixture 工作 |
| F3 | DELETE/DROP 仍被拒绝；错误包 Type/Phase/Problem/Solution |
| F4 | DeepSeek 4s / 2 次 tool：SQL 含 `da_sales_fixture`，总和 **700**；depth=0；无 child |
| F5 | 同一连接第二次 run_id 不串；SQL 仍打 fixture；North 总和 **250** |

## Oracle review（已吸收的 P1/P2）

- 未查库不得交卷（runtime gate）。
- 测试断言 `payload.code` 必须引用 `da_sales_fixture`。
- fixture 在 `try/finally` 里 DROP。
- prompt 主路径改为 `information_schema`，`da_*` 降为可选捷径。

v2 已吸收：`setup_db.py` 加载完整栈；`rlm_loop` 按 paradigm 分支；不再单独复制 `da_loop`。

## 证据边界

- 证明：专用入口能查真实表、答案来自行、不 spawn、原 RLM prompt 不变。
- 未证明：InfiniSQL、TEMP VIEW 工作台、sql_curator、SSE、delegate 聚合、`agent_rlm` 库同入口。
