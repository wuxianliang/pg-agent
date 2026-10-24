"""G6 W2 full gate: two-connection ordering for the complete G6 matrix.

This file is the W2 gate body (§8.1): ``G6-A1``, ``G6-B1``/``B2``/``B3``, the
cancel/steer x activate/retire/dispose cells
``G6-C1``/``C2``/``C3``/``D1``/``E1``/``F1``, the respond/T2 x
activate/retire/dispose cells ``G6-G1``/``G2``/``G3``/``H1``/``H2``/``H3``,
the W2 negatives N1-N9 and the five lock-order audits L1-L5.  The no-argument
run selects all thirty IDs; selecting an unimplemented name remains a hard
error.

Every assertion is driven through the real public wrappers on two real backend
connections.  The first command returns without committing, so its
transaction-scoped ``pg_advisory_xact_lock(24,1)`` (G) stays held; the second
command is proven to queue on G with ``pg_blocking_pids()`` and an ungranted
advisory ``pg_locks`` row.  Nothing is ordered with a sleep and nothing is
sampled: a missing block is a failure.

Run the full gate (all thirty IDs):

    uv run python v24/s7/test_g6.py

The W1 incremental subset remains available, for example:

    uv run python v24/s7/test_g6.py \
        --only g6_a,g6_b,g6_c,g6_d,g6_e,g6_f,g6_g,g6_h,n1
"""
from __future__ import annotations

import argparse
import base64
import json
import queue
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
S1 = ROOT.parent / "s1"
S2 = ROOT.parent / "s2"
S3 = ROOT.parent / "s3"
S4 = ROOT.parent / "s4"
S5 = ROOT.parent / "s5"
S6 = ROOT.parent / "s6"
S8 = ROOT.parent / "s8"
for _path in (S1, S2, S3, S4, S5, S6, S8):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from psycopg2.extras import Json  # noqa: E402

from setup_db import (  # noqa: E402
    _assert_closed_catalog,
    server_helper_scope,
    setup_db,
)
from test_g2b import (  # noqa: E402
    batch_digest,
    cancel,
    claim_effect,
    effect_row,
    hexbyte,
    install_no_network,
    md5_uuid,
    model_rows,
    respond,
    restore_no_network,
    serialized_race,
    settle,
    settle_tool,
    start,
    steer,
    steer_model_id,
)
from test_ddl import DIGEST, insert  # noqa: E402
from test_g2 import pin_barrier_fixture  # noqa: E402
from test_g3a import (  # noqa: E402
    advance,
    claim,
    command,
    one,
    seed_effect,
    seed_fiber,
    seed_install,
    seed_scope,
)
from test_g4 import (  # noqa: E402
    admit_install,
    close_scope,
    dispose,
    inspect_receipt,
    installed_fixture,
    new_child_scope,
    prepare_unknown_fixture,
    scope_closable,
    scope_row,
    settle_release,
)
from test_g7 import (  # noqa: E402
    _spawn_outcome,
    child_counts,
    make_parent,
    next_parent_model,
    settle_spawn,
    spawn_args,
    usage_for,
)
from g6_support import (  # noqa: E402
    assert_diff_exact,
    assert_no_wait_cycle,
    diff,
    format_diff,
    format_evidence,
    format_lock,
    format_zero,
    held_open_then_probe,
    snapshot,
    wait_for_g_block,
)

# ---------------------------------------------------------------------------
# Fixtures (fresh realm/scope/install/fiber per order)
# ---------------------------------------------------------------------------

def new_scope(owner, login, realm):
    creator, root = uuid4(), uuid4()
    principal = one(login, "SELECT v24.principal_id(session_user)")
    login.commit()
    seed_effect(owner, creator)
    seed_scope(owner, root, creator, default_realm=realm, owner_principal=principal)
    owner.commit()
    return root, creator


def add_fiber(owner, admin, scope, realm, *, key, provides=(), requires=(),
              activate=False):
    """An install + fiber inside ``scope``; optionally activated with an episode.

    ``requires``/``provides`` are the capability keys used by ``v24.resolve``.
    A fiber whose install requires another provider gets an *activation* pin;
    a dependency-free fiber activates without one (the G3b-4 fixture shape).
    """
    creator = uuid4()
    seed_effect(owner, creator)
    iid = seed_install(owner, scope_id=scope, creator=creator,
                       requires=[{"realm": realm, "key": item} for item in requires],
                       provides=[{"realm": realm, "key": item} for item in provides])
    fid = seed_fiber(owner, install_id=iid, scope_id=scope, creator=creator)
    owner.commit()
    entry = {"scope": scope, "install": iid, "fiber": fid, "realm": realm,
             "episode": None, "slot": None}
    if activate:
        response = one(admin, "SELECT v24.fiber_control(%s,'on',0,%s)",
                       (fid, f"g6-on-{uuid4()}"))
        admin.commit()
        assert response.get("disposition") == "committed", response
        assert len(response["emitted"]) == 1, response
        entry["episode"] = response["emitted"][0]
        if provides:
            entry["slot"] = one(owner, "SELECT slot_id FROM v24.slots "
                                       "WHERE fiber_id=%s AND key=%s", (fid, provides[0]))
        else:
            entry["slot"] = one(owner, "SELECT slot_id FROM v24.slots WHERE fiber_id=%s", (fid,))
        owner.rollback()
        assert entry["slot"] is not None, entry
    return entry


def fiber_row(owner, fiber):
    value = one(owner, "SELECT to_jsonb(f) FROM v24.fibers f WHERE fiber_id=%s", (fiber,))
    owner.rollback()
    return value


def slot_row(owner, slot):
    value = one(owner, "SELECT to_jsonb(s) FROM v24.slots s WHERE slot_id=%s", (slot,))
    owner.rollback()
    return value


def episode_row(owner, episode):
    value = one(owner, "SELECT to_jsonb(e) FROM v24.episodes e WHERE episode_id=%s",
                (episode,))
    owner.rollback()
    return value


def install_row(owner, install):
    value = one(owner, "SELECT to_jsonb(i) FROM v24.installs i WHERE install_id=%s",
                (install,))
    owner.rollback()
    return value


def pin_rows(owner, predicate, params):
    rows = one(owner, f"SELECT coalesce(jsonb_agg(to_jsonb(p) ORDER BY p.pin_id),'[]'::jsonb) "
                      f"FROM v24.pins p WHERE {predicate}", params)
    owner.rollback()
    return rows


def start_once(login, entry, *, requires, key):
    """One real ``v24.start``; the caller owns commit/rollback of its effect."""
    response, _ = start(login, entry["scope"], entry["fiber"],
                        {"requires": [{"key": item} for item in requires]},
                        {"steps": 3, "tool_calls": 2}, key)
    return response


def start_run(login, entry, *, requires, key):
    response = start_once(login, entry, requires=requires, key=key)
    login.commit()
    return response, None


def run_binding(owner, run_id):
    row = one(owner, "SELECT to_jsonb(r) FROM v24.runs r WHERE run_id=%s", (run_id,))
    owner.rollback()
    return row


def diff_parts(value):
    return {table: (len(rows["added"]), len(rows["changed"]), len(rows["removed"]))
            for table, rows in value.items()}


def added_rows(value, table):
    return value.get(table, {}).get("added", [])


def assert_table_counts(value, expected, label):
    actual = diff_parts(value)
    assert actual == expected, (label, actual, expected, format_diff(value))


def assert_zero_write(value, label):
    assert value == {}, (label, format_diff(value))


# ---------------------------------------------------------------------------
# Two real connections: first returns (G held), second is proven to block
# ---------------------------------------------------------------------------

def first_then_second(db, holder, worker, first_action, second_action, tag,
                      deadline=10.0):
    """Run ``first`` on ``holder`` (no commit), then ``second`` on ``worker``.

    The second command is started only after the first response arrived, so the
    order is fixed by the first command's held G.  The wait is proven through
    ``pg_blocking_pids()``/``pg_locks`` (never a sleep), the wait-for graph is
    checked for cycles, and both transactions are committed after release.
    ``second`` may return a W1 error envelope; that is a response, not a crash.
    """
    observer = db.connect()
    observer.autocommit = True
    result = queue.Queue()
    with worker.cursor() as cur:
        cur.execute("SET statement_timeout='20s'")
    worker.commit()
    first_response = first_action(holder)
    holder_pid = holder.get_backend_pid()
    worker_pid = worker.get_backend_pid()

    def run():
        try:
            response = second_action(worker)
            worker.commit()
            result.put((response, None))
        except BaseException as exc:  # surfaced after the holder is released
            try:
                worker.rollback()
            except Exception:
                pass
            result.put((None, exc))

    thread = threading.Thread(target=run, daemon=True, name=f"{tag}-second")
    thread.start()
    try:
        evidence = wait_for_g_block(observer, holder_pid, worker_pid, tag,
                                    deadline=deadline, waiter_thread=thread)
        graph = assert_no_wait_cycle(observer, [holder_pid, worker_pid], tag)
        holder.commit()
        second_response, error = result.get(timeout=30)
        assert error is None, error
        thread.join(timeout=10)
        assert not thread.is_alive(), f"{tag}: second command never finished"
        return first_response, second_response, evidence, graph
    finally:
        try:
            holder.rollback()
        except Exception:
            pass
        thread.join(timeout=10)
        observer.close()


def lock_line(tag, evidence, graph):
    return format_lock(
        tag, graph["wait_graph"], winner="G")


def evidence_line(tag, *, holder, holder_pid, waiter, waiter_pid, evidence,
                  order, diff_value, verdict):
    return format_evidence(
        tag,
        holder=f"{holder}:{holder_pid}",
        waiter=f"{waiter}:{waiter_pid}",
        blocking_pids=evidence["blocking_pids"],
        ungranted_advisory=evidence["ungranted_advisory"],
        order=order,
        diff_text=format_diff(diff_value),
        assert_text=verdict,
    )


# ---------------------------------------------------------------------------
# G6-A1: start x install/activate (§7 cell 1, §7.2 no-episode)
# ---------------------------------------------------------------------------

def _a1_fixture(owner, service, admin):
    """A dependent fiber B (requires ``base``) plus the provider it needs.

    B activates only after ``on``; its activation pin therefore exists and is
    the row start must not touch.
    """
    realm = f"g6-a1-{uuid4()}"
    scope, _ = new_scope(owner, service, realm)
    base = add_fiber(owner, admin, scope, realm, key="base", provides=("base",),
                     activate=True)
    entry = add_fiber(owner, admin, scope, realm, key="dep", provides=("dep",),
                      requires=("base",))
    return base, entry


def g6_a1(db, owner):
    """Two orders: activate->start (binds the new episode) and start->activate.

    Order 1: ``fiber_control(on)`` returns holding G; the start blocks on G and
    after release commits a run whose only provider pin names B's new episode.
    Order 2: with no episode the start is refused ``provider_unavailable`` W1
    (zero run/pin); only then does ``on`` activate, and the next start commits.
    """
    service, admin = db.connect("service"), db.connect("admin")
    try:
        # ---- order 1: on first, start second (both commit) ----
        base, entry = _a1_fixture(owner, service, admin)
        before = snapshot(owner)
        pre = fiber_row(owner, entry["fiber"])
        assert pre["want_on"] is False and pre["current_episode_id"] is None, pre
        assert one(owner, "SELECT count(*) FROM v24.episodes WHERE fiber_id=%s",
                   (entry["fiber"],)) == 0
        assert one(owner, "SELECT count(*) FROM v24.slots WHERE fiber_id=%s",
                   (entry["fiber"],)) == 0
        assert one(owner, "SELECT count(*) FROM v24.pins p JOIN v24.slots s "
                          "USING(slot_id) WHERE s.fiber_id=%s", (entry["fiber"],)) == 0
        owner.rollback()
        on_key = f"g6-a1-on-{uuid4()}"
        start_key = f"g6-a1-start-{uuid4()}"
        on_response, start_response, evidence, graph = first_then_second(
            db, admin, service,
            lambda conn: one(conn, "SELECT v24.fiber_control(%s,'on',0,%s)",
                             (entry["fiber"], on_key)),
            lambda conn: start_once(conn, entry, requires=("dep",), key=start_key),
            "G6-A1-order1",
        )
        assert on_response.get("disposition") == "committed", on_response
        episode = on_response["emitted"][0]
        entry["slot"] = one(owner, "SELECT slot_id FROM v24.slots "
                                   "WHERE fiber_id=%s AND key='dep'", (entry["fiber"],))
        owner.rollback()
        assert entry["slot"] is not None
        assert start_response.get("disposition") == "committed", start_response
        run_id, model_id = start_response["emitted"]

        after = snapshot(owner)
        value = diff(before, after)
        assert_table_counts(value, {
            "episodes": (1, 0, 0), "slots": (1, 0, 0), "fibers": (0, 1, 0),
            "pins": (2, 0, 0), "runs": (1, 0, 0), "effects": (4, 0, 0),
            "requests": (2, 0, 0), "events": (6, 0, 0),
        }, "G6-A1-order1")
        run = added_rows(value, "runs")[0]
        assert run["run_id"] == run_id and run["status"] == "running", run
        assert run["owner_fiber_id"] == str(entry["fiber"]), run
        assert run["owner_episode_id"] == episode, run
        pins = added_rows(value, "pins")
        activation = [p for p in pins if p["consumer_type"] == "activation"]
        run_pins = [p for p in pins if p["consumer_type"] == "run"]
        assert len(activation) == 1 and activation[0]["consumer_episode_id"] == episode, pins
        assert activation[0]["provider_episode_id"] == str(base["episode"]), activation[0]
        assert activation[0]["slot_id"] == str(base["slot"]), activation[0]
        assert value["pins"]["changed"] == [], value["pins"]["changed"]
        assert len(run_pins) == 1 and run_pins[0]["consumer_run_id"] == run_id, pins
        assert run_pins[0]["provider_episode_id"] == episode, run_pins[0]
        assert run_pins[0]["slot_id"] == str(entry["slot"]), run_pins[0]
        assert added_rows(value, "slots")[0]["released_at"] is None
        assert added_rows(value, "episodes")[0]["state"] == "active"
        start_effects = [e for e in added_rows(value, "effects") if e["run_id"] == run_id]
        assert sorted(e["kind"] for e in start_effects) == ["command_start", "model_call"], start_effects
        assert sorted(e["kind"] for e in added_rows(value, "effects")
                      if e["run_id"] is None) == ["command_fiber_control", "fiber_reconcile"], value["effects"]
        run_events = [e for e in added_rows(value, "events") if e["entity_type"] == "run"]
        assert sorted(e["event_kind"] for e in run_events) == ["model_call_requested",
                                                              "run_started"], run_events
        assert sorted(e["event_kind"] for e in added_rows(value, "events")
                      if e["entity_type"] != "run") == ["episode_opened", "fiber_activated",
                                                        "pin_created", "slot_contributed"], value["events"]
        print(format_evidence(
            "G6-A1", holder=f"admin:{evidence['holder_pid']}",
            waiter=f"service:{evidence['waiter_pid']}",
            blocking_pids=evidence["blocking_pids"],
            ungranted_advisory=evidence["ungranted_advisory"],
            order="activate->start",
            diff_text=format_diff(value),
            assert_text="start blocked until on committed; run pin names activated episode; "
                        "activation pin unchanged by start"))
        print(lock_line("G6-A1", evidence, graph))

        # ---- order 2: start first (W1 refusal), then on, then start ----
        base2, entry2 = _a1_fixture(owner, service, admin)
        before2 = snapshot(owner)
        fail_key = f"g6-a1-refused-{uuid4()}"
        on_key2 = f"g6-a1-on2-{uuid4()}"
        refused, on_second, evidence2, graph2 = first_then_second(
            db, service, admin,
            lambda conn: start_once(conn, entry2, requires=("dep",), key=fail_key),
            lambda conn: one(conn, "SELECT v24.fiber_control(%s,'on',0,%s)",
                             (entry2["fiber"], on_key2)),
            "G6-A1-order2",
        )
        assert refused == {"v": 1, "error": {"code": "provider_unavailable",
                                            "detail": {}}}, refused
        assert on_second.get("disposition") == "committed", on_second
        episode2 = on_second["emitted"][0]
        mid = snapshot(owner)
        mid_value = diff(before2, mid)
        assert added_rows(mid_value, "runs") == [], mid_value.get("runs")
        mid_pins = added_rows(mid_value, "pins")
        assert len(mid_pins) == 1 and mid_pins[0]["consumer_type"] == "activation", mid_pins
        assert mid_pins[0]["provider_episode_id"] == str(base2["episode"]), mid_pins
        assert_table_counts(mid_value, {
            "episodes": (1, 0, 0), "slots": (1, 0, 0), "fibers": (0, 1, 0),
            "pins": (1, 0, 0), "effects": (3, 0, 0), "requests": (2, 0, 0),
            "events": (4, 0, 0),
        }, "G6-A1-order2-before-second-start")
        refused_effects = [e for e in added_rows(mid_value, "effects")
                           if e["request_key"] == fail_key]
        assert len(refused_effects) == 1 and refused_effects[0]["status"] == "failed", refused_effects
        assert refused_effects[0]["kind"] == "command_start", refused_effects[0]
        assert refused_effects[0]["run_id"] is None, refused_effects[0]

        # The activation is now committed; the same start must bind its episode.
        start_key2 = f"g6-a1-start2-{uuid4()}"
        response2, _ = start_run(service, entry2, requires=("dep",), key=start_key2)
        assert response2.get("disposition") == "committed", response2
        run2 = response2["emitted"][0]
        after2 = snapshot(owner)
        final = diff(mid, after2)
        assert_table_counts(final, {
            "runs": (1, 0, 0), "pins": (1, 0, 0), "effects": (2, 0, 0),
            "requests": (1, 0, 0), "events": (2, 0, 0),
        }, "G6-A1-order2-start")
        assert added_rows(final, "pins")[0]["consumer_run_id"] == run2
        assert added_rows(final, "pins")[0]["provider_episode_id"] == episode2
        print(format_evidence(
            "G6-A1b", holder=f"service:{evidence2['holder_pid']}",
            waiter=f"admin:{evidence2['waiter_pid']}",
            blocking_pids=evidence2["blocking_pids"],
            ungranted_advisory=evidence2["ungranted_advisory"],
            order="start-refused->activate->start",
            diff_text=format_diff(diff(before2, after2)),
            assert_text="no episode: provider_unavailable W1 holds G and commits only a "
                        "receipt; activate then start binds the new episode"))
        print(lock_line("G6-A1b", evidence2, graph2))
    finally:
        service.close()
        admin.close()


# ---------------------------------------------------------------------------
# G6-B1/B2/B3: poll/wait are read verbs; they never take G and never write
# ---------------------------------------------------------------------------

def _reader_probe(conn, run_id, generation, epoch, after_revision):
    poll = one(conn, "SELECT v24.poll(%s,%s)", (run_id, after_revision))
    wait = one(conn, "SELECT v24.wait_check(%s,%s,%s,0)", (run_id, generation, epoch))
    assert poll["v"] == 1 and poll["run"]["run_id"] == str(run_id), poll
    assert wait["v"] == 1 and wait["run"]["run_id"] == str(run_id), wait
    assert poll["changed"] is False, poll
    return {"poll_revision": poll["revision"], "wake": wait["wake"]["reason"]}


def _b_fixture(owner, service, admin, *, activate=True):
    realm = f"g6-b-{uuid4()}"
    scope, _ = new_scope(owner, service, realm)
    return add_fiber(owner, admin, scope, realm, key="dep", provides=("dep",),
                     activate=activate)


def _b_with_run(owner, service, admin):
    entry = _b_fixture(owner, service, admin)
    response, _ = start_run(service, entry, requires=("dep",), key=f"g6-b-run-{uuid4()}")
    assert response.get("disposition") == "committed", response
    run_id = response["emitted"][0]
    run = run_binding(owner, run_id)
    return entry, run_id, run


def g6_b1(db, owner):
    """poll/wait x activate: a writer activates B under G; readers do not wait."""
    service, admin = db.connect("service"), db.connect("admin")
    observer = db.connect()
    observer.autocommit = True
    try:
        entry, run_id, run = _b_with_run(owner, service, admin)
        other = add_fiber(owner, admin, entry["scope"], entry["realm"], key="extra",
                          provides=("extra",))
        before = snapshot(owner)
        pre = fiber_row(owner, other["fiber"])
        assert pre["current_episode_id"] is None and pre["want_on"] is False, pre
        on_key = f"g6-b1-on-{uuid4()}"

        def writer(conn):
            return one(conn, "SELECT v24.fiber_control(%s,'on',0,%s)",
                       (other["fiber"], on_key))

        def reader(conn):
            return _reader_probe(conn, run_id, run["registration_generation"],
                                 run["epoch_no"], run["revision"])

        writer_response, reader_response, evidence = held_open_then_probe(
            admin, writer, service, reader, "G6-B1", owner, observer=observer)
        assert writer_response.get("disposition") == "committed", writer_response
        episode = writer_response["emitted"][0]
        assert reader_response["poll_revision"] == run["revision"], (reader_response, run["revision"])
        assert fiber_row(owner, other["fiber"])["current_episode_id"] is None
        admin.commit()
        activated = fiber_row(owner, other["fiber"])
        assert activated["current_episode_id"] == episode, activated
        assert episode_row(owner, episode)["state"] == "active"
        after = snapshot(owner)
        value = diff(before, after)
        assert diff_parts(value).get("runs", (0, 0, 0)) == (0, 0, 0), format_diff(value)
        assert added_rows(value, "pins") == [], value.get("pins")
        assert_table_counts(value, {
            "episodes": (1, 0, 0), "slots": (1, 0, 0), "fibers": (0, 1, 0),
            "effects": (2, 0, 0), "requests": (1, 0, 0), "events": (3, 0, 0),
        }, "G6-B1")
        print(format_evidence(
            "G6-B1", holder=f"admin:{evidence['holder_pid']}",
            waiter=f"service:{evidence['waiter_pid']}",
            blocking_pids=evidence["blocking_pids"],
            ungranted_advisory=evidence["ungranted_advisory"],
            order="activate->poll/wait",
            diff_text=format_diff(value),
            assert_text="reader did not take G; read old committed state; activation "
                        "visible only after commit; zero domain write by reader"))
        print(format_zero("G6-B1", before,
                          "poll+wait_check wrote zero rows in ten tables"))
    finally:
        observer.close()
        service.close()
        admin.close()


