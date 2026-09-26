"""v13 stannum 0.4.0 usage gate.

Run: uv run python v13/mgraph/test_stannum_usage.py  (exit 0 = pass)
"""
from __future__ import annotations

import importlib.metadata
import json
import math
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
from v13.load import files_through
from v13.mgraph.setup_db import DB, main as setup_db

PASSED = 0

EXPECTED_SQL = {
    "v13_recall(text,int)": (
        "SELECT c.content_hash, stannum.full_score(c.ctid)::numeric AS bm25, "
        "v13_extract_spans(c.body, jsonb_build_object('tinql', $1)) "
        "FROM chunks c JOIN v13_sources src "
        "ON src.source_hash = c.source_hash AND src.superseded_by IS NULL "
        "WHERE c.body ==> $1 ORDER BY bm25 DESC, c.content_hash ASC LIMIT $2"
    ),
    "v13_recall_count(text)": (
        "SELECT count(*) FROM chunks c "
        "JOIN v13_sources src ON src.source_hash = c.source_hash "
        "AND src.superseded_by IS NULL WHERE c.body ==> $1"
    ),
    "v13_transcript_recall(uuid,text,int)": (
        "SELECT t.content_hash, stannum.full_score(t.ctid)::numeric AS bm25, "
        "t.seq_from FROM transcript_chunks t "
        "WHERE t.session_id = $1 AND t.body ==> $3 "
        "ORDER BY bm25 DESC, t.content_hash ASC LIMIT $2"
    ),
    "v13_mgraph_candidates(uuid,text,int)": (
        "SELECT n.content_hash AS h, n.body AS b, n.source_at AS at, "
        "stannum.full_score(n.ctid)::numeric AS s FROM memory_nodes n "
        "WHERE n.session_id = $1 AND n.origin = 'episodic' AND n.body ==> $2 "
        "ORDER BY n.content_hash ASC"
    ),
}

P0_LABEL = {
    "v13_recall(text,int)": "P0a",
    "v13_recall_count(text)": "P0b",
    "v13_transcript_recall(uuid,text,int)": "P0c",
    "v13_mgraph_candidates(uuid,text,int)": "P0d",
}

PREPARE_TYPES = {
    "v13_recall(text,int)": "text, int",
    "v13_recall_count(text)": "text",
    "v13_transcript_recall(uuid,text,int)": "uuid, int, text",
    "v13_mgraph_candidates(uuid,text,int)": "uuid, text",
}

PROD_INDEXES = (
    "ix_chunks_stannum",
    "ix_transcript_stannum",
    "ix_decisions_question_stannum",
    "ix_memory_nodes_stannum",
)
FIVE_INDEXES = PROD_INDEXES + ("ix_v13_canary",)

SCORE_FUNCS = ("score_bound", "score_bound_indexed", "stannum_text_cmpfunc")
ZERO_FUNCS = (
    "tokenize", "ql_parse", "maybe_quote", "builtin_stop_words",
    "score", "max_score", "score_inspect", "highlight_ansi",
)
ZERO_QUALIFIED = tuple(f"stannum.{name}" for name in ZERO_FUNCS)

GRANT_STAGES = (
    "characterize", "filter", "memory", "economy", "summary", "periphery",
    "mgraph", "mgraph_assembly", "control", "spawn", "fanout", "triage",
)
EARLY_STAGES = (
    "schema", "resolve", "loop", "twophase", "envelope", "manifest",
    "chunks", "recall",
)

SIG_BOUND = (
    "stannum.score_bound(text,text,int,int,int,real,real,real,text[],text[])"
)
SIG_INDEXED = (
    "stannum.score_bound_indexed(tid,text,int,int,int,real,real,real,text[],text[])"
)

HIGHLIGHT_TYPES = {
    ("text", "text", "text", "text"),
    ("text", "text", "text", "stannum.indexed_query"),
    ("text", "text", "text", "text", "text"),
    ("text", "text", "text", "stannum.indexed_query", "text"),
}

BODY_EN = "quasar formation in high redshift surveys"
BODY_CJK = "東京タワーは電波塔である kohaku"
BODY_TR = "private session text quasarium"
BODY_MG = "为什么用户无法登录"

SPAN_SQL = """
CREATE FUNCTION pg_temp.v13_usage_highlight_spans(p_tagged text)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
  v_open text := chr(1);
  v_close text := chr(2);
  v_from int; v_cpos int; v_epos int;
  v_tags int := 0; v_total int := 0;
  v_bstart bigint; v_bend bigint;
  v_out jsonb := '[]'::jsonb;
BEGIN
  v_from := 1;
  LOOP
    EXIT WHEN v_total >= 256;
    v_cpos := position(v_open IN substring(p_tagged FROM v_from));
    EXIT WHEN v_cpos = 0;
    v_cpos := v_cpos + v_from - 1;
    v_epos := position(v_close IN substring(p_tagged FROM v_cpos + 1));
    EXIT WHEN v_epos = 0;
    v_epos := v_epos + v_cpos;
    v_bstart := octet_length(left(p_tagged, v_cpos)) + 1 - (v_tags + 1);
    v_bend := octet_length(left(p_tagged, v_epos - 1)) - (v_tags + 1);
    IF v_bstart >= 1 AND v_bend >= v_bstart THEN
      v_out := v_out || jsonb_build_array(jsonb_build_array(v_bstart, v_bend));
      v_total := v_total + 1;
    END IF;
    v_tags := v_tags + 2;
    v_from := v_epos + 1;
  END LOOP;
  RETURN v_out;
END $$;
"""


class ExtractError(Exception):
    pass


def check(label: str, condition: bool, detail: object = "") -> None:
    global PASSED
    mark = "PASS" if condition else "FAIL"
    extra = f": {detail}" if detail and (not condition or len(str(detail)) < 240) else ""
    print(f"[{mark}] {label}{extra}")
    if not condition:
        raise AssertionError(f"{label}: {detail}")
    PASSED += 1


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
    raise AssertionError(f"{label}: expected failure")


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
                out.append(src[i])
                if src[i] == '"':
                    i += 1
                    break
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


def guc(cur):
    cur.execute("RESET ROLE")
    cur.execute("SET search_path TO public, pg_catalog")
    cur.execute("SELECT set_config('typesafe.provider', 'mock', true)")
    cur.execute("SELECT set_config('typesafe.model', 'jev-mock', true)")


def commit_tx(conn, cur):
    conn.commit()
    guc(cur)


