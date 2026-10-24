"""Opt-in multilingual smoke: Python -> Node -> final in one real run.

This is not a closeout gate and never runs by default::

    uv run python -m v24.host.plugin_smoke --multilingual-smoke

Without the flag it prints ``not_requested`` and exits 0.  With the flag and no
Node toolchain it prints ``[SKIP] not_run/toolchain_absent planes=python,node``
and exits 2.  A Python-only green G10 run is *not* multilingual completion.

With Node present one database fixture, one scope and one run are used.  The
scripted model calls the Python plugin first, then the Node plugin, then the
same Node plugin with the known-error sentinel (exit 3), then returns final.
The test proves the args crossed the process boundary (Unicode, escaped
newline, empty string), both installs dispose, and the scope closes.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

V24 = Path(__file__).resolve().parent.parent
ROOT = V24.parent
S11 = V24 / "s11"
for _path in (S11, V24 / "s1", V24 / "s2", V24 / "s4", ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

socket = __import__("socket")

from setup_db import server_helper_scope, setup_db  # noqa: E402

from plugin_fixtures import (  # noqa: E402
    PluginHarness,
    build_registry,
    build_spec,
    final_reply,
    tool_reply,
)

_SAVED = None


def _deny(*args, **kwargs):
    raise AssertionError("v24 plugin smoke attempted network I/O")


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


def _tool_rows(harness, run_id):
    from test_g3a import one
    value = one(
        harness.owner,
        """SELECT coalesce(jsonb_agg(jsonb_build_object(
             'effect_id', e.effect_id, 'status', e.status,
             'ordinal', e.ordinal, 'parent', e.parent_effect_id,
             'outcome', e.outcome) ORDER BY e.created_at, e.effect_id), '[]')
           FROM v24.effects e
          WHERE e.run_id=%s AND e.kind='tool_call'""",
        (run_id,))
    harness.owner.commit()
    return value


def multilingual(fixture, workdir):
    realm = "v24-multilingual"
    python_spec = build_spec("python", realm=realm, tool_key="echo.python",
                             identity="v24.echo.python")
    node_spec = build_spec("node", realm=realm, tool_key="echo.node",
                           identity="v24.echo.node")
    registry = build_registry(python_spec, node_spec)
    harness = PluginHarness(fixture, registry, workdir, realm=realm)
    try:
        python_install = harness.admit(python_spec)
        node_install = harness.admit(node_spec)
        harness.prepare([python_install, node_install])
        harness.activate(python_install, python_spec.tool_key)
        harness.activate(node_install, node_spec.tool_key)
        owner_fiber = harness.fiber(python_install)["fiber_id"]
        response = harness.start(
            owner_fiber, [python_spec.tool_key, node_spec.tool_key],
            [{"role": "user",
              "content": "run python, then node, then the known error"}])
        run_id, _model_id = response["emitted"]

        python_args = {"text": "héllo 世界", "n": 1}
        node_args = {"text": "line1\nline2", "empty": ""}
        script = [
            tool_reply("call_1", python_spec.tool_key, python_args),
            tool_reply("call_2", node_spec.tool_key, node_args),
            tool_reply("call_3", node_spec.tool_key,
                       {"__tool_error__": True}),
            final_reply("multilingual-final"),
        ]
        stats = harness.run(script, max_rounds=40)
        assert stats.idle, stats
        run = harness.run_row(run_id)
        assert run["status"] == "completed", run
        assert run["result"]["final_text"] == "multilingual-final", run
        tools = _tool_rows(harness, run_id)
        assert len(tools) == 3, tools
        first, second, third = tools
        assert first["status"] == "succeeded", first
        first_result = first["outcome"]["body"]["result"]
        assert first_result["status"] == "ok", first_result
        assert first_result["output"]["language"] == "python", first_result
        assert first_result["output"]["echo"] == python_args, first_result
        assert second["status"] == "succeeded", second
        second_result = second["outcome"]["body"]["result"]
        assert second_result["status"] == "ok", second_result
        assert second_result["output"]["language"] == "node", second_result
        assert second_result["output"]["echo"] == node_args, second_result
        assert third["status"] == "failed", third
        third_result = third["outcome"]["body"]["result"]
        assert third_result["status"] == "error", third_result
        assert third_result["output"]["code"] == "echo_tool_error", third_result

        print(f"[multilingual] run_id={run_id}")
        print("[multilingual] tool 1 python success "
              f"unicode={first_result['output']['echo']['text']!r}")
        print("[multilingual] tool 2 node success "
              f"escaped_newline={second_result['output']['echo']['text']!r} "
              f"empty={second_result['output']['echo']['empty']!r}")
        print("[multilingual] tool 3 node failure exit=3 "
              f"code={third_result['output']['code']}")

        harness.off(python_install)
        harness.off(node_install)
        assert harness.dispose(python_install).get("disposition") == "committed"
        assert harness.dispose(node_install).get("disposition") == "committed"
        harness.run(None, max_rounds=8)
        python_row = harness.install_row(python_install)
        node_row = harness.install_row(node_install)
        assert python_row["state"] == "disposed", python_row
        assert node_row["state"] == "disposed", node_row
        assert python_row["disposed_at"] is not None, python_row
        assert node_row["disposed_at"] is not None, node_row
        scope = harness.close_scope()
        assert scope["closed_at"] is not None, scope
        print(f"[multilingual] dispose python={python_row['state']} "
              f"node={node_row['state']} scope=closed")
    finally:
        harness.close()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--multilingual-smoke", action="store_true",
                        help="run Python -> Node -> final in one real run")
    args = parser.parse_args(argv)
    if not args.multilingual_smoke:
        print("not_requested")
        return 0
    node = shutil.which("node")
    if node is None:
        print("[SKIP] not_run/toolchain_absent planes=python,node")
        return 2
    install_no_network()
    try:
        with server_helper_scope(), setup_db() as fixture:
            with tempfile.TemporaryDirectory(prefix="v24-multilingual-") as work:
                workdir = Path(work)
                os.chmod(workdir, 0o700)
                multilingual(fixture, workdir)
    finally:
        restore_no_network()
    print(f"[passed] v24 multilingual smoke python=ok node={node} final=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
