# RP 原生化·上下文收集设计 — Oracle 三轮裁决记录

> 日期:2026-09-21。通道:ask_oracle group(cursor:gpt-5.6-sol@xhigh + cursor:grok-4.6@xhigh)。
> 轮次:R1 独立评审 → R2 修改方案(双版) → R3 五点分歧裁决 → 用户拍板两项。
> 本文件是裁决存证;合成结论以 `repoprompt-native-on-v13-feasibility-v2-2026-09-21.md` 为准。

## 轮 1 · 独立评审(grok-4.6 交付;gpt-5.6-sol 通道中断——用户痛点的现场复现)

**总裁决:现状不能冻结为 v13.2 R0/R1/R6 起点;动态三表+加速环不准进 R0。**

对自评 12 条的裁决:确认 9、降级 2(混代 P0→P1、签名缺模型维 P1→P2)、升级 1(sweep 触发 P2→P1)。
确认总批评,并加码:「优化器底下的身份、论域、锁三件也没焊住——问题不只是缺遥测。」

**Oracle 独立新发现的三个 P0**(双方此前均未立法):

1. **字节没冻结**:stat 是失效启发式不是身份;同 size 同 mtime 改内容 ⇒ exact replay 读到不同字节,ch01「模型可见 ⟺ 已落行」被文件面废掉;
2. **开放世界论域**:存在性 Noul 的闸语义是「封闭语料里没有」;惰性注册语料是开放子集,Noul 答 no 会被当成「仓库无答案」;
3. **锁内读盘**:可行性 v1「read_file/tree=sql 快路、advance 同事务」直接违反 G-ctx1。

另发现 P1 六条:动态重组与 latch 未和解、可见性三门无合成代数、跟踪集三种群未定义、
生成物回写后两张脸塌缩、file→chunks 无准入(IDF 稀释)、est_tokens 推迟到装配后。

三题解法:首英里 = 路线 A(确定性名字先验)+ C(search-first 注册环)为主、
B(显式 bootstrap)为策略行重路径;混代 = source_epoch + 装配期 skipped(不读盘);
CJK = G-cjk-file 对照门(召回 canary / 排除安全 / on-off 对照 / 花费对照)。

## 轮 2 · 修改方案(双版交付)

两版骨架完全收敛:**七条不变量 I-file-1…7、R0 只做静态 workspace+收据表、
三类 effect(file_register/file_search/corpus_bootstrap,全部 mutating=false)、
v13_visible_tools 单源代数、首英里 A+C、G-cjk-file、动态三表后置并附放行条件。**

差异五处 → 进轮 3 裁决(见下)。

七条不变量(两版一致,I-file-4 经轮 3 D3 微调):

1. **I-file-1 身份与冻结**:模型可见身份 = (ws_id, canonical_path, content_hash);stat 只是失效启发式;进 manifest 的字节必须已冻结为 artifact;exact replay 只解冻旧 hash;
2. **I-file-2 开放世界**:bootstrap_done=false 期间禁止对 file corpus 发存在性 Noul;no 不得短路为「仓库无答案」;封闭只许 corpus_bootstrap 成功结算打开;
3. **I-file-3 注册即出境**:秘密扫描+准入同一道门,fail-closed,在路径树上执法;生成物默认 corpus='generated' 不进源文件 IDF 池;人 veto 高于超集;
4. **I-file-4 FS IO 全 effect**(轮 3 改写):「发现与注册必须在数据语义、授权 gate 和审计记录上分离;不强制拆成两个 effect。复合 effect 只有在目录合同明确声明、使用冻结策略版本、全部可见写入发生于 fenced settle 时才合法」;
5. **I-file-5 单源可见性**:v13_visible_tools(p_sid) 唯一合取(tools.enabled ∧ wb 活跃 ∧ ws.tool_scope);v13_wb_visible_tools 并入;
6. **I-file-6 三种群与 veto**:head/dirty/untracked 分列;untracked 单独授权;deselect 是确定性 veto,超集不得加回;禁止按 ws 硬切非 file 语料(§4.4 三分保留);
7. **I-file-7 冷启动契约**:新 ws 首 advance 建 names_prior effect 并 waiting;bootstrap_done=false 期间禁 LLM effect;禁止 Jev 决定「要不要全库扫」。

