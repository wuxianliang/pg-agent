# v15 线并入 main 合并计划

## Goal

把分支 `rp/agent/3e700836-agent` 自 merge-base `e915e92` 之后的全部 v15 历史（发布提交 `4eddbb4`、uv.lock 钉提交 `890d3a1` 及此前所有里程碑）以**一次非快进、非压缩、非 rebase 的 merge commit** 并入最新 `origin/main`；合并前实测双方差异面、按规则解决冲突、在未提交合并树上串行重跑十道 v15 gate 与受影响旧版本 gate、demo 复跑与清理，全部通过后单一合并提交、经 integration 分支普通推送远程 main（不动本地 main）；任何未定义冲突、gate 失败或远程分叉即停——不 force、不 reset、不重写已发布历史。

## 背景与输入（未实测前皆为任务输入，非结论）

- 共同基线 `e915e92`；`origin/main` 写作时为 `633f957`（main 侧多 4 个 v13 提交，内容**未读**，计划第一步实测）；v15 分支 tip `4eddbb4`（已推送）。
- v15 与 v13/v8 无共享 schema/库名（各 `v<N>/` 前缀隔离）；理论冲突面仅根级共享文件（`.gitignore`、`AGENTS.md`、`pyproject.toml`、`uv.lock`、`server.py`）与 docs 同名文件。
- 十道 v15 gate（schema→namespace→config→protocol→repl→io→loop→tree→govern→provider）须**本次合并重新全绿**，旧的全绿记录不算数；stage setup 互相删库，必须串行。
- demo_v15 八源文件已 tracked（`4eddbb4`），`/demo_v15/` 忽略行保留（reports/pyc/新文件继续忽略）；`agent_demo_v15%` 残留库会让 gate 的 `DROP ROLE v15_owner` 失败——gate 前后清理。
- 仓库纪律：MUST NOT force-push main、历史只追加、push 拒先 fetch、分叉无法安全合并停下问用户；按路径 add、禁止 `-A`。

## 1. 合并方式裁决

| 候选 | 裁决 | 原因 |
|---|---|---|
| rebase | **拒绝** | 重写已推送的 v15 历史 SHA（`4eddbb4`/`890d3a1` 等已发布） |
| squash | **拒绝** | 丢失里程碑提交边界，无法证明「全部历史」进入 main |
| cherry-pick | **拒绝** | 手工挑序必遗漏，不留分支拓扑 |
| fast-forward | **拒绝** | main 有独立提交，且须保留双方历史 |
| **`git merge --no-ff --no-commit`** | **采用** | 双历史保留；提交前完成冲突解决 + 全量 gate + 收尾文书 |

合并提交信息：`v15: merge the v15 line into main`。第一父 = fetch 后的最新 `origin/main`；第二父 = 核对过的 v15 分支 tip。

## 2. 差异面实测（先于一切冲突裁决；评审已代跑 2026-09-30，执行时复核）

**实测事实快照（评审 F1–F15，执行时逐项复核不照抄）**：merge-base `e915e92` ✅；分支尖本地=远程=`4eddbb4` ✅；`4eddbb4`/`890d3a1` 是 tip 祖先 ✅；demo 恰八文件 tracked ✅；main 侧自基线后实数 **19 个提交**（非任务输入的 4——pi_ports×8、pi_parity×5、1 merge、long-loop 计划×4 等）；双方路径交集**仅 `.gitignore`**（main 侧未动 AGENTS/pyproject/uv.lock/server.py、未动任何 `v15/**`/`demo_v15/**`）；**`git merge-tree` 探针对 origin/main 与本地 main 均零冲突**（`.gitignore` 两侧行区不相交：main 尾部追加、分支中部插入）；本地 main `0b18d0a` **领先 origin/main 两个未推送 v13 提交**（`649b1f9`/`0b18d0a`，v13 long-loop Phase A，已完成待推）；main 检出于**主检出** `/Users/wxl/Projects/pg-agent`（本会话 worktree 检出的是 v15 分支——`git switch main` 在此必败）；无活动 hook。

