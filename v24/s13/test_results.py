"""W2 result contract gate: envelopes, model text, budgets and frames.

Read-only over ``v24/s13/vectors/results_v2.json``.  DB-free, Node-free,
socket-free and subprocess-free.  The three ``m4_pending`` cases are asserted
to remain unexecuted; W2 does not claim replay or lifecycle behavior.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v24.host import tool_results  # noqa: E402
from v24.host.canonical import compact_json  # noqa: E402
from v24.host.renderers import RENDERERS  # noqa: E402
from v24.host.tool_results import (  # noqa: E402
    ToolDispatchResult,
    ToolResultError,
    assert_builtin_meta,
    assert_failure_output,
    assert_success_output,
    assert_unknown_output,
    assert_usage,
    classify_frame,
    failure_output,
    frame_bytes,
    join_content,
    measure,
    success_output,
    unknown_output,
)

VECTORS = Path(__file__).resolve().parent / "vectors" / "results_v2.json"

M2_CASES = {
    "result.success_envelope",
    "result.failure_envelope",
    "result.unknown_envelope",
    "result.usage_wall_ms",
    "result.model_text_join",
    "result.meta_excluded_from_model_text",
    "result.budget_domains",
    "result.frame_60000_60001_65536_65537",
}
M4_CASES = {
    "result.replay_no_rerender",
    "lifecycle.journal_replay_no_rerender",
    "lifecycle.tool_message_model_text_stable",
}
RENDERER_FOR_KIND = {
    "read": "v24.fs.read.text",
    "list": "v24.fs.list.text",
    "search": "v24.fs.search.text",
}


def expect_result_error(fn, reason):
    try:
        fn()
    except ToolResultError as exc:
        assert exc.reason == reason, (reason, exc.reason)
        return
    raise AssertionError(f"expected ToolResultError({reason!r})")


def check_byte_case(case, envelope) -> None:
    encoded = compact_json(envelope)
    assert encoded == bytes.fromhex(case["expected_hex"]), case["id"]
    assert encoded == case["expected_text"].encode("utf-8"), case["id"]
    assert len(encoded) == case["expected_length"], case["id"]
    assert hashlib.sha256(encoded).hexdigest() == case["expected_sha256"], case["id"]


def main() -> int:
    document = json.loads(VECTORS.read_text(encoding="utf-8"))
    cases = document["cases"]
    assert document["format"] == "v24-tool-plugin-abi-w1-vectors-1"
    assert len(cases) == 11
    by_id = {case["id"]: case for case in cases}
    assert set(by_id) == M2_CASES | M4_CASES

    for case_id in M4_CASES:
        assert by_id[case_id]["status"] == "m4_pending", case_id
        assert by_id[case_id]["first_production_stage"] == "M4", case_id

    # 1. Three envelope byte cases.
    success_case = by_id["result.success_envelope"]
    success_input = success_case["input"]
    success = success_output(
        success_input["value"], success_input["content"], success_input.get("meta")
    )
    assert_success_output(success)
    success_omitted = success_output(
        success_input["value"], success_input["content"]
    )
    assert success == success_omitted
    check_byte_case(success_case, success)

    failure_case = by_id["result.failure_envelope"]
    failure_input = failure_case["input"]
    failure = failure_output(
        failure_input["error"]["code"],
        failure_input["error"]["message"],
        failure_input["content"],
        failure_input.get("meta"),
    )
    assert_failure_output(failure)
    check_byte_case(failure_case, failure)

    unknown_case = by_id["result.unknown_envelope"]
    unknown_input = unknown_case["input"]
    unknown = unknown_output(
        unknown_input["error"]["code"], unknown_input["error"]["message"]
    )
    assert_unknown_output(unknown)
    check_byte_case(unknown_case, unknown)

    # 2. Usage is exactly {wall_ms}; extras are invalid_outcome.
    usage_case = by_id["result.usage_wall_ms"]
    assert len(usage_case["input"]) == 3
    for row in usage_case["input"]:
        if row["expected"] == "accepted":
            assert_usage(row["usage"])
        else:
            expect_result_error(lambda row=row: assert_usage(row["usage"]),
                                "invalid_outcome")
    for bad_usage in (
        {"wall_ms": -1},
        {"wall_ms": True},
        {"wall_ms": 1, "tokens": 1},
        {},
        [],
    ):
        expect_result_error(lambda bad_usage=bad_usage: assert_usage(bad_usage),
                            "invalid_outcome")

    # 3. Model text joins with LF, excludes meta, and is exactly 11 bytes.
    join_case = by_id["result.model_text_join"]
    joined = join_content(join_case["input"])
    assert joined == join_case["expected_text"]
    assert joined.encode("utf-8") == bytes.fromhex(join_case["expected_hex"])
    assert len(joined.encode("utf-8")) == 11

    meta_case = by_id["result.meta_excluded_from_model_text"]
    joined_meta = join_content(meta_case["input"]["content"])
    assert joined_meta == meta_case["expected_text"]
    assert joined_meta.encode("utf-8") == bytes.fromhex(meta_case["expected_hex"])
    assert meta_case["input"]["meta"] != {}
    assert "private" not in joined_meta

    # 4. Budget domains.
    budget_case = by_id["result.budget_domains"]
    expected = budget_case["expected"]
    sample = measure(
        {}, {"text": "x"}, [{"type": "text", "text": "x"}], None
    )
    assert tuple(sample) == tuple(expected["measures"])
    assert expected["meta_absent_normalizes_to_empty"] is True

    for row in budget_case["input"]:
        if "meta" in row:
            value = measure({}, {}, [{"type": "text", "text": "x"}], row["meta"])
            assert value["meta"] == row["measure"], row
            classification = (
                "accepted" if value["meta"] <= row["cap"] else "output_too_large"
            )
            assert classification == row["expected"], row
        elif "args" in row:
            value = measure(
                row["args"], {}, [{"type": "text", "text": "x"}]
            )["args"]
            assert value == row["measure"], row
            assert value == len(compact_json(row["args"]))
            assert b"\n" not in compact_json(row["args"])
            assert row["excludes"] == ["frame", "LF"]

    assert len(expected["exact_boundaries"]) == 9
    for row in expected["exact_boundaries"]:
        domain = row["domain"]
        repeat = row["repeat"]
        if domain == "value":
            value = {"text": "x" * repeat}
            content = [{"type": "text", "text": "x"}]
            meta = None
            pinned = repeat + 11
        elif domain == "content":
            value = {"text": "x"}
            content = [{"type": "text", "text": "x" * repeat}]
            meta = None
            pinned = repeat + 27
        else:
            value = {"text": "x"}
            content = [{"type": "text", "text": "x"}]
            meta = {"x": "x" * repeat}
            pinned = repeat + 8
        measured = measure({}, value, content, meta)[domain]
        assert measured == pinned, (row, measured)
        classification = "accepted" if measured <= row["cap"] else "output_too_large"
        assert classification == row["expected"], (row, measured)

    # 5. Built-in plugin meta policy: None and {} accepted, non-empty rejected.
    assert len(expected["builtin_plugin_meta"]) == 3
    for row in expected["builtin_plugin_meta"]:
        if row["expected"] == "accepted":
            assert_builtin_meta(row["meta"])
        else:
            expect_result_error(
                lambda row=row: assert_builtin_meta(row["meta"]),
                "invalid_tool_output",
            )

    # 6. Candidate projection reproduction only: W2 does not implement or
    # assert page selection, scanning or field relationships.
    assert not hasattr(tool_results, "page_decision")
    scenario_count = 0
    for scenario in expected["prefix_scenarios"]:
        scenario_count += 1
        kind = scenario["input"]["kind"]
        renderer_id = RENDERER_FOR_KIND[kind]
        entry = RENDERERS.by_id(renderer_id, 1)
        assert entry is not None
        values = scenario["input"]["values"]
        candidates = scenario["candidates"]
        assert len(values) == len(candidates), scenario["id"]
        for value, candidate in zip(values, candidates):
            content, meta = RENDERERS.render(
                entry.ref, scenario["input"]["args"], value
            )
            assert content == candidate["content"], scenario["id"]
            assert meta == candidate["meta"], scenario["id"]
            assert measure(
                scenario["input"]["args"], value, content, meta
            ) == candidate["measures"], scenario["id"]
    assert scenario_count == 27

    # 7. Four exact frame boundaries and classifications.
    frame_case = by_id["result.frame_60000_60001_65536_65537"]
    assert frame_case["expected"]["overhead"] == 49
    assert len(frame_case["input"]) == 4
    for row in frame_case["input"]:
        value = {"text": row["text_repeat"] * row["repeat_count"]}
        total = frame_bytes(value)
        assert total == row["target"], row
        assert classify_frame(total) == row["classification"], row
    assert classify_frame(60000) == "within_builtin_target"
    assert classify_frame(60001) == "over_builtin_target_transport_valid"
    assert classify_frame(65536) == "over_builtin_target_transport_valid"
    assert classify_frame(65537) == "stdout_limit_unknown"

    # 8. Envelope negative probes.
    extra = {"value": 1, "content": [{"type": "text", "text": ""}], "x": 1}
    expect_result_error(lambda: assert_success_output(extra), "invalid_tool_output")
    expect_result_error(
        lambda: assert_success_output({"value": 1}), "invalid_tool_output"
    )
    expect_result_error(
        lambda: assert_failure_output(
            {"value": 1, "content": [{"type": "text", "text": ""}]}
        ),
        "invalid_tool_output",
    )
    expect_result_error(
        lambda: assert_unknown_output(
            {"error": {"code": "x", "message": "y"}, "content": []}
        ),
        "invalid_tool_output",
    )
    expect_result_error(
        lambda: failure_output(
            "Not-Found", "File not found.", [{"type": "text", "text": ""}]
        ),
        "invalid_tool_output",
    )
    for message in (
        "Traceback (most recent call last):",
        "stack trace follows",
        "see /etc/passwd",
        r"see C:\Users\x",
        r"see \\server\share",
        "DEEPSEEK_API_KEY=secret",
        "OPENAI_API_KEY=secret",
        "NUL\x00",
        "bad \ud800",
    ):
        expect_result_error(
            lambda message=message: failure_output(
                "not_found", message, [{"type": "text", "text": ""}]
            ),
            "invalid_tool_output",
        )
    assert_failure_output(
        failure_output("not_found", "File not found.",
                       [{"type": "text", "text": ""}])
    )
    for content in (
        [],
        [{"type": "text", "text": 1}],
        [{"type": "json", "text": ""}],
        [{"type": "text", "text": "", "x": 1}],
        [{"type": "text", "text": ""}] * 17,
    ):
        expect_result_error(
            lambda content=content: success_output(1, content),
            "invalid_tool_output",
        )
    expect_result_error(
        lambda: success_output(1, [{"type": "text", "text": ""}], []),
        "invalid_tool_output",
    )
    expect_result_error(lambda: join_content([]), "invalid_tool_output")
    expect_result_error(
        lambda: measure(1.5, {}, [{"type": "text", "text": ""}]),
        "invalid_tool_output",
    )

    # 8b. Non-JSON values/content and cyclic containers normalize to the one
    # ``invalid_tool_output`` reason instead of leaking CanonicalError or
    # RecursionError through a public constructor.
    text_block = [{"type": "text", "text": ""}]
    for bad_value in (float("nan"), 1.5, object(), (1,), "\ud800"):
        expect_result_error(
            lambda bad_value=bad_value: success_output(bad_value, text_block),
            "invalid_tool_output",
        )
    expect_result_error(
        lambda: success_output(1, [{"type": "text", "text": "\ud800"}]),
        "invalid_tool_output",
    )
    cyclic = []
    cyclic.append(cyclic)
    expect_result_error(lambda: frame_bytes(cyclic), "invalid_tool_output")
    expect_result_error(
        lambda: measure({}, cyclic, text_block), "invalid_tool_output"
    )
    # Finite depth is legal: the encoder uses an explicit stack, so a value
    # far beyond Python's recursion limit still measures instead of failing.
    deep = 0
    for _ in range(1200):
        deep = [deep]
    assert success_output(deep, text_block)["value"] is deep
    assert measure({}, deep, text_block)["value"] == len(compact_json(deep))

    # 9. ToolDispatchResult closes the outer {status,output,usage} shape and
    # dispatches to the validator for its class.
    success_result = {
        "status": "ok", "output": success, "usage": {"wall_ms": 1},
    }
    failure_result = {
        "status": "error", "output": failure, "usage": {"wall_ms": 0},
    }
    unknown_result = {
        "status": "error", "output": unknown, "usage": {"wall_ms": 0},
    }
    assert ToolDispatchResult("unknown", unknown_result, "").model_text == ""
    assert ToolDispatchResult("success", success_result, joined).model_text == joined
    assert ToolDispatchResult("failure", failure_result, joined).model_text == joined
    for class_, bad_result in (
        ("unknown", unknown),
        ("unknown", {"status": "error", "output": unknown}),
        ("unknown", {
            "status": "error", "output": unknown,
            "usage": {"wall_ms": 0}, "x": 1,
        }),
        ("unknown", {"status": "unknown", "output": unknown,
                    "usage": {"wall_ms": 0}}),
        ("unknown", {"status": "ok", "output": unknown,
                    "usage": {"wall_ms": 0}}),
        ("unknown", {"status": "error", "output": unknown,
                    "usage": {"wall_ms": -1}}),
    ):
        expect_result_error(
            lambda class_=class_, bad_result=bad_result: ToolDispatchResult(
                class_, bad_result, ""
            ),
            "invalid_outcome",
        )
    expect_result_error(
        lambda: ToolDispatchResult("unknown", unknown_result, "text"),
        "invalid_outcome",
    )
    expect_result_error(
        lambda: ToolDispatchResult("maybe", unknown_result, ""),
        "invalid_outcome",
    )
    expect_result_error(
        lambda: ToolDispatchResult(
            "success",
            {"status": "ok", "output": failure, "usage": {"wall_ms": 0}},
            joined,
        ),
        "invalid_tool_output",
    )
    expect_result_error(
        lambda: ToolDispatchResult(
            "failure",
            {"status": "error", "output": success, "usage": {"wall_ms": 0}},
            joined,
        ),
        "invalid_tool_output",
    )

    print(
        "[passed] W2 result contract; cases=8; envelope_bytes=3; "
        "frame_boundaries=4; replay_claimed=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
