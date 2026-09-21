"""DP3 gate: manifest skeleton, freshness, three epochs.

Run: uv run python v13/manifest/test_manifest.py  (exit 0 = pass)
"""
from __future__ import annotations

import json
import re
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
V13 = AGENT_ROOT / "v13"
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.manifest.setup_db import DB, main as setup_db
from v13.load import files_through, SQL_LOAD_ORDER

ENV19 = {
    "sid", "ctx", "needed", "candidate_set_hash", "goal_hash",
    "provider", "model", "route_policy_name", "route_policy_version",
    "tools_revision", "tools_catalog", "candidate_generation_revision",
    "session_version", "max_event_seq", "needed_count",
    "templates", "groups", "timeout_ms", "budget",
}
TOP10 = {
    "judgments", "manifest_version", "policy", "prefix_identity",
    "query_side", "replay", "required_revision", "sections",
    "session_id", "turn_no",
}
SEC9 = {
    "cache_scope", "churn", "content_hash", "est_tokens", "kind",
    "payload_ref", "priority", "section_id", "transform",
}
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    extra = f": {detail}" if detail and (not condition or len(str(detail)) < 160) else ""
    print(f"[{mark}] {label}{extra}")
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u() -> str:
    return str(uuid.uuid4())


def fails_with(cur, sql, params, needle, label, pgcode=None):
    cur.execute("SAVEPOINT sp")
    try:
        cur.execute(sql, params)
    except psycopg2.Error as exc:
        if pgcode:
            ok = exc.pgcode == pgcode
        else:
            ok = needle.lower() in str(exc).lower()
        check(label, ok, str(exc).splitlines()[0])
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        return exc
    cur.execute("ROLLBACK TO SAVEPOINT sp")
    raise AssertionError(f"{label}: expected failure containing {needle!r}")


def connect_as(server, user):
    uri = server.get_uri(DB)
    host = (parse_qs(urlparse(uri).query).get("host") or [None])[0]
    return psycopg2.connect(host=host, dbname=DB, user=user)


def guc(cur):
    cur.execute("SET search_path TO public, pg_catalog")
    cur.execute("SELECT set_config('typesafe.provider', 'mock', false)")
    cur.execute("SELECT set_config('typesafe.model', 'jev-mock', false)")


def recycle(server, conn):
    try:
        conn.commit()
    except Exception:
        conn.rollback()
    conn.close()
    c = psycopg2.connect(server.get_uri(DB))
    c.autocommit = False
    k = c.cursor()
    guc(k)
    return c, k


def new_session(cur, sid=None):
    sid = sid or u()
    cur.execute("INSERT INTO sessions (session_id) VALUES (%s)", (sid,))
    return sid


def append_user(cur, sid, text="hello"):
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": text})),
    )
    return cur.fetchone()[0]


def set_mock(cur, mock: str) -> None:
    cur.execute("SELECT set_config('typesafe.mock_response', %s, true)", (mock,))


def poison(cur) -> None:
    cur.execute("SELECT set_config('typesafe.mock_response', NULL, true)")
    cur.execute("SELECT set_config('typesafe.endpoint', 'http://127.0.0.1:1/', true)")
    cur.execute("SELECT set_config('typesafe.api_key', 'probe', true)")
    cur.execute("SELECT set_config('typesafe.timeout_ms', '200', true)")


def claim_pinned(cur, eid, worker="w1", lease_ms=60000):
    cur.execute(
        "UPDATE effects SET status='cancelled' "
        "WHERE status='ready' AND effect_id IS DISTINCT FROM %s",
        (eid,))
    cur.execute("SELECT v13_claim(%s, %s)", (worker, lease_ms))
    row = cur.fetchone()[0]
    check("claim pinned",
          row is not None and str(row["effect_id"]) == str(eid), row)
    return row


def mock_from_needed(cur, sid, **over) -> str:
    cur.execute(
        "SELECT signal, kind, criteria FROM v13_needed_judgments(%s)", (sid,))
    answers = {}
    for signal, kind, criteria in cur.fetchall():
        if signal in over:
            answers[signal] = over[signal]
            continue
        if kind == "choice":
            keys = list(criteria.keys()) if isinstance(criteria, dict) else ["none"]
            ch = keys[0]
            answers[signal] = {
                "type": "choice", "choice": ch,
                "probabilities": {ch: 0.9}, "confidence": 0.9,
            }
        elif kind == "score":
            answers[signal] = {"type": "score", "score": 0.5, "confidence": 0.9}
        else:
            answers[signal] = {"type": "noul", "noul": 0.1}
    answers.update(over)
    return json.dumps({"model": "jev-mock", "answers": answers,
                       "usage": {"input_tokens": 1, "output_tokens": 1}})


def parse(cur, sid, **over):
    guc(cur)
    set_mock(cur, mock_from_needed(cur, sid, **over))
    cur.execute("SELECT v13_parse(%s)", (sid,))
    return cur.fetchone()[0]


def answers_sql(cur, sid):
    return parse(
        cur, sid,
        intent={"type": "choice", "choice": "sql_answer",
                "probabilities": {"sql_answer": 0.9}, "confidence": 0.9},
        gate_action={"type": "noul", "noul": 0.9},
        gate_off_topic={"type": "noul", "noul": 0.1},
        risk={"type": "score", "score": 0.5, "confidence": 0.9},
        tool={"type": "choice", "choice": "session_stats",
              "probabilities": {"session_stats": 0.9}, "confidence": 0.9})


def answers_llm(cur, sid):
    return parse(
        cur, sid,
        intent={"type": "choice", "choice": "llm_generate",
                "probabilities": {"llm_generate": 0.9}, "confidence": 0.9},
        gate_action={"type": "noul", "noul": 0.1},
        gate_off_topic={"type": "noul", "noul": 0.1},
        risk={"type": "score", "score": 0.5, "confidence": 0.9})


def next_policy_version(cur, name: str) -> int:
    cur.execute(
        "SELECT coalesce(max(version),0)+1 FROM v13_policies WHERE name=%s",
        (name,))
    return cur.fetchone()[0]


def bump_policy(cur, name: str, value: dict) -> int:
    ver = next_policy_version(cur, name)
    cur.execute(
        "INSERT INTO v13_policies (name, version, value, active) "
        "VALUES (%s,%s,%s::jsonb,false)",
        (name, ver, json.dumps(value)))
    cur.execute(
        "UPDATE v13_policies SET active=false WHERE name=%s AND active",
        (name,))
    cur.execute(
        "UPDATE v13_policies SET active=true WHERE name=%s AND version=%s",
        (name, ver))
    return ver


def seed_asm():
    return {
        "budget_tokens": 8192, "est_bytes_per_token": 4,
        "priority_overrides": {}, "kinds_disabled": [],
        "inline_max_bytes": 1048576, "blob_retention": "referenced-forever",
    }


def restore_asm(cur):
    bump_policy(cur, "assemble_manifest", seed_asm())


def sec_map(m):
    return {s["section_id"]: s for s in m["sections"]}


def sha_empty(cur):
    cur.execute("SELECT encode(digest(''::text, 'sha256'), 'hex')")
    return cur.fetchone()[0]


def hang_refresh(cur, sid, snap=None):
    if snap is None:
        snap = answers_sql(cur, sid)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid, json.dumps(snap)))
    a = cur.fetchone()[0]
    cur.execute(
        "SELECT effect_id FROM effects WHERE session_id=%s "
        "AND kind='context_refresh' AND status='ready'", (sid,))
    row = cur.fetchone()
    return a, (row[0] if row else None), snap


def settle(cur, eid):
    ck = claim_pinned(cur, eid)
    cur.execute(
        "SELECT v13_refresh_context(%s, %s, %s)",
        (eid, ck["attempt_no"], ck["fence"]))
    return cur.fetchone()[0], ck


def parse_settle(server, conn, cur, sid, **over):
    snap = parse(cur, sid, **over) if over else answers_sql(cur, sid)
    a, eid, snap = hang_refresh(cur, sid, snap)
    if eid is None:
        cur.execute("SELECT v13_goal_hash(%s)", (sid,))
        gh = cur.fetchone()[0]
        cur.execute(
            "SELECT v13_enqueue_effect(%s, 'context_refresh', %s::jsonb)",
            (sid, json.dumps({"goal_hash": gh, "nonce": u()})))
        eid = cur.fetchone()[0]
        cur.execute("SELECT status FROM effects WHERE effect_id=%s", (eid,))
        st = cur.fetchone()[0]
        check("nonce refresh ready", st == "ready", st)
    else:
        check("refresh hung waiting", a == "waiting", a)
    out, ck = settle(cur, eid)
    check("settle accepted", out == "accepted", out)
    conn, cur = recycle(server, conn)
    return snap, eid, out, conn, cur