```bash
git fetch origin --prune                                  # 网络为先决条件
git rev-parse origin/main rp/agent/3e700836-agent origin/rp/agent/3e700836-agent
git merge-base origin/main origin/rp/agent/3e700836-agent # 必须仍是 e915e92
git rev-list --left-right --count rp/agent/3e700836-agent...origin/rp/agent/3e700836-agent  # 0 0
git rev-list --left-right --count main...origin/main      # 非 0 0 → 先处理（见步骤 0）
git log --reverse --oneline e915e92..origin/main          # 实数记录（当前 19；v13 推送后 21）
git diff --name-status e915e92..origin/main
git diff --name-status e915e92..origin/rp/agent/3e700836-agent
comm -12 <(git diff --name-only e915e92..origin/main | sort) <(git diff --name-only e915e92..origin/rp/agent/3e700836-agent | sort)
git merge-base --is-ancestor 4eddbb4 origin/rp/agent/3e700836-agent && git merge-base --is-ancestor 890d3a1 origin/rp/agent/3e700836-agent
git merge-tree --write-tree --name-only origin/main rp/agent/3e700836-agent   # 冲突探针：零冲突则 §3 降级为应急预案
git log --oneline e915e92..origin/main -- .gitignore      # .gitignore 被 main 侧 4 提交分摊改动，逐提交 show 还原出处
git show --format=fuller --find-renames <每个 main 侧提交> -- .gitignore AGENTS.md pyproject.toml uv.lock server.py v13 v8 docs
```

判据：`v13/**`×`v15/**` 交集应为空；根级交集（当前仅 `.gitignore`）逐文件入表；**main 侧若动 `v15/**`、`demo_v15/**`、删 v15 路径或动 `SQL_LOAD_ORDER`——停止重估**。

## 3. 冲突解决规则

- **`.gitignore`**：语义并集——保 main 侧 v13 规则 + 分支侧 `/demo_v15/` 与其 tracked-source/ignored-artifact 注释；不加任何 reports/.env 例外。
- **`AGENTS.md`**：并集双侧纪律；保留 v15 两入口句、禁 `-A`/`--no-verify`/force-push 顺序纪律；v8 时代字面量（`v8/load.py`）非本次修正项。
- **`pyproject.toml`**：并集依赖 + 保留本地 pgembed/DuckDB source；删重复键不删一侧依赖；合并后 `uv lock` + `uv lock --check`；本地 source 缺失即停。
- **`uv.lock`**：生成物不手工挑行——先解 manifest，删冲突标记，`uv lock` 重生成，`--check` 验证，diff 只反映 merged manifest；`890d3a1` 钉作为历史保留，内容由重生成决定。
- **`server.py`**：无冲突留分支侧；冲突则保 PGDATA 语义/`get_server()` 封装/四命令，不建第二启动器；跑 `server.py status` + 受影响 gate。
- **docs**：异名共存；同名双侧改 → 保留双方事实不整文件覆盖；历史 plan/critique 的「当时未跟踪」句按历史处理不改写。
- **跨版本同文件冲突**（`v13/**`/`v8/**` 内同名文件被双侧改）：未定义 → `git merge --abort` 停止。

## 4. 合并执行（场地：本会话 worktree 切 integration 分支；不经 `git switch main`）

**步骤 0（排序前置，评审 §2.2）**：先把本地 main 领先的 2 个 v13 提交按其自身里程碑推送（`git -C /Users/wxl/Projects/pg-agent push origin main`；主检出须干净）——不推则 §7 的 ff 必在十道 gate 之后才炸，且普通 merge 会把无关 v13 提交卷进 v15 里程碑。推完后 origin/main=`0b18d0a`，重贴 §2 差异清单（实数 21、加 `v13/plan_arm/`、`v13/loop_driver/`）。

