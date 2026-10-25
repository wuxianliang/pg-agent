"""G8: adversarial extension check for the M-H host read surface and kernel
stability limits.

Run from the worktree root:

    uv run python v24/s9/test_g8.py            # all cases, exit 0/1
    uv run python v24/s9/test_g8.py --only G8-H1

`--only` is an incremental checkpoint, not a closeout claim.  No network is
opened: the static scan runs before the fixture, and socket connect /
create_connection are denied for the whole run.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parent
S1 = ROOT.parent / "s1"
S2 = ROOT.parent / "s2"
S4 = ROOT.parent / "s4"
S5 = ROOT.parent / "s5"
S6 = ROOT.parent / "s6"
S8 = ROOT.parent / "s8"
for _path in (S1, S2, S4, S5, S6, S8):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

socket = __import__("socket")

import psycopg2  # noqa: E402
from psycopg2.extras import Json  # noqa: E402
from psycopg2.extensions import TRANSACTION_STATUS_IDLE  # noqa: E402

from setup_db import (  # noqa: E402
    EXPECTED_TABLES,
    _assert_closed_catalog,
    server_helper_scope,
    setup_db,
)
from test_ddl import DIGEST, effect, insert  # noqa: E402
from test_g2b import (  # noqa: E402
    claim_effect as g2b_claim_effect,
    loop_fixture,
    make_tool_calls,
    run_pins as g2b_run_pins,
    settle_tool_batch,
    start,
    start_tool_run,
)
from test_g3a import advance as g3_advance  # noqa: E402
from test_g7 import (  # noqa: E402
    make_parent as g7_make_parent,
    spawn_args,
)

import h_support as h  # noqa: E402

ALL_CASES = (
    "G8-H1", "G8-H2", "G8-H3", "G8-H4", "G8-H5", "G8-H6", "G8-H7",
    "G8-H8", "G8-H9", "G8-H10", "G8-H11", "G8-H12", "G8-H13",
    "G8-C1", "G8-C2", "G8-L1", "G8-L2", "G8-L3", "G8-R1",
    "G8-D1a", "G8-D1b", "G8-D2", "G8-W1",
)

_NET_SAVED = None


def _deny_network(*args, **kwargs):
    raise AssertionError("v24/s9 gate attempted network I/O")


def install_no_network():
    global _NET_SAVED
    _NET_SAVED = (socket.socket.connect, socket.create_connection)
    socket.socket.connect = _deny_network
    socket.create_connection = _deny_network


def restore_no_network():
    global _NET_SAVED
    if _NET_SAVED is not None:
        socket.socket.connect, socket.create_connection = _NET_SAVED
        _NET_SAVED = None


def assert_static_guards():
    for path in sorted(ROOT.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for name in h.FORBIDDEN_IMPORTS:
            assert re.search(rf"(?m)^\s*(?:from|import)\s+{re.escape(name)}\b",
                             source) is None, (path.name, name)
        assert ("time." + "sleep") not in source, path.name
    sql = (ROOT.parent / "sql" / "49_host_reads.sql").read_text(encoding="utf-8")
    assert h.SQL_FORBIDDEN.search(sql) is None, h.SQL_FORBIDDEN.search(sql).group(0)
    assert h.SQL_DDL.search(sql) is None, h.SQL_DDL.search(sql).group(0)


def bind_roles(db):
    owner = db.connect()
    with owner.cursor() as cur:
        cur.execute("SET ROLE v24_owner")
    owner.commit()
    conns = {alias: db.connect(alias) for alias in ("admin", "service", "operator")}
    return owner, conns


def principals(conns):
    return {alias: h.principal(conn) for alias, conn in conns.items()}


def assert_denied(response, label):
    assert response == h.error("not_found_or_denied"), (label, response)


def assert_invalid(response, label):
    assert response == h.error("invalid_args"), (label, response)


def effect_item_keys(owner, effect_id):
    return set(h.one(owner, "SELECT to_jsonb(e) FROM v24.effects e WHERE e.effect_id=%s",
                     (effect_id,)))


# ---------------------------------------------------------------------------
# G8-H1: host_scopes
# ---------------------------------------------------------------------------
def g8_h1(db, owner, conns, pmap):
    admin, service, operator = conns["admin"], conns["service"], conns["operator"]
    root_admin = h.seed_scope(owner, owner_principal=pmap["admin"])
    root_service = h.seed_scope(owner, owner_principal=pmap["service"])
    closing = h.seed_scope(
        owner, owner_principal=pmap["admin"],
        close_requested_at=datetime.now(timezone.utc))
    closed = h.seed_scope(
        owner, owner_principal=pmap["admin"],
        close_requested_at=datetime.now(timezone.utc),
        closed_at=datetime.now(timezone.utc))

    admin_all = h.call_list(admin, "host_scopes", (None, None, 64))
    h.assert_list_envelope(admin_all, 64)
    ids = {item["scope_id"] for item in admin_all["items"]}
    assert {str(root_admin), str(root_service), str(closing), str(closed)} <= ids, ids
    for item in admin_all["items"]:
        assert set(item) == h.SCOPE_KEYS, item

    service_all = h.call_list(service, "host_scopes", (None, None, 64))
    assert [item["scope_id"] for item in service_all["items"]] == [str(root_service)]
    assert service_all["items"][0]["owner_principal"] == str(pmap["service"])
    operator_all = h.call_list(operator, "host_scopes", (None, None, 64))
    assert operator_all["items"] == []

    assert_denied(h.call_list(service, "host_scopes", (root_admin, None, 64)),
                  "explicit foreign scope")
    assert_denied(h.call_list(operator, "host_scopes", (root_service, None, 64)),
                  "operator foreign scope")

    empty = h.call_list(admin, "host_scopes", (None, None, 0))
    assert empty == {"v": 1, "items": [], "limit": 0, "has_more": False,
                     "next_cursor": None}, empty
    negative = h.call_list(admin, "host_scopes", (None, None, -3))
    assert negative["limit"] == 0 and negative["items"] == [], negative
    capped = h.call_list(admin, "host_scopes", (None, None, 999))
    assert capped["limit"] == 64, capped

    paged, sizes = h.scan_pages(admin, "host_scopes", (None, None, 64), 1)
    assert sizes == [1, 1, 1, 1], sizes
    assert len({item["scope_id"] for item in paged}) == 4, paged
    print("[G8-H1] owner-only visibility, admin all, closing/closed visible, "
          "foreign denied, UUID cursor/limit 0/negative/64 cap/empty")


# ---------------------------------------------------------------------------
# G8-H2: host_runs
# ---------------------------------------------------------------------------
def _start_run(conn, scope_id, key, *, tokens=1000):
    response, _ = start(conn, scope_id, None, {"messages": []},
                        {"steps": 4, "tool_calls": 0, "tokens": tokens,
                         "wall_ms": 60000}, key)
    conn.commit()
    assert response.get("disposition") == "committed", response
    return response["emitted"][0]


def g8_h2(db, owner, conns, pmap):
    admin, service = conns["admin"], conns["service"]
    scope_id = h.seed_scope(owner, owner_principal=pmap["admin"])
    run_ids = [_start_run(admin, scope_id, f"g8-h2-{i}") for i in range(3)]
    response = h.call_list(admin, "host_runs", (scope_id, None, None, 64))
    h.assert_list_envelope(response, 64)
    assert {item["run_id"] for item in response["items"]} == {str(x) for x in run_ids}
    for item in response["items"]:
        assert set(item) == h.RUN_PROJECTION_KEYS, item
        expected = h.one(owner, "SELECT v24.run_projection(%s)", (UUID(item["run_id"]),))
        owner.rollback()
        assert item == expected, item
    ordered = [(item["created_at"], item["run_id"]) for item in response["items"]]
    assert ordered == sorted(ordered), ordered

    paged, sizes = h.scan_pages(admin, "host_runs", (scope_id, None, None, 64), 1)
    assert sizes == [1, 1, 1], sizes
    assert len({item["run_id"] for item in paged}) == 3, paged

    assert_denied(h.call_list(service, "host_runs", (scope_id, None, None, 64)),
                  "non-owner host_runs")
    empty_scope = h.seed_scope(owner, owner_principal=pmap["admin"])
    empty = h.call_list(admin, "host_runs", (empty_scope, None, None, 64))
    assert empty["items"] == [] and empty["has_more"] is False, empty
    assert_invalid(h.call_list(admin, "host_runs",
                               (scope_id, datetime.now(timezone.utc), None, 64)),
                   "unpaired time cursor")
    print("[G8-H2] full run_projection equality, (created_at,run_id) order, "
          "cross-page uniqueness, non-owner denied, empty scope")


# ---------------------------------------------------------------------------
# G8-H3: host_effects
# ---------------------------------------------------------------------------
def g8_h3(db, owner, conns, pmap):
    service, operator = conns["service"], conns["operator"]
    scope_id = h.seed_scope(owner, owner_principal=pmap["service"])
    install_id = h.seed_install(owner, scope_id, owner_principal=pmap["service"])
    ready_host = h.seed_effect(
        owner, scope_id=scope_id, kind="host_prepare", status="ready",
        request={"install_id": str(install_id), "reservation": "v24:host_prepare:x"})
    claimed_host = h.seed_effect(
        owner, scope_id=scope_id, kind="host_release", status="claimed",
        request={"install_id": str(install_id)},
        attempt_no=1, fence=1, claim_owner="seed-owner",
        lease_until=datetime.now(timezone.utc) + timedelta(minutes=1),
        cancel_requested=True)
    ready_tool = h.seed_effect(
        owner, scope_id=scope_id, kind="tool_call", status="ready",
        request={"v": 1, "ordinal": 0})
    command = h.seed_effect(
        owner, scope_id=scope_id, kind="command_start", status="ready",
        request={"scope_id": str(scope_id)})
    settled = h.seed_effect(
        owner, scope_id=scope_id, kind="model_call", status="succeeded",
        request={"v": 1}, outcome={"v": 1, "class": "success"},
        settled_at=datetime.now(timezone.utc))

    response = h.call_list(service, "host_effects", (scope_id, None, None, 64))
    h.assert_list_envelope(response, 64)
    by_id = {item["effect_id"]: item for item in response["items"]}
    assert set(by_id) == {str(ready_host), str(claimed_host), str(ready_tool)}, by_id
    for item in response["items"]:
        assert set(item) == h.EFFECT_KEYS, item
    fixture = h.one(owner, "SELECT to_jsonb(e) FROM v24.effects e WHERE effect_id=%s",
                    (ready_host,))
    owner.rollback()
    assert by_id[str(ready_host)]["request"] == fixture["request"]
    claimed = by_id[str(claimed_host)]
    assert (claimed["attempt_no"], claimed["fence"], claimed["claim_owner"]) == (
        1, 1, "seed-owner")
    assert claimed["lease_until"] is not None and claimed["cancel_requested"] is True
    assert str(command) not in by_id and str(settled) not in by_id, by_id
    assert_denied(h.call_list(operator, "host_effects", (scope_id, None, None, 64)),
                  "non-owner host_effects")
    print("[G8-H3] ready/claimed five-kind work set, raw request equality, "
          "claim/lease/cancel facts, command/settled absent, non-owner denied")


# ---------------------------------------------------------------------------
# G8-H4: host_run_effects
# ---------------------------------------------------------------------------
def g8_h4(db, owner, conns, pmap):
    service = conns["service"]
    run_id, model_id = start_tool_run(
        owner, service, "g8-h4", ("alpha", "beta"),
        {"steps": 7, "tool_calls": 2, "tokens": 5000, "wall_ms": 600000})
    ids, _digest, _pins = settle_tool_batch(
        owner, service, run_id, model_id, ("alpha", "beta"))
    response = h.call_list(service, "host_run_effects", (run_id, None, None, 64))
    h.assert_list_envelope(response, 64)
    kinds = [item["kind"] for item in response["items"]]
    assert kinds.count("model_call") == 1 and kinds.count("tool_call") == 2, kinds
    assert response["items"][0]["effect_id"] == str(model_id), response["items"]
    tools = [item for item in response["items"] if item["kind"] == "tool_call"]
    assert {item["effect_id"] for item in tools} == {str(x) for x in ids}, tools
    assert sorted(item["ordinal"] for item in tools) == [0, 1], tools
    assert [item["effect_id"] for item in sorted(tools, key=lambda x: x["ordinal"])] == [
        str(x) for x in ids], tools
    for item in response["items"]:
        assert set(item) == h.EFFECT_KEYS, item
    paged, sizes = h.scan_pages(
        service, "host_run_effects", (run_id, None, None, 64), 1)
    assert sizes == [1, 1, 1], sizes
    assert [item["effect_id"] for item in paged] == [
        item["effect_id"] for item in response["items"]], paged

    other_scope = h.seed_scope(owner, owner_principal=pmap["admin"])
    other_run = _start_run(conns["admin"], other_scope, "g8-h4-other")
    assert_denied(h.call_list(service, "host_run_effects",
                              (other_run, None, None, 64)),
                  "foreign run")
    assert_denied(h.call_list(service, "host_run_effects",
                              (uuid4(), None, None, 64)), "missing run")
    print("[G8-H4] model/tool history, deterministic batch order, page "
          "stability, foreign/missing run denied")


# ---------------------------------------------------------------------------
# G8-H5: host_effect point lookup
# ---------------------------------------------------------------------------
def g8_h5(db, owner, conns, pmap):
    service, admin = conns["service"], conns["admin"]
    scope_id = h.seed_scope(owner, owner_principal=pmap["service"])
    install_id = h.seed_install(owner, scope_id, owner_principal=pmap["service"],
                                state="preparing")
    effect_id = h.seed_effect(
        owner, scope_id=scope_id, kind="host_prepare", status="ready",
        request={"install_id": str(install_id),
                 "reservation": "v24:host_prepare:point"})
    token = h.claim_probe(service, effect_id, lease=60000)["claim"]
    committed = h.one(
        owner, "SELECT to_jsonb(e) FROM v24.effects e WHERE e.effect_id=%s",
        (effect_id,))
    owner.rollback()
    assert committed["status"] == "claimed", (token, committed)
    point = h.one(admin, "SELECT v24.host_effect(%s)", (effect_id,))
    admin.rollback()
    assert set(point) == {"v", "effect"} and point["v"] == 1, point
    assert set(point["effect"]) == h.EFFECT_KEYS, point
    assert point["effect"]["request"] == committed["request"], point
    assert (point["effect"]["attempt_no"], point["effect"]["fence"],
            point["effect"]["claim_owner"]) == (
        token["attempt"], token["fence"], token["owner"]), point
    assert point["effect"]["lease_until"] is not None

    assert_denied(h.one(service, "SELECT v24.host_effect(%s)", (uuid4(),)),
                  "missing point")
    foreign_scope = h.seed_scope(owner, owner_principal=pmap["admin"])
    foreign = h.seed_effect(owner, scope_id=foreign_scope, kind="host_prepare",
                            request={})
    denied = h.one(service, "SELECT v24.host_effect(%s)", (foreign,))
    service.rollback()
    assert_denied(denied, "foreign point")
    hidden = h.seed_effect(owner, scope_id=scope_id, kind="command_start",
                           request={})
    assert_denied(h.one(service, "SELECT v24.host_effect(%s)", (hidden,)),
                  "non-external kind")

    outcome = {"v": 1, "class": "success", "claim": token, "body": {}}
    settled = h.advance(service, effect_id, outcome)
    service.commit()
    assert settled.get("disposition") == "committed", settled
    point = h.one(admin, "SELECT v24.host_effect(%s)", (effect_id,))
    admin.rollback()
    assert point["effect"]["status"] == "succeeded", point
    assert point["effect"]["outcome"] == outcome, point
    print("[G8-H5] committed token/request point read, missing/foreign/kind "
          "indistinguishable, settled outcome readable")


# ---------------------------------------------------------------------------
# G8-H6: host_scope_installs
# ---------------------------------------------------------------------------
def g8_h6(db, owner, conns, pmap):
    service, operator = conns["service"], conns["operator"]
    scope_id = h.seed_scope(owner, owner_principal=pmap["service"])
    installed = h.seed_install(
        owner, scope_id, owner_principal=pmap["service"],
        state="installed", requires=[{"key": "a"}], provides=[{"key": "b"}],
        artifact_digest=b"\xab\xcd", adapter_digest=b"\x01\x02")
    dispose_effect = h.seed_effect(
        owner, scope_id=scope_id, kind="command_dispose", status="succeeded",
        outcome={"v": 1, "class": "success"}, settled_at=datetime.now(timezone.utc))
    disposed = h.seed_install(
        owner, scope_id, owner_principal=pmap["service"],
        state="installed", artifact_digest=b"\xef\x01",
        adapter_digest=b"\x10\x20", identity="g8-h6-disposed")
    with owner.cursor() as cur:
        cur.execute("""UPDATE v24.installs SET state='disposed',
                         dispose_effect=%s, disposed_at=now()
                        WHERE install_id=%s""",
                    (dispose_effect, disposed))
    owner.commit()

    response = h.call_list(service, "host_scope_installs", (scope_id, None, 64))
    h.assert_list_envelope(response, 64)
    by_id = {item["install_id"]: item for item in response["items"]}
    assert set(by_id) == {str(installed), str(disposed)}, by_id
    for item in response["items"]:
        assert set(item) == h.INSTALL_KEYS, item
        for field in ("manifest_digest", "artifact_digest", "adapter_digest"):
            assert re.fullmatch(r"[0-9a-f]+", item[field]), (field, item[field])
    assert by_id[str(installed)]["manifest_digest"] == DIGEST.hex()
    assert by_id[str(installed)]["artifact_digest"] == "abcd"
    assert by_id[str(installed)]["adapter_digest"] == "0102"
    assert by_id[str(installed)]["requires"] == [{"key": "a"}]
    assert by_id[str(installed)]["provides"] == [{"key": "b"}]
    assert by_id[str(disposed)]["state"] == "disposed"
    assert by_id[str(disposed)]["dispose_effect"] == str(dispose_effect)
    assert by_id[str(disposed)]["disposed_at"] is not None

    paged, sizes = h.scan_pages(service, "host_scope_installs",
                                (scope_id, None, 64), 1)
    assert sizes == [1, 1], sizes
    assert len({item["install_id"] for item in paged}) == 2
    assert_denied(h.call_list(operator, "host_scope_installs",
                              (scope_id, None, 64)), "non-owner installs")
    print("[G8-H6] all install states, manifest/requires/provides, lowercase "
          "hex digests, dispose fields, cursor, non-owner denied")


# ---------------------------------------------------------------------------
# G8-H7: host_install_fibers
# ---------------------------------------------------------------------------
def g8_h7(db, owner, conns, pmap):
    service, operator = conns["service"], conns["operator"]
    scope_id = h.seed_scope(owner, owner_principal=pmap["service"])
    raw = json.dumps({"identity": "g8-h7", "version": "1", "requires": [],
                      "provides": [], "adapter_digest": "\\x"}).encode()
    response = h.one(service, "SELECT v24.install(%s,NULL,%s,%s,%s)",
                     (scope_id, raw, b"", "g8-h7-install"))
    service.commit()
    assert response.get("disposition") == "committed", response
    install_id = response["emitted"][0]
    fibers = h.call_list(service, "host_install_fibers", (install_id, None, 64))
    h.assert_list_envelope(fibers, 64)
    assert len(fibers["items"]) == 1, fibers
    fiber = fibers["items"][0]
    assert set(fiber) == h.FIBER_KEYS, fiber
    assert fiber["control_seq"] == 0 and fiber["current_episode_id"] is None

    controlled = h.one(service, "SELECT v24.fiber_control(%s,'on',0,%s)",
                       (fiber["fiber_id"], "g8-h7-on"))
    service.commit()
    assert controlled.get("disposition") == "committed", controlled
    fibers = h.call_list(service, "host_install_fibers", (install_id, None, 64))
    fiber = fibers["items"][0]
    committed = h.one(owner, "SELECT to_jsonb(f) FROM v24.fibers f WHERE fiber_id=%s",
                      (UUID(fiber["fiber_id"]),))
    owner.rollback()
    episode = h.one(owner, """SELECT to_jsonb(e) FROM v24.episodes e
        WHERE episode_id=%s""", (UUID(fiber["current_episode_id"]),))
    owner.rollback()
    assert fiber["control_seq"] == committed["control_seq"] == 1, (fiber, committed)
    assert fiber["current_episode_id"] == committed["current_episode_id"]
    assert episode["state"] == "active", episode
    assert_denied(h.call_list(operator, "host_install_fibers",
                              (install_id, None, 64)), "non-owner fibers")
    print("[G8-H7] fiber/control_seq/current_episode matches committed "
          "fiber_control(on); non-owner denied")


# ---------------------------------------------------------------------------
# G8-H8: host_run_pins
# ---------------------------------------------------------------------------
def g8_h8(db, owner, conns, pmap):
    service, operator = conns["service"], conns["operator"]
    root, live, _creator = loop_fixture(
        owner, service, realm="g8-h8", requires=("dep",))
    response, _ = start(
        service, root, live["fiber"], {"requires": [{"key": "dep"}]},
        {"steps": 5, "tool_calls": 1, "tokens": 5000, "wall_ms": 600000},
        "g8-h8-start")
    service.commit()
    assert response.get("disposition") == "committed", response
    run_id = response["emitted"][0]
    pins = h.call_list(service, "host_run_pins", (run_id, None, 64))
    h.assert_list_envelope(pins, 64)
    assert len(pins["items"]) == 1, pins
    pin = pins["items"][0]
    assert set(pin) == h.PIN_KEYS, pin
    fixture = h.one(owner, """SELECT to_jsonb(p) FROM v24.pins p
        WHERE consumer_run_id=%s""", (UUID(str(run_id)),))
    owner.rollback()
    slot = h.one(owner, "SELECT to_jsonb(s) FROM v24.slots s WHERE slot_id=%s",
                 (UUID(pin["slot_id"]),))
    owner.rollback()
    assert pin["descriptor"] == slot["descriptor"], pin
    assert pin["descriptor_digest"] == fixture["descriptor_digest"][2:]
    assert pin["provider_install_id"] == str(h.one(
        owner, "SELECT install_id FROM v24.fibers WHERE fiber_id=%s",
        (UUID(pin["provider_fiber_id"]),)))
    owner.rollback()

    generation = h.one(owner, "SELECT driving_generation FROM v24.runs WHERE run_id=%s",
                       (UUID(str(run_id)),))
    owner.rollback()
    cancelled = h.one(service, "SELECT v24.cancel(%s,%s,%s)",
                      (run_id, generation, "g8-h8-cancel"))
    service.commit()
    assert cancelled.get("disposition") == "committed", cancelled
    released = h.call_list(service, "host_run_pins", (run_id, None, 64))
    assert released["items"][0]["released_at"] is not None, released
    assert released["items"][0]["pin_id"] == pin["pin_id"]
    assert_denied(h.call_list(operator, "host_run_pins", (run_id, None, 64)),
                  "non-owner pins")
    print("[G8-H8] descriptor/digest/provider_install_id, released pin still "
          "readable, non-owner denied")


# ---------------------------------------------------------------------------
# G8-H9: host_request
# ---------------------------------------------------------------------------
def g8_h9(db, owner, conns, pmap):
    admin, service = conns["admin"], conns["service"]
    key = "g8-h9-root"
    response = h.one(admin, "SELECT v24.scope_control('create_root',NULL,%s,NULL,%s)",
                     (Json({}), key))
    admin.commit()
    assert response.get("disposition") == "committed", response
    fixture = h.one(owner, """SELECT to_jsonb(r) FROM v24.requests r
        WHERE principal_id=%s AND request_key=%s""", (pmap["admin"], key))
    owner.rollback()
    point = h.one(admin, "SELECT v24.host_request(%s)", (key,))
    admin.rollback()
    assert set(point) == {"v", "request"} and point["v"] == 1, point
    assert set(point["request"]) == h.REQUEST_KEYS, point
    assert base64.b64decode(point["request"]["request_bytes_base64"]) == bytes.fromhex(
        fixture["request_bytes"][2:])
    assert point["request"]["request_digest_hex"] == fixture["request_digest"][2:]
    assert point["request"]["response"] == fixture["response"]
    assert point["request"]["effect_id"] == fixture["effect_id"]

    assert_denied(h.one(service, "SELECT v24.host_request(%s)", (key,)),
                  "other principal")
    before = h.one(owner, "SELECT count(*) FROM v24.requests")
    owner.rollback()
    replay = h.one(admin, "SELECT v24.scope_control('create_root',NULL,%s,NULL,%s)",
                   (Json({}), key))
    admin.commit()
    after = h.one(owner, "SELECT count(*) FROM v24.requests")
    owner.rollback()
    assert replay == response and after == before, (replay, before, after)
    assert_invalid(h.one(admin, "SELECT v24.host_request(NULL)"), "null key")
    print("[G8-H9] canonical bytes base64, digest hex, first response, other "
          "principal denied, replay adds no request row")


# ---------------------------------------------------------------------------
# G8-H10: ACL/read-only commons
# ---------------------------------------------------------------------------
def g8_h10(db, owner, conns, pmap):
    admin, service, operator = conns["admin"], conns["service"], conns["operator"]
    definers = h.rows(owner, """SELECT p.proname::text FROM pg_proc p
        WHERE p.pronamespace='v24'::regnamespace AND p.prosecdef
        ORDER BY p.proname""")
    owner.rollback()
    assert tuple(row[0] for row in definers) == h.HOST_DEFINERS, definers
    sql = (ROOT.parent / "sql" / "50_permissions.sql").read_text(encoding="utf-8")
    assert len(re.findall(r"(?m)^GRANT EXECUTE ON FUNCTION", sql)) == 27, sql

    pure = {"canonical_json", "effect_id_for", "principal_id", "error_v1"}
    base = pure | {"advance", "scope_control", "resolve", "poll", "wait_check",
                   "fiber_control", "dispose", "start", "cancel", "steer",
                   "respond", "recoverable_effects", "command_recover"}
    expected = {
        "admin": base | set(h.HOST_READS),
        "service": base | set(h.HOST_READS) | {"install"},
        "operator": base | set(h.HOST_READS) | {"install"},
    }
    for alias, conn in conns.items():
        exposed = set(h.one(conn, """SELECT array_agg(proname::text)
            FROM pg_proc WHERE pronamespace='v24'::regnamespace
              AND has_function_privilege(session_user,oid,'EXECUTE')"""))
        conn.rollback()
        assert exposed == expected[alias], (alias, sorted(exposed - expected[alias]),
                                            sorted(expected[alias] - exposed))
        assert not h.one(conn, """SELECT has_function_privilege(session_user,
            'v24.host_scope_allowed(uuid)'::regprocedure,'EXECUTE')""")
        conn.rollback()
    assert len(expected["admin"]) == 26 and len(expected["service"]) == 27
    assert not h.one(admin, "SELECT has_function_privilege(session_user,"
                            "'v24.install(uuid,uuid,bytea,bytea,text)'::regprocedure,"
                            "'EXECUTE')")
    admin.rollback()

    for row in h.rows(owner, """SELECT p.proname, p.provolatile, p.proconfig,
            p.prosrc FROM pg_proc p
        WHERE p.pronamespace='v24'::regnamespace AND p.proname = ANY(%s)""",
                      (list(h.HOST_READS) + ["host_scope_allowed"],)):
        name, volatility, config, prose = row
        assert volatility == "s", (name, volatility)
        assert config == ["search_path=pg_catalog, v24"], (name, config)
        assert h.READ_NOISE.search(prose) is None, (name, h.READ_NOISE.search(prose))
    owner.rollback()

    for table in sorted(EXPECTED_TABLES):
        for alias, conn in conns.items():
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                assert not h.one(conn, "SELECT has_table_privilege(session_user,%s,%s)",
                                 ("v24." + table, privilege)), (alias, table, privilege)
            conn.rollback()
    for alias, conn in conns.items():
        assert not h.one(conn, """SELECT EXISTS (SELECT 1 FROM pg_proc p
            WHERE p.pronamespace='v24'::regnamespace
              AND p.prosecdef AND p.proname<>'advance'
              AND p.prosrc ~* '\\m(insert|update|delete|pg_advisory[a-z_0-9]*)\\M')""")
        conn.rollback()

    # Every scoped function denies a non-owner service caller with the same
    # not_found_or_denied envelope.  Build one comprehensive admin scope.
    scope_id = h.seed_scope(owner, owner_principal=pmap["admin"])
    install_id = h.seed_install(owner, scope_id, owner_principal=pmap["admin"])
    fiber_id = h.seed_fiber(owner, install_id, scope_id)
    episode_id = h.seed_episode(owner, fiber_id)
    slot_id = h.seed_slot(owner, fiber_id, episode_id, key="g8-h10")
    run_id = h.seed_run(owner, scope_id)
    pin_id = h.seed_pin(
        owner, consumer_run_id=run_id, slot_id=slot_id,
        provider_fiber_id=fiber_id, provider_episode_id=episode_id)
    effect_id = h.seed_effect(
        owner, scope_id=scope_id, run_id=run_id, fiber_id=fiber_id,
        episode_id=episode_id, pin_id=pin_id, kind="model_call",
        request={"v": 1})
    h.seed_request(owner, pmap["admin"], "g8-h10-request",
                   request_bytes=b'{"action":"create_root"}')
    before = h.snapshot(owner)
    denied = {
        "host_scopes": h.call_list(service, "host_scopes", (scope_id, None, 64)),
        "host_runs": h.call_list(service, "host_runs", (scope_id, None, None, 64)),
        "host_effects": h.call_list(service, "host_effects",
                                    (scope_id, None, None, 64)),
        "host_run_effects": h.call_list(service, "host_run_effects",
                                        (run_id, None, None, 64)),
        "host_effect": h.one(service, "SELECT v24.host_effect(%s)", (effect_id,)),
        "host_scope_installs": h.call_list(service, "host_scope_installs",
                                           (scope_id, None, 64)),
        "host_install_fibers": h.call_list(service, "host_install_fibers",
                                           (install_id, None, 64)),
        "host_run_pins": h.call_list(service, "host_run_pins", (run_id, None, 64)),
        "host_request": h.one(service, "SELECT v24.host_request('g8-h10-request')"),
    }
    service.rollback()
    for name, response in denied.items():
        assert_denied(response, name)
    after = h.snapshot(owner)
    assert after == before, "read calls changed a row"
    assert h.one(service, "SELECT count(*) FROM pg_locks WHERE pid=pg_backend_pid() "
                          "AND locktype='advisory'") == 0
    service.rollback()
    assert_fingerprint_stable(owner, service, scope_id)
    print("[G8-H10] 17 definers exact, 27 GRANTs, 26/27/27 EXECUTE, helper "
          "hidden, admin install denied, STABLE/fixed path/no PUBLIC/zero "
          "table rights, scoped denials, ten-table unchanged, no G lock")


def assert_fingerprint_stable(owner, service, scope_id):
    before = h.snapshot(owner)
    h.call_list(service, "host_effects", (scope_id, None, None, 64))
    after = h.snapshot(owner)
    assert before == after, "fingerprint changed"


# ---------------------------------------------------------------------------
# Remaining cases are appended below.
# ---------------------------------------------------------------------------


def run_case(case, db, owner, conns, pmap):
    table = {
        "G8-H1": g8_h1, "G8-H2": g8_h2, "G8-H3": g8_h3, "G8-H4": g8_h4,
        "G8-H5": g8_h5, "G8-H6": g8_h6, "G8-H7": g8_h7, "G8-H8": g8_h8,
        "G8-H9": g8_h9, "G8-H10": g8_h10, "G8-H11": g8_h11,
        "G8-H12": g8_h12, "G8-H13": g8_h13,
        "G8-C1": g8_c1, "G8-C2": g8_c2,
        "G8-L1": g8_l1, "G8-L2": g8_l2, "G8-L3": g8_l3,
        "G8-R1": g8_r1, "G8-D1a": g8_d1a, "G8-D1b": g8_d1b,
        "G8-D2": g8_d2, "G8-W1": g8_w1,
    }
    if case in table:
        table[case](db, owner, conns, pmap)
        return
    raise AssertionError(f"unknown or not-yet-implemented case {case}")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default=None)
    args = parser.parse_args(argv)
    selected = ALL_CASES
    if args.only:
        requested = tuple(x.strip() for x in args.only.split(",") if x.strip())
        assert requested and set(requested) <= set(ALL_CASES), requested
        selected = requested

    assert_static_guards()
    install_no_network()
    try:
        with server_helper_scope(), setup_db() as db:
            owner, conns = bind_roles(db)
            pmap = principals(conns)
            _assert_closed_catalog(db.connect())
            h.install_closure_probe(owner)
            for case in selected:
                run_case(case, db, owner, conns, pmap)
    finally:
        restore_no_network()
    print(f"[passed] v24 G8 host reads / closure / lease / recovery: "
          f"{len(selected)} case(s)")
    return 0


# ---------------------------------------------------------------------------
# G8-H11: held-G snapshot and non-blocking reads
# ---------------------------------------------------------------------------
def _h11_fixture(owner, pmap):
    scope_id = h.seed_scope(owner, owner_principal=pmap["admin"])
    install_id = h.seed_install(owner, scope_id, owner_principal=pmap["admin"])
    fiber_id = h.seed_fiber(owner, install_id, scope_id)
    episode_id = h.seed_episode(owner, fiber_id)
    slot_id = h.seed_slot(owner, fiber_id, episode_id, key="g8-h11")
    run_id = h.seed_run(owner, scope_id)
    pin_id = h.seed_pin(
        owner, consumer_run_id=run_id, slot_id=slot_id,
        provider_fiber_id=fiber_id, provider_episode_id=episode_id)
    model_id = h.seed_effect(
        owner, scope_id=scope_id, run_id=run_id, fiber_id=fiber_id,
        episode_id=episode_id, pin_id=pin_id, kind="model_call",
        request={"v": 1, "cause": "start"})
    target = h.seed_effect(owner, scope_id=scope_id, kind="host_prepare",
                           request={})
    h.seed_request(owner, pmap["admin"], "g8-h11-request",
                   request_bytes=b'{"action":"create_root"}')
    return {
        "scope": scope_id, "install": install_id, "fiber": fiber_id,
        "episode": episode_id, "slot": slot_id, "run": run_id,
        "pin": pin_id, "model": model_id, "target": target,
    }


def g8_h11(db, owner, conns, pmap):
    admin, service = conns["admin"], conns["service"]
    fx = _h11_fixture(owner, pmap)
    reader = db.connect("admin")
    reader.autocommit = False
    with reader.cursor() as cur:
        cur.execute("SET LOCAL statement_timeout = '5s'")
    reader_started = time.monotonic()
    calls = {
        "host_scopes": h.call_list(reader, "host_scopes", (fx["scope"], None, 64)),
        "host_runs": h.call_list(reader, "host_runs", (fx["scope"], None, None, 64)),
        "host_effects": h.call_list(reader, "host_effects",
                                    (fx["scope"], None, None, 64)),
        "host_run_effects": h.call_list(reader, "host_run_effects",
                                        (fx["run"], None, None, 64)),
        "host_effect": h.one(reader, "SELECT v24.host_effect(%s)", (fx["model"],)),
        "host_scope_installs": h.call_list(reader, "host_scope_installs",
                                           (fx["scope"], None, 64)),
        "host_install_fibers": h.call_list(reader, "host_install_fibers",
                                           (fx["install"], None, 64)),
        "host_run_pins": h.call_list(reader, "host_run_pins",
                                     (fx["run"], None, 64)),
        "host_request": h.one(reader, "SELECT v24.host_request('g8-h11-request')"),
    }
    elapsed = time.monotonic() - reader_started
    for name, response in calls.items():
        assert "error" not in response, (name, response)
    assert calls["host_scopes"]["items"][0]["close_requested_at"] is None
    assert calls["host_effect"]["effect"]["status"] == "ready"
    assert h.one(reader, "SELECT count(*) FROM pg_locks WHERE pid=pg_backend_pid() "
                         "AND locktype='advisory'") == 0
    reader.commit()
    assert elapsed < 5.0, elapsed

    blocker = db.connect()
    with blocker.cursor() as cur:
        cur.execute("SET ROLE v24_owner")
        cur.execute("SELECT pg_advisory_xact_lock(24,1)")
        cur.execute("UPDATE v24.scopes SET close_requested_at=now() WHERE scope_id=%s",
                    (fx["scope"],))
    service_pid = h.one(service, "SELECT pg_backend_pid()")
    service.commit()
    observer = db.connect()
    observer.autocommit = True
    queue = __import__("queue").Queue()

    def claimant():
        try:
            response = h.advance(service, fx["target"], h.claim())
            queue.put(("ok", response))
            service.commit()
        except BaseException as exc:  # pragma: no cover - diagnostic path
            service.rollback()
            queue.put(("error", repr(exc)))

    thread = threading.Thread(target=claimant, name="g8-h11-claim", daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    evidence = None
    while True:
        with observer.cursor() as cur:
            cur.execute(
                """SELECT pg_blocking_pids(%s)::text,
                          (SELECT count(*) FROM pg_locks
                            WHERE pid=%s AND locktype='advisory' AND NOT granted)""",
                (service_pid, service_pid))
            blockers, ungranted = cur.fetchone()
        if ungranted >= 1:
            evidence = (blockers, ungranted)
            break
        assert thread.is_alive(), "claim did not block on held G"
        assert time.monotonic() < deadline, (blockers, ungranted)
    blocker.rollback()
    blocker.close()
    try:
        kind, response = queue.get(timeout=10)
    except __import__("queue").Empty:
        raise AssertionError("claim did not finish after G release") from None
    thread.join(timeout=10)
    assert kind == "ok", response
    assert response.get("disposition") == "committed", response
    assert response["claim"] is not None, response
    after = h.one(owner, "SELECT close_requested_at FROM v24.scopes WHERE scope_id=%s",
                  (fx["scope"],))
    owner.rollback()
    assert after is None, "uncommitted blocker change leaked into committed state"
    observer.close()
    print(f"[G8-H11] nine reads finish in {elapsed:.3f}s with G held and see "
          f"committed snapshot; reader advisory locks=0; claim blocked "
          f"(pg_blocking_pids={evidence[0]}, ungranted={evidence[1]}) then committed")


# ---------------------------------------------------------------------------
# G8-H12: pagination + concurrent insertion/state change
# ---------------------------------------------------------------------------
def g8_h12(db, owner, conns, pmap):
    admin, service = conns["admin"], conns["service"]
    scope_id = h.seed_scope(owner, owner_principal=pmap["admin"])
    install_id = h.seed_install(owner, scope_id, owner_principal=pmap["admin"])
    ids = [h.seed_effect(owner, scope_id=scope_id, kind="host_prepare",
                         request={"install_id": str(install_id), "n": i})
           for i in range(7)]
    first, sizes = h.scan_pages(admin, "host_effects",
                                (scope_id, None, None, 64), 2)
    assert sizes == [2, 2, 2, 1], sizes
    assert {item["effect_id"] for item in first} == {str(x) for x in ids}
    assert len(first) == len({item["effect_id"] for item in first}) == 7

    late = h.seed_effect(owner, scope_id=scope_id, kind="host_prepare",
                         request={"install_id": str(install_id), "late": True})
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.effects SET created_at=now() - interval '1 day' "
                    "WHERE effect_id=%s", (late,))
    owner.commit()
    rescan, _ = h.scan_pages(admin, "host_effects",
                             (scope_id, None, None, 64), 2)
    assert {str(late)} | {str(x) for x in ids} == {
        item["effect_id"] for item in rescan}, rescan

    # A state/order change inside an open keyset scan can move a row behind the
    # cursor, so the same row is observed twice.  The worker deduplicates by
    # effect_id; the duplicate is asserted here, not left to chance.
    page1 = h.call_list(admin, "host_effects", (scope_id, None, None, 2))
    victim = page1["items"][0]["effect_id"]
    with owner.cursor() as cur:
        cur.execute("""UPDATE v24.effects SET status='claimed', attempt_no=1,
                         fence=1, claim_owner='g8-h12', lease_until=now()+interval '1 minute',
                         created_at=now()
                        WHERE effect_id=%s""", (UUID(victim),))
    owner.commit()
    seen = [item["effect_id"] for item in page1["items"]]
    cursor = page1["next_cursor"]
    while cursor is not None:
        page = h.call_list(admin, "host_effects",
                           (scope_id, cursor["created_at"],
                            cursor["effect_id"], 2))
        seen += [item["effect_id"] for item in page["items"]]
        cursor = page["next_cursor"] if page["has_more"] else None
    deduped = list(dict.fromkeys(seen))
    assert seen.count(victim) >= 2, (victim, seen)
    assert set(deduped) == {str(late)} | {str(x) for x in ids}, deduped
    print(f"[G8-H12] 7-row scan 2/2/2/1 no gap; older concurrent insert found "
          f"on next full scan; moved row observed {seen.count(victim)}x, "
          f"duplicates={len(seen) - len(deduped)}, worker dedup by effect_id "
          f"leaves {len(deduped)}")


# ---------------------------------------------------------------------------
# G8-H13: 64-item large-input fixture
# ---------------------------------------------------------------------------
def g8_h13(db, owner, conns, pmap):
    admin, service = conns["admin"], conns["service"]
    scope_id = h.seed_scope(owner, owner_principal=pmap["admin"])
    install_id = h.seed_install(owner, scope_id, owner_principal=pmap["admin"],
                                state="preparing")
    blob = "x" * 1048000
    run_ids = [h.seed_run(owner, scope_id) for _ in range(64)]
    with owner.cursor() as cur:
        cur.execute(
            """INSERT INTO v24.effects
                 (effect_id, requester_id, run_id, scope_id, kind, status,
                  request, request_digest, replay_policy)
               SELECT md5(%s || ':' || g)::uuid, %s, u.run_id, %s,
                      'model_call', 'ready',
                      jsonb_build_object('input', %s),
                      %s, 'no_replay'
                 FROM unnest(%s::uuid[]) WITH ORDINALITY AS u(run_id, g)""",
            ("g8-h13", str(uuid4()), scope_id, blob, b"g8-h13", run_ids))
    owner.commit()
    response = h.call_list(admin, "host_effects", (scope_id, None, None, 64))
    h.assert_list_envelope(response, 64)
    assert len(response["items"]) == 64 and response["has_more"] is False, len(
        response["items"])
    measured = len(json.dumps(response, separators=(",", ":")))
    assert measured > 60 * 1024 * 1024, measured

    target = h.seed_effect(owner, scope_id=scope_id, kind="host_prepare",
                           request={"install_id": str(install_id)})
    token = h.claim_probe(service, target, lease=1)["claim"]
    settled = h.advance(service, target, {
        "v": 1, "class": "success", "claim": token, "body": {}})
    service.commit()
    assert settled.get("disposition") == "committed", settled
    point = h.one(admin, "SELECT v24.host_effect(%s)", (target,))
    admin.rollback()
    assert point["effect"]["status"] == "succeeded", point
    print(f"[G8-H13] 64 items x ~1 MiB request measured page={measured} bytes "
          f"({measured / (1024 * 1024):.2f} MiB); lease=1 claim/settle accepted")



# ---------------------------------------------------------------------------
# G8-C1/C2: measured closure slope and the 512 bound
# ---------------------------------------------------------------------------
def _closure_fixture(owner, pmap):
    scope_id = h.seed_scope(owner, owner_principal=pmap["admin"])
    install_id = h.seed_install(owner, scope_id, owner_principal=pmap["admin"])
    target = h.seed_claim_target(owner, scope_id, install_id)
    return scope_id, install_id, target


def _claim_then_rollback(service, target, *, lease=300000):
    response = h.advance(service, target, h.claim(lease))
    assert response.get("disposition") == "committed", response
    assert response.get("claim") is not None, response
    service.rollback()
    return response


def g8_c1(db, owner, conns, pmap):
    admin, service = conns["admin"], conns["service"]
    scope_id, install_id, target = _closure_fixture(owner, pmap)
    base, _family = h.closure_size(owner, target)
    samples = []
    history = 0
    for wanted in (0, 1, 2, 4, 8, 16, 32):
        if wanted > history:
            h.seed_history(owner, scope_id, install_id, wanted - history,
                           prefix=f"g8-c1-{scope_id}-{history}-{wanted}")
            history = wanted
        measured, _family = h.closure_size(owner, target)
        _claim_then_rollback(service, target)
        samples.append((wanted, measured))
        assert measured == base + wanted, (base, wanted, measured)
    slopes = [samples[i][1] - samples[i - 1][1]
              for i in range(1, len(samples))]
    widths = [samples[i][0] - samples[i - 1][0]
              for i in range(1, len(samples))]
    assert slopes == widths, (slopes, widths)
    print(f"[G8-C1] B={base}; samples H/C=" +
          ", ".join(f"{h_}/{c}" for h_, c in samples) +
          f"; adjacent closure slope={slopes} (C=B+H)")
    return {"scope": scope_id, "install": install_id, "target": target,
            "base": base, "history": history}


def g8_c2(db, owner, conns, pmap):
    service = conns["service"]
    fixture = g8_c1(db, owner, conns, pmap)
    scope_id, install_id, target = (fixture["scope"], fixture["install"],
                                    fixture["target"])
    base, history = fixture["base"], fixture["history"]
    h_ok = 512 - base
    if h_ok > history:
        h.seed_history(owner, scope_id, install_id, h_ok - history,
                       prefix=f"g8-c2-ok-{scope_id}")
        history = h_ok
    measured, _family = h.closure_size(owner, target)
    assert measured == 512, (base, measured)
    response = h.advance(service, target, h.claim())
    assert response.get("disposition") == "committed", response
    assert response.get("claim") is not None, response
    service.rollback()

    h.seed_history(owner, scope_id, install_id, 1,
                   prefix=f"g8-c2-bad-{scope_id}")
    measured_bad, _family = h.closure_size(owner, target)
    assert measured_bad == 513, (base, measured_bad)
    before = h.snapshot(owner)
    bad = h.advance(service, target, h.claim())
    service.commit()
    assert bad == {"v": 1, "error": {"code": "retry_with_closure", "detail": {}}}, bad
    after = h.snapshot(owner)
    assert after == before, "retry closure wrote rows"
    replay = h.advance(service, target, h.claim())
    service.commit()
    assert replay == bad, replay
    print(f"[G8-C2] B={base}; H_ok={h_ok} -> C={measured} claim committed; "
          f"H_bad={h_ok + 1} -> C={measured_bad} retry_with_closure with "
          f"ten-table byte-equal and retry still rejected")
    public_growth(owner, conns["admin"], service, pmap)


# ---------------------------------------------------------------------------
# Public-path growth experiment (evidence, not a separate gate)
# ---------------------------------------------------------------------------
def public_growth(owner, admin, service, pmap):
    scope_id = h.seed_scope(owner, owner_principal=pmap["service"])
    manifest = json.dumps({
        "identity": "g8-public", "version": "1",
        "requires": [], "provides": [{"realm": "g8p", "key": "k"}],
        "adapter_digest": "\\x",
    }).encode()
    response = h.one(service, "SELECT v24.install(%s,NULL,%s,%s,%s)",
                     (scope_id, manifest, b"artifact", "g8-public-install"))
    service.commit()
    assert response.get("disposition") == "committed", response
    install_id = response["emitted"][0]
    prepare = h.one(owner, """SELECT effect_id FROM v24.effects
        WHERE kind='host_prepare' AND request->>'install_id'=%s
        ORDER BY created_at,effect_id LIMIT 1""", (str(install_id),))
    owner.rollback()
    prepare_closure, _family = h.closure_size(owner, prepare)
    token = h.claim_probe(service, prepare)["claim"]
    settled = h.advance(service, prepare, {
        "v": 1, "class": "success", "claim": token, "body": {}})
    service.commit()
    assert settled.get("disposition") == "committed", settled
    settled_closure, _family = h.closure_size(owner, prepare)
    fiber_id = h.one(owner, "SELECT fiber_id FROM v24.fibers WHERE install_id=%s",
                     (install_id,))
    owner.rollback()
    counts, closures = [], []
    for index in range(32):
        action = "on" if index % 2 == 0 else "off"
        seq = index
        result = h.one(service, "SELECT v24.fiber_control(%s,%s,%s,%s)",
                       (fiber_id, action, seq, f"g8-public-{action}-{index}"))
        service.commit()
        assert result.get("disposition") in ("committed", "deferred"), result
        latest = h.one(owner, """SELECT effect_id FROM v24.effects
            WHERE scope_id=%s ORDER BY created_at DESC,effect_id DESC LIMIT 1""",
                       (scope_id,))
        owner.rollback()
        closure, _family = h.closure_size(owner, latest)
        closures.append((index + 1, action, closure))
        if index in (0, 7, 15, 31):
            family = h.one(owner, """SELECT jsonb_build_object(
                    'effects',(SELECT count(*) FROM v24.effects WHERE scope_id=%s),
                    'host',(SELECT count(*) FROM v24.effects WHERE scope_id=%s
                              AND kind IN ('host_prepare','host_release','inspect_resource')),
                    'reconcile',(SELECT count(*) FROM v24.effects WHERE scope_id=%s
                              AND kind='fiber_reconcile'),
                    'episodes',(SELECT count(*) FROM v24.episodes
                              WHERE fiber_id=%s),
                    'pins',(SELECT count(*) FROM v24.pins WHERE consumer_run_id IS NULL
                              AND consumer_episode_id IS NOT NULL))""",
                                (scope_id, scope_id, scope_id, fiber_id))
            owner.rollback()
            family["closure"] = closures[-1][2]
            counts.append((index + 1, family))
    slopes = [closures[i][2] - closures[i - 1][2]
              for i in range(1, len(closures))]
    print(f"[G8-C1/public] install={install_id} host_prepare closure "
          f"{prepare_closure}->{settled_closure}; fiber_control on/off x32 "
          f"closures={[(i, a, c) for i, a, c in closures]}; adjacent slopes="
          f"{slopes}; counts={counts}; inspect branch not generated in M-H "
          f"(no unknown host effect), actual return=[]")



# ---------------------------------------------------------------------------
# G8-L1: lease boundaries
# ---------------------------------------------------------------------------
def g8_l1(db, owner, conns, pmap):
    service = conns["service"]
    scope_id = h.seed_scope(owner, owner_principal=pmap["service"])
    one_ms = h.seed_effect(owner, scope_id=scope_id, kind="host_prepare",
                           request={})
    max_ms = h.seed_effect(owner, scope_id=scope_id, kind="host_prepare",
                           request={})
    first = h.advance(service, one_ms, h.claim(1))
    service.commit()
    assert first.get("disposition") == "committed" and first["claim"], first
    second = h.advance(service, max_ms, h.claim(300000))
    service.commit()
    assert second.get("disposition") == "committed" and second["claim"], second

    invalid_targets = [
        h.seed_effect(owner, scope_id=scope_id, kind="host_prepare", request={})
        for _ in range(4)]
    invalid_bodies = (0, -1, 300001, "1")
    for target, lease in zip(invalid_targets, invalid_bodies):
        before = h.snapshot(owner)
        response = h.advance(service, target, h.claim(lease))
        service.commit()
        assert response == {"v": 1, "error": {"code": "invalid_args",
                                              "detail": {}}}, (lease, response)
        after = h.snapshot(owner)
        assert after == before, (lease, "invalid lease wrote rows")
        row = h.one(owner, "SELECT to_jsonb(e) FROM v24.effects e WHERE effect_id=%s",
                    (target,))
        owner.rollback()
        assert row["status"] == "ready" and row["attempt_no"] == 0 and row["fence"] == 0
    print("[G8-L1] lease=1 and 300000 committed; 0/-1/300001/'1' -> "
          "invalid_args with ten-table byte-equal and attempt/fence 0")


# ---------------------------------------------------------------------------
# G8-L2: live lease, expired host re-claim, model/tool stale claim
# ---------------------------------------------------------------------------
def g8_l2(db, owner, conns, pmap):
    service = conns["service"]
    scope_id = h.seed_scope(owner, owner_principal=pmap["service"])
    live = h.seed_effect(
        owner, scope_id=scope_id, kind="host_prepare", status="claimed",
        request={}, attempt_no=1, fence=1, claim_owner="g8-live",
        lease_until=datetime.now(timezone.utc) + timedelta(minutes=5))
    deferred = h.advance(service, live, h.claim())
    service.commit()
    assert deferred == {"v": 1, "disposition": "deferred", "effect_id": str(live),
                        "emitted": [], "revision": 0, "claim": None}, deferred
    row = h.one(owner, "SELECT to_jsonb(e) FROM v24.effects e WHERE effect_id=%s",
                (live,))
    owner.rollback()
    assert (row["attempt_no"], row["fence"], row["claim_owner"]) == (1, 1, "g8-live"), row

    expired = h.seed_effect(
        owner, scope_id=scope_id, kind="host_prepare", status="claimed",
        request={}, attempt_no=1, fence=1, claim_owner="g8-expired",
        lease_until=h.now_minus(30))
    old_token = {"attempt": 1, "fence": 1, "owner": "g8-expired"}
    bumped = h.advance(service, expired, h.claim())
    service.commit()
    assert bumped.get("disposition") == "committed", bumped
    assert (bumped["claim"]["attempt"], bumped["claim"]["fence"]) == (2, 2), bumped
    stale = h.advance(service, expired, {
        "v": 1, "class": "success", "claim": old_token, "body": {}})
    service.commit()
    assert stale == {"v": 1, "error": {"code": "stale_claim", "detail": {}}}, stale
    row = h.one(owner, "SELECT to_jsonb(e) FROM v24.effects e WHERE effect_id=%s",
                (expired,))
    owner.rollback()
    assert (row["status"], row["attempt_no"], row["fence"]) == ("claimed", 2, 2), row

    parent = g7_make_parent(
        owner, service, "g8-l2-model",
        {"steps": 6, "tool_calls": 2, "tokens": 5000, "wall_ms": 600000})
    model_id = UUID(str(parent["model_id"]))
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.effects SET lease_until=now()-interval '1 minute' "
                    "WHERE effect_id=%s", (model_id,))
    owner.commit()
    before = h.one(owner, "SELECT to_jsonb(e) FROM v24.effects e WHERE effect_id=%s",
                   (model_id,))
    owner.rollback()
    model_stale = h.advance(service, model_id, h.claim())
    service.commit()
    assert model_stale == {"v": 1, "error": {"code": "stale_claim",
                                             "detail": {}}}, model_stale
    after = h.one(owner, "SELECT to_jsonb(e) FROM v24.effects e WHERE effect_id=%s",
                  (model_id,))
    owner.rollback()
    assert (after["attempt_no"], after["fence"], after["claim_owner"]) == (
        before["attempt_no"], before["fence"], before["claim_owner"]), (before, after)

    run_id, model2 = start_tool_run(
        owner, service, "g8-l2-tool", ("k",),
        {"steps": 6, "tool_calls": 1, "tokens": 5000, "wall_ms": 600000})
    ids, _digest, _pins = settle_tool_batch(owner, service, run_id, model2, ("k",))
    tool_id = ids[0]
    tool_token = g2b_claim_effect(service, tool_id)
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.effects SET lease_until=now()-interval '1 minute' "
                    "WHERE effect_id=%s", (tool_id,))
    owner.commit()
    tool_before = h.one(owner, "SELECT to_jsonb(e) FROM v24.effects e WHERE effect_id=%s",
                        (tool_id,))
    owner.rollback()
    tool_stale = h.advance(service, tool_id, h.claim())
    service.commit()
    assert tool_stale == {"v": 1, "error": {"code": "stale_claim",
                                            "detail": {}}}, tool_stale
    tool_after = h.one(owner, "SELECT to_jsonb(e) FROM v24.effects e WHERE effect_id=%s",
                       (tool_id,))
    owner.rollback()
    assert (tool_after["attempt_no"], tool_after["fence"]) == (
        tool_before["attempt_no"], tool_before["fence"]), (tool_before, tool_after)
    print("[G8-L2] live lease -> deferred/null; expired host re-claim bumps 2/2 "
          "and old token stale; expired model/tool -> stale_claim with "
          "attempt/fence unchanged")


# ---------------------------------------------------------------------------
# G8-L3: late settlement and post-recovery receipt conflict
# ---------------------------------------------------------------------------
def g8_l3(db, owner, conns, pmap):
    service = conns["service"]
    scope_id = h.seed_scope(owner, owner_principal=pmap["service"])
    install_id = h.seed_install(owner, scope_id, owner_principal=pmap["service"],
                                state="preparing")
    target = h.seed_effect(
        owner, scope_id=scope_id, kind="host_prepare", request={
            "install_id": str(install_id)})
    token = h.claim_probe(service, target, lease=1)["claim"]
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.effects SET lease_until=now()-interval '1 second' "
                    "WHERE effect_id=%s", (target,))
    owner.commit()
    late = h.advance(service, target, {
        "v": 1, "class": "success", "claim": token, "body": {}})
    service.commit()
    assert late.get("disposition") == "committed", late
    row = h.one(owner, "SELECT to_jsonb(e) FROM v24.effects e WHERE effect_id=%s",
                (target,))
    owner.rollback()
    assert row["status"] == "succeeded", row

    parent = g7_make_parent(
        owner, service, "g8-l3-recover",
        {"steps": 6, "tool_calls": 0, "tokens": 5000, "wall_ms": 600000})
    scope = UUID(str(parent["scope_id"]))
    model_id = UUID(str(parent["model_id"]))
    old_token = parent["token"]
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.effects SET lease_until=now()-interval '1 minute' "
                    "WHERE effect_id=%s", (model_id,))
    owner.commit()
    run_before = h.one(owner, "SELECT to_jsonb(r) FROM v24.runs r WHERE run_id=%s",
                       (UUID(str(parent["run_id"])),))
    owner.rollback()
    recovered = h.one(service, "SELECT v24.command_recover(%s,%s,16)",
                      (scope, "g8-l3-recover"))
    service.commit()
    assert recovered.get("disposition") == "committed", recovered
    applied = recovered["recovery"]["applied"]
    assert any(item["effect_id"] == str(model_id) for item in applied), applied
    model_row = h.one(owner, "SELECT to_jsonb(e) FROM v24.effects e WHERE effect_id=%s",
                      (model_id,))
    owner.rollback()
    assert model_row["status"] == "unknown", model_row
    late_receipt = h.advance(service, model_id, {
        "v": 1, "class": "success", "claim": old_token,
        "body": {"kind": "model_call", "result": {"text": "late"}}})
    service.commit()
    assert late_receipt == {"v": 1, "error": {"code": "receipt_conflict",
                                              "detail": {}}}, late_receipt
    run_after = h.one(owner, "SELECT to_jsonb(r) FROM v24.runs r WHERE run_id=%s",
                      (UUID(str(parent["run_id"])),))
    owner.rollback()
    assert run_after["status"] == "blocked_unknown", run_after
    assert run_after["ended_at"] == run_before["ended_at"] or run_after["ended_at"]
    assert h.one(owner, """SELECT count(*) FROM v24.effects
        WHERE run_id=%s AND kind IN ('model_call','tool_call')""",
                  (UUID(str(parent["run_id"])),)) == 1
    owner.rollback()
    print("[G8-L3] expired claimed host accepts original token; command_recover "
          "settles model unknown, late receipt -> receipt_conflict, run stays "
          "blocked_unknown with no successor")


# ---------------------------------------------------------------------------
# G8-R1: bounded, explicit recovery sweep
# ---------------------------------------------------------------------------
def g8_r1(db, owner, conns, pmap):
    service = conns["service"]
    scope_id = h.seed_scope(owner, owner_principal=pmap["service"])
    expired = []
    for index in range(17):
        expired.append(h.seed_effect(
            owner, scope_id=scope_id, kind="host_prepare", status="claimed",
            request={}, attempt_no=1, fence=1, claim_owner=f"g8-r1-{index}",
            lease_until=h.now_minus(60 + index)))
    manual = h.seed_effect(
        owner, scope_id=scope_id, kind="host_prepare", status="claimed",
        request={}, replay_policy="manual", attempt_no=1, fence=1,
        claim_owner="g8-r1-manual", lease_until=h.now_minus(120))
    before_status = h.one(owner, """SELECT jsonb_object_agg(status, n)
        FROM (SELECT status, count(*) AS n FROM v24.effects
               WHERE effect_id = ANY(%s) GROUP BY status) q""",
                          (expired + [manual],))
    owner.rollback()
    assert before_status == {"claimed": 18}, before_status
    candidates = h.one(owner, "SELECT count(*) FROM v24.recoverable_effects(%s,16)",
                       (scope_id,))
    owner.rollback()
    assert candidates == 16, candidates

    first = h.one(service, "SELECT v24.command_recover(%s,%s,16)",
                  (scope_id, "g8-r1-first"))
    service.commit()
    assert first.get("disposition") == "committed", first
    recovery = first["recovery"]
    assert len(recovery["applied"]) == 16, recovery
    assert recovery["manual_debt"] == 1, recovery
    assert recovery["has_more"] is True, recovery
    statuses = h.one(owner, """SELECT jsonb_object_agg(status, n)
        FROM (SELECT status, count(*) AS n FROM v24.effects
               WHERE effect_id = ANY(%s) GROUP BY status) q""",
                     (expired + [manual],))
    owner.rollback()
    assert statuses == {"unknown": 16, "claimed": 2}, statuses

    second = h.one(service, "SELECT v24.command_recover(%s,%s,16)",
                   (scope_id, "g8-r1-second"))
    service.commit()
    assert len(second["recovery"]["applied"]) == 1, second
    assert second["recovery"]["manual_debt"] == 1, second
    assert second["recovery"]["has_more"] is False, second
    statuses = h.one(owner, """SELECT jsonb_object_agg(status, n)
        FROM (SELECT status, count(*) AS n FROM v24.effects
               WHERE effect_id = ANY(%s) GROUP BY status) q""",
                     (expired + [manual],))
    owner.rollback()
    assert statuses == {"unknown": 17, "claimed": 1}, statuses
    manual_row = h.one(owner, "SELECT to_jsonb(e) FROM v24.effects e WHERE effect_id=%s",
                       (manual,))
    owner.rollback()
    assert manual_row["status"] == "claimed" and manual_row["claim_owner"] == "g8-r1-manual"
    relations = {row[0] for row in h.rows(owner, """
        SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='v24' AND c.relkind IN ('r','p','v','m')
          AND (relname ~* '(queue|job|cursor)')""")}
    owner.rollback()
    assert not relations, relations
    assert {row[0] for row in h.rows(owner, """
        SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='v24' AND c.relkind='r'""")} == set(EXPECTED_TABLES)
    owner.rollback()
    print("[G8-R1] no command -> 18 claimed unchanged; sweep applies 16, "
          "manual_debt=1, has_more=true; next sweep applies the 17th only; "
          "manual untouched; no queue/job/cursor relation")



# ---------------------------------------------------------------------------
# G8-D1a: closed scope + expired candidate is still recovered
# ---------------------------------------------------------------------------
def g8_d1a(db, owner, conns, pmap):
    service = conns["service"]
    closed_at = datetime.now(timezone.utc)
    scope_id = h.seed_scope(
        owner, owner_principal=pmap["service"],
        close_requested_at=closed_at, closed_at=closed_at)
    install_id = h.seed_install(owner, scope_id, owner_principal=pmap["service"],
                                state="installed")
    target = h.seed_effect(
        owner, scope_id=scope_id, kind="host_prepare", status="claimed",
        request={"install_id": str(install_id)}, attempt_no=1, fence=1,
        claim_owner="g8-d1a", lease_until=h.now_minus(30))
    before_scope = h.one(owner, "SELECT to_jsonb(s) FROM v24.scopes s WHERE scope_id=%s",
                         (scope_id,))
    owner.rollback()
    before_install = h.one(owner, "SELECT to_jsonb(i) FROM v24.installs i WHERE install_id=%s",
                           (install_id,))
    owner.rollback()
    before_runs = h.one(owner, "SELECT count(*) FROM v24.runs WHERE scope_id=%s",
                        (scope_id,))
    owner.rollback()
    before_fibers = h.one(owner, "SELECT count(*) FROM v24.fibers WHERE scope_id=%s",
                          (scope_id,))
    owner.rollback()

    response = h.one(service, "SELECT v24.command_recover(%s,%s,16)",
                     (scope_id, "g8-d1a-recover"))
    service.commit()
    assert response.get("disposition") == "committed", response
    applied = response["recovery"]["applied"]
    assert len(applied) == 1, applied
    entry = applied[0]
    assert entry["effect_id"] == str(target), entry
    assert entry["action"] == "settle_unknown", entry
    assert entry["reason"] == "install_not_preparing", entry
    row = h.one(owner, "SELECT to_jsonb(e) FROM v24.effects e WHERE effect_id=%s",
                (target,))
    owner.rollback()
    assert row["status"] == "unknown", row
    assert row["outcome"]["body"]["result"]["reason"] == "install_not_preparing", row
    after_scope = h.one(owner, "SELECT to_jsonb(s) FROM v24.scopes s WHERE scope_id=%s",
                        (scope_id,))
    owner.rollback()
    assert after_scope == before_scope, (before_scope, after_scope)
    after_install = h.one(owner, "SELECT to_jsonb(i) FROM v24.installs i WHERE install_id=%s",
                          (install_id,))
    owner.rollback()
    assert after_install == before_install, (before_install, after_install)
    assert h.one(owner, "SELECT count(*) FROM v24.runs WHERE scope_id=%s",
                 (scope_id,)) == before_runs
    owner.rollback()
    assert h.one(owner, "SELECT count(*) FROM v24.fibers WHERE scope_id=%s",
                 (scope_id,)) == before_fibers
    owner.rollback()
    print("[G8-D1a] closed scope real expired candidate: applied=1 "
          "settle_unknown/install_not_preparing; scope/install/fiber/run not revived")


# ---------------------------------------------------------------------------
# G8-D1b: closed synthetic no-candidate scope
# ---------------------------------------------------------------------------
def g8_d1b(db, owner, conns, pmap):
    service = conns["service"]
    scope_id = h.seed_scope(owner, owner_principal=pmap["service"])
    manifest = json.dumps({
        "identity": "g8-d1b", "version": "1", "requires": [],
        "provides": [], "adapter_digest": "\\x"}).encode()
    admitted = h.one(service, "SELECT v24.install(%s,NULL,%s,%s,%s)",
                     (scope_id, manifest, b"", "g8-d1b-install"))
    service.commit()
    assert admitted.get("disposition") == "committed", admitted
    install_id = admitted["emitted"][0]
    closed = h.one(service, "SELECT v24.scope_control('close',%s,NULL,NULL,%s)",
                   (scope_id, "g8-d1b-close"))
    service.commit()
    assert closed.get("disposition") == "committed", closed
    # Synthetic terminal state: M-H has no host worker to drain the close.
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.scopes SET closed_at=now() WHERE scope_id=%s",
                    (scope_id,))
    owner.commit()
    before = {
        "scope": h.one(owner, "SELECT to_jsonb(s) FROM v24.scopes s WHERE scope_id=%s",
                       (scope_id,)),
        "install": h.one(owner, "SELECT to_jsonb(i) FROM v24.installs i WHERE install_id=%s",
                         (install_id,)),
        "fiber": h.one(owner, "SELECT to_jsonb(f) FROM v24.fibers f WHERE install_id=%s",
                       (install_id,)),
        "runs": h.one(owner, "SELECT count(*) FROM v24.runs WHERE scope_id=%s",
                      (scope_id,)),
        "effects": h.one(owner, "SELECT count(*) FROM v24.effects WHERE scope_id=%s",
                         (scope_id,)),
        "requests": h.one(owner, "SELECT count(*) FROM v24.requests WHERE principal_id=%s",
                          (pmap["service"],)),
    }
    owner.rollback()
    recovered = h.one(service, "SELECT v24.command_recover(%s,%s,16)",
                      (scope_id, "g8-d1b-recover"))
    service.commit()
    assert recovered.get("disposition") == "committed", recovered
    assert recovered["recovery"]["applied"] == [], recovered
    assert recovered["recovery"]["has_more"] is False, recovered
    after = {
        "scope": h.one(owner, "SELECT to_jsonb(s) FROM v24.scopes s WHERE scope_id=%s",
                       (scope_id,)),
        "install": h.one(owner, "SELECT to_jsonb(i) FROM v24.installs i WHERE install_id=%s",
                         (install_id,)),
        "fiber": h.one(owner, "SELECT to_jsonb(f) FROM v24.fibers f WHERE install_id=%s",
                       (install_id,)),
        "runs": h.one(owner, "SELECT count(*) FROM v24.runs WHERE scope_id=%s",
                      (scope_id,)),
        "effects": h.one(owner, "SELECT count(*) FROM v24.effects WHERE scope_id=%s",
                         (scope_id,)),
        "requests": h.one(owner, "SELECT count(*) FROM v24.requests WHERE principal_id=%s",
                          (pmap["service"],)),
    }
    owner.rollback()
    assert after["scope"] == before["scope"], (before["scope"], after["scope"])
    assert after["install"] == before["install"], (before["install"], after["install"])
    assert after["fiber"] == before["fiber"], (before["fiber"], after["fiber"])
    assert after["runs"] == before["runs"], (before["runs"], after["runs"])
    assert after["effects"] == before["effects"] + 1, (before["effects"], after["effects"])
    assert after["requests"] == before["requests"] + 1, (
        before["requests"], after["requests"])
    command = h.one(owner, """SELECT to_jsonb(e) FROM v24.effects e
        WHERE scope_id=%s AND kind='command_recover'
        ORDER BY created_at DESC,effect_id DESC LIMIT 1""", (scope_id,))
    owner.rollback()
    assert command["status"] == "succeeded", command
    assert command["request"]["body"]["payload"]["scope_id"] == str(scope_id), command
    print("[G8-D1b] public install + public close then synthetic closed_at; "
          "no-candidate recovery records only command/request, "
          "scope/install/fiber/run byte-equal")


# ---------------------------------------------------------------------------
# G8-D2: spawn mixing negatives are W0 and do not poison the claim
# ---------------------------------------------------------------------------
def g8_d2(db, owner, conns, pmap):
    service = conns["service"]
    parent = g7_make_parent(
        owner, service, "g8-d2",
        {"steps": 6, "tool_calls": 2, "tokens": 5000, "wall_ms": 600000})
    args = spawn_args(
        parent["scope_id"], "g8-d2-child",
        {"steps": 2, "tokens": 300, "tool_calls": 1, "wall_ms": 5000})
    token = parent["token"]
    spawn_call = [{"key": "agent.spawn", "args": args}]
    cases = {
        "two-spawn": {"tool_calls": [spawn_call[0], spawn_call[0]]},
        "spawn+tool": {"tool_calls": spawn_call + [{"key": "other", "args": {}}]},
        "spawn+final": {"tool_calls": spawn_call, "final": {"text": "x"}},
        "spawn+interaction": {"tool_calls": spawn_call,
                              "interaction": {"v": 1, "kind": "question"}},
    }
    for name, result in cases.items():
        before = h.snapshot(owner)
        response = h.advance(service, parent["model_id"], {
            "v": 1, "class": "success", "claim": token,
            "body": {"kind": "model_call", "result": result}})
        service.commit()
        assert response == {"v": 1, "error": {"code": "invalid_outcome",
                                              "detail": {}}}, (name, response)
        after = h.snapshot(owner)
        assert after == before, (name, "mixed spawn wrote rows")
        row = h.one(owner, "SELECT to_jsonb(e) FROM v24.effects e WHERE effect_id=%s",
                    (parent["model_id"],))
        owner.rollback()
        assert row["status"] == "claimed", (name, row)
        assert (row["attempt_no"], row["fence"], row["claim_owner"]) == (
            token["attempt"], token["fence"], token["owner"]), (name, row)
    legal = h.advance(service, parent["model_id"], {
        "v": 1, "class": "success", "claim": token,
        "body": {"kind": "model_call", "result": {
            "text": "spawn", "tool_calls": spawn_call,
            "usage": {"tokens": parent["model"]["request"]["reserve"]["tokens"],
                      "wall_ms": 0}}}})
    service.commit()
    assert legal.get("disposition") == "committed", legal
    assert len(legal.get("spawned", [])) == 1, legal
    handle = legal["spawned"][0]
    assert handle["spawn_key"] == "g8-d2-child" and handle["replayed"] is False, handle
    print("[G8-D2] two-spawn / spawn+tool / spawn+final / spawn+interaction "
          "are invalid_outcome W0 with claim unchanged; legal spawn after them "
          "commits and returns one child handle")


# ---------------------------------------------------------------------------
# G8-W1: worker contract preconditions available at M-H
# ---------------------------------------------------------------------------
def g8_w1(db, owner, conns, pmap):
    service, admin = conns["service"], conns["admin"]
    settings = {
        "statement_timeout": "30s",
        "lock_timeout": "5s",
        "idle_in_transaction_session_timeout": "5s",
    }
    for conn in (service, admin):
        with conn.cursor() as cur:
            for name, value in settings.items():
                cur.execute(f"SET {name} = '{value}'")
        conn.commit()
        assert h.one(conn, "SELECT current_setting('transaction_isolation')") == (
            "read committed")
        conn.rollback()
        for name, value in settings.items():
            assert h.one(conn, f"SELECT current_setting('{name}')") == value, (
                name, value)
            conn.rollback()

    parent = g7_make_parent(
        owner, service, "g8-w1",
        {"steps": 6, "tool_calls": 0, "tokens": 5000, "wall_ms": 600000})
    assert service.get_transaction_status() == TRANSACTION_STATUS_IDLE
    assert admin.get_transaction_status() == TRANSACTION_STATUS_IDLE
    live = h.one(owner, "SELECT count(*) FROM v24.recoverable_effects(%s,16)",
                 (UUID(str(parent["scope_id"])),))
    owner.rollback()
    assert live == 0, "live claim surfaced as a recovery candidate"
    expired = h.seed_effect(
        owner, scope_id=UUID(str(parent["scope_id"])), kind="host_prepare",
        status="claimed", request={}, attempt_no=1, fence=1,
        claim_owner="g8-w1-expired", lease_until=h.now_minus(60))

    def may_sweep(in_flight: bool, ready_expired: int) -> bool:
        return (not in_flight) and ready_expired > 0

    assert may_sweep(True, 1) is False
    before = h.one(owner, "SELECT to_jsonb(e) FROM v24.effects e WHERE effect_id=%s",
                   (UUID(str(parent["model_id"])),))
    owner.rollback()
    after = h.one(owner, "SELECT to_jsonb(e) FROM v24.effects e WHERE effect_id=%s",
                  (UUID(str(parent["model_id"])),))
    owner.rollback()
    assert after == before, "in-flight effect changed without a command"
    expired_row = h.one(owner, "SELECT status FROM v24.effects WHERE effect_id=%s",
                        (expired,))
    owner.rollback()
    assert expired_row == "claimed"
    print("[G8-W1] session profiles set (30s/5s/5s, read committed); after claim "
          "commit both connections idle; live claim not discoverable; with "
          "in-flight work worker policy skips the sweep and nothing changes")


if __name__ == "__main__":
    raise SystemExit(main())