## 轮 3 · 五点分歧裁决

| 点 | 双方裁决 | 收敛度 |
|---|---|---|
| D1 收据表 | 都裁「合成:receipts 只追加日志 + workspace_files 当前指针」;gpt 留第三张 file_source_epochs 状态机,grok 拒(effects.status 换皮,YAGNI) | 部分 |
| D2 探针键 | 都收敛:维持 DP1 七键;workspaces DML bump tools_revision + 分型审计事件;grok 当场撤回第二轮的 ws_revision 主张 | ✅ |
| D3 白皮书 | 都收敛:bootstrap 复合 effect,worker IO + 单笔 fenced settle ≤10 白皮书;search-first 仍禁同 turn;残差=waiting 措辞 | ≈✅ |
| D4 hits | 都取 B:search_hits 不可变 artifact 差集 + v13_search_hits_remaining 视图,每 turn ≤32,零准队列 | ✅ |
| D5 混代 | 都同意热路径零盘 + 装配期 mixed_vintage + fork 冻结;残差 = HEAD 住哪(tips 单行 vs epoch 行)+ epoch 是否进 candidate_set_hash | 部分 |

D1/D5 残余互相耦合(三层配 gpt-D5,两层配 grok-D5)→ 合并为一个结构决策呈用户。

## 用户拍板(2026-09-21,ask_user)

1. **D1+D5 文件平面结构:两层 + 发布检查函数**——file_receipts(只追加)+ workspace_files(指针)+ workspace_git_tips(单行 HEAD);epoch 三态用 effects.status 表达;发布完整性=确定性检查函数;epoch 不进 candidate_set_hash;
2. **D3 waiting 契约:p95 ≤ 1 保持**,且包含白皮书冻结。

## 最终合成口径(五点)

| 点 | 最终结论 |
|---|---|
| D1 | 两层:file_receipts 只追加(settle INSERT,含失败尝试)+ workspace_files 指针(PK=ws+path+population,同 settle UPSERT;热路径只读指针);不变量:每行指针存在同批同值收据;GC 靠引用可达性(blob 可收 iff hash 不被指针/manifest/水位引用);不建 epoch 状态机 |
| D2 | 七键不动;workspaces 作用域列 DML → tools_revision bump(statement-level AFTER 触发器,与 workbenches 同构)+ events 追加 type='ws_scope_changed'(payload:ws_id/变更列集/新旧 revision);审计归因靠分型事件,不靠探针键 |
| D3 | names_prior 为复合 effect:worker 枚举名字收据 + 白皮书闭集(策略行字面量,硬顶 10,命中才读)同一套扫描/准入/artifact/chunks/指针;扫描器不可用=整单 failed fail-closed;G-file-cold p95 ≤1 含白皮书;search+register 同 turn 仍红 |
| D4 | search_hits 不可变内联 artifact(去重+确定性排序+hit_ordinal);剩余=差集查询 v13_search_hits_remaining(视图非表);child effect_id 由 content_hash+epoch+ordinal 集+策略版本稳定推导;崩溃语义:差集按指针终态,不按 artifact 光标 |
| D5 | workspace_git_tips(ws_id PK, git_head, observed_at, source_effect_id)由任何观察过 git 的 effect settle UPSERT;混代判定在变更相纯 SQL(候选 distinct source_epoch>1 且跨文件 → 整批 skipped/mixed_vintage + 建重注册 effect,路径=表内 stat 变化 ∪ 已落库 name-diff);禁止 epoch/HEAD 并入 candidate_set_hash;fork 时 files_cutoff={tips.git_head, worktree_id:null, max(pointer.source_epoch)} 冻结 |
