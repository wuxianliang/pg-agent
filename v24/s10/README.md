# v24/s10 — G9 scripted provider extension check (M-R)

G9 is an **extension check**, not a twelfth closeout command. It proves the
M-R host worker and the v24 DeepSeek adapter against scripted transports and a
real PostgreSQL fixture. **No real socket is opened and no API key is needed.**
The historical closeout count stays 11/11.

## Run

```bash
uv run python v24/s10/test_g9.py
uv run python v24/s10/test_g9.py --only G9-A,G9-J1
```

Expected last line:

```text
[passed] v24 G9 M-R: 11 case(s): G9-A, G9-B, G9-C, G9-D, G9-E, G9-F, G9-L, G9-J1, G9-J2, G9-J3, G9-R
```

`--only` is a debugging checkpoint; the acceptance run is the no-argument
form above.

## Cases

| ID | Contract |
|---|---|
| `G9-A` | descriptor → safe provider name (`key` + `_` + sha256 prefix), reversible journal map, two provider turns, `reasoning_content` and `tool_call_id` echoed, no `tool_choice` / `parallel_tool_calls` |
| `G9-B` | `stop`/final success, usage `prompt+completion`, `wall_ms`; DB result excludes reasoning, response id and cost; journal keeps provider-only metadata; no key/header |
| `G9-C` | provider tool-call order survives tool effects settling by effect UUID; batch barrier yields exactly one continuation; duplicate provider call ids are a failure, not a replay |
| `G9-D` | mapping table: bad args / unknown tool / missing id / >16 calls / zero calls → `failure`; contradictory finish/message / empty choices / non-JSON / untrustworthy usage → `unknown` |
| `G9-E` | `length` → `unknown` with real usage, truncated text is not final; usage over reserve keeps mapped success and the kernel turns it semantic `unknown` |
| `G9-F` | preflight credentials absent → `failure`, zero HTTP, zero reserve consumed; 400 → `failure`; 3xx/408/429/5xx and timeout / connection interruption → `unknown`, exactly one attempt |
| `G9-L` | `READ COMMITTED`, `statement_timeout=30s`, `lock_timeout=5s`, `idle_in_transaction_session_timeout=5s`; `0 < timeout_s ≤ 239`; lease 61/180/299 s for 1/120/239 s; IDLE before external IO; journal 0700/0600, POSIX lock, closed event set, version/corruption/secret rejection, truncated-tail trim |
| `G9-J1` | crash after `effect_prepared` (no dispatch): re-reads DB eligibility and executes once without a duplicate prepared record; crash after `dispatch_finished`: restart resubmits the stored outcome, zero HTTP, no duplicate effect |
| `G9-J2` | restart after the effect was recovered to `unknown`: old journaled success is a recorded conflict and cannot revive the run |
| `G9-J3` | crash after `dispatch_started`: live lease isolates with zero HTTP; after expiry one `command_recover` sweep → `unknown`, still zero HTTP |
| `G9-R` | closed ten-table catalog, no second queue/claim/journal table; `run_until_idle(max_rounds=1)` executes one of two ready effects; no fairness claim |

## Scripted transport

`ScriptTransport` returns prepared `(status, raw)` pairs. The test also denies
`socket.socket.connect`, `socket.create_connection`, `urllib.request.urlopen`
and `v15.provider.deepseek.build_opener` for the whole run, and restores them
in `finally`. A static scan rejects socket/HTTP imports in `v24/s10/*.py`,
`v24/host/{worker,journal,db,process_io}.py`, direct `FROM v24.*` SQL in the
worker/journal, and any host RPC outside the nine public readers plus
`v24.command_recover` / `v24.advance`.

The adapter uses the official root `https://api.deepseek.com`, model
`deepseek-flash`, `stream:false`, and only the documented body fields. It
reuses `StdlibTransport`, errors and pricing from `v15` without modifying
`v15/**`.

Post-closeout D3 (2026-10-25): v24 fixes `MODEL="deepseek-flash"`; it
has no runtime allowlist and does not consume the v15 allowlist. This round
adds no `--model`, constructor model parameter or model environment override.
A v4-pro integration would require a separate configuration, validation and
pricing contract. External model/deprecation/pricing facts in the earlier plan
retain their 2026-10-24 research date; they were not rechecked here.

