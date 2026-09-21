"""Create the isolated v13 resolve database and load through resolve.

Deployment probes (plan §4 M2): typesafe ACL, unreachable-endpoint contract
code, and 57014 deliverability. M3/M4 import these helpers.
"""
from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v13.load import load_stage, run_psql

DB = "agent_v13_resolve"
STAGE = "resolve"

LOCAL_CLASSES = ("P0", "XX", "42", "22", "55", "53", "54", "40", "57")


def _hanging_server():
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(8)
    port = sock.getsockname()[1]
    stop = threading.Event()

    def serve() -> None:
        sock.settimeout(0.3)
        while not stop.is_set():
            try:
                conn, _ = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                time.sleep(8)
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
        try:
            sock.close()
        except OSError:
            pass

    threading.Thread(target=serve, daemon=True).start()
    return port, stop


def verify_typesafe_acl(cur) -> None:
    cur.execute(
        "SELECT has_function_privilege('public',"
        " 'typesafe_ask(jsonb,jsonb,text)', 'EXECUTE'),"
        " has_function_privilege('v13_resolve',"
        " 'typesafe_ask(jsonb,jsonb,text)', 'EXECUTE')")
    pub, nxt = cur.fetchone()
    if pub or not nxt:
        raise SystemExit(
            f"typesafe_ask ACL probe failed: PUBLIC={pub} v13_resolve={nxt}")


TIMEOUT_57014 = False


def probe_unreachable(conn) -> str:
    cur = conn.cursor()
    cur.execute("SAVEPOINT sp_unreach")
    cur.execute("SELECT set_config('typesafe.endpoint',"
                " 'http://127.0.0.1:1/', true)")
    cur.execute("SELECT set_config('typesafe.api_key', 'probe', true)")
    cur.execute("SELECT set_config('typesafe.mock_response', NULL, true)")
    pgcode = None
    try:
        cur.execute("SELECT typesafe_ask('{}'::jsonb, '{}'::jsonb)")
    except psycopg2.Error as exc:
        pgcode = exc.pgcode or ""
        cur.execute("ROLLBACK TO SAVEPOINT sp_unreach")
    else:
        cur.execute("ROLLBACK TO SAVEPOINT sp_unreach")
        raise SystemExit("unreachable probe: typesafe_ask succeeded")
    if (not pgcode or len(pgcode) != 5
            or pgcode == "V3001" or pgcode == "57014"
            or pgcode[:2] in LOCAL_CLASSES):
        raise SystemExit(
            f"unreachable probe: pgcode {pgcode!r} collides with local/"
            "V3001/57014 space — contract broken")
    cur.execute(
        "INSERT INTO v13_remote_sqlstates (sqlstate, origin, note) "
        "VALUES (%s, 'probe_unreachable', 'setup unreachable endpoint') "
        "ON CONFLICT (sqlstate) DO NOTHING",
        (pgcode,))
    conn.commit()
    print(f"[probe] unreachable pgcode={pgcode}")
    return pgcode


def probe_timeout(conn) -> None:
    port, stop = _hanging_server()
    cur = conn.cursor()
    cur.execute("SAVEPOINT sp_to")
    try:
        cur.execute("SELECT set_config('typesafe.endpoint', %s, true)",
                    (f"http://127.0.0.1:{port}/",))
        cur.execute("SELECT set_config('typesafe.api_key', 'probe', true)")
        cur.execute("SELECT set_config('typesafe.mock_response', NULL, true)")
        cur.execute("SELECT set_config('typesafe.timeout_ms', '5000', true)")
        cur.execute("SET LOCAL statement_timeout = '50ms'")
        try:
            cur.execute("SELECT typesafe_ask('{}'::jsonb, '{}'::jsonb)")
            cur.execute("ROLLBACK TO SAVEPOINT sp_to")
            raise SystemExit(
                "timeout probe: typesafe_ask succeeded; 57014 not delivered. "
                "Fallback: revise K1(ii)/K2/K6 to V3001 mock (turn 7 #45(b)).")
        except psycopg2.Error as exc:
            cur.execute("ROLLBACK TO SAVEPOINT sp_to")
            if exc.pgcode != "57014":
                print(
                    f"[probe] timeout NOT 57014 (got {exc.pgcode!r}); "
                    "pg_typesafe HTTP wait is not statement_timeout-interruptible. "
                    "Applying turn 7 #45(b) fallback: V3001 mock carries "
                    "failed=true; M2-15(a)/(b) stay contract notes until "
                    "HTTP wait is interruptible."
                )
                return
            global TIMEOUT_57014
            TIMEOUT_57014 = True
            print("[probe] timeout pgcode=57014")
    finally:
        stop.set()


def run_probes(server, database: str) -> None:
    conn = psycopg2.connect(server.get_uri(database))
    conn.autocommit = False
    cur = conn.cursor()
    verify_typesafe_acl(cur)
    probe_unreachable(conn)
    probe_timeout(conn)
    conn.close()


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
