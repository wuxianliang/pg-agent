"""Read-only verification of reviewed v1 golden vectors. Never re-blesses."""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from golden_cases import capture_all, server_helper_scope, setup_db, verify_descriptor_pg_vectors

GOLDEN = Path(__file__).resolve().parent / "golden"
FILES = ("descriptor_v1.json", "frames_v1.json",
         "provider_requests_v1.json", "tool_messages_v1.json")
REQUIRED_IDS = {
    "descriptor_v1.json": {
        "descriptor.echo.python", "descriptor.echo.node", "descriptor.pg.v1_echo",
        "descriptor.pg.v2_contract", "descriptor.pg.empty_object",
    },
    "frames_v1.json": {
        *(f"frame.{op}" for op in ("prepare", "invoke", "release", "inspect")),
        *(f"stdout.{language}.{case}" for language in ("python", "node")
          for case in ("prepare", "invoke_success", "invoke_error", "release", "inspect")),
        *(f"parser.{case}" for case in ("eof", "bad_json", "non_object_result",
          "missing_lf", "crlf", "extra_frame", "non_utf8", "u2028", "u2029")),
    },
    "provider_requests_v1.json": {
        "provider.success.request1", "provider.success.request2",
        "provider.known_error.request1", "provider.known_error.request2",
    },
    "tool_messages_v1.json": {
        "tool_message.success.content", "tool_message.known_error.content",
        "structure.journal_event_set", "structure.tool_message_keys",
        "structure.dispatch_payload_keys", "structure.tool_lease_ms",
        "structure.transport_limits", "structure.descriptor_v2_rejected",
    },
}


def _fail(case_id, expected, actual):
    a, b = bytes.fromhex(expected), bytes.fromhex(actual)
    offset = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    print(f"[FAIL] {case_id}: offset={offset} expected_len={len(a)} actual_len={len(b)} "
          f"expected_sha256={hashlib.sha256(a).hexdigest()} "
          f"actual_sha256={hashlib.sha256(b).hexdigest()}")
    raise SystemExit(1)


def _load():
    docs = {}
    for name in FILES:
        path = GOLDEN / name
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["format"] == "v24-tool-plugin-abi-v1-golden-1", name
        assert doc["domain_file"] == name, name
        docs[name] = doc["cases"]
    return docs


def _self_consistency(docs):
    ids = set()
    for name, cases in docs.items():
        case_ids = [case["id"] for case in cases]
        assert len(case_ids) == len(set(case_ids)), f"duplicate IDs in {name}"
        assert set(case_ids) == REQUIRED_IDS[name], (name, sorted(set(case_ids) - REQUIRED_IDS[name]),
                                                     sorted(REQUIRED_IDS[name] - set(case_ids)))
        for case in cases:
            case_id = case["id"]
            assert case_id not in ids, f"duplicate case id: {case_id}"
            ids.add(case_id)
            if case.get("kind") == "structural":
                continue
            raw = bytes.fromhex(case["expected_hex"])
            assert len(raw) == case["expected_length"], case_id
            assert hashlib.sha256(raw).hexdigest() == case["expected_sha256"], case_id
            text = case.get("expected_text")
            if text is None:
                assert case_id.startswith("parser."), case_id
            else:
                assert text.encode("utf-8") == raw, case_id
    expected = {
        "descriptor": 5,
        "frames": 4 + 10 + 9,
        "provider": 4,
        "tool_messages": 8,
    }
    actual = {"descriptor": len(docs[FILES[0]]), "frames": len(docs[FILES[1]]),
              "provider": len(docs[FILES[2]]), "tool_messages": len(docs[FILES[3]])}
    assert actual == expected, (actual, expected)


