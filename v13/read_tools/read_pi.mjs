// Ported & modified from @earendil-works/pi-coding-agent 0.80.3 (MIT).
// Copyright (c) 2025 Mario Zechner
// Sources: packages/coding-agent/src/core/tools/read.ts
//          packages/coding-agent/src/core/tools/truncate.ts
// Deviations: explicit root fence (no resolveReadPathAsync, no ~ expansion);
// image extensions return image_unsupported and do not include file bytes.
// TUI, highlighting, and processImage are not copied.
// See THIRD_PARTY_NOTICES.md.

import fs from "node:fs";
import path from "node:path";

const DEFAULT_MAX_LINES = 2000;
const DEFAULT_MAX_BYTES = 50 * 1024;
const IMAGE_EXTS = new Set(["jpg", "jpeg", "png", "gif", "webp", "bmp"]);

class ToolError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

function emit(obj, code) {
  process.stdout.write(`${JSON.stringify(obj)}\n`);
  process.exit(code);
}

function takeInt(value) {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    return undefined;
  }
  return value;
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
  if (raw.includes("\0")) {
    throw new ToolError("path_outside_workspace", "path contains NUL");
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
    return checked;
  }
  throw new ToolError("path_outside_workspace", "path outside workspace");
}

function isImagePath(absPath) {
  const ext = path.extname(absPath).replace(/^\./, "").toLowerCase();
  return IMAGE_EXTS.has(ext);
}

function splitLinesForCounting(content) {
  if (content.length === 0) {
    return [];
  }
  const lines = content.split("\n");
  if (content.endsWith("\n")) {
    lines.pop();
  }
  return lines;
}

function formatSize(bytes) {
  if (bytes < 1024) {
    return `${bytes}B`;
  } else if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)}KB`;
  } else {
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  }
}

function truncateHead(content, options = {}) {
  const maxLines = options.maxLines ?? DEFAULT_MAX_LINES;
  const maxBytes = options.maxBytes ?? DEFAULT_MAX_BYTES;

  const totalBytes = Buffer.byteLength(content, "utf-8");
  const lines = splitLinesForCounting(content);
  const totalLines = lines.length;

  if (totalLines <= maxLines && totalBytes <= maxBytes) {
    return {
      content,
      truncated: false,
      truncatedBy: null,
      totalLines,
      totalBytes,
      outputLines: totalLines,
      outputBytes: totalBytes,
      lastLinePartial: false,
      firstLineExceedsLimit: false,
      maxLines,
      maxBytes,
    };
  }

  const firstLineBytes = Buffer.byteLength(lines[0], "utf-8");
  if (firstLineBytes > maxBytes) {
    return {
      content: "",
      truncated: true,
      truncatedBy: "bytes",
      totalLines,
      totalBytes,
      outputLines: 0,
      outputBytes: 0,
      lastLinePartial: false,
      firstLineExceedsLimit: true,
      maxLines,
      maxBytes,
    };
  }

  const outputLinesArr = [];
  let outputBytesCount = 0;
  let truncatedBy = "lines";

  for (let i = 0; i < lines.length && i < maxLines; i++) {
    const line = lines[i];
    const lineBytes = Buffer.byteLength(line, "utf-8") + (i > 0 ? 1 : 0);

    if (outputBytesCount + lineBytes > maxBytes) {
      truncatedBy = "bytes";
      break;
    }

    outputLinesArr.push(line);
    outputBytesCount += lineBytes;
  }

  if (outputLinesArr.length >= maxLines && outputBytesCount <= maxBytes) {
    truncatedBy = "lines";
  }

  const outputContent = outputLinesArr.join("\n");
  const finalOutputBytes = Buffer.byteLength(outputContent, "utf-8");

  return {
    content: outputContent,
    truncated: true,
    truncatedBy,
    totalLines,
    totalBytes,
    outputLines: outputLinesArr.length,
    outputBytes: finalOutputBytes,
    lastLinePartial: false,
    firstLineExceedsLimit: false,
    maxLines,
    maxBytes,
  };
}

function readText(root, rawPath, offset, limit) {
  const absolutePath = resolveFenced(root, rawPath);
  if (isImagePath(absolutePath)) {
    throw new ToolError("image_unsupported", "image files are not supported");
  }
  let buffer;
  try {
    buffer = fs.readFileSync(absolutePath);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    throw new ToolError("read_failed", message);
  }
  let textContent;
  try {
    textContent = new TextDecoder("utf-8", { fatal: true }).decode(buffer);
  } catch {
    throw new ToolError("read_failed", "not utf-8");
  }
  const allLines = textContent.split("\n");
  const totalFileLines = allLines.length;
  const startLine = offset ? Math.max(0, offset - 1) : 0;
  const startLineDisplay = startLine + 1;
  if (startLine >= allLines.length) {
    throw new ToolError(
      "offset_out_of_range",
      `Offset ${offset} is beyond end of file (${allLines.length} lines total)`,
    );
  }
  let selectedContent;
  let userLimitedLines;
  if (limit !== undefined) {
    const endLine = Math.min(startLine + limit, allLines.length);
    selectedContent = allLines.slice(startLine, endLine).join("\n");
    userLimitedLines = endLine - startLine;
  } else {
    selectedContent = allLines.slice(startLine).join("\n");
  }
  const truncation = truncateHead(selectedContent);
  if (truncation.firstLineExceedsLimit) {
    const firstLineSize = formatSize(Buffer.byteLength(allLines[startLine], "utf-8"));
    return `[Line ${startLineDisplay} is ${firstLineSize}, exceeds ${formatSize(DEFAULT_MAX_BYTES)} limit. Use bash: sed -n '${startLineDisplay}p' ${rawPath} | head -c ${DEFAULT_MAX_BYTES}]`;
  }
  if (truncation.truncated) {
    const endLineDisplay = startLineDisplay + truncation.outputLines - 1;
    const nextOffset = endLineDisplay + 1;
    let outputText = truncation.content;
    if (truncation.truncatedBy === "lines") {
      outputText += `\n\n[Showing lines ${startLineDisplay}-${endLineDisplay} of ${totalFileLines}. Use offset=${nextOffset} to continue.]`;
    } else {
      outputText += `\n\n[Showing lines ${startLineDisplay}-${endLineDisplay} of ${totalFileLines} (${formatSize(DEFAULT_MAX_BYTES)} limit). Use offset=${nextOffset} to continue.]`;
    }
    return outputText;
  }
  if (userLimitedLines !== undefined && startLine + userLimitedLines < allLines.length) {
    const remaining = allLines.length - (startLine + userLimitedLines);
    const nextOffset = startLine + userLimitedLines + 1;
    return `${truncation.content}\n\n[${remaining} more lines in file. Use offset=${nextOffset} to continue.]`;
  }
  return truncation.content;
}

function main() {
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
  const result = readText(req.root, req.path, takeInt(req.offset), takeInt(req.limit));
  emit({ ok: true, result }, 0);
}

try {
  main();
} catch (err) {
  if (err instanceof ToolError) {
    emit({ ok: false, error: err.code, message: err.message }, 3);
  }
  process.exit(1);
}
