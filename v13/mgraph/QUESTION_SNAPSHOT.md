# v13/mgraph QUESTION_SNAPSHOT.md — Jev-Mem 题面快照(题面权威)

> 本文件是 v13 mgraph 六族 `mem_*` 判断模板题面的**唯一权威**(DP9 计划 §1.2-9/§3.3/附录 B)。
> 上游仓库: https://github.com/libingzheren/Jev-Mem
> 上游 commit: `81574eb23f3fd8d1a6c4d54a1e7d6f2dd539e9bb`(main@2026-09-22)
> 抄录日期: 2026-09-23;抄录源=本地 `/tmp/Jev-Mem-main`(与 codeload 该 commit 的 tarball 逐字节同——`diff` 验证)。
> `/tmp` 副本失效时:从上述 commit 重取(codeload tarball 或 GitHub 源码页),摘不到对应槽则 M1 闸门保持红。
> 许可:上游 MIT License — Copyright (c) 2024 Anonymous Authors(全文见文末附录)。

## 组合规则 combination-rule v1(版本化;改动即新版本)

v13 `judgment_templates.question` 须为单行 ASCII(`^[\x20-\x7E]+$`),而 v13 的 noul 形状 `criteria=NULL`;
上游 Jev-Mem 的 noul 携带 instructions + criteria{true,false} 两段文本。组合规则:

- **noul 槽**:`question = instructions || ' TRUE if: ' || criteria_true || ' FALSE if: ' || criteria_false`
  (四个拼接段之间以单空格分隔;`TRUE if:`/`FALSE if:` 为标记词;组合后字节进 request_hash 缓存键)。
- **choice 槽**(`mem_cons_representation`):criteria 保留为 JSON 闭集对象(键序 keep_separate, merge,
  promote, uncertain;值逐字);`question = instructions`(原样,不再拼接)。
- **v13 本地槽**(`mem_cons_fidelity`,无上游原文):`question` 即所记原文,不参与拼接。
- **实例化下标钉死**:上游 `relation_questions(index)`/`traversal_questions(index)`/`consolidation_questions(index)`
  按 `candidates[{index}]` 生成题面;本快照与 SQL 种子一律取 **index=0**(逐 pair 身份由 signal 与
  state 承载,不进题面——同模板题面跨 pair 恒定,缓存键差异来自 signal+state)。

## 槽位清单(27 上游槽 + 1 本地槽 = 28 模板)

| 族 | 模板 | 源 |
|---|---|---|
| type | `mem_type_episodic` | memory/jev_questions.py:47-50 |
| type | `mem_type_semantic` | memory/jev_questions.py:51-54 |
| type | `mem_type_procedural` | memory/jev_questions.py:55-58 |
| type | `mem_type_preference` | memory/jev_questions.py:59-62 |
| rel | `mem_rel_semantic` | memory/jev_questions.py:69-71 |
| rel | `mem_rel_causes` | memory/jev_questions.py:72-74 |
| rel | `mem_rel_caused_by` | memory/jev_questions.py:75-77 |
| rel | `mem_rel_entity` | memory/jev_questions.py:80-82 |
| cons | `mem_cons_redundant` | memory/jev_questions.py:89-91 |
| cons | `mem_cons_contradiction` | memory/jev_questions.py:92-94 |
| cons | `mem_cons_obsolete` | memory/jev_questions.py:95-97 |
| cons | `mem_cons_link` | memory/jev_questions.py:98-100 |
| cons | `mem_cons_representation` | memory/jev_questions.py:101-108 |
| routing | `mem_routing_semantic` | memory/jev_questions.py:114-115 |
| routing | `mem_routing_temporal` | memory/jev_questions.py:116-117 |
| routing | `mem_routing_causal` | memory/jev_questions.py:118-119 |
| routing | `mem_routing_entity` | memory/jev_questions.py:120-121 |
| routing | `mem_routing_multi_hop_need` | memory/jev_questions.py:122-123 |
| routing | `mem_routing_recency_importance` | memory/jev_questions.py:124-125 |
| stop | `mem_stop_sufficient` | memory/jev_questions.py:131-133 |
| stop | `mem_stop_continue` | memory/jev_questions.py:134-136 |
| stop | `mem_stop_missing` | memory/jev_questions.py:137-139 |
| stop | `mem_stop_contradiction` | memory/jev_questions.py:140-142 |
| trav | `mem_trav_relevance` | memory/jev_questions.py:149-150 |
| trav | `mem_trav_relation_usefulness` | memory/jev_questions.py:151-152 |
| trav | `mem_trav_new_information` | memory/jev_questions.py:153-154 |
| trav | `mem_trav_supports` | memory/jev_questions.py:155-156 |
| cons | `mem_cons_fidelity` | v13-local (本仓拟定,无上游槽) |

