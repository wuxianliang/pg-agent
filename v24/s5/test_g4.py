"""G4 (S5 W1-W4): cleanup graph, cascade, inspect convergence, dispose closure.

W1-W4 are implemented in this gate.  The fixtures for G4-A/B/E and the seeded
parts of the later rows are built by direct owner-role DML (the same precedent
as G2b-G) and are explicitly marked as seeded, non-public shapes.  G4-E's cycle
and the 65-node chain are seeded defects used to exercise defensive reads; the
public admission path can never construct them.  No socket is opened and no
external IO runs inside a transaction.
"""
from __future__ import annotations

import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from psycopg2.extras import Json

S1 = Path(__file__).resolve().parent.parent / "s1"
S2 = Path(__file__).resolve().parent.parent / "s2"
for _path in (S1, S2):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from setup_db import (  # noqa: E402
    EXPECTED_TABLES,
    _assert_closed_catalog,
    server_helper_scope,
    setup_db,
)
from test_g3a import (  # noqa: E402
    advance,
    claim,
    command,
    domain_state,
    one,
    seed_effect,
    seed_episode,
    seed_fiber,
    seed_install,
    seed_scope,
    seed_slot,
    state,
)


def manifest_bytes(identity: str, provides=(), requires=()) -> bytes:
    return json.dumps(
        {
            "identity": identity,
            "version": "1",
            "requires": list(requires),
            "provides": list(provides),
            "adapter_digest": "\\x",
        }
    ).encode()


def graph_rows(owner, scope_id):
    """Fetch cleanup_graph in its documented order, as Python dicts."""
    return one(
        owner,
        """SELECT coalesce(jsonb_agg(to_jsonb(g) ORDER BY g.depth DESC,
                     g.node_id, g.parent_id NULLS FIRST, g.edge NULLS FIRST), '[]')
             FROM v24.cleanup_graph(%s) g""",
        (scope_id,),
    )


def install_edges(owner, install_id):
    return one(
        owner,
        """SELECT coalesce(jsonb_agg(jsonb_build_object(
                     'next_id', e.next_id, 'edge', e.edge)
                     ORDER BY e.next_id, e.edge), '[]')
             FROM v24.cleanup_edges(%s) e""",
        (install_id,),
    )


def seed_pin(owner, *, consumer_episode_id, provider_episode_id, slot_id,
             provider_fiber_id, creator, key="dep"):
    """Seeded fixture: activation pin, not a public command path."""
    pin_id = uuid4()
    with owner.cursor() as cur:
        cur.execute(
            """INSERT INTO v24.pins(pin_id, consumer_type, consumer_episode_id,
                 consumer_epoch, key, slot_id, provider_fiber_id,
                 provider_episode_id, descriptor_digest, created_by_effect)
               VALUES (%s,'activation',%s,1,%s,%s,%s,%s,%s,%s)""",
            (pin_id, consumer_episode_id, key, slot_id, provider_fiber_id,
             provider_episode_id, b"g4-pin", creator),
        )
    return pin_id


def new_scope(admin, realm, key):
    response = one(
        admin,
        "SELECT v24.scope_control('create_root',NULL,'{}',%s,%s)",
        (realm, key),
    )
    assert response.get("disposition") == "committed", response
    admin.commit()
    return response["emitted"][0]


def admit_install(admin, scope_id, identity, key, provides=(), owner_fiber=None,
                  requires=()):
    effect_id, outcome = command(admin, key, "command_install", {
        "scope_id": str(scope_id),
        "owner_fiber_id": str(owner_fiber) if owner_fiber is not None else None,
        "manifest_bytes": base64.b64encode(
            manifest_bytes(identity, provides, requires)).decode(),
        "artifact_digest": "\\x"})
    response = advance(admin, effect_id, outcome)
    assert response.get("disposition") == "committed", response
    admin.commit()
    return response


def fiber_of(owner, install_id):
    value = one(owner,
                "SELECT fiber_id FROM v24.fibers WHERE install_id=%s",
                (install_id,))
    owner.rollback()
    return value


def install_row(owner, install_id):
    value = one(owner,
                "SELECT to_jsonb(i) FROM v24.installs i WHERE i.install_id=%s",
                (install_id,))
    owner.rollback()
    return value


def effect_row(owner, effect_id):
    value = one(owner,
                "SELECT to_jsonb(e) FROM v24.effects e WHERE e.effect_id=%s",
                (effect_id,))
    owner.rollback()
    return value


def effect_of(owner, install_id, kind):
    value = one(
        owner,
        """SELECT effect_id FROM v24.effects
            WHERE kind=%s AND request->>'install_id'=%s
            ORDER BY created_at, effect_id LIMIT 1""",
        (kind, str(install_id)),
    )
    owner.rollback()
    return value


def claim_effect(service, effect_id):
    response = advance(service, effect_id, claim())
    service.commit()
    assert response.get("disposition") == "committed", response
    return response["claim"]


def settle_effect(service, effect_id, token, cls, body):
    response = advance(service, effect_id,
                       {"v": 1, "class": cls, "claim": token, "body": body})
    service.commit()
    return response


def dispose(admin, install_id, key):
    response = one(admin, "SELECT v24.dispose(%s,%s)", (install_id, key))
    admin.commit()
    return response


def count_kind(owner, install_id, kind):
    value = one(owner, """SELECT count(*) FROM v24.effects
        WHERE kind=%s AND request->>'install_id'=%s""",
                (kind, str(install_id)))
    owner.rollback()
    return value


def inspect_receipt(owner, effect_id, observed, cls="success"):
    """Build the frozen inspect result body from the stored request."""
    request = effect_row(owner, effect_id)["request"]
    result = {"v": 1, "observed": observed}
    if cls == "success":
        result["target_effect_id"] = request["target_effect_id"]
        result["target_reservation"] = request["target_reservation"]
    elif cls == "failure":
        result["reason"] = "inspect_failed"
    return {"kind": "inspect_resource", "result": result}


def assert_claim_invalid(owner, service, effect_id, label, tag="G4-N"):
    """W0 invalid_args plus a ten-table byte-equal snapshot."""
    before = state(owner)
    owner.rollback()
    response = advance(service, effect_id, claim())
    service.commit()
    assert response == {"v": 1, "error": {"code": "invalid_args", "detail": {}}}, (
        label, response)
    after = state(owner)
    owner.rollback()
    assert after == before, (label, "inspect claim rejection wrote rows")
    row = effect_row(owner, effect_id)
    assert row["status"] == "ready", (label, row)
    assert row["attempt_no"] == 0 and row["fence"] == 0, (label, row)
    assert row["claim_owner"] is None and row["lease_until"] is None, (label, row)
    print("[%s] %s: invalid_args, ten-table byte-equal, attempt/fence 0"
          % (tag, label[len(tag + " "):] if label.startswith(tag + " ")
             else label))


def seed_inspect_probe(owner, scope_id, install_id, request, *, effect_id=None):
    """Seeded inspect effect used only for claim-shape negatives."""
    parent = uuid4()
    seed_effect(
        owner, parent, kind="command_dispose", status="succeeded",
        scope_id=scope_id, request_key=None,
        outcome=Json({"v": 1, "class": "command", "claim": None, "body": {}}),
        settled_at=datetime.now(timezone.utc))
    if effect_id is None:
        effect_id = one(
            owner,
            "SELECT md5(%s::text || ':inspect_resource:' || %s::text || ':0')::uuid",
            (parent, install_id))
    seed_effect(
        owner, effect_id, kind="inspect_resource", status="ready",
        parent_effect_id=parent, ordinal=0, scope_id=scope_id,
        request=Json(request), request_digest=b"\xcd" * 32)
    owner.commit()
    return effect_id


def prepare_unknown_fixture(owner, admin, service, tag):
    """Real flow: install provides -> host_prepare unknown -> prepare_unknown."""
    scope_id = new_scope(admin, tag, tag + "-root")
    admitted = admit_install(admin, scope_id, tag, tag + "-install",
                             provides=[{"realm": tag, "key": "k"}])
    install_id = admitted["emitted"][0]
    assert install_row(owner, install_id)["state"] == "preparing"
    hp = effect_of(owner, install_id, "host_prepare")
    token = claim_effect(service, hp)
    settled = settle_effect(service, hp, token, "unknown", {})
    assert settled.get("disposition") == "committed", settled
    assert install_row(owner, install_id)["state"] == "prepare_unknown"
    return scope_id, install_id, hp


def installed_fixture(owner, admin, service, tag):
    """Real flow: install provides -> host_prepare success -> installed."""
    scope_id = new_scope(admin, tag, tag + "-root")
    admitted = admit_install(admin, scope_id, tag, tag + "-install",
                             provides=[{"realm": tag, "key": "k"}])
    install_id = admitted["emitted"][0]
    hp = effect_of(owner, install_id, "host_prepare")
    token = claim_effect(service, hp)
    settled = settle_effect(service, hp, token, "success", {})
    assert settled.get("disposition") == "committed", settled
    assert install_row(owner, install_id)["state"] == "installed"
    return scope_id, install_id, hp


def new_child_scope(admin, parent_id, realm, key):
    payload = {"action": "create_child", "parent_scope_id": str(parent_id),
               "realm_routes": {}, "default_realm": realm}
    effect_id, outcome = command(admin, key, "command_scope_control", payload)
    response = advance(admin, effect_id, outcome)
    assert response.get("disposition") == "committed", response
    admin.commit()
    return response["emitted"][0]


def close_scope(admin, scope_id, key):
    payload = {"action": "close", "parent_scope_id": str(scope_id)}
    effect_id, outcome = command(admin, key, "command_scope_control", payload)
    response = advance(admin, effect_id, outcome)
    admin.commit()
    return response


def scope_row(owner, scope_id):
    value = one(owner, "SELECT to_jsonb(s) FROM v24.scopes s WHERE s.scope_id=%s",
                (scope_id,))
    owner.rollback()
    return value


def scope_phase_events(owner, scope_id):
    value = one(
        owner,
        """SELECT coalesce(jsonb_agg(jsonb_build_object(
             'phase', payload->>'phase', 'pending', payload->'pending',
             'blockers', payload->'blockers', 'ok', payload->'ok')
             ORDER BY seq), '[]')
             FROM v24.events
            WHERE entity_type='scope' AND entity_id=%s
              AND event_kind='scope_close_phase'""",
        (scope_id,),
    )
    owner.rollback()
    return value


def scope_event_count(owner, scope_id, event_kind):
    value = one(
        owner,
        """SELECT count(*) FROM v24.events
            WHERE entity_type='scope' AND entity_id=%s AND event_kind=%s""",
        (scope_id, event_kind),
    )
    owner.rollback()
    return value


def settle_release(service, effect_id):
    token = claim_effect(service, effect_id)
    settled = settle_effect(service, effect_id, token, "success", {})
    assert settled.get("disposition") == "committed", settled
    return settled


def scope_closable(owner, scope_id):
    value = one(owner, "SELECT v24.scope_closable(%s)", (scope_id,))
    owner.rollback()
    return value


def cleanup_pending(owner, scope_id):
    value = one(owner, "SELECT v24.cleanup_pending(%s)", (scope_id,))
    owner.rollback()
    return value


def write_counts(owner):
    """(effects, requests, failed effects, events) for write-class assertions."""
    counts = (
        one(owner, "SELECT count(*) FROM v24.effects"),
        one(owner, "SELECT count(*) FROM v24.requests"),
        one(owner, "SELECT count(*) FROM v24.effects WHERE status='failed'"),
        one(owner, "SELECT count(*) FROM v24.events"),
    )
    owner.rollback()
    return counts


def expect_w1(owner, action, code, label, *, detail=None, events_same=True):
    """W1: only a failed command effect/request; the domain stays byte-equal."""
    before_domain = domain_state(owner)
    owner.rollback()
    before = write_counts(owner)
    response = action()
    assert response.get("error", {}).get("code") == code, (label, response)
    if detail is not None:
        assert response["error"]["detail"] == detail, (label, response)
    assert domain_state(owner) == before_domain, (label, "W1 wrote domain rows")
    owner.rollback()
    after = write_counts(owner)
    assert after[0] == before[0] + 1, (label, before, after)
    assert after[1] == before[1] + 1, (label, before, after)
    assert after[2] == before[2] + 1, (label, before, after)
    if events_same:
        assert after[3] == before[3], (label, before, after)
    print("[G4-M] %s: W1 %s, domain byte-equal, +1 failed effect/request, "
          "events %s" % (label, code,
                         "unchanged" if events_same else "changed"))
    return response


def expect_w0(owner, action, code, label):
    """W0: rejected before any write; all ten tables stay byte-equal."""
    before = state(owner)
    owner.rollback()
    response = action()
    assert response == {"v": 1, "error": {"code": code, "detail": {}}}, (
        label, response)
    after = state(owner)
    owner.rollback()
    assert after == before, (label, "W0 wrote rows")
    print("[G4-M] %s: W0 %s, ten-table byte-equal" % (label, code))
    return response


ROW_ID = {
    "installs": "install_id", "fibers": "fiber_id", "episodes": "episode_id",
    "slots": "slot_id", "pins": "pin_id", "scopes": "scope_id",
    "runs": "run_id", "effects": "effect_id", "events": "seq",
}


def changed_rows(before, after, tables=("installs", "fibers", "episodes",
                                        "slots", "pins")):
    """Count inserted/updated/deleted rows across the named domain tables."""
    changed = 0
    for table in tables:
        key = ROW_ID[table]
        old = {row[key]: row for row in before[table]}
        new = {row[key]: row for row in after[table]}
        changed += sum(1 for name in set(old) | set(new)
                       if old.get(name) != new.get(name))
    return changed


def released_slot_order(owner, fiber_id):
    with owner.cursor() as cur:
        cur.execute(
            "SELECT contribution_seq, released_at FROM v24.slots "
            "WHERE fiber_id=%s AND released_at IS NOT NULL "
            "ORDER BY released_at, contribution_seq", (fiber_id,))
        rows = cur.fetchall()
    owner.rollback()
    return rows


def released_slot_count(owner, fiber_id):
    value = one(owner, "SELECT count(*) FROM v24.slots "
                       "WHERE fiber_id=%s AND released_at IS NOT NULL",
                (fiber_id,))
    owner.rollback()
    return value


def install_event_count(owner, install_id, event_kind):
    value = one(owner, """SELECT count(*) FROM v24.events
        WHERE entity_type='install' AND entity_id=%s AND event_kind=%s""",
                (install_id, event_kind))
    owner.rollback()
    return value



