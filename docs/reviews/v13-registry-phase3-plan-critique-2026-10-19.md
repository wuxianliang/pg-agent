# v13 Registry Phase 3 收尾计划：有界正确性/保真评审

> 日期：2026-10-19。评审对象：`docs/plans/v13-registry-phase3-closeout-2026-10-19.md`（最终稿）对照 `prompt-exports/oracle-plan-2026-10-19-090752-v13-b3b005-e64b.md` 的 Generated Plan。
> 方法：只读。证据根 `.claude/worktrees/v99`（`93d05f1`，tracked 干净，仅未跟踪 stage41 review）。没有运行 gate、没有改计划或实现。
> 不重提 §10 已列且被代码/Oracle 支持的纠正（20 替换、604 sentinel、fences 先于 CAS、pin_matches 不读 clock、A/B 各自 push、单里程碑、不预填 B hash、不做 C、回退 runbook 降级）。
> 约定：「已验证」= 本轮用只读命令亲自核对；「推断」= 由读码得出。

## 0. 基线覆盖核对结论

原 export 的主体（现状分层、接口表、数据流、20 项闭集、ACL/锁边界、错误边界表、逐文件影响、51 项 manifest、环境保护、状态机、G0–G6、证据寿命）在最终稿中**基本保留**，且被 §10 的纠正有依据地替换。未发现因「具体」而被删的大块内容。弱化项见 §1，均为局部。

已验证：最终稿 §6.3 的 51 行与 V99 `README.md` 清单逐行相同（路径、参数、退出码）；历史数字 951.81s、911.44s、49 个 exit 0、485/289 checks、trace SHA-256 `3496c6a4…933a`/mode 0644 均与 `prompt-exports/w5-phase2-*` 收据及当前文件一致。

## 1. 原 export 支持内容的丢失/弱化

1. **G 级 Stop conditions 被压扁。** export G1：「文档措辞把协议测试写成生产 worker、把 INFERRED 写成 DIRECT、误删历史 RED，均退回修订」；G2：「ignored receipt 是唯一事实来源、manifest 被省略或未执行条目被算通过时不得进入 G3」。最终稿 §8 工作项表只有 Done when，这两条没有对应的显式闸门，只散落在 §2.2/§4.3。这是**执行时最容易被越过**的两个文档质量闸，应恢复为 G1/G2 的显式 stop。
2. **immutable trigger 行丢失。** export §6：「pin/event mapping 修改或删除 → immutable trigger 抛错；不绕过 trigger 清理历史」。最终稿 §7 只保留「capture/FK/guard 失败回滚」，没有「手工 UPDATE/DELETE pin 或 mapping 被拒、运维不得绕 trigger」。runbook §4.1.4 只说「不手工补 pin/mapping」，未说明修改/删除也被 `trg_v13_effect_context_pin_frozen`/`…event_pin_frozen`（SQL `:642`、`:665`）拒绝。
3. **静态 preflight 清单缩水。** export §5 列了「`v13_effect_envelope` 剔除 registry revision；advance 第八键存在；loaded consumer 定义列表与 README 一致」「immutable trigger、capture trigger、ACL 矩阵」。最终稿 §6.1 缺这三项显式条目，只写了「使用现有守卫核验」。注意这些守卫（`test_consumer.py:952` 起）是行为/闭集守卫，并未逐项断言 README 文案一致；README 一致性必须由人工/最终报告核对，而非「由现有 gate 保证」。
4. **证据表的测试定位丢失。** export 的证据表对每个范围给了测试定位（如 `test_registry.py:220-340`、`:840-915`，`test_consumer.py:640-700`）。最终稿 §2.2 的历史证据表只剩 receipt 路径，没有「哪个 gate 组/哪段断言支撑哪条主张」。最终报告 §4.3 要求「证据分级」，但分级所需的断言指针现在只存在于 export 里，易在报告撰写时丢失（见 §3.2 的一个后果）。
5. **README 行号表述的精度。** 见 §3.4（纯引用错）。

