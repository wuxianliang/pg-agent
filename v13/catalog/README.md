# v13 stage 22 — catalog（D14）

换体 `v13_tools_catalog_frozen`：只改 VOLATILE 分支。解析仍按 proname 计全库 `pg_proc`，歧义文案逐字节留在活体底稿。`proconfig` 保持 NULL（形态 H）。不改 `v13_spawn_writer_ok` / `v13_named_sql_writer` 函数体，不动 tools 行。

## 换体公式

步骤 0–4 只在已取得唯一 `v_oid` 且 `provolatile='v'` 之后：

0. 裸名形状：`strpos(v_handler,'.')=0` 且与 `proname(v_oid)` 逐字节相等。否则原 RAISE，不调谓词。
1. `v_oid` 仍是换体前的全库唯一解析。
2. 断言 A：`to_regprocedure(v_qual) IS NOT DISTINCT FROM v_oid` 且 `public.v13_named_sql_writer(v_handler) IS NOT NULL`。`v_qual` 不进谓词。
3. 断言 B′：`v_arglist := substring(v_oid::regprocedure::text FROM '\(.*\)$')`，`to_regprocedure(v_handler || v_arglist) IS NOT DISTINCT FROM v_oid`。只用规范式 `(uuid,jsonb)`。
4. `public.v13_spawn_writer_ok(v_handler) IS TRUE`。

豁免 = 0∧2∧3∧4。原 RAISE 子串 `is VOLATILE` 不变。比对一律 `IS NOT DISTINCT FROM`。

活体 `v13_spawn_writer_ok` 体内裸调 `v13_named_sql_writer`。会话投毒下，限定直调真实 writer_ok 仍可因影子 named 为 false（否决型影子 → 真行 `is VOLATILE`，接受的 fail-closed 可用性损失，不是假豁免）。catalog 两处顶层谓词调用按 P8c 限定到 `public` 真实 OID；限定不递归固定谓词体内解析。臂 D 只锁该 fail-closed。逐调用点身份由源码/OID 硬断言证明，放行方向由臂 E 保证。

## 第四务

假 worker 只调 claim / renew / `v13_cancel_pending` / `v13_interruptible` / complete。分派键是 `v13_interruptible(tool_name)`。命中后零后续 provider IO。`replay`/`stale` 立即退出。谓词查询失败 fail-closed。跟踪只在 Python 内存。SQL 无 LISTEN、无 `pg_terminate_backend`、无第四务判定函数、无永久跟踪表。

## 验收

| 格 | 状态 |
|---|---|
| fake gate `uv run python v13/catalog/test_catalog.py` | ✅ 退出码 0 |
| 真实 worker 接线 | 🟡 环境级验证（gitignored 实跑通过，非 R4 关闭） |

Phase A 不声明「R4 真 worker 第四务已完成」。

## sql 快路

活体 `v13_advance` 仍有两处 `RAISE 'v13: spawn batch-dispatched'`。stage 20 `v13_triage_after_route` 在 direct 分类下先把 `sql/spawn_subsession` 改写成 `human/triage_direct`，所以该 RAISE 在这条可达路径上不触发；advance 不产子。扇出臂仍是产子路径。

2026-09-27：`demo_v13/test_demo_smoke.py --real-provider-smoke` 退出码 0。冒烟库装到 catalog，`demo_create_session` 走 `v13_open_session`；direct override 避开无带 triage，parse 后 freshen 再 advance。补丁在 gitignored `demo_v13/`，不进本 commit 的代码面。
