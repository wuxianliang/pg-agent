"""Small shared helpers for the v24 S6 crash harness.

Only local PostgreSQL, pipes and files are used: no network imports.
"""
from __future__ import annotations

import hashlib
import json
import os
import select
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from psycopg2.extras import Json

TEN_TABLES = (
    "scopes", "runs", "effects", "pins", "episodes",
    "fibers", "slots", "installs", "events", "requests",
)
PRIMARY_KEYS = {
    "scopes": ("scope_id",),
    "runs": ("run_id",),
    "effects": ("effect_id",),
    "pins": ("pin_id",),
    "episodes": ("episode_id",),
    "fibers": ("fiber_id",),
    "slots": ("slot_id",),
    "installs": ("install_id",),
    "events": ("event_id",),
    "requests": ("principal_id", "request_key"),
}


def one(conn, statement, params=()):
    with conn.cursor() as cur:
        cur.execute(statement, params)
        return cur.fetchone()[0]


def new_scope(conn, request_key: str) -> str:
    """Create one independent root scope through the ordinary wrapper."""
    response = one(
        conn,
        "SELECT v24.scope_control('create_root', NULL, %s, NULL, %s)",
        (Json({}), request_key),
    )
    assert response.get("disposition") == "committed", response
    conn.commit()
    emitted = response["emitted"]
    assert len(emitted) == 1, response
    return emitted[0]


def seed_claim(
    conn,
    scope_id,
    *,
    effect_id=None,
    kind: str = "host_prepare",
    replay_policy: str = "replay_safe",
    status: str = "claimed",
    attempt_no: int = 1,
    fence: int = 1,
    claim_owner: str = "g5-seed",
    lease_until=None,
    request_key: str | None = None,
    outcome=None,
    settled_at=None,
) -> str:
    """Owner-side fixture seed; never a public recovery path."""
    effect_id = UUID(str(effect_id)) if effect_id is not None else uuid4()
    request_key = request_key or f"g5-seed-{effect_id}"
    if status == "claimed":
        if lease_until is None:
            lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        assert claim_owner is not None and lease_until is not None
        assert outcome is None and settled_at is None
    elif status in ("succeeded", "failed", "unknown"):
        assert outcome is not None and settled_at is not None
        # A settled effect cannot carry a claim.
        claim_owner, lease_until = None, None
    elif status == "cancelled":
        assert outcome is None and settled_at is not None
        claim_owner, lease_until = None, None
    elif status == "ready":
        assert outcome is None and settled_at is None
        claim_owner, lease_until = None, None
    else:
        raise AssertionError(status)
    assert fence <= attempt_no
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO v24.effects
                 (effect_id, requester_id, request_key, scope_id, kind, status,
                  request, request_digest, replay_policy, attempt_no, fence,
                  claim_owner, lease_until, outcome, settled_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                str(effect_id), str(uuid4()), request_key, scope_id, kind, status,
                Json({"seed": True}), b"g5-seed", replay_policy, attempt_no,
                fence, claim_owner, lease_until,
                None if outcome is None else Json(outcome), settled_at,
            ),
        )
    return str(effect_id)


def g5_snapshot(conn) -> dict[str, list]:
    """The ten-table snapshot from plan section 5.2: full rows, ordered by PK."""
    result: dict[str, list] = {}
    with conn.cursor() as cur:
        for table in TEN_TABLES:
            order = ", ".join(f"t.{key}" for key in PRIMARY_KEYS[table])
            cur.execute(
                f"SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY {order}), '[]'::jsonb) "
                f"FROM v24.{table} t"
            )
            result[table] = cur.fetchone()[0]
    return result


def row_key(table: str, row: dict) -> tuple:
    return tuple(row[key] for key in PRIMARY_KEYS[table])


