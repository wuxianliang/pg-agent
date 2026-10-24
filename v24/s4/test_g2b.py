"""G2b W1 subset: model-only loop spine, claim/settle, stage guard, reserve.

The gate drives the real protocol through LOGIN roles and only simulates the
external model call in process.  A claim is always COMMITted and the worker
connection is IDLE before FakeLLM.complete runs; settlement is a later advance.
No sockets, files, randomness, or sleeps are used.
"""
from __future__ import annotations

from datetime import datetime, timezone
import inspect
import json
import re
import socket
import sys
from pathlib import Path
from uuid import uuid4

S1 = Path(__file__).resolve().parent.parent / "s1"
S2 = Path(__file__).resolve().parent.parent / "s2"
S3 = Path(__file__).resolve().parent.parent / "s3"
S4 = Path(__file__).resolve().parent
for stage in (S1, S2, S3, S4):
    if str(stage) not in sys.path:
        sys.path.insert(0, str(stage))

from psycopg2.extensions import TRANSACTION_STATUS_IDLE  # noqa: E402
from psycopg2.extras import Json  # noqa: E402

from fake_llm import FakeLLM, FakeTool  # noqa: E402
from setup_db import (EXPECTED_TABLES, _assert_closed_catalog,  # noqa: E402
                      server_helper_scope, setup_db)
from test_ddl import DIGEST, effect, insert  # noqa: E402
from test_g2 import PROJECTION_KEYS  # noqa: E402
from test_g3a import (advance, claim, one, provider, seed_effect,  # noqa: E402
                      seed_install, seed_scope, sqlstate, state)

OWNER_KEYS = frozenset("""v disposition effect_id emitted revision claim""".split())
POLL_KEYS = frozenset("""v revision changed run events""".split())
WAIT_KEYS = frozenset("""v run events wake""".split())
EVENT_KEYS = frozenset("""seq event_kind payload created_at""".split())
WAKE_KEYS = frozenset("""ready reason""".split())

COMMAND_KINDS = ("command_start", "command_cancel", "command_steer",
                 "command_respond", "command_install", "command_fiber_control",
                 "command_dispose", "command_scope_control")
ERROR_CODES = """invalid_args unauthorized not_found_or_denied request_conflict
    effect_id_conflict receipt_conflict stale_generation registration_stale
    already_terminal owner_closing install_not_ready interaction_mismatch
    provider_unavailable scope_closed dependency_unresolved provide_conflict
    install_identity_conflict budget_exceeded invalid_outcome stale_claim
    cleanup_cycle retry_with_closure blocked_unknown""".split()

_SAVED_NETWORK = None


def deny_network(*args, **kwargs):
    raise AssertionError("v24 S4 gate attempted network I/O")


def install_no_network():
    global _SAVED_NETWORK
    _SAVED_NETWORK = (socket.socket.connect, socket.create_connection)
    socket.socket.connect = deny_network
    socket.create_connection = deny_network


def restore_no_network():
    global _SAVED_NETWORK
    if _SAVED_NETWORK is not None:
        socket.socket.connect, socket.create_connection = _SAVED_NETWORK
        _SAVED_NETWORK = None


def read(conn, statement, params=()):
    value = one(conn, statement, params)
    conn.rollback()
    return value


def snapshot(conn):
    value = state(conn)
    conn.rollback()
    return value


def row_of(rows, key, value):
    return next(row for row in rows if row[key] == value)


def run_row(owner, run_id):
    return read(owner, "SELECT to_jsonb(r) FROM v24.runs r WHERE run_id=%s", (run_id,))


def effect_row(owner, effect_id):
    return read(owner, "SELECT to_jsonb(e) FROM v24.effects e WHERE effect_id=%s", (effect_id,))


def model_rows(owner, run_id):
    return read(owner, "SELECT coalesce(jsonb_agg(to_jsonb(e) ORDER BY e.created_at,e.effect_id),"
                       "'[]'::jsonb) FROM v24.effects e WHERE e.run_id=%s AND e.kind='model_call'",
                (run_id,))


def start(conn, scope_id, owner_fiber_id, input_value, budget, key):
    """Keep exact database JSON text so replay bytes stay comparable."""
    raw = one(conn, "SELECT v24.start(%s,%s,%s,%s,%s)::text",
              (scope_id, owner_fiber_id, Json(input_value), Json(budget), key))
    return json.loads(raw), raw.encode("utf-8")


def steer(conn, run_id, generation, instruction, key):
    raw = one(conn, "SELECT v24.steer(%s,%s,%s,%s)::text",
              (run_id, generation, instruction, key))
    return json.loads(raw), raw.encode("utf-8")


def respond(conn, run_id, interaction_id, response, generation, key):
    raw = one(conn, "SELECT v24.respond(%s,%s,%s,%s,%s)::text",
              (run_id, interaction_id, Json(response), generation, key))
    return json.loads(raw), raw.encode("utf-8")


def cancel(conn, run_id, generation, key):
    raw = one(conn, "SELECT v24.cancel(%s,%s,%s)::text", (run_id, generation, key))
    return json.loads(raw), raw.encode("utf-8")


def loop_fixture(owner, login, *, realm, requires=()):
    creator, root = uuid4(), uuid4()
    principal = one(login, "SELECT v24.principal_id(session_user)")
    login.commit()
    seed_effect(owner, creator)
    seed_scope(owner, root, creator, default_realm=realm, owner_principal=principal)
    live = provider(owner, root, realm, "owner", creator)
    for key in requires:
        provider(owner, root, realm, key, creator)
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.fibers SET want_on=true WHERE fiber_id=%s", (live["fiber"],))
    owner.commit()
    return root, live, creator


