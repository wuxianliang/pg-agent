# v13 控制面 Oracle R10 微裁：R9 探针 P8a 同域重定义（继承形态 H）（2026-09-27）

- 触发：stage 22 硬前置 P8a 不符——活体 `v13_tools_catalog_frozen`/`v13_named_sql_writer`/`v13_spawn_writer_ok` 三者 `proconfig` **全 NULL**（无固定 search_path，stage 2 以来如此）；R9「无固定 → 停工」触发，A2 按纪律停工。P8b 已实测：规范式 `substring(v_oid::regprocedure::text FROM '\(.*\)$')` 得 `(uuid,jsonb)` 可回解 ✓；identity-args 短式带参数名被拒（`invalid type name`）✗——取规范式，不二式任选。
- 通道：双车道（grokBuild / codex），**①修订版一致**；codex P1 第三条（谓词身份限定）为承重补充，控制器并入。全文：`prompt-exports/oracle-review-2026-09-27-020246-new-chat-2517c8-07f7.md`（gitignored）。编号：R8=并行 Phase B，R9=D14 绑定式，本篇=R10。
- 地位：只替换 R9 P8a 的域要求、投毒 gate 预期、并新增谓词身份限定。不重开：B′ 规范式、裸名形状检查先行、NULL-safe、断言 A、两谓词函数体、tools 行、第四务、D11(R6)/D12(R7/R7b)、零新表零新列、stage 1–21 冻结。

## §0 裁定

| 案 | Verdict |
|---|---|
| ① P8a 改「同域二选一」，活体取 (H) 统一会话继承；换体保持 NULL | **选定（修订后）** |
| ② 换体顺带给 catalog 钉死 search_path | 拒绝（R9 已禁；改变既有全部工具解析域，无逐行兼容证据） |
| ③ 只认钉死形态否则 D14 停工 | 拒绝（同域不变量在 H 下结构性成立；停工不关闭额外洞） |

## §1 P8a 替换条文（同域二选一并保持原形态）

- **(H) 继承形态**：三函数 `proconfig IS NULL` 且均 SECURITY INVOKER、函数体无 `set_config`/动态 SET 改写 search_path——同一次 catalog 调用内，v_oid 解析、体内 to_regprocedure（B′/A）、两谓词内部的 handler 解析共用同一条会话 search_path，**R9 要防的域分叉结构性不存在**。本活体命中 (H)。
- **(F) 固定形态**：catalog 含固定 search_path（无 `$user`）且两谓词未设（继承）或逐字相同。
- base 选定哪一形态，换体后必须保持同一形态与原配置；**禁 H→F/F→H、禁为凑探针新增 SET**。换体保持三函数 proconfig NULL（不写 `SET search_path`、不写 `SET ... FROM CURRENT`、不 `ALTER FUNCTION ... SET`）。
- **（codex 承重补充）谓词身份限定**：换体后的 catalog 函数体内，对两谓词的调用必须按实际 namespace **schema 限定**（绑定 base 记录的真实 OID）——继承形态下未限定调用会被投毒 schema 的**同名谓词**劫持（影子 writer_ok 返 true 即绕过深检）；该限定只固定谓词身份，不改变裸 v_handler 入参与谓词内部解析域，不违反 R9 的工具名字面量禁令（禁的是工具函数名/参数类型字面量与 split_part）。P8c 记录两谓词 OID/namespace 供绑定。

停工：(H)(F) 皆不成立；任一函数被新增/改写 search_path；谓词无法限定绑定到 base OID；函数体验证发现 set_config 改写。

## §2 投毒 gate（形态 H 的正确预期；替换 R9 §3 第③层后半与「真行仍豁免」句）

**继承形态下投毒的正确行为 = fail-closed RAISE，不是真行仍豁免**（「仍豁免」只属形态 F；R9 该句以本裁为准）。

时机与前置（换体后、同库、`SET ROLE v13_route`）：①未投毒路径先绿（真行豁免）；②建 `zshadow.v13_spawn_subsession(uuid,jsonb)`（VOLATILE、INVOKER、无 SET、**由非预期属主角色创建**、非深检克隆）；③`SET search_path = zshadow, public`；④前置断言：会话裸 `to_regprocedure('v13_spawn_subsession(uuid,jsonb)')` = shadow OID 且 `IS DISTINCT FROM` 真 OID（不成立=夹具失败不得记通过）。

通过条件（同时）：①未投毒对照已绿；②前置成立；③**投毒下调用 catalog RAISE，SQLERRM 含逐字节 `is VOLATILE`，无成功返回**——同域劫持下 v_oid 与 B′ 都解析到 shadow（B′ 为真，**不是拒绝层**），防墙 = 真实 writer_ok 深检；④同会话按真实 schema 限定直调 `v13_spawn_writer_ok('v13_spawn_subsession')` 为假（拒绝层记名，预判深检；实测若为形状/A/B′ 层只要 ③成立仍过，注释记名，不改函数凑层）；⑤**影子谓词夹具**：再建 `zshadow.v13_spawn_writer_ok(text)`（恒返 true）与 `zshadow.v13_named_sql_writer(text)`（恒返非 NULL）→ 投毒会话下 catalog **仍** RAISE `is VOLATILE`（证明谓词身份限定生效，未被影子谓词劫持）；⑥`RESET search_path` 后真行重新豁免、catalog/parse 绿（失败仅由投毒域触发）。

测后清理 shadow schema/临时行/恢复路径。停工：不 RAISE；最低夹具下限定直调 writer_ok 仍真；影子谓词存在时被劫持；为凑绿改两谓词/克隆深检属性/shadow 做成 STABLE|IMMUTABLE（那绕开 VOLATILE 分支，属候选②的面，本裁不开）。

## §3 残留与 README

R-1 在 (H) 下收窄：原「catalog/writer_ok 域分叉」结构性关闭；剩余边界 = shadow 同时通过 writer_ok 全部深检 + frozen/digest/ACL 后续校验，需函数属主/等价 DDL 权限/超权——普通调用者不可达（记 F26 处置列）。README 记：继承形态下投毒导致的是**有意的 fail-closed 可用性损失**，正常域仍绿；pg_temp 靠前同理可带偏裸名，防墙同为深检。

## §4 文档落地

F26 处置列末尾追加 R10 句（同域二选一/活体 H/保持 NULL/投毒预期 RAISE/谓词身份限定/R-1 收窄）；计划头部 r9→r10，§4.1 P8 行、§4.2 同域句+谓词限定、§4.4 第③层按本裁替换；R9 文首加 R10 链接注（P8a 与「真行仍豁免」以 R10 为准）；preflight 追加 R10 注。
