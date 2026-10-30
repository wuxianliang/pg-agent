# v20 alpha 偏差台账

日期：2026-10-14。gate：`uv run python v20/alpha/test_alpha.py`，仓库根，退出码 0，62/62。本文件只覆盖计划第 12 节。不把这些条写成已经回到章程或设计五的全文。

| id | 偏离 | 为什么 | alpha 的替代 | 再看 |
|---|---|---|---|---|
| D1 | 不追加 `v8/load.py` 的 `SQL_LOAD_ORDER`，运行时不 import v13 | 章程决策 1（`:1192`）把 v20 从 v8 累计装载和 v13 运行时里分开。这个里程碑不回并 | 自有 `v20/alpha/schema.sql`，由 `setup_db.py` 装进 `agent_v20_alpha` | 不回并 |
| D2 | 章程 M3 的 WorkspaceContext 和多平面读工具不在本切片 | 纵向循环先接 v13 已经验证的单根 Python 读，不接调查面 | Host 上的 `read_file`，围栏和换行切分跟 `v13/read_tools/read_contract.py`，不 import v13。`echo` 仍在。没有 workspace root 时读失败，失败仍走 `accept_tool_result` | M3 的 WorkspaceContext、Swift、Node、Duck |
| D3 | 章程 §4.3 的 workflow 表和 artifacts 表不建 | 设计五第 3 刀。没有导出就没有受保护引用，纵向循环不依赖它们 | 不建这些表。带 `input_artifact_digest` 的载荷在开事务前 `Rejected`。`input_retained` 由 CHECK 恒为 false | 设计五第 3 刀，约章程 M4/M7 |
| D4 | 设计五的 span、token usage、codex 句柄语义没有行为 | gate 不调模型。可选的真实调用不记用量 | span 表不建，不记 token。`drive.py` 在 `V20_MODE=real` 且 `V20_REAL_PROVIDER_AUTHORIZATION=1` 时才开口；缺 key 打印 `credentials_absent`、退出码 2、不调用 complete。密钥不进请求体，也不进库 | 章程 M7 的 authorized provider tier |
| D5 | Worker ABI 名称没有冻结为 `v20-worker-1` | 章程 §14.5（`:1210`）还没关闭这个名字 | 暂用 `WorkerRequest` / `TurnReceipt`。`input_kind`、`provider_handle`、`tool_results` 进入同一份 input digest | 章程 §14.5 关闭时 |
| D6 | 章程 §14.1 的「每库一个 runtime owner」没有做成库级租约 | 本切片没有宏观调度。设计五的 fence 落在 run 上 | 每个 run 一个 `owner_backend_pid`，值是控制连接的 `pg_backend_pid()` | 宏观调度，章程 M7 |
| D7 | 设计五 §7 的全量探针不在本 gate | 计划把完成标准收成第 11 节。实验探针不是 alpha 的合同 | 只跑 `v20/alpha/test_alpha.py` 里的 62 个探针。不 import `v20/experiments/` | 不把实验探针搬进 alpha。宏观探针留在后续里程碑 |
| D8 | fence 用的是后端 pid，不是操作系统进程 | `pg_stat_activity` 只能看见这条连接。实现按这个可见性判定死活 | owner 连接已经关闭、进程仍持有另一条连接时，`recover_owner` 可以把 run 写成 `expired` | 若出现多连接 Host，再改判定 |
| D9 | 设计五 `:330` 的 AlreadyActive 要「run 仍在跑」和「pid 仍活」同时成立 | 两个条件拆开才不会在死连接上直接开新 epoch | pid 已死但 run 仍是 `running` 或 `waiting_for_input` 时，`claim_resume` 为 `Rejected`，不写新 epoch。先 `recover_owner` | 若以后允许跳过 recover，再改这一条 |
