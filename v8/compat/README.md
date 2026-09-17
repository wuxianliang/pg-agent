# G13 / J0：keyless compat 合同与诚实报告

G13 验证 dsh-compat 的 **host 无关数据库合同面**，不是完整官方 DSH loop。
J0 修复凭据缺失早退漏跑 fake，并建立累计 keyless 证据。

## 运行

仓库根执行，测试会 DROP/CREATE `agent_v8_compat`，不要同时启动其他共库测试：

```bash
uv run python v8/compat/test_compat.py
uv run python v8/compat/test_compat.py --report-json /tmp/g13-report.json
uv run python v8/regression/test_baseline_runner.py
uv run python v8/regression/run_baseline.py --manifest v8/regression/v8-gates.json
```

普通 G13 即使环境有 key 也不构造真实 adapter：两个独立 FakeLLM 固定输入，比较完整对象，成功后才登记 passed。`test_keyless_branches` 用哨兵和替身验证零 live、失败传播、结果重置、CLI 退出码及 stale report 清理；替身不算真实 provider 证据。

真实协议探针只在明确授权后使用 `--real-provider-smoke`；J0 验收不执行真实调用：

| 请求 | 结果 | 退出码 |
|---|---|---|
| 默认 keyless | fake/DB/reporter 实跑；smoke `not_run/not_requested` | 必跑集合通过为 0，否则 1 |
| 显式 smoke，缺凭据 | `not_run/credentials_absent`；不调用 generate | 2 |
| 显式 smoke，已执行 | 三协议子例通过为 passed；失败保持 failed | 0 / 1 |

真实调用前后检查连接 idle。协议请求/响应、异常原文不会输出；实际 smoke 失败输出安全错误类别，非零退出。`--report-json` 在所有报告断言成功后写完整 schema-v2 dict 与 UTC 时间戳，临时文件 + fsync + rename；启动时清除同路径旧报告，拒收/失败无报告，写入失败不回退 stdout-only。

## 报告语义

- 输入：passed / failed / partial / not_run。not_run 必须有闭合 reason；not_requested/credentials_absent 仅允许唯一 optional smoke 行。
- blocked **只由** SQL 两维 capability matrix 和既有 external allowlist 推导，不是调用者输入状态。凭据缺失诊断不扩大 blocked 行集。
- 展示为五状态；未实现行保留 gap。显式失败即使展示被 blocked/partial 优先序覆盖，也阻断支持面/完整目标。
- 六类拒收检查稳定 `ReportError.code`，FC4/FC5 的隔离向量使用 test-only catalog，不改变实际实现状态。
- `declared_support_surface_conformant`：合法 capability block 可容忍，其余必跑面通过且 pinned 已解析、无显式失败。
- `minimal_dual_loop_passed`：只描述真实最小双 loop；不代表所有 fixture 通过。
- `full_target_achieved`：前两项均通过且所有 mandatory 行 passed；optional 未执行不阻断，optional 实际失败阻断。
- `compat_contract_passed` 保持 False（未终签）；`compat_contract_passable` 仅为 schema v2 的 full_target 别名。

当前真实报告：9 passed、0 failed、11 blocked、9 partial、1 not_run；三个结论均 False。**脚本绿不等于 P0C 完成，更不等于 v10 正式接入。**

## 累计 runner 与证据

版本化入口清单含 24 个产品脚本，保持 README 顺序和共享 DB 组；自检不是第 25 个产品 gate。runner 删除 provider 凭据、UV_ENV_FILE 并设置 UV_NO_ENV_FILE=1；独占进程锁只协调本 runner，不能阻止手工测试。

严格串行、每项一 attempt、无自动 retry/无 resume。失败可继续收集后续诊断但整轮不准出；中断或清理无法确认则停止后续。超时/中断清理整个测试进程组。每项原子 checkpoint，新 run-id 永不拼接历史绿色项。原始日志仅在 mode-0700 系统临时目录；仓库 JSON 只留 hash、退出码、计数、安全报告和版本/source provenance，无原始日志摘录。G13 报告缺失/无效/timeout 时结论 unavailable，不假装 false 或 passed。

准出要求同一 fresh run 全部 required exit 0、未中断、源集合前后相同。源快照包含 v8 Python/SQL/JSON 和 server.py/pyproject.toml/uv.lock，排除证据与纯文档。

J0 实跑 24/24 通过，runner 自检 45 checks；完整命令、计数、run-id/source digest/JSON SHA256 见 `docs/reviews/v8-j0-keyless-baseline-2026-09-17.md`。`v8/load.py` 与 SQL 未变，不存在待登记的新 SQL。

## 尚未完成

本地 DSH 源码已定位，不等于已验证 pin；固定 manifest 仍 null+note，switch 声明仍 unsupported。真实 compat loop、生命周期套件、真实 I/O、双运行时同 trace、T0–T4 参加面与终签分别待 J1–J7。Native G10–G19 的数据库机制通过不能替代这些证据。