def g6_b2(db, owner):
    """poll/wait x deactivate: off returns deferred while a run pin is live."""
    service, admin = db.connect("service"), db.connect("admin")
    observer = db.connect()
    observer.autocommit = True
    try:
        entry, run_id, run = _b_with_run(owner, service, admin)
        before = snapshot(owner)
        off_key = f"g6-b2-off-{uuid4()}"

        def writer(conn):
            return one(conn, "SELECT v24.fiber_control(%s,'off',1,%s)",
                       (entry["fiber"], off_key))

        def reader(conn):
            return _reader_probe(conn, run_id, run["registration_generation"],
                                 run["epoch_no"], run["revision"])

        writer_response, _, evidence = held_open_then_probe(
            admin, writer, service, reader, "G6-B2", owner, observer=observer)
        assert writer_response.get("disposition") == "deferred", writer_response
        assert writer_response["emitted"] == [], writer_response
        assert slot_row(owner, entry["slot"])["withdrawn_at"] is None
        admin.commit()
        slot = slot_row(owner, entry["slot"])
        episode = episode_row(owner, entry["episode"])
        assert slot["withdrawn_at"] is not None and slot["released_at"] is None, slot
        assert episode["state"] == "retiring" and episode["closed_at"] is None, episode
        live_pins = pin_rows(owner, "consumer_run_id=%s AND released_at IS NULL", (run_id,))
        assert len(live_pins) == 1, live_pins
        after = snapshot(owner)
        value = diff(before, after)
        assert_table_counts(value, {"slots": (0, 1, 0), "episodes": (0, 1, 0),
                                    "fibers": (0, 1, 0), "effects": (2, 0, 0),
                                    "requests": (1, 0, 0), "events": (2, 0, 0)}, "G6-B2")
        assert added_rows(value, "pins") == [] and "pins" not in value, value.get("pins")
        assert added_rows(value, "runs") == [], value.get("runs")
        print(format_evidence(
            "G6-B2", holder=f"admin:{evidence['holder_pid']}",
            waiter=f"service:{evidence['waiter_pid']}",
            blocking_pids=evidence["blocking_pids"],
            ungranted_advisory=evidence["ungranted_advisory"],
            order="deactivate->poll/wait",
            diff_text=format_diff(value),
            assert_text="off deferred by run pin; reader observed old state, did not "
                        "close episode or release slot"))
        print(format_zero("G6-B2", before, "poll+wait_check wrote zero rows while off is open"))
    finally:
        observer.close()
        service.close()
        admin.close()


def g6_b3(db, owner):
    """poll/wait x dispose: dispose is deferred by the live run pin."""
    service, admin = db.connect("service"), db.connect("admin")
    observer = db.connect()
    observer.autocommit = True
    try:
        entry, run_id, run = _b_with_run(owner, service, admin)
        before = snapshot(owner)
        dispose_key = f"g6-b3-dispose-{uuid4()}"

        def writer(conn):
            return one(conn, "SELECT v24.dispose(%s,%s)", (entry["install"], dispose_key))

        def reader(conn):
            return _reader_probe(conn, run_id, run["registration_generation"],
                                 run["epoch_no"], run["revision"])

        writer_response, _, evidence = held_open_then_probe(
            admin, writer, service, reader, "G6-B3", owner, observer=observer)
        assert writer_response.get("disposition") == "committed", writer_response
        assert writer_response["emitted"] == [], writer_response
        assert install_row(owner, entry["install"])["state"] == "installed"
        admin.commit()
        install = install_row(owner, entry["install"])
        assert install["state"] == "dispose_pending" and install["disposed_at"] is None, install
        assert fiber_row(owner, entry["fiber"])["disposed_at"] is None
        assert one(owner, "SELECT count(*) FROM v24.effects WHERE kind='host_release' "
                          "AND request->>'install_id'=%s", (str(entry["install"]),)) == 0
        owner.rollback()
        live_pins = pin_rows(owner, "consumer_run_id=%s", (run_id,))
        assert len(live_pins) == 1 and live_pins[0]["released_at"] is None, live_pins
        after = snapshot(owner)
        value = diff(before, after)
        assert_table_counts(value, {"installs": (0, 1, 0), "effects": (1, 0, 0),
                                    "requests": (1, 0, 0), "events": (3, 0, 0),
                                    "episodes": (0, 1, 0), "fibers": (0, 1, 0),
                                    "slots": (0, 1, 0)}, "G6-B3")
        assert added_rows(value, "pins") == [], value.get("pins")
        print(format_evidence(
            "G6-B3", holder=f"admin:{evidence['holder_pid']}",
            waiter=f"service:{evidence['waiter_pid']}",
            blocking_pids=evidence["blocking_pids"],
            ungranted_advisory=evidence["ungranted_advisory"],
            order="dispose->poll/wait",
            diff_text=format_diff(value),
            assert_text="dispose pending while run pin live; reader did not write "
                        "disposed_at or a host_release effect"))
        print(format_zero("G6-B3", before, "poll+wait_check wrote zero rows during dispose"))
    finally:
        observer.close()
        service.close()
        admin.close()


# ---------------------------------------------------------------------------
# G6-N1: start/dispose, both orders (mandatory negative, §7 cell 3)
# ---------------------------------------------------------------------------

def _settle_host_release(service, release_id):
    token = advance(service, release_id, claim())["claim"]
    service.commit()
    settled = advance(service, release_id,
                      {"v": 1, "class": "success", "claim": token, "body": {}})
    service.commit()
    return settled


def g6_n1(db, owner):
    """start/dispose both orders with a real two-connection G block.

    Order a (start first): the committed run pin defers dispose; the install is
    ``dispose_pending`` and no tombstone/host_release exists until the run pin
    drains.  Order b (dispose first): after the drained install is tombstoned,
    the start that queued behind G is refused ``provider_unavailable`` W1 with
    zero run and zero pin.
    """
    service, admin = db.connect("service"), db.connect("admin")
    try:
        entry = _b_fixture(owner, service, admin)
        before = snapshot(owner)
        start_key = f"g6-n1-start-{uuid4()}"
        dispose_key = f"g6-n1-dispose-{uuid4()}"
        start_response, dispose_response, evidence, graph = first_then_second(
            db, service, admin,
            lambda conn: start_once(conn, entry, requires=("dep",), key=start_key),
            lambda conn: one(conn, "SELECT v24.dispose(%s,%s)",
                             (entry["install"], dispose_key)),
            "G6-N1a",
        )
        assert start_response.get("disposition") == "committed", start_response
        run_id = start_response["emitted"][0]
        assert dispose_response.get("disposition") == "committed", dispose_response
        assert dispose_response["emitted"] == [], dispose_response
        staged = snapshot(owner)
        value = diff(before, staged)
        install = install_row(owner, entry["install"])
        assert install["state"] == "dispose_pending" and install["disposed_at"] is None, install
        assert fiber_row(owner, entry["fiber"])["disposed_at"] is None
        assert one(owner, "SELECT count(*) FROM v24.effects WHERE kind='host_release' "
                          "AND request->>'install_id'=%s", (str(entry["install"]),)) == 0
        owner.rollback()
        live = pin_rows(owner, "consumer_run_id=%s AND released_at IS NULL", (run_id,))
        assert len(live) == 1, live
        assert added_rows(value, "runs") != [] and any(
            p["consumer_type"] == "run" for p in added_rows(value, "pins")), format_diff(value)
        print(format_evidence(
            "G6-N1a", holder=f"service:{evidence['holder_pid']}",
            waiter=f"admin:{evidence['waiter_pid']}",
            blocking_pids=evidence["blocking_pids"],
            ungranted_advisory=evidence["ungranted_advisory"],
            order="start->dispose",
            diff_text=format_diff(value),
            assert_text="run pin blocks dispose; dispose_pending, disposed_at NULL, "
                        "no host_release"))
        print(lock_line("G6-N1a", evidence, graph))

        # Sequential drain: cancel releases the run pin, off releases the slot,
        # a new dispose emits host_release, settlement tombstones the install.
        cancelled, _ = cancel(service, run_id, 1, f"g6-n1-cancel-{uuid4()}")
        service.commit()
        assert cancelled.get("disposition") == "committed", cancelled
        off = one(admin, "SELECT v24.fiber_control(%s,'off',1,%s)",
                  (entry["fiber"], f"g6-n1-off-{uuid4()}"))
        admin.commit()
        assert off.get("disposition") == "committed", off
        slot = slot_row(owner, entry["slot"])
        assert slot["released_at"] is not None, slot
        final_dispose = one(admin, "SELECT v24.dispose(%s,%s)",
                            (entry["install"], f"g6-n1-dispose2-{uuid4()}"))
        admin.commit()
        assert final_dispose.get("disposition") == "committed", final_dispose
        assert len(final_dispose["emitted"]) == 1, final_dispose
        settled = _settle_host_release(service, final_dispose["emitted"][0])
        assert settled.get("disposition") == "committed", settled
        assert fiber_row(owner, entry["fiber"])["disposed_at"] is not None
        assert install_row(owner, entry["install"])["state"] == "disposed"
        assert pin_rows(owner, """consumer_run_id=%s AND released_at IS NULL""",
                        (run_id,)) == []

        # ---- order b: fresh drained install; dispose first, start queued ----
        entry2 = _b_fixture(owner, service, admin)
        off2 = one(admin, "SELECT v24.fiber_control(%s,'off',1,%s)",
                   (entry2["fiber"], f"g6-n1-off2-{uuid4()}"))
        admin.commit()
        assert off2.get("disposition") == "committed", off2
        before2 = snapshot(owner)
        dispose_key2 = f"g6-n1-dispose3-{uuid4()}"
        refused_key = f"g6-n1-refused-{uuid4()}"
        dispose_first, refused, evidence2, graph2 = first_then_second(
            db, admin, service,
            lambda conn: one(conn, "SELECT v24.dispose(%s,%s)",
                             (entry2["install"], dispose_key2)),
            lambda conn: start_run(conn, entry2, requires=("dep",), key=refused_key)[0],
            "G6-N1b",
        )
        assert dispose_first.get("disposition") == "committed", dispose_first
        assert len(dispose_first["emitted"]) == 1, dispose_first
        assert refused == {"v": 1, "error": {"code": "provider_unavailable",
                                            "detail": {}}}, refused
        staged2 = snapshot(owner)
        value2 = diff(before2, staged2)
        assert added_rows(value2, "runs") == [], value2.get("runs")
        assert added_rows(value2, "pins") == [], value2.get("pins")
        assert fiber_row(owner, entry2["fiber"])["disposed_at"] is not None
        refused_effect = [e for e in added_rows(value2, "effects")
                          if e["request_key"] == refused_key]
        assert len(refused_effect) == 1 and refused_effect[0]["status"] == "failed", refused_effect
        print(format_evidence(
            "G6-N1b", holder=f"admin:{evidence2['holder_pid']}",
            waiter=f"service:{evidence2['waiter_pid']}",
            blocking_pids=evidence2["blocking_pids"],
            ungranted_advisory=evidence2["ungranted_advisory"],
            order="dispose->start",
            diff_text=format_diff(value2),
            assert_text="tombstone first; queued start provider_unavailable W1, zero "
                        "run/pin"))
        print(lock_line("G6-N1b", evidence2, graph2))
        settled2 = _settle_host_release(service, dispose_first["emitted"][0])
        assert settled2.get("disposition") == "committed", settled2
        assert install_row(owner, entry2["install"])["state"] == "disposed"
    finally:
        service.close()
        admin.close()


# ---------------------------------------------------------------------------
# G6-N2..N5: respond/steer negatives behind a held G
# ---------------------------------------------------------------------------

def _n2_order(db, owner, service, admin, *, reverse, tag=None, emit=True):
    """respond x cancel: the G winner fixes whether the interaction is consumed.

    Order a: respond holds G, consumes the interaction and publishes one ready
    successor; the blocked cancel then archives that successor without touching
    the original receipt.  Order b: cancel holds G and seals the run first; the
    blocked respond is ``already_terminal`` W1 and no successor exists.

    ``tag``/``emit`` exist for the L5 lock audit, which reuses this exact body
    under its own tag without printing the N2 result line.
    """
    if tag is None:
        tag = "G6-N2b" if reverse else "G6-N2a"
    fixture = _waiting_fixture(owner, service, admin, tag, dependent=False)
    run_id, model1 = fixture["run"], fixture["model"]
    assert fixture["interaction"] is not None, fixture
    assert _one_pin(owner, run_id, tag)["released_at"] is None
    initial = run_binding(owner, run_id)
    assert initial["status"] == "waiting", initial
    original = effect_row(owner, model1)
    assert original["status"] == "succeeded", original
    original_outcome = original["outcome"]
    before = snapshot(owner)
    answer = {"answer": "red", "structured": {"n": 3}}
    second_conn = db.connect("service")
    try:
        respond_action = lambda conn: _respond_action(conn, fixture, answer, tag)
        # A respond advances the run generation, so the trailing cancel CASes on
        # the post-respond generation; the cancel-first order still sees gen 1.
        cancel_generation = 1 if reverse else 2
        cancel_action = lambda conn: cancel(conn, run_id, cancel_generation,
                                            f"{tag}-cancel-{uuid4()}")[0]
        if reverse:
            first, second, evidence, graph = first_then_second(
                db, second_conn, service, cancel_action, respond_action, tag)
            cancel_response, respond_response = first, second
            order = "cancel->respond"
        else:
            first, second, evidence, graph = first_then_second(
                db, service, second_conn, respond_action, cancel_action, tag)
            respond_response, cancel_response = first, second
            order = "respond->cancel"
    finally:
        second_conn.close()

    assert cancel_response.get("disposition") == "committed", cancel_response
    assert cancel_response["emitted"] == [], cancel_response
    run = run_binding(owner, run_id)
    assert run["status"] == "cancelled", run
    assert run["close_intent"]["kind"] == "cancel", run
    assert run["result"] is None, run
    assert run["ended_at"] is not None, run
    assert run["interaction"] is None, run
    assert _one_pin(owner, run_id, tag)["released_at"] is not None
    after = snapshot(owner)
    value = diff(before, after)
    if reverse:
        assert respond_response == {"v": 1, "error": {"code": "already_terminal",
                                                      "detail": {}}}, respond_response
        assert _model_count(owner, run_id) == 1
        assert added_rows(value, "runs") == [], value.get("runs")
        assert added_rows(value, "pins") == [], value.get("pins")
        failed = one(owner, "SELECT to_jsonb(e) FROM v24.effects e "
                            "WHERE e.kind='command_respond' AND e.status='failed' "
                            "AND e.request_key LIKE %s", (f"{tag}-respond-%",))
        owner.rollback()
        assert failed is not None, "respond W1 receipt missing"
        assert failed["run_id"] is None, failed
        verdict = ("cancel holds G on the waiting run; the blocked respond is "
                   "already_terminal W1 with zero new model and no domain run/pin "
                   "write; the interaction receipt is sealed by the cancel")
    else:
        assert respond_response.get("disposition") == "committed", respond_response
        assert len(respond_response["emitted"]) == 1, respond_response
        successor = respond_response["emitted"][0]
        successor_row = effect_row(owner, successor)
        assert successor_row["kind"] == "model_call", successor_row
        assert successor_row["status"] == "cancelled", successor_row
        assert successor_row["outcome"] is None, successor_row
        assert successor_row["settled_at"] is not None, successor_row
        assert successor_row["generation"] == 2, successor_row
        assert effect_row(owner, model1)["outcome"] == original_outcome
        assert _model_count(owner, run_id) == 2
        verdict = ("respond holds G, consumes the interaction and publishes one "
                   "ready generation-2 model; the blocked cancel archives that "
                   "successor with outcome NULL and does not rewrite the original "
                   "receipt; exactly two model_calls, no second successor")
    if emit:
        _print_order(tag, evidence, graph, "service", "service", order, value, verdict)
    return evidence, graph, "service", "service", order, value


def g6_n2(db, owner):
    """respond/cancel both orders, each decided by the G winner."""
    service, admin = db.connect("service"), db.connect("admin")
    try:
        for reverse in (False, True):
            _n2_order(db, owner, service, admin, reverse=reverse)
    finally:
        service.close()
        admin.close()


def g6_n3(db, owner):
    """terminal steer: the final T2 holds G; the queued steer is W1.

    The run completes inside the first (uncommitted) transaction, so G is still
    held when the steer queues.  After release the steer is refused
    ``already_terminal``: the only added effect is its failed receipt and the
    completed run remains byte-identical, including result/``ended_at``/cost.
    """
    service, admin = db.connect("service"), db.connect("admin")
    try:
        entry = _fresh_self_fixture(owner, service, admin, "G6-N3")
        started, _ = start(service, entry["scope"], entry["fiber"],
                           {"requires": [{"key": "dep"}]}, BUDGET,
                           f"g6-n3-start-{uuid4()}")
        service.commit()
        assert started.get("disposition") == "committed", started
        run_id, model_id = started["emitted"]
        token = claim_effect(service, model_id)
        before = snapshot(owner)
        receipt = {"v": 1, "class": "success", "claim": token,
                   "body": {"kind": "model_call",
                            "result": {"text": "done", "final": {"text": "done"},
                                       "usage": {"tokens": 40, "wall_ms": 5}}}}
        t2_action = lambda conn: advance(conn, model_id, receipt)
        steer_action = lambda conn: steer(conn, run_id, 1, "too late",
                                          f"g6-n3-steer-{uuid4()}")[0]
        t2, late_steer, evidence, graph = first_then_second(
            db, service, admin, t2_action, steer_action, "G6-N3")
        assert t2.get("disposition") == "committed", t2
        assert t2["emitted"] == [], t2
        assert late_steer == {"v": 1, "error": {"code": "already_terminal",
                                                 "detail": {}}}, late_steer
        after = snapshot(owner)
        value = diff(before, after)
        completed = run_binding(owner, run_id)
        assert completed["status"] == "completed", completed
        assert completed["result"]["close_reason"] == "final", completed
        assert completed["result"]["final_text"] == "done", completed
        assert completed["ended_at"] is not None, completed
        assert completed["pending_steer"] is None, completed
        assert completed["close_intent"] == {"kind": "final"}, completed
        assert completed["remaining_tokens"] == 4960, completed
        assert _model_count(owner, run_id) == 1
        assert added_rows(value, "runs") == [], value.get("runs")
        assert added_rows(value, "pins") == [], value.get("pins")
        added_effects = added_rows(value, "effects")
        assert len(added_effects) == 1, added_effects
        assert added_effects[0]["kind"] == "command_steer", added_effects
        assert added_effects[0]["status"] == "failed", added_effects
        assert added_effects[0]["run_id"] is None, added_effects
        assert len(added_rows(value, "requests")) == 1, value.get("requests")
        # A second terminal steer on the committed run is byte-identical.
        again, _ = steer(service, run_id, 1, "still too late",
                         f"g6-n3-steer2-{uuid4()}")
        assert again == late_steer, again
        assert run_binding(owner, run_id) == completed
        _print_order(
            "G6-N3", evidence, graph, "service", "admin",
            "settle(final)->steer", value,
            "final T2 holds G and completes the run; the queued steer is "
            "already_terminal W1, its failed receipt is the only added effect, "
            "and result/ended_at/cost stay byte-identical")
    finally:
        service.close()
        admin.close()


def g6_n4(db, owner):
    """steer/withdraw: the off-first body of E1, reported under G6-N4.

    The withdrawn slot keeps the claimed tool pin alive; the active steer still
    follows the old pin and writes ``pending_steer``, the claimed model makes no
    second model_call before settlement, settlement yields exactly one
    cause='steer' successor, and the slot is not released early.
    """
    service, admin = db.connect("service"), db.connect("admin")
    try:
        evidence, graph, holder_role, waiter_role, order, value = _e1_order(
            db, owner, service, admin, reverse=True)
        _print_order(
            "G6-N4", evidence, graph, holder_role, waiter_role, order, value,
            "off withdraws the slot first and holds G; the active steer keeps "
            "the old generation, writes pending_steer and creates no second "
            "model_call before settlement; settlement produces exactly one "
            "cause='steer' successor and the slot releases only after the pin")
    finally:
        service.close()
        admin.close()


def _n5_fixture(owner, service, admin, tag):
    """An activated provider B plus an activated owner A with no activation pin.

    The run (not A's install) requires ``base``, so only the run pin references
    B's slot and B can close once that pin is silent.
    """
    realm = f"{tag}-{uuid4()}"
    scope, _ = new_scope(owner, service, realm)
    base = add_fiber(owner, admin, scope, realm, key="base", provides=("base",),
                     activate=True)
    entry = add_fiber(owner, admin, scope, realm, key="dep", provides=("dep",),
                      activate=True)
    return base, entry


