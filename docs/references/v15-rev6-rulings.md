# v15 设计文档 rev 6 修订裁定（R-E 系列，终修）

来源：rev 5 复审（oracle 组 `6E014473-9DDE-4584-952E-926B06D0CE13`）。主 agent 裁决，binding。应用后标 **设计修订 rev 6**，修订说明追加一行引用本文。本轮全部为句子级局部修复，不改结构、不加码。

---

**R-E1（双轨 P0，§11.1）。** §11.1 的授权句改为与 §2/§4.1 一致：`v15_assert_manifest()`、`v15_assert_invoke_manifest(uuid)`、`v15_on_phase(...)` 的 `EXECUTE` **只授 `v15_owner`**（无 GRANT OPTION；不授 `v15_worker`）。调用它们的转移函数以 definer 身份（`v15_owner`）执行。

**R-E2（grok P0，§4.5.1 步骤 1/§3.5/§3.4）。** `p_base_messages` 的 `kind` 校验改为映射制：请求元素 `seed:system` → `system`、`seed:inputs` → `input`、其余 id → 存储行的 `kind`；SQL 校验 `message_id` 与**顺序**与 `llm_messages` 一致，不要求逐字节的 kind 相等。种子在库内存储 `kind = seed` 不变。

**R-E3（双轨 P0/P1，§4.5.1 步骤 5–7/§9.1/§9.6/§0.12）。** enter/send 效应时序定稿：
- `llm_query/enter` 的非消息效应（input/recursion/blackboard）在 enter 调用内**不落库**，只进入返回值；
- 载体键更名 `enter_messages`，**只携带 enter 的消息列表**（不含 input/blackboard/recursion）；send 不得重复应用任何非消息效应；
- send handler 的快照 = 基线快照 + enter 非消息效应的**内存叠加**（handler 可见，库不可见）；
- **唯一的落库点**在预留成功之后：先写 enter+send 的非消息效应（一次），再写消息（`max(seq)+1`），再插 attempt；
- 预留 0 行或 send abort：这些效应**从未写入**，fatal 路径干净提交（与 §0.12 一致）；
- `enter_messages` 排除在 handler 快照之外。

**R-E4（grok P1，§9.4）。** `invoke/enter` 的效应允许表加入 `add_messages`（`persistent` 必须为 `true`），与 R-D1 的「open 插入返回消息」配套；`drop_messages` 仍不允许。

**R-E5（grok P1，§4.7/§13/§0.8）。** suspend 捕获集定稿为**五码**：`V15_RECURSION_DISABLED`、`V15_SCOPE_CONFLICT`、`V15_INVOKE_FORM`、`V15_VALUE_INVALID`、`V15_GOVERNANCE_RAISE`。§4.7 删除「不在这四码里」的旧句；§13 在 `V15_VALUE_INVALID` 与 `V15_GOVERNANCE_RAISE` 的分类栏加注「由 `v15_suspend_for_child` 抛出并经 §4.7 捕获 → 语句失败」；§0.8 指向五码集。

**R-E6（grok P1，§4.5.1 步骤 6/§9.6/§0.28）。** 预留写者措辞定稿：govern 体（stage 9 的 `v15_on_phase`）在 phase 路径做唯一预留；stage 1–8 桩路径与重试路径的同一 `UPDATE` 由 `v15_begin_llm` 执行。§4.5.1 步骤 6 指向 §9.6，不重述。

**R-E7（grok P1，§4.5.1 步骤 1/2/§6.5）。** 明确单一事实：**worker** 重渲染 system 正文并放入 `p_base_messages` 的 `seed:system` 元素；SQL 只校验 id/顺序，不写 system 字节（§4.5.1 步骤 2 的「不得改写 base」指不改动传入数组）。

**R-E8（codex P1，§4.5.3/§4.6.2/§4.9/§4.12）。** preclassified 失败的收敛转移定稿：`v15_complete_statement` 的 return/raise 终端分支（以及 `v15_finish_exec` 候选校验之前）把**所有更晚下标**的 `failed`（preclassified）与 `pending` 行统一置 `skipped`。§3.3 的「后续 skipped」措辞与 §4.5.3 对齐（settle 时仅标记 `pending`→初始态，不提前 skip；skip 只发生在执行边界或终端完成）。worker 不做任何内核表 DML。

**R-E9（codex P1，§4.8/§3.3/§4.10/§15）。** fatal 展开时父侧语句终态化：fatal 送达把父的 bind-wait 语句置 `failed`（`error` = 触发 fatal 的码），更晚语句 `skipped`；加不变量「终态 invoke 不得存在 `running` 语句」，§15 stage 8 gate 断言之。§4.10 的修理分支同样满足该不变量。

**R-E10（grok P2 批）。** (a) §6.2/§13/§17 的序列函数拒绝统一为「`(` 前标识符匹配 `nextval`/`setval`/`currval`（含 `pg_catalog.` 限定）」。(b) §0.12 的 fatal 合成措辞指向 §9.5 的「归一后取或」。(c) `docs/references/v15-rev4-rulings.md` 的取代说明已由主 agent 添加（无需再动）。

---

自查：§13 仍 38 行 `P1501`–`P1538` 连续；单标题；无 oracle 元信息；无 `enter_effect` 旧名残留（全文应为 `enter_messages`）。
