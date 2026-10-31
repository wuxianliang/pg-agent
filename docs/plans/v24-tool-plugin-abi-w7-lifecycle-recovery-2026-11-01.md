# v24 Tool/Plugin ABI W7：完整生命周期与恢复收口 Deep Plan

日期：2026-11-01。版本：v6（第三轮 2 路 Oracle 后的 P1/P2 落实；lane 1 `pass` / lane 2 `needs-edits`）。状态：计划（未执行）。基线：`main` @ `a41ce220b60af95070d93ce1571d09d70299a5cf`（"v24: close out Tool/Plugin ABI M5"），`origin/main` 与本地 HEAD 相同。工作区已跟踪文件干净；未跟踪的 `.ctx-export-*`、`.token-probe*`、`ctx_export_check*`、`v20/experiments/ce_native_d5/` 与本计划无关，不进入候选集。

v2 已按 2026-11-01 两路 Oracle 审核（`needs-edits`）修订：P0 五项、P1 五项与 P2 建议全部落入正文；新增 R15（multiple pending tools）与 R16（K3.5），探针总数 16、`cases=30`。

v3 只解决 v2 的**可执行性、自洽性与未决项**，不改变 W7 的范围、marker、`cases=30`、`recovery_probes=16`、closeout 11/11 或 32-command 形态。v3 的实质变化：§17 #16 的 R07/R09/R14 三项全部落成显式调用顺序与断言；R01 的 `C(2)` 与 release 顺序固定；R02 改用 G12-G 的 `_execute_tool` monkeypatch；R11 四个 artifact 子探针按 `require_artifact` 的检查顺序重排；R15 的 `db.settle` patch 形状、`_settle` 的 `assert_all_idle` 与 `reconciled=3` 写明；R16 的 `inject_before` 过滤条件与一次性命中写明；R03 补 fork 前连接审计；§10.5 给出每 case 预算表与总预算；§16 的行号按本次实测源码复核。裁决原文保留在 §17，v3 修订见 §17.1。

v4 落实第二轮 2 路 Oracle（`needs-edits`）中被裁决**接受**的 P0 一项、P1 三项与 P2 四项，并把四条**被驳回**的裁决连同证据记进 §17.2：R10 的 `target` 从 ordinal 改为 UUID（真实缺陷）；R03 的 fork 子进程失败路径与父进程 `kill`/`waitpid`；`assert_no_live` 改为只观察、清理移到 case 最外层 `finally`；helper 清单与 audit 7 的 import allowlist 补齐（`assert_w7_invariants`、`HostDB`、`PluginDispatcher`、`install_spawn_log`、`_owner`）；Result 不再要求自身 commit SHA；R09 删掉同义 guard；R03 写明 500ms lease 余量；R07 增加 `host_prepare` effect 计数幂等断言。v4 **未**改变 `cases=30`、`recovery_probes=16`、marker、closeout 11/11、32-command 形态或 8 路径候选集。

v5 落实第三轮 2 路 Oracle（同一 L1/L2，`needs-edits`、**无 P0**）收敛出的三类 P1：`assert_w7_invariants` 改为 **scope 级**、签名去掉 `run_id`，并用显式 `recovered_unknown` 表示该 case 期望出现 `effect_recovered_unknown` 的 effect（R02/R03 传 `{target}`，其余 case 为空集）；删除 R05/R14/R15/R16 里重复的 `close_connections`，由 `run_recover_process` 独占 journal→db→owner 的关闭责任；R02 的 restore 改为把保存的 bound method **重新赋值**给 `worker._execute_tool`（不是 `del`）。P2 落实 `patch.stop()` 措辞、残留 “guard” 措辞、§11 W7-1 的 helper 清单、R03 的证据口径、§10.5 的 R08/R14 描述、ESRCH 语义、R13 的推理句、publication receipt 固定路径与 §16 的 `line_json` 引用。两条被驳回的裁决见 §17.3 X5/X6；v5 **未**改变 `cases=30`、`recovery_probes=16`、marker、closeout 11/11、32-command 形态、8 路径候选集或 helper 计数（15 组 / 17 个）。

v5 复核（2026-11-01，只读源码 + 一次性 `uv run python`，不作为 W7 pass 证据）：`harness.db.host_effects(scope)` 单参合法（`db.py:144-149` 的三个游标参数都有默认值），但该读只返回 `ready`/`claimed`（`49_host_reads.sql:184`），**不能**枚举已 settle 的 effect；`host_runs(scope)` 与 `host_run_effects(run)` 都不按状态过滤（`:76-127`、`:264-266`）。`line_json.py:274`（`_run_v2`）与 `:319`（v1 `run`）是两条路径上的 `run_process` 调用点，都调用模块级函数，patch `line_json.run_process` 一次覆盖 v1/v2。

v6 落实第三轮 2 路 Oracle 的合并结果：lane 1 判 `pass`、lane 2 判 `needs-edits`、**无 P0**；两条 P1 是可执行性缺口，A23–A26 是 P2 的措辞/适用范围修正。v6 的实质变化：`assert_w7_invariants` 在入口把 `recovered_unknown` 归一为规范字符串，枚举 effect 也用 `str(effect_id)` 做成员判断（R02/R03 仍可传 `uuid.UUID`）；`install_crash_after_started` 改为返回 `(restore, original)`，R02 用 helper 返回的 `original` 做 `is` 断言；`close_connections` 的调用方限定为 R03 fork 前、R06 restart 前与 `run_recover_process` 内部；§9 I6 的“先观察、后清理”只约束 R13，R03 保持测试侧先 `killpg` 再 `assert_no_live`；R09/R10 改用 `tool_order`；I4 的 install 枚举改用 `host_scope_installs` 翻页，helper 只保证 log 自洽与无重复 prepare/release。§17.4 另记四项已核实的静态事实。v6 **未**改变 `cases=30`、`recovery_probes=16`、marker、closeout 11/11、32-command 形态、8 路径候选集或 helper 计数（15 组 / 17 个）。

本计划是 **M5 之后的恢复补证阶段**，不是 design §10 的新 M 阶段，也不是 M4 的重做。M4 已由 W4c 在 C.11 下声明完成；W7 只补 W4c 执行记录自己列出的三个未覆盖项：**每个 crash window、mixed-batch replay with multiple pending tools、real process restart**；其中“每个 crash window”按 §6 落成 K0–K5+K3.5 的枚举，而不是无限全集。W7 不改变 M4/M5 的完成状态，不新增 closeout 条目，不重开 design 正文。

> v2/v3/v4 编写时做过若干**临时探针**（`/tmp`，未写入仓库，不作为验收证据）：v2 确认 R01/R02/R04/R07/R08/R09/R11 可测；v3 补测 R07 的 resume/幂等与完整 lifecycle、R09 的 read-last/read-first 两分支、R14 的 union/CountingSpawn/B0 字节、R15 的 3 pending + reconcile=3、R16 的 database_terminal 补写；v4 复核 `md5().hexdigest()` 与 `uuid.UUID()`/`md5(...)::uuid` 的等价性、以及 `min(dict, key=dict.get)` 返回键而非值（§4.6）。它们只降低计划风险，不计入 W7 pass。R03/R05/R06/R10/R12/R13 以及 R14/R15/R16 的 fresh-process 版本仍需按本计划实现并实测。

---

## 1. 为什么 W7 是「恢复收口」而不是「生命周期实现」

### 1.1 W4c 已经交付了什么

`v24/s13/test_lifecycle.py` 现有 645 行、14 个 case，覆盖 design §7.3 的 **G12-A…H + G12-L**：

| Case | 现有覆盖 | 关键断言 |
|---|---|---|
| G12-A | Python `read` + Node `list`/`search`，两个 install，三 key start，真实子进程，完整 off/dispose/release/scope close | `test_lifecycle.py:238-277` |
| G12-B | 同一 model batch 三个 tool，屏障后恰一个 continuation，list/search pin 同一 install | `:280-307` |
| G12-C | 非法 args `offset=0` → `invalid_tool_arguments` | `:310-334` |
| G12-D | 非法 output（`bad_value`/`bad_relation`）与 renderer 异常 → failure，不是 unknown | `:337-372` |
| G12-E | 插件 timeout → unknown `timeout`，run `blocked_unknown` | `:375-387` |
| G12-F | registry 内存中的 artifact/adapter/descriptor 篡改 → failure，零 spawn | `:390-433` |
| G12-G | `dispatch_finished` 之后崩溃，重建 journal/worker，`_reconcile` 从 journal 重交 | `:436-524` |
| G12-H | Node search 剩余 lease 19999 ms < 15000+5000 → `lease_insufficient`，零 spawn | `:527-551` |
| G12-L | v1 echo success/known-error 的 provider request 与 tool message 逐字节等于 B0 | `:554-601` |

W4c 的 marker 是：

```text
[passed] W4 lifecycle; cases=14; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true
```

W4c 执行记录同时写明了边界（`docs/reviews/v24-tool-plugin-abi-w4c-execution-2026-10-31.md:146-147`）：

> the replay test uses the journal-only `_reconcile` path after a tool `dispatch_finished`; it proves no rerender/second spawn for that window. It does not cover every crash window, mixed-batch replay with multiple pending tools, or a real process restart.

这三句话就是 W7 的任务书。

### 1.2 W7 的实质增量

W7 不重写 `fs_read.py` / `fs_tools.js`，不重写 registry、dispatcher、worker、line-json，也不改 SQL。W7 增加的是**恢复窗口的证据矩阵**：

1. 把 crash 从「`dispatch_finished` 之后」扩展到 `effect_prepared`、`dispatch_started`、真实 spawn 之后、`dispatch_finished` 之后、**DB settlement 已提交但 journal settlement 未写**（K3.5）、settlement 之后，以及 `host_prepare` / `host_release` 两个资源 effect。
2. 把「同进程重建 worker」升级为**独立 OS 进程恢复**，并至少做一次**真实 host 进程被 SIGKILL、插件已 spawn**的崩溃。
3. 把 single-tool replay 扩展到**三工具 mixed batch**：一个 timeout + 两个 success、第一个 tool `dispatch_finished` 后崩溃（一个 pending + 两个 ready），以及**三个 pending settlement 由独立进程 reconcile**（R15）。
4. 把 tamper 从 registry 内存对象扩展到**磁盘 artifact 本体**，并覆盖 workspace root 消失。
5. 把 timeout 从「结果正确」扩展到**进程组清理**（插件 + 孙进程无 live 残留）。
6. 把 legacy 从「字节不变」扩展到 **v1 在崩溃恢复路径上的字节不变**，并验证 v1/v2 同 scope 共存。
7. 增加 K3.5：DB 已 settle、journal 未写 settlement 时崩溃，重启只补 settlement、不二次 settle（R16）。

### 1.3 不是什么

- 不是 M4 重开。W7 全绿不改变 C.11 的 “M4 complete”，也不把 M4 改成 “M4 revised”。
- 不是 M6。design §10 没有 M6；W7 只是 s13 extension evidence。
- 不是 replay 授权。`replay_class=read_only` 仍是 metadata only；tool successor 仍是 `no_replay`；W7 只证明「不重投」，不实现「可重投」。
- 不是 closeout 第 12 条。closeout 仍是 **11/11**，s13 仍是 extension evidence。

---

## 2. Goal 与范围

### 2.1 In scope

1. 在 `v24/s13/test_lifecycle.py` 内新增 **R01–R16 共 16 个恢复 case**，保留现有 14 个 case 的行为与断言。
2. 增加测试侧 cut-point 注入：在 `HostJournal.append` 返回后、下一行之前抛 `HostCrash`，精确命中 `effect_prepared` 之后、`dispatch_started` 之前；另加“append 之前”注入，命中 DB settle 之后、journal `settlement_committed` 之前（K3.5）。所有注入都是一次性，并在 `finally` 恢复。
3. 增加 fresh-process recovery 资产 `v24/s13/w7_recover.py`：只打开 DB/journal，调用 `_reconcile`，输出 `reconciled` 与新增 `settlements`，不构造 registry、不 spawn。
4. 增加真实进程崩溃 case：fork 一个 host 子进程，测试插件在 spawn 后 `SIGKILL` 父进程；父 gate 进程恢复并断言无第二次 spawn。
5. 增加 mixed batch：一个 timeout + 两个 success；第一个 tool `dispatch_finished` 后崩溃、重启后继续剩余 tool；以及三个 pending settlement 由 fresh process 一次 reconcile（R15）。
6. 增加 K3.5：DB settle 成功、journal settlement 未写时崩溃；重启只补 journal settlement，不二次 settle（R16）。
7. 增加磁盘 tamper：artifact digest 不符、缺失、非普通文件、越出 cwd；workspace root 被移走。
8. 增加 timeout 进程组清理：测试插件派生孙进程；host timeout 后插件与孙进程都不能 live。
9. 增加 v1/v2 同 scope 共存与 v1 崩溃恢复，B0 provider/tool-message 字节不变。
10. 更新 README、conformance matrix、deviation ledger、W7 execution record 与本计划 Result。

### 2.2 Out of scope（明确不做）

- `v24/host/**` 的生产行为修改。W7 预期只改测试与文档；若探针暴露真实缺陷，只允许在 W7-8 做 host-only 修复，并重新跑全套证据。
- `v24/sql/**`。零 diff；不改 recovery、claim、successor、effect kind、journal event type。
- `v24/s13/plugins/fs_read.py`、`v24/s13/plugins/fs_tools.js`。W5/W6 已收口；artifact SHA 必须保持不变。
- `v24/s13/vectors/**`、`design_conformance.json`、`test_contracts.py`、`DESIGN_SHA256`。不 promotion、不重捕获、不改冻结 status。
- `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md` 与主设计。W7 不新增 Appendix C.19；需要改设计就 STOP。
- `test_tools.py`、`test_node.py`、`test_wiring.py`、`test_registry.py`、`test_line_json.py`、`test_descriptor.py`、`test_schema.py`、`test_renderers.py`、`test_results.py`、`test_pages.py`、`test_contracts.py`、`test_vectors.py`。
- `v24/s11/plugin_fixtures.py` 的现有行为。可以 import，不修改。
- 真正的 tool replay、写工具、交互 approval、in-flight cancel、资源撤销、session/spawn 表、fair-worker 恢复策略。
- 真实 provider、网络 socket、Linux real、非 UTF-8 新证据、12 秒墙钟 gate。
- 修改 `no_replay` 或 `replay_class` 语义；把 `dispatch_started` 前移；新增 journal event type。

---

## 3. Done when

1. **现有 14 个 case 行为不变。** G12-A…H/L 的断言仍通过；`test_lifecycle.py` 原有 helper 的语义不被改写；G12-L 的 B0 字节仍逐字节相等。
2. **R01–R16 全部通过，且 marker 精确为：**
   ```text
   [passed] W4 lifecycle; cases=30; recovery_probes=16; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true; no_replay=true
   ```
   `cases` 计数约定：现有 14 个 + 新 R01–R16 各算 1 个 = 30。W4c 的 14 由子场景构成（A1+B1+C1+D3+E1+F3+G1+H1+L2）；W7 改用**函数级计数**（一个 `rNN_*` 函数算 1），R11 的四个 artifact 形状、R13 的 restart 阶段、R14 的 success/known-error/crash 阶段、R15 的三个 pending、R16 的 settlement 补写都算同一 case 的子探针。两种口径不同，§9/§17 必须写明。若实现时 inventory 不同，先改本计划再跑 sweep，不得事后改 marker 迁就结果。
3. **crash 窗口矩阵覆盖 K0–K5 + K3.5**（定义见 §6）：K0 至少 R01/R07/R08，K1 至少 R02，K2 至少 R03，K3 至少 R04/R05，K3.5 至少 R16，K4 至少 R06，K5 至少 R04。
4. **R03 是真实进程崩溃，不是同进程异常。** host 子进程必须由 `SIGKILL` 终止（`WIFSIGNALED` 且 `WTERMSIG==SIGKILL`）；插件已 spawn（spawn log 有 `invoke` 行）；恢复后 `invoke` 行数仍为 1。stub `timeout_ms=1000`、child `default_lease_ms=6500`，满足 `remaining >= timeout_ms + 5000` 的 spawn 门槛。
5. **R05/R14/R15/R16 的恢复由独立 OS 进程完成。** `w7_recover.py` 退出 0，输出 `[w7-recover] reconciled=N settlements=M`；`settlements` 是**本次进程的增量**（`after - before`），不是 journal 总数。R05/R14 要求 `reconciled>=1`，R15 要求 `reconciled=3` 且三个 tool 的 `db.settle` 都在 fresh process 成功，R16 允许 `reconciled=0` 但必须 `settlements=1`。恢复进程不构造 registry、不 spawn；辅助证据是 journal 只新增 settlement、spawn 计数不变。`reconciled=3` 的依据是 `_reconcile` 遍历 `pending_settlements()` 的三个 effect，`status="claimed"`、journal claim token 与 DB `attempt_no/fence/claim_owner` 相等、`db.settle` 返回非 error，每成功一个 `settled += 1`（`worker.py:768-789`）。
6. **R10/R15 的 mixed batch 只有一个 continuation；R09 的 unknown 不建 continuation。** R09 三个 tool 全部产生 receipt（read unknown，list/search success），run `blocked_unknown`，model call 恰 1 次，model effect 仍 1、continuation 0；**R09 的 read 必须最后执行**：tool effect 按 `md5(model_id:tool_call:ordinal)` 的 UUID 升序执行，测试把 read 放在 UUID 最大的 ordinal（`order = tool_order(model_id, 3)`，`read_ord = order[-1]`；3 个 UUID 互不相同且全序，最大者一定存在，不需要 skip 分支）。若 read 先执行，run 立即 `blocked_unknown`，list/search 仍会被同一 worker claim 并 spawn，但 `db.settle` 返回 `blocked_unknown`，两个 effect 停留 `claimed` 且无 settlement；R09 不采用这个顺序，但把它写成显式已知分支（§8 R09）。R10 三个 tool 全部 success，model effect 恰 2 个（initial + continuation），continuation 恰 1 个；崩溃时只有 1 个 pending settlement、2 个 ready，崩溃目标是**执行顺序第一**（effect UUID 最小）的 tool。R15 三个 tool 的 `db.settle` 被注入 error，三个都是 pending；fresh process 一次 reconcile=3，随后 continuation 恰 1 个、无 tool 重 spawn。
7. **R11/R12 的 tamper/workspace 失败全部零 spawn。** 每个失败形状都有 `ZeroSpawn` sentinel 与 spawn log 双证；恢复原始 artifact/workspace 后下一次调用成功。
8. **R13 的 timeout 进程组无 live 残留。** 插件 pid 与孙进程 pid 在 timeout 后都不处于 live 状态；`invoke` spawn 恰 1 次；effect `unknown/timeout`；run `blocked_unknown`；重启不重投。
9. **R14 的 v1 字节与恢复都不变。** v1 success/known-error 的 provider request 与 tool message 逐字节等于 B0；v1 known-error 在 `dispatch_finished` 后崩溃，fresh process reconcile 只补一次 settlement；v1 进程计数用 `CountingSpawn(artifact=v1.entry.artifact_path)`（prepare + success invoke + known-error invoke = 3），恢复前后不变；v2 同 scope 的 read 不受影响。v1 的 tool message 必须按 `parent_effect_id == v1_model_id` 过滤，不能取 journal 里第一个 `tool_call`（union 中 v2 read 会先写一条）。
10. **不变量全部成立。** 所有 tool effect 的 `replay_policy` 都是 `no_replay`；DB recovery 的 action 是 `settle_unknown`，reason 是 `lease_expired`，绝不出现 `reset_ready` 的 tool_call；正常 settle 不要求 effect-level event，DB recovery 时 `effect_recovered_unknown` 恰 1、其余 tool effect 恰 0（期望集合由 `assert_w7_invariants(..., recovered_unknown=...)` 显式给出：R02/R03 为 `{target}`（`uuid.UUID`，helper 入口归一为规范字符串），其余 case 为空）；有 `dispatch_finished` 的 effect 的 journal `settlement_committed` 恰 1；K3.5 的 settlement 补写不改变 effect row；第二次 `_reconcile` 返回 0（K3.5 第一次也可能返回 0，用 settlements 判定）。
11. **32 条串行命令全部 exit 0。** 第 1–31 条有命令专属 `[passed]` 末行，第 32 条 `git diff --exit-code c8c4bd0 -- v24/sql` 输出为空；无 exit 2 / `[SKIP]`；closeout 仍 **11/11**。第 30 条的 marker 使用上面的 30/16 版本。
12. **七项 scope audit 在文档落盘后、staging 前重跑全过。** 候选集只含 §12 的 8 个路径；`v24/host`、`v24/sql`、`v24/s13/vectors`、design、冻结测试零 diff。
13. **文档一致。** README、matrix、ledger、execution record、本计划 Result 对 W7 的描述一致；不得把 W7 写成 M4 重开、M6 完成或 closeout 12/12。
14. **按路径提交并非 force push。** 提交信息 `v24: close out v2 lifecycle and recovery evidence`；不使用 `git add -A`/`git add .`/`--no-verify`/force。
15. **运行时间可控。** 先测现有 14 case 的基线（本次实测 12.5s）；加入 16 个探针后 `test_lifecycle.py` 单次目标 ~48s、硬上限 90s。R03 约 6.5s lease 等待、R02 约 3s，均为轮询；其余 case 的预算见 §10.5。不得用长 sleep 换稳定，不得为省时间删 case。

---

## 4. Current-state analysis（基线 `a41ce22`）

### 4.1 调用链与恢复所有权

```text
model batch
  → worker._execute_model（model effect：effect_prepared → dispatch_started → provider → dispatch_finished → settle）
  → DB advance 建 tool effect（pin_id, descriptor_digest, batch_digest, replay_policy=no_replay）
  → worker._execute_tool（effect_prepared → dispatch_started → plugins._tool_v2 → spawn → dispatch_finished → settle）
  → plugins._tool_v2 十三步（match_tool / args / schema / artifact / workspace / lease / spawn / parse / output / render / budget）
  → RENDERERS.render + tool_results 预算
  → 下一轮 model continuation
```

关键所有权：

- **DB** 拥有 effect 身份、pin、claim、lease、receipt、run 状态、recovery action。工具的 `replay_policy` 由 successor 固定为 `no_replay`（`v24/sql/48_loop.sql:1133`；recovery 的 `no_replay + tool_call` 分支在 `v24/sql/49_recovery.sql:369-371`）。
- **Host journal** 拥有本机 transcript：`effect_prepared` / `dispatch_started` / `dispatch_finished` / `settlement_committed`；每个 append 都 fsync（`v24/host/journal.py:1-18`）。
- **HostWorker** 拥有恢复顺序：`_reconcile`（`worker.py:754`）→ `_resume_prepared`（`:701`）→ `_orphan_state`（`:812`）→ `_recover`（`:852`）→ `_discover_ready` → claim/execute。
- **测试 harness** 拥有生命周期驱动：`PluginHarness`（`v24/s11/plugin_fixtures.py:274-429`）与 s13 的 `open_harness`/`spawn_count`（`v24/s13/fixtures.py:429-453`）。

### 4.2 已覆盖的恢复行为（W4c）

