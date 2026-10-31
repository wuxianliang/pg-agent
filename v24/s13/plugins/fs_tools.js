#!/usr/bin/env node
// v24 line-JSON v2 filesystem list/search plugin.
//
// One install provides both tools; the frame's ``tool`` field selects the
// path.  A single request frame is read from stdin and one response frame is
// written to stdout.  The plugin has no network access and writes only an
// explicitly supplied ``--spawn-log <absolute path>``.
"use strict";

const fs = require("fs");
const path = require("path");

const MAX_FILE_BYTES = 1024 * 1024;
const MAX_LINE_BYTES = 4096;
const MAX_LIST_ENTRIES = 10000;
const MAX_LIST_LIMIT = 500;
const MAX_SEARCH_HITS = 200;
const MAX_SEARCH_FILES = 10000;
const MAX_VALUE_BYTES = 40960;
const MAX_CONTENT_BYTES = 41984;
const MAX_META_BYTES = 4096;
const FRAME_TARGET = 60000;
const SCAN_BUDGET_MS = 12000;
const MAX_SAFE_BIGINT = BigInt(Number.MAX_SAFE_INTEGER);

class ToolError extends Error {
  constructor(code, message) {
    super(code);
    this.code = code;
    this.message = message;
  }
}

function spawnLog(argv) {
  const index = argv.indexOf("--spawn-log");
  if (index < 0 || index + 1 >= argv.length) return null;
  return argv[index + 1];
}

function appendSpawn(file, operation) {
  if (!file) return;
  fs.appendFileSync(file, `${process.pid} ${operation}\n`, "utf8");
}

function emit(payload, code) {
  process.stdout.write(JSON.stringify(payload) + "\n");
  process.exitCode = code;
}

function ok(result) {
  emit({ ok: true, v: 2, result }, 0);
}

function fail(code, message) {
  emit({ ok: false, v: 2, error: { code, message } }, 3);
}

function mapFsError(error) {
  if (error && (error.code === "ENOENT" || error.code === "ENOTDIR")) {
    return new ToolError("not_found", "path does not exist");
  }
  if (error && (error.code === "EACCES" || error.code === "EPERM")) {
    return new ToolError("permission_denied", "path is not readable");
  }
  return new ToolError("io_error", "path could not be inspected");
}

function rootPath() {
  const root = process.env.V24_WORKSPACE_ROOT;
  if (typeof root !== "string" || !root || !fs.existsSync(root)
      || !fs.statSync(root).isDirectory()) {
    throw new ToolError("root_unavailable",
      "the approved workspace root is not available");
  }
  return fs.realpathSync(root);
}

function pathArgument(value) {
  if (typeof value !== "string" || value.length === 0 || value.includes("\u0000")) {
    throw new ToolError("invalid_path", "path is not a valid string");
  }
  if (Buffer.byteLength(value, "utf8") > 1024) {
    throw new ToolError("invalid_path", "path is longer than 1024 bytes");
  }
  return value;
}

function components(value) {
  const parts = value.split("/");
  const result = [];
  for (const part of parts) {
    if (part === "" || part === ".") continue;
    if (part === "..") {
      throw new ToolError("path_escape", "path must not contain ..");
    }
    result.push(part);
  }
  return result;
}

function resolvePath(value, root, wantDirectory) {
  value = pathArgument(value);
  let comps = components(value);
  let rel;
  if (path.isAbsolute(value)) {
    const normalized = path.normalize(value);
    if (normalized !== root && !normalized.startsWith(root + path.sep)) {
      throw new ToolError("path_escape", "absolute path is outside the workspace");
    }
    rel = path.relative(root, normalized);
    comps = rel === "" ? [] : rel.split(path.sep);
  }
  if (comps.some((part) => part === ".git")) {
    throw new ToolError("path_excluded", "path is excluded");
  }
  let current = root;
  for (const part of comps) {
    current = path.join(current, part);
    let info;
    try {
      info = fs.lstatSync(current);
    } catch (error) {
      throw mapFsError(error);
    }
    if (info.isSymbolicLink()) {
      throw new ToolError("symlink_denied", "path contains a symlink");
    }
  }
  if (wantDirectory) {
    let info;
    try {
      info = fs.lstatSync(current);
    } catch (error) {
      throw mapFsError(error);
    }
    if (!info.isDirectory()) {
      throw new ToolError("not_a_directory", "path is not a directory");
    }
  }
  return { target: current, rel: comps.join("/") || "." };
}

