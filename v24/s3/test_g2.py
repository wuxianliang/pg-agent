"""G2a-0/1/2/3/4/5/6/7/8/10/11 and G3b pin lifecycle: real protocol LOGINs."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sys
from uuid import uuid4

S1 = Path(__file__).resolve().parent.parent / "s1"
S2 = Path(__file__).resolve().parent.parent / "s2"
for stage in (S1, S2):
    if str(stage) not in sys.path:
        sys.path.insert(0, str(stage))

from psycopg2.extras import Json

from setup_db import EXPECTED_TABLES, _assert_closed_catalog, server_helper_scope, setup_db  # noqa: E402
from test_ddl import DIGEST, effect, insert  # noqa: E402
from test_g3a import (advance, claim, one, provider, resolve_rows, seed_effect,
                      seed_fiber, seed_install, seed_scope, seed_slot, sqlstate, state)  # noqa: E402


PROJECTION_KEYS = frozenset("""run_id scope_id status epoch_no registration_generation
    turn_no driving_generation interaction pending_steer close_intent result
    remaining_steps remaining_tokens remaining_tool_calls remaining_wall_ms revision
    created_at updated_at ended_at owner_fiber_id owner_episode_id""".split())


def read_surface(db, owner):
    creator, root, run_id = uuid4(), uuid4(), uuid4()
    seed_effect(owner, creator)
    seed_scope(owner, root, creator, default_realm="g2a-0")
    live = provider(owner, root, "g2a-0", "live", creator)
    provider(owner, root, "g2a-0", "withdrawn", creator, withdrawn=True)
    first_requester, later_requester = uuid4(), uuid4()
    created_at = datetime.now(timezone.utc)
    with owner.cursor() as cur:
        insert(cur, "runs", run_id=run_id, scope_id=root, status="running",
               epoch_no=1, driving_generation=1, revision=1,
               remaining_steps=7, remaining_tokens=1234,
               remaining_tool_calls=3, remaining_wall_ms=10000)
    seed_effect(owner, uuid4(), run_id=run_id, kind="command_start",
                requester_id=later_requester, created_at=created_at + timedelta(seconds=1))
    seed_effect(owner, uuid4(), run_id=run_id, kind="command_start",
                requester_id=first_requester, created_at=created_at)
    # An earlier non-start effect must never establish ownership.
    seed_effect(owner, uuid4(), run_id=run_id, kind="command_cancel",
                requester_id=later_requester, created_at=created_at - timedelta(seconds=1))
    owner.commit()
    run = one(owner, "SELECT to_jsonb(r) FROM v24.runs r WHERE run_id=%s", (run_id,))
    expected_projection = {key: run[key] for key in PROJECTION_KEYS}
    owner.rollback()

    for alias in ("service", "operator", "admin"):
        login = db.connect(alias)
        identity = one(login, "SELECT jsonb_build_array(session_user, current_user)")
        assert identity == [db.roles[alias], db.roles[alias]], (alias, identity)
        assert one(login, "SELECT pg_has_role(session_user,%s,'USAGE')", (f"v24_{alias}",))
        assert one(login, "SELECT rolcanlogin FROM pg_roles WHERE rolname=session_user")
        assert not one(login, "SELECT pg_has_role(session_user,'v24_owner','USAGE')")
        for helper in ("v24.run_owner(uuid)", "v24.run_projection(uuid)"):
            assert not one(login, "SELECT has_function_privilege("
                                  "session_user,%s::regprocedure,'EXECUTE')", (helper,)), (alias, helper)
        for table in EXPECTED_TABLES:
            assert not one(login, "SELECT has_table_privilege(session_user,%s,"
                                 "'SELECT,INSERT,UPDATE,DELETE')", (f"v24.{table}",)), (alias, table)
        login.commit()
        before = state(owner)
        owner.rollback()

        rows = resolve_rows(login, root, ["live", "withdrawn", "missing"])
        assert len(rows) == 3, (alias, rows)
        assert [row["key"] for row in rows] == ["live", "withdrawn", "missing"], rows
        assert rows[0]["live"] is True, (alias, rows)
        assert rows[0]["slot_id"] == str(live["slot"]), rows
        assert rows[0]["provider_episode_id"] == str(live["episode"]), rows
        assert rows[0]["descriptor"] == {"k": "live"}, rows
        assert rows[0]["descriptor_digest"] is not None, rows
        for row in rows[1:]:
            assert row["live"] is False, (alias, row)
            assert row["slot_id"] is None and row["provider_episode_id"] is None, row
        # W3 poll/wait_check will authorize run reads, call these internal helpers,
        # and map unauthorized callers to not_found_or_denied.
        if alias == "service":
            for helper in ("run_owner", "run_projection"):
                sqlstate(login, "42501", lambda helper=helper: one(
                    login, f"SELECT v24.{helper}(%s)", (run_id,)),
                    message=f"permission denied for function {helper}")
        login.commit()
        assert state(owner) == before, f"{alias} read surface wrote rows"
        owner.rollback()
        login.close()

    before = state(owner)
    owner.rollback()
    migration = db.connect("owner")
    assert one(migration, "SELECT session_user::text") == db.roles["owner"]
    assert one(migration, "SELECT v24.run_owner(%s)::text", (run_id,)) == str(first_requester)
    projection = one(migration, "SELECT v24.run_projection(%s)", (run_id,))
    assert frozenset(projection) == PROJECTION_KEYS, projection
    assert projection == expected_projection, (projection, expected_projection)
    missing = uuid4()
    assert one(migration, "SELECT v24.run_owner(%s)", (missing,)) is None
    assert one(migration, "SELECT v24.run_projection(%s)", (missing,)) is None
    migration.commit()
    assert state(owner) == before, "migration owner read surface wrote rows"
    owner.rollback()
    migration.close()

    for name in ("resolve", "run_owner", "run_projection"):
        assert one(owner, """SELECT count(*) FROM pg_proc p,
            LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
            WHERE p.pronamespace='v24'::regnamespace AND p.proname=%s
              AND a.grantee=0 AND a.privilege_type='EXECUTE'""", (name,)) == 0, name
    owner.rollback()
    print("[G2a-0] real service/operator/admin LOGIN read surface; resolver live/miss; "
          "internal helpers denied (42501); migration first-start owner/frozen projection; "
          "ten-table zero writes; no PUBLIC EXECUTE")


def start(conn, scope_id, owner_fiber_id, input_value, budget, key):
    """Keep exact database JSON text for byte-for-byte replay assertions."""
    raw = one(conn, "SELECT v24.start(%s,%s,%s,%s,%s)::text",
              (scope_id, owner_fiber_id, Json(input_value), Json(budget), key))
    return json.loads(raw), raw.encode("utf-8")


def seed_run(owner, requester, *, status="running", epoch=1, revision=1,
             registration_generation=1, interaction=None, ended_at=None,
             event_count=2):
    """Seed an owned run and its run events as migration owner."""
    run_id, scope_id, command_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    with owner.cursor() as cur:
        insert(cur, "scopes", scope_id=scope_id, root_id=scope_id,
               route_path=[scope_id], owner_principal=requester,
               created_by_effect=command_id)
        insert(cur, "runs", run_id=run_id, scope_id=scope_id, status=status,
               epoch_no=epoch, registration_generation=registration_generation,
               turn_no=0, driving_generation=1, remaining_steps=7,
               remaining_tokens=1234, remaining_tool_calls=3, remaining_wall_ms=10000,
               interaction=Json(interaction) if interaction is not None else None,
               revision=revision, created_at=now, updated_at=now, ended_at=ended_at)
        effect(cur, command_id, kind="command_start", requester_id=requester,
               run_id=run_id, scope_id=scope_id, created_at=now)
        for seq in range(1, event_count + 1):
            event_effect = uuid4()
            effect(cur, event_effect)
            insert(cur, "events", effect_id=event_effect, seq=seq,
                   entity_type="run", entity_id=run_id,
                   event_kind=f"seed_{seq}", payload=Json({"seq": seq}),
                   payload_digest=DIGEST)
    owner.commit()
    return run_id


def read_call(conn, function, args):
    return one(conn, f"SELECT v24.{function}({','.join(['%s'] * len(args))})", args)


def assert_read_only_locks(conn):
    pid = one(conn, "SELECT pg_backend_pid()")
    assert one(conn, "SELECT count(*) FROM pg_locks WHERE pid=%s AND locktype='advisory'",
               (pid,)) == 0, "read verb acquired an advisory lock (including G)"
    assert one(conn, "SELECT count(*) FROM pg_locks WHERE pid=%s AND locktype='tuple'",
               (pid,)) == 0, "read verb acquired a tuple lock"
    assert one(conn, """SELECT count(*) FROM pg_locks l
        JOIN pg_class c ON c.oid=l.relation
        WHERE l.pid=%s AND l.locktype='relation' AND c.oid='v24.runs'::regclass
          AND l.mode='RowShareLock'""", (pid,)) == 0, "read verb requested row locks on runs"


def poll_contract(db, owner):
    service, operator = db.connect("service"), db.connect("operator")
    service_principal = one(service, "SELECT v24.principal_id(session_user)")
    operator_principal = one(operator, "SELECT v24.principal_id(session_user)")
    for conn in (service, operator):
        conn.commit()
    run_id = seed_run(owner, service_principal, event_count=70)
    operator_run = seed_run(owner, operator_principal, event_count=1)
    before = state(owner)
    owner.rollback()

    for conn, target in ((service, run_id), (operator, operator_run)):
        projection = one(owner, "SELECT v24.run_projection(%s)", (target,))
        revision = projection["revision"]
        response = read_call(conn, "poll", (target, revision))
        assert set(response) == {"v", "revision", "changed", "run", "events"}, response
        assert response["v"] == 1 and response["revision"] == revision, response
        assert response["changed"] is False, response
        assert set(response["run"]) == PROJECTION_KEYS, response["run"]
        assert response["run"] == projection, (response["run"], projection)
        events = response["events"]
        assert len(events) <= 64, len(events)
        assert all(set(event) == {"seq", "event_kind", "payload", "created_at"}
                   for event in events), events[:1]
        assert [event["seq"] for event in events] == sorted(event["seq"] for event in events), events
        assert all(event["seq"] <= 70 for event in events), events[-1:]
        assert_read_only_locks(conn)
        conn.commit()
        owner.rollback()
        changed = read_call(conn, "poll", (target, revision - 1))
        assert changed["changed"] is True, changed
        conn.commit()
        owner.rollback()

    assert len(read_call(service, "poll", (run_id, 0))["events"]) == 64
    service.commit()
    denied = read_call(service, "poll", (operator_run, 0))
    assert denied == {"v": 1, "error": {"code": "not_found_or_denied"}}, denied
    service.commit()
    missing = read_call(service, "poll", (uuid4(), 0))
    assert missing == {"v": 1, "error": {"code": "not_found_or_denied"}}, missing
    service.commit()
    assert state(owner) == before, "poll wrote one of the ten domain tables"
    owner.rollback()
    for conn in (service, operator):
        conn.close()
    print("[G2a-4] poll service/operator ownership, closed projection/events shapes, revision cursor, 64 cap, denial, no G/tuple locks, ten-table zero writes")


def wait_check_contract(db, owner):
    service, operator = db.connect("service"), db.connect("operator")
    service_principal = one(service, "SELECT v24.principal_id(session_user)")
    operator_principal = one(operator, "SELECT v24.principal_id(session_user)")
    service.commit()
    operator.commit()

    event_run = seed_run(owner, service_principal, event_count=2)
    terminal_run = seed_run(owner, service_principal, status="completed", ended_at=datetime.now(timezone.utc))
    interaction_run = seed_run(owner, service_principal, status="waiting",
                               interaction={"interaction_id": str(uuid4())}, event_count=2)
    epoch_run = seed_run(owner, operator_principal, epoch=2, event_count=2)
    before = state(owner)
    owner.rollback()

    stale = read_call(service, "wait_check", (event_run, 2, 1, 0))
    assert stale == {"v": 1, "error": {"code": "registration_stale"}}, stale
    service.commit()
    # Authorization takes precedence over stale-registration disclosure.
    denied_stale = read_call(service, "wait_check", (epoch_run, 2, 1, 0))
    assert denied_stale == {"v": 1, "error": {"code": "not_found_or_denied"}}, denied_stale
    service.commit()
    missing_stale = read_call(service, "wait_check", (uuid4(), 2, 1, 0))
    assert missing_stale == {"v": 1, "error": {"code": "not_found_or_denied"}}, missing_stale
    service.commit()

    cases = [
        (service, event_run, 1, 1, 0, "event"),
        (service, terminal_run, 1, 1, 0, "terminal"),
        (service, interaction_run, 1, 0, 0, "interaction"),
        # Event is also pending; epoch mismatch has priority over it.
        (operator, epoch_run, 1, 1, 0, "epoch"),
    ]
    for conn, run_id, generation, epoch, cursor, reason in cases:
        response = read_call(conn, "wait_check", (run_id, generation, epoch, cursor))
        assert set(response) == {"v", "run", "events", "wake"}, response
        assert response["v"] == 1 and set(response["run"]) == PROJECTION_KEYS, response
        assert all(set(event) == {"seq", "event_kind", "payload", "created_at"}
                   for event in response["events"]), response["events"][:1]
        assert all(event["seq"] > cursor for event in response["events"]), response["events"]
        assert response["wake"] == {"ready": True, "reason": reason}, response["wake"]
        assert_read_only_locks(conn)
        conn.commit()
        owner.rollback()

    filtered = read_call(service, "wait_check", (event_run, 1, 1, 1))
    assert [event["seq"] for event in filtered["events"]] == [2], filtered
    service.commit()
    assert state(owner) == before, "wait_check wrote one of the ten domain tables"
    owner.rollback()
    service.close()
    operator.close()
    print("[G2a-5] wait registration/auth ordering, event/terminal/interaction/epoch priorities, event cursor, no G/tuple locks, ten-table zero writes")


def start_fixture(owner, login, *, realm=None):
    creator, root = uuid4(), uuid4()
    # Live slot uniqueness is global on (realm,key), not scoped by root.
    realm = realm or f"start-{root}"
    principal = one(login, "SELECT v24.principal_id(session_user)")
    login.commit()
    seed_effect(owner, creator)
    seed_scope(owner, root, creator, default_realm=realm, owner_principal=principal)
    live = provider(owner, root, realm, "owner", creator)
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.fibers SET want_on=true WHERE fiber_id=%s", (live["fiber"],))
    owner.commit()
    return root, live, creator


def assert_start_failure(owner, login, root, fiber, input_value, budget, code, *, w1=False):
    before = state(owner)
    owner.rollback()
    key = f"start-failure-{uuid4()}"
    response, raw = start(login, root, fiber, input_value, budget, key)
    assert response == {"v": 1, "error": {"code": code, "detail": {}}}, (key, response)
    login.commit()
    after = state(owner)
    owner.rollback()
    # Compare the complete domain, including events; W1 permits only a receipt.
    for table in EXPECTED_TABLES - {"effects", "requests"}:
        assert after[table] == before[table], (code, table)
    if not w1:
        assert after == before, (code, "W0 wrote a receipt")
        return
    for table in ("effects", "requests"):
        assert all(row in after[table] for row in before[table]), (code, table, "changed old row")
        assert len(after[table]) == len(before[table]) + 1, (code, table)
    command = next(row for row in after["effects"] if row["request_key"] == key)
    receipt = next(row for row in after["requests"] if row["request_key"] == key)
    assert command["kind"] == "command_start" and command["status"] == "failed", command
    assert command["run_id"] is None and command["settled_at"] is not None, command
    assert receipt["effect_id"] == command["effect_id"] and receipt["response"] == response, receipt
    replay, replay_raw = start(login, root, fiber, input_value, budget, key)
    login.commit()
    assert replay == response and replay_raw == raw, (code, replay)
    assert state(owner) == after, (code, "failure replay wrote rows")
    owner.rollback()


def owner_start(db, owner):
    for alias in ("service", "operator"):
        login = db.connect(alias)
        assert one(login, "SELECT jsonb_build_array(session_user,current_user)") == [db.roles[alias]] * 2
        assert not one(login, "SELECT pg_has_role(session_user,'v24_owner','USAGE')")
        root, live, creator = start_fixture(owner, login, realm=f"start-{alias}")
        providers = {key: provider(owner, root, f"start-{alias}", key, creator)
                     for key in ("search", "memo")}
        owner.commit()
        input_value = {"requires": [{"key": key} for key in providers],
                       "prompt": "preserve me", "opaque": {"nested": [1, True, None]}}
        budget = {"steps": 7, "tool_calls": 3, "tokens": 1234, "wall_ms": 10000}
        key = f"owner-start-{alias}"
        principal = one(login, "SELECT v24.principal_id(session_user)")
        expected_effect = one(login, "SELECT v24.effect_id_for(%s,%s,'command_start')", (principal, key))
        login.commit()
        before = state(owner)
        owner.rollback()
        response, raw = start(login, root, live["fiber"], input_value, budget, key)
        login.commit()
        assert set(response) == {"v", "disposition", "effect_id", "emitted", "revision", "claim"}, response
        assert response["v"] == 1 and response["disposition"] == "committed", response
        assert response["effect_id"] == str(expected_effect), response
        assert response["revision"] == 1 and response["claim"] is None, response
        assert len(response["emitted"]) == 2 and len(set(response["emitted"])) == 2, response
        run_id, model_id = response["emitted"]
        reserve = one(owner, "SELECT v24.model_reserve(%s)", (budget["tokens"],))
        digests = one(owner, "SELECT v24.model_digests(%s)", (run_id,))
        after = state(owner)
        run = next(row for row in after["runs"] if row["run_id"] == run_id)
        for column, expected in {
            "scope_id": str(root), "owner_fiber_id": str(live["fiber"]),
            "owner_episode_id": str(live["episode"]), "status": "running",
            "epoch_no": 1, "registration_generation": 1, "turn_no": 0,
            "driving_generation": 1, "revision": 1,
            "remaining_steps": budget["steps"] - 1,
            "remaining_tool_calls": 3,
            "remaining_tokens": budget["tokens"] - reserve,
            "remaining_wall_ms": 10000,
        }.items():
            assert run[column] == expected, (alias, column, run)
        for column in ("parent_run_id", "spawn_key", "spawn_request_digest", "interaction",
                       "pending_steer", "close_intent", "result", "ended_at"):
            assert run[column] is None, (column, run)
        assert run["created_at"] and run["created_at"] == run["updated_at"], run
        pins = [row for row in after["pins"] if row["consumer_run_id"] == run_id]
        assert len(pins) == len(providers) and {row["key"] for row in pins} == set(providers), pins
        for pin in pins:
            resolved = providers[pin["key"]]
            expected = {"consumer_type": "run", "consumer_episode_id": None,
                        "consumer_run_id": run_id, "consumer_id": run_id, "consumer_epoch": 1,
                        "slot_id": str(resolved["slot"]), "provider_fiber_id": str(resolved["fiber"]),
                        "provider_episode_id": str(resolved["episode"]),
                        "descriptor_digest": "\\x" + DIGEST.hex(), "created_by_effect": str(expected_effect),
                        "released_at": None, "released_by_effect": None}
            assert {column: pin[column] for column in expected} == expected, pin
        model = next(row for row in after["effects"] if row["effect_id"] == model_id)
        for column, expected in {
            "kind": "model_call", "status": "ready", "run_id": run_id, "scope_id": str(root),
            "fiber_id": str(live["fiber"]), "episode_id": str(live["episode"]),
            "epoch_no": 1, "generation": 1, "ordinal": 0, "parent_effect_id": str(expected_effect),
            "replay_policy": "no_replay", "attempt_no": 0, "fence": 0,
        }.items():
            assert model[column] == expected, (column, model)
        assert model["request"] == {"run_id": run_id, "epoch_no": 1, "generation": 1,
                                    "input": input_value, "budget": budget,
                                    "v": 1, "cause": "start",
                                    "reserve": {"tokens": reserve}, "digests": digests}, model
        for column, expected in {"run_id": run_id, "epoch_no": 1, "generation": 1,
                                 "input": input_value, "budget": budget}.items():
            assert model["request"][column] == expected, (column, model)
        assert model["request"]["v"] == 1, model
        assert model["request"]["cause"] == "start", model
        assert model["request"]["reserve"] == {"tokens": reserve}, model
        assert model["request"]["digests"] == digests, model
        assert model["claim_owner"] is None and model["lease_until"] is None, model
        assert model["outcome"] is None and model["settled_at"] is None, model
        command = next(row for row in after["effects"] if row["effect_id"] == str(expected_effect))
        assert command["kind"] == "command_start" and command["status"] == "succeeded", command
        assert command["run_id"] == run_id and command["requester_id"] == str(principal), command
        assert command["settled_at"] is not None, command
        events = [row for row in after["events"] if row["entity_id"] == run_id]
        assert len(events) == 2 and {row["event_kind"] for row in events} == {"run_started", "model_call_requested"}, events
        assert sorted(row["seq"] for row in events) == [1, 2], events
        assert all(row["entity_type"] == "run" and row["effect_id"] == str(expected_effect) for row in events), events
        receipt = next(row for row in after["requests"] if row["request_key"] == key)
        assert receipt["response"] == response and receipt["effect_id"] == str(expected_effect), receipt
        payload = {"scope_id": str(root), "owner_fiber_id": str(live["fiber"]), "input": input_value, "budget": budget}
        assert one(owner, "SELECT request_bytes=convert_to(v24.canonical_json(%s),'UTF8') "
                          "AND request_digest=sha256(request_bytes) FROM v24.requests WHERE effect_id=%s",
                   (Json(payload), expected_effect)), receipt
        for table, increment in (("runs", 1), ("pins", 2), ("effects", 2), ("events", 2), ("requests", 1)):
            assert len(after[table]) == len(before[table]) + increment, (alias, table)
        for table in ("scopes", "episodes", "fibers", "slots", "installs"):
            assert after[table] == before[table], (alias, table)
        owner.rollback()
        replay, replay_raw = start(login, root, live["fiber"], input_value, budget, key)
        login.commit()
        assert replay == response and replay_raw == raw, (alias, replay)
        assert state(owner) == after, "same-key replay wrote rows"
        assert one(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                          "AND kind='model_call' AND status IN ('ready','claimed')",
                   (run_id,)) == 1
        sqlstate(owner, "23505", lambda: seed_effect(owner, uuid4(), run_id=run_id, kind="model_call"),
                 message="u_effects_model_call")
        owner.rollback()
        login.close()
    print("[G2a-1] real service/operator owner start: exact run/pins/model/events/receipt; byte-equal replay; model uniqueness")


def ownerless_start(db, owner):
    login = db.connect("service")
    root, _, _ = start_fixture(owner, login)
    budget = {"steps": 1, "tool_calls": 0, "tokens": 0, "wall_ms": 1}
    for input_value in ({}, {"requires": []}):
        before = state(owner)
        owner.rollback()
        response, _ = start(login, root, None, input_value, budget, f"ownerless-{uuid4()}")
        login.commit()
        assert response.get("disposition") == "committed", response
        run_id, model_id = response["emitted"]
        after = state(owner)
        run = next(row for row in after["runs"] if row["run_id"] == run_id)
        model = next(row for row in after["effects"] if row["effect_id"] == model_id)
        assert run["owner_fiber_id"] is None and run["owner_episode_id"] is None, run
        assert model["fiber_id"] is None and model["episode_id"] is None, model
        assert after["episodes"] == before["episodes"] and after["pins"] == before["pins"]
        assert model["request"]["input"] == input_value and model["request"]["budget"] == budget, model
        owner.rollback()
    assert_start_failure(owner, login, root, None, {"requires": [{"key": "owner"}]}, budget, "invalid_args")
    login.close()
    print("[G2a-2] ownerless absent/empty requires: no episode/pins; nonempty requires W0 invalid_args")


def start_failures(db, owner):
    login, outsider, admin = (db.connect(alias) for alias in ("service", "operator", "admin"))
    budget = {"steps": 2, "tool_calls": 1, "wall_ms": 100}
    root, live, creator = start_fixture(owner, login)
    assert_start_failure(owner, outsider, root, live["fiber"], {}, budget, "unauthorized")
    assert_start_failure(owner, login, uuid4(), None, {}, budget, "unauthorized")
    assert_start_failure(owner, login, root, uuid4(), {}, budget, "invalid_args")
    _, other_live, _ = start_fixture(owner, login)
    assert_start_failure(owner, login, root, other_live["fiber"], {}, budget, "invalid_args")
    closing, closing_live, _ = start_fixture(owner, login)
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.scopes SET close_requested_at=now() WHERE scope_id=%s", (closing,))
    owner.commit()
    assert_start_failure(owner, login, closing, closing_live["fiber"], {}, budget, "scope_closed", w1=True)
    for condition in ("disposed", "want_off", "inactive", "no_episode", "install_unavailable"):
        bad_root, bad, _ = start_fixture(owner, login)
        with owner.cursor() as cur:
            if condition == "disposed":
                cur.execute("UPDATE v24.fibers SET disposed_at=now(),want_on=false WHERE fiber_id=%s", (bad["fiber"],))
            elif condition == "want_off":
                cur.execute("UPDATE v24.fibers SET want_on=false WHERE fiber_id=%s", (bad["fiber"],))
            elif condition == "inactive":
                cur.execute("UPDATE v24.episodes SET state='retiring' WHERE episode_id=%s", (bad["episode"],))
            elif condition == "no_episode":
                cur.execute("UPDATE v24.fibers SET current_episode_id=NULL WHERE fiber_id=%s", (bad["fiber"],))
            else:
                cur.execute("UPDATE v24.installs SET state='prepare_failed' WHERE install_id=%s", (bad["install"],))
        owner.commit()
        assert_start_failure(owner, login, bad_root, bad["fiber"], {}, budget, "provider_unavailable", w1=True)
    realm = one(owner, "SELECT default_realm FROM v24.scopes WHERE scope_id=%s", (root,))
    provider(owner, root, realm, "withdrawn", creator, withdrawn=True)
    owner.commit()
    for key in ("withdrawn", "missing"):
        assert_start_failure(owner, login, root, live["fiber"], {"requires": [{"key": key}]}, budget,
                             "dependency_unresolved", w1=True)
    assert_start_failure(owner, login, root, live["fiber"], {}, {**budget, "steps": 257}, "budget_exceeded", w1=True)
    response, _ = start(admin, root, None, {}, budget, f"admin-start-{uuid4()}")
    admin.commit()
    assert response.get("disposition") == "committed", response
    for conn in (login, outsider, admin):
        conn.close()
    print("[G2a-3] unauthorized/missing owner/wrong scope; scope closed; disposed/off/inactive/no episode/install; withdrawn/missing dependency; W0 zero writes/W1 receipt only")


def start_boundaries(db, owner):
    login = db.connect("operator")
    root, live, _ = start_fixture(owner, login, realm="limits")
    minimum = {"steps": 1, "tool_calls": 0, "tokens": 0, "wall_ms": 1}
    maximum = {"steps": 256, "tool_calls": 1024, "tokens": 10**12, "wall_ms": 86400000}
    for budget in (minimum, maximum, {"steps": 1, "tool_calls": 0}):
        response, _ = start(login, root, live["fiber"], {}, budget, f"budget-valid-{uuid4()}")
        login.commit()
        assert response.get("disposition") == "committed", (budget, response)
        run = one(owner, "SELECT to_jsonb(r) FROM v24.runs r WHERE run_id=%s", (response["emitted"][0],))
        reserve = one(owner, "SELECT v24.model_reserve(%s)", (budget.get("tokens"),))
        assert run["remaining_steps"] == budget["steps"] - 1, run
        assert run["remaining_tool_calls"] == budget["tool_calls"], run
        expected_tokens = None if budget.get("tokens") is None else budget["tokens"] - reserve
        assert run["remaining_tokens"] == expected_tokens, run
        assert run["remaining_wall_ms"] == budget.get("wall_ms", 86400000), run
        owner.rollback()
    invalid = [None, [], {}, {"steps": 1}, {"tool_calls": 0}, {**minimum, "extra": 1}]
    for field in minimum:
        for bad in (-1, 1.5, "1", True, None):
            invalid.append({**minimum, field: bad})
    invalid += [{**minimum, "steps": 0}, {**minimum, "wall_ms": 0}]
    for budget in invalid:
        assert_start_failure(owner, login, root, live["fiber"], {}, budget, "invalid_args")
    for field, cap in maximum.items():
        assert_start_failure(owner, login, root, live["fiber"], {}, {**minimum, field: cap + 1},
                             "budget_exceeded", w1=True)
    assert_start_failure(owner, login, root, live["fiber"], {}, {**minimum, "steps": 10**100},
                         "budget_exceeded", w1=True)
    for input_value in (None, [], "text", {"requires": None}, {"requires": {}},
                        {"requires": ["key"]}, {"requires": [{}]},
                        {"requires": [{"key": ""}]}, {"requires": [{"key": "x" * 257}]},
                        {"requires": [{"key": 7}]}, {"requires": [{"key": "owner", "extra": 1}]},
                        {"requires": [{"key": "owner"}, {"key": "owner"}]},
                        {"requires": [{"key": str(i)} for i in range(17)]}):
        assert_start_failure(owner, login, root, live["fiber"], input_value, minimum, "invalid_args")
    # One run plus sixteen pins exercises the aggregate domain insert boundary.
    keys = ["x", "y" * 256] + [f"limit-{i}" for i in range(14)]
    for seq, key in enumerate(keys, 2):
        seed_slot(owner, fiber_id=live["fiber"], episode_id=live["episode"], realm="limits", key=key, seq=seq)
    owner.commit()
    response, _ = start(login, root, live["fiber"], {"requires": [{"key": key} for key in keys]},
                        minimum, f"sixteen-requires-{uuid4()}")
    login.commit()
    assert response.get("disposition") == "committed", response
    pins = one(owner, "SELECT array_agg(key ORDER BY key) FROM v24.pins WHERE consumer_run_id=%s",
               (response["emitted"][0],))
    assert pins == sorted(keys), pins
    owner.rollback()
    login.close()
    print("[G2a-10] exact min/max/optional budgets; malformed/negative/zero/unknown W0; all caps+1/huge W1; requires/key limits")


def assert_claim_rejected(owner, login, effect_id, label):
    """S3.1 W0 claim rejection: exact error, ten-table equality, untouched claim columns."""
    before = state(owner)
    owner.rollback()
    response = advance(login, effect_id, claim())
    assert response == {"v": 1, "error": {"code": "invalid_args", "detail": {}}}, (label, response)
    login.commit()
    after = state(owner)
    owner.rollback()
    assert after == before, (label, "claim rejection wrote rows")
    row = next(row for row in after["effects"] if row["effect_id"] == str(effect_id))
    assert row["status"] == "ready" and row["attempt_no"] == 0 and row["fence"] == 0, (label, row)
    assert row["claim_owner"] is None and row["lease_until"] is None, (label, row)


def claim_guard(db, owner):
    """G2a-11: W2 stage allowlist; model/tool eligible, every non-member stays W0."""
    login = db.connect("service")
    root, live, creator = start_fixture(owner, login, realm="claim-guard")
    response, _ = start(login, root, live["fiber"], {},
                        {"steps": 2, "tool_calls": 1, "wall_ms": 1000},
                        f"claim-guard-{uuid4()}")
    login.commit()
    assert response.get("disposition") == "committed", response
    run_id, model_id = response["emitted"]
    model = one(owner, "SELECT to_jsonb(e) FROM v24.effects e WHERE effect_id=%s", (model_id,))
    assert model["kind"] == "model_call" and model["status"] == "ready", model
    assert model["request"]["run_id"] == run_id, model
    assert model["attempt_no"] == 0 and model["fence"] == 0, model
    assert model["claim_owner"] is None and model["lease_until"] is None, model
    owner.rollback()
    kinds = one(owner, "SELECT v24.claimable_kinds()")
    assert kinds == ["host_prepare", "host_release", "model_call", "tool_call",
                     "inspect_resource"], kinds
    assert set(kinds) == {"host_prepare", "host_release", "model_call", "tool_call",
                          "inspect_resource"}, kinds
    owner.rollback()

    # S4 W1 positive: the real start model_call is claimable and the token is exact.
    before = state(owner)
    owner.rollback()
    claimed = advance(login, model_id, claim())
    login.commit()
    assert claimed == {"v": 1, "disposition": "committed", "effect_id": model_id,
                       "emitted": [], "revision": 0,
                       "claim": {"attempt": 1, "fence": 1, "owner": db.roles["service"]}}, claimed
    after = state(owner)
    owner.rollback()
    for table in EXPECTED_TABLES - {"effects"}:
        assert after[table] == before[table], (table, "model claim wrote extra rows")
    claimed_model = next(row for row in after["effects"] if row["effect_id"] == model_id)
    assert claimed_model["status"] == "claimed", claimed_model
    assert claimed_model["attempt_no"] == 1 and claimed_model["fence"] == 1, claimed_model
    assert claimed_model["claim_owner"] == db.roles["service"], claimed_model
    assert claimed_model["lease_until"] is not None, claimed_model

    # Every non-member kind stays W0 with a ten-table byte-equal snapshot.
    command_kinds = ("command_start", "command_cancel", "command_steer",
                     "command_respond", "command_install", "command_fiber_control",
                     "command_dispose", "command_scope_control", "command_recover")
    assert len(command_kinds) == 9, command_kinds
    for kind in ("inspect_resource",) + command_kinds + ("fiber_reconcile",):
        effect_id = uuid4()
        extra = {"fiber_id": live["fiber"]} if kind == "fiber_reconcile" else {}
        seed_effect(owner, effect_id, kind=kind, status="ready", **extra)
        owner.commit()
        assert_claim_rejected(owner, login, effect_id, f"seeded {kind}")

    # S1 install fixture / existing host claim path: not over-blocked.
    install = seed_install(owner, scope_id=root, creator=creator, state="preparing")
    effect_id = uuid4()
    seed_effect(owner, effect_id, kind="host_prepare", status="ready",
                request=Json({"install_id": str(install),
                              "reservation": f"v24:host_prepare:{effect_id}"}))
    owner.commit()
    before = state(owner)
    owner.rollback()
    claimed = advance(login, effect_id, claim())
    login.commit()
    assert claimed == {"v": 1, "disposition": "committed", "effect_id": str(effect_id),
                       "emitted": [], "revision": 0,
                       "claim": {"attempt": 1, "fence": 1, "owner": db.roles["service"]}}, claimed
    after = state(owner)
    owner.rollback()
    for table in EXPECTED_TABLES - {"effects"}:
        assert after[table] == before[table], (table, "host_prepare claim wrote extra rows")
    row = next(row for row in after["effects"] if row["effect_id"] == str(effect_id))
    assert row["status"] == "claimed" and row["attempt_no"] == 1 and row["fence"] == 1, row
    assert row["claim_owner"] == db.roles["service"] and row["lease_until"] is not None, row
    login.close()
    print("[G2a-11] claim allowlist = v24.claimable_kinds() "
          "{host_prepare,host_release,model_call,tool_call,inspect_resource}; real model "
          "claim exact token and effect-only write; owner-seeded request-less "
          "inspect_resource and all command_*/fiber_reconcile reject invalid_args with "
          "ten-table byte-equal snapshots and untouched attempt/fence/owner/lease; "
          "host_prepare still claims")


def cancel(conn, run_id, generation, key):
    raw = one(conn, "SELECT v24.cancel(%s,%s,%s)::text", (run_id, generation, key))
    return json.loads(raw), raw.encode("utf-8")


def assert_cancel_failure(owner, login, run_id, generation, code, *, w1=False):
    before = state(owner)
    owner.rollback()
    key = f"cancel-failure-{uuid4()}"
    response, raw = cancel(login, run_id, generation, key)
    login.commit()
    assert response == {"v": 1, "error": {"code": code, "detail": {}}}, response
    after = state(owner)
    owner.rollback()
    for table in EXPECTED_TABLES - {"effects", "requests"}:
        assert after[table] == before[table], (code, table, "domain write")
    if not w1:
        assert after == before, (code, "W0 wrote a receipt")
        return
    for table in ("effects", "requests"):
        assert all(row in after[table] for row in before[table]), (code, table, "changed old row")
        assert len(after[table]) == len(before[table]) + 1, (code, table)
    command = next(row for row in after["effects"] if row["request_key"] == key)
    receipt = next(row for row in after["requests"] if row["request_key"] == key)
    assert command["kind"] == "command_cancel" and command["status"] == "failed", command
    assert command["settled_at"] is not None, command
    assert receipt["effect_id"] == command["effect_id"] and receipt["response"] == response, receipt
    replay, replay_raw = cancel(login, run_id, generation, key)
    login.commit()
    assert replay == response and replay_raw == raw, (code, replay)
    assert state(owner) == after, (code, "failure replay wrote rows")
    owner.rollback()


def cancel_fixture(owner, login, *, extra_input=None):
    root, live, creator = start_fixture(owner, login)
    realm = one(owner, "SELECT default_realm FROM v24.scopes WHERE scope_id=%s", (root,))
    keys = ("cancel-a", "cancel-b", "cancel-c", "cancel-d")
    for key in keys:
        provider(owner, root, realm, key, creator)
    owner.commit()
    start_input = {"requires": [{"key": key} for key in keys]}
    if extra_input:
        start_input.update(extra_input)
    response, _ = start(login, root, live["fiber"],
                        start_input,
                        {"steps": 7, "tool_calls": 3, "tokens": 1234, "wall_ms": 10000},
                        f"cancel-start-{uuid4()}")
    login.commit()
    assert response.get("disposition") == "committed", response
    run_id, model_id = response["emitted"]
    pins = one(owner, "SELECT jsonb_agg(to_jsonb(p) ORDER BY key) FROM v24.pins p "
                      "WHERE consumer_run_id=%s", (run_id,))
    owner.rollback()
    return run_id, model_id, pins


def assert_cancel_success(owner, login, run_id, generation, *, ready_ids, claimed_ids=(), held_pins=()):
    run_id = str(run_id)
    before = state(owner)
    owner.rollback()
    old_run = next(row for row in before["runs"] if row["run_id"] == run_id)
    # [S4 addendum A] cancel refunds every ready model reserve it archives.
    refund = sum((row["request"].get("reserve") or {}).get("tokens", 0)
                 for row in before["effects"]
                 if row["run_id"] == run_id and row["kind"] == "model_call"
                 and row["status"] == "ready")
    expected_tokens = (None if old_run["remaining_tokens"] is None
                       else old_run["remaining_tokens"] + refund)
    key = f"cancel-success-{uuid4()}"
    response, raw = cancel(login, run_id, generation, key)
    login.commit()
    assert set(response) == {"v", "disposition", "effect_id", "emitted", "revision", "claim"}, response
    assert response["v"] == 1 and response["disposition"] == "committed", response
    assert response["emitted"] == [] and response["claim"] is None, response
    assert response["revision"] == old_run["revision"] + 1, response
    command_id = response["effect_id"]
    after = state(owner)
    owner.rollback()
    run = next(row for row in after["runs"] if row["run_id"] == run_id)
    assert run["status"] == "cancelled", run
    assert run["interaction"] is None and run["pending_steer"] is None, run
    assert run["driving_generation"] == generation + 1, run
    assert run["revision"] == old_run["revision"] + 1, run
    assert run["ended_at"] and run["ended_at"] == run["updated_at"], run
    assert run["close_intent"] == {"kind": "cancel", "generation": generation,
                                    "at": run["ended_at"]}, run
    assert run["remaining_tokens"] == expected_tokens, (run, expected_tokens)
    if expected_tokens is not None:
        assert run["remaining_tokens"] == old_run["remaining_tokens"] + refund, (old_run, run)
    changed_run = {"status", "interaction", "pending_steer", "driving_generation",
                   "revision", "ended_at", "updated_at", "close_intent",
                   "remaining_tokens"}
    assert {k: v for k, v in run.items() if k not in changed_run} == {
        k: v for k, v in old_run.items() if k not in changed_run}, (old_run, run)
    assert [row for row in after["runs"] if row["run_id"] != run_id] == [
        row for row in before["runs"] if row["run_id"] != run_id], "cancel changed another run"

    old_effects = {row["effect_id"]: row for row in before["effects"]}
    for row in after["effects"]:
        effect_id = row["effect_id"]
        if effect_id == command_id:
            assert row["kind"] == "command_cancel" and row["status"] == "succeeded", row
            assert row["run_id"] == run_id and row["settled_at"] is not None, row
        elif effect_id in ready_ids:
            expected = {**old_effects[effect_id], "status": "cancelled",
                        "settled_at": run["ended_at"], "outcome": None}
            assert row == expected, (row, expected)
        elif effect_id in claimed_ids:
            assert row == {**old_effects[effect_id], "cancel_requested": True}, row
            assert row["status"] == "claimed" and row["settled_at"] is None, row
        else:
            assert row == old_effects[effect_id], (effect_id, "cancel changed unrelated effect")
    assert len(after["effects"]) == len(before["effects"]) + 1

    old_pins = {row["pin_id"]: row for row in before["pins"]}
    assert len(after["pins"]) == len(before["pins"])
    for pin in after["pins"]:
        old_pin = old_pins[pin["pin_id"]]
        if pin["consumer_run_id"] == run_id and pin["pin_id"] not in held_pins:
            assert pin == {**old_pin, "released_at": run["ended_at"],
                           "released_by_effect": command_id}, pin
        else:
            assert pin == old_pin, (pin, "held/unrelated pin changed")
    new_events = [row for row in after["events"] if row not in before["events"]]
    assert len(new_events) == 1, new_events
    event = new_events[0]
    assert event["effect_id"] == command_id and event["entity_type"] == "run", event
    assert event["entity_id"] == run_id and event["event_kind"] == "run_cancelled", event
    assert event["payload"] == {"run_id": run_id, "generation": generation}, event
    assert len(after["events"]) == len(before["events"]) + 1
    assert len(after["requests"]) == len(before["requests"]) + 1
    assert all(row in after["requests"] for row in before["requests"])
    receipt = next(row for row in after["requests"] if row["request_key"] == key)
    assert receipt["response"] == response and receipt["effect_id"] == command_id, receipt
    assert one(owner, "SELECT request_bytes=convert_to(v24.canonical_json(%s),'UTF8') "
                      "AND request_digest=sha256(request_bytes) FROM v24.requests WHERE effect_id=%s",
               (Json({"run_id": run_id, "expected_generation": generation}), command_id)), receipt
    owner.rollback()
    for table in ("scopes", "episodes", "fibers", "slots", "installs"):
        assert after[table] == before[table], (table, "cancel changed shared provider state")
    replay, replay_raw = cancel(login, run_id, generation, key)
    login.commit()
    assert replay == response and replay_raw == raw, "cancel same-key replay changed bytes"
    assert state(owner) == after, "cancel same-key replay wrote rows"
    owner.rollback()
    # Terminal wins over CAS: this new key intentionally uses the now-old generation.
    assert_cancel_failure(owner, login, run_id, generation, "already_terminal", w1=True)


def cancel_contract(db, owner):
    service, operator, admin = (db.connect(alias) for alias in ("service", "operator", "admin"))
    for alias, login in (("service", service), ("operator", operator), ("admin", admin)):
        assert one(login, "SELECT jsonb_build_array(session_user,current_user)") == [db.roles[alias]] * 2
        assert not one(login, "SELECT pg_has_role(session_user,'v24_owner','USAGE')")
        login.commit()

    run_id, model_id, pins = cancel_fixture(owner, service)
    ready_tool = str(uuid4())
    # The ready tool references a pin: release must use post-cancellation state.
    seed_effect(owner, ready_tool, kind="tool_call", run_id=run_id,
                pin_id=pins[0]["pin_id"], generation=3)
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.runs SET status='waiting',interaction=%s,pending_steer=%s,"
                    "driving_generation=3,revision=7 WHERE run_id=%s",
                    (Json({"interaction_id": str(uuid4())}),
                     Json({"instruction": "discard me", "generation": 3}), run_id))
    owner.commit()
    assert_cancel_failure(owner, service, run_id, 2, "stale_generation", w1=True)
    assert_cancel_failure(owner, operator, run_id, 3, "unauthorized")
    assert_cancel_failure(owner, service, uuid4(), 1, "invalid_args")
    assert_cancel_success(owner, service, run_id, 3, ready_ids=(model_id, ready_tool))

    claimed_run, claimed_model, claimed_pins = cancel_fixture(owner, operator)
    claimed_tool = str(uuid4())
    held_pin = claimed_pins[0]["pin_id"]
    seed_effect(owner, claimed_tool, kind="tool_call", run_id=claimed_run, pin_id=held_pin,
                status="claimed", attempt_no=1, fence=1, claim_owner="fake-worker",
                lease_until=datetime.now(timezone.utc) + timedelta(minutes=5), generation=1)
    unknown_pin = claimed_pins[1]["pin_id"]
    # S4 produces unknown outcomes; owner fixtures exercise the release predicate only.
    for pin, quiesced in ((unknown_pin, None),
                         (claimed_pins[2]["pin_id"], datetime.now(timezone.utc))):
        seed_effect(owner, uuid4(), kind="tool_call", run_id=claimed_run, pin_id=pin,
                    status="unknown", outcome=Json({"fixture": "resource status unknown"}),
                    settled_at=datetime.now(timezone.utc), resource_quiesced_at=quiesced)
    owner.commit()
    assert_cancel_success(owner, operator, claimed_run, 1, ready_ids=(claimed_model,),
                          claimed_ids=(claimed_tool,), held_pins=(held_pin, unknown_pin))

    service_principal = one(service, "SELECT v24.principal_id(session_user)")
    service.commit()
    for status in ("completed", "failed", "cancelled", "blocked_unknown"):
        terminal = seed_run(owner, service_principal, status=status,
                            ended_at=datetime.now(timezone.utc))
        assert_cancel_failure(owner, service, terminal, 99, "already_terminal", w1=True)
        assert_cancel_failure(owner, operator, terminal, 99, "unauthorized")

    admin_run = seed_run(owner, service_principal)
    assert_cancel_success(owner, admin, admin_run, 1, ready_ids=())
    for conn in (service, operator, admin):
        conn.close()
    print("[G2a-6] real service/operator/admin cancel: CAS/auth/missing/terminal ordering; "
          "seal/clear/generation+1/revision+1; ready model+tool cancelled, NULL outcome, settled; "
          "claimed tool stays claimed+cancel_requested with token unchanged; event/receipt; "
          "same-key byte replay, new-key already_terminal; W0 zero writes/W1 receipt only")
    print("[G2a-6 pin predicate] ready pin reference cancelled then released; unreferenced run pins "
          "released by cancel effect; claimed tool pin held while other run pin releases; "
          "unknown unquiesced holds/quiesced releases; shared provider/activation state "
          "unchanged; claimed settlement release remains S4")


def steer(conn, run_id, generation, instruction, key):
    raw = one(conn, "SELECT v24.steer(%s,%s,%s,%s)::text",
              (run_id, generation, instruction, key))
    return json.loads(raw), raw.encode("utf-8")


def assert_steer_failure(owner, login, run_id, generation, code, *, w1=False,
                         instruction="change course", key=None):
    before = state(owner)
    owner.rollback()
    if key is None:
        key = f"steer-failure-{uuid4()}"
    response, raw = steer(login, run_id, generation, instruction, key)
    login.commit()
    assert response == {"v": 1, "error": {"code": code, "detail": {}}}, response
    after = state(owner)
    owner.rollback()
    for table in EXPECTED_TABLES - {"effects", "requests"}:
        assert after[table] == before[table], (code, table, "domain write")
    if not w1:
        assert after == before, (code, "W0 wrote a receipt")
        return
    for table in ("effects", "requests"):
        assert all(row in after[table] for row in before[table]), (code, table, "changed old row")
        assert len(after[table]) == len(before[table]) + 1, (code, table)
    command = next(row for row in after["effects"] if row["request_key"] == key)
    receipt = next(row for row in after["requests"] if row["request_key"] == key)
    assert command["kind"] == "command_steer" and command["status"] == "failed", command
    assert command["settled_at"] is not None, command
    assert receipt["effect_id"] == command["effect_id"] and receipt["response"] == response, receipt
    replay, replay_raw = steer(login, run_id, generation, instruction, key)
    login.commit()
    assert replay == response and replay_raw == raw, (code, replay)
    assert state(owner) == after, (code, "failure replay wrote rows")
    owner.rollback()


def assert_steer_success(owner, login, run_id, generation, *, deferred=False,
                         instruction="preserve this instruction", key=None, expected_input=None):
    run_id = str(run_id)
    key = key or f"steer-success-{uuid4()}"
    before = state(owner)
    owner.rollback()
    old_run = next(row for row in before["runs"] if row["run_id"] == run_id)
    response, raw = steer(login, run_id, generation, instruction, key)
    login.commit()
    assert set(response) == {"v", "disposition", "effect_id", "emitted", "revision", "claim"}, response
    assert response["v"] == 1 and response["disposition"] == "committed", response
    assert response["claim"] is None and response["revision"] == old_run["revision"] + 1, response
    command_id = response["effect_id"]
    after = state(owner)
    owner.rollback()
    run = next(row for row in after["runs"] if row["run_id"] == run_id)
    new_generation, new_epoch = generation + 1, old_run["epoch_no"] + 1
    expected_pending = ({"instruction": instruction, "generation": new_generation,
                         "epoch": new_epoch} if deferred else None)
    # [S4 addendum A] steer refunds every ready model reserve in the same delta;
    # a newly admitted model then pre-debits its own reserve.
    refund = sum((row["request"].get("reserve") or {}).get("tokens", 0)
                 for row in before["effects"]
                 if row["run_id"] == run_id and row["kind"] == "model_call"
                 and row["status"] == "ready")
    balance = (None if old_run["remaining_tokens"] is None
               else old_run["remaining_tokens"] + refund)
    new_reserve = 0 if deferred else one(
        owner, "SELECT v24.model_reserve(%s)", (balance,))
    expected_tokens = (None if balance is None else balance - new_reserve)
    expected_steps = old_run["remaining_steps"] - (0 if deferred else 1)
    for column, expected in {"status": "running", "epoch_no": new_epoch,
                             "driving_generation": new_generation,
                             "revision": old_run["revision"] + 1,
                             "interaction": None, "pending_steer": expected_pending,
                             "remaining_steps": expected_steps,
                             "remaining_tokens": expected_tokens}.items():
        assert run[column] == expected, (column, expected, run)
    if balance is not None:
        assert run["remaining_tokens"] == old_run["remaining_tokens"] + refund - new_reserve, run
    assert run["updated_at"] >= old_run["updated_at"], run
    changed_run = {"status", "epoch_no", "driving_generation", "revision",
                   "interaction", "pending_steer", "remaining_steps",
                   "remaining_tokens", "updated_at"}
    assert {k: v for k, v in run.items() if k not in changed_run} == {
        k: v for k, v in old_run.items() if k not in changed_run}, (old_run, run)
    assert [row for row in after["runs"] if row["run_id"] != run_id] == [
        row for row in before["runs"] if row["run_id"] != run_id], "steer changed another run"
    assert after["pins"] == before["pins"], "steer changed pins"

    old_effects = {row["effect_id"]: row for row in before["effects"]}
    new_effects = [row for row in after["effects"] if row["effect_id"] not in old_effects]
    command = next(row for row in new_effects if row["effect_id"] == command_id)
    assert command["kind"] == "command_steer" and command["status"] == "succeeded", command
    assert command["run_id"] == run_id and command["settled_at"] == run["updated_at"], command
    successors = [row for row in new_effects if row["effect_id"] != command_id]
    assert len(successors) == (0 if deferred else 1), successors
    if deferred:
        assert response["emitted"] == [], response
    else:
        successor = successors[0]
        expected_id = one(owner, "SELECT md5(%s || ':model_call:0')::uuid::text", (command_id,))
        assert response["emitted"] == [expected_id], response
        for column, expected in {"effect_id": expected_id, "kind": "model_call", "status": "ready",
                                 "run_id": run_id, "generation": new_generation, "epoch_no": new_epoch,
                                 "parent_effect_id": command_id, "ordinal": 0}.items():
            assert successor[column] == expected, (column, successor)
        digests = one(owner, "SELECT v24.model_digests(%s)", (run_id,))
        assert successor["request"] == {"run_id": run_id, "epoch_no": new_epoch,
                                        "generation": new_generation, "input": expected_input or {},
                                        "instruction": instruction,
                                        "v": 1, "cause": "steer",
                                        "reserve": {"tokens": new_reserve},
                                        "digests": digests}, successor
        for column, expected in {"run_id": run_id, "epoch_no": new_epoch,
                                 "generation": new_generation,
                                 "input": expected_input or {},
                                 "instruction": instruction}.items():
            assert successor["request"][column] == expected, (column, successor)
        assert successor["request"]["v"] == 1, successor
        assert successor["request"]["cause"] == "steer", successor
        assert successor["request"]["reserve"] == {"tokens": new_reserve}, successor
        assert successor["request"]["digests"] == digests, successor
        assert successor["outcome"] is None and successor["settled_at"] is None, successor
    for row in after["effects"]:
        if row["effect_id"] not in old_effects:
            continue
        old = old_effects[row["effect_id"]]
        if old["run_id"] == run_id and old["kind"] in ("model_call", "tool_call") and old["status"] == "ready":
            assert row == {**old, "status": "cancelled", "settled_at": run["updated_at"], "outcome": None}, row
        else:
            assert row == old, (row, "steer changed claimed/settled/unrelated effect")
        if old["run_id"] == run_id and old["status"] == "claimed":
            assert row["status"] == "claimed" and row["cancel_requested"] is False, row
    assert len(after["effects"]) == len(before["effects"]) + 1 + len(successors)
    new_events = [row for row in after["events"] if row not in before["events"]]
    assert len(new_events) == 1 and len(after["events"]) == len(before["events"]) + 1, new_events
    event = new_events[0]
    assert event["effect_id"] == command_id and event["entity_type"] == "run", event
    assert event["entity_id"] == run_id and event["event_kind"] == "run_steered", event
    assert event["payload"] == {"run_id": run_id, "generation": new_generation, "deferred": deferred}, event
    assert len(after["requests"]) == len(before["requests"]) + 1
    assert all(row in after["requests"] for row in before["requests"])
    receipt = next(row for row in after["requests"] if row["request_key"] == key)
    assert receipt["effect_id"] == command_id and receipt["response"] == response, receipt
    payload = {"run_id": run_id, "expected_generation": generation, "instruction": instruction}
    assert one(owner, "SELECT request_bytes=convert_to(v24.canonical_json(%s),'UTF8') "
                      "AND request_digest=sha256(request_bytes) FROM v24.requests WHERE effect_id=%s",
               (Json(payload), command_id)), receipt
    owner.rollback()
    for table in ("scopes", "episodes", "fibers", "slots", "installs"):
        assert after[table] == before[table], (table, "steer changed shared state")
    replay, replay_raw = steer(login, run_id, generation, instruction, key)
    login.commit()
    assert replay == response and replay_raw == raw, "steer same-key replay changed bytes"
    assert state(owner) == after, "steer same-key replay wrote rows"
    owner.rollback()


def steer_contract(db, owner):
    service, operator, admin = (db.connect(alias) for alias in ("service", "operator", "admin"))
    for alias, login in (("service", service), ("operator", operator), ("admin", admin)):
        assert one(login, "SELECT jsonb_build_array(session_user,current_user)") == [db.roles[alias]] * 2
        assert not one(login, "SELECT pg_has_role(session_user,'v24_owner','USAGE')")
        login.commit()

    original_input = {"prompt": "keep prior input", "opaque": [True, None, {"x": 1}]}
    run_id, model_id, pins = cancel_fixture(owner, service, extra_input=original_input)
    prior_input = one(owner, "SELECT request->'input' FROM v24.effects WHERE effect_id=%s", (model_id,))
    owner.rollback()
    assert_steer_failure(owner, service, run_id, 0, "stale_generation", w1=True)
    assert_steer_failure(owner, operator, run_id, 1, "unauthorized")
    assert_steer_failure(owner, service, uuid4(), 1, "invalid_args")
    for generation, instruction, key in ((-1, "ok", "valid-key"), (None, "ok", "valid-key"),
                                          (1, "", "valid-key"), (1, None, "valid-key"),
                                          (1, "x" * 8193, "valid-key"), (1, "ok", ""),
                                          (1, "ok", "x" * 513)):
        assert_steer_failure(owner, service, run_id, generation, "invalid_args",
                             instruction=instruction, key=key)
    # Only a ready model call: one archive, exactly one successor, all pins retained.
    assert_steer_success(owner, service, run_id, 1, expected_input=prior_input)

    claimed_run, claimed_model, claimed_pins = cancel_fixture(owner, operator)
    claimed_tool, ready_tool = str(uuid4()), str(uuid4())
    seed_effect(owner, claimed_tool, kind="tool_call", run_id=claimed_run,
                pin_id=claimed_pins[0]["pin_id"], status="claimed", attempt_no=1, fence=1,
                claim_owner="fake-worker", lease_until=datetime.now(timezone.utc) + timedelta(minutes=5),
                generation=1)
    seed_effect(owner, ready_tool, kind="tool_call", run_id=claimed_run,
                pin_id=claimed_pins[1]["pin_id"], generation=1)
    owner.commit()
    assert_steer_success(owner, operator, claimed_run, 1, deferred=True)

    waiting_run, waiting_model, _ = cancel_fixture(owner, service)
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.runs SET status='waiting',interaction=%s,pending_steer=%s,"
                    "driving_generation=3,epoch_no=2,revision=7 WHERE run_id=%s",
                    (Json({"interaction_id": str(uuid4())}),
                     Json({"instruction": "replace me", "generation": 3, "epoch": 2}), waiting_run))
    owner.commit()
    waiting_input = one(owner, "SELECT request->'input' FROM v24.effects WHERE effect_id=%s", (waiting_model,))
    owner.rollback()
    assert_steer_success(owner, service, waiting_run, 3, instruction="指" * 8192,
                         key="k" * 512, expected_input=waiting_input)

    principal = one(service, "SELECT v24.principal_id(session_user)")
    service.commit()
    for status in ("completed", "failed", "cancelled"):
        terminal = seed_run(owner, principal, status=status, ended_at=datetime.now(timezone.utc))
        # Terminal precedes stale CAS; authorization precedes terminal disclosure.
        assert_steer_failure(owner, service, terminal, 99, "already_terminal", w1=True)
        assert_steer_failure(owner, operator, terminal, 99, "unauthorized")
    # Declared S4 W3 alignment (D-S4-3): blocked_unknown is no longer an
    # already_terminal alias.  It is a W0 wall with its own code, so it writes
    # neither the command effect nor a receipt; auth precedence is unchanged.
    blocked = seed_run(owner, principal, status="blocked_unknown",
                       ended_at=datetime.now(timezone.utc))
    assert_steer_failure(owner, service, blocked, 99, "blocked_unknown")
    assert_steer_failure(owner, operator, blocked, 99, "unauthorized")
    # Admin bypasses ownership; no previous model call uses the empty-input fallback.
    admin_run = seed_run(owner, principal)
    assert_steer_success(owner, admin, admin_run, 1)
    for conn in (service, operator, admin):
        conn.close()
    print("[G2a-7] real service/operator/admin steer: ready model/tool archived+settled+NULL outcome; "
          "epoch/driving/revision+1; latest input successor or claimed-tool deferred pending; "
          "claimed token/cancel_requested and all pins unchanged; waiting interaction cleared; "
          "auth/missing/local limits/stale/terminal ordering; event/receipt and byte-equal replay")


def respond(conn, run_id, interaction_id, response, generation, key):
    raw = one(conn, "SELECT v24.respond(%s,%s,%s,%s,%s)::text",
              (run_id, interaction_id, Json(response), generation, key))
    return json.loads(raw), raw.encode("utf-8")


def respond_fixture(owner, login):
    """S4 interaction production is owner-seeded; respond itself never archives work."""
    run_id, origin_id, _ = cancel_fixture(owner, login)
    interaction_id = str(uuid4())
    interaction = {"interaction_id": interaction_id, "origin_effect_id": origin_id,
                   "generation": 4, "schema_digest": "\\x" + "11" * 32,
                   "prompt_digest": "\\x" + "22" * 32,
                   "created_at": datetime.now(timezone.utc).isoformat()}
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.effects SET status='cancelled',settled_at=now() "
                    "WHERE effect_id=%s", (origin_id,))
        # W1 pre-debits the model reserve at admission, so the owner fixture must
        # refund the archived model exactly as a real archive would (addendum A).
        cur.execute("UPDATE v24.runs SET status='waiting',interaction=%s,"
                    "remaining_tokens=CASE WHEN remaining_tokens IS NULL THEN NULL "
                    "ELSE remaining_tokens+(SELECT coalesce((request->'reserve'->>'tokens')::bigint,0) "
                    "FROM v24.effects WHERE effect_id=%s) END,"
                    "driving_generation=4,epoch_no=3,revision=7 WHERE run_id=%s",
                    (Json(interaction), origin_id, run_id))
    owner.commit()
    return run_id, interaction


def assert_respond_failure(owner, login, run_id, interaction_id, generation, code,
                           *, response=None, key=None, w1=False):
    answer = {"answer": "no domain changes"} if response is None else response
    key = f"respond-failure-{uuid4()}" if key is None else key
    before = state(owner)
    owner.rollback()
    result, raw = respond(login, run_id, interaction_id, answer, generation, key)
    login.commit()
    assert result == {"v": 1, "error": {"code": code, "detail": {}}}, result
    after = state(owner)
    owner.rollback()
    for table in EXPECTED_TABLES - {"effects", "requests"}:
        assert after[table] == before[table], (code, table, "domain write")
    if not w1:
        assert after == before, (code, "W0 wrote rows")
        return
    for table in ("effects", "requests"):
        assert all(row in after[table] for row in before[table]), (code, table)
        assert len(after[table]) == len(before[table]) + 1, (code, table)
    command = next(row for row in after["effects"] if row["request_key"] == key)
    receipt = next(row for row in after["requests"] if row["request_key"] == key)
    assert command["kind"] == "command_respond" and command["status"] == "failed", command
    assert command["settled_at"] is not None, command
    assert receipt["effect_id"] == command["effect_id"] and receipt["response"] == result, receipt
    replay, replay_raw = respond(login, run_id, interaction_id, answer, generation, key)
    login.commit()
    assert replay == result and replay_raw == raw, (code, replay)
    assert state(owner) == after, (code, "failure replay wrote rows")
    owner.rollback()


def assert_respond_success(owner, login, run_id, interaction, *, key=None):
    key = key or f"respond-success-{uuid4()}"
    answer = {"answer": "继续", "structured": [True, None, {"value": 42}]}
    before = state(owner)
    owner.rollback()
    old_run = next(row for row in before["runs"] if row["run_id"] == str(run_id))
    generation = old_run["driving_generation"]
    result, raw = respond(login, run_id, interaction["interaction_id"], answer, generation, key)
    login.commit()
    command_id = result.get("effect_id")
    model_id = one(owner, "SELECT md5(%s || ':model_call:0')::uuid::text", (command_id,))
    assert result == {"v": 1, "disposition": "committed", "effect_id": command_id,
                      "emitted": [model_id], "revision": old_run["revision"] + 1,
                      "claim": None}, result
    after = state(owner)
    owner.rollback()
    run = next(row for row in after["runs"] if row["run_id"] == str(run_id))
    reserve = one(owner, "SELECT v24.model_reserve(%s)", (old_run["remaining_tokens"],))
    expected_steps = old_run["remaining_steps"] - 1
    expected_tokens = (None if old_run["remaining_tokens"] is None
                       else old_run["remaining_tokens"] - reserve)
    expected_run = {**old_run, "status": "running", "interaction": None,
                    "driving_generation": generation + 1, "revision": old_run["revision"] + 1,
                    "remaining_steps": expected_steps, "remaining_tokens": expected_tokens,
                    "updated_at": run["updated_at"]}
    assert run == expected_run and run["updated_at"] >= old_run["updated_at"], run
    assert run["remaining_steps"] == old_run["remaining_steps"] - 1, run
    if expected_tokens is not None:
        assert run["remaining_tokens"] == old_run["remaining_tokens"] - reserve, run
    assert [r for r in after["runs"] if r["run_id"] != str(run_id)] == [
        r for r in before["runs"] if r["run_id"] != str(run_id)], "changed another run"
    old_effects = {row["effect_id"]: row for row in before["effects"]}
    new_effects = [row for row in after["effects"] if row["effect_id"] not in old_effects]
    assert len(new_effects) == 2 and all(row in after["effects"] for row in before["effects"])
    command = next(row for row in new_effects if row["effect_id"] == command_id)
    assert command["kind"] == "command_respond" and command["status"] == "succeeded", command
    assert command["run_id"] == str(run_id) and command["settled_at"] == run["updated_at"], command
    model = next(row for row in new_effects if row["effect_id"] == model_id)
    for column, expected in {"kind": "model_call", "status": "ready", "run_id": str(run_id),
                             "epoch_no": old_run["epoch_no"], "generation": generation + 1,
                             "fiber_id": old_run["owner_fiber_id"], "episode_id": old_run["owner_episode_id"],
                             "parent_effect_id": command_id, "ordinal": 0,
                             "replay_policy": "no_replay", "outcome": None, "settled_at": None}.items():
        assert model[column] == expected, (column, model)
    digests = one(owner, "SELECT v24.model_digests(%s)", (run_id,))
    assert model["request"] == {"run_id": str(run_id), "epoch_no": old_run["epoch_no"],
                                "generation": generation + 1, "response": answer,
                                "origin_effect_id": interaction["origin_effect_id"],
                                "v": 1, "cause": "respond",
                                "reserve": {"tokens": reserve},
                                "digests": digests}, model
    for column, expected in {"run_id": str(run_id), "epoch_no": old_run["epoch_no"],
                             "generation": generation + 1, "response": answer,
                             "origin_effect_id": interaction["origin_effect_id"]}.items():
        assert model["request"][column] == expected, (column, model)
    assert model["request"]["v"] == 1, model
    assert model["request"]["cause"] == "respond", model
    assert model["request"]["reserve"] == {"tokens": reserve}, model
    assert model["request"]["digests"] == digests, model
    assert len([row for row in after["effects"] if row["run_id"] == str(run_id)
                and row["kind"] == "model_call" and row["status"] == "ready"]) == 1
    events = [row for row in after["events"] if row not in before["events"]]
    assert len(events) == 1 and all(row in after["events"] for row in before["events"]), events
    event = events[0]
    assert event["entity_type"] == "run" and event["entity_id"] == str(run_id), event
    assert event["effect_id"] == command_id and event["event_kind"] == "interaction_responded", event
    assert event["payload"] == {"run_id": str(run_id), "interaction_id": interaction["interaction_id"],
                                 "generation": generation + 1}, event
    assert len(after["requests"]) == len(before["requests"]) + 1
    assert all(row in after["requests"] for row in before["requests"])
    receipt = next(row for row in after["requests"] if row["effect_id"] == command_id)
    assert receipt["kind"] == "command_respond" and receipt["response"] == result, receipt
    payload = {"run_id": str(run_id), "interaction_id": interaction["interaction_id"],
               "response": answer, "expected_generation": generation}
    assert one(owner, "SELECT request_bytes=convert_to(v24.canonical_json(%s),'UTF8') "
                      "AND request_digest=sha256(request_bytes) FROM v24.requests WHERE effect_id=%s",
               (Json(payload), command_id)), receipt
    owner.rollback()
    for table in EXPECTED_TABLES - {"runs", "effects", "requests", "events"}:
        assert after[table] == before[table], (table, "respond changed shared state/pins")
    replay, replay_raw = respond(login, run_id, interaction["interaction_id"], answer, generation, key)
    login.commit()
    assert replay == result and replay_raw == raw, "respond same-key replay changed bytes"
    assert state(owner) == after, "respond same-key replay wrote rows"
    owner.rollback()
    # A distinct key sees consumption before checking the now-stale generation.
    assert_respond_failure(owner, login, run_id, interaction["interaction_id"], generation,
                           "interaction_mismatch", w1=True)


def respond_contract(db, owner):
    service, operator, admin = (db.connect(alias) for alias in ("service", "operator", "admin"))
    for alias, login in (("service", service), ("operator", operator), ("admin", admin)):
        assert one(login, "SELECT jsonb_build_array(session_user,current_user)") == [db.roles[alias]] * 2
        assert not one(login, "SELECT pg_has_role(session_user,'v24_owner','USAGE')")
        login.commit()
    for login in (service, operator):
        run_id, interaction = respond_fixture(owner, login)
        iid = interaction["interaction_id"]
        assert_respond_failure(owner, login, run_id, uuid4(), 4, "interaction_mismatch", w1=True)
        assert_respond_failure(owner, login, run_id, uuid4(), 0, "interaction_mismatch", w1=True)
        assert_respond_failure(owner, login, run_id, iid, 0, "stale_generation", w1=True)
        stranger = operator if login is service else service
        assert_respond_failure(owner, stranger, run_id, iid, 4, "unauthorized")
        assert_respond_success(owner, login, run_id, interaction)

    principal = one(service, "SELECT v24.principal_id(session_user)")
    service.commit()
    running = seed_run(owner, principal)
    assert_respond_failure(owner, service, running, uuid4(), 1, "interaction_mismatch", w1=True)
    assert_respond_failure(owner, service, uuid4(), uuid4(), 1, "invalid_args")
    for status in ("completed", "failed", "cancelled"):
        terminal = seed_run(owner, principal, status=status, ended_at=datetime.now(timezone.utc))
        assert_respond_failure(owner, service, terminal, uuid4(), 99, "already_terminal", w1=True)
        assert_respond_failure(owner, operator, terminal, uuid4(), 99, "unauthorized")
    # Declared S4 W3 alignment (D-S4-3): blocked_unknown returns its own W0 code
    # before the interaction/CAS checks and writes neither effect nor receipt.
    blocked = seed_run(owner, principal, status="blocked_unknown",
                       ended_at=datetime.now(timezone.utc))
    assert_respond_failure(owner, service, blocked, uuid4(), 99, "blocked_unknown")
    assert_respond_failure(owner, operator, blocked, uuid4(), 99, "unauthorized")
    waiting, interaction = respond_fixture(owner, service)
    for rid, iid, answer, generation, key in (
            (None, interaction["interaction_id"], {}, 4, "valid"),
            (waiting, None, {}, 4, "valid"), (waiting, interaction["interaction_id"], [], 4, "valid"),
            (waiting, interaction["interaction_id"], "text", 4, "valid"),
            (waiting, interaction["interaction_id"], {}, -1, "valid"),
            (waiting, interaction["interaction_id"], {}, None, "valid"),
            (waiting, interaction["interaction_id"], {}, 4, ""),
            (waiting, interaction["interaction_id"], {}, 4, "k" * 513)):
        assert_respond_failure(owner, service, rid, iid, generation, "invalid_args", response=answer, key=key)
    # Admin owns no run but retains the protocol ownership bypass, including key length 512.
    assert_respond_success(owner, admin, waiting, interaction, key="r" * 512)
    for conn in (service, operator, admin):
        conn.close()
    print("[G2a-8] real service/operator/admin respond: full seeded interaction consumed; "
          "running/generation/revision+1; exactly one ready no_replay model successor with response/origin; "
          "unchanged old effects/pins/shared state; event/receipt; W0 auth/missing/local limits; "
          "interaction-before-CAS, valid-interaction stale, terminal precedence; byte-equal replay")



def pin_barrier_fixture(owner, service, admin):
    """Reuse S2 seeds; real on activates B with an advertised dependency."""
    root, a, creator = start_fixture(owner, service)
    realm = one(owner, "SELECT default_realm FROM v24.scopes WHERE scope_id=%s", (root,))
    iid = seed_install(owner, scope_id=root, creator=creator,
                       provides=[{"realm": realm, "key": "dep"}])
    fid = seed_fiber(owner, install_id=iid, scope_id=root, creator=creator)
    owner.commit()
    on = one(admin, "SELECT v24.fiber_control(%s,'on',0,%s)", (fid, f"g3b-on-{uuid4()}"))
    admin.commit()
    assert on.get("disposition") == "committed" and len(on["emitted"]) == 1, on
    b = {"install": iid, "fiber": fid, "episode": on["emitted"][0]}
    b["slot"] = one(owner, "SELECT slot_id FROM v24.slots WHERE fiber_id=%s", (fid,))
    owner.rollback()
    return root, a, b


def barrier_start(service, root, owner_fiber):
    response, _ = start(service, root, owner_fiber, {"requires": [{"key": "dep"}]},
                        {"steps": 3, "tool_calls": 2}, f"g3b-start-{uuid4()}")
    assert response.get("disposition") == "committed", response
    return response


def barrier_off(admin, b, seq):
    return one(admin, "SELECT v24.fiber_control(%s,'off',%s,%s)",
               (b["fiber"], seq, f"g3b-off-{uuid4()}"))


def assert_barrier_state(owner, b, *, closed):
    slot = one(owner, "SELECT to_jsonb(s) FROM v24.slots s WHERE slot_id=%s", (b["slot"],))
    ep = one(owner, "SELECT to_jsonb(e) FROM v24.episodes e WHERE episode_id=%s", (b["episode"],))
    fiber = one(owner, "SELECT to_jsonb(f) FROM v24.fibers f WHERE fiber_id=%s", (b["fiber"],))
    assert slot["withdrawn_at"] is not None and fiber["want_on"] is False, (slot, fiber)
    if closed:
        assert slot["released_at"] is not None and slot["released_at"] >= slot["withdrawn_at"], slot
        assert ep["state"] == "closed" and ep["closed_at"] is not None, ep
        assert fiber["current_episode_id"] is None, fiber
    else:
        assert slot["released_at"] is None and ep["state"] == "retiring" and ep["closed_at"] is None, (slot, ep)
        assert fiber["current_episode_id"] == str(b["episode"]), fiber
    owner.rollback()


def run_pin_provider_barrier(db, owner):
    service, admin = db.connect("service"), db.connect("admin")
    root, a, b = pin_barrier_fixture(owner, service, admin)
    response = barrier_start(service, root, a["fiber"])
    service.commit()
    run_id, model_id = response["emitted"]
    pin = one(owner, "SELECT to_jsonb(p) FROM v24.pins p WHERE consumer_run_id=%s", (run_id,))
    run = one(owner, "SELECT to_jsonb(r) FROM v24.runs r WHERE run_id=%s", (run_id,))
    assert pin["slot_id"] == str(b["slot"]) and pin["provider_episode_id"] == str(b["episode"]), pin
    assert pin["consumer_type"] == "run" and pin["released_at"] is None, pin
    assert one(owner, "SELECT count(*) FROM v24.pins WHERE provider_episode_id=%s "
                      "AND consumer_type='episode' AND released_at IS NULL", (b["episode"],)) == 0
    owner.rollback()
    off = barrier_off(admin, b, 1)
    admin.commit()
    assert off.get("disposition") == "deferred", off
    assert_barrier_state(owner, b, closed=False)
    assert one(owner, "SELECT to_jsonb(p) FROM v24.pins p WHERE pin_id=%s", (pin["pin_id"],)) == pin
    owner.rollback()
    print("[G3b-1 phase 1] only a run pin blocks B off: deferred, withdrawn/unreleased slot, retiring/open episode")

    assert_start_failure(owner, service, root, a["fiber"], {"requires": [{"key": "dep"}]},
                         {"steps": 3, "tool_calls": 2}, "dependency_unresolved", w1=True)
    assert one(owner, "SELECT to_jsonb(p) FROM v24.pins p WHERE pin_id=%s", (pin["pin_id"],)) == pin
    assert one(owner, "SELECT to_jsonb(r) FROM v24.runs r WHERE run_id=%s", (run_id,)) == run
    assert one(owner, "SELECT p.released_at IS NULL AND s.released_at IS NULL "
                      "AND s.withdrawn_at IS NOT NULL AND e.state='retiring' "
                      "FROM v24.pins p JOIN v24.slots s ON s.slot_id=p.slot_id "
                      "JOIN v24.episodes e ON e.episode_id=p.provider_episode_id "
                      "WHERE p.pin_id=%s", (pin["pin_id"],)) is True
    owner.rollback()
    print("[G3b-3] withdrawn slot rejects new start with dependency_unresolved/receipt only; existing run and pin unchanged/valid")
    assert_cancel_success(owner, service, run_id, 1, ready_ids=(model_id,))
    assert one(owner, "SELECT released_at IS NOT NULL AND released_by_effect IS NOT NULL "
                      "FROM v24.pins WHERE pin_id=%s", (pin["pin_id"],)) is True
    owner.rollback()
    off2 = barrier_off(admin, b, 2)
    admin.commit()
    assert off2.get("disposition") == "committed", off2
    assert_barrier_state(owner, b, closed=True)
    print("[G3b-1 phase 2] cancel without claimed effects releases run pin; second B off releases slot and closes episode")
    service.close()
    admin.close()


def claimed_reference_barrier(db, owner):
    service = db.connect("service")
    run_id, model_id, pins = cancel_fixture(owner, service)
    held_pin, tool_id = pins[0]["pin_id"], str(uuid4())
    seed_effect(owner, tool_id, kind="tool_call", run_id=run_id, pin_id=held_pin,
                status="claimed", attempt_no=1, fence=1, claim_owner="fake-worker",
                lease_until=datetime.now(timezone.utc) + timedelta(minutes=5), generation=1)
    owner.commit()
    assert len(pins) > 1, pins
    assert_cancel_success(owner, service, run_id, 1, ready_ids=(model_id,),
                          claimed_ids=(tool_id,), held_pins=(held_pin,))
    held = one(owner, "SELECT to_jsonb(e) FROM v24.effects e WHERE effect_id=%s", (tool_id,))
    assert held["pin_id"] == held_pin and held["status"] == "claimed", held
    assert held["cancel_requested"] is True and held["settled_at"] is None, held
    assert one(owner, "SELECT count(*) FROM v24.pins WHERE consumer_run_id=%s "
                      "AND released_at IS NULL", (run_id,)) == 1
    assert one(owner, "SELECT count(*) FROM v24.pins WHERE consumer_run_id=%s "
                      "AND pin_id<>%s AND released_at IS NOT NULL", (run_id, held_pin)) == len(pins) - 1
    owner.rollback()
    service.close()
    print("[G3b-2] claimed tool keeps exact run pin and claim token, cancel_requested=true; "
          "other unreferenced pins released; full claimed/unknown settlement release unverified / S4")


def dispose_and_settle(owner, admin, service, b):
    disposed = one(admin, "SELECT v24.dispose(%s,%s)", (b["install"], f"g3b-dispose-{uuid4()}"))
    admin.commit()
    assert disposed.get("disposition") == "committed" and len(disposed["emitted"]) == 1, disposed
    fiber = one(owner, "SELECT to_jsonb(f) FROM v24.fibers f WHERE fiber_id=%s", (b["fiber"],))
    assert fiber["disposed_at"] is not None and fiber["current_episode_id"] is None, fiber
    owner.rollback()
    # Existing S2 host-release protocol; no external IO occurs.
    release_id = disposed["emitted"][0]
    token = advance(service, release_id, claim())["claim"]
    service.commit()
    settled = advance(service, release_id, {"v": 1, "class": "success", "claim": token, "body": {}})
    service.commit()
    assert settled.get("disposition") == "committed", settled
    assert one(owner, "SELECT state='disposed' AND disposed_at IS NOT NULL FROM v24.installs "
                      "WHERE install_id=%s", (b["install"],)) is True
    assert one(owner, "SELECT count(*) FROM v24.pins p JOIN v24.slots s USING(slot_id) "
                      "WHERE s.fiber_id=%s AND p.released_at IS NULL", (b["fiber"],)) == 0
    owner.rollback()


def start_dispose_orders(db, owner):
    """Two fresh committed sequential orders; no concurrent-race claim."""
    service, admin = db.connect("service"), db.connect("admin")
    root, _, b = pin_barrier_fixture(owner, service, admin)
    response = barrier_start(service, root, b["fiber"])
    service.commit()
    run_id, model_id = response["emitted"]
    off = barrier_off(admin, b, 1)
    admin.commit()
    assert off.get("disposition") == "deferred", off
    pending = one(admin, "SELECT v24.dispose(%s,%s)", (b["install"], f"g3b-pending-{uuid4()}"))
    admin.commit()
    assert pending.get("disposition") == "committed" and pending["emitted"] == [], pending
    assert one(owner, "SELECT state FROM v24.installs WHERE install_id=%s", (b["install"],)) == "dispose_pending"
    assert one(owner, "SELECT disposed_at FROM v24.fibers WHERE fiber_id=%s", (b["fiber"],)) is None
    assert one(owner, "SELECT count(*) FROM v24.effects WHERE kind='host_release' "
                      "AND request->>'install_id'=%s", (str(b["install"]),)) == 0
    owner.rollback()
    assert_barrier_state(owner, b, closed=False)
    assert_cancel_success(owner, service, run_id, 1, ready_ids=(model_id,))
    off2 = barrier_off(admin, b, 2)
    admin.commit()
    assert off2.get("disposition") == "committed", off2
    assert_barrier_state(owner, b, closed=True)
    dispose_and_settle(owner, admin, service, b)

    root2, _, b2 = pin_barrier_fixture(owner, service, admin)
    # S2 dispose requires the active episode to drain before tombstoning.
    off_first = barrier_off(admin, b2, 1)
    admin.commit()
    assert off_first.get("disposition") == "committed", off_first
    assert_barrier_state(owner, b2, closed=True)
    dispose_and_settle(owner, admin, service, b2)
    assert_start_failure(owner, service, root2, b2["fiber"], {"requires": [{"key": "dep"}]},
                         {"steps": 3, "tool_calls": 2}, "provider_unavailable", w1=True)
    assert one(owner, "SELECT count(*) FROM v24.runs WHERE owner_fiber_id=%s", (b2["fiber"],)) == 0
    assert one(owner, "SELECT count(*) FROM v24.pins p JOIN v24.slots s USING(slot_id) "
                      "WHERE s.fiber_id=%s AND p.released_at IS NULL", (b2["fiber"],)) == 0
    owner.rollback()
    service.close()
    admin.close()
    print("[G3b-4] two fresh sequential orders: start/off deferred/dispose_pending not tombstoned, "
          "cancel/off closes/dispose completes; off drain/dispose first tombstones and closes, "
          "later start provider_unavailable with zero run/dangling pin; concurrency not claimed")


def serialized_second(db, holder, worker, first, second):
    """Observe second real command waiting on first command's G lock."""
    import queue
    import threading
    import time

    observer = db.connect()
    observer.autocommit = True
    result = queue.Queue()
    with worker.cursor() as cur:
        cur.execute("SET statement_timeout='10s'")
    worker.commit()
    holder_pid, worker_pid = holder.get_backend_pid(), worker.get_backend_pid()
    first_response = first()

    def run():
        try:
            response = second()
            worker.commit()
            result.put((response, None))
        except Exception as exc:
            worker.rollback()
            result.put((None, exc))

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not one(observer, "SELECT %s=ANY(pg_blocking_pids(%s))", (holder_pid, worker_pid)):
            assert thread.is_alive(), "second command finished before waiting on the first"
            assert time.monotonic() < deadline, "second command did not block on the first"
        assert one(observer, "SELECT count(*) FROM pg_locks WHERE pid=%s "
                             "AND locktype='advisory' AND NOT granted", (worker_pid,)) >= 1
        holder.commit()
        second_response, error = result.get(timeout=10)
        assert error is None, error
        thread.join(timeout=5)
        assert not thread.is_alive(), "second command did not finish after G release"
        return first_response, second_response
    finally:
        holder.rollback()
        thread.join(timeout=12)
        observer.close()


