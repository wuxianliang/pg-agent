"""Host-side success-page field-relation checks for the three built-in tools.

Design §5.6 requires the host to reject a schema-valid but relationally
inconsistent success page as ``invalid_tool_output`` *before* rendering.  The
renderers deliberately have a total projection over the whole schema domain
(§5.3.1), so these checks live here rather than inside a renderer.

The module is a pure function of its inputs: no clock, filesystem, database,
network or subprocess access.  It reads only ``args``/``value`` and the
immutable built-in renderer registry.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .canonical import SAFE_INTEGER_MAX
from .renderers import RENDERERS, RendererRef

MAX_LINE_BYTES = 16384
MAX_READ_LINES = 2000
MAX_LIST_ENTRIES = 500
MAX_SEARCH_HITS = 200
_SKIPPED_KEYS = frozenset({
    "hidden", "symlink", "binary", "too_large", "non_utf8", "long_lines",
})


class ToolPageError(ValueError):
    """A schema-valid success page violates the §5.6 field relations."""

    reason = "invalid_tool_output"


@dataclass(frozen=True)
class PageContract:
    renderer_id: str
    kind: str
    default_limit: int


BUILTIN_PAGE_CONTRACTS: Mapping[str, PageContract] = {
    "v24.fs.read.text": PageContract("v24.fs.read.text", "read", MAX_READ_LINES),
    "v24.fs.list.text": PageContract("v24.fs.list.text", "list", MAX_LIST_ENTRIES),
    "v24.fs.search.text": PageContract("v24.fs.search.text", "search",
                                       MAX_SEARCH_HITS),
}


def _fail() -> None:
    raise ToolPageError("invalid_tool_output")


def _is_safe_int(value: Any) -> bool:
    return type(value) is int and abs(value) <= SAFE_INTEGER_MAX


def _check_safe_domain(value: Any) -> None:
    """Every integer anywhere in ``value`` must be a safe integer.

    Iterative so a deeply nested Python value cannot exhaust the interpreter
    stack before the envelope layer sees it.
    """
    stack = [value]
    while stack:
        item = stack.pop()
        if type(item) is int:
            if abs(item) > SAFE_INTEGER_MAX:
                _fail()
        elif isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    _fail()
                stack.append(child)
        elif isinstance(item, list):
            stack.extend(item)


def _check_args(args: Any, contract: PageContract) -> tuple[int, int]:
    if not isinstance(args, dict):
        _fail()
    offset = args.get("offset", 1)
    limit = args.get("limit", contract.default_limit)
    if not _is_safe_int(offset) or offset < 1:
        _fail()
    if (not _is_safe_int(limit) or limit < 1
            or limit > contract.default_limit):
        _fail()
    return offset, limit


def _check_cursor(value: dict, offset: int, count: int, truncated: bool) -> None:
    expected = offset + count if truncated else None
    actual = value.get("next_offset")
    if actual != expected:
        _fail()
    if expected is not None and (not _is_safe_int(expected)
                                 or expected <= offset):
        _fail()


def _check_read(args: dict, value: dict, offset: int, limit: int) -> None:
    total = value.get("total_lines")
    if not _is_safe_int(total) or total < 0:
        _fail()
    if total == 0:
        # Design §6.2: the empty-file page has exactly one shape and only
        # offset=1 is a legal request.  The W1 reference oracle omits the
        # offset check; that reference gap is recorded, not reproduced.
        if offset != 1:
            _fail()
        if (value.get("text") != "" or value.get("start_line") != 0
                or value.get("end_line") != 0
                or value.get("final_newline") is not False
                or value.get("truncated") is not False
                or value.get("truncated_by") is not None
                or value.get("next_offset") is not None):
            _fail()
        return
    start = value.get("start_line")
    end = value.get("end_line")
    if (not _is_safe_int(start) or not _is_safe_int(end)
            or start != offset or not 1 <= start <= end <= total):
        _fail()
    count = end - start + 1
    if count < 1 or count > limit:
        _fail()
    text = value.get("text")
    if not isinstance(text, str):
        _fail()
    lines = text.split("\n")
    if len(lines) != count:
        _fail()
    for line in lines:
        if len(line.encode("utf-8")) > MAX_LINE_BYTES:
            _fail()
    truncated = end < total
    if value.get("truncated") is not truncated:
        _fail()
    expected_by = (("lines" if count == limit else "bytes")
                   if truncated else None)
    if value.get("truncated_by") != expected_by:
        _fail()
    _check_cursor(value, offset, count, truncated)


def _check_list(value: dict, offset: int, limit: int) -> None:
    entries = value.get("entries")
    total = value.get("total")
    if not isinstance(entries, list) or not _is_safe_int(total) or total < 0:
        _fail()
    if value.get("offset") != offset:
        _fail()
    count = len(entries)
    if count > limit:
        _fail()
    if count == 0:
        if not (offset == 1 and total == 0
                and value.get("truncated") is False
                and value.get("next_offset") is None):
            _fail()
        return
    if offset + count - 1 > total:
        _fail()
    truncated = offset + count - 1 < total
    if value.get("truncated") is not truncated:
        _fail()
    _check_cursor(value, offset, count, truncated)
    for entry in entries:
        if not isinstance(entry, dict):
            _fail()
        kind = entry.get("kind")
        size = entry.get("size")
        if kind == "file":
            if type(size) is not int:
                _fail()
        elif kind in ("directory", "symlink"):
            if size is not None:
                _fail()
        else:
            _fail()


def _check_search(value: dict, offset: int, limit: int) -> None:
    hits = value.get("hits")
    total = value.get("total")
    complete = value.get("complete")
    if (not isinstance(hits, list) or not _is_safe_int(total) or total < 0
            or type(complete) is not bool):
        _fail()
    scanned = value.get("scanned_files")
    if not _is_safe_int(scanned) or scanned < 0:
        _fail()
    skipped = value.get("skipped")
    if not isinstance(skipped, dict) or set(skipped) != _SKIPPED_KEYS:
        _fail()
    for item in skipped.values():
        if not _is_safe_int(item) or item < 0:
            _fail()
    if value.get("offset") != offset:
        _fail()
    count = len(hits)
    if count > limit:
        _fail()
    if count == 0:
        if not (offset == 1 and total == 0 and complete is True
                and value.get("truncated") is False
                and value.get("next_offset") is None):
            _fail()
        return
    if offset + count - 1 > total:
        _fail()
    truncated = offset + count - 1 < total or not complete
    if value.get("truncated") is not truncated:
        _fail()
    _check_cursor(value, offset, count, truncated)


def validate_page(render: RendererRef, args: dict, value: Any) -> None:
    """Reject success pages whose fields contradict design §5.6.

    ``render`` must be the exact approved built-in renderer identity.  Unknown
    ids, unsupported versions and digest mismatches fail closed rather than
    silently skipping the page contract.
    """
    if not isinstance(render, RendererRef):
        _fail()
    contract = BUILTIN_PAGE_CONTRACTS.get(render.id)
    if contract is None:
        _fail()
    try:
        RENDERERS.lookup(render)
    except Exception:
        _fail()
    offset, limit = _check_args(args, contract)
    if not isinstance(value, dict):
        _fail()
    _check_safe_domain(value)
    if contract.kind == "read":
        _check_read(args, value, offset, limit)
    elif contract.kind == "list":
        _check_list(value, offset, limit)
    else:
        _check_search(value, offset, limit)


# The page-contract table and the immutable renderer registry must agree at
# import time; a drift would silently disable one of the three checks.
if set(BUILTIN_PAGE_CONTRACTS) != {entry.ref.id for entry in RENDERERS.entries}:
    raise RuntimeError("page contract drift")
if {key: item.default_limit for key, item in BUILTIN_PAGE_CONTRACTS.items()} != {
        "v24.fs.read.text": MAX_READ_LINES,
        "v24.fs.list.text": MAX_LIST_ENTRIES,
        "v24.fs.search.text": MAX_SEARCH_HITS}:
    raise RuntimeError("page contract limit drift")
