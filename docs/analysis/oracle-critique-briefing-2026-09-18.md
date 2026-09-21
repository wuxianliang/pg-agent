# Oracle 批判简报：pg-agent 各版本保留/放弃评估（2026-09-18）

## 用户目标（原话意译）

「我在这个项目中用 Postgres 做 agent 底座测试了不同的想法。最终我要**最适合数据库的形式，而不是过度设计**。首先要做一个**相对简洁的设计**。请批判已有的版本：哪些应该保留，哪些应该放弃。」

评审立场：以「Postgres 作为 agent 底座时，数据库天然擅长什么、不擅长什么」为唯一准绳，判断每个版本/机制是**发挥数据库长处**还是**在数据库里硬造应用服务器的形状**。

## 版本清单（全部已实现，除注明外测试全绿）

| 版本 | 核心想法 | 状态 |
|---|---|---|
| v1 | 原始系统：CodeAct/RLM/POML，LLM HTTP 在 SQL 事务内（`agent_run` 同步循环） | 已弃用方向 |
| v2 | 数据分析入口 + workbench 工具=会话内 SQL 函数（TEMP VIEW 归属会话），plugin_*.sql 加载 + 工具注册表 | 绿 |
| v3 | **库内 PGMQ + 库外 worker**：`prepare_llm_request`→pgmq.send 立即返回 run_id；worker 调 LiteLLM；`apply_llm_response` 幂等（内容 hash）；visibility timeout 崩溃重放；DLQ；每 run 粘一条连接，TEMP KV 跨轮 | 绿 |
| v4 | 分层扩展六 stage：plugin taxonomy（COMMENT/注册表）、sticky workbench（v2 工具搬上 v3 粘连接）、queue kinds（embed/sql_heavy/human_inbox）、subagent fanout（PGMQ groups）、session durability（TEMP vs per-run schema 对比）、observability_budget（有界 step 元数据 + 预算强制） | 绿 202/202 |
| v5 | SQL slot 装配 + generate-then-retrieve：prompt taxonomy、recipe 组件、prompt pipeline、named tools、kernel freeze | 绿 125/125 |
| v6 | PG+DuckDB 临时工作台：白名单表有界快照→DuckDB 内存会话、可链式命名 view、PGMQ 元数据+库外执行；**钉死自定义 fork wheel** `duckdb==1.6.0.dev366+ga1f0ab1911` | 绿 W1–W9 |
| v6.1 | 代码/文件工作台方案（**仅计划**）：sitting_duck+duck_block_utils+tigerfs；结论=DuckDB 扩展 ABI 墙→推荐双平面 | 计划冻结 |
| v7 | Flock RAG on DuckDB：Phase 0 waived（未过），Phase 1 部分运行时，tachiom blocked，又一套自定义 wheel+四仓 provenance/evidence 机器 | 停滞 |
| v8 | **Postgres-native agent 大成**：冻结规范 T56（2026-09-14），24 gate 全绿，12k 行冻结 SQL，14 stage。细节见下 | 绿但未完结（P0C 真实 I/O 半边 blocked） |
| v9 | context_early：任务创建即投机构建 context pack，commit 精确标脏切片、增量刷新、gate 判新鲜度（fresh/sync_refresh/drift_delta） | 绿 W1–W9；与 v10 无实现关联 |
| v10 | 执行装配管道（ContextPipe 式 Plan/Bind/Optimize/Serialize）+ 装配与初始 decision seal 原子发布 + Bind 零外部工作 | **仅规范冻结，零代码** |
| v11 | TREE 会话 + Dream-RSI 离线 dreaming/回放/策略 CAS；叠在 v8 上 | **仅草稿，零代码** |
| DSH | deepseek-harness：独立 Node 仓，v8 P0C 的 pinned compat host | 外部仓 |

## v8 已建成的机制全清单（按 gate，全部有测试）

