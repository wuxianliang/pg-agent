# v17 G6 · repair —— 暂停、修复、resume，原调用完成

Gate: `uv run python v17/repair/test_repair.py`（退出码 0 = 通过）

## 一句话

**jiti 的招牌能力进了 effect 总线：被求值的 form 发出 condition，内核在
原调用仍在栈上时报告 condition 与 restart 菜单，调用方给的 repair form
在那个被挂起的 dynamic extent 里执行，再 invoke 一个 restart 让原计算
穿回去。** 对 world daemon，repair 配方是 job 契约的一部分：

```json
{"world": "...", "source": "...",
 "repair": "(setf (gethash \"r\" *state*) \"repaired\")",
 "resume_restart": "use-default"}
```

## restart 的指定方式：名字或序号，不是菜单 id

菜单 id 形如 `<pause计数>/<index>`——**每次 repair 让 condition-loop
重入一次，pause 计数就变，菜单重建，id 随之失效**。第一版实现按上一帧
菜单解析出 id 再提交，等动作被消费时菜单已经换了，resume 静默变
no-op，job 一路把预算烧穿（`EXHAUSTED`）。所以：

- 调用方给 restart 的**名字**（大小写不敏感）或从 0 起的**序号**；
- daemon 每次提交前**重读当前菜单**再解析（repair 之后必须重读）。

这也是 gate 里 `resume_restart: "use-default"` 的由来。

## 崩溃边界（如实断言，不修）

暂停中的 restart 是**活的 dynamic extent**，不是持久状态：
- 无 recipe 的暂停 → daemon 立即按 failed 结算，condition 与 pause
  落 journal（菜单只到活视图，journal 不背菜单）；
- repair 执行中进程被杀 → job 停在 `claimed`、world 不前进、被中断的
  repair 不留痕迹；此后只有显式决议（`v12_complete_job('unknown')` →
  `v12_resolve_unknown`）能推动它，**没有盲目重放**。

jiti 同样如此（只有 checkpoint 是耐久的），G6 把这个边界钉成断言。

## journal 的一个真实缺口（已补）

publish 事务提交**之后**内核才 emit `:accepted` / `:operation-finish`，
按构造进不了那个事务。daemon 因此补一段**独立事务**把剩余事件写进去。
安全性方向是对的：这些行只可能在 publish 成功之后存在，崩溃最多让
journal 少一个结果（绝不会出现幻觉结果），且下一轮扫描也看不到 queued
job。

## 五场景

1. **pause → repair → resume**：job succeeded，原计算穿 restart 返回 84；
2. **journal 留痕**：condition / restart / evaluated / invariants 全在，
   repair 造成的状态变化耐久；
3. **repair 自身失败**：job failed（reason 指名），没有新 revision；
4. **repair 执行中被杀**：job 停在 claimed、只有 baseline revision、
   被中断的 repair 无痕迹；随后走 unknown 墙（显式 unknown → resolve）；
5. **无 recipe 的暂停**：job failed，condition 与 pause 落 journal。

## 复现「damaged menu」 bug 的最小形式

```lisp
(let ((form '(greet ((:WHO . "team")))))   ; params alist 没 quote
  (eval form))                                ; => illegal function call
```

alist 里的 `(:WHO . "team")` 被当函数调用形式求值，关键字当了操作符。
正确形式 `(greet '((:WHO . "team")))`，见 G4/G5 README。
