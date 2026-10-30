# v13 最小 agent 循环 demo 计划：批判评审

- 评审对象：`docs/plans/v13-minimal-agent-loop-demo-2026-09-23.md`（下称「计划文件」）
- Baseline：`prompt-exports/oracle-plan-2026-09-23-104045-deep-plan-v13-agent-9b11.md` 中 `## Generated Plan` 之下 Oracle 2（grok-4.7-build-fast-xhigh）产出的完整方案。Oracle 1 网络错误的输出不计。`## Final Prompt` 与 `## Selection` 只作上下文。
- 计划文件自己的 `## Background` 按评审要求不计入 baseline 对照；但其中的事实声明做了抽检，结论见 §3.1。
- 方法：先做 baseline 与计划文件的规范化 diff（剥离 `（观察：…）`/`（任务已核：…）` provenance 标记后逐节比对），再对 load-bearing 的 `file:line` 断言做聚焦读取，最后对三个最高风险假设（GUC 设置、pgmq 授权、systemone 线格式）在 `agent_v13_gucprobe` 库上做了**实机探针**（PG 18.4 / pgembed / envelope stage）。探针库已 drop。

---

## 0. 结论先行

计划文件是 baseline 的**严格超集**：没有丢失任何 implementation-bearing 内容，另加了执行索引 W1–W10 与两处修正说明。这是好的。

但 baseline 里有**两处会在实施第一天就变红的确定性阻断**，计划文件把它们的风险等级写低了；另有**一处整个工件可以被一行 SQL 取代**而计划不知道；以及计划文件自己收紧引用时**引入了 4 处错误的 `file:line`**。

Verdict：**FIX**（10 项，见 §6）。

---

## 1. Baseline 有、计划文件缺失/弱化/泛化的内容

逐节比对（摘要 / 现状分析 9 节 / 决策表 12 行 / mermaid / 行为边界 / 库角色 RPC 11 函数 + 3 视图 + 授权清单 / 超时表 15 常量 / Shim J-A / 生成 / 工具 / 启动恢复 / Chainlit / FakeJudge 表 / 断言 1–14 / shim 测试 / smoke 三子用例 / uv 与忽略 / 文件影响 2 tracked + 18 ignored / D1–D17 / V1–V6 / 实施顺序 1–10 / 人工清单 6 项 / 运行手册 / 错误表 7 行）：

**内容零遗漏。** 计划文件还新增了 baseline 没有的 `## 执行索引`（W1–W10，含 Done-when 与 Deps），以及摘要里一段「相对探索脚手架的两处修正」。这些都是增益。

唯一的实质弱化是 **provenance 层的丢失**：

- Baseline 在几乎每句事实后面挂 `（观察：file:line）` 或 `（任务已核：…）`，把「已核实观察」与「推论」显式分开。计划文件删掉了全部约 40 处，同时在约 25 处补了内联 `file:line`——覆盖率约六成，且补的部分里有 4 处是错的（§2.4）。
- 被删且未获内联补偿的、比较要紧的几处：
  - `v13/loop/test_loop.py` M3-6（P0 只认锚定的 `llm/message`，`tool/result` 不终结）——计划文件的 route 优先级段没有 M3-6。
  - `v13_core.sql` events 注释词表 vs `v13_complete` 事件分支（`judge/answered` 无写入器）——未补。
  - advance ① 注释 + `v13_core.sql` 对 `blocked_unknown` 的预留说明（`unknown` 是墙）——未补。
  - `v13_complete` 的 CAS 段（不看 `lease_until`）——未补。
  - 策略种子（`turn_budget.max_cycles = 3`）——未补。
  - advance ④ 在 `CASE` 之前 append route——未补。
  - 模板种子 / DP1 needed 的 score 数组长度 4——未补。
  - `v13_effect_envelope` 的字段集合——只在视图段留了半句。

这份计划的相当一部分价值在于「这句话我核过」。删 provenance 而不全量补对内联引用，实施者就无法区分哪些是核实过的、哪些是模型推断——而这正是本次评审要花力气去补的那层。

---

## 2. 未充分规定的接缝 / 未决实质决策 / 矛盾 / 错误引用 / 缺失依赖

按严重度排序。§2.1、§2.2 是阻断级。

### 2.1 【阻断】`v13_send_work` 对 route 登录角色必然失败；计划给的 pgmq 授权不充分

实机探针结果（envelope 库、`v13_route_login`）：

