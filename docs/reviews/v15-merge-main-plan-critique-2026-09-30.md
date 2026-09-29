# v15 并入 main 合并计划（浓缩版）评审

- 评审对象：`docs/plans/v15-merge-main-plan-2026-09-30.md`（浓缩版，112 行）
- 保全基线：`/tmp/cb-merge.md` codex 轨（`# v15 线并入 main 合并计划` 至 `### Oracle 2`，下文引用为 codex §x）
- 异见参考：grok 轨（同文件 `### Oracle 2` 之后）。cursor 轨实际无内容（`Error: RetrievableError: Connection stalled`），不构成参考。
- 核查环境：worktree `rp-agent-3e700836-agent` @ `4eddbb4`（即待合并分支尖），2026-09-30 实跑。**网络当前不通**（`git fetch` 报 `curl 28 Operation too slow`），`origin/*` 为最后一次成功同步的 remote-tracking 引用；用户已口头核实远程分支尖 = `4eddbb4`。

## 0. 事实核查快照（本节全部为本次实跑结论）

| # | 计划的断言/前提 | 实测 | 结论 |
|---|---|---|---|
| F1 | merge-base `e915e92` | `e915e922728d5b2c56a2c428af58f3d1d48f22c0` | ✅ |
| F2 | 分支尖 `4eddbb4`（已推送） | 本地分支 = `origin/rp/agent/3e700836-agent` = `4eddbb4` | ✅ |
| F3 | `origin/main` = `633f957` | `633f9571…`（stale ref，网络不通无法刷新） | ✅（待网络恢复复核） |
| F4 | `4eddbb4`/`890d3a1` 是 tip 祖先 | 两条 `merge-base --is-ancestor` 均 0 | ✅ |
| F5 | `890d3a1` 只动 uv.lock | `uv.lock` 1+/1- | ✅ |
| F6 | demo_v15 恰八文件 tracked | `git ls-files -- demo_v15` = 8 条（README/assert_e2e/db/drive/report/script/task/test_harness） | ✅ |
| F7 | 八个 README 陈旧「九文件」 | `grep 九`：恰 8 个文件（config/io/loop/namespace/protocol/schema/repl/tree，均第 5 行同句）；govern 的「九」在准确句里；`v15/README.md`、provider 无「九」 | ✅ 枚举精确 |
| F8 | main 侧「预期 4 个提交」 | **19 个**（`e915e92..633f957`：pi_ports×8、pi_parity×5、1 个 merge、long-loop 计划×4、plan_contract、plan_read） | ❌ 计划停止规则会立刻触发 |
| F9 | 理论冲突面＝根级共享文件 | 双方路径交集**仅 `.gitignore`**；main 侧未动 AGENTS.md/pyproject.toml/uv.lock/server.py，未动任何 `v15/**`、`demo_v15/**`；docs 无同路径交集 | 部分成立，见 F10 |
| F10 | （隐含）合并会有冲突要解 | `git merge-tree --write-tree` 对 `633f957` 与本地 `0b18d0a` 均 **exit 0、零冲突路径**；`.gitignore` 两侧改动行区不相交（main 在文件尾追加 13 行，分支在中部插 4 行） | ❌ 冲突面实测为空 |
| F11 | （隐含）本地 main = origin/main | **本地 main = `0b18d0a` = `633f957` + 2 个未推送 v13 提交**（`649b1f9`、`0b18d0a`，动 `v13/load.py`、`v13/plan_arm/`、`v13/loop_driver/`、两份 phase-A 文书） | ❌ 见 §2.2 |
| F12 | （隐含）可在当前会话执行 `git switch main` | `git worktree list`：main 检出于**主检出** `/Users/wxl/Projects/pg-agent`；本会话 worktree 检出的正是待合并分支 | ❌ 见 §2.1 |
| F13 | 收尾工件存在 | matrix/ledger/critique 三文件均存在且 tracked | ✅ |
| F14 | hook 纪律 | 无 `.pre-commit-config.yaml`，hooks 目录仅 sample | 无活动 hook，该风险不适用 |
| F15 | 提交信息 `v15: merge the v15 line into main`（单行） | 分支近期提交（`4eddbb4`、`890d3a1`、`1d3d05b`）**全部带** `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` 尾行 | 见 §3.4 |

另：`.gitignore` 在 main 侧被 **4 个不同提交**改动过（`6212d27`/`5074e83`/`64b802d`/`8b15588`）；`v13/load.py` 被 2 个 main 侧提交改动、分支未动（自动取 main 侧）。

## 1. 浓缩版对 codex 基线实现性内容的丢弃/弱化

