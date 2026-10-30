# v20 CE facade 实验

这是可运行的对照实验，不是 v20 内核，也不是章程修订。四种设计都必须能跑同一条场景。不要选定胜者。

权威背景（只读，不要改）：

- `docs/designs/v20-runtime-charter-draft-2026-10-12.md`
- `docs/designs/v20-three-layer-implementation-reference-2026-10-13.md`
- `v13/ce_map/v13_ce_map.sql` 是反例：静态名字映射、多个写函数，不算协调

## 硬约束

- 不 runtime import v13，不调用 v13 SQL，不把本实验接进 `v8/load.py`。
- 不连接真实数据库，不打开网络，不调用真实模型。
- 唯一写入者是进程内的 `Control.execute`。事件只追加。幂等收据与 revision CAS 由这份 Control 执行。
- 模型调用与文件读写发生在事务外。事务打开时调用它们必须失败。
- `cleanup` 不删除事件。可以取消仍在跑的对象、写 purge 墓碑、丢掉导出文件内容。
- 四种设计各自一个模块，差异必须可从代码和场景报告里看出来。不要把四种设计收成一个带开关的类。

## 共享底

`substrate.py` 提供：

- runs、operations、events、artifacts、workflow_runs、workflow_steps
- `begin` / `commit` / `rollback`
- `execute(verb, payload)` 是唯一写入口
- 公共动词：start、poll、wait、steer、respond、cancel、spawn、handoff
- 内部动词：admit_turn、accept_turn_receipt、admit_tool、accept_tool_result、recover_owner
- artifact 以 digest 标识。下一步只能引用已提交的 digest

`scenario.py` 对每个 facade 跑同一序列，并写出结构化结果：

1. create_session，再 start 一条带初始消息的执行
2. 事务外伪造一次模型回合，用 accept_turn_receipt 提交，并登记一份计划 artifact
3. steer
4. 把执行推到 needs_input，再 respond
5. 再跑一步，下一步的输入必须引用上一步计划 artifact 的 digest
6. resume_session
7. get_log、extract_handoff、list_sessions
8. stop_session，然后 cleanup_sessions
9. 断言事件仍在；记录 resume 前后调用方看到的 session_id 与 run_id；记录哪些写发生在事务内

`run_experiment.py` 跑四种 facade，把报告写到同目录 `report.json`。
`test_experiment.py` 是独立脚本：`uv run python v20/experiments/ce_facades/test_experiment.py`，退出码 0 表示四种都跑完且事件未被 cleanup 删除。

## 四种设计

设计一，薄适配器。没有会话对象。调用方的 session_id 就是 run_id。resume 产生新 run_id，旧 id 只作 parent。create_session、resume_session、stop_session 分别是 start、带 resume_from 的 start、cancel 的别名。cleanup 由调用方编排，不进 kernel。交接靠调用方把 artifact ref 显式传给下一次 start 或 steer。

设计二，会话即 workflow 容器。session_id 是 workflow_run_id，其下有多个 run。start 是在容器内 spawn 子 run。子 run 已终态而容器仍活着时，steer 在同一事务里于容器内 spawn 新 run。交接落在 workflow step 已提交的 input/output artifact 引用上。

设计三，会话一等对象。增加 sessions 行和只能经 agent_manage 进入 Control 的内部动词 manage_create_session、manage_resume_session、manage_stop_session、manage_cleanup。session_id 跨 resume 稳定，current_run_id 更换。停止会话与 cancel 共用同一状态迁移。交接落在 session 的 artifact 链上。

设计四，可卸载 profile。kernel 只认识 run。调用方的 session_id 是外部 id，映射行与 start 或 retire 写在同一事务。resume 更换 run_id，外部 session_id 不变。写路径保持薄；get_log 与 extract_handoff 可以在读路径上折成会话形状。CE 没有对应 kernel 动词的操作显式拒绝。

## 状态

- 实现已落地。2026-10-13 重跑 `uv run python v20/experiments/ce_facades/test_experiment.py`，退出码 0。
- `report.json` 记录四种设计在 resume 身份、事务内写入、artifact 引用、cleanup 后事件保留上的差异。没有选定胜者。
- Oracle 对话 `untitled-chat-B42503` 的裁决是设计二 `workflow_container`。实验没有覆盖 poll/wait、并发 CAS、真实 Postgres 和跨多个 workflow 的宏观任务。

## 完成标准

- 上述文件存在，四种设计分文件实现。
- 测试脚本实跑通过。
- `report.json` 含四种设计在 resume、事务边界、artifact 引用、cleanup 后事件是否仍在这些字段上的差异。
- 不修改章程，不修改 v13，不提交 git。
