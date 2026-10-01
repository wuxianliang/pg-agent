"""claim_one for v13_claim_fair."""
from __future__ import annotations

import json

from psycopg2.extensions import TRANSACTION_STATUS_IDLE

RETRIES = 2


def as_obj(value):
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


def claim_one(conn, worker: str, lease_ms: int = 60000):
    if conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
        raise RuntimeError("v13: claim fair: canonical")
    was = conn.autocommit
    conn.autocommit = False
    attempts = 0
    try:
        while True:
            attempts += 1
            cur = conn.cursor()
            try:
                cur.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                cur.execute("SELECT v13_claim_fair(%s, %s)", (worker, lease_ms))
                row = cur.fetchone()
                conn.commit()
                return as_obj(None if row is None else row[0])
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception:
                    pass
                if getattr(exc, "pgcode", None) == "40P01" and attempts < RETRIES:
                    continue
                raise
    finally:
        conn.autocommit = was