停用词表(common_words,`memory/memory_builder.py:304-307`,同快照;策略 `entity_stopwords` v1 允许先 `[]`——OQ10「多抽不假抽」):

```text
The This That These Those What When Where Who Why How Image Thanks Wow Yes No Maybe Please Sorry Hello Hi Good Great Nice Sure Okay Well Now
```
(sha256(word-list-space-joined) = `da1e6bc3e15254227bd0e7baabe12093f56480cc55295eefdbd813994fbfe37f`)

种子数值来源参照(`memory/jev_mem_config.py:12-47`,DP9 §3.2 逐键;`consolidation_interval` 代码默认 0——论文附录「每 20 写」不采用,只记注):

```text
write_enabled=False read_enabled=False admission_enabled=False (12-14)
relation_threshold=0.60 candidate_top_k=10 total_graph_budget=20 probability_exponent=1.5 (25-29)
graph_activation_threshold=0.15 beam_width=5 maximum_depth=5 maximum_nodes=30 (31-37)
maximum_edges=200 maximum_jev_calls=10 max_latency_seconds=15.0 (38-40)
transition_weights=(0.25,0.35,0.15,0.15,0.10) (41)
evidence_sufficient_threshold=0.85 continue_threshold=0.40 (43-44)
consolidation_interval=0 consolidation_threshold=0.85 (45-46)
```

---

## 逐槽逐字记录

### slot mem_type_episodic

- source: memory/jev_questions.py:47-50
- kind: noul  ·  projection: ["body"]
- sha256(instructions) = `f0bb148fcc816714a13325d3747ddbac3dec8f6bc307911d23056f5e33f816c7`
- sha256(criteria_true) = `a4b1623ab9e81916485c054dc8d606a4dc21105993678a4f8d403b8041c23599`
- sha256(criteria_false) = `d63f5c1ea83cb4c51b5664a5ad838b6d9d531369013798e28df0542670876b60`
- sha256(question-combined) = `ac5439b8a6435307464dcee4221cc1ef39ae5fc3538e88798b6b38d9cce19ef7`

```text
Does `observation` describe a particular experience or event involving a participant?
```
```text
A specific past, current or planned event, even if its exact time is unstated.
```
```text
Only a general fact, procedure or preference with no particular event.
```

### slot mem_type_semantic

- source: memory/jev_questions.py:51-54
- kind: noul  ·  projection: ["body"]
- sha256(instructions) = `9151a1888d1e9b4d5b6972d5aa35a91a908aa1ed5e9cb54eb0e92b7777eab371`
- sha256(criteria_true) = `b76fdffd1d32712360db29736c00ed4ecf22ea07933cfefc345823c1fad0bf70`
- sha256(criteria_false) = `0ca7be67319a32b7ede31d907382dc6eb3bc30c25f01a183871554e187426cb4`
- sha256(question-combined) = `dc5806823848720eec3f39f8ba1fd03daf0a1f297cc7b6e0909327df64675cdb`

```text
Does `observation` state a fact about a person, entity or the world that remains useful beyond this conversational turn?
```
```text
An attributable fact or relationship, even when it also appears in an episodic account.
```
```text
Only a transient conversational acknowledgement or a question with no asserted fact.
```