```
pgmq.send 定义: ('send', 'queue_name text, msg jsonb', prosecdef=False)
route→pgmq:  has_schema_privilege('v13_route','pgmq','USAGE')      = False
             has_function_privilege('v13_route','pgmq.send(text,jsonb)') = True
             has_table_privilege('v13_route','pgmq.q_v13_work','INSERT') = False
SET ROLE v13_route_login; SELECT v13_send_work(gen_random_uuid());
  → ERROR: permission denied for schema pgmq
```

`pgmq.send` **不是 SECURITY DEFINER**，所以光有函数 EXECUTE 不够，还必须能进 schema 并能写队列表。

计划文件 L303–308（「另外两条部署 GRANT」）只列了 `GRANT USAGE ON SCHEMA pgmq TO v13_route` + `pgmq.send(text,jsonb)` 的 EXECUTE。实测：

- 只加 `USAGE ON SCHEMA pgmq` → 仍失败（缺表权）。
- 只加 `GRANT INSERT ON pgmq.q_v13_work` → 仍失败（pgmq 的 notify 触发器要更多）。
- **实测可用最小集**：`GRANT USAGE ON SCHEMA pgmq TO v13_route;` + `GRANT INSERT, SELECT, UPDATE ON pgmq.q_v13_work TO v13_route;`

影响面不是边角：`v13_advance` 的 `tool` / `llm` / `human` / `judge` 四个分支都 `PERFORM v13_send_work`（`advance.sql:510/516/522/378`）。只有 sql 快路绕开。所以计划里的**断言 2（「几条」→ sql 快路）会绿，断言 3/4/5/6 会全红**，W5 的 gate 第一步就过不去。

计划文件自己的措辞是「route 登录角色是否拿得到 `pgmq.send` 尚未被 gate 覆盖」——把它写成了「可能需要补一条 GRANT」的待观察项。实际是确定性阻断，而且授权集还给少了。计划说「M3 的工具用例是超级用户跑的」这点是准确的（`v13/loop/test_loop.py:189` 直接 `INSERT INTO effects`），所以现有 gate 确实没覆盖——但这不改变它是阻断的事实。

### 2.2 【阻断】`typesafe.provider` 不是已注册 GUC，`set_config(..., true)` 静默无效；`demo_parse` 必然 V3002

实机探针（envelope 库，全新连接）：

```sql
SELECT set_config('typesafe.provider','deepseek',true);   -- 返回 'deepseek'
SELECT current_setting('typesafe.provider', true);        -- 返回 ''      ← 静默丢失
SELECT set_config('typesafe.provider','deepseek',false);  -- 会话级
SELECT current_setting('typesafe.provider', true);        -- 返回 'deepseek'
```

对**从未注册**的自定义 GUC 名，`set_config(..., is_local => true)` 建的是事务级占位，`current_setting` 读不到。`typesafe.provider` 不在 pg_typesafe 的 GUC 清单里（`typesafe.c` 的 `_PG_init` 只定义 `api_key`/`endpoint`/`model`/`timeout_ms`/`mock_response`/`batch_size`/`http_concurrency`；`v12/indb/README.md` 的清单同样没有它；`v13/resolve/v13_resolve.sql:151` 的注释也明说「可能不在 GUC 清单」）。

后果：`v13_guc_required('typesafe.provider')` 必然抛 `V3002: GUC typesafe.provider must be configured`，`v13_parse` **永远失败**。计划文件 L280 的 GUC 顺序「全部 `set_config(..., true)`」对五个 pg_typesafe 已注册 GUC 有效，对 `typesafe.provider` 无效。

计划文件的 V1 问对了问题，但**预期和退路都错**：

- 预期写「成功是预期（两段式自定义 GUC 占位）」——实测不成功。
- 退路 D10 写「V1 失败时改 `STAGE=twophase`」——这会丢掉 `judgment_calls` / `judgment_cache` / 全局 `request_hash` 整个 DP2 判断平面，代价远大于正确修法。

**正确修法是一行部署面 DDL**，实测可行且非超级用户可读：

```sql
ALTER DATABASE agent_v13_demo SET typesafe.provider = 'deepseek';
-- 之后 set_config('typesafe.provider', X, true) 也开始生效
```

附带一条：`typesafe.model` 的扩展默认值是**空串**，实测未设置时 `v13_guc_required('typesafe.model')` 同样抛 V3002。所以计划 GUC 顺序第 2 步「两者空白则 `RAISE`」必须真的执行，不能省。

