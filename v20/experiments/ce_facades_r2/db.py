"""Open the round-two database on the repo's local PostgreSQL."""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg2
from psycopg2.extensions import parse_dsn

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = Path(__file__).with_name("schema.sql")
DB_NAME = "agent_v20_ce_facades_r2"


def _server():
    sys.path.insert(0, str(ROOT))
    from server import get_server

    return get_server()


def admin_dsn() -> str:
    return _server().get_uri("postgres")


def target_dsn() -> str:
    return _server().get_uri(DB_NAME)


def reset_database() -> str:
    """Drop and recreate only this experiment's database."""
    admin = psycopg2.connect(admin_dsn())
    admin.autocommit = True
    try:
        with admin.cursor() as cur:
            cur.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s AND pid <> pg_backend_pid()
                """,
                (DB_NAME,),
            )
            cur.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (DB_NAME,),
            )
            if cur.fetchone():
                cur.execute(f'DROP DATABASE "{DB_NAME}"')
            cur.execute(f'CREATE DATABASE "{DB_NAME}"')
    finally:
        admin.close()
    dsn = target_dsn()
    params = parse_dsn(dsn)
    host = params.get("host", "")
    if not host.startswith("/"):
        raise RuntimeError("round two requires a local Unix-domain PostgreSQL")
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(SCHEMA.read_text())
        conn.commit()
    finally:
        conn.close()
    return dsn
