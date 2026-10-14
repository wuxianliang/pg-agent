# v20 alpha

纵向循环的一个里程碑：一次 `start`，一轮进程内 `echo`，然后 `completed`。不接真实模型，不开出站网络。

权威是 `docs/designs/v20-ce-native-design-5-2026-10-13.md` 的对象、动词和字段。本目录按 `docs/plans/v20-alpha-2026-10-14.md` 实现。章程管原则和里程碑边界。三层参考不是合同。`v20/experiments/` 不是完成标准。

## 怎么跑

仓库根：

```bash
uv run python v20/alpha/test_alpha.py
```

退出码 0 即通过。脚本先 DROP/CREATE 数据库 `agent_v20_alpha`，再在同一进程里跑第 11 节的全部探针。2026-10-14 这次实现的结果是 **62/62**，退出码 0。

库只走本机 Unix socket。`local_dsn` 在 host 不以 `/` 开头时直接失败。

## 角色

- 管理员连接（`user=None`）负责 DROP/CREATE 和装 `schema.sql`。
- `v20_alpha_control`：LOGIN、INHERIT，表上 SELECT/INSERT/UPDATE，没有 DELETE，并有 `pg_read_all_stats`。动词探针用这个角色。
- `v20_alpha_worker`：NOLOGIN，没有 CONNECT。它不执行工具。工具是进程内的 `echo`。

## 循环

唯一写入入口是 `Control.execute(verb, actor, payload)`。`Host.drive(verb, actor, payload)` 在本进程里只允许一个线程。它先做 `start` / `steer` / `respond` / `claim_resume`，再在事务外 `resolve_handle`，然后才 `admit_turn`。FakeWorker 和 `echo` 都在事务外跑。`decide` 只读已提交快照，不决定下一笔 `admit_turn`。

`poll` 不写。`wait` 先 `LISTEN v20_alpha_run_changed` 并提交，再读权威 revision。通知载荷只有 `run_id|revision`。

默认列表没有动词。gate 直接查：

```sql
SELECT session_id FROM v20_sessions WHERE NOT list_hidden
```

## 不做什么

不改 `v8/load.py`，不 import v13，不建 workflow、plan、artifact、span、token 表。不跑真实 `read_file`，不跑真实 provider，不把 `v20_runs` 收成 v23 那种单表。偏差见 `docs/reviews/v20-deviation-ledger-2026-10-14.md`。探针对照见 `docs/reviews/v20-conformance-matrix-2026-10-14.md`。
