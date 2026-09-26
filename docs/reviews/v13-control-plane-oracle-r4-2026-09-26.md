# v13 控制面 Oracle R4 终裁：控制概念的表达形式（2026-09-26）

> 裁决日：2026-09-26。议题发起：用户对路线图「零新表 + 函数/事件/策略行混合」提出质疑——「直接把 RP-CE 与 LoopX 的概念建成投影表即可快速实现功能骨架」。
> 通道：四模型 Oracle 组（grokBuild grok-4.7-build-fast-xhigh / openCode grok-4.7 / codex gpt-5.6-sol@xhigh / openCode kimi-k3）。
> 全文：`prompt-exports/oracle-chat-2026-09-26-191841-new-chat-bcefde-5537.md`（gitignored）。
> 事实源（裁决时选区）：路线图 `docs/plans/v13-layered-control-roadmap-2026-09-26.md`、parity 裁决 `docs/reviews/v13-control-plane-parity-rpce-loopx-2026-09-26.md`、迁移报告、谱系文、R2、R3 链。
> 结果：**立场 A（路线图现行）四类全胜；「零新表零新列」默认维持，不打开闸门。**

## 0. 总裁决

B 案（概念直接建成概念形新表 / 物化视图 / 投影表）的最强读法已被审理：要的是 DDL 里看得见、可直接 SELECT、可先落骨架后补不变量的概念关系。该收益真实，但买来的是第二份权威。

- 概念按源系统命名，语义必须按 v13 的唯一真相与唯一推进纪律落地。
- 治理读面不物化；生命周期写面事件化；注册与资格分离；配额窗口重算。
- 物化视图、投影表、同事务概念缓存表与新表同禁（R4 扩写，防「物化视图不是表」绕过）。
- parity 分桶 13/29/29、Phase A→B→C、stage 序、D7/D10–D16 倾向均不变。

## 1. 逐类裁决（四模型一致）

| 类 | Verdict | 一句理由 |
|---|---|---|
| 治理读面（should-run / attention / quota 资格 / goal tree） | **A：STABLE 重算** | R2 §5/A21 已裁 `v_goal_tree` 是参数化 STABLE SRF「不是 VIEW、不是物化表」；should-run 的权威语义是「执行前必须再问一次」（迁移 §2.6），物化要么陈旧违约、要么成为 advance 锁图里的第二写者 |
| 生命周期写面（L32 停/复、F29 handoff、未来 pause） | **A：开放事件 + 唯一折叠函数** | 写面必须回答唯一写者 + 与 advance 的锁序 + 对 unknown 墙的崩溃语义（stage 19 为此付了 26 个断言）；事件是已裁唯一干预通道；`sessions.status` 闭集不扩 |
| 注册/资格（goal registry、spawn budget、capability） | **A：sessions PK + 全局策略行** | PK 即拒重复只覆盖身份唯一性（强于 LoopX 应用层 ValueError），资格/挂载归策略行；现在建 registry 表实现的是另一项产品 |
| 配额窗口 | **A：窗内重算 `turn/material_spent`，永不冲销** | 表禁令（迁移 §0/§3：quota_spends「语义证实，表冲突」）与事件族禁令（R3b-full:213 / R3c §8.7）是两道独立条文，俱在；LoopX 自己都禁可 UPDATE 的 `spent_slots` 计数器 |

## 2. 「零新表」默认的处置与例外闸门

默认原句维持：**零新表、零新列；策略行与开放事件不算新表；例外只经路线图 §4 改倾向之后。** R4 增列同禁：物化视图、概念状态表（goal/attention/scheduler/snapshot）、registry 表、配额账本表、RP-CE 快照表、同事务概念缓存表、「先建空表后补语义」。

未来任何新表提案的受理门槛（例外四问，须全答）：①唯一写者是谁；②与 advance 会话锁的锁序证明；③对 unknown 墙的崩溃语义；④证明「事件 + STABLE 投影」机制上承载不了（唯一合法理由=投影无法满足的索引点查规模——今日不存在：spawn_budget 上限 8 非终态、深度 64 已封顶）。

## 3. B 案真实收益的补救（不建表）

| B 的收益 | 补救（R4 并入路线图） |
|---|---|
| `\dt` 骨架可见 | 概念形 STABLE 函数名即骨架：`\df v13_*` + 路线图 §2.4 公共读面表 + 各 stage README 映射 |
| BI/仪表盘一句 SELECT | 带参数函数 + GRANT EXECUTE 模式；禁无参数全局 VIEW（与 F17/R3 D4 冲突） |
| L32「最后一条事件赢」读法绕 | stage 29 交付 STABLE `v13_goal_lifecycle(sid)`（唯一折叠函数体；advance/recover/should_run 都调它，不散落多份查询；允许部分索引） |
| 先填后补语义的草图速度 | 判为反模式：空表无写者正是 `blocked_unknown` 枚举零生产者同类债（卷宗 A #19，D5 因此而存在）；parity「一模一样」含失败模式，先有形状后有不变量正是被判「改变/没实现」的缺口 |

## 4. 裁决升级的路线图决策

- **D8 已裁（倾向成立）**：goal registry = sessions PK（身份唯一性）+ 具名策略行（资格）+ events（账本）；不建表。per-goal 差异化挂载真出现则停，第一候选是策略表作用域键。
- **D9 已裁（倾向成立）**：窗口资格 = 策略行 × 窗内 `turn/material_spent` 重算；滑出即过期；窗内冲销不做；窗口时钟只用事件行已有时间列，没有就停工报事实。

D7、D10–D14、D16 仍为倾向，未裁；对应 stage 不开工。

## 5. 已落入路线图的修订（同日完成）

§0 R4 终裁段；§1 存储责任划分段；§2.2 L5/L6/L21/L26/L38 落点加 R4 边界句；新增 §2.4 公共读面（概念→函数目录）；§3 每期收尾架构审计 + Phase C 导语禁 VIEW/物化 + stage 29 增 `v13_goal_lifecycle`；§4 D8/D9 标已裁、D15 加唯一折叠函数纪律；§5 第 2 条扩同禁清单 + 例外四问。
