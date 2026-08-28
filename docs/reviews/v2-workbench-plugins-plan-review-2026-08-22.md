# 评审:v2 Workbench Plugins 计划 vs Oracle 导出基线

- 评审对象:`docs/plans/v2-workbench-plugins-2026-08-22.md`
- 基线:`prompt-exports/oracle-plan-2026-08-22-210600-v2-workbench-plugins-0e65.md` 中 `# 1. Summary` 起的生成计划部分(导出开头的 composed prompt / 选择文件清单仅作背景,不算计划内容)
- 核查方式:对计划正文与导出正文做逐字 diff;对承重引用逐一读取 `v2/pg_agent_functional.sql`、`v2/pg_agent_rlm.sql`、`v2/pg_agent_data_analysis.sql`、`v2/setup_db.py`、`v2/test_data_analysis.py` 现行代码验证

## Context / Scope

计划目标:仅升级 v2(`da_agent`),以"每次一个 SQL 插件文件 + COMMENT/注册表/prompt 标准"扩展 Postgres 数据分析工作台,不经过 `jobs`/`worker()`/`job_handler`。本评审只覆盖任务指定的五类问题,不重写计划、不扩大范围。

## Findings

### 1. 导出内容在计划中的保真度

**结论:零丢失、零弱化。** 计划第 42 行(`# 1. Summary`)起的正文与导出第 111 行起的生成计划**逐字节一致**(diff 为空)。导出前言(`<ambiguities>`)中的实现要点也均被生成计划吸收:

- 黑名单 `\m<kw>\M` 全文匹配(含字符串字面量)、`wb_temp_view_create` 因下划线是词字符而通过 `\m` 边界 → 已进入计划 §2.4、§5.2,与代码一致(`v2/pg_agent_functional.sql:271-275`);
- F0d 钉死 `make_da_prompt(50)` 文本、`da_system_prompt` 仅被 F4g 使用 → 已进入 §3.3、测试改动清单。

计划唯一的新增内容是前置的工作项索引(W1–W8)。索引总体忠实,但 **W3 的依赖列("W1–W2 + plugins as they land")与规范正文相矛盾**,见 2.1。

### 2. 欠规格接缝、矛盾、错误引用

**2.1 实施顺序内部矛盾(高):loader 全量扩展先于插件文件存在。**
§6 步骤 3 要求把 `setup_db.py`/`test_data_analysis.py` 的 `SQL_FILES` 一次性扩到含全部三个插件文件的七文件栈,并"fail setup if … the registered count is not six"(§4 Modify `setup_db.py`);但插件文件到步骤 4–7 才逐个创建。按 §6 字面顺序执行,步骤 3 的 `ON_ERROR_STOP=1` 加载必然失败(文件不存在),六计数门也不可能通过。W3 行的"plugins as they land"暗示渐进扩展,与规范正文"full ordered stack + count six"不一致。**需要裁决**:要么 loader 随每个插件落地渐进扩展、六计数门移到步骤 7 之后作为终检;要么步骤 3 整体后移。这直接影响 W3 的排期位置。

**2.2 `refresh_workbench_tools()` 重建机制未指定(中):TRUNCATE vs DELETE。**
§3.10 声称"Concurrent refreshes serialize on the registry table lock"。该性质只有用 `TRUNCATE`(ACCESS EXCLUSIVE 锁,先例正是 `refresh_handlers()` 的 `TRUNCATE handlers`,`v2/pg_agent_functional.sql:315`)才成立;用 `DELETE + INSERT` 则并发 refresh 不串行化,可能产生重复键错误或交错结果。规范从未写明用哪种。应显式规定沿用 `TRUNCATE` 先例(TRUNCATE 可事务回滚,与"statement-atomic、失败保留旧注册表"的要求兼容)。

