"""Node lifecycle extension check for the v24 M-P plugin plane.

Run from the worktree root::

    uv run python v24/s11/test_node.py --node

Without ``--node`` the script prints ``not_requested`` and exits 0.  With the
flag and no Node toolchain it prints ``[SKIP] not_run/toolchain_absent
planes=node`` and exits 2: a SKIP is explicitly not a pass.  With Node present
it runs the same install -> prepare -> activate -> start -> real Node
subprocess -> final -> off -> dispose -> scope-close lifecycle as G10-B, and
also proves the Node exit-3 known-error mapping.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

S11 = Path(__file__).resolve().parent
V24 = S11.parent
ROOT = V24.parent
for _path in (S11, V24 / "s1", V24 / "s2", V24 / "s4", ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

socket = __import__("socket")

from setup_db import server_helper_scope, setup_db  # noqa: E402

from plugin_fixtures import (  # noqa: E402
    PluginHarness,
    build_registry,
    build_spec,
    execute_single,
    final_reply,
    tool_reply,
)

_SAVED = None


def _deny(*args, **kwargs):
    raise AssertionError("v24/s11 node gate attempted network I/O")


def install_no_network():
    global _SAVED
    urllib_request = __import__("urllib.request", fromlist=["request"])
    _SAVED = (socket.socket.connect, socket.create_connection,
              urllib_request.urlopen)
    socket.socket.connect = _deny
    socket.create_connection = _deny
    urllib_request.urlopen = _deny


def restore_no_network():
    global _SAVED
    if _SAVED is not None:
        socket.socket.connect, socket.create_connection, urlopen = _SAVED
        __import__("urllib.request", fromlist=["request"]).urlopen = urlopen
        _SAVED = None


def _tool_effect(harness, model_id):
    from test_g3a import one
    value = one(harness.owner,
                "SELECT effect_id FROM v24.effects WHERE parent_effect_id=%s "
                "AND kind='tool_call' ORDER BY ordinal LIMIT 1", (model_id,))
    harness.owner.commit()
    return harness.effect_row(value)


def run_node(fixture, workdir):
    realm = "g10-node"
    spec = build_spec("node", realm=realm)
    assert spec.entry.language == "node"
    assert spec.artifact_path.suffix == ".js"

    harness = PluginHarness(fixture, build_registry(spec),
                            workdir / "node", realm=realm)
    try:
        args = {"text": "héllo 世界", "multiline": "line1\nline2", "empty": ""}
        evidence = execute_single(harness, spec, args, "node-final")
        run = harness.run_row(evidence["run_id"])
        assert run["status"] == "completed", run
        assert run["result"]["final_text"] == "node-final", run
        tool = _tool_effect(harness, evidence["model_id"])
        assert tool["status"] == "succeeded", tool
        result = tool["outcome"]["body"]["result"]
        assert result["status"] == "ok", result
        assert result["output"]["echo"] == args, result
        assert result["output"]["language"] == "node", result
        harness.off(evidence["install_id"])
        assert harness.dispose(evidence["install_id"]).get(
            "disposition") == "committed"
        harness.run(None, max_rounds=6)
        install = harness.install_row(evidence["install_id"])
        assert install["state"] == "disposed", install
        assert install["disposed_at"] is not None, install
        scope = harness.close_scope()
        assert scope["closed_at"] is not None, scope
        print("[G10-NODE] full Node lifecycle: install -> prepare -> on -> "
              "start -> real node subprocess (Unicode, escaped newline, empty "
              "string) -> final -> off -> dispose -> host_release -> disposed; "
              "scope closed")

        error_spec = build_spec("node", realm=realm, tool_key="echo.node.error",
                                identity="v24.echo.node.error")
        error_harness = PluginHarness(
            fixture, build_registry(error_spec), workdir / "node-error",
            realm=realm)
        try:
            evidence = execute_single(error_harness, error_spec,
                                      {"__tool_error__": True},
                                      "node-error-final")
            tool = _tool_effect(error_harness, evidence["model_id"])
            assert tool["status"] == "failed", tool
            result = tool["outcome"]["body"]["result"]
            assert result["status"] == "error", result
            assert result["output"]["code"] == "echo_tool_error", result
            error_harness.off(evidence["install_id"])
            assert error_harness.dispose(evidence["install_id"]).get(
                "disposition") == "committed"
            error_harness.run(None, max_rounds=4)
            assert error_harness.install_row(
                evidence["install_id"])["state"] == "disposed"
            scope = error_harness.close_scope()
            assert scope["closed_at"] is not None, scope
            print("[G10-NODE/error] Node exit 3 -> failure receipt "
                  "code=echo_tool_error; install disposed; scope closed")
        finally:
            error_harness.close()
    finally:
        harness.close()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--node", action="store_true",
                        help="run the Node lifecycle (required for evidence)")
    args = parser.parse_args(argv)
    if not args.node:
        print("not_requested")
        return 0
    node = shutil.which("node")
    if node is None:
        print("[SKIP] not_run/toolchain_absent planes=node")
        return 2
    install_no_network()
    try:
        with server_helper_scope(), setup_db() as fixture:
            with tempfile.TemporaryDirectory(prefix="v24-node-") as work:
                workdir = Path(work)
                os.chmod(workdir, 0o700)
                (workdir / "node").mkdir(mode=0o700)
                (workdir / "node-error").mkdir(mode=0o700)
                run_node(fixture, workdir)
    finally:
        restore_no_network()
    print(f"[passed] v24 G10 M-P Node: node={node}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
