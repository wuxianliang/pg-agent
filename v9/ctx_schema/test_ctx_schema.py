"""W2 gate: ctx_schema stage — context pack state tables, CHECKs, and uniqueness."""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v9.ctx_schema.setup_db import DB, main as setup_db

# Full expected column sets per spec §3, verified through information_schema.
EXPECTED_COLUMNS = {
    "ctx_sources": {
        "source_id", "repo_path", "schema_name", "table_name", "max_rows",
        "enabled", "created_at",
    },
    "repo_heads": {"repo_path", "head_commit", "updated_at"},
    "context_commits": {"repo_path", "commit_id", "seq", "created_at"},
    "context_commit_files": {"repo_path", "commit_id", "dep_uri"},
    "context_packs": {
        "pack_id", "task_run_id", "repo_path", "status", "base_commit",
        "generation", "next_op_seq", "last_completed_op_seq", "pending_refresh",
        "token_count", "worker_id", "last_error", "created_at", "updated_at",
    },
    "context_slices": {
        "pack_id", "slice_id", "seq", "kind", "dep_uri", "title", "body",
        "content_hash", "generation", "stale", "updated_at",
    },
    "slice_dependencies": {"pack_id", "slice_id", "dep_uri", "built_at_commit"},
    "context_refresh_log": {
        "pack_id", "seq", "trigger_kind", "trigger_ref", "dirty_slices",
        "rebuilt_slices", "base_from", "base_to", "created_at",
    },
    "ctx_operations": {
        "request_id", "pack_id", "op_kind", "op_seq", "status",
        "built_at_commit", "worker_id", "result_summary", "error",
        "created_at", "started_at", "finished_at",
    },
}

# Key columns the spec calls out explicitly for spot-checking.
KEY_COLUMNS = [
    ("context_packs", "last_completed_op_seq"),
    ("context_packs", "pending_refresh"),
    ("ctx_operations", "request_id"),
    ("ctx_operations", "status"),
    ("slice_dependencies", "built_at_commit"),
]

EXPECTED_INDEXES = {
    "slice_dep_uri_idx",
    "ctx_commits_seq_idx",
    "ctx_slices_stale_idx",
    "ctx_ops_pack_idx",
    "ctx_ops_open_idx",
}


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def table_columns(cur, table: str) -> set:
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
        (table,),
    )
    return {row[0] for row in cur.fetchall()}


def fails_with(cur, sql: str, params: tuple, needle: str, label: str) -> None:
    try:
        cur.execute(sql, params)
    except psycopg2.Error as exc:
        check(label, needle in str(exc).lower(), exc)
        return
    check(label, False, "statement unexpectedly succeeded")


def main() -> int:
    check("setup", setup_db() == 0)
    conn = psycopg2.connect(get_server().get_uri(DB))
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            for table, expected in EXPECTED_COLUMNS.items():
                actual = table_columns(cur, table)
                check(f"{table} has all expected columns", expected <= actual,
                      f"missing={sorted(expected - actual)}")

            for table, column in KEY_COLUMNS:
                check(f"column {table}.{column} present",
                      column in table_columns(cur, table))

            # CHECK constraint: context_packs rejects an illegal status.
            run = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO agent_runs(run_id, question) VALUES (%s, %s)",
                (run, "w2 ctx_schema gate"),
            )
            fails_with(
                cur,
                "INSERT INTO context_packs(pack_id, task_run_id, repo_path, status)"
                " VALUES (%s, %s, %s, 'NOT_A_STATUS')",
                ("p_bad_status", run, "default"),
                "check",
                "context_packs rejects illegal status",
            )

            # UNIQUE(task_run_id): first pack for the run is accepted...
            pack = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO context_packs(pack_id, task_run_id, repo_path)"
                " VALUES (%s, %s, 'default')",
                (pack, run),
            )
            check("first context_packs row accepted", True)
            # ...a second pack for the same run is rejected.
            fails_with(
                cur,
                "INSERT INTO context_packs(pack_id, task_run_id, repo_path)"
                " VALUES (%s, %s, 'default')",
                ("p_dup", run),
                "duplicate",
                "context_packs enforces UNIQUE(task_run_id)",
            )

            # FK: a pack pointing at a nonexistent run is rejected.
            fails_with(
                cur,
                "INSERT INTO context_packs(pack_id, task_run_id, repo_path)"
                " VALUES (%s, %s, 'default')",
                ("p_fk", "no-such-run"),
                "foreign key",
                "context_packs enforces FK to agent_runs",
            )

            # CHECK constraint: context_slices rejects an illegal kind.
            fails_with(
                cur,
                "INSERT INTO context_slices(pack_id, slice_id, seq, kind, dep_uri,"
                " body, content_hash) VALUES (%s, %s, 1, 'NOT_A_KIND', %s, %s, %s)",
                (pack, "s_bad_kind", "src:none", "body", "hash"),
                "check",
                "context_slices rejects illegal kind",
            )

            cur.execute(
                "SELECT indexname FROM pg_indexes WHERE indexname = 'slice_dep_uri_idx'"
            )
            check("slice_dep_uri_idx exists in pg_indexes", cur.fetchone() is not None)

            cur.execute("SELECT indexname FROM pg_indexes")
            present = {row[0] for row in cur.fetchall()}
            check("all v9 indexes present", EXPECTED_INDEXES <= present,
                  f"missing={sorted(EXPECTED_INDEXES - present)}")
    finally:
        conn.close()
    print("[W2] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