| 窗口 | 现有 case | 现有证明 | 缺口 |
|---|---|---|---|
| `dispatch_finished` 后、settle 前 | G12-G | 重建 journal/worker，`_reconcile` 从 journal 重交；handlers raising；无第二次 spawn；无第二次 settlement；renderer digest 改动不被重渲染 | 同进程重建；R04 补 model call；R10 覆盖 1 pending + 2 ready；R15 覆盖 3 pending；R16 覆盖 K3.5 |
| timeout | G12-E | stub sleep 0.6s + 300ms deadline → unknown `timeout`，run blocked | 未证明进程组/孙进程清理；未证明 restart 不重投 |
| registry tamper | G12-F | 内存中 artifact/adapter/descriptor 改动 → failure，零 spawn | 未覆盖磁盘 artifact 本体；未覆盖 workspace root 消失 |
| lease 不足 | G12-H | Node search 19999ms 剩余 lease → `lease_insufficient`，零 spawn | 未覆盖 lease 过期后的 `settle_unknown` |
| mixed batch | G12-B | 三 tool 同 batch，恰一个 continuation | R09 覆盖一个 unknown + 两个 success；R10 覆盖 crash 后 1 pending + 2 ready；R15 覆盖 3 pending |
| legacy | G12-L | v1 provider request/tool message 等于 B0 | 未覆盖 v1 崩溃恢复；未覆盖 v1/v2 同 scope |

### 4.3 未覆盖的 crash 窗口

`HostWorker` 的 `crash_after` 只接受 `prepared`/`started`/`finished`（`worker.py:86-89`），且三个分支并不对称（`_execute_tool` 的 `dispatch_started` 在 `:1042-1046`，`db.assert_all_idle()` 在 `:1047`，`crash_after=="started"` 检查在 `:1048`）：

- `prepared` 只在 `_execute_model` 有检查（`worker.py:970`）；`_execute_tool` 与 `_execute_resource` 在 `effect_prepared` 之后没有该检查。
- `started` 在 model（`:985`）、tool（`:1048`）、resource（`:1101`）都有。
- `finished` 在 model（`:1020`）、tool（`:1081`）、resource（`:1123`）都有。

因此，**tool `effect_prepared` 之后、`dispatch_started` 之前**这个窗口不能靠 `crash_after="prepared"` 命中；必须在测试侧包一层 `HostJournal.append`，在 append 返回后抛 `HostCrash`。这是 W7 的 D3。

另一个没有生产 hook 的窗口是 **K3.5**：`_settle` 先 `db.settle`，成功后才 `journal.append("settlement_committed")`（`worker.py:1278-1288`）。中间崩溃时 DB 已 terminal、journal 仍停在 `dispatch_finished`。测试侧在 `settlement_committed` append **之前**抛 `HostCrash`，恢复时 `_reconcile` 走 `database_terminal` 分支补 settlement，`settled` 计数为 0；因此不能用 `reconciled` 判定该窗口，必须用 journal settlement 增量（R16）。

### 4.4 不是缺陷、不得「修」的部分

- **`dispatch_started` 在 handler 之前写。** 这是 v1 既有顺序；pre-spawn 失败也可能留下 `dispatch_started`（design C.14）。W7 的零 spawn 证明用进程计数双证，不用 journal 事件数。
- **`no_replay` 是硬边界。** `replay_class=read_only` 只是声明；tool successor 仍 `no_replay`；`49_recovery.sql:369-371` 对过期 claimed tool 走 `settle_unknown/lease_expired`。W7 不把它改成 `reset_ready`。
- **K1/K2 的 journal 可能停在 `dispatch_started`。** DB recovery 没有 `dispatch_finished` 可写；host journal 不会伪造事件。W7 以 DB `effect_recovered_unknown` 为 receipt，不要求 journal 补一条 `dispatch_finished`。这是 D8 的已知不对称，不是 W7 要修的 host bug。
- **`_reconcile` 只处理有 `dispatch_finished` 的 pending settlement。** 没有 finish 的 claimed effect 走 `_recover`（DB 命令），不走 `_reconcile`。两者不要混。
- **`replay_class` / `concurrency` 进 descriptor 只是 metadata。** 不改 recovery；不改 successor。
- **v1 路径不动。** `ApprovedAdapter`、`match_pin`、`line_json` v1 parser、`canonical_json(output)` 保持不变；v1 字节是 golden。

### 4.5 可复用件

| 件 | 位置 | W7 用途 |
|---|---|---|
| `PluginHarness` | `v24/s11/plugin_fixtures.py:274-429` | admit/prepare/activate/start/off/dispose/close_scope；owner 读；`close()` 只关连接，不触发 release |
| `open_harness` / `spawn_count` | `v24/s13/fixtures.py:429-453` | 建 registry、读 spawn log；`install_spawn_log` 对无 `--spawn-log` 的 v1 返回 None |
| `stub_spec` / `run_stub` | `test_lifecycle.py:173-235` | cut-point stub |
| `two_install_harness` | `test_lifecycle.py:133-144` | Python + Node 双 install |
| `batch_reply` / `start_run` / `tool_effects` | `test_lifecycle.py:93-151` | scripted model batch、effect 查询 |
| `ZeroSpawn` | `test_lifecycle.py:72-90` | 零 spawn sentinel |
| `HostCrash` | `v24/host/worker.py` | 测试注入 |
| `HostJournal` | `v24/host/journal.py` | `prepared_without_dispatch` / `pending_settlements` / `unfinished_dispatches` |
| B0 golden | `v24/b0/golden/provider_requests_v1.json`、`tool_messages_v1.json` | v1 字节 |
| s6 crash pattern | `v24/s6/test_g5.py`、`v24/s6/crash_worker.py` | 子进程/DSN/READY 风格参考（W7 不复制 kernel 逻辑） |

### 4.6 计划编写与 v3 修订时的临时探针（不作为验收证据）

2026-11-01 在 `/tmp` 写了若干一次性脚本，确认以下行为可测：

| 探针 | 观察 |
|---|---|
| 现有 `test_lifecycle.py` | 通过，marker `cases=14` |
| tool `effect_prepared` 后注入 | 重启 `_resume_prepared` 执行一次；`invoke` spawn 1；settlement 1；run completed |
| tool `dispatch_started` 后 `crash_after=started` | lease live 时 `skipped`；过期后 `recovered=1`；effect unknown；run blocked；无 spawn |
| model `dispatch_finished` 后 `crash_after=finished` | `reconciled=1`；3 tool 全 success；model effect 2；continuation 1；provider call 1+1 |
| `host_prepare` `effect_prepared` 后注入 | 重启后 install `installed`；`prepare` spawn 1；无重复 prepare |
| `host_release` `effect_prepared` 后注入 | `off` 后 `dispose`；重启后 `disposed`；release spawn 1；无重复 release |
| mixed batch：read timeout + list/search success | 3 tool effect；read unknown；list/search success；run blocked；model call 1；spawn 2/3（**read 必须是最后执行**，见 v3 复核） |
| 磁盘 artifact 追加字节 | `artifact_digest_mismatch`；零 spawn |

这些探针说明 R01/R02/R04/R07/R08/R09/R11 的期望行为是当前代码可达到的；R03/R05/R06/R10/R12/R13 仍需实现后实测。

**v3 复核探针**（2026-11-01，`/tmp`，不作为 W7 pass 证据）：

- R07：`admit` 后 `preparing`/prepare spawn 0；注入 `host_prepare effect_prepared` 后崩溃；`h.run(None)` → `installed`/prepare spawn 1；再 `h.prepare([install])` 仍为 1。完整 lifecycle 的生成日志为 `{prepare:1, invoke:1, release:1}`。
- R09：read 最后执行时 list/search success、read unknown、run `blocked_unknown`、transport 1；read 最先执行时 list/search 仍 spawn 并写 `dispatch_finished` success，但 effect 停留 `claimed`、无 settlement。
- R14：`ApprovedAdapterRegistry((v1.entry, v2.entry))` 可用；`CountingSpawn(artifact=v1.entry.artifact_path)` 在 prepare 后 1、success 后 2、known-error 后 3；v1 success 的 B0 request1/2 与 tool message 逐字节相等（tool message 必须按 `parent_effect_id` 取）；v1 `--spawn-log` 不存在。
- R15：patched `db.settle` 后 3 个 tool 全 `claimed`、`h.run` 5 轮后 idle；in-process `_reconcile` 返回 3，tool settlement 从 0 到 3。fresh process 的 `w7_recover.py` 尚未实现，仍需实测。
- R16：tool effect 在崩溃前已 `succeeded`、journal settlement 为 0；in-process `_reconcile` 返回 0、tool settlement 从 0 到 1，payload `reason="database_terminal"`、`conflict=false`。fresh process 的 `w7_recover.py` 尚未实现，仍需实测。

这些复核只降低计划风险，不替代 `test_lifecycle.py` 的正式断言；R03/R05/R06/R10/R12/R13 以及 R14/R15/R16 的 fresh-process 版本仍需实现后实测。

**Oracle 评审后的修订**（这些探针不作为 W7 pass 证据）：

- R03 原计划的 500ms lease 不满足 spawn 门槛（read timeout=5000 → 需 ≥10000ms），改为 stub `timeout_ms=1000`、child `default_lease_ms=6500`。
- R14 原顺序（先跑完 known-error 再在 finish 后崩溃）拿不到 B0 request2；改为“success 完整跑 → known-error 在 `dispatch_finished` 后崩溃 → fresh reconcile → 父进程续跑出 request2”。
- R15/R16 是评审新增窗口；v2 计划编写时未做临时探针，v3 只做了 in-process `_reconcile` 复核，fresh-process `w7_recover.py` 仍需实现后实测。
- R02 lease 从 1000ms 提到 3000ms，避免第一次 restart 前已经过期。

**v4 复核探针**（2026-11-01，`/tmp` 与一次性 `uv run python`，不作为 W7 pass 证据）：

- `uuid.UUID(hashlib.md5(...).hexdigest())` 可用：`hexdigest()` 恒为 **32 位**小写十六进制，`uuid.UUID()` 接受 32 位无连字符形式；实测与按 `8-4-4-4-12` 切分后构造的 UUID **相等**（即与 PostgreSQL `md5(...)::uuid` 等价）。§7.1 #3 的原写法保留。
- `min({0: uuidA, 1: uuidB, 2: uuidC}, key=ids.get)` 返回的是**键**（ordinal），不是值（UUID）。把它直接传给 `inject_after(effect_id=...)` 时 `str(uuid) != str(0)`，命中条件恒假、注入永不触发。R10 因此改为先取 `target_ordinal` 再 `ids[target_ordinal]`（§17.2 A1）。

---

## 5. 决策记录

### D1 — W7 是 post-M5 recovery closure，不是 M4 重做

M4 已由 C.11 与 W4c 声明完成。W7 只补 W4c 记录中列出的三个缺口，不改变 design §10 的阶段表，不新增 M6，不重写 G12-A…H/L 的历史结论。W7 的完成声明只能是“恢复证据收口”，不能写成“M4 重新完成”。

### D2 — 扩展现有 `test_lifecycle.py`，不新建 gate 文件

理由：

1. design §7.1/§7.3 把 G12 映射到 `test_lifecycle.py`；恢复探针属于同一 G12 家族。
2. W6 的先例是扩展 `test_tools.py` 并改 marker，不是新建 gate。
3. 不增加第 33 条串行命令，32-command sweep 的形态、closeout 行号（14–24）与 M5 记录保持可比。
4. 现有 helper（`two_install_harness`、`run_stub`、`batch_reply`、`tool_effects`）可直接复用。

代价是文件会从 645 行涨到约 1,300–1,600 行；用清晰的小节（`# --- W7 R01 ...`）控制可读性。以加法为主：原有 case/helper 的行为与断言不变；允许 `stub_spec` 增加可选 `realm` 参数、`main()` 顺序与 marker 变化。

### D3 — cut-point 注入用测试侧 journal wrapper，不加生产 crash hook

对 K0（`effect_prepared` 之后、`dispatch_started` 之前）与 K3/K5（`dispatch_finished` 之后、settle 之前）用 post-append wrapper：

```python
def inject_after(harness, event_type, *, effect_id=None, kind=None, exc=HostCrash):
    original = harness.journal.append
    state = {"done": False}

    def restore():
        harness.journal.append = original

    def wrapper(event_type_, effect_id_, digest, payload, **kwargs):
        result = original(event_type_, effect_id_, digest, payload, **kwargs)
        matched = (not state["done"]
                   and event_type_ == event_type
                   and (effect_id is None or str(effect_id_) == str(effect_id))
                   and (kind is None or payload.get("kind") == kind))
        if matched:
            state["done"] = True
            restore()
            raise exc(f"injected after {event_type}")
        return result

    harness.journal.append = wrapper
    return restore
```

注入点在 append 返回后，精确模拟“journal 已 fsync、下一行未写”的崩溃。恢复时 `prepared_without_dispatch()` 会看到该 effect，`_resume_prepared` 重执行一次。`effect_id`/`kind` 至少给一个；R01/R07/R08 用 `kind` 区分 `tool_call`/`host_prepare`/`host_release`，R05/R10/R14 用 `effect_id` 精确命中一个 tool。

K3.5 另用 **pre-append** 的 `inject_before(harness, "settlement_committed", effect_id=target, kind="tool_call")`：命中时**不调用**原始 append 就抛 `HostCrash`，模拟“DB 已提交、journal 未写”。命中条件必须同时满足：`event_type_ == "settlement_committed"`、`str(effect_id_) == str(target)`、`payload["outcome"]["body"]["kind"] == "tool_call"`、`"response" in payload` 且 `"outcome" in payload`，并且 `payload.get("reconciled")` 为假、`"reason"` 与 `"conflict"` 不在 `payload` 里。最后三条用来排除 `_record_settlement` 的 `database_terminal`/`reconciled`/`claim_token_changed` payload，以及 model settlement 的 `kind="model_call"`。`inject_before` 也必须在命中后立即恢复，`hits` 必须恰为 1；未命中即 FAIL。

两种注入都必须是一次性（命中后自动恢复）并在 `finally` 里恢复原方法；未命中即 FAIL，不能静默通过。不把 `crash_after` 扩成 `"prepared"` 的生产分支：那会改变 host 行为，且 W7 不需要。

### D4 — 真实进程崩溃用 fork host child + stub `kill_parent`

R03 的步骤：

1. 父 gate 进程建好 harness，admit/prepare/activate，`start_run` 得到 `run_id`/`model_id`；此时**尚未 claim** 任何 tool effect，父进程不得先跑 worker，否则 6500ms lease 不在子进程生效。
2. 父进程按 `journal → db → owner` 关闭连接（与 `PluginHarness.close()` 的 `424-429` 同序），再 `os.fork()`。必须先关 journal：`HostJournal.open` 在 fd 上做 `flock(LOCK_EX|LOCK_NB)`（`journal.py:121-127`）；fork 后父子共享同一个 open file description，子进程再用同一路径 `HostJournal.open` 会看到锁被占（`JournalLocked`）。同时 psycopg2 连接不能跨 fork 共享 socket，父进程必须先把 `db`/`owner` 关掉。
3. fork 前调用 `assert_fork_safe(harness)`：`journal._fd == -1`；`db._closed is True` 且 `db.control.closed == 1`、`db.service.closed == 1`；`owner.closed == 1`；`all(conn.closed == 1 for conn in fixture._connections)`；`fixture._lock_conn` 仍非空且 `closed == 0`。除 registry/scope/run_id/DSN 字符串与这个测试库锁外，父进程不得持有任何可变连接。`fixture._lock_conn` 必须保留：`setup_db.cleanup()` 依赖它释放测试库锁（`setup_db.py:461-483`）；子进程继承 fd 但不使用它，SIGKILL 只关子进程副本，父进程的锁仍在。
4. 子进程分支**整体**包在 `try:` 里：`except BaseException: os._exit(1)`，正常结束也 `os._exit(0)`。`os._exit` 不展开栈、不跑 `finally`/`__exit__`/`atexit`，因此子进程不会替父进程关闭继承来的上下文管理器或连接。分支内：用继承的 `harness.fixture.role_dsn("admin"/"service")` 重开 `HostDB`，用 `PluginDispatcher(child_db, harness.registry)` 新建 dispatcher，重开 `HostJournal`，`child_adapter, _transport = model_adapter(script)`（`model_adapter` 返回 `(adapter, transport)` 元组，不能直接当 adapter 传），再新建 `HostWorker(default_lease_ms=6500, adapter=child_adapter)`，再 `run_until_idle`。claim 必须由子进程执行，`default_lease_ms=6500` 才会写进 tool effect 的 `lease_until`；`_lease_for` 对 tool/resource 返回 `default_lease_ms`，对 model 返回 adapter lease（`worker.py:919-922`）。插件的 `kill_parent` scenario 在 append spawn log 后 `os.kill(os.getppid(), SIGKILL)`；被杀的是 host child（plugin 的父进程），不是 gate 父进程。
5. 父进程 `waitpid(child_pid, WNOHANG)` 轮询（30s deadline），断言 `WIFSIGNALED` 且 `WTERMSIG==SIGKILL`。用 `reaped` 标志记录该 pid 是否已被回收：同一 pid 只允许成功 `waitpid` 一次，后续清理先看 `reaped`，避免第二次 `waitpid` 的 `ECHILD` 掩盖原始失败。超时或断言失败时用 **`os.kill(child_pid, SIGKILL)`**——**不能** `killpg(child_pid)`：`fork()` 出的 child 不是进程组 leader，它的 pgid 仍是父测试进程的 pgid，`killpg(child_pid)` 要么 `ESRCH` 静默失败（child 继续存活），要么误杀 pgid 恰好等于该 pid 的无关进程组——然后再 `waitpid` 收尸并置 `reaped=True`。插件仍按 spawn log 的 pid `killpg`（插件由 `process_io` 以 `start_new_session=True` 启动，pid == pgid），再用只观察的 `assert_no_live`。
6. 父进程重开 DB/journal（`reopen_harness`），轮询 `host_effect(effect_id)["lease_until"]` 到 `remaining <= 0`（上限 lease+2s），再 `h.run(None)`；断言 effect unknown、run blocked、`invoke` 行仍 1、DB `effect_recovered_unknown` 恰 1。

选择 fork 而不是独立 driver + spec JSON：registry/scope/run_id 已经在内存里，fork 后子进程直接继承，避免序列化 `ApprovedPlugin` 与重建 fixture；DB 连接在 fork 前关闭，子进程全部重开，不共享 psycopg2 socket。

### D5 — 用短 lease 触发过期，不用 owner DML/时钟 seam

测试在 claim 前设置 `worker.default_lease_ms`。`_lease_for` 只对 tool/resource 用它；model claim 用 `DeepSeekAdapter.lease_ms(adapter.timeout_s)`（`worker.py:919-922`），所以 R02/R03 的 model effect 不会因短 lease 被提前回收：

- **R02 用 3000ms**，保证第一次 restart 时 lease 仍 live，随后过期；R02 工具不 spawn，不受 spawn 门槛影响。
- **R03 用 6500ms**。这里必须先过 `plugins.py:173` 的 spawn 门槛：`remaining >= tool.timeout_ms + 5000`。stub `timeout_ms=1000` → 需要 ≥6000ms；6500ms 只留 **500ms 余量**，是本计划里最紧的一处时序。子进程 claim 后立即 spawn，中间不插入其它 IO；若 CI 抖动导致 `remaining < 6000`，测试 **FAIL** 并把实际 `remaining` 写进失败信息，**不得**把 lease 调到 30s 规避——那只是把余量换成墙钟，同时掩盖门槛本身。

崩溃后轮询 `host_effect(effect_id)["lease_until"]` 的 `remaining_lease_ms`，上限为 **lease + 2s**（R02 约 5s、R03 约 8.5s），每 50ms 检查一次，再让 recovery 看到 `remaining <= 0`。R02 的 effect_id 从 journal 唯一的 tool `dispatch_started` 取，R03 的 effect_id 从 child 写入的 `dispatch_started` 取；不直接 `UPDATE v24.effects SET lease_until=...`，也不改 host 时钟。

代价是 R02 约 3s、R03 约 6.5s；可接受。若 CI 抖动导致窗口不够，只能延长轮询到 lease+2s；**不得**把 lease 调到 30s 后 sleep，也不得把 R03 标 SKIP。

### D6 — 磁盘 tamper 测真实 artifact path；registry tamper 留给 G12-F

R11 直接操作 `spec.entry.artifact_path`，四个失败子探针严格按 `require_artifact` 的检查顺序排列（`registry.py:66-83`）：

| 子探针 | 变更 | 第一个失败检查 | reason |
|---:|---|---|---|
| 1 | `unlink` | `resolve(strict=True)` 抛 `FileNotFoundError` | `artifact_missing` |
| 2 | 换成指向 `/etc/hosts` 的 symlink | `commonpath(real_artifact, real_cwd) != real_cwd` | `artifact_outside_cwd` |
| 3 | 换成目录 | `stat` 后 `S_ISREG` 为假 | `artifact_not_regular` |
| 4 | 追加一个字节 | `sha256(read_bytes) != artifact_digest` | `artifact_digest_mismatch` |
| 5 | 恢复原始 bytes | 全部通过 | 下一次调用 success |

每个子探针后先把路径恢复成普通文件（必要时 `unlink`/`rmdir` 再 `write_bytes(original)`），再进下一个；第 5 个是恢复后的正向对照。G12-F 的内存 registry 篡改仍保留，作为“approval 对象被替换”的对照；W7 不重复它。

### D7 — legacy 只做 v1 字节 + v1 恢复，不改 v1

R14 复用 G12-L 的 B0 读取逻辑，但时序必须是 **先完整 success、再 known-error 崩溃续跑**：

- v1 与 v2 同 scope 共存：`v1 = build_spec("python", realm=realm, tool_key="echo.python", identity="v24.w7.legacy")`，`v2 = read_spec(..., realm=realm)`；`registry = ApprovedAdapterRegistry((v1.entry, v2.entry))`，再 `PluginHarness(fixture, registry, workdir, realm=realm)`。`build_registry(spec)` 只是单 spec 的便捷构造；union 必须显式传两个 entry（构造函数接受 `ApprovedAdapter`/`ApprovedPlugin` 混合，`registry.py:394-407`）。
- v1 success 完整跑 2 次 provider call，逐字节比对 B0 `request1/request2` 与 tool message。tool message 必须按 `parent_effect_id == v1_model_id` 取；union 中 v2 read 会先写一条 `tool_call`，不能取 journal 第一条。
- v1 known-error 只跑出 `request1`，在 tool `dispatch_finished` 后注入崩溃；fresh process `_reconcile` 只补 settlement（不再 invoke）；父进程续跑 `request2` 并逐字节比对 B0。
- v1 没有 `--spawn-log`（`plugin_fixtures.py:136` 的 argv 只有 interpreter + artifact），因此用 `CountingSpawn(artifact=v1.entry.artifact_path)` 过滤 `spec.argv[1]` 的真实路径（v1/v2 的 artifact 都在 argv[1]），包住 prepare + 两次 invoke = 3 次；`CountingSpawn` 同时解析 `spec.stdin` 的 `operation`，期望 `{"prepare": 1, "invoke": 2}`；恢复前后计数不变。v1 无 log 的证明链见 §8 R14。

不修改 `ApprovedAdapter`、`match_pin`、v1 parser、`canonical_json(output)`。

### D8 — DB receipt 与 journal receipt 的不对称要写进文档，不伪造事件

K1/K2 的 journal 只有 `dispatch_started`，没有 `dispatch_finished`；DB recovery 写 `effect_recovered_unknown`（`v24/sql/49_recovery.sql:95`），effect 状态 unknown。W7 断言：

- DB receipt：effect row 终态 + 恰一个 `effect_recovered_unknown` 事件。
- Journal：允许停在 `dispatch_started`；不要求、不伪造 `dispatch_finished`/`settlement_committed`。
- 对 K3（有 `dispatch_finished`）：journal `settlement_committed` 恰一个。
- 对 K3.5（DB terminal、journal 未写）：DB receipt 不变；journal 补写一个 `settlement_committed`，payload 为 `{"conflict": False, "reason": "database_terminal", "outcome": <dispatch_finished 的 outcome>}`（`worker.py:790-797`），`reconciled` 为 0；必须用 `settlements` 增量判定，不能用 `reconciled`。

