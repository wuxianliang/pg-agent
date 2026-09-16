# s32c-completion-evidence — §3.2 后段:complete_effect、证据分类、recovery 接管

> **抽取范围**:`docs/designs/v8-dev.md` 第 601–696 行(逐行通读)。本区间实际内容为:
> 1. `effect_audit` 主表 DDL 注释块后半(601–676):三列联合 CHECK(Q05)、内部行效应归属 CHECK(L4-R04)、复合 FK 不采用注记(F8/L4-FINAL-08)、唯一键 NULLS NOT DISTINCT 后分支语义、归属列四列联合 CHECK(P03)、`audit_key_kind` 三值、`received_result_raw`/`result_fingerprint`/`raw_invalid_class`/`binding_invalid_class`/`result_parse_path` 列语义、数据库级等价关系(三条)+ binding 侧分流等价(两条)、去重语义、并发插入幂等;
> 2. `effect_audit_binding_occurrences` 子表完整 DDL(677–686);
> 3. `effect_audit_result_occurrences` 子表 DDL(687–692);
> 4. 第 695 行超长冻结段:binding occurrences 唯一存储合同、N06 统一递归脱敏、三载体同源脱敏、`received_binding_raw` 证据存储、归属键与不可归属形态、**双判据独立分流**(键判据 J06 三分支 + 值判据)、类型化去重列与十列唯一约束、result 指纹入键的去重域、response-loss retry、**(2) 语义层**(DECISION_PLAN_INVALID,X02+Y02 适用时序限定);
> 5. 第 693–694 行:代码块收尾。
>
> **注**:任务标题中的「recovery 接管」内容**不在本区间**(应位于 696 行之后,由后续行号区间的 digest 覆盖)。本区间不涉及 recovery。
>
> 邻接上下文(585–596 行,用于补全 601 行所延续的约束块):`effect_audit` 的 CREATE 于 592 行以 `)` 收尾,末尾五列为 `internal_op_kind`、`parent_command_id`、`internal_op_ordinal`、`audit_key_kind`、`audit_key_value`;593 行为十列唯一约束;594–596 行为列级约束开头(`audit_key_kind`/`audit_key_value`/`result_fingerprint`/`result_parse_path`/`reason` NOT NULL、`internal_op_kind` 五值 CHECK)。主表列清单前半(约 570–592)归前段 digest。

---

## 1. 数据库表(完整清单)

### 1.1 `effect_audit`(completion 审计主表)— [LATER](结构层拒绝证据基础设施;P0B 最小闭环为成功路径 + receipt/binding 幂等,不写本表)

**规格仅部分给出**:CREATE TABLE 起于本区间之前(约 570–592 行,列清单前半见前段 digest);本区间(601–676 + 邻接 593–596)给出其全部约束与注释后半。

**本区间明确点名的列**(列名 + 类型/约束,凡规格给出处逐字):

