# 设计五：数据库原生的 CE 会话，加上 v20 的控制协调

日期：2026-10-13
状态：设计。2026-10-14 按 Oracle `untitled-chat-EBEB1E` 复审补入两条：显式续接 workflow 时在原 run 上承接已提交 refs；写 step 时对 workflow revision 做 CAS。不修改章程，也不改 `ce_facades_r2`。

这一版要同时做到两件事。内核身份沿用 RepoPrompt-CE 已经落盘的会话结构。run 的快照、owner fence、回合回执、工具准入、步骤、artifact 和计划沿用 v20 章程里的协调对象。写入口仍然只有 `Control.execute`。模型和文件读写仍然在事务外。

## 1. CE 的数据如果放进数据库

CE 今天没有 agent 控制库。持久事实是几份文件，运行中的 run 是内存对象。按「一份文档一行、数组拆成多行、整文件 CAS 换成行级 revision」翻译之后，是下面这些东西。

### 1.1 已经落盘的

| CE 里的东西 | 位置 | 进库之后 |
|---|---|---|
| 运行时会话 metadata | `DomainRuntime/.../settings/agent-sessions.json`，整文件按 digest CAS（`DomainPersistence.swift:394`、`:605`–`:617`） | 每个 session 一行。文件级 `revision` 换成这一行自己的 `revision` |
| 行的字段 | `DomainAgentSessionDurableMetadata`（`DomainAgentRunSessionStore.swift:42`–`:51`） | `session_id`、runtime、registration generation、`last_epoch_ordinal`、`continuity_generation`、`state`、`resumable`、`updated_at`。没有 workflow id，没有 run id，没有 parent，没有正文 |
| 外层文档 | `DomainAgentSessionMetadataDocument`（同文件 `:99` 起）：version、profile、revision、sessions 数组 | profile 收到目录行。数组不再整包重写 |
| 界面会话文档 | 工作区 `AgentSessions/AgentSession-<uuid>.json`（`HistorySessionScanner.swift:1454`） | 正文拆成 transcript 表。`providerSessionID` 等句柄单独一张表 |
| 自定义 workflow | `~/Library/Application Support/RepoPrompt CE/Workflows/*.md`（`AgentWorkflowStore.swift:129`–`:132`） | 目录行只记 `definition_id`、路径和 digest。正文留在文件里 |
| 计划导出 | `prompt-exports/` 下的文件，消息里带 `oracle_export_path` | artifact 行：digest + path。字节留在事务外的文件里 |
| worktree 绑定 | `agent-worktree-bindings.json`，同样整文件 CAS | 这一版不进内核表。快照里需要时走 context / worktree 插件 |

`AgentSession`（`AgentSession.swift:143`）上的身份是 `id`（`:148`）。`parentSessionID` 在 `:230`。`transcript` 在 `:164`。`providerSessionID` 在 `:189`，注释写明它用于 `--resume`，不重放历史。`providerCleanupHandle` 在 `:193`，注释写明和可恢复性分开。这些字段里，只有 `id` 和 lifecycle 计数属于 metadata 那一行。

### 1.2 在内存里、数据库版要留下来的

无界面协调器里 `runID = sessionID`（`DirectHeadlessProviderCoordinator.swift:206`–`:207`）。父指针取调用方 principal 的 `runID`，并且只有这个 id 还在以 sessionID 为键的活表里才保留（`:211`–`:212`、`:243`）。所以父指针的值就是父 session 的同一个 UUID。

`DomainAgentRunTurnEpoch`（`DomainAgentSessionModels.swift:11`–`:20`）挂在 session 上：ordinal、continuity、`transitionKind`（`initial`、`relatedFollowUp`、`steering`、`unrelated`）。resume 认领的是同一个 `sessionID`：`nextEpochOrdinal` 从 `lastEpochOrdinal + 1` 起，`continuityGeneration` 原样保留（`DomainAgentRunSessionStore.swift:288`–`:304`）。界面侧的 MCP 激活走的就是 `claimResumableSession`（`AgentModeViewModel.swift:10233`）。

`DomainAgentRunSnapshot`（`DomainAgentSessionModels.swift:75` 起，字段从 `:494`）是 poll 看到的投影：`sessionID`、可选的 `runID`（`:495`）、status、预览、interaction、parent、failure。这个类型没有 `Codable`，CE 不把它写进 metadata 文件。进程没了，列表只剩 metadata。v20 要在重启后还能 CAS 和恢复，所以设计五把**最后一份已发布快照**写在 `v20_runs` 上，并把控制面的 `run_id` 填成 `session_id`。这是 v20 补上的协调行，不是 CE metadata 的字段。

正文里还有另一个 `runID`，不要并进这张控制表。`AgentTranscriptProviderResponseSpan.runID`（`AgentTranscriptModels.swift:347`）和 `providerTurnID`（`:346`）跟着 response span 走。`AgentTokenUsagePersist.runID`（`AgentSession.swift:39`）是用量行上的可选 UUID。它们和 `AgentRecord.runID = sessionID` 不是同一个事实。设计五把前者放在 span 和用量行的 `provider_run_id` 上，不设向 `v20_runs` 的外键。

### 1.3 看起来像工作流、其实不是容器的

`AgentWorkflowDefinition.template` 标明 runtime-only，不持久化（`AgentWorkflow.swift:140`–`:141`）。`CodingKeys`（`:255`–`:256`）没有 `template`。发消息时用当前选中的 workflow 包住用户文本，然后立刻清掉 `selectedWorkflow`（`AgentModeViewModel.swift:17244`）。留下的痕迹在这条 transcript activity 的 `workflow` 字段上（`AgentTranscriptModels.swift:91`）。一个 session 上没有 workflow 实例外键。

无界面启动只解析内建 workflow，把包装后的字符串交给 provider（`DirectHeadlessProviderCoordinator.swift` 的 `resolvedLaunchMessage`）。仓库里没有 `WorkflowRun` 这种类型。编排把计划写成文件，把路径放进子 agent 的 message。子 agent 是一次新的 `agent_run start`，因此是一个新的 session id，parent 指向调用方。

### 1.4 两套「turn」不要并成一张表

`AgentTranscriptTurn`（`AgentTranscriptModels.swift:437`）是对话正文：request、response spans、保留层级、摘要。`v20_turns` 是章程里的 Worker 回执（`docs/designs/v20-runtime-charter-draft-2026-10-12.md:244`–`:245`）。一次对话回合可以对应一次或多次控制回执。设计五两张表都留。可选的 `transcript_turn_id` 放在 `v20_turns` 上，外键指向 `v20_transcript_turns`。`v20_transcript_turns` 不放 `control_turn_id`。

工具同理。`AgentTranscriptToolExecution`（`AgentTranscriptModels.swift:39`）是对话里的投影。`v20_tool_invocations` 是准入、lease 和结果的权威。T1 写入准入行和请求投影，并固化当时的 owner generation 与 epoch。T2 校验通过后，在同一个事务里写结果和响应投影。旧 owner 或旧 epoch 只归档。大块参数和结果进 artifact，投影上留 `invocation_id`、状态和有界摘要。

## 2. 身份规则

1. `v20_sessions.session_id` 是调用方看到的稳定 id。它可以在没有任何 workflow 实例时存在。
2. 每个 session 恰好有一行 `v20_runs`，并且控制面的 `run_id = session_id`。这是无界面路径 `AgentRecord.runID = sessionID` 的数据库形式。resume、steer、recover 都不分配新的控制 run id。span 上的 `provider_run_id` 可以不同，也可以为空。
3. 推进单位是 epoch。steer 插入 `transition_kind = steering` 的 epoch。相关的 resume 插入 `related_follow_up`，ordinal 加一，continuity 不变。`unrelated` 才让 `continuity_generation` 加一，和 `beginEpoch` 一致。
4. 子 agent 是新的 session。`parent_session_id` 等于父 session 的 id。子 session 自己的 `run_id` 等于它自己的 `session_id`。因为别名成立，这个父 id 同时就是父 run 的 id。
5. `sessions` 上不设 `workflow_run_id`。workflow 定义出现在发出去的那条 activity 上。多步实例是另行准入的 `v20_workflow_runs`，步骤再指向执行它的 session。
6. owner fence 在 run 上：`owner_generation` 和 `owner_backend_pid`。`recover_owner` 在同一个事务里抬高 run 的 owner generation 和 session 的 registration generation。旧 generation 的 steer 被拒绝。T1 把当时的 `owner_generation` 和 `epoch_id` 写在 operation 上；同时准入的 turn 或 tool invocation 也写上这两列。当前 epoch 是 `v20_epochs` 里 `ordinal = v20_sessions.last_epoch_ordinal` 的那一行。T2 的 `publish_snapshot`、`accept_turn_receipt`、`accept_tool_result` 在同一事务里锁住 run、epoch 和 T1 operation。只有 operation 仍是 `pending`、固化的 owner generation 仍等于 run 上的值、固化的 epoch 仍是当前 epoch、该 epoch 的 `closed_at` 为空，并且目标状态迁移仍然允许，才更新当前快照。旧 owner 或旧 epoch 的迟到结果只归档，不覆盖 `v20_runs`。`cancel` 和 `cleanup` 不改 owner generation，也不换 epoch；它们在同一事务里给当前 epoch 写上 `closed_at`，并把该 epoch 上尚未完成的 operation 从 `pending` 改为 `closed`。关闭之后到达的结果只归档，不覆盖当前快照。
7. `provider_session_id` 和 cleanup handle 不参与 CAS，也不作为删除事件或 transcript 的理由。

设计三把 resume 做成「同一个 session id，新的 run id，session 指向一个 workflow」。设计五把 resume 做成 CE 的 claim：session id 和 run id 都不变，epoch 往前走。workflow 实例是后来的可选行。

## 3. 表

命名跟章程的最小对象对齐。章程 `:242`–`:250` 列出的 runs、operations、turns、tool invocations、events、workflow runs、workflow steps、artifacts 都在。这一版补上 CE 有、章程名单里还没有的 session、epoch、transcript 和 workflow 定义。计划四张表沿用章程 `:730`–`:734`。

