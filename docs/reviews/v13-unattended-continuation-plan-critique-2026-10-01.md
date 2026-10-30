# v13 unattended_continuation 授权增补计划 复审意见（2026-10-01）

对象：`docs/plans/v13-unattended-continuation-authorization-plan-2026-10-01.md`（下称「计划」）。
基线：`prompt-exports/oracle-plan-2026-10-01-195602-v13-unattended-conti-7a04.md` 中「## Generated Plan」之后的三路 Oracle 计划（openCode/stepfun/cursor 三 lane；其前的组合提示与选档 dump 只作上下文，不作基线）。
核对代码：HEAD `78e77c7` 实树（`git rev-parse HEAD` 复核一致；工作区无已跟踪改动）。

三项显式父裁决的丢弃（Oracle 2 的 gate `main()` 翻转 exit_0、8 轮预算、blob 钉死 load.py）按指令视为正确，不在缺陷之列。本文只列其余发现，按严重度排序。每条给出代码证据。

> **修订状态（2026-10-01，Oracle 复审轮 `852EC7B3-BE51-4990-A61A-71558C800E5C` 后）**：本文件针对的是修订前候选稿。H1（未付读法）、M1（取证白名单）、M2（负例行状态）、M3（preset 恢复）已按现行计划吸收（分别见计划 §4.2 停止规则、§4.4 扫描、§6.4 行状态、§4.1 库生命周期两支）；L1–L4 同步修复。该复审轮新增两项并已修：load 追加式收紧为对应性追加（§2.3）、preset 支与 DROP 证据分流（§4.1）。下文发现正文保留作历史记录，以现行计划文本与该复审轮为准。
>
> **修订状态补（2026-10-02，第二轮 Oracle 复审 group `8523289F-41E2-45C6-9FE7-E27239EA853E`，codex 与 grok 两路均附条件接受）**：P1 四组全部修入计划。①§2.3 重写——`extra` 分流（`fresh` 闭集恰为 `accept_unattended.py` + `known` 逐文件字节钉到 `78e77c7`，例外仅 test AST 追加式与 README 纯追加）；②load 对应性追加收紧为「规范形态穷尽」（全部 `+` 行逐行匹配追加项规范序列化，堵函数体插入/文末新函数），`r1_load_append_ok` 为唯一 load 子谓词、`r0_source_scope` 与 `test_stage_bytes` 共用；③§4.1 preset 收紧（专用命名空间 `ll_unattended_preset_` 前缀）+ 取证纪律可执行化（§6.2 `env -u` 命令、stdout `[dropped]`/`[kept]` 标记、§4.4 新断言 `unattended_matrix_row_requires_dropped`；不实现成入口拒绝以免 preset 支不可达）；④§4.4 可执行面补夹具 UPDATE 形状（`result||jsonb`、`status='unknown'`、`blocked_unknown`），扫描改 AST 调用位置（新函数 `unattended_accept_script_scan`，`test_static` 不动保字节钉）。P2 亦修：§4.3 三墙补 `settle_once=1`/advance 按实际计数、`accept_database_dropped` 按分支、`getattr` 取 `llm`；§1 行名歧义；合成反例闭集补至 20 条。**驳回一条**：codex P2「`test_stage_bytes` 实际用 `HEAD` 而非 `R1`」经活体复核不成立——`v13/goal_supervisor/test_goal_supervisor.py:233-235` 即 `["git", "diff", R1, "--", "v13/load.py"]`，计划 §2.2 第 3 条描述正确，不改。
>
> **修订状态补二（2026-10-02，第三轮 Oracle 验证 group `8523289F` 同组续轮）**：两路确认上轮四组 P1 与 P2 均已落位、驳回正确；新抓 4 组 P1（均系第二轮修订自身引入）并已修：①`fresh` 从活体等式改为**子集分期合同**（`fresh ⊆ {accept_unattended.py}`，提交②空集合法/提交③一元集合法，合成正例补两形状）；②load 规范形态对齐活体 diff（`+` 行去前缀后为 `V13_ROOT / "<stage>" / "<file>.sql",` 或 `"<stage>": <整数>,`，丢 `+++`/`---`/`@@` 文件头行——原引号路径写法与活体 `git diff fb295ac` 实形不符，已亲验修正）；③§4.4 可执行面补 `fixture_unpaid` claimed 分支的三字段 infinity UPDATE（`:156-159`，与 settle() 五字段领取形单列）；④矩阵断言时序重排（§7/§10 改为授权实跑 → 矩阵/README 更新 → gate 复跑后验）+ 防自反（按 `[dropped] ll_unattended_accept_` / `[kept] ll_unattended_preset_` 带库名具体标记检查，不做裸 token 子串）。P2 同步：合成反例补「两追加键同编号拒」；preset 命名空间标注为操作者承担的隔离前置条件（非所有权/空库证明）；§2.3 明确既有四份 README 例外集保留（plan_arm README 走 protected 例外，不进 known/fresh）；§4.1「accept_database_dropped 只在这一支适用」改为「DROP 断言只在自建支适用（preset 支按分支断言）」与 §4.3 对齐。
>
> **终裁（2026-10-02，第五轮）**：第四轮 codex 裁接受、grok 附条件接受（最后一组 P1：§6.4 证据格括号说明含禁标字面量会自反）+ P2（规范形态行的体内插入变体）；两处已修（§6.4 证据格去禁标字面量、§4.4 声明禁标只作断言针；§2.3 合成反例改双拒理由）。第五轮两路均终裁**接受**，无残余 P0/P1。三轮循环共处理 10 组 P1（含亲验驳回 1 条）与全部 P2；计划自始至终未改 tick/settle_once/SQL，父裁决（旧 gate 不动/2 轮/追加式）全部保持。

