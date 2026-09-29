"""Phase A plan_read gate.

Run: UV_FROZEN=1 uv run python v13/plan_read/test_plan_read.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import uuid
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.load import run_psql
from v13.plan_read.setup_db import DB, main as setup_db
import v13.plan_read.setup_db as setup_mod

N = 0
SQL = (ROOT / "v13_plan_read.sql").read_text()


def check(label, condition, detail=""):
    global N
    N += 1
    mark = "PASS" if condition else "FAIL"
    extra = f": {detail}" if detail and (not condition or len(str(detail)) < 240) else ""
    print(f"[{mark}] {label}{extra}")
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u():
    return str(uuid.uuid4())


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def as_obj(value):
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


def connect(server):
    conn = psycopg2.connect(server.get_uri(DB))
    conn.autocommit = False
    return conn


def q1(cur, sql, params=None):
    cur.execute(sql, params)
    row = cur.fetchone()
    return None if row is None else row[0]


def counts(cur):
    return (
        q1(cur, "SELECT count(*) FROM sessions"),
        q1(cur, "SELECT count(*) FROM events"),
        q1(cur, "SELECT count(*) FROM effects"),
    )


def open_root(cur, version=1):
    spec = {"route_policy_name": "default", "version": version}
    return str(q1(cur, "SELECT v13_plan_commit_entry(%s::jsonb)", (json.dumps(spec),)))


def prefix(cur, sid, text="hello goal"):
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": text})))


def max_seq(cur, sid):
    return q1(cur, "SELECT max(seq) FROM events WHERE session_id=%s", (sid,))


def plan_n(cur, sid):
    return q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id=%s "
        "AND type IN ('plan/committed','todo/delta')",
        (sid,))


def todo(tid, text, cls, status, verb="add_new", due=None):
    return {
        "todo_id": tid,
        "text": text,
        "text_hash": sha(text),
        "task_class": cls,
        "status": status,
        "due": due,
        "verb": verb,
    }


def plan_body(todos, based, supersedes=None):
    return {
        "schema_version": 1,
        "call_kind": "plan_commit",
        "based_on_seq": based,
        "supersedes": supersedes,
        "todos": todos,
    }


def delta(tid, text, status_from, status_to, verb="update", binding=None,
          due=None, quarantine=None, link=None):
    return {
        "schema_version": 1,
        "call_kind": "todo_delta",
        "verb": verb,
        "todo_id": tid,
        "status_from": status_from,
        "status_to": status_to,
        "binding": binding,
        "due": due,
        "quarantine": quarantine,
        "text_hash": sha(text),
        "link": link,
    }


def writer(cur, sid, canonical, now=None, actor=None, apply=None, kind=None):
    kind = kind or canonical["call_kind"]
    apply = apply or u()
    cur.execute(
        "SELECT v13_plan_writer(%s::uuid, %s::uuid, %s::uuid, %s, %s::jsonb, %s::timestamptz)",
        (actor, sid, apply, kind, json.dumps(canonical), now))
    return apply, as_obj(cur.fetchone()[0])


def seed_root(cur, text="anchor"):
    sid = open_root(cur)
    prefix(cur, sid, text)
    return sid, max_seq(cur, sid)


def sort_ids(cur, ids):
    cur.execute("SELECT id::text FROM unnest(%s::uuid[]) AS id ORDER BY id", (ids,))
    return [row[0] for row in cur.fetchall()]


def inventory(cur, sid):
    return as_obj(q1(cur, "SELECT v13_plan_inventory(%s)", (sid,)))


def horizon(cur, sid):
    return as_obj(q1(cur, "SELECT v13_plan_horizon(%s)", (sid,)))


def current_id(cur, sid):
    obj = as_obj(q1(cur, "SELECT v13_plan_current(%s)", (sid,)))
    return None if obj is None else obj["plan_id"]


def commit_sorted(cur, sid, specs):
    ids = sort_ids(cur, [spec[0] for spec in specs])
    by_id = {spec[0]: spec for spec in specs}
    ordered = [todo(*by_id[tid]) for tid in ids]
    seq = max_seq(cur, sid)
    _, out = writer(cur, sid, plan_body(ordered, seq))
    return ids, out


def test_zero_write(cur):
    sid, _seq = seed_root(cur)
    commit_sorted(cur, sid, [(u(), "one", "advancement_task", "runnable")])
    before = counts(cur)
    got = inventory(cur, sid)
    hor = horizon(cur, sid)
    after = counts(cur)
    inv_src = q1(cur, "SELECT pg_get_functiondef('public.v13_plan_inventory(uuid)'::regprocedure)")
    hor_src = q1(cur, "SELECT pg_get_functiondef('public.v13_plan_horizon(uuid)'::regprocedure)")
    vol = (
        q1(cur, "SELECT provolatile FROM pg_proc WHERE proname = 'v13_plan_inventory'"),
        q1(cur, "SELECT provolatile FROM pg_proc WHERE proname = 'v13_plan_horizon'"),
    )
    quiet = (
        "INSERT" not in inv_src and "UPDATE" not in inv_src and "DELETE" not in inv_src
        and "v13_append_event" not in inv_src and "v13_plan_writer" not in inv_src
        and "INSERT" not in hor_src and "UPDATE" not in hor_src and "DELETE" not in hor_src
        and "v13_append_event" not in hor_src and "v13_plan_writer" not in hor_src
        and "CREATE OR REPLACE" not in SQL and "v13_advance" not in SQL
    )
    check(
        "zero_write",
        before == after and vol == ("s", "s") and quiet
        and got["rows_examined"] == 1 and hor["items"]["rows_examined"] == 1,
        (before, after, vol))


def test_inventory_caps(cur):
    sid, _seq = seed_root(cur, "thirty-three")
    specs = [(u(), f"item-{i:02d}", "advancement_task", "runnable") for i in range(33)]
    ids, _out = commit_sorted(cur, sid, specs)
    got = inventory(cur, sid)
    returned = [row["todo_id"] for row in got["items"]]
    check(
        "inventory_33",
        got["rows_examined"] == 32
        and got["rows_returned"] == 32
        and got["omitted_count"] == 1
        and got["omitted_complete"] is False
        and returned == ids[:32]
        and ids[32] not in returned,
        (got["rows_examined"], got["omitted_count"], len(returned)))

    sid32, _seq = seed_root(cur, "thirty-two")
    specs32 = [(u(), f"row-{i:02d}", "advancement_task", "runnable") for i in range(32)]
    ids32, _out = commit_sorted(cur, sid32, specs32)
    got32 = inventory(cur, sid32)
    returned32 = [row["todo_id"] for row in got32["items"]]
    check(
        "inventory_32",
        got32["rows_examined"] == 32
        and got32["rows_returned"] == 32
        and got32["omitted_count"] == 0
        and got32["omitted_complete"] is True
        and returned32 == ids32,
        (got32["rows_examined"], got32["omitted_count"]))

    sid0, _seq = seed_root(cur, "none")
    got0 = inventory(cur, sid0)
    check(
        "inventory_0",
        got0["rows_examined"] == 0
        and got0["rows_returned"] == 0
        and got0["omitted_count"] == 0
        and got0["omitted_complete"] is True
        and got0["items"] == [],
        got0)


def test_horizon_caps(cur):
    sid, _seq = seed_root(cur, "horizon")
    carrier = u()
    targets = [u() for _ in range(5)]
    blockers = [u(), u()]
    specs = [(carrier, "carrier", "advancement_task", "runnable")]
    specs.extend((tid, f"target-{i}", "advancement_task", "runnable") for i, tid in enumerate(targets))
    specs.extend((tid, f"block-{i}", "blocker", "pending") for i, tid in enumerate(blockers))
    ids, _out = commit_sorted(cur, sid, specs)
    open_ids = ids
    for tid in targets:
        writer(cur, sid, delta(
            carrier, "carrier", "runnable", "runnable",
            verb="link_successor", link={"on": "successor", "id": tid}))
    hor = horizon(cur, sid)
    items = hor["items"]
    rels = hor["relations"]
    gaps = hor["gaps"]
    item_ids = [row["todo_id"] for row in items["rows"]]
    rel_targets = [row["target"] for row in rels["rows"]]
    gap_ids = [row["todo_id"] for row in gaps["rows"]]
    blocker_order = [tid for tid in open_ids if tid in blockers]
    check(
        "horizon_caps",
        items["rows_examined"] == 4
        and items["rows_returned"] == 4
        and items["omitted_count"] == 1
        and items["omitted_complete"] is False
        and item_ids == open_ids[:4]
        and rels["rows_examined"] == 4
        and rels["rows_returned"] == 4
        and rels["omitted_count"] == 1
        and rels["omitted_complete"] is False
        and rel_targets == targets[:4]
        and gaps["rows_examined"] == 1
        and gaps["rows_returned"] == 1
        and gaps["omitted_count"] == 1
        and gaps["omitted_complete"] is False
        and gap_ids == [blocker_order[0]],
        (items["omitted_count"], rels["omitted_count"], gaps["omitted_count"], gap_ids))


def test_gap_inserts_nothing(cur):
    sid, _seq = seed_root(cur, "gap")
    bid = u()
    commit_sorted(cur, sid, [(bid, "open blocker", "blocker", "pending")])
    before = counts(cur)
    replan_before = q1(cur, "SELECT count(*) FROM events WHERE type = 'replan/required'")
    hor = horizon(cur, sid)
    after = counts(cur)
    replan_after = q1(cur, "SELECT count(*) FROM events WHERE type = 'replan/required'")
    check(
        "gap_inserts_nothing",
        before == after and replan_before == replan_after == 0
        and hor["gaps"]["rows_returned"] == 1
        and hor["gaps"]["rows"][0]["kind"] == "blocker"
        and hor["gaps"]["rows"][0]["todo_id"] == bid
        and plan_n(cur, sid) == 2,
        (before, after, hor["gaps"]))


def test_text_cap(cur):
    sid, _seq = seed_root(cur, "cap")
    text = "n" * 1024
    tid = u()
    commit_sorted(cur, sid, [(tid, text, "advancement_task", "runnable")])
    got = inventory(cur, sid)
    row = got["items"][0]
    check(
        "text_cap",
        got["rows_examined"] == 1
        and row["text"] == text
        and len(row["text"]) == 1024
        and "left(" in SQL
        and "1024" in SQL,
        len(row["text"]))


def test_empty_plan(cur):
    sid, _seq = seed_root(cur, "empty")
    before = counts(cur)
    got = inventory(cur, sid)
    hor = horizon(cur, sid)
    after = counts(cur)
    check(
        "empty_plan",
        got["rows_examined"] == 0 and got["items"] == []
        and hor["items"]["rows_examined"] == 0
        and hor["relations"]["rows_examined"] == 0
        and hor["gaps"]["rows_examined"] == 0
        and before == after,
        got)
    tid = u()
    _, out = writer(cur, sid, plan_body(
        [todo(tid, "will expire", "advancement_task", "runnable")],
        max_seq(cur, sid)))
    check("empty_plan", current_id(cur, sid) == out["plan_id"] and inventory(cur, sid)["rows_examined"] == 1)
    prefix(cur, sid, "later message")
    folded = q1(cur, "SELECT count(*) FROM v13_plan_todo_fold(%s)", (sid,))
    got2 = inventory(cur, sid)
    check(
        "empty_plan",
        current_id(cur, sid) is None
        and folded == 1
        and got2["rows_examined"] == 0
        and got2["rows_returned"] == 0
        and got2["omitted_count"] == 0
        and got2["items"] == [],
        (folded, got2["rows_examined"]))


def test_child_reads_root_stream(cur):
    sid, _seq = seed_root(cur, "parent stream")
    ids, out = commit_sorted(cur, sid, [
        (u(), "root-a", "advancement_task", "runnable"),
        (u(), "root-b", "advancement_task", "pending"),
    ])
    root_inv = inventory(cur, sid)
    plan_id = current_id(cur, sid)
    cur.execute("SAVEPOINT sp_child")
    cur.execute("SET ROLE v13_spawn_owner")
    cur.execute(
        "INSERT INTO sessions (parent_session_id, route_policy_name, route_policy_version) "
        "VALUES (%s, 'default', 1) RETURNING session_id",
        (sid,))
    child = str(cur.fetchone()[0])
    cur.execute("RESET ROLE")
    cur.execute("RELEASE SAVEPOINT sp_child")
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'workflow/pointer', %s::jsonb)",
        (child, u(), json.dumps({
            "schema_version": 1,
            "parent_session_id": sid,
            "root_session_id": sid,
            "todo_id": ids[0],
            "up_to_seq": 0,
        })))
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'plan/committed', %s::jsonb)",
        (child, u(), json.dumps({
            "apply_id": u(),
            "call_kind": "plan_commit",
            "canonical": {"schema_version": 1, "note": "child domain"},
            "plan_id": u(),
        })))
    child_inv = inventory(cur, child)
    check(
        "child_reads_root_stream",
        child_inv["rows_examined"] == root_inv["rows_examined"] == 2
        and [row["todo_id"] for row in child_inv["items"]] == ids
        and current_id(cur, sid) == plan_id == out["plan_id"]
        and current_id(cur, child) == plan_id
        and plan_n(cur, child) == 1
        and plan_n(cur, sid) == 2,
        (child_inv["rows_examined"], root_inv["rows_examined"], plan_id))


def run(cur):
    test_zero_write(cur)
    test_inventory_caps(cur)
    test_horizon_caps(cur)
    test_gap_inserts_nothing(cur)
    test_text_cap(cur)
    test_empty_plan(cur)
    test_child_reads_root_stream(cur)
    cur.execute("COMMIT")


def main() -> int:
    print("[db]", DB)
    if setup_db() != 0:
        return 1
    server = get_server()
    conn = connect(server)
    try:
        run(conn.cursor())
    finally:
        conn.close()
        if setup_mod.CREATED:
            run_psql(server, "postgres", f'DROP DATABASE "{DB}" WITH (FORCE);')
            setup_mod.CREATED = False
            print("[dropped]", DB)
    print(f"[ok] {N} checks")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[FAIL] {exc}")
        if setup_mod.CREATED:
            try:
                run_psql(get_server(), "postgres", f'DROP DATABASE "{DB}" WITH (FORCE);')
                print("[dropped]", DB)
            except Exception as drop_exc:
                print("[cleanup-fail]", drop_exc)
        raise SystemExit(1)
