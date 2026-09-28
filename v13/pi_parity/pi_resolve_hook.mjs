import { isBuiltin } from "node:module";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const stageDir = path.dirname(fileURLToPath(import.meta.url));
const parentURL = pathToFileURL(path.join(stageDir, "package.json")).href;
const PI_ROOT = "/Users/wxl/Projects/pi";
const WORKSPACE_ENTRIES = {
	"@earendil-works/pi-tui": path.join(PI_ROOT, "packages/tui/src/index.ts"),
	"@earendil-works/pi-ai": path.join(PI_ROOT, "packages/ai/src/index.ts"),
	"@earendil-works/pi-agent-core": path.join(PI_ROOT, "packages/agent/src/index.ts"),
};

function isRelativeOrBuiltin(specifier) {
	return (
		isBuiltin(specifier) ||
		specifier.startsWith(".") ||
		specifier.startsWith("/") ||
		specifier.startsWith("#") ||
		specifier.startsWith("file:") ||
		specifier.startsWith("node:") ||
		specifier.startsWith("data:")
	);
}

export async function resolve(specifier, context, nextResolve) {
	const workspace = WORKSPACE_ENTRIES[specifier];
	if (workspace) {
		return { url: pathToFileURL(workspace).href, shortCircuit: true };
	}
	if (isRelativeOrBuiltin(specifier)) {
		return nextResolve(specifier, context);
	}
	return nextResolve(specifier, { ...context, parentURL });
}
