// pi_parity PiSwift-side driver: run the same two-file read task through the
// REAL PiSwift coding-agent session with a scripted provider, and emit a
// canonical schema-v2 trace at traces/piswift.jsonl (relative to cwd).
//
// Injection route (all public API, verified by the smoke that preceded this
// driver):
//   1. PiSwiftAI.registerFauxProvider() -> FauxProviderRegistration
//      (Sources/PiSwiftAI/FauxProvider.swift; port of pi's fauxProvider)
//   2. registration.getModel() -> Model passed as CreateAgentSessionOptions
//      .model (Sources/PiSwiftCodingAgent/Core/SDK.swift:504)
//   3. AuthStorage.setRuntimeApiKey satisfies the pre-stream credential gate
//      (throwaway key, in-memory auth file under a temp dir)
//   4. toolNames: ["read"] restricts the tool face to the session's built-in
//      read tool; offline: true; SessionManager.inMemory keeps the session
//      state in-process
//
// The scripted judgment is a FauxResponseFactory over the normalized
// TranscriptContext, isomorphic to the pg ring's overrides_for/
// final_from_results: count toolResult messages, emit the next read tool
// call, digest the results for the final answer.
//
// Canonical mapping (AgentSessionEvent -> phase; README table source):
//   .agent(.messageEnd(assistant))       -> llm
//   .agent(.toolExecutionStart)          -> claim
//   .agent(.toolExecutionEnd)            -> tool
//   .agent(.agentEnd)                    -> finish
//   .agent(.messageStart/.messageUpdate),
//     .agent(.messageEnd(non-assistant)) -> folded into next step raw[]
//   .agent(.agentStart/.turnStart/.turnEnd), .agentSettled,
//     auto-compaction/retry events       -> phase "raw" rows
//   .entryAppended(.message)             -> persistence evidence (ordinal)
//   .entryAppended(other)                -> raw rows
//   judge/parse/advance have NO PiSwift native equivalent; never fabricated.
//
// Persistence honesty: the session runs on SessionManager.inMemory; entries
// committed at session boundaries are the persistence channel (persisted
// "memory", evidence session_entry:#<ordinal>/<role>). If no boundary commits
// entries during the run, evidence degrades honestly to the event stream.
// Durations/timestamps/UUIDs are excluded for byte stability.
import CryptoKit
import Foundation
import PiSwiftAI
import PiSwiftAgent
import PiSwiftCodingAgent

let expectedReads = ["hello.txt", "fib.py"]

func digest(_ text: String) -> String {
    let hash = SHA256.hash(data: Data(text.utf8))
    return "sha256:" + hash.map { String(format: "%02x", $0) }.joined().prefix(16)
}

func finalFromResults(_ results: [String]) -> String {
    "hello.txt \(digest(results[0])) is a three-line greeting file; "
        + "fib.py \(digest(results[1])) defines recursive fib(n) with fib(10)=55; "
        + "both files were read."
}

func emit(_ obj: [String: Any], code: Int32) -> Never {
    guard JSONSerialization.isValidJSONObject(obj),
          let raw = try? JSONSerialization.data(withJSONObject: obj, options: [.sortedKeys]) else {
        FileHandle.standardError.write(Data("emit: invalid JSON\n".utf8))
        Darwin.exit(1)
    }
    var frame = raw
    frame.append(0x0A)
    try? FileHandle.standardOutput.write(contentsOf: frame)
    Darwin.exit(code)
}

func textOfBlocks(_ blocks: [ContentBlock]) -> String {
    var text = ""
    for block in blocks {
        if case .text(let tc) = block { text += tc.text }
    }
    return text
}

// ─── scripted judgment (FauxResponseFactory over the transcript) ──────────────

final class Counter: @unchecked Sendable {
    private let lock = NSLock()
    private var _n = 0
    func bump() { lock.lock(); _n += 1; lock.unlock() }
    var n: Int { lock.lock(); defer { lock.unlock() }; return _n }
}
let providerCalls = Counter()