| 列 | 类型/约束(规格原文) |
|---|---|
| `session_id` / `step_id` / `effect_id` / `attempt_no` | expected 归属四列,可 NULL;可归属行四列均非 NULL、不可归属行四列统一 NULL(四列联合 CHECK 强制,见下) |
| `audit_context_session_id` | 非空列;「不可归属分支的授权归属落库列」,来自已授权命令调用上下文的 session,**MUST NOT 取自 received binding 的任何不可信字段**;并进入审计去重键——同授权上下文同键收敛一条、不同授权上下文同输入各自留存(RLS 下天然隔离);内部子操作行上 = 该子操作的 `parent_session_id`(该等值保持受保护写函数校验) |
| `result_hash` | 可 NULL;由值判据独立决定(完整 received result 可通过 §1.3 canonical profile → canonical 值;不可规范化 → MUST 为 NULL) |
| `result_fingerprint` | NOT NULL(本列无 NULL 分支);合法 result 分支 = canonical result_hash 值同值复用;result malformed 分支 = `received_result_fingerprint@v2` 键值;无 received result 字节按空字节序列计算 |
| `result_parse_path` | NOT NULL CHECK (result_parse_path IN ('complete','raw_invalid','empty'))——三值闭合集 |
| `raw_invalid_class` | 列级 CHECK (raw_invalid_class IN ('TRUNCATED','CORRUPT_BYTES','UNBOUNDED_KEY'))——闭合三值 |
| `binding_invalid_class` | 列级 CHECK (binding_invalid_class IN ('TRUNCATED','CORRUPT_BYTES','UNBOUNDED_KEY'))——闭合三值;binding 侧不另立 binding_parse_path 列(路径区分由 audit_key_kind 第三值 invalid_binding 承载) |
| `reason` | NOT NULL(invalid_binding 路径「reason 标注对应类别」;入唯一键) |
| `received_binding_raw` | bytea;合法/malformed 分支 = received binding 段**脱敏后字节全集**的不可变证据存储(同事务写入、永不改写、一律写入,MUST NOT 作为 fingerprint 输入);invalid_binding 分支 = 仅 64 字节摘要字节 |
| `received_result_raw` | bytea 不可变证据、此后永不改写;完整解析路径为脱敏后字节全集,损坏路径为 `raw_invalid_digest@v1` 摘要字节(与该路径 RAW_INVALID 单 occurrence 同字节);'empty' 形态恒为零长度 bytea、非 NULL |
| `received_*` 标量列 | 解析后的 received 标量列仅用于查询/展示,同样 MUST NOT 作为 fingerprint 输入(§1.3 输入可获得性);malformed 分支「无法落入标量列的值按其原始字节原样保存于对应 received 字段」(不规范化、不丢弃) |
| `internal_op_kind` | 可 NULL CHECK (internal_op_kind IN ('failure_drain','shared_cancel_closure','compact_terminal_abort','infra_closure','generation_revocation_drain'))——五值闭合集(§3.1.2 统一内部子操作审计合同) |
| `parent_command_id` | NULL=普通 completion 路径审计行;内部子操作行 MUST 非 NULL(= 触发该子操作的父命令 command_id) |
| `internal_op_ordinal` | 父命令事务内 ordinal(同 §3.1.2 分配规则、不可变);MUST 非 NULL 且 >= 0(与 (op 类别, 目标 identity) 经分配规则一一对应) |
| `audit_key_kind` | NOT NULL CHECK (audit_key_kind IN ('canonical_binding','malformed_binding','invalid_binding'))——闭合集三值,独立于 §3.1.2 receipt 键类型命名空间 |
| `audit_key_value` | NOT NULL |

**约束(逐字引用规格)**:

(a) **Q05 三列全有全无 CHECK**(数据库级第一道,受保护写函数校验为第二道):
```sql
CHECK ((internal_op_kind IS NULL AND parent_command_id IS NULL AND internal_op_ordinal IS NULL)
    OR (internal_op_kind IS NOT NULL AND parent_command_id IS NOT NULL
        AND internal_op_ordinal IS NOT NULL AND internal_op_ordinal >= 0))
```
一切部分 NULL 形态(仅 kind 非 NULL、kind+parent 非 NULL 而 ordinal NULL、kind+ordinal 非 NULL 而 parent NULL、parent/ordinal 单侧非 NULL 等)均被数据库级拒绝。

(b) **L4-R04 内部行效应归属联合 CHECK**(与 Q05 独立各自成立、联合蕴含内部行七列全非 NULL):
```sql
CHECK (internal_op_kind IS NULL OR (parent_command_id IS NOT NULL
    AND internal_op_ordinal IS NOT NULL AND session_id IS NOT NULL
    AND step_id IS NOT NULL AND effect_id IS NOT NULL AND attempt_no IS NOT NULL))
```
effect 域内部子操作行 MUST 有效应归属;`internal_op_kind` 非 NULL 而归属四列任一 NULL 的行被数据库级拒绝——**无 effect 归属的 session 级内部操作(如 `compact_terminal_abort`,目标为 compaction)由此构造上不可写入本表、仅入 `internal_op_audits`**(§3.1.2 两键作用域互斥的分表语义数据库级闭合)。

(c) **P03 归属列四列联合 CHECK**(取代旧「仅 effect_id/attempt_no 两列 CHECK」;受保护审计写入函数双重强制保持——函数层四列一致校验为第二道,两道各自独立成立):
```sql
CHECK ((session_id IS NULL AND step_id IS NULL AND effect_id IS NULL AND attempt_no IS NULL)
    OR (session_id IS NOT NULL AND step_id IS NOT NULL
        AND effect_id IS NOT NULL AND attempt_no IS NOT NULL))
```
一切部分归属形态(仅 session_id 有值、session_id+step_id 有值而 effect_id/attempt_no NULL、effect_id 与 attempt_no 单侧 NULL 等)均被数据库级拒绝。

