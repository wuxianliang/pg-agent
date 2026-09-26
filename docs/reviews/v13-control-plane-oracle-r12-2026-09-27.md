# v13 控制面 Oracle R12 微裁：夹具 3 臂 D 改真行 fail-closed；限定证明移交源码硬断言 + 臂 E（2026-09-27）

- 触发：R11 臂 D 落地实测（未改谓词、未 commit）——S 已锁死、夹具 1/2 过；臂 D 失败：投毒下**按 namespace 限定直调真实 `v13_spawn_writer_ok` 也为 false**——活体 writer_ok 体内**裸调** `v13_named_sql_writer`（未限定），继承投毒会话路径命中恒 NULL 影子 → 真实谓词自身返 false → 真行落 `is VOLATILE`。R11 臂 D 预期（真行仍豁免）隐含要求冻结谓词体投毒免疫，不可达；且此形态下「限定调用」与「被劫持」观察相同，臂 D 结构上不区分两者。
- 通道：grokBuild + codex 双车道**一致选 A 修订版**；B（改冻结谓词体）C（删臂 D）拒绝。全文：`prompt-exports/oracle-review-2026-09-27-023707-new-chat-2517c8-a85c.md`（gitignored）。编号：…R10=P8a 同域，R11=解析层矩阵，R12=本篇。
- 地位：只改 R11 夹具 3 臂 D/臂 E 条文与证明分工。不重开：P8a(H)、P8b 规范式、形状检查、NULL-safe、断言 A、**两谓词函数体（冻结）**、tools 行、P8a′ 限定义务本身、第四务、D11/D12、零新表、stage 1–21 冻结。

## §0 裁定

| 案 | Verdict |
|---|---|
| A 臂 D 改真行 `is VOLATILE`（fail-closed 回归）；P8a′ 动态证明移交源码硬断言 + 臂 E | **选定（修订后）** |
| B 限定 writer_ok 体内 named 调用 | 拒绝（stage 18 冻结；改的是谓词对全部调用方的投毒行为） |
| C 删臂 D | 拒绝（仍是「否决型影子下真行不得豁免成功」的回归锁） |

## §1 臂 D 替换条文

影子：`v13_spawn_writer_ok(text)` 恒 false；`v13_named_sql_writer(text)` 恒 NULL；INVOKER、无 SET、非真属主；path=zshadow,public；真行裸名=真 proname；库内工具恰一份。

前置（同一会话、SET ROLE v13_route 后、catalog 前；缺一即夹具失败）：①裸工具 `to_regprocedure` = 真 OID（无歧义墙）；②两谓词裸名 = 影子 OID ≠ P8c 真 OID；③直调两影子得 false/NULL；④限定直调真实 `named('v13_spawn_subsession')` 非 NULL；⑤**限定直调真实 `writer_ok('v13_spawn_subsession')` = false**（记名机制=其体内裸调命中影子 NULL；若实测为 true → 前提失效**停工复裁**，不许记 RAISE 也不许记豁免）。

通过（同时）：catalog 抛错无成功返回；SQLERRM 含逐字节 `is VOLATILE` **且点名 `spawn_subsession`**（活体格式 `v13: sql tool spawn_subsession handler v13_spawn_subsession is VOLATILE`，换体不得改文案）；SQLERRM **不含** S。实测拒绝层早于 writer_ok 时只要三条文字成立仍过，注释记名，不改函数凑层。

本臂**不证明 P8a′**（劫持否决型影子观察相同）；只锁：此投毒下真行保持 fail-closed，不得出现对照 G 式成功豁免。测后删影子恢复 path、G 复绿，再建臂 E。

## §2 臂 E 加严

影子体：`writer_ok(text)` 恒 true；`named_sql_writer(text)` 对**任意入参**返回同一非 NULL 常量 C（C=未投毒路径以 route 限定直调真实 named 对真行裸名的返回值，固化进影子；**禁按入参转调真实 named**——名单外入参会得 NULL 使劫持路径也拒绝、臂 E 假绿）。名单外行同 R11（enabled sql、裸名=全库唯一 proname、VOLATILE、投毒 path 上形状与 B′ 为真；proname ≠ v13_spawn_subsession）。

前置（缺一即失败）：①无第二份工具函数；②两谓词裸名=影子 OID；③**限定直调真实 `writer_ok('v13_spawn_subsession')` IS TRUE**（不成立=与真行假拒绝纠缠，**停工复裁**；禁退回「任意 is VOLATILE 算过」）；④限定直调真实 named 对真行非 NULL、对名单外裸名 IS NULL；⑤裸调（走影子）两谓词对名单外裸名为 true/非 NULL；⑥限定直调真实 `writer_ok(名单外裸名)` 布尔值**记入注释**（false=谓词层也拒；true=记谓词层残留见 §4，不关账成「只有假拒绝」）。

通过（同时）：catalog 抛错无成功返回、结果不含该名单外行；SQLERRM 含逐字节 `is VOLATILE` 且**点名这条名单外工具**（tool 名与 handler）；SQLERRM **不点名 spawn_subsession、不含 S**（点名真行或第三工具=夹具失败）。

证明口径：臂 E 只证「放行型影子未形成端到端假豁免」；**不单独证明两调用点各自限定**（codex 收窄）——那由 §3 结构 gate 承担。

## §3 P8a′ 的承重半边：源码/OID 硬断言（并入源码断言组）

①限定签名回解到 P8c 记录的真实 OID（两谓词各查）；②`pg_get_functiondef(catalog)` 两调用点分别恰一次使用该真实 namespace，无未限定/错 namespace 调用；③实参均为裸 v_handler；④臂 D/E 都 RAISE 不得替代本组失败（任一失败停工）。

## §4 残留、README、F26

- 谓词层残留（仅当前置⑥为 true 时记）：真实 writer_ok 对名单外裸名可被影子 named 的非 NULL 常量放行——stage 18 冻结体既有性质，D14 不修不换体；catalog 层断言 A 走真实 named 时名单外行仍 NULL 落 RAISE。
- README 两句：活体 writer_ok 体内裸调 named，会话投毒下限定直调真实 writer_ok 仍 false（否决型影子→真行 `is VOLATILE`，接受的 fail-closed 可用性损失非假豁免）；catalog 两处**顶层**谓词调用按 P8c 限定到真实 OID（限定不递归固定谓词体内解析）；臂 D 只锁该行为，逐调用点身份由 §3 结构 gate 证明，放行方向由臂 E 保证。
- F26 处置列追加 R12 句（臂 D 改真行 RAISE 点名 spawn_subsession / writer_ok 体内裸调事实 / P8a′ 证明分工 / 前置不成立停工禁降级）。

## §5 停工红线（增补）

臂 D 前置⑤不成立仍记通过；臂 D SQLERRM 非点名 spawn_subsession 的 `is VOLATILE`（含成功返回/含 S）；把臂 D 写成「限定已证明」；臂 E 前置③不成立仍把任意 `is VOLATILE` 记通过；臂 E 点名错行仍记通过；臂 E 名单外行被豁免；影子 named 按入参转调真实 named；§3 结构 gate 失败；为臂 D 旧预期改谓词/加 SET/加体内限定。R11 其余红线维持。

## §6 文档落地

计划 r11→r12（§4.4 臂 D/E 分句按 §1/§2 替换、§4.2 证明指针改「源码断言+臂 E；臂 D 是假拒绝回归」、§5.6 增补）；R11 文首加 R12 注（臂 D 原文保留）；preflight 追加 §15。
