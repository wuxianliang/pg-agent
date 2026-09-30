# Postgres-Native JAZ V15 开发文档

本文是 pg-agent v15 的行为合同：在 PostgreSQL 内实现 JAZ 的 invoke 状态机。模型书写受约束的 SQL 语句列表；worker 只在事务外做 LLM I/O，并做语句切分；每一次权威转移都是 SQL。

**设计修订。** rev 11。

**修订说明。** 本修订吸收 R-B1–R-B19：`SECURITY DEFINER` 函数体内禁止切换角色；scratch 只授予 schema 权限，终态由属主直接 `DROP SCHEMA … CASCADE`；工具改为 `v15_tool_<name>` 的 definer；`v15_reclaim_expired()` 同时收回没有存活 attempt 的过期 invoke 租约；子 invoke 的每一次提交类终态都在同一事务送达。
本修订吸收 R-C1–R-C18，来源 `docs/references/v15-rev4-rulings.md`。
本修订吸收 R-D1–R-D22，来源 `docs/references/v15-rev5-rulings.md`。
本修订吸收 R-E1–R-E10，来源 `docs/references/v15-rev6-rulings.md`。
本修订吸收 R-F1–R-F6，来源 `docs/references/v15-rev7-rulings.md`。
本修订吸收 R-G1–R-G2，来源 `docs/references/v15-rev8-rulings.md`。
本修订把真实 provider 定为 worker 侧 opt-in。attempt 终态集合不变。新增 `V15_PROVIDER_REJECTED` / `P1539`。`llm` 键集不变。
本修订追加 `V15_VALIDATION_FAILED` / `P1540`。`repl_exec/complete` 可以把候选 `return` 改成 `continue`，或改成带该码的 `raise`。计数接受函数不改名。`v15_io_sqlstate` 不映射这个码。
本修订追加 D2 轨迹回放：`V15_REPLAY_DIVERGED` / `P1541` 与 `V15_REPLAY_MISSING` / `P1542`。二者是回滚类异常，不是 invoke 终态码，不进入 §9.5 四个可保留 abort 码。合运行时是十二个文件全部加载的库，库名 `agent_v15_replay`。不启用 `supply_llm_response`。摘要复用 `llm_requests.logical_digest`。
本修订追加 stage 13 外部工具延续：`bind_tool` / `tool_wait`、`tool_requests` 与 `tool_attempts`（本修订对「其后 stage 不得加表」的**唯一例外**），以及 `V15_TOOL_BINDING` / `P1543`、`V15_TOOL_FAILED` / `P1544`、`V15_TOOL_EXHAUSTED` / `P1545`。合运行时迁到十三个文件，库名 `agent_v15_tools`。`P1546`–`P1548` 仍未分配。

**权威。** 本文是 v15 实现与 gate 的唯一行为权威。K1–K6、两轮 oracle 的 R1–R5（`docs/references/v15-oracle-round1.md`、`docs/references/v15-oracle-round2.md`，裁定组 `54BBD0FD-1DC4-44CE-9500-E4BF8C6B0E8B`）、rev 2 的 R-A1–R-A29、rev 3 的 R-B1–R-B19 以及 rev 4 的 R-C1–R-C18 rev 5 的 R-D1–R-D22 rev 6 的 R-E1–R-E10 以及 rev 7 的 R-F1–R-F6、rev 8 的 R-G1–R-G2 只作为来源保留。裁定已全部吸收进本文，本文是唯一权威。论文的两条性质，以及「外部 I/O 不在数据库事务内；unknown 不是成功」这条 v8 规则，同为权威。jaz 的 Python REPL 沙箱、Jinja 模板、`__history__` 的属性措辞、`jaz-evals` 提示词、v8 的 `sessions` / `effect_requests` / 插件世代、v13 的 stage 布局，都不是 v15 行为权威（完整非权威清单在 §16）。

**环境基线。** PostgreSQL **18.4**。实现树为 `v15/`，与 v8、v13 的 schema、加载序和库互不共用。合运行时只存在于 `v15/load.py` 的 `SQL_LOAD_ORDER` 全部加载完成之后。gate 串行运行。每个 stage 的 `setup_db.py` 先 `DROP DATABASE … WITH (FORCE)` 每一个`starts_with(datname, 'agent_v15_')` 的库，再重建集群全局的 `v15_*` 角色，然后 `CREATE DATABASE agent_v15_<stage>` 并累计加载到该 stage。角色不靠 SQL 文件里的 `IF NOT EXISTS`（§2、§15）。SQL 是普通 `CREATE`，不用 `IF NOT EXISTS`。gate 为 `uv run python v15/<stage>/test_*.py`，退出码 0 为通过。gate（`v15/**/test_*.py`）只用 FakeLLM / FakeTool，MUST NOT 打开网络套接字。`v15/provider/smoke.py` 在显式 `--real-provider-smoke` 下可以打开套接字，且不是合运行时证明（§0.0）。

**引用指纹。** 身份是下列路径在本文件冻结时的仓库文本，外加已吸收的裁定编号。本轮不另造字节摘要。

- `docs/references/jaz-paper-harness-as-a-language.md`
- jaz 参考核心：`invoke.py`、`_agent.py`、`config.py`、`scope.py`、`inputs.py`、`hooks/`（dispatcher、effects、blackboard、events）、`repl/`、`protocol/code_only.py`
- `docs/designs/v8-dev.md`（文风样本）
- `AGENTS.md`、`v8/load.py`、`v13/load.py`（累计加载约定）
- `docs/references/v15-oracle-round1.md`
- `docs/references/v15-oracle-round2.md`
- `docs/references/v15-oracle-review1.md`
- `docs/references/v15-rev4-rulings.md`
- `docs/references/v15-rev5-rulings.md`
- `docs/references/v15-rev6-rulings.md`
- `docs/references/v15-rev7-rulings.md`
- `docs/references/v15-rev8-rulings.md`

内核 schema 为 `v15`，模型面 schema 为 `jaz`。下文未写出 schema 的表名均在 `v15`。

## 0. 不可妥协的不变量

0. **合运行时。** 合同是本文在 PostgreSQL 18.4 上的行为。一个库只有在 `SQL_LOAD_ORDER` 全部加载之后才是合运行时。前缀加载只是 gate 脚手架，MUST NOT 作为交付运行时。gate（`v15/**/test_*.py`）MUST 只用 FakeLLM，MUST NOT 打开网络套接字。`v15/provider/smoke.py` 在显式 `--real-provider-smoke` 下可以打开套接字，且当时没有打开的数据库事务；它不是合运行时证明。

1. **版本隔离。** v15 MUST 只使用 `v15/` 树与 `v15` / `jaz` schema。MUST NOT 修改 v8 或 v13 的 SQL、加载序、冻结规格或持久化数据。

2. **两条论文性质与同迭代消费。** 模型 SQL MUST 能在 `jaz.bind_invoke` 处挂起当前迭代，并在**同一父迭代的下一条已生成语句**里用 `jaz.var` 读到子结果。父 invoke 为此 MUST NOT 再发一次 LLM 调用。模型在提示中看到的显式输入、scope 名、工具结果、本 invoke 已结束的历史、按祖先 id 授予的祖先历史，以及当前迭代已结算 attempt 的冻结请求（`jaz.request_messages`，含持久与瞬态 hook 消息），MUST 都能被模型 SQL 读取。

3. **行是权威。** `invoke_events` 只追加。同一 `invoke_id` 的 `seq` 连续、单调且唯一。`invokes`、`iterations`、`statements`、`llm_requests`、`llm_attempts` 与租约是控制面。worker 进程内存、后端本地 GUC、临时表和预备语句 MUST NOT 当作可恢复状态。

4. **事务内禁止外部 I/O。** LLM 调用 MUST 只发生在租赁事务提交之后、结算事务开始之前。任何 SQL 函数 MUST NOT 调用 FakeLLM 或 provider，也 MUST NOT 以循环代替 worker。`v15_run_until_quiescent` 是 worker 里的 Python。SQL 只提供只读扫描 `v15_next_runnable()`。worker 在已经打开的转移事务里渲染提示词是本地 CPU，不是 provider I/O。

5. **栅栏。** 一次 claim 颁发一个 fence。陈旧 fence 上的 settle、reclaim 或执行推进 MUST 抛出 `V15_STALE_FENCE`，并且 MUST NOT 修改控制态。invoke 租约、LLM attempt 与语句执行各自使用独立 fence。旧 fence 永远不能覆盖新 fence。attempt 的 `fence` 是该行自己的计数，新插入的行从 1 起，不是全局计数器。挂起本身不加 invoke 栅栏；栅栏未变时，旧持有者再调用得到的是 `V15_INVALID_TRANSITION`，不是 `V15_STALE_FENCE`。

6. **unknown attempt。** `v15_reclaim_expired()` 无参数。它终结过期 attempt，并按该行存放的预留记账。`call_started = true` 的过期行置为终态 `unknown`；`call_started = false` 的过期行置为终态 `failed`。回收事务 MUST NOT 插入新 attempt，MUST NOT 调用 `v15_on_phase`，MUST NOT 调用 FakeLLM。

同一函数还扫描 `status = leased` 且 `lease_until <= clock_timestamp()`、并且没有存活 `leased` attempt 的 invoke：`fence` 加 1，租约清空，状态改为 `runnable`，并做语句修理（§4.10）。终结 attempt 之后已经没有存活 `leased` attempt 的 invoke 走同一条收回，不必再等下一轮。

对 `unknown`、`failed` 或 `settled` 行调用 `v15_settle_llm` MUST 抛出 `V15_ATTEMPT_NOT_SETTLEABLE`，MUST NOT 把响应写入转录。过期行 MUST NOT 被改写成另一种终态。新的 attempt 只由 `v15_begin_llm` 插在同一 `llm_requests` 上。`llm_query` span 已经打开时，这次插入是重试：不发 `enter` / `send`，预留数量复制上一 attempt 存放的 `reserved_calls` 与 `reserved_cost`。span 未打开时才发 `enter` / `send`。

worker MUST 只在**自己**刚刚把该行的 `call_started` 从 false 提交为 true 之后调用 FakeLLM 或 provider。遇到本进程没有置位的 `call_started = true`，留给过期回收，MUST NOT 再次调用该 attempt。provider 调用一旦开始，该 attempt 的终态只允许 `settled` 或 `unknown`。`failed` 只允许出现在调用尚未开始的 attempt 上。

`unknown` 的写入者是 `v15_reclaim_expired`、`v15_provider_abandon` 与 `v15_provider_reject_started`。后两者的记账公式与已 `call_started` 的回收相同（§4.5.4、§4.5.5）。`v15_provider_reject_unstarted` 只在 `call_started = false` 时把 attempt 写成 `failed`，并结束 invoke。这三只函数都不调用 provider。`v15_provider_abandon` 不调用 `v15_on_phase`。两个 reject 走 `v15_io_terminal`。

7. **语句原子性。** 一条模型语句的 scratch 写入、binding 效果与 `statements.status` 在同一事务里提交。`status = done` 的语句 MUST NOT 再次执行。失败迭代里已经提交的前序语句保持提交；失败语句回滚；其后语句不执行；该迭代成为一次可恢复的 `Continue`。本条不适用于 LLM attempt（见不变量 6）。已存放的行是否还能执行，只看 `status = pending AND error IS NULL`。`reject_code` 只出现在结算入参里，不是列。分类器拒绝的行在结算时已经是 `failed` 且 `error` 非空，那时还没有任何语句事务。

8. **挂起在语句之间。** 挂起是同一迭代内、语句与语句之间的延续，不是 SQL 表达式内部的挂起。`bind_invoke` 的 jsonb 实参来自该语句已存放的 `arg_sql`：worker 以 `v15_repl` 做 `SELECT (<arg_sql>)`，再把求值结果交给 `v15_suspend_for_child`。SQL MUST NOT 重新解析助手原文。下一条父语句看见绑定。同一条助手消息里的规范尾委托是：`SELECT jaz.bind_invoke('<ident>', <jsonb-expr>);` 随后 `SELECT jaz."return"(jaz.var('<ident>'));`。

`v15_suspend_for_child` 插入子行之后，MUST 立刻把父写成 bind-wait（语句仍为 `running` 且写入 `child_invoke_id`，迭代 `suspended`，invoke `suspended`，租约清空），然后才跑子的 open 守卫与 `invoke/enter`。子停在 `runnable` 时只建立 §4.8 的结构前置（父 bind-wait）。同事务送达只发生在子已 `completed`、`failed` 或 `aborted` 时；子在这次 open 里进入终态才直接走 §4.8（§4.7）。suspend 捕获集是这五码：`V15_RECURSION_DISABLED`、`V15_SCOPE_CONFLICT`、`V15_INVOKE_FORM`、`V15_VALUE_INVALID`、`V15_GOVERNANCE_RAISE`（§4.7）。worker 在这条路径上若接到其中之一，MUST 回到保存点，把该语句提交为 `failed`，MUST NOT 把它留在 `pending` 上反复重试（§4.7、§4.12）。`SELECT (<arg_sql>)` 的任何错误同样回到保存点并提交 `failed`。suspend 捕获集是上述五码，与实参求值的任意错误是两句，不混写（§4.7）。

成功完成的 `jaz."return"` 或 `jaz."raise"` 结束本轮剩余程序。`v15_complete_statement` 只把 `resume_stmt` 移到语句条数。skip 的切点与唯一执行者在 §4.9：存在 `done` 的 `return`/`raise` 时 `cut` 是该语句的 `stmt_index`，不得用 `resume_stmt`。`repl_exec/complete` 对 `continue`、`return`、`raise` 三条路径都发出。把候选 `return` 收成 `continue` 的阶段效应清除 `invokes.return_value`，保留该 `return` 语句为 `done`，其后语句按 §4.9 切点保持 `skipped`，迭代以 `continue` 写历史。

9. **函数本身不产子。** `jaz.bind_invoke` 若在语句里被实际执行，MUST 抛出 `V15_INVOKE_FORM`，并且 MUST NOT 插入子 invoke。只有 `session_user = v15_worker` 时调用的 `v15_suspend_for_child` 可以创建子 invoke。该函数是 `SECURITY DEFINER`，体内 `current_user` 是 `v15_owner`，MUST NOT 用 `current_user` 识别 worker，也 MUST NOT 在体内 `SET ROLE`（不变量 20）。

10. **一个 invoke 一个租约持有者。** `status = suspended` 的 invoke MUST NOT 被 claim。同一时刻至多一个 lease owner 推进一个 invoke。v15 没有 `ainvoke`，也没有迭代内的并行 `map_invoke`。子 invoke 只在父 invoke 处于 `suspended` 时变为可 claim。持有 invoke 租约的转移必须出示与 `invokes.lease_owner` 相同的 `p_owner`（§4.2）。

11. **fatal 位。** `fatal = true`（共享池耗尽，或 hook abort 的 `fatal = true`）在同一事务把该 invoke、每一级祖先，以及这些行中仍非终态的后代标为 `aborted`。`fatal = false`（迭代上限、递归上限、`jaz."raise"`、非 fatal 的子失败、I/O attempt 上限）只结束该 invoke。父迭代成为可恢复的 `Continue`，其后的父语句不再执行。

任何提交类事务只要把子 invoke 写成 `completed`、`failed` 或 `aborted`，都必须在**同一事务**做 §4.8 的送达与 fatal 展开。这包括 `v15_begin_llm` 的迭代上限与 I/O 耗尽、阶段 abort、预算 fatal、回收驱动的关闭，以及 finish。父语句记录的码一律是 `V15_CHILD_ERROR`，只有绑定名冲突才是 `V15_DELIVERY_CONFLICT`。子行保留自己的码，父语句不得抄写它。

12. **效应代数。** 效应集合闭合。当前 phase 不接受的效应 MUST 抛出 `V15_INVALID_EFFECT`，MUST NOT 被静默跳过。预留名 `supply_llm_response`、`supply_invoke_result`、`modify_invoke_result`、`supply_exec_result`、`modify_llm_response` 对每个 channel 都是 `V15_INVALID_EFFECT`。同一 phase 内同键合成与 hook 登记顺序无关：jsonb 相等则合并；黑板写或输入添加不相等则该 phase 失败。不等的 `budget`、不等的消息载荷是回滚类 `V15_EFFECT_CONFLICT`。

hook 的 abort 可以提交。可保留的码集合闭合为 `{V15_IO_EXHAUSTED, V15_BUDGET_EXHAUSTED, V15_RECURSION_EXCEEDED, V15_ITERATION_EXCEEDED}`（§9.5）。集合外的任何码一律归一为 `V15_HOOK_ABORT`（`P1538`）。数个 abort 规范化后的码不一致时，顶层也是 `V15_HOOK_ABORT`。`fatal` 按 §9.5 在归一之后取或。MUST NOT 把只属于回滚类的码写入已提交的 `error`，也 MUST NOT 提交带 `payload.codes` 的替代 abort。非 baseline handler **抛出**的异常只记审计，不变成效应。它正常返回的非法形状、未知键或预留效应名不是这条隔离路径，阶段失败。任何 `exit` phase 都不得 `abort`，只允许黑板写（§9.4）。

带预算的那次阶段调用里，预留是第一笔落库。预留的条件更新影响 0 行时，本转移里尚未写入的 enter/send 效应一律不写，事务走 `V15_BUDGET_EXHAUSTED`。预留成功之后才是 enter/send 的唯一落库点：先写两边的非消息效应各一次，再写消息。预留 0 行或 send abort 时这些效应从未写入。黑板写仍在本 phase 全部 handler 返回并完成合成之后才应用；读者在本 phase 只看见写入前的快照，下一 phase 才看见新一代。

13. **治理清单。** `governance_manifest` 恰好一行。`max_iterations`、`max_depth`、`max_io_attempts`、`max_statement_ms` MUST 为整数且 `>= 1`。否则 `v15_open_invoke` 抛出 `V15_GOVERNANCE_MISSING`，MUST NOT 租赁 LLM attempt。调用方可以安装更紧的上限。更松的上限 MUST 抛出 `V15_GOVERNANCE_RAISE`。open 把**有效**上限安装为 baseline hook，并把有效上限的摘要写入 `invokes.manifest_digest`（§3.13、§8.5）。模型 SQL 与非 baseline hook MUST NOT 删除或改写这些行；触发器以 `V15_BASELINE_IMMUTABLE` 拒绝。这四个上限不是 config 的字段；config 对象携带它们是未知选项。

14. **授权靠 grant，不靠约定。** `v15_repl` 对内核表没有 DML，对内核转移函数没有 EXECUTE，不是 `v15_worker` 或任何 hook / tool owner 角色的成员，不能写 `exec_context`，不能把 `role` 或 `search_path` 提权。已绑定但没有 `tool_grants` 行的工具名 MUST 抛出 `V15_TOOL_UNAUTHORIZED`。`V15_TOOL_UNAUTHORIZED` 与模型语句上的权限错误只失败该语句，不把 invoke 送进终态。

15. **handler 只返回效应。** 已登记 hook MUST 为 `SECURITY DEFINER`、owner 为 `NOLOGIN` 且非超级用户、`STABLE`、语言为 SQL 或 plpgsql、`proconfig` 恰好是 `search_path=pg_catalog` 这一个元素（不得出现 `pg_temp`），并且 owner 对内核表没有 grant。登记 MUST 拒绝 `IMMUTABLE`、`VOLATILE` 与 C 语言 handler。登记时 `REVOKE ALL ON FUNCTION … FROM PUBLIC`，`EXECUTE` 只授给 `v15_owner`，且没有 `GRANT OPTION`，运行时不得再授。dispatcher 按 `regprocedure` 的 oid 调用，不查 `search_path`，体内不切换角色。每次调用前重查 owner、`provolatile`、`prosecdef`、语言、`proconfig`、规范化的 `proacl`，并核对 §3.11 的 `handler_digest`；同时重查 owner 对内核表没有权限。漂移为 `V15_HANDLER_DIGEST`。baseline handler 抛出的异常 MUST 变成 `V15_GOVERNANCE_FAULT` 并使该 phase 事务失败。预算预留的写者——phase 路径是 stage 9 的 govern 体；stage 1–8 桩路径与重试路径是 `v15_begin_llm`（同一条单次 `UPDATE`，§9.6）；`llm_messages` 在 LLM 路径只由 `v15_on_phase` 写入。`v15_begin_llm` MUST NOT 把 hook 消息再插入 `llm_messages`。

16. **配置折叠后冻结。** 有效配置按此序折叠，后者胜：base profile，然后该绝对深度的全局 depth partial，然后 propagating layer 的 `ordinal` 升序，然后本 invoke 的 local layer。`llm`、`repl`、`protocol` 整对象替换，不做字段深合并。层内缺键表示不写。`config_layers` 的 `llm` / `repl` / `protocol` 是可空列，在不在场用 `IS NOT NULL`，不用 `jsonb_exists`。depth partial 内部的键是否存在才用 `jsonb_exists`。值为 JSON `null` 算在场，但不是对象，折叠失败。折叠结果在 open 时写入 `invokes.resolved_config` 与 `config_digest`。此后对 profile 的修改 MUST NOT 重折已打开的 invoke。子 invoke 继承 `config_scope_id` 与父 invoke 上已经冻结的 propagating hook 行，不继承父的 local layer，也不继承父的 local hook，也不按子 open 当时的 layer 表再装一遍 `extra_hooks`。depth partial 内不得再含 `depth_map`。

17. **历史隔离与值域。** 模型可见值是 jsonb。`kind = scope` 的 binding 在子 open 时按值复制；`kind = input` 不向子传播。同一名字兼属 scope 与显式 input MUST 在 open 时抛出 `V15_SCOPE_CONFLICT`。`jaz.history` 是 `security_barrier` 视图，只出本 invoke 已结束的迭代；它不承诺视图内部 `ORDER BY` 会对外层查询生效，读者 MUST 写 `ORDER BY iteration`。`jaz.prior_history(uuid)` 只对自身或祖先返回行，其他 id MUST 抛出 `V15_HISTORY_SCOPE`。`jaz.request_messages` 只出当前 `exec_context` 所属迭代里、已结算 attempt 实际送出的请求，含 hook 消息。提示词描述这些关系，MUST NOT 描述名为 `__history__` 的对象。发给模型的观测文本可以截断；`repl_history.repl_output` 与 `llm_messages` MUST 保存完整文本。失败的 `continue` 迭代里，`repl_output` 是 capture 与异常块拼成的完整观测（§3.6），不是只存 capture。

18. **方言权威与规范控制形式。** 助手消息整段就是程序，解析是恒等。切分权威是 `v15/protocol/split_sql.py`，MUST 识别标准字符串、`E''` / `U&''`、标识符引号、行注释、嵌套块注释，以及任意 dollar-quote 标签。库内只存已经切分的语句行，MUST NOT 用 SQL 正则再切。规范的单独语句只有：

```text
SELECT jaz.bind_invoke('<ident>', <jsonb-expr>);
SELECT jaz."return"(<jsonb-expr>);
SELECT jaz."raise"(<text-expr>);
SELECT jaz.print(<text-expr>);
SELECT jaz.assign('<ident>', <jsonb-expr>);
```

`jaz.var` 与 `jaz.tool` 可以出现在表达式里。未加引号的 `return` / `raise` 不是规范形式，MUST 在执行前失败 `V15_INVOKE_FORM`。非规范语句里的控制名只按 §6.2 的记号流判断，并且只看字符串、注释与 dollar-quote **之外**的记号。这些名字出现在字符串或注释字面量里，不是 `V15_INVOKE_FORM`。`jaz.bind_invoke` 被实际执行时仍不产子（不变量 9）。

`DO` 不在方言内，首记号 `DO` MUST 失败 `V15_DIALECT`。语句内部的迭代只走 `WITH RECURSIVE` 的 `SELECT` 路径。`DO` 若要重新进入语言，必须换成 `session_user` 本身无权的模型连接，本版不做（V15-D25）。`CALL`、`EXECUTE`、`COPY`、显式事务控制、`SET` / `RESET` MUST 失败 `V15_DIALECT`。`CREATE FUNCTION`、`CREATE PROCEDURE`、`CREATE ROUTINE`、`CREATE EXTENSION`、`CREATE ROLE`、`CREATE DATABASE`、`CREATE EVENT TRIGGER`、`GRANT`、`REVOKE`、`COMMENT`、`SECURITY LABEL`、`VACUUM`、`REINDEX`、`CLUSTER`，以及一切 `ALTER TABLE`，MUST 失败 `V15_DDL`。模型要改表就 `DROP` 再 `CREATE`，不得依赖命令 jsonb 去辨认 `ALTER` 子句。

scratch 内、且只有这些形式，`kind` 为 `plain`、`reject_code` 为空：`CREATE TABLE`、`CREATE TABLE AS`、`SELECT INTO`、`CREATE INDEX`、`CREATE UNIQUE INDEX`、`CREATE VIEW`、`DROP TABLE`、`DROP INDEX`、`DROP VIEW`。`UNIQUE` 不是第二条语句。`TRUNCATE` 不在方言内，分类器以 `V15_DIALECT` 拒绝；清空表用 `DELETE`（§6.2）。schema 边界是事件触发器（不变量 26），不是首记号一刀切。其余 `CREATE` / `ALTER` / `DROP` 仍是 `V15_DDL`。

整段切分失败时不产生部分语句列表。worker 仍结算，且只结算一条合成的失败语句（§3.3），然后迭代 `Continue`。响应正文里的 NUL 不能进入 PostgreSQL `text`：存入前把每个 NUL 换成六字符序列 `\u0000`，该条 `reject_code` 为 `V15_VALUE_INVALID`。

19. **SQLSTATE。** 每个 `V15_*` 条件恰好一个 sqlstate，自 `P1501` 起连续分配，无空号，无同义名。本修订止于 `P1545`（`V15_TOOL_EXHAUSTED`），共 45 行。硬顶为 `P1548`。`P1546`–`P1548` 未分配，不得预占。gate MUST 按 `sqlstate` 分类。本族 MUST NOT 使用 `P0001`。码表在 §13。`P15` 是否被本安装占用，以仓库钉住的 PG 18.4 errcode 快照在设计时核对；运行时 gate 只断言 `server_version_num` 与这些自定义码能够 `RAISE`（§17）。

20. **身份。** 内核转移的授权谓词是 `session_user = v15_worker`。转移函数为 `SECURITY DEFINER` 时，体内 `current_user` 是 `v15_owner`，MUST NOT 用来识别 worker。任何 `SECURITY DEFINER` 函数体内 MUST NOT 执行 `SET ROLE`、`RESET ROLE` 或 `SET SESSION AUTHORIZATION`。PostgreSQL 在这类函数内拒绝角色切换；合同也不把切换当作实现手段。模型语句执行时 `current_user` MUST 为 `v15_repl`。这个 `SET LOCAL ROLE v15_repl` 只允许出现在 worker 事务的顶层，位于转移函数返回之后、模型语句之前，然后在语句之后 `RESET ROLE`。`jaz` 包装 MUST 拒绝 `current_user` 不是 `v15_repl` 的调用。清单写入与 hook / tool 登记 MUST 只接受 bootstrap 装载身份。

21. **attempt 上限与保守记账。** 同一 `llm_requests` 的 attempt 序号从 1 连续，MUST NOT 超过有效 `max_io_attempts`。超出则该 invoke 以 `fatal = false`、`V15_IO_EXHAUSTED` 结束，MUST NOT 插入越限的那一行。预留数量是合成后的 `reserved_calls` 与 `reserved_cost`，缺省为 1 与 0，记在 attempt 的类型化列上，不是写死的 ±1。`unknown` 把存放的 `reserved_calls` 转入 `calls_used`，并释放存放的 `reserved_cost`，不加 `cost_used`。调用尚未开始的 `failed` 只释放这两项预留，不增加 `calls_used`。新 attempt 按自己那一行将存放的数量重新预留。池无法覆盖该预留，或结算后 `cost_used` 超过非空的 `cost_limit` 时，invoke 以 `fatal = true`、`V15_BUDGET_EXHAUSTED` 中止，并在同一事务中止祖先，MUST NOT 留下新的 `leased` attempt。预留已经写入、且本事务将提交某种终态时，同一事务按存放数量退回 `calls_reserved` 与 `cost_reserved`。回滚类错误不另做退款。`prompt_tokens` 与 `cost_usd` 一旦出现，MUST `>= 0`。预留影响 0 行时，本轮 hook 效应不落库（不变量 12）。

22. **打印与结束互斥。** `reject_finish_on_printed_output` 默认为 true。模型 SQL MUST NOT 把它关掉。同一迭代里既有 `jaz.print` 又有 `jaz."return"` 或 `jaz."raise"` 时，该迭代以 `Continue` 和 `V15_PRINT_AND_RETURN` 结束，invoke MUST NOT 因此进入终态。

23. **扫描恢复，NOTIFY 不是正确性。** 进度 MUST 能只靠 `v15_reclaim_expired()` 与 `v15_next_runnable()` 扫回。丢失或重复的 `NOTIFY` MUST NOT 改变可恢复的控制态。扫描不返回 `leased` 行。过期 attempt，以及 `lease_until` 已过、且没有存活 `leased` attempt 的 invoke，都由这一次无参数回收处理：attempt 终结，invoke 回到 `runnable` 且 `fence` 加 1。`running` 且不是 bind-wait 的语句回到 `pending`；bind-wait 的修理在 §4.10。

24. **span 必闭合，且只记在事件行。** 每个已经打开的 `invoke`、`llm_query`、`repl_exec` span MUST 以 `completed`、`aborted` 或 `failed` 关闭，用的就是 §3.9 检查约束里的小写值。崩溃恢复和 fatal 展开同样要关闭。这些事实只写入 `invoke_events`。v15 MUST NOT 另建 `programs`、`turns`、`spans` 或 `phases` 表。父 invoke 在等待子 invoke 期间，其 REPL 执行 span 保持打开，直到子结果送达并且该父程序收束。`exit` 的 outcome 行在调用 `v15_on_phase` 之前写入；该 phase 不能把 outcome 改掉（不变量 12）。

25. **深度与迭代。** 根 invoke 的 `depth` 为 1，子深度为父深度加 1。`iteration` 从 0 起。`depth = max_depth` 时本 invoke 失去递归：提示中不再描述 `bind_invoke`，调用它得到 `V15_RECURSION_DISABLED`。`depth > max_depth` 时在 `invoke/enter` 中止，码为 `V15_RECURSION_EXCEEDED`，`fatal = false`。`iteration >= max_iterations` 时在 `llm_query/enter`、租赁 attempt 之前中止，码为 `V15_ITERATION_EXCEEDED`。`invoke/enter` 的内核守卫与阶段 `abort` 都是提交类终态关闭：按 `fatal` 写入 `failed` 或 `aborted`，为当前迭代写空的 `repl_history`，删除 scratch；若该 invoke 是子，同一事务按 §4.8 送达，父语句码为 `V15_CHILD_ERROR`，子行保留 `V15_RECURSION_EXCEEDED` 或 abort 自己的码。

26. **scratch 隔离。** 每个 invoke 的 scratch schema 名为 `s_` 加上该 uuid 的 32 位十六进制，由 open 的 `SECURITY DEFINER` 函数创建，owner 是 `v15_owner`。`CREATE SCHEMA … AUTHORIZATION v15_worker` 不使用。已提交状态下 `v15_repl` 对该 schema 没有 `USAGE`，也没有 `CREATE`。不存在 `v15_owner` 对 `v15_repl` 的成员关系。

`v15_prepare_statement` 只校验并返回超时与 schema 名，MUST NOT 在函数体内 `set_config` 去改 `search_path` 或 `statement_timeout`。它在本语句事务内只授予 schema 权限，无 `GRANT OPTION`，且永不授予表级权限：非 `bind_invoke` 语句授予 `USAGE, CREATE ON SCHEMA`；`bind_invoke` 的实参求值只授予 `USAGE`。模型以 `v15_repl` 创建的对象，属主保持 `v15_repl`，DML 来自属主权。下一语句能否再看见它们，只取决于 schema `USAGE` 是否再次授予。完成或失败路径在返回前 `REVOKE` 本事务授出的 schema 权限。worker 在该函数返回之后、仍在同一事务顶层、改角色之前执行 `SET LOCAL search_path` 与 `SET LOCAL statement_timeout`，然后 `SET LOCAL ROLE v15_repl`（§4.6）。

事件触发器 MUST NOT `ALTER … OWNER`。终态删除 MUST NOT 使用 `REASSIGN OWNED`，也 MUST NOT 在 definer 函数内 `SET ROLE`。终态转移以 `v15_owner`（schema 属主）直接执行 `DROP SCHEMA … CASCADE`。级联删除不另查内部对象的属主；§17 的探针证明 PostgreSQL 18.4 如此。若该探针失败，唯一的后备是 worker 在终态事务的顶层、任何函数之外执行 `SET LOCAL ROLE v15_repl`、`DROP SCHEMA … CASCADE`、`RESET ROLE`。这不是常规路径，也不得写进 definer 函数。

`v15_repl` 没有数据库的 `TEMP` 权限。`v15_scratch_guard` 是 `SECURITY INVOKER` 的 `ddl_command_end` 触发器，只在 `current_user = v15_repl` 时限制。它用 `pg_event_trigger_ddl_commands()` 的命令标签与对象身份核对目标 schema；schema 名来自全限定 `v15.v15_current_scratch_schema()`。触发器函数是 `SECURITY INVOKER`，`SET search_path = pg_catalog`（`SECURITY DEFINER`，只返回本后端 `exec_context.scratch_schema`，不返回其他列）。白名单仅限落在该 schema 内的：`CREATE TABLE`、`CREATE TABLE AS`、`SELECT INTO`、`CREATE INDEX`（含 `UNIQUE`）、`CREATE VIEW`、`DROP TABLE`、`DROP INDEX`、`DROP VIEW`。`TRUNCATE` 不在白名单，分类器以 `V15_DIALECT` 拒绝。没有 `ALTER TABLE`。`DROP TABLE`、`DROP INDEX`、`DROP VIEW` 的对象身份改由 `sql_drop` 事件触发器与 `pg_event_trigger_dropped_objects()` 核对；`ddl_command_end` 不含 drop 的对象身份。其余标签，包括 `CREATE FUNCTION`、`CREATE PROCEDURE`、`CREATE ROUTINE` 与 `ALTER TABLE`，抛 `V15_DDL`。`CREATE EVENT TRIGGER` 只出现在超级用户加载的 `v15_schema.sql` 里。

实参求值不授 `CREATE`，也不授任何表权限。该语句 `kind = bind_invoke` 时，`jaz.assign`、`jaz.print`、`jaz.tool`、`jaz."return"`、`jaz."raise"`、`jaz.bind_invoke` 抛 `V15_INVOKE_FORM`。权限失败保持 PostgreSQL 自己的 sqlstate。不另设表达式写入错误码。

27. **历史行的时点。** `repl_history` 在迭代结束时写一行，包括因语句失败而结束的迭代。`result_kind` 为 `return` 或 `raise` 时 `repl_output` MUST 为 `''`。`result_kind` 为 `continue` 且 `repl_exception` 非空时，`repl_output` MUST 为 §3.6 的完整观测。当前轮，以及正停在 `bind_invoke` 上的轮，都还不是历史行。

28. **阶段函数签名先冻结。** `v15_on_phase(invoke_id uuid, iteration int, span text, phase text, io jsonb) returns jsonb` 在 stage 1 建立，stage 1 至 stage 8 的函数体返回 `{"contract":1,"action":"proceed"}`。stage 9 只 `CREATE OR REPLACE` 同一签名的函数体，保持 oid。MUST NOT `DROP FUNCTION`。stage 1–8 桩不在体内预留；那一次 `UPDATE` 由 `v15_begin_llm` 执行。stage 9 的体在 phase 路径做唯一预留。签名不变（§9.6）。`contract` 不是 1，或出现合同未列的键，MUST 抛出 `V15_PHASE_CONTRACT`。`v15_assert_manifest()` 从 stage 1 起就是真实检查，不是空函数。回滚类、提交类、语句失败的权威分类是 §13 的表；不变量正文里的举例不是第二份穷尽清单。

29. **工具在语句内同步执行。** 模型面签名是 `jaz.tool(name text, args jsonb) returns jsonb`。目录里的 handler 是 `SECURITY DEFINER`，签名 `(jsonb) returns jsonb`，owner 为 `NOLOGIN` 角色 `v15_tool_<name>`。`name` 匹配 `^[a-z][a-z0-9_]{0,53}$`，以便角色名不超过 63 字节。handler 是纯函数：只根据 `args` 返回 jsonb，MUST NOT 写 scratch 或内核表。登记检查与 hook 相同（`STABLE`、SQL 或 plpgsql、`search_path=pg_catalog` 单元素、owner 对内核表无权限），并 `REVOKE ALL ON FUNCTION … FROM PUBLIC`，`GRANT EXECUTE … TO v15_owner`，没有其他被授权者，没有 `GRANT OPTION`，运行时不再 `GRANT`。

`v15.jaz_tool` 是 `SECURITY DEFINER`、属主 `v15_owner`。它核对 binding、`tool_grants` 与 §3.11 的摘要（含规范化 `proacl`），并重查 owner 对内核表无权限，然后按 oid 调用 handler。handler 自己的 definer 上下文使 `current_user` 成为 `v15_tool_<name>`。这条路径没有 `SET ROLE`，也没有临时 `GRANT`。调用返回后，模型语句的 `current_user` MUST 仍是 `v15_repl`。`tool_catalog.external = true` MUST 抛出 `V15_EXTERNAL_TOOL`。同步路径不插 `tool_attempts`。

异步延续只走规范 `jaz.bind_tool`（§6.2），且仅 `external = true`。worker 认出该语句，在 D24 路径求值 `arg_sql` 后调用 `v15_suspend_for_tool`：invoke 进入 `tool_wait`（不是 `suspended`），无子 invoke、无树边。FakeTool 只在 `call_started` 已提交、会话无打开事务时运行（§4.14）。`external = false` 的 `bind_tool` 是 `V15_TOOL_BINDING`。`jaz.bind_tool` 被实际执行时仍抛 `V15_INVOKE_FORM`。

## 1. 语义目标与架构总览

v15 保住论文的两条性质，并用 PostgreSQL 的语句边界实现它们。模型的一次回复是一段直线 SQL 程序。worker 把它切成顶层语句，每条语句一个短事务，以 `v15_repl` 执行。语句内部的重复计算只有 `WITH RECURSIVE`。`DO` 会在 `session_user` 仍是 `v15_worker` 的前提下执行 `RESET ROLE`，从而逃回特权角色，因此整条拒绝（不变量 18，V15-D25）。

`jaz.bind_invoke` 不是会阻塞到子树返回的 SQL 函数。worker 认出这条规范语句，只读求值已存放的 `arg_sql`，把子输入与预先渲染的子种子正文交给 `v15_suspend_for_child`。该函数先插入子行并把父写成 bind-wait，再跑子的 open。子树到达终态的那次事务把 jsonb 结果写入父 binding，或按 §4.8 做非 fatal 收束。父程序的下一条语句才读结果。深度很大的尾委托因此仍是「一条父回复、一棵子树、父程序的下一条语句消费结果」。

值域是 jsonb。scope 在子 open 时按值复制。历史是关系 `jaz.history`，祖先历史用 `jaz.prior_history(uuid)` 按 id 读取。当次实际送进模型的消息，包括 hook 追加的消息，用 `jaz.request_messages` 读取。工具在语句事务内同步返回，不写 scratch，执行身份是 `v15_tool_<name>`。配置在 open 时折叠并冻结。hook 是登记在册的 `regprocedure`，只返回效应；dispatcher 在预留成功之后统一写入。`jaz` 的公开面是 `SECURITY INVOKER` 包装，definer 体在 `v15`。

**不在本版行为内的能力**（效应名可以预留，本版在每个 phase 拒绝它们）：`ReturnType`、`ValidateReturn`、`ValidateREPLCode`、轨迹回放、OTel / Langfuse / Jaeger、`map_invoke`、外部工具、`ainvoke`、Jinja、Display / catalog 渲染，以及 `DO`。数值治理、FakeLLM、租约回收、语句间递归，在本版内。真实 provider 是 worker 侧 opt-in，不是 SQL 能力。模型 SQL 仍不能开 socket（§0.4、§4.5.5）。

### 1.1 角色分工

- **worker**（连接身份 `v15_worker`，因而 `session_user = v15_worker`）驱动转移：claim、开始 / 结算 LLM、开始执行、挂起、收束。它在事务已提交的窗口里调用 FakeLLM。模型语句前后的 `SET LOCAL ROLE` / `RESET ROLE` 只出现在事务顶层。
- **模型语句**以 `v15_repl` 跑在 scratch schema 与 `jaz` 包装上。它不持有内核 DML。`current_user` 必须是 `v15_repl`。它拥有自己创建的表。
- **内核函数**属 `v15_owner`，`SECURITY DEFINER`，固定 `search_path`。体内 `current_user` 是 `v15_owner`。它们核对 `session_user` 与 fence，然后写控制行。体内不切换角色。
- **hook** 在 phase 快照上返回效应。baseline 故障使 phase 失败；其余 handler 抛出的异常只留审计。正常返回的非法效应使 phase 失败（不变量 12）。
- **tool** 以自己的 definer 身份 `v15_tool_<name>` 运行，不经 `SET ROLE`。

### 1.2 端到端控制链

一次没有子 invoke 的迭代：

```text
v15_open_invoke（worker 传入已渲染的 system 正文，以及可空的 user 正文）
  → 折叠并冻结配置，复制 scope，安装 baseline hook，建 scratch schema
  → 内核深度守卫，然后 v15_on_phase(invoke, enter)
  → abort 或深度守卫失败：提交类终态，空历史行，属主 DROP SCHEMA … CASCADE
  → 否则 phase 只返回 enter 消息；open 写 seed:system（seq 0），有 show_in_prompt 输入则写 seed:inputs（seq 1），再把返回的持久消息按 max(seq)+1 插入；input_adds 进入 inputs 种子；status = runnable
v15_claim → fence，status = leased
v15_begin_llm（worker 传入已截断的 base messages；SQL 不第二次截断）
  → v15_assert_manifest，并核对 invokes.manifest_digest
  → llm_query span 未打开：enter，然后 send
       enter 只合成并返回
       send 为 proceed 时，v15_on_phase 先按合成预算预留
       预留 0 行：效应不落库，fatal，不插入 attempt
       预留成功：同一次 v15_on_phase 才写持久 hook 消息与其余效应
       v15_begin_llm 把 enter 列表、再把 send 列表抄进 request，自己不插入这些行
  → span 已打开：不发 enter/send；复制上一 attempt 的 reserved_calls / reserved_cost，
       预留该数量，插入 n+1
  → abort 或池不足：不留下 leased attempt；若本 invoke 是子，同一事务 §4.8
FakeLLM（仅当本进程刚刚提交了 call_started=false→true，且会话里没有打开的事务）
v15_settle_llm
  → complete，然后 exit（exit 不能 abort；outcome 行先于 exit 的阶段调用写入）
  → 追加助手消息，写入已经切分的 statements 行（含 arg_sql）
  → 迭代 status = executing
v15_begin_exec
  → repl_exec 的 enter，然后 send
对每条 pending 且 error 为空的语句：
  → prepare：写 exec_context；只授 schema 的 USAGE，或 USAGE 与 CREATE
  → 函数返回后，worker 在事务顶层执行
       SET LOCAL search_path、SET LOCAL statement_timeout、SET LOCAL ROLE v15_repl
  → 执行这一条，RESET ROLE，REVOKE schema 权限，提交
  → 进程内截止时间是语句超时的权威，statement_timeout 只是背书
  → 若该条是规范 bind_invoke：不执行 jaz.bind_invoke
       worker 以 v15_repl 求值已存放的 arg_sql
       再传入子输入与预先渲染的子种子正文
       插入子行后立刻写父的 bind-wait，然后才跑子的 open
       子 runnable 只建立父 bind-wait；open 中已终态才同事务走 §4.8
       父 status = suspended，父租约清除，父不可 claim，父 fence 不加
       SELECT (<arg_sql>) 的任何错误回到保存点，提交为 failed，不留在 pending
成功完成 return 或 raise：
  → 更大下标的 pending 与 preclassified failed 都改为 skipped（切点见 §4.9）
子树到达终态的那次事务（任何提交类路径，不限于 finish）：
  → 成功则绑定 kind=var，父 status = runnable，resume_stmt 指向下一条
  → 子自身 status = failed 且非 fatal：父迭代 Continue，父语句码 V15_CHILD_ERROR，
       子行保留自己的码，剩余父语句 skipped，repl_exec 以 failed 关闭
  → 子 completed 但 bind_name 已被非 var 占用：子保持 completed，
       父走同一套非 fatal 收束，父语句码是 V15_DELIVERY_CONFLICT
  → fatal：父、祖先与仍非终态的后代在同一事务 aborted
下一条父语句在同一 iteration 执行，不再次调用父 LLM
v15_finish_exec
  → 先 repl_exec/complete（return、raise、continue 都发），再按分支 exit
  → return：invoke span complete/exit，invoke completed
  → raise：invoke span exit，outcome = failed
  → continue：repl_history 一行，观测消息，iteration 加 1，invoke runnable
       语句失败引起的 continue：repl_exec exit 的 outcome = completed
  → 若本 invoke 是子，终态写入与 §4.8 同一事务
```

最终 `request.messages` 的顺序是：base（system 种子、显式输入的 user 种子、然后本轮插入 hook 行之前已存放的 `llm_messages`，按 `msg_seq`），然后 enter 合成列表，然后 send 合成列表（§3.4）。

`v15_reclaim_expired()` 是普通事务，没有 owner 或租约参数。它把过期 attempt 收成 `unknown` 或 `failed`，按该行存放的 `reserved_calls` 与 `reserved_cost` 记账。它也把租约已过、且没有存活 `leased` attempt 的 invoke 放回 `runnable` 并加 fence，同时做语句修理。它不插入 attempt，不调用阶段函数，不调用 FakeLLM。若这次收回把子 invoke 写成终态，同一事务做 §4.8。

空消息或只含空白的消息消耗一次迭代，不执行语句。整段切分失败或正文含 NUL，结算为一条合成的失败语句，不回滚这次 settle（不变量 18）。不是 SQL 的散文成为该语句的可恢复错误，不把 invoke 标成机器故障。方言错误同样落在迭代的 `Continue` 上。迭代上限、递归上限、I/O attempt 上限与 fatal 预算失败按不变量 11、13、21 结束 invoke；若对象是子 invoke，父在同一事务收到送达。`V15_TOOL_UNAUTHORIZED` 与模型语句上的 ACL 错误只失败该语句（不变量 14）。凡进入终态而 scratch 仍在的事务，都由 schema 属主直接 `DROP SCHEMA … CASCADE`。

### 1.3 worker 看见的扫描

`v15_next_runnable()` 只读。它只返回 `status = runnable` 且租约空缺或已过期的 `invoke_id`，次序稳定（`root_invoke_id`，然后 `depth` 降序，然后 `invoke_id`）。它不返回 `leased` 或 `suspended`，也不把过期租约改成 `runnable`。子行自然先于已重新变为 `runnable` 的父行被 claim。函数不修改租约，不发 I/O。过期的 `leased` invoke 要先经过 `v15_reclaim_expired()`。

## 2. 角色与权限矩阵

角色在集群内全局。gate 串行运行。每个 stage 的 `setup_db.py` 以超级用户执行引导段，并且在加载任何 SQL 文件之前：

1. `DROP DATABASE … WITH (FORCE)` 每一个 `starts_with(datname, 'agent_v15_')` 的库。
2. 终止仍然以 `v15_` 开头的角色连接着的后端。
3. 按依赖从叶子到根 `DROP ROLE`：每个现存的 `v15_tool_*` 与 `v15_hook_*`，然后 `v15_repl`，`v15_worker`，`v15_owner`，`v15_bootstrap`。
4. 按本节重新 `CREATE ROLE`。只给 `v15_worker` 授予 `v15_repl`（`INHERIT FALSE, SET TRUE`）。不给 `v15_owner` 授予 `v15_repl`。
5. `CREATE DATABASE agent_v15_<stage>`，再加载到该 stage。
6. 加载结束后 `ALTER ROLE v15_bootstrap NOLOGIN`。

这段引导不放进累积 SQL 文件。`CREATE EVENT TRIGGER` 在 `v15_schema.sql` 末尾，只因为超级用户加载该文件而成功。加载器不是超级用户时必须失败，不得改成静默跳过。

| 角色 | 登录 | 成员关系 | 持有什么 |
|---|---|---|---|
| `v15_bootstrap` | 仅装载 | 无运行时成员 | 装 SQL、写清单与目录。不是请求路径上的身份 |
| `v15_owner` | `NOLOGIN` | 无成员，也不是 `v15_repl` 的成员 | 拥有 `v15` 与 `jaz` 的表、视图、scratch schema，以及 `SECURITY DEFINER` 转移。不作为会话用户出现 |
| `v15_worker` | 可登录 | 是 `v15_repl` 的成员，`INHERIT FALSE, SET TRUE`；非超级用户 | 对内核转移的 `EXECUTE`。可以在事务顶层 `SET LOCAL ROLE v15_repl`。不直接 DML 内核业务表。不继承 `v15_repl` 的表权限 |
| `v15_repl` | `NOLOGIN` | 不是 `v15_worker` 的成员 | 模型语句的 `current_user`。可 `EXECUTE` `jaz` 的包装，以及 `v15.jaz_*` 与 `v15_current_scratch_schema()`。无内核 DML，无 `TEMP`。拥有自己在 scratch 里创建的对象 |
| `v15_hook_<name>` | `NOLOGIN` | 无任何成员 | 单个已登记 hook 的 owner。对内核表无 grant |
| `v15_tool_<name>` | `NOLOGIN` | 无任何成员 | 单个已登记 tool 的 owner。对内核表无 grant。调用时由该函数自己的 definer 成为 `current_user` |
| `v15_tool_fake_search` | `NOLOGIN` | 无任何成员 | stage 13 种子角色。catalog 名 `fake_search`、`external = true`。handler 只抛 `V15_EXTERNAL_TOOL`。不登录 |

`GRANT v15_repl TO v15_worker` 是 `INHERIT FALSE, SET TRUE`。没有 `GRANT v15_repl TO v15_owner`。`v15_repl` 不能 `SET ROLE v15_worker`。因为 `session_user` 在模型语句期间仍是 `v15_worker`，顶层 `RESET ROLE` 会回到 worker；这是拒绝 `DO` 的原因（不变量 18）。已提交的权限不把 scratch 的 `USAGE` 或 `CREATE` 授给 `v15_repl`。

`v15_repl` 与 `v15_worker` 都有 schema `jaz` 与 `v15` 的 `USAGE`。没有这项授权，函数上的 `EXECUTE` 到不了对象。`v15_tool_*` 与 `v15_hook_*` 没有这两份 `USAGE`，也没有内核表权限。

在本库从 `PUBLIC` 收回、且不授给 `v15_repl` 的包括：`set_config(text, text, boolean)`、`pg_sleep` 及其 interval 形式、`pg_read_file` / `pg_read_binary_file` / `pg_ls_dir` / `pg_stat_file`、advisory lock 一族、`pg_terminate_backend`、`pg_cancel_backend`、`lo_import` / `lo_export`，以及存在时的 `dblink`。`pg_cancel_backend(int)` 的 `EXECUTE` 只补授给 `v15_worker`。正在跑模型语句的那条连接取消不了自己；worker 从第二条连接取消。`setup_db` 在收回之后不得再依赖这些入口。

语句超时有两层，模型都不能拆掉 worker 那一层：worker 进程内的截止时间是权威；`statement_timeout` 是背书。生效上限为已解析 repl 超时、清单 `max_statement_ms`、以及该语句首部 `-- timeout: <秒>` 三者的最小值。pragma 只接受有限正数。

| 动作 | bootstrap | owner（definer 函数体内） | worker | v15_repl | hook / tool owner | PUBLIC |
|---|---|---|---|---|---|---|
| 内核表 DML | 装载 | 是 | 无直接 grant | 否 | 否 | 否 |
| 调用 `v15_*` 转移 | 装载 | 体内是 `v15_owner`，不得当作 worker | 是，且 `session_user` 必须是 `v15_worker` | 否 | 否 | 否 |
| FakeLLM | 否 | 否 | 是，且当时无打开的事务，且本次进程刚刚提交了 `call_started` | 否 | 否 | 否 |
| FakeTool | 否 | 否 | 是，且当时无打开的事务，且本次进程刚刚提交了工具 `call_started` | 否 | 否 | 否 |
| 模型语句 | 否 | 否 | 仅在事务顶层 `SET LOCAL ROLE v15_repl` 之后的那一条 | 是 | 否 | 否 |
| 函数体内 `SET ROLE` / `RESET ROLE` | 否 | 否 | 否 | 否 | 否 | 否 |
| 写 `exec_context`、清单、`tool_grants`、`hook_defs` | 装载 | 是 | 否 | 否 | 否 | 否 |
| `EXECUTE` `jaz` 包装 | 否 | 函数体内 | 否（未 `SET ROLE` 时不继承） | 是，且 `current_user` 必须是 `v15_repl` | 否 | 否 |
| `EXECUTE` `v15.jaz_*` | 否 | 否 | 否 | 是，仅此一个被授权者 | 否 | 否 |
| `EXECUTE` `v15_current_scratch_schema()` | 否 | 否 | 否 | 是，仅此一个被授权者 | 否 | 否 |
| `EXECUTE` `v15_on_phase`、`v15_assert_manifest`、`v15_assert_invoke_manifest` | 否 | 是，无 `GRANT OPTION`；不授其他角色 | 否 | 否 | 否 | 否 |
| `EXECUTE` `v15_span_open` | 否 | 是 | 是，worker 循环直接调用 | 否 | 否 | 否 |
| schema `jaz`、`v15` 的 `USAGE` | 装载 | 是 | 是 | 是 | 否 | 否 |
| `pg_cancel_backend(int)` | 否 | 是 | 是，且只从另一条连接 | 否 | 否 | 否 |
| 已提交的 scratch `USAGE` / `CREATE` | 否 | schema owner | 否 | 否 | 否 | 否 |
| 语句事务内的 scratch 授权 | 否 | prepare 只授 schema | 调用 prepare | 被授予至 `REVOKE` | 否 | 否 |
| 表级 `GRANT` 给 `v15_repl` | 否 | 否 | 否 | 否 | 否 | 否 |
| hook 与 tool 函数的已提交 `EXECUTE` | 登记时收回 | 是，且无 `GRANT OPTION` | 否 | 否 | 否 | 否 |
| 登记 handler 或 tool | 装载 | 是 | 否 | 否 | 否 | 否 |
| `DROP SCHEMA` scratch | 否 | 是，属主直接 `CASCADE` | 仅 §17 探针失败时的顶层后备 | 否 | 否 | 否 |

`GRANT EXECUTE ON FUNCTION v15_on_phase(...), v15_assert_manifest(), v15_assert_invoke_manifest(uuid) TO v15_owner`，无 `GRANT OPTION`。转移函数以 definer 身份嵌套调用它们；不授则 `42501`。这三份不授其他角色。`v15_span_open` 另授 `v15_worker`（§4.1）。

转移函数在 `session_user` 不是 `v15_worker` 时抛 `V15_ROLE`。`jaz` 包装在 `current_user` 不是 `v15_repl` 时抛 `V15_ROLE`。`v15.jaz_*` 的 definer 体只断言有效 `exec_context`（本 `backend_pid`、语句 `running`），不符抛 `V15_INVALID_TRANSITION`，不做 `current_user` 断言；体内 `current_user` 是 `v15_owner`（§5.1）。

模型语句事务的固定顺序：worker 调用 `v15_prepare_statement`（此时仍是 worker）。该函数写 `exec_context`，并只授予本 invoke 的 schema：普通语句为 `USAGE` 与 `CREATE`，`bind_invoke` 只为 `USAGE`，都无 `GRANT OPTION`，没有表级 `GRANT`。函数返回之后、改角色之前，worker 在事务顶层执行 `SET LOCAL search_path = <scratch>, pg_catalog` 与 `SET LOCAL statement_timeout = '<毫秒>ms'`，然后 `SET LOCAL ROLE v15_repl`，执行这一条语句，`RESET ROLE`，再由完成路径 `REVOKE` schema 权限，然后提交。语句失败或连接断开使 `GRANT` 与语句一起回滚。下一条语句必须再次覆盖该 `backend_pid` 的 `exec_context` 行。schema 的 owner 保持为 `v15_owner`。模型新建对象的 owner 保持为 `v15_repl`。

工具调用不改变这条角色顺序。`v15.jaz_tool` 在 `v15_owner` 的 definer 上下文里按 oid 调用 tool 函数；进入 handler 后 `current_user` 是 `v15_tool_<name>`，返回后模型语句仍是 `v15_repl`。已提交的权限表里，`v15_repl` 没有 handler 的 `EXECUTE`。`v15.jaz_tool` 与 `v15.jaz_prior_history` 的 `EXECUTE` 只授给 `v15_repl`（§5.1），不授给 `v15_worker`。handler 的 `EXECUTE` 仍只在 `v15_owner`。

`v15_suspend_for_tool`、`v15_begin_tool`、`v15_mark_tool_started`、`v15_settle_tool`、`v15_next_tool` 的 `EXECUTE` 只授给 `v15_worker`。`jaz.bind_tool` 包装的 `EXECUTE` 只授给 `v15_repl`；函数体无论谁调用都抛 `V15_INVOKE_FORM`，不插 request。

## 3. 数据模型

下列 21 张表都在 stage 1 创建。其后的 stage 可以增加函数、视图、授权、目录种子 DML，以及 §18 点名的那一次 `v15_on_phase` 与治理 handler 体的 `CREATE OR REPLACE`。**不得再增加表。** 本修订的唯一例外：stage 13 追加 `tool_requests` 与 `tool_attempts`（§3.16），表数 21→23。其后的 stage 仍不得加表。可变控制行带 `revision bigint NOT NULL DEFAULT 0`，每次权威更新加 1。blackboard 的 UPSERT、`hook_counters`、`llm_attempts`、`llm_requests`、`iterations`、`statements`、`tool_requests`、`tool_attempts`，以及 §4.10 的全部修理 `UPDATE`，一律在同一条语句里 `revision = revision + 1`。`INSERT` 使用默认 0。时间列都是 `timestamptz`。

### 3.1 `invokes`

一个 invoke 一行。根行 `parent_invoke_id` 与 `parent_iteration` 都为空、`depth = 1`、`root_invoke_id = invoke_id`。子行的 `depth` 等于父 `depth + 1`，`parent_iteration` 为产子那次迭代（从 0 起）。

```text
invokes(
  invoke_id              uuid PRIMARY KEY,
  parent_invoke_id       uuid NULL REFERENCES invokes(invoke_id),
  parent_iteration       int  NULL CHECK (parent_iteration >= 0),
  root_invoke_id         uuid NOT NULL,
  depth                  int  NOT NULL CHECK (depth >= 1),
  status                 text NOT NULL CHECK (status IN
                           ('pending','runnable','leased','suspended',
                            'tool_wait','completed','failed','aborted')),
  return_value           jsonb NULL,
  error                  jsonb NULL,
  fatal                  boolean NOT NULL DEFAULT false,
  recursion_available    boolean NOT NULL,
  resolved_config        jsonb NOT NULL,
  config_digest          text NOT NULL,
  config_scope_id        uuid NULL,
  local_layer_id         uuid NULL,
  pool_id                uuid NULL REFERENCES budget_pools(pool_id),
  manifest_digest        text NOT NULL,
  scratch_schema         text NOT NULL UNIQUE,
  fence                  bigint NOT NULL CHECK (fence >= 1),
  lease_owner            text NULL,
  lease_until            timestamptz NULL,
  revision               bigint NOT NULL DEFAULT 0,
  created_at             timestamptz NOT NULL,
  updated_at             timestamptz NOT NULL,
  CONSTRAINT invokes_parent_pair CHECK (
    (parent_invoke_id IS NULL) = (parent_iteration IS NULL)),
  CONSTRAINT invokes_lease CHECK (
    (status = 'leased'
      AND lease_owner IS NOT NULL AND lease_until IS NOT NULL)
    OR (status <> 'leased'
      AND lease_owner IS NULL AND lease_until IS NULL)),
  CONSTRAINT invokes_completed CHECK (
    status <> 'completed'
    OR (return_value IS NOT NULL AND error IS NULL AND NOT fatal)),
  CONSTRAINT invokes_failed CHECK (
    status <> 'failed'
    OR (error IS NOT NULL AND NOT fatal)),
  CONSTRAINT invokes_aborted CHECK (
    status <> 'aborted'
    OR (error IS NOT NULL AND fatal))
)
```

- `manifest_digest` 是该 invoke 有效上限的摘要，不是 `governance_manifest.manifest_digest` 的拷贝（§3.13）。
- `scratch_schema` 匹配 `^s_[0-9a-f]{32}$`，owner 为 `v15_owner`（不变量 26）。终态由该属主 `DROP SCHEMA … CASCADE`。
- `local_layer_id` 唯一（部分唯一索引，非空值）。一个 invoke 至多一个 local layer。
- `return_value` 可以在 `status` 仍为 `leased` 时被 `jaz."return"` 暂存。终态检查只约束终态行，不禁止这次暂存。

`pending` 只存在于 open 事务内部的构建窗口；提交后的可调度初态是 `runnable`。`pool_id` 引用 `budget_pools`。空表示不设调用池与金额池。`status = leased` 且 `lease_until` 已过、又没有存活 `leased` attempt 的行，由 `v15_reclaim_expired()` 收回，不由扫描函数改写。

### 3.2 `iterations`

```text
iterations(
  invoke_id     uuid NOT NULL REFERENCES invokes(invoke_id),
  iteration     int  NOT NULL CHECK (iteration >= 0),
  status        text NOT NULL CHECK (status IN
                  ('pending','llm','executing','suspended','done')),
  resume_stmt   int  NOT NULL DEFAULT 0 CHECK (resume_stmt >= 0),
  result_kind   text NULL CHECK (result_kind IN ('continue','return','raise')),
  capture       text NOT NULL DEFAULT '',
  revision      bigint NOT NULL DEFAULT 0,
  PRIMARY KEY (invoke_id, iteration)
)
```

`status = done` 时 `result_kind` 非空；未结束时 `result_kind` 为空。`capture` 累积本迭代已提交的 `jaz.print` 文本，挂起后恢复仍保留。`resume_stmt` 是下一条要执行的 `stmt_index`。存在 `failed` 语句时，迭代可以仍是 `executing`。

### 3.3 `statements`

```text
statements(
  invoke_id        uuid NOT NULL,
  iteration        int  NOT NULL,
  stmt_index       int  NOT NULL CHECK (stmt_index >= 0),
  sql              text NOT NULL,
  sql_digest       text NOT NULL,
  kind             text NOT NULL CHECK (kind IN
                     ('plain','bind_invoke','return','raise','print','assign',
                      'bind_tool')),
  bind_name        text NULL,
  tool_name        text NULL,
  arg_sql          text NULL,
  status           text NOT NULL CHECK (status IN
                     ('pending','running','done','failed','skipped')),
  child_invoke_id  uuid NULL REFERENCES invokes(invoke_id),
  error_sqlstate   text NULL,
  error            jsonb NULL,
  revision         bigint NOT NULL DEFAULT 0,
  PRIMARY KEY (invoke_id, iteration, stmt_index),
  FOREIGN KEY (invoke_id, iteration)
    REFERENCES iterations(invoke_id, iteration)
)
```

结算入参的每个元素，旧 6 kind 仍是 `{sql, sql_digest, kind, bind_name, arg_sql, reject_code}`（六键）。`kind = bind_tool` 恰好七键，多 `tool_name`，匹配 `^[a-z][a-z0-9_]{0,53}$`。`sql_digest` 必须等于对存放文本 `sql` 的 `md5`。`sql` 不得含 NUL。`reject_code` 不是表列。`error_sqlstate` 恒等于 `error->>'sqlstate'`；`error` 为空则该列为空。行一旦写入，可执行谓词是 `status = 'pending' AND error IS NULL`。运行路径不得再读 `reject_code`。`tool_name` 当且仅当 `kind = bind_tool` 非空。

`arg_sql` 是分类器抽出的实参表达式文本，不是整句。`kind` 为 `bind_invoke`、`assign`、`print`、`return`、`raise` 且表达式抽得出来时写入；否则为 SQL NULL。入参里规范 `bind_invoke` 且 `reject_code` 为空时，写入行的 `arg_sql` 与 `bind_name` MUST NOT NULL，并且 `status = pending`、`error` 为空。`v15_suspend_for_child` 只读已存放的 `arg_sql`，求值结果由 worker 作为 jsonb 传入。

`kind = bind_invoke` 时 `bind_name` 非空。`kind = bind_tool` 时 `bind_name` 与 `tool_name` 都非空；`child_invoke_id` 保持 NULL。子 invoke 只由 `v15_suspend_for_child` 写入 `child_invoke_id`。`done` 与 `skipped` 不再执行。`failed` 表示该语句不会执行：要么结算已经拒绝它，要么语句事务已回滚。迭代是否结束不由这一列表示。入参 `reject_code` 非空的行在结算时就是 `failed`，`error` 非空且 `error.code` 等于该码。settle 不提前把后续下标改成 `skipped`。skip 只发生在执行边界，或 `return` / `raise` 终端完成（§4.5.3、§4.6.2、§4.9）。

整段无法切分时，这一次结算恰好一行：`kind = plain`，`bind_name` 与 `arg_sql` 为空，`status = failed`。不含 NUL 的未闭合引号、注释或 dollar-quote，`sql` 为原文，`error.code = V15_DIALECT`。含 NUL 时，先把每个 NUL 换成六字符 `\u0000`，再计算摘要并存放，`error.code = V15_VALUE_INVALID`，不再另报未闭合。这一行不执行。

被拒绝的 `DO` 与 `ALTER TABLE` 同样是结算时的 `failed` 行，`kind = plain`。`DO` 的 `error.code` 为 `V15_DIALECT`，`ALTER TABLE` 的为 `V15_DDL`。它们都不是可执行语句。

### 3.4 `llm_requests` 与 `llm_attempts`

一个逻辑查询一行 request。同一次迭代至多一个 request。重试不新建 request，只追加 attempt。

```text
llm_requests(
  request_id      uuid PRIMARY KEY,
  invoke_id       uuid NOT NULL,
  iteration       int  NOT NULL,
  status          text NOT NULL CHECK (status IN ('open','settled','exhausted')),
  logical_digest  text NOT NULL,
  revision        bigint NOT NULL DEFAULT 0,
  UNIQUE (invoke_id, iteration),
  FOREIGN KEY (invoke_id, iteration)
    REFERENCES iterations(invoke_id, iteration)
)

llm_attempts(
  attempt_id      uuid PRIMARY KEY,
  request_id      uuid NOT NULL REFERENCES llm_requests(request_id),
  n               int  NOT NULL CHECK (n >= 1),
  status          text NOT NULL CHECK (status IN
                    ('leased','settled','failed','unknown')),
  fence           bigint NOT NULL CHECK (fence >= 1),
  lease_owner     text NULL,
  lease_until     timestamptz NULL,
  pool_id         uuid NULL REFERENCES budget_pools(pool_id),
  reserved_calls  int NOT NULL DEFAULT 1 CHECK (reserved_calls >= 1),
  reserved_cost   numeric NOT NULL DEFAULT 0 CHECK (reserved_cost >= 0),
  call_started    boolean NOT NULL DEFAULT false,
  calls_charged   boolean NOT NULL DEFAULT false,
  request         jsonb NOT NULL,
  response        jsonb NULL,
  prompt_tokens   int NULL CHECK (prompt_tokens IS NULL OR prompt_tokens >= 0),
  cost_usd        numeric NULL CHECK (cost_usd IS NULL OR cost_usd >= 0),
  revision        bigint NOT NULL DEFAULT 0,
  UNIQUE (request_id, n),
  CHECK (status <> 'failed'
         OR (NOT call_started AND NOT calls_charged)),
  CHECK (status <> 'unknown'
         OR (call_started AND calls_charged)),
  CHECK (status <> 'settled'
         OR (call_started AND calls_charged)),
  CHECK (status <> 'leased' OR NOT calls_charged)
)
```

`request` 的存放形状是：

```text
{
  attempt_id: uuid,
  messages: [
    { seq: int, message_id: text, role: text,
      kind: text, content: text },
    ...
  ]
}
```

`kind` 的闭集是 `system`、`input`、`assistant`、`observation`、`persistent_hook`、`transient_hook`。`seq` 是本次数组的下标，从 0 起，不是 `llm_messages.msg_seq`。`message_id` 在这一数组内必须唯一；`v15_begin_llm` 在插入 attempt 之前检查合成结果，重复则 `V15_VALUE_INVALID`（回滚类）。

数组顺序固定，不得按 `message_id` 重排：

1. **base。** 消息 id 与顺序取自已存放的 `llm_messages`：`seed:system`，然后 `seed:inputs`（没有则跳过），然后其余行按 `msg_seq` 升序。`seed:system` 的正文由 worker 在调用 `v15_begin_llm` 之前重渲染，可与存放的种子不同。inputs 正文跟随当前 `kind = input` 行，仅截断。SQL 校验 `message_id` 与顺序，不要求 kind 逐字节相等（§4.5.1）。请求 kind 按映射：`seed:system` → `system`，`seed:inputs` → `input`，其余用存储行的 `kind`。库内种子仍是 `kind = seed`。
2. **enter。** 本次 `llm_query/enter` 合成后的消息，瞬态与持久都在，顺序见 §9.5。
3. **send。** 本次 `llm_query/send` 合成后的消息，同样含瞬态与持久。

base 的快照在本轮持久 hook 行插入之前取。enter 与 send 段来自阶段返回的列表，不得在插入之后把 `llm_messages` 再读一遍拼进 request，否则持久消息会出现两次。`v15_begin_llm` 只复制这两份列表，不执行 `INSERT`。持久行由 dispatcher 在预留成功之后写入（§3.5）。瞬态行只存在于 `request.messages`。

worker 传入的 base 元素至少有 `role`、`kind`、`content`、`message_id`。`transient_hook` 不得出现在 base 里。base 正文的字符数之和大于已冻结的 `max_invoke_input_length` 时，`v15_begin_llm` 以提交类 `V15_VALUE_INVALID` 结束本 invoke，不插入 attempt。

`logical_digest` 由 SQL 计算，不是 worker 传入的。FakeLLM 的键是 `(llm_requests.logical_digest, n)`。存放值是最终 `request` 去掉 `attempt_id` 之后的 `md5(jsonb::text)`，消息数组含 enter 与 send 追加的消息。`send` 的 `io.logical_digest` 只覆盖追加之前的 base；没有追加时两者相等。FakeLLM 使用存放的最终摘要。同一 request 的各 attempt 共用这一摘要。重试复制上一 attempt 的 `messages`，换上新的 `attempt_id`，不得改写 `llm_requests.logical_digest`；重算结果与原值不同则 `V15_VALUE_INVALID`，回滚类。

`reserved_calls` 与 `reserved_cost` 是该 attempt 实际占住的数量。首次尝试来自合成后的 `budget`，缺省 1 与 0。重试复制上一 attempt 的这两列，不重新跑 `enter` / `send`。结算与回收只移动这两列里的数。`pool_id` 复制自 invoke；invoke 没有池时为空，池上的 `UPDATE` 跳过，列仍然照写。

`fence` 在每一新行上从 1 起。回收不插入行，因此不存在「回收颁发的全局 attempt 栅栏」。`call_started` 与 `calls_charged` 必须与 `status` 在同一条 `UPDATE` 里一起改变，使上面的检查在语句结束时成立。

### 3.5 `llm_messages`

持久转录。种子、助手回复、已标 `persistent` 的 hook 消息、以及迭代结束后的观测，按追加序进入。瞬态警告不得插入。

```text
llm_messages(
  invoke_id    uuid NOT NULL REFERENCES invokes(invoke_id),
  msg_seq      bigint NOT NULL CHECK (msg_seq >= 0),
  message_id   text NOT NULL,
  iteration    int NULL CHECK (iteration IS NULL OR iteration >= 0),
  role         text NOT NULL CHECK (role IN ('system','user','assistant')),
  kind         text NOT NULL CHECK (kind IN
                 ('seed','assistant','observation','persistent_hook')),
  content      text NOT NULL,
  PRIMARY KEY (invoke_id, msg_seq),
  UNIQUE (invoke_id, message_id)
)
```

`message_id` 没有列默认值。写入者 MUST 使用下列冻结拼写，不得再用 `db:<msg_seq>`：

| 行 | `message_id` |
|---|---|
| system 种子 | `seed:system` |
| 显式输入的 user 种子 | `seed:inputs` |
| 第 `n` 次迭代的助手回复 | `iter:<n>:assistant` |
| 第 `n` 次迭代的观测 | `iter:<n>:observation` |
| 持久 hook | hook 提供的 id，原样存放 |
| 瞬态 hook | 不插入本表；只在 `request.messages` 里携带同一 hook id |

`n` 是迭代号的十进制文本，无前导零，与 `iterations.iteration` 相同。hook 提供的 id 长度 1..200，并且 MUST NOT 等于 `seed:system` 或 `seed:inputs`，也 MUST NOT 匹配 `^iter:[0-9]+:(assistant|observation)$`。`budget_forcing` 的消息 id 是 `budget_forcing:<ordinal>:<计数增加前的 n>`（§10.2），受同一条禁止规则约束。违反者在效应阶段得到 `V15_VALUE_INVALID`。

LLM 路径的持久 hook 行只由 `v15_on_phase` 在预留成功之后写入。`invoke/enter` 的持久消息不由 phase 插入：phase 只返回 `messages`，由 `v15_open_invoke` 与 `v15_suspend_for_child` 的子 open 在种子之后按 `max(seq)+1` 插入。这是 enter 路径上唯一的非 dispatcher 写者。`v15_begin_llm` MUST NOT 插入 hook 消息。种子由 open 在效应返回之后写入。助手行由 `v15_settle_llm` 写入。观测行由 `v15_finish_exec` 的 continue 分支写入。这三处都不是 hook 消息。

行不可变：触发器拒绝 `UPDATE` 与 `DELETE`。同一 `invoke_id` 的 `msg_seq` 无洞。`kind = seed` 时 `iteration` 为空。请求元素的 kind 是映射，不是这列的逐字节拷贝（§3.4、§4.5.1）。open 先解析 `invoke/enter` 效应，再插入 `seed:system`（`msg_seq` 0），若效应后仍存在 `show_in_prompt` 的输入则插入 `seed:inputs`（`msg_seq` 1）。持久 enter 消息一律 `max(seq)+1`。种子行是 `INSERT`，不是 `UPDATE`。system 种子正文是 `p_system`。inputs 种子按 §6.5 从效应后的显式输入组成，enter 的 `input_adds` 因此进入其中。SQL 不调用 Python 渲染器。

### 3.6 `repl_history`

`jaz.history` 的基表。`SELECT` 不授给 `v15_repl`。

```text
repl_history(
  invoke_id       uuid NOT NULL,
  iteration       int  NOT NULL CHECK (iteration >= 0),
  llm_response    text NOT NULL,
  repl_output     text NOT NULL,
  repl_exception  jsonb NULL,
  PRIMARY KEY (invoke_id, iteration),
  FOREIGN KEY (invoke_id, iteration)
    REFERENCES iterations(invoke_id, iteration)
)
```

写行的事务就是把该 `iterations.status` 置为 `done` 的事务。`result_kind` 为 `return` 或 `raise` 时 `repl_output = ''`。成功的 `continue`（`repl_exception` 为空）里，`repl_output` 等于 `capture`，可以为 `''`。失败的 `continue`（`repl_exception` 非空）里，`repl_output` 是完整观测：`capture` 为空时就是 `[v15 exception <code>]`、换行、`message`；`capture` 非空时先写 `capture`，再一个换行，然后同一异常块。`repl_exception` 仍只是含 `sqlstate`、`code`、`message` 的 jsonb。同一事务追加的观测消息正文等于这份 `repl_output`，`message_id` 为 `iter:<n>:observation`。没有第 0 行之前的初始化行。`invoke/enter` 的提交类中止也写一行，`llm_response` 与 `repl_output` 都是 `''`。

### 3.7 `bindings`

```text
bindings(
  invoke_id       uuid NOT NULL REFERENCES invokes(invoke_id),
  name            text NOT NULL,
  kind            text NOT NULL CHECK (kind IN ('input','scope','var','tool')),
  value           jsonb NOT NULL,
  tool_id         uuid NULL REFERENCES tool_catalog(tool_id),
  show_in_prompt  boolean NOT NULL,
  provenance      text NOT NULL CHECK (provenance IN
                    ('explicit','scope','hook','repl','delivery')),
  revision        bigint NOT NULL DEFAULT 0,
  PRIMARY KEY (invoke_id, name)
)
```

`name` 是匹配 `^[A-Za-z_][A-Za-z0-9_]*$` 的标识符，并且不是保留框架名（保留名表在 §5）。`kind = tool` 当且仅当 `tool_id` 非空。同一 `(invoke_id, name)` 只有一种 `kind`。子 open 复制 `kind = scope` 的行；不复制 `kind = input`。`jaz.assign` 与子结果绑定写入 `kind = var`，`provenance` 分别为 `repl` 与 `delivery`。`bind_tool` 成功送达同样写入或更新 `kind = var`，`provenance = delivery`，`show_in_prompt = true`。这些 `var` 行不向孙 invoke 传播。

子 `completed` 时，若 `bind_name` 已被 `input`、`scope` 或 `tool` 占用，不覆盖该行。父走非 fatal 收束，父语句的 `error.code` 是 `V15_DELIVERY_CONFLICT`，子保持 `completed`。`bind_tool` 成功结算时若同名已被 `input`、`scope` 或 `tool` 占用：attempt 仍 `settled`（已计 calls）、request `settled`、binding 不改，语句 `V15_DELIVERY_CONFLICT`，非 fatal 收束。除此之外，子以 `failed` 结束时，父语句的码一律是 `V15_CHILD_ERROR`，即使子行自己的码是 `V15_RECURSION_EXCEEDED`、`V15_ITERATION_EXCEEDED`、`V15_IO_EXHAUSTED`、`V15_RAISE` 或 `V15_HOOK_ABORT`。`V15_CHILD_ERROR` 不写回子行。

### 3.8 `exec_context`

```text
exec_context(
  backend_pid     int PRIMARY KEY,
  invoke_id       uuid NOT NULL REFERENCES invokes(invoke_id),
  iteration       int NOT NULL,
  stmt_index      int NOT NULL,
  scratch_schema  text NOT NULL,
  revision        bigint NOT NULL DEFAULT 0
)
```

DML 只属于 worker / owner。`jaz` 包装调用的 `v15` definer 体用 `pg_backend_pid()` 读这一行，并且函数自身的 `search_path` 钉死，避免 scratch 对象挡住 `pg_catalog`。这不是 GUC，也不是临时表。模型语句的 `search_path` 由 worker 在 prepare 返回之后、于事务顶层设置，不由这一张表触发，也不由 definer 函数设置。

### 3.9 `invoke_events`

span 与审计的唯一载体。

```text
invoke_events(
  invoke_id    uuid NOT NULL REFERENCES invokes(invoke_id),
  seq          bigint NOT NULL CHECK (seq >= 0),
  event_class  text NOT NULL CHECK (event_class IN ('span','audit')),
  span         text NULL CHECK (span IN ('invoke','llm_query','repl_exec')),
  phase        text NULL CHECK (phase IN
                 ('enter','send','complete','exit','retry')),
  outcome      text NULL CHECK (outcome IN ('completed','aborted','failed')),
  payload      jsonb NOT NULL,
  fence        bigint NULL,
  created_at   timestamptz NOT NULL,
  PRIMARY KEY (invoke_id, seq)
)
```

`event_class = span` 时 `span` 与 `phase` 都非空；`exit` 与 `retry` 之外 `outcome` 为空；`exit` 时 `outcome` 非空，且只使用上列小写值。`exit` 行在对应的 `v15_on_phase(..., 'exit', ...)` 之前插入，payload 里的 outcome 与该行相同。`event_class = audit` 时 `span`、`phase`、`outcome` 都为空。触发器拒绝一切 `UPDATE` 与 `DELETE`。同一 `invoke_id` 的 `seq` 从 0 起连续。进入终态的 span 必有配对的 `exit` 行；此条由转移函数保证，不靠一条能在 span 仍打开时成立的 CHECK。

### 3.10 配置三表

```text
config_profiles(
  profile_id       uuid PRIMARY KEY,
  llm              jsonb NOT NULL,
  repl             jsonb NOT NULL,
  protocol         jsonb NOT NULL,
  baseline_hooks   jsonb NOT NULL,
  profile_digest   text NOT NULL,
  created_at       timestamptz NOT NULL
)

config_scopes(
  scope_id     uuid PRIMARY KEY,
  profile_id   uuid NOT NULL REFERENCES config_profiles(profile_id),
  scope_digest text NOT NULL
)

config_layers(
  layer_id      uuid PRIMARY KEY,
  scope_id      uuid NULL REFERENCES config_scopes(scope_id),
  ordinal       int NOT NULL CHECK (ordinal >= 0),
  kind          text NOT NULL CHECK (kind IN ('plain','depth')),
  llm           jsonb NULL,
  repl          jsonb NULL,
  protocol      jsonb NULL,
  depth_map     jsonb NULL,
  extra_hooks   jsonb NULL,
  layer_digest  text NOT NULL
)
```

`kind = 'plain'` 时 `depth_map` 为空。组件列是否参与折叠看 `IS NOT NULL`，不看 `jsonb_exists`。值为 JSON `null` 时列非空，但不是对象，折叠拒绝。`kind = 'depth'` 时三个组件列都为空，`depth_map` 非空；只有 `depth_map` 里该深度的 partial 参与折叠。partial 里某个组件键在不在，用 `jsonb_exists`。`depth_map` 的值里不得再出现 `depth_map` 或 `baseline_hooks`。`scope_id` 非空时 `UNIQUE (scope_id, ordinal)`。`scope_id` 为空的 layer 是 local layer，只能被一个 `invokes.local_layer_id` 引用，且 `kind = 'plain'`。propagating 层挂在 scope 上。子 invoke 不从这些层重读 `extra_hooks`，只复制父行上已经安装的 propagating hook（§3.11）。

### 3.11 `hook_defs` 与 `invoke_hooks`

```text
hook_defs(
  hook_def_id        uuid PRIMARY KEY,
  hook_key           text NOT NULL UNIQUE,
  regprocedure       oid  NOT NULL,
  owner_role         oid  NOT NULL,
  baseline_required  boolean NOT NULL,
  handler_digest     text NOT NULL,
  search_path        text NOT NULL,
  created_at         timestamptz NOT NULL
)

invoke_hooks(
  invoke_id    uuid NOT NULL REFERENCES invokes(invoke_id),
  ordinal      int  NOT NULL CHECK (ordinal >= 0),
  hook_def_id  uuid NOT NULL REFERENCES hook_defs(hook_def_id),
  channel      text NOT NULL CHECK (channel IN
                 ('baseline','propagating','local')),
  config       jsonb NOT NULL,
  state        jsonb NOT NULL,
  revision     bigint NOT NULL DEFAULT 0,
  PRIMARY KEY (invoke_id, ordinal)
)
```

`handler_digest` 是下列文本的 `md5`，段与段之间一个换行：`pg_get_functiondef(oid)`、owner 角色名、`provolatile`、`prosecdef` 的 `true` 或 `false`、语言名、`proconfig` 的文本（空则空串）、规范化的 `proacl`。`proacl` 为 SQL NULL 时最后一段是空串；否则每个 `aclitem::text` 按字节序升序，用逗号连接，逗号后不加空格。只改 owner、`search_path` 或 `GRANT` / `REVOKE` 而 `prosrc` 不变，摘要也变。`tool_catalog.handler_digest` 使用同一拼接。`search_path` 列存放登记时核对过的 `pg_catalog`。

调用前重算摘要，并重查 owner 对 `v15` 与 `jaz` 的任何表都没有表级权限。摘要不符，或这道权限重查失败，都是 `V15_HANDLER_DIGEST`。表权限不在 `proacl` 里，所以两道检查都要做。

登记时持久化的检查结果必须为：`provolatile = 's'`、语言是 SQL 或 plpgsql、owner 是对应的 `v15_hook_<name>`、`prosecdef` 为真、`proconfig` 恰好一个元素 `search_path=pg_catalog`、owner 对内核表无表级权限、`PUBLIC` 无 `EXECUTE`、`EXECUTE` 只在 `v15_owner` 且该授权没有 `GRANT OPTION`。`baseline_required` 的定义由 open 安装到每个 invoke 的 `channel = baseline` 行。

子 open 不复制父的 `ordinal` 数值，也不按当时的 `config_layers.extra_hooks` 再装一份。它先安装自己的 baseline，再按父 propagating 行的相对顺序接上新的连续 `ordinal`，复制 `hook_def_id`、`channel` 与 `config`，`state` 置为 `{}`。`channel = local` 的行不复制。分发顺序仍是 baseline，然后 propagating，然后 local。

### 3.12 `blackboard`、`budget_pools`、`hook_counters`

```text
blackboard(
  invoke_id   uuid NOT NULL REFERENCES invokes(invoke_id),
  key         text NOT NULL,
  value       jsonb NOT NULL,
  generation  bigint NOT NULL CHECK (generation >= 0),
  revision    bigint NOT NULL DEFAULT 0,
  PRIMARY KEY (invoke_id, key)
)

budget_pools(
  pool_id          uuid PRIMARY KEY,
  calls_limit      int NULL CHECK (calls_limit IS NULL OR calls_limit >= 1),
  cost_limit       numeric NULL CHECK (cost_limit IS NULL OR cost_limit >= 0),
  calls_used       int NOT NULL DEFAULT 0 CHECK (calls_used >= 0),
  calls_reserved   int NOT NULL DEFAULT 0 CHECK (calls_reserved >= 0),
  cost_used        numeric NOT NULL DEFAULT 0 CHECK (cost_used >= 0),
  cost_reserved    numeric NOT NULL DEFAULT 0 CHECK (cost_reserved >= 0),
  revision         bigint NOT NULL DEFAULT 0
)

hook_counters(
  invoke_id    uuid NOT NULL REFERENCES invokes(invoke_id),
  counter_key  text NOT NULL,
  n            bigint NOT NULL DEFAULT 0 CHECK (n >= 0),
  revision     bigint NOT NULL DEFAULT 0,
  PRIMARY KEY (invoke_id, counter_key)
)
```

`blackboard.generation` 是该键最后一次被 dispatcher 批次写上的代数。同一 phase 的 handler 读到的是批次应用前的整张映射。预留失败的那次转移不增加 generation。

`calls_reserved` 与 `cost_reserved` 是尚未结算的占位，跨事务有效。新的预留必须在一条条件 `UPDATE` 里同时满足：`calls_limit` 为空，或 `calls_used + calls_reserved + reserved_calls` 不超过它；并且 `cost_limit` 为空，或 `cost_used + cost_reserved + reserved_cost` 不超过它。更新到 0 行就是池不足，不是把预留写成负数，同事务也不写本轮其余效应。退款或入账若影响 0 行，抛 `V15_INVALID_TRANSITION`。数量来自 attempt 上存放的两列。锁的完整顺序在 §4.1：先无锁读出将要写的 id，再按 `pool_id` 锁池，再按 `invoke_id` 锁全部将写入的 invoke（自身、祖先、非终态后代），然后重读 fence 与状态。

`hook_counters` 按 invoke 计数。`budget_forcing` 的拒绝次数键仍是 `budget_forcing:` 接该 `invoke_hooks.ordinal` 的十进制文本。这是计数键，不是消息 id。消息 id 还要再接一个冒号和增加前的计数值（§3.5、§10.2）。

### 3.13 `governance_manifest`

```text
governance_manifest(
  manifest_id        smallint PRIMARY KEY CHECK (manifest_id = 1),
  max_iterations     int NOT NULL CHECK (max_iterations >= 1),
  max_depth          int NOT NULL CHECK (max_depth >= 1),
  max_io_attempts    int NOT NULL CHECK (max_io_attempts >= 1),
  max_statement_ms   int NOT NULL CHECK (max_statement_ms >= 1),
  manifest_digest    text NOT NULL,
  created_at         timestamptz NOT NULL
)
```

表内至多一行，且合运行时必须有这一行。stage 1 的装载插入初始行。`governance_manifest.manifest_digest` 只摘要这一单例的四项上限，形状与 §8.5 的对象相同，不含 `manifest_id` 与 `created_at`。存放值与四列重算不一致时，视同清单损坏，`V15_GOVERNANCE_MISSING`。

`invokes.manifest_digest` 是该 invoke **有效**上限的摘要。调用方收紧之后它小于清单上的对应值，因此一般不等于单例行的摘要。二者相等，仅当 `p_ceilings` 为空且 open 之后这四项没有变过。open 不得把单例摘要抄进 invoke 行。已打开 invoke 的推进重算自己的 baseline，不因清单后来变紧而改写自己的摘要。对不上 `invokes.manifest_digest` 的推进抛 `V15_MANIFEST_DIGEST`。

### 3.14 `tool_catalog` 与 `tool_grants`

```text
tool_catalog(
  tool_id         uuid PRIMARY KEY,
  name            text NOT NULL UNIQUE,
  arg_schema      jsonb NOT NULL,
  handler         oid  NOT NULL,
  description     text NOT NULL,
  external        boolean NOT NULL DEFAULT false,
  handler_digest  text NOT NULL
)

tool_grants(
  invoke_id  uuid NOT NULL REFERENCES invokes(invoke_id),
  tool_id    uuid NOT NULL REFERENCES tool_catalog(tool_id),
  PRIMARY KEY (invoke_id, tool_id)
)
```

`name` 匹配 `^[a-z][a-z0-9_]{0,53}$`，角色名是 `v15_tool_` 接 `name`。`jaz.tool` 同时要求：本 invoke 有 `bindings.kind = 'tool'` 且 `name` 匹配的行，以及 `tool_grants` 的对应行。`external = true` 时抛出 `V15_EXTERNAL_TOOL`，不调用 handler。

handler 为 `SECURITY DEFINER`，`prosecdef` 为真，签名 `(jsonb) returns jsonb`，`STABLE`，语言是 SQL 或 plpgsql，owner 是对应的 `v15_tool_<name>`。owner 对内核表无 grant。`handler_digest` 的拼接与 §3.11 相同，因此包含规范化 `proacl`。已提交的 `EXECUTE` 只属于 `v15_owner`，没有 `GRANT OPTION`。`v15_repl` 没有这份权限。调用时不临时 `GRANT`，也不 `SET ROLE`；oid 调用进入 handler 自己的 definer，`current_user` 变为 `v15_tool_<name>`。handler 不写 scratch。scope 传来的工具在子 open 时复制 binding，并在同一事务复制 grant 行；显式 input 工具不复制。

### 3.15 模型面

`jaz` 里给 `v15_repl` 的对象是公开面。函数的公开面是 `SECURITY INVOKER` 包装：它检查 `current_user = v15_repl`，再调用 `v15` 里的 `SECURITY DEFINER` 体。`GRANT EXECUTE ON FUNCTION v15.jaz_<name>(...) TO v15_repl`，仅此一个被授权者；`v15_worker` 不获此授权。包装断言 `current_user = 'v15_repl'`，不符抛 `V15_ROLE`。definer 体只断言有效 `exec_context`，不符抛 `V15_INVALID_TRANSITION`，不做 `current_user` 断言。同样适用于 `v15.jaz_tool` 与 `v15.jaz_prior_history`。视图没有这层包装。包装的 `current_user` 合同在 §5.1。这些对象都不是第二份真相。基表的 `SELECT` 不授给 `v15_repl`。

`jaz.history` 的 owner 是 `v15_owner`，`security_barrier = true`，`security_invoker = false`。列是 `iteration`、`llm_response`、`repl_output`、`repl_exception`。行滤到当前 `exec_context.invoke_id`。没有本后端的 `exec_context` 行时抛 `V15_INVALID_TRANSITION`，与 `jaz.request_messages` 相同（§5.4）。关系按 `iteration` 键区分，视图定义不得被当成对外的排序合同。提示词要求 `ORDER BY iteration`（§6.5）。

`jaz.request_messages` 的 owner、`security_barrier` 与 `security_invoker` 与上表相同。列是 `seq`、`role`、`kind`、`content`。行来自当前 `exec_context` 的 invoke 与迭代上、`n` 最大且 `status = settled` 的那次 `llm_attempts.request.messages`。没有已结算 attempt 时返回空表，不抛错。正文是该 attempt 实际送出的正文：观测可以是截断后的副本，瞬态 hook 消息在这里可见，不在 `jaz.history` 里。`message_id` 留在 jsonb 里，不作为视图列。

`jaz.prior_history(uuid)` 与 `jaz.var` 在 `jaz` 中是 `VOLATILE` 的 invoker 包装。对应的 `VOLATILE`、`SECURITY DEFINER` 体在 `v15`，同样只认 `exec_context`。

### 3.16 `tool_requests` 与 `tool_attempts`（异步工具段）

本小节是 §3 表数例外所追加的两张表。它们不进 invoke 树：无 `parent_invoke_id` 边、无深度变化、不建 scratch、不跑子 open、不调 `v15_on_phase`。

```text
tool_requests(
  request_id   uuid PRIMARY KEY,
  invoke_id    uuid NOT NULL,
  iteration    int  NOT NULL CHECK (iteration >= 0),
  stmt_index   int  NOT NULL CHECK (stmt_index >= 0),
  tool_id      uuid NOT NULL REFERENCES tool_catalog(tool_id),
  bind_name    text NOT NULL,
  args         jsonb NOT NULL,
  args_digest  text NOT NULL,
  status       text NOT NULL CHECK (status IN
                 ('open','settled','failed','exhausted')),
  revision     bigint NOT NULL DEFAULT 0,
  UNIQUE (invoke_id, iteration, stmt_index),
  FOREIGN KEY (invoke_id, iteration)
    REFERENCES iterations(invoke_id, iteration)
)

tool_attempts(
  attempt_id      uuid PRIMARY KEY,
  request_id      uuid NOT NULL REFERENCES tool_requests(request_id),
  n               int  NOT NULL CHECK (n >= 1),
  status          text NOT NULL CHECK (status IN
                    ('leased','settled','failed','unknown')),
  fence           bigint NOT NULL CHECK (fence >= 1),
  lease_owner     text NULL,
  lease_until     timestamptz NULL,
  pool_id         uuid NULL REFERENCES budget_pools(pool_id),
  reserved_calls  int NOT NULL DEFAULT 1 CHECK (reserved_calls >= 1),
  reserved_cost   numeric NOT NULL DEFAULT 0 CHECK (reserved_cost >= 0),
  call_started    boolean NOT NULL DEFAULT false,
  calls_charged   boolean NOT NULL DEFAULT false,
  result          jsonb NULL,
  revision        bigint NOT NULL DEFAULT 0,
  UNIQUE (request_id, n)
)
```

`args_digest = md5(args::text)`。`args` 必须是 jsonb 对象。同一 request 至多一行 `leased`。`n` 从 1 连续，与 LLM request 的 `n` 各自计数，上限看 `governance_io`。`fence` 插入时为 1。不接受 FakeTool 上报 cost。

`tool_wait` 不变量：恰一条 `running` 的 `bind_tool` 语句（`child_invoke_id` NULL、`stmt_index` 等于 open request）、恰一条 `open` request、`leased` attempt ≤ 1、无 `suspended` 子等待、无其他 `running` 语句、`repl_exec` 已 enter 无 exit。

## 4. 状态机与转移合同

本节把 §1.2 的控制链落成事务。每个转移是 `v15` 内的一个 `VOLATILE`、`SECURITY DEFINER`、`search_path = pg_catalog` 函数，`EXECUTE` 只授给 `v15_worker`。函数体内不得 `COMMIT`、`ROLLBACK`、打开另一条会话，也不得 `SET ROLE`、`RESET ROLE` 或 `SET SESSION AUTHORIZATION`（§0.20）。worker 把一次转移包在一个显式事务里，函数正常返回后 `COMMIT`。模型语句的保存点由 worker 在事务顶层设置（§4.6），不由内核函数设置。`SET LOCAL ROLE v15_repl` 与配对的 `RESET ROLE` 也只出现在事务顶层。

`pending` 的 invoke 行只出现在 `v15_open_invoke` 的事务内部。提交之后别人看得见的初态是 `runnable`（§3.1）。

### 4.1 总则

**三类失败。** 回滚类、提交类、语句失败的权威分类是 §13 的表。本节只规定转移怎么走，不另列一份穷尽码表。

- **提交类。** 函数正常返回。调用者 `COMMIT`。治理中止、预算耗尽、迭代耗尽、I/O 耗尽、切分失败的结算、挂起、送达，都是提交类：控制行与 `invoke_events` 在同一事务里留下。
- **回滚类。** 函数抛出。调用者 `ROLLBACK`，控制态与调用前一致。
- **语句失败。** 该语句保存点回滚；外层事务提交 `statements.status = failed` 且 `error` 非空。invoke 不因此成为机器故障（§0.7）。

**已存放语句的可执行谓词。** 运行路径只认 `status = 'pending' AND error IS NULL`。`reject_code` 只存在于 `v15_settle_llm` 的入参数组里，不是列，结算提交之后不得再读它（§3.3）。

**身份。** 转移函数的授权谓词是 `session_user = v15_worker`（§0.20）。体内 `current_user` 是 `v15_owner`，MUST NOT 用来识别 worker。`EXECUTE` 被拒绝时抛 `V15_ROLE`。嵌套调用 `v15_on_phase`、`v15_assert_manifest`、`v15_assert_invoke_manifest` 的 `EXECUTE` 只授给 `v15_owner`，无 `GRANT OPTION`。`v15_span_open` 另授 `v15_worker`（§2）。模型面包装的 `current_user` 合同在 §5.1。

**时钟与租约。** 比较和颁发都用 `clock_timestamp()`，不用 `now()`。`lease_until = clock_timestamp() + p_lease`。`p_lease` 必须非空、有限且 `> 0`，否则 `V15_VALUE_INVALID`（回滚类）。worker 默认传入 `30 seconds`。`lease_owner` 是调用者给出的非空文本，长度 1..200，不是数据库角色。

**持有租约的转移必须出示 `p_owner`。** 下列函数的 `p_owner` 必须等于该行当前的 `invokes.lease_owner`：`v15_begin_llm`、`v15_mark_call_started`、`v15_settle_llm`、`v15_begin_exec`、`v15_prepare_statement`、`v15_complete_statement`、`v15_fail_statement`、`v15_suspend_for_child`、`v15_finish_exec`。不相等抛 `V15_INVALID_TRANSITION`，无写入。栅栏不一致且行仍处于本次调用要求的非终态时，抛 `V15_STALE_FENCE`，不得用 owner 码覆盖栅栏码。`v15_reclaim_expired()` 不接收 owner。

**栅栏（§0.5）。** 三套计数互不替代：

| 栅栏 | 存放 | 颁发 |
|---|---|---|
| invoke 租约 | `invokes.fence` | `v15_claim` 加 1。open 插入时为 1，此时尚无持有者。回收把过期租约收回时再加 1 |
| LLM attempt | `llm_attempts.fence` | 每一新行自己的计数，插入时为 1。回收不颁发新行 |
| 语句执行 | `exec_context.revision` | `v15_prepare_statement` 对该后端行加 1 并返回 |

attempt 已是 `unknown`、`failed` 或 `settled` 时，先抛 `V15_ATTEMPT_NOT_SETTLEABLE`，不再用栅栏码覆盖。挂起不加 invoke 栅栏；旧持有者再调用得到 `V15_INVALID_TRANSITION`。旧栅栏不得覆盖新栅栏。

**锁。** 会写 `budget_pools`，或可能写多于一个 invoke 的转移，在任何控制行写入之前按此顺序取锁：

1. 无锁读出将要写的 id：自身、`parent_invoke_id` 链上的全部祖先、这些行中仍非终态的后代、以及这些 invoke 的非空 `pool_id`。
2. 按 `pool_id` 升序 `FOR UPDATE` 锁池。
3. 按 `invoke_id` 升序 `FOR UPDATE` 锁第 1 步的全部 invoke。
4. 重读 fence、status、`lease_owner`、父链与池。fence 与出示值不一致则 `V15_STALE_FENCE`。`p_owner` 与 `lease_owner` 不一致则 `V15_INVALID_TRANSITION`。图比第 1 步多出未锁的 invoke，或状态已不满足该函数前置，则 `V15_INVALID_TRANSITION`。不得在持有 invoke 锁之后再去锁池。

`v15_on_phase` MUST NOT 锁 `invokes`。它对池的 `UPDATE` 只发生在调用方已经按上面的顺序持有该池锁的事务里。

适用这一顺序的函数：`v15_begin_llm`、`v15_begin_exec`（其 abort 路径写父）、`v15_settle_llm`、`v15_finish_exec`、`v15_reclaim_expired`、`v15_suspend_for_child`、`v15_prepare_statement`。`v15_prepare_statement` 也走这一顺序，因为同一语句事务里的挂起或子终态可能接着写祖先。`v15_claim` 是例外：只对目标行 `SELECT … FOR UPDATE SKIP LOCKED`，不碰池。

`governance_manifest` 的存在性检查用 `SHARE`，并且在上述排他锁之前。`v15_repl` 没有 advisory lock（§2）。

**lock_timeout。** 除模型语句事务外，转移事务的第一条语句是 `SET LOCAL lock_timeout = '2s'` 与 `SET LOCAL statement_timeout = '30s'`。事务内等锁超过 2 秒（`55P03`）由该函数改写成 `V15_INVALID_TRANSITION`（回滚类）。`40001` 与 `40P01` 若在 `COMMIT` 时才出现，SQL 函数改写不了它们。worker 把这两个 sqlstate 当成可重试的事务级信号：整段事务已回滚，worker 从头重试该转移，MUST NOT 把它们记成 `V15_INVALID_TRANSITION`，也 MUST NOT 据此把 attempt 收成 `unknown`。模型语句事务同样设置 `lock_timeout = '2s'`；其 `statement_timeout` 由 §4.6 覆盖。

**修订。** 凡 `UPDATE` 带 `revision` 的控制行，同一条语句把 `revision` 加 1。`INSERT` 使用默认 0。blackboard 的 UPSERT、`hook_counters`、`llm_attempts`、`llm_requests`、`iterations`、`statements`，以及 §4.10 的全部修理 `UPDATE`，一律 `revision = revision + 1`。

**事件。** 只追加 `invoke_events`（§3.9）。调用方持有该 invoke 的行锁时取 `seq = coalesce(max(seq), -1) + 1`，从 0 起无洞。`payload` 至少是 `{}`。`outcome` 只用小写 `completed`、`aborted`、`failed`（§0.24）。`exit` 行在对应的 `v15_on_phase(..., 'exit', ...)` 之前写入。每个写 `exit` 事件的关闭路径，包括深度守卫失败与 `invoke/enter` abort，都在事件之后调用该 phase。`io` 恰好是 `{"outcome"}`；`outcome` 按 `fatal` 取 `failed` 或 `aborted`。`llm_query/exit` 豁免这个信封，用 §9.1 的 `{attempt_id}`，可为 JSON `null`。handler 仅可写黑板（§4.3、§9.1）。`exit` 不允许 `abort`（§9.4）；handler 在 `exit` 返回 `abort` 则阶段失败 `V15_INVALID_EFFECT`，整笔回滚，刚才的 `exit` 行不提交。`v15_span_open(invoke_id uuid, span text) returns boolean` 为只读：该 `span` 已有 `enter` 且其后没有 `exit`。它不是第二张真相表。

**阶段返回。** dispatcher 返回给转移的 jsonb 键只允许：`contract`、`action`、`fatal`、`code`、`messages`、`exec_result`、`recursion_available`、`input_adds`、`input_drops`、`blackboard_writes`、`budget`。没有 `error`，也没有 `message_drops`。`contract` 必须为 1。`action` 为 `proceed` 或 `abort`。`abort` 时还必须有布尔 `fatal` 与文本 `code`。形状不符抛 `V15_PHASE_CONTRACT`（回滚类）。stage 1 至 8 的函数体固定返回 `{"contract":1,"action":"proceed"}`。

内核在调用 `v15_on_phase` **之前**执行对应上限；hook 可以更早 `abort`，不能取消内核已经做出的中止。`action = abort` 是提交类。写入 `invokes.error.code` 的值就是返回值的顶层 `code`。该码必须属于 §9.5 的可保留集合，或者是 `V15_HOOK_ABORT`。hook 返回集合外的码，或数个 abort 规范化后的码不一致时，dispatcher 已经把顶层 `code` 收成 `V15_HOOK_ABORT`（§0.12、§9.5）。转移 MUST NOT 把回滚类码写进已提交的 `error`。`fatal` 取返回值，内核预算失败另强制 `fatal = true`。baseline handler 抛出的异常是 `V15_GOVERNANCE_FAULT`（回滚类，§0.15）。

**子终态清单。** 本事务若把任一 `parent_invoke_id` 非空的 invoke 写成 `completed`、`failed` 或 `aborted`，提交前必须在同一事务执行 §4.8。适用的路径包括：子 open 的守卫或 `invoke/enter` abort、`v15_begin_llm` 的迭代上限与 I/O 耗尽、阶段 abort、预算 fatal、`v15_settle_llm` 的金额超限、`v15_finish_exec`、以及回收把子行收成终态。非 fatal 时，父语句的 `error.code` 是 `V15_CHILD_ERROR`。唯一的例外是子仍为 `completed`、但 `bind_name` 已被非 `var` 占用：父语句码是 `V15_DELIVERY_CONFLICT`。子行保留自己的 `error.code`，父语句不得抄写它。`fatal = true` 不写 `V15_CHILD_ERROR`：父、祖先与仍非终态的后代改为 `aborted`，父的 `error.code` 是触发 fatal 的那个码。

**预算。** 带 `budget` 的那次阶段调用是 `llm_query/send`。dispatcher 在落地 enter 或 send 的任何效应之前，先做唯一的预留 `UPDATE`（§4.5.4、§9.6）。影响 0 行：两份尚未落库的效应都不写，不插入 attempt，走 `V15_BUDGET_EXHAUSTED` 且 `fatal = true`。预留成功之后，dispatcher 才写持久 hook 消息与其余效应。`v15_begin_llm` 不再对池做第二次 `UPDATE`，也不得自己 `INSERT` hook 消息。重试不调用 `v15_on_phase`，由 `v15_begin_llm` 按上一行存放的 `reserved_calls` 与 `reserved_cost` 做那一次预留。`pool_id` 为空则跳过池上的 `UPDATE`，两列仍写入 attempt。`prompt_tokens` 与 `cost_usd` 一旦出现，必须 `>= 0`。

**scratch。** open 以 definer 创建 schema，owner 是 `v15_owner`，名字 `s_` 加 `invoke_id` 的 32 位小写十六进制（§0.26）。终态删除由同一 definer 转移执行 `DROP SCHEMA … CASCADE`。执行身份就是 `v15_owner`，因为函数是 `SECURITY DEFINER`。不得在函数内 `SET ROLE`，不得先以 `v15_repl` 删对象，不得 `REASSIGN OWNED`。不存在 `v15_owner` 对 `v15_repl` 的成员关系。级联删除不另查 schema 内对象的属主；§17 的探针证明 PostgreSQL 18.4 如此。探针若失败，唯一后备是 worker 在该终态事务的顶层、任何函数之外执行 `SET LOCAL ROLE v15_repl`、`DROP SCHEMA … CASCADE`、`RESET ROLE`。那不是常规路径。

**invoke 状态。**

```text
(open 事务内) pending ──提交──► runnable
runnable ──claim──► leased
leased ──挂起且子未终态──► suspended
leased ──挂起且等外部工具──► tool_wait
suspended ──送达：子成功，或子非 fatal 失败，或名字冲突的非 fatal 收束──► runnable
tool_wait ──工具送达成功，或非 fatal 工具收束──► runnable
leased ──finish return──► completed
leased ──finish raise，或非 fatal 的上限中止──► failed
leased 或 suspended 或 tool_wait ──fatal──► aborted
```

`completed` / `failed` / `aborted` 没有出边。`suspended` 与 `tool_wait` 都不可 claim（§0.10）。`tool_wait` 不是 `suspended`：无子 invoke，扫描与 claim 都把它当不可调度。

**iteration 状态。**

```text
pending ──begin_llm──► llm ──settle──► executing
executing ──挂起──► suspended ──送达成功──► executing
executing 或 suspended ──finish / 非 fatal 子失败 / 语句失败收束──► done
```

`done` 必有 `result_kind`（§3.2）。每次把迭代置为 `done` 的同一事务写 `repl_history` 一行（§0.27）。

**attempt 状态。**

```text
begin_llm 插入 ► leased (call_started = false, fence = 1)
    ├─ 本进程 mark_call_started ► leased (call_started = true) ─ settle ► settled
    ├─ reclaim，call_started = false ► failed
    └─ reclaim，call_started = true  ► unknown
同一 request 的下一行只由之后的 begin_llm 插入，回收不插入
```

`settled`、`failed`、`unknown` 没有出边（§0.6）。

### 4.2 内核签名

```text
v15_open_invoke(
  p_invoke_id uuid,
  p_config_scope_id uuid,
  p_local_layer_id uuid,
  p_inputs jsonb,
  p_pool_id uuid,
  p_ceilings jsonb,
  p_system text,
  p_user text
) returns uuid

v15_claim(p_invoke_id uuid, p_owner text, p_lease interval) returns bigint

v15_begin_llm(
  p_invoke_id uuid,
  p_fence bigint,
  p_owner text,
  p_base_messages jsonb
) returns jsonb

v15_mark_call_started(
  p_attempt_id uuid,
  p_attempt_fence bigint,
  p_invoke_fence bigint,
  p_owner text
) returns void

v15_settle_llm(
  p_attempt_id uuid,
  p_attempt_fence bigint,
  p_invoke_fence bigint,
  p_owner text,
  p_response jsonb,
  p_statements jsonb
) returns void

v15_begin_exec(p_invoke_id uuid, p_fence bigint, p_owner text) returns void

v15_prepare_statement(
  p_invoke_id uuid, p_fence bigint, p_owner text, p_stmt_index int
) returns jsonb

v15_complete_statement(
  p_invoke_id uuid,
  p_fence bigint,
  p_owner text,
  p_stmt_index int,
  p_statement_fence bigint,
  p_status text,
  p_error jsonb
) returns void

v15_fail_statement(
  p_invoke_id uuid,
  p_fence bigint,
  p_owner text,
  p_stmt_index int,
  p_error jsonb
) returns void

v15_suspend_for_child(
  p_invoke_id uuid,
  p_fence bigint,
  p_owner text,
  p_stmt_index int,
  p_statement_fence bigint,
  p_child_inputs jsonb,
  p_child_system text,
  p_child_user text
) returns uuid

v15_finish_exec(p_invoke_id uuid, p_fence bigint, p_owner text) returns void

v15_reclaim_expired() returns int

v15_span_open(p_invoke_id uuid, p_span text) returns boolean

v15_next_runnable() returns setof uuid

v15_suspend_for_tool(
  p_invoke_id uuid,
  p_iteration int,
  p_stmt_index int,
  p_owner text,
  p_args jsonb
) returns jsonb

v15_next_tool() returns setof uuid

v15_begin_tool(
  p_invoke_id uuid, p_owner text, p_lease interval
) returns jsonb

v15_mark_tool_started(
  p_attempt_id uuid, p_fence bigint, p_owner text
) returns void

v15_settle_tool(
  p_attempt_id uuid, p_fence bigint, p_owner text, p_result jsonb
) returns void
```

`v15_claim` 未抢到时返回 SQL NULL，不是异常。`v15_begin_llm` 成功插入时返回的 jsonb 至少含 `attempt_id`、`request`、`logical_digest`、`input_chars`、`n`、`action`。`action` 为 `proceed`。提交类结束、没有新 attempt 时，`attempt_id` 为 JSON `null`，`action` 为 `abort`，并含布尔 `fatal` 与文本 `code`。worker 只把 `action = proceed` 的返回值交给后续的 mark 与 FakeLLM。

`v15_prepare_statement` 返回的 jsonb 恰好四个键：`statement_fence`、`timeout_ms`、`kind`、`scratch_schema`。`timeout_ms` 是进程截止时间的毫秒数（§4.6）。函数 MUST NOT 在体内 `set_config`。`v15_suspend_for_child` 返回子 `invoke_id`；子在本事务内已经终态时仍然返回该 id。`v15_reclaim_expired()` 返回本事务收成终态的 attempt 行数，不是插入行数。没有 attempt 被终结、但有 invoke 租约被收回时，返回 0，租约收回仍然提交。

子 invoke 没有公开的 open 入口。`v15_open_invoke` 只创建根。插入子行的唯一路径是 `v15_suspend_for_child`（§4.7）。

### 4.3 `v15_open_invoke`

一个事务。根的 `depth = 1`，`root_invoke_id = invoke_id`，`parent_invoke_id` 与 `parent_iteration` 都为空。本函数不持有租约，没有 `p_owner`。

**前置。**

1. `session_user = v15_worker`。
2. `v15_assert_manifest()`：单例行存在，四项上限都 `>= 1`，且单例上存放的 `manifest_digest` 与这四项的重算一致。否则 `V15_GOVERNANCE_MISSING`（§3.13）。
3. `p_ceilings` 为 SQL NULL，或只含 `max_iterations`、`max_depth`、`max_io_attempts`、`max_statement_ms` 的 jsonb 对象。出现的值必须是 `>= 1` 的整数，且小于等于清单上的对应值。更大抛 `V15_GOVERNANCE_RAISE`。缺键表示采用清单值。这四项不是 config 键（§8.4）。
4. 按 §8 折叠 `p_config_scope_id` 与 `p_local_layer_id`，深度取 1。折叠失败则本事务无行。
5. `p_inputs` 是 jsonb 数组，元素为对象，键只允许 `name`、`kind`、`value`、`show_in_prompt`、`tool_id`、`provenance`。`kind` 只允许 `input`、`scope`、`tool`。`input` 的 `provenance` 必须是 `explicit`；`scope` 的必须是 `scope`；`tool` 的必须是 `explicit` 或 `scope`。`value` 不得为 SQL NULL（jsonb 的 `null` 允许）。名字服从 §5.2。同一 `name` 出现两次，或一个名字同时来自 `explicit` 与 `scope`，抛 `V15_SCOPE_CONFLICT`。`kind = tool` 当且仅当 `tool_id` 指向 `tool_catalog`。
6. `p_system` 为非空文本。`p_user` 为 SQL NULL 或文本。它们是 worker 在调用前按 §6.5 从这份 `p_inputs` 渲染的种子，SQL 不调用渲染器。

**写入。**

- 插入 `invokes`：事务内先用 `pending` 建造。`lease_owner` 与 `lease_until` 为空，`fence = 1`，`fatal = false`，`return_value` 与 `error` 为空，`revision = 0`。
- `resolved_config`、`config_digest` 取 §8 的快照。`manifest_digest` 是**有效**上限对象的摘要（§8.5），不是 `governance_manifest.manifest_digest` 的拷贝。`recursion_available = (depth < effective max_depth)`。
- `CREATE SCHEMA` scratch，owner 为 `v15_owner`。此时不向 `v15_repl` 授予 `USAGE` 或 `CREATE`。
- 插入 `iterations`：`(invoke_id, 0, status pending, resume_stmt 0, capture '')`。
- 插入 `bindings`。`kind = tool` 且 `provenance` 为 `scope` 或 `explicit` 的行，同时插入 `tool_grants`。`show_in_prompt` 照调用方的布尔值存放。
- 按 §8.6 安装 hook 行。
- 内核深度守卫在 `v15_on_phase` 之前。`depth > effective max_depth` 时不调用 handler，走下面的提交类关闭，码为 `V15_RECURSION_EXCEEDED`，`fatal = false`。根在 `max_depth >= 1` 时到不了这里；例程仍保留此守卫，供 §4.7 的子路径调用。
- 守卫通过才调用 `v15_on_phase(invoke_id, 0, 'invoke', 'enter', '{"depth": <depth>}')`。`io` 只有 `depth`。返回 `abort` 时按返回的 `fatal` 与 `code` 走同一套提交类关闭。`fatal = false` 的 invoke 状态是 `failed`；`fatal = true` 是 `aborted`。
- 关闭写入：当前迭代 `done` / `result_kind = continue`；`repl_history` 的 `llm_response` 与 `repl_output` 都是 `''`，`repl_exception` 为该 `error`；`DROP SCHEMA … CASCADE`；不写种子消息。根没有父。子路径的送达在 §4.7，不在本函数对根的调用里。这是提交类。提交可见状态就是该终态，不是 `runnable`。
- `proceed` 时：`v15_on_phase` 对 `invoke/enter` 只应用 input、recursion、blackboard，并返回 `messages`，不写 `llm_messages`。然后本函数插入 `seed:system`：`msg_seq = 0`，`message_id = seed:system`，`role = system`，`kind = seed`，`iteration` 为空，`content = p_system`。`p_system` 是 open 时的转录种子，渲染用 `depth < effective max_depth`；其后 enter 的 `disable_recursion` 不改写它。若效应后仍存在 `show_in_prompt` 的输入，再插入 `seed:inputs`：`msg_seq = 1`，`role = user`，`kind = seed`，正文按 §6.5 的 user 段从这些输入组成，因此 enter 的 `input_adds` 进入 inputs 种子。返回的持久消息按 `max(seq)+1` 插入，`kind = persistent_hook`，`message_id` 为效应的 id。SQL 不调用 Python 渲染器。然后把状态写成 `runnable`。

**事件。** `proceed`：`seq 0`，`span = invoke`，`phase = enter`，`payload` 含 `depth`、`config_digest`、`manifest_digest`。守卫失败或 `abort`：同一事务先有这条 `enter`，再写 `phase = exit`。`fatal = false` 时 `outcome = failed`；`fatal = true` 时 `outcome = aborted`。`payload.code` 为关闭码。不写 `llm_query` 或 `repl_exec`。写了 `exit` 事件之后必须调用对应 exit phase，`io` 恰好是 `{"outcome": <failed 或 aborted>}`，按 `fatal` 取值。handler 仅可写黑板（§4.1、§9.1）。

### 4.4 `v15_claim`

一个事务。

**前置。** `session_user` 为 worker。目标行 `status = runnable`，且 `lease_owner` 为空或 `lease_until <= clock_timestamp()`。用 `SELECT … FOR UPDATE SKIP LOCKED` 锁这一行。锁不到或状态不对：返回 SQL NULL，无写入、无事件。`suspended`、`tool_wait`、未过期的 `leased`、以及终态都走这条路径，不抛错。`SKIP LOCKED` 不等待，因而不吃满 `lock_timeout`。

**写入。** `fence := fence + 1`，`status = leased`，`lease_owner = p_owner`，`lease_until = clock_timestamp() + p_lease`，`revision` 加 1，`updated_at` 刷新。不修改迭代与语句。

**事件。** 一行 `audit`，`payload = {"op":"claim","fence":<新值>,"owner":<p_owner>}`。

返回新 `fence`。同一持有者对已经 `leased` 且未过期的行再次 claim 得不到行，因此 claim 不是幂等的。`v15_next_runnable()` 不返回 `leased` 行；过期租约要先经 §4.10 才回到 `runnable`（§0.23）。

### 4.5 LLM 窗口

三次独立事务：`v15_begin_llm`，然后 `v15_mark_call_started`，然后才是 FakeLLM，然后 `v15_settle_llm`。FakeLLM 所在的会话里没有打开的事务（§0.4）。worker 在转移事务里渲染 `p_base_messages` 只是本地 CPU。本节每条把 invoke 写成终态的路径都服从 §4.1 的子终态清单。

#### 4.5.1 `v15_begin_llm`

**锁。** 按 §4.1 的全序，在调用 `v15_on_phase` 之前完成。`p_owner` 必须等于 `lease_owner`。

**前置。** invoke `status = leased`，`fence` 匹配，租约未过期。租约已过期抛 `V15_INVALID_TRANSITION`，不得在过期租约上开 attempt。`v15_assert_manifest()` 与 `v15_assert_invoke_manifest(invoke_id)` 都通过；后者失败为 `V15_MANIFEST_DIGEST`（§11.1）。

迭代与 request 只允许两种形状，否则 `V15_INVALID_TRANSITION`：

1. **首次。** 迭代 `pending`，没有本迭代的 `llm_requests`，`v15_span_open(llm_query)` 为假。
2. **重试。** 迭代 `llm`，`llm_requests.status = open`，不存在 `status = leased` 的 attempt，`v15_span_open(llm_query)` 为真。

已有 `leased` attempt 时不得插入，也不得采纳。那一行要么由本进程接着 mark，要么留给 §4.10。

**内核上限，在 `v15_on_phase` 之前，且在预留之前。**

- `iteration >= effective max_iterations`：提交类中止，`fatal = false`，`error.code = V15_ITERATION_EXCEEDED`。不插入 attempt，不预留，不写 hook 消息。首次路径此时 `llm_query` 未打开，不补它的 `enter`。关闭形状见下。有父则 §4.8，父语句码为 `V15_CHILD_ERROR`，子行保持 `V15_ITERATION_EXCEEDED`。
- `next_attempt_n > effective max_io_attempts`：不插入、不预留。request 置 `exhausted`。invoke `failed`，`fatal = false`，`V15_IO_EXHAUSTED`。重试路径上 `llm_query` span 已经打开：先写 `exit` 行，`outcome = failed`，再调用 `llm_query/exit`（只能黑板写）。然后同样关闭 `invoke` span。删 scratch。有父则 §4.8，父语句码为 `V15_CHILD_ERROR`，子行保持 `V15_IO_EXHAUSTED`。

`next_attempt_n` 在首次为 1，在重试为该 request 上 `max(n) + 1`。`max_io_attempts >= 1` 时首次不会被这条拒绝。重试不调用 `governance_io`，因为不再发 `enter`；内核这条比较仍然生效。

迭代上限、I/O 耗尽、`input_chars` 超限、enter/send abort、预算 abort，以及 §4.6.1 的 phase abort，这些提交类终态关闭统一用 §4.3 的关闭形状（`llm_query/exit` 的信封是 `{attempt_id}`，可为 JSON `null`，不走通用 `{outcome}`）：当前迭代 `done` / `result_kind = continue`（写 `repl_history` 行；尚无助手消息时 `llm_response = ''`，`repl_output = ''`，`repl_exception` 为该 `error`）→ 已打开 span 的 `exit` 事件 → 对应 `exit` phase（仅黑板）→ §4.8 送达。尚未打开的 span 不补 `enter`。清除租约。删 scratch。返回 `action = abort`。不调用 FakeLLM。未产生 attempt 的路径上，`llm_query/exit` 的 `io.attempt_id` 为 JSON `null`（§9.1）。

**首次路径。**

1. 校验 `p_base_messages`：jsonb 数组，元素为对象，键只允许 `message_id`、`role`、`kind`、`content`。`role` 属于 `system`、`user`、`assistant`。`kind` 属于 `system`、`input`、`assistant`、`observation`、`persistent_hook`。`transient_hook` 不得出现在 base 里。`message_id` 与顺序必须与已存放的 `llm_messages` 一致：首元素 `seed:system`；若有第二类种子则为 `seed:inputs`；助手为 `iter:<iteration>:assistant`；观测为 `iter:<iteration>:observation`；持久 hook 行保持其 hook id。数组内 `message_id` 唯一。SQL 不按 worker 数组重排，也不写 system 字节。请求元素的 `kind` 按映射校验：`seed:system` → `system`，`seed:inputs` → `input`，其余 id → 存储行的 `kind`。不要求与库内 `kind` 逐字节相等。种子在 `llm_messages` 里仍是 `kind = seed`。请求里的 kind 是映射，不是存储列的拷贝（§3.4、§4.5.1）。worker 已把重渲染的 system 正文放进 `seed:system` 元素（§6.5）。数组为空，或 id、顺序与 `llm_messages` 不一致：`V15_VALUE_INVALID`（回滚类）。
2. `input_chars` 是这些元素 `content` 的 `char_length` 之和。它大于已冻结的 `protocol.max_invoke_input_length` 时，提交类中止，`fatal = false`，`V15_VALUE_INVALID`，不发 `enter`，不插入 attempt。有父则 §4.8，父语句码为 `V15_CHILD_ERROR`。SQL MUST NOT 截断、改写或重排传入的 base 数组，包括不改 system 字节。截断与 system 重渲染只发生在 worker 构造这份数组之前（§6.5）。
3. `base_digest` 是下面信封的 `md5(jsonb::text)`，十六进制小写。信封里没有 `attempt_id` 这个键，不是 JSON `null`：

```text
{"messages": [ {seq, message_id, role, kind, content}, ... ]}
```

4. 写 `llm_query/enter` 事件，再调用 `v15_on_phase`，`io` 恰好是 `{"iteration": <n>, "next_attempt_n": <next>}`。这次调用的效应只留在返回值里，先不落库。`abort` 则丢弃该返回值里的其余效应，按 `fatal` 与 `code` 走上面的关闭形状，不预留，不插入。有父则 §4.8。
5. `enter` 为 `proceed` 时，写 `llm_query/send` 事件，再调用 `v15_on_phase`。enter 调用本身不落库任何效应。`io` 恰好含 `iteration`、`logical_digest`、`input_chars`、`enter_messages`、`enter_overlay`。`enter_messages` 只携带 enter 的消息列表，无消息时为 JSON `null`。`enter_overlay` 是对象或 JSON `null`，只含可缺的 `recursion_available` 与可缺的 `blackboard_writes` 数组；`llm_query/enter` 不允许 `add_inputs`，故不携带输入。两键都排除在 handler 快照之外。send handler 的快照是基线加上 `enter_overlay` 的内存叠加：handler 可见，库不可见。这里的 `logical_digest` 只覆盖 base。`send` 返回 `abort` 则这些效应从未写入，不预留，不插入，并按上面的关闭形状结束。有父则 §4.8。
6. `send` 为 `proceed` 时，预留写者见 §9.6，这里不重述。更新到 0 行：只返回 `action = abort`（`fatal = true`、`code = V15_BUDGET_EXHAUSTED`），enter/send 效应从未写入，不把 invoke 置终态。终态行与 §4.8 由 `v15_begin_llm` 按上面的关闭形状写，fatal 路径干净提交（§0.12）。不插入 attempt。有父则 fatal 展开已经覆盖送达，不再把父语句写成 `V15_CHILD_ERROR`。
7. 预留成功后是唯一落库点：先落 `enter_overlay` 一次，再落 send 自身的非消息效应，再把 `enter_messages` 与 send 的持久消息按 `max(seq)+1` 写入 `llm_messages`。`v15_begin_llm` 不执行这些 `INSERT`。然后才 `INSERT` attempt：`n = next_attempt_n`，`status = leased`，`fence = 1`，`call_started = false`，`calls_charged = false`，`lease_owner = p_owner`，`lease_until` 与 invoke 租约相同，`pool_id` 复制自 invoke，`reserved_calls` 与 `reserved_cost` 为刚刚预留的数量。

最终 `request.messages` 按此顺序拼接，不得再按 `msg_seq` 把刚插入的持久行读回来：

1. base，即校验后的 `p_base_messages`。它的快照取在本轮 hook 插入之前，因此不含本轮新持久行。
2. enter 返回值里的 `messages`，瞬态与持久都在，顺序见 §9.5。
3. send 返回值里的 `messages`，同样含瞬态与持久。

`persistent = false` 的元素 `kind = transient_hook`，只进 `request`。`persistent = true` 的元素既已在 `llm_messages`，也按上面的位置进 `request`，不得出现第二次。然后：

```text
request = {"attempt_id": <新 uuid>, "messages": [ ...最终数组... ]}
logical_digest = md5( (request - attempt_id)::jsonb::text )
```

合成后的 `message_id` 必须唯一，否则 `V15_VALUE_INVALID`（回滚类），预留随事务消失。`logical_digest` 写入新的 `llm_requests` 行，`status = open`。没有 enter/send 追加时，它等于 `base_digest`。FakeLLM 以后只用存放的这份最终摘要。迭代改为 `llm`。返回 `action = proceed` 与该 `request`、`logical_digest`、`input_chars`、`attempt_id`、`n`。

**重试路径。** 不读 `p_base_messages` 的内容（调用方仍须传一个 jsonb，可以是 `[]`）。不写 `enter` / `send`，不调用 `v15_on_phase`，不插入 `llm_messages`。复制上一 attempt 的 `messages` 与 `reserved_calls`、`reserved_cost`，换新的 `attempt_id`，按 §4.5.4 用这两列做唯一的预留。预留失败则走上面的 fatal 关闭，不插入，尚未复制出的新行不留下。成功则插入 `n + 1`、`fence = 1` 的 `leased` 行。重算的 `logical_digest` 必须等于 `llm_requests.logical_digest`，否则 `V15_VALUE_INVALID`（回滚类）。不得改写 request 行上的摘要。`input_chars` 按复制出的 `messages` 的 `content` 再求和，只放进返回值。

**事件。** 首次且 `proceed`：`llm_query/enter`，`llm_query/send`，然后 `audit` `{"op":"attempt_leased","attempt_id":...,"n":...}`。重试且 `proceed`：只有 `audit` `{"op":"attempt_leased","attempt_id":...,"n":...}`。回收时的 `retry` 事件仍在 §4.10，其 `new_attempt_id` 为 JSON `null`。

#### 4.5.2 `v15_mark_call_started`

独立事务，紧挨在 FakeLLM 之前。attempt `leased`，attempt 栅栏匹配，`call_started = false`，invoke 仍为同一 `lease_owner`（等于 `p_owner`）且 invoke 栅栏匹配、租约未过期。写入：`call_started = true`，`revision` 加 1。已是 `true` 则 `V15_INVALID_TRANSITION`。事件：`audit` `{"op":"call_started","attempt_id":...}`。

此位一旦提交，该 attempt 的终态只允许 `settled` 或 `unknown`（§0.6）。worker 只有在**这一次调用**把 false 提交成 true 之后，才可以调用 FakeLLM。本进程没有执行这次 mark、却看见 `call_started = true` 的，MUST NOT 调用 FakeLLM，也 MUST NOT 结算；留给租约过期。

#### 4.5.3 `v15_settle_llm`

**锁。** §4.1 全序，先于记账。`p_owner` 必须等于 `lease_owner`。

**前置。** attempt 与 invoke 两个栅栏都匹配；attempt `status = leased`；`call_started = true`；invoke `leased` 且租约未过期。`status` 已是 `unknown`、`settled` 或 `failed`：抛 `V15_ATTEMPT_NOT_SETTLEABLE`，即使栅栏也是旧的；不得写 `llm_messages`（§0.6）。`call_started = false`：`V15_INVALID_TRANSITION`。本函数不调用两道清单断言。

`p_response` 必须是含文本键 `content` 的对象。`prompt_tokens` 缺省 0，`cost_usd` 缺省 0。出现时必须 `>= 0`，否则 `V15_VALUE_INVALID`（回滚类）。`content` 里的每个 NUL 在进入 SQL 之前已由 worker 换成六字符 `\u0000`（§6.1）。

`p_statements` 是 jsonb 数组。元素形状是 `{sql, sql_digest, kind, bind_name, arg_sql, reject_code}`。`sql_digest` 必须等于 `md5(sql)`，`kind` 必须是 §3.3 的枚举，下标从 0 连续。`sql` 不得含 NUL。不符抛 `V15_VALUE_INVALID`（回滚类）。SQL 不再次切分（§0.18）。`reject_code` 为空，或是 `V15_INVOKE_FORM`、`V15_DIALECT`、`V15_DDL`、`V15_VALUE_INVALID` 之一。

入参里规范且 `reject_code` 为空的 `bind_invoke`：`bind_name` 与 `arg_sql` 都非空。`assign` 在抽得出目标名时填写 `bind_name`，并在抽得出表达式时填写 `arg_sql`。`print`、`return`、`raise` 的 `bind_name` 为空，`arg_sql` 为抽得的表达式或 NULL。其他 `kind` 的 `bind_name` 为空。这些字段写入 `statements` 之后，运行路径只看 `status` 与 `error`。

**写入。**

- 记账用该行存放的 `reserved_calls` 与 `reserved_cost`（§4.5.4 的结算式）。`calls_charged` 从 false 改为 true，与 `status = settled` 同一条语句。清空 attempt 的租约。填 `response`、`prompt_tokens`、`cost_usd`。request 改为 `settled`。
- `cost_limit` 非空且结算后 `cost_used` 超过它：attempt 保持 `settled`，invoke 与已锁祖先、非终态后代以 `fatal = true`、`V15_BUDGET_EXHAUSTED` 提交类中止。不写助手消息，不插语句。先写 `llm_query/exit`，`outcome = aborted`，再调用 `exit` phase。并关闭 `invoke` span。服从子终态清单里的 fatal 分支。
- 否则 `v15_on_phase` 的 `llm_query/complete`，`io` 恰好是 `{"attempt_id": <uuid>}`。`abort`：不写转录、不插语句，attempt 保持 `settled`，invoke 按 `fatal` 进入 `failed` 或 `aborted`。先写 `llm_query/exit` 的 outcome（`failed` 或 `aborted`），再调用 `exit` phase。有父则 §4.8：非 fatal 时父语句码为 `V15_CHILD_ERROR`，子行保留 abort 的码。
- `complete` 为 `proceed` 时：先写 `llm_query/exit`，`outcome = completed`，再调用 `exit` phase。然后追加 `llm_messages`，`role = assistant`，`kind = assistant`，`message_id = iter:<iteration>:assistant`，`content` 为响应全文，`iteration` 为当前迭代。按数组插入 `statements`。`reject_code` 为空的元素：`status = pending`，`error` 为空。`reject_code` 非空的元素：`status = failed`，`error.code` 为该码。这是 preclassified 失败。settle 不把其后的行改成 `skipped`。本迭代的错误是下标最小的 `failed` 行。`resume_stmt` 指向最小的尚未 `done`、尚未 `skipped` 的下标。若该行已是 `failed`，它就是当前执行边界上的错误，不执行更后的语句。其后的 preclassified `failed` 与 `pending` 只由 `v15_finish_exec` 按 §4.9 的切点改记 `skipped`。本函数不 skip。invoke 保持 `leased`，栅栏不变。

**事件。** `proceed`：`llm_query/complete`，`llm_query/exit` 且 `outcome = completed`，`audit` `{"op":"statements_stored","count":n}`。

空数组是合法输入，表示空消息（§4.11）。整段切分失败时，数组恰好一个合成元素（§6.1），本函数仍提交。

#### 4.5.4 预留、结算与释放

池行上的数量移动只有下面三种。`pool_id` 为空则整段跳过，attempt 上的两列仍要写。影响 0 行且本应移动已存在的预留时，抛 `V15_INVALID_TRANSITION`（回滚类）。条件更新影响 0 行是池不足，不是这个码；此时本轮尚未落库的 hook 效应保持不写。

预留（govern 体在 `v15_on_phase` 内、且先于落库；重试在 `v15_begin_llm` 内。`v15_on_phase` 桩函数体覆盖 stage 1–8；`v15_begin_llm` 的桩路径预留只在 io stage（6）起实际存在。同一事务对同一次尝试只有一次）：

```text
UPDATE budget_pools
   SET calls_reserved = calls_reserved + reserved_calls,
       cost_reserved  = cost_reserved  + reserved_cost,
       revision = revision + 1
 WHERE pool_id = pool
   AND (calls_limit IS NULL
        OR calls_used + calls_reserved + reserved_calls <= calls_limit)
   AND (cost_limit IS NULL
        OR cost_used + cost_reserved + reserved_cost <= cost_limit)
```

结算（`v15_settle_llm`，调用已经发生）：

```text
calls_reserved -= reserved_calls
calls_used     += reserved_calls
cost_reserved  -= reserved_cost
cost_used      += cost_usd
```

`unknown`（已 `call_started` 的过期行）：`calls_reserved` 减去存放值，`calls_used` 加上存放值，`cost_reserved` 减去存放值，`cost_used` 不变。`failed`（尚未 `call_started`）：只减去两份预留，不增加 `calls_used` 或 `cost_used`。

预留已经写入、而同一事务将以终态提交、且不会留下对应的 `leased` 或 `settled` attempt 时，同一事务从 `calls_reserved` 与 `cost_reserved` 减去存放的预留量，`calls_used` 与 `cost_used` 不动。这条退款 `UPDATE` 与结算 `UPDATE` 都加守卫 `AND calls_reserved >= <reserved_calls> AND cost_reserved >= <reserved_cost>`（§11.3）。差额下穿影响 0 行，抛 `V15_INVALID_TRANSITION`，不得撞 CHECK。回滚类错误不另做退款。`unknown` 不走这条退回，而走上面的转入 `calls_used`。

#### 4.5.5 provider 拒绝与 abandon

这三只函数是 worker 在事务外分类之后调用的转移。它们不调用 provider，也不调用 FakeLLM。`SECURITY DEFINER`，属主 `v15_owner`，`search_path = pg_catalog`。体内不得切换角色。`EXECUTE` 只授 `v15_worker`。

```text
v15_provider_reject_unstarted(p_attempt_id uuid, p_attempt_fence bigint, p_invoke_fence bigint, p_owner text, p_class text) returns void
v15_provider_reject_started(p_attempt_id uuid, p_attempt_fence bigint, p_invoke_fence bigint, p_owner text, p_detail jsonb) returns void
v15_provider_abandon(p_attempt_id uuid, p_attempt_fence bigint, p_invoke_fence bigint, p_owner text, p_detail jsonb) returns void
```

**共用前置。** 顺序照 `v15_settle_llm`，不自造锁。

1. `session_user = v15_worker`，否则 `V15_ROLE`。
2. 参数空，或 `p_owner` 长度不在 1..200：`V15_VALUE_INVALID`。
3. 由 attempt 找到 invoke。找不到：`V15_INVALID_TRANSITION`。
4. 按 §4.1 锁 invoke，再 `FOR UPDATE` attempt。
5. attempt 已是 `unknown`、`failed` 或 `settled`：先抛 `V15_ATTEMPT_NOT_SETTLEABLE`，不看栅栏（§4.13）。
6. 不是 `leased`：`V15_INVALID_TRANSITION`。
7. 栅栏不符：`V15_STALE_FENCE`。
8. owner、租约或 invoke 不是 `leased`：`V15_INVALID_TRANSITION`。
9. `reject_unstarted` 要求 `call_started = false`；另两只要求 `call_started = true`。相反：`V15_INVALID_TRANSITION`。
10. request 必须 `open`，迭代必须 `llm`。否则 `V15_INVALID_TRANSITION`。

`p_class` 或 `p_detail` 非法：`V15_VALUE_INVALID`，整笔回滚，attempt 仍 `leased`。这是 worker 缺陷，不是 provider 结果。

`p_detail` 的键恰好是 `class`、`http_status`、`finish_reason`。多键或少键：`V15_VALUE_INVALID`。

- `reject_started`：`class = http_status` 且 `http_status` 为 400..499 且不是 408 或 429，`finish_reason` 为 JSON null；或 `class = finish_reason` 且值恰好 `content_filter` 或 `model_mismatch`，`http_status` 为 JSON null；或 `class = request_invalid` 且另两键为 JSON null。
- `abandon`：`class = transport` 且 `finish_reason` 为 null，`http_status` 为 null、3xx 或 400；或 `class = http_status` 且状态是 400、408、429 或 500..599，`finish_reason` 为 null；或 `class = finish_reason` 且值属于 `{insufficient_system_resource, aborted, other}`，`http_status` 为 null；或 `class` 属于 `{unpriced, usage_invalid}` 且另两键为 null。
- `reject_unstarted` 的 `p_class` 属于 `{credentials_absent, model_not_allowlisted, model_missing, endpoint_rejected}`。

**unstarted 写入（一个事务）。** 按行上存放的预留调用释放，不计 call、不计 cost。attempt → `failed`，`calls_charged` 保持 false，清空 attempt 租约，`response` 保持 NULL。request → `exhausted`。审计 `{"op":"provider_rejected","attempt_id","class","call_started":false}`。然后 `v15_io_terminal(..., 'V15_PROVIDER_REJECTED', false, attempt_id)`。

**started reject 写入。** 池释放走 unknown 公式：计存放的 calls，cost 增量为 0。attempt → `unknown`，`calls_charged = true`，清空 attempt 租约，`response` 保持 NULL。不得写助手消息，不得插 `statements`。request → `exhausted`。审计同上，但 `call_started` 为 true，并带 `http_status` 与 `finish_reason`（null 用 JSON null）。同一个 `v15_io_terminal(..., 'V15_PROVIDER_REJECTED', false, ...)`。

不写 `llm_query/retry`。这次不是「以后还会 begin」。`v15_io_terminal` 走既有关闭：迭代收成 `done` / `continue`，写 `repl_history`（尚无助手消息则 `llm_response = ''`），invoke `failed`，`fatal = false`，关 `llm_query`（outcome `failed`），关 invoke span，`DROP SCHEMA … CASCADE`。`error.message` 是空串。分类只进审计 payload 的 `class`、`http_status`、`finish_reason`。有父则走 §4.8：父语句 `V15_CHILD_ERROR`，子行保留 `V15_PROVIDER_REJECTED`。`fatal = false`，父不是 `aborted`。本函数不重写送达。

**abandon 写入。** 与 started reject 相同的池释放与 attempt → `unknown`。不把 request 改成 `exhausted`，不调用 `v15_io_terminal`，不调用 `v15_on_phase`（§4.10）。`llm_query/retry` 的 payload 在既有三键之外加嵌套对象：

```text
{"old_attempt_id": <uuid>, "old_status": "unknown", "new_attempt_id": null, "provider": {"class", "http_status", "finish_reason"}}
```

然后调用已有的 `v15_io_reclaim_invoke`。此时没有存活 `leased` attempt，迭代在 `llm`。该函数把 fence 加 1、status 改为 `runnable`、清空 invoke 租约，并写 `lease_reclaimed`。不得再手动 bump 一次。`llm_query` span 保持打开，直到后来的 settle 或 `V15_IO_EXHAUSTED`。

**残留。** exit phase 若返回 abort，既有关闭路径抛 `V15_INVALID_EFFECT`，整笔 reject 回滚，attempt 仍 `leased`。这与 `V15_IO_EXHAUSTED` 的 exit 规则相同。不得为了写上拒绝而跳过 `v15_on_phase`。恢复仍靠租约到期后的 `v15_reclaim_expired`（它不调 phase）。坏的 exit hook 可以把确定性拒绝退回到 unknown 再试。本修订不改 hook 代数。

**同质。** 一个 `agent_v15_*` 库的 worker 池必须同质：全是 FakeLLM，或全是同一个真实 provider。本函数不做 model-aware claim。

### 4.6 执行窗口

本节把 invoke 写成终态时服从 §4.1 的子终态清单。

#### 4.6.1 `v15_begin_exec`

一个事务。`p_owner` 等于 `lease_owner`。invoke `leased`、栅栏匹配、租约未过期；迭代 `executing`；`v15_span_open(repl_exec)` 为假。已打开则 `V15_INVALID_TRANSITION`（送达之后的恢复不得再 `enter`，§0.24）。

先 `v15_on_phase` `repl_exec/enter`，`io` 恰好是 `{"iteration": <i>, "resume_stmt": <k>}`。再 `repl_exec/send`，`io` 恰好是 `{}`。任一次 `abort`：不执行语句，按 `fatal` 与 `code` 走 §4.5.1 的关闭形状（迭代 `done` / `result_kind = continue`，写 `repl_history`；`exit` 事件；`exit` phase 仅黑板；有父则 §4.8）。删 scratch。

零条语句也要打开 span，随后由 `v15_finish_exec` 关闭。

**事件。** `proceed`：`repl_exec/enter`，然后 `repl_exec/send`。

#### 4.6.2 一条模型语句，一个事务

worker 只执行 `kind ∈ (plain, print, assign, return, raise)` 且 `status = 'pending' AND error IS NULL` 且 `stmt_index = resume_stmt` 的行。`kind = bind_invoke` 走 §4.7，不得执行 `statements.sql`。

```text
BEGIN
  SET LOCAL lock_timeout = '2s'
  SELECT v15_prepare_statement(..., p_owner, ...)
  SET LOCAL search_path = <scratch_schema>, pg_catalog
  SET LOCAL statement_timeout = '<timeout_ms + 1000>ms'
  SAVEPOINT model_stmt
  SET LOCAL ROLE v15_repl
  <执行去掉首行 pragma 之后的这一条，不是整段助手消息>
  RESET ROLE
  RELEASE SAVEPOINT model_stmt
  SELECT v15_complete_statement(..., p_owner, ..., 'done', NULL)
COMMIT
```

`search_path` 与 `statement_timeout` 出现在保存点之外，由 worker 在事务顶层执行，不出现在任何函数体内。schema 名用 `quote_ident` 拼进 `SET LOCAL`。`v15_prepare_statement` 若自己 `set_config`，函数退出时会被函数级 `search_path` 还原，模型语句看不见 scratch（§0.26）。

模型语句抛错时：`ROLLBACK TO SAVEPOINT model_stmt`，在顶层 `RESET ROLE`，再 `v15_complete_statement(..., 'failed', error)`，然后 `COMMIT`。保存点之前的 prepare 写入保留。保存点之内的 scratch 写入、binding 与 `capture` 修改全部消失（§0.7）。`failed` 时该行置 `failed` 且 `error` 非空，`resume_stmt` 停在失败行。更晚 `failed` 与 `pending` 的 skip 不在本函数做，只在 `v15_finish_exec` 内完成（§4.9）。迭代保持 `executing`，直到 `v15_finish_exec`。

**prepare 前置。** 已按 §4.1 取锁。`p_owner` 等于 `lease_owner`。invoke `leased` 且栅栏、租约有效；迭代 `executing`；语句满足可执行谓词且下标等于 `resume_stmt`；`v15_span_open(repl_exec)`。否则 `V15_INVALID_TRANSITION`。

**prepare 写入。** 语句 `running`，`revision` 加 1。`INSERT` 或 `UPDATE` 本 `backend_pid` 的 `exec_context`，`revision` 加 1，返回值即 `statement_fence`。授予无 `GRANT OPTION`，且只有 schema 权限：`kind = bind_invoke` 时只 `GRANT USAGE ON SCHEMA`；其他 kind `GRANT USAGE, CREATE ON SCHEMA`。永不 `GRANT` 表级权限。模型随后以 `v15_repl` 创建的对象，DML 来自属主权。不修改 schema owner。不设置 GUC。

**超时。** `timeout_ms = min(有效 max_statement_ms, repl.timeout_ms 若该键存在, pragma 毫秒若存在)`。pragma 规则在 §6.3。返回的 `timeout_ms` 是进程截止时间，从 prepare 返回起算。worker 到点从**另一条**连接调用 `pg_cancel_backend`（§2）。同一条模型连接没有这个函数的 `EXECUTE`。`statement_timeout` 设为 `timeout_ms + 1000` 毫秒，只在进程没能取消时开火。两者都把该语句收成 `V15_STATEMENT_TIMEOUT`。

取消会使整个事务回滚，保存点来不及提交。语句被取消（`57014` 等）时，worker 丢弃该连接，不复用，在新事务调用 `v15_fail_statement` 记 `failed`。超时（进程截止或 `statement_timeout`）归一为 `V15_STATEMENT_TIMEOUT`；其余取消保留原生 sqlstate。目标语句当前可以是 `pending` 且 `error IS NULL`（prepare 已回滚）。后续行的 skip 由随后按 §4.12 调用的 `v15_finish_exec` 完成（§4.9 切点），`v15_fail_statement` 本身不写 skip。bind 路径用同一政策（§4.7）。worker 若已死、来不及记失败，语句仍是 `pending`；invoke 租约过期后由下一持有者重新执行这一条。

**`v15_complete_statement`。** 同一事务、同一 `backend_pid`。`p_owner`、语句栅栏、invoke 栅栏都匹配。语句 `running`。`p_status` 只允许 `done` 或 `failed`。`done` 且 `kind` 不是 `return` 或 `raise` 时，`resume_stmt := stmt_index + 1`。`done` 且 `kind` 为 `return` 或 `raise` 时，`resume_stmt` 等于语句条数。更晚 `failed` 与 `pending` 的 skip 不在本函数做，只在 `v15_finish_exec` 内完成（§4.9）。worker 不做内核表 DML。`failed` 时 `error` 必须非空。无论成败，返回前 `REVOKE` 本事务授出的 schema 权限。不存在表级授权需要收回。`done` 的行不得再执行（§0.7）。

**kind 与函数一致（§0.9、§0.18）。** 当前语句 `kind` 不是 `return` 时，`jaz."return"` 抛 `V15_INVOKE_FORM`。`raise`、`bind_invoke` 同理。worker 把控制语句误标成 `plain` 再执行，不会真的返回或产子。

**`return` / `raise` 的暂存。** 函数在本语句保存点内把值写入 `invokes.return_value` 或 `invokes.error`，不改终态，不关 span。`SELECT (<expr>)` 必须恰好一行。零行或多行是语句失败 `V15_VALUE_INVALID`。`kind` 为 `return` 或 `raise` 的语句标 `done` 之前，必须已经写入 `invokes.return_value` 或 `invokes.error`。形如 `jsonb_array_elements('[]')` 的 SRF 实参使函数未执行时，不得标 `done`，按失败收束（§5.3）。终态只在 `v15_finish_exec`。崩溃窗口里语句已 `done`、invoke 仍 `leased`：恢复路径调用 finish，不重新执行。

**打印与结束（§0.22）。** `jaz."return"` 或 `jaz."raise"` 发现本迭代 `capture <> ''` 时抛 `V15_PRINT_AND_RETURN`。保存点回滚暂存的返回值。外层把该语句记 `failed`。invoke 不因此进入终态。此时不走「成功的 return 跳过后继」那一支。

### 4.7 `v15_suspend_for_child`

一个事务。只用于 `kind = bind_invoke`、`status = 'pending' AND error IS NULL`、`arg_sql` 与 `bind_name` 都非空、下标等于 `resume_stmt` 的语句。worker 不得执行 `jaz.bind_invoke`。本函数服从 §4.1 的子终态清单。

prepare 对这种语句只授予 scratch 的 `USAGE`，不授予 `CREATE`，不授予任何表权限。函数返回后，worker 在同一事务、保存点之内、事务顶层 `SET LOCAL ROLE v15_repl`，执行 `SELECT (<arg_sql>)`。表达式文本是该行已存放的 `arg_sql`。求值结果必须是恰好一行 jsonb。零行或多行是语句失败 `V15_VALUE_INVALID`。然后顶层 `RESET ROLE`。worker 按 §7 的复制规则用父的 scope 快照与这份 jsonb 渲染 `p_child_system` 与 `p_child_user`，再调用本函数。渲染是本地 CPU。

**前置。** 锁已由 prepare 按 §4.1 持有，含祖先链。`p_owner` 等于 `lease_owner`。语句栅栏与 invoke 栅栏匹配，`v15_span_open(repl_exec)` 为真。`recursion_available = false` 时抛 `V15_RECURSION_DISABLED`，不使用 `p_child_inputs`，不插入子行。

**worker 对挂起路径的捕获。** `SELECT (<arg_sql>)` 的任何错误，含上述五码与 PostgreSQL 原生 sqlstate（如 `22012`、`42501`、`42883`），一视同仁。worker MUST 在顶层 `ROLLBACK TO SAVEPOINT`，`RESET ROLE`，再 `v15_complete_statement(..., 'failed', error)`，然后 `COMMIT`。不得留下 `pending` 的 bind 语句无限重试。`v15_suspend_for_child` 抛出 `V15_RECURSION_DISABLED`、`V15_SCOPE_CONFLICT`、`V15_INVOKE_FORM`、`V15_VALUE_INVALID` 或 `V15_GOVERNANCE_RAISE` 时，同样回到保存点并提交 `failed`。子 open 的收紧校验失败不得留在 `pending`。保存点包住求值与 suspend，因此 bind-wait、子行与子 open 一并消失（§0.8）。这五码之外的回滚类错误回滚整笔事务，语句保持可执行谓词，由 worker 重试整段转移，不得把它们记成 `failed`。

**求值背书。** 本阶段没有 `CREATE`，也没有表级授权。已有对象的属主仍是 `v15_repl`，所以只撤销 DML 挡不住写。`jaz.var` 与 `jaz.prior_history` 可读。`jaz.tool`、`jaz.assign`、`jaz.print`、`jaz."return"`、`jaz."raise"`、`jaz.bind_invoke` 抛 `V15_INVOKE_FORM`。分类器还要拒绝 `arg_sql` 里的写记号，以及字符串、注释与 dollar-quote 之外、`(` 前标识符匹配 `nextval`/`setval`/`currval`（含 `pg_catalog.` 限定）的调用（§6.2）。写防护仍是 `pg_stat_xact_user_tables` 加上仅 `USAGE`、无 `CREATE`。`v15_suspend_for_child` 插入子行之前，若 `pg_stat_xact_user_tables` 显示本事务对 scratch 关系有插入、更新或删除，抛 `V15_INVOKE_FORM`。权限失败保持 PostgreSQL 的 sqlstate。来自 `SELECT (<arg_sql>)` 的，包括 `42501`，按上面的捕获提交为该语句的 `failed`，不得整笔回滚后留在 `pending`。同一事务在 prepare 已经写过控制行，不得再 `SET TRANSACTION READ ONLY`。bind 实参求值被取消时，与 §4.6.2 相同：丢弃该连接，不复用，新事务 `v15_fail_statement`；超时归一为 `V15_STATEMENT_TIMEOUT`，其余取消保留原生 sqlstate。

**顺序。** 插入子 invoke 行之后，MUST 立刻把父写成 bind-wait，然后才跑子的 open 守卫与 `invoke/enter`：

1. 插入子行，状态先为构建中的 `pending`，scratch 已建，租约空。
2. 父语句保持 `running`，写入 `child_invoke_id`。父迭代 `suspended`。父 invoke `suspended`，租约清空，`fence` 不加。`resume_stmt` 仍等于该下标。`capture` 保留。
3. 然后再跑 §4.3 的深度守卫与 `invoke/enter`。

子停在 `runnable`，或在这次 open 里进入终态，提交之后都满足 §4.8 对父的结构前提：父曾经是等待这个子的 `suspended`。open 把子收成终态时，同一事务接着做 §4.8，父的 bind-wait 被送达结果覆盖。中间的 bind-wait 不单独提交。

**子行。** `p_child_inputs` 必须是 jsonb 对象，键是 §5.2 的名字，值不是 SQL NULL。否则 `V15_VALUE_INVALID`。这些键成为子的 `kind = input`、`provenance = explicit`、`show_in_prompt = true`。父的 `kind = scope` 按值复制。父的 `kind = tool` 且 `provenance = scope` 连同 `tool_grants` 一起复制。不复制 `kind = input`，不复制 `kind = var`，不复制 `provenance = explicit` 的工具（§0.17）。复制后的名字与新 input 冲突则 `V15_SCOPE_CONFLICT`。

子的 `depth` 为父深度加 1，`parent_invoke_id` 与 `parent_iteration` 指向这一迭代，`root_invoke_id` 与 `pool_id`、`config_scope_id` 照抄，`local_layer_id` 为空。按子深度重新折叠（§8.3）。hook 行按 §8.3 从父的已冻结 propagating 行复制，不重读 layer 的 `extra_hooks`。有效上限是父有效上限与当前清单的逐项较小值，不得放宽。子 `recursion_available` 按子深度冻结。子 scratch、子迭代 0 与根 open 同一规则。`p_child_system` 非空；`p_child_user` 可为 SQL NULL。子种子服从 §4.3：phase 只返回 `messages`，不写 `llm_messages`；然后写 `seed:system`（seq 0，正文 `p_child_system`），效应后仍有 `show_in_prompt` 的输入才写 `seed:inputs`（seq 1），返回的持久消息按 `max(seq)+1` 插入。`input_adds` 进入 inputs 种子。`message_id` 为 `seed:system` 与可选的 `seed:inputs`。worker 预先渲染的 `p_child_user` 不是最终 inputs 种子。

`depth > effective max_depth`，或 `enter` 返回 `abort`：子在本事务内终态关闭（空历史行、`DROP SCHEMA … CASCADE`、span `exit`）。`fatal = false` 时 §4.8 把父收成 continue，父语句码是 `V15_CHILD_ERROR`，子行保留 `V15_RECURSION_EXCEEDED` 或 abort 的码。`fatal = true` 时走 fatal 展开，父的码是 fatal 触发码，不是 `V15_CHILD_ERROR`。这是提交类。函数不把「子已终态、父仍 suspended」留到提交之后。

**父写入（子为 `runnable` 时）。** 第 2 步的 bind-wait 保持到提交。不关闭父的 `repl_exec`（§0.24）。不写 `repl_history`。返回前 `REVOKE` 本事务授出的 schema `USAGE`。成功路径不调用 `v15_complete_statement`。

**事件。** 父：`audit` `{"op":"suspend","child_invoke_id":...,"bind_name":...,"stmt_index":n}`。子：自己的 `invoke/enter`。子未终态时没有父的 `exit`。

`bind-wait` 谓词：语句 `running` 且 `child_invoke_id` 非空，迭代 `suspended`，invoke `suspended`。§3.3 不增加状态值。worker 不得执行处于 `bind-wait` 的语句。

### 4.8 子终态送达

把子 invoke 写成终态的那次事务，在 `COMMIT` 前完成送达。子的终态与父的更新同一提交。父当时必须已经是 `suspended`、无租约，并且 bind-wait 语句的 `child_invoke_id` 就是本子。这就是 §4.7 先写 bind-wait 的原因。子仍为 `runnable` 时本事务只建立这个结构前置，不送达。同事务送达只发生在子已 `completed`、`failed` 或 `aborted` 时。本事务改父，不 claim 父。这是 §0.10 的唯一写例外，只沿 `parent_invoke_id` 向上，并且只在子终态事务里。锁必须已经按 §4.1 持有：子、祖先、这些行的非终态后代，以及涉及到的池。

**结构不符**（父不是 `suspended`，或父的 bind-wait 语句的 `child_invoke_id` 不是本子）：抛 `V15_DELIVERY_CONFLICT`（回滚类）。子的终态一并回滚。不得留下「子已终态、父仍 suspended」的提交。

**子 `completed`，且 `bind_name` 可写。** 在父插入或更新 `bindings`：`name = bind_name`。已有 `kind = var` 则覆盖 `value`，`provenance = delivery`，`revision` 加 1，`show_in_prompt` 保持原值。新行则 `kind = var`，`show_in_prompt = true`，`provenance = delivery`。该语句 `done`，`error` 仍为空，`resume_stmt := stmt_index + 1`，迭代回到 `executing`，`capture` 不改，invoke `runnable`，租约空，父 `fence` 不加。不发父 LLM（§0.2）。不关闭父的 `repl_exec`。不写历史行。事件：父 `audit` `{"op":"deliver","child_invoke_id":...,"bind_name":...}`。

**子 `completed`，但 `bind_name` 已是 `input`、`scope` 或 `tool`。** 不覆盖该 binding。子保持 `completed`，子的 `error` 保持为空。父走与下一段相同的非 fatal 收束，但父语句的 `error.code` 是 `V15_DELIVERY_CONFLICT`，不是 `V15_CHILD_ERROR`。这是提交类。

**子 `failed` 且 `fatal = false`。** 不写 `var`。父语句 `failed`，`error.code = V15_CHILD_ERROR`。子行的 `error.code` 保持原值，可以是 `V15_RECURSION_EXCEEDED`、`V15_ITERATION_EXCEEDED`、`V15_IO_EXHAUSTED`、`V15_RAISE`、`V15_HOOK_ABORT` 或其他提交类码。更大下标、仍可执行的语句 `skipped`。父迭代 `done` / `continue`，`repl_output` 为 §3.6 的完整观测，`repl_exception` 为父语句上的 `V15_CHILD_ERROR` 对象。追加同样正文的观测消息，`message_id = iter:<父迭代>:observation`。插入下一迭代 `pending`。关闭父 `repl_exec`：先写 `exit` 行，`outcome = failed`，再调用 `exit` phase。invoke `runnable`，租约空。`invoke` span 保持打开。事件含 `audit` `{"op":"child_error","code":"V15_CHILD_ERROR"}`。

**子 `fatal = true`，或本次中止本身 `fatal = true`。** 本子、每一级祖先、以及这些行中任一非终态后代，在本事务全部 `aborted`，`fatal = true`，`error.code` 为触发码（预算为 `V15_BUDGET_EXHAUSTED`；阶段 abort 用 dispatcher 的顶层 `code`）。不把父的 `error.code` 改写成 `V15_CHILD_ERROR`。锁定闭包内每个 invoke 的 `running` 语句置 `failed`，`error` 为触发 fatal 的码，更晚语句 `skipped`。不止直接父。清除租约。终态 invoke 不得仍有 `running` 语句，这条覆盖全链。各自未 `done` 的当前迭代置 `done` / `continue` 并写 `repl_history`。仍打开的 span 先写 `exit`，`outcome = aborted`，再调用 `exit` phase。`DROP SCHEMA … CASCADE`。不写 `var`。后代一并关闭，避免父已 `aborted` 时兄弟再送达造成结构冲突后的无限重试。每个被展开的 invoke 另写 `audit` `{"op":"fatal","code":...}`。

非 fatal 的子失败不改祖先（§0.11）。名字冲突同样不改祖先。

### 4.9 `v15_finish_exec`

一个事务。先按 §4.1 取锁，并校验 fence、`p_owner` 与状态。若存在 `done` 的 `return` 或 `raise` 语句，`cut` 等于该语句的 `stmt_index`；否则 `cut = resume_stmt`（失败路径停在失败行上；全部完成或零语句的 continue 路径上 `resume_stmt` 即语句条数，`cut` 不选中任何行）。skip 只作用于 `stmt_index > cut` 的 `pending` 与 `failed`（preclassified）行。不得用 `resume_stmt` 作为 return/raise 情形的切点。执行环（return / raise / continue）内的 skip 唯一执行者是本函数；§4.8 的送达与 fatal 事务在同事务内自行 skip，不经过本函数。然后才做候选校验。`p_owner` 等于 `lease_owner`。invoke `leased`、栅栏匹配、租约未过期；迭代 `executing`；`repl_exec` 已打开。本函数服从子终态清单。三条互斥候选，否则 `V15_INVALID_TRANSITION`：

1. **return。** 存在一条 `kind = return` 且 `done`，没有 `failed`，没有 `pending` 且 `error IS NULL` 的行，也没有 `running`。`invokes.return_value` 非空。后继可以是 `skipped`。
2. **raise。** 与 return 对称，`kind = raise`，`invokes.error` 非空。
3. **continue。** 没有 `return` 或 `raise` 的 `done` 行。要么全部是 `done`（含零条语句），要么恰好一条 `failed`，且它是下标最小的错误；更大下标皆 `skipped`（含到达执行边界时已改记的 preclassified `failed`），更小下标皆 `done`。仍留着未来 preclassified `failed`、而当前边界尚未到它，不是这个形状（§4.12）。

先调用 `repl_exec/complete`。`continue`、`return`、`raise` 都发。`io` 恰好是 `{"result_kind","return_value","error","capture"}`。JSON 里的空值写成 JSON `null`。

- 返回 `abort`：不采用候选。按 `fatal` 与 `code` 做提交类终态，写历史行，先写 `repl_exec/exit` 的 outcome，再调用 `exit` phase，并关闭 `invoke` span。删 scratch。有父则 §4.8。不得先把 invoke 写成 `completed` 再被 abort 覆盖。
- 返回 `exec_result.result_kind = continue`，且候选是 return：清除 `invokes.return_value`，该 `return` 语句保持 `done`，后继保持 `skipped`，改走下面的成功 continue。这是 `budget_forcing` 的出口，也是未达上限的 return 校验的出口（§9.4）。接受这次改写时，本函数对每个被接受的持久消息 id `<hook_key>:<ordinal>:<n>` 调用 `v15_loop_accept_forcing`。该函数只解析 `budget_forcing`、`return_type` 与 `validate_return` family 的三段数字 id，把 `hook_counters` 键 `<hook_key>:<ordinal>` 加一，每消息一次，同一条语句 `revision = revision + 1`。`return_type:prompt:<ordinal>` 一类非计数 id 跳过，不抛 `V15_PHASE_CONTRACT`。dispatcher 不在 `complete` 中改这个计数（§9.6、§10.2）。
- 返回 `exec_result.result_kind = raise`，且候选是 return、`capture = ''`、`return_value` 为 JSON `null`、`error.code = V15_VALIDATION_FAILED`：用 `v15_loop_error` 把该 error 规范化成 `{sqlstate, code, message}`（`sqlstate = P1540`）。同一事务清除 `invokes.return_value` 并写入 `invokes.error`，同时把内存中的 `return_value` 置为 SQL NULL、把内存中的 `error` 置为这份规范化对象，然后改走下面的 raise 分支。不调用计数函数。该 `return` 语句保持 `kind = return`、`status = done`。这不是 abort。
- 其他 `exec_result` 在 §9 已是 `V15_INVALID_EFFECT`，到不了本函数的提交点。

然后写选定的分支，再写 `exit` 行，然后才调用 `exit` phase。

**return。** 迭代 `done` / `return`。`repl_output = ''`，`repl_exception` 为空，`llm_response` 为本迭代助手消息全文。invoke `completed`，`fatal = false`，`error` 为空，清除租约，`DROP SCHEMA … CASCADE`。不追加观测消息。有父则 §4.8 成功送达。

**raise。** 迭代 `done` / `raise`。`repl_output = ''`，`repl_exception` 为内存中的 `invokes.error`（模型 `jaz."raise"` 的 `V15_RAISE`，或 return→raise 改写写入的 `V15_VALIDATION_FAILED`）。invoke `failed`，`fatal = false`，清除租约，删 scratch。有父则 §4.8：父语句码是 `V15_CHILD_ERROR`，子行保留自己的码。

**continue。** 迭代 `done` / `continue`。`repl_exception` 为空时，`repl_output` 等于 `capture`，可以为 `''`。`repl_exception` 非空时，`repl_output` 是 §3.6 的完整观测。追加 `llm_messages`，`role = user`，`kind = observation`，`message_id = iter:<iteration>:observation`，正文等于这份 `repl_output`。观测在 `llm_messages` 与 `repl_history` 里都是全文；截断只发生在下一次组 base 时（§6.5）。插入下一号迭代，`pending`，`resume_stmt = 0`，`capture = ''`。invoke `runnable`，租约空，`fence` 不加。不关闭 `invoke` span。不删 scratch。

**事件与 exit outcome。** gate 按下表断言。`exit` 行先于 `exit` phase 的调用。

| 路径 | `repl_exec/complete` | `repl_exec/exit` | `invoke` span |
|---|---|---|---|
| return，未被改写 | 发出 | `completed` | `complete`，然后 `exit` `completed` |
| raise | 发出 | `failed` | 只 `exit` `failed`，不写 `invoke/complete` |
| continue，无失败语句 | 发出 | `completed` | 保持打开 |
| continue，本迭代有失败语句 | 发出 | `completed` | 保持打开 |
| `exec_result` 把 return 收成 continue | 发出 | `completed` | 保持打开 |
| `exec_result` 把 return 收成 raise | 发出 | `failed` | 只 `exit` `failed`，不写 `invoke/complete` |
| `complete` 本身 `abort`，`fatal = false` | 发出 | `failed` | `exit` `failed` |
| `complete` 本身 `abort`，`fatal = true` | 发出 | `aborted` | `exit` `aborted` |
| §4.8 子 `failed` 或名字冲突 | 不经过本函数 | `failed` | 父的 `invoke` span 保持打开 |

continue 另写 `audit` `{"op":"continue","next_iteration":n}`。`error` 对象的形状一律是 `{"sqlstate","code","message"}`。`message` 截到 1024 个字符。gate 断言 `sqlstate` 与 `code`，不断言 `message` 全文。

### 4.10 `v15_reclaim_expired`

一个事务。签名没有参数。不调用 FakeLLM，不打开网络，不调用 `v15_on_phase`，不插入 attempt（§0.4、§0.6）。不调用两道清单断言。清单缺失可以让以后的 `v15_begin_llm` 失败，但不得让已经过期的 attempt 停在 `leased`。本函数若把子 invoke 写成终态，服从 §4.1 的子终态清单。

**锁。** 无锁找出两类行，再按 §4.1 锁池、自身、祖先与非终态后代：

- attempt：`status = leased` 且 `lease_until <= clock_timestamp()`。
- invoke：`status = leased` 且 `lease_until <= clock_timestamp()`。

重读之后不再过期的行跳过。先处理 attempt，再处理 invoke。

**attempt。** 用存放的 `reserved_calls` 与 `reserved_cost`：

- `call_started = true`：行置 `unknown`，`calls_charged = true`。预留的 calls 转入 `calls_used`，`cost_reserved` 释放，`cost_used` 不加。
- `call_started = false`：行置 `failed`，`calls_charged` 保持 false。只释放两份预留。
- 清空该行租约。终态不得再改（§0.6）。

**invoke。** 收回集合是：`status = leased`，并且已经没有 `status = leased` 的 attempt，并且（`lease_until` 已过，或本事务刚刚终结了它的 attempt）。不要求 invoke 自己的 `lease_until` 已经到期才收回「attempt 先过期」的那一种；旧持有者因此不能再结算。

语句修理与租约收回。下列修理 `UPDATE` 一律 `revision = revision + 1`：

- `running` 且 `child_invoke_id` 非空，子已是终态：先置父 bind-wait（`suspended`、清租约、`fence` 不动），再在同事务做 §4.8 送达。不得 bump fence，也不得二次 bump。不得把这条语句改回 `pending`。
- 其余行：`fence := fence + 1`，清空租约。然后：
  - `running` 且 `child_invoke_id` 为空：改回 `pending`，`error` 保持为空。invoke 置 `runnable`。
  - `running` 且 `child_invoke_id` 非空，子尚未终态：invoke 改回 `suspended`，不再加第二次 fence。语句保持 `running`。这是 bind-wait 的修理。
  - 没有需要修理的 `running` 语句：invoke 置 `runnable`。

修理结束时，终态 invoke 不得仍有 `running` 语句（§4.8、§4.9）。

`suspended` 的父不在本函数的收回集合里。子终态与父送达若属于同一次提交，不存在「子已终态、父仍 suspended」的崩溃窗口。

**事件。** 每个被终结的 attempt：`llm_query/retry`，`payload` 含 `old_attempt_id`、`old_status`（`unknown` 或 `failed`）、`new_attempt_id` 为 JSON `null`。span 保持打开，直到后来的 settle 或 I/O 耗尽时 `exit`。invoke 租约被收回时另写 `audit` `{"op":"lease_reclaimed"}`。没有任何过期 attempt、也没有任何租约被收回：无写入、无事件，返回 0。返回值只计被终结的 attempt 行数。

下一轮要出现新 attempt，必须先 claim 这个 `runnable` invoke，再由 `v15_begin_llm` 的重试分支插入。回收事务与下一次 FakeLLM 之间因此至少有 claim 与 begin 与 mark 三次提交边界。

### 4.11 空消息、散文与切分失败

**空消息。** 助手 `content` 经 §6.1 得到零条语句。`v15_settle_llm` 插入零行，迭代 `executing`。worker 调用 `v15_begin_exec` 再 `v15_finish_exec` 的 continue 分支。消耗一次迭代，不执行语句。`repl_output = ''`。`repl_exec/exit` 的 `outcome = completed`。这不是错误。

**散文与非法 SQL。** 切分得到一条或多条，入参 `kind = plain` 且 `reject_code` 为空，但文本不是可执行语句。存放行是 `pending` 且 `error IS NULL`。worker 仍按 §4.6.2 执行。PostgreSQL 报错（例如 `42601`）落在保存点里，`error.sqlstate` 与 `error.code` 都填该 sqlstate，`message` 为数据库原文截断。然后 finish 的 continue。`repl_exec/exit` 仍是 `completed`。invoke 不进入 `failed`。已提交的前序语句保留（§0.7）。

**分类器拒绝。** 入参 `reject_code` 非空的行在 settle 时写成 `failed` 且 `error` 非空。worker 不执行它们，因为可执行谓词失败。前面仍可执行的行先执行。遇到 `failed` 即转入 finish 的 continue。`DO` 的码为 `V15_DIALECT`。`ALTER TABLE` 的码为 `V15_DDL`（§6.2）。

**整段切分失败或 NUL。** worker 仍调用 `v15_settle_llm`，数组里恰好一个合成元素：`kind = plain`，`bind_name` 与 `arg_sql` 为 SQL NULL。未闭合的引号、注释或 dollar-quote，且正文不含 NUL：`sql` 为原文，`reject_code = V15_DIALECT`。含 NUL：先把每个 NUL 换成六字符 `\u0000`，再计算 `sql_digest`，`reject_code = V15_VALUE_INVALID`，不再另报未闭合（§3.3）。存放行是 `failed` 且 `error.code` 等于该码。该行不执行。finish 走 continue。attempt 正常 `settled`。

### 4.12 worker 顺序

`v15_run_until_quiescent` 是 Python，不是 SQL 函数（§0.4）。每一轮：

1. `v15_reclaim_expired()`。没有参数。先把 `tool_wait` invoke 一并入锁种子；工具 attempt 的 unknown/failed 记账与 LLM 同态。
2. `v15_next_tool()`。只读。只返回 `tool_wait` 且有 open request、无 leased attempt 的 `invoke_id`。对每个 id：`v15_begin_tool` **提交** → 非 `proceed` 则下一个 → `v15_mark_tool_started` **提交** → 会话无打开事务时 `FakeTool.call(tool_name, args)`（Python 异常收成 `{"ok":false}`，不得逃出循环、不得留 leased 到超时）→ `v15_settle_tool` **提交**。
3. `v15_next_runnable()`。只读。正向过滤 `status = 'runnable'`。不返回 `suspended` 或 `tool_wait`，也不返回仍为 `leased` 的行。
4. 对返回的 id 按结果顺序 `v15_claim`。NULL 表示没抢到，跳过。claim 返回的 fence 与当初传入的 `p_owner` 是后续转移的出示值。
5. 持有租约之后只做下列之一。每一次调用都传同一个 `p_owner`：
   - 迭代 `pending`，或迭代 `llm` 且没有 `leased` attempt：渲染 base（重试路径的渲染结果会被 SQL 忽略），`v15_begin_llm`。返回 `abort` 则不得调用 FakeLLM。返回 `proceed` 则 `v15_mark_call_started`，`COMMIT` 之后、会话中没有打开的事务时，才 `FakeLLM.complete(logical_digest, n, request)`。摘要与 `n` 用函数返回值。
   - 看见 `call_started = true`，且不是本进程刚刚提交的那一次 mark：停在该 invoke 上，留给过期回收。不得补叫 FakeLLM，也不得结算。
   - 迭代 `executing` 且 `repl_exec` 未打开：`v15_begin_exec`。
   - 迭代 `executing` 且 span 已打开：从 `resume_stmt` 起，只取可执行谓词成立的语句。不再 `enter`。
   - 下一条是 `kind = bind_invoke` 且可执行：§4.7。成功挂起后本 invoke 不再继续，回到第 1 步。子深度更大，扫描会先拿到子。
   - 下一条是 `kind = bind_tool` 且可执行：§4.14。成功挂起后本 invoke 为 `tool_wait`，fence 不加，回到第 1 步。reject 则语句已 failed、invoke 仍 leased，同迭代继续，不 skip_after、不关 `repl_exec`。
6. 挂起路径上，`SELECT (<arg_sql>)` 的任何错误按 §4.7 / §4.14 收成该语句的 `failed` 并 `COMMIT`。不得让这条 `bind_invoke` 或 `bind_tool` 留在 `pending`。
7. 语句事务提交后：若本 worker 已不再持有租约，或迭代已不是 `executing`，或 `repl_exec` span 未打开，回到第 1 步。停止只看当前执行边界上的错误，不看更后的 preclassified `failed`。边界是 `failed`，或没有剩余可执行语句，或成功的 `return` / `raise` 已结束本轮时，worker 只调用 `v15_finish_exec`，不自己改写语句行。skip 收敛只在该函数内完成（§4.9）。finish 的 continue 把 invoke 放回 `runnable`，下一轮重新 claim，颁发新栅栏。

`NOTIFY` 可以少，可以重。少了就靠第 3 步扫回；多了不得第二次 apply（§0.23）。

### 4.13 乱序、重复与丢失

| 到达的调用 | 结果 |
|---|---|
| attempt 已是 `unknown`、`failed` 或 `settled` 时的 `v15_settle_llm` | `V15_ATTEMPT_NOT_SETTLEABLE`，转录不变。先看终态，不先看栅栏 |
| attempt 仍 `leased`，但 invoke 或 attempt 栅栏已变 | `V15_STALE_FENCE`，无写入 |
| `p_owner` 不等于 `lease_owner` | `V15_INVALID_TRANSITION`，无写入 |
| 挂起之后 fence 未变，旧持有者再 prepare、finish 或 suspend | `V15_INVALID_TRANSITION`。这不是 `V15_STALE_FENCE` |
| 回收已经把 invoke fence 加 1，旧持有者再调用 | `V15_STALE_FENCE`，或因 attempt 已终态而为 `V15_ATTEMPT_NOT_SETTLEABLE` |
| 重复 claim（已持有未过期租约） | 返回 NULL |
| 重复 `v15_mark_call_started` | `V15_INVALID_TRANSITION` |
| 对已有 `leased` attempt 再 `v15_begin_llm` | `V15_INVALID_TRANSITION`，不插入第二行 |
| 对 `done` 或 `error` 非空的语句再次 prepare | `V15_INVALID_TRANSITION` |
| 对终态 invoke 的 finish | `V15_INVALID_TRANSITION` |
| 丢失的 `NOTIFY` | 无控制态变化。下一轮先回收，再扫描 `runnable` |
| worker 死在 FakeLLM 期间（`call_started` 已提交） | 回收把该行定为 `unknown`。新进程不得再叫这一行。新 attempt 要等 claim 与重试分支 |
| worker 死在 mark 之前 | 回收把该行定为 `failed`，不计 `calls_used` |
| invoke 租约过期且没有存活 `leased` attempt | `v15_reclaim_expired()` 加 fence 并修理语句。bind-wait 且子未终态则父回到 `suspended` |
| `COMMIT` 返回 `40001` 或 `40P01` | 事务未提交。worker 整段重试，不改写 sqlstate |
| 事务内 `55P03` | `V15_INVALID_TRANSITION` |
| 挂起路径上 `SELECT (<arg_sql>)` 的错误未被捕获 | 视为 worker 违反 §4.7。语句会留在 `pending` 上并被无限重试 |
| 对 `tool_wait` 调用 `v15_claim` | 返回 NULL，行不变 |
| 对 `tool_wait` 或 `running` 的 `bind_tool` 调用 `v15_io_reclaim_invoke` | `V15_INVALID_TRANSITION`，不得打回 pending 丢 request |
| 未 mark 的工具 attempt 过期 | 行 `failed`，不计 calls；invoke 仍 `tool_wait`；审计 `op=tool_retry` |
| 已 mark 的工具 attempt 过期 | 行 `unknown`，计 1 call；invoke 仍 `tool_wait`；再 begin `n=2` |
| 工具 attempt 已终态时再 `v15_settle_tool` | `V15_ATTEMPT_NOT_SETTLEABLE`，不写 binding |

### 4.14 `tool_wait` 与 `v15_suspend_for_tool`

与 `bind_invoke` 平行、不进 invoke 树。规范语句 `SELECT jaz.bind_tool('<bind_ident>', '<tool_name>', <jsonb-expr>);`。worker 不调用该 SQL 函数；`jaz` 包装下函数体存在，被真正执行即抛 `V15_INVOKE_FORM`、不插 request。

实参求值走 D24 同路：prepare 后以 `v15_repl` 求 `arg_sql`；写记号/会写的 `jaz.*` → `V15_INVOKE_FORM` 不挂起；结果文本超 `protocol.max_invoke_input_length` → `V15_VALUE_INVALID` 不挂起（复用现成上限，不开新配置键）。prepare 对 `bind_tool` 只授 scratch `USAGE`，不授 `CREATE`。

`v15_suspend_for_tool` 返回闭集：

- `{"action":"wait","request_id"}`：插 open request、语句 `running`、迭代 `suspended`、invoke `tool_wait`、清租约、**fence 不变**、revision+1、审计 `op=tool_suspend`。不插 attempt、不预留池、不发 span。
- `{"action":"reject","code":...}`：语句 `failed` + `v15_io_error`，不插 request，invoke 仍 leased，同迭代继续下一条，不 skip_after、不关 `repl_exec`。

reject 校验序：语句 pending 或 running 且 kind=`bind_tool` → invoke leased+holder → `tool_name` 在 catalog → 本 invoke 有 `bindings.kind=tool` 且 name=`tool_name` 且有 `tool_grants` 行 → **external=true**。缺 catalog/binding/grant = `V15_TOOL_UNAUTHORIZED`。`external=false` = `V15_TOOL_BINDING`。

成功送达：request settled；binding 不存在则插 `kind=var` / `provenance=delivery` / `show_in_prompt=true`；已存在且 kind=var 则更新；语句 done、迭代 executing、`resume_stmt+1`、invoke runnable、fence 不变、审计 `op=deliver`；不写 `repl_history`；同迭代剩余语句继续。`ok=false` → `V15_TOOL_FAILED`；耗尽 → `V15_TOOL_EXHAUSTED`；名字被占 → `V15_DELIVERY_CONFLICT`。后三种走非 fatal 收束（skip_after、观测、下一迭代 pending、关 `repl_exec` failed、invoke runnable、审计 `op=tool_failed`）。不调 `v15_on_phase`，不写新 span 名。

## 5. 模型面 SQL API

模型只经过 `jaz` 的公开面。公开面里的函数是 `SECURITY INVOKER` 包装。包装检查 `current_user`，再调用 `v15` 里的 `SECURITY DEFINER` 体。definer 体的 `EXECUTE` 只授给 `v15_repl`（§5.1）。视图没有包装，直接建在 `jaz`（§3.15）。包装若做成 `SECURITY DEFINER`，体内的 `current_user` 会变成 `v15_owner`，包装上的 `V15_ROLE` 将无法表达「调用者不是 `v15_repl`」。

### 5.1 公共合同

`GRANT v15_repl TO v15_worker` 是 `INHERIT FALSE, SET TRUE`。没有 `GRANT v15_repl TO v15_owner`（§2）。worker 未 `SET ROLE` 时不继承模型面的 `EXECUTE`。

每个模型入口：

```text
jaz.<name>(...)  LANGUAGE plpgsql  VOLATILE  SECURITY INVOKER
  若 current_user 不是 v15_repl：抛 V15_ROLE
  否则调用 v15.jaz_<name>(...)

v15.jaz_<name>(...)  LANGUAGE plpgsql  VOLATILE  SECURITY DEFINER
  SET search_path = pg_catalog
  owner v15_owner
  GRANT EXECUTE ON FUNCTION v15.jaz_<name>(...) TO v15_repl
  仅此一个被授权者；PUBLIC 无 EXECUTE；v15_worker 不获此授权
  体内断言有效 exec_context：本 backend_pid，语句 running
  不符抛 V15_INVALID_TRANSITION，无写入
  不做 current_user 断言；体内 current_user 是 v15_owner
```

`GRANT EXECUTE ON FUNCTION v15.jaz_<name>(...) TO v15_repl`，仅此一个被授权者；`v15_worker` 不获此授权。同样适用于 `v15.jaz_tool` 与 `v15.jaz_prior_history`。包装断言 `current_user = 'v15_repl'`，不符抛 `V15_ROLE`。definer 体只断言有效 `exec_context`（本 `backend_pid`、语句 `running`），不符抛 `V15_INVALID_TRANSITION`，不做 `current_user` 断言。`jaz` 包装的 `EXECUTE` 只授给 `v15_repl`。包装是 plpgsql，因为 `LANGUAGE sql` 的函数体不能写这段分支与 `RAISE`。包装是 `VOLATILE`：`jaz.history` 与 `jaz.request_messages` 的可见行依赖 `exec_context`。`v15.jaz_*` 先按 `pg_backend_pid()` 读 `exec_context`。没有行、`backend_pid` 不符、或该语句不是 `running`：`V15_INVALID_TRANSITION`，无写入。`search_path` 钉死，scratch 里的同名对象挡不住 `pg_catalog`（§3.8）。definer 体内不得 `SET ROLE`。

`jaz.bind_invoke`、`jaz."return"`、`jaz."raise"` 另外要求当前 `statements.kind` 与函数匹配，否则 `V15_INVOKE_FORM`（§4.6.2）。`kind = bind_invoke` 的求值里，会写的 `jaz.*` 同样是 `V15_INVOKE_FORM`（§4.7）。

下列函数在当前语句的保存点里生效。语句失败则它们的写入全部不留下；更早语句已提交的 binding 与 `capture` 留下（§4.6.2、§0.7）。

### 5.2 名字

文法：`^[A-Za-z_][A-Za-z0-9_]*$`，长度 1..63。不符抛 `V15_VALUE_INVALID`。

保留字，大小写敏感，不得作为 binding 的 `name`：

```text
__history__  history  request_messages  return  raise  print  assign
var  tool  bind_invoke  prior_history  exec_context
invoke_id  iteration
```

`jaz.var('Return')` 与保留字 `return` 不是同一个名字。规范语句里的名字是普通字符串字面量的内容，不是标识符折叠的结果（§6.2）。

### 5.3 函数

```text
jaz.var(name text) returns jsonb
```

读本 invoke 的 binding。`kind` 为 `input`、`scope` 或 `var` 时返回 `value`。没有这个名字，或 `kind = tool`：抛 `V15_VALUE_INVALID`。不返回 SQL NULL。不改 `revision`。

```text
jaz.assign(name text, value jsonb) returns jsonb
```

`value` 为 SQL NULL 时 `V15_VALUE_INVALID`（jsonb `null` 允许）。名字已是 `input`、`scope` 或 `tool`：`V15_VALUE_INVALID`，不改 kind。已是 `var`：更新 `value`，`provenance = repl`，`revision` 加 1，`show_in_prompt` 不变。新名字：插入 `kind = var`，`provenance = repl`，`show_in_prompt = true`，`revision = 0`。返回写入后的 `value`。`bind_invoke` 求值期间调用则 `V15_INVOKE_FORM`。

```text
jaz.print(line text) returns void
```

`line` 为 SQL NULL 时 `V15_VALUE_INVALID`。`iterations.capture := capture || line`，中间不插入分隔符。`iterations.revision` 加 1。同一条成功语句里按调用顺序拼接；该语句失败则这些拼接消失。`SELECT jaz.print(...)` 作为语句是合法的。`bind_invoke` 求值期间调用则 `V15_INVOKE_FORM`。

```text
jaz.tool(name text, args jsonb) returns jsonb
```

一次调用，同步，在当前语句事务内结束（§0.29）。查找是同一条件的合取：本 invoke 存在 `bindings.kind = tool` 且 `name` 匹配，并且存在对应 `tool_grants` 行，并且 `tool_catalog` 有该 `tool_id`。合取失败抛 `V15_TOOL_UNAUTHORIZED`，不区分缺哪一项。`external = true` 时抛 `V15_EXTERNAL_TOOL`，不调用 handler。`args` 必须是 jsonb 对象，否则 `V15_VALUE_INVALID`。`arg_schema` 只存放，调用时不做模式展开。

handler 是 `SECURITY DEFINER`，签名 `(jsonb) returns jsonb`，owner 为 `v15_tool_<name>`。登记时的检查与 hook 相同，外加 `REVOKE ALL ON FUNCTION … FROM PUBLIC` 与只给 `v15_owner` 的 `EXECUTE`，没有 `GRANT OPTION`（§3.14、§9.3）。`v15.jaz_tool` 本身的 `EXECUTE` 只授给 `v15_repl`，不授给 `v15_worker`（§5.1）。`v15.jaz_tool` 在调用前重算 §3.11 的摘要，摘要含规范化 `proacl`，并重查 owner、`provolatile`、`prosecdef`、语言、`proconfig`，以及 owner 对内核表没有权限。任一不符则 `V15_HANDLER_DIGEST`，不调用。

调用文本与 hook 相同：由 oid 解析出 `quote_ident(namespace) || '.' || quote_ident(proname) || '($1::jsonb)'`（§9.2）。没有 `SET ROLE`，也没有临时 `GRANT`。进入 handler 之后，`current_user` 是 `v15_tool_<name>`，因为那是 handler 自己的 definer。handler 返回后，模型语句的 `current_user` 仍是 `v15_repl`。handler 抛出的非 `V15_*` 异常改写为 `V15_HANDLER_FAILED`。handler 只根据 `args` 计算 jsonb，不得写 scratch 或内核表。v15 不把 scratch 写入算作工具的可观察效果。`bind_invoke` 求值期间调用则 `V15_INVOKE_FORM`。

```text
jaz."return"(value jsonb) returns jsonb
jaz."raise"(message text) returns void
```

只在当前语句 `kind` 分别为 `return` 与 `raise` 时生效。`value` 或 `message` 为 SQL NULL：`V15_VALUE_INVALID`。`capture <> ''` 时抛 `V15_PRINT_AND_RETURN`，不写 `return_value` / `error`（§0.22）。否则 `return` 把 `invokes.return_value` 设为该 jsonb 并返回它；`raise` 把 `invokes.error` 设为 `{"sqlstate":<该码>,"code":"V15_RAISE","message":<截到 1024>}`。两者都不改 `status`，都不关 span。`SELECT` 实参必须恰好一行；零行或多行时函数未执行，语句不得标 `done`（§4.6.2）。成功路径上，`v15_complete_statement` 只推进 `resume_stmt`（§4.6.2）。后继 `pending` 与 preclassified `failed` 的 skip 只由 `v15_finish_exec` 按 §4.9 的切点完成。`V15_RAISE` 只表示这次 `jaz."raise"`。父送达时子行保留它，父语句另记 `V15_CHILD_ERROR`（§4.8）。

未加引号的 `return` / `raise` 不是这两个函数。分类器在执行前拒绝它们（§6.2）。

```text
jaz.bind_invoke(name text, args jsonb) returns jsonb
```

无论谁调用、无论语句 `kind` 是什么，都抛 `V15_INVOKE_FORM`，不插入子 invoke（§0.9）。子 invoke 只由 `v15_suspend_for_child` 插入。返回类型存在，只为了让规范语句在类型上是 `SELECT`。函数没有成功返回。

```text
jaz.bind_tool(bind_name text, tool_name text, args jsonb) returns jsonb
```

无论谁调用、无论语句 `kind` 是什么，都抛 `V15_INVOKE_FORM`，不插 `tool_requests`。异步挂起只由 `v15_suspend_for_tool` 完成。`EXECUTE` 只授给 `v15_repl`。

```text
jaz.prior_history(ancestor uuid) returns table (
  iteration int,
  llm_response text,
  repl_output text,
  repl_exception jsonb
)
```

`jaz.prior_history` 是 §5.1 的 invoker 包装。definer 体在 `v15`，`VOLATILE`、`SECURITY DEFINER`。`EXECUTE` 只授给 `v15_repl`，体内只断言有效 `exec_context`（§5.1）。从 `exec_context.invoke_id` 沿 `parent_invoke_id` 向上走。目标是自身或祖先时，返回该 invoke 已结束迭代的历史行。没有已结束迭代时返回空表，不是错误。其他 uuid 抛 `V15_HISTORY_SCOPE`（§0.17）。不写任何行。

### 5.4 视图

两张视图的 owner 都是 `v15_owner`，`security_barrier = true`，`security_invoker = false`。它们是 `jaz` 的公开面，没有 invoker 包装。`SELECT` 只授给 `v15_repl`。基表的 `SELECT` 不授给 `v15_repl`（§3.15）。视图定义里的排序不是对外合同。

`jaz.history` 的列与 `jaz.prior_history` 相同。行滤到 `exec_context.invoke_id`。没有本后端的 `exec_context` 行时，`jaz.history` 与 `jaz.request_messages` 都抛 `V15_INVALID_TRANSITION`。读者要顺序时写 `ORDER BY iteration`。当前迭代，以及正停在 bind-wait 的迭代，都还没有历史行（§0.27）。`return` 与 `raise` 的 `repl_output` 为空串。失败的 `continue` 的 `repl_output` 是完整观测（§3.6）。

`jaz.request_messages` 的列是 `seq`、`role`、`kind`、`content`。行来自当前 `exec_context` 的 invoke 与迭代上、`n` 最大且 `status = settled` 的那次 `llm_attempts.request.messages`。没有已结算 attempt 时返回空表。这里的 `content` 是该 attempt 实际送出的正文：观测可以是截断后的副本，`transient_hook` 在这里可见，不在 `jaz.history` 里。`message_id` 留在存放的 jsonb 里，不作为视图列。顺序是 §3.4 的 base、然后 enter、然后 send；读者要这个顺序时写 `ORDER BY seq`。

### 5.5 失败语句留下什么

| 已提交的前序语句 | 留下 |
|---|---|
| `jaz.assign` | `kind = var` 的 binding 与其 `revision` |
| `jaz.print` | `iterations.capture` 中已拼上的全文 |
| 规范 `return` / `raise` | 不会出现在「前序已提交、后面又失败」里：后继由 `v15_finish_exec` 按 §4.9 标成 `skipped`，不由 `v15_complete_statement` |

失败的那一条里，上述写入在保存点回滚。`statements.status = failed` 与后续的 `skipped` 随外层事务提交。`jaz.tool` 没有 scratch 写入可提交（§5.3）。`status = done` 的语句不得再执行。schema 的 `USAGE` 与 `CREATE` 在完成路径上已经 `REVOKE`，不留到下一事务。

## 6. 方言与协议

切分与分类只有一个实现：`v15/protocol/split_sql.py`。库内保存已经切好的语句行，SQL 不得用正则再切（§0.18）。worker 是可信的：它只能调用这个模块，再把结果交给 `v15_settle_llm`。模型不能写 `statements.kind`。

### 6.1 切分器

`split_sql(source: str) -> list[str] | SplitFailure`。词法状态：

| 状态 | 进入 | 离开 | 其中的分号 |
|---|---|---|---|
| `code` | 起始状态 | 见其余行 | **是**语句边界 |
| 行注释 | `code` 中的 `--` | 换行（换行保留为空白） | 不是 |
| 块注释 | `code` 中的 `/*` | 匹配的 `*/`，深度计数 | 不是 |
| 标准字符串 | `code` 中的 `'` | 非配对的 `'`；`''` 是内容 | 不是 |
| 扩展字符串 | `code` 中的 `E'` 或 `e'` | 与 PostgreSQL `E''` 相同的反斜杠与 `''` 规则 | 不是 |
| Unicode 字符串 | `code` 中的 `U&'` 或 `u&'` | 与 PostgreSQL `U&''` 相同 | 不是 |
| 标识符引号 | `code` 中的 `"` | `""` 为内容，单个 `"` 离开 | 不是 |
| dollar-quote | `code` 中的 `$tag$` | **同一个** `tag` 的 `$tag$` | 不是 |

块注释用深度计数，可以嵌套。`tag` 为空（`$$`）或为一个标识符：首字符为字母、下划线或 `>= U+0080` 的字符，其后为这些字符或数字。`tag` 内不得有 `$`。dollar-quote 不按栈嵌套。体内出现不同标签的 `$other$` 只是普通文本；体内再次出现相同标签则闭合。这与 PostgreSQL 18.4 的词法一致。

未闭合的块注释、字符串、标识符引号或 dollar-quote：不产生部分语句列表。worker 仍结算，且只结算一条合成语句（§4.11）。正文含 NUL 时，先把每个 NUL 换成六字符 `\u0000`，`reject_code = V15_VALUE_INVALID`，不再报告未闭合。PostgreSQL `text` 存不住原始 NUL。不含 NUL 的未闭合，`reject_code = V15_DIALECT`，`sql` 为原文。

语句边界只在 `code` 状态的分号。分号不属于任一条语句。每条结果去掉首尾空白。去掉之后若在 `code` 状态不再有记号，该条删除。`SELECT 1;;; SELECT 2` 得到两条。最后一条可以没有分号。

### 6.2 规范形式与分类

`classify_statement(sql: str) -> (kind, bind_name, arg_sql, reject_code)`。`kind` 是 §3.3 的枚举。`reject_code` 为空表示可以执行。否则 worker 不执行该条，settle 把它存成 `failed` 且 `error` 非空。存放之后，可执行谓词不再看 `reject_code`。`bind_tool` 另有 `tool_name`。

关键字与未加引号的 `jaz` 大小写不敏感。空白在记号之间可多可少。规范形式是**单独一条** `SELECT`，实参列表之外没有尾随记号：

```text
SELECT jaz.bind_invoke('<ident>', <jsonb-expr>);
SELECT jaz.bind_tool('<bind_ident>', '<tool_name>', <jsonb-expr>);
SELECT jaz."return"(<jsonb-expr>);
SELECT jaz."raise"(<text-expr>);
SELECT jaz.print(<text-expr>);
SELECT jaz.assign('<ident>', <jsonb-expr>);
```

引号内必须正好是小写 `return` 与 `raise`。`"RETURN"`、未加引号的 `return` / `raise` / `RETURN` / `RAISE` 都不是规范形式。`<tool_name>` 是标准字符串字面量，匹配 `^[a-z][a-z0-9_]{0,53}$`。

`<ident>` 只允许标准字符串字面量（`'` … `'`，`''` 转义），内容符合 §5.2，且不是保留字。`E''`、`U&''`、dollar-quote、表达式，都不是这个位置的合法写法。`<jsonb-expr>` 与 `<text-expr>` 是一条表达式：分类器只检查括号、字符串、注释与 dollar-quote 之下的顶层逗号个数，不解释表达式的类型。抽出来的表达式文本原样写入 `arg_sql`。规范控制语句抽不出表达式时，`reject_code = V15_INVOKE_FORM`。

同一套词法还要扫描 `bind_invoke` 与 `bind_tool` 的 `arg_sql`。在字符串、注释与 dollar-quote 之外若出现记号 `INSERT`、`UPDATE`、`DELETE`、`MERGE`、`TRUNCATE`、`COPY` 或 `INTO`，整条的 `reject_code = V15_INVOKE_FORM`。同一记号流还拒绝 `(` 前标识符匹配 `nextval`/`setval`/`currval`（含 `pg_catalog.` 限定），同样是 `V15_INVOKE_FORM`。这是序列变异防护。表的属主只要有 schema `USAGE` 就能写自己的表；词法检查是执行前的背书。写防护仍是 `pg_stat_xact_user_tables` 加上仅 `USAGE`、无 `CREATE`（§4.7、§4.14）。

这套记号流也是 §0.18 的权威：控制名只有出现在字符串、注释与 dollar-quote **之外**才算命中。字面量里的同样字符不是 `V15_INVOKE_FORM`。

分类顺序：

1. 命中六式之一，且 `arg_sql` 的写记号检查通过：`kind` 为对应值，`reject_code` 为空。`bind_invoke`、`bind_tool` 与 `assign` 把字符串字面量的内容写入 `bind_name`。`bind_tool` 另写 `tool_name`。`print`、`return`、`raise` 的 `bind_name` 为空。
2. 未命中，但记号流在字符串、注释、dollar-quote **之外**出现 `jaz.bind_invoke`、`jaz.bind_tool`、`jaz."return"`、`jaz."raise"`，或未加引号的 `jaz.return` / `jaz.raise`：`kind = plain`，`reject_code = V15_INVOKE_FORM`。函数被实际执行时仍不产子、不挂工具（§0.9、§4.14）。
3. 首记号序列属于下列 DDL 时，`kind = plain`，`reject_code = V15_DDL`：`CREATE FUNCTION`、`CREATE PROCEDURE`、`CREATE ROUTINE`、`CREATE EXTENSION`、`CREATE ROLE`、`CREATE DATABASE`、`CREATE EVENT TRIGGER`、`GRANT`、`REVOKE`、`COMMENT`、`SECURITY LABEL`、`VACUUM`、`REINDEX`、`CLUSTER`，以及任何 `ALTER TABLE`。`ALTER TABLE` 不因目标在 scratch 里而放行。模型要改表就 `DROP` 再 `CREATE`。
4. 首记号属于实用语句时，`kind = plain`，`reject_code = V15_DIALECT`：`CALL`、`EXECUTE`、`COPY`、`DO`、`BEGIN`、`COMMIT`、`ROLLBACK`、`SAVEPOINT`、`START`、`END`、`ABORT`、`RELEASE`、`SET`、`RESET`、`LOCK`、`PREPARE`、`DEALLOCATE`、`LISTEN`、`NOTIFY`、`UNLISTEN`、`LOAD`、`DISCARD`、`CHECKPOINT`、`EXPLAIN`、`TRUNCATE`。`DO` 整条拒绝。语句内部的重复计算只走 `WITH RECURSIVE` 的 `SELECT`。`DO` 若要回到语言里，必须换成 `session_user` 本身无权的模型连接；在 `v15_worker` 上 `SET ROLE v15_repl` 之后，顶层 `RESET ROLE` 会回到 worker，本版不把这个洞留在方言里（V15-D25）。
5. 下列形式 `kind = plain`，`reject_code` 为空，执行后由 §6.4 决定 schema：`CREATE TABLE`、`CREATE TABLE AS`、`SELECT INTO`、`CREATE INDEX`、`CREATE UNIQUE INDEX`、`CREATE VIEW`、`DROP TABLE`、`DROP INDEX`、`DROP VIEW`。`TRUNCATE` 在第 4 步以 `V15_DIALECT` 拒绝；清空表用 `DELETE`。`UNIQUE` 只是 `CREATE INDEX` 的修饰，不是第二条语句。分类器不看目标 schema。本步没有 `ALTER TABLE`。
6. 其余首记号为 `CREATE`、`ALTER` 或 `DROP`、且没有命中第 5 步的：`kind = plain`，`reject_code = V15_DDL`。包括 `CREATE SCHEMA`、`CREATE SEQUENCE`、`CREATE TYPE`、`DROP SCHEMA`，以及没有写全的 `ALTER`。
7. 其余：`kind = plain`，`reject_code` 为空。包括 `SELECT`、`WITH`、`TABLE`、`VALUES`、`INSERT`、`UPDATE`、`DELETE`、`MERGE`。`jaz.var` 与 `jaz.tool` 可以出现在表达式里。`print` 与 `assign` 出现在非规范语句里不受第 2 步连坐。

### 6.3 超时 pragma

只认语句**第一行**、整行匹配：可选空白、`--`、可选空白、`timeout:`、可选空白、一个有限正十进制数、可选空白。单位是秒。`floor(秒 * 1000)` 必须 `>= 1`，否则 `reject_code = V15_VALUE_INVALID`。第一行写了 `timeout:` 但配不上这个文法，同样是 `V15_VALUE_INVALID`。第二行及以后的 `-- timeout:` 是普通注释。

`timeout_ms` 取下列正整数的最小者：有效 `max_statement_ms`、`resolved_config.repl.timeout_ms`（键不存在则不参加）、pragma 毫秒（没有 pragma 则不参加）。模型语句不能执行 `SET` 来拆掉这个值（§6.2 第 4 步）。存放的 `statements.sql` 保留 pragma 行。`sql_digest` 针对这条存放文本。执行时 worker 送入的是去掉首行 pragma 之后的文本。

### 6.4 执行期背书

分类器在前，事件触发器在后。`v15_scratch_guard` 挂在 `ddl_command_end`，创建为 `SECURITY INVOKER`，`SET search_path = pg_catalog`。`current_user = v15_repl` 时才限制；不得做成 `SECURITY DEFINER`。schema 名只通过全限定调用 `v15.v15_current_scratch_schema()` 读取。该辅助函数是 `SECURITY DEFINER`，只返回本后端 `exec_context.scratch_schema`，体内不切换角色。`GRANT EXECUTE ON FUNCTION v15_current_scratch_schema() TO v15_repl`，仅此一个被授权者；`v15_worker` 不获此授权（§2）。

白名单只限落在该 schema 内的命令标签：`CREATE TABLE`、`CREATE TABLE AS`、`SELECT INTO`、`CREATE INDEX`（含 `UNIQUE`）、`CREATE VIEW`、`DROP TABLE`、`DROP INDEX`、`DROP VIEW`。没有 `TRUNCATE`，也没有 `ALTER TABLE`。`TRUNCATE` 由分类器以 `V15_DIALECT` 拒绝；清空表用 `DELETE`。标签与对象身份来自 `pg_event_trigger_ddl_commands()`。`DROP TABLE`、`DROP INDEX`、`DROP VIEW` 另有 `sql_drop` 触发器，用 `pg_event_trigger_dropped_objects()` 核对对象身份；`ddl_command_end` 不含 drop 的对象身份。`ALTER TABLE`、`CREATE FUNCTION`、`CREATE PROCEDURE`、`CREATE ROUTINE` 抛 `V15_DDL`。触发器不得 `ALTER … OWNER`。模型创建的对象 owner 保持 `v15_repl`。

`CREATE EVENT TRIGGER` 只出现在超级用户加载的 `v15_schema.sql` 里。`v15_repl` 没有 `TEMP`（§0.26）。`SET`、`COPY`、`DO` 与显式事务控制在分类器已经被拒绝。

### 6.5 提示词

渲染器是 `v15/protocol/render_prompt.py` 的纯函数。没有 Jinja。它有两个调用点，都在 worker 进程里：

- open 之前，从即将传入的 `p_inputs` 渲染 `p_system` 与可空的 `p_user`。渲染用 `depth < effective max_depth`。`p_system` 与 `p_child_system` 是 open 时的转录种子。SQL 在 `invoke/enter` 效应返回之后插入种子：`msg_seq` 0 为 `seed:system`，正文是 `p_system`；效应后仍有 `show_in_prompt` 的输入时，inputs 种子按本节 user 段组成并写入 `msg_seq` 1，含 enter 的 `input_adds`。返回的持久消息由 open 按 `max(seq)+1` 插入（§4.3）。其后 enter 的 `disable_recursion` 不改写已插入的种子。SQL 不调用 Python 渲染器。
- 每次 `v15_begin_llm` 之前，**worker** 用已提交的 `recursion_available` 与 bindings 重渲染 system 正文，放进 `p_base_messages` 的 `seed:system` 元素，可与存放种子不同。inputs 正文跟随当前 `kind = input` 行，仅截断。`recursion_available = false` 时，该正文省略两处 `bind_invoke` 教学，不出现这个函数名（§0.25）。SQL 只校验 id、顺序与映射 kind，不写 system 字节（§4.5.1）。

种子行不可变（§3.5）。enter 的 `input_adds` 在种子写入前已经落地，因此进入 inputs 种子。下一次 base 的 user 段仍按当时的显式输入渲染。模型当次看见的是最终 `request.messages`：base，然后 enter 列表，然后 send 列表（§4.5.1）。持久 hook 行由 `v15_on_phase` 插入；begin 只复制列表。

**system 正文**由下列块按顺序拼接，块与块之间一个空行。

响应格式（逐字；省略委托时同时删去 `bind_invoke` 那一行）：

```text
Your entire reply is a PostgreSQL statement list. Do not wrap it in markdown fences or prose. Separate statements with semicolons. The canonical control statements are:
SELECT jaz.bind_invoke('<ident>', <jsonb-expr>);
SELECT jaz."return"(<jsonb-expr>);
SELECT jaz."raise"(<text-expr>);
SELECT jaz.print(<text-expr>);
SELECT jaz.assign('<ident>', <jsonb-expr>);
jaz.var(name) and jaz.tool(name, args) may appear inside expressions. return and raise must be double-quoted. An unquoted return or raise is rejected.
```

REPL 说明（逐字）：

```text
Statements run one at a time. Your scratch schema is on the search_path. You may create and drop tables, indexes, and views only in that schema. CALL, EXECUTE, COPY, transaction control, SET, RESET, DO, ALTER, and TRUNCATE are rejected. Empty a table with DELETE. Other DDL is rejected. Repeat work inside one statement with WITH RECURSIVE, not with DO. Change a table by dropping it and creating it again.
```

历史与请求（逐字，两态都保留）：

```text
Finished iterations of this invoke are rows of jaz.history (columns iteration, llm_response, repl_output, repl_exception). Read them with ORDER BY iteration. There is no __history__ object. jaz.prior_history(invoke_id) returns the same columns for this invoke or an ancestor invoke and fails for any other id. jaz.request_messages (columns seq, role, kind, content) is the request stored for the latest settled attempt of the current iteration, including hook messages. Read it with ORDER BY seq.
```

尾委托（仅 `recursion_available` 时逐字保留）：

```text
To delegate to a child invoke, end your message with exactly these two statements and no further statements after them:
SELECT jaz.bind_invoke('<ident>', <jsonb-expr>);
SELECT jaz."return"(jaz.var('<ident>'));
The jsonb expression is a JSON object of explicit inputs for the child. The next statement of this same reply reads the child result with jaz.var. This invoke does not call the model again before that statement.
```

`context_window_warning` 的瞬态正文在 §10.2，有两套。`recursion_available = false` 时那套正文也不得出现 `bind_invoke`。瞬态消息的 `message_id` 是 hook 给的 id，只放进 `request`，不插入 `llm_messages`。

scoped 名是 system 的最后一块。标题行 `scoped names:`，然后每个 `show_in_prompt = true` 且 `kind ∈ (scope, var, tool)` 的 binding 一行，按名字的字节序升序。数据行是 `<name> kind=<kind>`。工具行再加一个空格与 `tool_catalog.description`。不把 scope 或 var 的 jsonb 值写入提示。`show_in_prompt = false` 的名字不出现。

**user 段**只含显式输入。标题行 `inputs:`，然后每个 `kind = input` 且 `show_in_prompt = true` 的 binding 一行 `<name>: <value::text>`，名字字节序升序。没有这样的 binding 时，open 的 `p_user` 为 SQL NULL，base 里也不放 `seed:inputs`。

**截断只作用于 worker 构造的 base，不改 `llm_messages`，也不改 `repl_history.repl_output`（§0.17）。** 参数来自冻结后的 `resolved_config.protocol`：`max_invoke_input_length`、`truncation_prefix_ratio`、`max_repl_output_length`。长度用字符数，与 `char_length` 的码点一致。截断不得改 `message_id`。

单串截断：长度不超过上限则原样返回。否则标记为换行、`[v15 truncated]`、换行。可保留长度 = 上限减标记长度；该值小于 1 时保留原串的前「上限」个字符。否则前缀长度为 `floor(可保留 × truncation_prefix_ratio)`，后缀为剩余，中间放标记。

组 base 的顺序：

1. 每条已存放的 `kind = observation` 先按 `max_repl_output_length` 做单串截断，放进 base 的对应元素。`message_id` 仍是 `iter:<n>:observation`。助手消息、system、显式输入不用这个上限。
2. system 永不截断。其长度已经大于 `max_invoke_input_length` 时，worker 仍把 base 交给 `v15_begin_llm`。SQL 看到 `input_chars` 超限后，以提交类、`fatal = false`、`V15_VALUE_INVALID` 结束本 invoke，不插入 attempt（§4.5.1）。有父则 §4.8。
3. 总长仍超过时，从最旧的观测元素继续单串截断，直到放下或该元素只剩标记。
4. 仍超过则对显式输入 user 元素做单串截断。
5. 仍超过则把这份 base 交给 SQL，由 SQL 做第 2 步那个提交类中止。worker 不得在 Python 里把 invoke 写成终态。

SQL 不第二次截断。`logical_digest` 不由 Python 写入。Python 可以调用数据库计算 `md5(jsonb::text)` 来做测试断言，不得自造另一种 jsonb 编码当作权威。最终摘要的信封在 §4.5.1，覆盖 base、enter 与 send。`send` 的 `io.logical_digest` 只覆盖 base。没有追加时两者相等。

子 invoke 的 `p_child_system` 与 `p_child_user` 用同一渲染器，输入是 §4.7 将要复制的 scope 与 `p_child_inputs`。子的第一次 `v15_begin_llm` 再按子提交后的状态渲染 base，不复用父的 `request`。

## 7. 输入、scope 与值域

值域是 jsonb。宿主在调用 `v15_open_invoke` 之前把 Python 值序列化成 jsonb。库内没有 Python 对象身份，也没有跨语句保持的指针。数字与字符串的形状以 PostgreSQL jsonb 的规范化为准。SQL NULL 不是 binding 的值。jsonb 的 `null` 是值。

### 7.1 kind

| `kind` | 谁写入 | 子 open 时 | `jaz.var` | 提示 |
|---|---|---|---|---|
| `input` | 根的 `p_inputs`，或子的 `p_child_inputs`，或 `invoke/enter` 的输入效应 | 不复制 | 返回 `value` | `show_in_prompt` 时进入 user 段，`message_id` 为 `seed:inputs` |
| `scope` | 根的 `p_inputs`，或从父 scope 按值复制 | 按值复制 | 返回 `value` | `show_in_prompt` 时只列名字 |
| `var` | `jaz.assign`，或子结果送达 | 不复制 | 返回 `value` | 新行默认显示；送达覆盖不改变原标志 |
| `tool` | 根的 `p_inputs`，或父 scope 工具连同 grant | 仅 `provenance = scope` 的行，并复制 `tool_grants` | 抛 `V15_VALUE_INVALID` | `show_in_prompt` 时列名字与 description |

`provenance` 的闭合集合是 `explicit`、`scope`、`hook`、`repl`、`delivery`（§3.7）。open 与送达只产生 `explicit`、`scope`、`repl`、`delivery`。`hook` 只由 §9 的输入效应产生。效应不得把一个已有名字改成另一种 `kind`。

同一 `(invoke_id, name)` 只有一种 `kind`。open 时显式输入与 scope 同名：`V15_SCOPE_CONFLICT`。根上这是回滚类，事务无 invoke 行。子上这是语句失败，由 §4.7 的捕获收成父语句 `failed`，无子行留下。

### 7.2 传播

复制发生在子 open 的那一个事务，是 jsonb 按值拷贝，不是共享行。此后任一侧的 `jaz.assign` 或送达都不改另一侧。`kind = var` 不进入孙 invoke。父的 local layer 与 local hook 不进入子（§8.3）。父的 `capture`、迭代与 `repl_history` 不复制。子要读祖先历史时调用 `jaz.prior_history`（§5.3）。

`p_child_inputs` 只产生子的 `kind = input`。它不能携带工具 oid。工具进子只通过 scope 复制与配套的 `tool_grants`。只复制其中一项时，`jaz.tool` 抛 `V15_TOOL_UNAUTHORIZED`（§5.3）。

`show_in_prompt = false` 的值仍然可以用 `jaz.var` 读取。工具在有 grant 时仍可调用。隐藏只影响 §6.5 的正文，不是权限边界。权限边界是 `tool_grants` 与角色（§0.14）。

送达写入的 `var` 在同一父迭代的下一条语句可见，因为 binding 提交发生在子终态事务，下一条父语句是更晚的事务（§0.2）。该 `var` 不出现在本迭代已经发出的请求里。下一次父 LLM 的 base 才会在 scoped 名列表里看见它，若 `show_in_prompt` 仍为真。最终请求的消息 id 与顺序取自存放的 `llm_messages`。`seed:system` 的正文由 worker 在调用 `v15_begin_llm` 之前重渲染，可与 open 时的转录种子不同；inputs 正文跟随当前 `kind = input` 行，仅截断（§3.4、§6.5）。

子 `completed` 时，`bind_name` 若已被 `input`、`scope` 或 `tool` 占用，不覆盖。父按 §4.8 做非 fatal 收束，父语句记录 `V15_DELIVERY_CONFLICT`，子保持 `completed`。子自身 `status = failed` 时，父语句记录 `V15_CHILD_ERROR`，子行保留自己的码。`fatal = true` 时父 invoke 改为 `aborted`，不写 `V15_CHILD_ERROR`。

## 8. 配置解析

配置在 open 时折叠一次，写入 `invokes.resolved_config` 与 `config_digest`，此后对这个 invoke 不再重折（§0.16）。profile 或 layer 的后续 `UPDATE` 只影响尚未 open 的 invoke。已经出生的子不读这份新折叠；它在自己的 open 事务里单独折叠。

### 8.1 对象与允许的键

折叠结果只有三个组件，外加一个记录深度的整数：

```text
{"llm": object, "repl": object, "protocol": object, "depth": int}
```

组件整对象替换，不做字段深合并。层表上的 `llm`、`repl`、`protocol` 是可空列：`IS NULL` 表示不写。列非空但 `jsonb_typeof` 不是 `object`（包括 JSON `null`）抛 `V15_VALUE_INVALID`。depth partial 内部的键是否存在用 `jsonb_exists`，不用列的 `IS NULL`。键存在而值不是对象，同样是 `V15_VALUE_INVALID`。

允许的键：

| 组件 | 键 | 约束 |
|---|---|---|
| `llm` | `model` | 非空文本。折叠结束后必须存在 |
| `llm` | `temperature` | 数值，可缺 |
| `llm` | `max_output_tokens` | 整数 `>= 1`，可缺 |
| `repl` | `timeout_ms` | 整数 `>= 1`，可缺。缺则语句超时只看清单与 pragma |
| `protocol` | `max_invoke_input_length` | 整数 `>= 1`，折叠结束后必须存在 |
| `protocol` | `truncation_prefix_ratio` | 数值，`> 0` 且 `< 1`，折叠结束后必须存在 |
| `protocol` | `max_repl_output_length` | 整数 `>= 1`，折叠结束后必须存在 |

其它键，包括 `reject_finish_on_printed_output`、`baseline_hooks`、`depth_map`，以及四项治理上限的名字，在组件对象里出现即 `V15_VALUE_INVALID`。打印与结束互斥恒为真，没有配置开关（§0.22）。

endpoint、凭据、HTTP 超时不是 `llm` 的键。`model` 由 worker 选用 allowlist 适配器。`temperature` 可以折叠，但不承诺送进每一个适配器（V15-D27）。

stage 1 种子 profile 的组件，测试在不覆盖时就是这一份：`llm = {"model":"fake"}`，`repl = {"timeout_ms":30000}`，`protocol = {"max_invoke_input_length":100000,"truncation_prefix_ratio":0.7,"max_repl_output_length":4000}`。

### 8.2 折叠顺序

`resolve(scope_id, local_layer_id, depth)` 的唯一顺序：base，然后该绝对深度的 depth partial，然后 propagating 的 `ordinal` 升序，然后本 invoke 的 local layer。后写的组件整段替换先写的。

```text
profile := config_scopes.profile_id → config_profiles
acc.llm := profile.llm
acc.repl := profile.repl
acc.protocol := profile.protocol

depth_layers := 本 scope 上 kind = 'depth' 的 config_layers，按 ordinal 升序
for layer in depth_layers:
    if layer.extra_hooks IS NOT NULL: 抛 V15_DEPTH_SELF
    if layer.llm、layer.repl、layer.protocol 任一 IS NOT NULL: 抛 V15_DEPTH_SELF
    if depth 的十进制文本（无前导零）不是 depth_map 的键: 继续下一层
    partial := 该键的值
    应用 partial

for layer in 本 scope 上 kind = 'plain' 的层，按 ordinal 升序:
    应用这一层 IS NOT NULL 的组件列

if local_layer_id 非空:
    layer := 该行
    if layer.scope_id IS NOT NULL 或 layer.kind <> 'plain': 抛 V15_CONFIG_LOCAL
    应用 layer 上 IS NOT NULL 的组件列

acc.depth := depth
digest := md5(acc::text)
```

「应用对象 X」：X 含键 `depth_map` 则 `V15_DEPTH_SELF`；含键 `baseline_hooks` 则 `V15_BASELINE_IMMUTABLE`。对 `llm`、`repl`、`protocol`，列或 partial 键在场则整段替换，并立刻校验允许的键。`depth_map` 里不是本深度的键不读出、不校验。本深度的 partial 一旦被选中就必须合法。`kind = depth` 的层不得在 `llm` / `repl` / `protocol` 列里再写一份；那些列必须为 SQL NULL。

local layer 的 `ordinal` 不参与排序。它要么缺席，要么最后应用。一个 local layer 至多被一个 invoke 引用（§3.1 的部分唯一索引）。

### 8.3 子 invoke 继承什么

子 open 调用 `resolve(父.config_scope_id, NULL, 子.depth)`。因此：

- 继承 `config_scope_id`，从而继承 base、depth partial 与 propagating layer 在**子 open 当时**的组件列。
- 不继承父的 `local_layer_id`，也不把父的 `resolved_config` 整块拷贝给子。父子的 `config_digest` 可以不同。
- 父 open 之后、子 open 之前对 profile 或 propagating layer 的修改，父的快照看不见，子的折叠看得见。已打开的行不被重折。
- 不重读 `config_layers.extra_hooks`，也不复制父的 `ordinal` 数值。baseline 按 §8.6 用子的有效上限与**当时**的 profile `baseline_hooks` 安装，`ordinal` 从 0 连续。然后按父 invoke 上 `channel = propagating` 的行的相对顺序，接上新的连续 `ordinal`，复制 `hook_def_id`、`channel` 与 `config`，`state` 置为 `{}`，`revision` 置 0。`channel = local` 的行不复制。
- 有效上限以父的有效四项为起点，再与当前清单逐项取较小值。不得大于父，也不得大于清单。子没有 `p_ceilings`。子的 `manifest_digest` 是这份有效上限的摘要，可以与父不同，也可以与单例行的摘要不同。

`v15_open_invoke` 的 `p_local_layer_id` 指向 `kind = depth` 或 `scope_id` 非空的层时，抛 `V15_CONFIG_LOCAL`。子路径传入非空 local 同样是 `V15_CONFIG_LOCAL`。

### 8.4 清单上限不是 config 键

`max_iterations`、`max_depth`、`max_io_attempts`、`max_statement_ms` 只存在于 `governance_manifest` 与 baseline hook 的 `config`。它们出现在 `llm`、`repl`、`protocol`、depth partial 或层组件里，折叠抛 `V15_VALUE_INVALID`。调用方收紧上限只通过 `p_ceilings`（§4.3）。放宽抛 `V15_GOVERNANCE_RAISE`。

`invoke_hooks` 上的触发器拒绝 `DELETE`，并拒绝 `UPDATE` baseline 行的 `config`、`channel`、`hook_def_id`、`ordinal`。违反者抛 `V15_BASELINE_IMMUTABLE`，不是 `V15_GOVERNANCE_MISSING`。行若仍然缺失，`v15_assert_invoke_manifest` 抛 `V15_MANIFEST_DIGEST`。模型 SQL 与非 baseline hook 都走这条触发器，没有第二条删除路径。

已打开 invoke 的推进读自己的 baseline 行，不读清单表的新数值。清单行被删或检查不再成立时，`v15_assert_manifest()` 对**新的** open 与 `v15_begin_llm` 失败，码 `V15_GOVERNANCE_MISSING`。这不重折旧快照。`v15_reclaim_expired()` 不调用这道断言（§4.10）。

### 8.5 摘要

`config_digest = md5(resolved_config::text)`。`resolved_config` 就是 §8.1 的四键对象。`invokes.manifest_digest = md5(ceilings::text)`，其中 `ceilings` 是该 invoke 的**有效**上限：

```text
{"max_depth":int,"max_io_attempts":int,"max_iterations":int,"max_statement_ms":int}
```

`governance_manifest.manifest_digest` 用同一形状摘要单例行的四项，不含 `manifest_id` 与 `created_at`。它不是 open 时抄进 invoke 的那个值。两者相等，仅当 `p_ceilings` 为空，且 open 之后这四项没有变过（§3.13）。

两者都取 PostgreSQL 18.4 `jsonb::text` 的文本，`md5` 十六进制小写。这是变更检测，不是外部密码学承诺。实现不得改用另一种键序或另一种哈希而不改本节。open 写入 `invokes.manifest_digest` 之后，推进路径只重算 baseline 并比较，不因清单表出现了新行而改写它。

`config_profiles.profile_digest` 是 `md5` 作用于 `{"baseline_hooks","llm","protocol","repl"}` 这个对象。`config_layers.layer_digest` 是 `md5` 作用于该行上非 SQL NULL 的 jsonb 列组成的对象，键为列名。SQL NULL 的列不进入对象。这两枚摘要不进入 `invokes.config_digest` 的输入；进入的是折叠结果。

### 8.6 baseline 的安装

根 open，以及子 open 的 baseline 段，在折叠之外插入 `invoke_hooks`。`ordinal` 从 0 连续。子 open 在这段之后改接 §8.3 的 propagating 复制，不执行下面的第 3 步和第 4 步。

1. 四个治理 hook，`channel = baseline`，`hook_key` 依次为 `governance_iterations`、`governance_depth`、`governance_io`、`governance_statement`。`config = {"max": <该 invoke 的有效整数>}`。这四行 `hook_defs.baseline_required = true`。
2. `config_profiles.baseline_hooks` 里的 `hook_key` 数组，仍是 `channel = baseline`，`config = {}`。与第 1 步重复则 `V15_VALUE_INVALID`。
3. 仅根：propagating plain layer 的 `extra_hooks`，按层 `ordinal`，层内按数组顺序，`channel = propagating`。元素形状是 `{"hook_key": text, "config": object}`。子 open 不用这一步。
4. 仅根：local layer 的 `extra_hooks`，`channel = local`。子没有 local layer。

`hook_key` 必须已经在 `hook_defs`。`kind = depth` 的层 `extra_hooks IS NOT NULL` 则 `V15_DEPTH_SELF`（§8.2）。层或 partial 里出现 `baseline_hooks` 键则 `V15_BASELINE_IMMUTABLE`。安装完才把有效上限的 `manifest_digest` 写入 invoke 行。

## 9. Hook 事件·效应·黑板

`v15_on_phase(invoke_id uuid, iteration int, span text, phase text, io jsonb) returns jsonb` 的签名与 oid 自 stage 1 起固定（§0.28）。stage 1 至 stage 8 的函数体不读 `invoke_hooks`，不预留预算，返回 `{"contract":1,"action":"proceed"}`，且不含 `budget` 键。stage 9 只在 `v15/govern/v15_govern.sql` 里 `CREATE OR REPLACE` 这个函数体。本节是该函数体的合同。转移对 `action = abort` 的提交类处理以 §4.3、§4.5、§4.7、§4.9 为准。

阶段返回值叫做 `phase_effect`。它与 handler 的返回值不是同一个对象。

handler 返回的键只允许：`contract`、`action`、`fatal`、`error`、`messages`、`message_drops`、`exec_result`、`recursion_available`、`input_adds`、`input_drops`、`blackboard_writes`、`budget`。`error` 的形状是 `{"code": text, "message": text}`。

dispatcher 返回给转移的键只允许：`contract`、`action`、`fatal`、`code`、`messages`、`exec_result`、`recursion_available`、`input_adds`、`input_drops`、`blackboard_writes`、`budget`。返回值里没有 `error`，也没有 `message_drops`。`code` 是已经合成的顶层文本。`contract` 必须为 1。缺键的含义与 §4.1 相同：`fatal` 缺为 false，数组缺为 `[]`，`exec_result` 与 `budget` 缺为 SQL NULL。stage 1–8 的桩只有 `contract` 与 `action`。

任何 `SECURITY DEFINER` 函数，包括本函数，体内不得 `SET ROLE`、`RESET ROLE` 或 `SET SESSION AUTHORIZATION`（§0.20）。

### 9.1 激活顺序与快照

一次阶段调用只读该 `invoke_id` 的 `invoke_hooks`，按 `ordinal` 升序调用。安装顺序保证这就是 baseline，然后 propagating，然后 local（§8.6）。子 invoke 的 propagating 行使用 §8.3 重新分配的连续 `ordinal`，保持父行的相对顺序，不使用父行原来的序号。

快照在任何 handler 之前组装一次。每个 handler 拿到这份快照的拷贝，外加只属于它的 `self`。前一个 handler 的返回值不得进入后一个 handler 的快照。

```text
snapshot = {
  contract: 1,
  invoke_id: uuid,
  iteration: int,
  span: text,
  phase: text,
  io: <调用方传入的 jsonb 对象，去掉 dispatcher 专用键 enter_messages 与 enter_overlay 后的副本>,
  config: invokes.resolved_config,
  ceilings: {max_iterations, max_depth, max_io_attempts, max_statement_ms},
  recursion_available: boolean,
  blackboard: { values: {key: jsonb}, generation: {key: bigint} },
  counters: {counter_key: bigint},
  hooks: [ {ordinal, hook_key, channel, config, state}, ... ],
  self: {ordinal, hook_key, channel, config, state}
}
```

`ceilings` 来自该 invoke 四行 baseline 的 `config.max`，不是清单表的当前值（§8.4）。`blackboard.values` 是本 phase 应用前的已提交代。`counters` 缺键表示 0。`budget_forcing` 读的就是这里的当前值，消息 id 用增加之前的数（§10.2）。`recursion_available` 读调用当时的行。

`io` 必须恰好包含下表的键。多一个键或少一个必填键都抛 `V15_PHASE_CONTRACT`。`iteration` 参数只与列出了 `iteration` 的阶段比较；那些阶段里两者不一致同样是 `V15_PHASE_CONTRACT`。`invoke/enter` 的 `io` 没有 `iteration`，不得因为参数是 0 而去比较一个不存在的键。

| 调用点 | `io` 恰好包含 |
|---|---|
| `invoke/enter` | `depth`（int，`>= 1`） |
| `llm_query/enter` | `iteration`（int，`>= 0`）、`next_attempt_n`（int，`>= 1`） |
| `llm_query/send` | `iteration`、`logical_digest`（非空文本）、`input_chars`（int，`>= 0`）、`enter_messages`（消息列表，无消息时为 JSON `null`）、`enter_overlay`（对象或 JSON `null`） |
| `llm_query/complete` | `attempt_id`（uuid 文本） |
| `llm_query/exit` | `attempt_id`（uuid 文本，或 JSON `null`） |
| `repl_exec/enter` | `iteration`、`resume_stmt`（int，`>= 0`） |
| `repl_exec/send` | 空对象 |
| `repl_exec/complete` | `result_kind`、`return_value`、`error`、`capture` |
| `repl_exec/exit`、`invoke/complete`、`invoke/exit` | `outcome`（`completed`、`aborted` 或 `failed`） |

`repl_exec/complete` 的空值是 JSON `null`，不是缺键。`llm_query/exit` 的 `io.attempt_id` 在未产生 attempt 即关 span 的路径（enter/send abort、预算 abort、I/O 耗尽）允许 JSON `null`。`llm_query/complete` 仍必须是 uuid 文本。`llm_query/send` 的 `logical_digest` 只覆盖 base；最终摘要由 `v15_begin_llm` 在效应落地并拼好 `request` 之后计算（§4.5.1）。`input_chars` 是 base 的字符数之和，不算本 phase 追加的 hook 消息。`enter_messages` 与 `enter_overlay` 都排除在 handler 快照之外。`enter_overlay` 只含可缺的 `recursion_available` 与可缺的 `blackboard_writes`。`enter_overlay.recursion_available` 若存在，替换快照同名场。`enter_overlay.blackboard_writes` 的每个元素替换 `blackboard.values[key]`；受影响键的内存代数 = 已提交代 + 1，新键为 1。send handler 看见的是这份内存叠加，库中尚无这些行。除 `llm_query/exit` 外，写了 `exit` 事件的关闭路径在事件之后调用对应 phase，`io` 恰好是 `{"outcome"}`。`llm_query/exit` 豁免该信封，用本表的 `{attempt_id}`，可为 JSON `null`（§4.1）。handler 仅可写黑板。

`v15_reclaim_expired()` 不调用本函数。`retry` 只是事件的 phase 字面量（§4.10）。对未列入上表的组合调用本函数，在读 handler 之前抛 `V15_INVALID_TRANSITION`。

span 事件行由转移在调用本函数之前写入。`exit` 的 outcome 行也在调用之前写入，payload 里的 outcome 与该行相同（§3.9、§4.1）。本函数不得再插入同一 phase 的 span 行，也不得改写已经写入的 outcome。本函数插入的 `invoke_events` 只有 §9.2 的 handler 审计，不另插 span。

`invoke/enter` 返回 `abort` 时，转移做提交类终态关闭：按 `fatal` 写 `failed` 或 `aborted`，空历史行，由 schema 属主 `DROP SCHEMA … CASCADE`；子 invoke 还在同一事务里送达父（§4.3、§4.7、§4.8）。dispatcher 不自己送达。

### 9.2 handler 的调用

handler 签名是 `(p_snapshot jsonb) returns jsonb`。dispatcher 的 `search_path` 为 `pg_catalog`。调用文本由该 oid 解析出 `quote_ident(namespace) || '.' || quote_ident(proname) || '($1::jsonb)'`。`regprocedure::text` 自带参数签名，不能直接拼 `($1)`。不查 `search_path`（§0.15）。工具调用用同一机制（§5.3）。没有 `SET ROLE`。

调用前重算 §3.11 的 `handler_digest`。拼接包含 `pg_get_functiondef`、owner 角色名、`provolatile`、`prosecdef`、语言名、`proconfig`，以及规范化的 `proacl`（`aclitem::text` 按字节序升序，逗号连接，逗号后无空格；`proacl` 为 SQL NULL 时该段为空串）。并重查：

- `proowner` 仍是登记时的 `v15_hook_<hook_key>`
- `provolatile = 's'`，`prosecdef` 为真
- 语言是 `sql` 或 `plpgsql`
- `proconfig` 恰好一个元素 `search_path=pg_catalog`
- owner 对 `v15` 与 `jaz` 的任何表都没有表级权限

表权限不在 `proacl` 里，所以摘要与这道权限重查都要做。任一不符抛 `V15_HANDLER_DIGEST`（回滚类），不调用该函数。只改 owner、`search_path` 或 `GRANT` / `REVOKE` 而 `prosrc` 不变，也必须失败。

工具不走本函数。`v15.jaz_tool` 用同一套摘要与权限重查，对象是 `tool_catalog.handler`（§5.3）。

每个 handler 包在 PL/pgSQL 的 `BEGIN … EXCEPTION` 子事务里。函数内不得执行 `SAVEPOINT` 命令。

- baseline（`hook_defs.baseline_required` 或该行 `channel = baseline`）在子事务里抛出任何异常：整个转移事务失败，对外的码是 `V15_GOVERNANCE_FAULT`（回滚类）。不得把这次抛出改写成 abort 效应。
- 非 baseline **抛出**的异常：回滚该子事务，丢弃这个 handler 的返回值，写一行审计，`payload` 为 `{"op":"handler_exception","hook_key":...,"sqlstate":...,"message":...}`，`message` 截到 200 字符，然后继续下一个 handler。该异常不得变成效应。
- handler **正常返回**的非法形状、未知键、预留效应名或本阶段不允许的效应，对每个 channel 都失败整个阶段（§9.4）。这不是审计隔离路径。

同一会话 `CREATE OR REPLACE` 保持 oid。替换体之后必须在同一次装载里更新 `handler_digest`。只替换体、不更新摘要，下一次调用失败 `V15_HANDLER_DIGEST`。

### 9.3 登记

hook 的唯一写入 `hook_defs` 的路径是 bootstrap 装载与 `v15_register_hook`。工具的唯一写入 `tool_catalog` 的路径是 bootstrap 装载与 `v15_register_tool`。两套检查相同，失败都抛 `V15_HANDLER_SHAPE`，不留下该行。工具不是 hook，不得插入 `hook_defs`，也不得进入 `invoke_hooks`。

触发器在对应表的 `INSERT` 与 `UPDATE` 时重做下列检查：

- `provolatile = 's'`。`IMMUTABLE` 与 `VOLATILE` 都拒绝。语言只允许 `sql` 与 `plpgsql`。C 语言拒绝。
- `prosecdef` 为真。owner 是 `NOLOGIN`、非超级用户。hook 的角色名等于 `v15_hook_` 接 `hook_key`。工具的角色名等于 `v15_tool_` 接 `tool_catalog.name`。
- 名字匹配 `^[a-z][a-z0-9_]{0,53}$`。
- 参数是一个 `jsonb`，返回 `jsonb`，无 `OUT` 参数。工具签名就是 `(jsonb) returns jsonb`。
- `proconfig` 恰好是 `search_path=pg_catalog` 这一个元素，不得出现 `pg_temp`。
- owner 对 `v15` 与 `jaz` 的任何表都没有表级权限。
- `REVOKE ALL ON FUNCTION … FROM PUBLIC` 已经生效。`EXECUTE` 只存在于 `v15_owner`，该授权没有 `GRANT OPTION`。没有其他被授权者。运行时不得再 `GRANT`。

`handler_digest` 按 §3.11 在登记时写入，因此已经包含当时的规范化 `proacl`。登记函数不调用 handler。`ALTER FUNCTION` 不触发这些表上的触发器，所以 §9.2 与 §5.3 的调用前重查是运行时的背书。

### 9.4 效应闭集与阶段允许表

正常返回里出现未列出的键，或 `contract` 不是 1：`V15_PHASE_CONTRACT`。`action` 不是 `proceed` 或 `abort`：同样是 `V15_PHASE_CONTRACT`。这两个码对每个 channel 都回滚阶段，不走审计隔离。

返回值到效应的对应：

| 返回 | 效应 |
|---|---|
| `action = abort` | `abort`。必须有布尔 `fatal`，以及 `error.code`（§13 里的一个 `V15_*` 名）。`error.message` 是文本，可以为空 |
| `messages` 的元素 | `add_messages` |
| `message_drops` 的元素 | `drop_messages` |
| `recursion_available = false` | `disable_recursion` |
| `input_adds` / `input_drops` | `add_inputs` / `drop_inputs` |
| `exec_result` 不是 SQL NULL | `modify_exec_result` |
| `blackboard_writes` 的元素 | `blackboard_write` |
| `budget` 不是 SQL NULL | 预算指令，不是效应名 |

`recursion_available = true` 抛 `V15_GOVERNANCE_RAISE`，整个阶段回滚。`error.code` 不是 §13 的名字：`V15_INVALID_EFFECT`，整个阶段回滚，不得改记成 `V15_HOOK_ABORT`。

下列名字出现在返回对象的任何键或嵌套文本键上，都是 `V15_INVALID_EFFECT`，每个 channel 一样，不得改走审计：`supply_llm_response`、`supply_invoke_result`、`modify_invoke_result`、`supply_exec_result`、`modify_llm_response`。允许表之外的效应同样是 `V15_INVALID_EFFECT`。

| span | phase | 允许 |
|---|---|---|
| `invoke` | `enter` | `abort`、`add_messages`（`persistent` 必须为 true）、`disable_recursion`、`add_inputs`、`drop_inputs`、`blackboard_write`。没有 `drop_messages` |
| `invoke` | `complete` | `blackboard_write` |
| `invoke` | `exit` | `blackboard_write` |
| `llm_query` | `enter` | `abort`、`add_messages`、`drop_messages`、`disable_recursion`、`blackboard_write` |
| `llm_query` | `send` | `abort`、`add_messages`、`drop_messages`、`blackboard_write`，以及 `budget` |
| `llm_query` | `complete` | `abort`、`add_messages`、`drop_messages`、`blackboard_write` |
| `llm_query` | `exit` | `blackboard_write` |
| `repl_exec` | `enter` | `abort`、`add_messages`、`drop_messages`、`blackboard_write` |
| `repl_exec` | `send` | `abort`、`blackboard_write` |
| `repl_exec` | `complete` | `abort`、`modify_exec_result`、`add_messages`、`drop_messages`、`blackboard_write` |
| `repl_exec` | `exit` | `blackboard_write` |

三个 `exit` 都不得 `abort`。handler 在 `exit` 正常返回 `action = abort`：`V15_INVALID_EFFECT`，整笔事务回滚，调用前已经写下的 outcome 行也不提交（V15-D26）。`exit` 只能写黑板，不能改 outcome。

`budget` 只允许在 `llm_query/send`。其他阶段出现 `budget` 即 `V15_INVALID_EFFECT`。形状是 `{"reserve_calls": int, "reserve_cost": numeric}`，`reserve_calls >= 1`，`reserve_cost >= 0`。stage 9 没有任何 handler 给出 `budget` 时，`send` 的 `proceed` 仍使用 `{reserve_calls:1, reserve_cost:0}`，并且返回值里必须有 `budget` 键。

`add_messages` 的元素是 `{id, role, content, persistent}`。`id` 长度 1..200，不得等于 `seed:system` 或 `seed:inputs`，不得匹配 `^iter:[0-9]+:(assistant|observation)$`，否则 `V15_VALUE_INVALID`。`role` 只允许 `system`、`user`、`assistant`。`persistent = false` 只允许在 `llm_query/send`；其他允许 `add_messages` 的阶段里 `persistent` 必须为 true，否则 `V15_INVALID_EFFECT`。`message_drops` 的元素是 `{id}`。这里的 `id` 就是 `llm_messages.message_id`，也是 `request.messages[].message_id`（§3.5）。

`input_adds` 的元素是 `{name, value, show_in_prompt}`。`name` 服从 §5.2。`value` 不得为 SQL NULL。`kind` 固定为 `input`，`provenance` 固定为 `hook`。`input_drops` 的元素是 `{name}`，只除去 `kind = input` 的名字。除去其他 `kind` 是 `V15_INVALID_EFFECT`。

`blackboard_writes` 的元素是 `{key, value}`。`key` 长度 1..200。`value` 不得为 SQL NULL。

`exec_result` 的形状是 `{result_kind, return_value, error}`。内层空值是 JSON `null`。`result_kind` 只允许 `continue`、`return`、`raise`。本版合法的修改只有两种，都只作用于候选 `return` 且 `capture` 为空串。其一是把候选 `return` 改成 `continue`，且 `return_value` 与 `error` 都是 JSON `null`。其二是把候选 `return` 改成 `raise`，`return_value` 为 JSON `null`，`error` 恰好含 `code` 与 `message`，`code` 必须是 `V15_VALIDATION_FAILED`，`message` 是长度不超过 1024 的文本。其他修改，包括改写模型 `raise`、把 `continue` 改成 `return`、`capture` 不是空串时的修改，以及 `error.code` 不是 `V15_VALIDATION_FAILED` 的 `return`→`raise`，都是 `V15_INVALID_EFFECT`。`v15_finish_exec` 接受 `continue` 时：清除 `invokes.return_value`，该 `return` 语句保持 `done`，更大下标保持 `skipped`，走 continue 分支并写历史行（§4.9）。接受 `raise` 时：清除 `return_value`，写入规范化后的 `invokes.error`，走既有 raise 分支，不增加计数。dispatcher 不自己清 `return_value`。`V15_VALIDATION_FAILED` 若出现在 `action = abort` 的 `error.code` 中，不属于四个保留 abort code，按 §9.5 归一为 `V15_HOOK_ABORT`。

### 9.5 合成

全部 handler 返回之后才合成。同键合成与 `ordinal` 无关。消息的最终排列除外。形状检查在合成之前：一个 handler 的正常返回不合法，整个阶段回滚，不把其余 handler 合成后提交。

- 同一 `id` 的 `add_messages`：对象 jsonb 相等则留一条；不相等则 `V15_EFFECT_CONFLICT`。同一 `id` 又被 drop：`V15_EFFECT_CONFLICT`。不同 `id` 都保留，排序键是 `(ordinal, 该 handler 数组下标)`。
- 同一 `id` 的多次 drop：合并为一次。该 `id` 不在本 phase 的 add 里：无操作。drop 不得 `DELETE` 已插入的 `llm_messages`；触发器拒绝删除（§3.5）。drop 只影响本 phase 尚未落地的 add 集合，不改写 base，也不改写已经插入的持久行。
- 同一 `name` 的 `input_adds`：`value` 与 `show_in_prompt` 都相等则留一条；否则 `V15_INPUT_CONFLICT`。同一 `name` 既 add 又 drop：`V15_INPUT_CONFLICT`。
- 同一黑板 `key`：`value` jsonb 相等则留一条；否则 `V15_BLACKBOARD_CONFLICT`。
- `exec_result`：jsonb 相等则留一份。同相位同时出现 `result_kind = raise` 与 `result_kind = continue` 时取 `raise`，不报 `V15_EFFECT_CONFLICT`；发出 `continue` 的 handler 在本相位的持久消息丢弃，不写入 `llm_messages`，也不参加计数。两个不等的 `continue` 仍是 `V15_EFFECT_CONFLICT`。多个 `raise` 取 `ordinal` 最小的那条，其余 `raise` 的本相位持久消息丢弃，不写入 `llm_messages`，也不参加计数。
- `budget`：jsonb 相等则留一份；否则 `V15_EFFECT_CONFLICT`。
- 多个 `disable_recursion`：合并为一次。
- `abort`：先规范化每一个 `error.code`。hook 可保留的 abort 码集合闭合为 `{V15_IO_EXHAUSTED, V15_BUDGET_EXHAUSTED, V15_RECURSION_EXCEEDED, V15_ITERATION_EXCEEDED}`。集合内的码保持不变。保留码的 `fatal` 强制取 §13 的规范值：`V15_BUDGET_EXHAUSTED` 为 true，其余三码为 false。返回的 `fatal` 与规范值不符时不报错，直接归一。hook 返回的其他任何码一律归一为 `V15_HOOK_ABORT`（`P1538`）。规范化后的码全部相同：顶层 `code` 用该码。不相同：顶层 `code` 为 `V15_HOOK_ABORT`。两种情况都是提交类，`fatal` 取归一后的或。`error.message` 不参加相等判断；落地时用 `ordinal` 最小的那条，截到 1024 字符。不得回滚去换 `V15_EFFECT_CONFLICT`，不得提交带 `payload.codes` 的替代行。未知名字仍是 `V15_INVALID_EFFECT`（§9.4），不走这条归一。

`V15_EFFECT_CONFLICT`、`V15_INPUT_CONFLICT`、`V15_BLACKBOARD_CONFLICT` 以及形状类的 `V15_PHASE_CONTRACT`、`V15_INVALID_EFFECT` 都是回滚类。阶段事务失败，不写黑板、不改 binding、不追加消息、不动预算、不留下审计行。worker 不得把这种回滚提交成另一种终态。

合成结果含 `abort` 时，丢弃本 phase 其余效应，把规范化之后的码放到返回值的顶层 `code`。转移按 §4 做提交类终态。abort 与黑板写不同时落地。`exit` 上不存在这条提交路径：那里的 abort 已经在 §9.4 被拒绝。

### 9.6 落地顺序

LLM 路径的持久 hook 行只由 `v15_on_phase` 写入。`v15_begin_llm` 不得向 `llm_messages` 插入 hook 消息。它只把已经合成的列表抄进 `request.messages`。种子、助手回复、观测仍由 §3.5 点名的转移写入，那些不是 hook 消息。

除下面的 LLM 首次尝试之外，`action = proceed` 时，本函数在返回前按此顺序落地。handler 不得自己写这些表。本函数不锁 `invokes`。

1. `input_drops`，然后 `input_adds`。新行 `kind = input`、`provenance = hook`。名字已被别的 `kind` 占用：`V15_INPUT_CONFLICT`。
2. `disable_recursion`：把 `invokes.recursion_available` 置为 false。已经是 false 则不改 `revision`。禁止置回 true。
3. 持久消息追加进 `llm_messages`：`kind = persistent_hook`，`message_id` 等于效应的 `id`，`msg_seq` 为 `max(seq)+1`。`invoke/enter` 不在这一步写持久消息，见下。落地前若该 id 已存在于 `llm_messages`，抛 `V15_VALUE_INVALID`，本 phase 回滚，不触发原生 `23505`。瞬态消息不插入这张表。
4. 黑板。对每个键：

```text
INSERT INTO blackboard (invoke_id, key, value, generation)
VALUES (invoke, key, value, 1)
ON CONFLICT (invoke_id, key) DO UPDATE
   SET value = EXCLUDED.value,
       generation = blackboard.generation + 1,
       revision = blackboard.revision + 1
```

新键的 `generation` 为 1。本 phase 的 handler 只看见步骤 4 之前的快照。下一 phase 才看见新代（§0.12）。预留失败或阶段回滚时，generation 不增加。

`invoke/enter` 只应用步骤 1、2、4，并返回 `messages`，不写 `llm_messages`。种子与返回的持久消息由 `v15_open_invoke` 或子 open 插入（§4.3）。

**LLM 首次尝试。** enter 调用不落库任何效应。`io.enter_messages` 只带消息列表。`io.enter_overlay` 只带 `recursion_available` 与 `blackboard_writes`。send handler 看见这份内存叠加，库中无这些行。`send` 且合成结果为 `proceed` 时，预留是任何落库之前的第一笔（§0.12、§11.3）：

1. 池上的条件 `UPDATE` 使用合成后的 `budget`；没有 handler 给出时用缺省 `{reserve_calls:1, reserve_cost:0}`。`pool_id` 为空则跳过 `UPDATE`，数字仍然放进返回值的 `budget`。
2. 更新到 0 行：不写 enter 的效应，也不写 send 的效应。`v15_on_phase` 永不自行把 invoke 置终态；它只返回 `action = abort`、`fatal = true`、`code = V15_BUDGET_EXHAUSTED`。终态行与 §4.8 由 `v15_begin_llm` 写。`v15_begin_llm` 丢弃两份效应，按 §4.5.1 做提交类关闭，不得插入 attempt，有父则同一事务 §4.8。
3. 预留成功是唯一落库点：先落 `enter_overlay` 一次，再落 send 自身的非消息效应，再按 `max(seq)+1` 写消息，然后返回。不第二次调用 handler，不再次预留。

`v15_begin_llm` 把 `enter_messages` 与 `enter_overlay` 传入 send，自己不 `INSERT` `llm_messages`。LLM 路径的 `llm_messages` 只由 `v15_on_phase` 在预留成功之后写入。桩返回的效应为空时，落地是无操作。stage 9 不改变 `v15_on_phase` 的签名。

最终 `request.messages` 的顺序仍是 base，然后 enter 列表，然后 send 列表（§3.4、§4.5.1）。持久元素既在 `llm_messages` 里，也在对应列表里，不得因为落地之后再读 `msg_seq` 而出现第二次。`persistent = false` 的元素 `kind = transient_hook`，只进 `request`。结算之后，当前迭代最新一次 `settled` attempt 的这些元素由 `jaz.request_messages` 读出（§3.15、§5.4）。

forcing 计数不在 `complete` 里改。接受 return→continue 时由 `v15_finish_exec` 更新（§4.9、§10.2）。dispatcher 不在 `complete` 中改 `hook_counters`。

桩体与 govern 体的分工：

- govern 体（stage 9 的 `v15_on_phase`）在 phase 路径做唯一预留。`v15_begin_llm` 看见 `budget` 键就不得再 `UPDATE` 池。
- `v15_on_phase` 桩函数体覆盖 stage 1–8，不预留。`v15_begin_llm` 的桩路径预留只在 io stage（6）起实际存在：`pool_id` 为空时把 attempt 的两列写成 1 与 0，不对池 `UPDATE`；`pool_id` 非空时按缺省 `{reserve_calls:1, reserve_cost:0}` 做同一条 `UPDATE`。更新到 0 行走 `V15_BUDGET_EXHAUSTED`，`fatal = true`，不插入 attempt。
- 重试不调用本函数。那一次同一 `UPDATE` 只在 `v15_begin_llm` 里，数量是上一 attempt 存放的两列（§4.5.1、§0.28）。

预留已经写入、而同一事务改为终态且不会留下对应的 `leased` 或 `settled` attempt 时，退款由那个转移按 §11.3 完成。回滚类错误不退款。

### 9.7 与 §4 的衔接

| `phase_effect` | 谁消费 |
|---|---|
| `invoke/enter` 的 `abort` | §4.3 与 §4.7 的提交类关闭。子 invoke 的送达在产生该终态的同一事务。父语句码是 `V15_CHILD_ERROR`，除非 `fatal = true` |
| `action = abort`，且阶段不是 `exit` | §4.5、§4.6.1、§4.9。顶层 `code` 进入终态与 §4.8。回滚类的码不会出现在这里 |
| `llm_query/send` 的预留 | 本函数内、效应落地之前的唯一一次。0 行由 §4.5.1 写成 `V15_BUDGET_EXHAUSTED` |
| `enter` 与 `send` 的 `messages` | 预留成功之后由 `v15_on_phase` 按 enter 然后 send 落地。`v15_begin_llm` 只按同一顺序抄进 `request` |
| `repl_exec/complete` 的 `exec_result` | 仅 `v15_finish_exec`（§4.9）。内层 JSON `null` 是合法的 |
| 三个 `exit` | 只落地黑板。outcome 已经写好 |
| 黑板、输入、`recursion_available` | 落地之后的后续 phase，以及提交后的下一语句 |

`v15_finish_exec` 在写终态之前调用 `repl_exec/complete`。`continue`、`return`、`raise` 都调用。`abort` 不得先把 invoke 写成 `completed`。return 路径在行已是 `completed` 之后调用 `invoke/complete` 与 `invoke/exit`，`io` 为 `{"outcome":"completed"}`。raise 与 `fatal = false` 的关闭调用 `invoke/exit`，`outcome` 为 `failed`，不调用 `invoke/complete`。`fatal = true` 的 `invoke/exit` 使用 `aborted`。这些调用都在 §4 已经打开的那个事务里。先写 `exit` 行，再调用 `exit` phase。`repl_exec/exit` 的 outcome 以 §4.9 的表为准。

## 10. 五个内置 hook

四个治理 hook 是 baseline，open 必装（§8.6）。五个 jaz 对等 hook 是可选内置：`hook_defs.baseline_required = false`。它们不得进入 `channel = baseline`，也不得出现在 `config_profiles.baseline_hooks` 里，否则 open 抛 `V15_VALUE_INVALID`。可选 hook 只通过 propagating 或 local 的 `extra_hooks` 安装。它们不代替四行治理 baseline。

stage 1 建立四个治理 handler 的桩（返回 `{"contract":1,"action":"proceed"}`）与对应 `hook_defs` 行。stage 9 按原 oid `CREATE OR REPLACE` 成下面的体，并更新 `handler_digest`。五个可选 hook 的函数与 `hook_defs` 只在 stage 9 创建。

handler 在自己不负责的阶段必须返回 `{"contract":1,"action":"proceed"}`，不带任何效应。它们不得在任何 `exit` 上返回 `abort`。

### 10.1 四个治理 baseline

四行的 `config` 都是 `{"max": <该 invoke 的有效整数>}`。handler 读 `self.config.max`，并与 `snapshot.ceilings` 的对应字段比较。不一致则 `RAISE`，码为 `V15_MANIFEST_DIGEST`。baseline 的抛出使转移对外成为 `V15_GOVERNANCE_FAULT`（§9.2）。调用前的 `v15_assert_invoke_manifest` 才是 gate 通常看见的 `V15_MANIFEST_DIGEST`（§11.1）。`max < 1` 同样是 baseline 故障。

内核在调用 dispatcher 之前执行同一谓词（§4.3、§4.5.1）。hook 不能取消已经做出的内核中止。stage 1–8 的桩不调用 handler，上限仍由内核谓词执行。比较符必须与内核相同：迭代用 `>=`，I/O 的下一序号用 `>`，深度用 `>` 与 `=`。

| `hook_key` | 阶段 | 谓词与效应 |
|---|---|---|
| `governance_iterations` | `llm_query/enter` | `iteration >= max` 时 `abort`，`fatal = false`，`error.code = V15_ITERATION_EXCEEDED`。此判定在预留与插入 attempt 之前。该码在 §13 含提交类，提交时保持原码 |
| `governance_depth` | `invoke/enter` | `depth > max` 时 `abort`，`fatal = false`，`error.code = V15_RECURSION_EXCEEDED`。`depth = max` 时 `recursion_available = false`。`depth < max` 时不发出效应。内核守卫若已走失败路径，不得再调用 handler（§4.3） |
| `governance_io` | `llm_query/enter` | 读 `io.next_attempt_n`。该值 `> max` 时 `abort`，`fatal = false`，`error.code = V15_IO_EXHAUSTED`，不预留，不插入。重试不再发 `enter`；同一上限由 `v15_begin_llm` 的内核比较继续执行（§4.5.1） |
| `governance_statement` | `repl_exec/enter` | 核对 `max >= 1` 且等于 `ceilings.max_statement_ms`。不返回超时效应。`v15_prepare_statement` 返回的 `timeout_ms` 不得大于这个 `max`（§6.3） |

`governance_depth` 发出的 false 与 open 时的初值合成之后仍是 false。任何把该位写回 true 的返回都是 `V15_GOVERNANCE_RAISE`。

### 10.2 五个可选 hook

安装时的收紧检查在 open 事务内完成。失败时根 open 无行，子 open 按语句失败收束。`config.max` 大于该 invoke 已有效的治理上限，是 `V15_GOVERNANCE_RAISE`。

**`iteration_limit`。** channel 为 propagating 或 local。`config = {"max": int}`，且 `1 <= max <= ceilings.max_iterations`。阶段 `llm_query/enter`：`iteration >= config.max` 时 `abort`，`fatal = false`，`error.code = V15_ITERATION_EXCEEDED`。与治理 hook 的码相同，合成是一条 abort。它不写 `hook_counters`。同一次迭代的重试不再发 `enter`。

**`recursion_limit`。** channel 为 propagating 或 local。local 允许，这是收紧。`config = {"max": int}`，且 `1 <= max <= ceilings.max_depth`。阶段 `invoke/enter`：`depth > max` 时 `abort`、`fatal = false`、`error.code = V15_RECURSION_EXCEEDED`；`depth = max` 时 `recursion_available = false`。local 行不复制给子（§8.3）。要约束整棵子树，用 propagating。多个 false 合成一次。

**`budget_pool`。** channel 为 propagating 或 local。`config = {"reserve_calls": int, "reserve_cost": numeric}`，缺省 1 与 0。`invokes.pool_id` 为空却装了这个 hook：open 抛 `V15_VALUE_INVALID`。hook 不得改 `pool_id`，不得改两个上限。阶段是 `llm_query/send`：返回 `budget`。池上的 `UPDATE` 只由 `send` 的 dispatcher 在任何效应落地之前执行（§9.6、§11.3）。两份 `budget` jsonb 不等则 `V15_EFFECT_CONFLICT`，阶段回滚，预留不留下。重试不调用 `send`，因此不重新读这份 `config`；`v15_begin_llm` 复制上一 attempt 已经存放的 `reserved_calls` 与 `reserved_cost`。

**`budget_forcing`。** channel 为 propagating 或 local。`config = {"max_rejections": int}` 且 `>= 1`。计数键是 `budget_forcing:<ordinal>`，存在 `hook_counters`。阶段只在 `repl_exec/complete`。候选 `result_kind = return`、`capture = ''`、且该计数 `< max_rejections` 时，返回：

- `exec_result = {"result_kind":"continue","return_value":null,"error":null}`，内层是 JSON `null`
- 一条持久消息，`role = user`，`id = budget_forcing:<ordinal>:<n>`。`n` 是该计数当前值，也就是本次若被接受、增加之前的值。正文逐字为：

```text
[v15 budget_forcing] The finish was not accepted. Continue the task. Finished iterations are rows of jaz.history.
```

`v15_finish_exec` 接受这次修改时，对每个被接受的消息 id `budget_forcing:<ordinal>:<n>` 把该键加一，每消息一次，同时 `revision = revision + 1`。dispatcher 不在 `complete` 中改计数（§4.9）。计数已经达到 `max_rejections`、候选是 `raise` 或 `continue`、或 `capture <> ''` 时，返回 proceed 且不修改。强制继续不能越过 `governance_iterations`：下一轮 `llm_query/enter` 仍按迭代上限中止。持久消息进入 `llm_messages`。不得把 `jaz."raise"` 改成 continue。

**`context_window_warning`。** channel 为 propagating 或 local。`config = {"ratio": numeric}`，`> 0` 且 `<= 1`。不写计数，不写黑板。阶段只在 `llm_query/send`。`io.input_chars >= floor(protocol.max_invoke_input_length * ratio)` 时追加一条瞬态消息：`persistent = false`，`role = user`，`id = context_window_warning`。正文由 `snapshot.recursion_available` 选择，两套都逐字冻结。

`recursion_available = true` 时：

```text
[v15 context_window_warning] The prompt is near max_invoke_input_length. Finished iterations are rows of jaz.history. Ancestor history is jaz.prior_history(invoke_id). To delegate, end with exactly these two statements and no further statements after them:
SELECT jaz.bind_invoke('<ident>', <jsonb-expr>);
SELECT jaz."return"(jaz.var('<ident>'));
```

`recursion_available = false` 时，正文停在历史句，不得出现 `bind_invoke`：

```text
[v15 context_window_warning] The prompt is near max_invoke_input_length. Finished iterations are rows of jaz.history. Ancestor history is jaz.prior_history(invoke_id).
```

该消息只进入本 attempt 的 `request`，不进入 `llm_messages`。结算之后由 `jaz.request_messages` 可见。截断仍只由 §6.5 对 base 做。本 hook 不截断、不 abort。重试复制上一份 `request.messages`，不再发 `send`，因此不追加第二条同样的警告。

原有五个可选 hook 之上，rev 10 追加两个 return-validation hook family：内建 `return_type`，以及注册式 `validate_return` / `validate_return_<suffix>`。handler 的 CREATE、权限与 `hook_defs` 插入仍只许出现在 govern 文件。`validate_return*` 不预插 builtin 行，由 `v15_register_hook` 登记。

**`return_type`。** channel 为 propagating 或 local。`invoke_hooks.config` 必须是对象，且键集合恰好为：

```text
{
  "spec": <jsonb 规格对象>,
  "max_failures": <JSON null or [0, 2147483647] 整数>
}
```

`spec` 是封闭 jsonb 类型规格，恰好一种形态。判定用 exact-keys。

| 形态 | 键 | 含义 |
|---|---|---|
| 标量 | 只有 `type`，值 `any` / `null` / `string` / `number` / `boolean` | `jsonb_typeof` 相等；`any` 接受任何 jsonb，含 JSON `null` |
| 数组 | 恰好 `type=array` + `items`（递归 spec） | 每元素匹配 `items`；空数组通过 |
| 对象 | 恰好 `type=object` + `required`（字符串数组）+ `properties`（对象，值为 spec） | 见下 |
| 联合 | 只有 `anyOf`，非空数组 1..8，元素是 spec | 任一分支匹配即通过 |
| 枚举 | 只有 `enum`，非空数组 | 与任一元素 jsonb 相等即通过 |

对象规则：`required` 名字两两不同且都在 `properties`。`properties` 中不在 `required` 的键是可选键：值里缺该键则通过，有则按 spec 查。值里多余键允许。键名 `^[A-Za-z_][A-Za-z0-9_]{0,62}$`。嵌套深度 ≤ 8，根为 1。数字不区分整数与浮点：`jsonb` 的 `number` 是一种。

安装期用 `v15_return_spec_valid(spec)` 做形状校验。非法 spec、多余键、坏形态、深度超限、坏键名、`anyOf` 超 8、`max_failures` 非法，都在安装期抛 `V15_VALUE_INVALID` / `P1524`。

运行期 `v15_return_spec_fault(value, spec) returns text`：匹配返回 SQL NULL；否则返回不带前缀的失败文字。spec 非法时返回 `config spec invalid`，不抛异常。运行期任何错误按校验失败处理。

`render(spec)` 由 `v15_return_spec_render(jsonb) returns text` 实现。标量等于 type 词；数组为 `array of <render(items)>`；对象为 `object {` + required 按序 `<key>: <render>` + 可选键按 UTF-8 字节序 `<key>?: <render>` + `}`，多项之间是 `, `，花括号内侧无空格；anyOf 为 `anyOf (<render> | <render>)`，分支之间是 ` | `；enum 为 `enum (<elem::text>, ...)`，元素之间是 `, `。enum 通过性按 jsonb 数值相等（`enum:[1]` 匹配 `1.0`），展示按 `elem::text` 字形。

失败文字从 `$` 起。根类型不符：`Expected <render(root)>. Got jsonb <typeof>.`。深层：`Expected <render(node)> at <path>. Got jsonb <typeof>.`。缺必填键：`Expected <render(root)>. Missing key <path>.`。anyOf 全败与 enum 不符不钻进分支：一律用根模板配该节点整棵 render，不写 `at <path>`。SQL NULL 根值的失败文字是 `Expected <render(root)>. Got SQL NULL.`。handler 前缀是 `[v15 return_type] `（一个空格）。continue 消息与 raise 的 `error.message` 是同一整句。

冻结示例：

```text
spec {"type":"string"}，值 1：
[v15 return_type] Expected string. Got jsonb number.
spec {"type":"object","required":["n"],"properties":{"n":{"type":"number"}}}，值 {}：
[v15 return_type] Expected object {n: number}. Missing key $.n.
同 spec，值 {"n":"x"}：
[v15 return_type] Expected number at $.n. Got jsonb string.
spec {"anyOf":[{"type":"string"},{"type":"null"}]}，值 1：
[v15 return_type] Expected anyOf (string | null). Got jsonb number.
spec {"type":"object","required":["x"],"properties":{"x":{"anyOf":[{"type":"string"},{"type":"null"}]}}}，值 {"x":1}：
[v15 return_type] Expected anyOf (string | null). Got jsonb number.
```

两只内核辅助函数的 owner 是 `v15_owner`，STABLE，SECURITY INVOKER，`search_path = pg_catalog`，REVOKE PUBLIC，`GRANT EXECUTE` 给 `v15_owner` 与 `v15_hook_return_type`。`v15_hook_return_type` 还须有 schema `v15` 的 USAGE，否则 schema 限定调用在 handler 内因权限失败，被异常隔离当成通过。它们放在 govern 文件。`v15_return_spec_valid(jsonb) returns boolean` 只走形状。`v15_return_spec_fault(jsonb, jsonb) returns text` 做运行期匹配。

`llm_query/enter` 且 `iteration = 0`、`next_attempt_n = 1` 时，返回一条持久 user message。id 固定为 `return_type:prompt:<ordinal>`，不参与计数。正文含 `render(spec)`。`next_attempt_n > 1` 不再生成。

`repl_exec/complete` 且 `io.result_kind = return` 且 `io.capture = ''` 时，调用 `v15_return_spec_fault`。SQL NULL 则 proceed。否则调用 `v15_return_validation_effect`。其他 phase proceed。

`max_failures` 为 JSON null 时，该 hook 永不升级，但每次可恢复拒绝仍递增计数。当前计数小于 `max_failures` 时 return→continue，并带一条持久消息，id 为 `return_type:<ordinal>:<n>`，`n` 是增加前的计数值。当前计数已达到 `max_failures` 时 return→raise，`error.code = V15_VALIDATION_FAILED`，不产生计数消息，因此不 bump。计数只在 `v15_finish_exec` 接受 return→continue 之后增加。

**`validate_return` 与 `validate_return_<suffix>`。** 完整 key 仍须满足 `hook_defs.hook_key` 名称正则。每个 key 有自己的 `v15_hook_<key>` owner、handler oid、digest 与 ordinal。config 键集合恰好为 `{"max_failures": <JSON null or non-negative integer>}`，规则与 `return_type.max_failures` 相同。只能以 propagating 或 local 安装。安装期坏 config 抛 `P1524`。handler 形状不符抛 `P1537`。

handler 在 `span/phase` 不是 `repl_exec/complete`，或 `io.result_kind` 不是 `return` 时返回 proceed。拒绝时调用 `v15_return_validation_effect(snapshot, valid, message)`，不得用直接 `RAISE` 表示值不合法。直接抛出的异常仍走既有非 baseline 隔离，不算校验拒绝，不 bump。每个 validator 的计数按自己的 full hook key 与 ordinal 隔离。

`v15_return_validation_effect(jsonb, boolean, text) returns jsonb` 放在 stage 11。它不写表，不改计数。仅当 `p_valid` 为 SQL `true`、非 `repl_exec/complete`、非 return 候选或 `capture` 非空时返回 proceed。`p_valid` 为 SQL NULL 或 `false` 走拒绝路径。`p_message` 为 SQL NULL 时用 `validation message missing`；超过 1024 时截到 1024，不抛异常。计数行缺席视为 0；计数行存在但值畸形、`ordinal` 不在 `0..2147483647`、或 hook key 不在 counted family 白名单时 fail-closed 为 raise，不生成不可计数的 continue。未达上限时返回 continue 与一条持久消息，id 为 `<hook_key>:<ordinal>:<n>`。已达上限时返回 raise，`error = {"code":"V15_VALIDATION_FAILED","message":<原始消息>}`，不产生计数消息。`v15_register_hook` 登记 `validate_return` / `validate_return_*` 时授予 schema `v15` 的 USAGE 和该函数的 EXECUTE 给 `v15_hook_<key>`。

计数键是 `<hook_key>:<ordinal>`。`v15_loop_accept_forcing` 名字与签名不变。它只接受 `budget_forcing`、`return_type`、`validate_return`，以及以 `validate_return_` 开头的 key。`(invoke_id, ordinal)` 必须存在，且关联的 `hook_key` 等于消息中的 key，否则 `V15_INVALID_TRANSITION`。同一 message id 只 bump 一次。不比对消息里的 `n` 与库值。第 2、3 段不是数字，或数字溢出，则跳过，不抛 `V15_PHASE_CONTRACT`。`n` 达到 bigint 最大值时，接受函数以 `V15_VALUE_INVALID` 失败，不允许溢出。

## 11. 治理与预算

### 11.1 两道断言

```text
v15_assert_manifest() returns void
v15_assert_invoke_manifest(invoke_id uuid) returns void
```

`v15_assert_manifest()`、`v15_assert_invoke_manifest(uuid)` 与 `v15_on_phase(...)` 都是 `VOLATILE`、`SECURITY DEFINER`、`search_path = pg_catalog`。`EXECUTE` 只授 `v15_owner`，无 `GRANT OPTION`，不授 `v15_worker`。调用它们的转移函数以 definer 身份（`v15_owner`）执行（§2、§4.1）。体内不得切换角色。

`v15_assert_manifest` 对 `governance_manifest` 取 `SHARE` 锁，并且在任何 `invokes` 或 `budget_pools` 的排他锁之前（§4.1）。单例行不存在、四项上限有一项不是 `>= 1` 的整数、或存放的 `governance_manifest.manifest_digest` 与这四列的重算不一致：`V15_GOVERNANCE_MISSING`。它不比较 `invokes.manifest_digest`。

`v15_assert_invoke_manifest` 从该 invoke 的四行 baseline 拼出 §8.5 的有效 `ceilings`，`md5(ceilings::text)` 必须等于 `invokes.manifest_digest`，且每项 `>= 1`。否则 `V15_MANIFEST_DIGEST`。缺少任一行 baseline 同样是这个码。`invokes.manifest_digest` 摘要的是这份有效上限，不是单例行的摘要。二者相等，仅当 `p_ceilings` 为空且 open 之后清单四项没有变过（§3.13、§8.5）。本函数不读清单表上的新数值，因此事后收紧清单不会让已打开的 invoke 在这里失败（§8.4）。

`v15_open_invoke` 与 `v15_begin_llm` 在修改控制行之前调用 `v15_assert_manifest`。`v15_begin_llm` 还调用 `v15_assert_invoke_manifest`。`v15_settle_llm` 不调用这两道断言。`v15_reclaim_expired()` 也不调用。清单缺失可以使以后的 open 与 begin 失败，但不得让已经过期的 attempt 停在 `leased`（§4.10、§0.6）。

`invoke_hooks` 上的触发器拒绝一切 `DELETE`，并拒绝 `UPDATE` baseline 行的 `config`、`channel`、`hook_def_id`、`ordinal`。违反者抛 `V15_BASELINE_IMMUTABLE`。非 baseline 行的 `state` 在本版保持 `{}`。计数放在 `hook_counters`，不放在 `state`。

### 11.2 有效上限

有效四元组在 open 时算完，写入四行 baseline 的 `config.max` 与 `invokes.manifest_digest`（§4.3、§8.5）。根的起点是清单，`p_ceilings` 只许更小。子的起点是父的有效四元组，再与当时清单逐项取较小值（§8.3）。比较是整数比较。

推进路径上的迭代、深度、I/O 次数、语句毫秒数只读这份已冻结的四元组。`resolved_config` 里出现这四个名字是折叠错误 `V15_VALUE_INVALID`（§8.4）。

### 11.3 池的预留、结算与退款

`pool_id` 为空则不做下列 `UPDATE`。attempt 上的 `reserved_calls` 与 `reserved_cost` 仍要写入。`max_io_attempts` 仍然有效。锁顺序以 §4.1 为准：无锁读出 id，按 `pool_id` 升序锁池，再按 `invoke_id` 升序锁将要写的全部 invoke，然后重读 fence 与状态。dispatcher 不另取 `invokes` 锁。handler 不锁这些行。

数量来自类型化列，或来自即将写入这两列的合成结果。不得把调用次数写成字面量 1，除非合成结果或上一行存放的值就是 1。`prompt_tokens` 与 `cost_usd` 一旦出现，必须 `>= 0`（§3.4）。

预留是该次 `send` 的第一笔落库，早于消息、黑板、输入与 `recursion_available`（§9.6）。govern 体的首次 `UPDATE` 在 `v15_on_phase` 内。`v15_on_phase` 桩函数体覆盖 stage 1–8；`v15_begin_llm` 的桩路径预留只在 io stage（6）起实际存在，数量是缺省 1 与 0。重试的 `UPDATE` 只在 `v15_begin_llm`，数量是上一行存放的两列。同一事务对同一次尝试只有这一次池 `UPDATE`。返回值已经含 `budget` 时，`v15_begin_llm` 不得再执行它。

```text
UPDATE budget_pools
   SET calls_reserved = calls_reserved + reserved_calls,
       cost_reserved  = cost_reserved  + reserved_cost,
       revision = revision + 1
 WHERE pool_id = pool
   AND (calls_limit IS NULL
        OR calls_used + calls_reserved + reserved_calls <= calls_limit)
   AND (cost_limit IS NULL
        OR cost_used + cost_reserved + reserved_cost <= cost_limit)
```

更新到 0 行：池不足。不得插入 `leased` attempt。本 phase 尚未写入的效应保持不写。`v15_on_phase` 在 0 行时只返回 abort，不把 invoke 置终态；终态行与 §4.8 由 `v15_begin_llm` 写，本 invoke 与已锁的祖先、非终态后代 `aborted`，`fatal = true`，`error.code = V15_BUDGET_EXHAUSTED`（§0.21、§4.5.1、§4.8、§9.6）。这不是 `V15_INVALID_TRANSITION`，也不是 `V15_HOOK_ABORT`。桩路径与重试路径的那一次 `UPDATE` 在 `v15_begin_llm` 内，由它写终态。

结算，在 `v15_settle_llm` 把 attempt 写成 `settled` 的同一语句序列里，`calls_charged` 改为 true。两列用该行已经存放的值：

```text
calls_reserved = calls_reserved - reserved_calls
calls_used     = calls_used     + reserved_calls
cost_reserved  = cost_reserved  - reserved_cost
cost_used      = cost_used      + cost_usd
```

这条结算 `UPDATE`，以及从 `calls_reserved`、`cost_reserved` 减去存放预留量的退款 `UPDATE`（usage 不动），都加守卫 `AND calls_reserved >= <reserved_calls> AND cost_reserved >= <reserved_cost>`。差额下穿影响 0 行，抛 `V15_INVALID_TRANSITION`，不得撞上 `calls_reserved >= 0` / `cost_reserved >= 0` 的 CHECK。

`cost_limit` 非空且 `cost_used` 超过它：attempt 仍是 `settled`，invoke 与已锁祖先、非终态后代以 `fatal = true`、`V15_BUDGET_EXHAUSTED` 提交类中止，不写转录（§4.5.3）。

回收（§4.10），仍用该行存放的两列：

- `call_started = true`：行置 `unknown`，`calls_charged = true`。`calls_reserved` 减去存放值，`calls_used` 加上存放值，`cost_reserved` 减去存放值，`cost_used` 不变。
- `call_started = false`：行置 `failed`。只减去两份预留。不增加 `calls_used` 或 `cost_used`。

预留已经写入，而同一事务将以终态提交，且不会留下对应的 `leased` 或 `settled` attempt：同一事务从 `calls_reserved` 与 `cost_reserved` 减去存放的预留量，`calls_used` 与 `cost_used` 不动。`unknown` 不走这条退回，而走上面的转入 `calls_used` 并释放 `cost_reserved`。回滚类错误不另做退款。

结算、退款或释放影响 0 行时抛 `V15_INVALID_TRANSITION`（回滚类）。`calls_reserved` 与 `cost_reserved` 不得被更新成负数。

### 11.4 fatal 的展开

`fatal = true` 只来自两处：池无法覆盖预留，或结算后金额超过 `cost_limit`（码 `V15_BUDGET_EXHAUSTED`）；以及 `phase_effect.fatal = true` 的 abort。展开的行集合、锁顺序、span 的 `exit` / `aborted`、scratch 的 `DROP SCHEMA … CASCADE`，全部以 §4.8 为准。`fatal = false` 的治理中止只结束本 invoke。父迭代在子自身 `status = failed` 时得到 `V15_CHILD_ERROR`，子行保留自己的码。名字冲突得到的是 `V15_DELIVERY_CONFLICT`。`fatal = true` 时父的码是触发 fatal 的那个码，不是 `V15_CHILD_ERROR`。

### 11.5 桩阶段的保险丝

不存在关掉 baseline 的 GUC，也不存在 `hooks_disabled` 配置键。stage 1–8 的桩不读 `invoke_hooks`。可选 hook 的 `hook_defs` 到 stage 9 才插入。

stage 6 的测试保持 `pool_id` 为空。stage 8 可以为了证明子行 `fatal = true` 之后的 §4.8，使用非空池并走 §9.6 的桩预留。stage 9 的预留只发生在 dispatcher；测试必须断言池被加上恰好一次。

测试要证明 hook 返回的 abort 或效应，只在 stage 9 安装非 baseline hook，或直接调用已替换的治理 handler。测试不得删除四行 baseline。hook 返回 `fatal = true` 的展开，以及子 `invoke/enter` 因 hook abort 而送达，只在 stage 9 断言（§15）。不新增错误码来表示「测试用的 fatal」。

## 12. IO 与 unknown

生命周期的写入点是 §4.5 与 §4.10。本节只固定状态与记账的对应。SQL 函数不得调用 FakeLLM（§0.4）。`v15_reclaim_expired()` 没有参数。它终结过期 attempt，并按存放的预留记账；它不插入 attempt，不调用 `v15_on_phase`。它还收回 `status = leased` 且 `lease_until` 已过、并且没有存活 `leased` attempt 的 invoke：`fence` 加 1，租约清空，并做 §4.10 的语句修理。新的 attempt 只由之后的 `v15_begin_llm` 插入。span 已打开时那次插入不发 `enter` / `send`，并复制上一行的 `reserved_calls` 与 `reserved_cost`。

| 行状态 | 谁写入 | 池 | 再被 `v15_settle_llm` |
|---|---|---|---|
| `leased`，`call_started = false` | `v15_begin_llm` 的首次插入，或重试分支的 `n+1` | 预留已占，尚未入账 | `V15_INVALID_TRANSITION` |
| `leased`，`call_started = true` | 本进程自己的 `v15_mark_call_started` 提交之后 | 仍只是预留 | 栅栏匹配且 `p_owner` 匹配则 `settled`。本进程没有置过这位的，不得调用 FakeLLM，留给回收 |
| `settled` | `v15_settle_llm` | `reserved_calls` 转入 `calls_used`，`cost_usd` 加入 `cost_used`，`cost_reserved` 释放 | `V15_ATTEMPT_NOT_SETTLEABLE` |
| `failed` | 回收且当时 `call_started = false`；或 `v15_provider_reject_unstarted`（§4.5.5） | 只释放两份预留，不加 `calls_used` | `V15_ATTEMPT_NOT_SETTLEABLE` |
| `unknown` | 回收且当时 `call_started = true`；或 `v15_provider_abandon` / `v15_provider_reject_started`（§4.5.5），记账与回收相同 | `reserved_calls` 转入 `calls_used`，`cost_reserved` 释放，不加 `cost_usd` | `V15_ATTEMPT_NOT_SETTLEABLE`。不得改写终态（§0.6） |

同一 `llm_requests` 的 `n` 从 1 连续增加，不得超过有效 `max_io_attempts`。超出则 `V15_IO_EXHAUSTED`，`fatal = false`，不插入越限的那一行（§0.21）。`logical_digest` 在各 attempt 之间不变，由 SQL 对最终 `request` 去掉 `attempt_id` 之后计算（§4.5.1）。`failed` 与 `unknown` 都不是成功。provider 一旦开始（`call_started` 已提交），该行只许 `settled` 或 `unknown`。

gate 不开网络。行为循环类 gate 的唯一 LLM 仍是 `v15/fake_llm.py` 的 `FakeLLM.complete(logical_digest, n, request, llm_config=None)`。`llm_config` 可缺，FakeLLM 忽略它。返回对象含 `content`，可选 `prompt_tokens` 与 `cost_usd`，两者一旦出现必须 `>= 0`。键是 `(logical_digest, n)`，其中 `logical_digest` 是 attempt 所属 request 上存放的最终摘要。同一键的两次调用返回同一 jsonb，不含时钟、随机数或套接字。测试用 `register(digest, n, response)` 登记剧本。未登记的键在 Python 里失败，不得调用 `v15_settle_llm`；该 attempt 保持 `leased`，直到回收按 `call_started` 把它定为 `unknown` 或 `failed`。`n` 增加后是另一个键。

`v15/provider/test_provider.py` 可以注入传输构造 `DeepSeekProvider`，并且不得打开网络。`v15/provider/deepseek.py` 的默认传输只由 opt-in 驱动（`v15/provider/smoke.py --real-provider-smoke`，或手工运行）构造。worker 接受带 `complete(logical_digest, n, request, llm_config=None)` 的对象。

worker 只在自己刚刚把 `call_started` 从 false 提交为 true 之后，并且会话里没有打开的事务时，调用 `complete`。看见本进程没有置位的 `call_started = true`，留给 `v15_reclaim_expired()`。回收事务与下一次 `complete` 之间还有 claim、重试分支的 begin、以及 mark 这三次提交边界。

FakeTool 不是 Python。测试需要工具时，在该测试库里创建 `SECURITY DEFINER` 的 SQL 函数，签名 `(jsonb) returns jsonb`，owner 为 `v15_tool_<name>`，`external = false`。登记检查与 §9.3 相同。已提交的 `EXECUTE` 只给 `v15_owner`。再插入 `tool_catalog` 与 `tool_grants`。`jaz.tool` 在语句事务内按 oid 调用它，不临时 `GRANT`，不 `SET ROLE`（§5.3）。handler 不得写 scratch。`external = true` 抛 `V15_EXTERNAL_TOOL`。工具函数不进入 `SQL_LOAD_ORDER`。

## 13. 错误码表

本表是唯一码源：45 行，`P1501` 至 `P1545`，无空号，无同义名。硬顶 `P1548`。`P1546`–`P1548` 未分配，不得预占。每个 `RAISE` 使用表中的 `ERRCODE`。本族不得使用 `P0001`（§0.19）。`error` jsonb 的 `sqlstate` 与 `code` 必须来自同一行。回滚类、提交类、语句失败以本表的「分类」列为权威；§4.1 不再另列穷尽清单。

hook abort 可原样写入已提交 `error` 的码，闭集为 `{V15_IO_EXHAUSTED, V15_BUDGET_EXHAUSTED, V15_RECURSION_EXCEEDED, V15_ITERATION_EXCEEDED}`。其他任何码一律归一为 `V15_HOOK_ABORT`。多个 abort 规范化之后仍不一致，同样使用 `V15_HOOK_ABORT`（§9.5）。

`40001` 与 `40P01` 不是本表的行。它们若在 `COMMIT` 时出现，worker 把整段事务当作可重试信号，不得改写成 `V15_INVALID_TRANSITION`（§4.1）。事务内的锁等待 `55P03` 才改写成 `V15_INVALID_TRANSITION`。

分类的含义：

- **回滚类。** 转移事务 `ROLLBACK`，控制行与调用前一致。
- **提交类。** 码写在已提交的 `invokes.error` 或父语句的 `error` 里，转移事务 `COMMIT`。
- **语句失败。** 模型语句的保存点回滚；外层事务提交 `statements.status = failed` 且 `error` 非空。invoke 不因此成为机器故障。分类器拒绝与合成失败行随 `v15_settle_llm` 提交，仍算语句失败（§4.11）。

PostgreSQL 自己的 sqlstate（例如散文的 `42601`、权限不足的 `42501`）按 §4.11 原样写入 `error.sqlstate` 与 `error.code`，不是本表的行，不得包装成 `V15_DIALECT`。

| 代码 | SQLSTATE | 触发条件 | 分类 |
|---|---|---|---|
| `V15_STALE_FENCE` | `P1501` | 出示的栅栏与行上当前值不一致，且该行仍处于本次调用要求的非终态（§0.5、§4.1）。attempt 已终态时不用这个码 | 回滚类 |
| `V15_ATTEMPT_NOT_SETTLEABLE` | `P1502` | 对 `unknown`、`settled` 或 `failed` 的 attempt 调用 `v15_settle_llm`。先看终态，再看栅栏（§0.6、§4.13） | 回滚类 |
| `V15_INVOKE_FORM` | `P1503` | 非规范控制语句；记号流在字符串、注释与 dollar-quote 之外出现控制名（§6.2）；未加引号的 `return` / `raise`；在错误 `kind` 上执行控制函数；`arg_sql` 含写记号，或 `(` 前标识符匹配 `nextval`/`setval`/`currval`（含 `pg_catalog.` 限定）；求值期间调用会写的 `jaz.*`；或 `pg_stat_xact_user_tables` 显示实参事务写了 scratch（§0.9、§4.7）。不另设实参写入专用码。由 `v15_suspend_for_child` 抛出并经 §4.7 捕获 → 语句失败（提交 `failed` 行）；其余场合维持本列分类 | 语句失败 |
| `V15_GOVERNANCE_MISSING` | `P1504` | 清单行不存在，四项上限任一不是 `>= 1` 的整数，或单例上存放的 `manifest_digest` 与四列重算不一致（§3.13、§11.1）。`v15_reclaim_expired()` 不抛这个码 | 回滚类 |
| `V15_GOVERNANCE_RAISE` | `P1505` | `p_ceilings`、可选 hook 的 `max`，或 `recursion_available = true` 试图放宽已冻结上限（§0.13、§9.4、§10.2） | 回滚类。由 `v15_suspend_for_child` 抛出并经 §4.7 捕获 → 语句失败 |
| `V15_INVALID_EFFECT` | `P1506` | 效应不在闭集、不在该阶段允许表内、使用了预留名、`exit` 上返回了 `abort`，或 `exec_result` 不是两种合法 return validation transform 之一。每个 channel 的正常返回都算（§0.12、§9.4） | 回滚类 |
| `V15_TOOL_UNAUTHORIZED` | `P1507` | `jaz.tool` 时 binding 与 `tool_grants` 的合取失败（§0.14、§5.3）。只失败该语句 | 语句失败 |
| `V15_GOVERNANCE_FAULT` | `P1508` | baseline handler 抛出异常（§0.15、§9.2）。正常返回的坏形状用 `V15_PHASE_CONTRACT` 或 `V15_INVALID_EFFECT`，不用这个码 | 回滚类 |
| `V15_SCOPE_CONFLICT` | `P1509` | 同一名字以两种 `kind` 进入 open，或子 open 时复制的 scope 与新 input 同名（§0.17、§7.1）。由 `v15_suspend_for_child` 抛出并经 §4.7 捕获 → 语句失败（提交 `failed` 行）；其余场合维持本列分类 | 根 open 为回滚类；子 open 为语句失败 |
| `V15_HISTORY_SCOPE` | `P1510` | `jaz.prior_history` 的参数不是自身或祖先（§0.17、§5.3） | 语句失败 |
| `V15_DIALECT` | `P1511` | 切分未闭合且正文不含 NUL；或首记号属于 §6.2 第 4 步，包括 `DO`、`CALL`、`EXECUTE`、`COPY`、事务控制、`SET`、`RESET`。未闭合时结算恰好一条合成失败语句（§4.11、§6.1） | 语句失败 |
| `V15_DDL` | `P1512` | 首记号属于 §6.2 第 3 步或第 6 步，包括任何 `ALTER TABLE`；或 `v15_repl` 的 DDL 被 `v15_scratch_guard` 拒绝（§0.18、§6.4） | 语句失败 |
| `V15_IO_EXHAUSTED` | `P1513` | 下一 attempt 的 `n` 将超过有效 `max_io_attempts`（§0.21、§4.5.1、§10.1）。不插入该行 | 提交类，`fatal = false` |
| `V15_BUDGET_EXHAUSTED` | `P1514` | 预留的条件 `UPDATE` 影响 0 行，或结算后 `cost_used` 超过非空的 `cost_limit`（§0.21、§11.3）。尚未落地的 hook 效应不写 | 提交类，`fatal = true` |
| `V15_PRINT_AND_RETURN` | `P1515` | 同一迭代 `capture <> ''` 又执行 `jaz."return"` 或 `jaz."raise"`（§0.22、§5.3） | 语句失败 |
| `V15_PHASE_CONTRACT` | `P1516` | `contract` 不是 1，返回对象含未列出的键，`io` 的键集与 §9.1 不一致，或在列出了 `iteration` 的阶段里参数与 `io.iteration` 不一致（§0.28、§9.1） | 回滚类 |
| `V15_EXTERNAL_TOOL` | `P1517` | `tool_catalog.external = true` 时调用 `jaz.tool`（§0.29、§5.3） | 语句失败 |
| `V15_RECURSION_DISABLED` | `P1518` | `recursion_available = false` 时仍走规范 `bind_invoke`（§0.25、§4.7）。由 `v15_suspend_for_child` 抛出并经 §4.7 捕获 → 语句失败（提交 `failed` 行）；其余场合维持本列分类 | 语句失败 |
| `V15_RECURSION_EXCEEDED` | `P1519` | `depth >` 有效 `max_depth`。open 守卫或 `invoke/enter` 的 abort 都是提交类关闭（§0.25、§4.3、§10.1）。父语句另记 `V15_CHILD_ERROR` | 提交类，`fatal = false` |
| `V15_ITERATION_EXCEEDED` | `P1520` | `iteration >=` 有效迭代上限，在预留之前（§0.25、§4.5.1、§10.1） | 提交类，`fatal = false` |
| `V15_MANIFEST_DIGEST` | `P1521` | 由四行 baseline 重算的有效上限摘要不等于 `invokes.manifest_digest`（§8.5、§11.1）。这不是单例行摘要的比较 | 回滚类 |
| `V15_ROLE` | `P1522` | 转移时 `session_user` 不是 `v15_worker`，或 `jaz` 包装的 `current_user` 不是 `v15_repl`。definer 体不以此码断言 `current_user`（§0.20、§5.1） | 转移与 `EXECUTE` 拒绝为回滚类；包装在模型语句内抛出时为语句失败 |
| `V15_INVALID_TRANSITION` | `P1523` | 状态、租约、`p_owner`、`call_started`、span 开闭或阶段组合不满足该函数的前置；事务内 `55P03`；结算、退款或释放已有预留时影响 0 行，含差额下穿（§4.1、§11.3）。不含 `40001` 与 `40P01`。挂起不加栅栏，旧持有者再调用也是这个码，不是 `V15_STALE_FENCE` | 回滚类 |
| `V15_VALUE_INVALID` | `P1524` | 值不符合已写明的形状：租约、jsonb、名字、折叠键、pragma、`p_statements`、hook 消息 id 占用了 `seed:` 或 `iter:<n>:` 的冻结拼写，或持久 `add_messages` 的 id 已存在于 `llm_messages`（§5.2、§6.3、§8.1、§9.4、§9.6）。由 `v15_suspend_for_child` 抛出并经 §4.7 捕获 → 语句失败（提交 `failed` 行）；其余场合维持本列分类。base 的 `input_chars` 超过上限时是提交类中止（§4.5.1）。正文含 NUL 时，合成失败行存放替换后的文本，这个码是语句失败（§6.1） | 内核转移内为回滚类；模型语句与合成失败行为语句失败；`input_chars` 超限为提交类。由 `v15_suspend_for_child` 抛出并经 §4.7 捕获 → 语句失败 |
| `V15_HANDLER_FAILED` | `P1525` | `jaz.tool` 的目录函数抛出非 `V15_*` 异常（§5.3）。调用返回后 `current_user` 仍是 `v15_repl` | 语句失败 |
| `V15_STATEMENT_TIMEOUT` | `P1526` | worker 进程截止时间到达，或背书用的 `statement_timeout` 先到达（§4.6.2）。权威是进程截止时间 | 语句失败 |
| `V15_DELIVERY_CONFLICT` | `P1527` | 子终态送达时父不是等待这个子的 `suspended`；或子 `completed` 但 `bind_name` 已被非 `var` 占用（§4.8）；或 `bind_tool` 送达时同名已被 `input`/`scope`/`tool` 占用（§4.14）。后者不是 `V15_CHILD_ERROR` | 结构不符为回滚类；名字被占用为提交类 |
| `V15_CHILD_ERROR` | `P1528` | 子自身 `status = failed` 且 `fatal = false`。父语句用这个码，剩余父语句 `skipped`。子行保留自己的码（§0.11、§4.8） | 提交类 |
| `V15_RAISE` | `P1529` | `jaz."raise"` 写入 `invokes.error` 后，finish 把 invoke 收成 `failed`（§5.3、§4.9）。函数本身不抛这个码。父送达时子行保留它 | 提交类，`fatal = false` |
| `V15_DEPTH_SELF` | `P1530` | `kind = depth` 的层在组件列或 `extra_hooks` 里写入，或 partial 内再含 `depth_map`（§8.2） | 回滚类 |
| `V15_CONFIG_LOCAL` | `P1531` | local layer 的 `scope_id` 非空、`kind <> plain`，或子路径传入 local layer（§8.3） | 回滚类 |
| `V15_BASELINE_IMMUTABLE` | `P1532` | 层或 partial 含 `baseline_hooks`，或触发器拒绝删除、改写 baseline hook 行（§8.6、§11.1） | 回滚类 |
| `V15_BLACKBOARD_CONFLICT` | `P1533` | 同一 phase、同一黑板键的两份 `value` jsonb 不相等（§9.5） | 回滚类 |
| `V15_INPUT_CONFLICT` | `P1534` | 同一 phase、同一输入名的 add 不相等，或 add 与 drop 同时出现，或 add 撞上已有的非 `input` 名字（§9.5、§9.6） | 回滚类 |
| `V15_EFFECT_CONFLICT` | `P1535` | 同一消息 `id`、同一 `exec_result` 或同一 `budget` 的两份 jsonb 不相等（§9.5）。`raise` 压过 `continue` 不是这个码。多个 `raise` 取 `ordinal` 最小的那条也不是这个码。abort 码不一致不是这个码 | 回滚类 |
| `V15_HANDLER_DIGEST` | `P1536` | 调用前按 §3.11 重算的摘要（含规范化 `proacl`）与存放值不一致，或 owner、`provolatile`、`prosecdef`、语言、`proconfig` 不符，或 owner 重新获得了内核表权限（§9.2、§5.3） | 阶段调度为回滚类；`jaz.tool` 内为语句失败 |
| `V15_HANDLER_SHAPE` | `P1537` | 登记 hook 或 tool 时函数不是 STABLE 的 SQL/plpgsql、owner 或 `search_path` 或签名不符、owner 持有内核表权限，或 `PUBLIC` 仍有 `EXECUTE`，或 `EXECUTE` 不只在 `v15_owner`（§9.3） | 回滚类 |
| `V15_HOOK_ABORT` | `P1538` | 形状合法的 hook abort 所带的码不在 `{V15_IO_EXHAUSTED, V15_BUDGET_EXHAUSTED, V15_RECURSION_EXCEEDED, V15_ITERATION_EXCEEDED}` 内，或数个 abort 规范化之后的码仍不相同（§0.12、§9.5）。`fatal` 为 §9.5 归一后的或。不得用来包装预留名或未知键 | 提交类 |
| `V15_PROVIDER_REJECTED` | `P1539` | 适配器预检拒绝，或已开始的确定性 provider 拒绝（§4.5.5） | 提交类，`fatal = false` |
| `V15_VALIDATION_FAILED` | `P1540` | validation hook 在容忍次数耗尽后，将候选 return 改写为带 validation error 的 raise | 提交类，`fatal = false` |
| `V15_REPLAY_DIVERGED` | `P1541` | 锁定后 `logical_digest` 不一致。缺帧是 `P1542`；终局不一致由驱动投影比较 | 回滚类。非 invoke 终态码，不进入 §9.5 abort 可保留闭集 |
| `V15_REPLAY_MISSING` | `P1542` | 库已进入真实 LLM 尝试而 trace 无该坐标帧 | 回滚类。非 invoke 终态码，不进入 §9.5 abort 可保留闭集 |
| `V15_TOOL_BINDING` | `P1543` | `bind_tool` 的 catalog 行 `external = false`（§4.14）。同步 `jaz.tool` 对 `external = false` 仍走 handler，不用此码 | 语句失败 |
| `V15_TOOL_FAILED` | `P1544` | FakeTool / settle 的 `{"ok":false}`。不写 binding；非 fatal 收束 | 提交类，`fatal = false` |
| `V15_TOOL_EXHAUSTED` | `P1545` | 下一工具 attempt 的 `n` 将超过有效 `governance_io`。不插入该 attempt | 提交类，`fatal = false` |

`V15_PROVIDER_REJECTED`、`V15_VALIDATION_FAILED`、`V15_REPLAY_DIVERGED` 与 `V15_REPLAY_MISSING` 都不进入 hook abort 可保留闭集。hook 若把它们放进 `abort.error.code`，仍归一成 `V15_HOOK_ABORT`（§9.5）。未知名字仍是 `V15_INVALID_EFFECT`，不走这条归一。

`V15_CHILD_ERROR`、`V15_RAISE` 与作为提交结果的 `V15_HOOK_ABORT`，其 sqlstate 写进 jsonb，不要求该语句事务里有同名异常。gate 读 jsonb 的 `sqlstate` 字段。

## 14. 偏差台账

每一行都是相对 jaz 参考运行时的有意差别。实现不得把这些行修回参考运行时。

### 14.1 偏差

**V15-D01。** jaz 的一轮回复是 Python 片段。v15 的一轮回复是 PostgreSQL 语句列表，切分器是 `split_sql`（§6）。可观察后果：模型必须写 SQL；Python 缩进与 `import` 不会被执行。

**V15-D02。** jaz 的 `bind_invoke` 在同一次求值里阻塞到子树返回。v15 只在语句之间挂起，函数本身抛 `V15_INVOKE_FORM`（§0.8、§0.9）。可观察后果：子结果要靠下一条已生成语句里的 `jaz.var` 读取；一条语句内部看不到子结果。

**V15-D03。** jaz 向模型展示 `__history__`。v15 的关系是 `jaz.history`，祖先用 `jaz.prior_history(uuid)`，当次请求用 `jaz.request_messages`，提示词禁止 `__history__` 这个名字（§0.17、§6.5）。可观察后果：按属性访问历史的程序得不到那段关系；祖先历史要按 uuid 读取。

**V15-D04。** jaz 的 `return` / `raise` 是未加引号的语法。v15 的规范形式只有双引号 `jaz."return"` 与 `jaz."raise"`（§0.18）。可观察后果：未加引号的调用在执行前就是 `V15_INVOKE_FORM`。解析探针可以打印解析器的反应，但不得变成第二种规范拼写。

**V15-D05。** jaz 可以有异步工具与 `bind_name` 延续。v15 只有 `jaz.tool(name, args) returns jsonb`，在语句事务内同步结束。handler 是 `v15_tool_<name>` 拥有的 `SECURITY DEFINER` 纯函数，不写 scratch，调用时不 `SET ROLE`、不临时 `GRANT`。`external = true` 为 `V15_EXTERNAL_TOOL`（§0.29）。可观察后果：工具要么在本语句返回 jsonb，要么随保存点消失；没有工具挂起，也没有工具留下的 scratch 行。

**V15-D06。** jaz 的 `ainvoke` 与 `map_invoke` 可以在一轮里并发子调用。v15 一个 invoke 只有一个租约持有者，父在 `suspended` 时不可 claim（§0.10）。可观察后果：扫描结果里子先于重新 `runnable` 的父；不存在同一父迭代的两个 `running` 子语句。

**V15-D07。** jaz 用 Jinja 渲染提示。v15 的渲染器是 `render_prompt.py` 的纯函数，正文以 §6.5 的逐字段落为准。可观察后果：模板文件改动不会改变发给 FakeLLM 的 system 文本。最终 `logical_digest` 由 SQL 计算。消息 id 使用 §3.5 的冻结拼写。

**V15-D08。** jaz 的 hook 可以返回任意 Python 对象并直接改运行时。v15 的返回只解释为 §9.4 的闭集，预留名一律 `V15_INVALID_EFFECT`。不等的消息、`exec_result` 或 `budget` 回滚阶段。不等的 abort 码，或不在 §9.5 可保留闭集内的 abort 码，提交为 `V15_HOOK_ABORT`，不回滚，也不写 `payload.codes`（§9.5）。可观察后果：hook 不能替模型写出助手消息，也不能直接改 `invokes.return_value`。

**V15-D09。** jaz 可以在一次运行中途改配置。v15 在 open 时折叠进 `resolved_config` 后不再重折（§0.16）。可观察后果：open 之后 `UPDATE` profile，已打开 invoke 的 `config_digest` 不变；尚未出生的子 invoke 会看见新的 propagating 层。

**V15-D10。** jaz 参考实现的根深度从 0 起。v15 的根 `depth = 1`（§0.25、§3.1）。可观察后果：`max_depth = 1` 的根不能再委托；`depth = max` 关闭递归，`depth > max` 才是 `V15_RECURSION_EXCEEDED`。

**V15-D11。** jaz 的子调用沿用父的现场配置对象。v15 的子用父的 `config_scope_id` 按子深度重新折叠，不继承 `local_layer_id`，也不复制父的 `resolved_config`（§8.3）。可观察后果：父子的 `config_digest` 可以不同；父的 local 替换对子不可见。

**V15-D12。** jaz 可以把 hook 的可变状态交给子。v15 复制父 invoke 上已经冻结的 propagating 行的 `hook_def_id` 与 `config`，`state` 置为 `{}`，不复制 local 行，也不按子 open 当时的 `extra_hooks` 再装一份。`ordinal` 在子的 baseline 之后重新连续编号（§8.3）。可观察后果：父的 `budget_forcing:<ordinal>` 计数不会出现在子的 `hook_counters` 里。

**V15-D13。** jaz 在一次 Python 求值里的赋值，异常之后仍可能留在进程里。v15 一条语句一个保存点，失败则该语句的 binding 与 `capture` 消失，已提交的前序语句保留（§0.7、§5.5）。可观察后果：失败语句的 `jaz.assign` 在下一轮 `jaz.var` 里看不见。

**V15-D14。** jaz 把提供方失败当成异常再重试。v15 把每一次尝试写成 `llm_attempts` 行：未开始而过期是 `failed`，已开始而过期是 `unknown`，成功是 `settled`（§0.6、§12）。`v15_reclaim_expired()` 无参数，不插入 attempt，也不调用阶段函数；没有存活 `leased` attempt 的过期 invoke 租约在同一次调用里收回。可观察后果：迟到响应不能补写转录。`retry` 事件的 `new_attempt_id` 为 JSON `null`。新行只在之后的 `v15_begin_llm`。

**V15-D15。** jaz 的预算耗尽通常停在当前调用。v15 在池盖不住预留或金额超限时 `fatal = true`，同一事务中止该 invoke、祖先，以及这些行中仍非终态的后代（§0.11、§4.8）。预留失败时，本轮还没写下的 hook 效应不写。可观察后果：祖先不会停在 `suspended` 等待一个已经 `aborted` 的子。

**V15-D16。** jaz 的迭代与递归上限多来自可选配置。v15 强制恰好一行 `governance_manifest`，调用方只能收紧（§0.13）。可观察后果：没有清单行时 `v15_open_invoke` 抛 `V15_GOVERNANCE_MISSING`，不会先去租 LLM。invoke 上的摘要是有效上限，不是单例摘要的拷贝。

**V15-D17。** jaz 常以名字约定暴露工具。v15 要求 `kind = tool` 的 binding 与 `tool_grants` 行同时存在（§0.14）。可观察后果：只复制其中一项时 `jaz.tool` 抛 `V15_TOOL_UNAUTHORIZED`，invoke 不因此终态。

**V15-D18。** jaz 可以有独立的 span 对象。v15 的 span 只是 `invoke_events` 的行，没有 `programs`、`turns`、`spans`、`phases` 表（§0.24、§3.9）。可观察后果：轨迹查询就是按 `seq` 读事件。父在 `suspended` 期间 `repl_exec` 没有 `exit`。`outcome` 只用小写的 `completed`、`aborted`、`failed`。

**V15-D19。** jaz 的截断有时落在保存下来的观测上。v15 只截断送进 base 的观测文本；`llm_messages` 与 `repl_history.repl_output` 保存全文（§0.17、§6.5）。失败的 continue 里，这份全文是 capture 与 `[v15 exception …]` 块拼成的观测。可观察后果：`jaz.history` 的 `repl_output` 可以长于模型在下一轮 request 里看见的那一截。

**V15-D20。** jaz 的词法是 Python。v15 的词法是 §6.1：嵌套块注释、不按栈嵌套的 dollar-quote。`DO` 不是一条可执行语句，首记号 `DO` 在执行前失败 `V15_DIALECT`。`ALTER TABLE` 一律 `V15_DDL`，模型要改表就先 `DROP` 再 `CREATE`（§0.18、§6.2）。可观察后果：`DO $$ … $$;` 与 `ALTER TABLE` 都变成结算时的失败行，函数体与改表都不运行。`WITH RECURSIVE` 仍是一条可执行的 `plain`。

**V15-D21。** jaz 的 hook 可以替换模型响应或子调用结果。v15 拒绝 `supply_llm_response`、`supply_invoke_result`、`modify_invoke_result`、`supply_exec_result`、`modify_llm_response`（§9.4）。可观察后果：这些名字使阶段事务回滚，invoke 状态不变。非 baseline handler 抛出的异常才只留审计。

**V15-D22。** `jaz.history` 与 `jaz.request_messages` 的 `security_barrier` 阻止用户条件被推到视图之下。`EXPLAIN` 不是隔离边界：隔离 gate 必须再开一个 invoke 并断言行集，不得用 `EXPLAIN` 文本当证据（§3.15、§17）。可观察后果：能解释视图的角色仍可能看见视图定义；看不见另一个 invoke 的已提交历史行或请求行。

**V15-D23。** local 的 `recursion_limit` 允许作为收紧安装，但不复制给子（§10.2）。可观察后果：父在 `depth = local.max` 时不能再 `bind_invoke`。子不受父的 local 上限约束。

**V15-D24。** 实参求值不能把本事务改成 `READ ONLY`：`v15_prepare_statement` 已经写过控制行。v15 不引入 `V15_INVOKE_EXPR_WRITE`。求值只授予 scratch 的 `USAGE`，不授予 `CREATE`，也不做任何表级 `GRANT`。表的属主仍是 `v15_repl`，所以属主权挡不住写自己的表。背书是 `arg_sql` 的写记号、会写的 `jaz.*`，以及 `pg_stat_xact_user_tables` 上的写入，全部 `V15_INVOKE_FORM`（§4.7）。可观察后果：实参里的 `INSERT` 失败，并且没有子 invoke 行。

**V15-D25。** jaz 有完整的 Python 控制流。v15 的一轮是直线语句列表。跨 invoke 的递归只走 `bind_invoke`。一条语句内部的迭代只走 `WITH RECURSIVE`。`DO` 被拒绝，因为在 `session_user = v15_worker` 的连接里，顶层 `RESET ROLE` 会从 `v15_repl` 回到 worker（§0.18、§6.2）。可观察后果：模型写 `DO` 得到 `V15_DIALECT`。`DO` 若要重新进入语言，必须换成 `session_user` 本身无权的模型连接；那是后续版本。

**V15-D26。** jaz 允许 hook 在 exit 上 abort，从而改写已经决定的 outcome。v15 的 `invoke/exit`、`llm_query/exit` 与 `repl_exec/exit` 只允许 `blackboard_write`。outcome 行在调用阶段函数之前写入。exit 上的 abort 是 `V15_INVALID_EFFECT`，整笔回滚（§9.4）。可观察后果：exit hook 不能把 `completed` 改成 `failed`；它只能写下一次 phase 才看得见的黑板。

**V15-D27。** jaz 会发送 `temperature`。v15 的 DeepSeek allowlist 模型不上送 `temperature` / `top_p`（思考模式默认开启时供应商忽略或拒绝）。值仍留在 `resolved_config`。实现不得把它们补进线协议来「对齐 jaz」。

**V15-D28。** 供应商无幂等。unknown 之后的新 attempt 可能在供应商侧重复计费。`cost_used` 只含已 settle 的自算成本，可以低于发票，也可以因节假日按高峰估算而高于发票。`cost_used` 是估算值，`cost_limit` 是治理闸门，不是对账单。

**V15-D29。** `reasoning_content` 不是助手程序，不进 `llm_messages.content`。思考文本不得被拼进 `content`。审计只可带 `reasoning_chars`（整数），不带正文。

**V15-D30。** 高峰只按上海时区周一至周五的两个半开窗口 `[09:00, 12:00)` 与 `[14:00, 18:00)` 估算，不含法定节假日。假日若落在周一至周五，按高峰计价。方向是多报成本，不少报。实现不得为了贴近发票而补节假日日历。

**V15-D31。** jaz 的 ReturnType / ValidateReturn 用 Python 类型与异常对象，并在 InvokeComplete 再查一次。v15 用封闭 jsonb 类型规格与注册式 SQL handler，只在 `repl_exec/complete` 校验。可恢复拒绝是 return→continue 加持久消息；耗尽后是 return→raise / `P1540`。`P1540` 不是 abort 保留码。没有第二次谓词调用。validator 直接 `RAISE` 仍走异常隔离，不算校验拒绝。

**V15-D32。** spec 键名限制为 `^[A-Za-z_][A-Za-z0-9_]{0,62}$`，嵌套深度 ≤ 8。`jsonb` 的 `number` 不区分整数与浮点。enum 通过性按数值相等，展示按 `elem::text`。对象渲染的 required 按数组序，可选键按 UTF-8 字节序，项之间是 `, `。

D2 轨迹回放不启用 `supply_llm_response`，摘要复用 `logical_digest`。不另开偏差编号。

### 14.2 故意保留

下列行为是论文性质或本版合同的目标，不是偏差。gate 必须证明它们仍然成立：

- 父迭代的下一条已生成语句用 `jaz.var` 读到子结果，父为此不再次调用 LLM（§0.2、§4.8）。
- 模型能读到显式输入、scope、本 invoke 已结束的历史、按祖先 id 授予的祖先历史，以及当前迭代已结算 attempt 的冻结请求（`jaz.request_messages`，含 hook 消息）（§0.2、§5.4）。
- 尾委托就是 §6.5 的两句规范语句，中间没有另一次父 LLM。`recursion_available = false` 时，提示与 `context_window_warning` 都不写出 `bind_invoke`。
- 同一迭代既打印又 `return` 或 `raise`，得到 `V15_PRINT_AND_RETURN`，invoke 不因此终态（§0.22）。
- 四项治理上限始终存在，且只能收紧（§0.13）。
- scope 按值复制，`var` 与显式 input 不向子传播（§7.2）。
- `unknown` attempt 不是成功，迟到响应不进转录（§0.6）。
- 五个可选 hook 的可观察意图：更紧的迭代与递归、池预留、拒绝过早的 `return`、以及按 `recursion_available` 二选一的瞬态窗口警告（§10.2）。

## 15. Stage/Gate 计划

十三个 stage 按此顺序追加。合运行时是十三个 SQL 文件都加载之后（§0.0）。前缀库只用于该 stage 的 gate。`agent_v15_govern`、`agent_v15_provider` 与 `agent_v15_replay` 都是前缀。stage 1 之后可以增加函数、视图、授权、目录种子 DML，以及 §18 点名的 `CREATE OR REPLACE`。不得再增加表。**唯一例外：** stage 13 追加 `tool_requests` 与 `tool_attempts`（§3.16），表数 21→23。其后的 stage 仍不得加表。

| # | 目录 | SQL | gate | 证明 |
|---|---|---|---|---|
| 1 | `v15/schema` | `v15_schema.sql` | `test_schema.py` | §3 的 21 张表与本文的列、终态 CHECK、`invoke_events` 只追加、清单单例、`v15_on_phase` 桩、`v15_assert_manifest` 真检查、四个治理 handler 桩与 `hook_defs` |
| 2 | `v15/namespace` | `v15_namespace.sql` | `test_namespace.py` | §5 的 plpgsql `SECURITY INVOKER` 包装、`jaz.history` 与 `jaz.request_messages`、`V15_ROLE`、保留字、`jaz.history` 与 `jaz.request_messages` 在 `exec_context` 缺失时抛 `V15_INVALID_TRANSITION` |
| 3 | `v15/config` | `v15_config.sql` | `test_config.py` | §8 的折叠、列的 `IS NOT NULL` 与 partial 的 `jsonb_exists`、两枚清单摘要、`V15_DEPTH_SELF`、`V15_CONFIG_LOCAL`、`V15_BASELINE_IMMUTABLE`、子路径不收 local layer |
| 4 | `v15/protocol` | `v15_protocol.sql` | `test_protocol.py` | 只证明切分器、分类器与渲染器。五种规范形式、`DO` 为 `V15_DIALECT`、`ALTER TABLE` 为 `V15_DDL`、未闭合与 NUL 的**返回值**（替换后的文本与 `reject_code`）、§6.5 的冻结段落与截断。未加引号 `return` 的探针只打印到 gate 输出。本 stage 不得调用 `v15_settle_llm`，不得断言 attempt 或迭代状态 |
| 5 | `v15/repl` | `v15_repl.sql` | `test_repl.py` | §4.6 的单语句事务、worker 在函数外 `SET LOCAL search_path`、只授 schema 的 `USAGE`/`CREATE`、无表级 `GRANT`、`assign` / `print` / `tool`、引号形式的 `return` / `raise`、后继 `skipped`、`V15_PRINT_AND_RETURN`、`V15_EXTERNAL_TOOL`、`V15_HANDLER_FAILED`、工具不写 scratch 且不切换角色 |
| 6 | `v15/io` | `v15_io.sql` | `test_io.py` | §4.5、§4.10、§12。直接调用 claim、begin、mark、settle、`v15_reclaim_expired()` 与 `FakeLLM.complete`。不要求 `v15_finish_exec`，不要求 `run_until_quiescent`。回收不插入 attempt，并收回没有存活 attempt 的过期 invoke。切分失败的那条合成语句在这里结算：`failed` 行且 attempt `settled`。`pool_id` 为空。转移能解释 `abort`，桩仍返回 `proceed` |
| 7 | `v15/loop` | `v15_loop.sql` | `test_loop.py` | 单 invoke 循环。测试驱动 `run_until_quiescent`。空消息、散文，以及 stage 6 已结算的切分失败，在这里 continue。finish 的三分支、`return` / `raise` 跳过后继、§4.9 的 `repl_exec/exit` outcome、`v15_next_runnable`、丢失的 `NOTIFY`。不含子 invoke |
| 8 | `v15/tree` | `v15_tree.sql` | `test_tree.py` | §4.7 先写父的 bind-wait 再跑子 open。§4.8 的结构送达：子 `completed` 绑定、子 `failed` 时父语句 `V15_CHILD_ERROR`、名字冲突 `V15_DELIVERY_CONFLICT`。内核深度守卫的非 fatal 送达也在这里。子 `fatal = true` 的祖先展开只用 §9.6 的桩预留把子收成 `aborted`，不用 hook。断言终态 invoke 没有 `running` 语句（§4.8）。同迭代 `jaz.var`、父不再次 LLM、等待期间 `repl_exec` 不 `exit`。不含 hook 返回的 fatal，不含 hook 在 `invoke/enter` 上的 abort |
| 9 | `v15/govern` | `v15_govern.sql` | `test_govern.py` | 同一 oid 上的 dispatcher、预留先于效应、§9 的合成与代际、§10 的九个 handler、两套窗口警告、`budget_forcing:<ordinal>:<n>`、§11 的池与双摘要。hook 返回的 `fatal = true`，以及子在 `invoke/enter` 上因 hook abort 而在同一事务送达，只在本 stage 断言。回滚类冲突不留行 |
| 10 | `v15/provider` | `v15_provider.sql` | `test_provider.py` | 三转移、`P1539`、计价 fail-closed 的 SQL 形状、keyless、不执行模型 SQL 的冒烟辅助退出码。不加表。hook 带回 `V15_PROVIDER_REJECTED` 仍归一为 `V15_HOOK_ABORT` 并提交，不因 `P1506` 被拒 |
| 11 | `v15/return_hooks` | `v15_return_hooks.sql` | `test_return_hooks.py` | 十一文件前缀、`P1540`、计数 id 泛化、return→raise、raise 压过 continue，以及 cap 时 raise 取 ordinal 最小。不加表。ReturnType handler 与 effect builder 不在 M1 |
| 12 | `v15/replay` | `v15_replay.sql` | `test_replay.py` | 十二文件前缀、轨迹导出/重放、`P1541`/`P1542`、`supply_llm_response` 仍 `P1506`。不加表。摘要复用 `logical_digest` |
| 13 | `v15/tools` | `v15_tools.sql` | `test_tools.py` | 十三文件装载序、`tool_requests` 与 `tool_attempts`（不得加表的唯一例外）、`tool_wait`、`bind_tool`、`P1543`/`P1544`/`P1545`。Python `FakeTool` 零网络。合运行时库名 `agent_v15_tools` |

`v15/protocol/v15_protocol.sql` 只有注释，声明切分与渲染不在库内。加载它必须成功，且不得创建表。

`v15/load.py` 照 `v13/load.py` 的形状：`SQL_LOAD_ORDER` 是上表十三个文件，只许在末尾追加；`STAGE_THROUGH` 把目录名映到 `1..13`；`files_through` 取前缀；`load_stage` 按前缀执行，遇到 `ERROR` 或 `FATAL` 即失败。SQL 是普通 `CREATE`，不用 `IF NOT EXISTS`。角色语句不得放进这些文件。

gate 串行运行。每个 stage 的 `setup_db.py` 以集群超级用户执行，并且在加载任何 SQL 之前跑引导段：

1. `DROP DATABASE … WITH (FORCE)` 每一个 `starts_with(datname, 'agent_v15_')` 的库。
2. 终止仍然以 `v15_` 开头的角色连接着的后端。
3. 按依赖从叶子到根 `DROP ROLE`：每个现存的 `v15_tool_*` 与 `v15_hook_*`，然后 `v15_repl`，`v15_worker`，`v15_owner`，`v15_bootstrap`。
4. 按 §2 重新 `CREATE ROLE`。只 `GRANT v15_repl TO v15_worker`，`INHERIT FALSE, SET TRUE`。不把 `v15_repl` 授给 `v15_owner`。装载前创建 `NOLOGIN` 角色 `v15_hook_governance_iterations`、`v15_hook_governance_depth`、`v15_hook_governance_io`、`v15_hook_governance_statement`（stage 1 之前）。stage 9 在加载 `v15_govern.sql` 之前再创建五个可选 hook 的 `v15_hook_*` 角色，以及 `v15_hook_return_type`。会加载 govern SQL 的后续 stage 同样创建 `v15_hook_return_type`。测试自建 `v15_tool_<name>`。这些角色语句都在 `SQL_LOAD_ORDER` 之外。
5. `CREATE DATABASE agent_v15_<stage>`，再 `load_stage` 到该 stage。
6. 加载结束后 `ALTER ROLE v15_bootstrap NOLOGIN`。

`CREATE EVENT TRIGGER` 写在 `v15/schema/v15_schema.sql` 的末尾。函数是 `SECURITY INVOKER` 的 `v15_scratch_guard`。这一句只因为超级用户加载该文件而成功。加载器不是超级用户时必须失败，不得改成静默跳过。库名与 v8、v13 分开。

`v15/govern/setup_db.py` 先加载到 `tree`，记下 `v15_on_phase(uuid,integer,text,text,jsonb)` 的 oid，以及四个治理 handler 的 oid，再执行 `v15_govern.sql`。gate 断言这些 oid 都未变。从空库按完整 `SQL_LOAD_ORDER` 加载时，schema 里的 `CREATE FUNCTION` 与 govern 里的 `CREATE OR REPLACE` 也必须是同一个 oid。任何文件都不得 `DROP FUNCTION` 这些函数。五个可选 hook 只在 govern 文件里 `CREATE`，并插入 `hook_defs`。那是目录种子 DML，不是新表。

gate 命令是 `uv run python v15/<stage>/test_<stage>.py`，退出码 0 为通过。每个 stage 目录只有这一个 `test_*.py`。共享夹具放在 `v15/support.py`。gate 不得打开网络套接字（§0.0）。`smoke.py` 不是 gate。

worker 只有一份：`v15/worker.py` 的 `run_until_quiescent`。行为循环类 gate 的唯一 LLM 仍是 `v15/fake_llm.py`。`v15/provider/test_provider.py` 可以注入传输构造 `DeepSeekProvider`，零网络。默认传输只由 opt-in 驱动构造。worker 接受 `complete(logical_digest, n, request, llm_config=None)`。stage 7 起需要跑完整循环的测试调用 `run_until_quiescent`。stage 6 的测试导入 `FakeLLM.complete`，并自己调用 §4.2 的转移函数，包括无参数的 `v15_reclaim_expired()`。不得在 stage 目录里再写一个驱动。SQL 侧工具 handler 由该测试在库内创建，不进 `SQL_LOAD_ORDER`（§12）。Python `FakeTool` 在 `v15/fake_tool.py`，与 FakeLLM 并列，不进装载序，gate 不建 socket。

里程碑沿用 `AGENTS.md` 的阶段纪律：一个 stage 一次提交，该 stage 的 gate 为绿，不把两个 stage 捆在同一提交。三次里程碑提交还要带上矩阵与说明，且不得改写已绿 gate 的断言去凑实现：

- M1，stage 5：`docs/designs/v15-conformance.md` 覆盖 §0 与 §5、§6 中已有 gate 的条目；`v15/README.md` 写明如何跑到 repl。
- M2，stage 7：矩阵补上单 invoke 循环与 IO。
- M3，stage 9：矩阵覆盖 §0 的每一条、§13 的每一码、§14 的每一行，并写明完整 `SQL_LOAD_ORDER`。
- M4，stage 10：矩阵覆盖 `P1539` 与 D27–D30，并写明十条 `SQL_LOAD_ORDER`。旧 M1–M3 不重开。

矩阵的一行是：不变量或错误码、证明它的 `test_<stage>.py` 名字、断言的是行为而不是实现私名。矩阵不是第二份行为合同。行为以本文为准。

## 16. 非权威清单

下列材料不得用来推翻本文。与本文冲突时改实现或改 gate，不改行为去迁就它们。

- jaz Python 包里的 REPL 沙箱、异常类、`__history__` 属性，以及 `invoke.py` 里未被 §14 保留清单点名的控制流。
- Jinja 模板与 jaz 的模板文件。§6.5 已经逐字冻结的段落本身是权威，它们的上游模板不是。
- `jaz-evals` 的提示词、评分脚本与期望输出。
- `docs/designs/v8-dev.md` 的行为条款。该文件只提供文风。v8 的 `sessions`、`effect_requests` 与插件世代不是 v15 的表或状态。
- v13 的 stage 目录、`v13_advance`、`v13/govern/v13_govern.sql`，以及 v13 的角色名。
- OTel、Langfuse、Jaeger、Display、catalog 渲染。
- `map_invoke`、`ainvoke`、外部工具，以及以 `bind_name` 挂起的异步工具。
- 论文里与 §14 相冲突的实现草图。论文的两条性质仍是权威（§0.2）。
- 两轮 oracle、`docs/references/v15-oracle-review1.md`，以及未写进本文的 R-A、R-B 备选方案。R1–R5、K1–K6、R-A1–R-A29、R-B1–R-B19、R-C1–R-C18 、R-D1–R-D22 、R-E1–R-E10 、R-F1–R-F6 与 R-G1–R-G2 已经吸收。吸收之后的行为只以本文为准。
- `pg_jsonschema`。v15 不启用它，`arg_schema` 只保存不展开（§5.3）。
- `NOTIFY` 作为正确性机制（§0.23）。
- worker 进程内存、后端 GUC、临时表、预备语句（§0.3）。
- `EXPLAIN` 的输出，作为历史或请求隔离的证据（V15-D22）。
- `DO` 作为可执行方言，以及 `ALTER TABLE` 作为 scratch 里的合法 DDL（V15-D20、V15-D25）。
- 在 `SECURITY DEFINER` 函数体内 `SET ROLE` 或 `RESET ROLE`。PostgreSQL 拒绝它，本文也不把它当作实现手段（§0.20）。

## 17. PG 18.4 实现险点

每一条都有对应的 gate。探针失败时停在该 stage，不得用放宽断言的方式继续。

**词法。** stage 4 的夹具必须覆盖：嵌套块注释、字符串与 `E''` / `U&''` 里的分号、标识符引号里的分号、行注释里的分号、空语句消去、首尾空白去掉。dollar-quote 用不同标签时，中间的 `$b$` 不是边界。相同标签关闭字符串，不做栈嵌套。未闭合且不含 NUL：`split_sql` 不产生部分列表；分类结果是一条 `kind = plain`、`reject_code = V15_DIALECT` 的合成描述。stage 4 只断言这个返回值。stage 6 断言 `v15_settle_llm` 把它存成 `failed` 且 attempt 为 `settled`。stage 7 断言该迭代 `continue`。`WITH RECURSIVE` 仍是一条可执行的 `plain`。

**NUL。** PostgreSQL `text` 存不住 NUL。worker 在计算摘要之前把每个 NUL 换成六字符序列 `\u0000`。stage 4 断言合成描述的 `sql` 含这六个字面字符 `\`、`u`、`0`、`0`、`0`、`0`，且 `reject_code = V15_VALUE_INVALID`，不再另报未闭合。stage 6 断言该行已结算、attempt 为 `settled`。不得把这次 settle 打成回滚类。

**`return` 探针。** stage 4 在一份只作记录的连接里解析未加引号的 `SELECT jaz.return('null'::jsonb)`，把实际反应打印到 gate 的标准输出。不得把结果写入仓库文件。规范路径不读这份输出。分类器仍在执行前以 `V15_INVOKE_FORM` 拒绝未加引号形式（§0.18、V15-D04）。

**`DO` 与 `ALTER`。** 不设「`DO` 体内 `SET` 之后再补救」的 gate。`DO $$ BEGIN PERFORM 1; END $$;` 必须在分类时得到 `V15_DIALECT`，worker 不执行它。`ALTER TABLE` 必须得到 `V15_DDL`，包括只增加一列的形式。gate 同时断言一条只含 `WITH RECURSIVE` 的 `SELECT` 能在 scratch 里返回行，并且 scratch 里的 `DROP TABLE` 加 `CREATE TABLE` 能换掉一张表。

**`search_path` 与超时。** `v15_prepare_statement` 的返回值只有 `statement_fence`、`timeout_ms`、`kind`、`scratch_schema`。它不得调用 `set_config`，也不得 `SET ROLE`。worker 在函数返回之后、事务顶层、`SET LOCAL ROLE` 之前执行 `SET LOCAL search_path` 与 `SET LOCAL statement_timeout`（§4.6.2）。gate 断言模型语句看得见 scratch。进程内截止时间从 prepare 返回起算，长度是 `timeout_ms`。`statement_timeout` 设为 `timeout_ms + 1000` 毫秒。取消从第二条连接调用 `pg_cancel_backend`。被取消的连接丢弃，不复用。超时归一为 `V15_STATEMENT_TIMEOUT`；其余取消保留原生 sqlstate（§4.6.2）。gate 必须有一条长语句，证明截止时间仍把该语句收成 `V15_STATEMENT_TIMEOUT`。另断言 `TRUNCATE` 为 `V15_DIALECT`，且 `DROP` 的对象身份走 `sql_drop`。

**scratch 权限。** schema owner 是 `v15_owner`。已提交状态下 `v15_repl` 没有 `USAGE`，也没有 `CREATE`。prepare 对非 `bind_invoke` 授予 `USAGE, CREATE ON SCHEMA`，对 `bind_invoke` 只授予 `USAGE`，都无 `GRANT OPTION`。不得出现表级 `GRANT`。完成或失败路径 `REVOKE` 的也只是 schema 权限。事件触发器不得 `ALTER … OWNER`。模型对象的 owner 保持 `v15_repl`。不存在 `v15_owner` 对 `v15_repl` 的成员关系。

**级联删除。** 终态转移以 `v15_owner` 直接执行 `DROP SCHEMA … CASCADE`，函数体内没有 `SET ROLE`。stage 5 的探针：definer 创建 schema，事务顶层 `SET ROLE v15_repl` 创建一张表，`RESET ROLE`，再由 definer 执行 `DROP SCHEMA … CASCADE`。断言 schema 不存在。PostgreSQL 18.4 上，schema 属主做级联删除时不另查内部对象的属主；这个探针就是该事实的 gate。探针若失败，停止实现：常规路径不得改成在函数里 `SET ROLE`。唯一后备是 worker 在终态事务的顶层、任何函数之外执行 `SET LOCAL ROLE v15_repl`、`DROP SCHEMA … CASCADE`、`RESET ROLE`，并且必须先改 §0.26 再改代码。在探针通过之前，不得把后备写进 `v15_finish_exec` 或其他终态函数。

**事件触发器。** `v15_scratch_guard` 创建为 `SECURITY INVOKER`，`SET search_path = pg_catalog`。`current_user = v15_repl` 时才限制。schema 名只来自全限定 `v15.v15_current_scratch_schema()`。白名单只限该 schema 内的 `CREATE TABLE`、`CREATE TABLE AS`、`SELECT INTO`、`CREATE INDEX`（含 `UNIQUE`）、`CREATE VIEW`、`DROP TABLE`、`DROP INDEX`、`DROP VIEW`。没有 `TRUNCATE`，也没有 `ALTER TABLE`。`TRUNCATE` 由分类器以 `V15_DIALECT` 拒绝。`DROP` 的对象身份由 `sql_drop` 触发器与 `pg_event_trigger_dropped_objects()` 核对。`CREATE FUNCTION` 与 `ALTER TABLE` 抛 `V15_DDL`。gate 至少断言：scratch 里的 `CREATE TABLE` 成功且 owner 为 `v15_repl`；`public` 里的 `CREATE TABLE` 失败；`CREATE FUNCTION` 失败；`ALTER TABLE` 失败；已提交的权限表里没有把 scratch 表的 DML 授给 `v15_repl`。`v15_repl` 没有数据库的 `TEMP` 权限。§2 列出的 `pg_sleep`、`pg_read_file`、advisory lock、`dblink`（扩展存在时）从 `v15_repl` 调用失败。

**`exec_context`。** 它是按 `backend_pid` 存的普通行（§3.8）。`jaz` 包装调用的 definer 体用 `pg_backend_pid()` 读取。gate 断言：`v15_repl` 不能执行 `set_config`；删掉本后端的行之后 `jaz.var` 得到 `V15_INVALID_TRANSITION`。保存点回滚模型语句时，保存点之前写入的 `exec_context` 仍在。整个事务被取消时，这一行回到语句开始之前。

**`security_barrier`。** `jaz.history` 与 `jaz.request_messages` 都必须 `security_barrier = true` 且 `security_invoker = false`。隔离的证据是第二个 invoke 的 `SELECT` 行集为空，或 `jaz.prior_history` 抛 `V15_HISTORY_SCOPE`。不得用 `EXPLAIN` 文本当证据（V15-D22）。`v15_repl` 对基表没有 `SELECT`。视图不承诺排序；gate 的查询自己写 `ORDER BY`。

**`regprocedure`。** dispatcher 用 oid 解析出的 `quote_ident(namespace) || '.' || quote_ident(proname) || '($1::jsonb)'` 调用，不把 `regprocedure::text` 再拼 `($1)`（§9.2）。gate 在 `public` 放一个同名诱饵，断言跑的是 `hook_defs` 里那个 oid 的体。同一会话 `CREATE OR REPLACE` 之后 oid 不变。不更新 §3.11 的摘要则 `V15_HANDLER_DIGEST`。只 `GRANT` 或 `REVOKE`、不改 `prosrc`，也必须是 `V15_HANDLER_DIGEST`，因为摘要含规范化 `proacl`。owner 被重新授予一张内核表时，同样是 `V15_HANDLER_DIGEST`。更新摘要且权限仍符合登记合同之后，新体生效，且不需要新连接。

**工具。** handler 是 `v15_tool_<name>` 的 `SECURITY DEFINER`。已提交权限里 `PUBLIC` 与 `v15_repl` 都没有 `EXECUTE`。`v15.jaz_tool` 按 oid 调用，函数体内没有 `SET ROLE`，也没有临时 `GRANT`。gate 断言：调用期间 handler 里的 `current_user` 是 `v15_tool_<name>`；返回之后模型语句的 `current_user` 仍是 `v15_repl`，`session_user` 仍是 `v15_worker`；`v15_repl` 始终没有该函数的 `EXECUTE`；handler 写内核表或 scratch 的尝试失败；成功的工具只返回 jsonb。

**实参求值。** 不设立 `V15_INVOKE_EXPR_WRITE`，也不把事务改成 `READ ONLY`（V15-D24）。gate 断言：`arg_sql` 里的 `INSERT` 或 `jaz.assign` 失败，码为 `V15_INVOKE_FORM` 或 PostgreSQL 权限码；字符串、注释与 dollar-quote 之外、`(` 前标识符匹配 `nextval`/`setval`/`currval`（含 `pg_catalog.` 限定）为 `V15_INVOKE_FORM`；`invokes` 里没有子行；prepare 没有发出表级 `GRANT`。worker 对 `SELECT (<arg_sql>)` 的任何错误必须回到保存点并提交 `failed`，该语句不得留在 `pending`（§4.7）。

**`P15` 探针。** 设计时把 PostgreSQL 18.4 的 `src/backend/utils/errcodes.txt` 中已分配的 sqlstate 钉在仓库文件 `v15/errcodes-pinned.txt`，文件首行是 `postgres 18.4`。本修订的结论是：该类文件里没有 `P15` 前缀，因此 §13 使用 `P1501`–`P1542`。实现者在第一次让 gate 断言 sqlstate 之前，必须用官方 18.4 源码核对这份钉文件。若钉文件里出现任一 `P15` 码，就停止：先把 §13 整表重排到空闲前缀上，仍然连续、无空号、不超过 48 行，然后才允许断言 sqlstate。

运行时 gate 不读取服务器上的 `errcodes.txt`。它们断言 `server_version_num = 180004`，并且对 §13 的每一个码执行一次 `RAISE`，捕获到的 sqlstate 与表中相同。安装包里没有源码树时，这个运行时检查仍然够用。

**提交期错误。** gate 不得要求把 `40001` 或 `40P01` 改写成 `P1523`。worker 的分类只在 Python 里：这两种 sqlstate 导致整段重试，控制行保持该事务开始之前的样子。

**子事务。** 用 PL/pgSQL 的 `EXCEPTION` 子句，不用函数内 `SAVEPOINT` 语句（§9.2）。gate：非 baseline handler 故意 `RAISE`，阶段事务仍提交，审计行存在，黑板没有该 handler 的写入。baseline handler 故意 `RAISE`，转移回滚，码为 `V15_GOVERNANCE_FAULT`，审计行也不留下。非 baseline handler 正常返回未知键：整个阶段回滚，码为 `V15_PHASE_CONTRACT`。正常返回 `supply_llm_response`：整个阶段回滚，码为 `V15_INVALID_EFFECT`。`exit` 上正常返回 `abort`：同样是 `V15_INVALID_EFFECT`，outcome 行不留下。

**stage 边界。** stage 8 不得把 hook 的 `fatal = true` 或 hook 的 `invoke/enter` abort 当作自己的断言；那些行在 stage 9。stage 8 的 fatal 展开只走桩预留耗尽这条内核路径。stage 4 不得连接数据库去结算切分失败；那是 stage 6 与 stage 7 的事。

## 18. 冻结协议

本文是 v15 的行为合同。设计修订为 rev 11。K1–K6、R1–R5、R-A1–R-A29、R-B1–R-B19、R-C1–R-C18、R-D1–R-D22、R-E1–R-E10、R-F1–R-F6 与 R-G1–R-G2 只说明这些句子从哪次裁定吸收进来。裁定已全部吸收进本文，本文是唯一权威。`docs/references/v15-oracle-review1.md` 不得再改写已经写进 §0–§18 的句子。

实现、gate、矩阵三者与本文不一致时，改那三者。修订本文的提交必须同时带上受影响的 gate，以及受影响的 §14 行。gate 只许加严，或改到新句子所要求的断言。禁止把断言放宽到当前实现做得到的程度。发现本文无法在 PG 18.4 上实现时，先在同一提交里改本文、§14 与 gate，再改实现。禁止先落地违背本文的 SQL、事后补文档。级联删除探针若失败，按 §17 先改 §0.26，不得在函数体内补上 `SET ROLE`。

`v15_on_phase` 的函数体只允许出现在两处：`v15/schema/v15_schema.sql` 的桩 `CREATE FUNCTION`，与 `v15/govern/v15_govern.sql` 的 `CREATE OR REPLACE`。四个治理 handler 同样只在这两处出现：schema 里的桩，govern 里的 `CREATE OR REPLACE`。五个可选 hook 的 `CREATE` 与 `hook_defs` 插入只允许出现在 govern 文件。`return_type` 的 CREATE、ALTER/REVOKE/GRANT 与 `hook_defs` 插入同样只允许出现在 govern 文件。`validate_return*` 不在 govern 中预创建用户 handler。stage 11 的 `v15/return_hooks/v15_return_hooks.sql` 只放 helper，不得 CREATE 这些 handler，也不得 `CREATE OR REPLACE` `v15_on_phase`。不另设落地函数；效应落地在 `v15_on_phase` 内。改变落地顺序必须先改 §9.6。其他文件不得 `CREATE`、`REPLACE` 或 `DROP` 这些函数。签名变化视同未冻结，必须先改 §0.28 与 §9，并在同一提交里更新 oid 不变的证明。

任何 `SECURITY DEFINER` 函数的函数体都不得包含 `SET ROLE`、`RESET ROLE` 或 `SET SESSION AUTHORIZATION`。模型语句前后的角色切换只出现在 worker 事务的顶层。终态删除的常规路径是 schema 属主直接 `DROP SCHEMA … CASCADE`。

前缀加载是 gate 脚手架，不是交付运行时（§0.0）。`README` 与矩阵不得把 `agent_v15_loop`、`agent_v15_govern`、`agent_v15_provider`、`agent_v15_return_hooks` 或 `agent_v15_replay` 写成合运行时。合运行时只指十三个文件全部加载的库，库名 `agent_v15_tools`。`SQL_LOAD_ORDER` 只许在末尾追加。角色的删除与重建只在 `setup_db.py` 的引导段，不进入 `SQL_LOAD_ORDER`。会加载 govern SQL 的引导段必须创建 `v15_hook_return_type`。引导段必须先删掉每一个 `starts_with(datname, 'agent_v15_')` 的库，再重建角色（§15）。gate 串行运行。

stage 10 的 `v15/provider/v15_provider.sql` 只许 `CREATE OR REPLACE` 下面两只映射，签名与 oid 不变，不得 `DROP FUNCTION`：

- `v15_io_sqlstate(text)`：追加 `V15_PROVIDER_REJECTED` → `P1539`。旧码的返回值不变。本修订不把 `V15_VALIDATION_FAILED` 写入这张映射。
- `v15_govern_known_code(text)`：已知码白名单追加 `V15_PROVIDER_REJECTED` 与 `V15_VALIDATION_FAILED`。govern 原建体与 provider 替换体都要有 `V15_VALIDATION_FAILED`。provider 替换体必须是 govern 名单的超集，还要保留 `V15_PROVIDER_REJECTED`。

`V15_VALIDATION_FAILED` → `P1540` 只追加在 `v15_loop_sqlstate` 的 CASE。不替换 `v15_repl_sqlstate`。非 fatal 送达写死父码 `V15_CHILD_ERROR`，不查子码映射。这两只拒绝的 `fatal` 恒为 false，不走 fatal 展开的白名单。provider 文件不得 `CREATE`、`REPLACE` 或 `DROP` `v15_on_phase` 与四个治理 handler。

stage 12 的 `v15/replay/v15_replay.sql` 只许 `CREATE OR REPLACE` 下面两只映射，签名与 oid 不变，不得 `DROP FUNCTION`：以 provider 替换体为基线，追加 `V15_REPLAY_DIVERGED` → `P1541` 与 `V15_REPLAY_MISSING` → `P1542`。`v15_govern_known_code` 同步追加这两名。不把 `V15_VALIDATION_FAILED` 写入 `v15_io_sqlstate`。replay 文件不得 `CREATE`、`REPLACE` 或 `DROP` `v15_on_phase` 与四个治理 handler。

stage 13 的 `v15/tools/v15_tools.sql` 只许 `CREATE OR REPLACE` 下面映射，签名与 oid 不变，不得 `DROP FUNCTION`：以 replay 替换体为基线，追加 `V15_TOOL_BINDING` → `P1543`、`V15_TOOL_FAILED` → `P1544`、`V15_TOOL_EXHAUSTED` → `P1545`。`v15_govern_known_code` 同步追加这三名。`v15_replay_export` 在本文件替换：树含 `bind_tool` 或 `tool_wait` → `P1524`。tools 文件不得 `CREATE`、`REPLACE` 或 `DROP` `v15_on_phase` 与四个治理 handler。本 stage 是「其后不得加表」的唯一例外：追加 `tool_requests` 与 `tool_attempts`。

错误码只许从表尾追加，追加之后仍不得超过 `P1548`，且不得与已有行同义。本修订的最后一行是 `P1545`。`P1546`–`P1548` 空着，不得预占。§17 的钉文件若显示 `P15` 被占用，整表一起重排，禁止留下空号，也禁止 gate 在重排提交之前断言 sqlstate。

文档头的修订说明在行为修订时追加一行，不另起平行规格。本文件现在的修订号是 rev 11。


