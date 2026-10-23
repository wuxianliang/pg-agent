"""G3a (W1-W3): resolver, closure/reconcile infra, install admission.

W1 covers the read-only resolver.  W2 covers the closure edges, the internal
kind's claim exclusion, the unique unsettled-reconcile index and the fail-closed
closure.  W3 covers the per-install inactive fiber and child admission.  The
born-settled/settle[] applier paths are exercised by W4, where a producer
exists; this file does not fake them.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import base64
import json
import sys
import time
from pathlib import Path
from uuid import uuid4

import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json

S1 = Path(__file__).resolve().parent.parent / "s1"
if str(S1) not in sys.path:
    sys.path.insert(0, str(S1))

from setup_db import EXPECTED_TABLES, _assert_closed_catalog, server_helper_scope, setup_db  # noqa: E402
from test_ddl import DIGEST, effect, insert, scope  # noqa: E402


def one(conn, statement, params=()):
    with conn.cursor() as cur:
        cur.execute(statement, params)
        return cur.fetchone()[0]


def state(conn):
    result = {}
    for table in sorted(EXPECTED_TABLES):
        result[table] = one(conn, sql.SQL(
            "SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text), '[]') "
            "FROM v24.{} t").format(sql.Identifier(table)))
    return result


def advance(conn, effect_id, outcome):
    return one(conn, "SELECT v24.advance(%s,%s)", (effect_id, Json(outcome)))


def sqlstate(conn, code, action, message=None):
    with conn.cursor() as cur:
        cur.execute("SAVEPOINT g3a_probe")
    try:
        action()
    except psycopg2.Error as exc:
        actual, text = exc.pgcode, str(exc)
        with conn.cursor() as cur:
            cur.execute("ROLLBACK TO SAVEPOINT g3a_probe")
            cur.execute("RELEASE SAVEPOINT g3a_probe")
        assert actual == code, (actual, code, text)
        if message is not None:
            assert message in text, text
        return
    with conn.cursor() as cur:
        cur.execute("ROLLBACK TO SAVEPOINT g3a_probe")
        cur.execute("RELEASE SAVEPOINT g3a_probe")
    raise AssertionError(f"expected SQLSTATE {code}")


def command(conn, key, kind, payload):
    encoded = one(conn, "SELECT encode(convert_to(v24.canonical_json(%s),'UTF8'),'base64')",
                  (Json(payload),))
    effect_id = one(conn, "SELECT v24.effect_id_for(v24.principal_id(session_user),%s,%s)",
                    (key, kind))
    return effect_id, {"v": 1, "class": "command", "claim": None, "body": {
        "op": "admit_and_apply", "kind": kind, "request_key": key,
        "payload": payload, "canonical_bytes": encoded}}


def claim(lease=300000):
    return {"v": 1, "class": "claim", "claim": None, "body": {"lease_ms": lease}}


def seed_effect(conn, effect_id, **kwargs):
    with conn.cursor() as cur:
        effect(cur, effect_id, **kwargs)


def seed_scope(conn, scope_id, creator, **kwargs):
    with conn.cursor() as cur:
        scope(cur, scope_id, creator, **kwargs)


def seed_install(conn, *, scope_id, creator, requires=None, provides=None,
                 state="installed", owner_fiber_id=None, owner_episode_id=None):
    install_id = uuid4()
    with conn.cursor() as cur:
        insert(cur, "installs",
               install_id=install_id, scope_id=scope_id,
           owner_fiber_id=owner_fiber_id, owner_episode_id=owner_episode_id,
           identity=f"i-{install_id}", version="1",
           manifest=Json({"identity": f"i-{install_id}"}),
           manifest_digest=DIGEST,
           requires=Json(requires or []), provides=Json(provides or []),
           artifact_digest=b"", adapter_digest=DIGEST,
           owner_principal=uuid4(), state=state, created_by_effect=creator)
    return install_id


def seed_fiber(conn, *, install_id, scope_id, creator, want_on=False,
               current_episode_id=None):
    fiber_id = uuid4()
    with conn.cursor() as cur:
        insert(cur, "fibers", fiber_id=fiber_id, install_id=install_id,
           scope_id=scope_id, want_on=want_on, control_seq=0,
           current_episode_id=current_episode_id, next_contribution_seq=0,
           created_by_effect=creator)
    return fiber_id


def seed_episode(conn, *, fiber_id, creator, epoch=1, state="active", **extra):
    episode_id = uuid4()
    values = dict(episode_id=episode_id, fiber_id=fiber_id, epoch=epoch,
                  activation_effect=creator, state=state, target_seq=0)
    values.update(extra)
    with conn.cursor() as cur:
        insert(cur, "episodes", **values)
    return episode_id


def seed_slot(conn, *, fiber_id, episode_id, realm, key, seq=1, **extra):
    slot_id = uuid4()
    values = dict(slot_id=slot_id, fiber_id=fiber_id, episode_id=episode_id,
                  realm=realm, key=key, descriptor=Json({"k": key}),
                  descriptor_digest=DIGEST, contribution_seq=seq)
    values.update(extra)
    with conn.cursor() as cur:
        insert(cur, "slots", **values)
    return slot_id


def provider(conn, scope_id, realm, key, creator, *, withdrawn=False, released=False,
             episode_state="active", fiber_disposed=False):
    """Migration-owner seed: install + inactive/active fiber + episode + slot."""
    iid = seed_install(conn, scope_id=scope_id, creator=creator)
    fid = seed_fiber(conn, install_id=iid, scope_id=scope_id, creator=creator)
    eid = seed_episode(conn, fiber_id=fid, creator=creator, state=episode_state)
    extra = {}
    if withdrawn or released:
        extra["withdrawn_at"] = datetime.now(timezone.utc)
    if released:
        extra["released_at"] = datetime.now(timezone.utc)
    slot_id = seed_slot(conn, fiber_id=fid, episode_id=eid, realm=realm, key=key, **extra)
    with conn.cursor() as cur:
        cur.execute("UPDATE v24.fibers SET current_episode_id=%s WHERE fiber_id=%s", (eid, fid))
        if fiber_disposed:
            cur.execute("UPDATE v24.fibers SET disposed_at=now(), want_on=false WHERE fiber_id=%s",
                        (fid,))
        if fiber_disposed:
            cur.execute("UPDATE v24.slots SET withdrawn_at=now() WHERE slot_id=%s", (slot_id,))
    return {"install": iid, "fiber": fid, "episode": eid, "slot": slot_id}


def resolve_rows(conn, scope_id, keys):
    return one(conn, """SELECT coalesce(jsonb_agg(to_jsonb(r)), '[]'::jsonb)
        FROM v24.resolve(%s, %s) r""", (scope_id, keys))


def resolver_contract(owner):
    row = one(owner, """SELECT jsonb_build_object(
            'prosecdef', p.prosecdef, 'volatile', p.provolatile,
            'args', pg_get_function_identity_arguments(p.oid),
            'ret', pg_get_function_result(p.oid))
        FROM pg_proc p WHERE p.pronamespace='v24'::regnamespace
          AND p.proname='resolve'""")
    assert row["prosecdef"] is True, row
    assert row["volatile"] == "s", row
    assert row["args"] == "p_scope_id uuid, p_keys text[]", row
    assert "key text" in row["ret"] and "live boolean" in row["ret"], row
    print("[G3a-A1] resolve is STABLE/INVOKER with the frozen six-column shape")


def resolver_shape_and_writes(owner):
    eid = uuid4()
    seed_effect(owner, eid)
    root = uuid4()
    seed_scope(owner, root, eid, default_realm="ra")
    p = provider(owner, root, "ra", "k", eid)
    owner.commit()
    before = state(owner)
    rows = resolve_rows(owner, root, ["k", "missing"])
    assert len(rows) == 2, rows
    assert rows[0]["key"] == "k" and rows[0]["live"] is True, rows[0]
    assert rows[0]["slot_id"] == str(p["slot"]), rows[0]
    assert rows[0]["provider_episode_id"] == str(p["episode"]), rows[0]
    assert rows[1]["key"] == "missing" and rows[1]["live"] is False, rows[1]
    assert rows[1]["slot_id"] is None, rows[1]
    assert state(owner) == before, "resolve wrote rows"
    print("[G3a-A2] six columns, input order, unresolved live=false, zero writes")


def resolver_routing(owner):
    eid = uuid4()
    seed_effect(owner, eid)
    root, child = uuid4(), uuid4()
    seed_scope(owner, root, eid, default_realm="r1")
    seed_scope(owner, child, eid, parent_id=root, root_id=root,
          route_path=[root, child], realm_routes=Json({"k": "r2", "only-r1": "r2"}))
    p1 = provider(owner, root, "r1", "k", eid)
    p2 = provider(owner, root, "r2", "k", eid)
    provider(owner, root, "r1", "only-r1", eid)
    owner.commit()
    leaf = resolve_rows(owner, child, ["k", "only-r1"])
    assert leaf[0]["live"] is True and leaf[0]["slot_id"] == str(p2["slot"]), leaf[0]
    # routed to r2, but the only slot lives in r1: no cross-realm fallback
    assert leaf[1]["live"] is False and leaf[1]["slot_id"] is None, leaf[1]
    top = resolve_rows(owner, root, ["k"])
    assert top[0]["live"] is True and top[0]["slot_id"] == str(p1["slot"]), top[0]
    print("[G3a-A3] leaf-first routing, same key coexists across realms, no fallback")


def resolver_live_predicate(owner):
    eid = uuid4()
    seed_effect(owner, eid)
    root, closing = uuid4(), uuid4()
    seed_scope(owner, root, eid, default_realm="rp")
    seed_scope(owner, closing, eid, default_realm="rp",
          close_requested_at=datetime.now(timezone.utc))
    provider(owner, root, "rp", "live", eid)
    provider(owner, root, "rp", "withdrawn", eid, withdrawn=True)
    provider(owner, root, "rp", "released", eid, released=True)
    provider(owner, root, "rp", "retiring", eid, episode_state="retiring")
    provider(owner, root, "rp", "disposed", eid, fiber_disposed=True)
    provider(owner, closing, "rp", "closing", eid)
    owner.commit()
    rows = {r["key"]: r for r in resolve_rows(
        owner, root, ["live", "withdrawn", "released", "retiring", "disposed", "closing"])}
    assert rows["live"]["live"] is True, rows["live"]
    for key in ("withdrawn", "released", "retiring", "disposed", "closing"):
        assert rows[key]["live"] is False, (key, rows[key])
    print("[G3a-A4] live predicate rejects withdrawn/released/retiring/disposed/closing")


def resolver_limit(owner):
    eid = uuid4()
    seed_effect(owner, eid)
    root = uuid4()
    seed_scope(owner, root, eid, default_realm="ra")
    owner.commit()
    sqlstate(owner, "22023", lambda: one(
        owner, "SELECT count(*) FROM v24.resolve(%s,%s)", (root, ["k"] * 257)))
    assert resolve_rows(owner, root, []) == []
    print("[G3a-A5] key cap 256 -> 22023; empty key set -> empty result")


def reconcile_index_and_claim(owner, service):
    eid = uuid4()
    seed_effect(owner, eid)
    root = uuid4()
    seed_scope(owner, root, eid, default_realm="ra")
    iid = seed_install(owner, scope_id=root, creator=eid)
    fid = seed_fiber(owner, install_id=iid, scope_id=root, creator=eid)
    first, second = uuid4(), uuid4()
    seed_effect(owner, first, kind="fiber_reconcile", fiber_id=fid)
    owner.commit()
    sqlstate(owner, "23505", lambda: seed_effect(
        owner, second, kind="fiber_reconcile", fiber_id=fid),
        "u_effects_reconcile")
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.effects SET status='succeeded', outcome=%s, "
                    "settled_at=now() WHERE effect_id=%s", (Json({"ok": True}), first))
    seed_effect(owner, second, kind="fiber_reconcile", fiber_id=fid)
    owner.commit()
    before = state(owner)
    response = advance(service, second, claim())
    assert response == {"v": 1, "error": {"code": "invalid_args", "detail": {}}}, response
    service.commit()
    assert state(owner) == before, "claim rejection wrote rows"
    owner.rollback()
    print("[G3a-W2a] one unsettled reconcile per fiber; fiber_reconcile is not claimable")


def closure_fail_closed_and_seam(owner, service):
    missing = uuid4()
    eid, outcome = command(service, "g3a-missing", "command_fiber_control",
                           {"fiber_id": str(missing), "action": "on",
                            "expected_control_seq": 0})
    before = state(owner)
    assert advance(service, eid, outcome)["error"]["code"] == "retry_with_closure"
    service.commit()
    assert state(owner) == before, "closure refusal wrote rows"
    owner.rollback()

    creator = uuid4()
    seed_effect(owner, creator)
    root = uuid4()
    seed_scope(owner, root, creator, default_realm="ra")
    iid = seed_install(owner, scope_id=root, creator=creator)
    fid = seed_fiber(owner, install_id=iid, scope_id=root, creator=creator)
    owner.commit()
    eid, outcome = command(service, "g3a-seam", "command_fiber_control",
                           {"fiber_id": str(fid), "action": "on",
                            "expected_control_seq": 0})
    activated = advance(service, eid, outcome)
    assert activated.get("disposition") == "committed", activated
    service.commit()
    owner.rollback()
    print("[G3a-W2b] unknown closure refs fail closed; a complete closure reaches the interpreter")


def closure_locks_slot(db, owner, service):
    import queue
    import threading

    creator = uuid4()
    seed_effect(owner, creator)
    root = uuid4()
    seed_scope(owner, root, creator, default_realm="rlock")
    consumer_install = seed_install(
        owner, scope_id=root, creator=creator,
        requires=[{"key": "dep"}])
    consumer_fiber = seed_fiber(owner, install_id=consumer_install, scope_id=root,
                                creator=creator)
    provider(owner, root, "rlock", "dep", creator)
    owner.commit()

    blocker = db.connect()
    worker = db.connect("service")
    observer = db.connect()
    observer.autocommit = True
    try:
        with blocker.cursor() as cur:
            cur.execute("SELECT slot_id FROM v24.slots WHERE realm='rlock' AND key='dep' FOR UPDATE")
        blocker_pid = blocker.get_backend_pid()
        pid = one(worker, "SELECT pg_backend_pid()")
        worker.commit()
        eid, outcome = command(worker, "g3a-lock", "command_fiber_control",
                               {"fiber_id": str(consumer_fiber), "action": "on",
                                "expected_control_seq": 0})
        worker.commit()
        result = queue.Queue()

        def run():
            try:
                advance(worker, eid, outcome)
                result.put(None)
            except psycopg2.Error as exc:
                worker.rollback()
                result.put(exc.pgcode)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while True:
                waiting = one(observer, """SELECT count(*) FROM pg_locks
                    WHERE pid=%s AND NOT granted""", (pid,))
                if waiting >= 1:
                    break
                assert thread.is_alive(), "advance finished before locking the slot"
                assert time.monotonic() < deadline, "advance did not block on the slot"
            assert thread.is_alive()
            blocked_by = one(observer,
                             "SELECT %s = ANY(pg_blocking_pids(%s))",
                             (blocker_pid, pid))
            assert blocked_by is True, "blocker does not own the slot lock"
        finally:
            blocker.rollback()
        code = result.get(timeout=5)
        assert code is None, code
        thread.join(timeout=5)
        assert not thread.is_alive()
    finally:
        blocker.rollback()
        blocker.close()
        worker.rollback()
        worker.close()
        observer.close()
    owner.rollback()
    print("[G3a-W2c] closure locks the resolved slot before the interpreter (episodes->slots edge)")


def install_command(conn, scope_id, owner, identity, key):
    manifest = {"identity": identity, "version": "1", "requires": [],
                "provides": [], "adapter_digest": "\\x"}
    raw = json.dumps(manifest).encode()
    return command(conn, key, "command_install", {
        "scope_id": str(scope_id), "owner_fiber_id": owner,
        "manifest_bytes": base64.b64encode(raw).decode(),
        "artifact_digest": "\\x"})


def domain_state(conn):
    snapshot = state(conn)
    snapshot.pop("effects")
    snapshot.pop("requests")
    return snapshot


def root_install(owner, admin, scope_id, identity, key):
    eid, outcome = install_command(admin, scope_id, None, identity, key)
    response = advance(admin, eid, outcome)
    assert response.get("disposition") == "committed", response
    admin.commit()
    install_id = response["emitted"][0]
    fiber_id = one(owner, "SELECT fiber_id FROM v24.fibers WHERE install_id=%s", (install_id,))
    assert fiber_id == one(owner, "SELECT md5(%s::text || ':fiber')::uuid", (install_id,))
    return install_id, fiber_id, response


def install_fibers(owner, admin):
    # Root admission: exactly one inactive, deterministic fiber.
    eid = uuid4()
    seed_effect(owner, eid)
    root = uuid4()
    seed_scope(owner, root, eid, default_realm="w3")
    owner.commit()
    install_id, fiber_id, response = root_install(owner, admin, root, "w3-root", "w3-root")
    fiber = one(owner, "SELECT to_jsonb(f) FROM v24.fibers f WHERE fiber_id=%s", (fiber_id,))
    assert fiber["want_on"] is False and fiber["current_episode_id"] is None, fiber
    assert fiber["owner_fiber_id"] is None and fiber["owner_episode_id"] is None, fiber
    assert fiber["control_seq"] == 0 and fiber["next_contribution_seq"] == 0, fiber
    assert fiber["created_by_effect"] == one(
        owner, "SELECT created_by_effect::text FROM v24.installs WHERE install_id=%s", (install_id,))
    assert one(owner, "SELECT count(*) FROM v24.fibers WHERE install_id=%s", (install_id,)) == 1

    # Byte-identical replay and same-declaration reuse add no second fiber.
    eid2, outcome2 = install_command(admin, root, None, "w3-root", "w3-root")
    assert str(eid2) == response["effect_id"], (eid2, response["effect_id"])
    replay = advance(admin, eid2, outcome2)
    assert replay == response, replay
    admin.commit()
    owner.rollback()
    eid3, outcome3 = install_command(admin, root, None, "w3-root", "w3-root-new")
    reused = advance(admin, eid3, outcome3)
    assert reused["emitted"] == [install_id], reused
    admin.commit()
    owner.rollback()
    assert one(owner, "SELECT count(*) FROM v24.fibers WHERE install_id=%s", (install_id,)) == 1

    # Child admission: owner must be live, accepting, on an active current episode.
    ep1 = seed_episode(owner, fiber_id=fiber_id, creator=eid, epoch=1)
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.fibers SET want_on=true, current_episode_id=%s WHERE fiber_id=%s",
                    (ep1, fiber_id))
    owner.commit()
    child_eid, child_outcome = install_command(
        admin, root, str(fiber_id), "w3-child", "w3-child")
    child = advance(admin, child_eid, child_outcome)
    assert child.get("disposition") == "committed", child
    admin.commit()
    child_install = child["emitted"][0]
    row = one(owner, "SELECT to_jsonb(i) FROM v24.installs i WHERE install_id=%s", (child_install,))
    assert row["owner_fiber_id"] == str(fiber_id) and row["owner_episode_id"] == str(ep1), row
    child_fiber = one(owner, "SELECT to_jsonb(f) FROM v24.fibers f WHERE install_id=%s",
                      (child_install,))
    assert child_fiber["owner_fiber_id"] == str(fiber_id), child_fiber
    assert child_fiber["owner_episode_id"] == str(ep1), child_fiber

    # E1 -> E2: the old child keeps its historical owner episode.
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.episodes SET state='closed', closed_at=now() WHERE episode_id=%s", (ep1,))
    ep2 = seed_episode(owner, fiber_id=fiber_id, creator=eid, epoch=2)
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.fibers SET current_episode_id=%s WHERE fiber_id=%s", (ep2, fiber_id))
    owner.commit()
    assert one(owner, "SELECT owner_episode_id::text FROM v24.installs WHERE install_id=%s",
               (child_install,)) == str(ep1)

    # Refusals: disposed, not accepting, no active current, nonexistent owner.
    cases = []
    disposed_i, disposed_f, _ = root_install(owner, admin, root, "w3-disposed", "w3-disposed")
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.fibers SET disposed_at=now(), want_on=false WHERE fiber_id=%s",
                    (disposed_f,))
    owner.commit()
    cases.append(("w3-disposed", str(disposed_f), "already_terminal", "w1"))

    idle_i, idle_f, _ = root_install(owner, admin, root, "w3-idle", "w3-idle")
    cases.append(("w3-idle", str(idle_f), "owner_closing", "w1"))

    empty_i, empty_f, _ = root_install(owner, admin, root, "w3-empty", "w3-empty")
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.fibers SET want_on=true WHERE fiber_id=%s", (empty_f,))
    owner.commit()
    cases.append(("w3-empty", str(empty_f), "install_not_ready", "w1"))

    retiring_i, retiring_f, _ = root_install(owner, admin, root, "w3-retiring", "w3-retiring")
    ep_ret = seed_episode(owner, fiber_id=retiring_f, creator=eid, state="retiring")
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.fibers SET want_on=true, current_episode_id=%s WHERE fiber_id=%s",
                    (ep_ret, retiring_f))
    owner.commit()
    cases.append(("w3-retiring", str(retiring_f), "install_not_ready", "w1"))

    for identity, owner_id, code, write_class in cases:
        before = domain_state(owner) if write_class == "w1" else state(owner)
        eid_bad, outcome_bad = install_command(admin, root, owner_id, identity + "-child",
                                               identity + "-child")
        response_bad = advance(admin, eid_bad, outcome_bad)
        assert response_bad == {"v": 1, "error": {"code": code, "detail": {}}}, response_bad
        admin.commit()
        assert (domain_state(owner) if write_class == "w1" else state(owner)) == before, (identity, code)
        owner.rollback()

    before = state(owner)
    missing = uuid4()
    eid_missing, outcome_missing = install_command(
        admin, root, str(missing), "w3-missing", "w3-missing")
    assert advance(admin, eid_missing, outcome_missing)["error"]["code"] == "invalid_args"
    admin.rollback()
    assert state(owner) == before
    owner.rollback()
    print("[G3a-J] install creates one deterministic inactive fiber; child admission fixed and refusals atomic")


def fiber_control_activation(owner, admin):
    with admin.cursor() as cur:
        cur.execute("SELECT v24.scope_control('create_root',NULL,'{}',%s,%s)",
                    ("w4", "w4-root-scope"))
        root = cur.fetchone()[0]["emitted"][0]
    admin.commit()

    install_id, fiber_id, _ = root_install(owner, admin, root, "w4-root", "w4-root")
    on = one(admin, "SELECT v24.fiber_control(%s,%s,%s,%s)",
             (fiber_id, "on", 0, "w4-on"))
    assert on.get("disposition") == "committed", on
    admin.commit()
    episode_id = on["emitted"][0]
    fiber = one(owner, "SELECT to_jsonb(f) FROM v24.fibers f WHERE fiber_id=%s", (fiber_id,))
    assert fiber["want_on"] is True and fiber["current_episode_id"] == episode_id, fiber
    assert fiber["control_seq"] == 1, fiber
    ep = one(owner, "SELECT to_jsonb(e) FROM v24.episodes e WHERE episode_id=%s", (episode_id,))
    assert ep["state"] == "active" and ep["epoch"] == 1 and ep["fiber_id"] == str(fiber_id), ep
    reco = one(owner, """SELECT to_jsonb(e) FROM v24.effects e
        WHERE fiber_id=%s AND kind='fiber_reconcile'""", (fiber_id,))
    assert reco["status"] == "succeeded", reco
    assert ep["activation_effect"] == reco["effect_id"], (ep, reco)
    events = one(owner, """SELECT count(*) FROM v24.events
        WHERE effect_id=(SELECT effect_id FROM v24.requests WHERE request_key='w4-on')""")
    assert events == 2, events  # fiber_activated + episode_opened
    assert one(owner, "SELECT count(*) FROM v24.pins WHERE consumer_episode_id=%s",
               (episode_id,)) == 0
    assert one(owner, "SELECT count(*) FROM v24.slots WHERE episode_id=%s",
               (episode_id,)) == 0

    # Replay is byte-equal and creates no second episode.
    admin.rollback()
    replay = one(admin, "SELECT v24.fiber_control(%s,%s,%s,%s)",
                 (fiber_id, "on", 0, "w4-on"))
    assert replay == on, (replay, on)
    admin.commit()
    owner.rollback()
    assert one(owner, "SELECT count(*) FROM v24.episodes WHERE fiber_id=%s", (fiber_id,)) == 1

    # New key for an already-satisfied target: receipt only, no domain diff.
    before = domain_state(owner)
    noop = one(admin, "SELECT v24.fiber_control(%s,%s,%s,%s)",
               (fiber_id, "on", 1, "w4-on-noop"))
    assert noop["disposition"] == "committed" and noop["emitted"] == [], noop
    admin.commit()
    assert domain_state(owner) == before
    owner.rollback()

    # CAS mismatch: W1 stale_generation, no domain write.
    before = domain_state(owner)
    stale = one(admin, "SELECT v24.fiber_control(%s,%s,%s,%s)",
                (fiber_id, "off", 0, "w4-stale"))
    assert stale == {"v": 1, "error": {"code": "stale_generation", "detail": {}}}, stale
    admin.commit()
    assert domain_state(owner) == before
    owner.rollback()

    # retry without a recorded failure is a no-op.
    retry_noop = one(admin, "SELECT v24.fiber_control(%s,%s,%s,%s)",
                     (fiber_id, "retry", 1, "w4-retry-noop"))
    assert retry_noop["disposition"] == "committed" and retry_noop["emitted"] == [], retry_noop
    admin.commit()
    owner.rollback()

    # off completes for a barrier-free leaf: withdraw, release, close, clear.
    off = one(admin, "SELECT v24.fiber_control(%s,%s,%s,%s)",
              (fiber_id, "off", 1, "w4-off"))
    assert off["disposition"] == "committed", off
    admin.commit()
    fiber = one(owner, "SELECT to_jsonb(f) FROM v24.fibers f WHERE fiber_id=%s", (fiber_id,))
    assert fiber["want_on"] is False and fiber["current_episode_id"] is None, fiber
    assert fiber["control_seq"] == 2, fiber
    ep = one(owner, "SELECT to_jsonb(e) FROM v24.episodes e WHERE episode_id=%s", (episode_id,))
    assert ep["state"] == "closed" and ep["closed_at"] is not None, ep
    assert one(owner, """SELECT count(*) FROM v24.effects WHERE fiber_id=%s
        AND kind='fiber_reconcile' AND status='ready'""", (fiber_id,)) == 0
    owner.rollback()

    # E1 -> E2: the closed episode is retained; the next on opens epoch+1.
    on2 = one(admin, "SELECT v24.fiber_control(%s,%s,%s,%s)",
              (fiber_id, "on", 2, "w4-on2"))
    assert on2.get("disposition") == "committed", on2
    admin.commit()
    e2 = one(owner, "SELECT to_jsonb(e) FROM v24.episodes e WHERE episode_id=%s",
             (on2["emitted"][0],))
    assert e2["epoch"] == 2 and e2["state"] == "active", e2
    assert one(owner, "SELECT count(*) FROM v24.episodes WHERE fiber_id=%s", (fiber_id,)) == 2
    assert one(owner, "SELECT state FROM v24.episodes WHERE episode_id=%s",
               (episode_id,)) == "closed"
    owner.rollback()

    # Missing dependency: W1 failure, no episode/slot/pin, failure recorded.
    creator = uuid4()
    seed_effect(owner, creator)
    ci = seed_install(owner, scope_id=root, creator=creator, requires=[{"key": "dep"}])
    cf = seed_fiber(owner, install_id=ci, scope_id=root, creator=creator)
    owner.commit()
    missing = one(admin, "SELECT v24.fiber_control(%s,%s,%s,%s)",
                  (cf, "on", 0, "w4-dep-1"))
    assert missing == {"v": 1, "error": {"code": "dependency_unresolved", "detail": {}}}, missing
    admin.commit()
    row = one(owner, "SELECT to_jsonb(f) FROM v24.fibers f WHERE fiber_id=%s", (cf,))
    assert row["failure_seq"] == 1 and row["failure"]["code"] == "dependency_unresolved", row
    assert row["current_episode_id"] is None, row
    assert one(owner, "SELECT count(*) FROM v24.episodes WHERE fiber_id=%s", (cf,)) == 0
    assert one(owner, "SELECT count(*) FROM v24.pins p JOIN v24.episodes e ON e.episode_id=p.consumer_episode_id WHERE e.fiber_id=%s", (cf,)) == 0
    owner.rollback()

    # Provide the dependency, then retry succeeds and pins it.
    creator2 = uuid4()
    seed_effect(owner, creator2)
    pi = seed_install(owner, scope_id=root, creator=creator2)
    pf = seed_fiber(owner, install_id=pi, scope_id=root, creator=creator2)
    pe = seed_episode(owner, fiber_id=pf, creator=creator2)
    ps = seed_slot(owner, fiber_id=pf, episode_id=pe, realm="w4", key="dep")
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.fibers SET current_episode_id=%s WHERE fiber_id=%s", (pe, pf))
    owner.commit()

    retried = one(admin, "SELECT v24.fiber_control(%s,%s,%s,%s)",
                  (cf, "retry", 1, "w4-dep-retry"))
    assert retried.get("disposition") == "committed", retried
    admin.commit()
    row = one(owner, "SELECT to_jsonb(f) FROM v24.fibers f WHERE fiber_id=%s", (cf,))
    assert row["current_episode_id"] == retried["emitted"][0], row
    assert row["control_seq"] == 2 and row["failure_seq"] is None and row["failure"] is None, row
    pin_row = one(owner, """SELECT to_jsonb(p) FROM v24.pins p
        WHERE p.consumer_episode_id=%s""", (row["current_episode_id"],))
    assert pin_row["key"] == "dep" and pin_row["slot_id"] == str(ps), pin_row
    assert pin_row["provider_episode_id"] == str(pe), pin_row
    owner.rollback()

    # check_policy: invalid shape is rejected at admission; false predicate is unresolved.
    bad_manifest = {"identity": "w4-badpol", "version": "1",
                    "requires": [{"key": "pol",
                                  "check_policy": {"v": 2, "op": "equals", "path": [], "value": 1}}],
                    "provides": [], "adapter_digest": "\\x"}
    bad_raw = json.dumps(bad_manifest).encode()
    bad_eid, bad_outcome = command(admin, "w4-badpol", "command_install", {
        "scope_id": str(root), "owner_fiber_id": None,
        "manifest_bytes": base64.b64encode(bad_raw).decode(),
        "artifact_digest": "\\x"})
    assert advance(admin, bad_eid, bad_outcome)["error"]["code"] == "invalid_args"
    admin.rollback()
    owner.rollback()

    creator4 = uuid4()
    seed_effect(owner, creator4)
    pol_i = seed_install(owner, scope_id=root, creator=creator4, requires=[{
        "key": "pol",
        "check_policy": {"v": 1, "op": "equals", "path": ["kind"], "value": "ok"}}])
    pol_f = seed_fiber(owner, install_id=pol_i, scope_id=root, creator=creator4)
    pol_pi = seed_install(owner, scope_id=root, creator=creator4)
    pol_pf = seed_fiber(owner, install_id=pol_pi, scope_id=root, creator=creator4)
    pol_pe = seed_episode(owner, fiber_id=pol_pf, creator=creator4)
    seed_slot(owner, fiber_id=pol_pf, episode_id=pol_pe, realm="w4", key="pol",
              descriptor=Json({"kind": "bad"}))
    with owner.cursor() as cur:
        cur.execute("UPDATE v24.fibers SET current_episode_id=%s WHERE fiber_id=%s",
                    (pol_pe, pol_pf))
    owner.commit()
    pol = one(admin, "SELECT v24.fiber_control(%s,%s,%s,%s)", (pol_f, "on", 0, "w4-pol"))
    assert pol == {"v": 1, "error": {"code": "dependency_unresolved", "detail": {}}}, pol
    admin.commit()
    row = one(owner, "SELECT to_jsonb(f) FROM v24.fibers f WHERE fiber_id=%s", (pol_f,))
    assert row["failure"]["code"] == "dependency_unresolved", row
    owner.rollback()

    # provide_conflict: a second activation of the same realm/key is refused.
    creator3 = uuid4()
    seed_effect(owner, creator3)
    a_i = seed_install(owner, scope_id=root, creator=creator3,
                       provides=[{"realm": "w4", "key": "same"}])
    a_f = seed_fiber(owner, install_id=a_i, scope_id=root, creator=creator3)
    b_i = seed_install(owner, scope_id=root, creator=creator3,
                       provides=[{"realm": "w4", "key": "same"}])
    b_f = seed_fiber(owner, install_id=b_i, scope_id=root, creator=creator3)
    owner.commit()
    first = one(admin, "SELECT v24.fiber_control(%s,%s,%s,%s)", (a_f, "on", 0, "w4-prov-a"))
    assert first.get("disposition") == "committed", first
    admin.commit()
    prov_slot = one(owner, """SELECT to_jsonb(s) FROM v24.slots s
        WHERE s.fiber_id=%s AND s.released_at IS NULL""", (a_f,))
    assert prov_slot["realm"] == "w4" and prov_slot["key"] == "same", prov_slot
    assert prov_slot["contribution_seq"] == 0, prov_slot
    assert one(owner, """SELECT descriptor_digest = sha256(convert_to('{}','UTF8'))
        FROM v24.slots WHERE slot_id=%s""", (prov_slot["slot_id"],)) is True, prov_slot
    second = one(admin, "SELECT v24.fiber_control(%s,%s,%s,%s)", (b_f, "on", 0, "w4-prov-b"))
    assert second == {"v": 1, "error": {"code": "provide_conflict", "detail": {}}}, second
    admin.commit()
    row = one(owner, "SELECT to_jsonb(f) FROM v24.fibers f WHERE fiber_id=%s", (b_f,))
    assert row["failure_seq"] == 1 and row["failure"]["code"] == "provide_conflict", row
    assert one(owner, "SELECT count(*) FROM v24.episodes WHERE fiber_id=%s", (b_f,)) == 0
    assert one(owner, "SELECT count(*) FROM v24.slots WHERE fiber_id=%s", (b_f,)) == 0
    owner.rollback()
    print("[G3a-B/C/D/E] empty-inject activation, replay/no-op/CAS, dependency failure+retry, provide_conflict")


def deactivation_barrier(owner, admin):
    with admin.cursor() as cur:
        cur.execute("SELECT v24.scope_control('create_root',NULL,'{}',%s,%s)",
                    ("w5", "w5-root"))
        root = cur.fetchone()[0]["emitted"][0]
    admin.commit()
    creator = uuid4()
    seed_effect(owner, creator)
    b_install = seed_install(owner, scope_id=root, creator=creator,
                             provides=[{"realm": "w5", "key": "dep"}])
    b_fiber = seed_fiber(owner, install_id=b_install, scope_id=root, creator=creator)
    a_install = seed_install(owner, scope_id=root, creator=creator,
                             requires=[{"key": "dep"}])
    a_fiber = seed_fiber(owner, install_id=a_install, scope_id=root, creator=creator)
    owner.commit()

    b_on = one(admin, "SELECT v24.fiber_control(%s,%s,%s,%s)", (b_fiber, "on", 0, "w5-b-on"))
    assert b_on.get("disposition") == "committed", b_on
    admin.commit()
    b_ep = b_on["emitted"][0]
    a_on = one(admin, "SELECT v24.fiber_control(%s,%s,%s,%s)", (a_fiber, "on", 0, "w5-a-on"))
    assert a_on.get("disposition") == "committed", a_on
    admin.commit()
    a_ep = a_on["emitted"][0]
    assert one(owner, "SELECT count(*) FROM v24.pins WHERE provider_episode_id=%s", (b_ep,)) == 1

    # B retires but stage B is blocked by A's live activation pin.
    b_off = one(admin, "SELECT v24.fiber_control(%s,%s,%s,%s)", (b_fiber, "off", 1, "w5-b-off"))
    assert b_off["disposition"] == "deferred", b_off
    admin.commit()
    slot = one(owner, "SELECT to_jsonb(s) FROM v24.slots s WHERE s.fiber_id=%s", (b_fiber,))
    assert slot["withdrawn_at"] is not None and slot["released_at"] is None, slot
    ep = one(owner, "SELECT to_jsonb(e) FROM v24.episodes e WHERE e.episode_id=%s", (b_ep,))
    assert ep["state"] == "retiring" and ep["closed_at"] is None, ep
    assert ep["retire_started_at"] is not None, ep
    assert one(owner, """SELECT count(*) FROM v24.effects WHERE fiber_id=%s
        AND kind='fiber_reconcile' AND status='ready'""", (b_fiber,)) == 1
    owner.rollback()

    # A releases its consumer pin while closing its own episode.
    a_off = one(admin, "SELECT v24.fiber_control(%s,%s,%s,%s)", (a_fiber, "off", 1, "w5-a-off"))
    assert a_off["disposition"] == "committed", a_off
    admin.commit()
    pin = one(owner, "SELECT to_jsonb(p) FROM v24.pins p WHERE p.provider_episode_id=%s", (b_ep,))
    assert pin["released_at"] is not None and pin["released_by_effect"] is not None, pin
    a_ep_row = one(owner, "SELECT to_jsonb(e) FROM v24.episodes e WHERE e.episode_id=%s", (a_ep,))
    assert a_ep_row["state"] == "closed", a_ep_row
    owner.rollback()

    # B's second off drains stage B.
    b_off2 = one(admin, "SELECT v24.fiber_control(%s,%s,%s,%s)", (b_fiber, "off", 2, "w5-b-off2"))
    assert b_off2["disposition"] == "committed", b_off2
    admin.commit()
    slot = one(owner, "SELECT to_jsonb(s) FROM v24.slots s WHERE s.slot_id=%s", (slot["slot_id"],))
    assert slot["released_at"] is not None and slot["released_at"] >= slot["withdrawn_at"], slot
    ep = one(owner, "SELECT to_jsonb(e) FROM v24.episodes e WHERE e.episode_id=%s", (b_ep,))
    assert ep["state"] == "closed" and ep["closed_at"] is not None, ep
    b_row = one(owner, "SELECT to_jsonb(f) FROM v24.fibers f WHERE f.fiber_id=%s", (b_fiber,))
    assert b_row["current_episode_id"] is None and b_row["control_seq"] == 3, b_row
    assert one(owner, """SELECT count(*) FROM v24.effects WHERE fiber_id=%s
        AND kind='fiber_reconcile' AND status='ready'""", (b_fiber,)) == 0
    off_reco = one(owner, """SELECT to_jsonb(e) FROM v24.effects e
        WHERE e.fiber_id=%s AND e.kind='fiber_reconcile' AND e.status='succeeded'
          AND e.outcome->>'stage'='deactivate'""", (b_fiber,))
    assert off_reco["outcome"]["result"] == "closed", off_reco
    owner.rollback()

    # E1 -> E2 after a real drain: old episode and old pin rows are retained.
    b_on2 = one(admin, "SELECT v24.fiber_control(%s,%s,%s,%s)", (b_fiber, "on", 3, "w5-b-on2"))
    assert b_on2.get("disposition") == "committed", b_on2
    admin.commit()
    e2 = one(owner, "SELECT to_jsonb(e) FROM v24.episodes e WHERE e.episode_id=%s",
             (b_on2["emitted"][0],))
    assert e2["epoch"] == 2 and e2["state"] == "active", e2
    e1 = one(owner, "SELECT to_jsonb(e) FROM v24.episodes e WHERE e.episode_id=%s", (b_ep,))
    assert e1["state"] == "closed" and e1["epoch"] == 1, e1
    assert one(owner, "SELECT count(*) FROM v24.episodes WHERE fiber_id=%s", (b_fiber,)) == 2
    old_pin = one(owner, "SELECT to_jsonb(p) FROM v24.pins p WHERE p.provider_episode_id=%s", (b_ep,))
    assert old_pin["released_at"] is not None, old_pin
    owner.rollback()
    print("[G3a-F/G] activation-pin barrier, deferred stage B, withdraw/release, E1->E2")


def dispose_leaf(owner, admin, service):
    with admin.cursor() as cur:
        cur.execute("SELECT v24.scope_control('create_root',NULL,'{}',%s,%s)",
                    ("w6", "w6-root-scope"))
        root = cur.fetchone()[0]["emitted"][0]
    admin.commit()

    install_id, fiber_id, _ = root_install(owner, admin, root, "w6-root", "w6-root")
    resp = one(admin, "SELECT v24.dispose(%s,%s)", (install_id, "w6-dispose"))
    assert resp.get("disposition") == "committed" and len(resp["emitted"]) == 1, resp
    release_id = resp["emitted"][0]
    admin.commit()
    row = one(owner, "SELECT to_jsonb(i) FROM v24.installs i WHERE install_id=%s", (install_id,))
    assert row["state"] == "dispose_pending", row
    assert row["dispose_effect"] == one(
        owner, "SELECT effect_id::text FROM v24.requests WHERE request_key='w6-dispose'"), row
    fiber = one(owner, "SELECT to_jsonb(f) FROM v24.fibers f WHERE fiber_id=%s", (fiber_id,))
    assert fiber["disposed_at"] is not None and fiber["want_on"] is False, fiber
    rel = one(owner, "SELECT to_jsonb(e) FROM v24.effects e WHERE effect_id=%s", (release_id,))
    assert rel["kind"] == "host_release" and rel["status"] == "ready", rel
    assert rel["request"]["install_id"] == str(install_id), rel
    assert rel["request"]["reservation"] == "v24:host_release:" + release_id, rel

    # Replay is byte-equal and does not emit a second release.
    replay = one(admin, "SELECT v24.dispose(%s,%s)", (install_id, "w6-dispose"))
    assert replay == resp, (replay, resp)
    admin.commit()
    assert one(owner, "SELECT count(*) FROM v24.effects WHERE kind='host_release' "
                      "AND request->>'install_id'=%s", (str(install_id),)) == 1
    owner.rollback()

    token = advance(service, release_id, claim())["claim"]
    service.commit()
    settled = advance(service, release_id, {"v": 1, "class": "success",
                                           "claim": token, "body": {}})
    assert settled.get("disposition") == "committed", settled
    service.commit()
    row = one(owner, "SELECT to_jsonb(i) FROM v24.installs i WHERE install_id=%s", (install_id,))
    assert row["state"] == "disposed" and row["disposed_at"] is not None, row
    assert one(owner, "SELECT count(*) FROM v24.events WHERE event_kind='install_disposed' "
                      "AND entity_id=%s", (install_id,)) == 1
    owner.rollback()

    before = domain_state(owner)
    late = one(admin, "SELECT v24.dispose(%s,%s)", (install_id, "w6-dispose-late"))
    assert late == {"v": 1, "error": {"code": "already_terminal", "detail": {}}}, late
    admin.commit()
    assert domain_state(owner) == before
    owner.rollback()

    # Active fiber blocks the release; off drains it; a second dispose emits.
    blocked_i, blocked_f, _ = root_install(owner, admin, root, "w6-blocked", "w6-blocked")
    on = one(admin, "SELECT v24.fiber_control(%s,%s,%s,%s)", (blocked_f, "on", 0, "w6-blocked-on"))
    assert on.get("disposition") == "committed", on
    admin.commit()
    first = one(admin, "SELECT v24.dispose(%s,%s)", (blocked_i, "w6-blocked-dispose"))
    assert first["disposition"] == "committed" and first["emitted"] == [], first
    admin.commit()
    assert one(owner, "SELECT state FROM v24.installs WHERE install_id=%s",
               (blocked_i,)) == "dispose_pending"
    assert one(owner, "SELECT count(*) FROM v24.effects WHERE kind='host_release' "
                      "AND request->>'install_id'=%s", (str(blocked_i),)) == 0
    off = one(admin, "SELECT v24.fiber_control(%s,%s,%s,%s)", (blocked_f, "off", 1, "w6-blocked-off"))
    assert off["disposition"] == "committed", off
    admin.commit()
    second = one(admin, "SELECT v24.dispose(%s,%s)", (blocked_i, "w6-blocked-dispose-2"))
    assert second["disposition"] == "committed" and len(second["emitted"]) == 1, second
    admin.commit()
    owner.rollback()

    # prepare_unknown stops at dispose_pending: inspect convergence is S5.
    creator = uuid4()
    seed_effect(owner, creator)
    unknown_i = seed_install(owner, scope_id=root, creator=creator, state="prepare_unknown")
    seed_fiber(owner, install_id=unknown_i, scope_id=root, creator=creator)
    owner.commit()
    unk = one(admin, "SELECT v24.dispose(%s,%s)", (unknown_i, "w6-unknown"))
    assert unk["disposition"] == "committed" and unk["emitted"] == [], unk
    admin.commit()
    assert one(owner, "SELECT state FROM v24.installs WHERE install_id=%s",
               (unknown_i,)) == "dispose_pending"
    assert one(owner, "SELECT count(*) FROM v24.effects WHERE kind='host_release' "
                      "AND request->>'install_id'=%s", (str(unknown_i),)) == 0
    owner.rollback()

    # host_release failure keeps dispose_pending and never writes disposed_at.
    fail_i, fail_f, _ = root_install(owner, admin, root, "w6-fail", "w6-fail")
    fail = one(admin, "SELECT v24.dispose(%s,%s)", (fail_i, "w6-fail-dispose"))
    fail_rel = fail["emitted"][0]
    admin.commit()
    fail_token = advance(service, fail_rel, claim())["claim"]
    service.commit()
    failed = advance(service, fail_rel, {"v": 1, "class": "failure",
                                         "claim": fail_token, "body": {}})
    assert failed.get("disposition") == "committed", failed
    service.commit()
    row = one(owner, "SELECT to_jsonb(i) FROM v24.installs i WHERE install_id=%s", (fail_i,))
    assert row["state"] == "dispose_pending" and row["disposed_at"] is None, row
    assert one(owner, "SELECT status FROM v24.effects WHERE effect_id=%s",
               (fail_rel,)) == "failed"
    owner.rollback()

    # A preparing install cannot accept a host_prepare receipt after dispose.
    prep_i = seed_install(owner, scope_id=root, creator=creator, state="preparing")
    seed_fiber(owner, install_id=prep_i, scope_id=root, creator=creator)
    hp = uuid4()
    seed_effect(owner, hp, kind="host_prepare", status="ready",
                request=Json({"install_id": str(prep_i),
                              "reservation": "v24:host_prepare:" + str(hp)}))
    owner.commit()
    prep = one(admin, "SELECT v24.dispose(%s,%s)", (prep_i, "w6-prep-dispose"))
    assert prep["disposition"] == "committed" and prep["emitted"] == [], prep
    admin.commit()
    hp_token = advance(service, hp, claim())["claim"]
    service.commit()
    refused = advance(service, hp, {"v": 1, "class": "success",
                                    "claim": hp_token, "body": {}})
    assert refused == {"v": 1, "error": {"code": "receipt_conflict", "detail": {}}}, refused
    service.rollback()
    assert one(owner, "SELECT state FROM v24.installs WHERE install_id=%s",
               (prep_i,)) == "dispose_pending"
    owner.rollback()
    print("[G3a-K] dispose: release successor, disposed, replay, already_terminal, "
          "blocked/unknown/failure boundaries")


def acl(owner, connections):
    for name in ("fiber_control", "dispose"):
        row = one(owner, """SELECT jsonb_build_object('sec', p.prosecdef,
                'def', pg_get_functiondef(p.oid))
            FROM pg_proc p WHERE p.pronamespace='v24'::regnamespace
              AND p.proname=%s""", (name,))
        assert row["sec"] is False, (name, row)
        assert "v24.advance(" in row["def"], (name, row)
        for write in ("INSERT INTO", "UPDATE v24.", "DELETE FROM", "pg_advisory_xact_lock"):
            assert write not in row["def"], (name, write, row)
    for alias, conn in connections.items():
        assert one(conn, "SELECT has_function_privilege(session_user, "
                         "'v24.resolve(uuid,text[])'::regprocedure, 'EXECUTE')") is True
    assert one(owner, """SELECT count(*) FROM pg_proc p, LATERAL aclexplode(
            coalesce(p.proacl,acldefault('f',p.proowner))) a
        WHERE p.pronamespace='v24'::regnamespace AND p.proname='resolve'
          AND a.grantee=0 AND a.privilege_type='EXECUTE'""") == 0
    print("[G3a-A6] resolve EXECUTE is granted to the three protocol roles only")


def main():
    with server_helper_scope(), setup_db() as db:
        owner = db.connect()
        with owner.cursor() as cur:
            cur.execute("SET ROLE v24_owner")
        owner.commit()
        connections = {alias: db.connect(alias) for alias in ("admin", "service", "operator")}
        service = connections["service"]
        resolver_contract(owner)
        resolver_shape_and_writes(owner)
        resolver_routing(owner)
        resolver_live_predicate(owner)
        resolver_limit(owner)
        acl(owner, connections)
        reconcile_index_and_claim(owner, service)
        closure_fail_closed_and_seam(owner, service)
        closure_locks_slot(db, owner, service)
        install_fibers(owner, connections["admin"])
        fiber_control_activation(owner, connections["admin"])
        deactivation_barrier(owner, connections["admin"])
        dispose_leaf(owner, connections["admin"], connections["service"])
        _assert_closed_catalog(owner)
    print("[passed] v24 S2 W1-W6: resolve, infra, admission, activation, deactivation, dispose")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
