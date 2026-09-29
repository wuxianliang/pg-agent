# v13 plan_contract

Phase A 第一段。交付 A1 写者、A2 状态机与绑定载荷、A4 零 INSERT 前奏和提交入口。没有 advance 替换，没有 provider，没有驱动器循环。

超级用户夹具不是产品角色证明。本目录不证明产品库名、产品角色、stannum GRANT、PC-4。`steer/injected` 字面未关闭：水位谓词只有 `user/message`。把任何 steer 字面加进谓词之前必须先 `ASK_USER`。

## 种子帽

这些数字是 Phase A 种子，不是 LoopX 64/8/5，也不是 `spawn.sql` 的深度 64。本目录不执行读帽；后续 stage 不得静默改这些数。

| 种子 | 值 |
|---|---|
| inventory_scan_cap | 32 |
| inventory_return_cap | 32 |
| horizon_items | 4 |
| horizon_relations | 4 |
| horizon_gaps | 1 |
| item_text_cap | 1024 |
| 规划 provider 尝试 | 2 |
| 摘录字符帽 | 1024 |

## 本 stage 的选择

- `v13_plan_apply_id`：UTF-8 SHA-256 的前 16 字节。variant 是 RFC 4122（`10xxxxxx`）。version nibble 是 8。RFC 4122 没有 SHA-256 版本号；version 5 被定义为 SHA-1，这里不冒充。
- 空事件流没有最大 `seq`。`plan_commit` 的 `based_on_seq` 对不上，RAISE `waterline`。不发明 `-1` 哨兵。
- `explicit_version_binds_column` 用测试夹具冻结的 `default` version 99，证明入口把显式 version 交给 `v13_open_session`。version 2 的产品种子在 `real_chain`，不在本 SQL 里插入，避免和后续装载冲突。
- `v13_plan_current` 在本目录，因为水位失效是写者合同的折叠谓词。`plan_read` 消费它，不得再 `CREATE OR REPLACE`。
- 触发器只拒 `plan/committed` / `todo/delta` 的载荷闭集，文案 `v13: plan payload`。不改旧守卫。超级用户仍可用形状合法的裸 INSERT 绕过水位；这不是产品角色证明。
- 活跃 `should_run` 政策 version 仍是 3。写者不调用 `v13_should_run`，不调用 `v13_advance`，不调用 `clock_timestamp()` 或 `now()`。
