"""Provider worker and read_file. Not the 62-probe kernel gate.

Run from the repository root: uv run python v20/alpha/test_run.py
No outbound network.
"""
from __future__ import annotations

from pathlib import Path
import io
import json
import os
import sys
import tempfile
import traceback
from contextlib import redirect_stdout
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import v20.alpha.drive as drive
import v20.alpha.setup_db as setup
from v20.alpha.control import Control
from v20.alpha.host import Host
from v20.alpha.provider import ProviderWorker, receipt_from_model_text
from v20.alpha.read_file import read_text
from v20.alpha.tools import ToolFailed, run_tool
from v20.alpha.worker import WorkerRequest, compute_input_digest

ACTOR = "alpha"
DSN = ""
CONTROLS: list[Control] = []
PROBES = (
    "crlf_split_matches_headless_contract",
    "symlink_escape_rejected",
    "echo_still_closed_and_read_needs_root",
    "provider_read_is_visible_on_next_turn",
    "escaped_read_fails_tool_and_run_completes",
    "secret_in_model_text_is_not_a_receipt",
    "fake_drive_reads_file_without_network",
    "real_drive_refuses_without_authorization",
    "real_drive_refuses_without_credential",
)


def uid() -> str:
    return str(uuid4())


def open_control() -> Control:
    ctrl = Control(DSN)
    CONTROLS.append(ctrl)
    return ctrl


def close_controls() -> None:
    while CONTROLS:
        ctrl = CONTROLS.pop()
        try:
            ctrl.close()
        except Exception:
            pass


def _request() -> WorkerRequest:
    material = {
        "base_revision": 1,
        "continuation": False,
        "input_kind": "initial",
        "instruction": "hello",
        "provider_handle": None,
        "response": None,
        "run_id": "run",
        "tool_results": [],
        "turn_id": "turn",
    }
    return WorkerRequest(
        run_id="run",
        turn_id="turn",
        base_revision=1,
        input_kind="initial",
        input_digest=compute_input_digest(material),
        instruction="hello",
        response=None,
        continuation=False,
        provider_handle=None,
        tool_results=[],
    )


def crlf_split_matches_headless_contract():
    root = tempfile.mkdtemp()
    path = Path(root, "crlf.txt")
    path.write_bytes(b"alpha\r\nbeta\r\n")
    assert read_text(root, "crlf.txt") == "alpha\n\nbeta\n\n"


def symlink_escape_rejected():
    base = Path(tempfile.mkdtemp())
    root = base / "ws"
    root.mkdir()
    outside = base / "outside.txt"
    outside.write_text("nope", encoding="utf-8")
    (root / "escape").symlink_to(outside)
    try:
        read_text(str(root), "escape")
    except Exception as exc:
        assert getattr(exc, "code", "") == "path_outside_workspace"
    else:
        raise AssertionError("symlink escaped the workspace")


def echo_still_closed_and_read_needs_root():
    assert run_tool("echo", {"text": "a"}) == {"text": "a"}
    try:
        run_tool("read_file", {"path": "note.txt"})
    except ToolFailed as exc:
        assert "workspace root" in str(exc)
    else:
        raise AssertionError("read_file ran without a root")
    try:
        run_tool("bash", {})
    except ToolFailed as exc:
        assert "unknown" in str(exc)
    else:
        raise AssertionError("unknown tool ran")


def _complete_from(script: dict):
    def complete(messages):
        content = messages[-1]["content"]
        if "Tool results:" in content:
            return json.dumps(script["after"])
        return json.dumps(script["before"])
    return complete


def provider_read_is_visible_on_next_turn():
    root = tempfile.mkdtemp()
    Path(root, "note.txt").write_text("hello-from-file\n", encoding="utf-8")
    worker = ProviderWorker(_complete_from({
        "before": {
            "outcome": "progress",
            "result": {"text": "reading"},
            "tool_calls": [{"name": "read_file", "arguments": {"path": "note.txt"}}],
        },
        "after": {"outcome": "completed", "result": {"text": "saw it"}},
    }))
    ctrl = open_control()
    try:
        done = Host(ctrl, worker, workspace_root=root).drive("start", ACTOR, {
            "request_id": uid(), "input_message": "read note.txt",
        })
        assert done["disposition"] == "stop"
        assert done["status"] == "completed"
        assert worker.calls[1].tool_results[0]["output"]["text"] == "hello-from-file\n"
        assert worker.calls[1].tool_results[0]["tool_name"] == "read_file"
    finally:
        close_controls()