```sql
CREATE TABLE v20_runtime_catalog (
    profile_identifier text PRIMARY KEY,
    metadata_schema_version integer NOT NULL,
    revision bigint NOT NULL
);

CREATE TABLE v20_sessions (
    session_id text PRIMARY KEY,
    owning_runtime_id text NOT NULL,
    owning_runtime_generation bigint NOT NULL,
    registration_generation bigint NOT NULL,
    last_epoch_ordinal bigint NOT NULL,
    continuity_generation bigint NOT NULL,
    state text NOT NULL,          -- dormant | active | interrupted | terminal
    resumable boolean NOT NULL,
    list_hidden boolean NOT NULL DEFAULT false,
    parent_session_id text REFERENCES v20_sessions (session_id),
    revision bigint NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE TABLE v20_session_profiles (
    session_id text PRIMARY KEY REFERENCES v20_sessions (session_id),
    name text NOT NULL DEFAULT '',
    workspace_id text,
    is_mcp_originated boolean NOT NULL DEFAULT false,
    created_by_overseer_session_id text,
    document_version integer NOT NULL DEFAULT 9
);

CREATE TABLE v20_session_provider_handles (
    session_id text PRIMARY KEY REFERENCES v20_sessions (session_id),
    epoch_id text,                 -- 最近一次成功写入当前句柄的 epoch
    attempt_seq bigint,           -- 当前句柄属于哪一次执行尝试
    provider_session_id text,
    provider_cleanup_handle jsonb,
    codex_conversation_id text,
    codex_rollout_path text,
    codex_mcp_session_key text
);

CREATE TABLE v20_runs (
    run_id text PRIMARY KEY,
    session_id text NOT NULL UNIQUE REFERENCES v20_sessions (session_id),
    revision bigint NOT NULL,
    status text NOT NULL,         -- running | waiting_for_input | completed | failed | cancelled | expired
    status_text text,
    latest_assistant_preview text,
    interaction jsonb,
    failure_reason text,
    transcript_item_count integer NOT NULL DEFAULT 0,
    owner_generation bigint NOT NULL,
    owner_backend_pid integer,
    updated_at timestamptz NOT NULL,
    CONSTRAINT v20_runs_id_aliases_session CHECK (run_id = session_id)
);

CREATE TABLE v20_epochs (
    epoch_id text PRIMARY KEY,
    session_id text NOT NULL REFERENCES v20_sessions (session_id),
    run_id text NOT NULL REFERENCES v20_runs (run_id),
    ordinal bigint NOT NULL,
    continuity_generation bigint NOT NULL,
    transition_kind text NOT NULL, -- initial | related_follow_up | steering | unrelated
    activation_id text NOT NULL,
    registration_generation bigint NOT NULL,
    closed_at timestamptz,
    UNIQUE (session_id, ordinal)
);

CREATE TABLE v20_workflow_definitions (
    definition_id text PRIMARY KEY, -- builtin-orchestrate，或 custom-<uuid>
    source text NOT NULL,           -- builtin | custom
    display_name text NOT NULL,
    body_path text,
    body_digest text
);

CREATE TABLE v20_workflow_runs (
    workflow_run_id text PRIMARY KEY,
    definition_id text REFERENCES v20_workflow_definitions (definition_id),
    revision bigint NOT NULL,
    status text NOT NULL
);

CREATE TABLE v20_workflow_steps (
    step_id text PRIMARY KEY,
    workflow_run_id text NOT NULL REFERENCES v20_workflow_runs (workflow_run_id),
    seq bigint NOT NULL,
    session_id text REFERENCES v20_sessions (session_id),
    run_id text REFERENCES v20_runs (run_id),
    epoch_id text REFERENCES v20_epochs (epoch_id),
    input_artifact_refs text[] NOT NULL DEFAULT '{}',
    output_artifact_refs text[] NOT NULL DEFAULT '{}',
    status text NOT NULL,
    UNIQUE (workflow_run_id, seq)
);

CREATE TABLE v20_artifacts (
    digest text PRIMARY KEY,
    kind text NOT NULL,
    path text,
    body jsonb,
    session_id text,
    run_id text,
    availability text NOT NULL DEFAULT 'available'  -- available | unavailable
);

CREATE TABLE v20_transcript_turns (
    turn_id text PRIMARY KEY,
    session_id text NOT NULL REFERENCES v20_sessions (session_id),
    retention_tier text NOT NULL,
    summary jsonb,
    terminal_state text,
    started_at timestamptz NOT NULL,
    completed_at timestamptz
);

CREATE TABLE v20_transcript_spans (
    span_id text PRIMARY KEY,
    turn_id text NOT NULL REFERENCES v20_transcript_turns (turn_id),
    provider_turn_id text,
    provider_run_id text,
    lifecycle text NOT NULL,
    started_at timestamptz NOT NULL,
    completed_at timestamptz
);

CREATE TABLE v20_transcript_activities (
    activity_id text PRIMARY KEY,
    turn_id text NOT NULL REFERENCES v20_transcript_turns (turn_id),
    span_id text REFERENCES v20_transcript_spans (span_id),
    sequence_index bigint NOT NULL,
    role text NOT NULL,
    item_kind text NOT NULL,
    text text NOT NULL DEFAULT '',
    workflow_definition_id text REFERENCES v20_workflow_definitions (definition_id),
    tool_invocation_id text,
    UNIQUE (turn_id, sequence_index)
);

CREATE TABLE v20_provider_token_usage (
    usage_id bigserial PRIMARY KEY,
    session_id text NOT NULL REFERENCES v20_sessions (session_id),
    provider_run_id text,
    provider_turn_id text,
    prompt_tokens integer NOT NULL,
    completion_tokens integer NOT NULL,
    recorded_at timestamptz NOT NULL
);

CREATE TABLE v20_operations (
    request_id text PRIMARY KEY,
    verb text NOT NULL,
    epoch_id text REFERENCES v20_epochs (epoch_id),
    owner_generation bigint,
    attempt_seq bigint NOT NULL,   -- 同一 session 内单调递增
    snapshot_seq bigint,           -- 这次执行已发布进度的幂等键
    status text NOT NULL,          -- pending | completed | archived | closed
    handle_state text NOT NULL,    -- pending | present | absent
    expects_handle boolean NOT NULL, -- 会产生 provider 句柄时为 true
    depends_on_request_id text REFERENCES v20_operations (request_id), -- 同一 session 里 attempt_seq 更小且 expects_handle = true 的最近一条；没有则为空
    input_message text,
    input_artifact_digest text REFERENCES v20_artifacts (digest),
    input_retained boolean NOT NULL, -- 有输入 digest 时为 true
    payload_digest text NOT NULL,
    result jsonb                  -- T2 写入；pending 时为空
);

CREATE TABLE v20_provider_handle_attempts (
    request_id text PRIMARY KEY REFERENCES v20_operations (request_id),
    attempt_seq bigint NOT NULL,
    epoch_id text REFERENCES v20_epochs (epoch_id),
    handle jsonb NOT NULL
);

CREATE TABLE v20_turns (
    turn_id text PRIMARY KEY,
    request_id text NOT NULL REFERENCES v20_operations (request_id),
    run_id text NOT NULL REFERENCES v20_runs (run_id),
    epoch_id text NOT NULL REFERENCES v20_epochs (epoch_id),
    owner_generation bigint NOT NULL,
    transcript_turn_id text REFERENCES v20_transcript_turns (turn_id),
    status text NOT NULL,
    receipt jsonb
);

CREATE TABLE v20_tool_invocations (
    invocation_id text PRIMARY KEY,
    request_id text NOT NULL REFERENCES v20_operations (request_id),
    run_id text NOT NULL REFERENCES v20_runs (run_id),
    turn_id text NOT NULL REFERENCES v20_turns (turn_id),
    epoch_id text NOT NULL REFERENCES v20_epochs (epoch_id),
    owner_generation bigint NOT NULL,
    tool_name text NOT NULL,
    status text NOT NULL,
    request_digest text,
    result_digest text,
    lease_deadline timestamptz
);

CREATE TABLE v20_events (
    event_id bigserial PRIMARY KEY,
    kind text NOT NULL,
    session_id text,
    run_id text,
    epoch_id text,
    workflow_run_id text,
    digest text,
    message text
);

CREATE INDEX v20_events_session_id_idx ON v20_events (session_id);

CREATE TABLE v20_plan_revisions (
    plan_revision_id text PRIMARY KEY,
    revision bigint NOT NULL,
    status text NOT NULL,
    proposal_digest text
);

CREATE TABLE v20_plan_tasks (
    task_id text PRIMARY KEY,
    plan_revision_id text NOT NULL REFERENCES v20_plan_revisions (plan_revision_id),
    status text NOT NULL,
    workflow_definition_id text,
    workflow_run_id text,
    session_id text
);

CREATE TABLE v20_plan_edges (
    plan_revision_id text NOT NULL REFERENCES v20_plan_revisions (plan_revision_id),
    from_task_id text NOT NULL,
    to_task_id text NOT NULL,
    relation text NOT NULL,
    PRIMARY KEY (plan_revision_id, from_task_id, to_task_id, relation)
);

CREATE TABLE v20_plan_artifacts (
    plan_revision_id text NOT NULL REFERENCES v20_plan_revisions (plan_revision_id),
    digest text NOT NULL REFERENCES v20_artifacts (digest),
    role text NOT NULL,
    PRIMARY KEY (plan_revision_id, digest, role)
);
```

`parent_session_id` 放在 `v20_sessions` 上，是因为 spawn 的授权要用它，而 CE 的 durable metadata 本身不存 parent。界面文档和内存 record 上的那份父指针，在只有一个写入器时就是这一个事实。provider 句柄、名称、工作区留在旁边的表里，fence 不读它们。

`list_hidden` 对应实验里的墓碑。CE 的 `listAgents` 仍会列出已恢复的 metadata。默认列表排除 `list_hidden`。cleanup 把 `state` 设为 `terminal`、`resumable` 设为 false，并在调用方要求隐藏时置上 `list_hidden`。事件和 transcript 留下。

`v20_turns.transcript_turn_id` 可空，外键指向 `v20_transcript_turns`。多个控制 turn 可以指向同一个对话回合。

受保护引用有四类：step 的 `input_artifact_refs` 或 `output_artifact_refs`，`v20_plan_artifacts`，`status = pending` 的 operation 上的 `input_artifact_digest`，以及 `status = archived` 且 `input_retained = true` 的 operation 上的 `input_artifact_digest`。当时仍是 `pending` 的 operation 因 owner 或 epoch 失效标成 `archived` 时，不把 `input_retained` 设为 false，不释放这份 digest。`recover_owner` 对仍需恢复的 pending operation 做的就是这次归档，不改成 `closed`。`cancel` 和 `cleanup` 仍改成 `closed`。已经是 `closed` 的，迟到 T2 只追加一条归档事件，不改成 `archived`，也不把 `input_retained` 设回 true。`completed` 或 `closed` 之后，这条 operation 不再靠自己挡住删除。引用还在时，path 上的字节必须可读，重算 digest 必须与主键一致。判定按 digest 计，不限于导出这份文件的那个 session。path 按 digest 分配。已经发布的路径不可覆盖。第二次导出不同内容必须用另一条路径。文件写入仍在事务外。新的 T1 若沿用仍被旧行保住的 digest，同一事务把新 operation 写成 `pending`，并把旧行的 `input_retained` 设为 false。明确放弃恢复的 `cleanup` 才把本 session 的 `input_retained` 设为 false。在此之前，cleanup 不能删文件。

