# v15 stage 11 · return_hooks

Gate: `uv run python v15/return_hooks/test_return_hooks.py`（退出码 0 = 通过）。只用 FakeLLM，不开网络。

库名 `agent_v15_return_hooks`。`load_stage(..., "return_hooks")` 加载全部十一个 SQL 文件。这是合运行时库。更早的 `agent_v15_*` 仍是前缀库。

本 stage 不新增表。本文件只放 `v15_return_validation_effect`：读 snapshot 里的 `max_failures` 与计数，生成 return→continue 或 return→raise，不写表。`v15_return_spec_valid` / `v15_return_spec_fault` / `v15_return_spec_render` 与内建 `return_type` 的 CREATE、权限、`hook_defs` 插入仍只在 govern 文件。

`return_type` 用封闭 jsonb 类型规格（五形态）。`validate_return` 与 `validate_return_<suffix>` 不预插 builtin 行；登记方创建 `v15_hook_<key>`，并授予 schema `v15` 的 USAGE 与 effect builder 的 EXECUTE。handler 用 effect builder 传 valid/message，不要用直接 `RAISE` 表示值不合法。
