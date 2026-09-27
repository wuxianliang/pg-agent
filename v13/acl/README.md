# v13 stage 23 — acl（D7 overload）

谓词 `v13_control_authorized(actor, target)` 是取消、human 结算、以及后续观察/日志/交接的唯一亲缘判断。不读 `sessions.status`，不锁行，自身只返布尔。

## 真值表

| 类 | 条件 | 结果 |
|---|---|---|
| 行政 | `p_actor IS NULL` 且 `v13_control_operator()` 为真，且 target 行存在 | 真。不读 status。终态 cancel 仍走已冻 `replay` |
| agent | `p_actor` 非空，actor 行存在，target 行存在，`p_actor <> p_target`，`target.parent_session_id = p_actor` | 真。同样不读 status |
| 拒绝 | 其余：非 operator 的空 actor、actor 行不存在、target 不存在、自身、孙、祖先、旁系、无关 | 假 |

`v13_control_operator()` ≡ `rolsuper` 或 `pg_has_role(current_user, 'v13_route', 'USAGE')`。`USAGE` 不把 NOINHERIT 的 `v13_worker` 算进带；`v13_route_login` 经 INHERIT 进带。`p_actor` 非空时即使当前 principal 是 operator 也只走亲缘，不升行政。

## overload 通道

| 签名 | 角色 |
|---|---|
| `v13_cancel(p_actor uuid, p_sid uuid)` | 唯一取消正文。准入在递归/锁/`cancel/requested` 之前；锁后复验在 tree-changed 与终态 `replay` 之间，只在 actor 非空时跑 |
| `v13_cancel(p_sid uuid)` | 纯委托 `v13_cancel(NULL, p_sid)`。不保留第二份递归 |
| `v13_complete(p_actor, p_effect, p_attempt, p_fence, p_status, p_result jsonb DEFAULT NULL::jsonb)` | 唯一结算正文。锁前扩列取 `session_id, kind`；actor 非空只放行 human；锁后复验重读锁定行，不并进 `FOR UPDATE` |
| `v13_complete(五参，默认 `NULL::jsonb`)` | 纯委托 `actor=NULL`。默认参数与换体前活体逐字相同 |

拒绝文案：agent 路径与「非 operator 且 actor 空」一律 `v13: session not found`（不插值 uuid）。operator 且 actor 空且目标无行保留活体 `v13: unknown session %` / `v13: unknown effect %`。非 human 且 actor 空不调谓词。

## 驱动器合同

agent cancel = `v13_cancel(父会话, 子会话)`。agent human complete = 六参且 actor 前置。行政/UI = 旧签名，不传 actor。动词不读工具 JSON、不读 human result、不读事件 payload、不读会话参数。仓库内 driver 补丁不进本里程碑。

## 验收

| 格 | 状态 |
|---|---|
| 谓词 + 换体 + `uv run python v13/acl/test_acl.py` | 合同已证明（2026-09-27 退出码 0，197 checks） |
| 仓库内驱动器在 agent 路径传 actor | 未交付 |

不得把本 stage 写成「F17 已在生产路径生效」。

## 威胁模型

工具参数不可信。持有 route 或超级用户连接的驱动器可信。谓词是动词里的控制流，不是 RLS；route 今天就能直接 `UPDATE effects`，本期不重划表权限。SQL 证明的是：动词不读工具参数；伪造 JSON actor 不改变结果；亲缘按 `parent_session_id` 执法。库只验带与亲缘，不证 actor 的网络来源。

## 不授权

新函数 `REVOKE EXECUTE FROM PUBLIC` 后只授 `v13_route` 与旧签名活体 proacl 里的 `v13_spawn_owner`。不授 `v13_worker`、`v13_resolve`、`v13_recall`、PUBLIC。不对换体函数 `REVOKE ALL`。

## Gate

`uv run python v13/acl/test_acl.py`（退出码 0）：谓词矩阵；cancel/human 接入正例；六类文案全等；6 参缺 effect 不走 `unknown effect`；spawn_owner 缺 effect 不走原句；human 自答加伪造 actor 键；未授权终态不是 replay；父调孙零写；worker 42501；operator 传 actor 不升行政；非 human 不误套谓词；COMMIT 并发日程（2 参 cancel 与 6 参 human）；源码差集与 wrapper 纯委托；D12 恰一次。
