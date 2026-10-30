"""One-shot driver for the alpha kernel. Not a gate.

``V20_MODE`` defaults to ``fake``: no socket, a deterministic worker that
read_file's a relative path named in the message, or echo when none exists.

``V20_MODE=real`` also requires ``V20_REAL_PROVIDER_AUTHORIZATION=1`` and an
API key. Otherwise the process prints ``not_authorized`` or
``credentials_absent`` and exits 2 without calling the provider.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from v20.alpha.control import Control, ControlError
from v20.alpha.host import Host
from v20.alpha.provider import ProviderWorker, credential, live_complete
from v20.alpha.read_file import ReadError, resolve_path
from v20.alpha.setup_db import ensure

ACTOR = "alpha"


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one v20 alpha drive")
    parser.add_argument("--root", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--session-id", default="")
    return parser.parse_args(argv)


def demo_complete(messages: list[dict[str, str]], root: str) -> str:
    content = messages[-1]["content"] if messages else ""
    if "Tool results:" in content:
        excerpt = content[-2000:]
        return json.dumps({"outcome": "completed", "result": {"text": excerpt}})
    for token in content.split():
        path = token.strip("`\"'")
        if not path or path.startswith("/") or "\0" in path:
            continue
        try:
            checked = resolve_path(root, path)
        except ReadError:
            continue
        if not os.path.isfile(checked):
            continue
        return json.dumps({
            "outcome": "progress",
            "result": {"text": "reading"},
            "tool_calls": [{"name": "read_file", "arguments": {"path": path}}],
        })
    return json.dumps({
        "outcome": "progress",
        "result": {"text": "echo"},
        "tool_calls": [{"name": "echo", "arguments": {"text": content[:200]}}],
    })


def main(argv: list[str] | None = None) -> int:
    args = _parse(sys.argv[1:] if argv is None else argv)
    mode = os.environ.get("V20_MODE", "fake")
    if mode == "real":
        if os.environ.get("V20_REAL_PROVIDER_AUTHORIZATION") != "1":
            print("not_authorized")
            return 2
        if credential() == "":
            print("credentials_absent")
            return 2
        complete = live_complete
    elif mode == "fake":
        complete = lambda messages: demo_complete(messages, args.root)
    else:
        print("unknown_mode")
        return 2
    if type(args.message) is not str or not args.message.strip():
        print("empty_message")
        return 2
    if not os.path.isdir(args.root):
        print("root_missing")
        return 2
    control = Control(ensure())
    try:
        payload = {"request_id": str(uuid4()), "input_message": args.message}
        if args.session_id:
            payload["session_id"] = args.session_id
        try:
            done = Host(
                control, ProviderWorker(complete), workspace_root=args.root,
            ).drive("start", ACTOR, payload)
        except ControlError as exc:
            print(exc.code)
            return 1
        except RuntimeError:
            print("provider_failed")
            return 1
        snap = control.execute("poll", ACTOR, {"run_id": done["run_id"]})
        stored = snap["driving"]["request_id"]
        with control.conn.cursor() as cur:
            cur.execute("SELECT result FROM v20_operations WHERE request_id = %s", (stored,))
            row = cur.fetchone()
        control.conn.commit()
        body = row["result"] if row else None
        if isinstance(body, str):
            body = json.loads(body)
        visible = None if not isinstance(body, dict) else body.get("result")
        print("disposition=" + str(done["disposition"]))
        print("status=" + str(done["status"]))
        print("run_id=" + str(done["run_id"]))
        print("result=" + json.dumps(visible, ensure_ascii=False)[:2000])
        return 0
    finally:
        control.close()


if __name__ == "__main__":
    raise SystemExit(main())
