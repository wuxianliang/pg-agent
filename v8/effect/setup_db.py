"""Create the isolated v8 G4 database and load the effect stage."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v8.load import load_stage, run_psql

DB = "agent_v8_effect"
STAGE = "effect"


def main() -> int:
    s = get_server()
    run_psql(s, "postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE);")
    run_psql(s, "postgres", f"CREATE DATABASE {DB};")
    load_stage(s, DB, STAGE)
    print("[ready]", DB)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