这条不对称写进 README/execution record/ledger，避免后来者把“journal 少一条”误判成重复 receipt 或丢失 receipt。

### D9 — marker 与计数约定

```text
[passed] W4 lifecycle; cases=30; recovery_probes=16; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true; no_replay=true
```

- 保留 `W4 lifecycle` 前缀，避免破坏既有命令识别。
- `cases=30` = 现有 14 + R01–R16 各 1。现有 14 的构成是 A1+B1+C1+D3+E1+F3+G1+H1+L2；W7 按 case 函数计数，两种口径的差异在 §3/§9/§17 写明。
- R11 的 4 个 artifact 形状、R13 的 restart 阶段、R14 的 v1 success/known-error/crash 阶段、R15 的 3 个 pending、R16 的 settlement 补写，都算同一 case 的子探针，不单独加 `cases`。
- `recovery_probes=16` 固定。
- `journal_events_unchanged=true` 保留 G12-G 的集合断言，不能被 `no_replay=true` 取代。
- `no_replay=true` 由 §9 的 aggregate 断言产生。

### D10 — 生产代码零改动是默认，W7-8 是条件分支

计划预期只改：

- `v24/s13/test_lifecycle.py`
- `v24/s13/w4_stub_plugin.py`（test-only）
- `v24/s13/w7_recover.py`（新 test-only）
- 文档

如果某个 R 探针红，先判断是测试假设错还是 host 真缺陷。测试假设错 → 改测试/计划；host 真缺陷 → W7-8 做最小 host fix，并重跑全部证据。若修复需要 SQL/kernel/replay/design 变更 → **STOP**，另立设计修订，不在 W7 偷渡。

### D11 — Node 缺失 SKIP；fork 失败 FAIL

- Node 缺失：沿用现有行为，`[SKIP] W4 lifecycle; node_missing`，exit 2，不算通过。
- `os.fork()`/`waitpid` 不可用或子进程没有按预期被 SIGKILL：**FAIL**，不转 SKIP。W7 的目标平台是当前 macOS/Linux 测试环境；不能用 SKIP 掩盖真实进程崩溃证据缺失。
- 插件孙进程清理失败：FAIL，不能留下 live 进程。

### D12 — 不引入长时间 sleep / 墙钟 gate

- 唯一固定等待是 lease 过期：R02 约 3s、R03 约 6.5s，轮询上限 lease+2s；其余 case 无固定 sleep。§10.5 给出每 case 预算表。
- timeout 用 300ms deadline（R13 用 1000ms 给孙进程启动留余量），不 sleep 12s。
- 不断言精确 wall-clock；只断言 bounded（例如 timeout case < 5s）。
- 不把 12 秒 search budget 拉进 W7。

---

## 6. 恢复窗口模型

| 窗口 | 崩溃点 | journal 最后状态 | DB 状态 | 重启动作 | 期望 spawn | 期望 receipt | run |
|---|---|---|---|---|---|---|---|
| **K0** | `effect_prepared` 后、`dispatch_started` 前（tool/resource） | `effect_prepared` | claimed | `_resume_prepared` 重执行一次 | +1（原本未 spawn） | 1 | 继续 |
| **K1** | `dispatch_started` 后、handler 前（tool） | `dispatch_started` | claimed | live 时 block；过期后 `_recover` → `settle_unknown` | +0 | DB `effect_recovered_unknown` 1 | blocked_unknown |
| **K2** | 真实 spawn 后、`dispatch_finished` 前 | `dispatch_started` | claimed | live 时 block；过期后 `settle_unknown` | 崩溃的 1 次；恢复 +0 | DB 1 | blocked_unknown |
| **K3** | `dispatch_finished` 后、settle 前（tool/model） | `dispatch_finished` | claimed | `_reconcile` 用 journal outcome settle | +0 | journal settlement 1 | 继续 |
| **K3.5** | DB settle 成功、journal `settlement_committed` 未写（tool/model） | `dispatch_finished` | terminal | `_reconcile` 走 `database_terminal` 只补 journal settlement；`settled=0` | +0 | DB 不变；journal settlement 1 | 不变或继续 |
| **K4** | settlement 后 | `settlement_committed` | terminal | 无动作 | +0 | 不变 | 不变 |
| **K5** | model `dispatch_finished` 后、settle 前 | `dispatch_finished` | claimed | `_reconcile` settle model；DB 建 tool effects；继续执行 | model +0；tool 正常 | 崩溃的 model 1；continuation 另 1；tool 各 1 | 继续 |

语义边界：

- K0 是 **resume**，不是 replay：`dispatch_started` 未写，外部 IO 未发生；`_resume_prepared` 只在 claim token 未变且 lease 足够时执行。resource（`host_prepare`/`host_release`）的 `required=0`，只要 `remaining > 0` 就重执行；tool 也是 `required=0`；model 的 `required=adapter.timeout_s*1000+5000`（`worker.py:734-741`）。R07/R08 用默认 30000ms lease，不得缩短。
- K1/K2 是 **no_replay**：`dispatch_started` 已写，host 无法证明外部副作用未发生；DB 只能 `settle_unknown`。K1 甚至没有 spawn，但保守判 unknown 是 design C.14 的已知限制。`_recover` 走 `db.recover`（`worker.py:852-860`），journal 不补 settlement。
- K3/K5 是 **journal replay**：`dispatch_finished` 已写，outcome 是可信的；重交不调用 handler/provider，不产生第二 receipt。
- K3.5 是 **journal settlement 补写**，不是 replay：DB 已 terminal，`_reconcile` 只补 `settlement_committed`，不能再 settle；`reconciled` 可能为 0，必须用 journal settlement 增量判定。
- K4 是 **idempotent no-op**：第二次 `_reconcile` 返回 0。
- **blocked 兄弟 effect（R09 的边界）**：`db.claim` 只检查 effect kind/status，不检查 run status（`30_advance.sql:583-585`）；一旦某个 tool 以 unknown 先 settle，run 被置为 `blocked_unknown`（`48_loop.sql:1438`），同 batch 仍 `ready` 的兄弟仍会被 claim/spawn，但其 `db.settle` 返回 `blocked_unknown`（`48_loop.sql:1359-1360`），effect 停留 `claimed` 且无 journal settlement。这不是 W7 要修的行为；R09 通过把 read 放到最后来避免它，并在 §8 写明。

---

## 7. 组件设计

### 7.1 `v24/s13/test_lifecycle.py`（改，以加法为主）

新增 helper（放在现有 helper 之后，避免改动已有函数）：

1. `class CountingSpawn(artifact=None, expected=None)`：包装 `line_json.run_process`；若给 `artifact`，只计数 `len(spec.argv) > 1 and os.path.realpath(spec.argv[1]) == os.path.realpath(artifact)` 的调用，其它调用委托但不计数。每次命中把 `json.loads(spec.stdin)["operation"]` 记入 `ops`；`__exit__` 恢复原函数并断言 `len(calls) == expected`（若给）与 `ops` 的分布。用于 v1（无 spawn log）与 R01/R05/R07/R08/R13/R14。
2. `def spawn_ops(harness, install_id) -> dict[str, int]`：解析 spawn log 的 `<pid> <operation>` 行，按 operation 计数（`prepare`/`invoke`/`release`/`inspect`）；v1 无 log，返回 0/空 dict 时不得与 `CountingSpawn` 混用。
3. `def tool_effect_id(model_id, ordinal) -> uuid.UUID`：`uuid.UUID(hashlib.md5(f"{model_id}:tool_call:{ordinal}".encode()).hexdigest())`，与 `v24.tool_effect_id`（`48_loop.sql:45-47`）一致；`def tool_order(model_id, n=3)` 返回按该 UUID 升序的 ordinal 列表。R09 用 `order = tool_order(model_id, 3)` 取执行顺序；R10 用 `target_ordinal = tool_order(model_id, 3)[0]`、`target = T(model_id, target_ordinal)` 取执行顺序第一的 tool；R16 只有一个 tool，直接用 `T(model_id, 0)`。不能假设 ordinal 顺序等于执行顺序。
4. `def reopen_harness(harness)`：新建 `HostJournal.open(workdir/"plugin-journal.jsonl")`、`HostDB(fixture.role_dsn("admin"), fixture.role_dsn("service"))`、`_owner(fixture.connect())`、`PluginDispatcher(db, harness.registry)`、`HostWorker(db, journal, tool_handler=..., resource_handler=...)`，替换 `harness.journal/db/owner/dispatcher/worker`；复用同一 registry/scope。打开顺序 owner → db → journal → worker。
5. `def close_connections(harness)` / `def open_connections(harness)`：fork/重建前后的连接管理。关闭顺序是 journal → db → owner（与 `PluginHarness.close()` 的 424-429 一致）；**不关闭** `fixture._lock_conn`（它持有测试库锁）；子进程只重开自己需要的连接，继承的 psycopg2 连接不得使用。调用方**仅限** R03 fork 前、R06 restart 前与 `run_recover_process` 内部；只禁止 R05/R14/R15/R16 的 fresh-process recovery action 再调（它们直接调 `run_recover_process`，由后者独占关闭责任）。`reopen_harness` 自己**不负责关闭**：它只重开连接，调用方必须先关闭（R06 显式调 `close_connections`；R03 在 fork 前已关；R05/R14/R15/R16 由 `run_recover_process` 内部关）。
6. `def assert_fork_safe(harness)`：`journal._fd == -1`；`db._closed is True` 且 `db.control.closed == 1`、`db.service.closed == 1`；`owner.closed == 1`；`all(conn.closed == 1 for conn in fixture._connections)`；`fixture._lock_conn` 非空且 `closed == 0`。除 registry/scope/run_id/DSN 字符串与该测试库锁外，父进程不得持有可变连接。
7. `def inject_after(harness, event_type, *, effect_id=None, kind=None, exc=HostCrash)`：D3 的 post-append journal wrapper，一次性，返回 restore 函数；`effect_id`/`kind` 至少给一个。
8. `def inject_before(harness, event_type, *, effect_id=None, kind=None, exc=HostCrash, hits=None)`：K3.5 的 pre-append wrapper；命中时只抛异常、不写 journal；若给 `hits` 列表则 `hits.append(effect_id_)`，供 R16 断言一次性命中。R16 用 `effect_id=target` + `kind="tool_call"` + `payload` 的 `outcome.body.kind`/`response` 过滤，排除 `_record_settlement`。
9. `def install_crash_after_started(worker) -> tuple[restore, original]`：保存 `original = worker._execute_tool`（bound method），在 wrapper 调用原函数前设 `worker.crash_after="started"`，`finally` 里把 `crash_after` 置回 `None`；restore 把 `original` **重新赋值**给 `worker._execute_tool`（`worker._execute_tool = original`）；helper 返回 `(restore, original)`。**不能**用 `del worker._execute_tool`：`_execute_tool` 是类方法（`worker.py:1027`），`del` 只会退回类属性，之后每次属性访问都会新建一个 bound method，R02 第 3 步的 `harness.worker._execute_tool is original` 恒为 False。调用者也**不得**自己再取一次 `worker._execute_tool` 当 `original`——两次属性访问得到的是不同 bound method，`is` 同样不成立；必须使用 helper 返回的对象。只用于 R02（全局设 `started` 会让 model 先崩）。
10. `def assert_single_receipt(harness, effect_id, *, journal_finish, db_recovery=False, snapshot=None)`：**不**用“effect row 恰 1 行”（主键同义反复）。断言 effect 是 terminal（`succeeded`/`failed`/`unknown`/`cancelled`）、`settled_at` 非空；若给 `snapshot`，逐项比 `attempt_no`/`fence`/`settled_at`。正常 settle 不要求 effect-level event；`db_recovery=True` 时 `v24.events` 的 `effect_recovered_unknown` 恰 1，payload `action="settle_unknown"`、`reason="lease_expired"`（与 #15 的 I2 是同一判定，此处只针对单个 effect）。`journal_finish=True` 时 `dispatch_finished` 恰 1 且 `settlement_count(effect_id)==1`；第二次 `_reconcile` 返回 0（K3.5 的第一次也可能 0，用 settlement 增量）。
11. `def capture_effect(harness, effect_id) -> dict`：保存 status/outcome/settled_at/attempt_no/fence，用于 K4/K3.5 不变断言。
12. `def run_recover_process(harness, scope) -> tuple[int, int]`：先 `close_connections(harness)`（journal 释放 flock），再 `subprocess.run([sys.executable, str(HERE / "w7_recover.py"), str(harness.workdir / "plugin-journal.jsonl"), str(scope)], env={**os.environ, "V24_W7_ADMIN_DSN": ... , "V24_W7_SERVICE_DSN": ...}, timeout=30)`；解析 `[w7-recover] reconciled=N settlements=M`，断言 exit 0；返回 `(N, M)` 由 case 判定期望。**调用者不得再重复 `close_connections`**：本 helper 独占 journal→db→owner 的关闭责任（重复 close 虽幂等，但会把关闭点分散到四个 case）；R05/R14/R15/R16 的 recovery action 只恢复自己的 patch/快照，然后直接调用本 helper。
13. `def assert_no_live(pid, timeout_s=2.0)`：**只观察，不发任何信号**。用 `ps -o stat= -p <pid>` 轮询，空或 `Z` 视为已退出；超时即 FAIL。函数内不得 `kill`/`killpg`/`waitpid`：若它在 `finally` 里清理，R13 先检查插件 pid 时会顺带杀死同组孙进程，随后检查孙进程必然通过——这是假阳性。清理只由 R13 的 case 最外层 `finally` 做；R03 的测试侧 `killpg` 在 `assert_no_live` 之前（见 §9 I6）。
14. `def settlement_count(harness, effect_id=None) -> int`：统计 journal 中 `settlement_committed` 的数量，可按 effect 过滤；R15/R16 用它做增量断言。
15. `def assert_w7_invariants(harness, *, recovered_unknown=frozenset())`：§9 的 aggregate 断言（I1 `no_replay`、I2 DB receipt、I3 journal receipt、I4 spawn 双证、I5 无重复 spawn/rerender 的聚合部分），**scope 级、不带 `run_id`**。effect 枚举：先 `harness.db.host_runs(harness.scope)` 逐页取 scope 内全部 run（`host_runs` 不按状态过滤，`49_host_reads.sql:76-127`），再对每个 run 调 `harness.db.host_run_effects(run_id)` 取其全部 effect（该读**不**按状态过滤，只含 `model_call`/`tool_call`，`49_host_reads.sql:264-266`），筛 `kind == "tool_call"`；两级读都按 `has_more`/`next_cursor` 翻页，不写死 64（实际每个 case ≤ 5 run、≤ 3 tool effect）。`recovered_unknown` 是期望出现 `effect_recovered_unknown` 的 effect_id 集合（元素可以是 `uuid.UUID` 或字符串），默认空。helper 入口先 `expected = {str(item) for item in recovered_unknown}`；枚举得到的每个 effect 用 `key = str(effect["effect_id"])`；成员判断一律用**规范字符串**（`key in expected`），**不能**写 `effect_id in recovered_unknown`——R02/R03 传 `{target}` 时 `target` 是 `uuid.UUID`，而枚举出的 `effect_id` 是字符串，直接比较恒为 False。对每个 tool effect，若 `key in expected`，断言 `v24.events`（`entity_type='effect'`、`entity_id=<effect_id>`、`event_kind='effect_recovered_unknown'`）恰 1 条且 payload `action="settle_unknown"`、`reason="lease_expired"`；否则断言 0 条（run 级的 `tool_call_unknown`/`run_blocked_unknown` 不计入）。I4 的 install 枚举同样在 helper 内：用 `harness.db.host_scope_installs(harness.scope, None, 64)` 按 `has_more`/`next_cursor` 翻页取全部 install（`db.py:159-161`；`next_cursor` 形如 `{"install_id": ...}`，下一轮 `after = next_cursor["install_id"]`），再逐个 `install_spawn_log(harness, install_id)` 取 log；`install_spawn_log` 返回 `None` 的 install（R14 的 v1）跳过日志自洽部分，由 case 内 `CountingSpawn` 负责。helper 另外用单参 `harness.db.host_effects(harness.scope)` 断言 scope 内没有残留 `tool_call`（即没有 `ready`/`claimed` 的 tool effect）；**不能**只靠它枚举“全部 effect”：它只返回 `ready`/`claimed`（`49_host_reads.sql:184`），case 结束时已 settle 的 effect 全部不在结果里，枚举会退化为空集（见 §17.3 注）。每个 `rNN_*` 结束前调用一次，失败信息带 `scope`/`effect_id`；run 级断言（continuation 计数、model effect 计数）留在 case 内，不进 helper。

新增 case 函数：`r01_prepared_resume` … `r16_settlement_backfill`。每个函数只做一件事，失败信息带 effect_id/run_id/spawn_ops。

`main()` 的顺序：现有 G12-A…H → G12-L → R01…R16 → marker。R03 的 fork 放在 R01–R02 之后、R04 之前或最后都行，但必须保证它不会污染前一个 case 的 journal/连接；每个 case 用独立 `harness`/`base` 目录。`stub_spec` 增加 `realm=None` 参数并同步 scenario enum（`grandchild`/`kill_parent`），R09 用同一 realm 建 stub 与 Node。`main()` 必须按 `r01`…`r16` 顺序调用；fork 子进程不得执行父进程的 atexit。

### 7.2 `v24/s13/w4_stub_plugin.py`（改，test-only）

只加 scenario，不改现有分支：

- `grandchild`：`main()` 已先 `_append_spawn(spawn_log, "invoke")`；`_invoke` 里 `spawn_log = _spawn_log_path(sys.argv)`，`assert spawn_log is not None`，`child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])`（不传 `start_new_session`，让孙进程留在 plugin 的进程组里），`Path(f"{spawn_log}.child").write_text(str(child.pid), encoding="utf-8")`，`flush` 由 `write_text` 关闭保证，然后 `time.sleep(60)`。用于 R13 的进程组清理。
- `kill_parent`：`main()` 已先 append spawn log；`_invoke` 里 `os.kill(os.getppid(), signal.SIGKILL)`，然后 `time.sleep(5)`；不写 frame。用于 R03 的真实 host 崩溃。

约束：

- `_invoke(args)` 内部用 `_spawn_log_path(sys.argv)` 自取 log 路径，**不**改 `main()`/`_invoke` 签名；不得用 cwd 或源码树内的固定路径。
- 新增 `import signal`、`import subprocess`、`from pathlib import Path`；`SCENARIOS` 从 11 个值扩到 13 个（加 `grandchild`/`kill_parent`），只在 `_invoke` 增加两个分支；`test_lifecycle.py` 的 `stub_spec()` descriptor enum 也要加入同名值（11→13），并给 `stub_spec` 增加 `realm=None` 参数（R09 需要同 realm）。现有 `ok`/`timeout`/`bad_*` 行为不变。
- 测试侧读取 `.child` 时用轮询（最多 2s），文件未出现即 FAIL；不得把“孙进程没启动”当成已经清理。
- spawn log 仍只由显式 `--spawn-log` 写；生产 manifest 不含该 flag。
- 不新增 env/argv 开关；孙进程 pid 文件由 spawn log 路径派生，测试侧读取。
- `test_wiring.py` 使用 stub 的既有 scenario，必须保持绿。

### 7.3 `v24/s13/w7_recover.py`（新，test-only）

职责：一个独立 OS 进程，只做 journal→DB settlement，不构造 registry、不 spawn。它打开真实 `HostDB`（不是父进程的 patch 对象），`_reconcile` 的 handler 是 `os._exit(97)`，一旦误调 handler 就非零退出。

```python
"""W7 fresh-process recovery: reconcile journal outcomes, never call a tool."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v24.host.db import HostDB
from v24.host.journal import HostJournal
from v24.host.worker import HostWorker


def _settlements(journal) -> int:
    return sum(1 for item in journal.records
               if item["event_type"] == "settlement_committed")


def main() -> int:
    admin = os.environ["V24_W7_ADMIN_DSN"]
    service = os.environ["V24_W7_SERVICE_DSN"]
    journal_path, scope = sys.argv[1:3]
    journal = HostJournal.open(journal_path)
    db = None
    try:
        before = _settlements(journal)
        db = HostDB(admin, service)
        # _reconcile never calls a handler; if it ever does, exit loudly.
        worker = HostWorker(db, journal, tool_handler=lambda effect: os._exit(97))
        reconciled = worker._reconcile(scope)
        settlements = _settlements(journal) - before
        print(f"[w7-recover] reconciled={reconciled} settlements={settlements}")
        return 0 if reconciled + settlements >= 1 else 1
    finally:
        if db is not None:
            db.close()
        journal.close()


if __name__ == "__main__":
    raise SystemExit(main())
```

父测试通过 subprocess 启动：DSN 走 `V24_W7_ADMIN_DSN`/`V24_W7_SERVICE_DSN` 环境变量（不放在 argv，避免进程列表/日志泄漏），journal/scope 走 argv；父进程必须先 `journal.close()` 释放 flock。子进程退出 0 且 marker 匹配才算通过；子进程若调用 handler 会以 97 退出。

输出同时给出 `reconciled` 与 `settlements`：K3 类窗口看 `reconciled`，K3.5 看 `settlements`；R16 的 `reconciled=0` 不是失败。`HostDB` 构造失败时 `journal` 仍由 `finally` 关闭，避免下一个进程锁不上。`settlements` 是本次进程的 `after - before` 增量，不是 journal 累计条数。

### 7.4 Harness/连接复用

- `PluginHarness` 的 `db`/`journal`/`owner` 都是普通属性，可在测试内替换；不改 s11 源码。
- `reopen_harness` 用原 `harness.fixture.role_dsn("admin"/"service")` 与 `harness.workdir / "plugin-journal.jsonl"` 重开；registry 不变。
- `close_connections` 先 `journal.close()`，再 `db.close()`，再 `owner.close()`；顺序不能反，否则 journal 锁可能未释放。fork 前必须调用 `assert_fork_safe` 确认这三条都已关闭、`fixture._connections` 全部 closed，且没有其它 psycopg2 连接被带进子进程；`fixture._lock_conn` 必须保留，否则测试库锁会提前释放。调用点仅限 R03 fork 前、R06 restart 前与 `run_recover_process` 内部；`reopen_harness` 只重开，不负责关闭。
- `open_connections` 先 owner，再 db，再 journal，再 worker；与 `PluginHarness.__init__` 的顺序一致。
- fork 子进程只使用从父进程继承的 registry/scope/run_id/DSN 字符串；它继承 `fixture._lock_conn` 的 fd 但**不使用**，也不使用任何继承的 psycopg2/journal 连接；子进程自己重开 `HostDB`/`HostJournal`。子进程正常结束也走 `os._exit(0)`，不执行父进程的 atexit/连接清理。
- `waitpid` 用 `WNOHANG` 轮询，总 deadline 30s；超时就 `os.kill(child_pid, SIGKILL)` 再 `waitpid` 并 FAIL（**不** `killpg(child_pid)`，理由见 D4 第 5 步）。插件进程组用 spawn log 的 pid `killpg` 清理；同一 pid 只允许成功 `waitpid` 一次并用 `reaped` 记录，避免重复 `waitpid` 的 `ECHILD` 掩盖原始失败；清理失败只记录，不掩盖原始失败。
- 父进程在子进程退出后才重开 journal/DB；若子进程被 SIGKILL，flock 由内核释放，父进程重开不应看到 `JournalLocked`（出现即 FAIL）。父进程重开后先轮询 `host_effect(effect_id)["lease_until"]`，到 `remaining <= 0` 再 `h.run(None)`；不要在 lease live 时反复 `h.run(None)`，否则每轮只记 skipped。

