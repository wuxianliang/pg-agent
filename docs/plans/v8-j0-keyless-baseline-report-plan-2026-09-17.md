# V8 J0：无凭据基线与报告收口开发计划

日期：2026-09-17。状态：Mid-flow 决议与设计审查均已完成（`docs/reviews/v8-j0-keyless-baseline-plan-critique-2026-09-17.md`：0 阻断，2 P1 + 4 P2，已全部并入正文）。**J0 W1–W4 已实施并实测：runner 自检 45 checks、同一 fresh run 24/24 产品脚本 exit 0、源快照无漂移；证据见 `docs/reviews/v8-j0-keyless-baseline-2026-09-17.md`。提交/推送状态以实施交付消息为准，不回填自引用 commit。**

## 1. Goal 与完成边界

落实 `docs/plans/v8-dsh-v10-joint-readiness-plan-2026-09-17.md:68–76` 的 J0：修复 G13 必跑 fake 子例受 provider 凭据门遮蔽的问题；使报告区分支持面符合、最小双 loop 和完整目标；用版本化清单串行执行累计 keyless 回归、保存可核验脱敏证据；逐项更新 README、Conformance 矩阵与偏差台账。

J0 是**一个实施里程碑、一个完成提交**，下述 W1–W4 是内部工作项，不拆成多个 gate/提交。脚本测试通过不等于 P0C 完成，更不等于 v10 正式接入。

### 范围内

- G13 fake/live 编排、显式 optional smoke、精确结果登记与无凭据安全测试。
- 既有 Python 报告器的数据表示、判据、错误标识和独立拒收测试。
- 当前 24 脚本的单一机器清单、V8 专用轻量串行 runner、自检与证据归档。
- J0 stage README 和三份既有收尾文档的事实更正、人读基线报告。

### 明确不做

- 不做 J1 DSH pin/构建、J2 probe、J3 compat 生命周期新接线、J4–J7 provider/loop 对比；不运行上游 DSH 或真实模型。
- 不改生产 SQL、`v8/load.py`、各 stage `setup_db.py`、`v8/loop/runtime.py`、`pinned_host_manifest.json`、能力声明或 SQL seed，不修改 v8/v10 冻结正文。
- 不消解 runtime/协议偏差，不因 Native 绿将 compat 未实现行标为 implemented/passed。
- 不建立通用 CI 平台，不引入并行调度、自动 retry 或新的 provider 抽象。

## 2. Background：已核实的当前行为

行号以调查时主工作区为准；不把 `.claude/worktrees/` 的副本当现状。

| 接口/证据 | 当前行为与影响 |
|---|---|
| `v8/compat/test_compat.py:1076–1084` | `test_deepseek()` 缺凭据时写 real-provider partial、追加外部原因，然后 return |
| 同文件 `1181–1188` | FakeLLM×2 的完整对象相等断言与 fake-suite passed 登记位于早退之后，keyless 下没有执行 |
| 同文件 `89–93,1300–1319` | check 失败抛 AssertionError；main 先 deepseek 再 reporter；缺 fake 结果触发报告器缺项拒收 |
| `v8/compat/p0c_report.py:179–184,258–267` | fake/real-provider 都是 DB 行；effective_blocked 只读 SQL matrix 并在 all-real-io 外部原因下展开 REAL，不会由凭据缺失自动扩大 |
| 同文件 `270–350` | 六类拒收是防假绿的核心；blocked 不能由 results 自报；未实现行必须保留 gap |
| 同文件 `354–405` | build_report 先 blocked，再 unimplemented→partial，再 supplied result；passable 忽略 partial，unmapped fixture 仅回显，passed 恒 False |
| 同文件 `408–431` | render 是现有消费者，必须认识新增状态及三个结论；旧顶层字段有迁移义务 |
| `test_compat.py:1193–1295` | 六拒收只捕获任意 ReportError，部分用例会被更早 missing/block 条件抢先，不能证明命中了目标规则 |
| `v8/loop/runtime.py:258–306` | DeepSeekLLM 读取 DEEPSEEK_API_KEY/OPENAI_API_KEY/OPENAI_API_URI/OPENAI_MODEL，有key可 urllib 外调，无key先拒；FakeLLM 无网络 |
| `v8/closeout/test_closeout.py:704–746` | 有 pop 三环境项、finally恢复、无key拒调用与凭据泄漏探针先例 |
| `v8/compat/setup_db.py:30–31,45–49`；`v8/load.py` | G13固定库 agent_v8_compat，每次DROP/CREATE并累计加载；J0不改其加载边界，不借此接线全部compat生命周期 |
| `v8/README.md:34–59` | 当前24脚本清单；retry/cancel/stream分别两脚本共库，必须串行 |
| `docs/reviews/v8-p0ab-deviation-ledger-2026-09-16.md:95–96,157起` | A87/A88与B范围段是更正落点；保留历史事实，不能全篇重写消除偏差 |

### 2.1 失败基线，不是本轮准出

上位联合计划记载此前 2026-09-17 在 `2b0edf64638872ab06157e5968186e6a814b571f` 实跑24脚本，23 exit0、G13 exit1且独立复现；PG18.4、pgembed0.3.0rc2。错误为缺 `c12-db-fake-suite`。本计划不重新宣称运行，实施须刷新源文件、版本和退出码；临时日志不能当永久归档。

### 2.2 需要更正但不能过度推断的事实

