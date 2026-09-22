"""DP6 gate M1: existence-Noul gate + per-chunk Score + cross-session reuse
+ judgment_defaults.points (filter pipeline). Groups A-H.

Run: uv run python v13/filter/test_filter.py  (exit 0 = pass)
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
from v13.filter.setup_db import DB, main as setup_db
from v13.load import SQL_LOAD_ORDER, files_through

HEX64 = re.compile(r"^[0-9a-f]{64}$")
ENV19 = {
    "sid", "ctx", "needed", "candidate_set_hash", "goal_hash",
    "provider", "model", "route_policy_name", "route_policy_version",
    "tools_revision", "tools_catalog", "candidate_generation_revision",
    "session_version", "max_event_seq", "needed_count",
    "templates", "groups", "timeout_ms", "budget",
}
ENV20 = ENV19 | {"candidates"}
CAND4 = {"content_hash", "bm25", "spans", "decision_id"}
FILTER_TEMPLATES = ("chunk_score", "corpus_exists")
PARSE7 = {"snap", "envelope", "abandon", "asked_questions",
          "asked_batches", "remaining", "failed"}
CORPUS_Q = ("Given `state.query` (the user request) and `state.chunks` "
            "(the retrieved passages), does the corpus contain information "
            "that can answer the request?")
SCORE_Q = ("Given `state.query` (the user request), rate how relevant the "
           "passage in `state.chunks` keyed by this question signal is to "
           "answering the request.")
SCORE_CRITERIA = [
    "Not relevant: unrelated to the request.",
    "Marginally relevant: touches the topic but does not help answer.",
    "Relevant: supports a partial answer.",
    "Directly relevant: contains content that directly answers the request."]

CORPUS_EXISTS = "corpus_exists"


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    extra = f": {detail}" if detail and (not condition or len(str(detail)) < 220) else ""
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
        msg_ok = needle.lower() in str(exc).lower() if needle else True
        code_ok = exc.pgcode == pgcode if pgcode else True
        check(label, msg_ok and code_ok,
              f"pgcode={exc.pgcode} {str(exc).splitlines()[0]}")
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        return exc
    cur.execute("ROLLBACK TO SAVEPOINT sp")
    raise AssertionError(
        f"{label}: expected failure containing {needle!r} pgcode={pgcode!r}")


def strip_sql_comments(src: str) -> str:
    out = []
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch == "$":
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            if j < n and src[j] == "$":
                tag = src[i:j + 1]
                k = src.find(tag, j + 1)
                if k < 0:
                    out.append(src[i:])
                    break
                out.append(src[i:k + len(tag)])
                i = k + len(tag)
                continue
        if ch == "'":
            out.append("'")
            i += 1
            while i < n:
                if src[i] == "'":
                    out.append("'")
                    if i + 1 < n and src[i + 1] == "'":
                        out.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                out.append(src[i])
                i += 1
            continue
        if ch == '"':
            out.append('"')
            i += 1
            while i < n:
                if src[i] == '"':
                    out.append('"')
                    i += 1
                    break
                out.append(src[i])
                i += 1
            continue
        if ch == "-" and i + 1 < n and src[i + 1] == "-":
            while i < n and src[i] != "\n":
                i += 1
            out.append(" ")
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "*":
            i += 2
            depth = 1
            while i < n and depth:
                if src[i] == "/" and i + 1 < n and src[i + 1] == "*":
                    depth += 1
                    i += 2
                    continue
                if src[i] == "*" and i + 1 < n and src[i + 1] == "/":
                    depth -= 1
                    i += 2
                    continue
                i += 1
            out.append(" ")
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def connect_as(server, user):
    uri = server.get_uri(DB)
    host = (parse_qs(urlparse(uri).query).get("host") or [None])[0]
    return psycopg2.connect(host=host, dbname=DB, user=user)


def guc(cur):
    # provider is a placeholder GUC (unregistered by pg_typesafe): it can
    # only be written on connections that have not yet loaded the extension
    # library (i.e. before any typesafe_ask). Session-scoped so it survives
    # commits on that connection.
    cur.execute("RESET ROLE")
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


class Conns:
    """Connection manager: typesafe.provider is a placeholder GUC that is
    PURGED when the extension library loads (first typesafe_ask on the
    connection) and cannot be re-set afterward (reserved prefix). Any
    connection that has asked can never build another envelope -> ensure()
    detects the purged provider and recycles to a fresh connection."""

    def __init__(self, server):
        self.server = server
        self.conn = None
        self.cur = None
        self.open_fresh()

    def open_fresh(self):
        if self.conn is not None:
            try:
                self.conn.commit()
            except Exception:
                self.conn.rollback()
            self.conn.close()
        self.conn = psycopg2.connect(self.server.get_uri(DB))
        self.conn.autocommit = False
        self.cur = self.conn.cursor()
        guc(self.cur)

    def ensure(self):
        self.cur.execute(
            "SELECT coalesce(current_setting('typesafe.provider', true), '')")
        if not self.cur.fetchone()[0]:
            self.open_fresh()

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()


MGR = None


def _mgr_cur():
    MGR.ensure()
    return MGR.cur


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


def with_current_probe(cur, sid, snap):
    cur.execute("SELECT v13_probe(%s)", (sid,))
    probe = cur.fetchone()[0]
    out = json.loads(json.dumps(snap))
    out["snap"].update(probe)
    return out


def env_of(cur, sid) -> dict:
    if MGR is not None:
        cur = _mgr_cur()
    cur.execute("SELECT v13_judgment_envelope(%s)", (sid,))
    return cur.fetchone()[0]


def gap_of(cur, env) -> list:
    cur.execute("SELECT v13_gap(%s::jsonb)", (json.dumps(env),))
    return cur.fetchone()[0]


def next_batch(cur, env) -> list:
    """Predict the next ask batch exactly as v13_resolve_judgments selects
    it: canonical group first (<=32 by signal), else existence, else the
    fillable per-chunk prefix (<=32 by signal)."""
    gap = gap_of(cur, env)
    canon = [g for g in gap
             if g["template_name"] not in FILTER_TEMPLATES]
    if canon:
        return canon[:32]
    if any(g["signal"] == CORPUS_EXISTS for g in gap):
        return [g for g in gap if g["signal"] == CORPUS_EXISTS]
    if env and isinstance(env.get("candidates"), list):
        cur.execute(
            "SELECT v13_filter_gate_open(%s::jsonb)", (json.dumps(env),))
        if cur.fetchone()[0]:
            return [g for g in gap if g["signal"].startswith("chunk::")][:32]
    return []


def mock_for(cur, sid_or_env, over=None) -> str:
    over = over or {}
    env = sid_or_env if isinstance(sid_or_env, dict) else env_of(cur, sid_or_env)
    batch = next_batch(cur, env)
    answers = {}
    for g in batch:
        s = g["signal"]
        if s in over:
            answers[s] = over[s]
            continue
        if g["kind"] == "choice":
            crit = g.get("criteria") or {"none": "no option"}
            ch = sorted(crit.keys())[0]
            answers[s] = {"type": "choice", "choice": ch,
                          "probabilities": {ch: 0.9}, "confidence": 0.9}
        elif g["kind"] == "score":
            crit = g.get("criteria") or [0, 1]
            answers[s] = {"type": "score", "score": min(3, len(crit) - 1),
                          "confidence": 0.9}
        else:
            answers[s] = {"type": "noul", "noul": 0.85}
    for k, v in over.items():
        if k in answers:
            answers[k] = v
    return json.dumps({"model": "jev-mock", "answers": answers,
                       "usage": {"input_tokens": 1, "output_tokens": 1}})


def parse_mock(cur, sid, over=None) -> dict:
    k = _mgr_cur() if MGR is not None else cur
    set_mock(k, mock_for(k, sid, over))
    k.execute("SELECT v13_parse(%s)", (sid,))
    return k.fetchone()[0]


def answers_sql(cur, sid) -> dict:
    return parse_mock(cur, sid, {
        "intent": {"type": "choice", "choice": "sql_answer",
                   "probabilities": {"sql_answer": 0.9}, "confidence": 0.9},
        "gate_action": {"type": "noul", "noul": 0.9},
        "gate_off_topic": {"type": "noul", "noul": 0.1},
        "risk": {"type": "score", "score": 0.5, "confidence": 0.9},
        "tool": {"type": "choice", "choice": "session_stats",
                 "probabilities": {"session_stats": 0.9}, "confidence": 0.9}})


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


def parse_settle(server, C, sid, snap=None):
    cur = C.cur
    snap = snap if snap is not None else answers_sql(cur, sid)
    cur = C.cur
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
    C.commit()
    C.open_fresh()
    return snap, eid, out


def succeed_tool(cur, sid=None):
    sid = sid or new_session(cur)
    append_user(cur, sid, "ingest-op")
    cur.execute(
        "SELECT v13_enqueue_effect(%s, 'tool', %s::jsonb, 'v13_ingest_corpus')",
        (sid, json.dumps({"plan": "ingest", "nonce": u()})))
    eid = cur.fetchone()[0]
    ck = claim_pinned(cur, eid)
    cur.execute(
        "SELECT v13_complete(%s,%s,%s,'succeeded', '{}'::jsonb)",
        (eid, ck["attempt_no"], ck["fence"]))
    check("tool complete accepted", cur.fetchone()[0] == "accepted")
    return eid, sid


def ingest_doc(cur, body, corpus="docs", supersedes=None, eid=None, sid=None):
    if eid is None:
        eid, sid = succeed_tool(cur, sid)
    if supersedes is None:
        cur.execute("SELECT v13_ingest_document(%s,%s,%s)", (eid, corpus, body))
    else:
        cur.execute("SELECT v13_ingest_document(%s,%s,%s,%s)",
                    (eid, corpus, body, supersedes))
    return cur.fetchone()[0], eid, sid


def active_manifest(cur, sid):
    cur.execute(
        "SELECT a.inline FROM sessions s JOIN artifacts a "
        "ON a.artifact_id = s.context_active_artifact "
        "WHERE s.session_id=%s", (sid,))
    row = cur.fetchone()
    return row[0] if row else None


def wait_lock(watch, pid, timeout=8.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        watch.execute(
            "SELECT wait_event_type, wait_event FROM pg_stat_activity "
            "WHERE pid=%s", (pid,))
        row = watch.fetchone()
        if row and row[0] == "Lock":
            return True
        watch.execute(
            "SELECT bool_or(NOT granted) FROM pg_locks "
            "WHERE locktype='advisory' AND pid=%s", (pid,))
        row = watch.fetchone()
        if row and row[0] is True:
            return True
        time.sleep(0.02)
    return False


def keys_of(obj) -> set:
    if isinstance(obj, str):
        obj = json.loads(obj)
    return set(obj)


def hanging_server():
    import socket
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(8)
    port = sock.getsockname()[1]
    stop = threading.Event()

    def serve() -> None:
        sock.settimeout(0.3)
        while not stop.is_set():
            try:
                conn, _ = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                time.sleep(8)
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
        try:
            sock.close()
        except OSError:
            pass

    threading.Thread(target=serve, daemon=True).start()
    return port, stop


def main() -> int:
    global MGR
    setup_db()
    server = get_server()
    C = Conns(server)
    MGR = C

    C.cur.execute("SELECT candidate_generation_revision FROM v13_tools_meta WHERE singleton")
    cgr_a0 = C.cur.fetchone()[0]

    # ----- A templates / policies / defaults (F1 carrier) -----
    C.cur.execute(
        "SELECT kind, question, criteria, projection, provider, model, writer,"
        " wire_version, canon_version, epoch, answer_schema_version "
        "FROM judgment_templates WHERE template_name='corpus_exists' "
        "AND template_version=1")
    row = C.cur.fetchone()
    check("A1: corpus_exists kind noul", row[0] == "noul", row)
    check("A1: corpus_exists question verbatim", row[1] == CORPUS_Q, row[1])
    check("A1: corpus_exists criteria NULL", row[2] is None, row[2])
    check("A1: corpus_exists projection", row[3] == ["query", "chunks"], row[3])
    check("A1: corpus_exists provider/model NULL",
          row[4] is None and row[5] is None, (row[4], row[5]))
    check("A1: corpus_exists writer", row[6] == "v13_resolve", row[6])
    check("A1: corpus_exists wire/canon 1", row[7] == 1 and row[8] == 1)
    check("A1: corpus_exists epoch pre-finalize",
          row[9] == "pre-finalize", row[9])
    C.cur.execute(
        "SELECT kind, question, criteria, projection, epoch "
        "FROM judgment_templates WHERE template_name='chunk_score' "
        "AND template_version=1")
    row = C.cur.fetchone()
    check("A1: chunk_score kind score", row[0] == "score", row)
    check("A1: chunk_score question verbatim", row[1] == SCORE_Q, row[1])
    check("A1: chunk_score criteria four levels",
          row[2] == SCORE_CRITERIA, row[2])
    check("A1: chunk_score projection", row[3] == ["query", "chunks"], row[3])
    check("A1: chunk_score epoch pre-finalize",
          row[4] == "pre-finalize", row[4])
    C.cur.execute(
        "SELECT state FROM v13_judgment_template_versions "
        "WHERE template_name IN ('corpus_exists','chunk_score')")
    check("A1: both versions frozen",
          C.cur.fetchall() == [("frozen",), ("frozen",)])

    C.cur.execute("SELECT candidate_generation_revision FROM v13_tools_meta WHERE singleton")
    cgr_a1 = C.cur.fetchone()[0]
    C.cur.execute(
        "INSERT INTO v13_judgment_template_versions (template_name, template_version) "
        "VALUES ('filter_canary', 1)")
    C.cur.execute("SELECT candidate_generation_revision FROM v13_tools_meta WHERE singleton")
    check("A1: versions insert does not bump cgr",
          C.cur.fetchone()[0] == cgr_a1)
    C.cur.execute(
        "INSERT INTO judgment_templates (template_name, template_version, kind,"
        " question, criteria, projection, epoch) VALUES "
        "('filter_canary', 1, 'noul', 'canary?', NULL, '[\"*\"]'::jsonb, 'pre-bind')")
    C.cur.execute("SELECT candidate_generation_revision FROM v13_tools_meta WHERE singleton")
    cgr_canary_content = C.cur.fetchone()[0]
    check("A1: content row bumps cgr",
          cgr_canary_content == cgr_a1 + 1, (cgr_a1, cgr_canary_content))
    C.cur.execute(
        "UPDATE v13_judgment_template_versions SET state='frozen' "
        "WHERE template_name='filter_canary'")
    C.cur.execute("SELECT candidate_generation_revision FROM v13_tools_meta WHERE singleton")
    cgr_canary_frozen = C.cur.fetchone()[0]
    check("A1: freeze bumps cgr",
          cgr_canary_frozen == cgr_canary_content + 1,
          (cgr_canary_content, cgr_canary_frozen))
    fails_with(
        C.cur,
        "INSERT INTO judgment_templates (template_name, template_version, kind,"
        " question, criteria, projection) VALUES "
        "('filter_canary', 1, 'noul', 'dup?', NULL, '[\"*\"]'::jsonb)",
        (), "draft parent", "A1: same-version content row rejected (insert_guard)")
    C.commit()

    C.cur.execute(
        "SELECT version, value FROM v13_policies WHERE name='judgment_defaults' AND active")
    jdef_ver, jdef_val = C.cur.fetchone()
    check("A2: defaults active v2", jdef_ver == 2, jdef_ver)
    check("A2: defaults v2 points shape",
          jdef_val["points"]["chunk_score"] ==
          {"missing": "include", "timeout": "include", "review": "degrade"}
          and jdef_val["points"]["corpus_exists"] ==
          {"missing": "include", "timeout": "include", "review": "include"},
          jdef_val)
    C.cur.execute("SELECT v13_judgment_defaults_check(%s::jsonb)",
                (json.dumps(jdef_val),))
    check("A2: defaults v2 passes validator", True)
    sid_a2 = new_session(C.cur)
    append_user(C.cur, sid_a2, "defaults probe")
    C.cur.execute("SELECT v13_context_required(%s)", (sid_a2,))
    check("A2: token jdef_ver=2",
          C.cur.fetchone()[0]["jdef_ver"] == 2)
    bad_v3 = {"points": {"chunk_score": {"missing": "include"}},
              "actions": ["include", "exclude", "degrade", "fail"]}
    fails_with(C.cur, "SELECT v13_judgment_defaults_check(%s::jsonb)",
               (json.dumps(bad_v3),), "point chunk_score shape violation",
               "A2: v3 missing state key rejected V3003", pgcode="V3003")
    C.commit()

    C.cur.execute(
        "SELECT value FROM v13_policies WHERE name='chunk_filter' AND active")
    cf = C.cur.fetchone()[0]
    sid_a3 = new_session(C.cur)
    append_user(C.cur, sid_a3, "chunk filter shape")
    C.cur.execute("SELECT v13_goal_hash(%s)", (sid_a3,))
    gh_a3 = C.cur.fetchone()[0]

    def bad_cf(val, label, existence_too=True, action_too=True):
        bump_policy(C.cur, "chunk_filter", val)
        if existence_too:
            fails_with(C.cur, "SELECT v13_existence_action(%s::jsonb)",
                       (json.dumps({"noul": 0.5}),), "invalid chunk_filter",
                       label, pgcode="V3006")
        if action_too:
            fails_with(
                C.cur,
                "SELECT v13_chunk_filter_action(%s,%s,%s,%s)",
                (sid_a3, gh_a3, "0" * 64, "1" * 64),
                "invalid chunk_filter", label + " (action)", pgcode="V3006")
        bump_policy(C.cur, "chunk_filter", cf)

    bad_cf({k: v for k, v in cf.items() if k != "gate_open_lo"},
           "A3: missing gate_open_lo")
    bad_cf({**cf, "gate_closed_hi": "0.30"}, "A3: string band value")
    bad_cf({**cf, "gate_closed_hi": 0.5, "gate_open_lo": 0.4},
           "A3: hi >= lo", action_too=False)
    bad_cf({**cf, "score_conf_lo": 1.5}, "A3: conf_lo > 1",
           existence_too=False)
    C.commit()

    v4 = {**jdef_val}
    bump_policy(C.cur, "judgment_defaults",
                {"points": {"corpus_exists": jdef_val["points"]["corpus_exists"]},
                 "actions": jdef_val["actions"]})
    fails_with(C.cur, "SELECT v13_filter_defaults_action('chunk_score','missing')",
               (), "missing point chunk_score", "A4: runtime defaults fail-closed",
               pgcode="V3006")
    bump_policy(C.cur, "judgment_defaults", v4)
    C.cur.execute("SELECT version FROM v13_policies WHERE name='judgment_defaults' AND active")
    check("A4: defaults restored (values of v2)",
          C.cur.fetchone()[0] >= 2)
    C.commit()

    # ----- B envelope integration (OQ2) -----
    eid_ops, sid_ops = succeed_tool(C.cur)
    C.commit()
    for i in range(2):
        ingest_doc(C.cur, f"quasar formation document {i} about quasars",
                   "docs", eid=eid_ops)
    C.commit()
    sid_b1 = new_session(C.cur)
    append_user(C.cur, sid_b1, "quasar formation")
    env_b1 = env_of(C.cur, sid_b1)
    check("B1: 20 keys", keys_of(env_b1) == ENV20, keys_of(env_b1))
    sigs_b1 = [n["signal"] for n in env_b1["needed"]]
    check("B1: corpus_exists exactly one",
          sigs_b1.count(CORPUS_EXISTS) == 1, sigs_b1)
    cand_hashes_b1 = {c["content_hash"] for c in env_b1["candidates"]}
    chunk_sigs_b1 = [s for s in sigs_b1 if s.startswith("chunk::")]
    check("B1: chunk rows equal distinct candidates",
          {s[7:] for s in chunk_sigs_b1} == cand_hashes_b1,
          (len(chunk_sigs_b1), len(cand_hashes_b1)))
    check("B1: needed_count", env_b1["needed_count"] == len(sigs_b1))
    check("B1: all signals distinct", len(set(sigs_b1)) == len(sigs_b1))
    base_n = len([n for n in env_b1["needed"]
                  if n["template_name"] not in FILTER_TEMPLATES])
    check("B1: needed = base + 1 + k",
          env_b1["needed_count"] == base_n + 1 + len(cand_hashes_b1))

    shared = "sharedtok " + ("x" * 3200)
    tail1 = "tail-alpha " + ("y" * 3200)
    tail2 = "tail-beta " + ("z" * 3200)
    ingest_doc(C.cur, shared + "\n\n" + tail1, "dup1", eid=eid_ops)
    ingest_doc(C.cur, shared + "\n\n" + tail2, "dup2", eid=eid_ops)
    C.commit()
    sid_b2 = new_session(C.cur)
    append_user(C.cur, sid_b2, "sharedtok")
    env_b2 = env_of(C.cur, sid_b2)
    sigs_b2 = [n["signal"] for n in env_b2["needed"]]
    dup_rows = [c for c in env_b2["candidates"]
                if c["content_hash"] in
                {x["content_hash"] for x in env_b2["candidates"]}]
    shared_hash = None
    C.cur.execute("SELECT v13_body_hash(%s)", (shared,))
    shared_hash = C.cur.fetchone()[0]
    n_cand_shared = len([c for c in env_b2["candidates"]
                         if c["content_hash"] == shared_hash])
    check("B2: cross-source same body stays two candidate rows",
          n_cand_shared == 2, n_cand_shared)
    chunk_shared = [s for s in sigs_b2
                    if s == "chunk::" + shared_hash]
    check("B2: filter row deduped to one", len(chunk_shared) == 1, chunk_shared)

    sid_b3 = new_session(C.cur)
    env_b3 = env_of(C.cur, sid_b3)
    sigs_b3 = [n["signal"] for n in env_b3["needed"]]
    check("B3: empty session zero filter rows",
          not any(s == CORPUS_EXISTS or s.startswith("chunk::")
                  for s in sigs_b3), sigs_b3)
    C.cur.execute("SELECT v13_recall_candidates(%s)", (sid_b3,))
    rc_b3 = C.cur.fetchone()[0]
    check("B3: k=0 candidates empty",
          rc_b3["k"] == 0 and rc_b3["candidates"] == [], rc_b3)

    groups_b1 = env_b1["groups"]
    check("B4: groups canonical only (one wildcard group)",
          len(groups_b1) == 1, groups_b1)
    check("B4: group state is full ctx (wildcard)",
          groups_b1[0]["state"] == env_b1["ctx"], list(groups_b1[0]["state"]))
    check("B4: no filter group state carried",
          all("chunks" not in g["state"] for g in groups_b1))

    snap_csh1 = env_of(C.cur, sid_b1)
    snap_csh2 = env_of(C.cur, sid_b1)
    check("B5: same world csh stable",
          snap_csh1["candidate_set_hash"] == snap_csh2["candidate_set_hash"])
    ingest_doc(C.cur, "quasar formation fresh drift " + u(), "docs", eid=eid_ops)
    C.commit()
    snap_csh3 = env_of(C.cur, sid_b1)
    check("B5: ingest changes csh",
          snap_csh3["candidate_set_hash"] != snap_csh1["candidate_set_hash"])
    check("B5: csh hex", bool(HEX64.match(snap_csh3["candidate_set_hash"])))

    C.cur.execute("SELECT v13_recall_candidates(%s)", (sid_b1,))
    rc_direct = C.cur.fetchone()[0]
    check("B6: envelope candidates equal single derivation",
          env_of(C.cur, sid_b1)["candidates"] == rc_direct["candidates"])

    C.cur.execute(
        "SELECT v13_template_latest.kind IS NOT NULL "
        "FROM v13_template_latest "
        "WHERE template_name IN ('corpus_exists','chunk_score')")
    check("B7: production filter templates present (belt)",
          C.cur.rowcount == 2)
    bad_tmpl = {"corpus_exists": {"kind": "noul", "question": "q?"}}
    fails_with(C.cur, "SELECT v13_require_filter_templates(%s::jsonb)",
               (json.dumps(bad_tmpl),), "corpus_exists/chunk_score missing",
               "B7: guard fails closed", pgcode="V3006")
    C.commit()

    # ----- C existence gate (G-ctx4-1 + F2) -----
    for i in range(2):
        ingest_doc(C.cur, f"c1gate formation doc {i} {u()}", "c1", eid=eid_ops)
    C.commit()
    sid_c1 = new_session(C.cur)
    append_user(C.cur, sid_c1, "c1gate formation")
    answers_sql(C.cur, sid_c1)
    C.commit()
    env_c1 = env_of(C.cur, sid_c1)
    set_mock(C.cur, mock_for(C.cur, env_c1))
    C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
                (json.dumps(env_c1),))
    r_c1 = C.cur.fetchone()[0]
    check("C1: gate open (noul 0.85)", r_c1["gate_open"] is True, r_c1)
    C.cur.execute(
        "SELECT projection_key FROM judgment_calls WHERE session_id=%s "
        "ORDER BY created_at, call_id", (sid_c1,))
    labels_c1 = [r[0] for r in C.cur.fetchall()]
    check("C1: existence batch precedes all chunk batches",
          labels_c1 == [l for l in labels_c1
                        if l != CORPUS_EXISTS] or
          (CORPUS_EXISTS in labels_c1 and
           (not any(l == "chunk_score" for l in labels_c1) or
            labels_c1.index(CORPUS_EXISTS) <
            max(i for i, l in enumerate(labels_c1) if l == "chunk_score"))),
          labels_c1)
    check("C1: first filter ask is existence", "chunk_score" not in labels_c1,
          labels_c1)
    C.commit()

    for i in range(2):
        ingest_doc(C.cur, f"c2gate formation doc {i} {u()}", "c2", eid=eid_ops)
    C.commit()
    sid_c2 = new_session(C.cur)
    append_user(C.cur, sid_c2, "c2gate formation")
    answers_sql(C.cur, sid_c2)
    C.commit()
    env_c2 = env_of(C.cur, sid_c2)
    set_mock(C.cur, mock_for(C.cur, env_c2, {CORPUS_EXISTS: {"type": "noul", "noul": 0.10}}))
    C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 10)",
                (json.dumps(env_c2),))
    r_c2 = C.cur.fetchone()[0]
    check("C2: asked exactly 1", r_c2["asked_questions"] == 1, r_c2)
    check("C2: failed=false", r_c2["failed"] is False, r_c2)
    check("C2: remaining 0 (gate-aware)", r_c2["remaining"] == 0, r_c2)
    check("C2: gate_open false", r_c2["gate_open"] is False, r_c2)
    C.cur.execute(
        "SELECT projection_key, question_count FROM judgment_calls "
        "WHERE session_id=%s AND projection_key IN ('corpus_exists',"
        "'chunk_score')", (sid_c2,))
    calls_c2 = C.cur.fetchall()
    check("C2: exactly one existence call, zero score calls",
          calls_c2 == [(CORPUS_EXISTS, 1)], calls_c2)
    C.cur.execute(
        "SELECT count(*) FILTER (WHERE signal='corpus_exists'),"
        " count(*) FILTER (WHERE signal LIKE 'chunk::%%') "
        "FROM decisions WHERE session_id=%s", (sid_c2,))
    n_ex, n_ch = C.cur.fetchone()
    check("C2: one existence decision, zero chunk decisions",
          (n_ex, n_ch) == (1, 0), (n_ex, n_ch))
    C.cur.execute(
        "SELECT context FROM decisions WHERE session_id=%s "
        "AND signal='corpus_exists'", (sid_c2,))
    ctx_c2 = C.cur.fetchone()[0]
    check("C2: existence context carries digest",
          bool(HEX64.match(ctx_c2.get("candidates_digest", ""))), ctx_c2)
    C.commit()

    tokA = "driftogen alpha"
    tokB = "driftogen beta"
    sid_c3 = new_session(C.cur)
    append_user(C.cur, sid_c3, tokA)
    answers_sql(C.cur, sid_c3)
    C.commit()
    ingest_doc(C.cur, f"document about {tokA} unrelated filler", "c3", eid=eid_ops)
    C.commit()
    env_c3a = env_of(C.cur, sid_c3)
    set_mock(C.cur, mock_for(C.cur, env_c3a,
                           {CORPUS_EXISTS: {"type": "noul", "noul": 0.10}}))
    C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 10)",
                (json.dumps(env_c3a),))
    C.cur.fetchone()
    C.commit()
    snap_c3 = parse_mock(C.cur, sid_c3)
    C.commit()
    ingest_doc(C.cur, f"document that answers {tokA} with {tokB} content",
               "c3", eid=eid_ops)
    C.commit()
    C.cur.execute("SELECT v13_advance(%s, %s::jsonb)",
                (sid_c3, json.dumps(snap_c3)))
    check("C3: advance stale after ingest", C.cur.fetchone()[0] == "stale")
    C.open_fresh()
    env_c3b = env_of(C.cur, sid_c3)
    check("C3: candidates grew with docB",
          len(env_c3b["candidates"]) > len(env_c3a["candidates"]),
          (len(env_c3a["candidates"]), len(env_c3b["candidates"])))
    set_mock(C.cur, mock_for(C.cur, env_c3b,
                           {CORPUS_EXISTS: {"type": "noul", "noul": 0.85}}))
    C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
                (json.dumps(env_c3b),))
    r_c3b = C.cur.fetchone()[0]
    check("C3: gate reopened on new generation", r_c3b["gate_open"] is True, r_c3b)
    C.commit()
    C.open_fresh()
    env_c3c = env_of(C.cur, sid_c3)
    set_mock(C.cur, mock_for(C.cur, env_c3c))
    C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 10)",
                (json.dumps(env_c3c),))
    r_c3c = C.cur.fetchone()[0]
    check("C3: per-chunk batches run after reopen",
          r_c3c["failed"] is False, r_c3c)
    C.commit()
    C.cur.execute(
        "SELECT count(*) FROM judgment_cache WHERE signal='corpus_exists' "
        "AND request_hash IN (SELECT request_hash FROM decisions "
        "WHERE session_id=%s AND signal='corpus_exists')", (sid_c3,))
    check("C3: exactly two existence cache generations (this session)",
          C.cur.fetchone()[0] == 2)
    C.cur.execute(
        "SELECT context->>'candidates_digest' FROM decisions "
        "WHERE session_id=%s AND signal='corpus_exists' ORDER BY created_at",
        (sid_c3,))
    digs_c3 = [r[0] for r in C.cur.fetchall()]
    check("C3: two existence decisions with distinct digests",
          len(digs_c3) == 2 and digs_c3[0] != digs_c3[1], digs_c3)
    C.commit()

    C.open_fresh()
    C.cur.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                (sid_c3,))
    calls_c3 = C.cur.fetchone()[0]
    poison(C.cur)
    p_c4 = None
    C.cur.execute("SELECT v13_parse(%s)", (sid_c3,))
    p_c4 = C.cur.fetchone()[0]
    check("C4: poisoned reparse failed=false asked=0",
          p_c4["failed"] is False and p_c4["asked_questions"] == 0, p_c4)
    C.cur.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                (sid_c3,))
    check("C4: zero new calls", C.cur.fetchone()[0] == calls_c3)
    env_c4 = env_of(C.cur, sid_c3)
    C.cur.execute("SELECT v13_filter_gate_open(%s::jsonb)",
                (json.dumps(env_c4),))
    check("C4: gate_open true consuming cached row",
          C.cur.fetchone()[0] is True)
    C.commit()

    for i in range(2):
        ingest_doc(C.cur, f"c5gate formation doc {i} {u()}", "c5", eid=eid_ops)
    C.commit()
    sid_c5a = new_session(C.cur)
    append_user(C.cur, sid_c5a, "c5gate formation")
    answers_sql(C.cur, sid_c5a)
    C.commit()
    env_c5a = env_of(C.cur, sid_c5a)
    set_mock(C.cur, json.dumps({"model": "jev-mock",
                              "answers": {CORPUS_EXISTS:
                                          {"type": "noul", "noul": "bad"}},
                              "usage": {"input_tokens": 1}}))
    C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 10)",
                (json.dumps(env_c5a),))
    r_c5a = C.cur.fetchone()[0]
    check("C5-1: failed=true on malformed existence (engine #45(b) morph)",
          r_c5a["failed"] is True, r_c5a)
    C.cur.execute(
        "SELECT count(*) FROM decisions WHERE session_id=%s "
        "AND signal='corpus_exists'", (sid_c5a,))
    check("C5-1: no existence decision", C.cur.fetchone()[0] == 0)
    C.cur.execute("SELECT v13_filter_gate_open(%s::jsonb)",
                (json.dumps(env_c5a),))
    check("C5-1: missing state is fail-open (gate open)",
          C.cur.fetchone()[0] is True)
    C.commit()

    sid_c5b = new_session(C.cur)
    append_user(C.cur, sid_c5b, "c5gate formation")
    answers_sql(C.cur, sid_c5b)
    C.commit()
    env_c5b = env_of(C.cur, sid_c5b)
    set_mock(C.cur, mock_for(C.cur, env_c5b,
                           {CORPUS_EXISTS: {"type": "noul", "noul": 0.35}}))
    C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
                (json.dumps(env_c5b),))
    C.cur.fetchone()
    C.open_fresh()
    env_c5b2 = env_of(C.cur, sid_c5b)
    set_mock(C.cur, mock_for(C.cur, env_c5b2))
    C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 10)",
                (json.dumps(env_c5b2),))
    r_c5b = C.cur.fetchone()[0]
    check("C5-2: review band defaults include (gate open)",
          r_c5b["gate_open"] is True, r_c5b)
    C.cur.execute(
        "SELECT count(*) FROM judgment_calls WHERE session_id=%s "
        "AND projection_key='chunk_score'", (sid_c5b,))
    check("C5-2: per-chunk still runs", C.cur.fetchone()[0] >= 1)
    C.commit()

    C.cur.execute(
        "SELECT value FROM v13_policies WHERE name='judgment_defaults' AND active")
    jd_c5 = C.cur.fetchone()[0]
    jd_review_exclude = json.loads(json.dumps(jd_c5))
    jd_review_exclude["points"]["corpus_exists"]["review"] = "exclude"
    bump_policy(C.cur, "judgment_defaults", jd_review_exclude)
    C.commit()
    for i in range(2):
        ingest_doc(C.cur, f"c5cgate formation doc {i} {u()}", "c5c", eid=eid_ops)
    C.commit()
    sid_c5c = new_session(C.cur)
    append_user(C.cur, sid_c5c, "c5cgate formation")
    answers_sql(C.cur, sid_c5c)
    C.commit()
    env_c5c = env_of(C.cur, sid_c5c)
    set_mock(C.cur, mock_for(C.cur, env_c5c,
                           {CORPUS_EXISTS: {"type": "noul", "noul": 0.35}}))
    C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 10)",
                (json.dumps(env_c5c),))
    r_c5c = C.cur.fetchone()[0]
    check("C5-4: review->exclude version closes gate",
          r_c5c["gate_open"] is False and r_c5c["remaining"] == 0, r_c5c)
    C.cur.execute(
        "SELECT count(*) FROM judgment_calls WHERE session_id=%s "
        "AND projection_key='chunk_score'", (sid_c5c,))
    check("C5-4: zero score calls under closed gate",
          C.cur.fetchone()[0] == 0)
    bump_policy(C.cur, "judgment_defaults", jd_c5)
    C.commit()

    bump_policy(C.cur, "chunk_filter",
                {**cf, "gate_closed_hi": 0.5, "gate_open_lo": 0.4})
    fails_with(C.cur, "SELECT v13_filter_gate_open(%s::jsonb)",
               (json.dumps(env_c5b),), "invalid chunk_filter",
               "C6: gate_open negative on bad band", pgcode="V3006")
    bump_policy(C.cur, "chunk_filter", cf)
    C.commit()

    tokC = "beltogen secret"
    sid_c7 = new_session(C.cur)
    append_user(C.cur, sid_c7, tokC)
    ingest_doc(C.cur, f"first document mentioning {tokC} for the belt",
               "c7", eid=eid_ops)
    ingest_doc(C.cur, f"second document mentioning {tokC} as well",
               "c7", eid=eid_ops)
    C.commit()
    try:
        poison(C.cur)
        C.cur.execute("SELECT v13_parse(%s)", (sid_c7,))
        check("C7-1: poisoned parse raised", False, "no exception")
    except psycopg2.Error as exc:
        check("C7-1: poisoned parse raised fail-loud",
              exc.pgcode not in (None, "V3001"), exc.pgcode)
    C.rollback()
    C.cur.execute(
        "SELECT count(*) FROM decisions WHERE session_id=%s", (sid_c7,))
    check("C7-1: zero consumption", C.cur.fetchone()[0] == 0)
    C.cur.execute(
        "SELECT count(*) FROM judgment_calls WHERE session_id=%s", (sid_c7,))
    check("C7-1: zero calls", C.cur.fetchone()[0] == 0)
    env_c7 = env_of(C.cur, sid_c7)
    check("C7: env candidates present",
          len(env_c7["candidates"]) >= 2, len(env_c7["candidates"]))
    victim = env_c7["candidates"][0]["content_hash"]
    C.cur.execute("DELETE FROM chunks WHERE content_hash=%s", (victim,))
    C.commit()
    set_mock(C.cur, mock_for(C.cur, env_c7))
    C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 10)",
                (json.dumps(env_c7),))
    r_c7 = C.cur.fetchone()[0]
    check("C7-3: bodies guard failed=false", r_c7["failed"] is False, r_c7)
    check("C7-3: remaining 0 (filter rows excluded)", r_c7["remaining"] == 0, r_c7)
    C.cur.execute(
        "SELECT count(*) FROM judgment_calls WHERE session_id=%s "
        "AND projection_key='corpus_exists'", (sid_c7,))
    check("C7-3: zero existence asks", C.cur.fetchone()[0] == 0)
    C.cur.execute(
        "SELECT count(*) FROM judgment_cache WHERE signal='corpus_exists' "
        "AND request_hash IN (SELECT request_hash FROM decisions "
        "WHERE session_id=%s)", (sid_c7,))
    check("C7-3: zero existence cache rows (no stale no-answer)",
          C.cur.fetchone()[0] == 0)
    C.commit()
    C.cur.execute(
        "SELECT source_hash FROM v13_sources WHERE superseded_by IS NULL "
        "AND source_hash IN (SELECT source_hash FROM chunks WHERE content_hash=%s)"
        " LIMIT 1", (victim,))
    srcrow = C.cur.fetchone()
    ingest_doc(C.cur, f"first document mentioning {tokC} for the belt",
               "c7", eid=eid_ops)
    ingest_doc(C.cur, f"second document mentioning {tokC} as well",
               "c7", eid=eid_ops)
    C.commit()
    C.cur.execute(
        "SELECT count(*) FROM chunks WHERE content_hash=%s", (victim,))
    check("C7-4: same body re-ingested (content_hash back)", 
          C.cur.fetchone()[0] >= 1)
    C.open_fresh()
    snap_c7 = parse_mock(C.cur, sid_c7)
    check("C7-4: reparse failed=false", snap_c7["failed"] is False, snap_c7)
    C.commit()
    env_c7b = env_of(C.cur, sid_c7)
    dig_before = None
    C.cur.execute(
        "SELECT v13_candidates_digest(%s::jsonb), "
        "v13_candidates_digest(%s::jsonb)",
        (json.dumps(env_c7["candidates"]), json.dumps(env_c7b["candidates"])))
    dig_before, dig_after = C.cur.fetchone()
    check("C7-4: candidates restored, digest unchanged",
          dig_before == dig_after, (dig_before, dig_after))
    set_mock(C.cur, mock_for(C.cur, env_c7b,
                           {CORPUS_EXISTS: {"type": "noul", "noul": 0.85}}))
    C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 10)",
                (json.dumps(env_c7b),))
    C.cur.fetchone()
    C.cur.execute(
        "SELECT count(*) FROM judgment_calls WHERE session_id=%s "
        "AND projection_key='corpus_exists'", (sid_c7,))
    check("C7-4: existence asked exactly once (no stale reuse)",
          C.cur.fetchone()[0] == 1)
    C.commit()

    # ----- D per-chunk cache (G-ctx4-2/3) -----
    def fill_session(sid, goal, corpus_docs=3,
                     chunk_over=None, existence=0.85):
        for i in range(corpus_docs):
            ingest_doc(C.cur, f"{goal} evidence document {i} {u()}",
                       "dgrp", eid=eid_ops)
        C.commit()
        append_user(C.cur, sid, goal)
        answers_sql(C.cur, sid)
        C.commit()
        env = env_of(C.cur, sid)
        set_mock(C.cur, mock_for(C.cur, env,
                               {CORPUS_EXISTS: {"type": "noul", "noul": existence}}))
        C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
                    (json.dumps(env),))
        C.cur.fetchone()
        C.commit()
        env = env_of(C.cur, sid)
        over = dict(chunk_over or {})
        set_mock(C.cur, mock_for(C.cur, env, over))
        C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 10)",
                    (json.dumps(env),))
        C.cur.fetchone()
        C.commit()
        return env

    sid_d1 = new_session(C.cur)
    fill_session(sid_d1, "d1tok")
    C.cur.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                (sid_d1,))
    calls_d1 = C.cur.fetchone()[0]
    C.cur.execute("SELECT count(*) FROM decisions WHERE session_id=%s", (sid_d1,))
    dec_d1 = C.cur.fetchone()[0]
    C.cur.execute("SELECT count(*) FROM judgment_cache")
    cache_d1 = C.cur.fetchone()[0]
    C.open_fresh()
    poison(C.cur)
    p_d1 = None
    C.cur.execute("SELECT v13_parse(%s)", (sid_d1,))
    p_d1 = C.cur.fetchone()[0]
    check("D1: poisoned reparse failed=false asked=0",
          p_d1["failed"] is False and p_d1["asked_questions"] == 0, p_d1)
    C.cur.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                (sid_d1,))
    check("D1: zero new calls", C.cur.fetchone()[0] == calls_d1)
    C.cur.execute("SELECT count(*) FROM decisions WHERE session_id=%s", (sid_d1,))
    check("D1: zero new decisions", C.cur.fetchone()[0] == dec_d1)
    C.cur.execute("SELECT count(*) FROM judgment_cache")
    check("D1: zero new cache rows", C.cur.fetchone()[0] == cache_d1)
    C.commit()

    sid_d2 = new_session(C.cur)
    append_user(C.cur, sid_d2, "d1tok")
    C.commit()
    C.cur.execute("SELECT count(*) FROM judgment_cache")
    cache_d2a = C.cur.fetchone()[0]
    C.cur.execute("SELECT count(*) FROM judgment_calls")
    calls_d2a = C.cur.fetchone()[0]
    C.open_fresh()
    poison(C.cur)
    p_d2 = None
    C.cur.execute("SELECT v13_parse(%s)", (sid_d2,))
    p_d2 = C.cur.fetchone()[0]
    check("D2: cross-session poisoned parse zero ask",
          p_d2["failed"] is False and p_d2["asked_questions"] == 0, p_d2)
    C.cur.execute(
        "SELECT status, reused_from, call_id, session_id FROM decisions "
        "WHERE session_id=%s AND signal LIKE 'chunk::%%'", (sid_d2,))
    rows_d2 = C.cur.fetchall()
    check("D2: per-chunk decisions landed", len(rows_d2) >= 3, len(rows_d2))
    check("D2: all cached status",
          all(r[0] == "cached" for r in rows_d2), rows_d2[:2])
    check("D2: reused_from set, call_id NULL",
          all(r[1] is not None and r[2] is None for r in rows_d2), rows_d2[:2])
    check("D2: rows belong to session B", str(rows_d2[0][3]) == sid_d2)
    C.cur.execute(
        "SELECT count(*) FROM judgment_cache c JOIN decisions d "
        "ON d.reused_from = c.request_hash WHERE d.session_id=%s "
        "AND d.signal LIKE 'chunk::%%'", (sid_d2,))
    check("D2: reused_from joins canonical cache rows",
          C.cur.fetchone()[0] == len(rows_d2))
    C.cur.execute("SELECT count(*) FROM judgment_cache")
    check("D2: cache rows unchanged", C.cur.fetchone()[0] == cache_d2a)
    C.cur.execute("SELECT count(*) FROM judgment_calls")
    check("D2: calls unchanged", C.cur.fetchone()[0] == calls_d2a)
    C.cur.execute(
        "SELECT count(*) FROM (SELECT session_id, request_hash, count(*) "
        "FROM decisions WHERE session_id IN (%s,%s) GROUP BY session_id,"
        " request_hash HAVING count(*) > 1) x", (sid_d1, sid_d2))
    check("D2: per-session uniqueness intact", C.cur.fetchone()[0] == 0)
    env_d2 = env_of(C.cur, sid_d2)
    C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
                (json.dumps(env_d2),))
    r_d2 = C.cur.fetchone()[0]
    check("D2: cache_hits equals gap size",
          r_d2["cache_hits"] == len([g for g in gap_of(C.cur, env_d2)
                                     if g["signal"].startswith("chunk::")])
          or r_d2["cache_hits"] == env_d2["needed_count"], r_d2)
    C.commit()

    sid_d3 = new_session(C.cur)
    body_d3 = f"d3tok unique body {u()}"
    ingest_doc(C.cur, body_d3, "d3", eid=eid_ops)
    C.commit()
    append_user(C.cur, sid_d3, "d3tok")
    answers_sql(C.cur, sid_d3)
    C.commit()
    env_d3 = env_of(C.cur, sid_d3)
    set_mock(C.cur, mock_for(C.cur, env_d3,
                           {CORPUS_EXISTS: {"type": "noul", "noul": 0.85}}))
    C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
                (json.dumps(env_d3),))
    C.cur.fetchone()
    C.commit()
    env_d3 = env_of(C.cur, sid_d3)
    set_mock(C.cur, mock_for(C.cur, env_d3))
    C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 10)",
                (json.dumps(env_d3),))
    C.cur.fetchone()
    C.commit()
    out_d3, _, _ = ingest_doc(C.cur, body_d3, "d3", eid=eid_ops)
    check("D3: same body re-ingest unchanged",
          out_d3["unchanged"] is True, out_d3)
    C.cur.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                (sid_d3,))
    calls_d3 = C.cur.fetchone()[0]
    C.open_fresh()
    poison(C.cur)
    C.cur.execute("SELECT v13_parse(%s)", (sid_d3,))
    p_d3 = C.cur.fetchone()[0]
    check("D3: re-ingest same hash, poisoned reparse zero ask",
          p_d3["failed"] is False and p_d3["asked_questions"] == 0, p_d3)
    C.cur.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                (sid_d3,))
    check("D3: zero new calls", C.cur.fetchone()[0] == calls_d3)
    C.commit()

    gh_d4 = env_of(C.cur, sid_d1)["goal_hash"]
    ch_d4 = env_of(C.cur, sid_d1)["candidates"][0]["content_hash"]
    C.cur.execute(
        "SELECT v13_request_hash('chunk::'||%s,'score',%s,NULL,"
        "v13_filter_ref(%s,%s),'mock','jev-mock'),"
        " v13_request_hash('chunk::'||%s,'score',%s,NULL,"
        "v13_filter_ref(%s,%s),'mock','jev-mock')",
        (ch_d4, SCORE_Q, gh_d4, ch_d4, ch_d4, SCORE_Q, gh_d4, ch_d4))
    h1_d4, h2_d4 = C.cur.fetchone()
    C.cur.execute(
        "SELECT v13_request_hash('chunk::'||%s,'score',%s,NULL,"
        "v13_filter_ref(%s,%s),'mock','jev-mock')",
        (ch_d4, SCORE_Q, "f" * 64, ch_d4))
    h3_d4 = C.cur.fetchone()[0]
    C.cur.execute(
        "SELECT v13_request_hash('chunk::'||%s,'score',%s,NULL,"
        "v13_filter_ref(%s,%s),'mock','jev-mock')",
        (("e" * 64), SCORE_Q, gh_d4, ch_d4))
    h4_d4 = C.cur.fetchone()[0]
    check("D4: same args byte equal", h1_d4 == h2_d4)
    check("D4: chunk sensitivity", h1_d4 != h3_d4)
    check("D4: goal sensitivity", h1_d4 != h4_d4)
    C.cur.execute(
        "SELECT context FROM decisions WHERE session_id=%s "
        "AND signal=%s", (sid_d1, "chunk::" + ch_d4))
    stored_ctx = C.cur.fetchone()[0]
    C.cur.execute("SELECT v13_filter_ref(%s,%s)", (gh_d4, ch_d4))
    check("D4: stored context is filter_ref output (material=storage)",
          stored_ctx == C.cur.fetchone()[0], stored_ctx)
    env_d4 = env_of(C.cur, sid_d1)
    C.cur.execute("SELECT v13_row_context(%s::jsonb, %s)",
                (json.dumps(env_d4), "chunk::" + ch_d4))
    check("D4: row_context dispatch matches filter_ref",
          C.cur.fetchone()[0] == stored_ctx)
    C.commit()

    C.cur.execute("SELECT v13_candidates_digest(%s::jsonb)",
                (json.dumps([{"content_hash": "a" * 64, "bm25": 1.0,
                              "spans": []},
                             {"content_hash": "b" * 64, "bm25": 2.0,
                              "spans": []}]),))
    dig_1 = C.cur.fetchone()[0]
    C.cur.execute("SELECT v13_candidates_digest(%s::jsonb)",
                (json.dumps([{"content_hash": "b" * 64, "bm25": 9.9,
                              "spans": [1]},
                             {"content_hash": "a" * 64, "bm25": 0.1,
                              "spans": []}]),))
    dig_2 = C.cur.fetchone()[0]
    check("D5: shuffled same set equal", dig_1 == dig_2)
    C.cur.execute("SELECT v13_candidates_digest(%s::jsonb)",
                (json.dumps([{"content_hash": "a" * 64, "bm25": 1.0,
                              "spans": []},
                             {"content_hash": "c" * 64, "bm25": 2.0,
                              "spans": []}]),))
    dig_3 = C.cur.fetchone()[0]
    check("D5: set change differs", dig_1 != dig_3)
    env_d5 = env_of(C.cur, sid_d1)
    env_d5b = json.loads(json.dumps(env_d5))
    env_d5b["candidates"] = env_d5b["candidates"][:1] or []
    C.cur.execute(
        "SELECT v13_existence_ref(%s::jsonb) <> v13_existence_ref(%s::jsonb)",
        (json.dumps(env_d5), json.dumps(env_d5b)))
    check("D5: existence ref sensitive to candidates",
          C.cur.fetchone()[0] is True)
    C.commit()

    C.cur.execute("SELECT v13_candidates_digest(%s::jsonb)",
                (json.dumps([{"content_hash": "a" * 64, "bm25": 1.0,
                              "spans": [[1, 2]]},
                             {"content_hash": "b" * 64, "bm25": 5.0,
                              "spans": []}]),))
    dig_4 = C.cur.fetchone()[0]
    check("D6: only candidate dimension (bm25/spans excluded)",
          dig_4 == dig_1, (dig_1, dig_4))
    C.commit()

    # ----- E resolve integration (dual speed / budget / edges) -----
    for i in range(8):
        ingest_doc(C.cur, f"e1tok query evidence number {i} {u()}",
                   "e1", eid=eid_ops)
    C.commit()
    sid_e1 = new_session(C.cur)
    append_user(C.cur, sid_e1, "e1tok")
    p_e1 = answers_sql(C.cur, sid_e1)
    check("E1: parse1 canonical only, filter remaining",
          p_e1["asked_questions"] > 0 and p_e1["remaining"] == 9,
          (p_e1["asked_questions"], p_e1["remaining"]))
    parse_settle(server, C, sid_e1, snap=p_e1)
    live_e1 = with_current_probe(C.cur, sid_e1, p_e1)
    C.cur.execute("SELECT v13_advance(%s, %s::jsonb)",
                (sid_e1, json.dumps(live_e1)))
    a_e1 = C.cur.fetchone()[0]
    check("E1: advance waiting (judge effect)", a_e1 == "waiting", a_e1)
    C.cur.execute(
        "SELECT effect_id FROM effects WHERE session_id=%s AND kind='judge' "
        "AND status='ready'", (sid_e1,))
    je_row = C.cur.fetchone()
    check("E1: judge effect ready", je_row is not None)
    je_e1 = je_row[0]
    C.commit()

    wconn = psycopg2.connect(server.get_uri(DB))
    wconn.autocommit = False
    wcur = wconn.cursor()
    guc(wcur)
    ck_e1 = claim_pinned(wcur, je_e1)
    env_w = ck_e1["request"]["envelope"]
    rounds_e1 = 0
    renew_ok = True
    while True:
        env_now = wconn and env_w
        wcur.execute("SELECT v13_gap(%s::jsonb)", (json.dumps(env_w),))
        if not wcur.fetchone()[0]:
            break
        set_mock(wcur, mock_for(wcur, env_w))
        wcur.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
                     (json.dumps(env_w),))
        r_w = wcur.fetchone()[0]
        check(f"E1: worker round {rounds_e1} not failed",
              r_w["failed"] is False, r_w)
        wcur.execute("SELECT v13_renew_lease(%s, %s, 60000)",
                     (je_e1, ck_e1["fence"]))
        renew_ok = renew_ok and wcur.fetchone()[0] is True
        rounds_e1 += 1
        wconn.commit()
        if rounds_e1 > 6:
            break
    check("E1: worker rounds = 2 (existence + chunk)",
          rounds_e1 == 2, rounds_e1)
    check("E1: renew always true", renew_ok is True)
    wcur.execute("SELECT v13_renew_lease(%s, %s, 60000)",
                 (je_e1, ck_e1["fence"] + 99))
    check("E1: fence mismatch renew false",
          wcur.fetchone()[0] is False)
    wcur.execute(
        "SELECT v13_complete(%s, %s, %s, 'succeeded', NULL)",
        (je_e1, ck_e1["attempt_no"], ck_e1["fence"]))
    check("E1: complete accepted", wcur.fetchone()[0] == "accepted")
    wconn.commit()
    wconn.close()
    C.open_fresh()
    p_e1b = parse_mock(C.cur, sid_e1)
    check("E1: reparse zero ask", p_e1b["asked_questions"] == 0, p_e1b)
    C.commit()
    C.cur.execute("SELECT v13_advance(%s, %s::jsonb)",
                (sid_e1, json.dumps(p_e1b)))
    a_e1b = C.cur.fetchone()[0]
    if a_e1b == "waiting":
        C.cur.execute(
            "SELECT effect_id FROM effects WHERE session_id=%s "
            "AND kind='context_refresh' AND status='ready'", (sid_e1,))
        rrow = C.cur.fetchone()
        if rrow:
            out_r, _ = settle(C.cur, rrow[0])
            check("E1: post-worker refresh settled", out_r == "accepted", out_r)
            C.commit()
            C.open_fresh()
            p_e1c = parse_mock(C.cur, sid_e1)
            C.commit()
            C.cur.execute("SELECT v13_advance(%s, %s::jsonb)",
                        (sid_e1, json.dumps(p_e1c)))
            a_e1b = C.cur.fetchone()[0]
    check("E1: advance routes through (no new judge)",
          a_e1b in ("progressed", "waiting", "terminal"), a_e1b)
    C.cur.execute(
        "SELECT count(*) FROM effects WHERE session_id=%s AND kind='judge'",
        (sid_e1,))
    check("E1: single judge effect", C.cur.fetchone()[0] == 1)
    C.cur.execute(
        "SELECT count(*) FROM judgment_calls WHERE session_id=%s "
        "AND status='succeeded'", (sid_e1,))
    check("E1: calls total = 3 (canonical+existence+chunk)",
          C.cur.fetchone()[0] == 3)
    C.commit()

    print("[info] E2 ingest 64 docs (4 tiers x 16)")
    C.cur.execute(
        "SELECT value FROM v13_policies WHERE name='recall_k' AND active")
    rk_e2 = C.cur.fetchone()[0]
    bump_policy(C.cur, "recall_k", {**rk_e2, "k_base": 64})
    C.commit()
    C.cur.execute(
        "DO $b$ DECLARE i int; BEGIN "
        "FOR i IN 1..64 LOOP "
        "PERFORM v13_ingest_document(%s::uuid, 'e2', "
        "'e2tok tier doc ' || i::text || ' ' || %s); "
        "END LOOP; END $b$;",
        (str(eid_ops), u()))
    C.commit()
    sid_e2 = new_session(C.cur)
    append_user(C.cur, sid_e2, "e2tok")
    p_e2 = answers_sql(C.cur, sid_e2)
    check("E2: k=64 remaining", p_e2["remaining"] == 65,
          p_e2["remaining"])
    C.commit()
    parse_settle(server, C, sid_e2, snap=p_e2)
    live_e2 = with_current_probe(C.cur, sid_e2, p_e2)
    C.cur.execute("SELECT v13_advance(%s, %s::jsonb)",
                (sid_e2, json.dumps(live_e2)))
    check("E2: waiting", C.cur.fetchone()[0] == "waiting")
    C.cur.execute(
        "SELECT effect_id FROM effects WHERE session_id=%s AND kind='judge' "
        "AND status='ready'", (sid_e2,))
    je_row2 = C.cur.fetchone()
    check("E2: judge effect ready", je_row2 is not None)
    je_e2 = je_row2[0]
    C.commit()
    wconn = psycopg2.connect(server.get_uri(DB))
    wconn.autocommit = False
    wcur = wconn.cursor()
    guc(wcur)
    ck_e2 = claim_pinned(wcur, je_e2)
    env_w2 = ck_e2["request"]["envelope"]
    rounds_e2 = 0
    while True:
        wcur.execute("SELECT v13_gap(%s::jsonb)", (json.dumps(env_w2),))
        if not wcur.fetchone()[0]:
            break
        set_mock(wcur, mock_for(wcur, env_w2))
        wcur.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
                     (json.dumps(env_w2),))
        r_w2 = wcur.fetchone()[0]
        check(f"E2: round {rounds_e2} ok", r_w2["failed"] is False, r_w2)
        wcur.execute("SELECT v13_renew_lease(%s, %s, 60000)",
                     (je_e2, ck_e2["fence"]))
        check(f"E2: round {rounds_e2} renew", wcur.fetchone()[0] is True)
        rounds_e2 += 1
        wconn.commit()
        if rounds_e2 > 8:
            break
    check("E2: slow-path rounds = 3 (existence + ceil(64/32))",
          rounds_e2 == 3, rounds_e2)
    wcur.execute(
        "SELECT v13_complete(%s, %s, %s, 'succeeded', NULL)",
        (je_e2, ck_e2["attempt_no"], ck_e2["fence"]))
    check("E2: complete accepted", wcur.fetchone()[0] == "accepted")
    wconn.commit()
    wconn.close()
    C.open_fresh()
    C.cur.execute(
        "SELECT count(*) FROM judgment_calls WHERE session_id=%s "
        "AND status='succeeded'", (sid_e2,))
    calls_e2 = C.cur.fetchone()[0]
    check("E2: calls total = 4 (one-page ledger)", calls_e2 == 4, calls_e2)
    C.cur.execute(
        "SELECT question_count FROM judgment_calls WHERE session_id=%s "
        "AND projection_key='chunk_score' ORDER BY created_at", (sid_e2,))
    qc_e2 = [r[0] for r in C.cur.fetchall()]
    check("E2: chunk batches are 32+32", qc_e2 == [32, 32], qc_e2)
    bump_policy(C.cur, "recall_k", rk_e2)
    C.commit()

    for i in range(3):
        ingest_doc(C.cur, f"e3tok evidence doc {i} {u()}", "e3", eid=eid_ops)
    C.commit()
    sid_e3 = new_session(C.cur)
    append_user(C.cur, sid_e3, "e3tok")
    answers_sql(C.cur, sid_e3)
    C.commit()
    env_e3 = env_of(C.cur, sid_e3)
    gap_e3 = gap_of(C.cur, env_e3)
    chunk_gap_e3 = [g["signal"] for g in gap_e3
                    if g["signal"].startswith("chunk::")]
    check("E3: chunk gap present", len(chunk_gap_e3) >= 2, chunk_gap_e3)
    for sig in chunk_gap_e3:
        C.cur.execute(
            "SELECT v13_judgment_hash(%s::jsonb, %s, 'score', %s, %s::jsonb)",
            (json.dumps(env_e3), sig, SCORE_Q,
             json.dumps(env_e3["needed"][0].get("criteria") or SCORE_CRITERIA)))
        # build hash exactly as resolve does
        row = next(n for n in env_e3["needed"] if n["signal"] == sig)
        C.cur.execute(
            "SELECT v13_judgment_hash(%s::jsonb, %s, %s, %s, %s::jsonb)",
            (json.dumps(env_e3), sig, row["kind"], row["question"],
             json.dumps(row.get("criteria"))))
        bad_hash = C.cur.fetchone()[0]
        C.cur.execute(
            "INSERT INTO judgment_cache (request_hash, signal, kind, answer,"
            " provider, model, template_name, template_version,"
            " answer_schema_version) VALUES (%s, %s, 'score', %s::jsonb,"
            " 'mock', 'jev-mock', 'chunk_score', 1, 1)",
            (bad_hash, sig,
             json.dumps({"type": "score", "score": 9, "confidence": 0.9})))
    C.commit()
    env_e3 = env_of(C.cur, sid_e3)
    set_mock(C.cur, mock_for(C.cur, env_e3,
                           {CORPUS_EXISTS: {"type": "noul", "noul": 0.85}}))
    C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
                (json.dumps(env_e3),))
    C.cur.fetchone()
    C.open_fresh()
    env_e3 = env_of(C.cur, sid_e3)
    set_mock(C.cur, mock_for(C.cur, env_e3))
    C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 10)",
                (json.dumps(env_e3),))
    r_e3 = C.cur.fetchone()[0]
    check("E3: poisoned per-chunk batch failed=true (no progress)",
          r_e3["failed"] is True, r_e3)
    check("E3: readback rejects counted", r_e3["readback_rejects"] >= 1, r_e3)
    C.cur.execute(
        "SELECT count(*) FROM decisions WHERE session_id=%s "
        "AND signal LIKE 'chunk::%%'", (sid_e3,))
    check("E3: zero chunk decisions landed", C.cur.fetchone()[0] == 0)
    C.commit()

    for i in range(2):
        ingest_doc(C.cur, f"e4tok evidence doc {i} {u()}", "e4", eid=eid_ops)
    C.commit()
    sid_e4 = new_session(C.cur)
    append_user(C.cur, sid_e4, "e4tok")
    answers_sql(C.cur, sid_e4)
    C.commit()
    env_e4 = env_of(C.cur, sid_e4)
    set_mock(C.cur, mock_for(C.cur, env_e4,
                           {CORPUS_EXISTS: {"type": "noul", "noul": 0.85}}))
    C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
                (json.dumps(env_e4),))
    C.cur.fetchone()
    C.open_fresh()
    env_e4 = env_of(C.cur, sid_e4)
    gap_e4 = gap_of(C.cur, env_e4)
    sigs_e4 = [g["signal"] for g in gap_e4
               if g["signal"].startswith("chunk::")][:2]
    bad_answers = {s: {"type": "score", "score": 99, "confidence": 0.9}
                   for s in sigs_e4}
    set_mock(C.cur, mock_for(C.cur, env_e4, bad_answers))
    C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 10)",
                (json.dumps(env_e4),))
    r_e4 = C.cur.fetchone()[0]
    check("E4: beta reject failed=true", r_e4["failed"] is True, r_e4)
    C.cur.execute(
        "SELECT status FROM judgment_calls WHERE session_id=%s "
        "ORDER BY created_at DESC LIMIT 1", (sid_e4,))
    check("E4: failed_validation call row",
          C.cur.fetchone()[0] == "failed_validation")
    C.cur.execute(
        "SELECT count(*) FROM decisions WHERE session_id=%s "
        "AND signal LIKE 'chunk::%%'", (sid_e4,))
    check("E4: zero chunk decisions", C.cur.fetchone()[0] == 0)
    C.cur.execute(
        "SELECT count(*) FROM judgment_cache WHERE signal LIKE 'chunk::%%' "
        "AND request_hash IN (SELECT request_hash FROM decisions WHERE "
        "session_id=%s)", (sid_e4,))
    C.commit()

    # E5 alpha: (a) remote-error propagation (engine fact), (b) unclassified
    # cancel raises query_canceled mid filter ask.
    for i in range(2):
        ingest_doc(C.cur, f"e5atok evidence doc {i} {u()}", "e5a", eid=eid_ops)
    C.commit()
    sid_e5 = new_session(C.cur)
    append_user(C.cur, sid_e5, "e5atok")
    answers_sql(C.cur, sid_e5)
    C.commit()
    env_e5 = env_of(C.cur, sid_e5)
    port_e5, stop_e5 = hanging_server()
    C.cur.execute("SELECT set_config('typesafe.endpoint', %s, true)",
                (f"http://127.0.0.1:{port_e5}/",))
    C.cur.execute("SELECT set_config('typesafe.api_key', 'probe', true)")
    C.cur.execute("SELECT set_config('typesafe.mock_response', NULL, true)")
    C.cur.execute("SELECT set_config('typesafe.timeout_ms', '5000', true)")
    C.cur.execute("SET LOCAL statement_timeout = '50ms'")
    box_e5 = {}
    try:
        C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 10)",
                    (json.dumps(env_e5),))
        box_e5["r"] = C.cur.fetchone()[0]
    except psycopg2.Error as exc:
        box_e5["e"] = exc
    stop_e5.set()
    check("E5-a: remote/timeout-family error propagates (fail-loud)",
          "e" in box_e5 and box_e5["e"].pgcode not in (None, "V3001"),
          {k: getattr(v, "pgcode", v) for k, v in box_e5.items()})
    C.cur.execute("ROLLBACK")
    C.open_fresh()

    for i in range(2):
        ingest_doc(C.cur, f"e5ctok evidence doc {i} {u()}", "e5c", eid=eid_ops)
    C.commit()
    sid_e5c = new_session(C.cur)
    append_user(C.cur, sid_e5c, "e5ctok")
    answers_sql(C.cur, sid_e5c)
    C.commit()
    env_e5c = env_of(C.cur, sid_e5c)
    mock_e5c = mock_for(C.cur, env_e5c,
                        {CORPUS_EXISTS: {"type": "noul", "noul": 0.85}})
    C.cur.execute("""
        CREATE OR REPLACE FUNCTION v13_e5_pause() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          PERFORM pg_advisory_xact_lock(879011);
          RETURN NEW;
        END $$;
    """)
    C.cur.execute("DROP TRIGGER IF EXISTS trg_e5_pause ON judgment_calls")
    C.cur.execute(
        "CREATE TRIGGER trg_e5_pause BEFORE INSERT ON judgment_calls "
        "FOR EACH ROW EXECUTE FUNCTION v13_e5_pause()")
    C.commit()
    C.open_fresh()
    C.cur.execute("SELECT pg_advisory_lock(879011)")
    C.cur.execute("SELECT count(*) FROM judgment_calls")
    calls_before_e5 = C.cur.fetchone()[0]
    box_c = {}

    def run_e5_cancel():
        c = psycopg2.connect(server.get_uri(DB))
        k = c.cursor()
        guc(k)
        k.execute("SET statement_timeout = 0")
        k.execute("SELECT pg_backend_pid()")
        box_c["pid"] = k.fetchone()[0]
        set_mock(k, mock_e5c)
        try:
            k.execute("SELECT v13_resolve_judgments(%s::jsonb, 10)",
                      (json.dumps(env_e5c),))
            box_c["r"] = k.fetchone()[0]
            c.commit()
        except Exception as exc:
            box_c["e"] = exc
        c.close()

    th_e5 = threading.Thread(target=run_e5_cancel)
    th_e5.start()
    t0_e5 = time.time()
    while time.time() - t0_e5 < 4 and not box_c.get("pid"):
        time.sleep(0.02)
    time.sleep(0.3)
    C.cur.execute("SELECT pg_cancel_backend(%s)", (box_c["pid"],))
    C.cur.execute("SELECT pg_advisory_unlock(879011)")
    th_e5.join(10)
    check("E5-b: unclassified cancel raises query_canceled",
          "e" in box_c and getattr(box_c["e"], "pgcode", None) == "57014",
          box_c if "e" not in box_c else box_c["e"].pgcode)
    check("E5-b: not swallowed as failed=true return", "r" not in box_c, box_c)
    C.cur.execute("SELECT count(*) FROM judgment_calls")
    check("E5-b: cancel zero new calls", C.cur.fetchone()[0] == calls_before_e5)
    C.cur.execute("DROP TRIGGER IF EXISTS trg_e5_pause ON judgment_calls")
    C.cur.execute("DROP FUNCTION IF EXISTS v13_e5_pause()")
    C.commit()

    tok_e6 = "e6tok belt"
    sid_e6 = new_session(C.cur)
    append_user(C.cur, sid_e6, tok_e6)
    for i in range(2):
        ingest_doc(C.cur, f"{tok_e6} doc {i} {u()}", "e6", eid=eid_ops)
    C.commit()
    answers_sql(C.cur, sid_e6)
    C.commit()
    env_e6 = env_of(C.cur, sid_e6)
    hashes_e6 = [c["content_hash"] for c in env_e6["candidates"]]
    for h in hashes_e6:
        C.cur.execute("DELETE FROM chunks WHERE content_hash=%s", (h,))
    C.commit()
    set_mock(C.cur, mock_for(C.cur, env_e6))
    C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 10)",
                (json.dumps(env_e6),))
    r_e6 = C.cur.fetchone()[0]
    check("E6: bodies guard failed=false", r_e6["failed"] is False, r_e6)
    check("E6: remaining 0 with all gaps body-missing", r_e6["remaining"] == 0,
          r_e6)
    C.cur.execute(
        "SELECT count(*) FROM judgment_calls WHERE session_id=%s "
        "AND projection_key IN ('corpus_exists','chunk_score')", (sid_e6,))
    check("E6: zero filter asks, zero calls rows",
          C.cur.fetchone()[0] == 0)
    C.cur.execute(
        "SELECT count(*) FROM judgment_cache WHERE signal='corpus_exists' "
        "AND request_hash IN (SELECT request_hash FROM decisions "
        "WHERE session_id=%s)", (sid_e6,))
    check("E6: zero existence cache rows still",
          C.cur.fetchone()[0] == 0)
    C.commit()

    for i in range(2):
        ingest_doc(C.cur, f"e7tok evidence doc {i} {u()}", "e7", eid=eid_ops)
    C.commit()
    sid_e7 = new_session(C.cur)
    append_user(C.cur, sid_e7, "e7tok")
    env_e7 = env_of(C.cur, sid_e7)
    set_mock(C.cur, mock_for(C.cur, env_e7))
    C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
                (json.dumps(env_e7),))
    r_e7 = C.cur.fetchone()[0]
    check("E7: canonical first (1 batch, 0 filter asks)",
          r_e7["asked_batches"] == 1 and r_e7["asked_questions"] > 0, r_e7)
    C.cur.execute(
        "SELECT count(*) FROM judgment_calls WHERE session_id=%s "
        "AND projection_key IN ('corpus_exists','chunk_score')", (sid_e7,))
    check("E7: zero filter calls before canonical clears",
          C.cur.fetchone()[0] == 0)
    C.commit()
    env_e7b = env_of(C.cur, sid_e7)
    set_mock(C.cur, mock_for(C.cur, env_e7b,
                           {CORPUS_EXISTS: {"type": "noul", "noul": 0.85}}))
    C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
                (json.dumps(env_e7b),))
    C.cur.fetchone()
    C.cur.execute(
        "SELECT projection_key FROM judgment_calls WHERE session_id=%s "
        "ORDER BY created_at", (sid_e7,))
    labels_e7 = [r[0] for r in C.cur.fetchall()]
    check("E7: filter face starts after canonical clears",
          labels_e7[-1] == CORPUS_EXISTS, labels_e7)
    C.commit()

    sid_e8 = new_session(C.cur)
    append_user(C.cur, sid_e8, "e8tok probe")
    p_e8 = answers_sql(C.cur, sid_e8)
    check("E8: parse exit seven keys", keys_of(p_e8) == PARSE7, keys_of(p_e8))
    C.cur.execute(
        "SELECT jsonb_typeof(v->'abandon'), jsonb_typeof(v->'failed'),"
        " jsonb_typeof(v->'asked_questions'), jsonb_typeof(v->'remaining')"
        " FROM (SELECT %s::jsonb v) q", (json.dumps(p_e8),))
    t_ab, t_fl, t_aq, t_rm = C.cur.fetchone()
    check("E8: exit field types",
          (t_ab, t_fl, t_aq, t_rm) == ("boolean", "boolean", "number", "number"),
          (t_ab, t_fl, t_aq, t_rm))
    check("E8: no gate_open in parse exit", "gate_open" not in p_e8)
    env_e8 = env_of(C.cur, sid_e8)
    C.cur.execute(
        "SELECT jsonb_typeof(v13_resolve_judgments(%s::jsonb, 1)->'gate_open')"
        " IS DISTINCT FROM 'boolean' ", (json.dumps(env_e8),))
    check("E8: resolve direct returns boolean gate_open",
          C.cur.fetchone()[0] is False)
    C.commit()

    # ----- F manifest wiring + F1 poisoning -----
    sid_f = new_session(C.cur)
    append_user(C.cur, sid_f, "f4tok evidence")
    for i in range(2):
        ingest_doc(C.cur, f"f4tok evidence document {i} {u()}", "f4", eid=eid_ops)
    C.commit()
    env_f = env_of(C.cur, sid_f)
    f_hashes = [c["content_hash"] for c in env_f["candidates"]]
    check("F: two candidates", len(f_hashes) == 2, f_hashes)
    chunk_over_f = {
        "chunk::" + f_hashes[0]: {"type": "score", "score": 0, "confidence": 0.9},
        "chunk::" + f_hashes[1]: {"type": "score", "score": 3, "confidence": 0.9},
    }
    answers_sql(C.cur, sid_f)
    C.commit()
    env_f = env_of(C.cur, sid_f)
    set_mock(C.cur, mock_for(C.cur, env_f,
                           {CORPUS_EXISTS: {"type": "noul", "noul": 0.85}}))
    C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
                (json.dumps(env_f),))
    C.cur.fetchone()
    C.open_fresh()
    env_f = env_of(C.cur, sid_f)
    set_mock(C.cur, mock_for(C.cur, env_f, chunk_over_f))
    C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 10)",
                (json.dumps(env_f),))
    C.cur.fetchone()
    C.commit()
    parse_settle(server, C, sid_f)
    man_f = active_manifest(C.cur, sid_f)
    cands_f = man_f["query_side"]["candidates"]
    check("F1: candidates four keys",
          all(keys_of(c) == CAND4 for c in cands_f), cands_f)
    decided_f = [c for c in cands_f if c["decision_id"] is not None]
    check("F1: both include and exclude verdicts in consumption set",
          len(decided_f) == 2, [c.get("decision_id") for c in cands_f])
    C.cur.execute(
        "SELECT decision_id FROM decisions WHERE session_id=%s "
        "AND signal LIKE 'chunk::%%' AND answer IS NOT NULL", (sid_f,))
    dec_ids_f = {str(r[0]) for r in C.cur.fetchall()}
    check("F1: decision_ids join decisions",
          {str(c["decision_id"]) for c in decided_f} == dec_ids_f,
          (dec_ids_f, {str(c["decision_id"]) for c in decided_f}))
    C.cur.execute("SELECT v13_manifest_validate(%s::jsonb)",
                (json.dumps(man_f),))
    check("F1: validator green", True)

    juds_f = man_f["judgments"]
    check("F2: judgments non-empty",
          len(juds_f) == 3, len(juds_f))
    check("F2: epochs pre-finalize per row",
          all(j["epoch"] == "pre-finalize" for j in juds_f), juds_f)
    C.cur.execute(
        "SELECT decision_id::text, answer FROM decisions WHERE session_id=%s "
        "AND signal IN ('corpus_exists','chunk::'||%s,'chunk::'||%s)",
        (sid_f, f_hashes[0], f_hashes[1]))
    raw_map = {r[0]: r[1] for r in C.cur.fetchall()}
    check("F2: raw_verdict is decisions.answer verbatim",
          all(j["raw_verdict"] == raw_map.get(j["decision_id"])
              for j in juds_f if j["decision_id"] in raw_map), juds_f)
    check("F2: final_action vocabulary",
          all(j["final_action"] in ("include", "exclude", "degrade")
              for j in juds_f), {j["final_action"] for j in juds_f})
    C.cur.execute("SELECT * FROM v13_filter_trace(%s)", (sid_f,))
    trace_f = C.cur.fetchall()
    check("F2: trace rows carry action/basis",
          all(a in ("include", "exclude", "degrade")
              and b in ("decision", "decision_review", "default_timeout",
                        "gate_closed", "default_missing")
              for _, _, a, b in [(r[0], r[1], r[2], r[3]) for r in trace_f]),
          trace_f)
    trace_actions = {r[0]: r[2] for r in trace_f}
    # dp6.1 P2-2 强化:对照域=decided candidates(trace 是候选级面,存在性
    # judgment 结构性无 trace 行——按全集字面实现会永久红;候选缺行必红,
    # 不再静默跳过)。
    jud_by_id_f2 = {str(j["decision_id"]): j for j in juds_f
                    if j["decision_id"]}
    for c_f2 in decided_f:
        t_h = next((r[0] for r in trace_f
                    if r[1] and str(r[1]) == str(c_f2["decision_id"])), None)
        check("F2: decided candidate has matching trace row",
              t_h is not None,
              (c_f2["decision_id"], c_f2.get("content_hash"), trace_f))
        if t_h is not None:
            j_f2 = jud_by_id_f2[str(c_f2["decision_id"])]
            check("F2: trace action equals judgment final_action",
                  trace_actions[t_h] == j_f2["final_action"],
                  (t_h, trace_actions[t_h], j_f2["final_action"]))
    C.cur.execute("SELECT v13_manifest_validate(%s::jsonb)",
                (json.dumps(man_f),))
    check("F2: direct revalidate green", True)

    for i in range(2):
        ingest_doc(C.cur, f"f3tok evidence document {i} {u()}", "f3", eid=eid_ops)
    C.commit()
    sid_f3 = new_session(C.cur)
    append_user(C.cur, sid_f3, "f3tok evidence")
    answers_sql(C.cur, sid_f3)
    C.commit()
    env_f3 = env_of(C.cur, sid_f3)
    set_mock(C.cur, mock_for(C.cur, env_f3,
                           {CORPUS_EXISTS: {"type": "noul", "noul": 0.10}}))
    C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 10)",
                (json.dumps(env_f3),))
    C.cur.fetchone()
    C.commit()
    parse_settle(server, C, sid_f3)
    man_f3 = active_manifest(C.cur, sid_f3)
    check("F3: gate-closed candidates all NULL decision_id",
          all(c["decision_id"] is None
              for c in man_f3["query_side"]["candidates"]),
          man_f3["query_side"]["candidates"])
    check("F3: judgments exactly one existence row",
          len(man_f3["judgments"]) == 1
          and man_f3["judgments"][0]["final_action"] == "exclude",
          man_f3["judgments"])
    C.cur.execute("SELECT v13_manifest_validate(%s::jsonb)",
                (json.dumps(man_f3),))
    check("F3: validator green", True)
    check("F3: sections three (goal/history/tools)",
          sorted(s["section_id"] for s in man_f3["sections"]) ==
          ["goal", "history", "tools"],
          [s["section_id"] for s in man_f3["sections"]])

    for i in range(2):
        ingest_doc(C.cur, f"f4atok evidence document {i} {u()}", "f4a", eid=eid_ops)
    C.commit()
    sid_f4a = new_session(C.cur)
    append_user(C.cur, sid_f4a, "f4atok evidence")
    p_f4a = answers_sql(C.cur, sid_f4a)
    C.commit()
    env_f4a = env_of(C.cur, sid_f4a)
    set_mock(C.cur, mock_for(C.cur, env_f4a,
                           {CORPUS_EXISTS: {"type": "noul", "noul": 0.85}}))
    C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
                (json.dumps(env_f4a),))
    C.cur.fetchone()
    C.commit()
    parse_settle(server, C, sid_f4a, snap=p_f4a)
    C.cur.execute("SELECT * FROM v13_filter_trace(%s)", (sid_f4a,))
    trace_f4a = C.cur.fetchall()
    check("F4-1: missing -> include/default_missing everywhere",
          all(a == "include" and b == "default_missing"
              for _, _, a, b in trace_f4a), trace_f4a)
    man_f4a = active_manifest(C.cur, sid_f4a)
    check("F4-1: candidates decision_id all NULL",
          all(c["decision_id"] is None
              for c in man_f4a["query_side"]["candidates"]))
    check("F4-1: judgments only existence",
          len(man_f4a["judgments"]) == 1
          and man_f4a["judgments"][0]["final_action"] == "include")

    for i in range(2):
        ingest_doc(C.cur, f"f4btok evidence document {i} {u()}", "f4b", eid=eid_ops)
    C.commit()
    sid_f4b = new_session(C.cur)
    append_user(C.cur, sid_f4b, "f4btok evidence")
    answers_sql(C.cur, sid_f4b)
    C.commit()
    env_f4b = env_of(C.cur, sid_f4b)
    gh_f4b = env_f4b["goal_hash"]
    set_mock(C.cur, mock_for(C.cur, env_f4b,
                           {CORPUS_EXISTS: {"type": "noul", "noul": 0.85}}))
    C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
                (json.dumps(env_f4b),))
    C.cur.fetchone()
    C.commit()
    env_f4b2 = env_of(C.cur, sid_f4b)
    for h in [c["content_hash"] for c in env_f4b2["candidates"]]:
        row_h = next(n for n in env_f4b2["needed"]
                     if n["signal"] == "chunk::" + h)
        C.cur.execute(
            "SELECT v13_judgment_hash(%s::jsonb, %s, %s, %s, %s::jsonb)",
            (json.dumps(env_f4b2), "chunk::" + h, row_h["kind"],
             row_h["question"], json.dumps(row_h.get("criteria"))))
        rh = C.cur.fetchone()[0]
        C.cur.execute(
            "INSERT INTO decisions (session_id, signal, kind, question,"
            " criteria, context, answer, request_hash, status, template_name,"
            " template_version) VALUES (%s, %s, 'score', %s, NULL,"
            " v13_filter_ref(%s, %s), NULL, %s, 'failed', 'chunk_score', 1)",
            (sid_f4b, "chunk::" + h, SCORE_Q, gh_f4b, h, rh))
    C.commit()
    C.cur.execute("SELECT * FROM v13_filter_trace(%s)", (sid_f4b,))
    trace_f4b = C.cur.fetchall()
    check("F4-2: timeout rows -> include/default_timeout",
          all(a == "include" and b == "default_timeout"
              for _, _, a, b in trace_f4b), trace_f4b)

    for i in range(2):
        ingest_doc(C.cur, f"f4ctok evidence document {i} {u()}", "f4c", eid=eid_ops)
    C.commit()
    sid_f4c = new_session(C.cur)
    append_user(C.cur, sid_f4c, "f4ctok evidence")
    answers_sql(C.cur, sid_f4c)
    C.commit()
    env_f4c = env_of(C.cur, sid_f4c)
    h_f4c = env_f4c["candidates"][0]["content_hash"]
    set_mock(C.cur, mock_for(C.cur, env_f4c,
                           {CORPUS_EXISTS: {"type": "noul", "noul": 0.85}}))
    C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
                (json.dumps(env_f4c),))
    C.cur.fetchone()
    C.open_fresh()
    env_f4c = env_of(C.cur, sid_f4c)
    low_conf = {"chunk::" + c["content_hash"]:
                {"type": "score", "score": 3, "confidence": 0.30}
                for c in env_f4c["candidates"]}
    set_mock(C.cur, mock_for(C.cur, env_f4c, low_conf))
    C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 10)",
                (json.dumps(env_f4c),))
    C.cur.fetchone()
    C.commit()
    C.cur.execute("SELECT * FROM v13_filter_trace(%s)", (sid_f4c,))
    trace_f4c = C.cur.fetchall()
    check("F4-3: review rows -> degrade/decision_review",
          all(a == "degrade" and b == "decision_review"
              for _, _, a, b in trace_f4c), trace_f4c)
    bases_f4 = ({r[3] for r in trace_f4a}, {r[3] for r in trace_f4b},
                {r[3] for r in trace_f4c})
    check("F4: three forms partition basis vocabulary",
          bases_f4 == ({"default_missing"}, {"default_timeout"},
                       {"decision_review"}), bases_f4)

    C.cur.execute("SELECT v13_assemble_manifest(%s)", (sid_f,))
    m1_f5 = C.cur.fetchone()[0]
    C.cur.execute("SELECT v13_assemble_manifest(%s)", (sid_f,))
    m2_f5 = C.cur.fetchone()[0]
    check("F5: assemble deterministic", m1_f5 == m2_f5)
    C.cur.execute("SELECT * FROM v13_filter_trace(%s)", (sid_f,))
    t1_f5 = C.cur.fetchall()
    C.cur.execute("SELECT * FROM v13_filter_trace(%s)", (sid_f,))
    t2_f5 = C.cur.fetchall()
    check("F5: trace deterministic", t1_f5 == t2_f5)

    # F5b(dp6.1 P2-4):多世代 decision 行确定性——同 (session,signal,
    # context) 双 answered 行(session 中途 provider/model 换代重问;直插
    # owner 平面,G2 手工 DML 同款),消费必须确定性取 newest active
    # (answered_at DESC,decision_id 终裁):旧世代 include/新世代 exclude
    # →终局 exclude+新 decision_id。两世界:无 ORDER BY 时 planner 常取
    # 堆序首行(旧 include)→断言红;有 ORDER BY→确定性 newest。
    sid_f5b = new_session(C.cur)
    h_f5b = "f5b" + "0" * 61          # 64hex(v13_filter_ref 校验);chunk::
    gh_f5b = "e5b" + "0" * 61         # 前缀命名空间+全新会话,零碰撞面
    C.cur.execute("SELECT v13_filter_ref(%s, %s)", (gh_f5b, h_f5b))
    ctx_f5b = C.cur.fetchone()[0]
    C.cur.execute(
        "INSERT INTO decisions (session_id, signal, kind, question, context,"
        " answer, request_hash, status, answered_at, template_name,"
        " template_version) VALUES"
        " (%s, %s, 'score', %s, %s,"
        "  '{\"score\": 2.9, \"confidence\": 0.9}'::jsonb, %s, 'answered',"
        "  now() - interval '2 minutes', 'chunk_score', 1),"
        " (%s, %s, 'score', %s, %s,"
        "  '{\"score\": 0.4, \"confidence\": 0.9}'::jsonb, %s, 'answered',"
        "  now(), 'chunk_score', 1)",
        (sid_f5b, "chunk::" + h_f5b, SCORE_Q, json.dumps(ctx_f5b), u(),
         sid_f5b, "chunk::" + h_f5b, SCORE_Q, json.dumps(ctx_f5b), u()))
    C.commit()
    C.cur.execute(
        "SELECT decision_id::text FROM decisions WHERE session_id=%s"
        " AND answered_at IS NOT NULL ORDER BY answered_at", (sid_f5b,))
    ids_f5b = [r[0] for r in C.cur.fetchall()]
    check("F5: multi-generation fixture (two answered rows)",
          len(ids_f5b) == 2, ids_f5b)
    C.cur.execute("SELECT v13_chunk_filter_action(%s, %s, %s, %s)",
                  (sid_f5b, gh_f5b, "f5b-digest", h_f5b))
    act_f5b = C.cur.fetchone()[0]
    check("F5: newest active generation wins deterministically",
          act_f5b["action"] == "exclude" and
          act_f5b["basis"] == "decision" and
          str(act_f5b["decision_id"]) == ids_f5b[-1], act_f5b)

    C.cur.execute(
        "SELECT value FROM v13_policies WHERE name='judgment_defaults' AND active")
    jd_f6 = C.cur.fetchone()[0]
    sid_f6 = new_session(C.cur)
    append_user(C.cur, sid_f6, "f4tok evidence")
    parse_settle(server, C, sid_f6)
    C.cur.execute("SELECT v13_context_fresh(%s)", (sid_f6,))
    check("F6: fresh before flip", C.cur.fetchone()[0] is True)
    bump_policy(C.cur, "judgment_defaults", json.loads(json.dumps(jd_f6)))
    C.commit()
    C.cur.execute("SELECT v13_context_fresh(%s)", (sid_f6,))
    check("F6: jdef_ver flip makes context stale",
          C.cur.fetchone()[0] is False)
    parse_settle(server, C, sid_f6)
    C.cur.execute("SELECT v13_context_fresh(%s)", (sid_f6,))
    check("F6: fresh after one settle", C.cur.fetchone()[0] is True)
    C.cur.execute(
        "SELECT value FROM v13_policies WHERE name='chunk_filter' AND active")
    cf_f6 = C.cur.fetchone()[0]
    bump_policy(C.cur, "chunk_filter", json.loads(json.dumps(cf_f6)))
    C.commit()
    C.cur.execute("SELECT v13_context_fresh(%s)", (sid_f6,))
    check("F6: chunk_filter flip does not move token (still fresh)",
          C.cur.fetchone()[0] is True)
    bump_policy(C.cur, "judgment_defaults", jd_f6)
    bump_policy(C.cur, "chunk_filter", cf_f6)
    C.commit()

    C.cur.execute(
        "SELECT context_active_artifact FROM sessions WHERE session_id=%s",
        (sid_f,))
    art_f7 = C.cur.fetchone()[0]
    C.cur.execute("SELECT inline FROM artifacts WHERE artifact_id=%s", (art_f7,))
    m1_bytes_f7 = C.cur.fetchone()[0]
    C.cur.execute("SELECT v13_replay(%s)", (art_f7,))
    replay_f7 = C.cur.fetchone()[0]
    check("F7: exact replay freezes candidates with filter verdicts",
          replay_f7["query_side"]["candidates"] ==
          m1_bytes_f7["query_side"]["candidates"]
          and replay_f7["judgments"] == m1_bytes_f7["judgments"])
    late_h = None
    C.cur.execute(
        "SELECT signal FROM decisions WHERE session_id=%s "
        "AND signal LIKE 'chunk::%%' AND answer IS NULL", (sid_f,))
    row_late = C.cur.fetchone()
    if row_late:
        late_h = row_late[0][7:]
        C.cur.execute(
            "UPDATE decisions SET answer=%s::jsonb, status='answered',"
            " answered_at=now() WHERE session_id=%s AND signal=%s"
            " AND answer IS NULL",
            (json.dumps({"type": "score", "score": 2, "confidence": 0.9}),
             sid_f, "chunk::" + late_h))
        C.commit()
    C.cur.execute(
        "SELECT a.inline FROM sessions s JOIN artifacts a "
        "ON a.artifact_id=s.context_active_artifact WHERE s.session_id=%s",
        (sid_f,))
    check("F7: landed manifest bytes unchanged by late decision",
          C.cur.fetchone()[0] == m1_bytes_f7)
    C.commit()

    # ----- G locks / retention / GIN -----
    C.cur.execute(
        "SELECT signal FROM decisions WHERE session_id=%s "
        "AND signal LIKE 'chunk::%%' AND answer IS NOT NULL LIMIT 1", (sid_f,))
    g1_sig = C.cur.fetchone()[0]
    g1_hash = g1_sig[7:]
    C.cur.execute("SELECT v13_chunk_referenced(%s)", (g1_hash,))
    check("G1: per-chunk decision retains chunk",
          C.cur.fetchone()[0] is True)
    fails_with(C.cur, "DELETE FROM chunks WHERE content_hash=%s", (g1_hash,),
               "referenced", "G1: retained chunk delete rejected",
               pgcode="V3004")
    C.cur.execute(
        "SELECT content_hash FROM chunks c WHERE NOT EXISTS ("
        "SELECT 1 FROM decisions d WHERE d.context->'chunk' @> "
        "jsonb_build_object('content_hash', c.content_hash)) LIMIT 1")
    free_g1 = C.cur.fetchone()
    if free_g1:
        C.cur.execute("DELETE FROM chunks WHERE content_hash=%s", (free_g1[0],))
        check("G1: unreferenced chunk deletes freely", True)
    C.commit()

    C.cur.execute(
        "SELECT d.context->'chunk' @> jsonb_build_object('content_hash', %s)"
        " FROM decisions d WHERE d.session_id=%s AND d.signal=%s",
        (g1_hash, sid_f, g1_sig))
    check("G2: containment hits exact row", C.cur.fetchone()[0] is True)
    C.cur.execute(
        "SELECT count(*) FROM decisions d WHERE d.context->'chunk' @> "
        "jsonb_build_object('content_hash', %s)", (g1_hash,))
    n_new = C.cur.fetchone()[0]
    C.cur.execute(
        "SELECT count(*) FROM decisions d WHERE d.context->'chunk'->>'content_hash' = %s",
        (g1_hash,))
    n_old = C.cur.fetchone()[0]
    check("G2: containment equals legacy extraction", n_new == n_old,
          (n_new, n_old))
    sid_g2 = new_session(C.cur)
    C.cur.execute(
        "INSERT INTO decisions (session_id, signal, kind, question, context,"
        " request_hash) VALUES (%s, 'g2_nokey', 'noul', 'q?', '{}'::jsonb, %s),"
        " (%s, 'g2_scalar', 'noul', 'q?', '{\"chunk\": \"scalar\"}'::jsonb, %s)",
        (sid_g2, u(), sid_g2, u()))
    C.cur.execute(
        "SELECT count(*) FROM decisions d WHERE d.context->'chunk' @> "
        "jsonb_build_object('content_hash', %s)", (g1_hash,))
    check("G2: non-object/absent chunk keys never match",
          C.cur.fetchone()[0] == n_new)
    C.rollback()
    land_eid_g, _ = succeed_tool(C.cur)
    inline_g = {"query_side": {"candidates":
                               [{"content_hash": g1_hash}]}}
    C.cur.execute(
        "SELECT v13_artifact_land(%s, 'context', %s::jsonb)",
        (land_eid_g, json.dumps(inline_g)))
    C.commit()
    C.cur.execute("SELECT v13_chunk_referenced(%s)", (g1_hash,))
    check("G2: artifacts half unchanged (manifest reference hits)",
          C.cur.fetchone()[0] is True)

    C.cur.execute("SET enable_seqscan = off")
    C.cur.execute(
        "EXPLAIN (COSTS OFF) SELECT count(*) FROM decisions "
        "WHERE context->'chunk' @> jsonb_build_object('content_hash', %s)",
        (g1_hash,))
    plan_g3 = "\n".join(r[0] for r in C.cur.fetchall())
    C.cur.execute("SET enable_seqscan = on")
    check("G3: containment binds ix_decisions_chunk_ref",
          "ix_decisions_chunk_ref" in plan_g3
          and "Bitmap Index Scan" in plan_g3, plan_g3)

    tok_g4 = "g4tok lock"
    sid_g4 = new_session(C.cur)
    append_user(C.cur, sid_g4, tok_g4)
    for i in range(2):
        ingest_doc(C.cur, f"{tok_g4} doc {i} {u()}", "g4", eid=eid_ops)
    C.commit()
    answers_sql(C.cur, sid_g4)
    C.commit()
    env_g4 = env_of(C.cur, sid_g4)
    set_mock(C.cur, mock_for(C.cur, env_g4,
                           {CORPUS_EXISTS: {"type": "noul", "noul": 0.85}}))
    C.cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
                (json.dumps(env_g4),))
    C.cur.fetchone()
    C.open_fresh()
    env_g4 = env_of(C.cur, sid_g4)
    aconn = psycopg2.connect(server.get_uri(DB))
    aconn.autocommit = False
    acur = aconn.cursor()
    guc(acur)
    set_mock(acur, mock_for(acur, env_g4))
    acur.execute("SELECT v13_resolve_judgments(%s::jsonb, 10)",
                 (json.dumps(env_g4),))
    r_g4a = acur.fetchone()[0]
    check("G4: writer holds advisory locks uncommitted",
          r_g4a["failed"] is False and r_g4a["asked_questions"] > 0, r_g4a)
    acur.execute("SELECT pg_backend_pid()")
    pid_a_g4 = acur.fetchone()[0]

    bconn = psycopg2.connect(server.get_uri(DB))
    bconn.autocommit = False
    bcur = bconn.cursor()
    bcur.execute("SELECT pg_backend_pid()")
    pid_b_g4 = bcur.fetchone()[0]
    box_g4 = {}

    def run_g4_rebuild():
        try:
            bcur.execute("SET statement_timeout = '8s'")
            bcur.execute("SELECT v13_rebuild_chunks(NULL)")
            box_g4["out"] = bcur.fetchone()[0]
            bconn.commit()
            box_g4["ok"] = True
        except Exception as exc:
            box_g4["err"] = str(exc)
            box_g4["pgcode"] = getattr(exc, "pgcode", None)
            bconn.rollback()
            box_g4["ok"] = False

    th_g4 = threading.Thread(target=run_g4_rebuild)
    th_g4.start()
    blocked_g4 = False
    t0_g4 = time.time()
    while time.time() - t0_g4 < 3 and not box_g4:
        C.cur.execute(
            "SELECT bool_or(NOT granted) FROM pg_locks "
            "WHERE locktype='advisory' AND pid=%s", (pid_b_g4,))
        row = C.cur.fetchone()
        if row and row[0] is True:
            blocked_g4 = True
            break
        time.sleep(0.02)
    check("G4: rebuild queues on writer advisory locks (pg_locks evidence)",
          blocked_g4 is True, {"box": box_g4, "blocked": blocked_g4})
    aconn.commit()
    th_g4.join(12)
    check("G4: rebuild completes after writer commits",
          box_g4.get("ok") is True, box_g4)
    C.cur.execute(
        "SELECT count(*) FROM decisions d WHERE d.session_id=%s "
        "AND d.signal LIKE 'chunk::%%' AND d.answer IS NOT NULL", (sid_g4,))
    n_dec_g4 = C.cur.fetchone()[0]
    C.cur.execute(
        "SELECT count(*) FROM chunks c WHERE c.content_hash IN ("
        "SELECT (context->'chunk'->>'content_hash') FROM decisions "
        "WHERE session_id=%s AND signal LIKE 'chunk::%%')", (sid_g4,))
    check("G4: referenced rows survive rebuild",
          C.cur.fetchone()[0] == n_dec_g4, (n_dec_g4,))
    aconn.close()
    bconn.close()
    C.commit()

    round_results = []
    for rnd in range(3):
        sid_r = new_session(C.cur)
        append_user(C.cur, sid_r, tok_g4)
        C.commit()
        env_r = env_of(C.cur, sid_r)
        box_r = {}

        def run_writer(e=env_r, b=box_r):
            c = psycopg2.connect(server.get_uri(DB))
            c.autocommit = False
            k = c.cursor()
            guc(k)
            try:
                k.execute("SET statement_timeout = '8s'")
                set_mock(k, mock_for(k, e,
                                     {CORPUS_EXISTS: {"type": "noul",
                                                      "noul": 0.85}}))
                k.execute("SELECT v13_resolve_judgments(%s::jsonb, 10)",
                          (json.dumps(e),))
                k.fetchone()
                c.commit()
                b["w"] = "ok"
            except Exception as exc:
                c.rollback()
                b["w"] = getattr(exc, "pgcode", str(exc))
            c.close()

        def run_ingest(b=box_r):
            c = psycopg2.connect(server.get_uri(DB))
            c.autocommit = False
            k = c.cursor()
            guc(k)
            try:
                k.execute("SET statement_timeout = '8s'")
                ingest_doc(k, f"{tok_g4} ingest round doc {u()}",
                           "g4", eid=eid_ops)
                c.commit()
                b["i"] = "ok"
            except Exception as exc:
                c.rollback()
                b["i"] = getattr(exc, "pgcode", str(exc))
            c.close()

        tw = threading.Thread(target=run_writer)
        ti = threading.Thread(target=run_ingest)
        tw.start(); ti.start()
        tw.join(20); ti.join(20)
        check(f"G4: ascending interleave round {rnd} zero 40P01",
              box_r.get("w") == "ok" and box_r.get("i") == "ok", box_r)
        round_results.append(dict(box_r))
    C.open_fresh()

    srcs_g4 = []
    C.cur.execute(
        "SELECT DISTINCT source_hash FROM chunks WHERE corpus='g4' "
        "ORDER BY source_hash LIMIT 2")
    srcs_g4 = [r[0] for r in C.cur.fetchall()]
    box_m = {}

    def run_writer_m(e_env, b):
        c = psycopg2.connect(server.get_uri(DB))
        c.autocommit = False
        k = c.cursor()
        guc(k)
        try:
            k.execute("SET statement_timeout = '8s'")
            set_mock(k, mock_for(k, e_env,
                                 {CORPUS_EXISTS: {"type": "noul", "noul": 0.85}}))
            k.execute("SELECT v13_resolve_judgments(%s::jsonb, 10)",
                      (json.dumps(e_env),))
            k.fetchone()
            c.commit()
            b["w"] = "ok"
        except Exception as exc:
            c.rollback()
            b["w"] = getattr(exc, "pgcode", str(exc))
        c.close()

    def run_rebuild_m(b):
        c = psycopg2.connect(server.get_uri(DB))
        c.autocommit = False
        k = c.cursor()
        guc(k)
        for attempt in range(3):
            try:
                k.execute("SET statement_timeout = '8s'")
                k.execute("SELECT v13_rebuild_chunks('g4')")
                k.fetchone()
                c.commit()
                b["r"] = "ok"
                break
            except Exception as exc:
                k.rollback()
                b["r"] = getattr(exc, "pgcode", str(exc))
                if getattr(exc, "pgcode", None) != "40P01":
                    break
                time.sleep(0.1)
        c.close()

    if len(srcs_g4) >= 2:
        sid_m = new_session(C.cur)
        append_user(C.cur, sid_m, tok_g4)
        C.commit()
        env_m = env_of(C.cur, sid_m)
        thw = threading.Thread(target=run_writer_m, args=(env_m, box_m))
        thr = threading.Thread(target=run_rebuild_m, args=(box_m,))
        thw.start(); thr.start()
        thw.join(20); thr.join(20)
        check("G4: writer ok in multi-source smoke",
              box_m.get("w") == "ok", box_m)
        check("G4: rebuild converges (ok or loud 40P01 retried, never silent)",
              box_m.get("r") == "ok", box_m)
    else:
        check("G4: multi-source smoke fixture present",
              False, srcs_g4)
    C.commit()

    shared_g5 = "g5shared " + ("p" * 3200)
    ingest_doc(C.cur, shared_g5 + "\n\n" + "g5 tail one " + ("q" * 3200),
               "g5a", eid=eid_ops)
    ingest_doc(C.cur, shared_g5 + "\n\n" + "g5 tail two " + ("r" * 3200),
               "g5b", eid=eid_ops)
    C.commit()
    C.cur.execute("SELECT v13_body_hash(%s)", (shared_g5,))
    g5_hash = C.cur.fetchone()[0]
    C.cur.execute(
        "SELECT body, source_hash FROM chunks WHERE content_hash=%s "
        "ORDER BY source_hash, chunk_no", (g5_hash,))
    rows_g5 = C.cur.fetchall()
    check("G5: same hash two rows", len(rows_g5) == 2, len(rows_g5))
    check("G5: bodies equal across sources",
          rows_g5[0][0] == rows_g5[1][0])
    C.cur.execute(
        "SELECT source_hash FROM chunks WHERE content_hash=%s "
        "ORDER BY source_hash, chunk_no LIMIT 1", (g5_hash,))
    first_g5 = C.cur.fetchone()[0]
    C.cur.execute(
        "SELECT source_hash FROM chunks WHERE content_hash=%s "
        "ORDER BY source_hash, chunk_no LIMIT 1", (g5_hash,))
    check("G5: deterministic body lookup (dual run same row)",
          C.cur.fetchone()[0] == first_g5)
    C.commit()

    # ----- H ACL / regression / load -----
    sid_h = new_session(C.cur)
    append_user(C.cur, sid_h, "quasar formation")
    C.commit()
    env_h = env_of(C.cur, sid_h)
    C.cur.execute("SET ROLE v13_recall")
    C.cur.execute("SELECT * FROM v13_filter_trace(%s)", (sid_h,))
    C.cur.fetchall()
    C.cur.execute("SELECT v13_candidates_digest('[]'::jsonb)")
    C.cur.fetchone()
    C.cur.execute("SELECT v13_filter_ref(%s,%s)", ("f" * 64, "e" * 64))
    C.cur.fetchone()
    fails_with(C.cur, "SELECT v13_filter_ask('{}'::jsonb,'{}'::jsonb,"
                    "'[]'::jsonb,'x')", (), "permission",
               "H1: recall cannot EXECUTE filter_ask")
    C.cur.execute("RESET ROLE")

    C.cur.execute("SET ROLE v13_resolve")
    C.cur.execute("SELECT v13_filter_gate_open(%s::jsonb)", (json.dumps(env_h),))
    C.cur.fetchone()
    C.cur.execute("SELECT v13_filter_fillable(%s::jsonb)", (json.dumps(env_h),))
    C.cur.fetchone()
    C.cur.execute("SELECT v13_filter_bodies_present(%s::jsonb)",
                (json.dumps(env_h),))
    C.cur.fetchone()
    C.cur.execute("SELECT v13_filter_defaults_action('chunk_score','missing')")
    C.cur.fetchone()
    C.cur.execute("SELECT * FROM v13_filter_trace(%s)", (sid_h,))
    C.cur.fetchall()
    C.cur.execute("RESET ROLE")

    C.cur.execute("SET ROLE v13_route")
    C.cur.execute("SELECT v13_existence_action(%s::jsonb)",
                (json.dumps({"noul": 0.5}),))
    C.cur.fetchone()
    gh_h = env_h["goal_hash"]
    C.cur.execute("SELECT v13_chunk_filter_action(%s,%s,%s,%s)",
                (sid_h, gh_h, "0" * 64, "1" * 64))
    C.cur.fetchone()
    fails_with(C.cur, "SELECT v13_filter_ask('{}'::jsonb,'{}'::jsonb,"
                    "'[]'::jsonb,'x')", (), "permission",
               "H1: route cannot EXECUTE filter_ask")
    C.cur.execute("RESET ROLE")
    for sig in (
        "v13_candidates_digest(jsonb)",
        "v13_filter_ref(text,text)",
        "v13_existence_ref(jsonb)",
        "v13_row_context(jsonb,text)",
        "v13_require_filter_templates(jsonb)",
        "v13_goal_text(uuid,text)",
        "v13_filter_defaults_action(text,text)",
        "v13_existence_action(jsonb)",
        "v13_filter_gate_open(jsonb)",
        "v13_filter_fillable(jsonb)",
        "v13_filter_bodies_present(jsonb)",
        "v13_chunk_filter_action(uuid,text,text,text)",
        "v13_filter_trace(uuid)",
        "v13_filter_ask(jsonb,jsonb,jsonb,text)",
    ):
        C.cur.execute("SELECT has_function_privilege('public', %s, 'EXECUTE')",
                    (sig,))
        check(f"H1: PUBLIC no {sig}", C.cur.fetchone()[0] is False)

    for sig, role in (
        ("v13_judgment_hash(jsonb,text,text,text,jsonb)", "v13_resolve"),
        ("v13_resolve_judgments(jsonb,int)", "v13_resolve"),
        ("v13_judgment_envelope(uuid)", "v13_route"),
        ("v13_assemble_manifest(uuid,int)", "v13_route"),
    ):
        C.cur.execute("SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                    (role, sig))
        check(f"H2: {role} keeps {sig}", C.cur.fetchone()[0] is True)
    C.cur.execute(
        "SELECT has_function_privilege('public','v13_chunk_referenced(text)',"
        " 'EXECUTE'),"
        " has_function_privilege('v13_recall','v13_chunk_referenced(text)',"
        " 'EXECUTE')")
    pub_cr, rec_cr = C.cur.fetchone()
    check("H2: chunk_referenced ACL unchanged from DP4 (PUBLIC default)",
          pub_cr is True and rec_cr is True, (pub_cr, rec_cr))

    rl = connect_as(server, "v13_resolve_login")
    rlcur = rl.cursor()
    rlcur.execute("SET search_path TO public, pg_catalog")
    rlcur.execute("SELECT set_config('typesafe.provider','mock',false)")
    rlcur.execute("SELECT set_config('typesafe.model','jev-mock',false)")
    rlcur.execute("SELECT count(*) FROM sessions")
    rlcur.fetchone()
    rl.commit()
    sid_h3 = new_session(C.cur)
    append_user(C.cur, sid_h3, "quasar formation")
    C.commit()
    set_mock(rlcur, mock_for(rlcur, sid_h3))
    rlcur.execute("SELECT v13_parse(%s)", (sid_h3,))
    p_h3 = rlcur.fetchone()[0]
    check("H3: resolve_login full parse incl filter face",
          p_h3["failed"] is False and p_h3["asked_questions"] > 0, p_h3)
    rl.rollback()
    rl.close()

    rt = connect_as(server, "v13_route_login")
    rtcur = rt.cursor()
    rtcur.execute("SET search_path TO public, pg_catalog")
    fails_with(rtcur, "SELECT v13_filter_ask('{}'::jsonb,'{}'::jsonb,"
                      "'[]'::jsonb,'x')", (), "permission",
               "H3: route_login cannot EXECUTE filter_ask")
    fails_with(rtcur, "SET ROLE v13_resolve", (), "permission",
               "H3: route_login cannot SET ROLE v13_resolve")
    rtcur.execute("SELECT v13_assemble_manifest(%s)", (sid_h3,))
    rtcur.fetchone()
    rt.rollback()
    rtcur.execute("SELECT v13_goal_hash(%s)", (sid_h3,))
    gh_h3 = rtcur.fetchone()[0]
    rtcur.execute(
        "SELECT v13_enqueue_effect(%s, 'context_refresh', %s::jsonb)",
        (sid_h3, json.dumps({"goal_hash": gh_h3, "nonce": u()})))
    eid_h3 = rtcur.fetchone()[0]
    rtcur.execute("SELECT v13_claim('h3w', 60000)")
    ck_h3 = rtcur.fetchone()[0]
    rtcur.execute(
        "SELECT v13_refresh_context(%s, %s, %s)",
        (eid_h3, ck_h3["attempt_no"], ck_h3["fence"]))
    check("H3: route_login settle chain (zero GUC dependency)",
          rtcur.fetchone()[0] == "accepted")
    rt.commit()
    rt.close()
    C.open_fresh()

    check("H4: filter prefix 10", len(files_through("filter")) == 10)
    check("H4: memory excluded from filter prefix",
          all("memory" not in p.name for p in files_through("filter")))
    check("H4: filter file is 10th in load order",
          SQL_LOAD_ORDER[9].name == "v13_filter.sql")
    C.cur.execute("SELECT 1 FROM pg_database WHERE datname='agent_v13_characterize'")
    if C.cur.fetchone():
        cch = psycopg2.connect(server.get_uri("agent_v13_characterize"))
        kch = cch.cursor()
        kch.execute(
            "SELECT count(*) FROM pg_proc WHERE proname='v13_filter_ask'")
        check("H4: dp5 db has no filter ask", kch.fetchone()[0] == 0)
        kch.execute(
            "SELECT count(*) FROM pg_proc WHERE proname='v13_filter_gate_open'")
        check("H4: dp5 db has no filter gate", kch.fetchone()[0] == 0)
        cch.rollback()
        cch.close()
    else:
        print("[note] H4: agent_v13_characterize absent; prefix slice checked structurally")

    filter_sql = (V13 / "filter" / "v13_filter.sql").read_text()
    norm_f = strip_sql_comments(filter_sql)
    n_cf = len(re.findall(r"(?im)^CREATE (?:OR REPLACE )?FUNCTION", norm_f))
    check("H5: CREATE FUNCTION total 19 (14 new + 5 replace)", n_cf == 19, n_cf)
    n_orr = len(re.findall(r"(?im)^CREATE OR REPLACE FUNCTION", norm_f))
    check("H5: OR REPLACE five", n_orr == 5, n_orr)
    check("H5: CREATE TRIGGER zero",
          len(re.findall(r"(?im)^CREATE TRIGGER", norm_f)) == 0)
    sigs_h5 = re.findall(
        r"(?im)^CREATE (?:OR REPLACE )?FUNCTION (\w+)\(([^)]*)\)", norm_f)
    check("H5: no duplicate signature",
          len(sigs_h5) == len(set(sigs_h5)), 
          [s for s in sigs_h5 if sigs_h5.count(s) > 1])
    n_ins = len(re.findall(r"(?im)^INSERT INTO", norm_f))
    n_upd = len(re.findall(r"(?im)^UPDATE ", norm_f))
    n_idx = len(re.findall(r"(?im)^CREATE INDEX", norm_f))
    n_rev = len(re.findall(r"(?im)^REVOKE ", norm_f))
    n_gr = len(re.findall(r"(?im)^GRANT ", norm_f))
    check("H5: seed counts (4 INSERT / 3 UPDATE / 2 INDEX / 1 REVOKE / 5 GRANT)",
          (n_ins, n_upd, n_idx, n_rev, n_gr) == (4, 3, 2, 1, 5),
          (n_ins, n_upd, n_idx, n_rev, n_gr))
    check("H5: single BEGIN/COMMIT wraps file",
          norm_f.count("BEGIN;") == 1 and norm_f.rstrip().endswith("COMMIT;"),
          (norm_f.count("BEGIN;"), norm_f[-20:]))

    check("H6: file10 zero bind operator",
          norm_f.count("==>") == 0, norm_f.count("==>"))
    check("H6: file10 zero engine-qualified names",
          norm_f.count("stannum.") == 0, norm_f.count("stannum."))
    check("H6: file10 zero mock literal (dp1 scan belt)",
          "mock_response" not in norm_f)
    check("H6: file10 zero session-config writes (dp1 scan belt)",
          "set_config" not in norm_f)

    readme = (V13 / "filter" / "README.md").read_text()
    for needle in ("chunk_filter", "judgment_defaults", "fail-open",
                   "candidates_digest", "signal", "ask", "一页账"):
        check(f"H-readme: mentions {needle}", needle in readme)

    C.conn.close()
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