### 7.5 Host/SQL/design 边界（不变）

W7 不修改：

- `v24/host/worker.py` 的 `_resume_prepared`/`_reconcile`/`_orphan_state`/`_recover` 顺序。
- `v24/host/registry.py` 的 artifact 检查。
- `v24/host/plugins.py` 的十三步顺序。
- `v24/sql/48_loop.sql` 的 `no_replay` successor。
- `v24/sql/49_recovery.sql` 的 `settle_unknown` 分支。
- `v24/s13/vectors/**` 的任何字节。

若 W7-8 需要 host fix，必须证明它不改变 v1 字节、不改 SQL、不改 design；否则 STOP。

---

## 8. 测试设计（R01–R16）

记号：

- `S(install)` = `spawn_ops(harness, install_id)`，按 `prepare`/`invoke`/`release`/`inspect` 计数。
- `E(effect_id, ...)` = `assert_single_receipt`；`Z` = `ZeroSpawn` + spawn log 行数不变。
- `C(n)` = `with CountingSpawn(expected=n) as c:` 包住该 case 的进程；只包 invoke 的 case 单独写明。下文 `c.calls`/`c.ops` 指这个对象。
- `T(model_id, i)` = `tool_effect_id(model_id, i)`（`48_loop.sql:45-47` 的 md5）。tool effect 的执行顺序是 `_order_key` 的 `(kind_class, effect_id)` 升序（`worker.py:884-888`），**不是** ordinal 顺序；需要“第几个执行”时用 `T` 计算；实际执行顺序由 journal 中 `dispatch_finished` 的记录顺序断言，不靠 `T` 自证。
- 所有 case 结束前断言该 run 的 tool effect `replay_policy == "no_replay"`；aggregate invariants 见 §9。

### R01 — tool `effect_prepared` 后崩溃，restart resume

**Setup**：`read_spec`，`open_harness`。`C(2)` 必须在 `admit` 之前进入；`admit` 不 spawn。`prepare([install])`（`prepare=1`），`activate(install, "read")`。

**Action**：

1. `run_id, model_id = start_run(harness, install_id, ["read"], "r01")`。
2. `target = T(model_id, 0)`；`restore = inject_after(harness, "effect_prepared", effect_id=target, kind="tool_call")`。
3. `try: harness.run([batch_reply([("call_read", "read", {"path": "tail"})])], max_rounds=20) except HostCrash: pass`；`finally: restore()`。
4. 断言崩溃后：`host_effect(target)` 是 `claimed`；journal 最后一条是 `effect_prepared`，没有 `dispatch_started`；`S(install).get("invoke", 0) == 0`、`prepare == 1`。
5. `harness.run([final_reply("r01-final")], max_rounds=20)`。

**Assert**：

- 恢复后 `target` 是 `succeeded`；journal 的 `dispatch_started`/`dispatch_finished`/`settlement_committed` 各恰 1；run `completed`；`S(install)` 为 `{"prepare":1,"invoke":1}`。
- `C(2)`：`c.calls` 恰 2，`c.ops == {"prepare":1,"invoke":1}`；`E(target, journal_finish=True)`。

**`C(2)` 与 release 的顺序**：R01 **不**调用 `off`/`dispose`/`close_scope`；`finally: harness.close()` 只关 journal/db/owner（`plugin_fixtures.py:424-429`），不产生 `host_release`，所以 `C(2)` 不会被 teardown 改成 3。`C(2)` 在 `finally` 之前断言；若以后给 R01 加 dispose，必须先退出 `C`、再断言 release，并把期望改为 3，这是计划变更，不是测试内静默改数。

### R02 — tool `dispatch_started` 后崩溃（零 spawn），lease 过期 unknown

**Setup**：real `read`；`prepare`、`activate`；`harness.worker.default_lease_ms = 3000`。

**Action**：

1. `run_id, model_id = start_run(... ["read"] ...)`；`target = T(model_id, 0)`。
2. Helper 语义（第 3 步调用）：`install_crash_after_started(worker) -> tuple[restore, original]` 保存并返回 `original = worker._execute_tool`，在 wrapper 调用原函数前设 `crash_after="started"`，`finally` 把 `crash_after` 置回 `None` 并恢复 `_execute_tool`。**不能**在 worker 上全局设 `crash_after="started"`：同一 batch 的 model effect 先执行，会在 `_execute_model:985` 先崩，tool 根本不会走到 `:1048`。`original` 必须是 helper 的返回值，不能自己再取一次 `harness.worker._execute_tool`。
3. `restore, original = install_crash_after_started(harness.worker)`；用 `with ZeroSpawn() as zero:` 包住这次 `harness.run`：`try: harness.run([batch_reply([("call_read", "read", {"path": "tail"})])], max_rounds=20) except HostCrash: pass`；`finally: restore()`（恢复先于后续断言）；断言 `zero.calls == []`（tool 在 handler 前崩，model adapter 不 spawn）、`harness.worker.crash_after is None`、`harness.worker._execute_tool is original`（用 helper 返回的对象；restore 必须重新赋值 bound method，见 §7.1 #9）。
4. 从 journal 唯一的 tool `dispatch_started` 取 `effect_id`（不要用 `tool_effects`，它只扫 `dispatch_finished`）；断言 `str(effect_id) == str(target)`；断言 effect `claimed`、journal 无 `dispatch_finished`、`S(install).get("invoke", 0) == 0`。
5. 立即 `stats = harness.run(None, max_rounds=2)`；断言 `stats.skipped >= 1`、effect 仍 `claimed`、`_orphan_state` 的 live 分支生效。
6. 轮询 `host_effect(effect_id)["lease_until"]` 的 `remaining_lease_ms` 到 `<= 0`（上限 lease+2s，每 50ms）。
7. `harness.run(None, max_rounds=4)`；断言 effect `unknown`、run `blocked_unknown`、DB `effect_recovered_unknown` 恰 1（payload `action="settle_unknown"`、`reason="lease_expired"`）、journal 仍停在 `dispatch_started`、`S(install)["invoke"] == 0`。
8. `third = harness.run(None, max_rounds=2)`；断言无新 journal 记录、无新 settlement、`third.recovered == 0`。
9. `E(effect_id, journal_finish=False, db_recovery=True)`。

**Assert**：DB receipt 是唯一 receipt；`recovered` 只作辅助，不能替代 effect status/event。结束前 `assert_w7_invariants(harness, recovered_unknown={target})`。

### R03 — 真实 spawn 后 SIGKILL host，restart unknown

**Setup**：stub `kill_parent`，`timeout_ms=1000`；`prepare`、`activate`；`S(install)["prepare"] == 1`；`start_run`（batch 单 read `scenario=kill_parent`）；`target = T(model_id, 0)`（tool effect 此时还没创建，id 由 model_id 确定）。

**Action**：

1. `close_connections(harness)`（journal → db → owner）；`assert_fork_safe(harness)`。`fixture._lock_conn` 必须仍 open；`fixture._connections` 全部 closed；`db._closed`、`journal._fd == -1`、`owner.closed == 1`。除 registry/scope/run_id/DSN 字符串与测试库锁外，父进程不得持有可变连接。
2. `pid = os.fork()`。
3. 子进程：整个分支 `try: ... except BaseException: os._exit(1)`，正常结束 `os._exit(0)`（`os._exit` 不展开栈，不跑继承的 `finally`/`__exit__`/`atexit`/连接清理）。分支内：用 `fixture.role_dsn("admin"/"service")` 新建 `HostDB`；`HostJournal.open(workdir/"plugin-journal.jsonl")`；`PluginDispatcher(child_db, harness.registry)`；`child_adapter, _child_transport = model_adapter([batch])`；`HostWorker(child_db, child_journal, tool_handler=..., resource_handler=..., default_lease_ms=6500, adapter=child_adapter)`；`run_until_idle(harness.scope, max_rounds=4)`。claim 必须由子进程执行，6500ms 才会写进 tool effect 的 `lease_until`。
4. 插件 `kill_parent` 在 append spawn log 后杀 `os.getppid()`（host child），父 gate 进程不受影响。
5. 父进程 `waitpid(child_pid, WNOHANG)` 轮询 30s，用 `reaped` 标志记录是否已回收（同一 pid 只允许成功 `waitpid` 一次）；断言 `WIFSIGNALED` 且 `WTERMSIG == SIGKILL`。用 spawn log 的 plugin pid `killpg(SIGKILL)`，再 `assert_no_live(plugin_pid)`。整个 fork/wait 包在 `try/finally` 里：超时或断言失败时对 **child pid** 用 `os.kill(child_pid, SIGKILL)`（不能 `killpg(child_pid)`——fork 出的 child 不是进程组 leader，pgid 仍属于父测试进程），对**插件**用 `killpg(plugin_pid, SIGKILL)`；然后 `waitpid` 收尸并置 `reaped`，不留下 live 进程，也不因重复 `waitpid` 的 `ECHILD` 覆盖原始失败。这里先杀组再 `assert_no_live`，是**测试侧清理**：它只证明测试侧清理干净，不证明 host 会自动清理插件/孙进程；host 自动组杀的唯一证据是 R13 的 timeout 路径（`process_io._kill_group`）。
6. `reopen_harness(harness)`；轮询 `target` 的 `lease_until` 到 `<= 0`（上限 lease+2s）；`harness.run(None, max_rounds=4)`。

**Assert**：

- `S(install)` 的 `prepare=1`、`invoke=1`；spawn log 恰 1 条 `invoke`。
- 恢复后 effect `unknown`；run `blocked_unknown`；DB `effect_recovered_unknown` 恰 1；`invoke` 仍 1；`S` 的 `prepare=1`；插件 pid 无 live 残留（`ps -o stat=` 空或 `Z`）。
- `E(target, journal_finish=False, db_recovery=True)`；第二次 `_reconcile` 返回 0。结束前 `assert_w7_invariants(harness, recovered_unknown={target})`。

**门槛说明**：`plugins.py:173` 是 `remaining < tool.timeout_ms + 5000` 拒绝；`timeout_ms=1000` 需要 `remaining >= 6000`。6500ms 才允许 spawn；若 lease 设 500ms，`kill_parent` 根本不会执行。

### R04 — model `dispatch_finished` 后崩溃，journal replay + 三 tool

**Setup**：`two_install_harness`（Python read + Node list/search）；`start_run`；`worker.crash_after = "finished"`（此时第一个 effect 是 model，安全；不要用在 R05 的 tool 上）。

**Action**：

1. `try: harness.run([batch_reply([read,list,search])], max_rounds=30) except HostCrash: pass`；保存 `first_calls = len(harness._transport.calls)`（应为 1）；`worker.crash_after = None`。
2. 断言崩溃后：0 个 tool effect；model effect `claimed`；journal 有 model `dispatch_finished`、无 settlement。
3. `stats = harness.run([final_reply("r04-final")], max_rounds=30)`。

**Assert**：

- `stats.reconciled >= 1`；`first_calls == 1`，第二段 `len(harness._transport.calls) == 1`（共 2 calls）；model effect 恰 2（initial + continuation）；continuation 恰 1；没有第二次 initial request（不是“无 rerender”：崩溃在 model 阶段，此时还没有 tool message）。
- 三个 tool 全 `success`；`S(read)` 为 `{"prepare":1,"invoke":1}`，`S(node)` 为 `{"prepare":1,"invoke":2}`；run `completed`；每个 tool `E(..., journal_finish=True)`。
- R04 同时覆盖 K3（model finish）与 K5（model 后建 tool effect）。

### R05 — tool `dispatch_finished` 后崩溃，fresh process reconcile

**Setup**：real `read`；`C(2)` 在 `admit` 前进入；`prepare`、`activate`；`start_run`；`target = T(model_id, 0)`。

**Action**：

1. `restore = inject_after(harness, "dispatch_finished", effect_id=target, kind="tool_call")`；`try: harness.run([batch_reply([("call_read","read",{"path":"tail"})])], max_rounds=20) except HostCrash: pass`；`finally: restore()`。
2. 断言 effect `claimed`；journal `dispatch_finished` 恰 1；`settlement_count(target) == 0`；`S(install)["invoke"] == 1`。
3. `reconciled, settlements = run_recover_process(harness, harness.scope)`；断言 `reconciled >= 1`、`settlements == 1`，子进程 exit 0。`w7_recover.py` 的 tool handler 是 `os._exit(97)`，若被调用会非零退出。
4. `reopen_harness(harness)`；`harness.run([final_reply("r05-final")], max_rounds=20)`。

**Assert**：

- 主证据不是 `reconciled` 而是：spawn log 不增长、journal 只新增 1 条 `settlement_committed`、effect row 的终态与 `dispatch_finished` payload 的 outcome 一致。
- 恢复后 effect `success`；journal settlement 恰 1；`invoke` 仍 1；run `completed`；`C(2)` 的 `ops == {"prepare":1,"invoke":1}`；`E(target, journal_finish=True)`。
- R05 不 off/dispose/close_scope；`harness.close()` 不产生 release，`C(2)` 精确。

### R06 — settlement 后 restart no-op

**Setup**：real `read` + Node list/search；跑完三 tool + final；`capture_effect` 保存每个 tool effect 的 `status/outcome/settled_at/attempt_no/fence`；保存 `spawn_ops`、journal 记录数、run row。

**Action**：`close_connections(harness)`；`reopen_harness(harness)`；`stats = harness.run(None, max_rounds=4)`。

**Assert**：无新 effect、无新 spawn、无新 settlement；每个 effect 的快照逐项相等；`stats.reconciled == 0`；run row 仍 `completed`；journal 记录数不变。

### R07 — `host_prepare` `effect_prepared` 后崩溃，restart 完成 install + 全生命周期

**Setup**：real `read`；`admit(spec)`（install `preparing`，`host_prepare` effect ready）；`C(3)` 在 `admit` 前进入；**不缩短 lease**（默认 30000ms）。

**Action**：

1. `restore = inject_after(harness, "effect_prepared", kind="host_prepare")`；`try: harness.run(None, max_rounds=2) except HostCrash: pass`；`finally: restore()`。
2. 断言崩溃后：install `preparing`；`host_effect` 的 prepare effect `claimed`；journal 只有 `effect_prepared`、无 `dispatch_started`；`S(install).get("prepare", 0) == 0`。
3. 取 prepare effect：断言 `kind == "host_prepare"`、`status == "claimed"`、journal `effect_prepared` 的 claim 与 DB `attempt_no/fence/claim_owner` 相等；`remaining = harness.db.remaining_lease_ms(effect["lease_until"])`，断言 `remaining > 0`。
4. `harness.run(None, max_rounds=4)`；`_resume_prepared` 对 resource 的 `required=0`（`worker.py:734-741`），`remaining > 0` 即重执行；断言 install `installed`、`S(install)["prepare"] == 1`。
5. 先记下 `before = [e for e in harness.db.host_effects(harness.scope)["items"] if e["kind"] == "host_prepare"]`；`harness.prepare([install_id])` 再跑一次；`prepare` 内部先 `run(None)`（`plugin_fixtures.py:324-336`），但 install 已 `installed`，不得新增 prepare。断言 `S(install)["prepare"] == 1`、state 仍 `installed`，且 `len([e for e in harness.db.host_effects(harness.scope)["items"] if e["kind"] == "host_prepare"]) == len(before)`。`host_effects` 只返回 `ready`/`claimed` 的 effect（`49_host_reads.sql:183-184`），第 4 步完成后 prepare effect 已 settle、不在结果里，所以该计数应为 0；若 `h.prepare` 又建了一个 prepare effect，它会以 `ready` 出现、计数变成 1——这正是要拦的重复 prepare。R07 只有一个 install，不存在“允许其它 install 新增 prepare”的例外。
6. `activate(install_id, "read")`；`start_run`；`harness.run([batch_reply([read]), final_reply("r07-final")], max_rounds=30)`；run `completed`。
7. `teardown_two_install(harness, [install_id])`（off → dispose → `run(None)` → 断言 `disposed`/`disposed_at`/无未释放 slot → `close_scope`）。
8. 断言 `S(install)` 为 `{"prepare":1,"invoke":1,"release":1}`；`c.ops` 为 `{"prepare":1,"invoke":1,"release":1}`（clean lifecycle 无 `inspect`；本次临时探针实测为 3）。

**Assert**：prepare/read/release 各 `E(..., journal_finish=True)`；无重复 prepare/release；scope `closed_at` 非空。

### R08 — `host_release` `effect_prepared` 后崩溃，restart 完成 dispose

**Setup**：real `read`；`C(3)` 在 `admit` 前进入；`prepare`、`activate`；跑完 read+final；`off`；`dispose` → install `dispose_pending`，`host_release` effect ready。

**Action**：

1. 从 `host_effects` 取 `host_release` effect id；`restore = inject_after(harness, "effect_prepared", kind="host_release")`；`try: harness.run(None, max_rounds=2) except HostCrash: pass`；`finally: restore()`。
2. 断言崩溃后：install `dispose_pending`；release effect `claimed`；journal 只有 `effect_prepared`、无 `dispatch_started`；`S(install).get("release", 0) == 0`。
3. `harness.run(None, max_rounds=4)`；断言 install `disposed`、`S(install)["release"] == 1`；`close_scope`；`scope["closed_at"]` 非空。
4. 断言 `S(install)` 为 `{"prepare":1,"invoke":1,"release":1}`；`c.ops` 同上；无重复 release。

**Assert**：release `E(..., journal_finish=True)`；`dispose_pending` 是崩溃后的中间态，不是最终态。

### R09 — mixed batch：一个 timeout + 两个 success

**Setup**：stub timeout read（`stub_spec(..., realm=realm, timeout_ms=300)`）+ Node list/search（`node_spec(..., realm=realm)`）；**同一 realm**；`open_harness(fixture, [stub, node], ..., realm=realm)`；两个 install；`prepare`/`activate` 两者。

**Effect 创建与执行顺序**：

1. `start_run` 只创建 run + model effect；`model_id` 已知。
2. `harness.run([batch_reply(calls)])` 先执行 model；model `db.settle` 用 `v24.tool_effect_id(model_id, ordinal)` 创建 3 个 tool effect（`48_loop.sql:1114-1138`），`ordinal` 是 `calls` 列表下标。
3. worker 的 `_order_key` 按 `(klass, str(effect_id))` 排序（`worker.py:884-888`），每轮 `run_once` 只执行一个 ready effect；因此执行顺序是 **effect UUID 升序**，不是 ordinal 顺序。执行顺序由 §7.1 #3 的 `tool_order` 取得（第 4 步赋值）；helper 内部用 `sorted(ids, key=ids.get)`（UUID 对象排序），与 `_order_key` 的 `str(effect_id)` 字典序一致。
4. 让 read 最后执行：`order = tool_order(model_id, 3)`；`read_ord = order[-1]`；`calls = [None, None, None]`；把 read 放在 `calls[read_ord]`，list/search 放在另外两个 ordinal。3 个 UUID 互不相同且必然可排序，`order` 恒有 3 项、最大者一定存在，**不需要 skip 分支**；也**不需要** `assert order.index(read_ord) == 2` 这类同义 guard——`order[-1]` 的定义已经保证它在末位，断言恒真、没有证据价值。
5. list/search 先 settle success；此时 read 仍 ready/claimed，DB 的 `v_sibling` 为真，不建 continuation；read 最后 timeout → `unknown` → run `blocked_unknown`（`48_loop.sql:1438`），不建 continuation。

**Action**：`harness.run([batch_reply(calls)], max_rounds=30)`。

**Assert**：

- 3 个 tool effect：read `unknown` 且 error code `timeout`；list/search `success`；run `blocked_unknown`；`len(harness._transport.calls) == 1`（无第二个 model call）；model effect 1、continuation 0。
- journal 的 tool `dispatch_finished` 顺序等于 `order`（read 最后）；这是**实际记录顺序**的断言，读 journal 里 `dispatch_finished` 出现的先后、把 effect_id 映射回 ordinal 再与 `order` 比较，不是用 `order` 自证；`spawn_ops(stub)` 为 `{"prepare":1,"invoke":1}`，`spawn_ops(node)` 为 `{"prepare":1,"invoke":2}`。
- 每个 tool `E(..., journal_finish=True)`；restart `harness.run(None, max_rounds=2)` 无新 spawn/settlement，run 仍 `blocked_unknown`。
- 所有 tool `replay_policy == "no_replay"`（read 的 timeout 是正常 settle，不写 effect-level event，所以 `recovered_unknown` 为空集，`assert_w7_invariants` 省略该参数）。

**blocked 兄弟 effect（必须写明的负分支）**：如果 read 不是最后执行，read 的 unknown 会先把 run 置为 `blocked_unknown`；同 batch 仍 `ready` 的 list/search **仍会被同一 worker claim 并 spawn**，因为 `db.claim` 只检查 effect kind/status，不检查 run status（`30_advance.sql:583-585`）；但它们的 `db.settle` 会返回 `blocked_unknown`（`48_loop.sql:1359-1360`），`_settle` 返回 False，effect 停留 `claimed` 且 journal 无 settlement。R09 不采用这个顺序，也不对它断言 success；真正的证据是上面对**实际 `dispatch_finished` 顺序 == `order`** 的断言，顺序不符即 FAIL，防止计划退化成“应 success”的含糊断言。

### R10 — mixed batch：第一个 tool `dispatch_finished` 后崩溃，restart 完成剩余

**Setup**：`two_install_harness`；`start_run`；`target_ordinal = tool_order(model_id, 3)[0]`（**执行顺序第一**的 ordinal）；`target = T(model_id, target_ordinal)`（**执行顺序第一的 tool 的 UUID**）。`tool_order` 返回按 UUID 升序的 ordinal 列表，`[0]` 就是执行顺序第一；不要写成 `min(ids, key=ids.get)` 后直接把返回值当 `effect_id`——`min` 返回的是键（ordinal），`str(uuid) != str(0)`，注入永不命中。所有 effect 断言与注入都用 `target`，只有描述“第几个执行”时才用 `target_ordinal`。

**Action**：

1. `restore = inject_after(harness, "dispatch_finished", effect_id=target, kind="tool_call")`（`target` 是 UUID，不是 `target_ordinal`）；`try: harness.run([batch_reply([read,list,search])], max_rounds=30) except HostCrash: pass`；`finally: restore()`。
2. 断言崩溃时：`tool_effects(harness, model_id)` 恰 1（即 `target`，有 `dispatch_finished`）；`host_effects` 的 3 个 tool 里 `target` 是 `claimed`、另外 2 个是 `ready`（两个 ready 的 UUID 都大于 `target`，由 `tool_order` 的升序保证）；不是“3 个 pending”。
3. 保存 target 的 `dispatch_finished` payload 的 `tool_message.content`。
4. `stats = harness.run([final_reply("r10-final")], max_rounds=30)`。

**Assert**：

- `stats.reconciled >= 1`；`_reconcile` settle target；剩余两个首次执行；3 tool 全 `success`；run `completed`。
- model effect 2；continuation 1；`S(read)` 为 `{"prepare":1,"invoke":1}`，`S(node)` 为 `{"prepare":1,"invoke":2}`。
- 每个 tool `E(..., journal_finish=True)`；target 的 `dispatch_finished` tool_message 与保存值逐字节相等（不重渲染）；剩余两个是首次 render；无重复 receipt。

### R11 — 磁盘 artifact tamper 四形状 + 恢复

**Setup**：real `read`；`prepare`、`activate`；保存 `spec.entry.artifact_path` 的原始 bytes、路径、mode。

**Action**：严格按 `require_artifact` 的检查顺序做五个子探针（`registry.py:66-83`）；每个失败子探针用**新的 run**，失败后先把路径恢复成普通文件再进下一个：