顺带排除一个我本来担心的问题：`typesafe.api_key` 带 `GUC_SUPERUSER_ONLY`、`typesafe.endpoint` 是 `PGC_SUSET`。实测在非超级用户连接的 `SECURITY DEFINER`（属主 `v13_resolve_login`）函数里，`set_config(..., true)` 对这两项**都成功**。PostgreSQL 对 `set_config()` 不执行这两个 flag 的检查。所以 shim key 穿透 PostgREST 连接池这件事本身不构成阻断。

### 2.3 【设计冗余】V3 抓包整条链可以被 `typesafe_last_request()` 取代

读 pg_typesafe 源码（`../pgembed/pgbuild/pg_typesafe-93a5acbb…/typesafe.c`）：

```c
execute_request(const char *request_json)
{
    save_last_request(request_json);          /* ← 在 mock 短路之前 */
    if (typesafe_mock_response != NULL && typesafe_mock_response[0] != '\0')
        return pstrdup(typesafe_mock_response);
    return http_post_json(request_json);
}
```

所以 **mock 模式下**一次 `SELECT typesafe_last_request()` 就给出完整线格式，不发任何 HTTP。

实机取到的线格式（envelope 库、种子目录、9 问、mock 判定）：

```
WIRE TOP-LEVEL KEYS: ['state', 'model', 'questions']
QUESTIONS type: dict | count: 9
  'risk'  -> ['type','criteria','instructions'] type=score
  'tool'  -> ['type','criteria','instructions'] type=choice
  'intent'-> ['type','criteria','instructions'] type=choice
STATE keys: ['tools','derived','messages']
```

即 `{"state": …, "model": …, "questions": {<signal>: {type, instructions, criteria?}}}`，`questions` 是**以 signal 为键的 JSON 对象**。

响应侧也已由源码定死（`parse_response_json`）：顶层必须是 object、`model` 必须是 string、`answers` 必须是 object；**`usage` 可选**。计划写的 `{model, answers, usage}` 正确。

另外 `typesafe_ask(jsonb, jsonb, text DEFAULT NULL)` 是三参带默认（`typesafe--0.0.1.sql:63-70`），`v13_resolve_judgments` 的两参调用合法，model 回落 `typesafe.model` GUC。计划没写签名，实施时容易误判成必须三参。

结论：`capture_wire.py` + `fixtures/typesafe_request.http` + 「线适配单测在 fixture 不存在时失败」+ W8 的抓包步骤 + V3 这个停工条件，**全部可以由一行 SQL 取代**。少一个进程、一个 fixture、一个停工条件。

### 2.4 【引用错误】计划文件新增的内联 `file:line` 有 4 处不准确

| 计划文件位置 | 写的 | 实际 | 来源 |
|---|---|---|---|
| L94 现状分析→环在调用方 | `v13_route` 优先级在 `advance.sql:125-170` | `v13_route` 在 `advance.sql:110-163`（`END $$;` 在 163） | **计划文件收紧时引入**；baseline 只写「`advance.sql` 中 `v13_route`」 |
| L15 Background→状态词表 | events 开放词表在 `v13_core.sql:41-46` | 词表在 `v13_core.sql:33-36`；41-46 是 `at`/主键/唯一约束 | baseline 与计划文件都有 |
| L142 Background→服务器与忽略 | `.venv` 在 `.gitignore:9` | `.venv` 在第 10 行；第 9 行是 `# Virtual environments` 注释 | baseline 与计划文件都有 |
| L636 References→本方案新增落点 | `v13/loop/README.md:12-17` | README 共 24 行；运维纪律 1-5 在 13-17，**纪律 6（advance 前设 250ms/5s）在第 18 行** | **漏掉本方案唯一依赖的那条纪律** |

`v13/loop/README.md:7-8` 实际只有第 7 行有内容（第 8 行空），可接受，不必改。

### 2.5 【未规定的接缝】慢路超时取自冻结信封，不是 `demo_resolve_batch` 的 `p_timeout_ms`

`v13_resolve_judgments`（envelope 版，`v13_envelope.sql` 约 719-721）在调 `typesafe_ask` 之前：

```sql
IF p_env->>'timeout_ms' IS NOT NULL THEN
  EXECUTE format('SET LOCAL typesafe.timeout_ms = %L', p_env->>'timeout_ms');
END IF;
```

