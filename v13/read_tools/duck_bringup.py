#!/usr/bin/env python3
"""One-shot bring-up for the duck read plane.

Creates v13/read_tools/.duck-venv, pins duckdb==1.5.5, and INSTALLs
sitting_duck and duck_block_utils FROM community into the local extension
cache. Does not touch the repo pyproject or uv.lock. Network is used only
here; the read port LOADs from that cache with autoinstall off.
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
import sys

import duckdb

NAMES = ("sitting_duck", "duck_block_utils")

def install(con, name):
    community_error = None
    try:
        con.execute(f"INSTALL {name} FROM community")
        return "community"
    except Exception as exc:
        community_error = exc
    try:
        con.execute(f"INSTALL {name}")
    except Exception as official_error:
        print(f"FAIL {name} community: {community_error}", file=sys.stderr)
        print(f"FAIL {name} official: {official_error}", file=sys.stderr)
        sys.exit(1)
    print(f"WARN {name} community INSTALL failed; used official", file=sys.stderr)
    print(community_error, file=sys.stderr)
    return "official"

con = duckdb.connect(":memory:")
channels = {name: install(con, name) for name in NAMES}
for name in NAMES:
    con.execute(f"LOAD {name}")

print(f"duckdb_version={duckdb.__version__}")
try:
    platform_row = con.execute("PRAGMA platform").fetchone()
    print(f"platform={platform_row[0]}")
except Exception as exc:
    print(f"platform_error={exc}", file=sys.stderr)

cur = con.execute("SELECT * FROM duckdb_extensions()")
columns = [item[0] for item in cur.description]
rows = cur.fetchall()
print("duckdb_extensions_columns=" + ",".join(columns))
by_name = {}
for row in rows:
    record = dict(zip(columns, row))
    if record.get("extension_name") in NAMES:
        by_name[record["extension_name"]] = record

missing = [name for name in NAMES if name not in by_name]
if missing:
    print(f"FAIL missing from duckdb_extensions(): {missing}", file=sys.stderr)
    sys.exit(1)

for name in NAMES:
    record = by_name[name]
    version = record.get("extension_version")
    path = record.get("install_path") or ""
    print(f"{name}_channel={channels[name]}")
    print(f"{name}_version={version}")
    print(f"{name}_loaded={record.get('loaded')}")
    print(f"{name}_install_path={path}")
    if not path:
        print(f"FAIL {name} has no install_path", file=sys.stderr)
        sys.exit(1)
    digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
    print(f"{name}_sha256={digest}")
"""


def main() -> int:
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
    script_path = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
            handle.write(INNER)
            script_path = handle.name
        completed = subprocess.run([str(PY), script_path])
        return completed.returncode
    finally:
        if script_path is not None:
            Path(script_path).unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        print(exc, file=sys.stderr)
        sys.exit(exc.returncode or 1)