def seed_run(owner, principal, *, status="running", tokens=1234, steps=7,
             interaction=None, events=2):
    """Owner fixture: an owned run plus the first-start effect and run events."""
    run_id, scope_id, command_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    with owner.cursor() as cur:
        insert(cur, "scopes", scope_id=scope_id, root_id=scope_id,
               route_path=[scope_id], owner_principal=principal,
               created_by_effect=command_id)
        insert(cur, "runs", run_id=run_id, scope_id=scope_id, status=status,
               epoch_no=1, registration_generation=1, turn_no=0, driving_generation=1,
               remaining_steps=steps, remaining_tokens=tokens, remaining_tool_calls=3,
               remaining_wall_ms=10000,
               interaction=Json(interaction) if interaction is not None else None,
               revision=1, created_at=now, updated_at=now)
        effect(cur, command_id, kind="command_start", requester_id=principal,
               run_id=run_id, scope_id=scope_id, created_at=now,
               status="succeeded", outcome=Json({"fixture": "command_start"}),
               settled_at=now)
        for seq in range(1, events + 1):
            event_effect = uuid4()
            effect(cur, event_effect)
            insert(cur, "events", effect_id=event_effect, seq=seq,
                   entity_type="run", entity_id=run_id,
                   event_kind=f"seed_{seq}", payload=Json({"seq": seq}),
                   payload_digest=DIGEST)
    owner.commit()
    return run_id


def claim_effect(login, effect_id):
    response = advance(login, effect_id, claim())
    login.commit()
    assert response.get("disposition") == "committed", response
    assert response["claim"] is not None, response
    assert login.get_transaction_status() == TRANSACTION_STATUS_IDLE, response
    return response["claim"]


def settle(login, effect_id, token, class_name, result):
    outcome = {"v": 1, "class": class_name, "claim": token,
               "body": {"kind": "model_call", "result": result}}
    response = advance(login, effect_id, outcome)
    login.commit()
    return response, outcome


def assert_owner_envelope(response):
    assert set(response) == OWNER_KEYS, response
    assert response["v"] == 1 and response["disposition"] == "committed", response
    assert response["claim"] is None, response


def assert_claim_rejected(owner, login, effect_id, label):
    """Exact W0 claim rejection plus a ten-table byte-equal snapshot."""
    before = snapshot(owner)
    response = advance(login, effect_id, claim())
    login.commit()
    assert response == {"v": 1, "error": {"code": "invalid_args", "detail": {}}}, (label, response)
    after = snapshot(owner)
    assert after == before, (label, "claim rejection wrote rows")
    row = row_of(after["effects"], "effect_id", str(effect_id))
    assert row["status"] == "ready" and row["attempt_no"] == 0 and row["fence"] == 0, (label, row)
    assert row["claim_owner"] is None and row["lease_until"] is None, (label, row)


def ledger(owner, run_id):
    run = run_row(owner, run_id)
    spent = read(owner, """SELECT coalesce(sum(CASE
            WHEN e.status IN ('succeeded','failed')
              THEN coalesce((e.outcome->'body'->'result'->'usage'->>'tokens')::bigint,0)
            WHEN e.status = 'unknown'
              THEN coalesce((e.request->'reserve'->>'tokens')::bigint,0)
            ELSE 0 END),0)
        FROM v24.effects e WHERE e.run_id=%s AND e.kind='model_call'""", (run_id,))
    active = read(owner, """SELECT coalesce(sum(
            coalesce((e.request->'reserve'->>'tokens')::bigint,0)),0)
        FROM v24.effects e WHERE e.run_id=%s AND e.kind='model_call'
          AND e.status IN ('ready','claimed')""", (run_id,))
    return spent, active, run["remaining_tokens"]


def assert_ledger(owner, run_id, initial, expected):
    spent, active, remaining = ledger(owner, run_id)
    assert remaining is not None, (run_id, "NULL budget in a numeric ledger")
    print(f"[G2b-L ledger] initial={initial} spent={spent} active={active} "
          f"remaining={remaining} equation={spent}+{active}+{remaining}={initial}")
    assert (spent, active, remaining) == expected, (spent, active, remaining, expected)
    assert initial == spent + active + remaining, (initial, spent, active, remaining)


def assert_ledger_exempt(owner, run_id):
    spent, active, remaining = ledger(owner, run_id)
    print(f"[G2b-L ledger] initial=NULL spent={spent} active={active} "
          f"remaining=NULL equation=exempt (NULL is unlimited)")
    assert remaining is None, (run_id, remaining)