- G13 无凭据失败是测试编排错误，不是 FakeLLM 不确定或 v8 runtime 不可用。
- 将 fake 提成独立函数不增加正式脚本入口数；新增 runner 自检也不是“第25个V8产品gate”。
- README 部分 LATER 与 G17–G19 已交付矛盾，但每行是否整体完成取决于剩余义务，不可把 🟡 一律改 ✅。
- 本地 DSH 已定位不代表 pin、sync_before_io、真实双loop完成。J0只把陈旧 gap 改为准确去向，不填 manifest 能力值。
- 当前 `.gitignore:17–18` 已忽略 prompt-exports；原始日志也只放系统临时目录，不需为本次实现增加通用日志归档系统。

## 3. 决策摘要与工作项执行索引

用户已确认§11三项：普通G13默认keyless、保留终签区分、runner不做resume。以下是据此确定的方案；代码已证明的错误不作为可选项。

| 工作项 | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| W1 fake/live分离 | G13默认keyless且fake实际执行；`--report-json` CLI落地 | 无key/哨兵key环境均零live；fake失败不登记绿；显式smoke状态/退出码准确；报告JSON按§4.1固定接口写出 | test_compat.py | 与W2结果接口共同定型 | S |
| W2报告与拒收 | 状态/角色/三结论不互替，六拒收独立覆盖 | 精确code断言；partial/not_run不通关；optional缺席不阻keyless；能力矩阵不改 | p0c_report.py、test_compat.py | W1登记规则；两者同一实现单元 | M |
| W3串行基线证据 | 24入口机器清单、安全执行/诊断归档 | 自检通过；同一fresh run全部exit0；源快照无漂移且证据脱敏 | regression/v8-gates.json、run_baseline.py、test_baseline_runner.py | W1/W2通过后做产品基线 | M |
| W4文档与收尾 | 文档与同一证据一致 | 逐行状态/计数可追溯；README/矩阵/台账/新报告齐备；按路径提交推送 | compat/README.md、v8/README.md、三份review工件 | W3有效fresh证据 | M |

W1/W2的内部编码先后可交错，但不可留下已提交的结果schema/调用方不一致。W3自检用临时假子进程、不访问数据库；W4仅文档变化无需机械重复整套测试，见§9的源hash复核条件。

## 4. W1：必跑 fake 与可选真实 smoke

### 4.1 接口与控制流

拟接口（只在测试模块，不新增生产provider类型）：

- `test_fake_provider() -> None`：独立运行与登记fake结果。
- `test_real_provider_smoke(conn, *, requested: bool) -> SmokeOutcome`：小型不可变测试结果，state∈passed/failed/not_run，reason∈none/not_requested/credentials_absent/provider_failure。
- `main(argv=None) -> int`：解析 `--real-provider-smoke` 与 `--report-json <path>`；无smoke flag默认不live。复用原DB合同测试顺序，在 reporter 前无条件运行fake；smoke明确登记结果后再汇总。

`main()` 入口重置（审查F5）：`RESULTS = {}`、`not_run_reasons = {}`，`EXTERNAL_BLOCKED` **重建为初始六项固定集合**——不是空集（否则报告器allowlist校验拒收合法来源）、不是上一轮残留（否则动态注入项泄漏到下次运行）；同进程多次调用不得遗留上一轮passed。报告器的EXTERNAL_BLOCKED是允许原因全集，测试模块的六项是当前host事实集，两者职责不同，不把全集自动加入每次报告。`test_fake_provider()` 直接写 `RESULTS["c12-db-fake-suite"]`，由main统一在reporter前调用。

**`--report-json <path>` 固定接口（审查F1：W1实现、W3消费，W1/W2/W3共用此契约）**：

- 仅在 `build_report` 成功返回后写文件：内容为build_report完整dict（含 `report_schema_version` 与UTC时间戳），临时文件+rename原子写；stdout的render输出照旧打印，两者并存，runner的PASS行计数不受影响。
- `validate_results` 抛ReportError（拒收）时**不写该文件**：main exit 1，文件不存在即"报告未生成"，与产品断言失败同因，runner据此区分（§6.4）。
- 进程被杀/超时致文件缺失或截断：同上，不存在部分JSON被当有效报告消费的路径。
- 目标路径不可写等I/O错误按测试失败处理（exit 1），不得回退为只打印。

### 4.2 Fake 的通过条件

1. 调用两个独立 `FakeLLM` 实例，固定seed输入，比较完整返回对象。
2. 只有 check 成功后登记 `c12-db-fake-suite=passed`；失败立即raise，不预登记绿。
3. 保留原FakeLLM已覆盖行为，不把这个小断言描述为新增完整FakeTool/runtime对比；完整假工具gate仍由既有G6等负责。
4. 将当前fake断言从真实provider函数末尾移走，不留重复登记。

### 4.3 普通与显式 smoke 行为

| 请求 | 条件 | 行状态/reason | 脚本退出 |
|---|---|---|---|
| 普通G13 | 无凭据或父环境有凭据 | smoke=not_run/not_requested；fake独立实跑 | DB/fake/report测试均通过则0 |
| `--real-provider-smoke` | 缺凭据 | smoke=not_run/credentials_absent；不得调用generate | 2，表示显式目标未执行 |
| 显式smoke | 有凭据且三子例通过 | passed/none | 0（同时普通测试须通过） |
| 显式smoke | 已开始但协议/网络/断言失败 | failed/provider_failure | 1，失败不可吞掉 |

