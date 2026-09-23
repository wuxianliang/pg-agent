"""DP9 M1 gate (G-mg group A): mgraph dark library — tables/indexes, policy
row + fail-closed reader, six mem_* template families seeded verbatim from
QUESTION_SNAPSHOT.md, judgment_defaults six new points, needed_judgments
untouched + cgr bump, ACL negative face, source scan, zero side effects,
envelope constructor batch shape. M2-M4 groups (D/E/F) land with their
milestones.

Run: uv run python v13/mgraph/test_mgraph.py  (exit 0 = pass)
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
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

    print("\n[mgraph M1] group A: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