def g4_a(owner):
    """Merged DAG: R owns A, A owns B, live dependency A -> P. Read-only."""
    creator = uuid4()
    seed_effect(owner, creator)
    scope_id = uuid4()
    seed_scope(owner, scope_id, creator)

    r = seed_install(owner, scope_id=scope_id, creator=creator)
    a = seed_install(owner, scope_id=scope_id, creator=creator)
    b = seed_install(owner, scope_id=scope_id, creator=creator)
    p = seed_install(owner, scope_id=scope_id, creator=creator)
    rf = seed_fiber(owner, install_id=r, scope_id=scope_id, creator=creator)
    af = seed_fiber(owner, install_id=a, scope_id=scope_id, creator=creator)
    bf = seed_fiber(owner, install_id=b, scope_id=scope_id, creator=creator)
    pf = seed_fiber(owner, install_id=p, scope_id=scope_id, creator=creator)
    re = seed_episode(owner, fiber_id=rf, creator=creator)
    ae = seed_episode(owner, fiber_id=af, creator=creator)
    be = seed_episode(owner, fiber_id=bf, creator=creator)
    pe = seed_episode(owner, fiber_id=pf, creator=creator)

    # Seeded fixture (non-public shape): owner edges A -> R and B -> A.
    with owner.cursor() as cur:
        cur.execute(
            "UPDATE v24.installs SET owner_fiber_id=%s, owner_episode_id=%s "
            "WHERE install_id=%s", (rf, re, a))
        cur.execute(
            "UPDATE v24.installs SET owner_fiber_id=%s, owner_episode_id=%s "
            "WHERE install_id=%s", (af, ae, b))

    # Provider P has a live slot; A holds an activation pin on it.
    p_slot = seed_slot(owner, fiber_id=pf, episode_id=pe, realm="g4a", key="p0")
    seed_pin(owner, consumer_episode_id=ae, provider_episode_id=pe,
             slot_id=p_slot, provider_fiber_id=pf, creator=creator, key="p0")

    # Three unreleased contributions on A's fiber: cleanup_slots must be DESC.
    for seq in (0, 1, 2):
        seed_slot(owner, fiber_id=af, episode_id=ae, realm="g4a",
                  key=f"a{seq}", seq=seq)
    owner.commit()

    before_state = state(owner)
    before_domain = domain_state(owner)

    rows = graph_rows(owner, scope_id)
    node_set = {row["node_id"] for row in rows}
    assert node_set == {str(r), str(a), str(b), str(p)}, node_set
    assert len(node_set) == 4

    edge_set = {(row["parent_id"], row["node_id"], row["edge"])
                for row in rows if row["parent_id"] is not None}
    assert edge_set == {
        (str(a), str(r), "owner"),
        (str(b), str(a), "owner"),
        (str(a), str(p), "dependency"),
    }, edge_set

    order = []
    for row in rows:
        if row["node_id"] not in order:
            order.append(row["node_id"])
    assert order.index(str(b)) < order.index(str(a)) < order.index(str(r)), order
    assert order.index(str(a)) < order.index(str(p)), order

    edge_a = install_edges(owner, a)
    assert {"next_id": str(r), "edge": "owner"} in edge_a, edge_a
    assert {"next_id": str(p), "edge": "dependency"} in edge_a, edge_a

    closure = one(
        owner,
        """SELECT coalesce(jsonb_agg(c.install_id ORDER BY c.install_id), '[]')
             FROM v24.cleanup_closure(%s) c""",
        (scope_id,),
    )
    assert set(closure) == {str(r), str(a), str(b), str(p)}, closure

    assert one(owner, "SELECT v24.cleanup_cycle(%s)", (r,)) == []
    seqs = one(
        owner,
        """SELECT coalesce(jsonb_agg(s.contribution_seq ORDER BY s.ord), '[]')
             FROM v24.cleanup_slots(%s) WITH ORDINALITY AS s(slot_id, contribution_seq, ord)""",
        (af,),
    )
    assert seqs == [2, 1, 0], seqs
    assert one(owner, "SELECT v24.cleanup_pending(%s)", (scope_id,)) == 8

    after_state = state(owner)
    after_domain = domain_state(owner)
    assert before_state == after_state
    assert before_domain == after_domain
    owner.rollback()
    print("[G4-A] merged DAG nodes/edges, deterministic child-before-owner order, "
          "cleanup_cycle empty, cleanup_slots DESC, all reads domain zero-write")


def g4_b(owner):
    """Live dependency consumer-before-provider; releasing the pin drops it."""
    creator = uuid4()
    seed_effect(owner, creator)
    scope_id = uuid4()
    seed_scope(owner, scope_id, creator)

    a = seed_install(owner, scope_id=scope_id, creator=creator)
    p = seed_install(owner, scope_id=scope_id, creator=creator)
    af = seed_fiber(owner, install_id=a, scope_id=scope_id, creator=creator)
    pf = seed_fiber(owner, install_id=p, scope_id=scope_id, creator=creator)
    ae = seed_episode(owner, fiber_id=af, creator=creator)
    pe = seed_episode(owner, fiber_id=pf, creator=creator)

    # Seeded fixture: provider slot + live activation pin A -> P.
    p_slot = seed_slot(owner, fiber_id=pf, episode_id=pe, realm="g4b", key="p0")
    pin = seed_pin(owner, consumer_episode_id=ae, provider_episode_id=pe,
                   slot_id=p_slot, provider_fiber_id=pf, creator=creator, key="p0")
    owner.commit()

    before = state(owner)
    edge_a = install_edges(owner, a)
    assert {"next_id": str(p), "edge": "dependency"} in edge_a, edge_a
    rows = graph_rows(owner, scope_id)
    order = []
    for row in rows:
        if row["node_id"] not in order:
            order.append(row["node_id"])
    assert order.index(str(a)) < order.index(str(p)), order
    assert any(row["parent_id"] == str(a) and row["node_id"] == str(p)
               and row["edge"] == "dependency" for row in rows)
    after_reads = state(owner)
    assert before == after_reads
    owner.rollback()

    # Seeded fixture: release the pin directly (not a public command path).
    release_effect = uuid4()
    seed_effect(owner, release_effect)
    with owner.cursor() as cur:
        cur.execute(
            "UPDATE v24.pins SET released_at=now(), released_by_effect=%s "
            "WHERE pin_id=%s", (release_effect, pin))
    owner.commit()

    assert install_edges(owner, a) == [], "dependency edge survived pin release"
    rows_after = graph_rows(owner, scope_id)
    assert not any(row["edge"] == "dependency" for row in rows_after), rows_after
    owner.rollback()
    print("[G4-B] live pin yields dependency A->P and consumer-before-provider; "
          "pin release removes the edge (seeded fixture, read calls zero-write)")


def seed_owner_cycle(owner, *, creator, scope_id, size=3):
    """Seeded defect: owner pairs form a closed cycle (not public-path reachable)."""
    install_ids = [seed_install(owner, scope_id=scope_id, creator=creator)
                   for _ in range(size)]
    fibers = [seed_fiber(owner, install_id=iid, scope_id=scope_id, creator=creator)
              for iid in install_ids]
    episodes = [seed_episode(owner, fiber_id=fid, creator=creator) for fid in fibers]
    with owner.cursor() as cur:
        for index in range(size):
            nxt = (index + 1) % size
            cur.execute(
                "UPDATE v24.installs SET owner_fiber_id=%s, owner_episode_id=%s "
                "WHERE install_id=%s",
                (fibers[nxt], episodes[nxt], install_ids[index]))
    return install_ids, fibers, episodes


def g4_e(owner, admin, service):
    """Seeded owner cycle, admission defense, and the 65-edge depth sentinel."""
    service_principal = one(service, "SELECT v24.principal_id(session_user)")
    service.rollback()

    creator = uuid4()
    seed_effect(owner, creator)
    cycle_scope = uuid4()
    # Seeded fixture: the scope belongs to the service principal so the public
    # v24.install wrapper can be used for the defensive admission probe.
    seed_scope(owner, cycle_scope, creator, owner_principal=service_principal)
    cycle, cycle_fibers, cycle_episodes = seed_owner_cycle(
        owner, creator=creator, scope_id=cycle_scope)
    # Seeded fixture: A's fiber is live so admission reaches the cycle check.
    with owner.cursor() as cur:
        cur.execute(
            "UPDATE v24.fibers SET want_on=true, current_episode_id=%s "
            "WHERE fiber_id=%s", (cycle_episodes[0], cycle_fibers[0]))
    owner.commit()

    path = one(owner, "SELECT v24.cleanup_cycle(%s)", (cycle[0],))
    assert len(path) == 4 and path[0] == path[-1] == cycle[0], path
    assert set(path[:-1]) == set(cycle), path
    owner.rollback()

    before_domain = domain_state(owner)
    before_effects = one(owner, "SELECT count(*) FROM v24.effects")
    before_requests = one(owner, "SELECT count(*) FROM v24.requests")
    before_events = one(owner, "SELECT count(*) FROM v24.events")
    owner.rollback()

    disposed = one(admin, "SELECT v24.dispose(%s,%s)", (cycle[0], "g4e-dispose"))
    admin.commit()
    assert disposed.get("error", {}).get("code") == "cleanup_cycle", disposed
    detail = disposed["error"]["detail"]
    assert len(detail["path"]) == 4 and detail["path"][0] == detail["path"][-1]
    assert detail["install_id"] == str(cycle[0]), detail
    assert domain_state(owner) == before_domain
    assert one(owner, "SELECT count(*) FROM v24.effects") == before_effects + 1
    assert one(owner, "SELECT count(*) FROM v24.requests") == before_requests + 1
    assert one(owner, "SELECT count(*) FROM v24.events") == before_events
    failed = one(owner, """SELECT to_jsonb(e) FROM v24.effects e
        WHERE e.kind='command_dispose' ORDER BY e.created_at DESC LIMIT 1""")
    assert failed["status"] == "failed", failed
    owner.rollback()

    # Admission defense: v24.install on A's live fiber must reject the cycle.
    before_domain = domain_state(owner)
    before_effects = one(owner, "SELECT count(*) FROM v24.effects")
    before_requests = one(owner, "SELECT count(*) FROM v24.requests")
    owner.rollback()
    admitted = one(
        service,
        "SELECT v24.install(%s,%s,%s,%s,%s)",
        (cycle_scope, cycle_fibers[0], manifest_bytes("g4e-child"), b"",
         "g4e-admission"),
    )
    service.commit()
    assert admitted.get("error", {}).get("code") == "cleanup_cycle", admitted
    assert len(admitted["error"]["detail"]["path"]) == 4, admitted
    assert domain_state(owner) == before_domain
    assert one(owner, "SELECT count(*) FROM v24.effects") == before_effects + 1
    assert one(owner, "SELECT count(*) FROM v24.requests") == before_requests + 1
    assert one(owner, "SELECT count(*) FROM v24.installs WHERE scope_id=%s",
               (cycle_scope,)) == 3
    owner.rollback()

    # Queued dependency cycle: R owns A, while A and P consume each other's
    # slots.  The root itself is acyclic, so the error must come from the queued
    # child and the already-accumulated R dispose_pending row must be discarded.
    creator4 = uuid4()
    seed_effect(owner, creator4)
    dep_scope = uuid4()
    seed_scope(owner, dep_scope, creator4)
    dep_r = seed_install(owner, scope_id=dep_scope, creator=creator4)
    dep_a = seed_install(owner, scope_id=dep_scope, creator=creator4)
    dep_p = seed_install(owner, scope_id=dep_scope, creator=creator4)
    dep_rf = seed_fiber(owner, install_id=dep_r, scope_id=dep_scope, creator=creator4)
    dep_af = seed_fiber(owner, install_id=dep_a, scope_id=dep_scope, creator=creator4)
    dep_pf = seed_fiber(owner, install_id=dep_p, scope_id=dep_scope, creator=creator4)
    dep_re = seed_episode(owner, fiber_id=dep_rf, creator=creator4)
    dep_ae = seed_episode(owner, fiber_id=dep_af, creator=creator4)
    dep_pe = seed_episode(owner, fiber_id=dep_pf, creator=creator4)
    with owner.cursor() as cur:
        cur.execute(
            "UPDATE v24.installs SET owner_fiber_id=%s, owner_episode_id=%s "
            "WHERE install_id=%s", (dep_rf, dep_re, dep_a))
    dep_slot_a = seed_slot(owner, fiber_id=dep_af, episode_id=dep_ae,
                           realm="g4e-dep", key="a")
    dep_slot_p = seed_slot(owner, fiber_id=dep_pf, episode_id=dep_pe,
                           realm="g4e-dep", key="p")
    seed_pin(owner, consumer_episode_id=dep_ae, provider_episode_id=dep_pe,
             slot_id=dep_slot_p, provider_fiber_id=dep_pf, creator=creator4,
             key="to-p")
    seed_pin(owner, consumer_episode_id=dep_pe, provider_episode_id=dep_ae,
             slot_id=dep_slot_a, provider_fiber_id=dep_af, creator=creator4,
             key="to-a")
    owner.commit()

    before_domain = domain_state(owner)
    before_effects = one(owner, "SELECT count(*) FROM v24.effects")
    before_requests = one(owner, "SELECT count(*) FROM v24.requests")
    owner.rollback()
    dep_cycle = one(owner, "SELECT v24.cleanup_cycle(%s)", (dep_a,))
    assert len(dep_cycle) == 3 and dep_cycle[0] == dep_cycle[-1] == dep_a, dep_cycle
    owner.rollback()
    queued = one(admin, "SELECT v24.dispose(%s,%s)",
                 (dep_r, "g4e-dep-cycle"))
    assert queued.get("error", {}).get("code") == "cleanup_cycle", queued
    assert len(queued["error"]["detail"]["path"]) == 3, queued
    admin.commit()
    assert domain_state(owner) == before_domain
    assert one(owner, "SELECT count(*) FROM v24.effects") == before_effects + 1
    assert one(owner, "SELECT count(*) FROM v24.requests") == before_requests + 1
    assert one(owner, "SELECT state FROM v24.installs WHERE install_id=%s",
               (dep_r,)) == "installed"
    owner.rollback()

    # Depth bound: 65-node linear owner chain.  head -> ... -> tail; the walk
    # reaches 65 nodes and returns the fail-closed sentinel {head}.
    creator3 = uuid4()
    seed_effect(owner, creator3)
    deep_scope = uuid4()
    seed_scope(owner, deep_scope, creator3)
    nodes, fibers, episodes = [], [], []
    for _ in range(65):
        node = seed_install(owner, scope_id=deep_scope, creator=creator3)
        fiber = seed_fiber(owner, install_id=node, scope_id=deep_scope,
                           creator=creator3)
        episode = seed_episode(owner, fiber_id=fiber, creator=creator3)
        nodes.append(node)
        fibers.append(fiber)
        episodes.append(episode)
    with owner.cursor() as cur:
        for index in range(64):
            cur.execute(
                "UPDATE v24.installs SET owner_fiber_id=%s, owner_episode_id=%s "
                "WHERE install_id=%s",
                (fibers[index + 1], episodes[index + 1], nodes[index]))
    owner.commit()

    before_domain = domain_state(owner)
    sentinel = one(owner, "SELECT v24.cleanup_cycle(%s)", (nodes[0],))
    assert sentinel == [nodes[0]], sentinel
    max_depth = one(
        owner, "SELECT coalesce(max(g.depth),0) FROM v24.cleanup_graph(%s) g",
        (deep_scope,))
    assert max_depth <= 64, max_depth
    assert domain_state(owner) == before_domain
    owner.rollback()
    print("[G4-E] seeded 3-install owner cycle -> cleanup_cycle on dispose and "
          "admission (domain zero-write, +1 failed effect/request); 65-chain "
          "returns the {head} sentinel, graph depth <= 64")