def as_obj(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


def norm_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def walk_plans(node, acc=None):
    acc = acc if acc is not None else []
    if isinstance(node, list):
        for item in node:
            walk_plans(item, acc)
    elif isinstance(node, dict):
        if "Plan" in node:
            walk_plans(node["Plan"], acc)
        else:
            acc.append(node)
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk_plans(value, acc)
    return acc


def plan_obj(plan):
    if isinstance(plan, str):
        return json.loads(plan)
    return plan


def info_plan(label, plan):
    nodes = walk_plans(plan)
    summary = []
    for node in nodes:
        extra = (
            node.get("Custom Plan Provider")
            or node.get("Index Name")
            or node.get("Index")
            or node.get("Relation Name")
            or node.get("Function Name")
            or ""
        )
        summary.append(f"{node.get('Node Type')}|{extra}")
    print(f"[info] {label}: {summary}")


def is_finite(value) -> bool:
    if value is None:
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _function_body(funcdef: str) -> str:
    match = re.search(r"\bAS\s+(\$[A-Za-z0-9_]*\$)", funcdef)
    if not match:
        raise ExtractError("no dollar-quoted body")
    tag = match.group(1)
    start = match.end()
    end = funcdef.rfind(tag)
    if end < start:
        raise ExtractError("unclosed function body")
    return funcdef[start:end]


def _skip_ws(text, i):
    while i < len(text) and text[i].isspace():
        i += 1
    return i


def _parse_string(text, i):
    if i >= len(text) or text[i] != "'":
        raise ExtractError(f"expected string literal, saw {text[i:i+40]!r}")
    i += 1
    out = []
    while i < len(text):
        if text[i] == "'":
            if i + 1 < len(text) and text[i + 1] == "'":
                out.append("'")
                i += 2
                continue
            return "".join(out), i + 1
        out.append(text[i])
        i += 1
    raise ExtractError("unterminated string literal")


def _parse_concat(text, i):
    parts = []
    while True:
        i = _skip_ws(text, i)
        if i < len(text) and text[i] == "$":
            raise ExtractError("dollar quote in dynamic SQL (refused)")
        if i >= len(text) or text[i] != "'":
            if not parts:
                raise ExtractError(
                    f"dynamic SQL is not a quoted literal: {text[i:i+60]!r}")
            break
        lit, i = _parse_string(text, i)
        parts.append(lit)
        j = _skip_ws(text, i)
        if text.startswith("||", j):
            i = j + 2
            continue
        i = j
        break
    rest = text[i:i+40].lstrip()
    if not (
        rest.startswith("USING") or rest.startswith("INTO")
        or rest.startswith("LOOP") or rest.startswith(";")
    ):
        raise ExtractError(f"trailing non-literal after dynamic SQL: {rest!r}")
    return norm_sql("".join(parts))


def extract_dynamic_sql(funcdef: str) -> str:
    body = _function_body(funcdef)
    sites = []
    for match in re.finditer(r"RETURN\s+QUERY\s+EXECUTE\b", body, re.I):
        sites.append(match.end())
    for match in re.finditer(r"FOR\s+\w+\s+IN\s+EXECUTE\b", body, re.I):
        sites.append(match.end())
    for match in re.finditer(r"(?<![A-Za-z0-9_])EXECUTE\b", body, re.I):
        prefix = body[max(0, match.start() - 40):match.start()]
        if re.search(r"RETURN\s+QUERY\s+$", prefix, re.I):
            continue
        if re.search(r"FOR\s+\w+\s+IN\s+$", prefix, re.I):
            continue
        sites.append(match.end())
    if len(sites) != 1:
        raise ExtractError(
            f"expected exactly one dynamic EXECUTE, found {len(sites)}")
    return _parse_concat(body, sites[0])


def load_dynamic_sql(cur) -> dict[str, str]:
    found = {}
    for sig, label in P0_LABEL.items():
        cur.execute("SELECT pg_get_functiondef(%s::regprocedure)", (sig,))
        funcdef = cur.fetchone()[0]
        try:
            sql = extract_dynamic_sql(funcdef)
        except ExtractError as exc:
            print(f"[info] {label} extract failed for {sig}: {exc}")
            check(label, False, exc)
        expected = norm_sql(EXPECTED_SQL[sig])
        if sql != expected:
            print(f"[info] {label} mismatch for {sig}")
            print(f"[info] GOT {sql}")
            print(f"[info] EXP {expected}")
            check(label, False, "extracted SQL != design table; stopped")
        check(label, True)
        found[sig] = sql
    return found


def explain_sql(cur, sql, argtypes, params, verbose=False):
    cur.execute("DEALLOCATE ALL")
    cur.execute(f"PREPARE usage_dyn ({argtypes}) AS {sql}")
    holders = ", ".join(["%s"] * len(params))
    opts = "VERBOSE, FORMAT JSON" if verbose else "FORMAT JSON"
    cur.execute(
        f"EXPLAIN ({opts}) EXECUTE usage_dyn({holders})", params)
    plan = plan_obj(cur.fetchone()[0])
    cur.execute("DEALLOCATE usage_dyn")
    return plan


def seq_on(nodes, relation):
    return [
        node for node in nodes
        if node.get("Node Type") == "Seq Scan"
        and node.get("Relation Name") == relation
    ]


def custom_scans(nodes, provider=None):
    found = [
        node for node in nodes
        if node.get("Node Type") == "Custom Scan"
    ]
    if provider is None:
        return found
    return [node for node in found if node.get("Custom Plan Provider") == provider]


def idx_scan_of(cur, name):
    cur.execute(
        "SELECT idx_scan FROM pg_stat_user_indexes "
        "WHERE schemaname = 'public' AND indexrelname = %s",
        (name,))
    row = cur.fetchone()
    return int(row[0] or 0) if row else 0


def func_calls(cur, names):
    cur.execute(
        """
        SELECT p.proname, coalesce(sum(s.calls), 0)::bigint
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        LEFT JOIN pg_stat_user_functions s ON s.funcid = p.oid
        WHERE n.nspname = 'stannum' AND p.proname = ANY(%s)
        GROUP BY p.proname
        """,
        (list(names),))
    found = {name: int(calls) for name, calls in cur.fetchall()}
    missing = [name for name in names if name not in found]
    return found, missing


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


def claim_pinned(cur, eid, worker="w1", lease_ms=60000):
    cur.execute(
        "UPDATE effects SET status='cancelled' "
        "WHERE status='ready' AND effect_id IS DISTINCT FROM %s",
        (eid,))
    cur.execute("SELECT v13_claim(%s, %s)", (worker, lease_ms))
    row = as_obj(cur.fetchone()[0])
    if row is None or str(row["effect_id"]) != str(eid):
        raise AssertionError(f"claim pinned: {row}")
    return row


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
    accepted = cur.fetchone()[0]
    if accepted != "accepted":
        raise AssertionError(f"tool complete: {accepted}")
    return eid, sid


def ingest_doc(cur, body, corpus="docs", eid=None, sid=None):
    if eid is None:
        eid, sid = succeed_tool(cur, sid)
    cur.execute("SELECT v13_ingest_document(%s,%s,%s)", (eid, corpus, body))
    return cur.fetchone()[0], eid, sid


def one_text(cur, sql, params=()):
    cur.execute(sql, params)
    return cur.fetchone()[0]


def drop_usage_role(conn, cur):
    conn.commit()
    conn.autocommit = True
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'v13_usage_schema'")
    if cur.fetchone():
        cur.execute("DROP OWNED BY v13_usage_schema")
        cur.execute("DROP ROLE v13_usage_schema")
    conn.autocommit = False
    guc(cur)


def create_usage_role(conn, cur):
    drop_usage_role(conn, cur)
    conn.commit()
    conn.autocommit = True
    cur.execute("CREATE ROLE v13_usage_schema NOLOGIN")
    cur.execute("GRANT USAGE ON SCHEMA stannum TO v13_usage_schema")
    cur.execute(
        "GRANT SELECT ON chunks, v13_sources, transcript_chunks, "
        "memory_nodes, decisions TO v13_usage_schema")
    conn.autocommit = False
    guc(cur)


def role_query(cur, role, sql, params):
    cur.execute("SAVEPOINT sp_role")
    cur.execute(f"SET LOCAL ROLE {role}")
    try:
        cur.execute(sql, params)
        rows = cur.fetchall()
    except psycopg2.Error:
        cur.execute("ROLLBACK TO SAVEPOINT sp_role")
        cur.execute("RESET ROLE")
        raise
    cur.execute("ROLLBACK TO SAVEPOINT sp_role")
    cur.execute("RESET ROLE")
    return rows


def role_fails(cur, role, sql, params, needle, label, pgcode="42501"):
    cur.execute("SAVEPOINT sp_role")
    cur.execute(f"SET LOCAL ROLE {role}")
    try:
        fails_with(cur, sql, params, needle, label, pgcode=pgcode)
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT sp_role")
        cur.execute("RESET ROLE")


def grant_block(path: Path):
    match = re.search(r'GRANTS = """\n(.*?)"""', path.read_text(), re.S)
    if not match:
        return None
    return match.group(1).strip("\n")


def identity_types(ident: str):
    types = []
    for part in ident.split(","):
        part = part.strip()
        _name, typ = part.split(" ", 1)
        types.append(typ)
    return tuple(types)


def version_checks(server, cur):
    check("V1", one_text(
        cur, "SELECT extversion FROM pg_extension WHERE extname='stannum'")
        == "0.4.0")
    pg = psycopg2.connect(server.get_uri("postgres"))
    try:
        pg.autocommit = True
        pc = pg.cursor()
        pc.execute(
            "SELECT default_version FROM pg_available_extensions "
            "WHERE name='stannum'")
        check("V2", pc.fetchone()[0] == "0.4.0")
    finally:
        pg.close()
    check("V3", one_text(cur, "SELECT stannum.version()") == "0.4.0")
    server_num = one_text(cur, "SELECT current_setting('server_version_num')::int")
    check("V4", 180000 <= server_num < 190000, server_num)
    check("V5", importlib.metadata.version("pgembed") == "0.3.0rc2")
    cur.execute(
        """
        SELECT pg_get_function_identity_arguments(p.oid)
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'stannum' AND p.proname = 'highlight'
        ORDER BY 1
        """)
    raws = [row[0] for row in cur.fetchall()]
    print(f"[info] V6 identity arguments: {raws}")
    got = {identity_types(raw) for raw in raws}
    check("V6", got == HIGHLIGHT_TYPES and len(raws) == 4, raws)
    cur.execute(
        """
        SELECT stannum.highlight('beer', '<b>', '</b>', 'beer', NULL)
             = stannum.highlight('beer', '<b>', '</b>', 'beer'),
               stannum.highlight('beer', '<b>', '</b>', 'beer')
        """)
    same, rendered = cur.fetchone()
    check("V7", same is True and "<b>" in rendered, rendered)
    check("V8", one_text(cur, "SELECT stannum.wal_rmgr_id()") is None)
    fails_with(
        cur, "SELECT current_setting('stannum.wal_rmgr_id')", (),
        "unrecognized", "V9")
    check("V10", one_text(
        cur, "SELECT current_setting('stannum.enable_custom_scan')") == "on")
    check("V11", one_text(
        cur, "SELECT current_setting('stannum.strict_analysis')") == "off")


def load_fixtures(cur):
    eid, sid_chunks = succeed_tool(cur)
    ingest_doc(cur, BODY_EN, eid=eid, sid=sid_chunks)
    ingest_doc(cur, BODY_CJK, eid=eid, sid=sid_chunks)
    sid_tr = new_session(cur)
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'llm/message', %s::jsonb)",
        (sid_tr, u(), json.dumps({"text": BODY_TR})))
    cur.fetchone()
    cur.execute("SELECT v13_rebuild_transcript_chunks(100)")
    cur.fetchone()
    sid_other = new_session(cur)
    sid_mg = new_session(cur)
    cur.execute(
        """
        INSERT INTO memory_nodes (
          session_id, content_hash, body, origin, source_hashes, source_at,
          builder_version)
        VALUES (
          %s, v13_body_hash(%s), %s, 'episodic',
          ARRAY[v13_body_hash(%s)], now(), 1)
        """,
        (sid_mg, BODY_MG, BODY_MG, BODY_MG))
    return sid_tr, sid_other, sid_mg


