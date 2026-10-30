"""Run the four round-two facades and write report.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from db import reset_database  # noqa: E402
from control import Control  # noqa: E402
from scenario import run_scenario  # noqa: E402
from session_object import SessionObject  # noqa: E402
from thin_adapter import ThinAdapter  # noqa: E402
from unloadable_profile import UnloadableProfile  # noqa: E402
from workflow_container import WorkflowContainer  # noqa: E402

FACADES = (WorkflowContainer, ThinAdapter, SessionObject, UnloadableProfile)


def build_report() -> dict:
    dsn = reset_database()
    designs = []
    for facade_cls in FACADES:
        control = Control(dsn)
        try:
            designs.append(run_scenario(facade_cls(control)))
        finally:
            control.close()
    return {
        "experiment": "ce_facades_r2",
        "database": "agent_v20_ce_facades_r2",
        "note": "four designs observed; none selected",
        "designs": designs,
    }


def write_report(path: Path | None = None) -> Path:
    target = path or HERE / "report.json"
    report = build_report()
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return target


def main() -> int:
    path = write_report()
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
