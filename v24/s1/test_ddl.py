"""G1-O: owner DML probes of W2 DDL, not advance/interpreter behavior."""
from __future__ import annotations

import contextlib
from datetime import datetime, timezone
from uuid import uuid4

import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json, register_uuid

from setup_db import EXPECTED_TABLES, server_helper_scope, setup_db

register_uuid()
NOW = datetime.now(timezone.utc)
DIGEST = b"w2-ddl-probe"


def insert(cur, table: str, **values) -> None:
    cur.execute(
        sql.SQL("INSERT INTO v24.{} ({}) VALUES ({})").format(
            sql.Identifier(table),
            sql.SQL(", ").join(map(sql.Identifier, values)),
            sql.SQL(", ").join(sql.Placeholder() for _ in values),
        ),
        tuple(values.values()),
    )


def effect(cur, effect_id, **overrides) -> None:
    values = dict(
        effect_id=effect_id, requester_id=uuid4(), kind="host_prepare",
        status="ready", request=Json({}), request_digest=DIGEST,
        replay_policy="no_replay",
    )
    values.update(overrides)
    insert(cur, "effects", **values)


def scope(cur, scope_id, creator, **overrides) -> None:
    values = dict(scope_id=scope_id, root_id=scope_id, route_path=[scope_id],
                  owner_principal=uuid4(), created_by_effect=creator)
    values.update(overrides)
    insert(cur, "scopes", **values)


def episode(cur, episode_id, fiber_id, creator, **overrides) -> None:
    values = dict(episode_id=episode_id, fiber_id=fiber_id, epoch=1,
                  activation_effect=creator, state="active")
    values.update(overrides)
    insert(cur, "episodes", **values)


def slot(cur, slot_id, fiber_id, episode_id, **overrides) -> None:
    values = dict(slot_id=slot_id, fiber_id=fiber_id, episode_id=episode_id,
                  realm="w2", key=str(slot_id), descriptor=Json({}),
                  descriptor_digest=DIGEST, contribution_seq=1)
    values.update(overrides)
    insert(cur, "slots", **values)


def pin(cur, pin_id, seed, **overrides) -> None:
    values = dict(pin_id=pin_id, consumer_type="activation",
                  consumer_episode_id=seed["ep1"], consumer_epoch=1, key="dep",
                  slot_id=seed["slot1"], provider_fiber_id=seed["f1"],
                  provider_episode_id=seed["ep1"], descriptor_digest=DIGEST,
                  created_by_effect=seed["effect"])
    values.update(overrides)
    insert(cur, "pins", **values)


def request(cur, effect_id, key) -> None:
    insert(cur, "requests", principal_id=uuid4(), request_key=key,
           kind="command_scope_control", request_bytes=b"{}",
           request_digest=DIGEST, effect_id=effect_id, response=Json({}))


def rejects(conn, code: str, constraint: str, action) -> None:
    """Mirror v99's savepoint probe, also checking the diagnostic constraint."""
    with conn.cursor() as cur:
        cur.execute("SAVEPOINT w2_probe")
        try:
            action(cur)
        except psycopg2.Error as exc:
            actual = (exc.pgcode, exc.diag.constraint_name)
            cur.execute("ROLLBACK TO SAVEPOINT w2_probe")
            cur.execute("RELEASE SAVEPOINT w2_probe")
            assert actual == (code, constraint), (actual, code, constraint, str(exc))
            return
        cur.execute("ROLLBACK TO SAVEPOINT w2_probe")
        cur.execute("RELEASE SAVEPOINT w2_probe")
    raise AssertionError(f"expected {code} / {constraint}")


def sql_rejects(conn, code, constraint, statement, params=()) -> None:
    rejects(conn, code, constraint, lambda cur: cur.execute(statement, params))


def commit_rejects(conn, code: str, constraint: str, action) -> None:
    """Insertion succeeds with a savepoint; only an actual COMMIT may reject."""
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("SAVEPOINT w2_deferred_probe")
        action(cur)
        cur.execute("RELEASE SAVEPOINT w2_deferred_probe")
    try:
        conn.commit()
    except psycopg2.Error as exc:
        actual = (exc.pgcode, exc.diag.constraint_name)
        conn.rollback()
        assert actual == (code, constraint), (actual, code, constraint, str(exc))
        return
    raise AssertionError(f"COMMIT accepted {code} / {constraint} violation")