---

## 一、亲验为真的关键主张（先记录，供实现者不再重查）

以下计划主张逐条对过活体代码与 git 对象，**全部成立**：

| 计划主张 | 证据 |
|---|---|
| §2.2 预存红三条在 HEAD 上均红 | ① `r0_source_scope` 的 `assert extra <= {… startswith("v13/goal_supervisor/")}`（`v13/plan_arm/test_plan_arm.py:361-363`）：`git ls-files v13` 现含 `fair_claim`/`fair_driver` 8 个文件，断言红。② `protected` 逐字节相等含 `v13/load.py`（`:366-367`）：`git diff fb295ac -- v13/load.py` 恰两个 hunk、纯 `+` 行（`SQL_LOAD_ORDER` 表尾 1 行 + `STAGE_THROUGH "fair_claim": 39` 1 行），与计划 §2.2「已核验的 diff 形状」逐字一致。③ `test_goal_supervisor.py::test_stage_bytes` 的 `git diff R1 -- v13/load.py` 须为 `b""`（`:246-247`、`:270-271`）：R1 早于 `b761d9c`，红。 |
| §2.3 `r0_source_scope` 不在自身 AST 冻结集、可直接改 | `git show fb295ac:v13/plan_arm/test_plan_arm.py | grep -c "def r0_source_scope"` = 0。AST 冻结循环只约束 `old_functions`（fb295ac 时已存在的函数；`test_stage_bytes` 跳过，`main`/`run` 过滤 `r[01]_*()` 追加行后比对），新函数仅要求 `r0_`/`r1_` 前缀（`:413-414`），**不冻结新函数正文**；模块级 `normalize` 比对只覆盖非 FunctionDef 节点（`:409-411`），改 `r0_source_scope` 体内、从体内调用新函数 `r1_phase_d_prefix_allowance` 均合法。 |
| §4.4 `test_goal_supervisor.py` 不在冻结测试集 | `tests` 集恰为 `{plan_arm, frontier_gap, goal_supervise, loop_driver}` 四份测试（`:353-355`）；`goal_supervisor` 测试文件是 `extra`（经 `v13/goal_supervisor/` 前缀放行），AST 规则完全不触及它。新增顶层断言函数命名自由、`run()` 追加调用自由——计划正确丢弃了 Oracle 2 的 `a1_` 前缀与 `{r0_,r1_,a1_}` 前缀集放宽（那条基于 Oracle 2 的错误前提）。 |
| 提交② 路径集不需要 frontier_gap/goal_supervise 自身改动 | 两 gate 的 `stage_bytes` 已用追加式谓词：`removed == []` + `tail_ok`（`frontier_gap:351-367`、`goal_supervise:287-304`），`fair_claim` 表尾追加不触其 `load_ok`；其冻结 diff 路径已剔除 `plan_arm`/`loop_driver`（`frontier_gap:341`、`goal_supervise:283`）且不含 fair 目录，diff 保持空。二者红仅来自 `r0_source_scope()` 抛错。计划 §7 提交② 的「若仍红且失败行不是 r0_source_scope：停」守卫成立。 |
| §4.3 夹具序列与 gate 夹具逐一对应 | `open_root`（`route_policy_name=default, version=2` → `user/message` → `v13_submit_override(intent=direct)`，`:82-99`）；领取形 `UPDATE`（status/attempt/fence/lease 五字段）+ 5 参 `v13_complete`（`:121-130`）；`spent()` 用 `"turn/" + "material_spent"` 拼接（`:133-136`）；stale 夹具 = `sup.settler._r1_before_advance` 钩子内再 `v13_submit_override`（`:631-646`）；skipped_failed 夹具 = 先 `v13_goal_stop` 再 `result || {"failed": false}`（`:527-532`，`false` 使键在场、非 null，与 `stopped_without_failed_key_still_settles` 的无键反例互补）；unknown/cancel 两墙 = `unknown`+`blocked_unknown` 与 `v13_cancel(sid)`（`:602-616`）。 |
| finish 第 2 轮 `completed` 有 SQL 依据 | `v13/plan_arm/v13_plan_arm.sql:550-552`：`result_kind = 'finish'` 时 `PERFORM v13_closeout(p_sid, 'completed', 'harness_finish', false)`。计划 §9 的「第 2 轮非 completed 即停」兜底合理。 |
| 其余抽查 | `ALLOWED_V13` 恰 15 项含 `v13_wake_is_satisfied_v1`（`driver.py:16-32`）；wake `event` 变体缺 `effect_done` 即 RAISE（`v13_spawn.sql:821`）；`setup_db.py` 的 probe/拒绝不 DROP/`load_stage(...,"goal_supervise")` 到 38 不装 39（`STAGE_THROUGH["goal_supervise"]=38`）；`accept_real_provider.py:17-30` 的拆字面/未授权 `return 2`/重导入在 `authorized_main` 内；README 四个硬子串与 fourth-duty 行的 `:332-804`；矩阵 `goal_supervisor gate` 行与 M3 三行、台账 M3 节的现状；`R1` 常量在 `:40`；B6「本 tick 默认不调用」句在 children_terminal 行。 |