| # | 变更 | 第一个失败检查 | reason | 期望 |
|---:|---|---|---|---|
| 1 | `unlink` | `resolve(strict=True)` | `artifact_missing` | `Z` |
| 2 | symlink 到 `/etc/hosts` | `commonpath` | `artifact_outside_cwd` | `Z` |
| 3 | 目录替换 | `stat` + `S_ISREG` | `artifact_not_regular` | `Z` |
| 4 | 追加一个字节 | digest | `artifact_digest_mismatch` | `Z` |
| 5 | 恢复原始 bytes | 全部通过 | — | `invoke=1`，success |

每个失败子探针：`start_run`；`with ZeroSpawn(): harness.run([batch_reply([read]), final_reply(...)], max_rounds=20)`；`effect["outcome"]["class"] == "failure"`；error code 精确；`E(effect_id, journal_finish=True)`；spawn log 行数不变。第 5 个：恢复 bytes；`start_run`；`harness.run(...)`；`effect.success`；`S(install)["invoke"] == 1`；`E`。

**Assert**：不修改 registry；四个失败形状的 reason 必须与上表一致，不能把顺序写成 digest→missing→not_regular→outside。

### R12 — workspace root 消失 + 恢复

**Setup**：real `read`；`prepare`、`activate`；保存 root 路径。**Action**：`os.rename(root, root+".bak")`；`start_run`；`with ZeroSpawn(): harness.run([batch_reply([read]), final_reply(...)])`；断言 code `workspace_unavailable`、`E(journal_finish=True)`、`Z`；`finally: os.rename(root+".bak", root)`；`start_run`；`harness.run(...)` success；`S(install)["invoke"] == 1`；`E`。

**Assert**：失败检查在 `plugins.py:158-163`（realpath 相等且 `isdir`），零 spawn；恢复后 success。

### R13 — timeout 进程组清理 + restart no replay

**Setup**：stub `grandchild`，`timeout_ms=1000`（给孙进程启动留余量）；`C(2)` 包住 `run_stub` 的 prepare+invoke。

**Action**（整个 Action 用 `try/finally` 包住；`assert_no_live` 只观察、不发信号；插件 pid 与孙进程 pid 两条断言都做完后，才由 case 最外层 `finally` 对插件进程组 `killpg`，再 `harness.close()`）：

1. `with CountingSpawn(expected=2) as c: harness, install_id, run_id, model_id, effect, spec = run_stub(fixture, base, "grandchild", {"path":"a.txt","scenario":"grandchild"}, timeout_ms=1000)`。
2. 轮询 `Path(str(spec.spawn_log) + ".child")` 最多 2s；文件未出现即 FAIL。读孙进程 pid；从 spawn log 最后一条取 plugin pid。
3. 按顺序 `assert_no_live(plugin_pid)`、`assert_no_live(child_pid)`；两者都只观察、不发信号。孙进程由插件 `Popen` 派生、没有 `start_new_session`，与插件同组，所以清理只需对插件进程组 `killpg(plugin_pid, SIGKILL)`；这一步由 case 最外层 `finally` 在两条断言之后执行，清理失败只记录，不掩盖 timeout 主断言。
4. `harness.run(None, max_rounds=2)`（restart no replay）。

**Assert**：

- effect `unknown` `timeout`；run `blocked_unknown`；`S(install)["invoke"] == 1`；`c.ops == {"prepare":1,"invoke":1}`；timeout 返回 < 5s。
- plugin/孙进程无 live（`ps -o stat=` 空或 `Z`）；restart 无新 spawn/settlement；effect 仍 `unknown`；`E(effect_id, journal_finish=True)`。`recovered_unknown` 为空集（timeout 是正常 settle，不写 effect-level event），`assert_w7_invariants(harness)` 省略参数。
- **ESRCH 语义**：两条 `assert_no_live` 都通过后，最外层 `finally` 的 `killpg(plugin_pid, SIGKILL)` 可能因进程组已不存在而抛 `ProcessLookupError`（`ESRCH`）；这视为**成功**（already_gone），不记失败。其它 errno 只记录到日志，不掩盖主断言。
- **证据链**：`.child` 证明孙进程启动过；测试在观察前不发任何信号；stub 与孙进程都 `sleep(60)`，远大于 2s 观察窗口；插件被 SIGKILL 不会连带杀死孙进程（孙进程被 reparent 后继续 sleep），因此孙进程在窗口内消失只能来自组级 kill。
- case 最外层 `finally` 的 `killpg` 在插件 pid 与孙进程 pid 两条 `assert_no_live` **之后**执行；`assert_no_live` 自身不发信号，所以先检查插件 pid 不会顺手杀死孙进程，孙进程的检查有真实证据价值。`finally` 的 killpg 不掩盖原始失败。

### R14 — v1/v2 同 scope 共存 + v1 崩溃恢复 + B0 字节

**Setup**：

- `realm = ...`；`v1 = build_spec("python", realm=realm, tool_key="echo.python", identity="v24.w7.legacy")`；`v2 = read_spec(base/"v2", portable.root, realm=realm)`。
- `registry = ApprovedAdapterRegistry((v1.entry, v2.entry))`；`PluginHarness(fixture, registry, workdir, realm=realm)`。`build_registry(spec)` 是单 spec 的便捷构造；union 必须显式传两个 entry；构造函数接受 `ApprovedAdapter`/`ApprovedPlugin` 混合（`registry.py:394-407`），要求 `canonical_key`/`adapter_id` 不冲突。
- `C(3, artifact=v1.entry.artifact_path)` 在 `admit` 前进入（`C(n, artifact=...)` 表示 `CountingSpawn(expected=n, artifact=...)`）；`admit`/`prepare`/`activate` 两者；v1 prepare 计 1。

**Action**：

1. v2 read 跑通（不计入 v1 计数）：`start_run` on v2；`harness.run([batch_reply([read]), final_reply(...)])`；success。
2. v1 success：`run_id, v1_mid = start_run(harness, v1_id, ["echo.python"], "B0 fixed echo")`；脚本为 `tool_reply("call_b0_success", "echo.python", {"text":"snow 雪","zero":0}, reasoning="B0 fixed", usage=(17,9), response_id="resp_b0_success")` + `final_reply("B0 final", reasoning="B0 done", usage=(22,3), response_id="final_b0_success")`；`harness.run(..., max_rounds=30)`；transport 恰 2 calls；逐字节比对 B0 `provider.success.request1/request2`；v1 tool message 按 `parent_effect_id == v1_mid` 取，比对 `tool_message.success.content`；effect success。
3. v1 known-error：`run2, v1_mid2 = start_run(...)`；`target = T(v1_mid2, 0)`；`restore = inject_after(harness, "dispatch_finished", effect_id=target, kind="tool_call")`；`try: harness.run([tool_reply("call_b0_known_error", "echo.python", {"__tool_error__": True}, reasoning="B0 fixed", usage=(17,9), response_id="resp_b0_known_error")], max_rounds=20) except HostCrash: pass`；`finally: restore()`；transport 恰 1 call，比对 B0 `provider.known_error.request1`；journal 有 `dispatch_finished`、无 settlement；effect `claimed`；tool message 比对 `tool_message.known_error.content`（按 `parent_effect_id == v1_mid2` 取）。
4. `reconciled, settlements = run_recover_process(harness, harness.scope)`；断言 exit 0、`reconciled >= 1`、`settlements == 1`；`reopen_harness(harness)`。
5. `harness.run([final_reply("B0 final", reasoning="B0 done", usage=(22,3), response_id="final_b0_known_error")], max_rounds=20)`；transport 恰 1 call，逐字节比对 B0 `provider.known_error.request2`；run `completed`；continuation 恰 1；tool message 仍等于 B0。
6. `c.calls` 恰 3、`c.ops == {"prepare":1,"invoke":2}`；v1 `"--spawn-log" not in v1.entry.argv`；`install_spawn_log(harness, v1_id) is None`；`spawn_count(harness, v1_id) == 0`。证明链：`build_adapter` 只写 `argv=(interpreter, artifact)`（`plugin_fixtures.py:136`）→ `install_spawn_log` 找不到 `--spawn-log` 返回 None（`fixtures.py:436-447`）→ `spawn_count` 返回 0（`fixtures.py:450-453`）→ v1 只能用 `CountingSpawn` 计进程。
7. 再跑一次 v2 read success；v1 tool effect `replay_policy == "no_replay"`；v1 success/known-error 各 `E(..., journal_finish=True)`；v2 read `E`。

**Assert**：

- v1 success/known-error 的 provider request 与 tool message 逐字节等于 B0；v1 进程计数 = 3，恢复后不增；无第二次 spawn。
- v1 崩溃恢复：无第二次 spawn；`settlement_committed` 恰 1；effect terminal；run `completed`。
- v2 同 scope 的 read 前后都 success；无 v1 生产代码改动；不给 v1 加 `--spawn-log`。
- R14 不 off/dispose/close_scope；`C(3)` 在 `finally` 前断言，release 不在 C 作用域内。

### R15 — 三个 pending settlement，fresh process reconcile

**Setup**：`two_install_harness`；`start_run`；`targets = [T(model_id, i) for i in range(3)]`；`original = harness.db.settle`。

**Patch**：

```python
calls = []
def patched(effect_id, class_name, claim, kind, result):
    if kind == "tool_call":
        calls.append(effect_id)
        return {"error": {"code": "w7_injected_settle_error"}}
    return original(effect_id, class_name, claim, kind, result)

harness.db.settle = patched
```

- 返回形状必须是 `{"error": {"code": ...}}`，`is_error` 才识别（`db.py:244-245`）。
- `_settle` 先 `db.settle`（`worker.py:1278`），再 `db.assert_all_idle()`（`:1279`），然后 `is_error`（`:1282-1285`）。patched settle 不碰连接，所以 `assert_all_idle` **仍会跑并通过**；`_settle` 返回 False，effect 保持 `claimed`，不写 journal settlement。
- patch 只作用于父 `harness.db`；fresh process 用真实 `HostDB`，不受影响。

**Action**：

整个 Action 用 `try/finally` 保证 `harness.db.settle = original`；`close_connections` 不在 case 内调用——`run_recover_process`（§7.1 #12）内部先关 journal→db→owner。不能把 patch 留到 fresh process 或下一个 case。

1. `stats = harness.run([batch_reply([read,list,search])], max_rounds=30)`；断言 `stats.idle is True`。
2. 断言 3 个 tool effect 都是 `claimed`；每个都有 `dispatch_finished`；对每个 `target in targets`，`settlement_count(target) == 0`；`S(read)` 为 `{"prepare":1,"invoke":1}`，`S(node)` 为 `{"prepare":1,"invoke":2}`；run 仍 `running`。
3. 恢复 `harness.db.settle = original`；`reconciled, settlements = run_recover_process(harness, harness.scope)`；断言 `reconciled == 3`、`settlements == 3`、exit 0；spawn log 不变。
4. `reopen_harness(harness)`；断言 3 个 tool effect 都 terminal、每个 `target in targets` 的 settlement 恰 1；`harness.run([final_reply("r15-final")], max_rounds=30)`。

**为什么 `h.run` 会终止**：3 个 effect 都是 `claimed`，`_reconcile` 每轮重试 `db.settle` 但 patched 返回 error、`settled=0`；`_resume_prepared` 没有 `prepared_without_dispatch`；`_orphan_state` 没有 `unfinished_dispatches`（三个都有 `dispatch_finished`）；`_discover_ready` 为空；`run_once` 的 `progress==0`，`run_until_idle` 置 `idle=True` 返回。临时探针实测 5 轮后 idle。

**为什么 `reconciled=3`**：fresh `_reconcile` 遍历 `pending_settlements()`（`journal.py:290-302`）的三个 effect；每个 `status="claimed"`、journal claim token 与 DB `attempt_no/fence/claim_owner` 相等（`worker.py:768-772`）；`db.settle` 成功、`_record_settlement`、`settled += 1`（`:780-789`）。第三个 settle 后没有 live sibling，DB 建 continuation。

**Assert**：`h.run([final])` 后 run `completed`、model effect 2、continuation 1、无 tool 重 spawn；每个 tool `E(..., journal_finish=True)`；注入的 error 只影响父进程。

### R16 — K3.5：DB settlement 已提交、journal settlement 未写

**Setup**：real `read`；`prepare`、`activate`；`start_run`；`target = T(model_id, 0)`；`hits = []`（可变列表，供 wrapper append）。

**`inject_before` 过滤**：

```python
restore = inject_before(
    harness, "settlement_committed", effect_id=target, kind="tool_call", hits=hits)
```

wrapper 在**不调用**原 append 的情况下命中，条件全部满足才抛 `HostCrash`：

- `event_type == "settlement_committed"`；
- `str(effect_id) == str(target)`；
- `payload.get("outcome", {}).get("body", {}).get("kind") == "tool_call"`；
- `"response" in payload and "outcome" in payload`；
- `not payload.get("reconciled") and "reason" not in payload and not payload.get("conflict")`。

最后两条排除 `_record_settlement` 的 `database_terminal`/`reconciled`/`claim_token_changed` payload；`kind == "model_call"` 排除 model settlement。命中后立即 `restore()`，`hits.append(effect_id)`；`len(hits)` 必须恰为 1，未命中即 FAIL。

**Action**：

1. `try: harness.run([batch_reply([("call_read","read",{"path":"tail"})]), final_reply("r16-final")], max_rounds=30) except HostCrash: pass`；`finally: restore()`；断言 `len(hits) == 1`。
2. 断言 effect `succeeded`、`settled_at` 非空（DB 已 settle）；journal 有 `dispatch_finished`、`settlement_count(target) == 0`；`S(install)["invoke"] == 1`。
3. `snapshot = capture_effect(harness, target)`；`reconciled, settlements = run_recover_process(harness, harness.scope)`；断言 `reconciled == 0`、`settlements == 1`、exit 0；`reopen_harness(harness)`。
4. 断言 journal settlement 恰 1；payload `reason == "database_terminal"`、`conflict is False`；effect 的 `status/outcome/settled_at/attempt_no/fence` 与 `snapshot` 逐项相等。
5. `harness.run([final_reply("r16-final")], max_rounds=30)`；run `completed`、continuation 恰 1；再 `harness.run(None, max_rounds=2)`，断言不再新增 settlement、`_reconcile` 返回 0。

**Assert**：这是 K3.5 的**补写**，不是 replay；`reconciled=0` 不是失败，必须用 `settlements=1` 与 effect row 不变判定。`E(target, journal_finish=True)`。

## 9. 不变量与 receipt 证据

每个 `rNN_*` case 结束前跑一次 `assert_w7_invariants(harness, recovered_unknown=...)`（§7.1 #15，scope 级、无 `run_id`）；现有 G12-A…H/L 不调用它，行为与断言不变。**R02/R03 传 `{target}`**（DB recovery 必写 `effect_recovered_unknown`），**R09/R13 及其余 R 传空集合或省略**（timeout / 普通 failure / journal `_reconcile` settle 都不写 effect-level event，包括 R05/R14/R15/R16）。R07/R08 的检查同样是 scope 级；continuation 计数、model effect 计数等 run 级断言留在各 case 内，不进 helper。

### I1 — `no_replay` 未被提升

- 对 scope 内**全部** `kind='tool_call'` 的 effect（含已 settle 的，枚举方式见 §7.1 #15）：`replay_policy == "no_replay"`。
- 每个 tool effect 的 `effect_recovered_replay` 事件恰 0（不存在 `action == "reset_ready"` 的 tool_call）。
- **v2** tool descriptor 的 `descriptor.tool.replay_class` 仍是 `read_only`（声明），但 recovery 不读它做授权；v1 echo descriptor 没有 `replay_class` 字段，不对 v1 断言该字段。
- DB `effect_recovered_unknown` 的 payload：`action == "settle_unknown"`，`reason == "lease_expired"`；R02/R03 是这条的唯一来源（`recovered_unknown={target}`）；R05/R14/R15/R16 的 journal `_reconcile` settle 不写 effect-level event，也不产生 `reset_ready`。

### I2 — 一个 effect 一个 DB receipt

- 不用“`v24.effects` 中该 effect_id 恰 1 行”作证据：effect_id 是主键，行数恒为 1。
- 主证据是 effect row 的 `status` 为 terminal（`succeeded`/`failed`/`unknown`/`cancelled`）、`settled_at` 非空，且 `attempt_no`/`fence`/`settled_at` 与快照逐项相等；第二次 recovery 后不变。
- 正常 settle 不要求每个 effect 都有一条 `v24.events` 行（普通事件是 run-level；只有 recovery 写 effect-level `effect_recovered_unknown`）。
- 对 scope 内每个 tool effect：helper 先算 `expected = {str(item) for item in recovered_unknown}` 与 `key = str(effect_id)`；仅当 `key in expected` 时，`v24.events`（`entity_type='effect'`、`entity_id=<effect_id>`、`event_kind='effect_recovered_unknown'`）恰 1 条，payload `action == "settle_unknown"`、`reason == "lease_expired"`；否则恰 0 条。`v24.events` 的列名是 `effect_id`/`entity_type`/`entity_id`/`event_kind`/`payload`（`10_schema.sql:231-244`），所以 I2 用 `event_kind='effect_recovered_unknown'`、`entity_type='effect'`、`entity_id=<effect_id>` 三个条件定位。K1/K2 是前者的唯一来源；run 级的 `tool_call_unknown`/`run_blocked_unknown` 不计入 effect 计数。**不得**直接写 `effect_id in recovered_unknown`：R02/R03 传 `{target}` 时 `target` 是 `uuid.UUID`，枚举得到的是字符串，直接比较恒为 False。
- `harness.db.host_effects(harness.scope)`（单参）在 case 结束时不含 `tool_call`：scope 内不得残留 `ready`/`claimed` 的 tool effect（K1/K2 也已 `settle_unknown`）。这条只用它的单参形式，不用它枚举全部 effect（理由见 §7.1 #15、§17.3 注）。
- K3.5 的 DB 已 terminal，不允许再 settle；它的 evidence 是 journal settlement 增量，不是新 event。R16 在崩溃后、fresh recover 前就断言 effect `succeeded`；fresh recover 后再次逐项比 `status/outcome/settled_at/attempt_no/fence`。
- R15 的三个 tool 在父进程 patched settle 下仍是 `claimed`，不是 terminal；只有 fresh process 成功后才是 terminal。不要把“崩溃时 claimed”误判成缺 receipt。

### I3 — 有 `dispatch_finished` 时 journal receipt 恰一

- scope 内每个有 `dispatch_finished` 的 tool effect：`dispatch_finished` 恰 1；`settlement_committed` 恰 1；没有 `dispatch_finished` 的恰 0。
- helper 先断言上面的计数，再调用一次 `harness.worker._reconcile(harness.scope)`：必须返回 0，且 settlement 计数不变（K3.5 的第一次也可能返回 0，此时必须用 `settlements` 增量证明补写发生）。
- 对 K1/K2（无 `dispatch_finished`）：不要求 journal settlement；DB `effect_recovered_unknown` 是唯一 receipt（D8）。
- 对 K3.5：journal 补写 `settlement_committed` 恰 1，且 `payload.reason == "database_terminal"`、`payload.conflict is False`、`payload.outcome` 等于 `dispatch_finished` 的 outcome；不允许第二次 DB settle。R16 的 `reconciled=0` 不违反本判据，`settlements=1` 才是 receipt。
- R09 的 read 是最后一个 tool；unknown settle 后 run `blocked_unknown`，不再建 continuation。若 read 不是最后，list/search 会 `claimed` 且无 settlement（见 §8 R09），此时 I3 不成立，测试必须 FAIL 而不是放宽。
- v1 与 v2 用同一判据；v1 没有 spawn log 时，进程 evidence 用 `CountingSpawn`。

### I4 — spawn 双证

- **log 自洽 + 无重复 prepare/release**（helper 内，scope 级）：用 `harness.db.host_scope_installs(harness.scope, None, 64)` 按 `has_more`/`next_cursor` 翻页取 scope 内全部 install（`db.py:159-161`；下一轮 `after = next_cursor["install_id"]`）；对每个 install 调 `install_spawn_log(harness, install_id)` 取 log（`fixtures.py:436-447`），`spawn_ops` 解析出的 operation 计数之和等于 log 有效行数，且没有无法解析的行；`prepare <= 1`、`release <= 1`（同一 install 不得二次 prepare/release）。`install_spawn_log` 返回 `None` 的 install（R14 的 v1 没有 `--spawn-log`）**跳过**这段日志自洽，由 case 内 `CountingSpawn` 负责。精确 `invoke` 期望属于 case，不在 helper 重列；helper 的 `<= 1` 只能证明“没有重复 prepare/release”，不能单独支撑 marker 的 `second_spawn=false`。
- 有 `C` 的 v2 case（R01/R05/R07/R08/R13）：`CountingSpawn` 次数 == spawn log 行数 == 期望 operation 计数（`C.__exit__` 在 case 内断言）。只读 spawn log 的 case（R04/R09/R10/R15，以及 R11/R12 的成功子探针）：spawn log 的 operation 计数 == 期望值；不要为了“双证”给这些 case 强塞 `CountingSpawn`。`second_spawn=false` 由 case 内精确计数（`C` 的 `expected`/`ops` 或 spawn log 的精确 operation 期望）支撑，不由 helper 的 `<= 1` 推出。
- v1 没有 `--spawn-log`：只用 `CountingSpawn(artifact=v1.entry.artifact_path)`，过滤 `spec.argv[1]` 的真实路径，期望 `prepare=1`、`invoke=2`、总数 3；不得补一个测试专用 log 参数。证明链是 `plugin_fixtures.py:136`（argv 只有 interpreter+artifact）→ `fixtures.py:436-447`（无 flag 返回 None）→ `fixtures.py:450-453`（spawn_count 返回 0）。
- 零 spawn 的 case：`ZeroSpawn` calls == 0 且 spawn log 行数不变。
- R15/R16 的 fresh process：spawn log 行数在恢复前后不变（恢复进程没有 registry）。
- 不用 journal `dispatch_started` 数量代替进程计数（C.14）。

### I5 — 无重复 spawn / 无 rerender

- `spawn_ops` 每个 operation 的计数等于期望；恢复不增加计数。
- R04 断言“不重发 initial model request”，不是“不 rerender”：崩溃在 model 阶段，此时还没有 tool message。
- R10 只对崩溃前已 `dispatch_finished` 的 effect 断言不重渲染；剩余两个 tool 是首次 render。
- K3.5 不允许第二次 DB settle；R15 不允许 tool 重 spawn；R16 的 continuation 只由 DB settle 产生，fresh recover 不建新 effect。
- R09 的 tool `dispatch_finished` 顺序必须是 effect UUID 升序且 read 最后；list/search 的 success 在 read unknown 之前完成。顺序由 journal 的实际记录顺序断言，不符即 FAIL。
- `second_spawn=false`、`rerender=false` 由 aggregate 断言，不靠单个 marker 字符串；`journal_events_unchanged=true` 由 G12-G 的事件类型集合支撑。

### I6 — 进程清理