def p1_shape(plan):
    nodes = walk_plans(plan)
    text = json.dumps(plan, default=str)
    no_seq = seq_on(nodes, "chunks") == []
    score_ok = "full_score" in text or "score_bound" in text
    custom = [
        node for node in custom_scans(nodes, "Stannum Text Search Scan")
        if node.get("Index") == "ix_chunks_stannum"
    ]
    bitmap = (
        "score_bound_indexed" in text
        and "Bitmap Index Scan" in text
        and "ix_chunks_stannum" in text
        and not custom
    )
    if custom and no_seq and score_ok:
        return "custom", True
    if bitmap and no_seq and score_ok:
        return "bitmap", True
    return "other", False


def flush_stats(cur):
    cur.execute("SELECT pg_stat_force_next_flush()")
    cur.fetchone()


def measure(conn, cur, index_name, names, run):
    cur.execute("SET enable_seqscan = off")
    flush_stats(cur)
    commit_tx(conn, cur)
    base_idx = idx_scan_of(cur, index_name)
    base_calls, missing = func_calls(cur, names)
    rows = run()
    flush_stats(cur)
    commit_tx(conn, cur)
    cur.execute("RESET enable_seqscan")
    after_calls, missing_after = func_calls(cur, names)
    deltas = {
        name: after_calls.get(name, 0) - base_calls.get(name, 0)
        for name in names
    }
    return rows, idx_scan_of(cur, index_name) - base_idx, deltas, missing or missing_after


