"""Create the isolated v13 manifest database and load through manifest."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v13.load import load_stage, run_psql
from v13.resolve.setup_db import run_probes

DB = "agent_v13_manifest"
STAGE = "manifest"


def main() -> int:
    s = get_server()
    run_psql(s, "postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE);")
    run_psql(s, "postgres", f"CREATE DATABASE {DB};")
    load_stage(s, DB, STAGE)
    run_probes(s, DB)
    print("[ready]", DB)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
