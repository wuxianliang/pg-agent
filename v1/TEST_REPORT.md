# pg-agent 测试报告

日期：2026-08-21 · 环境：macOS (Apple Silicon) · LLM：DeepSeek `deepseek-chat`

## 环境搭建

| 组件 | 说明 |
|---|---|
| uv + Python 3.12 | `uv init` + `uv add pgembed psycopg2-binary` |
| pgembed 0.2.0 | 自包含 PostgreSQL 17.9（数据目录 `.pgdata/`，`uv run server.py` 管理） |
| pgsql-http v1.7 | pgembed 不含 http 扩展，从 [pramsey/pgsql-http](https://github.com/pramsey/pgsql-http) 用 pgembed 的 `pg_config` 编译安装（PGXS 的 CI sysroot 路径已改写为本机 SDK） |
| Homebrew postgresql@17 | 仅用于 poml 渲染层补充测试（pgembed 二进制未编译 libxml） |
| DeepSeek | `openai.api_uri=https://api.deepseek.com/v1`，`openai.model=deepseek-chat`，key 来自 `DEEPSEEK_API_KEY` |

分库加载（fixed 与 functional 的 `agent_runs`/`agent_steps` 同名不同构）：
`agent_fixed` ← pg_agent_fixed.sql；`agent_func` ← pg_agent_functional.sql + pg_agent_poml.sql。

## 测试结果

- **A. pg_agent_fixed.sql — 11/11 通过**（pgembed）
  execute_sql_safe 四类安全断言；`run_agent_sql` 端到端（DeepSeek，4s/3 步收敛）；
  `build_context_parallel → agent_worker → finalize` 生成 7 片段上下文；带上下文 agent 经 worker 队列 4s 完成。
- **B. pg_agent_functional.sql — 15/15 通过**（pgembed）
  sql_pipe / sql_map / sql_retry 组合子；make_system_prompt / parse_llm_output（含 markdown 围栏与噪声文本）/ fold_messages；
  exec_sql_readonly；`refresh_handlers()` 元编程注册 3 个 handler；`agent_run` 端到端（3s/2 步）；jobs + worker 队列。
- **C. pg_agent_poml.sql — 11/11 通过**（C1 在 pgembed；C2–C4 在 brew PG + libxml）
  模板引擎 vars/for/if；`poml_render <table>` 数据组件（真实查库渲染 Markdown 表格、失败优雅降级）；
  `render_template('agent_system')`；`<tools/>` 元编程扫描；`agent_run_poml` 端到端（3s/2 步）。

## 发现的 bug（补丁见 `setup_db.py` PATCHES，源文件未改动）

| # | 文件 | 问题 | 后果 | 修复 |
|---|---|---|---|---|
| 1 | fixed L181 | PG 正则无 `\b` 词边界（静默永不匹配） | 所有 SELECT 走 dml 分支：agent 拿不到数据死循环、context 任务全 ERROR | `\b` → `\M` |
| 2 | fixed L633 | worker 传随机 `p_run_id` 触发"恢复"路径 | agent_run job 必报 "run_id 不存在" | 传 `v_job.run_id`（NULL 即新建） |
| 3 | functional/poml | PG17 中 `'fn(args)'::regproc` 无法定位带参函数（内置函数同败） | `sql_retry('http_call_llm(jsonb)'::regproc, ...)` 直接报错 | `::regproc` → `::regprocedure` |
| 4 | functional L195 | `jsonb \|\|` 对 object 是合并而非拼接 | system 消息被 user 覆盖 → LLM 收不到 system prompt → DeepSeek 400（json_object 模式要求 prompt 含 "json"） | 前两条消息用 `jsonb_build_array` 包裹 |
| 5 | poml P1 | PG `regexp_match` 返回捕获组数组（1-based，无整体匹配），代码用了 `m[0]`（JS/Python 习惯）→ 恒为 NULL → `replace(p_src, NULL, ...)` 返回 NULL | `expand_vars/for/if` 三个模板函数全部返回 NULL | 正则外包一层捕获组，`m[1]`=整体匹配，其余顺移 |

其中 #1、#5 在任何 PG 版本上都会复现（非 pgembed 特有）；#3 是 PG17 行为（早期版本 `::regproc` 曾接受带参文本）。

## 环境限制

- pgembed 的 PostgreSQL 二进制未编译 libxml → `xmlparse`/`xpath` 不可用 → POML 渲染层（P2–P4）在 pgembed 上无法运行，需带 libxml 的 PG（brew 版 17.11 验证通过）。
- pgembed 不含 `uuid-ossp`（fixed.sql 未实际使用，仅加载时报一条 ERROR，不影响）。

## 文件

- `server.py` — pgembed 实例管理（start/stop/status/uri）
- `setup_db.py` — 建库 + 加载 SQL + 应用补丁（幂等）
- `run_tests.py` — A/B/C1 测试套件（含 DeepSeek 端到端）
- `test_poml_brew.py` — poml 渲染层补充测试（临时 brew PG，测完即关）
- `test_connectivity.py` — http 扩展 / DeepSeek 连通性

复跑：`uv run python v1/setup_db.py && uv run python v1/run_tests.py && uv run python v1/test_poml_brew.py`