### slot mem_type_procedural

- source: memory/jev_questions.py:55-58
- kind: noul  ·  projection: ["body"]
- sha256(instructions) = `29ebd30ede2ae997bb24f880c010dee362b8bb9d90e9dfc3e96c94e67b91bdbf`
- sha256(criteria_true) = `3825021a219f530f4a0e19f1179f8d55f6d78f928d22e621c05258c56c2c4ed3`
- sha256(criteria_false) = `da2a09eec9adc8adede4cdbd81844f8210657c4b4e11066d61559449bbe8132c`
- sha256(question-combined) = `17e7023936bc8a7a68aa09e30ed8f98c66d5a48d516e8aa9606bbc3c1367f1d6`

```text
Does `observation` describe how to carry out a task?
```
```text
An instruction, ordered step, method or actionable rule for performing a task.
```
```text
Merely mentions doing a task without describing how.
```

### slot mem_type_preference

- source: memory/jev_questions.py:59-62
- kind: noul  ·  projection: ["body"]
- sha256(instructions) = `e88533eb758a5f439a74bedb9b6c7934d03d7df2741679c28095a47f29ea7262`
- sha256(criteria_true) = `b1e7944d12425ce9de8bc3b937e3330c2c665c447837934262bf41d5d977265b`
- sha256(criteria_false) = `b2b6352aacb62a55f8bd2ccf554c5f1c067a3c4a2aca73a1770eb550a1a93f11`
- sha256(question-combined) = `3a0cba3b8a7be315734a82dbbd4020ebd109540e4b518c3acb4201976e5954a1`

```text
Does `observation` express a participant's preference, aversion or habitual choice?
```
```text
An attributable like, dislike, preferred option or habitual choice.
```
```text
An isolated action alone, another person's unattributed preference, or no preference evidence.
```

### slot mem_rel_semantic

- source: memory/jev_questions.py:69-71
- kind: noul  ·  projection: ["left","right"]
- sha256(instructions) = `173328f31fa4903b4a18abb974b02980ae294b52f46f81dcafe91a85ccad5c97`
- sha256(criteria_true) = `2e70dc68bdbcd5aa21849c217ad954cfdc877e735467be9e169546c2efb51374`
- sha256(criteria_false) = `3da9610615f487ffb596adbfcac0ff9b00b556ae1e5b5366bf63d80288a957e2`
- sha256(question-combined) = `4e0b903bb324b41b88b04474be02c8d3c42f3cc25006541e50fb1bea13479938`

```text
Compare `new_memory.content` with `candidates[0].content`. Would a semantic link between these observations help retrieve a shared specific topic or fact?
```
```text
A specific shared topic, fact or event makes the connection useful.
```
```text
Only generic conversational vocabulary or no meaningful semantic connection.
```

### slot mem_rel_causes

- source: memory/jev_questions.py:72-74
- kind: noul  ·  projection: ["left","right"]
- sha256(instructions) = `e9bdd74efc818a1fbfc9464ff4ecd25a1f70bba66fa6a7c24e1708802d3a7eba`
- sha256(criteria_true) = `1a8b796e48065e0daf83e6056a5fedab9bcae84f16f28c80caac1a3b01d7a0be`
- sha256(criteria_false) = `7b0d7a77480a67c83508ffee5a5087259050f3ca69c0ade597febe4d8f143b9a`
- sha256(question-combined) = `8f17c35590c553af442236725b72771bcf5a6eea1bb3d1abfbb0dd917196ffdc`

```text
Compare `new_memory.content` with `candidates[0].content`. Does the event in `new_memory.content` cause, enable or explain the candidate event?
```
```text
The supplied accounts support this direction of causal influence.
```
```text
Only similarity, chronology, a shared entity, or insufficient causal evidence.
```

### slot mem_rel_caused_by

