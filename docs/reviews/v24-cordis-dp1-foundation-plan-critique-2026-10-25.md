# v24 Cordis DP1 foundation 计划：有界完整性与设计批评

## 评审口径

- 评审对象为磁盘最新 `docs/plans/v24-cordis-dp1-foundation-plan-2026-10-25.md`，SHA-256 为 `b1eeb3a168945b36ba7f48b75243c56ce37fa50775e93a557deaa91649c4cbe9`。行号均指这一版本。
- export 只采用 `/Users/wxl/Projects/pg-agent/prompt-exports/oracle-plan-2026-10-25-211543-cordis-deep-b98c76-b807.md` 的 `## Generated Plan` → `### Response` 内容（:114–420）；前面的 composed prompt 和 selected-file dump 不作为计划基线。
- 产品依据为 `docs/designs/cordis-plugin-system-2026-10-25.md`；实现对照为 `v24/load.py`、`v24/sql/**`、`v24/s1/**`、`v24/s7/README.md` 和 `v24/s9/test_g8.py`。
- 这是静态、有界评审。没有执行 `uv sync`、建库或 gate，也没有把历史绿色结果当作本轮结果。除本报告外不修改文件。

## 结论

当前文本不宜直接进入施工。主要阻断点是：P0 环境证明仍有缺口；W2 有一个必然失效的复合键、 FK 清单缺口和 effects 状态/nullability 歧义；W3 的 role family、command/replay 身份、重领 replay 权利和 committed probe 尚未形成可执行合同；DP2/DP3 的 pin、divert/raise 与基本 dispose 归属会改变后续实施顺序。

另一方面，不应回退以下已经纠正的方向：15 文件总 manifest、replay target 先于 closure、活 lease 返回 `stale_claim`、runs owner 两列 `NOT NULL`、disposable committed probe，以及 v24 的 11 条 closeout 加单列 s9 扩展检查。以下只写需要修正之处及这些决策的必要边界，不重写计划。

## 1. 会阻断 P0/W2/W3 或后续顺序的问题

### 1.1 P0：环境命令仍未证明 `.venv` 归属、PostgreSQL 版本和必需核心函数

`docs/plans/v24-cordis-dp1-foundation-plan-2026-10-25.md:27` 要求先确认 `.venv` 的 owner/路径属于本 worktree，再运行 `uv sync --locked`；但实际命令在 :240–243 只有 `test -d .venv`。该命令接受指向其他 checkout 的 symlink，也不检查 owner，因而会在验证之前就让 `uv sync` 修改一个尚未确认归属的环境。两个本地依赖源的相对路径写法与 `pyproject.toml:18-20`、`uv.lock` 一致；当前只读核查未发现路径缺失，但不能由此代替 P0 实跑。

另有两处准备缺口：

- `uv run python -c "import sys, psycopg2; ..."` 只证明 Python/psycopg2；`v24/s1/setup_db.py:817-833` 的 self-check 也不查询或打印 PostgreSQL `server_version`。因此 :29、:346 所称用这两条命令复核 PostgreSQL 18.4 不成立。
- Cordis 的 `effect_id_for`、随机身份和 digest 需要 `sha256(bytea)`/`gen_random_uuid()`。计划的 `00_schema.sql` 没有对应可用性检查；`v24/sql/00_schema.sql:4-33` 已有不安装 extension、同时验证核心函数存在及依赖归属的直接先例。

**精确修正：**

1. 在 `uv sync --locked` 之前加入真实检查，而不是只 `test -d`：

   ```bash
   test -d .venv && test ! -L .venv
   test "$(cd .venv && pwd -P)" = "$(pwd -P)/.venv"
   test "$(stat -f '%Su' .venv)" = "$(id -un)"
   test -e ../pgembed
   test -e ../duckdb-python-pgagent/dist-special-g1/duckdb-1.6.0.dev366+ga1f0ab1911-cp312-cp312-macosx_26_0_arm64.whl
   ```

