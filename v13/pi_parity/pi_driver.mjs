// pi_parity pi-side driver: run the two-file read task through the REAL pi
// agent harness (packages/agent) with a deterministic scripted provider, and
// emit a canonical schema-v2 trace at traces/pi.jsonl.
//
// Framework surface actually used (pi checkout /Users/wxl/Projects/pi):
//   - AgentHarness.create (packages/agent/src/harness/agent-harness.ts)
//   - Lane.prompt -> accept + drive to completion
//   - harness read tool (packages/agent/src/harness/tools/read.ts) as the ONLY
//     active tool (activeToolNames limits the tool face)
//   - NodeExecutionEnv with cwd pinned to the fixture root
//   - fauxProvider/fauxAssistantMessage/fauxToolCall (packages/ai) fed by a
//     judgment function over the transcript (isomorphic to the pg side's
//     overrides_for/final_from_results: counts tool results, digests content)
//
// Canonical mapping (source of truth for the README table; do not drift):
//   message_end   -> llm    (assistant message; evidence = session entry ordinal)
//   tool_start    -> claim  (framework dispatch of a tool call)
//   tool_end      -> tool   (tool execution result)
//   run_end       -> finish (status completed)
//   message_start/message_update -> folded into the following llm step's raw[]
//   entry_added   -> evidence channel (session entry ordinals), raw row only
//                    for entries with no canonical step (e.g. the user prompt)
//   turn_start/turn_end/run_start and any other native type -> phase "raw" row
//   judge/parse/advance have NO pi native equivalent (framework-internal loop
//   decisions) and are never fabricated on this side.
//
// Persistence honesty: MemoryStorage (in-process) -> persisted "memory" with
// session-entry-ordinal evidence; nothing is written to disk by the framework.
import { register } from "node:module";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

await register(new URL("./pi_resolve_hook.mjs", import.meta.url));

const { createModels, fauxAssistantMessage, fauxProvider, fauxToolCall } = await import("@earendil-works/pi-ai");
const { AgentHarness, BACKGROUND_CONTEXT, StorageBackedSession, createReadTool } = await import(
	"@earendil-works/pi-agent-core"
);
const { MemoryStorage } = await import("/Users/wxl/Projects/pi/packages/agent/src/harness/session/memory.ts");
const { NodeExecutionEnv } = await import("/Users/wxl/Projects/pi/packages/agent/src/harness/env/nodejs.ts");

const STAGE_DIR = path.dirname(fileURLToPath(import.meta.url));
const FIXTURES = path.join(STAGE_DIR, "fixtures");
const TRACE_PATH = path.join(STAGE_DIR, "traces", "pi.jsonl");
const RUNTIME = "pi";
const EXPECTED_READS = ["hello.txt", "fib.py"];

function digest(text) {
	return "sha256:" + crypto.createHash("sha256").update(text, "utf8").digest("hex").slice(0, 16);
}

function finalFromResults(results) {
	const [hello, fib] = results;
	return (
		`hello.txt ${digest(hello)} is a three-line greeting file; ` +
		`fib.py ${digest(fib)} defines recursive fib(n) with fib(10)=55; ` +
		"both files were read."
	);
}

function textOfContent(content) {
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return "";
	return content
		.filter((block) => block && block.type === "text" && typeof block.text === "string")
		.map((block) => block.text)
		.join("");
}

// Deterministic scripted judgment, isomorphic to the pg ring's judge:
// - no tool results yet  -> emit the next read tool call (hello.txt then fib.py)
// - both results present -> final answer digesting the actual results.
function decideResponse(context) {
	const messages = (context && context.messages) || [];
	const results = messages.filter((message) => message.role === "toolResult");
	if (results.length >= EXPECTED_READS.length) {
		return fauxAssistantMessage(finalFromResults(results.map((message) => textOfContent(message.content))), {
			timestamp: 20,
		});
	}
	return fauxAssistantMessage(
		[fauxToolCall("read", { path: EXPECTED_READS[results.length] }, { id: `call-${results.length}` })],
		{ stopReason: "toolUse", timestamp: 20 },
	);
}

function emit(payload, code) {
	fs.writeSync(1, Buffer.from(`${JSON.stringify(payload)}\n`));
	process.exit(code);
}

