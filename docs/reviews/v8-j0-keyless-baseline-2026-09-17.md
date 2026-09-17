# V8 J0 keyless 基线实跑报告 · 2026-09-17

## 准出结论

**同一 fresh run：24/24 产品脚本 exit 0，failed=0、not_run=0；completed=true、interrupted=false、source_drift=false、eligible=true。**
runner 自检实跑 45 checks 通过（不计入 24 个产品 gate）。默认全程 keyless，没有调用真实 provider，也没有构建/运行 DSH。

## 唯一证据与 provenance

- final_run_id：`20260917T091425Z-62995f8be0f94c96b88a094c27dabca6`
- JSON：`v8/compat/evidence/j0/20260917T091425Z-62995f8be0f94c96b88a094c27dabca6.json`
- JSON SHA256：`f209c2b352beb537c08cfb4728b9dbcf7c1e2daf21e0d6f801a04219e433966a`
- base_commit：`2b0edf64638872ab06157e5968186e6a814b571f`（实施前 HEAD，不伪称为尚未生成的提交）
- working source_snapshot_digest：`bc3c3ba989046f484092b4ea7581146105cf6f9f1e5daf3e9d8bfd599c3e26a2`
- 源文件数：113；逐文件路径/SHA256 在 JSON 中。
- UTC：`2026-09-17T09:14:25.220909+00:00` → `2026-09-17T09:15:15.412682+00:00`；runner 计时 49.844 秒。
- 环境：Python 3.12.13；uv 0.8.24 (252f88733 2025-10-07)；PostgreSQL 18.4；pgembed 0.3.0rc2。
- dirty_paths 如实记录未提交工作区；无关 v11/其他计划不属于 J0 提交。运行前后源快照一致；文档收尾后再次核对源 digest。
- 若 JSON 缺失或 SHA256 不符，本报告无效；不得跨 run 拼接或将中断 checkpoint 续写为成功。最终提交与推送结果在交付消息记录，避免证据自引用提交循环。

## 全部实际命令与结果

命令为清单 argv；G13 由 runner 额外附加 `--report-json <private-run-dir>/g13-report.json`。占位符代表本次独有私有目录，真实路径不归档。所有测试库串行重建。计数仅 stdout 中以 `[PASS]` 开头的行数，不等同独立断言数。

| Gate | 命令 | DB 组 | exit | state | PASS 行 |
|---|---|---|---:|---|---:|
| G1 | `uv run python v8/canonical/test_canonical.py` | 无 | 0 | passed | 196 |
| G2 | `uv run python v8/schema/test_schema.py` | agent_v8_schema | 0 | passed | 86 |
| G3 | `uv run python v8/events/test_events.py` | agent_v8_events | 0 | passed | 130 |
| G4 | `uv run python v8/effect/test_effect.py` | agent_v8_effect | 0 | passed | 297 |
| G5 | `uv run python v8/loop/test_loop.py` | agent_v8_loop | 0 | passed | 250 |
| G6 | `uv run python v8/tools/test_tools.py` | agent_v8_tools | 0 | passed | 333 |
| G7a | `uv run python v8/retry/test_retry.py` | agent_v8_retry | 0 | passed | 258 |
| G7b | `uv run python v8/retry/test_takeover.py` | agent_v8_retry | 0 | passed | 134 |
| G7c | `uv run python v8/repair/test_repair.py` | agent_v8_repair | 0 | passed | 214 |
| G8a | `uv run python v8/cancel/test_cancel.py` | agent_v8_cancel | 0 | passed | 93 |
| G8b | `uv run python v8/cancel/test_closure.py` | agent_v8_cancel | 0 | passed | 222 |
| G9a | `uv run python v8/stream/test_stream.py` | agent_v8_stream | 0 | passed | 51 |
| G10 | `uv run python v8/grant/test_grant.py` | agent_v8_grant | 0 | passed | 144 |
| G11 | `uv run python v8/plugin/test_plugin.py` | agent_v8_plugin | 0 | passed | 207 |
| G12 | `uv run python v8/gates/test_gates.py` | agent_v8_gates | 0 | passed | 165 |
| G13 | `uv run python v8/compat/test_compat.py --report-json <private-run-dir>/g13-report.json` | agent_v8_compat | 0 | passed | 181 |
| G14 | `uv run python v8/concurrency/test_concurrency.py` | agent_v8_concurrency | 0 | passed | 102 |
| G9b | `uv run python v8/stream/test_observation.py` | agent_v8_stream | 0 | passed | 72 |
| G16 | `uv run python v8/audit/test_audit.py` | agent_v8_audit | 0 | passed | 106 |
| G17 | `uv run python v8/compact/test_compact.py` | agent_v8_compact | 0 | passed | 86 |
| G15 | `uv run python v8/drain/test_drain.py` | agent_v8_drain | 0 | passed | 107 |
| G18 | `uv run python v8/reconcile/test_reconcile.py` | agent_v8_reconcile | 0 | passed | 143 |
| G19a | `uv run python v8/assemble/test_assemble.py` | agent_v8_assemble | 0 | passed | 35 |
| G19b | `uv run python v8/closeout/test_closeout.py` | agent_v8_closeout | 0 | passed | 70 |