### 1.1 逐提交 `git show --find-renames`（codex §3.2.2）→ 降级为风险表补救
codex 对每个 main 侧提交执行 `git show --format=fuller --find-renames <commit> -- .gitignore AGENTS.md pyproject.toml uv.lock server.py v13 v8 docs`。浓缩版 §2 只剩两个区间 `diff --name-status`，逐提交检查只剩 §8 风险表里一句「逐提交 `git show` 语义合并」——从**合并前必做的审计步骤**弱化为**冲突发生时的补救动作**。实际损失：rename 检测（D+A 会伪装成「main 删除+新增」）、区间内改了又还原的路径不可见、`.gitignore` 的语义并集失去「哪行来自哪个提交」的出处。F10 已证冲突面为空，故这主要是审计链损失而非阻塞项——但 `.gitignore` 恰恰被 main 侧 4 个提交分摊改动（F15 附注），逐提交 `show` 是唯一能还原出处的方式，应恢复进 §2 命令块。

### 1.2 合并前祖先预检（codex §3.2.3）→ 只剩断言、没了命令
codex 在合并**前**跑 `git merge-base --is-ancestor 4eddbb4 / 890d3a1 origin/rp/agent-3e700836-agent`。浓缩版 §2 判据里保留了「`4eddbb4`/`890d3a1` 是 tip 祖先」的字样但没有任何命令；§7 只保留了**提交后**的祖先检查。本次实测两条预检均过（F4），但计划应保留可执行形式——它防的是「合并了一个被移动/陈旧的分支引用」。

### 1.3 integration 分支的重跑/弃置程序出现硬伤
浓缩版 §7 的推送被拒路径「弃旧 integration、从新 main 重走 §4–§7」：重走 §4 的字面命令 `git switch -c integrate/v15-main-20260930 origin/main` 会**直接失败**（分支已存在，需先 `git branch -D` 或改 `-B`）。codex 只说「建立新的 integration 分支」（同样未写删除，但至少语义是「新分支」）。另外两版都没写成功后清理 integration 分支（悬空分支卫生问题，次要）。

### 1.4 「合并与 ff 之间不得插入额外提交」的原子性禁令被删
codex §6 步骤 14 明文：「此步骤与前一步及后续 fast-forward 必须保持同一合并里程碑，不拆成 v15 代码、文书、锁文件多个提交」。浓缩版 Goal 里的「单一合并提交」隐含了它，但显式禁令（防止执行者在 gate 前先提交冲突解、或把 README 修正另起一提交）被删。这与 §2.5/§2.7 的记录载体问题耦合，见下。

### 1.5 §3.6.1 的显式库名清理阶梯被砍成单步
codex 的阶梯：`--drop-only` → **CLI 显式库名** → 仍残留才允许 `DROP DATABASE … WITH (FORCE)`，且清理失败不启动 gate。浓缩版 §5 只剩「`--drop-only` + 查空」。这不是理论路径：发布 Run record 曾实际需要显式删 `agent_demo_v15_harness` 与 `agent_demo_v15_bound`（grok 轨引用）；`demo_v15/db.py` 的 `--drop-only [name]` 确实接受尾随库名（`db.py:260-266`，`check_name` 正则接受 `agent_demo_v15_[a-z0-9]+` 后缀）——**但一次调用只删一个库**，多残留需多次调用。浓缩版执行者在遇到残留时没有定义好的下一步。应恢复整条阶梯。

### 1.6 八 README 修正的范围护栏被删
浓缩版 §6.1 保留了 8 个 stage 的括号枚举与 govern 不动（F7 证明枚举精确），但删了两句护栏：codex §3.8.2 的「`v15/README.md` 和 `v15/provider/README.md` 已描述十文件，不重复修改」与「**只修正文件数量和由此产生的直接表述，不改 gate 行为、SQL 说明或历史 stage 边界**」。后者是防止顺手扩写的边界条件，应恢复。另建议加一条前置 `grep -rn 九 v15/*/README.md` 实测（本次已代跑：恰 8 处）。

### 1.7 git-status 盲区：风险行幸存，支撑清单被删
 briefing 认为此行被删——实测**风险行本身在**（§8 末行「status 看不见 ignored 密钥/报告」）。真正被删的是支撑结构：codex §3.5 的**禁止状态清单**（无冲突标记 / 无未解释 uv.lock 修改 / 无 `demo_v15/.env` / reports 与 `.pyc` 不入 index / 无差异清单外路径）及其 gate 前 `git status --short` + `git diff --check` 检查。浓缩版只剩 demo 段的 check-ignore。属弱化而非删除。