def g4_cascade(owner, admin, service):
    """W1 owner cascade + leaf semantics, with a bounded stage probe."""
    scope_resp = one(
        admin,
        "SELECT v24.scope_control('create_root',NULL,'{}',%s,%s)",
        ("g4w1", "g4w1-root"),
    )
    assert scope_resp.get("disposition") == "committed", scope_resp
    root = scope_resp["emitted"][0]
    admin.commit()

    reid, rout = command(admin, "g4w1-r", "command_install", {
        "scope_id": str(root), "owner_fiber_id": None,
        "manifest_bytes": base64.b64encode(manifest_bytes("g4w1-r")).decode(),
        "artifact_digest": "\\x"})
    r_resp = advance(admin, reid, rout)
    assert r_resp.get("disposition") == "committed", r_resp
    root_install = r_resp["emitted"][0]
    admin.commit()
    root_fiber = one(owner, "SELECT fiber_id FROM v24.fibers WHERE install_id=%s",
                     (root_install,))
    on_r = one(admin, "SELECT v24.fiber_control(%s,'on',0,%s)",
               (root_fiber, "g4w1-r-on"))
    assert on_r.get("disposition") == "committed", on_r
    admin.commit()

    children = []
    for label in ("a", "b"):
        cid, cout = command(
            admin, f"g4w1-{label}", "command_install", {
                "scope_id": str(root), "owner_fiber_id": str(root_fiber),
                "manifest_bytes": base64.b64encode(
                    manifest_bytes(f"g4w1-{label}")).decode(),
                "artifact_digest": "\\x"})
        cresp = advance(admin, cid, cout)
        assert cresp.get("disposition") == "committed", cresp
        children.append(cresp["emitted"][0])
        admin.commit()
    child_a, child_b = children
    fiber_a = one(owner, "SELECT fiber_id FROM v24.fibers WHERE install_id=%s",
                  (child_a,))
    fiber_b = one(owner, "SELECT fiber_id FROM v24.fibers WHERE install_id=%s",
                  (child_b,))
    on_b = one(admin, "SELECT v24.fiber_control(%s,'on',0,%s)",
               (fiber_b, "g4w1-b-on"))
    assert on_b.get("disposition") == "committed", on_b
    admin.commit()

    # Bounded stage probe: the first dispose marks root + both children and
    # releases only the inactive leaf A (4 update rows, 1 successor, 4 events).
    stage = one(owner, "SELECT v24.dispose_stage(%s,%s,'command')",
                (root_install, uuid4()))
    assert len(stage["installs"]) + len(stage["fibers"]) <= 16, stage
    assert len(stage["successors"]) <= 16, stage
    assert len(stage["events"]) <= 64, stage
    assert {row["key"]["install_id"] for row in stage["installs"]} == {
        str(root_install), str(child_a), str(child_b)}, stage
    assert len(stage["successors"]) == 1, stage
    assert stage["successors"][0]["request"]["install_id"] == str(child_a), stage
    # S5 W3 test alignment: `close` is now an accepted dispose_stage mode (the
    # close cascade entry point).  The stage is still read-only here.
    close_probe = one(owner, "SELECT v24.dispose_stage(%s,%s,'close')",
                      (root_install, uuid4()))
    assert "error" not in close_probe, close_probe
    assert close_probe["installs"], close_probe
    owner.rollback()

    first = one(admin, "SELECT v24.dispose(%s,%s)",
                (root_install, "g4w1-dispose-1"))
    assert first.get("disposition") == "committed", first
    assert len(first["emitted"]) == 1, first
    admin.commit()

    rows = one(owner, """SELECT coalesce(jsonb_agg(jsonb_build_object(
        'install_id', i.install_id, 'state', i.state,
        'dispose_effect', i.dispose_effect) ORDER BY i.install_id), '[]')
        FROM v24.installs i WHERE i.install_id IN (%s,%s,%s)""",
        (root_install, child_a, child_b))
    by_id = {row["install_id"]: row for row in rows}
    assert by_id[str(root_install)]["state"] == "dispose_pending"
    assert by_id[str(child_a)]["state"] == "dispose_pending"
    assert by_id[str(child_b)]["state"] == "dispose_pending"
    assert all(row["dispose_effect"] == first["effect_id"] for row in rows), rows

    releases = one(owner, """SELECT coalesce(jsonb_agg(jsonb_build_object(
        'install_id', e.request->>'install_id', 'effect_id', e.effect_id,
        'status', e.status) ORDER BY e.request->>'install_id'), '[]')
        FROM v24.effects e WHERE e.kind='host_release'
          AND e.request->>'install_id' IN (%s,%s,%s)""",
        (str(root_install), str(child_a), str(child_b)))
    assert len(releases) == 1, releases
    assert releases[0]["install_id"] == str(child_a), releases
    assert releases[0]["effect_id"] == first["emitted"][0], releases
    assert releases[0]["status"] == "ready", releases
    a_release = first["emitted"][0]
    owner.rollback()

    # A new key on an install whose release is already ready must reuse it and
    # never emit a second host_release.
    reuse = one(admin, "SELECT v24.dispose(%s,%s)",
                (child_a, "g4w1-reuse-a"))
    assert reuse.get("disposition") == "committed", reuse
    assert reuse["emitted"] == [a_release], reuse
    admin.commit()
    assert one(owner, """SELECT count(*) FROM v24.effects
        WHERE kind='host_release' AND request->>'install_id'=%s""",
               (str(child_a),)) == 1
    owner.rollback()

    # Settle A: child disposed; root stays pending with no release while B lives.
    token = advance(service, a_release, claim())["claim"]
    service.commit()
    settled_a = advance(service, a_release, {"v": 1, "class": "success",
                                             "claim": token, "body": {}})
    assert settled_a.get("disposition") == "committed", settled_a
    service.commit()
    assert one(owner, "SELECT state FROM v24.installs WHERE install_id=%s",
               (child_a,)) == "disposed"
    owner.rollback()

    blocked = one(admin, "SELECT v24.dispose(%s,%s)",
                  (root_install, "g4w1-dispose-2"))
    assert blocked.get("disposition") == "committed", blocked
    assert blocked["emitted"] == [], blocked
    admin.commit()
    assert one(owner, """SELECT count(*) FROM v24.effects
        WHERE kind='host_release' AND request->>'install_id'=%s""",
               (str(root_install),)) == 0
    owner.rollback()

    off_b = one(admin, "SELECT v24.fiber_control(%s,'off',1,%s)",
                (fiber_b, "g4w1-b-off"))
    assert off_b.get("disposition") == "committed", off_b
    admin.commit()
    dispose_b = one(admin, "SELECT v24.dispose(%s,%s)",
                    (child_b, "g4w1-dispose-b"))
    assert dispose_b.get("disposition") == "committed", dispose_b
    assert len(dispose_b["emitted"]) == 1, dispose_b
    admin.commit()
    b_release = dispose_b["emitted"][0]
    assert one(owner, """SELECT request->>'install_id' FROM v24.effects
        WHERE effect_id=%s""", (b_release,)) == str(child_b)
    token = advance(service, b_release, claim())["claim"]
    service.commit()
    settled_b = advance(service, b_release, {"v": 1, "class": "success",
                                             "claim": token, "body": {}})
    assert settled_b.get("disposition") == "committed", settled_b
    service.commit()
    assert one(owner, "SELECT state FROM v24.installs WHERE install_id=%s",
               (child_b,)) == "disposed"
    owner.rollback()

    off_r = one(admin, "SELECT v24.fiber_control(%s,'off',1,%s)",
                (root_fiber, "g4w1-r-off"))
    assert off_r.get("disposition") == "committed", off_r
    admin.commit()
    final = one(admin, "SELECT v24.dispose(%s,%s)",
                (root_install, "g4w1-dispose-3"))
    assert final.get("disposition") == "committed", final
    assert len(final["emitted"]) == 1, final
    admin.commit()
    r_release = final["emitted"][0]
    r_release_row = one(owner, "SELECT to_jsonb(e) FROM v24.effects e WHERE effect_id=%s",
                        (r_release,))
    assert r_release_row["kind"] == "host_release"
    assert r_release_row["request"]["install_id"] == str(root_install)
    assert one(owner, """SELECT count(*) FROM v24.effects
        WHERE kind='host_release' AND request->>'install_id'=%s""",
               (str(root_install),)) == 1
    after_children = one(owner, """SELECT bool_and(e.created_at > i.disposed_at)
        FROM v24.effects e, v24.installs i
        WHERE e.effect_id=%s AND i.install_id IN (%s,%s)""",
        (r_release, child_a, child_b))
    assert after_children is True, after_children
    owner.rollback()

    token = advance(service, r_release, claim())["claim"]
    service.commit()
    settle_r = advance(service, r_release, {"v": 1, "class": "success",
                                            "claim": token, "body": {}})
    assert settle_r.get("disposition") == "committed", settle_r
    service.commit()
    root_row = one(owner, "SELECT to_jsonb(i) FROM v24.installs i WHERE install_id=%s",
                   (root_install,))
    assert root_row["state"] == "disposed" and root_row["disposed_at"] is not None, root_row
    assert one(owner, """SELECT count(*) FROM v24.effects
        WHERE kind='host_release' AND request->>'install_id'=%s""",
               (str(root_install),)) == 1
    for response in (first, blocked, dispose_b, final):
        assert len(response["emitted"]) <= 16, response
    owner.rollback()
    print("[G4-W1] owner cascade: child-before-owner release order, active child "
          "blocks the owner, leaf semantics preserved, <=16 rows/successors")


def g4_h(owner, admin, service):
    """G4-H: prepare_unknown -> inspect known -> installed -> release -> disposed."""
    scope_id, install_id, hp = prepare_unknown_fixture(owner, admin, service, "g4h")
    target = effect_row(owner, hp)
    assert target["status"] == "unknown", target
    assert target["resource_quiesced_at"] is None, target

    first = dispose(admin, install_id, "g4h-dispose-1")
    assert first.get("disposition") == "committed", first
    assert len(first["emitted"]) == 1, first
    inspect_id = first["emitted"][0]
    row = effect_row(owner, inspect_id)
    digest = one(owner,
                 "SELECT encode(request_digest,'hex') FROM v24.effects WHERE effect_id=%s",
                 (hp,))
    owner.rollback()
    expected_request = {
        "v": 1,
        "install_id": str(install_id),
        "target": "host_prepare",
        "target_effect_id": str(hp),
        "target_reservation": "v24:host_prepare:" + str(hp),
        "target_request_digest": digest,
    }
    assert row["kind"] == "inspect_resource", row
    assert row["status"] == "ready", row
    assert row["parent_effect_id"] == first["effect_id"], row
    assert row["request"] == expected_request, row
    assert str(row["effect_id"]) == str(one(
        owner, "SELECT md5(%s::text || ':inspect_resource:' || %s::text || ':0')::uuid",
        (first["effect_id"], install_id)))
    owner.rollback()
    print("[G4-H] inspect_id=%s parent=%s target=%s request=%s" % (
        inspect_id, first["effect_id"], hp,
        json.dumps(row["request"], sort_keys=True)))
    assert install_row(owner, install_id)["state"] == "prepare_unknown"
    assert count_kind(owner, install_id, "host_release") == 0
    assert count_kind(owner, install_id, "inspect_resource") == 1

    # A second dispose key reuses the ready inspect instead of duplicating it.
    reused = dispose(admin, install_id, "g4h-dispose-2")
    assert reused.get("disposition") == "committed", reused
    assert reused["emitted"] == [inspect_id], reused
    assert count_kind(owner, install_id, "inspect_resource") == 1

    before_claim = state(owner)
    owner.rollback()
    token = claim_effect(service, inspect_id)
    after_claim = state(owner)
    owner.rollback()
    for table in EXPECTED_TABLES - {"effects"}:
        assert after_claim[table] == before_claim[table], (table, "inspect claim wrote rows")
    claimed = effect_row(owner, inspect_id)
    assert claimed["status"] == "claimed", claimed
    assert claimed["attempt_no"] == 1 and claimed["fence"] == 1, claimed
    assert claimed["claim_owner"] is not None, claimed

    target_before = effect_row(owner, hp)
    install_before = install_row(owner, install_id)
    settled = settle_effect(service, inspect_id, token, "success",
                            inspect_receipt(owner, inspect_id, "known"))
    assert settled.get("disposition") == "committed", settled
    assert settled["emitted"] == [], settled
    target_after = effect_row(owner, hp)
    assert target_after["status"] == "unknown", target_after
    assert target_after["resource_quiesced_at"] is not None, target_after
    changed = {key for key in target_after
               if target_after[key] != target_before[key]}
    assert changed == {"resource_quiesced_at"}, changed
    self_row = effect_row(owner, inspect_id)
    assert self_row["status"] == "succeeded", self_row
    assert self_row["resource_quiesced_at"] is None, self_row
    install_after = install_row(owner, install_id)
    assert install_after["state"] == "installed", install_after
    assert install_after["disposed_at"] is None, install_after
    changed_install = {key for key in install_after
                       if install_after[key] != install_before[key]}
    assert changed_install == {"state"}, changed_install

    final = dispose(admin, install_id, "g4h-dispose-3")
    assert final.get("disposition") == "committed", final
    assert len(final["emitted"]) == 1, final
    release_id = final["emitted"][0]
    assert str(release_id) == str(one(
        owner, "SELECT md5(%s::text || ':host_release:' || %s::text || ':0')::uuid",
        (final["effect_id"], install_id)))
    owner.rollback()
    release = effect_row(owner, release_id)
    assert release["kind"] == "host_release", release
    assert release["request"] == {
        "install_id": str(install_id),
        "reservation": "v24:host_release:" + str(release_id)}, release
    token = claim_effect(service, release_id)
    settled = settle_effect(service, release_id, token, "success", {})
    assert settled.get("disposition") == "committed", settled
    disposed = install_row(owner, install_id)
    assert disposed["state"] == "disposed", disposed
    assert disposed["disposed_at"] is not None, disposed
    assert count_kind(owner, install_id, "host_release") == 1
    assert one(owner, """SELECT count(*) FROM v24.events
        WHERE event_kind='install_disposed' AND entity_id=%s""",
               (install_id,)) == 1
    owner.rollback()
    print("[G4-H] prepare_unknown -> one inspect (target=host_prepare, reservation/"
          "digest byte-equal, deterministic id) reused on a second key -> claim "
          "effect-only -> known installs and only target.resource_quiesced_at "
          "changes (inspect self NULL) -> new dispose release -> disposed")