2. 让 fixture self-check 通过维护连接记录 `current_setting('server_version')` 和 `server_version_num`；matrix 写实测值，不把 18.4 的历史记录当断言结果。
3. 在 Cordis `00_schema.sql` 和 CDP1-E 中复用核心函数存在性/非 extension 依赖检查，失败则停止，不通过安装 pgcrypto 来绕过“0 extension”。
4. 将 `--server-helper` 子进程、根 `server.py` 使用的 worktree `.pgdata`、启动失败、测试取消和 helper 回收责任写明。`server.py:14-19` 指向同一 worktree 数据目录，所以“私有 helper”不等于独立集群；至少需要串行使用纪律，以及失败/取消时只按已记录 OID 清理 DB/角色并回收 helper 的断言，不能泛化 DROP 或误停别人的服务。

### 1.2 W2：`current_episode_id` 的本地复合键列不存在，且“全部跨表 FK”仍不完整

`docs/plans/v24-cordis-dp1-foundation-plan-2026-10-25.md:128` 定义 fibers 的主键为 `id`，却把 current 复合键写成 `(fiber_id,current_episode_id)`；fibers 没有 `fiber_id` 列。这会使相应 DDL 直接失败。正确形状是：

```sql
FOREIGN KEY (id, current_episode_id)
  REFERENCES episodes(fiber_id, id)
```

目标端 `(fiber_id,id)` 与规格附录 A 的 `UNIQUE(fiber_id,id)` 一致；应改的是本地首列，不是目标端，也不是新增 fibers.fiber_id 列。

同一节 :142 声称跨表 FK 全部归入 `20_relations.sql`，但至少还缺 `pins.consumer_run_id` 的归属。该列是 run 消费者身份；没有 FK 或替代约束时，悬空 run pin 会破坏后续 drain/release 屏障。最小修正在 `20_relations.sql` 增加 `consumer_run_id → runs(id)` 普通 FK；若刻意不建，必须明确替代完整性机制，而不能称为“全部跨表 FK”。:120 和 :318 对 `20_relations.sql` 的简介也仍只写 owner/current/effect 子集，应同步改成完整跨表关系清单。

复合 FK 只证明 episode 属于该 fiber，并不证明 current 指向 open episode。规格 `docs/designs/cordis-plugin-system-2026-10-25.md:243` 把 current 定义为当前 open 投影。应在 DP1 增加 deferred constraint trigger，要求 COMMIT 时 current 为 NULL 或所指 episode `closed_at IS NULL`；否则就必须把该检查明确分给 DP2 advance，而不能在 DP1 matrix 标成已验证。

**CDP1-D 需要增加的证据：**合法 current 正例、跨 fiber current 负例、current 指向 closed episode 负例、E1 关闭/E2 开启后历史 owner 引用仍指向 E1 的正例，以及每个复合引用表的跨 fiber/episode 负例。后者同时证明历史 FK 没有误引用可变的 current projection。

### 1.3 W2：effects 的 cancelled/outcome/nullability 不能按现有“终态配对”字面实施

`docs/plans/v24-cordis-dp1-foundation-plan-2026-10-25.md:133` 只写“已终态与 outcome/settled_at 配对”。若理解为所有终态都必须有 outcome，会错误地强制 ready→cancelled 也携带外部 receipt；若理解宽松，又会漏掉 ready/claimed 的 outcome 必须为 NULL。规格 `docs/designs/cordis-plugin-system-2026-10-25.md:248` 明确 cancelled 只能由 ready 态落入，`v24/sql/10_schema.sql:101-106` 已有正确的分列先例。

应固定为独立谓词，而不是一个含糊的“配对”：

```sql
CHECK ((status IN ('succeeded','failed','unknown')) = (outcome IS NOT NULL))
CHECK ((status IN ('succeeded','failed','unknown','cancelled')) = (settled_at IS NOT NULL))
CHECK ((status = 'claimed') = (claim_owner IS NOT NULL AND lease_until IS NOT NULL))
CHECK ((parent_id IS NULL) = (ordinal IS NULL))
```

