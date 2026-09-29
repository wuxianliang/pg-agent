# v15 发布驱动源码（force-add demo_v15）: Plan

## Goal

把 gitignored 的 `demo_v15/` 8 个源文件（2291 行）force-add 入库并同步修正所有因发布而变陈旧的文书句子，使 demo 成为检出该分支的任何 clone 上零 key、零成本可复跑的仓库资产（「任何 clone 含 main」由紧随其后的合并里程碑完成）；十道 v15 gate 保持全绿，reports/ 与 `__pycache__/` 保持不入库。

## Background

### 发布影响面（探查实证，file:line）

**将变假话的句子（发布提交必须同步修正）**：
- `AGENTS.md:75`「该目录在 `.gitignore`」——入库后目录不再整体被忽略（同句其余内容经代码核对仍为真：`drive.py:468,473,233-234`）。
- `docs/plans/v15-demo-tail-delegation-plan-2026-09-29.md` 8 处：`:28`（「不入库的 headless 驱动」「跟踪提交只有…」）、`:88`（「本计划不 git add -f」）、`:470`（gitignore 目的）、`:532/:538/:579`（M1/M2 的 git status 自检与「不把 demo_v15/** 放进 git add」）、`:590`（「gitignored」标注）、`:523`（风险缓解理由的一半）。历史计划文档按仓库惯例不改正文——以文末追加「发布后记」节处理，不重写已执行里程碑的记录。
- `docs/reviews/v15-demo-tail-delegation-plan-critique-2026-09-29.md:29`「stays gitignored」——历史评审记录，不改正文。
- `docs/investigations/v15-next-steps-survey-2026-09-29.md:11/:20/:27`——选项 A 变「已执行」，回填状态。
- `demo_v15/README.md:1`「The directory is gitignored」——需改写。

**仍然为真的**：`v15/README.md:26`、`v15/provider/README.md:24`（入口指向）、矩阵 `:260`（「gitignored demo_v15/reports/（不入库）」——reports 仍不入库）、demo README L20 末句。

### Git 交互机制（check-ignore 实证）

- 目录级 ignore 对已跟踪文件失效（`demo_v13` 先例：`.gitignore:33` + `git ls-files demo_v13` = 3 文件，README 未被忽略而 `demo_v13/new.py` 仍被忽略）。
- 发布后：8 文件成为 tracked；`demo_v15/reports/`、`__pycache__/`（另有 `.gitignore:2` 双保险）**继续被忽略**；**新增文件继续被忽略**——未来每个新文件都需 `git add -f`（维护陷阱，README 须警示）。
- **密钥自检盲区**：`git status` 不列 `demo_v15/` 下未跟踪文件——原「status 确认无 .env」自检对该目录静默失效；发布后的密钥自检须改为 `git ls-files demo_v15` 白名单比对（恰好 8 文件）。

### demo_v13 反面先例（发布完整性的教训）

`demo_v13/memdrive_phase2.py:25-26` import `demo_v13.deepseek`/`demo_v13.settings`——两模块**从未入库、磁盘也不存在**，新 clone 上该脚本直接 ImportError，本地工作区因文件仍在磁盘而看不出来。**本计划的 8 文件集按依赖表是闭合的**（db→task；drive→db/assert_e2e/report/script/task；assert_e2e→v15.protocol（已跟踪）；test_harness→db/drive/script/task/assert_e2e；report/task/script 纯 stdlib），但计划必须含**机械 import 闭包验证**（如 pyflakes/AST 扫描 8 文件的顶层 import，证明无 demo_v15 内其他依赖），不能靠目测。

### 安全与就绪度（实证）

- 无硬编码 key（key 只从环境读，`drive.py:73-74`）；`report.py:171-174` redact 机制在位；`reports/` 实测零 key 命中；仓库根无 `.env`；无 `/Users/` 绝对路径。
- README 除 L1 外全部适合公开（命令块/key 纪律/退出码/留库警告）；`source ~/.zshrc` 是本机习惯，可保留但注明适用场景。
- 干净集群自足：`db.py:156-176` 幂等建角色（不依赖先跑过 v15 gate）、`load_stage(server, db, "provider")` 十文件全跟踪、`--drop-only` 幂等（库不存在也返回 0）、fake 路径零 key 零网络。**约束**：只能 `python demo_v15/db.py` 直跑（`db.py:13,20` 的 sys.path 机制），`python -m` 不行——README 已隐含，发布版须明示。
- `test_harness.py` 命名匹配 `test_*.py` 通配：当前无 CI、无 pytest 配置（pyproject 无 `[tool.pytest.ini_options]`，venv 无 pytest）、v15 gate 无 rglob（全仓六处 rglob——`v7/tests`×2、`v8/regression`、`v13`×3——无一触及 `demo_v15/` 或收集仓库根 `test_*.py`；评审实证）——**今天安全**；陷阱是未来有人加 pytest 配置或把文件移进 `v15/`。README 加一句命名警示即可，不改名（改名破坏 M0-M3 的历史记录与 README 引用链）。

### 提交先例

`da4663e`：3 文件 735 行 force-add，单行提交信息 `v13: fix demo candidates probe to use anchor OR tinql`（版本前缀 + 祈使句，无 body）。

# 1. Summary

**执行时序（用户裁决 2026-09-29）**：本计划在 **B（更深链 demo）完成之后**执行——B 会改 `task.py`/`script.py`/`assert_e2e.py`/`test_harness.py` 等多个驱动文件，改完一次发布，避免发布后立刻又一批驱动改动。因此本计划中的一切「基线数字」（2291/935/各 sha256）都是 **B 完成后重测的就地基线**，不是本文写作时的快照；文中出现的具体数字只是当前参考值，执行时以重测为准。发布推送后**立即起草「v15 线并入 main」的合并计划**（独立里程碑，不在本计划内）。执行发布前先单独处理 `uv.lock` 脏行（见 §3.8）。

在当前 v15 分支上做**一次原子提交**：把本 worktree 磁盘上的 `demo_v15/` 8 个源文件（M2 在此构建并产出 2026-09-29 真跑成功的那份字节）经内容闸与 AST 闭包闸之后 `git add -f` 入库，并在同一提交里改掉发布后会变成假话的文书。`/demo_v15/` 忽略行保留，因此 `reports/`、`__pycache__/` 和此后新增文件继续被忽略。十道 v15 gate 不重跑（diff 里没有 `v15/` 的 py/sql）；提交前在本 worktree 实跑 fake、harness、keyless，提交后用脱离 HEAD 的 worktree 再跑一遍，证明入库字节本身能在零 key 下复跑。本分支不是 `main`，所以只快进推送 `rp/agent/3e700836-agent`，不把这个提交推进 `main`。

# 2. Current-state analysis

## 2.1 文件已在本 worktree（主 agent 实证 2026-09-29）

- 本 worktree：`rp-agent-3e700836-agent`，分支 `rp/agent/3e700836-agent`，HEAD `3ab34aa`（实证 `git rev-parse HEAD`）。
- `demo_v15/` **就在这块磁盘上**：8 个源文件齐全（`ls` 实证）；本文写作时合计 2291 行、`assert_e2e.py` 935 行（B 完成后会变，执行时重测为基线），`reports/` 内含 M2 真跑报告（`e2e_report-20260929T142831Z.md` 等 14 份）。这批字节就是产出 `tail_ok relay_ok` 真跑证据的那份——**无需从任何其他检出复制**（O1 轨道「从主检出 cp」的前提是错的，已被实证推翻）。
- 工作区仅 ` M uv.lock` 一条未暂存改动。发布提交前它保持未暂存。
- 完整性锚点因此从「跨检出 sha256 对拷」简化为**就地基线**：内容闸通过后记录 8 文件 sha256 进 Run record；此后只有 `demo_v15/README.md` 允许改，提交前复核其余 7 个 `.py` 的 sha256 仍等于基线（防中途手改）。

## 2.2 忽略规则对已跟踪文件失效

直接观察 `.gitignore:2` 为 `__pycache__/`，`:31-34` 为 v13 注释、`/v13/demo/`、`/demo_v13/`、`/demo_v15/`。底稿已记录 `demo_v13` 先例：目录忽略仍在，已跟踪文件继续受跟踪，目录里的新文件仍被忽略。发布后的目标状态与此相同，对象换成 8 个路径。

因此：

- 删掉 `/demo_v15/` 会让 `reports/` 与新文件出现在 `git status` 里。该行保留。
- `git status` 不列出该目录下未跟踪文件。密钥自检不能再靠「status 里没有 `.env`」。
- `git check-ignore` 在 `git add -f` 之后仍可能对这 8 个路径报忽略规则。跟踪与否只以 `git ls-files -- demo_v15` 为准。

## 2.3 八文件闭包（底稿实证，执行时以 AST 为准）

底稿与调查 §A 给出的集合（直接观察调查表行与「干什么」段；行号约在 `docs/investigations/v15-next-steps-survey-2026-09-29.md:11` 与其后的 A 节）：

`demo_v15/{README.md, db.py, task.py, script.py, drive.py, assert_e2e.py, report.py, test_harness.py}`，合计 2291 行；`assert_e2e.py` 935 行。不入库：`reports/`、`__pycache__/`、任何 `.env`。

import 关系（探查实证 + AST 坐实，执行时以 AST 为准）：

| 模块 | 顶层依赖 |
|---|---|
| `report` / `task` | 仅 stdlib |
| `script` | 兄弟 `task`（`BIND_NAME`、`child_payload`）；其余 stdlib |
| `db` | `task`，以及 `server`、`v15.load`、`v15.provider.support` |
| `drive` | `db`、`assert_e2e`、`report`、`script`、`task`、`server`（get_server）、`v15.protocol.render_prompt`（render_system）、`v15.provider.support`（FLASH_SCOPE）、`v15.worker`；`v15.provider.deepseek` 只出现在函数体内（实证 AST） |
| `assert_e2e` | `v15.protocol`（`split_sql` / `classify_statement` 所在模块） |
| `test_harness` | `db`、`drive`、`script`、`task`、`assert_e2e` |

这些仓库模块都已跟踪，且与驱动的调用点一致：

- `load_stage` 走 `SQL_LOAD_ORDER` 的十个文件（直接观察 `v15/load.py:17-28`）。缺文件抛 `FileNotFoundError`，psql 失败抛 `RuntimeError`（直接观察同文件 `load_stage` 函数体）。
- `open_invoke` 把 inputs 写成 `'[]'::jsonb`，默认 scope 是 fake 的 `SEED_SCOPE`（直接观察 `v15/provider/support.py` 中 `open_invoke` 的 SQL 与签名；三个常量在 `support.py:8-10`：`SEED_SCOPE` `…b1`、`FLASH_PROFILE` `…a2`、`FLASH_SCOPE` `…b2`）。demo 因此自带 `open_root`，本里程碑不改 `support.py`。
- `DeepSeekProvider` 在 key 缺省时读 `DEEPSEEK_API_KEY` 再读 `OPENAI_API_KEY`，`base_url` 缺省时会读 `OPENAI_API_URI`（直接观察 `deepseek.py` 的 `__init__`；allowlist 与默认 base 在 `deepseek.py:19-20`）。驱动 real 分支按 demo 计划裁决 13 显式传入官方 base。发布不改这条路径。
- 反面先例是 `da4663e` 的 `demo_v13/memdrive_phase2.py`：顶层 import 了从未入库的 `demo_v13.deepseek` / `demo_v13.settings`。本地磁盘仍有文件时看不出来。闭包闸失败就停，本里程碑不改 7 个 `.py` 去「补上」缺的模块。

脚本布局：`smoke.py` 在 `v15/provider/` 下，用 `parent.parent.parent` 把仓库根插入 `sys.path`（直接观察 `v15/provider/smoke.py:11`）。`db.py` 在 `demo_v15/` 下，底稿记录是 `parent.parent`（`db.py:13,20`，执行时打开核对）。推断：`python demo_v15/db.py` 时 `sys.path[0]` 是脚本目录，兄弟模块 `task`、`db` 因此可 import；`python -m demo_v15.db` 不是这个布局。README 要写明只支持前一种。

## 2.4 哪些句子会假，哪些仍然为真

会过时的（正文处理方式在 §3.5，这里只定事实）：

| 锚 | 观察 | 发布后 |
|---|---|---|
| `AGENTS.md:73-75` | 直接观察。第 75 行含「该目录在 `.gitignore`。」同条其余内容：两个入口、都不是 gate、调用时不得有打开事务、无 key 则 `credentials_absent` / 退出码 2、缺省 `fake` | 只有这一小句为假 |
| demo 计划内 `gitignor` / `不入库` / `git add -f` / `demo_v15/**` 诸句 | 本会话对计划全文数行，与底稿点名的 8 处对齐，见 §3.5.4。执行时用锚句复读 | 历史步骤仍真；现在时「目录未跟踪」为假 |
| 调查 §A | 直接观察表行 A（约 `:11`）、「干什么」、「预期效果」第三条仍把 A 写成待做，并预言「gitignore 例外」与「跟踪策略节补 Run record」 | 那两条预言不按原话执行 |
| `demo_v15/README.md:3` | 直接观察：含 “The directory is gitignored”（第 3 行，非第 1 行） | 改为「8 文件已跟踪、忽略行仍在」 |
| 矩阵 `## Demo evidence（不是 gate）` 落点单元格 | 直接观察，唯一单元格原文 `gitignored demo_v15/reports/（不入库）` | reports 仍不入库；单元格要分开写驱动已入库 |
| 台账 `## Demo` | 直接观察末节：不新增 V15-D，不改渲染器 / 切分器 / worker / provider | 行为不变；补一句源码已入库 |
| 评审 `:29` | 直接观察 `docs/reviews/v15-demo-tail-delegation-plan-critique-2026-09-29.md:29` 含 “and so it stays gitignored” | 历史评审，不改 |

仍然为真、本里程碑不改：

- `v15/README.md:26`：demo 不是 gate；库名避开 `agent_v15_`；留下 `agent_demo_v15` 会使下一次 gate 在 `DROP ROLE v15_owner` 失败，须先 `demo_v15/db.py --drop-only`。
- `v15/provider/README.md:24`：正规全链入口是 `demo_v15/drive.py`，库名 `agent_demo_v15`，base 钉死 `https://api.deepseek.com/v1`，示例租约 `"240 seconds"`，恰好 180s 过不了发起前检查。发布后这句指向已跟踪脚本，更真。
- 台账 D27–D30 的计价、无幂等、思考文本、高峰窗口。发布不碰 `pricing.py`。
- demo 计划 Run record：2026-09-29，`NOTE_V1`，`tail_ok relay_ok`，`calls_used=3`，`$0.001257786`，真实全链预算 1/3，note 修改 0 次。本里程碑不再打真实模型。

库名链（直接观察 `v15/provider/setup_db.py` 的 `_drop_databases` / `_drop_roles`）：`starts_with(datname, 'agent_v15_')` 删不掉 `agent_demo_v15` 与 `agent_demo_v15_harness`；这两个库里只要还有 `v15_owner` 拥有的对象，随后的 `DROP ROLE v15_owner` 会失败，而且发生在 gate 库已经被删掉之后。证明命令的 `finally` 必须 drop 这两个名字。

## 2.5 可复用与禁止触碰

复用：demo 计划已落地的 8 个文件、`load_stage(..., "provider")`、`seed_flash_profile`、`run_until_quiescent`、keyless 退出码约定（`smoke.py` 的无 key → 2，已开打后的失败不降级为 2）。不新增 Python 模块，不把 AST 扫描脚本留在仓库里。

就位与身份核验（§3.2）是唯一闸口：文件已在磁盘上，先基线后 add。

# 3. Design

## 3.1 裁决

| # | 决定 | 理由 |
|---|---|---|
| 1 | demo 计划 8 处及复读扫到的同类句子：正文不改，文末追加「发布后记」 | M0–M3 是按「不入库」执行完的历史；改句子会把记录和当时的提交拆开 |
| 2 | 调查 §A 就地最小回填：表行 A、干什么、预期效果第三条、建议句、路线图里的 A。评审 critique 不改 | 调查是排期活文档；critique:29 是评审记录 |
| 3 | README 补两条警示：新文件要 `git add -f`；`test_harness.py` 不改名、不移入 `v15/`、不加 pytest 收集 | 两条都是已实证的坑；改名会打断 M0–M3 与 README 的引用 |
| 4 | 文件已在本 worktree（M2 产物），就地发布、就地 sha256 基线；不跨检出复制，不在其他分支上提交 | 父提交必须带齐 `v15/`；这批字节正是真跑成功的字节 |
| 5 | 一次原子提交，15 条路径 | force-add 与文书修正拆开，中间态会留下「已入库但 AGENTS 仍说整目录被忽略」 |
| 6 | 闭包闸是一次性 stdlib `ast` 扫描，不入库。pyflakes 不安装、不当门槛 | 不增加依赖；失败即停，不改 `.py` |
| 7 | 不重跑十道 gate，提交说明不写 gate 通过。必须实跑 fake、harness、显式 keyless | diff 无 `v15/` py/sql，与 demo 计划 M1/M3 相同；真正的回归是 8 文件是否自足 |
| 8 | 密钥三层：`git ls-files` 白名单、工作区与 `--cached` diff 的形状扫描、`git status --short` 路径集合。`uv.lock` 保持未暂存 | `git status` 对该目录的未跟踪文件是盲的 |
| 9 | `.gitignore` 只在 `/demo_v15/` 上方加注释，不删该行 | 删行会把 reports 与新文件暴露出来 |
| 10 | README 保留 `source ~/.zshrc`，并写明只用于「非交互 shell 且尚未 export key」 | 删掉会让 real 路径的无 key 被当成驱动故障。本里程碑不跑 real |
| 11 | 池 32 次 / `$2`、`max_io_attempts=2`、D28/D30 原句保留。授权的计费次数是 0 | 发布不改驱动行为 |
| 12 | 矩阵只改 Demo evidence 那一格落点措辞，不新增行、不打 ✅。台账 `## Demo` 补一句，不新增 V15-D | 发布不改变被断言的行为 |
| 13 | 本计划文件目前未跟踪，与 8 个源文件同一提交入库。提交说明一行：`v15: publish the tail-delegation demo driver` | 树里写不进「自己的 hash」。标识用这句说明，不用第二次提交去补 hash |
| 14 | 推送 `origin rp/agent/3e700836-agent`，且仅快进。禁止 `git push origin main`、禁止 `HEAD:main`、禁止 rebase 到 `b7b5f88`、禁止 force | 与 `origin/main` 不是快进关系；把整段 v15 历史并进 main 是另一个里程碑 |

底稿三个 Open Questions 分别落在裁决 1、2、3。本节之后不再保留悬空问题列表。

## 3.2 就位与身份核验

第 1 步全部成立才继续。有一条不成立就停，此时还没有任何文书改动。

| 检查 | 必须看到 |
|---|---|
| `git rev-parse --show-toplevel` | 路径含 `rp-agent-3e700836-agent` |
| `git rev-parse --abbrev-ref HEAD` | `rp/agent/3e700836-agent` |
| `git rev-parse HEAD` | 等于 `git rev-parse --verify 3ab34aa^{commit}`（若其后又有提交，以实际 HEAD 重核：发布提交的父必须带齐十文件 `v15/` 运行时与 demo 依赖的全部 tracked 文件） |
| `git status --short` | 只允许 ` M uv.lock` 与 `?? docs/plans/v15-publish-demo-driver-plan-2026-09-29.md` |
| `ls demo_v15/{...同 8 路径}` | 8 文件全部存在（B 之后若新增驱动文件，先回到本计划扩白名单再继续）；`wc -l` 记录合计与各文件行数进 Run record（不再断言 2291/935——那是写作时参考值） |

就位后立刻对 8 路径做 `shasum -a 256` 记入 Run record 草稿——这是**执行日基线**（B 后的字节，不是本文写作时的字节）。此后只有 `demo_v15/README.md` 允许再改；每次 `git add` 之前，其余 7 个 `.py` 的 sha256 仍须等于基线，不同则停。**B 敏感联动**：若 B 在 `demo_v15/` 新增第 9 个驱动文件，白名单扩为 9+，且五处写死「8 文件」的文案（AGENTS 替换句、gitignore 注释、README 替换句、调查回填、台账 Demo 节）同步改数——步骤 3 的枚举差分是检测点。

## 3.3 发布前内容闸

在 AST 与实跑之前做。任一失败：停，不改 7 个 `.py`，不提交。本地 8 文件保持不动（除 README 的既定改动）。

**行数。** 用 Python `splitlines()` 计行（末行无换行也算一行），记录 8 文件各自行数与合计进 Run record。本文写作时的参考值（合计 2291、`assert_e2e.py` 935）**不再是闸**——B 会改行数；若执行日数字与 B 后预期明显异常（如某文件归零），以异常处理停下人工核对，而非机械断言。`splitlines()` 与 `wc -l` 不一致时在 Run record 写明两种计数。

**打开核对底稿引用（只读）。** `drive.py` 里 key 只来自环境（底稿 `drive.py:73-75`）；`report.py` 有 redact（底稿 `report.py:171-176`）；`db.py` 的 `sys.path` 是仓库根（底稿 `db.py:13,20`）；角色是「`pg_roles` 没有该名才 CREATE」（底稿 `db.py:156-176`）。行号漂移可以，句子在文件里必须在。缺了就停。同时读 `db.py` 的 `--drop-only`：确认它删的是哪一个库名、库不存在时是否仍返回 0。本里程碑不给 `db.py` 加参数。harness 库名以 `test_harness.py` 里的字面量为准，预期是 `agent_demo_v15_harness`。

**8 文件形状扫描（报路径和模式名，不打印匹配行，避免行里真有 key）。** 失败模式：`/Users/`、`sk-` 后接字母数字、`Bearer `、`Authorization`、以及 `(DEEPSEEK_API_KEY|OPENAI_API_KEY)` 后面是赋值加引号字面量。`os.environ.get("DEEPSEEK_API_KEY")` 这种只提到变量名的句子必须仍然存在，并且不算失败。若当前环境里 `DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY` 非空且长度 ≥ 8，再检查这 8 个文件是否包含该值本身；命中则停，输出里不回显该值。

**本地 `demo_v15/reports/`（不入库）。** 目录存在（M2 产物）：用同一组模式扫描。命中则停（不提交）——redact 失效要另开里程碑改 `report.py`，不能在本次 force-add 里顺手改。

**额外文件。** `find demo_v15 -type f` 的每一项，要么属于 8 路径，要么 `git check-ignore -v` 有输出。`.env` 只要出现在任一检出的 `demo_v15/` 下就停。不要把 `.env` 抄进提交，也不要 cat 它。

**pytest。** 读仓库根 `pyproject.toml`：不存在 `[tool.pytest.ini_options]`、不存在会收集全仓 `test_*.py` 的 addopts。若有 `.github` workflow 用 pytest 收集全仓：停。今天不改名、不加过滤配置。停的原因是「今天安全」这个前提破了，改名属于另一项决策。（评审实证补记：全仓六处 rglob——v7/tests×2、v8/regression、v13×3——无一触及 `demo_v15/` 或收集仓库根 `test_*.py`。）

## 3.4 import 闭包

一次性 `uv run python -c`（或 stdin），脚本不写入仓库。Python 必须有 `sys.stdlib_module_names`；没有则停，不要手写一份 stdlib 名单。先 `uv run python -c "import sys; print(sys.version)"` 记入 Run record。

对 8 个 `.py`（README 不扫）做 `ast.parse`。收集每一处 `ast.Import`、`ast.ImportFrom`，以及 `importlib.import_module` / `__import__` 的字符串字面量参数。相对 import（`level > 0`）直接失败：这些文件是脚本，不是包。

模块名按下表分类，落在表外即失败：

| 类 | 规则 |
|---|---|
| stdlib | 顶层名 ∈ `sys.stdlib_module_names`（含 `__future__`） |
| 兄弟 | 顶层名 ∈ `{db, task, script, drive, assert_e2e, report, test_harness}`，且对应的 `demo_v15/<name>.py` 在本次 8 文件内 |
| 仓库 | 顶层名 `server` 时 `git ls-files --error-unmatch server.py` 成功。顶层名 `v15` 时把点号路径映到 `v15/...py`（以及同名包目录下被 import 的子模块文件），`git ls-files --error-unmatch` 成功。`from v15.provider import deepseek` 这种名字若磁盘上有 `v15/provider/deepseek.py`，该文件必须已跟踪 |
| 已安装第三方 | 顶层名只允许 `psycopg2`、`pgembed`。这两个是 `server.py` 与 `v15/provider/setup_db.py`、`v15/worker.py` 已经在用的依赖。出现第三个第三方名：停，禁止把 allowlist 加长来放行 |

`demo_v13`、`demo_v15` 作为 import 根，直接失败。

结构断言（缺一则停，仍然不改 `.py`）：

- `db.py` 顶层能到达 `server`、`v15.load`、`v15.provider.support`、`task`。
- `drive.py` 顶层能到达 `db`、`assert_e2e`、`report`、`script`、`task`、`v15.worker`。
- `v15.provider.deepseek` 至少出现一次，且只出现在 `drive.py` 的函数体或更深节点里，不在 `Module.body` 的直接子节点上。顶层出现即失败（demo 计划要求 keyless 路径在 import 期不构造 provider；模块 import 本身虽不开 socket，顶层 import 仍算违反该入口约束）。
- `assert_e2e.py` 能到达 `v15.protocol.split_sql` 或包路径 `v15.protocol`。
- `test_harness.py` 顶层能到达 `server`、`db`、`drive`、`script`、`task`（B 后 harness 经 `drive.run` 返回结果 dict，不再直连 `assert_e2e`——实证零处该 import，属预期重构）。
- `report.py` 的全部 import（含函数体内）只有 stdlib。`task.py` 允许 stdlib + 仓库 `v15.protocol.render_prompt`（B 的 sizer 实测 S 需要 render_system，顶层导入，实证 `task.py:8`）。`script.py` 允许 stdlib + 兄弟 `task` + 仓库 `v15.protocol.split_sql`（B 的分类闸 E1 修正需要，实证 `script.py:11`）。（B 后 AST 复核修正，2026-09-30。）

不要为了闭包去 `import db` / `import drive`。模块级是否调用 `get_server()` 未在本会话核实；import 副作用可能建库。动态证明只走下面三条命令行入口。

扫描结果写入 Run record：每个文件的顶层 import 根、deepseek 所在函数名。不把扫描脚本留在提交里。

## 3.5 文书

文书在 fake/harness/keyless 都通过、两个 demo 库都已 drop 之后再改。runtime 失败时这些文件应仍是 HEAD 原样（本计划文件除外，它本来就是未跟踪的新文本）。

### 3.5.1 `AGENTS.md`

`grep -c '该目录在 \`.gitignore\`。' AGENTS.md` 必须等于 1，且落在第 75 行那一条入口上。把这一小句换成：

已 force-add 的 8 个驱动源文件受跟踪；`.gitignore` 仍含 `/demo_v15/`，因此 `reports/`、`__pycache__/` 与此后新增文件仍被忽略。

前后句子保持原样：两个入口都不是 gate、也不是合运行时证明；调用当时不得有打开的数据库事务；无 key 时打印 `credentials_absent`、退出码 2、不构造 `DeepSeekProvider`、不调用 `complete`；`DEMO_MODE` 缺省为 `fake`。不改 §0.0，不改里程碑纪律，不把 demo 写进 `smoke.py`。

### 3.5.2 `.gitignore`

在现有 `/demo_v15/` 行上方插入注释，保留该行，不动 `:31-33` 的 v13 注释与路径：

```text
# demo_v15 driver sources (8 files) are tracked via git add -f.
# Keep this ignore: reports/, __pycache__/, and any new file stay untracked
# until an explicit git add -f of that path. git status will not list them.
/demo_v15/
```

注释用英文，与这份 gitignore 的其余注释一致。

### 3.5.3 `demo_v15/README.md`

文件是英文。先找到声称「目录 / 驱动源码被 gitignore」的那一句，底稿预期在第 1 行，短语 `The directory is gitignored`（在 `README.md:3`）。`grep -n gitignored` 之后：

- 只替换「整目录或源码未跟踪」的那一句。
- 已经只谈论 reports 不入库的句子保留。
- 若短语不存在：停，不要另写一套开头。

替换句：

The eight driver sources in this directory are tracked. `/demo_v15/` remains in `.gitignore`, so `reports/`, `__pycache__/`, and any file added later stay ignored until `git add -f` on that path.

在文末追加 `## Publish notes`，已有命令块、退出码、留库与 gate 的关系、key 纪律都保持原样。Publish notes 必须让读者读完 README 后能确认下面四件事；某一条若原文已经用同样的约束写过，就不要再贴一遍命令块：

1. 从仓库根执行 `uv run python demo_v15/db.py`、`drive.py`、`test_harness.py`。`python -m demo_v15...` 不是入口。`db.py` 用 `Path(__file__).resolve().parent.parent` 把仓库根放进 `sys.path`，这是脚本布局。
2. `source ~/.zshrc` 只用于非交互 shell 还要从操作者的 zshrc 取真实 key。`DEMO_MODE=fake` 不需要。key 已经在环境里时不需要。驱动不读这个文件。
3. `test_harness.py` 匹配 `test_*.py`，但不是 pytest 套件，也不是 v15 gate。禁止改名，禁止把本目录移到 `v15/` 下，禁止添加会收集它的 pytest 配置。
4. 本目录里 `git status` 看不到未跟踪文件。之后的提交用 `git ls-files demo_v15` 对照 8 路径白名单。禁止 `git add -A`。

### 3.5.4 demo 计划发布后记

追加在该文件末尾（Run record 之后），标题 `## 发布后记`。不改此前任何一行，包括 §3.7 围栏里已经写进 M1 的 AGENTS 旧文案。

先复读。对 `docs/plans/v15-demo-tail-delegation-plan-2026-09-29.md` 搜索 `gitignor`、`不入库`、`git add -f`、`demo_v15/**`、`无 demo_v15`、`没有 demo_v15`。本会话数行得到的命中如下；锚句对上就用这个行号，对不上就改后记里的行号到锚句实际所在行，锚句一个都找不到则停。

| 行 | 锚 | 分类 | 发布后的事实 |
|---|---|---|---|
| 28 | `# 1. Summary` 中「不入库」「跟踪提交只有」 | 现在时，已不描述当前树 | 8 个源文件已跟踪。报告仍不跟踪。该段记录的是 demo 计划自己的提交范围 |
| 21 附近（Background「跟踪策略」） | 「tracked 只有」计划文档、gitignore、矩阵/台账 | 同上 | 同上。复读时若该 bullet 没有这半句，就不要为它编一行 |
| 88 | 裁决 5「本计划 **不** `git add -f`」 | 对该计划的提交仍为真 | demo 计划的 M0/M1/M3 确实没 force-add。force-add 发生在本发布提交 |
| 146 附近 | `## 3.2` 下「目录（全部 gitignore）」 | 现在时，已不描述当前树 | 目录忽略规则还在；8 个已跟踪文件不再受它约束 |
| 470 | `## 跟踪文件` 表中 `.gitignore` 行，为何列含「都不入库」 | 行本身仍真 | M0 追加的 `/demo_v15/` 还在。报告与密钥仍然不入库。该行没有承诺源码永远不跟踪 |
| 484 附近 | 标题「只存在于忽略目录的文件」 | 现在时，已不描述当前树 | 标题是 demo 计划执行时的状态。文件现已跟踪 |
| 497 附近 | 「`git add -f` 这些文件不在本计划的任何提交里」以及「只 force-add 上表路径，排除 `reports/` 与任何 `.env`」 | 对该计划仍为真，且是本计划的授权 | 本发布提交就是那句「另写计划」。路径就是该表的 8 个文件，排除 reports 与 `.env` |
| 523 | 风险表「把 demo 放进 `v15/`」，处理列「路径固定在仓库根 `demo_v15/`」 | 仍然为真 | 本计划不移动目录。底稿称它「缓解理由的一半」：原先仓库根同时为了「保持未跟踪」和「避开 `test_*.py`」。未跟踪这一半已结束；这一行字面写的 rglob 理由仍然成立，所以不改 |
| 532 | `# 6` 首段「M1/M2 不把 `demo_v15/**` 放进 `git add`」 | 已执行步骤 | M1/M2 当时没加。不能把这句当成今后的提交办法 |
| 538 | M0 步骤「`git status` 确认无 `.env`、无 `demo_v15`」 | 已执行步骤 | 今天再跑这句，既看不到已跟踪的 8 文件，也看不到被忽略的 `.env` |
| 579 | M3 步骤「`git status` 确认没有 `demo_v15/`」 | 同上 | 同上 |
| §3.7 围栏 | 「该目录在 `.gitignore`。」 | 历史文案 | 这是 M1 写进 AGENTS 的句子。本发布提交已替换 AGENTS 中的那一小句；围栏保留 |
| 590 | 执行索引「本地库闸」行 `` `demo_v15/db.py`（gitignored） `` | 现在时标签已假 | `db.py` 已跟踪。忽略规则仍约束 reports、字节码和新文件 |

分类规则只用于复读时多出来的命中，避免再做一次设计：围栏里的「当时要提交的文案」算历史文案；M0/M1/M3 的命令算已执行步骤；「本计划不 force-add」算对该计划仍为真；现在时的「未跟踪 / 全部 gitignore / tracked 只有」算已不描述当前树；只谈论 reports 不入库的句子算仍然为真。

后记开头用一段话写明：发布提交说明是 `v15: publish the tail-delegation demo driver`；父提交是执行日复核过的 B 后分支尖；hash 用 `git log -1 --format=%H -- docs/plans/v15-publish-demo-driver-plan-2026-09-29.md` 查看，因为本提交不能收录自己的 hash。并写明 critique 文件故意不改。

### 3.5.5 调查回填

锚句对上才改，对不上就按锚句找到行，不要改 B/C/D 各节。

- 表行 A 的「一句话」列，现为 `force-add demo_v15/ 8 文件`。改为：已执行：force-add `demo_v15/` 8 文件（`docs/plans/v15-publish-demo-driver-plan-2026-09-29.md`，提交说明 `v15: publish the tail-delegation demo driver`）。规模、证据价值、风险三列不动。
- 「干什么」段末追加状态句：2026-09-29 已执行；与该段的文书修正在同一次提交；说明即上一句；树内不写自身 hash。保留原来的 8 文件名单与「不 add reports」这句，它仍然对；行数表述补一句「行数以发布计划 Run record 的执行日重测值为准」（本文的 2291/935 是 B 前参考值）。
- 「预期效果」第三条现为「需要同步改三处文书……gitignore 例外说明……跟踪策略节补一行 Run record」。整条改为已完成的事实：`.gitignore` 保留 `/demo_v15/` 并加了注释；`AGENTS.md` 只替换「该目录在 `.gitignore`。」；demo 计划正文不改，文末是发布后记；本调查 A 项标为已执行。不要写成「加了 gitignore 例外」或「在跟踪策略节里补了 Run record」，那两件事不发生。
- 「建议：做，且最先做」改为：已做（2026-09-29），仍排在 B 之前。
- 路线图里的 `A（发布驱动）` 改为 `A（发布驱动，已执行）`。B、C、D 的箭头与文字不动。

### 3.5.6 矩阵与台账

矩阵：`## Demo evidence（不是 gate）` 数据行的落点列，把 `gitignored demo_v15/reports/（不入库）` 换成 `驱动源码已入库（demo_v15/ 下 8 个文件）；reports/ 仍 gitignore、不入库`。该短语在文件中必须只出现一次。不新增行，不把这一行标成 ✅，不改「结果」列的 `tail_ok relay_ok`，不改断言列。

台账：`## Demo` 现有两句保留。在其后追加：驱动源码已入库（`demo_v15/` 下 8 个文件，force-add）。`reports/` 仍不入库。这一笔不新增 V15-D 行。找不到 `## Demo` 则停，不要另起编号。

## 3.6 实跑、暂存、提交、第二份工作树、推送

### 实跑

在文书修改之前，于本 worktree 用操作者入口 `uv run` 串行执行。cwd 是本 worktree 根。四条命令都带：

`env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1`

顺序：

1. `uv run python demo_v15/db.py --drop-only`。退出码 0。然后查 `pg_database`，`agent_demo_v15` 与 harness 库名都不存在。查询方式：`uv run python -c` 调用 `server.get_server()`，连到 `postgres` 库做 `SELECT datname FROM pg_database WHERE datname IN (...)`。禁止调用任一 `v15/*/setup_db.py`（那会删掉全部 `agent_v15_*` 并 DROP 角色）。
2. `DEMO_MODE=real uv run python demo_v15/drive.py`。stdout 有一行恰好是 `credentials_absent`，退出码 2。再次确认两个库名都不存在（无 key 不得建库）。
3. `DEMO_MODE=fake uv run python demo_v15/drive.py`。退出码 0，stdout 的成功行与 `latest.md` 的调用数字**以 B 完成后的实测为准**（B 的更深链会改变调用数与可能的措辞——执行日先跑一次 fake 记录「预期 stdout 行 / 预期 calls_used」为该跑基线，随后的证明树复跑用同一基线比对；本文写作时的 `tail_ok relay_ok` / `calls_used=3` 只是 M2 期参考值）。报告留在忽略目录，不加入提交。
4. `uv run python demo_v15/test_harness.py`。退出码 0。该脚本自己覆盖 continue-then-tail 与 keyless 子进程；步骤 2 仍然单独做，避免只靠阅读 harness 输出。
5. 再 `--drop-only`。harness 库若不是 `--drop-only` 的目标，用已有的 db 辅助函数按该名字删；若 CLI 只认识 `agent_demo_v15`，用一条连到 `postgres` 的 `DROP DATABASE <harness名> WITH (FORCE)`，只终止 `datname` 等于该库的后端。禁止 `DROP ROLE`，禁止 `starts_with(datname, 'agent_v15_')`。
6. 再次 `SELECT`，两个名字都是 0 行。

中断或非 0：先做步骤 5 的删除，再停。不提交。不改驱动。不跑 `DEMO_MODE=real` 的有 key 路径。

实跑可能在 `demo_v15/` 下生成 `__pycache__/` 与 `reports/`。提交前 `git check-ignore -v` 对报告和任意一个 `.pyc` 都必须有输出。

`uv run` 若改动 `uv.lock`，保持未暂存。不要 `uv sync` 去「修好」锁文件。`uv run` 本身不能启动则停。

### Run record

实跑通过后、`git add` 之前，填本计划文件末尾的 Run record。有空白字段就还不能暂存。字段见文末模板。

### 暂存

只允许这两次 add，禁止 `git add -A`、`git add .`、路径外的 `-f`：

```text
git add -f -- demo_v15/README.md demo_v15/db.py demo_v15/task.py demo_v15/script.py demo_v15/drive.py demo_v15/assert_e2e.py demo_v15/report.py demo_v15/test_harness.py
git add -- AGENTS.md .gitignore docs/plans/v15-demo-tail-delegation-plan-2026-09-29.md docs/investigations/v15-next-steps-survey-2026-09-29.md docs/reviews/v15-conformance-matrix-2026-09-29.md docs/reviews/v15-deviation-ledger-2026-09-29.md docs/plans/v15-publish-demo-driver-plan-2026-09-29.md
```

然后三条都要过：

- `git ls-files -- demo_v15` 排序后恰好是上面 8 个路径，不能多 `reports/`、`.pyc`、`.env`，也不能少。
- `git diff --cached --name-only` 排序后恰好是这 15 个路径。出现 `v15/`、`uv.lock`、`server.py` 或任何其他路径：停，不提交。
- `git status --short` 里，这 15 条是暂存（`A ` 或 `M `，README 与计划文件是 `A`，已跟踪文书是 `M`），并且只允许另外一条未暂存的 ` M uv.lock`。出现 `??` 则停。

对 `git diff --cached` 再跑 §3.3 的形状扫描。命中则停。人工看一眼暂存 diff 里没有第二份密钥；不要把报告正文抄进矩阵。

### 提交

```text
git commit -m "v15: publish the tail-delegation demo driver"
```

一行，无 body，不声称 gate 通过，不写金额。禁止 `--no-verify`。hook 失败就停，修 hook 要另当原因处理，本里程碑不绕过。

提交后立刻 `git show --name-only --format= HEAD`。集合仍须是那 15 个路径。若 hook 塞进了别的路径，且 `git status -sb` 表明该提交还没有任何远程：允许 `git reset --soft HEAD~1`，然后停在未提交状态，重新检查暂存。禁止 `reset --hard`。已经推送过则禁止 reset，停下来，不要 force。

### 脱离工作树的复跑

这是「clone 该提交」的证明，因为 pre-commit 的 `uv run` 仍可能看见本 worktree 磁盘上的忽略文件。

```text
git worktree add --detach <临时目录> HEAD
```

临时目录放在仓库外。在该目录用本 worktree 已有的 `.venv/bin/python` 直接跑与上面相同的 drop-only、keyless、fake、harness、再 drop-only。不要在证明树里 `uv run`：uv 的项目发现可能把 import 指回脏 worktree，从而掩盖缺文件。

证明树的两个前提随 §3.3 复核：① 若 B 改了 pyproject/依赖，先 `uv lock --check` 并确认本 worktree `.venv` 与 B 后锁文件一致（否则证明树用的是旧 venv，通过不代表新 clone 能跑）；② `server.py:14` 的 PGDATA 解析路径仍在（若 B 改成 DSN 直连，干净集群性质随之变化，Run record 记明）。这是干净集群：`db.py` 必须自己建角色。若第二个 pgembed 起不来，记录错误字样，改用降级证明，不要假装跑过干净集群：

- `git show HEAD:demo_v15/<每个文件>` 的 sha256 等于本 worktree 里刚测过的文件（README 用提交后的工作区副本）。
- 对这 8 个 blob 做 `ast.parse`（从 `git show` 读 stdin），闭包规则与 §3.4 相同。
- pre-commit 的 fake/harness/keyless 已经在与 HEAD blob 相同的字节上通过。

降级可以推送。若脱离工作树真的跑起来了并且失败（ImportError、退出码不对、建库失败）：不要推送，不要 amend。提交留在本地，停。这就是 `memdrive_phase2.py` 那种断链，推上去会变成远程上的坏树。

证明结束：`git worktree remove --force <临时目录>`。不要动本 worktree 的 `demo_v15/` 其余内容。

### 推送

`git fetch origin`。若 `origin/rp/agent/3e700836-agent` 不存在：`git push -u origin HEAD:rp/agent/3e700836-agent`。若存在：只有本地是它的严格快进后代才推。`git rev-list --left-right --count origin/rp/agent/3e700836-agent...HEAD` 左边非 0 则停。禁止 `--force`、`--force-with-lease`、`git push origin main`、`git push origin HEAD:main`。

推送被拒：按 AGENTS 的非 force 规则处理；仍然禁止把本分支推到 `main`。远程分叉无法快进：停，不要 rebase 到 `b7b5f88`。

「任何 clone 可复跑」在本里程碑的含义是：检出这个提交（或快进包含它的 `rp/agent/3e700836-agent`）之后，fake 与 keyless 命令成立。只克隆今天的 `origin/main` 仍然没有 `demo_v15/`，也没有 v15 运行时。把 v15 历史并入 `main` 要单独做，并且要先消化 `main` 上当时实际多出的提交（数量以执行日 fetch 后为准；09-29 参考值为 4 个 v13 提交）。

## 3.7 明确不改

`demo_v15` 的 7 个 `.py`；`v15/**`；`server.py`；根 `pyproject.toml`；`uv.lock`；`docs/designs/v15-jaz-dev.md`；`v15/README.md`；`v15/provider/README.md`；critique 文件；`SQL_LOAD_ORDER`；十道 gate；`pricing.py`；角色与 `agent_v15_*` 库。不新增 V15-D。不把 AST 脚本、报告、`.pyc`、`.env` 入库。不改 `test_harness.py` 的文件名。

## 3.8 `uv.lock` 脏行的单独处理（发布提交之前）

工作区长期存在 ` M uv.lock`（`requires-dist` 里 sqlalchemy 钉从 `>=2` 变 `>=2,<2.1`，stage 1 期间由某次 `uv run` 重锁产生，无对应代码变更）。发布提交不携带它（用户裁决：顺手单独处理，不混入发布）：

1. `git diff uv.lock` 确认仍只有这一行；`git checkout -- uv.lock` 还原到 HEAD 版本。
2. 还原后用**非变更性**验证：`uv lock --check`（退出码 0 即锁文件与 pyproject 一致）——不用 `uv run` 跑 gate（那正是产生脏行的操作类别，且会让「十道 gate 未跑」的 Run record 字段失真）。
3. 若第 2 步失败或随后任何 `uv run` 再次弄脏该行（说明环境真的需要该钉）：把该行作为一个独立提交入库（`v15: pin sqlalchemy below 2.1 in uv.lock`），同样不与发布混提交；此时 §3.2 身份核验的 status 行把 ` M uv.lock` 视为已处置（committed）而非缺失。
4. 两种结局都使 `git status` 在发布身份核验时只剩本计划文件一条 `??`。

## 3.9 推送后的立即事项（不在本提交内）

发布提交推上 `rp/agent-3e700836-agent` 后，**立即起草**「v15 线并入 main」的合并计划（独立里程碑）：范围是本分支自与 `origin/main` 的 merge-base 之后的全部 v15 历史（文件数以执行日 `git diff --stat` 实测为准，本文的 84+ 是 09-29 参考值），须先 `git fetch` 消化 `origin/main` 上当时实际多出的提交，合并方式（merge vs rebase）与 gate 全量重跑矩阵在那个计划里裁。本计划只负责把这句话写进 Run record 的「推送后」字段，不预支其结论。

# 4. File-by-file impact

| 文件 | 变更 | 为何 | 依赖 |
|---|---|---|---|
| `demo_v15/db.py`、`task.py`、`script.py`、`drive.py`、`assert_e2e.py`、`report.py`、`test_harness.py` | 只 `git add -f`，字节等于就地基线 sha256 | 闭包闸通过后按原样发布 | 就位核验、内容闸、AST、实跑都先完成 |
| `demo_v15/README.md` | 替换「整目录被 gitignore」句；文末 Publish notes | 裁决 3、9、10 | 在实跑之后改，避免把未验证的 README 和失败的运行绑在一起；改的是说明不是行为 |
| `AGENTS.md` | 只替换 `:75` 那一小句 | 裁决 5：与 force-add 同提交，避免新的假话 | 无代码依赖；与其他文书同一提交 |
| `.gitignore` | `/demo_v15/` 上方三行注释 | 忽略行必须留着，注释是后来的人唯一会看见的陷阱说明 | 同提交 |
| `docs/plans/v15-demo-tail-delegation-plan-2026-09-29.md` | 文末发布后记 | 裁决 1 | 复读锚句之后写；同提交 |
| `docs/investigations/v15-next-steps-survey-2026-09-29.md` | §A 五处最小回填 | 裁决 2 | 同提交 |
| `docs/reviews/v15-conformance-matrix-2026-09-29.md` | Demo evidence 落点一格 | 裁决 12 | 同提交 |
| `docs/reviews/v15-deviation-ledger-2026-09-29.md` | `## Demo` 追加一句 | 裁决 12 | 同提交 |
| `docs/plans/v15-publish-demo-driver-plan-2026-09-29.md` | 写入本计划；Run record 在暂存前填实 | 裁决 13。文件现在是 `??` | Run record 依赖实跑结果；与 8 文件同一提交 |

不改因此不进暂存：`docs/reviews/v15-demo-tail-delegation-plan-critique-2026-09-29.md`、`v15/README.md`、`v15/provider/README.md`、`uv.lock`。

15 路径必须一起出现在同一个提交里。只 add 了源文件、文书还是旧的，这个状态不能提交。

# 5. Risks and migration

没有 schema，没有新错误码，没有 v15 行为变化。回退是在未推送时按 §3.6 的窄条件 `reset --soft`；已推送则另做反向提交，不 force。`agent_v15_*` 与十道 gate 的合同不变。

| 风险 | 表现 | 处理 |
|---|---|---|
| 新文件继续被忽略 | 后人改了 `drive.py` 旁边的新模块，`git status` 是干净的，提交里却没有它 | README Publish notes + gitignore 注释 + 今后用 `git ls-files` 白名单。本里程碑不改忽略行 |
| `test_harness.py` 名字 | 将来 pytest 配置或把目录移进 `v15/` 会把它收成测试 | README 写明三禁。实证（评审）：六处 rglob 均不触及、pyproject 无 pytest 配置、无 CI。不改名 |
| `git status` 密钥盲区 | `demo_v15/.env` 或新密钥文件不出现在 status | 本提交用 ls-files 恰好 8 路径 + 形状扫描 + `find`。status 只用来确认没有把 `uv.lock` 和别的 `??` 卷进来 |
| 留着 `agent_demo_v15` | 下一次任意 v15 `setup_db.py` 在删完 `agent_v15_*` 之后 `DROP ROLE v15_owner` 失败 | 实跑前后 drop-only；失败路径也 drop。提交前 `pg_database` 查询为 0 行 |
| 走错检出 | 在 `b7b5f88` 上提交，或把本分支推到 `main` | 第 1 步四条 rev-parse。推送目标只是 `rp/agent/3e700836-agent` |
| 误加 `reports/` 或 `.env` | 报告里若 redact 失效会进历史；`.env` 同理 | 不复制这两类；ls-files 多一行就停；cached diff 形状扫描 |
| 闭包只在本地看起来是通的 | 磁盘上还有未跟踪模块，AST 若只扫「能 import 的」会放过 | AST 对照的是「已跟踪路径」，不是 `sys.path` 上碰巧能找到的文件。脱离工作树再跑 fake |
| 8 文件相对 B 完成时的状态被意外手改 | 就地基线记录后、提交前 sha256 复核不符（基线本身就是 B 后字节，不与 M2 期比对） | 停。没有 git blob 可恢复。不要删本地文件；与 B 的最后一笔提交核对是谁改的 |
| 证明树起不了第二个 Postgres | `get_server()` 失败 | 使用 §3.6 的降级证明并在终端留下错误字样。ImportError 与退出码错误仍然阻止推送 |
| hook 或 `uv run` 改写暂存区 / 锁 | 提交里出现第 16 个路径，或 `uv.lock` 被暂存 | `git show --name-only` 必须仍是 15 路径。锁文件保持未暂存 |
| 把「不重跑 gate」写成「gate 已绿」 | 提交说明失真 | 说明只有发布这一句。Run record 写明未跑十道 gate |
| 操作者接着跑 real | 花掉剩余 2/3 预算，或在发布 diff 里夹进 note 改动 | 本计划授权的 `complete` 次数是 0。note 与 `render_prompt.py` 不改 |

# 6. Implementation order

一步失败就停在那一步。1–4 不改已跟踪文件。5 失败时不进入文书修改。8 与 9 原子：15 路径一起暂存、一起提交。

0. **前置（B 完成与 uv.lock）。** B（更深链 demo）完成的机械定义：B 的计划文件已在 `docs/plans/`、其 Run record 字段无空缺、其全部里程碑提交（含证据回填）已在本分支（`git log --oneline` 能看到）、且 `git status` 显示 B 的驱动改动已全部提交（`demo_v15/` 下无 B 遗留未提交内容——被忽略的 reports/pyc 除外）。§3.8 的 uv.lock 处理完毕。Done when：以上逐项核过，`git status` 只剩本计划文件一条 `??`。
1. **身份。** §3.2 的 rev-parse 与 `git status --short`。Done when：HEAD 是 B 后的分支尖（带齐 `v15/` 与 demo 依赖），脏树干净。
2. **就位核验。** 8 路径存在性 + 行数记录 + sha256 基线。Done when：各文件行数与合计已记 Run record 草稿（数字是执行日事实，非 2291/935 旧值），sha256 基线已记。
3. **内容闸。** 行数记录（重测值）、底稿句子、形状扫描、本地 reports/、pytest/CI、`find` 与 check-ignore、**新文件枚举差分**（`ls demo_v15` 对白名单；多出的非忽略文件要么按 §3.2 扩白名单并同步五处「8 文件」文案，要么是 B 遗漏入库的证据——停下核对 B 交付物清单）。Done when：全部通过，计数已记草稿。
4. **AST。** §3.4。Done when：没有表外模块，deepseek 只在 `drive.py` 函数体内，必需 import 都在。脚本不留在树上。
5. **实跑。** §3.6 的六步。Done when：keyless 退出码 2 且未建库；fake 退出码 0 且 stdout/报告数字等于**执行日自建基线**（B 后重测）；harness 退出码 0；两个库名从 `pg_database` 消失；reports 与 pyc 被忽略。
6. **文书。** §3.5 全部，含发布后记的锚句复读。Done when：AGENTS 旧句 grep 计数为 0；gitignore 仍有 `/demo_v15/`；README 含 Publish notes 四条约束；调查 A 不再把发布写成待做；矩阵只有落点列变化；台账无新 D 编号；7 个 `.py` 的 sha256 仍等于就地基线。
7. **Run record。** 按模板填满。Done when：没有空白字段。这一步是暂存前对计划文件的最后一次编辑。
8. **暂存闸。** 两条 `git add`，然后 ls-files、cached name 集合、status、cached diff 形状扫描。Done when：恰好 15 路径，`uv.lock` 仍是未暂存修改。
9. **提交。** 指定的一行说明。Done when：`git show --name-only HEAD` 仍是这 15 路径。hook 失败则不推送。
10. **脱离工作树。** §3.6。Done when：同一套命令在证明树里通过，或降级证明的 blob 哈希与 AST 通过且证明树的失败原因只是第二个 Postgres 起不来。行为失败则不推送。
11. **推送。** 只快进 `origin/rp/agent/3e700836-agent`。Done when：远程该分支含此提交，`origin/main` 的 tip 未变。

## 执行索引

| 工作项 | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| 身份 | 确认发布点是 B 后的 v15 分支尖 | `git fetch origin` 后：HEAD=执行日分支尖（带齐 v15/ 与 demo 依赖）；`git merge-base HEAD origin/main` 记入 Run record（该值同时是 §3.9 合并计划的起点事实）；脏树只有本计划文件 | 无 | fetch origin | 小 |
| 就位核验 | 8 文件已在位、行数与 sha256 基线记录 | 8 文件存在，行数为执行日重测值，基线已记 | 本 worktree `demo_v15/` | 身份 | 小 |
| 内容闸 | 行数、密钥、绝对路径、reports、pytest、新文件枚举差分 | 形状扫描无命中（含本地 reports/）；无白名单外的非忽略新文件 | 8 文件；`demo_v15/reports/` 只读 | 就位核验 | 小 |
| AST 闭包 | 防止 demo_v13 式断链 | 表外 import 为 0；deepseek 仅 drive 函数体内 | 7 个 `.py`；`git ls-files` | 就位核验 | 小 |
| 实跑 | 零 key 复跑 | fake 0、keyless 2、harness 0、两库已删 | `drive.py`、`test_harness.py`、`db.py` | 内容闸、AST | 中 |
| 文书 | 去掉发布造成的假话 | §3.5 各锚句已改或已写入后记 | AGENTS、gitignore、README、调查、demo 计划、矩阵、台账 | 实跑 | 中 |
| 提交 | 15 路径一次入库 | `git show --name-only` 恰好 15 路径 | 上表全部 | 文书、Run record、暂存闸 | 小 |
| 证明树与推送 | 入库字节可复跑，且不改写 main | 证明通过或已记录的降级通过；远程分支快进；main tip 不变 | 临时 worktree | 提交 | 中 |

## Run record

执行到第 7 步时填实。提交进树之后不要为了补 hash 再做第二次提交。

- 日期：2026-09-30（本地；fake 报告戳 UTC `20260929T192238Z`）
- 父提交（B 完成后的分支尖，执行日核得）：`890d3a15e888860068201e91990b3a2b055f8567`（uv.lock 独立提交；其父为 B 完成提交 `1d3d05b`）。`git fetch origin` 后 `git merge-base HEAD origin/main` = `e915e922728d5b2c56a2c428af58f3d1d48f22c0`
- 提交说明：`v15: publish the tail-delegation demo driver`
- 自身 hash：不写入。读取命令：`git log -1 --format=%H -- docs/plans/v15-publish-demo-driver-plan-2026-09-29.md`
- Python：`3.12.11 (main, Sep 18 2025, 19:41:45) [Clang 20.1.4 ]`
- 行数：合计 3239 / `assert_e2e.py` 1384（`splitlines`）；与 `wc -l` 相同。各文件：README 23、db 293、task 299、script 122、drive 652、assert_e2e 1384、report 216、test_harness 250
- README 改前 sha256（等于就地基线）与改后 sha256：`1b71b0f65300a496ec88de9a56dfc72a045db25f581180d6626e6185410ae436` / `ef459a5dd754fa27beb37c3b7a046ac8db9436dfb8c4afb0bdc1447928104073`
- 其余 7 文件 sha256（等于就地基线，提交前复核）：db `f94f41d5d203b65c9c9623d2eec3e0205a6470881dc4eaa78133f3800995b42d`；task `6760e831eea662f48e14ddf90bdd0b252874c8e391b36ab2775a5fbe7d97e059`；script `e5cd94029513daf46e72a066dd3a301b2b73bde63871f91fbf9723f106da27d1`；drive `7ea1acf08b3769cf0f759968f3a2a0dd23c5538ee3ddddac22d687e87ff33a1e`；assert_e2e `52efd2cb1a9fe3a7df129a3f57b7c0f0a71d2bf3fa05971cffe7cb12556a26d9`；report `e0a9d0df02d5fc4708631bec1360664c63cc4f5d67929045bd2b318b24310622`；test_harness `66da959424bbec0cf53b82bf99f680fc111441c226eccbac549c4fbc5713f9db`
- AST：通过（修正后断言，退出码 0）。顶层 import 根：db `__future__ re sys uuid pathlib psycopg2 server v15.load v15.provider.support v15.worker task`；task `__future__ json re secrets v15.protocol.render_prompt`；script `__future__ json sys pathlib v15.protocol.split_sql task`；drive `__future__ contextlib io json os secrets sys uuid pathlib psycopg2 server v15.protocol.render_prompt v15.provider.support v15.worker db assert_e2e report script task`；assert_e2e `__future__ json re sys decimal pathlib v15.protocol.split_sql task`；report `__future__ json datetime pathlib`；test_harness `__future__ os subprocess sys pathlib server db drive script task`。`drive.py` 中 deepseek 所在函数：`build_real_provider`
- fake：退出码 0；stdout 首行 `tail_ok relay_ok`（次行是忽略目录里的报告路径）；latest 报告 `- calls_used: 8`
- keyless：退出码 2；stdout 恰好 `credentials_absent`；当时 `pg_database` 无 `agent_demo_v15` 与 `agent_demo_v15_harness`
- harness：退出码 0
- drop 之后两库 0 行：是（`--drop-only` 与 `--drop-only agent_demo_v15_harness` 均退出码 0；另用同一 CLI 删了 harness 自建的 `agent_demo_v15_bound`，三名查询均为 0 行）
- reports 扫描：已扫且无命中（35 个文件；目录存在为常态——M2/B 产物）
- uv.lock 处置：独立提交 `890d3a15e888860068201e91990b3a2b055f8567`（还原后 `uv lock --check` 退出码 1；`uv lock` 仅一行 sqlalchemy `>=2,<2.1`；提交后再 check 退出码 0）。不进本次暂存
- B 完成提交：`1d3d05b2125177df0c0dbed400720074887574b8`
- 十道 gate：未跑（发布 diff 无 v15/ py/sql）。本提交说明不声称 gate 通过
- 推送后承诺：立即起草「v15 线并入 main」的合并计划（§3.9；起点即上列 merge-base）。本字段在暂存前填承诺句，非事后事实
- `DEMO_MODE=real` 有 key：未跑
- 脱离工作树：未执行。步骤 10 交回主 agent；本记录在提交前填写，不声称通过

## References

- 依赖与文件清单：`docs/investigations/v15-next-steps-survey-2026-09-29.md` §A
- 发布计划先例：`da4663e`；反面先例：`demo_v13/memdrive_phase2.py:25-26`