删字节只发生在事务提交之后。事务里先锁住 artifact 行，确认没有受保护引用，把 `availability` 设为 `unavailable`，提交，然后才删 path 上的字节。有受保护引用时，`cleanup` 不改 `availability`，也不删。`handoff`、会插入 `v20_plan_artifacts` 的 `bind_plan`，以及写入 `input_artifact_digest` 的 T1，锁同一行，并且只在 `availability = available` 时插入引用。先提交的一方生效：引用先提交，`cleanup` 不能删；`cleanup` 先把行标成 `unavailable` 并提交，后来的 handoff、bind_plan 和 T1 被拒绝。`retire_artifact` 也锁这一行。受保护引用还在时它可以把行标成 `unavailable` 并拒绝新的 handoff，字节仍留在 path 上。

## 4. 动词

全部经过 `Control.execute`。幂等键是 `v20_operations.request_id`。重放同一个 `request_id` 返回已提交的那一行；`pending` 时这一行仍带着完整准入输入。恢复执行用新的 `request_id`，不靠重放旧行再开一次尝试。

`start`、`claim_resume`、`steer`、`respond`、`admit_turn`、`admit_tool` 的 T1 必须写下完整准入输入：`input_message`，或已经落盘的 `input_artifact_digest`。同一行还写上 `epoch_id`、当时的 `owner_generation`、`attempt_seq` 和 `status = pending`。只有 `start`、`claim_resume`、`steer`、`respond` 进入句柄等待：`expects_handle = true`，`handle_state = pending`。这四者的 T1 在插入自己的 operation 时，把 `depends_on_request_id` 写成同一 session 里、`attempt_seq` 更小、且 `expects_handle = true` 的最近一条。session 经 `v20_epochs.session_id` 认定。没有前序尝试则为空。事务外只等这一条指定的 `request_id`，不等自己。`depends_on_request_id` 为空就无句柄启动。`admit_turn` 和 `admit_tool` 设 `expects_handle = false`，T1 就把 `handle_state` 设为 `absent`，不写 `depends_on_request_id`。这两条 T1 必须带上调用方的 `epoch_id`。在同一把 run 锁下，这个 `epoch_id` 必须等于当前 epoch，并且 `closed_at` 为空。对不上就拒绝，不插入 pending，也不到事务外执行。不能把旧请求改记到新 epoch 上。`admit_tool` 还要核对关联 turn 的 `run_id` 和 `epoch_id` 与这次准入一致。`attempt_seq` 在这把 run 锁里分配，同一 session 单调递增。请求 activity 在这笔 T1 写入。响应 activity 等 T2。输入若是 artifact，事务外先核对字节与 digest 一致，事务里锁住该行并要求 `availability = available`，然后才写入 `input_artifact_digest`，并把 `input_retained` 设为 true。没有这份 digest 时 `input_retained` 为 false。这个 operation 保持 `pending` 期间，该 digest 是受保护引用。当时仍是 `pending` 的 operation 因 owner 失效标成 `archived` 之后，`input_retained` 仍为 true 时保护继续。已经 `closed` 的不因迟到 T2 改成 `archived`。新的 T1 沿用这个 digest 时，同一事务把新 operation 写成 `pending`，并把旧行的 `input_retained` 设为 false。

