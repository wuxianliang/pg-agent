# v13 registry Phase 2 计划评审（2026-10-18）

- 评审对象：`docs/plans/v13-registry-phase2-2026-10-18.md`（下称 plan）。
- 基线：`prompt-exports/oracle-plan-2026-10-18-191911-plan-registry-phase-fe67.md` 的 Generated Plan（下称 export；其 Oracle 1 lane 失败、Oracle 2 codex 完成，见 export:207-221，基线即 Oracle 2 产物）。
- 方法：plan 逐节对照 export，并对全部承重引用实读 v13 SQL/测试源码核对。只审计划，不实现、不重写。用户给定的 export 绝对路径在主仓不存在；实际文件在本 worktree 的 `prompt-exports/` 下，内容同一。

## P1 — 施工前必须修

### P1-1 `v13_effect_envelope`（或 `v13_effect_id` 哈希面）不在 overlay 范围：`registry_revision` 会漏进 judge effect 身份

plan 把 `registry_revision` 加为 envelope 第 21 键（plan:186）和步 0 第八比对键（plan:189），但全文（plan §3.5/§4/W3）没有安排替换 `v13_effect_envelope`。

证据：

- 有效定义 `v13/envelope/v13_envelope.sql:602-608` 恰好剔除七个水位键（session_version/max_event_seq/route_policy 两键/tools_revision/tools_catalog/cgr）；其剔除纪律原文在 `v13/resolve/v13_resolve.sql:334-353`（水位键不入 request 哈希，漂移由步 0 弃批，worker 不消费）。
- judge 建账调用点在有效 advance：`v13/plan_arm/v13_plan_arm.sql:726`（`v13_effect_envelope(p_snap->'envelope')`）。
- effect 身份 = request 哈希：`v13/schema/v13_core.sql:175-182`；不变量「同逻辑动作重试同 ID、新动作必新 ID」在 `v13/schema/v13_core.sql:168-174`。

后果：全局 singleton clock 下任何 scope 的一次 register/retire 都会改变 judge request 哈希 → 同一逻辑判断换 effect 行（attempt 计数断代、在途行成孤儿），恰是 plan:21-22 自己要避免的行为漂移；该类漂移已由步 0 第八键弃批覆盖，request 哈希不应再含它。export 的 26 项替换名单（export:495-523）同样漏了它——plan 应补上而不是继承这个共同盲点。修法二选一（只需指出方向）：`v13_effect_envelope` 追加 `- 'registry_revision'`（ACL 保持 route-only，`v13/resolve/v13_resolve.sql:730`），或在 `v13_effect_id` 的剔除路径（`v13/envelope/v13_envelope.sql:610-621` 的 `#- '{envelope,...}'`）加该键。现有 gate 不会抓到它（需要交错一次 registry 写才显形），测试矩阵应加一条「unrelated scope register 后同逻辑判断 effect_id 不变」的断言。

### P1-2 `native_events_and_probe` 的预期更新在 plan 中缺失

export 硬约束（export:27）与基线正文（export:532、export:585）都要求显式更新该 probe；plan §4.1（plan:222）只钉了 16 probes 的名称/顺序、八函数计数和四文件闭集，没有提这个 probe 的断言体必须改。

证据：`v13/registry/test_registry.py:689-700` —— 该 probe 在 register/retire 前后三次取 `v13_probe`，断言「除 session_version/max_event_seq 外其余键全不变」。probe 增第八键后，register/retire 推进 registry clock ⇒ `registry_revision` 变化 ⇒ 现断言必红。probe 身份钉在 `v13/registry/test_registry.py:871-875`（16 项 PROBES），名称/顺序不动是对的，但 plan 必须写明该 probe 改为「registry_revision 随 register/retire 推进、其余键不变」。

## P2 — 应修（矛盾/漏项）

### P2-1 缺 overlay 批准替换函数的显式名单；安装态复核漏 `pronargdefaults`

plan:220 要求 overlay allowlist 含「批准 replacement functions 和明确 ACL」，plan:246（native_overlay_static）依赖它判定，但全文从未枚举该名单；export:495-523 有 26 项显式名单、export:525 要求 DDL 定稿前与 `pg_proc` 的 `regprocedure`/`pronargdefaults` 对照、不符即停工改名单。plan:38 的安装态复核列了 regprocedure/owner/prosecdef/proconfig/ACL，独缺 `pronargdefaults` —— 而 strict 七参「无默认尾参」契约（plan:143）在目录层面的判据正是 `pronargdefaults=0`。

同点连带：plan §3.3（plan:143-151）未提共享 completion 实现（export:368、export:509 的 `v13_complete_contextual(..., bigint, boolean)`，legacy 委托 require_pin=false / strict 传 true）。共享还是不共享（复制有效体）是两种不同 allowlist，plan 不写死，validator 就没有真值可钉。注：现有 `validate_delta` 对任何既有函数行变化直接失败（`v13/registry/setup_db.py:319-393` 的 frozen functions 比较），两段式 validator 是刚需，plan §4.1 方向正确，缺的只是名单本体。

