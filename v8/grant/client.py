"""v8/grant/client.py — operator-channel client for the G10 grant stage.

Controlled wrappers around the SECURITY DEFINER operator functions. The
capability API boundary (Conformance 13, database half): a raw database
connection and raw paths never leave this surface — callers hand over
logical workspace/slice/grant identities and reasons only, and credentials
(or any secret-bearing payload) never enter session_events, jobs or logs;
the operator identity and reason recorded by the server-side audit are the
only trace.
"""
from __future__ import annotations

import json
import uuid


def _one(conn, sql, params) -> object:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


def issue_slice(conn, operator: str, workspace_id, name: str, kind: str,
                spec: dict | None = None) -> str:
    return str(_one(
        conn,
        "SELECT v_operator_issue_slice(%s, %s::uuid, %s, %s, %s::jsonb)",
        (operator, workspace_id, name, kind, json.dumps(spec or {}))))


def issue_grant(conn, operator: str, workspace_id, slice_id, subject_kind: str,
                subject_id: str, capability: str, constraints: dict | None = None,
                delegable: bool = False) -> str:
    return str(_one(
        conn,
        "SELECT v_operator_issue_grant(%s, %s::uuid, %s::uuid, %s, %s, %s,"
        " %s::jsonb, NULL, NULL, %s)",
        (operator, workspace_id, slice_id, subject_kind, subject_id,
         capability, json.dumps(constraints) if constraints else None,
         delegable)))


def revoke_grant(conn, operator: str, grant_id: str, reason: str) -> dict:
    raw = _one(conn, "SELECT v_operator_revoke_grant(%s, %s, %s)",
               (operator, grant_id, reason))
    return json.loads(raw) if isinstance(raw, str) else dict(raw or {})


def revoke_slice(conn, operator: str, slice_id, reason: str) -> dict:
    raw = _one(conn, "SELECT v_operator_revoke_slice(%s, %s::uuid, %s)",
               (operator, slice_id, reason))
    return json.loads(raw) if isinstance(raw, str) else dict(raw or {})


def workspace_initialize(conn, session_id, run_id: str, workspace_id,
                         owner_fence: int = 1) -> str:
    return str(_one(
        conn,
        "SELECT v_workspace_initialize(%s::uuid, %s, %s::uuid, %s)",
        (session_id, run_id, workspace_id, owner_fence)))


def fork_session(conn, parent_session_id, through_seq: int,
                 driver: str | None = None) -> dict:
    raw = _one(conn, "SELECT v_fork_session(%s::uuid, %s, %s)",
               (parent_session_id, through_seq, driver))
    if isinstance(raw, str):
        return json.loads(raw)
    return dict(raw or {})


def new_run_id() -> str:
    return f"run-{uuid.uuid4().hex[:12]}"
