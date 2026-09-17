"""v8/compat/client.py — Python command clients for the G13 host-agnostic
compat surface.

Same command convention as the shared clients (events/effect/tools): the
caller builds the FULL canonical request object with the shared canonical
profile (escape_dollar_keys + canonicalize) and hands the canonical text
plus the DECLARED hash to SQL; SQL recomputes v_sha256_hex and compares.

The transaction boundary of each wrapper is one transaction; real provider
IO (the DeepSeek adapter, see v8/loop/runtime.py) never happens inside
them — external IO stays outside database transactions (invariant 4).
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from v8.canonical import canonicalize, escape_dollar_keys

COMPAT_DRIVER = "dsh-compat"
PINNED_ADAPTER = "dsh-compat-adapter@1"


def _canon(obj: Any) -> tuple[str, str]:
    return canonicalize(escape_dollar_keys(obj))


def register_manifest(conn, adapter_id: str, driver: str,
                      dispatch_interception: str | None,
                      dispatch_note: str | None,
                      driver_switch: str,
                      compat_only_plugins: list[str] | None = None,
                      compat_only_fixtures: list[str] | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT v_compat_manifest_register(%s, %s, %s, %s, %s, %s::jsonb,"
            " %s::jsonb)",
            (adapter_id, driver, dispatch_interception, dispatch_note,
             driver_switch,
             json.dumps(compat_only_plugins or []),
             json.dumps(compat_only_fixtures or [])))
        cur.fetchone()
    conn.commit()


def portable_claim_ok(conn, adapter_id: str,
                      claimed_fixtures: list[str]) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT v_compat_portable_claim_ok(%s, %s::jsonb)",
                    (adapter_id, json.dumps(claimed_fixtures)))
        ok = cur.fetchone()[0]
    conn.commit()
    return bool(ok)


def compat_unmapped_audit(
    conn, session_id, command_id: str, driver: str, driver_epoch: int,
    adapter_identity: str, fixture_digest: str,
    dsh_type_canonical_identity: str, payload_hash: str,
    declared_hash: str | None = None,
) -> dict:
    """Gate + audit + commit in ONE transaction."""
    session_id = str(session_id)
    request = {
        "command_kind": "compat_unmapped_audit",
        "session_id": session_id,
        "command_id": command_id,
        "driver": driver,
        "driver_epoch": driver_epoch,
        "adapter_identity": adapter_identity,
        "fixture_digest": fixture_digest,
        "dsh_type_canonical_identity": dsh_type_canonical_identity,
        "payload_hash": payload_hash,
    }
    canonical_text, computed = _canon(request)
    declared = computed if declared_hash is None else declared_hash
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT outcome, code, receipt_json FROM v_compat_unmapped_audit("
                "%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (session_id, command_id, driver, driver_epoch, declared,
                 canonical_text, adapter_identity, fixture_digest,
                 dsh_type_canonical_identity, payload_hash))
            outcome, code, receipt = cur.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"outcome": outcome, "code": code, "receipt": receipt,
            "computed": computed}


def begin_switch(conn, session_id, command_id: str, driver: str,
                 driver_epoch: int, declared_hash: str | None = None,
                 target_driver: str | None = None,
                 lease_owner: str | None = None) -> dict:
    session_id = str(session_id)
    request = {
        "command_kind": "reconcile",
        "mode": "begin_switch",
        "session_id": session_id,
        "command_id": command_id,
        "driver": driver,
        "driver_epoch": driver_epoch,
    }
    if target_driver is not None:
        request["target_driver"] = target_driver
    canonical_text, computed = _canon(request)
    declared = computed if declared_hash is None else declared_hash
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT outcome, code, receipt_json FROM v_compat_begin_switch("
                "%s::uuid, %s, %s, %s, %s, %s, %s, %s)",
                (session_id, command_id, driver, driver_epoch, declared,
                 canonical_text, target_driver, lease_owner))
            outcome, code, receipt = cur.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"outcome": outcome, "code": code, "receipt": receipt}


def fork(conn, parent_session_id, through_seq: int,
         child_session_id=None, driver: str = COMPAT_DRIVER) -> dict:
    child = child_session_id or str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "SELECT v_compat_fork(%s::uuid, %s::uuid, %s, %s)",
            (str(parent_session_id), child, through_seq, driver))
        result = cur.fetchone()[0]
    conn.commit()
    return result


def matrix_blocked(conn, dispatch_interception: str,
                   driver_switch: str) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT v_compat_matrix_blocked(%s, %s)",
                    (dispatch_interception, driver_switch))
        return cur.fetchone()[0]


def participation(conn, adapter_id: str = PINNED_ADAPTER) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT v_compat_participation(%s)", (adapter_id,))
        result = cur.fetchone()[0]
    conn.commit()
    return result