def _n5_order(db, owner, service, admin, *, reverse):
    """cancel x retire with a late T2 after both orders.

    Both orders keep the run pin behind the claimed model and withdraw the slot.
    The late T2 then records only fact/cost, creates no old-generation
    successor, releases the pin, and only then does a second off close the
    episode.  Cancel never unloads the owner fiber on its own.
    """
    tag = "G6-N5b" if reverse else "G6-N5a"
    base, entry = _n5_fixture(owner, service, admin, tag)
    started, _ = start(service, entry["scope"], entry["fiber"],
                       {"requires": [{"key": "base"}]}, BUDGET,
                       f"{tag}-start-{uuid4()}")
    service.commit()
    assert started.get("disposition") == "committed", started
    run_id, model_id = started["emitted"]
    token = claim_effect(service, model_id)
    assert run_binding(owner, run_id)["status"] == "running"
    pin = _one_pin(owner, run_id, tag)
    assert pin["released_at"] is None, pin
    assert pin["provider_episode_id"] == str(base["episode"]), pin
    # A claimed model does not reference the run pin; the host-held tool child
    # does, so cancel must keep the pin until that child goes silent.
    held = run_binding(owner, run_id)
    tool_id = md5_uuid(f"{model_id}:tool_call:0")
    with owner.cursor() as cur:
        insert(cur, "effects", effect_id=tool_id, parent_effect_id=model_id,
               ordinal=0, requester_id=uuid4(), run_id=run_id,
               pin_id=pin["pin_id"], epoch_no=held["epoch_no"],
               generation=held["driving_generation"], kind="tool_call",
               status="ready", attempt_no=1, fence=1,
               request=Json({"v": 1, "run_id": run_id,
                             "epoch_no": held["epoch_no"],
                             "generation": held["driving_generation"],
                             "ordinal": 0, "key": pin["key"], "args": {},
                             "descriptor_digest": hexbyte(pin["descriptor_digest"]),
                             "batch_digest": batch_digest([tool_id])}),
               request_digest=DIGEST, replay_policy="no_replay")
    owner.commit()
    tool_token = claim_effect(service, tool_id)
    before = snapshot(owner)
    cancel_action = lambda conn: cancel(conn, run_id, 1,
                                        f"{tag}-cancel-{uuid4()}")[0]
    off_action = lambda conn: one(
        conn, "SELECT v24.fiber_control(%s,'off',1,%s)",
        (base["fiber"], f"{tag}-off1-{uuid4()}"))
    if reverse:
        first, second, evidence, graph = first_then_second(
            db, admin, service, off_action, cancel_action, tag)
        off_response, cancel_response = first, second
        holder_role, waiter_role, order = "admin", "service", "off->cancel"
    else:
        first, second, evidence, graph = first_then_second(
            db, service, admin, cancel_action, off_action, tag)
        cancel_response, off_response = first, second
        holder_role, waiter_role, order = "service", "admin", "cancel->off"
    assert cancel_response.get("disposition") == "committed", cancel_response
    assert cancel_response["emitted"] == [], cancel_response
    assert off_response.get("disposition") == "deferred", off_response
    assert off_response["emitted"] == [], off_response

    # Both orders: cancel sealed the run, but the claimed model retains the pin
    # and the owner fiber is neither unloaded nor closed.
    staged_run = run_binding(owner, run_id)
    assert staged_run["status"] == "cancelled", staged_run
    assert staged_run["close_intent"]["kind"] == "cancel", staged_run
    assert staged_run["result"] is None, staged_run
    assert staged_run["pending_steer"] is None, staged_run
    assert _one_pin(owner, run_id, tag)["released_at"] is None
    staged_slot = slot_row(owner, base["slot"])
    assert staged_slot["withdrawn_at"] is not None, staged_slot
    assert staged_slot["released_at"] is None, staged_slot
    assert episode_row(owner, base["episode"])["state"] == "retiring"
    assert fiber_row(owner, base["fiber"])["disposed_at"] is None
    owner_fiber = fiber_row(owner, entry["fiber"])
    assert owner_fiber["disposed_at"] is None, owner_fiber
    assert owner_fiber["current_episode_id"] == str(entry["episode"]), owner_fiber
    assert owner_fiber["want_on"] is True, owner_fiber
    assert _model_count(owner, run_id) == 1

    # The late T2 lands after both commands: fact/cost only, no successor.
    late, _ = settle(service, model_id, token, "success",
                     {"text": "late", "usage": {"tokens": 40, "wall_ms": 5}})
    assert late.get("disposition") == "committed", late
    assert late["emitted"] == [], late
    late_run = run_binding(owner, run_id)
    assert late_run["status"] == "cancelled", late_run
    assert late_run["result"] is None, late_run
    assert late_run["close_intent"] == staged_run["close_intent"], late_run
    assert late_run["remaining_tokens"] == 4960, late_run
    late_model = effect_row(owner, model_id)
    assert late_model["status"] == "succeeded", late_model
    assert _model_count(owner, run_id) == 1
    assert one(owner, "SELECT count(*) FROM v24.effects WHERE parent_effect_id=%s",
               (model_id,)) == 1  # the host-held tool child
    assert _one_pin(owner, run_id, tag)["released_at"] is None
    held_settled, _ = settle_tool(service, tool_id, tool_token, "success",
                                  {"status": "ok", "output": {},
                                   "usage": {"wall_ms": 3}})
    assert held_settled.get("disposition") == "committed", held_settled
    assert held_settled["emitted"] == [], held_settled
    assert _one_pin(owner, run_id, tag)["released_at"] is not None

    # Only after the pin went silent does a second off close the episode.
    off2 = _fiber_off(admin, base["fiber"], 2, f"{tag}-off2-{uuid4()}")
    assert off2.get("disposition") == "committed", off2
    assert off2["emitted"] == [], off2
    assert slot_row(owner, base["slot"])["released_at"] is not None
    assert episode_row(owner, base["episode"])["state"] == "closed"
    assert fiber_row(owner, base["fiber"])["current_episode_id"] is None
    owner_fiber = fiber_row(owner, entry["fiber"])
    assert owner_fiber["disposed_at"] is None, owner_fiber
    assert owner_fiber["current_episode_id"] == str(entry["episode"]), owner_fiber
    after = snapshot(owner)
    return evidence, graph, holder_role, waiter_role, order, diff(before, after)


def g6_n5(db, owner):
    """cancel/retire plus late T2 in both orders."""
    service, admin = db.connect("service"), db.connect("admin")
    try:
        for reverse in (False, True):
            evidence, graph, holder_role, waiter_role, order, value = _n5_order(
                db, owner, service, admin, reverse=reverse)
            tag = "G6-N5b" if reverse else "G6-N5a"
            _print_order(
                tag, evidence, graph, holder_role, waiter_role, order, value,
                "the run pin survives the cancel behind the claimed model and "
                "the slot is only withdrawn; the late T2 records fact/cost with "
                "zero old-generation successor, releases the pin, and a second "
                "off then releases the slot and closes the episode")
    finally:
        service.close()
        admin.close()


# ---------------------------------------------------------------------------
# G6-N6..N9: close vs install, cross-scope child, T2/cancel, spawn key
# ---------------------------------------------------------------------------

def _close_command(conn, scope_id, key):
    """Raw close request (no commit): the caller owns held G / the commit."""
    payload = {"action": "close", "parent_scope_id": str(scope_id)}
    effect_id, outcome = command(conn, key, "command_scope_control", payload)
    return advance(conn, effect_id, outcome)


def _manifest_bytes(identity, provides=()):
    return json.dumps({
        "identity": identity, "version": "1", "requires": [],
        "provides": list(provides), "adapter_digest": "\\x",
    }).encode()


def _admit_command(conn, scope_id, identity, key, provides=(), owner_fiber=None):
    """Raw install admission (no commit); W1 errors are responses, not raises."""
    payload = {
        "scope_id": str(scope_id),
        "owner_fiber_id": str(owner_fiber) if owner_fiber is not None else None,
        "manifest_bytes": base64.b64encode(
            _manifest_bytes(identity, provides)).decode(),
        "artifact_digest": "\\x",
    }
    effect_id, outcome = command(conn, key, "command_install", payload)
    return advance(conn, effect_id, outcome)


def _settle_raw(conn, effect_id, token, class_name, body):
    response = advance(conn, effect_id, {"v": 1, "class": class_name,
                                         "claim": token, "body": body})
    conn.commit()
    return response


def _install_count_in_scope(owner, scope_id):
    value = one(owner, "SELECT count(*) FROM v24.installs WHERE scope_id=%s",
                (scope_id,))
    owner.rollback()
    return value


def _last_close_phase(owner, scope_id):
    value = one(
        owner,
        """SELECT payload->>'phase' FROM v24.events
            WHERE entity_type='scope' AND entity_id=%s
              AND event_kind='scope_close_phase'
            ORDER BY seq DESC LIMIT 1""",
        (scope_id,),
    )
    owner.rollback()
    return value


def _n6a(db, owner):
    service, admin = db.connect("service"), db.connect("admin")
    tag = "G6-N6a"
    try:
        scope, install, _hp = installed_fixture(
            owner, admin, service, f"g6-n6a-{uuid4()}")
        assert install_row(owner, install)["state"] == "installed"
        before = snapshot(owner)
        first, second, evidence, graph = first_then_second(
            db, admin, service,
            lambda conn: _close_command(conn, scope, f"{tag}-close-{uuid4()}"),
            lambda conn: one(conn, "SELECT v24.dispose(%s,%s)",
                             (install, f"{tag}-dispose-{uuid4()}")),
            tag)
        assert first.get("disposition") == "committed", first
        assert first["emitted"] == [], first
        assert second.get("disposition") == "committed", second
        assert len(second["emitted"]) == 1, second
        release = second["emitted"][0]
        assert effect_row(owner, release)["kind"] == "host_release"
        staged = install_row(owner, install)
        assert staged["state"] == "dispose_pending", staged
        assert staged["disposed_at"] is None, staged
        row = scope_row(owner, scope)
        assert row["close_requested_at"] is not None, row
        assert row["closed_at"] is None, row
        closable = scope_closable(owner, scope)
        assert closable["ok"] is False, closable
        count_before = _install_count_in_scope(owner, scope)
        refused = _admit_command(
            admin, scope, f"{tag}-late-{uuid4()}", f"{tag}-admit-{uuid4()}",
            provides=[{"realm": f"g6-n6a-{uuid4()}", "key": "k"}])
        admin.commit()
        assert refused == {"v": 1, "error": {"code": "scope_closed",
                                             "detail": {}}}, refused
        assert _install_count_in_scope(owner, scope) == count_before
        # No premature closed: the install tombstone gates the finalize phase.
        settle_release(service, release)
        disposed = install_row(owner, install)
        assert disposed["state"] == "disposed", disposed
        assert disposed["disposed_at"] is not None, disposed
        closed = False
        for index in range(1, 10):
            response = close_scope(admin, scope,
                                   f"{tag}-finish-{index}-{uuid4()}")
            if scope_row(owner, scope)["closed_at"] is not None:
                assert response.get("disposition") == "committed", response
                closed = True
                break
        assert closed
        assert scope_closable(owner, scope)["ok"] is True
        after = snapshot(owner)
        _print_order(
            tag, evidence, graph, "admin", "service", "close->dispose",
            diff(before, after),
            "close commits only the request phase and keeps G; dispose queues "
            "on G and leaves the install dispose_pending with closed_at NULL "
            "and closable.ok false; a fresh admission is scope_closed W1 with "
            "zero install rows; only the settled release plus the later close "
            "phases reach closed_at")
    finally:
        service.close()
        admin.close()


def _n6b(db, owner):
    service, admin = db.connect("service"), db.connect("admin")
    tag = "G6-N6b"
    try:
        scope, install, _hp = prepare_unknown_fixture(
            owner, admin, service, f"g6-n6b-{uuid4()}")
        assert install_row(owner, install)["state"] == "prepare_unknown"
        before = snapshot(owner)
        for phase, expected in (("request", "committed"), ("drain", "deferred"),
                                ("retire", "deferred")):
            response = close_scope(admin, scope, f"{tag}-{phase}-{uuid4()}")
            assert response.get("disposition") == expected, (phase, response)
        captured = {}

        def cascade_first(conn):
            response = _close_command(conn, scope, f"{tag}-cascade-{uuid4()}")
            captured["response"] = response
            assert response.get("disposition") == "deferred", response
            assert len(response.get("emitted") or []) == 1, response
            captured["inspect"] = response["emitted"][0]
            return response

        first, second, evidence, graph = first_then_second(
            db, admin, service, cascade_first,
            lambda conn: claim_effect(conn, captured["inspect"]), tag)
        inspect_id = captured["inspect"]
        assert first.get("disposition") == "deferred", first
        assert isinstance(second, dict) and second.get("fence") == 1, second
        inspect = effect_row(owner, inspect_id)
        assert inspect["kind"] == "inspect_resource", inspect
        assert inspect["status"] == "claimed", inspect
        assert install_row(owner, install)["state"] == "prepare_unknown"
        phases = []
        for index in range(1, 7):
            response = close_scope(admin, scope,
                                   f"{tag}-stuck-{index}-{uuid4()}")
            assert response.get("disposition") == "deferred", response
            row = scope_row(owner, scope)
            assert row["close_requested_at"] is not None, row
            assert row["closed_at"] is None, row
            assert scope_closable(owner, scope)["ok"] is False
            stuck = install_row(owner, install)
            assert stuck["state"] == "prepare_unknown", stuck
            assert stuck["disposed_at"] is None, stuck
            phases.append(_last_close_phase(owner, scope))
        assert all(phase in ("cascade", "barrier") for phase in phases), phases
        assert one(owner, "SELECT count(*) FROM v24.effects "
                          "WHERE kind='inspect_resource' "
                          "AND request->>'install_id'=%s",
                   (str(install),)) == 1
        owner.rollback()
        settled = _settle_raw(service, inspect_id, second, "success",
                              inspect_receipt(owner, inspect_id, "absent"))
        assert settled.get("disposition") == "committed", settled
        failed = install_row(owner, install)
        assert failed["state"] == "prepare_failed", failed
        assert failed["disposed_at"] is None, failed
        closed = False
        for index in range(1, 10):
            response = close_scope(admin, scope,
                                   f"{tag}-finish-{index}-{uuid4()}")
            if scope_row(owner, scope)["closed_at"] is not None:
                assert response.get("disposition") == "committed", response
                closed = True
                break
        assert closed
        disposed = install_row(owner, install)
        assert disposed["state"] == "disposed", disposed
        assert disposed["disposed_at"] is not None, disposed
        # absent means prepare_failed: the product tombstones directly and
        # emits no host_release (G4-J2); assert that exact shape, not a release.
        assert one(owner, "SELECT count(*) FROM v24.effects "
                          "WHERE kind='host_release' AND request->>'install_id'=%s",
                   (str(install),)) == 0
        owner.rollback()
        assert scope_closable(owner, scope)["ok"] is True
        after = snapshot(owner)
        _print_order(
            tag, evidence, graph, "admin", "service", "close->inspect-claim",
            diff(before, after),
            "with the inspect claimed but unsettled the scope stays closing: "
            "repeated closes keep closed_at NULL and closable.ok false; the "
            "absent receipt moves prepare_unknown to prepare_failed and a "
            "final close tombstones it directly (zero host_release) before "
            "closed_at is written")
    finally:
        service.close()
        admin.close()


def g6_n6(db, owner):
    """scope close vs an installed and a prepare_unknown install."""
    _n6a(db, owner)
    _n6b(db, owner)


def _n7_fixture(owner, admin, service, tag):
    """Owner scope P with an activated owner fiber F in an active episode."""
    realm = f"{tag}-{uuid4()}"
    scope, install, _hp = installed_fixture(owner, admin, service, realm)
    fiber = one(owner, "SELECT fiber_id FROM v24.fibers WHERE install_id=%s",
                (install,))
    owner.rollback()
    on = one(admin, "SELECT v24.fiber_control(%s,'on',0,%s)",
             (fiber, f"{tag}-on-{uuid4()}"))
    admin.commit()
    assert on.get("disposition") == "committed", on
    episode = on["emitted"][0]
    child_scope = new_child_scope(admin, scope, realm,
                                  f"{tag}-childscope-{uuid4()}")
    assert fiber_row(owner, fiber)["current_episode_id"] == str(episode)
    return {"scope": scope, "install": install, "fiber": fiber,
            "episode": episode, "child_scope": child_scope, "realm": realm}


def _n7_add_child(owner, admin, fixture, tag):
    response = admit_install(
        admin, fixture["child_scope"], f"{tag}-child-{uuid4()}",
        f"{tag}-child-install-{uuid4()}",
        provides=[{"realm": fixture["realm"], "key": "child"}],
        owner_fiber=fixture["fiber"])
    child, hp = response["emitted"]
    assert install_row(owner, child)["state"] == "preparing"
    return child, hp


def _n7a(db, owner):
    service, admin = db.connect("service"), db.connect("admin")
    tag = "G6-N7a"
    try:
        fixture = _n7_fixture(owner, admin, service, f"g6-n7a-{uuid4()}")
        child, hp = _n7_add_child(owner, admin, fixture, tag)
        before = snapshot(owner)
        first, second, evidence, graph = first_then_second(
            db, admin, service,
            lambda conn: one(conn, "SELECT v24.fiber_control(%s,'off',1,%s)",
                             (fixture["fiber"], f"{tag}-off1-{uuid4()}")),
            lambda conn: one(conn, "SELECT v24.dispose(%s,%s)",
                             (fixture["install"], f"{tag}-dispose1-{uuid4()}")),
            tag)
        assert first.get("disposition") == "deferred", first
        assert first["emitted"] == [], first
        assert second.get("disposition") == "committed", second
        assert second["emitted"] == [], second
        owner_row = install_row(owner, fixture["install"])
        assert owner_row["state"] == "dispose_pending", owner_row
        assert owner_row["disposed_at"] is None, owner_row
        episode = episode_row(owner, fixture["episode"])
        assert episode["state"] != "closed", episode
        assert episode["closed_at"] is None, episode
        child_row = install_row(owner, child)
        assert child_row["state"] == "preparing", child_row
        assert child_row["disposed_at"] is None, child_row
        assert one(owner, "SELECT count(*) FROM v24.installs "
                          "WHERE owner_fiber_id=%s AND state <> 'disposed'",
                   (fixture["fiber"],)) == 1
        owner.rollback()
        token = claim_effect(service, hp)
        settled = _settle_raw(service, hp, token, "success", {})
        assert settled.get("disposition") == "committed", settled
        assert install_row(owner, child)["state"] == "installed"
        child_dispose = dispose(admin, child, f"{tag}-child-dispose-{uuid4()}")
        assert child_dispose.get("disposition") == "committed", child_dispose
        assert len(child_dispose["emitted"]) == 1, child_dispose
        settle_release(service, child_dispose["emitted"][0])
        assert install_row(owner, child)["state"] == "disposed"
        off2 = _fiber_off(admin, fixture["fiber"], 2, f"{tag}-off2-{uuid4()}")
        assert off2.get("disposition") == "committed", off2
        assert off2["emitted"] == [], off2
        assert episode_row(owner, fixture["episode"])["state"] == "closed"
        owner_dispose = dispose(admin, fixture["install"],
                                f"{tag}-dispose2-{uuid4()}")
        assert owner_dispose.get("disposition") == "committed", owner_dispose
        assert len(owner_dispose["emitted"]) == 1, owner_dispose
        settle_release(service, owner_dispose["emitted"][0])
        done = install_row(owner, fixture["install"])
        assert done["state"] == "disposed", done
        assert done["disposed_at"] is not None, done
        after = snapshot(owner)
        _print_order(
            tag, evidence, graph, "admin", "service", "off->dispose",
            diff(before, after),
            "the cross-scope child keeps the owner open: off is deferred with "
            "zero successors and dispose only stamps dispose_pending while the "
            "child is live; after the child is disposed a fresh off closes the "
            "episode and dispose tombstones the owner")
    finally:
        service.close()
        admin.close()


def _n7b_variant(db, owner, reverse):
    """One owner-first variant; returns (evidence, graph, diff, description)."""
    service, admin = db.connect("service"), db.connect("admin")
    worker = db.connect("admin")
    tag = "G6-N7b"
    try:
        fixture = _n7_fixture(owner, admin, service,
                              f"g6-n7b-{'d' if reverse else 'o'}-{uuid4()}")
        before = snapshot(owner)
        count_before = _install_count_in_scope(owner, fixture["child_scope"])

        def admit_action(conn):
            return _admit_command(
                conn, fixture["child_scope"], f"{tag}-late-{uuid4()}",
                f"{tag}-admit-{uuid4()}",
                provides=[{"realm": fixture["realm"], "key": "child"}],
                owner_fiber=fixture["fiber"])

        if reverse:
            first, second, evidence, graph = first_then_second(
                db, admin, worker,
                lambda conn: one(conn, "SELECT v24.dispose(%s,%s)",
                                 (fixture["install"],
                                  f"{tag}-dispose-{uuid4()}")),
                admit_action, f"{tag}-dispose-first")
            order = "dispose->admit"
            assert first.get("disposition") == "committed", first
            assert first["emitted"] == [], first
            owner_row = install_row(owner, fixture["install"])
            assert owner_row["state"] == "dispose_pending", owner_row
            assert owner_row["disposed_at"] is None, owner_row
            assert fiber_row(owner, fixture["fiber"])["want_on"] is False
            description = ("dispose-first leaves the owner dispose_pending and "
                           "its fiber want_on=false, so the child admission is "
                           "owner_closing W1 with zero child")
        else:
            first, second, evidence, graph = first_then_second(
                db, admin, worker,
                lambda conn: one(conn, "SELECT v24.fiber_control(%s,'off',1,%s)",
                                 (fixture["fiber"], f"{tag}-off-{uuid4()}")),
                admit_action, f"{tag}-off-first")
            order = "off->admit"
            assert first.get("disposition") == "committed", first
            assert first["emitted"] == [], first
            fiber = fiber_row(owner, fixture["fiber"])
            assert fiber["want_on"] is False, fiber
            assert fiber["current_episode_id"] is None, fiber
            assert episode_row(owner, fixture["episode"])["state"] == "closed"
            description = ("off-first closes the owner episode and clears "
                           "want_on, so the child admission is owner_closing W1 "
                           "with zero child")
        assert second == {"v": 1, "error": {"code": "owner_closing",
                                            "detail": {}}}, second
        assert _install_count_in_scope(owner, fixture["child_scope"]) == count_before
        after = snapshot(owner)
        return evidence, graph, diff(before, after), order, description
    finally:
        worker.close()
        service.close()
        admin.close()