(d) **十列唯一约束**(数据库级强制,依赖 PG ≥ 15;NULLS NOT DISTINCT 覆盖 expected 侧不可归属(effect_id/attempt_no 为空)的 audit 行):
```sql
UNIQUE NULLS NOT DISTINCT (audit_context_session_id, effect_id, attempt_no,
    audit_key_kind, audit_key_value, result_fingerprint, reason,
    internal_op_kind, parent_command_id, internal_op_ordinal)
```
入唯一键后分支(NULLS NOT DISTINCT):普通路径三列 NULL×NULL 保持既有合并(幂等);内部子操作行——异类(internal_op_kind 互异)/不同父命令(parent_command_id 互异)/不同 ordinal 互异**不合并**;同父同 ordinal 合并(= 同 op+同目标重触发:ordinal 由 §3.1.2 分配规则与 (op 类别, 目标 identity) 一一对应,同父同 ordinal 即同 op 同目标,合并为该子操作幂等——与幂等键 `(parent_command_id, op, 目标)` 合同对齐)。

(e) **复合 FK 不采用注记(F8/L4-FINAL-08,设计选择而非可行性结论)**:
- `audit_context_session_id` 与父命令 session 的等值(= `parent_session_id`)保持**受保护写函数校验**(函数层唯一校验路径);
- `command_receipts` 无 `(session_id, command_id)` 二列唯一约束可作引用目标(其唯一键为含类型化键对的四列——同一 command_id 合法持多行 receipt:首次执行 receipt 与后续 IDEMPOTENCY_CONFLICT 冲突拒绝 receipt);
- 以 `command_bindings(session_id, command_id)` 为目标同样选择函数层校验、不采用 FK。设计理由:binding 为首占控制行,审计归属一致性不应耦合控制行的首占/销毁生命周期(binding 行由父命令事务末段写入(如 §3.3 七步定位序步骤 (7))、而内部子操作 audit 行按五类全序执行序先行写入的插入序时序差异,可经 DEFERRABLE 外键等机制处理、非技术不可能——不采用是生命周期/耦合层面的设计选择,旧「非 DEFERRABLE 外键在插入序上必然失败」的不可行结论(仅由插入顺序推出)已删除)。

(f) **数据库级等价关系(部署必备)**——以**延迟约束触发器或受保护审计写入函数**强制,作用于同一事务提交时的最终行集状态(主表行与 result 子表行同事务插入的中间态不作判定);跨主表与 result 子表,逐形态拆分为三条独立等价:
```
result_parse_path='raw_invalid' ⇔ raw_invalid_class IS NOT NULL
    ∧ effect_audit_result_occurrences 总行数=1 ∧ 唯一行 type_tag='RAW'
result_parse_path='complete' ⇔ raw_invalid_class IS NULL
    ∧ effect_audit_result_occurrences 无任何 type_tag='RAW' 行
    ∧ 全部行 type_tag 仅五值域 {TEXT,NUMBER,BOOLEAN,JSON,NULL}
    ∧ 存在 received result 字节(received_result_raw 非零长度;零 occurrence 形态合法
       ——完整解析路径无可定位字段(如空对象)时 occurrences 为空序列,§1.3)
result_parse_path='empty' ⇔ raw_invalid_class IS NULL
    ∧ effect_audit_result_occurrences 总行数=0
    ∧ 无 received result 字节(received_result_raw 恒为零长度 bytea、非 NULL
       ——与 fingerprint 空字节序列输入同款表示)
```
零 occurrence 形态判别(complete × empty 不相交的闭合依据):两形态同为 class NULL ∧ 总行数=0,occurrences 不单独承载判别——判别维度是 received result 字节存在性(empty 无 result 字节;complete 零行形态有脱敏后 result 字节全集);三条等价各自强制其完整合取条件,联合可满足且两两无交集。

(g) **binding 侧分流等价(同款延迟约束触发器或受保护审计写入函数强制,J06)**:
```
audit_key_kind='invalid_binding' ⇔ binding_invalid_class IS NOT NULL
    ∧ effect_audit_binding_occurrences 总行数=0
    ∧ received_binding_raw 为 64 字节摘要(raw_invalid_digest@v1 键值字节)
audit_key_kind IN ('canonical_binding','malformed_binding') ⇔ binding_invalid_class IS NULL
    ∧ effect_audit_binding_occurrences 总行数 ≥ 10(十字段固定槽位含合成占位恒齐备)
```
两分支经行数与类别列判别、两两无交集。