三处 lane 间分歧的取舍（新脚本 vs 改 main、2 轮 vs 8 轮、追加式 vs 钉 blob）均按父裁决落在计划里，且实现细节（如提交②信息从「pin」改「allow」）与裁决自洽。

---

## 二、发现（按严重度）

### H1（高，实现阻断）：§4.2 停止规则的「未付」取值来源未钉死，两种读法一对一错，错的读法使两条场景断言不可满足

`tick` 的 report 里 `report["unpaid"]` 是**结算前快照**（`driver.py:193` 先 `report["unpaid"] = list(unpaid)` 再进结算分支），且 `status` 只在 tick 开头读一次——结算成功后 tick 继续用陈旧 `status`（`"waiting"`）走完 replan/hold/lease/`v13_recover_idle`/投影，`word` 保持默认 `"waiting"`。因此：

- progress 场景第 1 轮结束时：`word="waiting"`、`report["unpaid"]=[候选]`（非空）、**tick 后实读 `unpaid_after=[]`**、human 空。
- finish 场景第 1 轮同上，且 session 已是 `completed` 但 word 仍是 `"waiting"`。

计划 §4.2 规则 6 写「`word == "waiting"` 且未付空且 human 空 → `stable_waiting`」，规则 5 写「…未付已清」。若「未付」读作 §4.2 自己规定要记录的 **tick 后只读 `unpaid_after`**：

- progress 第 1 轮即命中规则 6 → `rounds_used=1`，与 `accept_progress_second_round_quiet` 的 `rounds_used=2` 直接矛盾；
- finish 第 1 轮同样命中规则 6 → 循环停在 `stable_waiting`，**永远看不到第 2 轮的 terminal**，`accept_finish_observed_next_round` 不可满足，且把已完成会话分类成 stable_waiting（掩盖终态）。

若「未付」读作 **`report["unpaid"]`（结算前快照）**：progress/finish 第 1 轮快照非空 → 规则 5/6 均不命中 → 开第 2 轮 → 全部场景表成立（quiet 第 1 轮快照空 → 规则 6 → `rounds_used=1` ✓；human 两轮 → 规则 5 到上界 ✓）。

即：只有「快照」读法自洽，但计划文本没有说明取哪个，而 §4.2 明文要求每轮记录 `unpaid_after`，自然诱导实现者用后者。**修正**：在 §4.2 规则 5/6 处显式写「未付 = 本轮 `report["unpaid"]`（tick 开始时的快照）」，或等价地给规则 6 加「且该轮 `settle_once` 计数为 0」条件；并在台账记一句为什么用快照（「本轮还有事做」不是稳定等待）。不钉死这一点，提交③的授权实跑第一次就会红。