def model_only_spine(db, owner):
    """G2b-A: start -> plain model -> one continuation -> final -> completed."""
    service = db.connect("service")
    root, live, _ = loop_fixture(owner, service, realm="g2b-a")
    budget = {"steps": 7, "tool_calls": 3, "tokens": 5000, "wall_ms": 600000}
    response, _ = start(service, root, live["fiber"], {}, budget, f"g2b-a-{uuid4()}")
    service.commit()
    assert_owner_envelope(response)
    assert len(response["emitted"]) == 2 and len(set(response["emitted"])) == 2, response
    run_id, model_id = response["emitted"]
    run = run_row(owner, run_id)
    model = effect_row(owner, model_id)
    assert run["status"] == "running" and run["turn_no"] == 0, run
    assert run["remaining_steps"] == 6, run
    assert run["remaining_tokens"] == 904, run
    assert model["kind"] == "model_call" and model["status"] == "ready", model
    assert model["ordinal"] == 0 and model["pin_id"] is None, model
    assert model["request"]["cause"] == "start", model
    assert model["request"]["reserve"] == {"tokens": 4096}, model
    assert read(owner, "SELECT count(*) FROM v24.requests WHERE effect_id=%s", (model_id,)) == 0
    print("[G2b-A] start: run running turn_no=0 steps=6 tokens=904; one ready "
          "model reserve=4096 cause=start; no model request row")

    llm = FakeLLM([
        {"cause": "start", "result": {"text": "thinking"}},
        {"cause": "continuation", "result": {"text": "done", "final": {"text": "done"}}},
    ])
    token = claim_effect(service, model_id)
    assert service.get_transaction_status() == TRANSACTION_STATUS_IDLE
    first = llm.complete(model["request"])
    assert first == {"text": "thinking"}, first
    settled, receipt = settle(service, model_id, token, "success", first)
    assert_owner_envelope(settled)
    assert len(settled["emitted"]) == 1, settled
    continuation_id = settled["emitted"][0]
    expected_continuation = read(
        owner, "SELECT md5(%s||':continuation')::uuid::text", (model_id,))
    assert continuation_id == expected_continuation, (continuation_id, expected_continuation)
    models = model_rows(owner, run_id)
    assert len(models) == 2, models
    continuation = row_of(models, "effect_id", continuation_id)
    batch_digest = read(owner, "SELECT encode(sha256(convert_to('','UTF8')),'hex')")
    run = run_row(owner, run_id)
    assert continuation["status"] == "ready" and continuation["ordinal"] == 0, continuation
    assert continuation["parent_effect_id"] == model_id, continuation
    assert continuation["request"]["cause"] == "continuation", continuation
    assert continuation["request"]["state"] == {}, continuation
    assert continuation["request"]["batch_digest"] == batch_digest, continuation
    assert continuation["request"]["reserve"] == {"tokens": 4096}, continuation
    assert continuation["request"]["digests"] == model["request"]["digests"], continuation
    assert continuation["pin_id"] is None, continuation
    assert run["remaining_steps"] == 5 and run["remaining_tokens"] == 904, run
    assert run["turn_no"] == 1, run
    assert_ledger(owner, run_id, 5000, (0, 4096, 904))
    print("[G2b-A] settlement: effect succeeded, exactly one continuation "
          "(parent=model, ordinal=0, state={}, batch_digest=sha256(''), reserve "
          "pre-debited); run steps=5 tokens=904 turn_no=1")

    token2 = claim_effect(service, continuation_id)
    second = llm.complete(continuation["request"])
    assert second == {"text": "done", "final": {"text": "done"}}, second
    settled2, _ = settle(service, continuation_id, token2, "success", second)
    assert_owner_envelope(settled2)
    assert settled2["emitted"] == [], settled2
    run = run_row(owner, run_id)
    assert run["status"] == "completed", run
    assert run["close_intent"] == {"kind": "final"}, run
    assert run["result"]["close_reason"] == "final", run
    assert run["result"]["final_text"] == "done", run
    assert run["turn_no"] == 2, run
    assert run["ended_at"] is not None and run["pending_steer"] is None, run
    assert run["interaction"] is None, run
    assert run["remaining_steps"] == 5 and run["remaining_tokens"] == 5000, run
    assert_ledger(owner, run_id, 5000, (0, 0, 5000))
    assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                       "AND kind IN ('model_call','tool_call') "
                       "AND status IN ('ready','claimed')", (run_id,)) == 0
    assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                       "AND kind='tool_call'", (run_id,)) == 0
    assert read(owner, "SELECT count(*) FROM v24.requests WHERE effect_id IN (%s,%s)",
                (model_id, continuation_id)) == 0
    assert [call["cause"] for call in llm.calls] == ["start", "continuation"], llm.calls
    assert llm.calls[0] == model["request"] and llm.calls[1] == continuation["request"], llm.calls
    print("[G2b-A] final: run completed close_reason=final final_text='done' "
          "turn_no=2 ended_at set; zero ready/claimed, zero tool effects, zero "
          "model request rows; FakeLLM calls start+continuation")


def real_claim_settle(db, owner):
    """G2b-B: exact real claim token and success settlement without a request row."""
    service = db.connect("service")
    root, live, _ = loop_fixture(owner, service, realm="g2b-b")
    budget = {"steps": 7, "tool_calls": 3, "tokens": 5000, "wall_ms": 600000}
    response, _ = start(service, root, live["fiber"], {}, budget, f"g2b-b-{uuid4()}")
    service.commit()
    assert_owner_envelope(response)
    run_id, model_id = response["emitted"]
    token = advance(service, model_id, claim())["claim"]
    service.commit()
    assert service.get_transaction_status() == TRANSACTION_STATUS_IDLE
    assert token == {"attempt": 1, "fence": 1, "owner": db.roles["service"]}, token
    print(f"[G2b-B] claim token byte-exact: {token}")
    requests_before = read(owner, "SELECT count(*) FROM v24.requests")
    receipt = {"text": "done", "final": {"text": "done"}}
    settled, outcome = settle(service, model_id, token, "success", receipt)
    assert_owner_envelope(settled)
    effect = effect_row(owner, model_id)
    run = run_row(owner, run_id)
    assert effect["status"] == "succeeded", effect
    assert effect["outcome"] == outcome, effect
    assert read(owner, "SELECT outcome=%s::jsonb FROM v24.effects WHERE effect_id=%s",
                (Json(outcome), model_id)) is True
    assert effect["resource_quiesced_at"] is not None, effect
    assert effect["claim_owner"] is None and effect["lease_until"] is None, effect
    assert run["turn_no"] == 1 and run["status"] == "completed", run
    assert read(owner, "SELECT count(*) FROM v24.requests") == requests_before
    print("[G2b-B] success settlement: effect succeeded, outcome byte-equal receipt, "
          "resource_quiesced_at set, claim_owner/lease_until NULL, run turn_no=1; "
          "requests row count unchanged")