function readChecked(file) {
  let info;
  try {
    info = fs.lstatSync(file);
  } catch (error) {
    throw mapFsError(error);
  }
  if (info.isSymbolicLink()) {
    throw new ToolError("symlink_denied", "path contains a symlink");
  }
  if (!info.isFile()) {
    throw new ToolError("not_a_file", "path is not a regular file");
  }
  if (info.size > MAX_FILE_BYTES) {
    throw new ToolError("file_too_large", "file is larger than 1 MiB");
  }
  let data;
  try {
    data = fs.readFileSync(file);
  } catch (error) {
    throw mapFsError(error);
  }
  if (data.length > MAX_FILE_BYTES) {
    throw new ToolError("file_too_large", "file is larger than 1 MiB");
  }
  if (data.subarray(0, 8192).includes(0)) {
    throw new ToolError("binary_file", "file contains a NUL byte");
  }
  return data;
}

function lineRanges(data) {
  const ranges = [];
  let start = 0;
  for (let index = 0; index < data.length; index += 1) {
    if (data[index] === 0x0a) {
      ranges.push([start, index]);
      start = index + 1;
    }
  }
  if (start < data.length) ranges.push([start, data.length]);
  const finalNewline = data.length > 0 && data[data.length - 1] === 0x0a;
  return { ranges, finalNewline };
}

function escapedLen(text) {
  return Buffer.byteLength(JSON.stringify(text), "utf8") - 2;
}

function jsonLen(value) {
  return Buffer.byteLength(JSON.stringify(value), "utf8");
}

function frameLen(value) {
  return jsonLen({ ok: true, v: 2, result: { value } }) + 1;
}

function selectPrefix(lengths, cap) {
  let best = 0;
  for (let index = 0; index < lengths.length; index += 1) {
    if (lengths[index] <= cap) best = index + 1;
  }
  return best;
}

function defaultCaps() {
  return {
    value: MAX_VALUE_BYTES,
    content: MAX_CONTENT_BYTES,
    meta: MAX_META_BYTES,
    frame: FRAME_TARGET,
  };
}

function addSafe(a, b) {
  if (!Number.isInteger(a) || !Number.isInteger(b)) {
    throw new ToolError("invalid_tool_output",
      "page arithmetic is not an integer");
  }
  const sum = BigInt(a) + BigInt(b);
  if (sum > MAX_SAFE_BIGINT || sum < 0n) {
    throw new ToolError("invalid_tool_output",
      "page arithmetic exceeds safe integers");
  }
  return Number(sum);
}

function pageMeasures(value, text) {
  return {
    value: jsonLen(value),
    content: 27 + escapedLen(text),
    meta: 2,
    frame: frameLen(value),
  };
}

function emptyMeasures(value, text) {
  return pageMeasures(value, text);
}

function fits(measures, caps) {
  return measures.value <= caps.value
    && measures.content <= caps.content
    && measures.meta <= caps.meta
    && measures.frame <= caps.frame;
}

function searchSettings(options) {
  const supplied = options && typeof options === "object" ? options : {};
  return {
    caps: Object.assign({}, defaultCaps(), supplied.caps || {}),
    fileLimit: supplied.fileLimit === undefined
      ? MAX_SEARCH_FILES : supplied.fileLimit,
    budgetMs: supplied.budgetMs === undefined
      ? SCAN_BUDGET_MS : supplied.budgetMs,
    trace: supplied.trace === undefined ? null : supplied.trace,
  };
}

function budgetExpired(state) {
  state.nowCalls += 1;
  if (state.now() >= state.deadline) {
    state.stopReason = "time-cap";
    return true;
  }
  return false;
}

function listSettings(options) {
  const supplied = options && typeof options === "object" ? options : {};
  return {
    caps: Object.assign({}, defaultCaps(), supplied.caps || {}),
    scanLimit: supplied.scanLimit === undefined
      ? MAX_LIST_ENTRIES : supplied.scanLimit,
  };
}

function listText(value) {
  const lines = [];
  for (const entry of value.entries) {
    if (entry.kind === "directory") lines.push(entry.path + "/");
    else if (entry.kind === "symlink") lines.push(entry.path + "@");
    else lines.push(`${entry.path} (${entry.size} B)`);
  }
  let text = lines.length ? lines.join("\n") : "[empty directory]";
  if (value.truncated) {
    const end = addSafe(value.offset, value.entries.length - 1);
    text += `\n\n[Showing ${value.offset}-${end} of ${value.total}. `
      + `Use offset=${value.next_offset} to continue.]`;
  }
  return text;
}