| 动词 | 事务里写什么 | 事务外 |
|---|---|---|
| `start` | 插入 session（`state = active`、`resumable = true`）、profile、run（`run_id = session_id`）、`initial` epoch、snapshot=`running`、event。operation 记下这个 epoch、当时的 `owner_generation`、完整 message 或已落盘 artifact 引用、`status = pending`、`expects_handle = true`、`handle_state = pending`、`depends_on_request_id` 为空。把 `owner_backend_pid` 写成调用者的 pid。同一事务写请求 activity | 若带 workflow，先读模板文件并包好 message，再进入事务。事务只记 `definition_id` 和当时的 digest。`depends_on_request_id` 为空，provider 在 T1 提交之后无句柄启动 |
| `claim_resume` | 要求 `resumable = true`。`state = terminal` 且 `resumable = false` 时拒绝，不新建 epoch，也不插入 operation。`alreadyActive` 的条件是：run 仍是 `running` 或 `waiting_for_input`，并且 `owner_backend_pid` 对应的进程还活着。两个条件都成立才拒绝。`recover_owner` 写下的 `expired` run 可以重新激活。通过时用新的 `request_id`。锁 run、旧 epoch 和它上面的 pending operation。session id 与 run id 不变。新 epoch，ordinal 加一。同一事务把旧 epoch 上仍 `pending` 的 operation 改为 `closed`，持有 run 锁，把 `owner_backend_pid` 写成这次调用者的 pid，并使用 `recover_owner` 已经抬高的 `owner_generation`，不另抬 generation。session 设为 `active`，run 设为 `running`，清掉 `interaction` 和 `failure_reason`，并插入一条新的 `pending` operation：完整输入、新 `epoch_id`、这个 `owner_generation`、下一个 `attempt_seq`、`expects_handle = true`、`handle_state = pending`、`depends_on_request_id`（同一 session 里 `attempt_seq` 更小且 `expects_handle = true` 的最近一条，没有则为空），以及请求 activity。关闭还没有 attempt 行的 pending operation 时，同一事务把 `handle_state` 设为 `absent`。同一事务再结算 `status = completed` 且 `handle_state = pending`、并且还没有 attempt 行的 operation：把 `handle_state` 设为 `absent`，status 保持 `completed`。这覆盖完成快照已提交、补写句柄前进程退出。沿用仍被旧行保住的 digest 时，同一事务把旧行的 `input_retained` 设为 false。重放同一个 `request_id` 返回这一行 | 事务提交之后，在事务外只等这一条 `depends_on_request_id`，不等自己。不看 turn 或 tool 的 `attempt_seq`。这一条为空就无句柄启动。`present` 就用那一行句柄再启动 provider。`absent` 就改用更早一次 `expects_handle = true` 且 `present` 的句柄，没有更早的就无句柄启动。`pending` 才继续等这一条。不等一个已经 `absent` 的尝试。不在打开的事务里等 |
| `steer` | CAS `runs.revision` 和 `sessions.revision`。`resumable` 不是 true，或 session 是 cleanup 留下的 `terminal` 且 `resumable = false` 时拒绝，不新建 epoch，也不插入 operation。`owner_generation` 必须匹配当前 run。run 是 `running` 或 `waiting_for_input` 时，和终态 steer 走同一笔事务：关闭旧 epoch（写 `closed_at`），把旧 epoch 上仍 `pending` 的 operation 改为 `closed`，结算还没有 attempt 行的 `handle_state` 为 `absent`，插入新 epoch 和新的 `pending` operation（完整 message 或 artifact 引用、新 `epoch_id`、当时的 `owner_generation`、`expects_handle = true`、`handle_state = pending`、`depends_on_request_id`），run 设为 `running`，清掉 `interaction` 和 `failure_reason`，session id 与 run id 不变。不另抬 `owner_generation`。旧尝试之后的 T2 只归档，不能覆盖新快照。终态（`completed`、`failed`、`cancelled`、`expired`）上用新的 `request_id` 走新 epoch，不新建 run，session id 与 run id 不变。同一事务持有 run 锁，把旧 epoch 上仍 `pending` 的 operation 改为 `closed`，session 设为 `active`，run 设为 `running`，把 `owner_backend_pid` 写成这次调用者的 pid，并使用 `recover_owner` 已经抬高的 `owner_generation`，不另抬 generation，清掉 `interaction` 和 `failure_reason`。T1 插入新的 `pending` operation：完整 message 或 artifact 引用、新 `epoch_id`、这个 `owner_generation`、`expects_handle = true`、`handle_state = pending`、`depends_on_request_id`（同一 session 里 `attempt_seq` 更小且 `expects_handle = true` 的最近一条，没有则为空），并写请求 activity。终态上关闭还没有 attempt 行的 pending operation 时，同一事务把 `handle_state` 设为 `absent`。同一事务再结算 `status = completed` 且 `handle_state = pending`、并且还没有 attempt 行的 operation：把 `handle_state` 设为 `absent`，status 保持 `completed`。沿用仍被旧行保住的 digest 时，同一事务把旧行的 `input_retained` 设为 false。重放同一个 `request_id` 返回已提交的那一行 | 事务提交之后，在事务外只等这一条 `depends_on_request_id`，不等自己。不看 turn 或 tool 的 `attempt_seq`。这一条为空就无句柄启动。`present` 就用那一行句柄再启动 provider。`absent` 就改用更早一次 `expects_handle = true` 且 `present` 的句柄，没有更早的就无句柄启动。`pending` 才继续等这一条。不等一个已经 `absent` 的尝试。不在打开的事务里等 |
| `respond` | 仅当 status 是 `waiting_for_input`。CAS 后把 interaction 清掉，status 回到 `running`。T1 同样固化 epoch、owner generation、下一个 `attempt_seq`、回答正文或 artifact 引用、`pending`、`expects_handle = true`、`handle_state = pending`、`depends_on_request_id`（同一 session 里 `attempt_seq` 更小且 `expects_handle = true` 的最近一条，没有则为空），并写请求 activity | 事务提交之后，在事务外只等这一条 `depends_on_request_id`，不等自己。不看 turn 或 tool 的 `attempt_seq`。这一条为空就无句柄启动。`present` 就用那一行句柄再启动 provider。`absent` 就改用更早一次 `expects_handle = true` 且 `present` 的句柄，没有更早的就无句柄启动。`pending` 才继续等这一条。不等一个已经 `absent` 的尝试。不在打开的事务里等 |
| `publish_snapshot` | 锁 run、epoch 和 T1 operation。operation 仍是 `pending`，固化的 owner generation 仍等于 run，固化的 epoch 仍是当前 epoch 且 `closed_at` 为空，并且这条 run 迁移允许，才写入。三种 T2 共用的只有 request 关联、owner fence、epoch 和 operation 状态。进度是 `running` 到 `running`：只更新预览和 `snapshot_seq`，operation 保持 `pending`，不改 `handle_state`，`result` 仍为空。已经是 `present` 或 `absent` 的不能改回 `pending`。`snapshot_seq` 记在这条 operation 上，是这次进度的幂等键。重试同一 `snapshot_seq` 返回已提交的进度，不另写一份。更大的 seq 才更新预览。更小的 seq 不覆盖已发布的进度。只有最终回执 `waiting_for_input`、`completed`、`failed` 才更新 status、interaction、failure，并把 operation 标为 `completed`。可恢复的完成把 session `state` 写成 `dormant`，`resumable` 保持 true。run 的状态迁移只由 `publish_snapshot` 负责。允许的迁移只从 `running` 到 `running`、`waiting_for_input`、`completed` 或 `failed`。`accept_turn_receipt` 和 `accept_tool_result` 不使用这条迁移，也不因局部调用完成而自动终结 run。`cancelled`、`completed`、`failed`、`expired`，或 session 已是 `terminal`，都不改当前快照。离开这些终态只发生在 `claim_resume` 或终态 `steer` 的新 epoch 事务里，那时 run 已经是 `running`，这条 T2 仍不从旧终态直接改写。只认这次准入插入的那条仍 `pending` 的 operation。旧 epoch 上已 `closed` 的行只追加归档事件，status 保持 `closed`，不把 `input_retained` 设回 true。`running` 或 `waiting_for_input` 上的 `steer` 已在同一事务把 run 设为 `running` 并关闭旧 epoch。旧尝试之后的 T2 只归档，不能覆盖新快照。同一笔 T2 可以同时更新当前 provider 句柄。同一 `request_id` 已是 `completed`，且 epoch 未关闭、owner 匹配、回执对得上时，原样返回已提交的 `result`，不改成 `archived`，也不重写 `result`。回执上的 `request_id` 必须等于这条 operation 的 `request_id`。对不上时只记一条归档事件，不修改任何 pending 的 operation、turn 或 invocation。当时仍是 `pending`、且 owner 或 epoch 失效，才把这一条 operation 标为 `archived`，并保持 `input_retained`，不释放 `input_artifact_digest`。已经是 `closed` 时，只追加一条归档事件，不把 status 改成 `archived`，也不把 `input_retained` 设回 true。最终回执的 `result` 明确没有句柄且没有 attempt 行时，同一事务把 `handle_state` 设为 `absent` | provider 已返回 |
| `admit_turn` / `accept_turn_receipt` | T1 按 run、epoch、operation 的顺序加锁。T1 必须带上调用方的 `epoch_id`。在同一把 run 锁下，这个 `epoch_id` 必须等于当前 epoch，并且 `closed_at` 为空；run 必须是 `running` 或 `waiting_for_input`，调用方 `owner_generation` 必须等于当前值。对不上就拒绝，不插入 pending，也不到事务外执行。不能把旧请求改记到新 epoch 上。通过才插入 `v20_turns`，行上写下 `request_id`、当时的 `epoch_id`、`owner_generation` 和可选的 `transcript_turn_id`，operation 为 `pending`，`expects_handle = false`，T1 就把 `handle_state` 设为 `absent`，并带上完整准入输入。两个控制 turn 可以填同一个 `transcript_turn_id`。T2 与 `publish_snapshot`、`accept_tool_result` 共用的只有 request 关联、owner fence、epoch 和 operation 状态：回执 `request_id` 必须等于这一行的 `request_id`；operation 仍是 `pending`，或同一 `request_id` 已是 `completed`；固化的 owner generation 仍等于 run；固化的 epoch 仍是当前 epoch 且 `closed_at` 为空。对不上 `request_id` 时只记一条归档事件，不修改任何 pending 的 operation、turn 或 invocation。同一 `request_id` 已是 `completed`，且 epoch 未关闭、owner 匹配、回执对得上时，原样返回已存储结果，不改成 `archived`。当时仍是 `pending`、且 owner 或 epoch 失效，才归档这一条 operation，并保持 `input_retained`，不改其他 pending 行。已经是 `closed` 时只追加归档事件，不把 `input_retained` 设回 true。通过后结算自己的 operation、这一行 turn 和响应投影，把 operation 标为 `completed`。不改 `v20_runs.status`，不改 `interaction`，不改 `failure_reason`，也不把 session 写成 `dormant`。不因这次局部调用完成而自动终结 run。run 已是 `waiting_for_input` 时仍可提交，原 `interaction` 保留 | T1 拒绝时不到事务外执行。通过后 Worker 调用在两笔事务之间 |
| `admit_tool` / `accept_tool_result` | T1 按 run、epoch、operation 的顺序加锁。T1 必须带上调用方的 `epoch_id`。在同一把 run 锁下，这个 `epoch_id` 必须等于当前 epoch，并且 `closed_at` 为空；run 必须是 `running` 或 `waiting_for_input`，调用方 `owner_generation` 必须等于当前值。对不上就拒绝，不插入 pending，也不到事务外执行。不能把旧请求改记到新 epoch 上。还要核对关联 turn 的 `run_id` 和 `epoch_id` 与这次准入一致。对不上同样拒绝，不插入 pending，也不启动工具进程。通过才插入 `v20_tool_invocations`，写上 `request_id`，固化调用方的 `epoch_id` 和 `owner_generation`，写下完整准入输入和请求投影。operation 设 `expects_handle = false`，T1 就把 `handle_state` 设为 `absent`。T2 与 `publish_snapshot`、`accept_turn_receipt` 共用的只有 request 关联、owner fence、epoch 和 operation 状态：回执 `request_id` 必须等于这一行的 `request_id`；operation 仍是 `pending`，或同一 `request_id` 已是 `completed`；固化的 owner generation 仍等于 run；固化的 epoch 仍是当前 epoch 且 `closed_at` 为空。对不上 `request_id` 时只记一条归档事件，不修改任何 pending 的 operation、turn 或 invocation。同一 `request_id` 已是 `completed`，且 epoch 未关闭、owner 匹配、回执对得上时，原样返回已存储结果，不改成 `archived`。当时仍是 `pending`、且 owner 或 epoch 失效，才归档这一条 operation，并保持 `input_retained`，不改其他 pending 行。已经是 `closed` 时只追加归档事件，不把 `input_retained` 设回 true。通过后结算自己的 operation、这一行 invocation 和响应投影，把 operation 标为 `completed`。不改 `v20_runs.status`，不改 `interaction`，不改 `failure_reason`，也不把 session 写成 `dormant`。不因这次局部调用完成而自动终结 run。run 已是 `waiting_for_input` 时仍可提交，原 `interaction` 保留。同一 epoch 的其他 pending 调用保持 pending，第一个回执不阻止第二个结算 | T1 拒绝时不启动工具进程。通过后工具进程在两笔事务之间 |
| `append_transcript` | 请求 activity 属于 T1。响应 activity 和 span 属于校验通过的 T2。它不是第二个写入器 | |
| `record_provider_handle` | 沿用这次 provider 调用的 `request_id` 和它的 `attempt_seq`，不另开 operation。`request_id` 对得上就写入 `v20_provider_handle_attempts`，并把该 operation 的 `handle_state` 改为 `present`，即使该 epoch 已经不是当前 epoch。可与 `publish_snapshot` 在同一笔 T2 提交。`v20_session_provider_handles` 仍只在传入 seq 大于或等于已存 seq、且该 epoch 仍是当前 epoch、`closed_at` 为空、owner generation 匹配、operation 是 `pending` 或已是 `completed` 时更新。更小的 seq 不覆盖当前行。operation 已是 `completed` 时，status 和 `result` 保持不动 | provider 已返回句柄 |
| `admit_workflow_run` | 插入 workflow run。不修改 session 行去指向它 | |
| `handoff` / `add_step` | 必须带 `expected_workflow_revision`。调用方不得自带 `seq`。事务内先按本步要写入的 `run_id`、`epoch_id` 加 `FOR UPDATE`（没有这两列才从 workflow 开始），再锁 `v20_workflow_runs` 核对 revision。匹配后在这把锁里取 `COALESCE(MAX(seq), -1) + 1`，按 digest 排序锁 artifact，要求 `availability = available`。同一事务插入 step，并把 workflow revision 加一。不匹配返回 `RevisionConflict`，不插 step。`open_workflow_run` 只把 revision 置为 1。`bind_plan` 不分配 seq | 插入前按 digest 读 path 并重算。事务内不读文件。重放同一 `request_id` 返回已提交行 |
| `export_artifact` | 插入 artifact 行，`path` 按 digest 分配，`availability = available`。已发布的路径不可覆盖 | 事务外把字节写到按 digest 分配的路径。不同内容使用另一条路径 |
| `retire_artifact` | 锁住 artifact 行，把 `availability` 设为 `unavailable`。受保护引用还在时，path 上的字节保留。此后新的 handoff 拒绝该 digest | 不在事务里删文件 |
| `bind_plan` | plan revision、task、edge。插入 plan artifact 时锁住同一 artifact 行，`availability` 必须是 `available`。`unavailable` 则拒绝这条新引用 | 计划正文已经在文件里 |
| `recover_owner` | 旧 pid 已死时抬高 owner generation 和 registration generation，不安装新 pid。run 仍是 `running` 或 `waiting_for_input` 时，同一事务把 run status 改为 `expired`，session state 改为 `interrupted`，`resumable` 保持 true，并关闭当前 epoch：写 `closed_at`。仍需恢复的 pending operation 改成 `archived`，`input_retained` 保持 true，不改成 `closed`。按已有规则结算 `handle_state`：还没有 attempt 行且 `handle_state = pending` 的改为 `absent`；`status = completed` 且还没有 attempt 行的，`handle_state` 设为 `absent`，status 保持 `completed`。此后 `claim_resume` 可以把这个 expired run 重新激活。新的 `claim_resume` T1 沿用 digest 时，再在同一事务把保护转到新的 pending operation | 不在事务里探测进程以外的 IO |
| `cleanup` | `terminal`、`resumable = false`，可选 `list_hidden`，追加 event。此后本 session 的 `claim_resume` 和 `steer` 拒绝，不新建 epoch。同一事务关闭本 session 当前 epoch：写 `closed_at`，把该 epoch 上 `pending` 的 operation 改为 `closed`。还没有 attempt 行的，同一事务把 `handle_state` 设为 `absent`。本 session 明确放弃恢复，同一事务把本 session operation 的 `input_retained` 设为 false。run 若仍是 `running` 或 `waiting_for_input`，把 `v20_runs.status` 改为 `cancelled` 并推进 `revision`。删本 session 导出的文件前，锁 artifact 行，确认没有受保护引用，把 `availability` 设为 `unavailable`。`input_retained` 仍为 true 时不删文件。别的 session 上仍 `pending` 的输入，以及 `archived` 且 `input_retained = true` 的输入，都算受保护引用 | 只删除这笔事务已经提交为 `unavailable`、且当时没有受保护引用的字节。事务内不删文件。提交后 NOTIFY，`wait` 重查能看到新 revision |
| `cancel` | 与完成 T2 一样先锁 run。只在 status 是 `running` 或 `waiting_for_input` 时，改为 `cancelled`，写上 `closed_at`，并把该 epoch 上 `pending` 的 operation 改为 `closed`。还没有 attempt 行的，同一事务把 `handle_state` 设为 `absent`。已经是 `completed`、`failed`、`expired` 或 `cancelled` 时不改 status，不写 `closed_at`，返回当前状态。不改 owner generation，不换 epoch，不换 run id，不把 `resumable` 设为 false，也不把 session 设为 `terminal` | 取消进程在提交之后或提交之前都可以，不在打开的事务里等。进程取消不代替这笔作废 |

