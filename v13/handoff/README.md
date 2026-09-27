# v13 stage 25 — handoff

不可变追加收据。不是可翻转的当前态，不建读面函数，不产 XML，不 fork。

## 信封

`control/handoff` 载荷恰四键：

| 键 | 取值 |
|---|---|
| `schema_version` | JSON 整数 1 |
| `delivery_id` | 本次 `gen_random_uuid()` 小写文本，不是 effect id，不由 hash 派生 |
| `transcript_hash` | `v13_transcript_hash(sid, up_to_seq)` 的 64 位小写 hex |
| `up_to_seq` | JSON 整数 ≥ 0，且等于本会话某条非 handoff 事件的 seq |

写入用 `to_jsonb(seq)`，使 `payload->>'up_to_seq'` 与 `seq::text` 逐字相等。`source_effect_id` 必须为 NULL。

## 前缀窗口

材料是 `seq <= up_to_seq AND type <> 'control/handoff'` 的全部事件，规范字节式是 `['v1', sid, up_to_seq, [[seq, type, payload_hash, source_effect_id]]]`。收据自身排除，防自激。

四键没有 `from_seq`。窗口必须是整段前缀，不是源合同的「最近 N 条」。空会话 NULL cutoff → `v13: handoff empty` 零写；显式 0、负数、缺口、指向收据、大于 max → `v13: handoff watermark` 零写。两句不得互换。

## 政策

`handoff_policy` 只消费 `enabled`。键集恰 `{schema_version, enabled}`，`schema_version` 为 JSON 整数 1，`enabled` 为布尔。缺行、零 active、多键、类型错 → `v13: handoff policy`。`enabled=false` → `v13: handoff disabled`。不借道 `v13_policy()`。

同身份回读先于策略：禁用或畸形时，已有收据仍返回原 payload，零新事件。策略只挡新写入。`v13_handoff_emit` 体内用同一套规则，所以 route 直调也过不了禁用。

## 写口

`v13_handoff_emit` 是 SECURITY DEFINER，属主 `v13_handoff_owner`（NOLOGIN，无成员）。守卫是 INVOKER。检查序：writer → source → keys → schema → delivery → digest → watermark → hash。

| 失败 | 文案 |
|---|---|
| 非属主插入 | `v13: handoff writer` |
| `source_effect_id` 非空 | `v13: handoff source` |
| 键集不是恰四键 | `v13: handoff keys` |
| `schema_version` 不是 JSON 整数 1 | `v13: handoff schema` |
| `delivery_id` 非 canonical uuid | `v13: handoff delivery` |
| hash 非 64 位小写 hex | `v13: handoff digest` |
| `up_to_seq` 非 canonical 非负整数，或没有对应非 handoff seq | `v13: handoff watermark` |
| hash 与前缀重算不等 | `v13: handoff hash` |

`up_to_seq` 在存储后的 jsonb 文本上判：numeric → trunc → `0 ≤ n ≤ 2^63−1` → 文本等于 `bigint::text`。`1.0` 与 `1.5` 都拒。溢出不泄 `22003`。

身份 = `(session_id, up_to_seq, transcript_hash)`。同身份重放返回原 payload。恰两个部分唯一索引：`ux_events_handoff_delivery`、`ux_events_handoff_snapshot`。extract 与 emit 体内无 EXCEPTION，不用异常把 `23505` 收成旧收据。

## route→emit

`v13_handoff_emit` / `v13_transcript_hash` 是受信 route 内部 helper，不是 actor 入口。D7 只承诺 `v13_extract_handoff`。route 直调的行为已定义：新身份成功落收据；同身份撞快照索引，裸 `23505`；`enabled=false` → `v13: handoff disabled`。不授 worker / recall / resolve / spawn_owner。

守卫也授给 route，否则 route 直插 `control/handoff` 停在 42501，到不了 `v13: handoff writer`。

## 与 fork 的边界

extract 不改 `sessions.status` / `turn_no`，不 INSERT 子会话，不写父会话，不写 artifacts，不调 fork。终态会话可以交接。`blocked_unknown` 墙不改；属主 emit 在墙已成立的会话上可以提交（点火不等于改值）。

`v13_json_int_ok` 活体第二参是 `numeric` 不是 `int`，GRANT 用活体签名。`schema CREATE` 授给属主，供 `ALTER OWNER` 与运行期保留。

## Gate

`uv run python v13/handoff/test_handoff.py` 退出码 0。必含一条 `SET ROLE v13_route` 后真正 COMMIT 的 extract。材料期望值按规范字节式自行 digest，不调用 helper 自证。

Phase B 六动词在同一脚本末尾以 `v13_route` 走通：observe、session_log、user/message 注入、6 参 complete、2 参 cancel、authorized、extract。合同已证明。仓库内驱动器未交付。
