# v13 控制面 Oracle R9 微裁：D14 断言 B 绑定式复裁（裸名同域）（2026-09-27）

- 触发：stage 22 RED 基线 P1–P7 全过后，断言 B 触发 R5 预授权停工——活体 `v13_spawn_writer_ok` 是「`split_part(handler,'.',2)` 式剥 schema 取裸名 + 闭集等值」（guard 调用点 spawn:1636 同传裸 handler）；`v_qual`（限定名+身份参数）代入两谓词均 false；无参数限定名为 true 只是剥 schema 后裸名巧合。
- 通道：三车道（grokBuild / codex / claude-fable-5）**一致选定候选①（修订后）**。全文：`prompt-exports/oracle-review-2026-09-27-014907-new-chat-c8d917-ccb8.md`（gitignored）。
- 编号注：**R8 已被并行 Phase B 线占用**（`v13-control-plane-oracle-r8-2026-09-27.md`：D7/D16 + Phase B 计划审核）；本文 D14 复裁记 R9。
- 地位：与 R5–R7b 同级微裁。只替换 D14 断言 B 的可执行式（计划 §4.2）与关联探针/gate/台账。不重开：D14 其余（复用现成一对谓词、不建 `v13_volatile_sql_exception`、不动 tools 行与两谓词函数体、名单外仍拒原子串、schema-qualify/digest/frozen/ACL 其余检查照旧）、第四务、D11(R6)/D12(R7/R7b)、零新表零新列、stage 1–21 字节冻结。R5「禁在 catalog 另写一份校验」收窄为「禁复制 writer_ok 的**深检**」（B′ 是绑定断言，不是第二份深检）。

## §0 裁定

| 案 | Verdict | 一句理由 |
|---|---|---|
| ① 两谓词入参改回 `v_handler`（行内裸名原文），防 shadow 改由断言 B′ 承担 | **选定（三通道一致）** | 与 guard 同参、与活体 (text) 签名同域；B′ 把「文本→OID」二解钉在 catalog 自己的固定 search_path 域内；shadow 在 B′ 或 writer_ok 深检任一处 fail-closed；零函数改动 |
| ② 传无参数限定名 | 拒绝 | 靠 split_part 恰取裸名才为真（解析式实现细节一变即静默失效）；无参签名不锁重载；catalog 合成文本与行内容脱钩 |
| ③ 改 writer_ok 接受限定名 | 拒绝 | R5 已禁 |

## §1 最终绑定式（替换计划 §4.2 断言段）

```
kind='sql' AND enabled AND provolatile='v' 的行（VOLATILE 分支）：
  0. 【裸名形状，先于一切】v_handler 必须是 canonical 裸名：
     strpos(v_handler,'.') = 0 且 v_handler = pg_proc.proname(oid=v_oid) 逐字节相等
     （等价 parse_ident 单段 + quote_ident 回拼；结构相等，非闭集——函数体零名字面量）。
     不满足 → 不调两谓词，直接落原 RAISE（限定名/带签名文本/非 canonical 拼写全部在此挡下）。
  1. v_oid := catalog 既有规则唯一解析（歧义 fail-closed）。
  2. 断言 A（保留，frozen 形态自洽）：to_regprocedure(v_qual) IS NOT DISTINCT FROM v_oid
     且 v13_named_sql_writer(v_handler) IS NOT NULL（闭集判定仅此一次）。
     v_qual 只由 v_oid 现拼（quote_ident(nsp)||'.'||quote_ident(proname)||v_arglist），
     仅用于 A，永不传入谓词。
  3. 断言 B′（替换 B，裸名同域绑定）：to_regprocedure(v_bind) IS NOT DISTINCT FROM v_oid，
     其中 v_bind := v_handler || v_arglist；
     v_arglist := substring(v_oid::regprocedure::text FROM '\(.*\)$')
     （若探针证实 identity-args 拼法对活体行可回解，可用其为短式；两式都非 NULL 且不等 → 停工；
     都对不上 → 停工；禁手写类型串）。
  4. 断言 4：v13_spawn_writer_ok(v_handler) IS TRUE。
  豁免（跳过这条 VOLATILE RAISE）当且仅当 0∧1∧2∧3∧4 同时成立；任一失败落原 RAISE（子串逐字节不变），
  谓词异常不得捕获当可继续。
  **P0（fable）：所有 to_regprocedure 比对一律 NULL-safe（IS [NOT] DISTINCT FROM / 显式 IS NULL）；
  裸 = 在 NULL 时 fail-open，源码断言见红即判。**
  同域：v_oid/A/B′ 都在 v13_tools_catalog_frozen 自己的 proconfig search_path 域内求解（§2 P8 钉住）；
  shadow 若在该域更前，B′ 与 writer_ok 一致看到 shadow，writer_ok 深检（owner/prosecdef/search_path/
  write_targets）不放行 → fail-closed；catalog 解析与 B′ 分叉 → B′≠v_oid → fail-closed。
豁免后：schema-qualify、签名、handler_digest、frozen 一致性、ACL/search_path 照旧全跑。
禁：改 writer_ok 解析；剥限定名后再放行；把 v_qual/合成限定名喂给任一谓词；复制 writer_ok 深检；
   函数体内出现函数名/参数类型字面量或 split_part；换体时省略原有 SET search_path（proconfig 逐字节保持）。
```

