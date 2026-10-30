# v20 CE facade 第二轮实验

第一轮在 `v20/experiments/ce_facades/`，保持不动。本目录是第二轮。不要选定胜者，不要改章程、v13、v23，不要提交 git。

第一轮 Oracle 对话 `untitled-chat-B42503` 选了设计二。它指出另外三个的缺口，并指出六项还没被实验证明：poll/wait、并发 CAS、recover_owner、真实 PostgreSQL、跨多个 workflow 的宏观任务、WorkspaceContext 的真实文件导出。

## 硬约束

- 不 import v13，不执行 v13 SQL，不把本实验接进 `v8/load.py`。
- 持久化必须是本机 PostgreSQL。连接用仓库根 `server.get_server().get_uri` 的 Unix socket。库名只用 `agent_v20_ce_facades_r2`。测试开始时 DROP/CREATE 这个库。不要动其他库。
- 唯一写入口仍是 `Control.execute`。事件只追加。幂等收据和 revision CAS 落在表里。
- 模型调用和文件读写在事务外。事务打开时做这两件事必须失败。
- `cleanup` 不删除事件行。可以追加 purge 墓碑，并删掉导出文件的字节。
- 四种设计分文件。差异要出现在 `report.json`。
- 不调用真实模型，不打开外网。

## 四种设计都跑同一条场景

设计二保持第一轮的身份模型：`session_id` 是 workflow run id。终态子 run 上的 resume 在同一事务里 spawn 新 run 并写 step。宏观任务是新增的一行，引用多个 `workflow_run_id`。

设计一的修复：稳定身份是已提交的 `session_aliases` 行，resume 在同一事务里更换 `current_run_id`。引用从 `artifacts` 表读出。宏观任务仍使用 workflow，但调用方的 session id 不是 workflow id。

设计三的修复：`sessions` 只有 `session_id`、`workflow_run_id`、`status`。revision 和步骤输入输出在 workflow 上。`get_log` 按 `events.session_id` 读取，该列有索引。

设计四的修复：`external_ids` 与 run 写在同一事务。cleanup 把映射标成 purged 并追加墓碑，不再拒绝 cleanup。`get_log` 仍在读路径折叠，折叠来源是 `external_runs`。

## 六项覆盖，四种设计都要跑通

1. poll/wait。短读后提交，事务关闭后再 LISTEN 或有界轮询，然后重读快照。通知载荷只有 run_id 和 revision。等待期间连接上不能有打开的事务。报告记下通知或轮询哪条路径观察到了新 revision。
2. 并发 CAS。两个连接读到同一 revision，同时 steer，或一个 steer 一个 respond。恰好一个提交。失败者返回 revision 冲突。报告记下胜负和失败连接的错误。
3. recover_owner。owner fence 写在 run 上。原 owner 的连接在未完成写入时断开。另一连接 `recover_owner` 推进 fence。旧 fence 的后续写入失败。新 owner 的 steer 可以提交。
4. 真实 PostgreSQL。上述结果用第二条连接 SELECT 读回。进程内字典不算数。
5. 宏观任务。一个 macro 行下至少两个 workflow。第二个 workflow 的步骤引用第一个 workflow 已提交的 artifact digest。
6. WorkspaceContext 真实导出。事务外把导出写到本目录 `exports/` 的真实文件。提交的 artifact 带路径和 digest。下一步打开该文件，重算 digest，必须与已提交 digest 一致。cleanup 去掉文件字节，digest 记录仍在。

第一轮场景也要保留在设计二上：create、start、计划 artifact、steer、needs_input、respond、resume、get_log、extract_handoff、list_sessions、stop、cleanup，以及 resume 前后的 session_id 和 run_id。

## 状态

- 2026-10-13：`uv run python v20/experiments/ce_facades_r2/test_experiment.py` 退出码 0。
- 库名 `agent_v20_ce_facades_r2`。四种设计的 poll/wait、并发 CAS、recover_owner、第二条连接读回、两个 workflow 的宏观任务、真实导出文件，都记在 `report.json`。
- Oracle 对话 `untitled-chat-6DA9B6` 选定设计三 `session_object`。要吸收的是设计二的 resume 承接 refs、终态 steer 自动 spawn，设计一的 cite 前核对已提交 digest，以及设计四的 list 只列活跃会话。不要吸收读路径折叠、alias 层、external_runs，也不要把 session id 改回 workflow id。