function skippedSum(skipped) {
  return Object.values(skipped).reduce((total, item) => total + item, 0);
}

function searchText(value) {
  const lines = [];
  for (const hit of value.hits) {
    for (const context of hit.before || []) {
      lines.push(`${hit.path}-${context.line}- ${context.text}`);
    }
    lines.push(`${hit.path}:${hit.line}:${hit.column}: ${hit.text}`);
    for (const context of hit.after || []) {
      lines.push(`${hit.path}-${context.line}- ${context.text}`);
    }
  }
  let text = lines.length ? lines.join("\n") : "[no matches]";
  const count = value.hits.length;
  const first = count ? value.offset : 0;
  const last = count ? addSafe(value.offset, count - 1) : 0;
  const total = `${value.total}${value.complete ? "" : "+"}`;
  text += `\n\n[hits ${first}-${last} of ${total}; scanned `
    + `${value.scanned_files}; skipped ${skippedSum(value.skipped)}]`;
  if (value.truncated) {
    text += `\n[Use offset=${value.next_offset} to continue.]`;
  }
  return text;
}

function listScan(dir, prefix, recursive, includeHidden, state) {
  let names;
  try {
    names = fs.readdirSync(dir, { encoding: "buffer" });
  } catch (error) {
    throw mapFsError(error);
  }
  names.sort((left, right) => Buffer.compare(left, right));
  for (const raw of names) {
    state.scanned += 1;
    if (state.scanned > state.scanLimit) {
      throw new ToolError("directory_too_large",
        "directory contains more than 10000 entries");
    }
    const name = raw.toString("utf8");
    if (!Buffer.from(name, "utf8").equals(raw)) {
      state.nonUtf8 += 1;
      continue;
    }
    if (name === ".git") continue;
    if (!includeHidden && name.startsWith(".")) continue;
    const full = path.join(dir, name);
    let info;
    try {
      info = fs.lstatSync(full);
    } catch (error) {
      throw mapFsError(error);
    }
    const entryPath = prefix ? `${prefix}/${name}` : name;
    if (info.isSymbolicLink()) {
      state.entries.push({ path: entryPath, kind: "symlink", size: null });
      continue;
    }
    if (info.isDirectory()) {
      state.entries.push({ path: entryPath, kind: "directory", size: null });
      if (recursive) {
        listScan(full, entryPath, true, includeHidden, state);
      }
      continue;
    }
    if (info.isFile()) {
      state.entries.push({ path: entryPath, kind: "file", size: info.size });
      continue;
    }
    state.special += 1;
  }
}

function listTool(args, root, options) {
  const targetInfo = resolvePath(args.path === undefined ? "." : args.path,
    root, true);
  const recursive = args.recursive === true;
  const includeHidden = args.include_hidden === true;
  const offset = args.offset === undefined ? 1 : args.offset;
  const limit = args.limit === undefined ? MAX_LIST_LIMIT : args.limit;
  if (typeof offset !== "number" || !Number.isSafeInteger(offset) || offset < 1
      || typeof limit !== "number" || !Number.isSafeInteger(limit)
      || limit < 1 || limit > MAX_LIST_LIMIT) {
    throw new ToolError("invalid_path", "offset or limit is invalid");
  }
  const settings = listSettings(options);
  const state = { entries: [], nonUtf8: 0, special: 0, scanned: 0,
    scanLimit: settings.scanLimit };
  listScan(targetInfo.target, targetInfo.rel === "." ? "" : targetInfo.rel,
    recursive, includeHidden, state);
  state.entries.sort((left, right) => Buffer.compare(
    Buffer.from(left.path, "utf8"), Buffer.from(right.path, "utf8")));
  const total = state.entries.length;
  if (total === 0) {
    if (offset !== 1) {
      throw new ToolError("offset_out_of_range", "offset is outside the directory");
    }
    const empty = {
      path: targetInfo.rel,
      offset: 1,
      entries: [],
      total: 0,
      truncated: false,
      next_offset: null,
      skipped_non_utf8: state.nonUtf8,
      skipped_special: state.special,
    };
    if (!fits(emptyMeasures(empty, listText(empty)), settings.caps)) {
      throw new ToolError("output_too_large",
        "no list page fits the budgets");
    }
    return empty;
  }
  const totalBig = BigInt(total);
  const offsetBig = BigInt(offset);
  if (offsetBig > totalBig) {
    throw new ToolError("offset_out_of_range", "offset is outside the directory");
  }
  const maxK = Math.min(limit, total - offset + 1);
  let best = null;
  for (let count = 1; count <= maxK; count += 1) {
    const entries = state.entries.slice(offset - 1, offset - 1 + count);
    const truncated = offsetBig + BigInt(count) - 1n < totalBig;
    const value = {
      path: targetInfo.rel,
      offset,
      entries,
      total,
      truncated,
      next_offset: truncated ? addSafe(offset, count) : null,
      skipped_non_utf8: state.nonUtf8,
      skipped_special: state.special,
    };
    if (fits(pageMeasures(value, listText(value)), settings.caps)) {
      best = value;
    }
  }
  if (best === null) {
    throw new ToolError("entry_too_large", "no list page fits the budgets");
  }
  return best;
}

