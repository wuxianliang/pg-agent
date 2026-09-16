"""v8 G17 compact client: the three controlled commands.

Envelope convention follows the frozen v8/effect/client.py contract: the
client canonicalizes the request object, passes the computed hash as the
declared hash (so a matching declared hash never trips
REQUEST_HASH_MISMATCH), and commits in ONE transaction with the SQL gate.
"""
from __future__ import annotations

from v8.effect.client import _canon, _gate_and_run

LOCK_SQL = ("SELECT outcome, code, receipt_json FROM v_compact_lock("
            "%s::uuid, %s, %s, %s, %s, %s, %s)")
FIN_SQL = ("SELECT outcome, code, receipt_json FROM v_compact_finalize("
           "%s::uuid, %s, %s, %s, %s, %s, %s, %s)")
ABORT_SQL = ("SELECT outcome, code, receipt_json FROM v_compact_abort("
             "%s::uuid, %s, %s, %s, %s, %s, %s, %s)")


def compact_lock(conn, session_id, command_id: str, driver: str,
                 driver_epoch: int, compaction_id: str,
                 declared_hash: str | None = None) -> dict:
    request = {
        "command_kind": "compact_lock",
        "session_id": str(session_id),
        "command_id": command_id,
        "driver": driver,
        "driver_epoch": driver_epoch,
        "compaction_id": compaction_id,
    }
    text, computed = _canon(request)
    declared = computed if declared_hash is None else declared_hash
    return _gate_and_run(
        conn, "compact_lock", text, declared, LOCK_SQL,
        (str(session_id), command_id, driver, driver_epoch, compaction_id,
         declared, text))


def compact_finalize(conn, session_id, command_id: str, driver: str,
                     driver_epoch: int, compaction_id: str, owner_fence: int,
                     declared_hash: str | None = None) -> dict:
    request = {
        "command_kind": "compact_finalize",
        "session_id": str(session_id),
        "command_id": command_id,
        "driver": driver,
        "driver_epoch": driver_epoch,
        "compaction_id": compaction_id,
        "owner_fence": owner_fence,
    }
    text, computed = _canon(request)
    declared = computed if declared_hash is None else declared_hash
    return _gate_and_run(
        conn, "compact_finalize", text, declared, FIN_SQL,
        (str(session_id), command_id, driver, driver_epoch, compaction_id,
         owner_fence, declared, text))


def compact_abort(conn, session_id, command_id: str, driver: str,
                  driver_epoch: int, compaction_id: str, owner_fence: int,
                  declared_hash: str | None = None) -> dict:
    request = {
        "command_kind": "compact_abort",
        "session_id": str(session_id),
        "command_id": command_id,
        "driver": driver,
        "driver_epoch": driver_epoch,
        "compaction_id": compaction_id,
        "owner_fence": owner_fence,
    }
    text, computed = _canon(request)
    declared = computed if declared_hash is None else declared_hash
    return _gate_and_run(
        conn, "compact_abort", text, declared, ABORT_SQL,
        (str(session_id), command_id, driver, driver_epoch, compaction_id,
         owner_fence, declared, text))
