# v13 envelope —— 判断请求信封与决策缓存（DP2）

Gate: `uv run python v13/envelope/test_envelope.py`（退出码 0 = 通过）

库名 `agent_v13_envelope`。加载 core + resolve + advance + twophase +
`v13_envelope.sql`（`files_through('envelope')` 五文件前缀）。

## 机制

判断请求 = 版本化模板 × 声明投影 × 同源构建器 × 全局 `judgment_cache` ×
逐调用 `judgment_calls`。`v13_needed_judgments` 五列（含 `template_name`），
信封 19 键。解析事务内 consult / 分组 ask / γ' read-back / no-progress 即失败。

## 运维纪律（DP1 六条）

1. 调用者 `v13_parse` + `v13_advance` 成对。
2. 驱动周期调 `v13_requeue_stale`。
3. 哈希只用信封冻结 provider/model；mock/timeout GUC 仅测试。
4. worker 出站携带 `idempotency_key`。
5. 双登录：判断面走 `v13_resolve_login`，建账面走 `v13_route_login`。
6. 调用 advance 前设 lock_timeout/statement_timeout；cap 翻新含全五键。

## 运维纪律（DP2 六条）

1. 模板 authoring = draft → 内容行 → freeze。任何模板变更使在途信封弃批，须重 parse。
2. canonical 缓存 first-wins。纠错路径 = 冻结新模板版本即换世代（错误答案不删行；γ' 拒绝经 `readback_rejects` 可观测；γ' 整批拒的付费批 `failed=true` → 封顶 abandon）。
3. shadow：`v13_shadow_reroute` 零 API；排除无 provenance 行；目标版本须声明 `template_compat`；exact replay 归 manifest（DP3）。
4. 窄 projection 启用 = §12 触发的纯数据动作（冻结新模板版本，零代码）。
5. 部署前置 = `SET typesafe.provider` / `typesafe.model`（fail-closed，未配置即 V3002）。
6. `judgment_calls` 是成本/usage 真相源，不得从 decisions 派生 usage。

## 台账

- **#45(b) 回退已激活**（承 DP1）：本仓 pg_typesafe HTTP 层不可被
  `statement_timeout` / `pg_cancel_backend` 中断。B10 声明超时形态走 V3001
  mock 承担 `failed=true`；未声明分类的 `pg_cancel_backend` 仍真取消。
  升回条件见 `v13/resolve/README.md`。
- **needed 从模板 jsonb 取 `criteria`**：`jsonb_build_object` 把 SQL NULL
  写成 json `null`。实现用 `NULLIF(..., 'null'::jsonb)` 还原 SQL NULL，
  否则 noul 族会把显式 `"criteria":null` 送进 wire（typesafe 拒收）。语义
  与计划「NULL 省键」一致，不是行为分叉。
- **timeout 冻结用 `SET LOCAL`**：计划写 `set_config(..., true)`。DP1
  G-ctx1-5(b) 对 `v13/**/*.sql` 扫 `set_config` 子串（`test_twophase.py`），
  禁改 dp1 测试。`SET LOCAL` 与 `set_config(..., true)` 同为事务局部，
  语义等价。
- **`tools.kind` 限定**：needed 查询 `tools.kind IN ('sql','tool')`，因
  `RETURNS TABLE(..., kind text, ...)` 使裸 `kind` 指 OUT 参数。无此限定会
  `42702`。查询集合与 DP1 resolve 旧体一致，零行为分叉。
- **`timeout_ms` 空串 `NULLIF`**：信封与 calls 落行把 GUC 空串规范成 SQL
  NULL。空串 `::int` 会 `22P02`；NULL = 未声明，与 A9 / 可空列一致。
- **β/γ' 用 `q->'criteria'`**：第三参是 jsonb；`->>` 产 text 再往返。与 C4
  「实参回读自 payload」同向。
- **`judgment_calls` GRANT 仅 INSERT**：`v13_resolve_judgments` 的
  `INSERT … RETURNING call_id` 需要列 SELECT。E1 有缺口路径在 gate 内
  `GRANT SELECT ON judgment_calls TO v13_resolve` 后走函数落行。SQL 文件
  未改（本轮只收测试保真）；后续可把 catalog 授权改成与 cache 同形的
  `SELECT, INSERT`。
