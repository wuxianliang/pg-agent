# v13 控制面偏差台账（2026-09-26）

编号从 P1 起。后裁优先于计划正文。实现差与「计划 vs R3*」冲突分列；冲突不是实现许可。

## 实现差

本期相对 R3 §1–§2、R3a §6、R3b §7 无未授权实现差。下列是安装期探针按已写死默认走完的事实，不是第三种写法。

| # | 事实 | 处置 |
|---|---|---|
| F1 | `artifacts.content_hash` 与 `produced_by` 均存在 | `produced_hashes` 走连接查询；不编译 manifest 链（活体 `sessions` 无 `context_active_artifact` 列，列缺失分支不会被装上） |
| F2 | `jsonb_matches_schema(schema json, instance jsonb)` 真名相符 | 用该签名；schema 参数 `::json` |
| F3 | R1/设计/ch07 无三注解键字面类型 | 用 R3b 默认：`harness_session_ref` 1..256 `[A-Za-z0-9_./:-]+`，`resume_token` 1..512，`partial` boolean |
| F4 | `v13/load.py` 不包外层事务 | stage 17 文件自带 `BEGIN`/`COMMIT` |
| F5 | 活体 `v13_requeue_stale` 含 `mgraph_consolidate` | 换体以 mgraph 加载态为底，不用 twophase 旧体 |
| F6 | 活体 advance ⑤ 不写 `turn_no` | closeout 禁止 `turn_no` 赋值，只把已提交值抄进 `spent` |
| F7 | `v13_effect_id` 含 `v13_cycle_no` | retry 在追加新 `turn/route` 之前 enqueue，身份才能重挂同一行；`turn/route` 在身份计算之后追加。落实 R3b「走现有重挂」，不是改裁 |
| F8 | stage 16 `v13_mgraph_assembly.sql` 已 `GRANT SELECT ON effects TO v13_recall` | stage 17 `REVOKE SELECT ON effects FROM v13_recall`，满足「recall 可读 `human/responded`、不能 `SELECT effects`」。不改 stage 16 文件字节 |

## 计划文档 vs R3*（后裁优先）

| # | 冲突 | 采用 |
|---|---|---|
| C1 | 计划 §3.2.8 / R3 §1：已有未消费 `cancel/requested` → replay 不二插 | R3b：不追加，但仍扫 ready→cancelled；终态才 `replay`，非终态返回 `accepted` |
| C2 | 计划 §3.2.9 / R3 §1：审批 human request 四键，含可选 `prompt` / `interaction_kind` | R3b：恰 `{schema_version:1, interaction_ref}` |
| C3 | 计划 §3.2.11 / R3 §1 C4：「request 无 ref 也拒」 | R3b 应用谓词：仅 `kind=human` 且 succeeded 且 request 含 `interaction_ref` 才跑 one-of。无 ref 的 `{reason}` human 照旧 succeeded，不写 `human/responded` |
| C4 | R3a：`v13_wake_is_satisfied_v1` 标 STABLE | R3b：必须 VOLATILE（`clock_timestamp`） |

## 受制裁例外

| # | 条目 | 理由 |
|---|---|---|
| X1 | `v13/mgraph_assembly/test_mgraph_assembly.py` 的 J3：`len(SQL_LOAD_ORDER) == 16` 改为 `>= 16`，文案改为 “at least 16 files”。仅此一行。`SQL_LOAD_ORDER[:15]` 字节冻结切片不动 | 控制器 2026-09-26 裁决。该断言是注册完整性快照，字面钉死 16 与「新 stage 只追加注册」冲突。`>= 16` 保底语义不变，前缀加载语义零改动。本轮唯一被允许触碰的 stage 1–16 文件 |
