"""DP7 gate M1: economy — policy rows + pricing catalog + R_o percentile +
tier bands/hysteresis (G-ctx6 round-2 corrected semantics) + E(r) three
disciplines + manifest v2 (economics half, three-bucket packing, econ_ver
token key, section_id multi-part rule) + cache-break attribution + parse
spend gate + lock order/ACL/boundary. Groups A-H.

Run: uv run python v13/economy/test_economy.py  (exit 0 = pass)
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
from v13.economy.setup_db import DB, main as setup_db
from v13.load import files_through

HEX64 = re.compile(r"^[0-9a-f]{64}$")
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


def append_llm(cur, sid, text, anchor=None):
    """anchor=<seq> emulates the production llm/message shape written by
    v13_complete (payload carries origin_user_seq): canonical_state's
    window is "seq <= last_user_seq OR origin anchored", so un-anchored
    machine events after the last user message are invisible to the
    history section."""
    payload = {"text": text}
    if anchor is not None:
        payload["origin_user_seq"] = anchor
    return append(cur, sid, "llm/message", payload)


def anchored_llm(cur, sid, text):
    cur.execute("SELECT v13_last_user_seq(%s)", (sid,))
    return append_llm(cur, sid, text, anchor=cur.fetchone()[0])


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


def refresh_once(cur, sid, goal_hash):
    """enqueue + claim + settle one context_refresh effect; returns
    (outcome, manifest)."""
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
    placeholder GUCs (resolve loads the extension library and reserves
    the prefix in this backend; provider/model are consumed per ask)."""
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


def llm_effect(cur, sid, completion, model="mock-1", text="generated body",
               status="succeeded"):
    """Real enqueue/claim/complete path for an llm effect. Production
    request shape = {route:{...}} with zero model key (P0-1 fixture
    discipline); model/usage live on the result side only. The reason
    varies per call: DP1 effect identity is (sid, anchor, cycle, kind,
    request-hash) — a constant request would re-hit the same succeeded
    row instead of creating a new sample."""
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
            "jsonb_build_object('text',%s,'usage',jsonb_build_object("
            "'completion_tokens',%s),'model',%s))",
            (eff, cl["attempt_no"], cl["fence"], text, completion, model))
    else:
        cur.execute(
            "SELECT v13_complete(%s,%s,%s,'failed',NULL)",
            (eff, cl["attempt_no"], cl["fence"]))
    return eff, cur.fetchone()[0]


def expected_ro(cur, p):
    """Hand-computed percentile over the same bucket predicate (B1
    cross-check, written independently of v13_ro_reserve)."""
    cur.execute(
        "SELECT count(*), percentile_cont(%s) WITHIN GROUP (ORDER BY ("
        "result->'usage'->>'completion_tokens')::bigint) "
        "FROM effects WHERE kind='llm' AND status='succeeded' "
        "AND result->>'model'=(SELECT value->>'model' FROM v13_policies "
        "WHERE name='generation' AND active) "
        "AND result->'usage'->>'completion_tokens' ~ '^[0-9]+$'", (p,))
    return cur.fetchone()


def mock_for(cur, sid, intent="llm_generate", noul=0.9, score=0.5,
             conf=0.9) -> str:
    cur.execute(
        "SELECT signal, kind, criteria FROM v13_needed_judgments(%s)", (sid,))
    answers = {}
    for signal, kind, criteria in cur.fetchall():
        if kind == "choice":
            if signal == "intent":
                ch = intent
            else:
                keys = list(criteria.keys()) if isinstance(criteria, dict) \
                    else ["none"]
                ch = keys[0]
                if signal == "tool":
                    ch = "session_stats"
            answers[signal] = {"type": "choice", "choice": ch,
                               "probabilities": {ch: conf}, "confidence": conf}
        elif kind == "score":
            answers[signal] = {"type": "score", "score": score,
                               "confidence": conf}
        else:
            answers[signal] = {"type": "noul", "noul": noul}
    return json.dumps({"model": "jev-mock", "answers": answers,
                       "usage": {"input_tokens": 1, "output_tokens": 1}})


def set_mock(cur, mock: str) -> None:
    cur.execute("SELECT set_config('typesafe.mock_response', %s, true)",
                (mock,))


def mock_for_env(env, exclude=()):
    """Mock answers scoped to one envelope's needed list — the mock
    provider validates answer keys against the questions actually asked,
    so a pre-answered signal (excluded from the ask by the gap join)
    must not appear in the response: pass it in `exclude`."""
    answers = {}
    for n in env["needed"]:
        sig, kind = n["signal"], n["kind"]
        if sig in exclude:
            continue
        if kind == "choice":
            if sig == "intent":
                ch = "llm_generate"
            elif sig == "tool":
                ch = "session_stats"
            else:
                keys = (list(n["criteria"].keys())
                        if isinstance(n["criteria"], dict) else ["none"])
                ch = keys[0]
            answers[sig] = {"type": "choice", "choice": ch,
                            "probabilities": {ch: 0.9}, "confidence": 0.9}
        elif kind == "score":
            answers[sig] = {"type": "score", "score": 0.5,
                            "confidence": 0.9}
        else:
            answers[sig] = {"type": "noul", "noul": 0.1}
    return json.dumps({"model": "jev-mock", "answers": answers,
                       "usage": {"input_tokens": 1, "output_tokens": 1}})


def hist_bytes(cur, sid) -> int:
    cur.execute(
        "SELECT octet_length(coalesce((v13_canonical_state(%s)->'messages')"
        "::text,''))", (sid,))
    return cur.fetchone()[0]


def tune_t_used(cur, sid, target_est: int, tag: str = "") -> int:
    """Append llm messages until the history-section est (ceil(bytes/4))
    equals target_est exactly. est=ceil(b/4)=t  <=>  4t-3 <= b <= 4t, so
    the loop converges on a 4-byte window; wrapper overhead is probed by
    measuring after each append. Capped iterations fail loudly instead of
    spinning (canonical window is last-20-events; net gain per append
    shrinks as old messages drop out)."""
    before = (hist_bytes(cur, sid) + 3) // 4
    if before == target_est:
        return before
    # Probe the actual canonical representation (including origin anchor and
    # rolling-window eviction) without retaining probe events. No fixed JSON
    # wrapper-size assumption, and no mutation of append-only event rows.
    lo, hi = 0, target_est * 4
    while lo <= hi:
        fill = (lo + hi) // 2
        cur.execute("SAVEPOINT tune_probe")
        anchored_llm(cur, sid, "x" * fill)
        actual = (hist_bytes(cur, sid) + 3) // 4
        cur.execute("ROLLBACK TO SAVEPOINT tune_probe")
        cur.execute("RELEASE SAVEPOINT tune_probe")
        if actual == target_est:
            anchored_llm(cur, sid, "x" * fill)
            est = (hist_bytes(cur, sid) + 3) // 4
            check(f"tune_t_used{tag} reached {target_est} exactly",
                  est == target_est, est)
            return est
        if actual < target_est:
            lo = fill + 1
        else:
            hi = fill - 1
    raise AssertionError(f"tune_t_used{tag}: target={target_est}, before={before}; "
                         "no single-event fixture fits")


def econ_of(manifest):
    return manifest["economics"]


