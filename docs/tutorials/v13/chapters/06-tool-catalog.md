# 第 6 章：工具目录——目录是表，可见性是查询

> 前置：第 2、5 章。现行 schema：`v13/schema/v13_core.sql` 的 `tools` 表。
> 对照上游：`v2`（workbench 注册表）、`v5`（named tools）、`v6`（enqueue-only 工具）。
> 设计对照：`docs/designs/v13-context-on-pg.md` §6.8（iv）（spawn 档位）。

## 6.1 这一章要做什么

agent 能用什么工具？常规框架把工具写成代码注册（装饰器/插件类）——
工具有没有、给谁看，都住在代码里。v13 的裁决（v2 起，十二轮没变过）：

> **工具目录是表；工具可见性是查询。**

新增一个工具通常仍是目录行加已有 handler；但当前表只有六列
`name/description/kind/handler/param_spec/enabled`。`allowlist`、`interruptible`、
`consumes`、`produces`、`mutating` 等早期设计字段不在现行 schema；若新增工具要改变
函数内的 interruptible/worktree 名单，还需要独立 SQL/消费者变更。当前 Phase 2
不把目录行新增写成生产 worker 或 profile 消费已交付。

## 6.2 最小形态

```sql
-- 当前 public.tools 的实际六列形状；字段约束以已加载 schema 为准。
CREATE TABLE tools (
  name        text PRIMARY KEY,
  description text NOT NULL,
  kind        text NOT NULL CHECK (kind IN ('sql','tool','llm')),
  handler     text NOT NULL,
  param_spec  jsonb NOT NULL,
  enabled     boolean NOT NULL DEFAULT true
);
```

早期设计以 sql/effect 分两档；现行 kind 为 sql/tool/llm：

```text
kind='sql'    库内函数：零外部 IO；advance 同事务直接执行（第 5 章 ④），
              不进队列。默认只读——具名写允许名单（v13_tools_guard 源码闭集）例外
kind='tool' / 'llm' 外部工具或模型工作：走 effects 账本；不使用 kind='effect'
```

这个两档划分消灭了 v2→v6 之间反复出现的问题：
「为什么有的工具入队有的不入队」——因为它们本来就是两种东西。
分界是**有无外部 IO**，不是 SELECT vs INSERT——`sql` 档的全部效果就是
数据库自身状态（含允许名单内的库内写），崩溃即整笔回滚（§6.7 同一口径）。

新目录行的六列形状示例（不是新增 handler 的部署步骤）：

```sql
-- 教学示例：六列目录行。实际工具名与 param_spec 必须符合已加载 handler 契约。
INSERT INTO tools(name, description, kind, handler, param_spec, enabled)
VALUES ('example_lookup', 'Look up an item', 'tool', 'lookup',
        '{"type":"object","required":["query"]}'::jsonb, true);
-- 此行仅说明目录数据形状，不会创建 handler，也不会改变硬编码的
-- interruptible/worktree 名单或接通生产 worker。
```

## 6.3 逐段解释

- **`handler` 是现行六列中的开放文本**：新增 handler 名可描述目录行为，但当前
  claim 接口不接收 `p_handlers`，也没有本阶段交付的生产 worker parity；单队列分流
  仍是后续接线问题。
- **早期目录设计，不是当前契约**：`consumes/produces`、目录 `mutating`、
  `input_schema` 等字段曾用于描述候选预筛、恢复策略和参数校验；它们不在现行
  `tools` 表中，不能据此推导当前查询或恢复行为。当前 effect 的 unknown/worktree
  纪律由既有代码路径及其 metadata/artifact 机制决定。
- **profile/allowlist 不是现行 tools 列**：pi/duck 的路径或表白名单、
  interruptible 档位仍是早期设计意图；当前名单由 `v13_interruptible()` 等函数内
  逻辑决定，registry 的 `tool_profile` 只有数据且没有消费者。未来消费需独立 SQL
  与 worker 设计，不能用 `SELECT * FROM tools` 宣称已生效。