- source: memory/jev_questions.py:75-77
- kind: noul  ·  projection: ["left","right"]
- sha256(instructions) = `c3140939f76b559c824e6f49218b83aa9c6bdb00ef2f1940ba538e6794225057`
- sha256(criteria_true) = `1a8b796e48065e0daf83e6056a5fedab9bcae84f16f28c80caac1a3b01d7a0be`
- sha256(criteria_false) = `7b0d7a77480a67c83508ffee5a5087259050f3ca69c0ade597febe4d8f143b9a`
- sha256(question-combined) = `20bf369b9200538667706bb09e3349d6b35c11fab661a6e8b7306ab1daf96ead`

```text
Compare `new_memory.content` with `candidates[0].content`. Does the candidate event cause, enable or explain the event in `new_memory.content`?
```
```text
The supplied accounts support this direction of causal influence.
```
```text
Only similarity, chronology, a shared entity, or insufficient causal evidence.
```

### slot mem_rel_entity

- source: memory/jev_questions.py:80-82
- kind: noul  ·  projection: ["left","right"]
- sha256(instructions) = `51fa36a8abe0c58e8c9395a9b695a145d224a55f9006aa1e1806ba49ed2913fd`
- sha256(criteria_true) = `61461b030de318534cfeb5b87b02d623b6b8a6401a17f1c5113209473f3210ad`
- sha256(criteria_false) = `50c89abc0389d0ed82550e49e54a0b1c9a6210c59f9b8b6ab9e2c0cb898f933f`
- sha256(question-combined) = `2f42a27ff4522eaac2cdd8a727695f80998837e683d41904144933a0fb2931a1`

```text
Compare `new_memory.content` with `candidates[0].content`. Using `new_memory.entities` and `candidates[0].entities`, do any names or aliases refer to the same real-world entity?
```
```text
Context supports a shared identity despite differing names or aliases.
```
```text
Distinct entities or insufficient evidence to resolve the alias; similar names alone are insufficient.
```

### slot mem_cons_redundant

- source: memory/jev_questions.py:89-91
- kind: noul  ·  projection: ["left","right"]
- sha256(instructions) = `1d470ac4dec1b1e6362e9be5c3e104fc0ef590318e1f2bd949eaf7b3604e9f43`
- sha256(criteria_true) = `1533936724922bd2746a888e105d0b55425460ca77cc0459ad9044cb1955ca07`
- sha256(criteria_false) = `af084869c5b65e7d29e3afdb82736accb020e85766003d29c38db43039c26f17`
- sha256(question-combined) = `45c92af4d2b8e65c1214e0c2d317942662be865ed4868b6f9ca91bab25b54208`

```text
Compare `new_memory.content` with `candidates[0].content`. Do these observations repeat the same fact with no additional recallable detail?
```
```text
One is a duplicate or paraphrase without a new detail or time-specific update.
```
```text
They provide different details or describe distinct occurrences.
```

### slot mem_cons_contradiction

- source: memory/jev_questions.py:92-94
- kind: noul  ·  projection: ["left","right"]
- sha256(instructions) = `cafc83da953f8e1a4e890af099152747d904c4f2e662e6531276195981949071`
- sha256(criteria_true) = `968ce436f155cd07a30605de71e26f032a65e04d0454b663fbff67060d7c7714`
- sha256(criteria_false) = `55193fdcedf30d21288112b3500356a5ce8437783f233879e84d8dbc21886f07`
- sha256(question-combined) = `e6e8cc7fb8877a5f03c04ba02096617f807d99c608d68c52d0241ce4b72c4453`

```text
Compare `new_memory.content` with `candidates[0].content`. Do these accounts assert incompatible facts about the same subject at the same time?
```
```text
Claims cannot both hold at the stated time and context.
```
```text
Compatible claims, uncertainty, or a change over time that explains the difference.
```

### slot mem_cons_obsolete

- source: memory/jev_questions.py:95-97
- kind: noul  ·  projection: ["left","right"]
- sha256(instructions) = `a713ba71fe009f1a714781e8ec9ac6fb5636dc90b1d8881affddd7cc2b52850d`
- sha256(criteria_true) = `c103e9c0d5b5a18ea3285083a1ec0c32a4c8a7b720d45940c277ecbd4b883903`
- sha256(criteria_false) = `cd1be4674a1c6604298c298e337234cb8c6f981ca135470303429618b361caa6`
- sha256(question-combined) = `e9c0b69376f8af3d28fe720f00709520071b51f920f538e61537718f1312ed9e`

