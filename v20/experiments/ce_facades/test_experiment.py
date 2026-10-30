"""CE facade experiment gate. Exit 0 when all four designs finish and diverge."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

REQUIRED = (
    "substrate.py",
    "thin_adapter.py",
    "workflow_container.py",
    "session_object.py",
    "unloadable_profile.py",
    "scenario.py",
    "run_experiment.py",
    "test_experiment.py",
)

DESIGN_IDS = (
    "thin_adapter",
    "workflow_container",
    "session_object",
    "unloadable_profile",
)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check_sources() -> None:
    for name in REQUIRED:
        path = ROOT / name
        check(path.is_file(), f"missing {name}")
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    check(
                        not alias.name.split(".")[0] == "v13",
                        f"{name} imports v13",
                    )
                    check(
                        alias.name.split(".")[0]
                        not in {"socket", "sqlite3", "psycopg", "psycopg2", "urllib"},
                        f"{name} imports {alias.name}",
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                root_name = node.module.split(".")[0]
                check(root_name != "v13", f"{name} imports v13")
                check(
                    root_name
                    not in {"socket", "sqlite3", "psycopg", "psycopg2", "urllib", "http"},
                    f"{name} imports {node.module}",
                )


def check_substrate() -> None:
    from substrate import (
        Control,
        EntryError,
        IdempotencyConflict,
        RevisionConflict,
        TransactionError,
        UnknownVerb,
    )
    from unloadable_profile import UnloadableProfile

    control = Control()
    started = control.execute(
        "start", {"request_id": "req_same", "message": "hello", "actor": "caller"}
    )
    replayed = control.execute(
        "start", {"request_id": "req_same", "message": "hello", "actor": "caller"}
    )
    check(replayed["run_id"] == started["run_id"], "idempotent replay changed run")
    check(len(control.events) == 1, "idempotent replay appended an event")
    try:
        control.execute(
            "start", {"request_id": "req_same", "message": "other", "actor": "caller"}
        )
        raise AssertionError("idempotency conflict was accepted")
    except IdempotencyConflict:
        pass
    try:
        control.execute(
            "steer",
            {
                "request_id": "req_stale",
                "run_id": started["run_id"],
                "message": "x",
                "expected_revision": 999,
            },
        )
        raise AssertionError("stale revision was accepted")
    except RevisionConflict:
        pass
    try:
        control.execute("manage_create_session", {"request_id": "req_manage"})
        raise AssertionError("manage verb accepted on the public entry")
    except EntryError:
        pass
    managed = control.execute(
        "manage_create_session",
        {"request_id": "req_manage", "run_id": started["run_id"]},
        entry="agent_manage",
    )
    check(managed["session_id"], "agent_manage did not create a session")
    try:
        control.execute("cleanup", {"request_id": "req_cleanup"})
        raise AssertionError("cleanup verb was accepted")
    except UnknownVerb as exc:
        check(exc.verb == "cleanup", "unexpected verb rejection")
    control.begin()
    try:
        try:
            control.call_model("nope")
            raise AssertionError("model call ran inside a transaction")
        except TransactionError:
            pass
        try:
            control.write_export("nope", b"x")
            raise AssertionError("file write ran inside a transaction")
        except TransactionError:
            pass
    finally:
        control.rollback()
    polled = control.execute(
        "poll", {"request_id": "req_poll", "run_id": started["run_id"]}
    )
    check(polled["run_id"] == started["run_id"], "poll lost the run")
    profile = UnloadableProfile(Control())
    profile.unload()
    try:
        profile.list_sessions()
        raise AssertionError("unloaded profile still served a session read")
    except RuntimeError:
        pass


def _cite_verbs(design: dict) -> tuple[list[str], set[str]]:
    verbs: list[str] = []
    objects: set[str] = set()
    for tx in design["transaction_writes"]["phases"]["cite"]:
        verbs.extend(tx["verbs"])
        objects.update(tx["objects"])
    return verbs, objects


def check_report(report: dict) -> None:
    check("winner" not in report, "report selects a winner")
    check(report.get("note") == "four designs observed; none selected", "note missing")
    designs = report["designs"]
    check(len(designs) == 4, "expected four designs")
    check(
        [item["design_id"] for item in designs] == list(DESIGN_IDS),
        "design order changed",
    )
    check(len({item["module"] for item in designs}) == 4, "designs share a module")

    divergence = report["divergence"]
    for key in (
        "resume_identity",
        "transaction_writes",
        "artifact_citation",
        "event_retention",
    ):
        check(key in divergence, f"divergence missing {key}")
        check(len(divergence[key]) == 4, f"{key} does not cover four designs")

    resume_flags = [
        (
            item["session_id_stable"],
            item["session_id_equals_run_id_after"],
            item["run_id_changed"],
            item["kernel_session_rows"],
            item["kernel_workflow_rows"],
        )
        for item in divergence["resume_identity"]
    ]
    check(len(set(map(json.dumps, resume_flags))) == 4, "resume identity does not diverge")
    thin, workflow, session, profile = divergence["resume_identity"]
    check(thin["session_id_stable"] is False, "thin adapter kept session_id")
    check(thin["session_id_equals_run_id_after"] is True, "thin session_id is not run_id")
    check(thin["parent_run_id"] == thin["run_id_before"], "thin resume dropped parent")
    check(thin["kernel_session_rows"] == 0, "thin adapter wrote a session row")
    check(thin["kernel_workflow_rows"] == 0, "thin adapter wrote a workflow row")
    check(workflow["session_id_stable"] is True, "workflow session_id changed")
    check(workflow["session_id_equals_run_id_after"] is False, "workflow id collapsed to run")
    check(workflow["kernel_workflow_rows"] == 1, "workflow container missing")
    check(workflow["kernel_session_rows"] == 0, "workflow design wrote a session row")
    check(workflow["parent_run_id"] == workflow["run_id_before"], "workflow child lost parent")
    check(session["session_id_stable"] is True, "session id changed across resume")
    check(session["run_id_changed"] is True, "session resume kept current_run_id")
    check(session["kernel_session_rows"] == 1, "session row missing")
    check(session["kernel_workflow_rows"] == 0, "session design wrote a workflow")
    check(profile["session_id_stable"] is True, "external session_id changed")
    check(profile["run_id_changed"] is True, "profile resume kept run_id")
    check(profile["kernel_session_rows"] == 0, "profile wrote a kernel session")
    check(profile["kernel_workflow_rows"] == 0, "profile wrote a workflow")
    check(profile["session_id_after"] != profile["run_id_after"], "external id became a run id")

    shapes = [
        json.dumps(item["resume"], sort_keys=True)
        for item in divergence["transaction_writes"]
    ]
    check(len(set(shapes)) == 4, "resume transactions do not diverge")
    tx = {item["design_id"]: item for item in divergence["transaction_writes"]}
    check(tx["thin_adapter"]["resume"][0]["verbs"] == ["start"], "thin resume is not start")
    check(tx["thin_adapter"]["resume"][0]["profile_writes"] == [], "thin resume wrote a profile")
    check(tx["thin_adapter"]["start"] == [], "thin start was not an idempotent alias")
    check(tx["thin_adapter"]["create_session"][0]["verbs"] == ["start"], "thin create is not start")
    check(
        "runs" in tx["thin_adapter"]["create_session"][0]["objects"],
        "thin create missed the run",
    )
    check(
        tx["workflow_container"]["resume"][0]["verbs"] == ["spawn", "handoff"],
        "workflow resume did not spawn and hand off in one transaction",
    )
    check(
        "workflow_steps" in tx["workflow_container"]["resume"][0]["objects"],
        "workflow resume missed the step",
    )
    check(
        tx["workflow_container"]["start"][0]["verbs"] == ["spawn"],
        "workflow start did not spawn",
    )
    check(
        tx["workflow_container"]["create_session"][0]["verbs"] == ["start"],
        "workflow create did not start a container",
    )
    check(
        "workflow_runs" in tx["workflow_container"]["create_session"][0]["objects"],
        "workflow create missed the container",
    )
    check(
        "runs" not in tx["workflow_container"]["create_session"][0]["objects"],
        "workflow create spawned a run too early",
    )
    check(
        tx["session_object"]["resume"][0]["verbs"]
        == ["start", "manage_resume_session"],
        "session resume was not one transaction",
    )
    check(
        "sessions" in tx["session_object"]["resume"][0]["objects"],
        "session resume missed the session row",
    )
    check(
        tx["session_object"]["create_session"][0]["verbs"]
        == ["start", "manage_create_session"],
        "session create split the manage verb",
    )
    check(tx["session_object"]["start"] == [], "session start was not a replay")
    check(
        tx["unloadable_profile"]["resume"][0]["verbs"] == ["start"],
        "profile resume verb changed",
    )
    check(
        tx["unloadable_profile"]["resume"][0]["profile_writes"] == ["rebind"],
        "profile mapping was not written with resume start",
    )
    check(
        tx["unloadable_profile"]["create_session"][0]["profile_writes"] == ["bind"],
        "profile mapping was not written with start",
    )
    check(
        "sessions" not in tx["unloadable_profile"]["create_session"][0]["objects"],
        "profile start wrote a session row",
    )

    authorities = [item["authority"] for item in divergence["artifact_citation"]]
    check(
        authorities
        == [
            "caller_explicit_ref",
            "workflow_step_io",
            "session_artifact_chain",
            "read_path_fold",
        ],
        f"citation authorities diverged unexpectedly: {authorities}",
    )
    by_id = {item["design_id"]: item for item in designs}
    for design_id, design in by_id.items():
        citation = design["artifact_citation"]
        check(citation["accepted"] is True, f"{design_id} rejected the committed digest")
        check(
            citation["unknown_digest_rejected"] is True,
            f"{design_id} accepted an unknown digest",
        )
        check(
            citation["unknown_digest_tx_count"] == 0,
            f"{design_id} committed a write for an unknown digest",
        )
        check(
            citation["digest"] in design["caller_view"]["handoff_refs"],
            f"{design_id} handoff lost the plan digest",
        )
        check(design["caller_view"]["log_count"] > 0, f"{design_id} log is empty")
        check(
            design["probes"]["model_inside_transaction_rejected"] is True,
            f"{design_id} allowed a model call inside a transaction",
        )
        check(
            design["probes"]["file_write_inside_transaction_rejected"] is True,
            f"{design_id} allowed a file write inside a transaction",
        )

    thin_verbs, thin_objects = _cite_verbs(by_id["thin_adapter"])
    check("steer" in thin_verbs, "thin citation did not steer")
    check("workflow_steps" not in thin_objects, "thin citation wrote a workflow step")
    check("sessions" not in thin_objects, "thin citation wrote a session")
    check(
        by_id["thin_adapter"]["artifact_citation"]["evidence"]["caller_bundle"]
        and by_id["thin_adapter"]["artifact_citation"]["digest"]
        in by_id["thin_adapter"]["artifact_citation"]["evidence"]["caller_bundle"],
        "thin caller bundle lost the digest",
    )
    check(
        by_id["thin_adapter"]["artifact_citation"]["digest"]
        in by_id["thin_adapter"]["artifact_citation"]["evidence"]["resume_run_start_refs"],
        "thin resume did not pass the artifact ref",
    )

    wf_verbs, wf_objects = _cite_verbs(by_id["workflow_container"])
    check("handoff" in wf_verbs, "workflow citation did not write a step")
    check("workflow_steps" in wf_objects, "workflow citation missed workflow_steps")
    check(
        by_id["workflow_container"]["artifact_citation"]["digest"]
        in by_id["workflow_container"]["artifact_citation"]["evidence"][
            "workflow_step_inputs"
        ],
        "workflow step inputs lost the digest",
    )

    sess_verbs, sess_objects = _cite_verbs(by_id["session_object"])
    check("handoff" in sess_verbs, "session citation did not hand off")
    check("sessions" in sess_objects, "session citation missed the session row")
    check("workflow_steps" not in sess_objects, "session citation wrote a workflow step")
    check(
        by_id["session_object"]["artifact_citation"]["digest"]
        in by_id["session_object"]["artifact_citation"]["evidence"]["session_chain"],
        "session chain lost the digest",
    )

    profile_verbs, profile_objects = _cite_verbs(by_id["unloadable_profile"])
    check("steer" in profile_verbs, "profile citation did not stay on the run")
    check("sessions" not in profile_objects, "profile citation wrote a session")
    check("workflow_steps" not in profile_objects, "profile citation wrote a step")
    check(
        by_id["unloadable_profile"]["artifact_citation"]["folded_on_read"] is True,
        "profile handoff was not a read-path fold",
    )
    check(
        by_id["unloadable_profile"]["artifact_citation"]["evidence"]["caller_bundle"]
        is None,
        "profile kept a caller bundle",
    )
    check(
        by_id["unloadable_profile"]["artifact_citation"]["evidence"]["session_chain"]
        == [],
        "profile wrote a session chain",
    )

    retention_sigs = []
    for item in divergence["event_retention"]:
        check(item["events_retained"] is True, f"{item['design_id']} lost events")
        check(item["event_ids_removed"] == [], f"{item['design_id']} removed event ids")
        check(
            item["event_count_after"] > item["event_count_before"],
            f"{item['design_id']} cleanup did not append",
        )
        check(item["tombstone_appended"] is True, f"{item['design_id']} missed tombstone")
        check(item["exports_dropped"] is True, f"{item['design_id']} kept export bytes")
        retention_sigs.append(
            (
                tuple(item["cleanup_verbs"]),
                item["tombstone_via"],
                item["kernel_verb_rejected"],
                item["session_rows"],
                item["workflow_rows"],
            )
        )
    check(len(set(retention_sigs)) == 4, "cleanup retention does not diverge")
    retained = {item["design_id"]: item for item in divergence["event_retention"]}
    check(retained["thin_adapter"]["cleanup_verbs"] == ["note_purge"], "thin cleanup verb")
    check(retained["thin_adapter"]["session_rows"] == 0, "thin cleanup left a session")
    check(retained["thin_adapter"]["workflow_rows"] == 0, "thin cleanup left a workflow")
    check(retained["thin_adapter"]["kernel_verb_rejected"] is None, "thin rejected cleanup")
    check(
        retained["workflow_container"]["workflow_rows"] == 1,
        "workflow cleanup deleted the container",
    )
    check(
        retained["workflow_container"]["cleanup_verbs"] == ["note_purge"],
        "workflow cleanup verb",
    )
    check(
        retained["session_object"]["cleanup_verbs"] == ["manage_cleanup"],
        "session cleanup left the manage verb",
    )
    check(retained["session_object"]["session_rows"] == 1, "session cleanup deleted the row")
    check(
        retained["unloadable_profile"]["kernel_verb_rejected"] == "cleanup",
        "profile accepted a kernel cleanup verb",
    )
    check(
        retained["unloadable_profile"]["cleanup_verbs"] == ["note_purge"],
        "profile cleanup did not fall back to an append",
    )
    check(retained["unloadable_profile"]["session_rows"] == 0, "profile cleanup wrote a session")

    session_lists = [item["caller_view"]["session_ids"] for item in designs]
    check(
        divergence["resume_identity"][0]["session_id_before"] in session_lists[0],
        "thin list dropped the parent session id",
    )
    check(
        divergence["resume_identity"][0]["session_id_after"] in session_lists[0],
        "thin list dropped the resumed session id",
    )
    for item, ids in zip(designs[1:], session_lists[1:]):
        check(
            ids == [item["resume"]["after"]["session_id"]],
            f"{item['design_id']} session list changed across resume",
        )


def main() -> int:
    check_sources()
    check_substrate()
    sys.path.insert(0, str(ROOT))
    from run_experiment import write_report

    path = write_report(ROOT / "report.json")
    report = json.loads(path.read_text())
    check_report(report)
    print("ce_facades: ok")
    print(f"report: {path}")
    for item in report["divergence"]["resume_identity"]:
        print(
            f"{item['design_id']}: session {item['session_id_before']} -> {item['session_id_after']}"
            f" run {item['run_id_before']} -> {item['run_id_after']}"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        import traceback

        traceback.print_exc()
        raise SystemExit(1)
