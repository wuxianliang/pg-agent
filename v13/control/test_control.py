"""P1 gate: v13 control plane stage 17.

Run: uv run python v13/control/test_control.py  (exit 0 = pass)
"""
from __future__ import annotations

import json
import sys
import threading
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.control.setup_db import DB, main as setup_db

HEX64 = "ab" * 32


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


def configure(cur):
    cur.execute("SELECT set_config('typesafe.provider', 'mock', false)")
    cur.execute("SELECT set_config('typesafe.model', 'jev-mock', false)")


def new_session(cur):
    sid = u()
    cur.execute("INSERT INTO sessions (session_id) VALUES (%s)", (sid,))
    return sid


def append_user(cur, sid, text="hello"):
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": text})))


def freshen(cur, sid):
    cur.execute(
        "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
        "WHERE session_id=%s", (sid,))


def refresh(cur, sid, snap):
    cur.execute("SELECT v13_probe(%s)", (sid,))
    probe = cur.fetchone()[0]
    out = json.loads(json.dumps(snap))
    out["snap"].update(probe)
    out["snap"]["sid"] = sid
    return out


def snap_of(cur, sid):
    cur.execute("SELECT v13_probe(%s)", (sid,))
    probe = cur.fetchone()[0]
    probe["sid"] = sid
    return {"snap": probe, "envelope": {"sid": sid}, "remaining": 0,
            "failed": False, "abandon": False}


def parse(cur, sid):
    cur.execute("SELECT signal, kind, criteria FROM v13_needed_judgments(%s)", (sid,))
    answers = {}
    for signal, kind, criteria in cur.fetchall():
        if signal == "intent":
            answers[signal] = {"type": "choice", "choice": "tool_action",
                               "probabilities": {"tool_action": 0.9}, "confidence": 0.9}
        elif signal == "tool":
            answers[signal] = {"type": "choice", "choice": "harness_turn",
                               "probabilities": {"harness_turn": 0.9}, "confidence": 0.9}
        elif signal == "gate_action":
            answers[signal] = {"type": "noul", "noul": 0.9}
        elif signal == "gate_off_topic":
            answers[signal] = {"type": "noul", "noul": 0.1}
        elif signal == "risk":
            answers[signal] = {"type": "score", "score": 0.5, "confidence": 0.9}
        elif kind == "choice":
            keys = list(criteria.keys()) if isinstance(criteria, dict) else ["none"]
            ch = keys[0]
            answers[signal] = {"type": "choice", "choice": ch,
                               "probabilities": {ch: 0.9}, "confidence": 0.9}
        elif kind == "score":
            answers[signal] = {"type": "score", "score": 0.5, "confidence": 0.9}
        else:
            answers[signal] = {"type": "noul", "noul": 0.1}
    mock = json.dumps({"model": "jev-mock", "answers": answers,
                       "usage": {"input_tokens": 1, "output_tokens": 1}})
    cur.execute("SELECT set_config('typesafe.mock_response', %s, true)", (mock,))
    cur.execute("SELECT v13_parse(%s)", (sid,))
    return cur.fetchone()[0]


def advance(cur, sid, snap):
    freshen(cur, sid)
    snap = refresh(cur, sid, snap)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid, json.dumps(snap)))
    return cur.fetchone()[0], snap


def tool_at(cur, sid, index=None):
    sql = ("SELECT effect_id, status, attempt_no, fence, request FROM effects "
           "WHERE session_id=%s AND kind='tool'")
    params = [sid]
    if index is not None:
        sql += " AND (request->>'continuation_index')::int = %s"
        params.append(index)
    sql += " ORDER BY effect_id DESC LIMIT 1"
    cur.execute(sql, params)
    return cur.fetchone()


def settle(cur, eid, result, status="succeeded"):
    cur.execute(
        "UPDATE effects SET status='claimed', attempt_no=attempt_no+1, fence=fence+1, "
        "lease_owner='w', lease_until=clock_timestamp()+interval '1 hour' "
        "WHERE effect_id=%s RETURNING attempt_no, fence", (eid,))
    attempt, fence = cur.fetchone()
    cur.execute(
        "SELECT v13_complete(%s, %s, %s, %s, %s::jsonb)",
        (eid, attempt, fence, status, json.dumps(result)))
    return cur.fetchone()[0], attempt, fence


def count_type(cur, sid, typ):
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s AND type=%s", (sid, typ))
    return cur.fetchone()[0]


