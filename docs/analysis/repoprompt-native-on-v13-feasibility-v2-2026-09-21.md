# 基于 v13 原生仿制 RepoPrompt-CE:可行性报告 v2(文件与上下文收集平面)

> 日期:2026-09-21。**v2,取代 v1**(`repoprompt-native-on-v13-feasibility-2026-09-21.md`)。
> 新增输入:Claude 会话设计稿 + 自评 12 条
> (`docs/reviews/repoprompt-native-context-plan-review-by-claude-2026-09-21.md`)、
> Oracle 三轮裁决(评审/方案/分歧裁决,
> `docs/reviews/repoprompt-native-context-oracle-r1-r3-2026-09-21.md`)、
> 用户两项拍板(文件平面两层 + waiting p95≤1)。
> 结论不变:**go;主体仍是 v13 底座**。v2 修订的是「收上下文」链路:
> v1 的三处字面合同作废,新增七条不变量与 R0/R1/R6 的重构范围。

## 0. v1 的三处 Erratum(先行声明)

| v1 原文 | 作废理由 | v2 修正 |
|---|---|---|
| §2「read_file/get_file_tree/get_code_structure = sql 快路、advance 同事务」 | 违反 G-ctx1(锁内 IO);ch01 被文件面废掉 | 快路 = **读已冻结行**;任何 live FS 读 = effect |
| §2/§5 R6「workspace_context 近零新件」 | 接线近零成立,收集平面是新承重件 | 「装配/渲染近零新件;**收集平面必须先于接线存在**」 |
| §5 R1「只读工具族 sql 快路(默认行读真 FS)」 | 同第一处 | R1 = 三类 effect + 已冻结行上的快路读 |

四句封面纪律(v2 全文有效):
**动态选择链不是 R0;stat 不是身份;惰性子集不是封闭语料;读盘不是 sql 快路。**

## 1. 七条不变量(I-file-1…7,与 v13 §4.3 / ch01 同级)

1. **I-file-1 身份与字节冻结**:模型可见的文件身份 = `(ws_id, canonical_path, content_hash)`;
   stat(mtime,size) 只许当「要不要发重读 effect」的失效启发式,禁作身份/缓存键/replay 键。
   进 manifest/render/exact replay/出站请求的字节必须已冻结为 `kind='file'` artifact;
   exact replay 只解冻当时 context artifact 所记 hash。
2. **I-file-2 开放世界论域**:`bootstrap_done=false` 期间禁止对 file corpus 发存在性 Noul;
   「已注册子集是否足够」的 no 不得短路为「仓库无答案」;封闭只许 `corpus_bootstrap`
   成功结算打开,且绑定 `(ws_id, corpus_epoch, files_cutoff, secret/admission policy 版本)`,
   任一变化即失效。
3. **I-file-3 注册即出境**:秘密扫描+类型/大小/deny glob 准入是同一道注册门,
   fail-closed,且在**路径树**上执法(秘密路径即使未读正文也不得进 tree/快路/manifest)。
   生成物(`produced_by` 非空)默认 `corpus='generated'`,不进源文件 IDF 池;
   人 deselect 是确定性 veto,优先级高于一切超集。
4. **I-file-4 FS IO 与事务边界**(轮 3 改写):所有 FS/git IO 发生在 effect worker;
   parse/advance/recall/visibility/manifest/render 只读已冻结行。
   「发现与注册必须在数据语义、授权 gate 和审计记录上分离;**不强制拆成两个 effect**。
   复合 effect 仅当目录合同明确声明可产文件收据、使用冻结策略版本、
   全部可见写入发生于 fenced settle 时合法。」
5. **I-file-5 单源可见性**:模型可见、advance 可建 effect 的工具集只来自
   `v13_visible_tools(p_sid)` = `enabled ∧ (wb IS NULL ∨ wb∈active) ∧ name ∈ ws.tool_scope`;
   v13.1 的 `v13_wb_visible_tools` 并入此函数,不得并列。
