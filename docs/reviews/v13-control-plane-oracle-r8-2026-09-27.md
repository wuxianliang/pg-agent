# v13 控制面 Oracle R8 终裁：D7/D16 + Phase B 计划审核（2026-09-27）

- 触发：路线图 §4 D7/D16 未裁（gate 住 Phase B stage 23/25）+ Phase B 计划 r1 成文送审。轮名 **R8（Phase B 动词轮）**——裁决号在本会话内两次让号：verdict-R6（D11 has-event）、verdict-R7/R7b（D12 守卫/写者死锁复裁，Phase A 会话 stage 21 施工期间消耗）均已占用；残留台账 R6（catalog 缝）亦被 R5-D14 吸收。本文一律 R8。
- 通道：三车道（grokBuild grok-4.7-build-fast-xhigh / codex gpt-5.6-sol@xhigh / claude-fable-5@xhigh）。全文：`prompt-exports/oracle-review-2026-09-27-013043-*.md`（gitignored）。
- 地位：与 R4–R7b 同级；与路线图 §4 D7/D16 倾向文字冲突处以本文为准。**不重开**：零新表零新列（R4 全集）、stage 1–20 字节冻结、events 唯一干预通道、唯一推进函数、R3 链已冻失败模式（终态 `replay`、C4 RAISE、`v13_interruptible` 闭集）、换体底稿=当日活体 dump、外部 IO 不进事务。
- 用户已拍板（本裁决确认入文、不复议）：D16 幂等 = 身份 `(session_id, up_to_seq, transcript_hash)` 去重；`handoff_policy` 键集 = 极简 `{"schema_version":1,"enabled":true}`；验收天花板 = 🟡（合同已证明/驱动器未交付两格）。

## §0 总表（六题全裁，无退回项）

| 题 | Verdict | 三通道 |
|---|---|---|
| ① D7 actor 通道 | **甲 overload**。2 参 cancel / 6 参 complete（`p_result jsonb DEFAULT NULL` 保持）为唯一正文（**正文自身授权**）；旧签名换体薄 wrapper 委托 `actor=NULL`（纯委托体）。不建 `v13.control_actor` GUC；**乙的会话级泄漏语义（跨请求冒充上一个 actor 写其直接子）被显式不接受**，故乙出局。6 参正文镜像旧 5 参活体 proacl（route+spawn_owner）；既有调用解析不变（6 参不 shadow 5 参；4 实参靠默认参数仍成功） | 三通道一致（grok 亦否自己早先的 GUC 案） |
| ② C15 非终态 | **谓词状态中立**。「可控任意非终态会话」= 动词有效控制面，不进 `v13_control_authorized`；终态 cancel 仍 `replay`；终态直接子的 observe/log/extract 按亲缘放行。否决 D7-alt-status | 一致 |
| ③ 缺会话 needle 例外 | **成立**。operator+空 actor+目标无行 → cancel 保留活体 `v13: unknown session %`、complete 保留 `v13: unknown effect %`（孪生例外，冻结 needle）；agent 路径与非 operator 空 actor 一律 `v13: session not found`（不插值 uuid、无自定义 SQLSTATE；谓词自身只返布尔）。parity F17「一律同一字符串」读作 **agent 授权拒绝面**的不可区分性 | 一致 |
| ④ D16 写口 | **DEFINER 单写者**。`v13_handoff_emit` SECURITY DEFINER `OWNER TO v13_handoff_owner`（属性恰 NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS、无成员；复用残留角色须验属性与 membership，不符 RAISE `v13: handoff baseline`）；守卫 INVOKER 断言 `current_user='v13_handoff_owner'`；extract 保持 INVOKER（D7 身份不被遮蔽）。**emit 体内策略门禁**（append 前查 `v13_policies`，同文案 `v13: handoff policy`/`v13: handoff disabled`）——否则持 EXECUTE 的 route 可在 `enabled=false` 直写；属主增 `SELECT ON v13_policies`（全闭包：schema USAGE/sessions SELECT+UPDATE/events SELECT+INSERT/effects SELECT/policies SELECT/六 helper EXECUTE）。**route→emit 直调 = 受信内部 helper 非 actor 入口**（D7 合同只承诺 extract），行为已定义（同身份→快照索引拒；新身份→合法新收据），台账一行；codex 带案（无 DEFINER/控制带守卫/历史行逐行核对）**拒**；历史行维持「有任何 `control/handoff` 行即 `v13: handoff baseline`，不回填」 | 一致（取向）；grok/fable 补 emit 策略门禁与直调处置、codex 要求 helper 边界明示——全部并入 |
| ⑤ 空前缀值域 | **无 −1**。`up_to_seq` JSON 整数 ≥ 0 且必须等于本会话某行 `type <> 'control/handoff'` 的 seq（存在性谓词，禁缩成数值区间）；空会话 NULL cutoff → `v13: handoff empty` 零写；显式非法（负/缺失/指向 handoff/空会话传 0/超 max）→ `v13: handoff watermark` 零写；不用 `handoff cutoff` 文案；`v13_transcript_hash` 亦拒负 cutoff；`v13_session_log` 的 `p_after_seq=-1` 从头语义独立合法 | 一致 |
| ⑥ hash 字段集 | **最小四元组 + v1**：材料 = `seq <= up_to_seq ∧ type <> 'control/handoff'` 升序 `[seq, type, payload_hash, coalesce(source_effect_id,'')]` + 外层 `['v1', sid, up_to_seq, 数组]`；不含 at/event_id/turn_no/payload 原文/effects/策略/probe；不复用 `v13_state_hash`；**规范字节式 = 计划 §1.2 jsonb_build_array 形（函数与 gate 各写一次；gate 独立重算禁调 helper 自证）**；改字段集须另裁升版本 v1→v2 | **2:1**——grok/fable 取最小集；codex 少数意见（增折 event_id/turn_no，承诺完整事件身份）存档不采纳 |