G1 canonical profile（JCS+SHA-256、跨语言 golden vectors）；G2 核心 DDL（sessions/steps/session_events/effect_requests/effect_attempts/batches/command_receipts/command_bindings/turn_end_slots/effect_audit + 不可变触发器 + 只追加）；G3 append_events 七步 + receipt/binding 判定序；G4 初始 decision seal 八步 + 双 fence + dispatch/complete_effect + STALE_JOB_FENCE；G5 P0B 闭环 + kill-at-every-boundary chaos + 幂等重放；G6 tools seal 第二路径 + 工具批次 + final_tools 终态化；G7a known_failure 结算 + retry cohort 分配；G7b recovery 接管（lease guard + fence CAS）；G7c repair 命令 + turn_end_closers 槽位链；G8a request_cancel 粘性 latch + 三窗口收束 + 两序竞态；G8b 共享取消收束五出口 + cancel-wins 矩阵 + AG01 四触发源；G9a 流式地基（stream_id/chunk/observation_ordinal + 计数 ABI）；G10 完整授权模型（slices/grants 六维 constraints/13 capability/RLS/锁序线性化/workspace_handles 五状态/fork）；G11 插件世代（specs/implementations/generations/members + 拓扑排序 + digest + 下线 drain）；G12 双实时授权门 + cohort 恒过；G13 P0C dsh-compat 合同面（十六行映射 + blocked 矩阵 + 报告器）；G16 字节级审计键五件（rejection/transport/malformed/received/raw_invalid + 递归脱敏 + occurrence 子表）；G17 compact 三命令（lock/finalize/abort + ×LLM effect 冲突矩阵）；G18 driver 切换 + quiescing 闭合 + fork 完整面；G19a 装配 manifest 五源 digest + seam 六检查点；G19b 收尾（唤醒层 wait_registrations、attempt/heartbeat、FORCE_JOB_TAKEOVER、reconcile_result…）。

未完结：P0C 真实 I/O 半边（blocked 于 pinned DSH host）；grant/世代等剩余 runtime 面。

## v8 的 18 条不可妥协不变量（原文压缩引用）

1. session_events 只追加、seq 连续单调唯一。2. 会话历史与控制态分离（sessions/steps/effect_requests/leases/世代是权威，非 projection）。3. 三类独立 fence，旧永不盖新。4. **外部 IO（LLM/工具/网络/宿主 handler）不得在数据库事务内执行**。5. 稳定 effect_id，重试复用 identity。6. 本地至多一次；外部副作用 exactly-once 取决于 provider。7. unknown 不盲目重放。8. NOTIFY/队列只是唤醒优化，扫描可恢复。9. assemble/fold/catalog/grant/policy 绑定 snapshot/cutoff/generation。10. 并行完成序不改语义。11. 授权失败封闭。12. 插件必须被数据库权限强制。13. step/effect 固定 generation/digest/contract。14. 规范是合同，compat 是参考。15. 同 driver_epoch 单 driver。16. workspace_id ≠ workspace_handle。17. 每次 seam/route/dispatch 同事务复验 grant。18. yield 前 checkpoint 或显式 workspace/lost。

## v10 增量（规范冻结、零代码）

不变量 19：执行装配（Plan/Bind/Optimize/Serialize）+ 初始 decision seal 原子同事务发布。不变量 20：Bind 零外部工作。范围：tools seal 不装配；emergent 限同 turn；不默认接 v9 pack；P0–P3 不重新分期；churn/八条论文 alert 延期。

## v11 增量（草稿、零代码）

不变量 21–31：TREE 会话（路径权威=leaf→root 的 parent_entry_id 链、双 ordinal、path_ordinal 不落库、单子节点约束）、批合法性 DB 强制、决策层只读重放探针、策略指针 CAS、节点世界=不可变 artifact+闭包、无损派生 DAG、episode 级揭示集、TREE 授权读边界；终局=Dream-RSI online→offline dreaming→redeploy 环。

## 请 Oracle 批判的问题

1. **逐版本裁决**：v1–v11 + v6.1 + DSH，每个给出 KEEP（核心想法进最终设计）/ DROP（连想法一起放弃）/ SALVAGE（想法保留但实现放弃，降级重做）及一句话理由。
2. **v8 机制级批判**：上表 G1–G19b 的机制里，哪些是「数据库真正的长处」（append-only 日志、事务性状态转移、CAS/幂等 receipt、声明式约束），哪些是**过度设计**——把应用服务器/编排器的形状硬塞进 SQL？请点名（例如：grant 模型 13 capability 六维 constraints？插件世代 digest 机器？driver epoch 切换？compact 三命令？字节级审计键五件？双 fence？turn_end_closers 槽位链？）。判断标准：删掉它，一个单租户、单 worker、诚实崩溃恢复的 agent 底座会不会真的坏？
3. **最小保留集**：如果明天重写一个「简洁版」，只许保留 5–8 个核心机制，你保留什么？给出一张目标 schema/协议草图（表 + 循环 + 崩溃恢复故事），并说明它靠什么抗拒哪些真实故障（worker 半路死、重复投递、外部副作用未知）。
4. **反方向检查**：简洁版会失去 v8 的什么真实保障？哪些损失是可接受的（因为场景不需要），哪些是自杀式的（看似过度设计实则是数据库形态的核心价值）？
5. 最终给一个明确的「保留/放弃」两列清单（机制粒度），用户将据此写新设计。