**2.3 `regprocedure` 的过载理由自相矛盾(低)。**
§3.2 说选 `regprocedure` 而非 `regproc` 是因为"may contain overloaded functions",但同节规定 `tool_name`(= `proname`)为 PRIMARY KEY、`llm_tool.name` 必须等于 `proname`、重复 `tool_name` 中止 refresh——即同名过载**不可能**同时注册。`regprocedure` 本身仍是对的选择,但理由应改为:精确到参数类型的函数身份、避免同名函数被替换重建后 OID 漂移导致的误解析。

**2.4 curator 原子性只有目标、没有机制(中)。**
§3.7 要求"create/replace 与 note 更新对调用者原子;note 失败时新视图不得残留",且"委托 `wb_temp_view_create()`"。但按 §3.4 工具结果标准,`wb_temp_view_create()` 会**吞掉异常并返回 jsonb 错误**(仿 `da_sample`/`exec_sql_readonly` 先例,`v2/pg_agent_data_analysis.sql:73-88`、`v2/pg_agent_functional.sql:277-285`),不会向 curator 抛异常。因此 curator 无法靠异常传播自动回滚 delegate 已完成的 DDL。规范必须写明机制:curator 把「delegate 调用 + `COMMENT ON`」包进自己的 `BEGIN…EXCEPTION` 子事务;delegate 返回错误 jsonb 时直接透传(无 DDL 无需回滚);DDL 成功后 note 失败时主动 `RAISE` 使子事务回滚,再在外层捕获转为结构化错误。这是 W7 的验收关键路径("Verify atomic failure behavior"),目前不可直接实现。

**2.5 行号引用漂移(低,不误导但需注意)。**
抽查发现若干引用与现行代码有小幅偏移:`handlers` 表实际在 `v2/pg_agent_functional.sql:303-306`(文中 299-302);`rlm_loop` DA prompt 分支实际 `v2/pg_agent_rlm.sql:421-426`(文中 419-424);观察写入/emit 实际 `:489-493`(文中 487-509);`v_got_q` 门实际为 `:456-474`(finalization 拒绝)加 `:485-487`(成功置位)(文中 468-486)。所有引用语义均正确,实现时按符号定位即可,不要按行号。

### 3. 被代码/PostgreSQL 行为反驳、或有更简替代的内容

**3.1 EXPLAIN 计划节点检查的承重理由不成立(高)——PostgreSQL 的 `CREATE VIEW` 自身校验完全覆盖该场景。**
§3.6 validator 步骤 6–7 要求用 `EXPLAIN (FORMAT JSON, COSTS false)` 做 planning-only 解析并检查 `ModifyTable`/`CreateTableAs` 节点,声称"specifically covers data-modifying CTEs under a top-level WITH"。三点反驳:

1. 在这条路径上,`p_select_sql` 唯一被执行的方式就是作为视图定义,而 PostgreSQL 的 `CREATE VIEW` 本身就硬性拒绝数据修改 CTE(`views must not contain data-modifying statements in WITH`)和 `SELECT INTO`(`views must not contain SELECT INTO`)。DML CTE 在任何情况下都不会被执行,EXPLAIN 层对该威胁是冗余的。
2. validator 步骤 4 已强制首 token 为 `SELECT`/`WITH`,`CreateTableAs` 节点不可能出现——列举它说明威胁模型没对准。
3. "planning-only"并非零执行:EXPLAIN(无 ANALYZE)在常量折叠时仍可能求值标记为 IMMUTABLE 的函数。

**精确修正**:删除步骤 6–7,把 `CREATE [OR REPLACE] TEMP VIEW` 自身的解析/校验错误捕获为 `Phase=Validation` 的结构化错误(更简单,少一次完整 parse+plan);若坚持保留 EXPLAIN 层,则必须改标为"纵深防御",删去"specifically covers DML CTEs"的承重表述,并在 W6(计划中唯一的 L 号工作项,主要成本就是这个 validator)重新估量。字面 token 黑名单(步骤 1–5)照旧保留。