```bash
git switch -c integrate/v15-main-20260930 origin/main   # 在本会话 worktree；v15 分支尖已推送可离开
git merge --no-ff --no-commit origin/rp/agent/3e700836-agent
git diff --name-only --diff-filter=U                     # 预期为空（merge-tree 已证）；非空按 §3 应急解，未定义冲突 → --abort 停
git diff --check && git status --short                   # 无冲突标记；状态仅合并结果+预期收尾
```

推送采用 `git push origin integrate/v15-main-20260930:main`（普通推送即远程快进，**全程不动本地 main**）；成功后本地 main 的对齐留作主检出的后续动作（`git -C /Users/wxl/Projects/pg-agent merge --ff-only origin/main`，主检出干净时）。重跑路径：integration 分支已存在时先 `git branch -D integrate/v15-main-20260930` 或用 `-B`。

## 5. gate 全量重跑矩阵（合并树上、串行、全部实跑）

**前清理（阶梯）**：`env -u …UV_NO_ENV_FILE=1 uv run python demo_v15/db.py --drop-only` → 查 `agent_demo_v15%` 仍有残留时 `uv run python demo_v15/db.py --drop-only <库名>`（一次一库，`db.py:260-266`；发布期实际用过 harness/bound 两名）→ 仍残留才允许对 postgres 库 `DROP DATABASE … WITH (FORCE)`（仅终止该库连接，不 DROP ROLE）。清理失败不启动 gate。

| # | Stage | 命令 | 判据 |
|--:|---|---|---|
| 1–9 | schema→…→govern | `uv run python v15/<stage>/test_<stage>.py` | 各退出码 0 |
| 10 | provider | `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v15/provider/test_provider.py` | 退出码 0 |

- `git ls-files 'v15/**/test_*.py'` 先核对每 stage 的完整 gate 集（有多 gate 全跑）。
- **任一失败即停**：不更新「通过」文书、不提交；修复后**从 schema 重跑全十道**，不单跑失败 stage。
- **main 侧回归**：按 §2 差异面跑受影响 v13/v8 gate（改了 server.py/pyproject/uv.lock 则跑依赖它们的版本 gate）；无交集则记「无额外旧版本 gate」。
- **demo 复跑**（十道绿后）：fake drive（0 + `tail_ok relay_ok`）、keyless real（2 + `credentials_absent` 不建库）、`test_harness.py`（0）；**不跑带 key 的 real**。完毕 `--drop-only` + `git ls-files -- demo_v15` 恰八文件 + check-ignore reports/pyc 有输出。

## 6. 收尾工件（gate 全绿后才动）

1. 八个早期 stage README（schema/namespace/config/protocol/repl/io/loop/tree——评审实测恰 8 处「九」、均第 5 行同句）的「九个文件合运行时」陈旧表述改「十个文件」。**护栏**：`v15/README.md` 与 `v15/provider/README.md` 已是十文件不动；govern 的「九」在准确句里不动；只改文件数量与直接表述，不改 gate 行为、SQL 说明或 stage 边界。
1b. 合并后核对 `v15/load.py`：`SQL_LOAD_ORDER` 仍十项、provider 在末尾、无 v13 SQL 混入。
2. conformance matrix 文末追加 `Merge verification` 节：双方 SHA、merge SHA、十道 gate 退出码、旧版本 gate 与 demo 复跑结果、demo 库清理结果。不改 83 条既有条目、不把 demo 标成 gate。
3. deviation ledger 追加 merge verification：D01–D30 无增改、八源文件仍 tracked、reports 不入库、demo 未升级为 gate。不新增 V15-D。
4. 不改：历史 plan 正文、`v15-demo-tail-delegation-plan-critique`。

## 7. 提交与推送（单一合并提交 + 推送后 SHA 记录提交）

