"""W4c Node extension gate: one install, list + search, real subprocess.

Node missing is an explicit ``[SKIP]`` with exit 2; it is never recorded as a
pass.  With Node present, one v2 install provides both tools and a real model
batch drives both through the host dispatcher.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _path in (HERE, HERE / "plugins", ROOT, ROOT / "v24" / "s11",
              ROOT / "v24" / "s1", ROOT / "v24" / "s2", ROOT / "v24" / "s4"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from setup_db import server_helper_scope, setup_db  # noqa: E402

from plugin_fixtures import _chat_body, final_reply  # noqa: E402
from fixtures import node_spec, open_harness, spawn_count, workspace  # noqa: E402
from v24.host.deepseek import _v2_provider_name  # noqa: E402
from v24.host.tool_pages import validate_page  # noqa: E402


def node_path():
    return shutil.which("node")


def batch_reply(calls):
    encoded = []
    for call_id, key, args in calls:
        encoded.append({
            "id": call_id,
            "type": "function",
            "function": {
                "name": _v2_provider_name(key),
                "arguments": json.dumps(args, ensure_ascii=False, sort_keys=True,
                                        separators=(",", ":")),
            },
        })
    return {
        "status": 200,
        "advance_ms": 7,
        "raw": _chat_body(content=None, finish="tool_calls",
                          tool_calls=encoded, usage=(10, 5),
                          reasoning="plan", response_id="resp-node"),
    }


def tool_effects(harness, model_id):
    found = []
    for record in harness.journal.records:
        if record.get("event_type") != "dispatch_finished":
            continue
        payload = record.get("payload") or {}
        if (payload.get("kind") == "tool_call"
                and str(payload.get("parent_effect_id")) == str(model_id)):
            found.append(harness.effect_row(record["effect_id"]))
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node", action="store_true")
    parser.parse_args(argv)
    node = node_path()
    if node is None:
        print("[SKIP] W4 node contract; node_missing")
        return 2
    with tempfile.TemporaryDirectory(prefix="w4c-node-") as temp:
        base = Path(temp)
        listing = workspace(base / "list", "list")
        spec = node_spec(base / "node", listing.root,
                         realm=f"w4c-node-{uuid.uuid4().hex[:8]}")
        with server_helper_scope(), setup_db() as fixture:
            harness = open_harness(fixture, [spec], base / "harness",
                                   realm=spec.realm)
            try:
                install_id = harness.admit(spec)
                harness.prepare([install_id])
                harness.activate(install_id, "list")
                fiber = harness.fiber(install_id)
                response = harness.start(
                    fiber["fiber_id"], ["list", "search"],
                    [{"role": "user", "content": "w4c node"}])
                run_id, model_id = response["emitted"]
                harness.run([
                    batch_reply([
                        ("call_list", "list", {"path": "."}),
                        ("call_search", "search", {"query": "x"}),
                    ]),
                    final_reply("node-final"),
                ], max_rounds=30)
                run = harness.run_row(run_id)
                assert run["status"] == "completed", run
                effects = tool_effects(harness, model_id)
                assert len(effects) == 2, effects
                for effect in effects:
                    assert effect["outcome"]["class"] == "success", effect
                    value = effect["outcome"]["body"]["result"]["output"]["value"]
                    key = effect["request"]["key"]
                    tool = spec.entry.tool_for(key)
                    assert tool is not None
                    tool.output_check(value)
                    validate_page(tool.render, effect["request"]["args"], value)
                pins = harness.db.host_run_pins(run_id, None, 64)
                items = pins.get("items", [])
                assert len(items) == 2, items
                assert {item["key"] for item in items} == {"list", "search"}
                assert items[0]["provider_install_id"] == \
                    items[1]["provider_install_id"]
                assert spawn_count(harness, install_id) == 3, \
                    spawn_count(harness, install_id)
            finally:
                harness.close()
    print(f"[passed] W4 node contract; node={node}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