**3.2 `GRANT SELECT ON workbench_tools`(§3.2)在本仓库无对象可授(低)。**
整个 v2 栈运行在 pgembed 嵌入式单角色环境(`server.py`、`v2/setup_db.py` 全程无角色管理)。授权步骤不是错,但任务不需要;应标注为"未来引入多角色时再补",避免实现者去发明不存在的角色。

**3.3 F0d 的修改量被高估(低)。**
现行 F0d(`v2/test_data_analysis.py:139-141`)断言的是 `information_schema`、"必须先成功查库"、"禁止 rlm_spawn"三个子串,**并不断言 `da_*` 存在**。因此从 `make_da_prompt` 删除 da_* 广告不会破坏现有 F0d;计划所谓"Update F0d"实为**新增**一条负向断言(`'da_list_tables' not in da`),不是修复被破坏的断言。对排期无影响,但实现者应知道现有断言原样可过。

### 4. 双方(导出与计划)均缺失的需求、边界与依赖

**4.1 确定性 mock LLM 机制完全未指定(高)——这是 W8/§6 步骤 8 的地基。**
计划多处要求"deterministic mocked-provider tests / test-only LLM response sequence",但两份文档都没说怎么 mock。现行测试通过 session GUC(`SET openai.api_uri/api_key/model`,`v2/test_data_analysis.py:61-63`)直连 DeepSeek。两条可行路线,选择影响测试架构:
- **本地 HTTP stub**:把 `openai.api_uri` 指向本地脚本化服务(返回 OpenAI 格式的预置响应序列)。不动数据库对象,但测试脚本要起/管一个本地服务。
- **函数覆盖**:测试库内 `CREATE OR REPLACE FUNCTION http_call_llm(jsonb)` 返回预置序列(注意 `rlm_loop` 经 `sql_retry('http_call_llm(jsonb)'::regprocedure, …)` 调用,`v2/pg_agent_rlm.sql:436`,签名必须保持)。必须在 DeepSeek 冒烟测试(F4/F5)之前恢复原函数——重载 `pg_agent_functional.sql` 即可恢复,但顺序必须写进测试设计。

这个决定应提前与 §6 步骤 3 一起裁定,而不是拖到步骤 8。

**4.2 工具结果的观察信封嵌套形状没有写进 prompt/测试合同(中)。**
`exec_sql_readonly` 把任何提交语句包装为 `SELECT jsonb_agg(t) FROM (%s LIMIT %s) t`(`v2/pg_agent_functional.sql:278-282`),因此模型看到的 `SELECT wb_brief_query('v')` 观察是:

```json
{"success": true, "data": [{"wb_brief_query": {"success": false, "Type": "WORKBENCH_ERROR", "...": "..."}}], "row_count": 1}
```

§3.11 末段说"prompt 必须指示模型检查嵌套结果",但 §3.2 的渲染段要求清单里没有任何一条要求说明这个 `data[0].<函数名>` 信封结构——模型不知道嵌套在哪里。另外,现有 grounding 断言惯用 `observation NOT ILIKE '%"success": false%'`(`v2/test_data_analysis.py:205-212`),对"外层成功 + 嵌套插件失败"的观察会误判——新工作台测试沿用该模式时必须区分外层与嵌套 `success`。两处都应写入 §3.2 渲染要求和 §7.5 测试设计。

**4.3 畸形注释探针会击穿 `refresh_handlers()` 与后续 SQL reload(中)。**
`refresh_handlers()` 对**所有** `public` 函数中注释以 `{` 开头者做 `::jsonb` 强转(`v2/pg_agent_functional.sql:322-323`),且 `pg_agent_functional.sql:383` 与 `pg_agent_rlm.sql:838` 在**文件加载时**就执行 `SELECT refresh_handlers()`。§7.2 的"malformed workbench comment aborts refresh"探针如果留下一个 `{` 开头的非法 JSON 注释,不仅 `refresh_workbench_tools()` 失败,`refresh_handlers()` 及此后任何一次 functional/rlm 文件重载都会失败。计划只引用了 v1 的注释恢复先例(`v1/run_tests.py:262-286`),没有点明这个跨注册表的共享故障面。测试必须把注释恢复放进 `finally`,且探针存续期间不得触发 handlers 刷新或 SQL 重载。

