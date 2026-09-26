"""Phase A stage 22 gate: D14 catalog exemption + fourth duty.

Run: uv run python v13/catalog/test_catalog.py  (exit 0 = pass)
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.catalog.setup_db import DB, build
from v13.load import run_psql

BASE = "agent_v13_catalog_base"
SQL = (ROOT / "v13_catalog.sql").read_text()
PREDICATES = ("v13_named_sql_writer(text)", "v13_spawn_writer_ok(text)")


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    extra = f": {detail}" if detail and (not condition or len(str(detail)) < 240) else ""
    print(f"[{mark}] {label}{extra}")
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u() -> str:
    return str(uuid.uuid4())


def connect(server, db):
    conn = psycopg2.connect(server.get_uri(db))
    conn.autocommit = False
    return conn


def q1(cur, sql, params=None):
    cur.execute(sql, params)
    return cur.fetchone()[0]


def raises(cur, sql, params=None, role=None):
    cur.execute("SAVEPOINT sp")
    if role:
        cur.execute(f"SET LOCAL ROLE {role}")
    try:
        cur.execute(sql, params)
    except psycopg2.Error as exc:
        msg = exc.diag.message_primary or str(exc)
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        return msg
    cur.execute("ROLLBACK TO SAVEPOINT sp")
    return None


def open_session(cur):
    return str(q1(cur, "SELECT v13_open_session(%s::jsonb)", (json.dumps({}),)))


def gucs(cur):
    cur.execute("SELECT set_config('typesafe.provider', 'probe', false)")
    cur.execute("SELECT set_config('typesafe.model', 'probe', false)")
    cur.execute("SELECT set_config('typesafe.api_key', 'probe', false)")


def catalog_as(cur, role):
    cur.execute("SAVEPOINT cat")
    cur.execute(f"SET LOCAL ROLE {role}")
    try:
        cur.execute("SELECT v13_tools_catalog_frozen()")
        cat = cur.fetchone()[0]
    except psycopg2.Error as exc:
        cur.execute("ROLLBACK TO SAVEPOINT cat")
        raise
    cur.execute("RESET ROLE")
    cur.execute("RELEASE SAVEPOINT cat")
    return cat


def spawn_row(cat):
    return next(row for row in cat if row["name"] == "spawn_subsession")


def body(cur):
    return q1(cur, "SELECT pg_get_functiondef('v13_tools_catalog_frozen()'::regprocedure)")


def lock_s(cur):
    cur.execute("SAVEPOINT sh")
    cur.execute("CREATE SCHEMA zshadow")
    cur.execute(
        """
        CREATE FUNCTION zshadow.v13_spawn_subsession(p_sid uuid, p_spec jsonb)
        RETURNS jsonb LANGUAGE plpgsql VOLATILE AS $f$
        BEGIN RETURN '{}'::jsonb; END $f$
        """)
    cur.execute("GRANT USAGE ON SCHEMA zshadow TO v13_route")
    cur.execute("SET LOCAL ROLE v13_route")
    msg = None
    try:
        cur.execute("SELECT v13_tools_catalog_frozen()")
    except psycopg2.Error as exc:
        msg = exc.diag.message_primary or ""
    cur.execute("ROLLBACK TO SAVEPOINT sh")
    return msg


def base_probes(server):
    conn = connect(server, BASE)
    cur = conn.cursor()
    gucs(cur)
    msg = raises(cur, "SELECT v13_tools_catalog_frozen()", role="v13_route")
    check("P1 base route catalog RED", msg is not None and "is VOLATILE" in msg, msg)
    sid = open_session(cur)
    cur.execute("SET ROLE v13_resolve")
    p2 = raises(cur, "SELECT v13_parse(%s)", (sid,))
    cur.execute("RESET ROLE")
    check("P2 base parse reaches catalog RED",
          p2 is not None and "is VOLATILE" in p2 and "spawn_subsession" in p2, p2)
    needed = q1(cur, "SELECT pg_get_functiondef('v13_needed_judgments(uuid)'::regprocedure)")
    check("P3 needed contains is_spawn_tool", "v13_is_spawn_tool" in needed)
    cur.execute(
        "GRANT EXECUTE ON FUNCTION v13_spawn_writer_ok(text), v13_named_sql_writer(text) "
        "TO v13_route, v13_resolve")
    cur.execute("SET ROLE v13_route")
    route_ok = q1(cur, "SELECT v13_spawn_writer_ok('v13_spawn_subsession')")
    cur.execute("RESET ROLE")
    cur.execute("SET ROLE v13_resolve")
    resolve_ok = q1(cur, "SELECT v13_spawn_writer_ok('v13_spawn_subsession')")
    cur.execute("RESET ROLE")
    check("P4 writer_ok same for route and resolve", route_ok is True and resolve_ok is True,
          (route_ok, resolve_ok))
    vols = {}
    cur.execute(
        """
        SELECT p.proname, p.provolatile, p.prosecdef, p.proconfig IS NULL,
               n.nspname, p.oid::text,
               pg_get_function_identity_arguments(p.oid),
               pg_get_function_result(p.oid)
          FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE p.proname IN ('v13_named_sql_writer','v13_spawn_writer_ok',
                             'v13_tools_catalog_frozen')
         ORDER BY 1
        """)
    rows = cur.fetchall()
    for name, vol, secdef, nullcfg, nsp, oid, args, ret in rows:
        vols[name] = (vol, secdef, nullcfg, nsp, oid, args, ret)
    check("P5 named IMMUTABLE writer_ok STABLE",
          vols["v13_named_sql_writer"][0] == "i" and vols["v13_spawn_writer_ok"][0] == "s")
    enabled = q1(cur, "SELECT enabled FROM tools WHERE name='spawn_subsession'")
    check("P6 spawn_subsession enabled", enabled is True)
    check("P7 predicate signatures",
          vols["v13_named_sql_writer"][5] == "p_handler text"
          and str(vols["v13_named_sql_writer"][6]).startswith("jsonb")
          and vols["v13_spawn_writer_ok"][5] == "p_handler text"
          and str(vols["v13_spawn_writer_ok"][6]).startswith("boolean"),
          (vols["v13_named_sql_writer"][5:], vols["v13_spawn_writer_ok"][5:]))
    check("P8a form H proconfig NULL invoker",
          all(vols[n][2] is True and vols[n][1] is False for n in vols))
    for name in ("v13_named_sql_writer", "v13_spawn_writer_ok", "v13_tools_catalog_frozen"):
        src = q1(cur, "SELECT prosrc FROM pg_proc WHERE proname=%s", (name,))
        check(f"P8a {name} no set_config", "set_config" not in src.lower())
    check("P8a' predicates in public",
          vols["v13_named_sql_writer"][3] == "public"
          and vols["v13_spawn_writer_ok"][3] == "public")
    oid = q1(cur, "SELECT 'public.v13_spawn_subsession(uuid,jsonb)'::regprocedure::oid")
    arglist = q1(cur, "SELECT substring(%s::regprocedure::text FROM '\\(.*\\)$')", (oid,))
    check("P8b canonical arglist", arglist == "(uuid,jsonb)", arglist)
    back = q1(cur, "SELECT to_regprocedure(%s)::oid", ("v13_spawn_subsession" + arglist,))
    check("P8b roundtrip", back == oid, (back, oid))
    ident = raises(cur, "SELECT to_regprocedure('v13_spawn_subsession(p_sid uuid, p_spec jsonb)')")
    check("P8b identity-args rejected", ident is not None, ident)
    matched = q1(
        cur,
        """
        SELECT p.oid FROM pg_proc p
          JOIN pg_roles r ON r.oid = p.proowner
         WHERE p.proname = 'v13_spawn_subsession'
           AND oidvectortypes(p.proargtypes) = 'uuid, jsonb'
           AND p.provolatile = 'v' AND p.prosecdef
           AND r.rolname = 'v13_spawn_owner'
        """)
    check("P8c writer_ok deep-check OID is v_oid", matched == oid)
    create_pub = q1(cur, "SELECT has_schema_privilege('v13_route', 'public', 'CREATE')")
    print(f"[note] P8d v13_route CREATE on public = {create_pub}")
    s = lock_s(cur)
    check("base S locked", s is not None and "ambiguous across schemas (2)" in s, s)
    conn.rollback()
    conn.close()
    return s, vols["v13_named_sql_writer"][4], vols["v13_spawn_writer_ok"][4]


class IO:
    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n += 1
        return self.n


class Worker:
    def __init__(self, cur, io):
        self.cur = cur
        self.io = io
        self.pred_reads = 0
        self.completes = []
        self.fail_closed = False

    def renew(self, eid, fence):
        return q1(self.cur, "SELECT v13_renew_lease(%s, %s, 60000)", (eid, fence))

    def pending(self, sid):
        self.pred_reads += 1
        return q1(self.cur, "SELECT v13_cancel_pending(%s)", (sid,))

    def tier(self, name):
        self.pred_reads += 1
        return q1(self.cur, "SELECT v13_interruptible(%s)", (name,))

    def fence_now(self, eid):
        return q1(self.cur, "SELECT fence FROM effects WHERE effect_id=%s", (eid,))

    def complete(self, eid, attempt, fence, status, result):
        self.completes.append(status)
        self.cur.execute(
            "SELECT v13_complete(%s, %s, %s, %s, %s::jsonb)",
            (eid, attempt, fence, status, None if result is None else json.dumps(result)))
        return self.cur.fetchone()[0]

    def run(self, claim, sid, tool_name, rounds=1, between=None, fence_override=None,
            before_preds=None):
        kind = claim["kind"]
        eid, attempt = claim["effect_id"], claim["attempt_no"]
        for i in range(rounds):
            self.io()
            fence = claim["fence"]
            if not self.renew(eid, fence):
                return "renew_failed"
            fence = self.fence_now(eid)
            if fence_override is not None:
                fence = fence_override
            if before_preds is not None:
                before_preds()
            self.cur.execute("SAVEPOINT pred")
            try:
                pending = self.pending(sid)
                tier = self.tier(tool_name)
            except psycopg2.Error:
                self.cur.execute("ROLLBACK TO SAVEPOINT pred")
                self.fail_closed = True
                return "fail_closed"
            self.cur.execute("RELEASE SAVEPOINT pred")
            if pending and tier == "best_effort":
                return self._finish(eid, attempt, fence, "cancelled", None)
            if pending and tier == "required" and kind == "llm":
                return self._finish(eid, attempt, fence, "cancelled", None)
            if pending and tier == "required" and kind == "tool":
                return self._finish(eid, attempt, fence, "unknown", None)
            if i + 1 < rounds and between is not None:
                between()
                claim = dict(claim)
                claim["fence"] = self.fence_now(eid)
        result = {"text": "ok"} if kind == "llm" else {"ok": True}
        return self._finish(eid, attempt, fence, "succeeded", result)

    def _finish(self, eid, attempt, fence, status, result):
        n = self.io.n
        word = self.complete(eid, attempt, fence, status, result)
        check("no provider IO after fourth-duty hit", self.io.n == n)
        if word in ("replay", "stale"):
            return word
        return word


def claim_one(cur, sid, kind, tool, request=None):
    eid = str(q1(
        cur, "SELECT v13_enqueue_effect(%s, %s, %s::jsonb, %s)",
        (sid, kind, json.dumps(request or {}), tool)))
    claim = q1(cur, "SELECT v13_claim('w', 60000)")
    check("claim got enqueued effect", claim["effect_id"] == eid, claim)
    claim["effect_id"] = str(claim["effect_id"])
    return claim


def cancel(cur, sid):
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'cancel/requested', %s::jsonb)",
        (sid, u(), json.dumps({"schema_version": 1, "scope": "session"})))


def effect_status(cur, eid):
    return q1(cur, "SELECT status FROM effects WHERE effect_id=%s", (eid,))


def session_status(cur, sid):
    return q1(cur, "SELECT status FROM sessions WHERE session_id=%s", (sid,))


def fourth_duty(cur):
    cur.execute("SAVEPOINT duty")
    sid = open_session(cur)
    claim = claim_one(cur, sid, "tool", "fanout_best_effort")
    io = IO()
    w = Worker(cur, io)
    word = w.run(claim, sid, "fanout_best_effort", fence_override=claim["fence"] - 1)
    check("renew uses post-renew fence; old fence stale", word == "stale", word)
    check("stale stops with one complete", w.completes == ["succeeded"] or w.completes == ["cancelled"] or len(w.completes) == 1,
          w.completes)
    check("stale does not settle", effect_status(cur, claim["effect_id"]) == "claimed")
    cur.execute("ROLLBACK TO SAVEPOINT duty")

    sid = open_session(cur)
    claim = claim_one(cur, sid, "llm", None)
    w = Worker(cur, IO())
    w.renew = lambda eid, fence: False
    word = w.run(claim, sid, None)
    check("renew failure skips predicates and complete",
          word == "renew_failed" and w.pred_reads == 0 and w.completes == [])

    sid = open_session(cur)
    claim = claim_one(cur, sid, "llm", None)
    w = Worker(cur, IO())
    word = w.run(claim, sid, None)
    check("pending false settles succeeded", word == "accepted" and effect_status(cur, claim["effect_id"]) == "succeeded")

    sid = open_session(cur)
    claim = claim_one(cur, sid, "tool", "fanout_best_effort")
    cancel(cur, sid)
    before = IO()
    w = Worker(cur, before)
    word = w.run(claim, sid, "fanout_best_effort")
    check("cancel before renew settles cancelled",
          word == "accepted" and effect_status(cur, claim["effect_id"]) == "cancelled", word)
    check("no IO after cancel hit", before.n == 1, before.n)

    sid = open_session(cur)
    claim = claim_one(cur, sid, "llm", None)
    w = Worker(cur, IO())
    word = w.run(claim, sid, None)
    cancel(cur, sid)
    check("cancel after read is not retroactive", effect_status(cur, claim["effect_id"]) == "succeeded")

    sid = open_session(cur)
    claim = claim_one(cur, sid, "tool", "fanout_best_effort")
    cancel(cur, sid)
    w = Worker(cur, IO())
    w.run(claim, sid, "fanout_best_effort")
    check("best_effort tool is cancelled not unknown", effect_status(cur, claim["effect_id"]) == "cancelled")

    sid = open_session(cur)
    claim = claim_one(cur, sid, "llm", "fanout_required")
    cancel(cur, sid)
    w = Worker(cur, IO())
    w.run(claim, sid, "fanout_required")
    check("required llm is cancelled", effect_status(cur, claim["effect_id"]) == "cancelled")

    sid = open_session(cur)
    claim = claim_one(cur, sid, "tool", "fanout_required")
    cancel(cur, sid)
    w = Worker(cur, IO())
    word = w.run(claim, sid, "fanout_required")
    check("required tool complete unknown",
          word == "accepted" and effect_status(cur, claim["effect_id"]) == "unknown", word)
    check("required tool hits unknown wall", session_status(cur, sid) == "blocked_unknown",
          session_status(cur, sid))

    for kind in ("judge", "human", "context_refresh"):
        sid = open_session(cur)
        claim = claim_one(cur, sid, kind, "fanout_required")
        cancel(cur, sid)
        w = Worker(cur, IO())
        w.run(claim, sid, "fanout_required")
        check(f"required {kind} settles succeeded", effect_status(cur, claim["effect_id"]) == "succeeded")

    sid = open_session(cur)
    claim = claim_one(cur, sid, "llm", None)
    cancel(cur, sid)
    w = Worker(cur, IO())
    w.run(claim, sid, None)
    check("unsupported pending still succeeded", effect_status(cur, claim["effect_id"]) == "succeeded")

    sid = open_session(cur)
    claim = claim_one(cur, sid, "llm", None)
    cancel(cur, sid)
    msg = raises(
        cur, "SELECT v13_complete(%s, %s, %s, 'cancelled', NULL)",
        (claim["effect_id"], claim["attempt_no"], claim["fence"]))
    check("empty tool llm complete cancelled raises",
          msg is not None and "interruptible unsupported" in msg, msg)

    sid = open_session(cur)
    claim = claim_one(cur, sid, "tool", "fanout_best_effort")
    cancel(cur, sid)
    w = Worker(cur, IO())
    w.run(claim, sid, "fanout_best_effort")
    replay = w.complete(claim["effect_id"], claim["attempt_no"], claim["fence"], "cancelled", None)
    check("replay exits with no further settle", replay == "replay" and effect_status(cur, claim["effect_id"]) == "cancelled")

    sid = open_session(cur)
    claim = claim_one(cur, sid, "llm", None)
    w = Worker(cur, IO())

    def poison():
        cur.execute("SET LOCAL search_path = pg_catalog")

    word = w.run(claim, sid, None, before_preds=poison)
    cur.execute("SET LOCAL search_path = public")
    check("predicate failure is fail-closed", word == "fail_closed" and w.completes == [], word)
    check("fail-closed leaves claimed", effect_status(cur, claim["effect_id"]) == "claimed")

    seen = {"n": 0}

    def between():
        seen["n"] += 1
        cancel(cur, sid2)

    sid2 = open_session(cur)
    claim = claim_one(cur, sid2, "tool", "fanout_best_effort")
    w = Worker(cur, IO())
    w.run(claim, sid2, "fanout_best_effort", rounds=2, between=between)
    check("each renew rechecks", seen["n"] == 1 and effect_status(cur, claim["effect_id"]) == "cancelled")
    cur.execute("RELEASE SAVEPOINT duty")


def plant_route(cur, sid):
    cur.execute("SELECT v13_judgment_envelope(%s)", (sid,))
    env = cur.fetchone()[0]
    needed = {g["signal"]: g for g in env["needed"]}
    blob = json.dumps(env)
    for signal in ("intent", "gate_action", "tool"):
        g = needed[signal]
        if g["kind"] == "noul":
            answer = {"type": "noul", "noul": 0.9}
        elif g["kind"] == "score":
            answer = {"type": "score", "score": 0.5, "confidence": 0.9}
        elif signal == "tool":
            answer = {"type": "choice", "choice": "spawn_subsession", "confidence": 0.9,
                      "probabilities": {"spawn_subsession": 0.9}}
        else:
            answer = {"type": "choice", "choice": "sql_answer", "confidence": 0.9,
                      "probabilities": {"sql_answer": 0.9}}
        criteria = g.get("criteria")
        rh = q1(
            cur, "SELECT v13_judgment_hash(%s::jsonb, %s, %s, %s, %s::jsonb)",
            (blob, signal, g["kind"], g["question"],
             None if criteria is None else json.dumps(criteria)))
        cur.execute(
            "INSERT INTO decisions (session_id, signal, kind, question, criteria, context, "
            "answer, request_hash, status, answered_at) VALUES "
            "(%s,%s,%s,%s,%s::jsonb,'{}'::jsonb,%s::jsonb,%s,'answered', now())",
            (sid, signal, g["kind"], g["question"],
             None if criteria is None else json.dumps(criteria),
             json.dumps(answer), rh))
    cur.execute("SELECT v13_probe(%s)", (sid,))
    probe = cur.fetchone()[0]
    probe["sid"] = sid
    return {"snap": probe, "envelope": env, "remaining": 0, "failed": False, "abandon": False}


def children(cur, sid):
    return q1(cur, "SELECT count(*) FROM sessions WHERE parent_session_id=%s", (sid,))


def arms(cur, server_s, named_oid, writer_oid):
    g = catalog_as(cur, "v13_route")
    grow = spawn_row(g)
    check("G catalog green and spawn exempt",
          grow["enabled"] is True and grow["handler"] == "public.v13_spawn_subsession")
    digest = grow.get("handler_digest")
    check("G digest present", bool(digest))

    cur.execute("SAVEPOINT fx1")
    cur.execute("CREATE SCHEMA zshadow")
    cur.execute("GRANT USAGE ON SCHEMA zshadow TO v13_route")
    cur.execute(
        """
        CREATE FUNCTION zshadow.v13_spawn_subsession(p_sid uuid, p_spec jsonb)
        RETURNS jsonb LANGUAGE plpgsql VOLATILE AS $f$
        BEGIN RETURN '{}'::jsonb; END $f$
        """)
    msg = raises(cur, "SELECT v13_tools_catalog_frozen()", role="v13_route")
    check("fixture 1 RAISE contains S", msg is not None and server_s in msg, msg)
    cur.execute("DROP FUNCTION zshadow.v13_spawn_subsession(uuid, jsonb)")
    restored = catalog_as(cur, "v13_route")
    check("fixture 1 delete restores G", spawn_row(restored) == grow)
    cur.execute("ROLLBACK TO SAVEPOINT fx1")

    cur.execute("SAVEPOINT fx2")
    cur.execute("CREATE SCHEMA zshadow")
    cur.execute("GRANT USAGE ON SCHEMA zshadow TO v13_route")
    cur.execute(
        """
        CREATE FUNCTION zshadow.v13_spawn_subsession(p_sid uuid, p_spec jsonb)
        RETURNS jsonb LANGUAGE plpgsql VOLATILE AS $f$
        BEGIN RETURN '{}'::jsonb; END $f$
        """)
    cur.execute("SET LOCAL search_path = zshadow, public")
    shadow = q1(cur, "SELECT to_regprocedure('v13_spawn_subsession(uuid,jsonb)')::oid")
    real = q1(cur, "SELECT 'public.v13_spawn_subsession(uuid,jsonb)'::regprocedure::oid")
    check("fixture 2 prerequisite shadow OID",
          shadow is not None and shadow != real, (shadow, real))
    msg = raises(cur, "SELECT v13_tools_catalog_frozen()", role="v13_route")
    check("fixture 2 same S; B'/writer_ok unreachable", msg is not None and server_s in msg, msg)
    print("[note] fixture 2 rejection layer = parse ambiguity, not B' or writer_ok")
    cur.execute("ROLLBACK TO SAVEPOINT fx2")

    cur.execute("SAVEPOINT fx3d")
    cur.execute("CREATE SCHEMA zshadow")
    cur.execute("GRANT USAGE ON SCHEMA zshadow TO v13_route")
    cur.execute(
        """
        CREATE FUNCTION zshadow.v13_spawn_writer_ok(p_handler text) RETURNS boolean
        LANGUAGE sql AS $f$ SELECT false $f$
        """)
    cur.execute(
        """
        CREATE FUNCTION zshadow.v13_named_sql_writer(p_handler text) RETURNS jsonb
        LANGUAGE sql AS $f$ SELECT NULL::jsonb $f$
        """)
    cur.execute("SET LOCAL search_path = zshadow, public")
    cur.execute("SET LOCAL ROLE v13_route")
    sw = q1(cur, "SELECT to_regprocedure('v13_spawn_writer_ok(text)')::oid")
    sn = q1(cur, "SELECT to_regprocedure('v13_named_sql_writer(text)')::oid")
    tool = q1(cur, "SELECT to_regprocedure('v13_spawn_subsession(uuid,jsonb)')::oid")
    check("arm D prereq bare tool is real OID", tool == real, (tool, real))
    check("arm D prereq bare predicates are shadows",
          sw is not None and sn is not None and sw != writer_oid and sn != named_oid,
          (sw, sn, writer_oid, named_oid))
    check("arm D prereq shadow values",
          q1(cur, "SELECT v13_spawn_writer_ok('v13_spawn_subsession')") is False
          and q1(cur, "SELECT v13_named_sql_writer('v13_spawn_subsession')") is None)
    check("arm D prereq qualified named non-null",
          q1(cur, "SELECT public.v13_named_sql_writer('v13_spawn_subsession')") is not None)
    qualified_ok = q1(cur, "SELECT public.v13_spawn_writer_ok('v13_spawn_subsession')")
    check("arm D prereq qualified writer_ok false", qualified_ok is False, qualified_ok)
    print("[note] arm D qualified writer_ok false: live body calls bare named, shadow NULL")
    cur.execute("RESET ROLE")
    msg = raises(cur, "SELECT v13_tools_catalog_frozen()", role="v13_route")
    check("arm D catalog RAISE names spawn_subsession",
          msg is not None and "is VOLATILE" in msg and "spawn_subsession" in msg
          and server_s not in msg, msg)
    cur.execute("ROLLBACK TO SAVEPOINT fx3d")
    cur.execute("SET search_path = public")
    restored = catalog_as(cur, "v13_route")
    check("arm D cleanup restores G", spawn_row(restored) == grow)

    c_named = q1(cur, "SELECT public.v13_named_sql_writer('v13_spawn_subsession')")
    check("arm E constant C captured", c_named is not None, c_named)
    cur.execute("SAVEPOINT fx3e")
    cur.execute("CREATE SCHEMA zshadow")
    cur.execute("GRANT USAGE ON SCHEMA zshadow TO v13_route")
    cur.execute(
        """
        CREATE FUNCTION zshadow.v13_spawn_writer_ok(p_handler text) RETURNS boolean
        LANGUAGE sql AS $f$ SELECT true $f$
        """)
    cur.execute(
        """
        CREATE FUNCTION zshadow.v13_named_sql_writer(p_handler text) RETURNS jsonb
        LANGUAGE sql AS $f$ SELECT %s::jsonb $f$
        """,
        (json.dumps(c_named),))
    cur.execute(
        """
        CREATE FUNCTION zshadow.v13_zz_outsider(p_sid uuid, p_spec jsonb)
        RETURNS jsonb LANGUAGE plpgsql VOLATILE AS $f$
        BEGIN RETURN '{}'::jsonb; END $f$
        """)
    cur.execute("GRANT EXECUTE ON FUNCTION zshadow.v13_zz_outsider(uuid, jsonb) TO v13_route")
    cur.execute("ALTER TABLE tools DISABLE TRIGGER USER")
    cur.execute(
        "INSERT INTO tools (name, description, kind, handler, param_spec, enabled) "
        "VALUES ('zz_outsider', 'outsider', 'sql', 'v13_zz_outsider', '{}', true)")
    cur.execute("ALTER TABLE tools ENABLE TRIGGER USER")
    cur.execute("SET LOCAL search_path = zshadow, public")
    cur.execute("SET LOCAL ROLE v13_route")
    sw = q1(cur, "SELECT to_regprocedure('v13_spawn_writer_ok(text)')::oid")
    sn = q1(cur, "SELECT to_regprocedure('v13_named_sql_writer(text)')::oid")
    out_oid = q1(cur, "SELECT to_regprocedure('v13_zz_outsider(uuid,jsonb)')::oid")
    tool = q1(cur, "SELECT to_regprocedure('v13_spawn_subsession(uuid,jsonb)')::oid")
    nspawn = q1(
        cur,
        """
        SELECT count(*) FROM pg_proc
         WHERE proname = 'v13_spawn_subsession'
           AND oidvectortypes(proargtypes) = 'uuid, jsonb'
        """)
    check("arm E prereq one tool function and shadow predicates",
          nspawn == 1 and tool == real and sw != writer_oid and sn != named_oid and out_oid is not None)
    shadow_src = q1(cur, "SELECT prosrc FROM pg_proc WHERE oid = %s", (sn,))
    check("arm E shadow named is a constant", "v13_named_sql_writer" not in shadow_src)
    qualified_ok = q1(cur, "SELECT public.v13_spawn_writer_ok('v13_spawn_subsession')")
    check("arm E prereq qualified writer_ok true", qualified_ok is True, qualified_ok)
    check("arm E prereq qualified named",
          q1(cur, "SELECT public.v13_named_sql_writer('v13_spawn_subsession')") is not None
          and q1(cur, "SELECT public.v13_named_sql_writer('v13_zz_outsider')") is None)
    check("arm E prereq bare shadow allows outsider",
          q1(cur, "SELECT v13_spawn_writer_ok('v13_zz_outsider')") is True
          and q1(cur, "SELECT v13_named_sql_writer('v13_zz_outsider')") is not None)
    outsider_ok = q1(cur, "SELECT public.v13_spawn_writer_ok('v13_zz_outsider')")
    print(f"[note] arm E qualified writer_ok(outsider) = {outsider_ok}")
    cur.execute("RESET ROLE")
    msg = raises(cur, "SELECT v13_tools_catalog_frozen()", role="v13_route")
    check("arm E RAISE names outsider not spawn",
          msg is not None and "is VOLATILE" in msg and "zz_outsider" in msg
          and "v13_zz_outsider" in msg and "spawn_subsession" not in msg
          and server_s not in msg, msg)
    cur.execute("ROLLBACK TO SAVEPOINT fx3e")

    cur.execute("SAVEPOINT fx4")
    cur.execute(
        """
        CREATE FUNCTION public."zshape.v13_shape_only"(p_sid uuid, p_spec jsonb)
        RETURNS jsonb LANGUAGE plpgsql VOLATILE AS $f$
        BEGIN RETURN '{}'::jsonb; END $f$
        """)
    cur.execute("ALTER TABLE tools DISABLE TRIGGER USER")
    cur.execute(
        "INSERT INTO tools (name, description, kind, handler, param_spec, enabled) "
        "VALUES ('shape_only', 'shape', 'sql', 'zshape.v13_shape_only', '{}', true)")
    cur.execute("ALTER TABLE tools ENABLE TRIGGER USER")
    n = q1(
        cur,
        """
        SELECT count(*) FROM pg_proc
         WHERE proname = 'zshape.v13_shape_only'
           AND oidvectortypes(proargtypes) = 'uuid, jsonb'
        """)
    check("fixture 4 unique proname not an enabled bare name", n == 1)
    msg = raises(cur, "SELECT v13_tools_catalog_frozen()", role="v13_route")
    check("fixture 4 qualified handler is VOLATILE at shape check",
          msg is not None and "is VOLATILE" in msg and "shape_only" in msg, msg)
    cur.execute("ROLLBACK TO SAVEPOINT fx4")

    cur.execute("SET search_path = public")
    bare = q1(cur, "SELECT to_regprocedure('v13_spawn_subsession(uuid,jsonb)')::oid")
    check("B' direct on G path", bare == real)
    return grow


def source_asserts(cur, named_oid, writer_oid):
    live = body(cur)
    import re
    qn = q1(cur, "SELECT to_regprocedure('public.v13_named_sql_writer(text)')::oid")
    qw = q1(cur, "SELECT to_regprocedure('public.v13_spawn_writer_ok(text)')::oid")
    check("P8a' qualified signatures are real OIDs", qn == named_oid and qw == writer_oid,
          (qn, named_oid, qw, writer_oid))
    check("P8a' each predicate called once qualified",
          live.count("public.v13_named_sql_writer(v_handler)") == 1
          and live.count("public.v13_spawn_writer_ok(v_handler)") == 1)
    check("P8a' no unqualified predicate call",
          re.search(r"(?<![\w.])v13_named_sql_writer\s*\(", live) is None
          and re.search(r"(?<![\w.])v13_spawn_writer_ok\s*\(", live) is None)
    check("resolution ambiguity text kept", "ambiguous across schemas" in live)
    check("no exception handler", "EXCEPTION WHEN" not in live.upper() and "WHEN OTHERS" not in live.upper())
    check("no SET search_path on catalog",
          q1(cur, "SELECT proconfig IS NULL FROM pg_proc WHERE proname='v13_tools_catalog_frozen'"))
    for pred in ("public.v13_named_sql_writer(v_handler)", "public.v13_spawn_writer_ok(v_handler)"):
        check(f"qualified call once: {pred}", live.count(pred) == 1)
    check("v_qual only in assertion A",
          "to_regprocedure(v_qual)" in live and "v13_named_sql_writer(v_qual)" not in live
          and "v13_spawn_writer_ok(v_qual)" not in live)
    shape_at = live.find("strpos(v_handler, '.')")
    pred_at = live.find("public.v13_named_sql_writer(v_handler)")
    check("exemption after shape check", 0 <= shape_at < pred_at)
    import re
    check("to_regprocedure null-safe",
          re.search(r"to_regprocedure\([^)]*\)\s*(=|<>)", live) is None)
    check("no split_part or tool literal in catalog sql",
          "split_part" not in SQL and "spawn_subsession" not in SQL and "v13_spawn_subsession" not in SQL)
    check("no deep-check copy", "dblink" not in SQL and "write_targets" not in SQL)
    for banned in ("LISTEN", "NOTIFY", "pg_terminate_backend", "v13_worker_fourth_duty",
                   "CREATE TABLE", "CREATE TEMP"):
        check(f"catalog sql has no {banned}", banned not in SQL)


def post_gates(cur, s, named_oid, writer_oid):
    gucs(cur)
    cat = catalog_as(cur, "v13_route")
    check("post route catalog green", any(r["name"] == "spawn_subsession" for r in cat))
    sid = open_session(cur)
    cur.execute("SELECT signal, kind, criteria FROM v13_needed_judgments(%s)", (sid,))
    answers = {}
    for signal, kind, criteria in cur.fetchall():
        if kind == "choice":
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
    cur.execute("SELECT set_config('typesafe.mock_response', %s, false)", (mock,))
    cur.execute("SET ROLE v13_resolve")
    cur.execute("SELECT v13_parse(%s)", (sid,))
    parsed = cur.fetchone()[0]
    cur.execute("RESET ROLE")
    check("post resolve parse green", isinstance(parsed, dict) and "envelope" in parsed)
    cur.execute("SAVEPOINT out")
    cur.execute(
        """
        CREATE FUNCTION public.v13_zz_closed(p_sid uuid, p_spec jsonb)
        RETURNS jsonb LANGUAGE plpgsql VOLATILE AS $f$
        BEGIN RETURN '{}'::jsonb; END $f$
        """)
    cur.execute("ALTER TABLE tools DISABLE TRIGGER USER")
    cur.execute(
        "INSERT INTO tools (name, description, kind, handler, param_spec, enabled) "
        "VALUES ('zz_closed', 'closed', 'sql', 'v13_zz_closed', '{}', true)")
    msg = raises(cur, "SELECT v13_tools_catalog_frozen()", role="v13_route")
    check("outsider VOLATILE still RED", msg is not None and "is VOLATILE" in msg, msg)
    cur.execute("ROLLBACK TO SAVEPOINT out")
    needed = q1(cur, "SELECT coalesce(string_agg(signal, ','), '') FROM v13_needed_judgments(%s)", (sid,))
    check("needed tool set excludes spawn_subsession", "spawn_subsession" not in needed, needed)
    for role in ("v13_route", "v13_resolve", "v13_recall"):
        for pred in PREDICATES:
            check(f"privilege {role} {pred}",
                  q1(cur, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, pred)))
    for pred in PREDICATES:
        check(f"worker denied {pred}",
              q1(cur, "SELECT NOT has_function_privilege('v13_worker', %s, 'EXECUTE')", (pred,)))
        public_exec = q1(
            cur,
            """
            SELECT EXISTS (
              SELECT 1 FROM aclexplode(proacl) a
               WHERE a.grantee = 0 AND a.privilege_type = 'EXECUTE')
              FROM pg_proc WHERE oid = %s::regprocedure
            """,
            (pred,))
        check(f"public revoked {pred}", public_exec is False, public_exec)
    source_asserts(cur, named_oid, writer_oid)
    arms(cur, s, named_oid, writer_oid)
    fourth_duty(cur)


def route_arms(server):
    conn = connect(server, DB)
    cur = conn.cursor()
    gucs(cur)
    sid = open_session(cur)
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": "hello"})))
    src = q1(cur, "SELECT v13_enqueue_effect(%s, 'tool', '{}'::jsonb, 'fanout_best_effort')", (sid,))
    cur.execute("UPDATE effects SET status='succeeded' WHERE effect_id=%s", (src,))
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'tool/call', %s::jsonb, %s)",
        (sid, u(), json.dumps({
            "schema_version": 1, "id": "call_1", "name": "spawn_subsession",
            "args": {"task": "one"},
        }), src))
    before = children(cur, sid)
    cur.execute(
        "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
        "WHERE session_id=%s", (sid,))
    cur.execute("SELECT v13_probe(%s)", (sid,))
    probe = cur.fetchone()[0]
    probe["sid"] = sid
    snap = {"snap": probe, "envelope": {"sid": sid}, "remaining": 0, "failed": False, "abandon": False}
    word = q1(cur, "SELECT v13_advance(%s, %s::jsonb)", (sid, json.dumps(snap)))
    check("fanout arm produces a child", word == "progressed" and children(cur, sid) == before + 1,
          (word, children(cur, sid), before))
    child = str(q1(cur, "SELECT session_id FROM sessions WHERE parent_session_id=%s", (sid,)))
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (child, u(), json.dumps({"text": "child"})))
    planted = plant_route(cur, child)
    env = json.dumps(planted["envelope"])
    route = q1(cur, "SELECT v13_route(%s, %s::jsonb)", (child, env))
    check("route still names sql spawn",
          route.get("action") == "sql" and route.get("tool") == "spawn_subsession", route)
    rewritten = q1(cur, "SELECT v13_triage_after_route(%s, %s::jsonb)", (child, json.dumps(route)))
    check("triage rewrites direct spawn before the sql arm",
          rewritten.get("action") == "human", rewritten)
    advance_def = q1(cur, "SELECT pg_get_functiondef('v13_advance(uuid,jsonb)'::regprocedure)")
    check("sql arm still raises batch-dispatched",
          advance_def.count("RAISE EXCEPTION 'v13: spawn batch-dispatched'") == 2)
    cur.execute(
        "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
        "WHERE session_id=%s", (child,))
    cur.execute("SELECT v13_probe(%s)", (child,))
    probe = cur.fetchone()[0]
    probe["sid"] = child
    planted["snap"] = probe
    before_c = children(cur, child)
    word = q1(cur, "SELECT v13_advance(%s, %s::jsonb)", (child, json.dumps(planted)))
    check("sql-intended advance creates zero children",
          children(cur, child) == before_c, (word, children(cur, child), before_c))
    conn.rollback()
    conn.close()


def main() -> int:
    server = get_server()
    build(server, BASE, "seam")
    s, named_oid, writer_oid = base_probes(server)
    print(f"[note] locked S = {s}")
    build(server, DB, "catalog")
    conn = connect(server, DB)
    cur = conn.cursor()
    named_oid = q1(cur, "SELECT 'public.v13_named_sql_writer(text)'::regprocedure::oid")
    writer_oid = q1(cur, "SELECT 'public.v13_spawn_writer_ok(text)'::regprocedure::oid")
    post_gates(cur, s, named_oid, writer_oid)
    conn.rollback()
    conn.close()
    route_arms(server)
    print("[catalog] ALL PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"[catalog] FAIL {exc}")
        raise SystemExit(1)