def stage_guard(db, owner):
    """G2b-C: W1 allowlist is exactly host*+model; exhaustive non-member rejection."""
    service = db.connect("service")
    root, live, creator = loop_fixture(owner, service, realm="g2b-c")
    kinds = read(owner, "SELECT v24.claimable_kinds()")
    assert kinds == ["host_prepare", "host_release", "model_call"], kinds
    assert set(kinds) == {"host_prepare", "host_release", "model_call"}, kinds
    print(f"[G2b-C] claimable_kinds() exactly {kinds}")
    non_members = ("tool_call", "inspect_resource") + COMMAND_KINDS + ("fiber_reconcile",)
    assert len(COMMAND_KINDS) == 8, COMMAND_KINDS
    for kind in non_members:
        effect_id = uuid4()
        extra = {"fiber_id": live["fiber"]} if kind == "fiber_reconcile" else {}
        seed_effect(owner, effect_id, kind=kind, status="ready", **extra)
        owner.commit()
        assert_claim_rejected(owner, service, effect_id, kind)
    print(f"[G2b-C] exhaustive non-members rejected invalid_args with byte-equal "
          f"state: {list(non_members)}")

    install = seed_install(owner, scope_id=root, creator=creator, state="preparing")
    effect_id = uuid4()
    seed_effect(owner, effect_id, kind="host_prepare", status="ready",
                request=Json({"install_id": str(install),
                              "reservation": f"v24:host_prepare:{effect_id}"}))
    owner.commit()
    before = snapshot(owner)
    claimed = advance(service, effect_id, claim())
    service.commit()
    assert claimed == {"v": 1, "disposition": "committed", "effect_id": str(effect_id),
                       "emitted": [], "revision": 0,
                       "claim": {"attempt": 1, "fence": 1, "owner": db.roles["service"]}}, claimed
    after = snapshot(owner)
    for table in EXPECTED_TABLES - {"effects"}:
        assert after[table] == before[table], (table, "host_prepare claim wrote extra rows")
    row = row_of(after["effects"], "effect_id", str(effect_id))
    assert row["status"] == "claimed" and row["attempt_no"] == 1 and row["fence"] == 1, row
    assert row["claim_owner"] == db.roles["service"] and row["lease_until"] is not None, row
    print("[G2b-C] host_prepare install fixture still claims: attempt=1 fence=1 "
          "owner=service; only the effect row changes")


