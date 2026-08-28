# pg-agent data_analysis 里程碑测试

日期：2026-08-22（Batch C 收尾）· 环境：macOS · LLM：DeepSeek `deepseek-chat`
标签：**窄 PostgreSQL data-analysis 里程碑**，不是 InfiniSynapse 协议兼容。

## 范围

- 与 v1 隔离：库名 `da_agent`，文件在 `v2/`。
- 加载（七文件栈）：`pg_agent_functional.sql` → `pg_agent_rlm.sql` →
  `pg_agent_workbench_core.sql` → `pg_agent_data_analysis.sql` →
  `plugin_brief_query.sql` → `plugin_temp_views.sql` → `plugin_sql_curator.sql`，
  每个插件加载后 `refresh_workbench_tools()`（1 → 5 → **6 累计，最终门闩**）。
- 最终安装 6 个 workbench 工具：`wb_brief_query`、`wb_temp_view_list`、
  `wb_temp_view_columns`、`wb_temp_view_create`、`wb_temp_view_drop`、`wb_sql_curate`。
- 工具是当前会话 SQL 函数（一条 `SELECT` 调用，`rlm_eval` 同后端执行），
  不走 `jobs`/`worker()`；注册表 `workbench_tools` 与队列 `handlers` 不相交。
- 入口与 SQL 守卫不变：`agent_run_data_analysis` → 共用 `rlm_loop`（DA 分支
  `da_system_prompt` = 静态 prompt + 渲染工具清单）→ `rlm_eval` → `exec_sql_readonly`；
  运行时拒绝「未成功 SELECT 就 final_answer」。

## 结果

`uv run python v2/setup_db.py && uv run python v2/test_data_analysis.py` → **80/80 通过**。

| 组 | 内容 |
|---|---|
| W0–W2 | refresh=6；注册表 6 工具；渲染 read_only 在前顺序确定（curator 居 mutation 组首）；探针（合法注册 / job_handler 互斥 / 畸形 JSON / 同名重载）失败均回滚保留旧注册表；`refresh_handlers` 后 `handlers` 无 `wb_*`；`da_system_prompt` 附 6 工具清单且 `make_da_prompt` 不再广告 `da_*`；`rlm_loop` DA 分支只调 `da_system_prompt` |
| W4 | brief_query：宿主 TEMP VIEW 预览（列序/行数/截断探测/空视图/p_limit 边界）；非法名 Validation、缺视图 Resolution |
| W5 | list/columns 只读本会话；temp 表/永久视图不匹配；双连接会话隔离（B 看不到 A 的视图，反之亦然） |
| W6 | create/drop 生命周期：SELECT/WITH 创建、覆盖/不覆盖、校验器拒绝（分号/注释/DML/DML-CTE/INTO/SET/首 token/非法名/NULL/超长）、CREATE VIEW 定义错误、不兼容替换保留原视图、temp 表同名冲突、受限 drop、重复 drop 非静默；`rlm_eval` 外层仍拒原生 CREATE，合法 `wb_*` 调用经 eval 成功（外层+嵌套双 success）；外层黑名单对字面量独立词（'set'）误报为文档化限制；全程无永久对象增减 |
| W7 | curator：curate 成功（view/replaced/note/columns，list 可见备注）；重述替换+备注更新；省略/纯空白 `p_note` = 全量重述并清备注；备注 1001 字符先拒后改；非法 SQL 透传 create 的结构化错误且视图未动；8000 上限（>8000 拒、=8000 收，生命周期工具收同一段 8008 SQL）；非法名 Validation；**原子性**（event trigger 阻断 COMMENT → 子事务整体回滚：原定义/原备注保留，返回 Execution 错误；触发器移除后重试成功） |
| F1–F3 | 空 question 抛错；`da_*` 遗留直调兼容；DELETE/DROP/原生 CREATE 仍被拒且错误包 Type/Phase/Problem/Solution |
| M | mock `http_call_llm`（同签名 CREATE OR REPLACE + 队列临时表）确定性序列：插件 SQL → final（步骤序列 llm,tool,llm,final；tool 步骤 code 即 wb 调用；外层/嵌套双 success）；过早 final 被门闩拒（Finalization 反馈、无 final 步、跑满步数）；失败 SQL 的 observation 不开作答门（外层 success=false、无 final）；finally 恢复真实 `http_call_llm`（M4 断言，stub 不跨 SQL 重载/refresh_handlers 存续） |
| F4 | DeepSeek：paradigm/depth 正确；≥1 步 tool；**grounding 按嵌套判定**（code 命中 `da_sales_fixture` 且外层 success=true 且 data 内无嵌套 success=false——外层 true 包嵌套 false 不算通过）；final 存在；答案含 700；无 child run |
| F5 | 同一连接第二次 run_id 不串；grounding 同上；答案含 250 |

## 已知限制（记录在案）

- 直接经 `SELECT` 函数改 TEMP VIEW 是显式能力边界：由插件校验器
  （单条 SELECT/WITH、拒分号/注释/DML/INTO/FOR + `CREATE VIEW` 自身校验）把守，
  `SECURITY INVOKER`、仅当前会话 `pg_temp`、无 CASCADE——不是完备沙箱
  （允许的 SELECT 仍可调用有副作用的函数）。
- 外层 `exec_sql_readonly` 黑名单扫描整段文本（含字符串字面量），SQL 里的独立
  黑名单词会误拒（W6n 回归覆盖）；这是既有执行器限制，未在本工作内放宽。
- TEMP VIEW 随连接存活、跨 run 复用（REPL 语义）；连接池换逻辑用户前须显式清理。

## 证据边界

- 证明：六工具注册表/渲染/会话隔离/校验器/生命周期/curator 原子性；mock 序列下
  门闩行为；DeepSeek 查真实表、答案来自行、grounding 到嵌套成功、不 spawn。
- 未证明：InfiniSQL、SSE、delegate 聚合、`agent_rlm` 库同入口、多角色权限边界。
