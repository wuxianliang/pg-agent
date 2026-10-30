# v13 controller thin cut 计划评审（2026-10-10）

评审对象：

- 计划：`docs/plans/v13-controller-thin-cut-2026-10-09.md`（下称「计划」）
- 导出基线：`prompt-exports/oracle-plan-2026-10-10-000856-v13-controller-thin-f0f6.md` 第 444 行起的 `# V13 Controller Thin Cut: Implementation Plan`（下称「基线」）。444 行以上的 composed prompt、选文件转储、被截断的初稿只作上下文。

方法：逐条比对基线与计划，并对两份文件引用的承载接缝做代码抽查（v13 SQL、`driver.py`、三份测试、两份收尾 review、loopx / repoprompt-ce 引用）。下文每条都给出证据与精确修正。计划与基线的绝大多数语义性断言（信封链、一次 advance、sql 臂行为、observe 行形状、冻结机制、stage 计数、收尾落点）经代码核验**成立**，问题集中在下列各条。

---

## 1. 基线中实现承载内容在计划里缺失、弱化或泛化

### F1. `waiting` 的第二条活体来源被丢掉（轻）

基线 2.4 明确：「A ready or claimed effect also reaches the early `waiting` return in `v13_plan_arm.sql`」。计划只保留 no-override / `triage_fail_closed` 一条路。

- 证据：`v13/plan_arm/v13_plan_arm.sql:404-467`：`IF EXISTS (... status IN ('ready','claimed'))` → `UPDATE sessions SET status = 'waiting'`（:465）→ `RETURN 'waiting'`（:466）。
- 影响：gate 不需要这条夹具，但删掉后，计划读者会把 `advance_word == "waiting"` 等同于 triage 拒判；而 `wait` disposition 的语义本就包含「既有 effect 待领」。
- 修正：在计划「活体 waiting / stale」一节补一句：ready/claimed effect 也走同一早期 `waiting` 返回（`:404-467`），本 gate 不覆盖该路径。

### F2. stale 夹具的检查集被静默收窄（轻）

基线 stale 步骤 9 要求「pre-existing effect/request tokens remain unchanged（若夹具含既有 watermark 检查）」；生产夹具实际有四条检查：`watermark stale`、`watermark zero write`、`watermark seq +1`、`watermark tokens`。计划只保留 `controller_stale_zero_write`，未说明丢弃其余两条。

- 证据：`v13/agentctl_verbs/test_agentctl_verbs.py:1497-1526`：`watermark seq +1`（:1518-1520，断言 steer 恰好把 child `next_seq` 抬 1）与 `watermark tokens`（:1526，断言既有 human effect 的 `request::text / request_hash / attempt_no / fence / lease_owner / lease_until` 不变）。`watermark zero write`（:1517）断言 `snapshot_window(cur) == before`，`snapshot_window`（:325）覆盖全部 sessions / events / effects 行及 artifacts / latches 计数——它证「advance 零写」，不证注入步本身。
- 影响：`seq +1` 量化注入步（防「侥幸 stale」的读法），`tokens` 证注入不碰既有 effect。零写单条在「word==stale 已证水位移动」的意义上够用，但计划自称「复制 `:1497-1527` 的顺序」，应收窄声明或补检查。
- 修正：二选一并写明——（a）gate 复制 `seq +1` / `tokens` 两条；或（b）明确声明本切只证 advance 零写，注入步检查留在生产 gate。同样地，README 追加节漏了基线要求的「supplied-snapshot stale behavior」条目（计划 :389-395 只有签名与整份 parse），补上。

---

## 2. 欠指定接缝、矛盾、错误引用、缺失依赖

### F3. 调用图里的 hop 前 `decide_controller_disposition` 与全文矛盾（重）

计划 :114 调用图在 `UPDATE context_active_revision` 与 `run_controller_once` 之间插入了一次 `decide_controller_disposition`，注释「仅当本 hop 的前置词是 run_now」。这不成立：

- 纯函数的回执要求 `advance_word` / `observe` / `readback`，hop 之前三者都不存在；计划没有定义任何「hop 前回执」形状。
- 与计划自身矛盾：`run_controller_once` 步骤 3-4（:233-240）由方法内部本地 import 调纯函数；纵向 gate 快乐路径（:269-273）直接调一次 hop，无前置判定。基线的链（导出 :937-948）同样没有这一步。
- 来源可考：composed prompt 的 relationships 注「host may call the pure function directly and call `run_controller_once` only on `run_now`」说的是**串联下一跳**的条件，本里程碑一跳，不适用。
- 修正：删掉该箭头；若想保留串联约束，改写为「后续 hop（不在本切）只有在前一回执 disposition 为 `run_now` 时才允许发起」。

