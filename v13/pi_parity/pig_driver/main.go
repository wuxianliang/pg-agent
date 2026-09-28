// pi_parity PiG-side driver: run the same two-file read task through the REAL
// PiG agent loop with a scripted provider, and emit a canonical schema-v2
// trace at traces/pig.jsonl (relative to the working directory).
//
// Why an own scripted provider: PiG's scriptedProvider / toolCallsThenText /
// replyText helpers live in agent/upstream_helpers_test.go, and Go does not
// compile _test.go files into importable packages. This driver therefore
// re-implements the same scripted semantics against the PUBLIC ai.Provider
// interface (ai/types.go:552: ID/Stream/Close), driven by a judgment function
// over the normalized transcript that is isomorphic to the pg ring's
// overrides_for/final_from_results: count ToolResultMessage messages, emit the
// next read tool call, digest the results for the final answer.
//
// Why an own read tool: PiG's agent package ships no importable read tool
// (the read tool lives behind its coding/TUI surface; v13/pi_ports/pig_port
// ports pi's read tool as a main package, which is also not importable). This
// driver's readTool reads the fixture file and returns its exact content.
//
// Canonical mapping (PiG AgentEvent -> phase; source of truth for README):
//   MessageEndEvent(assistant)  -> llm    (evidence = OnMessagePersist ordinal)
//   ToolExecutionStartEvent     -> claim  (framework dispatch of a tool call)
//   ToolExecutionEndEvent       -> tool   (result digest of AgentToolResult)
//   AgentEndEvent               -> finish (run settled, no retry)
//   MessageStart/MessageUpdate, ToolExecutionUpdate -> folded into the next
//     canonical step's raw[] (type names only; counts are transport noise)
//   AgentStart/TurnStart/TurnEnd/Timing/AgentSettled/QueueUpdate/
//   ThinkingLevelChanged/CompactionStart/CompactionEnd -> phase "raw" rows
//   judge/parse/advance have NO PiG native equivalent; never fabricated.
//
// Persistence honesty: the agent runs in-memory; OnMessagePersist (invoked
// exactly once per NEW message by the loop) is the persistence channel ->
// persisted "memory" with persist:#<ordinal>/<role> evidence. Durations and
// timestamps are excluded from the trace for byte stability.
package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"github.com/MichaelKinsy/PiG/agent"
	"github.com/MichaelKinsy/PiG/ai"
)

const runtimeName = "pig"

var expectedReads = []string{"hello.txt", "fib.py"}

func digest(text string) string {
	sum := sha256.Sum256([]byte(text))
	return "sha256:" + hex.EncodeToString(sum[:])[:16]
}

func finalFromResults(results []string) string {
	return fmt.Sprintf(
		"hello.txt %s is a three-line greeting file; fib.py %s defines recursive fib(n) with fib(10)=55; both files were read.",
		digest(results[0]), digest(results[1]),
	)
}

// ─── scripted provider (public ai.Provider re-implementation) ─────────────────

type parityProvider struct {
	mu      sync.Mutex
	request int
}

func (p *parityProvider) ID() string   { return "pig-parity" }
func (p *parityProvider) Close() error { return nil }

func (p *parityProvider) requests() int {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.request
}

func assistantMessage(content []ai.AssistantContentBlock, reason ai.StopReason) *ai.AssistantMessage {
	return &ai.AssistantMessage{Content: content, Provider: "pig-parity", Model: "scripted", StopReason: reason}
}

func doneStream(message *ai.AssistantMessage) (*ai.AssistantMessageEventStream, error) {
	stream := ai.NewAssistantMessageEventStream()
	if err := stream.Push(ai.StartEvent{Partial: assistantMessage(nil, ai.StopReasonPending)}); err != nil {
		return nil, err
	}
	if err := stream.Push(ai.DoneEvent{Reason: message.StopReason, Message: message}); err != nil {
		return nil, err
	}
	return stream, nil
}