### M1（中，自相矛盾）：§4.4 静态扫描白名单禁掉了 §4.2 强制要求的 `unpaid_after` 读

§4.2 每轮记录要求「tick 后只读的 `unpaid_after` id 列表」，读法只能是 `SELECT … FROM v13_unpaid_harness_turn(sid)`（gate 自己的 `unpaid_ids()` 即此，`:137-140`）；§4.3 的 `unpaid_remaining` 三场景也断言「候选仍在」。但 §4.4 给 `accept_unattended.py` 定的扫描规则是：允许夹具调用 `v13_open_session/v13_submit_override/v13_enqueue_effect/v13_complete/v13_goal_stop/v13_cancel/v13_append_event/v13_probe` 八个具名函数且**只出现在夹具函数内**；「循环函数只调 `GoalSupervisor.tick`/`close`」。`v13_unpaid_harness_turn` 不在八者之列，循环/观测函数按此扫描必被禁——按计划字面实现，验收脚本无法完成自己规定的逐轮观测。**修正**：把 `v13_unpaid_harness_turn`（只读投影，gate 测试文件本就自由调用）加入允许集并注明用于轮后观测；同时把「循环函数只调 `GoalSupervisor.tick`/`close`」改写为「循环函数对监督机器只调 `tick`/`close`」（观测 SELECT 不算）。

### M2（中，工件合同冲突）：§6.4「UA 未授权负例」行状态写 `exit_0`，违反矩阵文首自己的状态规则

矩阵文首：「状态从 `not_run` 起。**只有对应 gate 退出码 0 之后才写 `exit_0`**。不设 `real_authorized_exit_0`」。该行的命令是未授权脚本（退出 2），证据列也写「退出 2」；嵌入这三态断言的 fake gate 按裁决 A 永远以 ASK_USER 非零收尾。此行状态 `exit_0` 既不匹配命令退出码、也不匹配 gate 接受形态，与计划 §4.6 自己的「矩阵 `goal_supervisor gate` 行不得写成 `exit_0`」精神相抵。D4 又把状态词限定在「只用既有 `not_run`/`exit_0`」——但 `expected_nonzero` 同样是本矩阵既有状态词（现存三行在用），且正是「非零接受形态」的准确词。**修正**：UA 未授权负例行状态改 `expected_nonzero`（接受形态=退出 2 三态 + fake gate ASK_USER 载体），并把 D4 的措辞放宽为「只用既有状态词」；或将该行改记 gate 断言集、状态按 gate 接受形态。需要父/计划改一处 D4 文字，属计划内修正，不动裁决。

### M3（中，基线内容无声丢失）：Oracle 2 的 `V13_UNATTENDED_DB` preset 被静默丢弃，不在三项已裁丢弃之内

Oracle 2 §4.1 明确含 preset 支持（「形状同 `V13_REAL_CHAIN_DB`…preset 必须存在、不得 `agent_v13_%`，preset 模式下 `CREATED=False`、不 DROP 别人指名要留的库」，先例 `accept_real_provider.py:22-23`、`:158-176`）。终稿 §4.1 的库生命周期完全没有 preset，也没有一行说明为何删。这不是三项父裁丢弃之一，按「其余必须保留或无损合并」的标准属于漏项。两点修正任选：① 恢复 preset（含 `CREATED=False` 不 DROP 纪律）；② 在计划 §4.1 或台账记一句「有意简化：验收只走一次性自建库，preset 不提供」，同时注意连带效应——preset 删除后 §4.1 的 `agent_v13_%`/`agent_v13_longloop_p0_probe` 拒绝分支成为不可达防御码（库名恒为自生成 `ll_unattended_accept_*`），保留无害但别当可测行为写。

### L1（低，事实错误）：§4.6「B6 表 23 行」——实际 21 行

`test_static` 的 `need` 列表 21 项，`check("b6_rows_present", rows == need)`（`test_goal_supervisor.py:303-317`）；README B6 表恰 21 个数据行。「23」沿自组合提示的架构表（属上下文，非基线），进了终稿正文。**修正**：改 21 或删掉行数、只留「`need` 列表逐行解析」的机制描述（后者更抗漂移）。

### L2（低，数字口径）：§1/D1/§4.4 的「现有 63 项断言」vs 矩阵记录的 62 checks

