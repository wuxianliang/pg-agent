# v13 DP4 实现 L4 验收评审（chunks 投影与跨度装配）

> 评审者：父级 Loop Orchestrate 的 L4 验收代行。`context_builder` `response_type=review` 三路 Oracle：gpt-5.6-sol 完成（PASS-with-notes / 5P1）；grok-4.6 **provider_error 失败**（`ACP protocol violation: session/set_config_option … malformed model metadata`）；claude-fable-5 **失败**（403 weekly usage limit）。按 dp2-fix-dp3 先例降级：以 plan 原文 + `7b619ab` 源码独立核验为准，不采信未复核的 Oracle 推断；管道故障记入 §7。
> 被审对象：commit `7b619ab`（`v13: add chunks projection and span assembly`，7 files +2556/−2）vs 父提交 `5231fff`。
> 评审权威：`docs/plans/v13-dp4-chunks-projection-plan-2026-09-20.md`（1631 行；§1.1 硬边界、§3 SQL 草案、§4 A–J 断言表、A9b、§1.4 DP5/DP6 契约）。
> 已采信外部事实（控制器独立复跑，本评审不复跑）：七 gate 全绿（chunks **213** PASS + 前序 schema/resolve/loop/twophase/envelope/manifest）exit 0；提交已推 origin/main；diff 范围恰为 v13/chunks 五件套 + `v13/load.py` +2 + `v13/manifest/test_manifest.py` 2/2。
> 先例：上轮 dp2-fix-dp3 L4 = **PASS-with-notes**（无 P0 即正确性达标；P1 分阻断/不阻断，可开下一 DP）。dp5 plan L4 曾因扫描 gate 未定义归一化打回（P1-1）——本轮 G5 按 dp4 plan 字面裁量，不把 dp5 标尺回溯成 FAIL。
> 评审日：2026-09-22。

## Verdict：**PASS-with-notes** —— 0×P0 / 3×P1（1 合规不阻断 + 2 测试保真不阻断） / 8×P2

父循环 **可以开 DP5**。不给无 notes 的 PASS：`v13_manifest_validate` 第三处换体未获 §1.1 授权（P1-A）；I4 含恒真断言且未构造续字节窗（P1-B）；J3 反向次序与 J4「J1–J3 各三轮」未 1:1 落地（P1-C）。不给 FAIL：无 P0；SQL 机制面与 §3 草案同构（含 rebuild 策略校验——与草案同样不含 mode↔chunker 配对，见 §7 驳回）；三纪律 / lineage 跳过退役 / 八键 token / verify 七项+canary / pg_cron 降级 / 前缀第 7 位均在场且可证伪。

---

## 1. 两处边界事项裁定

### #1 manifest G6：`SQL_LOAD_ORDER[-1]` → `[5]` — **ACCEPT**（合法结构性适配）

**原意。** DP3 G6 要钉的是「manifest 在自己前缀切片的正确位置」，不是「全树永远末位」。同函数未动的邻近断言仍在：`files_through("manifest")==6`、五 stage 前缀排除 manifest（`test_manifest.py:376-383`）。`[5].name == "v13_manifest.sql"` 与「六文件前缀的第六项」等价：错位或前插即红。

**是否应改形态。** `[5]` **已经是** `SQL_LOAD_ORDER[5]=="v13_manifest.sql"` 的下标写法。不建议再钉「不存在第八项」——DP5 追加会再次改冻结 gate。本 stage 另有 `H4: chunks is 7th`（`test_chunks.py:957-958`：`SQL_LOAD_ORDER[6]==v13_chunks.sql` 且 `files_through("chunks")==7`），组合后比「全树末位」更符合可追加架构。

**触碰 DP3 测试是否合法。** plan §1.1 硬边界点名的是「DP1/DP2/DP3 **计划文件与其 SQL 文件**零改动」，未点名测试。实现循环禁削弱 gate：此改把「树终态」改回「stage-local 前缀位」，可证伪性不降。**记台账⑧正确**，属合法结构性适配，不是静默削弱。