// Stream answers each request from the transcript state, isomorphic to the pg
// ring's judgment: 0 tool results -> next read call, all results -> final text.
func (p *parityProvider) Stream(_ context.Context, transcript ai.TranscriptContext, _ ai.StreamOptions) (*ai.AssistantMessageEventStream, error) {
	p.mu.Lock()
	p.request++
	p.mu.Unlock()
	var results []string
	for _, message := range transcript.Messages() {
		result, ok := message.(ai.ToolResultMessage)
		if !ok {
			continue
		}
		text := ""
		for _, block := range result.Content {
			if tc, ok := block.(ai.TextContent); ok {
				text += tc.Text
			}
		}
		results = append(results, text)
	}
	if len(results) < len(expectedReads) {
		call := ai.ToolCall{
			ID:         fmt.Sprintf("call-%d", len(results)),
			Name:       "read",
			Arguments:  ai.JsonObject{"path": expectedReads[len(results)]},
		}
		return doneStream(assistantMessage([]ai.AssistantContentBlock{call}, ai.StopReasonToolUse))
	}
	return doneStream(assistantMessage(
		[]ai.AssistantContentBlock{ai.TextContent{Text: finalFromResults(results)}},
		ai.StopReasonStop,
	))
}

// ─── read tool (driver-local; PiG has no importable read tool) ────────────────

type readTool struct {
	root string
}

func (t *readTool) Name() string  { return "read" }
func (t *readTool) Label() string { return "Read" }
func (t *readTool) Schema() ai.ToolSchema {
	return ai.ToolSchema{
		Name:        "read",
		Description: "Read a file from the fixture root and return its exact content.",
		Parameters: map[string]any{
			"type":       "object",
			"properties": map[string]any{"path": map[string]any{"type": "string"}},
			"required":   []any{"path"},
		},
	}
}
func (t *readTool) ExecutionMode() agent.ToolExecutionMode { return agent.ToolModeSequential }

func (t *readTool) Execute(_ context.Context, _ string, params json.RawMessage, _ agent.ToolUpdateCallback) (agent.AgentToolResult, error) {
	var args struct {
		Path string `json:"path"`
	}
	if err := json.Unmarshal(params, &args); err != nil {
		return agent.AgentToolResult{Content: "invalid params: " + err.Error(), IsError: true}, nil
	}
	// Root fence: Abs + EvalSymlinks + Rel containment + regular file. A
	// naive filepath.Join would happily accept "../" escapes and symlinks
	// out of the fixture root.
	rootAbs, err := filepath.Abs(t.root)
	if err != nil {
		return agent.AgentToolResult{Content: "read failed: " + err.Error(), IsError: true}, nil
	}
	rootEval, err := filepath.EvalSymlinks(rootAbs)
	if err != nil {
		return agent.AgentToolResult{Content: "read failed: " + err.Error(), IsError: true}, nil
	}
	joined := filepath.Join(rootAbs, filepath.FromSlash(args.Path))
	joinedEval, err := filepath.EvalSymlinks(joined)
	if err != nil {
		return agent.AgentToolResult{Content: "read failed: " + err.Error(), IsError: true}, nil
	}
	rel, err := filepath.Rel(rootEval, joinedEval)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) || filepath.IsAbs(rel) {
		return agent.AgentToolResult{Content: "read out of fence: " + args.Path, IsError: true}, nil
	}
	info, err := os.Stat(joinedEval)
	if err != nil || !info.Mode().IsRegular() {
		return agent.AgentToolResult{Content: "not a regular file: " + args.Path, IsError: true}, nil
	}
	data, err := os.ReadFile(joined)
	if err != nil {
		return agent.AgentToolResult{Content: "read failed: " + err.Error(), IsError: true}, nil
	}
	return agent.AgentToolResult{Content: string(data)}, nil
}

// ─── canonical trace ──────────────────────────────────────────────────────────

type stepRow struct {
	Runtime       string   `json:"runtime"`
	Seq           int      `json:"seq"`
	Phase         string   `json:"phase"`
	Tool          *string  `json:"tool"`
	Args          map[string]any `json:"args"`
	ResultDigest  string   `json:"result_digest"`
	Persisted     string   `json:"persisted"`
	Evidence      string   `json:"evidence"`
	Raw           []string `json:"raw,omitempty"`
}

type builder struct {
	steps      []*stepRow
	pendingRaw []string
}

func (b *builder) takeRaw() []string {
	if len(b.pendingRaw) == 0 {
		return nil
	}
	folded := b.pendingRaw[:0:0]
	for _, name := range b.pendingRaw {
		if len(folded) == 0 || folded[len(folded)-1] != name {
			folded = append(folded, name)
		}
	}
	b.pendingRaw = nil
	return folded
}

func (b *builder) row(phase string, tool *string, args map[string]any, resultDigest string, evidence string) *stepRow {
	row := &stepRow{
		Runtime:      runtimeName,
		Seq:          len(b.steps),
		Phase:        phase,
		Tool:         tool,
		Args:         args,
		ResultDigest: resultDigest,
		Persisted:    "memory",
		Evidence:     evidence,
		Raw:          b.takeRaw(),
	}
	b.steps = append(b.steps, row)
	return row
}

