"""G2b W1-W4 subset: loop spine (model/tool), claim/settle, batch barrier, reserve,
interaction production, the real respond chain, budget/seal and cancel x T2.

The gate drives the real protocol through LOGIN roles and only simulates the
external model call in process.  A claim is always COMMITted and the worker
connection is IDLE before FakeLLM.complete runs; settlement is a later advance.
G2b-E/F additionally race two real service connections from two threads; the
G advisory lock is observed with pg_blocking_pids() and pg_locks, never sleeps.
No sockets, files, randomness, or sleeps are used.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import inspect
import json
import queue
import re
import socket
import sys
import threading
import time
from pathlib import Path
from uuid import UUID, uuid4

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
    print("[G2b-A/w1] start: run running turn_no=0 steps=6 tokens=904; one ready "
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
    print("[G2b-A/w1] settlement: effect succeeded, exactly one continuation "
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
    print("[G2b-A/w1] final: run completed close_reason=final final_text='done' "
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
    """G2b-C: W2 allowlist is exactly host*+model+tool+inspect; non-members reject."""
    service = db.connect("service")
    root, live, creator = loop_fixture(owner, service, realm="g2b-c")
    kinds = read(owner, "SELECT v24.claimable_kinds()")
    assert kinds == ["host_prepare", "host_release", "model_call", "tool_call",
                     "inspect_resource"], kinds
    assert set(kinds) == {"host_prepare", "host_release", "model_call", "tool_call",
                          "inspect_resource"}, kinds
    print(f"[G2b-C] claimable_kinds() exactly {kinds}")
    non_members = COMMAND_KINDS + ("fiber_reconcile",)
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
    """G2b-V: unknown wall, same-receipt replay, altered receipt conflict."""
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
    print("[G2b-V/unknown-wall] unknown: effect unknown resource_quiesced_at NULL, run "
          "blocked_unknown close_intent outcome_unknown, no successor, turn_no=1, "
          "reserve 4096 not refunded (remaining=904); model pin_id NULL and no run pin")

    before = snapshot(owner)
    replay = advance(service, model_id, outcome)
    service.commit()
    assert replay["disposition"] == "replay", replay
    assert replay["emitted"] == [] and replay["revision"] == 0, replay
    after = snapshot(owner)
    assert after == before, "unknown replay wrote rows"
    print("[G2b-V/replay] same receipt replay: disposition=replay, emitted=[], revision=0, "
          "ten-table byte-equal")

    before = snapshot(owner)
    altered = {"v": 1, "class": "unknown", "claim": token,
               "body": {"kind": "model_call", "result": {"altered": True}}}
    conflict = advance(service, model_id, altered)
    service.commit()
    assert conflict == {"v": 1, "error": {"code": "receipt_conflict", "detail": {}}}, conflict
    after = snapshot(owner)
    assert after == before, "receipt conflict wrote rows"
    print("[G2b-V/receipt-conflict] altered receipt for the same effect: receipt_conflict, "
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


# ---------------------------------------------------------------------------
# S4 W2: tool settlement, the C20 batch barrier, and the tool_calls budget.

def md5_uuid(text):
    return str(UUID(hashlib.md5(text.encode()).hexdigest()))


def hexbyte(value):
    return value[2:] if value.startswith("\\x") else value


def settle_tool(login, effect_id, token, class_name, result):
    outcome = {"v": 1, "class": class_name, "claim": token,
               "body": {"kind": "tool_call", "result": result}}
    response = advance(login, effect_id, outcome)
    login.commit()
    return response, outcome


def tool_rows(owner, run_id):
    return read(owner, """SELECT coalesce(jsonb_agg(to_jsonb(e) ORDER BY e.ordinal),'[]'::jsonb)
        FROM v24.effects e WHERE e.run_id=%s AND e.kind='tool_call'""", (run_id,))


def run_pins(owner, run_id):
    return read(owner, """SELECT coalesce(jsonb_agg(to_jsonb(p) ORDER BY p.key),'[]'::jsonb)
        FROM v24.pins p WHERE p.consumer_run_id=%s""", (run_id,))


def batch_digest(ids):
    return hashlib.sha256(",".join(ids).encode()).hexdigest()


def db_batch_digest(owner, model_id):
    return read(owner, """SELECT encode(sha256(convert_to(
            coalesce(string_agg(t.effect_id::text, ',' ORDER BY t.ordinal),''),'UTF8')),'hex')
        FROM v24.effects t WHERE t.parent_effect_id=%s AND t.kind='tool_call'""", (model_id,))


def make_tool_calls(keys):
    return [{"key": key, "args": {"n": index}} for index, key in enumerate(keys)]


def start_tool_run(owner, service, realm, keys, budget):
    root, live, _ = loop_fixture(owner, service, realm=realm, requires=tuple(keys))
    request = {"requires": [{"key": key} for key in keys]}
    response, _ = start(service, root, live["fiber"], request, budget, f"{realm}-{uuid4()}")
    service.commit()
    assert_owner_envelope(response)
    return response["emitted"][0], response["emitted"][1]


def settle_tool_batch(owner, service, run_id, model_id, keys, text="go"):
    pins = {pin["key"]: pin for pin in run_pins(owner, run_id)}
    token = claim_effect(service, model_id)
    response, _ = settle(service, model_id, token, "success",
                         {"text": text, "tool_calls": make_tool_calls(keys)})
    assert_owner_envelope(response)
    ids = [md5_uuid(f"{model_id}:tool_call:{index}") for index in range(len(keys))]
    assert response["emitted"] == ids, response
    return ids, batch_digest(ids), pins


def tool_batch_spine(db, owner):
    """G2b-A (full): model tool batch -> three claim/settle -> one continuation -> final."""
    service = db.connect("service")
    keys = ("alpha", "beta", "gamma")
    budget = {"steps": 7, "tool_calls": 3, "tokens": 5000, "wall_ms": 600000}
    run_id, model_id = start_tool_run(owner, service, "g2b-a-full", keys, budget)
    ids, digest, pins = settle_tool_batch(owner, service, run_id, model_id, keys)

    tools = tool_rows(owner, run_id)
    assert [tool["ordinal"] for tool in tools] == [0, 1, 2], tools
    assert [tool["effect_id"] for tool in tools] == ids, tools
    assert db_batch_digest(owner, model_id) == digest
    for index, tool in enumerate(tools):
        key = keys[index]
        assert tool["status"] == "ready" and tool["kind"] == "tool_call", tool
        assert tool["parent_effect_id"] == model_id, tool
        assert tool["pin_id"] == pins[key]["pin_id"], tool
        request = tool["request"]
        assert request["ordinal"] == index and request["key"] == key, request
        assert request["batch_digest"] == digest, request
        assert request["descriptor_digest"] == hexbyte(pins[key]["descriptor_digest"]), request
    run = run_row(owner, run_id)
    assert run["status"] == "running" and run["turn_no"] == 1, run
    assert run["remaining_steps"] == 6 and run["remaining_tool_calls"] == 0, run
    assert run["remaining_tokens"] == 5000, run
    assert read(owner, "SELECT count(*) FROM v24.events WHERE entity_id=%s "
                       "AND event_kind='tool_batch_admitted'", (run_id,)) == 1
    print("[G2b-A] model batch: 3 ready tools ordinal 0..2, deterministic ids, "
          "pin-bound by key, one recomputed batch_digest; run turn=1 steps=6 "
          "tokens=5000 tool_calls=0; tool_batch_admitted once")

    continuation = None
    for index, tool_id in enumerate(ids):
        token = claim_effect(service, tool_id)
        response, _ = settle_tool(service, tool_id, token, "success",
                                  {"status": "ok", "output": {"i": index},
                                   "usage": {"wall_ms": 5}})
        assert_owner_envelope(response)
        if index < 2:
            assert response["emitted"] == [], response
        else:
            assert len(response["emitted"]) == 1, response
            continuation = response["emitted"][0]
        run = run_row(owner, run_id)
        assert run["turn_no"] == index + 2, run
        assert run["remaining_tool_calls"] == 0, run
    assert continuation == md5_uuid(f"{model_id}:continuation"), continuation
    cont = effect_row(owner, continuation)
    assert cont["parent_effect_id"] == ids[2], cont
    assert cont["ordinal"] == 0 and cont["kind"] == "model_call", cont
    assert cont["request"]["cause"] == "continuation", cont
    assert cont["request"]["batch_digest"] == digest, cont
    assert cont["request"]["state"] == {}, cont
    run = run_row(owner, run_id)
    assert run["turn_no"] == 4, run
    assert run["remaining_steps"] == 5 and run["remaining_tokens"] == 904, run
    assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                       "AND kind='model_call'", (run_id,)) == 2
    print("[G2b-A] tool settlements: first two 0 successors; closing settlement "
          "(ordinal 2) creates exactly one continuation parent=max-ordinal tool, "
          "ordinal=0, same batch_digest; steps=5 tokens=904; two model effects total")

    token = claim_effect(service, continuation)
    settled, _ = settle(service, continuation, token, "success",
                        {"text": "done", "final": {"text": "done"}})
    assert_owner_envelope(settled)
    assert settled["emitted"] == []
    run = run_row(owner, run_id)
    assert run["status"] == "completed" and run["close_intent"] == {"kind": "final"}, run
    assert run["result"]["close_reason"] == "final", run
    assert run["result"]["final_text"] == "done", run
    assert run["turn_no"] == 5 and run["remaining_steps"] == 5, run
    assert run["remaining_tokens"] == 5000, run
    assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                       "AND kind IN ('model_call','tool_call') "
                       "AND status IN ('ready','claimed')", (run_id,)) == 0
    print("[G2b-A] final: completed/close_reason=final, turn=5, tokens refunded "
          "to 5000, zero ready/claimed business effects")


def tool_settlement_counters(db, owner):
    """G2b-D: real tool claim->settle success and failure; receipt, pin, counters."""
    service = db.connect("service")
    keys = ("d0", "d1")
    budget = {"steps": 7, "tool_calls": 2, "tokens": 5000, "wall_ms": 600000}
    run_id, model_id = start_tool_run(owner, service, "g2b-d", keys, budget)
    ids, _, pins = settle_tool_batch(owner, service, run_id, model_id, keys)
    base = run_row(owner, run_id)
    assert base["turn_no"] == 1 and base["remaining_tool_calls"] == 0, base

    token = claim_effect(service, ids[0])
    response, receipt = settle_tool(service, ids[0], token, "success",
                                    {"status": "ok", "output": {"v": 1},
                                     "usage": {"wall_ms": 11}})
    assert_owner_envelope(response)
    assert response["emitted"] == [], response
    tool = effect_row(owner, ids[0])
    run = run_row(owner, run_id)
    assert tool["status"] == "succeeded" and tool["outcome"] == receipt, tool
    assert tool["outcome"]["class"] == "success", tool
    assert tool["resource_quiesced_at"] is not None and tool["settled_at"] is not None, tool
    assert tool["claim_owner"] is None and tool["lease_until"] is None, tool
    assert tool["pin_id"] == pins[keys[0]]["pin_id"], tool
    assert run["turn_no"] == base["turn_no"] + 1, run
    assert run["remaining_tool_calls"] == base["remaining_tool_calls"], run
    assert run["remaining_tokens"] == base["remaining_tokens"] == 5000, run
    assert run["remaining_wall_ms"] <= base["remaining_wall_ms"], run
    assert read(owner, "SELECT count(*) FROM v24.events WHERE entity_id=%s "
                       "AND event_kind='tool_call_settled'", (run_id,)) == 1
    print("[G2b-D] tool success: effect succeeded with byte-equal receipt, exact "
          "pin_id, quiesced/settled, claim columns cleared; run turn+1, tool_calls "
          "and tokens unchanged, wall debited")

    token = claim_effect(service, ids[1])
    before_fail = run_row(owner, run_id)
    response, receipt = settle_tool(service, ids[1], token, "failure",
                                    {"status": "error", "output": {"why": "boom"},
                                     "usage": None})
    assert_owner_envelope(response)
    assert len(response["emitted"]) == 1, response
    tool = effect_row(owner, ids[1])
    run = run_row(owner, run_id)
    assert tool["status"] == "failed" and tool["outcome"] == receipt, tool
    assert tool["outcome"]["class"] == "failure", tool
    assert tool["resource_quiesced_at"] is not None, tool
    assert run["status"] == "running", run
    assert run["turn_no"] == before_fail["turn_no"] + 1, run
    assert run["remaining_steps"] == before_fail["remaining_steps"] - 1, run
    cont = effect_row(owner, response["emitted"][0])
    assert cont["parent_effect_id"] == ids[1], cont
    assert read(owner, "SELECT count(*) FROM v24.events WHERE entity_id=%s "
                       "AND event_kind='tool_call_failed'", (run_id,)) == 1
    assert read(owner, "SELECT count(*) FROM v24.events WHERE entity_id=%s "
                       "AND event_kind='tool_batch_completed'", (run_id,)) == 1
    print("[G2b-D] tool failure: effect failed with receipt, run still running "
          "(single tool failure does not fail the run), turn+1, closing settlement "
          "creates one continuation, tool_call_failed + tool_batch_completed once")


def concurrent_actions(participants, tag, timeout=10):
    """Start one committing action per thread at a shared barrier.

    ``participants`` is ``[(label, connection, action)]``.  Every action owns its
    connection for the whole thread lifetime and is responsible for committing.
    """
    barrier = threading.Barrier(len(participants))
    results, failures, threads = {}, {}, {}

    def run(label, conn, action):
        try:
            barrier.wait(timeout=timeout)
            results[label] = action(conn)
        except BaseException as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            failures[label] = exc

    for label, conn, action in participants:
        thread = threading.Thread(target=run, args=(label, conn, action),
                                  name=f"{tag}-{label}", daemon=True)
        threads[label] = thread
        thread.start()
    try:
        for thread in threads.values():
            thread.join(timeout=timeout)
        assert all(not thread.is_alive() for thread in threads.values()), \
            f"{tag}: action thread did not finish"
        if failures:
            raise next(iter(failures.values()))
        assert set(results) == set(threads), (tag, results)
        return results
    finally:
        for thread in threads.values():
            thread.join(timeout=5)
        for _, conn, _ in participants:
            try:
                conn.rollback()
            except Exception:
                pass


def serialized_race(db, participants, tag, deadline_seconds=10):
    """Race one non-committing ``advance`` per thread; the first holds G open.

    The first action to return keeps its transaction open while the other thread
    waits on ``pg_advisory_xact_lock(24,1)``.  An independent autocommit observer
    proves the wait with ``pg_blocking_pids()`` and an ungranted advisory
    ``pg_locks`` row, then the holder is released and both transactions commit.
    Returns ``(winner_label, winner_response, results, evidence)``.
    """
    assert len(participants) == 2, participants
    observer = db.connect()
    observer.autocommit = True
    barrier = threading.Barrier(len(participants))
    release = threading.Event()
    returned = queue.Queue()
    results, failures, threads = {}, {}, {}
    pids = {label: conn.get_backend_pid() for label, conn, _ in participants}

    def run(label, conn, action):
        try:
            barrier.wait(timeout=10)
            response = action(conn)
            returned.put((label, response))
            if not release.wait(timeout=20):
                raise AssertionError(f"{tag}: {label} was never released")
            conn.commit()
            results[label] = response
        except BaseException as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            failures[label] = exc

    for label, conn, action in participants:
        thread = threading.Thread(target=run, args=(label, conn, action),
                                  name=f"{tag}-{label}", daemon=True)
        threads[label] = thread
        thread.start()

    try:
        try:
            winner_label, winner_response = returned.get(timeout=10)
        except queue.Empty:
            raise AssertionError(f"{tag}: no thread returned from advance") from None
        loser_label = next(label for label, _, _ in participants if label != winner_label)
        winner_pid, loser_pid = pids[winner_label], pids[loser_label]
        deadline = time.monotonic() + deadline_seconds
        while True:
            with observer.cursor() as cur:
                cur.execute(
                    """SELECT pg_blocking_pids(%s)::text,
                              %s = ANY(pg_blocking_pids(%s)),
                              (SELECT count(*) FROM pg_locks
                                WHERE pid=%s AND locktype='advisory' AND NOT granted)""",
                    (loser_pid, winner_pid, loser_pid, loser_pid))
                blockers, blocks_on_winner, ungranted = cur.fetchone()
            if blocks_on_winner and ungranted >= 1:
                break
            assert threads[loser_label].is_alive(), (
                f"{tag}: {loser_label} finished before blocking on {winner_label}")
            assert time.monotonic() < deadline, (
                f"{tag}: {loser_label} did not block on {winner_label} "
                f"(blockers={blockers}, ungranted_advisory={ungranted})")
        winner_state = one(observer, "SELECT state FROM pg_stat_activity WHERE pid=%s",
                           (winner_pid,))
        assert winner_state == "idle in transaction", (tag, winner_state)
        print(f"[{tag}] G lock held open by {winner_label} pid={winner_pid} "
              f"(pg_stat_activity.state='idle in transaction'); {loser_label} pid={loser_pid} "
              f"blocked: pg_blocking_pids({loser_pid})={blockers}, "
              f"pg_locks(pid={loser_pid}, locktype='advisory', granted=false)={ungranted}")
        evidence = {"winner": winner_label, "loser": loser_label,
                    "winner_pid": winner_pid, "blocked_pid": loser_pid,
                    "blockers": blockers, "ungranted_advisory": ungranted}
        release.set()
        for thread in threads.values():
            thread.join(timeout=10)
            assert not thread.is_alive(), f"{tag}: thread still running after G release"
        if failures:
            raise next(iter(failures.values()))
        assert set(results) == set(threads), (tag, results)
        return winner_label, winner_response, results, evidence
    finally:
        release.set()
        for thread in threads.values():
            thread.join(timeout=10)
        for _, conn, _ in participants:
            try:
                conn.rollback()
            except Exception:
                pass
        observer.close()


def tool_batch_claims_and_guards(db, owner):
    """G2b-E/G2b-G: two-connection same-tool claim race, closure, model guards."""
    service = db.connect("service")
    # Every trial races a fresh, symmetric pair.  Odd trials map a/b to the
    # first/second-created connection and even trials swap that mapping; each
    # trial also swaps the thread start order.  Both threads always meet the
    # same Barrier.  Real races are sampled (at least four, at most eight) until
    # both G-acquisition orders are observed, without sleeps or event hand-offs.
    pairs = []
    keys = ("e0", "e1")
    budget = {"steps": 7, "tool_calls": 2, "tokens": 5000, "wall_ms": 600000}
    winners, last = [], None
    try:
        trial = 0
        while trial < 8 and (trial < 4 or len(set(winners)) < 2):
            trial += 1
            pair = (db.connect("service"), db.connect("service"))
            pairs.append(pair)
            first, second = pair
            conns = ({"a": first, "b": second} if trial % 2
                     else {"a": second, "b": first})
            order = ("a", "b") if trial % 2 else ("b", "a")
            run_id, model_id = start_tool_run(owner, service, f"g2b-e-{trial}", keys, budget)
            ids, digest, _ = settle_tool_batch(owner, service, run_id, model_id, keys)
            participants = [
                (label, conns[label],
                 lambda conn, tool_id=ids[0]: advance(conn, tool_id, claim()))
                for label in order
            ]
            winner_label, winner_response, results, evidence = serialized_race(
                db, participants, "G2b-E")
            loser_label = evidence["loser"]
            loser_response = results[loser_label]

            assert winner_response["disposition"] == "committed", winner_response
            assert winner_response["claim"] is not None, winner_response
            assert loser_response.get("disposition") == "deferred", loser_response
            assert loser_response["claim"] is None, loser_response
            assert loser_response["effect_id"] == ids[0], loser_response
            assert loser_response["emitted"] == [], loser_response
            tokens = [response["claim"] for response in results.values()
                      if response.get("claim") is not None]
            assert len(tokens) == 1, results
            token = tokens[0]
            assert token["attempt"] == 1 and token["fence"] == 1, token
            assert token["owner"] == db.roles["service"], token
            tool = effect_row(owner, ids[0])
            assert tool["status"] == "claimed" and tool["attempt_no"] == 1, tool
            assert tool["fence"] == 1 and tool["lease_until"] is not None, tool
            assert tool["claim_owner"] == db.roles["service"], tool
            assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                               "AND kind='tool_call' AND claim_owner IS NOT NULL",
                        (run_id,)) == 1
            assert read(owner, "SELECT count(DISTINCT claim_owner) FROM v24.effects "
                               "WHERE run_id=%s AND kind='tool_call' AND claim_owner IS NOT NULL",
                        (run_id,)) == 1
            sibling = effect_row(owner, ids[1])
            assert sibling["status"] == "ready" and sibling["claim_owner"] is None, sibling
            assert service.get_transaction_status() == TRANSACTION_STATUS_IDLE
            assert conns["a"].get_transaction_status() == TRANSACTION_STATUS_IDLE
            assert conns["b"].get_transaction_status() == TRANSACTION_STATUS_IDLE
            winners.append(winner_label)
            print(f"[G2b-E] trial {trial}: Barrier(2) same-tool claim race (thread start "
                  f"order={order}); winner={winner_label} token attempt=1/fence=1, "
                  f"{loser_label} deferred with claim NULL; effect attempt_no=1 fence=1, "
                  f"exactly one claim_owner={db.roles['service']}")
            last = (run_id, model_id, ids, digest)

            winner_conn = conns[winner_label]
            response, _ = settle_tool(winner_conn, ids[0], token, "success",
                                      {"status": "ok", "output": {}, "usage": None})
            assert_owner_envelope(response)
            assert response["emitted"] == [], response
            tool = effect_row(owner, ids[0])
            assert tool["status"] == "succeeded", tool
            assert tool["attempt_no"] == 1 and tool["fence"] == 1, tool
            assert tool["claim_owner"] is None and tool["lease_until"] is None, tool
            run = run_row(owner, run_id)
            assert run["status"] == "running" and run["turn_no"] == 2, run

            before = snapshot(owner)
            fresh = advance(winner_conn, ids[0], claim())
            winner_conn.commit()
            assert fresh == {"v": 1, "error": {"code": "invalid_args", "detail": {}}}, fresh
            assert snapshot(owner) == before, "post-settlement same-tool claim wrote rows"

            sibling_token = claim_effect(service, ids[1])
            assert sibling_token["attempt"] == 1 and sibling_token["fence"] == 1, sibling_token
            closing, _ = settle_tool(service, ids[1], sibling_token, "success",
                                     {"status": "ok", "output": {}, "usage": None})
            assert_owner_envelope(closing)
            assert len(closing["emitted"]) == 1, closing
            continuation = closing["emitted"][0]
            assert continuation == md5_uuid(f"{model_id}:continuation"), continuation
            cont = effect_row(owner, continuation)
            assert cont["parent_effect_id"] == ids[1], cont
            assert cont["ordinal"] == 0 and cont["kind"] == "model_call", cont
            assert cont["request"]["cause"] == "continuation", cont
            assert cont["request"]["batch_digest"] == digest, cont
            assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                               "AND effect_id=%s", (run_id, continuation)) == 1
            models = read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                                 "AND kind='model_call'", (run_id,))
            assert models == 2, models
            print(f"[G2b-E] trial {trial}: winner settlement with live sibling -> 0 "
                  f"successors; fresh same-tool claim -> invalid_args W0; closing "
                  f"settlement -> exactly one continuation (parent=max-ordinal tool, "
                  f"ordinal=0, batch_digest equal)")

        observed = sorted(set(winners))
        print(f"[G2b-E] {len(winners)} fresh fixtures: same-tool claim race is "
              f"order-independent; winners={winners}, G-acquisition orders "
              f"observed={observed}")
        run_id, model_id, ids, digest = last
    finally:
        for pair in pairs:
            for conn in pair:
                conn.close()

    # A second ready model cannot exist by construction: u_effects_model_call
    # admits at most one ready|claimed model per run.  The observable guarantee
    # is the 23505 net; the applier's clean precheck stays defensive.
    sqlstate(owner, "23505", lambda: seed_effect(owner, uuid4(), kind="model_call",
                                                 status="ready", run_id=run_id),
             message="u_effects_model_call")
    print("[G2b-G] a second ready model is impossible by construction; direct "
          "INSERT hits 23505 (u_effects_model_call is the last-resort net)")

    # C20 step 2: an extra claimed tool under the same model observes the batch
    # already closed -> invalid_outcome W0.
    extra = uuid4()
    pin = run_pins(owner, run_id)[0]
    seed_effect(owner, extra, kind="tool_call", status="claimed", run_id=run_id,
                parent_effect_id=model_id, ordinal=3, pin_id=pin["pin_id"],
                epoch_no=1, generation=1, attempt_no=1, fence=1,
                claim_owner=db.roles["service"],
                lease_until=datetime.now(timezone.utc) + timedelta(minutes=5))
    owner.commit()
    token = {"attempt": 1, "fence": 1, "owner": db.roles["service"]}
    before = snapshot(owner)
    closed, _ = settle_tool(service, extra, token, "success",
                            {"status": "ok", "output": {}, "usage": None})
    assert closed == {"v": 1, "error": {"code": "invalid_outcome", "detail": {}}}, closed
    assert snapshot(owner) == before, "duplicate-continuation W0 wrote rows"
    assert effect_row(owner, extra)["status"] == "claimed"
    print("[G2b-G] an extra claimed tool on a closed batch -> invalid_outcome "
          "W0 (continuation already exists), ten tables byte-equal")


def tool_batch_settlement_order(db, owner):
    """G2b-F: two-connection concurrent claims and settlements of one batch."""
    service = db.connect("service")
    # Symmetric race-only connections: fixture SQL runs on `service`, and both
    # racers get the same claim history before the settlement race, so neither
    # side is warmed by setup.
    conns = {"a": db.connect("service"), "b": db.connect("service")}
    keys = ("f0", "f1")
    budget = {"steps": 7, "tool_calls": 2, "tokens": 5000, "wall_ms": 600000}
    creators = []
    try:
        for trial, order in enumerate((("a", "b"), ("b", "a")), start=1):
            realm = f"g2b-f-{trial}"
            run_id, model_id = start_tool_run(owner, service, realm, keys, budget)
            ids, digest, _ = settle_tool_batch(owner, service, run_id, model_id, keys)
            tool_for = {"a": ids[0], "b": ids[1]}
            claim_participants = [
                (label, conns[label],
                 lambda conn, label=label: claim_effect(conn, tool_for[label]))
                for label in order
            ]
            claims = concurrent_actions(claim_participants, "G2b-F-claims")
            assert set(claims) == set(conns), claims
            for label in order:
                assert claims[label]["attempt"] == 1, (trial, claims[label])
                assert claims[label]["fence"] == 1, (trial, claims[label])
                assert claims[label]["owner"] == db.roles["service"], claims[label]
            assert ids[0] != ids[1]
            rows = tool_rows(owner, run_id)
            assert [row["status"] for row in rows] == ["claimed", "claimed"], rows
            assert [row["claim_owner"] for row in rows] == [db.roles["service"]] * 2, rows
            print(f"[G2b-F] trial {trial}: Barrier(2) claims of two distinct tools "
                  f"(thread start order={order}); both committed, effect ids differ, "
                  f"attempt=1/fence=1 each")

            outcomes = {
                "a": {"v": 1, "class": "success", "claim": claims["a"],
                      "body": {"kind": "tool_call",
                               "result": {"status": "ok", "output": {"i": 0},
                                          "usage": None}}},
                "b": {"v": 1, "class": "success", "claim": claims["b"],
                      "body": {"kind": "tool_call",
                               "result": {"status": "ok", "output": {"i": 1},
                                          "usage": None}}},
            }
            settle_participants = [
                (label, conns[label],
                 lambda conn, label=label: advance(conn, tool_for[label], outcomes[label]))
                for label in order
            ]
            winner_label, winner_response, results, evidence = serialized_race(
                db, settle_participants, "G2b-F")
            creator_label = evidence["loser"]
            creator_response = results[creator_label]
            assert_owner_envelope(winner_response)
            assert winner_response["emitted"] == [], (trial, winner_response)
            assert_owner_envelope(creator_response)
            assert len(creator_response["emitted"]) == 1, (trial, creator_response)
            continuation = creator_response["emitted"][0]
            assert continuation == md5_uuid(f"{model_id}:continuation"), continuation
            cont = effect_row(owner, continuation)
            assert cont["parent_effect_id"] == ids[1], (trial, cont)
            assert cont["ordinal"] == 0 and cont["kind"] == "model_call", (trial, cont)
            assert cont["request"]["cause"] == "continuation", (trial, cont)
            assert cont["request"]["batch_digest"] == digest, (trial, cont)
            assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                               "AND effect_id=%s", (run_id, continuation)) == 1
            assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                               "AND parent_effect_id=%s AND kind='model_call'",
                        (run_id, ids[1])) == 1
            models = read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                                 "AND kind='model_call'", (run_id,))
            assert models == 2, (trial, models)
            run = run_row(owner, run_id)
            assert run["turn_no"] == 3, (trial, run)
            creators.append(creator_label)
            print(f"[G2b-F] trial {trial}: G winner={winner_label} held its transaction "
                  f"open; creator/closure observer={creator_label}; first settlement 0 "
                  f"successors, second exactly one continuation parent=ordinal-1 tool "
                  f"(ids[1]), ordinal=0, batch_digest equal; exactly 2 model_call effects")
    finally:
        for conn in conns.values():
            conn.close()

    print(f"[G2b-F] {len(creators)} fresh fixtures: creators={creators}; "
          f"continuation identity is independent of which connection settles first")


def tool_call_budget(db, owner):
    """G2b-K: 17 is structural W0, exactly 16 is accepted, 5 with 2 left seals."""
    service = db.connect("service")
    budget = {"steps": 7, "tool_calls": 16, "tokens": 5000, "wall_ms": 600000}
    run_id, model_id = start_tool_run(owner, service, "g2b-k17", ("only",), budget)
    token = claim_effect(service, model_id)
    before = snapshot(owner)
    response, _ = settle(service, model_id, token, "success",
                         {"tool_calls": make_tool_calls([f"k{i}" for i in range(17)])})
    assert response == {"v": 1, "error": {"code": "invalid_outcome", "detail": {}}}, response
    assert snapshot(owner) == before, "17 tool_calls wrote rows"
    model = effect_row(owner, model_id)
    assert model["status"] == "claimed" and model["attempt_no"] == 1, model
    assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                       "AND kind='tool_call'", (run_id,)) == 0
    print("[G2b-K] 17 tool_calls: structural invalid_outcome W0, ten tables "
          "byte-equal, model still claimed, 0 tool effects (no truncation)")

    keys16 = tuple(f"k{i}" for i in range(16))
    budget16 = {"steps": 8, "tool_calls": 16, "tokens": 5000, "wall_ms": 600000}
    run16, model16 = start_tool_run(owner, service, "g2b-k16", keys16, budget16)
    ids, digest, _ = settle_tool_batch(owner, service, run16, model16, keys16)
    tools = tool_rows(owner, run16)
    assert len(tools) == 16, tools
    assert [tool["ordinal"] for tool in tools] == list(range(16)), tools
    assert [tool["effect_id"] for tool in tools] == ids, tools
    assert db_batch_digest(owner, model16) == digest
    run = run_row(owner, run16)
    assert run["remaining_tool_calls"] == 0 and run["turn_no"] == 1, run
    print("[G2b-K] exactly 16 tool_calls accepted: 16 ready tools ordinal 0..15, "
          "one digest, tool_calls budget fully debited")

    keys5 = ("b0", "b1", "b2", "b3", "b4")
    budget5 = {"steps": 7, "tool_calls": 2, "tokens": 5000, "wall_ms": 600000}
    run5, model5 = start_tool_run(owner, service, "g2b-k-budget", keys5, budget5)
    token5 = claim_effect(service, model5)
    response, receipt = settle(service, model5, token5, "success",
                               {"text": "too many", "tool_calls": make_tool_calls(keys5)})
    assert_owner_envelope(response)
    assert response["emitted"] == [], response
    model = effect_row(owner, model5)
    run = run_row(owner, run5)
    assert model["status"] == "succeeded" and model["outcome"] == receipt, model
    assert run["status"] == "completed", run
    assert run["close_intent"] == {"kind": "budget"}, run
    assert run["result"]["close_reason"] == "budget_exhausted", run
    assert run["turn_no"] == 1 and run["remaining_tool_calls"] == 2, run
    assert run["remaining_steps"] == 6 and run["remaining_tokens"] == 5000, run
    assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                       "AND kind='tool_call'", (run5,)) == 0
    print("[G2b-K/budget] 5 tool_calls with 2 remaining: model succeeded, 0 tool "
          "effects, run completed/budget_exhausted, tool_calls budget unchanged")


# ---------------------------------------------------------------------------
# S4 W3: interaction production (G2b-H) and the real respond chain (G2b-I).

def advance_text(conn, effect_id, outcome):
    return one(conn, "SELECT v24.advance(%s,%s)::text", (effect_id, Json(outcome)))


def event_kinds(owner, effect_id):
    return read(owner, """SELECT coalesce(jsonb_agg(event_kind ORDER BY seq),'[]'::jsonb)
        FROM v24.events WHERE effect_id=%s""", (effect_id,))


def events_of_kind(owner, run_id, kind):
    return read(owner, """SELECT coalesce(jsonb_agg(to_jsonb(e) ORDER BY e.seq),'[]'::jsonb)
        FROM v24.events e WHERE e.entity_id=%s AND e.event_kind=%s""", (run_id, kind))


def produce_waiting_interaction(owner, service, realm, *, schema_digest, prompt_digest,
                                payload, usage_tokens=40):
    """Drive start -> claim -> model success carrying interaction, no fake state."""
    root, live, _ = loop_fixture(owner, service, realm=realm)
    budget = {"steps": 7, "tool_calls": 3, "tokens": 5000, "wall_ms": 600000}
    response, _ = start(service, root, live["fiber"], {}, budget, f"{realm}-{uuid4()}")
    service.commit()
    assert_owner_envelope(response)
    run_id, model_id = response["emitted"]
    token = claim_effect(service, model_id)
    result = {"text": "need input",
              "interaction": {"schema_digest": schema_digest,
                              "prompt_digest": prompt_digest,
                              "payload": payload},
              "usage": {"tokens": usage_tokens, "wall_ms": 7}}
    settled, receipt = settle(service, model_id, token, "success", result)
    assert_owner_envelope(settled)
    return run_id, model_id, settled, receipt


def assert_respond_mismatch_w1(owner, before, response, key, label):
    """interaction_mismatch is W1: zero domain rows, exactly one command receipt."""
    assert response == {"v": 1, "error": {"code": "interaction_mismatch",
                                         "detail": {}}}, (label, response)
    after = snapshot(owner)
    for table in EXPECTED_TABLES - {"effects", "requests"}:
        assert after[table] == before[table], (label, table, "domain write")
    new_effects = [row for row in after["effects"] if row not in before["effects"]]
    new_requests = [row for row in after["requests"] if row not in before["requests"]]
    assert len(new_effects) == 1 and new_effects[0]["request_key"] == key, (label, new_effects)
    assert new_effects[0]["kind"] == "command_respond", (label, new_effects[0])
    assert new_effects[0]["status"] == "failed", (label, new_effects[0])
    assert len(new_requests) == 1, (label, new_requests)
    assert new_requests[0]["effect_id"] == new_effects[0]["effect_id"], (label, new_requests)
    assert new_requests[0]["response"] == response, (label, new_requests[0])
    print(f"[G2b-I/{label}] interaction_mismatch: ten-table domain byte-equal; W1 "
          f"command+receipt only")


def interaction_production(db, owner):
    """G2b-H: model success with interaction -> waiting, exact six fields, 0 successors."""
    service = db.connect("service")
    schema_digest = "1" * 64
    prompt_digest = "2" * 64
    payload = {"question": "colour?", "options": ["red", "blue"]}
    run_id, model_id, settled, receipt = produce_waiting_interaction(
        owner, service, "g2b-h", schema_digest=schema_digest,
        prompt_digest=prompt_digest, payload=payload)
    assert settled["emitted"] == [], settled
    run = run_row(owner, run_id)
    model = effect_row(owner, model_id)
    interaction = run["interaction"]
    assert set(interaction) == {"interaction_id", "origin_effect_id", "generation",
                                "schema_digest", "prompt_digest", "created_at"}, interaction
    assert interaction["interaction_id"] == model_id, interaction
    assert interaction["origin_effect_id"] == model_id, interaction
    assert interaction["generation"] == 1, interaction
    assert interaction["schema_digest"] == schema_digest, interaction
    assert interaction["prompt_digest"] == prompt_digest, interaction
    assert interaction["created_at"] is not None, interaction
    assert run["status"] == "waiting", run
    assert run["pending_steer"] is None, run
    assert run["close_intent"] is None and run["result"] is None, run
    assert run["ended_at"] is None, run
    assert run["turn_no"] == 1 and run["revision"] == 2, run
    assert run["remaining_steps"] == 6 and run["remaining_tool_calls"] == 3, run
    assert run["remaining_tokens"] == 4960, run
    assert model["status"] == "succeeded" and model["outcome"] == receipt, model
    assert model["resource_quiesced_at"] is not None, model
    assert model["claim_owner"] is None and model["lease_until"] is None, model
    assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                       "AND kind IN ('model_call','tool_call')", (run_id,)) == 1
    assert read(owner, "SELECT count(*) FROM v24.requests WHERE effect_id=%s",
                (model_id,)) == 0
    kinds = event_kinds(owner, model_id)
    assert kinds == ["model_call_settled", "interaction_created"], kinds
    created = events_of_kind(owner, run_id, "interaction_created")
    assert len(created) == 1, created
    assert created[0]["payload"] == {"run_id": run_id, "effect_id": model_id,
                                     "interaction_id": model_id, "generation": 1}, created[0]
    print("[G2b-H] model interaction: run waiting pending_steer=NULL; interaction "
          "exactly {interaction_id,origin_effect_id,generation,schema_digest,"
          "prompt_digest,created_at}; ids=source model; generation=1; 0 successors; "
          "1 interaction_created; turn_no=1 steps=6 tokens=904+4096-40=4960")

    before = snapshot(owner)
    first_raw = advance_text(service, model_id, receipt)
    service.commit()
    first = json.loads(first_raw)
    assert first["disposition"] == "replay" and first["emitted"] == [], first
    second_raw = advance_text(service, model_id, receipt)
    service.commit()
    assert second_raw == first_raw, "interaction replay bytes changed"
    assert snapshot(owner) == before, "interaction replay wrote rows"
    print("[G2b-H] replay: same receipt twice -> byte-equal replay responses and "
          "ten-table byte-equal snapshot; still one interaction_created")


def interaction_respond_chain(db, owner):
    """G2b-I: respond consumes the W3 interaction and admits one respond model."""
    service = db.connect("service")
    schema_digest = "3" * 64
    prompt_digest = "4" * 64
    payload = {"question": "ready?", "options": ["yes", "no"]}
    run_id, model_id, settled, _ = produce_waiting_interaction(
        owner, service, "g2b-i", schema_digest=schema_digest,
        prompt_digest=prompt_digest, payload=payload)
    assert settled["emitted"] == [], settled
    waiting = run_row(owner, run_id)
    interaction = waiting["interaction"]
    old_model = effect_row(owner, model_id)

    # Wrong interaction id plus a stale generation: interaction precedes CAS.
    before = snapshot(owner)
    wrong_key = f"g2b-i-wrong-{uuid4()}"
    wrong, _ = respond(service, run_id, uuid4(), {"answer": "no"},
                       waiting["driving_generation"] + 1, wrong_key)
    service.commit()
    assert_respond_mismatch_w1(owner, before, wrong, wrong_key, "wrong-id")

    answer = {"answer": "yes", "structured": {"n": 7}, "nested": [True, None]}
    before = snapshot(owner)
    response, _ = respond(service, run_id, interaction["interaction_id"], answer,
                          waiting["driving_generation"], f"g2b-i-{uuid4()}")
    service.commit()
    assert_owner_envelope(response)
    assert len(response["emitted"]) == 1, response
    new_model_id = response["emitted"][0]
    command_id = response["effect_id"]
    assert new_model_id == md5_uuid(f"{command_id}:model_call:0"), response
    run = run_row(owner, run_id)
    reserve = read(owner, "SELECT v24.model_reserve(%s)", (waiting["remaining_tokens"],))
    assert run["status"] == "running" and run["interaction"] is None, run
    assert run["driving_generation"] == waiting["driving_generation"] + 1, run
    assert run["revision"] == waiting["revision"] + 1, run
    assert run["turn_no"] == waiting["turn_no"], run
    assert run["remaining_steps"] == waiting["remaining_steps"] - 1, run
    assert run["remaining_tokens"] == waiting["remaining_tokens"] - reserve, run
    assert run["remaining_tokens"] == 864 and reserve == 4096, run
    models = model_rows(owner, run_id)
    assert len(models) == 2, models
    assert row_of(models, "effect_id", model_id) == old_model, "old model effect changed"
    new_model = row_of(models, "effect_id", new_model_id)
    digests = read(owner, "SELECT v24.model_digests(%s)", (run_id,))
    assert new_model["status"] == "ready" and new_model["ordinal"] == 0, new_model
    assert new_model["parent_effect_id"] == command_id, new_model
    assert new_model["generation"] == waiting["driving_generation"] + 1, new_model
    assert new_model["epoch_no"] == waiting["epoch_no"] and new_model["pin_id"] is None, new_model
    assert new_model["request"] == {
        "run_id": run_id, "epoch_no": waiting["epoch_no"],
        "generation": waiting["driving_generation"] + 1,
        "response": answer, "origin_effect_id": model_id,
        "v": 1, "cause": "respond",
        "reserve": {"tokens": reserve}, "digests": digests}, new_model["request"]
    assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                       "AND kind='model_call' AND status='ready'", (run_id,)) == 1
    after = snapshot(owner)
    new_events = [row for row in after["events"] if row not in before["events"]]
    assert len(new_events) == 1, new_events
    assert new_events[0]["event_kind"] == "interaction_responded", new_events[0]
    assert new_events[0]["payload"] == {
        "run_id": run_id, "interaction_id": interaction["interaction_id"],
        "generation": waiting["driving_generation"] + 1}, new_events[0]
    new_effects = [row for row in after["effects"] if row not in before["effects"]]
    assert len(new_effects) == 2, new_effects
    assert len([row for row in new_effects if row["kind"] == "model_call"]) == 1, new_effects
    assert len([row for row in new_effects if row["kind"] == "command_respond"]) == 1, new_effects
    print("[G2b-I] respond: interaction cleared, status running, generation+1 "
          "(1->2), revision+1, steps 6->5, tokens 4960-4096=864; exactly one ready "
          "cause=respond model with response/origin/digests; one interaction_responded; "
          "old model effect byte-unchanged")

    # A distinct key after consumption sees the interaction mismatch before CAS.
    before = snapshot(owner)
    second_key = f"g2b-i-second-{uuid4()}"
    second, _ = respond(service, run_id, interaction["interaction_id"], answer,
                        waiting["driving_generation"], second_key)
    service.commit()
    assert_respond_mismatch_w1(owner, before, second, second_key, "consumed")


def tool_unknown_wall(db, owner):
    """G2b-N: tool unknown keeps its receipt, blocks the run, retains its pin."""
    service = db.connect("service")
    keys = ("u0", "u1")
    budget = {"steps": 7, "tool_calls": 2, "tokens": 5000, "wall_ms": 600000}
    run_id, model_id = start_tool_run(owner, service, "g2b-n", keys, budget)
    ids, _, pins = settle_tool_batch(owner, service, run_id, model_id, keys)
    token0 = claim_effect(service, ids[0])
    token1 = claim_effect(service, ids[1])
    base = run_row(owner, run_id)
    response, receipt = settle_tool(service, ids[0], token0, "unknown",
                                    {"status": "error", "output": {"lost": True},
                                     "usage": {"wall_ms": 9}})
    assert_owner_envelope(response)
    assert response["emitted"] == [], response
    tool = effect_row(owner, ids[0])
    run = run_row(owner, run_id)
    assert tool["status"] == "unknown" and tool["outcome"] == receipt, tool
    assert tool["outcome"]["class"] == "unknown", tool
    assert tool["resource_quiesced_at"] is None, tool
    assert run["status"] == "blocked_unknown", run
    assert run["close_intent"]["kind"] == "unknown", run
    assert run["pending_steer"] is None and run["interaction"] is None, run
    assert run["turn_no"] == base["turn_no"] + 1, run
    assert run["remaining_tokens"] == base["remaining_tokens"], run
    own_pin = next(pin for pin in run_pins(owner, run_id)
                   if pin["pin_id"] == pins[keys[0]]["pin_id"])
    assert own_pin["released_at"] is None and own_pin["released_by_effect"] is None, own_pin
    assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                       "AND kind='model_call'", (run_id,)) == 1
    print("[G2b-N] tool unknown: effect unknown with original receipt byte-equal, "
          "resource_quiesced NULL, run blocked_unknown, 0 successors, tokens "
          "untouched, own pin retained")

    before = snapshot(owner)
    claim_again = advance(service, ids[0], claim())
    service.commit()
    assert claim_again == {"v": 1, "error": {"code": "invalid_args", "detail": {}}}, claim_again
    assert snapshot(owner) == before, "unknown re-claim wrote rows"
    print("[G2b-N] a later claim on the unknown tool is invalid_args with a "
          "byte-equal snapshot")

    before = snapshot(owner)
    late = advance(service, ids[1], {"v": 1, "class": "success", "claim": token1,
                                     "body": {"kind": "tool_call",
                                              "result": {"status": "ok", "output": {}}}})
    service.commit()
    assert late == {"v": 1, "error": {"code": "blocked_unknown", "detail": {}}}, late
    assert snapshot(owner) == before, "blocked_unknown run settlement wrote rows"
    print("[G2b-N] a sibling settlement on the blocked_unknown run is W0 "
          "blocked_unknown with a byte-equal snapshot")

    # D-S4-3: steer/respond on the blocked_unknown run are W0 walls too: the
    # code replaces already_terminal and writes neither command nor receipt.
    before = snapshot(owner)
    steer_refused, _ = steer(service, run_id, run["driving_generation"], "no more",
                             f"g2b-n-steer-{uuid4()}")
    service.commit()
    assert steer_refused == {"v": 1, "error": {"code": "blocked_unknown",
                                               "detail": {}}}, steer_refused
    assert snapshot(owner) == before, "blocked_unknown steer wrote rows"
    print("[G2b-N] steer on the blocked_unknown run is W0 blocked_unknown with a "
          "ten-table byte-equal snapshot (no command effect, no receipt)")

    before = snapshot(owner)
    respond_refused, _ = respond(service, run_id, uuid4(), {"answer": "no"},
                                 run["driving_generation"], f"g2b-n-respond-{uuid4()}")
    service.commit()
    assert respond_refused == {"v": 1, "error": {"code": "blocked_unknown",
                                                 "detail": {}}}, respond_refused
    assert snapshot(owner) == before, "blocked_unknown respond wrote rows"
    print("[G2b-N] respond on the blocked_unknown run is W0 blocked_unknown with a "
          "ten-table byte-equal snapshot (no command effect, no receipt)")


# ---------------------------------------------------------------------------
# S4 W4: turn/budget/seal (G2b-J), pending final seal (G2b-M), cancel x T2 (G2b-O).

def assert_business_idle(owner, run_id):
    ready = read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                        "AND kind IN ('model_call','tool_call') "
                        "AND status IN ('ready','claimed')", (run_id,))
    assert ready == 0, (run_id, ready)


def steps_budget_and_admission(db, owner):
    """G2b-J: steps/token exhaustion seals at every model-continuation admission."""
    service = db.connect("service")

    # J/tools: steps=1 is fully debited by start.  The model turn still admits
    # its two tools; the batch-closing settlement sees steps=0 and must seal.
    keys = ("j0", "j1")
    budget = {"steps": 1, "tool_calls": 2, "tokens": 5000, "wall_ms": 600000}
    run_id, model_id = start_tool_run(owner, service, "g2b-j", keys, budget)
    run = run_row(owner, run_id)
    assert run["status"] == "running" and run["turn_no"] == 0, run
    assert run["remaining_steps"] == 0, run
    ids, _, _ = settle_tool_batch(owner, service, run_id, model_id, keys)
    run = run_row(owner, run_id)
    assert run["turn_no"] == 1 and run["remaining_steps"] == 0, run
    assert run["remaining_tool_calls"] == 0, run
    assert run["remaining_tokens"] == 5000, run

    token = claim_effect(service, ids[0])
    first, _ = settle_tool(service, ids[0], token, "success",
                           {"status": "ok", "output": {"i": 0},
                            "usage": {"wall_ms": 2}})
    assert_owner_envelope(first)
    assert first["emitted"] == [], first
    run = run_row(owner, run_id)
    assert run["status"] == "running" and run["turn_no"] == 2, run

    token = claim_effect(service, ids[1])
    closing, receipt = settle_tool(service, ids[1], token, "success",
                                   {"status": "ok", "output": {"i": 1},
                                    "usage": {"wall_ms": 3}})
    assert_owner_envelope(closing)
    assert closing["emitted"] == [], closing
    run = run_row(owner, run_id)
    expected = {"v": 1, "close_reason": "budget_exhausted", "final_text": None,
                "turn_no": 3, "budget": budget}
    assert run["status"] == "completed", run
    assert run["close_intent"] == {"kind": "budget"}, run
    assert run["result"] == expected, run
    assert run["remaining_steps"] == 0 and run["turn_no"] == 3, run
    assert run["ended_at"] is not None, run
    assert_business_idle(owner, run_id)
    assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                       "AND kind='model_call'", (run_id,)) == 1
    assert effect_row(owner, ids[1])["outcome"] == receipt
    assert event_kinds(owner, ids[1]) == [
        "tool_call_settled", "tool_batch_completed", "budget_exhausted",
        "run_completed"], event_kinds(owner, ids[1])
    completed_events = events_of_kind(owner, run_id, "run_completed")
    assert len(completed_events) == 1, completed_events
    assert completed_events[0]["payload"]["close_reason"] == "budget_exhausted", completed_events
    print("[G2b-J] steps=1: start debits the only step (turn_no stays 0); the model "
          "turn admits 2 tools and turn_no advances 1->2; the last (closing) tool "
          "sees steps=0 and seals completed/budget_exhausted with turn_no=3, 0 "
          "successors, no continuation model, no error envelope")

    # J/model: the same steps=0 guard on a plain-text continuation admission.
    root, live, _ = loop_fixture(owner, service, realm="g2b-j-model")
    response, _ = start(service, root, live["fiber"], {}, budget, f"g2b-jm-{uuid4()}")
    service.commit()
    assert_owner_envelope(response)
    run_id, model_id = response["emitted"]
    assert run_row(owner, run_id)["remaining_steps"] == 0
    token = claim_effect(service, model_id)
    settled, _ = settle(service, model_id, token, "success",
                        {"text": "again", "usage": {"tokens": 10, "wall_ms": 1}})
    assert_owner_envelope(settled)
    assert settled["emitted"] == [], settled
    run = run_row(owner, run_id)
    assert run["status"] == "completed" and run["close_intent"] == {"kind": "budget"}, run
    assert run["result"]["close_reason"] == "budget_exhausted", run
    assert run["result"]["turn_no"] == 1, run
    assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                       "AND kind='model_call'", (run_id,)) == 1
    assert_business_idle(owner, run_id)
    print("[G2b-J/model] steps=0 at a plain-text continuation admission: the model "
          "settles (turn 1), no continuation is built, run completed/budget_exhausted")

    # J/tokens: start's first model is allowed at tokens=0 (C23 addendum B), but
    # a post-refund 0 balance cannot admit a continuation.
    zero_budget = {"steps": 7, "tool_calls": 2, "tokens": 0, "wall_ms": 600000}
    root, live, _ = loop_fixture(owner, service, realm="g2b-j-tokens")
    response, _ = start(service, root, live["fiber"], {}, zero_budget,
                        f"g2b-jz-{uuid4()}")
    service.commit()
    assert_owner_envelope(response)
    run_id, model_id = response["emitted"]
    assert run_row(owner, run_id)["remaining_tokens"] == 0
    assert effect_row(owner, model_id)["request"]["reserve"] == {"tokens": 0}
    token = claim_effect(service, model_id)
    settled, _ = settle(service, model_id, token, "success",
                        {"text": "only turn", "usage": {"tokens": 0, "wall_ms": 1}})
    assert_owner_envelope(settled)
    assert settled["emitted"] == [], settled
    run = run_row(owner, run_id)
    assert run["status"] == "completed" and run["close_intent"] == {"kind": "budget"}, run
    assert run["result"]["close_reason"] == "budget_exhausted", run
    assert run["remaining_tokens"] == 0 and run["turn_no"] == 1, run
    assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                       "AND kind='model_call'", (run_id,)) == 1
    assert_business_idle(owner, run_id)
    print("[G2b-J/tokens] tokens=0 admits start's first model; its plain-text "
          "settlement cannot reserve a continuation and seals completed/"
          "budget_exhausted at 0 balance")


def pending_final_seal(db, owner):
    """G2b-M: final blocked by a ready tool freezes close_intent; drain seals it."""
    service = db.connect("service")
    root, live, _ = loop_fixture(owner, service, realm="g2b-m", requires=("m0",))
    budget = {"steps": 4, "tool_calls": 2, "tokens": 5000, "wall_ms": 600000}
    response, _ = start(service, root, live["fiber"],
                        {"requires": [{"key": "m0"}]}, budget, f"g2b-m-{uuid4()}")
    service.commit()
    assert_owner_envelope(response)
    run_id, model_id = response["emitted"]
    run = run_row(owner, run_id)
    pin = run_pins(owner, run_id)[0]
    tool_id = md5_uuid(f"{model_id}:tool_call:0")
    request = {"v": 1, "run_id": run_id, "epoch_no": run["epoch_no"],
               "generation": run["driving_generation"], "ordinal": 0,
               "key": pin["key"], "args": {},
               "descriptor_digest": hexbyte(pin["descriptor_digest"]),
               "batch_digest": batch_digest([tool_id])}
    with owner.cursor() as cur:
        insert(cur, "effects", effect_id=tool_id, parent_effect_id=model_id,
               ordinal=0, requester_id=uuid4(), run_id=run_id,
               pin_id=pin["pin_id"], epoch_no=run["epoch_no"],
               generation=run["driving_generation"], kind="tool_call",
               status="ready", request=Json(request), request_digest=DIGEST,
               replay_policy="no_replay")
    owner.commit()

    token = claim_effect(service, model_id)
    frozen = {"kind": "final"}
    settled, receipt = settle(service, model_id, token, "success",
                              {"text": "done", "final": {"text": "done"},
                               "usage": {"tokens": 40, "wall_ms": 5}})
    assert_owner_envelope(settled)
    assert settled["emitted"] == [], settled
    run = run_row(owner, run_id)
    assert run["status"] == "running", run
    assert run["close_intent"] == frozen, run
    assert run["result"] is None and run["ended_at"] is None, run
    assert run["turn_no"] == 1 and run["remaining_steps"] == 3, run
    assert run["remaining_tokens"] == 4960, run
    assert effect_row(owner, model_id)["status"] == "succeeded"
    assert effect_row(owner, model_id)["outcome"] == receipt
    assert effect_row(owner, tool_id)["status"] == "ready"
    assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                       "AND kind='model_call'", (run_id,)) == 1
    print("[G2b-M/final] final settlement with a ready tool: only "
          "close_intent={kind:final} is written; "
          "run stays running, result NULL, 0 successors, no continuation model")

    token = claim_effect(service, tool_id)
    closed, tool_receipt = settle_tool(service, tool_id, token, "success",
                                       {"status": "ok", "output": {"drain": 1},
                                        "usage": {"wall_ms": 3}})
    assert_owner_envelope(closed)
    assert closed["emitted"] == [], closed
    run = run_row(owner, run_id)
    assert run["status"] == "completed", run
    assert run["close_intent"] == frozen, run
    assert run["result"] == {"v": 1, "close_reason": "final", "final_text": "done",
                             "turn_no": 2, "budget": budget}, run
    assert run["ended_at"] is not None and run["turn_no"] == 2, run
    assert effect_row(owner, tool_id)["outcome"] == tool_receipt
    assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                       "AND kind='model_call'", (run_id,)) == 1
    assert read(owner, "SELECT count(*) FROM v24.effects WHERE effect_id=%s",
                (md5_uuid(f"{model_id}:continuation"),)) == 0
    assert_business_idle(owner, run_id)
    assert all(pin["released_at"] is not None for pin in run_pins(owner, run_id))
    kinds = event_kinds(owner, tool_id)
    assert kinds == ["tool_call_settled", "tool_batch_completed",
                     "run_completed"], kinds
    completed_events = events_of_kind(owner, run_id, "run_completed")
    assert len(completed_events) == 1, completed_events
    assert completed_events[0]["payload"]["close_reason"] == "final", completed_events
    print("[G2b-M/drain] the closing tool settlement seals the frozen final result "
          "(completed/close_reason=final/final_text='done', turn 2, original "
          "budget), releases the pin and creates no continuation")


def ordered_advance_race(db, first, second, tag, deadline_seconds=10):
    """Run ``first`` (holding G open), then start ``second`` and prove it blocks.

    The first advance returns without committing, so its transaction-scoped
    ``pg_advisory_xact_lock(24,1)`` (G) stays held.  The second advance then runs
    on its own connection and must queue on the same advisory lock, proven by
    ``pg_blocking_pids()`` and an ungranted ``pg_locks`` row.  Ordering is fixed
    by the held advisory lock and the first response, never by a sleep.
    """
    first_label, first_conn, first_action = first
    second_label, second_conn, second_action = second
    observer = db.connect()
    observer.autocommit = True
    release = threading.Event()
    signals = {first_label: queue.Queue(), second_label: queue.Queue()}
    results, failures = {}, {}
    threads = []

    def run(label, conn, action):
        try:
            response = action(conn)
            results[label] = response
            signals[label].put(response)
            if not release.wait(timeout=20):
                raise AssertionError(f"{tag}: {label} was never released")
            conn.commit()
        except BaseException as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            failures[label] = exc
            signals[label].put(exc)

    first_thread = threading.Thread(target=run, args=(first_label, first_conn, first_action),
                                    name=f"{tag}-{first_label}", daemon=True)
    threads.append(first_thread)
    second_thread = None
    try:
        first_thread.start()
        first_response = signals[first_label].get(timeout=10)
        if isinstance(first_response, BaseException):
            raise first_response
        first_pid = first_conn.get_backend_pid()
        second_pid = second_conn.get_backend_pid()
        second_thread = threading.Thread(target=run,
                                         args=(second_label, second_conn, second_action),
                                         name=f"{tag}-{second_label}", daemon=True)
        threads.append(second_thread)
        second_thread.start()
        deadline = time.monotonic() + deadline_seconds
        while True:
            if second_label in failures:
                raise failures[second_label]
            with observer.cursor() as cur:
                cur.execute(
                    """SELECT pg_blocking_pids(%s)::text,
                              %s = ANY(pg_blocking_pids(%s)),
                              (SELECT count(*) FROM pg_locks
                                WHERE pid=%s AND locktype='advisory' AND NOT granted)""",
                    (second_pid, first_pid, second_pid, second_pid))
                blockers, blocks_on_first, ungranted = cur.fetchone()
            if blocks_on_first and ungranted >= 1:
                break
            assert second_thread.is_alive(), (
                f"{tag}: {second_label} finished before blocking on {first_label}")
            assert time.monotonic() < deadline, (
                f"{tag}: {second_label} did not block on {first_label} "
                f"(blockers={blockers}, ungranted_advisory={ungranted})")
        first_state = one(observer, "SELECT state FROM pg_stat_activity WHERE pid=%s",
                          (first_pid,))
        assert first_state == "idle in transaction", (tag, first_state)
        print(f"[{tag}] {first_label} pid={first_pid} holds G "
              f"(pg_stat_activity.state='idle in transaction'); {second_label} "
              f"pid={second_pid} blocked: pg_blocking_pids({second_pid})={blockers}, "
              f"pg_locks(pid={second_pid}, locktype='advisory', granted=false)="
              f"{ungranted}")
        evidence = {"first": first_label, "second": second_label,
                    "first_pid": first_pid, "blocked_pid": second_pid,
                    "blockers": blockers, "ungranted_advisory": ungranted}
        release.set()
        for thread in threads:
            thread.join(timeout=10)
            assert not thread.is_alive(), f"{tag}: thread still running after G release"
        if failures:
            raise next(iter(failures.values()))
        assert set(results) == {first_label, second_label}, (tag, results)
        return results[first_label], results[second_label], evidence
    finally:
        release.set()
        for thread in threads:
            thread.join(timeout=10)
        for conn in (first_conn, second_conn):
            try:
                conn.rollback()
            except Exception:
                pass
        observer.close()


def cancel_t2_two_orders(db, owner):
    """G2b-O: cancel x T2 in both submit orders with held-G blocking evidence."""
    service = db.connect("service")
    try:
        # Order 1: T2 (plain-text model settlement) submits first.  It records
        # its fact/cost and publishes the continuation; cancel then seals the run
        # and archives that ready successor without overwriting the receipt.
        root, live, _ = loop_fixture(owner, service, realm="g2b-o1")
        budget = {"steps": 7, "tool_calls": 2, "tokens": 5000, "wall_ms": 600000}
        response, _ = start(service, root, live["fiber"], {}, budget,
                            f"g2b-o1-{uuid4()}")
        service.commit()
        assert_owner_envelope(response)
        run_id, model_id = response["emitted"]
        token = claim_effect(service, model_id)
        receipt = {"v": 1, "class": "success", "claim": token,
                   "body": {"kind": "model_call",
                            "result": {"text": "step",
                                       "usage": {"tokens": 40, "wall_ms": 5}}}}
        cancel_key = f"g2b-o1-cancel-{uuid4()}"
        conns = (db.connect("service"), db.connect("service"))
        try:
            settled, cancelled, evidence = ordered_advance_race(
                db,
                ("settle", conns[0],
                 lambda conn: advance(conn, model_id, receipt)),
                ("cancel", conns[1],
                 lambda conn: cancel(conn, run_id, 1, cancel_key)[0]),
                "G2b-O1")
        finally:
            for conn in conns:
                conn.close()
        assert evidence["first"] == "settle" and evidence["second"] == "cancel", evidence
        assert str(evidence["first_pid"]) in evidence["blockers"], evidence
        assert evidence["ungranted_advisory"] >= 1, evidence
        continuation = md5_uuid(f"{model_id}:continuation")
        assert_owner_envelope(settled)
        assert settled["emitted"] == [continuation], settled
        assert cancelled["disposition"] == "committed", cancelled
        assert cancelled["emitted"] == [], cancelled
        run = run_row(owner, run_id)
        assert run["status"] == "cancelled", run
        assert run["close_intent"]["kind"] == "cancel", run
        assert run["result"] is None, run
        assert run["turn_no"] == 1, run
        assert run["driving_generation"] == 2, run
        assert run["remaining_steps"] == 5, run
        assert run["remaining_tokens"] == 4960, run
        assert run["ended_at"] is not None, run
        model = effect_row(owner, model_id)
        assert model["status"] == "succeeded" and model["outcome"] == receipt, model
        assert model["settled_at"] is not None, model
        successor = effect_row(owner, continuation)
        assert successor["status"] == "cancelled", successor
        assert successor["outcome"] is None, successor
        assert successor["settled_at"] is not None, successor
        assert_business_idle(owner, run_id)
        assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                           "AND kind IN ('model_call','tool_call')",
                    (run_id,)) == 2
        print(f"[G2b-O] order 1 (settle then cancel): settle pid="
              f"{evidence['first_pid']} held G; cancel pid={evidence['blocked_pid']} "
              f"blocked (pg_blocking_pids={evidence['blockers']}, ungranted advisory="
              f"{evidence['ungranted_advisory']}); model receipt/turn/cost retained, "
              f"cancel sealed kind='cancel', the published successor is cancelled/"
              f"NULL, 0 ready/claimed, no second successor")

        # Order 2: cancel submits first and revokes the claimed model token.  The
        # late success may only record fact/cost; it must not rewrite the cancel
        # seal or the held tool pin.
        root, live, _ = loop_fixture(owner, service, realm="g2b-o2", requires=("p0",))
        response, _ = start(service, root, live["fiber"],
                            {"requires": [{"key": "p0"}]}, budget,
                            f"g2b-o2-{uuid4()}")
        service.commit()
        assert_owner_envelope(response)
        run_id, model_id = response["emitted"]
        run = run_row(owner, run_id)
        held_pin = run_pins(owner, run_id)[0]
        tool_id = md5_uuid(f"{model_id}:tool_call:0")
        request = {"v": 1, "run_id": run_id, "epoch_no": run["epoch_no"],
                   "generation": run["driving_generation"], "ordinal": 0,
                   "key": held_pin["key"], "args": {},
                   "descriptor_digest": hexbyte(held_pin["descriptor_digest"]),
                   "batch_digest": batch_digest([tool_id])}
        with owner.cursor() as cur:
            insert(cur, "effects", effect_id=tool_id, parent_effect_id=model_id,
                   ordinal=0, requester_id=uuid4(), run_id=run_id,
                   pin_id=held_pin["pin_id"], epoch_no=run["epoch_no"],
                   generation=run["driving_generation"], kind="tool_call",
                   status="claimed", attempt_no=1, fence=1,
                   claim_owner="held-host",
                   lease_until=datetime.now(timezone.utc) + timedelta(minutes=5),
                   request=Json(request), request_digest=DIGEST,
                   replay_policy="no_replay")
        owner.commit()
        token = claim_effect(service, model_id)
        receipt = {"v": 1, "class": "success", "claim": token,
                   "body": {"kind": "model_call",
                            "result": {"text": "late",
                                       "usage": {"tokens": 40, "wall_ms": 5}}}}
        cancel_key = f"g2b-o2-cancel-{uuid4()}"
        conns = (db.connect("service"), db.connect("service"))
        try:
            cancelled, settled, evidence = ordered_advance_race(
                db,
                ("cancel", conns[0],
                 lambda conn: cancel(conn, run_id, 1, cancel_key)[0]),
                ("settle", conns[1],
                 lambda conn: advance(conn, model_id, receipt)),
                "G2b-O2")
        finally:
            for conn in conns:
                conn.close()
        assert evidence["first"] == "cancel" and evidence["second"] == "settle", evidence
        assert str(evidence["first_pid"]) in evidence["blockers"], evidence
        assert evidence["ungranted_advisory"] >= 1, evidence
        assert cancelled["disposition"] == "committed", cancelled
        assert cancelled["emitted"] == [], cancelled
        assert_owner_envelope(settled)
        assert settled["emitted"] == [], settled
        run = run_row(owner, run_id)
        assert run["status"] == "cancelled", run
        assert run["close_intent"]["kind"] == "cancel", run
        assert run["close_intent"]["generation"] == 1, run
        assert run["result"] is None, run
        assert run["turn_no"] == 1, run
        assert run["driving_generation"] == 2, run
        assert run["remaining_steps"] == 6, run
        assert run["remaining_tokens"] == 4960, run
        assert run["interaction"] is None and run["pending_steer"] is None, run
        model = effect_row(owner, model_id)
        assert model["status"] == "succeeded", model
        assert model["outcome"] == receipt, model
        assert model["resource_quiesced_at"] is not None, model
        assert model["cancel_requested"] is True, model
        assert model["claim_owner"] is None and model["lease_until"] is None, model
        held = effect_row(owner, tool_id)
        assert held["status"] == "claimed" and held["cancel_requested"] is True, held
        pin_row = next(item for item in run_pins(owner, run_id)
                       if item["pin_id"] == held_pin["pin_id"])
        assert pin_row["released_at"] is None, pin_row
        assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                           "AND kind='model_call'", (run_id,)) == 1
        assert read(owner, "SELECT count(*) FROM v24.effects WHERE effect_id=%s",
                    (md5_uuid(f"{model_id}:continuation"),)) == 0
        assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                           "AND kind='model_call' AND status IN ('ready','claimed')",
                    (run_id,)) == 0
        print(f"[G2b-O] order 2 (cancel then settle): cancel pid="
              f"{evidence['first_pid']} held G; settle pid={evidence['blocked_pid']} "
              f"blocked (pg_blocking_pids={evidence['blockers']}, ungranted advisory="
              f"{evidence['ungranted_advisory']}); claimed model became "
              f"cancel_requested and generation advanced 1->2; the late success "
              f"recorded only fact/cost (turn 1, tokens 4960), 0 successors, "
              f"close_intent/result preserved, held tool pin unreleased")
        print(f"[G2b-O] both orders proven with the G advisory lock as the barrier "
              f"and pg_blocking_pids evidence: order1 settle -> cancel; "
              f"order2 cancel -> settle")
    finally:
        service.close()


def cancel_t2_tool_unknown(db, owner):
    """G2b-O/tool-unknown: a cancel-late unknown tool preserves the cancel seal."""
    service = db.connect("service")
    try:
        root, live, _ = loop_fixture(owner, service, realm="g2b-o-tool-unknown",
                                     requires=("p0",))
        budget = {"steps": 7, "tool_calls": 2, "tokens": 5000, "wall_ms": 600000}
        response, _ = start(service, root, live["fiber"],
                            {"requires": [{"key": "p0"}]}, budget,
                            f"g2b-o-tu-{uuid4()}")
        service.commit()
        assert_owner_envelope(response)
        run_id, model_id = response["emitted"]
        token = claim_effect(service, model_id)
        settled, _ = settle(service, model_id, token, "success",
                            {"text": "call p0",
                             "tool_calls": [{"key": "p0", "args": {}}]})
        assert_owner_envelope(settled)
        assert len(settled["emitted"]) == 1, settled
        tool_id = settled["emitted"][0]
        run = run_row(owner, run_id)
        assert run["status"] == "running" and run["turn_no"] == 1, run
        assert run["remaining_tokens"] == 5000, run
        tool = effect_row(owner, tool_id)
        assert tool["status"] == "ready", tool
        held_pin_id = tool["pin_id"]
        token_tool = claim_effect(service, tool_id)
        cancelled, _ = cancel(service, run_id, 1, f"g2b-o-tu-c-{uuid4()}")
        service.commit()
        assert_owner_envelope(cancelled)
        assert cancelled["emitted"] == [], cancelled
        after_cancel = run_row(owner, run_id)
        assert after_cancel["status"] == "cancelled", after_cancel
        assert after_cancel["close_intent"]["kind"] == "cancel", after_cancel
        assert after_cancel["close_intent"]["generation"] == 1, after_cancel
        assert after_cancel["result"] is None, after_cancel
        assert after_cancel["turn_no"] == 1, after_cancel
        assert after_cancel["driving_generation"] == 2, after_cancel
        assert after_cancel["remaining_tokens"] == 5000, after_cancel
        held = effect_row(owner, tool_id)
        assert held["status"] == "claimed" and held["cancel_requested"] is True, held
        pin_before = next(item for item in run_pins(owner, run_id)
                          if item["pin_id"] == held_pin_id)
        assert pin_before["released_at"] is None, pin_before

        tokens_before = after_cancel["remaining_tokens"]
        steps_before = after_cancel["remaining_steps"]
        receipt = {"status": "error", "output": {"lost": True},
                   "usage": {"wall_ms": 9}}
        response, outcome = settle_tool(service, tool_id, token_tool,
                                        "unknown", receipt)
        assert_owner_envelope(response)
        assert response["emitted"] == [], response
        effect = effect_row(owner, tool_id)
        assert effect["status"] == "unknown", effect
        assert effect["outcome"] == outcome, effect
        assert effect["resource_quiesced_at"] is None, effect
        assert effect["settled_at"] is not None, effect
        assert effect["claim_owner"] is None and effect["lease_until"] is None, effect
        assert effect["cancel_requested"] is True, effect
        run = run_row(owner, run_id)
        assert run["status"] == "cancelled", run
        assert run["close_intent"] == after_cancel["close_intent"], run
        assert run["result"] is None, run
        assert run["turn_no"] == after_cancel["turn_no"] + 1, run
        assert run["remaining_tokens"] == tokens_before, run
        assert run["remaining_steps"] == steps_before, run
        assert run["interaction"] is None and run["pending_steer"] is None, run
        assert run["ended_at"] is not None, run
        assert event_kinds(owner, tool_id) == ["tool_call_unknown"], \
            event_kinds(owner, tool_id)
        unknown_events = events_of_kind(owner, run_id, "tool_call_unknown")
        assert len(unknown_events) == 1, unknown_events
        payload = unknown_events[0]["payload"]
        assert payload["late"] is True, payload
        assert payload["effect_id"] == tool_id, payload
        assert payload["turn_no"] == 2, payload
        assert read(owner, "SELECT count(*) FROM v24.events WHERE entity_id=%s "
                           "AND event_kind IN ('run_blocked_unknown',"
                           "'tool_batch_completed')", (run_id,)) == 0
        assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                           "AND kind='model_call'", (run_id,)) == 1
        assert read(owner, "SELECT count(*) FROM v24.effects WHERE effect_id=%s",
                    (md5_uuid(f"{model_id}:continuation"),)) == 0
        assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                           "AND kind='tool_call'", (run_id,)) == 1
        pin_after = next(item for item in run_pins(owner, run_id)
                         if item["pin_id"] == held_pin_id)
        assert pin_after["released_at"] is None, pin_after
        print("[G2b-O/tool-unknown] public start->claim->settle batch -> claim tool "
              "-> cancel(gen 1) -> settle tool class=unknown: effect unknown with "
              "byte-equal receipt and resource_quiesced NULL; run stays cancelled "
              "with close_intent kind='cancel'/gen 1 and result NULL; turn 2, tokens "
              "5000 unchanged, 0 successors/no continuation, own pin unreleased, "
              "events exactly [tool_call_unknown] (late=true), normal committed "
              "envelope")
    finally:
        service.close()


# ---------------------------------------------------------------------------
# S4 W5: pending_steer consumption (G2b-P/Q) and terminal pin release (G2b-R/S).

def steer_model_id(run_id, epoch, generation, instruction):
    """Mirror of v24.steer_model_effect_id:
    md5(run || ':steer_model:' || epoch || ':' || generation || ':' || md5(text))."""
    return md5_uuid(f"{run_id}:steer_model:{epoch}:{generation}:"
                    f"{hashlib.md5(instruction.encode()).hexdigest()}")


def pending_steer_consumption(db, owner):
    """G2b-P: claimed tool blocks the steer; its settlement consumes only the latest."""
    service = db.connect("service")
    try:
        budget = {"steps": 7, "tool_calls": 2, "tokens": 5000, "wall_ms": 600000}
        run_id, model_id = start_tool_run(owner, service, "g2b-p", ("p0",), budget)
        model1 = effect_row(owner, model_id)
        prior_input = model1["request"]["input"]
        tool_ids, _, _ = settle_tool_batch(owner, service, run_id, model_id, ("p0",))
        tool_id = tool_ids[0]
        token = claim_effect(service, tool_id)

        first, _ = steer(service, run_id, 1, "first steer", f"g2b-p-1-{uuid4()}")
        service.commit()
        assert_owner_envelope(first)
        assert first["emitted"] == [], first
        run = run_row(owner, run_id)
        assert run["pending_steer"] == {"instruction": "first steer", "generation": 2,
                                        "epoch": 2}, run
        assert run["driving_generation"] == 2 and run["epoch_no"] == 2, run
        assert run["status"] == "running", run
        assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                           "AND kind='model_call'", (run_id,)) == 1
        print("[G2b-P/steer1] claimed tool defers the steer: pending_steer="
              "{instruction:'first steer',generation:2,epoch:2}, 0 model "
              "successor, still exactly 1 model effect")

        second, _ = steer(service, run_id, 2, "latest steer", f"g2b-p-2-{uuid4()}")
        service.commit()
        assert_owner_envelope(second)
        assert second["emitted"] == [], second
        run = run_row(owner, run_id)
        assert run["pending_steer"] == {"instruction": "latest steer", "generation": 3,
                                        "epoch": 3}, run
        assert run["driving_generation"] == 3 and run["epoch_no"] == 3, run
        assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                           "AND kind='model_call'", (run_id,)) == 1
        print("[G2b-P/steer2] latest wins: pending_steer is overwritten to "
              "{instruction:'latest steer',generation:3,epoch:3} with 0 model "
              "successor")

        settled, _ = settle_tool(service, tool_id, token, "success",
                                 {"status": "ok", "output": {"p0": 1},
                                  "usage": {"wall_ms": 4}})
        assert_owner_envelope(settled)
        expected = steer_model_id(run_id, 3, 3, "latest steer")
        assert settled["emitted"] == [expected], (settled, expected)
        run = run_row(owner, run_id)
        assert run["pending_steer"] is None, run
        assert run["status"] == "running" and run["turn_no"] == 2, run
        assert run["remaining_steps"] == 5 and run["remaining_tokens"] == 904, run
        steer_effect = effect_row(owner, expected)
        assert steer_effect["kind"] == "model_call", steer_effect
        assert steer_effect["status"] == "ready", steer_effect
        assert steer_effect["parent_effect_id"] == tool_id, steer_effect
        assert steer_effect["ordinal"] == 0 and steer_effect["pin_id"] is None, steer_effect
        assert steer_effect["epoch_no"] == 3 and steer_effect["generation"] == 3, steer_effect
        assert steer_effect["request"] == {
            "v": 1, "cause": "steer", "run_id": run_id, "epoch_no": 3,
            "generation": 3, "input": prior_input, "instruction": "latest steer",
            "reserve": {"tokens": 4096}, "digests": model1["request"]["digests"]
        }, steer_effect["request"]
        consumed = events_of_kind(owner, run_id, "pending_steer_consumed")
        assert len(consumed) == 1, consumed
        assert consumed[0]["effect_id"] == tool_id, consumed
        assert consumed[0]["payload"]["model_effect_id"] == expected, consumed
        assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                           "AND kind='model_call'", (run_id,)) == 2
        assert read(owner, "SELECT count(*) FROM v24.effects WHERE effect_id=%s",
                    (md5_uuid(f"{model_id}:continuation"),)) == 0
        print("[G2b-P/consume] settling the last old-generation tool publishes "
              "exactly one cause='steer' model (epoch 3, generation 3, latest "
              "instruction, prior input, reserve 4096, same digests), clears "
              "pending, emits pending_steer_consumed and creates no old continuation")

        phase2_ids, _, _ = settle_tool_batch(owner, service, run_id, expected, ("p0",),
                                            text="phase two")
        tool2 = phase2_ids[0]
        token2 = claim_effect(service, tool2)
        third, _ = steer(service, run_id, 3, "third steer", f"g2b-p-3-{uuid4()}")
        service.commit()
        assert_owner_envelope(third) and third["emitted"] == [], third
        fourth, _ = steer(service, run_id, 4, "newest steer", f"g2b-p-4-{uuid4()}")
        service.commit()
        assert_owner_envelope(fourth) and fourth["emitted"] == [], fourth
        run = run_row(owner, run_id)
        assert run["pending_steer"] == {"instruction": "newest steer", "generation": 5,
                                        "epoch": 5}, run
        settled2, _ = settle_tool(service, tool2, token2, "success",
                                  {"status": "ok", "output": {"p0": 2},
                                   "usage": {"wall_ms": 6}})
        assert_owner_envelope(settled2)
        expected2 = steer_model_id(run_id, 5, 5, "newest steer")
        assert settled2["emitted"] == [expected2], (settled2, expected2)
        run = run_row(owner, run_id)
        assert run["pending_steer"] is None and run["status"] == "running", run
        steer_effect2 = effect_row(owner, expected2)
        assert steer_effect2["parent_effect_id"] == tool2, steer_effect2
        assert steer_effect2["request"]["instruction"] == "newest steer", steer_effect2
        assert steer_effect2["request"]["epoch_no"] == 5, steer_effect2
        assert steer_effect2["request"]["generation"] == 5, steer_effect2
        models = model_rows(owner, run_id)
        assert len(models) == 3, models
        assert {row["effect_id"] for row in models} == {model_id, expected, expected2}, models
        assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                           "AND effect_id IN (%s,%s)",
                    (run_id, md5_uuid(f"{model_id}:continuation"),
                     md5_uuid(f"{expected}:continuation"))) == 0
        assert len(events_of_kind(owner, run_id, "pending_steer_consumed")) == 2
        print("[G2b-P/second] a second claimed-tool settlement consumes only the "
              "newest of two further steers: a second cause='steer' model with "
              "epoch/generation 5 and instruction 'newest steer', 3 models total, "
              "0 inherited continuations")
    finally:
        service.close()


def pending_steer_unknown(db, owner):
    """G2b-Q: an old-generation unknown settlement walls the run, clears pending."""
    service = db.connect("service")
    try:
        budget = {"steps": 7, "tool_calls": 2, "tokens": 5000, "wall_ms": 600000}
        run_id, model_id = start_tool_run(owner, service, "g2b-q", ("q0",), budget)
        tool_ids, _, _ = settle_tool_batch(owner, service, run_id, model_id, ("q0",))
        tool_id = tool_ids[0]
        token = claim_effect(service, tool_id)
        steered, _ = steer(service, run_id, 1, "consume me", f"g2b-q-{uuid4()}")
        service.commit()
        assert_owner_envelope(steered)
        assert steered["emitted"] == [], steered
        assert run_row(owner, run_id)["pending_steer"]["instruction"] == "consume me"

        settled, receipt = settle_tool(
            service, tool_id, token, "unknown",
            {"status": "error", "output": {"lost": True}, "usage": {"wall_ms": 4}})
        assert_owner_envelope(settled)
        assert settled["emitted"] == [], settled
        tool = effect_row(owner, tool_id)
        assert tool["status"] == "unknown" and tool["outcome"] == receipt, tool
        assert tool["resource_quiesced_at"] is None, tool
        run = run_row(owner, run_id)
        assert run["status"] == "blocked_unknown", run
        assert run["pending_steer"] is None and run["interaction"] is None, run
        assert run["close_intent"]["kind"] == "unknown", run
        assert run["result"]["close_reason"] == "unknown", run
        assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                           "AND kind='model_call'", (run_id,)) == 1
        assert read(owner, "SELECT count(*) FROM v24.effects WHERE run_id=%s "
                           "AND kind='model_call' AND status IN ('ready','claimed')",
                    (run_id,)) == 0
        assert read(owner, "SELECT count(*) FROM v24.effects WHERE effect_id=%s",
                    (md5_uuid(f"{model_id}:continuation"),)) == 0
        assert events_of_kind(owner, run_id, "pending_steer_consumed") == []
        print("[G2b-Q] old-generation tool unknown: effect unknown with original "
              "receipt and resource_quiesced NULL, run blocked_unknown with "
              "close_reason='unknown', pending_steer cleared, 0 model successor, "
              "no continuation and no pending_steer_consumed event")
    finally:
        service.close()


def completed_pin_release(db, owner):
    """G2b-R: completing the run releases every run pin from the last settlement."""
    service = db.connect("service")
    try:
        keys = ("r0", "r1")
        budget = {"steps": 7, "tool_calls": 2, "tokens": 5000, "wall_ms": 600000}
        run_id, model_id = start_tool_run(owner, service, "g2b-r", keys, budget)
        tool_ids, _, pins = settle_tool_batch(owner, service, run_id, model_id, keys)
        assert len(pins) == 2 and all(pin["released_at"] is None for pin in pins.values())
        continuation = None
        for index, tool_id in enumerate(tool_ids):
            token = claim_effect(service, tool_id)
            response, _ = settle_tool(service, tool_id, token, "success",
                                      {"status": "ok", "output": {"i": index},
                                       "usage": {"wall_ms": 2}})
            assert_owner_envelope(response)
            if index == 0:
                assert response["emitted"] == [], response
                assert all(pin["released_at"] is None for pin in run_pins(owner, run_id))
            else:
                assert len(response["emitted"]) == 1, response
                continuation = response["emitted"][0]
        token = claim_effect(service, continuation)
        final, _ = settle(service, continuation, token, "success",
                          {"text": "done", "final": {"text": "done"},
                           "usage": {"tokens": 10, "wall_ms": 3}})
        assert_owner_envelope(final)
        assert final["emitted"] == [], final
        run = run_row(owner, run_id)
        assert run["status"] == "completed", run
        assert run["close_intent"] == {"kind": "final"}, run
        released = run_pins(owner, run_id)
        assert len(released) == 2, released
        for pin in released:
            assert pin["released_at"] is not None, pin
            assert pin["released_by_effect"] == continuation, (pin, continuation)
        assert read(owner, "SELECT v24.run_pin_release_set(%s,NULL,'completed',%s)",
                    (run_id, continuation)) == []
        print("[G2b-R] run completed by the final model settlement: both tool pins "
              f"released in that advance with released_by_effect={continuation}; "
              "the C22 release set is now empty")
    finally:
        service.close()


def settlement_pin_release(db, owner):
    """G2b-S: settlement-side pin release (batch-closing success and unknown)."""
    service = db.connect("service")
    try:
        # Part 1: a frozen final run is drained by the last tool success; the
        # completion and the pin release happen in the same advance.
        root, live, _ = loop_fixture(owner, service, realm="g2b-s-final",
                                     requires=("s0",))
        budget = {"steps": 4, "tool_calls": 2, "tokens": 5000, "wall_ms": 600000}
        response, _ = start(service, root, live["fiber"],
                            {"requires": [{"key": "s0"}]}, budget,
                            f"g2b-s-{uuid4()}")
        service.commit()
        assert_owner_envelope(response)
        run_id, model_id = response["emitted"]
        run = run_row(owner, run_id)
        pin = run_pins(owner, run_id)[0]
        tool_id = md5_uuid(f"{model_id}:tool_call:0")
        request = {"v": 1, "run_id": run_id, "epoch_no": run["epoch_no"],
                   "generation": run["driving_generation"], "ordinal": 0,
                   "key": pin["key"], "args": {},
                   "descriptor_digest": hexbyte(pin["descriptor_digest"]),
                   "batch_digest": batch_digest([tool_id])}
        with owner.cursor() as cur:
            insert(cur, "effects", effect_id=tool_id, parent_effect_id=model_id,
                   ordinal=0, requester_id=uuid4(), run_id=run_id,
                   pin_id=pin["pin_id"], epoch_no=run["epoch_no"],
                   generation=run["driving_generation"], kind="tool_call",
                   status="ready", request=Json(request), request_digest=DIGEST,
                   replay_policy="no_replay")
        owner.commit()
        token = claim_effect(service, model_id)
        frozen, _ = settle(service, model_id, token, "success",
                           {"text": "done", "final": {"text": "done"},
                            "usage": {"tokens": 40, "wall_ms": 5}})
        assert_owner_envelope(frozen)
        assert frozen["emitted"] == [], frozen
        assert run_row(owner, run_id)["status"] == "running"
        before_pin = run_pins(owner, run_id)[0]
        assert before_pin["released_at"] is None, before_pin
        assert before_pin["released_by_effect"] is None, before_pin
        token = claim_effect(service, tool_id)
        closed, _ = settle_tool(service, tool_id, token, "success",
                                {"status": "ok", "output": {"drain": 1},
                                 "usage": {"wall_ms": 3}})
        assert_owner_envelope(closed)
        assert closed["emitted"] == [], closed
        run = run_row(owner, run_id)
        assert run["status"] == "completed", run
        after_pin = run_pins(owner, run_id)[0]
        assert after_pin["pin_id"] == pin["pin_id"], after_pin
        assert after_pin["released_at"] is not None, after_pin
        assert after_pin["released_by_effect"] == tool_id, (after_pin, tool_id)
        completed = events_of_kind(owner, run_id, "run_completed")
        assert len(completed) == 1 and completed[0]["payload"]["close_reason"] == "final"
        print("[G2b-S/final] the last tool success closes the frozen final run and "
              "releases its pin in the same advance (released_by_effect = the "
              "settling tool effect), run_completed close_reason=final")

        # Part 2: an unknown tool keeps its own pin; every unreferenced pin of
        # the same run is released by that settlement.
        keys = ("s1", "s2")
        budget = {"steps": 7, "tool_calls": 2, "tokens": 5000, "wall_ms": 600000}
        run_id2, model_id2 = start_tool_run(owner, service, "g2b-s-unknown", keys, budget)
        tool_ids, _, _ = settle_tool_batch(owner, service, run_id2, model_id2, keys)
        token0 = claim_effect(service, tool_ids[0])
        token1 = claim_effect(service, tool_ids[1])
        ok_response, _ = settle_tool(service, tool_ids[0], token0, "success",
                                     {"status": "ok", "output": {"i": 0},
                                      "usage": {"wall_ms": 1}})
        assert_owner_envelope(ok_response)
        assert ok_response["emitted"] == [], ok_response
        unknown_response, _ = settle_tool(
            service, tool_ids[1], token1, "unknown",
            {"status": "error", "output": {"lost": True}, "usage": {"wall_ms": 2}})
        assert_owner_envelope(unknown_response)
        assert unknown_response["emitted"] == [], unknown_response
        run2 = run_row(owner, run_id2)
        assert run2["status"] == "blocked_unknown", run2
        pins_after = {pin["key"]: pin for pin in run_pins(owner, run_id2)}
        assert pins_after["s1"]["released_at"] is not None, pins_after
        assert pins_after["s1"]["released_by_effect"] == tool_ids[1], pins_after
        assert pins_after["s2"]["released_at"] is None, pins_after
        assert pins_after["s2"]["released_by_effect"] is None, pins_after
        print("[G2b-S/unknown] the unknown tool keeps its own pin (released_at "
              "NULL) while the settled sibling's pin is released in that same "
              "advance by the unknown settlement")
    finally:
        service.close()


def zero_write_negatives(db, owner):
    """G2b-T-1..T-10: ten named ten-table zero-write negatives.

    Nine are reached through the public claim/settlement API.  T-5 is a
    defensive duplicate-ordinal precheck in the INVOKER loop applier (the
    interpreter can only emit contiguous unique ordinals), and T-9 probes the
    frozen seal predicate itself: G2b-M covers the settlement-level behaviour
    (a final with a ready effect writes only close_intent, by design).
    """
    service = db.connect("service")
    budget = {"steps": 7, "tool_calls": 3, "tokens": 5000, "wall_ms": 600000}
    try:
        # T-1: a remaining non-member kind cannot be claimed.  inspect_resource
        # opened in S5 W2 (G2b-C matches claimable_kinds); its real claim→settle
        # positive lives in G4-N, not here.
        root, live, _ = loop_fixture(owner, service, realm="g2b-t1")
        effect_id = uuid4()
        seed_effect(owner, effect_id, kind="fiber_reconcile", status="ready",
                    fiber_id=live["fiber"])
        owner.commit()
        assert_claim_rejected(owner, service, effect_id, "G2b-T-1 fiber_reconcile")
        print("[G2b-T-1] remaining non-member fiber_reconcile claim: invalid_args, "
              "attempt/fence stay 0, ten-table byte-equal")

        # T-2: a settlement receipt without body.kind is structural W0.
        root, live, _ = loop_fixture(owner, service, realm="g2b-t2")
        response, _ = start(service, root, live["fiber"], {}, budget,
                            f"g2b-t2-{uuid4()}")
        service.commit()
        assert_owner_envelope(response)
        run_id, model_id = response["emitted"]
        token = claim_effect(service, model_id)
        before = snapshot(owner)
        missing_kind = {"v": 1, "class": "success", "claim": token,
                        "body": {"result": {}}}
        response = advance(service, model_id, missing_kind)
        service.commit()
        assert response == {"v": 1, "error": {"code": "invalid_outcome",
                                              "detail": {}}}, response
        assert snapshot(owner) == before, "missing body.kind wrote rows"
        assert effect_row(owner, model_id)["status"] == "claimed"
        print("[G2b-T-2] missing body.kind: invalid_outcome, effect stays claimed, "
              "ten-table byte-equal")

        # T-3: a model result with 17 tool_calls is structural W0 (max is 16).
        root, live, _ = loop_fixture(owner, service, realm="g2b-t3")
        response, _ = start(service, root, live["fiber"], {}, budget,
                            f"g2b-t3-{uuid4()}")
        service.commit()
        assert_owner_envelope(response)
        run_id, model_id = response["emitted"]
        token = claim_effect(service, model_id)
        before = snapshot(owner)
        seventeen = {"v": 1, "class": "success", "claim": token,
                     "body": {"kind": "model_call",
                              "result": {"tool_calls":
                                         make_tool_calls([f"k{i}" for i in range(17)])}}}
        response = advance(service, model_id, seventeen)
        service.commit()
        assert response == {"v": 1, "error": {"code": "invalid_outcome",
                                              "detail": {}}}, response
        assert snapshot(owner) == before, "17 tool_calls wrote rows"
        assert effect_row(owner, model_id)["status"] == "claimed"
        print("[G2b-T-3] 17 tool_calls: invalid_outcome, no partial batch, effect "
              "stays claimed, ten-table byte-equal")

        # T-4: a tool claim whose request key is not one of the live run pins.
        # The effect row is immutable after insert, so seed a second ready tool
        # at a free ordinal and bind it to the pin of a different key.
        run_id, model_id = start_tool_run(owner, service, "g2b-t4", ("t4",), budget)
        ids, _, _ = settle_tool_batch(owner, service, run_id, model_id, ("t4",))
        run = run_row(owner, run_id)
        pin = run_pins(owner, run_id)[0]
        tool_id = md5_uuid(f"{model_id}:tool_call:1")
        request = {"v": 1, "run_id": run_id, "epoch_no": run["epoch_no"],
                   "generation": run["driving_generation"], "ordinal": 1,
                   "key": "ghost-not-pinned", "args": {},
                   "descriptor_digest": hexbyte(pin["descriptor_digest"]),
                   "batch_digest": batch_digest([ids[0], tool_id])}
        with owner.cursor() as cur:
            insert(cur, "effects", effect_id=tool_id, parent_effect_id=model_id,
                   ordinal=1, requester_id=uuid4(), run_id=run_id,
                   pin_id=pin["pin_id"], epoch_no=run["epoch_no"],
                   generation=run["driving_generation"], kind="tool_call",
                   status="ready", request=Json(request), request_digest=DIGEST,
                   replay_policy="no_replay")
        owner.commit()
        before = snapshot(owner)
        response = advance(service, tool_id, claim())
        service.commit()
        assert response == {"v": 1, "error": {"code": "invalid_args",
                                              "detail": {}}}, response
        assert snapshot(owner) == before, "unpinned tool key wrote rows"
        print("[G2b-T-4] tool request key not in live run pins: claim invalid_args "
              "(C18 pin gate), ten-table byte-equal")

        # T-5: duplicate ordinal is a defensive applier precheck.  Reach it with a
        # real interpreted delta whose first successor is duplicated.
        run_id, model_id = start_tool_run(owner, service, "g2b-t5",
                                          ("t5a", "t5b"), budget)
        token = claim_effect(service, model_id)
        principal = one(service, "SELECT v24.principal_id(session_user)")
        service.commit()
        outcome = {"v": 1, "class": "success", "claim": token,
                   "body": {"kind": "model_call",
                            "result": {"text": "go",
                                       "tool_calls": make_tool_calls(("t5a", "t5b"))}}}
        delta = one(owner, "SELECT v24.interpret_model_settlement(%s,%s,%s,"
                           "'{}'::jsonb)", (model_id, principal, Json(outcome)))
        owner.commit()
        assert delta.get("error") is None and len(delta["successors"]) == 2, delta
        delta["successors"] = [delta["successors"][0], dict(delta["successors"][0])]
        before = snapshot(owner)
        refusal = one(owner, "SELECT v24.validate_and_apply_loop_delta(%s,%s,%s,%s,"
                             "'{}'::jsonb)", (model_id, principal, Json(outcome),
                                              Json(delta)))
        owner.commit()
        assert refusal == {"v": 1, "error": {"code": "invalid_outcome",
                                             "detail": {}}}, refusal
        assert snapshot(owner) == before, "duplicate ordinal wrote rows"
        print("[G2b-T-5] duplicate successor ordinal: defensive loop-applier "
              "precheck invalid_outcome, ten-table byte-equal")

        # T-6: a deterministic-id conflict at claim.  Seed a second ready tool at
        # a free ordinal whose effect id does not derive from (parent, ordinal).
        run_id, model_id = start_tool_run(owner, service, "g2b-t6", ("t6",), budget)
        ids, _, _ = settle_tool_batch(owner, service, run_id, model_id, ("t6",))
        run = run_row(owner, run_id)
        pin = run_pins(owner, run_id)[0]
        tool_id = str(uuid4())
        request = {"v": 1, "run_id": run_id, "epoch_no": run["epoch_no"],
                   "generation": run["driving_generation"], "ordinal": 1,
                   "key": "t6", "args": {},
                   "descriptor_digest": hexbyte(pin["descriptor_digest"]),
                   "batch_digest": batch_digest([ids[0], tool_id])}
        with owner.cursor() as cur:
            insert(cur, "effects", effect_id=tool_id, parent_effect_id=model_id,
                   ordinal=1, requester_id=uuid4(), run_id=run_id,
                   pin_id=pin["pin_id"], epoch_no=run["epoch_no"],
                   generation=run["driving_generation"], kind="tool_call",
                   status="ready", request=Json(request), request_digest=DIGEST,
                   replay_policy="no_replay")
        owner.commit()
        before = snapshot(owner)
        response = advance(service, tool_id, claim())
        service.commit()
        assert response == {"v": 1, "error": {"code": "invalid_args",
                                              "detail": {}}}, response
        assert snapshot(owner) == before, "deterministic-id conflict wrote rows"
        print("[G2b-T-6] deterministic-id conflict (effect id still derives from "
              "ordinal 0): claim invalid_args, ten-table byte-equal")

        # T-7: a stale claim token settles nothing.
        root, live, _ = loop_fixture(owner, service, realm="g2b-t7")
        response, _ = start(service, root, live["fiber"], {}, budget,
                            f"g2b-t7-{uuid4()}")
        service.commit()
        assert_owner_envelope(response)
        run_id, model_id = response["emitted"]
        token = claim_effect(service, model_id)
        wrong = dict(token, attempt=token["attempt"] + 1, fence=token["fence"] + 1)
        before = snapshot(owner)
        response = advance(service, model_id,
                           {"v": 1, "class": "success", "claim": wrong,
                            "body": {"kind": "model_call", "result": {"text": "x"}}})
        service.commit()
        assert response == {"v": 1, "error": {"code": "stale_claim",
                                              "detail": {}}}, response
        assert snapshot(owner) == before, "wrong token wrote rows"
        assert effect_row(owner, model_id)["status"] == "claimed"
        print("[G2b-T-7] wrong claim token: stale_claim, effect stays claimed, "
              "ten-table byte-equal")

        # T-8: an unknown receipt that tries to carry a successor is structurally
        # rejected; an unknown settlement never publishes successors.
        run_id, model_id = start_tool_run(owner, service, "g2b-t8", ("t8",), budget)
        ids, _, _ = settle_tool_batch(owner, service, run_id, model_id, ("t8",))
        tool_id = ids[0]
        token = claim_effect(service, tool_id)
        before = snapshot(owner)
        forged = {"v": 1, "class": "unknown", "claim": token,
                  "body": {"kind": "tool_call",
                           "result": {"status": "ok", "output": {},
                                      "successors": [{"effect_id": str(uuid4()),
                                                      "ordinal": 0}]}}}
        response = advance(service, tool_id, forged)
        service.commit()
        assert response == {"v": 1, "error": {"code": "invalid_args",
                                              "detail": {}}}, response
        assert snapshot(owner) == before, "unknown-with-successor wrote rows"
        assert effect_row(owner, tool_id)["status"] == "claimed"
        print("[G2b-T-8] unknown receipt carrying a successor: advance envelope "
              "guard invalid_args (class=unknown + nested successors), effect stays "
              "claimed, ten-table byte-equal")

        # T-9: a seal is refused while a ready business effect exists.  G2b-M is
        # the settlement-level counterpart (it writes only close_intent).
        root, live, _ = loop_fixture(owner, service, realm="g2b-t9", requires=("t9",))
        response, _ = start(service, root, live["fiber"],
                            {"requires": [{"key": "t9"}]}, budget,
                            f"g2b-t9-{uuid4()}")
        service.commit()
        assert_owner_envelope(response)
        run_id, model_id = response["emitted"]
        run = run_row(owner, run_id)
        pin = run_pins(owner, run_id)[0]
        tool_id = md5_uuid(f"{model_id}:tool_call:0")
        request = {"v": 1, "run_id": run_id, "epoch_no": run["epoch_no"],
                   "generation": run["driving_generation"], "ordinal": 0,
                   "key": pin["key"], "args": {},
                   "descriptor_digest": hexbyte(pin["descriptor_digest"]),
                   "batch_digest": batch_digest([tool_id])}
        with owner.cursor() as cur:
            insert(cur, "effects", effect_id=tool_id, parent_effect_id=model_id,
                   ordinal=0, requester_id=uuid4(), run_id=run_id,
                   pin_id=pin["pin_id"], epoch_no=run["epoch_no"],
                   generation=run["driving_generation"], kind="tool_call",
                   status="ready", request=Json(request), request_digest=DIGEST,
                   replay_policy="no_replay")
        owner.commit()
        token = claim_effect(service, model_id)
        settled, _ = settle(service, model_id, token, "success",
                            {"text": "done", "final": {"text": "done"},
                             "usage": {"tokens": 40, "wall_ms": 5}})
        assert_owner_envelope(settled)
        assert run_row(owner, run_id)["close_intent"] == {"kind": "final"}
        before = snapshot(owner)
        sealable = one(owner, "SELECT v24.loop_sealable(%s,%s,%s,NULL,NULL)",
                       (run_id, model_id, Json({"kind": "final"})))
        owner.commit()
        assert sealable is False, sealable
        assert snapshot(owner) == before, "refused seal wrote rows"
        assert read(owner, "SELECT count(*) FROM v24.events WHERE entity_id=%s "
                           "AND event_kind='run_completed'", (run_id,)) == 0
        print("[G2b-T-9] seal with a ready effect: loop_sealable=false, no "
              "run_completed, ten-table byte-equal")

        # T-10: a settlement on an already-blocked_unknown run is a W0 wall.
        keys = ("t10a", "t10b")
        run_id, model_id = start_tool_run(owner, service, "g2b-t10", keys, budget)
        ids, _, _ = settle_tool_batch(owner, service, run_id, model_id, keys)
        token0 = claim_effect(service, ids[0])
        token1 = claim_effect(service, ids[1])
        response, _ = settle_tool(service, ids[0], token0, "unknown",
                                  {"status": "error", "output": {"lost": True},
                                   "usage": {"wall_ms": 3}})
        assert_owner_envelope(response)
        assert run_row(owner, run_id)["status"] == "blocked_unknown"
        before = snapshot(owner)
        late, _ = settle_tool(service, ids[1], token1, "success",
                              {"status": "ok", "output": {}})
        assert late == {"v": 1, "error": {"code": "blocked_unknown",
                                          "detail": {}}}, late
        assert snapshot(owner) == before, "settlement on blocked_unknown wrote rows"
        print("[G2b-T-10] settlement on an already-blocked_unknown run: "
              "blocked_unknown, ten-table byte-equal")
    finally:
        service.close()


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
            tool_batch_spine(db, owner)
            tool_settlement_counters(db, owner)
            tool_batch_claims_and_guards(db, owner)
            tool_batch_settlement_order(db, owner)
            tool_call_budget(db, owner)
            interaction_production(db, owner)
            interaction_respond_chain(db, owner)
            tool_unknown_wall(db, owner)
            steps_budget_and_admission(db, owner)
            pending_final_seal(db, owner)
            cancel_t2_two_orders(db, owner)
            cancel_t2_tool_unknown(db, owner)
            pending_steer_consumption(db, owner)
            pending_steer_unknown(db, owner)
            completed_pin_release(db, owner)
            settlement_pin_release(db, owner)
            zero_write_negatives(db, owner)
            _assert_closed_catalog(owner)
    finally:
        restore_no_network()
    print("[passed] v24 S4 W1-W6")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
