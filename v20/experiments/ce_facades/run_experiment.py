"""Run the four CE facades through one scenario and write report.json."""

from __future__ import annotations

import json
from pathlib import Path

from scenario import run_scenario
from session_object import SessionObject
from substrate import Control
from thin_adapter import ThinAdapter
from unloadable_profile import UnloadableProfile
from workflow_container import WorkflowContainer


def _tx_shape(txs: list[dict]) -> list[dict]:
    return [
        {
            "verbs": list(tx["verbs"]),
            "objects": list(tx["objects"]),
            "profile_writes": list(tx["profile_writes"]),
        }
        for tx in txs
    ]


def _facades() -> list:
    return [
        ThinAdapter(Control()),
        WorkflowContainer(Control()),
        SessionObject(Control()),
        UnloadableProfile(Control()),
    ]


def build_report() -> dict:
    designs = [run_scenario(facade) for facade in _facades()]
    divergence = {
        "resume_identity": [
            {
                "design_id": item["design_id"],
                "session_id_before": item["resume"]["before"]["session_id"],
                "run_id_before": item["resume"]["before"]["run_id"],
                "session_id_after": item["resume"]["after"]["session_id"],
                "run_id_after": item["resume"]["after"]["run_id"],
                "session_id_stable": item["resume"]["session_id_stable"],
                "run_id_changed": item["resume"]["run_id_changed"],
                "session_id_equals_run_id_after": item["resume"][
                    "session_id_equals_run_id_after"
                ],
                "parent_run_id": item["resume"]["parent_run_id"],
                "kernel_session_rows": item["resume"]["kernel_session_rows"],
                "kernel_workflow_rows": item["resume"]["kernel_workflow_rows"],
            }
            for item in designs
        ],
        "transaction_writes": [
            {
                "design_id": item["design_id"],
                "create_session": _tx_shape(
                    item["transaction_writes"]["phases"]["create_session"]
                ),
                "start": _tx_shape(item["transaction_writes"]["phases"]["start"]),
                "resume": _tx_shape(item["transaction_writes"]["phases"]["resume"]),
                "cleanup": _tx_shape(item["transaction_writes"]["phases"]["cleanup"]),
            }
            for item in designs
        ],
        "artifact_citation": [
            {
                "design_id": item["design_id"],
                "authority": item["artifact_citation"]["authority"],
                "folded_on_read": item["artifact_citation"]["folded_on_read"],
                "unknown_digest_rejected": item["artifact_citation"][
                    "unknown_digest_rejected"
                ],
                "digest_in_handoff": item["artifact_citation"]["digest"]
                in item["caller_view"]["handoff_refs"],
                "evidence": item["artifact_citation"]["evidence"],
            }
            for item in designs
        ],
        "event_retention": [
            {
                "design_id": item["design_id"],
                "events_retained": item["event_retention"]["events_retained"],
                "event_ids_removed": item["event_retention"]["event_ids_removed"],
                "event_count_before": item["event_retention"]["event_count_before"],
                "event_count_after": item["event_retention"]["event_count_after"],
                "tombstone_appended": item["event_retention"]["tombstone_appended"],
                "tombstone_via": item["event_retention"]["tombstone_via"],
                "cleanup_verbs": item["event_retention"]["cleanup_verbs"],
                "kernel_verb_rejected": item["event_retention"]["kernel_verb_rejected"],
                "exports_dropped": item["event_retention"]["exports_dropped"],
                "session_rows": item["event_retention"]["session_rows"],
                "workflow_rows": item["event_retention"]["workflow_rows"],
            }
            for item in designs
        ],
    }
    return {
        "experiment": "ce_facades",
        "note": "four designs observed; none selected",
        "designs": designs,
        "divergence": divergence,
    }


def write_report(path: Path | None = None) -> Path:
    target = path or Path(__file__).resolve().parent / "report.json"
    report = build_report()
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return target


def main() -> int:
    path = write_report()
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