(h) **条件填充列语义**:
- `raw_invalid_class`:损坏路径 audit 行 MUST 非 NULL(按 §1.3 有序类别判定唯一填写:截断→TRUNCATED、非法字节/损坏重复字段→CORRUPT_BYTES、无法定界值(含 null/非字符串 idempotency_key occurrence、非对象顶层)→UNBOUNDED_KEY);完整解析路径与无 received result 字节的行 MUST 为 NULL(与 result_parse_path 的等价关系由 (f) 强制);
- `binding_invalid_class`:不可定界 binding 行(audit_key_kind='invalid_binding')MUST 非 NULL(按有序类别判定唯一填写:值/字符串截断→TRUNCATED、重复字段中值损坏→CORRUPT_BYTES、无法定界值(含 idempotency_key 原值无法定界、idempotency_key 值为非字符串——null/对象/数组/数字/布尔,**任何解码后同名成员、顶层或嵌套容器内任一层级**(统一递归脱敏域),无法按冻结规则脱敏即无法定界)→UNBOUNDED_KEY);可完整抽取行(canonical_binding/malformed_binding——含顶层字符串敏感值正常脱敏形态)MUST 为 NULL。

(i) **不可变性保护**:受保护审计写入函数为写路径(数据库 CHECK 之外的函数层第二道强制);`received_result_raw`「bytea 不可变证据、此后永不改写」;`received_binding_raw`「同事务写入、永不改写」。

### 1.2 `effect_audit_binding_occurrences`(received binding occurrences 的唯一存储;独立子表,R-02/R-02-R1 冻结)— [LATER]

**规格给出完整 DDL**(677–686 行):
```sql
effect_audit_binding_occurrences(
  audit_id,                           -- FK → effect_audit(audit_id),与所属 audit 行同事务插入
  occurrence_no,                      -- 规范序槽位;CHECK (occurrence_no >= 0)
  field_name_raw bytea NOT NULL,
  type_tag NOT NULL,                  -- CHECK (type_tag IN ('TEXT','NUMBER','BOOLEAN','JSON','NULL'))
  value_raw bytea NOT NULL
)
PRIMARY KEY (audit_id, occurrence_no)
```
逐项语义(逐字要点):
- `occurrence_no`:固定排序键,分配规则冻结为 §1.3 两段编码序——固定十字段在前(缺失已知字段为固定合成占位行),未知字段按解码名分组序在后(组间解码名 UTF-8 字节序、组内出现序——§1.3 组级排序键);无已知字段重复时十字段即 0–9、未知字段自 10 起;单调递增;合法域 ≥ 0;
- `field_name_raw`:字段名原始字节 = 去引号键名词法切片(不含引号、转义按线缆原样;含 NUL/非 UTF-8 等一切原始形态;成员名匹配域 = 解码后成员名);
- `type_tag`:五值闭合集(binding 子表专属值域,**禁 RAW**;与 result 子表六值 CHECK 分别约束、不共享;数据库级强制——插入 type_tag='RAW' 即被列级 CHECK 拒绝);
- `value_raw`:值原始字节;NULL 值以零长度字节表示(列本身 NOT NULL);
- `PRIMARY KEY (audit_id, occurrence_no)`:两列隐含 NOT NULL+唯一;**fingerprint 重放唯一合法读取序 = occurrence_no 升序**;
- 已提交行不可变(数据库级强制:触发器或等效约束拒绝一切 UPDATE;DELETE 仅随所属 effect_audit 行按统一数据销毁策略级联);主表不设 occurrences 单列——子表行全集即 occurrence 记录(§1.3 重放合同);
- 固定合成占位行:`field_name_raw`=该字段名字节、`type_tag`=`NULL`、`value_raw` 零长度——与 plain 拼写显式 null 逐字节相同;escaped 拼写显式 null 的词法切片互异 → fingerprint 互异;
- idempotency key 字段的 occurrence 值为脱敏 hash 字节、类型标签 TEXT;其余标量字段一律按收到原始字节;容器值(JSON 类型 occurrence)例外——为递归脱敏后子树字节(统一递归脱敏域 N06:嵌套同名成员已脱敏、无原值);
- received binding 合法与可完整抽取的 malformed 分支一律写入——不可定界 binding 走 invalid_binding 摘要拒绝路径、**本子表零行**(J06);
- 解析是实现内部动作,MUST NOT 要求跨实现重解析一致。