`cancel` 和 `cleanup` 关闭的是当前 epoch，不改 `owner_generation`，也不新开 epoch。同一事务里写 `closed_at`，并把该 epoch 上 `pending` 的 operation 改为 `closed`。锁的顺序是 run、epoch、operation、artifact。T2 用同一顺序。插入 `v20_workflow_steps` 时，这一行若带 `run_id` 或 `epoch_id`，先锁 run，再锁 epoch，然后锁 workflow，再按 digest 排序锁 artifact。两列都空才从 workflow 开始。`v20_workflow_steps.run_id` 和 `epoch_id` 的外键会在插入时取 `KEY SHARE`，所以绑定执行会话的 `handoff` 和 `add_step` 也要先锁这两行，不能在持有 workflow 锁之后才去等 run。关闭先提交，这个 epoch 上后来的 T2 看到 operation 已经是 `closed` 或 epoch 已关闭，只追加一条归档事件，不把 status 改成 `archived`，也不把 `input_retained` 设回 true，也不把当前快照从 `cancelled` 或 session 的 `terminal` 改走。

`claim_resume` 和终态上的 `steer` 另开一笔准入，用新的 `request_id`。session 要 `resumable = true`，并且不是 cleanup 留下的 `terminal` 加 `resumable = false`。`alreadyActive` 的条件是：run 仍是 `running` 或 `waiting_for_input`，并且 `owner_backend_pid` 对应的进程还活着。两个条件都成立才拒绝。`recover_owner` 写下的 `expired` run 可以重新激活。`claim_resume` 和终态 `steer` 在把 run 设回 `running` 的同一事务里持有 run 锁，把 `owner_backend_pid` 写成这次调用者的 pid，并使用 `recover_owner` 已经抬高的 `owner_generation`，不另抬 generation。`recover_owner` 不安装新 pid。两个调用者同时 `claim_resume` 时，一个提交并启动，另一个看到活 owner 被拒绝，不新建 epoch。同一事务里插入新 epoch，把旧 epoch 上仍 `pending` 的 operation 改为 `closed`。这些还没有 attempt 行的，`handle_state` 设为 `absent`。同一事务再结算 `status = completed` 且 `handle_state = pending`、并且还没有 attempt 行的 operation：把 `handle_state` 设为 `absent`，status 保持 `completed`。再插入一条新的 `pending` operation：完整输入、新的 `epoch_id`、当时的 `owner_generation`、`expects_handle = true`、`handle_state = pending`、`depends_on_request_id`（同一 session 里 `attempt_seq` 更小且 `expects_handle = true` 的最近一条，没有则为空）。沿用 `recover_owner` 归档行上的 digest 时，同一事务把保护转到这条新 operation，并把旧行的 `input_retained` 设为 false。插入新 epoch 不等句柄。旧行不能再拿来做 T2。session 设为 `active`，run 设为 `running`，清掉 `interaction` 和 `failure_reason`。session id 和 run id 不变。`publish_snapshot` 只认这条新 operation。重放刚才那个 `request_id` 返回已提交的行；再次执行用另一个新 `request_id`。`cancel` 只关闭当前 epoch，不把 `resumable` 设为 false；之后合法的 steer 可以再开 epoch 并重新激活。cleanup 之后的 session，resume 和 steer 都拒绝，不新建 epoch。

`steer` 在 run 是 `running` 或 `waiting_for_input` 时不按 `alreadyActive` 拒绝，和终态 `steer` 走同一笔事务：关闭旧 epoch，把旧 epoch 上仍 `pending` 的 operation 改为 `closed`，结算还没有 attempt 行的 `handle_state` 为 `absent`，插入新 epoch 和新的 `pending` operation，run 设为 `running`，清掉 `interaction` 和 `failure_reason`，session id 与 run id 不变。旧尝试之后的 T2 只归档，不能覆盖新快照。终态 `steer` 的规则保持不变。

`admit_turn` 和 `admit_tool` 的 T1 与 `cancel` 用同一锁顺序：run、epoch、operation。T1 必须带上调用方的 `epoch_id`。在同一把 run 锁下，这个 `epoch_id` 必须等于当前 epoch，并且 `closed_at` 为空；run 必须是 `running` 或 `waiting_for_input`，调用方 `owner_generation` 必须等于当前值。对不上就拒绝，不插入 pending，也不到事务外执行。不能把旧请求改记到新 epoch 上。`admit_tool` 还要核对关联 turn 的 `run_id` 和 `epoch_id` 与这次准入一致。对不上同样拒绝。T1 把 `request_id` 写进 turn 或 invocation。T2 先核对回执上的 `request_id` 是不是目标 turn 或 invocation 的 `request_id`。对不上时只把这次回执记成归档事件，不修改任何 pending 的 operation、turn 或 invocation。对上之后做这三种 T2 共用的 owner fence、epoch 和 operation 状态检查，不使用 `publish_snapshot` 的 run 迁移。通过后 `accept_turn_receipt` 和 `accept_tool_result` 结算自己的 operation、turn 或 invocation 和响应投影，把 operation 标为 `completed`。不改 `v20_runs.status`，不改 `interaction`，不改 `failure_reason`。run 已是 `waiting_for_input` 时仍可提交，原 `interaction` 保留。同一 epoch 的其他 pending 调用保持 pending。当时仍是 `pending`、且 owner 或 epoch 失效，才归档那一条 operation，并保持 `input_retained`，不释放 `input_artifact_digest`。已经是 `closed` 时只追加归档事件，不把 `input_retained` 设回 true。cancel 先提交，随后的 admit 被拒绝。admit 先提交，cancel 把这条 operation 改为 `closed`，迟到 T2 只追加归档事件。

`record_provider_handle` 只要 `request_id` 对得上，就把句柄写入 `v20_provider_handle_attempts`，并把该 operation 的 `handle_state` 改为 `present`，即使该 epoch 已经不是当前 epoch。`v20_session_provider_handles` 仍只在传入 seq 大于或等于已存 seq、且该 epoch 仍是当前 epoch 时更新。更小的 seq 不覆盖当前行。快照和句柄仍可以在同一笔 T2 里提交。operation 已是 `completed` 时，补写不改 status，也不改 `result`。

`start`、`claim_resume`、`steer`、`respond` 的 T1 把 `depends_on_request_id` 写成同一 session 里、`attempt_seq` 更小、且 `expects_handle = true` 的最近一条。没有前序尝试则为空。新的 provider 调用在事务外只等这一条指定的 `request_id`，不等自己，也不是 `v20_session_provider_handles` 的当前行。`depends_on_request_id` 为空就无句柄启动。这一行 `present` 就用 `v20_provider_handle_attempts` 的那一行。`absent` 表示不会再有生产者，改用更早一条 `expects_handle = true` 且 `present` 的句柄；没有更早的就无句柄启动。`pending` 才继续等这一条。不能无限等一个已经 `absent` 的尝试。`claim_resume` 先插入新 epoch，不为了等句柄而推迟这一笔。这一等在 T1 提交之后、事务外进行。快照已 `completed` 且 `result` 明确没有句柄、又没有 attempt 行时，同一事务把 `handle_state` 设为 `absent`。`claim_resume`、终态 `steer`，以及 run 仍是 `running` 或 `waiting_for_input` 的 `steer`，在同一事务里关闭旧 epoch 上仍 `pending` 的 operation，并把还没有 attempt 行、`handle_state = pending` 的设为 `absent`。`recover_owner` 不把仍需恢复的 pending operation 改成 `closed`，而是改成 `archived`，`input_retained` 保持 true，同时结算 `handle_state`。`status = completed` 且 `handle_state = pending`、并且还没有 attempt 行的，`handle_state` 设为 `absent`。这覆盖完成快照已提交、补写句柄前进程退出。

同一 `request_id` 的 T2 再交一次时，若 operation 已是 `completed`，且 epoch 未关闭、owner 匹配、回执对得上，原样返回已提交的 `result`。不把这一行改成 `archived`，也不重写 `result`。回执上的 `request_id` 对不上目标 turn 或 invocation 时，只记一条归档事件，不修改任何 pending 的 operation、turn 或 invocation。当时仍是 `pending`、且 owner 或 epoch 失效，才归档那一条 operation，并保持 `input_retained`，不释放 `input_artifact_digest`。已经是 `closed` 时只追加一条归档事件，不把 status 改成 `archived`，也不把 `input_retained` 设回 true。

`publish_snapshot` 分成进度和结算。`running` 到 `running` 的进度发布只更新预览和 `snapshot_seq`，不把 operation 标成 `completed`，也不改 `handle_state`。已经是 `present` 或 `absent` 的不能改回 `pending`。`snapshot_seq` 是这次进度的幂等键，重试同一 seq 不另写一份。只有最终回执 `waiting_for_input`、`completed`、`failed` 才把这条 operation 标成 `completed`，并更新 run 的 status、interaction、failure。可恢复的完成把 session `state` 写成 `dormant`，`resumable` 保持 true。`publish_snapshot`、`accept_turn_receipt`、`accept_tool_result` 共用的只有 request 关联、owner fence、epoch 和 operation 状态。run 的状态迁移只由 `publish_snapshot` 负责。`accept_turn_receipt` 和 `accept_tool_result` 结算自己的 operation、turn 或 invocation 和响应投影，不改 `v20_runs.status`，不改 `interaction`，不因局部调用完成而自动终结 run。run 已是 `waiting_for_input` 时，这两条回执仍可提交。