### 1.8 其他值得恢复的丢弃
- codex §3.2.1 的身份预检（`rev-parse --show-toplevel` / `--abbrev-ref HEAD` / `remote get-url origin`）——「我在正确的检出里吗」，与 §2.1 拓扑问题直接相关；
- codex §3.6.3 的兜底「无法机械确定依赖范围时跑仓库已有 v13/v8 gate 集合」——浓缩版只留「无交集则记无额外 gate」；
- codex §3.8.1 的合并后 `v15/load.py` 核对（`SQL_LOAD_ORDER` 仍十项、provider 在末尾、无 v13 SQL 混入）——浓缩版 §6 完全没这一步；
- codex §6 步骤 17 的**推送后**验证（fetch、`origin/main` == merge SHA、`is-ancestor` 分支→origin/main、终值 SHA 落档）——浓缩版止于 push；
- codex §3.8.5「文书若触及 .py/.sql/pyproject/uv.lock/server.py 须重验」——次要。

## 2. 浓缩版自身的矛盾与缺失依赖

### 2.1 `git switch main` 在当前拓扑下必然失败（执行阻塞）
§4 第一条 `git switch main && git pull --ff-only origin main`、§7 的 `git switch main`：F12 实测 main 检出于主检出 `/Users/wxl/Projects/pg-agent`，而本会话 worktree 检出的正是待合并分支。从本 worktree（或任何非主检出的 worktree）执行将得到 `fatal: 'main' is already checked out at …`。codex 同病（§3.3 同样的 `git switch main`，「在干净 worktree 中执行」从未说明是哪个检出）。**计划必须指名执行场地**：主检出（main 所在、要求其干净空闲），或专用 integration worktree + 不动本地 main（直接 `git push origin integrate/v15-main-20260930:main`，普通推送本身就是远程快进），或把本会话 worktree 切到 integration 分支跑完全程（`.pgdata` 已热，见 §3.5）。三条路线的取舍见 §4 Q2。

### 2.2 本地 main 领先 origin/main 两个提交——§4/§7 照写会在跑完十道 gate 之后才炸
F11：本地 main = `0b18d0a` = origin/main + 2 个未推送的 v13 long-loop Phase A 提交（记忆载明「两 commit 待网络恢复推送」）。浓缩版（与 codex）只检查**分支**的本地/远程分叉，从不检查 main 的对齐。照文执行的时序：§4 的 `pull --ff-only` 因为远程**落后**于本地而平凡成功（Already up to date），分叉被静默掩盖；§7 的 `git merge --ff-only integrate/…` 上到本地 main 时失败——`0b18d0a` 不是合并提交（第一父 `633f957`）的祖先。此错误在**十道 gate 全部跑完之后**才暴露。更危险的是「修一下」的冲动：普通 merge 或 rebase 会把两个无关的未推送 v13 提交卷进 v15 里程碑推送，直接违反 AGENTS「不要顺手把无关工作卷进提交」。**正解是排序问题**：先把那 2 个 v13 提交按其自身里程碑推送（网络恢复后），再从新的 `origin/main`（`0b18d0a`）重测差异面——实测 `merge-tree` 对 `0b18d0a` 同样零冲突，且那 2 个提交不动任何根级文件，计划结构完整存活，只是 main 侧实数变成 21、差异清单加 `v13/plan_arm/`、`v13/loop_driver/` 等（见 §4 Q1）。

### 2.3 `pull --ff-only` 与 AGENTS 的 `pull --rebase` 字面冲突，未做说明
AGENTS.md：「push 被拒…需要时 `git pull --rebase origin main` 后重推」。浓缩版 §4 用 `--ff-only`。实质上 `--ff-only` 是「历史只追加」更严格的读法（干净 main 上二者等价；分叉时 `--ff-only` 拒绝而 `--rebase` 改写本地提交——前者才是对的，这正是 §2.2 想要的失败模式）。但计划对这一偏离 AGENTS 字面的选择只字未提，且 AGENTS 那句的语境是**推送被拒的恢复动作**，不是合并前的对齐动作。补一句显式理由即可消除矛盾（顺带把 §4 的对齐检查改成对 `main...origin/main` 的 `rev-list --left-right --count`，今天实测 `2	0`，非 `0 0` 即停）。

### 2.4 §2 命令块笔误
`git rev-list --left-right --count rp/agent/3e700836-agent...origin/rp/agent-3e700836-agent`——`origin/rp/agent-3e700836-agent` 少了 `agent` 后的斜杠，照跑报 unknown revision。codex 原文正确。

