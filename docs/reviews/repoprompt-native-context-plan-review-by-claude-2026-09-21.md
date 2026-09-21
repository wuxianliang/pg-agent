# RP 原生化·上下文收集设计(会话产物)与已知批评 — Claude 自评

> 日期:2026-09-21。性质:会话设计产物摘要 + 作者自评,**未冻结**。
> 用途:供 Oracle 独立评审。冻结底座见 `docs/designs/v13-context-on-pg.md`(已选入)。
> 请先独立批评(当作没看见 §3),再逐条裁决 §3 的 12 条,最后严重度排序。

## 1. 评审对象:会话新增设计摘要

以下均为 2026-09-21 会话中口头设计、尚未写入任何设计文档的内容。

### 1.1 文件平面:「一真相,两张脸」

- **源文件**(用户仓库):真相 = 真 FS + git。v13 只记**收据**:`kind='file'` artifact,
  stat(mtime,size) 作缓存键,**惰性注册**(selection/任务驱动,没被选的不进 PG)。
- **生成物**(export/oracle 产物/diff/报告):真相 = artifact 行本身,不经文件形态。
- **tigerfs 定位**:可删视图——data-first 挂 v13 库做可观测路径面(人/外部工具);
  迁移期作桥(RP-CE 零改动,export 落挂载点,ingester 扫描投影成 artifacts)。
  判据 G-drop-mount:卸掉挂载全链照绿。
- **bulk sweep**:按需批量摄取投影(全库视野),水位 = git HEAD + 已注册 max(stat),
  可重建、幂等重跑。触发:任务需要全库视野/git hook/pg_cron。
- **拒绝的替代**:tigerfs 常驻镜像当真相(两店 CAS + 同步义务 + git 打架);
  duck 插件碰文件系统(`enable_external_access=false` 焊死,内容即值)。

### 1.2 workspace 统一(R0 决策,先于 R1)

```sql
workspaces(ws_id, prompt_ref, model_policy, render_policy,
           memory_corpora, tool_scope, write_grant)   -- 作用域定义
sessions.ws_id -- 外键;一对多
```

Zleap 公式 `Context = Sys + WsPrompt + Tools + Memory + History` 的 v13 表达:
manifest 每个 section 的来源都被当前 session 的 ws_id 过滤。
**与 workbenches(v13.1 执行平面)严格分离,不合并**;切换只发生在 fork/latch 边界。
路由:任务元数据→ws 用确定性规则 SQL 短路优先,真不确定才问 Jev(wb 族同型 Noul)。

### 1.3 动态 workspace(三表 + 选择链 + 加速环)

```sql
workspace_components(component_id, slot, version, content_ref,  -- prompt 文本=artifact 引用
                     capabilities, requires, enabled)            -- ASCII 能力卡
workspace_instances(ws_inst_id, session_id, turn_no, signature, -- append-only 收据
                     components jsonb, compose_policy, manifest_ref)
                     -- components={slot:{id,ver,decision_id|rule_id|'reused'}} 全溯源
workspace_patterns(pattern_id, version, signature_pattern, bundle,
                   evidence, status)                             -- draft→shadow→active→retired
```

- **签名** = hash(goal_hash × intent 类别 × 需求 artifact kinds × 域标记),
  **不含自由文本**(自由文本只进 Jev state)。
- **三级选择链**:①同 goal 沿用(零调用,护前缀缓存)→ ②模式规则短路(SQL 零 Jev)
  → ③Jev 逐组件存在性 Noul(只裁不确定带;Choice/组合置信度被拒,§6.7)。
  组装动作永远在 SQL(thresholds 带 + advance 路由)。
- **加速环**:instances 收据(自带 token/结局/开销原料)→ LLM 离线总结(worker,
  非 Jev——生成是 LLM 地盘)→ patterns draft → shadow 双跑 diff manifest
  → 零 diff N turn → flip active(版本化可回滚,永不在线学习)。
- **模型分工**:Jev 裁不确定性付发现税,LLM 管生成与压缩,SQL 永远握方向盘。

### 1.4 workspace_context 映射(RP-CE 仿制)

selection(人工策展)= 事件折叠投影;codemap = AST 签名投影视图;slices =
manifest section 行区间;presets = render 策略行;export = render(manifest,
policy, provider) 纯函数 → kind='export' artifact。快照视图 = sql 快路纯 SELECT。

### 1.5 主环共识图(骨架,评审基准)

