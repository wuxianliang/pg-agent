# v13 manifest —— 装配清单骨架与三 epoch/freeze（DP3）

Gate: `uv run python v13/manifest/test_manifest.py`（退出码 0 = 通过）

库名 `agent_v13_manifest`。加载 core + resolve + advance + twophase +
envelope + `v13_manifest.sql`（`files_through('manifest')` 六文件前缀）。

## 机制

context artifact 内嵌装配清单（manifest=IR）。freshness 缝
`v13_context_fresh` 比较 required/active 七键 token（含 gen_ver）。
freeze 点 = `v13_refresh_context` settle。exact replay 读旧 artifact
原字节；recompute 只读不落库。三 epoch 是模板属性，INSERT 期固化。

## 运维纪律

1. refresh worker：`v13_claim` 领 `context_refresh` →
   `v13_refresh_context(effect, attempt, fence)`。返回 `accepted` 即毕。
   装配异常不得吞——捕获后 `v13_complete(..., 'failed', {code})`。
   claim 后到 settle 前崩溃 = lease 过期 → unknown 墙。
2. 策略版本化：`assemble_manifest` / `generation` / `judgment_defaults`
   三族追加 = 新版本行 + 同事务翻 active。改 est 公式必新版本。新版本
   行必带合法数值键 + overrides 值在词表内 + judgment_defaults 过校验器。
   形状错在 settle 守卫 V3003。
3. exact replay 用清单里的旧 verdict，不拿新阈值重释 raw answer
   （那是 shadow reroute）。
4. `goal_hash` 单一来源 `v13_goal_hash`，禁内联重算。
5. generation / judgment_defaults 是版本化数据，改动 = 新版本行。
   settle 面零 GUC 依赖（生成身份读 generation 策略行）。
6. 回退：删 `v13/manifest/` + `v13/load.py` 两处注册（`SQL_LOAD_ORDER`
   末项与 `STAGE_THROUGH['manifest']`）+ DROP 库 `agent_v13_manifest`。
   DP1/DP2 文件零改动。

## 台账

- **① validator 去掉草案 `DECLARE k`**：k 仅聚合别名，DECLARE 后与
  `jsonb_object_keys(…) k` 撞 42702。删未用变量，零语义分叉。
- **② 墓碑二 envelope 从 live 复制**：plan §3.6 明文从
  `v13_envelope.sql` 原文复制、仅换 `goal_hash`。`NULLIF(timeout_ms)` 原样保留。
- **③ 第二次 refresh 用 nonce enqueue**：`parse_settle` 仅当
  `hang_refresh` 找不到 ready `context_refresh` 才 `enqueue … nonce`。
  零变化再 settle 的合法构造，不改 SQL 窄入口。
- **④ DEFINER settle 后 recycle 连接**：测试卫生（提交+重建连接），零语义。
- **⑤ G1 kind 守卫先拒**：ptr 守卫 BEFORE INSERT OR UPDATE：随机 uuid 的
  `SELECT kind` 得 NULL → kind 不符先于 FK。blob→kind、随机 uuid 均
  fail-closed。
- **⑥ v2 file 面立法不落本 DP SQL**：A6–A13 / L4 只登记 file section 与
  manifest 根字段族；骨架 validator 词表与 B2 三 kind 不扩。上线 file
  时只加不减。
