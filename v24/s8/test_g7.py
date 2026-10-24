"""G7 W1+W2: spawn admission, child run/edge/quota, first model, same-key
replay/conflict and the optional owner run pin.

W1 covers G7-A/D/E/F.  W2 adds same-key replay/conflict (`spawn_key_conflict`),
the §4.6 owner pin with the prospective toolset digest, and G7-B/C/H plus the
seven mandatory negatives N1-N7.  W3 adds child-first-model recovery (G7-G)
through the real public `v24.command_recover`.
The gate drives the real public loop (`v24.start` -> claim -> `v24.advance`) on
a fixture whose provider fiber is seeded by the repository's own S2 helper; it
never opens a socket, invokes a provider or performs external IO.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from uuid import UUID, uuid4

import psycopg2
from psycopg2.extras import Json

ROOT = Path(__file__).resolve().parent
S1 = ROOT.parent / "s1"
S2 = ROOT.parent / "s2"
S4 = ROOT.parent / "s4"
for _path in (S1, S2, S4):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from setup_db import (  # noqa: E402
    EXPECTED_TABLES,
    _assert_closed_catalog,
    server_helper_scope,
    setup_db,
)
from test_ddl import DIGEST, insert  # noqa: E402
from test_g2b import (  # noqa: E402
    cancel,
    claim_effect,
    effect_row,
    loop_fixture,
    read,
    run_row,
    serialized_race,
    start,
    steer,
)
from test_g3a import advance, one, state  # noqa: E402

OWNER_KEYS = frozenset("""v disposition effect_id emitted revision claim""".split())
TEN_TABLES = tuple(sorted(EXPECTED_TABLES))
SPAWN_KEY = "agent.spawn"


def snapshot(owner) -> dict:
    """Ten-table byte snapshot; the owner transaction is reset afterwards."""
    value = state(owner)
    owner.rollback()
    return value


def sha256_canonical(owner, payload) -> str:
    value = one(
        owner,
        "SELECT encode(sha256(convert_to(v24.canonical_json(%s),'UTF8')),'hex')",
        (Json(payload),),
    )
    owner.rollback()
    return value


def child_run_id(owner, parent_run_id: str, spawn_key: str) -> str:
    value = one(
        owner,
        "SELECT md5(%s::text || ':spawn:' || %s)::uuid::text",
        (parent_run_id, spawn_key),
    )
    owner.rollback()
    return value


def child_effect_id(owner, run_id: str) -> str:
    value = one(
        owner,
        "SELECT md5(%s::text || ':model_call:0')::uuid::text",
        (run_id,),
    )
    owner.rollback()
    return value


def digest_hex(value) -> str:
    """to_jsonb(bytea) renders as a backslash-x string."""
    assert isinstance(value, str) and value.startswith("\\x"), value
    return value[2:]


def seed_activation_pin(owner, live, creator, *, epoch=1, key="plugin") -> dict:
    """Owner fixture: the single live activation pin of the owner episode."""
    pin_id = uuid4()
    with owner.cursor() as cur:
        insert(cur, "pins", pin_id=pin_id, consumer_type="activation",
               consumer_episode_id=live["episode"], consumer_run_id=None,
               consumer_epoch=epoch, key=key, slot_id=live["slot"],
               provider_fiber_id=live["fiber"],
               provider_episode_id=live["episode"],
               descriptor_digest=DIGEST, created_by_effect=creator)
    owner.commit()
    return {"pin_id": str(pin_id), "epoch": epoch, "key": key}


def make_parent(owner, service, realm: str, budget: dict,
                owner_mode=None) -> dict:
    """Start a real run and claim its first model effect.

    `owner_mode='pin'` seeds the §4.6 owner pair and one live activation pin;
    `owner_mode='no_pin'` exposes a live fiber/episode with no activation pin
    (the dependency_unresolved case).
    """
    root, live, creator = loop_fixture(owner, service, realm=realm)
    response, _raw = start(
        service, root, live["fiber"], {}, budget, f"g7-{realm}-{uuid4()}"
    )
    service.commit()
    assert response.get("disposition") == "committed", response
    assert len(response["emitted"]) == 2, response
    run_id, model_id = response["emitted"]
    model = effect_row(owner, model_id)
    assert model["kind"] == "model_call" and model["status"] == "ready", model
    token = claim_effect(service, model_id)
    pair = None
    if owner_mode is not None:
        epoch = one(owner, "SELECT epoch FROM v24.episodes WHERE episode_id=%s",
                    (live["episode"],))
        owner.rollback()
        activation = None
        if owner_mode == "pin":
            activation = seed_activation_pin(owner, live, creator, epoch=epoch)
        pair = {
            "fiber": str(live["fiber"]),
            "episode": str(live["episode"]),
            "slot": str(live["slot"]),
            "epoch": epoch,
            "descriptor_digest": "\\x" + DIGEST.hex(),
            "activation_pin": activation,
        }
    return {
        "scope_id": str(root),
        "run_id": str(run_id),
        "model_id": str(model_id),
        "model": model,
        "token": token,
        "budget": budget,
        "owner": pair,
    }


def next_parent_model(owner, service, parent: dict, instruction: str = "again") -> dict:
    """Steer the parent and claim the successor model effect (a new outcome)."""
    run = run_row(owner, parent["run_id"])
    response, _raw = steer(service, parent["run_id"], run["driving_generation"],
                           instruction, f"g7-steer-{uuid4()}")
    service.commit()
    assert response.get("disposition") == "committed", response
    model = read(
        owner,
        """SELECT to_jsonb(e) FROM v24.effects e
            WHERE e.run_id=%s AND e.kind='model_call'
              AND e.status IN ('ready','claimed')""",
        (UUID(parent["run_id"]),),
    )
    assert model is not None, "steer published no model effect"
    model_id = model["effect_id"]
    token = claim_effect(service, model_id)
    return {
        "scope_id": parent["scope_id"],
        "run_id": parent["run_id"],
        "model_id": model_id,
        "model": model,
        "token": token,
        "budget": parent["budget"],
        "owner": parent.get("owner"),
    }


def spawn_args(scope_id: str, spawn_key: str, budget: dict,
               input_value=None, owner_pair=None) -> dict:
    value = {
        "v": 1,
        "spawn_key": spawn_key,
        "input": input_value or {"messages": [{"role": "user", "content": "child"}]},
        "scope_id": scope_id,
        "budget": budget,
    }
    if owner_pair is not None:
        value["owner_fiber_id"] = owner_pair["fiber"]
        value["owner_episode_id"] = owner_pair["episode"]
    return value


def settle_spawn(service, parent: dict, args: dict, *, usage=None,
                 text: str = "spawn") -> dict:
    result = {"text": text, "tool_calls": [{"key": SPAWN_KEY, "args": args}]}
    if usage is not None:
        result["usage"] = usage
    outcome = {
        "v": 1,
        "class": "success",
        "claim": parent["token"],
        "body": {"kind": "model_call", "result": result},
    }
    response = advance(service, parent["model_id"], outcome)
    service.commit()
    return response


def spawn_events(owner, effect_id: str) -> list[dict]:
    value = one(
        owner,
        """SELECT coalesce(jsonb_agg(jsonb_build_object(
                 'seq',e.seq,'entity_id',e.entity_id::text,
                 'event_kind',e.event_kind,'payload',e.payload)
                 ORDER BY e.entity_id,e.seq),'[]'::jsonb)
             FROM v24.events e WHERE e.effect_id=%s""",
        (effect_id,),
    )
    owner.rollback()
    return value


def catalog_columns(owner) -> list:
    value = one(
        owner,
        """SELECT coalesce(jsonb_agg(jsonb_build_object(
                 'table',table_name,'column',column_name,'position',ordinal_position,
                 'type',data_type,'nullable',is_nullable,'default',column_default)
                 ORDER BY table_name,ordinal_position),'[]'::jsonb)
             FROM information_schema.columns WHERE table_schema='v24'""",
    )
    owner.rollback()
    return value


def catalog_indexes(owner) -> list:
    value = one(
        owner,
        """SELECT coalesce(jsonb_agg(jsonb_build_object(
                 'table',tablename,'index',indexname,'definition',indexdef)
                 ORDER BY tablename,indexname),'[]'::jsonb)
             FROM pg_indexes WHERE schemaname='v24'""",
    )
    owner.rollback()
    return value


def table_counts(owner) -> dict:
    value = one(
        owner,
        """SELECT jsonb_build_object(
             'fibers',(SELECT count(*) FROM v24.fibers),
             'installs',(SELECT count(*) FROM v24.installs),
             'slots',(SELECT count(*) FROM v24.slots),
             'episodes',(SELECT count(*) FROM v24.episodes))""",
    )
    owner.rollback()
    return value


def usage_for(parent: dict) -> dict:
    """Spend the whole parent reservation so the C19 refund is exactly zero."""
    return {"tokens": parent["model"]["request"]["reserve"]["tokens"], "wall_ms": 0}


def model_reserve(owner, grant) -> int:
    value = one(owner, "SELECT v24.model_reserve(%s)", (grant,))
    owner.rollback()
    return value


def elapsed_ms(owner, effect_id: str) -> int:
    """The interpreter's (now()-created_at) millisecond truncation.

    settled_at is the settlement transaction's now(), so this is exactly the
    value the interpreter used before it deducted the child wall.
    """
    value = one(
        owner,
        """SELECT (extract(epoch from (e.settled_at - e.created_at))*1000)::bigint
             FROM v24.effects e WHERE e.effect_id=%s""",
        (UUID(effect_id),),
    )
    owner.rollback()
    return int(value)


def pin_row(owner, pin_id) -> dict:
    return read(owner, "SELECT to_jsonb(p) FROM v24.pins p WHERE pin_id=%s",
                (pin_id,))


def child_counts(owner, parent_run_id: str) -> dict:
    value = one(
        owner,
        """SELECT jsonb_build_object(
             'children',(SELECT count(*) FROM v24.runs
                          WHERE parent_run_id=%s),
             'effects',(SELECT count(*) FROM v24.effects e
                          JOIN v24.runs c ON c.run_id=e.run_id
                         WHERE c.parent_run_id=%s),
             'spawned',(SELECT count(*) FROM v24.events
                         WHERE entity_type='run' AND entity_id=%s
                           AND event_kind='run_spawned'),
             'started',(SELECT count(*) FROM v24.events
                         WHERE entity_type='run' AND event_kind='run_started'
                           AND payload->>'parent_run_id'=%s::text))""",
        (parent_run_id, parent_run_id, parent_run_id, parent_run_id),
    )
    owner.rollback()
    return value


def assert_handle(handle: dict, run_id: str, spawn_key: str,
                  effect_id: str, replayed: bool = False) -> None:
    assert set(handle) == {"run_id", "spawn_key", "child_effect_id", "replayed"}, handle
    assert handle["run_id"] == run_id, handle
    assert handle["spawn_key"] == spawn_key, handle
    assert handle["child_effect_id"] == effect_id, handle
    assert handle["replayed"] is replayed, handle


def assert_child_run(owner, parent: dict, args: dict, child_id: str,
                     parent_effect_id: str, owner_pair=None) -> dict:
    child = run_row(owner, child_id)
    assert child is not None, child_id
    assert child["scope_id"] == parent["scope_id"], child
    assert child["parent_run_id"] == parent["run_id"], child
    assert child["spawn_key"] == args["spawn_key"], child
    assert digest_hex(child["spawn_request_digest"]) == sha256_canonical(owner, args), child
    if owner_pair is None:
        assert child["owner_fiber_id"] is None, child
        assert child["owner_episode_id"] is None, child
        assert read(owner,
                    "SELECT count(*) FROM v24.pins WHERE consumer_run_id=%s",
                    (UUID(child_id),)) == 0, "ownerless child has a run pin"
    else:
        assert child["owner_fiber_id"] == owner_pair["fiber"], child
        assert child["owner_episode_id"] == owner_pair["episode"], child
    assert child["status"] == "running", child
    assert child["epoch_no"] == 0 and child["registration_generation"] == 1, child
    assert child["turn_no"] == 0 and child["driving_generation"] == 0, child
    assert child["revision"] == 0 and child["ended_at"] is None, child
    assert child["remaining_steps"] == args["budget"]["steps"], child
    grant = args["budget"]["tokens"]
    reserve = model_reserve(owner, grant)
    expected_remaining = None if grant is None else grant - reserve
    assert child["remaining_tokens"] == expected_remaining, child
    if grant is not None:
        assert child["remaining_tokens"] + reserve == grant, (
            child["remaining_tokens"], reserve, grant,
        )
    assert child["remaining_tool_calls"] == args["budget"]["tool_calls"], child
    assert child["remaining_wall_ms"] == args["budget"]["wall_ms"], child
    assert child["created_at"] is not None and child["updated_at"] is not None, child
    assert child["result"] is None and child["close_intent"] is None, child

    effect = effect_row(owner, child_effect_id(owner, child_id))
    assert effect is not None, child_id
    assert effect["parent_effect_id"] == parent_effect_id, effect
    assert effect["ordinal"] == 0 and effect["run_id"] == child_id, effect
    assert effect["scope_id"] == child["scope_id"], effect
    assert effect["kind"] == "model_call" and effect["status"] == "ready", effect
    assert effect["epoch_no"] == 0 and effect["generation"] == 0, effect
    assert effect["replay_policy"] == "no_replay", effect
    assert effect["pin_id"] is None, effect
    if owner_pair is None:
        assert effect["fiber_id"] is None and effect["episode_id"] is None, effect
    else:
        assert effect["fiber_id"] == owner_pair["fiber"], effect
        assert effect["episode_id"] == owner_pair["episode"], effect
        # The child model effect never carries effects.pin_id; the owner run
        # pin is a separate row located by its consumer triple.
        pins = read(
            owner,
            """SELECT coalesce(jsonb_agg(to_jsonb(p)),'[]'::jsonb)
                 FROM v24.pins p
                WHERE p.consumer_type='run' AND p.consumer_run_id=%s
                  AND p.released_at IS NULL""",
            (UUID(child_id),),
        )
        assert len(pins) == 1, pins
        pin = pins[0]
        assert pin["pin_id"] is not None, pin
        assert pin["consumer_type"] == "run", pin
        assert pin["consumer_run_id"] == child_id, pin
        assert pin["consumer_episode_id"] is None, pin
        assert pin["consumer_epoch"] == owner_pair["epoch"], pin
        assert pin["key"] == "run", pin
        assert pin["slot_id"] == owner_pair["slot"], pin
        assert pin["provider_fiber_id"] == owner_pair["fiber"], pin
        assert pin["provider_episode_id"] == owner_pair["episode"], pin
        assert pin["descriptor_digest"] == owner_pair["descriptor_digest"], pin
        assert pin["created_by_effect"] == parent_effect_id, pin
        assert pin["released_at"] is None, pin
        assert pin["released_by_effect"] is None, pin
    request = effect["request"]
    assert request["v"] == 1 and request["cause"] == "spawn", request
    assert request["run_id"] == child_id, request
    assert request["epoch_no"] == 0 and request["generation"] == 0, request
    assert request["input"] == args["input"], request
    assert request["reserve"] == {"tokens": reserve}, request
    assert request["spawn_key"] == args["spawn_key"], request
    assert request["parent_run_id"] == parent["run_id"], request
    assert request["digests"] == one(
        owner, "SELECT v24.model_digests(%s)", (UUID(child_id),)
    ), request
    owner.rollback()
    return child


def assert_spawn_events(owner, parent: dict, args: dict, child_id: str,
                        effect_id: str) -> None:
    events = spawn_events(owner, parent["model_id"])
    kinds = [event["event_kind"] for event in events]
    assert sorted(kinds) == sorted(
        ["model_call_settled", "run_spawned", "run_started"]
    ), events
    parent_event = next(e for e in events if e["event_kind"] == "run_spawned")
    assert parent_event["entity_id"] == parent["run_id"], parent_event
    assert parent_event["seq"] >= 1, parent_event
    assert parent_event["payload"] == {
        "child_run_id": child_id,
        "spawn_key": args["spawn_key"],
        "child_effect_id": effect_id,
        "spawn_request_digest": sha256_canonical(owner, args),
    }, parent_event
    child_event = next(e for e in events if e["event_kind"] == "run_started")
    assert child_event["entity_id"] == child_id, child_event
    assert child_event["seq"] == 1, child_event
    assert child_event["payload"] == {
        "run_id": child_id,
        "parent_run_id": parent["run_id"],
        "spawn_key": args["spawn_key"],
    }, child_event
    settled = next(e for e in events if e["event_kind"] == "model_call_settled")
    assert settled["entity_id"] == parent["run_id"], settled


def g7_a(db, owner) -> None:
    """G7-A: one advance atomically creates child/edge/quota/effect/events."""
    service = db.connect("service")
    parent = make_parent(
        owner, service, "g7a",
        {"steps": 5, "tool_calls": 3, "tokens": 5000, "wall_ms": 600000},
    )
    before = run_row(owner, parent["run_id"])
    args = spawn_args(
        parent["scope_id"], "child-a",
        {"steps": 2, "tokens": 300, "tool_calls": 1, "wall_ms": 5000},
    )
    run_id = child_run_id(owner, parent["run_id"], "child-a")
    effect_id = child_effect_id(owner, run_id)

    response = settle_spawn(service, parent, args, usage=usage_for(parent))
    assert set(response) == OWNER_KEYS | {"spawned"}, response
    assert response["v"] == 1 and response["disposition"] == "committed", response
    assert response["effect_id"] == parent["model_id"], response
    assert response["claim"] is None and response["emitted"] == [], response
    assert len(response["spawned"]) == 1, response
    assert_handle(response["spawned"][0], run_id, "child-a", effect_id)

    child = assert_child_run(owner, parent, args, run_id, parent["model_id"])
    after = run_row(owner, parent["run_id"])
    assert after["status"] == "running", after
    grant = args["budget"]["tokens"]
    parent_reserve = parent["model"]["request"]["reserve"]["tokens"]
    parent_usage = usage_for(parent)["tokens"]
    post_tokens = before["remaining_tokens"] + parent_reserve - parent_usage
    assert after["remaining_tokens"] == post_tokens - grant, (
        before["remaining_tokens"], parent_reserve, parent_usage, grant,
        after["remaining_tokens"],
    )
    assert after["remaining_steps"] == before["remaining_steps"] - child["remaining_steps"], (
        before["remaining_steps"], after["remaining_steps"], child["remaining_steps"],
    )
    assert after["remaining_tool_calls"] == (
        before["remaining_tool_calls"] - child["remaining_tool_calls"]
    ), (
        before["remaining_tool_calls"], after["remaining_tool_calls"],
        child["remaining_tool_calls"],
    )
    elapsed = elapsed_ms(owner, parent["model_id"])
    wall_before = max(0, before["remaining_wall_ms"] - elapsed)
    assert after["remaining_wall_ms"] == wall_before - child["remaining_wall_ms"], (
        before["remaining_wall_ms"], elapsed, after["remaining_wall_ms"],
        child["remaining_wall_ms"],
    )
    assert before["remaining_wall_ms"] - elapsed == (
        after["remaining_wall_ms"] + child["remaining_wall_ms"]
    ), (before["remaining_wall_ms"], elapsed, after["remaining_wall_ms"])
    assert after["turn_no"] == before["turn_no"] + 1, after
    assert after["revision"] == before["revision"] + 1, after

    # The spawn edge is the child's three columns, guarded by u_runs_spawn.
    edge = one(
        owner,
        """SELECT jsonb_build_object(
             'parent_run_id',r.parent_run_id,'spawn_key',r.spawn_key,
             'spawn_request_digest',r.spawn_request_digest)
             FROM v24.runs r WHERE r.run_id=%s""",
        (UUID(run_id),),
    )
    owner.rollback()
    assert edge == {
        "parent_run_id": parent["run_id"],
        "spawn_key": "child-a",
        "spawn_request_digest": "\\x" + sha256_canonical(owner, args),
    }, edge
    index_def = one(
        owner,
        """SELECT indexdef FROM pg_indexes
            WHERE schemaname='v24' AND indexname='u_runs_spawn'""",
    )
    owner.rollback()
    assert "parent_run_id" in index_def and "spawn_key" in index_def, index_def

    assert_spawn_events(owner, parent, args, run_id, effect_id)

    # The child first model is a normal claimable effect under cause='spawn'.
    child_token = claim_effect(service, effect_id)
    assert child_token["attempt"] == 1 and child_token["fence"] == 1, child_token
    claimed = effect_row(owner, effect_id)
    assert claimed["status"] == "claimed", claimed
    assert claimed["claim_owner"] == child_token["owner"], claimed

    # Failure injection, once each on the child run insert, the child effect
    # insert and the parent quota update.  Every failure must roll the whole
    # advance back and leave the model effect claimed.
    failure_parent = make_parent(
        owner, service, "g7a-fault",
        {"steps": 5, "tool_calls": 3, "tokens": 5000, "wall_ms": 600000},
    )
    failure_args = spawn_args(
        failure_parent["scope_id"], f"child-fault-{uuid4()}",
        {"steps": 1, "tokens": 200, "tool_calls": 1, "wall_ms": 1000},
    )
    for mode in ("run", "effect", "quota"):
        before_fault = snapshot(owner)
        _install_fault(owner, mode, failure_parent)
        try:
            advance(
                service,
                failure_parent["model_id"],
                _spawn_outcome(failure_parent, failure_args),
            )
        except psycopg2.Error as exc:
            service.rollback()
            assert exc.pgcode == "P0001", (mode, exc.pgcode, str(exc))
        else:
            raise AssertionError(f"{mode} fault injection did not raise")
        _drop_fault(owner, mode)
        after_fault = snapshot(owner)
        assert after_fault == before_fault, (mode, "spawn failure left rows")
        effect = effect_row(owner, failure_parent["model_id"])
        assert effect["status"] == "claimed", (mode, effect)

    print("[G7-A] child run+edge+quota+first model+events in one advance; "
          "run/effect/quota fault injection rolls the whole advance back")


def _spawn_outcome(parent: dict, args: dict) -> dict:
    return {
        "v": 1,
        "class": "success",
        "claim": parent["token"],
        "body": {
            "kind": "model_call",
            "result": {
                "text": "spawn",
                "tool_calls": [{"key": SPAWN_KEY, "args": args}],
                "usage": usage_for(parent),
            },
        },
    }


def _install_fault(owner, mode: str, parent: dict) -> None:
    with owner.cursor() as cur:
        if mode == "run":
            cur.execute(
                """CREATE FUNCTION v24_fake.g7a_block_run() RETURNS trigger
                   LANGUAGE plpgsql AS $$
                   BEGIN
                     RAISE EXCEPTION 'g7a injected child run fault'
                       USING ERRCODE='P0001';
                   END $$"""
            )
            cur.execute(
                """CREATE TRIGGER g7a_block_run BEFORE INSERT ON v24.runs
                   FOR EACH ROW WHEN (NEW.parent_run_id IS NOT NULL)
                   EXECUTE FUNCTION v24_fake.g7a_block_run()"""
            )
        elif mode == "effect":
            cur.execute(
                """CREATE FUNCTION v24_fake.g7a_block_effect() RETURNS trigger
                   LANGUAGE plpgsql AS $$
                   BEGIN
                     IF NEW.kind='model_call'
                        AND NEW.parent_effect_id = TG_ARGV[0]::uuid THEN
                       RAISE EXCEPTION 'g7a injected child effect fault'
                         USING ERRCODE='P0001';
                     END IF;
                     RETURN NEW;
                   END $$"""
            )
            cur.execute(
                """CREATE TRIGGER g7a_block_effect BEFORE INSERT ON v24.effects
                   FOR EACH ROW
                   EXECUTE FUNCTION v24_fake.g7a_block_effect(%s)""",
                (parent["model_id"],),
            )
        elif mode == "quota":
            cur.execute(
                """CREATE FUNCTION v24_fake.g7a_block_update() RETURNS trigger
                   LANGUAGE plpgsql AS $$
                   BEGIN
                     IF NEW.run_id = TG_ARGV[0]::uuid
                        AND NEW.revision > OLD.revision THEN
                       RAISE EXCEPTION 'g7a injected quota update fault'
                         USING ERRCODE='P0001';
                     END IF;
                     RETURN NEW;
                   END $$"""
            )
            cur.execute(
                """CREATE TRIGGER g7a_block_update BEFORE UPDATE ON v24.runs
                   FOR EACH ROW
                   EXECUTE FUNCTION v24_fake.g7a_block_update(%s)""",
                (parent["run_id"],),
            )
        else:
            raise AssertionError(mode)
    owner.commit()


def _drop_fault(owner, mode: str) -> None:
    with owner.cursor() as cur:
        if mode == "run":
            cur.execute("DROP TRIGGER g7a_block_run ON v24.runs")
            cur.execute("DROP FUNCTION v24_fake.g7a_block_run()")
        elif mode == "effect":
            cur.execute("DROP TRIGGER g7a_block_effect ON v24.effects")
            cur.execute("DROP FUNCTION v24_fake.g7a_block_effect()")
        elif mode == "quota":
            cur.execute("DROP TRIGGER g7a_block_update ON v24.runs")
            cur.execute("DROP FUNCTION v24_fake.g7a_block_update()")
        else:
            raise AssertionError(mode)
    owner.commit()


def g7_d(db, owner) -> None:
    """G7-D: corrected token ledger, elapsed wall conservation, NULL and over-budget."""
    service = db.connect("service")

    # Finite tokens: let the parent refund its first reservation in full.  The
    # token check/deduction must use the post-refund v_tokens (5000), not the
    # pre-refund row balance (904): grant=300, reserve=300, child remaining=0.
    parent = make_parent(
        owner, service, "g7d",
        {"steps": 6, "tool_calls": 3, "tokens": 5000, "wall_ms": 600000},
    )
    before = run_row(owner, parent["run_id"])
    args = spawn_args(
        parent["scope_id"], "child-d",
        {"steps": 2, "tokens": 300, "tool_calls": 2, "wall_ms": 7000},
    )
    run_id = child_run_id(owner, parent["run_id"], "child-d")
    response = settle_spawn(
        service, parent, args, usage={"tokens": 0, "wall_ms": 0}
    )
    assert response["disposition"] == "committed", response
    child = assert_child_run(owner, parent, args, run_id, parent["model_id"])
    after = run_row(owner, parent["run_id"])
    grant = args["budget"]["tokens"]
    reserve = model_reserve(owner, grant)
    assert child["remaining_tokens"] == grant - reserve == 0, child
    assert child["remaining_tokens"] + reserve == grant, child
    parent_reserve = parent["model"]["request"]["reserve"]["tokens"]
    parent_usage = 0
    post_tokens = before["remaining_tokens"] + parent_reserve - parent_usage
    assert post_tokens == 5000, (before["remaining_tokens"], parent_reserve)
    assert after["remaining_tokens"] == post_tokens - grant, (
        before["remaining_tokens"], parent_reserve, parent_usage, grant,
        after["remaining_tokens"],
    )
    assert after["remaining_steps"] == before["remaining_steps"] - child["remaining_steps"]
    assert after["remaining_tool_calls"] == (
        before["remaining_tool_calls"] - child["remaining_tool_calls"]
    )
    elapsed = elapsed_ms(owner, parent["model_id"])
    wall_after = max(0, before["remaining_wall_ms"] - elapsed)
    assert after["remaining_wall_ms"] == wall_after - child["remaining_wall_ms"], (
        before["remaining_wall_ms"], elapsed, after["remaining_wall_ms"],
        child["remaining_wall_ms"],
    )
    assert before["remaining_wall_ms"] - elapsed == (
        after["remaining_wall_ms"] + child["remaining_wall_ms"]
    )
    print(
        f"[G7-D finite] grant={grant} reserve={reserve} "
        f"child_remaining={child['remaining_tokens']} "
        f"tokens_before={before['remaining_tokens']} tokens_after={after['remaining_tokens']} "
        f"wall_elapsed={elapsed} wall_after={after['remaining_wall_ms']}"
    )

    # NULL tokens: parent NULL keeps the token arithmetic exempt; the child
    # reserve is 0 and the child run also stores NULL.  Steps/tool/wall stay
    # conserved on their post-settlement values.
    null_parent = make_parent(
        owner, service, "g7d-null",
        {"steps": 5, "tool_calls": 3, "wall_ms": 600000},
    )
    before_null = run_row(owner, null_parent["run_id"])
    assert before_null["remaining_tokens"] is None, before_null
    null_args = spawn_args(
        null_parent["scope_id"], "child-d-null",
        {"steps": 1, "tokens": None, "tool_calls": 1, "wall_ms": 1000},
    )
    null_run_id = child_run_id(owner, null_parent["run_id"], "child-d-null")
    response = settle_spawn(
        service, null_parent, null_args, usage={"tokens": 0, "wall_ms": 0}
    )
    assert response["disposition"] == "committed", response
    child_null = assert_child_run(
        owner, null_parent, null_args, null_run_id, null_parent["model_id"]
    )
    after_null = run_row(owner, null_parent["run_id"])
    assert after_null["remaining_tokens"] is None, after_null
    assert child_null["remaining_tokens"] is None, child_null
    assert child_null["remaining_steps"] == null_args["budget"]["steps"], child_null
    assert after_null["remaining_steps"] == (
        before_null["remaining_steps"] - child_null["remaining_steps"]
    )
    assert after_null["remaining_tool_calls"] == (
        before_null["remaining_tool_calls"] - child_null["remaining_tool_calls"]
    )
    null_elapsed = elapsed_ms(owner, null_parent["model_id"])
    assert after_null["remaining_wall_ms"] == max(
        0, before_null["remaining_wall_ms"] - null_elapsed
    ) - child_null["remaining_wall_ms"], (
        before_null["remaining_wall_ms"], null_elapsed,
        after_null["remaining_wall_ms"], child_null["remaining_wall_ms"],
    )
    assert before_null["remaining_wall_ms"] - null_elapsed == (
        after_null["remaining_wall_ms"] + child_null["remaining_wall_ms"]
    )
    null_effect = effect_row(owner, child_effect_id(owner, null_run_id))
    assert null_effect["request"]["reserve"] == {"tokens": 0}, null_effect
    print(
        "[G7-D NULL] parent/child remaining_tokens=NULL, reserve=0; "
        "steps/tool_calls/wall conserved on post-settlement values"
    )

    # A finite parent cannot hand a NULL token budget to the child.
    finite_parent = make_parent(
        owner, service, "g7d-finite-null",
        {"steps": 4, "tool_calls": 2, "tokens": 3000, "wall_ms": 60000},
    )
    finite_before = snapshot(owner)
    bad_args = spawn_args(
        finite_parent["scope_id"], "child-bad-null",
        {"steps": 1, "tokens": None, "tool_calls": 1, "wall_ms": 1000},
    )
    response = settle_spawn(service, finite_parent, bad_args)
    assert response == {
        "v": 1, "error": {"code": "invalid_outcome", "detail": {}}
    }, response
    assert snapshot(owner) == finite_before, "finite parent + child NULL wrote rows"

    # Over-budget: steps and wall are each checked against the post-settlement
    # parent balance; both are budget_exceeded W0 with byte-equal snapshots.
    over_parent = make_parent(
        owner, service, "g7d-over",
        {"steps": 3, "tool_calls": 2, "tokens": 3000, "wall_ms": 60000},
    )
    over_run = run_row(owner, over_parent["run_id"])
    over_before = snapshot(owner)
    over_args = spawn_args(
        over_parent["scope_id"], "child-over",
        {"steps": over_run["remaining_steps"] + 1, "tokens": 100,
         "tool_calls": 1, "wall_ms": 1000},
    )
    response = settle_spawn(service, over_parent, over_args)
    assert response == {
        "v": 1, "error": {"code": "budget_exceeded", "detail": {}}
    }, response
    assert snapshot(owner) == over_before, "over-budget spawn wrote rows"
    assert run_row(owner, over_parent["run_id"]) == over_run, "over-budget changed quota"

    wall_over_args = spawn_args(
        over_parent["scope_id"], "child-over-wall",
        {"steps": 1, "tokens": 100, "tool_calls": 1,
         "wall_ms": over_run["remaining_wall_ms"] + 1},
    )
    response = settle_spawn(service, over_parent, wall_over_args)
    assert response == {
        "v": 1, "error": {"code": "budget_exceeded", "detail": {}}
    }, response
    assert snapshot(owner) == over_before, "wall over-budget spawn wrote rows"
    assert run_row(owner, over_parent["run_id"]) == over_run, (
        "wall over-budget changed quota"
    )

    print("[G7-D] grant-reserve child ledger, post-settlement token/wall "
          "conservation, NULL tokens exempt, finite+NULL invalid, steps and "
          "wall over-budget W0 unchanged")

def g7_e(db, owner) -> None:
    """G7-E: a child is a run, never a fiber/install/slot."""
    service = db.connect("service")
    parent = make_parent(
        owner, service, "g7e",
        {"steps": 5, "tool_calls": 3, "tokens": 5000, "wall_ms": 600000},
    )
    before = table_counts(owner)
    assert before["fibers"] > 0 and before["installs"] > 0 and before["slots"] > 0, before
    args = spawn_args(
        parent["scope_id"], "child-e",
        {"steps": 1, "tokens": 100, "tool_calls": 1, "wall_ms": 1000},
    )
    run_id = child_run_id(owner, parent["run_id"], "child-e")
    response = settle_spawn(service, parent, args, usage=usage_for(parent))
    assert response["disposition"] == "committed", response
    after = table_counts(owner)
    assert after == before, (before, after)
    child = run_row(owner, run_id)
    assert child["owner_fiber_id"] is None and child["owner_episode_id"] is None, child
    effect = effect_row(owner, child_effect_id(owner, run_id))
    assert effect["fiber_id"] is None and effect["episode_id"] is None, effect
    assert read(
        owner,
        "SELECT count(*) FROM v24.pins WHERE consumer_run_id=%s",
        (UUID(run_id),),
    ) == 0
    assert read(
        owner,
        "SELECT count(*) FROM v24.fibers WHERE fiber_id IN "
        "(SELECT fiber_id FROM v24.fibers WHERE install_id IS NULL)",
    ) == 0
    print("[G7-E] fibers/installs/slots/episodes unchanged; child has no fiber, "
          "no episode pin and no run pin")


def g7_f(db, owner) -> None:
    """G7-F: no new tables/columns/indexes, no IO, zero fake-journal rows."""
    sql_root = ROOT.parent / "sql"
    forbidden_ddl = (
        "create table", "create index", "create unique index", "create view",
        "create materialized view", "create extension", "add column",
    )
    for name in ("30_advance.sql", "40_interpreters.sql", "48_loop.sql"):
        source = (sql_root / name).read_text(encoding="utf-8").lower()
        for term in forbidden_ddl:
            assert term not in source, (name, term)
        for term in ("http", "dblink", "pg_sleep", "socket"):
            assert term not in source, (name, term)

    forbidden_imports = ("socket", "http", "urllib", "requests", "httpx", "aiohttp")
    for path in sorted(ROOT.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for name in forbidden_imports:
            assert re.search(
                rf"(?m)^\s*(?:from|import)\s+{re.escape(name)}\b", source
            ) is None, (path.name, name)

    _assert_closed_catalog(owner)
    before_columns = catalog_columns(owner)
    before_indexes = catalog_indexes(owner)
    assert any(
        index["index"] == "u_runs_spawn" for index in before_indexes
    ), before_indexes
    before_journal = read(owner, "SELECT count(*) FROM v24_fake.journal")

    service = db.connect("service")
    parent = make_parent(
        owner, service, "g7f",
        {"steps": 4, "tool_calls": 2, "tokens": 5000, "wall_ms": 600000},
    )
    args = spawn_args(
        parent["scope_id"], "child-f",
        {"steps": 1, "tokens": 100, "tool_calls": 1, "wall_ms": 1000},
    )
    response = settle_spawn(service, parent, args, usage=usage_for(parent))
    assert response["disposition"] == "committed", response

    assert catalog_columns(owner) == before_columns, "spawn changed columns"
    assert catalog_indexes(owner) == before_indexes, "spawn changed indexes"
    after_journal = read(owner, "SELECT count(*) FROM v24_fake.journal")
    assert before_journal == 0 and after_journal == 0, (
        before_journal, after_journal,
    )
    assert frozenset(
        name
        for name, kind in [
            (row["relname"], row["relkind"])
            for row in _relation_rows(owner)
        ]
        if kind in ("r", "p")
    ) == EXPECTED_TABLES
    print("[G7-F] no new table/column/index/view/extension; no socket/HTTP; "
          "v24_fake.journal gained 0 rows")


def assert_w0(owner, service, parent, args, code: str) -> None:
    """A business W0 leaves the ten tables byte-identical and the effect claimed."""
    before = snapshot(owner)
    response = settle_spawn(service, parent, args, usage=usage_for(parent))
    assert response == {"v": 1, "error": {"code": code, "detail": {}}}, (code, response)
    assert snapshot(owner) == before, f"{code} wrote rows"
    effect = effect_row(owner, parent["model_id"])
    assert effect["status"] == "claimed", (code, effect)


def replay_envelope(effect_id: str) -> dict:
    """The frozen advance-level receipt replay envelope (S2/S4)."""
    return {"v": 1, "disposition": "replay", "effect_id": effect_id,
            "emitted": [], "revision": 0, "claim": None}


def g7_b(db, owner) -> None:
    """G7-B: same key/bytes on a NEW parent outcome replays the same child."""
    service = db.connect("service")
    parent = make_parent(
        owner, service, "g7b",
        {"steps": 6, "tool_calls": 3, "tokens": 5000, "wall_ms": 600000},
    )
    args = spawn_args(
        parent["scope_id"], "child-b",
        {"steps": 2, "tokens": 300, "tool_calls": 1, "wall_ms": 5000},
    )
    run_id = child_run_id(owner, parent["run_id"], "child-b")
    effect_id = child_effect_id(owner, run_id)

    first = settle_spawn(service, parent, args, usage=usage_for(parent))
    assert first["disposition"] == "committed", first
    assert_handle(first["spawned"][0], run_id, "child-b", effect_id)
    child_before = run_row(owner, run_id)
    tokens_after_first = run_row(owner, parent["run_id"])["remaining_tokens"]
    counts = child_counts(owner, parent["run_id"])
    assert counts == {"children": 1, "effects": 1, "spawned": 1, "started": 1}, counts

    second_parent = next_parent_model(owner, service, parent)
    assert second_parent["model_id"] != parent["model_id"]
    second = settle_spawn(service, second_parent, args,
                          usage=usage_for(second_parent))
    assert second["disposition"] == "committed", second
    assert set(second) == OWNER_KEYS | {"spawned"}, second
    assert_handle(second["spawned"][0], run_id, "child-b", effect_id, replayed=True)
    assert run_row(owner, run_id) == child_before, "replay rewrote the child"
    assert child_counts(owner, parent["run_id"]) == counts, "replay minted a child/effect/event"
    # Steer already reserved the successor model against the parent balance, so a
    # full-reserve settlement consumes exactly that reservation.  Any second child
    # grant deduction would subtract another 300 here.
    usage = usage_for(second_parent)["tokens"]
    assert run_row(owner, parent["run_id"])["remaining_tokens"] == (
        tokens_after_first - usage
    ), "replay deducted the child grant a second time"

    before = snapshot(owner)
    third = advance(service, second_parent["model_id"],
                    _spawn_outcome(second_parent, args))
    service.commit()
    assert third == replay_envelope(second_parent["model_id"]), third
    assert snapshot(owner) == before, "receipt replay wrote rows"
    print("[G7-B] same (parent,key,bytes) on a new parent outcome: replayed=true, "
          "one child/effect/run_spawned, grant deducted once; exact advance replay is "
          "the frozen replay envelope with zero writes")


def g7_c(db, owner) -> None:
    """G7-C: same key/different bytes is spawn_key_conflict W0, zero writes."""
    service = db.connect("service")
    parent = make_parent(
        owner, service, "g7c",
        {"steps": 6, "tool_calls": 3, "tokens": 5000, "wall_ms": 600000},
    )
    args = spawn_args(
        parent["scope_id"], "child-c",
        {"steps": 2, "tokens": 300, "tool_calls": 1, "wall_ms": 5000},
    )
    first = settle_spawn(service, parent, args, usage=usage_for(parent))
    assert first["disposition"] == "committed", first
    counts = child_counts(owner, parent["run_id"])

    conflict_parent = next_parent_model(owner, service, parent)
    assert conflict_parent["model_id"] != parent["model_id"], "request_key must differ"
    other = spawn_args(
        parent["scope_id"], "child-c",
        {"steps": 2, "tokens": 300, "tool_calls": 1, "wall_ms": 5000},
        input_value={"messages": [{"role": "user", "content": "different bytes"}]},
        owner_pair=None,
    )
    before = snapshot(owner)
    response = settle_spawn(service, conflict_parent, other,
                            usage=usage_for(conflict_parent))
    assert response == {"v": 1,
                        "error": {"code": "spawn_key_conflict", "detail": {}}}, response
    assert snapshot(owner) == before, "spawn_key_conflict wrote rows"
    effect = effect_row(owner, conflict_parent["model_id"])
    assert effect["status"] == "claimed", effect
    assert child_counts(owner, parent["run_id"]) == counts, "conflict minted rows"
    print("[G7-C] same key/different bytes on a different request_key: 24th code "
          "spawn_key_conflict W0, ten tables byte-equal, model effect still claimed")


def g7_h(db, owner) -> None:
    """G7-H: args, quota, owner and terminal W0 classes leave no half state."""
    service = db.connect("service")
    budget = {"steps": 4, "tool_calls": 2, "tokens": 5000, "wall_ms": 600000}
    parent = make_parent(owner, service, "g7h", budget)
    base = spawn_args(
        parent["scope_id"], "child-h",
        {"steps": 1, "tokens": 100, "tool_calls": 1, "wall_ms": 1000},
    )
    bad_args = spawn_args(
        parent["scope_id"], "child-h",
        {"steps": 1, "tokens": None, "tool_calls": 1, "wall_ms": 1000},
    )
    assert_w0(owner, service, parent, bad_args, "invalid_outcome")
    over = spawn_args(
        parent["scope_id"], "child-h",
        {"steps": 99, "tokens": 100, "tool_calls": 1, "wall_ms": 1000},
    )
    assert_w0(owner, service, parent, over, "budget_exceeded")
    missing = spawn_args(
        parent["scope_id"], "child-h",
        {"steps": 1, "tokens": 100, "tool_calls": 1, "wall_ms": 1000},
        owner_pair={"fiber": str(uuid4()), "episode": str(uuid4())},
    )
    assert_w0(owner, service, parent, missing, "provider_unavailable")

    nopin = make_parent(owner, service, "g7hn", budget, owner_mode="no_pin")
    nopin_args = spawn_args(
        nopin["scope_id"], "child-hn",
        {"steps": 1, "tokens": 100, "tool_calls": 1, "wall_ms": 1000},
        owner_pair=nopin["owner"],
    )
    assert_w0(owner, service, nopin, nopin_args, "dependency_unresolved")

    terminal = make_parent(owner, service, "g7ht", budget)
    cancelled, _raw = cancel(service, terminal["run_id"], 1, f"g7ht-{uuid4()}")
    service.commit()
    assert cancelled.get("disposition") == "committed", cancelled
    assert_w0(owner, service, terminal, base, "already_terminal")
    print("[G7-H] invalid args / budget_exceeded / provider_unavailable / "
          "dependency_unresolved / already_terminal: ten tables byte-equal, effect claimed")


def n1(db, owner) -> None:
    """N1: two real connections, same key/bytes; one child, loser replays."""
    service_a = db.connect("service")
    service_b = db.connect("service")
    parent = make_parent(
        owner, service_a, "n1",
        {"steps": 5, "tool_calls": 3, "tokens": 5000, "wall_ms": 600000},
    )
    args = spawn_args(
        parent["scope_id"], "child-n1",
        {"steps": 1, "tokens": 300, "tool_calls": 1, "wall_ms": 1000},
    )
    run_id = child_run_id(owner, parent["run_id"], "child-n1")
    effect_id = child_effect_id(owner, run_id)
    before = run_row(owner, parent["run_id"])
    outcome = _spawn_outcome(parent, args)
    winner, winner_response, results, evidence = serialized_race(
        db,
        [
            ("a", service_a,
             lambda conn: advance(conn, parent["model_id"], outcome)),
            ("b", service_b,
             lambda conn: advance(conn, parent["model_id"], outcome)),
        ],
        "G7-N1-lock",
    )
    assert winner_response["disposition"] == "committed", winner_response
    assert_handle(winner_response["spawned"][0], run_id, "child-n1", effect_id)
    loser = "b" if winner == "a" else "a"
    assert results[loser] == replay_envelope(parent["model_id"]), results[loser]
    assert str(evidence["winner_pid"]) in evidence["blockers"], evidence
    assert evidence["ungranted_advisory"] >= 1, evidence
    counts = child_counts(owner, parent["run_id"])
    assert counts == {"children": 1, "effects": 1, "spawned": 1, "started": 1}, counts
    grant = args["budget"]["tokens"]
    reserve = parent["model"]["request"]["reserve"]["tokens"]
    usage = usage_for(parent)["tokens"]
    after = run_row(owner, parent["run_id"])
    assert after["remaining_tokens"] == (
        before["remaining_tokens"] + reserve - usage - grant
    ), "concurrent duplicate deducted the grant twice"
    print(f"[G7-N1] Barrier(2) same effect/bytes: one child; {loser} pid="
          f"{evidence['blocked_pid']} blocked on pg_blocking_pids={evidence['blockers']} "
          f"and replayed the frozen envelope; grant deducted once")


def n2(db, owner) -> None:
    """N2: two connections, same key/different bytes; exactly one child."""
    service_a = db.connect("service")
    service_b = db.connect("service")
    parent = make_parent(
        owner, service_a, "n2",
        {"steps": 6, "tool_calls": 3, "tokens": 5000, "wall_ms": 600000},
    )
    args_a = spawn_args(
        parent["scope_id"], "child-n2",
        {"steps": 1, "tokens": 300, "tool_calls": 1, "wall_ms": 1000},
        input_value={"messages": [{"role": "user", "content": "bytes a"}]},
    )
    args_b = spawn_args(
        parent["scope_id"], "child-n2",
        {"steps": 1, "tokens": 300, "tool_calls": 1, "wall_ms": 1000},
        input_value={"messages": [{"role": "user", "content": "bytes b"}]},
    )
    before = run_row(owner, parent["run_id"])
    winner, winner_response, results, evidence = serialized_race(
        db,
        [
            ("a", service_a,
             lambda conn: advance(conn, parent["model_id"],
                                  _spawn_outcome(parent, args_a))),
            ("b", service_b,
             lambda conn: advance(conn, parent["model_id"],
                                  _spawn_outcome(parent, args_b))),
        ],
        "G7-N2-lock",
    )
    assert winner_response["disposition"] == "committed", winner_response
    loser = "b" if winner == "a" else "a"
    assert results[loser]["error"]["code"] == "receipt_conflict", results[loser]
    assert evidence["ungranted_advisory"] >= 1, evidence
    counts = child_counts(owner, parent["run_id"])
    assert counts == {"children": 1, "effects": 1, "spawned": 1, "started": 1}, counts
    grant = args_a["budget"]["tokens"]
    reserve = parent["model"]["request"]["reserve"]["tokens"]
    usage = usage_for(parent)["tokens"]
    assert run_row(owner, parent["run_id"])["remaining_tokens"] == (
        before["remaining_tokens"] + reserve - usage - grant
    ), "loser wrote a quota delta"

    # The 24th code itself: a later parent outcome with the losing bytes.
    conflict_parent = next_parent_model(owner, service_a, parent)
    other = args_b if winner == "a" else args_a
    before_conflict = snapshot(owner)
    response = settle_spawn(service_a, conflict_parent, other,
                            usage=usage_for(conflict_parent))
    assert response == {"v": 1,
                        "error": {"code": "spawn_key_conflict", "detail": {}}}, response
    assert snapshot(owner) == before_conflict, "spawn_key_conflict wrote rows"
    assert effect_row(owner, conflict_parent["model_id"])["status"] == "claimed"
    print("[G7-N2] concurrent same key/different bytes: one committed child, loser "
          "receipt_conflict (G-serialized, no half state); a later outcome with the "
          "losing bytes reaches spawn_key_conflict W0")


def n3(db, owner) -> None:
    """N3: terminal/cancelled parent spawn is already_terminal W0."""
    service = db.connect("service")
    parent = make_parent(
        owner, service, "n3",
        {"steps": 4, "tool_calls": 2, "tokens": 5000, "wall_ms": 600000},
    )
    args = spawn_args(
        parent["scope_id"], "child-n3",
        {"steps": 1, "tokens": 100, "tool_calls": 1, "wall_ms": 1000},
    )
    cancelled, _raw = cancel(service, parent["run_id"], 1, f"n3-{uuid4()}")
    service.commit()
    assert cancelled.get("disposition") == "committed", cancelled
    assert_w0(owner, service, parent, args, "already_terminal")
    assert child_counts(owner, parent["run_id"])["children"] == 0
    print("[G7-N3] cancelled parent: already_terminal W0, no child, effect claimed")


def n4(db, owner) -> None:
    """N4: child quota above the parent remaining is budget_exceeded W0."""
    service = db.connect("service")
    parent = make_parent(
        owner, service, "n4",
        {"steps": 2, "tool_calls": 1, "tokens": 5000, "wall_ms": 600000},
    )
    before = run_row(owner, parent["run_id"])
    over = spawn_args(
        parent["scope_id"], "child-n4",
        {"steps": 3, "tokens": 100, "tool_calls": 1, "wall_ms": 1000},
    )
    assert_w0(owner, service, parent, over, "budget_exceeded")
    assert run_row(owner, parent["run_id"]) == before, "parent quota moved"
    assert child_counts(owner, parent["run_id"])["children"] == 0
    print("[G7-N4] child steps above parent remaining: budget_exceeded W0, parent "
          "run row byte-equal, no child")


def n5(db, owner) -> None:
    """N5: faults at child run / quota update / child effect roll everything back."""
    service = db.connect("service")
    parent = make_parent(
        owner, service, "n5",
        {"steps": 4, "tool_calls": 2, "tokens": 5000, "wall_ms": 600000},
        owner_mode="pin",
    )
    args = spawn_args(
        parent["scope_id"], "child-n5",
        {"steps": 1, "tokens": 200, "tool_calls": 1, "wall_ms": 1000},
        owner_pair=parent["owner"],
    )
    for mode in ("run", "quota", "effect"):
        before = snapshot(owner)
        _install_fault(owner, mode, parent)
        try:
            advance(service, parent["model_id"], _spawn_outcome(parent, args))
        except psycopg2.Error as exc:
            service.rollback()
            assert exc.pgcode == "P0001", (mode, exc.pgcode, str(exc))
        else:
            raise AssertionError(f"{mode} fault injection did not raise")
        _drop_fault(owner, mode)
        assert snapshot(owner) == before, (mode, "spawn failure left rows")
        assert effect_row(owner, parent["model_id"])["status"] == "claimed", mode
    assert child_counts(owner, parent["run_id"])["children"] == 0
    print("[G7-N5] owner-pin spawn: faults at child run / quota update / child "
          "effect roll back the child, pin, quota and events; effect stays claimed")


def n6(db, owner) -> None:
    """N6: same request_key replay is the frozen envelope and never re-deducts."""
    service = db.connect("service")
    parent = make_parent(
        owner, service, "n6",
        {"steps": 5, "tool_calls": 3, "tokens": 5000, "wall_ms": 600000},
    )
    args = spawn_args(
        parent["scope_id"], "child-n6",
        {"steps": 1, "tokens": 300, "tool_calls": 1, "wall_ms": 1000},
    )
    outcome = _spawn_outcome(parent, args)
    first = advance(service, parent["model_id"], outcome)
    service.commit()
    assert first["disposition"] == "committed", first
    after_first = run_row(owner, parent["run_id"])
    counts = child_counts(owner, parent["run_id"])
    before = snapshot(owner)
    second = advance(service, parent["model_id"], outcome)
    service.commit()
    third = advance(service, parent["model_id"], outcome)
    service.commit()
    assert second == replay_envelope(parent["model_id"]), second
    assert third == second, "repeated receipt replay is not byte-equal"
    assert snapshot(owner) == before, "receipt replay wrote rows"
    assert run_row(owner, parent["run_id"]) == after_first
    assert child_counts(owner, parent["run_id"]) == counts
    print("[G7-N6] same request_key/bytes twice: byte-equal frozen replay envelope, "
          "ten tables unchanged, one child and one grant deduction")


def n7(db, owner) -> None:
    """N7: spawn never adds/removes fibers, installs, slots or episodes."""
    service = db.connect("service")
    parent = make_parent(
        owner, service, "n7",
        {"steps": 4, "tool_calls": 2, "tokens": 5000, "wall_ms": 600000},
        owner_mode="pin",
    )
    before = table_counts(owner)
    args = spawn_args(
        parent["scope_id"], "child-n7",
        {"steps": 1, "tokens": 100, "tool_calls": 1, "wall_ms": 1000},
        owner_pair=parent["owner"],
    )
    run_id = child_run_id(owner, parent["run_id"], "child-n7")
    response = settle_spawn(service, parent, args, usage=usage_for(parent))
    assert response["disposition"] == "committed", response
    assert table_counts(owner) == before, "spawn changed fibers/installs/slots/episodes"
    child = assert_child_run(owner, parent, args, run_id, parent["model_id"],
                             owner_pair=parent["owner"])
    assert child["owner_fiber_id"] == parent["owner"]["fiber"], child
    assert read(owner, "SELECT count(*) FROM v24.fibers WHERE fiber_id=%s",
                (UUID(run_id),)) == 0
    print("[G7-N7] owner-pin spawn: fibers/installs/slots/episodes unchanged, child "
          "is a run with the owner pair and one run pin, never a fiber/install")


def expire_claim(owner, effect_id: str) -> None:
    """Seeded fixture: the crashed child claim's lease is made stale."""
    with owner.cursor() as cur:
        cur.execute(
            """-- seeded fixture: the crashed owner's lease is made stale
               UPDATE v24.effects SET lease_until = now() - interval '1 second'
                WHERE effect_id=%s""",
            (effect_id,),
        )
        assert cur.rowcount == 1, cur.rowcount
    owner.commit()


