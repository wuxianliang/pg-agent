# v13 demo 运行手册(本地副本)

> 权威文本是 `docs/plans/v13-minimal-agent-loop-demo-2026-09-23.md`(基础面)与
> `docs/plans/v13-b2-demo-chainlit-plan-2026-09-24.md`(B2 面);本文件只是
> 操作者手边的副本。`demo_v13/` 整个目录 gitignored,永不提交。

最小 agent 循环 demo:Chainlit 聊天前端(:8000)→ PostgREST REST 面(:3000)→
PG 里的 v13 状态机(`v13_parse`/`v13_advance`/claim→IO→complete),LLM 判断经
本机 shim(:8765)译成一次 DeepSeek `/chat/completions`,生成由 Chainlit 进程
内适配器直调 DeepSeek。DeepSeek key 只活在进程环境变量里,不过 REST/DB。

## 端口表(全部只绑 127.0.0.1)

| 进程 | 端口 | 说明 |
|---|---|---|
| Chainlit(终端 B) | 8000 | 浏览器只连它 |
| PostgREST(终端 A) | 3000 | demo RPC / 只读视图的唯一 REST 面 |
| J-A shim(real 模式,Chainlit 进程内) | 8765 | `typesafe.endpoint` 钉住的对端 |

## 运行手册

```text
# 终端 A:仓库根
uv run --project demo_v13 python demo_v13/setup_db.py
# 记下它打印的 socket 目录 ABS(输出里的 [socket] 行)

export PGRST_DB_URI="postgres://authenticator@/agent_v13_demo?host=ABS"
export PGRST_DB_SCHEMAS=public
export PGRST_DB_ANON_ROLE=demo_anon
# (可选,默认不做)export PGRST_DB_PRE_REQUEST=demo_pre_request
export PGRST_SERVER_HOST=127.0.0.1
export PGRST_SERVER_PORT=3000
export PGRST_DB_POOL=10
export PGRST_DB_MAX_ROWS=10000
postgrest

# 终端 B
cd demo_v13
uv run chainlit run app.py --host 127.0.0.1 --port 8000 --headless
```

- `postgrest` 用本机二进制(`brew install postgrest`,主版本 ≥ 14,目标 v16.3),
  不写进 Python 依赖。日志级别保持默认或 warn——RPC body 里有 shim_key。
- Chainlit 端口 8000、PostgREST 3000、shim 8765,三者都只在 127.0.0.1;
  DeepSeek 调用只从 shim 线程和 hub 的生成函数出去。
- 模式:默认 auto(壳里有 `DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY` → real,否则
  fake);`DEMO_MODE=fake|real` 可强制。聊天顶部会发一条模式/会话说明。
  real 模式但无 key:Chainlit 进程在导入期即 `RuntimeError` 拒绝(不开任何
  socket)。fake 模式完全离线(FakeJudge/FakeLLM),不起 shim。

### 重建库的纪律(必读)

**先停 PostgREST 再 `setup_db.py`,建完再启动。** `PGRST_DB_URI` 不可热重载,
`DROP DATABASE` 也会拆掉 PostgREST 的连接;`setup_db.py` 在 DROP 前探测
`agent_v13_demo*` 上的外来连接,池还活着会响亮失败(这是故意的)。pgembed 的
生命周期归 Chainlit 进程(唯一长驻进程);PostgREST 只连不管。

## 人工清单(PostgREST 已听 127.0.0.1:3000、库已建好)

- [ ] `curl -s -X POST http://127.0.0.1:3000/rpc/demo_create_session -H 'Content-Type: application/json' -d '{}'`
      返回 uuid。
- [ ] `curl -s -X POST http://127.0.0.1:3000/rpc/demo_post_message -H 'Content-Type: application/json' \
        -d '{"p_sid":"<uuid>","p_text":"hello manual checklist"}'`
      返回 seq(bigint)。
- [ ] fake 的 `POST /rpc/demo_parse` 带 `p_mock`(见下)返回含 `snap` 与
      `envelope` 的对象,且 `remaining` 为 0。
      `{"p_sid":"<uuid>","p_provider":"fake","p_model":"fake-judge","p_endpoint":"http://127.0.0.1:9/disabled","p_shim_key":"x","p_timeout_ms":30000,"p_mock":"{\"model\":\"fake-judge\",\"answers\":{},\"usage\":{}}"}`
      (answers 留空仅当 decisions 已有缓存;干净库上请用 9 信号的完整 mock,
      或直接以 Chainlit fake 模式代跑这一项。)
- [ ] `curl -s 'http://127.0.0.1:3000/demo_session_timeline?session_id=eq.<uuid>&order=seq.asc'`
      能看到 `user/message`。
- [ ] `curl -s -X POST http://127.0.0.1:3000/rpc/v13_advance -H 'Content-Type: application/json' -d '{}'`
      是 404/权限错误,而不是执行成功(demo_anon 没有任何 `v13_*` EXECUTE)。
- [ ] 浏览器开发者工具:Chainlit 页面的请求没有发往 `:3000`,任何报文里都
      没有 `DEEPSEEK_API_KEY`。