```text
Compare `new_memory.content` with `candidates[0].content`. Does the new memory explicitly replace the candidate's previously valid fact with an updated fact?
```
```text
An explicit update supersedes the earlier fact for current-state questions.
```
```text
No explicit replacement; mere recency or a separate event is insufficient.
```

### slot mem_cons_link

- source: memory/jev_questions.py:98-100
- kind: noul  ·  projection: ["left","right"]
- sha256(instructions) = `2617033629c7423426968076489cb6a175961cbaa29b1777c65bd9a33e4066a9`
- sha256(criteria_true) = `96fbc43599a8e076000d1d6e2890598f5cce38570c440884362035aea2ebf46f`
- sha256(criteria_false) = `c8947991b38d48b469bd4ffc2703f192ca9d9e4c7eaaaeefd163ecc2a1242741`
- sha256(question-combined) = `e61b9e1f25fe714c8d80ab99b066b56ffb499c2f82da7e44533cb134e69f7b09`

```text
Compare `new_memory.content` with `candidates[0].content`. Would following a link between these observations help answer a future recall question?
```
```text
The connection supplies related, corroborating, correcting or contrasting evidence.
```
```text
There is no specific connection useful for recall.
```

### slot mem_cons_representation

- source: memory/jev_questions.py:101-108
- kind: choice  ·  projection: ["left","right"]
- sha256(instructions) = `d12f19328fca90dddea26bce1814abc709d4738d98f1734cea1bef647b0aec36`
- sha256(criteria-json-line) = `d79827a3d9af092bf4f0a65150e6081760aec4d30e244569a6229535f6118a44`
- sha256(question-combined) = `d12f19328fca90dddea26bce1814abc709d4738d98f1734cea1bef647b0aec36`

```text
Compare `new_memory.content` with `candidates[0].content`. Which representation best fits the relationship between these two observations? Judge from the supplied accounts; do not assume answers to other questions.
```
```json
{"keep_separate": "Contradictory accounts, unique details that a combined representation would lose, or distinct facts/events without a supported general pattern.", "merge": "Compatible accounts of the same fact or event can be combined without losing unique details.", "promote": "Distinct repeated episodes explicitly support a stable general pattern suitable for semantic abstraction; prefer this over merge for repeated events.", "uncertain": "Insufficient evidence to choose a safe combined or separate representation."}
```

### slot mem_routing_semantic

- source: memory/jev_questions.py:114-115
- kind: noul  ·  projection: ["query"]
- sha256(instructions) = `7a8a6babae416b438405d8023a220232994e9be4e491df08b07b4a9a0edb1077`
- sha256(criteria_true) = `15de9911443fd7f6692cbdb58e6e2d5e7d9f8afb8bdde63f6ef26b7b546d2ad4`
- sha256(criteria_false) = `f69a342a309e1384fab9a5907f3208b6947ee8b77aa95988660615462be7272f`
- sha256(question-combined) = `b5209c12740b35cbeae81bb9422fc2e3ad1f4466b048d9ee69c17ed60253f03d`

```text
Would finding topically or semantically related memories help answer `query`?
```
```text
Recall of related facts is useful.
```
```text
No related-memory lookup is needed.
```

### slot mem_routing_temporal

- source: memory/jev_questions.py:116-117
- kind: noul  ·  projection: ["query"]
- sha256(instructions) = `4008521966703714d52c1264f8cbfd59f3f1233ee03e9c7a3b80bb1834bf0ed6`
- sha256(criteria_true) = `11c9550f8f70d8687da514f893265a07a924be415b09e465c01c088b523050eb`
- sha256(criteria_false) = `8150f282361d95509252508ba6f2a7e2dabe1d4ce9cd9bb55d90593dff751aac`
- sha256(question-combined) = `369f02357b1f9bf28771c7f48c2ece8ef82f425f118aabbc4523a627db119a9a`