细节一并确认：operator 带 = `EXISTS(pg_roles.rolsuper) ∨ pg_has_role(current_user,'v13_route','USAGE')`（USAGE 排除 NOINHERIT worker）；agent 只控直接子非自身；读面拒绝零行不 RAISE；cancel/complete 锁前准入+锁后复验（复验为锁后下一条 plpgsql 语句，不并进 FOR UPDATE 同一条 SQL）；complete 准入在锁前（非 human 围栏处，且锁前定位 SELECT 扩列取 `session_id, kind`）；`p_actor` 非空即使 operator 也只走亲缘。

## §1 计划审核（r1）——REVISE（窄）；r2 已全部折入

承重项（r2 处置，逐条落进计划）：
1. §4.3 session_log 游标 gate 与 §1.3 矛盾（「未授权+-2 零行」错；正确=未授权与已授权同得 `v13: session log cursor` 逐字同文案，证明形状检查在谓词前）→ 已改；批判稿 §2.7 同错加勘误注。
2. §2 适配表残留 `≥ −1` 与 ⑤ 冲突 → 改 ≥ 0（拒 `1.0`/指数非 canonical 表示，`::bigint` 前先 numeric 范围判断）。
3. emit 策略门禁 + 属主 `SELECT ON v13_policies` + 安装后全套闭包断言（角色属性/membership/每项权限/prosecdef/proconfig）→ 已入 §1.2/§5.2。
4. observe 返回列含 `parent_session_id` 与「prosrc 无该列」断言互斥 → 改为授权段不读该列、快照段作输出列。
5. hash 规范字节式（gate 禁自证）→ 已入 §1.2。
6. `:320/:321/:326/:348/:355` 是 fanout 快照行号非活体锚 → §8.2 语句级重定位义务（禁按 fanout 行号回贴）。
7. operator 传 actor 不升行政的 gate（route 2 参 cancel 无关 actor→拒；超户 6 参 complete actor+tool effect→拒）→ 已入 §3.4。
8. 新增停工探针：`blocked_unknown` 会话 emit 若 wall RAISE → 停；events payload/payload_hash 可 UPDATE/DELETE → 停（身份去重依赖前缀不可变）→ 已入 §2。
9. complete 锁前定位扩列取 kind（列入允许差集）；wrapper 默认参数逐字保持（漏写=4 实参调用 API 回归），比对 `pg_get_function_arguments`/`pronargdefaults`/proconfig；overload 解析断言 → 已入 §3.2/§3.4。
10. jsonb 不保序 → 删「键序错」守卫负例；「若选 grok 案」分支 → 「R8 未选，不执行」；恰两个部分唯一索引固定 → 已改。
11. 取消/超时 gate 升级为 test-only 阻塞触发器法（仅终态比较不足）→ 已入 §5.3。
12. §2 证伪 10 分路：loader/helper 内长度断言按 X1 放宽；冻结 stage 1–20 测试内的 → 停并请例外 → 已改。
13. 次要：新函数一律 `SET search_path=pg_catalog,public`；`is_terminal` 闭集从活体 `v_goal_tree` 抄；§0 stage 25 回归口径 1→24；`sessions.spawn_kind/turn_no` 列探针 → 已入。

## §2 台账与文档落地