普通路径在决定requested=False之后不构造DeepSeekLLM，不检查或输出真实key内容。显式smoke保留原protocol shape、DB settlement/idempotency和uncertain-window测试，以及外部I/O前后connection idle断言；fake不再受它控制。显式调用flag不是本计划授权实际访问provider，J0验收永不传该flag执行真调用。

错误处理只为保存安全状态摘要，finally关闭连接后仍非零；不要用catch吞掉AssertionError/ReportError。真实响应/请求、Authorization、异常中的响应原文不能经check detail或traceback外泄到归档；可显示固定失败类别及安全定位信息，不打印完整provider对象。伪adapter模拟成功/失败/缺凭据测试代码分支，不宣称真实smoke已通过。

### 4.4 W1 验证

- 无凭据：fake实际调用次数=2，完整对象相等；result和reason齐备；普通G13 exit0。
- 哨兵凭据在场：普通路径仍不构造或调用真实adapter；用会抛错的替身/网络哨兵证明，不能用真实key“试一下”。
- fake返回不等：触发失败、fake结果不为passed。
- requested+无凭据：返回2、generate零调用、fake仍独立通过。
- 伪provider成功/抛错：各自登记passed/failed并保留正确退出；无真实网络。
- 连续两次main/test运行不复用上一轮结果或动态blocked原因。

## 5. W2：报告模型、兼容与判据

### 5.1 Catalog、输入和展示状态

新增 `Subcase.requirement` 闭合集 mandatory/optional_smoke，默认mandatory；**只有** `c12-db-real-provider-protocol` 为optional_smoke，不改其DB边界或implemented事实。其余catalog不因J0变implemented=True。

结果值扩为 passed/failed/partial/not_run；blocked仍只能由原SQL矩阵及既有allowlist计算。新增 `not_run_reasons: Mapping[str,str] | None = None` 参数传入validate/build_report，避免可变默认值。

| 状态 | 语义 |
|---|---|
| passed | 子例实际执行且满足断言 |
| failed | 实际执行并失败 |
| partial | 实现/覆盖尚不完整，有gap去向 |
| not_run | 本次未执行，必须有闭合reason |
| blocked（输出） | 原capability矩阵或已允许external来源推导，调用者不得传入 |

reason闭合集：not_requested、credentials_absent、execution_interrupted、dependency_unavailable。前两者只允许optional smoke；必跑子例未运行永远不通关，不能用dependency_unavailable冒充capability blocked。必跑缺少结果仍按既有规则报MISSING_RESULT，不默默补not_run。未知结果ID、非法状态、reason缺失/多余/不配对均作为结构错误拒收。

保持展示优先序blocked→未实现partial→已实现result；但显式failed不能被展示优先序掩盖为“无失败”，结论需检查输入失败集合。未实现子例自报passed拒绝，不允许靠调用者绕catalog；需要合成全已实现状态来测试结论时，只在测试隔离的catalog fixture中构造，不修改实际catalog、不写入真实证据。

缺凭据不展开全部REAL，not_requested也不添加凭据blocked源。保留 `blocked:real-provider-credentials` 作为已有诊断来源兼容，但它不改变required行的参加义务；optional缺席用not_run描述，不加新的SQL capability值。

### 5.2 三个结论和 pinned 约束

新增 `conclusions` 下三个对象，均含 `passed: bool` 和稳定排序的 `blockers: list[str]`；布尔由行事实推导，不接受调用方直接指定。

1. **declared_support_surface_conformant**：报告结构有效；pinned必需身份/前置验证无未解析项（沿用现有“unresolved不得称contract passed”）；所有未被合法能力阻塞的mandatory行passed；UNSUPPORTED强制负向passed；无显式失败、无unmapped_failed_fixtures。合法blocked可保留，仅说明已声明支持面符合，不说明完整目标。
2. **minimal_dual_loop_passed**：最小turn子例为真实passed、未被blocked、real_loop_available=True、非Native-only证据，并无该fixture未映射失败。J0没有该证据，正常结果false。此结论只描述最小实验，不代表其他fixture通过。
3. **full_target_achieved**：前两项true、pinned无未解析、所有mandatory行passed、**无mandatory blocked/partial/not_run/failed**、无unmapped失败，optional smoke未运行不影响它。optional若本次实际执行失败仍保留失败并使该次总目标false，不能藏起来当缺席。

这比“合法blocked也能完整目标绿”更保守，避免把降级符合和全面对比混为一谈。unsupported但负向通过可令支持面符合；切换正向仍blocked，所以完整目标false。J0脚本exit0与三个结论均false可以同时成立：测试验证了诚实的未完成报告。

### 5.3 字段兼容策略（已确认）

- 新增 `report_schema_version=2`、`conclusions`、row.requirement/row.not_run_reason；counts保留四键并增加not_run。
- 保留rows/counts/capability_matrix/external_blocked/pinned_unresolved/unmapped_failed_fixtures/compat_only_excluded_from_portable/note原字段名。
- `compat_contract_passed` 保持False，保留“明确终签尚未发生”的原语义；J0不偷偷建立自动签署入口。
- `compat_contract_passable` 改为full_target_achieved.passed，明确是新版本的严格可签条件；旧字段不是三个结论的替代品。optional分类和新判据使语义不完全等同于旧公式，不能宣称所有输入都仅False方向变化。**别名非单调边界（审查F6）**：旧公式要求blocked==0（含optional行），新full_target只要求无**mandatory** blocked——若optional smoke行恰被矩阵blocked且其余条件满足，新值可比旧值更宽松；当前不触发（dual_loop恒false→full_target恒false），但别名赋值必须伴随 `report_schema_version==2` 断言，防止未来消费者按旧语义解读。
- `--report-json` 写出的即build_report dict本体，无第二schema；安全边界由"报告内容本身不含secret"保证，不做字段裁剪。
- render保留旧行/原状态拼写，新增not_run标记、role/reason和三结论；说明脚本通过≠P0C完成。不把passed别名从恒False悄悄变成自动True。