- R03 的 host 子进程必须是 `WIFSIGNALED`/`SIGKILL`；**R03 的插件 pid** 与 **R13 的插件 pid、孙进程 pid** 在测试结束前无 live 状态（`ps -o stat=` 空或 `Z`）。两者的证据口径不同：**R03 先 `killpg` 再 `assert_no_live`，只证明测试侧清理干净**；**R13 先观察、后清理，才证明 host timeout 路径自己做了组级 kill**。
- **ESRCH 语义（R03/R13 都适用）**：R03 的测试侧 `killpg(plugin_pid, SIGKILL)` 与 R13 最外层 `finally` 的 `killpg`，在进程组已不存在时都可能抛 `ProcessLookupError`（`ESRCH`）；这视为**成功**（already_gone），不记失败。其它 errno 只记录，不掩盖主断言。
- **清理顺序（仅 R13）**：R13 必须先对插件 pid 与孙进程 pid **都**完成 `assert_no_live`（只观察，不发任何信号），再由 case 最外层 `finally` 对插件进程组 `os.killpg(plugin_pid, SIGKILL)` 清理；检查失败也保留失败，不因清理而变成通过。R03 **不适用**这条顺序：R03 在断言插件 pid 无 live 之前就是测试侧 `killpg(plugin_pid, SIGKILL)`，然后 `assert_no_live`，只证明测试侧清理干净，不证明 host 自动清理。`assert_no_live` 内不得 `kill`/`killpg`/`waitpid`——否则先检查插件 pid 会顺带杀死同组孙进程，孙进程检查必然通过（假阳性）。
- 清理失败只记录，不掩盖原始失败；同一 pid 只允许成功 `waitpid` 一次并用 `reaped` 记录。
- R03 fork 前 `assert_fork_safe` 必须成立：journal/db/owner 全关，`fixture._connections` 全 closed，`fixture._lock_conn` 仍 open；这不满足即 FAIL。
- R03 的 fork 子进程用 `WNOHANG` 轮询 + 30s deadline；超时用 `os.kill(child_pid, SIGKILL)`（不是 `killpg(child_pid)`）再 `waitpid`，并 FAIL，不转 SKIP。
- 不留下 `plugin-journal.jsonl` 之外的临时文件在仓库内；所有临时树在 `TemporaryDirectory` 下。

---

## 10. Gate、证据与 scope audit

### 10.1 命令与 marker

命令不变：

```bash
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 \
  uv run python v24/s13/test_lifecycle.py
```

目标 marker：

```text
[passed] W4 lifecycle; cases=30; recovery_probes=16; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true; no_replay=true
```

三态规则不变：exit 0 + marker = pass；exit 2 / `[SKIP]` = unverified；exit 1 / marker 缺失 = fail。

### 10.2 32-command 串行 sweep

沿用 M5 执行记录的 32 条命令与顺序；**不新增第 33 条**。唯一变化是第 30 条 `test_lifecycle.py` 的 marker（`cases=30; recovery_probes=16; ... journal_events_unchanged=true; no_replay=true`）。第 1–29、31–32 条的期望末行与 M5 记录相同；第 32 条仍是 `git diff --exit-code c8c4bd0 -- v24/sql`，输出为空。

要求：

- 32/32 exit 0；第 1–31 条有命令专属 `[passed]` 末行；第 32 条空输出。
- 无 exit 2 / `[SKIP]`。
- 第 14–24 条仍是 11 条 closeout 命令；closeout **11/11**；s13 不是第 12 条。
- 记录每条命令的 UTC 开始时间、exit、实际末行、log SHA-256；不用 `tail` 的退出码代替 producer 退出码。

### 10.3 七项 scope audit

在文档落盘后、staging 前重跑；每项 exit 0 且末行匹配。

| # | 检查 | 基线 | 期望末行 |
|---:|---|---|---|
| 1 | frozen modules/tests：`v24/host`、`v24/sql`、`v24/s13/vectors`、除 `test_lifecycle.py` 外的 `v24/s13/test_*.py` 零 diff；允许 `w4_stub_plugin.py`/`w7_recover.py` 两个 test asset 改动；无未跟踪冻结文件 | `a41ce22` | `[scope] passed frozen_modules_and_untracked` |
| 2 | 整个 `v24/s13/vectors` 零 diff（含 `design_conformance.json` 的 `design_input.sha256_at_review`） | `a41ce22` | `[scope] passed vectors_zero_diff` |
| 3 | `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md`、`design_conformance.json`、`test_contracts.py` 字节零 diff；`DESIGN_SHA256` 仍匹配 | `a41ce22` | `[scope] passed design_pins_zero_diff` |
| 4 | registry exact D12 patch（`c8c4bd0` 继承） | `c8c4bd0` | `[scope] passed registry_exact_patch` |
| 5 | host import purity（无 file/db/network/clock 新 import） | `c8c4bd0` | `[scope] passed host_import_purity` |
| 6 | SQL zero diff | `c8c4bd0` / `a41ce22` | `[scope] passed sql_zero_diff` |
| 7 | W7 候选集：tracked delta + untracked path+sha256 是 8 路径候选集的子集；`test_lifecycle.py` 允许 imports、helpers、R01–R16、`stub_spec` 的 enum/`realm`、`main`、marker；`w4_stub_plugin.py` 允许 imports、`SCENARIOS`、`_invoke` 两个新分支与自取 spawn_log，**不**改签名；原有 case/helper/scenario 行为不变 | `a41ce22` | `[scope] passed w7_candidate_only` |

注意：

- 审计 1 必须允许 `test_lifecycle.py`、`w4_stub_plugin.py`、新 `w7_recover.py`、README 的改动；但不允许 `v24/host`、`v24/sql`、vectors、其他测试改动。
- 审计 3 不用 `ab4636fc…` 或 `2307077` 的替代 SHA；用当前 `a41ce22` 的真实字节。
- 审计 7 的 allowlist 必须覆盖实际改动，不能再写“只增 helper/case”：`test_lifecycle.py` 的 imports（`re`/`signal`/`subprocess`/`time`；从 `plugin_fixtures` 引入 `_owner`；从 `v24.host.db` 引入 `HostDB`；从 `v24.host.plugins` 引入 `PluginDispatcher`；从 `fixtures` 引入 `install_spawn_log`）、15 组 helper（17 个函数/类：`CountingSpawn`/`spawn_ops`/`tool_effect_id`/`tool_order`/`reopen_harness`/`close_connections`/`open_connections`/`assert_fork_safe`/`inject_after`/`inject_before`/`install_crash_after_started`/`assert_single_receipt`/`capture_effect`/`run_recover_process`/`assert_no_live`/`settlement_count`/`assert_w7_invariants`）、R01–R16、`stub_spec` 的 `realm` 参数与 13 值 scenario enum、`main()` 顺序、marker；`w4_stub_plugin.py` 的 `import signal`/`subprocess`/`pathlib`、`SCENARIOS` 两个值、`_invoke` 两个分支与 `_spawn_log_path(sys.argv)` 自取。`main()`/`_invoke` 签名不变，现有 scenario 分支逐字节不变。v5 补充：`assert_w7_invariants` 的 scope 级枚举只用 `harness.db` 的既有读方法（`host_runs`/`host_run_effects`/`host_effects`），**不新增模块级 helper、不新增 import**；计数仍为 15 组 / 17 个。v6 再补 `host_scope_installs`（同样是 `HostDB` 既有方法，不新增 import）与 `recovered_unknown` 的规范字符串归一，计数仍为 15 组 / 17 个。

### 10.4 证据目录

`/tmp/v24-abi-w7-<UTC>/`，包含：

- `provenance.txt`：HEAD、origin/main、uv/Python/Node/PostgreSQL/macOS 版本。
- `git-status-porcelain.txt`：sweep 后完整状态。
- `source-sha256.txt`：候选源码（含 `test_lifecycle.py`、`w4_stub_plugin.py`、`w7_recover.py`）、`fs_read.py`、`fs_tools.js`、B0 golden 的 SHA-256。
- `01.log`–`32.log`、`results.tsv`、`merged.log`。
- `scope-precheck/`、`scope-final/` 与七项 audit 日志。
- `credential-scan.txt`：只记 redacted 位置；命中即停。
- `w7-recover.log`（如单独保存）。
- `publication-receipt.txt`：**固定路径** `/tmp/v24-abi-w7-<UTC>/publication-receipt.txt`，**不入 repo**；内容为 commit SHA、`git push` 退出码与远端 ref 更新行、push 后 `git rev-parse origin/main`、UTC 时间（§14）。

### 10.5 运行时间与稳定性

W7-0 已实测现有 14 case 基线为 **12.5s**（`/usr/bin/time -p`，2026-11-01，本机）。每 case 预算与总预算：

| 组 | 预算 (s) | 依据 |
|---|---:|---|
| G12-A…H + G12-L（现有 14） | 12.5 | 实测 |
| R01 | 1.0 | 1 prepare + 1 invoke |
| R02 | 3.5 | 3s lease 轮询 + 3 次 `run(None)` |
| R03 | 7.0 | 6.5s lease + 一次 fork/waitpid |
| R04 | 1.5 | 2 model call + 3 tool spawn |
| R05 | 1.5 | 1 tool + 1 fresh process |
| R06 | 1.5 | 3 tool + restart |
| R07 | 1.5 | prepare/resume/read/release |
| R08 | 1.5 | read/release + 1 in-process cut-point crash |
| R09 | 2.0 | 3 tool、2 install |
| R10 | 1.5 | 3 tool + 1 crash |
| R11 | 2.5 | 5 个子 run（复用同一 install） |
| R12 | 1.0 | 2 个 run |
| R13 | 2.0 | 1s timeout + 孙进程清理 |
| R14 | 2.5 | v1 prepare+2 invoke + 两次 v2 read + fresh |
| R15 | 2.5 | 3 tool + fresh + final |
| R16 | 2.0 | 1 tool + fresh + final |
| **探针小计** | **35.0** | 各 case 串行 |
| **合计** | **47.5** | 12.5 + 35.0 |
| **硬上限** | **90.0** | 留 1.9× 余量 |

- 唯一固定等待是 R02 的 3s 与 R03 的 6.5s lease（共 9.5s）；其余是 R13 的 1s timeout、4 次 fresh process（各约 0.3s）与轮询，没有长 sleep。
- R03 只 fork 一次，不重试；超时 30s 只作为失败保护，不进正常预算。
- R11 的五个子 run 复用同一个 harness/install，不重复 DB setup；R15/R16 的 fresh process 复用同一 fixture 的 DSN，不重建测试库。
- 全套 32 条 ≤ 6min 不变。若实测 > 90s，先优化等待/复用 harness，不得删 case、不得把 R03 标 SKIP；若 R03 连续 3 次不稳定，先修时序/清理，仍不稳定则 STOP 改写为 subprocess driver（§13 R1）。

---

## 11. 工作项与执行索引

| # | 工作项 | Done when | 关键文件 | 依赖 | 量级 |
|---:|---|---|---|---|---:|
| W7-0 | 基线复核 | 读 W4c record、design §7.3/C.11/C.14、现有 14 case；确认 HEAD `a41ce22`；现有 gate 绿；实测 14 case 12.5s | 只读 | — | 0.5h |
| W7-1 | 测试 helper + stub scenario | 见 §7.1 #1–#15：15 组 helper（17 个函数/类）可用，`assert_w7_invariants` 为 scope 级、`recovered_unknown` 归一为规范字符串、I4 用 `host_scope_installs` 翻页；§17.4 的四项静态事实已核实，W7-1 只保留运行时探针（helper 实跑、stub 两 scenario、`realm`）；stub 两 scenario 可 import；`stub_spec` 支持 `realm` | `test_lifecycle.py`、`w4_stub_plugin.py` | W7-0 | 3h |
| W7-2 | K0/K1 资源与 tool cut-point | R01/R02/R07/R08 绿；`spawn_ops`/`E` 成立 | `test_lifecycle.py` | W7-1 | 3h |
| W7-3 | fresh-process recovery | R05/R06/R15/R16 绿；`w7_recover.py` 输出 reconciled/settlements | `test_lifecycle.py`、`w7_recover.py` | W7-1 | 3h |
| W7-4 | 真实进程崩溃 | R03 绿：SIGKILL、spawn 1、unknown、无第二次 spawn、无 live 残留 | `test_lifecycle.py`、`w4_stub_plugin.py` | W7-1 | 3h |
| W7-5 | mixed batch | R04/R09/R10 绿；R04/R10 continuation 恰 1，R09 continuation 0；R09 read 最后执行且由 journal 实际 `dispatch_finished` 顺序断言；receipt 不重复 | `test_lifecycle.py` | W7-2/W7-3 | 3.5h |
| W7-6 | tamper/timeout/legacy | R11/R12/R13/R14 绿；R11 子探针按 registry 顺序；零 spawn 双证；进程组清理；B0 字节 | `test_lifecycle.py`、`w4_stub_plugin.py` | W7-1 | 3h |
| W7-7 | 文档与 sweep | README/matrix/ledger/execution record/Result；32/32；7 audits | docs、README | W7-2…W7-6 | 2.5h |
| W7-8 | 条件式 host fix | 仅在探针红且确认为 host 缺陷时执行；host-only；全套重跑 | 视缺陷 | W7-2…W7-6 | 不确定 |

依赖图：

```text
W7-0 → W7-1 → W7-2 → W7-5
             ├→ W7-3 → W7-5
             ├→ W7-4
             └→ W7-6
W7-2…W7-6 → W7-7
任何红 → W7-8（条件）
```

---

## 12. File-by-file impact

### 12.1 生产/测试代码（3 路径）

| 路径 | 变更 | 说明 |
|---|---|---|
| `v24/s13/test_lifecycle.py` | 改，约 +850 行 | 15 组 helper（17 个函数/类，`assert_w7_invariants` 为 scope 级、无 `run_id`、`recovered_unknown` 归一为规范字符串、I4 用 `host_scope_installs` 翻页）+ R01–R16；`stub_spec()` 加 `realm` 参数与两个 scenario；现有 14 case 与 helper 行为不变；marker 改为 `cases=30; recovery_probes=16` |
| `v24/s13/w4_stub_plugin.py` | 改，约 +55 行 | `SCENARIOS` 与 `_invoke` 只加 `grandchild`/`kill_parent`；`import signal`/`subprocess`/`pathlib`；现有 scenario 不变；不改签名 |
| `v24/s13/w7_recover.py` | 新，约 +110 行 | fresh-process `_reconcile`，输出 reconciled/settlements；真实 `HostDB`；无 registry、无 spawn |

### 12.2 文档（5 路径）

| 路径 | 变更 |
|---|---|
| `v24/s13/README.md` | 追加 W7 小节：命令、marker、16 probes、K0–K5+K3.5、limits、closeout 11/11 |
| `docs/reviews/v24-conformance-matrix-2026-10-23.md` | 追加 W7 小节：R01–R16 证据表、K0–K5+K3.5、gate 结果、closeout 不变 |
| `docs/reviews/v24-deviation-ledger-2026-10-23.md` | 追加 `D-ABI-W7-1…6`：journal/DB receipt 不对称（含 K3.5）、fork crash 测试资产、R02/R03 的 lease 选择、multiple pending 注入、无 host 改动、无 replay 扩张 |
| `docs/reviews/v24-tool-plugin-abi-w7-execution-2026-11-01.md` | 新：provenance、source SHA、32 行 sweep、7 audits、R15/R16 证据、limits、publication |
| `docs/plans/v24-tool-plugin-abi-w7-lifecycle-recovery-2026-11-01.md` | 本计划；执行后写 Result |

### 12.3 明确不改

`v24/host/**`、`v24/sql/**`、`v24/s13/vectors/**`、`v24/s13/plugins/fs_read.py`、`v24/s13/plugins/fs_tools.js`、`v24/s13/fixtures.py`（`open_harness` 的 `realm` 已是必填 kwarg，见 `fixtures.py:429-433`）、`v24/s11/plugin_fixtures.py`（`PluginHarness` 已接受 registry）、design 两份、`design_conformance.json`、`test_contracts.py`、其他 s13 测试、`v24/b0/**`、`v24/load.py`。

若 W7-8 触发，新增的 host 路径单独列出，并重新评估 12.1/12.2 与 audit 1/4/5。

---

## 13. 风险、STOP 与回滚

| # | 风险 | 影响 | 缓解 / STOP |
|---:|---|---|---|
| R1 | fork 子进程在 macOS 上不稳定/挂起 | R03 无法证明真实进程崩溃 | 30s 超时 + `os.kill(child_pid, SIGKILL)` 后 `waitpid`（不是 `killpg(child_pid)`），插件进程组另按 spawn log 的 pid `killpg`；连续 3 次失败则 STOP，改写为 subprocess driver；不得把 R03 标 SKIP |
| R2 | lease 太短，spawn 前就过期；或太长，测试变慢 | R02/R03 抖动 | R02 用 3000ms、R03 用 6500ms（满足 1000+5000 门槛）；6500ms 对 6000ms 门槛只有 500ms 余量，抖动导致 `remaining < 6000` 时 FAIL 并记录实际值，不得把 lease 调到 30s 规避；用 `remaining_lease_ms` 轮询上限 lease+2s；不 sleep 30s；不直接改 DB lease |
| R3 | journal wrapper 漏掉目标 effect，或注入不恢复 | K0/K3.5 注入未命中或污染后续 case | `inject_after`/`inject_before` 一次性，命中后立即 restore；注入后断言 journal 最后事件是 `effect_prepared`（K0）或 `dispatch_finished` 且无 settlement（K3.5）；未命中/`hits != 1` 即 FAIL；`finally` 再恢复一次 |
| R4 | K1/K2 journal 没有 settlement，被误判为缺 receipt | 测试错误地要求补事件 | D8 明确：DB `effect_recovered_unknown` 是 receipt；不伪造 journal 事件 |
| R5 | fork 前未关闭 DB/journal，子进程继承锁/连接 | R03 挂起或 journal locked | `close_connections` 关 journal→db→owner；`assert_fork_safe` 检查 `journal._fd == -1`、`db._closed`、`owner.closed`、`fixture._connections` 全 closed；保留 `fixture._lock_conn`；子进程只重开；父用 WNOHANG 30s 后重开 |
| R6 | 插件孙进程变成 zombie，`kill(pid,0)` 仍成功 | R13 误判 live | 用 `ps -o stat=` 判定空或 `Z`；R13 的清理由 case 最外层 `finally` 做 `killpg`（`assert_no_live` 只观察、不发信号）；不把 zombie 当 live；`.child` 文件轮询 2s |
| R7 | v1/v2 union registry 构造错误，或 R14 时序错 | R14 无法 start 或 B0 request2 拿不到 | 同一 realm；`ApprovedAdapterRegistry((v1.entry, v2.entry))`；先 v2、再 v1 success、再 known-error 崩溃续跑；失败即 STOP，不改 v1 |
| R8 | 测试 runtime > 90s | sweep 超时 | W7-0 先测基线；复用 harness；R03 只做一次；R02/R03 轮询而非长 sleep；不删 case |
| R9 | 探针暴露 host 真缺陷 | 需要改 host | W7-8 host-only 最小修复；若需 SQL/kernel/replay/design → STOP，另立设计修订 |
| R10 | closeout 被误写成 12/12 | 文档不一致 | README/matrix/ledger 明确 11/11；audit 7 检查关键字 |
| R11 | 临时 `/tmp` 探针被当成 gate 证据 | 过度声明 | 计划/记录明确“不作为验收证据”；evidence 只认 sweep 日志 |
| R12 | 未跟踪文件被卷入提交 | 违反 AGENTS | 按路径 `git add`；staging 后 `git status` + diff 复查；不 `-A` |
| R13 | R15 的 `db.settle` patch 泄漏到恢复进程 | 三个 pending 被错误 settle，证据失真 | patch 只作用于父 `harness.db`，恢复前 `harness.db.settle = original`（R15 用的是直接赋值，不是 `unittest.mock.patch`，所以没有 `patch.stop()`）；fresh process 用真实 `HostDB`；断言恢复进程 spawn log 不变 |
| R14 | R16 的 `reconciled=0` 被误判为失败 | K3.5 无法验收 | `w7_recover` 同时输出 `settlements`；R16 用 settlement 增量与 effect row 不变判定 |
| R15 | R09 的 read 先于 list/search 执行 | run 提前 blocked，兄弟 effect 停留 claimed、无 settlement，R09 的“三 receipt”失败 | 用 `T(model_id, ordinal)` 计算 effect UUID，`order = tool_order(model_id, 3)`，把 read 放在 `order[-1]`（3 个 UUID 必然可排序、最大者一定存在，不需要 skip 分支或同义 guard）；实际执行顺序由 journal 的 `dispatch_finished` 顺序断言，不符即 FAIL。负分支写入 §8 R09，不静默放宽 |
| R16 | R02 的 `crash_after="started"` 全局设置 | model 在 `_execute_model:985` 先崩，tool 不会到 `:1048` | 只通过 G12-G 的 `_execute_tool` monkeypatch 设置；helper 保存并**返回** `original`，wrapper 在 `finally` 恢复 `crash_after=None`，restore 把 `original` **重新赋值**回 `worker._execute_tool`（不是 `del`，见 §7.1 #9）；断言 `is original`，其中 `original` 必须是 helper 的返回值，调用者不得自己再取 bound method |
| R17 | R16 的 `inject_before` 误命中 `_record_settlement`/model settlement | K3.5 注入不命中或命中两次 | 过滤 `effect_id` + `payload.outcome.body.kind=="tool_call"` + `response`/`outcome` + `payload.get("reconciled")` 为假且无 `reason`/`conflict`；命中后 restore；`hits==1` |
| R18 | R15 的 `db.settle` patch 返回形状不被 `is_error` 识别 | 三个 tool 被真实 settle，pending=0 | 返回 `{"error": {"code": ...}}`；`is_error` 要求 `error` 是 dict（`db.py:244-245`）；`_settle` 在 error 时仍跑 `assert_all_idle`（`:1279`）；恢复前 `harness.db.settle = original`（直接赋值，没有 `patch.stop()`） |
| R19 | R03 的 fork 子进程继承 `fixture` 的其它连接 | 子进程写坏父连接/锁 | `assert_fork_safe` 检查除 `_lock_conn` 外全部 closed；子进程只用 DSN 字符串新建 `HostDB`/`HostJournal`；`os._exit` 不走 atexit |

**必须停下来改设计/内核的条件**：

- 需要把 tool `no_replay` 改成 `replay_safe`/自动重投。
- 需要新增 journal event type 或第 11 张表。
- 需要修改 `dispatch_started` 的顺序（pre-spawn 前移）。
- 需要 SQL recovery 行为变更。
- 需要改 design §7/§10/C.11 的完成声明。
- 合法输入无法在现有 64 KiB/5s/15s/30s 合同内表达。

---

## 14. 提交与推送

顺序（不可颠倒）：

```text
32/32 gate 绿
→ 7 项 audit 预检 + 文档落盘后 final audit
→ git status / 按 8 路径 git add
→ staged diff + credential scan
→ git commit -m "v24: close out v2 lifecycle and recovery evidence"
→ git push origin main
```

规则：

- 一次 W7 里程碑提交；不把 M3/M5 或无关工作卷进来。
- 只 add §12 的 8 个路径；不使用 `git add -A`/`git add .`。
- 不使用 `--no-verify`；hook 失败修根因。
- 不 force push；push 被拒先 `git fetch origin`，必要时 `git pull --rebase origin main`。
- 提交前扫描 staged bytes 与 evidence，发现疑似 key/DSN/token 即停；只报 redacted 位置。
- 记录 commit SHA / push 结果到**外置** publication receipt：固定路径 `/tmp/v24-abi-w7-<UTC>/publication-receipt.txt`（**不入 repo**），内容为 commit SHA、`git push` 退出码与远端 ref 更新行（`... -> main`）、push 后 `git rev-parse origin/main`、UTC 时间。execution record 与**本计划 Result** 都只引用该路径，不嵌自己的 commit SHA（文件不可能包含自身 SHA，见 §17.2 A5）。Result 只记 sweep HEAD、验证结果与该 receipt 路径。

---

## 15. W7 不证明什么

