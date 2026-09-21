# 第 6 章：工具目录——目录是表，可见性是查询

> 前置：第 2、5 章。产出：`v13/schema/core.sql` 的 `tools` 表（G1/G6 验收）。
> 对照上游：`v2`（workbench 注册表）、`v5`（named tools）、`v6`（enqueue-only 工具）。

## 6.1 这一章要做什么

agent 能用什么工具？常规框架把工具写成代码注册（装饰器/插件类）——
工具有没有、给谁看，都住在代码里。v13 的裁决（v2 起，十二轮没变过）：

> **工具目录是表；工具可见性是查询。**

新增一个工具 = INSERT 一行 + 起一个 worker（如果是新语言/新 handler）。
决策平面（第 4 章）、推进函数（第 5 章）、其他语言的 worker——**全部零改动**。
这就是「目录是数据」买到的东西：**工具-任务匹配变成关系操作**。

## 6.2 最小形态

```sql
CREATE TABLE tools (
  name        text PRIMARY KEY,
  version     int NOT NULL DEFAULT 1,
  handler     text NOT NULL,          -- 'sql' | 'py' | 'swift' | 'duck' | ... 开放词表
  kind        text NOT NULL CHECK (kind IN ('sql','effect')),
  description text NOT NULL,          -- 给判断平面看的一句话
  input_schema jsonb NOT NULL,        -- args 形状（严格校验 effect.request）
  consumes    text[] DEFAULT '{}',    -- 吃什么 artifact kind（第 7 章）
  produces    text[] DEFAULT '{}',    -- 产什么 artifact kind
  mutating    boolean NOT NULL DEFAULT false,   -- 决定 unknown 纪律（第 2 章）
  allowlist   jsonb,                  -- 数据不是代码：路径白名单/表白名单/参数域
  timeout_ms  int NOT NULL DEFAULT 30000,
  max_attempts int NOT NULL DEFAULT 3,
  enabled     boolean NOT NULL DEFAULT true
);
```

工具分两档（v2 与 v6 的合流）：

```text
kind='sql'    纯只读函数：advance 同事务直接执行（第 5 章 ④），不进队列
kind='effect' 有 IO/副作用：走 effects 账本 + worker（第 2 章）
```

这个两档划分消灭了 v2→v6 之间反复出现的问题：
「为什么有的工具入队有的不入队」——因为它们本来就是两种东西。

## 6.3 逐段解释

- **`handler` 开放词表**：新语言接入 = 新 handler 名 + 一个 worker 进程，零 DDL。
  claim 的 `p_handlers` 过滤（第 2 章）让每种 worker 只领自己的活——单队列单总线。
- **`consumes/produces` 是匹配的关节**：工具-任务匹配从「全目录 Choice」降为
  「SQL join 预筛 + Jev 终选」——任务需要 kind X 的 artifact →
  `WHERE X = ANY(consumes)` 出候选集 → 判断只在候选集里选。
  判断负担下降一个数量级，且这是纯关系操作（「SQL 管算术，Jev 管语义」的又一次兑现）。
- **`mutating` 不只是标注**：它决定第 2 章 `v13_recover_expired` 的行为——
  非 mutating 失败可回 ready 重试；mutating 失败进 unknown。
  **一列数据驱动恢复策略**，不需要 per-tool 的恢复代码。
- **`allowlist` 是数据**：pi 式文件工具的根目录白名单、duck 工具的表白名单、
  SQL 工具的参数域——全部住在目录行上。改授权 = UPDATE 一行，审计 =
  `SELECT * FROM tools`。
- **只读角色执法（v2 的教训）**：模型生成的 SQL 永远跑在
  `default_transaction_read_only` 的角色下——**让数据库自己执法**，
  而不是文本黑名单（v2 的黑名单连字符串里的 `'set'` 都误伤）。
  这是 v8 grant 帝国被砍后唯一保留的种子：保护数据库不受模型，不是租户互防。

## 6.4 硬性规定与 gate

```text
G1/G6 节选断言：
✓ INSERT 新 sql 工具后，advance 无需任何代码变更即可路由到它
✓ consumes/produces 预筛：给任务注入 kind='ast' 需求，候选集只含吃 ast 的工具
✓ disabled 工具对判断平面不可见（fold_state 查 enabled=true）
✓ input_schema 不符的 effect.request 在创建时被拒（fail-closed，不静默修参数）
✓ mutating=true 的工具在恢复扫描中绝不回 ready（只能 unknown）
```

## 6.5 检查点练习

1. 注册三个假工具（sql 只读、py effect、duck effect），写 fold_state 的工具目录
   摘要视图：`v_tool_catalog(p_handler)`。断言：禁用一个后摘要即时变化。