**4.4 未定义的边缘输入(低)。**
- `wb_brief_query(p_limit)`:规定了 0/负数/超上限,未定义显式 `NULL`(`SELECT wb_brief_query('v', NULL)`)。建议:NULL → 验证错误或回落默认 20,择一写死。
- `pg_my_temp_schema()` 在会话从未创建任何临时对象时返回 `0`:`_wb_temp_view_oid()` 应返回 NULL(自然的 join 空集即可),`wb_temp_view_list()` 应返回空数组——行为大概率自然正确,但应写入合同并加测试,避免实现者对 oid 0 做特判时出错。

**4.5 `wb_sql_curate` 的 note 语义有隐性破坏面(低)。**
`p_note DEFAULT NULL` 且"null 或空白 = 清空 note"意味着:**不带 note 的重复 curate 会清掉之前设置的 note**。若这是有意的("每次 curate 必须完整重述文档"),应明说;若无意,现签名无法区分"省略=保留"与"显式清空",需要改设计(如保留哨兵值或去掉 DEFAULT)。

### 5. 答案会实质改变设计或实施顺序的问题

1. **mock LLM 用 HTTP stub 还是函数覆盖?**(决定 W8 结构与测试脚本形态;建议与步骤 3 一起定,见 4.1)
2. **六工具计数门放在哪一步?**(决定 §6 步骤 3 与 W3 的位置;见 2.1)
3. **EXPLAIN 校验层删还是降级为纵深防御?**(W6 被标 L 的主要成本来源;见 3.1)
4. **refresh 重建用 TRUNCATE 还是 DELETE?**(决定并发语义与"串行化"声明是否成立;见 2.2)
5. **不带 note 的重复 curate 清空已有 note 是否有意?**(决定 `wb_sql_curate` 签名;见 4.5)

## Recommendations

按影响排序:

1. **裁决实施顺序矛盾(2.1)**:推荐 loader 渐进扩展 + 终检式六计数门;同步修正 §6 步骤 3 与 §4 `setup_db.py` 条目的措辞。
2. **删除或降级 EXPLAIN 校验层(3.1)**:推荐删除,改为捕获 `CREATE VIEW` 自身校验错误并归入 `Phase=Validation`;同步下调 W6 估量。
3. **在步骤 3 之前定下 mock LLM 机制(4.1)**:推荐函数覆盖方案(无进程管理负担),并把"覆盖→确定性测试→重载 functional.sql 恢复→DeepSeek 冒烟"的顺序写进 W8。
4. **补写 curator 原子性机制(2.4)** 与 **refresh 的 TRUNCATE 语义(2.2)** 到规范正文。
5. **把观察信封结构写进 §3.2 渲染要求与 §7.5 断言设计(4.2)**;新 grounding 断言区分外层/嵌套 `success`。
6. **在 §7.2 测试设计中注明畸形注释探针的 `finally` 恢复义务与 `refresh_handlers` 共享故障面(4.3)**。
7. 低优先:修正 `regprocedure` 理由(2.3)、`GRANT` 步骤标注(3.2)、F0d 措辞(3.3)、`p_limit NULL` 与 temp-schema-oid-0 合同(4.4)、note 清空语义(4.5)、按符号而非行号定位引用(2.5)。

以上不包含任何"因内容具体/低层而删除"的建议;计划中经核查准确的低层细节(黑名单词边界行为、观察截断与 `last_obs` 全文保留、`v_got_q` 门只看外层成功、TEMP VIEW 跨 run 存续等)均与代码一致,应原样保留。
