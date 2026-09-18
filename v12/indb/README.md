# v12 G7 · indb —— 判断平面入库（pg_typesafe）

Gate: `uv run python v12/indb/test_indb.py`（退出码 0 = 通过，全程
`typesafe.mock_response` 离线确定性）

## 前置

pg_typesafe 是本地 pgembed 打包的 C 扩展（commit `bb491da`）：
`typesafe_ask(state jsonb, questions jsonb) -> jsonb` 以原生 systemone
格式发请求、返回原生响应；GUC：`typesafe.endpoint` / `api_key` / `model`
/ `timeout_ms` / `mock_response` / `batch_size` / `http_concurrency`，
429/529 内建重试。另有 `classify/detect/score/_many/_label` 便捷函数。

## 三个 SQL 函数

- `v12_ask_in_db(batch)`：ready 批次 → `typesafe_ask` →
  `v12_record_answers`，同事务，含 SQL 侧延迟测量。
- `v12_decide_in_db(session)`：**一条 SQL 调用完成整个 decide**——
  fold → 开批 → 建题 → seal（哈希缓存生效）→ 入库问 Jev → 确定性路由；
  返回 route，`turn/route` 事件落库即返回。
- `v12_guardrail_in_db(session, state)`：三问护栏全入库。

## 不变量的自觉演化（v8 不变量 4 → v12）

**副作用 IO（工具、LLM 生成）仍留库外 worker（G3/G6 不变）；
纯判断 IO（Jev：无副作用、幂等、廉价）经 pg_typesafe 允许进事务。**
代价是调用期间持有锁（实测 9 问批 1.3–1.6s），已作为权衡记录。
v1 库内 HTTP 之死在于把慢而贵的**生成**调用塞进库——这里进库的是
100ms 量级、可缓存重放的判断。

## OpenRouter 配置（实测打通）

```sql
SET typesafe.endpoint = 'https://openrouter.ai/api/alpha/decisions';
SET typesafe.api_key  = '<OPENROUTER_API_KEY>';
SET typesafe.model    = 'typesafe/jev-1.13';
```

手动实测：`uv run python v12/indb/probe_indb.py`（一次 decide 约
$0.00004）。两次实跑：一次 route=sql 交付；一次 intent 置信 0.73
（act 带 0.75 差 0.02）→ 转人工——review 带按设计工作。

## gate 里的发现

护栏失败用例最初用了与通过用例完全相同的 state——seal 直接命中
request_hash 缓存复用了通过答案，mock 根本没被咨询。缓存语义正确，
测试改为换不同 draft 才真正发起第二次询问。