def snapshot_diff(before: dict[str, list], after: dict[str, list]) -> dict:
    """Changed tables with added/removed/modified rows (fixture evidence only)."""
    diff: dict[str, dict] = {}
    for table in TEN_TABLES:
        old = {row_key(table, row): row for row in before[table]}
        new = {row_key(table, row): row for row in after[table]}
        added = [new[key] for key in new.keys() - old.keys()]
        removed = [old[key] for key in old.keys() - new.keys()]
        changed = [
            {"before": old[key], "after": new[key]}
            for key in old.keys() & new.keys() if old[key] != new[key]
        ]
        if added or removed or changed:
            diff[table] = {
                "added": sorted(added, key=lambda row: str(row_key(table, row))),
                "removed": sorted(removed, key=lambda row: str(row_key(table, row))),
                "changed": changed,
            }
    return diff


def insert_row(conn, table: str, **values) -> None:
    """Owner-side fixture insert; never a public write path."""
    from psycopg2 import sql

    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("INSERT INTO v24.{} ({}) VALUES ({})").format(
                sql.Identifier(table),
                sql.SQL(", ").join(map(sql.Identifier, values)),
                sql.SQL(", ").join(sql.Placeholder() for _ in values),
            ),
            tuple(values.values()),
        )


def seed_run_with_model(conn, scope_id) -> dict:
    """Owner fixture: one running run, its command_start parent and a ready model.

    The model effect is a structurally valid ``cause=start`` request so the
    ordinary advance claim path can be used; this is a fixture, not a public
    run-creation path.
    """
    run_id, parent = uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    hex64 = "00" * 32
    insert_row(
        conn, "runs", run_id=run_id, scope_id=scope_id, status="running",
        epoch_no=1, registration_generation=1, turn_no=0, driving_generation=1,
        remaining_steps=5, remaining_tokens=1000, remaining_tool_calls=3,
        remaining_wall_ms=10000, revision=1, created_at=now, updated_at=now,
    )
    insert_row(
        conn, "effects", effect_id=parent, requester_id=uuid4(),
        kind="command_start", status="succeeded", scope_id=scope_id,
        run_id=run_id, request=Json({"fixture": "command_start"}),
        request_digest=b"g5-model-parent", replay_policy="replay_safe",
        outcome=Json({"v": 1, "class": "command", "claim": None, "body": {}}),
        settled_at=now,
    )
    model_id = one(
        conn,
        "SELECT md5(%s::text || ':model_call:0')::uuid",
        (str(parent),),
    )
    request = {
        "v": 1, "cause": "start", "run_id": str(run_id), "epoch_no": 1,
        "generation": 1, "input": {}, "budget": {},
        "reserve": {"tokens": 64},
        "digests": {"policy": hex64, "schema": hex64, "toolset": hex64},
    }
    insert_row(
        conn, "effects", effect_id=model_id, parent_effect_id=parent, ordinal=0,
        requester_id=uuid4(), scope_id=scope_id, run_id=run_id, epoch_no=1,
        generation=1, kind="model_call", status="ready", request=Json(request),
        request_digest=b"g5-model-request", replay_policy="no_replay",
    )
    conn.commit()
    return {
        "run_id": str(run_id),
        "parent_effect_id": str(parent),
        "model_effect_id": str(model_id),
    }



def fingerprint(snapshot: dict[str, list]) -> str:
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def jsonl_path(directory, window: str) -> str:
    return os.path.join(str(directory), f"{window}.jsonl")


def read_jsonl(path) -> list[dict]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def wait_ready(ready_fd: int, timeout: float = 30) -> dict:
    """Wait on the READY pipe with select; a timeout is a failure, not a retry."""
    data = bytearray()
    while b"\n" not in data:
        readable, _, _ = select.select([ready_fd], [], [], timeout)
        if not readable:
            raise TimeoutError("crash child did not reach READY before the deadline")
        chunk = os.read(ready_fd, 4096)
        if not chunk:
            raise EOFError("crash child exited before reporting READY")
        data.extend(chunk)
    return json.loads(bytes(data).split(b"\n", 1)[0])