let judgment: FauxResponseFactory = { transcript, _, _, model in
    providerCalls.bump()
    var results: [String] = []
    for message in transcript.messages {
        if case .toolResult(let result) = message {
            results.append(textOfBlocks(result.content))
        }
    }
    if results.count < expectedReads.count {
        let call = ToolCall(
            id: "call-\(results.count)",
            name: "read",
            arguments: ["path": AnyCodable(expectedReads[results.count])]
        )
        return AssistantMessage(
            content: [.toolCall(call)],
            api: model.api,
            provider: model.provider,
            model: model.id,
            usage: Usage(input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: UsageCost()),
            stopReason: .toolUse
        )
    }
    return AssistantMessage(
        content: [.text(TextContent(text: finalFromResults(results)))],
        api: model.api,
        provider: model.provider,
        model: model.id,
        usage: Usage(input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: UsageCost()),
        stopReason: .stop
    )
}

// ─── recorder: raw events + session entry ordinals during the run ─────────────

struct EntryFact {
    let ordinal: Int
    let role: String
    let toolCallId: String
}

final class Recorder: @unchecked Sendable {
    private let lock = NSLock()
    private var _events: [AgentSessionEvent] = []
    private var _entries: [EntryFact] = []
    private var _nonMessageEntries: [String] = []

    var events: [AgentSessionEvent] { lock.lock(); defer { lock.unlock() }; return _events }
    var entries: [EntryFact] { lock.lock(); defer { lock.unlock() }; return _entries }
    var nonMessageEntries: [String] { lock.lock(); defer { lock.unlock() }; return _nonMessageEntries }

    func record(_ event: AgentSessionEvent) {
        lock.lock(); defer { lock.unlock() }
        _events.append(event)
        if case .entryAppended(let entry) = event {
            if case .message(let messageEntry) = entry {
                var role = "other"
                var toolCallId = ""
                switch messageEntry.message {
                case .system: role = "system"
                case .user: role = "user"
                case .assistant: role = "assistant"
                case .toolResult(let result):
                    role = "toolResult"
                    toolCallId = result.toolCallId
                case .custom: role = "custom"
                }
                _entries.append(EntryFact(ordinal: _entries.count, role: role, toolCallId: toolCallId))
            } else {
                _nonMessageEntries.append(entry.type)
            }
        }
    }
}

// ─── canonical trace builder ──────────────────────────────────────────────────

final class TraceBuilder: @unchecked Sendable {
    private(set) var steps: [[String: Any]] = []
    private var pendingRaw: [String] = []

    private func takeRaw() -> [String]? {
        guard !pendingRaw.isEmpty else { return nil }
        var folded: [String] = []
        for name in pendingRaw where folded.last != name {
            folded.append(name)
        }
        pendingRaw.removeAll()
        return folded
    }

    @discardableResult
    func row(_ phase: String, tool: Any?, _ args: [String: Any], resultDigest: String, evidence: String) -> [String: Any] {
        var row: [String: Any] = [
            "runtime": "piswift",
            "seq": steps.count,
            "phase": phase,
            "tool": tool ?? NSNull(),
            "args": args,
            "result_digest": resultDigest,
            "persisted": "memory",
            "evidence": evidence,
        ]
        if let raw = takeRaw() {
            row["raw"] = raw
        }
        steps.append(row)
        return row
    }

    func rawRow(_ native: String, _ extra: [String: Any] = [:]) {
        var args: [String: Any] = ["native": native]
        for (key, value) in extra { args[key] = value }
        row("raw", tool: nil, args, resultDigest: "", evidence: "memory: in-process session event")
    }

    func fold(_ name: String) {
        pendingRaw.append(name)
    }

    func setEvidence(_ seq: Int, _ evidence: String) {
        steps[seq]["evidence"] = evidence
    }
}

// ─── main ─────────────────────────────────────────────────────────────────────

let fixtures = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "fixtures"
try? FileManager.default.removeItem(atPath: "traces/piswift.jsonl") // stale artifacts must never survive a run

let faux = registerFauxProvider()
faux.setResponses([.factory(judgment), .factory(judgment), .factory(judgment)])
guard let model = faux.getModel() else {
    emit(["ok": false, "error": "no_faux_model"], code: 2)
}

let tmp = NSTemporaryDirectory() + "/piswift-parity-" + UUID().uuidString
try? FileManager.default.createDirectory(atPath: tmp, withIntermediateDirectories: true)
defer { try? FileManager.default.removeItem(atPath: tmp) }