def g4_i(owner, admin, service):
    """G4-I: release unknown -> inspect unknown keeps pending; new key -> new id."""
    scope_id, install_id, hp = installed_fixture(owner, admin, service, "g4i")
    first = dispose(admin, install_id, "g4i-dispose-1")
    assert first.get("disposition") == "committed", first
    release_id = first["emitted"][0]
    token = claim_effect(service, release_id)
    settled = settle_effect(service, release_id, token, "unknown", {})
    assert settled.get("disposition") == "committed", settled
    release = effect_row(owner, release_id)
    assert release["status"] == "unknown", release
    assert release["resource_quiesced_at"] is None, release
    pending = install_row(owner, install_id)
    assert pending["state"] == "dispose_pending", pending
    assert pending["disposed_at"] is None, pending

    second = dispose(admin, install_id, "g4i-dispose-2")
    assert second.get("disposition") == "committed", second
    assert len(second["emitted"]) == 1, second
    inspect_id = second["emitted"][0]
    inspect = effect_row(owner, inspect_id)
    assert inspect["kind"] == "inspect_resource", inspect
    assert inspect["request"]["target"] == "host_release", inspect
    assert inspect["request"]["target_effect_id"] == str(release_id), inspect
    assert inspect["request"]["target_reservation"] == (
        "v24:host_release:" + str(release_id)), inspect
    assert count_kind(owner, install_id, "host_release") == 1
    assert count_kind(owner, install_id, "inspect_resource") == 1
    print("[G4-I] release=%s inspect1=%s request=%s" % (
        release_id, inspect_id, json.dumps(inspect["request"], sort_keys=True)))

    token = claim_effect(service, inspect_id)
    unknown_receipt = inspect_receipt(owner, inspect_id, "unknown", cls="unknown")
    unknown_outcome = {"v": 1, "class": "unknown", "claim": token,
                       "body": unknown_receipt}
    settled = settle_effect(service, inspect_id, token, "unknown", unknown_receipt)
    assert settled.get("disposition") == "committed", settled
    assert install_row(owner, install_id)["state"] == "dispose_pending"
    assert install_row(owner, install_id)["disposed_at"] is None
    assert count_kind(owner, install_id, "host_release") == 1
    assert effect_row(owner, inspect_id)["resource_quiesced_at"] is None
    assert effect_row(owner, release_id)["resource_quiesced_at"] is None
    assert one(owner, """SELECT count(*) FROM v24.events
        WHERE event_kind='install_disposed' AND entity_id=%s""",
               (install_id,)) == 0
    owner.rollback()

    third = dispose(admin, install_id, "g4i-dispose-3")
    assert third.get("disposition") == "committed", third
    assert len(third["emitted"]) == 1, third
    new_inspect = third["emitted"][0]
    assert str(new_inspect) != str(inspect_id), (new_inspect, inspect_id)
    assert str(new_inspect) == str(one(
        owner, "SELECT md5(%s::text || ':inspect_resource:' || %s::text || ':0')::uuid",
        (third["effect_id"], install_id)))
    owner.rollback()
    assert count_kind(owner, install_id, "inspect_resource") == 2
    assert install_row(owner, install_id)["state"] == "dispose_pending"
    print("[G4-I] inspect2=%s differs from inspect1=%s; install stays "
          "dispose_pending with one host_release" % (new_inspect, inspect_id))

    before_replay = state(owner)
    owner.rollback()
    replay = advance(service, inspect_id, unknown_outcome)
    service.commit()
    assert replay.get("disposition") == "replay", replay
    after_replay = state(owner)
    owner.rollback()
    assert after_replay == before_replay, "inspect replay wrote rows"
    print("[G4-I] release unknown -> exactly one inspect (never a second release) "
          "-> inspect unknown keeps dispose_pending, no release/tombstone, target "
          "and self quiesced NULL -> new key emits a different inspect id; same-key "
          "replay is byte-equal with no effect/event")


def g4_j(owner, admin, service):
    """G4-J: inspect absent on release then a fresh release; prepare direct tombstone."""
    # (1) release unknown -> inspect absent -> new release -> disposed.
    scope_id, install_id, hp = installed_fixture(owner, admin, service, "g4j1")
    first = dispose(admin, install_id, "g4j1-dispose-1")
    release_one = first["emitted"][0]
    token = claim_effect(service, release_one)
    settle_effect(service, release_one, token, "unknown", {})
    second = dispose(admin, install_id, "g4j1-dispose-2")
    inspect_id = second["emitted"][0]
    token = claim_effect(service, inspect_id)
    settled = settle_effect(service, inspect_id, token, "success",
                            inspect_receipt(owner, inspect_id, "absent"))
    assert settled.get("disposition") == "committed", settled
    pending = install_row(owner, install_id)
    assert pending["state"] == "dispose_pending", pending
    assert pending["disposed_at"] is None, pending
    assert effect_row(owner, release_one)["resource_quiesced_at"] is not None
    assert effect_row(owner, inspect_id)["resource_quiesced_at"] is None

    third = dispose(admin, install_id, "g4j1-dispose-3")
    assert third.get("disposition") == "committed", third
    release_two = third["emitted"][0]
    assert str(release_two) != str(release_one), (release_two, release_one)
    assert str(release_two) == str(one(
        owner, "SELECT md5(%s::text || ':host_release:' || %s::text || ':0')::uuid",
        (third["effect_id"], install_id)))
    owner.rollback()
    assert effect_row(owner, release_two)["request"]["reservation"] == (
        "v24:host_release:" + str(release_two))
    assert count_kind(owner, install_id, "host_release") == 2
    print("[G4-J] release1=%s release2=%s reservation2=%s" % (
        release_one, release_two, "v24:host_release:" + str(release_two)))
    token = claim_effect(service, release_two)
    settled = settle_effect(service, release_two, token, "success", {})
    assert settled.get("disposition") == "committed", settled
    assert install_row(owner, install_id)["state"] == "disposed"
    assert one(owner, """SELECT count(*) FROM v24.events
        WHERE event_kind='install_disposed' AND entity_id=%s""",
               (install_id,)) == 1
    owner.rollback()

    # (2) prepare_unknown -> inspect absent -> prepare_failed -> direct disposed.
    scope_id, install_id, hp = prepare_unknown_fixture(owner, admin, service, "g4j2")
    first = dispose(admin, install_id, "g4j2-dispose-1")
    inspect_id = first["emitted"][0]
    token = claim_effect(service, inspect_id)
    settled = settle_effect(service, inspect_id, token, "success",
                            inspect_receipt(owner, inspect_id, "absent"))
    assert settled.get("disposition") == "committed", settled
    assert install_row(owner, install_id)["state"] == "prepare_failed"
    second = dispose(admin, install_id, "g4j2-dispose-2")
    assert second.get("disposition") == "committed", second
    assert second["emitted"] == [], second
    assert count_kind(owner, install_id, "host_release") == 0
    disposed = install_row(owner, install_id)
    assert disposed["state"] == "disposed" and disposed["disposed_at"] is not None, disposed
    assert one(owner, """SELECT count(*) FROM v24.events
        WHERE event_kind='install_disposed' AND entity_id=%s""",
               (install_id,)) == 1
    event = one(owner, """SELECT payload FROM v24.events
        WHERE event_kind='install_disposed' AND entity_id=%s""", (install_id,))
    owner.rollback()
    assert event["released"] is False and event["state"] == "disposed", event
    assert one(owner, "SELECT disposed_at FROM v24.fibers WHERE install_id=%s",
               (install_id,)) is not None
    owner.rollback()
    print("[G4-J] direct tombstone: host_release=0, disposed_at set, event=%s"
          % json.dumps(event, sort_keys=True))
    print("[G4-J] (1) release unknown -> inspect absent -> fresh release (new id/"
          "reservation) -> disposed; (2) prepare_unknown -> inspect absent -> "
          "prepare_failed -> dispose writes disposed directly with 0 host_release "
          "and one install_disposed{released:false}")


def g4_k(owner, admin, service):
    """G4-K: both prepare_unknown paths and a genuine dispose_pending receipt conflict."""
    # known path
    scope_id, install_id, hp = prepare_unknown_fixture(owner, admin, service, "g4k1")
    first = dispose(admin, install_id, "g4k1-dispose-1")
    inspect_id = first["emitted"][0]
    token = claim_effect(service, inspect_id)
    settled = settle_effect(service, inspect_id, token, "success",
                            inspect_receipt(owner, inspect_id, "known"))
    assert settled.get("disposition") == "committed", settled
    assert install_row(owner, install_id)["state"] == "installed"
    second = dispose(admin, install_id, "g4k1-dispose-2")
    release_id = second["emitted"][0]
    token = claim_effect(service, release_id)
    settled = settle_effect(service, release_id, token, "success", {})
    assert settled.get("disposition") == "committed", settled
    assert install_row(owner, install_id)["state"] == "disposed"

    # absent path
    scope_id, install_id, hp = prepare_unknown_fixture(owner, admin, service, "g4k2")
    first = dispose(admin, install_id, "g4k2-dispose-1")
    inspect_id = first["emitted"][0]
    token = claim_effect(service, inspect_id)
    settled = settle_effect(service, inspect_id, token, "success",
                            inspect_receipt(owner, inspect_id, "absent"))
    assert settled.get("disposition") == "committed", settled
    assert install_row(owner, install_id)["state"] == "prepare_failed"
    second = dispose(admin, install_id, "g4k2-dispose-2")
    assert second["emitted"] == [], second
    assert install_row(owner, install_id)["state"] == "disposed"
    assert count_kind(owner, install_id, "host_release") == 0

    # Genuine dispose_pending + host_prepare receipt -> receipt_conflict.
    scope_id = new_scope(admin, "g4k3", "g4k3-root")
    admitted = admit_install(admin, scope_id, "g4k3", "g4k3-install",
                             provides=[{"realm": "g4k3", "key": "k"}])
    install_id = admitted["emitted"][0]
    hp = effect_of(owner, install_id, "host_prepare")
    # Seeded fixture, non-public shape: force the pending state while the
    # executed host_prepare receipt is still un-settled.
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.installs SET state='dispose_pending' "
                    "WHERE install_id=%s", (install_id,))
    owner.commit()
    before = domain_state(owner)
    owner.rollback()
    token = claim_effect(service, hp)
    refused = settle_effect(service, hp, token, "success", {})
    assert refused == {"v": 1, "error": {"code": "receipt_conflict", "detail": {}}}, refused
    after = domain_state(owner)
    owner.rollback()
    assert after == before, "receipt_conflict wrote domain rows"
    assert install_row(owner, install_id)["state"] == "dispose_pending"
    assert effect_row(owner, hp)["status"] == "claimed"
    print("[G4-K] receipt_conflict: domain_state byte-equal, install stays "
          "dispose_pending, host_prepare stays claimed")
    print("[G4-K] prepare_unknown known -> installed -> release -> disposed; "
          "absent -> prepare_failed -> direct disposed; dispose_pending + "
          "host_prepare receipt -> receipt_conflict with zero domain writes")


