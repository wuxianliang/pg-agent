"""Create the isolated v8 G10 database and load through the grant stage.

Also provisions the non-superuser worker role used by the RLS vectors:
NOLOGIN, NOBYPASSRLS, USAGE on schema public, SELECT on the tenant tables
and EXECUTE on functions — never any business-table DML (the capability
functions are the only write channel, SECURITY DEFINER + per-function
audit). The role is cluster-scoped while the database is recreated below,
so it is dropped and recreated here on every run.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v8.load import load_stage, run_psql

DB = "agent_v8_grant"
STAGE = "grant"


def main() -> int:
    s = get_server()
    run_psql(s, "postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE);")
    run_psql(s, "postgres", f"CREATE DATABASE {DB};")
    load_stage(s, DB, STAGE)
    run_psql(s, "postgres", "DROP ROLE IF EXISTS v8_worker;")
    run_psql(s, "postgres",
             "CREATE ROLE v8_worker LOGIN NOBYPASSRLS;")
    run_psql(
        s, DB,
        "GRANT USAGE ON SCHEMA public TO v8_worker;"
        "GRANT SELECT ON slices, grants, workspace_handles, stream_registry,"
        " grant_ops_audit, authz_denial_audits TO v8_worker;"
        "GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO v8_worker;")
    print("[ready]", DB)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
