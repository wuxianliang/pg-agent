# 第 7 章：artifacts 平面——中间产物内容寻址

> 前置：第 2、6 章。产出：`v13/schema/core.sql` 的 `artifacts` 表 + `chunks` 投影（G1 + G-ctx2 验收）。
> 对照上游：`v6.1` 调研（内容即值、文件身份≠路径）、`v10` 冻结稿里被保留的种子
> （内容寻址 artifact）。
> 设计对照：`docs/designs/v13-context-on-pg.md` §4.2（chunks 投影三纪律）、§5.2（manifest 指针）。

## 7.1 这一章要做什么

第 6 章的工具们要协作：Python 的分析结果给 Swift 工具用，DuckDB 解析的 AST
给 LLM 用，RAG 检索的 chunk 给判断平面用。常规做法是让工具互相传文件/
共享内存/彼此调用——语言边界就是地狱。

v13 的裁决：

> **工具之间从不直接交换数据，只交换 artifact 引用。**
> 每个 artifact 是一行：内容寻址、不可变、可溯源。

这就是「中间产物可以互通」的全部机制——**互通 = 下游工具的 args 里写 artifact_id，
结算事务里校验它存在且已结算**。语言差异、进程差异、时序差异全部消失在行里。

检索用的 chunk **不是**再给 artifacts 加一个表达式索引。`kind='chunk'` 仍是
不可变内容行；面向召回的 `chunks` 是可重建投影，三纪律进 7.5，
装配当时「发现了什么」记在 context artifact 的清单上（7.3 的指针）。

## 7.2 最小形态

```sql
CREATE TABLE artifacts (
  artifact_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  content_hash text NOT NULL,          -- sha256；相等判断与语言无关
  kind         text NOT NULL,          -- 开放词表：'text','table','ast','chunk',
                                       -- 'embedding','view_def','file','summary',
                                       -- 'context',...
  inline       jsonb,                  -- 小产物：值即内容（默认 ≤1MB）
  ref          text,                   -- 大产物：外部存储指针
  size         bigint NOT NULL,
  produced_by  uuid NOT NULL REFERENCES effects(effect_id),  -- 溯源：哪个 effect
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON artifacts (content_hash);            -- 内容寻址查找
CREATE INDEX ON artifacts (kind, created_at DESC);   -- 按类浏览
```

生产（settle 事务内）与消费（effect 创建时校验）：

```sql
-- 生产：v13_complete 的扩展——结果落账同事务写 artifact
INSERT INTO artifacts(content_hash, kind, inline, size, produced_by) VALUES (...);

-- 消费：v13_advance 创建 effect 时
SELECT 1 FROM artifacts a JOIN effects e ON e.effect_id = a.produced_by
WHERE a.artifact_id = ANY(p_arg_artifacts)
  AND e.status = 'succeeded';          -- 不存在或未结算 → 拒绝创建（fail-closed）
```

## 7.3 chunks 投影与 context manifest 指针

`kind='chunk'` 的 artifact 仍走 7.2：不可变、内容寻址、外键溯源。
**检索索引不能建在 `artifacts.inline` 上**——设计已裁，三条物理原因：

1. artifacts 是多 kind 的 JSON 容器，把 `==>` 绑到表达式列脆弱（第 10 章绑定纪律）；
2. artifacts 无 DELETE：源文件改写后死 chunk 永不离开表，**永久稀释 IDF**
   （BM25 是语料统计的函数，同一 SELECT 换个时刻本就换一批结果；死行让「换时刻」
   变成「永远被幽灵稀释」）；
3. 不可变行的主键会活过任何一次重摄取，检索身份却不该活过——下一节纪律 3。

所以物化一张专用投影表。索引建在这张表上；投影行可以随重摄取死亡，
artifacts 本体不动：

