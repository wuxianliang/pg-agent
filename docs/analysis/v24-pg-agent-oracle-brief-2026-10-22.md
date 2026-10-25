# v24 pg-agent：Oracle 承重评审 brief

日期：2026-10-23。本文可独立评审；全部为 [规格]，v24 尚无实现或 gate 证据。

## 命题与细腰

v24 将 agent loop、六控制原语与 Cordis 生命周期收敛到唯一写入口 `advance(effect_id,outcome_v1)`。唯一事务提交资格、可信结果、领域状态、预算/pin 变化及有限后继；wrapper 只构造 admission outcome。写 command 在一次 advance 内创建并结算 command effect、request、receipt 和领域变化，不存在 ready-command 中间窗口。外部 IO 在事务外；claim 和 IO 结果也只能由 advance 接纳。poll/wait/resolve 只读。没有 CE/plugin 专属 claim、lease、恢复扫描或第二写口。

loop 的可 claim effect 只有 `model_call`、`tool_call` 和生命周期 host effect；spawn 是模型 outcome 内 DB-only intent，advance 原子建 child run、扣 quota、记录 spawn 身份并生成首个 model_call。恢复入口为 resolve + 未结算 effects。远端执行无法与 PG 原子；无可信事实时保留 unknown/debt，不承诺 exactly-once。

## 数据模型与约束

十表：`scopes,runs,effects,pins,episodes,fibers,slots,installs,events,requests`。scope 存 parent/root/path、realm route 与 close 屏障；run 存对话 epoch、registration generation、driving generation、预算及交互；effects 独占 kind/status/attempt/fence/lease/outcome、实际 `pin_id`、`resource_quiesced_at`；pin 绑定 slot/provider episode；episode 保留激活代身份；install 同行存 canonical manifest/requires/provides、digest 与 `owner_fiber_id/owner_episode_id` 复合 owner 边。

关键约束：`UNIQUE(run_id) WHERE kind='model_call' AND status IN ('ready','claimed')`，并行 tool_call 不受限；run pin 仅在 run terminal 且不存在引用它的 ready/claimed effect 或未静默 unknown 时释放。success/failure receipt 证明 IO 已返回；unknown 需 inspect 置 resource_quiesced_at。scope `closed_at` 前其所有 install 必须 disposed 且 prepare/release 责任清零；无 inspect 时停在 closing。每 realm/key 仅一未释放 slot；activation/run pin consumer XOR；每 fiber 一个 open episode；owner+dependency 清理图无环。install 状态为 preparing→installed|prepare_failed|prepare_unknown，只有 installed 可开 fiber；(scope,identity,version) 唯一且 manifest/artifact digest 不同则拒绝。无 turn/receipt/claim/queue/recovery 状态表。

## 六动词与关键交点

`start(scope,input,budget,key)` 写：解析并固化 run pin，创建 run 与 model_call。 `poll(run,cursor)` 读：不写游标。 `wait(run,registration_generation,epoch,event_seq,timeout)` 读：registration generation 与对话 epoch 分离。 `cancel(run,generation,key)` 写：seal run、撤 driving-generation 发布权，不改 claim fence。 `steer(run,generation,instruction,key)` 写：仅非 terminal run 可接受，递增对话 epoch/driving generation，不改配置 pin；terminal 返回 already_terminal。 `respond(run,interaction_id,response,generation,key)` 写：消费当前 interaction 并创建下一 model_call。

| 交点 | 两提交序合同 |
|---|---|
| start / retire | start pin 先则 withdraw 但等 pin 排空；retire 先则新 start 拒绝 |
| cancel / retire | 两序均先 seal/withdraw；claimed 或未静默 unknown 仍持 run pin，正常回执/inspect 静默后才释放 |
| cancel / IO outcome | cancel 先只撤发布代次；原 token 在被新 attempt 替代前可结算成本/事实，不得生成后继 |
| steer / retire | active steer 先用旧 pin 排空；retire 先后 active steer 可续原 pin；terminal steer 两序均拒 |
| tool batch / loop | 多个 tool_call 可并行 claim；G 串行接纳；所有 ordinal settled 且静默后才生成一个 model_call |
| install / activate | install preparing/失败/unknown 时 on 返回 install_not_ready；仅 prepare 成功转 installed 后可激活 |
| spawn / loop | spawn intent 与模型 outcome 一次事务建 child、扣 quota、首个 model_call；没有 spawn effect/外部调用 |
| owner dispose / child install | child install 先则 owner 清理可由 owner 两列找到并等待 inspect/release/dispose；owner 先则关闭 admission，child install 被拒 |

## 八个请专打的问题

