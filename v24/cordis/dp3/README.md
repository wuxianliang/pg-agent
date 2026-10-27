# Cordis v2 DP3

DP3 从 DP2 已结项的内核继续做失效传播与可逆退役。产品行为由 `docs/designs/cordis-plugin-system-2026-10-25.md` 规定；实施计划是 `docs/plans/v24-cordis-dp3-teardown-plan-2026-10-27.md`。本 README 只记录已经实跑的阶段。DP1/DP2 的历史验收仍在各自 README 与 `docs/reviews/cordis-v2-dp1-*`、`docs/reviews/cordis-v2-dp2-*`，不在这里改写。

## 当前状态

**B0 与 W1 已完成。门禁实跑于未提交 HEAD `9fe6b5b`。W2–W5 尚未实现。本提交按 2026-10-27 用户授权把 W1 发布到 `origin/v24`；B0 是前一个提交。**

- 工作树 `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`，分支 `v24`，HEAD 仍是 `9fe6b5b170776907d490fab079fca63cdde6aa28`。当时 W1 尚未提交。本提交发布该结果。
- B0 于 2026-10-27 按计划 §4.1 串行实跑 21 条既有命令，退出码均为 0。当时 40=1130、41=1097、42 不存在、合计 2227，DDL 414，manifest 16。旧 gate 仍按单文件 1200 通过，5000/5001 迁移没有做。这些数字保留在 matrix 的 B0 节，不被 W1 改写。
- W1 于同日在该根上串行实跑 22 条命令。审查的两处 P2 关闭后再次逐条启动并等待退出，退出码均为 0：§4.1 的 21 条，然后 `uv run python v24/cordis/dp3/test_protocol.py`。CDP3-L/T/D/B 没有加入。逐条打印见 `docs/reviews/cordis-v2-dp3-conformance-matrix-2026-10-27.md` 的 W1 节。
- W1 容量用 `splitlines()`：`40_advance.sql` 1170、`41_lifecycle.sql` 1097、`42_teardown.sql` 16，合计 2283≤5000。这次修复没有改这三个文件的行数。共享 `v24/cordis/helper_budget.py` 的 `assert_helper_budget` 在临时目录上被调用，文件恰好是这三名，合计 5000 物理行时返回 5000，合计 5001 时拒绝。DP1 直接调用该证明，不导入 DP2。DP2 的 `assert_helper_budget` 先跑同一证明再检查真实目录。字面整数比较不是该证明。DDL 前缀 414。manifest 17。表 10。仅 `advance` 为 `SECURITY DEFINER`。源码中无 `CREATE VIEW` / `CREATE EXTENSION`。
- 冻结 diff `git diff --exit-code 57e2c1e -- v24/load.py v24/sql v24/s1 … v24/s12` 退出 0。`git diff --check` 退出 0。
- `42_teardown.sql` 只有 `command_barrier`（生产返回 NULL）和只读 `lifecycle_step`（精确 `{tag:"idle"}`，`advance` 与 `interpret_command` 不调用）。idle 不是 teardown 选择器，W2/W3 替换该函数体。其余六项 teardown helper 未建。
- command 私有控制结果在 `validate_and_apply_delta` 之前分流。deferred、`blocked_unknown`、`unsupported` 由替换 `command_barrier` 的非生产探针证明，十表零写，调用方提交后第二连接取得 G。该探针不是生产 P6。
- replay-first 在屏障仍非 ready 时证明。生产 NULL `command_barrier` 下先提交一笔 admitted existing-scope install（`disposition` committed）。再把函数换成 deferred 与 `blocked_unknown`。同一 request 重放首次 response，十表快照不变，仍是一条 request 与一条 event。然后才恢复原函数。该重放不是生产 P6，也不是 W3 的屏障满足后首次提交。
- 身份伪造仍是 `effect_id_conflict`。有效身份下的 generation/target/phase 由 `continuation_state` 返回无 `code` 的控制分类，advance 仍在解释器前以 `0A000` 失败关闭。ready input 不可改（`55000`），第二 ready reconcile 被 I7 拒绝（`23505`），已有槽时 `on` 为 `0A000`。没有合并提交。`off`/`retry` 仍 `0A000`。claim 与 I7 保持。
- 无关的预算文档修订和未跟踪用户文件不进入本提交。

## 未覆盖

W2–W5 未交付：真实 off/on/retry 真值表、drift 转 closing、failure、leave/unload、withdraw/release、inverse、drain，以及已激活实例的有界 dispose。CDP3-L/T/D/B 不存在。`lifecycle_step` 的 idle 与 W1 deferred 探针都不是这些生产行为。CDP1-K 的通过行仍印出固定句“dispose remain 0A000”；同一轮 CDP2-B 已经提交了无活义务的 basic dispose。这两句打印都原样保留，不把前者读成“dispose 仍未实现”。

DP2 的 `origin/v24` 授权不延伸到 DP3。`AGENTS.md` 仍写推送 `origin main`。2026-10-27 用户明确授权全部 DP3 里程碑逐个 commit 并 push `origin/v24`。本提交发布 W1。
