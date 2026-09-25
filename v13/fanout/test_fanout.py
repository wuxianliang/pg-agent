"""P3 gate: v13 fanout stage 19.

Run: uv run python v13/fanout/test_fanout.py  (exit 0 = pass)
"""
from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.fanout.setup_db import DB, main as setup_db


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    extra = f": {detail}" if detail and (not condition or len(str(detail)) < 180) else ""
    print(f"[{mark}] {label}{extra}")
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u() -> str:
    return str(uuid.uuid4())


def fails_with(cur, sql, params, needle, label):
    cur.execute("SAVEPOINT sp")
    try:
        cur.execute(sql, params)
    except psycopg2.Error as exc:
        msg = str(exc)
        check(label, needle.lower() in msg.lower(), msg.splitlines()[0])
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        return
    cur.execute("ROLLBACK TO SAVEPOINT sp")
    raise AssertionError(f"{label}: expected failure")


def connect(server):
    conn = psycopg2.connect(server.get_uri(DB))
    conn.autocommit = False
    return conn


def connect_as(server, user):
    uri = server.get_uri(DB)
    host = (parse_qs(urlparse(uri).query).get("host") or [None])[0]
    return psycopg2.connect(host=host, dbname=DB, user=user)


def open_session(cur, spec=None):
    cur.execute("SELECT v13_open_session(%s::jsonb)", (json.dumps(spec or {}),))
    return str(cur.fetchone()[0])


def prefix(cur, sid, text="hello"):
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": text})))


def snap_of(cur, sid):
    cur.execute("SELECT v13_probe(%s)", (sid,))
    probe = cur.fetchone()[0]
    probe["sid"] = sid
    return {"snap": probe, "envelope": {"sid": sid}, "remaining": 0,
            "failed": False, "abandon": False}


def advance(cur, sid):
    cur.execute(
        "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
        "WHERE session_id=%s", (sid,))
    snap = snap_of(cur, sid)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid, json.dumps(snap)))
    return cur.fetchone()[0]


def claim_row(cur, sid, kind, request, tool_name):
    cur.execute(
        "SELECT v13_enqueue_effect(%s, %s, %s::jsonb, %s)",
        (sid, kind, json.dumps(request), tool_name))
    eid = str(cur.fetchone()[0])
    cur.execute(
        "UPDATE effects SET status='claimed', attempt_no=1, fence=1, lease_owner='w', "
        "lease_until=clock_timestamp()+interval '1 hour' "
        "WHERE effect_id=%s RETURNING attempt_no, fence", (eid,))
    attempt, fence = cur.fetchone()
    return eid, attempt, fence


def complete(cur, eid, attempt, fence, status, result=None):
    cur.execute(
        "SELECT v13_complete(%s, %s, %s, %s, %s::jsonb)",
        (eid, attempt, fence, status, None if result is None else json.dumps(result)))
    return cur.fetchone()[0]


def trev(cur, sid):
    cur.execute("SELECT (v13_probe(%s)->>'tools_revision')::bigint", (sid,))
    return int(cur.fetchone()[0])


def wt_request(tool, bid, revision):
    return {
        "tool": tool,
        "params": {"binding_artifact_id": bid},
        "handler": "worker:" + tool,
        "tools_revision": revision,
    }


def inline_result():
    return {"schema_version": 1, "root_path": "/tmp/wt", "base_ref": "main"}


def event_count(cur, sid, etype):
    cur.execute(
        "SELECT count(*) FROM events WHERE session_id=%s AND type=%s", (sid, etype))
    return cur.fetchone()[0]


def effect_status(cur, eid):
    cur.execute("SELECT status, error FROM effects WHERE effect_id=%s", (eid,))
    return cur.fetchone()


def session_status(cur, sid):
    cur.execute("SELECT status FROM sessions WHERE session_id=%s", (sid,))
    return cur.fetchone()[0]