### 1.3 `effect_audit_result_occurrences`(received result occurrences 的唯一存储;与 binding 子表对应的 result 侧子表)— [LATER]

**规格给出紧凑 DDL**(687–690 行,列清单逐字):
```sql
effect_audit_result_occurrences(
  audit_id, occurrence_no, field_name_raw bytea NOT NULL, type_tag NOT NULL, value_raw bytea NOT NULL
)
PRIMARY KEY (audit_id, occurrence_no)
```
注释(逐字要点):result 子表:audit_id FK、occurrence_no ≥ 0、type_tag NOT NULL+**六值 CHECK**(result 侧专属值域,**含 RAW**:TEXT/NUMBER/BOOLEAN/JSON/NULL/RAW)、bytea NOT NULL(NULL 值零长度)、行不可变、升序重放。两子表 CHECK 分别约束(冻结)。
**RAW 标签专属**:`type_tag='RAW'` 仅由 result 侧损坏路径的 RAW_INVALID 单 occurrence 产生(§1.3 R-04 严格两径);binding 侧抽取语义不变、永不写入 RAW。

---

## 2. 命令与流程

### 2.1 complete_effect 第 (2) 层:语义层 — [P0B-CORE](入口限定与检查本体在成功路径必经;DECISION_PLAN_INVALID 收束分支为 [LATER])

- **前置**:结构层全部通过后,对**已认证 decision result** 的语义一致性检查(§3.1.2 初始 decision seal 的 **decision 标记/plan 双向互斥穷尽检查**)。
- **适用时序限定(冻结,X02+Y02 收窄)**——语义层入口唯一为**已进入终局结算的成功 decision result**:
  1. 流式适用域内仅字段矩阵形态 (i)(`stream_complete=true` ∧ 计数合法——完整流、终局结算路径;矩阵 (ii)/(v) 形态已 schema reject、不达本层);
  2. 非流式为 `known_success`(既有——**唯一证据分类函数输出**);
  3. **(iii)/(iv) pending observation(`stream_complete=false` 非终局 stream observation)MUST NOT 进入语义层**——与五款状态门及 observation 零控制态合同互斥:pending 流的 tools plan 标记组可能不完整(中间事实不保证 plan 终版),语义层互斥检查在该输入上无定义域——其 payload 不触发 `DECISION_PLAN_INVALID` 检查与既有 INFRA 收束(仍按 observation 分流、五款状态门唯一裁定——§3.2.2 四步后分流第 (1) 分支);
  4. 四步序第 (iv) 步(非 `known_success`——取消/失败/unknown 按证据收束)的 result **不进入语义层**:失败/取消/unknown result 不携带待互斥校验的 tools plan 标记组,语义层入口以成功分类为前置、MUST NOT 对非成功 result 套用标记组合检查。
- **拒绝路径([LATER])**:非法按 `DECISION_PLAN_INVALID` 拒绝并触发既有 INFRA 收束(§3.1.2 拒绝规则的受控例外——同事务写收束控制态:effect `failed_terminal`、step/session 按 §3.1.1 `fail_session` 第 (3) 类 INFRA 路径收束;session 已有持久化 failure cause(`WORKSPACE_LOST` 或既有 INFRA code)时父层 code 保持既有 cause、step 按既有 drain 三分支收束,该 effect 的 INFRA code 只落 effect/audit 层(§3.1.2 父层 code 优先级限定);「零控制态修改」仅适用于结构层失败,MUST NOT 据此豁免或吞并语义层收束)。

### 2.2 已接受结果的 response-loss retry — [P0B-CORE](命令幂等)

已接受结果的 response-loss retry **只返回原 receipt,不重复追加结果事件**。

### 2.3 结构层拒绝路径的审计写入 — [LATER]