def start_off_orders(db, owner):
    service, admin = db.connect("service"), db.connect("admin")
    root, a, b = pin_barrier_fixture(owner, service, admin)
    started, off = serialized_second(
        db, service, admin, lambda: barrier_start(service, root, a["fiber"]),
        lambda: barrier_off(admin, b, 1))
    assert started.get("disposition") == "committed" and off.get("disposition") == "deferred", (started, off)
    assert_barrier_state(owner, b, closed=False)
    pin = one(owner, "SELECT to_jsonb(p) FROM v24.pins p WHERE consumer_run_id=%s", (started["emitted"][0],))
    assert pin["slot_id"] == str(b["slot"]) and pin["released_at"] is None, pin
    owner.rollback()

    root2, a2, b2 = pin_barrier_fixture(owner, service, admin)
    def late_start():
        return start(service, root2, a2["fiber"], {"requires": [{"key": "dep"}]},
                     {"steps": 3, "tool_calls": 2}, f"g3b-off-first-{uuid4()}")[0]
    off_first, rejected = serialized_second(
        db, admin, service, lambda: barrier_off(admin, b2, 1), late_start)
    assert off_first.get("disposition") == "committed", off_first
    assert rejected == {"v": 1, "error": {"code": "dependency_unresolved", "detail": {}}}, rejected
    assert_barrier_state(owner, b2, closed=True)
    assert one(owner, "SELECT count(*) FROM v24.runs WHERE scope_id=%s", (root2,)) == 0
    assert one(owner, "SELECT count(*) FROM v24.pins p JOIN v24.slots s USING(slot_id) "
                      "WHERE s.fiber_id=%s", (b2["fiber"],)) == 0
    owner.rollback()
    service.close()
    admin.close()
    print("[G3b-5] two fresh fixtures/two connections: pg_blocking_pids + waiting advisory pg_locks "
          "prove G serialization; start-first/off deferred; off-first/start dependency_unresolved with no run/pin")

def main():
    with server_helper_scope(), setup_db() as db:
        owner = db.connect()
        with owner.cursor() as cur:
            cur.execute("SET ROLE v24_owner")
        owner.commit()
        read_surface(db, owner)
        owner_start(db, owner)
        ownerless_start(db, owner)
        start_failures(db, owner)
        start_boundaries(db, owner)
        claim_guard(db, owner)
        poll_contract(db, owner)
        wait_check_contract(db, owner)
        cancel_contract(db, owner)
        steer_contract(db, owner)
        respond_contract(db, owner)
        run_pin_provider_barrier(db, owner)
        claimed_reference_barrier(db, owner)
        start_dispose_orders(db, owner)
        start_off_orders(db, owner)
        _assert_closed_catalog(owner)
    print("[passed] v24 S3 W1-W7: read surface + start + poll/wait_check + cancel + steer + respond "
          "(G2a-0/1/2/3/4/5/6/7/8/10/11; G3b-1..5; claimed/unknown settlement release reserved S4)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