let authStorage = AuthStorage(URL(fileURLWithPath: tmp).appendingPathComponent("auth.json").path)
authStorage.setRuntimeApiKey(model.provider, "parity-driver-key")
let sessionManager = SessionManager.inMemory(fixtures)

let result = await createAgentSession(CreateAgentSessionOptions(
    cwd: fixtures,
    agentDir: tmp,
    authStorage: authStorage,
    model: model,
    offline: true,
    toolNames: ["read"],
    sessionManager: sessionManager,
    settingsManager: SettingsManager.create(tmp, tmp)
))

if let fallback = result.modelFallbackMessage, !fallback.isEmpty {
    // Fail-closed: the faux-only parity contract admits no model fallback.
    emit(["ok": false, "error": "model_fallback", "detail": fallback], code: 5)
}

let recorder = Recorder()
let unsubscribe = result.session.subscribe { event in
    recorder.record(event)
}

var claimPath: [String: String] = [:]
do {
    try await result.session.prompt("Read hello.txt and fib.py, then state the key points of both files.")
} catch {
    unsubscribe()
    emit(["ok": false, "error": "prompt_failed", "detail": "\(error)"], code: 3)
}
unsubscribe()

let builder = TraceBuilder()
var llmSeqs: [Int] = []
var toolSeqByCall: [String: Int] = [:]
var finishSeq: Int? = nil
for event in recorder.events {
    switch event {
    case .agent(.messageStart):
        builder.fold("message_start")
    case .agent(.messageUpdate):
        builder.fold("message_update")
    case .agent(.messageEnd(let message)):
        if case .assistant(let assistant) = message {
            var toolCalls: [[String: Any]] = []
            for block in assistant.content {
                if case .toolCall(let call) = block {
                    var path = ""
                    if let pathValue = call.arguments["path"]?.value as? String { path = pathValue }
                    toolCalls.append(["name": call.name, "path": path])
                }
            }
            let step = builder.row("llm", tool: nil, [
                "stopReason": assistant.stopReason.rawValue,
                "toolCalls": toolCalls,
            ], resultDigest: String(digest(textOfBlocks(assistant.content))), evidence: "pending-resolution")
            llmSeqs.append(step["seq"] as! Int)
        } else {
            var role = "other"
            switch message {
            case .system: role = "system"
            case .user: role = "user"
            case .toolResult: role = "toolResult"
            case .custom: role = "custom"
            case .assistant: break
            }
            builder.fold("message_end:\(role)")
        }
    case .agent(.toolExecutionStart(let toolCallId, let toolName, let args)):
        var path = ""
        if let pathValue = args["path"]?.value as? String { path = pathValue }
        claimPath[toolCallId] = path
        builder.row("claim", tool: toolName, [
            "kind": "tool",
            "toolCallId": toolCallId,
            "path": path,
        ], resultDigest: "", evidence: "memory: dispatch tool_call:\(toolCallId)")
    case .agent(.toolExecutionUpdate):
        builder.fold("tool_update")
    case .agent(.toolExecutionEnd(let toolCallId, let toolName, let agentResult, _)):
        let step = builder.row("tool", tool: toolName, [
            "path": claimPath[toolCallId] ?? "",
        ], resultDigest: String(digest(textOfBlocks(agentResult.content))), evidence: "pending-resolution")
        toolSeqByCall[toolCallId] = step["seq"] as! Int
    case .agent(.agentEnd(let messages)):
        var status = "completed"
        for message in messages.reversed() {
            if case .assistant(let assistant) = message {
                if assistant.stopReason != .stop {
                    status = assistant.stopReason.rawValue
                }
                break
            }
        }
        finishSeq = builder.row("finish", tool: nil, [
            "status": status,
        ], resultDigest: "", evidence: "pending-resolution")["seq"] as? Int
    case .agent(.agentStart):
        builder.rawRow("agent_start")
    case .agent(.turnStart):
        builder.rawRow("turn_start")
    case .agent(.turnEnd):
        builder.rawRow("turn_end")
    case .agentSettled:
        builder.rawRow("agent_settled")
    case .autoCompactionStart:
        builder.rawRow("auto_compaction_start")
    case .autoCompactionEnd:
        builder.rawRow("auto_compaction_end")
    case .autoRetryStart:
        builder.rawRow("auto_retry_start")
    case .autoRetryEnd:
        builder.rawRow("auto_retry_end")
    case .entryAppended(let entry):
        // Message entries fold like pi's entry_added (evidence channel);
        // non-message entries surface as raw rows with their entry type.
        if case .message(let messageEntry) = entry {
            var role = "other"
            switch messageEntry.message {
            case .system: role = "system"
            case .user: role = "user"
            case .assistant: role = "assistant"
            case .toolResult: role = "toolResult"
            case .custom: role = "custom"
            }
            builder.fold("entry_added:\(role)")
        } else {
            builder.rawRow("entry_added", ["entryType": entry.type])
        }
    }
}