def reserve_conservation(db, owner):
    """G2b-L: reserve pre-debit/refund conservation observed after every step."""
    service = db.connect("service")

    # Case 1: usage refund then continuation admission in the same settlement.
    root, live, _ = loop_fixture(owner, service, realm="g2b-l1")
    budget = {"steps": 7, "tool_calls": 3, "tokens": 5000, "wall_ms": 600000}
    response, _ = start(service, root, live["fiber"], {}, budget, f"g2b-l1-{uuid4()}")
    service.commit()
    assert_owner_envelope(response)
    run_id, model_id = response["emitted"]
    assert_ledger(owner, run_id, 5000, (0, 4096, 904))
    token = claim_effect(service, model_id)
    first = {"text": "step", "usage": {"tokens": 40, "wall_ms": 5}}
    settled, _ = settle(service, model_id, token, "success", first)
    assert len(settled["emitted"]) == 1, settled
    run = run_row(owner, run_id)
    post_refund = 904 + 4096 - 40
    assert post_refund == 4960, post_refund
    assert run["remaining_tokens"] == post_refund - 4096 == 864, run
    assert run["remaining_steps"] == 5, run
    assert_ledger(owner, run_id, 5000, (40, 4096, 864))
    print("[G2b-L case1] usage 40: post-refund balance 4960, continuation "
          "reserve 4096 pre-debited -> persisted remaining=864")
    continuation_id = settled["emitted"][0]
    token2 = claim_effect(service, continuation_id)
    final = {"text": "done", "final": {"text": "done"}, "usage": {"tokens": 0, "wall_ms": 3}}
    settled2, _ = settle(service, continuation_id, token2, "success", final)
    assert settled2["emitted"] == [], settled2
    run = run_row(owner, run_id)
    assert run["remaining_tokens"] == 4960 and run["turn_no"] == 2, run
    assert_ledger(owner, run_id, 5000, (40, 0, 4960))
    print("[G2b-L case1] final usage 0: reserve 4096 refunded -> remaining=4960; "
          "ledger 5000 at every observable step")

    # Case 2: steer archives the ready model and refunds its reserve.
    root, live, _ = loop_fixture(owner, service, realm="g2b-l2")
    response, _ = start(service, root, live["fiber"], {}, budget, f"g2b-l2-{uuid4()}")
    service.commit()
    run_id, model_id = response["emitted"]
    assert_ledger(owner, run_id, 5000, (0, 4096, 904))
    steered, _ = steer(service, run_id, 1, "archive", f"g2b-l2s-{uuid4()}")
    service.commit()
    assert_owner_envelope(steered)
    assert len(steered["emitted"]) == 1, steered
    models = model_rows(owner, run_id)
    assert len(models) == 2, models
    old = row_of(models, "effect_id", model_id)
    new = next(row for row in models if row["effect_id"] != model_id)
    assert old["status"] == "cancelled" and old["outcome"] is None, old
    assert old["settled_at"] is not None, old
    assert new["status"] == "ready" and new["request"]["cause"] == "steer", new
    assert new["request"]["reserve"] == {"tokens": 4096}, new
    assert new["effect_id"] == read(owner, "SELECT md5(%s||':model_call:0')::uuid::text",
                                    (steered["effect_id"],)), new
    run = run_row(owner, run_id)
    assert run["remaining_tokens"] == 904 and run["epoch_no"] == 2, run
    assert_ledger(owner, run_id, 5000, (0, 4096, 904))
    print("[G2b-L case2] steer archived ready model (cancelled/NULL outcome), exactly "
          "one new ready steer model reserve=4096, remaining=904, ledger 5000")

    # Case 3: cancel refunds the ready model reserve.
    root, live, _ = loop_fixture(owner, service, realm="g2b-l3")
    response, _ = start(service, root, live["fiber"], {}, budget, f"g2b-l3-{uuid4()}")
    service.commit()
    run_id, model_id = response["emitted"]
    cancelled, _ = cancel(service, run_id, 1, f"g2b-l3c-{uuid4()}")
    service.commit()
    assert_owner_envelope(cancelled)
    assert cancelled["emitted"] == [], cancelled
    model = effect_row(owner, model_id)
    run = run_row(owner, run_id)
    assert model["status"] == "cancelled" and model["outcome"] is None, model
    assert run["status"] == "cancelled", run
    assert run["remaining_tokens"] == 5000, run
    assert_ledger(owner, run_id, 5000, (0, 0, 5000))
    print("[G2b-L case3] cancel: model cancelled, run cancelled, remaining=5000, "
          "ledger 5000=0+0+5000")

    # Case 4: token-0 steer archives and seals instead of reserving 0.
    root, live, _ = loop_fixture(owner, service, realm="g2b-l4")
    zero_budget = {"steps": 7, "tool_calls": 3, "tokens": 0, "wall_ms": 600000}
    response, _ = start(service, root, live["fiber"], {}, zero_budget, f"g2b-l4-{uuid4()}")
    service.commit()
    run_id, model_id = response["emitted"]
    assert run_row(owner, run_id)["remaining_tokens"] == 0
    assert effect_row(owner, model_id)["request"]["reserve"] == {"tokens": 0}
    assert_ledger(owner, run_id, 0, (0, 0, 0))
    sealed, _ = steer(service, run_id, 1, "zero", f"g2b-l4s-{uuid4()}")
    service.commit()
    assert_owner_envelope(sealed)
    assert sealed["emitted"] == [], sealed
    run = run_row(owner, run_id)
    archived = effect_row(owner, model_id)
    assert run["status"] == "completed", run
    assert run["close_intent"] == {"kind": "budget"}, run
    assert run["result"]["close_reason"] == "budget_exhausted", run
    assert run["pending_steer"] is None and run["interaction"] is None, run
    assert archived["status"] == "cancelled" and archived["outcome"] is None, archived
    assert len(model_rows(owner, run_id)) == 1
    assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                       "AND kind IN ('model_call','tool_call') "
                       "AND status IN ('ready','claimed')", (run_id,)) == 0
    assert_ledger(owner, run_id, 0, (0, 0, 0))
    print("[G2b-L case4] token-0 steer: no reserve-0 successor, archived model "
          "cancelled, run completed budget_exhausted, zero ready/claimed")

    # Case 5: token-0 respond consumes the interaction and seals.
    root, live, _ = loop_fixture(owner, service, realm="g2b-l5")
    principal = read(service, "SELECT v24.principal_id(session_user)")
    interaction_id, origin_id = str(uuid4()), str(uuid4())
    interaction = {"interaction_id": interaction_id,
                   "origin_effect_id": origin_id,
                   "generation": 1,
                   "schema_digest": "\\x" + "11" * 32,
                   "prompt_digest": "\\x" + "22" * 32,
                   "created_at": datetime.now(timezone.utc).isoformat()}
    run_id = seed_run(owner, principal, status="waiting", tokens=0,
                      interaction=interaction)
    # The interaction's origin is the already-settled model, as in the S3 fixture.
    seed_effect(owner, origin_id, kind="model_call", run_id=run_id, generation=1,
                status="cancelled", settled_at=datetime.now(timezone.utc))
    owner.commit()
    sealed, _ = respond(service, run_id, interaction_id, {"answer": "now"}, 1,
                        f"g2b-l5-{uuid4()}")
    service.commit()
    assert_owner_envelope(sealed)
    assert sealed["emitted"] == [], sealed
    run = run_row(owner, run_id)
    assert run["status"] == "completed", run
    assert run["interaction"] is None, run
    assert run["close_intent"] == {"kind": "budget"}, run
    assert run["result"]["close_reason"] == "budget_exhausted", run
    assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                       "AND kind IN ('model_call','tool_call') "
                       "AND status IN ('ready','claimed')", (run_id,)) == 0
    models = model_rows(owner, run_id)
    assert len(models) == 1 and models[0]["effect_id"] == origin_id, models
    assert models[0]["status"] == "cancelled", models
    assert_ledger(owner, run_id, 0, (0, 0, 0))
    print("[G2b-L case5] token-0 respond: interaction consumed, no model successor, "
          "run completed budget_exhausted, interaction NULL, zero ready/claimed")

    # Case 6: NULL budget is unlimited; a steer model with reserve 0 is admitted.
    root, live, _ = loop_fixture(owner, service, realm="g2b-l6")
    null_budget = {"steps": 7, "tool_calls": 3, "wall_ms": 600000}
    response, _ = start(service, root, live["fiber"], {}, null_budget, f"g2b-l6-{uuid4()}")
    service.commit()
    run_id, model_id = response["emitted"]
    run = run_row(owner, run_id)
    assert run["remaining_tokens"] is None, run
    assert effect_row(owner, model_id)["request"]["reserve"] == {"tokens": 0}
    unlimited, _ = steer(service, run_id, 1, "unlimited", f"g2b-l6s-{uuid4()}")
    service.commit()
    assert_owner_envelope(unlimited)
    assert len(unlimited["emitted"]) == 1, unlimited
    new = effect_row(owner, unlimited["emitted"][0])
    assert new["status"] == "ready" and new["request"]["reserve"] == {"tokens": 0}, new
    assert run_row(owner, run_id)["remaining_tokens"] is None
    assert_ledger_exempt(owner, run_id)
    print("[G2b-L case6] NULL budget: start/steer keep remaining_tokens NULL, steer "
          "admits reserve=0 model, ledger exempt")