```text
Does answering `query` require event dates, durations, ordering or changes over time?
```
```text
A time relation is needed to answer correctly.
```
```text
Dates or ordering are incidental to the answer.
```

### slot mem_routing_causal

- source: memory/jev_questions.py:118-119
- kind: noul  ·  projection: ["query"]
- sha256(instructions) = `8d75130a46efbdac57a0f7cc5b838bb669b23b15cffb8c2c8c1e777827ed82fe`
- sha256(criteria_true) = `597486894159b11eca00499a61d4b4dcb41bc7afa7626bc5297d700aab35c0e6`
- sha256(criteria_false) = `5a54c6bbc2f627bc78f8a528727ead370bbe141e014ddbdc8c9379eab61c7849`
- sha256(question-combined) = `370782467c6dc72fd4a638abf1034aaadff0b2ff468ff63ca6e6dbbc00ad5927`

```text
Does answering `query` require explaining a cause, motivation, enabling condition or effect?
```
```text
Causal or explanatory evidence is needed.
```
```text
Only factual association or chronology is requested.
```

### slot mem_routing_entity

- source: memory/jev_questions.py:120-121
- kind: noul  ·  projection: ["query"]
- sha256(instructions) = `1a146cf38a0c6e797da12e639a6167fe738a862623b65795bdff4b4f52aa29f3`
- sha256(criteria_true) = `fa82a39c0eb758a488ab654deac3fd1f34bf0851631113233d21064305784cc5`
- sha256(criteria_false) = `e8b649585cc72005ca7ac85b9436a29605d301d610b37533a7fdfd1f72bd26ce`
- sha256(question-combined) = `54162ecef27227d45a6f64b450fefcda191c8f16931e3a2ed0a03dbd64e49958`

```text
Would connecting mentions of the same person, place, object or organization help answer `query`?
```
```text
Combining entity-specific facts or aliases is useful.
```
```text
Entity identity is irrelevant to the answer.
```

### slot mem_routing_multi_hop_need

- source: memory/jev_questions.py:122-123
- kind: noul  ·  projection: ["query"]
- sha256(instructions) = `4182154ab2a7115b1473f420876353185d3d847d1ff019713586bed9d50d0189`
- sha256(criteria_true) = `53e13d65c57d0c619b7a4dafa915f8cd011d3e1c0a0e6d968a5bf9e287cd3588`
- sha256(criteria_false) = `3c9f621bbcc429d926c1cf385e7ee892b527e5cc802399750721957072a42f76`
- sha256(question-combined) = `77cc24fc32e5700c4f60a1440c32b0ea270c45796cc68c8f5f2ab2521dc7a269`

```text
Does `query` require combining at least two distinct pieces of remembered evidence?
```
```text
The question asks for a comparison, aggregation or chained inference.
```
```text
One direct remembered fact suffices.
```

### slot mem_routing_recency_importance

- source: memory/jev_questions.py:124-125
- kind: noul  ·  projection: ["query"]
- sha256(instructions) = `221e4ec9e0456f25ce8fee6385fcc4a2b424d1b6baa12b857c9fe00815e916e3`
- sha256(criteria_true) = `83c85a75c6388778cb1dbc3dec92bc450ce2899b7e8745f42d3c1aef14f48f43`
- sha256(criteria_false) = `4174cef31d867542119c3c989609d1e1e7cc4d96067267c71ed72d0b8a7e5808`
- sha256(question-combined) = `ecb00eefee510c81f1a4bc67da7685ab7c726b3452d9e802ececc72c54f8cfac`

```text
Does `query` require the latest applicable fact rather than a historical fact?
```
```text
Current state, latest update or recent status is requested.
```
```text
Historical or timeless facts answer the question.
```

### slot mem_stop_sufficient