- 台账 **F27 起**（F24=R6；F25=R7/R7b D12 锁协议；F26=R9 D14 断言 B 复裁——均已被 Phase A 会话占用）。Phase B 段：F27 actor 通道与信任边界（overload；DB 只验带+亲缘，来源由服务端绑定）；F28 生产绑定两格（🟡）；F29 读面拒绝=零行与旧动词 needle 并存；F30 前缀窗口非源尾窗（四键约束换体）；F31 收据排除出 transcript 材料（防自激）+ route→emit 直调=受信内部 helper 行为已定义；C15 状态中立（含 ③ 例外句）；C16 R4:23 非生命周期收据澄清（唯一承诺函数=`v13_transcript_hash`；advance 不调；不新增 `v13_latest_handoff`/`v13_handoff_state`/全局 VIEW；路线图 §2.4 交接行维持「收据即事件」）。
- 路线图 §4：D7/D16 标 **R8 已裁**并指向本记录与 Phase B 计划；§3 Phase B 表 stage 23/25 的 D7/D16 条件解除（**Phase A 绿门仍在**——stage 22 catalog 未落）。
- 计划 r2 = 本裁决 + 第一轮审核全部承重项折入后的活规格（`docs/plans/v13-phase-b-workflow-verbs-plan-2026-09-26.md`）。

## §3 三通道分歧存档（不合并、不改判）

| 点 | 分歧 | 处置 |
|---|---|---|
| hash 字段集 | codex：增折 `event_id`/`turn_no`（承诺 session_log 暴露的完整事件身份与回合归属）；grok/fable：最小四元组（seq 已提供稳定顺序身份；event_id 随机会使同逻辑账本迁移后 hash 无谓漂移） | 2:1 取最小集；codex 存档，改须 v2 另裁 |
| 空会话文案 | codex 用 `handoff cutoff` 统一；grok/fable 用 `handoff empty` 专文 | 取 `handoff empty`（与 `handoff watermark` 分职更可诊断） |
| complete 准入点 | grok 原稿插在 unknown-effect 块后（实为锁后）；批判轮/r1：锁前+锁后复验 | 取锁前+复验（grok 终轮认同） |
| 乙通道 | grok 早稿 GUC 完整施工段 | 三通道终轮全否（fail-open 默认 + 跨请求冒充） |
| route→emit 直调 | codex 视为须明示的受信边界；fable 要求台账+gate 定义行为；grok 以 emit 内策略门禁回应 | 三者互补全并入 |

## §4 后续

- 计划 r2 送第二轮审核至 APPROVE；APPROVE 后 stage 23 开工门只剩 **Phase A 绿**（Phase B 计划 §8 复核：stage 21 已落 e925ebe，stage 22 catalog 未落；含语句级重定位义务）。
- 第二轮若出新承重项：同轮修订再审；不回开六题。

## §5 审核轮勘误（事后并入，不回写上文）