6. **I-file-6 三种群与 veto**:head/dirty/untracked 分列,禁止同 section 静默混排;
   默认跟踪集 = head ∪ 显式 selection,untracked 单独授权;脏文件只以带标记的
   覆盖 section 出现;veto 由事件折叠(`v13_file_vetoes(p_sid)` 单源函数),
   T0/过滤/装配/bootstrap 一律不得加回;§4.4 语料三分保留,禁止按 ws 硬切非 file 语料。
7. **I-file-7 冷启动契约**:新 ws 或名字表空时,首次需要仓库上下文的 advance
   建 `corpus_bootstrap(mode='names_prior')` 并返回 waiting,**不得同时建 LLM effect**;
   p95 waiting ≤ 1(含白皮书冻结,用户拍板);失败不置 bootstrap_done,
   耗尽进 blocked_unknown;禁止 Jev 决定「要不要全库扫」(容量问题,§6.2 触点 3)。

## 2. R0(立法 + 静态作用域 + 两层收据表)

### 2.1 冻结清单

- **静态 `workspaces`**:`ws_id, prompt_ref, model_policy, render_policy, memory_corpora
  (boost 非硬切), tool_scope(闭集,空=fail-closed 无工具), write_grant(R0 留列),
  bootstrap_done, corpus_epoch`。session 引用后语义列禁原地 DML;
  变更 = 新版本/fork。**无 ws 选择 Noul、无动态组件**(spawn 时确定性规则定)。
- **sessions 增列**:`ws_id NOT NULL`;`files_cutoff jsonb {git_head, worktree_id,
  max_file_epoch}`(spawn/fork 时冻结;fork 复制父值)。**不加 ws_revision**(D2 裁决)。
- **两张文件表(两层,D1 裁决)**:
  - `file_receipts`(只追加,触发器拒 UPDATE/DELETE,与 events 同形):
    一行=一次路径级尝试(含 name-only/blocked/skipped/clean)。
    关键维:`(ws_id, normalized_path, population, register_batch_id)` + `content_hash`(可空)
    + `source_epoch` + `scan_status` + `skip_reason` + `est_tokens` + `git_head`
    + `stat_*` + `effect_id` + `at`。**热路径不 join 此表**。
  - `workspace_files`(当前指针):PK=`(ws_id, normalized_path, population)`;
    `content_hash/source_epoch/register_batch_id/scan_status/est_tokens/chunked`;
    `content_hash IS NULL` 禁进 recall/manifest/render。
    **不变量(gate 一句):每行指针存在同批同值收据;违约即双源。**
- **`workspace_git_tips`**(单行/工作区,D5 裁决):`ws_id PK, git_head, observed_at,
  source_effect_id`;仅观察过 git 的 effect settle UPSERT;热路径只 SELECT。
- **veto**:`type='file_deselect'/'file_select'` 事件折叠 + `v13_file_vetoes(p_sid)` 单源。
- **发布检查函数**:确定性检查(某 register_batch 的 expected 路径全部终态 ∧
  passed 均已投影 → 允许翻 `bootstrap_done=true, corpus_epoch+=1`);advance 调用,
  零 FS IO。不建 epoch 状态机(building=effects.claimed,published=settle 提交,
  aborted=failed 且指针未动)。
- **探针(D2 裁决)**:workspaces 作用域列 DML → `tools_revision` bump
  (statement AFTER 触发器,与 workbenches 同构)+ events 追加 `type='ws_scope_changed'`
  (payload: ws_id/变更列集/新旧 revision)。**对 DP1 零结构增量。**

### 2.2 后置清单(不准进 R0)

动态三表(components/instances/patterns)、逐组件 Noul、ws 选择 Noul、
`full_tree` 作为冷启动唯一门、tigerfs 常驻镜像/迁移桥、锁内读盘(永不)、
按 ws 硬切非 file 语料(永不)。放行条件见 §6。

## 3. R1(发现 + 注册 + 搜索,全部走账本)

### 3.1 三类 effect 目录行(`kind='tool'`,handler='fs',mutating=false)