### 5.4 拒收标识与顺序

继续使用一个 `ReportError` 类，增加 `code` 属性，保留可读message，不建六个异常子类。六主code：

| 规则 | code |
|---|---|
| 非allowlist外部blocked来源 | INVALID_BLOCK_SOURCE |
| implemented且非blocked的必跑结果缺失 | MISSING_RESULT |
| Native结果冒充compat | NATIVE_EVIDENCE_AS_COMPAT |
| blocked REAL自报passed | BLOCKED_REAL_MARKED_PASSED |
| REAL自报passed但无真实loop | REAL_PASS_WITHOUT_LOOP |
| UNSUPPORTED强制负向未passed | MANDATORY_NEGATIVE_NOT_PASSED |

辅助结构code：INVALID_RESULT_ID、INVALID_RESULT_STATE、INVALID_NOT_RUN_REASON、UNIMPLEMENTED_MARKED_PASSED；catalog重复ID/缺clause亦须确定拒因。外部blocked合法性与结果结构先校验，之后缺项→Native来源→REAL降级→REAL无loop→强制负向；表内编号是规范规则分类，不是必须照编号执行的优先序。测试双重无效输入锁定顺序，不能依赖异常message模糊包含。

**`not_run` 集中决策矩阵（审查F2；校验位置固定：非法值检查之后、fail-class 2缺项检查之前）**：

| requirement | result | reason | 行为 |
|---|---|---|---|
| mandatory | 缺失 | — | MISSING_RESULT（既有） |
| mandatory | not_run | not_requested / credentials_absent | INVALID_NOT_RUN_REASON（前两reason只允许optional smoke） |
| mandatory | not_run | execution_interrupted / dependency_unavailable | 允许，但三结论必false |
| optional_smoke | not_run | not_requested / credentials_absent | 允许，不影响keyless支持面与full_target |
| optional_smoke | not_run | execution_interrupted / dependency_unavailable | 允许，结论同上 |
| 任意 | not_run | 缺失/未知值 | INVALID_NOT_RUN_REASON |
| 任意 | 非not_run | — | 残留该子例reason条目即多余reason，拒收 |

注意mandatory+not_run在results里**有值**，不会落入MISSING_RESULT的"缺失"分支——第二行是独立新检查，不能靠既有runnable集合逻辑顺带覆盖。

### 5.5 独立验证向量

构造完整有效基底：非blocked已实现行齐备、optional not_run+reason、强制负向passed、未实现行保留gap；matrix使用真实SQL结果，unit fixture可提供已记录的相同形状。每个负向只破坏一项，核准确code：

1. 加未知external source→INVALID_BLOCK_SOURCE。
2. 删除c16-db-unmapped-audit→MISSING_RESULT。
3. 将passed DB行加入native_evidence_only→NATIVE_EVIDENCE_AS_COMPAT。
4. 选blocked REAL行填passed，real_loop_available=True且其他输入完整→BLOCKED_REAL_MARKED_PASSED。
5. sync+supported、**精确移除 `blocked:all-real-io-subcases`（保留其余五项外部原因）**，REAL填passed而real_loop_available=False→REAL_PASS_WITHOUT_LOOP；不得被class4抢先。当前测试因EXTERNAL_BLOCKED恒含该项而实际触发FC4（审查F3指出的假阳性），本向量即其修复——不移除该项此向量永远测不到FC5。
6. sync+unsupported、负向**提供failed**（不是删除）→MANDATORY_NEGATIVE_NOT_PASSED；另测删除时MISSING_RESULT，以免混淆。

另测：非法results blocked；未知ID；not_run无reason/必跑用not_requested；未实现passed；mandatory partial/not_run/failed分别使结论false；optional not_run仍不变成passed；unresolved阻断contract；unmapped失败阻断；最小双looppassed不自动使支持面/完整目标passed；unsupported+负向通过只允许支持面符合；render五状态与兼容字段。

正常报告与“fx-unmapped-demo”负向报告分开，后者必须显示阻断结论，不能把故意失败fixture塞进正式J0证据。合成全绿catalog测试只验证公式，明确标test-only，不把它当实施结果。

## 6. W3：机器清单、执行与证据

### 6.1 文件与接口

拟新增：

- `v8/regression/v8-gates.json`：版本化累计清单。
- `v8/regression/run_baseline.py`：只服务V8的同步runner。
- `v8/regression/test_baseline_runner.py`：独立脚本自检，标准库临时目录/假子进程，无数据库。
- `v8/compat/evidence/j0/<run-id>.json`：运行后生成的安全机器记录。
- `docs/reviews/v8-j0-keyless-baseline-2026-09-17.md`：从选定final JSON整理的人读报告。

`python -m py_compile`等结构检查不替代runner自检。runner与自检不是新产品stage，没有setup_db，不修改load.py。

### 6.2 Manifest固定内容