- 结构层拒绝路径**仅写 receipt 与 `effect_audit`、零控制态修改**(含跨 result 分支组合:一次合法 result(canonical hash)与一次 malformed result(原始字节指纹)对同 binding 的指纹值与输入形态互异,同样各自留存)。
- **去重语义(冻结)**:同 binding(`audit_key_kind`/`audit_key_value` 相同)+ 同 result(`result_fingerprint` 相同)→ 幂等返回同一 audit 行;同 binding + 不同 result(指纹不同)→ 各自留存为独立 audit 行,MUST NOT 覆盖、MUST NOT 静默丢弃 raw evidence——`received_result_raw` 照常保存于各自行。
- **并发插入**命中唯一约束(同 `(audit_context_session_id, effect_id, attempt_no, audit_key_kind, audit_key_value, result_fingerprint, reason, internal_op_kind, parent_command_id, internal_op_ordinal)` 已存在)时 MUST 幂等返回已有 audit 行、MUST NOT 产生第二条记录(幂等返回时不插入第二组 occurrence 行,子表与主表同事务判定)。
- **不可归属输入按授权上下文收敛**:同一授权上下文收到相同不可归属输入的并发/重发收敛为一条,不同授权上下文收到相同输入各自留存、MUST NOT 返回对方上下文的 audit(RLS 租户隔离下天然不可见)。
- 同一 malformed completion 重发按其 malformed 键**与 result 指纹**幂等去重为一条 audit;同原文重发同 digest 幂等收敛、不同原文不同 digest 各自留存。
- MUST NOT 通过修正或规范化原始输入获得 canonical 键(原始 received 字节按收到原样进入 fingerprint,结构性分离与 §1.3 rejection fingerprint 同源);两种键域下均不得只依赖 `result_hash + reason`。

### 2.4 result/binding 接收时一次性抽取(同事务落库)— [LATER]

- 解析与脱敏在接收时一次性完成并同事务落库(与所属 effect_audit 行原子提交);result 侧「本分支接收时一次性抽取并同事务落库」。
- **三载体 MUST 源自同一接收时脱敏结果**:同一次接收按同一冻结规则一次性脱敏后分别落为标量列、raw 与 occurrences,不存在载体间脱敏时机或规则不一致的窗口(result 侧 `received_result_raw` 与 `effect_audit_result_occurrences` 子表、`received_result_fingerprint@v2` 同样源自同一接收时 result 侧一次性抽取结果)。
- 未脱敏取证材料(含 result 侧损坏路径完整原报文——audit 仅存 `raw_invalid_digest@v1` 摘要与 `raw_invalid_class` 类别,原文不落任何审计载体)MAY 另设受限 ingress 存储(operator 级访问控制;不属于三载体、不参与 fingerprint 计算与普通审计查询——**本合同不引入该必选机制**)。

---

## 3. 字节级算法

### 3.1 `raw_invalid_digest@v1` — [LATER]

- **用途(版本化键复用,两个侧共用同款算法)**:binding 侧不可定界 → `audit_key_value` 键值;result 侧损坏路径 → RAW_INVALID occurrence 的 `value_raw` 摘要字节、`received_result_raw` 的损坏路径字节、invalid_binding 分支 `received_binding_raw` 的 64 字节摘要字节。
- **公式(逐字)**:`SHA-256(完整原始字节) 小写十六进制`——binding 侧输入 = 完整 binding 原始字节;result 侧输入 = 完整原始 result 字节;输出摘要字节 = 「SHA-256(完整原始字节) 小写十六进制 UTF-8 64 字节」(即 64 字节小写 hex ASCII)。**原文不保存**(R-04-R1)。

### 3.2 `malformed_binding_fingerprint@v2` — [LATER]

- **输入**:对 `effect_audit_binding_occurrences` 子表行全集的逐 occurrence 编码(十字段固定序 + unknown_fields 段组级排序 × 每字段出现序);**输入覆盖完整 received binding 含全部未知字段**——自子表(按 `occurrence_no` 升序)逐 occurrence 编码生成(§1.3 输入可获得性)。
- **输出**:SHA-256 输出小写十六进制。
- **冻结限定**:编码格式与输入域**以 §1.3 正式定义为准,本节 MUST NOT 复述或另建第二套编码规则**;`effect_audit` MUST 能自该子表按 `occurrence_no` 升序重放生成字节级完全相同的 fingerprint。
- **版本注记**:`malformed_binding_fingerprint@v1` 仅存在于本合同历史草案、从未实现/部署——**首次落盘即 @v2,无迁移条款**。

### 3.3 `received_result_fingerprint@v2` — [LATER]