def open_harness(server):
    conn = connect(server)
    cur = conn.cursor()
    configure(cur)
    sid = new_session(cur)
    append_user(cur, sid)
    snap = parse(cur, sid)
    word, snap = advance(cur, sid, snap)
    row = tool_at(cur, sid, 0)
    if word != "waiting" or row is None:
        raise AssertionError(f"open_harness {word} {row}")
    return conn, cur, sid, snap, row


def main() -> int:
    setup_db()
    server = get_server()
    conn = connect(server)
    cur = conn.cursor()
    cur.execute("SELECT extversion FROM pg_extension WHERE extname='pg_jsonschema'")
    check("pg_jsonschema extension", cur.fetchone()[0] == "0.3.4")
    cur.execute("SELECT kind, handler, enabled FROM tools WHERE name='harness_turn'")
    check("harness_turn seed", cur.fetchone() == ("tool", "worker:harness_turn", True))
    cur.execute(
        "SELECT value->>'dialect' FROM v13_policies WHERE name='harness_result_schema' AND active")
    check("harness_result_schema dialect", cur.fetchone()[0] == "draft-07")
    fails_with(cur, "SELECT v13_enqueue_effect(%s, 'tool', %s::jsonb, 'harness_turn')",
               (u(), json.dumps({"tool": "harness_turn", "params": {}})),
               "logical_turn_id required", "G-ctx10-logical-turn direct enqueue missing pair")
    fails_with(cur, "SELECT v13_enqueue_effect(%s, 'tool', %s::jsonb, 'send_summary_email')",
               (u(), json.dumps({"tool": "send_summary_email", "params": {},
                                 "logical_turn_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"})),
               "logical_turn_id required", "G-ctx10-logical-turn ordinary tool logical key")
    fails_with(cur, "SELECT v13_enqueue_effect(%s, 'judge', %s::jsonb)",
               (u(), json.dumps({"logical_turn_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"})),
               "logical_turn_id required", "G-ctx10-logical-turn judge logical key")
    conn.commit()
    conn.close()

    hconn, hcur, sid, snap, row = open_harness(server)
    req = row[4]
    check("G-ctx10-logical-turn first waiting", row[1] == "ready")
    check("G-ctx10-logical-turn six keys",
          sorted(req) == ["continuation_index", "handler", "logical_turn_id",
                          "params", "tool", "tools_revision"])
    check("G-ctx10-logical-turn idx0", req["continuation_index"] == 0)
    check("G-ctx10-logical-turn uuid",
          len(req["logical_turn_id"]) == 36 and req["logical_turn_id"] == req["logical_turn_id"].lower())
    n_route = count_type(hcur, sid, "turn/route")
    word, snap = advance(hcur, sid, snap)
    hcur.execute("SELECT count(*) FROM effects WHERE session_id=%s", (sid,))
    check("G-ctx10-logical-turn ready second advance waiting",
          word == "waiting" and hcur.fetchone()[0] == 1, word)
    check("G-ctx10-logical-turn ready second advance zero new route",
          count_type(hcur, sid, "turn/route") == n_route)
    settle(hcur, row[0], {"result_kind": "progress", "signals": ["repair/required"]})
    check("G-ctx10-spend progress+signal zero before consume",
          count_type(hcur, sid, "turn/material_spent") == 0)
    word, snap = advance(hcur, sid, snap)
    row2 = tool_at(hcur, sid, 1)
    check("G-ctx10-logical-turn continuation waiting", word == "waiting", word)
    check("G-ctx10-logical-turn continuation index+1",
          row2 is not None and row2[4]["logical_turn_id"] == req["logical_turn_id"], row2)
    hcur.execute(
        "SELECT payload->>'reason' FROM events WHERE session_id=%s AND type='turn/route' "
        "ORDER BY seq DESC LIMIT 1", (sid,))
    check("G-ctx10-logical-turn harness_continuation", hcur.fetchone()[0] == "harness_continuation")
    check("G-ctx10-spend +signal zero receipt", count_type(hcur, sid, "turn/material_spent") == 0)
    check("wait-lexicon progress+signal no extra human",
          count_type(hcur, sid, "human/responded") == 0)
    hconn.commit()
    hconn.close()

    hconn, hcur, sid, snap, row = open_harness(server)
    settle(hcur, row[0], {"result_kind": "finish", "delivery_kind": "LOUD-BUT-BLIND"})
    word, _ = advance(hcur, sid, snap)
    check("G-ctx10-delivery blind delivery still closeout", word == "terminal", word)
    check("G-ctx10-spend finish counts 1", count_type(hcur, sid, "turn/material_spent") == 1)
    hcur.execute("SELECT status FROM sessions WHERE session_id=%s", (sid,))
    check("G-ctx10-delivery finish completed", hcur.fetchone()[0] == "completed")
    hcur.execute("SELECT payload FROM events WHERE session_id=%s AND type='session/completed'", (sid,))
    seal = hcur.fetchone()[0]
    hcur.execute("SELECT v13_state_hash(%s)", (sid,))
    check("G-closeout state_hash recomputed", hcur.fetchone()[0] == seal["state_hash"])
    hcur.execute("SELECT v13_closeout(%s, 'completed', 'harness_finish', false)", (sid,))
    check("G-closeout-unknown-authority replay payload", hcur.fetchone()[0] == seal)
    hcur.execute("SELECT count(*) FROM events WHERE session_id=%s AND type='session/completed'", (sid,))
    check("G-closeout-unknown-authority replay no second seal", hcur.fetchone()[0] == 1)
    hconn.commit()
    hconn.close()

    hconn, hcur, sid, snap, row = open_harness(server)
    ltid = row[4]["logical_turn_id"]
    settle(hcur, row[0], {"result_kind": "progress", "partial": True,
                          "harness_session_ref": "sess/1", "resume_token": "tok"})
    word, _ = advance(hcur, sid, snap)
    hcur.execute(
        "SELECT status, request FROM effects WHERE session_id=%s AND kind='tool' "
        "AND request->>'logical_turn_id' IS DISTINCT FROM %s", (sid, ltid))
    nxt = hcur.fetchone()
    check("G-ctx10-spend progress no signal counts 1",
          count_type(hcur, sid, "turn/material_spent") == 1)
    check("G-ctx10-logical-turn material new uuid",
          word == "waiting" and nxt is not None and nxt[1]["continuation_index"] == 0, word)
    check("G-ctx10-delivery annotation keys do not block effect", nxt[0] == "ready")
    hconn.commit()
    hconn.close()

    hconn, hcur, sid, snap, row = open_harness(server)
    out, attempt, fence = settle(hcur, row[0], {"result_kind": "progress"}, status="failed")
    word, _ = advance(hcur, sid, snap)
    hcur.execute(
        "SELECT fence, attempt_no, request->>'logical_turn_id', "
        "(request->>'continuation_index')::int FROM effects WHERE effect_id=%s", (row[0],))
    retried = hcur.fetchone()
    check("G-ctx10-logical-turn failed retry same id",
          word == "waiting" and retried[0] == fence + 1 and retried[1] == attempt
          and retried[2] == row[4]["logical_turn_id"] and retried[3] == 0, retried)
    hconn.commit()
    hconn.close()

    hconn, hcur, sid, snap, row = open_harness(server)
    settle(hcur, row[0], {"result_kind": "wait", "wait_reason": "evidence",
                          "wake": {"kind": "not_before", "at": "2099-01-01T00:00:00Z"}})
    word, _ = advance(hcur, sid, snap)
    hcur.execute("SELECT count(*) FROM effects WHERE session_id=%s", (sid,))
    check("wake not_before future waiting zero new effect",
          word == "waiting" and hcur.fetchone()[0] == 1, word)
    check("G-ctx10-wake no satisfied yet", count_type(hcur, sid, "wake/satisfied") == 0)
    hcur.execute("SELECT status FROM sessions WHERE session_id=%s", (sid,))
    check("wait-lexicon evidence status waiting", hcur.fetchone()[0] == "waiting")
    hconn.commit()
    hconn.close()

    hconn, hcur, sid, snap, row = open_harness(server)
    settle(hcur, row[0], {"result_kind": "wait", "wait_reason": "quota",
                          "wake": {"kind": "not_before", "at": "2020-01-01T00:00:00Z"}})
    word, snap = advance(hcur, sid, snap)
    check("G-ctx10-wake not_before past continues",
          word == "waiting" and tool_at(hcur, sid, 1) is not None, word)
    check("G-ctx10-wake one satisfied", count_type(hcur, sid, "wake/satisfied") == 1)
    word, _ = advance(hcur, sid, snap)
    check("G-ctx10-wake repeat advance no second satisfied",
          word == "waiting" and count_type(hcur, sid, "wake/satisfied") == 1, word)
    hconn.commit()
    hconn.close()

    hconn, hcur, sid, snap, row = open_harness(server)
    settle(hcur, row[0], {"result_kind": "wait", "wait_reason": "evidence",
                          "wake": {"kind": "event", "event_type": "demo/ping"}})
    word, snap = advance(hcur, sid, snap)
    check("G-ctx10-wake event before batch tail waiting",
          word == "waiting" and count_type(hcur, sid, "wake/satisfied") == 0)
    hcur.execute("SELECT v13_append_event(%s, %s, 'demo/ping', '{}'::jsonb)", (sid, u()))
    word, _ = advance(hcur, sid, snap)
    check("G-ctx10-wake event after batch tail continues",
          word == "waiting" and count_type(hcur, sid, "wake/satisfied") == 1, word)
    hconn.commit()
    hconn.close()

    hconn, hcur, sid, snap, row = open_harness(server)
    settle(hcur, row[0], {"result_kind": "progress"})
    hcur.execute(
        "INSERT INTO artifacts (content_hash, kind, size, produced_by) VALUES (%s, 'note', 1, %s)",
        (HEX64, row[0]))
    hconn.commit()
    hconn.close()
    hconn, hcur, sid, snap, row = open_harness(server)
    settle(hcur, row[0], {"result_kind": "wait", "wait_reason": "evidence",
                          "wake": {"kind": "artifact", "content_hash": HEX64}})
    word, _ = advance(hcur, sid, snap)
    check("G-ctx10-wake artifact global hit continues",
          word == "waiting" and count_type(hcur, sid, "wake/satisfied") == 1, word)
    hconn.commit()
    hconn.close()

    hconn, hcur, sid, snap, row = open_harness(server)
    eid = row[0]
    hcur.execute("UPDATE effects SET status='claimed', attempt_no=1, fence=1 WHERE effect_id=%s", (eid,))
    fails_with(hcur, "SELECT v13_complete(%s, 1, 1, 'succeeded', %s::jsonb)",
               (eid, json.dumps({
                   "result_kind": "wait", "wait_reason": "evidence",
                   "wake": {"kind": "children_terminal",
                            "child_session_ids": ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]}})),
               "children_terminal requires stage 18", "G-ctx10-wake children_terminal P1 reject")
    fails_with(hcur, "SELECT v13_complete(%s, 1, 1, 'succeeded', %s::jsonb)",
               (eid, json.dumps({"result_kind": "progress", "interaction_kind": "material_cap"})),
               "harness_result schema", "G-ctx10-delivery interaction_kind rejected")
    fails_with(hcur, "SELECT v13_complete(%s, 1, 1, 'succeeded', %s::jsonb)",
               (eid, json.dumps({"result_kind": "wait", "wait_reason": "approval",
                                 "interaction_id": "ix",
                                 "wake": {"kind": "event", "event_type": "x"}})),
               "harness_result schema", "G-ctx10-wake approval with wake rejected")
    fails_with(hcur, "SELECT v13_complete(%s, 1, 1, 'succeeded', %s::jsonb)",
               (eid, json.dumps({"result_kind": "progress", "delivery_kind": "USER_ACTION_REQUIRED"})),
               "harness_result schema", "G-ctx10-delivery USER_ACTION matrix")
    hcur.execute("SELECT v13_complete(%s, 0, 0, 'succeeded', %s::jsonb)",
                 (eid, json.dumps({"result_kind": "progress"})))
    check("G-ctx10-wake stale before schema", hcur.fetchone()[0] == "stale")
    hconn.commit()
    hconn.close()

    hconn, hcur, sid, snap, row = open_harness(server)
    settle(hcur, row[0], {"result_kind": "wait", "wait_reason": "approval",
                          "interaction_id": "ix-approval-1",
                          "delivery_kind": "USER_ACTION_REQUIRED"})
    word, snap = advance(hcur, sid, snap)
    hcur.execute("SELECT request FROM effects WHERE session_id=%s AND kind='human'", (sid,))
    href = hcur.fetchone()[0]
    check("wait-lexicon approval exactly one human",
          word == "waiting" and href == {"schema_version": 1, "interaction_ref": "ix-approval-1"}, href)
    hcur.execute("SELECT status FROM sessions WHERE session_id=%s", (sid,))
    check("approval status has no approval word", hcur.fetchone()[0] in ("ready", "waiting"))
    word, _ = advance(hcur, sid, snap)
    hcur.execute("SELECT count(*) FROM effects WHERE session_id=%s AND kind='human'", (sid,))
    check("wait-lexicon second advance still one human", word == "waiting" and hcur.fetchone()[0] == 1)
    hcur.execute("SELECT effect_id FROM effects WHERE session_id=%s AND kind='human'", (sid,))
    hid = hcur.fetchone()[0]
    hcur.execute("UPDATE effects SET status='claimed', attempt_no=1, fence=1 WHERE effect_id=%s", (hid,))
    hcur.execute("SELECT v13_complete(%s, 1, 0, 'succeeded', %s::jsonb)",
                 (hid, json.dumps({"schema_version": 1, "interaction_ref": "ix-approval-1", "response": "yes"})))
    check("G-ctx10-approval-ref fence stale", hcur.fetchone()[0] == "stale")
    fails_with(hcur, "SELECT v13_complete(%s, 1, 1, 'succeeded', %s::jsonb)",
               (hid, json.dumps({"schema_version": 1, "interaction_ref": "nope", "response": "yes"})),
               "current=", "G-ctx10-approval-ref mismatch current=")
    for payload, needle in (
        ({"schema_version": 1, "interaction_ref": "ix-approval-1", "response": ""}, "illegal"),
        ({"schema_version": 1, "interaction_ref": "ix-approval-1", "response": {}}, "illegal"),
        ({"schema_version": 1, "interaction_ref": "ix-approval-1", "answers": {}}, "illegal"),
        ({"schema_version": 1, "interaction_ref": "ix-approval-1", "skip": "yes"}, "illegal"),
        ({"schema_version": 1, "interaction_ref": "ix-approval-1", "response": "a", "answers": {"x": 1}}, "one-of"),
        ({"schema_version": 1, "interaction_ref": "ix-approval-1", "note": "x", "response": "a"}, "unknown"),
        ({"schema_version": 1, "interaction_ref": "ix-approval-1", "skip": False}, "one-of"),
    ):
        fails_with(hcur, "SELECT v13_complete(%s, 1, 1, 'succeeded', %s::jsonb)",
                   (hid, json.dumps(payload)), needle, f"G-ctx10-approval-payload {needle}")
    out, attempt, fence = settle(hcur, hid, {
        "schema_version": 1, "interaction_ref": "ix-approval-1", "response": False, "skip": False})
    check("G-ctx10-approval-payload false is legal", out == "accepted", out)
    hcur.execute("SELECT payload FROM events WHERE source_effect_id=%s AND type='human/responded'", (hid,))
    hp = hcur.fetchone()[0]
    check("G-ctx10-approval-payload unused null",
          hp["response"] is False and hp["answers"] is None and hp["skip"] is None, hp)
    hcur.execute("SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
                 (hid, attempt, fence, json.dumps({"not": "a channel"})))
    check("G-ctx10-approval-ref replay does not leak channel error", hcur.fetchone()[0] == "replay")
    fails_with(hcur, "SELECT v13_enqueue_effect(%s, 'human', %s::jsonb)",
               (sid, json.dumps({"schema_version": 1, "interaction_ref": "ix-approval-1", "extra": 1})),
               "ux_effects_human_interaction_ref", "G-ctx10-approval-ref exhausted ref re-enqueue")
    hconn.commit()
    hconn.close()

    conn = connect(server)
    cur = conn.cursor()
    sid = new_session(cur)
    append_user(cur, sid)
    cur.execute("SELECT v13_enqueue_effect(%s, 'human', %s::jsonb)",
                (sid, json.dumps({"reason": "budget_exhausted"})))
    rid = cur.fetchone()[0]
    cur.execute("UPDATE effects SET status='claimed', attempt_no=1, fence=1 WHERE effect_id=%s", (rid,))
    cur.execute("SELECT v13_complete(%s, 1, 1, 'succeeded', %s::jsonb)",
                (rid, json.dumps({"reason": "ok"})))
    check("C4 reason human still succeeded", cur.fetchone()[0] == "accepted")
    check("C4 reason human zero human/responded", count_type(cur, sid, "human/responded") == 0)

    sid = new_session(cur)
    append_user(cur, sid)
    cur.execute("SELECT v13_enqueue_effect(%s, 'tool', %s::jsonb, 'send_summary_email')",
                (sid, json.dumps({"tool": "send_summary_email", "params": {},
                                  "handler": "worker:send_summary_email", "tools_revision": 1})))
    wid = cur.fetchone()[0]
    cur.execute("UPDATE effects SET status='claimed', attempt_no=1, fence=1 WHERE effect_id=%s", (wid,))
    cur.execute("SELECT v13_complete(%s, 1, 1, 'unknown', %s::jsonb)", (wid, json.dumps({"x": 1})))
    check("G-wall-session-status complete unknown accepted", cur.fetchone()[0] == "accepted")
    cur.execute("SELECT status FROM sessions WHERE session_id=%s", (sid,))
    check("G-wall-session-status blocked_unknown", cur.fetchone()[0] == "blocked_unknown")
    word, _ = advance(cur, sid, snap_of(cur, sid))
    cur.execute("SELECT status FROM sessions WHERE session_id=%s", (sid,))
    check("G-wall-session-status advance does not unwall",
          word == "waiting" and cur.fetchone()[0] == "blocked_unknown", word)
    cur.execute("SELECT v13_cancel(%s)", (sid,))
    check("G-cancel-does-not-unwall accepted", cur.fetchone()[0] == "accepted")
    cur.execute("SELECT status FROM sessions WHERE session_id=%s", (sid,))
    check("G-cancel-does-not-unwall status", cur.fetchone()[0] == "blocked_unknown")
    cur.execute("SELECT status FROM effects WHERE effect_id=%s", (wid,))
    check("G-cancel-does-not-unwall unknown untouched", cur.fetchone()[0] == "unknown")
    fails_with(cur, "SELECT v13_closeout(%s, 'cancelled', 'cancel', false)", (sid,),
               "closeout precondition", "G-closeout-unknown-authority unknown blocks seal")
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s AND type LIKE %s", (sid, "session/%"))
    check("G-closeout-unknown-authority zero seal", cur.fetchone()[0] == 0)
    append_user(cur, sid, "again")
    cur.execute("SELECT status FROM sessions WHERE session_id=%s", (sid,))
    check("G-user-message-keeps-wall", cur.fetchone()[0] == "blocked_unknown")
    cur.execute("UPDATE effects SET result=%s::jsonb WHERE effect_id=%s",
                (json.dumps({"x": 1}), wid))
    cur.execute("SELECT encode(digest(result::text, 'sha256'), 'hex') FROM effects WHERE effect_id=%s", (wid,))
    ph = cur.fetchone()[0]
    cur.execute("SELECT v13_resolve_unknown(%s, 'confirmed', %s::jsonb)",
                (wid, json.dumps({"observation": "committed", "payload_hash": ph})))
    check("G-resolve-clears-overlay confirmed", cur.fetchone()[0] == "accepted")
    cur.execute("SELECT status FROM sessions WHERE session_id=%s", (sid,))
    check("G-resolve-clears-overlay ready", cur.fetchone()[0] == "ready")

    sid = new_session(cur)
    append_user(cur, sid)
    cur.execute("SELECT v13_enqueue_effect(%s, 'tool', %s::jsonb, 'send_summary_email')",
                (sid, json.dumps({"tool": "send_summary_email", "params": {},
                                  "handler": "worker:x", "tools_revision": 1})))
    hid2 = cur.fetchone()[0]
    cur.execute("UPDATE effects SET status='claimed', attempt_no=1, fence=1 WHERE effect_id=%s", (hid2,))
    cur.execute("SELECT v13_complete(%s, 1, 1, 'unknown', '{}'::jsonb)", (hid2,))
    cur.fetchone()
    cur.execute("SELECT v13_enqueue_effect(%s, 'human', %s::jsonb)",
                (sid, json.dumps({"reason": "hold"})))
    cur.execute("SELECT v13_resolve_unknown(%s, 'not_happened', %s::jsonb)",
                (hid2, json.dumps({"observation": "absent"})))
    check("G-resolve-clears-overlay human exception accepted", cur.fetchone()[0] == "accepted")
    cur.execute("SELECT status FROM sessions WHERE session_id=%s", (sid,))
    check("G-resolve-clears-overlay human exception waiting", cur.fetchone()[0] == "waiting")
    cur.execute("SELECT v13_complete(%s, 1, 1, 'succeeded', '{}'::jsonb)", (hid2,))
    check("G-resolve G4 complete replay", cur.fetchone()[0] == "replay")
    cur.execute("SELECT v13_renew_lease(%s, 1, 1000)", (hid2,))
    check("G-resolve G4 renew false", cur.fetchone()[0] is False)

    parent = new_session(cur)
    child = u()
    cur.execute(
        "INSERT INTO sessions (session_id, parent_session_id) VALUES (%s, %s)",
        (child, parent))
    append_user(cur, parent)
    fails_with(cur, "SELECT v13_closeout(%s, 'cancelled', 'cancel', false)", (parent,),
               "closeout children require stage 18", "G-wall-no-parent-write")
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s AND type LIKE %s", (parent, "session/%"))
    check("G-wall-no-parent-write zero parent seal", cur.fetchone()[0] == 0)

    sid = new_session(cur)
    append_user(cur, sid)
    cur.execute("SELECT v13_enqueue_effect(%s, 'tool', %s::jsonb, 'send_summary_email')",
                (sid, json.dumps({"tool": "send_summary_email", "params": {},
                                  "handler": "worker:x", "tools_revision": 1})))
    stid = cur.fetchone()[0]
    cur.execute("UPDATE effects SET status='claimed', attempt_no=1, fence=1 WHERE effect_id=%s", (stid,))
    old = snap_of(cur, sid)
    cur.execute("SELECT request, request_hash, status, fence, attempt_no FROM effects WHERE effect_id=%s", (stid,))
    frozen = cur.fetchone()
    cur.execute("SELECT v13_append_event(%s, %s, 'steer/injected', %s::jsonb)",
                (sid, u(), json.dumps({"schema_version": 1})))
    cur.execute("SELECT request, request_hash, status, fence, attempt_no FROM effects WHERE effect_id=%s", (stid,))
    check("G-steer-frozen-request unchanged", frozen == cur.fetchone())
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid, json.dumps(old)))
    check("G-steer-frozen-request old envelope stale", cur.fetchone()[0] == "stale")
    cur.execute("SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
                (stid, frozen[4], frozen[3], json.dumps({"ok": True})))
    check("G-steer-frozen-request original token accepted", cur.fetchone()[0] == "accepted")

    sid = new_session(cur)
    append_user(cur, sid)
    cur.execute("SELECT v13_enqueue_effect(%s, 'judge', %s::jsonb)",
                (sid, json.dumps({"envelope": {"probe": 1}})))
    qid = cur.fetchone()[0]
    cur.execute(
        "UPDATE effects SET status='claimed', attempt_no=1, fence=1, lease_owner='w', "
        "lease_until=clock_timestamp()-interval '1 minute' WHERE effect_id=%s", (qid,))
    cur.execute("SELECT v13_cancel(%s)", (sid,))
    check("G-cancel-requeue cancel accepted", cur.fetchone()[0] == "accepted")
    cur.execute("SELECT v13_requeue_stale()")
    rq = cur.fetchone()[0]
    cur.execute("SELECT status FROM effects WHERE effect_id=%s", (qid,))
    check("G-cancel-requeue judge cancelled not ready", cur.fetchone()[0] == "cancelled", rq)
    check("G-cancel-requeue keys stable",
          set(rq) == {"reclaimed_ready", "walled_unknown", "lease_exhausted", "woken_ready", "walls_total"})

    sid = new_session(cur)
    append_user(cur, sid)
    cur.execute("SELECT v13_enqueue_effect(%s, 'tool', %s::jsonb, 'send_summary_email')",
                (sid, json.dumps({"tool": "send_summary_email", "params": {},
                                  "handler": "worker:send_summary_email", "tools_revision": 1})))
    mid = cur.fetchone()[0]
    cur.execute("UPDATE effects SET status='claimed', attempt_no=1, fence=1 WHERE effect_id=%s", (mid,))
    cur.execute("SELECT v13_complete(%s, 1, 1, 'succeeded', %s::jsonb)",
                (mid, json.dumps({"result_kind": "finish"})))
    check("send_summary_email result_kind accepted", cur.fetchone()[0] == "accepted")
    cur.execute("SELECT status FROM sessions WHERE session_id=%s", (sid,))
    check("send_summary_email result_kind does not closeout", cur.fetchone()[0] == "ready")
    conn.commit()
    conn.close()

    c2 = connect(server)
    b = c2.cursor()
    bsid = new_session(b)
    b.execute("SELECT v13_enqueue_effect(%s, 'human', %s::jsonb)",
              (bsid, json.dumps({"reason": "bijection"})))
    beid = b.fetchone()[0]
    b.execute("UPDATE effects SET status='unknown' WHERE effect_id=%s", (beid,))
    try:
        c2.commit()
        check("bijection COMMIT single-sided fails", False, "commit succeeded")
    except psycopg2.Error as exc:
        check("bijection COMMIT single-sided fails", "unknown wall bijection" in str(exc),
              str(exc).splitlines()[0])
        c2.rollback()
    b = c2.cursor()
    bsid = new_session(b)
    b.execute("SELECT v13_enqueue_effect(%s, 'human', %s::jsonb)",
              (bsid, json.dumps({"reason": "bijection-ok"})))
    beid = b.fetchone()[0]
    b.execute("UPDATE effects SET status='unknown' WHERE effect_id=%s", (beid,))
    b.execute("UPDATE sessions SET status='blocked_unknown' WHERE session_id=%s", (bsid,))
    c2.commit()
    check("bijection COMMIT paired succeeds", True)
    b = c2.cursor()
    b.execute("UPDATE sessions SET status='completed' WHERE session_id=%s", (bsid,))
    c2.commit()
    check("bijection COMMIT terminal residual succeeds", True)
    b = c2.cursor()
    wsid = new_session(b)
    b.execute("SELECT v13_enqueue_effect(%s, 'human', %s::jsonb)",
              (wsid, json.dumps({"reason": "wall-empty"})))
    weid = b.fetchone()[0]
    b.execute("UPDATE effects SET status='unknown' WHERE effect_id=%s", (weid,))
    b.execute("UPDATE sessions SET status='blocked_unknown' WHERE session_id=%s", (wsid,))
    c2.commit()
    b = c2.cursor()
    b.execute("UPDATE effects SET status='succeeded' WHERE effect_id=%s", (weid,))
    try:
        c2.commit()
        check("bijection COMMIT wall without unknown fails", False)
    except psycopg2.Error as exc:
        check("bijection COMMIT wall without unknown fails", "unknown wall bijection" in str(exc))
        c2.rollback()
    c2.close()

    rc = connect(server)
    rc.autocommit = True
    rcur = rc.cursor()
    rcur.execute("SET ROLE v13_recall")
    rcur.execute("SELECT count(*) FROM events WHERE type='human/responded'")
    check("SET ROLE v13_recall reads human/responded", rcur.fetchone()[0] >= 1)
    try:
        rcur.execute("SELECT count(*) FROM effects")
        check("SET ROLE v13_recall cannot SELECT effects", False)
    except psycopg2.Error as exc:
        check("SET ROLE v13_recall cannot SELECT effects", "permission" in str(exc).lower(),
              str(exc).splitlines()[0])
    rcur.execute("RESET ROLE")
    rc.close()

    box = {"held": False}
    lconn = connect(server)
    lc = lconn.cursor()
    box["sid"] = new_session(lc)
    lc.execute("SELECT v13_enqueue_effect(%s, 'judge', %s::jsonb)",
               (box["sid"], json.dumps({"envelope": {"lock": 1}})))
    lid = lc.fetchone()[0]
    lc.execute(
        "UPDATE effects SET status='claimed', attempt_no=1, fence=1, "
        "lease_until=clock_timestamp()-interval '1 minute' WHERE effect_id=%s", (lid,))
    lconn.commit()

    def hold():
        h = connect(server)
        hc = h.cursor()
        hc.execute("SELECT 1 FROM sessions WHERE session_id=%s FOR UPDATE", (box["sid"],))
        box["held"] = True
        threading.Event().wait(0.4)
        h.commit()
        h.close()

    t = threading.Thread(target=hold)
    t.start()
    while not box["held"]:
        threading.Event().wait(0.01)
    lc.execute("SELECT v13_requeue_stale()")
    lc.fetchone()
    lc.execute("SELECT v13_renew_lease(%s, 1, 1000)", (lid,))
    lc.fetchone()
    t.join(timeout=5)
    check("lock order complete/requeue/renew no deadlock", not t.is_alive())
    lconn.rollback()
    lconn.close()
    print("[PASS] stage 17 gates")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[FAIL] {exc}")
        raise SystemExit(1)