def unknown_path(db, owner):
    """G2b-T-1/2/3: unknown wall, same-receipt replay, altered receipt conflict."""
    service = db.connect("service")
    root, live, _ = loop_fixture(owner, service, realm="g2b-t")
    budget = {"steps": 7, "tool_calls": 3, "tokens": 5000, "wall_ms": 600000}
    response, _ = start(service, root, live["fiber"], {}, budget, f"g2b-t-{uuid4()}")
    service.commit()
    assert_owner_envelope(response)
    run_id, model_id = response["emitted"]
    token = claim_effect(service, model_id)
    settled, outcome = settle(service, model_id, token, "unknown", {})
    assert_owner_envelope(settled)
    assert settled["emitted"] == [], settled
    effect = effect_row(owner, model_id)
    run = run_row(owner, run_id)
    assert effect["status"] == "unknown", effect
    assert effect["outcome"] == outcome, effect
    assert effect["resource_quiesced_at"] is None, effect
    assert effect["pin_id"] is None, effect
    assert run["status"] == "blocked_unknown", run
    assert run["close_intent"] == {"kind": "unknown", "reason": "outcome_unknown",
                                   "effect_id": model_id}, run
    assert run["result"] == {"v": 1, "close_reason": "unknown", "turn_no": 1}, run
    assert run["pending_steer"] is None and run["interaction"] is None, run
    assert run["turn_no"] == 1, run
    assert run["remaining_tokens"] == 904, run
    assert len(model_rows(owner, run_id)) == 1
    assert read(owner, "SELECT count(*) FROM v24.pins WHERE consumer_run_id=%s",
                (run_id,)) == 0
    assert_ledger(owner, run_id, 5000, (4096, 0, 904))
    print("[G2b-T-1] unknown: effect unknown resource_quiesced_at NULL, run "
          "blocked_unknown close_intent outcome_unknown, no successor, turn_no=1, "
          "reserve 4096 not refunded (remaining=904); model pin_id NULL and no run pin")

    before = snapshot(owner)
    replay = advance(service, model_id, outcome)
    service.commit()
    assert replay["disposition"] == "replay", replay
    assert replay["emitted"] == [] and replay["revision"] == 0, replay
    after = snapshot(owner)
    assert after == before, "unknown replay wrote rows"
    print("[G2b-T-2] same receipt replay: disposition=replay, emitted=[], revision=0, "
          "ten-table byte-equal")

    before = snapshot(owner)
    altered = {"v": 1, "class": "unknown", "claim": token,
               "body": {"kind": "model_call", "result": {"altered": True}}}
    conflict = advance(service, model_id, altered)
    service.commit()
    assert conflict == {"v": 1, "error": {"code": "receipt_conflict", "detail": {}}}, conflict
    after = snapshot(owner)
    assert after == before, "receipt conflict wrote rows"
    print("[G2b-T-3] altered receipt for the same effect: receipt_conflict, "
          "ten-table byte-equal")


