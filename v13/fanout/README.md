# v13 fanout（stage 19，P3）

cancel 同事务扇出、interruptible 第四务、worktree latch。换体只在 `v13_fanout.sql` 里 `CREATE OR REPLACE`。stage 1–18 文件字节不动。

## Gate

```bash
uv run python v13/fanout/test_fanout.py
```

退出码 0 = 通过。事务内不碰文件系统。测试用 Fake，不调真实 provider。

## 不做

triage、fold cap、`quota/spent`、`pg_terminate_backend`。这些不是本期。