def seed_rows(conn):
    s = {key: uuid4() for key in (
        "root", "root2", "child", "install", "f1", "f2", "ep1", "ep2",
        "slot1", "slot2", "pin", "run", "effect",
    )}
    with conn.cursor() as cur:
        # Frozen order: domain rows -> effects -> requests -> events.
        scope(cur, s["root"], s["effect"])
        scope(cur, s["root2"], s["effect"])
        scope(cur, s["child"], s["effect"], parent_id=s["root"],
              root_id=s["root"], route_path=[s["root"], s["child"]])
        insert(cur, "installs", install_id=s["install"], scope_id=s["root"],
               identity="w2", version="1", manifest=Json({}), manifest_digest=DIGEST,
               requires=Json([]), provides=Json([]), artifact_digest=DIGEST,
               adapter_digest=DIGEST, owner_principal=uuid4(), state="preparing",
               created_by_effect=s["effect"])
        for f in ("f1", "f2"):
            insert(cur, "fibers", fiber_id=s[f], install_id=s["install"],
                   scope_id=s["root"], created_by_effect=s["effect"])
        for f, ep in (("f1", "ep1"), ("f2", "ep2")):
            episode(cur, s[ep], s[f], s["effect"])
            cur.execute("UPDATE v24.fibers SET current_episode_id=%s WHERE fiber_id=%s",
                        (s[ep], s[f]))
        for f, ep, sl in (("f1", "ep1", "slot1"), ("f2", "ep2", "slot2")):
            slot(cur, s[sl], s[f], s[ep])
        pin(cur, s["pin"], s)
        insert(cur, "runs", run_id=s["run"], scope_id=s["root"], status="running",
               remaining_steps=1, remaining_tool_calls=1, remaining_wall_ms=1)
        effect(cur, s["effect"], kind="command_scope_control", status="succeeded",
               outcome=Json({}), settled_at=NOW, scope_id=s["root"], run_id=s["run"],
               fiber_id=s["f1"], episode_id=s["ep1"], pin_id=s["pin"])
        request(cur, s["effect"], "seed")
        insert(cur, "events", effect_id=s["effect"], seq=1, entity_type="scope",
               entity_id=s["root"], event_kind="created", payload_digest=DIGEST)
    conn.commit()
    print("[order] domain/effect cycles closed at COMMIT; fiber pointer updated after episode")
    return s


