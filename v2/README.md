# pg-agent v2（数据分析系统）

独立库 `da_agent`，不 DROP v1 的库。

```bash
uv run python v2/setup_db.py
uv run python v2/test_data_analysis.py
```

入口：`SELECT agent_run_data_analysis('问题');`
循环：共用 `rlm_loop`，`paradigm=data_analysis` 时用 `da_system_prompt`（静态 `make_da_prompt` + workbench 工具清单），且必须先成功 SELECT 才能交卷。

## 加载顺序与部署步骤

```text
pg_agent_functional.sql      共享基础设施（jobs / rlm_vars / exec_sql_readonly / handlers）
pg_agent_rlm.sql             RLM 执行模型（rlm_loop / rlm_eval；DA 分支调 da_system_prompt）
pg_agent_workbench_core.sql  workbench_tools 注册表 + refresh/render + _wb_* 助手
pg_agent_data_analysis.sql   DA 层（make_da_prompt / da_system_prompt / 入口）
plugin_brief_query.sql       只读预览 TEMP VIEW          → 注册 1 个工具
plugin_temp_views.sql        list / columns / create / drop → 累计 5 个工具
plugin_sql_curator.sql       策展视图（创建+备注）          → 累计 6 个工具（最终门闩）
SELECT refresh_workbench_tools();   -- 每次加载/删除 plugin_*.sql 后必须执行
```

`setup_db.py` 按此顺序加载并在每个插件后 refresh、核对累计工具数；`test_data_analysis.py` 用同一顺序重载。

## Workbench 工具是会话内 SQL 函数，不是队列任务

- 六个工具（`wb_brief_query`、`wb_temp_view_list`、`wb_temp_view_columns`、
  `wb_temp_view_create`、`wb_temp_view_drop`、`wb_sql_curate`）都是
  `RETURNS jsonb` 的普通函数，模型用一条 `SELECT` 调用，经 `rlm_eval` →
  `exec_sql_readonly` 在调用者同一后端执行——TEMP VIEW 因此归属当前会话。
- 不走 `jobs` / `worker()` / `job_handler`：worker 是另一个后端，看不到会话级
  TEMP VIEW。workbench 注册表（`workbench_tools`）与队列注册表（`handlers`）
  永不相交（同一注释同时声明两个键会被 refresh 拒绝）。
- observation 外层是 `{success, data:[{<函数名>:<工具 jsonb>}], row_count}`：
  外层 `success=true` 可能包着嵌套的 `success=false`，模型必须检查嵌套对象。
- TEMP VIEW 只在 `pg_my_temp_schema()` 内解析：外部调用方只传未限定名，
  不接受 `pg_temp.` 前缀 / 点号 / 引号 / schema 限定；永久视图、temp 表、
  其他会话的对象一律不匹配。视图随连接存活，跨 run 复用（REPL 语义），
  连接池换逻辑用户前需显式清理。

## 插件文件标准（新增 plugin_<slug>.sql 时）

- 一个文件 = 一个能力，幂等可重载，声明依赖位置、加载在 workbench_core 之后。
- 每个暴露函数 `RETURNS jsonb`、`SECURITY INVOKER`，COMMENT 与定义同文件，
  形如（`llm_tool.name` 必须等于函数名，`args` 键/类型与签名严格一致）：

  ```json
  {"workbench_plugin":"plugin_<slug>",
   "llm_tool":{"name":"wb_<fn>","description":"单行","args":{"p_x":"text"},
               "returns":"jsonb","session_scope":"current_session",
               "capability":"read_only|temp_view_mutation"}}
  ```

- 错误统一结构化：`{success:false, Type:"WORKBENCH_ERROR", Phase:..., Problem:..., Solution:...}`。
- 变更能力（`temp_view_mutation`）只允许改动当前会话 `pg_temp`；SQL 入参必须经
  共享校验器（`_wb_validate_select_sql`：单条 SELECT/WITH、无分号/注释/DML）；
  标识符一律 `format('%I')`。注意外层 `exec_sql_readonly` 黑名单扫描整段文本，
  SQL 字符串里的独立黑名单词（如 'set'）仍会被外层误拒（已知限制）。
- `wb_sql_curate` 委托 `wb_temp_view_create`（不复制校验器，上限更严：8000 字符），
  备注落为视图 COMMENT（`wb_temp_view_list` 可见）；create+COMMENT 同一子事务，
  备注失败则连替换一起回滚。省略/NULL/纯空白 `p_note` = 替换视图并清除备注。

## `da_*` 是遗留兼容函数

`da_list_tables` / `da_show_create` / `da_sample` 保持原签名可直调，但已从
canonical prompt 移除，不带 `workbench_plugin` 元数据、不出现在工具清单；
主发现路径是 `information_schema` / `pg_catalog`。