## Optional real-provider smoke

```bash
uv run python -m v24.host.smoke
uv run python -m v24.host.smoke --real-provider-smoke
```

- no flag → `not_requested`, exit 0;
- flag + no `DEEPSEEK_API_KEY` → `credentials_absent`, exit 2, no adapter
  constructed and no database opened;
- flag + key → one short start → model → final run through the real adapter.

The smoke never prints the prompt, content, reasoning or key, and keeps the
journal on failure. It is not a gate.

## Boundaries

- G9 proves the M-R host worker, journal, adapter mapping and opt-in entry. It
  does **not** prove real-provider latency, availability, cost or model
  quality; those need the opt-in smoke and are not deterministic gate claims.
- No starvation/fairness claim (`D-S7-2` stays open).
- No cross-host lease, multi-host or M-P plugin/registry claim.
- `v24/host/process_io.py` is scaffolding for a future plugin host; G9 only
  checks its bounds indirectly through the package static scan.


## Post-closeout M-M（2026-10-25）

D3：v24 固定 `deepseek-flash`；无运行时 allowlist，不消费 v15 allowlist。本轮不新增模型参数、环境 override 或 CLI，不修改 adapter 与 v15。closeout 11/11、G9 11/11 均 exit 0；逐命令时间/source/result 见正式后续计划。外部型号与计价事实没有重新查询。

## Post-closeout M-S（2026-10-25）

M-S 修复完整 smoke 的终态核验：`_bootstrap()` 保存已提交的 scope/run/model handles，完成后从 `host_runs` 与 `host_run_effects` 历史读取面核对终态、usage 和 outcome，再绑定核对 journal 的 `dispatch_started`/`dispatch_finished` 与 reply metadata。成功摘要在泄漏检查、资源关闭、fixture 退出、临时目录删除并确认不存在之后才输出；删除启动前失败保留完整 journal，部分删除失败报告仍可读取的证据，不重试。失败与 `KeyboardInterrupt` 路径不打印请求、响应正文、Authorization 或 key。

G9 仍保持 11 个顶层 ID；G9-B/F/L 的既有 smoke 子场景覆盖模型离开 active work list、空 final、唯一 request key、未完成/取消后的 late success、malformed history、分页与 journal 不匹配、初始化/关闭/fixture/删除失败、部分删除，以及 cleanup 期间 interrupt。所有响应继续来自 ScriptTransport，网络 deny 和 borrowed fixture 约束不变。M-S 的 11 条 closeout 与 G9 11/11 均 exit 0；真实 provider smoke 仍是 opt-in，当前未授权且未执行。

## M-E 真实 provider 证据（2026-10-25）

`recorded_at=2026-10-25`。本轮实际执行了两条负控；未检查实际 key 是否存在，无 flag 命令直接短路，flag 负控显式清除凭据；没有取得 live 授权。`negative_control` 与 `live_attempt` 独立记录：

| record_group | executed_at | source_sha | command | status | reason | exit_code |
|---|---|---|---|---|---|---|
| `negative_control` | 2026-10-25T11:05:35+08:00 Asia/Shanghai | `e869e81` | `UV_NO_ENV_FILE=1 uv run python -m v24.host.smoke` | passed | `not_requested` | 0 |
| `negative_control` | 2026-10-25T11:05:35+08:00 Asia/Shanghai | `e869e81` | `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python -m v24.host.smoke --real-provider-smoke` | passed | `credentials_absent` | 2 |
| `live_attempt` | `not_executed` | `e869e81` | 拟执行：`UV_NO_ENV_FILE=1 /usr/bin/time -p uv run python -m v24.host.smoke --real-provider-smoke` | `not_run` | `not_authorized` | `not_executed` |

负控只证明入口短路行为，不证明当前环境本来没有 key，也不证明真实 provider 的成功、失败、延迟、费用或质量。live attempt 的成功摘要（endpoint/model/run/effect/tokens/finish/provider wall_ms）和外部耗时均为 `not_executed`，证明范围为空；D-S7-2 继续开启。