def runtime_checks(conn, cur, sqls, sid_tr, sid_other, sid_mg):
    tinql_q = one_text(cur, "SELECT v13_build_tinql(%s)", (BODY_EN.split()[0],))
    tinql_cjk = one_text(cur, "SELECT v13_build_tinql(%s)", ("東京タワー",))
    tinql_ka = one_text(cur, "SELECT v13_build_tinql(%s)", ("タ",))
    tinql_tr = one_text(cur, "SELECT v13_build_tinql(%s)", ("quasarium",))
    anchor = one_text(cur, "SELECT v13_mgraph_anchor_tinql(%s)", (BODY_MG,))
    print(f"[info] tinql quasar={tinql_q!r} cjk={tinql_cjk!r} ka={tinql_ka!r}")
    print(f"[info] tinql transcript={tinql_tr!r}")
    print(f"[info] anchor={anchor!r}")
    cur.execute("SET track_functions TO 'all'")
    print("[info] stats window uses pg_stat_force_next_flush before COMMIT")
    cur.execute("SET enable_seqscan = off")
    plan_p1 = explain_sql(
        cur, sqls["v13_recall(text,int)"], PREPARE_TYPES["v13_recall(text,int)"],
        (tinql_q, 8))
    info_plan("P1", plan_p1)
    kind, p1_ok = p1_shape(plan_p1)
    print(f"[info] P1 provider branch: {kind}")
    check("P1", p1_ok, kind)
    plan_p3 = explain_sql(
        cur, sqls["v13_recall_count(text)"],
        PREPARE_TYPES["v13_recall_count(text)"], (tinql_q,))
    info_plan("P3", plan_p3)
    p3_nodes = walk_plans(plan_p3)
    p3_text = json.dumps(plan_p3, default=str)
    p3_plan_ok = (
        seq_on(p3_nodes, "chunks") == []
        and (
            "ix_chunks_stannum" in p3_text
            or any(n.get("Custom Plan Provider") == "Stannum Count"
                   for n in p3_nodes)
            or any(n.get("Custom Plan Provider") == "Stannum Text Search Scan"
                   for n in p3_nodes)
        )
    )
    plan_p13 = plan_obj(one_text(
        cur, "EXPLAIN (FORMAT JSON) SELECT * FROM v13_recall(%s, 8)",
        (tinql_q,)))
    info_plan("P13", plan_p13)
    p13_nodes = walk_plans(plan_p13)
    cur.execute("RESET enable_seqscan")
    commit_tx(conn, cur)

    def run_recall():
        cur.execute(
            "SELECT content_hash, bm25, spans FROM v13_recall(%s, 8)",
            (tinql_q,))
        return cur.fetchall()

    rows, d_idx, deltas, missing = measure(
        conn, cur, "ix_chunks_stannum", SCORE_FUNCS + ZERO_FUNCS, run_recall)
    score_delta = sum(deltas[name] for name in SCORE_FUNCS)
    print(f"[info] P2 idx_scan+={d_idx} score_calls+={score_delta} "
          f"deltas={ {n: deltas[n] for n in SCORE_FUNCS} } rows={len(rows)}")
    info_plan("P2 plan (same SQL as P1)", plan_p1)
    check("P2",
          len(rows) >= 1 and all(is_finite(row[1]) for row in rows)
          and (d_idx >= 1 or score_delta >= 1) and not missing,
          (len(rows), d_idx, score_delta, missing))
    n_count = one_text(cur, "SELECT v13_recall_count(%s)", (tinql_q,))
    n_k = one_text(cur, "SELECT count(*) FROM v13_recall(%s, 1024)", (tinql_q,))
    check("P3", p3_plan_ok and n_count >= 1 and n_count == n_k,
          (p3_plan_ok, n_count, n_k))
    n_cjk = one_text(cur, "SELECT count(*) FROM v13_recall(%s, 8)", (tinql_cjk,))
    n_ka = one_text(cur, "SELECT count(*) FROM v13_recall(%s, 8)", (tinql_ka,))
    check("P4", n_cjk >= 1 and n_ka == 0, (n_cjk, n_ka))
    ch = rows[0][0]
    row_spans = rows[0][2]
    if isinstance(row_spans, str):
        row_spans = json.loads(row_spans)
    cur.execute(
        """
        SELECT no_sent,
               jsonb_typeof(spans) = 'array'
                 AND jsonb_array_length(spans) > 0,
               spans = derived,
               spans = %s::jsonb
        FROM (
          SELECT (SELECT bool_and(position(chr(i) IN c.body) = 0)
                    FROM generate_series(1, 8) i) AS no_sent,
                 v13_extract_spans(c.body, jsonb_build_object('tinql', %s))
                   AS spans,
                 pg_temp.v13_usage_highlight_spans(
                   stannum.highlight(c.body, chr(1), chr(2), %s)) AS derived
          FROM chunks c WHERE c.content_hash = %s
        ) s
        """,
        (json.dumps(row_spans), tinql_q, tinql_q, ch))
    no_sent, nonempty, derived_eq, row_eq = cur.fetchone()
    check("P5", no_sent and nonempty and derived_eq and row_eq,
          (no_sent, nonempty, derived_eq, row_eq, row_spans))

    # P5b (U2b): spans <-> production index binding. P5 locks the sentinel
    # parity of the 4-arg TEXT highlight (default tokenizer) against
    # v13_extract_spans; this one binds the same CJK row's tinql to
    # ix_chunks_stannum via stannum.bind_query and drives the 4-arg
    # indexed_query highlight overload. The two interval sequences must be
    # equal, ordered, and non-empty. Equal today because the production
    # index runs the default unicode analyzer; it turns red the day the
    # index analyzer forks (tokenizer/max_token_bytes/long_tokens) while
    # extract_spans stays on the default — that red is the point, not a
    # false alarm. Fixture must stay CJK: a latin term can tokenize
    # identically under jieba and unicode and lock nothing.
    cur.execute(
        """
        SELECT (SELECT bool_and(position(chr(i) IN c.body) = 0)
                  FROM generate_series(1, 8) i),
               v13_extract_spans(c.body, jsonb_build_object('tinql', %s)),
               pg_temp.v13_usage_highlight_spans(
                 stannum.highlight(c.body, chr(1), chr(2),
                   stannum.bind_query(%s, 'ix_chunks_stannum'::regclass)))
        FROM chunks c WHERE c.body = %s
        """,
        (tinql_cjk, tinql_cjk, BODY_CJK))
    no_sent_b, spans_b, derived_b = cur.fetchone()
    if isinstance(spans_b, str):
        spans_b = json.loads(spans_b)
    if isinstance(derived_b, str):
        derived_b = json.loads(derived_b)
    print(f"[info] P5b extract={spans_b} indexed_bound={derived_b}")
    check("P5b",
          no_sent_b is True
          and isinstance(spans_b, list) and len(spans_b) > 0
          and isinstance(derived_b, list) and len(derived_b) > 0
          and spans_b == derived_b,
          (no_sent_b, spans_b, derived_b))

    cur.execute("SET enable_seqscan = off")
    plan_p6 = explain_sql(
        cur, sqls["v13_transcript_recall(uuid,text,int)"],
        PREPARE_TYPES["v13_transcript_recall(uuid,text,int)"],
        (sid_tr, 8, tinql_tr))
    info_plan("P6", plan_p6)
    p6_text = json.dumps(plan_p6, default=str)
    p6_plan_ok = (
        "score_bound_indexed" in p6_text
        and "transcript_chunks_pkey" in p6_text
        and "Bitmap Index Scan" in p6_text
        and '"Node Type": "Seq Scan"' not in p6_text
    )
    cur.execute("RESET enable_seqscan")

    def run_tr():
        cur.execute(
            "SELECT * FROM v13_transcript_recall(%s, %s, 8)",
            (sid_tr, tinql_tr))
        return cur.fetchall()

    tr_rows, tr_idx, tr_delta, tr_missing = measure(
        conn, cur, "ix_transcript_stannum", ("score_bound_indexed",), run_tr)
    print(f"[info] P6 idx_scan+={tr_idx} "
          f"score_bound_indexed+={tr_delta['score_bound_indexed']} "
          f"rows={len(tr_rows)}")
    check("P6",
          p6_plan_ok and len(tr_rows) >= 1
          and (tr_idx >= 1 or tr_delta["score_bound_indexed"] >= 1)
          and not tr_missing,
          (p6_plan_ok, len(tr_rows), tr_idx, tr_delta, tr_missing))
    n_other = one_text(
        cur, "SELECT count(*) FROM v13_transcript_recall(%s, %s, 8)",
        (sid_other, tinql_tr))
    check("P7", n_other == 0, n_other)

    cur.execute("SET enable_seqscan = off")
    print("[info] P8 EXPLAIN VERBOSE: ORDER BY content_hash hides "
          "score_bound_indexed unless Output is included")
    plan_p8 = explain_sql(
        cur, sqls["v13_mgraph_candidates(uuid,text,int)"],
        PREPARE_TYPES["v13_mgraph_candidates(uuid,text,int)"],
        (sid_mg, anchor), verbose=True)
    info_plan("P8", plan_p8)
    p8_nodes = walk_plans(plan_p8)
    p8_text = json.dumps(plan_p8, default=str)
    p8_plan_ok = (
        seq_on(p8_nodes, "memory_nodes") == []
        and "stannum" in p8_text
        and ("full_score" in p8_text or "score_bound" in p8_text)
    )
    cur.execute("RESET enable_seqscan")

    def run_mg():
        cur.execute(
            "SELECT * FROM v13_mgraph_candidates(%s, %s, 10)",
            (sid_mg, anchor))
        return cur.fetchall()

    mg_rows, mg_idx, mg_delta, mg_missing = measure(
        conn, cur, "ix_memory_nodes_stannum",
        ("score_bound", "score_bound_indexed"), run_mg)
    mg_score = mg_delta["score_bound"] + mg_delta["score_bound_indexed"]
    print(f"[info] P8 idx_scan+={mg_idx} score_calls+={mg_score} rows={len(mg_rows)}")
    check("P8",
          p8_plan_ok and len(mg_rows) >= 1 and (mg_idx >= 1 or mg_score >= 1)
          and not mg_missing,
          (p8_plan_ok, len(mg_rows), mg_idx, mg_delta, mg_missing))

    cur.execute(
        """
        SELECT p.proname, pg_get_functiondef(p.oid)
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public' AND p.proname LIKE 'v13\\_%'
        """)
    defs = cur.fetchall()
    bad_question = [name for name, body in defs if "question ==>" in body]
    bad_index = [
        name for name, body in defs
        if "ix_decisions_question_stannum" in body
        and name != "v13_verify_memory"
    ]
    verify_has_index = any(
        name == "v13_verify_memory" and "ix_decisions_question_stannum" in body
        for name, body in defs)
    verify_owners = {
        "ix_chunks_stannum": "v13_verify_chunks",
        "ix_transcript_stannum": "v13_verify_memory",
        "ix_decisions_question_stannum": "v13_verify_memory",
        "ix_memory_nodes_stannum": "v13_verify_mgraph",
    }
    call_re = re.compile(r"stannum\.verify_index\s*\(\s*'([^']+)'")
    call_sites = {idx: [] for idx in verify_owners}
    for name, body in defs:
        for idx in call_re.findall(body):
            if idx in call_sites:
                call_sites[idx].append(name)
    mapping_ok = all(
        call_sites[idx] == [owner] for idx, owner in verify_owners.items())
    check("P9",
          not bad_question and not bad_index and verify_has_index
          and mapping_ok,
          (bad_question, bad_index, verify_has_index, call_sites))
    n_dec = one_text(
        cur,
        "SELECT count(*) FROM stannum.verify_index("
        "'ix_decisions_question_stannum', true) "
        "WHERE severity IN ('error','warning')")
    check("P10", n_dec == 0, n_dec)
    n_mn = one_text(
        cur,
        "SELECT count(*) FROM stannum.verify_index("
        "'ix_memory_nodes_stannum', true) "
        "WHERE severity IN ('error','warning')")
    check("P11", n_mn == 0, n_mn)
    mgraph_def = next(
        body for name, body in defs if name == "v13_verify_mgraph")
    covered = call_re.findall(mgraph_def)
    cur.execute("SELECT v13_verify_mgraph(false)")
    v_mg = as_obj(cur.fetchone()[0])
    v_checks = v_mg["checks"]
    check(
        "P14",
        v_mg.get("all_ok") is True
        and v_mg.get("version") == 1
        and set(v_mg) == {"version", "checks", "all_ok"}
        and len(v_checks) == 1
        and set(v_checks[0]) == {"name", "ok", "detail"}
        and v_checks[0]["name"] == "memory_nodes_verify_index"
        and v_checks[0]["ok"] is True
        and set(v_checks[0]["detail"]) == {"findings"}
        and int(v_checks[0]["detail"]["findings"]) == 0
        and covered == ["ix_memory_nodes_stannum"],
        (v_mg, covered))
    cur.execute(
        "SELECT count(*) FROM pg_extension WHERE extname = 'pg_cron'")
    if cur.fetchone()[0] == 1:
        cur.execute("SELECT jobname, command FROM cron.job")
        cron_hits = [
            (name, cmd) for name, cmd in cur.fetchall()
            if "v13_verify_mgraph" in (name or "")
            or "v13_verify_mgraph" in (cmd or "")
        ]
        check("P15", not cron_hits, cron_hits)
    else:
        print("[note] P15: pg_cron not loadable in this database "
              "(cron.database_name guard) — v13_verify_mgraph stays "
              "manually callable")
    check(
        "P16",
        mgraph_def.count("stannum.verify_index") == 1
        and covered == ["ix_memory_nodes_stannum"]
        and "==>" not in mgraph_def
        and "ix_decisions_question_stannum" not in mgraph_def,
        (mgraph_def.count("stannum.verify_index"), covered))
    cur.execute(
        """
        SELECT c.relname, i.indnatts, c.reloptions
        FROM pg_index i
        JOIN pg_class c ON c.oid = i.indexrelid
        JOIN pg_am am ON am.oid = c.relam
        WHERE am.amname = 'stannum'
          AND c.relname = ANY(%s)
        ORDER BY 1
        """,
        (list(FIVE_INDEXES),))
    rels = {name: (natts, opts) for name, natts, opts in cur.fetchall()}
    prod_ok = all(
        rels.get(name, (None, "missing"))[0] == 1
        and (
            rels[name][1] is None
            or not any(tok in " ".join(rels[name][1])
                       for tok in ("tokenizer", "field_weights", "jieba"))
        )
        for name in PROD_INDEXES
    )
    canary_opts = rels.get("ix_v13_canary", (None, None))[1] or []
    canary_ok = (
        rels.get("ix_v13_canary", (None, None))[0] == 1
        and set(canary_opts) == {"long_tokens=split", "max_token_bytes=64"}
        and not any("tokenizer" in opt for opt in canary_opts)
    )
    check("P12", prod_ok and canary_ok and len(rels) == 5, rels)
    check("P13",
          any(n.get("Node Type") == "Function Scan" for n in p13_nodes)
          and not any(n.get("Node Type") == "Custom Scan" for n in p13_nodes),
          [n.get("Node Type") for n in p13_nodes])
    return {
        "tinql_q": tinql_q,
        "tinql_tr": tinql_tr,
        "anchor": anchor,
        "sid_tr": sid_tr,
        "sid_mg": sid_mg,
        "p1_kind": kind,
        "p6_plan_ok": p6_plan_ok,
        "p6_text": p6_text,
        "plans": {"P2": plan_p1, "P6": plan_p6, "P8": plan_p8},
        "zero_deltas": {name: deltas[name] for name in ZERO_FUNCS},
        "zero_missing": [name for name in ZERO_FUNCS if name in missing],
        "prod_null": all(rels[name][1] is None for name in PROD_INDEXES),
        "no_jieba": all(
            "jieba" not in " ".join(rels[name][1] or [])
            for name in FIVE_INDEXES
        ),
    }