`cancel` 与完成 T2 争同一把 run 锁。完成先提交，随后的 `cancel` 看到 `completed`，status 保持不变。`cancel` 先提交，随后的 T2 只追加归档事件，operation 保持 `closed`，不把 `input_retained` 设回 true，run status 保持 `cancelled`。

运行中的 `cleanup` 在关闭 epoch 的同一事务里，若 run 还是 `running` 或 `waiting_for_input`，把 `v20_runs.status` 改为 `cancelled`，推进 `revision`，提交后 NOTIFY。session 仍是 `terminal`，`resumable` 仍是 false。`poll` 读到的 status 不再是 `running`。`wait` 重查能看到这次 revision。

删文件时锁住 artifact 行。没有受保护引用才把 `availability` 改成 `unavailable` 并提交，字节在这次提交之后才删除。`archived` 且 `input_retained = true` 时，cleanup 不删该文件。`handoff`、新增 plan artifact 的 `bind_plan`，以及写入 `input_artifact_digest` 的 T1，锁同一行。引用先提交，cleanup 就不能删。`unavailable` 先提交，后来的引用被拒绝。

`poll` 只读 run 快照。`wait` 先在自己的连接上 `LISTEN` 并提交，再读权威 revision。读完之后这条连接上没有打开的事务。`NOTIFY` 的载荷可以是 `run_id|revision`，收到之后只按 `run_id` 重查。等待有超时或周期重查；通知没送到时，以重查读到的 revision 为准。

一次编排在这套表上的走法：

1. 父 session `start`。T1 把完整 message 写入 operation（`pending`）和请求 activity。若 message 使用 orchestrate 模板，activity 记下 `builtin-orchestrate`。这一步没有 workflow run。
2. 计划文件在事务外写成 `prompt-exports/...`。`export_artifact` 记下 digest 和 path，`availability = available`。
3. 需要多步跟踪时，`admit_workflow_run` 建实例，revision 从 1 起。`handoff` 带上当时的 `expected_workflow_revision`，把 digest 放进 step 0 的输出。handoff 要求该行仍是 `available`，并且事务外已经核对过 path 上的字节。空 workflow 的第一步 `seq = 0`。
4. 子 agent `start`，`parent_session_id` 指向父 session。子 message 里仍带文件路径，CE 的 `read_file` 交接保留。step 1 的 `input_artifact_refs` 是同一个 digest。父 session 之后 `cleanup` 把父会话标成 terminal，并关闭父 epoch 上尚未完成的 T2。仍被 step、plan 或别的 pending operation 引用的文件不删。
5. 宏观计划用 `v20_plan_tasks` 指向 definition、workflow run 和执行 session。session 行本身仍然不指向计划。

### 4.1 显式续接 workflow

只有调用方显式传入 `workflow_run_id` 的 `claim_resume`，以及显式传入 `workflow_run_id` 的终态 `steer`（run 已是 `completed`、`failed`、`cancelled` 或 `expired`），才承接已提交 refs。不带 `workflow_run_id` 的 `claim_resume` 和 `steer` 不插入 `v20_workflow_steps`。run 仍是 `running` 或 `waiting_for_input` 的 `steer` 即使带了 `workflow_run_id` 也拒绝：不关 epoch，不插 operation，不插 step，不改 workflow revision。

事务外读取该 workflow 已提交步骤的 `input_artifact_refs` 和 `output_artifact_refs`，按 digest 去重并按字典序排列，再读 path 重算。不一致或缺失就拒绝，不开事务。没有已提交步骤时 refs 为空集，仍然插入一行输入为空的 step。

事务内锁顺序是 run、旧 epoch、该 epoch 上的 operation、`v20_workflow_runs`、artifact，都用 `FOR UPDATE`，多个 artifact 按 digest 排序。`workflow revision` 必须仍等于 `expected_workflow_revision`。每个 digest 都要有行且 `availability = available`。在 workflow 行锁内分配 `seq = COALESCE(MAX(seq), -1) + 1`。调用方不得自带 `seq`。同一事务完成原有的新 epoch 和新 pending operation，并插入一行 `v20_workflow_steps`：输入是排好序的 refs，输出为空，`session_id` 与 `run_id` 仍是原会话，`epoch_id` 是新 epoch，`status = ready`。workflow revision 加一。任一检查失败整笔回滚，不留新 epoch、operation 或 step。不插入新的 `v20_runs` 行。这一行 step 是新的受保护引用，不替换该 operation 自己的 `input_message` 或 `input_artifact_digest`。

同一 `expected_workflow_revision` 的两个并发写 step 只能一个提交。失败方返回 `RevisionConflict`，不得以 deadlock 代替。重放同一 `request_id` 返回已提交行，不再插第二个 step。

## 5. 事务边界

沿用章程 `:266`–`:278`：

```text
T1 admission commit
  写入 request_id、当时的 owner_generation、epoch_id、
  完整准入输入（input_message 或已落盘的 input_artifact_digest）、
  operation status = pending，以及请求 activity
  start、claim_resume、steer、respond：expects_handle = true，handle_state = pending
  depends_on_request_id = 同一 session 里 attempt_seq 更小且 expects_handle = true 的最近一条
  没有前序尝试则为空；事务外只等这一条，不等自己；为空就无句柄启动
  admit_turn、admit_tool：expects_handle = false，handle_state = absent，不写 depends_on_request_id
  调用方 epoch_id 必须等于当前 epoch，且 closed_at 为空；对不上就拒绝
  不插入 pending，也不到事务外执行；不能把旧请求改记到新 epoch
  admit_tool 还核对关联 turn 的 run_id 和 epoch_id 与这次准入一致
  输入若是 artifact：事务外已核对字节与 digest，事务内锁行且 availability = available
  input_retained = true；没有这份 digest 时 input_retained = false
  沿用一条 archived 且 input_retained = true 的 digest 时，
  同一事务把旧行的 input_retained 设为 false
  → 事务外的 provider、工具、读模板、写导出文件
  → T2：锁 run、epoch 和 T1 operation
    三种 T2 共用的只有 request 关联、owner fence、epoch、operation 状态
    operation 仍是 pending，或同一 request_id 已是 completed
    epoch.closed_at 为空
    固化的 owner_generation 仍等于 run，固化的 epoch 仍是当前 epoch
    先核对回执上的 request_id
    publish_snapshot：必须等于这条 operation 的 request_id
    accept_turn_receipt / accept_tool_result：必须等于目标 turn 或 invocation 的 request_id
    对不上：只记一条归档事件，不修改任何 pending 的 operation、turn 或 invocation
    对上，且 operation 仍是 pending，epoch.closed_at 为空
    固化的 owner_generation 仍等于 run，固化的 epoch 仍是当前 epoch
    同一 request_id 已是 completed，且 epoch 未关闭、owner 匹配、回执对得上：
      原样返回已存储的 result，不改 status，不改成 archived，不重写 result
    当时仍是 pending，且 owner 或 epoch 失效：把那一条改为 archived，保持 input_retained，不释放 input_artifact_digest
    不改其他 pending 行，也不更新当前快照
    已经是 closed：只追加一条归档事件，status 保持 closed，不把 input_retained 设回 true
    run 的状态迁移只由 publish_snapshot 负责
    进度（running → running）：只更新预览和 snapshot_seq，不改 handle_state
    operation 保持 pending，result 仍为空
    已经是 present 或 absent 的不能改回 pending
    同一 snapshot_seq 再交一次：返回已提交的进度，不另写一份
    最终回执（waiting_for_input、completed、failed）只由 publish_snapshot 写 run：
    才更新 status、interaction、failure，并写 snapshot
    这条 operation 改为 completed，并写响应 activity
    可恢复的完成：session state = dormant，resumable 保持 true
    最终回执的 result 明确没有句柄且没有 attempt 行：同一笔把 handle_state 设为 absent
    同一笔里可以写入 attempt 句柄，并把 handle_state 设为 present
    当前行仍要求 epoch 是当前 epoch 且 seq 不倒退
    允许的迁移只从 running 到 running、waiting_for_input、completed 或 failed
    accept_turn_receipt / accept_tool_result 不使用这条 run 迁移：
    结算自己的 operation 为 completed，写入 turn 或 invocation 的回执和响应投影
    不改 v20_runs.status，不改 interaction，不改 failure_reason
    不把 session 写成 dormant，不因局部调用完成而自动终结 run
    run 已是 waiting_for_input 时仍可提交，原 interaction 保留
    同一 epoch 的其他 pending 调用保持 pending，第一个回执不阻止第二个结算
  → best-effort NOTIFY（等待方只把它当作重查信号）
```

打开的事务里拒绝模型调用、文件读和文件写。模板正文和计划正文都走这条边界。库里留 digest 和 path。带正文的准入还在 T1 留下 `input_message` 或 artifact 引用。字节是否与 digest 一致，在打开事务之前核对。

T1 提交之后进程可以退出。恢复按 `request_id` 读到 `pending` 的 operation：epoch、owner generation 和完整输入都在，请求 activity 已经提交。响应 activity 要等 T2。重放同一个 `request_id` 返回这一行。这一行若已是 `closed`、`completed` 或 `archived`，重放仍只返回它。继续执行用新的 `request_id`。快照仍是 `running` 时，先由 `recover_owner` 写成 `expired`。仍需恢复的 pending operation 改成 `archived`，`input_retained` 保持 true，不改成 `closed`。再由 `claim_resume` 或终态 `steer` 插入新的 pending operation。新的 `claim_resume` T1 沿用 digest 时，同一事务把保护转到新的 pending operation。`recover_owner` 抬高 generation 之后，旧 operation 上固化的 generation 不再满足 T2，也不能靠重放同一个 `request_id` 开新尝试。输入若是 `input_artifact_digest`，T1 把 `input_retained` 设为 true。`pending` 期间，以及 owner 失效后标成 `archived` 且 `input_retained` 仍为 true 时，都挡住导出方的 cleanup。重启之后 path 上的字节仍在，digest 重算一致。新的 T1 沿用这个 digest 时，同一事务把新 operation 写成 `pending`，并把旧行的 `input_retained` 设为 false。`cleanup` 明确放弃本 session 的恢复时，才把本 session 的 `input_retained` 设为 false；在此之前不删文件。进入 `completed` 或 `closed` 之后，这条 operation 不再靠 `input_retained` 挡住删除。删除仍要先锁行、确认没有受保护引用、标成 `unavailable` 并提交。

