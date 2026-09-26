# v13 控制面 Oracle R11 微裁：投毒矩阵按活体解析层重排（2026-09-27）

- 触发：R10 §2 落地实测（probe 库回滚验证，未写换体）——投毒前置成立（裸 `to_regprocedure` 命中 shadow），但 catalog 先抛活体既有解析层 `ambiguous across schemas (2)`：**活体唯一解析按 proname 计全库 `pg_proc`，不看 search_path，在 VOLATILE 分支之前退出**。同名 shadow 工具只要存在（投毒与否相同）即 fail-closed；R10「v_oid 与 B′ 同落 shadow → 限定 writer_ok 打出 `is VOLATILE`」在「只改 VOLATILE 分支、保持既有解析」下不可达。
- 通道：grokBuild 完整裁定 + codex 部分完成（不活跃看门狗截断）且其 P1 与 grokBuild 收紧一致（夹具 3 须反值影子谓词；v_oid 非会话域）。**案 A 修订版选定**；B（解析改 search_path 域内）/C（VOLATILE 分支单独 path-scoped）拒绝——都是改既有解析语义。全文：`prompt-exports/oracle-review-2026-09-27-021548-new-chat-2517c8-e13e.md`（gitignored）。编号：R8=并行 Phase B，R9=D14 绑定式，R10=P8a 同域，R11=本篇。
- 地位：只替换 R10 §2（投毒矩阵）与计划 §4.2 同域句/§4.4 投毒层/§5.6 停工红线。不重开：P8a 形态选择（本活体 (H) 三函数 proconfig NULL 保持）、P8b 规范式、裸名形状检查、NULL-safe、断言 A、谓词函数体、tools 行、**谓词身份限定义务**、第四务、D11/D12 各裁、零新表、stage 1–21 冻结。

## §0 裁定

| 案 | Verdict |
|---|---|
| A 接受全库 proname 计数为更早防墙，矩阵按可达性重排（修订版） | **选定** |
| B 解析改 search_path 域内 | 拒绝（改 stage 2 以来全部 sql 工具解析语义，拆掉既有歧义墙；无逐行清单与全量回归） |
| C VOLATILE 分支单独 path-scoped | 拒绝（同一函数两套解析；豁免路径比普通路径更宽） |

## §1 修正矩阵（替换 R10 §2 与计划 §4.4 投毒层）

换体后的 catalog 上测；角色 `v13_route`；真行裸名=真函数 proname；shadow 由非属主创建（INVOKER、无 SET、不克隆深检、不 DROP 真函数）；测后删 shadow schema/临时行、恢复 path、对照 G 复绿。**记名子串 S = 换体前 base 库同一夹具的 SQLERRM 逐字节子串**（恰一具同名 shadow 时含 `ambiguous across schemas (2)`，以 base 实测锁死）；换体后必须仍含同一 S；禁改写成 `is VOLATILE`、禁捕获后进豁免分支。步骤 0–4（形状/A/B′/谓词）只在既有解析已取得唯一 `v_oid` 且 `provolatile='v'` 后执行；解析期 ambiguity 退出逐字节留在活体底稿。

- **对照 G**（无任何 shadow/影子谓词、未投毒）：catalog 成功返回、真行豁免。一切夹具之前采样；G 失败不得用后夹具充绿。
- **夹具 1（shadow 工具存在，不投毒）**：`zshadow.v13_spawn_subsession(uuid,jsonb)` VOLATILE，route 对 zshadow 有 USAGE → catalog RAISE 含 **S**（拒绝层=既有解析，非形状/B′/writer_ok）；删除该函数后 G 恢复。
- **夹具 2（同 shadow + 投毒）**：path=zshadow 接对照 G 之前；前置（catalog 调用前同会话）：裸 `to_regprocedure('v13_spawn_subsession(uuid,jsonb)')` = shadow OID 且 `IS DISTINCT FROM` 真 OID（不成立=夹具失败不得记通过）→ 结果同夹具 1（RAISE 含 S）；B′/writer_ok 本次不可达，注释记「解析层先退出」。
- **夹具 3（无 shadow 工具，仅影子谓词 + 投毒；双臂分建，返回值相反不并存）**：库内工具函数仍恰一份；两影子与真谓词同签名 (text)、INVOKER、无 SET、非真属主。前置（缺一即失败）：裸 `to_regprocedure` 两谓词名均解析到影子 OID ≠ P8c 真 OID，且工具裸名仍=真 OID。
  - **臂 D（否决型）**：影子 `v13_spawn_writer_ok` 恒 false、影子 `v13_named_sql_writer` 恒 NULL；直调影子确认返回值；schema 限定直调真 OID 对真行裸名得 writer_ok 真、named 非 NULL → **catalog 成功返回、真行仍按对照 G 豁免**（行 handler/digest/write targets 与 G 一致）——证明调用打到真谓词（若走裸名 AND 断、真行不豁免）。
  - **臂 E（放行型）**：影子恒 true/恒非 NULL；另插一条**名单外** enabled sql 行（handler 裸名=其 proname 且全库唯一、VOLATILE、落在投毒 path 上，使形状与 B′ 在该行为真）→ **catalog RAISE 含逐字节 `is VOLATILE`**（真谓词不放行；影子若被劫持则该行会被放行）——R10「恒真影子仍拒」在活体解析下唯一走得到谓词的位置。
  - 恒真影子加在真行上看到豁免两臂都能出现，**不单独当证明**。