- **不证明 tool replay 可用。** 所有 tool effect 仍是 `no_replay`；K1/K2 仍是 unknown + `blocked_unknown`，不是自动重投。
- **不证明真实 provider 的 in-flight 恢复。** R04 只覆盖 model `dispatch_finished` 后的 journal replay；model `dispatch_started` 后、response 前的崩溃不在 W7（kernel G5/G7 覆盖 DB 层，不是 v2 provider 层）。
- **只证明 enumerated windows（K0–K5 + K3.5），不是“所有 crash window”。** R03 是 tool invoke 的真实 SIGKILL；prepare/release 是 in-process cut-point（K0），不是真实进程崩溃。K1/K2 没有 `dispatch_finished`，K3.5 是 DB terminal/journal 未写；其它窗口（例如 command_prepared/committed、DB settle 返回 error 后的多轮重试、model `dispatch_started` 后 response 前）不在 W7。
- **不证明 multiple pending 的生产调度策略。** R15 用注入的 `db.settle` error 制造 3 个 pending，只证明 fresh process 能一次 reconcile、不重 spawn；不证明生产环境产生 pending 的原因或 fair-worker 的债务处理。
- **不证明 blocked 兄弟 effect 的自动恢复。** R09 只验证“read 最后执行”的正向路径；read 先执行时 list/search 会 claim/spawn 但 settle 被 `blocked_unknown` 拒绝、停留 claimed（§8 R09）。W7 不修这个行为，也不把它写成 success；若要覆盖，另立 case。
- **不证明 R07/R08 的真实进程崩溃。** prepare/release 的 K0 是 in-process journal cut-point，不是 SIGKILL；真实 SIGKILL 只覆盖 R03 的 tool invoke。
- **不证明 v1 的 release/dispose。** R14 只跑 v1 prepare + 2 invoke，不做 v1 off/dispose；`C(3)` 因此是精确的 3，不是 4。
- **不证明 Linux real。** 当前 macOS-first；fork/process-group 语义在 Linux 应一致，但未运行。
- **不证明 fair-worker 恢复。** W7 用 `run_until_idle`；`run_scopes_until_idle` 的 recovery debt 不在范围。
- **不证明并发/恶意 workspace。** 不覆盖 `require_artifact` 与 spawn 之间的 TOCTOU；不覆盖 symlink race；不覆盖恶意插件。
- **不证明 journal 与 DB 在 K1/K2 完全对称。** D8 已知不对称：DB 有 `effect_recovered_unknown`，journal 停在 `dispatch_started`。
- **不证明 12 秒 search budget 或硬实时。** W7 不碰 12s/15s；只做 timeout 进程组清理。R13 的 timeout 用 Python stub；Node `search` 的 timeout 走同一 `process_io` 路径，但 W7 不单独跑 15s 真实超时。
- **不证明 closeout 变化。** closeout 仍 11/11；s13 仍是 extension evidence。
- **不证明 v1 行为变化。** v1 字节与恢复路径必须不变；任何 v1 差异都是 FAIL。

---

## 16. References

- `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md`
  - §7.3 G12-A…H/L（`:937-948`）
  - §7.4 done-when 1–8（`:952-986`）
  - §8.1 replay 是 kernel revision（`:1001-1012`）
  - §10 M4/M5（`:1067-1068`）
  - C.11 W4c/M4（`:1287-1298`）
  - C.13 十三步 reason 表（`:1342-1367`）
  - C.14 pre-spawn `dispatch_started` 与零 spawn 双证（`:1370-1376`）
  - C.16 timeout 边界（`:1380-1385`）
- `docs/reviews/v24-tool-plugin-abi-w4c-execution-2026-10-31.md:146-147`（W7 的三个缺口）
- `docs/reviews/v24-tool-plugin-abi-m5-closeout-execution-2026-11-01.md`（32-command 形态、7 audits、closeout 11/11）
- `v24/s13/test_lifecycle.py:238-645`（现有 14 case）
- `v24/host/worker.py:654-698`（`run_once` 顺序）、`:701-751`（`_resume_prepared`，resource `required=0` 在 `:736-741`）、`:754-798`（`_reconcile`）、`:812-860`（`_orphan_state`/`_recover`）、`:884-888`（`_order_key`）、`:919-922`（`_lease_for`）、`:970/985/1020/1048/1081/1101/1123`（crash_after）、`:1278-1288`（`_settle` 的 DB→assert_idle→journal 顺序）
- `v24/host/journal.py:121-127`（flock）、`:201-208`（close/unlock）、`:273/290/304`（三类恢复查询）
- `v24/host/db.py:99-103`（`assert_all_idle`）、`:144-149`（`host_effects`；`after_created_at`/`after_effect_id`/`limit` 三个游标参数都有默认值，单参 `host_effects(scope)` 合法）、`:150-155`（`host_run_effects`，同样三个默认值）、`:159-161`（`host_scope_installs(scope, after=None, limit=64)`）、`:184-193`（`HostDB.settle`）、`:244-245`（`is_error`）
- `v24/host/registry.py:49-51`（`artifact_path=argv[1]`）、`:57-83`（artifact resolve → commonpath → regular → digest）、`:394-407`（union registry 构造）
- `v24/host/plugins.py:157-176`（`require_artifact`/workspace/lease，含 `:173` 的 lease 门槛）、`:283-314`（prepare/release）
- `v24/host/process_io.py:89-182`（`start_new_session`、`_kill_group`、timeout wait）
- `v24/s11/plugin_fixtures.py:136`（v1 argv 只有 interpreter+artifact）、`:274-429`（`PluginHarness`，含 `close`）
- `v24/s13/fixtures.py:429-453`（`open_harness`/`install_spawn_log`/`spawn_count`）
- `v24/host/line_json.py:274`（`_run_v2` 内的 `run_process` 调用点）、`:319`（v1 `run` 内的 `run_process` 调用点）：两条路径都调用**模块级** `run_process`，所以 patch `line_json.run_process` 同时覆盖 v1/v2（`CountingSpawn` 因此在两个版本上都生效）
- `v24/sql/48_loop.sql:45-47`（tool effect id）、`:1114-1138`（tool successors）、`:1133`（no_replay）、`:1359-1360`（blocked_unknown settle 拒绝）、`:1438`（run blocked）
- `v24/sql/10_schema.sql:231-244`（`v24.events` 的 `effect_id`/`entity_type`/`entity_id`/`event_kind`/`payload` 列与 `u_events_once` 唯一约束）
- `v24/sql/49_recovery.sql:95`（`effect_recovered_unknown`）、`:369-371`（no_replay tool → settle_unknown/lease_expired）
- `v24/sql/49_host_reads.sql:76-127`（`host_runs`，不按状态过滤）、`:129-207`（`host_effects`，只返回 `ready`/`claimed`，见 `:184`）、`:209-287`（`host_run_effects`，不按状态过滤，只含 `model_call`/`tool_call`，item 含 `replay_policy`，见 `:253`/`:265-266`）、`:349-358`（`host_scope_installs`）
- `v24/sql/30_advance.sql:583-585`（claim 只查 kind/status）、`:882-893`（claim lease）
- `v24/s1/setup_db.py:438/453-483`（`_lock_conn` 与 cleanup）
- `v24/s13/w4_stub_plugin.py`
- `v24/b0/golden/provider_requests_v1.json`
- `v24/b0/golden/tool_messages_v1.json`
- `AGENTS.md`（提交/推送/测试规则）

---

## 17. Oracle 裁决记录（2026-11-01）

两路 Oracle：L1 = `claude-opus-5-5`，L2 = `gpt-6.1-sol-xhigh`；2/2 完成，合并结论 **`needs-edits`**。不需要改 SQL/design；若探针暴露 host 缺陷，走 W7-8 host-only 分支。下表保留 v2 裁决原文，作为落实索引；v3 的修订逐条见 §17.1，其中 #16 已由 v3 关闭。

| # | 优先级 | 裁决 | 落实位置 |
|---:|---|---|---|
| 1 | P0 | R03 的 500ms lease 不满足 `timeout_ms + 5000` spawn 门槛 | R03 改 stub `timeout_ms=1000`、child `default_lease_ms=6500`；D5/D12/§10.5 同步 |
| 2 | P0 | `w7_recover.py` 缺 `main()` 入口；`reconciled` 不是被恢复 effect 数 | 补 `__main__` 与 `reconciled/settlements` 双输出；handler 改 `os._exit(97)`；R05/R14/R15/R16 |
| 3 | P0 | R14 先跑完 known-error 再崩溃，拿不到 B0 request2 | 改为 v1 success 完整跑 → known-error 在 `dispatch_finished` 崩溃 → fresh reconcile → 续跑 request2；v1 计数用 `CountingSpawn`=3 |
| 4 | P0 | `assert_single_receipt` 与 I2 的“每个 effect 有终态 event”矛盾 | helper 改为 terminal/attempt/fence/settled_at + DB recovery event 恰 1；正常 settle 不要求 event |
| 5 | P0 | R09 要同 realm，但 `stub_spec` 写死 realm | `stub_spec(realm=None)`；R09 用同 realm 建 stub+Node；audit 7 allowlist 列入 |
| 6 | P1 | R10 只有 1 pending + 2 ready，不兑现 multiple pending | 新增 R15（`db.settle` 对 tool 注入 error，3 pending，fresh reconcile=3）；cases 30 |
| 7 | P1 | K3.5（DB settle 已提交、journal settlement 未写）未覆盖 | 新增 R16；`w7_recover` 输出 `settlements`；K3.5 首次 `reconciled` 可为 0 |
| 8 | P1 | R02 lease 1000ms 可能在第一次 restart 前过期 | 提到 3000ms；`recovered==0/1` 降为辅助，主证据用 effect status/event |
| 9 | P1 | marker 不应丢 `journal_events_unchanged=true` | marker 同时保留该 flag 与 `no_replay=true`；cases=30、probes=16 |
| 10 | P1 | audit 7 的“只增 helper/case”容不下实际改动 | allowlist 精确到 imports、helpers、R01–R16、`stub_spec` enum/realm、main、marker、stub 两分支 |
| 11 | P2 | `grandchild` 需要 main 传 `spawn_log`，与“只加分支”冲突 | `_invoke` 内用 `_spawn_log_path(sys.argv)` 自取，不改签名 |
| 12 | P2 | R08 的 `dispose` 不会自己执行 release，动作顺序不完整 | 写明 dispose → 第一次 `h.run(None)` 崩溃 → 恢复 → 第二次 `h.run(None)` |
| 13 | P2 | R04 的“无 rerender”口径不对（崩溃时还没有 tool message） | 改断言“不重发 initial request”；R10 只对已 finish 的 effect 断言不重渲染 |
| 14 | P2 | D3 注入需 one-shot；I3 需 sanity | wrapper 一次性 + `finally` 恢复；K3.5 用 `settlements` 例外 |
| 15 | rejected | “`test_wiring` 会被 `SCENARIOS` 破坏”“第 14 个是 replay probe”“R09 不需 realm” | 维持现实现：`test_wiring.py:76` 用自己的元组；14 = A1+B1+C1+D3+E1+F3+G1+H1+L2；`stub_spec` 必须加 realm |
| 16 | unresolved | R07 的 `prepare` 幂等、R09 的 blocked 兄弟 effect、R14 的 union registry | 写成显式步骤与 smoke：R07 先 `h.run(None)` 再 `h.prepare`；R09 必须实测；R14 先最小 smoke，失败按 R7 STOP |

**v3 状态**：#16 已 **resolved**（§17.1 #16）；其余 15 条维持 v2 结论。

**计数口径**：现有 14（W4c 的子场景计数，A1+B1+C1+D3+E1+F3+G1+H1+L2）+ R01–R16 各 1 = `cases=30`；W7 采用函数级计数，R11/R13/R14/R15/R16 的子探针不另加。`recovery_probes=16` 固定。

### 17.1 v3 修订（2026-11-01）

v2 表保留为历史；v3 不重开任何裁决，只把未决项与自洽性缺口落成可执行步骤。逐条：

1. **#1 / R03**：保留 stub `timeout_ms=1000`、child `default_lease_ms=6500`；D4 补“先关 journal（flock）→ db → owner 再 fork”、`assert_fork_safe`、claim 必须由子进程执行、父 waitpid 后重开并轮询 lease；`fixture._lock_conn` 保留。§8 R03 给出完整 6 步。
2. **#2 / `w7_recover.py`**：保留 `main()` 与 `os._exit(97)` handler；新增 `settlements` 是 `after-before` 增量；fresh process 用真实 `HostDB`；R16 允许 `reconciled=0 settlements=1`。
3. **#3 / R14**：v1+v2 union 明确为 `ApprovedAdapterRegistry((v1.entry, v2.entry))` + `PluginHarness(fixture, registry, ...)`；`build_registry` 只作单 spec 便捷构造；`CountingSpawn(artifact=v1.entry.artifact_path)` 过滤 `spec.argv[1]`，期望 `prepare=1`/`invoke=2`/总数 3；v1 无 `--spawn-log` 的三段证明链写进 §8 R14；B0 tool message 必须按 `parent_effect_id` 取。
4. **#4 / `assert_single_receipt`**：保持 terminal + `settled_at` + `attempt_no/fence/settled_at` 快照；正常 settle 不要求 effect-level event；`db_recovery=True` 时 `effect_recovered_unknown` 恰 1；K3.5 用 settlement 增量。I2/I3 同步。
5. **#5 / `stub_spec`**：加 `realm=None`；descriptor enum 从 11 个值扩到 13 个（`grandchild`/`kill_parent`）；R09 用同一 realm 建 stub + Node；audit 7 allowlist 列入。
6. **#6 / R15**：写明 patched `db.settle` 返回 `{"error": {"code": ...}}`（`is_error` 认 `error` dict）；`_settle` 在 error 时仍先跑 `assert_all_idle`（`worker.py:1279`）；`h.run` 因 3 个 claimed、无 ready 而 idle；fresh process 真实 `HostDB`，`reconciled=3` 的依据是三个 pending 的 token 匹配 + `db.settle` 成功。
7. **#7 / R16**：`inject_before` 过滤 `effect_id` + `payload.outcome.body.kind=="tool_call"` + `response/outcome` + 无 `reason/reconciled/conflict`；命中后 restore，`len(hits)==1`；`_reconcile` 走 `database_terminal`，`reconciled=0 settlements=1`，effect row 不变。
8. **#8 / R02**：明确用 G12-G 的 `worker._execute_tool` monkeypatch 在调用原函数前设 `crash_after="started"`，`finally` 恢复 `_execute_tool` 与 `crash_after=None`；不能全局设，否则 model 在 `_execute_model:985` 先崩；lease 保持 3000ms，第一次 restart live、第二次 expired、第三次 no-op。
9. **#9 / marker**：保留 `cases=30; recovery_probes=16; ... journal_events_unchanged=true; no_replay=true`；`cases` 口径不变。
10. **#10 / audit 7**：allowlist 精确到 `test_lifecycle.py` 的 imports（`re`/`signal`/`subprocess`/`time`，以及 `plugin_fixtures._owner`；v4 再补 `HostDB`/`PluginDispatcher`/`install_spawn_log`，见 §17.2 A4）、14 组 helper（16 个函数/类；v4 补 `assert_w7_invariants` 后为 15 组 / 17 个；v5 只把它的签名改为 scope 级 `recovered_unknown`，组数/函数数不变，见 §17.3 A9/A14）、R01–R16、`stub_spec` 的 `realm` 与 13 值 enum、`main()`、marker；`w4_stub_plugin.py` 的 `signal`/`subprocess`/`pathlib`、`SCENARIOS` 两值、`_invoke` 两分支、`_spawn_log_path(sys.argv)`。
11. **#11 / R13**：`_invoke(args)` 内用 `_spawn_log_path(sys.argv)` 自取 log，不改 `main()`/`_invoke` 签名；`.child` 由 `<spawn_log>.child` 派生；`grandchild` 不建新 session，留在 plugin 进程组；测试侧轮询 2s。
12. **#12 / R08**：明确 `dispose` 只到 `dispose_pending`；第一次 `h.run(None)` 在 `host_release effect_prepared` 后崩；恢复后第二次 `h.run(None)` 才执行 release；`C(3)` 含 release。
13. **#13 / R04/R10**：R04 断言“不重发 initial request”，不是“无 rerender”；R10 的崩溃目标是 effect UUID 最小（执行顺序第一）的 tool，不是 ordinal 第一。v4 修正了 R10 把 `min(ids, key=ids.get)` 的返回值（ordinal）直接当 `effect_id` 的缺陷（§17.2 A1）。
14. **#14 / D3/I3**：`inject_after`/`inject_before` 一次性并在命中后 restore；`finally` 再恢复；未命中/`len(hits)!=1` 即 FAIL；K3.5 用 `settlements` 例外。
15. **#15（rejected）**：维持 `test_wiring.py:76` 自己的元组、14 = A1+B1+C1+D3+E1+F3+G1+H1+L2、`stub_spec` 必须加 realm；v3 不改。
16. **#16（v2 unresolved，v3 resolved）**：
    - **R07**：`admit` → `host_prepare effect_prepared` 后崩溃 → `h.run(None)` 由 `_resume_prepared` 完成 prepare（resource `required=0`，`remaining>0`）→ install `installed`，prepare spawn 0→1；再 `h.prepare([install])` 内部先 `run(None)` 但不再 spawn，prepare 仍 1；全生命周期 spawn `{prepare:1, invoke:1, release:1}`，`C(3)`。
    - **R09**：tool effect 按 `md5(model_id:tool_call:ordinal)` UUID 升序执行；测试把 read 放在最大 UUID（`read_ord = order[-1]`）；v4 删除了同义的 `assert order.index(read_ord)==2`（§17.2 A6）；list/search 先 success，read 最后 timeout→`blocked_unknown`，三 receipt 成立；read 先执行时兄弟 effect 会 claim/spawn 但 settle 被 `blocked_unknown` 拒绝、停留 claimed，这个负分支写进 §8 R09 与 §15，不再含糊写“应 success”。
    - **R14**：union registry 与 `CountingSpawn` 的构造/过滤/期望次数见 #3；v1 success + known-error + crash 的顺序见 §8 R14；v1 无 spawn log 的证明链见 §8 R14 第 6 步。

此外，v3 还同步了：**R01** 的 `C(2)` 先断言、`harness.close()` 不产生 release（若加 dispose 必须先退出 C，期望改 3）；**R11** 四个 artifact 子探针按 `resolve → commonpath → stat → digest` 重排为 missing → outside_cwd → not_regular → digest_mismatch；**R05/R06/R12** 的 fresh-process/no-op/workspace 步骤写全；**§10.5** 增加每 case 预算表（基线 12.5s + 探针 35s ≈ 47.5s，上限 90s）；**§16** 按本次实际源码复核行号（`worker.py:1278-1288`、`journal.py:273/290/304`、`registry.py:57-83`、`fixtures.py:429-453`、`plugin_fixtures.py:274-429` 等）；**§3/§9/§12/§13** 与正文同步。v3 **未**改变：32 条串行命令、closeout 11/11、`cases=30`、`recovery_probes=16`、marker 前缀、W7 范围与 STOP 条件。

### 17.2 v4 修订（2 路 Oracle 裁决与驳回）

第二轮 2 路 Oracle（L1/L2）仍判 `needs-edits`。v4 只落实**被裁决接受**的条目 A1–A8，并把**被驳回**的四条（X1–X4）连同证据写在这里，避免下一轮重复提出。全部证据均在 2026-11-01 对 `a41ce22` 的工作树复核；v4 不引入任何 host/SQL/design/vectors 改动。

| # | 优先级 | 裁决 | 结论 | 落实位置与证据 |
|---:|---|---|---|---|
| A1 | P0 | R10 的 `target = min(ids, key=ids.get)` 返回键（ordinal），不是 UUID，`inject_after(effect_id=...)` 永不命中 | **accept（真实缺陷）** | `ids = {i: T(model_id, i)}` 的键是 ordinal、值是 UUID；`min(dict, key=dict.get)` 遍历键、返回的也是键。改为 `target_ordinal = min(ids, key=ids.get)` + `target = ids[target_ordinal]`；effect 断言/注入用 `target`，描述执行顺序用 `target_ordinal`。§8 R10 Setup 与第 1/2 步，§17.1 #13 指针；v6 再把 `min(ids, key=ids.get)` 换成 `tool_order`（§17.4 A25） |
| A2 | P1 | R03 子进程异常会沿继承的上下文管理器/`atexit` 跑父进程清理；父进程 `killpg(child_pid)` 无效 | **accept** | 子进程分支整体 `try/except BaseException: os._exit(1)`、正常结束 `os._exit(0)`；`os._exit` 不展开栈、不跑 `finally`/`__exit__`/`atexit`。`fork()` 出的 child 不是进程组 leader（pgid 仍是父测试进程的），`killpg(child_pid)` 只会 `ESRCH` 或误杀无关组；超时改 `os.kill(child_pid, SIGKILL)` + `waitpid`，用 `reaped` 防重复回收。插件仍按 spawn log 的 pid `killpg`（`process_io.py:112` 的 `start_new_session=True`，pid == pgid）。D4 第 4/5 步、§7.4、§8 R03 第 3/5 步、§9 I6、§13 R1 |
| A3 | P1 | `assert_no_live` 自己在 `finally` 里 `killpg`，会造成假阳性 | **accept** | R13 先检查插件 pid，`killpg(plugin_pid)` 会顺带杀死同组孙进程，随后检查孙进程必然通过。改为只观察（`ps -o stat=`）、不发任何信号；插件 pid 与孙进程 pid 两条断言都完成后，才由 case 最外层 `finally` 清理插件进程组。§7.1 #13、§8 R13、§9 I6 |
| A4 | P1 | helper 清单缺 `assert_w7_invariants`；audit 7 的 import allowlist 漏项 | **accept** | §9 要求每个 case 调 `assert_w7_invariants`（v5 明确为只对 `rNN_*`，现有 G12 不调用），但 §7.1 的清单与 §10.3 审计 7 都没列。补为第 15 组，计数从 **14 组 / 16 个**改为 **15 组 / 17 个函数·类**（§7.1、§10.3、§12.1、§11 W7-1、§17.1 #10 指针）。import allowlist 补 `HostDB`（`v24/host/db.py`）、`PluginDispatcher`（`v24/host/plugins.py:75`）、`install_spawn_log`（`v24/s13/fixtures.py`）与既有的 `_owner`。只改清单/allowlist 文字，不改审计判定标准，不加文件 |
| A5 | P2 | Result 要求回填本次 commit SHA，与“先落文档、再一次里程碑提交”矛盾 | **accept** | 文件不可能包含自身 commit SHA。Result 只记 sweep HEAD、验证结果与 **external publication receipt 的位置**；commit SHA / push 结果留在 receipt。§14、Result |
| A6 | P2 | R09 的 `read_ord = order[-1]; assert order.index(read_ord) == 2` 是同义 guard | **accept** | `order[-1]` 按定义就在末位，断言恒真、无证据价值。删除该断言，保留 §8 R09 对**实际 `dispatch_finished` 顺序 == `order`** 的断言；并写明 3 个 UUID 互不相同且必然可排序、最大者一定存在、不需要 skip 分支。§3 第 6 条、§8 R09 第 4 步与负分支、§9 I5、§13 R15、§17.1 #16 |
| A7 | P2 | 6500ms 对 6000ms 门槛只有 500ms 余量，计划未写抖动处理 | **accept** | 补：子进程 claim 后立即 spawn；CI 抖动导致 `remaining < 6000` 时测试 **FAIL** 并记录实际 `remaining`，**不得**把 lease 调到 30s 规避。D5、§13 R2 |
| A8 | P2 | R07 第 5 步只断言 `S(install)["prepare"] == 1`，幂等不够硬 | **accept** | 增加 `host_effects(scope)` 中 `host_prepare` effect 计数不增加。注意 `host_effects` 只返回 `ready`/`claimed`（`49_host_reads.sql:183-184`），第 4 步后 prepare effect 已 settle、计数为 0；重复 prepare 会以 `ready` 出现、计数变 1。R07 只有一个 install，不需要“允许其它 install 新增 prepare”的例外。§8 R07 第 5 步 |

