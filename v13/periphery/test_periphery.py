"""DP8 gate: periphery — latches (INSERT-once/admission/F13), generation
latch freeze, 11-key token restoration, canonical render family,
ForkPrefix spawn shell + validate-spawn + cache probe, shadow observe /
streak, intent soft gate (record-only). Groups A-I.

Run: uv run python v13/periphery/test_periphery.py  (exit 0 = pass)
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import threading
import uuid
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
V13 = AGENT_ROOT / "v13"
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.periphery.setup_db import DB, main as setup_db
from v13.load import files_through, SQL_LOAD_ORDER

PERIPHERY_SQL = V13 / "periphery" / "v13_periphery.sql"

PASS = 0


def check(label: str, condition: bool, detail: object = "") -> None:
    global PASS
    mark = "PASS" if condition else "FAIL"
    extra = (f": {detail}" if detail and (not condition or len(str(detail)) < 220)
             else "")
    print(f"[{mark}] {label}{extra}", flush=True)
    if not condition:
        raise AssertionError(f"{label}: {detail}")
    PASS += 1


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


def full_settle(cur, sid):
    m = assemble(cur, sid)
    return refresh_n(cur, sid, m["required_revision"]["goal"])


def active_artifact(cur, sid):
    cur.execute(
        "SELECT context_active_artifact FROM sessions WHERE session_id=%s",
        (sid,))
    return cur.fetchone()[0]


def fire(cur, sid, name, value):
    cur.execute("SELECT v13_latch_fire(%s,%s,%s::jsonb)",
                (sid, name, json.dumps(value)))
    return cur.fetchone()[0]


def llm_succeed(cur, sid, result_extra, route_reason="probe"):
    """Real llm effect: enqueue -> claim -> complete succeeded with the
    DP7/DP8 worker-contract result shape (+extra keys)."""
    cur.execute(
        "SELECT v13_enqueue_effect(%s,'llm',"
        "jsonb_build_object('route',jsonb_build_object('action','llm',"
        "'reason',%s))::jsonb)", (sid, route_reason))
    eff = cur.fetchone()[0]
    cur.execute("SELECT v13_claim('t')")
    cl = cur.fetchone()[0]
    cur.execute(
        "SELECT v13_complete(%s,%s,%s,'succeeded',"
        "jsonb_build_object('text','generated','usage',jsonb_build_object("
        "'completion_tokens',5,'cache_read_input_tokens',0),'model','mock-1'"
        ") || %s::jsonb)",
        (eff, cl["attempt_no"], cl["fence"], json.dumps(result_extra)))
    out = cur.fetchone()[0]
    assert out == "accepted", out
    return eff


def policy_flip(cur, name, version, value):
    """INSERT inactive new version + double UPDATE flip (仪式同款)."""
    cur.execute(
        "INSERT INTO v13_policies (name, version, value, active) "
        "VALUES (%s, %s, %s::jsonb, false)",
        (name, version, json.dumps(value)))
    cur.execute(
        "UPDATE v13_policies SET active=false WHERE name=%s AND active",
        (name,))
    cur.execute(
        "UPDATE v13_policies SET active=true WHERE name=%s AND version=%s",
        (name, version))


def policy_unflip(cur, name, version):
    """Flip active back to the given (pre-existing) version."""
    cur.execute(
        "UPDATE v13_policies SET active=false WHERE name=%s AND active",
        (name,))
    cur.execute(
        "UPDATE v13_policies SET active=true WHERE name=%s AND version=%s",
        (name, version))


def policy_value(cur, name):
    cur.execute(
        "SELECT value FROM v13_policies WHERE name=%s AND active", (name,))
    return cur.fetchone()[0]


def intent_decision(cur, sid, confidence):
    cur.execute(
        "INSERT INTO decisions (session_id, signal, kind, question, "
        "criteria, context, answer, provider, model, request_hash, status) "
        "VALUES (%s,'intent','choice','What does the user need next?',"
        "'{\"include\":\"keep\",\"exclude\":\"drop\"}'::jsonb,"
        "'{}'::jsonb,%s::jsonb,'mock','jev-mock',%s,'answered')",
        (sid, json.dumps({"choice": "sql_answer",
                          "confidence": confidence}), u()))
    cur.execute(
        "SELECT decision_id FROM decisions WHERE session_id=%s AND "
        "signal='intent' ORDER BY created_at DESC LIMIT 1", (sid,))
    return cur.fetchone()[0]


def events_of(cur, sid, etype):
    cur.execute(
        "SELECT payload FROM events WHERE session_id=%s AND type=%s "
        "ORDER BY at, seq", (sid, etype))
    return [r[0] for r in cur.fetchall()]


def main() -> int:
    server = get_server()
    setup_db()
    conn = psycopg2.connect(server.get_uri(DB))
    conn.autocommit = False
    cur = conn.cursor()
    guc(cur)
    src = PERIPHERY_SQL.read_text()
    norm = strip_sql_comments(src)

    # ============================== A 组 ==============================
    # A1 加载/形状/种子纪律
    cur.execute(
        "SELECT name, min(version), bool_and(active), count(*) FILTER "
        "(WHERE active) FROM v13_policies WHERE name IN "
        "('latches','cache_probe','shadow_flip','shadow_watch','intent_gate')"
        " GROUP BY name ORDER BY name")
    rows_a1 = cur.fetchall()
    check("A1: six new policy rows seeded v1-active (five names)",
          len(rows_a1) == 5 and all(r[1] == 1 and r[2] and r[3] == 1
                                    for r in rows_a1), rows_a1)
    cur.execute(
        "SELECT version, active FROM v13_policies WHERE name='generation' "
        "ORDER BY version")
    rows_gen = cur.fetchall()
    check("A1: generation v2 active, v1 archived",
          rows_gen == [(1, False), (2, True)], rows_gen)
    cur.execute(
        "SELECT count(*) FROM information_schema.columns WHERE "
        "table_name='sessions' AND column_name='spawn_kind'")
    check("A1: sessions.spawn_kind column present",
          cur.fetchone()[0] == 1)
    cur.execute(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE "
        "conrelid='sessions'::regclass AND contype='c' AND "
        "pg_get_constraintdef(oid) LIKE '%fresh_fork%'")
    cdef = cur.fetchone()
    check("A1: spawn_kind CHECK vocabulary (three kinds)",
          cdef is not None and all(k in cdef[0] for k in
          ("exact_replay", "recompute", "fresh_fork")), cdef)
    seed_stmt = src.split("INSERT INTO v13_policies")[1] \
        .split("UPDATE v13_policies")[0]
    check("A1: policy seeds single jsonb literal + ::jsonb (zero builders)",
          seed_stmt.count("'::jsonb") == 6
          and "jsonb_build_object" not in seed_stmt
          and "||" not in seed_stmt)

    # A2 翻版仪式 + 冻结不可变
    cur.execute(
        "INSERT INTO v13_policies (name, version, value, active) VALUES "
        "('generation', 3, '{\"provider\":\"mock\",\"model\":\"mock-1\","
        "\"system_blocks\":[],\"system_blocks_digest\":\"-none-\"}'::jsonb, "
        "false)")
    cur.execute("UPDATE v13_policies SET active=false WHERE "
                "name='generation' AND active")
    cur.execute("UPDATE v13_policies SET active=true WHERE "
                "name='generation' AND version=3")
    cur.execute("SELECT version FROM v13_policies WHERE "
                "name='generation' AND active")
    check("A2: generation v3 flipped active (double UPDATE ceremony)",
          cur.fetchone()[0] == 3)
    fails_with(cur,
               "UPDATE v13_policies SET value='{\"x\":1}'::jsonb WHERE "
               "name='generation' AND version=3", None,
               "immutable", "A2: policy value frozen (append-only)")
    policy_unflip(cur, "generation", 2)
    conn.commit()

    # A3 latch 触发器族
    sid_a = new_session(cur)
    conn.commit()
    cur.execute("INSERT INTO latches (session_id, name, value) VALUES "
                "(%s,'probe_latch','{\"v\":1}'::jsonb)", (sid_a,))
    conn.commit()
    fails_with(cur, "UPDATE latches SET value='{\"v\":2}'::jsonb WHERE "
               "session_id=%s", (sid_a,), "INSERT-once",
               "A3: latch UPDATE rejected (V3008)", pgcode="V3008")
    fails_with(cur, "DELETE FROM latches WHERE session_id=%s", (sid_a,),
               "INSERT-once", "A3: latch DELETE rejected (V3008)",
               pgcode="V3008")
    fails_with(cur, "TRUNCATE latches", None, "INSERT-once",
               "A3: latch TRUNCATE rejected by statement trigger (V3008)",
               pgcode="V3008")

    # A4 spawn 列不可变
    fails_with(cur,
               "UPDATE sessions SET parent_cutoff_seq=1 WHERE session_id=%s",
               (sid_a,), "write-once",
               "A4: fork columns UPDATE rejected (V3008)", pgcode="V3008")
    fails_with(cur,
               "UPDATE sessions SET spawn_kind='fresh_fork' WHERE "
               "session_id=%s", (sid_a,), "write-once",
               "A4: spawn_kind UPDATE rejected (V3008)", pgcode="V3008")
    cur.execute("UPDATE sessions SET status='completed' WHERE session_id=%s",
                (sid_a,))
    check("A4: non-fork column UPDATE untouched by guard",
          cur.rowcount == 1)
    conn.rollback()

    # A5 源码扫描(归一化)
    check("A5: zero '==>' operator", "==>" not in norm)
    check("A5: zero stannum-qualified refs", "stannum." not in norm)
    check("A5: zero typesafe_ask (no new Jev surface)",
          "typesafe_ask" not in norm)
    v3008 = norm.count("USING ERRCODE = 'V3008'")
    check("A5: new RAISEs all V3008 (count checkpoint=34)",
          v3008 == 34, v3008)
    raises = norm.count("RAISE EXCEPTION")
    errcoded = norm.count("USING ERRCODE")
    check("A5: RAISE/errcode paper checkpoint (104/97; bare 7 = verbatim "
          "copies: context_required per-input ×4 + refresh entry ×2 + "
          "blob_land produced_by ×1; validate RAISEs all carry ERRCODE)",
          raises == 104 and errcoded == 97, (raises, errcoded))

    # A6 ACL(双登录)
    sid_acl = new_session(cur)
    conn.commit()
    cur.execute("SET ROLE v13_route")
    cur.execute(
        "SELECT has_function_privilege('v13_latch_fire(uuid,text,jsonb)',"
        "'EXECUTE'), has_function_privilege('v13_fork(uuid,bigint,text,"
        "jsonb)','EXECUTE'), has_function_privilege('v13_cache_probe"
        "(uuid)','EXECUTE'), has_function_privilege('v13_shadow_observe"
        "(uuid)','EXECUTE'), has_function_privilege('v13_render(uuid,int)',"
        "'EXECUTE'), has_function_privilege('v13_render_wire(uuid,jsonb,"
        "int)','EXECUTE')")
    check("A6: route granted fire/fork/probe/observe/render/wire",
          cur.fetchone() == (True,) * 6)
    fire(cur, sid_acl, "acl_probe", {"who": "route"})
    cur.execute("SELECT count(*) FROM latches WHERE session_id=%s",
                (sid_acl,))
    check("A6: route can SELECT latches (real read)",
          cur.fetchone()[0] == 1)
    cur.execute("SELECT v13_cache_probe(%s)", (str(uuid.uuid4()),))
    check("A6: route real-exec probe no-op path (NULL on unknown effect)",
          cur.fetchone()[0] is None)
    cur.execute("RESET ROLE")
    cur.execute("SET ROLE v13_recall")
    cur.execute("SELECT v13_intent_gate(%s)", (sid_acl,))
    gate_acl = cur.fetchone()[0]
    cur.execute("SELECT v13_shadow_streak('render_policy', 99)")
    streak_acl = cur.fetchone()[0]
    check("A6: recall real-exec intent_gate + streak",
          gate_acl["mode"] == "superset"
          and streak_acl["observations"] == 0)
    fails_with(cur, "INSERT INTO latches (session_id, name, value) VALUES "
               "(%s,'nope','{}'::jsonb)", (sid_acl,), "permission",
               "A6: recall INSERT latches denied")
    cur.execute("RESET ROLE")
    cur.execute("SET ROLE v13_resolve")
    cur.execute(
        "SELECT has_function_privilege('v13_latch_fire(uuid,text,jsonb)',"
        "'EXECUTE'), has_function_privilege('v13_cache_probe(uuid)',"
        "'EXECUTE'), has_function_privilege('v13_intent_gate(uuid)',"
        "'EXECUTE'), has_function_privilege('v13_prefix_identity(uuid)',"
        "'EXECUTE')")
    privs_resolve = cur.fetchone()
    check("A6: resolve denied new faces, keeps manifest identity-family ACL",
          privs_resolve == (False, False, False, True), privs_resolve)
    cur.execute("RESET ROLE")
    cur.execute(
        "SELECT count(*) FROM pg_proc p WHERE p.proname IN "
        "('v13_latch_fire','v13_fork','v13_cache_probe','v13_intent_gate',"
        "'v13_shadow_observe') AND array_to_string(coalesce(p.proacl,"
        "'{}'::aclitem[]), ',') ~ '(^|,)='")
    check("A6: PUBLIC not granted on new functions (proacl negative)",
          cur.fetchone()[0] == 0)
    conn.commit()

    # ============================== B 组 ==============================
    # B1 INSERT once + fire adopt
    sid_b = new_session(cur)
    conn.commit()
    v1_b = fire(cur, sid_b, "band", {"tier": "normal"})
    v2_b = fire(cur, sid_b, "band", {"tier": "aggressive"})
    check("B1: repeated fire adopts existing (F13 read-back)",
          v1_b == v2_b == {"tier": "normal"}, (v1_b, v2_b))
    cur.execute("SELECT count(*) FROM latches WHERE session_id=%s AND "
                "name='band'", (sid_b,))
    check("B1: exactly one row per (sid,name)", cur.fetchone()[0] == 1)
    fails_with(cur, "INSERT INTO latches (session_id, name, value) VALUES "
               "(%s,'band','{\"tier\":\"x\"}'::jsonb)", (sid_b,),
               "duplicate key", "B1: second direct INSERT hits PK")

    # B2 并发首触发(F13)
    sid_b2 = new_session(cur)
    conn.commit()
    results_b2 = {}
    barrier = threading.Barrier(2)

    def fire_thread(key, val):
        c = psycopg2.connect(server.get_uri(DB))
        c.autocommit = False
        k = c.cursor()
        guc(k)
        barrier.wait()
        results_b2[key] = fire(k, sid_b2, "concurrent", val)
        c.commit()
        c.close()

    t1 = threading.Thread(target=fire_thread, args=("a", {"winner": "a"}))
    t2 = threading.Thread(target=fire_thread, args=("b", {"winner": "b"}))
    t1.start(); t2.start(); t1.join(); t2.join()
    cur.execute("SELECT count(*), count(DISTINCT value::text) FROM latches "
                "WHERE session_id=%s AND name='concurrent'", (sid_b2,))
    cnt_b2 = cur.fetchone()
    check("B2: concurrent first-fire lands exactly one row, one value",
          cnt_b2 == (1, 1), (cnt_b2, results_b2))
    check("B2: both connections read back the same winner value",
          results_b2["a"] == results_b2["b"], results_b2)

    # B3 admission 上限
    sid_b3 = new_session(cur)
    conn.commit()
    ok_all = True
    for i in range(16):
        try:
            fire(cur, sid_b3, f"latch_{i:02d}", {"i": i})
        except psycopg2.Error:
            ok_all = False
            conn.rollback()
            break
    check("B3: 16 latches within cap all land", ok_all)
    fails_with(cur, "SELECT v13_latch_fire(%s,'latch_16',"
               "'{\"i\":16}'::jsonb)", (sid_b3,), "cap reached",
               "B3: 17th latch V3008 fail-closed (admission)", pgcode="V3008")

    # B4 保留名
    fails_with(cur, "SELECT v13_latch_fire(%s,'generation',"
               "'{\"x\":1}'::jsonb)", (sid_b3,), "settle-reserved",
               "B4: public fire 'generation' rejected (V3008)",
               pgcode="V3008")

    # B5 digest
    sid_b5 = new_session(cur)
    conn.commit()
    fire(cur, sid_b5, "alpha", {"a": 1})
    fire(cur, sid_b5, "beta", {"b": 2})
    cur.execute("SELECT v13_latch_digest(%s), v13_latch_digest(%s)",
                (sid_b5, sid_b5))
    d1_b5, d2_b5 = cur.fetchone()
    check("B5: digest deterministic (same set, byte-equal)", d1_b5 == d2_b5)
    cur.execute("ALTER TABLE latches DISABLE TRIGGER trg_latches_immutable")
    cur.execute("UPDATE latches SET fired_at='2001-01-01T00:00:00Z' "
                "WHERE session_id=%s", (sid_b5,))
    cur.execute("ALTER TABLE latches ENABLE TRIGGER trg_latches_immutable")
    cur.execute("SELECT v13_latch_digest(%s)", (sid_b5,))
    check("B5: fired_at not in digest material (timestamp ≠ content)",
          cur.fetchone()[0] == d1_b5)
    sid_b5e = new_session(cur)
    conn.commit()
    cur.execute("SELECT v13_latch_digest(%s)", (sid_b5e,))
    check("B5: empty set digest == '-none-' (DP3 stub byte-link)",
          cur.fetchone()[0] == "-none-")

    # ============================== C 组 ==============================
    # C1 首 settle 自动首发
    sid_c1 = new_session(cur)
    append_user(cur, sid_c1, "hello world goal")
    conn.commit()
    full_settle(cur, sid_c1)
    conn.commit()
    cur.execute("SELECT value FROM latches WHERE session_id=%s AND "
                "name='generation'", (sid_c1,))
    latch_c1 = cur.fetchone()[0]
    gen2_c1 = policy_value(cur, "generation")
    check("C1: first settle auto-fires generation latch (row snapshot)",
          latch_c1 is not None
          and latch_c1["provider"] == gen2_c1["provider"]
          and latch_c1["model"] == gen2_c1["model"]
          and latch_c1["generation_version"] == 2, latch_c1)
    full_settle(cur, sid_c1)
    conn.commit()
    cur.execute("SELECT count(*) FROM latches WHERE session_id=%s AND "
                "name='generation'", (sid_c1,))
    check("C1: second settle adopts (no new generation row)",
          cur.fetchone()[0] == 1)

    # C2/C3 mid-session 翻版安全绳(ch14.5 redeploy)+ 未 pin 追动
    cur.execute("SELECT v13_prefix_identity(%s)", (sid_c1,))
    ident_before_c2 = cur.fetchone()[0]
    cur.execute("SELECT v13_context_fresh(%s)", (sid_c1,))
    fresh_before_c2 = cur.fetchone()[0]
    v4_val = {"provider": "mock", "model": "mock-9",
              "system_blocks": [], "system_blocks_digest": "-none-",
              "note": "c2"}
    # 运维纪律实证:翻 v3+ 模型必须同批补 v13_pricing 行,否则 er 块
    # e_base 为 NULL → validate V3007 fail-loud(README ③ 记档)
    cur.execute(
        "INSERT INTO v13_pricing (provider, model, account, cache_class, "
        "fresh_usd_per_mtok, cached_usd_per_mtok, catalog_version, "
        "effective_from, effective_to, active) VALUES "
        "('mock', 'mock-9', 'default', 'default', 3.000000, 0.750000, 1, "
        "'2026-09-23 00:00:00+00'::timestamptz, NULL, true)")
    policy_flip(cur, "generation", 4, v4_val)
    cur.execute("SELECT v13_prefix_identity(%s)", (sid_c1,))
    ident_after_c2 = cur.fetchone()[0]
    cur.execute("SELECT v13_context_fresh(%s)", (sid_c1,))
    fresh_after_c2 = cur.fetchone()[0]
    check("C2: pinned session identity byte-stable across mid-session flip",
          ident_before_c2 == ident_after_c2 and fresh_before_c2
          and fresh_after_c2, (ident_before_c2, ident_after_c2))
    sid_c3 = new_session(cur)
    conn.commit()
    cur.execute("SELECT v13_context_required(%s)->>'gen_ver'", (sid_c3,))
    check("C3: unpinned session chases active row (gen_ver=v4)",
          cur.fetchone()[0] == "4")
    cur.execute("SELECT v13_context_required(%s)->>'gen_ver'", (sid_c1,))
    check("C3: pinned session gen_ver frozen at latch version",
          cur.fetchone()[0] == "2")
    full_settle(cur, sid_c3)
    conn.commit()
    cur.execute("SELECT value->>'model' FROM latches WHERE session_id=%s "
                "AND name='generation'", (sid_c3,))
    check("C3: new session first settle takes v4 (fresh fork source)",
          cur.fetchone()[0] == "mock-9")
    policy_unflip(cur, "generation", 2)
    conn.commit()

    # C4 render_policy 翻版追动(DP7 §1.4 兑现)
    cur.execute("SELECT v13_prefix_identity(%s), v13_context_required(%s)"
                "->>'ident_ver'", (sid_c1, sid_c1))
    ident_c4, iv_c4 = cur.fetchone()
    policy_flip(cur, "render_policy", 2, {
        "renderer": "canonical", "cache_markers": True,
        "provider_policy": "protocol_only", "note": "c4 same-output"})
    cur.execute("SELECT v13_prefix_identity(%s), v13_context_required(%s)"
                "->>'ident_ver'", (sid_c1, sid_c1))
    ident_c4b, iv_c4b = cur.fetchone()
    check("C4: render_policy flip moves identity (9th material key)",
          ident_c4 != ident_c4b)
    cur.execute("SELECT v13_context_fresh(%s)", (sid_c1,))
    check("C4: ident_ver chases (token stale, one refresh owed)",
          iv_c4 != iv_c4b and cur.fetchone()[0] is False)
    full_settle(cur, sid_c1)
    conn.commit()
    cur.execute("SELECT v13_context_fresh(%s)", (sid_c1,))
    check("C4: single refresh re-freshes", cur.fetchone()[0] is True)
    policy_unflip(cur, "render_policy", 1)
    full_settle(cur, sid_c1)
    conn.commit()

    # C5 latch 追动
    cur.execute("SELECT v13_context_required(%s)->>'ident_ver'",
                (sid_c1,))
    iv_c5 = cur.fetchone()[0]
    cur.execute("SELECT v13_prefix_identity(%s)", (sid_c1,))
    pid_c5 = cur.fetchone()[0]
    fire(cur, sid_c1, "cache_scope", {"eligible": True})
    conn.commit()
    cur.execute("SELECT v13_context_required(%s)->>'ident_ver'",
                (sid_c1,))
    iv_c5b = cur.fetchone()[0]
    cur.execute("SELECT v13_prefix_identity(%s)", (sid_c1,))
    pid_c5b = cur.fetchone()[0]
    cur.execute("SELECT v13_context_fresh(%s)", (sid_c1,))
    check("C5: new latch moves ident_ver + identity (latch_digest material)",
          iv_c5 != iv_c5b and pid_c5 != pid_c5b
          and cur.fetchone()[0] is False)
    full_settle(cur, sid_c1)
    conn.commit()
    cur.execute("SELECT v13_context_fresh(%s)", (sid_c1,))
    check("C5: refresh consumes latch chase", cur.fetchone()[0] is True)

    # C6 九键材料 + 负向
    cur.execute("SELECT pg_get_functiondef('v13_prefix_identity(uuid)'"
                "::regprocedure)")
    defn_pi = cur.fetchone()[0]
    keys_pi = ["'provider'", "'model'", "'system_blocks_digest'",
               "'tools_rev'", "'tools_digest'", "'goal_hash'",
               "'latch_digest'", "'render_policy_version'",
               "'manifest_version'"]
    check("C6: prefix_identity material = nine keys (structure)",
          all(k in defn_pi for k in keys_pi)
          and defn_pi.count("jsonb_build_object") == 1, defn_pi[:80])
    sid_c6 = new_session(cur)
    conn.commit()
    cur.execute("UPDATE v13_policies SET active=false WHERE "
                "name='generation'")
    fails_with(cur, "SELECT v13_prefix_identity(%s)", (sid_c6,),
               "no active generation",
               "C6: killed generation row → V3008 (unpinned session)",
               pgcode="V3008")
    cur.execute("UPDATE v13_policies SET active=true WHERE "
                "name='generation' AND version=2")
    cur.execute("UPDATE v13_policies SET active=false WHERE "
                "name='render_policy'")
    fails_with(cur, "SELECT v13_prefix_identity(%s)", (sid_c6,),
               "no active render_policy",
               "C6: killed render_policy row → V3008", pgcode="V3008")
    cur.execute("UPDATE v13_policies SET active=true WHERE "
                "name='render_policy' AND version=1")
    conn.commit()

    # ============================== D 组 ==============================
    # D1 纯函数确定性 + wire 重现
    cur.execute("SELECT v13_render(%s)::text", (sid_c1,))
    w1 = cur.fetchone()[0]
    cur.execute("SELECT v13_render(%s)::text", (sid_c1,))
    w2 = cur.fetchone()[0]
    cur.execute("SELECT v13_render(%s)::text", (sid_c1,))
    w3 = cur.fetchone()[0]
    check("D1: render triple-call byte-equal (pure function)",
          w1 == w2 == w3)
    cur.execute(
        "SELECT encode(digest(v13_render_wire(%s, a.inline)::text,'sha256'),"
        "'hex') FROM artifacts a WHERE a.artifact_id="
        "(SELECT context_active_artifact FROM sessions WHERE session_id=%s)",
        (sid_c1, sid_c1))
    wire_digest_replay = cur.fetchone()[0]
    cur.execute(
        "SELECT a.inline->'render'->>'wire_digest' FROM artifacts a WHERE "
        "a.artifact_id=(SELECT context_active_artifact FROM sessions WHERE "
        "session_id=%s)", (sid_c1,))
    check("D1: wire re-derivation equals settle-frozen wire_digest "
          "(不落库纪律的可重现面)",
          wire_digest_replay == cur.fetchone()[0])

    # D2 wire 结构
    wire_d2 = json.loads(w1)
    check("D2: wire outer keys exactly {system,tools,sections}",
          sorted(wire_d2.keys()) == ["sections", "system", "tools"])
    secs_d2 = wire_d2["sections"]
    check("D2: every section {id,marker,body} three keys",
          len(secs_d2) > 0 and all(sorted(s.keys()) == ["body", "id",
                                                        "marker"]
                                    for s in secs_d2))
    check("D2: marker carries section_id + cache_scope (cache_markers:true)",
          all(s["marker"].startswith("[v13-section:")
              and ":cache_scope=" in s["marker"] for s in secs_d2),
          secs_d2[0]["marker"] if secs_d2 else None)

    # D3 tools 同源
    cur.execute(
        "SELECT (v13_render(%s)->'tools')::text = (v13_canonical_state(%s)"
        "->'tools')::text", (sid_c1, sid_c1))
    check("D3: render.tools byte-equal to identity tools_digest source "
          "(single source)", cur.fetchone()[0] is True)

    # D4 system blocks 通道(owner blob 落地→v3 翻版→按序;tamper/缺失)
    sid_d4 = new_session(cur)
    conn.commit()
    eff_d4 = llm_succeed(cur, sid_d4, {}, "land system blocks")
    conn.commit()
    cur.execute("SELECT v13_blob_land(%s, to_jsonb('system block one'::text)"
                ", 'system_block')", (eff_d4,))
    h1_d4 = cur.fetchone()[0]
    cur.execute("SELECT v13_blob_land(%s, to_jsonb('system block two'::text)"
                ", 'system_block')", (eff_d4,))
    h2_d4 = cur.fetchone()[0]
    conn.commit()
    digest_expr = ("SELECT coalesce(encode(digest(jsonb_agg(b.inline "
                   "ORDER BY o.ord)::text,'sha256'),'hex'),'-none-') FROM "
                   "jsonb_array_elements(%s::jsonb) WITH ORDINALITY o(h,ord) "
                   "LEFT JOIN artifacts b ON b.content_hash=o.h->>'content_"
                   "hash' AND b.kind='system_block'")
    cur.execute(digest_expr,
                (json.dumps([{"content_hash": h1_d4},
                             {"content_hash": h2_d4}]),))
    dig_d4 = cur.fetchone()[0]
    policy_flip(cur, "generation", 5, {
        "provider": "mock", "model": "mock-1",
        "system_blocks": [{"content_hash": h1_d4},
                          {"content_hash": h2_d4}],
        "system_blocks_digest": dig_d4, "note": "d4"})
    sid_d4b = new_session(cur)
    append_user(cur, sid_d4b, "render with system blocks")
    conn.commit()
    full_settle(cur, sid_d4b)
    conn.commit()
    cur.execute("SELECT v13_render(%s)->'system'", (sid_d4b,))
    sys_d4 = cur.fetchone()[0]
    check("D4: render.system returns both blocks in order",
          sys_d4 == ["system block one", "system block two"], sys_d4)
    # tamper blob 内容 → settle 守卫 digest 校验 RAISE(owner 直改;
    # 事务内 DROP CONSTRAINT+DISABLE TRIGGER 使 UPDATE 可达,失败后整
    # 事务 rollback 即恢复原状——比手工还原更干净的 fixture 仪式)
    cur.execute("ALTER TABLE artifacts DROP CONSTRAINT "
                "v13_artifacts_selfcheck")
    cur.execute("ALTER TABLE artifacts DISABLE TRIGGER "
                "trg_artifacts_append_only")
    cur.execute("UPDATE artifacts SET inline='\"tampered block\"'::jsonb "
                "WHERE content_hash=%s AND kind='system_block'", (h1_d4,))
    sid_d4c = new_session(cur)
    append_user(cur, sid_d4c, "tampered settle")
    m_d4c = assemble(cur, sid_d4c)
    append(cur, sid_d4c, "turn/route", {"action": "refresh"})
    cur.execute("SELECT v13_enqueue_effect(%s,'context_refresh',"
                "jsonb_build_object('goal_hash',%s))",
                (sid_d4c, m_d4c["required_revision"]["goal"]))
    eff_d4c = cur.fetchone()[0]
    cur.execute("SELECT v13_claim('t')")
    cl_d4c = cur.fetchone()[0]
    fails_with(cur, "SELECT v13_refresh_context(%s,%s,%s)",
               (eff_d4c, cl_d4c["attempt_no"], cl_d4c["fence"]),
               "digest mismatch",
               "D4: tampered system block blob → settle guard V3008",
               pgcode="V3008")
    conn.rollback()
    # 列表指向缺失 blob → render fail-closed(fresh fork overrides 形态;
    # 先 append 一条事件使 cutoff=0 落在 [0, next_seq-1] 界内)
    sid_d4d = new_session(cur)
    append_user(cur, sid_d4d, "missing blob fixture")
    conn.commit()
    cur.execute("SELECT v13_fork(%s, 0, 'fresh_fork', %s::jsonb)",
                (sid_d4d, json.dumps({"system_blocks": [
                    {"content_hash": "f" * 64}]})))
    sid_d4e = cur.fetchone()[0]
    conn.commit()
    fails_with(cur, "SELECT v13_render_wire(%s, '{}'::jsonb)", (sid_d4e,),
               "system block blob missing",
               "D4: missing system block blob → render fail-closed (V3008)",
               pgcode="V3008")
    policy_unflip(cur, "generation", 2)
    conn.commit()

    # D5 render 块进 manifest v3 + est 公式
    _, m_d5 = refresh_n(cur, sid_c1,
                        assemble(cur, sid_c1)["required_revision"]["goal"])
    conn.commit()
    keys_d5 = sorted(m_d5.keys())
    check("D5: manifest v3 outer keys == 12 (with render)",
          keys_d5 == sorted(["manifest_version", "session_id", "turn_no",
                             "prefix_identity", "policy", "required_revision",
                             "economics", "sections", "query_side",
                             "judgments", "replay", "render"])
          and m_d5["manifest_version"] == 3, keys_d5)
    rkeys_d5 = sorted(m_d5["render"].keys())
    check("D5: render block exactly 4 keys",
          rkeys_d5 == ["render_policy_version", "renderer",
                       "stable_prefix_est_tokens", "wire_digest"]
          and re.fullmatch(r"[0-9a-f]{64}",
                           m_d5["render"]["wire_digest"]) is not None
          and m_d5["render"]["stable_prefix_est_tokens"] >= 0, rkeys_d5)
    cur.execute(
        "WITH w AS (SELECT v13_render(%s) AS wire), div AS (SELECT "
        "(v13_policy('assemble_manifest')->>'est_bytes_per_token')::int AS d)"
        " SELECT ((coalesce(octet_length((w.wire->'system')::text),0) + "
        "coalesce(octet_length((w.wire->'tools')::text),0) + coalesce(("
        "SELECT sum(octet_length(jsonb_build_object('id', s->>'section_id',"
        "'body', v13_render_section_body(%s, s))::text)) FROM "
        "jsonb_array_elements(%s::jsonb) s WHERE (s->>'churn')::int = 0),0)"
        " + div.d - 1) / div.d)::int FROM w, div",
        (sid_c1, sid_c1, json.dumps(m_d5["sections"])))
    est_expected = cur.fetchone()[0]
    check("D5: est matches DP3 formula (same divisor, int arithmetic)",
          est_expected == m_d5["render"]["stable_prefix_est_tokens"],
          (est_expected, m_d5["render"]["stable_prefix_est_tokens"]))

    # D6 空表衔接
    cur.execute("SELECT value->>'system_blocks_digest', "
                "value->'system_blocks' FROM latches WHERE session_id=%s "
                "AND name='generation'", (sid_c1,))
    d6 = cur.fetchone()
    check("D6: empty system_blocks session digest '-none-' (DP3 link)",
          d6 == ("-none-", []), d6)
    f1_d6, f2_d6 = new_session(cur), new_session(cur)
    conn.commit()
    cur.execute("SELECT v13_prefix_identity(%s) = v13_prefix_identity(%s)",
                (f1_d6, f2_d6))
    check("D6: two empty sessions identity-comparable (equal)",
          cur.fetchone()[0] is True)

    # D7 钉版本(shadow 面)
    cur.execute(
        "INSERT INTO v13_policies (name, version, value, active) VALUES "
        "('render_policy', 9, '{\"renderer\":\"canonical\","
        "\"cache_markers\":false,\"provider_policy\":\"protocol_only\","
        "\"note\":\"d7 marker-off\"}'::jsonb, false)")
    conn.commit()
    cur.execute("SELECT encode(digest(v13_render(%s, 9)::text,'sha256'),"
                "'hex') = encode(digest(v13_render(%s)::text,'sha256'),"
                "'hex')", (sid_c1, sid_c1))
    check("D7: pinned-version render differs (marker-off variant)",
          cur.fetchone()[0] is False)

    # ============================== E 组 ==============================
    # E1 exact_replay@settle 点
    sid_e1 = new_session(cur)
    append_user(cur, sid_e1, "fork me about /a/b and id 7")
    append(cur, sid_e1, "llm/message",
           {"text": "reply one " + "z " * 120, "origin_user_seq": 0})
    conn.commit()
    full_settle(cur, sid_e1)
    conn.commit()
    art_e1 = active_artifact(cur, sid_e1)
    cur.execute("SELECT inline FROM artifacts WHERE artifact_id=%s",
                (art_e1,))
    man_e1 = cur.fetchone()[0]
    cut_e1 = man_e1["required_revision"]["sem"]
    cur.execute("SELECT v13_fork(%s, %s, 'exact_replay')", (sid_e1, cut_e1))
    child_e1 = cur.fetchone()[0]
    conn.commit()
    cur.execute("SELECT context_active_artifact FROM sessions WHERE "
                "session_id=%s", (child_e1,))
    check("E1: child inherits parent artifact pointer",
          cur.fetchone()[0] == art_e1)
    cur.execute("SELECT v13_replay(%s)", (art_e1,))
    rep_e1 = cur.fetchone()[0]
    strip_replay = lambda d: {k: v for k, v in d.items()
                               if k != "replay"}
    check("E1: replay(child artifact) byte-equal to parent manifest "
          "(content minus replay key)",
          strip_replay(rep_e1) == strip_replay(man_e1)
          and rep_e1["replay"]["mode"] == "exact_replay"
          and rep_e1["replay"]["source_artifact"] == art_e1)
    evs_e1 = events_of(cur, child_e1, "forked")
    check("E1: forked event present with identity pair",
          len(evs_e1) == 1 and evs_e1[0]["kind"] == "exact_replay"
          and evs_e1[0]["parent_identity"] == evs_e1[0]["child_identity"]
          and evs_e1[0]["parent_identity"] == man_e1["prefix_identity"],
          evs_e1)

    # E2 三种 spawn 可区分
    kids_e2 = {}
    for kind in ("exact_replay", "recompute", "fresh_fork"):
        cur.execute("SELECT v13_fork(%s, %s, %s)",
                    (sid_e1, cut_e1, kind))
        kids_e2[kind] = cur.fetchone()[0]
        conn.commit()
    cur.execute(
        "SELECT spawn_kind FROM sessions WHERE session_id IN %s "
        "ORDER BY spawn_kind", (tuple(kids_e2.values()),))
    kinds_e2 = [r[0] for r in cur.fetchall()]
    check("E2: three spawn_kind values distinct (ch14.4 不得混称)",
          sorted(kinds_e2) == ["exact_replay", "fresh_fork", "recompute"])
    payloads_e2 = {}
    for kind, kid in kids_e2.items():
        evs = events_of(cur, kid, "forked")
        payloads_e2[kind] = evs[0] if evs else None
    check("E2: forked payload kinds distinct + identity pair present",
          len({p["kind"] for p in payloads_e2.values()}) == 3
          and all(p["child_identity"] for p in payloads_e2.values()))
    ptrs_e2 = []
    for kind, kid in kids_e2.items():
        cur.execute("SELECT context_active_artifact FROM sessions WHERE "
                    "session_id=%s", (kid,))
        ptrs_e2.append(cur.fetchone()[0])
    check("E2: exact/recompute inherit pointer, fresh none",
          ptrs_e2[0] == art_e1 and ptrs_e2[1] == art_e1
          and ptrs_e2[2] is None, ptrs_e2)

    # E3 越界/无覆盖
    fails_with(cur, "SELECT v13_fork(%s, 999999, 'exact_replay')",
               (sid_e1,), "out of bounds",
               "E3: cutoff beyond next_seq → V3008 zero rows",
               pgcode="V3008")
    sid_e3 = new_session(cur)
    append_user(cur, sid_e3, "never settled early")
    append(cur, sid_e3, "llm/message",
           {"text": "r " + "z " * 80, "origin_user_seq": 0})
    conn.commit()
    full_settle(cur, sid_e3)
    conn.commit()
    cur.execute("SELECT next_seq FROM sessions WHERE session_id=%s",
                (sid_e3,))
    fails_with(cur, "SELECT v13_fork(%s, %s, 'exact_replay')",
               (sid_e3, 0), "no context artifact covers",
               "E3: cutoff before first settle coverage → V3008",
               pgcode="V3008")
    cur.execute("SELECT count(*) FROM sessions WHERE parent_session_id=%s",
                (sid_e3,))
    check("E3: rejected forks leave zero child rows",
          cur.fetchone()[0] == 0)

    # E4 身份漂移四负向
    cur.execute("SELECT count(*) FROM sessions WHERE parent_session_id=%s",
                (sid_e1,))
    kids_before_e4 = cur.fetchone()[0]
    fire(cur, sid_e1, "post_freeze", {"drift": True})
    conn.commit()
    fails_with(cur, "SELECT v13_fork(%s, %s, 'exact_replay')",
               (sid_e1, cut_e1), "identity drift",
               "E4-①: parent latch after freeze → V3008", pgcode="V3008")
    cur.execute("SAVEPOINT e4b")
    cur.execute("UPDATE tools SET description='bumped for e4 probe' "
                "WHERE name=(SELECT name FROM tools LIMIT 1)")
    fails_with(cur, "SELECT v13_fork(%s, %s, 'exact_replay')",
               (sid_e1, cut_e1), "identity drift",
               "E4-②: tools catalog bump → V3008", pgcode="V3008")
    cur.execute("ROLLBACK TO SAVEPOINT e4b")
    fails_with(cur, "SELECT v13_fork(%s, %s, 'exact_replay', "
               "'{\"x\":1}'::jsonb)", (sid_e1, cut_e1),
               "overrides require fresh_fork",
               "E4-③: overrides + identity-claiming kind → V3008",
               pgcode="V3008")
    sid_e4 = new_session(cur)
    append_user(cur, sid_e4, "e4 goal drift base")
    conn.commit()
    full_settle(cur, sid_e4)
    conn.commit()
    cur.execute("SELECT inline->'required_revision'->>'sem' FROM artifacts "
                "WHERE artifact_id=%s", (active_artifact(cur, sid_e4),))
    sem_e4 = int(cur.fetchone()[0])
    seq_after_e4 = append_user(
        cur, sid_e4, "message after settle, before next settle")
    conn.commit()
    check("E4-④-fixture: post-settle user message lands past artifact sem",
          seq_after_e4 > sem_e4, (sem_e4, seq_after_e4))
    fails_with(cur, "SELECT v13_fork(%s, %s, 'exact_replay')",
               (sid_e4, seq_after_e4), "identity drift",
               "E4-④: cutoff past covering artifact over new user goal → "
               "V3008 (fail-closed correct behavior)", pgcode="V3008")
    cur.execute("SELECT count(*) FROM sessions WHERE parent_session_id IN "
                "(%s,%s)", (sid_e1, sid_e4))
    check("E4: all four rejections leave zero child rows",
          cur.fetchone()[0] == kids_before_e4)

    # E5 fresh fork + overrides
    ovr_e5 = {"model": "mock-9", "thinking_budget": "high"}
    cur.execute("SELECT v13_fork(%s, %s, 'fresh_fork', %s::jsonb)",
                (sid_e1, cut_e1, json.dumps(ovr_e5)))
    child_e5 = cur.fetchone()[0]
    conn.commit()
    cur.execute("SELECT value FROM latches WHERE session_id=%s AND "
                "name='generation'", (child_e5,))
    latch_e5 = cur.fetchone()[0]
    check("E5: overrides land in child generation latch (关系化 clamp)",
          latch_e5["model"] == "mock-9"
          and latch_e5["thinking_budget"] == "high", latch_e5)
    ev_e5 = events_of(cur, child_e5, "forked")[0]
    check("E5: forked payload carries overrides + child identity",
          ev_e5["overrides"] == ovr_e5
          and ev_e5["child_identity"] is not None)
    cur.execute("SELECT v13_fork(%s, %s, 'fresh_fork')",
                (sid_e1, cut_e1))
    child_e5b = cur.fetchone()[0]
    conn.commit()
    cur.execute("SELECT v13_prefix_identity(%s)", (child_e5b,))
    ident_e5b = cur.fetchone()[0]
    check("E5: plain fresh at settle-aligned cutoff may equal parent "
          "artifact identity (cache hit, legal — L4 P1-2)",
          ident_e5b == man_e1["prefix_identity"])

    # E6 goal_hash 前缀感知回归
    cur.execute(
        "SELECT v13_goal_hash(%s) = coalesce((SELECT g.content_hash FROM "
        "v13_goals g WHERE g.session_id=%s ORDER BY g.seq DESC LIMIT 1), "
        "encode(digest(''::text,'sha256'),'hex'))", (sid_e1, sid_e1))
    check("E6: non-fork goal_hash byte-equal to ≤13号 formula",
          cur.fetchone()[0] is True)
    cur.execute(
        "SELECT v13_goal_hash(%s) = (SELECT g.content_hash FROM v13_goals g "
        "WHERE g.session_id=%s AND g.seq <= %s ORDER BY g.seq DESC LIMIT 1)",
        (child_e1, sid_e1, cut_e1))
    check("E6: fork child (no own goal) = parent goal @cutoff",
          cur.fetchone()[0] is True)

    # E7 冻结隔离
    cur.execute("SELECT v13_prefix_identity(%s)", (child_e1,))
    ident_e7 = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM latches WHERE session_id=%s",
                (child_e1,))
    latches_e7 = cur.fetchone()[0]
    append_user(cur, sid_e1, "parent keeps moving after fork")
    fire(cur, sid_e1, "post_fork_drift", {"more": True})
    conn.commit()
    cur.execute("SELECT v13_prefix_identity(%s)", (child_e1,))
    ident_e7b = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM latches WHERE session_id=%s",
                (child_e1,))
    check("E7: child identity + latch set isolated from parent drift",
          ident_e7 == ident_e7b
          and cur.fetchone()[0] == latches_e7)

    # E8 O(1) 结构(源码断言)
    cur.execute("SELECT pg_get_functiondef('v13_fork(uuid,bigint,text,"
                "jsonb)'::regprocedure)")
    fork_def = strip_sql_comments(cur.fetchone()[0])
    check("E8: fork body zero `FROM events` (O(1) 除事件结构)",
          "from events" not in fork_def.lower())

    # ============================== F 组 ==============================
    # 大 fixture:est 需 > 1024(默认 min_tokens),且 < 5120(est*0.2<1024)。
    # est 语义=稳定前缀(已落地 blob 的段):首次装配时当前材料 blob 尚未落
    # 地不计——先 settle 落 blob,再经 latch 追动(token 变化,非 exact
    # replay)重 settle,材料不变而 blob 已在 ⇒ est 含 history(README 记档)
    sid_f = new_session(cur)
    for i in range(1, 6):
        append_user(cur, sid_f, f"turn {i} about file /f/g/{i} and id {i}")
        append(cur, sid_f, "llm/message",
               {"text": f"reply {i} " + "z " * 400,
                "origin_user_seq": i * 2 - 2})
        conn.commit()
    full_settle(cur, sid_f)
    conn.commit()
    fire(cur, sid_f, "probe_anchor", {"scope": "stable"})
    conn.commit()
    full_settle(cur, sid_f)
    conn.commit()
    cur.execute("SELECT inline->'render'->>'stable_prefix_est_tokens' FROM "
                "artifacts WHERE artifact_id=%s", (active_artifact(cur,
                                                                   sid_f),))
    est_f = int(cur.fetchone()[0])
    check("F-fixture: est in (1024, 5120) window for default tolerance",
          1024 < est_f < 5120, est_f)
    art_f = active_artifact(cur, sid_f)
    wd_f = None
    cur.execute("SELECT inline->'render'->>'wire_digest' FROM artifacts "
                "WHERE artifact_id=%s", (art_f,))
    wd_f = cur.fetchone()[0]

    # F1 差额
    eff_f1 = llm_succeed(cur, sid_f, {"context_artifact_id": art_f},
                         "f1 gap")
    conn.commit()
    cur.execute("SELECT v13_cache_probe(%s)", (eff_f1,))
    probe_f1 = cur.fetchone()[0]
    evs_f1 = events_of(cur, sid_f, "audit/cache_probe")
    check("F1: estimate_gap event exactly once with expected/actual",
          probe_f1 == {"probed": True, "event": True}
          and len(evs_f1) == 1
          and evs_f1[0]["basis"] == "estimate_gap"
          and evs_f1[0]["expected_tokens"] == est_f
          and evs_f1[0]["actual_tokens"] == 0, (probe_f1, evs_f1))

    # F2 干净
    eff_f2 = llm_succeed(cur, sid_f, {
        "context_artifact_id": art_f,
        "usage": {"completion_tokens": 5,
                  "cache_read_input_tokens": est_f}}, "f2 clean")
    conn.commit()
    cur.execute("SELECT v13_cache_probe(%s)", (eff_f2,))
    probe_f2 = cur.fetchone()[0]
    evs_f2 = events_of(cur, sid_f, "audit/cache_probe")
    check("F2: within tolerance → zero new events, {probed,event:false}",
          probe_f2 == {"probed": True, "event": False}
          and len(evs_f2) == 1, (probe_f2, len(evs_f2)))

    # F3 no-op 形态
    eff_f3 = llm_succeed(cur, sid_f, {
        "context_artifact_id": art_f, "usage": None}, "f3 no-usage")
    conn.commit()
    cur.execute("SELECT v13_cache_probe(%s)", (eff_f3,))
    probe_f3 = cur.fetchone()[0]
    evs_f3 = events_of(cur, sid_f, "audit/cache_probe")
    check("F3: usage missing → no-op zero events (missing≠error)",
          probe_f3 == {"probed": True, "event": False}
          and len(evs_f3) == 1)
    cur.execute("SELECT v13_cache_probe(%s)", (str(uuid.uuid4()),))
    check("F3: unknown/non-llm effect → NULL no-op",
          cur.fetchone()[0] is None)

    # F4 wire 完整性(可与 estimate_gap 叠加恰两条)
    eff_f4 = llm_succeed(cur, sid_f, {
        "context_artifact_id": art_f, "wire_digest": "ab" * 32},
        "f4 wire mismatch")
    conn.commit()
    cur.execute("SELECT v13_cache_probe(%s)", (eff_f4,))
    evs_f4 = events_of(cur, sid_f, "audit/cache_probe")
    bases_f4 = [e["basis"] for e in evs_f4[-2:]]
    check("F4: forged wire_digest → wire_mismatch stacks with "
          "estimate_gap (exactly two)",
          bases_f4 == ["wire_mismatch", "estimate_gap"], evs_f4)

    # F5 纯审计(行级对照)
    cur.execute("SELECT (SELECT count(*) FROM sessions), (SELECT count(*) "
                "FROM effects), (SELECT count(*) FROM artifacts), "
                "(SELECT result FROM effects WHERE effect_id=%s)",
                (eff_f1,))
    before_f5 = cur.fetchone()
    cur.execute("SELECT v13_cache_probe(%s)", (eff_f1,))
    cur.fetchone()
    cur.execute("SELECT (SELECT count(*) FROM sessions), (SELECT count(*) "
                "FROM effects), (SELECT count(*) FROM artifacts), "
                "(SELECT result FROM effects WHERE effect_id=%s)",
                (eff_f1,))
    after_f5 = cur.fetchone()
    check("F5: probe is pure audit (zero row changes, effect result intact)",
          before_f5 == after_f5, (before_f5, after_f5))

    # F6 对账锚竞态免疫
    full_settle(cur, sid_f)
    conn.commit()
    art_f6 = active_artifact(cur, sid_f)
    check("F6-fixture: pointer moved after complete",
          art_f6 != art_f)
    cur.execute("SELECT v13_cache_probe(%s)", (eff_f1,))
    cur.fetchone()
    evs_f6 = events_of(cur, sid_f, "audit/cache_probe")
    last_f6 = evs_f6[-1]
    check("F6: probe still reads OLD artifact render via result anchor "
          "(immune to pointer race)",
          last_f6["basis"] == "estimate_gap"
          and last_f6["expected_tokens"] == est_f, last_f6)

    # ============================== G 组 ==============================
    sid_g = new_session(cur)
    append_user(cur, sid_g, "shadow fixture goal")
    conn.commit()
    full_settle(cur, sid_g)
    conn.commit()
    check("G1: production targets=[] → zero shadow_obs events",
          len(events_of(cur, sid_g, "audit/shadow_obs")) == 0)

    # G2 render 族双跑
    policy_flip(cur, "shadow_watch", 2, {"targets": ["render_policy"]})
    cur.execute(
        "INSERT INTO v13_policies (name, version, value, active) VALUES "
        "('render_policy', 21, '{\"renderer\":\"canonical\","
        "\"cache_markers\":true,\"provider_policy\":\"protocol_only\","
        "\"note\":\"g2 same-output\"}'::jsonb, false)")
    conn.commit()
    full_settle(cur, sid_g)
    conn.commit()
    evs_g2 = events_of(cur, sid_g, "audit/shadow_obs")
    check("G2: same-output shadow variant → content_equal=true",
          len(evs_g2) == 1 and evs_g2[0]["content_equal"] is True
          and evs_g2[0]["shadow_version"] == 21, evs_g2)
    cur.execute(
        "INSERT INTO v13_policies (name, version, value, active) VALUES "
        "('render_policy', 22, '{\"renderer\":\"canonical\","
        "\"cache_markers\":false,\"provider_policy\":\"protocol_only\","
        "\"note\":\"g2 marker-off\"}'::jsonb, false)")
    conn.commit()
    full_settle(cur, sid_g)
    conn.commit()
    evs_g2b = events_of(cur, sid_g, "audit/shadow_obs")
    check("G2: marker-off shadow variant → content_equal=false",
          evs_g2b[-1]["content_equal"] is False
          and evs_g2b[-1]["shadow_version"] == 22, evs_g2b[-1])

    # G3 assemble 族双跑(shadow 版本保持 inactive,active 恒 v1)
    asm_v1 = policy_value(cur, "assemble_manifest")
    policy_flip(cur, "shadow_watch", 3, {"targets": ["assemble_manifest"]})
    cur.execute(
        "INSERT INTO v13_policies (name, version, value, active) VALUES "
        "('assemble_manifest', 21, %s::jsonb, false)",
        (json.dumps(asm_v1),))
    conn.commit()
    full_settle(cur, sid_g)
    conn.commit()
    evs_g3 = [e for e in events_of(cur, sid_g, "audit/shadow_obs")
              if e["name"] == "assemble_manifest"]
    check("G3: same-value assemble shadow → content_equal=true "
          "(projection strips version-only blocks)",
          len(evs_g3) == 1 and evs_g3[0]["content_equal"] is True
          and evs_g3[0]["shadow_version"] == 21, evs_g3)
    cur.execute(
        "INSERT INTO v13_policies (name, version, value, active) VALUES "
        "('assemble_manifest', 22, %s::jsonb, false)",
        (json.dumps({**asm_v1, "budget_tokens": 64}),))
    conn.commit()
    full_settle(cur, sid_g)
    conn.commit()
    evs_g3b = [e for e in events_of(cur, sid_g, "audit/shadow_obs")
               if e["name"] == "assemble_manifest"]
    check("G3: differing assemble shadow → content_equal=false",
          evs_g3b[-1]["content_equal"] is False
          and evs_g3b[-1]["shadow_version"] == 22, evs_g3b[-1])

    # G4 词表
    policy_flip(cur, "shadow_watch", 4, {"targets": ["context_tiers"]})
    m_g4 = assemble(cur, sid_g)
    append(cur, sid_g, "turn/route", {"action": "refresh"})
    cur.execute("SELECT v13_enqueue_effect(%s,'context_refresh',"
                "jsonb_build_object('goal_hash',%s))",
                (sid_g, m_g4["required_revision"]["goal"]))
    eff_g4 = cur.fetchone()[0]
    cur.execute("SELECT v13_claim('t')")
    cl_g4 = cur.fetchone()[0]
    fails_with(cur, "SELECT v13_refresh_context(%s,%s,%s)",
               (eff_g4, cl_g4["attempt_no"], cl_g4["fence"]),
               "outside v1 vocabulary",
               "G4: watch name outside v1 → V3008 (tier flip 证据面归 DP7)",
               pgcode="V3008")
    conn.rollback()
    policy_unflip(cur, "shadow_watch", 1)
    conn.commit()

    # G5 streak(专用 name/version 99,免回滚)
    sid_g5 = new_session(cur)
    conn.commit()
    for i in range(10):
        cur.execute(
            "INSERT INTO events (session_id, seq, event_id, type, "
            "payload, payload_hash, at) VALUES (%s, %s, %s, "
            "'audit/shadow_obs', %s::jsonb, 'x', now() - make_interval("
            "secs => %s))",
            (sid_g5, i, u(),
             json.dumps({"name": "render_policy", "shadow_version": 99,
                         "content_equal": True}), 20 - i))
    conn.commit()
    cur.execute("SELECT v13_shadow_streak('render_policy', 99)")
    st_g5 = cur.fetchone()[0]
    check("G5: 10 consecutive equal → streak=10, ready=true",
          st_g5["streak"] == 10 and st_g5["observations"] == 10
          and st_g5["ready"] is True, st_g5)
    cur.execute(
        "INSERT INTO events (session_id, seq, event_id, type, payload, "
        "payload_hash, at) VALUES (%s, 99, %s, 'audit/shadow_obs', "
        "%s::jsonb, 'x', now())",
        (sid_g5, u(),
         json.dumps({"name": "render_policy", "shadow_version": 99,
                     "content_equal": False})))
    conn.commit()
    cur.execute("SELECT v13_shadow_streak('render_policy', 99)")
    st_g5b = cur.fetchone()[0]
    check("G5: one false in latest window → ready resets (bool_and window)",
          st_g5b["ready"] is False and st_g5b["streak"] == 9, st_g5b)

    # G6 flip 仪式 + auto-flip 不存在
    cur.execute("SELECT v13_context_fresh(%s)", (sid_g,))
    fresh_g6 = cur.fetchone()[0]
    policy_flip(cur, "render_policy", 23, {
        "renderer": "canonical", "cache_markers": False,
        "provider_policy": "protocol_only", "note": "g6 real flip"})
    cur.execute("SELECT v13_context_fresh(%s)", (sid_g,))
    check("G6: real flip → identity/token chase (stale)",
          fresh_g6 is True and cur.fetchone()[0] is False)
    full_settle(cur, sid_g)
    conn.commit()
    cur.execute("SELECT v13_context_fresh(%s)", (sid_g,))
    check("G6: refresh settles the chase (C4 same chain)",
          cur.fetchone()[0] is True)
    policy_unflip(cur, "render_policy", 1)
    full_settle(cur, sid_g)
    conn.commit()
    for fn in ("v13_shadow_observe(uuid)", "v13_shadow_streak(text,int)"):
        cur.execute("SELECT pg_get_functiondef(%s::regprocedure)", (fn,))
        d = strip_sql_comments(cur.fetchone()[0])
        check(f"G6: {fn} carries no policy UPDATE (auto-flip absent)",
              "update v13_policies" not in d.lower())

    # ============================== H 组 ==============================
    # H1 缺失
    sid_h = new_session(cur)
    append_user(cur, sid_h, "english goal for intent gate")
    conn.commit()
    cur.execute("SELECT v13_intent_gate(%s)", (sid_h,))
    g_h1 = cur.fetchone()[0]
    check("H1: no intent row → superset/missing",
          g_h1 == {"mode": "superset", "basis": "missing",
                   "actions_enabled": False}, g_h1)

    # H2 低置信
    intent_decision(cur, sid_h, 0.5)
    conn.commit()
    cur.execute("SELECT v13_intent_gate(%s)", (sid_h,))
    g_h2 = cur.fetchone()[0]
    check("H2: confidence below pass band → superset/low_confidence",
          g_h2["mode"] == "superset" and g_h2["basis"] == "low_confidence",
          g_h2)

    # H3 CJK(即使高置信)
    sid_h3 = new_session(cur)
    append_user(cur, sid_h3, "中文目标文本")
    conn.commit()
    intent_decision(cur, sid_h3, 0.95)
    conn.commit()
    cur.execute("SELECT v13_intent_gate(%s)", (sid_h3,))
    g_h3 = cur.fetchone()[0]
    check("H3: CJK goal → superset/cjk (high confidence notwithstanding)",
          g_h3["mode"] == "superset" and g_h3["basis"] == "cjk", g_h3)

    # H4 高置信非 CJK
    intent_decision(cur, sid_h, 0.95)
    conn.commit()
    cur.execute("SELECT v13_intent_gate(%s)", (sid_h,))
    g_h4 = cur.fetchone()[0]
    check("H4: confident non-CJK → narrow_eligible (record-only v1)",
          g_h4 == {"mode": "narrow_eligible", "basis": "confident",
                   "actions_enabled": False}, g_h4)

    # H5 needed 集不变性
    cur.execute("SELECT v13_judgment_envelope(%s)->'needed'", (sid_h,))
    needed_h5 = cur.fetchone()[0]
    cur.execute("UPDATE v13_policies SET active=false WHERE "
                "name='intent_gate'")
    cur.execute("SELECT v13_judgment_envelope(%s)->'needed'", (sid_h,))
    needed_h5b = cur.fetchone()[0]
    cur.execute("UPDATE v13_policies SET active=true WHERE "
                "name='intent_gate' AND version=1")
    conn.commit()
    check("H5: envelope needed byte-equal with/without gate row "
          "(envelope chain never calls gate)",
          needed_h5 == needed_h5b)

    # H6 零新调三重
    cur.execute("SELECT count(*) FROM judgment_calls")
    calls_h6 = cur.fetchone()[0]
    cur.execute("SELECT v13_intent_gate(%s)", (sid_h,))
    cur.fetchone()
    cur.execute("SELECT count(*) FROM judgment_calls")
    check("H6: judgment_calls zero increment across gate call",
          cur.fetchone()[0] == calls_h6)
    cur.execute("SELECT pg_get_functiondef('v13_intent_gate(uuid)'"
                "::regprocedure)")
    d_h6 = strip_sql_comments(cur.fetchone()[0])
    check("H6: intent_gate body zero typesafe_ask (source scan)",
          "typesafe_ask" not in d_h6)
    cur.execute("SELECT provolatile FROM pg_proc WHERE proname="
                "'v13_intent_gate'")
    check("H6: intent_gate STABLE (structurally read-only)",
          cur.fetchone()[0] == "s")

    # H7 thresholds 单源(新版本带行仪式)
    intent_decision(cur, sid_h, 0.85)
    conn.commit()
    cur.execute("SELECT v13_intent_gate(%s)->>'mode'", (sid_h,))
    mode_h7a = cur.fetchone()[0]
    cur.execute("INSERT INTO v13_route_policies (policy_name, "
                "policy_version) VALUES ('default', 2)")
    cur.execute("INSERT INTO thresholds (policy_name, policy_version, "
                "signal, band_no, lo, hi, action) VALUES "
                "('default', 2, 'intent', 1, 0.90, 'Infinity', 'pass')")
    cur.execute("UPDATE v13_route_policies SET state='frozen', "
                "frozen_at=now() WHERE policy_name='default' AND "
                "policy_version=2")
    cur.execute("UPDATE sessions SET route_policy_version=2 WHERE "
                "session_id=%s", (sid_h,))
    conn.commit()
    cur.execute("SELECT v13_intent_gate(%s)->>'mode'", (sid_h,))
    mode_h7b = cur.fetchone()[0]
    check("H7: raising intent band lo (0.75→0.90) flips mode "
          "narrow→superset on same fixture (single truth source)",
          mode_h7a == "narrow_eligible" and mode_h7b == "superset",
          (mode_h7a, mode_h7b))
    cur.execute("UPDATE sessions SET route_policy_version=1 WHERE "
                "session_id=%s", (sid_h,))
    conn.commit()

    # ============================== I 组 ==============================
    # I1 token 十一键集恰等(附 A #1 修复断言面)
    cur.execute(
        "SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys("
        "v13_context_required(%s)) k", (sid_c1,))
    keys_i1 = cur.fetchone()[0]
    check("I1: token key set exactly 11 (corpus/recall_ver restored + "
          "ident_ver)",
          keys_i1 == "asm_ver,corpus,dec,econ_ver,gen_ver,goal,ident_ver,"\
                     "jdef_ver,recall_ver,sem,tools_rev", keys_i1)
    cur.execute(
        "SELECT count(*) FROM jsonb_each(v13_context_required(%s)) WHERE "
        "value IS NULL OR value::text = 'null'", (sid_c1,))
    check("I1: all eleven keys non-null", cur.fetchone()[0] == 0)

    # I2 manifest v3 三上游装配链标记
    cur.execute(
        "SELECT inline FROM artifacts WHERE artifact_id=%s",
        (active_artifact(cur, sid_c1),))
    m_i2 = cur.fetchone()[0]
    cur.execute("SELECT pg_get_functiondef('v13_manifest_validate(jsonb)'"
                "::regprocedure)")
    d_i2 = strip_sql_comments(cur.fetchone()[0])
    check("I2: validate v4 vocabulary keeps kind='summary' + economics "
          "block layer + render layer present in real manifest",
          "'summarize'" in d_i2 and m_i2["economics"] is not None
          and m_i2["economics"]["summary"] is not None
          and sorted(m_i2["render"].keys()) == [
              "render_policy_version", "renderer",
              "stable_prefix_est_tokens", "wire_digest"],
          sorted(m_i2["render"].keys()))

    # I3 v3 产物拒 v2 形状 + replay exempt 逐字节
    m_v2_i3 = {**m_i2, "manifest_version": 2}
    fails_with(cur, "SELECT v13_manifest_validate(%s::jsonb)",
               (json.dumps(m_v2_i3),), "anchor/identity shape",
               "I3: mv3 product rejects v2 manifest_version (validate "
               "negative)", pgcode="V3003")
    eff_i3 = llm_succeed(cur, sid_c1, {}, "i3 v2 replay lander")
    conn.commit()
    legacy_v2 = {k: v for k, v in m_i2.items() if k != "render"}
    legacy_v2["manifest_version"] = 2
    cur.execute(
        "SELECT v13_artifact_land(%s, 'context', %s::jsonb)",
        (eff_i3, json.dumps(legacy_v2)))
    art_i3 = cur.fetchone()[0]
    conn.commit()
    cur.execute("SELECT v13_replay(%s)", (art_i3,))
    rep_i3 = cur.fetchone()[0]
    strip_replay = lambda d: {k: v for k, v in d.items()
                               if k != "replay"}
    check("I3: v13_replay replays old-shape artifact byte-exact "
          "(exempt path, no validate)",
          strip_replay(rep_i3) == strip_replay(legacy_v2)
          and rep_i3["replay"]["source_artifact"] == art_i3)

    # I4 前缀库互证(装载切片+上游对象在场;13 gate 复跑在 gate 外由
    #    AGENTS.md 前置条件执行并记录于 README)
    slice_i4 = files_through("periphery")
    check("I4: periphery slice loads exactly 14 files, periphery last",
          len(slice_i4) == 14
          and slice_i4[-1].name == "v13_periphery.sql"
          and slice_i4[12].name == "v13_summary.sql")
    cur.execute(
        "SELECT count(*) FROM pg_proc WHERE proname IN ('v13_history_"
        "action','v13_summary_schedule','v13_recall_candidates',"
        "'v13_filter_ref','v13_ingest_document')")
    check("I4: upstream DP5/DP6/DP7 objects live in periphery library",
          cur.fetchone()[0] == 5)

    # I5 ≤13 号库零 14 号对象(结构断言:源文件扫描)
    periphery_marks = ["CREATE TABLE latches", "ADD COLUMN spawn_kind",
                       "v13_latch_fire", "v13_render_wire",
                       "v13_cache_probe", "v13_intent_gate",
                       "('latches', 1"]
    leaked = []
    for p in files_through("summary"):
        t = strip_sql_comments(p.read_text())
        for m in periphery_marks:
            if m in t:
                leaked.append((p.name, m))
    check("I5: prefix (≤13号) sources carry zero periphery objects",
          leaked == [], leaked)

    # I6 DP5/DP6 装配增量存续(corpus fixture 走真实摄取链路)
    sid_i6 = new_session(cur)
    append_user(cur, sid_i6, "ingest-op")
    conn.commit()
    cur.execute(
        "SELECT v13_enqueue_effect(%s, 'tool', %s::jsonb, "
        "'v13_ingest_corpus')",
        (sid_i6, json.dumps({"plan": "ingest", "nonce": u()})))
    eid_i6 = cur.fetchone()[0]
    cur.execute("SELECT v13_claim('t')")
    cl_i6 = cur.fetchone()[0]
    cur.execute("SELECT v13_complete(%s,%s,%s,'succeeded','{}'::jsonb)",
                (eid_i6, cl_i6["attempt_no"], cl_i6["fence"]))
    conn.commit()
    doc_i6 = ("Kohaku ingest op notes: the ingest queue bridge drains "
              "the duck tools registry each turn. " * 8)
    cur.execute("SELECT v13_ingest_document(%s, 'docs', %s)",
                (eid_i6, doc_i6))
    doc_id_i6 = cur.fetchone()[0]
    conn.commit()
    full_settle(cur, sid_i6)
    conn.commit()
    m_i6 = assemble(cur, sid_i6)
    cur.execute("SELECT v13_recall_candidates(%s)->'candidates'",
                (sid_i6,))
    live_cands_i6 = cur.fetchone()[0]
    strip_did = lambda cs: [{k: v for k, v in c.items()
                             if k != "decision_id"} for c in cs]
    check("I6: manifest v3 candidates == live recall output (goal echo "
          "zero residue, non-empty via real corpus)",
          strip_did(m_i6["query_side"]["candidates"]) == live_cands_i6
          and len(live_cands_i6) > 0,
          len(live_cands_i6))
    cand_i6 = live_cands_i6[0]
    ch_i6 = cand_i6["content_hash"]
    cur.execute(
        "INSERT INTO decisions (session_id, signal, kind, question, "
        "criteria, context, answer, provider, model, request_hash, status,"
        " template_name, template_version)"
        " VALUES (%s, %s, 'choice', 'Include this chunk?', "
        "'{\"include\":\"keep\",\"exclude\":\"drop\"}'::jsonb, "
        "v13_filter_ref(v13_goal_hash(%s), %s), "
        "'{\"action\":\"include\",\"confidence\":0.9}'::jsonb, 'mock', "
        "'jev-mock', %s, 'answered', 'intent', 1)",
        (sid_i6, f"chunk::{ch_i6}", sid_i6, ch_i6,
         hashlib.sha256(ch_i6.encode()).hexdigest()))
    conn.commit()
    full_settle(cur, sid_i6)
    conn.commit()
    m_i6b = assemble(cur, sid_i6)
    dec_i6 = [c for c in m_i6b["query_side"]["candidates"]
              if c["content_hash"] == ch_i6]
    check("I6: decided candidate carries decision_id (non-null)",
          dec_i6 and dec_i6[0]["decision_id"] is not None, dec_i6)
    rows_i6 = [j for j in m_i6b["judgments"]
               if j["decision_id"] == dec_i6[0]["decision_id"]]
    cur.execute(
        "SELECT (v13_chunk_filter_action(%s, v13_goal_hash(%s), "
        "v13_candidates_digest(%s), %s)->>'action')",
        (sid_i6, sid_i6, json.dumps(live_cands_i6), ch_i6))
    live_action_i6 = cur.fetchone()[0]
    check("I6: judgments final_action = live filter action truth "
          "(non-placeholder)",
          rows_i6 and rows_i6[0]["final_action"] == live_action_i6,
          (rows_i6, live_action_i6))

    conn.commit()
    conn.close()
    print(f"ALL PASS ({PASS} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