function globRegex(glob) {
  if (typeof glob !== "string" || glob.length === 0
      || Buffer.byteLength(glob, "utf8") > 256
      || /[{}[\]\\]/.test(glob)) {
    throw new ToolError("invalid_glob", "glob is invalid");
  }
  let out = "^";
  let index = 0;
  while (index < glob.length) {
    const ch = glob[index];
    if (ch === "*" && glob[index + 1] === "*") {
      if (glob[index + 2] === "/") {
        out += "(?:.*/)?";
        index += 3;
      } else {
        out += ".*";
        index += 2;
      }
    } else if (ch === "*") {
      out += "[^/]*";
      index += 1;
    } else if (ch === "?") {
      out += "[^/]";
      index += 1;
    } else {
      out += ch.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      index += 1;
    }
  }
  return {
    regex: new RegExp(out + "$"),
    basenameOnly: !glob.includes("/"),
  };
}

function codePointLength(text) {
  return Array.from(text).length;
}

function truncateCodePoints(text, limit) {
  const points = Array.from(text);
  if (points.length <= limit) return { text, truncated: false };
  return { text: points.slice(0, limit).join(""), truncated: true };
}

function asciiFold(text) {
  return text.replace(/[A-Z]/g, (ch) => ch.toLowerCase());
}

function searchFile(file, relPath, args, state, matcher) {
  let info;
  try {
    info = fs.lstatSync(file);
  } catch (error) {
    throw mapFsError(error);
  }
  if (info.size > MAX_FILE_BYTES) {
    state.skipped.too_large += 1;
    return false;
  }
  let data;
  try {
    data = fs.readFileSync(file);
  } catch (error) {
    throw mapFsError(error);
  }
  if (data.subarray(0, 8192).includes(0)) {
    state.skipped.binary += 1;
    return false;
  }
  let text;
  try {
    text = data.toString("utf8");
    if (!Buffer.from(text, "utf8").equals(data)) throw new Error("bad utf8");
  } catch (error) {
    state.skipped.non_utf8 += 1;
    return false;
  }
  const lines = text === "" ? [] : text.split("\n");
  if (lines.length && lines[lines.length - 1] === "") lines.pop();
  if (lines.some((line) => Buffer.byteLength(line, "utf8") > MAX_LINE_BYTES)) {
    state.skipped.long_lines += 1;
    return false;
  }
  state.scannedFiles += 1;
  if (matcher) {
    const subject = matcher.basenameOnly
      ? path.posix.basename(relPath) : relPath;
    if (!matcher.regex.test(subject)) return false;
  }
  const foldedQuery = args.ignore_case === true ? asciiFold(args.query) : args.query;
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index].endsWith("\r") ? lines[index].slice(0, -1) : lines[index];
    const haystack = args.ignore_case === true ? asciiFold(line) : line;
    const at = haystack.indexOf(foldedQuery);
    if (at < 0) continue;
    const column = codePointLength(line.slice(0, at)) + 1;
    const shown = truncateCodePoints(line, 500);
    const hit = {
      path: relPath,
      line: index + 1,
      column,
      text: shown.text,
      text_truncated: shown.truncated,
    };
    if (args.context > 0) {
      const before = [];
      const after = [];
      for (let cursor = Math.max(0, index - args.context); cursor < index; cursor += 1) {
        before.push({ line: cursor + 1,
          text: truncateCodePoints(
            lines[cursor].endsWith("\r") ? lines[cursor].slice(0, -1) : lines[cursor],
            500).text });
      }
      for (let cursor = index + 1;
        cursor <= Math.min(lines.length - 1, index + args.context); cursor += 1) {
        after.push({ line: cursor + 1,
          text: truncateCodePoints(
            lines[cursor].endsWith("\r") ? lines[cursor].slice(0, -1) : lines[cursor],
            500).text });
      }
      if (before.length) hit.before = before;
      if (after.length) hit.after = after;
    }
    state.hits.push(hit);
    if (BigInt(state.hits.length) >= BigInt(args.offset) + BigInt(args.limit)) {
      state.stopReason = "sentinel";
      return true;
    }
  }
  return false;
}