```sql
CREATE TABLE chunks (
  source_hash      text NOT NULL,     -- 源 artifact 的 content_hash
  chunk_no         int  NOT NULL,
  body             text NOT NULL,
  content_hash     text NOT NULL,     -- 行自证：写入时 = sha256(body)
  corpus           text NOT NULL,     -- 文档语料 vs 记忆语料，分索引
  chunker_version  text NOT NULL,
  analyzer_version text NOT NULL,
  PRIMARY KEY (source_hash, chunk_no)
);
-- 索引随行同事务提交（WAL）。不在 artifacts.inline 上建表达式索引。
```

`chunks` 不是第二真相源：body 来自 `kind='chunk'` 的 artifacts；
`v13_rebuild_chunks()` = truncate + 从 artifacts 重灌。主键仍是
`(source_hash, chunk_no)`。跨源同文会落两行，判断缓存按 `content_hash`
吸收；IDF 轻微失真实测超标再迁 `content_hash` 主键。

重摄取没有同步器、没有失效协议——就是一笔事务：

```sql
BEGIN;
INSERT INTO artifacts(...) VALUES (...);          -- 新源 + 新 kind='chunk' 行
DELETE FROM chunks WHERE source_hash = :src;      -- 旧投影行死亡
INSERT INTO chunks (source_hash, chunk_no, body, content_hash, ...)
SELECT ...;
COMMIT;
-- 提交后插入即可检。中途崩溃整笔回滚，索引不脏。
```

**manifest 指针。** 模型实际消费的不是 `chunks` 行，是一份 **context artifact**
（`kind='context'`），里面嵌装配清单——**manifest = IR**。每个 section 至少记
`content_hash`（外加 cache_scope / priority / est_tokens / payload_ref）；
查询侧还记候选 hash / bm25 / 命中跨度 / `decision_id`。清单的完整 schema、
applied/skipped 双分支、三种回放语义在第 10 章展开。本章只钉一条：
**清单与 `decisions` 只记 `content_hash`，不记 chunks 主键**——投影行会随
重摄取死亡，hash 才是跨重灌仍能对上的身份。

## 7.4 逐段解释

- **不可变 + 溯源是不变量**：artifact 没有 UPDATE 路径；`produced_by` 必须指向
  已结算 effect。「证据链」不用建——它就是外键。第 9 条不变量的全部内容。
- **`content_hash` 是跨语言相等性**：Python 产的表和 Swift 处理过的表是否同源，
  比对 hash 即可——不需要任何语言共享代码。也是第 14 章回放「输入逐字节一致」的锚。
- **inline vs ref 的阈值是数据**：默认 1MB。界限写死在常量里就违反本教程的习惯——
  放 `meta`（第 15 章），可调。**不让 artifacts 表变成对象存储**：超限一律 ref。
- **`kind` 开放词表**：新领域（第 10 章 RAG 的 `chunk` / `context`、第 9 章工作台
  的 `ast`）自定义 kind，零 DDL——和 events.type 同一条缝。`kind='chunk'` 是内容行；
  检索投影是 `chunks` 表，不是再给 inline 加一条表达式索引。
- **链条走 artifacts，不走 sticky**：工具 A → B → C 的链式分析，
  中间每步的产物是行。会话亲和的温缓存（第 9 章）只是加速器——
  丢了 fail-closed，从 artifacts 重放。**正确性永远不依赖易失状态。**
- **内容即值（v6.1 调研的兑现）**：`parse_ast(code, language)` 吃内容不吃路径——
  文件系统问题被消灭在接口形状里。文件身份 ≠ 路径：rename 不改 artifact 身份
  （id 永存），路径只是 ref 的一种。
- **投影行自证，外部不引用它的主键**：`chunks.content_hash = sha256(body)`，
  且对应 `artifacts(content_hash, kind='chunk')` 必须存在。manifest / decisions
  只记这个 hash——重摄取杀死 `(source_hash, chunk_no)` 行，不杀死身份。

## 7.5 硬性规定与 gate

