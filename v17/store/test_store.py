"""G1 gate: v17 store — the jiti file store as Postgres tables.

Run: uv run python v17/store/test_store.py  (exit 0 = pass)

Scenarios: DDL shape (4 tables + constraints) / publish-load-list-rollback
end-to-end via the fiveam suite in a forked SBCL subprocess / ancestry
corruption detection (seq hole, broken parent link, cycle -> v17_list_revisions
raises) / concurrent publish serialization (advisory lock: both win, seqs
unique and hole-free) / journal operation-event validation (record.id +
record.status required, operation_id must agree or is backfilled) / crash
with no half-written revision (SIGKILL after INSERT, before COMMIT -> CURRENT
unmoved, no orphan row) / SBCL version mismatch refused on load / autocommit
publish refused (publish-revision requires with-store-transaction; both
inside the fiveam suite).
"""
from __future__ import annotations

import os
import select
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import psycopg2
from psycopg2.extras import Json

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v17.store.setup_db import DB, main as setup_db

LISP = AGENT_ROOT / "v17" / "lisp"
RUN_SUITE = LISP / "tests" / "run-store-suite.lisp"
CRASH_CHILD = LISP / "tests" / "crash-child.lisp"
SBCL_TIMEOUT = 300  # first run compiles postmodern/yason/fiveam FASLs


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def socket_dir(server) -> str:
    uri = server.get_uri(DB)
    host = parse_qs(urlparse(uri).query).get("host")
    check("env: pgembed uri carries a unix socket dir", bool(host), uri)
    return host[0]


def lisp_env(sockdir: str) -> dict:
    env = dict(os.environ)
    env["PGSOCKETDIR"] = sockdir
    env["PGDATABASE"] = DB
    return env


def run_sbcl(script: Path, env: dict, args: list[str] | None = None,
             timeout: int = SBCL_TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["sbcl", "--script", str(script)] + (args or []),
        env=env, capture_output=True, text=True, timeout=timeout)


def publish_sql(cur, world: str, state: str) -> str:
    cur.execute(
        "SELECT v17_publish_revision(%s::uuid, %s, %s::jsonb)::text",
        (world, state, Json({"sbcl": "gate"})))
    return cur.fetchone()[0]


def make_world(cur, name: str) -> str:
    cur.execute(
        "INSERT INTO lisp_worlds (name, package_name) VALUES (%s, %s) "
        "RETURNING world_id::text", (name, "V17-WORLD"))
    return cur.fetchone()[0]


def expect_raise(conn, cur, label: str, sql: str, args=()) -> None:
    try:
        cur.execute(sql, args)
        check(label, False, "expected an error, got none")
    except psycopg2.Error as exc:
        check(label, True, exc.diag.message_primary if exc.diag else str(exc))
    finally:
        conn.rollback()


def test_ddl_shape(conn, cur) -> None:
    cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name IN "
        "('lisp_worlds', 'lisp_revisions', 'lisp_current', 'lisp_journal')")
    got = sorted(r[0] for r in cur.fetchall())
    check("ddl: four store tables exist",
          got == ["lisp_current", "lisp_journal", "lisp_revisions",
                  "lisp_worlds"], got)

    w = make_world(cur, "ddl-shape")
    publish_sql(cur, w, "(defparameter *a* 1)")
    conn.commit()
    # UNIQUE (world_id, seq) on revisions
    expect_raise(conn, cur, "ddl: duplicate (world_id, seq) rejected",
                 "INSERT INTO lisp_revisions (world_id, seq, state_text, "
                 "sbcl_version) VALUES (%s, 1, 'x', 'gate')", (w,))
    # CHECK seq >= 1
    expect_raise(conn, cur, "ddl: seq 0 rejected by CHECK",
                 "INSERT INTO lisp_revisions (world_id, seq, state_text, "
                 "sbcl_version) VALUES (%s, 0, 'x', 'gate')", (w,))
    # append-only triggers
    expect_raise(conn, cur, "ddl: lisp_revisions is append-only (UPDATE)",
                 "UPDATE lisp_revisions SET state_text = 'tampered' "
                 "WHERE world_id = %s", (w,))
    expect_raise(conn, cur, "ddl: lisp_revisions is append-only (DELETE)",
                 "DELETE FROM lisp_revisions WHERE world_id = %s", (w,))
    cur.execute("SELECT v17_append_journal(%s::uuid, %s::jsonb)",
                (w, Json({"event": "note"})))
    conn.commit()
    expect_raise(conn, cur, "ddl: lisp_journal is append-only (UPDATE)",
                 "UPDATE lisp_journal SET event = '{}'::jsonb "
                 "WHERE world_id = %s", (w,))
    # name uniqueness on the registry
    expect_raise(conn, cur, "ddl: duplicate world name rejected",
                 "INSERT INTO lisp_worlds (name, package_name) "
                 "VALUES ('ddl-shape', 'V17-WORLD')")