第一条同时保证 cancelled/ready/claimed 的 outcome 为 NULL，第二条要求 cancelled 有 `settled_at`。`attempt`/`fence` 应明确为 bigint、非负且 `fence <= attempt`，避免 Appendix A 的 int 草图与 v24 ABI 的 bigint 范围不一致。

DP1 不需要实现 cancel 命令或状态机。应把“cancelled 只能由 ready 转移”的生产者明确归到后续 run 终止阶段；DP1 只用 fixture 预置 cancelled 行验证 settlement 拒绝。该负例应断言 `receipt_conflict`、全表零写，不声称已经证明 claimed→cancelled 被运行时拒绝。另补 ready/claimed/cancelled 的 outcome 与 settled_at 真值表、非 claimed 残留 claim_owner/lease、parent/ordinal 半空等 DDL 负例。

### 1.4 W1/W3：随机 role family 还缺建库加载身份和精确映射合同

`docs/plans/v24-cordis-dp1-foundation-plan-2026-10-25.md:87` 定义随机 NOLOGIN/LOGIN 角色族，:180 又让 ACL 和 `role_allowed` 从 schema owner 推导 sibling roles，但没有规定谁创建 schema、加载时 `current_user` 是谁、database CREATE 权限如何授予。照现有文字实施，容易得到由 pgembed superuser 拥有的 schema，随后 family 发现和 ACL 全部失去依据。

可复用的完整加载链应明确为：维护 superuser 创建随机组/登录角色及 template0 数据库 → 只向本 fixture owner group 授予该临时库的 CREATE → owner LOGIN 连接并 `SET ROLE` 到对应 NOLOGIN owner group → 在同一事务加载；`CREATE SCHEMA v24_cordis` 因而以该 group 为 owner。`v24/s1/setup_db.py:592-653` 已有 database GRANT 和 SET ROLE 顺序。默认函数权限也必须针对同一个 owner group/current_user 设置。

对 :180 的映射还需收紧：

- 以 `pg_namespace.nspowner`（并可交叉核对 `pg_proc.proowner`）为起点，按精确命名规则得到四个预期 sibling role，再核验 OID、NOLOGIN/属性及 LOGIN→group membership；不能只凭字符串前缀搜索并授权。OID 用于身份核验和精确清理，SQL GRANT 本身使用经核验并正确 quote 的角色名。
- W1 catalog 断言 schema owner OID 恰为本 fixture owner group；W3 断言全部函数 owner、`search_path`、DEFINER 集合、精确 EXECUTE 和 PUBLIC/表权限。
- `role_allowed` 需要显式 role×class 矩阵。按当前文字的最小解释应固定为：三个协议角色都可提交允许的三类 lifecycle command；只有 service 可对 DP1 `host_io` 做 claim/success/failure/unknown；其他组合 false。若 admin 需要更窄权限，必须在 W3 前写成具体单元格，不能留给实现者猜测。
- 用两个不同 suffix 的 fixture 做跨 family 负例：A family 登录身份在 B 库中即使被测试 setup 临时授予 EXECUTE，也必须在 `role_allowed` 处失败；同时检查 SQL 文本和实际 ACL 不含 `v24_admin` 等硬编码角色。

### 1.5 W3：command body 与 replay 身份未固定，仅比较 bytes 会重放错误响应

`docs/plans/v24-cordis-dp1-foundation-plan-2026-10-25.md:146-166` 只给外层 envelope 和“确定性生成”名称，没有固定 Cordis command body 的必填键、kind 闭集、canonical 算法和 effect id 算法。durable probe 因而没有唯一可实现的输入合同。

更重要的是，requests 保存了 `kind`，:166 却只比较 canonical bytes。于是同一 principal/request_key/payload 换成另一 kind 时，只要传入与该新 kind 正确派生的新 effect id，就可能返回旧 kind 的首次 response。`v24/sql/30_advance.sql:249-263` 的 bytes/digest 分支不能未经审视地照搬；本报告不要求修改 v24，但新内核必须避免这个身份洞。