1. **episode/pin。** 保留最小 episode；无 run 的 activation pin 仍挡 provider release，episode 区分反转前后代。可能错：activation pin 是否覆盖所有长活消费者，是否还需要复合配置快照？
2. **cancel×插件。** cancel 不卸共享 fiber；terminal 本身不释放 run pin，引用 IO 未静默则 retire 等待。可能错：child run/owner fiber 的排空是否需要更强父子取消规则？
3. **steer×epoch。** terminal steer 一律 already_terminal；active steer 改对话 epoch/generation，不改 provider pin。可能错：terminal 定义是否还需区分 completed 与 blocked_unknown？
4. **spawn 边界。** DB-only intent，不是 effect；child run 字段承载 spawn edge。可能错：模型 outcome 重放与同 spawn_key 异 digest 的冲突顺序是否完全可判定？
5. **锁序。** 所有写者 G 首锁，随后 request→scope→run→effect→install→fiber→episode→slot→pin→event，集合内稳定键排序。可能错：唯一键等待或动态 FK 闭包是否仍能造成锁序外等待？
6. **恢复。** 重启仅 resolve + 未结算 effects；prepare/IO/receipt 窗口据同一 effect 与 reservation 收敛。可能错：host 无 inspect 时资源永久 unknown 是可接受债务还是缺状态？
7. **native 反例。** 所有写由 advance；prepare、control、dispose 无第二 admission/claim。可能错：SECURITY DEFINER、触发器或宿主脚本是否仍构成隐藏写口？
8. **replay 权利。** replay_policy 为 no_replay/replay_safe/manual；unknown 不自动重放。可能错：同 provider idempotency token 是否仍可能重复计费或产生不同输出？

## 非目标与评审要求

不做任意 JS 闭包/事件总线、跨库/多主机事务、外部 exactly-once、取消即杀停、通用外部逆操作或父 run 自动卸载共享 fiber。CAS 与 PG 之间若无幂等 reservation/inspect，保留 unknown 并阻止 dispose。

## Oracle R2 处置

| P1 | 处置与落点 |
|---|---|
| 7 scope 关闭漏 install | 接受；`closed_at` 要求 scope 内全部 install disposed 且无 prepare/release obligation；无 inspect 保持 closing。主规格 §3.1.1、§3.2、§6.7、§8、G6。 |
| 8 install 缺 owner 边 | 接受方案 (a)；`installs.owner_fiber_id/owner_episode_id` 同 advance 写入并以复合 FK 固定；owner retire/dispose 等 child install 准备/释放/处置完成。主规格 §3.1.8、§3.2、§6.2、§6.6–6.7、§7.2。 |

## Oracle R1 处置

| P1 | 处置与落点 |
|---|---|
| 1 terminal steer 复用已释放 pin | 接受；terminal 一律 already_terminal；主规格 §4.6、§7、§B.3。 |
| 2 cancel 先释在途 pin | 接受；run terminal 且无引用的未结算/未静默 effect 才释；effects.pin_id/resource_quiesced_at；§3.1.3、§3.2、§4.5、§6.3、§7。 |
| 3 cancel 改 claim fence | 接受；只增 driving_generation，当前 token 可记事实/成本，fence 只在新 attempt 替代时增；§4.5、§5.3、附录 B.4。 |
| 4 spawn 外部 effect | 接受；移出 kind 闭集，成为模型 outcome 同 advance 的 DB-only intent；§3.1.3、§5.5、附录 A.1。 |
| 5 install preparing/激活闸门 | 接受；preparing/installed/prepare_failed/prepare_unknown，on 只认 installed；§3.1.8、§6.1–6.3、§8。 |
| 6 工具并行与唯一索引冲突 | 接受；唯一索引只限 ready/claimed model_call，tool_call 可并发，G 串行接纳并按 ordinal 屏障；§3.2、§5.4、Gate G2/G6。 |

请只找承重漏洞与反例，不要改写成另一套系统。

## Oracle R3 处置

| P1 | 处置与落点 |
|---|---|
| 9 owner 复合 FK 阻塞合法 off→on | 接受；`installs(owner_fiber_id,owner_episode_id)` 复合 FK 指向有 `UNIQUE(fiber_id,episode_id)` 的 `episodes` 不可变身份，不引用 `fibers.current_episode_id`。install admission 在 G 内另校验 owner 当前 episode 等于指定 episode 且 active；owner 关闭由对应历史 episode 下 child installs 全部 disposed 的屏障裁决。off 关闭 E1 并清空 current 后，历史 C→(F,E1) 外键仍成立，F 可切到 E2。主规格 §3.1.5、§3.1.8、§3.2、§6.2–6.3、§6.6–6.7、§7.2。 |

文本自检：dispose 与 owner retire 的 child 枚举均按固定 `(owner_fiber_id,owner_episode_id)` 历史键，不读 current 指针；清理偏序仍要求 child install 准备/释放/处置完成后才关 owner episode，且先关 child 再 dispose 对应 install；表数仍为十，仅调整复合 FK 目标与约束说明。