def test_concurrent_publish(cur, uri: str) -> None:
    w = make_world(cur, "concurrent")
    cur.connection.commit()
    barrier = threading.Barrier(3)
    results: dict[int, str] = {}
    errors: dict[int, Exception] = {}

    def racer(idx: int) -> None:
        c = psycopg2.connect(uri)
        c.autocommit = True
        try:
            barrier.wait(timeout=10)
            cc = c.cursor()
            cc.execute(
                "SELECT v17_publish_revision(%s::uuid, %s, %s::jsonb)::text",
                (w, f"(defparameter *racer* {idx})", Json({"sbcl": "gate"})))
            results[idx] = cc.fetchone()[0]
        except Exception as exc:  # noqa: BLE001 - surfaced by the assertion
            errors[idx] = exc
        finally:
            c.close()

    threads = [threading.Thread(target=racer, args=(i,)) for i in (0, 1)]
    for t in threads:
        t.start()
    barrier.wait(timeout=10)
    for t in threads:
        t.join(timeout=30)
    check("concurrent: both racers returned (no deadlock)", not errors,
          {k: str(v) for k, v in errors.items()})
    check("concurrent: both publishes won, distinct revisions",
          len(set(results.values())) == 2, results)
    cur.execute("SELECT seq FROM lisp_revisions WHERE world_id = %s "
                "ORDER BY seq", (w,))
    seqs = [r[0] for r in cur.fetchall()]
    check("concurrent: seqs are unique and hole-free", seqs == [1, 2], seqs)
    cur.execute("SELECT r.seq FROM lisp_current c JOIN lisp_revisions r "
                "ON r.revision_id = c.revision_id WHERE c.world_id = %s", (w,))
    check("concurrent: CURRENT points at seq 2", cur.fetchone()[0] == 2)


def test_corruption_detection(conn, cur) -> None:
    w = make_world(cur, "corrupt")
    r1 = publish_sql(cur, w, "(defparameter *v* 1)")
    r2 = publish_sql(cur, w, "(defparameter *v* 2)")
    r3 = publish_sql(cur, w, "(defparameter *v* 3)")
    conn.commit()
    cur.execute("SELECT count(*) FROM v17_list_revisions(%s::uuid)", (w,))
    check("corruption: clean ancestry lists 3 revisions",
          cur.fetchone()[0] == 3)

    disable = "ALTER TABLE lisp_revisions DISABLE TRIGGER " \
              "trg_lisp_revisions_append_only"

    # seq hole: 1, 7, 3 (contiguity check must fire)
    cur.execute(disable)
    cur.execute("UPDATE lisp_revisions SET seq = 7 WHERE revision_id = %s::uuid",
                (r2,))
    expect_raise(conn, cur, "corruption: sequence hole detected",
                 "SELECT count(*) FROM v17_list_revisions(%s::uuid)", (w,))

    # broken parent link: rev2 loses its parent
    cur.execute(disable)
    cur.execute("UPDATE lisp_revisions SET parent_id = NULL "
                "WHERE revision_id = %s::uuid", (r2,))
    expect_raise(conn, cur, "corruption: broken parent link detected",
                 "SELECT count(*) FROM v17_list_revisions(%s::uuid)", (w,))

    # cycle: rev1's parent becomes the tip
    cur.execute(disable)
    cur.execute("UPDATE lisp_revisions SET parent_id = %s::uuid "
                "WHERE revision_id = %s::uuid", (r3, r1))
    expect_raise(conn, cur, "corruption: ancestry cycle detected",
                 "SELECT count(*) FROM v17_list_revisions(%s::uuid)", (w,))

    # orphan: a revision of this world unreachable from CURRENT
    cur.execute(disable)
    cur.execute("UPDATE lisp_revisions SET parent_id = NULL "
                "WHERE revision_id = %s::uuid", (r2,))
    cur.execute("DELETE FROM lisp_current WHERE world_id = %s::uuid", (w,))
    cur.execute("INSERT INTO lisp_current (world_id, revision_id) "
                "VALUES (%s::uuid, %s::uuid)", (w, r1))
    expect_raise(conn, cur, "corruption: orphan revisions detected",
                 "SELECT count(*) FROM v17_list_revisions(%s::uuid)", (w,))