def catalog(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT current_user::text")
        assert cur.fetchone() == ("v24_owner",)
        cur.execute("""SELECT c.relname, c.relkind, r.rolname
                         FROM pg_class c JOIN pg_roles r ON r.oid=c.relowner
                        WHERE c.relnamespace='v24'::regnamespace
                          AND c.relkind IN ('r','p','v','m')""")
        assert set(cur.fetchall()) == {(t, "r", "v24_owner") for t in EXPECTED_TABLES}
        cur.execute("""SELECT conname, condeferrable, condeferred
                         FROM pg_constraint WHERE connamespace='v24'::regnamespace
                          AND contype='f' AND confrelid='v24.effects'::regclass""")
        rows = cur.fetchall()
        assert len(rows) == 10, rows
        assert all(deferred and initial for _, deferred, initial in rows), rows
        cur.execute("""SELECT conname FROM pg_constraint
                        WHERE connamespace='v24'::regnamespace AND contype='f'
                          AND confrelid<>'v24.effects'::regclass
                          AND (condeferrable OR condeferred)""")
        assert cur.fetchall() == []
        cur.execute("""SELECT condeferrable, condeferred FROM pg_constraint
                        WHERE conrelid='v24.episodes'::regclass
                          AND conname='u_episodes_ident'""")
        assert cur.fetchone() == (False, False)
        cur.execute("""SELECT indexrelid::regclass::text FROM pg_index
                        WHERE indrelid IN ('v24.episodes'::regclass, 'v24.slots'::regclass,
                                           'v24.pins'::regclass)
                          AND indisunique AND indimmediate AND indpred IS NOT NULL""")
        assert {r[0] for r in cur.fetchall()} == {
            "v24.u_episodes_open", "v24.u_slots_live", "v24.u_pins_live",
        }
        cur.execute("""SELECT tgname, tgtype::int, tgdeferrable, tginitdeferred
                         FROM pg_trigger WHERE tgrelid IN
                          (SELECT oid FROM pg_class WHERE relnamespace='v24'::regnamespace)
                          AND NOT tgisinternal""")
        assert set(cur.fetchall()) == {
            ("t_events_no_mut", 26, False, False),
            ("t_events_no_trunc", 34, False, False),
            ("t_effects_identity", 19, False, False),
            ("t_scopes_route", 19, False, False),
            ("t_installs_identity", 19, False, False),
            ("t_scopes_parent_route", 21, True, True),
        }
    conn.rollback()
    print("[catalog] ten tables; FK split; nondeferrable episode key; partial indexes; five trigger groups")


def negatives(conn, s):
    rejects(conn, "23505", "u_episodes_open", lambda c: episode(
        c, uuid4(), s["f1"], s["effect"], epoch=2))
    # The PK necessarily overlaps this redundant composite FK target; PostgreSQL
    # reports the PK first. catalog() independently proves the target is immediate.
    rejects(conn, "23505", "episodes_pkey", lambda c: c.execute(
        "INSERT INTO v24.episodes SELECT * FROM v24.episodes WHERE episode_id=%s", (s["ep1"],)))
    rejects(conn, "23505", "u_slots_live", lambda c: slot(
        c, uuid4(), s["f2"], s["ep2"], key=str(s["slot1"]), contribution_seq=2))
    rejects(conn, "23505", "u_pins_live", lambda c: pin(c, uuid4(), s))
    rejects(conn, "23503", "f_effects_scope", lambda c: effect(
        c, uuid4(), scope_id=uuid4()))
    rejects(conn, "23503", "f_fibers_install", lambda c: insert(
        c, "fibers", fiber_id=uuid4(), install_id=uuid4(), scope_id=s["root"],
        created_by_effect=s["effect"]))
    rejects(conn, "23503", "f_episodes_fiber", lambda c: episode(
        c, uuid4(), uuid4(), s["effect"]))
    rejects(conn, "23503", "f_slots_ep", lambda c: slot(
        c, uuid4(), s["f2"], s["ep1"], contribution_seq=2))
    sql_rejects(conn, "23503", "f_runs_owner_ep",
                "UPDATE v24.runs SET owner_fiber_id=%s,owner_episode_id=%s WHERE run_id=%s",
                (s["f2"], s["ep1"], s["run"]))
    rejects(conn, "23514", "c_pins_xor", lambda c: pin(
        c, uuid4(), s, consumer_run_id=s["run"]))
    rejects(conn, "23514", "c_pins_xor", lambda c: pin(
        c, uuid4(), s, consumer_episode_id=None))
    bad = uuid4()
    rejects(conn, "23514", "c_scopes_path_end", lambda c: scope(
        c, bad, s["effect"], route_path=[s["root"]]))
    # Both path checks fail for an empty array; PostgreSQL checks names in order.
    rejects(conn, "23514", "c_scopes_path_end", lambda c: scope(
        c, uuid4(), s["effect"], route_path=[]))
    rejects(conn, "23514", "c_scopes_path_end", lambda c: scope(
        c, uuid4(), s["effect"], route_path=[None]))
    # §4.12: these are DDL probes only; no S2/S3 lifecycle is claimed.
    for constraint, assignment in (
        ("c_runs_budget", "remaining_steps=-1"),
        ("c_runs_terminal", "status='completed'"),
        ("c_runs_waiting", "status='waiting'"),
    ):
        sql_rejects(conn, "23514", constraint,
                    f"UPDATE v24.runs SET {assignment} WHERE run_id=%s", (s["run"],))
    for constraint, assignment in (
        ("c_fibers_owner_pair", "owner_fiber_id=gen_random_uuid()"),
        ("c_fibers_tombstone", "want_on=true,disposed_at=now()"),
    ):
        sql_rejects(conn, "23514", constraint,
                    f"UPDATE v24.fibers SET {assignment} WHERE fiber_id=%s", (s["f1"],))
    sql_rejects(conn, "23514", "c_slots_release",
                "UPDATE v24.slots SET released_at=now() WHERE slot_id=%s", (s["slot1"],))
    sql_rejects(conn, "23514", "c_slots_release",
                "UPDATE v24.slots SET withdrawn_at=now(),released_at=now()-interval '1s' "
                "WHERE slot_id=%s", (s["slot1"],))
    sql_rejects(conn, "23514", "c_installs_identity_len",
                "INSERT INTO v24.installs (install_id,scope_id,identity,version,manifest,"
                "manifest_digest,requires,provides,artifact_digest,adapter_digest,"
                "owner_principal,state,created_by_effect) "
                "SELECT gen_random_uuid(),scope_id,'',version,manifest,manifest_digest,"
                "requires,provides,artifact_digest,adapter_digest,owner_principal,state,"
                "created_by_effect FROM v24.installs WHERE install_id=%s", (s["install"],))
    sql_rejects(conn, "23514", "c_installs_disposed",
                "UPDATE v24.installs SET state='disposed' WHERE install_id=%s", (s["install"],))
    sql_rejects(conn, "23514", "c_scopes_close_pair",
                "UPDATE v24.scopes SET closed_at=now() WHERE scope_id=%s", (s["root"],))
    sql_rejects(conn, "23514", "c_scopes_close_order",
                "UPDATE v24.scopes SET close_requested_at=now(),closed_at=now()-interval '1s' "
                "WHERE scope_id=%s", (s["root"],))
    for kind in ("command_scope_control", "command_install", "command_recover"):
        rejects(conn, "23514", "c_effects_command_claim", lambda c, kind=kind: effect(
            c, uuid4(), kind=kind, attempt_no=1))
    for statement in ("UPDATE v24.events SET payload=payload", "DELETE FROM v24.events",
                      "TRUNCATE v24.events", "UPDATE v24.events SET seq=seq WHERE false",
                      "DELETE FROM v24.events WHERE false"):
        sql_rejects(conn, "23514", "c_events_append_only", statement)
    # S6 W2 positive: a command_recover effect admits attempt_no=0, and the
    # widened event entity set accepts 'effect' while still rejecting a bogus
    # entity type.  Keep this in its own savepoint: a pending deferred event FK
    # would make the TRUNCATE probe above fail with ObjectInUse first.
    with conn.cursor() as cur:
        cur.execute("SAVEPOINT w2_effect_entity")
        recovery_effect = uuid4()
        effect(cur, recovery_effect, kind="command_recover")
        cur.execute("SELECT count(*) FROM v24.effects WHERE effect_id=%s",
                    (recovery_effect,))
        assert cur.fetchone() == (1,)
        insert(cur, "events", effect_id=s["effect"], seq=1, entity_type="effect",
               entity_id=recovery_effect, event_kind="effect_recovered_replay",
               payload_digest=DIGEST)
        cur.execute("SELECT count(*) FROM v24.events "
                    "WHERE entity_type='effect' AND entity_id=%s",
                    (recovery_effect,))
        assert cur.fetchone() == (1,)
        cur.execute("ROLLBACK TO SAVEPOINT w2_effect_entity")
        cur.execute("RELEASE SAVEPOINT w2_effect_entity")
    rejects(conn, "23514", "c_events_entity", lambda c: insert(
        c, "events", effect_id=s["effect"], seq=1, entity_type="bogus",
        entity_id=uuid4(), event_kind="effect_recovered_replay",
        payload_digest=DIGEST))
    conn.rollback()
    print("[negative] partial uniqueness, composite FKs, XOR, paths, reserved-column CHECKs, command claim, append-only")


def guards(conn, s):
    # Every frozen field is tested, including NULL -> non-NULL changes.
    groups = (
        ("effects", "effect_id", s["effect"], "c_effects_immutable", {
            "request": Json({"changed": True}), "request_digest": b"changed",
            "kind": "command_install", "requester_id": uuid4(),
            "scope_id": s["root2"], "run_id": None, "fiber_id": s["f2"],
            "episode_id": s["ep2"], "pin_id": None,
            "parent_effect_id": uuid4(), "ordinal": 1,
        }),
        ("scopes", "scope_id", s["root"], "c_scopes_immutable", {
            "root_id": s["root2"], "parent_id": s["root2"],
            "route_path": [s["root2"], s["root"]],
            "realm_routes": Json({"x": "y"}), "default_realm": "changed",
        }),
        ("installs", "install_id", s["install"], "c_installs_immutable", {
            "manifest": Json({"changed": True}), "manifest_digest": b"changed",
            "requires": Json(["changed"]), "provides": Json(["changed"]),
            "artifact_digest": b"changed", "adapter_digest": b"changed",
            "identity": "changed", "version": "2", "scope_id": s["root2"],
        }),
    )
    for table, pk, ident, constraint, columns in groups:
        for column, value in columns.items():
            statement = sql.SQL("UPDATE v24.{} SET {}=%s WHERE {}=%s").format(
                sql.Identifier(table), sql.Identifier(column), sql.Identifier(pk))
            sql_rejects(conn, "23514", constraint, statement, (value, ident))
    with conn.cursor() as cur:
        cur.execute("UPDATE v24.scopes SET close_requested_at=%s WHERE scope_id=%s RETURNING close_requested_at",
                    (NOW, s["root"]))
        assert cur.fetchone() == (NOW,)
        cur.execute("UPDATE v24.installs SET state='installed' WHERE install_id=%s RETURNING state",
                    (s["install"],))
        assert cur.fetchone() == ("installed",)
        cur.execute("UPDATE v24.effects SET cancel_requested=true WHERE effect_id=%s RETURNING cancel_requested",
                    (s["effect"],))
        assert cur.fetchone() == (True,)
        for table, pk, ident, _, columns in groups:
            column = next(iter(columns))
            cur.execute(sql.SQL("UPDATE v24.{} SET {}={} WHERE {}=%s RETURNING {}").format(
                sql.Identifier(table), sql.Identifier(column), sql.Identifier(column),
                sql.Identifier(pk), sql.Identifier(pk)), (ident,))
            assert cur.fetchone() == (ident,)
    conn.commit()
    print("[guards] all T2–T4 frozen fields rejected; permitted and no-op updates persist")


def rollover(conn, s):
    with conn.cursor() as cur:
        cur.execute("SAVEPOINT w2_rollover")
        cur.execute("UPDATE v24.episodes SET state='closed',closed_at=now() WHERE episode_id=%s",
                    (s["ep1"],))
        next_ep = uuid4()
        episode(cur, next_ep, s["f1"], s["effect"], epoch=2)
        cur.execute("UPDATE v24.fibers SET current_episode_id=%s WHERE fiber_id=%s", (next_ep, s["f1"]))
        cur.execute("UPDATE v24.slots SET withdrawn_at=now(),released_at=now() WHERE slot_id=%s",
                    (s["slot1"],))
        slot(cur, uuid4(), s["f1"], next_ep, key=str(s["slot1"]), contribution_seq=2)
        cur.execute("UPDATE v24.pins SET released_at=now(),released_by_effect=%s WHERE pin_id=%s",
                    (s["effect"], s["pin"]))
        pin(cur, uuid4(), s)
        cur.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cur.execute("ROLLBACK TO SAVEPOINT w2_rollover")
        cur.execute("RELEASE SAVEPOINT w2_rollover")
    conn.rollback()
    print("[order] close/release before replacement succeeds for episodes, slots, and pins")


def deferred(conn, s):
    missing = uuid4()
    commit_rejects(conn, "23503", "f_requests_effect",
                   lambda c: request(c, missing, "missing-effect"))
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM v24.requests WHERE effect_id=%s", (missing,))
        assert cur.fetchone() == (0,)
        # requests before effects proves the FK really closes at COMMIT.
        request(cur, missing, "late-effect")
        cur.execute("SELECT count(*) FROM v24.effects WHERE effect_id=%s", (missing,))
        assert cur.fetchone() == (0,)
        effect(cur, missing)
    conn.commit()
    bad_path = uuid4()
    commit_rejects(conn, "23514", "c_scopes_parent_route", lambda c: scope(
        c, bad_path, s["effect"], parent_id=s["root"], root_id=s["root"],
        route_path=[bad_path]))
    bad_root = uuid4()
    commit_rejects(conn, "23514", "c_scopes_parent_route", lambda c: scope(
        c, bad_root, s["effect"], parent_id=s["root"], root_id=s["root2"],
        route_path=[s["root"], bad_root]))
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM v24.scopes WHERE scope_id IN (%s,%s)", (bad_path, bad_root))
        assert cur.fetchone() == (0,)
    conn.rollback()
    print("[commit] missing request effect and child path/root rejected at COMMIT; late effect closes successfully")


def main() -> int:
    with server_helper_scope(), setup_db() as db, contextlib.closing(db.connect()) as conn:
        with conn.cursor() as cur:
            cur.execute("SET ROLE v24_owner")
        conn.commit()
        catalog(conn)
        s = seed_rows(conn)
        negatives(conn, s)
        guards(conn, s)
        rollover(conn, s)
        deferred(conn, s)
    print("[passed] v24 W2 G1-O owner DDL probes (no advance/ACL/lifecycle claim)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
