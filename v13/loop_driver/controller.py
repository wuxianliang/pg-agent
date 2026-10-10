"""Pure, fail-closed controller receipt validation and six-word disposition."""
from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID


_RECEIPT_KEYS = {
    "schema_version", "caller", "target", "advance_word", "target_seq_before",
    "observe", "readback", "repair_required", "replan_required",
}
_OBSERVE_KEYS = {"schema_version", "ok", "rows", "hints", "pointers"}
_READBACK_KEYS = {
    "session_id", "status", "is_terminal", "last_event_seq", "last_event_type",
    "pending_human", "cancel_pending",
}


def _canonical_uuid(value):
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _integer(value, minimum):
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _normalized_row(value):
    """Return the seven-field subset of a usable row, otherwise None."""
    if not isinstance(value, Mapping) or not _READBACK_KEYS <= set(value):
        return None
    if (not _canonical_uuid(value["session_id"])
            or not isinstance(value["status"], str)
            or not isinstance(value["is_terminal"], bool)
            or not _integer(value["last_event_seq"], -1)
            or (value["last_event_type"] is not None
                and not isinstance(value["last_event_type"], str))
            or not isinstance(value["pending_human"], bool)
            or not isinstance(value["cancel_pending"], bool)):
        return None
    return {key: value[key] for key in _READBACK_KEYS}


def decide_controller_disposition(receipt: Mapping) -> str:
    """Validate the closed receipt before applying repair-first precedence."""
    if not isinstance(receipt, Mapping):
        raise ValueError("controller receipt must be an object")
    if set(receipt) != _RECEIPT_KEYS:
        raise ValueError("controller receipt keys")
    if not _integer(receipt["schema_version"], 1) or receipt["schema_version"] != 1:
        raise ValueError("controller receipt schema_version must be 1")
    for field in ("caller", "target"):
        if not _canonical_uuid(receipt[field]):
            raise ValueError("controller receipt " + field + " must be canonical uuid")
    word = receipt["advance_word"]
    if not isinstance(word, str) or word not in ("progressed", "waiting", "terminal", "stale"):
        raise ValueError("controller receipt advance_word")
    if not _integer(receipt["target_seq_before"], -1):
        raise ValueError("controller receipt target_seq_before")
    for field in ("repair_required", "replan_required"):
        if not isinstance(receipt[field], bool):
            raise ValueError("controller receipt " + field)

    observe, readback = receipt["observe"], receipt["readback"]
    if observe is not None:
        if (not isinstance(observe, Mapping)
                or set(observe) not in (_OBSERVE_KEYS, _OBSERVE_KEYS | {"reason"})
                or not _integer(observe.get("schema_version"), 1)
                or observe["schema_version"] != 1
                or not isinstance(observe.get("ok"), bool)
                or any(not isinstance(observe.get(key), list)
                       for key in ("rows", "hints", "pointers"))
                or ("reason" in observe and (observe["ok"]
                    or not isinstance(observe["reason"], str)))):
            raise ValueError("controller receipt observe shape")
    if readback is not None:
        if (not isinstance(readback, Mapping) or set(readback) != _READBACK_KEYS
                or _normalized_row(readback) is None):
            raise ValueError("controller receipt readback shape")

    observed = None
    if observe is not None and observe["ok"] and len(observe["rows"]) == 1:
        observed = _normalized_row(observe["rows"][0])
    if word != "progressed":
        if observe is not None or readback is not None:
            raise ValueError("controller receipt observe/readback mismatch")
    elif (observed is None) != (readback is None):
        raise ValueError("controller receipt observe/readback mismatch")

    unavailable = word == "progressed" and (
        observed is None or readback != observed
        or readback["session_id"] != receipt["target"]
        or readback["last_event_seq"] <= receipt["target_seq_before"])
    if receipt["repair_required"] or word == "stale" or unavailable:
        return "repair"
    if word == "terminal" or (readback is not None and (
            readback["status"] in ("completed", "failed", "cancelled")
            or readback["is_terminal"])):
        return "terminal"
    if readback is not None and readback["pending_human"]:
        return "user_action_required"
    if receipt["replan_required"]:
        return "replan"
    return "run_now" if word == "progressed" else "wait"