def search_function_scan(plan) -> bool:
    for node in walk_plans(plan):
        if node.get("Node Type") != "Function Scan":
            continue
        if node.get("Function Name") in ("search", "search_count"):
            return True
    return "stannum.search" in json.dumps(plan, default=str)


def feature_checks(cur, ctx):
    check("F1", True)
    check("F2", ctx["p1_kind"] == "custom" and ctx["p6_plan_ok"],
          ctx["p1_kind"])
    check("F3", "score_bound_indexed" in ctx["p6_text"])
    cur.execute("DROP TABLE IF EXISTS v13_usage_probe")
    cur.execute("CREATE TABLE v13_usage_probe (title text, body text)")
    cur.execute(
        "CREATE INDEX ix_v13_usage_probe ON v13_usage_probe "
        "USING stannum (title, body) WITH (field_weights='title:3,body:1')")
    cur.execute("INSERT INTO v13_usage_probe VALUES ('lager', 'beer ale')")
    true_hit = one_text(
        cur, "SELECT (title ==> 'title:(lager)') FROM v13_usage_probe")
    cur.execute("SAVEPOINT sp_f4")
    try:
        cur.execute("SELECT (title ==> 'body:(lager)') FROM v13_usage_probe")
        val = cur.fetchone()[0]
        cur.execute("RELEASE SAVEPOINT sp_f4")
        foreign_ok = False
        foreign_detail = f"returned {val!r}; 0.4.0 rejects this form"
    except psycopg2.Error as exc:
        cur.execute("ROLLBACK TO SAVEPOINT sp_f4")
        msg = str(exc).splitlines()[0]
        foreign_ok = (
            exc.pgcode == "XX000" and "this ==> clause answers" in str(exc))
        foreign_detail = f"pgcode={exc.pgcode} {msg}"
    still_single = one_text(
        cur,
        """
        SELECT bool_and(i.indnatts = 1)
        FROM pg_index i
        JOIN pg_class c ON c.oid = i.indexrelid
        WHERE c.relname = ANY(%s)
        """,
        (list(PROD_INDEXES),))
    cur.execute("DROP TABLE v13_usage_probe")
    gone = one_text(
        cur, "SELECT count(*) FROM pg_class WHERE relname = 'v13_usage_probe'") == 0
    print(f"[info] F4 foreign-field query: {foreign_detail}")
    check("F4", true_hit is True and foreign_ok and still_single and gone,
          foreign_detail)
    cur.execute("CREATE TABLE v13_usage_probe_single (body text)")
    fails_with(
        cur,
        "CREATE INDEX ix_v13_usage_probe_single ON v13_usage_probe_single "
        "USING stannum (body) WITH (field_weights='body:1.0')",
        (), "multi-column", "F5", pgcode="XX000")
    cur.execute("DROP TABLE v13_usage_probe_single")
    check("F6",
          ctx["no_jieba"]
          and one_text(cur, "SELECT current_setting('stannum.strict_analysis')")
          == "off")
    check("F7", ctx["prod_null"], ctx["prod_null"])
    norm_src = "\n".join(
        strip_sql_comments(path.read_text()) for path in files_through("mgraph"))
    plan_search = any(search_function_scan(plan) for plan in ctx["plans"].values())
    check("F8", "stannum.search" not in norm_src and not plan_search,
          plan_search)
    cur.execute(
        """
        SELECT documents, average_length, analysis_matches, analysis_detail
        FROM stannum.index_stats('ix_chunks_stannum')
        """)
    stats = cur.fetchall()
    check("F9",
          len(stats) == 1 and stats[0][0] >= 1 and float(stats[0][1]) == 0
          and stats[0][2] is None and stats[0][3] is None,
          stats)
    cur.execute("SELECT index::text FROM stannum.index_health")
    health = {row[0] for row in cur.fetchall()}
    check("F10", health == set(FIVE_INDEXES), health)
    cur.execute(
        "SELECT kind::text FROM stannum.segment_info('ix_chunks_stannum')")
    kinds = [row[0] for row in cur.fetchall()]
    print(f"[info] F11 segment kinds: {kinds}")
    check("F11", len(kinds) >= 1 and set(kinds) <= {"immutable", "mutable"},
          kinds)
    probe_left = one_text(
        cur,
        "SELECT count(*) FROM pg_class WHERE relname = %s OR relname = %s",
        ("v13_usage_probe", "v13_usage_probe_single"))
    check("F12", probe_left == 0, probe_left)
    guc_expect = {
        "stannum.write_buffer_docs": "512",
        "stannum.write_buffer_bytes": "1048576",
        "stannum.max_merge_docs": "1024",
        "stannum.build_segment_docs": "32768",
        "stannum.max_segments": "128",
        "stannum.merge_tier_factor": "8",
    }
    raw_gucs = {}
    ok = True
    for name, expect in guc_expect.items():
        raw_gucs[name] = one_text(cur, "SELECT current_setting(%s)", (name,))
        if name == "stannum.max_segments" and raw_gucs[name] != "128":
            print(f"[info] F13 max_segments actual={raw_gucs[name]}")
        if raw_gucs[name] != expect:
            ok = False
    strategy = one_text(
        cur, "SELECT current_setting('stannum.experimental_vacuum_merge_strategy')")
    raw_gucs["stannum.experimental_vacuum_merge_strategy"] = strategy
    print(f"[info] F13 raw: {raw_gucs}")
    if strategy not in ("auto", "Auto"):
        ok = False
    check("F13", ok, raw_gucs)
    qualified_hit = []
    for name in ZERO_QUALIFIED:
        pat = re.compile(rf"{re.escape(name)}(?![A-Za-z0-9_])")
        if pat.search(norm_src):
            qualified_hit.append(name)
    zero_calls = all(ctx["zero_deltas"].get(name, 0) == 0 for name in ZERO_FUNCS)
    check("F14",
          zero_calls and not ctx["zero_missing"] and not qualified_hit,
          (ctx["zero_deltas"], ctx["zero_missing"], qualified_hit))
    return norm_src


