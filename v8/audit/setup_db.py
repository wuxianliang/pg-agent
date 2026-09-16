"""Create the isolated v8 G16 database and load through the audit stage.

G16 (audit) adds the versioned raw-byte audit keys' carriers: the remaining
effect_audit columns, the two occurrence child tables and the
internal_op_audits table. Its SQL file sits at load position 3 (after
schema/keys, before grant) — the three-key judgement is consumed by the
events stage's receipt/binding ordering, so it must load before
v8_append.sql.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v8.load import load_stage, run_psql

DB = "agent_v8_audit"
STAGE = "audit"


def main() -> int:
    s = get_server()
    run_psql(s, "postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE);")
    run_psql(s, "postgres", f"CREATE DATABASE {DB};")
    load_stage(s, DB, STAGE)
    print("[ready]", DB)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