def g7_g(db, owner) -> None:
    """G7-G: public claim + command_recover settles the expired child-first model.

    The child is minted by the real spawn path with the §4.6 owner pair, so its
    first model is the spawn-shaped row S6 never sees: ``cause='spawn'`` and
    ``parent_effect_id`` pointing at the parent model.  ``model_call.pin_id`` is
    always NULL; the owner run pin is a separate ``pins`` row keyed by
    ``(consumer_type='run', consumer_run_id=child)``.  The claim is therefore the
    ordinary public claim path (attempt=1/fence=1), never a seeded fixture.  The
    expiry is S6's owner DML, and the convergence is the real public
    ``v24.command_recover``.  No second recovery path is involved; after the
    fixture setup the only domain write is the public recovery command.
    """
    service = db.connect("service")
    parent = make_parent(
        owner, service, "g7g",
        {"steps": 5, "tool_calls": 3, "tokens": 5000, "wall_ms": 600000},
        owner_mode="pin",
    )
    args = spawn_args(
        parent["scope_id"], "child-g",
        {"steps": 2, "tokens": 300, "tool_calls": 1, "wall_ms": 5000},
        owner_pair=parent["owner"],
    )
    run_id = child_run_id(owner, parent["run_id"], "child-g")
    effect_id = child_effect_id(owner, run_id)
    spawned = settle_spawn(service, parent, args, usage=usage_for(parent))
    assert spawned["disposition"] == "committed", spawned
    assert_handle(spawned["spawned"][0], run_id, "child-g", effect_id)

    child_seeded = run_row(owner, run_id)
    edge_before = {
        "parent_run_id": child_seeded["parent_run_id"],
        "spawn_key": child_seeded["spawn_key"],
        "spawn_request_digest": child_seeded["spawn_request_digest"],
    }
    assert edge_before == {
        "parent_run_id": parent["run_id"],
        "spawn_key": "child-g",
        "spawn_request_digest": "\\x" + sha256_canonical(owner, args),
    }, edge_before
    effect_seeded = effect_row(owner, effect_id)
    assert effect_seeded["kind"] == "model_call", effect_seeded
    assert effect_seeded["request"]["cause"] == "spawn", effect_seeded
    assert effect_seeded["request"]["spawn_key"] == "child-g", effect_seeded
    assert effect_seeded["request"]["parent_run_id"] == parent["run_id"], effect_seeded
    assert effect_seeded["parent_effect_id"] == parent["model_id"], effect_seeded
    assert effect_seeded["pin_id"] is None, effect_seeded
    child_pin_rows = read(
        owner,
        """SELECT coalesce(jsonb_agg(to_jsonb(p)),'[]'::jsonb)
             FROM v24.pins p
            WHERE p.consumer_type='run' AND p.consumer_run_id=%s
              AND p.released_at IS NULL""",
        (UUID(run_id),),
    )
    assert len(child_pin_rows) == 1, child_pin_rows
    child_pin = child_pin_rows[0]
    assert child_pin["consumer_run_id"] == run_id, child_pin
    child_pin_id = child_pin["pin_id"]

    # The real public claim path, replacing the old seeded-fixture bypass.  The
    # child model effect now has pin_id NULL, so the ordinary model claim is
    # legal and must mint attempt=1/fence=1 with the service login as owner.
    child_token = claim_effect(service, effect_id)
    assert child_token["attempt"] == 1 and child_token["fence"] == 1, child_token
    claimed = effect_row(owner, effect_id)
    assert claimed["status"] == "claimed", claimed
    assert claimed["attempt_no"] == 1 and claimed["fence"] == 1, claimed
    assert claimed["claim_owner"] == child_token["owner"], (claimed, child_token)
    assert claimed["lease_until"] is not None, claimed

    with owner.cursor() as cur:
        cur.execute(
            "UPDATE v24.runs SET pending_steer=%s WHERE run_id=%s",
            (Json({"instruction": "queued before recovery", "generation": 1,
                   "epoch": 0}), UUID(run_id)),
        )
        assert cur.rowcount == 1, cur.rowcount
    owner.commit()
    expire_claim(owner, effect_id)

    expired = effect_row(owner, effect_id)
    assert expired["status"] == "claimed", expired
    assert expired["lease_until"] is not None, expired
    lease_expired = read(
        owner,
        "SELECT lease_until < now() FROM v24.effects WHERE effect_id=%s",
        (UUID(effect_id),),
    )
    assert lease_expired is True, expired
    child_before = run_row(owner, run_id)
    assert child_before["status"] == "running", child_before
    assert child_before["ended_at"] is None, child_before
    assert child_before["pending_steer"] is not None, child_before
    assert child_before["interaction"] is None, child_before
    parent_before = run_row(owner, parent["run_id"])
    quota_fields = ("remaining_steps", "remaining_tokens",
                    "remaining_tool_calls", "remaining_wall_ms")
    quota_before = {field: parent_before[field] for field in quota_fields}
    counts_before = child_counts(owner, parent["run_id"])
    assert counts_before == {"children": 1, "effects": 1,
                             "spawned": 1, "started": 1}, counts_before
    effects_before = read(owner, "SELECT count(*) FROM v24.effects")

    raw = one(
        service,
        "SELECT v24.command_recover(%s,%s,16)::text",
        (parent["scope_id"], f"g7g-recover-{uuid4()}"),
    )
    service.commit()
    recovery = json.loads(raw)
    assert recovery.get("disposition") == "committed", recovery
    assert recovery["recovery"]["limit"] == 16, recovery
    assert recovery["recovery"]["candidates"] == [effect_id], (
        recovery["recovery"]["candidates"], effect_id)
    applied = {item["effect_id"]: item for item in recovery["recovery"]["applied"]}
    assert set(applied) == {effect_id}, applied
    assert applied[effect_id] == {
        "effect_id": effect_id, "kind": "model_call",
        "replay_policy": "no_replay", "action": "settle_unknown",
        "reason": "lease_expired", "attempt_no": 1, "fence": 1,
        "run_id": run_id, "install_id": None,
    }, applied[effect_id]
    assert recovery["recovery"]["manual_debt"] == 0, recovery
    assert recovery["recovery"]["has_more"] is False, recovery

    effect_after = effect_row(owner, effect_id)
    assert effect_after["status"] == "unknown", effect_after
    assert effect_after["attempt_no"] == 1 and effect_after["fence"] == 1, effect_after
    assert effect_after["claim_owner"] is None, effect_after
    assert effect_after["lease_until"] is None, effect_after
    assert effect_after["settled_at"] is not None, effect_after
    assert effect_after["outcome"]["class"] == "unknown", effect_after
    result = effect_after["outcome"]["body"]["result"]
    assert result["observed"] == "unknown", result
    assert result["reason"] == "lease_expired", result
    assert result["recovery"]["effect_id"] == effect_id, result
    assert effect_after["outcome"]["claim"] == {
        "attempt": 1, "fence": 1, "owner": child_token["owner"]}, effect_after

    child_after = run_row(owner, run_id)
    assert child_after["status"] == "blocked_unknown", child_after
    assert child_after["ended_at"] is not None, child_after
    assert child_after["interaction"] is None, child_after
    assert child_after["pending_steer"] is None, child_after
    edge_after = {
        "parent_run_id": child_after["parent_run_id"],
        "spawn_key": child_after["spawn_key"],
        "spawn_request_digest": child_after["spawn_request_digest"],
    }
    assert edge_after == edge_before, (edge_before, edge_after)
    assert child_after["scope_id"] == child_before["scope_id"], child_after

    counts_after = child_counts(owner, parent["run_id"])
    assert counts_after == counts_before, (counts_before, counts_after)
    assert read(
        owner,
        "SELECT count(*) FROM v24.effects WHERE run_id=%s AND kind='model_call'",
        (UUID(run_id),),
    ) == 1, "recovery minted a second child model"
    # The only new effect is the command_recover command row itself.
    effects_after = read(owner, "SELECT count(*) FROM v24.effects")
    assert effects_after == effects_before + 1, (
        effects_before, effects_after, "recovery minted a second effect")
    assert read(
        owner,
        "SELECT count(*) FROM v24.effects "
        "WHERE kind='command_recover' AND scope_id=%s",
        (parent["scope_id"],),
    ) == 1, "recovery did not mint exactly one command effect"
    parent_after = run_row(owner, parent["run_id"])
    quota_after = {field: parent_after[field] for field in quota_fields}
    assert quota_after == quota_before, (quota_before, quota_after)
    assert parent_after == parent_before, "recovery changed the parent run"
    child_pin_after = pin_row(owner, child_pin_id)
    assert child_pin_after["released_at"] is not None, child_pin_after
    assert child_pin_after["released_by_effect"] == effect_id, child_pin_after

    print(
        f"[G7-G] effect={effect_id} run={run_id} cause=spawn "
        f"child_model pin_id=NULL claimed(public:attempt={child_token['attempt']}/"
        f"fence={child_token['fence']},owner={child_token['owner']}) "
        f"lease_expired->{effect_after['status']} "
        f"child_run={child_before['status']}->{child_after['status']} "
        f"ended_at=set interaction={child_after['interaction']!r} "
        f"pending_steer=seeded->{child_after['pending_steer']!r} "
        f"edge=(parent_run_id={edge_after['parent_run_id']},"
        f"spawn_key={edge_after['spawn_key']},"
        f"spawn_request_digest={digest_hex(edge_after['spawn_request_digest'])}) "
        f"children={counts_before['children']}->{counts_after['children']} "
        f"child_effects={counts_before['effects']}->{counts_after['effects']} "
        f"effects_total={effects_before}->{effects_after}"
        f"(+1 command_recover receipt) "
        f"parent_quota={quota_before}->{quota_after} "
        f"run_pin={child_pin_id} "
        f"released={child_pin_after['released_at'] is not None} "
        f"released_by_effect={child_pin_after['released_by_effect']}"
    )
    print(
        "[G7-G evidence] "
        f"model_pin_id_before_claim={effect_seeded['pin_id']!r} "
        f"claim={json.dumps(child_token, sort_keys=True)} "
        f"lease_until={expired['lease_until']} "
        f"lease_expired={lease_expired} "
        f"effect_status={effect_after['status']} "
        f"effect_outcome_class={effect_after['outcome']['class']} "
        f"observed={result['observed']} reason={result['reason']} "
        f"outcome_claim={json.dumps(effect_after['outcome']['claim'], sort_keys=True)} "
        f"child_status={child_after['status']} "
        f"ended_at={child_after['ended_at']} "
        f"interaction={child_after['interaction']!r} "
        f"pending_steer={child_after['pending_steer']!r} "
        f"edge={json.dumps(edge_after, sort_keys=True)} "
        f"child_counts={json.dumps(counts_after, sort_keys=True)} "
        f"parent_quota_before={json.dumps(quota_before, sort_keys=True)} "
        f"parent_quota_after={json.dumps(quota_after, sort_keys=True)} "
        f"run_pin={child_pin_id} "
        f"run_pin_released_at={child_pin_after['released_at']} "
        f"run_pin_released_by={child_pin_after['released_by_effect']}"
    )


