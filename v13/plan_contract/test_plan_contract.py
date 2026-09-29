"""Phase A plan_contract gate.

Run: UV_FROZEN=1 uv run python v13/plan_contract/test_plan_contract.py
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
from v13.plan_contract.setup_db import DB, main as setup_db
import v13.plan_contract.setup_db as setup_mod

N = 0
SQL = (ROOT / "v13_plan_contract.sql").read_text()


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


def apply_id(text):
    raw = bytearray(hashlib.sha256(text.encode("utf-8")).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x80
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(raw)))


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


def fails_with(cur, sql, params, needle, label):
    cur.execute("SAVEPOINT sp")
    try:
        cur.execute(sql, params)
    except psycopg2.Error as exc:
        msg = exc.diag.message_primary or str(exc).splitlines()[0]
        check(label, needle in msg, msg)
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        return msg
    cur.execute("ROLLBACK TO SAVEPOINT sp")
    raise AssertionError(f"{label}: expected failure")


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


def writer_fail(cur, sid, canonical, needle, label, now=None, actor=None, apply=None, kind=None):
    kind = kind or canonical["call_kind"]
    apply = apply or u()
    fails_with(
        cur,
        "SELECT v13_plan_writer(%s::uuid, %s::uuid, %s::uuid, %s, %s::jsonb, %s::timestamptz)",
        (actor, sid, apply, kind, json.dumps(canonical), now),
        needle,
        label)
    return apply


def fold_row(cur, sid, tid):
    cur.execute(
        "SELECT status, due, effect_id, child_session_id, quarantine::text, task_class, text_hash "
        "FROM v13_plan_todo_fold(%s) WHERE todo_id=%s",
        (sid, tid))
    row = cur.fetchone()
    if row is None:
        return None
    q = None if row[4] is None else json.loads(row[4])
    return {
        "status": row[0],
        "due": row[1],
        "effect_id": row[2],
        "child_session_id": row[3],
        "quarantine": q,
        "task_class": row[5],
        "text_hash": row[6],
    }


def current_id(cur, sid):
    obj = as_obj(q1(cur, "SELECT v13_plan_current(%s)", (sid,)))
    return None if obj is None else obj["plan_id"]


def seed_root(cur, text="anchor"):
    sid = open_root(cur)
    prefix(cur, sid, text)
    return sid, max_seq(cur, sid)


def test_prelude(cur):
    before = (
        q1(cur, "SELECT count(*) FROM sessions"),
        q1(cur, "SELECT count(*) FROM events"),
        q1(cur, "SELECT count(*) FROM effects"),
    )
    got = as_obj(q1(
        cur,
        "SELECT v13_plan_prelude(%s::jsonb)",
        (json.dumps({"route_policy_name": "default", "version": 2}),)))
    after = (
        q1(cur, "SELECT count(*) FROM sessions"),
        q1(cur, "SELECT count(*) FROM events"),
        q1(cur, "SELECT count(*) FROM effects"),
    )
    src = q1(cur, "SELECT pg_get_functiondef('public.v13_plan_prelude(jsonb)'::regprocedure)")
    check("prelude_zero_insert", before == after and got["version"] == 2, (before, after, got))
    check("prelude_zero_insert", "v13_open_session" not in src and "INSERT" not in src, "prelude writes")
    fails_with(
        cur,
        "SELECT v13_plan_prelude(%s::jsonb)",
        (json.dumps({}),),
        "v13: plan prelude: version_required",
        "prelude_zero_insert")
    before_n = q1(cur, "SELECT count(*) FROM sessions")
    msg = fails_with(
        cur,
        "SELECT v13_plan_prelude(%s::jsonb)",
        (json.dumps({"route_policy_name": "default", "version": 9999999999}),),
        "v13: plan prelude: version_required",
        "prelude_zero_insert")
    after_n = q1(cur, "SELECT count(*) FROM sessions")
    check("prelude_zero_insert", before_n == after_n and "out of range" not in msg, msg)


def test_empty_and_version(cur):
    before = q1(cur, "SELECT count(*) FROM sessions")
    fails_with(
        cur,
        "SELECT v13_plan_commit_entry(%s::jsonb)",
        (json.dumps({}),),
        "v13: plan commit entry: version_required",
        "empty_spec_rejected")
    after = q1(cur, "SELECT count(*) FROM sessions")
    check("empty_spec_rejected", before == after, (before, after))
    msg = fails_with(
        cur,
        "SELECT v13_plan_commit_entry(%s::jsonb)",
        (json.dumps({"route_policy_name": "default", "version": 9999999999}),),
        "v13: plan commit entry: version_required",
        "empty_spec_rejected")
    after = q1(cur, "SELECT count(*) FROM sessions")
    check("empty_spec_rejected", before == after and "out of range" not in msg, (before, after, msg))
    cur.execute(
        "INSERT INTO v13_route_policies (policy_name, policy_version) VALUES ('default', 99)")
    cur.execute(
        "UPDATE v13_route_policies SET state = 'frozen' "
        "WHERE policy_name = 'default' AND policy_version = 99")
    sid = str(q1(
        cur,
        "SELECT v13_plan_commit_entry(%s::jsonb)",
        (json.dumps({"route_policy_name": "default", "version": 99}),)))
    ver = q1(cur, "SELECT route_policy_version FROM sessions WHERE session_id=%s", (sid,))
    name = q1(cur, "SELECT route_policy_name FROM sessions WHERE session_id=%s", (sid,))
    src = q1(cur, "SELECT pg_get_functiondef('public.v13_plan_commit_entry(jsonb)'::regprocedure)")
    check("explicit_version_binds_column", ver == 99 and name == "default", (ver, name))
    check("explicit_version_binds_column", "v13_open_session" in src)


def test_plan_commit(cur):
    sid, seq = seed_root(cur)
    tid = u()
    body = plan_body([todo(tid, "one task", "advancement_task", "runnable")], seq)
    apply, out = writer(cur, sid, body)
    rows = q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id=%s AND payload->>'apply_id'=%s",
        (sid, apply))
    kinds = q1(
        cur,
        "SELECT count(DISTINCT type) FROM events WHERE session_id=%s AND payload->>'apply_id'=%s",
        (sid, apply))
    same_can = q1(
        cur,
        "SELECT count(DISTINCT payload->'canonical') FROM events "
        "WHERE session_id=%s AND payload->>'apply_id'=%s",
        (sid, apply))
    xmin_n = q1(
        cur,
        "SELECT count(DISTINCT xmin::text) FROM events "
        "WHERE session_id=%s AND payload->>'apply_id'=%s",
        (sid, apply))
    twin_id = q1(
        cur,
        "SELECT payload->>'todo_id' FROM events "
        "WHERE session_id=%s AND type='todo/delta' AND payload->>'apply_id'=%s",
        (sid, apply))
    effects = q1(cur, "SELECT count(*) FROM effects WHERE session_id=%s", (sid,))
    check(
        "plan_commit_one_tx",
        rows == 2 and kinds == 2 and same_can == 1 and xmin_n == 1
        and twin_id == tid and effects == 0 and out["replayed"] is False
        and out["todo_ids"] == [tid],
        (rows, kinds, same_can, xmin_n, twin_id, out))
    a, b = u(), u()
    ordered = sorted([a, b], key=lambda item: uuid.UUID(item).bytes)
    seq2 = max_seq(cur, sid)
    body2 = plan_body(
        [
            todo(ordered[0], "left", "advancement_task", "pending"),
            todo(ordered[1], "right", "user_gate", "blocked"),
        ],
        seq2,
        supersedes=out["plan_id"])
    apply2, out2 = writer(cur, sid, body2)
    null_id = q1(
        cur,
        "SELECT payload->'todo_id' FROM events "
        "WHERE session_id=%s AND type='todo/delta' AND payload->>'apply_id'=%s",
        (sid, apply2))
    null_id = as_obj(null_id) if not isinstance(null_id, (dict, list, type(None))) else null_id
    check("plan_commit_one_tx", null_id is None and out2["todo_ids"] == ordered, (null_id, out2))
    bad = plan_body([todo(u(), "x", "advancement_task", "runnable")], max_seq(cur, sid))
    bad["todos"][0]["text_hash"] = "0" * 64
    before = plan_n(cur, sid)
    writer_fail(cur, sid, bad, "v13: plan writer: canonical", "plan_commit_one_tx")
    check("plan_commit_one_tx", plan_n(cur, sid) == before)


def test_replay_and_conflict(cur):
    sid, seq = seed_root(cur)
    tid = u()
    body = plan_body([todo(tid, "keep", "advancement_task", "runnable")], seq)
    apply, first = writer(cur, sid, body)
    before = plan_n(cur, sid)
    _, second = writer(cur, sid, body, apply=apply)
    check(
        "replay_same_ids",
        second["replayed"] is True
        and second["plan_id"] == first["plan_id"]
        and second["todo_ids"] == first["todo_ids"]
        and plan_n(cur, sid) == before,
        second)
    other = plan_body([todo(tid, "changed", "advancement_task", "runnable")], seq)
    writer_fail(cur, sid, other, "v13: plan writer: replay_conflict", "conflict_raises", apply=apply)
    check("conflict_raises", plan_n(cur, sid) == before)
    writer_fail(
        cur, sid, delta(tid, "keep", "runnable", "done"),
        "v13: plan writer: replay_conflict", "conflict_raises", apply=apply, kind="todo_delta")
    check("conflict_raises", plan_n(cur, sid) == before)


def test_stop_and_terminal(cur):
    fp_before = q1(
        cur,
        "SELECT md5(prosrc) FROM pg_proc WHERE oid = 'public.v13_goal_fingerprint(uuid)'::regprocedure")
    sid, seq = seed_root(cur)
    tid = u()
    body = plan_body([todo(tid, "stop me", "advancement_task", "pending")], seq)
    apply, first = writer(cur, sid, body)
    d_apply, _ = writer(cur, sid, delta(tid, "stop me", "pending", "runnable"))
    fp = q1(cur, "SELECT v13_goal_fingerprint(%s)", (sid,))
    n_before = plan_n(cur, sid)
    q1(cur, "SELECT v13_goal_stop(%s, %s)", (sid, "pause"))
    _, replayed = writer(cur, sid, body, apply=apply)
    _, d_replay = writer(
        cur, sid, delta(tid, "stop me", "pending", "runnable"), apply=d_apply)
    fp_after = q1(cur, "SELECT v13_goal_fingerprint(%s)", (sid,))
    fp_fn = q1(
        cur,
        "SELECT md5(prosrc) FROM pg_proc WHERE oid = 'public.v13_goal_fingerprint(uuid)'::regprocedure")
    check(
        "replay_after_stop",
        replayed["plan_id"] == first["plan_id"]
        and replayed["replayed"] is True
        and d_replay["replayed"] is True
        and plan_n(cur, sid) == n_before
        and fp_after == fp
        and fp_fn == fp_before
        and "plan/committed" not in q1(
            cur,
            "SELECT prosrc FROM pg_proc WHERE oid = 'public.v13_goal_fingerprint(uuid)'::regprocedure")
        and "v13_goal_fingerprint" not in SQL,
        (replayed, n_before, plan_n(cur, sid)))
    fresh = plan_body([todo(u(), "after stop", "advancement_task", "pending")], max_seq(cur, sid))
    writer_fail(cur, sid, fresh, "v13: plan writer: stopped", "replay_after_stop")
    check("replay_after_stop", plan_n(cur, sid) == n_before)

    sid2, seq2 = seed_root(cur)
    q1(cur, "SELECT v13_goal_stop(%s, %s)", (sid2, "first"))
    writer_fail(
        cur, sid2,
        plan_body([todo(u(), "nope", "advancement_task", "runnable")], seq2),
        "v13: plan writer: stopped", "first_write_stopped")
    check("first_write_stopped", plan_n(cur, sid2) == 0)
    check(
        "first_write_stopped",
        q1(cur, "SELECT v13_plan_admit(NULL::uuid, %s)", (sid2,)) is False)

    for status in ("completed", "failed", "cancelled"):
        sid3, seq3 = seed_root(cur)
        cur.execute("UPDATE sessions SET status=%s WHERE session_id=%s", (status, sid3))
        writer_fail(
            cur, sid3,
            plan_body([todo(u(), status, "advancement_task", "runnable")], seq3),
            "v13: plan writer: terminal", "first_write_terminal")
        check("first_write_terminal", plan_n(cur, sid3) == 0)


def test_auth_and_child(cur):
    sid, seq = seed_root(cur)
    body = plan_body([todo(u(), "root only", "advancement_task", "runnable")], seq)
    writer_fail(cur, sid, body, "v13: plan writer: auth", "root_actor_rejected", actor=u())
    check("root_actor_rejected", plan_n(cur, sid) == 0)
    apply, first = writer(cur, sid, body)
    writer_fail(cur, sid, body, "v13: plan writer: auth", "root_actor_rejected", actor=u(), apply=apply)
    check("root_actor_rejected", plan_n(cur, sid) == 1 + 1)

    cur.execute("SAVEPOINT sp_role")
    cur.execute("SET ROLE v13_spawn_owner")
    cur.execute(
        "INSERT INTO sessions (parent_session_id, route_policy_name, route_policy_version) "
        "VALUES (%s, 'default', 1) RETURNING session_id",
        (sid,))
    child = str(cur.fetchone()[0])
    cur.execute("RESET ROLE")
    cur.execute("RELEASE SAVEPOINT sp_role")
    seq_c = max_seq(cur, sid)
    tid = u()
    _, out = writer(
        cur, child,
        plan_body([todo(tid, "from child", "advancement_task", "pending")], seq_c))
    on_child = plan_n(cur, child)
    on_root = q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id=%s AND payload->>'plan_id'=%s",
        (sid, out["plan_id"]))
    check("child_maps_to_root", on_child == 0 and on_root == 2 and current_id(cur, child) == out["plan_id"],
          (on_child, on_root, out))


def test_waterline(cur):
    sid, seq = seed_root(cur)
    tid = u()
    body = plan_body([todo(tid, "water", "advancement_task", "runnable")], seq)
    _, out = writer(cur, sid, body)
    check("waterline_user_message", current_id(cur, sid) == out["plan_id"], out)
    prefix(cur, sid, "later")
    check("waterline_user_message", current_id(cur, sid) is None)
    _, d_out = writer(cur, sid, delta(tid, "water", "runnable", "done"))
    check(
        "waterline_user_message",
        d_out["replayed"] is False and current_id(cur, sid) is None
        and fold_row(cur, sid, tid)["status"] == "done")
    bad = plan_body(
        [todo(u(), "wrong seq", "advancement_task", "waiting")],
        0)
    writer_fail(cur, sid, bad, "v13: plan writer: waterline", "waterline_user_message")
    src = q1(cur, "SELECT pg_get_functiondef('public.v13_plan_current(uuid)'::regprocedure)")
    steer_n = q1(cur, "SELECT count(*) FROM events WHERE type = 'steer/injected'")
    check("steer_literal_not_closed", "steer/injected" not in src and steer_n == 0, src)


def test_reuse(cur):
    sid, seq = seed_root(cur)
    tid = u()
    text = "same text"
    _, first = writer(
        cur, sid,
        plan_body([todo(tid, text, "advancement_task", "runnable", due="2026-09-29 00:00:00+00")], seq))
    eid = u()
    writer(
        cur, sid,
        delta(tid, text, "runnable", "runnable",
               binding={"effect_id": eid, "child_session_id": None}))
    seq2 = max_seq(cur, sid)
    _, reused = writer(
        cur, sid,
        plan_body(
            [todo(tid, text, "advancement_task", "runnable", verb="reuse",
                  due="2026-09-29 00:00:00+00")],
            seq2,
            supersedes=first["plan_id"]))
    row = fold_row(cur, sid, tid)
    check(
        "reuse_keeps_fold",
        row["status"] == "runnable" and row["effect_id"] == eid
        and row["due"] == "2026-09-29 00:00:00+00" and row["task_class"] == "advancement_task"
        and reused["replayed"] is False,
        row)
    before = plan_n(cur, sid)
    writer_fail(
        cur, sid,
        plan_body(
            [todo(tid, "other", "advancement_task", "runnable", verb="reuse",
                  due="2026-09-29 00:00:00+00")],
            max_seq(cur, sid),
            supersedes=first["plan_id"]),
        "v13: plan writer: reuse_hash",
        "reuse_keeps_fold")
    writer_fail(
        cur, sid,
        plan_body(
            [todo(tid, text, "advancement_task", "pending", verb="reuse",
                  due="2026-09-29 00:00:00+00")],
            max_seq(cur, sid),
            supersedes=first["plan_id"]),
        "v13: plan writer: transition",
        "reuse_keeps_fold")
    check("reuse_keeps_fold", plan_n(cur, sid) == before and fold_row(cur, sid, tid)["effect_id"] == eid)
    pend = u()
    writer(
        cur, sid,
        plan_body([todo(pend, "pend bind", "advancement_task", "pending")], max_seq(cur, sid)))
    before = plan_n(cur, sid)
    bad_eid = u()
    writer_fail(
        cur, sid,
        delta(pend, "pend bind", "pending", "pending",
               binding={"effect_id": bad_eid, "child_session_id": None}),
        "v13: plan writer: transition", "reuse_keeps_fold")
    check(
        "reuse_keeps_fold",
        plan_n(cur, sid) == before and fold_row(cur, sid, pend)["effect_id"] is None)


def test_transitions(cur):
    sid, seq = seed_root(cur)
    cases = [
        (todo(u(), "a", "advancement_task", "pending"), None),
        (todo(u(), "b", "advancement_task", "runnable"), None),
        (todo(u(), "c", "user_gate", "blocked"), None),
        (todo(u(), "d", "user_action", "pending"), None),
        (todo(u(), "e", "blocker", "runnable"), None),
        (todo(u(), "m", "continuous_monitor", "waiting", due="2026-09-29 00:00:00+00"), None),
    ]
    ids = [item[0]["todo_id"] for item in cases]
    ids.sort(key=lambda item: uuid.UUID(item).bytes)
    ordered = []
    for tid in ids:
        ordered.append(next(item for item, _ in cases if item["todo_id"] == tid))
    writer(cur, sid, plan_body(ordered, seq))
    check("class_initial_and_transitions", plan_n(cur, sid) == 2)

    bad_initials = [
        todo(u(), "bad a", "advancement_task", "waiting"),
        todo(u(), "bad g", "user_gate", "waiting"),
        todo(u(), "bad m", "continuous_monitor", "pending", due="2026-09-29 00:00:00+00"),
        todo(u(), "bad done", "advancement_task", "done"),
    ]
    for item in bad_initials:
        writer_fail(
            cur, sid, plan_body([item], max_seq(cur, sid)),
            "v13: plan writer: bad_initial", "class_initial_and_transitions")
    writer_fail(
        cur, sid,
        plan_body([todo(u(), "empty due", "continuous_monitor", "waiting")], max_seq(cur, sid)),
        "v13: plan writer: empty_due", "class_initial_and_transitions")

    pend = next(item["todo_id"] for item in ordered if item["text"] == "a")
    run = next(item["todo_id"] for item in ordered if item["text"] == "b")
    mon = next(item["todo_id"] for item in ordered if item["text"] == "m")
    writer(cur, sid, delta(pend, "a", "pending", "runnable"))
    writer(cur, sid, delta(pend, "a", "runnable", "dropped"))
    writer_fail(
        cur, sid, delta(pend, "a", "dropped", "runnable"),
        "v13: plan writer: transition", "class_initial_and_transitions")
    writer(cur, sid, delta(run, "b", "runnable", "waiting"))
    writer_fail(
        cur, sid, delta(run, "b", "waiting", "runnable"),
        "v13: plan writer: transition", "class_initial_and_transitions")
    writer(cur, sid, delta(run, "b", "waiting", "dropped"))
    writer(
        cur, sid,
        delta(mon, "m", "waiting", "runnable", due=None),
        now="2026-09-29 12:00:00+00")
    check("class_initial_and_transitions", fold_row(cur, sid, mon)["status"] == "runnable")
    writer_fail(
        cur, sid,
        delta(mon, "m", "runnable", "waiting"),
        "v13: plan writer: empty_due", "class_initial_and_transitions")
    writer(
        cur, sid,
        delta(mon, "m", "runnable", "waiting", due="2026-09-30 00:00:00+00"))
    check(
        "class_initial_and_transitions",
        fold_row(cur, sid, mon)["status"] == "waiting"
        and fold_row(cur, sid, mon)["due"] == "2026-09-30 00:00:00+00")
    writer_fail(
        cur, sid,
        delta(mon, "m", "waiting", "runnable"),
        "v13: plan writer: transition", "class_initial_and_transitions",
        now="2026-09-29 18:00:00+00")
    writer(
        cur, sid,
        delta(mon, "m", "waiting", "runnable"),
        now="2026-09-30 00:00:00+00")
    check("class_initial_and_transitions", fold_row(cur, sid, mon)["status"] == "runnable")


def test_links(cur):
    sid, seq = seed_root(cur)
    a, b, c = sorted((u(), u(), u()), key=lambda item: uuid.UUID(item).bytes)
    writer(
        cur, sid,
        plan_body(
            [
                todo(a, "A", "advancement_task", "runnable"),
                todo(b, "B", "advancement_task", "pending"),
                todo(c, "C", "blocker", "blocked"),
            ],
            seq))
    writer(
        cur, sid,
        delta(a, "A", "runnable", "runnable", verb="link_successor",
               link={"on": "successor", "id": b}))
    writer_fail(
        cur, sid,
        delta(b, "B", "pending", "pending", verb="link_successor",
               link={"on": "successor", "id": a}),
        "v13: plan writer: cycle", "link_cycle_and_goal")
    writer_fail(
        cur, sid,
        delta(a, "A", "runnable", "runnable", verb="link_successor",
               link={"on": "resume", "id": a}),
        "v13: plan writer: cycle", "link_cycle_and_goal")
    writer_fail(
        cur, sid,
        delta(c, "C", "blocked", "blocked", verb="link_successor",
               link={"on": "successor", "id": u()}),
        "v13: plan writer: canonical", "link_cycle_and_goal")
    other, oseq = seed_root(cur, "other")
    foreign = u()
    writer(
        cur, other,
        plan_body([todo(foreign, "F", "advancement_task", "pending")], oseq))
    before = plan_n(cur, sid)
    writer_fail(
        cur, sid,
        delta(b, "B", "pending", "pending", verb="link_successor",
               link={"on": "resume", "id": foreign}),
        "v13: plan writer: canonical", "link_cycle_and_goal")
    check("link_cycle_and_goal", plan_n(cur, sid) == before)
    root, root_seq = seed_root(cur, "branch cycle")
    a_id, x_id, c_id, t_id = u(), u(), u(), u()
    names = {a_id: "A", x_id: "X", c_id: "C", t_id: "T"}
    ordered = sorted((a_id, x_id, c_id, t_id), key=lambda item: uuid.UUID(item).bytes)
    writer(
        cur, root,
        plan_body(
            [todo(item, names[item], "advancement_task", "pending") for item in ordered],
            root_seq))
    writer(
        cur, root,
        delta(a_id, "A", "pending", "pending", verb="link_successor",
              link={"on": "successor", "id": x_id}))
    writer(
        cur, root,
        delta(a_id, "A", "pending", "pending", verb="link_successor",
              link={"on": "successor", "id": c_id}))
    writer(
        cur, root,
        delta(c_id, "C", "pending", "pending", verb="link_successor",
              link={"on": "successor", "id": t_id}))
    before = plan_n(cur, root)
    writer_fail(
        cur, root,
        delta(t_id, "T", "pending", "pending", verb="link_successor",
              link={"on": "successor", "id": a_id}),
        "v13: plan writer: cycle", "link_cycle_and_goal")
    check("link_cycle_and_goal", plan_n(cur, root) == before)


def test_quarantine(cur):
    sid, seq = seed_root(cur)
    tid, done_id = sorted((u(), u()), key=lambda item: uuid.UUID(item).bytes)
    writer(
        cur, sid,
        plan_body(
            [
                todo(tid, "q", "advancement_task", "runnable"),
                todo(done_id, "fin", "advancement_task", "runnable"),
            ],
            seq))
    eid = u()
    writer(
        cur, sid,
        delta(tid, "q", "runnable", "blocked",
               quarantine={"effect_id": eid, "cleared": False}))
    row = fold_row(cur, sid, tid)
    check(
        "quarantine_reenable",
        row["status"] == "blocked" and row["quarantine"]["cleared"] is False
        and row["quarantine"]["effect_id"] == eid,
        row)
    before = plan_n(cur, sid)
    writer_fail(
        cur, sid, delta(tid, "q", "blocked", "runnable"),
        "v13: plan writer: transition", "quarantine_reenable")
    writer_fail(
        cur, sid,
        delta(tid, "q", "blocked", "blocked",
               quarantine={"effect_id": eid, "cleared": True}),
        "v13: plan writer: transition", "quarantine_reenable")
    check("quarantine_reenable", plan_n(cur, sid) == before)
    writer(
        cur, sid,
        delta(tid, "q", "blocked", "runnable",
               binding={"clear_binding": True},
               quarantine={"effect_id": eid, "cleared": True}))
    row = fold_row(cur, sid, tid)
    check(
        "quarantine_reenable",
        row["status"] == "runnable" and row["effect_id"] is None
        and row["quarantine"]["cleared"] is True,
        row)
    writer(cur, sid, delta(done_id, "fin", "runnable", "done"))
    writer_fail(
        cur, sid,
        delta(done_id, "fin", "done", "runnable",
               binding={"clear_binding": True},
               quarantine={"effect_id": eid, "cleared": True}),
        "v13: plan writer: transition", "quarantine_reenable")
    pend = u()
    writer(
        cur, sid,
        plan_body([todo(pend, "qp", "advancement_task", "pending")], max_seq(cur, sid)))
    before = plan_n(cur, sid)
    writer_fail(
        cur, sid,
        delta(pend, "qp", "pending", "runnable",
              quarantine={"effect_id": u(), "cleared": False}),
        "v13: plan writer: transition", "quarantine_reenable")
    check("quarantine_reenable", plan_n(cur, sid) == before)
    writer(
        cur, sid,
        delta(pend, "qp", "pending", "pending",
              quarantine={"effect_id": u(), "cleared": False}))
    row = fold_row(cur, sid, pend)
    check(
        "quarantine_reenable",
        row["status"] == "pending" and row["quarantine"]["cleared"] is False,
        row)


def test_canonical(cur):
    sid, seq = seed_root(cur)
    spaced = " spaced"
    tid = u()
    body = plan_body([todo(tid, spaced, "advancement_task", "pending")], seq)
    _, out = writer(cur, sid, body)
    stored = q1(
        cur,
        "SELECT payload->'canonical'->'todos'->0->>'text' FROM events "
        "WHERE session_id=%s AND type='plan/committed' AND payload->>'plan_id'=%s",
        (sid, out["plan_id"]))
    check("canonical_hash_and_order", stored == spaced, stored)
    reordered = {
        "todos": body["todos"],
        "supersedes": None,
        "based_on_seq": seq,
        "call_kind": "plan_commit",
        "schema_version": 1,
    }
    before = plan_n(cur, sid)
    _, replayed = writer(cur, sid, reordered, apply=q1(
        cur,
        "SELECT payload->>'apply_id' FROM events "
        "WHERE session_id=%s AND type='plan/committed' AND payload->>'plan_id'=%s",
        (sid, out["plan_id"])))
    check("canonical_hash_and_order", replayed["replayed"] is True and plan_n(cur, sid) == before)

    a, b = u(), u()
    unordered = sorted([a, b], key=lambda item: uuid.UUID(item).bytes, reverse=True)
    writer_fail(
        cur, sid,
        plan_body(
            [
                todo(unordered[0], "z", "advancement_task", "pending"),
                todo(unordered[1], "y", "advancement_task", "pending"),
            ],
            max_seq(cur, sid)),
        "v13: plan writer: canonical", "canonical_hash_and_order")
    writer_fail(
        cur, sid,
        plan_body([todo(u(), "", "advancement_task", "pending")], max_seq(cur, sid)),
        "v13: plan writer: canonical", "canonical_hash_and_order")
    writer_fail(
        cur, sid,
        plan_body([todo(u(), "x" * 1025, "advancement_task", "pending")], max_seq(cur, sid)),
        "v13: plan writer: canonical", "canonical_hash_and_order")
    long_ok = plan_body([todo(u(), "x" * 1024, "advancement_task", "pending")], max_seq(cur, sid))
    writer(cur, sid, long_ok)
    missing = plan_body([todo(u(), "k", "advancement_task", "pending")], max_seq(cur, sid))
    del missing["supersedes"]
    writer_fail(cur, sid, missing, "v13: plan writer: canonical", "canonical_hash_and_order")
    writer_fail(
        cur, sid,
        plan_body([todo(u(), "bad due", "advancement_task", "pending", due="not-a-date")], max_seq(cur, sid)),
        "v13: plan writer: canonical", "canonical_hash_and_order")
    writer_fail(
        cur, sid,
        plan_body(
            [todo(u(), "no such", "advancement_task", "pending")],
            max_seq(cur, sid),
            supersedes=u()),
        "v13: plan writer: canonical", "canonical_hash_and_order")
    sql_id = str(q1(cur, "SELECT v13_plan_apply_id(%s)", ("bind:root:todo:effect",)))
    again = str(q1(cur, "SELECT v13_plan_apply_id(%s)", ("bind:root:todo:effect",)))
    parsed = uuid.UUID(sql_id)
    check(
        "canonical_hash_and_order",
        sql_id == apply_id("bind:root:todo:effect")
        and sql_id == again
        and parsed.version == 8
        and parsed.variant == uuid.RFC_4122,
        sql_id)
    fails_with(
        cur,
        "SELECT v13_append_event(%s, %s, 'plan/committed', %s::jsonb)",
        (sid, u(), json.dumps({"apply_id": u(), "extra": 1})),
        "v13: plan payload",
        "canonical_hash_and_order")
    before = plan_n(cur, sid)
    huge = plan_body(
        [todo(u(), "huge seq", "advancement_task", "pending")],
        10 ** 20)
    msg = fails_with(
        cur,
        "SELECT v13_plan_writer(%s::uuid, %s::uuid, %s::uuid, %s, %s::jsonb, %s::timestamptz)",
        (None, sid, u(), "plan_commit", json.dumps(huge), None),
        "v13: plan writer: canonical",
        "canonical_hash_and_order")
    check(
        "canonical_hash_and_order",
        plan_n(cur, sid) == before and "out of range" not in msg,
        msg)
    bad_sv = plan_body(
        [todo(u(), "float ver", "advancement_task", "pending")],
        max_seq(cur, sid))
    bad_sv["schema_version"] = 1.0
    writer_fail(cur, sid, bad_sv, "v13: plan writer: canonical", "canonical_hash_and_order")
    bad_delta = delta(tid, spaced, "pending", "runnable")
    bad_delta["schema_version"] = 1.0
    writer_fail(cur, sid, bad_delta, "v13: plan writer: canonical", "canonical_hash_and_order")
    check("canonical_hash_and_order", plan_n(cur, sid) == before)


def test_should_run(cur):
    sid, seq = seed_root(cur)
    cur.execute(
        "INSERT INTO effects (effect_id, session_id, kind, request, request_hash, origin_user_seq) "
        "VALUES (%s, %s, 'human', %s::jsonb, %s, %s)",
        (u(), sid, json.dumps({"reason": "need"}), sha("need"), seq))
    runnable = q1(cur, "SELECT v13_should_run(%s)", (sid,))
    ver = q1(cur, "SELECT version FROM v13_policies WHERE name='should_run' AND active")
    _, out = writer(
        cur, sid,
        plan_body([todo(u(), "despite gate", "advancement_task", "runnable")], seq))
    src = q1(
        cur,
        "SELECT pg_get_functiondef('public.v13_plan_writer(uuid,uuid,uuid,text,jsonb,timestamptz)'::regprocedure)")
    check(
        "writer_skips_should_run",
        runnable is False and ver == 3 and out["replayed"] is False
        and "v13_should_run" not in src
        and "v13_advance" not in src
        and "clock_timestamp" not in src
        and "now()" not in src,
        (runnable, ver))


def run(cur):
    test_prelude(cur)
    test_empty_and_version(cur)
    test_plan_commit(cur)
    test_replay_and_conflict(cur)
    test_stop_and_terminal(cur)
    test_auth_and_child(cur)
    test_waterline(cur)
    test_reuse(cur)
    test_transitions(cur)
    test_links(cur)
    test_quarantine(cur)
    test_canonical(cur)
    test_should_run(cur)
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