def g4_n(owner, admin, service):
    """G4-N: S1-S4 regression surface plus the real inspect claim->settle positive."""
    # host_prepare claim -> settle still works (installed_fixture uses the public flow).
    scope_id, install_id, hp = installed_fixture(owner, admin, service, "g4n1")
    assert effect_row(owner, hp)["status"] == "succeeded"
    assert install_row(owner, install_id)["state"] == "installed"

    # error_v1 still accepts exactly the closed 23-code set.
    codes = """invalid_args unauthorized not_found_or_denied request_conflict
        effect_id_conflict receipt_conflict stale_generation registration_stale
        already_terminal owner_closing install_not_ready interaction_mismatch
        provider_unavailable scope_closed dependency_unresolved provide_conflict
        install_identity_conflict budget_exceeded invalid_outcome stale_claim
        cleanup_cycle retry_with_closure blocked_unknown""".split()
    assert len(codes) == 23, codes
    for code in codes:
        response = one(owner, "SELECT v24.error_v1(%s)", (code,))
        owner.rollback()
        assert response["error"]["code"] == code, (code, response)

    # Leaf dispose replay and new-key already_terminal.
    scope_id = new_scope(admin, "g4n2", "g4n2-root")
    admitted = admit_install(admin, scope_id, "g4n2", "g4n2-install")
    install_id = admitted["emitted"][0]
    assert install_row(owner, install_id)["state"] == "installed"
    first = dispose(admin, install_id, "g4n2-dispose")
    release_id = first["emitted"][0]
    token = claim_effect(service, release_id)
    settled = settle_effect(service, release_id, token, "success", {})
    assert settled.get("disposition") == "committed", settled
    replay = dispose(admin, install_id, "g4n2-dispose")
    assert replay == first, (replay, first)
    late = dispose(admin, install_id, "g4n2-late")
    assert late == {"v": 1, "error": {"code": "already_terminal", "detail": {}}}, late

    # fiber_control on/off minimal E1 -> E2.
    scope_id = new_scope(admin, "g4n3", "g4n3-root")
    admitted = admit_install(admin, scope_id, "g4n3", "g4n3-install")
    install_id = admitted["emitted"][0]
    fiber = fiber_of(owner, install_id)
    on = one(admin, "SELECT v24.fiber_control(%s,'on',0,%s)",
             (fiber, "g4n3-on"))
    assert on.get("disposition") == "committed", on
    admin.commit()
    episode = one(owner, "SELECT current_episode_id FROM v24.fibers WHERE fiber_id=%s",
                  (fiber,))
    owner.rollback()
    assert episode is not None, episode
    off = one(admin, "SELECT v24.fiber_control(%s,'off',1,%s)",
              (fiber, "g4n3-off"))
    assert off.get("disposition") == "committed", off
    admin.commit()
    after_off = one(owner, "SELECT to_jsonb(f) FROM v24.fibers f WHERE f.fiber_id=%s",
                    (fiber,))
    owner.rollback()
    assert after_off["want_on"] is False and after_off["current_episode_id"] is None, after_off
    assert one(owner, "SELECT state FROM v24.episodes WHERE episode_id=%s",
               (episode,)) == "closed"
    owner.rollback()

    # start/pin projection remains intact.
    scope_id = new_scope(admin, "g4n4", "g4n4-root")
    provider = admit_install(admin, scope_id, "g4n4-prov", "g4n4-prov-install",
                             provides=[{"realm": "g4n4", "key": "k"}])
    provider_install = provider["emitted"][0]
    provider_hp = effect_of(owner, provider_install, "host_prepare")
    token = claim_effect(service, provider_hp)
    settle_effect(service, provider_hp, token, "success", {})
    provider_fiber = fiber_of(owner, provider_install)
    on_provider = one(admin, "SELECT v24.fiber_control(%s,'on',0,%s)",
                      (provider_fiber, "g4n4-prov-on"))
    assert on_provider.get("disposition") == "committed", on_provider
    admin.commit()
    slot = one(owner, "SELECT slot_id FROM v24.slots WHERE fiber_id=%s AND released_at IS NULL",
               (provider_fiber,))
    owner.rollback()
    consumer = admit_install(admin, scope_id, "g4n4-cons", "g4n4-cons-install")
    consumer_install = consumer["emitted"][0]
    consumer_fiber = fiber_of(owner, consumer_install)
    on_consumer = one(admin, "SELECT v24.fiber_control(%s,'on',0,%s)",
                      (consumer_fiber, "g4n4-cons-on"))
    assert on_consumer.get("disposition") == "committed", on_consumer
    admin.commit()
    start_response = one(
        admin, "SELECT v24.start(%s,%s,%s,%s,%s)",
        (scope_id, consumer_fiber, Json({"requires": [{"key": "k"}]}),
         Json({"steps": 5, "tool_calls": 2, "tokens": 5000, "wall_ms": 60000}),
         "g4n4-start"))
    admin.commit()
    assert start_response.get("disposition") == "committed", start_response
    run_id, model_id = start_response["emitted"]
    poll = one(admin, "SELECT v24.poll(%s,0)", (run_id,))
    admin.commit()
    assert set(poll) == {"v", "revision", "changed", "run", "events"}, poll
    assert poll["run"]["run_id"] == run_id, poll
    assert poll["run"]["status"] == "running", poll
    assert poll["run"]["owner_fiber_id"] == str(consumer_fiber), poll
    assert poll["changed"] is True, poll
    run_pin = one(owner, """SELECT jsonb_build_object('key',key,'slot_id',slot_id,
        'released_at',released_at) FROM v24.pins
        WHERE consumer_run_id=%s AND released_at IS NULL""", (run_id,))
    owner.rollback()
    assert run_pin["key"] == "k" and str(run_pin["slot_id"]) == str(slot), run_pin
    assert run_pin["released_at"] is None, run_pin
    model = effect_row(owner, model_id)
    assert model["kind"] == "model_call" and model["status"] == "ready", model

    # Inspect claim negatives (ten-table byte-equal) and a real claim->settle.
    scope_id, install_id, hp = prepare_unknown_fixture(owner, admin, service, "g4n5")
    first = dispose(admin, install_id, "g4n5-dispose")
    inspect_id = first["emitted"][0]
    request = effect_row(owner, inspect_id)["request"]

    # already-quiesced target
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.effects SET resource_quiesced_at=now() WHERE effect_id=%s",
                    (hp,))
    owner.commit()
    assert_claim_invalid(owner, service, inspect_id, "G4-N already-quiesced target")
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.effects SET resource_quiesced_at=NULL WHERE effect_id=%s",
                    (hp,))
    owner.commit()

    # terminal target: save/restore the settled unknown receipt exactly.
    original = effect_row(owner, hp)
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.effects SET status='succeeded', outcome=%s, settled_at=now() "
                    "WHERE effect_id=%s", (Json({"seed": True}), hp))
    owner.commit()
    assert_claim_invalid(owner, service, inspect_id, "G4-N terminal target")
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.effects SET status=%s, outcome=%s, settled_at=%s "
                    "WHERE effect_id=%s",
                    (original["status"], Json(original["outcome"]),
                     original["settled_at"], hp))
    owner.commit()

    bad_key_set = dict(request)
    bad_key_set.pop("v")
    probe = seed_inspect_probe(owner, scope_id, install_id, bad_key_set)
    assert_claim_invalid(owner, service, probe, "G4-N wrong key set")

    bad_reservation = dict(request)
    bad_reservation["target_reservation"] = "v24:host_release:" + str(uuid4())
    probe = seed_inspect_probe(owner, scope_id, install_id, bad_reservation)
    assert_claim_invalid(owner, service, probe, "G4-N wrong reservation")

    absent_reservation = dict(request)
    absent_reservation.pop("target_reservation")
    probe = seed_inspect_probe(owner, scope_id, install_id, absent_reservation)
    assert_claim_invalid(owner, service, probe, "G4-N absent reservation")

    bad_digest = dict(request)
    bad_digest["target_request_digest"] = "0" * 64
    probe = seed_inspect_probe(owner, scope_id, install_id, bad_digest)
    assert_claim_invalid(owner, service, probe, "G4-N bad digest")

    probe = seed_inspect_probe(owner, scope_id, install_id, request,
                               effect_id=uuid4())
    assert_claim_invalid(owner, service, probe, "G4-N wrong deterministic id")

    before_claim = state(owner)
    owner.rollback()
    token = claim_effect(service, inspect_id)
    after_claim = state(owner)
    owner.rollback()
    for table in EXPECTED_TABLES - {"effects"}:
        assert after_claim[table] == before_claim[table], (
            table, "inspect positive claim wrote rows")
    claimed = effect_row(owner, inspect_id)
    assert claimed["status"] == "claimed", claimed
    assert claimed["attempt_no"] == 1 and claimed["fence"] == 1, claimed
    settled = settle_effect(service, inspect_id, token, "success",
                            inspect_receipt(owner, inspect_id, "known"))
    assert settled.get("disposition") == "committed", settled
    assert install_row(owner, install_id)["state"] == "installed"
    assert effect_row(owner, hp)["resource_quiesced_at"] is not None
    assert effect_row(owner, inspect_id)["resource_quiesced_at"] is None
    print("[G4-N] host_prepare claim->settle, 23-code error_v1, leaf dispose replay/"
          "terminal, fiber_control E1->E2, start/poll projection + run pin, and "
          "inspect claim negatives (key set/reservation/target state/digest/id) all "
          "invalid_args with byte-equal snapshots; real inspect claim->settle "
          "converges with an effect-only claim write")


def g4_g(owner, admin, service):
    """G4-G: command-driven close phases; child scope finalizes first."""
    parent = new_scope(admin, "g4g", "g4g-parent")
    child = new_child_scope(admin, parent, "g4g-c", "g4g-child")
    parent_install = admit_install(
        admin, parent, "g4g-parent-i", "g4g-parent-inst")["emitted"][0]
    child_install = admit_install(
        admin, child, "g4g-child-i", "g4g-child-inst")["emitted"][0]

    def parent_call(key, phase, disposition):
        before = scope_event_count(owner, parent, "scope_close_phase")
        response = close_scope(admin, parent, key)
        after = scope_event_count(owner, parent, "scope_close_phase")
        assert after == before + 1, (key, before, after)
        current = scope_phase_events(owner, parent)[-1]
        assert current["phase"] == phase, (key, current)
        assert response["disposition"] == disposition, (key, response)
        if disposition == "deferred":
            assert scope_row(owner, parent)["closed_at"] is None, key
        return response

    first = parent_call("g4g-p-1", "request", "committed")
    assert first["emitted"] == [], first
    parent_call("g4g-p-2", "drain", "deferred")
    parent_call("g4g-p-3", "retire", "deferred")
    cascade = parent_call("g4g-p-4", "cascade", "deferred")
    assert len(cascade["emitted"]) == 1, cascade
    assert scope_event_count(owner, parent, "scope_closed") == 0
    parent_call("g4g-p-5", "barrier", "deferred")
    parent_barrier = scope_phase_events(owner, parent)[-1]
    assert parent_barrier["pending"]["children"] > 0, parent_barrier
    assert scope_event_count(owner, parent, "scope_closed") == 0

    # The parent's install is disposable, but the child scope is still open.
    settle_release(service, cascade["emitted"][0])
    assert install_row(owner, parent_install)["state"] == "disposed"
    parent_call("g4g-p-6", "barrier", "deferred")

    child_phases = []
    child_closed_at = None
    for index in range(1, 16):
        before = scope_event_count(owner, child, "scope_close_phase")
        response = close_scope(admin, child, "g4g-c-%d" % index)
        after = scope_event_count(owner, child, "scope_close_phase")
        assert after == before + 1, (index, before, after)
        child_phases.append(scope_phase_events(owner, child)[-1]["phase"])
        if response.get("emitted"):
            for effect_id in response["emitted"]:
                settle_release(service, effect_id)
        row = scope_row(owner, child)
        if row["closed_at"] is not None:
            child_closed_at = row["closed_at"]
            assert response["disposition"] == "committed", response
            break
        assert scope_event_count(owner, child, "scope_closed") == 0
    assert child_closed_at is not None, child_phases
    assert child_phases[-1] == "finalize", child_phases
    assert install_row(owner, child_install)["state"] == "disposed"

    parent_call("g4g-p-7", "barrier", "deferred")
    assert scope_phase_events(owner, parent)[-1]["ok"] is True
    final = parent_call("g4g-p-8", "finalize", "committed")
    assert final["emitted"] == [], final
    parent_row = scope_row(owner, parent)
    assert parent_row["closed_at"] is not None, parent_row
    assert parent_row["close_requested_at"] is not None, parent_row

    parent_phases = [event["phase"] for event in scope_phase_events(owner, parent)]
    assert parent_phases == [
        "request", "drain", "retire", "cascade",
        "barrier", "barrier", "barrier", "finalize"], parent_phases
    rank = {"request": 0, "drain": 1, "retire": 2, "cascade": 3,
            "barrier": 4, "finalize": 5}
    assert [rank[p] for p in parent_phases] == sorted(rank[p] for p in parent_phases)
    assert [rank[p] for p in child_phases] == sorted(rank[p] for p in child_phases)
    assert any(event["phase"] == "barrier"
               and event["pending"]["children"] > 0
               for event in scope_phase_events(owner, parent))
    assert scope_event_count(owner, parent, "scope_closed") == 1
    assert scope_event_count(owner, child, "scope_closed") == 1
    ordered = one(owner, """SELECT
        (SELECT closed_at FROM v24.scopes WHERE scope_id=%s) <
        (SELECT closed_at FROM v24.scopes WHERE scope_id=%s)""", (child, parent))
    owner.rollback()
    assert ordered is True, ordered

    # Same-key replay: byte-equal response and zero new events/effects/rows.
    before_state = state(owner)
    owner.rollback()
    before_phases = scope_event_count(owner, parent, "scope_close_phase")
    replay = close_scope(admin, parent, "g4g-p-1")
    assert replay == first, (replay, first)
    assert state(owner) == before_state
    owner.rollback()
    assert scope_event_count(owner, parent, "scope_close_phase") == before_phases

    # A new key on the closed scope is the existing W1 already_terminal receipt.
    closed_at = scope_row(owner, parent)["closed_at"]
    before_domain = domain_state(owner)
    owner.rollback()
    terminal = close_scope(admin, parent, "g4g-p-9")
    assert terminal == {
        "v": 1, "error": {"code": "already_terminal", "detail": {}}}, terminal
    assert domain_state(owner) == before_domain
    assert scope_event_count(owner, parent, "scope_closed") == 1
    assert scope_row(owner, parent)["closed_at"] == closed_at

    # Drain evidence: a live run gets only close_intent={kind:'close'}.  The
    # run row is a seeded fixture (non-public path); status/ended_at are not
    # rewritten and the close command publishes no successor.
    run_scope = new_scope(admin, "g4g-r", "g4g-run-root")
    run_id = uuid4()
    with owner.cursor() as cur:
        cur.execute(
            """INSERT INTO v24.runs(run_id, scope_id, status, remaining_steps,
                 remaining_tool_calls, remaining_wall_ms)
               VALUES (%s,%s,'running',2,1,1000)""",
            (run_id, run_scope))
    owner.commit()
    assert close_scope(admin, run_scope, "g4g-r-1")["disposition"] == "committed"
    run_before = one(owner, "SELECT to_jsonb(r) FROM v24.runs r WHERE r.run_id=%s",
                     (run_id,))
    owner.rollback()
    drain = close_scope(admin, run_scope, "g4g-r-2")
    assert drain["disposition"] == "deferred", drain
    run_after = one(owner, "SELECT to_jsonb(r) FROM v24.runs r WHERE r.run_id=%s",
                    (run_id,))
    owner.rollback()
    run_changed = {key for key in run_after if run_after[key] != run_before[key]}
    assert run_changed == {"close_intent"}, run_changed
    assert run_after["status"] == "running" and run_after["ended_at"] is None
    assert run_after["close_intent"] == {"kind": "close"}, run_after
    assert one(owner, "SELECT count(*) FROM v24.effects WHERE parent_effect_id=%s",
               (drain["effect_id"],)) == 0
    drain_event = scope_phase_events(owner, run_scope)[-1]
    assert drain_event["phase"] == "drain", drain_event
    assert drain_event["pending"]["runs"] == 1, drain_event
    assert close_scope(admin, run_scope, "g4g-r-3")["disposition"] == "deferred"
    assert scope_phase_events(owner, run_scope)[-1]["phase"] == "retire"
    assert one(owner, "SELECT status FROM v24.runs WHERE run_id=%s",
               (run_id,)) == "running"
    owner.rollback()

    # Retire evidence: the active generation moves to retiring, its slots are
    # withdrawn (not released), and the fiber intent flips with control_seq + 1.
    retire_scope, retire_install, _hp = installed_fixture(
        owner, admin, service, "g4g-ret")
    retire_fiber = fiber_of(owner, retire_install)
    activated = one(admin, "SELECT v24.fiber_control(%s,'on',0,%s)",
                    (retire_fiber, "g4g-ret-on"))
    admin.commit()
    assert activated.get("disposition") == "committed", activated
    retire_episode = activated["emitted"][0]
    close_scope(admin, retire_scope, "g4g-ret-1")
    close_scope(admin, retire_scope, "g4g-ret-2")
    retire_stage = close_scope(admin, retire_scope, "g4g-ret-3")
    assert retire_stage["disposition"] == "deferred", retire_stage
    assert scope_phase_events(owner, retire_scope)[-1]["phase"] == "retire"
    episode = one(owner, "SELECT to_jsonb(e) FROM v24.episodes e WHERE episode_id=%s",
                  (retire_episode,))
    owner.rollback()
    assert episode["state"] == "retiring", episode
    assert episode["retire_started_at"] is not None and episode["closed_at"] is None
    slot = one(owner, "SELECT to_jsonb(s) FROM v24.slots s WHERE episode_id=%s",
               (retire_episode,))
    owner.rollback()
    assert slot["withdrawn_at"] is not None, slot
    assert slot["released_at"] is None, slot
    retire_fiber_row = one(
        owner, "SELECT to_jsonb(f) FROM v24.fibers f WHERE f.fiber_id=%s",
        (retire_fiber,))
    owner.rollback()
    assert retire_fiber_row["want_on"] is False, retire_fiber_row
    assert retire_fiber_row["control_seq"] == 2, retire_fiber_row
    print("[G4-G] parent phases=%s child phases=%s child.closed_at<parent.closed_at=%s "
          "barrier children>0, finalize-once, same-key replay, new-key already_terminal; "
          "drain writes only close_intent={kind:close}; retire moves the generation to "
          "retiring and withdraws (not releases) its slots"
          % (parent_phases, child_phases, ordered))