def _relation_rows(owner) -> list[dict]:
    value = one(
        owner,
        """SELECT coalesce(jsonb_agg(jsonb_build_object(
                 'relname',c.relname,'relkind',c.relkind)
                 ORDER BY c.relname,c.relkind),'[]'::jsonb)
             FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='v24'""",
    )
    owner.rollback()
    return value


CHECKS = {
    "g7_a": g7_a,
    "g7_b": g7_b,
    "g7_c": g7_c,
    "g7_d": g7_d,
    "g7_e": g7_e,
    "g7_f": g7_f,
    "g7_g": g7_g,
    "g7_h": g7_h,
    "n1": n1,
    "n2": n2,
    "n3": n3,
    "n4": n4,
    "n5": n5,
    "n6": n6,
    "n7": n7,
}
DEFAULT_ONLY = "g7_a,g7_b,g7_c,g7_d,g7_e,g7_f,g7_g,g7_h,n1,n2,n3,n4,n5,n6,n7"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="v24 S8 W1-W3 G7 spawn/child-run gate")
    parser.add_argument(
        "--only", default=DEFAULT_ONLY,
        help="comma-separated checks (G7-A/B/C/D/E/F/G/H, n1-n7); the default "
             "runs every W1-W3 check exactly once",
    )
    args = parser.parse_args(argv)
    selected = [item.strip() for item in args.only.split(",") if item.strip()]
    assert selected, "--only selected no checks"
    for name in selected:
        assert name in CHECKS, f"gate does not implement {name}; available: {sorted(CHECKS)}"

    with server_helper_scope(), setup_db() as db:
        owner = db.connect()
        with owner.cursor() as cur:
            cur.execute("SET ROLE v24_owner")
        owner.commit()
        for name in selected:
            print(f"[G7] running {name}")
            CHECKS[name](db, owner)
        _assert_closed_catalog(owner)
    print(f"[passed] v24 S8 W1-W3 G7-A…H + N1-N7: {','.join(selected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