### P2-2 三个新触发器函数的安全属性未规定

plan §3.2 的 helper 表（plan:103-110）只列 6 个 helper；两张 pin 表的 immutable trigger 函数和 events AFTER INSERT capture 函数不在表内，owner/SECURITY DEFINER/固定 search_path/REVOKE 全部未写（export:312-316 有写）。

承重原因：capture trigger 要写 owner-only 的 mapping 表（plan:88、plan:94），而 events 的写入角色不止 route：`v13/schema/v13_core.sql:866`（route 有 INSERT ON events）、`v13/spawn/v13_spawn.sql:1733-1735`（spawn_owner 的 ALL TABLES/ALL FUNCTIONS 授予）、triage 经 SECURITY DEFINER 的 `v13_triage_emit` 写入（`v13/triage/v13_triage.sql:195-203`）。INVOKER 触发器在这些角色下写 mapping 表必 42501、且挂在每条事件插入路径上。库内先例即 DEFINER 形态：`v13/manifest/v13_manifest.sql:24-36` 的 `v13_goal_project`。

已核对无需担心的一点：spawn:1733-1735 的 blanket 授权早于两张新表存在，不溯及未来对象，pin 表 owner-only（plan:88）成立。

### P2-3 helper ACL 的条件式写法与「明确 ACL」validator 矛盾；resolve 对 `v13_registry_fences` 是刚需而非「如需」

plan:105 写「route/recall（如 resolve 需要则仅授该 helper）」，与 plan:220「明确 ACL」和 plan §8 最终 ACL 矩阵相矛盾——条件式授权没有可校验真值。且证据链表明 resolve 必须授：

- `v13_parse` 只授 v13_resolve（`v13/resolve/v13_resolve.sql:725-729`），parse 调 envelope（`v13/economy/v13_economy.sql:358`）；
- envelope 是 SECURITY INVOKER、授 recall/resolve/route（`v13/resolve/v13_resolve.sql:716-724`；`v13/envelope/v13_envelope.sql:976-983`）；
- registry clock 表对一切角色零 SELECT（`v13/registry/v13_registry.sql:582-585`）⇒ envelope 读 clock 只能经 DEFINER helper。

同理 `v13_effect_context_event_current` 被 parse（resolve 角色）消费（plan:177 行），plan:109-110 的「实际需要的 narrow definer consumer」应坐实为 resolve。export 已直接授 resolve（export:324、328-329）。

另：plan 丢了每个 helper 的 STABLE/VOLATILE 标注（export:324-329 全标）。setup 快照本来就按 (volatility, definer, strict, config) 逐函数校验（`v13/registry/setup_db.py:331` 附近 `_registry_function_rows` 行形），读类 helper 必须钉 STABLE，才能被 STABLE 的 envelope/probe（`v13/filter/v13_filter.sql:486`、`v13/manifest/v13_manifest.sql:831`）正当调用而不虚标波动性。

## P3 — 勘误与措辞

### P3-1 worker 协议把 fair claim 写进了 route 身份的同一流程

plan:195 定调「worker 使用具备 route 能力的 adapter/driver」，plan:197 却写「调用 global/fair claim」。fair claim 是 owner-only（plan:50、plan:112；route 42501 由 `v13/fair_claim/test_fair_claim.py:630-637` 的 `path_grant_route_only` 钉死）。fair 路径只能以 owner 身份跑，钉版复核链（fences/pin_lookup）在 owner 下天然可用，但 plan 应把两条身份线分开写，否则实施者按 route 身份实现 fair worker 会撞 42501。

### P3-2 有证据的引用勘误

- plan:38「`v13/load.py:48-50,101-102`」：registry 加载条目在 `v13/load.py:58`、stage 号映射在 `v13/load.py:102`；48-50 三行是 plan_contract/plan_read/plan_arm。尾部断言见 `v13/registry/test_registry.py:237-240`。
- plan:52「`v13_scheduler_hint` … `v13/govern/v13_govern.sql:559-570`」：该函数 CREATE OR REPLACE 在 `v13/govern/v13_govern.sql:517` 起，559-570 只是其中 tool/call 计数的消费点；export:24 同样以 559-570 指代函数本体，两边都宜改成「定义 :517 起、消费点 :559-570」。同表 `v13_recover_idle` 的 453-507 正确。
- plan:47「`v13/plan_arm/v13_plan_arm.sql:332-700`」：有效 `v13_advance` 实际到 :869 结束；P1-1 的 judge 建账调用点 :726 以及末段 route 分发都在被引区间之外。
- 轻微区间漂移（不影响定位，一并记录）：filter envelope 485-579 → 实际 485-597；economy parse 353-398 → 353-392；loop route 110-178 → 110-163；acl complete 245-451/459-470 → 245-457/459-471。

