# v17 G5 · develop —— agent 长工具，下一轮的 tool job 打到新 Lisp 函数上

Gate: `uv run python v17/develop/test_develop.py`（退出码 0 = 通过）

## 一句话

**v12 的 turn 管道负责路由与护栏，world daemon 负责把模型给出的
`defun` 变成持久能力：一次 `lisp_develop` job（带调用方的 goals）→ world
前进一个 revision → 之后同一会话的 tool 路由把 job 投给这个新函数 →
交付。** 杀进程换新进程，函数仍在（Postgres 即恢复面）。

## 部署形状（gate 如实建模的部分）

| 组件 | 职责 |
|---|---|
| Python `QueueDriver` | SQL-only 推进 turn 状态机（v12 不动） |
| SBCL **queue worker** | 答 Jev 批次、跑 LLM 生成；对 lisp job 的唤醒**只归档不认领** |
| SBCL **world daemon** | 扫表，服务 `lisp_eval` / `lisp_develop` / `lisp:` 工具 job |
| gate 脚本（部署方） | 把 LLM 交付的文本落成 `lisp_develop` job；往 `tools` 注册工具行与其参数阈值 |

为什么「把文本变成 job」和「注册工具」在 gate 里：v12 的 driver 是
SQL-only 的设计，不可能组装 Lisp 或写目录行。这两步是部署侧行为，
gate 显式做，并在注释里说明。

## `lisp:` 工具的契约（重要）

- `tools.handler = 'lisp:<world>:<fn>'`、`effect_class='side_effect'`、
  `param_spec` 每个参数一项；
- 注册工具必须**同时注册参数阈值**：`v12_routes` 视图 join `thresholds`
  on (purpose, question_id)，没有阈值行就没有 verdict，
  `v12_resolve_tool_params` 于是跳过该参数（params 变空）。这是注册
  工具容易漏的一步，gate 断言了它；
- daemon 组装的形式是 `(<fn> '((:PARAM . "v") ...))`——**params alist
  必须 quote**，否则 `((:PARAM . "v"))` 里的关键字会被当函数操作符
  （SBCL 只报难解的 `illegal function call`）；
- 函数签名就是「一个参数：解析后的 JSON params alist」；值是**文本**
  （v12 的选项是字符串），所以数值参数要 `parse-integer`，且**不要**
  `write-to-string`（`write` 的 `:escape` 默认 T 会给字符串加引号）。

## 四场景

1. **长工具全链路**：user 提问 → Jev 路由 `llm_generate` → 队列 worker
   的假 LLM 产出 defun → 护栏过 → 交付；gate 把文本落成
   `lisp_develop`（goals `(= (double '((:x . "21"))) 42)`）→ 新进程探针
   看到函数 → 注册工具（含阈值）→ 第二轮 user 提问 → 路由 `tool_action`
   → driver 投 job → daemon 用新函数执行 → `tool/result` 带 `params`
   与 84；
2. **不变式拒绝**：`invariants: ["(null (fboundp 'poison))"]` 的 develop
   被拒，reason 指名，函数不在 world 里；
3. **显式 rollback 消失**：`v17/develop/lisp/lisp-sql.lisp` 用会话 API
   提交 `:rollback "previous"`（内核的 rollback 是 worker-only），钩子在
   一个事务里导入目标 revision 并以 `rollback-source` 发布，然后函数
   不在恢复出的 world 里；
4. **重启仍在**：新 daemon 起得来、被拒的函数仍不存在。

## 脚本 `lisp-sql.lisp`

`V17_ROLLBACK_WORLD=<name> sbcl --script v17/develop/lisp/lisp-sql.lisp`
打印 `ROLLBACK-DONE target=<revision-id>` 与 `ROLLBACK-COMMIT`。
要点：rollback 钩子必须返回 **plist**（`:commit :rolled-back :revision id
:source target`）——session-step 的合同把返回值当 outcome 存，返回裸 id
会让内核在 `emit` 时撞「malformed property list」。
