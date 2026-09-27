"""Line-JSON read port for the released DuckDB plane.

Run with v13/read_tools/.duck-venv/bin/python. Imports duckdb 1.5.5 only.
Does not import repository modules and does not use the repository venv.
Disk reads stay in this process. DuckDB sees source text, not paths.
See THIRD_PARTY_NOTICES.md.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


EXPECTED_DUCKDB_VERSION = "1.5.5"
EXTENSION_ROOT = Path.home() / ".duckdb" / "extensions"
PINS_BY_PLATFORM = {
    "osx_arm64": {
        "sitting_duck": {
            "version": "b8c06a8",
            "sha256": "e031481f864f342b97deb1e985b6ff5f4b27a97de28d7ec37cf1ad64b6483176",
        },
        "duck_block_utils": {
            "version": "39941a7",
            "sha256": "4a4f6ff8800c23e959198fa62c134da311acd82d81258f85c64aa16ef21cf529",
        },
    },
}


class ToolError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def emit(obj: dict, code: int) -> None:
    frame = json.dumps(obj, ensure_ascii=True).encode("ascii") + b"\n"
    sys.stdout.buffer.write(frame)
    sys.stdout.buffer.flush()
    raise SystemExit(code)


def fail_internal(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_path(root: str, raw: str) -> str:
    if not isinstance(raw, str):
        raise ToolError("invalid_params", "path must be a string")
    if "\0" in raw:
        raise ToolError("path_outside_workspace", "path contains NUL")
    if raw.strip() == "":
        raise ToolError("invalid_params", "path must not be empty")
    if not isinstance(root, str) or root.strip() == "":
        raise ToolError("invalid_params", "root must be a string")
    try:
        root_real = os.path.realpath(root)
        cand = raw if raw.startswith("/") else os.path.join(root_real, raw)
        checked = os.path.realpath(os.path.normpath(cand))
    except OSError as exc:
        raise ToolError("read_failed", str(exc)) from exc
    if checked == root_real or checked.startswith(root_real + os.sep):
        return checked
    raise ToolError("path_outside_workspace", "path outside workspace")


def read_utf8(resolved: str) -> str:
    if os.path.isdir(resolved):
        raise ToolError("read_failed", "is a directory")
    try:
        with open(resolved, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        raise ToolError("read_failed", str(exc)) from exc
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ToolError("read_failed", "not utf-8") from exc
    if "\0" in text:
        raise ToolError("read_failed", "contains NUL")
    return text


def extension_file(platform: str, name: str) -> Path:
    return EXTENSION_ROOT / f"v{EXPECTED_DUCKDB_VERSION}" / platform / f"{name}.duckdb_extension"


def sql_load(path: Path) -> str:
    text = str(path)
    if "'" in text:
        fail_internal(f"extension path contains quote: {text}")
    return f"LOAD '{text}'"


def prepare():
    import duckdb

    loaded_from = os.path.realpath(duckdb.__file__)
    prefix = os.path.realpath(sys.prefix)
    if not loaded_from.startswith(prefix + os.sep):
        fail_internal(f"duckdb loaded from {loaded_from}")
    if duckdb.__version__ != EXPECTED_DUCKDB_VERSION:
        fail_internal(f"duckdb {duckdb.__version__}")
    con = duckdb.connect(":memory:", config={"extension_directory": str(EXTENSION_ROOT)})
    try:
        con.execute("SET autoinstall_known_extensions=false")
        con.execute("SET autoload_known_extensions=false")
        platform = con.execute("PRAGMA platform").fetchone()[0]
        pins = PINS_BY_PLATFORM.get(platform)
        if pins is None:
            fail_internal(f"platform_unpinned: {platform}")
        hashed = {}
        for name, pin in pins.items():
            path = extension_file(platform, name)
            if not path.is_file():
                fail_internal(f"missing {path}")
            digest = sha256_file(path)
            if digest != pin["sha256"]:
                fail_internal(f"{name} sha256 {digest}")
            con.execute(sql_load(path))
            hashed[name] = path
        rows = con.execute(
            "SELECT extension_name, extension_version, loaded, install_path "
            "FROM duckdb_extensions() "
            "WHERE extension_name IN ('sitting_duck', 'duck_block_utils')"
        ).fetchall()
        found = {row[0]: row for row in rows}
        for name, pin in pins.items():
            row = found.get(name)
            if row is None or row[2] is not True or row[1] != pin["version"]:
                fail_internal(f"{name} version {row}")
            install = row[3]
            got = None if not install else os.path.realpath(install)
            expected = os.path.realpath(hashed[name])
            if got != expected:
                fail_internal(f"{name} install_path {got} != {expected}")
        return con
    except BaseException:
        con.close()
        raise


def seal(con):
    con.execute("SET enable_external_access=false")
    flag = con.execute("SELECT current_setting('enable_external_access')").fetchone()[0]
    if flag not in (False, "false"):
        fail_internal(f"enable_external_access={flag!r}")
    return con


def load_plane():
    con = prepare()
    try:
        return seal(con)
    except BaseException:
        con.close()
        raise


def language_for(con, path: str) -> str:
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if ext == "":
        raise ToolError("language_unsupported", "no extension")
    rows = con.execute(
        "SELECT language, extensions FROM ast_supported_languages()"
    ).fetchall()
    matches = []
    for language, extensions in rows:
        if not isinstance(language, str):
            continue
        for item in extensions or []:
            if isinstance(item, str) and item.lower() == ext:
                matches.append(language)
                break
    if not matches:
        raise ToolError("language_unsupported", f"unsupported extension: {ext}")
    matches.sort()
    return matches[0]


def render(con, text: str, language: str) -> str:
    con.execute(
        "CREATE TEMP TABLE ast AS SELECT * FROM parse_ast(?, ?, peek := 'full')",
        [text, language],
    )
    rows = con.execute(
        "SELECT duck_blocks_validate(list(block ORDER BY element_order)).valid, "
        "duck_blocks_to_text(list(block ORDER BY element_order)) "
        "FROM ast_to_blocks_from('ast') "
        "GROUP BY file_path "
        "ORDER BY file_path"
    ).fetchall()
    parts: list[str] = []
    for valid, rendered in rows:
        if valid is not True:
            raise ToolError("parse_failed", "duck_blocks_validate rejected blocks")
        if not isinstance(rendered, str):
            raise ToolError("parse_failed", "duck_blocks_to_text did not return text")
        parts.append(rendered)
    return "\n".join(parts)


def main() -> None:
    con = None
    try:
        raw = sys.stdin.buffer.read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise SystemExit(1)
        if text.strip() == "":
            emit({"ok": False, "error": "invalid_params", "message": "empty stdin"}, 3)
        try:
            req = json.loads(text)
        except json.JSONDecodeError:
            raise SystemExit(1)
        if not isinstance(req, dict):
            raise SystemExit(1)
        root = req.get("root")
        if "path" not in req or not isinstance(req.get("path"), str) or not isinstance(root, str):
            emit(
                {"ok": False, "error": "invalid_params", "message": "root and path must be strings"},
                3,
            )
        path = req["path"]
        if path.strip() == "":
            emit({"ok": False, "error": "invalid_params", "message": "path must not be empty"}, 3)
        resolved = resolve_path(root, path)
        con = load_plane()
        language = language_for(con, resolved)
        body = read_utf8(resolved)
        try:
            result = render(con, body, language)
        except ToolError:
            raise
        except Exception as exc:
            message = str(exc)
            if len(message) > 400:
                message = message[:400]
            raise ToolError("parse_failed", message) from exc
        emit({"ok": True, "result": result}, 0)
    finally:
        if con is not None:
            con.close()


if __name__ == "__main__":
    try:
        main()
    except ToolError as exc:
        emit({"ok": False, "error": exc.code, "message": exc.message}, 3)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