```text
G1/G7 节选断言：
✓ artifacts 无 UPDATE/DELETE 路径（触发器拒绝）
✓ produced_by 指向非 succeeded effect 的插入被拒
✓ 消费不存在的 artifact_id：effect 创建 fail-closed
✓ inline 超 meta 阈值被拒，必须走 ref
✓ 同 content_hash 不同 artifact_id 共存（内容寻址 ≠ 去重；去重是上层选择）

G-ctx2（chunks 投影）——三纪律：
✓ 行自证：每一行 content_hash = sha256(body)，且
  exists artifacts(content_hash, kind='chunk')；
  v13_rebuild_chunks() = truncate + 从 artifacts 重灌，跑两次字节级一致；
  verify_index 进 gate（pg_cron 夜跑是同一条命令的定时形态）
✓ 重摄取 = 与新 artifacts 同一事务 DELETE BY source_hash + INSERT：
  提交后插入即可检；事务外看不到中间态；没有同步器、没有失效协议
✓ 外部一律引用 content_hash，不引用 chunks 主键：
  context artifact 的装配清单（manifest）与 decisions 只记 hash，
  不得出现 (source_hash, chunk_no)——投影行会随重摄取死亡
```

装配清单的字段表、applied/skipped 双分支、三种回放（exact replay /
recompute / fresh fork）不在本章展开——指针在 7.3，schema 在第 10 章。
本章 gate 只钉纪律 3 的那一半：清单行里没有 chunks 主键。

## 7.6 检查点练习

1. 写 `v_lineage(artifact_id)`：递归 CTE 追溯生产链到最初的 user 输入事件。
   这是「证据链」视图——观察平面（第 15 章）的核心件。
2. 实现去重视图 `v_dedup_artifacts`：同 content_hash 取最早 id。
   思考题：为什么核心不做自动去重？（提示：produced_by 溯源与重放语义。）
3. 压测：灌 10k 个 100KB artifact，量 inline 查询与 ref 查询的延迟差。
   把数字写进 `meta` 的注释——这是调 inline 阈值的依据。
4. 实现 `v13_rebuild_chunks()` 与一次重摄取。断言三纪律：行自证 + 对应
   `kind='chunk'` artifact 存在；同一事务 DELETE+INSERT 该 `source_hash`，
   提交后旧主键消失、新 `content_hash` 可检、事务外看不到中间态；
   一份假清单若引用 `(source_hash, chunk_no)` 则 gate 红，只许引用 hash。

## 7.7 回到 vN 对照

- `v6.1-code-file-workbench-plan`：两条被保留的调查结论——内容即值、
  文件身份≠路径——在本章兑现为表结构；tigerfs/双平面被降级为第 9 章的 handler 细节。
- `v10-dev.md` 的 context_artifacts：内容寻址 artifact 是 v10 五阶段管线里
  唯一被 Oracle 保留的种子（「可独立实现」）——v13 把它从管线里拆出来，
  变成所有工具共享的平面。检索面再拆一刀：不可变内容留在 artifacts，
  可重建投影留给 `chunks`，当时交给模型的证据链留给 context artifact
  内嵌的清单（第 10 章）。

## 7.8 内在合理性：前因后果

**作用力**先于任何设计存在。其一：一个进程只精通一种语言——Python 的
DataFrame、Swift 的 AST、SQL 的行，内存里没有共同表示，能横跨三者逐字节
比较的只有内容本身。其二：崩溃可以落在任何指令边界，backend 一死事务即
回滚，行锁只活在事务内——任何跨语句的有效性都必须落成持久行，不能活在
连接或进程内存里。其三：判断有成本且答案可缓存，同一份输入被第二个工具
消费时重判是纯浪费。其四：把大对象塞进 OLTP 行有真实账单——WAL 放大、
TOAST 重写、备份窗口，随体积线性走。其五：**BM25 是语料统计的函数**，
IDF/avgdl 随 ingest 漂移；索引随行同事务提交（WAL），没有独立的失效协议。
其六：投影行在重摄取时必须能死，否则死 chunk 永久稀释 IDF。六条全是物理
与经济事实，不是偏好。