**精确修正：**

1. 固定 command body 为 `op='admit_and_apply'` 及 `{op,kind,request_key,canonical_bytes,payload}` 精确键集，request_key 1–512，payload object，canonical_bytes 为 payload canonical JSON UTF-8 的 base64；DP1 command kind 按规格 §10.1 限定为 `command_install/command_reconcile/command_dispose`，不复制 v24 的 kind allowlist。run_start 和业务 kind 的后续准入不归入这三类 command。
2. 明确 `canonical_json`、digest 和 `effect_id_for` 算法及一个固定 golden vector。若沿用 v24 算法，应写成 `sha256(UTF8(principal || ':' || kind || ':' || request_key))` 的前 32 个 hex 字符转 uuid，而不是仅写“确定性”。
3. request 命中后同时比较 stored `kind`、stored `effect_id`、canonical bytes 和 digest。相同四元组才 replay；同 key 不同 bytes 或不同 kind 均 `request_conflict`，错误派生 effect id 仍在 request 查询前返回 `effect_id_conflict`。新增“同 principal/key/payload、不同 kind”的 committed replay 负例，并断言零写。
4. claim body 仍固定为仅 `lease_ms`；settlement claim 恰有 attempt/fence/owner，数值类型、非负上限和 owner 长度进入 preflight，避免“外层兼容”只剩字段名兼容。

### 1.6 W3：过期重领没有检查显式 replay 权利，违反恢复边界

`docs/plans/v24-cordis-dp1-foundation-plan-2026-10-25.md:168` 允许所有已过期 claimed host_io 被重领。规格 `docs/designs/cordis-plugin-system-2026-10-25.md:798,804-806` 则要求：到期后的重投必须遵守显式 replay 合同，不能从 read_only 或幂等键自行推定；`installs.contracts` 正是该权利的承载位置（:241、:870）。当前计划虽然保存 contracts，却没有重领的消费者，属于 export 与计划共同遗漏的安全接缝。

不增表或新列的最小修正是：

- 在计划中固定 `installs.contracts` 的 replay 字段路径和闭集，可复用 v24 词汇 `no_replay/replay_safe/manual`；host_io 的冻结 `effects.input` 至少携带 install/contract 引用，closure 必须包含并锁定相应 install。过期重领只在 locked immutable contract 明确为 `replay_safe` 时允许；`manual` 不等同于 DP1 自动重领授权。
- ready 的首次 claim 与过期后的再次 claim 分开验证。无自动重投权利的过期重领返回闭集错误（建议 `stale_claim`，detail `{"reason":"replay_not_allowed"}`），不得递增 attempt/fence、不得改写 owner/lease，也不得以 deferred 掩盖。
- DP2 install admission 负责生成并校验这个冻结引用，且按规格 G3 拒绝无所需 replay 权利的外部写能力；DP1 不提前实现 install interpreter，只用 owner-seeded contracts/effects 验证 claim 分支。

CDP1-K 必须有四个 committed 场景：`replay_safe` 过期重领成功且 attempt/fence 递增；无权利重领零写；无权利重领失败后，原 token 因未被替代仍可在 probe settlement seam 提交可信 receipt；成功重领后旧 token 才 `stale_claim`。活 lease 的 `stale_claim/claim_busy` 与这里的 replay 权利是两个独立判定，不能互相替代。

### 1.7 W3：committed probe 方向正确，但证据步骤和 delta seam 仍需消歧

export :197、:267 允许在 rollback-only 事务内临时替换 seam 并声称原子 receipt；现计划 :90、:170 改为 disposable DB 中真实 COMMIT，这是必要改进，不应回退。不过当前还没有明确要求 seam 替换本身已提交、重放来自新连接，也没有说明“production interpreter/delta seam 仍为 0A000”中的 delta 是否包括 :160 已实现 empty-domain receipt 的 `validate_and_apply_delta`。若包括，它与该函数的合同直接矛盾。