值来自 `v13_judgment_envelope` 冻结的 `timeout_ms`，会**覆盖** `demo_resolve_batch` 先 `set_config` 的那个。

计划文件 L271 写「同样的 GUC 顺序」，L310 起的超时表给 `TYPESAFE_TIMEOUT_MS = 30000`，读起来像 `p_timeout_ms` 是权威设置点。实际：

- real 模式：信封里的值与 `p_timeout_ms` 同源（Settings 冻结），无差异。
- fake/mock 模式：信封 `timeout_ms` 为 NULL，`SET LOCAL` 被跳过，`p_timeout_ms` 才生效——而 fake 模式根本不发 HTTP。

功能上不出错，但**计划对慢路超时权威设置点的描述是错的**，与它对 advance 超时「权威设置点是 advance 语句之前的那条语句」的严格态度不一致。同类未提的还有：`decisions.provider/model` 与 `judgment_calls.provider/model` 都取自 `p_env->>'provider'/'model'`（冻结值），不是 GUC。

### 2.6 【未规定的常量】恢复用的 `lease_owner` 字面量从未被钉住

启动恢复第 1 步按 `lease_owner = demo-chainlit` 过滤；REST 端口还把它写进查询串（`GET /demo_effect_claims?...&lease_owner=eq.demo-chainlit`）。但 `demo_claim(p_worker, p_lease_ms)` 的 `p_worker` 由 driver 传，**计划全文没有规定这个值，也没规定它放 `settings.py`**。

一旦 driver 传的不是 `demo-chainlit`，恢复过滤器静默匹配 0 行 → 本 worker 的 claim 不被 fail-settle → `v13_requeue_stale` 把它们收成 `unknown` → 会话永久楔死。这是一个**静默失败**，与计划自己在别处坚持的「配置错误要响亮失败」相悖。

### 2.7 【缺失的不变量】`ux_v13_effects_single_active` 与 `v13_claim` 的 `op_seq` 死臂

`v13_core.sql` 有：

```sql
CREATE UNIQUE INDEX ux_v13_effects_single_active
  ON effects (session_id) WHERE status IN ('ready','claimed');
```

「同一时刻至多一个活跃工作单元」由 DDL 执法。**计划全文没提。** 它是 hub「单认领者」模型、judge 慢路「一个活跃 effect」推理、取消路径、W6 临时插工具用例的共同前提。

`v13_claim` 的谓词第二臂 `op_seq = (SELECT min(op_seq) …)`（`v13_core.sql:289-291`）：全树 grep 确认 `op_seq` **只有声明、没有任何写入点**（`v13_core.sql:116` 注释即「并行序留缝(ch8)，DP1 恒 NULL」）。所以计划「`v13_claim` 全局领最早的 ready 行，不按 session 过滤」是对的，但这个正确性**依赖 `op_seq IS NULL` 恒真**。将来若加载到给 `op_seq` 赋值的 stage，claim 语义会静默变成「按 (session, mutation_scope) 头序领取」，而计划的「加载停在 `envelope`」正是在无意中保护这条谓词——应当写明。

### 2.8 【缺失依赖】`demo_claim` 的补列是第二次读，不是 `RETURNING`

`v13_claim` 的 `RETURNING` 只有 `{effect_id, attempt_no, fence, kind, request}`。计划的 `demo_claim` 要把 `idempotency_key`/`session_id`/`tool_name` 并进返回对象，只能在**同一事务**里再 `SELECT` 一次 `effects`。计划没写这个第二次读，也没写它必须与 `v13_claim` 同事务（PostgREST 每 RPC 一事务天然满足；测试端口必须显式保持同事务，否则读到的是 claim 之后可能已变化的行）。

风险低（hub 是唯一认领者），但是一处未规定的实现细节。

### 2.9 【矛盾】断言 3 与 driver 的幂等集合设计互相矛盾

断言 3 写「同一 `idempotency_key` 的**第二次 complete** 不会出现第二份 preview 副作用（hub 的 set）」。但同一 `(attempt, fence)` 的第二次 `v13_complete` 会走终态重入守卫返回 `replay`，`v13_complete` 不会重写 result。也就是说：如果 driver 真的发了第二次 complete，测到的是 SQL 的 replay，**不是** hub 的幂等集合。driver 应该在调 complete **之前**就短路。措辞需要改。

---

## 3. 代码反证的 / 任务不要求的 / 被更简设计完全取代的

### 3.1 代码反证的：无