def regression_surface(db, owner):
    """G2b-U: S1-S3 surfaces still hold with the W1 loop open."""
    service = db.connect("service")
    root, live, creator = loop_fixture(owner, service, realm="g2b-u", requires=("dep",))
    for code in ERROR_CODES:
        assert read(owner, "SELECT v24.error_v1(%s)->'error'->>'code'", (code,)) == code, code
    assert len(ERROR_CODES) == 23, ERROR_CODES
    sqlstate(owner, "22023", lambda: one(owner, "SELECT v24.error_v1('no_interpreter')"))
    owner.rollback()
    print("[G2b-U] error_v1 still accepts the closed 23-code set; unknown code 22023")

    install = seed_install(owner, scope_id=root, creator=creator, state="preparing")
    effect_id = uuid4()
    seed_effect(owner, effect_id, kind="host_prepare", status="ready",
                request=Json({"install_id": str(install),
                              "reservation": f"v24:host_prepare:{effect_id}"}))
    owner.commit()
    before = snapshot(owner)
    token = claim_effect(service, effect_id)
    settled = advance(service, effect_id,
                      {"v": 1, "class": "success", "claim": token,
                       "body": {"result": "prepared"}})
    service.commit()
    assert settled["disposition"] == "committed", settled
    effect = effect_row(owner, effect_id)
    assert effect["status"] == "succeeded", effect
    assert read(owner, "SELECT state FROM v24.installs WHERE install_id=%s",
                (install,)) == "installed"
    after = snapshot(owner)
    assert after["installs"] != before["installs"], "host_prepare did not settle"
    print("[G2b-U] host_prepare claim->settle still succeeds; install state=installed")

    principal = read(service, "SELECT v24.principal_id(session_user)")
    run_id = seed_run(owner, principal, events=2)
    poll = read(service, "SELECT v24.poll(%s,0)", (run_id,))
    assert set(poll) == POLL_KEYS, poll
    assert set(poll["run"]) == PROJECTION_KEYS, poll["run"]
    assert all(set(event) == EVENT_KEYS for event in poll["events"]), poll["events"]
    wait = read(service, "SELECT v24.wait_check(%s,1,1,0)", (run_id,))
    assert set(wait) == WAIT_KEYS, wait
    assert set(wait["run"]) == PROJECTION_KEYS, wait["run"]
    assert set(wait["wake"]) == WAKE_KEYS, wait["wake"]
    assert all(set(event) == EVENT_KEYS for event in wait["events"]), wait["events"]
    print(f"[G2b-U] poll/wait_check top-level key sets unchanged: {sorted(POLL_KEYS)} "
          f"and {sorted(WAIT_KEYS)}; run projection has the S3 {len(PROJECTION_KEYS)} keys")

    before = snapshot(owner)
    resolved = read(service, "SELECT count(*) FROM v24.resolve(%s,ARRAY['owner','dep'])",
                    (root,))
    assert resolved == 2, resolved
    after = snapshot(owner)
    assert after == before, "resolve wrote domain rows"
    print("[G2b-U] resolve is read-only: two live rows, ten-table byte-equal")

    replay_run = seed_run(owner, principal, events=1)
    key = f"g2b-u-replay-{uuid4()}"
    first, raw_first = steer(service, replay_run, 1, "replay me", key)
    service.commit()
    assert_owner_envelope(first)
    before = snapshot(owner)
    second, raw_second = steer(service, replay_run, 1, "replay me", key)
    service.commit()
    assert second == first and raw_second == raw_first, (first, second)
    after = snapshot(owner)
    assert after == before, "steer same-key replay wrote rows"
    print("[G2b-U] steer same-key replay keeps the S3 envelope and byte-equal response; "
          "ten-table byte-equal")

    scripted = FakeLLM([{"cause": "start", "result": {"text": "one"}}])
    assert scripted.complete({"cause": "start", "state": {}}) == {"text": "one"}
    try:
        scripted.complete({"cause": "start", "state": {}})
    except RuntimeError:
        pass
    else:
        raise AssertionError("FakeLLM did not fail on script exhaustion")
    try:
        FakeLLM([{"cause": "start", "result": {}}]).complete(
            {"cause": "continuation", "state": {}})
    except RuntimeError:
        pass
    else:
        raise AssertionError("FakeLLM answered a mismatched cause")
    assert len(scripted.calls) == 2, scripted.calls
    print("[G2b-U] FakeLLM contract: cause/state.step selection, calls recorded, "
          "exhaustion and mismatched cause raise RuntimeError")

    tool = FakeTool({"search": {"status": "ok", "output": {"hits": []}}})
    assert tool.invoke({"tool": {"key": "search"}}) == {"status": "ok",
                                                        "output": {"hits": []}}
    try:
        tool.invoke({"tool": {"key": "missing"}})
    except RuntimeError:
        pass
    else:
        raise AssertionError("FakeTool accepted an unregistered key")
    assert [call["tool"]["key"] for call in tool.calls] == ["search", "missing"], tool.calls
    print("[G2b-U] FakeTool W2 readiness: registered key returns its result, "
          "unregistered key raises, calls recorded")

    assert socket.socket.connect is deny_network, socket.socket.connect
    assert socket.create_connection is deny_network, socket.create_connection
    import fake_llm
    source = inspect.getsource(fake_llm)
    for banned in ("socket", "http", "urllib", "requests"):
        assert re.search(rf"^\s*(?:import|from)\s+{banned}\b", source, re.MULTILINE) is None, banned
    print("[G2b-U] network guard active (socket.connect/create_connection denied); "
          "fake_llm source has no socket/http/urllib/requests import")


