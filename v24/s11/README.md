# v24 S11 — 最小多语言插件（M-P）

本目录是 M-P 的 reference plugin plane：approved adapter registry → one-shot
line-JSON 子进程 → v24 tool/host receipt。模型仍是 Fake（scripted
transport），不引入真实 provider；Python/Node 插件都是真实本地子进程。

## 命令与三态

```bash
# Python 全生命周期 extension check（M-P 必跑，非第十二条 closeout）
uv run python v24/s11/test_g10.py

# Node 全生命周期（独立证据；SKIP 不算通过）
uv run python v24/s11/test_node.py            # -> not_requested, exit 0
uv run python v24/s11/test_node.py --node     # Node 存在 -> exit 0；缺失 -> SKIP exit 2

# M-P-3：同一 run 内 Python → Node → final（opt-in，非 gate）
uv run python -m v24.host.plugin_smoke --multilingual-smoke
```

三态记录规则：

| 结果 | 含义 |
|---|---|
| exit 0 + `[passed]` | 该层实际运行并通过 |
| exit 2 / `[SKIP] not_run/toolchain_absent planes=...` | **未验证**，不是通过 |
| exit 1 / traceback | 失败，必须归因 |

`test_g10.py` 全绿只证明 Python 生命周期；`test_node.py --node` 是独立的
Node 全生命周期；只有 `plugin_smoke.py --multilingual-smoke` 的同一 run
（Python → Node → final，两个 install 均 disposed）才构成多语言完成证据。

## G10 用例（8 个 ID）

- `G10-A`：registry frozen、真实 artifact/manifest/descriptor digest、
  五字段 lookup、重复/篡改/目录 artifact 拒绝。
- `G10-B`：Python `install → host_prepare → fiber_control(on) → start →
  tool → final → fiber_control(off) → dispose → host_release → disposed`，
  Unicode echo，episode/slot/pin 收口，scope close。
- `G10-C`：exit 3 已知工具错误 → `failure` receipt，无 forced release /
  unknown→success；run 可继续到 final，install 仍可 dispose。
- `G10-D`：坏帧 → `unknown`；run `blocked_unknown`，pin/resource 屏障保留，
  `dispose` 不完成、零 `host_release`。
- `G10-E`：artifact / adapter / descriptor 三个独立 digest 不匹配，各自
  **零 spawn**（安装已完成 prepare，再替换 registry 以隔离工具派发）。
- `G10-F`：冻结 run pin 的 descriptor 字节被篡改而 digest 字段仍匹配 →
  批准项与 pin 字节不等，**零 spawn**。
- `G10-G`：重复 prepare/release reservation 幂等，一行 `host_prepare`、
  一行 `host_release`，第二次 dispose 不重复副作用。
- `G10-H`：line-JSON success / exit 3 / 坏帧 / 第二帧 / EOF / stdout 64 KiB
  超限 / stderr 16 KiB 超限 / 异常退出 / timeout 映射；超限与超时均杀进程组
  并 reap。

## Approved registry 边界

`v24/host/registry.py` 的 `ApprovedAdapter` 是 frozen dataclass，启动代码构造
`ApprovedAdapterRegistry` 后只读。匹配键只使用 install 已有的

```text
(identity, version, manifest_digest, artifact_digest, adapter_digest)
```

匹配后才取得固定 `adapter_id/language/argv/cwd/tool_key`。硬约束：

- `argv`、`cwd`、env 只来自 registry；manifest、tool args、descriptor、模型
  输出都不能拼 argv，且 `shell=False`；
- 无匹配、digest 不符、artifact 不是 cwd 内的常规文件、文件 SHA-256 与批准
  值不等，全部在创建进程前拒绝；
- `descriptor_digest` 在 spawn 前与 **该 run pin 冻结的**
  `descriptor`/`descriptor_digest` 双向比对。比较文本使用 PostgreSQL
  `jsonb::text` 的规范形式（key 按字节长度后字节序、`", "`/`": "` 间距），
  因为 `v24.canonical_json(jsonb)` 就是 `p_payload::text`；
- 不新增 manifest 顶层键、SQL 列或 revision registry。

## line-JSON 合同

`v24/host/line_json.py` 复用 v13 的帧契约但不调用 v13 桥（v13 桥只读第一行，
无法执行本里程碑的额外帧/上限规则）：

```text
request: {"v":1,"operation":"prepare|invoke|release|inspect",
          "reservation":"<idempotency key>","args":{...}}

success: {"ok":true,"result":"<含 JSON object 的字符串>"}   exit 0
error:   {"ok":false,"error":"<code>","message":"<text>"}   exit 3
```

stdout 上限 64 KiB、stderr 上限 16 KiB、默认 deadline 5 s。EOF、坏 JSON、
第二帧、输出超限、超时、异常退出/信号一律 `unknown`；超限/超时先
`killpg` 再 `wait` reap。stderr 只留在内存证据中，不进普通日志。

prepare/release/inspect 沿用既有 host effect result 形状，不新增第二套
lifecycle receipt；幂等键使用 effect request 里的 reservation，工具调用使用
确定性的 `v24:tool_call:<effect_id>`。工具回执按 **parent model effect +
ordinal** 关联，不按 key；同一 key 可重复调用，provider tool-call id 由模型
脚本保证唯一。

## 参考插件与 fixture

`v24/s11/plugins/echo.py` / `echo.js` 实现相同操作：

- `prepare` 校验 reservation 前缀；
- `invoke` 返回 `{"echo":args,"language":"python|node"}`；测试哨兵
  `{"__tool_error__": true}` 走 exit 3；
- `release` 幂等成功；
- `inspect` 按 reservation 前缀报告 `known`/`absent`。

`plugin_fixtures.py` 计算 artifact SHA-256、生成现有 manifest 格式
（`identity/version/requires/provides/adapter_digest`）、构造两个 registry
entry，并用 `PluginHarness` 驱动真实公共生命周期。测试断言 registry 的
artifact/manifest/descriptor digest 与真实文件/pin 一致。

## 偏差

G10/`test_node.py` 使用真实本地解释器子进程，与设计 §9.1「所有 gate 外部
适配器为 Fake」的字面表述有张力。该路径本地、确定性、无网络，解释器必然
存在，判为可接受；已在
`docs/reviews/v24-deviation-ledger-2026-10-23.md` 登记为一条 §9.1 偏差，并把
口径固定为「真实**网络** IO 不进 gate」。Go/Swift/DuckDB 不在本轮范围。

## M-F 后续范围登记（2026-10-25）

第二批语言、D-S7-2 公平性、跨主机租约及 provider 延迟/质量分别移交独立计划；本轮不建占位实现。当前源 `74b3c30` 的 `test_g10.py`、`test_node.py --node` 与 `plugin_smoke.py --multilingual-smoke` 均 exit 0。M-P 发布候选仍须在候选树上重跑 Node 与 multilingual 两条命令；Go/Swift/DuckDB 仍未验证。


## M-P release-candidate verification (2026-10-25)

The clean candidate from v24 source `6d53a2d05a2e5439e7694125d4751ba053acb147` on main base `ab34d6972a17f688c4a11adba89e363d74adbe81` passed G10 Python (8/8), `test_node.py --node` (exit 0), and `plugin_smoke.py --multilingual-smoke` (exit 0). This confirms the existing Python+Node scope only; Go/Swift/DuckDB remain outside this release.

Full candidate evidence and release status: [release record](../../docs/reviews/v24-release-2026-10-25.md).