- **夹具 4（限定名临时行，形状检查）**：临时函数 proname **不得与任何 enabled 裸名 handler 相同**（不用 v13_spawn_subsession）；handler=带 schema 限定名、VOLATILE、全库该 proname 计数 1 → catalog RAISE 含 `is VOLATILE`，源码层死在形状检查（strpos 见 `.`）未进谓词。撞名形态（handler=zshadow.v13_spawn_subsession 与真行同 proname）整次调用死在 S 上，不得记成夹具 4 通过。
- **B′ 直测（不经 catalog）**：对照 G path 上真行 v_bind 回解 = 真 OID；shadow 工具存在时 `to_regprocedure('zshadow.…(uuid,jsonb)')` `IS DISTINCT FROM` 真 OID。夹具 2 裸名解析到 shadow 是 to_regprocedure 既有行为，非「B′ 意外为真」停工。
- **不构造**：「投毒下经深检打出 `is VOLATILE`」——解析层先拦截；`is VOLATILE` 负例=夹具 4 + 臂 E + 原名单外行。

## §2 停工红线（替换 R10 停工）

夹具 1/2 的 SQLERRM 不含 base 锁死的 S（含成功返回/改抛 is VOLATILE/其它文案）；base 与换体后 S 不一致；夹具 2/3 前置不成立仍记通过；删 shadow 后 G 不恢复；臂 D 真行未按 G 豁免或仅用恒真影子记通过；臂 E 名单外行被豁免（劫持成功）；夹具 4 限定名行被豁免或撞名 ambiguity 被记成形状通过；**换体改写既有解析**（v_oid 改走 to_regprocedure/search_path、VOLATILE 分支另写解析、捕获 ambiguity 继续、新加 SET）；为过矩阵改谓词/克隆深检/shadow 做 STABLE|IMMUTABLE/DROP 真函数。夹具 4 在 base 上若进不了 VOLATILE 分支（限定名被既有解析以别文案拒）：记 base SQLERRM 复裁；换体后不得宽于 base。

## §3 (H) 收窄与残留

(H) = 三函数 proconfig NULL、INVOKER、无 set_config → **B′ 的 to_regprocedure 与两谓词内部**共用会话 search_path；**v_oid 不在此域**（全库 proname 计数，歧义即退出）。R-1 再收窄：同名第二函数到不了深检（解析层 fail-closed，可用性损失非绕过）；剩余防面=无第二份工具函数时的影子谓词，防墙=P8c 记录的 namespace/OID schema 限定调用。pg_temp 同名函数同样使计数+1 走 S。README 按此两句记；R10「v_oid 与 B′ 同落 shadow」只描述反事实形态。

## §4 文档落地

计划 r10→r11：§4.2 同域句改 §3 收窄句并写明步骤 0–4 进入条件；§4.4 投毒层整段换 §1（对照 G + 夹具 1–4）；§5.6 红线换 §2。R10 文首与 §2 加 R11 注（原文保留）。preflight 追加 §14。F26 处置列追加 R11 句（解析层先拦/S 锁死/夹具 3 双臂/停工改解析层放过 shadow 即停）。
