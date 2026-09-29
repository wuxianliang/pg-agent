# v15 stage 10 · provider

Gate: `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v15/provider/test_provider.py`（退出码 0 = 通过）。

本 stage 只追加 `v15/provider/v15_provider.sql`，不新增表。`files_through("govern")` 仍是前缀 gate；十个 SQL 文件全部加载后，`agent_v15_provider` 才是合运行时，`agent_v15_govern` 只是前缀库。

M1 的 SQL gate 使用注入的假结果直接调用三条 provider 转移，证明拒绝、abandon、记账、栅栏、span、子送达、ACL、hook 把 `V15_PROVIDER_REJECTED` 归一为 `V15_HOOK_ABORT`，以及 keyless 骨架；不构造真实 provider，不打开网络。真实适配器与冒烟脚本属于后续里程碑。

三只时钟在真实 provider 版本中分别是：SQL 转移 `statement_timeout = 30s`；FakeLLM 默认租约 `30s`；真实 HTTP 与 Worker 租约由后续 provider 接线定义。这个 stage 不改变前九个 SQL 文件。