function searchWalk(dir, prefix, args, state, matcher) {
  let names;
  try {
    names = fs.readdirSync(dir, { encoding: "buffer" });
  } catch (error) {
    throw mapFsError(error);
  }
  names.sort((left, right) => Buffer.compare(left, right));
  for (const raw of names) {
    const name = raw.toString("utf8");
    if (name === ".git") continue;
    if (args.include_hidden !== true && name.startsWith(".")) {
      state.skipped.hidden += 1;
      continue;
    }
    if (!Buffer.from(name, "utf8").equals(raw)) {
      state.skipped.non_utf8 += 1;
      continue;
    }
    const full = path.join(dir, name);
    const relPath = prefix ? `${prefix}/${name}` : name;
    let info;
    try {
      info = fs.lstatSync(full);
    } catch (error) {
      throw mapFsError(error);
    }
    if (info.isSymbolicLink()) {
      state.skipped.symlink += 1;
      continue;
    }
    if (info.isDirectory()) {
      if (budgetExpired(state)) return true;
      if (searchWalk(full, relPath, args, state, matcher)) return true;
      continue;
    }
    if (!info.isFile()) continue;
    state.regular += 1;
    if (state.regular > state.fileLimit) {
      state.stopReason = "file-cap";
      return true;
    }
    if (budgetExpired(state)) return true;
    if (searchFile(full, relPath, args, state, matcher)) return true;
  }
  return false;
}

function searchTool(args, root, options) {
  const targetInfo = resolvePath(args.path === undefined ? "." : args.path,
    root, true);
  if (typeof args.query !== "string" || args.query.length === 0
      || Buffer.byteLength(args.query, "utf8") > 512) {
    throw new ToolError("invalid_path", "query is invalid");
  }
  const context = args.context === undefined ? 0 : args.context;
  if (typeof context !== "number" || !Number.isInteger(context)
      || context < 0 || context > 2) {
    throw new ToolError("invalid_path", "context is invalid");
  }
  const offset = args.offset === undefined ? 1 : args.offset;
  const limit = args.limit === undefined ? MAX_SEARCH_HITS : args.limit;
  if (typeof offset !== "number" || !Number.isSafeInteger(offset) || offset < 1
      || typeof limit !== "number" || !Number.isSafeInteger(limit)
      || limit < 1 || limit > MAX_SEARCH_HITS) {
    throw new ToolError("invalid_path", "offset or limit is invalid");
  }
  const settings = searchSettings(options);
  const now = options && options.now !== undefined ? options.now
    : () => Number(process.hrtime.bigint()) / 1e6;
  const started = now();
  const normalized = {
    query: args.query,
    ignore_case: args.ignore_case === true,
    context,
    offset,
    limit,
    include_hidden: args.include_hidden === true,
    glob: args.glob,
  };
  let matcher = null;
  if (args.glob !== undefined) matcher = globRegex(args.glob);
  const state = {
    hits: [],
    scannedFiles: 0,
    regular: 0,
    skipped: { hidden: 0, symlink: 0, binary: 0, too_large: 0,
      non_utf8: 0, long_lines: 0 },
    stopReason: null,
    fileLimit: settings.fileLimit,
    now,
    deadline: started + settings.budgetMs,
    nowCalls: 1,
  };
  searchWalk(targetInfo.target, targetInfo.rel === "." ? "" : targetInfo.rel,
    normalized, state, matcher);
  if (state.stopReason === null) state.stopReason = "eof";
  if (settings.trace) {
    settings.trace.stopReason = state.stopReason;
    settings.trace.nowCalls = state.nowCalls;
  }
  const complete = state.stopReason === "eof";
  const total = state.hits.length;
  const totalBig = BigInt(total);
  const offsetBig = BigInt(offset);
  if (total === 0) {
    if (offset !== 1) {
      if (complete) {
        throw new ToolError("offset_out_of_range", "offset is outside the hits");
      }
      throw new ToolError("search_scope_too_large",
        "search stopped before the requested offset");
    }
    if (!complete) {
      throw new ToolError("search_scope_too_large",
        "search stopped before the requested offset");
    }
    const empty = {
      path: targetInfo.rel,
      offset: 1,
      hits: [],
      total: 0,
      complete: true,
      scanned_files: state.scannedFiles,
      skipped: state.skipped,
      truncated: false,
      next_offset: null,
    };
    if (!fits(emptyMeasures(empty, searchText(empty)), settings.caps)) {
      throw new ToolError("output_too_large",
        "no search page fits the budgets");
    }
    return empty;
  }
  if (offsetBig > totalBig) {
    if (complete) {
      throw new ToolError("offset_out_of_range", "offset is outside the hits");
    }
    throw new ToolError("search_scope_too_large",
      "search stopped before the requested offset");
  }
  const startBig = offsetBig - 1n;
  const endBig = startBig + BigInt(limit) < totalBig
    ? startBig + BigInt(limit) : totalBig;
  const start = Number(startBig);
  const end = Number(endBig);
  if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end)) {
    throw new ToolError("invalid_tool_output",
      "page arithmetic exceeds safe integers");
  }
  const candidate = state.hits.slice(start, end);
  let best = null;
  for (let count = 1; count <= candidate.length; count += 1) {
    const hits = candidate.slice(0, count);
    const truncated = offsetBig + BigInt(count) - 1n < totalBig || !complete;
    const value = {
      path: targetInfo.rel,
      offset,
      hits,
      total,
      complete,
      scanned_files: state.scannedFiles,
      skipped: state.skipped,
      truncated,
      next_offset: truncated ? addSafe(offset, count) : null,
    };
    if (fits(pageMeasures(value, searchText(value)), settings.caps)) {
      best = value;
    }
  }
  if (best === null) {
    throw new ToolError("hit_too_large", "no search page fits the budgets");
  }
  if (!complete) {
    const selected = best.hits.length;
    if (!(selected === candidate.length && selected === limit)
        && !(selected < candidate.length)) {
      throw new ToolError("search_scope_too_large",
        "search stopped before the page could be filled");
    }
  }
  return best;
}

