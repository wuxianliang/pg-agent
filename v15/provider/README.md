# v15 stage 10 · provider

Gate: `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v15/provider/test_provider.py`（退出码 0 = 通过）。

本 stage 只追加 `v15/provider/v15_provider.sql`，不新增表。`files_through("govern")` 仍是前缀 gate；十个 SQL 文件全部加载后，`agent_v15_provider` 才是合运行时，`agent_v15_govern` 只是前缀库。

Gate 构造 `DeepSeekProvider` 时只注入传输，并把默认 opener 构造罩成 `AssertionError`。不跟随重定向，不走环境代理，不调 `urlopen`。冒烟脚本仍属后续里程碑。

三只时钟：`_begin` 的 `statement_timeout = 30s` 只管转移 SQL；FakeLLM 默认租约 `30s`；真实 HTTP `timeout_s = 120s` 是单调总期限。构造时租约必须 ≥ timeout + 60s；发起 HTTP 前再查 `lease_until - now`，不足同一门槛就不发起调用。mark 已经耗掉一点时间，所以恰好 180s 的租约过不了这一检查，手工跑要留出余量。一个库的 worker 池必须同质：全 FakeLLM，或全同一个真实 provider。价目以 `pricing.py` 里抄录的官方页为准；周一至五 `[09:00, 12:00)` 与 `[14:00, 18:00)` 为高峰，不含节假日日历。