// ─── post-run evidence resolution ─────────────────────────────────────────────

// Authoritative persistence record: the post-run session manager log. The
// entryAppended events observed during the run are corroboration only (their
// ordinals are observation order, not session order, and in-memory sessions
// commit further entries at boundaries after the events stop).
func jsonKey(_ obj: Any) -> String {
    guard let data = try? JSONSerialization.data(withJSONObject: obj, options: [.sortedKeys]) else { return "" }
    return String(data: data, encoding: .utf8) ?? ""
}

struct AuthFact {
    let ordinal: Int
    let role: String
    let toolCallId: String
    let text: String
    let stopReason: String
    let toolCalls: [[String: Any]]
}

let authoritative = sessionManager.getEntries()
var authFacts: [AuthFact] = []
for (index, entry) in authoritative.enumerated() {
    guard case .message(let messageEntry) = entry else { continue }
    var role = "other"
    var toolCallId = ""
    var text = ""
    var stopReason = ""
    var toolCalls: [[String: Any]] = []
    switch messageEntry.message {
    case .system: role = "system"
    case .user: role = "user"
    case .assistant(let assistant):
        role = "assistant"
        text = textOfBlocks(assistant.content)
        stopReason = assistant.stopReason.rawValue
        for block in assistant.content {
            if case .toolCall(let call) = block {
                var path = ""
                if let pathValue = call.arguments["path"]?.value as? String { path = pathValue }
                toolCalls.append(["name": call.name, "path": path])
            }
        }
    case .toolResult(let result):
        role = "toolResult"
        toolCallId = result.toolCallId
        text = textOfBlocks(result.content)
    case .custom: role = "custom"
    }
    authFacts.append(AuthFact(ordinal: index, role: role, toolCallId: toolCallId, text: text, stopReason: stopReason, toolCalls: toolCalls))
}

// Corroboration: the event-observed message sequence must be an in-order
// subsequence of the authoritative log (same roles, same toolCallIds).
do {
    var cursor = 0
    for fact in recorder.entries {
        var matched = false
        while cursor < authFacts.count {
            let candidate = authFacts[cursor]
            cursor += 1
            if candidate.role == fact.role && (fact.toolCallId.isEmpty || candidate.toolCallId == fact.toolCallId) {
                matched = true
                break
            }
        }
        if !matched {
            emit(["ok": false, "error": "entry_event_divergence",
                  "detail": "observed \(fact.role)/\(fact.toolCallId) missing from session log"], code: 5)
        }
    }
}