def structural_retry_and_semantic(db, owner):
    """G2b-V: structural W0 retry does not consume budget, semantic stays unknown."""
    service = db.connect("service")

    # V-1/V-2: two invalid shapes, byte-equal state, then the same token succeeds.
    root, live, _ = loop_fixture(owner, service, realm="g2b-v1")
    budget = {"steps": 7, "tool_calls": 3, "tokens": 5000, "wall_ms": 600000}
    response, _ = start(service, root, live["fiber"], {}, budget, f"g2b-v1-{uuid4()}")
    service.commit()
    assert_owner_envelope(response)
    run_id, model_id = response["emitted"]
    token = claim_effect(service, model_id)
    before = snapshot(owner)
    before_effect = row_of(before["effects"], "effect_id", model_id)
    before_run = row_of(before["runs"], "run_id", run_id)
    bad = {"v": 1, "class": "success", "claim": token,
           "body": {"result": {"text": "missing kind"}}}
    for attempt in range(2):
        refused = advance(service, model_id, bad)
        service.commit()
        assert refused == {"v": 1, "error": {"code": "invalid_outcome", "detail": {}}}, refused
        after = snapshot(owner)
        assert after == before, (attempt, "structural W0 wrote rows")
        row = row_of(after["effects"], "effect_id", model_id)
        run = row_of(after["runs"], "run_id", run_id)
        assert (row["attempt_no"], row["fence"], row["lease_until"]) == (
            before_effect["attempt_no"], before_effect["fence"],
            before_effect["lease_until"]), (attempt, row)
        assert (run["remaining_steps"], run["remaining_tokens"],
                run["remaining_tool_calls"], run["remaining_wall_ms"],
                run["turn_no"]) == (
            before_run["remaining_steps"], before_run["remaining_tokens"],
            before_run["remaining_tool_calls"], before_run["remaining_wall_ms"],
            before_run["turn_no"]), (attempt, run)
    print("[G2b-V-1] two invalid structural receipts: both invalid_outcome, "
          "ten-table byte-equal, attempt/fence/lease_until/remaining_*/turn_no unchanged")

    good = {"text": "good", "final": {"text": "good"}}
    settled, _ = settle(service, model_id, token, "success", good)
    assert_owner_envelope(settled)
    effect = effect_row(owner, model_id)
    run = run_row(owner, run_id)
    assert effect["status"] == "succeeded", effect
    assert run["status"] == "completed" and run["turn_no"] == 1, run
    assert run["remaining_steps"] == 6 and run["remaining_tokens"] == 5000, run
    print("[G2b-V-2] same token after W0: normal success, turn_no=1, steps=6, "
          "tokens=5000 (retry consumed neither budget nor turn)")

    # V-3/V-4: semantic violation settles unknown, preserving its pin and receipt.
    root, live, creator = loop_fixture(owner, service, realm="g2b-v3", requires=("pinned",))
    response, _ = start(service, root, live["fiber"], {"requires": [{"key": "pinned"}]},
                        budget, f"g2b-v3-{uuid4()}")
    service.commit()
    assert_owner_envelope(response)
    run_id, model_id = response["emitted"]
    pin = read(owner, "SELECT to_jsonb(p) FROM v24.pins p WHERE consumer_run_id=%s",
               (run_id,))
    assert pin["released_at"] is None, pin
    token = claim_effect(service, model_id)
    # C22 fixture: an unquiesced unknown tool keeps its pin referenced so the
    # semantic settlement's release predicate must preserve it.
    holder_id = uuid4()
    seed_effect(owner, holder_id, kind="tool_call", run_id=run_id,
                pin_id=pin["pin_id"], generation=1, status="unknown",
                outcome=Json({"fixture": "pin holder"}),
                settled_at=datetime.now(timezone.utc), resource_quiesced_at=None)
    owner.commit()
    receipt = {"tool_calls": [{"key": "not-pinned", "args": {}}]}
    settled, outcome = settle(service, model_id, token, "success", receipt)
    assert_owner_envelope(settled)
    assert settled["emitted"] == [], settled
    effect = effect_row(owner, model_id)
    run = run_row(owner, run_id)
    pin = read(owner, "SELECT to_jsonb(p) FROM v24.pins p WHERE pin_id=%s",
               (pin["pin_id"],))
    assert effect["status"] == "unknown", effect
    assert effect["outcome"] == outcome and effect["outcome"]["class"] == "success", effect
    assert effect["resource_quiesced_at"] is None, effect
    assert run["status"] == "blocked_unknown", run
    assert run["close_intent"]["kind"] == "unknown", run
    assert run["close_intent"]["reason"] == "semantic_violation", run
    assert run["turn_no"] == 1, run
    assert run["pending_steer"] is None and run["interaction"] is None, run
    assert pin["released_at"] is None, pin
    event = read(owner, """SELECT payload FROM v24.events
        WHERE entity_id=%s AND event_kind='model_call_unknown'""", (run_id,))
    assert event["reason"] == "semantic_violation", event
    assert event["effect_id"] == model_id, event
    assert len(model_rows(owner, run_id)) == 1
    print("[G2b-V-3] tool key outside live pins is semantic, not invalid_outcome: "
          "effect unknown with class='success' receipt preserved, run blocked_unknown "
          "semantic_violation, pin preserved, 0 successor, event recorded")

    before = snapshot(owner)
    replay = advance(service, model_id, outcome)
    service.commit()
    assert replay["disposition"] == "replay", replay
    after = snapshot(owner)
    assert after == before, "semantic replay wrote rows"
    before = snapshot(owner)
    altered = {"v": 1, "class": "success", "claim": token,
               "body": {"kind": "model_call",
                        "result": {"tool_calls": [{"key": "not-pinned",
                                                   "args": {"changed": True}}]}}}
    conflict = advance(service, model_id, altered)
    service.commit()
    assert conflict == {"v": 1, "error": {"code": "receipt_conflict", "detail": {}}}, conflict
    after = snapshot(owner)
    assert after == before, "semantic receipt conflict wrote rows"
    print("[G2b-V-4] semantic settlement: same digest -> replay, different digest -> "
          "receipt_conflict; both ten-table byte-equal")


def main():
    install_no_network()
    try:
        with server_helper_scope(), setup_db() as db:
            owner = db.connect()
            with owner.cursor() as cur:
                cur.execute("SET ROLE v24_owner")
            owner.commit()
            model_only_spine(db, owner)
            real_claim_settle(db, owner)
            stage_guard(db, owner)
            reserve_conservation(db, owner)
            unknown_path(db, owner)
            regression_surface(db, owner)
            structural_retry_and_semantic(db, owner)
            _assert_closed_catalog(owner)
    finally:
        restore_no_network()
    print("[passed] v24 S4 W1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
