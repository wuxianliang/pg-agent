# v13 spawn（stage 18，P2）

子会话控制面：专用属主写 `sessions`、`v13_open_session`、`v13_spawn_subsession`、llm `tool_calls` 扇出、席位预算、`v_goal_tree`、`v13_recover_idle`。换体只在本文件 `CREATE OR REPLACE`，不改 stage 1–17 的 SQL 字节。§8.2/§8.3 与 §8.8 冲突处以 §8.8 为准。

## Gate

```bash
uv run python v13/spawn/test_spawn.py
```

退出码 0 = 通过。外部 IO 不进事务。测试不调真实 provider。

## 不做

cancel 扇出、worktree、triage、fold cap、`quota/spent`。这些归 stage 19–20。