### P3-3 措辞/精度

- plan:21「共享同一 statement-consistent registry revision」：probe（advance 事务内、route 角色）与 envelope（parse 事务、resolve 角色）物理上不可能共享一个语句快照；真正的不变量是「envelope 单语句自洽 + advance 第八键比对弃批」，export:429 表述正确，plan 措辞应改。
- plan:128「claim 在一个 statement snapshot 中读取双 fences」弱于 export:346 的「单条 data-modifying statement 完成物化 fences+CAS+pin」。plan:200 的 commit 前 fences 复核已封住窗口，两种实现测试等价，但 plan 应明说「允许多语句实现、由复核兜底」还是坚持单语句，现在两种读法都成立。
- plan:87 的额外唯一键 `(effect_id, attempt_no, fence)` 与主键 `(effect_id, attempt_no)` 重复：claim 是 attempt_no 唯一递增点、requeue 只推 fence 不动 attempt（`v13/fanout/v13_fanout.sql:270-283` 注释；`v13/control/v13_control.sql:1104-1130`），pin 表内 fence 函数依赖于 (effect_id, attempt_no)；mapping 外键指主键、fence 作普通数据列即可通过同样测试。保留三列外键的唯一增量价值是交叉校验 mapping.fence = pin.fence（防 capture trigger 自身 bug）；plan:87 写的理由（「供事件 mapping 外键使用」）不构成必要，要么写明交叉校验意图，要么去掉该唯一键。

## 已核对自洽的部分（对应评审重点 2/3 的正面结论）

- **事件归属无竞态**：所有携带 `source_effect_id` 的事件写入点都在 effect 行锁+CAS 之后（有效 completion 体 `v13/acl/v13_acl.sql:411-455`）；advance 写 wake/material 的 source 是已终态 harness effect、attempt/fence 稳定（`v13/plan_arm/v13_plan_arm.sql:546-548,567-569`）；stale worker 的迟到完成被 CAS 挡在事件写入之前（先返 `stale`，零事件）。capture trigger「按当前 attempt/fence 找 pin」在这些路径下归属正确；re-claim 后旧完成事件保持旧 pin 归属（plan:95）成立。
- **legacy/synthetic/CE 区分与 append-only/`source_effect_id` 契约一致**：control guard 强制 repair/replan、turn/material_spent、human/responded 必须带 source（`v13/control/v13_control.sql:425-429`），resolve/failed 不在守卫词表（:421-482），故 plan:153 给 judge failure 补 `source_effect_id` 不触守卫；frontier_gap 的 synthetic replan 的 source 不在 effects（`v13/frontier_gap/v13_frontier_gap.sql:300-308`）→ 无 pin 历史 → eligible，与 plan:179 一致；CE claim 七键不变（`v13/ce_run/v13_ce_run.sql:254-280`）、CE completion 走共享 legacy 六参（`v13/ce_run/v13_ce_run.sql:645,728,929`）→ 永无 pin，与 plan:153/264 一致。
- **payload guard 面不受 plan 影响**（`v13/control/v13_control.sql:421-482`、`v13/spawn/v13_spawn.sql:230-274`），side-table 选型（不改 payload）与 exact-key 守卫相容。
- **锁序无逆转**：registry 写面 clock→meta→sessions→registrations（`v13/registry/v13_registry.sql:298-336`）、fair claim advisory 13002→root→child→effect（`v13/fair_claim/v13_fair_claim.sql:478-599`）、completion session→effect（`v13/acl/v13_acl.sql:284-285`）与 plan:128/204 一致；claim 只读 clock 不 FOR UPDATE 不会与写面成环。
- **有效定义表核对无误**：probe=manifest:830-843（七键）、envelope=filter:485（20 键）、snap_of=resolve:384、snapshot=envelope:566-567、parse=economy:353、advance=plan_arm:332、route=loop/advance.sql:110、claim=fanout:266-303（五键）、claim_fair=fair_claim:421（六键含 root_session_id、REVOKE PUBLIC 后零授权）、complete=acl:245/459、closeout=spawn:585、fold/block=triage:325/516、recover_idle=govern:453。被覆盖同名定义（loop/control/spawn/fanout/triage/should_run/govern 的 advance 链等）与 plan §2.1 一致。
- **收口口径一致**：README 50 项 manifest（48×exit 0 + goal_supervisor 1/2，`v13/registry/README.md:147-218`）与 plan:248 的 49+2=51 一致；16 probes 钉（`v13/registry/test_registry.py:871-875`）、八函数计数（:236）、四文件闭集（:245-258，plan 引 :285-293 略有漂移）与 plan:222 一致。

## 评审边界

只审计划文本与 export 的 Generated Plan 段，未评审实现（尚不存在）、未评审设计文档 §11.5 之外的 Phase 3 内容；export 的 Final Prompt/hard_constraints 仅作需求来源引用，不作为正确性证据。