def spawn_tree(cur, n=2):
    sid = open_session(cur)
    prefix(cur, sid)
    children = [{"tool_call_id": f"c{i}", "task": f"task {i}"} for i in range(n)]
    cur.execute(
        "SELECT v13_spawn_subsession(%s, %s::jsonb)",
        (sid, json.dumps({"schema_version": 1, "children": children})))
    cur.fetchone()
    return sid


def main() -> int:
    sql = (ROOT / "v13_fanout.sql").read_text()
    check("source has no pg_terminate_backend", "pg_terminate_backend" not in sql)
    check("source has no LISTEN", "LISTEN" not in sql)
    setup_db()
    server = get_server()
    conn = connect(server)
    cur = conn.cursor()

    cur.execute(
        "SELECT name, kind, handler FROM tools WHERE name LIKE 'worktree_%' ORDER BY name")
    rows = cur.fetchall()
    check("worktree catalog three tool rows",
          rows == [
              ("worktree_merge", "tool", "worker:worktree_merge"),
              ("worktree_prepare", "tool", "worker:worktree_prepare"),
              ("worktree_release", "tool", "worker:worktree_release"),
          ], rows)
    cur.execute(
        "SELECT v13_interruptible('fanout_required'), v13_interruptible('fanout_best_effort'), "
        "v13_interruptible('worktree_prepare'), v13_interruptible('send_summary_email'), "
        "v13_interruptible(NULL)")
    check("interruptible closed set default unsupported",
          cur.fetchone() == ("required", "best_effort", "unsupported", "unsupported", "unsupported"))
    cur.execute(
        "SELECT v13_requires_worktree('worktree_prepare'), v13_requires_worktree('worktree_merge'), "
        "v13_requires_worktree('worktree_release'), v13_requires_worktree('send_summary_email')")
    check("requires_worktree only merge and release", cur.fetchone() == (False, True, True, False))
    cur.execute(
        "SELECT has_function_privilege('v13_worker', 'v13_latch_fire(uuid,text,jsonb)', 'EXECUTE'), "
        "has_table_privilege('v13_worker', 'latches', 'INSERT')")
    check("worker cannot write latch", cur.fetchone() == (False, False))

    sid = open_session(cur)
    prefix(cur, sid)
    cur.execute("SELECT v13_cancel(%s)", (sid,))
    check("P1 no-child cancel accepted", cur.fetchone()[0] == "accepted")
    check("P1 one cancel event", event_count(cur, sid, "cancel/requested") == 1)
    cur.execute(
        "SELECT v13_json_keys(payload) FROM events WHERE session_id=%s AND type='cancel/requested'",
        (sid,))
    check("cancel payload keys unchanged", cur.fetchone()[0] == ["schema_version", "scope"])
    cur.execute("SELECT v13_cancel_pending(%s), v13_unconsumed_cancel(%s)", (sid, sid))
    check("cancel_pending copies unconsumed predicate", cur.fetchone() == (True, True))
    cur.execute("SELECT v13_cancel(%s)", (sid,))
    check("second cancel still accepted and not duplicated",
          cur.fetchone()[0] == "accepted" and event_count(cur, sid, "cancel/requested") == 1)
    conn.rollback()

    root = spawn_tree(cur, 2)
    cur.execute(
        "SELECT session_id FROM sessions WHERE parent_session_id=%s ORDER BY session_id",
        (root,))
    kids = [str(row[0]) for row in cur.fetchall()]
    cur.execute("UPDATE sessions SET status='completed' WHERE session_id=%s", (kids[0],))
    cur.execute(
        "CREATE TEMP TABLE fanout_order (n serial, session_id uuid) ON COMMIT DROP")
    cur.execute(
        "CREATE OR REPLACE FUNCTION v13_fanout_order_probe() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN "
        "IF NEW.type = 'cancel/requested' THEN "
        "INSERT INTO fanout_order (session_id) VALUES (NEW.session_id); END IF; "
        "RETURN NEW; END $$")
    cur.execute(
        "CREATE TRIGGER trg_fanout_order AFTER INSERT ON events "
        "FOR EACH ROW EXECUTE FUNCTION v13_fanout_order_probe()")
    cur.execute("SELECT v13_cancel(%s)", (root,))
    check("fanout accepted", cur.fetchone()[0] == "accepted")
    cur.execute(
        "WITH RECURSIVE tree AS ("
        " SELECT session_id, 0 AS depth, status FROM sessions WHERE session_id=%s"
        " UNION ALL SELECT s.session_id, t.depth+1, s.status FROM sessions s"
        " JOIN tree t ON s.parent_session_id=t.session_id)"
        " SELECT session_id::text FROM tree"
        " WHERE status NOT IN ('completed','failed','cancelled')"
        " ORDER BY depth, session_id", (root,))
    expected = [row[0] for row in cur.fetchall()]
    cur.execute("SELECT session_id::text FROM fanout_order ORDER BY n")
    order = [row[0] for row in cur.fetchall()]
    check("application order depth then session_id", order == expected, (order, expected))
    check("terminal descendant zero events", event_count(cur, kids[0], "cancel/requested") == 0)
    check("live child got one event", event_count(cur, kids[1], "cancel/requested") == 1)
    cur.execute("DROP TRIGGER trg_fanout_order ON events")
    conn.rollback()

    root = spawn_tree(cur, 2)
    conn.commit()
    cur.execute(
        "SELECT session_id FROM sessions WHERE session_id=%s OR parent_session_id=%s "
        "ORDER BY session_id LIMIT 1", (root, root))
    smallest = cur.fetchone()[0]
    hold = connect(server)
    hcur = hold.cursor()
    hcur.execute("SELECT session_id FROM sessions WHERE session_id=%s FOR UPDATE", (smallest,))
    box = {"out": None, "err": None}

    def _cancel():
        c = connect(server)
        k = c.cursor()
        try:
            k.execute("SET statement_timeout = '8000'")
            k.execute("SELECT v13_cancel(%s)", (root,))
            box["out"] = k.fetchone()[0]
            c.commit()
        except psycopg2.Error as exc:
            box["err"] = str(exc).splitlines()[0]
            c.rollback()
        c.close()

    thread = threading.Thread(target=_cancel)
    thread.start()
    waiting = False
    for _ in range(30):
        time.sleep(0.1)
        cur.execute(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE query LIKE 'SELECT v13_cancel%%' AND state = 'active' "
            "AND wait_event_type = 'Lock'")
        if cur.fetchone()[0] >= 1:
            waiting = True
            break
    check("lock order waits on smallest session_id", waiting, box)
    hold.rollback()
    hold.close()
    thread.join(timeout=8)
    check("cancel finishes after lock released", box["out"] == "accepted" and box["err"] is None, box)
    conn.rollback()

    c1, c2 = connect(server), connect(server)
    k1, k2 = c1.cursor(), c2.cursor()
    sid = open_session(k1)
    prefix(k1, sid)
    k1.execute(
        "SELECT v13_spawn_subsession(%s, %s::jsonb)",
        (sid, json.dumps({"schema_version": 1, "children": [
            {"tool_call_id": "a", "task": "one"},
            {"tool_call_id": "b", "task": "two"}]})))
    k1.fetchone()
    c1.commit()
    done = {"ok": 0, "err": []}

    def _both(conn_i):
        try:
            conn_i.cursor().execute("SELECT v13_cancel(%s)", (sid,))
            conn_i.commit()
            done["ok"] += 1
        except psycopg2.Error as exc:
            done["err"].append(str(exc).splitlines()[0])
            conn_i.rollback()

    threads = [threading.Thread(target=_both, args=(c,)) for c in (c1, c2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=8)
    cur.execute(
        "SELECT count(*) FROM events e JOIN sessions s ON s.session_id = e.session_id "
        "WHERE e.type = 'cancel/requested' AND (s.session_id = %s OR s.parent_session_id = %s)",
        (sid, sid))
    n_ev = cur.fetchone()[0]
    check("concurrent cancel no deadlock and one event each",
          done["ok"] == 2 and n_ev == 3 and not done["err"], {"events": n_ev, **done})
    c1.close()
    c2.close()
    conn.rollback()

    sid = open_session(cur)
    prefix(cur, sid)
    eid, attempt, fence = claim_row(cur, sid, "llm", {"text": "x"}, "fanout_required")
    cur.execute("SELECT v13_renew_lease(%s, %s, 60000)", (eid, fence))
    renewed = cur.fetchone()[0]
    cur.execute("SELECT v13_cancel_pending(%s)", (sid,))
    check("fake fourth duty polls after renew", renewed is True and cur.fetchone()[0] is False)
    cur.execute("SELECT v13_cancel(%s)", (sid,))
    cur.fetchone()
    cur.execute("SELECT v13_renew_lease(%s, %s, 60000)", (eid, fence))
    cur.fetchone()
    cur.execute("SELECT v13_cancel_pending(%s)", (sid,))
    check("poll sees pending cancel", cur.fetchone()[0] is True)
    check("cancelled fence mismatch is stale",
          complete(cur, eid, attempt, fence + 1, "cancelled", {"text": "no"}) == "stale")
    check("stale cancelled leaves claimed", effect_status(cur, eid)[0] == "claimed")
    out = complete(cur, eid, attempt, fence, "cancelled", {"text": "hidden", "tool_calls": []})
    check("required llm settles cancelled", out == "accepted")
    st, err = effect_status(cur, eid)
    check("cancelled error NULL", st == "cancelled" and err is None, (st, err))
    check("cancelled writes effect_done not llm/message",
          event_count(cur, sid, "effect_done") == 1 and event_count(cur, sid, "llm/message") == 0)
    check("cancelled does not raise wall", session_status(cur, sid) != "blocked_unknown")
    check("replay cancelled", complete(cur, eid, attempt, fence, "cancelled") == "replay")
    conn.rollback()

    sid = open_session(cur)
    prefix(cur, sid)
    eid, attempt, fence = claim_row(cur, sid, "tool", {"x": 1}, "fanout_required")
    cur.execute("SELECT v13_cancel(%s)", (sid,))
    cur.fetchone()
    fails_with(cur, "SELECT v13_complete(%s, %s, %s, 'cancelled', NULL)",
               (eid, attempt, fence), "mutating interrupt settles unknown",
               "required tool cancelled rejected")
    st, _err = effect_status(cur, eid)
    check("rejected cancelled leaves claimed", st == "claimed", st)
    check("rejected cancelled does not raise wall", session_status(cur, sid) != "blocked_unknown")
    out = complete(cur, eid, attempt, fence, "unknown")
    check("mutating interrupt settles unknown", out == "accepted" and effect_status(cur, eid)[0] == "unknown")
    check("unknown raises wall", session_status(cur, sid) == "blocked_unknown")
    cur.execute("SELECT v13_cancel(%s)", (sid,))
    cur.fetchone()
    check("cancel does not rewrite unknown", effect_status(cur, eid)[0] == "unknown")
    check("cancel does not clear wall", session_status(cur, sid) == "blocked_unknown")
    conn.rollback()

    sid = open_session(cur)
    prefix(cur, sid)
    eid, attempt, fence = claim_row(cur, sid, "tool", {"x": 1}, "send_summary_email")
    cur.execute("SELECT v13_cancel(%s)", (sid,))
    cur.fetchone()
    fails_with(cur, "SELECT v13_complete(%s, %s, %s, 'cancelled', NULL)",
               (eid, attempt, fence), "interruptible unsupported",
               "unsupported cancelled rejected")
    out = complete(cur, eid, attempt, fence, "succeeded", {"ok": True})
    check("unsupported runs to completion", out == "accepted")
    check("unsupported result kept", event_count(cur, sid, "tool/result") == 1)
    turned = advance(cur, sid)
    check("unsupported sticky absorb", turned == "terminal" and session_status(cur, sid) == "cancelled", turned)
    conn.rollback()

    sid = open_session(cur)
    prefix(cur, sid)
    eid, attempt, fence = claim_row(cur, sid, "tool", {"x": 1}, "fanout_best_effort")
    fails_with(cur, "SELECT v13_complete(%s, %s, %s, 'cancelled', NULL)",
               (eid, attempt, fence), "cancel not pending",
               "best_effort cancelled without pending")
    cur.execute("SELECT v13_cancel(%s)", (sid,))
    cur.fetchone()
    check("best_effort cancelled", complete(cur, eid, attempt, fence, "cancelled") == "accepted")
    check("best_effort cancelled skips tool/result", event_count(cur, sid, "tool/result") == 0)
    conn.rollback()

    sid = open_session(cur)
    prefix(cur, sid)
    eid, attempt, fence = claim_row(cur, sid, "tool", {"x": 1}, "fanout_best_effort")
    cur.execute("SELECT v13_cancel(%s)", (sid,))
    cur.fetchone()
    check("best_effort failed", complete(cur, eid, attempt, fence, "failed", {"ok": False}) == "accepted")
    conn.rollback()
    sid = open_session(cur)
    prefix(cur, sid)
    eid, attempt, fence = claim_row(cur, sid, "tool", {"x": 1}, "fanout_best_effort")
    check("best_effort succeeded", complete(cur, eid, attempt, fence, "succeeded", {"ok": True}) == "accepted")
    eid, attempt, fence = claim_row(cur, sid, "tool", {"x": 1}, "fanout_best_effort")
    check("best_effort unknown", complete(cur, eid, attempt, fence, "unknown") == "accepted")
    check("best_effort unknown raises wall", session_status(cur, sid) == "blocked_unknown")
    conn.rollback()

    sid = open_session(cur)
    rev = trev(cur, sid)
    bid = u()
    req = wt_request("worktree_merge", bid, rev)
    cur.execute(
        "SELECT v13_enqueue_effect(%s, 'tool', %s::jsonb, 'worktree_merge')",
        (sid, json.dumps(req)))
    merge_id = cur.fetchone()[0]
    cur.execute("SELECT v13_claim('wt')")
    check("claim skips merge without latch", cur.fetchone()[0] is None)
    cur.execute("SELECT status FROM effects WHERE effect_id=%s", (merge_id,))
    check("skipped merge stays ready", cur.fetchone()[0] == "ready")
    cur.execute("UPDATE effects SET status='cancelled' WHERE effect_id=%s", (merge_id,))
    pre = wt_request("worktree_prepare", bid, rev)
    eid, attempt, fence = claim_row(cur, sid, "tool", pre, "worktree_prepare")
    check("prepare complete", complete(cur, eid, attempt, fence, "succeeded", inline_result()) == "accepted")
    check("prepare advance binds", advance(cur, sid) in ("waiting", "progressed", "terminal"))
    cur.execute("SELECT value FROM latches WHERE session_id=%s AND name='worktree'", (sid,))
    latch = cur.fetchone()[0]
    check("worktree latch prepared",
          latch["state"] == "prepared" and latch["binding_artifact_id"] == bid
          and latch["schema_version"] == 1, latch)
    cur.execute(
        "SELECT kind, inline FROM artifacts WHERE artifact_id=%s", (bid,))
    kind, body = cur.fetchone()
    check("binding artifact inline",
          kind == "worktree_binding" and body["root_path"] == "/tmp/wt" and body["base_ref"] == "main")
    cur.execute(
        "UPDATE effects SET status='cancelled' WHERE session_id=%s AND status='ready'", (sid,))
    cur.execute(
        "SELECT v13_enqueue_effect(%s, 'tool', %s::jsonb, 'worktree_merge')",
        (sid, json.dumps(req)))
    merge_id = cur.fetchone()[0]
    cur.execute("SELECT v13_claim('wt')")
    claimed = cur.fetchone()[0]
    check("merge claimable once latched",
          claimed is not None and str(claimed["effect_id"]) == str(merge_id), claimed)
    conn.rollback()

    sid = open_session(cur)
    cur.execute("SELECT v13_latch_digest(%s)", (sid,))
    bare = cur.fetchone()[0]
    cur.execute(
        "SELECT v13_latch_fire(%s, 'cache', %s::jsonb)",
        (sid, json.dumps({"schema_version": 1})))
    cur.fetchone()
    cur.execute("SELECT v13_latch_digest(%s)", (sid,))
    before = cur.fetchone()[0]
    cur.execute(
        "SELECT v13_latch_fire(%s, 'worktree', %s::jsonb)",
        (sid, json.dumps({
            "schema_version": 1, "binding_artifact_id": u(), "state": "released"})))
    cur.fetchone()
    cur.execute("SELECT v13_latch_digest(%s)", (sid,))
    after = cur.fetchone()[0]
    check("digest excludes worktree byte-identically", before == after and before != bare, (before, after, bare))
    fails_with(
        cur, "SELECT v13_latch_fire(%s, 'worktree', %s::jsonb)",
        (u(), json.dumps({"schema_version": 1, "binding_artifact_id": u(), "state": "nope"})),
        "worktree latch", "bad latch state rejected")
    conn.rollback()

    sid = open_session(cur)
    prefix(cur, sid, "fork me about worktree")
    cur.execute(
        "SELECT v13_latch_fire(%s, 'cache', %s::jsonb)",
        (sid, json.dumps({"schema_version": 1, "k": "v"})))
    cur.fetchone()
    cur.execute(
        "SELECT v13_latch_fire(%s, 'worktree', %s::jsonb)",
        (sid, json.dumps({
            "schema_version": 1, "binding_artifact_id": u(), "state": "prepared"})))
    cur.fetchone()
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid,))
    man = cur.fetchone()[0]
    goal = man["required_revision"]["goal"]
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'turn/route', %s::jsonb)",
        (sid, u(), json.dumps({"action": "refresh"})))
    cur.execute(
        "SELECT v13_enqueue_effect(%s, 'context_refresh', %s::jsonb)",
        (sid, json.dumps({"goal_hash": goal})))
    reid = cur.fetchone()[0]
    cur.execute(
        "UPDATE effects SET status='claimed', attempt_no=1, fence=1, lease_owner='w', "
        "lease_until=clock_timestamp()+interval '1 hour' WHERE effect_id=%s "
        "RETURNING attempt_no, fence", (reid,))
    attempt, fence = cur.fetchone()
    cur.execute("SELECT v13_refresh_context(%s, %s, %s)", (reid, attempt, fence))
    cur.fetchone()
    cur.execute("SELECT context_active_artifact FROM sessions WHERE session_id=%s", (sid,))
    art = cur.fetchone()[0]
    cur.execute("SELECT inline FROM artifacts WHERE artifact_id=%s", (art,))
    cut = cur.fetchone()[0]["required_revision"]["sem"]
    cur.execute("SELECT v13_fork(%s, %s, 'exact_replay')", (sid, cut))
    child = str(cur.fetchone()[0])
    cur.execute(
        "SELECT name FROM latches WHERE session_id=%s ORDER BY name", (child,))
    names = [row[0] for row in cur.fetchall()]
    check("non-fresh fork skips worktree latch", "worktree" not in names and "cache" in names, names)
    conn.rollback()
    conn.close()
    print("[done] fanout")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[FAIL] {exc}")
        raise SystemExit(1)
