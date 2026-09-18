"""Manual live probe: one full decide, entirely inside Postgres.

NOT a gate — real network call through pg_typesafe. Run with the key:

    uv run python v12/indb/probe_indb.py   # reads OPENROUTER_API_KEY

Points typesafe.endpoint at OpenRouter's decisions endpoint (native
systemone body, verified earlier), then a single SQL call —
SELECT v12_decide_in_db(session) — folds state, asks Jev, records answers
and persists the route. Cost: one turn batch (~$0.00004).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v12.indb.setup_db import DB, main as setup_db


def main() -> int:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        print("set OPENROUTER_API_KEY first (this script talks to the network)")
        return 2
    setup_db()
    conn = psycopg2.connect(get_server().get_uri(DB))
    cur = conn.cursor()
    cur.execute("SELECT set_config('typesafe.endpoint', "
                "'https://openrouter.ai/api/alpha/decisions', false)")
    cur.execute("SELECT set_config('typesafe.api_key', %s, false)", (key,))
    cur.execute("SELECT set_config('typesafe.model', 'typesafe/jev-1.13', false)")

    cur.execute("INSERT INTO sessions (workspace_id) VALUES ('probe') "
                "RETURNING session_id")
    sid = str(cur.fetchone()[0])
    cur.execute("SELECT v12_append_event(%s, 'user/message', %s)",
                (sid, json.dumps(
                    {"text": "How many messages are in this session so far?"})))
    conn.commit()

    cur.execute("SELECT v12_decide_in_db(%s)", (sid,))
    route = cur.fetchone()[0]
    conn.commit()

    cur.execute("SELECT type, payload FROM events WHERE session_id = %s "
                "ORDER BY seq", (sid,))
    events = cur.fetchall()
    cur.execute("SELECT status, usage, latency_ms FROM jev_batches "
                "WHERE session_id = %s", (sid,))
    batch = cur.fetchone()
    print("route    :", route)
    for t, p in events:
        print(f"  {t} -> {json.dumps(p, ensure_ascii=False)[:140]}")
    print("batch    :", batch[0], "| usage:", batch[1], "| latency_ms:", batch[2])
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