对象字段：schema_version=1、suite_id=v8-cumulative-keyless、entries数组。每项 gate_id、argv数组、database_group（实际测试DB或null）、required=true；可记录stage用于审计但不由runner负责加载SQL。禁止shell拼接和任意命令，生产清单argv严格为 `uv run python <主仓v8路径/test_*.py>`，不允许live flag。

以下路径统一前缀 `v8/`、命令统一前缀 `uv run python`，顺序沿README当前运行块；数据库名除G1外均为 `agent_v8_<组>`：

| 序 | gate_id | 脚本 | DB组 |
|---|---|---|---|
| 1 | G1 | canonical/test_canonical.py | null |
| 2 | G2 | schema/test_schema.py | schema |
| 3 | G3 | events/test_events.py | events |
| 4 | G4 | effect/test_effect.py | effect |
| 5 | G5 | loop/test_loop.py | loop |
| 6 | G6 | tools/test_tools.py | tools |
| 7 | G7a | retry/test_retry.py | retry |
| 8 | G7b | retry/test_takeover.py | retry |
| 9 | G7c | repair/test_repair.py | repair |
| 10 | G8a | cancel/test_cancel.py | cancel |
| 11 | G8b | cancel/test_closure.py | cancel |
| 12 | G9a | stream/test_stream.py | stream |
| 13 | G10 | grant/test_grant.py | grant |
| 14 | G11 | plugin/test_plugin.py | plugin |
| 15 | G12 | gates/test_gates.py | gates |
| 16 | G13 | compat/test_compat.py | compat |
| 17 | G14 | concurrency/test_concurrency.py | concurrency |
| 18 | G9b | stream/test_observation.py | stream |
| 19 | G16 | audit/test_audit.py | audit |
| 20 | G17 | compact/test_compact.py | compact |
| 21 | G15 | drain/test_drain.py | drain |
| 22 | G18 | reconcile/test_reconcile.py | reconcile |
| 23 | G19a | assemble/test_assemble.py | assemble |
| 24 | G19b | closeout/test_closeout.py | closeout |

runtime数量从清单推导，不在runner写死24；J0验收核对以上精确集合/顺序。校验unique gate_id/脚本、文件存在、resolve后无symlink/`..`逃逸、不落另一个worktree；README展示与JSON作一致性核对。后续新增正式gate须同提交更新清单。

### 6.3 执行模型与状态

拟CLI：`--manifest <path>`（缺省上述清单）、`--timeout-seconds <正整数>`（默认240）。不实现--resume；每次启动都创建新run-id，既有run文件只读保留。输出路径固定为仓库证据目录，run-id唯一，原日志在私有临时目录；不提供任意外部shell命令配置。

1. 定位主仓根、校验清单及版本、准备source snapshot；在运行记录中明确“会DROP/CREATE测试库”。
2. 持本仓runner独占进程锁，阻止两个runner相互DROP；锁文件可在被忽略的`.pgdata/`下，不要求修改gitignore。操作者也不得同时手动跑共享库脚本；锁不声称能拦住未合作的手工命令。
3. child env复制父环境后删除DEEPSEEK_API_KEY/OPENAI_API_KEY/OPENAI_API_URI，并删除UV_ENV_FILE、设置UV_NO_ENV_FILE=1避免uv自动注入；不得读取.env或记录key值。OPENAI_MODEL不是secret，普通keyless路径不消费它作为授权条件。
4. 严格串行subprocess argv、cwd=主仓根；没有线程池/并行stage/自动retry。stdout/stderr流式写私有临时文件，不在内存积累整个suite日志。
5. 启动前记录running，退出后追加attempt结果并原子替换checkpoint；state=passed/failed/not_run，timeout按failed/timeout记录，真实退出码或signal另存。
6. 单脚本失败可以继续收集本轮后续脚本诊断，但全局结果必非零、禁止进入完成提交/下一里程碑。不会自动重跑红项；用户停止/runner异常/无法确认子进程已终止时停止后续。
7. 超时或SIGINT时终止并等待该测试进程组退出再释放锁，不能留子进程继续改库；未启动项标not_run/execution_interrupted。checkpoint持久，run标非准出。
8. 中断记录只用于定位已完成/失败/未启动项目，不续写为成功；操作者恢复执行只能新建run-id完整重跑。单脚本手工诊断可另跑，但不合并进旧run，不覆盖原结果。
9. final准出必须来自一个fresh、无中断、全部required exit0且结束source hash与开始一致的run。修复失败后新run-id完整重跑；不得跨run拼接绿色项。

runner退出：0=本次fresh有效全绿；1=failed/timeout/drift或未满足准出；2=清单/前置输入错误；中断用130。传入--resume等未支持参数按输入错误拒绝；任何历史checkpoint都不能被选为本次成功起点。

### 6.4 Source provenance 与证据模型

机器记录至少保存：schema_version/run_id、UTC起止、duration、manifest路径/hash、base_commit、dirty路径清单、Python/uv/PG/pgembed版本（安全查询不输出URI）、每entry argv/DB组/required/时间/exit/signal/state/reason、stdout/stderr SHA256、PASS行计数（仅观测）、总passed/failed/not_run、fresh/completed/interrupted标志、source_snapshot_digest、G13实际报告的安全结构与三个结论。