已逐条抽检的 load-bearing 声明，除 §2.4 的四处引用外**全部准确**：

- `v13/load.py:17-50` 的 `SQL_LOAD_ORDER` 与 `STAGE_THROUGH`（loop=3 / twophase=4 / envelope=5）；`files_through` 在 53-55。
- `v13_core.sql:267` `v13_claim`、`:300` `v13_complete`、`:662` `v13_append_event`、`:932-956` 种子工具。
- `advance.sql:186-190` `v13_send_work` 的函数体确为 `pgmq.send('v13_work', …)`。
- 策略种子：`resolve_fast_path = {"max_batches":1,"batch_questions":32}`、`turn_budget = {"max_cycles":3}`、`resolve_retry = {"cap":2}`、`effect_attempt_cap` 五 kind 全在。
- 阈值带：`intent`/`gate_action`/`tool` pass `[0.75, Infinity)`、`risk` reject `[2.25, Infinity)`、`gate_off_topic` reject `[0.75, Infinity)`、param/stated pass `[0.60, Infinity)`。
- `v13_canonical_state`：三类型 + `seq <= last_user_seq OR payload->>'origin_user_seq' = last_user_seq` 双重条件 + 内层 `ORDER BY seq DESC LIMIT 20` 外层按 seq 升序——与计划描述的 prompt 窗口逐条一致。
- `v13_effect_envelope` 剥 7 键、留 `budget`/`templates`/`groups`/`needed`/`provider`/`model`/`timeout_ms`/`ctx`/`goal_hash`；`request` 里确实没有 API key。
- `v13/resolve/v13_resolve.sql:661` = `CREATE FUNCTION v13_parse`；`v13_economy/v13_economy.sql:353` 替换 `v13_parse`；`v13_recall/v13_recall.sql:486` 替换 `v13_judgment_envelope`；`v13/characterize/setup_db.py:23-31,33-45`。
- `v8/loop/runtime.py:235` = `class DeepSeekLLM`，env 名/URL/receipt 语义如计划所述。
- `v8/compat/test_compat.py:1122` `SmokeOutcome`、`:1133` `test_real_provider_smoke`、`:1146-1153` credentials_absent→not_run+exit 2、`:1164` 「never downgraded to not_run」。
- `v13/twophase/test_twophase.py:143-147` 确为 `G-ctx1-5(b)` 的 `mock_response` 源码扫描。
- `v6/workbench_demo/app.py` 确为 821 行。
- `v_session_timeline` 确实只在教程 ch15:35 出现、v13 SQL 里没有。
- Background 的「72 tracked 文件 / 14,470 行 SQL / 14 stage 目录 / 无 fakes.py、无 demo、无 harness」逐项核实为真。

**并且断言 1 的 tripwire 我实测复现了**：种子目录 + 9 问完整 mock → `remaining = 0`、`asked_questions = 9`、`failed = false`；`needed = 5 固定信号（intent / gate_action / gate_off_topic / risk / tool）+ 4 个 param/stated = 9`。这条最脆的断言站得住。

### 3.2 任务不要求的（scope creep，应标记而非追加）

用户原始需求是「Chainlit + PostgREST + DeepSeek env key + uv in v13/ + 不上 GitHub」。以下超出该边界：

- **`demo_pre_request` / `demo_apply_timeouts` / PostgREST `db-pre-request` / V4 / 断言 12**：advance 的 250ms/5s 护栏是 v13 的运维纪律，不是 demo 的验收标准。它带来 2 个函数、1 个对 `request.path` GUC 的依赖、1 个验证项、1 条断言，以及「pre-request 看不到路径就退到 45s」的半成品风险。建议标注为**可选，默认不做**：`demo_advance` 由 driver 在调用前 `SET LOCAL`（测试端口已经是这么做的），REST 端口接受默认超时或用固定 `statement_timeout`，不读 `request.path`。
- **`port_rest.py` 的双端口抽象**（`contract.py` 的 11 方法协议 + 「`driver.py` 不分支 REST 还是 psycopg」）：demo 里 pg 端口只被测试用、rest 端口只被 app 用，两者从不同时存在。这个抽象是为「两边方法相同」付的税。可以留，但应意识到它没有第二个消费者。
- **`SLOW_PATH_BATCH_CAP = 4` 与 `MAX_TICKS = 16` 的「最多 4 次 judge claim」推导**：`effect_attempt_cap.judge = 4`，但 `resolve_retry.cap = 2` 会先到（常态分支），`judge_attempts` 只是 belt（`advance.sql` ③ 的注释自己这么写）。tick 预算按 4 次 judge claim 算偏松。

