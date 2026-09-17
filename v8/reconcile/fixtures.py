"""G18 gate fixtures: driver capability declarations, reconcile client and
shared session scaffolding.

The switch intent identity golden vectors are computed with the standalone
hashlib expression (never by calling v_switch_intent_identity — the
anti-circular golden rule shared with the other stages' key tests).
"""
from __future__ import annotations

import hashlib
import json
import struct

SV, CV = "sv@1", "canon@1"
EPOCH = 1


def _canon(obj) -> tuple[str, str]:
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return text, hashlib.sha256(text.encode()).hexdigest()


def switch_intent_identity(session_id: str, target_driver: str,
                           fence: int) -> str:
    """Standalone re-computation of the v8:switch-intent@v1 key (the
    compact-style len8-prefixed segment framing)."""
    def seg(raw: bytes) -> bytes:
        return struct.pack(">Q", len(raw)) + raw
    body = (b"v8:switch-intent@v1\x00"
            + seg(str(session_id).encode())
            + seg(target_driver.encode())
            + seg(str(fence).encode()))
    return hashlib.sha256(body).hexdigest()


def declare_capability(conn, driver: str, capability: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO driver_switch_capabilities(driver, switch_capability)"
            " VALUES (%s, %s) ON CONFLICT (driver) DO NOTHING",
            (driver, capability))
    conn.commit()


def reconcile(conn, session_id, command_id: str, action: str, *,
              driver: str, driver_epoch: int = EPOCH,
              expected_mode: str = "active", session_fence: int,
              lease_owner: str, target_driver: str | None = None,
              declared_hash: str | None = None) -> dict:
    session_id = str(session_id)
    request = {
        "command_kind": "reconcile",
        "mode": action,
        "session_id": session_id,
        "command_id": command_id,
        "driver": driver,
        "driver_epoch": driver_epoch,
        "driver_mode": expected_mode,
        "session_fence": session_fence,
    }
    if target_driver is not None:
        request["target_driver"] = target_driver
    canonical_text, computed = _canon(request)
    declared = computed if declared_hash is None else declared_hash
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT outcome, code, receipt_json FROM v_reconcile("
                "%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (session_id, command_id, action, driver, driver_epoch,
                 expected_mode, session_fence, lease_owner, target_driver,
                 declared, canonical_text))
            outcome, code, receipt = cur.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"outcome": outcome, "code": code, "receipt": receipt}