建议保留一个 production fixture 和一个 receipt-probe fixture，按以下可观察顺序验收：

1. 两库均由 canonical production loader 建立，记录 production 的 `pg_get_functiondef`/hash。
2. 只在 probe DB 替换 interpreter，并在独立事务 COMMIT；用另一连接确认替换可见。所谓 no-op 是“无生命周期领域 mutation”，其 delta 仍须产生测试所需的 effect receipt、request response 和簿记 event，不能是会导致无任何可重放行的全空 delta。
3. 首次 command advance 后 COMMIT 并关闭连接；新连接重放同一请求，断言返回首次 response，requests/effects/events/successors 计数不增加。fault-after-write 必须在 effect/request 已写之后触发，再证明 rollback 后十表快照与调用前完全相同。
4. settlement probe 同样先 COMMIT seam 替换，再 COMMIT terminal receipt；新连接改变 `receipt_key` 或提交错误 token 时仍优先 replay，冲突 receipt 零写。另覆盖“lease 已过期但未重领，原 token 的首次可信 settlement 可 COMMIT”。
5. 完成后按 OID 删除 probe DB，重新读取**原 production DB** 的函数定义/hash，并调用两个 interpreter 证明仍为 `0A000`。不必仅为这一断言再重建第三份 production fixture；原库未变比“重建后正确”更能证明 probe 没有越界。

文本应明确：production 的 `interpret_command`/`interpret_settlement` 是 `0A000`；`validate_delta` 与 `validate_and_apply_delta` 的 empty-domain receipt 路径是已实现接缝，不能也称其为 `0A000`。

### 1.8 DP2/DP3：pin 与 divert/raise 的归属互相依赖，export 的基本 dispose 被丢失

`docs/plans/v24-cordis-dp1-foundation-plan-2026-10-25.md:187` 把 L-Begin/L-Iter/L-Finish 和 divert/raise 全放 DP2，:188 又把 activation pins/live 放 DP3。规格 `docs/designs/cordis-plugin-system-2026-10-25.md:324` 的 L-Begin 本身必须逐 key 写 activation pin，所以 DP2 无法在“没有 activation pin”的前提下实现 begin。规格 §10.3 的 S2/S3（:762–768）则明确把 L-Divert/L-Raise 放在后续 pin/live/cleanup 切片。

此外，export :285 的 DP3 包含“基本 dispose”，现计划删除了它，DP6 只剩“dispose 子树完整收敛”。这使基本/leaf dispose 与 O-Remove 在任何阶段都没有明确 owner，而不是有意的范围收窄。

**实施顺序应调整为：**

- DP2：install/O-Insert 与 reconcile P0–P4 的 begin/iter/finish 成功路径，包含 L-Begin 所需的 resolve、committed_view、activation pin 创建、iterator 和 contribution append。
- DP3：pin 的 live/withdraw/release 与屏障、L-Leave/L-Unload，以及 L-Divert/L-Raise；恢复 export 中的基本/leaf dispose 和墓碑语义。若 DP2 在 divert/raise 尚未实现前遇到 target drift 或注册失败，必须 `0A000` 回滚并在 matrix 标未实现，不能写入半个 closing 状态冒充完成。
- DP6：继续承担全宿主公平扫描、八行崩溃矩阵、未知资源对账和完整 dispose 子树，不把基本 dispose 与全子树恢复混成同一个首次交付。

这同时恢复 export 的实现性内容和规格 S2→S3 的依赖顺序，不增加新的 DP 或用户范围。

## 2. 对应 gate 前仍需补齐的设计与可证伪性

### 2.1 replay-first 需要交叉反例，closure 发现也必须在 513 时短路

`docs/plans/v24-cordis-dp1-foundation-plan-2026-10-25.md:166-167` 的 replay target lock 先于 closure 与规格 §3.2 一致，且修正了 export :200 的“request 在领域锁 pass 后”顺序，应保留。需要补的是能证明优先级的交叉用例，而不是分别测试 replay 和锁序：