### #2 `v13_manifest_validate` OR REPLACE 扩 corpus — **REJECT（计划合规）/ 保留机制**

**plan 有无明文。** 全文检索 `manifest_validate` / `v13_manifest_validate` = **0 命中**。§1.1 封闭清单恰两处：① `CREATE OR REPLACE FUNCTION v13_context_required`；② artifacts/decisions 各一 BEFORE 触发器。Size 行写「22 新 + **1** OR REPLACE v13_context_required」。§3.6 只给 context_required 换体。**validator 换体是第三处，无授权。**

**树级纪律。** 「OR REPLACE 允许、原文件不动」：**形态满足**——DP3 `v13_manifest.sql` 零改；同签名换体，OID/ACL 连续（前缀库不加载 7 号文件，七键体照常）。**封闭清单不满足**——§1.1「恰两处」被突破。README 台账⑤不能替代权威计划授权。

**换体 diff。** 对照 DP3 原体 `v13_manifest.sql:249-345` vs `v13_chunks.sql:929-1121`：除 `required_revision` 闭集七键→八键（增 `corpus`）+ `corpus>=0` 外，顶层键集 / policy / replay / sections / query_side / judgments **逐段同构**。无偷偷改校验器其它面。

**为何必须留。** DP3 原体把 required_revision 钉死 `'asm_ver,dec,gen_ver,goal,jdef_ver,sem,tools_rev'`。token 扩 corpus 后 G2 真实 `parse→advance→settle`（`test_chunks.py:758-770`）必 V3003。无此缝则八键 freshness 链路不可达。

**处置：** 保留实现 + **补 plan erratum** 列为第三授权缝。不回滚。升 P1-A（合规，不阻断 dp5）。

---

## 2. 5 项自报偏差 — 逐项裁定

| # | 偏差 | 裁定 | 台账 | 理由 |
|---|---|---|---|---|
| ⑤ | validator 八键 OR REPLACE | **REJECT（合规）/ 保留机制** | ⑤ 保留；**须补 plan erratum** | 见边界 #2。台账自辩「实现必要缝」事实成立，不能补授权 |
| ⑥a | 锁别名 `s→lk` | **ACCEPT** | README #6 足够 | ingest 锁查询 `unnest … AS s` 与 plpgsql `s jsonb` 撞名 42702；零语义 |
| ⑥b | `get_byte(…, (v_s-1)::int)` | **ACCEPT** | README #6 足够 | PG `get_byte(bytea,int)`，草案 `v_s-1` 无候选；零算法变化 |
| ⑦ | verify GUC 用 `SET` 代 `set_config` | **ACCEPT** | README #7 足够 | 同会话强制+正常/`query_canceled`/`OTHERS` 三路恢复（`v13_chunks.sql:560-576`）。与 dp2 偏差 #4（SET LOCAL 代 set_config 避 M4 `set_config` 子串扫描）口径一致 |
| ⑧ | DP3 G6 `[-1]→[5]` | **ACCEPT** | README #8 足够 | 见边界 #1 |

---

## 3. SQL 对 §3 忠实度

