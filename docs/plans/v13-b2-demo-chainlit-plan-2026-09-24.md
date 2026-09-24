# v13 B2 交付的 Chainlit demo 升级方案(mgraph 装配接线端到端验证)

> **状态**:v1.0(2026-09-24)。本文只做设计:**不改任何 demo 代码、不改 `v13/` 任何文件、不提交任何东西**(demo 树 gitignored 永不提交;按 v13 惯例,本计划文档本身也保持本地不提交)。实施是后续另一个 agent 的工作项,P0 清单写到「另一个工程师可照做」的精度。
>
> **P0 已交付**(2026-09-24,同日实施):W1–W5 全绿——建库 exit 0(16 文件/属主自检/demo_anon 10 RPC);fake gate `test_demo_b2.py` 35 PASS;real 端到端冒烟 `b2_smoke_real.py` GREEN(DeepSeek 播种→build 5 节点/6 边→A_off disabled 零 walk→翻版→A_on walk 5 步 stop=evidence→段 emit 2 行 speaker=user→回答正确引用「八千,三万是重复计数」);回归 test_demo_loop 78 PASS / test_demo_smoke / test_demo_shim 73 PASS(shim 需 `no_proxy='*'`)。实施偏差 13 条已记入 §6 台账(要点:demo_mgraph_build 属主改 postgres、run_round GUC pre-load 顺序、签名 +p_api_key、一回合双 refresh、探针前必须重投影)。W6(P1)未实施,无头 A/B-lite 由冒烟脚本承担。库 agent_v13_demo_b2 已重置默认(read/write off)。
>
> **命名消歧**:本文的「demo」指 gitignored 的 `v13/demo/` 树(Chainlit + PostgREST + driver + psycopg 双端口),不是任何 tracked 文件。「B2」= `docs/plans/v13-mgraph-assembly-wiring-plan-2026-09-24.md` 的装配接线(Stage 16),已由 5f801d5/b1a1c86/c65362d 交付。

## Goal

把刚交付的 B2 mgraph 装配接线接进 Chainlit demo,使「记忆是否真的改善回答」首次在端到端真实栈(PG 状态机 + PostgREST + shim → DeepSeek)上**可跑、可看、可判**:

1. **驱动**:demo 工人实现 W3 双连接契约(claim → walk 循环 → refresh settle),整体替换 `driver.py:224` 对 `context_refresh` 的 fail-loud 结算;transcript 投影与节点 build 的驱动时机有明确落点。
2. **观测**:`memory_graph` 段(行/provenance 七键)、walk 统计(edges_used/depth/calls/judge spend)、degraded 审计在 UI 呈现;提供可判定的 A/B 协议(同会话翻版前后为主,同题两会话 read on/off 为严选变体)。
3. **库**:demo 库从 15 文件升到 16 文件(`mgraph_assembly`),`demo_api*.sql` 兼容性给出确定答案。
4. **清单**:逐文件修改清单,每条绑 B2 事实(工人契约/GUC 陷阱/策略翻版仪式),标 P0(跑通一轮记忆注入对话必需)/P1(观测呈现)/P2(锦上添花)。

## Background

### B2 交付事实(已核实,直接采用)

- **段与身份**:manifest 升 v4(`manifest_version` 3→4);`memory_graph` 单段从**已停** walk 的 evidence 注入(`sec_src` 第六支,`cache_scope=Session`、优先级 LastResort、blob 化 `payload_ref.kind='blob'`,B-E2 不进 `sec_full`);第 12 个 token 键 `mgraph_ver`(`v13_mgraph_asm_ver` 窄 digest,材料仅 `{generation, policy_version}`);provenance 七键闭集(`origin/speaker/conflict/seq_count/seq_first/seq_last/source_hashes`),`speaker ∈ user|llm|mixed|consolidation|unknown`,同文折叠=mixed+conflict。
- **工人契约**(`v13/mgraph_assembly/README.md` W3 节,计划 §3.7):`route txn: v13_claim`(不进 refresh)→ `resolve: loop{q=v13_mgraph_turn_query(sid) 每轮重读; act=v13_mgraph_next_action(sid,q,elapsed); act∈{done,skip}→出; act=ask→(real 模式零工人 IO,run_round 体内 ask); r=v13_mgraph_run_round(sid,q,elapsed); COMMIT 一轮一事务}until r.status∈{stopped,skipped} or r.action∈{done,skip}` → `route txn: v13_refresh_context(effect, attempt, fence)`。七条纪律:elapsed 工人累计;read off/空 query/degraded 直接 settle 无段;**walk 抛错或 spend 帽仍 settle**(段缺席即降级,回合不 failed,失败的 refresh 才被 advance ② 收成 terminal);**步数帽工人侧 `maximum_jev_calls*6+8`,不进 SQL 函数体**;**每步在 route 连接续租**,失败则结束循环并 settle;查询串只许经 `turn_query`;已停 walk 二次循环 asks=0。
- **ACL 事实**(决定 demo RPC 属主,J9 实测):`v13_mgraph_run_round`/`next_action`/`capture_pm` **仅** `v13_resolve`;`turn_query`/`section_plan`/`section_material`/`section_status`/`asm_ver`/`progress`/`policy()`/`evidence` 授 route/resolve/recall;`v13_refresh_context` 是 SECURITY DEFINER 且 economy 已授 route(试验期 `demo_refresh_context` 属主 `v13_route_login` 实测可用);`v13_rebuild_transcript_chunks`/`v13_verify_memory` **仅 owner**(memory README 运维面);`v13_mgraph_build(uuid,int)` 授 `v13_resolve`。
- **策略纪律**:默认 `read_enabled=false`;翻版须 INSERT 新 mgraph 策略版本行 + 双 UPDATE 翻 active 仪式(`v13_policies` 禁 DELETE、值不可变)。翻版改 `policy_version` → `mgraph_ver` 变 → `context_fresh=false` → 下一回合 advance ② 自然 enqueue `context_refresh`——**翻版即触发记忆注入**。
- **降级面**(§3.9):`section_status` 闭集 `emit|disabled|degraded|empty_query|no_walk|no_rows`;仅 status=degraded 落一条 `audit/memory_degraded`(refresh 内,指针后 shadow_observe 后)。

### demo 现状(必读,均在 gitignored 的 `v13/demo/`)

