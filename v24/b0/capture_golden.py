"""Capture candidate v1 vectors into a new, non-committed directory only.

Usage: uv run python v24/b0/capture_golden.py --output /tmp/v24-b0-golden-candidate-1
The destination must not exist. This tool never writes to v24/b0/golden/.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from golden_cases import capture_all, server_helper_scope, setup_db


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path,
                        help="explicit new candidate directory; existing paths are refused")
    args = parser.parse_args(argv)
    lexical_destination = args.output.expanduser().absolute()
    destination = lexical_destination.resolve(strict=False)
    repository = Path(__file__).resolve().parents[2]
    def inside(path, parent):
        try:
            return os.path.commonpath((str(path), str(parent))) == str(parent)
        except ValueError:
            return False
    # Refuse any repository path, even if currently absent, and any symlinked
    # alias whose resolved destination points back into the checkout.
    if inside(lexical_destination, repository) or inside(destination, repository):
        parser.error("candidate output must resolve outside the repository; delivery/tracked paths are forbidden")
    if destination.exists():
        parser.error(f"refusing to overwrite existing candidate directory: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with server_helper_scope():
        db = setup_db()
        try:
            with tempfile.TemporaryDirectory(prefix="b0-golden-journal-") as temp:
                vectors = capture_all(db, Path(temp))
        finally:
            db.close()
    # Build completely elsewhere, then publish by a single rename. Never replace.
    staging = Path(tempfile.mkdtemp(prefix=".b0-golden-stage-", dir=destination.parent))
    try:
        for name, cases in vectors.items():
            payload = {"format": "v24-tool-plugin-abi-v1-golden-1",
                       "domain_file": name, "cases": cases}
            (staging / name).write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8")
        os.rename(staging, destination)
    except BaseException:
        import shutil
        shutil.rmtree(staging, ignore_errors=True)
        raise
    counts = {name: len(cases) for name, cases in vectors.items()}
    print(f"[captured] {destination}; cases={counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
