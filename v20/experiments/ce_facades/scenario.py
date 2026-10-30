"""One scenario, four facades. Observations come from Control's commit log."""

from __future__ import annotations

from typing import Any, Callable

from substrate import CitationError, TransactionError

MESSAGE = "draft a plan for the migration"
RESPOND_MESSAGE = "use expand-contract"


def _probe_closed_world(control: Any) -> dict[str, bool]:
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
            file_read_rejected = True
        else:
            file_read_rejected = False
    finally:
        control.rollback()
    return {
        "model_inside_transaction_rejected": model_rejected,
        "file_write_inside_transaction_rejected": file_rejected,
        "file_read_inside_transaction_rejected": file_read_rejected,
    }


def _phase(control: Any, fn: Callable[[], Any]) -> tuple[Any, list[dict[str, Any]]]:
    start = len(control.tx_log)
    value = fn()
    txs = [dict(tx) for tx in control.tx_log[start:]]
    return value, txs


def _resume_start_refs(control: Any, run_id: str) -> list[str]:
    for event in control.events:
        if event.get("kind") == "start" and event.get("run_id") == run_id:
            return list(event.get("artifact_refs") or [])
    return []


def _workflow_inputs(control: Any, session_id: str) -> list[str]:
    refs: list[str] = []
    steps = [
        step
        for step in control.workflow_steps.values()
        if step["workflow_run_id"] == session_id
    ]
    steps.sort(key=lambda step: step["seq"])
    for step in steps:
        for ref in step["input_artifact_refs"]:
            if ref not in refs:
                refs.append(ref)
    return refs


def run_scenario(facade: Any) -> dict[str, Any]:
    control = facade.control
    probes = _probe_closed_world(control)

    created, tx_create = _phase(
        control, lambda: facade.create_session(message=MESSAGE)
    )
    started, tx_start = _phase(
        control,
        lambda: facade.start(
            session_id=created["session_id"],
            message=MESSAGE,
            request_id=created.get("start_request_id"),
        ),
    )
    session_id = started["session_id"]

    plan, tx_plan = _phase(
        control, lambda: facade.accept_model_plan(session_id=session_id)
    )
    digest = plan["digest"]

    marker = len(control.tx_log)
    unknown_rejected = False
    try:
        facade.run_citing_step(session_id=session_id, digest="0" * 64)
    except CitationError:
        unknown_rejected = True
    unknown_digest_tx_count = len(control.tx_log) - marker

    steered, tx_steer = _phase(
        control,
        lambda: facade.steer(session_id=session_id, message="focus on cutover"),
    )
    needs, tx_needs = _phase(
        control, lambda: facade.drive_to_needs_input(session_id=session_id)
    )
    responded, tx_respond = _phase(
        control,
        lambda: facade.respond(session_id=session_id, message=RESPOND_MESSAGE),
    )
    cited, tx_cite = _phase(
        control, lambda: facade.run_citing_step(session_id=session_id, digest=digest)
    )

    before = facade.view(session_id)
    resumed, tx_resume = _phase(
        control, lambda: facade.resume_session(session_id=session_id)
    )
    after_id = resumed["session_id"]
    after = facade.view(after_id)
    parent_run_id = control.runs[after["run_id"]].get("parent_run_id")

    log = facade.get_log(session_id=after_id)
    handoff = facade.extract_handoff(session_id=after_id)
    sessions = facade.list_sessions()

    stopped, tx_stop = _phase(
        control, lambda: facade.stop_session(session_id=after_id)
    )
    ids_before = [event["event_id"] for event in control.events]
    cleaned, tx_cleanup = _phase(
        control, lambda: facade.cleanup_sessions(session_id=after_id)
    )
    ids_after = [event["event_id"] for event in control.events]
    removed = [event_id for event_id in ids_before if event_id not in set(ids_after)]
    tombstones = [
        event for event in control.events if event.get("kind") == "purge_tombstone"
    ]
    exports_dropped = bool(control.exports) and all(
        value == b"" for value in control.exports.values()
    )
    session_chain = []
    if after_id in control.sessions:
        session_chain = list(control.sessions[after_id]["artifact_chain"])
    elif before["session_id"] in control.sessions:
        session_chain = list(control.sessions[before["session_id"]]["artifact_chain"])

    phases = {
        "create_session": tx_create,
        "start": tx_start,
        "model_plan": tx_plan,
        "steer": tx_steer,
        "needs_input": tx_needs,
        "respond": tx_respond,
        "cite": tx_cite,
        "resume": tx_resume,
        "stop": tx_stop,
        "cleanup": tx_cleanup,
    }
    resume = {
        "before": before,
        "after": after,
        "session_id_stable": before["session_id"] == after["session_id"],
        "run_id_changed": before["run_id"] != after["run_id"],
        "session_id_equals_run_id_after": after["session_id"] == after["run_id"],
        "parent_run_id": parent_run_id,
        "kernel_session_rows": len(control.sessions),
        "kernel_workflow_rows": len(control.workflow_runs),
        "profile_loaded": bool(getattr(facade, "loaded", False)),
        "external_session_id_unchanged": before["session_id"] == after["session_id"],
    }
    citation = {
        "authority": cited["authority"],
        "digest": digest,
        "accepted": True,
        "unknown_digest_rejected": unknown_rejected,
        "unknown_digest_tx_count": unknown_digest_tx_count,
        "folded_on_read": bool(handoff.get("folded_on_read")),
        "evidence": {
            "caller_bundle": facade.caller_bundle(after_id),
            "session_chain": session_chain,
            "workflow_step_inputs": _workflow_inputs(
                control, after_id if after_id in control.workflow_runs else before["session_id"]
            ),
            "resume_run_start_refs": _resume_start_refs(control, after["run_id"]),
        },
    }
    retention = {
        "events_retained": removed == [],
        "event_ids_removed": removed,
        "event_count_before": len(ids_before),
        "event_count_after": len(ids_after),
        "events_deleted": len(removed),
        "tombstone_appended": len(tombstones) >= 1,
        "purge_tombstones": len(tombstones),
        "tombstone_via": cleaned["tombstone_via"],
        "kernel_verb_rejected": cleaned["kernel_verb_rejected"],
        "kernel_cleanup_verb": cleaned["kernel_cleanup_verb"],
        "exports_dropped": exports_dropped,
        "session_rows": len(control.sessions),
        "workflow_rows": len(control.workflow_runs),
        "cleanup_verbs": [verb for tx in tx_cleanup for verb in tx["verbs"]],
        "workflow_row_present": len(control.workflow_runs) >= 1,
        "session_row_present": len(control.sessions) >= 1,
    }
    return {
        "design_id": facade.design_id,
        "title": facade.title,
        "module": facade.__class__.__module__,
        "probes": probes,
        "resume": resume,
        "transaction_writes": {"phases": phases},
        "artifact_citation": citation,
        "event_retention": retention,
        "caller_view": {
            "log_count": len(log["entries"]),
            "handoff_refs": list(handoff["artifact_refs"]),
            "session_ids": list(sessions),
            "folded_on_read": bool(handoff.get("folded_on_read")),
        },
        "unused_observations": {
            "created_session_id": created["session_id"],
            "steered_run_id": steered.get("run_id"),
            "needs_status": needs.get("status"),
            "responded_status": responded.get("status"),
            "stopped": stopped.get("status") or stopped.get("transition"),
        },
    }