### 3.3 被更简设计完全取代的

- **`capture_wire.py` + `fixtures/` + V3**：被 mock 模式下的 `SELECT typesafe_last_request()` 完全取代（§2.3）。这是计划里唯一一个「整个工件可以被一行 SQL 替掉」的项。
- **`p_shim_key` + shim 的 `Authorization` 校验**：`resolve_api_key()` 在 GUC 空时回落 `TYPESAFE_API_KEY` 环境变量、再空则 RAISE，所以 shim 确实需要一个非空 secret。但 shim 只绑 `127.0.0.1`、单操作者、unix socket trust——为这个威胁模型引入「每进程轮换的共享秘密 + 一个 RPC 参数 + 断言 11 钉的键集合 + 人工清单里查 key 泄漏」是过度设计。更简设计：shim key 作为 `ALTER DATABASE … SET typesafe.api_key` 的建库期固定值（与 `typesafe.provider` 同一条路径处理），或干脆不校验。**这不构成阻断**（§2.2 末尾已实测 `set_config` 可写），是复杂度取舍，应显式记为可删。

---

## 4. 计划与 export 都缺失的：ownership / lifecycle / 失败行为 / 取消 / 可测性

### 4.1 PostgREST 与 pgembed 的生命周期归属没有 owner

- 计划让操作者在三个终端手工起 setup_db / postgrest / chainlit。`setup_db.py` 会 `DROP DATABASE … WITH (FORCE)`，而 PostgREST 持有到该库的连接池。D14 记了「重建库后必须重启 PostgREST」，运行手册也写了「重建数据库之后先停 PostgREST 再 setup_db」——但 **W3/W4 的验证步骤都是直接跑 `setup_db.py`，没有「PostgREST 不能在 build 期间活着」的前置检查**。建议 `build()` 在 DROP 前探测 `pg_stat_activity` 里非本会话的 `agent_v13_demo*` 连接并响亮失败。
- pgembed 本身：`server.get_server()` 幂等，但三个进程谁负责退出时 `cleanup()`？计划没说。建议明确：**pgembed 的生命周期归 Chainlit 进程**（唯一长驻进程，退出即停），PostgREST 只连不管。

### 4.2 取消的粒度比计划写的粗

- 计划写「hub 在每次 RPC 之间查看」取消标记。但 hub 串行处理多会话，生成 HTTP 超时 60s。会话 B 的 `on_stop` 在会话 A 的 60s HTTP 在飞期间不会被查看。单操作者 demo 可接受，但计划把它写成了取消是及时的。
- 取消标记的生命周期未定义：一次性？按 turn？`on_stop` 后「sid 离开 active」，但同一 sid 的下一条消息在旧 tick 还在飞时到达，计划只处理了「已有在飞 tick 则回绝」，没处理「旧 tick 结束后、新 tick 开始前」这个窗口里标记是否该清除。

### 4.3 `demo_post_message` 的 RAISE 在 REST 面上的失败形状未定义

断言 8 测的是 psycopg 直调抛异常。经 PostgREST，plpgsql `RAISE` 变成 400 + `{code, message, details, hint}`。`port_rest.py` 要把它映射成 UI 消息，而 L614 起的「错误时操作者看到什么」表没有这一行（表现在有 shim/DeepSeek/V3001/55P03/stale/replay/PostgREST 连接失败/unknown 七种，没有「用户文本被拒」）。

### 4.4 可测性：driver 的核心分支没有不联网的测试钩子

- `driver.py` 的 tick 循环、慢路分派、取消、恢复都只能通过真实 `demo_*` RPC 驱动。计划只在「Fake 与真实共用一个 driver。差异只在注入物」列了 `answer_mock` / `generate` / `tools[...]` 三个名字，**没有定义它们的签名**。
- 断言 13/14 依赖「手工把一行 llm effect 留在 `claimed`」这类库态构造，但没说什么 fixture 函数承载、是否会污染后续断言。断言 2 的 pgmq 深度比较、断言 5 的「`effects` 中无 `ready|claimed|unknown`」都对库态敏感，顺序耦合没有说明。
- 断言 3 的措辞与 driver 设计矛盾（§2.9）。

### 4.5 shim 的线程模型与 Chainlit 事件循环的交互

