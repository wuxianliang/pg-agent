# v13 characterize —— text-search 刻画与 T0 definition 换体（DP5 stage 9）

Gate: `uv run python v13/characterize/test_characterize.py`（退出码 0 = 通过）

库名 `agent_v13_characterize`。加载前缀九文件。setup **硬前置探针**
`pg_available_extensions` 无名即 exit 非 0（fail-closed，无降级）。

## runbook 六件

1. **索引可丢基础行不可丢**：`DROP INDEX ix_chunks_stannum` 不丢 chunks/artifacts
   行。正确性检测 = EXPLAIN 形状 + verify v2 第八项。默认配置下索引丢失是
   **性能事件非正确性事件**（回退 comparator = 最宽配置）。
2. **连接池预热**：新连接有 buffer 重建税。生产连接池应在 attach 后跑一次
   热查询（`SELECT v13_recall('"quasar"', 8)`）再接流量。
3. **fold 毛刺**：M1 数字见 gate 打印。宽松守门 `p99_fold ≤ max(p99_base×10, 200ms)`。
4. **升级**：扩展版本变更 → 重跑 K3（无索引回落）与 K5（三禁路径一致性）。
   0.1.0 实测三禁路径与 EXECUTE 等价，**实测等价 ≠ 禁令撤销**。
5. **REINDEX 演练**：`REINDEX INDEX ix_chunks_stannum; REINDEX INDEX ix_v13_canary;`
   然后复跑 K2/N1。基础行不动。
6. **AGPL 分发审查**：分发本扩展或链接产物前走 AGPL 合规审查；触发 =
   对外分发二进制/镜像含该扩展。

## tokenizer canary

专用表 `v13_canary_docs` + `WITH (long_tokens='split', max_token_bytes=64)`。
64B 精确块：bound 命中 / 默认回退漏召。**绝不与生产索引同列共存**。

## 同列双索引禁令

chunks 表恰一个 text-search 索引（生产默认配置）。两索引并存时 planner
恰绑其一（绑错即错结果）。bigram 未来走**独立列**。

## verify v2

第八项 `stannum_verify_index`：`verify_index('ix_chunks_stannum', true)` 的
error/warning 计数。cron job 零新增（DP4 `v13-verify-chunks` 调本函数自动升 v2）。
verify 体用 `SET enable_seqscan` 不用 `set_config`（避开 G-ctx1-5(b) 全树扫描）。

## >1024 展开

编译器 64 段上限挡用户面；引擎面 1030 词项 AND 直测保守回查（0.1.0 成功返回）。

## 尺寸刻画面

6 档 × 20 文档（查询词埋中段，本机 Q1）：

| size | hits | bm25_mean | avg_rank |
|---|---|---|---|
| 512B | 20 | 0.3787 | 10.5 |
| 1K | 20 | 0.8360 | 10.5 |
| 2K | 20 | 1.0162 | 10.5 |
| 4K | 20 | 1.0638 | 10.5 |
| 8K | 20 | 1.0498 | 10.5 |
| 16K | 20 | 1.0129 | 10.5 |

2K 起均值进入平台。3072 先验落在平台上，本轮不翻 `chunks_ingest.target_bytes`。
数据支持 ≠ 3072 时：新版本行 + `v13_rebuild_chunks()`，**不自动翻策略**。

## 台账

- **① extract 参数名**：OR REPLACE 不能改输入参数名（PG：`p_terms`）。v2 体仍用
  `p_terms jsonb`，载荷约定改为 `{"tinql":…}`。签名 `(text,jsonb)` 不变。
- **② verify SET 非 set_config**：逐字复制 DP4 v1 的 `SET enable_seqscan` 路径，
  避开 G-ctx1-5(b) 对 `set_config` 的全树扫描。
- **③ full_score 值域**：英文 quasar fixture ∈[0,1]；CJK 短语实测可 >1
  （本机 3.37）。P2 钉英文值域；CJK 超 1 记为 0.1.0 观测，不宽化 P2。

## 0.1.0 实测记录

- Custom Scan / `Stannum Text Search Scan`（K1 钉死，升级若改节点形态随 README 重钉，不做 OR 宽化）
- 降级面：无索引回落默认 comparator；同列双索引错绑
- K5 三禁路径 0.1.0 命中保持绑定（升级复测项）
- Katakana 连跑成单 token；查询侧 CJK 语段一律短语引用

## 回退

删 `v13/characterize/` + `v13/load.py` 第 9 位。第 8 位 T0 tsvector 仍可全绿。