def g4_o(owner, admin, service):
    """G4-O: close_requested_at blocks every new admission; fiber on is narrowed."""
    scope_id = new_scope(admin, "g4o", "g4o-root")
    admitted = admit_install(admin, scope_id, "g4o-i", "g4o-inst")
    install_id = admitted["emitted"][0]
    fiber = fiber_of(owner, install_id)

    requested = close_scope(admin, scope_id, "g4o-close")
    assert requested["disposition"] == "committed", requested
    requested_row = scope_row(owner, scope_id)
    assert requested_row["close_requested_at"] is not None, requested_row
    assert requested_row["closed_at"] is None, requested_row

    before = domain_state(owner)
    owner.rollback()

    child_payload = {"action": "create_child",
                     "parent_scope_id": str(scope_id),
                     "realm_routes": {}, "default_realm": "g4o-c"}
    effect_id, outcome = command(
        admin, "g4o-child", "command_scope_control", child_payload)
    child_block = advance(admin, effect_id, outcome)
    admin.commit()
    assert child_block == {
        "v": 1, "error": {"code": "scope_closed", "detail": {}}}, child_block
    assert domain_state(owner) == before
    owner.rollback()

    install_payload = {
        "scope_id": str(scope_id), "owner_fiber_id": None,
        "manifest_bytes": base64.b64encode(
            manifest_bytes("g4o-second")).decode(),
        "artifact_digest": "\\x"}
    effect_id, outcome = command(
        admin, "g4o-install", "command_install", install_payload)
    install_block = advance(admin, effect_id, outcome)
    admin.commit()
    assert install_block == {
        "v": 1, "error": {"code": "scope_closed", "detail": {}}}, install_block
    assert domain_state(owner) == before
    owner.rollback()

    start_block = one(
        admin, "SELECT v24.start(%s,%s,%s,%s,%s)",
        (scope_id, fiber, Json({}),
         Json({"steps": 2, "tool_calls": 1, "wall_ms": 100}), "g4o-start"))
    admin.commit()
    assert start_block == {
        "v": 1, "error": {"code": "scope_closed", "detail": {}}}, start_block
    assert domain_state(owner) == before
    owner.rollback()

    ten_before = state(owner)
    owner.rollback()
    fiber_before = one(
        owner, "SELECT to_jsonb(f) FROM v24.fibers f WHERE f.fiber_id=%s", (fiber,))
    owner.rollback()
    fiber_block = one(
        admin, "SELECT v24.fiber_control(%s,'on',0,%s)", (fiber, "g4o-on"))
    admin.commit()
    assert fiber_block == {
        "v": 1, "error": {"code": "scope_closed", "detail": {}}}, fiber_block
    ten_after = state(owner)
    owner.rollback()
    for table in EXPECTED_TABLES - {"effects", "requests", "fibers"}:
        assert ten_after[table] == ten_before[table], (
            table, "fiber_control(on) after close wrote rows")
    fiber_after = one(
        owner, "SELECT to_jsonb(f) FROM v24.fibers f WHERE f.fiber_id=%s", (fiber,))
    owner.rollback()
    changed = {key for key in fiber_after if fiber_after[key] != fiber_before[key]}
    assert changed == {"failure_seq", "failure"}, changed
    assert fiber_after["failure_seq"] == 1, fiber_after
    assert fiber_after["failure"]["code"] == "scope_closed", fiber_after
    assert fiber_after["want_on"] is False, fiber_after
    assert fiber_after["control_seq"] == 0, fiber_after
    assert one(owner, "SELECT count(*) FROM v24.episodes WHERE fiber_id=%s",
               (fiber,)) == 0
    assert one(owner, "SELECT count(*) FROM v24.slots WHERE fiber_id=%s",
               (fiber,)) == 0
    assert one(owner, """SELECT count(*) FROM v24.pins p
        JOIN v24.episodes e ON e.episode_id=p.consumer_episode_id
        WHERE e.fiber_id=%s""", (fiber,)) == 0
    owner.rollback()

    # A close by a non-owner/non-admin remains the existing W1 unauthorized
    # receipt (the close applier must not turn it into invalid_outcome) and
    # writes no domain rows.
    before = domain_state(owner)
    owner.rollback()
    unauthorized = close_scope(service, scope_id, "g4o-unauth")
    assert unauthorized == {
        "v": 1, "error": {"code": "unauthorized", "detail": {}}}, unauthorized
    assert domain_state(owner) == before
    owner.rollback()
    print("[G4-O] create_child/install/start -> scope_closed with byte-equal domain; "
          "fiber_control(on) -> scope_closed with only failure_seq/failure changed; "
          "non-owner close keeps the W1 unauthorized receipt")


def g4_c(owner, admin, service):
    """G4-C: consumer-before-provider across a live dependency pin."""
    tag = "g4c"
    scope_id = new_scope(admin, tag, tag + "-root")
    provider = admit_install(
        admin, scope_id, tag + "-p", tag + "-p-install",
        provides=[{"realm": tag, "key": "k"}])["emitted"][0]
    hp = effect_of(owner, provider, "host_prepare")
    settle_effect(service, hp, claim_effect(service, hp), "success", {})
    provider_fiber = fiber_of(owner, provider)
    on_provider = one(admin, "SELECT v24.fiber_control(%s,'on',0,%s)",
                      (provider_fiber, tag + "-p-on"))
    assert on_provider.get("disposition") == "committed", on_provider
    admin.commit()

    consumer = admit_install(
        admin, scope_id, tag + "-a", tag + "-a-install",
        requires=[{"key": "k"}])["emitted"][0]
    consumer_fiber = fiber_of(owner, consumer)
    on_consumer = one(admin, "SELECT v24.fiber_control(%s,'on',0,%s)",
                      (consumer_fiber, tag + "-a-on"))
    assert on_consumer.get("disposition") == "committed", on_consumer
    admin.commit()
    consumer_episode = on_consumer["emitted"][0]

    provider_slot = one(
        owner, "SELECT slot_id FROM v24.slots WHERE fiber_id=%s",
        (provider_fiber,))
    owner.rollback()
    pin = one(owner, """SELECT pin_id FROM v24.pins
        WHERE slot_id=%s AND released_at IS NULL""", (provider_slot,))
    owner.rollback()
    assert pin is not None, (provider_slot, consumer_episode)

    # Provider dispose: the live consumer pin is a provider-side barrier, so P
    # stays pending, withdraws (not releases) its slot and emits no release.
    first = dispose(admin, provider, tag + "-p-dispose-1")
    assert first.get("disposition") == "committed", first
    assert first["emitted"] == [], first
    provider_row = install_row(owner, provider)
    assert provider_row["state"] == "dispose_pending", provider_row
    assert provider_row["disposed_at"] is None, provider_row
    slot_row = one(owner, "SELECT to_jsonb(s) FROM v24.slots s WHERE s.slot_id=%s",
                   (provider_slot,))
    owner.rollback()
    assert slot_row["released_at"] is None, slot_row
    pin_row = one(owner, "SELECT to_jsonb(p) FROM v24.pins p WHERE p.pin_id=%s",
                  (pin,))
    owner.rollback()
    assert pin_row["released_at"] is None, pin_row
    assert count_kind(owner, provider, "host_release") == 0
    print("[G4-C] P dispose#1: P.state=%s disposed_at=%s slot.released_at=%s "
          "pin.released_at=%s host_release=%d (consumer barrier)"
          % (provider_row["state"], provider_row["disposed_at"],
             slot_row["released_at"], pin_row["released_at"],
             count_kind(owner, provider, "host_release")))

    off = one(admin, "SELECT v24.fiber_control(%s,'off',1,%s)",
              (consumer_fiber, tag + "-a-off"))
    assert off.get("disposition") == "committed", off
    admin.commit()
    pin_after = one(owner, """SELECT jsonb_build_object(
        'released_at', released_at, 'released_by_effect', released_by_effect)
        FROM v24.pins WHERE pin_id=%s""", (pin,))
    owner.rollback()
    assert pin_after["released_at"] is not None, pin_after
    assert pin_after["released_by_effect"] is not None, pin_after
    assert one(owner, "SELECT state FROM v24.episodes WHERE episode_id=%s",
               (consumer_episode,)) == "closed"
    owner.rollback()

    releases = []
    stages = 0
    for index in range(2, 9):
        response = dispose(admin, provider, "%s-p-dispose-%d" % (tag, index))
        assert response.get("disposition") == "committed", response
        stages += 1
        for effect_id in response["emitted"]:
            row = effect_row(owner, effect_id)
            assert row["kind"] == "host_release", row
            assert row["request"]["install_id"] == str(provider), row
            releases.append(effect_id)
        if releases:
            break
    assert len(releases) == 1, releases
    assert stages <= 7, stages
    release_id = releases[0]
    assert count_kind(owner, provider, "host_release") == 1
    assert install_row(owner, provider)["state"] == "dispose_pending"
    settle_release(service, release_id)

    final = install_row(owner, provider)
    assert final["state"] == "disposed", final
    assert final["disposed_at"] is not None, final
    slot_final = one(owner, "SELECT released_at FROM v24.slots WHERE slot_id=%s",
                     (provider_slot,))
    owner.rollback()
    assert slot_final is not None, slot_final
    assert count_kind(owner, provider, "host_release") == 1
    print("[G4-C] after consumer off + P dispose#%d: release=%s exactly one "
          "host_release, slot.released_at=%s, P.state=%s disposed_at=%s"
          % (stages + 1, release_id, slot_final, final["state"],
             final["disposed_at"]))


def g4_d(owner, admin, service):
    """G4-D: three contributions release strictly DESC, one per advance."""
    tag = "g4d"
    scope_id = new_scope(admin, tag, tag + "-root")
    install_id = admit_install(
        admin, scope_id, tag, tag + "-install",
        provides=[{"realm": tag, "key": "k0"},
                  {"realm": tag, "key": "k1"},
                  {"realm": tag, "key": "k2"}])["emitted"][0]
    hp = effect_of(owner, install_id, "host_prepare")
    settle_effect(service, hp, claim_effect(service, hp), "success", {})
    fiber = fiber_of(owner, install_id)
    on = one(admin, "SELECT v24.fiber_control(%s,'on',0,%s)",
             (fiber, tag + "-on"))
    assert on.get("disposition") == "committed", on
    admin.commit()
    episode = on["emitted"][0]

    initial = one(owner, """SELECT coalesce(jsonb_agg(jsonb_build_object(
        'seq', contribution_seq, 'released', released_at IS NOT NULL,
        'withdrawn', withdrawn_at IS NOT NULL) ORDER BY contribution_seq), '[]')
        FROM v24.slots WHERE fiber_id=%s""", (fiber,))
    owner.rollback()
    assert [row["seq"] for row in initial] == [0, 1, 2], initial
    assert not any(row["released"] or row["withdrawn"] for row in initial), initial

    for index in (1, 2, 3):
        base = released_slot_count(owner, fiber)
        off = one(admin, "SELECT v24.fiber_control(%s,'off',%s,%s)",
                  (fiber, index, "%s-off-%d" % (tag, index)))
        assert off.get("disposition") == "committed", off
        admin.commit()
        after = released_slot_count(owner, fiber)
        assert after == base + 1, (index, base, after)
        order = released_slot_order(owner, fiber)
        assert [seq for seq, _ts in order] == [2, 1, 0][:index], (index, order)
        for left, right in zip(order, order[1:]):
            assert left[1] < right[1], (index, order)
        withdrawn = one(owner, """SELECT count(*) FROM v24.slots
            WHERE fiber_id=%s AND withdrawn_at IS NULL""", (fiber,))
        owner.rollback()
        assert withdrawn == 0, (index, withdrawn)
        episode_row = one(owner, """SELECT jsonb_build_object(
            'state', state, 'closed_at', closed_at) FROM v24.episodes
            WHERE episode_id=%s""", (episode,))
        owner.rollback()
        if index < 3:
            assert episode_row["state"] == "retiring", (index, episode_row)
            assert episode_row["closed_at"] is None, (index, episode_row)
        else:
            assert episode_row["state"] == "closed", (index, episode_row)
            assert episode_row["closed_at"] is not None, (index, episode_row)
        print("[G4-D] off#%d: released=%d order=%s episode=%s closed_at=%s"
              % (index, after, [seq for seq, _ts in order],
                 episode_row["state"], episode_row["closed_at"]))

    assert released_slot_order(owner, fiber)[0][0] == 2
    assert released_slot_count(owner, fiber) == 3
    print("[G4-D] contribution_seq release order by released_at = [2, 1, 0]; "
          "exactly one slot per advance; episode closed only after #3")