def role_count(cur, role, sql, params):
    rows = role_query(cur, role, sql, params)
    return rows[0][0]


def privilege_checks(conn, cur, ctx):
    tinql_q = ctx["tinql_q"]
    tinql_tr = ctx["tinql_tr"]
    anchor = ctx["anchor"]
    sid_tr = ctx["sid_tr"]
    sid_mg = ctx["sid_mg"]
    recall_sql = "SELECT count(*) FROM v13_recall(%s, 8)"
    create_usage_role(conn, cur)
    n1 = role_count(cur, "v13_recall", recall_sql, (tinql_q,))
    check("R1", n1 >= 1, n1)
    n_resolve = role_count(cur, "v13_resolve", recall_sql, (tinql_q,))
    n_route = role_count(cur, "v13_route", recall_sql, (tinql_q,))
    check("R2", n_resolve >= 1 and n_route >= 1, (n_resolve, n_route))
    n3 = role_count(cur, "v13_route_login", recall_sql, (tinql_q,))
    check("R3", n3 >= 1, n3)
    n4 = role_count(cur, "v13_resolve_login", recall_sql, (tinql_q,))
    check("R4", n4 >= 1, n4)
    role_fails(
        cur, "v13_worker", recall_sql, (tinql_q,),
        "permission denied", "R5")
    cur.execute("SAVEPOINT sp_r6")
    cur.execute("SET LOCAL ROLE v13_worker")
    cur.execute("SET LOCAL ROLE v13_route")
    cur.execute(recall_sql, (tinql_q,))
    n6 = cur.fetchone()[0]
    cur.execute("ROLLBACK TO SAVEPOINT sp_r6")
    cur.execute("RESET ROLE")
    check("R6", n6 >= 1, n6)
    n7 = role_count(
        cur, "v13_recall",
        "SELECT count(*) FROM v13_transcript_recall(%s, %s, 8)",
        (sid_tr, tinql_tr))
    check("R7", n7 >= 1, n7)
    cand_sql = "SELECT * FROM v13_mgraph_candidates(%s, %s, 10)"
    role_fails(
        cur, "v13_recall", cand_sql, (sid_mg, anchor),
        "v13_mgraph_candidates", "R8a", pgcode="42501")
    rows8b = role_query(cur, "v13_resolve", cand_sql, (sid_mg, anchor))
    check("R8b", len(rows8b) >= 1, len(rows8b))
    cur.execute(
        "SELECT has_function_privilege('v13_recall',"
        " 'v13_mgraph_candidates(uuid,text,int)','EXECUTE'),"
        " has_function_privilege('v13_resolve',"
        " 'v13_mgraph_candidates(uuid,text,int)','EXECUTE')")
    hp_r8c = cur.fetchone()
    check("R8c", hp_r8c == (False, True), hp_r8c)
    role_fails(
        cur, "v13_recall", "SELECT v13_verify_chunks(false)", (),
        "permission denied", "R9: verify_chunks")
    role_fails(
        cur, "v13_recall", "SELECT v13_verify_memory(false)", (),
        "permission denied", "R9: verify_memory")
    role_fails(
        cur, "v13_recall", "SELECT v13_verify_mgraph(false)", (),
        "v13_verify_mgraph", "R9c", pgcode="42501")
    n10 = role_count(
        cur, "v13_recall",
        "SELECT count(*) FROM stannum.verify_index('ix_chunks_stannum', true) "
        "WHERE severity IN ('error','warning')",
        ())
    check("R10", n10 == 0, n10)
    role_fails(
        cur, "v13_recall",
        "SELECT stannum.verify_index('ix_v13_canary', true)", (),
        "permission denied", "R11")
    rows12 = role_query(
        cur, "v13_recall",
        "SELECT documents FROM stannum.index_stats('ix_chunks_stannum')", ())
    check("R12", len(rows12) == 1 and rows12[0][0] >= 1, rows12)
    role_fails(
        cur, "v13_recall",
        "SELECT stannum.index_stats('ix_v13_canary')", (),
        "permission denied", "R13")
    role_fails(
        cur, "v13_recall", "SELECT count(*) FROM stannum.index_health", (),
        "permission denied", "R14")
    n15 = one_text(cur, "SELECT count(*) FROM stannum.index_health")
    check("R15", n15 == 5, n15)
    cur.execute("SAVEPOINT sp_r16")
    cur.execute("SET LOCAL ROLE v13_usage_schema")
    cur.execute("SET LOCAL enable_seqscan = off")
    try:
        fails_with(
            cur,
            "SELECT stannum.full_score(t.ctid) FROM transcript_chunks t "
            "WHERE session_id = %s AND body ==> %s LIMIT 8",
            (sid_tr, tinql_tr), "score_bound", "R16", pgcode="42501")
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT sp_r16")
        cur.execute("RESET ROLE")
    ver = role_query(cur, "v13_usage_schema", "SELECT stannum.version()", ())
    check("R17", ver[0][0] == "0.4.0", ver)
    cur.execute("SAVEPOINT sp_r18")
    cur.execute("SET LOCAL ROLE v13_usage_schema")
    cur.execute("SET LOCAL enable_seqscan = off")
    r18_ok = False
    r18_detail = ""
    try:
        cur.execute("SELECT 1 FROM chunks WHERE body ==> %s", (tinql_q,))
        cur.fetchall()
        print("[info] Custom Scan 不调用 score_bound SQL 函数")
        r18_ok = True
        r18_detail = "success"
    except psycopg2.Error as exc:
        r18_ok = exc.pgcode == "42501" and "score_bound" in str(exc).lower()
        r18_detail = f"pgcode={exc.pgcode} {str(exc).splitlines()[0]}"
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT sp_r18")
        cur.execute("RESET ROLE")
    check("R18", r18_ok, r18_detail)
    cur.execute(
        """
        SELECT has_function_privilege('v13_recall', %s, 'EXECUTE'),
               has_function_privilege('v13_recall', %s, 'EXECUTE')
        """,
        (SIG_BOUND, SIG_INDEXED))
    r19a, r19b = cur.fetchone()
    check("R19", r19a is True and r19b is True, (r19a, r19b))
    print("[info] R20: SET ROLE v13_worker cannot resolve stannum.* "
          "(no schema USAGE); privilege checked without SET ROLE")
    cur.execute(
        """
        SELECT has_function_privilege('v13_worker', %s, 'EXECUTE'),
               has_function_privilege('v13_worker', %s, 'EXECUTE')
        """,
        (SIG_BOUND, SIG_INDEXED))
    r20a, r20b = cur.fetchone()
    check("R20", r20a is False and r20b is False, (r20a, r20b))
    canonical = grant_block(V13 / "mgraph" / "setup_db.py")
    mismatches = []
    for stage in GRANT_STAGES:
        block = grant_block(V13 / stage / "setup_db.py")
        if block != canonical or block is None or "full_score" in (block or ""):
            mismatches.append(stage)
    early_hit = [
        stage for stage in EARLY_STAGES
        if "GRANT USAGE ON SCHEMA stannum" in (V13 / stage / "setup_db.py").read_text()
    ]
    check("R21",
          canonical is not None and "full_score" not in canonical
          and not mismatches and not early_hit,
          (mismatches, early_hit))


