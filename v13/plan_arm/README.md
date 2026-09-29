# v13 plan_arm

Phase A 第三段。唯一一份 `CREATE OR REPLACE v13_advance`。它是 govern 里活体函数的副本，加上调用 `v13_plan_advance_prefix` 的一段。插入点在 spawn 块 `RETURN 'progressed'` 之后、`v13_harness_predecessor` 之前。不改 `:790-829`，不插入 T1.3 点名臂内部。

源函数正文 SHA-256（`v13/govern/v13_govern.sql` 里从 `CREATE OR REPLACE FUNCTION public.v13_advance` 到对应 `END $function$`）：

`515eea33d95079580648e61651aeaae61b20252ee2a4f0eb34a10a31680d2911`

超级用户夹具不是产品角色证明。本目录不证明产品库名、产品角色、stannum、PC-4，也不证明 material 已扣。`should_run` 政策 version 仍是 3。不调用 `v13_child_pointer`。不替换 `v13_recover_idle` 或指纹函数。

## 臂

- 子会话：结算与派发跳过，零 plan/todo。恰好一条 `workflow/pointer` 且还没有任何 `read_file_py` effect 时，`should_run` 为真才建 `tool` effect。不写 `tool/call`。
- 根、未 stopped：先核对子 `read_file_py` 摘录，命中则经写者 `runnable→done` 并返回 `waiting`，零新 effect。
- harness `progress|finish` 且绑定的 advancement 仍是 `runnable`：写归档后落入活体收据臂，同一事务。`wait`/`reject` 不写。monitor 不猜 due，不归档成 `done`。
- `failed|cancelled` 且仍 `runnable`：一条隔离 `update`，`status_to=blocked`。
- 门为真且 `should_run` 为真才派发。`provider` 的 kind 是活体模型回合的 `llm`。`operator` 是 `human`。`none` 不建 effect。首次绑定是 `status_from=status_to` 的载荷更新。
- stopped：本调用新增 plan/todo 为 0，活体 finish 仍可写收据。