## 2. 欠规格接口 / 决策 / 矛盾 / 依赖

1. **postcommit 红后的持久记录无处安放（矛盾）。** §7 末行：「A 之后 postcommit 红 → 不撤销已推 A，不追加 B「完成」；记录红和未跑并停止」。但 §1/§8 规定唯一合法的后续提交是 docs-only B，且不创建额外提交。「记录」到哪里？A 已 push，仓库里 A 的报告写着「postcommit pending」；若只在会话里回报，则 `origin/v99` 上永久留着一份未闭环、无红灯记录的 A。必须二选一并写明：(a) 允许一个状态为 RED 的 B（同样 docs-only、立即 push、同样遵守 AGENTS）；或 (b) 明确接受不写入仓库、仅由交付回执报告，并让 A 的措辞在 pending 状态下自洽。当前稿两者都没选。
2. **「执行面」未定义，B 的 docs-only 核验不可执行。** §8.2 要求 `git diff A -- <执行路径>` 为空，但 `<执行路径>` 没有枚举。B 必须改 `v13/registry/README.md`（在 `v13/` 下），而 runner 在运行时**从工作树 README 解析 51 项清单**（`prompt-exports/w5-phase2-runner.py`：正则 `^\| \d+ \| \`(v13/[^\`]+)\` \| ([012]) \|$`，`len(items)==50` 时自动补 consumer，断言恰 51 且互异）。因此 README 的编辑有一条硬约束：**清单表行必须逐字节不变，且不得新增匹配该正则的表行**（例如结果表若写成 `| 17 | \`v13/…\` | 1 |` 会让断言失败或造成重复）。计划没有写这条，G1/G3/G5 三处改 README 都可能踩到。建议把「执行面 = 除 §5 白名单文档外的全部 tracked 路径，并另加：README 清单表字节不变」写成 B 的核验定义。
3. **runner 不执行计划要求的验收。** 已读 runner 全文：`valid = code==expected and restored`，仅对 #17/#18 额外查 marker。它**不**核对 #39 的 `485 checks`、#51 的 `289 checks`、HEAD、tracked 干净、PiSwift 保护。§6.3 要求「#39 485、#51 289」「任一计数漂移先解释」，但没有说谁、在哪一步检查（tail 的最后 6 行里恰有 SUMMARY，可人工核；这是可行的，但必须写成显式步骤，否则 `valid=true` 会被当成计数已验证）。
4. **timeout 行为与计划描述不符。** §6.3：「每项结束（包括失败/timeout）恢复 trace」。runner 的 `finally` 确实恢复 trace，但 `subprocess.run(timeout=600)` 抛 `TimeoutExpired` 后异常直接穿出，**不写该行 results.json**，也不会生成「timeout」状态行。同时历史最大单项 #36 `read_tools` = 467.61s（postcommit 收据），余量约 22%。负载高时 RED_REGRESSION 可能是 timeout，而收据里没有这一行——计划应说明：timeout 的证据只在 stdout/日志，需手工入报告，且不是 gate 逻辑失败。
5. **fetch 时机晚。** G0 只记录 `origin/v99` 本地 tracking ref，并明说「未 fetch」；fetch 在 G4 push 前才做。若远端此时已前进，则 precommit 51 项（~16 分钟）与 A 内容全部基于旧基线，§8.1 又要求「重新锁定并重验」。只读 `git fetch origin`（不改工作树）可以并应该放进 G0，把分叉风险提前到花钱之前。
6. **引用了不存在的符号。** §4.1.1：「loader 函数/`stage_bytes` 只是 SQL 来源与测试加载机制」。`v13/load.py` 中没有 `stage_bytes`（已验证：`load.py` 的相关符号为 `SQL_LOAD_ORDER`、`STAGE_THROUGH`、`run_psql:111`、`load_stage:125`）。`stage_bytes` 是 `plan_arm/test_plan_arm.py` 的 `test_stage_bytes`（`:250`），用来 diff 冻结目录，与部署无关。应改为 `load.load_stage`（`load.py:125`）与 `setup_db._registry_sql_parts`（`setup_db.py:209`）。
7. **引用了将悬空的文件。** §References 指向 `docs/reviews/v13-registry-phase3-plan-critique-2026-10-19.md`，但 §5 白名单不含它，且它只存在于主树。A 若携入该计划，会在 V99 留下指向不存在文件的引用。要么从携入版去掉，要么把它列入 A（但那等于把评审工件提交，需要明确决定）。
8. **「本计划仅结果区」含糊。** §5/§8.2 允许 B 修改本计划的「执行状态/结果区」，但计划没有这个区。需要指明区段，否则 B 的 diff 审查无从判定。