2. 加 `tool_version_guard`：effect.request 里记录工具 version，settle 时目录已升版
   → 结果照常落账（已发生的执行不可抹），但新 effect 必须用新版本。
   （这是 v8 插件世代域被砍后保留的种子——第 15 章 meta 版本门的局部版。）
3. 破坏性实验：把 mutating 标错（真副作用工具标 false），构造 recover 回 ready，
   观察双执行。写断言把「目录 mutating 必须与实现一致」钉进 gate
   （FakeTool 双执行计数 == 1）。

## 6.6 回到 vN 对照

- `v2/pg_agent_workbench_core.sql`：`workbench_tools` 注册表 + refresh 计数——
  目录思想的原点，但注册走 SQL 注释解析（v13 裁决：一张表 INSERT 即可，注释注册表废除）。
- `v5/named_tools`：动作名是数据、解析即查询。
- `v6/duck_tools`：七个 enqueue-only `wb_duck_*` ——`kind='effect'` 档的完全体：
  SQL 侧只校验参数、落元数据、发唤醒；重活全在库外。

## 6.7 内在合理性：前因后果

**作用力。** 这张目录是被几条系统性质压出来的：

- **外部 IO 与事务无原子性**：数据库回滚得了自己的页，回滚不了已经
  发出的 HTTP 请求；「已提交」与「副作用已发生」之间没有原子性。
- **崩溃可在任何指令边界，且超时≠失败**：worker 死在哪一步永远未知，
  超时只说明「期限内没回音」，不说明「没发生」。
- **backend 死即回滚**：进程里的注册表与缓存随进程归零，可信状态必须
  住在表里；角色权限与 CHECK/UNIQUE 是现成的声明式执法者，不认文本长相。
- **判断有成本且答案可缓存**：判断按 token 收费、按秒计延迟，候选集
  每小一号，这笔账就便宜一号。

**推导。** 「可信状态必须在表里」逼出**目录是表、可见性是查询**：目录行
与 fold_state、advance、claim 共享同一个 commit 边界，`INSERT` 一行，
提交瞬间对所有读者可见——决策平面、推进函数、其他 worker 零改动；
`v_tool_catalog` 是视图——视图是计算不是存储，摘要永不与目录漂移。
「外部 IO 无原子性」逼出**两档 `kind` 是外部 IO 有无的物理分界**：
`sql` 档的全部效果就是数据库自身状态，同事务执行、backend 一死整体
回滚，原子性白送；`effect` 档碰库外世界，事务罩不住，只剩账本 +
worker + at-least-once。「超时≠失败」逼出**`mutating` 列**：恢复扫描
无法证明超时 effect 的副作用没发生，把 mutating 工具回 ready 等于
重放副作用，一列数据统一分流，免掉 per-tool 恢复代码。「判断有成本」
逼出**`consumes/produces`**：`WHERE X = ANY(consumes)` 是免费的算术，
Jev 终选是昂贵的语义，先用便宜的把贵的喂小。「执法者现成」逼出
**只读角色 + `allowlist` 数据化**：模型 SQL 永远跑在 `default_transaction_read_only`
之下，写得再花也写不进库——收紧授权是 `UPDATE`，审计是 `SELECT`。

**反事实。** 把注册搬回代码：T0 运维上线新工具，改了派发器的注册代码，
漏改判断摘要的拼装；T0+ε 新工具可执行但不可见，claim 领得到活、判断
平面永远选不中，任务在候选集外无限等待；T0+1h 滚动升级到一半，旧
worker 领到不认识的 handler，超时循环烧完 `max_attempts`，effect 沉进
unknown——没有一次是「写错代码」，全是缺一个原子提交点的必然产物。
再把只读执法换成文本黑名单：T0 判断平面生成
`COPY tools FROM '/etc/passwd'`；T0+0.1s 校验器扫描字符串，黑名单
里有 DROP/DELETE/UPDATE、没有 COPY，放行；T0+0.2s SQL 在可写角色
下执行，模型写库成功；反方向同样失败——合法字面量 `'set'` 被误拦。
**扫描必然误伤字面量、绕过手段无穷**；只读角色下 COPY 直接报错。

**被拒替代。** **装饰器/插件类注册**：新增工具要同步改摘要、派发、校验
三处，没有事务边界与约束兜底，一致性只能靠人肉。**LRU 热载插件**：
可见性变更不经过 commit 边界，worker 先看见、判断平面还看不见，可见性
分裂；崩溃后缓存清零，重启后可见集不确定。**每工具微服务**：用第二个
系统重新发明这张表，预筛从 index scan 变成跨网络调用，更贵。一张表最便宜。
