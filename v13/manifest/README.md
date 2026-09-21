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
6. 回退：删 `v13/manifest/` + `v13/load.py` 一行 + DROP 库
   `agent_v13_manifest`。DP1/DP2 文件零改动。

## 台账

- **v2 file 面立法不落本 DP SQL**：A6–A13 / L4 只登记 file section 与
  manifest 根字段族；骨架 validator 词表与 B2 三 kind 不扩。上线 file
  时只加不减。