## 3. 被代码/用户范围反证的细节（与精确纠正）

### 3.1 外部环境前提已不成立（高置信，已验证）
§6.2 把 `/tmp/pg-agent-w5-PiSwift-v0.87.1/PiSwift` 作为「历史成功环境，复用前提」。现状：
- `ls -d /tmp/pg-agent-w5-PiSwift-v0.87.1/PiSwift` → 不存在；`/private/tmp` 下无 `pg-agent*`。
- `git -C /Users/wxl/Projects/PiSwift worktree list --porcelain` 把该 detached worktree（`bfccb32`）标为 **`prunable … gitdir file points to non-existent location`**。
- `piswift_driver/Package.swift:8` 与 `prepare.py:9` 都硬编码该路径；`prepare.py` 还断言其 HEAD。
- 其余仍在：活动 PiSwift 为 `main@a73c391`、`git status` 为空，tag `v0.87.1` 存在，SwiftPM 缓存里有 `OpenAI-*`/`SwiftOpenAI-*`。

纠正：§6.2 的措辞应是「该 worktree 当前缺失，重建它是对用户 PiSwift 仓库 `.git/worktrees` 元数据的写操作（`git worktree prune` / `add --detach`），需要用户批准」，而不是「核对后复用」。§7 的 `BLOCKED_ENV` 在当前机器上**预计 100% 触发**，而不是例外分支。见 §5.1。

### 3.2 两处证据强度混淆
1. **「claim 内 40001」没有任何测试断言。** 已验证：`grep -rn 40001 v13/**/test_*.py` 无命中。§2.4 第 1 步、§7「函数/adapter 复核发现双 fence 变更 → 函数 40001/CAS 与 pin 回滚」读起来像已观测行为，实为 **STATIC（读码 `v13_registry.sql:822` 起）**。`test_consumer.py:634–688`（`native_worker_protocol`）的 rollback 是**测试里的 adapter 自己比较 fences 后 `adapter.rollback()`**，并非函数抛出 40001。§3.1 第三行说「复核前变化→rollback 直接覆盖」是对的，但仅覆盖 adapter 层；函数层 40001 的等级必须单列为 STATIC，且不能作为「出现半写即 BLOCKED_PHASE2_DEFECT」的可观测判据（没有观测手段）。
2. **「adapter」是测试代码，不是交付物。** §2.4 第 2、3 步描述的 IDLE 起点、三元缓存键、提交前复核，全部出自 `native_worker_protocol` 内联逻辑。生产的 `fair_driver/driver.py:31`（`SELECT v13_claim_fair(%s, %s)`）与 `loop_driver` 没有实现它（计划 §2.2 已承认）。所以「adapter 复核只缩窄窗口」**在当前生产路径上没有被缩窄**——窗口更宽，且旧版 5/6 参 `v13_complete`（`require_pin=false`）完全不核对 pin。文档（README、runbook、教程）必须把这写成「worker 合同 + 测试模型」，不能写成已部署的保护。
3. **spawn_owner 的「先 42501」是 STATIC。** 已验证：`REVOKE … FROM … v13_spawn_owner` 后只授 route/recall/resolve 以 `v13_registry_fences()`（SQL `:799–810`），而 `v13_claim` 是 INVOKER 且第一条语句就读 fences（`:822` 起），故推断先 42501。但 `test_consumer.py:963` 只断言 spawn_owner 对 `v13_claim(text,integer)` **有 EXECUTE**，没有断言调用被拒。§3.1 应标 STATIC。
4. **「无生产 caller」需要写出检查方法。** 已验证：`v13_spawn.sql` 内 `v13_claim` 出现 0 次；spawn_owner 拥有的 SECURITY DEFINER 函数为 `v13_fork`、`v13_open_session`、`v13_spawn_subsession`（`:563–565`）；`SET LOCAL ROLE v13_spawn_owner` 仅在 `:1765` 的一次性自检 DO 中。§3.1/§7 的 G0 说「调用图」但没有给判据。精确的无新增测试判据：对 loaded `pg_proc`，查「owner = v13_spawn_owner 且 prosecdef」的函数 `prosrc` 是否引用 `v13_claim`，以及仓库 SQL/Python 中 `SET ROLE v13_spawn_owner` 点。