- 已存 request/terminal receipt 的关联 closure 超过 512 时，仍返回首次 response/replay 或 receipt conflict，不得变成 `retry_with_closure`，不得写行。
- 非 replay 达到 512 可通过、达到 513 返回 `retry_with_closure`；request identity 行和 events 不计数。
- 以锁证据固定“G → 仅目标 request/effect → 其余 closure”的例外顺序；其余 pass 才是 scopes parent-depth/UUID，再 runs/effects/installs/fibers/episodes/contributions/pins UUID。可用 test-only discovery counter 证明 replay 没有调用 closure discovery。
- 发现过程必须在第 513 个不同 typed target 时停止并失败。先递归物化完整 CTE、再 `count(*) > 512` 不是有界发现；`v24/sql/30_advance.sql:317-533` 的旧做法不能当成有界性的充分证据。

### 2.2 15 文件不违反 §10.1，但预算必须进入 gate，拆 helper 不能“减少”总行数

`docs/plans/v24-cordis-dp1-foundation-plan-2026-10-25.md:100-118` 的 15 个总文件中，`10_`–`17_` 恰是八张领域表的一表一文件；其余文件承载两张簿记表、关系、触发器、advance 和 ACL。因此“总数为 15”本身不违反规格 §10.1 的“8 个领域 SQL 文件”，不应为了凑回 export 的五文件而合并。

现计划 :44 虽补入 DDL ≤900、advance+helpers ≤1200，却没有对应 gate 或计数口径。应在现有 CDP1-E/D/K 中增加：

- 对完整 15 项 canonical tuple 和 10–17 到八表的精确映射作硬断言，避免同时修改 expected/actual 造成自洽漂移。
- W2 实测领域 DDL 行数；`20_relations.sql` 的领域 FK 和 `30_triggers.sql` 的领域守卫不能从预算中隐身。可采用保守口径：10–17、20、30 全计领域 DDL，18/19 的簿记 DDL 单列。若采用其他口径，必须在 matrix 明示并保证仍覆盖规格要求。
- W3 实测 `40_advance.sql` 中 advance 与私有 helpers 的总行数，W4 复核并记录；DP6 仍须做最终实现预算复核。

规格 §10.1 的预算已经包含 helpers，所以“超过行预算先拆私有 helper”（计划 :44）不能使总数重新达标。拆函数只改善局部结构；超支时应简化实现或回到规格重裁，不得通过移动行到另一个 helper 文件来假称满足预算。

### 2.3 P0 实施步骤仍漏跑 s9；11 条 closeout 本身是正确的

`docs/plans/v24-cordis-dp1-foundation-plan-2026-10-25.md:16` 和 :276 明确要求 P0/W4 都运行 s9，但 P0 实施步骤 :346 只写 11 条 closeout，W1 Done-when :217 也没有 s9 记录。应在 P0 步骤和 W1 证据要求补上 `uv run python v24/s9/test_g8.py`，单列真实退出码及 23/23 ID 结果，仍不得计为第 12 条 closeout。

计划 :278–290 的 11 条命令及顺序与 `v24/s7/README.md:210-227` 完全一致；s9 是 extension check 的定位也与 `v24/s7/README.md:234-254` 一致。无需在本批评中增加 G9/G10 或其他扩展 gate。

### 2.4 export 的完整 owner/DAG 校验被弱化可以接受，但残留断言必须与 empty-only 一致

export :254 要求 DP1 `validate_delta` 校验 footprint、owner 和 DAG；现计划 :159 明确只做结构/闭集/B=16，并拒绝任何非空领域 mutation。对 DP1 而言，后者是更简单且不损失当前安全性的设计：既然不允许任何真实领域 delta，就没有必要提前实现并假装验证完整的生命周期 owner/confinement/DAG。

需要修正的是残留矛盾：