- **值(§1.3 严格两径)**:
  - 完整 ABI 解析成功 → 对 `effect_audit_result_occurrences` 子表逐 occurrence 按 `malformed_binding_fingerprint@v2` **同款编码格式**编码+脱敏;
  - 任何层级解析失败 → 单一 RAW_INVALID occurrence(`value_raw`=digest 字节)按同款编码;
  - 无 received result 字节 → 零 occurrence 序列(**空字节序列**)计算指纹。
- RAW_INVALID occurrence 定型(逐字):固定字段名 `"__raw_invalid__"`、type_tag `RAW`、value_raw=`raw_invalid_digest@v1` 摘要字节(SHA-256(完整原始字节) 小写十六进制 UTF-8 64 字节,原文不保存——R-04-R1)、`raw_invalid_class` 按序唯一填写、`result_parse_path` 按严格两径随行持久化。

### 3.4 canonical 审计键:`hash(canonical(received binding 元组))` — [LATER](canonical profile 本体为 P0B-CORE,定义在 §1.3 digest)

- 合法分支(可整体通过 §1.3 canonical profile,含 NFC 与类型约束):`audit_key_kind=canonical_binding`、`audit_key_value = hash(canonical(received binding 元组))`;canonical profile 作用于**完整 received binding 对象**、天然含全部未知字段——十个已知字段相同但未知字段不同的合法 binding 得到不同键值。
- 值判据 canonical result_hash:完整 received result 可通过 §1.3 canonical profile → `result_hash` 写 canonical 值(按 §1.3 canonical profile 对 received 结果重算的值),`result_fingerprint` 同值复用该 canonical `result_hash` 值(不另立第二套算法;binding malformed 时 `result_hash` 列按既有分支为 NULL、`result_fingerprint` 仍为该 canonical 值——本列恒非 NULL)。

### 3.5 idempotency_key 统一递归脱敏 hash(N06)— [LATER]

- 接收层在形成任何审计载体之前,MUST 按冻结规则(SHA-256,§1.3)将原始 idempotency key 原值替换为其 hash。
- **脱敏域 = 任何解码后成员名为 `idempotency_key` 的收到值(顶层与嵌套容器内一律)**:嵌套命中字符串 → hash 替换、所在容器字节为递归脱敏后子树;嵌套命中非字符串(null/对象/数组/数字/布尔)→ 整体 `invalid_binding` 摘要路径,不产生载体输入。
- **两层 replacement 公式(逐字)**:hash 输入 = 解码后 UTF-8 字节、occurrence 值 = **64 字节小写 hex ASCII 不含引号**、父容器按完整 JSON 字面域替换为带引号 hex 字面(`"`+hex+`"`,合法 JSON)重建——§1.3 脱敏规则两层 replacement 与递归脱敏、容器字节(嵌套与数组内命中先替换、再形成父容器字节)。
- 三个审计载体(`received_*` 标量列、`received_binding_raw`、`effect_audit_binding_occurrences` 子表)均 MUST NOT 含原始 key 原值(含嵌套容器内同名成员原值及其任何片段,无原值禁令绝对);expected/received 两侧 hash 必须可比较,以定位具体失配字段。result 侧载体(`received_result_raw`、`effect_audit_result_occurrences` 子表)同样 MUST NOT 含原始 key 原值:完整解析路径下 result 段任意层级的 `idempotency_key` occurrence 一律为脱敏 hash 字节,容器(对象/数组)`JSON` occurrence 的 `value_raw` 一律为递归脱敏后子树字节;任何 occurrence 的 `value_raw` 与 `received_result_raw` MUST NOT 含未脱敏原值子树或其任何片段(无条件禁令)。

---

## 4. 状态机