function invoke(args, tool, root) {
  if (tool === "list") return listTool(args, root);
  if (tool === "search") return searchTool(args, root);
  throw new ToolError("tool_not_approved", "tool is not approved");
}

function main() {
  const argv = process.argv.slice(2);
  const file = spawnLog(argv);
  const raw = fs.readFileSync(0, "utf8");
  let frame = null;
  let operation = null;
  try {
    frame = JSON.parse(raw.split("\n")[0]);
    operation = frame && frame.operation;
  } catch (error) {
    operation = null;
  }
  appendSpawn(file, operation || "unknown");
  try {
    if (frame === null || typeof frame !== "object" || frame.v !== 2
        || !["prepare", "invoke", "release", "inspect"].includes(operation)
        || typeof frame.reservation !== "string" || frame.reservation.length === 0
        || frame.args === null || typeof frame.args !== "object"
        || Array.isArray(frame.args)) {
      throw new ToolError("bad_request", "request frame is invalid");
    }
    const reservation = frame.reservation;
    const args = frame.args;
    const root = rootPath();
    if (operation === "prepare") {
      if (!reservation.startsWith("v24:host_prepare:")) {
        throw new ToolError("reservation_invalid", "prepare reservation mismatch");
      }
      ok({ prepared: true });
      return;
    }
    if (operation === "release") {
      if (!reservation.startsWith("v24:host_release:")) {
        throw new ToolError("reservation_invalid", "release reservation mismatch");
      }
      ok({ released: true });
      return;
    }
    if (operation === "inspect") {
      if (!["host_prepare", "host_release"].includes(args.target)
          || typeof args.target_reservation !== "string") {
        throw new ToolError("inspect_request_invalid",
          "inspect request is invalid");
      }
      const prefix = args.target === "host_prepare"
        ? "v24:host_prepare:" : "v24:host_release:";
      ok({ observed: args.target_reservation.startsWith(prefix)
        ? "known" : "absent" });
      return;
    }
    ok({ value: invoke(args, frame.tool, root) });
  } catch (error) {
    if (error instanceof ToolError) fail(error.code, error.message);
    else fail("io_error", "tool execution failed");
  }
}

if (require.main === module) main();

module.exports = {
  selectPrefix,
  listText,
  searchText,
  searchTool,
  listTool,
  ToolError,
  SCAN_BUDGET_MS,
  MAX_SEARCH_FILES,
  MAX_LIST_ENTRIES,
  defaultCaps,
  emptyMeasures,
  addSafe,
};