- **只读角色执法（v2 的教训）**：模型生成的 SQL 永远跑在
  `default_transaction_read_only` 的角色下——**让数据库自己执法**，
  而不是文本黑名单（v2 的黑名单连字符串里的 `'set'` 都误伤）。
  这是 v8 grant 帝国被砍后唯一保留的种子：保护数据库不受模型，不是租户互防。
  执法范围澄清：只读角色**只约束模型生成的 SQL 文本**，不约束 advance
  变更相分派的目录函数——后者为 `SECURITY DEFINER`（固定 `search_path`、
  owner=控制角色、`REVOKE PUBLIC`、`GRANT EXECUTE` 只给控制角色——模型
  角色无 EXECUTE）在 advance 已持父 FOR UPDATE 的事务内执行。外层调用链：
  执行者是 `v13_advance`（变更相，owner=控制角色的 SECURITY DEFINER 链）——
  普通 route 调用者经 advance 进入控制角色，不直接持这些具名函数的 EXECUTE。
  用 DEFINER
  的理由是**唯一写路径可执法**：INVOKER 下执行角色必须持 sessions
  INSERT，「该角色直接 INSERT sessions 被拒」就无法由数据库执法；
  DEFINER 收权后执行角色零表权，直写即拒（R2 修订复核裁决）。
- **具名写允许名单 = `v13_tools_guard` 源码闭集**：guard 默认仍拒 VOLATILE，
  例外只有核心函数闭集——`v13_fork`、`v13_spawn_subsession`、装配函数
  （第 10 章，实现时核对真名）。例外条件全满足才放行：`provolatile='v'`、
  签名 `(uuid,jsonb)→jsonb`、`SECURITY DEFINER`+固定 `search_path`+
  owner=控制角色（`REVOKE PUBLIC`+`GRANT EXECUTE` 只给控制角色，模型角色
  无 EXECUTE——执法理由同上「唯一写路径可执法」）、`prosrc` 不含 dblink/pg_net/
  COPY PROGRAM 等 IO 通道。扩员 = guard 源码改+设计修订+部署 gate 同发；
  `UPDATE tools` 扩员被拒，「有 write_targets 键即放行任意 VOLATILE」同样被拒。

## 6.4 硬性规定与 gate

```text
历史 G1/G6 验收意图（不是当前 v13 gate 或实现保证）：目录可见性、artifact 预筛、
输入 schema 校验与 mutating 驱动恢复曾作为目标。当前实现应以已加载 schema、现行
consumer 与独立 gate 为准；本章不声称上述早期断言仍由现有实现覆盖。

历史 G-sql-write-closed 设计断言（不是当前 gate 逐项实跑记录）：
✓ 具名闭集外 VOLATILE sql 工具 enable → 红
✓ write_targets 缺键而 VOLATILE → 红；prosrc 含 IO 通道（dblink/pg_net/COPY PROGRAM）→ 红
✓ UPDATE tools 扩 guard 名单被拒（扩员 = guard 源码+设计修订+部署 gate 同发）
```

## 6.5 检查点练习

这些是早期设计练习，不是可直接运行的现状练习。现状练习应先检查
`v13/schema/v13_core.sql` 中的 `tools` schema、已加载的 handler 和
`v13/registry/test_registry.py` 对 enabled/context 的覆盖；不得使用本节已移除的
`v_tool_catalog(p_handler)`、版本守卫或目录 mutating 机制。

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

**历史设计推导（非当前契约）。** 早期草案曾把目录行、fold_state、advance、claim
描述为共享数据驱动边界，并设想以 `mutating` 与 `consumes/produces` 驱动恢复和候选
预筛。这些字段及相应的 `v_tool_catalog`、input schema 与 allowlist 不属于现行六列
schema；不可据此声称当前运行时采用这些机制。当前注册 overlay 的工具快照也是当前值，
不是历史版本。有关 provider IO 与事务边界的通用约束仍应依各现行 handler/worker 契约判断。

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
