# v17 偏差台账 — SBCL worker

日期：2026-10-06（初始建立于 G3 提交时）。记录实现与计划
`docs/plans/v17-sbcl-worker-plan-2026-10-06.md` 的差异及理由，
按 D-17-N 编号，只追加不放任。

**状态约定**：`open` = 已立案未裁；`fixed` = 已修；`accepted` = 已裁定接受；
`noted` = 已记录只作说明。

---

## D-17-01 · 并发发布语义：计划写「单赢家」，实现为「advisory lock 串行、双赢」— `accepted`

计划 §5 G1 原文：「并发发布单赢家（两连接同事务竞 CAS）」。实现按
§3.1 的「seq 每 world 无洞」纪律走 `pg_advisory_xact_lock`：两个并发
publish 被串行化，都成功、seq=1/2 无洞。

**理由**：advisory lock 下不存在「CAS 竞争失败」，双赢是锁的必然结果，
语义比计划文本更强（无洞、无孤儿、无失败分支）。计划 §3.1 是设计权威，
§5 只是 gate 场景描述；以 §3.1 为准。gate 断言与 `v17/store/README.md`
如实记录该语义。

**残留动作**：冻结计划时把 §5 G1 行改为「advisory lock 串行、双赢」。
（初判 `open`，本轮改判 `accepted`；计划文本回改留待冻结轮处理。）

## D-17-02 · `lisp_revisions.seq` / `lisp_journal.seq` 用 bigint（计划写 int）— `accepted`

更宽、无害；`v17_publish_revision` 返回 bigint。零成本修正已在
`v17_store.sql`：54 与 journal 定义处。

## D-17-03 · jiti 的 `sb-ext:lock-package` 防线一度缺失（G2 三评审发现）— `fixed`

G2 实现曾丢第二层防御，被 `g2-review-2`（blocker）
「runtime intern 绕过无人兜底」与 `g2-review-1`（major）明确点出：
validate-form 是纯文本闸，`(intern "VALIDATE-FORM" ...)` 可在词法上
隐形化绕过。

**修复**：三个 src 文件末尾全部加
`(sb-ext:lock-package :v17-kernel/:v17-pgstore/:v17-worker)` 及同款
包（jev/llm/pgmq 各自的 trusted-base 说明注释），`+protected-package-names+`
加入 `"POSTMODERN" "CL-POSTGRES"`（G3 起 world 线程持连接后 form 可直发
裸 SQL，必须提前拦住）；world-suite 补
`package-lock-stops-runtime-intern-bypass` 反例断言。

## D-17-04 · publish/journal 事务纪律不在 pgstore API 层强制（G1 评审 blocker）— `fixed`

g1-review-2（blocker）：`publish-revision`/`publish-world-revision` 调
`%assert-explicit-transaction`，但 pgstore 的裸包装（旧版）走逐条
autocommit；最自然的调用序列恰好重开 jiti 式 uncertain 窗口。

**修复**：`%assert-explicit-transaction` 覆盖 publish-revision /
append-journal / publish-world-revision 三个入口；导出
`with-store-transaction`；G1 gate 增补「autocommit 直调 publish 被拒绝」
断言。同一评审的 major「`v17_append_journal` 零校验」也在 SQL 侧补齐
operation-start/finish 的 record.id/status 校验（见收尾说明）。

## D-17-05 · 计划没预见的 G2/G3 实现事实（如实记录，非偏差）— `noted`

- **崩溃无半截 revision 的 gate 未压到 publish 函数本身**：`crash-child.lisp`
  用裸 INSERT 绕开发布函数做 kill；「INSERT+CAS 两句在同事务原子回滚」
  由同事务两语句的结构性保证 + advisory lock 语义覆盖。字面场景已写
  明（README §Gate scenarios），未改用「删掉函数改裸 INSERT」的更强
  形式——因为裸 INSERT 已足以证明「提交前 kill 无残留」，而 publish 路径
  的原子性由 SQL 单函数语境直接给出。
- **`v17_list_revisions` 用固定名临时表 `_v17_ancestry`**：函数内
  DROP/CREATE ON COMMIT DROP；若 caller 会话已有同名 temp 表会被静默
  DROP。已在函数注释声明重入与 DROP 调用方 temp 表的约束；更冷僻命名可作后续加固，非正确性问题。
- **advisory lock 键为 `hashtext(world_id::text)`（int4）**：跨 world
  哈希碰撞只损性能不损正确性；锁粒度（publish/append_journal 同键串行化）
  与「同 world job 经 mailbox 序列化」的叠加关系写入 README。
- **`v17_list_revisions` 标 VOLATILE**：祖先链 walk 需物化临时表，
  CYCLE 子句 `cycle_path record[]` 伪类型不可入表、OUT 参数遮蔽列名
  两个坑已在实现中处理。
- **据 `hashtext` 的锁键**（继续上条）：`v17_store.sql:108`。

## D-17-06 · 计划 §5 G1/G2/G3 之外新增的断言（实现加固，超出计划）— `noted`

- G3 场景 8 jsonb canary、场景 9 跨语言混跑：计划 §5 G3 只列七场景；
  8/9 是对 §2.1 教训 3 与「worker 可多副本」的正面回归。
- `V17_FAKE_STATE`/state 文件的跨进程调用计数：解决「fork 出的 Lisp
  worker 无法用进程内 `fake.calls` 断言」的等价物。
- `llm.lisp` 的 `V17_FAKE_LLM_TEXT`：`llm_fn` 缺失语义（llm job 直接
  失败）与空转退出（daemon 模式）对齐 `run_until_idle` 的进程内循环。

## D-17-07 · a11 版本钉死方案（计划 §7.4 落地情况）

`v17_publish_revision` 从 `manifest->>'sbcl'` 取回写版本，缺失即 RAISE；
`pgstore:load-revision` 与（lisp-implementation-version）对比，不符抛
`revision-version-mismatch`。brew SBCL 版本浮动风险已按计划 §7.4 关闭。
gate 输出记录 `lisp-implementation-version`。**无偏差。**

---

## G4 追加（2026-10-07）

### D-17-08 · goal 门的位置与 jiti 语义差一步 — `accepted`

计划 §3.2 引 jiti 的验收合同时说「未过 goal 允许安全中间进展」。那对
**交互会话**成立（jiti 的 worker-main 只在非交互模式下把 goal 当退出条件）。
对 **job** 不成立：调用方点名要了能力，发布了没有它的 world 就是把失败
effect 当成成功交付。

实现把 goal 门放进 publish 钩子（拒绝 → attempt abort → 恢复 → job failed），
invariant 仍在内核 attempt 内。jiti 语义的「goal 只报告」在交互路径未被
改动。已在 G4 README 与 worldd 头注释记录。

### D-17-09 · `lisp:` 工具的 params 以 quote 传入 — `noted`

计划 §3.2 说「params 转成一个 alist 参数」。实现组装的形式是
`(<fn> '((:PARAM . "v")))`——alist 必须 quote，否则会被当函数调用形式求值
（关键字当操作符，SBCL 只报 `illegal function call`）。README 与代码注释
都写明了这一点。

### D-17-10 · 每 job 新包（而非每 world 稳定包）— `accepted`

最初按「每 world 一个稳定包名」实现（revision 里的 defun 需要可读回）。
实践中进程内复用 adapter 会引入跨 job 的残留状态，且稳定名并无必要：
导出文本不带包前缀，读进哪个包都行。改为每 job 新包
`V17-WORLD-<name>-<n>`，同时让「Lisp 状态不跨 job 携带」在设计上成立
（连进程内也不携带）。

