# v13 seam（stage 21，Phase A）

D11 cap×tail-gap 豁免（R6 has-event only）与 D12 `worktree/released` 投影。换体底稿是 stage 20 全量加载后的 `pg_get_functiondef`。closeout / advance / state_hash 零改动。

## 机制

- `v13_cap_answer_anchor` 是 cap 字面量的谓词之家。`v13_cap_human_answered` 委托它。`repair_cap`/`replan_cap` 仍出现在冻结的 `v13_triage_fold_reason`（路由原因，不是第二份谓词）。
- `v13_tail_gap_cap_exempt` 只认匹配类 anchor 之后、`source_effect_id = effect_id` 的自身事件。无自身事件的 ready/claimed 行不盖章。
- 首次成功 `worktree_release` 写开放事件 `worktree/released`。latch 行保持 `prepared`。`v13_worktree_state` 折叠出 `released`。released 本期不被 claim 消费。
- 守卫 `v13_seam_event_guard` 全程无锁（R7）。写者先 `latches FOR UPDATE`，下一条语句再重查事件（R7 两条语句规则）。该结构只由源码断言钉住。
- 并发日程是 R7b 生产序：sessions `FOR UPDATE` → 观察 B 等 A 的 xid → latch `FOR UPDATE` → 直插。本日程不动态验证两条语句规则。

## 实测

- G10 重泵 = **(b)** 返回 `waiting`，零新 effect / 零新 event / session 仍 `waiting`。不是 (c)，不加幂等守卫。
- `v13_resolve_unknown` 在调写者前已持本会话 `sessions FOR UPDATE`（`pg_get_functiondef` 复核）。未补锁。
- 缺失/重复 child id：活体已 RAISE（`children_terminal child` / `duplicate`）。不改求值器。

## Gate

```bash
uv run python v13/seam/test_seam.py
```

退出码 0 = 通过。测试用 Fake，不调真实 provider。
