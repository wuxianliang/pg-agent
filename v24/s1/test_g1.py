"""G1: kernel, commands, claim/settlement and production ACL gates.

Migration-owner DML seeds states and injects transactional faults.
Protocol probes use real LOGIN roles without test-local privilege grants.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import json
import re
import time
from uuid import uuid4

import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json

from fake_host import FakeHost, HostCrash
from setup_db import EXPECTED_TABLES, _assert_closed_catalog, server_helper_scope, setup_db
from test_ddl import effect, insert, scope, seed_rows


def one(conn, statement, params=()):
    with conn.cursor() as cur:
        cur.execute(statement, params)
        return cur.fetchone()[0]


def advance(conn, effect_id, outcome):
    return one(conn, "SELECT v24.advance(%s,%s)", (effect_id, Json(outcome)))


def state(conn):
    """All ten tables, all columns, including bytea, receipt and claim fields."""
    result = {}
    for table in sorted(EXPECTED_TABLES):
        result[table] = one(conn, sql.SQL(
            "SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text), '[]') "
            "FROM v24.{} t").format(sql.Identifier(table)))
    return result


def rejects_without_writes(owner, login, effect_id, outcome, code):
    before = state(owner)
    response = advance(login, effect_id, outcome)
    assert response == {"v": 1, "error": {"code": code, "detail": {}}}, response
    # Commit as well: a rejection must not hide writes in an uncommitted txn.
    login.commit()
    assert state(owner) == before, (code, outcome)
    owner.rollback()
    return response


def sqlstate(conn, code, action, message=None):
    """Expected SQL errors are contained in savepoints, not whole-txn retries."""
    with conn.cursor() as cur:
        cur.execute("SAVEPOINT w3_probe")
    try:
        action()
    except psycopg2.Error as exc:
        actual, text = exc.pgcode, str(exc)
        with conn.cursor() as cur:
            cur.execute("ROLLBACK TO SAVEPOINT w3_probe")
            cur.execute("RELEASE SAVEPOINT w3_probe")
        assert actual == code, (actual, code, text)
        if message is not None:
            assert message in text, text
        return
    with conn.cursor() as cur:
        cur.execute("ROLLBACK TO SAVEPOINT w3_probe")
        cur.execute("RELEASE SAVEPOINT w3_probe")
    raise AssertionError(f"expected SQLSTATE {code}")


def command(conn, key="w3", kind="command_scope_control", payload=None):
    if payload is None:
        payload = {"action": "create_child"}
    encoded = one(conn, "SELECT encode(convert_to(v24.canonical_json(%s),'UTF8'),'base64')",
                  (Json(payload),))
    effect_id = one(conn, "SELECT v24.effect_id_for(v24.principal_id(session_user),%s,%s)",
                    (key, kind))
    return effect_id, {"v": 1, "class": "command", "claim": None, "body": {
        "op": "admit_and_apply", "kind": kind, "request_key": key,
        "payload": payload, "canonical_bytes": encoded}}


def claim(lease=300000):
    return {"v": 1, "class": "claim", "claim": None, "body": {"lease_ms": lease}}


def settlement(kind="success", owner="wrong-owner", attempt=1, fence=1):
    return {"v": 1, "class": kind, "claim": {
        "attempt": attempt, "fence": fence, "owner": owner}, "body": {"result": "w3"}}


def seed_effect(owner, **fields):
    effect_id = uuid4()
    with owner.cursor() as cur:
        effect(cur, effect_id, **fields)
    owner.commit()
    return effect_id


def expect_envelope(response, effect_id, disposition, token=None):
    assert response == {"v": 1, "disposition": disposition, "effect_id": str(effect_id),
                        "emitted": [], "revision": 0, "claim": token}, response


def catalog(owner):
    with owner.cursor() as cur:
        cur.execute("""SELECT p.proname, p.prosecdef, p.provolatile,
                              p.proconfig, pg_get_functiondef(p.oid)
                         FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
                        WHERE n.nspname='v24'""")
        functions = {r[0]: r[1:] for r in cur.fetchall()}
    read_definers = {"resolve", "run_owner", "run_projection", "poll", "wait_check"}
    assert {n for n, r in functions.items() if r[0]} == {"advance"} | read_definers
    assert functions["advance"][2] == ["search_path=pg_catalog, v24"]
    for name in read_definers:
        security, volatility, config, definition = functions[name]
        assert security and volatility == "s", (name, functions[name])
        assert config == ["search_path=pg_catalog, v24"], (name, config)
        assert not re.search(r"\b(?:INSERT|UPDATE|DELETE|pg_advisory\w*)\b",
                             definition, re.IGNORECASE), (name, definition)
    for helper in ("canonical_json", "principal_id", "effect_id_for", "error_v1"):
        assert functions[helper][0:2] == (False, "i"), (helper, functions[helper])
    for name, (_, _, _, definition) in functions.items():
        assert not name.startswith(("claim_", "lease_", "acquire_")), name
        if "UPDATE v24.effects" in definition:
            assert name in {
                "advance",
                "validate_and_apply_install_delta",
                "validate_and_apply_delta",
            }, name
            if name != "advance":
                assert not functions[name][0]  # INVOKER; no application table privileges
        if "pg_advisory_xact_lock" in definition:
            assert name == "advance", name
    for wrapper in ("scope_control", "install", "start", "cancel", "steer", "respond"):
        assert not functions[wrapper][0], wrapper
        body = functions[wrapper][3]
        assert "v24.advance(" in body, wrapper
        for write in ("INSERT INTO", "UPDATE v24.", "DELETE FROM", "pg_advisory_xact_lock"):
            assert write not in body, (wrapper, write)
    assert one(owner, """SELECT count(*) FROM pg_proc
        WHERE pronamespace='v24'::regnamespace AND proowner<>'v24_owner'::regrole""") == 0
    assert one(owner, """SELECT count(*) FROM pg_proc p,
        LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
        WHERE p.pronamespace='v24'::regnamespace AND a.grantee=0
          AND a.privilege_type='EXECUTE'""") == 0
    definition = functions["advance"][3]
    first = definition.index("PERFORM pg_advisory_xact_lock")
    assert first < definition.index("FROM v24.requests") < definition.index("FOR UPDATE")
    locks = [definition.index(s) for s in (
        "PERFORM scope_id FROM v24.scopes", "PERFORM run_id FROM v24.runs",
        "PERFORM effect_id FROM v24.effects", "PERFORM install_id FROM v24.installs",
        "PERFORM fiber_id FROM v24.fibers", "PERFORM episode_id FROM v24.episodes",
        "PERFORM slot_id FROM v24.slots", "PERFORM pin_id FROM v24.pins")]
    assert locks == sorted(locks)
    for term in ("http", "dblink", "pg_sleep", "current_setting", "current_user"):
        # Comments explain why current_user is forbidden; strip them first.
        body = "\n".join(line.split("--", 1)[0] for line in definition.splitlines())
        assert term not in body.lower(), term
    assert one(owner, "SELECT v24.canonical_json('{\"b\":2,\"a\":1}'::jsonb)") == '{"a": 1, "b": 2}'
    assert one(owner, "SELECT v24.principal_id('example'::name)=md5('example')::uuid")
    assert one(owner, """SELECT v24.effect_id_for(v24.principal_id('example'), 'key', 'kind') =
        substr(encode(sha256(convert_to(v24.principal_id('example')::text || ':kind:key',
        'UTF8')),'hex'),1,32)::uuid""")
    codes = """invalid_args unauthorized not_found_or_denied request_conflict effect_id_conflict
        receipt_conflict stale_generation registration_stale already_terminal owner_closing
        install_not_ready interaction_mismatch provider_unavailable scope_closed dependency_unresolved
        provide_conflict install_identity_conflict budget_exceeded invalid_outcome stale_claim
        cleanup_cycle retry_with_closure blocked_unknown""".split()
    assert len(codes) == 23
    for code in codes:
        assert one(owner, "SELECT v24.error_v1(%s)->'error'->>'code'", (code,)) == code
    sqlstate(owner, "22023", lambda: one(owner, "SELECT v24.error_v1('no_interpreter')"))
    owner.rollback()
    print("[G1-A] advance is sole writable DEFINER; closed read DEFINER allowlist; "
          "pure helpers; closed error set; ordered lock pass")


def shapes(owner, service):
    effect_id = seed_effect(owner)
    # §4.21.1: six nonmembers, including JSON null and a case variant.
    for value in ("COMMAND", None, "settle", "", "host", 7):
        outcome = claim()
        outcome["class"] = value
        rejects_without_writes(owner, service, effect_id, outcome, "invalid_args")
    invalid = [None, [], {}, {"v": 1, "class": "claim", "body": {"lease_ms": 1}},
               {"v": 2, "class": "claim", "claim": None, "body": {"lease_ms": 1}}]
    for cls in ("command", "claim"):
        _, cmd = command(service)
        bad = cmd if cls == "command" else claim()
        bad["claim"] = {"attempt": 0, "fence": 0, "owner": "spoof"}
        invalid.append(bad)
    invalid.append(settlement())
    invalid[-1]["body"] = {"large": "x" * 1048576}
    nested = {}
    for _ in range(33):
        nested = {"nested": nested}
    bad = settlement()
    bad["body"] = nested
    invalid.append(bad)
    bad = settlement()
    bad["body"] = {str(i): i for i in range(201)}
    invalid.append(bad)
    _, bad = command(service, kind="command_nonexistent")
    invalid.append(bad)
    for value in (-1, 0, 300001, 1.5, "1", True, None, 10**100):
        invalid.append(claim(value))
    bad = claim()
    bad["body"]["owner"] = "spoof"
    invalid.append(bad)
    for key in ("successors", "intents"):
        for body in ({key: []}, {"nested": {key: []}}):
            bad = settlement("unknown")
            bad["body"] = body
            invalid.append(bad)
    for token in (None, {}, {"attempt": "1", "fence": 1, "owner": "x"},
                  {"attempt": -1, "fence": 1, "owner": "x"},
                  {"attempt": 1, "fence": 1.5, "owner": "x"},
                  {"attempt": 1, "fence": 1, "owner": None},
                  {"attempt": 2**63, "fence": 1, "owner": "x"}):
        bad = settlement()
        bad["claim"] = token
        invalid.append(bad)
    for field, value in (("op", "claim"), ("payload", []), ("request_key", ""),
                         ("request_key", "x" * 513), ("canonical_bytes", "!bad"),
                         ("canonical_bytes", "e30=")):
        _, bad = command(service)
        bad["body"][field] = value
        invalid.append(bad)
    _, bad = command(service)
    bad["body"]["payload"]["changed_after_canonicalization"] = True
    invalid.append(bad)
    for outcome in invalid:
        rejects_without_writes(owner, service, effect_id, outcome, "invalid_args")
    # Boundary values are valid and actually issue qualifications.
    for lease in (1, 300000):
        eid = seed_effect(owner)
        response = advance(service, eid, claim(lease))
        expect_envelope(response, eid, "committed", {
            "attempt": 1, "fence": 1, "owner": one(service, "SELECT session_user::text")})
        service.commit()
    print("[G1-Q / Done 1,2] six nonmembers; eight shape families; byte binding; lease boundaries")


def identities_and_matrix(owner, connections, db):
    service = connections["service"]
    before = one(service, "SELECT v24.principal_id(session_user)")
    login = one(service, "SELECT session_user::text")
    with service.cursor() as cur:
        cur.execute("SET ROLE v24_service")
    assert one(service, "SELECT current_user::text") == "v24_service"
    assert one(service, "SELECT v24.principal_id(session_user)") == before
    assert before != one(service, "SELECT v24.principal_id(current_user)")
    eid = seed_effect(owner)
    expect_envelope(advance(service, eid, claim()), eid, "committed",
                    {"attempt": 1, "fence": 1, "owner": login})
    with service.cursor() as cur:
        cur.execute("RESET ROLE")
    service.commit()
    for alias, conn in connections.items():
        assert one(conn, "SELECT session_user::text") == db.roles[alias]
        # Both command rows: admin only for root, all three for other commands.
        for action in ("create_root", "create_child"):
            eid, outcome = command(conn, key=f"matrix-{alias}-{action}", payload={"action": action})
            if action == "create_root" and alias != "admin":
                rejects_without_writes(owner, conn, eid, outcome, "unauthorized")
            else:
                before_state = state(owner)
                response = advance(conn, eid, outcome)
                if action == "create_root" and alias == "admin":
                    assert response["disposition"] == "committed", response
                    conn.commit()
                    owner.rollback()
                else:
                    assert response.get("error", {}).get("code") == "invalid_args", (action, alias, response)
                    conn.commit()
                    assert state(owner) == before_state
                    owner.rollback()
        for cls in ("claim", "success", "failure", "unknown"):
            eid = seed_effect(owner)
            outcome = claim() if cls == "claim" else settlement(cls)
            if alias != "service":
                rejects_without_writes(owner, conn, eid, outcome, "unauthorized")
            elif cls == "claim":
                response = advance(conn, eid, outcome)
                expect_envelope(response, eid, "committed", {
                    "attempt": 1, "fence": 1, "owner": db.roles[alias]})
                conn.commit()
            else:
                rejects_without_writes(owner, conn, eid, outcome, "stale_claim")
    # Shape outranks authorization even for a login with the wrong group.
    bad = claim(0)
    rejects_without_writes(owner, connections["operator"], uuid4(), bad, "invalid_args")
    print("[G1-H1 / matrix] real LOGIN roles; SET ROLE preserves principal and claim_owner; all three rows")


def command_prefix(owner, service):
    eid, outcome = command(service, key="seeded-request")
    response = {"v": 1, "disposition": "committed", "effect_id": str(eid),
                "emitted": [], "revision": 0, "claim": None, "first": "preserved"}
    principal = one(service, "SELECT v24.principal_id(session_user)")
    raw = one(service, "SELECT decode(%s,'base64')", (outcome["body"]["canonical_bytes"],))
    with owner.cursor() as cur:
        effect(cur, eid, kind="command_scope_control", status="succeeded",
               outcome=Json(outcome), settled_at=datetime.now(timezone.utc))
        insert(cur, "requests", principal_id=principal, request_key="seeded-request",
               kind="command_scope_control", request_bytes=raw,
               request_digest=one(owner, "SELECT sha256(%s)", (raw,)),
               effect_id=eid, response=Json(response))
    owner.commit()
    # C0 outranks BOTH possible request matches (same or different bytes).
    rejects_without_writes(owner, service, uuid4(), outcome, "effect_id_conflict")
    _, different = command(service, key="seeded-request", payload={"action": "close"})
    rejects_without_writes(owner, service, uuid4(), different, "effect_id_conflict")
    rejects_without_writes(owner, service, eid, different, "request_conflict")
    before = state(owner)
    replay = advance(service, eid, outcome)
    assert replay == response, replay
    service.commit()
    assert state(owner) == before
    owner.rollback()
    # A matching effect with no request is checked after the ordered lock pass.
    collision, cmd = command(service, key="collision")
    with owner.cursor() as cur:
        effect(cur, collision)
    owner.commit()
    rejects_without_writes(owner, service, collision, cmd, "effect_id_conflict")
    missing, cmd = command(service, key="reaches-interpreter")
    before = state(owner)
    assert advance(service, missing, cmd)["error"]["code"] == "invalid_args"
    service.commit()
    assert state(owner) == before
    owner.rollback()
    print("[G1-F1 / Done 4] C0 before replay/conflict; request prefix; malformed scope args rejected")


def claims_and_receipts(owner, service, login):
    rejects_without_writes(owner, service, uuid4(), claim(), "effect_id_conflict")
    for cls in ("success", "failure", "unknown"):
        rejects_without_writes(owner, service, uuid4(), settlement(cls), "effect_id_conflict")
    command_id = seed_effect(owner, kind="command_install")
    rejects_without_writes(owner, service, command_id, claim(), "invalid_args")
    # S3.1 temporary allowlist: only host_prepare/host_release are claimable
    # until S4 adds model/tool settlement. The claim lifecycle itself is
    # unchanged; this fixture exercises it through a host effect.
    eid = seed_effect(owner, kind="host_prepare")
    before = state(owner)
    token = {"attempt": 1, "fence": 1, "owner": login}
    expect_envelope(advance(service, eid, claim()), eid, "committed", token)
    service.commit()
    after = state(owner)
    for table in EXPECTED_TABLES - {"effects"}:
        assert after[table] == before[table], table
    row = one(owner, "SELECT to_jsonb(e) FROM v24.effects e WHERE effect_id=%s", (eid,))
    assert row["claim_owner"] == login and row["status"] == "claimed"
    assert row["attempt_no"] == row["fence"] == 1
    # Live claim: deferred, no token, and absolutely no changes.
    before = state(owner)
    expect_envelope(advance(service, eid, claim()), eid, "deferred")
    service.commit()
    assert state(owner) == before
    owner.rollback()
    # Expiry is deterministic owner seeding, never a timing-dependent sleep.
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.effects SET lease_until=now()-interval '1s' WHERE effect_id=%s", (eid,))
    owner.commit()
    token = {"attempt": 2, "fence": 2, "owner": login}
    expect_envelope(advance(service, eid, claim()), eid, "committed", token)
    service.commit()
    # Non-host kinds are not claimable until S4 settlement exists.
    unsupported = seed_effect(owner, kind="tool_call", status="claimed", attempt_no=2,
                              fence=2, claim_owner=login,
                              lease_until=datetime.now(timezone.utc) + timedelta(minutes=5))
    rejects_without_writes(owner, service, unsupported, claim(), "invalid_args")
    for cls in ("success", "failure", "unknown"):
        for attempt, fence, who in ((1, 1, login), (2, 1, login), (1, 2, login), (2, 2, "spoof")):
            rejects_without_writes(owner, service, eid, settlement(cls, who, attempt, fence), "stale_claim")
        # Non-host_prepare kinds retain the explicit unsupported boundary.
        before = state(owner)
        sqlstate(service, "0A000", lambda cls=cls: advance(
            service, unsupported, settlement(cls, login, 2, 2)), "v24.interpret_settlement:")
        service.commit()
        assert state(owner) == before
        owner.rollback()
    for cls, status in (("success", "succeeded"), ("failure", "failed"), ("unknown", "unknown")):
        receipt = settlement(cls, login, 99, 99)
        receipt["receipt_key"] = "first-transport-key"
        settled = seed_effect(owner, status=status, outcome=Json(receipt),
                              attempt_no=2, fence=2, settled_at=datetime.now(timezone.utc))
        before = state(owner)
        # Terminal receipt replay wins even with a token unlike historical columns.
        repeat = deepcopy(receipt)
        repeat["receipt_key"] = "new-transport-key"
        expect_envelope(advance(service, settled, repeat), settled, "replay")
        service.commit()
        assert state(owner) == before
        owner.rollback()
        changed = deepcopy(repeat)
        changed["body"]["result"] = "different"
        rejects_without_writes(owner, service, settled, changed, "receipt_conflict")
        rejects_without_writes(owner, service, settled, claim(), "invalid_args")
    cancelled = seed_effect(owner, status="cancelled", settled_at=datetime.now(timezone.utc))
    rejects_without_writes(owner, service, cancelled, claim(), "invalid_args")
    rejects_without_writes(owner, service, cancelled, settlement(), "receipt_conflict")
    print("[G1-Q/R / Done 3,5,6] five unique dispatches; claim ready/live/expired/terminal; receipt before token")


def closure_retry(owner, service, graph):
    missing_install = uuid4()
    eid = seed_effect(owner, scope_id=graph["child"], run_id=graph["run"],
                      fiber_id=graph["f1"], episode_id=graph["ep1"], pin_id=graph["pin"],
                      request=Json({"install_id": str(missing_install)}))
    rejects_without_writes(owner, service, eid, claim(), "retry_with_closure")
    # Repair the JSON-only link (D5), then a fresh G transaction rediscovers it.
    with owner.cursor() as cur:
        insert(cur, "installs", install_id=missing_install, scope_id=graph["root"],
               identity="closure-repair", version="1", manifest=Json({}), manifest_digest=b"w3",
               requires=Json([]), provides=Json([]), artifact_digest=b"w3", adapter_digest=b"w3",
               owner_principal=uuid4(), state="preparing", created_by_effect=graph["effect"])
    owner.commit()
    response = advance(service, eid, claim())
    assert response["disposition"] == "committed" and response["claim"]["attempt"] == 1, response
    service.commit()
    print("[Done 7] dangling install reference retries with zero writes; repaired closure reclaims successfully")


def locks(db, owner, graph):
    blocker, worker, observer = db.connect(), db.connect("service"), db.connect()
    observer.autocommit = True
    eid = seed_effect(owner, scope_id=graph["child"], run_id=graph["run"],
                      fiber_id=graph["f1"], episode_id=graph["ep1"], pin_id=graph["pin"],
                      request=Json({"install_id": str(graph["install"])}))
    pid = one(worker, "SELECT pg_backend_pid()")
    worker.commit()
    one(blocker, "SELECT pg_advisory_xact_lock(24,1)")
    assert one(observer, """SELECT count(*) FROM pg_locks WHERE pid=%s
        AND locktype='advisory' AND classid=24 AND objid=1 AND objsubid=2 AND granted""",
               (blocker.get_backend_pid(),)) == 1
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(advance, worker, eid, claim())
        try:
            deadline = time.monotonic() + 5
            # Poll actual lock evidence; no sleep used to guess execution order.
            while True:
                waiting = one(observer, """SELECT count(*) FROM pg_locks l
                    JOIN pg_stat_activity a ON a.pid=l.pid
                    WHERE l.pid=%s AND l.locktype='advisory' AND l.classid=24
                      AND l.objid=1 AND l.objsubid=2 AND NOT l.granted
                      AND a.wait_event_type='Lock'""", (pid,))
                if waiting == 1:
                    break
                assert not future.done(), future.result() if future.done() else ""
                assert time.monotonic() < deadline, "advance did not block on G within 5s"
            assert one(observer, """SELECT count(*) FROM pg_locks l
                JOIN pg_class c ON c.oid=l.relation
                WHERE l.pid=%s AND l.granted AND c.relnamespace='v24'::regnamespace""", (pid,)) == 0
            assert not future.done()
        finally:
            blocker.rollback()
        response = future.result(timeout=5)
        expect_envelope(response, eid, "committed", {
            "attempt": 1, "fence": 1, "owner": db.roles["service"]})
        worker.commit()
    blocker.close()
    worker.close()
    observer.close()
    print("[G1-L1/L2 / Done 8] exact G lock identity; advisory wait; zero granted v24 relation locks before G")



def scope_control_w4(owner, admin, service):
    # G1-B: one command creates the domain row, settled command effect, request and event.
    payload = {"action": "create_root", "realm_routes": {"k": "r"}, "default_realm": "r"}
    eid, outcome = command(admin, key="w4-root", payload=payload)
    before = state(owner)
    response = advance(admin, eid, outcome)
    assert response["disposition"] == "committed", response
    admin.commit()
    root_id = uuid4()  # response emits the actual generated identifier
    root_id = response["emitted"][0]
    root = one(owner, "SELECT to_jsonb(s) FROM v24.scopes s WHERE scope_id=%s", (root_id,))
    assert root["root_id"] == root_id and root["route_path"] == [root_id] and root["parent_id"] is None
    assert one(owner, "SELECT status FROM v24.effects WHERE effect_id=%s", (eid,)) == "succeeded"
    assert one(owner, "SELECT effect_id FROM v24.requests WHERE request_key='w4-root'") == eid
    assert one(owner, "SELECT count(*) FROM v24.events WHERE effect_id=%s", (eid,)) == 1
    assert len(state(owner)["scopes"]) == len(before["scopes"]) + 1
    first = response
    # G1-D: byte-identical command returns its first response, with zero table diff.
    snapshot = state(owner)
    replay = advance(admin, eid, outcome)
    assert replay == first, (replay, first)
    admin.commit()
    assert state(owner) == snapshot
    owner.rollback()

    child_payload = {"action": "create_child", "parent_scope_id": root_id,
                     "realm_routes": {}, "default_realm": None}
    child_effect, child_outcome = command(admin, key="w4-child", payload=child_payload)
    child_response = advance(admin, child_effect, child_outcome)
    assert child_response["disposition"] == "committed", child_response
    admin.commit()
    child_id = child_response["emitted"][0]
    child = one(owner, "SELECT to_jsonb(s) FROM v24.scopes s WHERE scope_id=%s", (child_id,))
    assert child["root_id"] == root_id and child["route_path"] == [root_id, child_id]
    owner.rollback()

    # G1-B (all-or-nothing): a fault inside command application must leave no
    # partial rows. The trigger fires on the event insert, i.e. after the scope,
    # effect and request rows were already written, so the snapshot equality
    # proves a real rollback rather than a pre-write refusal. It is committed so
    # no DDL lock is held across the two sessions, then dropped explicitly.
    with owner.cursor() as cur:
        cur.execute("""CREATE FUNCTION v24.w6_reject_event() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'w6 event fault' USING ERRCODE='23514'; END $$;
            CREATE TRIGGER w6_reject_event BEFORE INSERT ON v24.events
            FOR EACH ROW EXECUTE FUNCTION v24.w6_reject_event()""")
    owner.commit()
    before = state(owner)
    sqlstate(admin, "23514", lambda: advance(
        admin, *command(admin, "w6-rollback", payload=child_payload)), "w6 event fault")
    admin.commit()
    assert state(owner) == before
    with owner.cursor() as cur:
        cur.execute("DROP TRIGGER w6_reject_event ON v24.events; DROP FUNCTION v24.w6_reject_event()")
    owner.commit()

    close_payload = {"action": "close", "parent_scope_id": child_id}
    close_effect, close_outcome = command(admin, key="w4-close", payload=close_payload)
    close_response = advance(admin, close_effect, close_outcome)
    assert close_response["disposition"] == "committed", close_response
    admin.commit()
    closed = one(owner, "SELECT close_requested_at IS NOT NULL AND closed_at IS NULL FROM v24.scopes WHERE scope_id=%s", (child_id,))
    assert closed
    blocked_effect, blocked_outcome = command(admin, key="w4-child-blocked", payload=child_payload | {"parent_scope_id": child_id})
    blocked = advance(admin, blocked_effect, blocked_outcome)
    assert blocked == {"v":1,"error":{"code":"scope_closed","detail":{}}}, blocked
    admin.commit()
    assert one(owner, "SELECT count(*) FROM v24.effects WHERE effect_id=%s AND status='failed'", (blocked_effect,)) == 1
    assert one(owner, "SELECT response->'error'->>'code' FROM v24.requests WHERE request_key='w4-child-blocked'") == "scope_closed"
    print("[G1-B/D/J2] atomic commit plus injected-fault rollback, byte-equal replay, "
          "root/child route, close intent and scope_closed W1")


def install_settlement_w5(db, owner, admin, service):
    root_effect, root_command = command(admin, "w5-root", payload={"action": "create_root"})
    scope_id = advance(admin, root_effect, root_command)["emitted"][0]
    admin.commit()
    journal = db.connect()
    journal.autocommit = True

    def payload(identity, artifact=b"artifact", provides=None, raw=None):
        manifest = {"identity": identity, "version": "1", "requires": [],
                    "provides": [] if provides is None else provides,
                    "adapter_digest": "\\x" + hashlib.sha256(b"adapter").hexdigest()}
        raw = json.dumps(manifest).encode() if raw is None else raw
        return {"scope_id": scope_id, "owner_fiber_id": None,
                "manifest_bytes": base64.b64encode(raw).decode(), "artifact_digest": "\\x" + artifact.hex()}

    def admit(key, p):
        eid, outcome = command(admin, key, "command_install", p)
        result = advance(admin, eid, outcome)
        admin.commit()
        assert result.get("disposition") == "committed", result
        return eid, outcome, result

    def journal_count(eid):
        return one(journal, "SELECT count(*) FROM v24_fake.journal WHERE effect_id=%s", (eid,))

    def claim_and_io(hid, action):
        token = advance(service, hid, claim())["claim"]
        assert journal_count(hid) == 0
        host = FakeHost(journal, [action])
        try:
            host.prepare(service, hid, token)
        except RuntimeError as exc:
            assert "claim COMMIT" in str(exc), exc
        else:
            raise AssertionError("FakeHost accepted an uncommitted claim")
        assert journal_count(hid) == 0
        assert one(journal, "SELECT status FROM v24.effects WHERE effect_id=%s", (hid,)) == "ready"
        service.commit()
        owner.rollback()
        receipt = host.prepare(service, hid, token)
        assert journal_count(hid) == 1
        # IO returned while domain state still awaits T2.
        assert one(journal, "SELECT status FROM v24.effects WHERE effect_id=%s", (hid,)) == "claimed"
        return receipt

    # Root-only and malformed manifests are W0 even for nonexistent child owners.
    p = payload("invalid")
    for bad in (p | {"owner_fiber_id": str(uuid4())}, p | {"manifest_bytes": "!"},
                p | {"manifest_bytes": base64.b64encode(b"[]").decode()},
                p | {"artifact_digest": "not-bytea"},
                payload("invalid", raw=b'{"identity":"x"}'),
                payload("invalid", raw=b'\xff')):
        eid, outcome = command(admin, "w5-invalid", "command_install", bad)
        rejects_without_writes(owner, admin, eid, outcome, "invalid_args")

    # Admin uses advance directly; install wrapper is service/operator-only (G1-P).
    pure = payload("pure", artifact=b"")
    raw = base64.b64decode(pure["manifest_bytes"])
    response = advance(admin, *command(admin, "w5-pure", "command_install", pure))
    admin.commit()
    iid = response["emitted"][0]
    assert len(response["emitted"]) == 1
    stored = one(owner, "SELECT to_jsonb(i) FROM v24.installs i WHERE install_id=%s", (iid,))
    assert stored["state"] == "installed" and stored["owner_fiber_id"] is None and stored["owner_episode_id"] is None
    assert stored["manifest_digest"] == "\\x" + hashlib.sha256(raw).hexdigest()
    assert stored["identity"] == "pure" and stored["version"] == "1"
    assert stored["requires"] == stored["provides"] == []
    assert stored["manifest"] == json.loads(raw)
    before = state(owner)
    assert advance(admin, *command(admin, "w5-pure", "command_install", pure)) == response
    admin.commit()
    assert state(owner) == before
    _, _, reused = admit("w5-pure-new-key", pure)
    assert reused["emitted"] == [iid]
    assert one(owner, "SELECT count(*) FROM v24.installs WHERE scope_id=%s AND identity='pure'", (scope_id,)) == 1
    for key, conflicting in (("artifact", pure | {"artifact_digest": "\\x01"}),
                              ("manifest", pure | {"manifest_bytes": base64.b64encode(raw+b" ").decode()})):
        eid, outcome = command(admin, "w5-conflict-"+key, "command_install", conflicting)
        refused = advance(admin, eid, outcome)
        assert refused["error"]["code"] == "install_identity_conflict", refused
        admin.commit()
        before = state(owner)
        assert advance(admin, eid, outcome) == refused
        admin.commit()
        assert state(owner) == before
        assert one(owner, "SELECT status FROM v24.effects WHERE effect_id=%s", (eid,)) == "failed"
    owner.rollback()

    for action, cls, target, status in (("succeed", "success", "installed", "succeeded"),
                                        ("fail", "failure", "prepare_failed", "failed"),
                                        ("unknown", "unknown", "prepare_unknown", "unknown")):
        p = payload(action, artifact=b"", provides=[{"realm": "test", "key": action}])
        eid, outcome, result = admit("w5-"+action, p)
        iid, hid = result["emitted"]
        assert one(owner, "SELECT state FROM v24.installs WHERE install_id=%s", (iid,)) == "preparing"
        effect_before = one(owner, "SELECT to_jsonb(e) FROM v24.effects e WHERE effect_id=%s", (hid,))
        assert effect_before["status"] == "ready" and effect_before["attempt_no"] == 0
        assert effect_before["request"] == {"install_id": iid, "reservation": "v24:host_prepare:"+hid}
        assert effect_before["parent_effect_id"] == str(eid) and effect_before["ordinal"] == 0
        # Command replay must not re-admit the install or re-emit work.
        before = state(owner)
        assert advance(admin, eid, outcome) == result
        admin.commit()
        assert state(owner) == before
        owner.rollback()
        receipt = claim_and_io(hid, action)
        assert receipt["class"] == cls
        for field in ("attempt", "fence", "owner"):
            bad = deepcopy(receipt)
            bad["claim"][field] = "spoof" if field == "owner" else 0
            rejects_without_writes(owner, service, hid, bad, "stale_claim")
        # T2 rollback and preflight refusal: inject only the pure interpreter's delta.
        before = state(owner)
        requests_before = one(owner, "SELECT count(*) FROM v24.requests")
        definition = one(owner, "SELECT pg_get_functiondef('v24.interpret_settlement(uuid,uuid,jsonb,jsonb)'::regprocedure)")
        malformed = definition.replace("'successors','[]'::jsonb", "'successors',jsonb_build_array('{}'::jsonb)")
        assert malformed != definition
        with owner.cursor() as cur:
            cur.execute(malformed)
        assert advance(owner, hid, receipt)["error"]["code"] == "invalid_outcome"
        assert state(owner) == before
        owner.rollback()  # also restores the interpreter
        # A real DML trigger error aborts all T2 work, including the install update.
        with owner.cursor() as cur:
            cur.execute("""CREATE FUNCTION v24.w5_reject_event() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'w5 event fault' USING ERRCODE='23514'; END $$;
                CREATE TRIGGER w5_reject_event BEFORE INSERT ON v24.events
                FOR EACH STATEMENT EXECUTE FUNCTION v24.w5_reject_event()""")
        sqlstate(owner, "23514", lambda: advance(owner, hid, receipt), "w5 event fault")
        assert state(owner) == before
        owner.rollback()
        # Install no longer preparing: CAS refusal is zero-write.
        with owner.cursor() as cur:
            cur.execute("UPDATE v24.installs SET state='prepare_failed' WHERE install_id=%s", (iid,))
        changed = state(owner)
        assert advance(owner, hid, receipt)["error"]["code"] == "receipt_conflict"
        assert state(owner) == changed
        owner.rollback()
        expect_envelope(advance(service, hid, receipt), hid, "committed")
        service.commit()
        row = one(owner, "SELECT to_jsonb(e) FROM v24.effects e WHERE effect_id=%s", (hid,))
        assert row["status"] == status and row["outcome"] == receipt and row["settled_at"] is not None
        assert row["claim_owner"] is None and row["lease_until"] is None
        assert row["attempt_no"] == row["fence"] == 1
        assert (row["resource_quiesced_at"] is None) == (cls == "unknown")
        for field in ("requester_id", "request", "request_digest", "parent_effect_id", "ordinal", "created_at"):
            assert row[field] == effect_before[field], field
        assert one(owner, "SELECT state FROM v24.installs WHERE install_id=%s", (iid,)) == target
        assert one(owner, "SELECT count(*) FROM v24.requests") == requests_before
        assert one(owner, "SELECT count(*) FROM v24.events WHERE effect_id=%s", (hid,)) == 1
        assert one(owner, "SELECT count(*) FROM v24.effects WHERE parent_effect_id=%s", (hid,)) == 0
        assert one(owner, "SELECT array_agg(seq ORDER BY seq) FROM v24.events WHERE entity_type='install' AND entity_id=%s", (iid,)) == [1, 2]
        before = state(owner)
        replay = deepcopy(receipt) | {"receipt_key": "retry"}
        expect_envelope(advance(service, hid, replay), hid, "replay")
        service.commit()
        assert state(owner) == before and journal_count(hid) == 1
        conflict = deepcopy(receipt)
        conflict["body"] = {"result": "different"}
        rejects_without_writes(owner, service, hid, conflict, "receipt_conflict")
        rejects_without_writes(owner, service, hid, claim(), "invalid_args")

    # Both crash windows are observable, and neither fabricates a settlement.
    for crash, rows in (("crash_before_journal", 0), ("crash_after_journal", 1)):
        _, _, result = admit("w5-"+crash, payload(crash))
        iid, hid = result["emitted"]
        token = advance(service, hid, claim())["claim"]
        service.commit()
        owner.rollback()
        try:
            FakeHost(journal, [crash]).prepare(service, hid, token)
        except HostCrash as exc:
            assert str(exc) == crash
        else:
            raise AssertionError("scripted host crash did not occur")
        assert journal_count(hid) == rows
        assert one(journal, "SELECT status FROM v24.effects WHERE effect_id=%s", (hid,)) == "claimed"
        assert one(journal, "SELECT state FROM v24.installs WHERE install_id=%s", (iid,)) == "preparing"
        # Reclaim the same reservation; historical token is stale; no second IO.
        with owner.cursor() as cur:
            cur.execute("UPDATE v24.effects SET lease_until=now()-interval '1s' WHERE effect_id=%s", (hid,))
        owner.commit()
        new_token = advance(service, hid, claim())["claim"]
        assert new_token == token | {"attempt": 2, "fence": 2}
        service.commit()
        rejects_without_writes(owner, service, hid, {"v": 1, "class": "success", "claim": token, "body": {}}, "stale_claim")
        receipt = FakeHost(journal, ["succeed"]).prepare(service, hid, new_token)
        assert receipt["class"] == ("success" if rows == 0 else "unknown")
        assert journal_count(hid) == 1
        expect_envelope(advance(service, hid, receipt), hid, "committed")
        service.commit()

    # Closing blocks installs with W1 receipts, never a half-created install.
    eid, outcome = command(admin, "w5-close", payload={"action": "close", "parent_scope_id": scope_id})
    assert advance(admin, eid, outcome)["disposition"] == "committed"
    admin.commit()
    eid, outcome = command(admin, "w5-closed-install", "command_install", payload("closed"))
    refused = advance(admin, eid, outcome)
    assert refused["error"]["code"] == "scope_closed"
    admin.commit()
    assert one(owner, "SELECT status FROM v24.effects WHERE effect_id=%s", (eid,)) == "failed"
    # A third application schema is rejected by the closed catalog assertion.
    with owner.cursor() as cur:
        cur.execute("CREATE SCHEMA w5_forbidden")
    try:
        _assert_closed_catalog(owner)
    except AssertionError:
        pass
    else:
        raise AssertionError("fixture accepted a third schema")
    owner.rollback()
    _assert_closed_catalog(owner)
    owner.rollback()
    journal.close()
    print("[G1-I/J/K/C] claim COMMIT -> FakeHost journal -> atomic T2; three states/quiescence; event once/replay; crash windows")


def permissions(db, owner, connections):
    """G1-P: deny protocol DML while keeping the DEFINER owner functional."""
    migration = db.connect("owner")
    assert one(migration, "SELECT session_user::text") == db.roles["owner"]
    for table in sorted(EXPECTED_TABLES):
        for privilege in ("INSERT", "UPDATE", "DELETE"):
            assert one(migration, "SELECT has_table_privilege(session_user,%s,%s)",
                       ("v24." + table, privilege)), (table, privilege)
    # Real owner LOGIN inserts into all ten tables, including the identity sequence.
    seed_rows(migration)
    probe = uuid4()
    with migration.cursor() as cur:
        effect(cur, probe)
        cur.execute("UPDATE v24.effects SET cancel_requested=true WHERE effect_id=%s RETURNING effect_id", (probe,))
        assert cur.fetchone() == (probe,)
        cur.execute("DELETE FROM v24.effects WHERE effect_id=%s RETURNING effect_id", (probe,))
        assert cur.fetchone() == (probe,)
    migration.commit()
    # Migration ownership does not add a fourth row to the protocol matrix.
    assert advance(migration, uuid4(), claim())["error"]["code"] == "unauthorized"
    migration.rollback()
    migration.close()

    pure = {"canonical_json", "effect_id_for", "principal_id", "error_v1"}
    for alias, conn in connections.items():
        exposed = one(conn, """SELECT array_agg(proname::text ORDER BY proname)
            FROM pg_proc WHERE pronamespace='v24'::regnamespace
              AND has_function_privilege(session_user,oid,'EXECUTE')""")
        expected = pure | {"advance", "scope_control", "resolve", "poll", "wait_check",
                           "fiber_control", "dispose", "start", "cancel", "steer", "respond"}
        if alias != "admin":
            expected.add("install")
        assert set(exposed) == expected, (alias, exposed)
        before = state(owner)
        for table in sorted(EXPECTED_TABLES):
            # Identity/generated columns fail parse-time (428C9) before the
            # executor's 42501 check, so the UPDATE probe needs a plain column.
            column = one(owner, """SELECT attname FROM pg_attribute
                WHERE attrelid=%s::regclass AND attnum>0 AND NOT attisdropped
                  AND attidentity='' AND attgenerated=''
                ORDER BY attnum LIMIT 1""", ("v24." + table,))
            statements = (
                sql.SQL("INSERT INTO v24.{} DEFAULT VALUES").format(sql.Identifier(table)),
                sql.SQL("UPDATE v24.{} SET {}={} WHERE false").format(
                    sql.Identifier(table), sql.Identifier(column), sql.Identifier(column)),
                sql.SQL("DELETE FROM v24.{} WHERE false").format(sql.Identifier(table)),
            )
            for statement in statements:
                sqlstate(conn, "42501", lambda statement=statement: one(conn, statement))
        for forbidden in ("v24_owner", db.roles["owner"], one(owner, "SELECT session_user::text"),
                          *("v24_" + other for other in connections if other != alias)):
            sqlstate(conn, "42501", lambda forbidden=forbidden: one(
                conn, sql.SQL("SET ROLE {}").format(sql.Identifier(forbidden))))
        sqlstate(conn, "42501", lambda: one(conn, sql.SQL("SET SESSION AUTHORIZATION {}").format(
            sql.Identifier(db.roles["owner"]))))
        sqlstate(conn, "42501", lambda: one(conn, "CREATE TABLE v24.acl_bypass(id int)"))
        sqlstate(conn, "42501", lambda: one(conn,
            "SELECT v24.validate_and_apply_delta(NULL,NULL,'{}','{}','{}')"))
        if alias == "admin":
            sqlstate(conn, "42501", lambda: one(conn,
                "SELECT v24.install(NULL,NULL,''::bytea,''::bytea,'admin-denied')"))
        conn.commit()
        assert state(owner) == before
        owner.rollback()

        # TEMP is allowed, but shadows cannot redirect fully qualified entry points.
        # The temp objects must be created *after* SET ROLE: the login role is only a
        # member of the protocol group role, so a temp schema owned by the login role
        # is not readable once the session switches to the group role.
        principal = one(conn, "SELECT v24.principal_id(session_user)")
        with conn.cursor() as cur:
            cur.execute(sql.SQL("SET ROLE {}").format(sql.Identifier("v24_" + alias)))
            cur.execute("CREATE TEMP TABLE effects(marker text); CREATE TEMP TABLE requests(marker text)")
            cur.execute("""CREATE FUNCTION pg_temp.principal_id(name) RETURNS uuid
                LANGUAGE sql IMMUTABLE AS $$ SELECT '00000000-0000-0000-0000-000000000000'::uuid $$""")
            cur.execute("SET search_path=pg_temp,v24")
        assert one(conn, "SELECT v24.principal_id(session_user)") == principal
        if alias == "admin":
            root = one(conn, "SELECT v24.scope_control('create_root',NULL,'{}',NULL,'acl-root')")
            assert root["disposition"] == "committed", root
            sid = root["emitted"][0]
        else:
            # Owner-created parent supplies a real permitted path for each login.
            sid, creator = uuid4(), uuid4()
            with owner.cursor() as cur:
                scope(cur, sid, creator, owner_principal=principal)
                effect(cur, creator)
            owner.commit()
        child = one(conn, "SELECT v24.scope_control('create_child',%s,'{}',NULL,%s)",
                    (sid, "acl-child-" + alias))
        assert child["disposition"] == "committed", child
        conn.commit()
        assert one(owner, "SELECT owner_principal FROM v24.scopes WHERE scope_id=%s",
                   (child["emitted"][0],)) == principal
        if alias != "admin":
            raw = json.dumps({"identity": "acl-" + alias, "version": "1", "requires": [],
                              "provides": [], "adapter_digest": "\\x"}).encode()
            result = one(conn, "SELECT v24.install(%s,NULL,%s,%s,%s)",
                         (sid, raw, b"", "acl-install-" + alias))
            assert result["disposition"] == "committed", result
            conn.commit()
            assert one(owner, "SELECT state FROM v24.installs WHERE install_id=%s",
                       (result["emitted"][0],)) == "installed"
        # advance and all four helpers succeed under each granted LOGIN identity.
        eid, outcome = command(conn, "acl-direct-" + alias, payload={
            "action": "close", "parent_scope_id": child["emitted"][0]})
        assert advance(conn, eid, outcome)["disposition"] == "committed"
        assert one(conn, "SELECT v24.error_v1('invalid_args')->'error'->>'code'") == "invalid_args"
        conn.commit()
        closed = one(conn, "SELECT v24.scope_control('close',%s,NULL,NULL,%s)",
                     (sid, "acl-close-" + alias))
        assert closed["disposition"] == "committed", closed
        conn.commit()
        assert one(conn, "SELECT count(*) FROM pg_temp.effects") == 0
        assert one(conn, "SELECT count(*) FROM pg_temp.requests") == 0
        with conn.cursor() as cur:
            cur.execute("DROP TABLE pg_temp.effects,pg_temp.requests")
            cur.execute("DROP FUNCTION pg_temp.principal_id(name)")
            cur.execute("RESET ROLE; RESET search_path")
        conn.commit()
        owner.rollback()
        print(f"[G1-P/{alias}] 30 DML refusals=42501; exact EXECUTE; SET ROLE/TEMP cannot escalate")
    print("[G1-P/owner] real owner LOGIN inserts ten tables and updates/deletes; no protocol membership")


def main():
    with server_helper_scope(), setup_db() as db:
        owner = db.connect()
        with owner.cursor() as cur:
            cur.execute("SET ROLE v24_owner")
        owner.commit()
        connections = {alias: db.connect(alias) for alias in ("admin", "service", "operator")}
        service = connections["service"]
        catalog(owner)
        permissions(db, owner, connections)
        graph = seed_rows(owner)  # migration owner; exercises every lock-vector level
        shapes(owner, service)
        identities_and_matrix(owner, connections, db)
        command_prefix(owner, service)
        claims_and_receipts(owner, service, db.roles["service"])
        closure_retry(owner, service, graph)
        locks(db, owner, graph)
        scope_control_w4(owner, connections["admin"], service)
        install_settlement_w5(db, owner, connections["admin"], service)
    print("[passed] v24 G1 kernel, commands, claim, locks, host_prepare settlement and ACL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
