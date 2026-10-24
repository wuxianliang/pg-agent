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
from pathlib import Path
from uuid import uuid4

S1 = Path(__file__).resolve().parent.parent / "s1"
S2 = Path(__file__).resolve().parent.parent / "s2"
for _path in (S1, S2):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from setup_db import _assert_closed_catalog, server_helper_scope, setup_db  # noqa: E402
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


def manifest_bytes(identity: str) -> bytes:
    return json.dumps(
        {
            "identity": identity,
            "version": "1",
            "requires": [],
            "provides": [],
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
    close_probe = one(owner, "SELECT v24.dispose_stage(%s,%s,'close')",
                      (root_install, uuid4()))
    assert close_probe["error"]["error"]["code"] == "invalid_args", close_probe
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
        _assert_closed_catalog(owner)
    print("[passed] v24 S5 W1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