- shim 是「线程 HTTP 服务」，`deepseek.py` 同步，hub 用 `asyncio.to_thread`。但 shim 自己也在一个线程里，它调同步的 `chat_completion`（最多阻塞 25s）。若 PG 的 `typesafe_ask` 与 hub 的生成同时到达，**shim 线程会被生成请求占住，而 PG 那边在等 shim 的 25s 超时**。计划没写 shim 用 `ThreadingHTTPServer` 还是单线程 `HTTPServer`——这是一个会在真机冒烟里暴露的死锁面。
- shim 在「导入 app 模块时」启动 + once flag。`chainlit run app.py -w` 的 reload 会重新 import，计划说 once flag 防重复监听，但没说不 listen 时旧 socket 的清理。

---

## 5. 会实质改变设计或实施顺序的问题

1. **`typesafe.provider` 用 `ALTER DATABASE SET` 注册，还是接受 V1 失败就降级到 `twophase`？** 前者保留 DP2 判断平面（`judgment_calls`/`judgment_cache`/全局 `request_hash`），后者丢掉它们但避开 `v13_guc_required`。这直接决定 W3 的 `build()` 内容、W6 的慢路用例形态、W9 的 R-judge 断言。**最高优先级**，且答案几乎肯定是前者（一行 ALTER，实测可行）。
2. **pgmq 授权的完整最小集是什么？** 我实测 `USAGE ON SCHEMA pgmq` + `INSERT, SELECT, UPDATE ON pgmq.q_v13_work` 可用。若想更窄需确认 pgmq notify 触发器到底要哪些。这决定 W4 能否绿，也因此决定 W5 能不能开始。
3. **advance 的 250ms/5s 护栏是 demo 的必需项还是可选装饰？** 必需则 V4 必须在 W10 之前；可选则 W4/W5 可去掉两个函数和断言 12，实施顺序能合并两步。用户原始需求没提超时护栏。
4. **shim 是否保留 `Authorization` 校验？** 保留则 shim key 需要穿过 PostgREST 连接池（每进程轮换 or `ALTER DATABASE` 固定值二选一）；不保留则 `p_shim_key` 参数、断言 11 的键集合、人工清单的 key 检查全部简化。这影响 `demo_parse` 的签名——而断言 11 钉的就是它。
5. **恢复用的 worker 名由谁定？** 见 §2.6。它是一个字面量，但决定 W5 断言 13 的写法，且错了是静默楔死。
6. **Chainlit 2.12.0 在本地装得上吗？** W2 的验证命令是 `import chainlit`。2.12.0 是社区维护版，若与根项目 Python 3.12 + 现有依赖冲突，W2 就红，后面全部顺序作废。它是实施顺序第 2 步，但失败会推翻整个顺序——应在 W1 之前先单独跑一次。

---

## 6. Verdict: FIX

按计划文件的精确位置给出的可执行修正：

1. **（阻断，L303-308「另外两条部署 GRANT」）** 把 pgmq 授权改为实测可用的最小集：
   ```sql
   GRANT USAGE ON SCHEMA pgmq TO v13_route;
   GRANT INSERT, SELECT, UPDATE ON pgmq.q_v13_work TO v13_route;
   ```
   删掉「授实际被 `v13_send_work` 解析到的那一个」这种只授函数的写法（`pgmq.send` 非 SECURITY DEFINER，光有 EXECUTE 不够），并把「route 登录角色是否拿得到 `pgmq.send` 尚未被 gate 覆盖」改成确定性陈述：不加这两条，`v13_advance` 的 tool/llm/human/judge 四分支全失败。

2. **（阻断，L280-286 GUC 顺序 + `build()` 顺序 + V1/D10）** 在 `build()` 的 `run_psql` demo SQL 之前加一步 `ALTER DATABASE {db} SET typesafe.provider = 'deepseek';`；把 GUC 顺序第 1 步改成「确认 `typesafe.provider` 已由数据库级 SET 注册——`set_config(..., true)` 对未注册自定义 GUC 静默无效，`current_setting` 返回空串」；把 V1 的预期从「成功是预期」改为「注册后成功」，并**删掉 D10 的「降级到 `twophase`」退路**（代价是丢掉 DP2 判断平面，不值得）。