async function main() {
	const storage = new MemoryStorage({ now: () => 100 });
	const session = new StorageBackedSession(
		{ id: "pi-parity-1", createdAt: 1, storageVersion: 1 },
		storage,
	);
	const faux = fauxProvider();
	const models = createModels();
	models.setProvider(faux.provider);
	// Three provider calls: read hello.txt -> read fib.py -> final answer.
	faux.setResponses([decideResponse, decideResponse, decideResponse]);

	const env = new NodeExecutionEnv({ cwd: FIXTURES });
	const readTool = createReadTool();
	const steps = [];
	const entryOrder = []; // entry ids in entry_added order (deterministic ordinals)
	const entryById = new Map();
	const claimPathByCallId = new Map();
	const toolStepByCallId = new Map(); // tool_end steps, resolved after the run
	const llmStepsInOrder = []; // assistant llm steps, resolved after the run
	let pendingRaw = []; // native types folded into the next canonical step

	const row = (fields) => {
		const step = { runtime: RUNTIME, seq: steps.length, ...fields };
		steps.push(step);
		return step;
	};
	const rawRow = (native, extra = {}) =>
		row({ phase: "raw", tool: null, args: { native, ...extra }, result_digest: "", persisted: "memory", evidence: "memory: in-process harness event" });

	const on = (harness, type, handler) => harness.events.on(type, handler);

	// Fold native streaming frames (message_start/update, folded entry_added)
	// into the next canonical step's raw[] array, collapsing consecutive
	// duplicates: the faux provider's streaming frame COUNT is a transport
	// artifact that varies run to run, while the event types themselves are
	// semantic and must never be dropped.
	const takeRaw = () => {
		if (pendingRaw.length === 0) return undefined;
		const collapsed = [];
		for (const type of pendingRaw.splice(0)) {
			if (collapsed[collapsed.length - 1] !== type) collapsed.push(type);
		}
		return collapsed.length > 0 ? { raw: collapsed } : undefined;
	};
	const listeners = {
		run_start: () => rawRow("run_start"),
		run_resume: () => rawRow("run_resume"),
		run_suspend: () => rawRow("run_suspend"),
		operation_abort: () => rawRow("operation_abort"),
		run_end: (event) => {
			row({
				phase: "finish",
				tool: null,
				args: { status: event.status },
				result_digest: "",
				persisted: "memory",
				evidence: "pending-resolution",
				...(takeRaw()),
			});
		},
		fault: () => rawRow("fault"),
		handler_error: () => rawRow("handler_error"),
		turn_start: () => rawRow("turn_start"),
		turn_end: () => rawRow("turn_end"),
		retry_scheduled: () => rawRow("retry_scheduled"),
		retry_start: () => rawRow("retry_start"),
		retry_end: () => rawRow("retry_end"),
		message_start: () => pendingRaw.push("message_start"),
		message_update: () => pendingRaw.push("message_update"),
		message_end: (event) => {
			const message = event.message;
			if (!message || message.role !== "assistant") {
				pendingRaw.push(`message_end:${message && message.role}`);
				return;
			}
			const toolCalls = message.content.filter((block) => block.type === "toolCall");
			const step = row({
				phase: "llm",
				tool: null,
				args: {
					stopReason: message.stopReason,
					toolCalls: toolCalls.map((call) => ({ name: call.name, path: call.arguments && call.arguments.path })),
				},
				result_digest: digest(textOfContent(message.content)),
				persisted: "memory",
				evidence: "pending-resolution",
				...(takeRaw()),
			});
			llmStepsInOrder.push(step);
		},
		tool_start: (event) => {
			claimPathByCallId.set(event.toolCallId, event.args && event.args.path);
			row({
				phase: "claim",
				tool: event.toolName,
				args: { kind: "tool", toolCallId: event.toolCallId, path: event.args && event.args.path },
				result_digest: "",
				persisted: "memory",
				evidence: `memory: dispatch tool_call:${event.toolCallId}`,
				...(takeRaw()),
			});
		},
		tool_update: () => pendingRaw.push("tool_update"),
		tool_end: (event) => {
			const text = textOfContent((event.result && event.result.content) || []);
			const step = row({
				phase: "tool",
				tool: event.toolName,
				args: { path: claimPathByCallId.get(event.toolCallId) },
				result_digest: digest(text),
				persisted: "memory",
				evidence: "pending-resolution",
				...(takeRaw()),
			});
			toolStepByCallId.set(event.toolCallId, step);
		},
		entry_added: (event) => {
			const entry = event.entry;
			entryOrder.push(entry.id);
			entryById.set(entry.id, entry);
			const message = entry.type === "message" ? entry.message : undefined;
			if (message && message.role === "user") {
				rawRow("entry_added", { entry: "user/message" });
				return;
			}
			// assistant/toolResult entry_added events fold into the raw bucket of
			// the next canonical step; their ordinals are consumed by the
			// post-run evidence resolution below.
			pendingRaw.push(`entry_added:${message ? message.role : entry.type}`);
		},
		queue_update: () => rawRow("queue_update"),
		value_update: () => rawRow("value_update"),
		config_update: () => rawRow("config_update"),
		compaction_start: () => rawRow("compaction_start"),
		compaction_end: () => rawRow("compaction_end"),
		navigation_start: () => rawRow("navigation_start"),
		navigation_end: () => rawRow("navigation_end"),
		lane_created: () => rawRow("lane_created"),
		usage: () => rawRow("usage"),
	};
	const originalToolStart = listeners.tool_start;
	listeners.tool_start = (event) => {
		claimPathByCallId.set(event.toolCallId, event.args && event.args.path);
		originalToolStart(event);
	};

	const { harness } = await AgentHarness.create(
		{
			session,
			models,
			model: faux.getModel(),
			thinkingLevel: "off",
			activeToolNames: ["read"],
			tools: [readTool],
			toolContext: { env },
			retry: { enabled: false, maxRetries: 0, baseDelayMs: 0 },
			toolExecution: "sequential",
		},
		BACKGROUND_CONTEXT,
	);
	for (const [type, handler] of Object.entries(listeners)) on(harness, type, handler);

	const lane = await harness.lane("main", BACKGROUND_CONTEXT);
	const run = await lane.prompt(
		"Read hello.txt and fib.py, then state the key points of both files.",
		undefined,
		BACKGROUND_CONTEXT,
	);
	if (!(run && run.ok && run.value && run.value.kind === "run" && run.value.status === "completed")) {
		emit({ ok: false, error: "run_failed", detail: JSON.stringify(run && run.value) }, 4);
	}

	const finalEntry = [...entryOrder].reverse().find((id) => {
		const entry = entryById.get(id);
		return entry && entry.type === "message" && entry.message.role === "assistant";
	});
	const finalText = textOfContent(entryById.get(finalEntry).message.content);

	// Post-run evidence resolution: message_end/tool_end fire before the
	// corresponding entry_added commits, so pair steps to persisted entries
	// only once the session tip is final.
	const assistantOrdinals = [];
	const toolResultOrdinalByCallId = new Map();
	entryOrder.forEach((id, index) => {
		const entry = entryById.get(id);
		if (entry.type !== "message") return;
		const message = entry.message;
		if (message.role === "assistant") assistantOrdinals.push(index);
		else if (message.role === "toolResult") toolResultOrdinalByCallId.set(message.toolCallId, index);
	});
	if (assistantOrdinals.length !== llmStepsInOrder.length) {
		emit({ ok: false, error: "evidence_mismatch", detail: `assistant entries ${assistantOrdinals.length} != llm steps ${llmStepsInOrder.length}` }, 5);
	}
	llmStepsInOrder.forEach((step, index) => {
		step.evidence = `session_entry:#${assistantOrdinals[index]}/assistant (MemoryStorage)`;
	});
	for (const [callId, step] of toolStepByCallId) {
		const ordinal = toolResultOrdinalByCallId.get(callId);
		if (ordinal === undefined) emit({ ok: false, error: "evidence_mismatch", detail: `no toolResult entry for ${callId}` }, 5);
		step.evidence = `session_entry:#${ordinal}/toolResult (MemoryStorage)`;
	}
	const finishStep = steps.findLast((step) => step.phase === "finish");
	if (finishStep) {
		finishStep.evidence = `memory: run_end completed; session tip entry #${entryOrder.length - 1} (MemoryStorage)`;
	}

	fs.mkdirSync(path.dirname(TRACE_PATH), { recursive: true });
	const lines = steps.map((step) => JSON.stringify(step));
	lines.push(JSON.stringify({ runtime: RUNTIME, final: finalText }));
	fs.writeFileSync(TRACE_PATH, lines.join("\n") + "\n", "utf8");

	await harness.close(BACKGROUND_CONTEXT);
	await session.close(BACKGROUND_CONTEXT);

	emit({ ok: true, trace: TRACE_PATH, steps: steps.length, final: finalText }, 0);
}

try {
	await main();
} catch (error) {
	process.stderr.write(`${error && error.stack ? error.stack : String(error)}\n`);
	process.exit(1);
}
