# v15 stage 12 · replay

Gate: `uv run python v15/replay/test_replay.py`（退出码 0 = 通过）。只用测试本地完成器 / ReplayLLM，不开网络。

库名 `agent_v15_replay`。`load_stage(..., "replay")` 加载全部十二个 SQL 文件。这是合运行时库。更早的 `agent_v15_*` 仍是前缀库。`setup_db.py` 会删掉每一个 `agent_v15_` 库，所以 gate 要串行跑。

本 stage 不新增表。`v15_replay.sql` 以 provider 现行体为基线替换 `v15_io_sqlstate` / `v15_govern_known_code`，追加 `V15_REPLAY_DIVERGED`/`P1541` 与 `V15_REPLAY_MISSING`/`P1542`。不把 `V15_VALIDATION_FAILED` 写入 `v15_io_sqlstate`。`supply_llm_response` 仍是 `P1506`。

重放走既有 worker 路径：ReplayLLM 实现 `complete(logical_digest, n, request, llm_config)`，按 `(path, iteration)` 供给已录制正文，`cost_usd` 固定 0。摘要复用 `llm_requests.logical_digest`。
