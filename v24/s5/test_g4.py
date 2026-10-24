"""G4 (S5 W1): cleanup graph, owner cascade and cycle rejection.

Only W1 is implemented in this gate.  The fixtures for G4-A/B/E are seeded by
direct owner-role DML (the same precedent as G2b-G) and are explicitly marked
as seeded, non-public shapes.  G4-E's cycle and the 65-node chain are seeded
defects used to exercise defensive reads; the public admission path can never
construct them.  No socket is opened and no external IO runs inside a
transaction.
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


def manifest_bytes(identity: str, provides=()) -> bytes:
    return json.dumps(
        {
            "identity": identity,
            "version": "1",
            "requires": [],
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


def admit_install(admin, scope_id, identity, key, provides=(), owner_fiber=None):
    effect_id, outcome = command(admin, key, "command_install", {
        "scope_id": str(scope_id),
        "owner_fiber_id": str(owner_fiber) if owner_fiber is not None else None,
        "manifest_bytes": base64.b64encode(
            manifest_bytes(identity, provides)).decode(),
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


def assert_claim_invalid(owner, service, effect_id, label):
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
    print("[G4-N] %s: invalid_args, ten-table byte-equal, attempt/fence 0"
          % (label[len("G4-N "):] if label.startswith("G4-N ") else label))


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
        g4_e(owner, admin, service)
        g4_cascade(owner, admin, service)
        g4_g(owner, admin, service)
        g4_h(owner, admin, service)
        g4_i(owner, admin, service)
        g4_j(owner, admin, service)
        g4_k(owner, admin, service)
        g4_n(owner, admin, service)
        g4_o(owner, admin, service)
        _assert_closed_catalog(owner)
    print("[passed] v24 S5 W1-W3")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