- `driver.py:224` `_dispatch` 对 `context_refresh` 等 kind 走 fail-loud(`demo_unknown_handler`)——**要被工人契约整体替换的核心位置**。driver 只跟 `contract.Port` 说话(不 import psycopg/chainlit),Fake 与真实共用一个 driver。
- 试验期适配(v1 trial / v2 rerun):`mem2_converse.py:74` `MemDriver._dispatch` 把 `context_refresh` 直接 settle(无 walk);`PortMem.refresh_context` 走 `demo_refresh_context`(`sql/demo_api_mem.sql:12`,属主 route_login)。全栈实测:一会话 11–12 次 `context_refresh`;词法命中 0.772–0.900;幻觉复述(「周六九点」→「周日上午九点」)0.824 同权可召回;全部 depth=1/edges_used=0(CJK superset 路由下遍历未发生);build 前须手动投影(pg_cron 被 `cron.database_name` 闸)。
- demo 库现状:`agent_v13_demo`(envelope,5 文件,基面)+ `agent_v13_demo_mem`/`agent_v13_demo_mem2`(15 文件到 mgraph,v1/v2 试验对照库,留档不动)。B2 后须 **16 文件**。
- 端口双实现:`port_pg.py`(同步 psycopg,一调用一事务,超级用户)+ `port_rest.py`(httpx over PostgREST,sync face 桥到 app 事件循环);RPC 双属主(`v13_route_login`/`v13_resolve_login`)+ postgres 特例(`demo_recycle_pool`)。
- **关键缺口**:demo 的生成提示自建于事件窗(`driver.build_messages`),**不消费 manifest**。B2 的段不进提示,端到端就看不到「记忆改善回答」——本方案必须补上注入点(§2.1.6)。

### 本方案必须回答的四个问题

1. 端到端驱动:demo 工人如何在 driver 里实现「claim→walk 循环→refresh」双连接契约(步数帽/续租/异常仍 settle);transcript 投影 tick 与节点 build 的驱动时机放回合哪一步。
2. 效果观测:A/B 对照设计(须可判「记忆是否真的改善回答」);段在 UI 的呈现;walk 统计;degraded 显示。
3. demo 库升级:16 文件加载 + `demo_api*.sql` 是否需改。
4. 修改清单:逐文件、理由绑 B2 事实、P0/P1/P2。

## 0. 执行索引

| 工作项 | Goal | Done when | Key files | P 级 | Size |
|---|---|---|---|---|---|
| W1 库与 RPC 面 | 16 文件库 `agent_v13_demo_b2` + B2 RPC/视图 | 建库退出码 0;`demo_anon` 可调全部新 RPC;属主自检绿 | `sql/demo_api_b2.sql`(新)、`setup_db_b2.py`(新) | P0 | M |
| W2 端口协议 | `contract.Port` 扩展 + 双端口实现 | fake gate 与 REST 面方法集一致;build 的池回收+重试落地 | `contract.py`、`port_rest.py`、`port_pg.py` | P0 | M |
| W3 driver 工人契约 | `context_refresh` 分支实现 W3 七纪律 + 记忆块注入生成提示 | fake gate 断言 1–3 绿(见 W5);real 模式一轮记忆注入对话跑通 | `driver.py`、`settings.py` | P0 | L |
| W4 UI 呈现 | 段/行/provenance/walk/degraded 渲染 + `/memory` 命令 | 人工清单(A/B 协议六步)全过 | `app.py` | P0 | M |
| W5 fake 契约 gate | 离线验证契约形态(no-op/触帽/段出现/blob 对账) | `uv run --project v13/demo python v13/demo/test_demo_b2.py` 退出码 0 | `test_demo_b2.py`(新)、`harness.py`、`fakes.py` | P1 | M |
| W6 脚本化 A/B | headless 同型驱动 + 观测脚本(与 trial 同款日志) | `b2trial/*.json` 落盘;A/B 判定字段齐全 | `b2_converse.py`(新)、`b2_observe.py`(新) | P1 | S |

每个 W 独立可验;W3 依赖 W1+W2;W4 依赖 W3;W5 依赖 W3;W6 依赖 W3。**提交纪律不适用本文**(不提交);实施 agent 自行按里程碑自测。

## 1. 定位与边界

### 1.1 不变量核对

| 不变量 | 来源 | 守法方式 |
|---|---|---|
| 外部 IO 一律不进数据库事务 | AGENTS.md 4;DP7 1 | demo **不自行发起 walk 判断 IO**:walk 的 provider IO 由 `run_round` 体内的 `v13_resolve_judgments→typesafe_ask` 完成(M3/B2 既有形态,demo 工人只做步进+续租+settle);生成 IO 照旧在事务外(`asyncio.to_thread`)。demo 不新增任何 IO-in-transaction |
| W3 七条纪律 | mgraph_assembly README §W3 | 逐条落入 `driver._do_context_refresh`(§2.1.2 伪码注释绑条款号) |
| 单活跃 effect | `ux_v13_effects_single_active` | 复用 `context_refresh` 车,不 enqueue 嵌套 effect;hub 串行单认领者模型不变 |
| 查询串单源 | W3 #6 | 工人只经 `v13_mgraph_turn_query` 取串;不用 `effect.request`(request 只有 `goal_hash`) |
| 策略翻版仪式 | B2 基座锁定 #14 | 翻版只经 `demo_mgraph_policy_bump`(INSERT + 双 UPDATE);表禁 DELETE、值不可变 |
| demo 部署面纪律 | demo 计划 §库、角色、RPC | 不 `CREATE OR REPLACE` 任何 `v13_*`;GRANT 只写 setup 的 GRANTS 字符串;新 RPC 双属主 + postgres 特例(owner 平面);末尾 REVOKE PUBLIC |
| 不追加 `SQL_LOAD_ORDER` | demo 计划 | B2 库经 `load_stage(server, db, "mgraph_assembly")` 走注册表既有第 16 文件,零改动 |
| fake/real 哈希空间分开 | settings.py 既定 | fake 模式 `provider=fake/model=fake-judge`;A/B 效果判定只用 real 模式 |

### 1.2 边界

- 只碰 gitignored 的 `v13/demo/` 树;`v13/`、根 `pyproject.toml`、`.gitignore` 零改动。
- 不修 mgraph/mgraph_assembly 的任何已知问题(锚池方向不对称=W4 未触发、CJK superset 路由、contradicts 判断质量);demo 只消费既有行为并把现象显示出来。
- 不把 demo RPC 追加进 `v13/load.py`;不改 `sql/demo_api.sql`(envelope 基面)与 `sql/demo_api_mem.sql`(15 文件试验库可复现)。

## 2. 设计

### 2.1 端到端驱动(回答问题 1)

#### 2.1.1 回合内的位置

一次带记忆注入的回合,拨格序列(advance ② 在 `mgraph_ver`/`sem` 等 token 失配时 enqueue `context_refresh` 并返回 `waiting`;trial 实测一会话 11–12 次):

```
tick 1  parse → advance = waiting(context_refresh 已入队)
        claim(kind=context_refresh)              ← route 面
        ┌─ walk 循环(§2.1.2,resolve 面,一轮一事务)─┐
        refresh settle(route 面)                  ← 段落进活动 artifact
tick 2  parse(fresh)→ advance = waiting(kind=llm)
        claim → timeline → build_messages + 记忆块(§2.1.6)→ generate → complete
tick 3  parse → advance = terminal(finish/answered)
```