3. **（设计，L338-359 Shim 节 + L84 W8 + L501 文件影响 + L559 V3 + L575 实施顺序 8）** 用 mock 模式下的 `SELECT typesafe_last_request()` 取代 `capture_wire.py` / `fixtures/` / V3：删掉文件影响表里的 `capture_wire.py` 行与「线适配单测在 fixture 不存在时失败」，把实施顺序 8 改为「mock 模式下取 `typesafe_last_request()` 钉死线格式 → 实现 `shim.py` → 跑 `test_demo_shim.py`」。同时在 Shim 节写明：请求体 = `{state, model, questions}`，`questions` 是以 signal 为键的 JSON 对象；响应只强制 `model`(string) + `answers`(object)，`usage` 可选；`typesafe_ask(jsonb,jsonb,text DEFAULT NULL)`。

4. **（引用，L94 / L15 / L142 / L636）** 改四处：`advance.sql:125-170` → `advance.sql:110-163`；`v13_core.sql:41-46`（events 词表）→ `v13_core.sql:33-36`；`.gitignore:9` → `.gitignore:10`；References 的 `v13/loop/README.md:12-17` → `12-18`（补回纪律 6，即本方案依赖的 advance 超时护栏）。

5. **（规定，L310 超时表）** 在表里加一行 `WORKER_NAME = "demo-chainlit"`，并写：「启动恢复的 `lease_owner` 过滤器与 `demo_claim` 的 `p_worker` 必须共用这一个常量；不匹配时恢复静默匹配 0 行，会把本 worker 的 claim 交成 `unknown` 并楔死会话」。

6. **（规定，L271 `demo_resolve_batch` 行 + L310 超时表）** 补一句：慢路的实际超时取自冻结信封的 `envelope.timeout_ms`（`v13_resolve_judgments` 会 `SET LOCAL` 覆盖 GUC），`demo_resolve_batch` 的 `p_timeout_ms` 只在信封 `timeout_ms` 为 NULL 时生效；`decisions`/`judgment_calls` 的 provider/model 同样取自冻结信封而非 GUC。

7. **（规定，L90-95「环在调用方，状态在库里」）** 补一段：`ux_v13_effects_single_active`（每 session 至多一个 `ready|claimed` effect，DDL 执法）是 hub 单认领者与 judge 慢路的前提；`v13_claim` 的 `op_seq` 臂在全树无写入点故恒真，「全局领最早 ready 行」的正确性依赖加载停在 `envelope`，不要在计划里把这当成无条件事实。

8. **（规定，L614「错误时操作者看到什么」表）** 加一行：`demo_post_message` 空白/超长 → UI 提示文本被拒（PostgREST 400），库态无变化。

9. **（范围，L277/L280/L296/L305 授权清单/L412 断言 12/L527 V4/L570 实施顺序 4）** 把 `demo_pre_request` / `demo_apply_timeouts` / V4 / 断言 12 标注为「可选（v13 运维纪律，非 demo 验收项）」并默认不做；若不做，从函数表与 `demo_anon` 授权清单去掉这两个函数，并把实施顺序 4 与 5 合并为一步。

10. **（顺序，L564 实施顺序开头）** 在步骤 1 之前插一步 0：先单独跑 `uv run --project v13/demo python -c "import chainlit"` 验证 2.12.0 装得上（社区维护版，且是整条顺序第 2 个依赖），再动 `.gitignore` 与计划文件。

---

## 附：本次实机探针的可复现要点

- 探针库：`agent_v13_gucprobe`（envelope stage，已 drop）。
- `set_config('typesafe.provider', X, true)` 对未注册自定义 GUC 静默无效（`current_setting` 返回 `''`）；`is_local=false` 或 `ALTER DATABASE … SET` 后生效。
- `v13_route_login` 调 `v13_send_work()` → `permission denied for schema pgmq`；加 `USAGE ON SCHEMA pgmq` + `INSERT, SELECT, UPDATE ON pgmq.q_v13_work` 后成功。
- mock 模式下 `SELECT typesafe_last_request()` 返回 `{"state": …, "model": …, "questions": {<signal>: {type,instructions,criteria?}}}`。
- 种子目录 + 9 问完整 mock：`v13_parse` → `remaining=0`、`asked_questions=9`、`failed=false`。
- 非超级用户连接的 `SECURITY DEFINER`（属主 `v13_resolve_login`）函数里，`set_config(..., true)` 对 `typesafe.api_key`（`GUC_SUPERUSER_ONLY`）与 `typesafe.endpoint`（`PGC_SUSET`）均成功。
