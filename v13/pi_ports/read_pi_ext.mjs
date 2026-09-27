import fs from "node:fs";
import { register } from "node:module";
import path from "node:path";
import { pathToFileURL } from "node:url";

const PI_READ_TS = "/Users/wxl/Projects/pi/packages/coding-agent/src/core/tools/read.ts";
const PI_PKG = "/Users/wxl/Projects/pi/packages/coding-agent/package.json";
const IMAGE_EXTS = new Set(["jpg", "jpeg", "png", "gif", "webp", "bmp"]);

await register(new URL("./pi_resolve_hook.mjs", import.meta.url));

class ToolError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "ToolError";
    this.code = code;
  }
}

function emit(obj, code) {
  const frame = Buffer.from(`${JSON.stringify(obj)}\n`);
  let offset = 0;
  try {
    while (offset < frame.length) {
      const wrote = fs.writeSync(1, frame, offset, frame.length - offset);
      if (wrote <= 0) {
        process.exit(1);
      }
      offset += wrote;
    }
  } catch {
    process.exit(1);
  }
  process.exit(code);
}

function takeInt(value) {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    return undefined;
  }
  return value;
}

function piVersion() {
  try {
    return JSON.parse(fs.readFileSync(PI_PKG, "utf8")).version ?? "unknown";
  } catch {
    return "unknown";
  }
}

function realpathLoose(target) {
  const missing = [];
  let cur = target;
  for (;;) {
    try {
      const resolved = fs.realpathSync(cur);
      if (missing.length === 0) {
        return resolved;
      }
      return path.join(resolved, ...missing.reverse());
    } catch (err) {
      if (err && (err.code === "ENOENT" || err.code === "ENOTDIR")) {
        const parent = path.dirname(cur);
        if (parent === cur) {
          throw new ToolError("read_failed", err.message);
        }
        missing.push(path.basename(cur));
        cur = parent;
        continue;
      }
      const message = err instanceof Error ? err.message : String(err);
      throw new ToolError("read_failed", message);
    }
  }
}

function resolveFenced(root, raw) {
  if (typeof root !== "string" || root.trim() === "") {
    throw new ToolError("invalid_params", "root must be a string");
  }
  if (typeof raw !== "string") {
    throw new ToolError("invalid_params", "path must be a string");
  }
  if (raw.includes("\0")) {
    throw new ToolError("path_outside_workspace", "path contains NUL");
  }
  if (raw.trim() === "") {
    throw new ToolError("invalid_params", "path must not be empty");
  }
  let rootReal;
  try {
    rootReal = fs.realpathSync(root);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    throw new ToolError("read_failed", message);
  }
  const cand = raw.startsWith("/") ? raw : path.join(rootReal, raw);
  const checked = realpathLoose(path.normalize(cand));
  if (checked === rootReal || checked.startsWith(rootReal + path.sep)) {
    return { rootReal, absolutePath: checked };
  }
  throw new ToolError("path_outside_workspace", "path outside workspace");
}

function isImagePath(absPath) {
  const ext = path.extname(absPath).replace(/^\./, "").toLowerCase();
  return IMAGE_EXTS.has(ext);
}

function assertRegularFile(absolutePath) {
  let info;
  try {
    info = fs.lstatSync(absolutePath);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    throw new ToolError("read_failed", message);
  }
  if (!info.isFile()) {
    throw new ToolError("read_failed", "not a regular file");
  }
}

function validateTextBytes(absolutePath) {
  assertRegularFile(absolutePath);
  let buffer;
  try {
    buffer = fs.readFileSync(absolutePath);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    throw new ToolError("read_failed", message);
  }
  try {
    new TextDecoder("utf-8", { fatal: true }).decode(buffer);
  } catch {
    throw new ToolError("read_failed", "not utf-8");
  }
  if (buffer.includes(0)) {
    throw new ToolError("read_failed", "contains NUL");
  }
}

function textFromToolResult(executed) {
  const content = executed && executed.content;
  if (!Array.isArray(content)) {
    throw new ToolError("read_failed", "framework read returned no text");
  }
  const block = content.find((item) => item && item.type === "text" && typeof item.text === "string");
  if (!block) {
    throw new ToolError("read_failed", "framework read returned no text");
  }
  return block.text;
}

function restoreCallerPathInBashHint(text, executedPath, callerPath) {
  if (executedPath === callerPath) {
    return text;
  }
  const marker = "sed -n '";
  const at = text.lastIndexOf(marker);
  if (at < 0 || !text.slice(at).includes(executedPath)) {
    return text;
  }
  return text.slice(0, at) + text.slice(at).split(executedPath).join(callerPath);
}

async function readViaFramework(rootReal, absolutePath, callerPath, offset, limit) {
  const mod = await import(pathToFileURL(PI_READ_TS).href);
  if (typeof mod.createReadTool !== "function") {
    throw new ToolError("read_failed", "createReadTool is not exported");
  }
  const tool = mod.createReadTool(rootReal);
  process.stderr.write(
    `pi_ports evidence: package=@earendil-works/pi-coding-agent version=${piVersion()} createReadTool=${PI_READ_TS} tool=${tool.name} execute=AgentTool.execute path=fenced-absolute\n`,
  );
  const params = { path: absolutePath };
  if (offset !== undefined) {
    params.offset = offset;
  }
  if (limit !== undefined) {
    params.limit = limit;
  }
  try {
    const executed = await tool.execute("pi-ports-read", params);
    return restoreCallerPathInBashHint(textFromToolResult(executed), absolutePath, callerPath);
  } catch (err) {
    if (err instanceof ToolError) {
      throw err;
    }
    const message = err instanceof Error ? err.message : String(err);
    if (/Offset .+ is beyond end of file/.test(message)) {
      throw new ToolError("offset_out_of_range", message);
    }
    throw new ToolError("read_failed", message);
  }
}

async function main() {
  const raw = fs.readFileSync(0);
  let text;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(raw);
  } catch {
    process.exit(1);
  }
  if (text.trim() === "") {
    emit({ ok: false, error: "invalid_params", message: "empty stdin" }, 3);
  }
  let req;
  try {
    req = JSON.parse(text);
  } catch {
    process.exit(1);
  }
  if (req === null || typeof req !== "object" || Array.isArray(req)) {
    process.exit(1);
  }
  if (typeof req.root !== "string" || typeof req.path !== "string") {
    emit({ ok: false, error: "invalid_params", message: "root and path must be strings" }, 3);
  }
  if (req.path.trim() === "") {
    emit({ ok: false, error: "invalid_params", message: "path must not be empty" }, 3);
  }
  let limit = takeInt(req.limit);
  if (typeof limit === "number" && limit < 0) {
    limit = 0;
  }
  const fenced = resolveFenced(req.root, req.path);
  if (isImagePath(fenced.absolutePath)) {
    throw new ToolError("image_unsupported", "image files are not supported");
  }
  validateTextBytes(fenced.absolutePath);
  const result = await readViaFramework(
    fenced.rootReal,
    fenced.absolutePath,
    req.path,
    takeInt(req.offset),
    limit,
  );
  emit({ ok: true, result }, 0);
}

try {
  await main();
} catch (err) {
  if (err instanceof ToolError) {
    emit({ ok: false, error: err.code, message: err.message }, 3);
  }
  process.stderr.write(`${err instanceof Error ? err.stack || err.message : String(err)}\n`);
  process.exit(1);
}