| 工具 | 调用者 | param_spec(冻结) | 产出 |
|---|---|---|---|
| `file_register` | system(SQL 派生) | `paths[]≤32, population_default, register_batch_id`;allowlist=根+字节帽+deny glob+secret_profile_version | settle:INSERT receipts + UPSERT 指针 + artifact + chunks 重摄取(§4.2) |
| `file_search` | model+system | `query(受限编译), scope∈{path,content,both}, max_hits≤200` | 不可变 `kind='search_hits'` artifact(去重+确定性排序+hit_ordinal);**发现工具,不是 T0**;命中 secret 路径只回计数不回字符串 |
| `corpus_bootstrap` | system | `mode∈{names_prior,full_tree}`(full_tree 默认关,策略行开) | names_prior:名字收据+白皮书闭集(**复合 effect,D3 裁决**:白皮书=策略行字面量,硬顶 10,命中才读,worker IO+**同一笔 fenced settle** 走与 file_register 同一套门);full_tree:分片扫,最后一片成功才置 bootstrap_done |

失败分类:`SOURCE_EPOCH_STALE`(可重试)/`SECRET_REJECTED`(终态,不可见)/
`ADMISSION_REJECTED`(确定性终态)/`DIRTY_SNAPSHOT_REQUIRED`(blocked_unknown)/
worker 崩溃(lease 重领,幂等靠 effect_id+指针 PK+hash 去重)。

### 3.2 首英里 A+C(状态机)

```text
spawn(ws) → 名字表空、bootstrap_done=false
→ parse: 无 file 存在性 Noul
→ advance: 建 names_prior → waiting(唯一 effect,无 LLM)
→ settle: 名字收据 + 白皮书冻结(≤10)
→ 下一 parse: 白皮书可召回;仍开放世界
→ 深文件: 已知路径→确定性 SQL 建 file_register;
          未知路径→file_search → (下一 turn) hits−veto−已终态 前 32 → 一个 file_register
→ hits>32: 分 turn 消化,剩余= v13_search_hits_remaining(p_sid)(差集视图,非表,D4 裁决)
→ 装配只 applied: content_hash 非空 ∧ clean ∧ ¬veto ∧ epoch≤cutoff
```

白皮书名集:`README*, AGENTS.md, pyproject.toml, package.json, go.mod, Cargo.toml,
composer.json, Gemfile`;热路径近 20 commit 去重 ≤50 条只写名字;条目帽 500,
超帽 `skip_reason='prior_cap'` 不静默当全库。

### 3.3 `v13_visible_tools` 单源

替换 needed 的 tool map 读法、advance ④、v13.1 `v13_wb_visible_tools`。
wb 表不存在时该项恒真(R0 可先于 v13.1 加载)。文件侧对应
`v13_visible_files(p_sid, epoch, cutoff)`:recall/tree/read/manifest 共用。

## 4. R6(manifest 接线;装配/渲染近零新件)

manifest 根增:`ws_id, files_source_epoch, files_cutoff, bootstrap_done,
secret/admission_policy_version`。file section 增:

```
kind='file'; content_hash+payload_ref(非路径); est_tokens(注册时写入,禁装配期现估)
ws_id/normalized_path/population/git_head/source_epoch/receipt_id
replay=exact|recompute|fresh; applied|skipped+reason
skipped 闭集: mixed_vintage/veto/blocked_secret/admission/budget/open_world_no_body/stale_stat
```

装配(变更相纯 SQL):候选=已冻结∧clean∧¬veto∧epoch≤cutoff;
跨文件候选 distinct source_epoch>1 → **整批 skipped/mixed_vintage** + 建重注册
effect(路径=表内 stat 变化 ∪ tips/收据上已落库的 name-diff,**零 FS 调用**);
超窗 → skipped/budget。render 只读 artifact bytes;三种回放显式标注。
RP-CE 映射:selection=事件折叠∩¬veto;slices=冻结 body 上的区间;
presets=render 策略行;export=render→kind='export'(不回流 file 语料);
snapshot/tree=已落行 SELECT;tokens=Σest_tokens。