def g4_f(owner, admin, service):
    """G4-F: an unknown-unquiesced release blocks close until inspect absent."""
    tag = "g4f"
    scope_id = new_scope(admin, tag, tag + "-root")
    install_id = admit_install(
        admin, scope_id, tag, tag + "-install")["emitted"][0]
    release_one = dispose(admin, install_id, tag + "-dispose-1")["emitted"][0]
    token = claim_effect(service, release_one)
    settled = settle_effect(service, release_one, token, "unknown", {})
    assert settled.get("disposition") == "committed", settled
    release = effect_row(owner, release_one)
    assert release["status"] == "unknown", release
    assert release["resource_quiesced_at"] is None, release
    pending = install_row(owner, install_id)
    assert pending["state"] == "dispose_pending", pending
    assert pending["disposed_at"] is None, pending
    closable = scope_closable(owner, scope_id)
    assert closable["ok"] is False, closable
    print("[G4-F] (a) release status=%s quiesced=%s install=%s disposed_at=%s "
          "closable.ok=%s blockers=%s"
          % (release["status"], release["resource_quiesced_at"],
             pending["state"], pending["disposed_at"], closable["ok"],
             json.dumps(closable["blockers"], sort_keys=True)))

    observed = []
    for index in range(1, 8):
        close_scope(admin, scope_id, "%s-close-%d" % (tag, index))
        row = scope_row(owner, scope_id)
        assert row["closed_at"] is None, (index, row)
        assert row["close_requested_at"] is not None, (index, row)
        closable = scope_closable(owner, scope_id)
        assert closable["ok"] is False, (index, closable)
        observed.append((index, closable["blockers"]["effects"]))
    print("[G4-F] repeated close: closed_at NULL, close_requested_at set, "
          "closable.ok false for %d calls (effects blocker=%d)"
          % (len(observed), observed[-1][1]))

    inspect_id = one(owner, """SELECT effect_id FROM v24.effects
        WHERE kind='inspect_resource' AND request->>'install_id'=%s
          AND status='ready' ORDER BY created_at, effect_id LIMIT 1""",
        (str(install_id),))
    owner.rollback()
    if inspect_id is None:
        emitted = dispose(admin, install_id, tag + "-dispose-inspect")["emitted"]
        assert len(emitted) == 1, emitted
        inspect_id = emitted[0]
    inspect = effect_row(owner, inspect_id)
    assert inspect["kind"] == "inspect_resource", inspect
    assert inspect["request"]["target"] == "host_release", inspect
    assert inspect["request"]["target_effect_id"] == str(release_one), inspect
    token = claim_effect(service, inspect_id)
    settled = settle_effect(service, inspect_id, token, "success",
                            inspect_receipt(owner, inspect_id, "absent"))
    assert settled.get("disposition") == "committed", settled
    squashed = effect_row(owner, release_one)
    assert squashed["resource_quiesced_at"] is not None, squashed
    assert effect_row(owner, inspect_id)["resource_quiesced_at"] is None
    assert install_row(owner, install_id)["state"] == "dispose_pending"

    second = dispose(admin, install_id, tag + "-dispose-2")
    assert second.get("disposition") == "committed", second
    assert len(second["emitted"]) == 1, second
    release_two = second["emitted"][0]
    assert str(release_two) != str(release_one), (release_two, release_one)
    row_two = effect_row(owner, release_two)
    assert row_two["kind"] == "host_release", row_two
    assert row_two["request"]["reservation"] == (
        "v24:host_release:" + str(release_two)), row_two
    assert count_kind(owner, install_id, "host_release") == 2
    settle_release(service, release_two)
    disposed = install_row(owner, install_id)
    assert disposed["state"] == "disposed", disposed
    assert disposed["disposed_at"] is not None, disposed
    print("[G4-F] (b) inspect=%s observed=absent target.quiesced=%s -> new "
          "release=%s reservation=%s -> install=%s disposed_at=%s"
          % (inspect_id, squashed["resource_quiesced_at"],
             release_two, row_two["request"]["reservation"],
             disposed["state"], disposed["disposed_at"]))

    closed = False
    for index in range(1, 10):
        response = close_scope(admin, scope_id, "%s-final-%d" % (tag, index))
        assert (response.get("emitted") or []) == [], response
        row = scope_row(owner, scope_id)
        if row["closed_at"] is not None:
            closed = True
            break
    assert closed, "close never reached closed_at after the tombstone"
    closable = scope_closable(owner, scope_id)
    assert closable["ok"] is True, closable
    print("[G4-F] (b) close reached closed_at=%s closable.ok=%s"
          % (scope_row(owner, scope_id)["closed_at"], closable["ok"]))

    tag2 = "g4f2"
    scope_two = new_scope(admin, tag2, tag2 + "-root")
    install_two = admit_install(
        admin, scope_two, tag2, tag2 + "-install",
        provides=[{"realm": tag2, "key": "k"}])["emitted"][0]
    hp = effect_of(owner, install_two, "host_prepare")
    token = claim_effect(service, hp)
    failed = settle_effect(service, hp, token, "failure", {})
    assert failed.get("disposition") == "committed", failed
    failed_install = install_row(owner, install_two)
    assert failed_install["state"] == "prepare_failed", failed_install
    assert failed_install["disposed_at"] is None, failed_install
    assert install_event_count(owner, install_two, "install_disposed") == 0
    closable = scope_closable(owner, scope_two)
    assert closable["ok"] is False, closable
    assert scope_row(owner, scope_two)["closed_at"] is None
    requested = close_scope(admin, scope_two, tag2 + "-close-1")
    assert requested.get("disposition") == "committed", requested
    assert scope_row(owner, scope_two)["closed_at"] is None
    assert install_row(owner, install_two)["state"] == "prepare_failed"
    print("[G4-F] (c) prepare failure: install=%s disposed_at=%s scope."
          "closed_at=NULL closable.ok=%s"
          % (failed_install["state"], failed_install["disposed_at"],
             closable["ok"]))


def g4_l(owner, admin, service):
    """G4-L: idempotent retry, fresh release after failure, terminal receipt."""
    tag = "g4l"
    scope_id = new_scope(admin, tag, tag + "-root")
    install_id = admit_install(
        admin, scope_id, tag, tag + "-install")["emitted"][0]
    first = dispose(admin, install_id, tag + "-dispose-1")
    assert first.get("disposition") == "committed", first
    assert len(first["emitted"]) == 1, first
    release_one = first["emitted"][0]

    before_state = state(owner)
    owner.rollback()
    before_counts = write_counts(owner)
    replay = dispose(admin, install_id, tag + "-dispose-1")
    assert replay == first, (replay, first)
    assert state(owner) == before_state, "dispose replay wrote rows"
    owner.rollback()
    after_counts = write_counts(owner)
    assert after_counts == before_counts, (before_counts, after_counts)
    print("[G4-L] same dispose key replay: byte-identical response, effects=%d "
          "requests=%d events=%d unchanged"
          % (after_counts[0], after_counts[1], after_counts[3]))

    token = claim_effect(service, release_one)
    failed = settle_effect(service, release_one, token, "failure", {})
    assert failed.get("disposition") == "committed", failed
    failed_row = effect_row(owner, release_one)
    assert failed_row["status"] == "failed", failed_row
    assert failed_row["resource_quiesced_at"] is not None, failed_row
    assert install_row(owner, install_id)["state"] == "dispose_pending"
    assert count_kind(owner, install_id, "host_release") == 1

    second = dispose(admin, install_id, tag + "-dispose-2")
    assert second.get("disposition") == "committed", second
    assert len(second["emitted"]) == 1, second
    release_two = second["emitted"][0]
    assert str(release_two) != str(release_one), (release_two, release_one)
    row_two = effect_row(owner, release_two)
    assert row_two["kind"] == "host_release", row_two
    assert row_two["request"]["reservation"] == (
        "v24:host_release:" + str(release_two)), row_two
    assert row_two["request"]["reservation"] != (
        failed_row["request"]["reservation"]), (row_two, failed_row)
    assert count_kind(owner, install_id, "host_release") == 2
    settle_release(service, release_two)
    disposed = install_row(owner, install_id)
    assert disposed["state"] == "disposed", disposed
    assert install_event_count(owner, install_id, "install_disposed") == 1
    print("[G4-L] after failure: release#1=%s status=failed quiesced=%s; new key "
          "-> release#2=%s reservation=%s, host_release=%d -> %s"
          % (release_one, failed_row["resource_quiesced_at"], release_two,
             row_two["request"]["reservation"],
             count_kind(owner, install_id, "host_release"), disposed["state"]))

    before_domain = domain_state(owner)
    owner.rollback()
    before_late = write_counts(owner)
    late = dispose(admin, install_id, tag + "-dispose-3")
    assert late == {"v": 1, "error": {"code": "already_terminal",
                                      "detail": {}}}, late
    assert domain_state(owner) == before_domain
    owner.rollback()
    after_late = write_counts(owner)
    assert after_late[0] == before_late[0] + 1, (before_late, after_late)
    assert after_late[1] == before_late[1] + 1, (before_late, after_late)
    assert after_late[2] == before_late[2] + 1, (before_late, after_late)
    assert after_late[3] == before_late[3], (before_late, after_late)
    assert count_kind(owner, install_id, "host_release") == 2
    print("[G4-L] disposed + new key -> already_terminal W1 (+1 failed effect/"
          "request), host_release stays 2")

    tag2 = "g4l2"
    scope_two = new_scope(admin, tag2, tag2 + "-root")
    install_two = admit_install(
        admin, scope_two, tag2, tag2 + "-install")["emitted"][0]
    leave = dispose(admin, install_two, tag2 + "-dispose-1")
    release_unknown = leave["emitted"][0]
    token = claim_effect(service, release_unknown)
    settle_effect(service, release_unknown, token, "unknown", {})
    inspect_response = dispose(admin, install_two, tag2 + "-dispose-2")
    assert inspect_response.get("disposition") == "committed", inspect_response
    assert len(inspect_response["emitted"]) == 1, inspect_response
    inspect_id = inspect_response["emitted"][0]
    assert effect_row(owner, inspect_id)["kind"] == "inspect_resource"

    before_state = state(owner)
    owner.rollback()
    before_counts = write_counts(owner)
    replay_inspect = dispose(admin, install_two, tag2 + "-dispose-2")
    assert replay_inspect == inspect_response, (replay_inspect, inspect_response)
    assert state(owner) == before_state, "inspect-emitting dispose replay wrote rows"
    owner.rollback()
    assert write_counts(owner) == before_counts
    assert count_kind(owner, install_two, "inspect_resource") == 1
    print("[G4-L] same inspect-emitting dispose key replay: byte-identical "
          "response, inspect_resource=1, no new effect/event")

    token = claim_effect(service, inspect_id)
    unknown_body = inspect_receipt(owner, inspect_id, "unknown", cls="unknown")
    inspect_settled = settle_effect(service, inspect_id, token, "unknown",
                                    unknown_body)
    assert inspect_settled.get("disposition") == "committed", inspect_settled
    replay_outcome = {"v": 1, "class": "unknown", "claim": token,
                      "body": unknown_body}
    before_state = state(owner)
    owner.rollback()
    replay_settled = advance(service, inspect_id, replay_outcome)
    service.commit()
    assert replay_settled.get("disposition") == "replay", replay_settled
    assert replay_settled["effect_id"] == inspect_id, replay_settled
    assert replay_settled["emitted"] == [], replay_settled
    assert state(owner) == before_state, "inspect settlement replay wrote rows"
    owner.rollback()
    print("[G4-L] same inspect settlement replay: disposition=replay, "
          "effect_id=%s, emitted=[], ten-table byte-equal" % (inspect_id,))


def g4_m(owner, admin, service):
    """G4-M: eight zero-write/write-class negatives (M-1..M-8)."""
    def leaf(prefix):
        scope = new_scope(admin, prefix, prefix + "-root")
        install = admit_install(
            admin, scope, prefix, prefix + "-install")["emitted"][0]
        return scope, install

    # M-1: new key close on an already closed scope -> W1 already_terminal.
    tag1 = "g4m1"
    scope_one = new_scope(admin, tag1, tag1 + "-root")
    for index in range(1, 12):
        close_scope(admin, scope_one, "%s-close-%d" % (tag1, index))
        if scope_row(owner, scope_one)["closed_at"] is not None:
            break
    assert scope_row(owner, scope_one)["closed_at"] is not None
    expect_w1(owner, lambda: close_scope(admin, scope_one, tag1 + "-late"),
              "already_terminal", "M-1 close on already-closed scope")

    # M-2: new key dispose on a disposed install -> W1 already_terminal.
    tag2 = "g4m2"
    scope_two, install_two = leaf(tag2)
    release_two = dispose(admin, install_two, tag2 + "-dispose-1")["emitted"][0]
    settle_release(service, release_two)
    assert install_row(owner, install_two)["state"] == "disposed"
    expect_w1(owner, lambda: dispose(admin, install_two, tag2 + "-dispose-2"),
              "already_terminal", "M-2 dispose on disposed install")

    # M-3: inspect claim whose target is not unknown/already quiesced -> W0.
    tag3 = "g4m3"
    scope_three, install_three, hp = prepare_unknown_fixture(
        owner, admin, service, tag3)
    inspect_id = dispose(admin, install_three, tag3 + "-dispose-1")["emitted"][0]
    # Seeded fixture / non-public path: force the inspect target out of the
    # inspectable state (quiesced, then not-unknown) for the claim gate.
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.effects SET resource_quiesced_at=now() "
                    "WHERE effect_id=%s", (hp,))
    owner.commit()
    assert_claim_invalid(owner, service, inspect_id,
                         "M-3 already-quiesced inspect target", tag="G4-M")
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.effects SET resource_quiesced_at=NULL "
                    "WHERE effect_id=%s", (hp,))
    owner.commit()
    original = effect_row(owner, hp)
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.effects SET status='succeeded', outcome=%s, "
                    "settled_at=now() WHERE effect_id=%s",
                    (Json({"seed": True}), hp))
    owner.commit()
    assert_claim_invalid(owner, service, inspect_id,
                         "M-3 non-unknown inspect target", tag="G4-M")
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.effects SET status=%s, outcome=%s, settled_at=%s "
                    "WHERE effect_id=%s",
                    (original["status"], Json(original["outcome"]),
                     original["settled_at"], hp))
    owner.commit()

    # M-4: host_release success while the install is not dispose_pending -> W0
    # receipt_conflict.  Seeded fixture / non-public path: rewrite the install
    # state back so the settlement's precheck conflicts.
    tag4 = "g4m4"
    scope_four, install_four = leaf(tag4)
    release_four = dispose(admin, install_four, tag4 + "-dispose-1")["emitted"][0]
    token = claim_effect(service, release_four)
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.installs SET state='installed', "
                    "dispose_effect=NULL, disposed_at=NULL WHERE install_id=%s",
                    (install_four,))
    owner.commit()
    expect_w0(owner, lambda: settle_effect(
        service, release_four, token, "success", {}), "receipt_conflict",
        "M-4 release success while install is not dispose_pending")
    assert effect_row(owner, release_four)["status"] == "claimed"

    # M-5: seeded owner cycle on dispose -> W1 cleanup_cycle, domain zero-write.
    # Seeded fixture / non-public path: direct owner-pair rewrite forms a cycle.
    tag5 = "g4m5"
    creator = uuid4()
    seed_effect(owner, creator)
    cycle_scope = uuid4()
    seed_scope(owner, cycle_scope, creator)
    cycle, _fibers, _episodes = seed_owner_cycle(
        owner, creator=creator, scope_id=cycle_scope)
    owner.commit()
    response = expect_w1(
        owner, lambda: dispose(admin, cycle[0], tag5 + "-dispose"),
        "cleanup_cycle", "M-5 seeded owner cycle on dispose")
    detail = response["error"]["detail"]
    assert len(detail["path"]) == 4, detail
    assert detail["path"][0] == detail["path"][-1] == str(cycle[0]), detail

    # M-6: close with an unsettled install never writes closed_at.
    tag6 = "g4m6"
    scope_six, install_six = leaf(tag6)
    release_six = dispose(admin, install_six, tag6 + "-dispose-1")["emitted"][0]
    assert effect_row(owner, release_six)["status"] == "ready"
    for index in range(1, 7):
        close_scope(admin, scope_six, "%s-close-%d" % (tag6, index))
        row = scope_row(owner, scope_six)
        assert row["closed_at"] is None, (index, row)
        assert row["close_requested_at"] is not None, (index, row)
        assert scope_closable(owner, scope_six)["ok"] is False, index
    assert install_row(owner, install_six)["state"] == "dispose_pending"
    assert effect_row(owner, release_six)["status"] == "ready"
    print("[G4-M] M-6 close with an unsettled ready release: closed_at stays "
          "NULL, close_requested_at set, install=%s"
          % install_row(owner, install_six)["state"])

    # M-7: malformed inspect outcome -> W0 invalid_outcome, effect stays claimed.
    tag7 = "g4m7"
    scope_seven, install_seven, hp_seven = prepare_unknown_fixture(
        owner, admin, service, tag7)
    inspect_seven = dispose(
        admin, install_seven, tag7 + "-dispose-1")["emitted"][0]
    token = claim_effect(service, inspect_seven)
    malformed = {"kind": "inspect_resource", "result": {"v": 1,
                                                        "observed": "weird"}}
    expect_w0(owner, lambda: settle_effect(
        service, inspect_seven, token, "success", malformed), "invalid_outcome",
        "M-7 malformed inspect outcome")
    assert effect_row(owner, inspect_seven)["status"] == "claimed"

    # M-8: dispose with an unknown-unquiesced release emits only inspect.
    tag8 = "g4m8"
    scope_eight, install_eight = leaf(tag8)
    release_eight = dispose(
        admin, install_eight, tag8 + "-dispose-1")["emitted"][0]
    token = claim_effect(service, release_eight)
    settle_effect(service, release_eight, token, "unknown", {})
    again = dispose(admin, install_eight, tag8 + "-dispose-2")
    assert again.get("disposition") == "committed", again
    assert len(again["emitted"]) == 1, again
    inspect_eight = effect_row(owner, again["emitted"][0])
    assert inspect_eight["kind"] == "inspect_resource", inspect_eight
    assert inspect_eight["request"]["target"] == "host_release", inspect_eight
    assert inspect_eight["request"]["target_effect_id"] == str(release_eight), (
        inspect_eight)
    assert count_kind(owner, install_eight, "host_release") == 1
    pending = install_row(owner, install_eight)
    assert pending["state"] == "dispose_pending", pending
    assert pending["disposed_at"] is None, pending
    print("[G4-M] M-8 unknown release -> dispose emits only inspect_resource "
          "target=%s, host_release stays 1, install=%s"
          % (inspect_eight["request"]["target_effect_id"], pending["state"]))
    print("[G4-M] M-1/M-2/M-5 W1 receipts (domain byte-equal + one failed "
          "effect/request); M-3/M-4/M-7 W0 ten-table byte-equal; M-6 no "
          "closed_at; M-8 inspect-only recovery")