def wait_lock(watch, pid, timeout=8.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        watch.execute(
            "SELECT wait_event_type, wait_event FROM pg_stat_activity "
            "WHERE pid=%s", (pid,))
        row = watch.fetchone()
        if row and row[0] == "Lock":
            return True
        time.sleep(0.02)
    return False


def wait_box_lock(watch, box, key="pid", timeout=8.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        pid = box.get(key)
        if pid:
            if wait_lock(watch, pid, timeout=0.12):
                return True
            watch.execute(
                "SELECT bool_or(NOT granted) FROM pg_locks WHERE pid=%s",
                (pid,))
            row = watch.fetchone()
            if row and row[0]:
                return True
        time.sleep(0.02)
    return False


def minus_replay(m):
    body = json.loads(json.dumps(m))
    body.pop("replay", None)
    return body


def insert_complete_decision(cur, sid, signal="late"):
    h = uuid.uuid4().hex + uuid.uuid4().hex
    cur.execute(
        "INSERT INTO decisions (session_id, signal, kind, question, context, "
        " request_hash, status, answer) "
        "VALUES (%s, %s, 'noul', %s, '{}'::jsonb, %s, 'answered', "
        " %s::jsonb) RETURNING decision_id",
        (sid, signal, f"{signal} complete decision question.", h,
         json.dumps({"type": "noul", "noul": 0.1})))
    return cur.fetchone()[0]


CANON_PAUSE_SQL = r"""
CREATE OR REPLACE FUNCTION v13_canonical_state(p_sid uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE v jsonb;
BEGIN
  PERFORM pg_advisory_xact_lock({lock});
  SELECT jsonb_build_object(
    'messages', COALESCE((
      SELECT jsonb_agg(jsonb_build_object('seq', e.seq, 'type', e.type,
                                          'payload', e.payload) ORDER BY e.seq)
        FROM (SELECT seq, type, payload FROM events
               WHERE session_id = p_sid
                 AND type IN ('user/message','llm/message','tool/result')
                 AND (seq <= v13_last_user_seq(p_sid)
                      OR (payload->>'origin_user_seq')::bigint
                         = v13_last_user_seq(p_sid))
               ORDER BY seq DESC LIMIT 20) e), '[]'::jsonb),
    'derived', jsonb_build_object(
      'message_count', (SELECT count(*) FROM events WHERE session_id = p_sid
                         AND type IN ('user/message','llm/message','tool/result')
                         AND (seq <= v13_last_user_seq(p_sid)
                              OR (payload->>'origin_user_seq')::bigint
                                 = v13_last_user_seq(p_sid)))),
    'tools', COALESCE((
      SELECT jsonb_agg(jsonb_build_object('name', name, 'description', description,
                                          'kind', kind) ORDER BY name)
        FROM tools WHERE enabled), '[]'::jsonb))
    INTO v;
  RETURN v;
END $$;
"""


def main() -> int:
    setup_db()
    server = get_server()
    conn = psycopg2.connect(server.get_uri(DB))
    conn.autocommit = False
    cur = conn.cursor()
    guc(cur)

    sql_path = ROOT / "v13_manifest.sql"
    body = sql_path.read_text()
    n_fn = len(re.findall(r"^CREATE(?: OR REPLACE)? FUNCTION", body, re.M))
    n_trg = len(re.findall(r"^CREATE TRIGGER", body, re.M))
    n_or = len(re.findall(r"^CREATE OR REPLACE FUNCTION", body, re.M))
    names = re.findall(
        r"^CREATE(?: OR REPLACE)? FUNCTION\s+([a-z0-9_]+)\s*\(",
        body, re.M | re.I)
    check("G7: CREATE FUNCTION total 21", n_fn == 21, n_fn)
    check("G7: CREATE TRIGGER total 7", n_trg == 7, n_trg)
    check("G7: OR REPLACE 3", n_or == 3, n_or)
    check("G7: unique function names", len(names) == len(set(names)), names)
    check("G7: policy INSERT semicolon",
          "judgment_defaults" in body and body.count("INSERT INTO v13_policies") >= 1)
    check("G7: backfill INSERT", "INSERT INTO v13_goals" in body)
    check("G6: files_through manifest is 6",
          len(files_through("manifest")) == 6, len(files_through("manifest")))
    check("G6: SQL_LOAD_ORDER[5] is manifest",
          SQL_LOAD_ORDER[5].name == "v13_manifest.sql")
    for st in ("schema", "resolve", "loop", "twophase", "envelope"):
        check(f"G6: {st} prefix excludes manifest",
              all(p.name != "v13_manifest.sql" for p in files_through(st)))
    check("paper: BEGIN/COMMIT wrap",
          body.lstrip().startswith("BEGIN;") and "COMMIT;" in body[-20:])
    check("paper: $$ even", body.count("$$") % 2 == 0, body.count("$$"))

    # ----- A goal / freshness -----
    sid_a1 = new_session(cur)
    cur.execute("SELECT count(*) FROM v13_goals WHERE session_id=%s", (sid_a1,))
    g0 = cur.fetchone()[0]
    seq = append_user(cur, sid_a1, "goal-a1")
    cur.execute("SELECT count(*) FROM v13_goals WHERE session_id=%s", (sid_a1,))
    check("A1: user/message projects goal", cur.fetchone()[0] == g0 + 1)
    cur.execute(
        "SELECT content_hash, payload FROM v13_goals WHERE session_id=%s AND seq=%s",
        (sid_a1, seq))
    gh, gp = cur.fetchone()
    cur.execute("SELECT encode(digest(%s::text, 'sha256'), 'hex')", (json.dumps(gp),))
    # payload stored as jsonb; compare via SQL
    cur.execute(
        "SELECT content_hash = encode(digest(payload::text, 'sha256'), 'hex') "
        "FROM v13_goals WHERE session_id=%s AND seq=%s", (sid_a1, seq))
    check("A1: content_hash = sha256(payload)", cur.fetchone()[0] is True)
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'turn/route', '{}'::jsonb)",
        (sid_a1, u()))
    cur.fetchone()
    cur.execute("SELECT count(*) FROM v13_goals WHERE session_id=%s", (sid_a1,))
    check("A1: non-user event zero extra goal", cur.fetchone()[0] == g0 + 1)
    fails_with(cur, "UPDATE v13_goals SET payload='{}'::jsonb WHERE session_id=%s",
               (sid_a1,), "append-only", "A1: UPDATE goals rejected")
    fails_with(cur, "DELETE FROM v13_goals WHERE session_id=%s",
               (sid_a1,), "append-only", "A1: DELETE goals rejected")
    fails_with(
        cur,
        "INSERT INTO v13_goals (session_id, seq, content_hash, payload) "
        "VALUES (%s, 999, 'deadbeef', '{}'::jsonb)",
        (sid_a1,), "check", "A1: forged hash rejected")
    cur.execute(
        "INSERT INTO v13_goals (session_id, seq, content_hash, payload) "
        "SELECT e.session_id, e.seq, encode(digest(e.payload::text,'sha256'),'hex'), "
        "e.payload FROM events e WHERE e.type='user/message' ON CONFLICT DO NOTHING")
    cur.execute("SELECT count(*) FROM v13_goals WHERE session_id=%s", (sid_a1,))
    check("A1: backfill idempotent", cur.fetchone()[0] == g0 + 1)

    cur.execute(
        "SELECT v13_goal_hash(%s), encode(digest(payload::text,'sha256'),'hex') "
        "FROM v13_goals WHERE session_id=%s ORDER BY seq DESC LIMIT 1",
        (sid_a1, sid_a1))
    h_fn, h_raw = cur.fetchone()
    check("A2(i): goal_hash = last payload sha", h_fn == h_raw)
    sid_empty = new_session(cur)
    cur.execute("SELECT v13_goal_hash(%s)", (sid_empty,))
    check("A2(ii): empty = sha256('')", cur.fetchone()[0] == sha_empty(cur))
    append_user(cur, sid_a1, "second-goal")
    cur.execute(
        "SELECT v13_goal_hash(%s), encode(digest(payload::text,'sha256'),'hex') "
        "FROM v13_goals WHERE session_id=%s ORDER BY seq DESC LIMIT 1",
        (sid_a1, sid_a1))
    h2, h2r = cur.fetchone()
    check("A2(iii): later user/message wins", h2 == h2r and h2 != h_fn)

    cur.execute("SELECT v13_probe(%s)", (sid_a1,))
    pr = cur.fetchone()[0]
    for k in ("session_version", "max_event_seq", "goal_hash",
              "route_policy_name", "route_policy_version",
              "tools_revision", "candidate_generation_revision"):
        check(f"A3: probe has {k}", k in pr, list(pr))
    cur.execute("SELECT v13_goal_hash(%s)", (sid_a1,))
    check("A3: probe goal_hash = v13_goal_hash", pr["goal_hash"] == cur.fetchone()[0])
    cur.execute("SELECT revision FROM v13_tools_meta WHERE singleton")
    rev0 = cur.fetchone()[0]
    cur.execute("UPDATE tools SET enabled=false WHERE name='send_summary_email'")
    cur.execute("SELECT v13_probe(%s)", (sid_a1,))
    pr2 = cur.fetchone()[0]
    check("A3: disable tool bumps tools_revision",
          pr2["tools_revision"] != pr["tools_revision"], (rev0, pr2["tools_revision"]))
    cur.execute("UPDATE tools SET enabled=true WHERE name='send_summary_email'")
    cur.execute(
        "INSERT INTO v13_judgment_template_versions "
        "(template_name, template_version) "
        "SELECT 'intent', coalesce(max(template_version),0)+1 "
        "FROM v13_judgment_template_versions WHERE template_name='intent'")
    cur.execute(
        "INSERT INTO judgment_templates "
        "(template_name, template_version, kind, question, criteria, "
        " answer_schema_version, projection, writer, wire_version, canon_version) "
        "SELECT 'intent', v.template_version, t.kind, t.question, t.criteria, "
        " t.answer_schema_version, t.projection, t.writer, t.wire_version, "
        " t.canon_version "
        "FROM v13_template_latest t, v13_judgment_template_versions v "
        "WHERE t.template_name='intent' AND v.template_name='intent' "
        "AND v.state='draft' ORDER BY v.template_version DESC LIMIT 1")
    cur.execute(
        "UPDATE v13_judgment_template_versions SET state='frozen' "
        "WHERE template_name='intent' AND state='draft'")
    cur.execute("SELECT v13_probe(%s)", (sid_a1,))
    pr3 = cur.fetchone()[0]
    check("A3: freeze template bumps cgr",
          pr3["candidate_generation_revision"] != pr2["candidate_generation_revision"])

    guc(cur)
    cur.execute("SELECT v13_judgment_envelope(%s)", (sid_a1,))
    env = cur.fetchone()[0]
    check("A4: 19 keys", set(env) == ENV19, set(env) ^ ENV19)
    cur.execute("SELECT v13_goal_hash(%s)", (sid_a1,))
    check("A4: envelope goal_hash = v13_goal_hash",
          env["goal_hash"] == cur.fetchone()[0])

    sid_a5 = new_session(cur)
    append_user(cur, sid_a5, "fresh")
    cur.execute("SELECT v13_context_fresh(%s)", (sid_a5,))
    check("A5: new session not fresh", cur.fetchone()[0] is False)
    cur.execute("SELECT v13_context_required(%s)", (sid_a5,))
    tok = cur.fetchone()[0]
    check("A5: token seven keys",
          set(tok) == {"sem", "dec", "goal", "tools_rev", "asm_ver", "jdef_ver", "gen_ver"},
          set(tok))
    snap5, eid5, _, conn, cur = parse_settle(server, conn, cur, sid_a5)
    cur.execute("SELECT v13_context_fresh(%s)", (sid_a5,))
    check("A5: after settle fresh", cur.fetchone()[0] is True)
    conn, cur = recycle(server, conn)
    snap5b = answers_sql(cur, sid_a5)
    poison(cur)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid_a5, json.dumps(snap5b)))
    a5b = cur.fetchone()[0]
    check("A5: second advance past ②", a5b in ("progressed", "waiting", "terminal"), a5b)
    cur.execute(
        "SELECT inline->'replay'->>'mode' FROM artifacts a "
        "JOIN sessions s ON s.context_active_artifact=a.artifact_id "
        "WHERE s.session_id=%s", (sid_a5,))
    check("A5: first settle mode=fresh", cur.fetchone()[0] == "fresh")
    cur.execute(
        "SELECT request FROM effects WHERE effect_id=%s", (eid5,))
    req5 = cur.fetchone()[0]
    check("A5: refresh request only goal_hash",
          set(req5) == {"goal_hash"}, req5)

    # A6 token monotonic
    sid_a6 = new_session(cur)
    last6 = append_user(cur, sid_a6, "tok")
    cur.execute("SELECT v13_context_required(%s)", (sid_a6,))
    t0 = cur.fetchone()[0]
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'llm/message', %s::jsonb)",
        (sid_a6, u(), json.dumps({"text": "x", "origin_user_seq": last6})))
    cur.fetchone()
    cur.execute("SELECT v13_context_required(%s)", (sid_a6,))
    t1 = cur.fetchone()[0]
    check("A6: llm/message moves sem", t1["sem"] != t0["sem"], (t0["sem"], t1["sem"]))
    parse(cur, sid_a6)
    cur.execute("SELECT v13_context_required(%s)", (sid_a6,))
    t2 = cur.fetchone()[0]
    check("A6: parse moves dec", t2["dec"] != t1["dec"], (t1["dec"], t2["dec"]))
    append_user(cur, sid_a6, "tok2")
    cur.execute("SELECT v13_context_required(%s)", (sid_a6,))
    t3 = cur.fetchone()[0]
    check("A6: new user moves sem and goal",
          t3["sem"] != t2["sem"] and t3["goal"] != t2["goal"])
    cur.execute("SELECT (v13_context_required(%s))->>'tools_rev'", (sid_a6,))
    tr0 = cur.fetchone()[0]
    cur.execute("UPDATE tools SET description='x' WHERE name='session_stats'")
    cur.execute("SELECT (v13_context_required(%s))->>'tools_rev'", (sid_a6,))
    check("A6: catalog DDL moves tools_rev", cur.fetchone()[0] != tr0)
    cur.execute("SELECT (v13_context_required(%s))->>'asm_ver'", (sid_a6,))
    av0 = cur.fetchone()[0]
    bump_policy(cur, "assemble_manifest", seed_asm())
    cur.execute("SELECT (v13_context_required(%s))->>'asm_ver'", (sid_a6,))
    check("A6: asm v2 moves asm_ver", cur.fetchone()[0] != av0)
    cur.execute("SELECT (v13_context_required(%s))->>'jdef_ver'", (sid_a6,))
    jv0 = cur.fetchone()[0]
    bump_policy(cur, "judgment_defaults",
                {"points": {}, "actions": ["include", "exclude", "degrade", "fail"]})
    cur.execute("SELECT (v13_context_required(%s))->>'jdef_ver'", (sid_a6,))
    check("A6: jdef v2 moves jdef_ver", cur.fetchone()[0] != jv0)
    cur.execute("SELECT (v13_context_required(%s))->>'gen_ver'", (sid_a6,))
    gv0 = cur.fetchone()[0]
    bump_policy(cur, "generation",
                {"provider": "mock", "model": "mock-2",
                 "system_blocks_digest": "-none-"})
    cur.execute("SELECT (v13_context_required(%s))->>'gen_ver'", (sid_a6,))
    check("A6: gen v2 moves gen_ver", cur.fetchone()[0] != gv0)
    bump_policy(cur, "generation",
                {"provider": "mock", "model": "mock-1",
                 "system_blocks_digest": "-none-"})
    restore_asm(cur)

    conn, cur = recycle(server, conn)
    # A7 straggler
    sid_a7 = new_session(cur)
    last7 = append_user(cur, sid_a7, "strag")
    _, _, _, conn, cur = parse_settle(server, conn, cur, sid_a7)
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_a7,))
    m7a = cur.fetchone()[0]
    h_hist = sec_map(m7a)["history"]["content_hash"]
    cur.execute("SELECT v13_context_required(%s)", (sid_a7,))
    sem0 = cur.fetchone()[0]["sem"]
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'tool/result', %s::jsonb)",
        (sid_a7, u(), json.dumps({"tool": "x", "result": {"v": 1},
                                  "origin_user_seq": -1})))
    # force high seq already from append
    cur.execute("SELECT v13_context_required(%s)", (sid_a7,))
    check("A7: straggler moves sem", cur.fetchone()[0]["sem"] != sem0)
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_a7,))
    m7b = cur.fetchone()[0]
    check("A7: history hash unchanged",
          sec_map(m7b)["history"]["content_hash"] == h_hist)

    conn, cur = recycle(server, conn)
    # A8 single-active
    sid_a8 = new_session(cur)
    append_user(cur, sid_a8, "write a poem")
    snap8 = answers_llm(cur, sid_a8)
    # settle first so ② is fresh, then llm
    a8, eid_r, _ = hang_refresh(cur, sid_a8, snap8)
    if eid_r:
        settle(cur, eid_r)
        conn, cur = recycle(server, conn)
        snap8 = answers_llm(cur, sid_a8)
        poison(cur)
        cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid_a8, json.dumps(snap8)))
        cur.fetchone()
    cur.execute(
        "SELECT count(*) FROM effects WHERE session_id=%s AND kind='llm' "
        "AND status IN ('ready','claimed')", (sid_a8,))
    n_llm = cur.fetchone()[0]
    if n_llm == 0:
        # may have finished sql; enqueue llm by force
        cur.execute(
            "SELECT v13_enqueue_effect(%s, 'llm', %s::jsonb)",
            (sid_a8, json.dumps({"route": "llm"})))
        cur.fetchone()
    conn, cur = recycle(server, conn)
    cur.execute("SELECT v13_context_fresh(%s)", (sid_a8,))
    # force not fresh
    cur.execute(
        "UPDATE sessions SET context_active_revision=NULL WHERE session_id=%s",
        (sid_a8,))
    snap8b = answers_llm(cur, sid_a8)
    poison(cur)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid_a8, json.dumps(snap8b)))
    a8b = cur.fetchone()[0]
    check("A8: ready llm -> waiting", a8b == "waiting", a8b)
    cur.execute(
        "SELECT count(*) FROM effects WHERE session_id=%s AND kind='context_refresh' "
        "AND status IN ('ready','claimed')", (sid_a8,))
    check("A8: context_refresh not enqueued", cur.fetchone()[0] == 0)

    conn, cur = recycle(server, conn)
    # ----- B manifest fields -----
    sid_b = new_session(cur)
    append_user(cur, sid_b, "manifest-b")
    _, _, _, conn, cur = parse_settle(server, conn, cur, sid_b)
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_b,))
    mb = cur.fetchone()[0]
    check("B1: 10 outer keys", set(mb) == TOP10, set(mb) ^ TOP10)
    check("B1: manifest_version=1", mb["manifest_version"] == 1)
    check("B1: session_id", str(mb["session_id"]) == str(sid_b))
    check("B1: policy 4 keys",
          set(mb["policy"]) == {"assemble_version", "budget_tokens",
                                "est_bytes_per_token", "judgment_defaults_version"})
    check("B1: required_revision 7 keys",
          set(mb["required_revision"]) == {
              "sem", "dec", "goal", "tools_rev", "asm_ver", "jdef_ver", "gen_ver"})
    check("B1: no timestamp keys",
          not any("at" == k or k.endswith("_at") for k in mb))

    sm = sec_map(mb)
    check("B2: three sections", set(sm) == {"goal", "history", "tools"}, set(sm))
    for name, scope, prio, tname in (
            ("goal", "Session", "First", "verbatim"),
            ("history", "Session", "Normal", "verbatim"),
            ("tools", "Global", "First", "catalog_digest")):
        s = sm[name]
        check(f"B2: {name} 9 keys", set(s) == SEC9, set(s) ^ SEC9)
        check(f"B2: {name} cache_scope", s["cache_scope"] == scope)
        check(f"B2: {name} priority", s["priority"] == prio)
        check(f"B2: {name} hash 64hex", bool(HEX64.match(s["content_hash"])))
        check(f"B2: {name} transform name",
              s["transform"].get("applied") is True
              and s["transform"].get("name") == tname, s["transform"])
        check(f"B2: {name} est_tokens>0", s["est_tokens"] > 0, s["est_tokens"])
    check("B2: goal payload_ref",
          sm["goal"]["payload_ref"]["kind"] == "goal"
          and "seq" in sm["goal"]["payload_ref"])
    for name in ("history", "tools"):
        prf = sm[name]["payload_ref"]
        check(f"B2: {name} blob ref",
              prf["kind"] == "blob" and prf["content_hash"] == sm[name]["content_hash"],
              prf)
    cur.execute("SELECT (value->>'est_bytes_per_token')::int FROM v13_policies "
                "WHERE name='assemble_manifest' AND active")
    div = cur.fetchone()[0]
    cur.execute(
        "SELECT octet_length(payload::text) FROM v13_goals "
        "WHERE session_id=%s ORDER BY seq DESC LIMIT 1", (sid_b,))
    gbytes = cur.fetchone()[0]
    check("B2: goal est formula",
          sm["goal"]["est_tokens"] == (gbytes + div - 1) // div)

    qs = mb["query_side"]
    check("B3: query_side keys", set(qs) == {"query_artifact_id", "candidates"})
    check("B3: query_artifact_id is goal addr",
          qs["query_artifact_id"]["kind"] == "goal")
    check("B3: one echo candidate", len(qs["candidates"]) == 1)
    cand = qs["candidates"][0]
    check("B3: candidate four keys",
          set(cand) == {"content_hash", "bm25", "spans", "decision_id"})
    check("B3: spans empty array", cand["spans"] == [])

    cur.execute(
        "SELECT count(*) FROM decisions WHERE session_id=%s AND answer IS NOT NULL",
        (sid_b,))
    nd = cur.fetchone()[0]
    check("B4: decisions landed", nd >= 2, nd)
    check("B4: judgments empty", mb["judgments"] == [])
    cur.execute(
        "SELECT count(*) FROM decisions d "
        "LEFT JOIN judgment_calls c ON c.session_id=d.session_id "
        "WHERE d.session_id=%s", (sid_b,))
    check("B4: history queryable", cur.fetchone()[0] >= nd)
    src = (ROOT / "v13_manifest.sql").read_text()
    check("B4: complete predicate in assemble",
          "answer IS NOT NULL" in src and "status IN ('answered','cached')" in src)
    check("B4: no usage key in judgments shape",
          all("usage" not in (j or {}) for j in mb["judgments"]))

    # B5 validate
    cur.execute("SELECT v13_manifest_validate(%s::jsonb)", (json.dumps(mb),))
    check("B5: legal applied manifest validates", True)
    for reason in ("budget", "priority_never", "disabled", "invalid_override"):
        mskip = json.loads(json.dumps(mb))
        mskip["sections"][1]["transform"] = {"applied": False, "reason": reason}
        cur.execute("SELECT v13_manifest_validate(%s::jsonb)", (json.dumps(mskip),))
        check(f"B5: skip {reason} validates", True)

    def vfail(obj, label):
        fails_with(cur, "SELECT v13_manifest_validate(%s::jsonb)",
                   (json.dumps(obj),), "V3003", label, pgcode="V3003")

    extra = json.loads(json.dumps(mb))
    extra["sidecar"] = 1
    vfail(extra, "B5: extra top key")
    missing = json.loads(json.dumps(mb))
    del missing["turn_no"]
    vfail(missing, "B5: missing top key")
    badsc = json.loads(json.dumps(mb))
    badsc["sections"][0]["cache_scope"] = None
    vfail(badsc, "B5: null cache_scope")
    badpr = json.loads(json.dumps(mb))
    badpr["sections"][0]["priority"] = None
    vfail(badpr, "B5: null priority")
    badch = json.loads(json.dumps(mb))
    badch["sections"][0]["churn"] = None
    vfail(badch, "B5: null churn")
    badmv = json.loads(json.dumps(mb))
    del badmv["manifest_version"]
    vfail(badmv, "B5: missing manifest_version")
    bada = json.loads(json.dumps(mb))
    bada["sections"][0]["transform"] = {"applied": True}
    vfail(bada, "B5: applied missing name")
    bads = json.loads(json.dumps(mb))
    bads["sections"][1]["transform"] = {"applied": False}
    vfail(bads, "B5: skipped missing reason")
    badmix = json.loads(json.dumps(mb))
    badmix["sections"][0]["transform"] = {
        "applied": True, "name": "verbatim", "reason": "budget"}
    vfail(badmix, "B5: applied with reason")
    badnm = json.loads(json.dumps(mb))
    badnm["sections"][1]["transform"] = {"applied": False, "reason": "budget",
                                         "name": "verbatim"}
    vfail(badnm, "B5: skipped with name")
    badtn = json.loads(json.dumps(mb))
    badtn["sections"][0]["transform"] = {"applied": True, "name": "window_20"}
    vfail(badtn, "B5: bad transform name")
    badstr = json.loads(json.dumps(mb))
    badstr["sections"][0]["transform"]["applied"] = "true"
    vfail(badstr, "B5: applied string true")
    empty = json.loads(json.dumps(mb))
    empty["sections"] = []
    vfail(empty, "B5: empty sections")
    badref = json.loads(json.dumps(mb))
    badref["sections"][1]["payload_ref"]["kind"] = "path"
    vfail(badref, "B5: illegal payload_ref kind")
    badhex = json.loads(json.dumps(mb))
    badhex["sections"][1]["payload_ref"]["content_hash"] = "abc"
    vfail(badhex, "B5: short blob hash")
    nopj = json.loads(json.dumps(mb))
    del nopj["policy"]["judgment_defaults_version"]
    vfail(nopj, "B5: policy missing jdef_ver")
    zdiv = json.loads(json.dumps(mb))
    zdiv["policy"]["est_bytes_per_token"] = 0
    vfail(zdiv, "B5: divisor 0")
    nbud = json.loads(json.dumps(mb))
    nbud["policy"]["budget_tokens"] = -1
    vfail(nbud, "B5: negative budget")
    six = json.loads(json.dumps(mb))
    del six["required_revision"]["gen_ver"]
    vfail(six, "B5: token without gen_ver")
    badg = json.loads(json.dumps(mb))
    badg["required_revision"]["goal"] = "xyz"
    vfail(badg, "B5: goal not 64hex")
    exr = json.loads(json.dumps(mb))
    exr["replay"]["mode"] = "exact_replay"
    vfail(exr, "B5: exact_replay in assemble product")
    jrow = {
        "decision_id": str(uuid.uuid4()),
        "epoch": "pre-bind",
        "request_hash": "a" * 64,
        "template_name": "intent",
        "template_version": 1,
        "raw_verdict": {"noul": 0.1},
        "final_action": "recorded",
    }
    okj = json.loads(json.dumps(mb))
    okj["judgments"] = [jrow]
    cur.execute("SELECT v13_manifest_validate(%s::jsonb)", (json.dumps(okj),))
    check("B5: legal judgment row validates", True)
    badj = json.loads(json.dumps(okj))
    del badj["judgments"][0]["raw_verdict"]
    vfail(badj, "B5: judgment missing raw_verdict")
    badfa = json.loads(json.dumps(okj))
    badfa["judgments"][0]["final_action"] = "skip"
    vfail(badfa, "B5: judgment bad final_action")
    bade = json.loads(json.dumps(okj))
    bade["judgments"][0]["epoch"] = "mid"
    vfail(bade, "B5: judgment bad epoch")
    badpair = json.loads(json.dumps(okj))
    badpair["judgments"][0]["template_name"] = "intent"
    badpair["judgments"][0]["template_version"] = None
    vfail(badpair, "B5: template pair mismatch")
    badc = json.loads(json.dumps(mb))
    del badc["query_side"]["candidates"][0]["spans"]
    vfail(badc, "B5: candidate missing spans")
    badchash = json.loads(json.dumps(mb))
    badchash["query_side"]["candidates"][0]["content_hash"] = "ZZ"
    vfail(badchash, "B5: candidate hash not 64hex")
    pidu = json.loads(json.dumps(mb))
    pidu["prefix_identity"] = "A" * 64
    vfail(pidu, "B5: prefix_identity uppercase")
    pid63 = json.loads(json.dumps(mb))
    pid63["prefix_identity"] = "a" * 63
    vfail(pid63, "B5: prefix_identity 63 chars")

    cur.execute("SELECT v13_prefix_identity(%s)", (sid_b,))
    pid1 = cur.fetchone()[0]
    check("B6: prefix_identity 64hex", bool(HEX64.match(pid1)), pid1)
    bump_policy(cur, "generation",
                {"provider": "mock", "model": "other-model",
                 "system_blocks_digest": "-none-"})
    cur.execute("SELECT v13_prefix_identity(%s)", (sid_b,))
    pid2 = cur.fetchone()[0]
    check("B6: generation model change moves identity", pid2 != pid1)
    bump_policy(cur, "generation",
                {"provider": "mock", "model": "mock-1",
                 "system_blocks_digest": "-none-"})
    cur.execute("SELECT set_config('typesafe.model', 'other', true)")
    cur.execute("SELECT v13_prefix_identity(%s)", (sid_b,))
    pid3 = cur.fetchone()[0]
    check("B6: typesafe.model does not move identity", pid3 == pid1)
    conn, cur = recycle(server, conn)
    cur.execute("SELECT v13_prefix_identity(%s)", (sid_b,))
    check("B6: same state equal", cur.fetchone()[0] == pid1)
    cur.execute("SELECT pg_get_functiondef('v13_latch_digest(uuid)'::regprocedure)")
    check("B6: latch stub -none-", "-none-" in cur.fetchone()[0])
    cur.execute(
        "SELECT value->>'system_blocks_digest' FROM v13_policies "
        "WHERE name='generation' AND active")
    check("B6: system_blocks stub in generation policy",
          cur.fetchone()[0] == "-none-")
    cur.execute("SAVEPOINT sp_nogen")
    cur.execute("UPDATE v13_policies SET active=false WHERE name='generation'")
    fails_with(cur, "SELECT v13_prefix_identity(%s)", (sid_b,),
               "generation", "B6: missing generation RAISE")
    cur.execute("ROLLBACK TO SAVEPOINT sp_nogen")

    cur.execute("SELECT value FROM v13_policies WHERE name='judgment_defaults' AND active")
    cur.execute("SELECT v13_judgment_defaults_check(value) FROM v13_policies "
                "WHERE name='judgment_defaults' AND active")
    check("B7: seed defaults check", True)
    fails_with(cur,
               "SELECT v13_judgment_defaults_check(%s::jsonb)",
               (json.dumps({"points": {"x": {"missing": "exclude", "timeout": "fail"}},
                            "actions": ["include", "exclude", "degrade", "fail"]}),),
               "V3003", "B7: missing review key", pgcode="V3003")
    fails_with(cur,
               "SELECT v13_judgment_defaults_check(%s::jsonb)",
               (json.dumps({"points": {"x": {"missing": "skip", "timeout": "fail",
                                             "review": "fail"}},
                            "actions": ["include", "exclude", "degrade", "fail"]}),),
               "V3003", "B7: action skip", pgcode="V3003")
    fails_with(cur,
               "SELECT v13_judgment_defaults_check(%s::jsonb)",
               (json.dumps({"points": {}, "actions": ["include", "exclude",
                                                     "degrade", "fail"],
                            "extra": 1}),),
               "V3003", "B7: extra top key", pgcode="V3003")
    bump_policy(cur, "judgment_defaults", {
        "points": {"score_v1": {"missing": "exclude", "timeout": "exclude",
                                "review": "degrade"}},
        "actions": ["include", "exclude", "degrade", "fail"]})
    cur.execute("SELECT v13_judgment_defaults_check(value) FROM v13_policies "
                "WHERE name='judgment_defaults' AND active")
    check("B7: legal points v2", True)
    cur.execute("SELECT (v13_context_required(%s))->>'jdef_ver'", (sid_b,))
    check("B7: jdef_ver moved", int(cur.fetchone()[0]) >= 2)
    bump_policy(cur, "judgment_defaults", {
        "points": {"bad": {"missing": "nope", "timeout": "fail", "review": "fail"}},
        "actions": ["include", "exclude", "degrade", "fail"]})
    sid_b7 = new_session(cur)
    append_user(cur, sid_b7, "b7")
    a, eid, _ = hang_refresh(cur, sid_b7)
    ck = claim_pinned(cur, eid)
    fails_with(cur, "SELECT v13_refresh_context(%s,%s,%s)",
               (eid, ck["attempt_no"], ck["fence"]),
               "V3003", "B7: settle rejects illegal defaults", pgcode="V3003")
    bump_policy(cur, "judgment_defaults",
                {"points": {}, "actions": ["include", "exclude", "degrade", "fail"]})

    conn, cur = recycle(server, conn)
    # ----- C applied/skipped -----
    sid_c = new_session(cur)
    append_user(cur, sid_c, "budget-c")
    _, _, _, conn, cur = parse_settle(server, conn, cur, sid_c)
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_c,))
    mc = cur.fetchone()[0]
    smc = sec_map(mc)
    check("C1: all applied",
          all(s["transform"]["applied"] is True for s in mc["sections"]))
    check("C1: history verbatim", smc["history"]["transform"]["name"] == "verbatim")
    check("C1: churn first edition 0",
          all(s["churn"] == 0 for s in mc["sections"]))

    ge, te, he = smc["goal"]["est_tokens"], smc["tools"]["est_tokens"], smc["history"]["est_tokens"]
    order = [s["section_id"] for s in mc["sections"]]
    check("C1: order goal,tools,history",
          order == ["goal", "tools", "history"], order)

    def applied_set(m):
        return {s["section_id"] for s in m["sections"] if s["transform"]["applied"]}

    def reason_of(m, name):
        return sec_map(m)[name]["transform"].get("reason")

    v = seed_asm()
    v["budget_tokens"] = ge
    bump_policy(cur, "assemble_manifest", v)
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_c,))
    m2a = cur.fetchone()[0]
    check("C2 v2a applied={goal}", applied_set(m2a) == {"goal"}, applied_set(m2a))
    check("C2 v2a tools budget", reason_of(m2a, "tools") == "budget")
    check("C2 v2a history budget", reason_of(m2a, "history") == "budget")
    v["budget_tokens"] = ge + te - 1
    bump_policy(cur, "assemble_manifest", v)
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_c,))
    m2b = cur.fetchone()[0]
    check("C2 v2b applied={goal}", applied_set(m2b) == {"goal"}, applied_set(m2b))
    v["budget_tokens"] = ge + te
    bump_policy(cur, "assemble_manifest", v)
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_c,))
    m2c = cur.fetchone()[0]
    check("C2 v2c applied={goal,tools}",
          applied_set(m2c) == {"goal", "tools"}, applied_set(m2c))
    check("C2 v2c history budget", reason_of(m2c, "history") == "budget")
    v["budget_tokens"] = 0
    bump_policy(cur, "assemble_manifest", v)
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_c,))
    m2d = cur.fetchone()[0]
    check("C2 v2d all skip", applied_set(m2d) == set(), applied_set(m2d))
    restore_asm(cur)

    v = seed_asm()
    v["priority_overrides"] = {"history": "Never"}
    bump_policy(cur, "assemble_manifest", v)
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_c,))
    mnever = cur.fetchone()[0]
    check("C3: history Never skip",
          reason_of(mnever, "history") == "priority_never")
    check("C3: history priority field Never",
          sec_map(mnever)["history"]["priority"] == "Never")
    check("C3: Never not in packing",
          applied_set(mnever) == {"goal", "tools"}, applied_set(mnever))
    restore_asm(cur)

    v = seed_asm()
    v["kinds_disabled"] = ["tools"]
    bump_policy(cur, "assemble_manifest", v)
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_c,))
    mdis = cur.fetchone()[0]
    check("C4: tools disabled", reason_of(mdis, "tools") == "disabled")
    restore_asm(cur)

    conn, cur = recycle(server, conn)
    cur.execute(
        "SELECT inline FROM artifacts a JOIN sessions s "
        "ON s.context_active_artifact=a.artifact_id WHERE s.session_id=%s",
        (sid_c,))
    m_old = cur.fetchone()[0]
    cur.execute("SELECT v13_last_user_seq(%s)", (sid_c,))
    origin = cur.fetchone()[0]
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'llm/message', %s::jsonb)",
        (sid_c, u(), json.dumps({"text": "more", "origin_user_seq": origin})))
    cur.fetchone()
    _, _, _, conn, cur = parse_settle(server, conn, cur, sid_c)
    cur.execute(
        "SELECT inline FROM artifacts a JOIN sessions s "
        "ON s.context_active_artifact=a.artifact_id WHERE s.session_id=%s",
        (sid_c,))
    m_new = cur.fetchone()[0]
    check("C5: history churn=1", sec_map(m_new)["history"]["churn"] == 1)
    check("C5: history hash changed",
          sec_map(m_new)["history"]["content_hash"]
          != sec_map(m_old)["history"]["content_hash"])
    check("C5: goal churn=0", sec_map(m_new)["goal"]["churn"] == 0)
    _, _, _, conn, cur = parse_settle(server, conn, cur, sid_c)
    cur.execute(
        "SELECT inline FROM artifacts a JOIN sessions s "
        "ON s.context_active_artifact=a.artifact_id WHERE s.session_id=%s",
        (sid_c,))
    m_n2 = cur.fetchone()[0]
    check("C5: unchanged edition churn 0",
          sec_map(m_n2)["history"]["churn"] == 0)

    v = seed_asm()
    v["priority_overrides"] = {"history": "ASAP"}
    bump_policy(cur, "assemble_manifest", v)
    sid_c6 = new_session(cur)
    append_user(cur, sid_c6, "c6")
    a, eid, _ = hang_refresh(cur, sid_c6)
    ck = claim_pinned(cur, eid)
    fails_with(cur, "SELECT v13_refresh_context(%s,%s,%s)",
               (eid, ck["attempt_no"], ck["fence"]),
               "V3003", "C6: settle rejects ASAP override", pgcode="V3003")
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_c6,))
    minv = cur.fetchone()[0]
    hs = sec_map(minv)["history"]
    check("C6: invalid_override skip",
          hs["transform"] == {"applied": False, "reason": "invalid_override"},
          hs["transform"])
    check("C6: priority fallback Normal", hs["priority"] == "Normal")
    check("C6: not packed",
          applied_set(minv) == {"goal", "tools"}, applied_set(minv))
    restore_asm(cur)

    conn, cur = recycle(server, conn)
    # ----- D replay -----
    sid_d = new_session(cur)
    append_user(cur, sid_d, "replay-d")
    _, _, _, conn, cur = parse_settle(server, conn, cur, sid_d)
    cur.execute(
        "SELECT context_active_artifact FROM sessions WHERE session_id=%s", (sid_d,))
    art1 = cur.fetchone()[0]
    cur.execute("SELECT inline FROM artifacts WHERE artifact_id=%s", (art1,))
    inline1 = cur.fetchone()[0]
    cur.execute("SELECT v13_replay(%s)", (art1,))
    rp = cur.fetchone()[0]
    check("D1: replay mode exact_replay", rp["replay"]["mode"] == "exact_replay")
    check("D1: replay two keys",
          set(rp["replay"]) == {"mode", "source_artifact"})
    check("D1: source_artifact", str(rp["replay"]["source_artifact"]) == str(art1))
    base = json.loads(json.dumps(inline1))
    base.pop("replay", None)
    got = json.loads(json.dumps(rp))
    got.pop("replay", None)
    check("D1: body equals inline minus replay", base == got)
    check("D1: judgments empty", rp["judgments"] == [])
    cur.execute(
        "SELECT count(*) FROM decisions WHERE session_id=%s "
        "AND answer IS NOT NULL AND status IN ('answered','cached')", (sid_d,))
    n_d1 = cur.fetchone()[0]
    insert_complete_decision(cur, sid_d, "late-d1")
    cur.execute(
        "SELECT count(*) FROM decisions WHERE session_id=%s "
        "AND answer IS NOT NULL AND status IN ('answered','cached')", (sid_d,))
    check("D1: complete decision added", cur.fetchone()[0] == n_d1 + 1)
    cur.execute("SELECT v13_replay(%s)", (art1,))
    rp2 = cur.fetchone()[0]
    check("D1: replay unchanged after new decision", rp2 == rp)

    cur.execute("SELECT v13_last_user_seq(%s)", (sid_d,))
    origin = cur.fetchone()[0]
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'llm/message', %s::jsonb)",
        (sid_d, u(), json.dumps({"text": "advance-corpus", "origin_user_seq": origin})))
    cur.fetchone()
    cur.execute("SELECT count(*) FROM artifacts")
    nart = cur.fetchone()[0]
    cur.execute(
        "SELECT context_active_artifact FROM sessions WHERE session_id=%s", (sid_d,))
    ptr = cur.fetchone()[0]
    cur.execute("SELECT v13_assemble_manifest(%s, 1)", (sid_d,))
    mrec = cur.fetchone()[0]
    check("D2: recompute mode", mrec["replay"]["mode"] == "recompute")
    check("D2: assemble_version=1", mrec["policy"]["assemble_version"] == 1)
    cur.execute("SELECT count(*) FROM artifacts")
    check("D2: artifacts unchanged", cur.fetchone()[0] == nart)
    cur.execute(
        "SELECT context_active_artifact FROM sessions WHERE session_id=%s", (sid_d,))
    check("D2: pointer unchanged", cur.fetchone()[0] == ptr)

    v = seed_asm()
    v["budget_tokens"] = 100
    bump_policy(cur, "assemble_manifest", v)
    cur.execute("SELECT v13_assemble_manifest(%s, 1)", (sid_d,))
    mrec2 = cur.fetchone()[0]
    check("D2 bump: pinned v1 still recompute",
          mrec2["replay"]["mode"] == "recompute")
    _, _, _, conn, cur = parse_settle(server, conn, cur, sid_d)
    cur.execute(
        "SELECT inline->'replay'->>'mode' FROM artifacts a "
        "JOIN sessions s ON s.context_active_artifact=a.artifact_id "
        "WHERE s.session_id=%s", (sid_d,))
    check("D2 bump settle mode=recompute", cur.fetchone()[0] == "recompute")
    restore_asm(cur)

    cur.execute(
        "SELECT context_active_artifact, "
        "(SELECT inline->>'prefix_identity' FROM artifacts "
        " WHERE artifact_id=s.context_active_artifact) "
        "FROM sessions s WHERE session_id=%s", (sid_d,))
    old_art, old_pid = cur.fetchone()
    bump_policy(cur, "generation",
                {"provider": "mock", "model": "fork-model",
                 "system_blocks_digest": "-none-"})
    _, _, _, conn, cur = parse_settle(server, conn, cur, sid_d)
    cur.execute(
        "SELECT context_active_artifact, inline "
        "FROM sessions s JOIN artifacts a ON a.artifact_id=s.context_active_artifact "
        "WHERE s.session_id=%s", (sid_d,))
    new_art, mfr = cur.fetchone()
    check("D3: fresh after generation bump", mfr["replay"]["mode"] == "fresh")
    check("D3: prior_artifact_id old",
          str(mfr["replay"]["prior_artifact_id"]) == str(old_art))
    check("D3: prefix_identity changed", mfr["prefix_identity"] != old_pid)
    bump_policy(cur, "generation",
                {"provider": "mock", "model": "mock-1",
                 "system_blocks_digest": "-none-"})

    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_d,))
    d4a = cur.fetchone()[0]
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_d,))
    d4b = cur.fetchone()[0]
    check("D4: assemble deterministic", d4a == d4b)
    check("D4: order prank,section_id",
          [s["section_id"] for s in d4a["sections"]] == ["goal", "tools", "history"])

    conn, cur = recycle(server, conn)
    # ----- E epochs -----
    sid_e = new_session(cur)
    append_user(cur, sid_e, "epoch")
    parse(cur, sid_e)
    cur.execute(
        "SELECT bool_and(epoch='pre-bind') FROM decisions WHERE session_id=%s",
        (sid_e,))
    check("E1: default pre-bind", cur.fetchone()[0] is True)
    cur.execute(
        "SELECT decision_id FROM decisions WHERE session_id=%s LIMIT 1", (sid_e,))
    did = cur.fetchone()[0]
    fails_with(cur, "UPDATE decisions SET epoch='pre-finalize' WHERE decision_id=%s",
               (did,), "frozen", "E1: UPDATE epoch in-vocab rejected")
    fails_with(cur, "UPDATE decisions SET epoch='nope' WHERE decision_id=%s",
               (did,), "frozen", "E1: UPDATE epoch oob rejected")

    cur.execute(
        "INSERT INTO v13_judgment_template_versions (template_name, template_version) "
        "VALUES ('t9ep', 1)")
    cur.execute(
        "INSERT INTO judgment_templates "
        "(template_name, template_version, kind, question, criteria, "
        " answer_schema_version, projection, writer, wire_version, canon_version, "
        " epoch) "
        "VALUES ('t9ep', 1, 'noul', 'Epoch template question?', NULL, 1, "
        " '[\"*\"]'::jsonb, 'v13_resolve', 1, 1, 'pre-finalize')")
    cur.execute(
        "UPDATE v13_judgment_template_versions SET state='frozen' "
        "WHERE template_name='t9ep'")
    cur.execute(
        "INSERT INTO decisions (session_id, signal, kind, question, context, "
        " request_hash, template_name, template_version) "
        "VALUES (%s, 't9ep_sig', 'noul', 'Epoch template question?', "
        " '{}'::jsonb, %s, 't9ep', 1)",
        (sid_e, "b" * 64))
    cur.execute(
        "SELECT epoch FROM decisions WHERE session_id=%s AND signal='t9ep_sig'",
        (sid_e,))
    check("E2: template epoch pre-finalize", cur.fetchone()[0] == "pre-finalize")
    cur.execute(
        "INSERT INTO decisions (session_id, signal, kind, question, context, "
        " request_hash) "
        "VALUES (%s, 'dp1era', 'noul', 'DP1 era question here.', "
        " '{}'::jsonb, %s)",
        (sid_e, "c" * 64))
    cur.execute(
        "SELECT epoch FROM decisions WHERE session_id=%s AND signal='dp1era'",
        (sid_e,))
    check("E2: NULL template -> pre-bind", cur.fetchone()[0] == "pre-bind")

    conn, cur = recycle(server, conn)
    sid_e3 = new_session(cur)
    append_user(cur, sid_e3, "e3-fill")
    cur.execute("SELECT v13_judgment_envelope(%s)", (sid_e3,))
    env_e3 = cur.fetchone()[0]
    item_e3 = next(x for x in env_e3["needed"] if x["signal"] == "intent")
    cur.execute(
        "SELECT v13_judgment_hash(%s::jsonb, %s, %s, %s, %s::jsonb)",
        (json.dumps(env_e3), item_e3["signal"], item_e3["kind"],
         item_e3["question"],
         json.dumps(item_e3.get("criteria"))
         if item_e3.get("criteria") is not None else None))
    rh_e3 = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO decisions (session_id, signal, kind, question, criteria, "
        " context, request_hash, status) VALUES "
        " (%s, 'intent', 'choice', %s, %s::jsonb, '{}'::jsonb, %s, 'open') "
        " RETURNING decision_id, epoch",
        (sid_e3, item_e3["question"], json.dumps(item_e3["criteria"]), rh_e3))
    oid, oep = cur.fetchone()
    set_mock(cur, mock_from_needed(cur, sid_e3))
    cur.execute("SELECT v13_parse(%s)", (sid_e3,))
    cur.fetchone()
    cur.execute(
        "SELECT epoch, status, answer IS NOT NULL FROM decisions "
        "WHERE decision_id=%s", (oid,))
    ep3, st3, filled3 = cur.fetchone()
    check("E3: mock filled open row", filled3 is True and st3 == "answered",
          (st3, filled3))
    check("E3: epoch unchanged after fill", ep3 == oep)

    cur.execute(
        "INSERT INTO decisions (session_id, signal, kind, question, context, "
        " request_hash, epoch) "
        "VALUES (%s, 'forge-pe', 'noul', 'Forge post-execute question.', "
        " '{}'::jsonb, %s, 'post-execute')",
        (sid_e, "e" * 64))
    cur.execute(
        "SELECT epoch FROM decisions WHERE session_id=%s AND signal='forge-pe'",
        (sid_e,))
    check("E4: explicit post-execute ignored", cur.fetchone()[0] == "pre-bind")
    cur.execute(
        "INSERT INTO decisions (session_id, signal, kind, question, context, "
        " request_hash, template_name, template_version, epoch) "
        "VALUES (%s, 'forge-pe2', 'noul', 'Forge via intent template.', "
        " '{}'::jsonb, %s, 'intent', 1, 'post-execute')",
        (sid_e, "f" * 64))
    cur.execute(
        "SELECT epoch FROM decisions WHERE session_id=%s AND signal='forge-pe2'",
        (sid_e,))
    check("E4: template attribute wins", cur.fetchone()[0] == "pre-bind")
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_e,))
    me4 = cur.fetchone()[0]
    check("E4: judgments still empty", me4["judgments"] == [])
    hsec = json.dumps(me4["sections"])
    cur.execute("DELETE FROM decisions WHERE session_id=%s AND signal='forge-pe'",
                (sid_e,))
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_e,))
    me4b = cur.fetchone()[0]
    check("E4: sections independent of forged row",
          json.dumps(me4b["sections"]) == hsec)

    conn, cur = recycle(server, conn)
    # ----- F G-ctx9 -----
    sid_f = new_session(cur)
    append_user(cur, sid_f, "freeze-f")
    _, _, _, conn, cur = parse_settle(server, conn, cur, sid_f)
    cur.execute(
        "SELECT context_active_artifact FROM sessions WHERE session_id=%s", (sid_f,))
    m1id = cur.fetchone()[0]
    cur.execute("SELECT inline FROM artifacts WHERE artifact_id=%s", (m1id,))
    m1 = cur.fetchone()[0]
    cur.execute(
        "SELECT count(*) FROM decisions WHERE session_id=%s "
        "AND answer IS NOT NULL AND status IN ('answered','cached')", (sid_f,))
    n_f1 = cur.fetchone()[0]
    insert_complete_decision(cur, sid_f, "late-f1")
    cur.execute(
        "SELECT count(*) FROM decisions WHERE session_id=%s "
        "AND answer IS NOT NULL AND status IN ('answered','cached')", (sid_f,))
    check("F1: complete decision added", cur.fetchone()[0] == n_f1 + 1)
    cur.execute("SELECT inline FROM artifacts WHERE artifact_id=%s", (m1id,))
    check("F1: M1 inline frozen", cur.fetchone()[0] == m1)
    fails_with(cur, "UPDATE artifacts SET size=size+1 WHERE artifact_id=%s",
               (m1id,), "append-only", "F1: artifact UPDATE rejected")
    check("F1: judgments empty", m1["judgments"] == [])
    href = sec_map(m1)["history"]["payload_ref"]["content_hash"]
    cur.execute(
        "SELECT inline FROM artifacts WHERE kind='context_section' AND content_hash=%s",
        (href,))
    blob = cur.fetchone()
    check("F1: history blob retrievable", blob is not None)

    sid_f2 = new_session(cur)
    append_user(cur, sid_f2, "stale-f2")
    snapf = answers_sql(cur, sid_f2)
    append_user(cur, sid_f2, "newer")
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid_f2, json.dumps(snapf)))
    check("F2: advance stale", cur.fetchone()[0] == "stale")
    cur.execute("SELECT count(*) FROM effects WHERE session_id=%s", (sid_f2,))
    check("F2: stale zero effects", cur.fetchone()[0] == 0)
    conn, cur = recycle(server, conn)
    snapf2 = answers_sql(cur, sid_f2)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid_f2, json.dumps(snapf2)))
    check("F2: reparse advances", cur.fetchone()[0] in ("waiting", "progressed"))

    # F3 canary
    cur.execute("SELECT pg_get_functiondef('v13_canonical_state(uuid)'::regprocedure)")
    canon_def = cur.fetchone()[0]
    canary = str(uuid.uuid4())
    cur.execute("""
        CREATE OR REPLACE FUNCTION v13_canonical_state(p_sid uuid) RETURNS jsonb
        LANGUAGE sql STABLE AS $c$
          SELECT jsonb_build_object(
            'messages', COALESCE((
              SELECT jsonb_agg(jsonb_build_object('seq', e.seq, 'type', e.type,
                                                  'payload', e.payload) ORDER BY e.seq)
                FROM (SELECT seq, type, payload FROM events
                       WHERE session_id = p_sid
                         AND type IN ('user/message','llm/message','tool/result')
                         AND (seq <= v13_last_user_seq(p_sid)
                              OR (payload->>'origin_user_seq')::bigint
                                 = v13_last_user_seq(p_sid))
                       ORDER BY seq DESC LIMIT 20) e), '[]'::jsonb),
            'derived', jsonb_build_object(
              'message_count', (SELECT count(*) FROM events WHERE session_id = p_sid
                                 AND type IN ('user/message','llm/message','tool/result')
                                 AND (seq <= v13_last_user_seq(p_sid)
                                      OR (payload->>'origin_user_seq')::bigint
                                         = v13_last_user_seq(p_sid)))),
            'tools', COALESCE((
              SELECT jsonb_agg(jsonb_build_object('name', name, 'description', description,
                                                  'kind', kind) ORDER BY name)
                FROM tools WHERE enabled), '[]'::jsonb),
            'sidecar', %s);
        $c$;
    """, (canary,))
    sid_f3 = new_session(cur)
    append_user(cur, sid_f3, "canary")
    cur.execute("SELECT v13_assemble_manifest(%s)::text", (sid_f3,))
    blobtxt = cur.fetchone()[0]
    check("F3: manifest text omits canary", canary not in blobtxt)
    cur.execute(canon_def)
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_f3,))
    check("F3: restored assemble works", cur.fetchone()[0] is not None)

    conn, cur = recycle(server, conn)
    # F4(i-iii) statement snapshot: concurrent complete decision invisible to A
    sid_f4 = new_session(cur)
    append_user(cur, sid_f4, "f4-snap")
    parse(cur, sid_f4)
    cur.execute("SELECT (v13_context_required(%s)->>'dec')::int", (sid_f4,))
    dec_before = cur.fetchone()[0]
    cur.execute("SELECT pg_get_functiondef('v13_canonical_state(uuid)'::regprocedure)")
    canon_f4 = cur.fetchone()[0]
    conn, cur = recycle(server, conn)
    cur.execute(CANON_PAUSE_SQL.format(lock=879041))
    conn, cur = recycle(server, conn)
    cur.execute("SELECT pg_advisory_lock(879041)")
    box_f4 = {}

    def run_assemble_f4():
        c = psycopg2.connect(server.get_uri(DB))
        k = c.cursor()
        guc(k)
        k.execute("SELECT pg_backend_pid()")
        box_f4["pid"] = k.fetchone()[0]
        try:
            k.execute("SELECT v13_assemble_manifest(%s)", (sid_f4,))
            box_f4["m"] = k.fetchone()[0]
            c.commit()
        except Exception as exc:
            box_f4["err"] = str(exc)
        c.close()

    ta4 = threading.Thread(target=run_assemble_f4)
    ta4.start()
    check("F4: assemble blocked in snapshot", wait_box_lock(cur, box_f4))
    cB4 = psycopg2.connect(server.get_uri(DB))
    kB4 = cB4.cursor()
    did_f4 = insert_complete_decision(kB4, sid_f4, "f4inj")
    cB4.commit()
    cB4.close()
    cur.execute("SELECT pg_advisory_unlock(879041)")
    ta4.join(15)
    check("F4: assemble completed", "m" in box_f4, box_f4)
    mA4 = box_f4["m"]
    dec_a = mA4["required_revision"]["dec"]
    check("F4: A token.dec excludes concurrent row", int(dec_a) == dec_before,
          (dec_a, dec_before))
    jids = {str(j.get("decision_id")) for j in (mA4.get("judgments") or [])}
    check("F4: A judgments omit concurrent decision", str(did_f4) not in jids, jids)
    cur.execute(canon_f4)
    conn, cur = recycle(server, conn)
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_f4,))
    mA4b = cur.fetchone()[0]
    check("F4: after A commit token.dec includes row",
          int(mA4b["required_revision"]["dec"]) == dec_before + 1,
          mA4b["required_revision"]["dec"])

    # F4(iv) settle window: B append_event blocks on sessions row lock
    sid_f4iv = new_session(cur)
    append_user(cur, sid_f4iv, "f4iv")
    a, eid4iv, _ = hang_refresh(cur, sid_f4iv)
    ck4iv = claim_pinned(cur, eid4iv)
    cur.execute("SELECT v13_last_user_seq(%s)", (sid_f4iv,))
    origin4 = cur.fetchone()[0]
    conn, cur = recycle(server, conn)
    box_b4 = {}

    def run_append_f4iv():
        c = psycopg2.connect(server.get_uri(DB))
        k = c.cursor()
        k.execute("SELECT pg_backend_pid()")
        box_b4["pid"] = k.fetchone()[0]
        try:
            k.execute(
                "SELECT v13_append_event(%s, %s, 'llm/message', %s::jsonb)",
                (sid_f4iv, u(), json.dumps(
                    {"text": "f4iv-concurrent", "origin_user_seq": origin4})))
            box_b4["seq"] = k.fetchone()[0]
            c.commit()
        except Exception as exc:
            box_b4["err"] = str(exc)
        c.close()

    cA4 = psycopg2.connect(server.get_uri(DB))
    kA4 = cA4.cursor()
    guc(kA4)
    kA4.execute("SELECT 1 FROM sessions WHERE session_id=%s FOR UPDATE",
                (sid_f4iv,))
    kA4.execute("SELECT 1 FROM v13_tools_meta WHERE singleton FOR UPDATE")
    kA4.execute(
        "SELECT 1 FROM v13_policies "
        "WHERE name IN ('assemble_manifest','generation','judgment_defaults') "
        "AND active ORDER BY name FOR UPDATE")
    tb4 = threading.Thread(target=run_append_f4iv)
    tb4.start()
    check("F4(iv): B blocked on sessions lock", wait_box_lock(cur, box_b4))
    kA4.execute("SELECT v13_refresh_context(%s,%s,%s)",
                (eid4iv, ck4iv["attempt_no"], ck4iv["fence"]))
    out4iv = kA4.fetchone()[0]
    check("F4(iv): A settle accepted (belt, zero V3003)", out4iv == "accepted",
          out4iv)
    cA4.commit()
    cA4.close()
    tb4.join(15)
    check("F4(iv): B appended after A commit", "seq" in box_b4, box_b4)
    conn, cur = recycle(server, conn)
    cur.execute("SELECT v13_context_fresh(%s)", (sid_f4iv,))
    check("F4(iv): fresh=false after B event", cur.fetchone()[0] is False)

    conn, cur = recycle(server, conn)
    # F5 replay/stale/failed
    sid_f5 = new_session(cur)
    append_user(cur, sid_f5, "f5")
    _, eid5, _ = hang_refresh(cur, sid_f5)
    out1, ck5 = settle(cur, eid5)
    check("F5: first accepted", out1 == "accepted")
    conn, cur = recycle(server, conn)
    cur.execute("SELECT count(*) FROM artifacts WHERE kind='context'")
    nctx = cur.fetchone()[0]
    cur.execute(
        "SELECT v13_refresh_context(%s,%s,%s)",
        (eid5, ck5["attempt_no"], ck5["fence"]))
    check("F5: repeat replay", cur.fetchone()[0] == "replay")
    cur.execute("SELECT count(*) FROM artifacts WHERE kind='context'")
    check("F5: artifacts not grown", cur.fetchone()[0] == nctx)
    cur.execute(
        "SELECT v13_refresh_context(%s,%s,%s)",
        (eid5, ck5["attempt_no"] + 1, ck5["fence"]))
    check("F5: bad token stale", cur.fetchone()[0] == "stale")

    v = seed_asm()
    v["est_bytes_per_token"] = 0
    bump_policy(cur, "assemble_manifest", v)
    sid_f5b = new_session(cur)
    append_user(cur, sid_f5b, "f5fail")
    a, eidf, _ = hang_refresh(cur, sid_f5b)
    ckf = claim_pinned(cur, eidf)
    fails_with(cur, "SELECT v13_refresh_context(%s,%s,%s)",
               (eidf, ckf["attempt_no"], ckf["fence"]),
               "V3003", "F5: zero divisor V3003", pgcode="V3003")
    cur.execute(
        "SELECT v13_complete(%s,%s,%s,'failed', '{}'::jsonb)",
        (eidf, ckf["attempt_no"], ckf["fence"]))
    check("F5: worker complete failed", cur.fetchone()[0] == "accepted")
    restore_asm(cur)

    conn, cur = recycle(server, conn)
    # F6 settle||settle
    sid_f6 = new_session(cur)
    append_user(cur, sid_f6, "f6")
    snap6 = answers_sql(cur, sid_f6)
    a, eid6, _ = hang_refresh(cur, sid_f6, snap6)
    ck6 = claim_pinned(cur, eid6)
    conn.commit()
    box6 = {}

    def run_settle(key):
        c = psycopg2.connect(server.get_uri(DB))
        k = c.cursor()
        guc(k)
        try:
            k.execute("SELECT v13_refresh_context(%s,%s,%s)",
                      (eid6, ck6["attempt_no"], ck6["fence"]))
            box6[key] = k.fetchone()[0]
            c.commit()
        except psycopg2.Error as exc:
            box6[key] = f"ERR:{exc.pgcode}:{exc}"
            c.rollback()
        c.close()

    t1 = threading.Thread(target=run_settle, args=("a",))
    t2 = threading.Thread(target=run_settle, args=("b",))
    t1.start(); t2.start()
    t1.join(30); t2.join(30)
    check("F6: both returned", "a" in box6 and "b" in box6, box6)
    check("F6: no deadlock",
          all(not str(v).startswith("ERR:40P01") for v in box6.values()), box6)
    vals = {box6["a"], box6["b"]}
    check("F6: one accepted one replay",
          vals == {"accepted", "replay"}, box6)
    conn, cur = recycle(server, conn)

    # F6(ii) settle || complete(failed)
    sid_f6ii = new_session(cur)
    append_user(cur, sid_f6ii, "f6ii")
    a, eid6ii, _ = hang_refresh(cur, sid_f6ii)
    ck6ii = claim_pinned(cur, eid6ii)
    conn.commit()
    box6ii = {}

    def run_refresh_ii():
        c = psycopg2.connect(server.get_uri(DB))
        k = c.cursor()
        guc(k)
        try:
            k.execute("SELECT v13_refresh_context(%s,%s,%s)",
                      (eid6ii, ck6ii["attempt_no"], ck6ii["fence"]))
            box6ii["a"] = k.fetchone()[0]
            c.commit()
        except psycopg2.Error as exc:
            box6ii["a"] = f"ERR:{exc.pgcode}:{exc}"
            c.rollback()
        c.close()

    def run_complete_ii():
        c = psycopg2.connect(server.get_uri(DB))
        k = c.cursor()
        guc(k)
        try:
            k.execute(
                "SELECT v13_complete(%s,%s,%s,'failed', '{}'::jsonb)",
                (eid6ii, ck6ii["attempt_no"], ck6ii["fence"]))
            box6ii["b"] = k.fetchone()[0]
            c.commit()
        except psycopg2.Error as exc:
            box6ii["b"] = f"ERR:{exc.pgcode}:{exc}"
            c.rollback()
        c.close()

    t6a = threading.Thread(target=run_refresh_ii)
    t6b = threading.Thread(target=run_complete_ii)
    t6a.start(); t6b.start()
    t6a.join(30); t6b.join(30)
    check("F6(ii): both returned", "a" in box6ii and "b" in box6ii, box6ii)
    check("F6(ii): no deadlock",
          all(not str(v).startswith("ERR:40P01") for v in box6ii.values()),
          box6ii)
    vals_ii = {box6ii["a"], box6ii["b"]}
    check("F6(ii): one accepted, other replay/stale",
          "accepted" in vals_ii
          and vals_ii <= {"accepted", "replay", "stale"},
          box6ii)
    conn, cur = recycle(server, conn)
    cur.execute("SELECT status FROM effects WHERE effect_id=%s", (eid6ii,))
    st_ii = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM artifacts WHERE produced_by=%s", (eid6ii,))
    nart_ii = cur.fetchone()[0]
    cur.execute(
        "SELECT context_active_artifact FROM sessions WHERE session_id=%s",
        (sid_f6ii,))
    ptr_ii = cur.fetchone()[0]
    if st_ii == "succeeded":
        check("F6(ii): A-win has artifact+pointer",
              nart_ii >= 1 and ptr_ii is not None, (nart_ii, ptr_ii))
        check("F6(ii): B replay when A wins", box6ii["b"] == "replay", box6ii)
    elif st_ii == "failed":
        check("F6(ii): B-win zero artifacts", nart_ii == 0, nart_ii)
        check("F6(ii): A replay/stale when B wins",
              box6ii["a"] in ("replay", "stale"), box6ii)
    else:
        check("F6(ii): terminal status unique", False, st_ii)

    # F6(iii) settle || policy flip: B blocks on policy row lock
    cur.execute(
        "SELECT version FROM v13_policies "
        "WHERE name='assemble_manifest' AND active")
    old_asm = cur.fetchone()[0]
    sid_f6iii = new_session(cur)
    append_user(cur, sid_f6iii, "f6iii")
    a, eid6iii, _ = hang_refresh(cur, sid_f6iii)
    ck6iii = claim_pinned(cur, eid6iii)
    cur.execute("SELECT pg_get_functiondef('v13_canonical_state(uuid)'::regprocedure)")
    canon_f6 = cur.fetchone()[0]
    conn, cur = recycle(server, conn)
    cur.execute(CANON_PAUSE_SQL.format(lock=879061))
    conn, cur = recycle(server, conn)
    cur.execute("SELECT pg_advisory_lock(879061)")
    box6a = {}
    box6b = {}

    def run_settle_iii():
        c = psycopg2.connect(server.get_uri(DB))
        k = c.cursor()
        guc(k)
        k.execute("SELECT pg_backend_pid()")
        box6a["pid"] = k.fetchone()[0]
        try:
            k.execute("SELECT v13_refresh_context(%s,%s,%s)",
                      (eid6iii, ck6iii["attempt_no"], ck6iii["fence"]))
            box6a["r"] = k.fetchone()[0]
            c.commit()
        except psycopg2.Error as exc:
            box6a["r"] = f"ERR:{exc.pgcode}:{exc}"
            c.rollback()
        c.close()

    def run_flip_iii():
        c = psycopg2.connect(server.get_uri(DB))
        k = c.cursor()
        k.execute("SELECT pg_backend_pid()")
        box6b["pid"] = k.fetchone()[0]
        try:
            k.execute(
                "SELECT 1 FROM v13_policies "
                "WHERE name='assemble_manifest' AND active FOR UPDATE")
            bump_policy(k, "assemble_manifest", seed_asm())
            box6b["ok"] = True
            c.commit()
        except psycopg2.Error as exc:
            box6b["err"] = f"ERR:{exc.pgcode}:{exc}"
            c.rollback()
        c.close()

    t6s = threading.Thread(target=run_settle_iii, daemon=True)
    t6s.start()
    try:
        check("F6(iii): A blocked in assemble", wait_box_lock(cur, box6a), box6a)
        t6f = threading.Thread(target=run_flip_iii, daemon=True)
        t6f.start()
        blocked_b = wait_box_lock(cur, box6b)
        check("F6(iii): B blocked on policy lock", blocked_b, box6b)
    finally:
        cur.execute("SELECT pg_advisory_unlock(879061)")
    t6s.join(30); t6f.join(30)
    check("F6(iii): A accepted", box6a.get("r") == "accepted", box6a)
    check("F6(iii): B flip completed", box6b.get("ok") is True, box6b)
    cur.execute(canon_f6)
    conn, cur = recycle(server, conn)
    cur.execute(
        "SELECT inline->'policy'->>'assemble_version' FROM artifacts a "
        "JOIN effects e ON e.effect_id=a.produced_by "
        "WHERE e.effect_id=%s AND a.kind='context'", (eid6iii,))
    landed_ver = cur.fetchone()
    check("F6(iii): A manifest used old policy version",
          landed_ver is not None and int(landed_ver[0]) == old_asm, landed_ver)
    cur.execute("SELECT v13_context_fresh(%s)", (sid_f6iii,))
    check("F6(iii): fresh=false after policy flip", cur.fetchone()[0] is False)
    restore_asm(cur)
    conn, cur = recycle(server, conn)

    # ----- G remaining -----
    fails_with(cur, "UPDATE artifacts SET size=size+1 WHERE kind='context'",
               (), "append-only", "G1: artifacts UPDATE rejected")
    cur.execute(
        "SELECT effect_id FROM effects WHERE kind='context_refresh' "
        "AND status='succeeded' LIMIT 1")
    seid = cur.fetchone()[0]
    cur.execute(
        "SELECT effect_id FROM effects WHERE status='claimed' LIMIT 1")
    # claimed may be none; use a failed one by claiming new
    sid_g1 = new_session(cur)
    append_user(cur, sid_g1, "g1")
    a, eidg, _ = hang_refresh(cur, sid_g1)
    ck = claim_pinned(cur, eidg)
    fails_with(
        cur,
        "INSERT INTO artifacts (content_hash, kind, inline, size, produced_by) "
        "VALUES (%s, 'context', '{}'::jsonb, 2, %s)",
        ("a" * 64, eidg), "succeeded", "G1: claimed produced_by rejected")
    cur.execute(
        "SELECT produced_by FROM artifacts WHERE kind='context' LIMIT 1")
    pb = cur.fetchone()[0]
    cur.execute("SELECT status FROM effects WHERE effect_id=%s", (pb,))
    check("G1: context produced_by succeeded", cur.fetchone()[0] == "succeeded")
    cur.execute(
        "SELECT content_hash = encode(digest(inline::text,'sha256'),'hex') "
        "AND size = octet_length(inline::text) FROM artifacts WHERE kind='context' "
        "LIMIT 1")
    check("G1: hash/size selfcheck", cur.fetchone()[0] is True)
    cur.execute(
        "SELECT context_active_artifact FROM sessions "
        "WHERE context_active_artifact IS NOT NULL LIMIT 1")
    good = cur.fetchone()[0]
    cur.execute(
        "SELECT artifact_id FROM artifacts WHERE kind='context_section' LIMIT 1")
    blob_id = cur.fetchone()[0]
    cur.execute("SELECT session_id FROM sessions WHERE context_active_artifact=%s",
                (good,))
    sid_ptr = cur.fetchone()[0]
    fails_with(cur,
               "UPDATE sessions SET context_active_artifact=%s WHERE session_id=%s",
               (blob_id, sid_ptr), "kind", "G1: pointer to blob rejected")
    fails_with(cur,
               "UPDATE sessions SET context_active_artifact=%s WHERE session_id=%s",
               (str(uuid.uuid4()), sid_ptr), "kind",
               "G1: random uuid rejected")
    cur.execute(
        "UPDATE sessions SET context_active_artifact=NULL WHERE session_id=%s",
        (sid_ptr,))
    cur.execute(
        "SELECT context_active_artifact FROM sessions WHERE session_id=%s",
        (sid_ptr,))
    check("G1: pointer NULL allowed", cur.fetchone()[0] is None)
    cur.execute(
        "UPDATE sessions SET context_active_artifact=%s WHERE session_id=%s",
        (good, sid_ptr))

    conn, cur = recycle(server, conn)
    sid_g1r = new_session(cur)
    append_user(cur, sid_g1r, "g1-replay")
    _, _, _, conn, cur = parse_settle(server, conn, cur, sid_g1r)
    cur.execute("SELECT v13_goal_hash(%s)", (sid_g1r,))
    gh1 = cur.fetchone()[0]
    cur.execute(
        "SELECT v13_enqueue_effect(%s, 'context_refresh', %s::jsonb)",
        (sid_g1r, json.dumps({"goal_hash": gh1, "nonce": u()})))
    eid_g1r = cur.fetchone()[0]
    out_g1r, _ = settle(cur, eid_g1r)
    check("G1: second zero-change settle accepted", out_g1r == "accepted")
    cur.execute(
        "SELECT a.inline FROM artifacts a "
        "JOIN effects e ON e.effect_id=a.produced_by "
        "WHERE e.session_id=%s AND a.kind='context' "
        "ORDER BY a.created_at", (sid_g1r,))
    ctx_rows = [r[0] for r in cur.fetchall()]
    check("G1: two context artifacts", len(ctx_rows) >= 2, len(ctx_rows))
    check("G1: inline-replay byte-equal across zero-change settles",
          minus_replay(ctx_rows[-2]) == minus_replay(ctx_rows[-1]))

    conn, cur = recycle(server, conn)
    v = seed_asm()
    v["inline_max_bytes"] = 64
    bump_policy(cur, "assemble_manifest", v)
    sid_g2 = new_session(cur)
    append_user(cur, sid_g2, "g2-inline-" + ("x" * 200))
    a, eid2, _ = hang_refresh(cur, sid_g2)
    ck2 = claim_pinned(cur, eid2)
    cur.execute("SELECT status FROM effects WHERE effect_id=%s", (eid2,))
    st_before = cur.fetchone()[0]
    fails_with(cur, "SELECT v13_refresh_context(%s,%s,%s)",
               (eid2, ck2["attempt_no"], ck2["fence"]),
               "V3003", "G2: inline overflow V3003", pgcode="V3003")
    cur.execute("SELECT status FROM effects WHERE effect_id=%s", (eid2,))
    check("G2: still claimed", cur.fetchone()[0] == st_before)
    cur.execute(
        "SELECT count(*) FROM events WHERE type='effect_done' "
        "AND payload->>'effect_id' = %s", (str(eid2),))
    check("G2: zero effect_done", cur.fetchone()[0] == 0)
    cur.execute("SELECT result FROM effects WHERE effect_id=%s", (eid2,))
    check("G2: zero result write", cur.fetchone()[0] is None)
    cur.execute(
        "SELECT count(*) FROM artifacts a WHERE produced_by=%s", (eid2,))
    check("G2: zero artifacts", cur.fetchone()[0] == 0)
    restore_asm(cur)

    fails_with(
        cur,
        "INSERT INTO decisions (session_id, signal, kind, question, context, "
        " request_hash, template_name, template_version) "
        "VALUES (%s, 'miss', 'noul', 'Missing template question.', "
        " '{}'::jsonb, %s, 'nope', 99)",
        (sid_g2, "1" * 64),
        "V3002", "G3: hanging template V3002", pgcode="V3002")

    cur.execute(
        "SELECT has_function_privilege('public', "
        "'v13_refresh_context(uuid,integer,bigint)', 'EXECUTE')")
    check("G4: PUBLIC no refresh", cur.fetchone()[0] is False)
    for fn in (
            "v13_goal_hash(uuid)", "v13_context_required(uuid)",
            "v13_prefix_identity(uuid)", "v13_latch_digest(uuid)",
            "v13_manifest_validate(jsonb)", "v13_judgment_defaults_check(jsonb)",
            "v13_assemble_manifest(uuid,integer)",
            "v13_refresh_context(uuid,integer,bigint)",
            "v13_artifact_land(uuid,text,jsonb)", "v13_blob_land(uuid,jsonb)",
            "v13_replay(uuid)"):
        cur.execute("SELECT has_function_privilege('public', %s, 'EXECUTE')", (fn,))
        check(f"G4: PUBLIC no {fn.split('(')[0]}", cur.fetchone()[0] is False)
    cur.execute("SELECT current_user")
    owner = cur.fetchone()[0]
    for fn in ("v13_artifact_land(uuid,text,jsonb)",
               "v13_blob_land(uuid,jsonb)",
               "v13_goal_project()"):
        cur.execute("SELECT has_function_privilege(%s, %s, 'EXECUTE')", (owner, fn))
        check(f"G4: owner has {fn.split('(')[0]}", cur.fetchone()[0] is True)
        for role in ("v13_route", "v13_resolve", "v13_recall"):
            cur.execute("SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, fn))
            check(f"G4: {role} no {fn.split('(')[0]}", cur.fetchone()[0] is False)
    cur.execute("SAVEPOINT sp_g4")
    cur.execute("SET ROLE v13_route")
    cur.execute("SELECT has_function_privilege('v13_route', "
                "'v13_refresh_context(uuid,integer,bigint)', 'EXECUTE')")
    check("G4: route EXECUTE refresh", cur.fetchone()[0] is True)
    try:
        cur.execute(
            "INSERT INTO v13_goals (session_id, seq, content_hash, payload) "
            "VALUES (%s, 0, 'x', '{}'::jsonb)", (sid_g2,))
        check("G4: route INSERT goals denied", False)
    except psycopg2.Error as exc:
        check("G4: route INSERT goals denied",
              exc.pgcode == "42501" or "permission" in str(exc).lower(),
              exc.pgcode)
        cur.execute("ROLLBACK TO SAVEPOINT sp_g4")
    cur.execute("RESET ROLE")
    conn, cur = recycle(server, conn)
    cur.execute(
        "SELECT has_function_privilege('v13_resolve', "
        "'v13_refresh_context(uuid,integer,bigint)', 'EXECUTE')")
    check("G4: resolve no refresh", cur.fetchone()[0] is False)
    cur.execute(
        "SELECT has_function_privilege('v13_resolve', "
        "'v13_assemble_manifest(uuid,integer)', 'EXECUTE')")
    check("G4: resolve assemble", cur.fetchone()[0] is True)
    cur.execute(
        "SELECT has_function_privilege('v13_route', "
        "'v13_judgment_defaults_check(jsonb)', 'EXECUTE')")
    check("G4: route no defaults_check", cur.fetchone()[0] is False)
    for fn in (
            "v13_goals_append_only()", "v13_goal_project()",
            "v13_artifacts_append_only()", "v13_artifacts_effect_guard()",
            "v13_ctx_ptr_guard()", "v13_decisions_epoch_fill()",
            "v13_epoch_frozen()"):
        cur.execute("SELECT has_function_privilege('public', %s, 'EXECUTE')", (fn,))
        check(f"G4: PUBLIC no trigger {fn.split('(')[0]}", cur.fetchone()[0] is False)
    for fn, role_ok in (
            ("v13_context_fresh(uuid)", "v13_route"),
            ("v13_probe(uuid)", "v13_route"),
            ("v13_judgment_envelope(uuid)", "v13_route")):
        cur.execute("SELECT has_function_privilege('public', %s, 'EXECUTE')", (fn,))
        check(f"G4: PUBLIC no OR REPLACE {fn.split('(')[0]}",
              cur.fetchone()[0] is False)
        cur.execute("SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                    (role_ok, fn))
        check(f"G4: {role_ok} kept {fn.split('(')[0]} after OR REPLACE",
              cur.fetchone()[0] is True)

    rconn = connect_as(server, "v13_route_login")
    rc = rconn.cursor()
    guc(rc)
    sid_g5 = new_session(cur)
    append_user(cur, sid_g5, "g5")
    snapg5 = answers_sql(cur, sid_g5)
    a, eid5, _ = hang_refresh(cur, sid_g5, snapg5)
    ck5 = claim_pinned(cur, eid5)
    conn, cur = recycle(server, conn)
    rc.execute("SELECT v13_refresh_context(%s,%s,%s)",
               (eid5, ck5["attempt_no"], ck5["fence"]))
    check("G5: route_login settle", rc.fetchone()[0] == "accepted")
    try:
        rc.execute("SET ROLE v13_resolve")
        check("G5: SET ROLE resolve denied", False)
    except psycopg2.Error as exc:
        check("G5: SET ROLE resolve denied",
              "permission" in str(exc).lower(), str(exc).splitlines()[0])
        rconn.rollback()
    rconn.close()
    cur.execute(
        "SELECT has_function_privilege('v13_resolve', "
        "'v13_refresh_context(uuid,integer,bigint)', 'EXECUTE')")
    check("G5: resolve EXECUTE false", cur.fetchone()[0] is False)

    # G8 llm provenance — no ready llm is an immediate fail
    sid_g8 = new_session(cur)
    last8 = append_user(cur, sid_g8, "write a poem please")
    _, _, _, conn, cur = parse_settle(server, conn, cur, sid_g8, **{
        "intent": {"type": "choice", "choice": "llm_generate",
                   "probabilities": {"llm_generate": 0.9}, "confidence": 0.9},
        "gate_action": {"type": "noul", "noul": 0.1},
        "gate_off_topic": {"type": "noul", "noul": 0.1},
        "risk": {"type": "score", "score": 0.5, "confidence": 0.9},
    })
    conn, cur = recycle(server, conn)
    snap8 = answers_llm(cur, sid_g8)
    poison(cur)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid_g8, json.dumps(snap8)))
    a8 = cur.fetchone()[0]
    cur.execute(
        "SELECT effect_id FROM effects WHERE session_id=%s AND kind='llm' "
        "AND status='ready'", (sid_g8,))
    lrow = cur.fetchone()
    check("G8: llm effect ready", lrow is not None, a8)
    cur.execute(
        "SELECT context_active_artifact FROM sessions WHERE session_id=%s",
        (sid_g8,))
    art = cur.fetchone()[0]
    ck = claim_pinned(cur, lrow[0])
    cur.execute(
        "SELECT v13_complete(%s,%s,%s,'succeeded', %s::jsonb)",
        (lrow[0], ck["attempt_no"], ck["fence"],
         json.dumps({"text": "verse", "context_artifact_id": str(art)})))
    check("G8: llm complete", cur.fetchone()[0] == "accepted")
    cur.execute(
        "SELECT payload ? 'context_artifact_id' FROM events "
        "WHERE session_id=%s AND type='llm/message' "
        "ORDER BY seq DESC LIMIT 1", (sid_g8,))
    check("G8: llm/message has context_artifact_id", cur.fetchone()[0] is True)
    cur.execute("SELECT result ? 'context_artifact_id' FROM effects "
                "WHERE effect_id=%s", (lrow[0],))
    check("G8: effect.result has artifact", cur.fetchone()[0] is True)

    # G9 full chain: llm → ② settle → finish(terminal) → extra refresh
    sid_g9 = new_session(cur)
    last9 = append_user(cur, sid_g9, "write a short poem")
    _, _, _, conn, cur = parse_settle(server, conn, cur, sid_g9, **{
        "intent": {"type": "choice", "choice": "llm_generate",
                   "probabilities": {"llm_generate": 0.9}, "confidence": 0.9},
        "gate_action": {"type": "noul", "noul": 0.1},
        "gate_off_topic": {"type": "noul", "noul": 0.1},
        "risk": {"type": "score", "score": 0.5, "confidence": 0.9},
    })
    conn, cur = recycle(server, conn)
    snap9 = answers_llm(cur, sid_g9)
    poison(cur)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid_g9, json.dumps(snap9)))
    a9w = cur.fetchone()[0]
    cur.execute(
        "SELECT effect_id FROM effects WHERE session_id=%s AND kind='llm' "
        "AND status='ready'", (sid_g9,))
    l9 = cur.fetchone()
    check("G9: llm effect ready", l9 is not None, a9w)
    ck = claim_pinned(cur, l9[0])
    cur.execute(
        "SELECT v13_complete(%s,%s,%s,'succeeded', %s::jsonb)",
        (l9[0], ck["attempt_no"], ck["fence"], json.dumps({"text": "done"})))
    check("G9: llm complete", cur.fetchone()[0] == "accepted")
    conn, cur = recycle(server, conn)
    snap9b = answers_llm(cur, sid_g9)
    poison(cur)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid_g9, json.dumps(snap9b)))
    a9r = cur.fetchone()[0]
    check("G9: ② after llm/message", a9r == "waiting", a9r)
    cur.execute(
        "SELECT effect_id FROM effects WHERE session_id=%s "
        "AND kind='context_refresh' AND status='ready'", (sid_g9,))
    eid9r = cur.fetchone()
    check("G9: refresh ready after llm", eid9r is not None)
    out9r, _ = settle(cur, eid9r[0])
    check("G9: post-llm settle accepted", out9r == "accepted")
    conn, cur = recycle(server, conn)
    snap9c = answers_llm(cur, sid_g9)
    poison(cur)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid_g9, json.dumps(snap9c)))
    a9 = cur.fetchone()[0]
    check("G9: chain terminal", a9 == "terminal", a9)
    conn, cur = recycle(server, conn)
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s AND type='turn/route'",
                (sid_g9,))
    routes = cur.fetchone()[0]
    _, _, _, conn, cur = parse_settle(server, conn, cur, sid_g9)
    cur.execute(
        "SELECT inline FROM artifacts a JOIN sessions s "
        "ON s.context_active_artifact=a.artifact_id WHERE s.session_id=%s",
        (sid_g9,))
    m9 = cur.fetchone()[0]
    href = sec_map(m9)["history"]["payload_ref"]["content_hash"]
    cur.execute(
        "SELECT inline::text FROM artifacts "
        "WHERE kind='context_section' AND content_hash=%s", (href,))
    hist_txt = cur.fetchone()[0]
    check("G9: history has this-turn llm/message",
          "llm/message" in hist_txt and "done" in hist_txt, hist_txt[:240])
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s AND type='turn/route'",
                (sid_g9,))
    check("G9: refresh does not add turn/route", cur.fetchone()[0] == routes)

    # G10 blob freeze
    sid_g10 = new_session(cur)
    append_user(cur, sid_g10, "blob-g10")
    _, _, _, conn, cur = parse_settle(server, conn, cur, sid_g10)
    cur.execute(
        "SELECT context_active_artifact FROM sessions WHERE session_id=%s",
        (sid_g10,))
    m1id = cur.fetchone()[0]
    cur.execute("SELECT inline FROM artifacts WHERE artifact_id=%s", (m1id,))
    mg1 = cur.fetchone()[0]
    h1 = sec_map(mg1)["history"]["content_hash"]
    cur.execute(
        "SELECT inline FROM artifacts WHERE kind='context_section' AND content_hash=%s",
        (h1,))
    old_hist = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM artifacts WHERE kind='context_section'")
    nblob = cur.fetchone()[0]
    cur.execute("SELECT v13_last_user_seq(%s)", (sid_g10,))
    origin = cur.fetchone()[0]
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'llm/message', %s::jsonb)",
        (sid_g10, u(), json.dumps({"text": "changed-history",
                                   "origin_user_seq": origin})))
    cur.fetchone()
    cur.execute("UPDATE tools SET enabled=false WHERE name='send_summary_email'")
    v = seed_asm()
    v["budget_tokens"] = 4096
    bump_policy(cur, "assemble_manifest", v)
    _, _, _, conn, cur = parse_settle(server, conn, cur, sid_g10)
    cur.execute("SELECT v13_replay(%s)", (m1id,))
    rp = cur.fetchone()[0]
    rp_body = json.loads(json.dumps(rp)); rp_body.pop("replay", None)
    old_body = json.loads(json.dumps(mg1)); old_body.pop("replay", None)
    check("G10: M1 replay body unchanged", rp_body == old_body)
    cur.execute(
        "SELECT inline FROM artifacts WHERE kind='context_section' AND content_hash=%s",
        (h1,))
    check("G10: old history blob bytes", cur.fetchone()[0] == old_hist)
    cur.execute(
        "SELECT context_active_artifact FROM sessions WHERE session_id=%s",
        (sid_g10,))
    m2id = cur.fetchone()[0]
    cur.execute("SELECT inline FROM artifacts WHERE artifact_id=%s", (m2id,))
    mg2 = cur.fetchone()[0]
    h2 = sec_map(mg2)["history"]["content_hash"]
    check("G10: new history hash", h2 != h1)
    sm1, sm2 = sec_map(mg1), sec_map(mg2)
    changed = 0
    for sid, s in sm1.items():
        if sid not in sm2 or sm2[sid]["content_hash"] != s["content_hash"]:
            changed += 1
    for sid in sm2:
        if sid not in sm1:
            changed += 1
    cur.execute("SELECT count(*) FROM artifacts WHERE kind='context_section'")
    nblob2 = cur.fetchone()[0]
    check("G10: new blobs = changed sections",
          nblob2 - nblob == changed, (nblob, nblob2, changed))
    _, _, _, conn, cur = parse_settle(server, conn, cur, sid_g10)
    cur.execute("SELECT count(*) FROM artifacts WHERE kind='context_section'")
    check("G10: zero-change settle no new blobs", cur.fetchone()[0] == nblob2)
    cur.execute("UPDATE tools SET enabled=true WHERE name='send_summary_email'")
    restore_asm(cur)

    conn, cur = recycle(server, conn)
    conn.close()
    print("[manifest] ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
