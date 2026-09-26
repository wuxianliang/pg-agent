# Ported & modified from RepoPrompt CE (Apache-2.0).
# Sources: MCPDomainCanonicalWorkspaceService.swift:171-193
#          DirectHeadlessDomainContext.swift:302-333
# Single-root headless subset. Not the app-window read_file.
# See THIRD_PARTY_NOTICES.md.

from __future__ import annotations

import os
import re


class ReadError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


NEWLINE_RE = re.compile(r"[\n\r\v\f\x85\u2028\u2029]")


def resolve_path(root: str, raw: str) -> str:
    if not isinstance(raw, str):
        raise ReadError("invalid_params", "path must be a string")
    if "\0" in raw:
        raise ReadError("path_outside_workspace", "path contains NUL")
    if raw.strip() == "":
        raise ReadError("invalid_params", "path must not be empty")
    if not isinstance(root, str) or root.strip() == "":
        raise ReadError("invalid_params", "root must be a string")
    root_real = os.path.realpath(root)
    cand = raw if raw.startswith("/") else os.path.join(root_real, raw)
    checked = os.path.realpath(os.path.normpath(cand))
    if checked == root_real or checked.startswith(root_real + os.sep):
        return checked
    raise ReadError("path_outside_workspace", "path outside workspace")


def _optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def read_text(root: str, path: str, start_line: int | None = None, limit: int | None = None) -> str:
    resolved = resolve_path(root, path)
    if os.path.isdir(resolved):
        raise ReadError("read_failed", "is a directory")
    try:
        with open(resolved, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        raise ReadError("read_failed", str(exc)) from exc
    try:
        full = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReadError("read_failed", "not utf-8") from exc
    lines = NEWLINE_RE.split(full)
    start = _optional_int(start_line)
    take_limit = _optional_int(limit)
    if start is None:
        selected = lines
    elif start < 0:
        count = min(len(lines), abs(start))
        selected = lines[-count:] if count else []
    else:
        index = max(0, start - 1)
        if index >= len(lines):
            return ""
        take = len(lines) if take_limit is None else max(0, take_limit)
        selected = lines[index : index + take]
    return "\n".join(selected)
