"""Same expanded scenario for every facade. Observations come from PostgreSQL."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from control import EXPORTS, Control, RevisionConflict, TransactionError, file_digest

MESSAGE = "draft a plan for the migration"


def _probe_closed_world(control: Control) -> dict[str, bool]:
    control.begin()
    model_rejected = False
    file_rejected = False
    try:
        try:
            control.call_model("probe")
        except TransactionError:
            model_rejected = True
        try:
            control.write_export("probe", b"x")
        except TransactionError:
            file_rejected = True
        try:
            control.read_export("probe")
        except TransactionError:
            read_rejected = True
        else:
            read_rejected = False
    finally:
        control.rollback()
    return {
        "model_inside_transaction_rejected": model_rejected,
        "file_write_inside_transaction_rejected": file_rejected,
        "file_read_inside_transaction_rejected": read_rejected,
    }


def _count_events(dsn: str, session_id: str) -> int:
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*) FROM events
                WHERE session_id = %s OR workflow_run_id = %s OR run_id = %s
                   OR run_id IN (
                        SELECT run_id FROM alias_runs WHERE session_id = %s
                        UNION
                        SELECT run_id FROM external_runs WHERE external_id = %s
                        UNION
                        SELECT run_id FROM runs WHERE workflow_run_id = %s
                   )
                """,
                (session_id, session_id, session_id, session_id, session_id, session_id),
            )
            return cur.fetchone()[0]
    finally:
        conn.close()