let assistantFacts = authFacts.filter { $0.role == "assistant" }
if assistantFacts.count != llmSeqs.count {
    emit(["ok": false, "error": "evidence_mismatch",
          "detail": "assistant entries \(assistantFacts.count) != llm steps \(llmSeqs.count)"], code: 5)
}
for (index, seq) in llmSeqs.enumerated() {
    let fact = assistantFacts[index]
    let step = builder.steps[seq]
    let args = step["args"] as? [String: Any] ?? [:]
    if digest(fact.text) != (step["result_digest"] as? String ?? "") {
        emit(["ok": false, "error": "evidence_payload",
              "detail": "assistant entry #\(fact.ordinal) text digest != llm step seq \(seq)"], code: 5)
    }
    if fact.stopReason != (args["stopReason"] as? String ?? "") {
        emit(["ok": false, "error": "evidence_payload",
              "detail": "assistant entry #\(fact.ordinal) stopReason != llm step seq \(seq)"], code: 5)
    }
    if jsonKey(fact.toolCalls) != jsonKey(args["toolCalls"] ?? []) {
        emit(["ok": false, "error": "evidence_payload",
              "detail": "assistant entry #\(fact.ordinal) toolCalls != llm step seq \(seq)"], code: 5)
    }
    builder.setEvidence(seq, "session_entry:#\(fact.ordinal)/assistant (SessionManager.inMemory)")
}
for (callId, seq) in toolSeqByCall {
    guard let fact = authFacts.first(where: { $0.role == "toolResult" && $0.toolCallId == callId }) else {
        emit(["ok": false, "error": "evidence_mismatch", "detail": "no toolResult session entry for \(callId)"], code: 5)
    }
    let step = builder.steps[seq]
    if digest(fact.text) != (step["result_digest"] as? String ?? "") {
        emit(["ok": false, "error": "evidence_payload",
              "detail": "toolResult entry #\(fact.ordinal) digest != tool step seq \(seq)"], code: 5)
    }
    builder.setEvidence(seq, "session_entry:#\(fact.ordinal)/toolResult (SessionManager.inMemory)")
}
if let finish = finishSeq {
    builder.setEvidence(finish, "memory: agent_end; \(authoritative.count) session entries (SessionManager.getEntries)")
}

// Provider contract: exactly three calls (two tool turns + one final turn).
if providerCalls.n != 3 {
    emit(["ok": false, "error": "provider_calls",
          "detail": "expected 3 provider calls, got \(providerCalls.n)"], code: 5)
}

// Final answer FROM THE PERSISTED final assistant session entry,
// cross-verified against the event stream and the deterministic contract.
let finalText = assistantFacts.last!.text
do {
    var eventFinal = ""
    for event in recorder.events.reversed() {
        if case .agent(.messageEnd(let message)) = event, case .assistant(let assistant) = message {
            eventFinal = textOfBlocks(assistant.content)
            break
        }
    }
    if digest(finalText) != digest(eventFinal) {
        emit(["ok": false, "error": "final_mismatch",
              "detail": "persisted final assistant text != event-stream assistant text"], code: 5)
    }
    var persistedResults: [String] = []
    for callId in ["call-0", "call-1"] {
        guard let fact = authFacts.first(where: { $0.role == "toolResult" && $0.toolCallId == callId }) else {
            emit(["ok": false, "error": "final_mismatch", "detail": "missing toolResult entry for \(callId)"], code: 5)
        }
        persistedResults.append(fact.text)
    }
    if finalText != finalFromResults(persistedResults) {
        emit(["ok": false, "error": "final_mismatch",
              "detail": "final text != deterministic contract over persisted results"], code: 5)
    }
}

// ─── write the trace ──────────────────────────────────────────────────────────

try? FileManager.default.createDirectory(atPath: "traces", withIntermediateDirectories: true)
let tracePath = "traces/piswift.jsonl"
var lines: [String] = []
for step in builder.steps {
    if let raw = try? JSONSerialization.data(withJSONObject: step, options: [.sortedKeys]),
       let line = String(data: raw, encoding: .utf8) {
        lines.append(line)
    } else {
        emit(["ok": false, "error": "encode_failed"], code: 6)
    }
}
let finalRow: [String: Any] = ["runtime": "piswift", "final": finalText]
if let raw = try? JSONSerialization.data(withJSONObject: finalRow, options: [.sortedKeys]),
   let line = String(data: raw, encoding: .utf8) {
    lines.append(line)
} else {
    emit(["ok": false, "error": "encode_failed"], code: 6)
}
do {
    try lines.joined(separator: "\n").appending("\n").write(toFile: tracePath, atomically: true, encoding: .utf8)
} catch {
    emit(["ok": false, "error": "write_failed", "detail": "\(error)"], code: 6)
}

emit([
    "ok": true,
    "trace": tracePath,
    "steps": builder.steps.count,
    "final": finalText,
    "providerCalls": providerCalls.n,
    "entriesCommitted": recorder.entries.count,
    "entriesPostRun": authoritative.count,
    "sessionMessages": result.session.messages.count,
    "activeTools": result.session.getActiveToolNames(),
], code: 0)