`cancel` 与 `cleanup` 在事务里关闭当前 epoch：写 `closed_at`，并把该 epoch 上 pending 的 operation 改为 `closed`。还没有 attempt 行的，同一事务把 `handle_state` 设为 `absent`。owner generation 和 epoch id 保持不变。被关闭的那个 epoch 上随后到达的 T2 只追加一条归档事件，operation 保持 `closed`，不把 `input_retained` 设回 true，也不改当前快照。`cancel` 只在 run 处于 `running` 或 `waiting_for_input` 时改成 `cancelled`，并与完成 T2 先锁同一条 run。已经是 `completed`、`failed`、`expired` 或 `cancelled` 时不改 status，返回当前状态。`cancel` 不改 `resumable`。`cleanup` 看到 run 仍是 `running` 或 `waiting_for_input` 时，同一事务把 `v20_runs.status` 改为 `cancelled` 并推进 `revision`，提交后 NOTIFY。session 保持 `terminal`，`resumable` 保持 false。新 epoch 把 run 设回 `running` 是另一笔准入，不走这条归档。

`request_id` 对得上时，句柄写入 `v20_provider_handle_attempts`，并把 `handle_state` 改为 `present`，即使 epoch 已经不是当前 epoch。当前行仍只在 seq 大于或等于已存 seq、且 epoch 仍是当前 epoch 时更新。补写已 `completed` 的 operation 不改 status，也不改 `result`。下一次 provider 调用在事务外只等自己 T1 写下的 `depends_on_request_id`，不等自己。这一条是同一 session 里、`attempt_seq` 更小、且 `expects_handle = true` 的最近一条。`depends_on_request_id` 为空就无句柄启动。`present` 用那一行，`absent` 改用更早一条 `expects_handle = true` 且 `present` 的句柄，没有更早的就无句柄启动，`pending` 才继续等这一条。不看 turn 或 tool 的 `attempt_seq`，也不看自己这条 operation。不能无限等一个已经 `absent` 的尝试。`claim_resume` 插入新 epoch 不等句柄。快照已 `completed` 且明确没有句柄、又没有 attempt 行时，`handle_state` 设为 `absent`。`claim_resume`、终态 `steer`，以及 run 仍是 `running` 或 `waiting_for_input` 的 `steer`，在同一事务里关闭旧 epoch 上仍 `pending` 的 operation，并把还没有 attempt 行、`handle_state = pending` 的设为 `absent`。`recover_owner` 不把仍需恢复的 pending operation 改成 `closed`，而是改成 `archived`，`input_retained` 保持 true，同时结算 `handle_state`。`status = completed` 且 `handle_state = pending`、并且还没有 attempt 行的，`handle_state` 设为 `absent`。

同一 `request_id` 的 T2 在 operation 已是 `completed` 时原样返回已提交的 `result`。回执对不上目标 turn 或 invocation 时，只记归档事件，不改 pending 行。当时仍是 `pending`、且 owner 或 epoch 失效，才把那一条 operation 改成 `archived`，并保持 `input_retained`，不释放 `input_artifact_digest`。已经是 `closed` 时只追加一条归档事件，不把 status 改成 `archived`，也不把 `input_retained` 设回 true。成功行仍不改。`recover_owner` 在旧 pid 已死、且 run 仍是 `running` 或 `waiting_for_input` 时，同一事务抬高 generation，把 run status 改为 `expired`，session state 改为 `interrupted`，`resumable` 保持 true，关闭当前 epoch，把仍需恢复的 pending operation 改成 `archived`，`input_retained` 保持 true，并按已有规则结算 `handle_state`。`cancel` 和 `cleanup` 仍把 operation 改成 `closed`。迟到 T2 不能把 `closed` 改回 `archived`。此后 `claim_resume` 可以把这个 expired run 重新激活。新的 `claim_resume` T1 沿用 digest 时，同一事务把保护转到新的 pending operation。`alreadyActive` 的条件是：run 仍是 `running` 或 `waiting_for_input`，并且 `owner_backend_pid` 对应的进程还活着。最终 T2 把可恢复的完成写成 session `state = dormant`，`resumable` 保持 true。这只由 `publish_snapshot` 的可恢复完成写入。turn 或 tool 回执不改 run，也不写 `dormant`。

`wait` 使用单独的连接。先 `LISTEN` 并提交，让监听生效，再读 run 上的权威 revision，然后才进入等待。等待期间这条连接上没有打开的事务。收到 `NOTIFY` 就按 `run_id` 重查，不把载荷当成新事实。等待带超时，超时后重查；也可以按周期重查。监听建立之前已经提交的更新，由这次权威读看见。通知丢失之后，超时或周期查询仍看见新 revision。

并发 steer 对同一个 `expected_revision`：一个提交，一个冲突。冲突不插入 epoch。

## 6. 这一版故意不收的 CE 字段

- `AgentSession.items`：注释写明新持久化把它存空，从 transcript 重建。
- transcript 的视口、分组缓存、渲染块，以及 span 上那个不进 `Codable` 的 `fullRenderGroupedHistoryCache`。
- `AgentSessions/AgentSessionIndex.json`。它是列表投影。设计五用 `v20_sessions` 加 profile 查询代替这份索引文件。
- 内存里的 `selectedWorkflow`。落库的是已经发出的那条 activity。
- `agent-sessions.json` 的整文件 CAS。行级 `revision` 是它在 PostgreSQL 里的对应物。
- oversight 的 auto-wake 集合、session link 的待发队列。要做监督时再加表，不放进 session 身份行。
- worktree 绑定文件。快照需要绑定摘要时由插件给出，不放进 `v20_sessions`。
- `DomainWorkspaceDocument`（`DomainWorkspaceModels.swift:167`）。WorkspaceContext 继续是插件，输出带 digest 的 artifact。章程 `:361`–`:380` 已是这个边界。

## 7. 下一轮实验要证明的行为

库可以是本机的独立数据库，写法与 `ce_facades_r2` 相同：一个 `Control.execute`，Fake 模型，事务内探针拒绝真 IO。