def test_crash_no_half_revision(conn, cur, env: dict) -> None:
    w = make_world(cur, "crash")
    r1 = publish_sql(cur, w, "(defparameter *stable* 1)")
    conn.commit()
    cur.execute("SELECT revision_id::text FROM lisp_current "
                "WHERE world_id = %s", (w,))
    before_current = cur.fetchone()[0]
    check("crash: CURRENT at seq 1 before child", before_current == r1)

    proc = subprocess.Popen(
        ["sbcl", "--script", str(CRASH_CHILD), w, "999"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + SBCL_TIMEOUT
    ready = False
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            break
        r, _, _ = select.select([proc.stdout], [], [], 0.5)
        if r:
            line = proc.stdout.readline()
            if "READY" in line:
                ready = True
                break
    check("crash: child printed READY after its INSERT", ready,
          proc.stderr.read() if proc.poll() is not None else "")
    proc.send_signal(signal.SIGKILL)
    proc.wait(timeout=10)

    cur.execute("SELECT revision_id::text FROM lisp_current "
                "WHERE world_id = %s", (w,))
    check("crash: CURRENT unmoved after SIGKILL (txn rolled back)",
          cur.fetchone()[0] == before_current)
    cur.execute("SELECT count(*), max(seq) FROM lisp_revisions "
                "WHERE world_id = %s", (w,))
    n, mx = cur.fetchone()
    check("crash: no orphan revision row (seq 999 rolled back)",
          n == 1 and mx == 1, (n, mx))


def test_journal_event_validation(conn, cur) -> None:
    w = make_world(cur, "journal-validation")
    conn.commit()
    # operation events must carry a record object with non-empty id + status
    expect_raise(conn, cur,
                 "journal: operation-start without record refused",
                 "SELECT v17_append_journal(%s::uuid, %s::jsonb)",
                 (w, Json({"event": "operation-start"})))
    expect_raise(conn, cur,
                 "journal: operation-start without record.id refused",
                 "SELECT v17_append_journal(%s::uuid, %s::jsonb)",
                 (w, Json({"event": "operation-start",
                           "record": {"status": "running"}})))
    expect_raise(conn, cur,
                 "journal: operation-finish without record.status refused",
                 "SELECT v17_append_journal(%s::uuid, %s::jsonb)",
                 (w, Json({"event": "operation-finish",
                           "record": {"id": "op-x"}})))
    expect_raise(conn, cur,
                 "journal: operation_id disagreeing with record.id refused",
                 "SELECT v17_append_journal(%s::uuid, %s::jsonb, %s)",
                 (w, Json({"event": "operation-start",
                           "record": {"id": "op-x", "status": "running"}}),
                  "op-y"))
    # non-operation events stay free-form
    cur.execute("SELECT v17_append_journal(%s::uuid, %s::jsonb)",
                (w, Json({"event": "note"})))
    # well-formed operation event: operation_id backfilled from record.id
    cur.execute("SELECT v17_append_journal(%s::uuid, %s::jsonb)",
                (w, Json({"event": "operation-start",
                          "record": {"id": "op-ok", "status": "running"}})))
    cur.execute("SELECT operation_id FROM lisp_journal "
                "WHERE world_id = %s::uuid AND seq = 2", (w,))
    check("journal: operation_id backfilled from record.id",
          cur.fetchone()[0] == "op-ok")
    cur.execute("SELECT count(*) FROM lisp_journal WHERE world_id = %s::uuid",
                (w,))
    check("journal: rejected appends left no holes", cur.fetchone()[0] == 2)
    conn.commit()


def test_fiveam_suite(env: dict) -> None:
    proc = run_sbcl(RUN_SUITE, env)
    sys.stdout.write(proc.stdout)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr[-4000:])
    check("fiveam: store suite green (publish/load/list/rollback, journal, "
          "recover, journal validation, autocommit-publish refusal, sbcl "
          "version refusal)", proc.returncode == 0,
          f"exit {proc.returncode}")


def main() -> int:
    setup_db()
    server = get_server()
    uri = server.get_uri(DB)
    sockdir = socket_dir(server)
    env = lisp_env(sockdir)
    conn = psycopg2.connect(uri)
    cur = conn.cursor()

    test_ddl_shape(conn, cur)
    test_concurrent_publish(cur, uri)
    test_corruption_detection(conn, cur)
    test_journal_event_validation(conn, cur)
    test_crash_no_half_revision(conn, cur, env)
    test_fiveam_suite(env)

    conn.commit()
    conn.close()
    print("[G1 store] ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
