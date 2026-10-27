# Cordis v2 DP3

DP3 从 DP2 已结项的内核继续做失效传播与可逆退役。产品行为由 `docs/designs/cordis-plugin-system-2026-10-25.md` 规定；实施计划是 `docs/plans/v24-cordis-dp3-teardown-plan-2026-10-27.md`。本 README 只记录已经实跑的阶段。DP1/DP2 的历史验收仍在各自 README 与 `docs/reviews/cordis-v2-dp1-*`、`docs/reviews/cordis-v2-dp2-*`，不在这里改写。

## 当前状态

**B0 已完成基线取证与文件订正。W1–W5 尚未实现，不在本提交。本提交按 2026-10-27 用户授权把 B0 发布到 `origin/v24`。**

- 工作树 `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`，分支 `v24`，HEAD `9fe6b5b170776907d490fab079fca63cdde6aa28`，与 `origin/v24` 一致（`git rev-list --left-right --count origin/v24...v24` = `0 0`）。
- 2026-10-27 在该根上按计划 §4.1 串行实跑 21 条既有命令，每条单独启动并等待退出，退出码均为 0。这不是复制 DP2 在 `d5fd1bc` 上的历史退出码。逐条打印见 `docs/reviews/cordis-v2-dp3-conformance-matrix-2026-10-27.md`。
- 冻结的十二份 `v24/sql/*.sql` SHA-256 与 DP2 matrix 一致。`git diff --exit-code 57e2c1e -- v24/load.py v24/sql v24/s1 v24/s2 v24/s3 v24/s4 v24/s5 v24/s6 v24/s7 v24/s8 v24/s9 v24/s10 v24/s11 v24/s12` 退出 0。`git diff --check` 退出 0。
- 容量：`40_advance.sql` 1130、`41_lifecycle.sql` 1097、`42_teardown.sql` 不存在，合计 2227。DDL 前缀 414。manifest 16。表 10。CDP2-B 断言仅一个 `SECURITY DEFINER`。源码中无 `CREATE VIEW` / `CREATE EXTENSION`。旧 gate 仍按单文件 1200 通过；5000/5001 迁移没有做。
- 未改 `v24/cordis/sql/**` 与任何测试。工作区里原有的预算文档修订和未跟踪用户文件保留，没有暂存。

## 未覆盖

没有 DP3 生产实现：无 `42_teardown.sql`，无 CDP3-P/L/T/D/B。`off`/`retry`、drift 转 closing、failure、leave/unload、withdraw/release、inverse、drain 与已激活实例的有界 dispose 仍未交付。CDP1-K 的通过行仍印出固定句“dispose remain 0A000”；同一轮 CDP2-B 已经提交了无活义务的 basic dispose。这两句打印都原样保留，不把前者读成“dispose 仍未实现”。

DP2 的 `origin/v24` 授权不延伸到 DP3。`AGENTS.md` 仍写推送 `origin main`。2026-10-27 用户明确授权全部 DP3 里程碑逐个 commit 并 push `origin/v24`。本提交只发布 B0。
