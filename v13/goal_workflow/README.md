# v13 goal_workflow

单 goal、测试超级用户、Fake 夹具、场景自有 advance 上界 4（常数只活在 `v13/goal_workflow/test_goal_workflow.py`）、无真实 provider、唯一推进者是一个 `LoopDriver`：宏观门放行后，`workflow_template` version 1 / `first_real_chain` 展开成一条 advancement todo、一个子会话、一次 `read_file_py`、根上归档为 done，根与子都没有 human effect。已有 human pending 时场景停在非终态、不 skip、不 complete、不 cancel。这不是人可以离开生产终端。

## 函数

`public.v13_macro_suggestion(p_sid uuid, p_suggestion jsonb) → jsonb`

`LANGUAGE plpgsql`，`STABLE`，安装者属主，`SET search_path = pg_catalog, public`。`REVOKE EXECUTE` FROM PUBLIC，只 `GRANT EXECUTE` 给 `v13_route`。函数不是 `tools` 行。

`suggested_should_run` 在形状检查之后丢弃。它不进入 `admitted`，也不出现在返回对象里。`admitted` 是 `v13_should_run(p_sid) AND v13_quota_eligible(p_sid)`。

缺会话返回 missing，不调用 `v13_should_run`，不调用 `v13_quota_eligible`，也不调用 `v13_should_run_gate`。形状失败和缺会话都不 RAISE。

## 三种 JSON

形状失败和 missing 都是三键，没有 `schema_version`。评估对象是六键。`gate` 在门文本为 SQL NULL 时是 JSON null，键仍在。三个对象都由 `jsonb_build_object` 构成。

形状：

```json
{"ok": false, "reason": "shape", "admitted": false}
```

missing：

```json
{"ok": false, "reason": "missing", "admitted": false}
```

评估：

```json
{"schema_version": 1, "ok": true, "admitted": true, "should_run": true, "quota_eligible": true, "gate": null}
```

## 推进

唯一推进者是一个 `LoopDriver`。四次 advance 的词是 `waiting`、`progressed`、`waiting`、`waiting`。

第 2 次是 `serve` 内部的 spawn 臂，词是 `progressed`。

子读是事务外的 FakeTool，加上同一事务的 claim UPDATE 和五参 `v13_complete`。

第 4 次是 `_settlement_advance`，然后 `waiting`。

human pending 是 hold，不是 solved。

## 非目标

`actl_driver_demoted` 延期。不调用 `v13_agentctl_observe`、`v13_agentctl_steer`、`v13_agentctl_answer`、`v13_agentctl_cancel`。stage 43–45 不交付。

`setup_db.py` 把一次性库装到 `agentctl_verbs`。本目录 SQL 不在 setup 里应用。

## Gate

```bash
UV_FROZEN=1 uv run python v13/goal_workflow/test_goal_workflow.py
UV_FROZEN=1 uv run python v13/plan_arm/test_plan_arm.py
```

## 实跑

2026-10-09 `UV_FROZEN=1 uv run python v13/goal_workflow/test_goal_workflow.py` 退出码 0（460 checks）。`UV_FROZEN=1 uv run python v13/plan_arm/test_plan_arm.py` 退出码 0（104 checks）。一次性库在打印 `[ok]` 之前已删除。退出码 0 只表示单 goal、Fake、上界 4 的第一份绿场景，以及一个零写的宏观建议函数，已经在一个 `LoopDriver` 上验证。