- source: memory/jev_questions.py:131-133
- kind: noul  ·  projection: ["query","evidence"]
- sha256(instructions) = `24298d6ac0114f456ff36f397d76a134da4f743c1c46ec18885ae228ef767517`
- sha256(criteria_true) = `a7744755c63c840200234272180e24e832c31495675cdad829ab74542ffad659`
- sha256(criteria_false) = `93c30778da97881e3bf9026e65e0bb8f42325ca5c3e2e67b0798a106f848786a`
- sha256(question-combined) = `a242b1cc7c1933efb07bb8e27ca16fef66cda7b06aa467b8da184d4496e37cd9`

```text
Does `evidence` contain support for every factual part of an answer to `query`?
```
```text
A grounded answer can be given from these memories without inventing missing facts.
```
```text
Any required fact or reasoning link is unsupported; related topics alone are insufficient.
```

### slot mem_stop_continue

- source: memory/jev_questions.py:134-136
- kind: noul  ·  projection: ["query","evidence"]
- sha256(instructions) = `9dddc2946e40a2e0ab0462f137ec6c518ee90742eb7ea0dc3f4c2a7670ef3678`
- sha256(criteria_true) = `9640d2c09c8a3100e4115c1922e07a2373cfca43e0f826a3f1873f9a5f09bd64`
- sha256(criteria_false) = `56eae415e0cf8123b1bf8d344c0639246e2505df0bc3c2115ad19b70a372bcea`
- sha256(question-combined) = `bab38078e48dc1b1e9e054bd2f0c0596cb910a742b003928e99ae349961ff851`

```text
Given `query` and `evidence`, is another retrieval round likely to fill a specific gap or resolve a conflict?
```
```text
An identifiable missing fact or conflict could benefit from more memory retrieval.
```
```text
No identifiable retrieval need remains or more memories are unlikely to help.
```

### slot mem_stop_missing

- source: memory/jev_questions.py:137-139
- kind: noul  ·  projection: ["query","evidence"]
- sha256(instructions) = `f95d64b1895125b593db973cdb40dadb3a82ec44b2ba516c794b0d60cf4116a4`
- sha256(criteria_true) = `e2d1aa95284d72e5fa2daf11fcb538f3d60931b793aa1152bd87da04ddb0514f`
- sha256(criteria_false) = `862b3e08f8c46ad585228c189267618e936f429662664ff8fc721c0c2b896d7b`
- sha256(question-combined) = `a5758e890dd9fc4232c2c6cd822815c30e410c0785e6ba6911de3421ca32c432`

```text
Is at least one fact required by `query` absent from `evidence`?
```
```text
A required detail, date, identity, count or linking fact is not supported.
```
```text
All required facts have explicit support in the supplied evidence.
```

### slot mem_stop_contradiction

- source: memory/jev_questions.py:140-142
- kind: noul  ·  projection: ["query","evidence"]
- sha256(instructions) = `ebf0573cd88d1438c479a2380ba7515f3ad55221e5aa541f18ee3c82af2202db`
- sha256(criteria_true) = `f6903376f2403b7c83db8de04dbbe0633d8d8bac543055923a31d5afa2b8de63`
- sha256(criteria_false) = `b06e8f3401ebf042b943a17efcc99b6990eb611d2105d2fb147ca8fbe3ad2eb1`
- sha256(question-combined) = `75a40bfddfa705e174567da73375e4f61111b17c2f13118f51182736515cfac2`

```text
Does `evidence` contain conflicting claims relevant to `query` that the supplied time/context cannot reconcile?
```
```text
A conflict still affects which answer is correct.
```
```text
Claims agree, differ only by explained temporal updates, or do not affect the answer.
```

### slot mem_trav_relevance

- source: memory/jev_questions.py:149-150
- kind: noul  ·  projection: ["query","candidate","path"]
- sha256(instructions) = `f94d613867401ea418fcfa3401ab1dcb70a79c21e9dd25b143275ab105623212`
- sha256(criteria_true) = `5131c636c9a3208d3590facdf861eabe2a9b49a83331b40b7a3e44850ba1cf3d`
- sha256(criteria_false) = `2e9d0cbd4e898b83ac994c1d8b176b4fe7f6ca2d4a4c915771c472ead7371833`
- sha256(question-combined) = `f16d235e0a993e7bdda88193e473764f0792ff49009d062f988eae6d9ee1507a`

