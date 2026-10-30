# B-DP7-1 / B-DP7-2 oracle 三角裁决报告

> 日期:2026-09-22。性质:父级 Loop Orchestrate 控制器授权的 oracle 裁决会话产出(用户显式授权:由 oracle 给出 dp7 矛盾的解决方案,控制器随后照案执行)。
> 裁决对象:**B-DP7-1**(dp7 plan 内部矛盾:settle blob-belt vs history 收缩)+ **B-DP7-2**(M 组 decision count,细节丢失后重导)。
> 边界遵守:纯只读勘探 + 本报告;未改任何代码/plan/测试。**plan 文档冻结不动**;裁决全部落在实现侧(换体授权记 README 台账 + erratum 悬置清单)。
> 裁决方式:controller brief 下发 → 本会话独立核实材料 → 三路独立 oracle(context_builder 管道,互不知晓、同份中性 brief)→ 分歧逐条对照源码/plan 原文裁定。

---

## 0. 结论一览

| 项 | 裁决 |
|---|---|
| **B-DP7-1** | 矛盾**成立且为数学结构性**(非 fixture 缺陷)。终案=**方案 D(A 的最小安全实现)**:授权文件 13 对 `v13_refresh_context` 做**第 8 处 OR REPLACE**(全局第 8/文件 13 第 3 处),双模式 belt(未变形臂=economy 加载态原文逐字;变形臂=单源材料函数+独立 guard),summary belt 新块,最小 diff 清单执法。O 组全谱(含 O3 回退链)可构造。 |
| **B-DP7-2** | **机制无障碍;矛盾存在于 M1 断言自身文字**(「round1 检查失败」与「decision 行数恰 2」互斥)。裁决=M 组 gate 按 **M1a/M1b/M1-neg** 三行读法实现,澄清记 README(gate 注释),不改代码不改 plan。 |
| **回退条件** | 若用户/控制器推翻第 8 处换体授权:诚实回退=**M2 记 blocked/deferred**(B 案的真实内容),MUST NOT 用弱化断言假绿 O 组。 |

---

## 1. B-DP7-1 矛盾核实(证据链,本会话独立复核)

### 1.1 矛盾侧 A(plan 语义,文件 13 待实现)

- `docs/plans/v13-dp7-economics-summary-plan-2026-09-20.md` §3.2(iii)(≈L752-766):存在可消费 adopted summary 时——落 summary 段(`kind='summary'`,`payload_ref={kind:'blob',content_hash}`,settle 日 `v13_blob_land` 落,`transform={applied:true,name:'summarize'}`)+ **history 段收缩为 keep_tail_turns 尾段**(`transform='verbatim'`,content_hash 变⇒churn+1;被替旧轮零 skipped 行)。
- 同文件 O1(≈L958-959):「history 收缩为 keep_tail 尾;blob land 内容寻址(重 settle 零新行);**est(summary)<est(被替 span) 且总 est 下降**」。
- 同文件 OQ2 步 4(≈L109)、不变量 9(§1.5):「summary blob belt=settle 消费前对 effect.result 携带正文重算 content_hash 恒等才落行(零信 effect 自报哈希)」。
- **矛盾面不限于 adopted summary**:§3.2(iii) 回退链三级——①spill(history 段 transform `name:'spill'`,段 content_hash 变 churn+1)②`compaction_round_drop` ③`compaction_final_trim`——**全部改变 history 段字节**。即 O3 的回退链 fixture 同样会撞 belt(三路 oracle 一致指出,controller 原案 A 未列此点)。

### 1.2 矛盾侧 B(已交付代码)

- `v13/economy/v13_economy.sql` L1425-1442(换体五,机械复制自 `v13/manifest/v13_manifest.sql` L800-817):

```sql
v_hist  := public.v13_canonical_state(v_sid) -> 'messages';   -- 完整 canonical 历史
SELECT s->>'content_hash' INTO v_mh
  FROM jsonb_array_elements(v_manifest->'sections') s
 WHERE s->>'section_id' = 'history';
v_hh := public.v13_blob_land(p_effect, v_hist);
IF v_hh IS DISTINCT FROM v_mh THEN
  RAISE EXCEPTION 'v13: history blob hash drift vs manifest section'
    USING ERRCODE = 'V3003';
END IF;
```

- 装配 v2 的 history 段 content_hash=sha256(canonical messages 全文)(economy sec_src history 臂 ≈L483-497,同构 manifest L541-546);`v13_blob_land`(manifest L712-731)= 内容寻址,返回 sha256(p_inline::text)。
- **结构性红证明**:收缩后 manifest history 段 content_hash=sha256(tail),belt 重算=sha256(full canonical);被替 span 非空 ⇒ tail≠full ⇒ sha256 相等仅剩密码学碰撞 ⇒ **adopted summary(及回退链任一级)生效后的每次 settle 必抛 V3003**。v1 生产 `actions_enabled=false` 动作层零激活不触发;但 O 组 gate 必须翻 `actions_enabled=true` 演练 ⇒ gate 不可构造 ⇒ M2 blocked。
- **第二重事实(本会话核实,决定 B 案命运)**:`v13_blob_land` 零运行角色 EXECUTE(REVOKE PUBLIC,唯一可达=refresh DEFINER 体内;DP3 §3.5 立法原文),plan 附 A #11 明文「不新增 artifacts 直写面(lander 零运行角色纪律不动)」。⇒ **不改 refresh,summary blob 无任何合法落行路径**——即使放弃收缩只落 summary 段,B 案原 wording 也实施不了。

### 1.3 belt 法源(DP3 立法意图)