def g4_p(owner, admin, service):
    """G4-P: the install tombstone lands only after every obligation clears."""
    tag = "g4p"
    scope_id = new_scope(admin, tag, tag + "-root")
    root = admit_install(
        admin, scope_id, tag + "-root", tag + "-root-install",
        provides=[{"realm": tag, "key": "k0"},
                  {"realm": tag, "key": "k1"}])["emitted"][0]
    hp = effect_of(owner, root, "host_prepare")
    settle_effect(service, hp, claim_effect(service, hp), "success", {})
    root_fiber = fiber_of(owner, root)
    on = one(admin, "SELECT v24.fiber_control(%s,'on',0,%s)",
             (root_fiber, tag + "-root-on"))
    assert on.get("disposition") == "committed", on
    admin.commit()
    episode = on["emitted"][0]
    child = admit_install(
        admin, scope_id, tag + "-child", tag + "-child-install",
        owner_fiber=root_fiber)["emitted"][0]
    assert install_row(owner, child)["state"] == "installed"

    contributions = one(owner, """SELECT coalesce(jsonb_agg(jsonb_build_object(
        'seq', contribution_seq, 'released', released_at IS NOT NULL)
        ORDER BY contribution_seq), '[]') FROM v24.slots WHERE fiber_id=%s""",
        (root_fiber,))
    owner.rollback()
    assert [row["seq"] for row in contributions] == [0, 1], contributions
    assert not any(row["released"] for row in contributions), contributions

    first = dispose(admin, root, tag + "-dispose-1")
    assert first.get("disposition") == "committed", first
    assert len(first["emitted"]) == 1, first
    child_release = first["emitted"][0]
    child_release_row = effect_row(owner, child_release)
    assert child_release_row["kind"] == "host_release", child_release_row
    assert child_release_row["request"]["install_id"] == str(child), (
        child_release_row)
    assert install_row(owner, root)["state"] == "dispose_pending"
    assert install_row(owner, root)["disposed_at"] is None
    settle_release(service, child_release)
    child_row = install_row(owner, child)
    assert child_row["state"] == "disposed", child_row
    assert child_row["disposed_at"] is not None, child_row

    root_release = None
    stages = 0
    for index in range(2, 9):
        response = dispose(admin, root, "%s-dispose-%d" % (tag, index))
        assert response.get("disposition") == "committed", response
        stages += 1
        if response["emitted"]:
            assert len(response["emitted"]) == 1, response
            candidate = effect_row(owner, response["emitted"][0])
            assert candidate["kind"] == "host_release", candidate
            assert candidate["request"]["install_id"] == str(root), candidate
            root_release = response["emitted"][0]
            break
    assert root_release is not None, "root never emitted its release"

    # Before settlement: the owner is still pending with no tombstone, while
    # the child, contributions and episode are already complete.
    before = install_row(owner, root)
    assert before["state"] == "dispose_pending", before
    assert before["disposed_at"] is None, before
    fiber_before = one(owner, "SELECT to_jsonb(f) FROM v24.fibers f "
                              "WHERE f.fiber_id=%s", (root_fiber,))
    owner.rollback()
    assert fiber_before["disposed_at"] is not None, fiber_before
    order = released_slot_order(owner, root_fiber)
    assert [seq for seq, _ts in order] == [1, 0], order
    assert count_kind(owner, root, "host_release") == 1
    episode_before = one(owner, """SELECT jsonb_build_object(
        'state', state, 'closed_at', closed_at) FROM v24.episodes
        WHERE episode_id=%s""", (episode,))
    owner.rollback()
    assert episode_before["state"] == "closed", episode_before
    assert episode_before["closed_at"] is not None, episode_before
    assert install_row(owner, child)["state"] == "disposed"
    assert install_event_count(owner, root, "install_disposed") == 0
    print("[G4-P] pre-settle: install=%s disposed_at=%s fiber.disposed_at=%s "
          "slots(order)=%s episode=%s child=%s install_disposed=%d"
          % (before["state"], before["disposed_at"], fiber_before["disposed_at"],
             [seq for seq, _ts in order], episode_before["state"],
             install_row(owner, child)["state"],
             install_event_count(owner, root, "install_disposed")))

    settle_release(service, root_release)
    after = install_row(owner, root)
    assert after["state"] == "disposed", after
    assert after["disposed_at"] is not None, after
    fiber_after = one(owner, "SELECT disposed_at FROM v24.fibers "
                             "WHERE fiber_id=%s", (root_fiber,))
    owner.rollback()
    assert fiber_after is not None, fiber_after
    assert [seq for seq, _ts in released_slot_order(owner, root_fiber)] == [1, 0]
    episode_after = one(owner, """SELECT jsonb_build_object(
        'state', state, 'closed_at', closed_at) FROM v24.episodes
        WHERE episode_id=%s""", (episode,))
    owner.rollback()
    assert episode_after["state"] == "closed" and (
        episode_after["closed_at"] is not None), episode_after
    assert install_row(owner, child)["state"] == "disposed"
    assert install_event_count(owner, root, "install_disposed") == 1
    assert install_event_count(owner, child, "install_disposed") == 1
    assert count_kind(owner, root, "host_release") == 1
    assert count_kind(owner, child, "host_release") == 1
    print("[G4-P] post-settle: install=%s disposed_at=%s fiber.disposed_at=%s "
          "(fiber_disposed=%d) slots(order)=%s episode=%s child=%s "
          "install_disposed(root=%d child=%d)"
          % (after["state"], after["disposed_at"], fiber_after,
             one(owner, "SELECT count(*) FROM v24.events WHERE event_kind="
                        "'fiber_disposed' AND entity_id=%s",
                 (root_fiber,)),
             [seq for seq, _ts in released_slot_order(owner, root_fiber)],
             episode_after["state"], install_row(owner, child)["state"],
             install_event_count(owner, root, "install_disposed"),
             install_event_count(owner, child, "install_disposed")))
    owner.rollback()


def g4_q(owner, admin, service):
    """G4-Q: one bounded root stage; cleanup_pending non-increasing to zero."""
    tag = "g4q"
    creator = uuid4()
    seed_effect(owner, creator)
    scope_id = uuid4()
    seed_scope(owner, scope_id, creator)
    # Seeded fixture / non-public path: an installed 3-level owner chain A -> B
    # -> C with closed episodes, so the dispose walk never leaves the install
    # stage (its only job here is the owner cascade and budget).
    levels, fibers, episodes = [], [], []
    for _ in range(3):
        install = seed_install(owner, scope_id=scope_id, creator=creator)
        fiber = seed_fiber(owner, install_id=install, scope_id=scope_id,
                           creator=creator)
        episode = seed_episode(owner, fiber_id=fiber, creator=creator,
                               state="closed",
                               closed_at=datetime.now(timezone.utc))
        levels.append(install)
        fibers.append(fiber)
        episodes.append(episode)
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.installs SET owner_fiber_id=%s, "
                    "owner_episode_id=%s WHERE install_id=%s",
                    (fibers[0], episodes[0], levels[1]))
        cur.execute("UPDATE v24.installs SET owner_fiber_id=%s, "
                    "owner_episode_id=%s WHERE install_id=%s",
                    (fibers[1], episodes[1], levels[2]))
    owner.commit()

    initial_pending = cleanup_pending(owner, scope_id)
    assert initial_pending == 6, initial_pending
    before = state(owner)
    owner.rollback()
    response = dispose(admin, levels[0], tag + "-dispose-1")
    after = state(owner)
    owner.rollback()
    assert response.get("disposition") == "committed", response
    assert len(response["emitted"]) <= 16, response
    assert len(response["emitted"]) == 1, response
    leaf_release = response["emitted"][0]
    release_row = effect_row(owner, leaf_release)
    assert release_row["kind"] == "host_release", release_row
    assert release_row["request"]["install_id"] == str(levels[2]), release_row
    rows_changed = changed_rows(before, after)
    assert rows_changed <= 16, rows_changed
    assert rows_changed > 0, rows_changed
    for index, install in enumerate(levels):
        row = install_row(owner, install)
        assert row["state"] == "dispose_pending", (index, row)
        assert row["disposed_at"] is None, (index, row)
    pending = cleanup_pending(owner, scope_id)
    assert pending == initial_pending, pending
    assert count_kind(owner, levels[0], "host_release") == 0
    assert count_kind(owner, levels[1], "host_release") == 0
    assert count_kind(owner, levels[2], "host_release") == 1
    sequence = [initial_pending, pending]
    print("[G4-Q] single root dispose: emitted=%d rows_changed=%d pending=%d "
          "(init %d) root=%s deep=%s; only leaf release=%s"
          % (len(response["emitted"]), rows_changed, pending,
             initial_pending, install_row(owner, levels[0])["state"],
             install_row(owner, levels[2])["state"], leaf_release))

    settle_release(service, leaf_release)
    assert install_row(owner, levels[2])["state"] == "disposed"
    pending = cleanup_pending(owner, scope_id)
    assert pending == 4 and pending < sequence[-1], (pending, sequence)
    sequence.append(pending)
    for stage, expected_after in ((2, 2), (3, 0)):
        response = dispose(admin, levels[0], "%s-dispose-%d" % (tag, stage))
        assert response.get("disposition") == "committed", response
        assert len(response["emitted"]) == 1, response
        pending = cleanup_pending(owner, scope_id)
        assert pending == expected_after + 2, (stage, pending)
        assert pending <= sequence[-1], (stage, pending, sequence)
        sequence.append(pending)
        assert install_row(owner, levels[0])["state"] == "dispose_pending"
        released = response["emitted"][0]
        row = effect_row(owner, released)
        assert row["kind"] == "host_release", row
        settle_release(service, released)
        pending = cleanup_pending(owner, scope_id)
        assert pending == expected_after, (stage, pending)
        assert pending < sequence[-1], (stage, pending, sequence)
        sequence.append(pending)
        print("[G4-Q] stage=%d successor=%s clears a counted install/effect: "
              "pending=%d" % (stage, released, pending))
    assert sequence == [6, 6, 4, 4, 2, 2, 0], sequence
    assert cleanup_pending(owner, scope_id) == 0
    assert all(install_row(owner, install)["state"] == "disposed"
               for install in levels)
    print("[G4-Q] cleanup_pending sequence=%s (non-increasing; strict drops "
          "only when a counted obligation clears; final 0)" % (sequence,))


def main():
    with server_helper_scope(), setup_db() as db:
        owner = db.connect()
        with owner.cursor() as cur:
            cur.execute("SET ROLE v24_owner")
        owner.commit()
        admin = db.connect("admin")
        service = db.connect("service")
        g4_a(owner)
        g4_b(owner)
        g4_c(owner, admin, service)
        g4_d(owner, admin, service)
        g4_e(owner, admin, service)
        g4_cascade(owner, admin, service)
        g4_f(owner, admin, service)
        g4_g(owner, admin, service)
        g4_h(owner, admin, service)
        g4_i(owner, admin, service)
        g4_j(owner, admin, service)
        g4_k(owner, admin, service)
        g4_l(owner, admin, service)
        g4_m(owner, admin, service)
        g4_n(owner, admin, service)
        g4_o(owner, admin, service)
        g4_p(owner, admin, service)
        g4_q(owner, admin, service)
        _assert_closed_catalog(owner)
    print("[passed] v24 S5 W1-W4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