矩阵 M3 行记「62 checks」；`N` 是 `check()` 调用计数（同名标签会重复计数，如 `waiting_with_unpaid_remaining_is_failure` 三次）。终稿 §6.4 又写「旧库名/62 checks」——同一文件内两种口径。**修正**：统一为「62 checks（上次实跑）；标签集合以活体为准（OQ1 已如此处理），N 只增不减」。OQ1 的活体快照机制已把风险兜住，仅口径需改。

### L3（低，行号漂移）：三处 file:line 小误

- `main()` 尾部三行实际在 `test_goal_supervisor.py:939-941`（计划 §1 写 `:936-941`）；
- `settle_once` 哨兵块实际 `loop_driver/driver.py:467-553`（BEGIN`:467`/def`:468`/END`:553`；计划 §11 写 `467-552`）；
- §6.1「§7 十条回归」——十条清单在 §6.3，§7 是提交边界。

均不改变主张实质，随手改。

### L4（低，边界未记）：两类 tick 既有行为落在停止规则之外，计划与导出都没提

1. **ambiguous hold 根**：tick 对 hold 根返回 `word="waiting"`、`hold=True`（`driver.py:236-247`），未付空、human 空 → 规则 6 第 1 轮即 `stable_waiting` 退出 0。行为无害（hold 本就无进展可做），但 stop_reason 闭集没有 hold 类别、场景表没有 hold 用例，「稳定等待」的语义把「被外部持有者卡住」也收进来了。至少台账记一句；若父想区分，加第四停止类别是范围变更、须另裁。
2. **finish 场景第 1 轮的既有副作用**：结算完成后 tick 用陈旧 `status` 继续执行 `v13_recover_idle`（写）与全部只读投影（`driver.py:249-267`）——即对已 `completed` 的会话做了一次 recover+投影。这是 M3 已验收的 tick 行为、非本计划缺陷，但验收脚本逐轮计数里会出现它；台账预记一句，避免收尾时被误读为回归。

---

## 三、基线内容覆盖结论（对应复审要求第 1 条）

除 M3（preset）外，三 lane 的实施承载内容在终稿中**已无损合并或等价加强**：Oracle 1 的 64 条断言名收敛为终稿 §4.3/§4.4 的「gate 侧 10 + 授权侧 17」并逐条对应（拒绝三态、头部无网络、拒时零库、一次性库已 DROP、每轮至多一次 settle/advance、三墙仍失败、human 不 skip、wake 不消费、原断言保留、负例永不填授权行）；Oracle 1 的 exit 分类闭集并入 `stop_reason` 六值 + 错误表；Oracle 1/2 的 load.py「38 项前缀保持 + 尾部追加」合并为终稿追加式正向证明；Oracle 2 的「全绿则跳过提交②并点名」保留（§7）；Oracle 2 的 frontier_gap/goal_supervise 提交②改动经代码核实**正确删除**（见一、第 4 行）；Oracle 3 的内容构成终稿主体，钉 blob 换追加式、提交信息「pin→allow」同步换词。Oracle 2 基于「goal_supervisor 测试受 AST 冻结」错误前提的 `a1_` 前缀机制被正确丢弃（代码证据见一、第 3 行）。

## 四、会改变设计或实现顺序的问题（对应复审要求第 5 条）

1. **H1 的取值来源**（report 快照 vs `unpaid_after`）——不改则提交③授权实跑必红，是最先要裁的一条；推荐「快照」读法（改动最小、与场景表全兼容）。
2. **M2 的负例行状态词**——影响 §6.4 模板与 D4 措辞，须在提交③写矩阵前定（`expected_nonzero` vs 重定义该行所指）。
3. **M3 的 preset 去留**——去留皆可，但要在计划/台账落一句，避免后续以「先例对齐」名义反补。
4. **M1 的白名单修补**——决定观测读的归属（加白名单项 vs 改「循环函数只调」的措辞），影响 §4.4 断言 `test_static` 扫描的落地形状。
5. （可选）**L4 的 hold 分类**——是否需要第四停止类别属范围裁量，默认记台账即可。

## 五、结论

计划与三路基线高度忠实，冻结放宽形状、提交边界、场景/断言清单、声称上限均经活体代码核实成立；三处父裁决丢弃执行正确。须先修 H1（停止规则取值来源）与 M1（扫描白名单 vs 强制观测的自相矛盾）再开工提交③；M2/M3 是工件与基线完整性问题，随提交②/③的文书修正；L1–L4 随手改。无 P0 级结构性缺陷：不需要改 `tick`/`settle_once`/SQL，不需要新目录或新状态源，与计划的「定点变更」定性一致。
