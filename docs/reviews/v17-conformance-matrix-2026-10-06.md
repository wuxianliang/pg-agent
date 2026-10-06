# v17 覆盖矩阵 — SBCL worker

日期：2026-10-06。对象：`docs/plans/v17-sbcl-worker-plan-2026-10-06.md`。
本表只记录计划要求 → gate 实际断言的映射；实现偏差进偏差台账。

## Stage / Gate 实跑记录

| Gate | 命令 | 结果 |
|---|---|---|
| G1 store | `uv run python v17/store/test_store.py` | exit 0（2026-10-06） |
| G2 world | `uv run python v17/world/test_world.py` | exit 0（2026-10-06） |
| G3 queue | `uv run python v17/queue/test_queue.py` | exit 0（2026-10-06） |
| G4–G6 | — | 未开工（计划 §5，placeholder） |

## 计划 §5 G1 store

| 计划断言 | gate 覆盖 | 位置 |
|---|---|---|
| DDL（4 表、约束） | ✅ 表存在 + append-only trigger + sbcl_version 缺省拒绝 | `v17/store/test_store.py` ddl 段 |
| publish/load/list/rollback | ✅ Python 断言 + fiveam store 套件（子进程） | `v17/store/test_store.py`、`v17/lisp/tests/store-suite.lisp` |
| 祖先链腐坏检测（seq 断号 / parent 断链 / 环） | ✅ 三类被人为制造各断言 RAISE | `v17/store/test_store.py` |
| 并发发布单赢家 | ✅ 两连接竞发，断言 seq 唯一且无洞 | 同上（语义为「advisory lock 串行、双赢」——见偏差台账 D-17-01） |
| 崩溃无半截 revision | ✅ fork sbcl 子进程，README 握手中 `kill -9`，断言 CURRENT 不动、无孤儿行 | 同上 + `v17/lisp/tests/crash-child.lisp` |
| journal append + recover-operations | ✅ append 无洞 seq + running→interrupted 折叠 + newest-first + 最近 100 条 | 同上 + store-suite |
| sbcl 版本不匹配拒绝加载 | ✅ 假冒版本发布后 load 必错 | store-suite |

## 计划 §5 G2 world

| 计划断言 | gate 覆盖 | 位置 |
|---|---|---|
| twice 示例 | ✅ `(twice (twice 3)) = 12` | `v17/world/lisp/session-scenarios.lisp` |
| preview 恢复 | ✅ preview 值 1、状态仍 0 | 同上 |
| 出错回 checkpoint | ✅ 执行失败后状态不变 | 同上 |
| 未记录变更拒绝 | ✅ `fmakunbound` / `intern` 定义均于 capture 报错 | 同上 |
| managed-state 跨进程字节一致 | ✅ 两 sbcl 进程同操作序列 → bytea 逐字节比对 | `v17/world/lisp/capture-bytes.lisp` |
| catalogue export→import 行为同一 | ✅ publish → 新进程 load → 调用结果与 catalogue 相同 | `publish-world.lisp` + `load-world.lisp` |
| fiveam world 套件随 gate 跑 | ✅ policy gate / capture / session 协议 / preview-error-restore / export-import / pgstore 往返 | `v17/lisp/tests/world-suite.lisp` |

## 计划 §5 G3 queue（v12 G6 七场景 + 2）

| 计划断言 | gate 覆盖 | 位置 |
|---|---|---|
| 1. 队列模式 tool 路由 e2e + effect_id 跨模式一致 + 消息全归档 | ✅ 事件序列精确匹配；SQL `v12_effect_id` == Python `uuid5`；q 空、a≥2 | `v17/queue/test_queue.py` 场景 1 |
| 2. 瞬时失败 VT 重投 | ✅ 首泵 archived=0、批次仍 ready、>2.2s 后成功、`total_calls=2` | 场景 2 |
| 3. 重复唤醒去重 | ✅ 两消息归档、一次 ask | 场景 3 |
| 4. 确定性失败 → 批次 failed + 单次尝试 + 转人工 | ✅ `del ""` 破坏校验后全满足，含 `reason=decision_failed` | 场景 4 |
| 5. 丢消息 → `v12_requeue_stale` 恢复 | ✅ 手动 decide 不投递 → 无消息 → 扫描重投 → 交付 | 场景 5 |
| 6. LLM + 护栏全走队列 | ✅ 五事件序列、`llm_calls=1`、两 answered 批次、两 ask | 场景 6 |
| 7. 多 turn 不串轮 | ✅ 同会话两 turn 均交付 | 场景 7 |
| 8. jsonb canary（postmodern cast 怪癖） | ✅ 嵌套/unicode/CJK/NULL 字节保真往返 | 场景 8 + `queue-suite.lisp` |
| 9. Python/Lisp worker 同抢一队（不双答） | ✅ 3 会话全交付；每批恰好 answered 一次；每 job 副作用恰好一次（`lisp+py == succeeded == 3`） | 场景 9 |
| fiveam queue 套件 | ✅ fake jev 首匹配/无匹配/瞬失败计次、fake llm 计数、json 形状 | `v17/lisp/tests/queue-suite.lisp` |

## 计划 §3.1 表结构（store）

| 计划表 | 实现 | 备注 |
|---|---|---|
| `lisp_revisions` | ✅ `revision_id` PK + world_id + seq + parent_id + state_text + manifest jsonb + sbcl_version + rollback_source | seq 宽化为 bigint（D-17-02） |
| `lisp_current` | ✅ world_id PK + revision_id + updated_at（指针 CAS 与 revision INSERT 同函数同事务） | |
| `lisp_journal` | ✅ world_id + seq + operation_id + generation + event jsonb | 追加无洞 seq 经 advisory lock；写侧有 event 形状校验（G1 评审后补） |
| `lisp_worlds` | ✅ name UNIQUE + package_name | |
| `v17_publish_revision` 等 5 函数 | ✅ 全部落地，另增 manifest 缺 sbcl 即 RAISE、advisory lock 覆盖 seq 分配 | |

## 计划 §3.2 world 面

| 计划要求 | 实现 |
|---|---|
| 不加新 pgmq kind、不加新表 | ✅ `v17_world.sql` 仅约定注释 + handler 命名（`lisp:` 前缀留给 G4） |
| `tools.handler='lisp:...'` / `jobs.kind='lisp_eval'` / `lisp_develop` | ⏳ G4/G5 开工时落地（计划 §5） |

## 计划 §2.1 环境实测教训遵守情况

| 教训 | 遵守 |
|---|---|
| 1. `with-connection` 包住 DB 操作 | ✅ `with-store-connection`；worker 主循环内单连接 |
| 2. quickload 与引用分置顶层 form | ✅ 所有 `--script` runner 分四个 form |
| 3. pgmq 参数显式 cast | ✅ `pgmq.read($1::text,$2::int,$3::int)` 等 |
| 4. env 传 PGSOCKETDIR/PGDATABASE | ✅ gate 侧 `SOCKET_DIR`，worker 经 `V17_*` env 注入 |