`docs/plans/v13-dp3-manifest-skeleton-plan-2026-09-20.md` §3.5(L1238-1259 注释原文):

> 「section blob 冻结(P0-4①):history/tools 正文经内容寻址落行(去重);**材料重取自 canonical_state——三层行锁保证与装配快照同材料**;belt:重算哈希≠manifest 段哈希 ⇒ V3003(**锁失效的不可能路径,防御性**)。」

即 belt 同时执法两件事:
- **(i) 落行一致**:settle 落的 blob == manifest 声明的 history 段(payload_ref.content_hash 与段 content_hash 恒等,P0-4①);
- **(ii) 忠实投影**:manifest history 段 == canonical messages 的忠实投影(契约 #7,L44)。

**(ii) 的「全量」形态是 DP3 时代的首版语义,且 DP3 自己已把真窗口让渡给 DP7**:DP3 §1.4 DP7 行(经 dp7 plan 基座与缝 ≈L57 转引)——「**真窗口=新 transform 名+新策略版本行(首版 verbatim,O2 P1-1)**」;dp7 消费清单 #9 接的就是这句。P0-4① 的立法目的是消灭 `{kind:'canonical_state'}` 活指针(语料变化后重放漂移),保护的是「**被引用字节永可原字节回取**」,不是「永远引用全文」。canonical 本身仍是 events 的 append-only 全量投影(收缩是装配侧投影,不改 canonical——约束 4 核实在案)。

### 1.4 授权边界事实

- plan §1.1(≈L106):文件 13 仅授权 assemble/validate 再跳;M2 实施序(≈L989-990)同。refresh 换体=未授权第 8 处。
- 前任执行者曾以「断言可构造优先」自行做第 8 处换体,被否决。**否决的根因=未披露冲突+无授权记录的私自扩权**(turn 13 在档:执行方发现矛盾后上报、控制器核实、用户裁决挂起——不是「任何情况下都不得换体」)。
- 本次:控制器独立核实矛盾(ask_user 后用户改授权 oracle 裁决)且 brief 明示裁决落点=「**换体授权记 README 台账+erratum 悬置清单**」——即**换体授权本身在本裁决的职权范围内**,与被否决的先行裁量性质不同(见 §3 分歧 D1)。

---

## 2. Oracle 三角记录

### 2.1 三路执行情况

| 路 | 模型 | 状态 | 结论摘要 |
|---|---|---|---|
| R1 | gpt-5.6-sol(codex,xhigh) | ✅ 完整 | 新案 D=「双模式、材料单源的 refresh v3」(A 的加固版):授权第 8 处换体;未变形路径保留原 belt;变形路径从 canonical 确定性投影+effect.result 重算材料;三方哈希比对(材料=段=payload_ref=blob_land);通用材料解析函数;**若拒绝授权则 M2 必须 blocked,不得用 B 假装完成**。B-DP7-2:机制无障碍,M1 文字自相矛盾,拆 M1a/M1b/M1c。 |
| R2 | gpt-5.6-sol(codex,xhigh,第二轮) | ⚠️ 部分交付(watchdog 截断于 ④ 中段,①-③ 完整) | 严格三选=**B**;实现层=B 的必要修正版 **D0**(summary-consumption 完全延期:不落 summary 段/blob、schedule fail-closed、O1 真实收缩记 DEFERRED);**未来语义最优=D1**(section-aware 双分支+材料单源 belt,需先获第八处换体授权)。关键贡献:**B 原案也需改 refresh 才能落 summary blob**(否则 payload_ref 指向永不存在于 artifacts 的哈希,违反 P0-4 回取义务)⇒ B 的真实内容=不消费。B-DP7-2(截断前已给出):检查失败路径全程至多 1 条 decision,与「恰 2」互斥。 |
| R3 | grok-4.7-build-fast-xhigh | ✅ 完整 | **方案 D(对 A 的收窄)**:以 erratum 授权第 8 处换体,**只改锁块一行+history belt 的 IF 包裹(IF 臂=economy 原文四行逐字)+tools belt 后的 summary belt**;单源函数四件(`v13_history_action`/`v13_history_section_material`/`v13_summary_section_material`/`v13_history_belt_guard`);guard 用 canonical 独立复核后缀/span(防单源函数两边同错);测试端独立切片(第三重独立)。B-DP7-2:同 R1 结论+epoch 种子须显式 'pre-finalize'+两轮间 provider/model GUC 恒定。 |

(首轮另有 stepfun 路故障、一路被取消;重试后成上述三路。分歧裁定只采信经本会话源码复核的事实。)

### 2.2 三路一致点(本会话逐条源码复核通过)

1. 矛盾为数学结构性,非 fixture/断言写法问题。
2. `actions_enabled=false`(v1 生产)路径的行为必须与文件 12 **字节等同**——未变形臂必须逐字保留原 belt,不得「语义等价重写」(jsonb 重建会改变 `::text` ⇒ history blob 身份漂移)。
3. (i) 落行一致不放宽(且应加强为三方哈希:材料=段 content_hash=payload_ref.content_hash=blob_land 返回值)。
4. (ii) 的放宽法理=DP3 OQ4 已把真窗口让渡 DP7(lex specialis);canonical 全量仍完整保留在 events/旧 blob/旧 manifest,exact replay 不漂。
5. summary 材料必须从 effect.result 正文重算,**零信 `rounds[].content_hash`**(不变量 9)。
6. B-DP7-2:机制无障碍;M1 前后半互斥;reject/review 路径 decision 行已在 `v13_resolve_judgments` 落地(L745-753 answered 分支),检查失败路径零 decision(§6.4-3/K2)。

### 2.3 分歧与裁定

| # | 分歧 | 各方立场 | 裁定 + 证据 |
|---|---|---|---|
| **D1** | 授权边界 vs 交付语义 | R2:第八处换体未获授权,erratum 不能绕过硬授权 ⇒ 选 B(延期);R1/R3:授权换体+显式 erratum | **裁定:授权换体(R1/R3)**。证据:(a) controller brief 明示裁决落点含「换体授权记 README 台账」——授权正是本裁决的职权;(b) 被否决先例的根因是无记录的私自扩权(turn 13 流程在档),不是禁止经裁决的授权;(c) **R2 自己证实 B 原案也需改 refresh 才能落 summary blob**——B 的真实内容=「summary 消费完全延期」=M2 继续 blocked,与 brief「照案执行 M2」的目标相悖;(d) R2 的护栏全部吸收进终案(显式 erratum、条件回退=诚实 blocked 而非假绿)。 |
| **D2** | 换体形态 | R1:通用材料解析函数 `v13_manifest_blob_materials` + 通用落盘循环,**删除**原硬编码 history/tools 块;R3:IF 包裹最小 diff,IF 臂原文保留 | **裁定:R3 形态**。证据:不变量 10(机械复制+仅标注增量);R1 形态删除旧块违反「未变形路径保留原 belt」的 §2.2-2 一致点,v1 生产行为不再字节等同文件 12;L4 可验性(diff 允许清单)R3 显著更优。R1 的通用循环记为远期方向(多段化/chunk sections 落地日再议),本轮不采。 |
| **D3** | 新 RAISE 的 V 码 | R3:变形臂 history 漂移沿用 V3003 同文案;R1:变换路径用 V3007 | **裁定:按不变量 10——新代码新 RAISE 一律 V3007**;IF 臂复制体的 V3003 逐字保留(墓碑纪律)。理由:V 码顺延纪律(DP1-5=V3001-3005/DP6=V3006/DP7=V3007)的存在意义就是按代码世代溯源;变形臂是新世代代码。 |
| **D4** | 锁集 | R1:锁集加 `summary_accept`;R3:不加(消费面只读已冻结 effect result+已锁的 tiers/budget) | **裁定:加(一行)**。证据:装配 v3 的 economics.summary 子块消费 `summary_accept`(intent/packs,plan §3.2(ii))——「进 manifest 输入的策略版本锁内同版」纪律(不变量 8 同族);不加则装配与 belt 间存在该行版本的 READ COMMITTED 漂移窗(良性但可除)。README ops 锁序同步记一笔。context_summary effect 行的 `FOR SHARE`(R3)=**允许项(可选)**:终态 effect 行今日无 UPDATE 路径,属未来演化防御;计入 diff 允许清单。 |

---

## 3. 终案:方案 D(A 的最小安全实现)

### 3.1 ① 选定方案与完整理由

**授权文件 13(`v13/summary/v13_summary.sql`)对 `v13_refresh_context` 做第 8 处 OR REPLACE(文件 13 内第 3 处,与 assemble/validate 并列),换体形态=双模式 belt+单源材料函数+独立 guard,diff 以允许清单执法。**

理由(四层):

1. **矛盾不可在授权清单内消解**(§1.2 证明):收缩/回退链必然改 history 段字节;summary blob 唯一落行点=refresh 体内 `v13_blob_land`。「belt 表达式零改动」的替代路径全部违规——改 `v13_canonical_state`(污染语义窗/token/transcript 全部读者,破约束 4)、改 `v13_blob_land`(破内容寻址 CHECK 与 lander 授权清单)、新建第二条 DEFINER 落行入口(破窄入口,违反附 A #11)。
2. **B 不是可交付项**:R2 证实 B 需要先改 refresh 才能落 summary 段,否则连「summary 段在场」都做不到;B 的真实内容=DP7 摘要消费完全延期 ⇒ O1/O3/G-ctx8 消费半边全部记 DEFERRED ⇒ M2 不构成里程碑交付。若采 B,`est(summary)<est(被替 span) 且总 est 下降`永假(全量 history+summary 段反而净增)。
3. **法源支持**:(ii) 的全量首版语义经 DP3 OQ4 已让渡 DP7 真窗口(§1.3);P0-4① 保护的是被引用字节可回取——尾段 blob 是清单声明过的字节,不是活指针;canonical 与旧 blob 全量保全,exact replay 不漂。
4. **授权性质与先例区分**:被否决的是「未披露冲突、无台账的自行扩权」;本裁决=控制器核实+用户授权+三路 oracle+分歧裁定+L4 重点审+erratum 悬置清单,全过程在档。

**条件回退(必须随附)**:若用户/控制器推翻本授权,回退=R2 的 D0(summary 消费延期,schedule fail-closed,O 组记 DEFERRED/blocked)——MUST NOT 采「弱化 O1 断言后宣称通过」的任何形态。

### 3.2 ② 实现规格(实施者直接照做)

#### 3.2.0 总纪律

- refresh v3 复制源=**第 12 位 economy 加载态**(不是 manifest 原体——economy 已含经济学锁与守卫);仅按 `[DP7-summary]` 标注增量编辑;「移动=增+删」,文件内不残留旧定义。
- 文件内顺序:helper 函数 → OR REPLACE assemble → OR REPLACE validate → OR REPLACE refresh → 文件真末尾 ACL;BEGIN/COMMIT 单事务。
- 函数签名/SECURITY DEFINER/search_path/complete CAS 参数与调用序/artifact 落行/result 补挂/sessions 指针全部不变。
- `manifest_version` 维持 2(OQ7:kind 扩展走校验器词表)。

#### 3.2.1 新增单源函数(新对象,非换体;文件 13 正常新建预算内)

**(a) `v13_history_action(p_sid uuid) RETURNS text`**(`STABLE`,只读已锁行,禁止调用 `v13_assemble_manifest` 防环)。返回封闭词表 `full | tail | spill | round_drop | final_trim`:

```
actions_enabled 不真                         → full
有效 tier 无需压缩(且非硬窗口/E(r) 判定)      → full
需压缩 且 存在可消费 adopted summary          → tail
需压缩 无可用 summary                        → 固定梯逐级「装得下就停」:
                                               spill → round_drop → final_trim
                                               (停机判定用动作后 est 重跑三桶,只此一份)
```

可消费 adopted 谓词(与 O2 同一份):本 session 最新 `kind='context_summary' AND status='succeeded'` 行(次序=行上已存单调列+effect_id 打破平局,禁 now());`result.adopted=true`;该 effect **request** 冻结的 `span_digest` == 本次 canonical 在 protected tail 之外前缀的 `v13_span_digest`;否则不消费(basis 词表沿用 plan 冻结值 `{none,no_budget,no_effect,checks_failed,rejected,cjk,span_stale}`)。**span 一律取 request 冻结值,不读 result 副本**(request 不可变,result 是 worker 可写面)。

**(b) `v13_history_section_material(p_sid uuid) RETURNS jsonb`**(`STABLE`):

- `action='full'`:返回 `v13_canonical_state(p_sid)->'messages'` **原值**(禁止 `jsonb_agg` 重建——字节身份);
- `action='tail'`:返回尾段 jsonb 数组;
- 回退三级:返回梯作用后的 history 正文。

尾段定义(apply 与 guard 同一边界计数):user turn=`user/message` 起、至下一条 `user/message` 前的连续子数组(含其间 `llm/message`/`tool/result`);从末尾数 `keep=context_budget.keep_tail_turns`(活动行,economy 已锁)个 `user/message`;**不足 keep 个 ⇒ 材料=全量原值且 action 不得为 tail**(空前缀不能对应非空 span);否则 tail=该条 `user/message` 及其后全部元素,元素原样、序不变。消息类型键名以 `v13_canonical_state` 加载态实查为准,不新造。

**(c) `v13_summary_section_material(p_sid uuid) RETURNS jsonb`**(`STABLE`):不应落 summary 段时返回 NULL;否则=同一 adopted effect 的 `result.rounds` **最后一轮** `body` 文本 → `to_jsonb(body)`(jsonb 字符串;`blob_land` 对 `p_inline::text` 做 sha256,与 history 材料同哈希律)。**禁止读 `rounds[].content_hash`**(不变量 9)。

**(d) `v13_history_belt_guard(p_sid, p_full jsonb, p_mat jsonb, p_manifest jsonb)`**(owner-only):变形臂进入时 `p_mat` 哈希已等于段哈希且不等于全文哈希,guard 按 canonical 独立复核:

1. `v13_history_action='full'` ⇒ V3007(装配写了非全文哈希而决策说不变形);
2. tail:`p_mat` 是 `p_full` 的真后缀(等长尾部逐元素 jsonb 相等且更短);尾部 `user/message` 计数=`least(keep, 全文计数)` 且全文计数>keep;manifest 恰一个 applied summary 段(`name='summarize'`);无 `compaction_round_drop`/`compaction_final_trim` 段;`v13_summary_section_material` 哈希==summary 段 content_hash;canonical 前缀的 `v13_span_digest`==该 effect request 冻结 `span_digest`;goal 段哈希==`v13_goal_hash(p_sid)`。任一失败 ⇒ V3007;
3. 回退:manifest 无 summary 段;history transform/reason 与 action 对应(spill ⇒ history `{applied:true,name:'spill'}`;drop/trim ⇒ 对应 skipped 段且三级不跳级);`p_mat` 中每条非 tool 消息是 `p_full` 同序相等元素;tool/result 或与原文相等或为 stub(含 effect_id、不含原 body);goal 同上;
4. 其他形状 ⇒ V3007。

**guard 的存在理由(R3 核心贡献)**:单源函数若 action 与 material 同时把尾段切错一拍,装配与 belt 两边哈希仍相等——guard 对 canonical 重数后缀/重算 span,是 belt 侧的独立信源;测试端再独立切片一次(§3.2.5),共三重独立。

ACL:四函数 `REVOKE EXECUTE FROM PUBLIC`;(a)(b)(c) 授予与 `v13_assemble_manifest` 相同的只读角色(装配 SQL 调用);(d) 仅 owner(refresh DEFINER 体内调用时即 owner;不授 route)。helper 一律 SECURITY INVOKER,不做第二套 DEFINER 入口。

#### 3.2.2 装配 v3(已授权再跳)中与 belt 相关的增量

history 的 sec_src 行 bytes/content_hash/mat 三者同源:

```sql
CASE WHEN public.v13_history_action(p_sid) = 'full'
     THEN cs.c -> 'messages'
     ELSE public.v13_history_section_material(p_sid) END
```

- `action='full'` 时与 economy v2 逐字节同产物;`action='tail'` 时 transform 仍 `{applied:true,name:'verbatim'}`(plan §3.2(iii) 写死,不改名);churn 沿用既有规则(前版哈希异 ⇒ prior_churn+1);被替旧轮零 skipped 段。
- summary 段仅当 `v13_summary_section_material` 非空:`section_id='summary'`/`kind='summary'`/`cache_scope='Session'`/`priority='Normal'`/`payload_ref={kind:'blob',content_hash:<与段 content_hash 同>}`/`transform={applied:true,name:'summarize'}`/est 走 cls 既有整数公式(`bytes=octet_length(mat::text)`)。段上不内嵌正文。
- goal/tools 的 mat 与哈希表达式不动。

#### 3.2.3 validate v3(已授权再跳)新增 belt(均在既授权面内)

1. `payload_ref.kind='blob'` ⇒ `payload_ref.content_hash` 必须恒等段 `content_hash`(V3007)——P0-4① 的跨字段执法(现 validate 缺);
2. `section_id` 全局唯一(V3007);
3. `economics.summary.consumed` 与 summary 段双向一致:consumed NULL ⇒ summary 段数 0;非空 ⇒ 恰 1 且 kind/transform/payload_ref 形状合法、effect_id/decision_id/span_digest 为合法 UUID/64hex(V3007);
4. adopted 形态:history 单段、transform=verbatim、无 fallback applied 段、summary 与 history 均计 applied est;
5. 回退 recipe 闭集:steps op 仅 `spill/drop_rounds/final_trim`、顺序固定、参数域校验;consumed 与 fallback applied 互斥(V3007);
6. **不得**新增「history 哈希必须等于 canonical 全文」类断言(会把合法尾段拒掉)。

#### 3.2.4 refresh v3 换体(diff 允许清单——L4 对超出即退回)

相对 economy 加载态,允许且仅允许:

| # | diff | 位置 |
|---|---|---|
| 1 | 策略锁 `FOR UPDATE` 的 name IN 集合加 `'summary_accept'`(一行内增名) | 现有锁块 |
| 2 | (可选)adopted context_summary effect 行 `FOR SHARE`(次序=pricing 锁后、形状守卫前;零行合法) | 同上 |
| 3 | history belt 包 IF:IF 臂=**economy 现有四行逐字**(含 V3003 文案);ELSE=变形臂(下) | complete CAS 后原 belt 处 |
| 4 | summary belt 新块 | tools belt 原文块之后、`v13_artifact_land` 之前 |

以下必须 economy 加载态逐字:入口 kind/fence 校验、锁序骨架、形状守卫全文、assemble/validate/inline 调用序、complete CAS、tools belt 全文、artifact_land、result 补挂、sessions 指针、返回值。不换体:`v13_blob_land`/`v13_canonical_state`/`v13_complete`/`v13_advance`/`v13_enqueue_effect`/resolve/envelope 族。

**history belt(IF/ELSE)**:

```sql
v_full := public.v13_canonical_state(v_sid) -> 'messages';
SELECT s->>'content_hash' INTO v_mh
  FROM jsonb_array_elements(v_manifest->'sections') s
 WHERE s->>'section_id' = 'history';

IF encode(digest(coalesce(v_full::text,''),'sha256'),'hex') IS NOT DISTINCT FROM v_mh THEN
  -- ===== 以下四行 = economy 加载态原文逐字(V3003) =====
  v_hh := public.v13_blob_land(p_effect, v_full);
  IF v_hh IS DISTINCT FROM v_mh THEN
    RAISE EXCEPTION 'v13: history blob hash drift vs manifest section'
      USING ERRCODE = 'V3003';
  END IF;
ELSE
  v_mat := public.v13_history_section_material(v_sid);
  IF encode(digest(coalesce(v_mat::text,''),'sha256'),'hex') IS DISTINCT FROM v_mh THEN
    RAISE EXCEPTION 'v13: history blob hash drift vs manifest section (V3007)'
      USING ERRCODE = 'V3007';
  END IF;
  PERFORM public.v13_history_belt_guard(v_sid, v_full, v_mat, v_manifest);
  v_hh := public.v13_blob_land(p_effect, v_mat);
  IF v_hh IS DISTINCT FROM v_mh THEN
    RAISE EXCEPTION 'v13: history blob land drift vs manifest section (V3007)'
      USING ERRCODE = 'V3007';
  END IF;
END IF;
```

调度条件用哈希相等而非读 action:未变形(含 actions off)⇒ 全文哈希==段哈希 ⇒ 走 IF 臂 ⇒ **v1 生产与文件 12 字节同路径**;变形 ⇒ ELSE。装配写错(既非全文亦非单源材料哈希)⇒ ELSE 内第一比对拦下(V3007)。action 与哈希不一致 ⇒ guard 规则 1 拦下。

**summary belt**:

```sql
SELECT s->>'content_hash' INTO v_sh
  FROM jsonb_array_elements(v_manifest->'sections') s
 WHERE s->>'section_id' = 'summary';
v_smat := public.v13_summary_section_material(v_sid);

IF NOT FOUND THEN
  IF v_smat IS NOT NULL THEN
    RAISE EXCEPTION 'v13: summary material without summary section (V3007)'
      USING ERRCODE = 'V3007';
  END IF;
ELSE
  IF v_smat IS NULL
     OR encode(digest(coalesce(v_smat::text,''),'sha256'),'hex') IS DISTINCT FROM v_sh THEN
    RAISE EXCEPTION 'v13: summary blob hash drift vs manifest section (V3007)'
      USING ERRCODE = 'V3007';
  END IF;
  IF public.v13_blob_land(p_effect, v_smat) IS DISTINCT FROM v_sh THEN  -- 不变量 9:恒等才落行
    RAISE EXCEPTION 'v13: summary blob land drift vs manifest section (V3007)'
      USING ERRCODE = 'V3007';
  END IF;
END IF;
```

位置在 complete CAS 成功之后(blob_land 要求同事务 effect 已 succeeded)、`v13_artifact_land` 之前——与既有 belt 同事务语义;任一抛错 ⇒ 整事务回滚(complete 的 succeeded/blob/指针全部撤销,effect 回 claimed,worker 另事务 complete('failed'))。

**锁序声明**:sessions → tools_meta → 策略活动行(六名,含 summary_accept)→ v13_pricing active →(可选 context_summary 行 FOR SHARE)→ effects(complete CAS)。方向与全局不变量 8 一致,零新路径。

#### 3.2.5 O1 断言最终形态(gate 实现)

fixture 前置:`context_tiers` 翻版 `actions_enabled=true`;`keep_tail_turns=2`;canonical ≥3 个 user turn(前缀非空);context_summary 经真实 enqueue/claim/complete 成 succeeded 且 adopted=true;request.span_digest==该前缀摘要;末轮 body 比前缀短约一个数量级(防整除吃掉「总 est 下降」);**自报 rounds[].content_hash 故意填错**(不变量 9 集成断言);settle 前不再追加 user/message。

断言(十项):

1. `v13_refresh_context` 返回 'accepted',零 V3003/V3007;
2. summary 段在场:kind/section_id/priority/cache_scope/transform 如规;`payload_ref.content_hash`==段 `content_hash`,均 64hex;
3. 该哈希==sha256(to_jsonb(body)::text)(**测试端自算**),且 ≠ effect 自报哈希;artifacts 该哈希行 inline==to_jsonb(body);
4. history:transform=verbatim;content_hash==测试端独立切片的 sha256(tail)(**禁止调 `v13_history_section_material` 当 oracle**),≠sha256(全文);前版哈希异 ⇒ churn=prior+1;无被替旧轮 skipped 段;
5. history blob inline==尾段 jsonb(非 canonical 全文);
6. goal/tools content_hash 与 actions off 对照装配相同;tools blob 仍 canonical tools;
7. est(summary)<est(被替前缀)(同一 est 公式),且本次 applied Σest < 同库全量对照清单 Σest(反事实对照,勿与上一 turn manifest 总 est 比——新 user 消息会引入无关增量);
8. 同材料重 settle:summary/tail 的 context_section 行数仍各 1(ON CONFLICT DO NOTHING);
9. canonical messages 元素数不变;user/llm/tool 语义事件计数零增(P1 联测);
10. O2(span_stale):settle 前追加 user/message 使前缀 digest 失配 ⇒ history 段哈希回到全文哈希、走 IF 臂、无 summary 段、basis='span_stale'、settle 仍 accepted。

O3(回退链)用同一 ELSE 臂:验收不采用且需压缩 ⇒ action=spill/round_drop/final_trim 逐级 fixture;①能装下则零②;guard 规则 3 执法;goal/tools 字节不变(O5)。

#### 3.2.6 gate fixture 补充要点

- 负向:guard 单测(owner 直调)喂「声明 summarize 但 mat 非 canonical 后缀」的 manifest ⇒ V3007;不靠拆锁造 V3003(同事务锁成立时两调一致,V3003 留代码走读);
- `actions_enabled=false` 且库中有 adopted effect:history 哈希==sha256(canonical 全文),零 summary 段,与文件 12 行为一致(未变形臂字节身份);
- 前缀库:`files_through` 停在 manifest/economy 的 gate 不加载文件 13,旧 belt 用例保持绿;文件 13 断言对象 ≤13 号(H4/P6);
- 确定性:同输入装配两调 manifest::text 相等(含收缩);exact replay 读旧 artifact 原字节(旧 history blob 仍是收缩前全文,新 settle 不 UPDATE 旧 artifact);
- 测毕还原:翻版 fixture(actions on/packs=2 等)双回滚纪律逐处写入。

### 3.3 ③ 安全性分析

**完整保留(R1/R3 一致,本会话采纳)**:

| DP3 意图 | 终案状态 |
|---|---|
| (i) 落行 blob==manifest 声明 | **保留且加强**:材料哈希==段 content_hash==payload_ref.content_hash==blob_land 返回值(四方) |
| history 材料来源于 canonical_state | 保留:变形后仍是 canonical 的确定性投影,guard 对 canonical 独立复核 |
| tools 全量投影 / goal=v13_goals | 原样保留 |
| 内容寻址与去重 / lander 零运行角色 / 唯一入口=refresh DEFINER | 原样保留 |
| complete CAS 后才落 blob / 锁序 / settle 零外部 IO | 原样保留 |
| exact replay 原字节回取 | 加强:summary/tail/回退产物全部可回取 |
| 装配确定性(零时钟/零随机/同输入字节相等) | 保留(helper 全 STABLE 确定性,锁内同版) |
| 零信外部自报哈希 | 保留且执法:summary 材料重算,rounds[].content_hash 不参与 |

**唯一放宽(及法理)**:`action<>'full'` 时,「manifest history==canonical 全文」收窄为「==canonical 经受校验、版本化、确定性变换(keep_tail 尾段/spill/drop/trim)的投影,且 belt guard 用 canonical 独立复核」。法理:(a) DP3 OQ4 明文把真窗口让渡 DP7(「真窗口=新 transform 名+新策略版本行,首版 verbatim」)——lex specialis;(b) P0-4① 立法目的=消灭活指针、保护被引用字节可回取,未把「永远引用全文」立为跨 DP 不变量;(c) canonical events/旧 blob/旧 manifest 全量保全,重放不漂;(d) 变换仅由显式 transform+`actions_enabled` 门控触发,v1 生产零激活。

**明确不放宽**:belt 不改为 manifest 自哈希(驳 C 的法理——自述比对丢独立信源,锁失效/装配写任意字节都过);收缩不写进 canonical;summary 正文不进语义事件窗;不改 `v13_complete` kind 分支;失败路径不吞 V 码。

### 3.4 B-DP7-2 重导结论与裁决

**结论:机制无障碍(重导澄清);矛盾存在于 M1 断言自身文字,按澄清并入 gate 读法,不改代码/架构。**

机制核实(本会话+三路一致):

- `request_hash` 七参(envelope L569-577),`judgment_hash` 的 context=`v13_group_state(p_env,signal)`(L579-600)→ summary 组投影态 `{source,summary}`;**round2 新摘要文本 ⇒ state 变 ⇒ request_hash 变** ⇒ `UNIQUE(session_id,request_hash)`(resolve L512-514 ON CONFLICT 目标)不冲突 ⇒ 新 decision 行。两轮验收恰 2 行可构造;
- 同文本重验 ⇒ 同哈希 ⇒ `v13_gap`(resolve L363-372,命中=answer 非空∧status∈answered/cached)为空 ⇒ `v13_resolve_judgments` 循环入口即退出 ⇒ 零 judgment_calls 零新 decisions(负向对照成立;且首先是 gap 命中,不必等到 judgment_cache 层);
- `judgment_calls` 仅在真正调 `typesafe_ask` 后落行(成功/failed_timeout/failed_validation);**确定性检查失败 ⇒ resolve 未被调用 ⇒ 0 decision 0 calls**(§6.4-3/K2);
- 验收 reject/review 的 decision 行在 `v13_resolve_judgments` 内落地(answered),`v13_summary_verdict` 只做事后解释——reject 路径**有** decision 行;
- epoch:decisions/judgment_templates 两处 CHECK 均含 'pre-finalize'(manifest L118-125);`trg_decisions_epoch`(L127-148)INSERT 期按模板回填;`trg_decisions_epoch_freeze` 只拦 UPDATE OF epoch,answer-once 的 SET answer 不碰 epoch。**注意:模板种子行必须显式写 epoch='pre-finalize'(列默认是 'pre-bind')**;epoch 不进 request_hash、不按 epoch 分桶唯一约束——不减少行数。

**M1 文字矛盾**:「round1 检查失败」⇒ round1 无 decision ⇒ round2 验收后全程恰 **1** 行;「行数恰 2」仅当 round1 失败在**验收**(reject/review)时可构造。两半不能在同一条 fixture 里成立——这是 M1 把 K 组(检查失败不调 Jev)与 §6.4-5(重生成非重问)焊在了一起,非机制缺陷。

**裁决=M 组 gate 按下表实现(README/gate 注释载明,plan 原文不动)**:

| 编号 | 构造 | 断言 |
|---|---|---|
| M1a | packs=2;round1 确定性检查失败;round2 **不同**文本通过检查并验收 | signal `summary::%` 的 decision 行数=**1**;round1 前后 judgment_calls 差=0;全程 judgment_calls 差=1;两轮 request_hash 不等 |
| M1b | packs=2;round1 检查通过、验收 p=0.2(reject;另档 p=0.6 review 同型);round2 不同文本再验收 | decision 行数=**2**,均 epoch='pre-finalize';judgment_calls 差=2;两行 request_hash 不等;round2 ctx.summary≠round1 |
| M1-neg | 对已落答的同一 {source,summary} 再调 resolve | gap 空;decisions/judgment_calls 零新增 |
| M2 | packs=2 用尽 | 无第三轮;全败 ⇒ complete('failed')/adopted=false(终案落地后 settle 不再误伤此路径) |

fixture 纪律:两轮间 provider/model GUC 恒定(否则哈希因身份变而变,测不到「只因正文变」);计数不滤 epoch;模板种子 epoch 显式 'pre-finalize'。

### 3.5 ⑤ L4 验收检查点(建议)

1. **授权先验**:summary README 台账+erratum 悬置清单含 E-DP7-1/E-DP7-2/C-DP7-M1 三条(§4 原文);缺席即判 blocked,不接受静默第八换体。
2. **diff 允许清单**:refresh v3 vs economy 加载态 normalized diff,仅 §3.2.4 表四项;锁块其余/守卫/complete 调用/tools belt/指针更新一字之差退回。
3. **未变形臂字节身份**:actions off ⇒ history blob 哈希==测试端 sha256(canonical messages::text),与文件 12 同 fixture 相同;'full' 分支无 jsonb_agg 重建。
4. **ELSE 非自述**:走读确认变形臂哈希对象=单源函数返回值(manifest 无段正文);summary 材料不读 rounds[].content_hash(源码检索)。
5. **独立 oracle**:O1 测试自切尾段;guard 负向单测(自洽但非后缀 ⇒ V3007)。只跑 happy path 不算 belt 有效。
6. **不变量 9 负向**:自报哈希填错 ⇒ settle 仍 accepted,落行哈希==body 材料、≠自报值。
7. **span 信源**:前缀 digest 用 request 冻结值;O2 失配走 IF 臂无 summary 段。
8. **锁与并发**:summary_accept 已入锁集;FOR SHARE(如采)在 pricing 后 complete 前;settle∥各翻版零 40P01;无 effect→sessions 反向路径。
9. **回滚完整性**:belt 抛 V3007 ⇒ 本事务 succeeded/blob/context_active_artifact 零残留(effect 回 claimed)。
10. **ACL**:四新函数 REVOKE PUBLIC;guard owner-only;route 不能 EXECUTE blob_land/guard/不能 INSERT artifacts;helper 非 DEFINER。
11. **词表与版本**:收缩后 history 仍 9 键/verbatim/64hex/churn 规则;summary 经 validate v3;manifest_version=2;旧 artifact exact replay 取收缩前全文。
12. **M1 读法**:对照 M1a/M1b/M1-neg;若实现者造出「检查失败且 decision=2」,要么检查失败时偷插 decision(违 §6.4-3)要么把 reject 误称检查失败——均 FAIL;模板种子 epoch=='pre-finalize'。
13. **回退链可落盘**:spill/drop/trim 各至少一例过 ELSE 臂;三级不跳级负向;protected tail 与 goal/tools 不受梯(O5)。
14. **前缀回归**:manifest/economy 前缀库旧 belt 用例绿;文件 13 断言对象 ≤13 号。

---

## 4. 授权登记(README 台账 + erratum 悬置清单条目原文)

```text
E-DP7-1(授权漏计,plan 冻结不改):
  plan §1.1「七处 OR REPLACE」与不变量 9、§3.2(iii)、OQ2 步 4、O1 冲突:
  后四者要求 settle 落 summary blob 并在 adopted/回退时改 history 段字节,
  唯一落行点=v13_refresh_context 体内 v13_blob_land(lander 零运行角色,
  无第二合法落行面)。实施侧授权文件 13 对 v13_refresh_context 做第 8 处
  OR REPLACE(文件 13 第 3 处)。增量仅限:锁集增 summary_accept(一行)、
  (可选)context_summary 行 FOR SHARE、history belt IF 包裹(IF 臂=economy
  原文逐字含 V3003;ELSE=单源材料+guard+V3007)、tools belt 后 summary belt。
  未变形路径(actions_enabled=false 及 action='full')与文件 12 字节同路径。
  授权链:控制器核实+用户授权 oracle 裁决(2026-09-22,
  docs/reviews/v13-dp7-bdp7-1-oracle-resolution-2026-09-22.md)+L4 检查点 1-14。
  若本授权被推翻:回退=summary 消费延期(M2 记 blocked/deferred),
  不得弱化 O1/O3 断言假绿。

E-DP7-2(belt (ii) 首版限制的显性化,plan 冻结不改):
  DP3 OQ4 已把真窗口让渡 DP7(「真窗口=新 transform 名+新策略版本行,
  首版 verbatim」)。action='full' 时 (ii) 仍为 history 段=sha256(canonical
  messages 全文),原文语句与 V3003 逐字保留;action<>'full' 时 (ii) 改为
  「段字节=v13_history_section_material 对 canonical 的确定性投影,且
  v13_history_belt_guard 用 canonical 独立复核(尾段后缀/回退结构像/span)」。
  (i) 不放宽:blob_land 返回值与段 content_hash、payload_ref.content_hash 恒等。

C-DP7-M1(M1 断言文字澄清,plan 冻结不改):
  M1「round1 检查失败」与「decision 行数恰 2」互斥(检查失败不调 Jev ⇒
  round1 无 decision 行 ⇒ 全程恰 1 行)。gate 按 M1a(检查失败路径,1 行)/
  M1b(验收 reject 路径,2 行)/M1-neg(同文本重验,零新增)三行读法实现;
  模板种子 epoch 显式 'pre-finalize';两轮间 provider/model GUC 恒定。
```

---

## 5. 执行交接(给 M2 执行者的最短路径)

1. 按 §3.2.0-3.2.4 写文件 13:helper 四件 → assemble v3 → validate v3 → refresh v3(复制源=economy 加载态,按 diff 允许清单)→ ACL;
2. 其余 M2 件(kind 扩展/cap v2/summary_accept/模板/defaults 追点/span_digest/checks/envelope/verdict/schedule)照 plan §3.2 原文;
3. gate:M 组按 §3.2.5-3.2.6 与 §3.4 表;O 组按 O1 十项+O2/O3/O5;
4. README 三条登记(§4)+ops 锁序更新(summary_accept 翻版同序取锁);
5. 提交前:12 gate 全量复跑+I–P 绿(AGENTS.md);一里程碑一提交。

## References

- plan:`docs/plans/v13-dp7-economics-summary-plan-2026-09-20.md`(§1.1 ≈L106/§1.5 不变量 9/§3.2(iii) ≈L752-766/OQ2 ≈L109/OQ8/M1 ≈L944-946/O1 ≈L958-959/M2 实施序 ≈L989-990)
- 代码:`v13/economy/v13_economy.sql`(头注 L15-20/sec_src history 臂 ≈L483-497/belt L1425-1442);`v13/manifest/v13_manifest.sql`(epoch L118-157/history 段源 L541-546/blob_land L712-731/refresh 原体+belt L733-817);`v13/envelope/v13_envelope.sql`(group_state L294-319/request_hash L569-577/judgment_hash L579-600/resolve_judgments L623-852);`v13/resolve/v13_resolve.sql`(gap L363-372/decisions INSERT L501-527)
- DP3 法源:`docs/plans/v13-dp3-manifest-skeleton-plan-2026-09-20.md`(契约 #7 L44/OQ4/§3.5 L1238-1259)
- 背景与约束:`prompt-exports/loop-orchestrate-v13-deep-plans-impl-runs.md` turn 13(L52)
- oracle 三角:R1 gpt-5.6-sol(chat b-dp7-oracle-三角裁决-bdp7-1-F15F87)/R2 gpt-5.6-sol(chat dp7-belt矛盾裁决-5AA3B5,部分交付)/R3 grok-4.7-build(chat dp7-belt矛盾裁决-oracle-2-F19FFD)