def g6_n7(db, owner):
    """owner retire/dispose vs a cross-scope child admission, both orders."""
    _n7a(db, owner)
    first = _n7b_variant(db, owner, reverse=False)
    second = _n7b_variant(db, owner, reverse=True)
    ev1, graph1, diff1, order1, desc1 = first
    ev2, graph2, diff2, order2, desc2 = second
    merged = dict(ev1)
    merged["blocking_pids"] = f"{ev1['blocking_pids']}|{ev2['blocking_pids']}"
    value = diff1
    print(evidence_line(
        "G6-N7b", holder="admin", holder_pid=ev1["holder_pid"],
        waiter="service", waiter_pid=ev1["waiter_pid"], evidence=merged,
        order=f"{order1} / {order2}", diff_value=value,
        verdict=f"{desc1}; {desc2}"))
    print(lock_line("G6-N7b", merged,
                    {"wait_graph": {**graph1["wait_graph"],
                                    **graph2["wait_graph"]}}))


def _n8_fixture(owner, service, admin, tag, *, held_tool=False):
    """A claimed T2, optionally with a claimed tool that owns the run pin.

    A model_call never binds ``effects.pin_id`` (the product rejects a pinned
    model at settlement), so the in-flight-IO pin holder in this fixture is the
    claimed tool_child, exactly the G2b-O order-2 shape.  That is what keeps
    the run pin live across a cancel; the late T2 records fact/cost but the pin
    releases only when the held tool goes silent.
    """
    fixture = _claimed_model_fixture(owner, service, admin, tag)
    fixture["tool"] = None
    fixture["tool_token"] = None
    if held_tool:
        pin = fixture["pin"]
        run = fixture["run_row"]
        tool_id = md5_uuid(f"{fixture['model']}:tool_call:0")
        with owner.cursor() as cur:
            insert(cur, "effects", effect_id=tool_id,
                   parent_effect_id=fixture["model"], ordinal=0,
                   requester_id=uuid4(), run_id=fixture["run"],
                   pin_id=pin["pin_id"], epoch_no=run["epoch_no"],
                   generation=run["driving_generation"], kind="tool_call",
                   status="ready", attempt_no=0, fence=0,
                   request=Json({"v": 1, "run_id": fixture["run"],
                                 "epoch_no": run["epoch_no"],
                                 "generation": run["driving_generation"],
                                 "ordinal": 0, "key": pin["key"], "args": {},
                                 "descriptor_digest": hexbyte(pin["descriptor_digest"]),
                                 "batch_digest": batch_digest([tool_id])}),
                   request_digest=DIGEST, replay_policy="no_replay")
        owner.commit()
        fixture["tool_token"] = claim_effect(service, tool_id)
        fixture["tool"] = tool_id
        tool_row = effect_row(owner, tool_id)
        assert tool_row["status"] == "claimed", tool_row
        assert str(tool_row["pin_id"]) == str(pin["pin_id"]), tool_row
    return fixture


def _n8a(db, owner):
    service, admin = db.connect("service"), db.connect("admin")
    tag = "G6-N8a"
    try:
        fixture = _n8_fixture(owner, service, admin, f"g6-n8a-{uuid4()}")
        before = snapshot(owner)
        receipt = _t2_receipt(fixture["token"])
        first, second, evidence, graph = first_then_second(
            db, service, admin,
            lambda conn: advance(conn, fixture["model"], receipt),
            lambda conn: cancel(conn, fixture["run"], 1,
                                f"{tag}-cancel-{uuid4()}")[0], tag)
        assert first.get("disposition") == "committed", first
        assert second.get("disposition") == "committed", second
        assert second["emitted"] == [], second
        continuation = md5_uuid(f"{fixture['model']}:continuation")
        assert first["emitted"] == [continuation], first
        model = effect_row(owner, fixture["model"])
        assert model["status"] == "succeeded", model
        assert model["outcome"] == receipt, model
        successor = effect_row(owner, continuation)
        assert successor["status"] == "cancelled", successor
        assert successor["outcome"] is None, successor
        assert successor["settled_at"] is not None, successor
        run = run_binding(owner, fixture["run"])
        assert run["status"] == "cancelled", run
        assert run["close_intent"]["kind"] == "cancel", run
        assert run["result"] is None, run
        assert run["turn_no"] == 1, run
        assert run["remaining_tokens"] == 4960, run
        assert _one_pin(owner, fixture["run"], tag)["released_at"] is not None
        assert one(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                          "AND kind='model_call'", (fixture["run"],)) == 2
        owner.rollback()
        after = snapshot(owner)
        _print_order(
            tag, evidence, graph, "service", "admin", "settle->cancel",
            diff(before, after),
            "T2 records the frozen receipt/cost and one ready successor before "
            "G is released; cancel then archives that successor without "
            "overwriting the receipt, and no second successor is created")
    finally:
        service.close()
        admin.close()


def _n8b(db, owner):
    service, admin = db.connect("service"), db.connect("admin")
    tag = "G6-N8b"
    try:
        fixture = _n8_fixture(owner, service, admin, f"g6-n8b-{uuid4()}",
                              held_tool=True)
        before = snapshot(owner)
        receipt = _t2_receipt(fixture["token"])
        first, second, evidence, graph = first_then_second(
            db, admin, service,
            lambda conn: cancel(conn, fixture["run"], 1,
                                f"{tag}-cancel-{uuid4()}")[0],
            lambda conn: advance(conn, fixture["model"], receipt), tag)
        assert first.get("disposition") == "committed", first
        assert first["emitted"] == [], first
        assert second.get("disposition") == "committed", second
        assert second["emitted"] == [], second
        model = effect_row(owner, fixture["model"])
        assert model["status"] == "succeeded", model
        assert model["outcome"] == receipt, model
        run = run_binding(owner, fixture["run"])
        assert run["status"] == "cancelled", run
        assert run["result"] is None, run
        continuation = md5_uuid(f"{fixture['model']}:continuation")
        assert one(owner, "SELECT count(*) FROM v24.effects WHERE effect_id=%s",
                   (continuation,)) == 0
        owner.rollback()
        assert one(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                          "AND kind='model_call'", (fixture["run"],)) == 1
        owner.rollback()
        # The claimed tool_child owns the pin, so the pin stays live across the
        # cancel and the late T2 (the product's "retain until IO silence").
        held = _one_pin(owner, fixture["run"], tag)
        assert held["released_at"] is None, held
        late_tool, _outcome = settle_tool(
            service, fixture["tool"], fixture["tool_token"], "success",
            {"status": "ok", "output": {}, "usage": {"wall_ms": 3}})
        assert late_tool.get("disposition") == "committed", late_tool
        assert late_tool["emitted"] == [], late_tool
        released = _one_pin(owner, fixture["run"], tag)
        assert released["released_at"] is not None, released
        after = snapshot(owner)
        _print_order(
            tag, evidence, graph, "admin", "service", "cancel->settle",
            diff(before, after),
            "cancel first seals the run; the claimed model's late T2 is "
            "committed but records fact/cost only with emitted=[] and zero "
            "successor, and the run pin is retained across both commands by "
            "the in-flight tool (released only when that tool goes silent), "
            "with no second successor")
    finally:
        service.close()
        admin.close()


def g6_n8(db, owner):
    """T2/cancel key intersection in both orders."""
    _n8a(db, owner)
    _n8b(db, owner)


def g6_n9(db, owner):
    """Same spawn key, different canonical input bytes, two service connections."""
    service_a, service_b = db.connect("service"), db.connect("service")
    tag = "G6-N9"
    try:
        parent = make_parent(
            owner, service_a, "g6-n9",
            {"steps": 6, "tool_calls": 3, "tokens": 5000, "wall_ms": 600000})
        args_a = spawn_args(
            parent["scope_id"], "child-g6-n9",
            {"steps": 1, "tokens": 300, "tool_calls": 1, "wall_ms": 1000},
            input_value={"messages": [{"role": "user", "content": "bytes a"}]})
        args_b = spawn_args(
            parent["scope_id"], "child-g6-n9",
            {"steps": 1, "tokens": 300, "tool_calls": 1, "wall_ms": 1000},
            input_value={"messages": [{"role": "user", "content": "bytes b"}]})
        before = run_binding(owner, parent["run_id"])
        before_race = snapshot(owner)
        winner, winner_response, results, evidence = serialized_race(
            db,
            [
                ("a", service_a,
                 lambda conn: advance(conn, parent["model_id"],
                                      _spawn_outcome(parent, args_a))),
                ("b", service_b,
                 lambda conn: advance(conn, parent["model_id"],
                                      _spawn_outcome(parent, args_b))),
            ],
            f"{tag}-lock")
        assert winner_response.get("disposition") == "committed", winner_response
        loser = "b" if winner == "a" else "a"
        assert results[loser]["error"]["code"] == "receipt_conflict", results[loser]
        counts = child_counts(owner, parent["run_id"])
        assert counts == {"children": 1, "effects": 1, "spawned": 1,
                          "started": 1}, counts
        grant = args_a["budget"]["tokens"]
        reserve = parent["model"]["request"]["reserve"]["tokens"]
        usage = usage_for(parent)["tokens"]
        after_race = run_binding(owner, parent["run_id"])
        assert after_race["remaining_tokens"] == (
            before["remaining_tokens"] + reserve - usage - grant), (
                "the losing concurrent spawn wrote a quota delta")
        race_diff = diff(before_race, snapshot(owner))
        # The 24th code on a later parent outcome carrying the loser's bytes.
        conflict_parent = next_parent_model(owner, service_a, parent)
        other = args_b if winner == "a" else args_a
        before_conflict = snapshot(owner)
        response = settle_spawn(service_a, conflict_parent, other,
                                usage=usage_for(conflict_parent))
        assert response == {"v": 1, "error": {"code": "spawn_key_conflict",
                                              "detail": {}}}, response
        assert snapshot(owner) == before_conflict, "spawn_key_conflict wrote rows"
        assert effect_row(owner, conflict_parent["model_id"])["status"] == "claimed"
        assert child_counts(owner, parent["run_id"]) == counts
        print(format_evidence(
            tag,
            holder=f"{winner}:{evidence['winner_pid']}",
            waiter=f"{loser}:{evidence['blocked_pid']}",
            blocking_pids=evidence["blockers"],
            ungranted_advisory=evidence["ungranted_advisory"],
            order=f"{winner}->{loser}",
            diff_text=format_diff(race_diff),
            assert_text=(
                "two service connections on the same parent model effect and "
                "spawn key with different canonical bytes: exactly one child, "
                "the loser is receipt_conflict with no quota write, and a later "
                "outcome carrying the losing bytes is spawn_key_conflict W0 "
                "with a byte-equal ten-table snapshot and the conflict model "
                "effect still claimed")))
    finally:
        service_a.close()
        service_b.close()


# ---------------------------------------------------------------------------
# G6-C1..C3, D1, E1, F1: cancel/steer x activate/retire/dispose
# ---------------------------------------------------------------------------

def _fresh_self_fixture(owner, service, admin, tag):
    """One activated fiber B that provides and consumes its own ``dep`` slot."""
    realm = f"{tag}-{uuid4()}"
    scope, _ = new_scope(owner, service, realm)
    return add_fiber(owner, admin, scope, realm, key="dep", provides=("dep",),
                     activate=True)


def _fresh_dep_fixture(owner, service, admin, tag):
    """An activated provider B plus an activated dependent fiber A -> B."""
    realm = f"{tag}-{uuid4()}"
    scope, _ = new_scope(owner, service, realm)
    base = add_fiber(owner, admin, scope, realm, key="base", provides=("base",),
                     activate=True)
    entry = add_fiber(owner, admin, scope, realm, key="dep", provides=("dep",),
                      requires=("base",), activate=True)
    return base, entry


def _run_pins_of(owner, run_id):
    return pin_rows(owner, "consumer_run_id=%s", (run_id,))


def _one_pin(owner, run_id, label):
    rows = _run_pins_of(owner, run_id)
    assert len(rows) == 1, (label, "expected exactly one run pin", rows)
    return rows[0]


def _activation_pin(owner, consumer_episode):
    rows = pin_rows(owner, "consumer_type='activation' AND consumer_episode_id=%s",
                    (consumer_episode,))
    assert len(rows) == 1, ("activation pin", consumer_episode, rows)
    return rows[0]


def _model_count(owner, run_id):
    return one(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                      "AND kind='model_call'", (run_id,))


def _start_and_claim_tool(owner, service, entry, requires, tag):
    """start -> one model -> tool batch -> claim the tool; returns its id/token."""
    response, _ = start_run(service, entry, requires=requires,
                            key=f"{tag}-start-{uuid4()}")
    assert response.get("disposition") == "committed", response
    run_id, model_id = response["emitted"]
    token = claim_effect(service, model_id)
    settled, _ = settle(service, model_id, token, "success",
                        {"text": "run a tool",
                         "tool_calls": [{"key": requires[0], "args": {"n": 0}}],
                         "usage": {"tokens": 40, "wall_ms": 5}})
    assert settled.get("disposition") == "committed", settled
    tool_id = md5_uuid(f"{model_id}:tool_call:0")
    assert settled["emitted"] == [tool_id], settled
    tool_token = claim_effect(service, tool_id)
    assert tool_token is not None
    return run_id, model_id, tool_id, tool_token


def _settle_tool_success(service, tool_id, token):
    settled, _ = settle_tool(service, tool_id, token, "success",
                             {"status": "ok", "output": {"n": 0},
                              "usage": {"wall_ms": 3}})
    assert settled.get("disposition") == "committed", settled
    return settled


def _settle_final(service, effect_id, text="done"):
    token = claim_effect(service, effect_id)
    settled, _ = settle(service, effect_id, token, "success",
                        {"text": text, "final": {"text": text}})
    assert settled.get("disposition") == "committed", settled
    assert settled["emitted"] == [], settled
    return settled


def _fiber_off(admin, fiber_id, seq, key):
    response = one(admin, "SELECT v24.fiber_control(%s,'off',%s,%s)",
                   (fiber_id, seq, key))
    admin.commit()
    return response


def _print_order(tag, evidence, graph, holder_role, waiter_role, order,
                 value, verdict):
    print(evidence_line(
        tag, holder=holder_role, holder_pid=evidence["holder_pid"],
        waiter=waiter_role, waiter_pid=evidence["waiter_pid"],
        evidence=evidence, order=order, diff_value=value, verdict=verdict))
    print(lock_line(tag, evidence, graph))


def _c1_order(db, owner, service, admin, *, reverse):
    tag = "G6-C1-order2" if reverse else "G6-C1"
    base, entry = _fresh_dep_fixture(owner, service, admin, tag)
    started, _ = start_run(service, entry, requires=("base",),
                           key=f"{tag}-run1-{uuid4()}")
    assert started.get("disposition") == "committed", started
    run1 = started["emitted"][0]
    activation = _activation_pin(owner, entry["episode"])
    pin1 = _one_pin(owner, run1, tag)
    base_slot = slot_row(owner, base["slot"])
    run1_row = run_binding(owner, run1)
    assert run1_row["status"] == "running", run1_row
    assert pin1["released_at"] is None, pin1
    assert pin1["provider_episode_id"] == str(base["episode"]), pin1
    assert activation["provider_episode_id"] == str(base["episode"]), activation
    assert base_slot["withdrawn_at"] is None and base_slot["released_at"] is None, base_slot
    entry_fiber = fiber_row(owner, entry["fiber"])
    assert entry_fiber["want_on"] is True, entry_fiber
    assert entry_fiber["current_episode_id"] == str(entry["episode"]), entry_fiber
    before = snapshot(owner)

    cancel_action = lambda conn: cancel(conn, run1, 1, f"{tag}-cancel-{uuid4()}")[0]
    start_action = lambda conn: start_once(conn, entry, requires=("base",),
                                           key=f"{tag}-run2-{uuid4()}")
    if reverse:
        first, second, evidence, graph = first_then_second(
            db, admin, service, start_action, cancel_action, tag)
        start_response, cancel_response = first, second
        holder_role, waiter_role, order = "admin", "service", "start->cancel"
    else:
        first, second, evidence, graph = first_then_second(
            db, service, admin, cancel_action, start_action, tag)
        cancel_response, start_response = first, second
        holder_role, waiter_role, order = "service", "admin", "cancel->start"
    assert cancel_response.get("disposition") == "committed", cancel_response
    assert cancel_response["emitted"] == [], cancel_response
    assert start_response.get("disposition") == "committed", start_response
    assert len(start_response["emitted"]) == 2, start_response
    run2 = start_response["emitted"][0]
    assert run2 != run1

    after = snapshot(owner)
    value = diff(before, after)
    assert_diff_exact(value, {
        "effects": (3, 1, 0), "events": (3, 0, 0), "pins": (1, 1, 0),
        "requests": (2, 0, 0), "runs": (1, 1, 0),
    }, tag)
    cancelled = run_binding(owner, run1)
    assert cancelled["status"] == "cancelled" and cancelled["ended_at"] is not None, cancelled
    assert run_binding(owner, run2)["status"] == "running"
    assert _activation_pin(owner, entry["episode"]) == activation
    assert _one_pin(owner, run1, tag)["released_at"] is not None
    pin2 = _one_pin(owner, run2, tag)
    assert pin2["released_at"] is None, pin2
    assert pin2["provider_episode_id"] == str(base["episode"]), pin2
    assert pin2["slot_id"] == str(base["slot"]), pin2
    assert slot_row(owner, base["slot"]) == base_slot
    assert slot_row(owner, entry["slot"])["released_at"] is None
    assert fiber_row(owner, entry["fiber"])["current_episode_id"] == str(entry["episode"])
    return evidence, graph, holder_role, waiter_role, order, value


def g6_c1(db, owner):
    """cancel x activate: both orders keep the activation pin and B slot intact.

    Order 1 cancels run1 holding G; the queued start(run2) commits after release
    and binds the same activated B episode.  Order 2 starts run2 first and the
    queued cancel only seals run1.  run2 is the only net new run.
    """
    service, admin = db.connect("service"), db.connect("admin")
    try:
        for reverse in (False, True):
            evidence, graph, holder_role, waiter_role, order, value = _c1_order(
                db, owner, service, admin, reverse=reverse)
            tag = "G6-C1-order2" if reverse else "G6-C1"
            _print_order(
                tag, evidence, graph, holder_role, waiter_role, order, value,
                "cancel seals only run1 and releases its run pin; the queued "
                "start creates run2 on the same activated B episode; activation "
                "pin and B slot byte-identical")
    finally:
        service.close()
        admin.close()


def _c2_order(db, owner, service, admin, *, reverse, tag=None):
    """cancel x retire with a claimed tool retaining the run pin.

    ``tag`` exists for the L2 lock audit, which reuses this exact body under its
    own tag and prints the lock evidence outside this helper.
    """
    if tag is None:
        tag = "G6-C2-order2" if reverse else "G6-C2"
    entry = _fresh_self_fixture(owner, service, admin, tag)
    run_id, _model_id, tool_id, token = _start_and_claim_tool(
        owner, service, entry, ("dep",), tag)
    pin = _one_pin(owner, run_id, tag)
    tool = effect_row(owner, tool_id)
    assert run_binding(owner, run_id)["status"] == "running"
    assert tool["status"] == "claimed" and tool["pin_id"] == pin["pin_id"], tool
    assert pin["released_at"] is None, pin
    pre_slot = slot_row(owner, entry["slot"])
    assert pre_slot["withdrawn_at"] is None and pre_slot["released_at"] is None, pre_slot
    assert episode_row(owner, entry["episode"])["state"] == "active"
    assert fiber_row(owner, entry["fiber"])["want_on"] is True
    before = snapshot(owner)

    cancel_action = lambda conn: cancel(conn, run_id, 1, f"{tag}-cancel-{uuid4()}")[0]
    off_action = lambda conn: one(
        conn, "SELECT v24.fiber_control(%s,'off',1,%s)",
        (entry["fiber"], f"{tag}-off1-{uuid4()}"))
    if reverse:
        first, second, evidence, graph = first_then_second(
            db, admin, service, off_action, cancel_action, tag)
        off_response, cancel_response = first, second
        holder_role, waiter_role, order = "admin", "service", "off->cancel"
    else:
        first, second, evidence, graph = first_then_second(
            db, service, admin, cancel_action, off_action, tag)
        cancel_response, off_response = first, second
        holder_role, waiter_role, order = "service", "admin", "cancel->off"
    assert cancel_response.get("disposition") == "committed", cancel_response
    assert off_response.get("disposition") == "deferred", off_response
    assert off_response["emitted"] == [], off_response

    # The claimed tool still references the pin: it survives the cancel and the
    # retire stage stops before releasing the contribution.
    cancelled = run_binding(owner, run_id)
    assert cancelled["status"] == "cancelled", cancelled
    staged_tool = effect_row(owner, tool_id)
    assert staged_tool["status"] == "claimed", staged_tool
    assert staged_tool["cancel_requested"] is True, staged_tool
    assert _one_pin(owner, run_id, tag)["released_at"] is None
    staged_slot = slot_row(owner, entry["slot"])
    assert staged_slot["withdrawn_at"] is not None, staged_slot
    assert staged_slot["released_at"] is None, staged_slot
    assert episode_row(owner, entry["episode"])["state"] == "retiring"
    assert fiber_row(owner, entry["fiber"])["want_on"] is False

    # Settling the last claimed/unknown effect releases the retained pin.
    settled_tool = _settle_tool_success(service, tool_id, token)
    assert settled_tool.get("disposition") == "committed", settled_tool
    assert settled_tool["emitted"] == [], settled_tool
    released_pin = _one_pin(owner, run_id, tag)
    assert released_pin["released_at"] is not None, released_pin
    assert released_pin["released_by_effect"] == tool_id, released_pin
    assert effect_row(owner, tool_id)["status"] == "succeeded"
    assert run_binding(owner, run_id)["status"] == "cancelled"

    off2 = _fiber_off(admin, entry["fiber"], 2, f"{tag}-off2-{uuid4()}")
    assert off2.get("disposition") == "committed", off2
    assert off2["emitted"] == [], off2
    final_slot = slot_row(owner, entry["slot"])
    assert final_slot["released_at"] is not None, final_slot
    assert episode_row(owner, entry["episode"])["state"] == "closed"
    assert fiber_row(owner, entry["fiber"])["current_episode_id"] is None
    released_after_pin = one(
        owner, "SELECT s.released_at >= p.released_at FROM v24.slots s "
               "JOIN v24.pins p ON p.pin_id=%s WHERE s.slot_id=%s",
        (pin["pin_id"], entry["slot"]))
    assert released_after_pin is True, (pin, entry["slot"])

    after = snapshot(owner)
    value = diff(before, after)
    assert_diff_exact(value, {
        "effects": (4, 1, 0), "episodes": (0, 1, 0), "events": (6, 0, 0),
        "fibers": (0, 1, 0), "pins": (0, 1, 0), "requests": (3, 0, 0),
        "runs": (0, 1, 0), "slots": (0, 1, 0),
    }, tag)
    return evidence, graph, holder_role, waiter_role, order, value