### 3.3 Oracle 依据行号偏差
§3.1 的「依据」写 `test_consumer.py:495`、`:634`、`:952`。`:495` 是 `ready_uncommitted` 辅助函数定义，不是 freshness 或 open_session 证据；freshness 在 `native_freshness`（`:504` 起，register 调用在 `:524`），`v13_open_session('{}'::jsonb)` 的验证调用在 `:90`、`:269`、`:507`。§4.1.2 的「`test_consumer.py:495` 附近已验证 jsonb 调用」应改为 `:507`（或 `:90`）。组合场景「INFERRED」的结论本身仍成立：`native_w4_projection`（`:207`）用直接 `UPDATE v13_registry_clock SET revision=revision+1`（`:221` 附近）制造 supersede，而不是真实 `v13_registry_register/retire`，正好支持 Oracle 的 INFERRED 裁决，可在报告里写明这一点。

### 3.4 其余行号/引用错误（精确纠正）
| 计划处 | 现状 | 纠正 |
|---|---|---|
| §2.5 六参 `v13_complete`「`:1290` 附近」「`:1298` 新 strict」 | `:1298` 是**六参** `v13_complete`（计入 20）；strict 七参是 `:1308`；common（`v13_complete_contextual`）正文 `:1070` 起 | 六参 `:1298`，strict `:1308`，common `:1070`（父控制器已确认，待修） |
| §2.1「Phase 2 已确定的 V99 交付线（其计划 `:336`）」 | `:336` 是「使用 `<版本>:` 提交」条；推送条是 `:337`；Phase3 范围限制条是 `:338`（正确） | `:337` |
| §2.5 `v13_parse :2135` | `:2130` 是函数头，`:2135` 是函数体内第一个查询 | `:2130` |
| §2.5 `v13_cap_*`/`tail_gap` 合并写 `:2155`/`:2301` | `v13_cap_human_answered :2228`、`v13_tail_gap_cap_exempt :2237` 各有独立头 | 补列 |
| §2.5/§2.2 README `:228`、`:248` | `### Phase 2 ACL` 在 `:227`，ACL 表约 `:233` 起；`:248` 是 spawn_owner 说明，`### Lock Evidence` 在 `:252` | 按小节名引用，或改 `:227`、`:252` |
| §2.2 摘要 `w4-registry-final-report-20261018.md:3` | `:3` 是 `Commit:` 行，验证数字在其后的 Verification 段 | 改 `:8` 起 |
| §4.2 `06-tool-catalog.md:20` | 行 20 是代码围栏起始，`CREATE TABLE tools` 在 `:21` | `:21` |

## 4. 两稿皆漏的 ownership / lifecycle / failure / testability