func (b *builder) rawRow(native string, extra map[string]any) {
	args := map[string]any{"native": native}
	for key, value := range extra {
		args[key] = value
	}
	b.row("raw", nil, args, "", "memory: in-process agent event")
}

func assistantText(message *agent.AssistantMessage) string {
	text := ""
	for _, block := range message.Content {
		if tc, ok := block.(ai.TextContent); ok {
			text += tc.Text
		}
	}
	return text
}

func toolCallArgs(content []ai.AssistantContentBlock) []map[string]any {
	calls := []map[string]any{}
	for _, block := range content {
		if call, ok := block.(ai.ToolCall); ok {
			path := ""
			if value, ok := call.Arguments["path"].(string); ok {
				path = value
			}
			calls = append(calls, map[string]any{"name": call.Name, "path": path})
		}
	}
	return calls
}

func toolResultText(result *agent.ToolResultMessage) string {
	text := ""
	for _, block := range result.Content {
		if tc, ok := block.(ai.TextContent); ok {
			text += tc.Text
		}
	}
	return text
}

func emit(obj map[string]any, code int) {
	raw, err := json.Marshal(obj)
	if err != nil {
		os.Exit(1)
	}
	os.Stdout.Write(append(raw, '\n'))
	os.Exit(code)
}

func main() {
	fixtures := "fixtures"
	if len(os.Args) > 1 {
		fixtures = os.Args[1]
	}
	os.Remove("traces/pig.jsonl") // stale artifacts must never survive a run

	provider := &parityProvider{}
	model := &ai.Model{ID: "scripted", DisplayName: "scripted", Provider: provider, Capabilities: ai.ModelCapabilities{ContextWindow: 8192}}

	// OnMessagePersist is invoked exactly once per NEW message by the loop:
	// the in-memory persistence channel backing the trace evidence. The log
	// captures each message's payload (text digest, stopReason, tool calls)
	// so post-run evidence can be CONTENT-bound, not order-only.
	var persistMu sync.Mutex
	type persistEntry struct {
		ordinal    int
		role       string
		toolCallID string
		text       string
		textDigest string
		stopReason string
		toolCalls  []map[string]any
	}
	persistLog := []persistEntry{}
	onPersist := func(msg agent.AgentMessage) error {
		role := "custom"
		toolCallID := ""
		text := ""
		textDigest := ""
		stopReason := ""
		var toolCalls []map[string]any
		switch {
		case msg.System != nil:
			role = "system"
		case msg.User != nil:
			role = "user"
		case msg.Assistant != nil:
			role = "assistant"
			text = assistantText(msg.Assistant)
			textDigest = digest(text)
			stopReason = string(msg.Assistant.StopReason)
			toolCalls = toolCallArgs(msg.Assistant.Content)
		case msg.ToolResult != nil:
			role = "toolResult"
			toolCallID = msg.ToolResult.ToolCallID
			text = toolResultText(msg.ToolResult)
			textDigest = digest(text)
		}
		persistMu.Lock()
		persistLog = append(persistLog, persistEntry{ordinal: len(persistLog), role: role, toolCallID: toolCallID, text: text, textDigest: textDigest, stopReason: stopReason, toolCalls: toolCalls})
		persistMu.Unlock()
		return nil
	}

	eventCh := make(chan agent.AgentEvent) // unbuffered: emit blocks until received
	consumerDone := make(chan struct{})
	var events []agent.AgentEvent
	go func() {
		defer close(consumerDone)
		for ev := range eventCh {
			events = append(events, ev)
		}
	}()

	read := &readTool{root: fixtures}
	agentInstance := agent.NewAgent(agent.AgentOptions{
		Model:         model,
		Tools:         []agent.AgentTool{read},
		EventCh:       eventCh,
		ToolExecution: agent.ToolModeSequential,
		OnMessagePersist: onPersist,
	})

	_, err := agentInstance.Send(context.Background(), "Read hello.txt and fib.py, then state the key points of both files.")
	close(eventCh)
	<-consumerDone
	if err != nil {
		emit(map[string]any{"ok": false, "error": "send_failed", "detail": err.Error()}, 4)
	}

	b := &builder{}
	claimPath := map[string]string{}
	var llmSteps []*stepRow
	toolStepByCall := map[string]*stepRow{}
	var finishStep *stepRow
	for _, ev := range events {
		switch e := ev.(type) {
		case agent.MessageStartEvent:
			b.pendingRaw = append(b.pendingRaw, "message_start")
		case agent.MessageUpdateEvent:
			b.pendingRaw = append(b.pendingRaw, "message_update")
		case agent.MessageEndEvent:
			if e.Message.Assistant == nil {
				role := "other"
				if e.Message.User != nil {
					role = "user"
				} else if e.Message.ToolResult != nil {
					role = "toolResult"
				} else if e.Message.System != nil {
					role = "system"
				}
				b.pendingRaw = append(b.pendingRaw, "message_end:"+role)
				continue
			}
			toolCalls := []map[string]any{}
			for _, block := range e.Message.Assistant.Content {
				if call, ok := block.(ai.ToolCall); ok {
					path := ""
					if value, ok := call.Arguments["path"].(string); ok {
						path = value
					}
					toolCalls = append(toolCalls, map[string]any{"name": call.Name, "path": path})
				}
			}
			step := b.row("llm", nil, map[string]any{
				"stopReason": string(e.Message.Assistant.StopReason),
				"toolCalls":  toolCalls,
			}, digest(assistantText(e.Message.Assistant)), "pending-resolution")
			llmSteps = append(llmSteps, step)
		case agent.ToolExecutionStartEvent:
			path := ""
			var args struct {
				Path string `json:"path"`
			}
			if json.Unmarshal(e.Args, &args) == nil {
				path = args.Path
			}
			claimPath[e.ToolCallID] = path
			toolName := e.ToolName
			b.row("claim", &toolName, map[string]any{
				"kind":       "tool",
				"toolCallId": e.ToolCallID,
				"path":       path,
			}, "", fmt.Sprintf("memory: dispatch tool_call:%s", e.ToolCallID))
		case agent.ToolExecutionUpdateEvent:
			b.pendingRaw = append(b.pendingRaw, "tool_update")
		case agent.ToolExecutionEndEvent:
			toolName := e.ToolName
			step := b.row("tool", &toolName, map[string]any{
				"path": claimPath[e.ToolCallID],
			}, digest(e.Result.Content), "pending-resolution")
			toolStepByCall[e.ToolCallID] = step
		case agent.AgentEndEvent:
			status := "completed"
			for i := len(e.Messages) - 1; i >= 0; i-- {
				if message := e.Messages[i]; message.Assistant != nil {
					if message.Assistant.StopReason != ai.StopReasonStop {
						status = string(message.Assistant.StopReason)
					}
					break
				}
			}
			if e.WillRetry {
				status = "will_retry"
			}
			finishStep = b.row("finish", nil, map[string]any{
				"status": status,
			}, "", "pending-resolution")
		case agent.TimingEvent:
			b.rawRow("agent.TimingEvent", map[string]any{"kind": e.Kind})
		case agent.AgentStartEvent:
			b.rawRow("agent.AgentStartEvent", nil)
		case agent.AgentSettledEvent:
			b.rawRow("agent.AgentSettledEvent", nil)
		case agent.TurnStartEvent:
			b.rawRow("agent.TurnStartEvent", map[string]any{"turnIndex": e.TurnIndex})
		case agent.TurnEndEvent:
			b.rawRow("agent.TurnEndEvent", map[string]any{"turnIndex": e.TurnIndex})
		case agent.QueueUpdateEvent:
			b.rawRow("agent.QueueUpdateEvent", nil)
		case agent.ThinkingLevelChangedEvent:
			b.rawRow("agent.ThinkingLevelChangedEvent", nil)
		case agent.CompactionStartEvent:
			b.rawRow("agent.CompactionStartEvent", nil)
		case agent.CompactionEndEvent:
			b.rawRow("agent.CompactionEndEvent", nil)
		default:
			b.rawRow(fmt.Sprintf("%T", ev), nil)
		}
	}

	// Post-run evidence resolution: MessageEndEvent fires before the message
	// is persisted, so pair steps to OnMessagePersist ordinals once the run
	// (and the persist log) is final. Pairing is content-bound: each persisted
	// message must carry the same payload its event-stream step recorded.
	// Mismatch -> exit 5 WITHOUT writing the trace.
	if provider.requests() != 3 {
		emit(map[string]any{"ok": false, "error": "provider_calls",
			"detail": fmt.Sprintf("expected 3 provider calls, got %d", provider.requests())}, 5)
	}
	persistMu.Lock()
	defer persistMu.Unlock()
	assistantPersists := []persistEntry{}
	toolPersistByCall := map[string]persistEntry{}
	for _, entry := range persistLog {
		switch entry.role {
		case "assistant":
			assistantPersists = append(assistantPersists, entry)
		case "toolResult":
			toolPersistByCall[entry.toolCallID] = entry
		}
	}
	if len(assistantPersists) != len(llmSteps) {
		emit(map[string]any{"ok": false, "error": "evidence_mismatch",
			"detail": fmt.Sprintf("assistant persists %d != llm steps %d", len(assistantPersists), len(llmSteps))}, 5)
	}
	for index, step := range llmSteps {
		entry := assistantPersists[index]
		if entry.textDigest != step.ResultDigest {
			emit(map[string]any{"ok": false, "error": "evidence_payload",
				"detail": fmt.Sprintf("assistant persist #%d text digest != llm step seq %d", entry.ordinal, step.Seq)}, 5)
		}
		if entry.stopReason != step.Args["stopReason"] {
			emit(map[string]any{"ok": false, "error": "evidence_payload",
				"detail": fmt.Sprintf("assistant persist #%d stopReason != llm step seq %d", entry.ordinal, step.Seq)}, 5)
		}
		want, _ := json.Marshal(step.Args["toolCalls"])
		got, _ := json.Marshal(entry.toolCalls)
		if string(want) != string(got) {
			emit(map[string]any{"ok": false, "error": "evidence_payload",
				"detail": fmt.Sprintf("assistant persist #%d toolCalls != llm step seq %d", entry.ordinal, step.Seq)}, 5)
		}
		step.Evidence = fmt.Sprintf("persist:#%d/assistant (OnMessagePersist)", entry.ordinal)
	}
	for callID, step := range toolStepByCall {
		entry, ok := toolPersistByCall[callID]
		if !ok {
			emit(map[string]any{"ok": false, "error": "evidence_mismatch", "detail": "no toolResult persist for " + callID}, 5)
		}
		if entry.textDigest != step.ResultDigest {
			emit(map[string]any{"ok": false, "error": "evidence_payload",
				"detail": fmt.Sprintf("toolResult persist #%d digest != tool step seq %d", entry.ordinal, step.Seq)}, 5)
		}
		step.Evidence = fmt.Sprintf("persist:#%d/toolResult (OnMessagePersist)", entry.ordinal)
	}
	if finishStep != nil {
		finishStep.Evidence = fmt.Sprintf("memory: agent_end settled; %d messages persisted (OnMessagePersist)", len(persistLog))
	}

	// Final answer FROM THE PERSISTED final assistant message, cross-checked
	// against the event stream (last llm step digest) and the deterministic
	// contract over the persisted tool results.
	finalPersist := assistantPersists[len(assistantPersists)-1]
	finalText := finalPersist.text
	if digest(finalText) != llmSteps[len(llmSteps)-1].ResultDigest {
		emit(map[string]any{"ok": false, "error": "final_mismatch",
			"detail": "persisted final assistant text != event-stream llm digest"}, 5)
	}
	persistedResults := []string{toolPersistByCall["call-0"].text, toolPersistByCall["call-1"].text}
	if finalText != finalFromResults(persistedResults) {
		emit(map[string]any{"ok": false, "error": "final_mismatch",
			"detail": "final text != deterministic contract over persisted results"}, 5)
	}

	if err := os.MkdirAll("traces", 0o755); err != nil {
		emit(map[string]any{"ok": false, "error": "mkdir_failed", "detail": err.Error()}, 6)
	}
	file, err := os.OpenFile("traces/pig.jsonl", os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		emit(map[string]any{"ok": false, "error": "open_failed", "detail": err.Error()}, 6)
	}
	defer file.Close()
	encoder := json.NewEncoder(file)
	for _, step := range b.steps {
		if err := encoder.Encode(step); err != nil {
			emit(map[string]any{"ok": false, "error": "encode_failed", "detail": err.Error()}, 6)
		}
	}
	finalRow := map[string]any{"runtime": runtimeName, "final": finalText}
	if err := encoder.Encode(finalRow); err != nil {
		emit(map[string]any{"ok": false, "error": "encode_failed", "detail": err.Error()}, 6)
	}

	emit(map[string]any{"ok": true, "trace": "traces/pig.jsonl", "steps": len(b.steps), "final": finalText, "providerCalls": provider.requests()}, 0)
}
