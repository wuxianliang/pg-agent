# v13 chunks —— 投影与跨度装配（DP4）

Gate: `uv run python v13/chunks/test_chunks.py`（退出码 0 = 通过）

库名 `agent_v13_chunks`。加载 core + resolve + advance + twophase +
envelope + manifest + `v13_chunks.sql`（`files_through('chunks')` 七文件前缀）。

## 机制

chunks 是可重建投影（行自证 / 重摄取同事务 / 外部只记 content_hash）。
源台账 `v13_sources`；语料代数 `v13_chunks_meta.generation` 进 token 第八键
`corpus`。rebuild = 保护式重灌（被引用源 locked）。跨度生产者
`v13_extract_spans` / `v13_assemble_spans` 输出 `{doc,offsets}`。

## 运维纪律

1. **驱动器契约四步与 ops session 复用**：① 库外读文件（外部 IO 不进事务）；
   ② ops session + `v13_enqueue_effect(sid,'tool',request,p_tool='v13_ingest_corpus')`
   （request 携计划与字节数，不携正文）；③ claim → complete('succeeded')；
   ④ **同事务** `v13_ingest_document(effect_id, corpus, body[, supersedes])`。
   ops session 可复用，勿每文档新建连接。
2. **chunker 翻版 = 新策略行 + rebuild**：`chunks_ingest` 追加新版本行并翻
   active，然后 `v13_rebuild_chunks()`。被引用源锁定（不随升版）；逃生缝 =
   同逻辑源新内容新 `source_hash` 重摄取。supersede 后旧源台账退役
   （`superseded_by` 标记；rebuild / GC(delete) / 召回面均跳过——DP5 契约⑨）。
3. **保留规则与 GC 策略门 + 代数单调性守卫**：被引用行不可删（触发器 belt）。
   `chunk_gc` 默认 `dry-run-only`。手工改 `v13_chunks_meta.generation` 调低或
   DELETE meta 行被拒。
4. **pg_cron 前置 / 降级**：需 `shared_preload_libraries` 含 `pg_cron`。不可用则
   NOTICE 降级，`v13_verify_chunks()` 仍手动可调。crontab 等价：
   `17 3 * * * psql "$URI" -c "SELECT v13_verify_chunks(true)"`。
5. **T0 english 边界**：`body_tsv` = `to_tsvector('english')`。CJK 零召回是
   既裁边界，CJK 走 DP5 stannum。
6. **p99 度量协议**：基线 vs 载入各 2000 次 `v13_append_event`，三轮取中位；
   断言 `p99_loaded ≤ max(p99_base×1.25, p99_base+0.5ms)`。
7. **verify 手动命令**：`SELECT v13_verify_chunks(true)`。canary 用非停用词
   `quasar`（`the` 会被 english 配置剥空）。GIN 可用性用会话
   `enable_seqscan=off` 强制（小表 Seq Scan 是成本模型正确行为，不能证明
   病变）；EXPLAIN 异常路径恢复该 GUC。
8. **大产物 ref 路径与窗口化 GC**：v1 超 `max_doc_bytes` 拒；ref 路径与窗口化
   GC 入台账，触发 = 超限语料真实出现 / 扫描恢复成本实测超标。
9. **锁协议**：rebuild/GC(delete) 与同源 ingest 排队是预期（持有期=事务尾）。
   引用端触发器自动取锁。批量候选落行 = 单引用集并集升序预锁或拆单引用集事务
   （不变量 9 / DP5 ⑧ / DP6 ①）。
10. **装配四配置与策略五键**：`span_assembly` 行
    `mode/context_bytes/merge_gap_bytes/boundary/fence_aware/table_aware`。
    `mode='whole_chunk'` 整 chunk 开关；空 body 跳过（不产 `[1,0]`）。
    file 面摄取另有注册门前置（A9b：`scan_status='clean'` ∧ `content_hash`
    非空才可投影）；本 stage 文档入口 `v13_ingest_document` 不改。

## 回退

删 `v13/chunks/` + `v13/load.py` 两处注册（`SQL_LOAD_ORDER` 末项与
`STAGE_THROUGH['chunks']`）+ DROP 库 `agent_v13_chunks`。DP1–DP3 文件零改动。

## 台账

- **① jsonb 序列化哈希**：`v13_body_hash` = sha256(to_jsonb(body)::text)，与
  artifacts CHECK 同源。升级 PG 大版本若序列化变，重摄取或保留 referenced 行。
- **② 保护式重灌**：字面 truncate 被触发器拒。被引用源不升级。
- **③ superseded_by 不进任何哈希 / token**：lineage 是台账元数据；corpus 键 =
  generation。
- **④ file 面 A9a/A9b/A9c**：立法不落本 DP SQL。文档语料纪律②保留；file 面
  改收据+指针归后续。
- **⑤ validator 八键同步（实现必要缝）**：DP3 `v13_manifest_validate` 把
  `required_revision` 钉死七键。token 扩 `corpus` 后 settle 必 V3003。本文件
  `CREATE OR REPLACE` 同签名换体，仅键集改为
  `asm_ver,corpus,dec,gen_ver,goal,jdef_ver,sem,tools_rev` 并校验 corpus≥0。
  DP3 源文件零改动。无此缝则 G2 真实 refresh 链路不可达。
- **⑥ plpgsql 锁别名 / get_byte 转型**：ingest 锁查询 `unnest … AS s` 与
  变量 `s jsonb` 撞名（42702）；`get_byte(bytea,bigint)` 无候选，改为
  `(v_s-1)::int`。语义与草案一致。
- **⑦ verify GUC 用 SET 不用 set_config**：同会话 `enable_seqscan` 强制+恢复；
  避开 M4 `V13.rglob("*.sql")` 对 `set_config` 子串扫描（G-ctx1-5(b)）。
- **⑧ DP3 G6 下标**：`SQL_LOAD_ORDER[-1]` 改 `[5]`。末尾追加是 DP4 合同；
  原断言把前缀位写成树终态。SQL 零改。
