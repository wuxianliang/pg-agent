"""P4 gate: v13 triage stage 20.

Run: uv run python v13/triage/test_triage.py  (exit 0 = pass)
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.triage.setup_db import DB, main as setup_db


def check(label, condition, detail=""):
    mark = "PASS" if condition else "FAIL"
    extra = f": {detail}" if detail and (not condition or len(str(detail)) < 200) else ""
    print(f"[{mark}] {label}{extra}")
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u():
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


def prefix(cur, sid, text="hello goal"):
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": text})))


def snap_of(cur, sid, remaining=0):
    cur.execute("SELECT v13_probe(%s)", (sid,))
    probe = cur.fetchone()[0]
    probe["sid"] = sid
    return {"snap": probe, "envelope": {"sid": sid}, "remaining": remaining,
            "failed": False, "abandon": False}


def advance(cur, sid, remaining=0):
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid, json.dumps(snap_of(cur, sid, remaining))))
    return cur.fetchone()[0]


def n_children(cur, sid):
    cur.execute("SELECT count(*) FROM sessions WHERE parent_session_id=%s", (sid,))
    return int(cur.fetchone()[0])


def human_reason(cur, sid):
    cur.execute(
        "SELECT request->>'reason' FROM effects WHERE session_id=%s AND kind='human' "
        "ORDER BY created_at DESC LIMIT 1", (sid,))
    row = cur.fetchone()
    return None if row is None else row[0]


def flip_policy(cur, name, version, value):
    cur.execute(
        "INSERT INTO v13_policies (name, version, value, active) VALUES (%s, %s, %s::jsonb, false)",
        (name, version, json.dumps(value)))
    cur.execute("UPDATE v13_policies SET active=false WHERE name=%s AND version<>%s", (name, version))
    cur.execute("UPDATE v13_policies SET active=true WHERE name=%s AND version=%s", (name, version))


def answer_triage(cur, sid, choice, confidence):
    cur.execute(
        "INSERT INTO decisions (session_id, signal, kind, question, criteria, context, "
        "answer, request_hash, status, answered_at) VALUES ("
        "%s, 'triage', 'choice', 'triage', %s::jsonb, '{}'::jsonb, %s::jsonb, %s, "
        "'answered', now())",
        (sid,
         json.dumps({"direct": "d", "decompose": "s", "human": "h"}),
         json.dumps({"choice": choice, "confidence": confidence,
                     "probabilities": {choice: confidence}}),
         u().replace("-", "") + u().replace("-", "")))


def main() -> int:
    setup_db()
    server = get_server()
    conn = connect(server)
    cur = conn.cursor()
    sql = (ROOT / "v13_triage.sql").read_text()
    code = "\n".join(l for l in sql.splitlines() if not l.lstrip().startswith("--"))

    cur.execute(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid='thresholds'::regclass AND pg_get_constraintdef(oid) LIKE '%action%'")
    cdef = cur.fetchone()[0]
    check("G-triage-action-closed: CHECK is pass|reject",
          "pass" in cdef and "reject" in cdef and "direct" not in cdef and "llm" not in cdef,
          cdef)
    cur.execute("SELECT count(*) FROM thresholds WHERE action NOT IN ('pass','reject')")
    check("G-triage-action-closed: no other action values", cur.fetchone()[0] == 0)
    check("G-triage-action-closed: no ALTER thresholds",
          "ALTER TABLE thresholds" not in code and "explore_then_retry" not in code)
    check("no set_config in stage sql", "set_config" not in code and "mock_response" not in code)
    check("closeout not replaced", "FUNCTION v13_closeout" not in code and "FUNCTION public.v13_closeout" not in code)
    cur.execute("SELECT pg_get_functiondef('v13_closeout(uuid,text,text,boolean)'::regprocedure)")
    check("triage_reject stays off closeout escape list",
          "triage_reject" not in cur.fetchone()[0])
    check("explore enqueue does not call spawn",
          "v13_spawn_subsession" not in code.split("v13_triage_enqueue_llm")[1].split("CREATE FUNCTION")[0])

    sid = open_session(cur)
    prefix(cur, sid, "   ")
    check("G-triage-10a empty fold terminal", advance(cur, sid) == "terminal")
    cur.execute(
        "SELECT status FROM sessions WHERE session_id=%s", (sid,))
    check("empty fold failed", cur.fetchone()[0] == "failed")
    cur.execute(
        "SELECT payload->>'turn_end_reason' FROM events WHERE session_id=%s AND type='session/failed'",
        (sid,))
    check("empty fold turn_end_reason", cur.fetchone()[0] == "triage_reject")
    check("empty fold zero children", n_children(cur, sid) == 0)

    sid = open_session(cur)
    prefix(cur, sid, "please mutate and delete the production database")
    cur.execute("SELECT v13_triage_project(%s)", (sid,))
    proj = cur.fetchone()[0]
    check("has_mutating_hint constant false", proj["has_mutating_hint"] is False)
    check("10b keys equal", proj["remaining_turns"] == proj["quota_remaining"] == proj["subtree_reserved"]
          or proj["remaining_turns"] == proj["quota_remaining"])
    check("subtree_reserved is occupancy", proj["subtree_reserved"] == 0)
    check("root depth 0", proj["ancestor_depth"] == 0)
    check("est tokens from goal bytes", proj["task_est_tokens"] > 0)
    check("no override", proj["user_intent_override"] is None)
    check("no explore hash", proj["explore_evidence_hash"] is None)
    cur.execute("SELECT v13_triage_decide(v13_triage_project(%s))", (sid,))
    check("G-triage-10a-null-tree live root is none", cur.fetchone()[0] == "none")
    null_proj = dict(proj)
    for k in ("ancestor_depth", "n_nonterminal_children", "remaining_turns",
              "quota_remaining", "subtree_reserved"):
        null_proj[k] = None
    null_proj["user_intent_override"] = None
    null_proj["fold_empty"] = False
    cur.execute("SELECT v13_triage_decide(%s::jsonb)", (json.dumps(null_proj),))
    check("G-triage-10a-null-tree null tree is not direct", cur.fetchone()[0] != "direct")
    null_proj["user_intent_override"] = "decompose"
    cur.execute("SELECT v13_triage_decide(%s::jsonb)", (json.dumps(null_proj),))
    check("G-triage-10a-null-tree null tree does not fire decompose", cur.fetchone()[0] != "decompose")

    cur.execute("SELECT v13_triage_steer(%s)", (sid,))
    check("root no jev evidence is human", cur.fetchone()[0] == "waiting")
    check("fail-closed reason", human_reason(cur, sid) == "triage_fail_closed")
    check("fail-closed zero children", n_children(cur, sid) == 0)

    sid = open_session(cur)
    prefix(cur, sid)
    cur.execute(
        "SELECT v13_submit_override(%s, %s::jsonb)",
        (sid, json.dumps({"schema_version": 1, "intent": "direct", "source_principal": "user"})))
    cur.execute(
        "SELECT payload FROM events WHERE session_id=%s AND type='goal/override'", (sid,))
    payload = cur.fetchone()[0]
    check("override reason default empty", payload["reason"] == "" and payload["intent"] == "direct")
    fails_with(cur, "SELECT v13_append_event(%s, %s, 'goal/override', %s::jsonb)",
               (sid, u(), json.dumps({"schema_version": 1, "intent": "direct",
                                      "source_principal": "user", "reason": ""})),
               "triage writer", "raw append goal/override rejected")
    cur.execute("SELECT v13_triage_after_route(%s, %s::jsonb)",
                (sid, json.dumps({"action": "sql", "tool": "spawn_subsession", "reason": "x"})))
    rewritten = cur.fetchone()[0]
    check("direct spawn rewrite", rewritten["action"] == "human" and rewritten["reason"] == "triage_direct")

    sid = open_session(cur)
    prefix(cur, sid, "split this")
    cur.execute("SELECT v13_fork(%s, 0, 'fresh_fork', NULL)", (sid,))
    before = n_children(cur, sid)
    flip_policy(cur, "spawn_budget", 2, {"max_nonterminal": 1, "max_depth": 4, "max_fanout": 8})
    cur.execute(
        "SELECT v13_submit_override(%s, %s::jsonb)",
        (sid, json.dumps({"schema_version": 1, "intent": "decompose",
                          "source_principal": "operator", "reason": "please split"})))
    check("override through budget is waiting", advance(cur, sid) == "waiting")
    check("override through budget zero new children", n_children(cur, sid) == before)
    check("override through budget human", human_reason(cur, sid) == "triage_hard_gate")
    flip_policy(cur, "spawn_budget", 3, {"max_nonterminal": 8, "max_depth": 4, "max_fanout": 8})

    sid = open_session(cur)
    prefix(cur, sid, "hold me")
    flip_policy(cur, "triage", 2, {"duty_cycle": 0})
    check("duty 0 waiting", advance(cur, sid) == "waiting")
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s AND type='triage/hold'", (sid,))
    check("one hold", cur.fetchone()[0] == 1)
    check("duty 0 second advance still waiting", advance(cur, sid) == "waiting")
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s AND type='triage/hold'", (sid,))
    check("hold not duplicated", cur.fetchone()[0] == 1)
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'repair/required', %s::jsonb, %s)",
        (sid, u(), json.dumps({"schema_version": 1}), u()))
    cur.execute("SELECT v13_recover_idle()")
    rec = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s AND type='recover/nudge'", (sid,))
    check("duty 0 hold blocks recover nudge", cur.fetchone()[0] == 0, rec)
    flip_policy(cur, "triage", 3, {"duty_cycle": 1})
    cur.execute("SELECT v13_recover_idle()")
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s AND type='recover/nudge'", (sid,))
    check("duty 1 recover nudges repair", cur.fetchone()[0] >= 1)

    sid = open_session(cur)
    prefix(cur, sid, "repair me")
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'repair/required', %s::jsonb, %s)",
        (sid, u(), json.dumps({"schema_version": 1}), u()))
    check("fold cap waiting", advance(cur, sid) == "waiting")
    cur.execute(
        "SELECT request FROM effects WHERE session_id=%s AND kind='human'", (sid,))
    req = cur.fetchone()[0]
    check("repair_cap request shape", req == {"reason": "repair_cap"}, req)
    check("repair_cap not session reject",
          advance(cur, sid) == "waiting")
    cur.execute("SELECT status FROM sessions WHERE session_id=%s", (sid,))
    check("repair_cap does not close session", cur.fetchone()[0] == "waiting")

    sid = open_session(cur)
    prefix(cur, sid, "evidence")
    cur.execute(
        "SELECT criteria FROM v13_needed_judgments(%s) WHERE signal='triage'", (sid,))
    qrow = cur.fetchone()
    check("root needed triage signal", qrow is not None)
    crit1 = qrow[0]
    cur.execute("SELECT v13_triage_note_explore(%s, %s::jsonb)", (sid, json.dumps({"text": "one"})))
    h1 = cur.fetchone()[0]
    cur.execute(
        "SELECT criteria->>'explore_evidence_hash' FROM v13_needed_judgments(%s) WHERE signal='triage'",
        (sid,))
    check("G-triage-evidence-hash projection follows event", cur.fetchone()[0] == h1)
    cur.execute("SELECT v13_triage_note_explore(%s, %s::jsonb)", (sid, json.dumps({"text": "two"})))
    h2 = cur.fetchone()[0]
    cur.execute(
        "SELECT criteria FROM v13_needed_judgments(%s) WHERE signal='triage'", (sid,))
    crit2 = cur.fetchone()[0]
    check("G-triage-evidence-hash criteria changes", crit1 != crit2 and h1 != h2)
    cur.execute(
        "SELECT v13_request_hash('triage','choice','q', %s::jsonb, '{}'::jsonb, NULL, NULL)",
        (json.dumps(crit1),))
    rh1 = cur.fetchone()[0]
    cur.execute(
        "SELECT v13_request_hash('triage','choice','q', %s::jsonb, '{}'::jsonb, NULL, NULL)",
        (json.dumps(crit2),))
    rh2 = cur.fetchone()[0]
    check("G-triage-evidence-hash new request_hash", rh1 != rh2)

    cur.execute(
        "INSERT INTO v13_route_policies (policy_name, policy_version, state) VALUES ('default', 2, 'draft')")
    cur.execute(
        "INSERT INTO thresholds (policy_name, policy_version, signal, band_no, lo, hi, action) VALUES "
        "('default', 2, 'triage', 1, 0, 0.4, 'reject'),"
        "('default', 2, 'triage', 2, 0.8, 1.01, 'pass')")
    cur.execute(
        "UPDATE v13_route_policies SET state='frozen' WHERE policy_name='default' AND policy_version=2")
    sid = open_session(cur, {"version": 2})
    prefix(cur, sid, "review this goal")
    answer_triage(cur, sid, "direct", 0.5)
    kids = n_children(cur, sid)
    cur.execute("SELECT v13_triage_steer(%s)", (sid,))
    check("first review explore waits", cur.fetchone()[0] == "waiting")
    check("G-triage-explore-depth zero children", n_children(cur, sid) == kids)
    cur.execute(
        "SELECT request->'route'->>'reason' FROM effects WHERE session_id=%s AND kind='llm'", (sid,))
    check("explore route reason", cur.fetchone()[0] == "explore")
    cur.execute(
        "SELECT effect_id FROM effects WHERE session_id=%s AND kind='llm'", (sid,))
    eid = cur.fetchone()[0]
    cur.execute(
        "UPDATE effects SET status='claimed', attempt_no=1, fence=1, lease_owner='w', "
        "lease_until=clock_timestamp()+interval '1 hour' WHERE effect_id=%s RETURNING attempt_no, fence",
        (eid,))
    attempt, fence = cur.fetchone()
    cur.execute(
        "SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
        (eid, attempt, fence, json.dumps({
            "text": "notes",
            "tool_calls": [{"id": "c1", "name": "spawn_subsession", "args": {"task": "child work"}}]})))
    fails_with(cur, "SELECT v13_advance(%s, %s::jsonb)",
               (sid, json.dumps(snap_of(cur, sid))),
               "explore spawn", "G-triage-explore-depth explore tool_calls do not spawn")
    check("explore spawn zero children", n_children(cur, sid) == kids)

    sid = open_session(cur, {"version": 2})
    prefix(cur, sid, "review again")
    answer_triage(cur, sid, "decompose", 0.55)
    cur.execute("SELECT v13_triage_note_explore(%s, %s::jsonb)", (sid, json.dumps({"text": "already"})))
    cur.execute("SELECT v13_triage_steer(%s)", (sid,))
    check("explored review is human", cur.fetchone()[0] == "waiting")
    check("explored review reason", human_reason(cur, sid) == "triage_review")
    check("explored review zero children", n_children(cur, sid) == 0)

    w = connect_as(server, "v13_worker")
    wc = w.cursor()
    fails_with(wc, "SELECT v13_submit_override(%s, %s::jsonb)",
               (sid, json.dumps({"schema_version": 1, "intent": "direct", "source_principal": "user"})),
               "permission denied", "worker cannot submit override")
    fails_with(wc, "SELECT v13_append_event(%s, %s, 'goal/override', '{}'::jsonb)",
               (sid, u()), "permission denied", "worker has no append_event")
    w.close()

    cur.execute("SELECT count(*) FROM v13_needed_judgments(%s) WHERE signal='triage'", (sid,))
    check("override-free root asks triage", cur.fetchone()[0] == 1)
    cur.execute(
        "SELECT v13_submit_override(%s, %s::jsonb)",
        (sid, json.dumps({"schema_version": 1, "intent": "direct", "source_principal": "user", "reason": "x"})))
    cur.execute("SELECT count(*) FROM v13_needed_judgments(%s) WHERE signal='triage'", (sid,))
    check("override skips jev signal", cur.fetchone()[0] == 0)

    conn.rollback()
    conn.close()
    print("[done] triage")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("[fail]", exc)
        raise SystemExit(1)
