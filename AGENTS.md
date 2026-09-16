# AGENTS.md — pg-agent 开发约定

本文件是仓库级约定，适用于所有在 `/Users/wxl/Projects/pg-agent` 下工作的人与 agent。

---

## 里程碑完成后必须提交并推送

**规则：完成计划中的一个里程碑、且该里程碑的全部测试通过后，MUST 立即提交代码并推送到远程仓库。MUST NOT 把多个里程碑积压到一次提交。**

### 什么算一个里程碑

- 计划文件位于 `docs/plans/*.md`；里程碑 = 计划正文划分的 stage / gate。
  例：`v8-native-lifecycle-plan-2026-09-16.md` 的 G6 / G7a / G7b / G7c / G8a / G8b / G9a / G9b；
  `flock-rag-on-duckdb-final-plan-v4.1.md` 的 Phase 0。
- 一个里程碑一次提交。不要顺手把无关工作区的改动卷进同一次提交。

### 前置条件（缺一不可）

1. **测试实际跑过且全绿。** v8 的 gate 运行方式（仓库根，退出码 0 = 通过）：

   ```bash
   uv run python v8/<stage>/test_<name>.py
   ```

   同一 stage 的**全部** gate 都要跑，不只是新写的那个（防回归）。
2. **该里程碑的收尾工件已更新**（计划正文的硬性要求，不是可选项）：
   - 新增 SQL 已追加进 `v8/load.py` 的 `SQL_LOAD_ORDER`；
   - `docs/reviews/<version>-conformance-matrix-*.md` 覆盖矩阵已更新；
   - `docs/reviews/<version>-deviation-ledger-*.md` 偏差台账已更新；
   - 对应 stage 的 `README.md` 已更新。
3. **没有把未完成的工作当成完成。** gate 红就是红，先修再提交。MUST NOT 在没有实跑的情况下声称 gate 通过。

### 提交

```bash
git status                    # 先看清工作区
git add <按路径逐项添加>        # MUST NOT 用 `git add -A` / `git add .`
git status                    # 再看清暂存区
git commit -m "<版本>: <祈使句摘要>"
```

- 提交信息沿用仓库既有风格 `<版本>: <祈使句摘要>`，例如
  `v6: add DuckDB-side agent runtime (ingress, tools, queue bridge, budgets)`。
  摘要写「做了什么」，不写「修好了 bug」。
- **MUST NOT `git add -A` / `git add .`。** 工作区长期并存多条并行线的未跟踪文件（`.DS_Store`、`.spike-flock/`、其他版本的 docs 与 review），全量添加会把无关工作卷进里程碑提交。按路径逐项添加。
- 提交前用 `git status` 复查暂存内容。**发现任何疑似密钥/凭据的文件（`.env`、含 API key 的配置、`mineru.json` 之类）一律不提交** —— 即使文件名看起来无害，也要打开确认内容。
- MUST NOT 用 `--no-verify`，MUST NOT 跳过 hook。hook 失败要修根因，不要绕过。

### 推送

```bash
git push origin main
```

- 当前远程：`origin` = `https://github.com/wuxianliang/pg-agent.git`；工作分支 `main` 跟踪 `origin/main`。
- **MUST NOT force-push `main`**（`--force` 与 `--force-with-lease` 都不行）。历史只追加。
- push 被拒（远程有新提交）时：先 `git fetch origin` 看差异；需要时 `git pull --rebase origin main` 后重推。**MUST NOT 用 force 或 `reset --hard` 去「解决」分歧。**
- 若远程已分叉且无法安全合并：**停下来问用户**，不要自作主张。

### 顺序（不可颠倒，失败即停）

```
测试全绿 → 更新收尾工件 → git add（按路径）→ git commit → git push
```

任何一步失败就在那一步停下，不要跳到下一步，也不要用降低标准的方式「让它过去」。

---

## 其他既有约定（勿违反）

- **外部 IO 一律不进数据库事务**（v8 不变量 4）。测试用 FakeLLM / FakeTool，不调真实 provider。
- 测试是独立可跑脚本（`uv run python ...`，退出码 0 = 通过），不是 pytest 套件。每个 stage 的 `setup_db.py` 会 DROP/CREATE 自己的库，并按 `v8/load.py` 的 `SQL_LOAD_ORDER` 累计加载全部已注册 SQL。
- 规格原文是唯一权威（`docs/designs/v8-dev.md`），`docs/analysis/v8-impl-digest/` 只作入口摘要。任何改动 MUST NOT 破坏既有 gate。
- `prompt-exports/`、`.pgdata/`、`.venv`、`/memory` 已在 `.gitignore` 中，不要提交。
