# Investigation: v17 主要设计思路、实现与测试情况

日期：2026-10-07。对象：`v17/` + `docs/plans/v17-sbcl-worker-plan-2026-10-06.md` + 覆盖矩阵/偏差台账。
调查性质：设计/实现/测试现状综述，不做代码改动。

## Summary

待填充。

## Symptoms

调查问题（非 bug 症状）：

- v17 的一句话设计是什么？与 v12 / jiti / v15-v16 的关系是什么？
- 实现落到了哪里？SBCL worker / world daemon / Postgres store 如何组装？
- G1–G6 gate 与 fiveam 套件的覆盖是否真的全绿？计划与实现/台账有哪些偏差？
- 计划正文仍写「设计稿，待评审冻结，零代码」，但目录与 README 声称 G1–G6 全绿——文书与代码是否失步？

## Background / Prior Research

### Git archaeology（explore 84B18351）

五次提交、同一作者，约 66 文件 / ~8,000 行。末次提交说明写 All six v17 gates exit 0。

| Commit | 时间 | 摘要 | 宣称 gate |
|---|---|---|---|
| `539dae1` | 2026-10-06 20:27 | SBCL worker scaffold + Postgres store + world kernel | G1, G2 |
| `632b033` | 2026-10-06 22:21 | SBCL queue worker 替代 Python QueueWorker | G3 |
| `43e2462` | 2026-10-07 02:13 | world daemon：lisp_eval / lisp_develop / `lisp:` | G4 |
| `700699e` | 2026-10-07 03:04 | 长出来的 Lisp 函数接入 v12 tool routing | G5 |
| `0f954a4` | 2026-10-07 03:45 | repair：pause / repair form / resume restart | G6 |

计划文件 `docs/plans/v17-sbcl-worker-plan-2026-10-06.md` **只在 `539dae1` 写入，此后从未改**。头部仍写「设计稿，待评审冻结，零代码」。覆盖矩阵与偏差台账随 G3–G6 增量更新（G6 提交后矩阵称 6 gate 全绿；台账 D-17-01…D-17-13）。文书失步主要集中在计划头，不是矩阵/台账。

### v17 vs v12 血统（explore 7018335D）

`v17/load.py` 的 `SQL_LOAD_ORDER`（约 L20–30）：v12 的 7 个 SQL 按相对路径只读引用（schema/decide/act/turn/fanout/queue/indb），再追加 `v17_store.sql`（G1）与 `v17_world.sql`（G2）。文件头写明 v12 never modified / loaded READ-ONLY。`files_through()` 按 stage 切片；`queue`/`lisptools`/`develop`/`repair` 都加载全部 9 项。

v12 最近提交 `fd1a4b5`（2026-09-21），早于首个 v17 提交；五次 v17 提交均未改 `v12/`。Python `QueueWorker` 仍在 `v12/queue_worker.py`（class 约 L58），G3 混跑对手。

## Investigator Findings

<!-- Pair investigator appends structured analysis here. -->

## Investigation Log

### Phase 1 — Triage

**Hypothesis:** v17 是一条完整的 SBCL worker 线：只读加载 v12 的 7 个 SQL，用 postmodern 连 pgembed，把 jiti 文件 store 表化进 Postgres，并增加 `lisp_eval` / `lisp_develop` / `lisp:` 工具路径；G1–G6 已有对应 Python gate + Lisp fiveam 套件；计划正文可能未随实现更新。

**Initial evidence:**

- 计划：`docs/plans/v17-sbcl-worker-plan-2026-10-06.md` 头部仍写「设计稿，待评审冻结，零代码」。
- 实现树：`v17/{store,world,queue,lisptools,develop,repair,lisp}/` 齐全。
- README 声称 G1–G6 全 green。
- 覆盖矩阵至少记录到 G4；G5/G6 矩阵可能不全。
- git：5 次 `v17:` commits（10-06 G1/G2 脚手架 → G3 queue → G4 worldd → G5 develop → G6 repair）。

**Conclusion:** Needs more investigation — 设计与结构大致清晰，但实现层详情、偏差、测试真实覆盖与文书失步度待 pair + oracle 核实。

### Phase 2 — context_builder fallback

**Hypothesis:** context_builder 能自主发现 v17 设计/实现/测试文件。
**Findings:** `context_builder` 连续 MCP timeout（question 两次、clarify 两次）；`ask_oracle` 在全量选择上同样 timeout。改为 `manage_selection add` 手动纳入计划/矩阵/台账 + `v17/` 全树（约 100k tokens）。
**Evidence:** 选择集含 plan、conformance matrix、deviation ledger、load.py、六个 stage 的 README/test/sql、`v17/lisp/src/*` 与 tests。
**Conclusion:** 流程偏差已记；不阻塞 pair 主线调查。

## Root Cause

待填充。

## Recommendations

待填充。

## Preventive Measures

待填充。