为了不只证明入口脚本而漏掉SQL/依赖，source snapshot覆盖本仓v8下实际Python/SQL/JSON源（排除证据输出）、server.py、pyproject.toml、uv.lock、manifest/runner、自检和compat reporter/固定manifest；记录每条相对路径及SHA256，排序后计算集合digest。不导入测试模块做枚举以免触发setup副作用。显式排除evidence/**、新生成review、docs纯展示、.git/**、.claude/worktrees/**、缓存/venv/PGDATA与其他worktree；缺失/新增文件也纳入前后漂移检测。

base_commit可能是修复前HEAD，因此同时记录working source hash，不伪称测试了尚未生成的commit。最终提交hash/push结果记实施交付消息，不为把commit hash写回其自身证据再造提交。清单不存自身hash；证据可存清单hash，证据自身不参与source snapshot；Markdown可以引用已封存JSON的hash，不要求JSON反指Markdown形成环。

安全归档：

- 原始stdout/stderr只在权限受限临时目录保留，不提交、不复制进Markdown；报告只写hash、退出码、计数及短安全摘要。
- 摘要去掉Authorization/Bearer、常见API key赋值、URI userinfo及本机绝对home路径；不能确认安全则省略摘要，仅保留错误类别/hash。
- 不记录环境值、.env、完整provider请求/响应、数据库连接串。使用哨兵secret测试清理，不读取真实secret作为测试材料。
- 每项完成原子checkpoint；run结束保留成功或失败JSON。失败记录不被成功run覆盖，选定final_run_id仅指向有效fresh全绿记录。
- G13用§4.1固定的 `--report-json <path>`；runner只能为G13自动附加该选项和本次run专属临时目标（run-id/新建目录约束结果归属，测试失败不能因旧文件读出上一轮passed），证据记录实际argv。stdout里故意打印的负向合成报告不能当真实报告解析。
- **报告缺失降级路径（审查F4）**：G13 exit 1（拒收、文件未生成）、被timeout杀死（文件缺失/截断）或JSON解析失败时，runner记 `g13_report: null` + 具体原因（missing/invalid/timeout），**不升级为runner前置错误（不exit 2）**——该run本就因G13非零而failed；证据中三个结论字段标 `unavailable` 而非false。解析前校验 `report_schema_version` 与本次run归属。

### 6.5 自检（不计入24产品gate）

`uv run python v8/regression/test_baseline_runner.py` 用临时假Python程序/注入子进程调用点验证，不调用真实setup_db或provider：

- 清单合法、重复ID/脚本、路径逃逸、live flag/任意命令拒绝；24集合与README一致。
- 执行顺序、最多一个子进程存活、第二runner拒绝、共享DB组记录准确。
- child三个凭据键及dotenv控制安全；parent环境不变，不序列化哨兵值。
- exit1/timeout/signal留下失败，后续诊断与停止规则准确；不会retry红项。
- 中断checkpoint保留、未启动项not_run、新run不复用旧结果、源漂移拒准出；传--resume拒绝。
- fresh全0准出、任一failed/not_run/drift不能准出；PASS数量再高也不覆盖exit1。
- source集合覆盖SQL改动且排除产物，原子写失败/损坏checkpoint不伪造可恢复成功。
- 摘要脱敏、凭据值不落JSON/Markdown、失败产物保留、G13 report文件归属、缺失/无效时记null+原因而非前置错误。

## 7. W4：文档更正与人读证据

### 7.1 逐文件更正

**`v8/compat/README.md`（拟新增）**：满足stage收尾README要求，说明keyless默认、显式smoke条件、五状态与三结论、G13和runner/自检命令、测试库重建警告、当前host/真实loop未完成范围。

**`v8/README.md`**：更新G13行、修复运行块末尾代码围栏、保留24直接脚本命令并指向JSON清单；加入runner入口。旧“缺凭据skip exit0”改为fake必跑/smoke未请求；真实provider曾有瞬时失败的历史可留在台账且标明不是keyless依据，不能以这条注记解释当前确定性漏结果。153/155不预填，使用本轮fresh证据实际计数。已知边界按机制与compat执行分列，源码已定位但能力未验证不写成“已pin”。

**Conformance矩阵**：重点#1/#2/#6/#8/#9/#14/#16，兼顾#12与G13计数：

| 行 | 可据已有gate更正的机制事实 | 必须保留的剩余面 |
|---|---|---|
| #1 | G19b attempt/heartbeat | 真实compat重试/日志映射 |
| #2 | G19b FORCE_JOB_TAKEOVER、G12/G14 fence与竞态 | compat生命周期/真实恢复证据 |
| #6 | G17 compact、G14/G17锁序探针 | 未覆盖的真实compat cancel/dispatch |
| #8 | generation双门、G14并发、强制接管已有 | compat fixture/host执行层 |
| #9 | G19a seam checkpoints | 必需hook timeout/error的runtime/compat测试 |
| #14 | G19a seam与G12双门 | 真实compat revoke×dispatch |
| #16 | heartbeat/compact/switch/reconcile数据库机制 | DSH pin/loop/真实I/O与完整compat套件 |
| #12 | fake无凭据必跑，smoke明确optional | 未跑live不能写passed；真实loop不同于provider HTTP smoke |

每项引用实际测试函数/本次结果；整体状态按剩余义务决定，不统一升绿。表头计数从JSON的观测计数取值；脚本未统一打印PASS时如实标统计口径/无法计数，不编造断言总数。

**偏差台账**：保留A82–A89历史，A87追加keyless默认/opt-in/not_run更正，A88追加状态/三结论/code及判据变化；B节已被G17–G19消解处划线并引用实际A项/Gate，不一律以“A121–A141”概括替代精确匹配。不声称测试编排修复消除了产品协议偏差。

### 7.2 新人读报告

`docs/reviews/v8-j0-keyless-baseline-2026-09-17.md` 至少包含base_commit/source digest、实际entry数量、全部命令/退出码/状态、fresh条件与总结果、G13 fake/smoke状态、三个P0C结论、未完成范围、所引用JSON相对路径与SHA256；从选定final JSON生成或据其整理，禁止粘贴原始日志。JSON若缺或hash不符则报告无效。

文档生成不能成为新的mandatory网络任务。更新纯文档后核source snapshot未变和展示一致性；若实际Python/SQL/manifest改了才必须重新fresh全套。

## 8. File-by-file impact

| 路径 | 内容/责任 |
|---|---|
| 本计划文件 | 规划交付，确认决策；不等于实施完成 |
| v8/compat/test_compat.py | fake/live拆分、CLI、状态清理/安全JSON、精确拒收和公式测试 |
| v8/compat/p0c_report.py | role/not_run/reason、三结论、兼容字段、ReportError.code、render |
| v8/regression/v8-gates.json | 当前24入口单一机器清单 |
| v8/regression/run_baseline.py | 串行/隔离/timeout/锁/checkpoint/诊断恢复/证据 |
| v8/regression/test_baseline_runner.py | 无数据库runner自检，不新增正式stage |
| v8/compat/README.md | 新增stage使用与验收说明 |
| v8/compat/evidence/j0/<run-id>.json | 实施时生成，不在规划轮造结果 |
| docs/reviews/v8-j0-keyless-baseline-2026-09-17.md | 实施时从final JSON产生 |
| v8/README.md | 运行入口与边界更新 |
| docs/reviews/v8-p0ab-conformance-matrix-2026-09-16.md | 计数/分层覆盖纠正 |
| docs/reviews/v8-p0ab-deviation-ledger-2026-09-16.md | 历史更正与未完成项保留 |

文件所有权串行：W1/W2共改test_compat，W3归档与W4文档都引用同一final run。不要派多个agent同时改README/矩阵/台账。新增目录是否需空__init__.py按现有独立脚本导入方式最小处理，不额外建包架构。

## 9. 实施顺序、命令与提交

以下为原批准执行顺序；2026-09-17 已依此实施，实际结果与唯一 run 见 J0 基线实跑报告。

1. 读取批准后的计划、检查git status、确认没有别的进程在跑这些测试库；锁定base_commit。
2. W1/W2一起实现；语法检查和无网络分支测试通过后运行：
   ```bash
   env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u UV_ENV_FILE \
     UV_NO_ENV_FILE=1 uv run python v8/compat/test_compat.py
   ```
3. W3清单与runner落地，自检：
   ```bash
   uv run python v8/regression/test_baseline_runner.py
   ```
4. 产品fresh suite：
   ```bash
   uv run python v8/regression/run_baseline.py --manifest v8/regression/v8-gates.json
   ```
   runner必须自行移除凭据，不能只依赖命令行外壳。红gate保留记录、修复根因，再新建run完整重跑；不得降断言或拼接24个不同历史run。
5. 以有效fresh JSON更新W4。校验JSON/schema/hash、README清单、stage README、矩阵/台账、文档链接及git diff --check。若被测源hash不变，不为文档改字或提交重复昂贵全套；若代码/SQL/清单变了，重新自检+fresh suite再更新证据。
6. AGENTS完成顺序不可颠倒：全绿→工件→逐路径暂存→复查→commit→push。拟提交摘要 `v8: establish keyless compat baseline reporting`。
   - `git status` 后按本计划实际修改路径逐项 `git add <path>`，禁`git add .`/`-A`。
   - 看暂存diff确认无.env/凭据/原日志、无无关v11/联合计划/P0C草案、DSH源码或prompt-exports。
   - `git commit -m ...`，不得跳hook；`git push origin main`，不得force。
   - push拒绝先fetch看差异，需要时安全rebase；若被测文件受上游改变必须重跑受影响验证，分歧无法安全处理时停问用户，禁reset --hard。
   - 提交hash/push结果写交付消息，不回填证据造成自引用提交循环。

### J0 准出清单

- [x] 无key与哨兵key场景fake真实执行且零live；显式smoke保持optional，未运行不伪绿。
- [x] 六拒收命中各自code；两维matrix/blocked来源不改；partial/not_run/unmapped/未解析项均正确阻断。
- [x] 三结论与legacy字段/render通过正负向测试；当前实际报告未声称双loop/P0C完成。
- [x] manifest24入口齐备，runner/自检通过，产品同一fresh run全部exit0且source无漂移。
- [x] 脱敏JSON/人读报告绑定同一run，日志不提交，optional未跑如实记录。
- [x] stage README、总README、Conformance矩阵、偏差台账一致；未把Native绿冒充compat绿。
- [ ] 只按实际J0路径提交、推送（最终状态见实施交付消息）；冻结正文/SQL/能力seed 已核对未变。

## 10. 取舍、风险与基线保留台账

### 10.1 取舍

- 独立fake函数优于把断言简单挪到凭据判断前：职责可单独验证，不再让fake结果受smoke退出控制。
- 显式opt-in优于仅runner删key：直接跑G13也不因开发机环境而产生账单；用户已在Mid-flow批准其CLI行为变化。
- 新not_run优于把未请求都写partial/blocked：区分未实现、未执行和capability，保留原因；代价是schema v2与render更新。
- 单ReportError+code优于六异常子类/仅匹配字符串：精准核拒因且改动局部。
- V8专用串行runner优于通用CI框架：共享DROP库是硬限制，清单足以组织回归；用户选定不做resume，用保留checkpoint＋fresh全跑替代续跑状态机，仍保留失败定位、不可覆写与完整准出验证。
- 安全摘要+hash优于提交完整日志；source前后hash优于“待提交证据写最终commit”的自指方案。

### 10.2 风险与处置

- 新状态/结论改变报告消费者：逐搜索build_report/compat_contract_*调用者，不扫其他worktree；同步测试/render，schema版本显式。
- blocked或unimplemented优先级可能掩盖失败：显式失败集合参与结论，不能仅数展示行。
- optional失败被忽略：未请求允许不阻塞，但本次实际失败不能改写成not_run。
- 多runner/手工脚本同时DROP：进程锁+串行操作约定；不能声称锁覆盖未知手工进程。
- 超时残留子进程：终止并wait整个测试进程组后才继续；无法确认即停止。
- 日志含secret：从输入隔离、默认禁live、受限临时日志到摘要脱敏多层防护；无法确认安全不提交摘要。
- source只hash入口漏SQL：扩大到实际v8源及依赖配置，产物排除，前后复核。
- 文档误升绿：每项用测试和scope交叉核对，保留J3/J7去向。

### 10.3 context_builder 基线覆盖与纠正记录

本节是精简的保留台账，供Phase6/7.5核对，不含原始工具输出。原export生成计划§1–§7均已阅读，临时export在核对完成前保留。

| 基线内容 | 本计划落点 | 处置 |
|---|---|---|
| Summary、现状2.1–2.6、因果/矩阵/凭据/共库/文档 | §1–2 | 保留，源码引用补齐 |
| 3.1独立fake、SmokeOutcome、flag/退出码、错误安全 | §4 | 保留，补main重复调用清理与哨兵测试 |
| 3.2 role/五状态/reason/六拒收/code/三结论/兼容/render | §5 | 保留；mutable默认参数改None；完整目标无mandatory blocked，支持面与完整分开；passed恒False已由用户确认；unresolved不得称contract passed |
| 3.3 manifest、串行、checkpoint/resume、fresh、计数、脱敏、provenance、自检 | §6 | 除resume外保留；用户明确删除resume，以只读失败/中断checkpoint＋新run全跑代替，覆盖中断诊断及红结果不可变；补SQL依赖hash、源漂移、进程组timeout/锁与安全report文件；自检不是第25产品gate |
| 3.4 README/矩阵逐行/台账历史/新人读报告 | §7 | 保留；不删除旧真实provider历史，区分本轮keyless；新增stage README遵循AGENTS |
| §4逐文件影响 | §8 | 保留并列明自检/README新文件，不修改SQL/runtime/manifest能力 |
| §5 tradeoffs/risks | §10 | 保留并加强错判和进程残留边界 |
| §6实现顺序/命令/提交 | §9 | 保留；纯文档更新以source hash核验替代无条件重复全套，避免“证据变更→再测→再变更”循环；代码变化仍重跑 |
| §7待决 | §11 | 已按用户三项明确选择落实；单ReportError+code是有依据的局部设计，无剩余材料歧义 |

纠正有据：基线把两个legacy布尔改为新alias却称“只收紧、不可能False→True”，与原passed恒False冲突；本草案保留passed终签语义并显式版本化passable。基线full_target容许mandatory blocked会把降级目标与完整目标混同，按联合计划J8的双结论分开。新增not_run仍是报告层，不修改v8命令outcome枚举。

## 11. 已确认决策与剩余问题

2026-09-17 Mid-flow用户逐项选择：

1. **默认keyless**：普通G13即使机器有key也不真实调用；显式--real-provider-smoke才检查前置，缺key exit2。
2. **保留终签区分**：schema v2新增conclusions；旧passed保持False，passable引用严格完整目标，不自动终签。
3. **不做resume**：逐项保存失败/中断证据，恢复后只能另起完整run，删除续跑状态机。

没有遗留的材料性开放问题。2026-09-17设计审查（`docs/reviews/v8-j0-keyless-baseline-plan-critique-2026-09-17.md`）结论0阻断：F1/F2两条P1（--report-json接口固定、not_run集中决策矩阵）与F3–F6四条P2已作为文字补丁并入§3/§4.1/§5.3/§5.4/§5.5/§6.4/§6.5，无未落地的审查建议。实际测试计数、运行时间、环境版本与最终commit是实施时产生的证据，不是未决设计。发现共享产品缺陷或spec矛盾时按范围边界停止另立项，不能在J0顺手扩展。

## 12. References

- `AGENTS.md:9–66,70–76`：里程碑、提交、测试和外部IO约束。
- `docs/plans/v8-dsh-v10-joint-readiness-plan-2026-09-17.md:68–76`：J0唯一上位范围。
- `docs/designs/v8-dev.md:786–811,823–825`：capability矩阵、报告与P0C，不修改。
- `v8/compat/test_compat.py:89–93,1076–1084,1181–1319`：失败链、main和现有拒收测试。
- `v8/compat/p0c_report.py:63–90,179–184,258–431`：allowlist、catalog、判据、render。
- `v8/loop/runtime.py:258–306`；`v8/closeout/test_closeout.py:704–746`：凭据和拒调用先例。
- `v8/compat/setup_db.py:30–49`；`v8/load.py`：重建库与加载权威。
- `v8/README.md:34–59`；覆盖矩阵；偏差台账A87/A88及B节：收尾事实来源。
