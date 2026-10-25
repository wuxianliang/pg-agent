#!/usr/bin/env node
// Reference Node plugin for the v24 line-JSON plane.
//
// One request frame on stdin, one response frame on stdout.  The same file is
// the artifact hashed by v24/s11/plugin_fixtures.py.  Operations mirror
// echo.py exactly: prepare / invoke / release / inspect.
"use strict";

const fs = require("fs");

function emit(frame, code) {
  process.stdout.write(JSON.stringify(frame) + "\n");
  process.exitCode = code;
}

function ok(result) {
  emit({ ok: true, result: JSON.stringify(result) }, 0);
}

function fail(code, message) {
  emit({ ok: false, error: code, message: message }, 3);
}

function main() {
  const line = fs.readFileSync(0, "utf8").split("\n")[0];
  let frame;
  try {
    frame = JSON.parse(line);
  } catch (err) {
    fail("invalid_frame", "request is not one JSON object");
    return;
  }
  if (frame === null || typeof frame !== "object" || frame.v !== 1
      || !["prepare", "invoke", "release", "inspect"].includes(frame.operation)
      || typeof frame.reservation !== "string" || frame.reservation.length === 0
      || frame.args === null || typeof frame.args !== "object"
      || Array.isArray(frame.args)) {
    fail("invalid_frame", "request frame shape is invalid");
    return;
  }
  const operation = frame.operation;
  const reservation = frame.reservation;
  const args = frame.args;

  if (operation === "prepare") {
    if (!reservation.startsWith("v24:host_prepare:")) {
      fail("reservation_invalid", "prepare reservation mismatch");
      return;
    }
    ok({ prepared: true, language: "node", reservation: reservation });
    return;
  }
  if (operation === "invoke") {
    if (args.__tool_error__ === true) {
      fail("echo_tool_error", "requested known tool error");
      return;
    }
    ok({ echo: args, language: "node" });
    return;
  }
  if (operation === "release") {
    if (!reservation.startsWith("v24:host_release:")) {
      fail("reservation_invalid", "release reservation mismatch");
      return;
    }
    ok({ released: true, language: "node", reservation: reservation });
    return;
  }
  const observed = reservation.startsWith("v24:host_prepare:")
      || reservation.startsWith("v24:host_release:") ? "known" : "absent";
  ok({ v: 1, observed: observed, reservation: reservation });
}

main();
