# v24 Tool/Plugin ABI v1：具体设计任务 brief

- 日期：2026-10-29
- 状态：待 Oracle 三 lane 产出具体设计
- 上游裁决：选 C（协议先行 + 用现有 agent loop 跑薄切片）；不做 session/workflow 层
- 相关：`docs/investigations/deepseek-harness-design-vs-v24-2026-10-29.md`、`docs/investigations/v24-drift-factcheck-2026-10-29.md`、`docs/investigations/v24-plugin-vs-agent-sequencing-brief-2026-10-29.md`

## 1. 目标

为 v24 定义 **Tool/Plugin ABI v1**，能容纳 Pi 与 RepoPrompt 的工具形态，并用 3 个真实工具跑通现有 agent loop 的完整生命周期：

```text
install → host_prepare → fiber_control(on) → start
  → model_call → tool_call(s) → continuation model_call → final
  → fiber_control(off) → dispose → host_release → scope close
```

本设计稿要能直接拆成可执行开发计划。

## 2. 已定范围（不要重开）

- 选 C：先协议 + 3 个真实工具；**不建 session 对象、不做 spawn/join/result、不改六动词**。
- 工具：`read`、`list`、`search`。
- 语言：Python + Node.js；**一个 Node install 同时提供 `list` + `search`**，证明 plugin identity ≠ tool identity。
- 运行路径：现有 `v24.start` + scripted model，不接真实 provider。
- 不改 `v24/sql/**`；ABI 变更落在 host/spec/descriptor 层。若某决策非改内核不可，必须单独标注为“需要 kernel revision”，不能偷偷改。
- 不建第 11 张表；不引入第二 claim/queue/recovery。
- definition / transport 分离；MCP/PTC 只能作为 provider/便利层，不作为 ABI。
- 保留 descriptor/frame v1 兼容；legacy echo 的 provider 文本必须字节不变。

## 3. 必须由设计稿回答的问题

### A. 数据模型

1. `ToolDescriptor v2` 的精确 JSON 形状：必填/可选字段、类型、关闭集。
2. 多工具 install 的模型：`ApprovedAdapter`（进程/制品）与 `ApprovedTool`（descriptor/key）如何拆分？现有 `registry.py` 的 5 字段匹配、`match_pin`、`require_artifact` 如何演进而不弱化？
3. descriptor digest 的 canonical JSON 规则；跨语言（Python/Node）如何生成相同字节？与 `pg_jsonb_text` 的关系。
4. `tool.parameters` / `tool.output_schema` / `tool.render` / `tool.limits` / `tool.concurrency` / `tool.replay_class` / `tool.annotations` 的归属：哪些进 descriptor（DB 冻结），哪些进 registry（host 审批），哪些 deferred。
5. `timeout_ms` 放 descriptor 还是 registry？两者的优先级/上限/lease 关系。

### B. 传输与结果

1. `line-json.v2` 的精确帧：invoke 如何选 tool key；success/error/unknown 的边界；与 v1 的兼容策略。
2. 结果 envelope：外层 `{status,output,usage}` 不变的前提下，`output` 内的 `{value,content,meta,error}` 精确形状、关闭集、content block 类型。
3. 模型可见文本如何从 `content` 生成；legacy v1 如何字节不变；image/大结果如何处理。
4. schema 校验边界：host 在 spawn 前校验 args、成功后校验 value、render 后校验 content/limits；非法 args → 普通 failure 零 spawn；非法 output → 普通 failure；协议/超时 → unknown。DB 仍只做形状校验。
5. 截断/分页：`read/list/search` 的 continuation 元数据；transport 64 KiB 与语义 output 上限的关系。

### C. 三个工具的具体合同

对每个工具给出：
- key、description、parameters schema、output schema、render id/version/digest、limits、concurrency、annotations；
- 成功 value 形状、content 渲染、错误码；
- 边界：空文件、二进制、超长行、offset 越界、路径逃逸、符号链接、隐藏文件、确定性排序、最大 entries/hits。

### D. 工程落地

1. 新增/修改文件清单（host、s11/s13、tests、docs），每项职责与依赖。
2. 旧 v1 兼容的迁移路径：descriptor/frame/adapter digest；旧 host 遇到 v2 如何 fail closed；回滚条件。
3. 测试矩阵：合同向量、跨语言 digest、生命周期、mixed-language batch、非法 args 零 spawn、非法 output、render failure、timeout、越界、篡改、crash/receipt、legacy 字节不变。
4. gate/验收命令与 done-when；明确哪些是 extension check，哪些不进 closeout。
5. 风险与退出条件：哪些情况必须停下来改设计/改内核。

## 4. 约束与已知事实

- 当前 `tool_calls` 只校验 `{key,args}` 形状（`v24/sql/48_loop.sql:296-307`）。
- tool result 只校验 `{status,output,usage}` 形状（`48_loop.sql:1376-1415`）。
- 所有 tool successor 硬编码 `no_replay`（`48_loop.sql:1133`）；`replay_safe` 只对 host_prepare/host_release/inspect_resource 有效（`49_recovery.sql:351-375`）。
- 当前 `ApprovedAdapter` 一条 entry 对应一个 tool；`line_json.invoke` 不带 tool key。
- 当前 worker 把 `canonical_json(output)` 直接作为 tool message（`worker.py:1027-1080`）。
- DSH：`ToolDefinition.output` 必填（schema + render + presentationMeta），model-visible 只有 `{name,description,parameters}`；`timeoutMs` 在 definition；`isConcurrencySafe` 决定 parallel/exclusive。
- Pi：`ToolDefinition` 有 `outputSchema`、`renderCall/renderResult`、`executionMode`、`annotations`、`exposure`；`read` 的 output 是 string|image union。
- RepoPrompt：`Tool` 只有 inputSchema + annotations，没有 outputSchema/render；`MCPDomainToolCatalog` 有 admissionClass（exclusive/control/smallRead/fileRead/gitRead/fileSearch）与 operationPolicy。

## 5. 评估标准（用于比较三份设计）

1. **正确性**：是否与 v24 现有 effect/pin/receipt/unknown 语义一致；是否避免第二真相源。
2. **可落地性**：是否能在现有 host 上增量实现；是否明确文件/接口/测试。
3. **兼容性**：v1 echo 是否字节不变；旧 host 是否 fail closed；descriptor digest 是否跨语言稳定。
4. **最小性**：是否只引入必要的字段/模块；是否把 deferred 项明确列出。
5. **可测试性**：是否有跨语言向量、负例、崩溃/超时/篡改用例。
6. **风险**：是否隐藏 kernel revision；是否把 session/streaming 偷渡进来。
