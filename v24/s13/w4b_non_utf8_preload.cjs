// v24 W4b macOS-first non-UTF-8 directory-entry preload.
//
// This file is a test fixture, never a production plugin dependency.  It is
// loaded only into the Node plugin subprocess through
// NODE_OPTIONS=--require <absolute path>.  It appends one raw 0xff name to the
// buffer form of fs.readdirSync for exactly one realpath-normalized directory.
// The production plugins do not read this file or its environment variables.
"use strict";

const fs = require("fs");

const rawRoot = process.env.W4B_NON_UTF8_ROOT;
const ledger = process.env.W4B_SHIM_LEDGER;
if (!rawRoot || !ledger) {
  throw new Error("W4B non-UTF-8 preload requires root and ledger");
}
const root = fs.realpathSync.native(rawRoot);
delete process.env.W4B_NON_UTF8_ROOT;
delete process.env.W4B_SHIM_LEDGER;
delete process.env.NODE_OPTIONS;

const original = fs.readdirSync;

function record(event, detail) {
  fs.appendFileSync(
    ledger,
    JSON.stringify(Object.assign({ event }, detail)) + "\n",
    "utf8",
  );
}

record("loaded", { root, node: process.version });

fs.readdirSync = function patchedReaddirSync(target, options) {
  const result = original.apply(fs, arguments);
  let real;
  try {
    real = fs.realpathSync.native(target);
  } catch (error) {
    return result;
  }
  if (real !== root) return result;
  if (!options || options.encoding !== "buffer" || options.withFileTypes
      || options.recursive) {
    record("mismatch", {
      encoding: options && options.encoding,
      withFileTypes: Boolean(options && options.withFileTypes),
      recursive: Boolean(options && options.recursive),
    });
    throw new Error("W4B preload: unsupported readdirSync form");
  }
  if (result.some((item) => Buffer.isBuffer(item) && item.length === 1
      && item[0] === 0xff)) {
    record("duplicate", {});
    throw new Error("W4B preload: non-UTF-8 entry already exists");
  }
  record("inject", { count: result.length });
  return result.concat([Buffer.from([0xff])]);
};