def _compare(docs, live, *, include_node):
    expected = {case["id"]: case for cases in docs.values()
                for case in cases if case.get("kind") != "structural"
                and (include_node or not case["id"].startswith("stdout.node."))}
    actual = {case["id"]: case for cases in live.values() for case in cases
              if case.get("kind") != "structural"}
    assert set(expected) == set(actual), (sorted(set(expected) - set(actual)),
                                          sorted(set(actual) - set(expected)))
    for case_id, want in expected.items():
        got = actual[case_id]
        if want["expected_hex"] != got["expected_hex"]:
            _fail(case_id, want["expected_hex"], got["expected_hex"])
        if want.get("semantic") != got.get("semantic"):
            print(f"[FAIL] {case_id}: semantic expectation differs")
            raise SystemExit(1)


def _check_structures(docs, db, live):
    from v24.host import line_json
    from v24.host.journal import EVENT_TYPES
    import inspect
    from v24.host.worker import HostWorker
    from v24.host.deepseek import AdapterFailure, DeepSeekAdapter
    wanted = {case["id"]: case["expected"] for case in docs[FILES[3]]
              if case.get("kind") == "structural"}
    message_cases = [case for case in live[FILES[3]]
                     if case["id"].startswith("tool_message.")]
    first = message_cases[0]["semantic"]
    if any(case["semantic"]["message_shape"] != first["message_shape"]
           or case["semantic"]["dispatch_payload_keys"] != first["dispatch_payload_keys"]
           or case["semantic"]["journal_event_types"] != first["journal_event_types"]
           or case["semantic"]["tool_lease_ms"] != first["tool_lease_ms"]
           for case in message_cases[1:]):
        raise AssertionError("live success/error journal structures differ")
    actual = {
        "structure.journal_event_set": {
            "observed": sorted(first["journal_event_types"]),
            "declared": sorted(EVENT_TYPES),
        },
        "structure.tool_message_keys": sorted(first["message_shape"]),
        "structure.dispatch_payload_keys": first["dispatch_payload_keys"],
        "structure.tool_lease_ms": {
            "observed_tool_effect_ms": first["tool_lease_ms"],
            "worker_default_ms": inspect.signature(HostWorker).parameters["default_lease_ms"].default,
        },
        "structure.transport_limits": {"stdout": line_json.STDOUT_LIMIT,
                                       "stderr": line_json.STDERR_LIMIT},
        "structure.descriptor_v2_rejected": "descriptor_invalid",
    }
    try:
        DeepSeekAdapter._tools([{"key": "read", "descriptor": {"v": 2, "tool": {}}}])
    except AdapterFailure as exc:
        actual["structure.descriptor_v2_rejected"] = exc.reason
    else:
        actual["structure.descriptor_v2_rejected"] = "accepted"
    for key, value in wanted.items():
        if actual.get(key) != value:
            raise AssertionError(f"structural vector mismatch: {key}; actual={actual.get(key)!r}")
    verify_descriptor_pg_vectors(db)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--node", action="store_true",
                        help="also execute and compare the actual Node echo subprocess")
    args = parser.parse_args(argv)
    docs = _load()
    _self_consistency(docs)
    with server_helper_scope():
        db = setup_db()
        try:
            with tempfile.TemporaryDirectory(prefix="b0-golden-check-") as temp:
                live = capture_all(db, Path(temp), include_node=args.node)
            _check_structures(docs, db, live)
            _compare(docs, live, include_node=args.node)
        finally:
            db.close()
    languages = "Python+Node" if args.node else "Python"
    count = sum(1 for cases in docs.values() for case in cases
                if case.get("kind") != "structural"
                and (args.node or not case["id"].startswith("stdout.node.")))
    per_file = {name: len([case for case in cases
                           if case.get("kind") != "structural"
                           and (args.node or not case["id"].startswith("stdout.node."))])
                for name, cases in docs.items()}
    print(f"[passed] B0 v1 golden read-only check; byte_cases={count}; "
          f"structural_cases=6; total_vectors=40; files={per_file}; "
          f"descriptor=PostgreSQL+Python; plugins={languages}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