## §2 探针 P8（硬前置，base 库非超级用户；任一不符停工）

- **P8a**：`v13_tools_catalog_frozen` 的 proconfig 含固定 `search_path`（无 `$user` 占位）；换体前后逐字节相同（CREATE OR REPLACE 必须写回同一条 SET；禁新加）。无固定 → 停工（禁自行加 SET 凑）。
- **P8b**：B′ 往返对活体 spawn_subsession 行 = 真（两式都试，按 §1 规则）。
- **P8c**：记录 `v13_spawn_writer_ok`/`v13_named_sql_writer` 的 proconfig/prosecdef 与 writer_ok 对入参的实际解析式（已实测=剥 schema 裸名等值）；两谓词未设 search_path（继承 catalog 域）或与 catalog 相同 → 同域成立；不同 → 停工。writer_ok 实际检查的 OID 表达式照测一次，结果须 = v_oid。
- **P8d**：记录 public schema CREATE 权限状态（决定 shadow 夹具形态，不 STOP）。

## §3 gate 增补（替换计划 §4.4 shadow 行）

三层 shadow 矩阵（测后清理 shadow schema 与临时行；不改 stage 18 tools 行）：
1. **直调层**：`SET search_path=zshadow,public` 的连接直调 `v13_spawn_writer_ok('v13_spawn_subsession')` → 假，记录拒绝层。
2. **绑定层**（确定性直测）：建 `zshadow.v13_spawn_subsession(uuid,jsonb)`（VOLATILE、不过 H7 深检）后，在 catalog proconfig 域下：`to_regprocedure('zshadow.v13_spawn_subsession('||v_arglist||')') IS DISTINCT FROM v_oid` → 真（B′ 对 shadow 必假）；对行内 v_bind 同式 → 假（B′ 对真行必真）。
3. **端到端层**：临时插 handler=`zshadow.v13_spawn_subsession` 的 enabled sql 行 → catalog 仍 RAISE `is VOLATILE`（**限定名进不了谓词=形状检查挡下；记名实测命中层**）；会话投毒 search_path 后以 v13_route 调 catalog：真行仍豁免、返回无 zshadow（钉死域不被会话带走）；同会话裸 to_regprocedure 能见 shadow（证明投毒生效）。
4. **源码断言**：两谓词实参=v_handler；v_qual 只出现在断言 A；豁免分支在形状检查之后；to_regprocedure 比对全部 NULL-safe（裸 = 判红）；无函数名字面量/split_part/深检副本；两谓词各恰一次。
5. 名单外 VOLATILE sql 行仍同子串失败（原条款保留）。

## §4 台账

- **F22 照关**（命题=「D14 交付后具名写者对 parse 可见」不受绑定式影响），关闭行加指针：「绑定式按 R9/F26：裸名同域 B′，非 v_qual 代入」。
- 新增 **F26**（≠ parity F26）：事实=活体谓词裸名解析、R5 v_qual 代入不可满足触发停工（已按纪律停）；处置=①落地（B′ NULL-safe、形状检查先行、A 保留为 frozen 自洽、零函数改动）；残留 R-1 接受=catalog 域与 writer_ok 域分叉且后者解析到过深检的另一 OID——须超权造同名同参双份且过 owner/prosecdef/search_path/write_targets，非超权不可达；P8 任一不符停工。

## §5 停工追加

P8a–P8c 任一不符；§4.2 任一断言无法落成 NULL-safe 可执行式；shadow 反例在 B′ 上意外为真；限定名临时行被豁免。

## §6 文档落地

计划头部 r7b→r9；§4.1 增 P8 行；§4.2 断言段按 §1 替换；§4.4 shadow 行按 §3 替换；§4.6/台账按 §4；R5 记录顶部追加 R9 链接注（D14 条款以 R9 为准，原文历史保留）；preflight 末尾追加 R9 注。