**推导**：跨语言相等性逼出 `content_hash`——字节级哈希是三种语言唯一共同
的分母，配上 hash 上的索引，「同源吗」从跨进程协商退化成一次 B-tree 探测。
不可变性逼出「无 UPDATE 路径」：执法是声明式的（外键、约束、拒绝 UPDATE
的触发器），每次写入都检查、不靠工具自觉；而 artifact 一旦不可变，溯源就
退化成 `produced_by` 一个外键——证据链不需要专门机制，追溯查询是一条递归
CTE 视图，视图是计算不是存储，链条不占额外空间。互通=只传引用：语言差异、
进程边界、时序错位全部消失在行里；直接互调则每对语言一条集成路径，n²
增长。inline/ref 阈值放 meta，因为阈值是两侧成本的交点，随硬件漂移——
写死常量等于把账单写死。链条走 artifacts 不走 sticky 会话状态：温缓存易失，
正确性只能依赖 durable 的行。

同一组力把检索面从 artifacts 上拆下来。不可变表留不住「行必须能死」：
死 chunk 稀释 IDF，表达式索引还把 `==>` 绑进多 kind JSON 容器。所以
`chunks` 是可重建投影——**行自证**（`content_hash = sha256(body)`，且
对应 chunk artifact 存在）让 rebuild 可验证；**重摄取与新 artifacts 同一
事务 delete+insert** 让索引随事务一致，同步器和失效协议都不必存在；
**外部只引用 content_hash** 是因为主键 `(source_hash, chunk_no)` 会随
重摄取死亡，而 manifest / decisions 必须在重灌之后仍能对上当时发现的内容。
模型看到的那一份「当时发现了什么、实际交给它什么」不写在投影主键上，
写在 context artifact 内嵌的清单里（第 10 章）。

**反事实**：去掉内容寻址，工具互传文件路径。T0，Python 工具把
`/tmp/anal-9f2.csv` 落盘并作为参数交给 Swift 工具；T1，例行清理删掉 /tmp——
外部 IO 与事务无原子性，库根本不知道这个文件存在过；T2，Swift 工具读失败，
但它已建好 effect——超时≠失败，IO 也无法回滚语义，链条从这一步起每个下游
都指向不存在的路径。再去掉不可变性：T0'，A 产 artifact X，B、C 各自结算了
消费 X 的 effect；T1'，有人「修正」X 的 inline；T2'，B 的 lineage 从此说谎
且无人能察觉——行上没有版本，「输入逐字节一致」的回放锚已断。

再把检索索引建回 `artifacts.inline`：T0''，源文件 v2 落成新 chunk artifacts
（旧行不能删）；T1''，BM25 的 IDF 被 v1 的死行稀释，同一查询换一批名次，
且没有报错指向幽灵；T2''，rebuild 无从下手——不可变表没有「重灌」语义。
再把重摄取拆成两笔事务：T0'''，新 artifacts 已提交；T1'''，worker 在
DELETE chunks 前崩溃；T2'''，召回同时看见新旧投影，没有同步器比「同一事务」
窗口更短。再让 manifest 引用 `(source_hash, chunk_no)`：重摄取后旧主键死亡，
「当时发现了什么」无法重读，回放与判断缓存全部断锚。

**被拒替代**：共享文件系统直传——路径生命周期不受任何事务保护，rename 或
清理即断链，相等性退化成会撒谎的路径字符串。对象存储直连（工具各自持
key 互传）——持久性解决了，但「上游已结算」仍需有人校验，等于把 fail-closed
检查在每种语言里重写一遍。消息里夹带大负载——队列 at-least-once、NOTIFY
不持久，负载与结算事务无原子性，重放语义直接崩塌。同样的力之下，它们都
比「一行不可变、内容寻址、外键溯源」更贵。

检索面上被拒的是另外三件。**`artifacts.inline` 表达式索引当检索表**：多 kind
JSON 容器绑定脆弱；死 chunk 永不离开，IDF 被永久稀释。**独立同步器 /
失效协议**：索引本就随行同事务提交，第二通道只会引入「源已提交、投影未改」
的窗口。**外部引用 chunks 主键**：投影行的生命周期短于证据链需要的身份——
身份是 `content_hash`，清单在 context artifact 里，不在主键上。
