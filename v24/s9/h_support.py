"""Shared helpers for the v24 G8 host-read extension check.

Only the disposable local PostgreSQL fixture is used.  There is no network
client here: the static scan in test_g8.py polices this directory and the test
monkeypatches socket connect/create_connection before touching the database.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from psycopg2.extras import Json

ROOT = Path(__file__).resolve().parent
V24 = ROOT.parent
S1 = V24 / "s1"
S2 = V24 / "s2"
S4 = V24 / "s4"
S5 = V24 / "s5"
S6 = V24 / "s6"
S8 = V24 / "s8"
for _path in (S1, S2, S4, S5, S6, S8):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from setup_db import EXPECTED_TABLES  # noqa: E402
from test_ddl import DIGEST, effect, insert, scope  # noqa: E402

HOST_READS = (
    "host_scopes", "host_runs", "host_effects", "host_run_effects",
    "host_effect", "host_scope_installs", "host_install_fibers",
    "host_run_pins", "host_request",
)
SCOPED_READS = (
    "host_scopes", "host_runs", "host_effects", "host_run_effects",
    "host_effect", "host_scope_installs", "host_install_fibers",
    "host_run_pins",
)
HOST_DEFINERS = (
    "advance", "host_effect", "host_effects", "host_install_fibers",
    "host_request", "host_run_effects", "host_run_pins", "host_runs",
    "host_scope_allowed", "host_scope_installs", "host_scopes", "poll",
    "recoverable_effects", "resolve", "run_owner", "run_projection",
    "wait_check",
)
LIST_KEYS = frozenset(("v", "items", "limit", "has_more", "next_cursor"))
EFFECT_KEYS = frozenset((
    "effect_id", "parent_effect_id", "ordinal", "scope_id", "run_id",
    "fiber_id", "episode_id", "pin_id", "epoch_no", "generation", "kind",
    "status", "replay_policy", "attempt_no", "fence", "claim_owner",
    "cancel_requested", "request", "outcome", "lease_until",
    "resource_quiesced_at", "created_at", "settled_at",
))
SCOPE_KEYS = frozenset((
    "scope_id", "parent_id", "root_id", "owner_principal",
    "close_requested_at", "closed_at",
))
INSTALL_KEYS = frozenset((
    "install_id", "scope_id", "owner_fiber_id", "owner_episode_id",
    "identity", "version", "manifest", "manifest_digest", "requires",
    "provides", "artifact_digest", "adapter_digest", "owner_principal",
    "state", "created_by_effect", "dispose_effect", "disposed_at",
))
FIBER_KEYS = frozenset((
    "fiber_id", "install_id", "scope_id", "owner_fiber_id",
    "owner_episode_id", "want_on", "control_seq", "current_episode_id",
    "disposed_at", "failure_seq", "failure", "next_contribution_seq",
    "created_by_effect",
))
PIN_KEYS = frozenset((
    "pin_id", "consumer_type", "consumer_run_id", "consumer_epoch", "key",
    "slot_id", "provider_fiber_id", "provider_episode_id",
    "provider_install_id", "descriptor", "descriptor_digest",
    "created_by_effect", "released_by_effect", "released_at",
))
REQUEST_KEYS = frozenset((
    "request_key", "kind", "request_bytes_base64", "request_digest_hex",
    "response", "effect_id", "created_at",
))
RUN_PROJECTION_KEYS = frozenset((
    "run_id", "scope_id", "status", "epoch_no", "registration_generation",
    "turn_no", "driving_generation", "interaction", "pending_steer",
    "close_intent", "result", "remaining_steps", "remaining_tokens",
    "remaining_tool_calls", "remaining_wall_ms", "revision", "created_at",
    "updated_at", "ended_at", "owner_fiber_id", "owner_episode_id",
))
FORBIDDEN_IMPORTS = (
    "socket", "http", "urllib", "requests", "ftplib", "smtplib",
    "telnetlib", "ssl", "aiohttp", "httpx",
)
SQL_FORBIDDEN = re.compile(r"\b(?:http|dblink|pg_sleep|socket)\b", re.IGNORECASE)
SQL_DDL = re.compile(
    r"\b(?:insert|update|delete|truncate|alter|drop|create\s+table|"
    r"create\s+view|create\s+index|create\s+extension|copy|grant|revoke)\b",
    re.IGNORECASE,
)
READ_NOISE = re.compile(
    r"\b(?:insert|update|delete|pg_advisory[a-z_0-9]*)\b", re.IGNORECASE)


def one(conn, statement, params=()):
    with conn.cursor() as cur:
        cur.execute(statement, params)
        return cur.fetchone()[0]


def rows(conn, statement, params=()):
    with conn.cursor() as cur:
        cur.execute(statement, params)
        return cur.fetchall()


def advance(conn, effect_id, outcome):
    return one(conn, "SELECT v24.advance(%s,%s)", (effect_id, Json(outcome)))


def claim(lease=300000):
    return {"v": 1, "class": "claim", "claim": None,
            "body": {"lease_ms": lease}}


def state(conn):
    result = {}
    for table in sorted(EXPECTED_TABLES):
        result[table] = one(
            conn,
            "SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text), '[]') "
            f"FROM v24.{table} t",
        )
    return result


def fingerprint(snapshot):
    return hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def snapshot(conn):
    value = state(conn)
    conn.rollback()
    return value


def principal(conn):
    value = one(conn, "SELECT v24.principal_id(session_user)")
    conn.commit()
    return value


def error(code):
    return {"v": 1, "error": {"code": code}}


def assert_list_envelope(response, limit):
    assert set(response) == LIST_KEYS, response
    assert response["v"] == 1, response
    assert isinstance(response["items"], list), response
    assert response["limit"] == limit, response
    assert isinstance(response["has_more"], bool), response
    if response["has_more"]:
        assert response["next_cursor"] is not None, response
    else:
        assert response["next_cursor"] is None, response


def call_list(conn, name, args):
    response = one(conn, f"SELECT v24.{name}({', '.join(['%s'] * len(args))})", args)
    conn.rollback()
    return response


def scan_pages(conn, name, args, limit):
    """Read all pages from a list function; returns (items, page_sizes)."""
    items, sizes = [], []
    cursor = None
    while True:
        current = list(args)
        current[-1] = limit
        if cursor is not None:
            # Every scanned function is (anchor, cursor..., limit).
            current = [args[0]] + cursor + [limit]
        response = call_list(conn, name, current)
        assert_list_envelope(response, limit)
        items.extend(response["items"])
        sizes.append(len(response["items"]))
        if not response["has_more"]:
            return items, sizes
        assert response["next_cursor"] is not None, response
        next_cursor = response["next_cursor"]
        if "created_at" in next_cursor:
            id_key = next(key for key in next_cursor if key != "created_at")
            cursor = [next_cursor["created_at"], next_cursor[id_key]]
        else:
            cursor = [next(iter(next_cursor.values()))]
        assert len(cursor) > 0


def seed_creator(owner):
    creator = uuid4()
    with owner.cursor() as cur:
        effect(cur, creator, kind="command_scope_control", status="succeeded",
               outcome=Json({"ok": True}), settled_at=datetime.now(timezone.utc))
    owner.commit()
    return creator


def seed_scope(owner, *, owner_principal=None, creator=None, parent_id=None,
               root_id=None, close_requested_at=None, closed_at=None,
               realm_routes=None):
    scope_id = uuid4()
    creator = creator or seed_creator(owner)
    values = dict(
        scope_id=scope_id,
        parent_id=parent_id,
        root_id=root_id if root_id is not None else (parent_id or scope_id),
        route_path=[parent_id, scope_id] if parent_id is not None else [scope_id],
        realm_routes=Json(realm_routes or {}),
        owner_principal=owner_principal or uuid4(),
        created_by_effect=creator,
        close_requested_at=close_requested_at,
        closed_at=closed_at,
    )
    with owner.cursor() as cur:
        scope(cur, creator=creator, **values)
    owner.commit()
    return scope_id


def seed_install(owner, scope_id, *, creator=None, identity=None,
                 state="installed", requires=None, provides=None,
                 artifact_digest=None, adapter_digest=None,
                 owner_principal=None, owner_fiber_id=None,
                 owner_episode_id=None):
    install_id = uuid4()
    creator = creator or seed_creator(owner)
    with owner.cursor() as cur:
        insert(
            cur, "installs",
            install_id=install_id, scope_id=scope_id,
            owner_fiber_id=owner_fiber_id, owner_episode_id=owner_episode_id,
            identity=identity or f"g8-{install_id}",
            version="1",
            manifest=Json({"identity": identity or f"g8-{install_id}", "version": "1"}),
            manifest_digest=DIGEST,
            requires=Json(requires or []),
            provides=Json(provides or []),
            artifact_digest=artifact_digest if artifact_digest is not None else DIGEST,
            adapter_digest=adapter_digest if adapter_digest is not None else DIGEST,
            owner_principal=owner_principal or uuid4(),
            state=state, created_by_effect=creator,
        )
    owner.commit()
    return install_id


def seed_fiber(owner, install_id, scope_id, *, creator=None, want_on=False,
               current_episode_id=None):
    fiber_id = uuid4()
    creator = creator or seed_creator(owner)
    with owner.cursor() as cur:
        insert(
            cur, "fibers", fiber_id=fiber_id, install_id=install_id,
            scope_id=scope_id, want_on=want_on, control_seq=0,
            current_episode_id=current_episode_id, next_contribution_seq=0,
            created_by_effect=creator,
        )
    owner.commit()
    return fiber_id


def seed_episode(owner, fiber_id, *, creator=None, epoch=1, state="active"):
    episode_id = uuid4()
    creator = creator or seed_creator(owner)
    with owner.cursor() as cur:
        insert(
            cur, "episodes", episode_id=episode_id, fiber_id=fiber_id,
            epoch=epoch, activation_effect=creator, state=state, target_seq=0,
        )
    owner.commit()
    return episode_id


def seed_slot(owner, fiber_id, episode_id, *, creator=None, realm="g8",
              key=None, seq=1, descriptor=None):
    slot_id = uuid4()
    creator = creator or seed_creator(owner)
    with owner.cursor() as cur:
        insert(
            cur, "slots", slot_id=slot_id, fiber_id=fiber_id,
            episode_id=episode_id, realm=realm, key=key or f"k-{slot_id}",
            descriptor=Json(descriptor or {"v": 1, "tool": {"parameters": {"type": "object"}}}),
            descriptor_digest=DIGEST, contribution_seq=seq,
        )
    owner.commit()
    return slot_id


def seed_pin(owner, *, consumer_type="run", consumer_run_id=None,
             consumer_episode_id=None, epoch=1, key="dep", slot_id,
             provider_fiber_id, provider_episode_id, creator=None,
             released_by_effect=None, released_at=None):
    pin_id = uuid4()
    creator = creator or seed_creator(owner)
    with owner.cursor() as cur:
        insert(
            cur, "pins", pin_id=pin_id, consumer_type=consumer_type,
            consumer_episode_id=consumer_episode_id,
            consumer_run_id=consumer_run_id, consumer_epoch=epoch, key=key,
            slot_id=slot_id, provider_fiber_id=provider_fiber_id,
            provider_episode_id=provider_episode_id,
            descriptor_digest=DIGEST, created_by_effect=creator,
            released_by_effect=released_by_effect, released_at=released_at,
        )
    owner.commit()
    return pin_id


def seed_run(owner, scope_id, *, creator=None, status="running",
             remaining_steps=8, remaining_tool_calls=4,
             remaining_tokens=10000, remaining_wall_ms=600000,
             interaction=None):
    run_id = uuid4()
    creator = creator or seed_creator(owner)
    with owner.cursor() as cur:
        insert(
            cur, "runs", run_id=run_id, scope_id=scope_id, status=status,
            epoch_no=1, registration_generation=1, turn_no=0,
            driving_generation=0, remaining_steps=remaining_steps,
            remaining_tokens=remaining_tokens,
            remaining_tool_calls=remaining_tool_calls,
            remaining_wall_ms=remaining_wall_ms,
            interaction=Json(interaction) if interaction is not None else None,
        )
    owner.commit()
    return run_id


def seed_request(owner, principal_id, request_key, *,
                 kind="command_scope_control", request_bytes=b"{}",
                 response=None, effect_id=None):
    effect_id = effect_id or seed_effect(owner)
    with owner.cursor() as cur:
        insert(
            cur, "requests", principal_id=principal_id, request_key=request_key,
            kind=kind, request_bytes=request_bytes,
            request_digest=hashlib.sha256(request_bytes).digest(),
            effect_id=effect_id, response=Json(response or {"ok": True}),
        )
    owner.commit()
    return effect_id


def seed_effect(owner, *, scope_id=None, run_id=None, fiber_id=None,
                episode_id=None, pin_id=None, kind="host_prepare",
                status="ready", request=None, replay_policy="replay_safe",
                attempt_no=0, fence=0, claim_owner=None,
                lease_until=None, outcome=None, settled_at=None,
                parent_effect_id=None, ordinal=None, epoch_no=None,
                generation=None, cancel_requested=False,
                resource_quiesced_at=None):
    effect_id = uuid4()
    with owner.cursor() as cur:
        effect(
            cur, effect_id, requester_id=uuid4(), scope_id=scope_id,
            run_id=run_id, fiber_id=fiber_id, episode_id=episode_id,
            pin_id=pin_id, kind=kind, status=status,
            request=Json(request or {}), replay_policy=replay_policy,
            attempt_no=attempt_no, fence=fence, claim_owner=claim_owner,
            lease_until=lease_until, outcome=None if outcome is None else Json(outcome),
            settled_at=settled_at, parent_effect_id=parent_effect_id,
            ordinal=ordinal, epoch_no=epoch_no, generation=generation,
            cancel_requested=cancel_requested,
            resource_quiesced_at=resource_quiesced_at,
        )
    owner.commit()
    return effect_id


def seed_history(owner, scope_id, install_id, count, *, prefix="g8-h"):
    if count <= 0:
        return []
    with owner.cursor() as cur:
        cur.execute(
            """INSERT INTO v24.effects
                 (effect_id, requester_id, scope_id, kind, status, request,
                  request_digest, replay_policy, outcome, settled_at,
                  resource_quiesced_at)
               SELECT md5(%s || ':' || g)::uuid, %s, %s, 'host_prepare',
                      'succeeded',
                      jsonb_build_object('install_id', %s, 'history', g),
                      %s, 'replay_safe',
                      jsonb_build_object('v',1,'class','success','claim',NULL,
                        'body',jsonb_build_object('kind','host_prepare',
                          'result',jsonb_build_object('v',1,'observed','ok'))),
                      now(), now()
                 FROM generate_series(1, %s) AS g""",
            (prefix, str(uuid4()), scope_id, str(install_id), b"g8-history", count),
        )
    owner.commit()
    return count


def seed_claim_target(owner, scope_id, install_id, *, prefix="g8-target"):
    return seed_effect(
        owner, scope_id=scope_id, kind="host_prepare", status="ready",
        request={"install_id": str(install_id), "target": prefix},
        replay_policy="replay_safe",
    )


# ---------------------------------------------------------------------------
# Fixture-only closure probe.
#
# The full recursive CTE is extracted verbatim from 30_advance.sql.  A frozen
# hash plus an equality check against the installed probe body means a kernel
# closure change cannot silently leave this measurement on an old formula.
# The probe declares the same lvalue used by advance, so no re-writing of the
# CTE is needed.
# ---------------------------------------------------------------------------
_ADVANCE = (V24 / "sql" / "30_advance.sql").read_text(encoding="utf-8")
_START = "WITH RECURSIVE closure(entity_type, entity_id) AS ("
_END = ") SELECT jsonb_object_agg(entity_type, ids) INTO v_closure FROM grouped;"
_start_at = _ADVANCE.index(_START)
_end_at = _ADVANCE.index(_END, _start_at) + len(_END)
CLOSURE_SQL = _ADVANCE[_start_at:_end_at]
CLOSURE_SHA256 = "e9b15387dd41fd1621ec2aaec964e70c900cea8a0468b03242fd8b46528efba5"


def install_closure_probe(owner):
    digest = hashlib.sha256(CLOSURE_SQL.encode("utf-8")).hexdigest()
    assert digest == CLOSURE_SHA256, (
        "30_advance.sql closure block changed; update the probe and its frozen "
        f"hash deliberately (got {digest})")
    body = f"""
