# v15 stage 10 · provider

Gate: `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v15/provider/test_provider.py`（退出码 0 = 通过）。

本 stage 只追加 `v15/provider/v15_provider.sql`，不新增表。`files_through("govern")` 仍是前缀 gate；十个 SQL 文件全部加载后，`agent_v15_provider` 才是合运行时，`agent_v15_govern` 只是前缀库。

Gate 构造 `DeepSeekProvider` 时只注入传输，并把默认 opener 构造罩成 `AssertionError`。不跟随重定向，不走环境代理，不调 `urlopen`。冒烟脚本不是 gate。

三只时钟：`_begin` 的 `statement_timeout = 30s` 只管转移 SQL；FakeLLM 默认租约 `30s`；真实 HTTP `timeout_s = 120s` 是单调总期限。构造时租约必须 ≥ timeout + 60s；发起 HTTP 前再查 `lease_until - now`，不足同一门槛就不发起调用。mark 已经耗掉一点时间，所以恰好 180s 的租约过不了这一检查，手工跑要留出余量。一个库的 worker 池必须同质：全 FakeLLM，或全同一个真实 provider。价目以 `pricing.py` 里抄录的官方页为准；周一至五 `[09:00, 12:00)` 与 `[14:00, 18:00)` 为高峰，不含节假日日历。

## 冒烟

冒烟脚本不是 gate，也不是合运行时证明。`v15/provider/smoke.py` 不建库、不 `setup`、不开 invoke。

| 调用 | 行为 | 退出码 |
|---|---|---|
| 无 flag | 打印 `not_requested`，不构造适配器 | 0 |
| `--real-provider-smoke` 且无 key | 打印 `credentials_absent`，不调用 `complete` | 2 |
| `--real-provider-smoke` 且有 key | 适配器-only：固定请求 `Reply with exactly: SELECT 1;`，`DeepSeekProvider().complete("<smoke>", 1, request, {"model":"deepseek-flash"})`。成功只打印 host、模型名、`prompt_tokens`、`cost_usd`、`finish_reason` | 0 |
| 已开打后失败 | 异常信息换成 `real-provider smoke failed`（`raise ... from None`），不降级成未跑 | 1 |

stdout/stderr 不打印 content、reasoning、key、`Authorization`。uv 会经 `UV_ENV_FILE` 注入 `.env`；要验证无 key 退出码，必须 `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI UV_NO_ENV_FILE=1`。有 key 的真连不在 gate 里。

手工全链（真实 Worker + 数据库）支持，但不属于冒烟：`Worker(dsn, DeepSeekProvider(), id, lease="180 seconds")`。当时不得有打开的数据库事务。运行者自担该库被模型 SQL 写入的后果。恰好 180s 的租约过不了发起前的剩余租约检查，要留出余量。