def g6_c2(db, owner):
    """cancel x retire: the claimed tool pin holds the contribution in place.

    Order 1 cancels first (G held) and retires second (deferred); order 2
    retires first (deferred) and cancels second.  In both orders the pin is
    retained until the claimed tool settles, then the second off releases the
    slot/episode only after the pin release.
    """
    service, admin = db.connect("service"), db.connect("admin")
    try:
        for reverse in (False, True):
            evidence, graph, holder_role, waiter_role, order, value = _c2_order(
                db, owner, service, admin, reverse=reverse)
            tag = "G6-C2-order2" if reverse else "G6-C2"
            _print_order(
                tag, evidence, graph, holder_role, waiter_role, order, value,
                "cancel seals the run but the claimed-tool pin survives; the "
                "retire stage only withdraws; pin release precedes slot release "
                "and episode close")
    finally:
        service.close()
        admin.close()


def _c3_order(db, owner, service, admin, *, reverse):
    tag = "G6-C3-order2" if reverse else "G6-C3"
    entry = _fresh_self_fixture(owner, service, admin, tag)
    started, _ = start_run(service, entry, requires=("dep",),
                           key=f"{tag}-run-{uuid4()}")
    assert started.get("disposition") == "committed", started
    run_id = started["emitted"][0]
    pin = _one_pin(owner, run_id, tag)
    assert pin["released_at"] is None, pin
    assert run_binding(owner, run_id)["status"] == "running"
    assert install_row(owner, entry["install"])["state"] == "installed"
    assert fiber_row(owner, entry["fiber"])["want_on"] is True
    assert fiber_row(owner, entry["fiber"])["disposed_at"] is None
    pre_slot = slot_row(owner, entry["slot"])
    assert pre_slot["withdrawn_at"] is None and pre_slot["released_at"] is None, pre_slot
    assert episode_row(owner, entry["episode"])["state"] == "active"
    before = snapshot(owner)

    cancel_action = lambda conn: cancel(conn, run_id, 1, f"{tag}-cancel-{uuid4()}")[0]
    dispose_action = lambda conn: one(
        conn, "SELECT v24.dispose(%s,%s)",
        (entry["install"], f"{tag}-dispose1-{uuid4()}"))
    if reverse:
        first, second, evidence, graph = first_then_second(
            db, admin, service, dispose_action, cancel_action, tag)
        dispose_response, cancel_response = first, second
        holder_role, waiter_role, order = "admin", "service", "dispose->cancel"
    else:
        first, second, evidence, graph = first_then_second(
            db, service, admin, cancel_action, dispose_action, tag)
        cancel_response, dispose_response = first, second
        holder_role, waiter_role, order = "service", "admin", "cancel->dispose"
    assert cancel_response.get("disposition") == "committed", cancel_response
    assert dispose_response.get("disposition") == "committed", dispose_response
    assert dispose_response["emitted"] == [], dispose_response

    # Every order: dispose only marks the install pending; the tombstone waits
    # for cancel -> off -> release -> settle.
    assert run_binding(owner, run_id)["status"] == "cancelled"
    released_pin = _one_pin(owner, run_id, tag)
    assert released_pin["released_at"] is not None, released_pin
    staged_install = install_row(owner, entry["install"])
    assert staged_install["state"] == "dispose_pending", staged_install
    assert staged_install["disposed_at"] is None, staged_install
    assert fiber_row(owner, entry["fiber"])["disposed_at"] is None
    staged_slot = slot_row(owner, entry["slot"])
    assert staged_slot["withdrawn_at"] is not None, staged_slot
    assert staged_slot["released_at"] is None, staged_slot
    assert episode_row(owner, entry["episode"])["state"] == "retiring"

    off = _fiber_off(admin, entry["fiber"], 1, f"{tag}-off-{uuid4()}")
    assert off.get("disposition") == "committed", off
    assert off["emitted"] == [], off
    closed_slot = slot_row(owner, entry["slot"])
    assert closed_slot["released_at"] is not None, closed_slot
    assert episode_row(owner, entry["episode"])["state"] == "closed"
    assert fiber_row(owner, entry["fiber"])["current_episode_id"] is None

    disposed = one(admin, "SELECT v24.dispose(%s,%s)",
                   (entry["install"], f"{tag}-dispose2-{uuid4()}"))
    admin.commit()
    assert disposed.get("disposition") == "committed", disposed
    assert len(disposed["emitted"]) == 1, disposed
    release_id = disposed["emitted"][0]
    assert effect_row(owner, release_id)["kind"] == "host_release"
    assert install_row(owner, entry["install"])["state"] == "dispose_pending"
    settled = _settle_host_release(service, release_id)
    assert settled.get("disposition") == "committed", settled
    final_install = install_row(owner, entry["install"])
    assert final_install["state"] == "disposed", final_install
    assert final_install["disposed_at"] is not None, final_install
    assert fiber_row(owner, entry["fiber"])["disposed_at"] is not None
    assert _run_pins_of(owner, run_id) == [] or all(
        row["released_at"] is not None for row in _run_pins_of(owner, run_id))
    disposed_after_pin = one(
        owner, "SELECT i.disposed_at >= p.released_at FROM v24.installs i "
               "JOIN v24.pins p ON p.pin_id=%s WHERE i.install_id=%s",
        (pin["pin_id"], entry["install"]))
    assert disposed_after_pin is True, (pin["pin_id"], entry["install"])

    after = snapshot(owner)
    value = diff(before, after)
    assert_diff_exact(value, {
        "effects": (6, 1, 0), "episodes": (0, 1, 0), "events": (9, 0, 0),
        "fibers": (0, 1, 0), "installs": (0, 1, 0), "pins": (0, 1, 0),
        "requests": (4, 0, 0), "runs": (0, 1, 0), "slots": (0, 1, 0),
    }, tag)
    return evidence, graph, holder_role, waiter_role, order, value


def g6_c3(db, owner):
    """cancel x dispose: dispose never tombstones before the run pin is clear.

    Order 1 cancels first and disposes second; order 2 disposes first (pending,
    no tombstone) and cancels second.  Both orders then drain with off, re-issue
    dispose under a new key (host_release) and settle to disposed.
    """
    service, admin = db.connect("service"), db.connect("admin")
    try:
        for reverse in (False, True):
            evidence, graph, holder_role, waiter_role, order, value = _c3_order(
                db, owner, service, admin, reverse=reverse)
            tag = "G6-C3-order2" if reverse else "G6-C3"
            _print_order(
                tag, evidence, graph, holder_role, waiter_role, order, value,
                "dispose never tombstones in the racing advance; cancel "
                "releases the run pin, off releases the slot, the new-key "
                "dispose emits host_release and disposed_at is not earlier "
                "than pin release")
    finally:
        service.close()
        admin.close()


def _d1_order(db, owner, service, admin, *, reverse):
    tag = "G6-D1-order2" if reverse else "G6-D1"
    base, entry = _fresh_dep_fixture(owner, service, admin, tag)
    run1, _model1, _tool_id, _token = _start_and_claim_tool(
        owner, service, entry, ("base",), tag)
    activation = _activation_pin(owner, entry["episode"])
    pin1 = _one_pin(owner, run1, tag)
    assert pin1["released_at"] is None, pin1
    assert run_binding(owner, run1)["status"] == "running"
    assert _model_count(owner, run1) == 1
    assert effect_row(owner, _tool_id)["status"] == "claimed"
    assert fiber_row(owner, entry["fiber"])["want_on"] is True
    assert fiber_row(owner, base["fiber"])["current_episode_id"] == str(base["episode"])
    assert slot_row(owner, base["slot"])["released_at"] is None
    assert slot_row(owner, entry["slot"])["released_at"] is None
    before = snapshot(owner)

    steer_action = lambda conn: steer(conn, run1, 1, "d1 steer",
                                      f"{tag}-steer-{uuid4()}")[0]
    start_action = lambda conn: start_once(conn, entry, requires=("base",),
                                           key=f"{tag}-run2-{uuid4()}")
    if reverse:
        first, second, evidence, graph = first_then_second(
            db, admin, service, start_action, steer_action, tag)
        start_response, steer_response = first, second
        holder_role, waiter_role, order = "admin", "service", "start->steer"
    else:
        first, second, evidence, graph = first_then_second(
            db, service, admin, steer_action, start_action, tag)
        steer_response, start_response = first, second
        holder_role, waiter_role, order = "service", "admin", "steer->start"
    assert steer_response.get("disposition") == "committed", steer_response
    assert steer_response["emitted"] == [], steer_response
    assert start_response.get("disposition") == "committed", start_response
    run2 = start_response["emitted"][0]

    run1_row = run_binding(owner, run1)
    assert run1_row["pending_steer"] == {
        "instruction": "d1 steer", "generation": 2, "epoch": 2}, run1_row
    assert run1_row["driving_generation"] == 2 and run1_row["epoch_no"] == 2, run1_row
    assert _model_count(owner, run1) == 1
    assert _activation_pin(owner, entry["episode"]) == activation
    assert fiber_row(owner, base["fiber"])["current_episode_id"] == str(base["episode"])
    run2_row = run_binding(owner, run2)
    assert run2_row["status"] == "running", run2_row
    assert run2_row["owner_episode_id"] == str(entry["episode"]), run2_row
    pin2 = _one_pin(owner, run2, tag)
    assert pin2["released_at"] is None and pin2["provider_episode_id"] == str(base["episode"]), pin2
    assert effect_row(owner, _tool_id)["status"] == "claimed"

    after = snapshot(owner)
    value = diff(before, after)
    assert_diff_exact(value, {
        "effects": (3, 0, 0), "events": (3, 0, 0), "pins": (1, 0, 0),
        "requests": (2, 0, 0), "runs": (1, 1, 0),
    }, tag)
    return evidence, graph, holder_role, waiter_role, order, value


def g6_d1(db, owner):
    """steer x install/start: steer defers behind the claimed tool in both orders.

    The activation pin is byte-identical, steer emits no model, and the new run
    binds the same activated provider episode while the pending steer carries
    generation/epoch 2.
    """
    service, admin = db.connect("service"), db.connect("admin")
    try:
        for reverse in (False, True):
            evidence, graph, holder_role, waiter_role, order, value = _d1_order(
                db, owner, service, admin, reverse=reverse)
            tag = "G6-D1-order2" if reverse else "G6-D1"
            _print_order(
                tag, evidence, graph, holder_role, waiter_role, order, value,
                "steer defers behind the claimed tool (pending generation/epoch "
                "2) without a model; the concurrent start binds the same "
                "activated episode and the activation pin is unchanged")
    finally:
        service.close()
        admin.close()


def _e1_order(db, owner, service, admin, *, reverse):
    tag = "G6-E1-order2" if reverse else "G6-E1"
    entry = _fresh_self_fixture(owner, service, admin, tag)
    run_id, _model_id, tool_id, token = _start_and_claim_tool(
        owner, service, entry, ("dep",), tag)
    pin = _one_pin(owner, run_id, tag)
    assert pin["released_at"] is None, pin
    assert run_binding(owner, run_id)["status"] == "running"
    assert _model_count(owner, run_id) == 1
    assert effect_row(owner, tool_id)["status"] == "claimed"
    pre_slot = slot_row(owner, entry["slot"])
    assert pre_slot["withdrawn_at"] is None and pre_slot["released_at"] is None, pre_slot
    assert episode_row(owner, entry["episode"])["state"] == "active"
    assert fiber_row(owner, entry["fiber"])["want_on"] is True
    before = snapshot(owner)

    steer_action = lambda conn: steer(conn, run_id, 1, "e1 steer",
                                      f"{tag}-steer-{uuid4()}")[0]
    off_action = lambda conn: one(
        conn, "SELECT v24.fiber_control(%s,'off',1,%s)",
        (entry["fiber"], f"{tag}-off1-{uuid4()}"))
    if reverse:
        first, second, evidence, graph = first_then_second(
            db, admin, service, off_action, steer_action, tag)
        off_response, steer_response = first, second
        holder_role, waiter_role, order = "admin", "service", "off->steer"
    else:
        first, second, evidence, graph = first_then_second(
            db, service, admin, steer_action, off_action, tag)
        steer_response, off_response = first, second
        holder_role, waiter_role, order = "service", "admin", "steer->off"
    assert steer_response.get("disposition") == "committed", steer_response
    assert steer_response["emitted"] == [], steer_response
    assert off_response.get("disposition") == "deferred", off_response
    assert off_response["emitted"] == [], off_response

    run = run_binding(owner, run_id)
    assert run["pending_steer"] == {
        "instruction": "e1 steer", "generation": 2, "epoch": 2}, run
    assert _model_count(owner, run_id) == 1
    assert _one_pin(owner, run_id, tag)["released_at"] is None
    staged_slot = slot_row(owner, entry["slot"])
    assert staged_slot["withdrawn_at"] is not None, staged_slot
    assert staged_slot["released_at"] is None, staged_slot
    assert episode_row(owner, entry["episode"])["state"] == "retiring"

    # The claimed tool settlement consumes the pending steer exactly once.
    settled_tool = _settle_tool_success(service, tool_id, token)
    assert settled_tool.get("disposition") == "committed", settled_tool
    steer_model = steer_model_id(run_id, 2, 2, "e1 steer")
    assert settled_tool["emitted"] == [steer_model], settled_tool
    steer_effect = effect_row(owner, steer_model)
    assert steer_effect["request"]["cause"] == "steer", steer_effect
    assert _model_count(owner, run_id) == 2
    assert run_binding(owner, run_id)["pending_steer"] is None
    assert _one_pin(owner, run_id, tag)["released_at"] is None

    final = _settle_final(service, steer_model)
    assert final["emitted"] == []
    completed = run_binding(owner, run_id)
    assert completed["status"] == "completed", completed
    assert _model_count(owner, run_id) == 2
    released_pin = _one_pin(owner, run_id, tag)
    assert released_pin["released_at"] is not None, released_pin

    off2 = _fiber_off(admin, entry["fiber"], 2, f"{tag}-off2-{uuid4()}")
    assert off2.get("disposition") == "committed", off2
    assert off2["emitted"] == [], off2
    assert _model_count(owner, run_id) == 2
    final_slot = slot_row(owner, entry["slot"])
    assert final_slot["released_at"] is not None, final_slot
    assert episode_row(owner, entry["episode"])["state"] == "closed"
    assert fiber_row(owner, entry["fiber"])["current_episode_id"] is None
    released_after_pin = one(
        owner, "SELECT s.released_at >= p.released_at FROM v24.slots s "
               "JOIN v24.pins p ON p.pin_id=%s WHERE s.slot_id=%s",
        (pin["pin_id"], entry["slot"]))
    assert released_after_pin is True, (pin["pin_id"], entry["slot"])

    after = snapshot(owner)
    value = diff(before, after)
    assert_diff_exact(value, {
        "effects": (5, 1, 0), "episodes": (0, 1, 0), "events": (9, 0, 0),
        "fibers": (0, 1, 0), "pins": (0, 1, 0), "requests": (3, 0, 0),
        "runs": (0, 1, 0), "slots": (0, 1, 0),
    }, tag)
    return evidence, graph, holder_role, waiter_role, order, value


def g6_e1(db, owner):
    """steer x retire: steer follows the old pin, one model, retire drains last.

    Order 1 steers first (deferred behind the claimed tool) and retires second;
    order 2 retires first (withdrawn/retiring) and still accepts the active
    steer.  The claimed tool yields exactly one cause='steer' model and the slot
    is released only after the pin.
    """
    service, admin = db.connect("service"), db.connect("admin")
    try:
        for reverse in (False, True):
            evidence, graph, holder_role, waiter_role, order, value = _e1_order(
                db, owner, service, admin, reverse=reverse)
            tag = "G6-E1-order2" if reverse else "G6-E1"
            _print_order(
                tag, evidence, graph, holder_role, waiter_role, order, value,
                "retire is deferred while the claimed tool pin lives; steer "
                "keeps the old generation and yields exactly one cause='steer' "
                "model; slot release follows pin release")
    finally:
        service.close()
        admin.close()


def _f1_order1(db, owner, service, admin):
    tag = "G6-F1"
    entry = _fresh_self_fixture(owner, service, admin, tag)
    run_id, _model_id, tool_id, token = _start_and_claim_tool(
        owner, service, entry, ("dep",), tag)
    pin = _one_pin(owner, run_id, tag)
    assert pin["released_at"] is None, pin
    assert run_binding(owner, run_id)["status"] == "running"
    assert effect_row(owner, tool_id)["status"] == "claimed"
    assert install_row(owner, entry["install"])["state"] == "installed"
    pre_slot = slot_row(owner, entry["slot"])
    assert pre_slot["withdrawn_at"] is None and pre_slot["released_at"] is None, pre_slot
    assert episode_row(owner, entry["episode"])["state"] == "active"
    assert fiber_row(owner, entry["fiber"])["want_on"] is True
    before = snapshot(owner)

    steer_action = lambda conn: steer(conn, run_id, 1, "f1 steer",
                                      f"{tag}-steer-{uuid4()}")[0]
    dispose_action = lambda conn: one(
        conn, "SELECT v24.dispose(%s,%s)",
        (entry["install"], f"{tag}-dispose1-{uuid4()}"))
    steer_response, dispose_response, evidence, graph = first_then_second(
        db, service, admin, steer_action, dispose_action, tag)
    assert steer_response.get("disposition") == "committed", steer_response
    assert steer_response["emitted"] == [], steer_response
    assert dispose_response.get("disposition") == "committed", dispose_response
    assert dispose_response["emitted"] == [], dispose_response

    run = run_binding(owner, run_id)
    assert run["pending_steer"] == {
        "instruction": "f1 steer", "generation": 2, "epoch": 2}, run
    assert _model_count(owner, run_id) == 1
    staged_install = install_row(owner, entry["install"])
    assert staged_install["state"] == "dispose_pending", staged_install
    assert staged_install["disposed_at"] is None, staged_install
    assert fiber_row(owner, entry["fiber"])["disposed_at"] is None
    assert _one_pin(owner, run_id, tag)["released_at"] is None
    staged_slot = slot_row(owner, entry["slot"])
    assert staged_slot["withdrawn_at"] is not None, staged_slot
    assert staged_slot["released_at"] is None, staged_slot
    assert episode_row(owner, entry["episode"])["state"] == "retiring"

    # pending steer -> exactly one steer model; the conversation continuation
    # cannot revive the pending install/fiber.
    settled_tool = _settle_tool_success(service, tool_id, token)
    steer_model = steer_model_id(run_id, 2, 2, "f1 steer")
    assert settled_tool["emitted"] == [steer_model], settled_tool
    assert effect_row(owner, steer_model)["request"]["cause"] == "steer"
    assert _model_count(owner, run_id) == 2
    assert install_row(owner, entry["install"])["state"] == "dispose_pending"

    final = _settle_final(service, steer_model)
    assert final["emitted"] == []
    completed = run_binding(owner, run_id)
    assert completed["status"] == "completed", completed
    assert _one_pin(owner, run_id, tag)["released_at"] is not None

    off = _fiber_off(admin, entry["fiber"], 1, f"{tag}-off-{uuid4()}")
    assert off.get("disposition") == "committed", off
    assert slot_row(owner, entry["slot"])["released_at"] is not None
    disposed = one(admin, "SELECT v24.dispose(%s,%s)",
                   (entry["install"], f"{tag}-dispose2-{uuid4()}"))
    admin.commit()
    assert disposed.get("disposition") == "committed", disposed
    assert len(disposed["emitted"]) == 1, disposed
    release_id = disposed["emitted"][0]
    assert effect_row(owner, release_id)["kind"] == "host_release"
    settled = _settle_host_release(service, release_id)
    assert settled.get("disposition") == "committed", settled
    final_install = install_row(owner, entry["install"])
    assert final_install["state"] == "disposed", final_install
    assert final_install["disposed_at"] is not None, final_install
    assert fiber_row(owner, entry["fiber"])["disposed_at"] is not None
    final_run = run_binding(owner, run_id)
    assert final_run["status"] == "completed", final_run
    assert final_run["pending_steer"] is None, final_run
    assert _model_count(owner, run_id) == 2
    assert _run_pins_of(owner, run_id) == [] or all(
        row["released_at"] is not None for row in _run_pins_of(owner, run_id))
    final_slot = slot_row(owner, entry["slot"])
    assert final_slot["released_at"] is not None, final_slot
    assert episode_row(owner, entry["episode"])["state"] == "closed"

    after = snapshot(owner)
    value = diff(before, after)
    assert_diff_exact(value, {
        "effects": (7, 1, 0), "episodes": (0, 1, 0), "events": (13, 0, 0),
        "fibers": (0, 1, 0), "installs": (0, 1, 0), "pins": (0, 1, 0),
        "requests": (4, 0, 0), "runs": (0, 1, 0), "slots": (0, 1, 0),
    }, tag)
    order = "steer->dispose"
    _print_order(
        tag, evidence, graph, "service", "admin", order, value,
        "steer defers on the claimed tool while dispose only pends; the single "
        "steer model completes the run, dispose settles to disposed and the "
        "continuation never revives the disposed fiber")
    return after


