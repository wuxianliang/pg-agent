"""DP9 M1 gate (G-mg group A): mgraph dark library — tables/indexes, policy
row + fail-closed reader, six mem_* template families seeded verbatim from
QUESTION_SNAPSHOT.md, judgment_defaults six new points, needed_judgments
untouched + cgr bump, ACL negative face, source scan, zero side effects,
envelope constructor batch shape. M2 group D (write & rebuild): build/apply/
rebuild/candidates, caps & cursor semantics, concurrency, poisoned-rebuild
zero-ask. M3 group E (read loop B1): route/allocate/run_round/should_stop/
evidence. M4 group F (consolidation): five-question pair gate, effect kind
mgraph_consolidate + cap v3 + narrow requeue, enqueue/settle, fidelity
gate, consolidation nodes as the first remote-plane artifacts.
V2 V1 group G (candidate-discovery wake-up): mgraph-local anchor compiler
(terms/tinql/guard, STABLE), guard swap at the candidates entry, anchor
source swap at build/anchors/transition_score, policy v2 (41 keys,
candidate_top_k 10->5, anchor_ngram_n/anchor_max_terms).
V2 V2 group H (contradiction path): snapshot-frozen mem_rel_contradicts
slot (29th template, canonical (lo,hi) signal endpoints), apply_relations
closed set + contradicts, proximity-derived cons_pairs with byte-stable
v1 digests, semantic-bucket reachability, dual-gate semantics, multi-tick
rel_cursor resume under write_max_batches=8.
H8 (rerun P0 fix): relation-envelope provider passthrough — structural
5-arg scan of every live + source envelope call site, spent-connection
functional (3-arg face V3002 after a simulated GUC purge, 5-arg face
constructs).

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
    "relation_threshold": 0.60, "candidate_top_k": 5,
    "anchor_ngram_n": 3, "anchor_max_terms": 48,
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
        # v2 V2: a 3-block noul slot combines per rule v1 regardless of the
        # v13-local marker (mem_rel_contradicts carries a criteria pair;
        # single-block local slots like mem_cons_fidelity stay raw).
        if kind == "noul" and len(blocks) == 3:
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
    check("snapshot: 29 slots parsed (28 upstream + fidelity + contradicts)",
          len(slots) == 29, sorted(slots))
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
    check("A2: mgraph v2 active", ver == 2, ver)
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
    check("A2: bad-version fixtures rolled back (single v2 row)",
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
    check("A3: 29 mem_* templates registered", len(rows) == 29, sorted(rows))
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
          cgr_post - cgr_pre >= 29, f"pre={cgr_pre} post={cgr_post} "
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
                "%s, v13_mgraph_anchor_tinql(%s), %s)",
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
    cur.execute("SELECT v13_mgraph_anchor_tinql(%s)", (PB1,))
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
    cur.execute("SELECT * FROM v13_mgraph_candidates(%s, v13_mgraph_anchor_tinql(%s), 10)",
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
    hZh = body_hash_of(cur, "中文正文。")
    cur.execute("SELECT v13_mgraph_pair_questions(%s,%s,%s,%s)",
                (hA, hZh, "Alice met Bob.", "中文正文。"))
    pqA = cur.fetchone()[0]
    check("D7: mixed pair asks no entity relation (one side empty;"
          " contradicts only in the canonical direction)",
          len(pqA) == 3 + (1 if hA < hZh else 0)
          and not any(q["signal"].endswith("::entity") for q in pqA)
          and any(q["signal"].endswith("::contradicts") for q in pqA)
              == (hA < hZh),
          [q["signal"] for q in pqA])
    hC = body_hash_of(cur, "Carol met Dave.")
    cur.execute("SELECT v13_mgraph_pair_questions(%s,%s,%s,%s)",
                (hA, hC, "Alice met Bob.", "Carol met Dave."))
    pqB = cur.fetchone()[0]
    check("D7: disjoint non-empty entity sets include the entity question",
          len(pqB) == 4 + (1 if hA < hC else 0)
          and any(q["signal"].endswith("::entity") for q in pqB))
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
    check("D11: full coverage 4x4 type + 6x4 canonical + 6x3 reverse = 58",
          cur.fetchone()[0] == 58)
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

    # =====================================================================
    # DP9 M3 group E: read loop B1 (G-mg/E1-E9)
    #
    # One envelope per run_round call. The driver asks next_action, mocks
    # that gap, then steps. Provider is captured once per drive and passed
    # into the 5-arg envelope so a spent connection can still preview.
    # =====================================================================
    C.ensure()
    cur = C.cur
    set_active("mgraph", 2)

    BUCKETS = ("causal", "entity", "multi_hop", "recency", "semantic",
               "temporal")

    def as_ints(obj):
        return {k: int(v) for k, v in obj.items()}

    def noul_mock(sigs, spec):
        answers = {}
        for s in sigs:
            if s in spec:
                v = spec[s]
            else:
                v = spec.get("*", 0.55)
                for key, val in spec.items():
                    if key.startswith("*") and key != "*" and s.endswith(key[1:]):
                        v = val
                        break
            answers[s] = {"type": "noul", "noul": v}
        return json.dumps({"model": "jev-mock", "answers": answers,
                           "usage": {"input_tokens": 1, "output_tokens": 1}})

    def put_nodes(c, bodies, at="2020-01-01 00:00:00+00", prox=False):
        sid = u()
        c.execute("INSERT INTO sessions (session_id) VALUES (%s)", (sid,))
        hashes = []
        for b in bodies:
            c.execute("SELECT v13_body_hash(%s)", (b,))
            h = c.fetchone()[0]
            c.execute(
                "INSERT INTO memory_nodes (session_id, content_hash, body,"
                " origin, source_hashes, source_at, builder_version)"
                " VALUES (%s,%s,%s,'episodic',%s,%s::timestamptz,1)",
                (sid, h, b, [h], at))
            hashes.append(h)
        if prox:
            # v2 V2 B2: cons_pairs is proximity-derived — consolidation
            # fixtures need production-shaped proximity edges (origin=
            # 'proximity', structural score, both endpoints episodic).
            for i in range(len(hashes)):
                for j in range(i + 1, len(hashes)):
                    c.execute(
                        "INSERT INTO memory_links (session_id, src_hash,"
                        " dst_hash, rel, origin, decision_id, structural,"
                        " policy_version) VALUES (%s, least(%s,%s),"
                        " greatest(%s,%s), 'proximity', 'proximity', NULL,"
                        " 0.5, 2)",
                        (sid, hashes[i], hashes[j], hashes[i], hashes[j]))
        return sid, hashes

    def open_read(**over):
        ver = bump_policy(cur, "mgraph",
                          dict(EXPECTED_POLICY, read_enabled=True, **over))
        C.commit()
        return ver

    def drive(sid, query, elapsed=0, spec=None, commit=True,
              reconnect=True, pm=None, limit=48):
        spec = spec or {}
        if reconnect:
            C.ensure()
        cur_d = C.cur
        if pm is None:
            cur_d.execute(
                "SELECT current_setting('typesafe.provider', true),"
                " current_setting('typesafe.model', true)")
            pm = cur_d.fetchone()
        outs = []
        shadow = None
        for _ in range(limit):
            cur_d.execute(
                "SELECT v13_mgraph_next_action(%s,%s,%s)",
                (sid, query, elapsed))
            act = cur_d.fetchone()[0]
            if act["action"] in ("done", "skip"):
                outs.append({"preview": act})
                break
            before = None
            if act.get("kind") == "shadow":
                cur_d.execute(
                    "SELECT frontier, calls_used FROM memory_walks"
                    " WHERE session_id=%s AND status='stopped'", (sid,))
                before = cur_d.fetchone()
            if act["action"] == "ask":
                cur_d.execute(
                    "SELECT v13_mgraph_envelope(%s,%s::jsonb,%s::jsonb,%s,%s)",
                    (sid, json.dumps(act["state"]), json.dumps(act["questions"]),
                     pm[0], pm[1]))
                env = cur_d.fetchone()[0]
                gap = gap_of_env(cur_d, env)
                if gap:
                    cur_d.execute(
                        "SELECT set_config('typesafe.mock_response', %s, true)",
                        (noul_mock([g["signal"] for g in gap], spec),))
            cur_d.execute(
                "SELECT v13_mgraph_run_round(%s,%s,%s)",
                (sid, query, elapsed))
            step = cur_d.fetchone()[0]
            outs.append(step)
            if act.get("kind") == "shadow" and before is not None:
                cur_d.execute(
                    "SELECT frontier, calls_used FROM memory_walks"
                    " WHERE session_id=%s AND status='stopped'", (sid,))
                after = cur_d.fetchone()
                shadow = (before, after)
            if commit:
                C.commit()
        else:
            raise AssertionError(
                "drive did not finish: %s" % (outs[-1] if outs else None))
        return outs, shadow, pm

    def walk_row(c, sid):
        c.execute(
            "SELECT walk_id, status, stop_reason, calls_used, frontier, budgets"
            " FROM memory_walks WHERE session_id=%s", (sid,))
        row = c.fetchone()
        if row is None:
            return None
        return {"walk_id": row[0], "status": row[1], "stop_reason": row[2],
                "calls_used": row[3], "frontier": row[4], "budgets": row[5]}

    def alloc(c, weights):
        c.execute("SELECT v13_mgraph_allocate(%s::jsonb)",
                  (json.dumps(weights),))
        return as_ints(c.fetchone()[0])

    # ---------------- E1 allocate -----------------------------------------
    # Hand trace, B=20, exponent 1.5.
    # Equal weights: quota=20/6, floor 3, leftover 2, remainders tied,
    # name order gives the extra unit to causal then entity.
    got_eq = alloc(cur, {b: 1 for b in BUCKETS})
    exp_eq = {"causal": 4, "entity": 4, "multi_hop": 3, "recency": 3,
              "semantic": 3, "temporal": 3}
    check("E1: equal weights, name-order remainder tie",
          got_eq == exp_eq and sum(got_eq.values()) == 20, got_eq)
    check("E1: every active bucket funded (>=1)",
          all(v >= 1 for v in got_eq.values()), got_eq)
    # temporal=5, others=1: temporal remainder is the largest, then causal
    # (name order among the tied unit remainders) takes the second seat.
    got_hi = alloc(cur, {"causal": 1, "entity": 1, "multi_hop": 1,
                         "recency": 1, "semantic": 1, "temporal": 5})
    exp_hi = {"causal": 2, "entity": 1, "multi_hop": 1, "recency": 1,
              "semantic": 1, "temporal": 14}
    check("E1: unequal remainders, largest remainder then name",
          got_hi == exp_hi and sum(got_hi.values()) == 20, got_hi)
    got_zero = alloc(cur, {b: 0 for b in BUCKETS})
    check("E1: all-zero weights become the superset distribution",
          sum(got_zero.values()) == 20 and all(v >= 1 for v in got_zero.values()),
          got_zero)
    fails_with(cur, "SELECT v13_mgraph_allocate(%s::jsonb)",
               (json.dumps({"causal": -1, "entity": 1, "multi_hop": 1,
                            "recency": 1, "semantic": 1, "temporal": 1}),),
               "negative", "E1: negative weight raises V3009", pgcode="V3009")
    bump_policy(cur, "mgraph", dict(EXPECTED_POLICY, total_graph_budget=3))
    C.commit()
    fails_with(cur, "SELECT v13_mgraph_allocate(%s::jsonb)",
               (json.dumps({b: 1 for b in BUCKETS}),),
               "cannot fund", "E1: budget below active-bucket count raises",
               pgcode="V3009")
    bump_policy(cur, "mgraph", dict(EXPECTED_POLICY, total_graph_budget=6))
    C.commit()
    # B=6, one mass-100 bucket and five units: Hamilton parks all 6 on the
    # heavy bucket, then each empty active bucket borrows 1. End state is
    # one each.
    got_b = alloc(cur, {"causal": 100, "entity": 1, "multi_hop": 1,
                        "recency": 1, "semantic": 1, "temporal": 1})
    check("E1: borrow funds every active bucket",
          got_b == {b: 1 for b in BUCKETS} and sum(got_b.values()) == 6, got_b)
    set_active("mgraph", 2)

    # ---------------- E2 route + E4/E9 on one read policy -----------------
    open_read()
    r_why = None
    cur.execute("SELECT v13_mgraph_route(%s)", ("Why did the deploy fail?",))
    r_why = cur.fetchone()[0]
    why_w = {k: float(v) for k, v in r_why["weights"].items()}
    check("E2: WHY query routes deterministic with causal strictly heaviest",
          r_why["mode"] == "deterministic"
          and why_w["causal"] > max(why_w[b] for b in BUCKETS if b != "causal"),
          r_why)
    cur.execute("SELECT v13_mgraph_route(%s)", ("为什么部署失败",))
    r_cjk = cur.fetchone()[0]
    cjk_w = {k: float(v) for k, v in r_cjk["weights"].items()}
    floor = float(EXPECTED_POLICY["deterministic_floor"])
    al_cjk = alloc(cur, r_cjk["weights"])
    check("E2: CJK query is a superset at or above the floor",
          r_cjk["mode"] == "superset"
          and all(cjk_w[b] >= floor for b in BUCKETS)
          and all(al_cjk[b] >= 1 for b in BUCKETS),
          (r_cjk, al_cjk))

    sid_cjk = u()
    cur.execute("INSERT INTO sessions (session_id) VALUES (%s)", (sid_cjk,))
    C.commit()
    calls_before = None
    cur.execute("SELECT count(*) FROM decisions WHERE session_id=%s"
                " AND signal LIKE 'mem\\_route::%%'", (sid_cjk,))
    drive(sid_cjk, "为什么部署失败", spec={"*": 0.2})
    cur = C.cur
    cur.execute("SELECT count(*) FROM decisions WHERE session_id=%s"
                " AND signal LIKE 'mem\\_route::%%'", (sid_cjk,))
    check("E2: CJK deterministic walk asks no routing questions",
          cur.fetchone()[0] == 0)

    def five(tag):
        return [f"alpha beacon {tag} {i}" for i in range(5)]

    ev_spec = {"*::sufficient": 0.95, "*::missing": 0.10,
               "*::contradiction": 0.10, "*::continue": 0.90, "*": 0.50}
    sid_ev, _ = put_nodes(cur, five("ev"))
    C.commit()
    drive(sid_ev, "alpha beacon", spec=ev_spec)
    cur = C.cur
    w_ev = walk_row(cur, sid_ev)
    check("E4: sufficient/missing/contradiction stop as evidence",
          w_ev["status"] == "stopped" and w_ev["stop_reason"] == "evidence"
          and w_ev["calls_used"] == 6, w_ev)
    cur.execute("SELECT count(*) FROM decisions WHERE session_id=%s"
                " AND signal LIKE 'mem\\_route::%%'", (sid_ev,))
    check("E2: deterministic WHY-free walk wrote no mem_route rows",
          cur.fetchone()[0] == 0)

    cur.execute("SELECT v13_body_hash(btrim(%s))", ("alpha beacon",))
    qh_ev = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                (sid_ev,))
    calls_ev = cur.fetchone()[0]
    cur.execute("SELECT v13_mgraph_evidence(%s,%s)", (sid_ev, qh_ev))
    ev = cur.fetchone()[0]
    rows = ev["rows"]
    scores = [float(r["score"]) for r in rows]
    hashes = [r["content_hash"] for r in rows]
    check("E9: stopped walk returns <= inject_top_k, score desc hash asc",
          ev["asks"] == 0 and ev["skipped"] is None
          and 1 <= len(rows) <= EXPECTED_POLICY["inject_top_k"]
          and scores == sorted(scores, reverse=True)
          and all(hashes[i] <= hashes[i + 1]
                  for i in range(len(hashes) - 1)
                  if scores[i] == scores[i + 1]),
          ev)
    cur.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                (sid_ev,))
    check("E9: evidence itself asks nothing", cur.fetchone()[0] == calls_ev)
    cur.execute("SELECT v13_mgraph_evidence(%s,%s)", (sid_ev, "ab" * 32))
    ev_empty = cur.fetchone()[0]
    check("E9: no walk for that hash is an empty zero-ask set",
          ev_empty["rows"] == [] and ev_empty["asks"] == 0
          and ev_empty["skipped"] is None, ev_empty)

    cont_spec = {"*::sufficient": 0.10, "*::missing": 0.10,
                 "*::contradiction": 0.10, "*::continue": 0.10, "*": 0.50}
    sid_co, _ = put_nodes(cur, five("co"))
    C.commit()
    drive(sid_co, "alpha beacon", spec=cont_spec)
    cur = C.cur
    w_co = walk_row(cur, sid_co)
    check("E4: low continue stops as continue, still six batches",
          w_co["status"] == "stopped" and w_co["stop_reason"] == "continue"
          and w_co["calls_used"] == 6, w_co)

    open_read(maximum_jev_calls=6)
    call_spec = {"*::sufficient": 0.10, "*::missing": 0.10,
                 "*::contradiction": 0.10, "*::continue": 0.90, "*": 0.50}
    sid_ca, _ = put_nodes(cur, five("ca"))
    C.commit()
    drive(sid_ca, "alpha beacon", spec=call_spec)
    cur = C.cur
    w_ca = walk_row(cur, sid_ca)
    cur.execute("SELECT v13_mgraph_run_round(%s,%s,0)", (sid_ca, "alpha beacon"))
    again = cur.fetchone()[0]
    C.commit()
    check("E4: calls cap stops after 1 stop batch + 5 traversal batches"
          " and a later round does not ask",
          w_ca["status"] == "stopped" and w_ca["stop_reason"] == "calls"
          and w_ca["calls_used"] == 6 and again["asks"] == 0, (w_ca, again))

    # ---------------- E2 jev routing + shadow ------------------------------
    open_read(routing_mode="jev")
    sid_jv, _ = put_nodes(cur, ["alpha beacon jev route"])
    C.commit()
    C.ensure()
    cur = C.cur
    cur.execute("SELECT v13_mgraph_next_action(%s,%s,0)",
                (sid_jv, "alpha beacon"))
    act_jv = cur.fetchone()[0]
    check("E2: jev mode's first step is the six-question routing envelope",
          act_jv["action"] == "ask" and act_jv["kind"] == "route"
          and len(act_jv["questions"]) == 6, act_jv)
    drive(sid_jv, "alpha beacon", spec={"*": 0.80}, reconnect=True)
    cur = C.cur
    cur.execute("SELECT count(*) FROM decisions WHERE session_id=%s"
                " AND signal LIKE 'mem\\_route::%%'", (sid_jv,))
    check("E2: jev fixture lands six routing decisions",
          cur.fetchone()[0] == 6)

    open_read(routing_shadow=True)
    sid_sh, _ = put_nodes(cur, ["alpha beacon shadow"])
    C.commit()
    _outs, shadow, _pm = drive(sid_sh, "alpha beacon", spec=ev_spec)
    cur = C.cur
    check("E2: shadow ask leaves frontier and calls_used unchanged",
          shadow is not None and shadow[0][0] == shadow[1][0]
          and shadow[0][1] == shadow[1][1], shadow)
    cur.execute("SELECT count(*) FROM decisions WHERE session_id=%s"
                " AND signal LIKE 'mem\\_route::%%'", (sid_sh,))
    check("E2: shadow recorded the six routing decisions",
          cur.fetchone()[0] == 6)

    # ---------------- E3 beam tie + replay equality ------------------------
    open_read(beam_width=2)
    sid_e3, hashes_e3 = put_nodes(
        cur, ["alpha beacon aa", "alpha beacon bb", "alpha beacon cc"])
    C.commit()
    tie_spec = {"*": 0.40, "*::sufficient": 0.95, "*::missing": 0.10,
                "*::contradiction": 0.10, "*::continue": 0.90}
    drive(sid_e3, "alpha beacon", spec=tie_spec, commit=False)
    cur = C.cur
    w_e3a = walk_row(cur, sid_e3)
    cur.execute(
        "DELETE FROM memory_rounds WHERE walk_id IN"
        " (SELECT walk_id FROM memory_walks WHERE session_id=%s)", (sid_e3,))
    cur.execute("DELETE FROM memory_walks WHERE session_id=%s", (sid_e3,))
    drive(sid_e3, "alpha beacon", spec=tie_spec, commit=False, reconnect=False,
          pm=("mock", "jev-mock"))
    cur = C.cur
    w_e3b = walk_row(cur, sid_e3)
    fa = w_e3a["frontier"]
    fb = w_e3b["frontier"]
    check("E3: two rounds inside one transaction share a frontier",
          fa == fb and len(fa) == 2, (fa, fb))
    ordered = sorted(hashes_e3)
    front_h = [x["content_hash"] for x in fa]
    scores_e3 = [float(x["score"]) for x in fa]
    tied = len(scores_e3) == 2 and scores_e3[0] == scores_e3[1]
    check("E3: tied beam keeps the smaller content_hash first",
          tied and front_h == ordered[:2],
          {"frontier": fa, "hashes": ordered})
    C.commit()

    # ---------------- E5 timeout / missing basis ---------------------------
    open_read()
    sid_e5, (h_a, h_b) = put_nodes(
        cur, ["alpha beacon anchor", "quartz fossil unrelated"])
    cur.execute(
        "INSERT INTO memory_links (session_id, src_hash, dst_hash, rel,"
        " origin, decision_id, structural, policy_version)"
        " VALUES (%s,%s,%s,'temporal','temporal',NULL,NULL,1)",
        (sid_e5, h_a, h_b))
    C.commit()
    cur.execute(
        "SELECT v13_mgraph_walk_id(%s, v13_body_hash(btrim(%s)),"
        " (v13_mgraph_progress(%s)->>'generation')::bigint,"
        " (SELECT version FROM v13_policies WHERE name='mgraph' AND active))",
        (sid_e5, "alpha beacon", sid_e5))
    wid_e5 = cur.fetchone()[0]
    sig_rel = f"mem_trav::{wid_e5}::{h_b}::relevance"
    sig_use = f"mem_trav::{wid_e5}::{h_b}::relation_usefulness"
    payload = json.dumps({"signals": [sig_rel, sig_use]})
    cur.execute(
        "INSERT INTO judgment_calls (session_id, candidate_set_hash,"
        " projection_key, payload, payload_hash, provider, model,"
        " question_count, status, error)"
        " VALUES (%s,%s,'mgraph',%s::jsonb,%s,'mock','jev-mock',2,"
        " 'failed_timeout','57014')",
        (sid_e5, "ab" * 32, payload, sha(payload)))
    C.commit()
    cur.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                (sid_e5,))
    calls_e5_pre = cur.fetchone()[0]
    e5_spec = {"*::sufficient": 0.10, "*::missing": 0.10,
               "*::contradiction": 0.10, "*::continue": 0.90, "*": 0.60}
    drive(sid_e5, "alpha beacon", spec=e5_spec)
    cur = C.cur
    w_e5 = walk_row(cur, sid_e5)
    cur.execute(
        "SELECT basis FROM memory_rounds WHERE walk_id=%s AND round=2",
        (wid_e5,))
    basis_row = cur.fetchone()
    basis = basis_row[0] if basis_row else {}
    classes = set(basis.values()) if isinstance(basis, dict) else set()
    front_e5 = {x["content_hash"] for x in (w_e5["frontier"] or [])}
    cur.execute(
        "SELECT count(*) FROM decisions WHERE session_id=%s"
        " AND signal LIKE %s", (sid_e5, f"mem\\_trav::{wid_e5}::{h_b}::%"))
    b_decs = cur.fetchone()[0]
    cur.execute(
        "SELECT count(*) FROM memory_links WHERE session_id=%s"
        " AND origin='jev' AND decision_id IS NULL", (sid_e5,))
    naked = cur.fetchone()[0]
    cur.execute("SELECT calls_used FROM memory_walks WHERE walk_id=%s",
                (wid_e5,))
    used_e5 = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                (sid_e5,))
    calls_e5 = cur.fetchone()[0]
    check("E5: timeout basis, missing basis, structural neighbor kept,"
          " no forged noul and the failed batch counts",
          "default_timeout" in classes and "default_missing" in classes
          and h_b in front_e5 and b_decs == 0 and naked == 0
          and used_e5 == (calls_e5 - calls_e5_pre) + 1,
          {"basis": basis, "frontier": list(front_e5),
           "calls_used": used_e5, "new_calls": calls_e5 - calls_e5_pre})

    cur.execute("SET enable_seqscan = off")
    cur.execute(
        "EXPLAIN (FORMAT TEXT) SELECT * FROM v13_mgraph_neighbors(%s,%s,%s,5)",
        (sid_e5, h_a, ["temporal"]))
    plan_e = "\n".join(r[0] for r in cur.fetchall())
    cur.execute("SET enable_seqscan = on")
    # Tiny fixtures make the planner skip-scan ix_memory_links_dst
    # (session_id, rel) and filter src_hash. Either OQ1 btree counts;
    # a seq scan on memory_links does not.
    check("E5: neighbor plan uses a link btree, not a seq scan",
          "Seq Scan on memory_links" not in plan_e
          and ("ix_memory_links_src" in plan_e
               or "ix_memory_links_dst" in plan_e), plan_e)

    # ---------------- E7 latency -------------------------------------------
    open_read(max_latency_ms=0)
    sid_lat, _ = put_nodes(cur, ["alpha beacon late"])
    C.commit()
    drive(sid_lat, "alpha beacon", elapsed=0, spec=call_spec)
    cur = C.cur
    w_lat = walk_row(cur, sid_lat)
    check("E7: max_latency_ms=0 stops after the first round as latency",
          w_lat["status"] == "stopped" and w_lat["stop_reason"] == "latency",
          w_lat)

    # ---------------- E6 no effects, no resolve/failed, no tuple lock ------
    open_read()
    cur.execute("SELECT count(*) FROM effects")
    eff0 = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM events WHERE type='resolve/failed'")
    rf0 = cur.fetchone()[0]
    sid_e6, _ = put_nodes(cur, ["alpha beacon lock"])
    C.commit()
    drive(sid_e6, "alpha beacon", spec=ev_spec)
    cur = C.cur
    cur.execute("SELECT count(*) FROM effects")
    cur.execute("SELECT count(*) FROM events WHERE type='resolve/failed'")
    # refetch properly
    cur.execute("SELECT count(*) FROM effects")
    eff1 = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM events WHERE type='resolve/failed'")
    rf1 = cur.fetchone()[0]
    check("E6: a finished walk adds no effects and no resolve/failed",
          eff1 == eff0 and rf1 == rf0, (eff0, eff1, rf0, rf1))

    sid_lock = u()
    cur.execute("INSERT INTO sessions (session_id) VALUES (%s)", (sid_lock,))
    C.commit()
    cur.execute(
        "SELECT v13_mgraph_stop_questions("
        " v13_mgraph_walk_id(%s, v13_body_hash(btrim(%s)),"
        "  (v13_mgraph_progress(%s)->>'generation')::bigint,"
        "  (SELECT version FROM v13_policies WHERE name='mgraph' AND active)),"
        " 1)",
        (sid_lock, "alpha beacon", sid_lock))
    stop_qs = cur.fetchone()[0]
    mock_lock = noul_mock([q["signal"] for q in stop_qs], {"*": 0.2})
    lock_conn, lock_cur = fresh_conn()
    lock_cur.execute(
        "SELECT pg_advisory_lock(v13_lock_key(%s, 'mgraph-build'))",
        (sid_lock,))
    box_e6 = {}

    def _e6_round():
        c_b, k_b = fresh_conn()
        try:
            k_b.execute(
                "SELECT set_config('typesafe.mock_response', %s, true)",
                (mock_lock,))
            k_b.execute(
                "SELECT v13_mgraph_run_round(%s,%s,0)",
                (sid_lock, "alpha beacon"))
            box_e6["res"] = k_b.fetchone()[0]
            c_b.commit()
        except Exception as exc:            # pragma: no cover
            box_e6["err"] = repr(exc)
            c_b.rollback()
        finally:
            c_b.close()

    t_e6 = threading.Thread(target=_e6_round)
    t_e6.start()
    time.sleep(0.6)
    conn_ap, k_ap = fresh_conn()
    t0 = time.monotonic()
    k_ap.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid_lock, u(), json.dumps({"text": "e6 probe"})))
    dt_e6 = time.monotonic() - t0
    conn_ap.commit()
    conn_ap.close()
    check("E6: append_event while run_round waits on the advisory lock < 5s",
          dt_e6 < 5.0 and t_e6.is_alive(), (dt_e6, t_e6.is_alive(), box_e6))
    lock_cur.execute(
        "SELECT pg_advisory_unlock(v13_lock_key(%s, 'mgraph-build'))",
        (sid_lock,))
    lock_conn.commit()
    lock_conn.close()
    t_e6.join(timeout=20)
    check("E6: blocked run_round finished and did not raise",
          not t_e6.is_alive() and "res" in box_e6 and "err" not in box_e6,
          box_e6)
    cur.execute("SELECT count(*) FROM effects")
    eff2 = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM events WHERE type='resolve/failed'")
    rf2 = cur.fetchone()[0]
    check("E6: the blocked round still added no effect and no resolve/failed",
          eff2 == eff0 and rf2 == rf0, (eff2, rf2))

    # ---------------- E8 read off / degraded --------------------------------
    set_active("mgraph", 2)
    sid_off = u()
    cur.execute("INSERT INTO sessions (session_id) VALUES (%s)", (sid_off,))
    C.commit()
    cur.execute("SELECT count(*) FROM judgment_calls")
    calls_off = cur.fetchone()[0]
    cur.execute("SELECT v13_body_hash(btrim(%s))", ("alpha beacon",))
    qh_off = cur.fetchone()[0]
    cur.execute("SELECT v13_mgraph_evidence(%s,%s)", (sid_off, qh_off))
    ev_off = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM judgment_calls")
    check("E8: read_enabled=false is an empty skipped:disabled result",
          ev_off["rows"] == [] and ev_off["skipped"] == "disabled"
          and ev_off["asks"] == 0 and cur.fetchone()[0] == calls_off, ev_off)
    cur.execute("SELECT v13_mgraph_run_round(%s,%s,0)", (sid_off, "alpha beacon"))
    rr_off = cur.fetchone()[0]
    C.commit()
    check("E8: run_round honors the same disabled skip",
          rr_off.get("skipped") == "disabled" and rr_off.get("asks") == 0,
          rr_off)

    open_read()
    bump_policy(cur, "memory_stack", {"max_lag_events": 0})
    C.commit()
    sid_deg = mk_session(cur, ["alpha beacon fresh"])
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid_deg, u(), json.dumps({"text": "alpha beacon lagged"})))
    C.commit()
    cur.execute("SELECT v13_transcript_freshness(%s)->>'degraded'", (sid_deg,))
    deg = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM judgment_calls")
    calls_deg = cur.fetchone()[0]
    cur.execute("SELECT v13_mgraph_evidence(%s,%s)", (sid_deg, qh_off))
    ev_deg = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM judgment_calls")
    check("E8: degraded freshness is an empty skipped:degraded result",
          deg == "true" and ev_deg["rows"] == []
          and ev_deg["skipped"] == "degraded" and ev_deg["asks"] == 0
          and cur.fetchone()[0] == calls_deg, (deg, ev_deg))
    set_active("memory_stack", 1)

    # =====================================================================
    # DP9 M4 group F: consolidation (G-mg/F1-F11). One envelope per call
    # (consolidate steps after the first real ask; settle asks at most the
    # fidelity envelope). The predictor mirrors the SQL builders exactly
    # (cons_pairs / cons_questions / pair state) so the global cache closes
    # gaps across calls. Worker cycles use v13_claim + v13_complete like
    # any other effect kind — mgraph_consolidate rides the generic CAS
    # branch (effect_done only; no llm/message, no turn/end).
    # =====================================================================
    set_active("mgraph", 2)
    C.ensure()
    cur = C.cur

    def cons_step(sid, over=None, limit=100):
        """Predict the next pending pair envelope, mock it, run one
        consolidate call; returns (result, key of the pair asked)."""
        over = over or {}
        C.ensure()
        cc = C.cur
        cc.execute("SELECT src,dst,src_body,dst_body,consolidation_key"
                   " FROM v13_mgraph_cons_pairs(%s)", (sid,))
        target = None
        for src, dst, sb, db_, key in cc.fetchall():
            cc.execute("SELECT status FROM memory_consolidations"
                       " WHERE session_id=%s AND consolidation_key=%s",
                       (sid, key))
            row = cc.fetchone()
            if row and row[0] == "adopted":
                continue
            cc.execute("SELECT v13_mgraph_cons_questions(%s,%s,%s,%s)",
                       (src, dst, sb, db_))
            qs = cc.fetchone()[0]
            env = envelope_of(cc, sid,
                              {"left": {"content": sb},
                               "right": {"content": db_}}, qs)
            gap = gap_of_env(cc, env)
            if gap:
                target = (gap, key)
                break
        if target is None:
            cc.execute("SELECT v13_mgraph_consolidate(%s, %s)", (sid, limit))
            return cc.fetchone()[0], None
        gap, key = target
        answers = {}
        for g in gap:
            sig = g["signal"]
            if sig.endswith("::representation"):
                ch = over.get("choice", "merge")
                answers[sig] = {"type": "choice", "choice": ch,
                                "probabilities": {ch: over.get("prob", 0.9)},
                                "confidence": over.get("prob", 0.9)}
            else:
                answers[sig] = {"type": "noul",
                                "noul": over.get(sig.rsplit("::", 1)[1], 0.1)}
        cc.execute("SELECT set_config('typesafe.mock_response', %s, true)",
                   (json.dumps({"model": "jev-mock", "answers": answers,
                                "usage": {"input_tokens": 1,
                                          "output_tokens": 1}}),))
        cc.execute("SELECT v13_mgraph_consolidate(%s, %s)", (sid, limit))
        res = cc.fetchone()[0]
        C.commit()
        check("F0: consolidate call did not fail", res.get("failed") is False,
              res)
        return res, key

    def worker_cycle(text=None, outcome="succeeded"):
        """Claim the single ready effect and complete it like a worker."""
        cur.execute("SELECT v13_claim('fworker', 60000)")
        cl = cur.fetchone()[0]
        check("F0: claim picked the mgraph_consolidate effect",
              cl["kind"] == "mgraph_consolidate", cl)
        C.commit()
        if outcome == "succeeded":
            cur.execute("SELECT v13_complete(%s,%s,%s,'succeeded',%s::jsonb)",
                        (cl["effect_id"], cl["attempt_no"], cl["fence"],
                         json.dumps({"text": text})))
        else:
            cur.execute("SELECT v13_complete(%s,%s,%s,'failed',NULL)",
                        (cl["effect_id"], cl["attempt_no"], cl["fence"]))
        out = cur.fetchone()[0]
        C.commit()
        return cl, out

    def settle_fid(eid, sid, key, sb, db_, text, fid):
        """Predict the fidelity envelope, mock fid, settle."""
        C.ensure()
        cc = C.cur
        fqs = [{"signal": f"mem_cons::{key}::fidelity",
                "template_name": "mem_cons_fidelity"}]
        env = envelope_of(cc, sid, {"source": sb + "\n" + db_,
                                    "summary": text}, fqs)
        gap = gap_of_env(cc, env)
        if gap:
            cc.execute("SELECT set_config('typesafe.mock_response', %s, true)",
                       (json.dumps({"model": "jev-mock",
                                    "answers": {g["signal"]: {
                                        "type": "noul", "noul": fid}
                                        for g in gap},
                                    "usage": {"input_tokens": 1,
                                              "output_tokens": 1}}),))
        cc.execute("SELECT v13_mgraph_consolidate_settle(%s)", (eid,))
        r = cc.fetchone()[0]
        C.commit()
        return r

    def forbidden_event_counts(sid):
        cur.execute(
            "SELECT count(*) FILTER (WHERE type='llm/message'),"
            " count(*) FILTER (WHERE type='turn/end'),"
            " count(*) FILTER (WHERE type='resolve/failed')"
            " FROM events WHERE session_id=%s", (sid,))
        return cur.fetchone()

    # ---------------- F1 contradiction over threshold ----------------
    sid_f1, _ = put_nodes(cur, ["Nadia forged the brass key blank.",
                                "Nadia forged the brass key copy."], prox=True)
    C.commit()
    res_f1, key_f1 = cons_step(sid_f1, over={"contradiction": 0.9})
    check("F1: gate blocks on contradiction over threshold",
          res_f1["eligible"] == [] and res_f1["asks"] == 1, res_f1)
    cur.execute("SELECT v13_mgraph_cons_gate(%s,%s)", (sid_f1, key_f1))
    gate_f1 = cur.fetchone()[0]
    check("F1: gate reason is contradiction",
          gate_f1["allowed"] is False and gate_f1["reason"] == "contradiction",
          gate_f1)
    cur.execute("SELECT v13_mgraph_consolidate_enqueue(%s)", (sid_f1,))
    check("F1: enqueue returns NULL (no eligible pair)",
          cur.fetchone()[0] is None)
    cur.execute("SELECT count(*) FROM effects WHERE kind='mgraph_consolidate'")
    check("F1: zero generation effects", cur.fetchone()[0] == 0)
    cur.execute("SELECT count(*) FROM memory_consolidations WHERE session_id=%s",
                (sid_f1,))
    check("F1: zero queue rows", cur.fetchone()[0] == 0)
    C.commit()

    # ---------------- F2 happy chain + P0 zero-claims --------------------
    FB = ["Priya racked the copper still.", "Priya racked the copper kettle."]
    sid_f2, h_f2 = put_nodes(cur, FB, prox=True)
    # give the pair a pre-existing edge: settle must not touch it (F5)
    cur.execute(
        "INSERT INTO memory_links (session_id, src_hash, dst_hash, rel,"
        " origin, decision_id, structural, policy_version)"
        " VALUES (%s, least(%s,%s), greatest(%s,%s), 'temporal', 'temporal',"
        " NULL, NULL, 1)", (sid_f2, h_f2[0], h_f2[1], h_f2[0], h_f2[1]))
    C.commit()
    before_links_f2 = links_of(cur, sid_f2)
    fb_forbidden0 = forbidden_event_counts(sid_f2)
    res_f2, key_f2 = cons_step(sid_f2)
    cur = C.cur
    check("F2: five-question envelope asked once, pair eligible",
          res_f2["asks"] == 1 and len(res_f2["eligible"]) == 1
          and res_f2["eligible"][0]["consolidation_key"] == key_f2, res_f2)
    cur.execute("SELECT v13_mgraph_consolidate_enqueue(%s)", (sid_f2,))
    eid_f2 = cur.fetchone()[0]
    check("F2: enqueue created the mgraph_consolidate effect",
          eid_f2 is not None)
    C.commit()
    cur.execute("SELECT kind, status, jsonb_object_keys(request)"
                " FROM effects WHERE effect_id=%s ORDER BY 3", (eid_f2,))
    req_keys = sorted(r[2] for r in cur.fetchall())
    cur.execute("SELECT status FROM effects WHERE effect_id=%s", (eid_f2,))
    eff_status_f2 = cur.fetchone()[0]
    cur.execute("SELECT status, effect_id FROM memory_consolidations"
                " WHERE session_id=%s AND consolidation_key=%s",
                (sid_f2, key_f2))
    q_f2 = cur.fetchone()
    check("F2: request carries exactly the five adjudicated keys",
          req_keys == ["consolidation_key", "left_hash", "policy_version",
                       "purpose", "right_hash"]
          and eff_status_f2 == "ready", req_keys)
    check("F2: queue row generating bound to the effect",
          q_f2 == ("generating", eid_f2), q_f2)
    # second enqueue while the effect is live -> NULL (single-active gate)
    cur.execute("SELECT v13_mgraph_consolidate_enqueue(%s)", (sid_f2,))
    check("F2: live effect blocks a second enqueue (gate face)",
          cur.fetchone()[0] is None)
    cl_f2, comp_f2 = worker_cycle("Merged: Priya racked the copper vessels.")
    check("F2: worker complete accepted", comp_f2 == "accepted", comp_f2)
    cur.execute("SELECT count(*) FROM effects WHERE kind='mgraph_consolidate'")
    check("F2: exactly one mgraph_consolidate effect", cur.fetchone()[0] == 1)
    fb_forbidden1 = forbidden_event_counts(sid_f2)
    check("F2: zero llm/message, zero turn/end, zero resolve/failed"
          " (route cannot finish on it)",
          fb_forbidden1 == (0, 0, 0) and fb_forbidden0 == (0, 0, 0),
          (fb_forbidden0, fb_forbidden1))
    # ---------------- F5 settle include (continues the F2 chain) ---------
    cur.execute("SELECT src, dst, src_body, dst_body FROM"
                " v13_mgraph_cons_pairs(%s)", (sid_f2,))
    src_f2, dst_f2, sb_f2, db_f2 = cur.fetchone()
    TEXT_F2 = "Merged: Priya racked the copper vessels."
    st_f5 = settle_fid(eid_f2, sid_f2, key_f2, sb_f2, db_f2, TEXT_F2, 0.9)
    cur = C.cur
    check("F5: settle adopts on fidelity include",
          st_f5["status"] == "adopted" and st_f5["asks"] == 1, st_f5)
    cur.execute("SELECT v13_body_hash(%s)", (TEXT_F2,))
    new_hash_f2 = cur.fetchone()[0]
    cur.execute(
        "SELECT source_hashes, consolidation_key, origin, source_at"
        " FROM memory_nodes WHERE session_id=%s AND content_hash=%s",
        (sid_f2, new_hash_f2))
    node_f5 = cur.fetchone()
    check("F5: new node hash, both parent hashes, key, consolidation origin",
          node_f5 is not None and sorted(node_f5[0]) == sorted([src_f2, dst_f2])
          and node_f5[1] == key_f2 and node_f5[2] == "consolidation", node_f5)
    after_links_f2 = links_of(cur, sid_f2)
    new_edges_f2 = [e for e in after_links_f2 if e not in before_links_f2]
    check("F5: original edges intact + exactly one new consolidation edge",
          set(before_links_f2) <= set(after_links_f2) and len(new_edges_f2) == 1
          and new_edges_f2[0][2] == "related_to"
          and new_edges_f2[0][0] == src_f2 and new_edges_f2[0][1] == new_hash_f2
          and new_edges_f2[0][3] == "consolidation",
          (before_links_f2, after_links_f2))
    cur.execute("SELECT count(*) FROM memory_nodes WHERE session_id=%s"
                " AND origin='episodic'", (sid_f2,))
    check("F5: both parents still present", cur.fetchone()[0] == 2)
    cur.execute("SELECT status, body_hash FROM memory_consolidations"
                " WHERE session_id=%s AND consolidation_key=%s",
                (sid_f2, key_f2))
    q_f5 = cur.fetchone()
    check("F5: queue adopted with product body_hash",
          q_f5 == ("adopted", new_hash_f2), q_f5)

    # ---------------- F3 deterministic check failure ----------------
    sid_f3, _ = put_nodes(cur, ["Ravi tuned the drone oscillator.",
                                "Ravi tuned the drone receiver."], prox=True)
    C.commit()
    res_f3, key_f3 = cons_step(sid_f3)
    cur = C.cur
    cur.execute("SELECT v13_mgraph_consolidate_enqueue(%s)", (sid_f3,))
    eid_f3 = cur.fetchone()[0]
    C.commit()
    worker_cycle("x" * 32769)
    cur.execute("SELECT src_body, dst_body FROM v13_mgraph_cons_pairs(%s)",
                (sid_f3,))
    sb_f3, db_f3 = cur.fetchone()
    cur.execute("SELECT count(*) FROM decisions WHERE session_id=%s"
                " AND signal LIKE '%%::fidelity'", (sid_f3,))
    fid0_f3 = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                (sid_f3,))
    calls0_f3 = cur.fetchone()[0]
    C.ensure()
    cur = C.cur
    cur.execute("SELECT v13_mgraph_consolidate_settle(%s)", (eid_f3,))
    st_f3 = cur.fetchone()[0]
    C.commit()
    cur.execute("SELECT count(*) FROM decisions WHERE session_id=%s"
                " AND signal LIKE '%%::fidelity'", (sid_f3,))
    fid1_f3 = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                (sid_f3,))
    calls1_f3 = cur.fetchone()[0]
    check("F3: over-budget text -> rejected with zero fidelity asks",
          st_f3["status"] == "rejected" and st_f3["reason"] == "over_budget"
          and st_f3["asks"] == 0 and fid1_f3 == fid0_f3
          and calls1_f3 == calls0_f3, st_f3)
    cur.execute("SELECT v13_body_hash(%s)", ("x" * 32769,))
    bh_big = cur.fetchone()[0]
    cur.execute("SELECT status, body_hash FROM memory_consolidations"
                " WHERE session_id=%s AND consolidation_key=%s",
                (sid_f3, key_f3))
    q_f3 = cur.fetchone()
    check("F11: rejected row backfills the attempt body_hash",
          q_f3 == ("rejected", bh_big), q_f3)
    cur.execute("SELECT v13_mgraph_consolidate_settle(%s)", (eid_f3,))
    st_f3b = cur.fetchone()[0]
    C.commit()
    check("F11: rejected row second settle is a zero-ask no-op",
          st_f3b["status"] == "rejected" and st_f3b["asks"] == 0, st_f3b)

    # ---------------- F4 fidelity exclude ----------------
    sid_f4, _ = put_nodes(cur, ["Sasha brewed the oat porter.",
                                "Sasha brewed the oat lager."], prox=True)
    C.commit()
    res_f4, key_f4 = cons_step(sid_f4)
    cur = C.cur
    cur.execute("SELECT v13_mgraph_consolidate_enqueue(%s)", (sid_f4,))
    eid_f4 = cur.fetchone()[0]
    C.commit()
    worker_cycle("Merged: Sasha brewed the oat ales.")
    cur.execute("SELECT src_body, dst_body FROM v13_mgraph_cons_pairs(%s)",
                (sid_f4,))
    sb_f4, db_f4 = cur.fetchone()
    st_f4 = settle_fid(eid_f4, sid_f4, key_f4, sb_f4, db_f4,
                       "Merged: Sasha brewed the oat ales.", 0.1)
    cur = C.cur
    check("F4: fidelity exclude -> rejected, no node",
          st_f4["status"] == "rejected"
          and st_f4["reason"] == "fidelity_exclude" and st_f4["asks"] == 1,
          st_f4)
    cur.execute("SELECT count(*) FROM memory_nodes WHERE session_id=%s"
                " AND origin='consolidation'", (sid_f4,))
    check("F4: zero new nodes; both parents remain",
          cur.fetchone()[0] == 0, None)
    cur.execute("SELECT count(*) FROM memory_nodes WHERE session_id=%s"
                " AND origin='episodic'", (sid_f4,))
    check("F4: both parents still present", cur.fetchone()[0] == 2)

    # ---------------- F6 re-run same key ----------------
    res_f6, key_f6 = cons_step(sid_f2)
    cur = C.cur
    check("F6: second consolidate run asks nothing, pair excluded",
          res_f6["asks"] == 0 and res_f6["pairs"] == 0
          and res_f6["eligible"] == [] and key_f6 is None, res_f6)
    cur.execute("SELECT v13_mgraph_consolidate_enqueue(%s)", (sid_f2,))
    check("F6: enqueue on adopted key returns NULL", cur.fetchone()[0] is None)
    cur.execute("SELECT v13_mgraph_consolidate_settle(%s)", (eid_f2,))
    st_f6 = cur.fetchone()[0]
    C.commit()
    check("F6: second settle idempotent zero-ask adopted",
          st_f6["status"] == "adopted" and st_f6["asks"] == 0, st_f6)
    cur.execute("SELECT count(*) FROM memory_nodes WHERE session_id=%s"
                " AND origin='consolidation'", (sid_f2,))
    check("F6: node not double-inserted", cur.fetchone()[0] == 1)

    # ---------------- F7 isolation from the document corpus -------------
    sql_f7 = SQL_FILE.read_text(encoding="utf-8")
    cur.execute("SELECT v13_recall_candidates(%s)", (sid_f2,))
    rc_f7 = cur.fetchone()[0]
    rc_hashes = {c["content_hash"] for c in rc_f7["candidates"]}
    cur.execute("SELECT content_hash FROM memory_nodes WHERE session_id=%s",
                (sid_f2,))
    graph_hashes = {r[0] for r in cur.fetchall()}
    check("F7: recall_candidates intersects no graph node hash",
          rc_hashes.isdisjoint(graph_hashes),
          rc_hashes & graph_hashes)
    check("F7: the new consolidation node is not a chunk candidate",
          new_hash_f2 not in rc_hashes)
    cur.execute(
        "SELECT pg_get_functiondef('v13_needed_judgments(uuid)'::regprocedure)")
    check("F7: needed_judgments still carries no mem_ face",
          "mem_" not in cur.fetchone()[0])
    check("F7: ALTER TABLE targets are effects only (prior files untouched)",
          set(re.findall(r"ALTER TABLE (\w+)", sql_f7)) == {"effects"},
          set(re.findall(r"ALTER TABLE (\w+)", sql_f7)))
    check("F7: OR REPLACE targets are the two adjudicated functions",
          set(re.findall(r"CREATE OR REPLACE FUNCTION (\w+)", sql_f7))
          == {"v13_mgraph_envelope", "v13_requeue_stale"},
          set(re.findall(r"CREATE OR REPLACE FUNCTION (\w+)", sql_f7)))

    # ---------------- F8 cap + narrow requeue ----------------
    cur.execute("SELECT version, value FROM v13_policies"
                " WHERE name='effect_attempt_cap' AND active")
    ver_f8, cap_f8 = cur.fetchone()
    check("F8: cap v3 active with seven keys, six verbatim",
          ver_f8 == 3 and cap_f8 == {"judge": 4, "tool": 3, "llm": 3,
                                     "human": 2, "context_refresh": 3,
                                     "context_summary": 2,
                                     "mgraph_consolidate": 2}, cap_f8)
    cur.execute("SELECT v13_attempt_ok('mgraph_consolidate',1),"
                " v13_attempt_ok('mgraph_consolidate',2)")
    check("F8: attempt belt for the new kind (cap=2)",
          cur.fetchone() == (True, False))
    check("F8: requeue cap check is per-row kind, not hardcoded",
          "v13_attempt_ok(kind, attempt_no)" in sql_f7)
    sid_f8 = u()
    cur.execute("INSERT INTO sessions (session_id) VALUES (%s)", (sid_f8,))

    def f8_effect(kind, attempt):
        e = u()
        s8 = u()
        cur.execute("INSERT INTO sessions (session_id) VALUES (%s)", (s8,))
        cur.execute(
            "INSERT INTO effects (effect_id, session_id, kind, request,"
            " request_hash, idempotency_key, origin_user_seq, attempt_no,"
            " fence, lease_owner, lease_until, status)"
            " VALUES (%s,%s,%s,'{}'::jsonb,%s,%s,-1,%s,0,'f8',"
            " clock_timestamp() - interval '1 hour','claimed')",
            (e, s8, kind, sha(e), "v13:f8:" + e, attempt))
        return e

    e_j = f8_effect("judge", 0)
    e_m1 = f8_effect("mgraph_consolidate", 0)
    e_m2 = f8_effect("mgraph_consolidate", 2)
    e_l = f8_effect("llm", 0)
    C.commit()
    cur.execute("SELECT v13_requeue_stale()")
    rq_f8 = cur.fetchone()[0]
    C.commit()
    by_id = {}
    cur.execute(
        "SELECT effect_id, status, attempt_no, fence, error FROM effects"
        " WHERE effect_id = ANY(%s::uuid[])", ([e_j, e_m1, e_m2, e_l],))
    for eid, st, at, fn, err in cur.fetchall():
        by_id[eid] = (st, at, fn, err)
    check("F8: judge in-cap reclaimed ready, fence+1 attempt kept",
          by_id[e_j] == ("ready", 0, 1, None), by_id[e_j])
    check("F8: mgraph_consolidate in-cap reclaimed ready, fence+1 attempt kept",
          by_id[e_m1] == ("ready", 0, 1, None), by_id[e_m1])
    check("F8: mgraph_consolidate over cap -> failed + lease_exhausted",
          by_id[e_m2][0] == "failed" and by_id[e_m2][1] == 2
          and by_id[e_m2][3] == {"code": "lease_exhausted"}, by_id[e_m2])
    check("F8: other kinds keep the unknown wall (byte behavior)",
          by_id[e_l][0] == "unknown", by_id[e_l])
    check("F8: requeue counters",
          rq_f8["reclaimed_ready"] == 2 and rq_f8["lease_exhausted"] == 1
          and rq_f8["walled_unknown"] == 1 and rq_f8["walls_total"] == 1,
          rq_f8)
    cur.execute("UPDATE effects SET status='cancelled'"
                " WHERE effect_id IN (%s,%s)", (e_j, e_m1))
    C.commit()

    # ---------------- F9 reachability through the semantic bucket -----
    open_read()
    C.ensure()
    cur = C.cur
    _outs_f9, _sh_f9, _pm_f9 = drive(
        sid_f2, "Priya racked copper",
        spec={"*::sufficient": 0.10, "*::missing": 0.10,
              "*::contradiction": 0.10, "*::continue": 0.90, "*": 0.50})
    cur = C.cur
    w_f9 = walk_row(cur, sid_f2)
    visited_f9 = set(w_f9["budgets"].get("visited", [])) \
        if isinstance(w_f9["budgets"], dict) else set()
    frontier_f9 = {x["content_hash"] for x in (w_f9["frontier"] or [])}
    check("F9: consolidation node reached via traversal (not an anchor)",
          new_hash_f2 in (visited_f9 | frontier_f9),
          {"visited": sorted(visited_f9), "frontier": sorted(frontier_f9)})
    set_active("mgraph", 2)

    # ---------------- F10 ACL negative face ----------------
    cur.execute(
        "SELECT has_function_privilege('v13_resolve',"
        " 'v13_enqueue_effect(uuid,text,jsonb,text)','EXECUTE'),"
        " has_function_privilege('v13_route',"
        " 'v13_enqueue_effect(uuid,text,jsonb,text)','EXECUTE')")
    hp_a = cur.fetchone()
    cur.execute(
        "SELECT has_function_privilege('v13_resolve',"
        " 'v13_mgraph_consolidate_enqueue(uuid)','EXECUTE'),"
        " has_function_privilege('v13_route',"
        " 'v13_mgraph_consolidate_enqueue(uuid)','EXECUTE')")
    hp_b = cur.fetchone()
    cur.execute(
        "SELECT has_function_privilege('v13_resolve',"
        " 'v13_mgraph_consolidate_settle(uuid)','EXECUTE'),"
        " has_function_privilege('v13_route',"
        " 'v13_mgraph_consolidate(uuid,integer)','EXECUTE')")
    hp_c = cur.fetchone()
    check("F10: enqueue faces split resolve(denied)/route(allowed)",
          hp_a == (False, True) and hp_b == (False, True), (hp_a, hp_b))
    check("F10: settle is resolve-only, consolidate is resolve-only",
          hp_c == (True, False), hp_c)
    cur.execute("SET ROLE v13_resolve")
    fails_with(cur, "SELECT v13_mgraph_consolidate_enqueue(%s)", (sid_f2,),
               "permission denied",
               "F10: resolve EXECUTE consolidate_enqueue denied")
    cur.execute("RESET ROLE")
    C.commit()

    # ---------------- F11 retry via effect attempts + obsolete -----
    sid_f11, _ = put_nodes(cur, ["Tomas glazed the clay pitcher.",
                                 "Tomas glazed the clay platter."], prox=True)
    C.commit()
    res_f11, key_f11 = cons_step(sid_f11)
    cur = C.cur
    cur.execute("SELECT v13_mgraph_consolidate_enqueue(%s)", (sid_f11,))
    eid_f11 = cur.fetchone()[0]
    C.commit()
    cl_f11a, _ = worker_cycle(outcome="failed")
    check("F11: first worker attempt failed on the same effect",
          cl_f11a["effect_id"] == eid_f11 and cl_f11a["attempt_no"] == 1)
    C.ensure()
    cur = C.cur
    cur.execute("SELECT v13_mgraph_consolidate_settle(%s)", (eid_f11,))
    st_f11a = cur.fetchone()[0]
    C.commit()
    check("F11: settle on failed effect converges the row to rejected",
          st_f11a["status"] == "rejected" and st_f11a["asks"] == 0, st_f11a)
    res_f11b, key_f11b = cons_step(sid_f11)
    cur = C.cur
    check("F11: re-consolidate is zero-ask (cached) and re-eligible",
          res_f11b["asks"] == 0 and len(res_f11b["eligible"]) == 1
          and key_f11b is None, res_f11b)
    cur.execute("SELECT v13_mgraph_consolidate_enqueue(%s)", (sid_f11,))
    eid_f11b = cur.fetchone()[0]
    cur.execute("SELECT status, attempt_no, fence FROM effects"
                " WHERE effect_id=%s", (eid_f11,))
    eff_f11b = cur.fetchone()
    C.commit()
    check("F11: retry re-mounts the same effect id (attempt rides the row)",
          eid_f11b == eid_f11 and eff_f11b[0] == "ready"
          and eff_f11b[1] == 1 and eff_f11b[2] == 2, (eid_f11b, eff_f11b))
    TEXT_F11 = "Merged: Tomas glazed the clay vessels."
    cl_f11c, _ = worker_cycle(TEXT_F11)
    check("F11: second attempt is attempt 2", cl_f11c["attempt_no"] == 2)
    cur.execute("SELECT src_body, dst_body FROM v13_mgraph_cons_pairs(%s)",
                (sid_f11,))
    sb_f11, db_f11 = cur.fetchone()
    st_f11c = settle_fid(eid_f11, sid_f11, key_f11, sb_f11, db_f11,
                         TEXT_F11, 0.9)
    cur = C.cur
    check("F11: retry with new text adopts",
          st_f11c["status"] == "adopted", st_f11c)
    cur.execute("SELECT count(*) FROM memory_consolidations"
                " WHERE session_id=%s AND consolidation_key=%s",
                (sid_f11, key_f11))
    check("F11: one queue row across the retry (no new row per text)",
          cur.fetchone()[0] == 1)
    cur.execute("SELECT count(*) FROM memory_nodes WHERE session_id=%s"
                " AND origin='consolidation'", (sid_f11,))
    check("F11: retry produced the product node", cur.fetchone()[0] == 1)
    # cap exhaustion: second failed attempt closes the pair for this turn
    sid_f11b, _ = put_nodes(cur, ["Ulla charted the reef pass.",
                                  "Ulla charted the reef cove."], prox=True)
    C.commit()
    _, key_f11b2 = cons_step(sid_f11b)
    cur = C.cur
    cur.execute("SELECT v13_mgraph_consolidate_enqueue(%s)", (sid_f11b,))
    eid_f11b2 = cur.fetchone()[0]
    C.commit()
    worker_cycle(outcome="failed")
    C.ensure()
    cur = C.cur
    cur.execute("SELECT v13_mgraph_consolidate_settle(%s)", (eid_f11b2,))
    C.commit()
    cur.execute("SELECT v13_mgraph_consolidate_enqueue(%s)", (sid_f11b,))
    eid_f11b3 = cur.fetchone()[0]
    C.commit()
    check("F11: in-cap re-mount after first failure",
          eid_f11b3 == eid_f11b2)
    worker_cycle(outcome="failed")
    C.ensure()
    cur = C.cur
    cur.execute("SELECT v13_mgraph_consolidate_settle(%s)", (eid_f11b2,))
    C.commit()
    cur.execute("SELECT v13_mgraph_consolidate_enqueue(%s)", (sid_f11b,))
    r_cap = cur.fetchone()[0]
    cur.execute("SELECT status, attempt_no FROM effects WHERE effect_id=%s",
                (eid_f11b2,))
    eff_cap = cur.fetchone()
    cur.execute("SELECT status FROM memory_consolidations"
                " WHERE session_id=%s AND consolidation_key=%s",
                (sid_f11b, key_f11b2))
    q_cap = cur.fetchone()
    C.commit()
    check("F11: over-cap third enqueue refuses and converges rejected",
          r_cap is None and eff_cap == ("failed", 2) and q_cap == ("rejected",),
          (r_cap, eff_cap, q_cap))
    # obsolete high alone never enqueues
    sid_f11c, _ = put_nodes(cur, ["Vera stowed the main halyard.",
                                  "Vera stowed the main jib."], prox=True)
    C.commit()
    res_f11c, _ = cons_step(sid_f11c, over={"obsolete": 0.9,
                                            "choice": "uncertain"})
    cur = C.cur
    check("F11: obsolete high score alone does not enqueue",
          res_f11c["eligible"] == [], res_f11c)
    cur.execute("SELECT v13_mgraph_consolidate_enqueue(%s)", (sid_f11c,))
    check("F11: enqueue returns NULL, zero effects for obsolete-only",
          cur.fetchone()[0] is None)
    cur.execute("SELECT count(*) FROM effects WHERE kind='mgraph_consolidate'"
                " AND session_id=%s", (sid_f11c,))
    check("F11: obsolete fixture produced no effect", cur.fetchone()[0] == 0)
    C.commit()

    # =====================================================================
    # mgraph v2 V1 group G: candidate-discovery wake-up (G-mg/G1-G9).
    # Plan: docs/plans/v13-dp9-mgraph-v2-plan-2026-09-24.md §5 G table.
    # Anchor compiler = latin whole-segment + CJK char n-gram (n=3 default),
    # dedup-preserving-order, capped at anchor_max_terms; OR-form tinql;
    # mgraph-local guard (quoted-phrase OR closed set, V3005 fail-closed).
    # Mock discipline unchanged: one ask batch shape per GUC value, so the
    # write-path gates (G4/G8) run under write caps=1 with the stepper.
    # =====================================================================

    # ---------------- G1 compiler determinism + policy sensitivity ------
    set_active("mgraph", 2)
    C.commit()

    def anchor_terms_of(c, body):
        c.execute("SELECT v13_mgraph_anchor_terms(%s)", (body,))
        return c.fetchone()[0]

    def anchor_tinql_of(c, body):
        c.execute("SELECT v13_mgraph_anchor_tinql(%s)", (body,))
        return c.fetchone()[0]

    CJK_G1 = "用户无法登录系统因为密码过期"
    MIX_G1 = "Alice shipped 用户受影响 counts 三万"
    for g1b in (CJK_G1, MIX_G1, PB1):
        t_a = anchor_terms_of(cur, g1b)
        t_b = anchor_terms_of(cur, g1b)
        q_a = anchor_tinql_of(cur, g1b)
        q_b = anchor_tinql_of(cur, g1b)
        check(f"G1: same body + same active policy -> identical terms/tinql ({g1b[:10]})",
              t_a == t_b and q_a == q_b and (t_a == []) == (q_a == ""),
              (t_a, q_a))
    t_cjk_full = anchor_terms_of(cur, CJK_G1)
    t_mix_full = anchor_terms_of(cur, MIX_G1)
    check("G1: repeated segments dedup preserving first-seen order",
          anchor_terms_of(cur, "abc abc def abc") == ["abc", "def"])
    bump_policy(cur, "mgraph", dict(EXPECTED_POLICY, anchor_ngram_n=2))
    C.commit()
    t_n2 = anchor_terms_of(cur, CJK_G1)
    check("G1: policy flip (anchor_ngram_n 3->2) changes terms for the same body",
          t_n2 != t_cjk_full and t_n2 == ["用户", "户无", "无法", "法登", "登录",
                                         "录系", "系统", "统因", "因为",
                                         "为密", "密码", "码过", "过期"], t_n2)
    set_active("mgraph", 2)
    C.commit()
    bump_policy(cur, "mgraph", dict(EXPECTED_POLICY, anchor_max_terms=3))
    C.commit()
    t_cap3 = anchor_terms_of(cur, MIX_G1)
    check("G1: truncation keeps the first N terms in order (anchor_max_terms=3)",
          len(t_mix_full) > 3 and t_cap3 == t_mix_full[:3], (t_mix_full, t_cap3))
    set_active("mgraph", 2)
    C.commit()
    bump_policy(cur, "mgraph", dict(EXPECTED_POLICY, anchor_ngram_n=0))
    C.commit()
    t_n0 = anchor_terms_of(cur, MIX_G1)
    cur.execute("SELECT v13_query_segments(%s)", (MIX_G1,))
    segs_g1 = cur.fetchone()[0]
    q_n0 = anchor_tinql_of(cur, MIX_G1)
    check("G1: n=0 degrades to whole-segment OR semantics (== segments, OR-joined)",
          t_n0 == segs_g1 and q_n0 == " OR ".join(f'"{s}"' for s in segs_g1)
          and " AND " not in q_n0, (t_n0, q_n0))
    set_active("mgraph", 2)
    C.commit()

    # ---------------- G2 n-gram boundaries + mixed + bytes vs chars ------
    check("G2: CJK segment of n-1 chars -> zero items",
          anchor_terms_of(cur, "一二") == [])
    check("G2: CJK segment of exactly n chars -> exactly one item",
          anchor_terms_of(cur, "一二三") == ["一二三"])
    check("G2: CJK segment of n+1 chars -> two sliding-window items",
          anchor_terms_of(cur, "一二三四") == ["一二三", "二三四"])
    check("G2: mixed body keeps latin segments whole (never n-grammed)",
          anchor_terms_of(cur, "abc一二三") == ["abc", "一二三"])
    check("G2: latin segment shorter than n still whole",
          anchor_terms_of(cur, "ab cd") == ["ab", "cd"])
    check("G2: 3-char CJK run is 9 UTF-8 bytes but yields exactly one gram"
          " (chars, not bytes)",
          len("一二三".encode("utf-8")) == 9
          and anchor_terms_of(cur, "一二三") == ["一二三"])
    # 85 distinct CJK chars = 255 bytes (passes the segmenter's byte cap);
    # 83 distinct sliding grams -> capped at anchor_max_terms=48.
    g2_85 = "".join(chr(0x4E00 + i) for i in range(85))
    check("G2: 255-byte CJK segment passes the byte cap and truncates at 48 grams",
          len(g2_85.encode("utf-8")) == 255
          and len(anchor_terms_of(cur, g2_85)) == 48)
    fails_with(cur, "SELECT v13_mgraph_anchor_terms(%s)", ("字" * 87,),
               "max bytes", "G2: >256B segment propagates the segmenter V3005",
               pgcode="V3005")
    check("G2: separator-only body -> empty anchor -> empty tinql",
          anchor_terms_of(cur, "。。。") == []
          and anchor_tinql_of(cur, "。。。") == "")

    # ---------------- G3 guard fail-closed closed set -------------------
    def guard_of(t):
        cur.execute("SELECT v13_mgraph_anchor_guard(%s)", (t,))
        return cur.fetchone()[0]

    check("G3: legal OR phrase string passes",
          guard_of('"abc" OR "def"') == ["abc", "def"])
    check("G3: legal CJK OR string passes",
          guard_of('"用户受影响" OR "三万"') == ["用户受影响", "三万"])
    check("G3: empty string -> empty normalized set", guard_of("") == [])
    fails_with(cur, "SELECT v13_mgraph_anchor_guard(%s)", (None,),
               "must not be NULL", "G3: NULL tinql -> V3005", pgcode="V3005")
    fails_with(cur, "SELECT v13_mgraph_anchor_guard(%s)", ('"a" AND "b"',),
               "grammar", "G3: AND form -> V3005 (not the emitted grammar)",
               pgcode="V3005")
    fails_with(cur, "SELECT v13_mgraph_anchor_guard(%s)", ("abc",),
               "grammar", "G3: bare word -> V3005", pgcode="V3005")
    fails_with(cur, "SELECT v13_mgraph_anchor_guard(%s)", ('"a"OR"b"',),
               "grammar", "G3: unspaced OR / embedded quotes -> V3005",
               pgcode="V3005")
    fails_with(cur, "SELECT v13_mgraph_anchor_guard(%s)", ('"ab*"',),
               "character domain", "G3: wildcard -> V3005", pgcode="V3005")
    fails_with(cur, "SELECT v13_mgraph_anchor_guard(%s)", ('"a(b"',),
               "character domain", "G3: regex metachar -> V3005", pgcode="V3005")
    fails_with(cur, "SELECT v13_mgraph_anchor_guard(%s)", ('"ab~"',),
               "character domain", "G3: fuzzy marker -> V3005", pgcode="V3005")
    fails_with(cur, "SELECT v13_mgraph_anchor_guard(%s)", ('"a b"',),
               "character domain", "G3: embedded space -> V3005", pgcode="V3005")
    fails_with(cur, "SELECT v13_mgraph_anchor_guard(%s)", ('"' + "a" * 300 + '"',),
               "out of bounds", "G3: >256B phrase -> V3005", pgcode="V3005")
    check("G3: 48 distinct phrases accepted at the cap",
          len(guard_of(" OR ".join(f'"w{i}"' for i in range(48)))) == 48)
    fails_with(cur, "SELECT v13_mgraph_anchor_guard(%s)",
               (" OR ".join(f'"w{i}"' for i in range(49)),), "max terms",
               "G3: > anchor_max_terms phrases -> V3005", pgcode="V3005")
    for g3b in (CJK_G1, MIX_G1, PB1):
        t_rt = anchor_terms_of(cur, g3b)
        q_rt = anchor_tinql_of(cur, g3b)
        g_rt = guard_of(q_rt)
        check(f"G3: guard(compiler output) == compiler terms ({g3b[:10]})",
              g_rt == t_rt, (q_rt, g_rt, t_rt))

    # ---------------- G4 wake-up: rare-shared-3gram pair asked ----------
    open_write(write_max_batches=1, write_max_asks=1)
    GA = "今天系统里有三万个受影响的用户账号"
    GB = "昨天统计的受影响用户大约只有八千个"
    GN = "数据库每晚做全量备份"
    sid_g4 = mk_session(cur, [GA, GB])
    stepper(sid_g4)
    cur = C.cur
    hA, hB = body_hash_of(cur, GA), body_hash_of(cur, GB)
    sigs_g4 = answered_sigs(cur, sid_g4)
    check("G4: zero-clause-intersection pair sharing rare 3-grams gets its"
          " base relation envelope",
          {f"mem_rel::{hA}::{hB}::semantic", f"mem_rel::{hA}::{hB}::causes",
           f"mem_rel::{hA}::{hB}::caused_by"} <= sigs_g4,
          sorted(s for s in sigs_g4 if s.startswith("mem_rel::")))
    prox_g4 = links_of(cur, sid_g4, "proximity")
    check("G4: proximity edge recorded for the awakened pair",
          any({p[0], p[1]} == {hA, hB} for p in prox_g4), prox_g4)
    cur.execute("SELECT v13_mgraph_anchor_tinql(%s)", (GA,))
    tqA = cur.fetchone()[0]
    cur.execute("SELECT content_hash FROM v13_mgraph_candidates(%s, %s, 5)",
                (sid_g4, tqA))
    pool_g4 = {r[0] for r in cur.fetchall()}
    check("G4: candidate pool contains both endpoints under the OR anchor",
          {hA, hB} <= pool_g4, pool_g4)
    sid_g4n = mk_session(cur, [GA, GN])
    stepper(sid_g4n)
    cur = C.cur
    sigs_g4n = answered_sigs(cur, sid_g4n)
    check("G4: zero shared n-gram -> zero relation envelopes (negative clean)",
          not any(s.startswith("mem_rel::") for s in sigs_g4n), sorted(sigs_g4n))
    cur.execute("SELECT v13_mgraph_anchor_tinql(%s)", (GA,))
    tqA2 = cur.fetchone()[0]
    cur.execute("SELECT content_hash FROM v13_mgraph_candidates(%s, %s, 5)",
                (sid_g4n, tqA2))
    pool_g4n = {r[0] for r in cur.fetchall()}
    check("G4: negative session pool = the anchor itself only",
          pool_g4n == {hA}, pool_g4n)

    # ---------------- G5 read-side anchor on a CJK graph ---------------
    set_active("mgraph", 2)
    C.commit()
    sid_g5, _ = put_nodes(cur, ["用户无法登录系统因为密码过期"])
    C.commit()
    cur.execute("SELECT v13_mgraph_anchors(%s, %s, 'semantic')",
                (sid_g5, "为什么用户无法登录"))
    anch_g5 = cur.fetchone()[0]
    check("G5: pure CJK query anchors non-empty on a CJK graph"
          " (structurally empty pre-V1)", len(anch_g5) >= 1, anch_g5)
    cur.execute("SELECT v13_mgraph_anchors(%s, %s, 'semantic')",
                (sid_g5, "数据库备份策略怎么样"))
    check("G5: unrelated CJK query stays empty", cur.fetchone()[0] == [])

    # ---------------- G6 discipline rescan ------------------------------
    sql_g6 = SQL_FILE.read_text(encoding="utf-8")
    norm_g6 = strip_sql_comments(sql_g6)
    check("G6: bind operator exactly 1 in comment-stripped source",
          norm_g6.count("==>") == 1, norm_g6.count("==>"))
    for fname_g6 in ("v13_mgraph_anchor_terms", "v13_mgraph_anchor_tinql",
                     "v13_mgraph_anchor_guard"):
        cur.execute("SELECT pg_get_functiondef(oid) FROM pg_proc WHERE proname = %s",
                    (fname_g6,))
        fdef = cur.fetchone()[0]
        check(f"G6: {fname_g6} STABLE, zero dynamic binding, zero bind operator",
              "STABLE" in fdef and "EXECUTE" not in fdef and "==>" not in fdef)
    cur.execute(
        "SELECT count(*) FROM pg_proc p CROSS JOIN LATERAL aclexplode(p.proacl) a"
        " WHERE p.proname LIKE 'v13\\_mgraph\\_anchor%' AND a.grantee = 0")
    check("G6: anchor functions carry no PUBLIC grant (grantee=0)",
          cur.fetchone()[0] == 0)
    cur.execute("SELECT v13_mgraph_anchor_tinql(%s)", ("为什么用户无法登录",))
    tq_g6 = cur.fetchone()[0]
    cur.execute("SET enable_seqscan = off")
    cur.execute(
        "EXPLAIN (ANALYZE, FORMAT TEXT) SELECT n.content_hash FROM memory_nodes n"
        " WHERE n.session_id = %s AND n.origin = 'episodic' AND n.body ==> %s",
        (sid_g5, tq_g6))
    plan_g6 = "\n".join(r[0] for r in cur.fetchall())
    cur.execute("SET enable_seqscan = on")
    check("G6: OR-form anchor pool query still drives the stannum predicate",
          "Seq Scan on memory_nodes" not in plan_g6 and "stannum" in plan_g6,
          plan_g6)
    cur.execute(
        "SELECT count(*) FROM memory_nodes n"
        " WHERE n.session_id = %s AND n.origin = 'episodic' AND n.body ==> %s",
        (sid_g5, tq_g6))
    check("G6: the stannum operator matches the CJK node through the OR tinql",
          cur.fetchone()[0] == 1)

    # ---------------- G7 D1/D2 preserved under the OR anchor ------------
    C.ensure()
    cur = C.cur
    cur.execute("SELECT v13_mgraph_anchor_tinql(%s)", (GA,))
    tq_g7 = cur.fetchone()[0]
    cur.execute("SELECT * FROM v13_mgraph_candidates(%s, %s, 10)", (sid_g4, tq_g7))
    ca_g7 = [tuple(str(x) for x in r) for r in cur.fetchall()]
    cur.execute("SELECT * FROM v13_mgraph_candidates(%s, %s, 10)", (sid_g4, tq_g7))
    cb_g7 = [tuple(str(x) for x in r) for r in cur.fetchall()]
    check("G7: same-pool double call byte-identical (D1 condition preserved)",
          ca_g7 == cb_g7 and len(ca_g7) >= 1, (ca_g7, cb_g7))
    fails_with(
        cur, "SELECT * FROM v13_mgraph_candidates(%s, %s, 10)",
        (sid_g4, '"用户无法" AND "登录系统"'), "grammar",
        "G7: AND-form tinql rejected at the candidates entry (guard swap live)",
        pgcode="V3005")

    # ---------------- G8 entity gate awake through the write path -------
    open_write(write_max_batches=1, write_max_asks=1)
    sid_g8 = mk_session(cur, ["Alice shipped the crate.", "Bob ferried the drum."])
    stepper(sid_g8)
    cur = C.cur
    sigs_g8 = answered_sigs(cur, sid_g8)
    ent_g8 = [s for s in sigs_g8
              if s.startswith("mem_rel::") and s.endswith("::entity")]
    check("G8: disjoint-entity pair gets its entity question (deviation #12"
          " postscript: gate awake post-V1)", len(ent_g8) >= 1, sorted(sigs_g8))
    set_active("mgraph", 2)
    C.commit()

    # ---------------- G9 policy v2 shape -------------------------------
    cur.execute("SELECT v13_mgraph_policy()")
    pol_g9 = cur.fetchone()[0]
    check("G9: v2 keyset 41 keys, anchor keys in, routing intent keys out",
          len(pol_g9) == 41 and pol_g9["anchor_ngram_n"] == 3
          and pol_g9["anchor_max_terms"] == 48 and pol_g9["candidate_top_k"] == 5
          and "routing_intent_causal" not in pol_g9
          and "routing_intent_temporal" not in pol_g9, sorted(pol_g9))
    bump_policy(cur, "mgraph",
                {k: v for k, v in EXPECTED_POLICY.items() if k != "anchor_ngram_n"})
    C.commit()
    fails_with(cur, "SELECT v13_mgraph_policy()", (), "key set mismatch",
               "G9: missing anchor key -> V3009 (closed keyset)", pgcode="V3009")
    set_active("mgraph", 2)
    C.commit()
    bump_policy(cur, "mgraph", dict(EXPECTED_POLICY, anchor_ngram_n=2.5))
    C.commit()
    fails_with(cur, "SELECT v13_mgraph_policy()", (), "must be an integer",
               "G9: fractional anchor_ngram_n -> V3009 (integer domain)",
               pgcode="V3009")
    set_active("mgraph", 2)
    C.commit()
    bump_policy(cur, "mgraph", dict(EXPECTED_POLICY, anchor_ngram_n=-1))
    C.commit()
    fails_with(cur, "SELECT v13_mgraph_policy()", (), "must be an integer",
               "G9: negative anchor_ngram_n -> V3009 (fail-closed domain)",
               pgcode="V3009")
    set_active("mgraph", 2)
    C.commit()
    bump_policy(cur, "mgraph", dict(EXPECTED_POLICY, anchor_max_terms=0))
    C.commit()
    fails_with(cur, "SELECT v13_mgraph_policy()", (), ">= 1",
               "G9: zero anchor_max_terms -> V3009 (positive domain)",
               pgcode="V3009")
    set_active("mgraph", 2)
    C.commit()
    bump_policy(cur, "mgraph", dict(EXPECTED_POLICY, routing_intent_causal=0.8))
    C.commit()
    fails_with(cur, "SELECT v13_mgraph_policy()", (), "key set mismatch",
               "G9: routing_intent key refused by the closed keyset (OQ13=D)",
               pgcode="V3009")
    set_active("mgraph", 2)
    C.commit()

    # =====================================================================
    # mgraph v2 V2 group H: contradiction path (G-mg/H1-H7).
    # Plan: docs/plans/v13-dp9-mgraph-v2-plan-2026-09-24.md §5 H table.
    # B3 write side: mem_rel_contradicts (29th template, snapshot-frozen,
    # canonical (lo,hi) hash-order signal endpoints) + apply closed set.
    # B2 pair source: proximity-derived cons_pairs, v1-adjacent digests
    # byte-stable. Cache is cross-session (request_hash carries no sid —
    # D4 precedent), so every H fixture uses bodies fresh to this run.
    # =====================================================================

    # ---------------- H1 pair-source wake-up (proximity-derived) -------
    open_write(write_max_batches=1, write_max_asks=1)
    HTA = "本次上线之后大约有三万个账号受影响"
    HTM = "备份策略是每晚全量快照"
    HTB = "受影响账号最终统计只有八千个"
    HE1 = "Faye sorted the spare cables."
    HE2 = "sorted the spare cables Faye."
    sid_h1 = mk_session(cur, [HTA, HTM, HTB, HE1, HE2], same_txn=False)
    stepper(sid_h1)
    cur = C.cur
    hTA, hTM, hTB = (body_hash_of(cur, x) for x in (HTA, HTM, HTB))
    hE1, hE2 = body_hash_of(cur, HE1), body_hash_of(cur, HE2)
    prox_h1 = links_of(cur, sid_h1, "proximity")
    check("H1: real A5 build produced proximity edges for the non-adjacent"
          " contradiction pair and the adjacent echo pair",
          {frozenset((p[0], p[1])) for p in prox_h1}
          == {frozenset((hTA, hTB)), frozenset((hE1, hE2))}, prox_h1)
    cur.execute(
        "SELECT src, dst, consolidation_key FROM v13_mgraph_cons_pairs(%s)",
        (sid_h1,))
    pairs_h1 = cur.fetchall()
    got_h1 = {frozenset((r[0], r[1])) for r in pairs_h1}
    check("H1: non-adjacent T2/T6-type proximity pair selected",
          frozenset((hTA, hTB)) in got_h1, sorted(map(str, pairs_h1)))
    check("H1: adjacent echo pair with a proximity edge still selected",
          frozenset((hE1, hE2)) in got_h1, sorted(map(str, pairs_h1)))
    check("H1: no-proximity episodic pairs excluded (time-adjacency alone"
          " no longer selects — narrowing adjudicated)",
          hTM not in {h for r in pairs_h1 for h in r[:2]} and len(pairs_h1) == 2,
          sorted(map(str, pairs_h1)))

    # ---------------- H2 canonical digest + v1 byte-stability ----------
    row_h2 = {frozenset((r[0], r[1])): r[2] for r in pairs_h1}
    check("H2: one key per unordered proximity pair, keys unique",
          len(set(row_h2.values())) == len(row_h2) == 2, sorted(row_h2.values()))
    cur.execute(
        "SELECT v13_mgraph_pair_digest(%s,%s), v13_mgraph_pair_digest(%s,%s)",
        (hTA, hTB, hE1, hE2))
    dig_h2 = cur.fetchone()
    check("H2: digest = pair_digest(early, late) by (source_at, content_hash)",
          row_h2[frozenset((hTA, hTB))] == dig_h2[0]
          and row_h2[frozenset((hE1, hE2))] == dig_h2[1],
          (row_h2, dig_h2))
    cur.execute(
        "WITH ord AS (SELECT content_hash, row_number() OVER"
        " (ORDER BY source_at ASC, content_hash ASC) AS rn FROM memory_nodes"
        " WHERE session_id=%s AND origin='episodic')"
        " SELECT a.content_hash, b.content_hash,"
        " v13_mgraph_pair_digest(a.content_hash, b.content_hash)"
        " FROM ord a JOIN ord b ON b.rn = a.rn + 1", (sid_h1,))
    v1_h2 = {frozenset((r[0], r[1])): r[2] for r in cur.fetchall()}
    check("H2: v1 adjacent enumeration finds 4 pairs, target pair NOT among"
          " them (selection genuinely widened)",
          len(v1_h2) == 4 and frozenset((hTA, hTB)) not in v1_h2
          and frozenset((hE1, hE2)) in v1_h2, sorted(map(str, v1_h2.items())))
    check("H2: v1-adjacent pair digest byte-identical (cache not invalidated)",
          v1_h2[frozenset((hE1, hE2))] == row_h2[frozenset((hE1, hE2))],
          (v1_h2[frozenset((hE1, hE2))], row_h2[frozenset((hE1, hE2))]))
    cur.execute(
        "INSERT INTO memory_consolidations (session_id, consolidation_key,"
        " status) VALUES (%s, %s, 'queued') ON CONFLICT DO NOTHING", (sid_h1, dig_h2[1]))
    cur.execute(
        "INSERT INTO memory_consolidations (session_id, consolidation_key,"
        " status) VALUES (%s, %s, 'queued') ON CONFLICT DO NOTHING", (sid_h1, dig_h2[1]))
    C.commit()
    cur.execute(
        "SELECT count(*) FROM memory_consolidations WHERE session_id=%s"
        " AND consolidation_key=%s", (sid_h1, dig_h2[1]))
    check("H2: queue PK keeps a single row per consolidation key (F6 face)",
          cur.fetchone()[0] == 1)

    # ---------------- H3 contradicts write side (canonical signal) -----
    HGA = "本次发布会到场人数约为三千二百人"
    HGB = "实际统计的到场人数只有九百人"
    sid_h3 = mk_session(cur, [HGA, HGB], same_txn=False)
    hGA, hGB = body_hash_of(cur, HGA), body_hash_of(cur, HGB)
    lo_h3, hi_h3 = sorted([hGA, hGB])
    sig_contra_h3 = f"mem_rel::{lo_h3}::{hi_h3}::contradicts"
    stepper(sid_h3, over={sig_contra_h3: 0.9,
                          f"mem_rel::{hGA}::{hGB}::semantic": 0.9})
    cur = C.cur
    contra_h3 = [e for e in links_of(cur, sid_h3, "jev")
                 if e[2] == "contradicts"]
    check("H3: over-threshold contradicts lands one jev edge in canonical"
          " (lo,hi) direction with an in-session decision",
          len(contra_h3) == 1 and contra_h3[0][0] == lo_h3
          and contra_h3[0][1] == hi_h3
          and contra_h3[0][4] not in ("None", None), contra_h3)
    check("H3: existing rel family unaffected (semantic edge still lands)",
          any(e[2] == "semantic" and (e[0], e[1]) == (hGA, hGB)
              for e in links_of(cur, sid_h3, "jev")))
    cur.execute(
        "SELECT count(*) FROM decisions WHERE session_id=%s AND signal=%s",
        (sid_h3, sig_contra_h3))
    check("H3: one canonical signal per unordered pair (A->B / B->A share"
          " a single signal set)", cur.fetchone()[0] == 1)
    cur.execute(
        "SELECT count(*) FROM memory_links WHERE session_id=%s"
        " AND rel='contradicts'", (sid_h3,))
    check("H3: contradicts edge not mirrored (exactly one edge)",
          cur.fetchone()[0] == 1)
    cur.execute("SELECT v13_mgraph_apply_relations(%s)", (sid_h3,))
    check("H3: apply re-entry inserts nothing (idempotent replay)",
          cur.fetchone()[0]["jev_edges"] == 0)
    C.commit()

    # ---------------- H4 semantic-bucket reachability ------------------
    cur.execute("SELECT v13_mgraph_bucket_rels('semantic')")
    rels_h4 = cur.fetchone()[0]
    check("H4: semantic bucket rel set already carries contradicts"
          " (zero-change read face)", "contradicts" in rels_h4, rels_h4)
    cur.execute("SELECT dst_hash, rel FROM v13_mgraph_neighbors(%s, %s, %s, NULL)",
                (sid_h3, lo_h3, rels_h4))
    nbrs_h4 = cur.fetchall()
    check("H4: one-hop traversal from the canonical src reaches the peer"
          " over contradicts",
          any(h == hi_h3 and rel == "contradicts" for h, rel in nbrs_h4),
          nbrs_h4)

    # ---------------- H5 dual-gate semantics ---------------------------
    res_h5, key_h5 = cons_step(sid_h3, over={"contradiction": 0.9,
                                             "choice": "merge", "prob": 0.9})
    cur = C.cur
    check("H5: strong contradiction blocks consolidation (eligible empty)",
          res_h5["eligible"] == [] and res_h5["asks"] == 1, res_h5)
    cur.execute("SELECT v13_mgraph_cons_gate(%s, %s)", (sid_h3, key_h5))
    gate_h5 = cur.fetchone()[0]
    check("H5: gate reason is contradiction (cons_gate zero change)",
          gate_h5["allowed"] is False and gate_h5["reason"] == "contradiction",
          gate_h5)
    cur.execute("SELECT v13_mgraph_consolidate_enqueue(%s)", (sid_h3,))
    check("H5: enqueue returns NULL (no merge/promote effect)",
          cur.fetchone()[0] is None)
    cur.execute(
        "SELECT count(*) FROM effects WHERE kind='mgraph_consolidate'"
        " AND session_id=%s", (sid_h3,))
    check("H5: zero consolidation effects", cur.fetchone()[0] == 0)
    cur.execute(
        "SELECT count(*) FROM memory_consolidations WHERE session_id=%s",
        (sid_h3,))
    check("H5: zero queue rows", cur.fetchone()[0] == 0)
    cur.execute(
        "SELECT count(*) FROM memory_links WHERE session_id=%s"
        " AND rel='contradicts' AND origin='jev'", (sid_h3,))
    check("H5: the jev contradicts edge persists — blocks the merge AND"
          " keeps the edge", cur.fetchone()[0] == 1)
    C.commit()

    # ---------------- H6 template/snapshot counts ----------------------
    cur.execute(
        "SELECT count(*) FROM judgment_templates WHERE template_name LIKE 'mem\\_%'")
    check("H6: 29 mem_* templates in DB", cur.fetchone()[0] == 29)
    contra_slot = slots["mem_rel_contradicts"]
    check("H6: contradicts slot is v13-local, combined per rule v1",
          contra_slot["source"].startswith("v13-local")
          and contra_slot["projection"] == ["left", "right"]
          and contra_slot["question"].startswith("Compare `new_memory.content`")
          and " TRUE if: " in contra_slot["question"]
          and " FALSE if: " in contra_slot["question"],
          contra_slot["source"])
    check("H6: cgr delta exactly 58 (29 content rows + 29 freeze, P2-4)",
          cgr_post - cgr_pre == 58, cgr_post - cgr_pre)

    # ---------------- H7 multi-tick resume under batches=8 -------------
    # write_max_batches=8 is the P0-4 caliber; the GUC mock answers exactly
    # one ask-batch shape per value (deviation #17 family), so the per-tick
    # throttle rides write_max_asks=1 — every call makes exactly one clean
    # ask (<= 8) and stops at a resume point; >1 real ask per call needs a
    # real-provider face (deviation ledger).
    open_write(write_max_batches=8, write_max_asks=1)
    p7 = ["Axel Bree Cole Drew unloaded the truck.",
          "Bree Cole Drew Axel unloaded the truck.",
          "Cole Drew Axel Bree unloaded the truck.",
          "Drew Axel Bree Cole unloaded the truck."]
    sid_h7 = mk_session(cur, p7)
    res_h7, waves_h7 = stepper(sid_h7)
    cur = C.cur
    check("H7: every build call asked <= 8 batches (batch cap in place)",
          all(r["asks"] <= 8 for r in res_h7), [r["asks"] for r in res_h7])
    check("H7: multiple build calls complete the build (cursor resume)",
          len(res_h7) > 1, len(res_h7))
    check("H7: per-tick truncation observable (asks/batches stop reasons)",
          any(r["stop_reason"] in ("asks", "batches") for r in res_h7[:-1]),
          [r["stop_reason"] for r in res_h7])
    check("H7: cumulative asks = 4 type + 12 pair envelopes = 16",
          sum(r["asks"] for r in res_h7) == 16, [r["asks"] for r in res_h7])
    check("H7: per-call signal increments non-empty and pairwise disjoint",
          all(len(w) > 0 for w in waves_h7)
          and len(set().union(*waves_h7)) == sum(len(w) for w in waves_h7),
          [len(w) for w in waves_h7])
    h7 = [body_hash_of(cur, b) for b in p7]
    cur.execute(
        "SELECT DISTINCT ON (content_hash) content_hash, seq_from"
        " FROM transcript_chunks WHERE session_id=%s"
        " ORDER BY content_hash, seq_from", (sid_h7,))
    fs_h7 = dict(cur.fetchall())
    cur.execute("SELECT v13_mgraph_progress(%s)", (sid_h7,))
    prog_h7 = cur.fetchone()[0]
    check("H7: final cursor=last node, watermark=its seq",
          prog_h7["rel_cursor"] == h7[3] and prog_h7["watermark"] == fs_h7[h7[3]],
          prog_h7)
    set_active("mgraph", 2)
    C.commit()

    # ---------------- H8 relation-envelope passthrough (rerun P0) -------
    # Rerun report docs/investigations/v13-dp9-mgraph-v2-demo-rerun-2026-09-24.md
    # §8 item 2: the RELATION envelope inside v13_mgraph_build was left on
    # the 3-arg GUC-reading face while the type envelope had already moved
    # to the 5-arg explicit passthrough. typesafe.provider is a placeholder
    # GUC purged when the typesafe library loads (the connection's first
    # judgment IO) and re-set is refused (reserved prefix), so the second
    # envelope of a real multi-envelope tick (wmb>=2) raised V3002. Gates
    # could not see it: single-batch discipline (wmb/wma=1) asks exactly
    # once per connection and the GUC-mock path never loads the library —
    # the path was structurally unreachable. Coverage: (a) structural —
    # every envelope call site in the LIVE function bodies (pg_proc defs,
    # G6 precedent) AND in the comment-stripped dollar-quoted bodies of
    # the source passes provider/model explicitly (exactly 5 top-level
    # args; the sanctioned GUC read lives only inside the constructor
    # itself); (b) functional — after a simulated purge the 3-arg face
    # fails closed V3002 while the 5-arg face still constructs on the
    # same connection (the fix).

    def envelope_call_argcs(fragment: str) -> list:
        """Top-level argument count of every v13_mgraph_envelope( CALL in
        fragment. CREATE ... FUNCTION headers are not calls (skipped);
        commas inside nested parens or ' literals do not count."""
        argcs = []
        i = 0
        needle = "v13_mgraph_envelope("
        while True:
            j = fragment.find(needle, i)
            if j < 0:
                return argcs
            if re.search(r"FUNCTION\s+(\w+\.)?\s*$", fragment[:j]):
                i = j + len(needle)   # definition header (schema-qualified too)
                continue
            depth = 0
            args = 1
            k = j + len(needle)
            while fragment[k] != ")" or depth > 0:
                ch = fragment[k]
                if ch == "'":                        # skip ' literals
                    k += 1
                    while fragment[k] != "'":
                        k += 1
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                elif ch == "," and depth == 0:
                    args += 1
                k += 1
            argcs.append(args)
            i = k + 1

    cur.execute(
        "SELECT proname, pg_get_functiondef(oid) FROM pg_proc"
        " WHERE prokind = 'f' AND position('v13_mgraph_envelope(' in"
        " pg_get_functiondef(oid)) > 0 ORDER BY oid")
    defs_h8 = cur.fetchall()
    names_h8 = {d[0] for d in defs_h8}
    check("H8: envelope callers present in live defs (build/run_round/"
          "consolidate/settle/delegate)",
          {"v13_mgraph_build", "v13_mgraph_run_round", "v13_mgraph_consolidate",
           "v13_mgraph_consolidate_settle", "v13_mgraph_envelope"} <= names_h8,
          sorted(names_h8))
    live_h8 = {f"{d[0]}#{n}": a for d in defs_h8
               for n, a in enumerate(envelope_call_argcs(d[1]), 1)}
    check("H8: every live envelope call passes 5 args (GUC-reading call"
          " face absent from all function bodies)",
          bool(live_h8) and all(a == 5 for a in live_h8.values()), live_h8)
    sql_h8 = SQL_FILE.read_text(encoding="utf-8")
    bodies_h8 = strip_sql_comments(sql_h8).split("$$")[1::2]
    src_h8 = {f"body#{b}#{n}": a for b, seg in enumerate(bodies_h8, 1)
              for n, a in enumerate(envelope_call_argcs(seg), 1)}
    check("H8: comment-stripped source: 6 envelope calls, all 5-arg",
          len(src_h8) == 6 and all(a == 5 for a in src_h8.values()), src_h8)

    # (b) functional: one connection, two envelopes, purge in between
    conn_h8, k8 = fresh_conn()
    sid_h8 = u()
    qs_h8 = [{"signal": f"mem_type::{sha('h8')}::episodic",
              "template_name": "mem_type_episodic"}]
    st_h8 = {"body": "Ivo greased the spare winch."}
    k8.execute("SELECT v13_mgraph_envelope(%s,%s::jsonb,%s::jsonb)",
               (sid_h8, json.dumps(st_h8), json.dumps(qs_h8)))
    env_h8a = k8.fetchone()[0]
    check("H8: 3-arg face constructs while the GUCs hold (first envelope)",
          env_h8a["provider"] == "mock" and env_h8a["model"] == "jev-mock",
          (env_h8a["provider"], env_h8a["model"]))
    # simulated purge: the real one is the typesafe library load (the mock
    # path never loads it); v13_guc_required fails closed on NULL and ''
    k8.execute("SELECT set_config('typesafe.provider', '', false)")
    k8.execute("SELECT set_config('typesafe.model', '', false)")
    fails_with(k8, "SELECT v13_mgraph_envelope(%s,%s::jsonb,%s::jsonb)",
               (sid_h8, json.dumps(st_h8), json.dumps(qs_h8)),
               "must be configured",
               "H8: 3-arg face raises V3002 once the GUC is gone (the"
               " wmb>=2 second-envelope crash mechanism)", pgcode="V3002")
    k8.execute("SELECT v13_mgraph_envelope(%s,%s::jsonb,%s::jsonb,%s,%s)",
               (sid_h8, json.dumps(st_h8), json.dumps(qs_h8),
                "mock", "jev-mock"))
    env_h8b = k8.fetchone()[0]
    check("H8: 5-arg face constructs on the same spent connection (fix)",
          env_h8b["provider"] == "mock" and env_h8b["model"] == "jev-mock"
          and env_h8b["candidate_set_hash"] == env_h8a["candidate_set_hash"],
          (env_h8b["provider"], env_h8b["model"]))
    conn_h8.rollback()
    conn_h8.close()

    # ---------------- M3 source discipline ---------------------------------
    sql_m3 = SQL_FILE.read_text(encoding="utf-8")
    norm_m3 = strip_sql_comments(sql_m3)
    check("M3: bind operator exactly 1 in comment-stripped source",
          norm_m3.count("==>") == 1, norm_m3.count("==>"))
    check("M3: whole-file scan still clean (A7 five tokens)",
          all(sql_m3.count(tok) == 0 for tok in (
              "typesafe_ask", "v13_append_event", "FOR UPDATE",
              "mock_response", "cypher(")))
    check("M3: no set_config in mgraph SQL", "set_config" not in sql_m3)

    # ---------------- M2 source discipline + policy restore ----------------
    sql_m2 = SQL_FILE.read_text(encoding="utf-8")
    norm_m2 = strip_sql_comments(sql_m2)
    check("M2: bind operator exactly 1 in comment-stripped source",
          norm_m2.count("==>") == 1, norm_m2.count("==>"))
    check("M2: whole-file scan still clean (A7 five tokens)",
          all(sql_m2.count(tok) == 0 for tok in (
              "typesafe_ask", "v13_append_event", "FOR UPDATE",
              "mock_response", "cypher(")))

    # ---------------- M4 source discipline + policy restore -------------
    sql_m4 = SQL_FILE.read_text(encoding="utf-8")
    norm_m4 = strip_sql_comments(sql_m4)
    check("M4: bind operator still exactly 1", norm_m4.count("==>") == 1,
          norm_m4.count("==>"))
    check("M4: whole-file scan still clean (A7 five tokens)",
          all(sql_m4.count(tok) == 0 for tok in (
              "typesafe_ask", "v13_append_event", "FOR UPDATE",
              "mock_response", "cypher(")))
    check("M4: no set_config in mgraph SQL", "set_config" not in sql_m4)
    set_active("mgraph", 2)
    cur.execute(
        "SELECT version, (value->>'write_enabled')::boolean,"
        " (value->>'read_enabled')::boolean FROM v13_policies"
        " WHERE name='mgraph' AND active")
    v_fin, w_fin, r_fin = cur.fetchone()
    check("M4: policy restored to v2 with write/read back off",
          v_fin == 2 and w_fin is False and r_fin is False, (v_fin, w_fin, r_fin))
    C.conn.rollback()
    C.conn.close()

    print("\n[mgraph M1+M2+M3+M4+v2-V1+V2] groups A+D+E+F+G+H: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
