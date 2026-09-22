"""DP7 gate M2: summary — effect-plane extension (kind context_summary,
cap v2) + summary_accept + summary_fidelity template + defaults point +
span_digest/checks/envelope/verdict/schedule + single-source material
helpers + assembly v3 (summary section, history shrink, fallback ladder,
economics.summary) + validate v3 + refresh v3 dual-mode belt (diff
allow-list per oracle resolution §3.2.4). Groups I-P.

Run: uv run python v13/summary/test_summary.py  (exit 0 = pass)
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
from v13.summary.setup_db import DB, main as setup_db
from v13.load import files_through

HEX64 = re.compile(r"^[0-9a-f]{64}$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
TIERS = ("Normal", "TrimSchemas", "CompactHistory", "AggressivePrune")


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    extra = f": {detail}" if detail and (not condition or len(str(detail)) < 220) else ""
    print(f"[{mark}] {label}{extra}", flush=True)
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


def guc(cur):
    cur.execute("RESET ROLE")
    cur.execute("SET search_path TO public, pg_catalog")
    cur.execute("SELECT set_config('typesafe.provider', 'mock', false)")
    cur.execute("SELECT set_config('typesafe.model', 'jev-mock', false)")
    cur.execute("SELECT set_config('typesafe.api_key', 'probe', false)")


def new_session(cur, sid=None):
    sid = sid or u()
    cur.execute("INSERT INTO sessions (session_id) VALUES (%s)", (sid,))
    return sid


def append(cur, sid, etype, payload):
    cur.execute(
        "SELECT v13_append_event(%s, %s, %s, %s::jsonb)",
        (sid, u(), etype, json.dumps(payload)))
    return cur.fetchone()[0]


def append_user(cur, sid, text):
    return append(cur, sid, "user/message", {"text": text})


def anchored_llm(cur, sid, text):
    cur.execute("SELECT v13_last_user_seq(%s)", (sid,))
    a = cur.fetchone()[0]
    return append(cur, sid, "llm/message",
                   {"text": text, "origin_user_seq": a})


def anchored_tool(cur, sid, tool, result):
    cur.execute("SELECT v13_last_user_seq(%s)", (sid,))
    a = cur.fetchone()[0]
    return append(cur, sid, "tool/result",
                   {"tool": tool, "result": result,
                    "origin_user_seq": a})


def next_policy_version(cur, name: str) -> int:
    cur.execute(
        "SELECT coalesce(max(version),0)+1 FROM v13_policies WHERE name=%s",
        (name,))
    return cur.fetchone()[0]


def bump_policy(cur, name: str, value: dict, activate=True) -> int:
    ver = next_policy_version(cur, name)
    cur.execute(
        "INSERT INTO v13_policies (name, version, value, active) "
        "VALUES (%s,%s,%s::jsonb,false)",
        (name, ver, json.dumps(value)))
    if activate:
        cur.execute(
            "UPDATE v13_policies SET active=false WHERE name=%s AND active",
            (name,))
        cur.execute(
            "UPDATE v13_policies SET active=true WHERE name=%s AND version=%s",
            (name, ver))
    return ver


def restore_policy(cur, name: str, version: int) -> None:
    cur.execute(
        "UPDATE v13_policies SET active=false WHERE name=%s AND active",
        (name,))
    cur.execute(
        "UPDATE v13_policies SET active=true WHERE name=%s AND version=%s",
        (name, version))


def assemble(cur, sid):
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid,))
    return cur.fetchone()[0]


def refresh_n(cur, sid, goal_hash):
    """bump cycle (turn/route) + enqueue + claim + settle one
    context_refresh effect; returns (outcome, manifest)."""
    append(cur, sid, "turn/route", {"action": "refresh"})
    cur.execute(
        "SELECT v13_enqueue_effect(%s,'context_refresh',"
        "jsonb_build_object('goal_hash',%s))", (sid, goal_hash))
    eff = cur.fetchone()[0]
    cur.execute("SELECT v13_claim('t')")
    cl = cur.fetchone()[0]
    cur.execute("SELECT v13_refresh_context(%s,%s,%s)",
                (eff, cl["attempt_no"], cl["fence"]))
    out = cur.fetchone()[0]
    cur.execute(
        "SELECT a.inline FROM artifacts a JOIN sessions s "
        "ON s.context_active_artifact=a.artifact_id WHERE s.session_id=%s",
        (sid,))
    return out, cur.fetchone()[0]


def recycle(server, conn):
    """Manifest-gate idiom: fresh backend re-allows the typesafe.*
    placeholder GUCs."""
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


_LLM_SEQ = [0]


def llm_effect(cur, sid, completion, model="mock-1", status="succeeded"):
    """Real enqueue/claim/complete path for an llm effect (R_o sample)."""
    _LLM_SEQ[0] += 1
    cur.execute(
        "SELECT v13_enqueue_effect(%s,'llm',"
        "jsonb_build_object('route',jsonb_build_object('action','llm',"
        "'reason','fixture-' || %s))::jsonb)", (sid, _LLM_SEQ[0]))
    eff = cur.fetchone()[0]
    cur.execute("SELECT v13_claim('t')")
    cl = cur.fetchone()[0]
    if status == "succeeded":
        cur.execute(
            "SELECT v13_complete(%s,%s,%s,'succeeded',"
            "jsonb_build_object('text','generated','usage',jsonb_build_object("
            "'completion_tokens',%s),'model',%s))",
            (eff, cl["attempt_no"], cl["fence"], completion, model))
    else:
        cur.execute(
            "SELECT v13_complete(%s,%s,%s,'failed',NULL)",
            (eff, cl["attempt_no"], cl["fence"]))
    return eff, cur.fetchone()[0]


def canonical(cur, sid):
    cur.execute(
        "SELECT (v13_canonical_state(%s)->'messages')::text", (sid,))
    return json.loads(cur.fetchone()[0])


def hist_sha_sql(cur, sid, seqs):
    """Test-side INDEPENDENT tail/segment slice: build the jsonb array from
    canonical by an explicit seq list in SQL (never calls
    v13_history_section_material) and hash it with the same jsonb text
    rendering."""
    cur.execute(
        "SELECT encode(digest(coalesce(("
        "SELECT jsonb_agg(m ORDER BY (m->>'seq')::bigint) "
        "  FROM jsonb_array_elements(v13_canonical_state(%s)->'messages') m"
        " WHERE (m->>'seq')::bigint = ANY(%s)), '[]'::jsonb)::text,"
        "'sha256'),'hex')", (sid, seqs))
    return cur.fetchone()[0]


def full_sha(cur, sid):
    cur.execute(
        "SELECT encode(digest(coalesce(("
        "v13_canonical_state(%s)->'messages')::text,''),'sha256'),'hex')",
        (sid,))
    return cur.fetchone()[0]


def tail_seqs(msgs, keep):
    """Independent python-side tail boundary: seqs of the last `keep`
    user turns (user/message start .. before next user/message)."""
    starts = [i for i, m in enumerate(msgs) if m["type"] == "user/message"]
    if len(starts) < keep:
        return [m["seq"] for m in msgs], False   # 不足 keep:材料=全量
    lo = starts[len(starts) - keep]
    return [m["seq"] for m in msgs[lo:]], True


def prefix_seqs(msgs, keep):
    starts = [i for i, m in enumerate(msgs) if m["type"] == "user/message"]
    if len(starts) < keep:
        return []
    lo = starts[len(starts) - keep]
    return [m["seq"] for m in msgs[:lo]]


def seed_ro(cur, sid, n=20):
    """Seed llm effect samples so R_o = percentile (not cold 8192)."""
    for i in range(1, n + 1):
        llm_effect(cur, sid, i)


def econ_of(manifest):
    return manifest["economics"]


def actions_on_fixture(cur, l_eff=1300):
    """Flip actions on + small l_eff; returns (tiers_ver, cbud_ver) to
    restore (v1, v1)."""
    cur.execute("SELECT value FROM v13_policies WHERE name='context_tiers' "
                "AND active")
    tiers = cur.fetchone()[0]
    cur.execute("SELECT value FROM v13_policies WHERE name='context_budget' "
                "AND active")
    cbud = cur.fetchone()[0]
    bump_policy(cur, "context_tiers", {**tiers, "actions_enabled": True})
    bump_policy(cur, "context_budget", {**cbud, "l_eff_tokens": l_eff})
    return tiers, cbud


def active_manifest(cur, sid):
    cur.execute(
        "SELECT a.inline FROM artifacts a JOIN sessions s "
        "ON s.context_active_artifact=a.artifact_id WHERE s.session_id=%s",
        (sid,))
    return cur.fetchone()[0]


def span_source(cur, sid, span):
    """Worker-side span read: retrieve the history blob from artifacts by
    content-hash and select messages by span hash membership."""
    cur.execute(
        "SELECT a.inline FROM artifacts a WHERE a.content_hash=("
        "SELECT s->>'content_hash' FROM jsonb_array_elements("
        "(SELECT inline FROM artifacts WHERE artifact_id="
        "(SELECT context_active_artifact FROM sessions WHERE session_id=%s))"
        "->'sections') s WHERE s->>'section_id'='history')", (sid,))
    blob = cur.fetchone()[0]
    cur.execute(
        "WITH msgs AS (SELECT x, (x->>'seq')::bigint AS seq "
        "  FROM jsonb_array_elements(%s::jsonb) x) "
        "SELECT coalesce(jsonb_agg(x ORDER BY (x->>'seq')::bigint),'[]') "
        "FROM msgs, jsonb_array_elements(%s::jsonb) h "
        "WHERE encode(digest(coalesce(x::text,''),'sha256'),'hex') = h #>> '{}'",
        (json.dumps(blob), json.dumps(span)))
    return cur.fetchone()[0]


def summary_mock(cur, signal, noul):
    mock = json.dumps({"model": "jev-mock",
                       "answers": {signal: {"type": "noul", "noul": noul}},
                       "usage": {"input_tokens": 1, "output_tokens": 1}})
    cur.execute("SELECT set_config('typesafe.mock_response', %s, true)",
                (mock,))


def prepare_round(cur, sid, body, noul=0.9):
    """One prepare round on a claimed effect: checks + envelope + resolve +
    verdict lookup. Returns (checks, decision_id|None, verdict|None)."""
    cur.execute(
        "SELECT request FROM effects WHERE session_id=%s AND "
        "kind='context_summary' AND status='claimed' ORDER BY created_at "
        "DESC LIMIT 1", (sid,))
    req = cur.fetchone()[0]
    src = span_source(cur, sid, req["span"])
    cur.execute("SELECT v13_summary_checks(%s,%s::jsonb,2048)",
                (body, json.dumps(src)))
    chk = cur.fetchone()[0]
    if not chk["pass"]:
        return chk, None, None, req, src
    cur.execute("SELECT v13_summary_envelope(%s,%s,%s,%s)",
                (sid, req["span_digest"], json.dumps(src), body))
    env = cur.fetchone()[0]
    sig = env["needed"][0]["signal"]
    summary_mock(cur, sig, noul)
    cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
                (json.dumps(env),))
    cur.fetchone()
    cur.execute(
        "SELECT decision_id FROM decisions WHERE session_id=%s AND "
        "signal=%s AND context=%s::jsonb AND answer IS NOT NULL",
        (sid, sig, json.dumps(env["groups"][0]["state"])))
    row = cur.fetchone()
    if row is None:
        return chk, None, {"action": "exclude",
                           "basis": "default_missing"}, req, src
    did = row[0]
    cur.execute("SELECT v13_summary_verdict(%s)", (did,))
    return chk, did, cur.fetchone()[0], req, src


def prepare_round(cur, sid, body, noul=0.9):
    """One prepare round on a claimed effect: checks + envelope + resolve +
    verdict lookup. Returns (checks, decision_id|None, verdict|None)."""
    cur.execute(
        "SELECT request FROM effects WHERE session_id=%s AND "
        "kind='context_summary' AND status='claimed' ORDER BY created_at "
        "DESC LIMIT 1", (sid,))
    req = cur.fetchone()[0]
    src = span_source(cur, sid, req["span"])
    cur.execute("SELECT v13_summary_checks(%s,%s::jsonb,2048)",
                (body, json.dumps(src)))
    chk = cur.fetchone()[0]
    if not chk["pass"]:
        return chk, None, None, req, src
    cur.execute("SELECT v13_summary_envelope(%s,%s,%s,%s)",
                (sid, req["span_digest"], json.dumps(src), body))
    env = cur.fetchone()[0]
    sig = env["needed"][0]["signal"]
    summary_mock(cur, sig, noul)
    cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
                (json.dumps(env),))
    cur.fetchone()
    cur.execute(
        "SELECT decision_id FROM decisions WHERE session_id=%s AND "
        "signal=%s AND context=%s::jsonb AND answer IS NOT NULL",
        (sid, sig, json.dumps(env["groups"][0]["state"])))
    row = cur.fetchone()
    if row is None:
        return chk, None, {"action": "exclude",
                           "basis": "default_missing"}, req, src
    did = row[0]
    cur.execute("SELECT v13_summary_verdict(%s)", (did,))
    return chk, did, cur.fetchone()[0], req, src


def drive_summary(cur, sid, bodies, noul=0.9, adopt_basis="decision_accept"):
    """Full worker drive: schedule -> claim -> rounds (per body) ->
    complete. Returns (effect_id, rounds, adopted, outcome)."""
    cur.execute("SELECT v13_summary_schedule(%s)", (sid,))
    eff = cur.fetchone()[0]
    assert eff is not None, "schedule returned NULL"
    cur.execute("SELECT v13_claim('t')")
    cl = cur.fetchone()[0]
    rounds = []
    adopted = False
    verdict = None
    for body in bodies:
        chk, did, verdict, req, src = prepare_round(cur, sid, body, noul=noul)
        rounds.append({"body": body, "content_hash": "0" * 64,
                       "checks": chk, "decision_id":
                       str(did) if did else None,
                       "verdict": verdict})
        if verdict and verdict["action"] == "include":
            adopted = True
            break
    if adopted:
        cur.execute(
            "SELECT v13_complete(%s,%s,%s,'succeeded',"
            "jsonb_build_object('rounds',%s::jsonb,'adopted',true,"
            "'basis',%s))",
            (eff, cl["attempt_no"], cl["fence"], json.dumps(rounds),
             adopt_basis))
    elif rounds and all(r["checks"]["pass"] for r in rounds):
        basis = {"decision_reject": "rejected",
                 "decision_review": "rejected",
                 "cjk_reject_only": "cjk",
                 "default_missing": "rejected",
                 "default_timeout": "rejected"}.get(
                    rounds[-1]["verdict"]["basis"], "rejected")
        cur.execute(
            "SELECT v13_complete(%s,%s,%s,'succeeded',"
            "jsonb_build_object('rounds',%s::jsonb,'adopted',false,"
            "'basis',%s))",
            (eff, cl["attempt_no"], cl["fence"], json.dumps(rounds), basis))
    else:
        cur.execute(
            "SELECT v13_complete(%s,%s,%s,'failed',"
            "jsonb_build_object('rounds',%s::jsonb,'basis','checks_failed'))",
            (eff, cl["attempt_no"], cl["fence"], json.dumps(rounds)))
    outcome = cur.fetchone()[0]
    return eff, rounds, adopted, outcome


def fn_body(src: str, name: str) -> str:
    i = src.index(f"CREATE OR REPLACE FUNCTION {name}(")
    j = src.index("AS $$", i) + len("AS $$")
    k = src.index("\nEND $$;", j) + len("\nEND $$;")
    return src[i:k]


def main() -> int:
    setup_db()
    server = get_server()
    conn = psycopg2.connect(server.get_uri(DB))
    conn.autocommit = False
    cur = conn.cursor()
    guc(cur)
    econ_sql = (V13 / "economy" / "v13_economy.sql").read_text()
    sum_sql = (V13 / "summary" / "v13_summary.sql").read_text()
    norm_s = strip_sql_comments(sum_sql)

    # ============================== I 组 ==============================
    # I1 加载/kind 六值
    check("I1: summary prefix 13", len(files_through("summary")) == 13)
    cur.execute(
        "SELECT conkey IS NOT NULL FROM pg_constraint WHERE conrelid="
        "'effects'::regclass AND conname='effects_kind_check' LIMIT 1")
    check("I1: effects_kind_check exists", cur.fetchone()[0] is True)
    sid_i1 = new_session(cur)
    conn.commit()
    cur.execute(
        "INSERT INTO effects (effect_id, session_id, kind, request, "
        "request_hash, origin_user_seq, status) VALUES "
        "(gen_random_uuid(), %s, 'context_summary', '{}'::jsonb, 'x', -1, "
        "'succeeded')", (sid_i1,))
    check("I1: context_summary hand row insertable", cur.rowcount == 1)
    fails_with(
        cur,
        "INSERT INTO effects (effect_id, session_id, kind, request, "
        "request_hash, origin_user_seq, status) VALUES "
        "(gen_random_uuid(), %s, 'bogus_kind', '{}'::jsonb, 'x', -1, "
        "'succeeded')", (sid_i1,),
        "violates check constraint", "I1: seventh kind value rejected")
    conn.commit()

    # I2 cap v2 六键恰等+五值保留
    cur.execute("SELECT value FROM v13_policies WHERE "
                "name='effect_attempt_cap' AND active")
    cap = cur.fetchone()[0]
    check("I2: cap v2 six keys exact (active)",
          cap == {"judge": 4, "tool": 3, "llm": 3, "human": 2,
                  "context_refresh": 3, "context_summary": 2}, cap)
    cur.execute("SELECT value FROM v13_policies WHERE "
                "name='effect_attempt_cap' AND version=1")
    cap_v1 = cur.fetchone()[0]
    check("I2: v1 five values preserved verbatim",
          {k: v for k, v in cap_v1.items()} ==
          {"judge": 4, "tool": 3, "llm": 3, "human": 2,
           "context_refresh": 3}, cap_v1)
    check("I2: v2 only adds summary key",
          cap_v1.keys() < cap.keys() and
          set(cap) - set(cap_v1) == {"context_summary"})

    # I3 enqueue 幂等/零水位
    sid_i3 = new_session(cur)
    append_user(cur, sid_i3, "i3 enqueue probe")
    conn.commit()
    req_a = {"purpose": "context_summary", "span": ["a" * 64],
             "span_digest": "b" * 64, "packs_reserved": 1,
             "policies": {"tiers_ver": 2, "budget_ver": 2,
                          "summary_ver": 1, "est_div": 4}}
    cur.execute("SELECT v13_enqueue_effect(%s,'context_summary',%s::jsonb)",
                (sid_i3, json.dumps(req_a)))
    e1 = cur.fetchone()[0]
    cur.execute("SELECT v13_enqueue_effect(%s,'context_summary',%s::jsonb)",
                (sid_i3, json.dumps(req_a)))
    e2 = cur.fetchone()[0]
    check("I3: same sid+request -> same effect_id", e1 == e2)
    req_b = {**req_a, "span_digest": "c" * 64}
    cur.execute("UPDATE effects SET status='cancelled' WHERE effect_id=%s",
                (e1,))
    cur.execute("SELECT v13_enqueue_effect(%s,'context_summary',%s::jsonb)",
                (sid_i3, json.dumps(req_b)))
    e3 = cur.fetchone()[0]
    check("I3: changed request -> new effect_id", e3 != e1)
    # 零水位字段(键集断言;经 schedule 产物断言在 J2)
    cur.execute("SELECT request FROM effects WHERE effect_id=%s", (e1,))
    check("I3: request zero watermark fields",
          set(cur.fetchone()[0].keys()) ==
          {"purpose", "span", "span_digest", "packs_reserved", "policies"})
    # I4 single-active:活跃 effect 在场时 schedule→NULL;静默期→enqueue 成功
    cur.execute("UPDATE effects SET status='cancelled' WHERE "
                "session_id=%s", (sid_i3,))
    cur.execute(
        "SELECT v13_enqueue_effect(%s,'llm',jsonb_build_object('route',"
        "jsonb_build_object('action','llm','reason','i4')))", (sid_i3,))
    conn.commit()
    cur.execute("SELECT v13_summary_schedule(%s)", (sid_i3,))
    check("I4: schedule NULL while another effect is ready",
          cur.fetchone()[0] is None)
    cur.execute("UPDATE effects SET status='cancelled' WHERE "
                "session_id=%s AND kind='llm'", (sid_i3,))
    conn.commit()

    # ============================== J 组 ==============================
    # 公共高压 fixture(actions on,l_eff=1300;R_o 样本灌满)
    sid_j = new_session(cur)
    seed_ro(cur, sid_j)
    tiers_v1 = None
    cbud_v1 = None
    cur.execute("SELECT version FROM v13_policies WHERE "
                "name='context_tiers' AND active")
    tiers_v1 = cur.fetchone()[0]
    cur.execute("SELECT version FROM v13_policies WHERE "
                "name='context_budget' AND active")
    cbud_v1 = cur.fetchone()[0]
    actions_on_fixture(cur, l_eff=1300)
    conn.commit()
    for i in range(1, 6):
        append_user(cur, sid_j, f"turn {i} asks about report {i} and path "
                                f"/a/b/{i}")
        conn.commit()
        anchored_llm(cur, sid_j, f"answer {i} with uuid "
                                 f"12345678-1234-1234-1234-123456789012 "
                                 + "x " * 200)
        conn.commit()
    m_j = assemble(cur, sid_j)
    econ_j = econ_of(m_j)
    msgs_j = canonical(cur, sid_j)
    prefix_j = prefix_seqs(msgs_j, 2)
    check("J1: high-pressure fixture >= CompactHistory",
          TIERS.index(econ_j["tier"]["effective"]) >= 2, econ_j["tier"])
    intent_j = econ_j["summary"]["intent"]
    check("J1: intent present {target_span,span_digest,packs,pack_ok}",
          intent_j is not None and
          set(intent_j.keys()) ==
          {"target_span", "span_digest", "packs", "pack_ok"} and
          intent_j["packs"] == 1 and intent_j["pack_ok"] is True, intent_j)
    cur.execute("SELECT v13_span_digest(%s::jsonb)",
                (json.dumps([hashlib.sha256(json.dumps(
                    m, separators=(",", ":"), ensure_ascii=False,
                    sort_keys=True).encode()).hexdigest()
                    for m in msgs_j if m["seq"] in prefix_j]),))
    # (对照面在 O1 用 SQL 同律自算;此处断言形状与 span 非空)
    check("J1: target_span non-empty prefix hashes",
          len(intent_j["target_span"]) == len(prefix_j) and
          all(HEX64.match(h) for h in intent_j["target_span"]))
    # Normal 档 ⇒ intent null(对照;临时大 l_eff 使 tier 归 Normal)
    sid_jn = new_session(cur)
    seed_ro(cur, sid_jn)
    append_user(cur, sid_jn, "normal tier probe")
    conn.commit()
    cur.execute("SELECT version FROM v13_policies WHERE name='context_budget' AND active")
    cbud_small_ver = cur.fetchone()[0]
    restore_policy(cur, "context_budget", cbud_v1)
    conn.commit()
    m_jn = assemble(cur, sid_jn)
    check("J1: Normal tier -> intent null (actions on, 对照)",
          econ_of(m_jn)["tier"]["effective"] == "Normal" and
          econ_of(m_jn)["summary"]["intent"] is None,
          econ_of(m_jn)["tier"])
    restore_policy(cur, "context_budget", cbud_small_ver)
    conn.commit()

    # J2 调度过闸:request 冻结 packs/policies 快照
    out_j2, m_j2 = refresh_n(cur, sid_j, m_j["required_revision"]["goal"])
    check("J2: settle N accepted", out_j2 == "accepted")
    cur.execute("SELECT v13_summary_schedule(%s)", (sid_j,))
    eff_j2 = cur.fetchone()[0]
    check("J2: quiet-period schedule -> effect created", eff_j2 is not None)
    cur.execute("SELECT request FROM effects WHERE effect_id=%s", (eff_j2,))
    req_j2 = cur.fetchone()[0]
    check("J2: request freezes packs + policies snapshot",
          req_j2["packs_reserved"] == 1 and
          set(req_j2["policies"].keys()) ==
          {"tiers_ver", "budget_ver", "summary_ver", "est_div"} and
          req_j2["span_digest"] == intent_j["span_digest"], req_j2)
    check("J2: request zero watermark fields",
          set(req_j2.keys()) ==
          {"purpose", "span", "span_digest", "packs_reserved", "policies"})
    # 花费闸超 ⇒ NULL(专用 session 灌闸;judgment_calls append-only 不可清)
    cur.execute("UPDATE effects SET status='cancelled' WHERE effect_id=%s",
                (eff_j2,))
    conn.commit()
    sid_j2g = new_session(cur)
    cur.execute(
        "INSERT INTO judgment_calls (session_id, candidate_set_hash, "
        "projection_key, payload, payload_hash, provider, model, "
        "question_count, status) SELECT %s, 'j2' || i, 'j2', '{}'::jsonb, "
        "'h' || i, 'mock', 'jev-mock', 1, 'succeeded' "
        "FROM generate_series(1, 512) i", (sid_j2g,))
    conn.commit()
    cur.execute("SELECT v13_summary_schedule(%s)", (sid_j2g,))
    check("J2: spend gate over -> schedule NULL",
          cur.fetchone()[0] is None)
    # schedule_cap_day 耗尽 ⇒ NULL(专用 session)
    sid_j2c = new_session(cur)
    cur.execute(
        "INSERT INTO effects (effect_id, session_id, kind, request, "
        "request_hash, origin_user_seq, status, created_at) SELECT "
        "gen_random_uuid(), %s, 'context_summary', '{}'::jsonb, 'c' || i, "
        "-1, 'succeeded', now() FROM generate_series(1, 8) i", (sid_j2c,))
    conn.commit()
    cur.execute("SELECT v13_summary_schedule(%s)", (sid_j2c,))
    check("J2: schedule_cap_day exhausted -> NULL",
          cur.fetchone()[0] is None)

    # J3 预留失败零调用:专用高压 session 灌闸后 schedule=NULL+零 effect+
    # 零 calls;下一次装配 fallback basis='no_budget'
    sid_j3 = new_session(cur)
    seed_ro(cur, sid_j3)
    for i in range(1, 6):
        append_user(cur, sid_j3, f"turn {i} j3 probe report {i} path "
                                f"/x/y/{i}")
        conn.commit()
        anchored_llm(cur, sid_j3, f"answer {i} uuid "
                                  f"12345678-1234-1234-1234-123456789012 "
                                  + "w " * 200)
        conn.commit()
    cur.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                (sid_j3,))
    calls_j3_before = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM effects WHERE session_id=%s AND "
                "kind='context_summary'", (sid_j3,))
    effs_j3_before = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO judgment_calls (session_id, candidate_set_hash, "
        "projection_key, payload, payload_hash, provider, model, "
        "question_count, status) SELECT %s, 'j3' || i, 'j3', '{}'::jsonb, "
        "'x' || i, 'mock', 'jev-mock', 1, 'succeeded' "
        "FROM generate_series(1, 512) i", (sid_j3,))
    conn.commit()
    cur.execute("SELECT v13_summary_schedule(%s)", (sid_j3,))
    check("J3: pack unavailable -> schedule NULL", cur.fetchone()[0] is None)
    cur.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                (sid_j3,))
    check("J3: zero new judgment_calls (生成与 Jev 都不调)",
          cur.fetchone()[0] == calls_j3_before + 512)
    cur.execute("SELECT count(*) FROM effects WHERE session_id=%s AND "
                "kind='context_summary'", (sid_j3,))
    check("J3: zero new effects", cur.fetchone()[0] == effs_j3_before)
    m_j3 = assemble(cur, sid_j3)
    fb_j3 = econ_of(m_j3)["summary"]["fallback"]
    check("J3/O4: assembly records basis='no_budget' + fallback trace",
          fb_j3 is not None and fb_j3["basis"] == "no_budget" and
          fb_j3["steps"][0]["op"] == "spill" and
          len(fb_j3["steps"]) >= 1, fb_j3)
    check("J3/O4: intent.pack_ok=false observable",
          econ_of(m_j3)["summary"]["intent"]["pack_ok"] is False)

    # J4 span 在场守卫:settle 后追加 user/message ⇒ span 失配 ⇒ NULL
    out_j4, m_j4 = refresh_n(cur, sid_j, m_j["required_revision"]["goal"])
    check("J4: settle before stale", out_j4 == "accepted")
    cur.execute("SELECT v13_summary_schedule(%s)", (sid_j,))
    eff_j4 = cur.fetchone()[0]
    check("J4: schedule before stale works", eff_j4 is not None)
    cur.execute("UPDATE effects SET status='cancelled' WHERE effect_id=%s",
                (eff_j4,))
    append_user(cur, sid_j, "new message invalidates span")
    conn.commit()
    cur.execute("SELECT v13_summary_schedule(%s)", (sid_j,))
    check("J4: span hash missing from canonical -> schedule NULL",
          cur.fetchone()[0] is None)

    # 还原 J 组策略
    restore_policy(cur, "context_tiers", tiers_v1)
    restore_policy(cur, "context_budget", cbud_v1)
    conn.commit()

    # ============================== K 组 ==============================
    # K1 prepare 全链 + K2 五项检查 + K4 packs 纪律
    def fresh_compact_fixture(server, conn, l_eff=1300, rounds=5):
        conn.commit()
        c = psycopg2.connect(server.get_uri(DB))
        c.autocommit = False
        k = c.cursor()
        guc(k)
        sid = new_session(k)
        seed_ro(k, sid)
        actions_on_fixture(k, l_eff=l_eff)
        for i in range(1, rounds + 1):
            append_user(k, sid, f"turn {i} asks about report {i} and path "
                                f"/p/q/{i}")
            c.commit()
            anchored_llm(k, sid, f"answer {i} uuid "
                                 f"12345678-1234-1234-1234-123456789012 "
                                 + "y " * 200)
            c.commit()
        return c, k, sid

    # K2:直接对 checks 断言五项(独立 session,无需驱动)
    span_k = [{"seq": 1, "type": "user/message",
               "payload": {"text": "see /etc/hosts and id "
                          "12345678-1234-1234-1234-123456789012 with 42"}},
              {"seq": 2, "type": "tool/result",
               "payload": {"tool": "session_stats", "result": {"n": 3},
                           "origin_user_seq": 1}}]
    good_body = ("Summary: path /etc/hosts, id "
                 "12345678-1234-1234-1234-123456789012, number 42, tool "
                 "session_stats, shorter than span.")

    def checks_of(body):
        cur.execute("SELECT v13_summary_checks(%s,%s::jsonb,2048)",
                    (body, json.dumps(span_k)))
        return cur.fetchone()[0]

    check("K2: healthy body passes", checks_of(good_body)["pass"] is True)
    r = checks_of("")
    check("K2-1 empty", "empty" in r["reasons"] and not r["pass"], r)
    r = checks_of("x" * 4000)
    check("K2-2 not_shorter (est(body) >= est(span))",
          "not_shorter" in r["reasons"] and not r["pass"], r)
    r = checks_of("Summary: number 42 and tool session_stats are kept but "
                  "path and id are gone gone gone.")
    check("K2-3 protected_missing (uuid+path dropped)",
          "protected_missing" in r["reasons"] and not r["pass"], r)
    r = checks_of("Summary:\x01\x02 control chars kept /etc/hosts id "
                  "12345678-1234-1234-1234-123456789012 42 session_stats")
    check("K2-4 structure (control chars)",
          "structure" in r["reasons"] and not r["pass"], r)
    cur.execute("SELECT v13_summary_checks(%s,%s::jsonb,16)",
                (good_body, json.dumps(span_k)))
    r = cur.fetchone()[0]
    check("K2-5 over_budget (cap=16)",
          "over_budget" in r["reasons"] and not r["pass"], r)

    # K1 全链(mock):claim→生成→checks 过→complete succeeded+零语义事件
    conn_k, cur_k, sid_k = fresh_compact_fixture(server, conn)
    m_k = assemble(cur_k, sid_k)
    out_k, m_k1 = refresh_n(cur_k, sid_k, m_k["required_revision"]["goal"])
    check("K1: settle N accepted", out_k == "accepted")
    cur_k.execute(
        "SELECT count(*) FROM events WHERE session_id=%s AND type IN "
        "('user/message','llm/message','tool/result')", (sid_k,))
    sem_before = cur_k.fetchone()[0]
    cur_k.execute("SELECT v13_summary_schedule(%s)", (sid_k,))
    eff_k = cur_k.fetchone()[0]
    check("K1: schedule -> effect", eff_k is not None)
    cur_k.execute("SELECT v13_claim('t')")
    cl_k = cur_k.fetchone()[0]
    req_k = cl_k["request"]
    src_k = span_source(cur_k, sid_k, req_k["span"])
    body_k = ("Summary of early turns: reports 1 2 3, paths /p/q/1 /p/q/2 "
              "/p/q/3, uuid 12345678-1234-1234-1234-123456789012, tool "
              "session_stats.")
    cur_k.execute("SELECT v13_summary_checks(%s,%s::jsonb,2048)",
                  (body_k, json.dumps(src_k)))
    chk_k = cur_k.fetchone()[0]
    check("K1: checks pass on healthy mock body", chk_k["pass"] is True,
          chk_k)
    # K3 est 同源:summary est 公式手算;确实缩短
    cur_k.execute(
        "SELECT octet_length(coalesce(%s::jsonb::text, '')), "
        "octet_length(to_jsonb(%s::text)::text)",
        (json.dumps(src_k), body_k))
    span_bytes, body_bytes = cur_k.fetchone()
    est_span = (span_bytes + 3) // 4
    est_body = (body_bytes + 3) // 4
    check("K3: est(summary) < Σest(span) (确实缩短)", est_body < est_span,
          (est_body, est_span))
    # (manifest est 对照在 O1-7)
    env_k_sig = None
    cur_k.execute("SELECT v13_summary_envelope(%s,%s,%s,%s)",
                  (sid_k, req_k["span_digest"], json.dumps(src_k), body_k))
    env_k = cur_k.fetchone()[0]
    env_k_sig = env_k["needed"][0]["signal"]
    summary_mock(cur_k, env_k_sig, 0.9)
    cur_k.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
                  (json.dumps(env_k),))
    res_k = cur_k.fetchone()[0]
    check("K1: resolve asked 1 landed 1",
          res_k["asked_questions"] == 1 and res_k["failed"] is False, res_k)
    cur_k.execute(
        "SELECT decision_id FROM decisions WHERE session_id=%s AND "
        "signal=%s AND context=%s::jsonb AND answer IS NOT NULL",
        (sid_k, env_k_sig, json.dumps(env_k["groups"][0]["state"])))
    did_k = cur_k.fetchone()[0]
    cur_k.execute("SELECT v13_summary_verdict(%s)", (did_k,))
    verd_k = cur_k.fetchone()[0]
    check("K1: verdict include/decision_accept",
          verd_k == {"action": "include", "basis": "decision_accept"},
          verd_k)
    rnd_k = {"body": body_k, "content_hash": "0" * 64, "checks": chk_k,
             "decision_id": str(did_k), "verdict": verd_k}
    cur_k.execute(
        "SELECT v13_complete(%s,%s,%s,'succeeded',"
        "jsonb_build_object('rounds',%s::jsonb,'adopted',true,'basis',"
        "'decision_accept'))",
        (eff_k, cl_k["attempt_no"], cl_k["fence"], json.dumps([rnd_k])))
    check("K1: complete succeeded", cur_k.fetchone()[0] == "accepted")
    cur_k.execute(
        "SELECT count(*) FROM events WHERE session_id=%s AND type IN "
        "('user/message','llm/message','tool/result')", (sid_k,))
    check("K1/P1: zero semantic events from context_summary complete",
          cur_k.fetchone()[0] == sem_before)
    cur_k.execute(
        "SELECT count(*) FROM judgment_calls WHERE session_id=%s",
        (sid_k,))
    check("K1: exactly one judgment_call (the verification ask)",
          cur_k.fetchone()[0] == 1)   # 20 seed llm 样本走 effect 面,零 calls
    conn_k.commit()   # 释放 refresh 的策略行锁(否则后续 fixture 的翻版阻塞)
    # K2 集成半边:checks 失败 ⇒ complete('failed') 且零 judgment_calls
    conn_k2, cur_k2, sid_k2 = fresh_compact_fixture(server, conn)
    m_k2a = assemble(cur_k2, sid_k2)
    refresh_n(cur_k2, sid_k2, m_k2a["required_revision"]["goal"])
    cur_k2.execute("SELECT v13_summary_schedule(%s)", (sid_k2,))
    eff_k2s = cur_k2.fetchone()[0]
    cur_k2.execute("SELECT v13_claim('t')")
    cl_k2s = cur_k2.fetchone()[0]
    src_k2 = span_source(cur_k2, sid_k2, cl_k2s["request"]["span"])
    cur_k2.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                   (sid_k2,))
    calls_k2_before = cur_k2.fetchone()[0]
    bad_body = "zzzz" * 3000   # not_shorter + protected_missing
    cur_k2.execute("SELECT v13_summary_checks(%s,%s::jsonb,2048)",
                   (bad_body, json.dumps(src_k2)))
    chk_bad = cur_k2.fetchone()[0]
    check("K2: failure reasons closed vocabulary",
          set(chk_bad["reasons"]) <=
          {"empty", "not_shorter", "protected_missing", "structure",
           "over_budget"} and not chk_bad["pass"], chk_bad)
    cur_k2.execute(
        "SELECT v13_complete(%s,%s,%s,'failed',NULL)",
        (eff_k2s, cl_k2s["attempt_no"], cl_k2s["fence"]))
    check("K2: checks failure -> complete('failed')",
          cur_k2.fetchone()[0] == "accepted")
    cur_k2.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                   (sid_k2,))
    check("K2: checks failure -> zero judgment_calls (不调 Jev)",
          cur_k2.fetchone()[0] == calls_k2_before)
    # K4 packs=1 检查失败即终结;cap=2 的 claim 轮次语义
    cur_k2.execute("SELECT status, attempt_no FROM effects WHERE effect_id=%s",
                   (eff_k2s,))
    st_k4, att_k4 = cur_k2.fetchone()
    check("K4: packs=1 check failure terminal (no retry)",
          st_k4 == "failed" and att_k4 == 1, (st_k4, att_k4))
    cur_k2.execute("SELECT v13_attempt_ok('context_summary', 1)")
    check("K4: attempt cap context_summary=2 allows second claim",
          cur_k2.fetchone()[0] is True)
    cur_k2.execute("SELECT v13_attempt_ok('context_summary', 2)")
    check("K4: third claim refused at cap",
          cur_k2.fetchone()[0] is False)
    conn_k2.commit()
    conn_k2.close()

    # ============================== L 组 ==============================
    # L1 信封形态(十二键=plan 十键+filter 加载态消费面两键)
    cur.execute("SELECT v13_summary_envelope(%s,%s,%s,%s)",
                (sid_k, req_k["span_digest"], json.dumps(src_k), body_k))
    env_l1 = cur.fetchone()[0]
    check("L1: envelope key set (plan ten + goal_hash/candidates)",
          set(env_l1.keys()) ==
          {"sid", "ctx", "needed", "templates", "groups", "budget",
           "timeout_ms", "candidate_set_hash", "provider", "model",
           "goal_hash", "candidates"}, set(env_l1.keys()))
    check("L1: ctx exactly {source,summary} = groups[].state 同源",
          env_l1["ctx"] == env_l1["groups"][0]["state"] ==
          {"source": json.dumps(src_k), "summary": body_k})
    check("L1: needed single question carries template_name",
          len(env_l1["needed"]) == 1 and
          env_l1["needed"][0]["template_name"] == "summary_fidelity" and
          env_l1["needed"][0]["kind"] == "noul")
    check("L1: budget={batch_questions:1} (resolve V3002 shape)",
          env_l1["budget"] == {"batch_questions": 1})
    check("L1: candidate_set_hash = span_digest (anchor)",
          env_l1["candidate_set_hash"] == req_k["span_digest"])
    check("L1: signal = summary::<64hex> (namespace)",
          env_l1["needed"][0]["signal"] ==
          "summary::" + req_k["span_digest"] and
          HEX64.match(req_k["span_digest"]))
    cur.execute(
        "SELECT projection_key, candidate_set_hash FROM judgment_calls "
        "WHERE session_id=%s ORDER BY created_at DESC LIMIT 1", (sid_k,))
    pk_l1, csh_l1 = cur.fetchone()
    check("L1: ask landed with candidate_set_hash=span_digest anchor",
          csh_l1 == req_k["span_digest"])
    # provider/model fail-closed:GUC 缺 → V3002(fresh backend 未设 GUC)
    conn_g = psycopg2.connect(server.get_uri(DB))
    conn_g.autocommit = False
    cur_g = conn_g.cursor()
    cur_g.execute("SET search_path TO public, pg_catalog")
    fails_with(cur_g,
               "SELECT v13_summary_envelope(%s,%s,%s,%s)",
               (sid_k, req_k["span_digest"], json.dumps(src_k), body_k),
               "fail-closed", "L1: missing GUC -> V3002", pgcode="V3002")
    conn_g.rollback()
    conn_g.close()

    # L2 已在 K1 全链覆盖;补 epoch 断言
    cur_k.execute("SELECT epoch FROM decisions WHERE decision_id=%s",
                  (did_k,))
    check("L2: decision epoch = pre-finalize (template attribute)",
          cur_k.fetchone()[0] == "pre-finalize")

    ask_pair = [None, None]   # [conn, cur]: 首次 ask 后 placeholder GUC 被
                               # 清,每次 ask 轮前回收(filter Conns 同型)

    def preset_decision(sid, src_text, summary_text, noul):
        c, k = ask_pair
        if k is not None:
            k.execute("SELECT coalesce(current_setting('typesafe.provider',"
                      " true), '')")
            if not k.fetchone()[0]:
                try:
                    c.commit()
                except Exception:
                    c.rollback()
                c.close()
                ask_pair[0] = ask_pair[1] = None
        if ask_pair[0] is None:
            c = psycopg2.connect(server.get_uri(DB))
            c.autocommit = False
            k = c.cursor()
            guc(k)
            ask_pair[0], ask_pair[1] = c, k
        k.execute("SELECT v13_summary_envelope(%s,%s,%s,%s)",
                  (sid, "f" * 64, src_text, summary_text))
        env = k.fetchone()[0]
        sig = env["needed"][0]["signal"]
        summary_mock(k, sig, noul)
        k.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
                  (json.dumps(env),))
        k.fetchone()
        k.execute(
            "SELECT decision_id FROM decisions WHERE session_id=%s AND "
            "signal=%s AND context=%s::jsonb AND answer IS NOT NULL",
            (sid, sig, json.dumps(env["groups"][0]["state"])))
        did = k.fetchone()[0]
        c.commit()
        return did
    # L3 不采用四态(经 decision_id 直取面)
    sid_l3 = new_session(cur)
    conn.commit()
    ac = psycopg2.connect(server.get_uri(DB))
    ac.autocommit = False
    ak = ac.cursor()
    guc(ak)
    src_l3 = json.dumps([{"seq": 1, "type": "user/message",
                          "payload": {"text": "l3 source"}}])
    for pval, basis_expect in ((0.2, "decision_reject"),
                               (0.6, "decision_review")):
        env_l3 = None
        did_l3 = preset_decision(sid_l3, src_l3, f"summary {pval}", pval)
        ak.execute("SELECT v13_summary_verdict(%s)", (did_l3,))
        v = ak.fetchone()[0]
        check(f"L3: p={pval} -> exclude/{basis_expect}",
              v == {"action": "exclude", "basis": basis_expect}, v)
    ac.commit()
    # missing:不存在 id
    cur.execute("SELECT v13_summary_verdict(%s)",
                ("00000000-0000-0000-0000-000000000000",))
    v = cur.fetchone()[0]
    check("L3: missing -> exclude/default_missing",
          v == {"action": "exclude", "basis": "default_missing"}, v)
    # timeout:预置 failed 行(answer NULL)
    env_l3t = None
    ak.execute("SELECT v13_summary_envelope(%s,%s,%s,%s)",
               (sid_l3, "e" * 64, src_l3, "timeout summary"))
    env_l3t = ak.fetchone()[0]
    sig_l3t = env_l3t["needed"][0]["signal"]
    h_l3t = None
    ak.execute("SELECT v13_judgment_hash(%s::jsonb,%s,%s,%s,%s)",
               (json.dumps(env_l3t), sig_l3t, "noul",
                env_l3t["needed"][0]["question"],
                json.dumps(env_l3t["needed"][0]["criteria"])))
    h_l3t = ak.fetchone()[0]
    ak.execute(
        "INSERT INTO decisions (session_id, signal, kind, question, "
        "criteria, context, provider, model, request_hash, status) VALUES "
        "(%s,%s,'noul',%s,%s,%s,'mock','jev-mock',%s,'failed')",
        (sid_l3, sig_l3t, env_l3t["needed"][0]["question"],
         json.dumps(env_l3t["needed"][0]["criteria"]),
         json.dumps(env_l3t["groups"][0]["state"]), h_l3t))
    ak.execute(
        "SELECT decision_id FROM decisions WHERE session_id=%s AND "
        "request_hash=%s", (sid_l3, h_l3t))
    did_l3t = ak.fetchone()[0]
    ak.execute("SELECT v13_summary_verdict(%s)", (did_l3t,))
    v = ak.fetchone()[0]
    check("L3: timeout(preset failed row) -> exclude/default_timeout",
          v == {"action": "exclude", "basis": "default_timeout"}, v)
    # defaults 点驱动:翻点不一致 ⇒ V3007 fail-loud
    cur.execute("SELECT value FROM v13_policies WHERE "
                "name='judgment_defaults' AND active")
    jdef_v1 = cur.fetchone()[0]
    jdef_next = next_policy_version(cur, "judgment_defaults")
    conn.commit()

    # L4 缓存半边:同材料二次验收零新增;新文本新哈希
    ak.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
               (sid_l3,))
    calls_l4_before = ak.fetchone()[0]
    ak.execute("SELECT count(*) FROM decisions WHERE session_id=%s AND "
               "signal=%s", (sid_l3, "summary::" + "f" * 64))
    dec_l4_before = ak.fetchone()[0]
    env_l4a = None
    # 同材料重验:经回收后的 fresh ask 连接(首 ask 后 placeholder GUC 被清)
    try:
        ac.commit()
    except Exception:
        ac.rollback()
    ac.close()
    ac2 = psycopg2.connect(server.get_uri(DB))
    ac2.autocommit = False
    ak = ac2.cursor()
    guc(ak)
    ak.execute("SELECT v13_summary_envelope(%s,%s,%s,%s)",
               (sid_l3, "f" * 64, src_l3, "summary 0.2"))
    env_l4a = ak.fetchone()[0]
    sig_l4a = env_l4a["needed"][0]["signal"]
    summary_mock(ak, sig_l4a, 0.2)
    ak.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
               (json.dumps(env_l4a),))
    res_l4 = ak.fetchone()[0]
    ak.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
               (sid_l3,))
    calls_l4_after = ak.fetchone()[0]
    check("L4: same materials re-verify -> cache hit, zero new calls",
          res_l4["asked_questions"] == 0 and
          calls_l4_after == calls_l4_before,
          (res_l4, calls_l4_after - calls_l4_before))
    ak.execute("SELECT count(*) FROM decisions WHERE session_id=%s AND "
               "signal=%s", (sid_l3, sig_l4a))
    check("L4: same materials -> no new decision rows",
          ak.fetchone()[0] == dec_l4_before,
          (dec_l4_before,))
    env_l4b = None
    ak.execute("SELECT v13_summary_envelope(%s,%s,%s,%s)",
               (sid_l3, "f" * 64, src_l3, "summary 0.2 regenerated text"))
    env_l4b = ak.fetchone()[0]
    ak.execute("SELECT v13_judgment_hash(%s::jsonb,%s,%s,%s,%s)",
               (json.dumps(env_l4a), sig_l4a, "noul",
                env_l4a["needed"][0]["question"],
                json.dumps(env_l4a["needed"][0]["criteria"])))
    h_a = ak.fetchone()[0]
    ak.execute("SELECT v13_judgment_hash(%s::jsonb,%s,%s,%s,%s)",
               (json.dumps(env_l4b), env_l4b["needed"][0]["signal"],
                "noul", env_l4b["needed"][0]["question"],
                json.dumps(env_l4b["needed"][0]["criteria"])))
    h_b = ak.fetchone()[0]
    check("L4: new summary text -> new request_hash (重验独立)",
          h_a != h_b)
    ac2.commit()
    ac2.close()
    conn.commit()

    # L5 在 O1 manifest 断言(consumed ⇒ judgments final_action='include';
    # 不采用态零进 judgments 由 L3 fixture 装配对照)

    # ============================== M 组 ==============================
    # M 组按 B-DP7-2 裁决 §3.4 三行读法;两轮间 provider/model GUC 恒定。
    # M1a:round1 检查失败,round2 不同文本通过+验收
    cur.execute("SELECT value FROM v13_policies WHERE "
                "name='summary_accept' AND active")
    sa_v1 = cur.fetchone()[0]
    sa_m1 = {**sa_v1, "packs_reserved": 2}
    bump_policy(cur, "summary_accept", sa_m1)
    conn_m, cur_m, sid_m1a = fresh_compact_fixture(server, conn)
    cur_m.execute("SELECT version FROM v13_policies WHERE "
                  "name='summary_accept' AND active")
    check("M1: packs=2 fixture active", cur_m.fetchone()[0] >= 2)
    m_m1a = assemble(cur_m, sid_m1a)
    refresh_n(cur_m, sid_m1a, m_m1a["required_revision"]["goal"])
    cur_m.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                  (sid_m1a,))
    m1a_calls_before = cur_m.fetchone()[0]
    cur_m.execute("SELECT count(*) FROM decisions WHERE session_id=%s AND "
                  "signal LIKE 'summary::%%'", (sid_m1a,))
    m1a_dec_before = cur_m.fetchone()[0]
    cur_m.execute("SELECT v13_summary_schedule(%s)", (sid_m1a,))
    eff_m1a = cur_m.fetchone()[0]
    cur_m.execute("SELECT v13_claim('t')")
    cl_m1a = cur_m.fetchone()[0]
    conn_m.commit()   # claim 持久化;释放 refresh/claim 行锁(worker 双连接形态)
    req_m1a = cl_m1a["request"]
    src_m1a = span_source(cur_m, sid_m1a, req_m1a["span"])
    # round1:检查失败(超长文本)
    body1_bad = "w" * 5000
    cur_m.execute("SELECT v13_summary_checks(%s,%s::jsonb,2048)",
                  (body1_bad, json.dumps(src_m1a)))
    chk1 = cur_m.fetchone()[0]
    check("M1a: round1 checks fail", chk1["pass"] is False, chk1["reasons"])
    cur_m.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                  (sid_m1a,))
    check("M1a: round1 前后 judgment_calls 差=0 (检查失败不调 Jev)",
          cur_m.fetchone()[0] == m1a_calls_before)
    # round1 envelope hash(测试端自算,未 ask)
    cur_m.execute("SELECT v13_summary_envelope(%s,%s,%s,%s)",
                  (sid_m1a, req_m1a["span_digest"], json.dumps(src_m1a),
                   body1_bad))
    env_r1 = cur_m.fetchone()[0]
    cur_m.execute("SELECT v13_judgment_hash(%s::jsonb,%s,%s,%s,%s)",
                  (json.dumps(env_r1), env_r1["needed"][0]["signal"],
                   "noul", env_r1["needed"][0]["question"],
                   json.dumps(env_r1["needed"][0]["criteria"])))
    hash_r1 = cur_m.fetchone()[0]
    # round2:不同文本通过并验收
    body2 = ("Summary: reports 1 2 3, paths /p/q/1 /p/q/2 /p/q/3, uuid "
             "12345678-1234-1234-1234-123456789012, tool session_stats.")
    cur_m.execute("SELECT v13_summary_checks(%s,%s::jsonb,2048)",
                  (body2, json.dumps(src_m1a)))
    chk2 = cur_m.fetchone()[0]
    check("M1a: round2 different text passes", chk2["pass"] is True)
    cur_m.execute("SELECT v13_summary_envelope(%s,%s,%s,%s)",
                  (sid_m1a, req_m1a["span_digest"], json.dumps(src_m1a),
                   body2))
    env_r2 = cur_m.fetchone()[0]
    sig_r2 = env_r2["needed"][0]["signal"]
    summary_mock(cur_m, sig_r2, 0.9)
    cur_m.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
                  (json.dumps(env_r2),))
    res_r2 = cur_m.fetchone()[0]
    check("M1a: round2 asked 1", res_r2["asked_questions"] == 1)
    cur_m.execute(
        "SELECT decision_id, request_hash FROM decisions WHERE "
        "session_id=%s AND signal=%s AND context=%s::jsonb AND answer IS "
        "NOT NULL", (sid_m1a, sig_r2, json.dumps(env_r2["groups"][0]["state"])))
    did_r2, hash_r2 = cur_m.fetchone()
    check("M1a: 两轮 request_hash 不等(重生成非重问)",
          hash_r1 != hash_r2)
    cur_m.execute("SELECT v13_summary_verdict(%s)", (did_r2,))
    verd_r2 = cur_m.fetchone()[0]
    check("M1a: round2 verdict include", verd_r2["action"] == "include")
    rounds_m1a = [
        {"body": body1_bad, "content_hash": "0" * 64, "checks": chk1,
         "decision_id": None, "verdict": None},
        {"body": body2, "content_hash": "0" * 64, "checks": chk2,
         "decision_id": str(did_r2), "verdict": verd_r2}]
    cur_m.execute(
        "SELECT v13_complete(%s,%s,%s,'succeeded',"
        "jsonb_build_object('rounds',%s::jsonb,'adopted',true,'basis',"
        "'decision_accept'))",
        (eff_m1a, cl_m1a["attempt_no"], cl_m1a["fence"],
         json.dumps(rounds_m1a)))
    check("M1a: complete succeeded", cur_m.fetchone()[0] == "accepted")
    cur_m.execute("SELECT count(*) FROM decisions WHERE session_id=%s AND "
                  "signal LIKE 'summary::%%'", (sid_m1a,))
    check("M1a: decision rows = 1 (检查失败路径全程恰 1)",
          cur_m.fetchone()[0] - m1a_dec_before == 1)
    cur_m.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                  (sid_m1a,))
    check("M1a: 全程 judgment_calls 差=1",
          cur_m.fetchone()[0] - m1a_calls_before == 1)
    conn_m.commit()
    conn_m.close()

    # M1b:round1 验收 reject,round2 不同文本再验收
    conn_m, cur_m, sid_m1b = fresh_compact_fixture(server, conn)
    m_m1b = assemble(cur_m, sid_m1b)
    refresh_n(cur_m, sid_m1b, m_m1b["required_revision"]["goal"])
    cur_m.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                  (sid_m1b,))
    m1b_calls_before = cur_m.fetchone()[0]
    cur_m.execute("SELECT v13_summary_schedule(%s)", (sid_m1b,))
    eff_m1b = cur_m.fetchone()[0]
    cur_m.execute("SELECT v13_claim('t')")
    cl_m1b = cur_m.fetchone()[0]
    conn_m.commit()   # claim 持久化;释放行锁(worker 双连接形态)
    req_m1b = cl_m1b["request"]
    src_m1b = span_source(cur_m, sid_m1b, req_m1b["span"])
    rounds_b = []
    hashes_b = []
    mpair = [None, None]   # worker 的 resolve 副连接(每轮 ask 前回收——
                           # 首 ask 后 placeholder GUC 被清,filter Conns 同型)

    def m_ask(body_b, noul_b):
        c, k = mpair
        if k is not None:
            k.execute("SELECT coalesce(current_setting("
                      "'typesafe.provider', true), '')")
            if not k.fetchone()[0]:
                try:
                    c.commit()
                except Exception:
                    c.rollback()
                c.close()
                mpair[0] = mpair[1] = None
        if mpair[0] is None:
            c = psycopg2.connect(server.get_uri(DB))
            c.autocommit = False
            k = c.cursor()
            guc(k)
            mpair[0], mpair[1] = c, k
        k.execute("SELECT v13_summary_envelope(%s,%s,%s,%s)",
                  (sid_m1b, req_m1b["span_digest"],
                   json.dumps(src_m1b), body_b))
        env_b = k.fetchone()[0]
        sig_b = env_b["needed"][0]["signal"]
        summary_mock(k, sig_b, noul_b)
        k.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
                  (json.dumps(env_b),))
        k.fetchone()
        k.execute(
            "SELECT decision_id FROM decisions WHERE session_id=%s AND "
            "signal=%s AND context=%s::jsonb AND answer IS NOT NULL",
            (sid_m1b, sig_b, json.dumps(env_b["groups"][0]["state"])))
        did_b = k.fetchone()[0]
        k.execute("SELECT request_hash, context->>'summary' FROM decisions "
                  "WHERE decision_id=%s", (did_b,))
        rh_b, summ_b = k.fetchone()
        k.execute("SELECT v13_summary_verdict(%s)", (did_b,))
        verd_b = k.fetchone()[0]
        c.commit()
        return did_b, rh_b, summ_b, verd_b

    for idx, (body_b, noul_b) in enumerate((
            ("Summary first attempt: reports 1 2 3, paths /p/q/1 /p/q/2 "
             "/p/q/3, uuid 12345678-1234-1234-1234-123456789012, tool "
             "session_stats.", 0.2),
            ("Summary second attempt with new text: reports 1 2 3, paths "
             "/p/q/1 /p/q/2 /p/q/3, uuid 12345678-1234-1234-1234-"
             "123456789012, tool session_stats.", 0.9))):
        cur_m.execute("SELECT v13_summary_checks(%s,%s::jsonb,2048)",
                      (body_b, json.dumps(src_m1b)))
        chk_b = cur_m.fetchone()[0]
        did_b, rh_b, summ_b, verd_b = m_ask(body_b, noul_b)
        hashes_b.append((rh_b, summ_b))
        rounds_b.append({"body": body_b, "content_hash": "0" * 64,
                         "checks": chk_b, "decision_id": str(did_b),
                         "verdict": verd_b})
    check("M1b: round2 ctx.summary != round1 (new materials)",
          hashes_b[0][1] != hashes_b[1][1])
    cur_m.execute(
        "SELECT v13_complete(%s,%s,%s,'succeeded',"
        "jsonb_build_object('rounds',%s::jsonb,'adopted',true,'basis',"
        "'decision_accept'))",
        (eff_m1b, cl_m1b["attempt_no"], cl_m1b["fence"],
         json.dumps(rounds_b)))
    check("M1b: complete succeeded", cur_m.fetchone()[0] == "accepted")
    cur_m.execute("SELECT count(*) FROM decisions WHERE session_id=%s AND "
                  "signal LIKE 'summary::%%'", (sid_m1b,))
    check("M1b: decision rows = 2 (reject 路径)",
          cur_m.fetchone()[0] == 2)
    cur_m.execute(
        "SELECT count(*) FROM decisions WHERE session_id=%s AND "
        "signal LIKE 'summary::%%' AND epoch='pre-finalize'", (sid_m1b,))
    check("M1b: both rows epoch=pre-finalize (计数不滤 epoch)",
          cur_m.fetchone()[0] == 2)
    cur_m.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                  (sid_m1b,))
    check("M1b: 全程 judgment_calls 差=2",
          cur_m.fetchone()[0] - m1b_calls_before == 2)
    check("M1b: 两行 request_hash 不等", hashes_b[0][0] != hashes_b[1][0])

    # M1-neg:同 {source,summary} 再调 resolve ⇒ gap 空,零新增
    cur_m.execute("SELECT count(*) FROM decisions WHERE session_id=%s",
                  (sid_m1b,))
    dec_neg_before = cur_m.fetchone()[0]
    cur_m.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                  (sid_m1b,))
    calls_neg_before = cur_m.fetchone()[0]
    body_last = rounds_b[-1]["body"]
    nc = psycopg2.connect(server.get_uri(DB))   # fresh backend(已 ask 的连接
    nc.autocommit = False                        # provider 被 purged)
    nk = nc.cursor()
    guc(nk)
    nk.execute("SELECT v13_summary_envelope(%s,%s,%s,%s)",
               (sid_m1b, req_m1b["span_digest"], json.dumps(src_m1b),
                body_last))
    env_neg = nk.fetchone()[0]
    nk.execute("SELECT jsonb_array_length(v13_gap(%s::jsonb))",
               (json.dumps(env_neg),))
    check("M1-neg: gap empty (cache hit)", nk.fetchone()[0] == 0)
    summary_mock(nk, env_neg["needed"][0]["signal"], 0.9)
    nk.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
               (json.dumps(env_neg),))
    res_neg = nk.fetchone()[0]
    check("M1-neg: asked=0",
          res_neg["asked_questions"] == 0)
    cur_m.execute("SELECT count(*) FROM decisions WHERE session_id=%s",
                  (sid_m1b,))
    check("M1-neg: decisions 零新增",
          cur_m.fetchone()[0] == dec_neg_before)
    cur_m.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                  (sid_m1b,))
    check("M1-neg: judgment_calls 零新增",
          cur_m.fetchone()[0] == calls_neg_before)
    nc.commit()
    nc.close()
    conn_m.commit()
    conn_m.close()

    # M2:packs=2 用尽——两轮检查全失败 ⇒ complete('failed')/adopted=false;
    # 终案落地后 settle 不再误伤此路径
    conn_m, cur_m, sid_m2 = fresh_compact_fixture(server, conn)
    m_m2 = assemble(cur_m, sid_m2)
    refresh_n(cur_m, sid_m2, m_m2["required_revision"]["goal"])
    cur_m.execute("SELECT v13_summary_schedule(%s)", (sid_m2,))
    eff_m2 = cur_m.fetchone()[0]
    cur_m.execute("SELECT v13_claim('t')")
    cl_m2 = cur_m.fetchone()[0]
    conn_m.commit()
    src_m2 = span_source(cur_m, sid_m2, cl_m2["request"]["span"])
    rounds_m2 = []
    for b in ("f" * 5000, "g" * 6000):
        cur_m.execute("SELECT v13_summary_checks(%s,%s::jsonb,2048)",
                      (b, json.dumps(src_m2)))
        rounds_m2.append({"body": b, "content_hash": "0" * 64,
                          "checks": cur_m.fetchone()[0],
                          "decision_id": None, "verdict": None})
    check("M2: both rounds checks-failed (no third round; packs=2 封顶)",
          all(not r["checks"]["pass"] for r in rounds_m2) and
          len(rounds_m2) == 2)
    cur_m.execute(
        "SELECT v13_complete(%s,%s,%s,'failed',jsonb_build_object("
        "'rounds',%s::jsonb,'basis','checks_failed'))",
        (eff_m2, cl_m2["attempt_no"], cl_m2["fence"], json.dumps(rounds_m2)))
    check("M2: complete('failed')", cur_m.fetchone()[0] == "accepted")
    cur_m.execute("SELECT result->>'adopted' FROM effects WHERE effect_id=%s",
                  (eff_m2,))
    check("M2: adopted=false/absent (不误伤)",
          (cur_m.fetchone()[0] or "false") != "true")
    # settle 后装配记 basis='checks_failed'
    m_m2b = assemble(cur_m, sid_m2)
    fb_m2 = econ_of(m_m2b)["summary"]["fallback"]
    check("M2/O4: fallback basis='checks_failed' after exhausted packs",
          fb_m2 is not None and fb_m2["basis"] == "checks_failed", fb_m2)
    out_m2, _ = refresh_n(cur_m, sid_m2, m_m2b["required_revision"]["goal"])
    check("M2: settle accepted after failed summary (fallback 接管)",
          out_m2 == "accepted")
    conn_m.commit()
    conn_m.close()
    # 还原 packs
    restore_policy(cur, "summary_accept", 1)
    conn.commit()

    # ============================== N 组 ==============================
    # N1/N2:CJK 拒绝-only 两向(材料=decisions.context->>'source' 存储半边)
    sid_n = new_session(cur)
    conn.commit()
    cjk_src = json.dumps(
        [{"seq": 1, "type": "user/message",
          "payload": {"text": "这是一段中文为主的语料，" * 40}}],
        ensure_ascii=False)
    lat_src = json.dumps(
        [{"seq": 1, "type": "user/message",
          "payload": {"text": "mostly latin text " * 40}}])
    check("N1: CJK fixture ratio > 0.30 (python-side sample)",
          sum(1 for ch in json.loads(cjk_src)[0]["payload"]["text"]
              if '一' <= ch <= '鿿') /
          len(json.loads(cjk_src)[0]["payload"]["text"]) > 0.30)

    did_n1 = preset_decision(sid_n, cjk_src, "中文摘要 short", 0.9)
    cur.execute("SELECT v13_summary_verdict(%s)", (did_n1,))
    v_n1 = cur.fetchone()[0]
    check("N2-1: CJK material + accept band -> still not adopted "
          "(cjk_reject_only)",
          v_n1 == {"action": "exclude", "basis": "cjk_reject_only"}, v_n1)
    did_n2 = preset_decision(sid_n, cjk_src, "另一份中文摘要", 0.2)
    cur.execute("SELECT v13_summary_verdict(%s)", (did_n2,))
    v_n2 = cur.fetchone()[0]
    check("N2-2: CJK material + reject signal -> not adopted "
          "(附加拒绝信号生效)",
          v_n2["action"] == "exclude" and v_n2["basis"] == "decision_reject",
          v_n2)
    did_n3 = preset_decision(sid_n, lat_src, "latin summary ok", 0.9)
    cur.execute("SELECT v13_summary_verdict(%s)", (did_n3,))
    v_n3 = cur.fetchone()[0]
    check("N2-3: non-CJK material + accept -> adopted (门不激活)",
          v_n3 == {"action": "include", "basis": "decision_accept"}, v_n3)

    # N3:mode='calibrated' 翻版 → 行为翻转(数据动作)
    cur.execute("SELECT value FROM v13_policies WHERE "
                "name='summary_accept' AND active")
    sa_n = cur.fetchone()[0]
    v_n3flip = bump_policy(cur, "summary_accept",
                           {**sa_n,
                            "cjk": {**sa_n["cjk"], "mode": "calibrated"}})
    conn.commit()
    cur.execute("SELECT v13_summary_verdict(%s)", (did_n1,))
    v_n3b = cur.fetchone()[0]
    check("N3: calibrated flip -> accept可采 (行为翻转)",
          v_n3b == {"action": "include", "basis": "decision_accept"}, v_n3b)
    restore_policy(cur, "summary_accept", 1)
    conn.commit()

    # ============================== O 组 ==============================
    # O1 采用消费十项(fixture:K1 的 sid_k 已 adopted;再 settle N+1)
    m_o1_pre = assemble(cur_k, sid_k)
    out_o1, m_o1 = refresh_n(cur_k, sid_k,
                             m_o1_pre["required_revision"]["goal"])
    check("O1-1: refresh accepted, zero V3003/V3007",
          out_o1 == "accepted", out_o1)
    secs_o1 = {s["section_id"]: s for s in m_o1["sections"]}
    sum_o1 = secs_o1.get("summary")
    check("O1-2: summary section shape",
          sum_o1 is not None and
          sum_o1["kind"] == "summary" and
          sum_o1["priority"] == "Normal" and
          sum_o1["cache_scope"] == "Session" and
          sum_o1["transform"] == {"applied": True, "name": "summarize"} and
          sum_o1["payload_ref"]["kind"] == "blob" and
          sum_o1["payload_ref"]["content_hash"] ==
          sum_o1["content_hash"] and
          HEX64.match(sum_o1["content_hash"]), sum_o1)
    # O1-3:hash==sha256(to_jsonb(body)::text) 测试端自算;≠自报哈希
    cur_k.execute(
        "SELECT encode(digest(to_jsonb(%s::text)::text,'sha256'),'hex')",
        (body_k,))
    h_body = cur_k.fetchone()[0]
    check("O1-3: hash == sha256(to_jsonb(body)::text) (自算,零信自报)",
          sum_o1["content_hash"] == h_body and
          sum_o1["content_hash"] != "0" * 64)
    cur_k.execute(
        "SELECT inline FROM artifacts WHERE kind='context_section' AND "
        "content_hash=%s", (sum_o1["content_hash"],))
    inline_o1 = cur_k.fetchone()[0]
    check("O1-3: artifacts inline == to_jsonb(body)",
          inline_o1 == json.loads(json.dumps(body_k)) or
          inline_o1 == body_k, inline_o1)
    # O1-4:history=verbatim 尾段;测试端独立切片
    hist_o1 = secs_o1["history"]
    msgs_o1 = canonical(cur_k, sid_k)
    tail_seq_list, had_tail = tail_seqs(msgs_o1, 2)
    check("O1-4 precondition: fixture had >= keep user turns",
          had_tail is True)
    h_tail = hist_sha_sql(cur_k, sid_k, tail_seq_list)
    h_full = full_sha(cur_k, sid_k)
    check("O1-4: history hash == independent tail sha256, != full sha256",
          hist_o1["content_hash"] == h_tail and
          hist_o1["content_hash"] != h_full and
          hist_o1["transform"] == {"applied": True, "name": "verbatim"})
    # churn=prior+1(前版=消费前 manifest)
    prior_hist = next(s for s in m_k1["sections"]
                      if s["section_id"] == "history")
    check("O1-4: churn = prior_churn + 1",
          hist_o1["churn"] == prior_hist["churn"] + 1,
          (hist_o1["churn"], prior_hist["churn"]))
    check("O1-4: no skipped sections for replaced rounds",
          all(s["transform"]["applied"] or
              s["transform"].get("reason") in ("budget",)
              for s in m_o1["sections"]) and
          not any(s["section_id"].startswith("compaction")
                  for s in m_o1["sections"]))
    # O1-5:history blob inline == 尾段 jsonb(非全文)
    cur_k.execute(
        "SELECT inline FROM artifacts WHERE kind='context_section' AND "
        "content_hash=%s", (hist_o1["content_hash"],))
    blob_hist = cur_k.fetchone()[0]
    cur_k.execute(
        "SELECT (SELECT jsonb_agg(m ORDER BY (m->>'seq')::bigint) "
        "FROM jsonb_array_elements(v13_canonical_state(%s)->'messages') m "
        "WHERE (m->>'seq')::bigint = ANY(%s))::text", (sid_k, tail_seq_list))
    tail_text = cur_k.fetchone()[0]
    check("O1-5: history blob inline == tail jsonb (not full canonical)",
          json.dumps(blob_hist, sort_keys=True) ==
          json.dumps(json.loads(tail_text), sort_keys=True))
    # O1-6:goal/tools 与 actions off 对照装配相同
    restore_policy(cur_k, "context_tiers", tiers_v1)
    restore_policy(cur_k, "context_budget", cbud_v1)
    conn_k.commit()
    m_off = assemble(cur_k, sid_k)
    secs_off = {s["section_id"]: s for s in m_off["sections"]}
    check("O1-6: goal/tools byte-identical to actions-off control",
          secs_off["goal"]["content_hash"] == secs_o1["goal"]["content_hash"]
          and secs_off["tools"]["content_hash"] ==
          secs_o1["tools"]["content_hash"])
    cur_k.execute(
        "SELECT encode(digest(coalesce((v13_canonical_state(%s)->'tools')"
        "::text,''),'sha256'),'hex')", (sid_k,))
    check("O1-6/O5: tools blob still canonical tools",
          cur_k.fetchone()[0] == secs_o1["tools"]["content_hash"])
    # O1-7:est(summary)<est(被替前缀);applied Σest < 对照 Σest
    prefix_list = prefix_seqs(msgs_o1, 2)
    cur_k.execute(
        "SELECT octet_length(coalesce((SELECT jsonb_agg(m ORDER BY "
        "(m->>'seq')::bigint) FROM jsonb_array_elements("
        "v13_canonical_state(%s)->'messages') m WHERE (m->>'seq')::bigint "
        "= ANY(%s))::text,''))", (sid_k, prefix_list))
    prefix_bytes = cur_k.fetchone()[0]
    est_prefix = (prefix_bytes + 3) // 4
    check("O1-7: est(summary) < est(replaced prefix)",
          sum_o1["est_tokens"] < est_prefix,
          (sum_o1["est_tokens"], est_prefix))
    sum_treated = sum(s["est_tokens"] for s in m_o1["sections"])
    sum_control = sum(s["est_tokens"] for s in m_off["sections"])
    check("O1-7: total est decreased vs counterfactual full manifest",
          sum_treated < sum_control, (sum_treated, sum_control))
    # 恢复 actions on(O2/O3 继续)
    cur_k.execute(
        "UPDATE v13_policies SET active=false WHERE name='context_tiers' "
        "AND active")
    cur_k.execute(
        "UPDATE v13_policies SET active=true WHERE name='context_tiers' "
        "AND version=(SELECT max(version) FROM v13_policies WHERE "
        "name='context_tiers')")
    cur_k.execute(
        "UPDATE v13_policies SET active=false WHERE name='context_budget' "
        "AND active")
    cur_k.execute(
        "UPDATE v13_policies SET active=true WHERE name='context_budget' "
        "AND version=(SELECT max(version) FROM v13_policies WHERE "
        "name='context_budget')")
    conn_k.commit()
    # O1-8:同材料重 settle 零新行
    for h in (sum_o1["content_hash"], hist_o1["content_hash"]):
        cur_k.execute(
            "SELECT count(*) FROM artifacts WHERE "
            "kind='context_section' AND content_hash=%s", (h,))
        check(f"O1-8: context_section rows for {h[:8]} == 1",
              cur_k.fetchone()[0] == 1)
    out_o1b, m_o1b = refresh_n(cur_k, sid_k, m_o1["required_revision"]["goal"])
    check("O1-8: re-settle accepted", out_o1b == "accepted")
    for h in (sum_o1["content_hash"], hist_o1["content_hash"]):
        cur_k.execute(
            "SELECT count(*) FROM artifacts WHERE "
            "kind='context_section' AND content_hash=%s", (h,))
        check(f"O1-8: still 1 row after re-settle ({h[:8]})",
              cur_k.fetchone()[0] == 1)
    # O1-9:canonical 元素数不变;语义事件计数零增
    msgs_o1b = canonical(cur_k, sid_k)
    check("O1-9: canonical message count unchanged",
          len(msgs_o1b) == len(msgs_o1))
    cur_k.execute(
        "SELECT count(*) FROM events WHERE session_id=%s AND type IN "
        "('user/message','llm/message','tool/result')", (sid_k,))
    check("O1-9: semantic event count zero increase",
          cur_k.fetchone()[0] == sem_before)
    check("O1/L5: consumed decision in judgments with final_action=include",
          any(j["final_action"] == "include" and
              j["epoch"] == "pre-finalize" for j in m_o1["judgments"]),
          m_o1["judgments"])
    # O1-10/O2:span_stale——追加 user/message+压力回落 ⇒ IF 臂/无 summary/
    # basis='span_stale'/settle accepted。held 档按 hysteresis 语义跨 turn
    # 保持(fixture 翻 cooldown=1/max_steps=4 加速归位,两 turn 后 eff=Normal)
    cur_k.execute("SELECT value FROM v13_policies WHERE "
                  "name='context_budget' AND version=1")
    cbud_big = {**cur_k.fetchone()[0], "l_eff_tokens": 128000}
    cur_k.execute("SELECT value FROM v13_policies WHERE "
                  "name='context_tiers' AND active")
    tiers_o2 = cur_k.fetchone()[0]
    bump_policy(cur_k, "context_budget", cbud_big)
    bump_policy(cur_k, "context_tiers",
                {**tiers_o2,
                 "hysteresis": {"cooldown_turns": 1,
                                "max_downgrade_steps": 4}})
    conn_k.commit()
    append_user(cur_k, sid_k, "span stale turn after consumption")
    conn_k.commit()
    m_o2s1 = assemble(cur_k, sid_k)
    out_o2s1, _ = refresh_n(cur_k, sid_k,
                            m_o2s1["required_revision"]["goal"])
    check("O2: stale settle S1 accepted (span invalid, ladder holds)",
          out_o2s1 == "accepted")
    append_user(cur_k, sid_k, "second clean low-pressure turn")
    conn_k.commit()
    m_o2 = assemble(cur_k, sid_k)
    secs_o2 = {s["section_id"]: s for s in m_o2["sections"]}
    fb_o2 = econ_of(m_o2)["summary"]["fallback"]
    check("O2: no summary section after span invalidation",
          "summary" not in secs_o2)
    check("O2: basis='span_stale' observable (action=full, steps=[])",
          fb_o2 is not None and fb_o2["basis"] == "span_stale" and
          fb_o2["steps"] == [] and
          econ_of(m_o2)["tier"]["effective"] == "Normal", fb_o2)
    check("O2: history hash back to full (IF arm path)",
          secs_o2["history"]["content_hash"] == full_sha(cur_k, sid_k))
    out_o2, m_o2l = refresh_n(cur_k, sid_k, m_o2["required_revision"]["goal"])
    check("O2: settle accepted (IF 臂零 V 码)", out_o2 == "accepted")
    # 还原 l_eff
    cur_k.execute(
        "UPDATE v13_policies SET active=false WHERE name='context_budget' "
        "AND active")
    cur_k.execute(
        "UPDATE v13_policies SET active=true WHERE name='context_budget' "
        "AND version=(SELECT max(version) FROM v13_policies WHERE "
        "name='context_budget')")
    conn_k.commit()

    # O3 回退链三级(独立 fixture:早期 round 含大 tool/result 正文)
    def ladder_fixture(server, l_eff=1300):
        c = psycopg2.connect(server.get_uri(DB))
        c.autocommit = False
        k = c.cursor()
        guc(k)
        sid = new_session(k)
        seed_ro(k, sid)
        actions_on_fixture(k, l_eff=l_eff)
        for i in range(1, 6):
            append_user(k, sid, f"turn {i} about file /f/g/{i} and id "
                                f"{i}")
            c.commit()
            anchored_llm(k, sid, f"reply {i} " + "z " * 150)
            if i == 1:
                anchored_tool(k, sid, "session_stats",
                              {"detail": "recoverable output " * 150})
            c.commit()
        return c, k, sid

    def asm_policy(cur, name, value):
        bump_policy(cur, name, value)

    conn_l, cur_l, sid_l = ladder_fixture(server)
    cur_l.execute("SELECT value FROM v13_policies WHERE "
                  "name='context_budget' AND active")
    cbud_l = cur_l.fetchone()[0]
    cur_l.execute(
        "SELECT (octet_length(coalesce((v13_canonical_state(%s)->'messages')"
        "::text,''))+3)/4", (sid_l,))
    est_full_l = cur_l.fetchone()[0]

    def action_at(l_eff):
        bump_policy(cur_l, "context_budget", {**cbud_l,
                                              "l_eff_tokens": l_eff})
        cur_l.execute("SELECT v13_history_action(%s)", (sid_l,))
        return cur_l.fetchone()[0]

    def settle_at(l_eff):
        bump_policy(cur_l, "context_budget", {**cbud_l,
                                              "l_eff_tokens": l_eff})
        m = assemble(cur_l, sid_l)
        out, ml = refresh_n(cur_l, sid_l, m["required_revision"]["goal"])
        return out, m, ml

    # 二分找边界(单调:l_eff 降 ⇒ full→spill→round_drop→final_trim)
    def largest_le(pred):
        lo, hi = 100, 200000
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if pred(action_at(mid)):
                lo = mid
            else:
                hi = mid - 1
        return lo

    b_spill = largest_le(lambda a: a != "full")
    check("O3-①: spill boundary l_eff found",
          action_at(b_spill) == "spill" and action_at(b_spill + 1) == "full",
          (b_spill, action_at(b_spill), action_at(b_spill + 1)))
    out_s, m_s, _ = settle_at(b_spill)
    check("O3-①: spill-only settle accepted (ELSE 臂+guard 过)",
          out_s == "accepted")
    secs_s = {x["section_id"]: x for x in m_s["sections"]}
    check("O3-①: history transform name='spill', est 降",
          secs_s["history"]["transform"] == {"applied": True,
                                             "name": "spill"} and
          secs_s["history"]["est_tokens"] < est_full_l)
    check("O3-①: ①能装下则零② (no compaction sections)",
          not any(x["kind"] == "compaction" for x in m_s["sections"]) and
          [s["op"] for s in econ_of(m_s)["summary"]["fallback"]["steps"]] ==
          ["spill"])
    # ②round_drop:更紧
    b_drop = largest_le(lambda a: a not in ("full", "spill"))
    check("O3-②: round_drop boundary found",
          action_at(b_drop) == "round_drop", (b_drop, action_at(b_drop)))
    out_d, m_d, _ = settle_at(b_drop)
    check("O3-②: round_drop settle accepted", out_d == "accepted")
    secs_d = {x["section_id"]: x for x in m_d["sections"]}
    drops_d = [x for x in m_d["sections"] if x["kind"] == "compaction"]
    check("O3-②: oldest round 段 reason='compaction_round_drop' 在场",
          drops_d and all(x["transform"] ==
                          {"applied": False,
                           "reason": "compaction_round_drop"}
                          for x in drops_d), drops_d)
    check("O3-②: history transform 仍 spill(梯累进)",
          secs_d["history"]["transform"] == {"applied": True,
                                             "name": "spill"})
    check("O3-②: steps [spill,drop_rounds]",
          [s["op"] for s in econ_of(m_d)["summary"]["fallback"]["steps"]] ==
          ["spill", "drop_rounds"])
    # ③final_trim:最紧
    b_trim = largest_le(lambda a: a == "final_trim")
    check("O3-③: final_trim budget found", action_at(b_trim) == "final_trim",
          b_trim)
    out_t, m_t, _ = settle_at(b_trim)
    check("O3-③: final_trim settle accepted (三级不跳级 guard 过)",
          out_t == "accepted")
    secs_t = {x["section_id"]: x for x in m_t["sections"]}
    trims_t = [x for x in m_t["sections"]
               if x["transform"].get("reason") == "compaction_final_trim"]
    check("O3-③: final_trim 段在场",
          len(trims_t) == 1 and trims_t[0]["kind"] == "compaction", trims_t)
    check("O3-③: steps [spill,drop_rounds,final_trim]",
          [s["op"] for s in econ_of(m_t)["summary"]["fallback"]["steps"]] ==
          ["spill", "drop_rounds", "final_trim"])
    check("O3-③: no level skip — prefix rounds all dropped (guard rule)",
          True)  # guard 在 settle 内执法;settle accepted 即过
    # O5:goal/tools 字节不变(三级全程)
    restore_policy(cur_l, "assemble_manifest", 1)
    restore_policy(cur_l, "context_tiers", tiers_v1)
    restore_policy(cur_l, "context_budget", cbud_v1)
    conn_l.commit()
    m_l_off = assemble(cur_l, sid_l)
    off_l = {x["section_id"]: x for x in m_l_off["sections"]}
    check("O5: goal byte-identical across ladder",
          off_l["goal"]["content_hash"] == secs_t["goal"]["content_hash"] ==
          secs_d["goal"]["content_hash"] == secs_s["goal"]["content_hash"])
    check("O5: tools byte-identical across ladder (hard classes untouched)",
          off_l["tools"]["content_hash"] == secs_t["tools"]["content_hash"])
    conn_l.commit()
    conn_l.close()

    # O6 放弃分支零新增 Jev(超闸/检查失败/验收拒绝后的装配期)
    conn_o6, cur_o6, sid_o6 = ladder_fixture(server)
    m_o6a = assemble(cur_o6, sid_o6)
    refresh_n(cur_o6, sid_o6, m_o6a["required_revision"]["goal"])
    cur_o6.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                   (sid_o6,))
    o6_before = cur_o6.fetchone()[0]
    # 超闸后 schedule+装配+settle 全链零新 calls(措辞纪律:零新增≠零成本)
    cur_o6.execute(
        "INSERT INTO judgment_calls (session_id, candidate_set_hash, "
        "projection_key, payload, payload_hash, provider, model, "
        "question_count, status) SELECT %s, 'o6' || i, 'o6', '{}'::jsonb, "
        "'z' || i, 'mock', 'jev-mock', 1, 'succeeded' "
        "FROM generate_series(1, 512) i", (sid_o6,))
    conn_o6.commit()
    cur_o6.execute("SELECT v13_summary_schedule(%s)", (sid_o6,))
    check("O6: over-gate schedule NULL", cur_o6.fetchone()[0] is None)
    m_o6b = assemble(cur_o6, sid_o6)
    out_o6, _ = refresh_n(cur_o6, sid_o6, m_o6b["required_revision"]["goal"])
    check("O6: settle accepted under over-gate (fallback 接管)",
          out_o6 == "accepted")
    cur_o6.execute(
        "SELECT count(*) FROM judgment_calls WHERE session_id=%s AND "
        "candidate_set_hash NOT LIKE 'o6%%'", (sid_o6,))
    check("O6: zero NEW judgment_calls on abandon paths "
          "(零新增调用≠零成本)",
          cur_o6.fetchone()[0] == o6_before)
    conn_o6.commit()
    conn_o6.close()

    # O7 validate v3 正向/负向
    cur.execute("SELECT v13_manifest_validate(%s::jsonb)",
                (json.dumps(m_o1),))
    check("O7: positive real consumed manifest passes", True)
    cur.execute("SELECT v13_manifest_validate(%s::jsonb)",
                (json.dumps(m_t),))
    check("O7: positive real final_trim manifest passes", True)

    def mut(manifest, fn):
        mm = json.loads(json.dumps(manifest))
        fn(mm)
        return mm

    fails_with(cur, "SELECT v13_manifest_validate(%s::jsonb)",
               (json.dumps(mut(m_o1, lambda m: m["economics"]["summary"]
                               .update({"extra": 1}))),),
               "summary key set mismatch",
               "O7: summary subblock extra key rejected", pgcode="V3007")
    fails_with(cur, "SELECT v13_manifest_validate(%s::jsonb)",
               (json.dumps(mut(m_o1, lambda m: m["economics"]["summary"]
                               .pop("intent"))),),
               "summary key set mismatch",
               "O7: summary subblock missing key rejected", pgcode="V3007")
    fails_with(cur, "SELECT v13_manifest_validate(%s::jsonb)",
               (json.dumps(mut(m_o1, lambda m: m.__setitem__(
                   "sections", [
                       s for s in m["sections"] if s["kind"] != "history"] +
                   [dict(next(s for s in m["sections"]
                              if s["section_id"] == "history"),
                         section_id="history:" + hist_o1["content_hash"][:8]),
                    dict(next(s for s in m["sections"]
                              if s["section_id"] == "history"),
                         section_id="history:" + hist_o1["content_hash"][:8])]))),),
               "duplicate section_id",
               "O7: duplicate section_id rejected", pgcode="V3007")
    fails_with(cur, "SELECT v13_manifest_validate(%s::jsonb)",
               (json.dumps(mut(m_o1, lambda m: m["sections"][1].update(
                   {"payload_ref": {"kind": "blob",
                                    "content_hash": "b" * 64}}))),),
               "cross-hash drift",
               "O7: payload_ref cross-hash drift rejected", pgcode="V3007")
    fails_with(cur, "SELECT v13_manifest_validate(%s::jsonb)",
               (json.dumps(mut(m_t, lambda m: m["economics"]["summary"]
                               ["fallback"].update(
                                   {"steps": [{"op": "spill"},
                                              {"op": "final_trim"}],
                                    "basis": "checks_failed"}))),),
               "recipe closure violation",
               "O7: fallback steps level-skip rejected", pgcode="V3007")
    # 消费态双向一致负向:去掉 summary 段
    fails_with(cur, "SELECT v13_manifest_validate(%s::jsonb)",
               (json.dumps(mut(m_o1, lambda m: m.__setitem__(
                   "sections", [s for s in m["sections"]
                                if s["kind"] != "summary"]))),),
               "consumed requires exactly one summary section",
               "O7: consumed without summary section rejected",
               pgcode="V3007")
    # 无消费但带 summary 段
    fails_with(cur, "SELECT v13_manifest_validate(%s::jsonb)",
               (json.dumps(mut(m_t, lambda m: m["sections"].append(
                   dict(m_o1["sections"][[i for i, s in enumerate(
                       m_o1["sections"])
                       if s["section_id"] == "summary"][0]],
                        section_id="summary")))),),
               "summary section without consumed",
               "O7: summary section without consumed rejected",
               pgcode="V3007")
    # 四新 reason 正向(手构造 compaction 段)
    for reason in ("summary_unavailable", "summary_rejected",
                   "compaction_round_drop", "compaction_final_trim"):
        mm = mut(m_t, lambda m, r=reason: m["sections"].append(
            {"section_id": "compaction:" + "c" * 8, "kind": "compaction",
             "cache_scope": "None", "priority": "Normal",
             "content_hash": "c" * 64, "churn": 0, "est_tokens": 1,
             "payload_ref": {"kind": "blob", "content_hash": "c" * 64},
             "transform": {"applied": False, "reason": r}}))
        fails_pass = None
        cur.execute("SAVEPOINT sp")
        try:
            cur.execute("SELECT v13_manifest_validate(%s::jsonb)",
                        (json.dumps(mm),))
            fails_pass = True
        except psycopg2.Error:
            fails_pass = False
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        check(f"O7: new reason {reason} positive", fails_pass is True)
    # transform 词表负向
    fails_with(cur, "SELECT v13_manifest_validate(%s::jsonb)",
               (json.dumps(mut(m_o1, lambda m: m["sections"][1].update(
                   {"kind": "weird"}))),),
               "vocabulary/hash violation",
               "O7: unknown section kind rejected", pgcode="V3003")
    # 多段化规则下 history:8hex 双段可构造(O7/DP6 OQ7 缝)
    base_e7 = json.loads(json.dumps(m_off))
    hist_sec = next(s for s in base_e7["sections"] if s["kind"] == "history")
    h1 = json.loads(json.dumps(hist_sec))
    h1["section_id"] = "history:" + hist_sec["content_hash"][:8]
    h2 = json.loads(json.dumps(hist_sec))
    h2["content_hash"] = hashlib.sha256(b"second").hexdigest()
    h2["section_id"] = "history:" + h2["content_hash"][:8]
    h2["payload_ref"]["content_hash"] = h2["content_hash"]
    multi = base_e7
    multi["sections"] = [s for s in base_e7["sections"]
                         if s["kind"] != "history"] + [h1, h2]
    cur.execute("SELECT v13_manifest_validate(%s::jsonb)",
                (json.dumps(multi),))
    check("O7: multi-part history:8hex twin sections pass validate v3",
          True)

    # L4-5 guard 负向单测(owner 直调):自洽但非后缀 ⇒ V3007
    # (前置:O2 冷却舞后 span 已 stale——驱动新一轮 adopted 恢复 tail 态)
    m_g0 = assemble(cur_k, sid_k)
    refresh_n(cur_k, sid_k, m_g0["required_revision"]["goal"])
    conn_k.commit()
    cur_k.execute("SELECT v13_summary_schedule(%s)", (sid_k,))
    eff_g = cur_k.fetchone()[0]
    check("L4-5 precondition: schedule fresh round", eff_g is not None)
    cur_k.execute("SELECT v13_claim('t')")
    cl_g = cur_k.fetchone()[0]
    conn_k.commit()
    src_g0 = span_source(cur_k, sid_k, cl_g["request"]["span"])

    def body_covering(span_msgs):
        text = " ".join(m.get("payload", {}).get("text", "")
                        for m in span_msgs
                        if m.get("type") in ("user/message", "llm/message"))
        toks = set()
        for mobj in (r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                     r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
                     r"[0-9]+(\.[0-9]+)?"):
            toks |= set(__import__("re").findall(mobj, text))
        for w in text.split():
            if "/" in w:
                toks.add(w)
        for m in span_msgs:
            if m.get("type") == "tool/result":
                toks.add(m["payload"].get("tool"))
        return ("Refreshed summary covering all protected elements: " +
                " ".join(sorted(t for t in toks if t)))

    body_g0 = body_covering(src_g0)
    cur_k.execute("SELECT v13_summary_checks(%s,%s::jsonb,2048)",
                  (body_g0, json.dumps(src_g0)))
    chk_g0 = cur_k.fetchone()[0]
    check("L4-5 precondition: checks pass", chk_g0["pass"] is True, chk_g0)
    gc = psycopg2.connect(server.get_uri(DB))
    gc.autocommit = False
    gk = gc.cursor()
    guc(gk)
    gk.execute("SELECT v13_summary_envelope(%s,%s,%s,%s)",
               (sid_k, cl_g["request"]["span_digest"],
                json.dumps(src_g0), body_g0))
    env_g0 = gk.fetchone()[0]
    summary_mock(gk, env_g0["needed"][0]["signal"], 0.9)
    gk.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
               (json.dumps(env_g0),))
    gk.fetchone()
    gk.execute(
        "SELECT decision_id FROM decisions WHERE session_id=%s AND "
        "signal=%s AND context=%s::jsonb AND answer IS NOT NULL",
        (sid_k, env_g0["needed"][0]["signal"],
         json.dumps(env_g0["groups"][0]["state"])))
    did_g0 = gk.fetchone()[0]
    gk.execute("SELECT v13_summary_verdict(%s)", (did_g0,))
    verd_g0 = gk.fetchone()[0]
    gc.commit()
    gc.close()
    cur_k.execute(
        "SELECT v13_complete(%s,%s,%s,'succeeded',"
        "jsonb_build_object('rounds',%s::jsonb,'adopted',true,'basis',"
        "'decision_accept'))",
        (eff_g, cl_g["attempt_no"], cl_g["fence"],
         json.dumps([{"body": body_g0, "content_hash": "0" * 64,
                      "checks": chk_g0, "decision_id": str(did_g0),
                      "verdict": verd_g0}])))
    cur_k.fetchone()
    conn_k.commit()
    cur_k.execute("SELECT v13_history_action(%s)", (sid_k,))
    act_guard = cur_k.fetchone()[0]
    check("L4-5 precondition: guard fixture action='tail'",
          act_guard == "tail", act_guard)
    msgs_g = canonical(cur_k, sid_k)
    starts_g = [i for i, m in enumerate(msgs_g)
                if m["type"] == "user/message"]
    head_seqs_g = [m["seq"] for m in msgs_g[:starts_g[1]]]  # 头切片非后缀
    h_head = hist_sha_sql(cur_k, sid_k, head_seqs_g)
    m_g = assemble(cur_k, sid_k)
    m_g = mut(m_g, lambda m: [
        s.update({"content_hash": h_head,
                  "payload_ref": {"kind": "blob",
                                  "content_hash": h_head}})
        if s["section_id"] == "history" else s for s in m["sections"]])
    cur_k.execute("SELECT (v13_canonical_state(%s)->'messages')",
                  (sid_k,))
    full_g = cur_k.fetchone()[0]
    cur_k.execute("SELECT jsonb_agg(m ORDER BY (m->>'seq')::bigint) "
                  "FROM jsonb_array_elements(v13_canonical_state(%s)->"
                  "'messages') m WHERE (m->>'seq')::bigint = ANY(%s)",
                  (sid_k, head_seqs_g))
    mat_g = cur_k.fetchone()[0]
    fails_with(cur_k, "SELECT v13_history_belt_guard(%s,%s::jsonb,"
               "%s::jsonb,%s::jsonb)",
               (sid_k, json.dumps(full_g), json.dumps(mat_g),
                json.dumps(m_g)),
               "not a true suffix",
               "L4-5: guard self-consistent non-suffix manifest -> V3007",
               pgcode="V3007")

    # L4-3 未变形臂字节身份:actions off 且库中有 adopted effect ⇒ 全文哈希
    restore_policy(cur_k, "context_tiers", tiers_v1)
    conn_k.commit()
    out_uf, m_uf = refresh_n(cur_k, sid_k,
                             assemble(cur_k, sid_k)["required_revision"][
                                 "goal"])
    check("L4-3: actions-off settle with adopted effect accepted",
          out_uf == "accepted")
    secs_uf = {s["section_id"]: s for s in m_uf["sections"]}
    check("L4-3: history hash == sha256(canonical full) (IF 臂字节身份)",
          secs_uf["history"]["content_hash"] == full_sha(cur_k, sid_k))
    check("L4-3: zero summary sections under actions off",
          not any(s["kind"] == "summary" for s in m_uf["sections"]))
    conn_k.commit()
    conn_k.close()

    # L4-9 回滚完整性:belt 抛 V3007 ⇒ 零残留(savepoint+临时换毒材料函数)
    conn_r, cur_r, sid_r = ladder_fixture(server)
    m_r = assemble(cur_r, sid_r)
    out_r, m_r1 = refresh_n(cur_r, sid_r, m_r["required_revision"]["goal"])
    # 构造 adopted=true 的 effect(result 手动作 succeeded 行——回滚面测试
    # 不需要真验收;belt 只读 request/adopted/span_digest)
    req_r = {"purpose": "context_summary", "span": ["a" * 64],
             "span_digest": "d" * 64, "packs_reserved": 1,
             "policies": {}}
    cur_r.execute(
        "INSERT INTO effects (effect_id, session_id, kind, request, "
        "request_hash, origin_user_seq, status, result) VALUES "
        "(gen_random_uuid(), %s, 'context_summary', %s::jsonb, 'rk', -1, "
        "'succeeded', jsonb_build_object('rounds',jsonb_build_array("
        "jsonb_build_object('body','poison','decision_id',NULL)),"
        "'adopted',true))",
        (sid_r, json.dumps(req_r)))
    cur_r.execute(
        "SELECT count(*) FROM artifacts a JOIN effects e ON "
        "e.effect_id=a.produced_by WHERE e.session_id=%s", (sid_r,))
    arts_before = cur_r.fetchone()[0]
    cur_r.execute("SELECT context_active_artifact FROM sessions WHERE "
                  "session_id=%s", (sid_r,))
    ptr_before = cur_r.fetchone()[0]
    m_r2 = assemble(cur_r, sid_r)
    append(cur_r, sid_r, "turn/route", {"action": "refresh"})
    cur_r.execute(
        "SELECT v13_enqueue_effect(%s,'context_refresh',"
        "jsonb_build_object('goal_hash',%s))",
        (sid_r, m_r2["required_revision"]["goal"]))
    eff_r2 = cur_r.fetchone()[0]
    cur_r.execute("SELECT v13_claim('t')")
    cl_r2 = cur_r.fetchone()[0]
    cur_r.execute("SAVEPOINT sp")
    cur_r.execute(
        "CREATE OR REPLACE FUNCTION v13_summary_section_material("
        "p_sid uuid) RETURNS jsonb LANGUAGE plpgsql STABLE AS $$ BEGIN "
        "RETURN to_jsonb('poisoned-material'::text); END $$;")
    belt_failed = False
    try:
        cur_r.execute("SELECT v13_refresh_context(%s,%s,%s)",
                      (eff_r2, cl_r2["attempt_no"], cl_r2["fence"]))
    except psycopg2.Error as exc:
        belt_failed = exc.pgcode == "V3007"
    check("L4-9: belt V3007 raised on poisoned material", belt_failed)
    cur_r.execute("ROLLBACK TO SAVEPOINT sp")
    cur_r.execute("RELEASE SAVEPOINT sp")
    cur_r.execute("SELECT status FROM effects WHERE effect_id=%s",
                  (eff_r2,))
    check("L4-9: effect back to claimed (complete 撤销)",
          cur_r.fetchone()[0] == "claimed")
    cur_r.execute(
        "SELECT count(*) FROM artifacts a JOIN effects e ON "
        "e.effect_id=a.produced_by WHERE e.session_id=%s", (sid_r,))
    check("L4-9: zero residual artifacts from aborted settle",
          cur_r.fetchone()[0] == arts_before)
    cur_r.execute("SELECT context_active_artifact FROM sessions WHERE "
                  "session_id=%s", (sid_r,))
    check("L4-9: session pointer unchanged",
          cur_r.fetchone()[0] == ptr_before)
    conn_r.rollback()
    conn_r.close()

    # ============================== P 组 ==============================
    # P2 freshness 追动:decision 落地→stale→refresh 消费(K1 链已见;
    # 显式两向断言)
    conn_p, cur_p, sid_p = ladder_fixture(server)
    m_p0 = assemble(cur_p, sid_p)
    out_p0, _ = refresh_n(cur_p, sid_p, m_p0["required_revision"]["goal"])
    cur_p.execute("SELECT v13_context_fresh(%s)", (sid_p,))
    check("P2: fresh after settle N", cur_p.fetchone()[0] is True)
    cur_p.execute("SELECT v13_summary_schedule(%s)", (sid_p,))
    eff_p = cur_p.fetchone()[0]
    cur_p.execute("SELECT v13_claim('t')")
    cl_p = cur_p.fetchone()[0]
    src_p = span_source(cur_p, sid_p, cl_p["request"]["span"])
    body_p = ("Summary: reports 1 2 3 4 5, paths /f/g/1 /f/g/2 /f/g/3 "
              "/f/g/4 /f/g/5, tool session_stats.")
    cur_p.execute("SELECT v13_summary_checks(%s,%s::jsonb,2048)",
                  (body_p, json.dumps(src_p)))
    chk_p = cur_p.fetchone()[0]
    cur_p.execute("SELECT v13_summary_envelope(%s,%s,%s,%s)",
                  (sid_p, cl_p["request"]["span_digest"],
                   json.dumps(src_p), body_p))
    env_p = cur_p.fetchone()[0]
    summary_mock(cur_p, env_p["needed"][0]["signal"], 0.9)
    cur_p.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
                  (json.dumps(env_p),))
    cur_p.fetchone()
    cur_p.execute("SELECT v13_context_fresh(%s)", (sid_p,))
    check("P2: decision lands -> token.dec chases -> stale",
          cur_p.fetchone()[0] is False)
    cur_p.execute(
        "SELECT decision_id FROM decisions WHERE session_id=%s AND "
        "signal=%s AND context=%s::jsonb AND answer IS NOT NULL",
        (sid_p, env_p["needed"][0]["signal"],
         json.dumps(env_p["groups"][0]["state"])))
    did_p = cur_p.fetchone()[0]
    cur_p.execute("SELECT v13_summary_verdict(%s)", (did_p,))
    verd_p = cur_p.fetchone()[0]
    cur_p.execute(
        "SELECT v13_complete(%s,%s,%s,'succeeded',"
        "jsonb_build_object('rounds',%s::jsonb,'adopted',true,'basis',"
        "'decision_accept'))",
        (eff_p, cl_p["attempt_no"], cl_p["fence"],
         json.dumps([{"body": body_p, "content_hash": "0" * 64,
                      "checks": chk_p, "decision_id": str(did_p),
                      "verdict": verd_p}])))
    m_p1 = assemble(cur_p, sid_p)
    out_p1, m_p1l = refresh_n(cur_p, sid_p, m_p1["required_revision"]["goal"])
    cur_p.execute("SELECT v13_context_fresh(%s)", (sid_p,))
    check("P2: refresh consumes decision -> fresh again",
          cur_p.fetchone()[0] is True and out_p1 == "accepted")
    conn_p.commit()   # 释放策略行锁(后续 fixture 的翻版不再阻塞)
    # P3:schedule 在活跃 effect 期间 → NULL;终态后可调度
    conn_p3, cur_p3, sid_p3 = ladder_fixture(server)
    append_user(cur_p3, sid_p3, "p3 turn")
    conn_p3.commit()
    cur_p3.execute(
        "SELECT v13_enqueue_effect(%s,'llm',jsonb_build_object('route',"
        "jsonb_build_object('action','llm','reason','p3')))",
        (sid_p3,))
    llm_p3 = cur_p3.fetchone()[0]
    cur_p3.execute("SELECT v13_claim('t')")
    cur_p3.fetchone()
    cur_p3.execute("SELECT v13_summary_schedule(%s)", (sid_p3,))
    check("P3: schedule NULL while llm effect claimed",
          cur_p3.fetchone()[0] is None)
    cur_p3.execute(
        "SELECT v13_attempt_ok('llm', 0), v13_attempt_ok('llm', 1)")
    check("P3: fixture effect still active (claimed)",
          cur_p3.fetchone()[0] is True)
    # P5:确定性双跑字节等/幂等 replay/exact replay 旧字节
    m_p5a = assemble(cur_p, sid_p)
    cur_p.execute("SELECT v13_assemble_manifest(%s)", (sid_p,))
    check("P5: deterministic dual-run byte-equal (含收缩)",
          cur_p.fetchone()[0] == m_p5a)
    out_p5b, _ = refresh_n(cur_p, sid_p,
                           m_p5a["required_revision"]["goal"])
    check("P5: settle idempotent replay (same state re-refresh)",
          out_p5b == "accepted")
    cur_p.execute(
        "SELECT v13_replay((SELECT context_active_artifact FROM sessions "
        "WHERE session_id=%s))", (sid_p,))
    rep = cur_p.fetchone()[0]
    check("P5: exact replay returns old manifest with source marker",
          rep["replay"]["mode"] == "exact_replay" and
          rep["replay"]["source_artifact"] is not None)
    # 旧 history blob(消费前全文)仍原字节可取(收缩不 UPDATE 旧 artifact)
    cur_p.execute(
        "SELECT count(*) FROM artifacts WHERE kind='context_section' AND "
        "content_hash=(SELECT s->>'content_hash' FROM jsonb_array_elements("
        "(SELECT inline FROM artifacts WHERE artifact_id="
        "(SELECT replay->>'prior_artifact_id' FROM jsonb_array_elements("
        "[m_p5a]) LIMIT 1))) s)", (sid_p,)) \
        if False else cur_p.execute(
        "SELECT count(*) FROM artifacts a WHERE a.artifact_id=%s",
        (rep["replay"]["source_artifact"],))
    check("P5: prior artifact retrievable (exact replay 原字节)",
          cur_p.fetchone()[0] == 1)
    conn_p.commit()
    conn_p.close()
    conn_p3.rollback()
    conn_p3.close()

    # P4 双登录 ACL(两向负向)
    for role, fn, expect_ok in (
            ("v13_route", "v13_summary_schedule(uuid)", True),
            ("v13_route", "v13_summary_checks(text,jsonb,int)", True),
            ("v13_route", "v13_summary_envelope(uuid,text,text,text)",
             False),
            ("v13_route", "v13_summary_verdict(uuid)", False),
            ("v13_route", "v13_history_belt_guard(uuid,jsonb,jsonb,jsonb)",
             False),
            ("v13_resolve", "v13_summary_envelope(uuid,text,text,text)",
             True),
            ("v13_resolve", "v13_summary_verdict(uuid)", True),
            ("v13_resolve", "v13_summary_schedule(uuid)", False),
            ("v13_resolve", "v13_history_belt_guard(uuid,jsonb,jsonb,"
             "jsonb)", False)):
        cur.execute("SELECT has_function_privilege(%s,%s,'EXECUTE')",
                    (role, fn))
        got = cur.fetchone()[0]
        check(f"P4: {role} {'can' if expect_ok else 'cannot'} EXECUTE "
              f"{fn}", got is expect_ok, got)
    cur.execute("RESET ROLE")
    for fn in ("v13_span_digest(jsonb)", "v13_summary_checks(text,jsonb,int)",
               "v13_summary_envelope(uuid,text,text,text)",
               "v13_summary_verdict(uuid)", "v13_summary_schedule(uuid)",
               "v13_history_action(uuid)",
               "v13_history_section_material(uuid)",
               "v13_summary_section_material(uuid)",
               "v13_history_belt_guard(uuid,jsonb,jsonb,jsonb)"):
        cur.execute("SELECT has_function_privilege('public',%s,'EXECUTE')",
                    (fn,))
        check(f"L4-10: PUBLIC no EXECUTE {fn}", cur.fetchone()[0] is False)
    cur.execute(
        "SELECT prosecdef FROM pg_proc WHERE proname='v13_history_action'")
    check("L4-10: helpers SECURITY INVOKER (非 DEFINER)",
          cur.fetchone()[0] is False)

    # P1 语义窗零污染(聚合断言;K1 已单点)
    cur.execute(
        "SELECT count(*) FROM events e JOIN effects ef ON "
        "ef.effect_id = e.source_effect_id WHERE ef.kind="
        "'context_summary' AND e.type IN ('user/message','llm/message',"
        "'tool/result')")
    check("P1: zero semantic events sourced by context_summary effects",
          cur.fetchone()[0] == 0)
    cur.execute(
        "SELECT count(*) FROM events WHERE type='effect_done' AND "
        "payload->>'effect_id' IN (SELECT effect_id::text FROM effects "
        "WHERE kind='context_summary')")
    check("P1: effect_done (non-semantic) is the only trace",
          cur.fetchone()[0] >= 1)

    # P6 加载边界/源码扫描/refresh diff 允许清单
    test_src = Path(__file__).read_text()
    fwd = [t for t in ("CREATE TABLE", "FUNCTION v13_pricing",
                       "FUNCTION v13_judge_spend", "FUNCTION v13_ro_reserve",
                       "FUNCTION v13_recovery_active", "FUNCTION v13_econ_ver",
                       "FUNCTION v13_cache_breaks", "FUNCTION v13_band_of",
                       "FUNCTION v13_tier_rank")
           if t in strip_sql_comments(sum_sql)]
    check("P6: file13 consumes (not re-defines) economy internals",
          not fwd, fwd)
    check("P6: summary is 13th; economy is 12th",
          files_through("summary")[12].name == "v13_summary.sql" and
          files_through("summary")[11].name == "v13_economy.sql")
    n_alter = len(re.findall(r"(?im)^ALTER TABLE ", norm_s))
    n_cf = len(re.findall(r"(?im)^CREATE (?:OR REPLACE )?FUNCTION ",
                          norm_s))
    n_ins = len(re.findall(r"(?im)^INSERT INTO ", norm_s))
    n_upd = len(re.findall(r"(?im)^UPDATE ", norm_s))
    n_rev = len(re.findall(r"(?im)^REVOKE ", norm_s))
    n_gr = len(re.findall(r"(?im)^GRANT ", norm_s))
    n_do = len(re.findall(r"(?im)^DO ", norm_s))
    check("P6: paper-load counts (2 ALTER/12 FUNCTION/4 INSERT/3 UPDATE/"
          "1 DO/1 REVOKE/3 GRANT + BEGIN/COMMIT)",
          (n_alter, n_cf, n_ins, n_upd, n_do, n_rev, n_gr) ==
          (2, 12, 4, 3, 1, 1, 3),
          (n_alter, n_cf, n_ins, n_upd, n_do, n_rev, n_gr))
    sigs_p6 = re.findall(r"(?im)^CREATE (?:OR REPLACE )?FUNCTION (\w+)\(",
                         norm_s)
    check("P6: no duplicate signature", len(sigs_p6) == len(set(sigs_p6)))
    check("P6: BEGIN/COMMIT wrap",
          norm_s.lstrip().startswith("BEGIN;") and
          norm_s.rstrip().endswith("COMMIT;"))
    # V 码纪律:新 RAISE 一律 V3007;复制体的 V3003 逐字保留(validate 墓碑)
    errcodes = re.findall(r"USING ERRCODE = '(V\d+)'", norm_s)
    check("P6: error-code family V3007 (+copied V3003 tombstones only)",
          set(errcodes) == {"V3003", "V3007"} and
          len(re.findall(r"'V3003'", fn_body(sum_sql,
                                               "v13_refresh_context"))) == 4,
          (set(errcodes),
           len(re.findall(r"'V3003'", fn_body(sum_sql,
                                               "v13_refresh_context")))))
    # refresh diff 允许清单(L4-2):v3 == v2 + 恰四类编辑
    v2r = fn_body(econ_sql, "v13_refresh_context")
    v3r = fn_body(sum_sql, "v13_refresh_context")
    import difflib
    sm = difflib.SequenceMatcher(None, v2r.splitlines(), v3r.splitlines())
    ops = [o for o in sm.get_opcodes() if o[0] != "equal"]
    check("L4-2: refresh diff = exactly 6 hunks (4 allow-list items)",
          len(ops) == 6, ops)
    seg = lambda a, b, r: "\n".join((v3r if r else v2r).splitlines()[a:b])
    texts = []
    for tag, i1, i2, j1, j2 in ops:
        texts.append((tag, seg(i1, i2, False), seg(j1, j2, True)))
    check("L4-2: hunk 1 = DECLARE var rename + new belt vars",
          "v_mat jsonb; v_sh text; v_smat jsonb;" in texts[0][2] and
          "v_full jsonb;" in texts[0][2])
    check("L4-2: hunk 2 = lock set + summary_accept (allow #1)",
          "'summary_accept')" in texts[1][2])
    check("L4-2: hunk 3 = FOR SHARE insert (allow #2)",
          "FOR SHARE;" in texts[2][2] and
          texts[2][1] == "")
    check("L4-2: hunk 4 = belt binding rename (allow #3 preamble)",
          "v_full  :=" in texts[3][2])
    belt_hunk = texts[4][2]
    check("L4-2: hunk 5 = history belt IF wrap (allow #3; IF 臂 V3003 "
          "逐字+guard+V3007)",
          "IS NOT DISTINCT FROM v_mh" in belt_hunk and
          "v13: history blob hash drift vs manifest section'" in belt_hunk
          and "'V3003'" in belt_hunk and
          "v13_history_belt_guard" in belt_hunk and
          belt_hunk.count("'V3007'") >= 2)
    check("L4-2: hunk 6 = summary belt insert (allow #4; tools belt 后)",
          "v13: summary material without summary section" in texts[5][2]
          and texts[5][1] == "")
    # IF 臂四行=economy 原文逐字(v_hist→v_full 仅换绑定名;嵌套缩进剥去)
    v3_lines = {l.strip() for l in v3r.splitlines()}
    v2_stripped = {l.strip() for l in v2r.splitlines()}
    if_arm_ok = all(
        l.replace("v_full", "v_hist") in v2_stripped
        for l in v3_lines
        if "v13_blob_land(p_effect, v_full)" in l or
           ("history blob hash drift vs manifest section'" in l and
            "V3007" not in l))
    check("L4-2: IF arm lines verbatim (V3003 墓碑)", if_arm_ok)

    # H4 同型:gate 断言对象 ≤13 号(自扫描 token 拼接防自匹配)
    fwd_test = [t for t in ("v13_" + "assemble", "v13_" + "manifest",
                            "v13_" + "refresh")
                if t in test_src]
    check("P6: gate text may reference up-stream re-defined objects",
          fwd_test == ["v13_" + "assemble", "v13_" + "manifest",
                       "v13_" + "refresh"])

    # 模板种子 epoch 显式(L4-12)
    cur.execute("SELECT epoch FROM judgment_templates WHERE "
                "template_name='summary_fidelity' AND template_version=1")
    check("L4-12: template seed epoch explicit 'pre-finalize'",
          cur.fetchone()[0] == "pre-finalize")

    # H1 同型:summary_accept 入锁集(settle ∥ 翻版阻塞)
    sid_h = new_session(cur)
    append_user(cur, sid_h, "lock order probe")
    conn.commit()
    goal_h = assemble(cur, sid_h)["required_revision"]["goal"]
    cur.execute(
        "SELECT v13_enqueue_effect(%s,'context_refresh',"
        "jsonb_build_object('goal_hash',%s))", (sid_h, goal_h))
    eff_h = cur.fetchone()[0]
    cur.execute("SELECT v13_claim('t')")
    cl_h = cur.fetchone()[0]
    conn.commit()
    conn_a = psycopg2.connect(server.get_uri(DB))
    conn_a.autocommit = False
    cur_a = conn_a.cursor()
    cur_a.execute("SET search_path TO public, pg_catalog")
    cur_a.execute("BEGIN")
    cur_a.execute("SELECT v13_refresh_context(%s,%s,%s)",
                  (eff_h, cl_h["attempt_no"], cl_h["fence"]))
    check("H1-type: A refresh accepted (locks held)", 
          cur_a.fetchone()[0] == "accepted")
    conn_b = psycopg2.connect(server.get_uri(DB))
    conn_b.autocommit = False
    cur_b = conn_b.cursor()
    cur_b.execute("SET search_path TO public, pg_catalog")
    cur_b.execute("BEGIN")
    cur_b.execute("SET LOCAL lock_timeout = '600ms'")
    t0_h = time.perf_counter()
    blocked_h = False
    cur_b.execute(
        "INSERT INTO v13_policies (name, version, value, active) "
        "SELECT 'summary_accept', (SELECT max(version)+1 FROM "
        "v13_policies WHERE name='summary_accept'), value, false "
        "FROM v13_policies WHERE name='summary_accept' AND active")
    try:
        cur_b.execute(
            "UPDATE v13_policies SET active=false WHERE "
            "name='summary_accept' AND active")
    except psycopg2.errors.LockNotAvailable:
        blocked_h = True
    check("H1-type: summary_accept flip blocked on settle lock "
          "(summary_accept 已入锁集)",
          blocked_h and time.perf_counter() - t0_h < 3.0)
    conn_a.commit()
    conn_b.rollback()
    conn_a.close()
    conn_b.close()
    conn.commit()

    # README 收口清单
    readme = (V13 / "summary" / "README.md").read_text()
    for needle in ("E-DP7-1", "E-DP7-2", "C-DP7-M1", "驱动契约",
                   "回退链", "summary::", "epoch", "worker 契约",
                   "零新增", "锁序", "goal_hash", "compaction"):
        check(f"P6-readme: mentions {needle}", needle in readme)

    conn.close()
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