def _f1_order2(db, owner, service, admin):
    tag = "G6-F1-order2"
    entry = _fresh_self_fixture(owner, service, admin, tag)
    started, _ = start_run(service, entry, requires=("dep",),
                           key=f"{tag}-run-{uuid4()}")
    assert started.get("disposition") == "committed", started
    run_id = started["emitted"][0]
    cancelled, _ = cancel(service, run_id, 1, f"{tag}-cancel-{uuid4()}")
    service.commit()
    assert cancelled.get("disposition") == "committed", cancelled
    assert run_binding(owner, run_id)["status"] == "cancelled"
    assert _run_pins_of(owner, run_id) == [] or all(
        row["released_at"] is not None for row in _run_pins_of(owner, run_id))
    run_before = run_binding(owner, run_id)
    model_before = effect_row(owner, started["emitted"][1])
    assert install_row(owner, entry["install"])["state"] == "installed"
    assert fiber_row(owner, entry["fiber"])["want_on"] is True
    assert fiber_row(owner, entry["fiber"])["disposed_at"] is None
    pre_slot = slot_row(owner, entry["slot"])
    assert pre_slot["withdrawn_at"] is None and pre_slot["released_at"] is None, pre_slot
    assert episode_row(owner, entry["episode"])["state"] == "active"
    before = snapshot(owner)

    dispose_action = lambda conn: one(
        conn, "SELECT v24.dispose(%s,%s)",
        (entry["install"], f"{tag}-dispose1-{uuid4()}"))
    steer_action = lambda conn: steer(conn, run_id, 1, "revive?", 
                                      f"{tag}-steer-{uuid4()}")[0]
    dispose_response, steer_response, evidence, graph = first_then_second(
        db, admin, service, dispose_action, steer_action, tag)
    assert dispose_response.get("disposition") == "committed", dispose_response
    assert dispose_response["emitted"] == [], dispose_response
    assert steer_response == {"v": 1, "error": {"code": "already_terminal",
                                                "detail": {}}}, steer_response

    # W1: domain zero write, exactly one failed command_steer receipt, and the
    # terminal run/pin/fiber/dispose state is unchanged.
    assert run_binding(owner, run_id) == run_before
    assert effect_row(owner, started["emitted"][1]) == model_before
    assert _run_pins_of(owner, run_id) == [] or all(
        row["released_at"] is not None for row in _run_pins_of(owner, run_id))
    assert _model_count(owner, run_id) == 1
    staged_install = install_row(owner, entry["install"])
    assert staged_install["state"] == "dispose_pending", staged_install
    assert staged_install["disposed_at"] is None, staged_install
    assert fiber_row(owner, entry["fiber"])["disposed_at"] is None
    failed = one(owner, "SELECT to_jsonb(e) FROM v24.effects e "
                        "WHERE e.kind='command_steer' AND e.status='failed' "
                        "AND e.request_key LIKE %s", (f"{tag}-steer-%",))
    owner.rollback()
    assert failed is not None, "steer W1 receipt missing"
    assert failed["run_id"] is None, failed

    # Intermediate exact diff: dispose's own pending/retire rows plus the W1
    # receipt only.  The blocked steer created no model, pin or domain row.
    staged = snapshot(owner)
    assert_diff_exact(diff(before, staged), {
        "effects": (2, 0, 0), "episodes": (0, 1, 0), "events": (3, 0, 0),
        "fibers": (0, 1, 0), "installs": (0, 1, 0),
        "requests": (2, 0, 0), "slots": (0, 1, 0),
    }, f"{tag}-race")

    off = _fiber_off(admin, entry["fiber"], 1, f"{tag}-off-{uuid4()}")
    assert off.get("disposition") == "committed", off
    assert slot_row(owner, entry["slot"])["released_at"] is not None
    disposed = one(admin, "SELECT v24.dispose(%s,%s)",
                   (entry["install"], f"{tag}-dispose2-{uuid4()}"))
    admin.commit()
    assert disposed.get("disposition") == "committed", disposed
    assert len(disposed["emitted"]) == 1, disposed
    settled = _settle_host_release(service, disposed["emitted"][0])
    assert settled.get("disposition") == "committed", settled
    final_install = install_row(owner, entry["install"])
    assert final_install["state"] == "disposed", final_install
    assert final_install["disposed_at"] is not None, final_install
    assert fiber_row(owner, entry["fiber"])["disposed_at"] is not None
    assert run_binding(owner, run_id) == run_before
    assert effect_row(owner, started["emitted"][1]) == model_before

    after = snapshot(owner)
    value = diff(before, after)
    assert_diff_exact(value, {
        "effects": (6, 0, 0), "episodes": (0, 1, 0), "events": (8, 0, 0),
        "fibers": (0, 1, 0), "installs": (0, 1, 0),
        "requests": (4, 0, 0), "slots": (0, 1, 0),
    }, tag)
    _print_order(
        tag, evidence, graph, "admin", "service", "dispose->steer", value,
        "dispose holds G on a terminal run's install; the queued steer is "
        "already_terminal W1 with zero domain write and disposed_at NULL; the "
        "W1 receipt does not revive the fiber")
    return after


def g6_f1(db, owner):
    """steer x dispose: continuity cannot revive a disposed/pending fiber.

    Order 1 steers a claimed-tool run (pending), disposes (deferred), then
    settles the single steer model and drains to disposed.  Order 2 disposes
    first on a terminal run while holding G; the queued steer is
    already_terminal W1 (zero domain write, disposed_at still NULL) and the
    install only drains afterwards.
    """
    service, admin = db.connect("service"), db.connect("admin")
    try:
        _f1_order1(db, owner, service, admin)
        _f1_order2(db, owner, service, admin)
    finally:
        service.close()
        admin.close()


# ---------------------------------------------------------------------------
# G6-G1..G3: respond x activate/retire/dispose
# ---------------------------------------------------------------------------

BUDGET = {"steps": 7, "tool_calls": 2, "tokens": 5000, "wall_ms": 600000}
SCHEMA_DIGEST = "1" * 64
PROMPT_DIGEST = "2" * 64


def _start_committed(conn, entry, requires, key):
    response, _ = start(conn, entry["scope"], entry["fiber"],
                        {"requires": [{"key": item} for item in requires]},
                        BUDGET, key)
    conn.commit()
    assert response.get("disposition") == "committed", response
    return response


def _waiting_fixture(owner, service, admin, tag, *, dependent):
    """A live run waiting on one interaction, with a real run pin.

    ``dependent`` uses the activated A->B pair (so an activation pin exists);
    the self-provide shape gives the run a pin to its own episode/slot, which
    is what makes the following off/dispose barrier real.
    """
    if dependent:
        base, entry = _fresh_dep_fixture(owner, service, admin, tag)
        requires = ("base",)
    else:
        base, entry = None, _fresh_self_fixture(owner, service, admin, tag)
        requires = ("dep",)
    started = _start_committed(service, entry, requires,
                               f"{tag}-wait-{uuid4()}")
    run_id, model_id = started["emitted"]
    token = claim_effect(service, model_id)
    result = {"text": "need input",
              "interaction": {"schema_digest": SCHEMA_DIGEST,
                              "prompt_digest": PROMPT_DIGEST,
                              "payload": {"question": "colour?",
                                          "options": ["red", "blue"]}},
              "usage": {"tokens": 40, "wall_ms": 7}}
    settled, _ = settle(service, model_id, token, "success", result)
    assert settled.get("disposition") == "committed", settled
    assert settled["emitted"] == [], settled
    run = run_binding(owner, run_id)
    assert run["status"] == "waiting", run
    interaction = run["interaction"]
    assert interaction is not None, run
    assert interaction["interaction_id"] == model_id, interaction
    assert interaction["origin_effect_id"] == model_id, interaction
    assert interaction["generation"] == 1, interaction
    assert run["driving_generation"] == 1 and run["epoch_no"] == 1, run
    return {"base": base, "entry": entry, "run": run_id, "model": model_id,
            "interaction": interaction, "requires": requires}


def _respond_action(conn, fixture, answer, tag):
    return respond(conn, fixture["run"],
                   fixture["interaction"]["interaction_id"], answer,
                   fixture["interaction"]["generation"],
                   f"{tag}-respond-{uuid4()}")[0]


def _event_count(owner, run_id, kind):
    return one(owner, "SELECT count(*) FROM v24.events WHERE entity_id=%s "
                      "AND event_kind=%s", (run_id, kind))


def _single_event(owner, run_id, kind):
    rows = one(owner, "SELECT coalesce(jsonb_agg(to_jsonb(e)),'[]'::jsonb) "
                      "FROM v24.events e WHERE e.entity_id=%s AND e.event_kind=%s",
               (run_id, kind))
    assert len(rows) == 1, (run_id, kind, rows)
    return rows[0]


def _g1_order(db, owner, service, admin, *, reverse):
    tag = "G6-G1-order2" if reverse else "G6-G1"
    fixture = _waiting_fixture(owner, service, admin, tag, dependent=True)
    activation = _activation_pin(owner, fixture["entry"]["episode"])
    pin = _one_pin(owner, fixture["run"], tag)
    old_model = effect_row(owner, fixture["model"])
    assert pin["released_at"] is None, pin
    assert pin["provider_episode_id"] == str(fixture["base"]["episode"]), pin
    assert activation["provider_episode_id"] == str(fixture["base"]["episode"]), activation
    before = snapshot(owner)
    answer = {"answer": "yes", "structured": {"n": 7}}
    holder = db.connect("service")
    waiter = db.connect("service")
    try:
        respond_action = lambda conn: _respond_action(conn, fixture, answer, tag)
        start_action = lambda conn: start_once(
            conn, fixture["entry"], requires=fixture["requires"],
            key=f"{tag}-run2-{uuid4()}")
        if reverse:
            first, second, evidence, graph = first_then_second(
                db, holder, waiter, start_action, respond_action, tag)
            start_response, respond_response = first, second
            order = "start->respond"
        else:
            first, second, evidence, graph = first_then_second(
                db, holder, waiter, respond_action, start_action, tag)
            respond_response, start_response = first, second
            order = "respond->start"
    finally:
        holder.close()
        waiter.close()
    assert respond_response.get("disposition") == "committed", respond_response
    assert len(respond_response["emitted"]) == 1, respond_response
    continuation = respond_response["emitted"][0]
    assert start_response.get("disposition") == "committed", start_response
    run2 = start_response["emitted"][0]

    run1 = run_binding(owner, fixture["run"])
    assert run1["status"] == "running", run1
    assert run1["interaction"] is None and run1["pending_steer"] is None, run1
    assert run1["driving_generation"] == 2 and run1["epoch_no"] == 1, run1
    assert run1["turn_no"] == 1, run1
    assert run1["remaining_steps"] == 5 and run1["remaining_tokens"] == 864, run1
    assert effect_row(owner, fixture["model"]) == old_model
    continuation_row = effect_row(owner, continuation)
    assert continuation_row["status"] == "ready", continuation_row
    assert continuation_row["kind"] == "model_call", continuation_row
    assert continuation_row["parent_effect_id"] == respond_response["effect_id"], continuation_row
    assert continuation_row["ordinal"] == 0 and continuation_row["pin_id"] is None, continuation_row
    assert continuation_row["generation"] == 2 and continuation_row["epoch_no"] == 1, continuation_row
    request = continuation_row["request"]
    assert request["cause"] == "respond", request
    assert request["response"] == answer, request
    assert request["origin_effect_id"] == fixture["model"], request
    assert len(model_rows(owner, fixture["run"])) == 2
    assert one(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                      "AND kind='model_call' AND status='ready'",
               (fixture["run"],)) == 1
    created = _single_event(owner, fixture["run"], "interaction_created")
    responded = _single_event(owner, fixture["run"], "interaction_responded")
    assert created["payload"]["interaction_id"] == fixture["model"], created
    assert responded["payload"]["interaction_id"] == fixture["model"], responded
    assert responded["payload"]["generation"] == 2, responded
    assert _activation_pin(owner, fixture["entry"]["episode"]) == activation
    assert _one_pin(owner, fixture["run"], tag)["released_at"] is None
    run2_row = run_binding(owner, run2)
    assert run2_row["status"] == "running", run2_row
    assert run2_row["owner_episode_id"] == str(fixture["entry"]["episode"]), run2_row
    pin2 = _one_pin(owner, run2, tag)
    assert pin2["released_at"] is None, pin2
    assert pin2["provider_episode_id"] == str(fixture["base"]["episode"]), pin2

    after = snapshot(owner)
    value = diff(before, after)
    assert_diff_exact(value, {
        "effects": (4, 0, 0), "events": (3, 0, 0), "pins": (1, 0, 0),
        "requests": (2, 0, 0), "runs": (1, 1, 0),
    }, tag)
    return evidence, graph, order, value


def g6_g1(db, owner):
    """respond x activate: respond consumes only the original interaction.

    Both orders run respond (service backend) against start(run2) (second
    service backend).  The activation pin is byte-identical, run2 binds the same
    provider episode, and exactly one continuation on the original interaction
    exists (no second interaction).
    """
    service, admin = db.connect("service"), db.connect("admin")
    try:
        for reverse in (False, True):
            evidence, graph, order, value = _g1_order(
                db, owner, service, admin, reverse=reverse)
            tag = "G6-G1-order2" if reverse else "G6-G1"
            _print_order(
                tag, evidence, graph, "service", "service", order, value,
                "respond consumes only the original interaction and admits one "
                "cause=respond continuation; the concurrent start binds the "
                "same activated provider episode; activation pin unchanged")
    finally:
        service.close()
        admin.close()


def _g2_order(db, owner, service, admin, *, reverse):
    tag = "G6-G2-order2" if reverse else "G6-G2"
    fixture = _waiting_fixture(owner, service, admin, tag, dependent=False)
    pin = _one_pin(owner, fixture["run"], tag)
    old_model = effect_row(owner, fixture["model"])
    pre_slot = slot_row(owner, fixture["entry"]["slot"])
    assert pin["released_at"] is None, pin
    assert pre_slot["withdrawn_at"] is None and pre_slot["released_at"] is None, pre_slot
    assert episode_row(owner, fixture["entry"]["episode"])["state"] == "active"
    assert fiber_row(owner, fixture["entry"]["fiber"])["want_on"] is True
    before = snapshot(owner)
    answer = {"answer": "red"}

    respond_action = lambda conn: _respond_action(conn, fixture, answer, tag)
    off_action = lambda conn: one(
        conn, "SELECT v24.fiber_control(%s,'off',1,%s)",
        (fixture["entry"]["fiber"], f"{tag}-off1-{uuid4()}"))
    if reverse:
        first, second, evidence, graph = first_then_second(
            db, admin, service, off_action, respond_action, tag)
        off_response, respond_response = first, second
        holder_role, waiter_role, order = "admin", "service", "off->respond"
    else:
        first, second, evidence, graph = first_then_second(
            db, service, admin, respond_action, off_action, tag)
        respond_response, off_response = first, second
        holder_role, waiter_role, order = "service", "admin", "respond->off"
    assert respond_response.get("disposition") == "committed", respond_response
    assert len(respond_response["emitted"]) == 1, respond_response
    continuation = respond_response["emitted"][0]
    assert off_response.get("disposition") == "deferred", off_response
    assert off_response["emitted"] == [], off_response

    run = run_binding(owner, fixture["run"])
    assert run["status"] == "running" and run["interaction"] is None, run
    assert run["driving_generation"] == 2, run
    assert effect_row(owner, fixture["model"]) == old_model
    assert effect_row(owner, continuation)["status"] == "ready"
    assert len(model_rows(owner, fixture["run"])) == 2
    assert _one_pin(owner, fixture["run"], tag)["released_at"] is None
    staged_slot = slot_row(owner, fixture["entry"]["slot"])
    assert staged_slot["withdrawn_at"] is not None, staged_slot
    assert staged_slot["released_at"] is None, staged_slot
    assert episode_row(owner, fixture["entry"]["episode"])["state"] == "retiring"
    assert fiber_row(owner, fixture["entry"]["fiber"])["want_on"] is False
    assert _event_count(owner, fixture["run"], "interaction_created") == 1
    assert _event_count(owner, fixture["run"], "interaction_responded") == 1

    # Drain the one continuation to terminal: only then may the pin and slot
    # be released by the next off.
    _settle_final(service, continuation)
    completed = run_binding(owner, fixture["run"])
    assert completed["status"] == "completed", completed
    assert _one_pin(owner, fixture["run"], tag)["released_at"] is not None
    off2 = _fiber_off(admin, fixture["entry"]["fiber"], 2, f"{tag}-off2-{uuid4()}")
    assert off2.get("disposition") == "committed", off2
    assert off2["emitted"] == [], off2
    assert slot_row(owner, fixture["entry"]["slot"])["released_at"] is not None
    assert episode_row(owner, fixture["entry"]["episode"])["state"] == "closed"
    assert fiber_row(owner, fixture["entry"]["fiber"])["current_episode_id"] is None
    assert _event_count(owner, fixture["run"], "interaction_created") == 1
    assert one(owner, "SELECT s.released_at >= p.released_at FROM v24.slots s "
                      "JOIN v24.pins p ON p.pin_id=%s WHERE s.slot_id=%s",
               (pin["pin_id"], fixture["entry"]["slot"])) is True

    after = snapshot(owner)
    value = diff(before, after)
    assert_diff_exact(value, {
        "effects": (5, 0, 0), "episodes": (0, 1, 0), "events": (7, 0, 0),
        "fibers": (0, 1, 0), "pins": (0, 1, 0), "requests": (3, 0, 0),
        "runs": (0, 1, 0), "slots": (0, 1, 0),
    }, tag)
    return evidence, graph, holder_role, waiter_role, order, value


def g6_g2(db, owner):
    """respond x retire: the answer still commits while the slot waits.

    Order 1 responds first (old-pin continuation) and off is deferred; order 2
    retires first (withdrawn/retiring) and the interaction remains answerable.
    The slot is released only after the continuation terminalizes and the run
    pin is released, and only one interaction ever exists.
    """
    service, admin = db.connect("service"), db.connect("admin")
    try:
        for reverse in (False, True):
            evidence, graph, holder_role, waiter_role, order, value = _g2_order(
                db, owner, service, admin, reverse=reverse)
            tag = "G6-G2-order2" if reverse else "G6-G2"
            _print_order(
                tag, evidence, graph, holder_role, waiter_role, order, value,
                "respond keeps the original interaction as its only one and "
                "publishes one old-pin continuation; off stays deferred until "
                "the run pin drains and never releases the slot early")
    finally:
        service.close()
        admin.close()


def _drain_disposed(owner, service, admin, fixture, tag):
    """off -> new-key dispose -> host_release settlement, from dispose_pending."""
    off = _fiber_off(admin, fixture["entry"]["fiber"], 1, f"{tag}-off-{uuid4()}")
    assert off.get("disposition") == "committed", off
    assert off["emitted"] == [], off
    assert slot_row(owner, fixture["entry"]["slot"])["released_at"] is not None
    assert episode_row(owner, fixture["entry"]["episode"])["state"] == "closed"
    disposed = one(admin, "SELECT v24.dispose(%s,%s)",
                   (fixture["entry"]["install"], f"{tag}-dispose2-{uuid4()}"))
    admin.commit()
    assert disposed.get("disposition") == "committed", disposed
    assert len(disposed["emitted"]) == 1, disposed
    release_id = disposed["emitted"][0]
    assert effect_row(owner, release_id)["kind"] == "host_release"
    assert install_row(owner, fixture["entry"]["install"])["state"] == "dispose_pending"
    settled = _settle_host_release(service, release_id)
    assert settled.get("disposition") == "committed", settled
    final_install = install_row(owner, fixture["entry"]["install"])
    assert final_install["state"] == "disposed", final_install
    assert final_install["disposed_at"] is not None, final_install
    assert fiber_row(owner, fixture["entry"]["fiber"])["disposed_at"] is not None