### 2.5 计划文件自身的提交载体未定义
实测本计划文件在本 worktree 是未跟踪状态（`?? docs/plans/v15-merge-main-plan-2026-09-30.md`）。两版计划都没写它自己怎么进 main：codex 不提；grok 明确把它的计划文件只放进合并提交（从而不改写分支尖）。若执行者不 `git add` 它，合并后的 main 缺少 matrix 将引用的那份计划。需裁决（§4 Q4）。

### 2.6 「预期 4 不符即停」在第一步就触发
F8：main 侧实数 19（若先推 v13 两提交则 21）。浓缩版 §2「预期 4，不符即停」与 codex §3.2.2 的同等规则都会让执行在第一个核查步停下。路径级停止谓词（不动 `v15/**`、不删 v15 路径、不动 `SQL_LOAD_ORDER`）本次全部通过——「4」是陈旧任务输入（只对应 `e915e92..b7b5f88` 时代的计数），三条轨里只有 grok 预先对冲过（「个数不同不自动停」）。改写成实测清单即可，不构成实质风险。

### 2.7 matrix 要记「merge SHA」，但 matrix 修改搭乘在合并提交里——自指矛盾（承自 codex）
§6.2 要求 matrix 记录 merge SHA，§7 又把 matrix 放进合并提交：提交无法包含自己的 SHA。codex §3.8.3 + 步骤 12/14 同构矛盾。可选解：(a) 合并提交内只记双亲 SHA 与十道退出码，merge SHA 留给推送后记录（grok 的立场：不为写回 SHA 做第二次提交）；(b) 推送后补一个纯记录小提交（两提交一里程碑，需对 AGENTS「一个里程碑一次提交」做一句豁免说明）。计划必须二选一（§4 Q4）。

## 3. 两份文档（codex 与浓缩版）共同遗漏

### 3.1 worktree/检出拓扑约束
两版都没有 `git worktree list`，不问 main 在哪、执行在哪个检出（详见 §2.1）。唯一正确处理此题的是 grok 轨：专用临时 worktree 做合并、只在本地 main「就是旧 MAIN0 且未被其他 worktree 检出」时才 ff、功能分支 worktree 全程停在 FEATURE——而且它的「本地 main 有独自提交就停下来问」条件恰好会在今天的 `0b18d0a` 上正确刹车。值得整体借鉴。

### 3.2 main 本地/远程对齐预检缺失
见 §2.2。一句话补进 §2：`git rev-list --left-right --count main...origin/main`，非 `0 0` 即停并先处理（推送或明确豁免）。

### 3.3 冲突面其实**现在就可证空**——两版都没用 `git merge-tree`
`git merge-tree --write-tree`（git ≥2.38，本机 2.49）只读、不触工作区，一次调用即给出确定性冲突清单。实测对 `633f957` 与 `0b18d0a` 均零冲突（F10）：`.gitignore` 两侧改动行区不相交（main 侧 EOF 追加 pi_ports/pi_parity 构建产物 13 行；分支侧中部插入 `/demo_v15/` 4 行块）；AGENTS.md/uv.lock 仅分支改动（自动取分支）；pyproject.toml 与 server.py 双侧未动。**§3 的整套冲突规则当前一条都不会触发**——应把 merge-tree 作为 §2 的第一个冲突探针、§3 降级为纯应急预案。注意：零冲突不豁免任何语义检查（`uv lock --check`、ls-files 白名单、gate 全量）。

### 3.4 合并提交的署名/尾行问题
F15：v15 线近期提交全部带 `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`。计划的单行提交信息没有尾行，与本会话的署名约定和仓库近期惯例都不一致。合并提交要不要带尾行，需在提交前定（带尾行不违反「单行摘要」风格；grok 的「恰好一行无 body」若按字面执行会排除尾行——那是 grok 的约束，不必继承）。见 §4 Q3。

### 3.5 第二个 pgembed 实例（仅 grok 发现）
`server.py` 把 PGDATA 钉在文件父目录，每个 worktree 各有一块 `.pgdata`（实测本 worktree 与主检出都有；当前无 postgres 进程在跑）。在新 worktree 里跑 gate 会初始化一个全新嵌入式集群；串行执行下唯一风险是另一处实例仍在运行占端口。最简消解：选一个 `.pgdata` 已热的场地执行（本 worktree 或主检出）；否则采纳 grok 的「第二个 Postgres 起不来：记录原文、停、不改 server.py、不杀另一实例」。

