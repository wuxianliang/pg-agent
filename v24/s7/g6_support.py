"""Concurrency primitives for the v24 S7 G6 gate.

This module contains *only* harness mechanics: two-connection ordering,
``pg_blocking_pids``/``pg_locks`` evidence, held-G controls, ten-table
snapshot/diff wrappers and the evidence-line format frozen in the S7 plan
(§4.4/§4.6).  It contains no product semantics, no DDL and no SQL.

Ordering is never guessed: a writer that returned from ``advance`` keeps its
transaction open (and therefore the transaction-scoped
``pg_advisory_xact_lock(24,1)`` G lock), a second connection/thread waits, and
the wait is observed with ``pg_blocking_pids()`` plus an ungranted advisory
``pg_locks`` row.  Every polling loop is deadline-bounded with
``time.monotonic()``; this file contains no sleep call.

The snapshot/diff implementation is not duplicated: ``snapshot``/``diff`` are
thin wrappers over ``v24/s6/g5_support.py`` (``g5_snapshot``,
``snapshot_diff``, ``fingerprint``).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
S1 = ROOT.parent / "s1"
S4 = ROOT.parent / "s4"
S6 = ROOT.parent / "s6"
for _path in (S1, S4, S6):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from g5_support import (  # noqa: E402
    fingerprint as _fingerprint,
    g5_snapshot as _g5_snapshot,
    snapshot_diff as _snapshot_diff,
)
from test_g2b import ordered_advance_race  # noqa: E402

# The exact identity of G: pg_advisory_xact_lock(24, 1) -> classid/objid/objsubid.
G_CLASSID = 24
G_OBJID = 1
G_OBJSUBID = 2

# Relation modes that can block a writer / imply a row or table write intent.
# AccessShareLock is the only mode a read verb is allowed to take on v24 tables.
WRITE_LOCK_MODES = (
    "RowShareLock", "RowExclusiveLock", "ShareLock", "ShareRowExclusiveLock",
    "ExclusiveLock", "AccessExclusiveLock",
)


# ---------------------------------------------------------------------------
# Ten-table snapshot / diff (thin wrappers, no second implementation)
# ---------------------------------------------------------------------------

def snapshot(conn) -> dict:
    """Snapshot the ten domain tables and end the read transaction."""
    value = _g5_snapshot(conn)
    conn.rollback()
    return value


def diff(before: dict, after: dict) -> dict:
    """Structured added/changed/removed rows, keyed by table."""
    return _snapshot_diff(before, after)


def fingerprint(snap: dict) -> str:
    """Canonical sha256 of a ten-table snapshot."""
    return _fingerprint(snap)


def diff_counts(diff_value: dict) -> dict[str, tuple[int, int, int]]:
    """``{table: (added, changed, removed)}`` for every changed table."""
    return {
        table: (len(rows["added"]), len(rows["changed"]), len(rows["removed"]))
        for table, rows in diff_value.items()
    }


def format_diff(diff_value: dict) -> str:
    """Compact ``table:+a/~c/-r`` evidence text; unchanged tables are omitted."""
    counts = diff_counts(diff_value)
    if not counts:
        return "zero-ten-tables"
    return ",".join(
        f"{table}:+{counts[table][0]}/~{counts[table][1]}/-{counts[table][2]}"
        for table in sorted(counts)
    )


def assert_diff_exact(diff_value: dict, expected: dict, label: str) -> None:
    """Exact table-level added/changed/removed counts (no weak superset)."""
    actual = diff_counts(diff_value)
    assert actual == expected, (label, actual, expected, diff_value)


# ---------------------------------------------------------------------------
# Small probes
# ---------------------------------------------------------------------------

def _scalar(conn, statement, params=()):
    with conn.cursor() as cur:
        cur.execute(statement, params)
        return cur.fetchone()[0]


def _g_grants(conn, pid: int) -> int:
    return _scalar(
        conn,
        """SELECT count(*) FROM pg_locks WHERE pid=%s AND locktype='advisory'
             AND classid=%s AND objid=%s AND objsubid=%s AND granted""",
        (pid, G_CLASSID, G_OBJID, G_OBJSUBID),
    )


def _g_waits(conn, pid: int) -> int:
    return _scalar(
        conn,
        """SELECT count(*) FROM pg_locks WHERE pid=%s AND locktype='advisory'
             AND classid=%s AND objid=%s AND objsubid=%s AND NOT granted""",
        (pid, G_CLASSID, G_OBJID, G_OBJSUBID),
    )


def _product_locks(conn, pid: int, *, granted: bool) -> int:
    """Granted row/tuple/relation write locks, or ungranted non-G locks."""
    qualifier = "l.granted" if granted else "NOT l.granted"
    row_and_relation = _scalar(
        conn,
        f"""SELECT count(*) FROM pg_locks l
              LEFT JOIN pg_class c ON c.oid=l.relation
             WHERE l.pid=%s AND {qualifier}
               AND (l.locktype='tuple'
                    OR (l.locktype='relation' AND c.relnamespace='v24'::regnamespace
                        AND l.mode = ANY(%s)))""",
        (pid, list(WRITE_LOCK_MODES)),
    )
    non_g_waits = 0
    if not granted:
        non_g_waits = _scalar(
            conn,
            """SELECT count(*) FROM pg_locks WHERE pid=%s AND NOT granted
                 AND NOT (locktype='advisory' AND classid=%s AND objid=%s
                          AND objsubid=%s)""",
            (pid, G_CLASSID, G_OBJID, G_OBJSUBID),
        )
    return row_and_relation + non_g_waits


def _waiters_only_on_g(observer, pid: int) -> None:
    """A waiter for G must not hold a v24 row or relation *write* lock.

    A plain public wrapper (``v24.start``/``fiber_control``/``dispose``) can
    hold an ``AccessShareLock`` on a v24 relation while PostgreSQL plans the
    invoked PL/pgSQL body; that read lock is compatible with every writer and
    cannot be the "lock after G" failure this gate is looking for.  Tuple
    locks, advisory locks and relation modes from RowShareLock upward are
    rejected (the L1 shape: the waiter queued only on G).
    """
    assert _product_locks(observer, pid, granted=True) == 0, (
        f"pid {pid} held a v24 tuple/relation write lock before acquiring G")
    assert _scalar(
        observer,
        "SELECT count(*) FROM pg_locks WHERE pid=%s AND locktype='advisory' AND granted",
        (pid,),
    ) == 0, f"pid {pid} held an advisory lock before acquiring G"


# ---------------------------------------------------------------------------
# Held G / blocking evidence
# ---------------------------------------------------------------------------

def held_g(conn) -> int:
    """Take G explicitly on ``conn`` and return its backend pid.

    The caller owns the transaction: release is ``commit``/``rollback`` on
    ``conn``.  Used only for controls/negatives, never for product ordering.
    """
    pid = conn.get_backend_pid()
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (G_CLASSID, G_OBJID))
    assert _g_grants(conn, pid) == 1, (pid, "held_g did not acquire G")
    return pid


def wait_for_g_block(observer, holder_pid: int, waiter_pid: int, tag: str,
                     deadline: float = 10.0, waiter_thread=None) -> dict:
    """Prove ``waiter_pid`` is blocked on G held by ``holder_pid``.

    Polls the real lock state with ``time.monotonic()``; a deadline expiry is a
    failure, never a retry.  Also asserts the waiter acquired no v24 relation,
    tuple or write lock before G (so it is not waiting on a row lock), and that
    the holder is idle in transaction (the response returned, the transaction
    stayed open).
    """
    deadline_at = time.monotonic() + deadline
    blocker_text = "{}"
    while True:
        with observer.cursor() as cur:
            cur.execute(
                """SELECT pg_blocking_pids(%s)::text,
                          %s = ANY(pg_blocking_pids(%s)),
                          (SELECT count(*) FROM pg_locks WHERE pid=%s
                            AND locktype='advisory' AND classid=%s AND objid=%s
                            AND objsubid=%s AND NOT granted)""",
                (waiter_pid, holder_pid, waiter_pid, waiter_pid,
                 G_CLASSID, G_OBJID, G_OBJSUBID),
            )
            blocker_text, blocks_on_holder, ungranted = cur.fetchone()
        if blocks_on_holder and ungranted >= 1:
            break
        if waiter_thread is not None:
            assert waiter_thread.is_alive(), (
                f"{tag}: waiter finished before blocking on holder {holder_pid} "
                f"(blockers={blocker_text}, ungranted_advisory={ungranted})")
        assert time.monotonic() < deadline_at, (
            f"{tag}: waiter {waiter_pid} did not block on holder {holder_pid} "
            f"(blockers={blocker_text}, ungranted_advisory={ungranted})")

    holder_state = _scalar(
        observer, "SELECT state FROM pg_stat_activity WHERE pid=%s", (holder_pid,))
    assert holder_state == "idle in transaction", (tag, holder_pid, holder_state)
    _waiters_only_on_g(observer, waiter_pid)
    assert _g_grants(observer, waiter_pid) == 0, (tag, waiter_pid, "waiter holds G")
    return {
        "holder_pid": holder_pid,
        "waiter_pid": waiter_pid,
        "blocking_pids": blocker_text,
        "ungranted_advisory": ungranted,
    }


def assert_no_wait_cycle(observer, pids, tag: str) -> dict:
    """Build the wait-for graph for ``pids`` and fail on any cycle.

    Also fails if a blocker is outside the supplied pid set (that would be an
    unaccounted lock) or if a waiter is queued on anything other than G.  The
    graph is read from ``pg_blocking_pids()`` at call time; callers invoke this
    while the wait is live.
    """
    pids = list(pids)
    graph: dict[int, list[int]] = {}
    for pid in pids:
        with observer.cursor() as cur:
            cur.execute("SELECT unnest(pg_blocking_pids(%s))::int", (pid,))
            graph[pid] = [row[0] for row in cur.fetchall()]
        assert set(graph[pid]) <= set(pids), (tag, pid, graph[pid], pids)
        if graph[pid]:
            # Only a *waiter* is checked for the lock-after-G failure.  The
            # holder legitimately owns the row/relation write locks of the
            # transaction it has not committed yet.
            assert _g_waits(observer, pid) >= 1, (tag, pid, "blocker is not G")
            assert _product_locks(observer, pid, granted=True) == 0, (
                tag, pid, "waiter holds a product write lock")
        assert _product_locks(observer, pid, granted=False) == 0, (
            tag, pid, "waiter queued on a non-G lock")

    color: dict[int, int] = {}

    def visit(pid: int, path: list[int]) -> None:
        color[pid] = 1
        path = path + [pid]
        for nxt in graph[pid]:
            if color.get(nxt) == 1:
                raise AssertionError(f"{tag}: wait-for cycle {path + [nxt]}")
            if color.get(nxt, 0) == 0:
                visit(nxt, path)
        color[pid] = 2

    for pid in pids:
        if color.get(pid, 0) == 0:
            visit(pid, [])
    return {"wait_graph": graph, "cycle": False, "advisory_only": True}


# ---------------------------------------------------------------------------
# Held-open writer + non-blocking reader (poll/wait cells)
# ---------------------------------------------------------------------------

def held_open_then_probe(writer_conn, writer_action, reader_conn, reader_action,
                         tag: str, owner, deadline: float = 10.0,
                         observer=None):
    """Run a writer that keeps G, then prove a reader does not block or write.

    ``writer_action(conn)`` must return after ``advance`` without committing, so
    the transaction-scoped G lock stays held.  ``reader_action(conn)`` runs on a
    second real connection while the writer is still uncommitted.  The reader
    transaction is inspected for advisory/tuple/relation write locks, its
    ``pg_blocking_pids()`` must be empty, it must finish before ``deadline``,
    and its committed-effect-free behaviour is proven by a ten-table snapshot
    taken before and after the (committed) read-only transaction.

    Returns ``(writer_response, reader_response, evidence)``; the writer is
    still uncommitted on return and the caller must commit/rollback it.
    """
    before = snapshot(owner)
    writer_response = writer_action(writer_conn)
    writer_pid = writer_conn.get_backend_pid()
    assert _g_grants(writer_conn, writer_pid) == 1, (tag, "writer does not hold G")

    reader_pid = reader_conn.get_backend_pid()
    started = time.monotonic()
    reader_response = reader_action(reader_conn)
    elapsed = time.monotonic() - started
    assert elapsed < deadline, (
        f"{tag}: reader took {elapsed:.3f}s; it must not wait on G")

    blocker_text = _scalar(
        reader_conn, "SELECT pg_blocking_pids(%s)::text", (reader_pid,))
    assert blocker_text == "{}", (tag, reader_pid, blocker_text)
    assert _scalar(
        reader_conn,
        "SELECT count(*) FROM pg_locks WHERE pid=%s AND locktype='advisory'",
        (reader_pid,),
    ) == 0, (tag, "reader acquired an advisory lock")
    assert _scalar(
        reader_conn,
        "SELECT count(*) FROM pg_locks WHERE pid=%s AND locktype='tuple'",
        (reader_pid,),
    ) == 0, (tag, "reader acquired a tuple lock")
    assert _product_locks(reader_conn, reader_pid, granted=True) == 0, (
        tag, "reader acquired a v24 relation/tuple write lock")
    # A backend querying pg_stat_activity for itself always looks "active",
    # and the protocol LOGIN roles cannot see each other's sessions, so the
    # state probe uses the caller's superuser observer when one is supplied.
    state_probe = observer if observer is not None else writer_conn
    reader_state = _scalar(
        state_probe, "SELECT state FROM pg_stat_activity WHERE pid=%s", (reader_pid,))
    assert reader_state == "idle in transaction", (tag, reader_pid, reader_state)

    reader_conn.commit()
    after = snapshot(owner)
    assert after == before, (tag, "reader transaction wrote domain state")
    assert _g_grants(writer_conn, writer_pid) == 1, (tag, "G released too early")

    evidence = {
        "holder_pid": writer_pid,
        "waiter_pid": reader_pid,
        "blocking_pids": blocker_text,
        "ungranted_advisory": 0,
        "reader_elapsed": elapsed,
        "fingerprint": fingerprint(before),
    }
    return writer_response, reader_response, evidence


# ---------------------------------------------------------------------------
# Two specified orders
# ---------------------------------------------------------------------------

def two_orders(db, build_order, tag: str, deadline_seconds: float = 10.0) -> list[dict]:
    """Run two specified orders, each on its own fresh fixture.

    ``build_order(direction)`` is called for ``"first->second"`` and
    ``"second->first"`` and must return ``(first_participant,
    second_participant, context)``.  Participants follow
    ``v24/s4/test_g2b.py:ordered_advance_race`` (``(label, conn, action)``) and
    each call must build a fresh realm/scope/run/install.  The first action
    returns without committing (holding G) and the second must block on G.
    Both orders are mandatory: a missing block raises, it is never sampled or
    skipped.
    """
    outcomes: list[dict] = []
    for direction in ("first->second", "second->first"):
        first, second, context = build_order(direction)
        first_response, second_response, evidence = ordered_advance_race(
            db, first, second, f"{tag}-{direction}-lock",
            deadline_seconds=deadline_seconds,
        )
        outcomes.append({
            "direction": direction,
            "first": first_response,
            "second": second_response,
            "evidence": evidence,
            "context": context,
        })
    return outcomes


# ---------------------------------------------------------------------------
# Evidence lines (§4.6)
# ---------------------------------------------------------------------------

def role_pid(label: str, pid: int) -> str:
    return f"{label}:{pid}"


def format_evidence(tag: str, *, holder: str, waiter: str, blocking_pids: str,
                    ungranted_advisory: int, order: str, diff_text: str,
                    assert_text: str) -> str:
    return (
        f"[{tag}] holder={holder} waiter={waiter} "
        f"blocking_pids={blocking_pids} "
        f"ungranted_advisory={ungranted_advisory} order={order} "
        f"diff={diff_text} assert={assert_text}"
    )


def format_zero(tag: str, snap: dict, assert_text: str) -> str:
    return (
        f"[{tag}-zero] sha={fingerprint(snap)} diff=zero-ten-tables "
        f"assert={assert_text}"
    )


def format_lock(tag: str, wait_graph: dict, winner: str = "G") -> str:
    graph_text = ",".join(
        f"{pid}->{{{','.join(str(item) for item in blockers)}}}"
        for pid, blockers in sorted(wait_graph.items())
    )
    return (
        f"[{tag}-lock] wait_graph={graph_text} cycle=false "
        f"advisory_only=true winner={winner}"
    )