- **effect**:本区间唯一引用写入的终态为 **`failed_terminal`**(语义层 `DECISION_PLAN_INVALID` 触发既有 INFRA 收束,同事务写收束控制态:effect `failed_terminal`)。effect 完整状态集(含成功终态)定义在 §3.2 前段/§3.1,不在本区间。[failed_terminal 写入路径 LATER]
- **step/session**:语义层 INFRA 收束按 §3.1.1 `fail_session` 第 (3) 类 INFRA 路径;session 已有持久化 failure cause(`WORKSPACE_LOST` 或既有 INFRA code)时父层 code 保持既有 cause、step 按既有 drain 三分支收束(§3.1.2 父层 code 优先级限定)。[LATER]
- **`result_parse_path` 三值闭合集**(`complete`/`raw_invalid`/`empty`):状态判别即第 1.1(f) 三条数据库级等价;零 occurrence 形态下 complete × empty 由 received result 字节存在性判别。[LATER]
- **`audit_key_kind` 三值闭合集**(`canonical_binding`/`malformed_binding`/`invalid_binding`):分支由键判据(received binding 可规范化性与可抽取性)决定;三键域经 kind 闭合集恒可区分;binding 侧分流等价即第 1.1(g)。[LATER]
- **`raw_invalid_class`/`binding_invalid_class` 有序类别判定**(各闭合三值 TRUNCATED/CORRUPT_BYTES/UNBOUNDED_KEY,按序唯一填写,见 1.1(h))。[LATER]

---

## 5. P0B 相关性标注总表

**[P0B-CORE]**(依 P0B 最小闭环判定标准):
1. 语义层入口限定(X02+Y02):入口唯一为已进入终局结算的成功 decision result;非流式 = `known_success`(唯一证据分类函数输出——对应 P0B「成功证据分类」);流式仅矩阵形态 (i);pending observation 与非成功 result(取消/失败/unknown)MUST NOT 进入语义层。
2. 语义层检查本体:§3.1.2 初始 decision seal 的 decision 标记/plan 双向互斥穷尽检查——P0B 假 LLM decision 的成功完成路径必经此检查(合法决策放行;P0B 中只需对「空 tools plan + assistant message」形态正确通过)。
3. 已接受结果的 response-loss retry 只返回原 receipt、不重复追加结果事件(命令幂等)。
4. (交叉引用)canonical profile 本体(§1.3)为 P0B-CORE;本区间的 `hash(canonical(received binding 元组))`/canonical result_hash 为其在审计上的应用 [LATER]。

**[LATER]**(完整抽取如上第 1–4 节,后续里程碑要用):
1. `effect_audit` 主表全部 DDL 细节(列、十列 UNIQUE NULLS NOT DISTINCT、Q05/L4-R04/P03 三条联合 CHECK、列级 CHECK、条件填充、复合 FK 不采用注记)。
2. `effect_audit_binding_occurrences`/`effect_audit_result_occurrences` 两子表(DDL、五值/六值 type_tag CHECK、不可变触发器、occurrence_no 两段编码序、合成占位行)。
3. 四套字节算法:`raw_invalid_digest@v1`、`malformed_binding_fingerprint@v2`(含 @v1 从未部署/首次落盘即 @v2 无迁移条款)、`received_result_fingerprint@v2`、canonical 审计键。
4. N06 统一递归脱敏域与三载体同源脱敏合同、无原值禁令。
5. 数据库级等价关系三条 + binding 侧分流等价两条(延迟约束触发器或受保护审计写入函数)。
6. 双判据独立分流(键判据 J06 三分支 + 值判据)、类型化去重列、result 指纹入键的去重域、并发插入幂等、不可归属输入按授权上下文收敛。
7. `DECISION_PLAN_INVALID` 拒绝 + INFRA 收束(effect `failed_terminal`、fail_session 第 (3) 类、父层 code 优先级、drain 三分支、「零控制态修改」不豁免语义层收束)。
8. 结构层拒绝路径「仅写 receipt 与 effect_audit、零控制态修改」原则及受限 ingress 取证存储注记(MAY,非必选)。
9. 内部子操作三列(internal_op_kind 五值闭合集/parent_command_id/internal_op_ordinal)入键与幂等语义、§3.1.2 两键作用域互斥(本表承载 effect 域、`internal_op_audits` 三元组唯一索引承载其余域)。

---

## 交叉引用(本区间引用、定义在他处的概念)

§1.3(canonical profile、malformed_binding_fingerprint@v2 正式定义、严格两径、组级排序键、unknown_fields 段、输入可获得性、rejection fingerprint);§3.1.2(receipt/binding 键类型命名空间、初始 decision seal、内部子操作审计合同、五类全序、父层 code 优先级、拒绝规则);§3.1.1(fail_session 第 (3) 类 INFRA 路径、drain 三分支);§3.2.2(四步后分流第 (1) 分支、摘要拒绝路径、五款状态门、字段矩阵 (i)–(v));§3.3(七步定位序步骤 (7));`internal_op_audits`(另一审计表,承载无 effect 归属域)。
