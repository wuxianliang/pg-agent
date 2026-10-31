"""W4 page-contract gate: host §5.6 relations against the W1 reference oracle.

DB-free, Node-free, socket-free and subprocess-free except for the one import
direction probe, which starts a Python child.  The differential is only
defined for values that pass the approved tool's ``output_check``; schema
rejections are asserted on the host side only.  The two documented
``w1_reference.page_error`` gaps are excluded from the equivalence and
asserted one-sided, per W4 plan C5/D2.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _path in (HERE, ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from v24.host.registry import ApprovedTool  # noqa: E402
from v24.host.tool_pages import (  # noqa: E402
    BUILTIN_PAGE_CONTRACTS,
    MAX_LIST_ENTRIES,
    MAX_READ_LINES,
    MAX_SEARCH_HITS,
    ToolPageError,
    validate_page,
)
from v24.host.renderers import RENDERERS, RendererRef  # noqa: E402
from v24.host.tool_schema import InstanceError  # noqa: E402

VECTORS = HERE / "vectors"
KINDS = ("read", "list", "search")


def load_tools():
    document = json.loads((VECTORS / "descriptor_v2.json").read_text(
        encoding="utf-8"))
    tools = {}
    for case in document["cases"]:
        case_id = case["id"]
        if case_id.startswith("descriptor.v2."):
            kind = case_id.rsplit(".", 1)[-1]
            if kind in KINDS:
                tools[kind] = ApprovedTool.from_descriptor(case["input"], key=kind)
    assert set(tools) == set(KINDS), sorted(tools)
    return tools


TOOLS = load_tools()


def expect_page_error(fn, label):
    try:
        fn()
    except ToolPageError as exc:
        assert exc.reason == "invalid_tool_output", (label, exc.reason)
        return
    raise AssertionError(f"expected ToolPageError: {label}")


def host_rejects(render, args, value):
    try:
        validate_page(render, args, value)
    except ToolPageError:
        return True
    return False


def output_ok(tool, value):
    try:
        tool.output_check(value)
    except InstanceError:
        return False
    return True


def reference_rejects(kind, args, value):
    import w1_reference
    return w1_reference.page_error(kind, args, copy.deepcopy(value))


def _walk(value, path=()):
    if type(value) is int:
        yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _walk(child, path + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, path + (index,))


def _replace(value, path, replacement):
    cloned = copy.deepcopy(value)
    cursor = cloned
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = replacement
    return cloned


def mutations(kind, args, value):
    """Every plan-required single-field mutation of a schema-valid value."""
    seen = set()

    def emit(label, candidate):
        marker = json.dumps([kind, args, candidate], sort_keys=True,
                            ensure_ascii=False)
        if marker in seen:
            return None
        seen.add(marker)
        return label, candidate

    for path, item in _walk(value):
        for delta in (1, -1):
            candidate = _replace(value, path, item + delta)
            out = emit(f"int:{path}:{delta:+d}", candidate)
            if out is not None:
                yield out
    for path, item in _walk(value):
        if type(item) is bool:
            out = emit(f"bool:{path}", _replace(value, path, not item))
            if out is not None:
                yield out
    out = emit("cursor:null", _replace(
        value, ("next_offset",), None)) if "next_offset" in value else None
    if out is not None:
        yield out
    offset = args.get("offset", 1)
    if "next_offset" in value:
        out = emit("cursor:offset", _replace(
            value, ("next_offset",), offset))
        if out is not None:
            yield out
        out = emit("cursor:zero", _replace(
            value, ("next_offset",), 0))
        if out is not None:
            yield out
    collection = "entries" if kind == "list" else (
        "hits" if kind == "search" else None)
    if collection is not None:
        for index, item in enumerate(value.get(collection, [])):
            if not isinstance(item, dict) or "size" not in item:
                continue
            replacement = None if type(item["size"]) is int else 0
            out = emit(f"size:{index}", _replace(
                value, (collection, index, "size"), replacement))
            if out is not None:
                yield out


def collect_bases():
    bases = []
    renderers = json.loads((VECTORS / "renderers.json").read_text(
        encoding="utf-8"))
    for case in renderers["cases"]:
        case_id = case["id"]
        if not case_id.startswith("render.") or ".golden" not in case_id:
            continue
        kind = case_id.split(".")[1]
        for inner in case["input"]["cases"]:
            bases.append((kind, inner["args"], inner["value"],
                          f"renderers:{case_id}:{inner['id']}"))

    contracts = json.loads((VECTORS / "tool_contracts.json").read_text(
        encoding="utf-8"))
    for case in contracts["cases"]:
        case_id = case["id"]
        if case_id not in ("tool.read.contract", "tool.list.contract",
                           "tool.search.contract"):
            continue
        kind = case_id.split(".")[1]
        for inner in case["input"]["inputs"]:
            expected = inner.get("expected", {})
            if "value" in expected:
                bases.append((kind, inner["args"], expected["value"],
                              f"tool_contracts:{case_id}:{inner['id']}"))

    results = json.loads((VECTORS / "results_v2.json").read_text(
        encoding="utf-8"))
    for case in results["cases"]:
        if case["id"] != "result.budget_domains":
            continue
        for scenario in case["expected"]["prefix_scenarios"]:
            kind = scenario["input"]["kind"]
            for index, value in enumerate(scenario["input"]["values"]):
                bases.append((kind, scenario["input"]["args"], value,
                              f"results_v2:{scenario['id']}:{index}"))
    return bases


def main() -> int:
    # 1. Contract set is exactly the renderer set; default limits are the
    # descriptor limits.  A drift raises at import, but assert the public
    # table here too.
    assert set(BUILTIN_PAGE_CONTRACTS) == {
        "v24.fs.read.text", "v24.fs.list.text", "v24.fs.search.text"}
    assert {entry.ref.id for entry in RENDERERS.entries} == set(
        BUILTIN_PAGE_CONTRACTS)
    assert {key: contract.kind for key, contract in
            BUILTIN_PAGE_CONTRACTS.items()} == {
        "v24.fs.read.text": "read", "v24.fs.list.text": "list",
        "v24.fs.search.text": "search"}
    assert {key: contract.default_limit for key, contract in
            BUILTIN_PAGE_CONTRACTS.items()} == {
        "v24.fs.read.text": MAX_READ_LINES,
        "v24.fs.list.text": MAX_LIST_ENTRIES,
        "v24.fs.search.text": MAX_SEARCH_HITS}
    assert ToolPageError.reason == "invalid_tool_output"

    # 2. Unknown renderer ids, versions and digests fail closed.
    read = TOOLS["read"]
    assert read.render is not None
    for label, ref in (
        ("unknown-id", RendererRef("v24.fs.unknown.text", 1,
                                   read.render.digest)),
        ("unknown-version", RendererRef(read.render.id, 2,
                                        read.render.digest)),
        ("bad-digest", RendererRef(read.render.id, 1, "0" * 64)),
        ("bad-type", "v24.fs.read.text"),
    ):
        expect_page_error(
            lambda ref=ref: validate_page(ref, {"path": "x"}, {}), label)
    for kind in KINDS:
        tool = TOOLS[kind]
        assert tool.render is not None and tool.output_check is not None

    # 3. Import direction: tool_pages must not pull the s13 reference oracle
    # into a process.  Run in a child so the parent can import the oracle for
    # the differential below.
    probe = (
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "import v24.host.tool_pages\n"
        "assert 'w1_reference' not in sys.modules, 'oracle imported'\n"
        "assert 'v24.s13.w1_reference' not in sys.modules, 'oracle imported'\n"
    )
    subprocess.run([sys.executable, "-c", probe], cwd=ROOT, check=True)

    cases = 0
    differential = 0
    schema_rejected = 0
    gaps = {"empty_read_offset": 0, "negative_skipped": 0}

    def inspect(kind, args, value, label):
        nonlocal cases, differential, schema_rejected
        cases += 1
        tool = TOOLS[kind]
        if kind == "read" and isinstance(value, dict) and value.get(
                "total_lines") == 0 and args.get("offset", 1) > 1:
            # Oracle gap: page_error accepts the empty shape without checking
            # offset; design §6.2 requires offset_out_of_range.
            assert not reference_rejects(kind, args, value), label
            assert host_rejects(tool.render, args, value), label
            gaps["empty_read_offset"] += 1
            return
        skipped = value.get("skipped") if isinstance(value, dict) else None
        if (kind == "search" and isinstance(skipped, dict)
                and any(type(item) is int and item < 0
                        for item in skipped.values())
                and not reference_rejects(kind, args, value)):
            # Oracle gap: page_error only checks safe integers, not the
            # schema's non-negative minimum.  The schema rejects this before
            # validate_page runs in production, but the host must also fail
            # closed if it is ever called directly.
            assert not output_ok(tool, value), label
            assert host_rejects(tool.render, args, value), label
            gaps["negative_skipped"] += 1
            return
        if not output_ok(tool, value):
            schema_rejected += 1
            return
        oracle = reference_rejects(kind, args, value)
        host = host_rejects(tool.render, args, value)
        assert host == oracle, (
            label, "host", host, "oracle", oracle,
            json.dumps(value, ensure_ascii=False)[:500])
        differential += 1

    bases = collect_bases()
    for kind, args, value, label in bases:
        inspect(kind, args, value, label)
        for mutation_label, candidate in mutations(kind, args, value):
            inspect(kind, args, candidate, f"{label}:{mutation_label}")

    # 4. The empty-read gap is also reached from the frozen read contract
    # value with offset=2, not only from the explicit branch above.
    empty_value = next(value for kind, args, value, label in bases
                       if kind == "read" and value.get("total_lines") == 0
                       and args.get("offset", 1) == 1)
    inspect("read", {"path": "empty", "offset": 2}, empty_value,
            "explicit:empty-read-offset-2")

    # 5. Negative skipped is schema-rejected; assert the oracle/host split
    # explicitly with a value taken from the frozen contracts.
    search_value = next(value for kind, args, value, label in bases
                        if kind == "search" and value.get("hits"))
    negative = copy.deepcopy(search_value)
    negative["skipped"]["hidden"] = -1
    inspect("search", {"query": "needle"}, negative,
            "explicit:negative-skipped")

    # 6. A schema-invalid but relationally plausible page must be rejected by
    # the schema, and the host page check must still fail closed when called.
    bad_type = copy.deepcopy(search_value)
    bad_type["hits"][0]["line"] = "1"
    assert not output_ok(TOOLS["search"], bad_type)
    assert host_rejects(TOOLS["search"].render, {"query": "needle"}, bad_type)

    assert gaps["empty_read_offset"] >= 1, gaps
    assert gaps["negative_skipped"] >= 1, gaps
    assert differential > 0 and cases > differential, (cases, differential)
    assert schema_rejected > 0, schema_rejected
    print(f"[passed] W4 page contract; contracts=3; cases={cases}; "
          f"oracle_differential={differential}; unknown_ref_rejected=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