| 面 | 裁定 | 证据 |
|---|---|---|
| 三纪律 | **通过** | 行自证 CHECK 经 `v13_body_hash`（`:155-156`）；重摄取 DELETE+`v13_project_source` 同函数事务（`:427-435`）；spans 输出 `{doc,offsets}`（`:811-813`） |
| chunk_offset | **通过** | 列+`CHECK (>=0)`（`:146-147`）；A5 钉 whole 下 `chunk_offset=0` |
| superseded_by lineage | **机制通过** | 单一豁口触发器（`:93-114`：只许 NULL→值，禁改其它列/二次改/DELETE）；ingest 同事务标记（`:428-433`）；rebuild `WHERE superseded_by IS NULL`（`:464`）；GC 同跳过（`:507-510`）。测试交面见 §4 B |
| 哈希载体化 | **通过** | `sha256(to_jsonb(body)::text)`（`:13-16`）；`superseded_by` 不进 hash/token（台账③属实；corpus 键=generation） |
| 代数键 | **通过** | 单行 meta、INSERT/DELETE 语句级 bump、DELETE/调低拒（`:116-139`）；G3/G4 可红 |
| verify 七项 + canary + EXCEPTION | **通过** | 七项报告（`:580-597`）；canary=`quasar`；`SET enable_seqscan=off` + 三路恢复 + `gin_clean_pending_list` |
| span 四配置 + ⑧ EXIT WHEN | **主体通过** | sentence/fence/table/UTF-8 在场。⑧ 前置 EXIT WHEN：**end 环有** `EXIT WHEN v_e >= v_blen`（与草案 `:1136` 同构）；**start 环草案与实现均无** `EXIT WHEN v_s > v_blen`（plan-isomorphic，P2） |
| corpus 八键 | **通过** | `v13_context_required` OR REPLACE 仅增 corpus（§3.6 同构）。validator 同步正确但未授权（P1-A） |
| 摄取准入 A9b | **按计划通过（延后）** | v2 节明文「只立法，不改 §3.3 字面」「file 面未过门负向若后续加断言，只加不减」。README #10 / 台账④已记。F4 只钉 corpus 隔离，不得声称已实现注册门 |
| pg_cron | **通过** | CREATE EXTENSION 异常捕获 + NOTICE 降级 + 函数手调（`:1123-1141` 与 §3.7 逐字同构） |
| ACL / 纸面 / 前缀 | **通过** | BEGIN/COMMIT 包裹；写函数 REVOKE PUBLIC、运行角色零写（H3）；`SQL_LOAD_ORDER` 纯末尾第 7 位。chunks gate **无** DP3 式 paper `$$` 配平断言（P2 轻） |

**rebuild 策略校验：** ingest 有 `left(chunker_version, length(mode))` 配对（§3.3 `:603-604`）；rebuild 只有分词表（§3.4 `:703-710`）。**实现与草案同构。** 非法配对 `mode='whole'+chunker_version='para_v1'` 可过 rebuild、按 whole 切片却记 `para_v1`——是计划既有近似，**不升实现 P1**（§7 驳回 Oracle）。记 P2 草案残差，建议抽取共用校验器。

---

## 4. A–J 断言强度

标准：1:1 真实可红；无恒真 / covered-by / 伪链路。

| 组 | 裁定 |
|---|---|
| A | 主体可红。A2 `fails_with` 只匹配消息、不钉 V3004；CHECK 违约实为 `23514`（P2） |
| B | B1 真四步；B2 强制 seqscan off 后 **EXPLAIN + 真 quasar 查询**；B3 两连接 rollback；B4 幂等。B5 无引用 supersede + lineage 标记，与 B5 表「旧源无引用行死亡」+ B5b「仍零行」1:1。B5b 三负向 owner 直改均在场。混合「退役源仍有被引用行」未 fixture——plan B5b 自身按零行写，升 P2 非 P1 |
| C | extract 纯 offsets / assemble `{doc,offsets}` / 返回值白名单在场 |
| D | D4 回放主链（引用锁→策略翻 target 512→locked 源不变 / 未引用源重切）真实可红 |
| E | rebuild 字节幂等；verify 七项正负向在场 |
| F | **通过**。F1/F3 会话 `enable_seqscan=off` 后 EXPLAIN 含 `ix_chunks_tsv`；B2 同强制下真查询命中。不是「只见索引名」。F2 CJK 零命中钉 T0 边界；F4 两 corpus 不串 |
| G | G1 八键；G2 **真实** parse_settle → ingest → fresh=false → 再 settle（依赖两处 OR REPLACE）；G3 DML bump；G4 RAISE/meta 守卫；G8 策略负向族走 ingest。G5 裸 `in src_sql` 不剥注释/不要求限定名——plan G5 字面即「不含字样」，当前三串不在注释中故不会假绿；dp5 归一化标尺不回溯 FAIL，记 P2 |
| H | H1 p99 三轮中位；H2 两连接读 **token**（`v13_context_required`）而非 plan 字面 `advance`（P2）；H3 ACL 负向；H4 前缀 7 + DP3 原体无 corpus 键；H5 跨源同文 |
| I | I1 句界（英文句点端点 + CJK 。）可红。I2/I3 用「包含」而非精确起止，侵入钮外未测（P2）。**I4 恒真** → P1-B |
| J | J1 已提交引用+rebuild 存活。J2 **真两连接**（A 未提交 INSERT context 持锁 → B rebuild 阻塞 → COMMIT → 行存活），不是纯计时；`wait_lock` 先接受任意 `wait_event_type='Lock'`，其次才 `pg_locks` 未授予 advisory（P2 松）。J3 rebuild 持锁未提交 → ingest 排队、零 23505、一代切片——**正向真并发**；缺 plan「反向次序同断言」。J4 只 3 轮异 source 并行 ingest，未「J1–J3 各三轮」→ P1-C |

