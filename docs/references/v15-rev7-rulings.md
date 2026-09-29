# v15 设计文档 rev 7 修订裁定（R-F 系列，收尾轮）

来源：rev 6 复审。主 agent 裁决，binding。应用后标 **设计修订 rev 7**。本轮为最后一批句子级修复。

---

**R-F1（双轨 P0/P1，§9.1/§9.6/§4.5.1）。** send 包络加 dispatcher 专用键 `enter_overlay`（对象或 JSON null）：只含 `recursion_available`（可缺）与 `blackboard_writes`（数组，可缺）——即 `llm_query/enter` 允许的非消息效应（该 phase 不允许 add_inputs，无需携带）。与 `enter_messages` 同样排除在 handler 快照之外。时序：send handler 快照 = 基线 + `enter_overlay` 内存叠加；预留成功后先落 `enter_overlay`（一次），再落 send 自身非消息效应，再写消息。enter 调用本身不落库任何效应。

**R-F2（grok P1，§3.4/§7.2）。** system 重渲染归属统一为「**worker 在调用 `v15_begin_llm` 之前**重渲染 `seed:system`」；`v15_begin_llm` 只校验 id/顺序/映射 kind，不写 system 字节。删除 §3.4/§7.2 中归因于 SQL 的旧句。

**R-F3（grok P1，§4.12/§4.9）。** 删除 worker 侧的 preclassified skip 指令；skip 收敛只在 `v15_finish_exec` 内完成，且**先**按 §4.1 获取锁并校验 fence/owner/状态，**再**把边界之后的所有 `failed`（preclassified）与 `pending` 置 `skipped`，**然后**做候选校验。worker 只调用 finish。

**R-F4（grok P1，§4.8）。** fatal 展开对**锁定闭包内每个** invoke 的 `running` 语句置 `failed`（error = 触发码）、更晚语句 `skipped`——不止直接父。终态 invoke 无 `running` 语句的不变量覆盖全链。

**R-F5（codex P1，§4.1/§9.1）。** `llm_query/exit` 豁免通用 `{outcome}` 信封规则，用 §9.1 表中该行的 `{attempt_id}`（可为 null，见 R-C4）。§4.1 的「事件」段相应注明。

**R-F6（P2 批）。** (a) §0.8/§4.7 的「四个 V15 码」改为「上述五码」（arg 求值任意错误、suspend 捕获五码，两句分开）。(b) §13 `V15_HOOK_ABORT` 单元格补「fatal 为 §9.5 归一后的或」。(c) §15 stage 1 行删「rev 5 的列」类陈旧字样。(d) §4.5.4 与 §9.6 的桩口径统一：`v15_on_phase` 桩函数体覆盖 stage 1–8；`v15_begin_llm` 的桩路径预留只在 io stage（6）起实际存在。

---

自查：§13 仍 38 行 `P1501`–`P1538` 连续；无 `enter_effect` 旧名；`enter_overlay` 与 `enter_messages` 并存且各司其职。