### F4. 「方法体被改必须失败」的证明机制缺失（重）

计划要求 `r1_driver_restore` 使「方法体被改到与工作区当前批准文本不一致」失败（:368），`r1_freeze_positive_proof` 新增「空方法 / 方法被改 / 挪进哨兵」负例（:370）；基线 3.5 同样要求拒绝「a mutated controller method that does not match the current working tree's approved extra」。两份文件都没有给出机制，而代码证明朴素的整段剥离**证不出**这类变异：

- 证据：现行 `r1_driver_restore`（`v13/plan_arm/test_plan_arm.py:275-291`）正则剥哨兵后与 git 基线逐字节比较；`r1_freeze_positive_proof`（:294-324）在内存里改字节重跑 restore 取 `AssertionError`（`run_turn` 改名之所以失败，是因为残余文本与基线不等）。若 `run_controller_once` 也被整段剥掉，方法体内任意改动随剥离消失，残余仍等于 `fb295ac`——变异通过。哨兵内容的现行检查（`def settle_once` 在块内、一句 `FOR UPDATE`）也不是字节钉。
- 唯一可行的真值来源：把方法的批准文本（或其哈希）嵌进某个 `r1_*` **函数体内部**（函数级常量合法——`r0_source_scope` 只冻 `fb295ac` 已有函数体与模块级 setup，`:925` 的 `changed module setup` 禁止新增模块级常量；`r1_*` 函数体可改，`:926-927` 仅要求新函数以 `r0_`/`r1_` 开头）。剥离即「精确匹配批准文本才剥，否则失败」。
- 修正：计划须点名该机制与存放位置，并写明连带成本——改方法体的任何提交必须同步更新 `r1_*` 内嵌文本；否则实现者会交一个正则剥离版，满足除「变异失败」外的全部断言，静默漏掉该负例。「缺方法 / 重复 / 挪进哨兵」三条靠计数与剥离边界即可机械判失败，只有「空方法 / 方法体变异」依赖此锚点。

### F5. observe 失败包装多一个 `reason` 键，与闭集形状冲突（中）

计划规定 `observe` 必须是 `{schema_version, ok, rows, hints, pointers}`（:158-160），优先级 2 把 `ok == false` 归为**语义** repair（:187, :196）。

- 证据：`v13/agentctl/v13_agentctl.sql:21-27`：形状失败时返回的包装**多一个 `reason` 键**（`ok=false, reason='shape'`）。若校验器按恰差五键的闭集验，活体 `ok=false` 包装会抛 `ValueError("controller receipt observe shape")` 而不是走 repair——该语义分支成为死代码。
- 另注：`ok=false` 只在请求形状非法时出现（`:36-37` 要求键恰为 `['ids']` 或 `['hint','ids']`）；未授权 id 返回 `ok=true, rows=[]`（整批隐藏，`:153` 注释）。生产 hop 自己构造请求，`ok=false` 几乎不可达；真正可达的 repair 触发器是 `rows == []`。
- 修正：明确 observe 校验器接受可选 `reason` 键（至少当 `ok` 为 false 时），并把「`rows` 为空 = 未授权/不存在目标的正常隐藏路径」写进纯函数语义注记。

### F6. 新 gate 的夹具依赖来源未指定（中）

计划的 `controller_stale_zero_write` 需要 `snapshot_window`；快乐路径夹具需要 `shrink_catalog`、`call_verb`、`controller_pair`、`prepare_chain` 形状的 mock 序列。计划只说「夹具按 `prepare_chain` 的形状，不要 import 那个测试模块去跑它的 main」（:259），没有说这些 helper 从哪里来。

- 证据：上述 helper 全部定义在 `v13/agentctl_verbs/test_agentctl_verbs.py`（`shrink_catalog` :229、`snapshot_window` :325、`prepare_chain` :1262、`controller_pair` :1498 内使用、`call_verb` :1512 内使用）。该模块 import 无副作用（连接都在函数内，main 有守卫）；`v13/loop/test_loop.py` 的 `set_mock`（:67）/ `mock_from_needed`（:111-129）同样 import 安全。
- 修正：计划应二选一写明——从生产测试模块 import 这些 helper（安全，且与「不跑它的 main」的字面一致），或在 gate 文件内本地复制。含混会导致实现者各自发明，尤其 `snapshot_window` 的覆盖范围（全表快照）直接决定 `controller_stale_zero_write` 的语义强度。

