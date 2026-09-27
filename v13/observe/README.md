# v13 stage 24 — observe

两个 STABLE INVOKER 读面。亲缘只活在 `v13_control_authorized`。拒绝是零行，不 RAISE。不建表、不建 waiter。

## 列契约

`v13_observe(p_actor uuid, p_ids uuid[])` 返回序固定：

`ordinal, session_id, parent_session_id, status, spawn_kind, is_terminal, turn_no, last_event_seq, last_event_type, pending_human, cancel_pending`

- `ordinal` 从 1 起，输出序 = 输入序。
- `is_terminal` := `status IN ('completed','failed','cancelled')`，闭集从活体 `v_goal_tree` 抄。
- 无事件时 `last_event_seq = -1`，`last_event_type` 为 NULL。
- `pending_human` 直接调用 `v13_pending_human(uuid)`（探针：返回 boolean）。
- `cancel_pending` 调用 advance 源码里的 `v13_unconsumed_cancel(uuid)`（探针：advance 只引用这个名字，不引用 `v13_cancel_pending`；返回 boolean）。

`v13_session_log(p_actor uuid, p_sid uuid, p_after_seq bigint DEFAULT NULL)` 返回：

`seq, event_id, type, turn_no, payload, payload_hash, source_effect_id, at`

seq 升序。不 join `effects`。NULL 与 −1 从头（事件 seq 恒 ≥ 0）。`p_after_seq < -1` 在谓词之前 RAISE `v13: session log cursor`。

## 控制流

`v13_observe` 是 plpgsql 多段，不是一条带 join 的 SQL 函数：

1. 参数段。NULL 数组或空数组 → 零行。NULL 元素 → `v13: observe id`。重复 → `v13: observe duplicate`。这两句在授权前，文案不含会话存在性。
2. 授权段。按输入序逐 id 调谓词。任一假 → 整批零行，不 RAISE。此段不查 `events`，不读 `parent_session_id`。
3. 快照段。才读 `sessions`（含 `parent_session_id` / `spawn_kind` 作为已授权行的输出列）和事件末 seq/type，并调两个布尔适配。适配若对已授权会话 RAISE，错误原样传播；它们不出现在授权循环里。

任一 id 未授权则整批隐藏。后续对已授权单 id 的调用仍返回一行：零行是隐藏，不是不可观察。

## 无 waiter，驱动器重入

没有 `pg_sleep`，没有 `LISTEN`，没有数组长度上限。这是 poll，不是队列。

「第一个 interesting 胜」由驱动器在返回行上选（看 status / pending / terminal / watermark），再重入。并发新事件可能到下一次调用才可见：STABLE 单调用是一份快照。观察返回真值只表示可以再读，不是已经允许 cancel。

## GRANT

`REVOKE EXECUTE FROM PUBLIC` 后只授 `v13_route`。`v13_route_login` 经 INHERIT 成员获得。不授 `v13_recall`、`v13_worker`、`v13_resolve`、`v13_spawn_owner`。recall 今天仍有 `events` 的表级 SELECT，本 stage 不收回，也不宣称该表级权限已被谓词封死。

函数只吃参数，不读会话变量。

## Gate

`uv run python v13/observe/test_observe.py`（退出码 0）。2026-09-27 实跑 147 checks。回归 stage 1–24 串行 25 脚本全绿。