- **第二轮（r3 折入）**：§4.3 observe 源码断言与返回列互斥；§5.2 步 6 emit 体补策略门禁（步 3 只授已存在对象、步 5 后精确签名补授）；空会话两文案对进 gate；6 参+不存在 effect 统一文案；spawn_owner 缺 effect 统一文案；非 human 不误套谓词 gate；策略负例两条有序 UPDATE；守卫负例属主身份直插；GUC 退出活合同；并发 COMMIT 日程；complete 无行分支按 operator 带分岔；**台账改 F26 起（F25=R7/R7b 已占，向台账原文核证）**；探针升证伪 11/12；wrapper 纯委托 grep。
- **第三轮（r4 折入）**：**extract 控制流改「回读先于策略」**（同身份重放在 policy 禁用/畸形下仍返原 payload——幂等合同优先；emit 门禁只管新写入）；jsonb 已归一化→不单列 `1.0`/指数负例，改用 `1.5` 小数；policy 缺行不可删（冻结触发器）不进 gate，形状负例只多键+enabled 类型错；两唯一索引正交夹具（约束名断言 + pg_get_indexdef 逐项）；complete 并发半边用 human effect 全 payload；spawn_owner 夹具须超户可写完且双边 stale/replay 不算过；extract/emit prosrc 无 EXCEPTION；hash/回读/索引用同一套 canonical 文本。
- **第四轮（r5 折入）**：`1.5` 夹具补全（seq=2 存在、余四键全合法、hash=cutoff 2 规范式、唯一非法字段 1.5，与缺口 seq 分列）；**jsonb 事实纠错（codex）**：`1.0` 存储后可观察（numeric 保留 scale），是负例不是归一化例外；canonical 规则改为 numeric→trunc→0≤n≤2^63−1→文本等式；补 `9223372036854775808` 溢出负例（不泄 22003）；**零 active policy 恢复进 gate**（UPDATE 置 v1 inactive 即可构造无需 DELETE；旧 identity 可回读/新 identity `handoff policy`/route→emit 同拒）；**台账改 F27 起**（F26=R9 已被 stage 22 占用，向 Phase A 现行版核证）；worker 行矛盾修复（无 EXECUTE→42501，否定证据=pg_has_role USAGE 假）；C15 行补 ③ 例外句；头部/§1.3/§1.4 版本号对齐；schema CREATE 探针（PG15+ ALTER OWNER 前置）。四轮导出：`prompt-exports/oracle-review-2026-09-27-031552-*.md`（第二轮 `...-014802-*.md`、第三轮 `...-030233-*.md`——fable 通道三轮超时未归，其前两轮立场已被另两通道覆盖）。
- **第五轮（r6 折入）**：`1.0` 夹具钉死（seq=1 存在、hash=seq=1 前缀、材料 cutoff 整数 1、唯一非法=存储文本，与 1.5 分列——只有文本等式一步能拒它）；头部状态行/§8.1 A1/A8/§2/§11 基线矛盾修复（「已提交 ≠ 已绿」分写，Phase A 引用刷到现行版）；§4.3 GUC 残留用例删除（改任意会话变量抗噪声例 + 全树源码断言不读 `v13.control_actor`）；DEFINER 闭包精度（to_regprocedure 实测签名授 GRANT 含 digest 双载与 gen_random_uuid 显式授、schema-qual 硬断言、prosecdef/proconfig/owner/search_path 入 gate）；route 对 v13_policies SELECT 探针。五轮导出：`prompt-exports/oracle-review-2026-09-27-034214-*.md`。
- **第六轮（r7 折入）**：`v13.control_actor` 断言分阶段作用域（§3.4/§4.3/§5.3 各管各的已安装面）；§5.2 步 12 直接 ACL（aclexplode）+ digest(text,text) 单载 + pg_catalog.gen_random_uuid() 显式授；schema CREATE 探针后置到步 2 角色创建之后（保留为运行期权限）。六轮导出：`...-045056-*.md`。
- **第七轮（r8 折入；codex/fable 双通道 APPROVE，grok 三条文本残留）**：§4.3 旧「stage 23–25」句删除（断言句改为解析即断言/缺席跳过）；§1.2/步 3 与步 12 同句（digest 只授 text/text、裸名禁、NULL 停工、aclexplode 直接 ACL 为准）；步 5/6/7/10 CREATE 全部 `SET search_path = pg_catalog, public`、步 6 写调用 `public.v13_append_event(..., pg_catalog.gen_random_uuid(), ...)`；fable P2 顺手项（守卫 watermark 文案、适配表指夹具、§1.4 版本、proconfig 拼写统一）。七轮导出：`...-050856-*.md`。
- **第八轮（r9 折入；grok/fable 双通道 APPROVE，codex 一处 P0）**：守卫检查项「`source_effect_id` 非空」缺箭头被读成「要求非空」（会拒一切合法写入）——改为 `NEW.source_effect_id IS NOT NULL → RAISE 'v13: handoff source'`（专属文案；§5.3 负例同文案）；正常 emit/属主直插夹具 `source_effect_id=NULL`。八轮导出：`...-051807-*.md`。
- **§8 复核 + 第十/十一轮（r10/r11 折入；对齐终审）**：Phase A 完成后 §8 复核由子代理执行 = **GO-with-edits**（23/23 脚本 0 退出码、A1–A8 全成立、无 STOP；报告 `docs/reviews/v13-phase-b-phase-a-recheck-2026-09-27.md`，dump 存 /tmp/v13-pb-recheck/）。六条对齐折入 r10：锚换 dump 活体（L16 单列/L17/L18/L19-21/L45/L52/L176-D12 尾部）；cancel 活体序写死（递归在锁前）；:348/:355 debunk；`NULL::jsonb`；A3/A8 证据刷新；§2 表改「历史源锚」。第十一轮修 r10 引入的「② 多锚」（②=L16/L17 之间，③④=L18/L22 之间）→ **grok+codex APPROVE（fable 配额止步但其第十轮条件句已满足）——r11 最终版，stage 23 可开工**（日内刷新纪律保留：开工当日重取 stage 22 dump）。导出 `...-070100-*.md`/`...-071209-*.md`。
- **第九轮（终轮）：三通道 APPROVE**（grok/codex/fable 一致；导出 `...-052738-*.md`）。计划 r9 定稿可开工，硬门 = §8 实跑 stage 1→22 全绿。
- **基线注（第五轮事后并入）**：本文 §2/§4 初稿写「stage 22 catalog 未落」系写作时点快照——现状 = stage 21/22 均已提交（末笔 f59058d）、未实跑绿；以 Phase B 计划 §8 强制刷新为准。