DECLARE
  v_closure jsonb;
BEGIN
{CLOSURE_SQL}
  RETURN v_closure;
END;
"""
    with owner.cursor() as cur:
        cur.execute("DROP FUNCTION IF EXISTS v24_fake.closure_probe(uuid,text,jsonb)")
        cur.execute(
            "CREATE FUNCTION v24_fake.closure_probe(p_effect_id uuid, "
            "v_class text, v_body jsonb) RETURNS jsonb LANGUAGE plpgsql STABLE "
            "SET search_path = pg_catalog, v24 AS $probe$" + body + "$probe$")
    owner.commit()
    prose = one(owner, """SELECT prosrc FROM pg_proc
        WHERE pronamespace='v24_fake'::regnamespace AND proname='closure_probe'""")
    owner.rollback()
    assert CLOSURE_SQL in prose, "probe body no longer contains the frozen CTE"


def closure_size(owner, effect_id, body=None, v_class="claim"):
    value = one(
        owner,
        "SELECT v24_fake.closure_probe(%s,%s,%s)",
        (effect_id, v_class, Json(body or {"lease_ms": 300000})),
    )
    owner.rollback()
    return sum(len(v) for v in value.values()), value


def claim_probe(service, effect_id, lease=300000):
    response = advance(service, effect_id, claim(lease))
    service.commit()
    return response


def now_minus(seconds):
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)