```text
Does `candidates[0].content` contain a fact needed to answer `query`?
```
```text
Direct answer evidence or a necessary intermediate fact.
```
```text
Only topic overlap or unrelated content.
```

### slot mem_trav_relation_usefulness

- source: memory/jev_questions.py:151-152
- kind: noul  ·  projection: ["query","candidate","path"]
- sha256(instructions) = `c934cd725cb746d2d56c3d03749fb27a3cc5b060c8395f3ea84d1f5f38060bc0`
- sha256(criteria_true) = `83c3cb8164a5ccc7f50af1e95559153689ffd2b1bdbf00d823efd94d797b91f0`
- sha256(criteria_false) = `42840680d9e4f95884f6faa98cc607558cb75723ac7fbcbdb2fc79ca75619c45`
- sha256(question-combined) = `3a1ab370e5a5552a313ba8cb8dcd8955443c9001928de021d4572629e67ba38f`

```text
Does the stated graph relation of `candidates[0]` connect `evidence` to information useful for `query`?
```
```text
The relation and its direction support an answer-relevant connection.
```
```text
A graph edge exists but has no demonstrated usefulness for this question.
```

### slot mem_trav_new_information

- source: memory/jev_questions.py:153-154
- kind: noul  ·  projection: ["query","candidate","path"]
- sha256(instructions) = `06a9c4ad39522d8c6c5c749e9c3a0399dae5e1e7ff790718f74f58ad4329f233`
- sha256(criteria_true) = `4987852c02b8ee5c9130b2eee0d594b3b2df2e39989a9864f83a2537a8f19c64`
- sha256(criteria_false) = `55b00f4ac7093ace2d4508825079a40377babb5a8bd45f2aaf48cbf027e811df`
- sha256(question-combined) = `7a6122debb245cee0ced86f19dd9163e883fb0f9c75f39cd30da146cd919f9f3`

```text
Does `candidates[0].content` add an answer-relevant detail absent from `evidence`?
```
```text
A distinct relevant detail or missing reasoning link.
```
```text
Only duplicated evidence or irrelevant new details.
```

### slot mem_trav_supports

- source: memory/jev_questions.py:155-156
- kind: noul  ·  projection: ["query","candidate","path"]
- sha256(instructions) = `368340905542c19acee48e68ab3ec68588dba842be77853ae4d858b02920b2b7`
- sha256(criteria_true) = `477c51db0683c8eb5f5402cecc6d684a21b4184135498ddcdc34472a3eab543a`
- sha256(criteria_false) = `5a4add843034afa065db3359262a8475d2a2fb59ca1e287624e16537f2a463e1`
- sha256(question-combined) = `aea23336ac3d17c49b8f91aaf939b45383c0ea192a50cb9dbbe07478f0bcbd04`

```text
Does `candidates[0].content` independently corroborate a claim in `evidence` relevant to `query`?
```
```text
Provides compatible corroborating evidence for a specific claim.
```
```text
No specific corroboration, or contradicts that claim.
```

### slot mem_cons_fidelity

- source: v13-local (本仓拟定,无上游槽)
- kind: noul  ·  projection: ["source","summary"]
- sha256(instructions) = `04834a592b195f93646c0e3041808816e9c22c22de6719f47127b8286d38a5d7`  ·  criteria = NULL(v13 noul 形状,无上游 criteria 对)
- sha256(question-combined) = `04834a592b195f93646c0e3041808816e9c22c22de6719f47127b8286d38a5d7`

```text
Does the consolidated memory faithfully preserve the load-bearing content of both source memories (protected IDs, paths, numbers, tool pairings, decisions)? answer yes/no
```

---

## 附录:上游 MIT License 全文

```text
MIT License

Copyright (c) 2024 Anonymous Authors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

