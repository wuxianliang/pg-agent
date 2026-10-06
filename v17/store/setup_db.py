"""Create the isolated v17 G1 database and load through the store stage."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v17.load import load_stage, run_psql

DB = "agent_v17_store"
STAGE = "store"


def main() -> int:
    s = get_server()
    run_psql(s, "postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE);")
    run_psql(s, "postgres", f"CREATE DATABASE {DB};")
    load_stage(s, DB, STAGE)
    print("[ready]", DB)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