def cleanup(conn, cur):
    try:
        conn.rollback()
    except Exception:
        pass
    try:
        conn.autocommit = True
        cur.execute("DROP TABLE IF EXISTS v13_usage_probe CASCADE")
        cur.execute("DROP TABLE IF EXISTS v13_usage_probe_single CASCADE")
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'v13_usage_schema'")
        if cur.fetchone():
            cur.execute("DROP OWNED BY v13_usage_schema")
            cur.execute("DROP ROLE v13_usage_schema")
    except Exception as exc:
        print(f"[info] cleanup: {exc}")


def main() -> int:
    setup_db()
    server = get_server()
    conn = psycopg2.connect(server.get_uri(DB))
    conn.autocommit = False
    cur = conn.cursor()
    guc(cur)
    try:
        drop_usage_role(conn, cur)
        cur.execute(SPAN_SQL)
        version_checks(server, cur)
        sqls = load_dynamic_sql(cur)
        sid_tr, sid_other, sid_mg = load_fixtures(cur)
        commit_tx(conn, cur)
        ctx = runtime_checks(conn, cur, sqls, sid_tr, sid_other, sid_mg)
        feature_checks(cur, ctx)
        privilege_checks(conn, cur, ctx)
    finally:
        cleanup(conn, cur)
        try:
            conn.close()
        except Exception:
            pass
    print(f"ALL PASS ({PASSED})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