**驳回记录（附证据，保留原写法）**

| # | 被驳回的裁决 | 证据 | 处置 |
|---:|---|---|---|
| X1 | “`uuid.UUID(hashlib.md5(...).hexdigest())` 非法，必须切成 8-4-4-4-12” | `md5().hexdigest()` 恒为 **32 位**小写十六进制；`uuid.UUID()` 接受 32 位无连字符形式。实测 `uuid.UUID(hashlib.md5(...).hexdigest())` 成功，且与按 `8-4-4-4-12` 切分构造的 UUID **相等**（即与 PostgreSQL `md5(...)::uuid` 等价）。 | 保留 §7.1 #3 原写法；不引入切分 helper、不改 `tool_effect_id` |
| X2 | “R15 的‘5 轮后 idle’与 `run_until_idle` 矛盾” | `run_once` 每轮只执行一个 ready effect：`effect = ready[0]`（`worker.py:686`），紧接着一次 `_claim_and_execute`（`:687`），`ready` 来自 `_discover_ready`（`:683`）；`run_until_idle` 在 `progress == 0` 时置 idle（`:107-119`，判断在 `:115`），`progress` 只累加 claimed/executed/settled/reconciled/recovered（`:75-76`）。R15 第 1 轮 model、第 2–4 轮三个 tool（patched `db.settle` 返回 error，但 claimed/executed 仍计 progress）、第 5 轮无 ready 且 `reconciled=0` → `progress == 0` 才 idle。探针实测 5 轮。 | 保留“5 轮后 idle”；断言仍以 `stats.idle is True` 为准，不写死轮数 |
| X3 | “R16 的 `inject_before` 过滤不能排除 `reconciled=True`” | 过滤条件已含 `not payload.get("reconciled")`（§8 R16 第 5 项）。`_reconcile` 的 claimed 分支写 `{"outcome": outcome, "response": result, "reconciled": True}`（`worker.py:785-788`），被该项排除；`database_terminal` 分支写 `{"conflict": ..., "reason": "database_terminal", "outcome": ...}`（`:790-797`），被 `"reason" not in payload` 排除；model settlement 被 `payload.outcome.body.kind == "tool_call"` 排除；`claim_token_changed` 被 `"reason"` 排除。`_record_settlement` 本身只做 `has()` 去重后 append（`:800-804`），不新增 payload 形状。 | 过滤条件不变；措辞统一为“`payload.get("reconciled")` 为假”（D3、§8 R16、§13 R17） |
| X4 | “R14 的 `C(3)` 会被 `inspect_resource` 破坏” | R14 不 `off`/`dispose`/`close_scope`，没有任何路径创建 `inspect_resource`：host 侧只有 `resource_handler` 对已存在的 kind 分派（`plugins.py:93`），创建它的是 SQL 侧的 inspect 请求（`40_interpreters.sql:1444/1463/1602/1633` 的 `inspect_resource` 分支），R14 不触发。且 R14 已断言 `c.ops == {"prepare":1,"invoke":2}`，精确 ops 已排除 `inspect`/`release`。 | 保留 `C(3)` 与精确 `ops` 断言 |

**v4 一致性**：`cases=30`、`recovery_probes=16`、marker 全文、closeout 11/11、32-command 形态与 8 路径候选集**全部不变**；唯一计数变化是 A4 的 helper 组数/函数数（14/16 → 15/17），只改 §7.1 清单与 §10.3/§12.1 的 allowlist 文字，不新增文件。v4 不重开 X1–X4，也不把“已驳回”重述为“未决”。仍存疑项见交付说明，不在本计划内自行放宽。

### 17.3 v5 修订（2 路 Oracle 第三轮）

第三轮同一 2 路 Oracle（L1/L2）仍判 `needs-edits`、**无 P0**；剩余 P1 收敛为三类，P2 九条。v5 落实 A9–A20，并把两条**被驳回**的裁决记在 X5/X6，另加一条落实时的证据修正（`host_effects` 的枚举边界）。全部证据于 2026-11-01 对 `a41ce22` 工作树复核；v5 不引入任何 host/SQL/design/vectors 改动。

| # | 优先级 | 裁决 | 结论 | 落实位置与证据 |
|---:|---|---|---|---|
| A9 | P1 | `assert_w7_invariants(harness, run_id)` 是 run 级，无法覆盖同 case 的其它 run，也无法表达“哪些 effect 应该有 recovery event” | **accept** | 改为 `def assert_w7_invariants(harness, *, recovered_unknown=frozenset())`，**去掉 `run_id`**；I1/I2/I4 按 `harness.scope` 枚举全部 tool effect（R11 有 5 个 run、R14 有 3 个 run，单 run 枚举会漏）。I2 逐 effect：`effect_id in recovered_unknown` → `effect_recovered_unknown` 恰 1（payload `action="settle_unknown"`、`reason="lease_expired"`；v6 把成员判断改为规范字符串，见 §17.4 A21）；否则恰 0（正常 settle 不要求 effect-level event）。R02/R03 传 `{target}`，R09/R13 及其余 case 传空集/省略；R07/R08 用 scope 级检查；continuation、model effect 计数等 run 级断言留在 case 内。§7.1 #15、§9 开头、I1/I2/I3/I4、§3 第 10 条、§8 R02/R03/R09/R13、§10.3、§11 W7-1、§12.1 |
| A10 | P1 | `run_recover_process` 内部已 `close_connections`，R05/R14/R15/R16 又各调一次，关闭点分散 | **accept** | 删除四处 case 内的显式 `close_connections`，让 `run_recover_process` 独占 journal→db→owner 的关闭责任；R15 调用前只恢复 `harness.db.settle = original`，R16 调用前先 `capture_effect`。§7.1 #12 写明“调用者不得再重复 close”，§7.1 #5 与 §8 R05/R14/R15/R16 同步 |
| A11 | P1 | R02 的 restore 若用 `del worker._execute_tool`，`is original` 恒为 False | **accept** | `_execute_tool` 是类方法（`worker.py:1027`），`del` 只退回类属性，之后每次访问都新建 bound method。§7.1 #9 改为把保存的 bound method **重新赋值**（`worker._execute_tool = original`）；§8 R02 第 3 步指向 #9 |
| A12 | P2 | §13 R13/R18 写 `patch.stop()`，但 R15 是直接赋值 `harness.db.settle = patched`，没有 `unittest.mock.patch` | **accept** | 两处改为“恢复 `harness.db.settle = original`（直接赋值，没有 `patch.stop()`）”。§13 R13、R18 |
| A13 | P2 | §8 记号行与 §11 W7-5 仍有 “guard” 措辞 | **accept** | 两处改为“由 journal 实际 `dispatch_finished` 顺序断言”。§8 记号 `T(...)` 一行、§11 W7-5 |
| A14 | P2 | §11 W7-1 逐个重列 helper，与 §7.1 清单重复且易漂移 | **accept** | 改为“见 §7.1 #1–#15：15 组 helper（17 个函数/类）”，只保留 `assert_w7_invariants` 的 scope 级/`recovered_unknown` 两个新增特征。§11 W7-1 |
| A15 | P2 | R03 第 5 步先 `killpg` 插件再 `assert_no_live`，被当成“host 自动清理”的证据 | **accept** | 写明这是**测试侧清理**，只证明测试侧清理干净；host 自动组杀的唯一证据是 R13 的 timeout 路径（`process_io._kill_group`，`:82-86/133-138`）。§8 R03 第 5 步、§9 I6 首条 |
| A16 | P2 | §10.5 把 R08 写成 “1 fresh crash”，R14 的预算描述漏了第二次 v2 read | **accept** | R08 改“1 in-process cut-point crash”（R07/R08 是 journal cut-point，不是 SIGKILL，见 §15）；R14 改“v1 prepare+2 invoke + 两次 v2 read + fresh”。§10.5 |
| A17 | P2 | R13 外层 `killpg` 在进程组已不存在时的 `ESRCH` 未定义 | **accept** | 两个 pid 的观察断言都通过后，外层 `killpg` 返回 `ESRCH` 视为**成功**（already_gone）；其它 errno 只记录、不掩盖主断言。§8 R13 Assert、§9 I6 |
| A18 | P2 | R13 缺“孙进程消失只能来自组级 kill”的推理句 | **accept** | 补：`.child` 证明孙进程启动过；测试在观察前不发信号；stub 与孙进程都 `sleep(60)`，远大于 2s 观察窗口；插件被 SIGKILL 不会连带杀死孙进程（孙进程被 reparent 后继续 sleep），因此孙进程在窗口内消失只能来自组级 kill。§8 R13 Assert |
| A19 | P2 | publication receipt 只写“external”，没有固定路径与内容 | **accept** | 固定 `/tmp/v24-abi-w7-<UTC>/publication-receipt.txt`（**不入 repo**），内容为 commit SHA、`git push` 退出码与远端 ref 更新行、push 后 `git rev-parse origin/main`、UTC 时间。§10.4 文件清单、§14 规则、Result 只引用该路径 |
| A20 | P2 | §16 把 `line_json.py:274` 写成“v2 `run_process`”，未说明 v1/v2 是否同一条路径 | **accept** | `:274` 是 `_run_v2` 内的调用点、`:319` 是 v1 `run` 内的调用点，两者都调用**模块级** `run_process`，所以 patch `line_json.run_process` 同时覆盖 v1/v2；并补 `db.host_effects(scope)` 三个游标参数有默认值（`db.py:144-149`）。§16 |

**驳回记录（附证据，保留原写法）**

| # | 被驳回的裁决 | 证据 | 处置 |
|---:|---|---|---|
| X5 | “`host_effects(harness.scope)` 单参调用会 TypeError” | `db.py:144-149` 的签名是 `host_effects(self, scope, after_created_at=None, after_effect_id=None, limit=64)`：单参绑到 `scope`，其余三个游标参数全有默认值；`host_runs` 同样（`:138-141`）。现有 R07 第 5 步本来就用单参 `harness.db.host_effects(harness.scope)`，若该裁决成立，现有计划早已不自洽。 | 保留 R07/R08 的单参写法；写成四参也合法，但不是必须；#15 的 pending 检查继续用单参 |
| X6 | “`RoundingSpawn` 命名不一致” | 全文检索无 `RoundingSpawn`；只有 `CountingSpawn`（§7.1 #1、§8 `C(n)` 记号、§9 I4、§12.1、§17.2 A4/X4）。`C(n)` 是 §8 的记号，展开为 `with CountingSpawn(expected=n) as c:`，不是第二个类名。 | 无需改名；不新增/重命名 helper |

**注（`host_effects` 的枚举边界，落实时的证据修正）**：v5 指示里的 `db.host_effects(harness.scope)` 单参**合法**（三个游标参数都有默认值），但它只返回 `status IN ('ready','claimed')` 的 effect（`49_host_reads.sql:184`）。若用它枚举“scope 内全部 tool effect”，case 结束时所有 effect 都已 settle，结果恒为空集，I1/I2 会退化成空真。因此 §7.1 #15 的“全部”改用不按状态过滤的两级读：`host_runs(scope)`（`:76-127`）→ `host_run_effects(run)`（`:209-287`，只含 `model_call`/`tool_call`，正好覆盖 I1/I2 的对象）；`host_effects(scope)` 保留为“case 结束时没有残留 `ready`/`claimed` 的 tool effect”这一条断言，单参写法不变。这不是驳回 Oracle，也不改任何 case 的期望值。若下一轮仍要求只用 `host_effects` 枚举，等价于让 I1/I2 在 case 结束时失去证据力；本计划不接受这一退化，保留两级读。

**v5 一致性**：`cases=30`、`recovery_probes=16`、marker 全文、closeout 11/11、32-command 形态、8 路径候选集与 helper 计数（15 组 / 17 个）**全部不变**；R05/R14/R15/R16 只是少一次重复 close，不改步骤数与期望；R02 只改 restore 的写法，不改 `crash_after` 语义；R13 只加 ESRCH 与证据链说明，不改观察顺序。v5 不重开 X1–X6，也不把“已驳回”重述为“未决”。

### 17.4 v6 修订（第三轮：lane1 pass / lane2 needs-edits）

v5 送第三轮 2 路 Oracle：lane 1 判 `pass`，lane 2 判 `needs-edits`，**无 P0**；合并后剩两条 P1（可执行性缺口）与 A23–A26 四条 P2（措辞/适用范围）。v6 落实 A21–A26，不引入 host/SQL/design/vectors 改动，也不改变 `cases=30`、`recovery_probes=16`、marker、closeout 11/11、32-command 形态、8 路径候选集或 helper 计数（15 组 / 17 个）。

| # | 优先级 | 裁决 | 结论 | 落实位置与证据 |
|---:|---|---|---|---|
| A21 | P1 | `recovered_unknown` 的元素是 `uuid.UUID`，而 DB/journal 枚举出的 `effect_id` 是字符串，`effect_id in recovered_unknown` 恒为 False | **accept（真实缺陷）** | helper 入口 `expected = {str(item) for item in recovered_unknown}`；枚举每个 effect 用 `key = str(effect["effect_id"])`；成员判断一律 `key in expected`。R02/R03 仍可传 `{target}`（`uuid.UUID`），由 helper 归一；`v24.events` 查询仍用 UUID 参数。§7.1 #15、§9 I2、§3 第 10 条 |
| A22 | P1 | R02 的 `original` 在 helper 内是局部变量，case 取不到；调用者自己再取 bound method 会让 `is` 恒 False | **accept** | `install_crash_after_started(worker) -> tuple[restore, original]`：保存并返回 `original = worker._execute_tool`，restore 把 `original` 重新赋值回去。R02 第 3 步解包并用返回的 `original` 断言 `harness.worker._execute_tool is original`；`finally` 先 `restore()`。调用者不得自己再取 bound method。§7.1 #9、§8 R02、§13 R16 |
| A23 | P2 | `close_connections` 的调用方未写死，与 R03/R06 及 R05/R14/R15/R16 的关闭责任冲突 | **accept** | 调用方**仅限** R03 fork 前、R06 restart 前与 `run_recover_process` 内部；只禁止 R05/R14/R15/R16 的 fresh-process recovery action 再调。`reopen_harness` 自己只重开、不负责关闭。§7.1 #5、§7.4、§8 R05/R14/R15/R16 |
| A24 | P2 | §9 I6 的“两个 pid 都先观察、再由外层清理”被误读为也约束 R03 | **accept** | 该顺序**只约束 R13**；R03 保持“测试侧先 `killpg` 插件组、再 `assert_no_live`”，只证明测试侧清理，不证明 host 自动组杀。`ESRCH=already_gone` 对 R03 的测试侧 killpg 与 R13 的外层 killpg 都适用。§9 I6、§8 R03/R13 |
| A25 | P2 | §7.1 #3 说 R09/R10/R16 用 `tool_order`，但 v5 的 R09/R10 实际写的是 `sorted(ids, key=ids.get)`/`min(ids, key=ids.get)` | **accept** | R09 用 `order = tool_order(model_id, 3)`；R10 用 `target_ordinal = tool_order(model_id, 3)[0]`、`target = T(model_id, target_ordinal)`；R16 只有一个 tool，用 `T(model_id, 0)`。§7.1 #3、§8 R09/R10 |
| A26 | P2 | I4 未说明如何枚举 install，也未区分无 spawn log 的 v1 | **accept** | helper 用 `db.host_scope_installs(scope, None, 64)` 按 `has_more`/`next_cursor` 翻页取 install（`db.py:159-161`；`after` 取 `next_cursor["install_id"]`），再 `install_spawn_log(harness, install_id)` 取 log；返回 `None` 的 install（R14 的 v1）跳过 scope 部分，由 case 内 `CountingSpawn` 负责。helper 部分改名为“log 自洽 + 无重复 prepare/release”；精确 `invoke` 期望仍在 case，marker 的 `second_spawn=false` 由 case 内精确计数支撑。§9 I4、§7.1 #15 |

**已核实（替代 W7-1 的“待预检”）**

以下四项原先挂在 W7-1 的“待预检”名下；v6 已对 `a41ce22` 工作树只读核实，降为静态已核实事实。它们只降低计划风险，不作为 W7 pass 证据；W7-1 只保留运行时探针（helper 实跑、stub 两 scenario、`realm`）。

| 事实 | 证据 | 用途 |
|---|---|---|
| `v24.events` 的列名是 `effect_id`/`entity_type`/`entity_id`/`event_kind`/`payload` | `v24/sql/10_schema.sql:231-244`（`u_events_once` 唯一约束在 `:244`） | I2 用 `event_kind='effect_recovered_unknown'`、`entity_type='effect'`、`entity_id=<effect_id>` 定位；不猜列名 |
| `host_run_effects` 的 item 含 `replay_policy`；SQL **不按 status 过滤**，只含 `model_call`/`tool_call` | `v24/sql/49_host_reads.sql:209-287`（item 的 `replay_policy` 在 `:253`） | I1 直接读 `replay_policy`；I1/I2 的枚举不会漏掉已 settle 的 effect，也不会混入 resource effect |
| `host_runs(scope)` 返回 scope 内全部 run 的 projection | `v24/sql/49_host_reads.sql:76-127` | #15 的两级枚举先从 run 出发；不假设 run 状态 |
| `host_scope_installs(scope, after=None, limit=64)` 已存在 | `v24/host/db.py:159-161`；SQL `v24/sql/49_host_reads.sql:349-358` | I4 的 install 枚举；按 `has_more`/`next_cursor` 翻页（`after = next_cursor["install_id"]`），不写死 64 |

**v6 一致性**：`cases=30`、`recovery_probes=16`、marker 全文、closeout 11/11、32-command 形态、8 路径候选集与 helper 计数（15 组 / 17 个）**全部不变**。A21/A22 只改 helper 的返回值与比较口径，不改任何 case 的期望；A23 只收窄 `close_connections` 的调用点，不增加/删除 case 步骤；A24 只改 I6 的适用范围文字；A25 只把 R09/R10 的临时排序换成 §7.1 #3 的 helper；A26 只改 I4 的枚举与命名，不改精确 `invoke` 期望。v6 不重开 X1–X6，也不把“已驳回”重述为“未决”。

## Result

实际执行日期 **2026-11-01**（+08:00；证据目录 UTC 标记 `/tmp/v24-abi-w7-20261031T200002Z/`）。sweep HEAD **`a41ce22`**（`a41ce220b60af95070d93ce1571d09d70299a5cf`），`origin/main` 同点；工作区只含本计划的 8 路径候选。

**32/32**：第 1–31 条串行命令全部 exit 0 且有命令专属 `[passed]` 末行，第 32 条 `git diff --exit-code c8c4bd0 -- v24/sql` exit 0、输出为空；无 exit 2/`[SKIP]`。第 14–24 条仍是 11 条 closeout 命令，closeout **11/11** 不变，s13 不是第 12 条。

row 30 末行：

```text
[passed] W4 lifecycle; cases=30; recovery_probes=16; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true; no_replay=true
```

`cases=30` 为函数级计数（W4c 的 14 个子场景 + R01–R16 各 1），`recovery_probes=16`；`test_lifecycle.py` 2,849 行，实测墙钟 ≈40.4 s，sweep row-30 窗口 `2026-10-31T20:03:34Z` → `2026-10-31T20:04:14Z`，低于 90 s 硬上限。

七项 scope audit 的末行（precheck 与文档落盘后的 final 均 exit 0；confirmation 结果只记入外置 receipt）：

| # | audit | 末行 | precheck | final |
|---:|---|---|---|---|
| 1 | `frozen_modules_and_untracked` | `[scope] passed frozen_modules_and_untracked` | exit 0 | exit 0 |
| 2 | `vectors_zero_diff` | `[scope] passed vectors_zero_diff` | exit 0 | exit 0 |
| 3 | `design_pins_zero_diff` | `[scope] passed design_pins_zero_diff` | exit 0 | exit 0 |
| 4 | `registry_exact_patch` | `[scope] passed registry_exact_patch` | exit 0 | exit 0 |
| 5 | `host_import_purity` | `[scope] passed host_import_purity` | exit 0 | exit 0 |
| 6 | `sql_zero_diff` | `[scope] passed sql_zero_diff` | exit 0 | exit 0 |
| 7 | `w7_candidate_only` | `[scope] passed w7_candidate_only` | exit 0 | exit 0 |

候选 8 路径 SHA-256（final audit 后、本 Result 落盘前；本文件不能包含自身 digest）：

| 路径 | SHA-256 |
|---|---|
| `v24/s13/test_lifecycle.py` | `4b11c4f4690b31bcfa4be912e38b879a754cba1c5a01a8080ae618302365e47f` |
| `v24/s13/w4_stub_plugin.py` | `916ca5b2e997a4ba0386c51b18b0da3663d00772d67497d7753c75d95fa634fa` |
| `v24/s13/w7_recover.py` | `d5c3178038577053d651f1ad53e2d3895f417503253a17045995d8e36d39b85d` |
| `v24/s13/README.md` | `08b2a0c99805d88f92d15c4c61a07e157f31d38215922acf5358a1bd1b81ea54` |
| `docs/reviews/v24-conformance-matrix-2026-10-23.md` | `39517c2a9df9daa335584c362e00a5d0a6c96a8f61e3f08bb0d9ccc1f0ae2e6d` |
| `docs/reviews/v24-deviation-ledger-2026-10-23.md` | `74fc108425ff779b4446f110d043ef4d08ed256436954f7f2b998685329f25b2` |
| `docs/reviews/v24-tool-plugin-abi-w7-execution-2026-11-01.md` | `80a9a9232134135c6401f5f99d964aba7c7a69a61387fef522537f6e15fd77c0` |
| `docs/plans/v24-tool-plugin-abi-w7-lifecycle-recovery-2026-11-01.md` | 本文件自身；最终 digest 记入 `source-sha256.txt` 与 `publication-receipt.txt` |

进程清理观测：**R03 只证明测试侧清理**——host 子进程 `WIFSIGNALED=true`、`WTERMSIG=9`/`SIGKILL`，`invoke` 1→1；插件在崩溃瞬间仍为 live（`ps stat=Ss`），测试侧 `killpg` 后才 `ps=""`。**R13 才是 host 自动组杀**——插件与孙进程在 1.131 s 内都变为空 `ps stat=`，测试在观察前不发信号，孙进程只能由 host 的 `process_io._kill_group` 清除；restart `reconciled=0`、journal 12 条与 3 个 settlement 不变。

R15：3 个 pending（`claimed`、`dispatch_finished` 有、settlement 0）由 fresh process 一次 `reconciled=3 settlements=3`，三个 effect 均 succeeded、continuation 恰 1、spawn 计数不变。R16：K3.5 的 fresh process `reconciled=0 settlements=1`，payload `reason=database_terminal`、`conflict=false`，effect row 不变，第二次 `_reconcile=0`。

Publication：commit SHA / push 退出码 / 远端 ref 更新行 / push 后 `git rev-parse origin/main` / UTC 时间 / 8 路径 manifest，全部记录在 **`/tmp/v24-abi-w7-20261031T200002Z/publication-receipt.txt`**；本文件不嵌 commit SHA（§17.2 A5）。

**无 W7-8 偏差**：`v24/host`、`v24/sql`、`v24/s13/vectors`、design、pins 与其余 s13 测试零 diff，B0 字节不变，所有 tool effect 仍 `no_replay`；W7 不是 M4 重开、不是 M6、不是 closeout 第 12 条。
