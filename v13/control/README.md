# v13 control（stage 17，P1）

单会话控制面：unknown 墙与双射、harness_turn 生产侧、A16 closeout 收据、粘性 cancel、`v13_advance` / `v13_complete` / `v13_enqueue_effect` / `v13_requeue_stale` 换体。换体只在本文件 `CREATE OR REPLACE`，不改 stage 1–16 的 SQL 字节。

## Gate

```bash
uv run python v13/control/test_control.py
```

退出码 0 = 通过。外部 IO 不进事务；路由夹具用 `typesafe` mock GUC，不调真实 provider。

## 不做

spawn / `v13_open_session` / 扇出 / worktree / triage / fold cap / `children_terminal` 求值 / steer 正文 / `quota/spent` / `closeout/inbox_residual`。这些归 stage 18–20。