- 没有 workflow run 的 session 可以 start、steer、poll。`session_id` 与 `run_id` 相等。
- resume 之后两个 id 仍然相等，epoch ordinal 增加，`continuity_generation` 在 related follow-up 上不变。
- 完成后 resume：完成 T2 已把 session 写成 `dormant`，`resumable` 仍为 true。用新的 `request_id` 做 `claim_resume`。同一事务插入新 epoch，把旧 epoch 上仍 `pending` 的 operation 改为 `closed`，并插入一条新的 `pending` operation，带上完整输入、新的 `epoch_id` 和当时的 `owner_generation`。session 设为 `active`，run 设为 `running`，session id 与 run id 不变。随后 `publish_snapshot` 只认这条新 operation，并把新结果写上快照。重放旧 `request_id` 返回已提交的旧行，不发布新结果。
- cancel 后合法 steer：`cancel` 不改 `resumable`。之后用新的 `request_id` 做 steer，开新 epoch，把旧 epoch 上仍 pending 的 operation 改为 `closed`，插入新的 pending operation，并把 run 设回 `running`。`publish_snapshot` 只认这条新 operation，能写上新结果。被 cancel 关掉的旧 epoch 上的迟到 T2 仍只归档。
- `admit_turn` 或 `admit_tool` 与 `cancel` 交错。cancel 先提交时，随后的 admit 被拒绝，不插入 pending，也不到事务外执行。admit 先提交时，cancel 把这条 operation 改为 `closed`，迟到 T2 只归档。
- A 发起请求但 T1 尚未提交，steer 到 B。然后 A 的 `admit_turn` 和 `admit_tool` 都被拒绝，没有 pending 行，也没有 Worker 或工具调用。B 的合法请求仍能执行并完成 T2。
- 新 epoch 的 `record_provider_handle` 已写入当前句柄之后，旧 epoch 的句柄晚到。attempt 行写上旧句柄。当前 `v20_session_provider_handles` 行不变。
- 同一 `request_id` 的句柄和快照有两种顺序。句柄先于 `publish_snapshot`，以及快照先于句柄。两种都留下当前句柄。快照先提交时，operation 保持 `completed`，`result` 不变。
- T2 已提交、响应丢失、同一 `request_id` 再交一次 T2。status 仍是 `completed`，`result` 不变。
- 同一 epoch 里新句柄先写入、旧句柄后到。当前行保持新句柄，更小的 `attempt_seq` 只归档。
- 完成快照先提交、resume 已插入新 epoch，并把这条 `completed`、`handle_state = pending`、还没有 attempt 行的 operation 设为 `absent`。旧句柄后到仍写入 attempt 行。新调用按 `absent` 启动，新 T2 成功发布。当前行不被旧句柄覆盖。
- 完成快照提交，补写句柄前退出，再恢复。`handle_state` 已是 `absent`。新 provider 启动，新 T2 发布。
- 同一次执行先发布 running 预览，再成功发布最终结果。进度不把 operation 标成 `completed`。重试同一 `snapshot_seq` 不另写一份。run 不再停在 `running`。
- 同一个 Control 进程还在。完成后 session 是 `dormant`，`resumable` 仍为 true。resume 成功并发布新结果。
- T1 提交后、provider 启动前进程退出。快照仍是 `running`。`recover_owner` 把它写成 `expired`，session 为 `interrupted`，`resumable` 仍为 true。仍需恢复的 operation 是 `archived`，`input_retained` 保持 true。然后 `claim_resume`，新 provider 启动，新 T2 发布。没有更早的 `present` 时无句柄启动。
- artifact 输入，进程退出，`recover_owner`。导出方 cleanup 删不掉文件。`claim_resume` 的新 T1 能读到原字节，重算 digest 一致，并在同一事务把保护转到新的 pending operation。然后新 provider 启动，新 T2 发布。
- 句柄先提交，然后 running 进度，然后最终 `waiting_for_input`。进度不改 `handle_state`。随后 `respond` 能启动 provider。
- `cancel` 之后，导出方 cleanup 删掉已无保护的文件。随后的迟到 T2 只追加归档事件，不把 operation 改成 `archived`，也不重新产生受保护引用。
- 产生句柄前 `cancel`，再合法 `steer`。被关闭的那次尝试 `handle_state` 为 `absent`。新 provider 启动，新 T2 成功发布。没有更早的 `present` 时无句柄启动。
- 从 `running` steer：同一事务关闭旧 epoch，把仍 `pending` 的 operation 改为 `closed`，还没有 attempt 行的 `handle_state` 设为 `absent`，插入新 epoch 和新的 `pending` operation，run 仍是 `running`，清掉 `interaction` 和 `failure_reason`，session id 与 run id 不变。新 provider 启动，新 T2 发布。旧尝试之后的 T2 只归档，不能覆盖新快照。
- 从 `waiting_for_input` steer：同一事务关闭旧 epoch，把仍 `pending` 的 operation 改为 `closed`，还没有 attempt 行的 `handle_state` 设为 `absent`，插入新 epoch 和新的 `pending` operation，run 设为 `running`，清掉 `interaction` 和 `failure_reason`，session id 与 run id 不变。新 provider 启动，新 T2 发布。旧尝试之后的 T2 只归档，不能覆盖新快照。
- 完成 T2 与 `cancel` 两种顺序。完成先提交，随后的 `cancel` 不改 status，仍是 `completed`。`cancel` 先提交，随后的 T2 只追加归档事件，operation 保持 `closed`，status 保持 `cancelled`。
- 运行中 `cleanup` 之后，`poll` 读到的 `v20_runs.status` 不是 `running`。`wait` 能看到这次推进的 revision。session 仍是 `terminal` 且 `resumable = false`。
- 同一 epoch 两个 pending 调用。交叉回执只记成归档事件。两条 operation 保持 `pending`。随后各自正确的回执都能标成 `completed`。
- run 保持 `waiting_for_input`。合法准入的 turn 和 tool 能提交回执并完成各自 operation。原 `interaction` 保留。随后 `respond` 仍可执行。
- 同一 epoch 的两个工具依次完成。第一个回执不阻止第二个结算。两条 operation 各自 `completed`。run 不被这两条回执改成 `completed`。
- cleanup 后 resume 和 steer 都被拒绝，不新建 epoch，run 不回到 `running`。
- 子 start 得到新的 session id，`parent_session_id` 指向父 session。
- `v20_sessions` 的列里没有 `workflow_run_id`。workflow 只出现在 activity 和可选的 workflow run 上。
- cite 在插入 step 之前读得到已提交的 artifact。step 有 `seq`。读日志不折叠出新的 handoff。
- wait：先 `LISTEN` 并提交，再读权威 revision。等待连接上没有打开的事务，主连接空闲。监听建立前已经提交的更新，这次读取能看到。通知丢失之后，超时或周期重查仍能看到新 revision。`NOTIFY` 只触发重查。
- 两个并发 CAS：一个 `committed`，一个 `conflict`。
- 两个调用者在恢复后同时 `claim_resume`。一个持有 run 锁提交，把 `owner_backend_pid` 写成自己的 pid 并启动。另一个看到活 owner 被拒绝，不新建 epoch。
- tool 回执完成后，下一次 provider 调用只等自己 T1 写下的 `depends_on_request_id`，不等自己，能启动并完成 T2。
- `claim_resume`：A 的句柄已经 `present`，B 的新 T1 已经 `pending`。B 的 `depends_on_request_id` 指向 A。B 读到 A 的句柄并启动 provider，然后新 T2 发布。
- `respond`：A 的句柄已经 `present`，B 的新 T1 已经 `pending`。B 的 `depends_on_request_id` 指向 A。B 读到 A 的句柄并启动 provider，然后新 T2 发布。
- `recover_owner`：旧 fence 被拒绝，新 owner 的 steer 提交，generation 增加，session id 与 run id 不变。
- 迟到回写：T1 固化 owner generation 和 epoch 之后，另一笔提交抬高了 owner generation，或推进了新 epoch。随后旧 owner 或旧 epoch 的 `publish_snapshot`、`accept_turn_receipt`、`accept_tool_result` 只把结果归档，`v20_runs` 上的当前快照保持不变。
- `cancel` 或 `cleanup` 提交后，同一个 owner、同一个 epoch 的 `publish_snapshot`、`accept_turn_receipt` 或 `accept_tool_result` 到达。结果只追加归档事件。已经 `closed` 的 operation 保持 `closed`，不把 `input_retained` 设回 true。run 快照保持 `cancelled`，或 session 保持 `terminal`。
- T1 提交后进程退出。恢复仍能按 `request_id` 读到完整准入输入（message 或 artifact 引用）、epoch 和 `pending`。请求 activity 已在，响应 activity 还没有。
- 一个 plan 下两个 workflow run、两个 session。第二步的输入是第一步导出的 digest，文件字节与 digest 一致。
- 第二次导出不同内容之后，第一次的受保护引用仍能读到原字节，重算 digest 与第一次一致。
- 父 session `cleanup` 之后，子步骤仍能读到输入文件，并重算 digest，与 artifact 行一致。把该 artifact 标为 `unavailable` 之后，新的 handoff 被拒绝；已有引用仍能读到原来的字节。
- artifact 尚无引用时，handoff 或 `bind_plan` 与 cleanup 交错。引用先提交，随后的 cleanup 不删文件，digest 重算仍一致。cleanup 先提交 `unavailable`，随后的 handoff 和 `bind_plan` 被拒绝，不留下新引用。
- 一份输入只被 pending operation 的 `input_artifact_digest` 引用，没有 step 或 plan 引用。导出方 cleanup 和进程重启之后，仍能读到文件并重算 digest。
- 当时仍是 `pending` 的 operation 因 owner 失效被标成 `archived`，`input_retained` 仍为 true。导出方 cleanup 删不掉文件。新尝试的 T1 仍能读到字节，重算 digest 与第一次一致。
- cleanup 之后事件行数不减少，transcript 还在，默认列表不再返回 `list_hidden` 的 session。
- 一个 transcript turn 关联两个控制回执：两行 `v20_turns` 的 `transcript_turn_id` 指向同一 `v20_transcript_turns.turn_id`。transcript 表上没有 `control_turn_id`。
- 事务内的模型调用和文件读写被拒绝。
- 显式 `claim_resume` 带 `workflow_run_id`：插入一行 step，输入是去重排序后的已提交 refs，`run_id` 仍等于 `session_id`，epoch 增加，workflow revision 加一。空 workflow 的这次续接 `seq = 0`。不带 `workflow_run_id` 的 `claim_resume` 不增加 step。
- 终态 `steer` 带 `workflow_run_id` 同样插入一行并推进 revision。`running` 上的 `steer` 带 `workflow_run_id` 被拒绝，step 行数和 revision 不变。
- 两个连接拿同一 `expected_workflow_revision` 做 `handoff`：一个提交，一个 `RevisionConflict`，失败方不增加 step。
- 显式续接与绑定同一 run 的 `handoff` 交错：不发生 deadlock。一个提交，另一个或提交下一个 seq，或返回 `RevisionConflict`。失败方不留 step。过期的 `expected_workflow_revision` 整笔回滚，epoch 数不增加。`get_log` 仍不插入 step。

## 8. 实现顺序

每一刀都可以单独做完并跑上面的对应探针。前一刀没绿，不开始下一刀。

1. session、run 别名、epoch、event、operation。探针：start、steer CAS、从 running 与 waiting_for_input steer 都关闭旧 epoch 并发布新 T2 且旧尝试不覆盖新快照、resume 不换 run id、完成后 resume 从新 pending operation 到 T2 发布、同一个 Control 进程还在时完成后 resume 能发布新结果、同一次执行先发 running 预览再发最终结果且 run 不再停在 running、cancel 后合法 steer 能发布新结果、cleanup 后 resume 和 steer 都被拒绝、运行中 cleanup 之后 poll 不再是 running 且 wait 能看到新 revision、admit 与 cancel 的两种提交顺序、A 的 T1 未提交时 steer 到 B 后 A 的 admit_turn 和 admit_tool 被拒绝且 B 的合法请求完成 T2、同一 epoch 两个 pending 调用的交叉回执仍保持 pending 且随后都能完成、run 保持 waiting_for_input 时合法 turn 和 tool 回执完成各自 operation 且原 interaction 保留、同一 epoch 两个工具依次完成、wait（先 LISTEN 再读 revision；监听前的提交和丢失的通知都要看见）、recover_owner、恢复后两个 claim_resume 只有一个提交并启动、迟到回写只归档、T1 提交后退出仍能读到输入、cancel 或 cleanup 之后同 owner 同 epoch 的 T2 不改快照、已完成 T2 的同一 request_id 重试不改 result、完成与 cancel 的两种提交顺序。
2. transcript 投影和 provider handle 表。探针：handle 不参与 CAS；新 epoch 的句柄写入后，旧 epoch 的迟到句柄不覆盖当前行；句柄先于快照和快照先于句柄都留下当前句柄；同一 epoch 里较小的 attempt_seq 不覆盖新句柄；完成快照先提交、resume 把还没有 attempt 行的 completed operation 设为 absent 后新 T2 能发布且当前行不被覆盖；完成快照提交、补写句柄前退出再恢复，新 provider 启动且新 T2 发布；T1 后、provider 启动前退出时快照仍是 running，recover_owner 写成 expired 再 claim_resume，新 provider 启动且新 T2 发布；句柄先于 running 进度，再到 waiting_for_input 后 respond 能启动；产生句柄前 cancel 再合法 steer，新 provider 启动且新 T2 发布；从 running 与 waiting_for_input steer 后新 provider 启动且新 T2 发布，旧尝试不覆盖新快照；tool 回执完成后下一次 provider 调用按 depends_on_request_id 启动并完成 T2；A 的句柄已 present 时，claim_resume 与 respond 的新 T1 读到 A 的句柄并发布新 T2；cleanup 不删 transcript 和 event；一个对话回合关联两个控制回执；请求 activity 在 T1，响应在 T2。
3. workflow definition 目录、activity 上的 definition id、可选 workflow run 和带 digest 校验的 step。探针：无 workflow 的 session 仍能跑；cite 与导出；父 session cleanup 之后子步骤仍能读到输入文件并重算 digest；第二次导出不同内容后第一次的受保护引用仍读到原字节；handoff 或 bind_plan 与 cleanup 的两种提交顺序；仅被 pending operation 引用的文件在导出方 cleanup 和重启后仍可读；artifact 输入经 recover_owner 归档后，导出方 cleanup 删不掉，claim_resume 的新 T1 重算 digest 一致并发布新 T2；cancel 之后导出方 cleanup 删掉无保护文件，迟到 T2 不重新产生受保护引用。写 step 带 `expected_workflow_revision`，空 workflow 的第一步 `seq = 0`，并发 handoff 一个提交一个冲突。显式续接在原 run 上承接已提交 refs；不带 workflow 的 resume 不插 step；running 上的 steer 拒绝续接；过期 revision 回滚 epoch；续接与 handoff 交错不发生 deadlock。
4. plan 四张表把两个 workflow run 和两个 session 连起来。探针：宏观任务。

这一份设计不改 `docs/designs/v20-runtime-charter-draft-2026-10-12.md`。章程要收 session 和 epoch 时，再把第 3 节的表名写回去。