### P1-B I4 详证

plan I4：`context_bytes` 窗口端点须落在 CJK **续字节**上，输出两端均为前导字节。

实现 fixture：`utf_doc="ab世界cd"`，`p_s=3,p_e=4,context_bytes=1`。UTF-8 布局：`a=1,b=2,世=3–5,界=6–8,c=9,d=10`。`3-1=2` 是 ASCII `'b'`，**start 吸附根本不触发**。`check("I4: start not continuation", not (128<=lead<=191))` 在无吸附时也绿。

```python
if ue < blen:
    ...
    check("I4: end not mid-char leftover", True, nxt)   # test_chunks.py:1087-1089
```

`condition=True`：**恒真**。`ue==blen` 时整枝跳过。正确 fixture 例：核落在「界」前导（字节 6）、`context_bytes=1` → start 落「世」末续字节（字节 5）。

### P1-C J 组 1:1 缺口

- J3 反向（ingest 先持锁、rebuild 排队）未测。
- J4 字面「J1–J3 各跑三轮 + 异 source 并行 ingest」只落地后半。
- 两连接正向（J2/J3）**不是**伪链路；缺口是协议覆盖不是「没并发」。

### B5b 零复活（用户点名）

**咬到了 plan B5b 字面：** supersede 后旧源零行 → rebuild 后仍零 → GC delete 后仍零 + 三负向。机制上 rebuild/GC 都 `superseded_by IS NULL`，零行源不会被当前策略重投影。

**没咬到更强混合交面：** 退役源上仍有被引用行时——引用行存活、无引用兄弟死亡、rebuild 不按新策略给退役源添行。plan B5 括号「引用行存活(D 组前置)」把该面推给 D/J1；B5b 正文按「仍零行」写。**不升 P1**（否则惩罚实现 1:1 落地 plan 表）。记 P2：dp5 召回面契约⑨（退役源不进召回）开工前建议补混合 fixture。

### G5 vs dp5 扫描打回先例

dp5 plan P1-1 是「扫描 gate 未定义剥注释/限定名」。dp4 G5 权威是「本文件源断言不含三字样」。裸包含对「注释里写了名字」是假红（保守），对「真调用」能红。三目标串目前不在注释中。P2，不打回。

---

## 5. 修复清单

### P1（不阻断 dp5；建议 dp5 合并前或并行收）

1. **P1-A** plan erratum：§1.1「恰两处」改为三处，明文授权 `CREATE OR REPLACE FUNCTION v13_manifest_validate`（同签名、仅 required_revision 八键+corpus≥0）。不改 SQL。权威=plan，不是 README ⑤。
2. **P1-B** `test_chunks.py:1073-1089`：续字节窗 fixture（核落多字节第二字节）；断言 start 字节与 end 后一字节均非 0x80–0xBF；删 `check(..., True, nxt)`。
3. **P1-C** J3 加 ingest-first 反向；J4 按表把 J1–J3 各跑三轮（或改 plan 字面为「异 source 三轮冒烟」并台账）。J2 主断言改为目标 PID 存在 `pg_locks` 未授予 advisory（可保留 Lock 为辅）。

