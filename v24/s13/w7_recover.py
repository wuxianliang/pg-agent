"""W7 fresh-process recovery: reconcile journal outcomes, never call a tool."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v24.host.db import HostDB
from v24.host.journal import HostJournal
from v24.host.worker import HostWorker


def _settlements(journal) -> int:
    return sum(1 for item in journal.records
               if item["event_type"] == "settlement_committed")


def main() -> int:
    admin = os.environ["V24_W7_ADMIN_DSN"]
    service = os.environ["V24_W7_SERVICE_DSN"]
    journal_path, scope = sys.argv[1:3]
    journal = HostJournal.open(journal_path)
    db = None
    try:
        before = _settlements(journal)
        db = HostDB(admin, service)
        # _reconcile never calls a handler; if it ever does, exit loudly.
        worker = HostWorker(db, journal, tool_handler=lambda effect: os._exit(97))
        reconciled = worker._reconcile(scope)
        settlements = _settlements(journal) - before
        print(f"[w7-recover] reconciled={reconciled} settlements={settlements}")
        return 0 if reconciled + settlements >= 1 else 1
    finally:
        if db is not None:
            db.close()
        journal.close()


if __name__ == "__main__":
    raise SystemExit(main())
