"""Pure prompt renderer for v15 (§6.5). No Jinja. Does not compute digests."""
from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR

RESPONSE_FORMAT = (
    "Your entire reply is a PostgreSQL statement list. Do not wrap it in "
    "markdown fences or prose. Separate statements with semicolons. The "
    "canonical control statements are:\n"
    "SELECT jaz.bind_invoke('<ident>', <jsonb-expr>);\n"
    "SELECT jaz.\"return\"(<jsonb-expr>);\n"
    "SELECT jaz.\"raise\"(<text-expr>);\n"
    "SELECT jaz.print(<text-expr>);\n"
    "SELECT jaz.assign('<ident>', <jsonb-expr>);\n"
    "jaz.var(name) and jaz.tool(name, args) may appear inside expressions. "
    "return and raise must be double-quoted. An unquoted return or raise is "
    "rejected."
)
_BIND_INVOKE_LINE = "SELECT jaz.bind_invoke('<ident>', <jsonb-expr>);\n"
RESPONSE_FORMAT_NO_DELEGATION = RESPONSE_FORMAT.replace(_BIND_INVOKE_LINE, "", 1)
REPL_TEXT = (
    "Statements run one at a time. Your scratch schema is on the search_path. "
    "You may create and drop tables, indexes, and views only in that schema. "
    "CALL, EXECUTE, COPY, transaction control, SET, RESET, DO, ALTER, and "
    "TRUNCATE are rejected. Empty a table with DELETE. Other DDL is rejected. "
    "Repeat work inside one statement with WITH RECURSIVE, not with DO. "
    "Change a table by dropping it and creating it again."
)
HISTORY_TEXT = (
    "Finished iterations of this invoke are rows of jaz.history (columns "
    "iteration, llm_response, repl_output, repl_exception). Read them with "
    "ORDER BY iteration. There is no __history__ object. "
    "jaz.prior_history(invoke_id) returns the same columns for this invoke or "
    "an ancestor invoke and fails for any other id. jaz.request_messages "
    "(columns seq, role, kind, content) is the request stored for the latest "
    "settled attempt of the current iteration, including hook messages. Read "
    "it with ORDER BY seq."
)
TAIL_DELEGATION = (
    "To delegate to a child invoke, end your message with exactly these two "
    "statements and no further statements after them:\n"
    "SELECT jaz.bind_invoke('<ident>', <jsonb-expr>);\n"
    "SELECT jaz.\"return\"(jaz.var('<ident>'));\n"
    "The jsonb expression is a JSON object of explicit inputs for the child. "
    "The next statement of this same reply reads the child result with "
    "jaz.var. This invoke does not call the model again before that statement."
)
MARKER = "\n[v15 truncated]\n"
_SCOPED_KINDS = frozenset({"scope", "var", "tool"})


def seed_system_id() -> str:
    return "seed:system"


def seed_inputs_id() -> str:
    return "seed:inputs"


def iter_message_id(n: int, part: str) -> str:
    if part not in {"assistant", "observation"} or isinstance(n, bool) or n < 0:
        raise ValueError(part)
    return f"iter:{n}:{part}"


def render_system(*, recursion_available: bool, bindings: list[dict]) -> str:
    response = RESPONSE_FORMAT if recursion_available else RESPONSE_FORMAT_NO_DELEGATION
    blocks = [response, REPL_TEXT, HISTORY_TEXT]
    if recursion_available:
        blocks.append(TAIL_DELEGATION)
    blocks.append(_scoped_block(bindings))
    return "\n\n".join(blocks)


def render_inputs(bindings: list[dict]) -> str | None:
    rows = [
        row
        for row in bindings
        if row.get("kind") == "input" and row.get("show_in_prompt") is True
    ]
    if not rows:
        return None
    rows.sort(key=lambda row: row["name"].encode("utf-8"))
    lines = ["inputs:"]
    for row in rows:
        lines.append(f"{row['name']}: {row['value_text']}")
    return "\n".join(lines)


def render_base(
    *,
    recursion_available: bool,
    bindings: list[dict],
    history: list[dict],
    protocol: dict,
) -> list[dict]:
    messages = [
        {
            "message_id": seed_system_id(),
            "role": "system",
            "kind": "system",
            "content": render_system(
                recursion_available=recursion_available,
                bindings=bindings,
            ),
        }
    ]
    user = render_inputs(bindings)
    if user is not None:
        messages.append(
            {
                "message_id": seed_inputs_id(),
                "role": "user",
                "kind": "input",
                "content": user,
            }
        )
    messages.extend(dict(row) for row in history)
    return truncate_base(messages, protocol)


def truncate_text(text: str, limit: int, prefix_ratio: float) -> str:
    if len(text) <= limit:
        return text
    keepable = limit - len(MARKER)
    if keepable < 1:
        return text[:limit] if limit > 0 else ""
    prefix_len = _floor_mul(keepable, prefix_ratio)
    suffix_len = keepable - prefix_len
    suffix = text[-suffix_len:] if suffix_len else ""
    return text[:prefix_len] + MARKER + suffix


def truncate_base(messages: list[dict], protocol: dict) -> list[dict]:
    max_in = int(protocol["max_invoke_input_length"])
    repl_limit = int(protocol["max_repl_output_length"])
    ratio = protocol["truncation_prefix_ratio"]
    out = [dict(row) for row in messages]
    originals = [row["content"] for row in messages]
    observations = [i for i, row in enumerate(out) if row.get("kind") == "observation"]
    for index in observations:
        out[index]["content"] = truncate_text(originals[index], repl_limit, ratio)
    for index in observations:
        total = _total(out)
        if total <= max_in:
            break
        current = out[index]["content"]
        if len(current) <= len(MARKER):
            continue
        excess = total - max_in
        target = len(current) - excess
        if target <= len(MARKER):
            out[index]["content"] = MARKER
            continue
        out[index]["content"] = truncate_text(originals[index], target, ratio)
    total = _total(out)
    if total > max_in:
        for index, row in enumerate(out):
            if row.get("kind") != "input":
                continue
            excess = total - max_in
            target = len(row["content"]) - excess
            out[index]["content"] = truncate_text(originals[index], max(0, target), ratio)
            break
    return out


def _scoped_block(bindings: list[dict]) -> str:
    rows = [
        row
        for row in bindings
        if row.get("kind") in _SCOPED_KINDS and row.get("show_in_prompt") is True
    ]
    rows.sort(key=lambda row: row["name"].encode("utf-8"))
    lines = ["scoped names:"]
    for row in rows:
        line = f"{row['name']} kind={row['kind']}"
        if row["kind"] == "tool":
            description = row.get("description") or ""
            line = f"{line} {description}"
        lines.append(line)
    return "\n".join(lines)


def _total(messages: list[dict]) -> int:
    return sum(len(row["content"]) for row in messages)


def _floor_mul(keepable: int, ratio) -> int:
    if isinstance(ratio, Decimal):
        value = Decimal(keepable) * ratio
    elif isinstance(ratio, float):
        value = Decimal(keepable) * Decimal(str(ratio))
    else:
        value = Decimal(keepable) * Decimal(ratio)
    return int(value.to_integral_value(rounding=ROUND_FLOOR))
