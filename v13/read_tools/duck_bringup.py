#!/usr/bin/env python3
"""One-shot bring-up for the duck read plane.

Creates v13/read_tools/.duck-venv, pins duckdb==1.5.5, and INSTALLs
sitting_duck and duck_block_utils FROM community into the local extension
cache. Does not touch the repo pyproject or uv.lock. Network is used only
by the install path. --verify-only checks the same pins offline.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".duck-venv"
PY = VENV / "bin" / "python"
DUCKDB_SPEC = "duckdb==1.5.5"

INNER = r"""
import hashlib
import os
import sys

sys.path.insert(0, sys.argv[1])
mode = sys.argv[2]

from read_duck_port import EXPECTED_DUCKDB_VERSION, EXTENSION_ROOT, PINS_BY_PLATFORM
import duckdb


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    sys.exit(1)


if duckdb.__version__ != EXPECTED_DUCKDB_VERSION:
    fail(
        f"FAIL duckdb version expected={EXPECTED_DUCKDB_VERSION} got={duckdb.__version__}"
    )

con = duckdb.connect(":memory:", config={"extension_directory": str(EXTENSION_ROOT)})
con.execute("SET autoinstall_known_extensions=false")
con.execute("SET autoload_known_extensions=false")
platform = con.execute("PRAGMA platform").fetchone()[0]
print(f"duckdb_version={duckdb.__version__}")
print(f"platform={platform}")
pins = PINS_BY_PLATFORM.get(platform)
if pins is None:
    fail(f"FAIL platform_unpinned expected={sorted(PINS_BY_PLATFORM)} got={platform}")

if mode == "install":
    for name in pins:
        try:
            con.execute(f"INSTALL {name} FROM community")
        except Exception as exc:
            fail(f"FAIL {name} community: {exc}")
        print(f"{name}_channel=community")
elif mode != "verify":
    fail(f"FAIL unknown mode {mode}")

for name, pin in pins.items():
    path = EXTENSION_ROOT / f"v{EXPECTED_DUCKDB_VERSION}" / platform / f"{name}.duckdb_extension"
    if not path.is_file():
        fail(f"FAIL missing {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    print(f"{name}_sha256={digest}")
    if digest != pin["sha256"]:
        fail(f"FAIL {name} sha256 expected={pin['sha256']} got={digest}")
    text = str(path)
    if "'" in text:
        fail(f"FAIL {name} path contains quote: {text}")
    con.execute(f"LOAD '{text}'")

rows = con.execute(
    "SELECT extension_name, extension_version, loaded, install_path "
    "FROM duckdb_extensions() "
    "WHERE extension_name IN ('sitting_duck', 'duck_block_utils')"
).fetchall()
found = {row[0]: row for row in rows}
for name, pin in pins.items():
    row = found.get(name)
    version = None if row is None else row[1]
    loaded = None if row is None else row[2]
    install = None if row is None else row[3]
    hashed = EXTENSION_ROOT / f"v{EXPECTED_DUCKDB_VERSION}" / platform / f"{name}.duckdb_extension"
    print(f"{name}_version={version}")
    print(f"{name}_loaded={loaded}")
    print(f"{name}_install_path={install}")
    if row is None or loaded is not True or version != pin["version"]:
        fail(f"FAIL {name} version expected={pin['version']} got={row}")
    if not install or os.path.realpath(install) != os.path.realpath(hashed):
        fail(
            f"FAIL {name} install_path expected={os.path.realpath(hashed)} got={install}"
        )
con.close()
"""


def usage() -> int:
    print(
        "usage: uv run python v13/read_tools/duck_bringup.py [--verify-only]",
        file=sys.stderr,
    )
    return 2


def run_inner(mode: str) -> int:
    script_path = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
            handle.write(INNER)
            script_path = handle.name
        completed = subprocess.run([str(PY), script_path, str(ROOT), mode])
        return completed.returncode
    finally:
        if script_path is not None:
            Path(script_path).unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--verify-only"]:
        if not PY.is_file():
            print(f"venv missing: {PY}", file=sys.stderr)
            return 1
        return run_inner("verify")
    if args:
        return usage()
    uv = shutil.which("uv")
    if uv is None:
        print("uv not found", file=sys.stderr)
        return 1
    if not PY.is_file():
        subprocess.run([uv, "venv", str(VENV), "--python", "3.12"], check=True)
    subprocess.run(
        [uv, "pip", "install", "--python", str(PY), DUCKDB_SPEC],
        check=True,
    )
    return run_inner("install")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        print(exc, file=sys.stderr)
        sys.exit(exc.returncode or 1)
