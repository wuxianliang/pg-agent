# v15 设计文档 rev 8 修订裁定（R-G 系列，最终收口）

来源：rev 7 复审（grok 轨道；codex/kimi 轨道当日额度耗尽）。应用后标 **设计修订 rev 8**。

---

**R-G1（P0，§4.9/§4.6.2/§5.3/§5.5/§0.8/§4.5.3）。** skip 切点定稿：`v15_finish_exec` 内——若存在 `done` 的 `return`/`raise` 语句，`cut = 该语句的 stmt_index`；否则 `cut = resume_stmt`（停在失败行上）。skip 只作用于 `stmt_index > cut` 的 `pending` 与 `failed`（preclassified）行。**不得**用 `resume_stmt` 作为 return/raise 情形的切点。skip 的唯一执行者是 `v15_finish_exec`（§4.9）；修正 §5.3/§5.5 中把 skip 归给 `v15_complete_statement` 的句子（后者只推进 `resume_stmt`，§4.6.2 不变）；§4.5.3 的 skip 引用只指 §4.9；§0.8 指向本切点规则。

**R-G2（P2，§9.1/§6.5/§4.5.1）。** (a) §9.1 快照合成写明：`enter_overlay.recursion_available`（若存在）替换快照同名场；`enter_overlay.blackboard_writes` 的每个元素替换 `blackboard.values[key]`，受影响键的内存代数 = 已提交代 +1（新键为 1）。(b) §6.5 的「SQL 只校验 id 与顺序」补「与映射 kind」（§4.5.1 步骤 1）。(c) §4.5.1「统一用 §4.3 的关闭形状」处重申 `llm_query/exit` 信封是 `{attempt_id}`（可为 null），不走通用 `{outcome}`。

---

自查：§13 仍 38 行 `P1501`–`P1538` 连续。
