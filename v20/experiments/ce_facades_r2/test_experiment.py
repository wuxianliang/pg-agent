"""Round-two gate. Exit 0 means all four designs covered the expanded scenario."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from run_experiment import write_report  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def check_design(design: dict) -> None:
    name = design["design_id"]
    check(design["probes"]["model_inside_transaction_rejected"], f"{name} model")
    check(design["probes"]["file_write_inside_transaction_rejected"], f"{name} file write")
    check(design["probes"]["file_read_inside_transaction_rejected"], f"{name} file read")
    resume = design["resume"]
    check(resume["session_id_stable"], f"{name} session id changed")
    check(resume["run_id_changed"], f"{name} run id did not change")
    check(resume["listed"], f"{name} missing from list_sessions")
    waited = design["poll_wait"]
    check(waited["path"] == "notify", f"{name} wait path")
    check(waited["waiter_transaction_open"] is False, f"{name} wait transaction")
    check(waited["main_connection_idle"] is True, f"{name} connection idle")
    check(waited["payload_fields"] == ["run_id", "revision"], f"{name} notify fields")
    check(waited["advanced"] is True, f"{name} wait did not advance")
    check(design["cas"]["one_commit_one_conflict"], f"{name} cas {design['cas']}")
    recovered = design["recover_owner"]
    check(recovered["old_fence_rejected"], f"{name} old fence")
    check(recovered["new_owner_steer_committed"], f"{name} new owner")
    check(design["macro_links"] == 2, f"{name} macro links")
    check(len(design["macro"]["workflow_ids"]) == 2, f"{name} macro workflows")
    check(design["macro"]["file_matches_digest"], f"{name} macro file")
    check(
        design["macro"]["digest"] in design["macro"]["second_step_inputs"],
        f"{name} macro citation",
    )
    export = design["workspace_export"]
    check(export["digest_matched_file_before_cleanup"], f"{name} export digest")
    check(export["bytes_cleared"], f"{name} export bytes")
    check(export["artifact_row_remains"], f"{name} artifact row")
    check(design["event_retention"]["events_retained"], f"{name} events")
    check(design["event_retention"]["kernel_verb_rejected"] is None, f"{name} cleanup")
    check(design["log_count"] > 0, f"{name} log")
    check(design["citation"]["digest"] == export["digest"], f"{name} cite digest")
    check(design["needs_status"] == "needs_input", f"{name} needs_input")
    check(design["responded_status"] == "running", f"{name} respond")
    identity = design["postgres_readback"]
    check(identity["row"] is not None, f"{name} sql identity")
    check(identity["events_session_indexed"], f"{name} event index")
    check(
        identity["session_columns"] == ["session_id", "status", "workflow_run_id"],
        f"{name} session columns {identity['session_columns']}",
    )


def check_differences(report: dict) -> None:
    by_id = {item["design_id"]: item for item in report["designs"]}
    thin = by_id["thin_adapter"]
    workflow = by_id["workflow_container"]
    session = by_id["session_object"]
    profile = by_id["unloadable_profile"]
    check(thin["citation"]["authority"] == "committed_artifact_row", "thin authority")
    check(thin["macro"]["alias_rows"] == 2, "thin macro aliases")
    check(str(thin["resume"]["before"]["session_id"]).startswith("alias_"), "thin id")
    check(workflow["citation"]["authority"] == "workflow_step_io", "workflow authority")
    check(workflow["citation"]["folded_on_read"] is False, "workflow fold")
    check(workflow["macro"]["alias_rows"] == 0, "workflow aliases")
    check(workflow["macro"]["external_rows"] == 0, "workflow externals")
    check(
        workflow["resume"]["before"]["session_id"].startswith("wf_"),
        "workflow session id",
    )
    check(session["citation"]["authority"] == "workflow_step_io", "session authority")
    check(session["handoff"]["seq"] >= 1, "session step seq")
    check(session["macro"]["session_rows"] == 2, "session macro rows")
    check(session["resume"]["before"]["session_id"].startswith("sess_"), "session id")
    check(profile["citation"]["folded_on_read"] is True, "profile fold")
    check(profile["macro"]["external_rows"] == 2, "profile macro rows")
    check(profile["postgres_readback"]["row"]["status"] == "purged", "profile purged")
    check(profile["resume"]["before"]["session_id"].startswith("ext_"), "profile id")


def main() -> int:
    path = write_report()
    import json

    report = json.loads(path.read_text())
    check(len(report["designs"]) == 4, "expected four designs")
    for design in report["designs"]:
        check_design(design)
        print(
            f"{design['design_id']}: session {design['resume']['before']['session_id']}"
            f" -> run {design['resume']['after']['run_id']}"
        )
    check_differences(report)
    print("ce_facades_r2: ok")
    print(f"report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