### F7. 「`GoalSupervisor.tick` 只调 `settle_once`」被代码证伪（轻）

计划 :84。证据：`v13/goal_supervisor/driver.py` 的 `tick`（:174 起）在 :201 调 `settle_once` 之外，还调 `_session_status`、`_lifecycle`、`_unpaid`、`_maybe_replan`（:218）、`_holds`、`v13_notify_project`（:222/:252）、`v13_observe_fold`（:226/:255）、`v13_goal_lease_once`（:235）、`v13_recover_idle`（:240）、`v13_scheduler_hint` / `v13_should_run` / `v13_plan_current` / `v13_selected_todo` / `v13_goal_stop`（:260）。

- 修正：改为「`tick` 的推进只经 `settle_once`（:201）；它从不调 `serve` / `run_turn` / `v13_complete`，故不进入本路径」。计划要证的结论不变，措辞必须收窄。

### F8. 行号引用批量勘误（轻，但计划是实现合同）

以下引用经代码核验为准（左 = 计划，右 = 实际）：

| 对象 | 计划 | 实际 |
|---|---|---|
| `WHEN 'sql'` 臂 | `v13_plan_arm.sql:771-843`（:39、:469） | `:772-813`（`RETURN 'progressed'` :813；`WHEN 'tool'` 起 :814） |
| `v13_route` / finish | `advance.sql:110-166` / `:129-132` | `:110-163` / `:130-131` |
| `tool_calls` → `tool/call` | `v13_acl.sql:408-424` | 捕获 `:408-410`，追加 `:424-427` |
| `actl_chain_full` | `test_agentctl_verbs.py:1262-1335` | `:1315-1442`（`:1262` 是 `prepare_chain`） |
| `context_active_revision` UPDATE | `:1303-1306` | `:1329-1332` |
| 整份 parse 进 advance | `:1307-1308` | `:1333` |
| waiting 夹具 | `:1381-1405` | `:1381-1412`（检查 :1400 / :1406） |
| stale 夹具 | `:1497-1527` | `:1497-1526` |
| observe GRANT | `v13_agentctl.sql:128-129` | `:134-135`（授予**角色** `v13_route`，`v13_core.sql:822`，与函数同名） |
| pointers 块 | `:114-121` | `:112-124` |
| `v13_observe` 行 | `v13_observe.sql:43-54` | RETURNS TABLE `:44-55` |
| `LoopDriver` 类 / advance / serve / run_turn / _read | `:124` / `:173-177` / `:315-384` / `:441-464` / `:157-162` | `:118` / `:173-178` / `:315-385`（`v13_complete` 追加 :380 ✓）/ `:441-466` / `:157-163` |
| `r1_driver_restore` / `allow()` / `r0_source_scope` | `:275-290` / `:516-521` | `:275-291` / `:516-542`（成员断言 :517-519、减法断言 :520-521，计划对两处语义的描述准确） |
| README 断言名列表 | `:72-78` | `:76` 与 `:78`（全文恰 80 行） |

---

## 3. 代码证伪 / 任务不需要 / 更简单设计可替代

- F3（hop 前 decide）是本类主条目：该行既无输入合同也无任何其它章节支撑，删除即修正。
- F7 属「代码证伪的表述」。
- 「unsupported advance word」分支（计划 :213, :242）经核验**活体不可达**——`v13_advance` `RETURNS text`，全部返回路径只有四词（`'stale'` :368、`'terminal'` / `'waiting'` / `'progressed'` :508/:675/:813，加上前缀与 triage 的 `'waiting'`/`'terminal'`/NULL 透传）。保留它作为 fail-closed 防御是合理且廉价的，**不建议删**，但计划可注明其防御性质，避免读者去找第五词的活体来源。
- 基线与计划的 loopx / repoprompt-ce 边界引用经核验准确（`decide_loop_disposition` 定义在 `loop_controller.py:639-670`，八词含 `capability_action_required` / `stop`，`turn_contract_generated.py:31-39`；`agent_run` 单 `execute(op)`，`AgentRunMCPToolService.swift:412-438`）。计划引 `:1-17` 是模块纯度合同 docstring，可接受；如需精确定义位置可改引 `:639`。

## 4. 计划与基线都缺的内容