def escaped_read_fails_tool_and_run_completes():
    root = tempfile.mkdtemp()
    worker = ProviderWorker(_complete_from({
        "before": {
            "outcome": "progress",
            "result": {"text": "reading"},
            "tool_calls": [{"name": "read_file", "arguments": {"path": "/etc/hosts"}}],
        },
        "after": {"outcome": "completed", "result": {"text": "settled"}},
    }))
    ctrl = open_control()
    try:
        done = Host(ctrl, worker, workspace_root=root).drive("start", ACTOR, {
            "request_id": uid(), "input_message": "read hosts",
        })
        assert done["disposition"] == "stop"
        output = worker.calls[1].tool_results[0]["output"]
        assert "path_outside_workspace" in output["error"]
    finally:
        close_controls()


def secret_in_model_text_is_not_a_receipt():
    sentinel = "sk-test-sentinel-v20"
    saved = os.environ.get("DEEPSEEK_API_KEY")
    os.environ["DEEPSEEK_API_KEY"] = sentinel
    try:
        try:
            receipt_from_model_text("the key is " + sentinel, _request())
        except RuntimeError as exc:
            assert "secret" in str(exc)
        else:
            raise AssertionError("secret was accepted as a receipt")
    finally:
        if saved is None:
            os.environ.pop("DEEPSEEK_API_KEY", None)
        else:
            os.environ["DEEPSEEK_API_KEY"] = saved


def _without_network(fn):
    import urllib.request
    calls = {"n": 0}
    real = urllib.request.urlopen

    def boom(*_args, **_kwargs):
        calls["n"] += 1
        raise AssertionError("network")

    urllib.request.urlopen = boom
    try:
        return fn(), calls["n"]
    finally:
        urllib.request.urlopen = real


def fake_drive_reads_file_without_network():
    root = tempfile.mkdtemp()
    Path(root, "note.txt").write_text("hello-from-file\n", encoding="utf-8")
    saved = os.environ.get("V20_MODE")
    os.environ["V20_MODE"] = "fake"
    buffer = io.StringIO()

    def run():
        with redirect_stdout(buffer):
            return drive.main(["--root", root, "--message", "read note.txt"])

    try:
        code, opened = _without_network(run)
    finally:
        if saved is None:
            os.environ.pop("V20_MODE", None)
        else:
            os.environ["V20_MODE"] = saved
    assert opened == 0
    assert code == 0, buffer.getvalue()
    assert "disposition=stop" in buffer.getvalue()
    assert "hello-from-file" in buffer.getvalue()


def real_drive_refuses_without_authorization():
    saved_mode = os.environ.get("V20_MODE")
    saved_auth = os.environ.get("V20_REAL_PROVIDER_AUTHORIZATION")
    os.environ["V20_MODE"] = "real"
    os.environ.pop("V20_REAL_PROVIDER_AUTHORIZATION", None)
    buffer = io.StringIO()

    def run():
        with redirect_stdout(buffer):
            return drive.main(["--root", "/tmp", "--message", "hi"])

    try:
        code, opened = _without_network(run)
    finally:
        if saved_mode is None:
            os.environ.pop("V20_MODE", None)
        else:
            os.environ["V20_MODE"] = saved_mode
        if saved_auth is None:
            os.environ.pop("V20_REAL_PROVIDER_AUTHORIZATION", None)
        else:
            os.environ["V20_REAL_PROVIDER_AUTHORIZATION"] = saved_auth
    assert opened == 0
    assert code == 2
    assert buffer.getvalue().strip() == "not_authorized"


def real_drive_refuses_without_credential():
    keys = ("DEEPSEEK_API_KEY", "OPENAI_API_KEY")
    saved = {key: os.environ.get(key) for key in keys}
    saved_mode = os.environ.get("V20_MODE")
    saved_auth = os.environ.get("V20_REAL_PROVIDER_AUTHORIZATION")
    os.environ["V20_MODE"] = "real"
    os.environ["V20_REAL_PROVIDER_AUTHORIZATION"] = "1"
    for key in keys:
        os.environ.pop(key, None)
    buffer = io.StringIO()

    def run():
        with redirect_stdout(buffer):
            return drive.main(["--root", "/tmp", "--message", "hi"])

    try:
        code, opened = _without_network(run)
    finally:
        if saved_mode is None:
            os.environ.pop("V20_MODE", None)
        else:
            os.environ["V20_MODE"] = saved_mode
        if saved_auth is None:
            os.environ.pop("V20_REAL_PROVIDER_AUTHORIZATION", None)
        else:
            os.environ["V20_REAL_PROVIDER_AUTHORIZATION"] = saved_auth
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    assert opened == 0
    assert code == 2
    assert buffer.getvalue().strip() == "credentials_absent"


def main() -> int:
    global DSN
    setup.main()
    DSN = setup.local_dsn()
    failed = 0
    for name in PROBES:
        try:
            globals()[name]()
        except Exception:
            traceback.print_exc()
            print("FAIL", name)
            failed += 1
        else:
            print("ok", name)
        finally:
            close_controls()
    print(f"{len(PROBES) - failed}/{len(PROBES)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