## G13 实际报告（不是合成全绿 fixture）

- fake suite：passed；optional real-provider smoke：not_run / not_requested。
- 行计数：passed=9 / failed=0 / blocked=11 / partial=9 / not_run=1。
- declared_support_surface_conformant=false：pinned 尚未解析且 compat 必跑执行面仍有 partial。
- minimal_dual_loop_passed=false：没有真实 compat loop；最小双运行时行 blocked。
- full_target_achieved=false；compat_contract_passable=false；compat_contract_passed=false（未终签）。
- unmapped_failed_fixtures=[]；故意失败 demo/合成 catalog 只在测试内部使用，未污染实际报告。
- 具体 blocker 列表和 capability matrix 见 JSON 完整 schema-v2 报告。

## 已验证与保留边界

- W1：fake/live 拆分、无 key/哨兵 key 零 live、精确登记、显式缺凭据 exit 2、失败传播、重复 main 状态重置及原子报告写入。
- W2：六拒收各自精确 code、not_run/reason 结构校验、未实现不得自报通过、partial/failed/unmapped/pinned 阻断、三结论与旧字段/render 的合成正负向。
- W3：清单/README 一致；凭据与 dotenv 隔离；串行/锁/进程组 timeout 与 SIGINT；失败/中断/源漂移不准出；旧损坏 checkpoint 不续用；secret 哨兵不进入证据；G13 缺失/无效报告为 unavailable。自检首次超时用例用 0.1 秒误伤正常假进程，已改为 1 秒，仍对 30 秒睡眠进程验证强制终止；修复后自检全绿才启动本次产品 run。
- W4：stage README、总 README、Conformance #1/#2/#6/#8/#9/#12/#14/#16 与偏差台账 A87/A88/B 已按机制/compat 执行面分别更正，不一律升绿。
- 未改 SQL、v8/load.py、setup_db.py、v8/loop/runtime.py、能力 seed/pinned manifest 或 v8/v10 冻结正文。
- Oracle 实施 review 调用发生 watchdog 后又遇 ACP model metadata 配置错误，未取得实质审查结果；不声称独立 review 已通过。批准计划的既有设计审查仍为其原始结论，不能替代本次实施 review。
- 本轮测试编排修复不消解既有产品协议偏差；DSH pin/probe/PG provider/ledger bridge/双 loop/真实 I/O 与 v10 接入门均不在 J0 完成声明中。

## 安全与可复核性

原始 stdout/stderr 只在私有系统临时目录，未复制进 Markdown 或提交；JSON 仅包含其 SHA256、退出码、计数与安全结构。没有记录环境值、Authorization、provider 请求/响应、数据库 URI 或本机绝对 home 路径。
源集合覆盖 v8 Python/SQL/JSON、server.py、pyproject.toml、uv.lock；排除 evidence、纯文档和缓存。文档更新不改变被测源；若以后源 hash 改变，必须新建完整 fresh run，不沿用本报告。