进是一行(events)→ 两阶段 advance(parse:recall/resolve 不碰会话锁;
advance:水位复核/ws 组装/manifest/路由/预算,毫秒级持锁)→ effect 行 + 门铃同事务
→ worker 无状态三步合同(claim/IO 零事务/settle fence CAS)→ 回是一行(effect_done)
→ 引擎再拨。恢复 = SELECT 重建;队列/挂载/worker 全部可删可换。

## 2. 收上下文的链路定义(批评的靶子)

```text
① 发现(什么进语料) → ② 注册(读流/stat/秘密?) → ③ 投影(chunks/corpus 分区)
→ ④ 召回(recall T0/T1) → ⑤ 过滤(存在性 Noul + per-chunk Score)
→ ⑥ 装配(manifest/ws 组装/render) → ⑦ 回流(记忆投影/模式加速)
```

## 3. 已知批评(作者自评 12 条,待 Oracle 裁决)

**P0 级**
1. **秘密扫描被弄丢**:注册即出境(artifacts→chunks→manifest→provider);
   RP-CE 有 preflight 秘密扫描,我们的计划留在 W8 台账。应注册 gate fail-closed。
2. **混代怪物**:惰性注册+stat 缓存 ⇒ 一个 manifest 各 section 可能是不同时刻的
   文件版本;有 hash 可审计但无 vintage 一致性 gate;跨文件推理会静默出错。
   修:manifest 记 git HEAD/max-stat 水位,混代即标记;跨文件任务强制同批重注册。
3. **首英里悖论**:recall 只能找已注册的;注册靠 selection 驱动;自主任务的
   selection 驱动本身是上下文问题(循环依赖)。RP-CE 靠人策展逃掉;自治环没有
   发现层设计(import 图/目录先验/git 热点/上轮 file_search 反哺)。

**P1 级**
4. **检索遗憾无遥测**:装配后模型仍调 file_search/read = 召回失败最强信号,
   免费可观测(effects 表),无人采集;语料策略(bulk sweep 什么)永远瞎着。
5. **硬分区失明**:corpus 按 ws 分区 = 排序前硬切,跨区相关性永久不可见;
   与「过滤管道让硬切不必要」哲学自相矛盾。修:分区降 boost + 全局兜底,
   或跨区存在性 Noul。
6. **CJK 退化**:存在性 Noul/per-chunk Score 在 CJK 劣化带;超集兜底吸收错误的
   方式=静默退化 no-op;而用户主力语言是中文 ⇒ token 节省承诺在最弱处最弱。
   修:CJK shadow 对照把退化变可观测;bigram 触发条件按用户语料提前实测。
7. **签名缺 provider/model 维**:判断缓存键含 provider/model(§6.5),ws 签名
   不含 ⇒ A 模型学的模式套在 B 模型上。
8. **重组无经济学闸**:goal 切换即重组 = cache break;§5.4 E(r) 未建模组合性
   churn;频繁换 goal 的 session 重组代价可能吃掉全部节省。修:策略行加成本闸。

**P2 级**
9. **模式晋升无 ground truth**:shadow 零 diff 只证「新旧一致」不证「任一为对」;
   结局统计有任务难度混杂。诚实口径=一致性与成本,非质量。
10. **G-dws5 弱**:固定任务集回放只证缓存工作,不证模式覆盖新任务;缺开放集 holdout。
11. **bulk sweep 触发语义未定义**:「谁判断需要全库视野」本身是判断;sweep 异步
    ⇒ 新仓库第一 turn 必 waiting;冷启动延迟未写进预期。
12. **人的负向选择 vs 超集哲学未裁决**:用户 deselect 过的文件 recall 又要加,
    谁赢?人的显式否定是确定性信号应最高优先(veto join);未设计。

**总批评**:注意力全在「选择与加速」(ws/模式/Jev 分级),收集侧传感器
(发现策略/遗憾遥测/秘密扫描)一行没设计——在没有反馈信号的系统上精雕优化器。

## 4. 请 Oracle 回答

1. **独立批评**:链路 ①–⑦ 上还有什么本文件与 v13/v13.1 设计都未覆盖的缺陷?
   按严重度排序,给失败场景。
2. **逐条裁决 §3**:确认/反驳/降级 + 一句理由;有反驳请给反例。
3. **重点展开**:首英里悖论的解法空间;混代 vintage 的最小修;CJK 退化的观测设计。