def _g3_order1(db, owner, service, admin):
    tag = "G6-G3"
    fixture = _waiting_fixture(owner, service, admin, tag, dependent=False)
    pin = _one_pin(owner, fixture["run"], tag)
    old_model = effect_row(owner, fixture["model"])
    assert pin["released_at"] is None, pin
    before = snapshot(owner)
    answer = {"answer": "blue"}
    respond_action = lambda conn: _respond_action(conn, fixture, answer, tag)
    dispose_action = lambda conn: one(
        conn, "SELECT v24.dispose(%s,%s)",
        (fixture["entry"]["install"], f"{tag}-dispose1-{uuid4()}"))
    respond_response, dispose_response, evidence, graph = first_then_second(
        db, service, admin, respond_action, dispose_action, tag)
    assert respond_response.get("disposition") == "committed", respond_response
    assert len(respond_response["emitted"]) == 1, respond_response
    continuation = respond_response["emitted"][0]
    assert dispose_response.get("disposition") == "committed", dispose_response
    assert dispose_response["emitted"] == [], dispose_response

    run = run_binding(owner, fixture["run"])
    assert run["status"] == "running" and run["interaction"] is None, run
    assert effect_row(owner, fixture["model"]) == old_model
    assert effect_row(owner, continuation)["status"] == "ready"
    assert _one_pin(owner, fixture["run"], tag)["released_at"] is None
    staged_install = install_row(owner, fixture["entry"]["install"])
    assert staged_install["state"] == "dispose_pending", staged_install
    assert staged_install["disposed_at"] is None, staged_install
    assert fiber_row(owner, fixture["entry"]["fiber"])["disposed_at"] is None
    staged_slot = slot_row(owner, fixture["entry"]["slot"])
    assert staged_slot["withdrawn_at"] is not None, staged_slot
    assert staged_slot["released_at"] is None, staged_slot
    assert episode_row(owner, fixture["entry"]["episode"])["state"] == "retiring"

    _settle_final(service, continuation)
    completed = run_binding(owner, fixture["run"])
    assert completed["status"] == "completed", completed
    released_pin = _one_pin(owner, fixture["run"], tag)
    assert released_pin["released_at"] is not None, released_pin
    # The dispose intent still may not tombstone while the run pin/terminal
    # continuation is draining.
    assert install_row(owner, fixture["entry"]["install"])["disposed_at"] is None

    _drain_disposed(owner, service, admin, fixture, tag)
    disposed_after_pin = one(
        owner, "SELECT i.disposed_at >= p.released_at FROM v24.installs i "
               "JOIN v24.pins p ON p.pin_id=%s WHERE i.install_id=%s",
        (pin["pin_id"], fixture["entry"]["install"]))
    assert disposed_after_pin is True
    after = snapshot(owner)
    value = diff(before, after)
    assert_diff_exact(value, {
        "effects": (7, 0, 0), "episodes": (0, 1, 0), "events": (11, 0, 0),
        "fibers": (0, 1, 0), "installs": (0, 1, 0), "pins": (0, 1, 0),
        "requests": (4, 0, 0), "runs": (0, 1, 0), "slots": (0, 1, 0),
    }, tag)
    _print_order(
        tag, evidence, graph, "service", "admin", "respond->dispose", value,
        "respond publishes one continuation and dispose only pends/retires; "
        "the run pin and effect debt drain before off and a new-key dispose "
        "emit host_release; disposed_at follows pin release")
    return after


def _g3_order2(db, owner, service, admin):
    tag = "G6-G3-order2"
    fixture = _waiting_fixture(owner, service, admin, tag, dependent=False)
    cancelled, _ = cancel(service, fixture["run"], 1, f"{tag}-cancel-{uuid4()}")
    service.commit()
    assert cancelled.get("disposition") == "committed", cancelled
    terminal = run_binding(owner, fixture["run"])
    assert terminal["status"] == "cancelled" and terminal["interaction"] is None, terminal
    assert _run_pins_of(owner, fixture["run"]) == [] or all(
        row["released_at"] is not None for row in _run_pins_of(owner, fixture["run"]))
    run_before = run_binding(owner, fixture["run"])
    model_before = effect_row(owner, fixture["model"])
    assert install_row(owner, fixture["entry"]["install"])["state"] == "installed"
    assert fiber_row(owner, fixture["entry"]["fiber"])["want_on"] is True
    assert fiber_row(owner, fixture["entry"]["fiber"])["disposed_at"] is None
    pre_slot = slot_row(owner, fixture["entry"]["slot"])
    assert pre_slot["withdrawn_at"] is None and pre_slot["released_at"] is None, pre_slot
    assert episode_row(owner, fixture["entry"]["episode"])["state"] == "active"
    before = snapshot(owner)

    dispose_action = lambda conn: one(
        conn, "SELECT v24.dispose(%s,%s)",
        (fixture["entry"]["install"], f"{tag}-dispose1-{uuid4()}"))
    respond_action = lambda conn: _respond_action(
        conn, fixture, {"answer": "late"}, tag)
    dispose_response, respond_response, evidence, graph = first_then_second(
        db, admin, service, dispose_action, respond_action, tag)
    assert dispose_response.get("disposition") == "committed", dispose_response
    assert dispose_response["emitted"] == [], dispose_response
    assert respond_response == {"v": 1, "error": {"code": "already_terminal",
                                                  "detail": {}}}, respond_response

    # W1: the terminal run and its model are byte-identical, the interaction is
    # not resurrected, and disposed_at is still NULL.
    assert run_binding(owner, fixture["run"]) == run_before
    assert effect_row(owner, fixture["model"]) == model_before
    assert _run_pins_of(owner, fixture["run"]) == [] or all(
        row["released_at"] is not None for row in _run_pins_of(owner, fixture["run"]))
    assert _event_count(owner, fixture["run"], "interaction_created") == 1
    assert _event_count(owner, fixture["run"], "interaction_responded") == 0
    staged_install = install_row(owner, fixture["entry"]["install"])
    assert staged_install["state"] == "dispose_pending", staged_install
    assert staged_install["disposed_at"] is None, staged_install
    assert fiber_row(owner, fixture["entry"]["fiber"])["disposed_at"] is None
    staged_slot = slot_row(owner, fixture["entry"]["slot"])
    assert staged_slot["withdrawn_at"] is not None, staged_slot
    assert staged_slot["released_at"] is None, staged_slot
    assert episode_row(owner, fixture["entry"]["episode"])["state"] == "retiring"
    staged = snapshot(owner)
    assert_diff_exact(diff(before, staged), {
        "effects": (2, 0, 0), "episodes": (0, 1, 0), "events": (3, 0, 0),
        "fibers": (0, 1, 0), "installs": (0, 1, 0),
        "requests": (2, 0, 0), "slots": (0, 1, 0),
    }, f"{tag}-race")
    failed = one(owner, "SELECT to_jsonb(e) FROM v24.effects e "
                        "WHERE e.kind='command_respond' AND e.status='failed' "
                        "AND e.request_key LIKE %s", (f"{tag}-respond-%",))
    owner.rollback()
    assert failed is not None, "respond W1 receipt missing"
    assert failed["run_id"] is None, failed

    _drain_disposed(owner, service, admin, fixture, tag)
    assert run_binding(owner, fixture["run"]) == run_before
    assert effect_row(owner, fixture["model"]) == model_before
    assert _event_count(owner, fixture["run"], "interaction_created") == 1
    after = snapshot(owner)
    value = diff(before, after)
    assert_diff_exact(value, {
        "effects": (6, 0, 0), "episodes": (0, 1, 0), "events": (8, 0, 0),
        "fibers": (0, 1, 0), "installs": (0, 1, 0),
        "requests": (4, 0, 0), "slots": (0, 1, 0),
    }, tag)
    _print_order(
        tag, evidence, graph, "admin", "service", "dispose->respond", value,
        "dispose holds G on the terminal run's install; respond is "
        "already_terminal W1 with zero domain write, no revived interaction "
        "and disposed_at still NULL; the install only drains afterwards")
    return after


def g6_g3(db, owner):
    """respond x dispose: dispose never cancels a live interaction.

    Order 1 answers the waiting interaction (continuation) and dispose is
    deferred until the run terminalizes/drains.  Order 2 first makes the run
    terminal; dispose holds G, the queued respond is already_terminal W1 with
    zero revival, and disposed_at is only written after the drain.
    """
    service, admin = db.connect("service"), db.connect("admin")
    try:
        _g3_order1(db, owner, service, admin)
        _g3_order2(db, owner, service, admin)
    finally:
        service.close()
        admin.close()


# ---------------------------------------------------------------------------
# G6-H1..H3: model/tool advance (T2) x activate/retire/dispose
# ---------------------------------------------------------------------------

def _claimed_model_fixture(owner, service, admin, tag):
    """One running run with its first model claimed (T2 not yet submitted)."""
    entry = _fresh_self_fixture(owner, service, admin, tag)
    started = _start_committed(service, entry, ("dep",), f"{tag}-run-{uuid4()}")
    run_id, model_id = started["emitted"]
    token = claim_effect(service, model_id)
    run = run_binding(owner, run_id)
    model = effect_row(owner, model_id)
    pin = _one_pin(owner, run_id, tag)
    assert run["status"] == "running", run
    assert model["status"] == "claimed" and model["attempt_no"] == 1, model
    assert pin["released_at"] is None and pin["key"] == "dep", pin
    pre_slot = slot_row(owner, entry["slot"])
    assert pre_slot["withdrawn_at"] is None and pre_slot["released_at"] is None, pre_slot
    assert episode_row(owner, entry["episode"])["state"] == "active"
    assert fiber_row(owner, entry["fiber"])["want_on"] is True
    return {"entry": entry, "run": run_id, "model": model_id, "token": token,
            "pin": pin, "run_row": run, "model_row": model}


def _t2_receipt(token):
    return {"v": 1, "class": "success", "claim": token,
            "body": {"kind": "model_call",
                     "result": {"text": "step",
                                "usage": {"tokens": 40, "wall_ms": 5}}}}


def _h1_order(db, owner, service, admin, *, reverse):
    tag = "G6-H1-order2" if reverse else "G6-H1"
    fixture = _claimed_model_fixture(owner, service, admin, tag)
    before = snapshot(owner)
    receipt = _t2_receipt(fixture["token"])
    settle_action = lambda conn: advance(conn, fixture["model"], receipt)
    start_action = lambda conn: start_once(
        conn, fixture["entry"], requires=("dep",), key=f"{tag}-run2-{uuid4()}")
    holder = db.connect("service")
    waiter = db.connect("service")
    try:
        if reverse:
            first, second, evidence, graph = first_then_second(
                db, holder, waiter, start_action, settle_action, tag)
            start_response, settle_response = first, second
            order = "start->settle"
        else:
            first, second, evidence, graph = first_then_second(
                db, holder, waiter, settle_action, start_action, tag)
            settle_response, start_response = first, second
            order = "settle->start"
    finally:
        holder.close()
        waiter.close()
    continuation = md5_uuid(f"{fixture['model']}:continuation")
    assert settle_response.get("disposition") == "committed", settle_response
    assert settle_response["emitted"] == [continuation], settle_response
    assert start_response.get("disposition") == "committed", start_response
    run2 = start_response["emitted"][0]

    settled_model = effect_row(owner, fixture["model"])
    assert settled_model["status"] == "succeeded", settled_model
    assert settled_model["outcome"] == receipt, settled_model
    assert settled_model["resource_quiesced_at"] is not None, settled_model
    assert settled_model["claim_owner"] is None and settled_model["lease_until"] is None, settled_model
    frozen = settled_model["request"]
    assert frozen["generation"] == 1 and frozen["epoch_no"] == 1, frozen
    assert settled_model["pin_id"] is None, settled_model
    continuation_row = effect_row(owner, continuation)
    assert continuation_row["status"] == "ready", continuation_row
    assert continuation_row["kind"] == "model_call", continuation_row
    assert continuation_row["parent_effect_id"] == fixture["model"], continuation_row
    assert continuation_row["ordinal"] == 0 and continuation_row["pin_id"] is None, continuation_row
    assert continuation_row["generation"] == 1 and continuation_row["epoch_no"] == 1, continuation_row
    assert continuation_row["request"]["cause"] == "continuation", continuation_row
    assert continuation_row["request"]["input"] == frozen["input"], continuation_row
    assert continuation_row["request"]["reserve"] == {"tokens": 4096}, continuation_row
    run1 = run_binding(owner, fixture["run"])
    assert run1["status"] == "running", run1
    assert run1["turn_no"] == 1, run1
    assert run1["remaining_steps"] == 5, run1
    assert run1["remaining_tokens"] == 864, run1
    assert run1["driving_generation"] == 1, run1
    assert _one_pin(owner, fixture["run"], tag)["released_at"] is None
    models = model_rows(owner, fixture["run"])
    assert len(models) == 2, models
    assert one(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                      "AND kind='model_call' AND status='ready'",
               (fixture["run"],)) == 1
    assert _event_count(owner, fixture["run"], "model_call_settled") == 1
    run2_row = run_binding(owner, run2)
    assert run2_row["status"] == "running", run2_row
    assert run2_row["owner_episode_id"] == str(fixture["entry"]["episode"]), run2_row
    pin2 = _one_pin(owner, run2, tag)
    assert pin2["released_at"] is None, pin2
    assert pin2["provider_episode_id"] == str(fixture["entry"]["episode"]), pin2

    after = snapshot(owner)
    value = diff(before, after)
    assert_diff_exact(value, {
        "effects": (3, 1, 0), "events": (3, 0, 0), "pins": (1, 0, 0),
        "requests": (1, 0, 0), "runs": (1, 1, 0),
    }, tag)
    return evidence, graph, order, value


def g6_h1(db, owner):
    """T2 x activate: the receipt lands on the frozen generation; start is separate.

    Both orders settle the claimed model (T2) against start(run2).  The receipt
    is exact, the single continuation is on the frozen generation, run2 resolves
    the current episode, and turn/cost are counted once.
    """
    service, admin = db.connect("service"), db.connect("admin")
    try:
        for reverse in (False, True):
            evidence, graph, order, value = _h1_order(
                db, owner, service, admin, reverse=reverse)
            tag = "G6-H1-order2" if reverse else "G6-H1"
            _print_order(
                tag, evidence, graph, "service", "service", order, value,
                "T2 records the exact receipt on the frozen generation and "
                "publishes one ready continuation; the concurrent start binds "
                "the current episode with no second unsettled model and "
                "turn/cost counted once")
    finally:
        service.close()
        admin.close()


def _h2_order(db, owner, service, admin, *, reverse):
    tag = "G6-H2-order2" if reverse else "G6-H2"
    fixture = _claimed_model_fixture(owner, service, admin, tag)
    before = snapshot(owner)
    receipt = _t2_receipt(fixture["token"])
    settle_action = lambda conn: advance(conn, fixture["model"], receipt)
    off_action = lambda conn: one(
        conn, "SELECT v24.fiber_control(%s,'off',1,%s)",
        (fixture["entry"]["fiber"], f"{tag}-off1-{uuid4()}"))
    if reverse:
        first, second, evidence, graph = first_then_second(
            db, admin, service, off_action, settle_action, tag)
        off_response, settle_response = first, second
        holder_role, waiter_role, order = "admin", "service", "off->settle"
    else:
        first, second, evidence, graph = first_then_second(
            db, service, admin, settle_action, off_action, tag)
        settle_response, off_response = first, second
        holder_role, waiter_role, order = "service", "admin", "settle->off"
    continuation = md5_uuid(f"{fixture['model']}:continuation")
    assert settle_response.get("disposition") == "committed", settle_response
    assert settle_response["emitted"] == [continuation], settle_response
    assert off_response.get("disposition") == "deferred", off_response
    assert off_response["emitted"] == [], off_response

    settled_model = effect_row(owner, fixture["model"])
    assert settled_model["status"] == "succeeded", settled_model
    assert settled_model["outcome"] == receipt, settled_model
    assert settled_model["resource_quiesced_at"] is not None, settled_model
    run = run_binding(owner, fixture["run"])
    assert run["status"] == "running", run
    assert run["turn_no"] == 1 and run["remaining_steps"] == 5, run
    assert run["remaining_tokens"] == 864, run
    continuation_row = effect_row(owner, continuation)
    assert continuation_row["status"] == "ready", continuation_row
    assert continuation_row["generation"] == settled_model["request"]["generation"], continuation_row
    assert continuation_row["epoch_no"] == settled_model["request"]["epoch_no"], continuation_row
    assert run["driving_generation"] == continuation_row["generation"], run
    pins = _run_pins_of(owner, fixture["run"])
    assert len(pins) == 1 and pins[0]["pin_id"] == fixture["pin"]["pin_id"], pins
    assert pins[0]["released_at"] is None, pins
    staged_slot = slot_row(owner, fixture["entry"]["slot"])
    assert staged_slot["withdrawn_at"] is not None, staged_slot
    assert staged_slot["released_at"] is None, staged_slot
    assert episode_row(owner, fixture["entry"]["episode"])["state"] == "retiring"
    assert fiber_row(owner, fixture["entry"]["fiber"])["want_on"] is False

    _settle_final(service, continuation)
    completed = run_binding(owner, fixture["run"])
    assert completed["status"] == "completed", completed
    released_pin = _one_pin(owner, fixture["run"], tag)
    assert released_pin["released_at"] is not None, released_pin
    off2 = _fiber_off(admin, fixture["entry"]["fiber"], 2, f"{tag}-off2-{uuid4()}")
    assert off2.get("disposition") == "committed", off2
    assert off2["emitted"] == [], off2
    assert slot_row(owner, fixture["entry"]["slot"])["released_at"] is not None
    assert episode_row(owner, fixture["entry"]["episode"])["state"] == "closed"
    assert one(owner, "SELECT s.released_at >= p.released_at FROM v24.slots s "
                      "JOIN v24.pins p ON p.pin_id=%s WHERE s.slot_id=%s",
               (fixture["pin"]["pin_id"], fixture["entry"]["slot"])) is True

    after = snapshot(owner)
    value = diff(before, after)
    assert_diff_exact(value, {
        "effects": (4, 1, 0), "episodes": (0, 1, 0), "events": (7, 0, 0),
        "fibers": (0, 1, 0), "pins": (0, 1, 0), "requests": (2, 0, 0),
        "runs": (0, 1, 0), "slots": (0, 1, 0),
    }, tag)
    return evidence, graph, holder_role, waiter_role, order, value


def g6_h2(db, owner):
    """T2 x retire: the receipt is a fact, the pin gates the release.

    Order 1 settles first (successor ready) and off is deferred; order 2 retires
    first (withdrawn/retiring) and the late T2 still records fact/cost on the
    frozen generation with no new pin or slot resolution.  The pin stays until
    the successor quiesces, so the slot is never released early.
    """
    service, admin = db.connect("service"), db.connect("admin")
    try:
        for reverse in (False, True):
            evidence, graph, holder_role, waiter_role, order, value = _h2_order(
                db, owner, service, admin, reverse=reverse)
            tag = "G6-H2-order2" if reverse else "G6-H2"
            _print_order(
                tag, evidence, graph, holder_role, waiter_role, order, value,
                "T2 records the exact receipt and one frozen-generation "
                "successor; off only withdraws and stays deferred while the "
                "run pin lives; the pin drains before the slot is released")
    finally:
        service.close()
        admin.close()


def _h3_order(db, owner, service, admin, *, reverse):
    tag = "G6-H3-order2" if reverse else "G6-H3"
    fixture = _claimed_model_fixture(owner, service, admin, tag)
    before = snapshot(owner)
    receipt = _t2_receipt(fixture["token"])
    settle_action = lambda conn: advance(conn, fixture["model"], receipt)
    dispose_action = lambda conn: one(
        conn, "SELECT v24.dispose(%s,%s)",
        (fixture["entry"]["install"], f"{tag}-dispose1-{uuid4()}"))
    if reverse:
        first, second, evidence, graph = first_then_second(
            db, admin, service, dispose_action, settle_action, tag)
        dispose_response, settle_response = first, second
        holder_role, waiter_role, order = "admin", "service", "dispose->settle"
    else:
        first, second, evidence, graph = first_then_second(
            db, service, admin, settle_action, dispose_action, tag)
        settle_response, dispose_response = first, second
        holder_role, waiter_role, order = "service", "admin", "settle->dispose"
    continuation = md5_uuid(f"{fixture['model']}:continuation")
    assert settle_response.get("disposition") == "committed", settle_response
    assert settle_response["emitted"] == [continuation], settle_response
    assert dispose_response.get("disposition") == "committed", dispose_response
    assert dispose_response["emitted"] == [], dispose_response

    settled_model = effect_row(owner, fixture["model"])
    assert settled_model["status"] == "succeeded", settled_model
    assert settled_model["outcome"] == receipt, settled_model
    assert settled_model["resource_quiesced_at"] is not None, settled_model
    assert effect_row(owner, continuation)["status"] == "ready"
    run = run_binding(owner, fixture["run"])
    assert run["status"] == "running" and run["turn_no"] == 1, run
    assert _one_pin(owner, fixture["run"], tag)["released_at"] is None
    staged_install = install_row(owner, fixture["entry"]["install"])
    assert staged_install["state"] == "dispose_pending", staged_install
    assert staged_install["disposed_at"] is None, staged_install
    assert fiber_row(owner, fixture["entry"]["fiber"])["disposed_at"] is None
    staged_slot = slot_row(owner, fixture["entry"]["slot"])
    assert staged_slot["withdrawn_at"] is not None, staged_slot
    assert staged_slot["released_at"] is None, staged_slot
    assert episode_row(owner, fixture["entry"]["episode"])["state"] == "retiring"
    assert one(owner, "SELECT count(*) FROM v24.effects WHERE kind='host_release' "
                      "AND request->>'install_id'=%s",
               (str(fixture["entry"]["install"]),)) == 0

    # The late T2 did not revive the install: still pending, still no tombstone.
    assert install_row(owner, fixture["entry"]["install"])["state"] == "dispose_pending"
    assert install_row(owner, fixture["entry"]["install"])["disposed_at"] is None

    _settle_final(service, continuation)
    completed = run_binding(owner, fixture["run"])
    assert completed["status"] == "completed", completed
    released_pin = _one_pin(owner, fixture["run"], tag)
    assert released_pin["released_at"] is not None, released_pin
    assert install_row(owner, fixture["entry"]["install"])["state"] == "dispose_pending"
    assert install_row(owner, fixture["entry"]["install"])["disposed_at"] is None

    _drain_disposed(owner, service, admin, fixture, tag)
    disposed_after_pin = one(
        owner, "SELECT i.disposed_at >= p.released_at FROM v24.installs i "
               "JOIN v24.pins p ON p.pin_id=%s WHERE i.install_id=%s",
        (fixture["pin"]["pin_id"], fixture["entry"]["install"]))
    assert disposed_after_pin is True
    after = snapshot(owner)
    value = diff(before, after)
    assert_diff_exact(value, {
        "effects": (6, 1, 0), "episodes": (0, 1, 0), "events": (11, 0, 0),
        "fibers": (0, 1, 0), "installs": (0, 1, 0), "pins": (0, 1, 0),
        "requests": (3, 0, 0), "runs": (0, 1, 0), "slots": (0, 1, 0),
    }, tag)
    return evidence, graph, holder_role, waiter_role, order, value


