"""Lexical splitter and statement classifier for v15 (§6.1–§6.3).

classify_statement returns Classification with five fields in §6.2 order:
(kind, bind_name, arg_sql, reject_code, tool_name). An empty reject_code is
None. An empty bind_name, arg_sql, or tool_name is None, which is the SQL
NULL the settlement row stores. Object equality is the five-field contract.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from typing import NamedTuple

_NUL_TEXT = "\\u0000"
_WRITE_WORDS = frozenset(
    {"insert", "update", "delete", "merge", "truncate", "copy", "into"}
)
_SEQ_FUNCS = frozenset({"nextval", "setval", "currval"})
_RESERVED_NAMES = frozenset(
    {
        "__history__",
        "history",
        "request_messages",
        "return",
        "raise",
        "print",
        "assign",
        "var",
        "tool",
        "bind_invoke",
        "bind_tool",
        "prior_history",
        "exec_context",
        "invoke_id",
        "iteration",
    }
)
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,53}$")
_DDL_PREFIXES = (
    ("create", "function"),
    ("create", "procedure"),
    ("create", "routine"),
    ("create", "extension"),
    ("create", "role"),
    ("create", "database"),
    ("create", "event", "trigger"),
    ("grant",),
    ("revoke",),
    ("comment",),
    ("security", "label"),
    ("vacuum",),
    ("reindex",),
    ("cluster",),
    ("alter", "table"),
)
_UTILITY = frozenset(
    {
        "call",
        "execute",
        "copy",
        "do",
        "begin",
        "commit",
        "rollback",
        "savepoint",
        "start",
        "end",
        "abort",
        "release",
        "set",
        "reset",
        "lock",
        "prepare",
        "deallocate",
        "listen",
        "notify",
        "unlisten",
        "load",
        "discard",
        "checkpoint",
        "explain",
        "truncate",
    }
)
_SCRATCH_PREFIXES = (
    ("create", "unique", "index"),
    ("create", "index"),
    ("create", "table"),
    ("create", "view"),
    ("drop", "table"),
    ("drop", "index"),
    ("drop", "view"),
)
_PRAGMA_ATTEMPT = re.compile(r"^[ \t\f\v]*--[ \t\f\v]*timeout:")
_PRAGMA_FULL = re.compile(
    r"^[ \t\f\v]*--[ \t\f\v]*timeout:[ \t\f\v]*"
    r"([0-9]+(?:\.[0-9]+)?|\.[0-9]+)"
    r"[ \t\f\v]*$"
)


class _Unclosed(Exception):
    pass


@dataclass(frozen=True)
class Tok:
    kind: str
    text: str
    start: int
    end: int
    content: str | None = None
    style: str | None = None


@dataclass(frozen=True)
class SplitFailure:
    sql: str
    reject_code: str
    kind: str = "plain"
    bind_name: str | None = None
    arg_sql: str | None = None


class Classification(NamedTuple):
    kind: str
    bind_name: str | None
    arg_sql: str | None
    reject_code: str | None
    tool_name: str | None = None

    def as_core(self) -> tuple[str, str | None, str | None, str | None]:
        """Explicit 4-tuple of the pre-tool fields. Equality stays five-field."""
        return (self.kind, self.bind_name, self.arg_sql, self.reject_code)


def split_sql(source: str) -> list[str] | SplitFailure:
    if "\x00" in source:
        return SplitFailure(
            sql=source.replace("\x00", _NUL_TEXT),
            reject_code="V15_VALUE_INVALID",
        )
    try:
        tokens = scan(source)
    except _Unclosed:
        return SplitFailure(sql=source, reject_code="V15_DIALECT")
    parts: list[str] = []
    start = 0
    for tok in tokens:
        if tok.kind == "punct" and tok.text == ";":
            _keep(source, start, tok.start, parts)
            start = tok.end
    _keep(source, start, len(source), parts)
    return parts


def classify_statement(sql: str) -> Classification:
    if "\x00" in sql:
        return Classification("plain", None, None, "V15_VALUE_INVALID")
    try:
        tokens = scan(sql)
    except _Unclosed:
        return Classification("plain", None, None, "V15_DIALECT")
    result = _classify_tokens(sql, tokens)
    _ms, invalid = _parse_pragma(sql)
    if invalid and result.reject_code is None:
        return result._replace(reject_code="V15_VALUE_INVALID")
    return result


def timeout_pragma_ms(sql: str) -> int | None:
    ms, invalid = _parse_pragma(sql)
    if invalid:
        return None
    return ms


def sql_without_timeout_pragma(sql: str) -> str:
    line, sep, rest = sql.partition("\n")
    check = line[:-1] if line.endswith("\r") else line
    if _PRAGMA_ATTEMPT.match(check) is None:
        return sql
    if sep:
        return rest
    return ""


def scan(source: str) -> list[Tok]:
    tokens: list[Tok] = []
    n = len(source)
    i = 0
    while i < n:
        ch = source[i]
        if ch.isspace():
            i += 1
            continue
        if source.startswith("--", i):
            i += 2
            while i < n and source[i] != "\n":
                i += 1
            continue
        if source.startswith("/*", i):
            i = _scan_block(source, i)
            continue
        if source.startswith(("E'", "e'"), i):
            end = _scan_extended(source, i + 2)
            tokens.append(Tok("string", source[i:end], i, end, style="ext"))
            i = end
            continue
        if source.startswith(("U&'", "u&'"), i):
            end = _scan_standard(source, i + 3)
            tokens.append(Tok("string", source[i:end], i, end, style="unicode"))
            i = end
            continue
        if ch == "'":
            end = _scan_standard(source, i + 1)
            raw = source[i:end]
            tokens.append(
                Tok("string", raw, i, end, content=_decode_std(raw), style="std")
            )
            i = end
            continue
        if ch == '"':
            end = _scan_quoted_ident(source, i + 1)
            raw = source[i:end]
            tokens.append(Tok("qident", raw, i, end, content=_decode_qident(raw)))
            i = end
            continue
        if ch == "$":
            opened = _open_dollar(source, i)
            if opened is not None:
                tag, body = opened
                closer = f"${tag}$"
                found = source.find(closer, body)
                if found < 0:
                    raise _Unclosed()
                end = found + len(closer)
                tokens.append(Tok("dollar", source[i:end], i, end))
                i = end
                continue
            tokens.append(Tok("punct", "$", i, i + 1))
            i += 1
            continue
        if _ident_start(ch):
            j = i + 1
            while j < n and _ident_cont(source[j]):
                j += 1
            tokens.append(Tok("ident", source[i:j], i, j))
            i = j
            continue
        if "0" <= ch <= "9":
            j = _scan_number(source, i)
            tokens.append(Tok("number", source[i:j], i, j))
            i = j
            continue
        tokens.append(Tok("punct", ch, i, i + 1))
        i += 1
    return tokens


def _keep(source: str, start: int, end: int, parts: list[str]) -> None:
    piece = source[start:end].strip()
    if not piece:
        return
    try:
        if scan(piece):
            parts.append(piece)
    except _Unclosed:
        parts.append(piece)


def _scan_block(source: str, i: int) -> int:
    n = len(source)
    depth = 1
    i += 2
    while i < n:
        if source.startswith("/*", i):
            depth += 1
            i += 2
            continue
        if source.startswith("*/", i):
            depth -= 1
            i += 2
            if depth == 0:
                return i
            continue
        i += 1
    raise _Unclosed()


def _scan_standard(source: str, i: int) -> int:
    n = len(source)
    while i < n:
        if source[i] == "'":
            if i + 1 < n and source[i + 1] == "'":
                i += 2
                continue
            return i + 1
        i += 1
    raise _Unclosed()


def _scan_extended(source: str, i: int) -> int:
    n = len(source)
    while i < n:
        if source[i] == "\\":
            if i + 1 >= n:
                raise _Unclosed()
            i += 2
            continue
        if source[i] == "'":
            if i + 1 < n and source[i + 1] == "'":
                i += 2
                continue
            return i + 1
        i += 1
    raise _Unclosed()


def _scan_quoted_ident(source: str, i: int) -> int:
    n = len(source)
    while i < n:
        if source[i] == '"':
            if i + 1 < n and source[i + 1] == '"':
                i += 2
                continue
            return i + 1
        i += 1
    raise _Unclosed()


def _scan_number(source: str, i: int) -> int:
    n = len(source)
    j = i + 1
    while j < n and "0" <= source[j] <= "9":
        j += 1
    if j < n and source[j] == "." and j + 1 < n and "0" <= source[j + 1] <= "9":
        j += 2
        while j < n and "0" <= source[j] <= "9":
            j += 1
    return j


def _open_dollar(source: str, i: int) -> tuple[str, int] | None:
    n = len(source)
    if i + 1 < n and source[i + 1] == "$":
        return "", i + 2
    j = i + 1
    if j >= n or not _tag_start(source[j]):
        return None
    j += 1
    while j < n and _tag_cont(source[j]):
        j += 1
    if j < n and source[j] == "$":
        return source[i + 1 : j], j + 1
    return None


def _tag_start(ch: str) -> bool:
    if ch == "_" or ("A" <= ch <= "Z") or ("a" <= ch <= "z"):
        return True
    return ord(ch) >= 0x80


def _tag_cont(ch: str) -> bool:
    return _tag_start(ch) or ("0" <= ch <= "9")


def _ident_start(ch: str) -> bool:
    if ch == "_" or ("A" <= ch <= "Z") or ("a" <= ch <= "z"):
        return True
    return unicodedata.category(ch).startswith("L")


def _ident_cont(ch: str) -> bool:
    if _ident_start(ch) or ch == "$" or ("0" <= ch <= "9"):
        return True
    return unicodedata.category(ch) == "Nd"


def _decode_std(raw: str) -> str:
    return raw[1:-1].replace("''", "'")


def _decode_qident(raw: str) -> str:
    return raw[1:-1].replace('""', '"')


def _classify_tokens(sql: str, sig: list[Tok]) -> Classification:
    canonical = _match_canonical(sql, sig)
    if canonical is not None:
        return canonical
    if _has_control_name(sig):
        return Classification("plain", None, None, "V15_INVOKE_FORM")
    words = _leading_words(sig)
    if any(_starts(words, prefix) for prefix in _DDL_PREFIXES):
        return Classification("plain", None, None, "V15_DDL")
    if words and words[0] in _UTILITY:
        return Classification("plain", None, None, "V15_DIALECT")
    if any(_starts(words, prefix) for prefix in _SCRATCH_PREFIXES):
        return Classification("plain", None, None, None)
    if words and words[0] in {"create", "alter", "drop"}:
        return Classification("plain", None, None, "V15_DDL")
    return Classification("plain", None, None, None)


def _match_canonical(sql: str, sig: list[Tok]) -> Classification | None:
    if len(sig) < 5:
        return None
    if not _is_word(sig[0], "select") or not _is_jaz(sig[1]):
        return None
    if not (sig[2].kind == "punct" and sig[2].text == "."):
        return None
    func = _canonical_func(sig[3])
    if func is None:
        return None
    if not (sig[4].kind == "punct" and sig[4].text == "("):
        return None
    close = _call_end(sig, 4)
    if close is None or close != len(sig) - 1:
        return None
    interior = sig[5:close]
    open_end = sig[4].end
    close_start = sig[close].start
    if func == "bind_tool":
        return _match_tool(sql, interior, close_start)
    if func in {"bind_invoke", "assign"}:
        return _match_two_arg(sql, func, interior, open_end, close_start)
    return _match_one_arg(sql, func, interior, open_end, close_start)


def _match_one_arg(
    sql: str,
    func: str,
    interior: list[Tok],
    open_end: int,
    close_start: int,
) -> Classification:
    if not interior or _top_commas(interior):
        return Classification("plain", None, None, "V15_INVOKE_FORM")
    if not any(t.kind != "punct" or t.text not in {"(", ")"} for t in interior):
        return Classification("plain", None, None, "V15_INVOKE_FORM")
    return Classification(func, None, sql[open_end:close_start], None)


def _match_two_arg(
    sql: str,
    func: str,
    interior: list[Tok],
    open_end: int,
    close_start: int,
) -> Classification:
    commas = _top_commas(interior)
    if len(commas) != 1:
        return Classification("plain", None, None, "V15_INVOKE_FORM")
    comma = commas[0]
    before = [t for t in interior if t.end <= comma.start]
    after = [t for t in interior if t.start >= comma.end]
    if len(before) != 1 or before[0].kind != "string" or before[0].style != "std":
        return Classification("plain", None, None, "V15_INVOKE_FORM")
    if not after:
        return Classification("plain", None, None, "V15_INVOKE_FORM")
    name = before[0].content or ""
    if not _valid_bind_name(name):
        return Classification("plain", None, None, "V15_INVOKE_FORM")
    arg_sql = sql[comma.end : close_start]
    if func == "bind_invoke" and _arg_has_write(arg_sql):
        return Classification("bind_invoke", name, arg_sql, "V15_INVOKE_FORM")
    return Classification(func, name, arg_sql, None)


def _match_tool(
    sql: str,
    interior: list[Tok],
    close_start: int,
) -> Classification:
    commas = _top_commas(interior)
    if len(commas) != 2:
        return Classification("plain", None, None, "V15_INVOKE_FORM")
    first_comma, second_comma = commas
    before = [t for t in interior if t.end <= first_comma.start]
    middle = [
        t for t in interior if t.start >= first_comma.end and t.end <= second_comma.start
    ]
    after = [t for t in interior if t.start >= second_comma.end]
    if (
        len(before) != 1
        or before[0].kind != "string"
        or before[0].style != "std"
        or len(middle) != 1
        or middle[0].kind != "string"
        or middle[0].style != "std"
        or not after
    ):
        return Classification("plain", None, None, "V15_INVOKE_FORM")
    name = before[0].content or ""
    tool_name = middle[0].content or ""
    if not _valid_bind_name(name) or not _valid_tool_name(tool_name):
        return Classification("plain", None, None, "V15_INVOKE_FORM")
    arg_sql = sql[second_comma.end : close_start]
    reject = "V15_INVOKE_FORM" if _arg_has_write(arg_sql) else None
    return Classification("bind_tool", name, arg_sql, reject, tool_name)


def _top_commas(interior: list[Tok]) -> list[Tok]:
    depth = 0
    found: list[Tok] = []
    for tok in interior:
        if tok.kind == "punct" and tok.text == "(":
            depth += 1
        elif tok.kind == "punct" and tok.text == ")":
            depth -= 1
        elif tok.kind == "punct" and tok.text == "," and depth == 0:
            found.append(tok)
    return found


def _call_end(sig: list[Tok], open_index: int) -> int | None:
    depth = 0
    for i in range(open_index, len(sig)):
        tok = sig[i]
        if tok.kind == "punct" and tok.text == "(":
            depth += 1
        elif tok.kind == "punct" and tok.text == ")":
            depth -= 1
            if depth == 0:
                return i
    return None


def _arg_has_write(arg_sql: str) -> bool:
    try:
        sig = scan(arg_sql)
    except _Unclosed:
        return True
    i = 0
    while i < len(sig):
        tok = sig[i]
        if tok.kind == "ident" and tok.text.casefold() in _WRITE_WORDS:
            return True
        if tok.kind == "qident" and (tok.content or "").casefold() in _WRITE_WORDS:
            if tok.content in _WRITE_WORDS:
                return True
        if _seq_call(sig, i):
            return True
        i += 1
    return False


def _seq_call(sig: list[Tok], i: int) -> bool:
    name = _func_name(sig[i])
    if name is None:
        return False
    j = i + 1
    if name == "pg_catalog":
        if j >= len(sig) or not (sig[j].kind == "punct" and sig[j].text == "."):
            return False
        j += 1
        if j >= len(sig):
            return False
        name = _func_name(sig[j])
        if name is None:
            return False
        j += 1
    if name not in _SEQ_FUNCS:
        return False
    return j < len(sig) and sig[j].kind == "punct" and sig[j].text == "("


def _func_name(tok: Tok) -> str | None:
    if tok.kind == "ident":
        return tok.text.casefold()
    if tok.kind == "qident" and tok.content in _SEQ_FUNCS | {"pg_catalog"}:
        return tok.content
    return None


def _has_control_name(sig: list[Tok]) -> bool:
    for i in range(len(sig) - 2):
        if not _is_jaz(sig[i]):
            continue
        if not (sig[i + 1].kind == "punct" and sig[i + 1].text == "."):
            continue
        if _is_control_func(sig[i + 2]):
            return True
    return False


def _is_control_func(tok: Tok) -> bool:
    if tok.kind == "ident" and tok.text.casefold() in {
        "bind_invoke",
        "bind_tool",
        "return",
        "raise",
    }:
        return True
    if tok.kind == "qident" and tok.content in {
        "return",
        "raise",
        "bind_invoke",
        "bind_tool",
    }:
        return True
    return False


def _canonical_func(tok: Tok) -> str | None:
    if tok.kind == "ident":
        name = tok.text.casefold()
        if name in {"bind_invoke", "bind_tool", "print", "assign"}:
            return name
        return None
    if tok.kind == "qident" and tok.content in {
        "return",
        "raise",
        "bind_invoke",
        "bind_tool",
        "print",
        "assign",
    }:
        return tok.content
    return None


def _is_jaz(tok: Tok) -> bool:
    if tok.kind == "ident" and tok.text.casefold() == "jaz":
        return True
    return tok.kind == "qident" and tok.content == "jaz"


def _is_word(tok: Tok, word: str) -> bool:
    return tok.kind == "ident" and tok.text.casefold() == word


def _leading_words(sig: list[Tok]) -> list[str]:
    words: list[str] = []
    for tok in sig:
        if tok.kind != "ident":
            break
        words.append(tok.text.casefold())
    return words


def _starts(words: list[str], prefix: tuple[str, ...]) -> bool:
    return len(words) >= len(prefix) and tuple(words[: len(prefix)]) == prefix


def _valid_bind_name(name: str) -> bool:
    return (
        1 <= len(name) <= 63
        and _IDENT_RE.fullmatch(name) is not None
        and name not in _RESERVED_NAMES
    )


def _valid_tool_name(name: str) -> bool:
    return _TOOL_NAME_RE.fullmatch(name) is not None


def _first_line(sql: str) -> str:
    line = sql.split("\n", 1)[0]
    if line.endswith("\r"):
        line = line[:-1]
    return line


def _parse_pragma(sql: str) -> tuple[int | None, bool]:
    line = _first_line(sql)
    if _PRAGMA_ATTEMPT.match(line) is None:
        return None, False
    matched = _PRAGMA_FULL.fullmatch(line)
    if matched is None:
        return None, True
    number = Decimal(matched.group(1))
    if not number.is_finite() or number <= 0:
        return None, True
    ms = (number * Decimal(1000)).to_integral_value(rounding=ROUND_FLOOR)
    if ms < 1:
        return None, True
    return int(ms), False
