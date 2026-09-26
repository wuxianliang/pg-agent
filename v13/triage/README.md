# v13 triage（stage 20，P4）

A20 阶梯、goal/override、同会话 explore、fold cap。换体只在 `v13_triage.sql` 里 `CREATE OR REPLACE`。stage 1–19 文件字节不动。

## Gate

```bash
uv run python v13/triage/test_triage.py
```

退出码 0 = 通过。测试用 Fake，不调真实 provider。

## 不做

`closeout/inbox_residual`、`quota/spent`、`quota/voided`、G6 新条文、`material_cap` 生产路径。超限 material 继续 RAISE。`thresholds.action` 不 ALTER。

## 授权面（P5/F19）

`v13_triage_project(uuid)` 与 `v13_json_keys(jsonb)` 追授 resolve/recall（定义分别在本地与 stage 17，此处只加 GRANT）；`v13_triage_owner` 需要 `v13_assert_unknown_wall` EXECUTE 与 `effects` SELECT（emit 提交期双射触发器路径）。勿删（gate：test_triage.py F19 组）。