## 错误时操作者看到什么

| 情况 | UI | 库状态 |
|---|---|---|
| shim 没起来 / DeepSeek 5xx / 超时 | 传输错误,该 sid 停止 | parse 回滚,用户消息还在,没有新 decisions |
| `V3001` | 时间线上的 `resolve/failed`,hub 继续 | 达 cap 后 human,最终 `failed` |
| advance `55P03` | 「会话忙」并再试一次 | 回滚,零新事件 |
| `complete` 返回 `stale` | 租约失效,停止 | 不拿旧令牌重试 |
| `complete` 返回 `replay` | 当作已经结算 | 无第二次语义事件 |
| PostgREST 连接失败 | 横幅 | 无变化 |
| 恢复后仍有 `unknown` | 说明 ch12 不在本 demo | 该 sid 不再拨格 |
| `demo_post_message` 拒绝(空白/超长) | UI 提示文本被拒(PostgREST 400 + `{code,message}`,`port_rest` 映射为中文提示) | 无变化(事务回滚) |
| 取消(on_stop) | 「正在结算本回合…」→ 回合气泡「已停止本回合。」 | 手握的非 judge claim 以 `demo_cancelled` failed 结算,无未决行 |
| 回合步数耗尽(tick cap) | 「回合步数达到上限,已停止。」 | 手握非 judge claim fail-settle |

助手气泡:本 turn 最后一条锚定 `llm/message` 的 text;`turn/end.delivered=false`
时改为 reason 的中文短句——`injection_veto` 拒绝、`budget_exhausted` 预算用尽、
`resolve_budget` 判断放弃、`judge_attempts` 判断尝试耗尽,其余 reason 原样展示。

## REST 面的 GUC 限制(实测,2026-09-23)

`pg_typesafe` 懒加载(`MarkGUCPrefixReserved("typesafe")`)决定了三条硬事实,
REST 面(port_rest/app)按此设计:

1. **`typesafe.provider` 只能设在尚未加载 typesafe 库的连接上。** PostgREST
   池化连接只要执行过一次 ask(真实或 mock 都会触发加载)就永久不能再
   parse(42602 invalid configuration parameter name "typesafe.provider")。
   `port_rest.parse` 检测到该错误后调 `demo_recycle_pool()`——终止本库全部
   authenticator(PostgREST 连接角色)后端、含执行它的那个(其 HTTP 响应中断
   是预期)——丢弃 keep-alive 连接,并在池新建的连接上**恰好重试一次**。
   代价:池被毒化后的每一次 parse 都先撞墙→回收→重试(实测一个普通回合的
   3 次 parse ≈ 3 次回收;毒化连接对 advance/claim/complete 等其余 RPC 仍完全
   可用)。属 demo 级已知妥协;pg 端口(port_pg)不受影响(每次 parse 一条
   新连接)。
2. **`typesafe.endpoint` 是 `PGC_SUSET`**:`demo_parse` 体内(definer
   `v13_resolve_login`,非超级用户)的 session 级设置在库懒加载替换
   placeholder 时不被采纳。真实模式的对端由 `setup_db.build()` 的
   `ALTER DATABASE ... SET typesafe.endpoint = 'http://127.0.0.1:8765'` 钉住
   (`[pin ]` 输出);`p_endpoint` 参数仍随 RPC 发送(与 pg 端口合同对称),
   但在本面上不具权威。
3. **`typesafe.api_key` 注册为 `PGC_USERSET`**(其 `GUC_SUPERUSER_ONLY` 旗标
   只是展示位),所以 `p_shim_key` 参数值在每个连接类上都真实到达 ask——
   shim 校验的就是 Chainlit 进程启动时生成的 per-process `Settings.shim_key`,
   不需要建库期固定值。

pg 端口与 REST 面的分工:`port_pg.resolve_batch` 以超级用户在同一事务先
preload 再设 endpoint/api_key;REST 面做不到(连不上超级用户),故 judge 慢路
在 REST 面上同样依赖建库期的 endpoint 钉值 + `p_shim_key` 参数(慢路的实际
HTTP 超时权威点本来就在冻结信封的 `envelope.timeout_ms`)。

## D12 / D15 安全注意

- **无 JWT、仅本机**:PostgREST 以 `authenticator` 连 socket trust,anon 角色
  `demo_anon` 能读视图里的对话。只绑 `127.0.0.1`,单操作者 threat model;
  不要把它改成 TCP 上的 postgres 超级用户,不要把任何端口暴露到非回环地址。
- **socket 目录权限(D15)**:PostgREST 与 Chainlit 必须和 pgembed 同一 OS
  用户才能进入 `.pgdata` socket 目录。连不上就停,不要改 `-h '*'`,不要为省事
  在 `pg_hba.conf` 里打开 TCP。
- shim 的 `Authorization` 校验的是进程本地 shim_key(不是 DeepSeek key);
  DeepSeek key 只出现在 shim 线程与生成函数的出站头,不进 PG、不进 REST、
  不进日志(RPC body 里最多有 shim_key)。