def _sql_identity(dsn: str, design_id: str, session_id: str) -> dict[str, Any]:
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if design_id == "workflow_container":
                cur.execute(
                    """
                    SELECT workflow_run_id, current_run_id, revision
                    FROM workflow_runs WHERE workflow_run_id = %s
                    """,
                    (session_id,),
                )
            elif design_id == "thin_adapter":
                cur.execute(
                    """
                    SELECT session_id, current_run_id, revision
                    FROM session_aliases WHERE session_id = %s
                    """,
                    (session_id,),
                )
            elif design_id == "session_object":
                cur.execute(
                    """
                    SELECT session_id, workflow_run_id, status
                    FROM sessions WHERE session_id = %s
                    """,
                    (session_id,),
                )
            else:
                cur.execute(
                    """
                    SELECT external_id, run_id, status
                    FROM external_ids WHERE external_id = %s
                    """,
                    (session_id,),
                )
            row = cur.fetchone()
            cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'sessions'
                ORDER BY column_name
                """
            )
            session_columns = [item["column_name"] for item in cur.fetchall()]
            cur.execute(
                """
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'events_session_id_idx'
                """
            )
            indexed = cur.fetchone() is not None
        return {
            "row": None if row is None else dict(row),
            "session_columns": session_columns,
            "events_session_indexed": indexed,
        }
    finally:
        conn.close()


def _probe_wait(facade: Any, session_id: str) -> dict[str, Any]:
    view = facade.view(session_id)
    revision = view["revision"]
    generation = view["owner_generation"]
    run_id = view["run_id"]

    def produce() -> None:
        side = Control(facade.control.dsn)
        try:
            side.execute(
                "steer",
                {
                    "request_id": side.new_id("req"),
                    "run_id": run_id,
                    "message": "wake",
                    "expected_revision": revision,
                    "owner_generation": generation,
                    "session_id": session_id,
                },
            )
        finally:
            side.close()

    return facade.control.wait_for(run_id, revision, produce)


def _probe_cas(facade: Any, session_id: str) -> dict[str, Any]:
    view = facade.view(session_id)
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def attempt(message: str) -> None:
        side = Control(facade.control.dsn)
        try:
            barrier.wait(5)
            side.execute(
                "steer",
                {
                    "request_id": side.new_id("req"),
                    "run_id": view["run_id"],
                    "message": message,
                    "expected_revision": view["revision"],
                    "owner_generation": view["owner_generation"],
                    "session_id": session_id,
                },
            )
            with lock:
                outcomes.append("committed")
        except RevisionConflict:
            with lock:
                outcomes.append("conflict")
        finally:
            side.close()

    threads = [
        threading.Thread(target=attempt, args=("cas-a",)),
        threading.Thread(target=attempt, args=("cas-b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return {
        "outcomes": sorted(outcomes),
        "one_commit_one_conflict": sorted(outcomes) == ["committed", "conflict"],
    }


def _probe_recover(facade: Any, session_id: str) -> dict[str, Any]:
    view = facade.view(session_id)
    dead_pid = facade.control.abandon_owner()
    recovered = facade.control.execute(
        "recover_owner",
        {
            "request_id": facade.control.new_id("req"),
            "run_id": view["run_id"],
            "seen_generation": view["owner_generation"],
            "session_id": session_id,
        },
    )
    old_rejected = False
    try:
        facade.control.execute(
            "steer",
            {
                "request_id": facade.control.new_id("req"),
                "run_id": view["run_id"],
                "message": "stale owner",
                "expected_revision": recovered["revision"],
                "owner_generation": view["owner_generation"],
                "session_id": session_id,
            },
        )
    except RevisionConflict:
        old_rejected = True
    fresh = facade.control.fetch_run(view["run_id"])
    new_steer = facade.control.execute(
        "steer",
        {
            "request_id": facade.control.new_id("req"),
            "run_id": view["run_id"],
            "message": "new owner",
            "expected_revision": fresh["revision"],
            "owner_generation": recovered["owner_generation"],
            "session_id": session_id,
        },
    )
    return {
        "dead_pid": dead_pid,
        "old_fence_rejected": old_rejected,
        "new_owner_steer_committed": new_steer["status"] == "running",
        "owner_generation": new_steer["owner_generation"],
    }


def run_scenario(facade: Any) -> dict[str, Any]:
    control = facade.control
    probes = _probe_closed_world(control)
    created = facade.create_session(message=MESSAGE)
    started = facade.start(session_id=created["session_id"], message=MESSAGE)
    session_id = created["session_id"]
    exported = facade.export_plan(session_id=session_id)
    facade.steer(session_id=session_id, message="narrow the plan")
    polled = facade.poll(session_id=session_id)
    waited = _probe_wait(facade, session_id)
    needs = facade.drive_to_needs_input(session_id=session_id)
    responded = facade.respond(session_id=session_id, message="use expand-contract")
    cas = _probe_cas(facade, session_id)
    recovered = _probe_recover(facade, session_id)
    cited = facade.cite(session_id=session_id, digest=exported["digest"])
    before = facade.view(session_id)
    resumed = facade.resume_session(session_id=session_id)
    after = facade.view(session_id)
    macro = facade.build_macro()
    log = facade.get_log(session_id=session_id)
    handoff = facade.extract_handoff(session_id=session_id)
    sessions = facade.list_sessions()
    export_matched = file_digest_matches(exported)
    events_before = _count_events(control.dsn, session_id)
    facade.stop_session(session_id=session_id)
    cleanup = facade.cleanup_sessions(session_id=session_id)
    events_after = _count_events(control.dsn, session_id)
    identity = _sql_identity(control.dsn, facade.design_id, session_id)
    export_path = EXPORTS.parent / exported["path"]
    artifact_remains = False
    conn = psycopg2.connect(control.dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT path FROM artifacts WHERE digest = %s",
                (exported["digest"],),
            )
            artifact_remains = cur.fetchone() is not None
            cur.execute(
                "SELECT count(*) FROM macro_workflows WHERE macro_id = %s",
                (macro["macro_id"],),
            )
            macro_links = cur.fetchone()[0]
    finally:
        conn.close()
    return {
        "design_id": facade.design_id,
        "title": facade.title,
        "repair_note": facade.repair_note,
        "probes": probes,
        "resume": {
            "before": {"session_id": session_id, "run_id": before["run_id"]},
            "after": {"session_id": session_id, "run_id": after["run_id"]},
            "session_id_stable": session_id == resumed["session_id"] == after["session_id"],
            "run_id_changed": before["run_id"] != resumed["run_id"],
            "parent_run_id": resumed.get("parent_run_id"),
            "listed": session_id in sessions,
        },
        "poll_wait": {
            "polled_revision": polled["revision"],
            **waited,
        },
        "cas": cas,
        "recover_owner": recovered,
        "citation": cited,
        "handoff": handoff,
        "log_count": len(log["entries"]),
        "needs_status": needs["status"],
        "responded_status": responded["status"],
        "started_run_id": started["run_id"],
        "macro": macro,
        "macro_links": macro_links,
        "event_retention": {
            "events_before": events_before,
            "events_after": events_after,
            "events_retained": events_after >= events_before and events_after > events_before,
            "tombstone_via": cleanup["tombstone_via"],
            "kernel_verb_rejected": cleanup["kernel_verb_rejected"],
        },
        "workspace_export": {
            "path": exported["path"],
            "digest": exported["digest"],
            "file_exists": export_path.exists(),
            "bytes_cleared": export_path.exists() and export_path.stat().st_size == 0,
            "artifact_row_remains": artifact_remains,
            "digest_matched_file_before_cleanup": export_matched,
        },
        "postgres_readback": identity,
    }


def file_digest_matches(exported: dict[str, Any]) -> bool:
    path = Path(exported["path"])
    if not path.is_absolute():
        path = EXPORTS.parent / exported["path"]
    if not path.exists() or path.stat().st_size == 0:
        return False
    return file_digest(path) == exported["digest"]
