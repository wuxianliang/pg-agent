# v24 开发顺序裁决：先做 RepoPrompt 式 agent 工作流，还是先定工具/插件协议

- 日期：2026-10-29
- 状态：待 Oracle 裁决
- 相关：`docs/investigations/deepseek-harness-design-vs-v24-2026-10-29.md`（DSH 对照）、`docs/investigations/v24-drift-factcheck-2026-10-29.md`

## 背景与原始目标

v24 的最初目标之一是给数据库原生 agent 设计**多语言工具/插件协议**，要求至少能容纳两类参考实现的功能：

- **Pi**：read / bash / edit / write / grep / find / ls 等 coding tools，已有 TS/Go/Swift 多语言 port 经验（`v13/pi_ports`）。
- **RepoPrompt**：read_file / get_file_tree / file_search / get_code_structure / git / apply_edits / workspace_context 等工具，以及 session → agent → subagent 的工作流层。

参考 **DeepSeek Harness (DSH)**，因为它同时具备：
- Cordis 插件系统（service / inject / apply / reversible effects / waterfall events）；
- 工具数据结构（`ToolDefinition`：name/description/parameters、`output.schema`、`render`、`execute`）；
- 多运行时 seam（native / MCP / PTC / subagent providers）。
目标是借鉴其**数据结构与扩展 seam 的本质**，创造性转化进 v24，而不是复制实现。

用户明确：**session 对话控制是另一个问题，两者应该正交。** 本裁决只决定开发顺序。

## v24 当前状态

- agent loop 已实现：effect-defined turn、model_call/tool_call、batch barrier、budget、seal、unknown wall、recovery（S1–S8）。
- spawn/child run 已实现：`agent.spawn` 在同一 advance 创建 child run/edge/quota/first model（S8/G7）；但没有 session 对象、parent-child join/result、per-run role/model。
- 插件面已有最小 reference plane：`v24/s11` 的 Python/Node line-JSON echo 插件，manifest/provides/descriptor/pin/approved adapter registry/host_prepare/release。
- 真实工具/协议仍未落地：descriptor 无 output schema/render/replay class/approval/limits；host 只有 one-shot line-JSON；没有 Pi/RepoPrompt 工具的真实实现。
- RepoPrompt 式工作流层未实现：没有 session 对象、workflow prompt/agent 编排、subagent join、session transcript。

## 选项 A：先实现“像 RepoPrompt 内置工作流一样的 agent 系统能跑起来”

- 先做 session/agent 编排层：创建 session、派 agent、派 child run、等待/收集、把结果回灌父 run；可以用占位工具或现有 echo 插件。
- 优点：更早看到“一个 session 派 agent 再派子代理一起工作”的端到端形态；能验证编排语义。
- 风险：工具面还是空的，工作流只能跑 fake/echo；容易围绕“能跑”发明临时 tool 接口，之后被真正的多语言协议推翻；session 控制本身是正交问题，可能偏离原始目标。

## 选项 B：先定义工具/插件协议，并打造几个示例工具/插件

- 先冻结 ToolDescriptor/Plugin ABI v1（definition/transport 分离），实现 3–5 个真实工具（如 read/list/search），至少两种语言（如 Swift + TS/Python），跑通 install → prepare → activate → pin → tool_call → receipt。
- 优点：直接推进原始目标；协议是可复用合同，Pi/RepoPrompt 工具迁移都依赖它；真实工具能暴露 schema、render、limits、timeout、multi-language 等真实问题；agent 工作流之后可以建立在这套稳定工具面上。
- 风险：没有“工作流能跑”的演示，可能被质疑只有协议没有产品；需要先确定工具候选和最小 ABI，避免过度设计。

## 需要 Oracle 回答的问题

1. 在“session 控制与工具/插件协议正交”的前提下，推荐先 A 还是先 B？为什么？
2. 是否存在第三条路：一个**薄的垂直切片**，同时包含最小 agent run 和 2–3 个真实工具，从而避免“协议无 runner”或“工作流无工具”？
3. 如果先 B，协议第一版应该冻结到什么程度（descriptor 字段、transport、result、capability、render、schema 校验）？哪些可以后置？
4. 如果先 A，工作流层应该只做到什么程度，才能不锁死 tool ABI？
5. 从“至少容纳 Pi 和 RepoPrompt 工具”的目标看，哪个顺序更能暴露真正的兼容性问题？
6. 给出一个明确的里程碑顺序（最多 4 步），每步的 done 判据和风险。

## 约束

- 不建第 11 张表；不引入第二 claim/queue/recovery。
- 工具 ABI 是 definition + transport 分离；MCP/PTC 只能作为 provider/便利层，不作为 ABI。
- session 控制是正交问题，本轮不要求把它一起做完。
- 现有 v24 内核 SQL 已冻结；任何协议改动优先落在 host/spec/descriptor 层。