## 本地 gate(不联网)

```text
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u UV_ENV_FILE \
  UV_NO_ENV_FILE=1 uv run --project demo_v13 python demo_v13/test_demo_loop.py
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u UV_ENV_FILE \
  UV_NO_ENV_FILE=1 uv run --project demo_v13 python demo_v13/test_demo_shim.py
uv run --project demo_v13 python demo_v13/test_demo_smoke.py                 # exit 0
# B2 面(离线 fake;建 agent_v13_demo_b2_test,验 W3 工人契约四断言):
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u UV_ENV_FILE \
  UV_NO_ENV_FILE=1 uv run --project demo_v13 python demo_v13/test_demo_b2.py
# 有 key 时(opt-in,真实 DeepSeek;无 key → exit 2):
uv run --project demo_v13 python demo_v13/test_demo_smoke.py --real-provider-smoke
```

## B2 mgraph 装配接线库(agent_v13_demo_b2,16 文件)

B2 面把 mgraph 装配接线(manifest v4 + `memory_graph` 段 + memory belt)接进
Chainlit 栈。建库(PostgREST 必须先停,重建同样):

```text
uv run --project demo_v13 python demo_v13/setup_db_b2.py
```

- 16 文件 = `SQL_LOAD_ORDER` 全量(core→…→mgraph_assembly),经
  `load_stage(server, db, "mgraph_assembly")` 走注册表既有第 16 文件,
  `v13/load.py` 零改动。
- PostgREST 的 `PGRST_DB_URI` 指本库后照常起;Chainlit 照常跑
  (real 模式才有记忆效果;fake 模式可验契约形态)。
- 旧库不动:`agent_v13_demo`(envelope 基面)、`agent_v13_demo_mem`/
  `agent_v13_demo_mem2`(15 文件试验对照)。
- U1a:`memdrive_phase2` 候选探针改走 `v13_mgraph_anchor_tinql`(空锚记 0、不调用 candidates);`mem2_observe` 的 `n_terms` 按 ` OR ` 段数计。

### /memory 命令表(hub 空闲时;回合执行中拒绝)

| 命令 | 作用 | 库面 |
|---|---|---|
| `/memory on` / `/memory off` | 翻 `read_enabled`(INSERT 新策略版本 + 双 UPDATE 翻 active);翻版改 `mgraph_ver` → 下一回合自动 `context_refresh` 并注入记忆段 | `demo_mgraph_policy_bump` |
| `/memory write on` / `/memory write off` | 翻 `write_enabled`(建图前置) | 同上 |
| `/memory project` | transcript 投影(幂等;pg_cron 在 stage 库不可用,手动投影是真实运维形态) | `demo_rebuild_transcript_chunks` |
| `/memory build` | 投影 + build 循环至自然完成(每 tick 一次 RPC;REST 面先回收池保证新连接) | `demo_mgraph_build` |
| `/memory panel` | 记忆面板:策略版本/read·write、段状态(六态)、live vs 冻结对账、last_walk 统计、judge 累计、降级审计 | `demo_memory_panel` 视图 |

### A/B 协议(同会话翻版前后;判定「记忆是否真的改善回答」)

1. **播种**(read off,默认):发 4–6 条埋点消息(实体/因果/时间链/数字);
2. **建图**:`/memory write on` → `/memory project` → `/memory build`(观察
   tick 至自然完成)→ 可 `/memory write off` 收尾;
3. **基线**:问探针问题(如「为什么发布前没跑预发?」)→ 记下 A_off
   (面板段状态应为「记忆读取未开启」);
4. **翻版**:`/memory on`(下一回合自动 refresh + walk);
5. **实验**:同一问题再问 → A_on;面板段状态应为「已注入」,展开行看
   provenance(speaker=llm 的行是「模型复述」观测点)/score/walk 统计;
6. **判定**:A_on 引用了播种事实而 A_off 没有;负例查询(无关问题)段
   不出现或空集;`edges_used=0/depth=1` 是 CJK superset 路由的已知形态
   (trial/rerun 一致),不算回归。

### 陷阱速查(实测已落入端口/命令层,操作者仍须知)

- **GUC 墙**:已花费连接上 `typesafe.provider` 占位符被删且保留前缀不可
  重设——build 每 tick 必须新连接(REST 面=先回收池再调);run_round 相反
  (先 `typesafe_last_request()` 加载再设 mock/api_key,provider 靠
  capture_pm 回落 judgment_calls)。
- **blob 按 content_hash**:段内容寻址去重,跨会话同内容共享一行——UI 与
  断言一律按 manifest 段 `content_hash` 查 `artifacts`,不得按 effect 数。
- **generation 竞态**:walk 开始后任何 build 都会推进 generation 使旧 walk
  材料落空(段缺席)——build/翻版只许回合之间(busy 拒绝兜底)。
- **策略翻版零 DELETE**:`v13_policies` 禁 DELETE、值不可变,只能 INSERT 新
  版本行 + 双 UPDATE 翻 active(全部经 `demo_mgraph_policy_bump`)。