## 5. Gate 清单 v2(`uv run python v13/<stage>/test_*.py`,0=绿)

| Gate | 断言要点 |
|---|---|
| G-file-id | 同 size 同 mtime 改字节:旧 replay 逐字不变;新字节仅经新 epoch 注册后可见 |
| G-file-replay | exact 不发 FS effect;recompute 允许 register;fresh fork 新 cutoff;把重读 FS 标 exact→红 |
| G-file-open | bootstrap_done=false 时 file 存在性 Noul 计数=0;子集不足的 no 不短路整批 |
| G-file-secret(+veto) | .env/*.pem/密钥正文:blocked、无 chunks、无路径无正文;扫描器挂=整批 failed 无假 clean;deselect 的秘密路径不被超集/bootstrap 加回(违=P0) |
| G-file-admit / G-file-gen | deny glob 只有 skipped 收据;IDF 行数不因 deny 暴涨;export 落盘被扫→corpus='generated' 不进源 IDF 池 |
| G-ctx1-file | 锁内注入慢 FS:events INSERT 照常;锁内 open/stat/git 探针计数>0→红 |
| G-file-vis | 只翻 tool_scope/wb/enabled 各变一处;needed=advance=函数输出;无第二份过滤 SQL |
| G-file-pop / G-file-veto | head 与 dirty 两行两 hash;untracked 无授权拒注册;deselect 后 T0 不召、装配 skipped=veto |
| G-file-cold | 新 ws 首_advance=names_prior+waiting,LLM effect=0;重复拨动不重复建;p95 waiting≤1 含白皮书;失败不置 done |
| G-file-ac | 零收据 fixture:仅文件名/中文路径/正文 symbol 命中→seed→search→register→recall 全链,零依赖既有 recall;search+register 同 turn→红;hits>32 分 turn |
| G-file-vintage | 两文件两 epoch+跨文件→零 applied(mixed_vintage),本相 FS syscall=0;重注册路径集=stat 变化∪已落库 name-diff |
| G-file-est | 仅 size 的文件 est_tokens>0 保守上限;超预算→skipped/budget;无 prompt-too-long 进 R_o |
| G-file-regret | manifest 后 file_search/read 分型落审计:unregistered/registered_miss/prewrite_reread;缺分型→红 |
| G-file-boost | 同 ws 内 document 命中不因 file 分区从 T0 消失;跨 ws 默认不可见 |
| G-file-cutoff / G-file-recovery | 迟到/乱序 receipt 不越 cutoff;freeze 后加收据不改 manifest hash;各边界 kill:未发布不泄漏、重试单 cutoff、无重复出境 |
| **G-cjk-file** | 召回 canary(中英混合源码/纯中文 md/中文查询→英文标识符);must_include∩skipped=∅;on/off 全 CJK fixture 全等→标 cjk_filter_noop **红**(禁把过滤写成已交付省 token 能力);hit_rate<英文−δ 且 tokens 无降→红;含「CJK 恒低分」毒化档 |

## 6. 动态 workspace 三表:后置与放行条件(不准进 R0/R1/R6)

放行前提(全部满足,另开设计修订+L4):
1. I-file-1…7 已进冻结设计文;G-file-id/open/ctx1-file/secret/cold/ac/vintage/vis 全绿
   且 DP1 基线复跑 G-ctx1;**G-cjk-file 全绿**(否则禁承诺「组件 Noul 省 token」);
2. 实测(本地 fixture 仓,数字进 gate):names_prior p95 waiting≤1;
   search-and-register 深文件 p95 额外 waiting≤2;持锁 p99 达 G-ctx1 预算;
   开放世界期间 file 存在性 Noul 调用率=0;
3. latch(DP8)已落地——动态 compose 必须先回答身份问题;
4. 静态基线:≥200 成功 repo-context turns、≥5 仓、≥50 CJK turns、
   秘密泄漏/混代/veto 违反=0;shadow planner 覆盖含 ≥30 开放集任务;
5. 相对静态基线:gold recall 降幅≤2pp、critical 零丢失、p50 输入 token 降≥15%、
   真实 E(r) 成本降≥10%、cache 命中降幅≤3pp、装配 p95 增量≤100ms;
6. 经济学闸:重组预计节省须覆盖 Jev 调用+cache-break 成本,净收益率≥10%。

放行时四处强制修改:签名+`(provider,model)` 维;组件槽闭集(≤4)且 Noul 与
固定五问/wb/tool **合计** ≤1 批(≤32),超出走慢路;`ws_deferred` 守卫
(与 wb_deferred 同形,同 hash 二次 deferred=gate 失败);compose/模式晋升=身份变更
——本 session 组件组合写 latch(INSERT-once),再换必须 fork;pattern flip 只产新
策略版本且只作用于新 session/fork;零 diff N turn 只证一致性,**禁写成质量**。

## 7. 与既有裁决的冲突登记(轮 3 后更新)

| 对象 | 处置 | 性质 |
|---|---|---|
| ch07「文件=artifacts」 | 增量澄清:人侧真相=FS+git;**模型侧**=artifacts。tigerfs 维持建议 A(可删视图),翻案须独立 erratum | 澄清非翻案 |
| ch01「模型可见 ⟺ 已落行」 | 增量适用到文件字节 | 无冲突 |
| v13 §4.2 chunks 重摄取 | file 面改 append-only 收据;旧 blob 被 manifest 引用时不可 GC | **erratum** |
| v13 §4.5 存在性 Noul 先行 | 增加论域条件:仅 bootstrap_done=true 后先行 | **erratum(论域)** |
| v13 §4.3 / G-ctx1 | 增量适用到 FS/git(零锁内 IO) | 增量 |
| v13 §4.4 语料三分 | 保留;新增 corpus='file'\|'generated';禁 ws 硬切 | 增量 |
| v13 §6.7 / §6.2 触点 3 | 遵守:全库扫触发禁 Noul | 遵守 |
| DP1 探针七键 | **轮 3 后:零结构增量**(D2 收敛);workspaces DML 走 tools_revision+分型事件 | 增量(原 gpt 版第八键已撤) |
| v13.1 v13_wb_visible_tools | 并入 v13_visible_tools(单源) | v13.1 增量替换 |
| v13.1 不变量 5(duck 只读) | 不触碰;写面仍 R3/B005 | 无冲突 |
| 可行性 v1 三处 | §0 表格 | **erratum** |
| 会话稿动态三表+加速环 | 拒入冻;放行条件 §6 | 后置 |

## 8. 实施顺序(替换 v1 §5 的 R0/R1/R6 行;其余 Phase 结构不变)

1. **R0a**(与 DP1 加载序协调):workspaces+sessions 增列+两张文件表+tips+
   veto 函数+七不变量立法。Gate:表约束/不可变/空语料开放世界。
2. **R0b**:`v13_visible_tools` 单源;needed/advance 改读。Gate:G-file-vis。
3. **R1a**:目录三行+FakeFs worker+names_prior+白皮书。Gate:G-file-cold/ac/ctx1-file。
4. **R1b**:file_search+差集消化+file_register 全门。Gate:secret/admit/pop/veto/est/regret。
5. **R1c**:tips+混代代数。Gate:G-file-vintage。
6. **R6**:manifest 字段+三回放+render 只读 hash。Gate:G-file-id/replay/boost。
7. **G-cjk-file**:可与 R6 并行;**声称过滤省 token 之前必须绿**。
8. `full_tree`:独立提交,默认关,不与 R1a 冷启动绑死。

原子组合(必须同提交):R0a 的 DDL+I-file 立法;R1a+G-ctx1-file;
G-file-secret+第一版 file_register(无门的注册=出境事故)。

---
**v2 封面句**:先冻论域、字节、锁,再谈组件与加速。R0/R1/R6 之上,
Phase 1(v13 底座 DP1–DP8)与 Phase 2(v13.1 M1–M5)不变,仍是工程主体。