- **observe `reason` 键与 `ok=false` 可达性**：见 F5，两份文件均未覆盖。
- **`blocked_unknown` 状态落空**：`sessions.status` CHECK 为 `('ready','waiting','blocked_unknown','completed','failed','cancelled')`（`v13/schema/v13_core.sql:14-15`）。目标处于 `blocked_unknown`、序号已前进、无 human 时，按优先级落 `run_now`。两份文件都没讨论非终态非 ready 状态的分派；loopx 词表对此有独立的 `capability_action_required`，本切六词折叠了它。是设计选择还是遗漏，需点名（见 Q5）。
- **所有权 / 生命周期 / 失败行为 / 取消 / 可测性**：经核查两份文件覆盖充分——单跳无循环故无取消面；异常原样传播、无重试无二次 advance（计划 :243）；库生命周期归测试 host（自建自丢）；纯函数不连库可直测。除上述各条外无新增缺口。

## 5. 答案会实质改变设计或实现顺序的问题

- **Q1（源于 F3）**：调用图的 hop 前 decide 是笔误还是意图？若意图存在「hop 前闸门」，其回执形状必须新设——这会在 W1 之前插出一个新合同。默认应按笔误删除。
- **Q2（源于 F4）**：方法的批准文本 / 哈希嵌在哪个 `r1_*` 函数体内？这决定 W3 的实际改动面与后续每次方法体编辑的双处同步纪律，必须在动工前定。
- **Q3（源于 F6）**：gate 的 helper 是 import 还是本地复制？import 让 gate 跟随生产夹具演进；复制让 `r1_phase_d_prefix_allowance` 的两文件集合保持干净语义但引入副本漂移。影响 W4 的文件体量与维护方式。
- **Q4（源于 F5）**：observe 校验器接受可选 `reason` 键，还是把 `ok=false` 改判为形状错误？前者与优先级表一致，后者会删掉一条语义分支。答案直接改变 `controller.py` 的校验代码与 `controller_disposition_repair` 的构造回执用例。
- **Q5（源于 §4）**：`blocked_unknown`（及任何未来非终态）目标在序号前进时返回 `run_now` 是否为选定语义？若是，值得在 TC-1 或优先级注记里写一句；若不是，需要在 terminal 与 run_now 之间加规则——那将改动六词优先级，属于合同级变更。
- **Q6（源于 F2）**：stale gate 是否保留 `watermark seq +1` / `watermark tokens`？影响 W4 的断言清单与 README 追加节的 label 列表。

---

## 已核验成立、不再重议的关键前提（节选）

- 信封链而非 FakeLLM `tool_calls`：`v13_route` 工具名来自信封 `intent`/`tool`（`advance.sql:116-117`）；`v13_complete` 只把 `tool_calls` 记成 `tool/call`；route 见 `llm/message` 即 finish。
- 一次 advance 不 serve：sql 臂事务内 `EXECUTE` handler（`:787-788`）、插 effect、返回 `'progressed'`；`serve` 只领 `llm`/`tool`。
- 冻结机制：R1 哨兵 `:467-553` 仅包 `settle_once`；`fb295ac` 无 `r0_*`/`r1_*`；`r0_source_scope`（`:847-928`）在 :900-902 调用三个 `r1_*`，并被 `test_plan_arm.py:272`、`test_agentctl_verbs.py:1583`、`test_loop_driver.py:931` 三处引用——因此计划 W3 的「与 W2、W4 同一工作区，否则 `r0_source_scope` 红」因果链成立。
- `load_stage(..., "agentctl_verbs")` 累计装到 stage 41；动词 SQL 是 plain `CREATE FUNCTION`，重复 apply 必败——计划「不要再 run_psql 动词 SQL」正确，且正确偏离了生产 gate 自身 `setup_db` 只装 `agentctl` 再补 run_psql（`:1609`）的做法。
- `v13/load.py` 44 个 stage 键、无 45；`agentctl_verbs=41`、42=goal_workflow、43=external_exec、44=ce_map。
- observe 行恰 11 列；`is_terminal = status IN ('completed','failed','cancelled')`；`pending_human` = 存在 ready/claimed 的 human effect（`v13_control.sql:121-127`）。
- 收尾落点：矩阵末行 #90（#91 空闲且无撞名），台账 Stage 44 末签 `S44-5`、无 `TC-*`；被拒绝的 native 计划确曾预写 #91/`S46-*` 措辞（`v13-native-wait-poll-steer-2026-10-09.md:165-178`），不采其措辞有真实所指。
- driver 返回词是裸 text（`advance` 返回 `rows[0][0]`），uuid 全程以 str 流动（无 `register_uuid`），observe 经 `_read` 提交短读、不进 `calls`、不查 `ALLOWED_CONTROL_SQL`。