要点:walk 必须整体早于同一次 refresh 的 assemble(manifest freeze 只消费 freeze 前已提交的 stopped walk,AF1);记忆块在 llm 生成前从**活动 artifact** 取,保证「模型看到的」与「冻结的」一致。

#### 2.1.2 工人契约落地:`driver._do_context_refresh`(P0 核心)

替换 `driver.py:224` fail-loud 分支;`_dispatch` 增加:

```python
if kind == "context_refresh":
    return self._do_context_refresh(claim, sid, result, cancel, emit)
```

伪码(注释绑 W3 条款;elapsed/steps/renew 的数值常量进 `settings.py`):

```python
def _do_context_refresh(self, claim, sid, result, cancel, emit) -> str:
    # W3:claim 的 session 为准(demo_claim 返回 session_id;hub 串行但不错信调用方 sid)
    sid = claim.get("session_id") or sid
    eid, attempt, fence = claim["effect_id"], claim["attempt_no"], claim["fence"]

    def fail(code):                       # 与 _do_llm.fail 同型:结算后回合继续拨格
        self.port.complete(eid, attempt, fence, "failed", {"code": code}); return "ok"

    if cancelled(): fail("demo_cancelled"); return "cancelled"
    # 续租 #1:claim 之后、循环之前(与 _do_llm 同位)
    if not self.port.renew_lease(eid, fence, S.LEASE_MS):
        emit("lease_lost", {"effect_id": str(eid)})
        result.error = "lease_lost"; return "error"
    # 步数帽(W3 #4,工人侧):maximum_jev_calls*6+8;策略行循环起点读一次
    pol = self.port.mgraph_policy() or {}
    max_steps = int(pol.get("maximum_jev_calls", 10)) * S.MGRAPH_STEP_FACTOR \
                + S.MGRAPH_STEP_BASE                      # 6 与 8 进 settings
    walk = {"steps": 0, "capped": False, "rounds": [], "degraded": False}
    t0 = time.monotonic()
    try:
        for _ in range(max_steps):
            if cancelled(): fail("demo_cancelled"); return "cancelled"
            q = self.port.mgraph_turn_query(sid)          # W3 #6:每轮重读,唯一取串口
            act = self.port.mgraph_next_action(sid, q, elapsed_ms(t0))
            if act.get("action") in ("done", "skip"):     # read off/空 query/degraded 落这
                break
            mock = None
            if act.get("action") == "ask" and self.answer_mock is not None:
                mock = self._mgraph_round_mock(sid, act)  # fake 模式:envelope+gap+mock(§2.4 #7)
            r = self.port.mgraph_run_round(sid, q, elapsed_ms(t0), mock)  # 一轮一事务
            walk["steps"] += 1; walk["rounds"].append(r)
            emit("walk", r)                               # UI 步进展示
            # 续租(W3 #5):每步在 route 连接续本 effect 租约;失败→结束循环仍 settle
            if not self.port.renew_lease(eid, fence, S.LEASE_MS):
                emit("lease_lost", {"effect_id": str(eid)}); break
            if r.get("status") in ("stopped", "skipped") or r.get("action") in ("done", "skip"):
                break
        else:
            walk["capped"] = True     # 触帽:停止循环并 settle;walk 仍 open 则段不出现(W3 #4)
    except Exception as exc:          # W3 #3:walk 抛错仍 settle,段缺席即降级,回合不 failed
        walk["degraded"] = True; walk["error"] = f"{type(exc).__name__}: {exc}"
    result.walk = walk
    try:
        # settle:route 连接;refresh 内序(锁→advisory→assemble→validate→complete→
        # memory belt→指针→shadow_observe→仅 degraded 落 audit)B2 已交付,demo 原样调用
        result.refresh_settle = self.port.refresh_context(eid, attempt, fence)
    except Exception as exc:
        # refresh 自身 RAISE(belt 漂移 V3009 等)= 程序缺陷不是降级(B2 §3.9):
        # complete failed,回合有机会被 advance ② 收成 terminal;gate 必须先红
        self.port.complete(eid, attempt, fence, "failed",
                           {"code": "demo_refresh_raise"})
        result.error = f"refresh: {exc}"; return "error"
    return "ok"
```

配套小改:

- `TurnResult` 增字段:`walk`(上形)、`refresh_settle`(accepted/stale/replay)、`memory`(settle 后的段快照,供 UI 与 gate)。
- `_mgraph_round_mock(sid, act)`
- `elapsed_ms(t0)` = 模块级小函数 `int((time.monotonic()-t0)*1000)`(W3 #1:工人从循环起点累计;测试传 0 的同构)。
- cancel 语义与既有 kind 一致:结算 failed 后返回 `cancelled`,不写 `cancel/*`。

#### 2.1.3 「双连接」在 demo 的体现

REST 面(app 实际路径):claim/renew/refresh 走 route 属主 RPC,walk 三步走 resolve 属主 RPC;每 RPC = PostgREST 一笔事务,**「一轮一事务」天然成立**;`next_action` 预览与 `run_round` 分居两事务无语义损失(`run_round` 内部自取动作,预览仅作 UI 展示)。
psycopg 面(gate 用):按 J8 参考工人形态,walk 用 `v13_resolve_login` 连接(`connect_as` 既有助手)、claim/refresh 用 route 连接;超级用户直连只用于库态构造与只读断言(harness 既有纪律)。

#### 2.1.4 步数帽 / 续租 / 异常的落点(回答问题 1 的前半)

- 步数帽:工人侧 for-range(伪码 `else: walk["capped"]=True`);**不进 SQL 函数体**(W3 #4);帽值来源=`v13_mgraph_policy()` 的 `maximum_jev_calls`(默认 10 → 帽 68),循环起点读一次(循环中翻版是运维错误,不防御)。
- 续租:循环前一次 + 每步一次(`renew_lease` 既有 RPC);失败即结束循环并照常 settle(W3 #5),同时 `emit("lease_lost")` 上屏。
- 异常分级:walk 抛错 → 吞、settle、`walk.degraded=True`(段缺席即降级,W3 #3);refresh 抛错 → complete failed + 回合可能 terminal(B2 §3.9 表格原样);spend 帽/步数帽 → 不是异常,照常 settle,段可能缺席。
- settle 零 walk IO:refresh 调用前循环已停,`v13_refresh_context` 内不做任何判断(B2 交付事实)。

#### 2.1.5 投影 tick 与节点 build 的时机(回答问题 1 的后半)

**结论:不进回合循环,放在回合之间,由显式命令触发。**

理由(绑 B2 事实):

1. build 是多 tick、跨信封的写路径(重跑实测 49 tick/106s),进回合会把长 IO 塞进 turn 拨格;judge spend 与回合预算混账。
2. **generation 竞态**:build 提交 bump `v13_mgraph_meta.generation`;walk 身份含 generation,材料按**当前** generation 查找——walk 开始后、停下来之前若 build 推进 generation,旧 walk 的材料查找落空(`no_walk`,段不出现,B2 §3.8)。所以 walk 开始后**任何** build 都必须避免。
3. 投影(`v13_rebuild_transcript_chunks`)是 build 的前置(pg_cron 在 stage 库不可用,手动投影是全栈下的真实运维形态——trial §3);它与 build 同属「回合之间的图维护」,不该占回合延迟。

落点(UI 命令,hub 空闲时执行;`st.busy` 显式拒绝):

- `/memory project` → `port.rebuild_transcript_chunks(S.MGRAPH_PROJECT_LIMIT)`(幂等,trial 实测调两次等效)。
- `/memory build` → 先投影,后循环 `port.mgraph_build(sid)` 至 `status=ok and pending_nodes=0 and stop_reason is null`(或 failed/skipped/触 `S.MGRAPH_BUILD_TICK_CAP`);每 tick 一次 RPC。**帽用种子值**(`write_max_batches=8/write_max_asks=64`):914790f 已把关系信封修成 5 参显式传参,不再需要 trial 时期的 wmb=1 绕过;但每 tick 仍须落在**未加载 typesafe 库的新连接**上(§2.4 #1),由端口层回收池保证。**前置**:`v13_mgraph_build` 在 `write_enabled=false` 时直接返回 `skipped/disabled`(mgraph 暗库默认双 false)——`/memory build` 前必须先 `/memory write on`(同一翻版仪式);命令层在拿到 `skipped` 时给出中文提示而不是空转。
- build 循环在 driver 上以 `build_memory(sid, cancel, on_event)` 方法落地(与 `run_session` 同线程模型,`asyncio.to_thread` 包跑),返回 ticks 摘要供 UI/日志。

#### 2.1.6 记忆块进生成提示(端到端效果的必经缝)

demo 生成提示自建于事件窗,不消费 manifest;不补这条,B2 的段对回答零影响。改法(P0,`driver._do_llm` 内):

```python
events = self.port.timeline(sid)
messages = build_messages(events)
mem = self.port.memory_section(sid)        # 活动 artifact 的 memory_graph 段(§2.3 视图/RPC)
if mem and mem.get("rows"):
    messages.insert(1, {"role": "system",
                        "content": format_memory_block(mem)})   # 位置 1:主 SYSTEM_PROMPT 之后
```

`format_memory_block` 契约(纯函数,进 driver 模块):头部一句「以下是与当前问题相关的记忆片段,仅在与当前问题相关时使用,不得编造未列出的事实」;每行 `[{score:.3f}][{speaker}{"/conflict" if conflict}] {body}`;行数/每行长度截断(常量进 `settings.py`)。降级路径:`memory_section` 在视图/RPC 缺失(如 envelope 基面库)或 404 时返回 `None`——**base demo 行为零变化**。

### 2.2 效果观测(回答问题 2;本 demo 的存在意义)

#### 2.2.1 A/B 协议(主方案:同会话翻版前后)

前置:建 `agent_v13_demo_b2` → 起 PostgREST → 起 Chainlit(real 模式)→ 新线程(会话 A)。

| 阶段 | 操作 | 记录 |
|---|---|---|
| 1 播种(read off,默认) | 发 4–6 条埋点消息(实体/因果/时间链/数字,埋点法同 trial:Alice/Bob/Zephyr、T2 三万→T6 八千更正、时间链;SYSTEM_PROMPT 已限 ≤4 句禁列表,避开 V3005) | 每回合 outcome/status |
| 2 建图 | `/memory write on`(翻版,write_enabled=true)→ `/memory project` → `/memory build`(观察 tick 至自然完成;收尾可 `/memory write off` 翻回) | 策略版本;nodes/edges/jc 批数/wall |
| 3 基线 | 问探针问题 Q(如「为什么发布前没跑预发?」「when 恢复登录」) | **A_off**;panel:section_status 应为 `disabled`(read off) |
| 4 翻版 | `/memory on`(INSERT 新版本 + 双 UPDATE;`policy_version` 变 → `mgraph_ver` 变 → 下一回合自动 refresh) | 策略版本号 |
| 5 实验 | **同一 Q 再问一遍** | **A_on**;panel:section_status=`emit`、行/provenance/walk 统计 |

判定标准(可判「记忆是否真的改善回答」):

1. A_on 引用了播种事实(如「三万/八千」「周六九点」),A_off 没有或答不出;
2. 幻觉样本可见且被标注:若 llm 复述行进 evidence,UI 行显示 `speaker=llm`(「模型复述」徽标)——trial 的 0.824 样本从此可归因;
3. 负例查询(无关问题)evidence 空集、无段、`stop_reason=depth` 收束;
4. walk 统计前后对照:`calls_used/edges_used/depth` 与 trial/rerun 基线(全部 depth=1/edges_used=0,CJK superset 形态)对比——**这是已知形态不是回归**;
5. judge spend:本回合 `judgment_calls` 批数增量 = walk asks(面板对账)。

严选变体(同题两会话):线程 B 在建图后直接 read on,脚本化同题;两会话历史相同故回答差异可归因于记忆。注意:DP2 `judgment_cache` 主键是全局 `request_hash`,B 的相同问题会命中 A 的判断缓存(**spend 对比必须注明此口径**,mem2 报告同款注记)。

#### 2.2.2 UI 呈现(P0 渲染 / P1 面板)

- **段状态行**(每回合 refresh 后一个 step):`memory_graph: emit(5 行)· walk stopped/evidence · depth=1 edges_used=0 calls=3 · judge +4 批`;六状态中文映射:`disabled`=记忆读取未开启、`no_walk`=无已停 walk、`no_rows`=walk 无命中行、`empty_query`=空查询、`degraded`=投影降级、`emit`=已注入。
- **行渲染**(段内每行或折叠一组):`0.900 ▸ episodic · speaker=user · seq#2 · 「因为发布前没有在预发环境跑够三十分钟…」`;`conflict=true` 或 `speaker∈{mixed,unknown}` 加警示标;`speaker=llm` 加「模型复述」徽标(幻觉观测点);consolidation 行标 `speaker=consolidation`。
- **walk 统计**:`memory_walks` 最新行(status/stop_reason/calls_used/nodes_used/edges_used/depth)+ 本回合 judge 批数增量(app 侧对面板快照做差)。
- **degraded**:`audit/memory_degraded` 事件渲染为警示 step(`_render_event` 新分支);面板 `last_degraded_audit` 供复查。
- **面板命令** `/memory panel`:GET `demo_memory_panel`(§2.3),展示 live material 与 frozen 对账、last_walk、jc 累计、策略版本与 read/write flags。

#### 2.2.3 观测口径纪律

1. **冻结 vs live**:UI 展示的段正文取**活动 artifact 的冻结 blob**(模型真看到的);`v13_mgraph_section_material` 是活值,只做对账——两者 `content_hash` 一致才呈现「对账 OK」,不一致提示「refresh 后有新 walk,请重新提问」。
2. **blob 按 content_hash 查**:`v13_blob_land` 对 context_section 内容寻址去重(`uq_artifacts_context_section`),跨会话相同内容的段共享一行、`produced_by` 只记首个 effect——**UI 不得按 effect 数 blob**,一律按 manifest 段的 `content_hash` 查 `artifacts`(测试断言同口径,J6d/J6e 偏差同源)。
3. edges_used=0/depth=1 是 CJK superset 路由下的已知形态(trial/rerun 一致),呈现时注明,不算回归。

### 2.3 demo 库升级(回答问题 3)

#### 2.3.1 加载与库名

- 新库 **`agent_v13_demo_b2`**,新 setup `setup_db_b2.py`(从 `setup_db_mem2.py` 机械复制,只改:`DB`、`STAGE="mgraph_assembly"`(16 文件)、`DEMO_SQL` 追加 `sql/demo_api_b2.sql`、`DEMO_FUNCTIONS`/`GRANTS` 追加新面、自检表更新)。`agent_v13_demo_mem`/`mem2` **不动**(v1/v2 对照留档);原 `agent_v13_demo` 不动。
- 前置照搬:stannum fail-closed 探针、`run_probes`、`register_provider`(DB 级 `typesafe.provider`)、`pin_rest_plane`(DB 级 `typesafe.endpoint`→shim)、DROP 前连接探测(PostgREST 必须先停;建完重启即自然 reload schema cache,运行期无 DDL)。

#### 2.3.2 `demo_api*.sql` 兼容性结论

| 文件 | 是否改 | 理由 |
|---|---|---|
| `sql/demo_api.sql`(基面) | **不改** | 停在 envelope,B2 的 16 文件库与它无关;基面 demo 行为不变 |
| `sql/demo_api_mem.sql`(15 文件试验面) | **不改** | `agent_v13_demo_mem/mem2` 可复现性;其 `demo_refresh_context` 被**逐字搬进** `demo_api_b2.sql` |
| `sql/demo_api_b2.sql`(新) | 新增 | B2 库的 RPC/视图面(下表) |

#### 2.3.3 新 RPC/视图清单(全部 `LANGUAGE plpgsql SECURITY DEFINER SET search_path=public`,末尾 REVOKE PUBLIC;GRANT 只在 setup 的 GRANTS 字符串)

| 对象 | 属主 | 作用 / 理由 |
|---|---|---|
| `demo_refresh_context(uuid,int,bigint)` | `v13_route_login` | 从 `demo_api_mem.sql` 逐字搬迁;W3 settle 步(refresh 是 DEFINER,economy 已授 route,J9 实测) |
| `demo_mgraph_turn_query(uuid)` | `v13_resolve_login` | W3 每轮重读查询串;turn_query 授三角色,resolve 属主与 walk 同面 |
| `demo_mgraph_next_action(uuid,text,int)` | `v13_resolve_login` | **仅 resolve 有 EXECUTE**(B2 ACL)——属主决定的硬点 |
| `demo_mgraph_run_round(uuid,text,int,text,text)` | `v13_resolve_login` | 一轮一事务步进;**仅 resolve**;函数体:`PERFORM typesafe_last_request()`(先加载,后设置)→ 清/设 `typesafe.mock_response` → 设 `typesafe.api_key`(USERSET,值存活)→ 设 `typesafe.model` → `RETURN v13_mgraph_run_round(...)`;**不设 provider**(capture_pm 回落 judgment_calls,§2.4 #1) |
| `demo_mgraph_envelope(uuid,jsonb,jsonb,text,text)` | `v13_resolve_login` | fake 模式算 gap 用(5 参显式传 provider/model,绕开 GUC 墙) |
| `demo_mgraph_gap(jsonb)` | `v13_resolve_login` | fake 模式算 gap;`v13_gap` 授三角色 |
| `demo_mgraph_policy()` | `v13_resolve_login` | 步数帽读 `maximum_jev_calls`;policy() 授三角色 |
| `demo_mgraph_build(uuid,text,text)` | `v13_resolve_login` | build 授 resolve;函数体**不 preload**:先设 `api_key/model/mock_response`(新连接上 pre-load 值存活,trial 实测形态),再 `v13_mgraph_build(sid, NULL)`;provider 由 build 起点 `v13_guc_required` 从 DB 级注册值读——**调用方必须保证新连接**(端口层回收池) |
| `demo_rebuild_transcript_chunks(int)` | **postgres** | rebuild 是 owner 平面(memory README「写/运维面仅 owner」);postgres 属主先例=`demo_recycle_pool` |
| `demo_mgraph_policy_bump(jsonb)` | **postgres** | 翻版仪式:读 active mgraph 行 → `INSERT (name,version=max+1,value=base||overrides,active=false)` → `UPDATE active=false WHERE active` → `UPDATE active=true WHERE version=new`;事务内完成,零 DELETE、零改值(绑 B2 策略纪律) |
| 视图 `demo_memory_panel` | postgres | demo_anon 只读(与既有三视图同权限模型);列:`session_id, read_enabled, write_enabled, mgraph_policy_version, section_status, material_live, frozen_material, frozen_content_hash, frozen_ok, last_walk(status/stop_reason/calls_used/nodes_used/edges_used/depth), generation, freshness, judge_batches, judge_questions, last_degraded_audit`。取法:`sessions.context_active_artifact → artifacts.inline->'sections'` 找 `kind='memory_graph'` 的段 → 段 `content_hash` → `artifacts(kind='context_section')` 取 inline(**按 content_hash,陷阱 2**);`section_status/material_live` 直接包 `v13_mgraph_section_status/material(session_id)`(STABLE,视图属主 postgres 可执行) |

`memory_section`(驱动注入用)不新增 RPC:从 `demo_memory_panel` 的 `frozen_material`/`frozen_content_hash` 投影即可(端口方法 `memory_section(sid)` 内部 GET 视图取两列)。

### 2.4 已知陷阱与落实(每条落到改法)

1. **typesafe GUC 陷阱**(mgraph README ⑧、B2 偏差 #10/#11、mgraph #17/#19 同源):已花费连接上 `typesafe.provider` 占位符被删、保留前缀下同后端 `set_config` 重建被拒。落实:(a) walk 的 `run_round` **不依赖 worker 侧 provider**——capture_pm 回落会话 `judgment_calls`(real 模式会话必有行,provider/model 随冻结信封落账);(b) `build` 必须落在**未加载 typesafe 的新连接**——`PortREST.mgraph_build` 每次先 `demo_recycle_pool()`(自杀式回收,响应中断预期内忽略)再发 RPC,撞 V3002/provider 墙再回收重试至多一次;`PortPG.mgraph_build` 每 tick 一条新连接,pre-load 设 `api_key/model/endpoint`(与 `mem2_mgraph.py` `conn_ask` 同型),**不调 `typesafe_last_request` preload**(那会先杀 provider 占位符);(c) `demo_mgraph_run_round` 相反:先 preload 再设(注册名可重复设),因为跑在池化的已花费连接上。
2. **blob 内容寻址去重**:UI 与断言一律按段 `content_hash` 查 `artifacts`;不得按 effect/produced_by 计数(§2.2.3)。
3. **外部 IO 不进事务**:demo 工人零 walk 判断 IO(run_round 体内完成是 M3/B2 既有形态);生成 IO 照旧事务外;`/memory build` 的 tick 之间无持锁事务(advisory `mgraph-build` 在 build 函数内自行管理)。
4. **generation 与 walk 身份**:build/翻版只许回合之间(命令层 `st.busy` 拒绝);walk 开始后新 `user/message` 落入按 W3 #6 fail-closed(busy 守卫天然避免;headless 脚本靠串行驱动)。
5. **judgment_cache 全局 request_hash**:A/B spend 口径注明(mem2 报告同款);fake/real provider/model 哈希空间分开(settings 既定)。
6. **mock 精确批纪律**(mgraph README #17/#19):fake 模式每轮重算 gap mock(`demo_mgraph_envelope`+`demo_mgraph_gap`+`fakes` 的 mem_* 答案);答案必须恰好覆盖缺口 signal(多未知 signal = V3001 整批拒);不生成「看起来合法」的替答案。
7. **V3005 预检**:llm 回复 >64 段会使 build fail-closed(trial 异常 1);SYSTEM_PROMPT 已限 ≤4 句禁列表;build 前零成本预检(段数/段长)列为 P2。
8. **spend 帽与步数帽的区别**:`maximum_jev_calls` 是 walk 的 ask 帽(SQL 内),`*6+8` 是工人步数帽(driver 内);两者都只停循环不改写 walk 状态,段缺席即降级。

## 3. 修改清单(逐文件:文件 → 改法 → 理由 → 优先级)

### P0 — 跑通一轮记忆注入对话必需

| # | 文件 | 改法 | 理由(绑 B2 事实) | P |
|---|---|---|---|---|
| 1 | `v13/demo/sql/demo_api_b2.sql`(新) | 按 §2.3.3 表建 10 函数 + 1 视图;`demo_refresh_context` 从 `demo_api_mem.sql` 逐字搬;`run_round`/`build` 的 GUC 顺序按 §2.4 #1;全部 REVOKE PUBLIC | walk 三步仅 resolve 有 EXECUTE;rebuild/policy_bump 是 owner 平面;blob 按 content_hash 查 | P0 |
| 2 | `v13/demo/setup_db_b2.py`(新) | 复制 `setup_db_mem2.py`:`DB="agent_v13_demo_b2"`、`STAGE="mgraph_assembly"`(16 文件)、`DEMO_SQL_B2` 追加加载、`DEMO_FUNCTIONS` 追加 10 项(属主按 §2.3.3)、`GRANTS` 追加 demo_anon EXECUTE + 视图 SELECT、`check_owners` 期望表更新 | 16 文件加载是 B2 库前提;部署面 GRANT 纪律(不进 SQL 文件) | P0 |
| 3 | `v13/demo/contract.py` | `Port` 协议增 11 方法:`refresh_context`(从 MemDriver 提升为协议成员)、`mgraph_turn_query/mgraph_next_action/mgraph_run_round/mgraph_envelope/mgraph_gap/mgraph_policy/mgraph_build/rebuild_transcript_chunks/mgraph_policy_bump/memory_section`;docstring 绑 W3 条款与 ACL 属主 | driver 只跟协议说话;两端口对等实现 | P0 |
| 4 | `v13/demo/port_rest.py` | 实现 11 方法(async core + sync face);`mgraph_build` = 回收池 → RPC → V3002/provider 墙则再回收重试至多一次(墙标记扩一个 `"typesafe.provider" in message`);`memory_section`/`memory_panel` GET 视图,404/缺视图 → None(基面库安全) | GUC 陷阱 #1 的 REST 面落实;记忆注入的降级路径 | P0 |
| 5 | `v13/demo/port_pg.py` | 同方法集;`mgraph_run_round/mgraph_build` 用「一调用一条新连接 + pre-load 设 GUC」(build 不 preload、run_round preload,§2.4 #1);其余走 `_call` | fake gate 与 REST 行为对等;超级用户面可设 SUSET endpoint | P0 |
| 6 | `v13/demo/driver.py` | (a) `_dispatch` 增 `context_refresh` 分支调 `_do_context_refresh`(§2.1.2 伪码),删 :224 fail-loud 对该 kind 的覆盖(未知 kind 仍 fail-loud);(b) `_do_llm` 插入记忆块(§2.1.6)+ `format_memory_block` 纯函数;(c) `TurnResult` 增 `walk/refresh_settle/memory`;(d) 增 `build_memory(sid, cancel, on_event)`(投影+build 步进,§2.1.5;write off 时首 tick 即 `skipped`,循环带提示退出);(e) `_mgraph_round_mock`(fake) | W3 契约整体替换 fail-loud;投影/build 时机(§2.1.5);端到端效果必经缝(§2.1.6) | P0 |
| 7 | `v13/demo/settings.py` | 增常量:`MGRAPH_STEP_FACTOR=6`、`MGRAPH_STEP_BASE=8`(步数帽,与 README 逐字)、`MGRAPH_BUILD_TICK_CAP=140`、`MGRAPH_PROJECT_LIMIT=200`、`MGRAPH_BLOCK_MAX_ROWS=8`、`MGRAPH_BLOCK_ROW_MAX=400`;无新 env(模式/shim_key 既有) | 常量只放一处的既定纪律;帽值与 W3 #4 一致 | P0 |
| 8 | `v13/demo/app.py` | (a) `_render_event` 增 `audit/memory_degraded` 分支;(b) `_consume` 增 `walk`/`refresh` kind 渲染(步统计 + settle 结果);(c) `on_message` 增 `/memory write on|off`、`/memory on|off`、`/memory project|build|panel` 命令(busy 拒绝;build/project 走 `asyncio.to_thread`;`on/off` 控 `read_enabled`、`write on/off` 控 `write_enabled`,全部经 `demo_mgraph_policy_bump` 仪式);(d) `on_chat_start` 发「记忆控制台」说明消息;(e) `TappingPort` 把 `refresh_context` 纳入 tap 集(settle 可能落 audit 事件) | 效果观测的 UI 面;A/B 协议的命令入口;命令即翻版仪式的唯一操作面 | P0 |
| 9 | `v13/demo/README.md` | 运行手册补:`setup_db_b2.py` 建库、16 文件说明、`/memory` 命令表、A/B 协议六步、陷阱速查(GUC/blob/generation) | 操作者照做入口;与 trial/rerun 报告的复现工件对齐 | P0 |

### P1 — 观测呈现与离线验证

| # | 文件 | 改法 | 理由 | P |
|---|---|---|---|---|
| 10 | `v13/demo/fakes.py` | `FakeJudge.answer` 增 mem_* 分支:`mem_type::*`、`mem_rel::*`、`mem_trav::*`、`mem_stop::*` 给合法 noul 答案(默认 0.1;停止问显式低分使 walk 以 depth 收束);不动种子信号表 | fake 模式契约验证(W5)需要恰好覆盖缺口的 mock(mgraph README #17/#19) | P1 |
| 11 | `v13/demo/test_demo_b2.py`(新)+ `harness.py` | fake 模式 gate(库 `agent_v13_demo_b2_test`,`setup_db_b2.build`):断言 1 read off → next_action skip → 零 run_round → refresh accepted → 活动 artifact 无 memory_graph 段、session 不 failed;断言 2 翻 read on(经 `demo_mgraph_policy_bump`)→ 下一回合 walk steps≥1 → settle accepted → 段出现 → 段 content_hash 可在 artifacts 取到 inline 且哈希自校验 → 每行 provenance 七键齐;断言 3 步数帽(mock 永不停)→ 触帽 → 仍 accepted → walk 仍 open → 无段;断言 4 blob 对账(两会话同内容段 → 按 content_hash 去重只有一行) | W3 契约的离线回归;blob 陷阱钉死;AGENTS「测试用 Fake」纪律 | P1 |
| 12 | `v13/demo/b2_converse.py`(新) | headless 同型驱动(driver + PortREST + RawAsyncTransport,对话文本/埋点同 trial),按 §2.2.1 五阶段跑 A/B,落 `b2trial/ab_log.json`(每回合 panel 快照 + A_off/A_on 全文 + walk 统计 + jc 增量) | 无浏览器端对话回放时(2.12 无 testing 模块,trial 同款降级)的脚本化 A/B | P1 |
| 13 | `v13/demo/b2_observe.py`(新) | 只读观测(复制 `mem2_observe.py` 改库名):加 memory_graph 段/walk/provenance 查询与 `audit/memory_degraded` 计数 | 事后核查与 trial/rerun 基线对照 | P1 |

### P2 — 锦上添花

| # | 文件 | 改法 | 理由 | P |
|---|---|---|---|---|
| 14 | `v13/demo/chainlit.md` | 欢迎词补记忆控制台与 A/B 说明 | 上手成本 | P2 |
| 15 | `v13/demo/app.py` | Chainlit actions 按钮替代文本命令;build 前零成本预检(段数/段长,V3005 前置) | 操作体验;trial 异常 1 的前置防护 | P2 |

### 不改(及理由)

| 文件 | 理由 |
|---|---|
| `v13/demo/sql/demo_api.sql`、`setup_db.py` | envelope 基面;B2 无关;基面 demo 行为必须不变 |
| `v13/demo/sql/demo_api_mem.sql`、`setup_db_mem.py`、`setup_db_mem2.py` | 15 文件试验库(mem/mem2)可复现性;`demo_refresh_context` 被搬进新文件而非改旧 |
| `v13/demo/mem2_converse.py`、`mem2_mgraph.py`、`mem2_observe.py`、`memdrive_*.py`、`memtrial*/` | v1/v2 试验历史留档;W3 分支进 driver 核心后其 `MemDriver` 覆盖成为死代码但不再运行,不删 |
| `v13/` 任何文件、`v13/load.py`、根 `pyproject.toml`、`.gitignore` | 边界:只碰 gitignored demo 树;B2 已交付,无 v13 侧改动需求 |

## 4. 风险与回退

| 风险 | 影响 | 处置 |
|---|---|---|
| PostgREST 池回收影响在飞请求 | build tick 期间其它 RPC 断 | 命令限 hub 空闲(`st.busy`);单操作者 demo 可接受;回收后重试至多一次 |
| fake 模式 walk 不可行(mock 路径的 `judgment_calls` 不落 provider/model → capture_pm V3002) | W5 gate 断言 2/3 退化为「异常仍 settle」路径 | 实施期先验证;若否,fake 只保断言 1(no-op),段断言挪到 real 冒烟(opt-in) |
| 真实判断低置信 → `budget_exhausted`(D16 已知,trial 4/8、rerun 5/8) | A/B 播种回合失败 | 埋点消息用陈述句;失败回合的 user/message 仍入档,不阻塞建图 |
| 段出现但回答未变(注入格式/位置不当) | A/B 判定无效 | `format_memory_block` 头部指令显式;先跑 b2_converse 无头对照再上 UI |
| refresh RAISE(belt 漂移) | 回合 terminal | 按 B2 §3.9 当程序缺陷:gate 先红,不静默 |

**回退**:删 demo 树新文件(`sql/demo_api_b2.sql`、`setup_db_b2.py`、`test_demo_b2.py`、`b2_*.py`)→ `DROP DATABASE agent_v13_demo_b2`(及 `_test`);driver/app 等改动随 demo 树整体 gitignored,`git checkout` 不涉及任何 tracked 文件;`v13/`、基面 demo、mem/mem2 库零接触。

## 5. 明确不做

- **不提交任何东西**(含本计划文档;v13 惯例,demo 相关设计留本地)。
- 不改 `v13/` 任何文件、不追加 `SQL_LOAD_ORDER`、不修 mgraph/mgraph_assembly 已知问题(锚池方向不对称=W4 未触发、CJK superset 路由、contradicts 判断质量、关系信封 5 参已修则不再涉及)。
- 不做 consolidation 自动化/队列驱动的 demo 化(M4 链路的 UI 化);不做自动投影调度与 walk retention(pg_cron 闸;手动命令)。
- 不做多会话并行 hub、token 流式、生成提示整体切换 `v13_render_wire`(P2 备选,不作数)。
- 不做 fake 模式的效果判定(只做契约形态);不把真实 provider 冒烟塞进 gate(沿用 opt-in 惯例)。
- 不改 `demo_api.sql` 基面、不改 mem/mem2 试验面、不删 trial 脚本。

## 6. 偏差记录(实施期填写)

2026-09-24 P0 实施期填写(W1–W4 全交付 + W5 fake gate 35 PASS + real 冒烟 GREEN;
详见下表;fake gate 命令与 README 同步)。

| # | 工作项 | 计划原文 | 实际 | 处理 |
|---|---|---|---|---|
| 1 | W1 §2.3.3 | `demo_mgraph_run_round(uuid,text,int,text)` | 签名加一个 `p_api_key text` → `(uuid,text,integer,text,text)` | walk 的真实 ask 需要 shim key 而计划参数面无处可传;与 demo_parse 的 p_shim_key 同型。入 setup_db_b2 的 DEMO_FUNCTIONS |
| 2 | W1 §2.3.3 | run_round 函数体「先 preload 再设(含 api_key)」 | api_key 移到 preload **之前**尽力设,`EXCEPTION WHEN insufficient_privilege THEN NULL`;mock_response 在 preload 后重设 | W5 旧实测重演:已加载连接上 resolve_login 设 SUPERUSER_ONLY 项一律 permission denied;新连接 pre-load placeholder 值存活(demo_parse 同型)。provider 仍绝不设(capture_pm 回落 judgment_calls,实演回归绿) |
| 3 | W1 §2.3.3 | `demo_mgraph_build` 属主 `v13_resolve_login` | 属主 **postgres**(与 rebuild/policy_bump 同面) | `v13_mgraph_build` 是 INVOKER,体内 temporal 重连 `DELETE FROM memory_links(origin='temporal')` 只授 resolve INSERT 无 DELETE(gate/trial 的 build 全以 owner 跑);resolve 属主 DEFINER 链实测 permission denied。不缩 v13 ACL 面,改属主 |
| 4 | W2 §2.1.3 | pg 面 walk 用 `v13_resolve_login` 连接(connect_as) | PortPG 保持超级用户连接,walk/run_round/build 一调用一条新连接调 demo_* wrapper | wrapper 全部 SECURITY DEFINER,函数体内以属主权限执行——ACL 面不因调用方属主而绕过;REST 面原生走 resolve 属主平面。J8 参考工人形态的「resolve 连接」由 wrapper 属主等效承担 |
| 5 | W2 §2.3.3 | 面板 `last_walk`=「最新行」 | 定义为「当前回合查询×当前 generation×当前策略版本」的确定性 walk(memory_walks 唯一键) | memory_walks 无时间戳列,「最新」不可定义;取当前 turn 的 walk 语义更准 |
| 6 | W3 §2.1.2 | TurnResult.walk 为回合末状态 | 一个回合可能 refresh 两次(walk 落 decisions 后 dec token 再变):首次走图、末次见同 walk 已停即 done;TurnResult.walk 保留末次,gate/冒烟按 refresh 事件聚合断言 | 契约行为不变(两次都 settle accepted);观测面取聚合 |
| 7 | W5 断言 3 | 「mock 永不停→触帽」用真实帽值 `jev*6+8` | 种子策略下帽不可达(6+8 边距就是设计);gate 收窄帽(monkeypatch `MGRAPH_STEP_BASE=2/FACTOR=0`)+ 永不停注入 | 验的还是工人侧帽机制(触帽→停止循环→仍 accepted→walk 仍 open→无段),不碰 SQL 函数体 |
| 8 | W5 断言 4 | 两会话同内容段→按 content_hash 去重只有一行 | 退化为「每个段 content_hash 恰一行 artifacts(kind=context_section)+ 全库无重复行 + 哈希自校验 + inline==live」 | fake 下行 score 含时间衰减(recency halflife 86400s),两会话材料逐字节相同不可构造;检索口径(按 content_hash,不按 effect)已钉死 |
| 9 | W5 前置 | — | fakes.py 提前加了 mem_* 分支(计划 P1 #10) | fake 模式 build 的 ask 走本地 fake-judge HTTP(wire_response→FakeJudge.answer),需要合法 mem_type/mem_rel 答案;顺带与 driver 默认 mock 规格同源 |
| 10 | real 冒烟 | — | 每次探针前必须重投影(`rebuild_transcript_chunks`):lag 按 **seq 差**计(非策展事件数),探针回合的 user/llm 消息叠加前一回合未投影事件很易把 lag 拉过 `max_lag_events=16`→walk skip(degraded)、audit/memory_degraded 落两条(降级面实测正确) | 投影幂等;冒烟脚本 run_probe 内建。UI 的 A/B 手册(README)在步骤 5 前加「可再 `/memory project`」提示即可 |
| 11 | real 冒烟 | — | 播种回合 2–4 `budget_exhausted`(D16 低置信已知,trial 4/8、rerun 5/8 同款) | user/message 仍入档、不阻塞建图与探针;不修 v13 侧行为(边界约定) |
| 12 | W4 | A/B 六步人工清单 | 未起交互式 UI(任务约定 headless);六步链路由 `b2_smoke_real.py` 逐阶段覆盖(播种→建图→基线 A_off→翻版→实验 A_on,输出段/walk/回答) | Chainlit 面命令与渲染已交付,操作者可照 README 手册自跑 |
| 13 | W6(P1) | `b2_converse.py`/`b2_observe.py` | 未实施(P1 不在本次 P0 范围);real 栈无头 A/B-lite 由 `b2_smoke_real.py` 承担,日志落 `b2trial/ab_log.json` | 后续需要「与 trial 同款日志」的脚本化对照时再补 |

额外实施事实(非偏差):walk 统计 real 冒烟实测 `stop=evidence depth=1 edges_used=0 calls=3`(CJK superset 路由已知形态,与 trial/rerun 基线一致);记忆块注入生成提示位 1(system)由 fake gate 断言钉死;`edges_used=0/depth=1` 呈现口径按 §2.2.3 #3 注明。

## References

- `v13/mgraph_assembly/README.md`(W3 工人契约七条、ACL 表、J8/J9 实测、偏差 #10/#11)
- `docs/plans/v13-mgraph-assembly-wiring-plan-2026-09-24.md`(§3.7 驱动、§3.8 并发、§3.9 降级、§1.7 ACL、§1.5 裁决)
- `docs/plans/v13-minimal-agent-loop-demo-2026-09-23.md`(demo 计划:端口协议、RPC 双属主、GUC 顺序、行为边界)
- `docs/investigations/v13-dp9-mgraph-demo-trial-2026-09-24.md`、`docs/investigations/v13-dp9-mgraph-v2-demo-rerun-2026-09-24.md`(实测基线与异常)
- `v13/mgraph/README.md`(⑧ provider 占位符与连接纪律、⑩ 读环步进、#17/#19 mock 精确批)
- `v13/demo/driver.py:224`、`v13/demo/mem2_converse.py:74`、`v13/demo/sql/demo_api_mem.sql:12`、`v13/demo/setup_db_mem2.py`
- 提交:5f801d5/b1a1c86/c65362d(B2 W1–W3)、914790f(关系信封 5 参修复)