1. **旧 pin 与终态 effect 的运维后果没有写。** 对 superseded 的 exact pin，strict completion 仍返回 `accepted`（`pin_matches` 只比对调用者给的 revision），随后 capture 给产生的事件建 mapping，`event_current` 对其为 false。结果是：**effect 已 succeeded、IO 已发生，但其输出被后续投影排除**（`native_w4_projection` 直接证明 finish 不被旧 llm/message 触发）。runbook/最终报告应明确这是「已接受成本」且 Phase 3 不提供重新排队手段，否则读者会以为 supersede 会自动重发 effect。
2. **README 是三方共用的输入。** README 既是文档、又是 runner 的清单来源（§2 第 2 点）、又列入 `plan_arm`/`pi_parity`/`pi_ports`/`read_tools` 的受保护路径集合（只做「名称在许可集合内」检查，已验证 `v13/registry/README.md` 在其中，因此 A/B 对它的修改不会触发 guard）。三个事实应写入 G1 的前置，避免 G1 作者只把它当文档。
3. **PiSwift 环境的所有权与恢复审批。** 谁有权对 `/Users/wxl/Projects/PiSwift` 做 `git worktree prune/add`？§6.2/§7 同时写「恢复需另行批准」和「不改外部 checkout 自救」，没有指明批准的主体和范围。
4. **A 的内容在 precommit 运行时是脏树。** 与 Phase 2 同形（precedent：Phase 2 precommit 也是脏树），但 §8.2 仅对 postcommit 要求「tracked clean」。最终报告应分别记录两轮的 HEAD 与 `git status`（runner 只写 `head.txt`，不写 status），否则「A 净树」证据只在会话里。
5. **receipt label 唯一性与可复现。** runner `OUT.mkdir(exist_ok=False)`，label 复用即失败（安全）；但 label 命名约定（precommit/postcommit、日期）没有固定，容易与既有 `w5-phase2-*` 混淆。

## 5. 真正会改变设计/顺序的问题

1. **把环境可行性检查提前到 G0，并先决定 PiSwift 恢复审批。**（§3.1）当前计划把 G1、G2（两大文档工作）排在 G3 的环境 preflight 之前；在本机，G3 开头几乎必然 `BLOCKED_ENV`。顺序应为：G0 做只读环境探测（`ls`、`git worktree list`、`git fetch origin`）→ 若缺失，先向用户取得「重建 detached worktree」或「接受 pi_parity/pi_ports 不可复现、范围降级」的决定，再动 G1。若用户不允许重建，则 #30/#31 无法在原口径下通过，**整个「完整 51 项」验收主张不可兑现**，必须在 G0 就改写 Done-when，而不是在 G3 才发现。
2. **定义 postcommit 红灯后的收尾形态。**（§2.1）因为 A 先于 postcommit 被 push，红灯路径已是真实分支，需要预先决定是否允许 RED-B。这影响 §1 的「唯一收尾 B」表述和 G5/G6 的 Done-when。
3. **把 runner 的验收缺口补成显式步骤，而非「runner 全绿即可」。**（§2.3–2.4）包括：#39=485、#51=289 的人工核对点、timeout 不落收据行、HEAD/status 记录点。不新增测试逻辑，只是计划动作。
4. **按 STATIC / DIRECT 重标 §2.4 与 §7。**（§3.2）40001、adapter 复核、spawn_owner 先拒绝三处目前读起来像已观测行为；执行者按字面会把「观测不到」当成缺陷触发条件。

## 6. 非问题（已核实，无需改动）

- 51 项清单、预期退出码（49×0 + #17=1 + #18=2）与 README 一致。
- `setup_db.py:52` 的 `STAGE42_REPLACEMENTS` 恰为 20 项（脚本计数）；README `:164` 与 matrix `:249` 是仅有的两处「21」。
- 604 为 sentinel；`events` capture trigger 在 `:698`；pin 表 trigger 在 `:642`、`:665`。
- `pin_matches` 授予 route、spawn_owner（`:815`）；`event_current` 追加授予 recall、spawn_owner（`:2721`）；与 §2.5 ACL 表一致。
- 活动 PiSwift 仍为 clean `main@a73c391`；trace 当前 hash/mode 与计划记载一致（`3496c6a4…`，0644）。