- :168 仍写“锁后复验 closure、owner、claim/token、预算和 delta 结构”，应收窄为 DP1 实际检查的 target/claim eligibility、协议预算与结构，不把生命周期 owner/run budget 标成已验证。
- :205 的“非法 delta 写目标/owner”不能通过专用 owner 规则已实现的假象。应改成“任何非空 domain mutation（包括携带合法或非法 owner 形状的样例）都因 DP1 empty-only 边界被拒绝”，断言其稳定拒绝原因和零写；matrix 继续把真实 owner/confinement/联合 DAG 标为 DP2/DP3 未实现。
- 16/17 successor、ordinal、inverse 闭集等结构负例应保留，不能因领域写入为空而删除这些有信息量的测试。

### 2.5 一处错误规格引用需要纠正

`docs/plans/v24-cordis-dp1-foundation-plan-2026-10-25.md:73` 引用设计稿 :276–291（§4.5）证明 events 和 requests 都是簿记；该节只论证不新增第九张领域表，并没有同时给出 requests 的这一定义。应改引设计稿 §1.2 的 :43–51（events/requests 的分类）及 §10.1 :730 或附录 C :1067。表数结论本身正确，不需改变。

## 3. 已核实、不要为了“修正”而回退的基线差异

1. **runs owner `NOT NULL` 是正确修订。** export :227 的可空 pair 与规格附录 A `docs/designs/cordis-plugin-system-2026-10-25.md:965-977` 不一致，计划 :132、:142 已修正。CDP1-D 还需显式覆盖两列均 NULL、任一单列 NULL、合法非空复合 owner 和跨 episode 错配，防止实现时回退。
2. **活 lease `stale_claim` 是显式且有依据的兼容偏离。** 规格 §3.1 :175 把 deferred 限定为 DB barrier，计划以 `stale_claim` + `{"reason":"claim_busy"}` 区分 claim 冲突，不能因 v24 host 的旧行为而改回 deferred。应断言精确错误 JSON、attempt/fence/owner/lease 不变；同 owner 与不同 owner 的活 lease 重领都走该分支。只有 barrier 才返回 deferred/null claim。
3. **replay target 先于 closure 正确。** 不再采用 export :200 的领域锁后 request 顺序；后续修正只是补交叉反例，不是恢复 closure-first。
4. **disposable committed probe 是对 export rollback-only 证据的实质增强。** 应按 §1.7 补强，不应退回临时函数在回滚后消失却仍声称持久 replay 的做法。
5. **events 不保留 export 的 created_at 不构成 DP1 语义缺失。** export :235 有该列，计划 :140 与规格附录 A :1011–1021 一致地省略它；事件游标由 `(entity_type,entity_id,seq)` 承担。不要只为基线保真重新加列；后续若确有观测需求，按计划先修订规格。
6. **15 文件、三元 claim ABI 和 runs 非空 owner 均应保留。** 它们分别修正 export 的五文件过度合并、附录 token/ABI 冲突和可空 owner 偏差；真正的问题是本文列出的键列、权利和 gate 接缝，而不是这些决策本身。

## 4. 对实施顺序的最小修正

1. **P0 之前/之中：**补 `.venv` 与真实 PG 版本检查、核心函数检查、helper 所有权/取消清理，以及 s9 的 P0 运行记录。
2. **W2 之前：**修正 current 本地复合键、补齐 consumer_run 等 FK、固定 effects nullability/状态谓词，并把复合 FK、owner 非空和预算断言纳入 CDP1-D。
3. **W3 之前：**固定 role family 加载与授权矩阵、command body/effect id/replay 身份、replay 权利和 closure 短路；按 §1.7 写可重复的 committed probe，不先实现生命周期 interpreter。
4. **DP2 开工前：**重排 DP2/DP3 的 activation pin、divert/raise 和基本 dispose 归属，避免在 DP2 写出无法清理的半生命周期状态。
5. **W4：**复核 11 条 closeout 与单列 s9、全部 DP1 gate、SQL 预算及 production seam；不把 DP2–DP6 的能力写成 DP1 已覆盖。
