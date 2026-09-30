# v15 stage 11 · return_hooks

Gate: `uv run python v15/return_hooks/test_return_hooks.py`（退出码 0 = 通过）。只用 FakeLLM，不开网络。

库名 `agent_v15_return_hooks`。`load_stage(..., "return_hooks")` 加载全部十一个 SQL 文件。这是合运行时库。`agent_v15_provider` 与更早的 `agent_v15_*` 仍是前缀库。

本 stage 不新增表。M1 只放可加载的 helper 占位；validation effect builder、ReturnType handler 与 ValidateReturn 注册协议在后续里程碑。`return_type` 的 CREATE、权限与 `hook_defs` 插入仍只许出现在 govern 文件。

M1 已落地：`P1540` / `V15_VALIDATION_FAILED`、`v15_loop_accept_forcing` 的计数 id 泛化（不改名）、`return`→`raise` 的效应放行与 finish 消费、同相位 raise 压过 continue。封闭类型 DSL 的五形态文法在规格 §10.2；运行期 helper 尚未进本文件。