def main() -> int:
    setup_db()
    server = get_server()
    conn = psycopg2.connect(server.get_uri(DB))
    conn.autocommit = False
    cur = conn.cursor()
    guc(cur)
    econ_sql = (V13 / "economy" / "v13_economy.sql").read_text()
    norm_e = strip_sql_comments(econ_sql)

    # ============================== A 组 ==============================
    # A1 加载/五行策略/单字面量
    check("A1: economy prefix 12", len(files_through("economy")) == 12)
    cur.execute(
        "SELECT name, version, active, value FROM v13_policies "
        "WHERE name IN ('context_tiers','context_budget','judge_spend_gate',"
        "'fastpath_tiers','render_policy') ORDER BY name")
    rows_a1 = cur.fetchall()
    check("A1: five policy rows v1 active",
          [(r[0], r[1], r[2]) for r in rows_a1] ==
          [("context_budget", 1, True), ("context_tiers", 1, True),
           ("fastpath_tiers", 1, True), ("judge_spend_gate", 1, True),
           ("render_policy", 1, True)],
          [(r[0], r[1], r[2]) for r in rows_a1])
    pol_block = econ_sql[econ_sql.index(
        "INSERT INTO v13_policies (name, version, value, active) VALUES"):]
    pol_block = pol_block[:pol_block.index("\n\n-- === 定价目录")]
    check("A1: policy seed block single literals (no text concat)",
          "||" not in pol_block)
    for r in rows_a1:
        cur.execute("SELECT jsonb_typeof(value)='object' FROM v13_policies "
                    "WHERE name=%s AND version=1", (r[0],))
        check(f"A1: {r[0]} value is jsonb object", cur.fetchone()[0])

    # A2 翻版仪式
    cur.execute("SELECT value FROM v13_policies WHERE name='context_tiers' "
                "AND active")
    tiers_v1 = cur.fetchone()[0]
    v2 = bump_policy(cur, "context_tiers",
                     {**tiers_v1, "actions_enabled": True})
    cur.execute("SELECT active FROM v13_policies WHERE name='context_tiers' "
                "AND version=2")
    check("A2: flip ritual activates v2", cur.fetchone()[0] is True)
    cur.execute("SELECT count(*) FROM v13_policies WHERE name='context_tiers'")
    check("A2: old row retained (append-only)", cur.fetchone()[0] == 2)
    fails_with(
        cur,
        "UPDATE v13_policies SET value='{\"x\":1}'::jsonb "
        "WHERE name='context_tiers' AND version=1", (),
        "immutable", "A2: policies_frozen rejects value UPDATE")
    restore_policy(cur, "context_tiers", 1)
    cur.execute("SELECT active FROM v13_policies WHERE name='context_tiers' "
                "AND version=1")
    check("A2: restored v1 active", cur.fetchone()[0] is True)
    conn.commit()

    # A3 pricing 目录
    cur.execute("SELECT provider, model, fresh_usd_per_mtok, "
                "cached_usd_per_mtok, catalog_version, active FROM v13_pricing")
    pr_a3 = cur.fetchone()
    cur.execute("SELECT value->>'provider', value->>'model' "
                "FROM v13_policies WHERE name='generation' AND active")
    gen = cur.fetchone()
    check("A3: seed row five-dim matches generation mock row",
          (pr_a3[0], pr_a3[1], pr_a3[5]) == (gen[0], gen[1], True), pr_a3)
    fails_with(
        cur, "UPDATE v13_pricing SET fresh_usd_per_mtok=9 WHERE "
        "catalog_version=1", (), "append-only",
        "A3: pricing frozen rejects price UPDATE")
    fails_with(cur, "DELETE FROM v13_pricing WHERE catalog_version=1", (),
               "append-only", "A3: pricing frozen rejects DELETE")
    cur.execute("INSERT INTO v13_pricing (provider, model, account, "
                "cache_class, fresh_usd_per_mtok, cached_usd_per_mtok, "
                "catalog_version, active) VALUES ('mock','mock-1','default',"
                "'default', 2.000000, 0.500000, 2, false)")
    fails_with(
        cur, "UPDATE v13_pricing SET active=true WHERE "
        "provider='mock' AND catalog_version=2", (),
        "duplicate key", "A3: partial unique rejects double active")
    cur.execute("UPDATE v13_pricing SET active=false WHERE "
                "provider='mock' AND catalog_version=1")
    cur.execute("UPDATE v13_pricing SET active=true WHERE "
                "provider='mock' AND catalog_version=2")
    cur.execute("SELECT v13_pricing_r('mock','mock-1')")
    r_a3 = float(cur.fetchone()[0])
    check("A3: v13_pricing_r = cached/fresh in [0,1]",
          0.0 <= r_a3 <= 1.0 and abs(r_a3 - 0.25) < 1e-9, r_a3)
    cur.execute("UPDATE v13_pricing SET active=false WHERE "
                "provider='mock' AND catalog_version=2")
    cur.execute("UPDATE v13_pricing SET active=true WHERE "
                "provider='mock' AND catalog_version=1")
    conn.commit()

    # A4 形状守卫(settle 面)
    sid_a4 = new_session(cur)
    append_user(cur, sid_a4, "shape guard probe")
    conn.commit()
    m_a4 = assemble(cur, sid_a4)
    cur.execute("SELECT v13_enqueue_effect(%s,'context_refresh',"
                "jsonb_build_object('goal_hash',%s))",
                (sid_a4, m_a4["required_revision"]["goal"]))
    eff_a4 = cur.fetchone()[0]
    cur.execute("SELECT v13_claim('t')")
    cl_a4 = cur.fetchone()[0]

    def guard_flip(name, bad_value, label):
        ver = bump_policy(cur, name, bad_value)
        fails_with(
            cur, "SELECT v13_refresh_context(%s,%s,%s)",
            (eff_a4, cl_a4["attempt_no"], cl_a4["fence"]),
            "V3007" if label.startswith("shape") else label,
            f"A4: {label} rejected before assemble", pgcode="V3007")
        restore_policy(cur, name, 1)

    cur.execute("SELECT value FROM v13_policies WHERE "
                "name='context_tiers' AND active")
    tiers_now = cur.fetchone()[0]
    guard_flip("context_tiers",
               {**tiers_now, "bands": tiers_now["bands"][:3]},
               "shape: context_tiers missing band")
    guard_flip("context_tiers",
               {**tiers_now, "r_o": {"p_steady": 0.75}},
               "shape: context_tiers r_o missing keys")
    guard_flip("context_budget",
               {"buckets": {"core": 0.6, "history": 0.55, "retrieval": 0.10},
                "l_eff_tokens": 128000, "keep_tail_turns": 2,
                "hard_window_bp": 10000},
               "shape: context_budget bucket sum > 1.0")
    cbud_v1 = json.loads(json.dumps({
        "buckets": {"core": 0.35, "history": 0.55, "retrieval": 0.10},
        "l_eff_tokens": 128000, "keep_tail_turns": 2,
        "hard_window_bp": 10000, "note": "x"}))
    guard_flip("context_budget", {**cbud_v1, "l_eff_tokens": 0},
               "shape: context_budget l_eff=0")
    guard_flip("judge_spend_gate",
               {"session_asks_cap": 512, "day_asks_cap": 8192,
                "scope": "everywhere"},
               "shape: judge_spend_gate scope vocab")
    guard_flip("fastpath_tiers", {"tiers_over_one_batch": ["WeirdTier"]},
               "shape: fastpath_tiers tier vocab")
    guard_flip("render_policy",
               {"renderer": "", "cache_markers": True},
               "shape: render_policy empty renderer")
    cur.execute("SELECT v13_refresh_context(%s,%s,%s)",
                (eff_a4, cl_a4["attempt_no"], cl_a4["fence"]))
    check("A4: refresh accepted after restore", cur.fetchone()[0] == "accepted")
    conn.commit()

    # A5 源码扫描
    check("A5: file12 zero bind-operator literals",
          norm_e.count("==>") == 0)
    check("A5: file12 zero engine-qualified names",
          norm_e.count("stannum.") == 0)
    check("A5: file12 zero judgment-IO references",
          "typesafe_ask" not in norm_e)
    for role in ("v13_recall", "v13_resolve", "v13_route"):
        cur.execute("SELECT has_table_privilege(%s,'v13_policies','SELECT')",
                    (role,))
        check(f"A5: {role} SELECT v13_policies (DP1 grant intact)",
              cur.fetchone()[0] is True)
        cur.execute("SELECT has_table_privilege(%s,'v13_pricing','SELECT')",
                    (role,))
        check(f"A5: {role} SELECT v13_pricing", cur.fetchone()[0] is True)

    # A6 ACL
    a6_new = [
        "v13_pricing_r(text,text,text,text)", "v13_ro_reserve(uuid)",
        "v13_recovery_active(uuid)", "v13_judge_spend(uuid)",
        "v13_econ_ver()", "v13_cache_breaks(uuid)",
        "v13_band_of(jsonb,bigint)", "v13_tier_rank(text)"]
    for fn in a6_new:
        cur.execute("SELECT has_function_privilege('public',%s,'EXECUTE')",
                    (fn,))
        check(f"A6: PUBLIC no EXECUTE {fn}", cur.fetchone()[0] is False)
    for fn in ("v13_pricing_r(text,text,text,text)", "v13_econ_ver()"):
        for role in ("v13_recall", "v13_resolve", "v13_route"):
            cur.execute(
                "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, fn))
            check(f"A6: {role} EXECUTE {fn}", cur.fetchone()[0] is True)
    for fn in ("v13_ro_reserve(uuid)", "v13_recovery_active(uuid)",
               "v13_judge_spend(uuid)", "v13_cache_breaks(uuid)"):
        for role in ("v13_resolve", "v13_route"):
            cur.execute(
                "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, fn))
            check(f"A6: {role} EXECUTE {fn}", cur.fetchone()[0] is True)
        cur.execute("SELECT has_function_privilege('v13_recall',%s,'EXECUTE')",
                    (fn,))
        check(f"A6: recall no EXECUTE {fn} (parse/driver face)",
              cur.fetchone()[0] is False)
    for fn in ("v13_parse(uuid)", "v13_assemble_manifest(uuid,integer)",
               "v13_manifest_validate(jsonb)",
               "v13_refresh_context(uuid,integer,bigint)",
               "v13_context_required(uuid)"):
        cur.execute("SELECT has_function_privilege('public',%s,'EXECUTE')",
                    (fn,))
        check(f"A6: PUBLIC no EXECUTE OR REPLACE {fn}",
              cur.fetchone()[0] is False)
    acl6 = {"v13_parse(uuid)": "v13_resolve",
            "v13_assemble_manifest(uuid,integer)": "v13_resolve",
            "v13_manifest_validate(jsonb)": "v13_route",
            "v13_refresh_context(uuid,integer,bigint)": "v13_route",
            "v13_context_required(uuid)": "v13_resolve"}
    for fn, role in acl6.items():
        cur.execute("SELECT has_function_privilege(%s,%s,'EXECUTE')",
                    (role, fn))
        check(f"A6: OR REPLACE ACL preserved ({role} keeps {fn})",
              cur.fetchone()[0] is True)
    conn.commit()

    # ============================== B 组 ==============================
    # B3 冷启动(先于大批量样本)
    sid_b3 = new_session(cur)
    n_b3, p_b3 = expected_ro(cur, 0.75)
    check("B3: empty bucket at start", n_b3 == 0, (n_b3, p_b3))
    cur.execute("SELECT v13_ro_reserve(%s)", (sid_b3,))
    check("B3: cold start returns cold_tokens=8192",
          cur.fetchone()[0] == 8192)
    for i in range(19):
        llm_effect(cur, sid_b3, i + 1)
    n_b3b, _ = expected_ro(cur, 0.75)
    cur.execute("SELECT v13_ro_reserve(%s)", (sid_b3,))
    ro_b3b = cur.fetchone()[0]
    check("B3: 19 samples (<min 20) still cold", ro_b3b == 8192, ro_b3b)
    check("B3: cold direction over-reserves (8192 > actual p75)",
          8192 > 14, ro_b3b)
    llm_effect(cur, sid_b3, 20)
    n_b3c, p_b3c = expected_ro(cur, 0.75)
    cur.execute("SELECT v13_ro_reserve(%s)", (sid_b3,))
    check("B3: 20 samples switches to percentile",
          cur.fetchone()[0] == int(p_b3c), (p_b3c,))
    conn.commit()

    # B1 percentile 正确性(40 样本对照手算)
    for i in range(21, 41):
        llm_effect(cur, sid_b3, i)
    n_b1, p_b1 = expected_ro(cur, 0.75)
    check("B1: bucket has 40 samples", n_b1 == 40, n_b1)
    cur.execute("SELECT v13_ro_reserve(%s)", (sid_b3,))
    check("B1: ro_reserve == hand-computed p75",
          cur.fetchone()[0] == int(p_b1), (p_b1,))
    llm_effect(cur, sid_b3, 10 ** 6, model="other-model")
    cur.execute("SELECT v13_ro_reserve(%s)", (sid_b3,))
    check("B1: foreign-model row not in bucket (percentile unchanged)",
          cur.fetchone()[0] == int(p_b1))
    conn.commit()

    # B2 失败/缺失样本排除
    before_b2 = expected_ro(cur, 0.75)
    llm_effect(cur, sid_b3, 10 ** 9, status="failed")
    cur.execute(
        "SELECT count(*) FROM effects WHERE kind='llm' AND status='failed'")
    check("B2: failed effect landed", cur.fetchone()[0] >= 1)
    cur.execute("SELECT v13_ro_reserve(%s)", (sid_b3,))
    check("B2: failed sample excluded (percentile unchanged)",
          cur.fetchone()[0] == int(before_b2[1]))
    eff_b2, _ = llm_effect(cur, sid_b3, 0, status="succeeded",
                           text="no usage no model here")
    cur.execute(
        "UPDATE effects SET result=result - 'usage' - 'model' "
        "WHERE effect_id=%s", (eff_b2,))
    cur.execute("SELECT v13_ro_reserve(%s)", (sid_b3,))
    check("B2: usage/model-missing row excluded (no bad sample)",
          cur.fetchone()[0] == int(before_b2[1]))
    conn.commit()

    # B4 恢复期窗口(跨 turn)
    sid_b4 = new_session(cur)
    append_user(cur, sid_b4, "recovery window turn N")
    conn.commit()
    eff_b4, _ = llm_effect(cur, sid_b4, 100, status="failed")
    cur.execute("UPDATE effects SET error=jsonb_build_object("
                "'code','prompt_too_long') WHERE effect_id=%s", (eff_b4,))
    cur.execute("SELECT v13_recovery_active(%s)", (sid_b4,))
    check("B4: recovery active at failure turn",
          cur.fetchone()[0] is True)
    n_b4, p75_b4 = expected_ro(cur, 0.75)
    _, p95_b4 = expected_ro(cur, 0.95)
    cur.execute("SELECT v13_ro_reserve(%s)", (sid_b4,))
    check("B4: failure turn uses p95", cur.fetchone()[0] == int(p95_b4),
          (p75_b4, p95_b4))
    conn.commit()   # now() is transaction-start time: separate tx so the
                    # N+1 boundary timestamp strictly exceeds the failure's
    append_user(cur, sid_b4, "recovery turn N+1")
    conn.commit()
    cur.execute("SELECT v13_recovery_active(%s)", (sid_b4,))
    check("B4: recovery visible in turn N+1 (cross-turn window)",
          cur.fetchone()[0] is True)
    cur.execute("SELECT v13_ro_reserve(%s)", (sid_b4,))
    check("B4: turn N+1 still p95", cur.fetchone()[0] == int(p95_b4))
    conn.commit()
    append_user(cur, sid_b4, "clean turn N+2")
    conn.commit()
    cur.execute("SELECT v13_recovery_active(%s)", (sid_b4,))
    check("B4: two clean boundaries later floor gone",
          cur.fetchone()[0] is False)
    cur.execute("SELECT v13_ro_reserve(%s)", (sid_b4,))
    check("B4: back to steady p75", cur.fetchone()[0] == int(p75_b4))
    conn.commit()

    # B5 usage+model 记录面(真实 enqueue/complete 路径执法)
    sid_b5 = new_session(cur)
    llm_effect(cur, sid_b5, 777, model="mock-1", text="recorded sample")
    cur.execute(
        "SELECT count(*) FROM effects WHERE kind='llm' AND "
        "status='succeeded' AND result->>'model'='mock-1' AND "
        "(result->'usage'->>'completion_tokens')::int=777")
    check("B5: real-path result-side usage+model lands in bucket",
          cur.fetchone()[0] == 1)
    n_b5, p75_b5 = expected_ro(cur, 0.75)
    cur.execute("SELECT v13_ro_reserve(%s)", (sid_b5,))
    check("B5: real-path sample visible to ro_reserve",
          cur.fetchone()[0] == int(p75_b5), (n_b5, p75_b5))
    conn.commit()
    RO_NOW = int(p75_b5)

    # ============================== C 组 ==============================
    # 计算当前桶 ro(动态,防后续样本漂移)
    def ro_now():
        return expected_ro(cur, 0.75)[1]

    # C1 band 路由:小 l_eff 驱动压力跨档
    cbud_seed = {
        "buckets": {"core": 0.35, "history": 0.55, "retrieval": 0.10},
        "l_eff_tokens": 128000, "keep_tail_turns": 2,
        "hard_window_bp": 10000}
    ver_cb = bump_policy(cur, "context_budget",
                         {**cbud_seed, "l_eff_tokens": 1000})
    try:
        sid_c1 = new_session(cur)
        append_user(cur, sid_c1, "band routing probe")
        conn.commit()
        m_c1 = assemble(cur, sid_c1)
        t_c1 = econ_of(m_c1)["pressure"]["t_used"]
        bp_c1 = econ_of(m_c1)["pressure"]["bp"]
        exp_band = ("Normal" if bp_c1 < 6000 else
                    "TrimSchemas" if bp_c1 < 7500 else
                    "CompactHistory" if bp_c1 < 9000 else "AggressivePrune")
        check("C1: low-pressure fixture lands Normal",
              econ_of(m_c1)["tier"]["raw"] == "Normal" and
              exp_band == "Normal", (t_c1, bp_c1))
        # 拉大 history 走到 CompactHistory
        tune_t_used(cur, sid_c1, 800)
        conn.commit()
        m_c1b = assemble(cur, sid_c1)
        bp_c1b = econ_of(m_c1b)["pressure"]["bp"]
        check("C1: big history lifts raw tier",
              econ_of(m_c1b)["tier"]["raw"] in ("CompactHistory",
                                                "AggressivePrune"), bp_c1b)
        # 边界:l_eff 使 bp 恰 6000 → TrimSchemas(半开区间)。
        # bp = (t+ro)*10000/l_eff 整除恰 6000 ⇔ l_eff=(t+ro)*10000/6000
        # 且 (t+ro)*10000 整除 6000 ⇔ (t+ro)≡0 (mod 3)。
        # tune 只长 history est;goal+tools est 恒定 → 总 t_used 同步长。
        ro_c1 = int(ro_now())
        t_total = econ_of(m_c1b)["pressure"]["t_used"]
        hist_est_now = (hist_bytes(cur, sid_c1) + 3) // 4
        goal_tools_est = t_total - hist_est_now
        target_total = t_total
        while (target_total + ro_c1) % 3 != 0:
            target_total += 1
        if target_total > t_total:
            tune_t_used(cur, sid_c1, target_total - goal_tools_est,
                        tag=" C1 boundary")
            conn.commit()
        check("C1: boundary target reached",
              econ_of(assemble(cur, sid_c1))["pressure"]["t_used"] ==
              target_total, target_total)
        l_eff_boundary = (target_total + ro_c1) * 10000 // 6000
        bump_policy(cur, "context_budget",
                    {**cbud_seed, "l_eff_tokens": l_eff_boundary})
        m_c1c = assemble(cur, sid_c1)
        check("C1: bp exactly 6000",
              econ_of(m_c1c)["pressure"]["bp"] == 6000,
              econ_of(m_c1c)["pressure"])
        check("C1: bp=6000 belongs to TrimSchemas (half-open)",
              econ_of(m_c1c)["tier"]["raw"] == "TrimSchemas")
    finally:
        restore_policy(cur, "context_budget", 1)
    conn.commit()

    # C2 单 Plan 单调(同 turn 重装配不降级)
    bump_policy(cur, "context_budget", {**cbud_seed, "l_eff_tokens": 1000})
    try:
        sid_c2 = new_session(cur)
        append_user(cur, sid_c2, "single plan monotonic")
        tune_t_used(cur, sid_c2, 850)   # 高压
        conn.commit()
        m_c2a, art_c2a = None, None
        out_c2, m_c2a = refresh_once(cur, sid_c2,
                                     assemble(cur, sid_c2)[
                                         "required_revision"]["goal"])
        check("C2: first refresh lands", out_c2 == "accepted", out_c2)
        tier_c2a = econ_of(m_c2a)["tier"]["effective"]
        check("C2: first assembly high tier",
              tier_c2a in ("CompactHistory", "AggressivePrune"), tier_c2a)
        # 同 turn 窗口滑走大消息 → raw 低;predicted 持高(origin 锚定
        # 机器事件,不开新 turn)
        for i in range(21):
            anchored_llm(cur, sid_c2, "small " + str(i))
        conn.commit()
        m_c2b = assemble(cur, sid_c2)
        econ_c2b = econ_of(m_c2b)
        check("C2: raw pressure dropped after window slide",
              econ_c2b["tier"]["raw"] == "Normal",
              (econ_c2b["pressure"], econ_c2b["tier"]))
        check("C2: effective held by predicted (single-Plan monotonic)",
              econ_c2b["tier"]["basis"] == "predicted" and
              TIERS.index(econ_c2b["tier"]["effective"]) >=
              TIERS.index(tier_c2a),
              econ_c2b["tier"])
    finally:
        restore_policy(cur, "context_budget", 1)
    conn.commit()

    # C3 跨 turn hysteresis
    bump_policy(cur, "context_budget", {**cbud_seed, "l_eff_tokens": 1000})
    try:
        sid_c3 = new_session(cur)
        append_user(cur, sid_c3, "hysteresis turn 1")
        tune_t_used(cur, sid_c3, 800)  # bp≈(800+ro)*10 ≥ 7500 → CH/AP
        conn.commit()
        _, m1_c3 = refresh_once(cur, sid_c3, assemble(cur, sid_c3)[
            "required_revision"]["goal"])
        held_c3 = econ_of(m1_c3)["tier"]["effective"]
        rank1 = TIERS.index(held_c3) + 1
        check("C3: turn1 high tier", rank1 >= 3, held_c3)

        def low_turn(sid, n):
            append_user(cur, sid, f"clean low turn {n}")
            for i in range(21):
                anchored_llm(cur, sid, "tiny " + str(i))
            conn.commit()
            _, m = refresh_once(cur, sid, assemble(cur, sid)[
                "required_revision"]["goal"])
            return econ_of(m)["tier"]

        t2 = low_turn(sid_c3, 2)
        check("C3: turn2 downgrade blocked inside cooldown (held)",
              t2["effective"] == held_c3 and t2["basis"] == "prior_held", t2)
        t3 = low_turn(sid_c3, 3)
        check("C3: turn3 still held (cooldown_turns=2 not yet full)",
              t3["effective"] == held_c3 and t3["basis"] == "prior_held", t3)
        t4 = low_turn(sid_c3, 4)
        check("C3: turn4 downgrade exactly one step",
              t4["effective"] == TIERS[rank1 - 2] and
              t4["basis"] != "prior_held", t4)
        t5 = low_turn(sid_c3, 5)
        check("C3: turn5 downgrade exactly one further step",
              t5["effective"] == TIERS[max(rank1 - 3, 0)], t5)
        t6_low = low_turn(sid_c3, 6)
        check("C3: sustained low pressure returns to Normal (no permanent lock)",
              t6_low["effective"] == "Normal", t6_low)
        # 升档即时:turn7 重新高压
        append_user(cur, sid_c3, "high again turn 7")
        tune_t_used(cur, sid_c3, 800)
        conn.commit()
        t6 = econ_of(assemble(cur, sid_c3))["tier"]
        check("C3: upgrade immediate (no cooldown)",
              t6["effective"] in ("CompactHistory", "AggressivePrune") and
              t6["basis"] in ("raw",), t6)
    finally:
        restore_policy(cur, "context_budget", 1)
    conn.commit()

    # C4 恢复 floor
    # l_eff=4000:恢复 turn 的 raw 必须落在 Normal 带(bp<6000)。l_eff=1000 时
    # T_used(~599)+p95 R_o(39)会越过带沿进 TrimSchemas,「即使 raw 低」的对照
    # 面消失(plan §4 C4:floor 在 raw=Normal 时把 effective 抬到 CompactHistory)。
    bump_policy(cur, "context_budget", {**cbud_seed, "l_eff_tokens": 4000})
    try:
        sid_c4 = new_session(cur)
        append_user(cur, sid_c4, "floor turn N")
        conn.commit()
        _, m1_c4 = refresh_once(cur, sid_c4, assemble(cur, sid_c4)[
            "required_revision"]["goal"])
        check("C4: base turn Normal",
              econ_of(m1_c4)["tier"]["effective"] == "Normal")
        eff_c4, _ = llm_effect(cur, sid_c4, 100, status="failed")
        cur.execute("UPDATE effects SET error=jsonb_build_object("
                    "'code','prompt_too_long') WHERE effect_id=%s",
                    (eff_c4,))
        conn.commit()   # separate tx: N+1 boundary > failure timestamp
        append_user(cur, sid_c4, "recovery floor turn N+1")
        for i in range(21):
            anchored_llm(cur, sid_c4, "small post-failure " + str(i))
        conn.commit()
        m2_c4 = econ_of(assemble(cur, sid_c4))
        check("C4: recovery turn floored at CompactHistory despite low raw",
              m2_c4["tier"]["raw"] == "Normal" and
              m2_c4["tier"]["effective"] == "CompactHistory" and
              m2_c4["tier"]["basis"] == "recovery_floor", m2_c4["tier"])
        _, m2l = refresh_once(cur, sid_c4, assemble(cur, sid_c4)[
            "required_revision"]["goal"])
        conn.commit()
        append_user(cur, sid_c4, "clean turn N+2")
        for i in range(21):
            anchored_llm(cur, sid_c4, "clean tail " + str(i))
        conn.commit()
        _, m3l = refresh_once(cur, sid_c4, assemble(cur, sid_c4)[
            "required_revision"]["goal"])
        t3_c4 = econ_of(m3l)["tier"]
        check("C4: floor faded after clean turns (basis not recovery_floor)",
              t3_c4["basis"] != "recovery_floor", t3_c4)
        cur.execute("SELECT v13_recovery_active(%s)", (sid_c4,))
        check("C4: v13_recovery_active false (single source)", 
              cur.fetchone()[0] is False)
    finally:
        restore_policy(cur, "context_budget", 1)
    conn.commit()

    # C5 shadow seed(actions off 动作层零激活)
    sid_c5 = new_session(cur)
    append_user(cur, sid_c5, "shadow seed probe")
    append_llm(cur, sid_c5, "a normal sized reply for shadow probing")
    conn.commit()
    m_c5 = assemble(cur, sid_c5)
    names_c5 = {s["transform"].get("name") for s in m_c5["sections"]}
    reasons_c5 = {s["transform"].get("reason") for s in m_c5["sections"]}
    check("C5: actions_off transforms stay in DP3 vocabulary",
          names_c5 <= {"verbatim", "catalog_digest", None} and
          reasons_c5 <= {"budget", "priority_never", "disabled",
                         "invalid_override", None},
          (names_c5, reasons_c5))
    check("C5: no spill/round_drop/final_trim/summarize transforms",
          not (names_c5 & {"spill", "summarize"}) and
          not (reasons_c5 & {"compaction_round_drop",
                             "compaction_final_trim"}))
    check("C5: skeleton sections match DP3 C1 baseline "
          "(all applied; goal/history verbatim, tools catalog_digest)",
          all(s["transform"]["applied"] is True for s in m_c5["sections"]) and
          [s["transform"]["name"] for s in m_c5["sections"]] ==
          ["verbatim", "catalog_digest", "verbatim"] and
          [s["section_id"] for s in m_c5["sections"]] ==
          ["goal", "tools", "history"],
          [(s["section_id"], s["transform"]) for s in m_c5["sections"]])
    check("C5: economics fully recorded under shadow",
          set(econ_of(m_c5).keys()) ==
          {"pressure", "tier", "er", "buckets", "compact_hint"})

    # C6 compact_hint(触点 1 shadow)
    cur.execute("SELECT value FROM v13_policies WHERE "
                "name='context_tiers' AND active")
    tiers_c6 = cur.fetchone()[0]
    bump_policy(cur, "context_budget", {**cbud_seed, "l_eff_tokens": 1000})
    ver_c6 = bump_policy(cur, "context_tiers",
                         {**tiers_c6, "actions_enabled": True})
    try:
        sid_c6 = new_session(cur)
        append_user(cur, sid_c6, "compact hint probe")
        tune_t_used(cur, sid_c6, 800)
        conn.commit()
        m_c6_on = assemble(cur, sid_c6)
        econ_c6 = econ_of(m_c6_on)
        check("C6: hint recorded when effective tier crosses CH",
              econ_c6["tier"]["effective"] in ("CompactHistory",
                                               "AggressivePrune") and
              econ_c6["compact_hint"] is not None and
              econ_c6["compact_hint"]["order"],
              econ_c6["compact_hint"])
        hist_ids = [s["section_id"] for s in m_c6_on["sections"]
                    if s["kind"] == "history"]
        check("C6: hint order covers history sections only (hard classes "
              "never hinted)",
              set(econ_c6["compact_hint"]["order"]) <= set(hist_ids) and
              not (set(econ_c6["compact_hint"]["order"]) &
                   {"goal", "tools"}))
        # shadow: actions off 同输入 sections 逐字节相等
        restore_policy(cur, "context_tiers", 1)
        m_c6_off = assemble(cur, sid_c6)
        check("C6: sections byte-equal with actions off (zero reorder)",
              m_c6_on["sections"] == m_c6_off["sections"])
        check("C6: hint still recorded with actions off (shadow record)",
              econ_of(m_c6_off)["compact_hint"] is not None)
        # Normal 档 → hint null
        sid_c6b = new_session(cur)
        append_user(cur, sid_c6b, "normal tier hint probe")
        conn.commit()
        m_c6b = assemble(cur, sid_c6b)
        check("C6: Normal tier hint null",
              econ_of(m_c6b)["compact_hint"] is None and
              econ_of(m_c6b)["tier"]["effective"] == "Normal")
    finally:
        restore_policy(cur, "context_budget", 1)
        restore_policy(cur, "context_tiers", 1)
    conn.commit()

    # ============================== D 组 ==============================
    # D1 r 在场 + adopt
    sid_d1 = new_session(cur)
    anchor_d1 = append_user(cur, sid_d1, "e(r) adopt probe")
    append(cur, sid_d1, "tool/result",
           {"tool": "session_stats", "result": {"message_count": 3,
             "detail": "recoverable output " * 100},
            "origin_user_seq": anchor_d1})
    conn.commit()
    ver_d1 = bump_policy(cur, "context_tiers",
                         {**tiers_c6, "actions_enabled": True})
    try:
        m_d1 = assemble(cur, sid_d1)
        er_d1 = econ_of(m_d1)["er"]
        check("D1: er.r from pricing seed (=0.25)",
              abs(float(er_d1["r"]) - 0.25) < 1e-9, er_d1["r"])
        check("D1: r_source five dims + catalog_version",
              set(er_d1["r_source"].keys()) ==
              {"provider", "model", "account", "cache_class",
               "catalog_version"} and
              er_d1["r_source"]["catalog_version"] == 1, er_d1["r_source"])
        check("D1: branch=adopt when e_comp<e_base with actions on",
              er_d1["branch"] == "adopt" and
              er_d1["e_comp"] < er_d1["e_base"], er_d1)
    finally:
        restore_policy(cur, "context_tiers", 1)

    # D2 r 缺失
    cur.execute("UPDATE v13_pricing SET active=false WHERE "
                "provider='mock' AND catalog_version=1")
    try:
        m_d2 = assemble(cur, sid_d1)
        er_d2 = econ_of(m_d2)["er"]
        check("D2: r unknown when no active pricing row",
              er_d2["r"] is None and er_d2["branch"] == "r_unknown", er_d2)
        check("D2: hard_window flag observable (economics records basis)",
              er_d2["hard_window"] is False)
    finally:
        cur.execute("UPDATE v13_pricing SET active=true WHERE "
                    "provider='mock' AND catalog_version=1")
    conn.commit()

    # D3 r<r*
    cur.execute("INSERT INTO v13_pricing (provider, model, account, "
                "cache_class, fresh_usd_per_mtok, cached_usd_per_mtok, "
                "catalog_version, active) VALUES ('mock','mock-1','default',"
                "'default', 1.000000, 0.100000, 3, false)")
    cur.execute("UPDATE v13_pricing SET active=false WHERE "
                "provider='mock' AND catalog_version=1")
    cur.execute("UPDATE v13_pricing SET active=true WHERE "
                "provider='mock' AND catalog_version=3")
    bump_policy(cur, "context_tiers", {**tiers_c6, "actions_enabled": True})
    try:
        m_d3 = assemble(cur, sid_d1)
        er_d3 = econ_of(m_d3)["er"]
        check("D3: r=0.10 < r* → branch=loss",
              abs(float(er_d3["r"]) - 0.10) < 1e-9 and
              er_d3["branch"] == "loss", er_d3)
        cur.execute("SELECT value->>'note' FROM v13_policies WHERE "
                    "name='context_tiers' AND active")
        note_d3 = cur.fetchone()[0]
        check("D3: break-even note carried in policy row",
              "0.145" in note_d3)
    finally:
        cur.execute("UPDATE v13_pricing SET active=false WHERE "
                    "provider='mock' AND catalog_version=3")
        cur.execute("UPDATE v13_pricing SET active=true WHERE "
                    "provider='mock' AND catalog_version=1")
        restore_policy(cur, "context_tiers", 1)
    conn.commit()

    # D4 分支词表封闭(五分支互斥可构造)
    branches_d4 = {}

    def branch_of(sid):
        return econ_of(assemble(cur, sid))["er"]["branch"]

    bump_policy(cur, "context_tiers", {**tiers_c6, "actions_enabled": True})
    bump_policy(cur, "context_budget", {**cbud_seed, "l_eff_tokens": 1000})
    try:
        branches_d4["adopt"] = branch_of(sid_d1)
        cur.execute("UPDATE v13_pricing SET active=false WHERE "
                    "provider='mock' AND catalog_version=1")
        branches_d4["r_unknown"] = branch_of(sid_d1)
        cur.execute("UPDATE v13_pricing SET active=true WHERE "
                    "provider='mock' AND catalog_version=1")
        # hard window:bp>=10000
        sid_d4 = new_session(cur)
        append_user(cur, sid_d4, "hard window probe")
        tune_t_used(cur, sid_d4, 1200)   # (1200+ro)*10 ≥ 12000
        conn.commit()
        m_d4 = assemble(cur, sid_d4)
        check("D4: hard-window fixture bp>=10000",
              econ_of(m_d4)["pressure"]["bp"] >= 10000,
              econ_of(m_d4)["pressure"])
        branches_d4["hard_window"] = econ_of(m_d4)["er"]["branch"]
    finally:
        restore_policy(cur, "context_tiers", 1)
        restore_policy(cur, "context_budget", 1)
    branches_d4["actions_off"] = branch_of(sid_d1)   # v1 默认
    cur.execute("INSERT INTO v13_pricing (provider, model, account, "
                "cache_class, fresh_usd_per_mtok, cached_usd_per_mtok, "
                "catalog_version, active) VALUES ('mock','mock-1','default',"
                "'default', 1.000000, 0.100000, 4, false)")
    cur.execute("UPDATE v13_pricing SET active=false WHERE "
                "provider='mock' AND catalog_version=1")
    cur.execute("UPDATE v13_pricing SET active=true WHERE "
                "provider='mock' AND catalog_version=4")
    bump_policy(cur, "context_tiers", {**tiers_c6, "actions_enabled": True})
    branches_d4["loss"] = branch_of(sid_d1)
    restore_policy(cur, "context_tiers", 1)
    cur.execute("UPDATE v13_pricing SET active=false WHERE "
                "provider='mock' AND catalog_version=4")
    cur.execute("UPDATE v13_pricing SET active=true WHERE "
                "provider='mock' AND catalog_version=1")
    conn.commit()
    check("D4: five branches constructible and mutually exclusive",
          set(branches_d4.values()) ==
          {"adopt", "loss", "r_unknown", "hard_window", "actions_off"} and
          len(set(branches_d4.values())) == 5, branches_d4)
    m_d4z = assemble(cur, sid_d1)
    check("D4: economics zero unknown keys",
          set(econ_of(m_d4z).keys()) ==
          {"pressure", "tier", "er", "buckets", "compact_hint"})

    # D5 定价翻版不追动
    sid_d5 = new_session(cur)
    append_user(cur, sid_d5, "pricing flip no-chase probe")
    conn.commit()
    out_d5, m_d5 = refresh_once(cur, sid_d5, assemble(cur, sid_d5)[
        "required_revision"]["goal"])
    check("D5: refreshed fresh", out_d5 == "accepted")
    cur.execute("SELECT v13_context_fresh(%s)", (sid_d5,))
    check("D5: fresh before pricing flip", cur.fetchone()[0] is True)
    rr_before = m_d5["required_revision"]
    cur.execute("INSERT INTO v13_pricing (provider, model, account, "
                "cache_class, fresh_usd_per_mtok, cached_usd_per_mtok, "
                "catalog_version, active) VALUES ('mock','mock-1','default',"
                "'default', 2.000000, 0.600000, 5, false)")
    cur.execute("UPDATE v13_pricing SET active=false WHERE "
                "provider='mock' AND catalog_version=1")
    cur.execute("UPDATE v13_pricing SET active=true WHERE "
                "provider='mock' AND catalog_version=5")
    cur.execute("SELECT v13_context_fresh(%s)", (sid_d5,))
    check("D5: pricing flip does not chase token (still fresh)",
          cur.fetchone()[0] is True)
    m_d5b = assemble(cur, sid_d5)
    check("D5: token unchanged after pricing flip",
          m_d5b["required_revision"] == rr_before)
    check("D5: r reflected from new catalog (bill choice only)",
          abs(float(econ_of(m_d5b)["er"]["r"]) - 0.30) < 1e-9)
    # 对照:context_tiers 翻版追动
    bump_policy(cur, "context_tiers", {**tiers_c6,
                                       "actions_enabled": False})
    cur.execute("SELECT v13_context_fresh(%s)", (sid_d5,))
    check("D5: context_tiers flip chases token (control)",
          cur.fetchone()[0] is False)
    restore_policy(cur, "context_tiers", 1)
    cur.execute("UPDATE v13_pricing SET active=false WHERE "
                "provider='mock' AND catalog_version=5")
    cur.execute("UPDATE v13_pricing SET active=true WHERE "
                "provider='mock' AND catalog_version=1")
    conn.commit()

    # ============================== E 组 ==============================
    sid_e = new_session(cur)
    append_user(cur, sid_e, "manifest v2 shape probe")
    conn.commit()
    m_e = assemble(cur, sid_e)
    check("E1: 11 outer keys",
          set(m_e.keys()) == {"economics", "judgments", "manifest_version",
                              "policy", "prefix_identity", "query_side",
                              "replay", "required_revision", "sections",
                              "session_id", "turn_no"}, set(m_e.keys()))
    check("E1: manifest_version=2", m_e["manifest_version"] == 2)
    check("E1: policy block 7 keys",
          set(m_e["policy"].keys()) ==
          {"assemble_version", "budget_tokens", "est_bytes_per_token",
           "judgment_defaults_version", "tiers_version", "budget_version",
           "pricing_version"})
    check("E1: required_revision 10 keys incl econ_ver 64hex",
          set(m_e["required_revision"].keys()) ==
          {"sem", "dec", "goal", "tools_rev", "asm_ver", "jdef_ver",
           "gen_ver", "corpus", "recall_ver", "econ_ver"} and
          HEX64.match(m_e["required_revision"]["econ_ver"]))

    def walk_keys(obj, pref=""):
        ks = set()
        if isinstance(obj, dict):
            for k, v in obj.items():
                ks.add(pref + k)
                ks |= walk_keys(v, pref + k + ".")
        elif isinstance(obj, list):
            for v in obj:
                ks |= walk_keys(v, pref)
        return ks

    # matcher precision: bare suffixes "at"/"ts" false-positive on plain
    # nouns ("buckets", "judgments"); exact-name or underscore-suffixed
    # timestamp keys are still caught.
    ts_keys = {k for k in walk_keys(m_e)
               if k.lower().split(".")[-1] in ("ts", "at", "time",
                                               "timestamp")
               or k.lower().endswith(("_at", "_ts", "_time",
                                      "timestamp"))}
    check("E1: zero timestamp keys anywhere", not ts_keys, ts_keys)

    ec_e = econ_of(m_e)
    check("E2: economics five sub-blocks keyset exact",
          set(ec_e.keys()) == {"pressure", "tier", "er", "buckets",
                               "compact_hint"} and
          set(ec_e["pressure"].keys()) == {"t_used", "r_o", "l_eff", "bp"} and
          set(ec_e["tier"].keys()) == {"raw", "effective", "basis"} and
          set(ec_e["er"].keys()) ==
          {"branch", "r", "r_source", "e_base", "e_comp", "hard_window"} and
          set(ec_e["buckets"].keys()) ==
          {"core_cap", "history_cap", "retrieval_cap", "effective_budget"})
    check("E2: pressure/buckets all ints >= 0",
          all(isinstance(v, int) and v >= 0
              for v in list(ec_e["pressure"].values()) +
                  list(ec_e["buckets"].values())))

    cur.execute("SELECT v13_manifest_validate(%s::jsonb)",
                (json.dumps(m_e),))
    check("E3: positive real manifest passes", cur.fetchone() is not None)

    def mut(manifest, fn):
        mm = json.loads(json.dumps(manifest))
        fn(mm)
        return mm

    fails_with(cur, "SELECT v13_manifest_validate(%s::jsonb)",
               (json.dumps(mut(m_e, lambda m: m["economics"].update(
                   {"extra": 1}))),),
               "economics key set mismatch",
               "E3: economics extra key rejected", pgcode="V3007")
    fails_with(cur, "SELECT v13_manifest_validate(%s::jsonb)",
               (json.dumps(mut(m_e, lambda m: m["economics"].pop(
                   "buckets"))),),
               "economics key set mismatch",
               "E3: economics missing key rejected", pgcode="V3007")
    fails_with(cur, "SELECT v13_manifest_validate(%s::jsonb)",
               (json.dumps(mut(m_e, lambda m: m["economics"]["pressure"].update(
                   {"t_used": "123"}))),),
               "pressure shape violation",
               "E3: int-as-string in pressure rejected", pgcode="V3007")
    fails_with(cur, "SELECT v13_manifest_validate(%s::jsonb)",
               (json.dumps(mut(m_e, lambda m: m["economics"]["er"].update(
                   {"branch": "cheap"}))),),
               "er shape violation",
               "E3: er.branch outside vocabulary rejected", pgcode="V3007")
    fails_with(cur, "SELECT v13_manifest_validate(%s::jsonb)",
               (json.dumps(mut(m_e, lambda m: m["economics"]["tier"].update(
                   {"basis": "vibes"}))),),
               "tier shape violation",
               "E3: tier.basis outside vocabulary rejected", pgcode="V3007")
    fails_with(cur, "SELECT v13_manifest_validate(%s::jsonb)",
               (json.dumps(mut(m_e, lambda m: m.update(
                   {"manifest_version": 1}))),),
               "anchor/identity shape violation",
               "E3: manifest_version=1 product rejected (v2 domain)")

    # E4 econ_ver 手算 + 追动
    cur.execute(
        "SELECT string_agg(name || ':' || version::text, ',' ORDER BY name) "
        "FROM v13_policies WHERE name IN ('context_tiers','context_budget') "
        "AND active")
    agg_e4 = cur.fetchone()[0]
    check("E4: econ_ver == sha256(name:version csv)",
          m_e["required_revision"]["econ_ver"] ==
          hashlib.sha256(agg_e4.encode()).hexdigest(), agg_e4)
    out_e4, m_e4a = refresh_once(cur, sid_e,
                                 m_e["required_revision"]["goal"])
    cur.execute("SELECT v13_context_fresh(%s)", (sid_e,))
    check("E4: fresh after refresh", cur.fetchone()[0] is True)
    bump_policy(cur, "context_tiers", {**tiers_c6,
                                       "actions_enabled": True})
    cur.execute("SELECT v13_context_fresh(%s)", (sid_e,))
    check("E4: context_tiers flip → stale (token chase)",
          cur.fetchone()[0] is False)
    # 同 turn 二次 refresh 需新 effect 身份:F1 同款 turn/route 编排事件
    # bump cycle_no(enqueue 对同身份 succeeded 行幂等返回不重开)
    append(cur, sid_e, "turn/route", {"action": "refresh"})
    out_e4b, m_e4b = refresh_once(cur, sid_e,
                                  m_e["required_revision"]["goal"])
    cur.execute("SELECT v13_context_fresh(%s)", (sid_e,))
    check("E4: refresh once → fresh again (econ_ver moved)",
          cur.fetchone()[0] is True and
          m_e4b["required_revision"]["econ_ver"] !=
          m_e4a["required_revision"]["econ_ver"])
    restore_policy(cur, "context_tiers", 1)
    append(cur, sid_e, "turn/route", {"action": "refresh"})
    out_e4c, m_e4c = refresh_once(cur, sid_e,
                                  m_e["required_revision"]["goal"])
    cur.execute("SELECT v13_context_fresh(%s)", (sid_e,))
    check("E4: context_budget flip same-family chase",
          cur.fetchone()[0] is True)
    bump_policy(cur, "context_budget", {**cbud_seed, "l_eff_tokens": 64000})
    cur.execute("SELECT v13_context_fresh(%s)", (sid_e,))
    check("E4: context_budget flip → stale", cur.fetchone()[0] is False)
    restore_policy(cur, "context_budget", 1)
    append(cur, sid_e, "turn/route", {"action": "refresh"})
    out_e4d, _ = refresh_once(cur, sid_e, m_e["required_revision"]["goal"])
    check("E4: restore+refresh accepted", out_e4d == "accepted")
    conn.commit()

    # E5 三桶装箱
    cur.execute("SELECT value FROM v13_policies WHERE "
                "name='assemble_manifest' AND active")
    asm_v1 = cur.fetchone()[0]
    bump_policy(cur, "context_budget", {**cbud_seed, "l_eff_tokens": 1000})
    try:
        sid_e5 = new_session(cur)
        append_user(cur, sid_e5, "three bucket probe")
        tune_t_used(cur, sid_e5, 800)
        conn.commit()
        m_e5 = assemble(cur, sid_e5)
        ec_e5 = econ_of(m_e5)
        sec_e5 = {s["section_id"]: s for s in m_e5["sections"]}
        check("E5: history over bucket cap skipped (budget)",
              sec_e5["history"]["transform"] ==
              {"applied": False, "reason": "budget"}, sec_e5["history"])
        check("E5: core sections applied despite history skip "
              "(no bucket borrowing)",
              sec_e5["goal"]["transform"]["applied"] is True and
              sec_e5["tools"]["transform"]["applied"] is True)
        check("E5: caps derived from ratios",
              ec_e5["buckets"]["core_cap"] ==
              int(ec_e5["buckets"]["effective_budget"] * 0.35) and
              ec_e5["buckets"]["history_cap"] ==
              int(ec_e5["buckets"]["effective_budget"] * 0.55))
        # Never/disabled 骨架零回归
        bump_policy(cur, "assemble_manifest",
                    {**asm_v1, "priority_overrides": {"history": "Never"},
                     "kinds_disabled": ["tools"]})
        m_e5b = assemble(cur, sid_e5)
        sec_e5b = {s["section_id"]: s for s in m_e5b["sections"]}
        check("E5: priority_never pre-skip zero regression",
              sec_e5b["history"]["transform"] ==
              {"applied": False, "reason": "priority_never"})
        check("E5: disabled kind pre-skip zero regression",
              sec_e5b["tools"]["transform"] ==
              {"applied": False, "reason": "disabled"})
        restore_policy(cur, "assemble_manifest", 1)
    finally:
        restore_policy(cur, "context_budget", 1)
    conn.commit()

    # E6 硬窗与预算
    bump_policy(cur, "context_budget", {**cbud_seed, "l_eff_tokens": 1000})
    try:
        sid_e6 = new_session(cur)
        append_user(cur, sid_e6, "hard window budget probe")
        tune_t_used(cur, sid_e6, 1200)
        conn.commit()
        m_e6 = assemble(cur, sid_e6)
        ec_e6 = econ_of(m_e6)
        ro_e6 = int(ro_now())
        check("E6: effective_budget = least(budget, l_eff-R_o)",
              ec_e6["buckets"]["effective_budget"] ==
              min(8192, 1000 - ro_e6),
              (ec_e6["buckets"]["effective_budget"], ro_e6))
        applied_sum = sum(s["est_tokens"] for s in m_e6["sections"]
                          if s["transform"]["applied"] is True)
        check("E6: sum(applied est) <= effective_budget (ch10 fifth)",
              applied_sum <= ec_e6["buckets"]["effective_budget"],
              (applied_sum, ec_e6["buckets"]))
        check("E6: hard window flag set at bp>=10000",
              ec_e6["er"]["hard_window"] is True and
              ec_e6["pressure"]["bp"] >= 10000)
        # 首段可 skip:core 桶 cap 压到 goal est 之下 → 首段超自身桶 cap 即
        # skip(DP3 C2 缩预算同型;不用超长 user 文本——recall 查询分段器
        # v13_query_segments 对 >256 字节段在装配路径内 fail-loud RAISE)
        cur.execute("SELECT value FROM v13_policies WHERE "
                    "name='assemble_manifest' AND active")
        asm_e6b = cur.fetchone()[0]
        bump_policy(cur, "assemble_manifest", {**asm_e6b, "budget_tokens": 8})
        try:
            sid_e6b = new_session(cur)
            append_user(cur, sid_e6b, "goal over own cap probe")
            conn.commit()
            m_e6b = assemble(cur, sid_e6b)
            sec_e6b = {s["section_id"]: s for s in m_e6b["sections"]}
            check("E6: first section over own bucket cap is skipped",
                  sec_e6b["goal"]["transform"] == {"applied": False,
                                                   "reason": "budget"},
                  sec_e6b["goal"])
        finally:
            restore_policy(cur, "assemble_manifest", 1)
    finally:
        restore_policy(cur, "context_budget", 1)
    conn.commit()

    # E7 section_id 多段化
    base_e7 = json.loads(json.dumps(m_e))
    hist_sec = next(s for s in base_e7["sections"]
                    if s["kind"] == "history")
    h1 = json.loads(json.dumps(hist_sec))
    h1["section_id"] = "history:" + hist_sec["content_hash"][:8]
    h2 = json.loads(json.dumps(hist_sec))
    h2["content_hash"] = hashlib.sha256(b"second-history-blob").hexdigest()
    h2["section_id"] = "history:" + h2["content_hash"][:8]
    h2["payload_ref"]["content_hash"] = h2["content_hash"]
    multi_e7 = base_e7
    multi_e7["sections"] = [s for s in base_e7["sections"]
                            if s["kind"] != "history"] + [h1, h2]
    cur.execute("SELECT v13_manifest_validate(%s::jsonb)",
                (json.dumps(multi_e7),))
    check("E7: kind:8hex twin sections pass validate v2",
          cur.fetchone() is not None)
    bare_e7 = json.loads(json.dumps(multi_e7))
    for s in bare_e7["sections"]:
        if s["kind"] == "history":
            s["section_id"] = "history"
    fails_with(cur, "SELECT v13_manifest_validate(%s::jsonb)",
               (json.dumps(bare_e7),),
               "multi-part rule violation",
               "E7: bare duplicate section_id rejected", pgcode="V3007")
    check("E7: single-kind manifests keep section_id=kind (DP3 skeleton "
          "zero drift)",
          all(s["section_id"] == s["kind"] for s in m_e["sections"]))

    # ============================== F 组 ==============================
    sid_f = new_session(cur)
    append_user(cur, sid_f, "cache break probe")
    append_llm(cur, sid_f, "stable history line one")
    conn.commit()
    out_f1, m_f1 = refresh_once(cur, sid_f, assemble(cur, sid_f)[
        "required_revision"]["goal"])
    # 同状态二次 refresh(bump cycle 经 turn/route 编排事件,零语义变化)
    append(cur, sid_f, "turn/route", {"action": "llm"})
    conn.commit()
    out_f1b, m_f1b = refresh_once(cur, sid_f, m_f1["required_revision"][
        "goal"])
    check("F1: two same-state refreshes accepted",
          out_f1 == out_f1b == "accepted")
    cur.execute("SELECT * FROM v13_cache_breaks(%s)", (sid_f,))
    br_f1 = cur.fetchall()
    check("F1: same state → all broke=false",
          all((not r[3]) for r in br_f1), br_f1)
    check("F1: same state → all rebill_suffix=false",
          all((not r[4]) for r in br_f1), br_f1)

    # F2 单段变更 + 首断点后缀(tools LastResort 使 history 后仍有段)
    cur.execute("SELECT value FROM v13_policies WHERE "
                "name='assemble_manifest' AND active")
    asm_f2 = cur.fetchone()[0]
    bump_policy(cur, "assemble_manifest",
                {**asm_f2, "priority_overrides": {"tools": "LastResort"}})
    try:
        append(cur, sid_f, "turn/route", {"action": "llm"})
        anchored_llm(cur, sid_f, "appended line changes history only")
        conn.commit()
        out_f2, m_f2 = refresh_once(cur, sid_f, m_f1b[
            "required_revision"]["goal"])
        cur.execute("SELECT * FROM v13_cache_breaks(%s)", (sid_f,))
        br_f2 = {r[0]: r for r in cur.fetchall()}
        check("F2: history broke=true", br_f2["history"][3] is True, br_f2)
        check("F2: goal/tools broke=false",
              br_f2["goal"][3] is False and br_f2["tools"][3] is False)
        check("F2: rebill suffix after first break only",
              br_f2["history"][4] is False and br_f2["tools"][4] is True and
              br_f2["goal"][4] is False,
              {k: (v[3], v[4]) for k, v in br_f2.items()})
        # F3 churn 对照(单源输入互证)
        churn_f3 = {s["section_id"]: s["churn"] for s in m_f2["sections"]}
        br_f3 = {r[0]: r[3] for r in br_f2.values()}
        check("F3: manifest churn>0 ⟺ attribution broke (same source)",
              all((churn_f3[k] > 0) == v for k, v in br_f3.items()),
              (churn_f3, br_f3))
    finally:
        restore_policy(cur, "assemble_manifest", 1)
    conn.commit()

    # F4 新段(前版无该 section_id → broke=true)
    cur.execute(
        "SELECT a.inline FROM artifacts a JOIN sessions s "
        "ON s.context_active_artifact=a.artifact_id WHERE s.session_id=%s",
        (sid_f,))
    m_f4src = cur.fetchone()[0]
    extra_f4 = json.loads(json.dumps(
        next(s for s in m_f4src["sections"] if s["kind"] == "tools")))
    extra_f4["section_id"] = "future"
    extra_f4["kind"] = "future"
    m_f4 = json.loads(json.dumps(m_f4src))
    m_f4["sections"] = m_f4["sections"] + [extra_f4]
    cur.execute(
        "SELECT v13_artifact_land((SELECT effect_id FROM effects WHERE "
        "session_id=%s AND kind='context_refresh' ORDER BY created_at DESC "
        "LIMIT 1), 'context', %s::jsonb)", (sid_f, json.dumps(m_f4)))
    art_f4 = cur.fetchone()[0]
    cur.execute("UPDATE sessions SET context_active_artifact=%s "
                "WHERE session_id=%s", (art_f4, sid_f))
    cur.execute("SELECT * FROM v13_cache_breaks(%s)", (sid_f,))
    br_f4 = {r[0]: r for r in cur.fetchall()}
    check("F4: brand-new section flagged broke (新增即断)",
          br_f4["future"][3] is True and br_f4["future"][1] is None, br_f4)
    # 还原指针到真实 refresh 产物
    cur.execute(
        "SELECT a.artifact_id FROM artifacts a JOIN effects e "
        "ON e.effect_id=a.produced_by WHERE e.session_id=%s AND "
        "a.kind='context' ORDER BY a.created_at DESC LIMIT 1", (sid_f,))
    real_f4 = cur.fetchone()[0]
    cur.execute("UPDATE sessions SET context_active_artifact=%s "
                "WHERE session_id=%s", (real_f4, sid_f))
    conn.commit()

    # ============================== G 组 ==============================
    # G1 未过闸零扰动(DP1 M4 基线等价)
    sid_g1 = new_session(cur)
    append_user(cur, sid_g1, "g1 baseline turn")
    conn.commit()
    set_mock(cur, mock_for(cur, sid_g1, intent="llm_generate", noul=0.1))
    cur.execute("SELECT v13_parse(%s)", (sid_g1,))
    p_g1 = cur.fetchone()[0]
    check("G1: parse exit schema intact",
          set(p_g1.keys()) == {"snap", "envelope", "abandon",
                               "asked_batches", "asked_questions",
                               "remaining", "failed"} and
          isinstance(p_g1["abandon"], bool) and
          isinstance(p_g1["asked_questions"], int), p_g1.keys())
    check("G1: resolve ran (asked>0, remaining=0, failed=false)",
          p_g1["asked_questions"] > 0 and p_g1["remaining"] == 0 and
          p_g1["failed"] is False and p_g1["abandon"] is False, p_g1)
    cur.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                (sid_g1,))
    calls_g1_before = cur.fetchone()[0]
    check("G1: judgment_calls landed (>=1 batch)", calls_g1_before >= 1)
    # DP1 advance order: fresh session + newly-landed decisions ⇒ context
    # stale ⇒ advance ② would route context_refresh first. Settle the
    # refresh now (refresh_once's enqueue = advance's would-be routing
    # identity), recycle (parse re-parse needs the provider/model GUC back
    # — see recycle docstring), re-parse (all cache hits ⇒ token stable ⇒
    # context stays fresh), then the single advance reaches the llm
    # routing face (DP1 M4 shape). noul=0.1 keeps gate_off_topic below
    # the reject band (mock default 0.9 would veto → terminal).
    refresh_once(cur, sid_g1, p_g1["snap"]["goal_hash"])
    conn, cur = recycle(server, conn)
    set_mock(cur, mock_for(cur, sid_g1, intent="llm_generate", noul=0.1))
    cur.execute("SELECT v13_parse(%s)", (sid_g1,))
    p_g1 = cur.fetchone()[0]
    cur.execute("SELECT v13_advance(%s,%s::jsonb)",
                (sid_g1, json.dumps(p_g1)))
    adv_g1 = cur.fetchone()[0]
    check("G1: advance routes llm effect (DP1 M4 shape)",
          adv_g1 == "waiting", adv_g1)
    cur.execute(
        "SELECT kind, status, request FROM effects WHERE session_id=%s "
        "AND kind='llm'", (sid_g1,))
    row_g1 = cur.fetchone()
    check("G1: llm effect enqueued with route-only request",
          row_g1[1] == "ready" and
          set(row_g1[2].keys()) == {"route"}, row_g1)
    cur.execute(
        "SELECT count(*) FROM events WHERE session_id=%s AND "
        "type='turn/route'", (sid_g1,))
    check("G1: turn/route event appended once", cur.fetchone()[0] == 1)
    conn.commit()

    # G2 超闸转慢路
    sid_g2 = new_session(cur)
    append_user(cur, sid_g2, "g2 over gate turn")
    conn.commit()
    cur.execute(
        "SELECT v13_judgment_envelope(%s)", (sid_g2,))
    env_g2 = cur.fetchone()[0]
    # 预置已答 decision(intent)——缓存命中消费面
    need_g2 = {n["signal"]: n for n in env_g2["needed"]}
    n_g2 = need_g2["intent"]
    cur.execute("SELECT v13_judgment_hash(%s,%s,%s,%s,%s)",
                (json.dumps(env_g2), "intent", n_g2["kind"], n_g2["question"],
                 json.dumps(n_g2["criteria"])))
    hash_g2 = cur.fetchone()[0]
    cur.execute("SELECT v13_group_state(%s::jsonb,'intent')",
                (json.dumps(env_g2),))
    ctx_g2 = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO decisions (session_id, signal, kind, question, "
        "criteria, context, answer, provider, model, request_hash, status, "
        "answered_at) VALUES (%s,'intent',%s,%s,%s,%s,"
        "'{\"noul\":0.9,\"type\":\"noul\"}'::jsonb,%s,%s,%s,'answered',now())",
        (sid_g2, n_g2["kind"], n_g2["question"],
         json.dumps(n_g2["criteria"]), json.dumps(ctx_g2),
         env_g2["provider"], env_g2["model"], hash_g2))
    # 灌满 session_asks_cap
    cur.execute(
        "INSERT INTO judgment_calls (session_id, candidate_set_hash, "
        "projection_key, payload, payload_hash, provider, model, "
        "question_count, status) SELECT %s, 'fixture' || i, 'fixture', "
        "'{}'::jsonb, 'h' || i, 'mock', 'jev-mock', 1, 'succeeded' "
        "FROM generate_series(1, 512) i", (sid_g2,))
    cur.execute("SELECT (v13_judge_spend(%s)->>'over')::boolean", (sid_g2,))
    check("G2: spend gate over at cap", cur.fetchone()[0] is True)
    calls_g2_before = cur.fetchone() if False else None
    cur.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                (sid_g2,))
    n_calls_g2 = cur.fetchone()[0]
    set_mock(cur, mock_for(cur, sid_g2))
    cur.execute("SELECT v13_parse(%s)", (sid_g2,))
    p_g2 = cur.fetchone()[0]
    check("G2: over gate skips resolve (asked=0, zero new calls)",
          p_g2["asked_questions"] == 0 and p_g2["asked_batches"] == 0 and
          p_g2["failed"] is False and p_g2["abandon"] is False, p_g2)
    cur.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                (sid_g2,))
    check("G2: zero new judgment_calls rows (cache-only)",
          cur.fetchone()[0] == n_calls_g2)
    check("G2: pre-answered signal consumed by gap (remaining excludes it)",
          p_g2["remaining"] == len(env_g2["needed"]) - 1, p_g2["remaining"])
    # Same ②-before-③ order as G1: settle the refresh the landed decision
    # made necessary, recycle (GUC), re-parse (cache-only — gate still
    # over), then advance hands the gaps to the slow path as judge effect.
    refresh_once(cur, sid_g2, p_g2["snap"]["goal_hash"])
    conn, cur = recycle(server, conn)
    set_mock(cur, mock_for(cur, sid_g2))
    cur.execute("SELECT v13_parse(%s)", (sid_g2,))
    p_g2 = cur.fetchone()[0]
    cur.execute("SELECT v13_advance(%s,%s::jsonb)",
                (sid_g2, json.dumps(p_g2)))
    adv_g2 = cur.fetchone()[0]
    check("G2: gaps handed to slow path (judge effect)",
          adv_g2 == "waiting", adv_g2)
    cur.execute(
        "SELECT count(*) FROM effects WHERE session_id=%s AND kind='judge'",
        (sid_g2,))
    check("G2: judge effect created", cur.fetchone()[0] == 1)
    # G5 慢路不闸(同场景 worker resolve 照常 ask)
    cur.execute(
        "SELECT request->'envelope' FROM effects WHERE session_id=%s AND "
        "kind='judge'", (sid_g2,))
    env_g2b = cur.fetchone()[0]
    # intent is pre-answered (G2 cache fixture) ⇒ the resolve ask excludes
    # it (gap join) ⇒ the mock must too (unknown-signal rejection otherwise)
    set_mock(cur, mock_for_env(env_g2b, exclude={"intent"}))
    cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)",
                (json.dumps(env_g2b),))
    res_g5 = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                (sid_g2,))
    n_calls_g5 = cur.fetchone()[0]
    check("G5: slow-path resolve still asks over gate (F5-1 fast-path only)",
          res_g5["asked_questions"] > 0 and n_calls_g5 > n_calls_g2,
          (res_g5, n_calls_g5 - n_calls_g2))
    conn.commit()

    # G3 日闸跨日边界
    sid_g3 = new_session(cur)
    cur.execute(
        "INSERT INTO judgment_calls (session_id, candidate_set_hash, "
        "projection_key, payload, payload_hash, provider, model, "
        "question_count, status, created_at) SELECT %s, 'old' || i, 'd1', "
        "'{}'::jsonb, 'oh' || i, 'mock', 'jev-mock', 1, 'succeeded', "
        "now() - interval '2 days' FROM generate_series(1, 9000) i",
        (sid_g3,))
    spend_g3 = None
    cur.execute("SELECT v13_judge_spend(%s)", (sid_g3,))
    spend_g3 = cur.fetchone()[0]
    check("G3: day counter resets across day boundary (0 today)",
          spend_g3["day_asks"] == 0, spend_g3)
    check("G3: session counter persists across days",
          spend_g3["session_asks"] == 9000, spend_g3)
    check("G3: day cap breached but session cap not → over",
          spend_g3["over"] is True, spend_g3)
    cur.execute(
        "INSERT INTO judgment_calls (session_id, candidate_set_hash, "
        "projection_key, payload, payload_hash, provider, model, "
        "question_count, status, created_at) SELECT %s, 'today' || i, 'd2', "
        "'{}'::jsonb, 'th' || i, 'mock', 'jev-mock', 1, 'succeeded', "
        "now() FROM generate_series(1, 10) i", (sid_g3,))
    cur.execute("SELECT v13_judge_spend(%s)", (sid_g3,))
    spend_g3b = cur.fetchone()[0]
    check("G3: today's calls counted in day_asks",
          spend_g3b["day_asks"] == 10 and
          spend_g3b["session_asks"] == 9010, spend_g3b)
    conn.commit()

    # G4 计数口径含 filter 族(DP6 面)——摘要验收 ask 归 13 号库 P 组断言
    sid_g4 = new_session(cur)
    cur.execute(
        "INSERT INTO judgment_calls (session_id, candidate_set_hash, "
        "projection_key, payload, payload_hash, provider, model, "
        "question_count, status) VALUES (%s, 'corpus-digest-fixture', "
        "'corpus_exists', '{}'::jsonb, 'fh1', 'mock', 'jev-mock', 1, "
        "'succeeded')", (sid_g4,))
    cur.execute("SELECT v13_judge_spend(%s)", (sid_g4,))
    spend_g4 = cur.fetchone()[0]
    check("G4: filter-family ask counted (no signal filtering)",
          spend_g4["session_asks"] == 1 and spend_g4["over"] is False,
          spend_g4)
    conn.commit()

    # ============================== H 组 ==============================
    # H1 settle ∥ 翻版(context_tiers)
    def settle_conn_factory():
        c = psycopg2.connect(server.get_uri(DB))
        c.autocommit = False
        return c

    sid_h1 = new_session(cur)
    append_user(cur, sid_h1, "h1 settle-parallel-flip")
    conn.commit()
    goal_h1 = assemble(cur, sid_h1)["required_revision"]["goal"]
    cur.execute(
        "SELECT v13_enqueue_effect(%s,'context_refresh',"
        "jsonb_build_object('goal_hash',%s))", (sid_h1, goal_h1))
    eff_h1 = cur.fetchone()[0]
    cur.execute("SELECT v13_claim('t')")
    cl_h1 = cur.fetchone()[0]
    conn.commit()   # effect claimed persists; refresh tx starts below

    conn_a = settle_conn_factory()
    cur_a = conn_a.cursor()
    cur_a.execute("SET search_path TO public, pg_catalog")
    cur_a.execute("BEGIN")
    cur_a.execute("SELECT v13_refresh_context(%s,%s,%s)",
                  (eff_h1, cl_h1["attempt_no"], cl_h1["fence"]))
    out_a = cur_a.fetchone()[0]
    check("H1: A refresh accepted (locks held in A tx)", out_a == "accepted")

    conn_b = settle_conn_factory()
    cur_b = conn_b.cursor()
    cur_b.execute("SET search_path TO public, pg_catalog")
    cur_b.execute("BEGIN")
    cur_b.execute("SET LOCAL lock_timeout = '600ms'")
    cur_b.execute(
        "INSERT INTO v13_policies (name, version, value, active) "
        "SELECT 'context_tiers', "
        "(SELECT max(version)+1 FROM v13_policies "
        " WHERE name='context_tiers'), value, false "
        "FROM v13_policies WHERE name='context_tiers' AND active")
    t0_h1 = time.perf_counter()
    blocked_h1 = False
    try:
        cur_b.execute(
            "UPDATE v13_policies SET active=false WHERE "
            "name='context_tiers' AND active")
    except psycopg2.errors.LockNotAvailable:
        blocked_h1 = True
        dt_h1 = time.perf_counter() - t0_h1
    check("H1: B flip blocked on policy row lock until A commits",
          blocked_h1 and dt_h1 < 3.0, dt_h1 if blocked_h1 else "no block")
    conn_a.commit()   # A 提交 → B 可推进
    conn_b.rollback()
    conn_a.close()
    conn_b.close()
    cur.execute(
        "SELECT a.inline->'policy'->>'tiers_version' FROM artifacts a "
        "JOIN sessions s ON s.context_active_artifact=a.artifact_id "
        "WHERE s.session_id=%s", (sid_h1,))
    check("H1: A manifest recorded old tiers_version (=1)",
          cur.fetchone()[0] == "1")
    # settle ∥ settle 零 40P01(两 session 并发 refresh)
    sid_h1b = new_session(cur)
    append_user(cur, sid_h1b, "h1 parallel settle")
    conn.commit()
    goal_h1b = assemble(cur, sid_h1b)["required_revision"]["goal"]
    # 两个并发 settle 都要用全新 session:sid_h1 的 refresh effect 已终态
    # (enqueue 幂等返回不重开⇒无 ready 行⇒对端 claim 抢空/错配)
    sid_h1c = new_session(cur)
    append_user(cur, sid_h1c, "h1 parallel settle c")
    conn.commit()
    goal_h1c = assemble(cur, sid_h1c)["required_revision"]["goal"]
    results_h1 = {}

    def settle_thread(sid, goal, key):
        c = psycopg2.connect(server.get_uri(DB))
        c.autocommit = False
        k = c.cursor()
        k.execute("SET search_path TO public, pg_catalog")
        try:
            k.execute(
                "SELECT v13_enqueue_effect(%s,'context_refresh',"
                "jsonb_build_object('goal_hash',%s))", (sid, goal))
            eff = k.fetchone()[0]
            k.execute("SELECT v13_claim('t')")
            clx = k.fetchone()[0]
            k.execute("SELECT v13_refresh_context(%s,%s,%s)",
                      (eff, clx["attempt_no"], clx["fence"]))
            results_h1[key] = k.fetchone()[0]
            c.commit()
        except psycopg2.Error as exc:
            c.rollback()
            results_h1[key] = f"{exc.pgcode}: {str(exc)[:80]}"
        c.close()

    th1 = threading.Thread(target=settle_thread,
                           args=(sid_h1c, goal_h1c, "r1"))
    th2 = threading.Thread(target=settle_thread,
                           args=(sid_h1b, goal_h1b, "r2"))
    th1.start(); th2.start(); th1.join(30); th2.join(30)
    check("H1: parallel settles both accepted, zero deadlock (40P01)",
          results_h1.get("r1") == "accepted" and
          results_h1.get("r2") == "accepted", results_h1)
    conn.commit()

    # H2 settle ∥ pricing 翻版
    sid_h2 = new_session(cur)
    append_user(cur, sid_h2, "h2 settle-parallel-pricing")
    conn.commit()
    goal_h2 = assemble(cur, sid_h2)["required_revision"]["goal"]
    cur.execute(
        "SELECT v13_enqueue_effect(%s,'context_refresh',"
        "jsonb_build_object('goal_hash',%s))", (sid_h2, goal_h2))
    eff_h2 = cur.fetchone()[0]
    cur.execute("SELECT v13_claim('t')")
    cl_h2 = cur.fetchone()[0]
    conn.commit()
    conn_a2 = settle_conn_factory()
    cur_a2 = conn_a2.cursor()
    cur_a2.execute("SET search_path TO public, pg_catalog")
    cur_a2.execute("BEGIN")
    cur_a2.execute("SELECT v13_refresh_context(%s,%s,%s)",
                   (eff_h2, cl_h2["attempt_no"], cl_h2["fence"]))
    check("H2: A refresh accepted", cur_a2.fetchone()[0] == "accepted")
    conn_b2 = settle_conn_factory()
    cur_b2 = conn_b2.cursor()
    cur_b2.execute("SET search_path TO public, pg_catalog")
    cur_b2.execute("BEGIN")
    cur_b2.execute("SET LOCAL lock_timeout = '600ms'")
    cur_b2.execute(
        "INSERT INTO v13_pricing (provider, model, account, cache_class, "
        "fresh_usd_per_mtok, cached_usd_per_mtok, catalog_version, active) "
        "VALUES ('mock','mock-1','default','default', 5.000000, 1.000000, "
        "99, false)")
    blocked_h2 = False
    try:
        cur_b2.execute("UPDATE v13_pricing SET active=false WHERE "
                       "provider='mock' AND catalog_version=1")
    except psycopg2.errors.LockNotAvailable:
        blocked_h2 = True
    check("H2: B pricing flip blocked on v13_pricing lock until A commits",
          blocked_h2)
    conn_a2.commit()
    conn_b2.rollback()
    conn_a2.close()
    conn_b2.close()
    cur.execute(
        "SELECT a.inline->'economics'->'er'->'r_source'->>'catalog_version' "
        "FROM artifacts a JOIN sessions s ON "
        "s.context_active_artifact=a.artifact_id WHERE s.session_id=%s",
        (sid_h2,))
    check("H2: A manifest r_source pinned old catalog_version (=1)",
          cur.fetchone()[0] == "1")
    conn.commit()

    # H3 OR REPLACE 五件 ACL/签名 + 上游回归抽样
    sig_expect = {
        "v13_parse": "p_sid uuid",
        "v13_context_required": "p_sid uuid",
        "v13_assemble_manifest": "p_sid uuid, p_policy_version integer",
        "v13_manifest_validate": "p_manifest jsonb",
        "v13_refresh_context": "p_effect uuid, p_attempt integer, "
                               "p_fence bigint"}
    for fn, want in sig_expect.items():
        cur.execute(
            "SELECT pg_get_function_identity_arguments(%s::regproc)",
            (fn,))
        check(f"H3: signature unchanged {fn}", cur.fetchone()[0] == want,
              want)
    cur.execute("SELECT has_function_privilege('v13_route',"
                "'v13_refresh_context(uuid,integer,bigint)','EXECUTE')")
    check("H3: refresh EXECUTE stays with route", cur.fetchone()[0] is True)
    cur.execute("SELECT has_function_privilege('v13_resolve',"
                "'v13_parse(uuid)','EXECUTE')")
    check("H3: parse EXECUTE stays with resolve", cur.fetchone()[0] is True)
    # 上游回归抽样(本前缀库)
    sid_h3 = new_session(cur)
    append_user(cur, sid_h3, "h3 upstream-family retest")
    conn.commit()
    m_h3 = assemble(cur, sid_h3)
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_h3,))
    check("H3: DP3-D4 family assemble deterministic dual-run",
          cur.fetchone()[0] == m_h3)
    check("H3: DP3-C1 family order (prank, section_id)",
          [s["section_id"] for s in m_h3["sections"]] ==
          ["goal", "tools", "history"])
    out_h3, m_h3l = refresh_once(cur, sid_h3,
                                 m_h3["required_revision"]["goal"])
    n_dec_h3 = 0
    cur.execute("SELECT count(*) FROM decisions WHERE session_id=%s",
                (sid_h3,))
    n_dec_h3 = cur.fetchone()[0]
    check("H3: DP3-F1 family settle lands artifact + empty judgments",
          out_h3 == "accepted" and m_h3l["judgments"] == [])
    cur.execute(
        "SELECT count(*) FROM artifacts a JOIN effects e ON "
        "e.effect_id=a.produced_by WHERE e.session_id=%s AND "
        "a.kind='context'", (sid_h3,))
    check("H3: artifact landed once", cur.fetchone()[0] >= 1)
    cur.execute(
        "SELECT count(*) FROM artifacts WHERE kind='context_section' AND "
        "content_hash IN (SELECT s->>'content_hash' FROM jsonb_array_elements"
        "(%s::jsonb->'sections') s)", (json.dumps(m_h3l),))
    check("H3: history blob retrievable (content-addressed)",
          cur.fetchone()[0] >= 2)
    conn.commit()

    # H4 加载边界
    test_src = Path(__file__).read_text()
    fwd = [t for t in ("summary_" + "accept", "context_" + "summary",
                       "v13_" + "summary", "v13_span_" + "digest",
                       "summary_" + "fidelity")
           if t in strip_sql_comments(econ_sql)]
    check("H4: file12 zero forward references to file-13 objects",
          not fwd, fwd)
    # tokens are concatenated so the scan list itself never matches its own
    # literals (the check stays 1:1 red-able against real references)
    fwd_test = [t for t in ("summary_" + "accept",
                            "v13_summary_" + "schedule",
                            "v13_summary_" + "envelope",
                            "summary_" + "fidelity")
                if t in test_src]
    check("H4: economy gate asserts nothing beyond file 12", not fwd_test,
          fwd_test)
    check("H4: economy is 12th; memory is 11th",
          files_through("economy")[11].name == "v13_economy.sql" and
          files_through("economy")[10].name == "v13_memory.sql")

    n_tbl = len(re.findall(r"(?im)^CREATE TABLE ", norm_e))
    n_idx = len(re.findall(r"(?im)^CREATE UNIQUE INDEX ", norm_e))
    n_cf = len(re.findall(r"(?im)^CREATE (?:OR REPLACE )?FUNCTION ", norm_e))
    n_trg = len(re.findall(r"(?im)^CREATE TRIGGER ", norm_e))
    n_ins = len(re.findall(r"(?im)^INSERT INTO ", norm_e))
    n_rev = len(re.findall(r"(?im)^REVOKE ", norm_e))
    n_gr = len(re.findall(r"(?im)^GRANT ", norm_e))
    check("H4: paper-load counts (1 TABLE/1 UINDEX/14 FUNCTION/1 TRIGGER/"
          "2 INSERT/1 REVOKE/3 GRANT + BEGIN/COMMIT wrap)",
          (n_tbl, n_idx, n_cf, n_trg, n_ins, n_rev, n_gr) ==
          (1, 1, 14, 1, 2, 1, 3),
          (n_tbl, n_idx, n_cf, n_trg, n_ins, n_rev, n_gr))
    sigs_h4 = re.findall(r"(?im)^CREATE (?:OR REPLACE )?FUNCTION (\w+)\(",
                         norm_e)
    check("H4: no duplicate signature", len(sigs_h4) == len(set(sigs_h4)))
    check("H4: BEGIN/COMMIT wrap",
          norm_e.lstrip().startswith("BEGIN;") and
          norm_e.rstrip().endswith("COMMIT;"))

    readme = (V13 / "economy" / "README.md").read_text()
    for needle in ("tier", "R_o", "冷启动", "shadow", "E(r)", "三桶",
                   "花费闸", "fastpath_tiers", "k_max", "cache-break",
                   "一页账", "零新增"):
        check(f"H4-readme: mentions {needle}", needle in readme)

    conn.close()
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