```bash
git diff --check && git diff --cached --check          # 无冲突标记
git ls-files -- demo_v15                                # 恰八
git add <按路径：合并结果 + 本计划文件 + §6 收尾文件>
git commit -m "v15: merge the v15 line into main" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
git rev-list --parents -n 1 HEAD                        # 两父：第一父=合并时 origin/main，第二父=v15 tip
git merge-base --is-ancestor 4eddbb4 HEAD && git merge-base --is-ancestor 890d3a1 HEAD
git push origin integrate/v15-main-20260930:main        # 普通推送；禁 force
```

**原子性**：冲突解、收尾文书、锁文件全部进**这一个**合并提交——不拆成代码/文书/锁多个提交，也不在 gate 前先提交。

**merge SHA 自指处理（裁决）**：matrix/计划进合并提交但只记双亲 SHA 与十道退出码，merge SHA 字段留「记录于推送后」；推送成功后**一个纯记录小提交**（`v15: record the main merge verification`）把实际 merge SHA 回填 matrix 与本计划 Run record——这是对「一里程碑一提交」的一句显式豁免（记录性文档提交，无行为变更）。

**推送后验证**：`git fetch origin` → `git rev-parse origin/main` == merge SHA → `git merge-base --is-ancestor origin/rp/agent/3e700836-agent origin/main` → 主检出干净时 ff 本地 main → 删 integration 分支。

推送被拒：fetch → origin/main 相对已测合并的第一父有新提交 → **弃旧 integration（`git branch -D` 后从新 main `-B` 重走 §2/§4–§7 含全量 gate）**；无法安全合并 → 停下问用户。回退已推送合并只能追加 revert commit。

## 8. 风险速查

| 风险 | 处理 |
|---|---|
| main 侧动了 .gitignore/AGENTS | 逐提交 `git show` 语义合并，禁整文件覆盖 |
| uv.lock 冲突 | manifest 先合、`uv lock` 重生成、`--check`；缺本地 source 即停 |
| demo 库残留挡 DROP ROLE | gate 前后查 `agent_demo_v15%` 并清 |
| gate 并行互删库 | 全部串行 |
| 测试期 origin/main 前进 | 弃旧 integration 重走全流程 |
| status 看不见 ignored 密钥/报告 | ls-files 白名单 + check-ignore + 形状扫描 |
| 第二个 pgembed 实例 | server.py 的 PGDATA 钉在文件父目录，每 worktree 一块 .pgdata——场地选已热的（本 worktree）；新实例起不来：记录原文停，不改 server.py 不杀另一实例 |
| 网络不通 | fetch/push 均需网络；gate 离线可跑但按计划顺序不可启动——后台重试模式恢复后执行 |

## References

- 发布计划：`docs/plans/v15-publish-demo-driver-plan-2026-09-29.md`（§3.9 本计划是其兑现）
- 仓库纪律：`AGENTS.md`；v15 十文件运行时：`v15/load.py`、`v15/README.md`
- 生成基线：oracle 组 `66A0921B`（codex 轨完整稿，grok/cursor 轨为异见参考）


## Run record（2026-09-30）

- 第一父 `0b18d0a`（2 个 v13 提交先独立推送）；第二父 `4b45dd8`；merge-base `e915e92`；main 侧实数 22。
- merge-tree 零冲突；实际合并零冲突自动并入；97 文件 staged；根级交集仅 `.gitignore`。
- `uv lock --check` 0；demo 库全清；十道 v15 gate 退出码全 0（合并树串行实跑）。
- v13 历史 gate（pi_ports G2 / pi_parity P0）：HEAD 钉死型清洁断言在当前 main 尖必红（其 HEAD^→HEAD 即含保护面改动），非本合并回归；合并对 v13/** 零改动，按可达性豁免。
- demo：fake 0 / keyless 2 / harness 0 / 库清 / 八文件白名单。
- merge SHA：db26c033d9a359305364737a6c1e876e5cb6e30c（推送后记录提交回填）。
