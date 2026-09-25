# v13 stannum 0.4 M3–M6 结案（2026-09-25）

状态：本循环零代码结案。Oracle 2026-09-25 裁决为 Q1=A、Q2=A、Q3=A、Q4=A。完成的那一条 lane 即裁决；另两 lane 为 provider_error，本文件不复裁。本结案只绑定本循环，不编辑任何冻结文件。

## 权威顺序

`docs/plans/v13-dp9-mgraph-v2-plan-2026-09-24.md` 终稿 v1.0 高于 `docs/investigations/v13-stannum-0.4-pgembed-adaptation-2026-09-25.md` §5 的 M3 排期。`docs/investigations/v13-jieba-canary-probe-2026-09-25.md` §9 高于「v2 已交付所以 M4 可以切换」这一读法。本文件不修改这两份冻结文档，也不修改 `docs/designs/v13-rag-subagent.md`。

## 动笔前核对

下列四句仍在原文中，且未被推翻：

- v2 计划终稿 v1.0 裁决 OQ13=D；其 §8 写明，三条夹具式触发条件全部满足，新计划才可重开 CJK 路由。
- OQ15 已交付为字符 3-gram，策略键为 `anchor_ngram_n=3`。
- jieba 探针 §9 的裁决是不切生产索引；将来若再议，只接受整包，不接受先改 reloption。
- `docs/designs/v13-rag-subagent.md` 仍把 T1 记为台账触发线，不是已开工。

§8 三条触发没有「已满足」记录。本循环没有发现把三条记成已满足的新证据。即便将来出现那种证据，本裁决也不自动升为 Q1=B 或 Q2=B。

## M3（Q1=A）

适配调查 §5 的「M3 = OQ13 建议裁 B」已经过时。有效裁决是 OQ13=D。不要改 `v13_mgraph_route`。不要新增 `routing_intent_causal` / `routing_intent_temporal`。E2 保持原样。§8 三条触发没有被记成已满足。

本文件不是重开文书。不要把本文件读成已经取代 DP9-OQ3。未来若另立重开计划，须由那份计划自己写出「supersedes DP9-OQ3」这一短语，并且必须先解决 P1-8：只读 script 分类器；不要编辑冻结的 `v13_query_segments`。

## M4（Q2=A）

旧阻塞「OQ13/OQ14 未裁或 mgraph v2 未交付」已经满足，而且裁决是 D；那不再是阻塞。M4 仍阻塞：整包先决 + 须正式 supersede OQ15。本文件不执行该 supersede。

不切生产索引。chunks / transcript_chunks / memory_nodes / decisions 的生产索引保持 unicode。`decisions.question` 永不切换。`v13_mgraph_anchor_terms` 保持 CJK 字符 3-gram。

将来的整包不是本循环。那一包要同时交付：词级锚、L3 重写且不用 OR 放宽、一条新的 highlight 绑定断言，以及同一次提交里重写的 G6。

## M5（Q3=A）

触发未到。没有第二自由文本列。不要发明列。不要启用 BM25F。不要设置 field_weights。能力说明已经写在适配调查 §2.4；本循环不另做探针。

## M6（Q4=A）

T1 未开工。不要配置 vchord preload。不要导入 pgembed_stannum。本注不抄 RRF 模板。

适配调查 §2.5 已经说明：那份模板的 BM25 臂是无过滤的 `search()`，不等价于 v13 的谓词过滤 top-k，所以不是成品。

## 本循环不做

不跑 16 个 gate。不连库。不重建 bundle。不改 `v13/**`。不改 route、E2、anchor_terms、生产索引、schema、BM25F、RRF、vchord 或嵌入。冻结检查只到 L3 原文核对。
