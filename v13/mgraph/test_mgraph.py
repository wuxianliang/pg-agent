"""DP9 M1 gate (G-mg group A): mgraph dark library — tables/indexes, policy
row + fail-closed reader, six mem_* template families seeded verbatim from
QUESTION_SNAPSHOT.md, judgment_defaults six new points, needed_judgments
untouched + cgr bump, ACL negative face, source scan, zero side effects,
envelope constructor batch shape. M2 group D (write & rebuild): build/apply/
rebuild/candidates, caps & cursor semantics, concurrency, poisoned-rebuild
zero-ask. M3/M4 groups (E/F) land with their milestones.

Run: uv run python v13/mgraph/test_mgraph.py  (exit 0 = pass)
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import threading
import time
import uuid
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
V13 = AGENT_ROOT / "v13"
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.mgraph.setup_db import DB, main as setup_db
from v13.load import load_stage, run_psql

SNAPSHOT = ROOT / "QUESTION_SNAPSHOT.md"
SQL_FILE = ROOT / "v13_mgraph.sql"
HEX64 = re.compile(r"^[0-9a-f]{64}$")

EXPECTED_POLICY = {
    "relation_threshold": 0.60, "candidate_top_k": 10,
    "total_graph_budget": 20, "probability_exponent": 1.5,
    "graph_activation_threshold": 0.15, "beam_width": 5, "maximum_depth": 5,
    "maximum_nodes": 30, "maximum_edges": 200, "maximum_jev_calls": 10,
    "max_latency_ms": 15000,
    "transition_weights": [0.25, 0.35, 0.15, 0.15, 0.10],
    "transition_recency_coef": 0.10,
    "evidence_sufficient_min": 0.85, "missing_stop_hi": 0.40,
    "contradiction_stop_hi": 0.40, "continue_min": 0.40,
    "consolidation_threshold": 0.85, "consolidation_choice_min": 0.85,
    "consolidation_priority": ["contradiction", "redundant", "link"],
    "lexical_coef": 2, "entity_coef": 2, "keyword_coef": 1,
    "candidate_recency_coef": 0.25, "candidate_recency_halflife_s": 86400,
    "keyword_cap": 15, "write_enabled": False, "read_enabled": False,
    "admission_enabled": False, "routing_mode": "deterministic",
    "routing_shadow": False, "write_max_batches": 8,
    "consolidate_mode": "manual", "consolidation_interval": 0,
    "deterministic_floor": 1, "inject_top_k": 5,
    "entity_stopwords": [],
    "consolidate_max_body_bytes": 32768,
    "write_max_asks": 64,
}

EXPECTED_POINTS = {
    "chunk_score": {"missing": "include", "timeout": "include",
                    "review": "degrade"},
    "corpus_exists": {"missing": "include", "timeout": "include",
                      "review": "include"},
    "summary_accept": {"missing": "exclude", "timeout": "exclude",
                       "review": "exclude"},
    "mem_relation": {"missing": "exclude", "timeout": "exclude",
                     "review": "exclude"},
    "mem_type": {"missing": "exclude", "timeout": "exclude",
                 "review": "exclude"},
    "mem_cons": {"missing": "exclude", "timeout": "exclude",
                 "review": "exclude"},
    "mem_traversal": {"missing": "degrade", "timeout": "degrade",
                      "review": "degrade"},
    "mem_stopping": {"missing": "exclude", "timeout": "exclude",
                     "review": "exclude"},
    "mem_routing": {"missing": "exclude", "timeout": "exclude",
                    "review": "exclude"},
}

TYPE_LABELS = ("episodic", "semantic", "procedural", "preference")


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    extra = f": {detail}" if detail and (not condition or len(str(detail)) < 220) else ""
    print(f"[{mark}] {label}{extra}")
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u() -> str:
    return str(uuid.uuid4())


def strip_sql_comments(src: str) -> str:
    """Comment-stripped source for the bind-operator exact-count gate
    (memory K4 precedent: dollar-quoted bodies and string literals are
    preserved verbatim; -- and /* */ comments become spaces)."""
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
            while i < n and not (src[i] == "*" and i + 1 < n and src[i + 1] == "/"):
                i += 1
            i += 2
            out.append(" ")
            continue
        out.append(ch)
        i += 1
    return "".join(out)


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


def parse_snapshot(path: Path):
    text = path.read_text(encoding="utf-8")
    m = re.search(r"停用词表[^\n]*\n\n```text\n(.*?)\n```", text, re.S)
    stopwords = m.group(1).split(" ")
    slots = {}
    parts = re.split(r"^### slot (\S+)\s*$", text, flags=re.M)
    for i in range(1, len(parts), 2):
        name, body = parts[i], parts[i + 1]
        kind = re.search(r"- kind: (\w+)", body).group(1)
        projection = json.loads(
            re.search(r"projection: (\[[^\n]*?\])", body).group(1))
        local = "v13-local" in body.split("\n")[2] if len(
            body.split("\n")) > 2 else False
        shas = dict(re.findall(r"- sha256\(([^)]+)\) = `([0-9a-f]{64})`",
                              body))
        blocks = re.findall(r"```(?:text|json)\n(.*?)\n```", body, re.S)
        if kind == "noul" and not local and len(blocks) == 3:
            instr, c_true, c_false = blocks
            question = (instr + " TRUE if: " + c_true
                        + " FALSE if: " + c_false)
            criteria = None
        elif kind == "noul":
            instr = blocks[0]
            question = instr
            c_true = c_false = None
            criteria = None
        else:  # choice
            instr, crit_line = blocks
            question = instr
            criteria = json.loads(crit_line)
            c_true = c_false = None
        # snapshot self-integrity: recorded sha256 lines match recomputed
        expect = {"instructions": sha(instr), "question-combined": sha(question)}
        if c_true is not None:
            expect["criteria_true"] = sha(c_true)
            expect["criteria_false"] = sha(c_false)
        if criteria is not None:
            expect["criteria-json-line"] = sha(crit_line)
        for k, v in expect.items():
            if shas.get(k) != v:
                raise SystemExit(
                    f"snapshot integrity: {name}.{k} sha256 drift")
        slots[name] = dict(kind=kind, question=question, criteria=criteria,
                           projection=projection,
                           source=re.findall(r"- source: ([^\n]+)", body)[0])
    return slots, stopwords


def guc(cur):
    cur.execute("RESET ROLE")
    cur.execute("SET search_path TO public, pg_catalog")
    cur.execute("SELECT set_config('typesafe.provider', 'mock', false)")
    cur.execute("SELECT set_config('typesafe.model', 'jev-mock', false)")


def set_mock(cur, mock: str) -> None:
    cur.execute("SELECT set_config('typesafe.mock_response', %s, true)",
                (mock,))


def mock_for_needed(env) -> str:
    answers = {}
    for q in env["needed"]:
        if q["kind"] == "choice":
            ch = sorted((q.get("criteria") or {}).keys())[0]
            answers[q["signal"]] = {
                "type": "choice", "choice": ch,
                "probabilities": {ch: 0.9}, "confidence": 0.9}
        elif q["kind"] == "score":
            answers[q["signal"]] = {
                "type": "score", "score": 1, "confidence": 0.9}
        else:
            answers[q["signal"]] = {"type": "noul", "noul": 0.9}
    return json.dumps({"model": "jev-mock", "answers": answers,
                       "usage": {"input_tokens": 1, "output_tokens": 1}})


def bump_policy(cur, name: str, value: dict) -> int:
    cur.execute(
        "SELECT coalesce(max(version),0)+1 FROM v13_policies WHERE name=%s",
        (name,))
    ver = cur.fetchone()[0]
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


def main() -> int:
    slots, stopwords = parse_snapshot(SNAPSHOT)
    check("snapshot: 28 slots parsed", len(slots) == 28, sorted(slots))
    check("snapshot: 28 stopwords parsed", len(stopwords) == 28, stopwords)

    setup_db()
    server = get_server()
    conn = psycopg2.connect(server.get_uri(DB))
    conn.autocommit = False
    cur = conn.cursor()
    guc(cur)

    # ---------------- A1 tables / indexes / immutability ----------------
    cur.execute(
        "SELECT indexname FROM pg_indexes WHERE tablename IN "
        "('memory_nodes','memory_links') ORDER BY indexname")
    idx = [r[0] for r in cur.fetchall()]
    for want in ("ix_memory_nodes_stannum", "ix_memory_links_src",
                 "ix_memory_links_dst"):
        check(f"A1: index {want} present", want in idx, idx)
    cur.execute(
        "SELECT count(*) FROM pg_tables WHERE tablename IN "
        "('memory_nodes','memory_links','v13_mgraph_meta',"
        "'memory_consolidations')")
    check("A1: four M1 tables present", cur.fetchone()[0] == 4)

    sid = u()
    cur.execute("INSERT INTO sessions (session_id) VALUES (%s)", (sid,))
    body = "Alice deployed the payment service on Friday morning."
    cur.execute("SELECT v13_body_hash(%s)", (body,))
    bh = cur.fetchone()[0]
    ts = "2026-09-23 10:00:00+00"
    fails_with(
        cur,
        "INSERT INTO memory_nodes (session_id, content_hash, body, origin,"
        " source_hashes, source_at, builder_version)"
        " VALUES (%s, %s, %s, 'episodic', ARRAY[%s], %s::timestamptz, 1)",
        (sid, "f" * 64, body, bh, ts),
        "v13_mn_hash_selfcheck", "A1: bad content_hash rejected (hash self-check)")
    cur.execute(
        "INSERT INTO memory_nodes (session_id, content_hash, body, origin,"
        " source_hashes, source_at, builder_version)"
        " VALUES (%s, %s, %s, 'episodic', ARRAY[%s], %s::timestamptz, 1)",
        (sid, bh, body, bh, ts))
    fails_with(
        cur, "UPDATE memory_nodes SET builder_version = 2 "
        "WHERE session_id=%s AND content_hash=%s", (sid, bh),
        "immutable", "A1: UPDATE memory_nodes -> V3009", pgcode="V3009")
    cur.execute(
        "INSERT INTO memory_links (session_id, src_hash, dst_hash, rel,"
        " origin, decision_id, structural, policy_version)"
        " VALUES (%s, %s, %s, 'temporal', 'temporal', NULL, 1.0, 1)",
        (sid, bh, bh))
    fails_with(
        cur, "UPDATE memory_links SET structural = 2 "
        "WHERE session_id=%s AND src_hash=%s", (sid, bh),
        "immutable", "A1: UPDATE memory_links -> V3009", pgcode="V3009")
    sql_src = SQL_FILE.read_text(encoding="utf-8")
    check("A1: source has no cypher( call", "cypher(" not in sql_src)
    cur.execute("ROLLBACK")
    conn.commit()

    # ---------------- A2 policy row + fail-closed reader ----------------
    cur.execute(
        "SELECT version, value FROM v13_policies WHERE name='mgraph' AND active")
    ver, val = cur.fetchone()
    check("A2: mgraph v1 active", ver == 1, ver)
    check("A2: mgraph seed equals §3.2 JSON key-for-key",
          val == EXPECTED_POLICY,
          {k: (val.get(k), EXPECTED_POLICY.get(k))
           for k in set(val) | set(EXPECTED_POLICY)
           if val.get(k) != EXPECTED_POLICY.get(k)})
    check("A2: transition weights sum = 1",
          abs(sum(val["transition_weights"]) - 1.0) < 1e-9,
          sum(val["transition_weights"]))
    cur.execute("SELECT v13_mgraph_policy()")
    check("A2: v13_mgraph_policy() returns active row verbatim",
          cur.fetchone()[0] == EXPECTED_POLICY)
    bad = dict(EXPECTED_POLICY, transition_weights=[0.5, 0.3, 0.1, 0.1, 0.1])
    bump_policy(cur, "mgraph", bad)
    fails_with(cur, "SELECT v13_mgraph_policy()", (), "transition_weights",
               "A2: weights sum != 1 -> V3009 (fail-closed)", pgcode="V3009")
    cur.execute("ROLLBACK")
    conn.commit()
    bump_policy(cur, "mgraph", dict(EXPECTED_POLICY, admission_enabled=True))
    fails_with(cur, "SELECT v13_mgraph_policy()", (), "admission_enabled",
               "A2: admission_enabled=true -> V3009 (loud key)", pgcode="V3009")
    cur.execute("ROLLBACK")
    conn.commit()
    bump_policy(cur, "mgraph",
                dict(EXPECTED_POLICY, consolidate_mode="interval"))
    fails_with(cur, "SELECT v13_mgraph_policy()", (), "consolidate_mode",
               "A2: consolidate_mode != manual -> V3009 (loud key)",
               pgcode="V3009")
    cur.execute("ROLLBACK")
    conn.commit()
    cur.execute(
        "SELECT count(*) FROM v13_policies WHERE name='mgraph'")
    check("A2: bad-version fixtures rolled back (single v1 row)",
          cur.fetchone()[0] == 1)

    # ---------------- A3 template families vs snapshot ----------------
    cur.execute(
        "SELECT t.template_name, t.kind, t.question, t.criteria, t.projection,"
        " t.writer, t.wire_version, t.canon_version, t.epoch, w.state"
        " FROM judgment_templates t"
        " JOIN v13_judgment_template_versions w"
        " ON w.template_name=t.template_name"
        " AND w.template_version=t.template_version"
        " WHERE t.template_name LIKE 'mem\\_%'")
    rows = {r[0]: r for r in cur.fetchall()}
    check("A3: 28 mem_* templates registered", len(rows) == 28, sorted(rows))
    for name, s in slots.items():
        r = rows.get(name)
        if r is None:
            check(f"A3: {name} present", False, "missing")
            continue
        _, kind, question, criteria, projection, writer, wire, canon, epoch, state = r
        check(f"A3: {name} question == snapshot combined string",
              question == s["question"],
              f"db={question!r}\nsnap={s['question']!r}")
        check(f"A3: {name} criteria matches snapshot",
              criteria == s["criteria"], f"db={criteria!r}")
        check(f"A3: {name} kind/epoch/frozen/projection",
              kind == s["kind"] and epoch == "pre-finalize"
              and state == "frozen" and projection == s["projection"]
              and projection != ["*"],
              (kind, epoch, state, projection))
        check(f"A3: {name} writer/wire/canon",
              writer == "v13_resolve" and wire == 1 and canon == 1,
              (writer, wire, canon))
    check("A3: stopwords snapshot parsed (entity_stopwords seed may stay [])",
          stopwords[:3] == ["The", "This", "That"], stopwords[:3])
    cur.execute(
        "SELECT value->'entity_stopwords' FROM v13_policies"
        " WHERE name='mgraph' AND active")
    check("A3: v1 entity_stopwords = [] (OQ10 多抽不假抽)",
          cur.fetchone()[0] == [])

    # ---------------- A4 judgment_defaults nine points ----------------
    cur.execute(
        "SELECT version, value FROM v13_policies"
        " WHERE name='judgment_defaults' AND active")
    jver, jval = cur.fetchone()
    check("A4: defaults flipped to v4", jver == 4, jver)
    check("A4: nine points exactly (3 kept + 6 mem_)",
          jval["points"] == EXPECTED_POINTS,
          {k: v for k, v in jval["points"].items()
           if EXPECTED_POINTS.get(k) != v})
    cur.execute("SELECT v13_mgraph_defaults_action('mem_traversal','timeout')")
    check("A4: reader returns degrade for mem_traversal.timeout",
          cur.fetchone()[0] == "degrade")
    cur.execute("SELECT v13_mgraph_defaults_action('mem_relation','missing')")
    check("A4: reader returns exclude for mem_relation.missing",
          cur.fetchone()[0] == "exclude")
    fails_with(cur, "SELECT v13_mgraph_defaults_action('mem_type','bogus')",
               (), "no state", "A4: missing state -> V3009", pgcode="V3009")
    fails_with(cur, "SELECT v13_mgraph_defaults_action('mem_nope','missing')",
               (), "missing", "A4: missing point -> V3009", pgcode="V3009")
    fails_with(cur, "SELECT v13_mgraph_defaults_action('chunk_score','missing')",
               (), "mem_ points only",
               "A4: non-mem point rejected -> V3009", pgcode="V3009")

    # ---------------- A5 needed untouched + cgr relative bump ----------------
    cur.execute(
        "SELECT pg_get_functiondef('v13_needed_judgments(uuid)'::regprocedure)")
    check("A5: v13_needed_judgments body contains no mem_",
          "mem_" not in cur.fetchone()[0])
    scratch = DB + "_cgrbase"
    run_psql(server, "postgres",
             f"DROP DATABASE IF EXISTS {scratch} WITH (FORCE);")
    run_psql(server, "postgres", f"CREATE DATABASE {scratch};")
    load_stage(server, scratch, "periphery")
    cbase = psycopg2.connect(server.get_uri(scratch))
    ccur = cbase.cursor()
    ccur.execute(
        "SELECT candidate_generation_revision FROM v13_tools_meta WHERE singleton")
    cgr_pre = ccur.fetchone()[0]
    cbase.close()
    run_psql(server, "postgres",
             f"DROP DATABASE IF EXISTS {scratch} WITH (FORCE);")
    cur.execute(
        "SELECT candidate_generation_revision FROM v13_tools_meta WHERE singleton")
    cgr_post = cur.fetchone()[0]
    check("A5: cgr bumped by mgraph load (>= 1 per template row-level trigger)",
          cgr_post - cgr_pre >= 28, f"pre={cgr_pre} post={cgr_post} "
          f"delta={cgr_post - cgr_pre}")

    # ---------------- A6 ACL negative face ----------------
    cur.execute("SET ROLE v13_recall")
    fails_with(
        cur,
        "INSERT INTO memory_nodes (session_id, content_hash, body, origin,"
        " source_hashes, source_at, builder_version)"
        " VALUES (%s, %s, %s, 'episodic', ARRAY[%s], %s::timestamptz, 1)",
        (sid, bh, body, bh, ts), "permission denied",
        "A6: recall INSERT memory_nodes denied")
    cur.execute("RESET ROLE")
    cur.execute("SET ROLE v13_resolve")
    fails_with(
        cur,
        "SELECT v13_append_event(%s, %s, 'user/message', '{\"text\":\"x\"}'::jsonb)",
        (sid, u()), "permission denied",
        "A6: resolve EXECUTE v13_append_event denied")
    cur.execute("RESET ROLE")
    cur.execute("SET ROLE v13_route")
    fails_with(cur, "SELECT typesafe_ask('{}'::jsonb, '{}'::jsonb)", (),
               "permission denied",
               "A6: route EXECUTE typesafe_ask denied")
    cur.execute("RESET ROLE")
    conn.commit()

    # ---------------- A7 source scan (five tokens, whole file) ----------------
    for tok in ("typesafe_ask", "v13_append_event", "FOR UPDATE",
                "mock_response", "cypher("):
        check(f"A7: source scan '{tok}' == 0", sql_src.count(tok) == 0,
              sql_src.count(tok))

    # ---------------- A8 dark library zero side effects ----------------
    for table in ("decisions", "effects", "memory_nodes", "memory_links",
                  "v13_mgraph_meta", "memory_consolidations"):
        cur.execute(f"SELECT count(*) FROM {table}")
        check(f"A8: {table} empty after M1 load", cur.fetchone()[0] == 0)
    cur.execute("INSERT INTO sessions (session_id) VALUES (%s)", (sid,))
    cur.execute("SELECT v13_mgraph_progress(%s)", (sid,))
    prog = cur.fetchone()[0]
    check("A8: rel_cursor=NULL / watermark=-1 initial state",
          prog == {"generation": 0, "watermark": -1, "rel_cursor": None,
                   "nodes_since_consolidate": 0}, prog)
    cur.execute("SELECT count(*) FROM sessions")
    check("A8: fixture session present (progress read on real session)",
          cur.fetchone()[0] >= 1)

    # ---------------- A9 envelope batch shape + one-batch resolve ----------------
    guc(cur)
    questions = [{"signal": f"mem_type::{bh}::{label}",
                  "template_name": f"mem_type_{label}"}
                 for label in TYPE_LABELS]
    cur.execute("SELECT v13_mgraph_envelope(%s, %s::jsonb, %s::jsonb)",
                (sid, json.dumps({"body": body}), json.dumps(questions)))
    env = cur.fetchone()[0]
    check("A9: envelope 12-key set aligned with summary envelope",
          sorted(env.keys()) == sorted(
              ["sid", "ctx", "needed", "templates", "groups", "budget",
               "timeout_ms", "candidate_set_hash", "provider", "model",
               "goal_hash", "candidates"]), sorted(env.keys()))
    check("A9: batch_questions = question count (4, not 1)",
          env["budget"]["batch_questions"] == 4, env["budget"])
    check("A9: groups exactly one element",
          len(env["groups"]) == 1 and env["groups"][0]["state"] == {"body": body},
          env["groups"])
    check("A9: candidates always []",
          env["candidates"] == [])
    check("A9: goal_hash always carried (64hex)",
          bool(HEX64.match(env["goal_hash"])), env["goal_hash"])
    check("A9: candidate_set_hash 64hex",
          bool(HEX64.match(env["candidate_set_hash"])),
          env["candidate_set_hash"])
    check("A9: needed carries the four frozen questions",
          len(env["needed"]) == 4
          and all(q["question"] == slots[f"mem_type_{lbl}"]["question"]
                  for q, lbl in zip(env["needed"], TYPE_LABELS)),
          [q["signal"] for q in env["needed"]])
    set_mock(cur, mock_for_needed(env))
    cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
                (json.dumps(env),))
    res = cur.fetchone()[0]
    check("A9: one-batch resolve: failed=false, asked_batches=1, asked_questions=4",
          res.get("failed") is False and res.get("asked_batches") == 1
          and res.get("asked_questions") == 4 and res.get("remaining") == 0,
          res)
    cur.execute(
        "SELECT count(*), max(question_count) FROM judgment_calls"
        " WHERE candidate_set_hash = %s", (env["candidate_set_hash"],))
    n_calls, q_count = cur.fetchone()
    check("A9: exactly one judgment_calls row with question_count=4",
          n_calls == 1 and q_count == 4, (n_calls, q_count))
    cur.execute(
        "SELECT count(*) FROM decisions WHERE session_id=%s"
        " AND signal LIKE 'mem\\_type::%%'", (sid,))
    check("A9: four mem_type decisions landed", cur.fetchone()[0] == 4)
    cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
                (json.dumps(env),))
    res2 = cur.fetchone()[0]
    check("A9: replay resolve zero ask (gap absorbed by decisions)",
          res2.get("failed") is False and res2.get("asked_batches") == 0
          and res2.get("remaining") == 0, res2)
    conn.rollback()
    conn.close()

    # =====================================================================
    # DP9 M2 group D: write path & rebuild (G-mg/D1-D16)
    #
    # Mock discipline (test_filter.Conns lesson): typesafe.provider is a
    # placeholder GUC purged when the typesafe library loads (first ask on
    # the connection) and un-settable afterwards (reserved prefix) — a
    # connection that has asked can never construct another envelope. The
    # build function captures provider/model once at start and passes them
    # explicitly, but tests must still run each envelope-constructing step
    # on a never-asked connection, hence the Conns recycle below. Mocks
    # answer exactly one ask batch shape per GUC value, so the stepper
    # drives build one ask per call under write caps=1 (the plan's
    # write_max_batches tick throttle exercised deliberately).
    # =====================================================================

    class Conns:
        def __init__(self):
            self.open_fresh()

        def open_fresh(self):
            self.conn = psycopg2.connect(server.get_uri(DB))
            self.conn.autocommit = False
            self.cur = self.conn.cursor()
            self.cur.execute("SET search_path TO public, pg_catalog")
            self.cur.execute(
                "SELECT set_config('typesafe.provider', 'mock', false)")
            self.cur.execute(
                "SELECT set_config('typesafe.model', 'jev-mock', false)")

        def ensure(self):
            self.cur.execute(
                "SELECT coalesce(current_setting('typesafe.provider', true), '')")
            if not self.cur.fetchone()[0]:
                self.conn.rollback()
                self.conn.close()
                self.open_fresh()

        def commit(self):
            self.conn.commit()

    def fresh_conn():
        c = psycopg2.connect(server.get_uri(DB))
        c.autocommit = False
        k = c.cursor()
        k.execute("SET search_path TO public, pg_catalog")
        k.execute("SELECT set_config('typesafe.provider', 'mock', false)")
        k.execute("SELECT set_config('typesafe.model', 'jev-mock', false)")
        return c, k

    C = Conns()
    cur = C.cur

    def sig_to_template(sig):
        parts = sig.split("::")
        if parts[0] == "mem_type":
            return f"mem_type_{parts[2]}"
        return f"mem_rel_{parts[3]}"

    def body_hash_of(c, body):
        c.execute("SELECT v13_body_hash(%s)", (body,))
        return c.fetchone()[0]

    def mgraph_firsts(c, sid):
        c.execute(
            "SELECT content_hash, body, fs FROM ("
            " SELECT DISTINCT ON (t.content_hash) t.content_hash, t.body,"
            "        t.seq_from AS fs"
            " FROM transcript_chunks t WHERE t.session_id = %s"
            " ORDER BY t.content_hash, t.seq_from) d ORDER BY fs", (sid,))
        return c.fetchall()

    def answered_sigs(c, sid):
        c.execute(
            "SELECT signal FROM decisions WHERE session_id = %s"
            " AND answer IS NOT NULL AND status IN ('answered','cached')",
            (sid,))
        return {r[0] for r in c.fetchall()}

    def envelope_of(c, sid, state, questions):
        c.execute("SELECT v13_mgraph_envelope(%s, %s::jsonb, %s::jsonb)",
                  (sid, json.dumps(state), json.dumps(questions)))
        return c.fetchone()[0]

    def gap_of_env(c, env):
        c.execute("SELECT v13_gap(%s::jsonb)", (json.dumps(env),))
        return c.fetchone()[0]

    def links_of(c, sid, origin=None):
        q = ("SELECT src_hash, dst_hash, rel, origin, decision_id,"
             " structural, policy_version FROM memory_links"
             " WHERE session_id = %s")
        args = [sid]
        if origin:
            q += " AND origin = %s"
            args.append(origin)
        q += " ORDER BY src_hash, dst_hash, rel, origin"
        c.execute(q, args)
        return [tuple(str(x) for x in r) for r in c.fetchall()]

    def mk_session(c, bodies, same_txn=True):
        sid = u()
        c.execute("INSERT INTO sessions (session_id) VALUES (%s)", (sid,))
        for b in bodies:
            c.execute(
                "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
                (sid, u(), json.dumps({"text": b})))
            if not same_txn:
                C.commit()
                time.sleep(0.02)
        C.commit()
        c.execute("SELECT v13_rebuild_transcript_chunks(1000)")
        C.commit()
        return sid

    def next_env(c, sid):
        """Predict build's next ask batch (node order x type-then-pairs),
        gap-aware via v13_gap — the global judgment_cache closes gaps that
        per-session decision checks alone would miss."""
        for h, body, fs in mgraph_firsts(c, sid):
            qs = [{"signal": f"mem_type::{h}::{lbl}",
                   "template_name": f"mem_type_{lbl}"}
                  for lbl in TYPE_LABELS]
            state = {"body": body}
            env = envelope_of(c, sid, state, qs)
            gap = gap_of_env(c, env)
            if gap:
                return state, [g["signal"] for g in gap]
            c.execute(
                "SELECT * FROM v13_mgraph_candidates("
                "%s, v13_build_tinql(%s), %s)",
                (sid, body, EXPECTED_POLICY["candidate_top_k"]))
            for ch, sc, ln in c.fetchall():
                if ch == h:
                    continue
                c.execute(
                    "SELECT body FROM memory_nodes WHERE session_id=%s"
                    " AND content_hash=%s", (sid, ch))
                rb = c.fetchone()[0]
                c.execute(
                    "SELECT v13_mgraph_pair_questions(%s,%s,%s,%s)",
                    (h, ch, body, rb))
                pqs = c.fetchone()[0]
                c.execute("SELECT v13_mgraph_entities(%s), v13_mgraph_entities(%s)",
                          (body, rb))
                le, re_ = c.fetchone()
                state = {"left": {"content": body, "entities": le},
                         "right": {"content": rb, "entities": re_}}
                env = envelope_of(c, sid, state, pqs)
                gap = gap_of_env(c, env)
                if gap:
                    return state, [g["signal"] for g in gap]
        return None

    def mock_answers(gap_sigs, over=None):
        over = over or {}
        answers = {}
        for s in gap_sigs:
            v = over.get(s, 0.9 if s.startswith("mem_type") else 0.1)
            answers[s] = {"type": "noul", "noul": v}
        return json.dumps({"model": "jev-mock", "answers": answers,
                           "usage": {"input_tokens": 1, "output_tokens": 1}})

    def set_active(name, version):
        cur.execute("UPDATE v13_policies SET active=false WHERE name=%s AND active",
                    (name,))
        cur.execute("UPDATE v13_policies SET active=true WHERE name=%s AND version=%s",
                    (name, version))
        C.commit()

    def open_write(**over):
        ver = bump_policy(cur, "mgraph",
                          dict(EXPECTED_POLICY, write_enabled=True, **over))
        C.commit()
        return ver

    def spend_cap(cap):
        ver = bump_policy(cur, "judge_spend_gate",
                          {"session_asks_cap": cap, "day_asks_cap": 8192,
                           "scope": "fast_path"})
        C.commit()
        return ver

    def stepper(sid, over=None):
        """Drive build to completion, one ask per call (write caps=1);
        returns (per-call build results, per-call new decision signals)."""
        results, waves = [], []
        while True:
            C.ensure()
            cur = C.cur
            nxt = next_env(cur, sid)
            if nxt is None:
                break
            state, gap_sigs = nxt
            before = answered_sigs(cur, sid)
            cur.execute("SELECT set_config('typesafe.mock_response', %s, true)",
                        (mock_answers(gap_sigs, over),))
            cur.execute("SELECT v13_mgraph_build(%s, 100)", (sid,))
            results.append(cur.fetchone()[0])
            C.commit()
            waves.append(answered_sigs(cur, sid) - before)
        return results, waves

    PB1 = "Dana Eric Grace Hope shipped the crate."
    PB2 = "Eric Grace Hope Dana shipped the crate."

    # ---------------- D15 write disabled -> skipped ----------------
    sid15 = mk_session(cur, [PB1, PB2])
    cur.execute("SELECT count(*) FROM judgment_calls")
    calls15 = cur.fetchone()[0]
    cur.execute("SELECT v13_mgraph_build(%s, 100)", (sid15,))
    r15 = cur.fetchone()[0]
    C.commit()
    check("D15: write_enabled=false -> skipped:disabled zero-write",
          r15.get("skipped") == "disabled" and r15.get("status") == "skipped",
          r15)
    cur.execute("SELECT count(*) FROM memory_nodes WHERE session_id=%s", (sid15,))
    check("D15: zero nodes written", cur.fetchone()[0] == 0)
    cur.execute("SELECT count(*) FROM v13_mgraph_meta WHERE session_id=%s", (sid15,))
    check("D15: zero meta rows", cur.fetchone()[0] == 0)
    cur.execute("SELECT count(*) FROM judgment_calls")
    check("D15: zero asks", cur.fetchone()[0] == calls15)

    open_write(write_max_batches=1, write_max_asks=1)
    sid15b = mk_session(cur, ["Wendy tuned the old radio."])
    C.ensure()
    cur = C.cur
    nxt = next_env(cur, sid15b)
    check("D15: write on -> predictor sees the pending type envelope",
          nxt is not None and nxt[1][0].startswith("mem_type"), nxt[1] if nxt else None)
    cur.execute("SELECT set_config('typesafe.mock_response', %s, true)",
                (mock_answers(nxt[1]),))
    cur.execute("SELECT v13_mgraph_build(%s, 100)", (sid15b,))
    r15b = cur.fetchone()[0]
    C.commit()
    check("D15: flipped on -> build projects normally",
          r15b["nodes_inserted"] == 1 and r15b["asks"] == 1
          and r15b["rel_cursor"] is not None, r15b)

    # ---------------- D1 above-threshold jev edge ----------------
    h1, h2 = body_hash_of(cur, PB1), body_hash_of(cur, PB2)
    sid1 = mk_session(cur, [PB1, PB2])
    res1, _ = stepper(sid1, over={f"mem_rel::{h1}::{h2}::semantic": 0.9})
    cur = C.cur
    jev_d1 = links_of(cur, sid1, "jev")
    check("D1: exactly one jev edge (semantic, above threshold)",
          len(jev_d1) == 1 and jev_d1[0][2] == "semantic"
          and (jev_d1[0][0], jev_d1[0][1]) == (h1, h2), jev_d1)
    cur.execute(
        "SELECT l.decision_id IS NOT NULL AND d.session_id = %s"
        " FROM memory_links l LEFT JOIN decisions d"
        " ON d.decision_id = l.decision_id"
        " WHERE l.session_id = %s AND l.origin = 'jev'", (sid1, sid1))
    check("D1: edge carries an in-session decision_id", cur.fetchone()[0] is True)
    cur.execute(
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_name = 'memory_links' ORDER BY ordinal_position")
    cols_ml = [r[0] for r in cur.fetchall()]
    check("D1: memory_links columns are hash-only (no body payload)",
          cols_ml == ["session_id", "src_hash", "dst_hash", "rel", "origin",
                      "decision_id", "structural", "policy_version"], cols_ml)
    cur.execute("SELECT v13_mgraph_apply_relations(%s)", (sid1,))
    check("D1: apply_relations idempotent (re-run inserts nothing)",
          cur.fetchone()[0]["jev_edges"] == 0)
    C.commit()
    # OQ7: same-pool double call byte-identical
    cur.execute("SELECT v13_build_tinql(%s)", (PB1,))
    tq1 = cur.fetchone()[0]
    cur.execute("SELECT * FROM v13_mgraph_candidates(%s, %s, 10)", (sid1, tq1))
    ca1 = [tuple(str(x) for x in r) for r in cur.fetchall()]
    cur.execute("SELECT * FROM v13_mgraph_candidates(%s, %s, 10)", (sid1, tq1))
    cb1 = [tuple(str(x) for x in r) for r in cur.fetchall()]
    check("D1: same-pool double call byte-identical (OQ7)", ca1 == cb1, (ca1, cb1))

    # ---------------- D2 below threshold / temporal / tie ----------------
    n0 = "Iris and Jules packed the van."
    n1 = "Iris and Jules packed the van slowly."
    n2 = "and Jules Iris the van packed slowly."
    sid2 = mk_session(cur, [n0, n1, n2])
    stepper(sid2)
    cur = C.cur
    hn0, hn1, hn2 = (body_hash_of(cur, x) for x in (n0, n1, n2))
    check("D2: below threshold -> zero jev edges",
          links_of(cur, sid2, "jev") == [])
    temp_d2 = links_of(cur, sid2, "temporal")
    check("D2: temporal edges present, decision_id NULL",
          len(temp_d2) == 2 and all(r[4] in ("None", None) for r in temp_d2),
          temp_d2)
    prox_d2 = links_of(cur, sid2, "proximity")
    check("D2: proximity edges recorded with structural score",
          len(prox_d2) >= 1 and all(r[5] not in ("None", None) for r in prox_d2),
          prox_d2)
    cur.execute("SELECT * FROM v13_mgraph_candidates(%s, v13_build_tinql(%s), 10)",
                (sid2, n0))
    rows_d2 = cur.fetchall()
    sc_d2 = {r[0]: str(r[1]) for r in rows_d2}
    order_d2 = [r[0] for r in rows_d2]
    check("D2: equal-score candidates tie-break by content_hash ASC (OQ7)",
          hn1 in sc_d2 and hn2 in sc_d2 and sc_d2[hn1] == sc_d2[hn2]
          and (order_d2.index(hn1) < order_d2.index(hn2)) == (hn1 < hn2),
          (sc_d2.get(hn1), sc_d2.get(hn2), order_d2))

    # ---------------- D3 V3001 -> nodes stay, zero jev edges ----------------
    p3a = "Rosa and Theo anchored the skiff."
    p3b = "Theo and Rosa anchored the skiff."
    sid3 = mk_session(cur, [p3a, p3b])
    C.ensure()
    cur = C.cur
    nxt = next_env(cur, sid3)
    bad = {s: {"type": "noul"} for s in nxt[1]}
    cur.execute("SELECT set_config('typesafe.mock_response', %s, true)",
                (json.dumps({"model": "jev-mock", "answers": bad,
                             "usage": {"input_tokens": 1, "output_tokens": 1}}),))
    cur.execute("SELECT v13_mgraph_build(%s, 100)", (sid3,))
    r3 = cur.fetchone()[0]
    C.commit()
    check("D3: V3001 -> build failed=true", r3["failed"] is True
          and r3["stop_reason"] == "failed", r3)
    check("D3: zero jev edges", links_of(cur, sid3, "jev") == [])
    cur.execute("SELECT count(*) FROM memory_nodes WHERE session_id=%s", (sid3,))
    check("D3: nodes remain (projection is not a judgment side effect)",
          cur.fetchone()[0] == 2)
    cur.execute(
        "SELECT count(*) FROM judgment_calls WHERE session_id=%s"
        " AND status='failed_validation'", (sid3,))
    check("D3: failed batch still counted as an ask (call row written)",
          cur.fetchone()[0] == 1)

    # ---------------- D4 poisoned rebuild ----------------
    sid4 = mk_session(cur, [PB1, PB2])
    stepper(sid4)          # all-cached session (D1 answers) -> zero asks
    cur = C.cur
    temp_a = links_of(cur, sid4, "temporal")
    jev_a = links_of(cur, sid4, "jev")
    prox_a = links_of(cur, sid4, "proximity")
    cbody = "Consolidated: the crate shipments summary."
    chash = body_hash_of(cur, cbody)
    ckey = body_hash_of(cur, h1 + ">" + h2)
    cur.execute(
        "INSERT INTO memory_nodes (session_id, content_hash, body, origin,"
        " source_hashes, source_at, builder_version, consolidation_key)"
        " VALUES (%s, %s, %s, 'consolidation', ARRAY[%s,%s], now(), 1, %s)",
        (sid4, chash, cbody, h1, h2, ckey))
    for sh, dh in ((h1, chash), (chash, h2)):
        cur.execute(
            "INSERT INTO memory_links (session_id, src_hash, dst_hash, rel,"
            " origin, decision_id, structural, policy_version)"
            " VALUES (%s, %s, %s, 'related_to', 'consolidation', NULL, NULL, 1)",
            (sid4, sh, dh))
    cur.execute(
        "INSERT INTO memory_links (session_id, src_hash, dst_hash, rel,"
        " origin, decision_id, structural, policy_version)"
        " VALUES (%s, %s, %s, 'contradicts', 'consolidation', NULL, NULL, 1)",
        (sid4, h1, h2))
    C.commit()
    C.ensure()
    cur = C.cur
    cur.execute("SELECT set_config('typesafe.mock_response', %s, true)",
                (json.dumps({"model": "jev-mock",
                             "answers": {"bogus::x": {"type": "noul", "noul": 0.9}},
                             "usage": {"input_tokens": 1, "output_tokens": 1}}),))
    cur.execute("SELECT count(*) FROM judgment_calls")
    calls4a = cur.fetchone()[0]
    cur.execute("SELECT v13_mgraph_rebuild(%s)", (sid4,))
    rb4 = cur.fetchone()[0]
    C.commit()
    check("D4: poisoned rebuild asked=0 / failed=false",
          rb4["build"]["asks"] == 0 and rb4["build"]["failed"] is False, rb4)
    cur.execute("SELECT count(*) FROM judgment_calls")
    check("D4: zero judgment_calls rows (poison would have logged any ask)",
          cur.fetchone()[0] == calls4a)
    check("D4: temporal edge set byte-identical after rebuild",
          links_of(cur, sid4, "temporal") == temp_a)
    check("D4: jev edges re-applied identically",
          links_of(cur, sid4, "jev") == jev_a)
    check("D4: proximity edges re-derived identically",
          links_of(cur, sid4, "proximity") == prox_a)
    cur.execute(
        "SELECT count(*) FROM memory_nodes WHERE session_id=%s"
        " AND content_hash=%s AND origin='consolidation'", (sid4, chash))
    check("D4: consolidation fixture node survives", cur.fetchone()[0] == 1)
    cur.execute(
        "SELECT count(*) FROM memory_links WHERE session_id=%s"
        " AND origin='consolidation' AND (src_hash=%s OR dst_hash=%s)",
        (sid4, chash, chash))
    check("D4: consolidation endpoint edges survive", cur.fetchone()[0] == 2)
    cur.execute(
        "SELECT count(*) FROM memory_links WHERE session_id=%s"
        " AND origin='consolidation' AND rel='contradicts'", (sid4,))
    check("D4: episodic-episodic consolidation-origin edge deleted (endpoint rule)",
          cur.fetchone()[0] == 0)
    cur.execute("SELECT v13_mgraph_rebuild(%s)", (sid4,))
    C.commit()
    check("D4: double rebuild temporal still identical",
          links_of(cur, sid4, "temporal") == temp_a)
    check("D4: double rebuild proximity identical (same-index snapshot, OQ7)",
          links_of(cur, sid4, "proximity") == prox_a)

    # ---------------- D13 source_at == events.at ----------------
    cur.execute(
        "SELECT n.content_hash, n.source_at, e.at FROM memory_nodes n"
        " JOIN transcript_chunks t ON t.session_id = n.session_id"
        " AND t.content_hash = n.content_hash"
        " JOIN events e ON e.session_id = t.session_id AND e.seq = t.seq_from"
        " WHERE n.session_id = %s AND n.origin = 'episodic'"
        " ORDER BY t.seq_from", (sid1,))
    rows13 = cur.fetchall()
    check("D13: source_at equals the source event at() (events.at backfill)",
          len(rows13) == 2 and all(r[1] == r[2] for r in rows13), rows13)

    # ---------------- D9 re-enter apply after the crash window ----------------
    cur.execute("DELETE FROM memory_links WHERE session_id=%s AND origin='jev'",
                (sid1,))
    C.commit()
    cur.execute("SELECT count(*) FROM judgment_calls")
    calls9a = cur.fetchone()[0]
    cur.execute("SELECT v13_mgraph_apply_relations(%s)", (sid1,))
    r9 = cur.fetchone()[0]
    C.commit()
    check("D9: re-entering apply restores edges (idempotent replay)",
          r9["jev_edges"] == 1 and links_of(cur, sid1, "jev") == jev_d1, r9)
    cur.execute("SELECT count(*) FROM judgment_calls")
    check("D9: re-entry asks nothing", cur.fetchone()[0] == calls9a)

    # ---------------- D14 duplicate body folding ----------------
    pb14 = "Xiomara calibrated the sensor array."
    sid14 = mk_session(cur, [pb14, pb14], same_txn=False)
    C.ensure()
    cur = C.cur
    nxt = next_env(cur, sid14)
    cur.execute("SELECT set_config('typesafe.mock_response', %s, true)",
                (mock_answers(nxt[1]),))
    cur.execute("SELECT v13_mgraph_build(%s, 100)", (sid14,))
    C.commit()
    cur.execute("SELECT count(*) FROM transcript_chunks WHERE session_id=%s",
                (sid14,))
    check("D14: two transcript rows for the same body", cur.fetchone()[0] == 2)
    cur.execute("SELECT count(*), min(source_at) FROM memory_nodes"
                " WHERE session_id=%s AND origin='episodic'", (sid14,))
    n14, sa14 = cur.fetchone()
    cur.execute(
        "SELECT e.at FROM events e JOIN transcript_chunks t"
        " ON t.session_id = e.session_id AND t.seq_from = e.seq"
        " WHERE e.session_id = %s ORDER BY e.seq LIMIT 1", (sid14,))
    at14 = cur.fetchone()[0]
    check("D14: folded to a single node keeping the earliest source_at",
          n14 == 1 and sa14 == at14, (n14, sa14, at14))
    cur.execute("SELECT set_config('typesafe.mock_response', %s, true)",
                (json.dumps({"model": "jev-mock",
                             "answers": {"bogus::y": {"type": "noul", "noul": 0.9}},
                             "usage": {"input_tokens": 1, "output_tokens": 1}}),))
    cur.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s", (sid14,))
    calls14a = cur.fetchone()[0]
    C.ensure()
    cur = C.cur
    cur.execute("SELECT v13_mgraph_rebuild(%s)", (sid14,))
    C.commit()
    cur.execute("SELECT count(*), min(source_at) FROM memory_nodes"
                " WHERE session_id=%s AND origin='episodic'", (sid14,))
    n14b, sa14b = cur.fetchone()
    cur.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s", (sid14,))
    check("D14: rebuild keeps one node, same source_at, zero asks",
          n14b == 1 and sa14b == sa14
          and cur.fetchone()[0] == calls14a, (n14b, sa14b))

    # ---------------- D7 entity gate (OQ10) ----------------
    cur.execute("SELECT v13_mgraph_entities(%s)", ("纯中文正文测试",))
    check("D7: CJK body -> {} (no raise)", cur.fetchone()[0] == [])
    cur.execute("SELECT v13_mgraph_entities(%s)", ("東京タワーAlice paid 42 dollars",))
    check("D7: mixed body -> latin CamelCase entities only",
          cur.fetchone()[0] == ["Alice"])
    hA = body_hash_of(cur, "Alice met Bob.")
    cur.execute("SELECT v13_mgraph_pair_questions(%s,%s,%s,%s)",
                (hA, body_hash_of(cur, "中文正文。"), "Alice met Bob.", "中文正文。"))
    pqA = cur.fetchone()[0]
    check("D7: mixed pair asks no entity relation (one side empty)",
          len(pqA) == 3 and not any(q["signal"].endswith("::entity") for q in pqA),
          [q["signal"] for q in pqA])
    cur.execute("SELECT v13_mgraph_pair_questions(%s,%s,%s,%s)",
                (hA, body_hash_of(cur, "Carol met Dave."),
                 "Alice met Bob.", "Carol met Dave."))
    pqB = cur.fetchone()[0]
    check("D7: disjoint non-empty entity sets include the entity question",
          len(pqB) == 4 and any(q["signal"].endswith("::entity") for q in pqB))
    sid7 = mk_session(cur, ["Alice shipped the crate.",
                            "Alice shipped the crate with 备注。"])
    stepper(sid7)
    cur = C.cur
    cur.execute(
        "SELECT count(*) FROM decisions WHERE session_id=%s"
        " AND signal LIKE '%%::entity'", (sid7,))
    check("D7: build asked no entity relation for the mixed pair",
          cur.fetchone()[0] == 0)
    cur.execute(
        "SELECT count(*) FROM decisions WHERE session_id=%s"
        " AND signal LIKE 'mem\\_rel::%%::semantic'", (sid7,))
    check("D7: semantic relation still asked", cur.fetchone()[0] >= 1)

    # ---------------- D10 no mirroring ----------------
    pa = "Mora and Nils ferried the barge."
    pb = "Nils and Mora ferried the barge."
    ha, hb = body_hash_of(cur, pa), body_hash_of(cur, pb)
    sid10 = mk_session(cur, [pa, pb])
    stepper(sid10, over={f"mem_rel::{ha}::{hb}::causes": 0.9})
    cur = C.cur
    jev10 = links_of(cur, sid10, "jev")
    check("D10: causes over threshold -> exactly one causes edge, no mirror",
          len(jev10) == 1 and jev10[0][2] == "causes"
          and (jev10[0][0], jev10[0][1]) == (ha, hb), jev10)

    # ---------------- D8 spend gate ----------------
    sid8 = mk_session(cur, [PB1, PB2])
    spend_cap(0)
    C.ensure()
    cur = C.cur
    cur.execute("SELECT count(*) FROM judgment_calls")
    calls8a = cur.fetchone()[0]
    cur.execute("SELECT v13_mgraph_build(%s, 100)", (sid8,))
    r8 = cur.fetchone()[0]
    C.commit()
    check("D8: spend cap 0 -> skipped=spend with zero asks",
          r8.get("skipped") == "spend" and r8["asks"] == 0, r8)
    cur.execute("SELECT count(*) FROM judgment_calls")
    check("D8: asked=0 (no call rows)", cur.fetchone()[0] == calls8a)
    set_active("judge_spend_gate", 1)

    # ---------------- D11 caps, cursor resume, increment-only asks ----------------
    p4 = ["Quinn Rhea Sven Tara unloaded the truck.",
          "Rhea Sven Tara Quinn unloaded the truck.",
          "Sven Tara Quinn Rhea unloaded the truck.",
          "Tara Quinn Rhea Sven unloaded the truck."]
    sid11 = mk_session(cur, p4)
    h4 = [body_hash_of(cur, b) for b in p4]
    res11, waves11 = stepper(sid11)
    cur = C.cur
    cur.execute(
        "SELECT DISTINCT ON (content_hash) content_hash, seq_from"
        " FROM transcript_chunks WHERE session_id=%s"
        " ORDER BY content_hash, seq_from", (sid11,))
    fs11 = dict(cur.fetchall())
    check("D11: first call stops at the cap with cursor/watermark untouched",
          res11[0]["stop_reason"] == "batches" and res11[0]["asks"] == 1
          and res11[0]["rel_cursor"] is None and res11[0]["watermark"] == -1
          and res11[0]["pending_nodes"] == 4, res11[0])
    check("D11: mid-run calls keep the cursor behind the unfinished node",
          all(r["rel_cursor"] is None and r["watermark"] == -1
              for r in res11[1:3]), [r["pending_nodes"] for r in res11[1:3]])
    check("D11: call completing node 1 pins cursor, watermark=its seq",
          res11[3]["rel_cursor"] == h4[0] and res11[3]["watermark"] == fs11[h4[0]]
          and res11[3]["pending_nodes"] == 3, res11[3])
    check("D11: resume asks only uncovered signals (waves pairwise disjoint)",
          len(set().union(*waves11)) == sum(len(w) for w in waves11), waves11)
    cur.execute(
        "SELECT count(*) FROM decisions WHERE session_id=%s"
        " AND signal LIKE 'mem\\_%%'", (sid11,))
    check("D11: full coverage 4x4 type + 12x3 pair = 52",
          cur.fetchone()[0] == 52)
    cur.execute("SELECT v13_mgraph_progress(%s)", (sid11,))
    prog11 = cur.fetchone()[0]
    check("D11: final cursor=last node, watermark=its seq",
          prog11["rel_cursor"] == h4[3] and prog11["watermark"] == fs11[h4[3]],
          prog11)
    # write_max_asks trips first under defaults (64 < session cap 512)
    p4a = ["Uma Vera Wade Xena unloaded the truck.",
           "Vera Wade Xena Uma unloaded the truck.",
           "Wade Xena Uma Vera unloaded the truck.",
           "Xena Uma Vera Wade unloaded the truck."]
    open_write(write_max_batches=64, write_max_asks=1)
    sid11a = mk_session(cur, p4a)
    C.ensure()
    cur = C.cur
    nxt = next_env(cur, sid11a)
    cur.execute("SELECT set_config('typesafe.mock_response', %s, true)",
                (mock_answers(nxt[1]),))
    cur.execute("SELECT v13_mgraph_build(%s, 100)", (sid11a,))
    r11a = cur.fetchone()[0]
    C.commit()
    check("D11: write_max_asks exhaustion returns the gap count",
          r11a["stop_reason"] == "asks" and r11a["asks"] == 1
          and r11a["pending_nodes"] == 4, r11a)
    # lowered session_asks_cap makes the spend gate bind before write caps
    p4b = ["Yara Zane Abel Bjorn unloaded the truck.",
           "Zane Abel Bjorn Yara unloaded the truck.",
           "Abel Bjorn Yara Zane unloaded the truck.",
           "Bjorn Yara Zane Abel unloaded the truck."]
    sid11b = mk_session(cur, p4b)
    spend_cap(1)
    C.ensure()
    cur = C.cur
    nxt = next_env(cur, sid11b)
    cur.execute("SELECT set_config('typesafe.mock_response', %s, true)",
                (mock_answers(nxt[1]),))
    cur.execute("SELECT v13_mgraph_build(%s, 100)", (sid11b,))
    r11b = cur.fetchone()[0]
    C.commit()
    check("D11: session_asks_cap below write cap -> spend gate binds (not asks cap)",
          r11b["stop_reason"] == "spend" and r11b["asks"] == 1
          and r11b.get("skipped") is None, r11b)
    set_active("judge_spend_gate", 1)
    open_write(write_max_batches=1, write_max_asks=1)

    # ---------------- D16 success path + rebuild reset ----------------
    pa16 = "Omar and Petra lifted the piano."
    pb16 = "Petra and Omar lifted the piano."
    sid16 = mk_session(cur, [pa16, pb16])
    h16a, h16b = body_hash_of(cur, pa16), body_hash_of(cur, pb16)
    res16, _ = stepper(sid16)
    cur = C.cur
    cur.execute(
        "SELECT DISTINCT ON (content_hash) content_hash, seq_from"
        " FROM transcript_chunks WHERE session_id=%s"
        " ORDER BY content_hash, seq_from", (sid16,))
    fs16 = dict(cur.fetchall())
    cur.execute(
        "SELECT rel_cursor, transcript_watermark FROM v13_mgraph_meta"
        " WHERE session_id=%s", (sid16,))
    c16, w16 = cur.fetchone()
    check("D16: success path cursor=last node, watermark=its seq (not null)",
          c16 == h16b and w16 == fs16[h16b] and w16 is not None, (c16, w16))
    spend_cap(0)
    C.ensure()
    cur = C.cur
    cur.execute("SELECT v13_mgraph_rebuild(%s)", (sid16,))
    rb16 = cur.fetchone()[0]
    C.commit()
    check("D16: rebuild under spend skip leaves the reset state observable",
          rb16["build"].get("skipped") == "spend", rb16)
    cur.execute(
        "SELECT transcript_watermark, rel_cursor FROM v13_mgraph_meta"
        " WHERE session_id=%s", (sid16,))
    w16b, c16b = cur.fetchone()
    check("D16: rebuild reset watermark=-1 and rel_cursor=NULL together",
          w16b == -1 and c16b is None, (w16b, c16b))
    cur.execute(
        "SELECT count(*) FROM memory_nodes WHERE session_id=%s"
        " AND origin='episodic'", (sid16,))
    check("D16: build re-projected nodes before the spend stop",
          cur.fetchone()[0] == 2)
    set_active("judge_spend_gate", 1)

    # ---------------- D5 two connections building concurrently ----------------
    sid5 = mk_session(cur, [PB1, PB2])
    stepper(sid5)                       # everything decided & committed
    cur = C.cur
    lockA, kA = fresh_conn()
    kA.execute("SELECT pg_advisory_lock(v13_lock_key(%s, 'mgraph-build'))",
               (sid5,))
    box5 = {}

    def _b5():
        cB, kB = fresh_conn()
        try:
            kB.execute("SELECT v13_mgraph_build(%s, 100)", (sid5,))
            box5["res"] = kB.fetchone()[0]
            cB.commit()
        except Exception as exc:            # pragma: no cover
            box5["err"] = repr(exc)
            cB.rollback()
        finally:
            cB.close()

    t5 = threading.Thread(target=_b5)
    t5.start()
    time.sleep(1.0)
    check("D5: second build blocks on the session advisory lock",
          t5.is_alive() and "res" not in box5)
    C.ensure()
    cur = C.cur
    cur.execute(
        "SELECT pg_try_advisory_lock(v13_lock_key(%s, 'mgraph-build'))", (sid5,))
    check("D5: build lock observed held", cur.fetchone()[0] is False)
    C.commit()
    kA.execute("SELECT pg_advisory_unlock(v13_lock_key(%s, 'mgraph-build'))",
               (sid5,))
    lockA.commit()
    lockA.close()
    t5.join(timeout=15)
    check("D5: blocked build completed after lock release",
          not t5.is_alive() and "res" in box5, box5)
    r5b = box5.get("res") or {}
    check("D5: second connection made zero asks (committed prefix absorbed)",
          r5b.get("asks") == 0 and r5b.get("pending_nodes") == 0, r5b)
    cur.execute(
        "SELECT count(*) FROM (SELECT signal FROM decisions WHERE session_id=%s"
        " GROUP BY signal HAVING count(*) > 1) d", (sid5,))
    check("D5: one decision row per signal", cur.fetchone()[0] == 0)

    # ---------------- D6 append_event during build ----------------
    lockB, kB = fresh_conn()
    kB.execute("SELECT pg_advisory_lock(v13_lock_key(%s, 'mgraph-build'))",
               (sid5,))
    b6 = "Kim and Lars hauled the raft ashore."
    h6 = body_hash_of(kB, b6)
    kB.execute(
        "INSERT INTO memory_nodes (session_id, content_hash, body, origin,"
        " source_hashes, source_at, builder_version)"
        " VALUES (%s, %s, %s, 'episodic', ARRAY[%s], now(), 1)",
        (sid5, h6, b6, h6))            # uncommitted: FK KEY SHARE footprint
    connC, kC = fresh_conn()
    t0 = time.monotonic()
    kC.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid5, u(), json.dumps({"text": "d6 probe one"})))
    dt1 = time.monotonic() - t0
    connC.commit()
    connC.close()
    check("D6: append_event under the build lock footprint < 5s", dt1 < 5.0, dt1)
    box6 = {}

    def _b6():
        cB, kb = fresh_conn()
        try:
            kb.execute("SELECT v13_mgraph_build(%s, 100)", (sid5,))
            box6["res"] = kb.fetchone()[0]
            cB.commit()
        except Exception as exc:            # pragma: no cover
            box6["err"] = repr(exc)
            cB.rollback()
        finally:
            cB.close()

    t6 = threading.Thread(target=_b6)
    t6.start()
    time.sleep(0.8)
    connC2, kC2 = fresh_conn()
    t0 = time.monotonic()
    kC2.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid5, u(), json.dumps({"text": "d6 probe two"})))
    dt2 = time.monotonic() - t0
    connC2.commit()
    connC2.close()
    check("D6: append_event while a real build waits at the lock < 5s",
          dt2 < 5.0 and t6.is_alive(), (dt2, t6.is_alive()))
    lockB.rollback()
    kB.execute("SELECT pg_advisory_unlock(v13_lock_key(%s, 'mgraph-build'))",
               (sid5,))
    lockB.commit()
    lockB.close()
    t6.join(timeout=15)
    check("D6: blocked build finished after release", "res" in box6
          and not t6.is_alive() and box6["res"]["asks"] == 0, box6)

    # ---------------- D12 routing generation flip (jev fixture) ----------------
    sid12 = u()
    C.ensure()
    cur = C.cur
    cur.execute("INSERT INTO sessions (session_id) VALUES (%s)", (sid12,))
    cur.execute(
        "INSERT INTO v13_mgraph_meta (session_id) VALUES (%s)"
        " ON CONFLICT (session_id) DO NOTHING", (sid12,))
    bump_policy(cur, "mgraph", dict(EXPECTED_POLICY, routing_mode="jev"))
    C.commit()
    q12 = "Why did the deploy fail?"
    cur.execute("SELECT v13_body_hash(btrim(%s))", (q12,))
    qh12 = cur.fetchone()[0]

    # Signal shape §1.5: mem_route::<query_hash>::<graph>@<generation> —
    # the <graph> slot carries the routing bucket name (one per question;
    # a bare graph-name constant would collide all six questions on one
    # signal), and every copy carries the generation (invariant 15).
    route_buckets = [("mem_routing_semantic", "semantic"),
                     ("mem_routing_temporal", "temporal"),
                     ("mem_routing_causal", "causal"),
                     ("mem_routing_entity", "entity"),
                     ("mem_routing_multi_hop_need", "multi_hop"),
                     ("mem_routing_recency_importance", "recency")]

    def routing_env(gen):
        qs = [{"signal": f"mem_route::{qh12}::{bucket}@{gen}",
               "template_name": tn} for tn, bucket in route_buckets]
        return envelope_of(cur, sid12, {"query": q12}, qs)

    env12a = routing_env(0)
    cur.execute("SELECT set_config('typesafe.mock_response', %s, true)",
                (mock_for_needed(env12a),))
    cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
                (json.dumps(env12a),))
    res12a = cur.fetchone()[0]
    C.commit()
    check("D12: jev-mode routing six questions land in one batch",
          res12a["asked_batches"] == 1 and res12a["asked_questions"] == 6
          and res12a["failed"] is False, res12a)
    cur.execute(
        "SELECT request_hash FROM decisions WHERE session_id=%s"
        " AND signal LIKE 'mem\\_route::%%'", (sid12,))
    rh12a = {r[0] for r in cur.fetchall()}
    check("D12: generation-0 answers landed (6 rows)", len(rh12a) == 6)
    cur.execute(
        "UPDATE v13_mgraph_meta SET generation = generation + 1"
        " WHERE session_id=%s", (sid12,))
    C.commit()
    C.ensure()                           # recycle: this connection has asked
    cur = C.cur
    env12b = routing_env(1)
    cur.execute("SELECT set_config('typesafe.mock_response', %s, true)",
                (mock_for_needed(env12b),))
    cur.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                (sid12,))
    calls12a = cur.fetchone()[0]
    cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
                (json.dumps(env12b),))
    res12b = cur.fetchone()[0]
    C.commit()
    cur.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                (sid12,))
    check("D12: generation flip re-asks (old routing answers not reused)",
          res12b["asked_batches"] == 1 and cur.fetchone()[0] == calls12a + 1,
          res12b)
    cur.execute(
        "SELECT request_hash FROM decisions WHERE session_id=%s"
        " AND signal LIKE 'mem\\_route::%%'", (sid12,))
    rh12b = {r[0] for r in cur.fetchall()}
    check("D12: 12 rows total, request_hash spaces disjoint (invariant 15)",
          len(rh12b) == 12 and len(rh12b - rh12a) == 6, len(rh12b))
    cur.execute(
        "SELECT count(*) FROM decisions WHERE session_id=%s"
        " AND signal LIKE 'mem\\_route::%%'", (sid1,))
    check("D12: deterministic mode produced no mem_route rows",
          cur.fetchone()[0] == 0)

    # ---------------- M2 source discipline + policy restore ----------------
    sql_m2 = SQL_FILE.read_text(encoding="utf-8")
    norm_m2 = strip_sql_comments(sql_m2)
    check("M2: bind operator exactly 1 in comment-stripped source",
          norm_m2.count("==>") == 1, norm_m2.count("==>"))
    check("M2: whole-file scan still clean (A7 five tokens)",
          all(sql_m2.count(tok) == 0 for tok in (
              "typesafe_ask", "v13_append_event", "FOR UPDATE",
              "mock_response", "cypher(")))
    set_active("mgraph", 1)
    cur.execute(
        "SELECT version, (value->>'write_enabled')::boolean FROM v13_policies"
        " WHERE name='mgraph' AND active")
    v_fin, w_fin = cur.fetchone()
    check("M2: policy restored to v1 with write back off",
          v_fin == 1 and w_fin is False, (v_fin, w_fin))
    C.conn.rollback()
    C.conn.close()

    print("\n[mgraph M1+M2] groups A+D: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