### 3.6 hook 与网络现状（关闭两个开放问题）
- 无活动 hook（F14）——AGENTS 的 hook 纪律与 grok 的 hook 应急对本次合并均不适用，可在计划里记一句「已核实无 hook」。
- **网络当前不通**：计划的第 1 步 fetch 与最后 push 都需要网络，且同一阻塞已压着那 2 个 v13 提交。fetch 失败本身也使「远程分支尖 = 4eddbb4」的核实只能依赖 stale ref + 用户口头确认。gate 本身离线可跑（FakeLLM），但按计划顺序（fetch 先行）整体不可启动——执行前先确认网络（§4 Q6）。

## 4. 改变执行方式的待裁决问题

1. **先推那 2 个 v13 提交吗？**（推荐：推。它们是已完成的独立里程碑；推完后 main 侧实数 21、需重贴差异清单，但实测零冲突且不动根级文件，计划结构不变。不推则只能 `integrate/…:main` 直推、本地 main 长期分叉，后续必欠一次手工整合——劣路。）
2. **执行场地选哪？** 主检出（main 所在，`git switch main` 唯一可行处，要求干净空闲）vs 本会话 worktree 切到 integration 分支（`.pgdata` 热、uv 环境现成，但本 worktree 离开 v15 分支）vs 新专用 worktree（最干净，代价是冷 `.pgdata`，见 §3.5）。场地决定 §4/§7 的字面命令是否需要改写。
3. **合并提交带不带 `Co-Authored-By` 尾行？**（近期历史全带；建议带。）
4. **计划文件与 merge SHA 的落档载体？** 计划文件进合并提交（grok 式）还是随收尾文书另行处理？matrix 的 merge SHA 用「推送后记录」还是「补一个记录提交」？（§2.5/§2.7，二者必须一起裁。）
5. **「预期 4」改写成实测 19/21，还是执行时按停止规则走一遍再改计划？**（推荐现在改，停止规则本意是防范围意外，不是防已知陈旧输入。）
6. **网络不通期间是否允许离线预跑？**（例如先 merge-tree + 差异清单 + 甚至离线跑十道 gate，推送等网络。计划顺序是 fetch 先行；若允许离线预跑，需明确「预跑结果不作为 gate 证据、网络恢复后重走」的边界。）

## 附录：核查命令与关键输出

```bash
git worktree list
# /Users/wxl/Projects/pg-agent  0b18d0a [main]          ← main 在主检出
# …/rp-agent-3e700836-agent     4eddbb4 [rp/agent/3e700836-agent]  ← 本会话
git fetch origin --prune        # 失败：curl 28 Operation too slow（网络不通）
git rev-parse origin/main main rp/agent/3e700836-agent origin/rp/agent/3e700836-agent
# 633f9571…  0b18d0a1…  4eddbb42…  4eddbb42…
git merge-base origin/main rp/agent/3e700836-agent   # e915e922728d5b2c56a2c428af58f3d1d48f22c0
git log --reverse --oneline e915e92..origin/main     # 19 个提交（pi_ports/pi_parity/long-loop/plan_*）
git rev-list --count 633f957..main                   # 2（649b1f9、0b18d0a，未推送）
comm -12 <(git diff --name-only e915e92..origin/main | sort) \
         <(git diff --name-only e915e92..rp/agent/3e700836-agent | sort)   # 仅 .gitignore
git merge-tree --write-tree --name-only origin/main rp/agent/3e700836-agent  # exit 0，零冲突
git merge-tree --write-tree --name-only main rp/agent/3e700836-agent         # exit 0，零冲突
git ls-files -- demo_v15                             # 恰 8 文件
grep -n 九 v15/README.md v15/*/README.md             # 8 处陈旧 + govern 1 处准确句
git show --stat 890d3a1                              # uv.lock 1+/1-
git log --oneline e915e92..origin/main -- .gitignore # 4 个提交（6212d27/5074e83/64b802d/8b15588）
ls .pre-commit-config.yaml                           # 不存在；hooks 目录仅 sample
git log -3 --format='%b' 4eddbb4                     # 均含 Co-Authored-By: Claude Sonnet 5
```

## 结论

浓缩版方向正确、裁决表完整，但相对 codex 基线丢了一层「执行时照着敲」的护甲（§1），且有两处照文执行必然失败的硬伤：`git switch main` 的检出拓扑（§2.1）与本地 main 领先两个未推送提交（§2.2）——后者会让失败在十道 gate 跑完之后才暴露。同时本次实测把计划最重的部分（§3 冲突规则）证明为当前不会触发的应急预案（F10），把「预期 4」证明为陈旧输入（F8）。建议按 §4 六问裁决后出一版修订，再进入执行；执行顺序上先推 v13 两提交、再走合并，是当前状态下唯一不违反仓库纪律的路径。
