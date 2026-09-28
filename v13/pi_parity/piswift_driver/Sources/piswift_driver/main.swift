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

let judgment: FauxResponseFactory = { transcript, _, _, model in
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
    FileHandle.standardError.write(Data("modelFallbackMessage: \(fallback)\n".utf8))
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

var entries = recorder.entries
if entries.isEmpty {
    // In-memory sessions commit entries without always emitting entryAppended
    // during the run; the post-run session manager log is the authoritative
    // in-memory persistence record.
    for (index, entry) in sessionManager.getEntries().enumerated() {
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
            entries.append(EntryFact(ordinal: index, role: role, toolCallId: toolCallId))
        }
    }
}
let assistantOrdinals = entries.filter { $0.role == "assistant" }.map { $0.ordinal }
var toolOrdinalByCall: [String: Int] = [:]
for fact in entries where fact.role == "toolResult" {
    toolOrdinalByCall[fact.toolCallId] = fact.ordinal
}

if assistantOrdinals.count == llmSeqs.count {
    for (index, seq) in llmSeqs.enumerated() {
        builder.setEvidence(seq, "session_entry:#\(assistantOrdinals[index])/assistant (SessionManager.inMemory)")
    }
} else {
    // Honest degradation: no assistant entries were committed at boundaries.
    for seq in llmSeqs {
        builder.setEvidence(seq, "memory: message_end event (no boundary commit observed)")
    }
}
for (callId, seq) in toolSeqByCall {
    if let ordinal = toolOrdinalByCall[callId] {
        builder.setEvidence(seq, "session_entry:#\(ordinal)/toolResult (SessionManager.inMemory)")
    } else {
        builder.setEvidence(seq, "memory: toolExecutionEnd event (no boundary commit observed)")
    }
}
if let finish = finishSeq {
    builder.setEvidence(finish, "memory: agent_end; \(entries.count) session entries committed (SessionManager.inMemory)")
}

var finalText = ""
for event in recorder.events.reversed() {
    if case .agent(.messageEnd(let message)) = event, case .assistant(let assistant) = message {
        finalText = textOfBlocks(assistant.content)
        break
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
    "entriesCommitted": entries.count,
    "entriesPostRun": sessionManager.getEntries().count,
    "sessionMessages": result.session.messages.count,
    "activeTools": result.session.getActiveToolNames(),
], code: 0)