### P2（可随 dp5 / README）

4. rebuild 与 ingest 抽取同一 `chunks_ingest` 校验器（含 mode↔chunker 配对）。**草案同缺**，属 erratum 级加严，不是本提交回退。
5. `fails_with` 在承重负向传 `pgcode`（V3004 / 23514 分流写清）。
6. H2 另一连接走带当前 probe 的真 `v13_advance`，不只 `v13_context_required`。
7. G5 剥 SQL 注释后再扫标识符（对齐 dp5 先例，防未来假红/假绿）。
8. extract/assemble 同起点二级键 `(start,end)`。
9. UTF-8 start 环补 `EXIT WHEN v_s > v_blen`（草案同样缺；非法 UTF-8 尾续字节有越界读面）。
10. B5 混合退役+引用 fixture（给 dp5 契约⑨垫层）；I2 补「窗侵入块后钮到块外」。
11. README 锁纪律点名 DP6 decisions 多行事务须并集升序预锁或拆事务（plan §1.4 DP6 ① / 不变量 9）。
12. （可选）chunks gate 补纸面 `BEGIN/COMMIT` + `$$` 配平，对齐 DP3 G7。

### 明确不修 / 已驳回

- 回滚 validator 换体：G2 必断。
- 把 rebuild 缺配对打成实现 P1：与 §3.4 草案同构。
- 把 B5b 零行 fixture 打成 FAIL：与 §4 B5b 字面 1:1。
- A9b 本 DP 落 SQL：v2 节禁止。
- 改 G6 为钉树终态 / 禁第八项：破坏可追加。

---

## 6. 可否开 DP5

**可以开。** dp5 消费的本 DP 缝均在场且未被本提交破坏：

| dp5 契约（plan §1.4） | 本提交状态 |
|---|---|
| ① generation 并 cgr/probe | 键已进 token 第八；接线归 dp5 |
| ② T0 消费 `body_tsv` GIN | 生成列+GIN+F 组可证 |
| ④ extract 签名/offsets 形态不变 | 在场 |
| ⑧ 引用写锁 | artifacts/decisions 触发器在场 |
| ⑨ 退役源不进召回 | 台账列+rebuild/GC 已跳过；召回枚举归 dp5 |

建议顺序：plan erratum（P1-A）与 I4/J 测试补丁可并行于 dp5 开工；rebuild 共用校验器与混合退役 fixture 最好在召回面落地前收。

---

## 7. 方法与 Oracle 分歧

| 来源 | 结果 | 本报告处置 |
|---|---|---|
| Oracle 1（gpt-5.6-sol） | PASS-with-notes；5P1/5P2；可开 dp5 | **采纳** validator 第三换体、I4 恒真、J 协议不完整、G5 归一化为 P2、H2 token 代 advance、SET 代 set_config ACCEPT。**驳回** rebuild 配对为实现 P1（§3.4 同构）。**驳回** B5b 升 P1（plan 表即零行；混合面 P2） |
| Oracle 2（grok-4.6） | **失败**（ACP `set_config_option` malformed model metadata） | 降级：不重试、不采信空结果 |
| Oracle 3（claude-fable-5） | **失败**（403 weekly quota / kimi） | 同降级 |

独立核验：通读 dp4 plan §1.1/§1.3–1.5/§3.3–3.8/§4 A–J/v2 A9b；`v13_chunks.sql` 表/触发器/ingest/rebuild/gc/verify/span/两处 OR REPLACE/ACL/cron；`test_chunks.py` helper/`wait_lock`/A2/B2–B5b/F1–F4/G1–G8/H2–H5/I1–I4/J1–J4；`v13_manifest.sql` 七键 validator 原体；`test_manifest.py` G6；`load.py`；README 台账①–⑧；上轮 L4 格式与 dp5 扫描先例。未复跑测试。