def g6_h3(db, owner):
    """T2 x dispose: external results never revive the install.

    Order 1 settles first (successor ready) and dispose only pends/retires;
    order 2 disposes first and the late T2 still records fact/cost without
    reviving the install.  Both drain off -> new-key dispose -> host_release,
    and disposed_at is written only after the effect/pin debt is quiesced.
    """
    service, admin = db.connect("service"), db.connect("admin")
    try:
        for reverse in (False, True):
            evidence, graph, holder_role, waiter_role, order, value = _h3_order(
                db, owner, service, admin, reverse=reverse)
            tag = "G6-H3-order2" if reverse else "G6-H3"
            _print_order(
                tag, evidence, graph, holder_role, waiter_role, order, value,
                "T2 records the exact receipt and one ready successor while "
                "dispose remains dispose_pending; the late result never revives "
                "the install and disposed_at follows pin release and host_release")
    finally:
        service.close()
        admin.close()


# ---------------------------------------------------------------------------
# G6-L1..L5: §B.2 lock-order / deadlock audits
# ---------------------------------------------------------------------------

def _assert_g_only(evidence, graph, tag):
    """The waiter queues on G alone: exactly the holder blocks it, no cycle.

    ``wait_for_g_block``/``assert_no_wait_cycle`` have already rejected any
    granted v24 relation/tuple write lock and any non-G wait on the waiter; the
    assertions here pin the exact two-node shape down for the L evidence.
    """
    holder_pid, waiter_pid = evidence["holder_pid"], evidence["waiter_pid"]
    assert evidence["blocking_pids"] == "{%d}" % holder_pid, (tag, evidence)
    assert evidence["ungranted_advisory"] >= 1, (tag, evidence)
    assert graph["wait_graph"].get(waiter_pid) == [holder_pid], (tag, graph)
    assert graph["wait_graph"].get(holder_pid) == [], (tag, graph)
    assert graph["cycle"] is False and graph["advisory_only"] is True, (tag, graph)


def _l1_order(db, owner, service, admin, *, reverse):
    """start x dispose: the two N1 orders, audited for a G-only wait.

    Order a: the start returns holding G and its committed run pin defers the
    queued dispose.  Order b: a drained install is disposed first (G held), so
    the queued start is ``provider_unavailable`` W1.  Neither waiter takes a
    v24 relation/tuple lock before G and the wait-for graph stays a single
    holder -> waiter edge.
    """
    tag = "G6-L1b" if reverse else "G6-L1a"
    entry = _b_fixture(owner, service, admin)
    if reverse:
        drained = one(admin, "SELECT v24.fiber_control(%s,'off',1,%s)",
                      (entry["fiber"], f"{tag}-drain-{uuid4()}"))
        admin.commit()
        assert drained.get("disposition") == "committed", drained
    before = snapshot(owner)
    start_key = f"{tag}-start-{uuid4()}"
    dispose_key = f"{tag}-dispose-{uuid4()}"
    start_action = lambda conn: start_once(conn, entry, requires=("dep",),
                                           key=start_key)
    dispose_action = lambda conn: one(conn, "SELECT v24.dispose(%s,%s)",
                                      (entry["install"], dispose_key))
    if reverse:
        dispose_response, start_response, evidence, graph = first_then_second(
            db, admin, service, dispose_action, start_action, tag)
        holder_role, waiter_role, order = "admin", "service", "dispose->start"
    else:
        start_response, dispose_response, evidence, graph = first_then_second(
            db, service, admin, start_action, dispose_action, tag)
        holder_role, waiter_role, order = "service", "admin", "start->dispose"
    _assert_g_only(evidence, graph, tag)

    if reverse:
        assert dispose_response.get("disposition") == "committed", dispose_response
        assert len(dispose_response["emitted"]) == 1, dispose_response
        assert start_response == {"v": 1, "error": {
            "code": "provider_unavailable", "detail": {}}}, start_response
    else:
        assert start_response.get("disposition") == "committed", start_response
        run_id = start_response["emitted"][0]
        assert dispose_response.get("disposition") == "committed", dispose_response
        assert dispose_response["emitted"] == [], dispose_response
        install = install_row(owner, entry["install"])
        assert install["state"] == "dispose_pending", install
        assert install["disposed_at"] is None, install
        assert fiber_row(owner, entry["fiber"])["disposed_at"] is None
        live = pin_rows(owner, "consumer_run_id=%s AND released_at IS NULL", (run_id,))
        assert len(live) == 1 and live[0]["consumer_type"] == "run", live
    after = snapshot(owner)
    return (tag, evidence, graph, holder_role, waiter_role, order,
            diff(before, after))


def g6_l1(db, owner):
    """L1: start locks its fiber while dispose locks the install (both orders).

    Each order prints one result plus one lock line; the shared
    ``first_then_second`` body proves the G wait, rejects product locks and
    builds the wait-for graph before the holder commits.
    """
    service, admin = db.connect("service"), db.connect("admin")
    try:
        for reverse in (False, True):
            tag, evidence, graph, holder_role, waiter_role, order, value = _l1_order(
                db, owner, service, admin, reverse=reverse)
            verdict = (
                "dispose is tombstone-first and the queued start is "
                "provider_unavailable W1; waiter blocked only on G, no product "
                "lock, no cycle, winner=G" if reverse else
                "the start's run pin defers dispose; dispose_pending, no "
                "tombstone; waiter blocked only on G, no product lock, no cycle, "
                "winner=G")
            _print_order(tag, evidence, graph, holder_role, waiter_role, order,
                         value, verdict)
    finally:
        service.close()
        admin.close()


def g6_l2(db, owner):
    """L2: cancel takes the run first, retire takes the fiber first (both orders).

    The reused C2 body proves the pin is still live after both commands and is
    released only once the claimed tool effect goes silent; the extra audit
    here pins the wait edge to G alone.
    """
    service, admin = db.connect("service"), db.connect("admin")
    try:
        for reverse in (False, True):
            tag = "G6-L2b" if reverse else "G6-L2a"
            evidence, graph, holder_role, waiter_role, order, value = _c2_order(
                db, owner, service, admin, reverse=reverse, tag=tag)
            _assert_g_only(evidence, graph, tag)
            verdict = (
                "retire queues second on G only; cancel then seals the run while "
                "the claimed-tool pin survives; the pin is released only after "
                "that in-flight effect settles, then the second off releases the "
                "slot and closes the episode; no cycle, winner=G" if reverse else
                "cancel holds G and seals the run but the claimed-tool pin keeps "
                "the retire stage at withdrawn/unreleased; the pin is released "
                "only after that in-flight effect settles; waiter blocked only on "
                "G, no run-pin/fiber row lock, no cycle, winner=G")
            _print_order(tag, evidence, graph, holder_role, waiter_role, order,
                         value, verdict)
    finally:
        service.close()
        admin.close()


def _l3_order(db, owner, first_conn, second_conn, *, reverse):
    """cancel(parent) x cancel(child) on a service and an admin connection."""
    tag = "G6-L3b" if reverse else "G6-L3a"
    realm = f"g6-l3-{uuid4()}"
    parent = make_parent(owner, first_conn, realm,
                         {"steps": 5, "tool_calls": 3, "tokens": 5000,
                          "wall_ms": 600000})
    args = spawn_args(parent["scope_id"], f"{tag}-child-{uuid4()}",
                      {"steps": 2, "tokens": 300, "tool_calls": 1,
                       "wall_ms": 5000})
    spawned = settle_spawn(first_conn, parent, args, usage=usage_for(parent))
    assert spawned.get("disposition") == "committed", spawned
    assert len(spawned["spawned"]) == 1, spawned
    child_run = spawned["spawned"][0]["run_id"]
    assert one(owner, "SELECT count(*) FROM v24.runs WHERE run_id=%s "
                      "AND parent_run_id=%s", (child_run, parent["run_id"])) == 1
    owner.rollback()
    parent_row = run_binding(owner, parent["run_id"])
    child_row = run_binding(owner, child_run)
    assert parent_row["status"] == "running", parent_row
    assert child_row["status"] == "running", child_row
    parent_generation = parent_row["driving_generation"]
    child_generation = child_row["driving_generation"]
    before = snapshot(owner)
    parent_cancel = lambda conn: cancel(
        conn, parent["run_id"], parent_generation,
        f"{tag}-cancel-parent-{uuid4()}")[0]
    child_cancel = lambda conn: cancel(
        conn, child_run, child_generation, f"{tag}-cancel-child-{uuid4()}")[0]
    if reverse:
        child_response, parent_response, evidence, graph = first_then_second(
            db, second_conn, first_conn, child_cancel, parent_cancel, tag)
        holder_role, waiter_role, order = "admin", "service", "child->parent"
    else:
        parent_response, child_response, evidence, graph = first_then_second(
            db, first_conn, second_conn, parent_cancel, child_cancel, tag)
        holder_role, waiter_role, order = "service", "admin", "parent->child"
    _assert_g_only(evidence, graph, tag)
    for label, response in (("parent", parent_response),
                            ("child", child_response)):
        assert response.get("disposition") == "committed", (label, response)
        assert response["emitted"] == [], (label, response)
    after = snapshot(owner)
    value = diff(before, after)
    parent_row = run_binding(owner, parent["run_id"])
    child_row = run_binding(owner, child_run)
    assert parent_row["status"] == "cancelled", parent_row
    assert child_row["status"] == "cancelled", child_row
    assert parent_row["ended_at"] is not None, parent_row
    assert child_row["ended_at"] is not None, child_row
    assert parent_row["close_intent"]["kind"] == "cancel", parent_row
    assert child_row["close_intent"]["kind"] == "cancel", child_row
    return (tag, evidence, graph, holder_role, waiter_role, order, value)


def g6_l3(db, owner):
    """L3: spawn parent/child vs cancel parent/child in both orders.

    The parent run is cancelled by its ``service`` owner and the spawned child
    (which has no ``command_start`` effect, so ``run_owner`` is NULL) by the
    ``v24_admin`` protocol-owner bypass; both callers hold a real connection,
    so the second cancel queues on G only rather than on the other run's row.
    """
    service, admin = db.connect("service"), db.connect("admin")
    try:
        for reverse in (False, True):
            tag, evidence, graph, holder_role, waiter_role, order, value = _l3_order(
                db, owner, service, admin, reverse=reverse)
            _print_order(
                tag, evidence, graph, holder_role, waiter_role, order, value,
                "the parent/child cancel pair is serialized on G; the waiter "
                "holds no v24 run/row lock before G, no blocking-pids cycle, "
                "both runs end cancelled, winner=G")
    finally:
        service.close()
        admin.close()


def _l4_order(db, owner, service, admin, *, reverse):
    """Two independent provider switches released in A->B and B->A order."""
    tag = "G6-L4b" if reverse else "G6-L4a"
    _root_a, _owner_a, a = pin_barrier_fixture(owner, service, admin)
    _root_b, _owner_b, b = pin_barrier_fixture(owner, service, admin)
    for label, fixture in (("A", a), ("B", b)):
        slot = slot_row(owner, fixture["slot"])
        assert slot["withdrawn_at"] is None and slot["released_at"] is None, (
            label, slot)
        assert episode_row(owner, fixture["episode"])["state"] == "active", label
        assert pin_rows(owner, "slot_id=%s AND released_at IS NULL",
                        (fixture["slot"],)) == [], label
    before = snapshot(owner)
    off_a = lambda conn: one(conn, "SELECT v24.fiber_control(%s,'off',1,%s)",
                             (a["fiber"], f"{tag}-off-a-{uuid4()}"))
    off_b = lambda conn: one(conn, "SELECT v24.fiber_control(%s,'off',1,%s)",
                             (b["fiber"], f"{tag}-off-b-{uuid4()}"))
    if reverse:
        first, second, evidence, graph = first_then_second(
            db, admin, service, off_b, off_a, tag)
        holder_slot, waiter_slot = b["slot"], a["slot"]
        holder_role, waiter_role, order = "admin", "service", "B->A"
    else:
        first, second, evidence, graph = first_then_second(
            db, service, admin, off_a, off_b, tag)
        holder_slot, waiter_slot = a["slot"], b["slot"]
        holder_role, waiter_role, order = "service", "admin", "A->B"
    _assert_g_only(evidence, graph, tag)
    for label, response in (("holder", first), ("waiter", second)):
        assert response.get("disposition") == "committed", (label, response)
        assert response["emitted"] == [], (label, response)
    holder = slot_row(owner, holder_slot)
    waiter = slot_row(owner, waiter_slot)
    assert holder["withdrawn_at"] is not None, holder
    assert holder["released_at"] is not None, holder
    assert waiter["withdrawn_at"] is not None, waiter
    assert waiter["released_at"] is not None, waiter
    followed = one(
        owner,
        """SELECT s1.withdrawn_at < s2.withdrawn_at
                AND s1.released_at < s2.released_at
             FROM v24.slots s1, v24.slots s2
            WHERE s1.slot_id=%s AND s2.slot_id=%s""",
        (holder_slot, waiter_slot),
    )
    owner.rollback()
    assert followed is True, (tag, holder, waiter)
    after = snapshot(owner)
    return (tag, evidence, graph, holder_role, waiter_role, order,
            diff(before, after))


def g6_l4(db, owner):
    """L4: two provider switches never release slots outside the commit order.

    Each order builds two fresh fiber/slot fixtures; the second ``off`` queues
    on G before touching any slot, both switches commit, and the holder's slot
    is withdrawn/released before the waiter's (commit order, not call order).
    """
    service, admin = db.connect("service"), db.connect("admin")
    try:
        for reverse in (False, True):
            tag, evidence, graph, holder_role, waiter_role, order, value = _l4_order(
                db, owner, service, admin, reverse=reverse)
            _print_order(
                tag, evidence, graph, holder_role, waiter_role, order, value,
                "the second provider switch waits only on G and grabs no slot "
                "lock first; no cycle; the holder slot is withdrawn/released "
                "before the waiter's, so release order follows commit order; "
                "both slots withdrawn, winner=G")
    finally:
        service.close()
        admin.close()


def _l5_order(db, owner, service, admin, *, reverse):
    """respond x cancel, audited as "interaction is not a separate lock object"."""
    tag = "G6-L5b" if reverse else "G6-L5a"
    assert one(owner, """SELECT count(*) FROM pg_class c
                          WHERE c.relnamespace='v24'::regnamespace
                            AND c.relname='interactions'""") == 0
    owner.rollback()
    assert one(owner, """SELECT count(*) FROM information_schema.columns
                          WHERE table_schema='v24' AND table_name='runs'
                            AND column_name='interaction'""") == 1
    owner.rollback()
    evidence, graph, holder_role, waiter_role, order, value = _n2_order(
        db, owner, service, admin, reverse=reverse, tag=tag, emit=False)
    _assert_g_only(evidence, graph, tag)
    return (tag, evidence, graph, holder_role, waiter_role, order, value)


def g6_l5(db, owner):
    """L5: respond vs cancel; the interaction is a projection on the run row.

    There is no ``v24.interactions`` relation to lock separately.  Both orders
    reuse the N2 body: the blocked participant queues on G alone, takes no
    v24 relation/tuple lock before G, and the wait-for graph has no cycle.
    """
    service, admin = db.connect("service"), db.connect("admin")
    try:
        for reverse in (False, True):
            tag, evidence, graph, holder_role, waiter_role, order, value = _l5_order(
                db, owner, service, admin, reverse=reverse)
            verdict = (
                "cancel holds G first; the blocked respond is already_terminal "
                "W1; there is no v24.interactions relation and the waiter takes "
                "no interaction table/row lock, no cycle, winner=G" if reverse else
                "respond holds G first and consumes the interaction; the queued "
                "cancel archives the one ready successor; there is no "
                "v24.interactions relation and the waiter takes no interaction "
                "table/row lock, no cycle, winner=G")
            _print_order(tag, evidence, graph, holder_role, waiter_role, order,
                         value, verdict)
    finally:
        service.close()
        admin.close()


# ---------------------------------------------------------------------------
# Registry / CLI
# ---------------------------------------------------------------------------

ASSERTIONS = {
    "g6_a1": ("G6-A1", g6_a1),
    "g6_b1": ("G6-B1", g6_b1),
    "g6_b2": ("G6-B2", g6_b2),
    "g6_b3": ("G6-B3", g6_b3),
    "g6_c1": ("G6-C1", g6_c1),
    "g6_c2": ("G6-C2", g6_c2),
    "g6_c3": ("G6-C3", g6_c3),
    "g6_d1": ("G6-D1", g6_d1),
    "g6_e1": ("G6-E1", g6_e1),
    "g6_f1": ("G6-F1", g6_f1),
    "g6_g1": ("G6-G1", g6_g1),
    "g6_g2": ("G6-G2", g6_g2),
    "g6_g3": ("G6-G3", g6_g3),
    "g6_h1": ("G6-H1", g6_h1),
    "g6_h2": ("G6-H2", g6_h2),
    "g6_h3": ("G6-H3", g6_h3),
    "g6_n1": ("G6-N1", g6_n1),
    "g6_n2": ("G6-N2", g6_n2),
    "g6_n3": ("G6-N3", g6_n3),
    "g6_n4": ("G6-N4", g6_n4),
    "g6_n5": ("G6-N5", g6_n5),
    "g6_n6": ("G6-N6", g6_n6),
    "g6_n7": ("G6-N7", g6_n7),
    "g6_n8": ("G6-N8", g6_n8),
    "g6_n9": ("G6-N9", g6_n9),
    "g6_l1": ("G6-L1", g6_l1),
    "g6_l2": ("G6-L2", g6_l2),
    "g6_l3": ("G6-L3", g6_l3),
    "g6_l4": ("G6-L4", g6_l4),
    "g6_l5": ("G6-L5", g6_l5),
}

GROUPS = {
    "g6_a": ("g6_a1",),
    "g6_b": ("g6_b1", "g6_b2", "g6_b3"),
    "g6_c": ("g6_c1", "g6_c2", "g6_c3"),
    "g6_d": ("g6_d1",),
    "g6_e": ("g6_e1",),
    "g6_f": ("g6_f1",),
    "g6_g": ("g6_g1", "g6_g2", "g6_g3"),
    "g6_h": ("g6_h1", "g6_h2", "g6_h3"),
    "n1": ("g6_n1",),
    "n2": ("g6_n2",), "n3": ("g6_n3",), "n4": ("g6_n4",), "n5": ("g6_n5",),
    "n6": ("g6_n6",), "n7": ("g6_n7",), "n8": ("g6_n8",), "n9": ("g6_n9",),
    "l1": ("g6_l1",), "l2": ("g6_l2",), "l3": ("g6_l3",), "l4": ("g6_l4",),
    "l5": ("g6_l5",),
}

ORDER = ("g6_a1", "g6_b1", "g6_b2", "g6_b3",
         "g6_c1", "g6_c2", "g6_c3", "g6_d1", "g6_e1", "g6_f1",
         "g6_g1", "g6_g2", "g6_g3", "g6_h1", "g6_h2", "g6_h3",
         "g6_n1", "g6_n2", "g6_n3", "g6_n4", "g6_n5",
         "g6_n6", "g6_n7", "g6_n8", "g6_n9",
         "g6_l1", "g6_l2", "g6_l3", "g6_l4", "g6_l5")


def resolve_selectors(text):
    """Exact names and group prefixes -> ordered assertion names.

    ``None`` selects the full W2 gate in ``ORDER``.  ``--only`` accepts exact
    assertion names and the ``GROUPS`` prefixes:
    ``--only g6_a,g6_b,g6_c,g6_d,g6_e,g6_f,g6_g,g6_h,n1`` is the W1 matrix
    subset, and ``--only g6_l1,...,g6_l5`` selects the five §B.2 lock audits
    (``GROUPS`` also maps ``l1``..``l5`` to them).  A selection that names an
    assertion this gate does not implement is a hard error: the gate must
    never claim a cell it did not run.
    """
    if text is None:
        return ORDER
    selected = []
    for token in (part.strip() for part in text.split(",")):
        if not token:
            raise SystemExit("--only: empty selector")
        if token in ASSERTIONS:
            names = (token,)
        elif token in GROUPS:
            names = GROUPS[token]
        elif token in ORDER:
            names = (token,)
        else:
            raise SystemExit(f"--only: unknown selector {token!r}")
        for name in names:
            if name not in ASSERTIONS:
                raise SystemExit(
                    f"--only: {token!r} expands to {name!r}, which is not implemented "
                    "in this W2 gate")
            if name not in selected:
                selected.append(name)
    if not selected:
        raise SystemExit("--only: no assertions selected")
    return tuple(sorted(selected, key=ORDER.index))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="v24 S7 G6 concurrency gate (W2 full gate)")
    parser.add_argument("--only", default=None,
                        help="comma-separated assertion names or groups, "
                             "e.g. g6_a,g6_b,g6_c,g6_d,g6_e,g6_f,g6_g,g6_h,n1")
    args = parser.parse_args(argv)
    selected = resolve_selectors(args.only)
    install_no_network()
    try:
        with server_helper_scope(), setup_db() as db:
            owner = db.connect()
            with owner.cursor() as cur:
                cur.execute("SET ROLE v24_owner")
            owner.commit()
            for name in selected:
                ASSERTIONS[name][1](db, owner)
            _assert_closed_catalog(owner)
            owner.close()
    finally:
        restore_no_network()
    if args.only is None:
        print("[passed] v24 S7 W1-W2 G6-A…H + N1-N9 + L1-L5: "
              f"{','.join(ORDER)}")
    else:
        print(f"[passed] v24 S7 G6 checkpoint subset ({len(selected)} selected): "
              f"{','.join(selected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
