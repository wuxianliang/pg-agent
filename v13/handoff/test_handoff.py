"""Stage 25 gate: handoff receipt event.

Run: uv run python v13/handoff/test_handoff.py  (exit 0 = pass)
"""
from __future__ import annotations

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
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.handoff.setup_db import DB, apply_handoff, prepare
from v13.load import SQL_LOAD_ORDER, STAGE_THROUGH

N = 0
NOT_FOUND = "v13: session not found"
EMPTY = "v13: handoff empty"
WATERMARK = "v13: handoff watermark"
HASH_MISMATCH = "v13: handoff hash"
POLICY = "v13: handoff policy"
DISABLED = "v13: handoff disabled"
WRITER = "v13: handoff writer"
SOURCE = "v13: handoff source"
KEYS = "v13: handoff keys"
SCHEMA = "v13: handoff schema"
DELIVERY = "v13: handoff delivery"
DIGEST = "v13: handoff digest"
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
QUAL_NAMES = (
    "events", "sessions", "effects", "v13_policies",
    "v13_append_event", "v13_transcript_hash", "v13_json_keys",
    "v13_json_int_ok", "v13_canonical_uuid", "digest", "gen_random_uuid",
)
FUNCS = (
    "v13_transcript_hash(uuid,bigint)",
    "v13_handoff_emit(uuid,jsonb)",
    "v13_handoff_event_guard()",
    "v13_extract_handoff(uuid,uuid,bigint)",
)
CANON_SQL = """
SELECT encode(digest(
  jsonb_build_array(
    'v1', %s::text, to_jsonb(%s::bigint),
    coalesce((
      SELECT jsonb_agg(jsonb_build_array(
               e.seq, e.type, e.payload_hash,
               coalesce(e.source_effect_id::text, '')) ORDER BY e.seq)
        FROM events e
       WHERE e.session_id = %s
         AND e.seq <= %s
         AND e.type <> 'control/handoff'
    ), '[]'::jsonb)
  )::text, 'sha256'), 'hex')
"""


def check(label: str, condition: bool, detail: object = "") -> None:
    global N
    N += 1
    mark = "PASS" if condition else "FAIL"
    extra = f": {detail}" if detail != "" and (not condition or len(str(detail)) < 240) else ""
    print(f"[{mark}] {label}{extra}")
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u() -> str:
    return str(uuid.uuid4())


def connect(server, db=DB):
    conn = psycopg2.connect(server.get_uri(db))
    conn.autocommit = False
    return conn


def connect_obs(server, db=DB):
    conn = psycopg2.connect(server.get_uri(db))
    conn.autocommit = True
    return conn


def raise_msg(cur, sql, params=None):
    cur.execute("SAVEPOINT sp_gate")
    try:
        cur.execute(sql, params)
        if cur.description is not None:
            cur.fetchall()
    except psycopg2.Error as exc:
        msg = exc.diag.message_primary
        code = exc.pgcode
        cname = exc.diag.constraint_name
        cur.execute("ROLLBACK TO SAVEPOINT sp_gate")
        return msg, code, cname
    cur.execute("ROLLBACK TO SAVEPOINT sp_gate")
    raise AssertionError(f"expected failure: {sql}")


def fails_exact(cur, sql, params, needle, label):
    msg, code, _cname = raise_msg(cur, sql, params)
    check(label, msg == needle, (msg, code))
    return msg, code


def fails_code(cur, sql, params, code, label):
    msg, got, cname = raise_msg(cur, sql, params)
    check(label, got == code, (got, msg, cname))
    return msg, cname


def q1(cur, sql, params=None):
    cur.execute(sql, params)
    return cur.fetchone()[0]


def open_session(cur):
    cur.execute("SELECT v13_open_session('{}'::jsonb)")
    return str(cur.fetchone()[0])


def prefix(cur, sid, text="hello"):
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": text})))
    return cur.fetchone()[0]


def insert_child(cur, parent):
    sid = u()
    cur.execute("SET LOCAL ROLE v13_spawn_owner")
    cur.execute(
        "INSERT INTO sessions (session_id, parent_session_id) VALUES (%s, %s)",
        (sid, parent))
    cur.execute("RESET ROLE")
    return sid


def enqueue_human(cur, sid, ref):
    cur.execute(
        "SELECT v13_enqueue_effect(%s, 'human', %s::jsonb)",
        (sid, json.dumps({"schema_version": 1, "interaction_ref": ref})))
    return str(cur.fetchone()[0])


def claim(cur, eid):
    cur.execute(
        "UPDATE effects SET status='claimed', attempt_no=1, fence=1, "
        "lease_owner='w', lease_until=clock_timestamp()+interval '1 hour' "
        "WHERE effect_id=%s RETURNING attempt_no, fence", (eid,))
    return cur.fetchone()


def event_count(cur, sid, etype=None):
    if etype is None:
        cur.execute("SELECT count(*) FROM events WHERE session_id=%s", (sid,))
    else:
        cur.execute(
            "SELECT count(*) FROM events WHERE session_id=%s AND type=%s", (sid, etype))
    return cur.fetchone()[0]


def next_seq(cur, sid):
    return q1(cur, "SELECT next_seq FROM sessions WHERE session_id=%s", (sid,))


def state_hash(cur, sid):
    return q1(cur, "SELECT v13_state_hash(%s)", (sid,))


def prosrc(cur, sig):
    return q1(cur, "SELECT prosrc FROM pg_proc WHERE oid = %s::regprocedure", (sig,))


def canon(cur, sid, cutoff):
    return q1(cur, CANON_SQL, (sid, cutoff, sid, cutoff))


def extract(cur, actor, sid, cutoff=None, two_arg=False):
    if two_arg:
        cur.execute("SELECT v13_extract_handoff(%s, %s)::text", (actor, sid))
    else:
        cur.execute(
            "SELECT v13_extract_handoff(%s, %s, %s)::text", (actor, sid, cutoff))
    return json.loads(cur.fetchone()[0])


def in_sql_string(src, pos):
    quotes = 0
    i = 0
    while i < pos:
        if src[i] == "'":
            if i + 1 < len(src) and src[i + 1] == "'":
                i += 2
                continue
            quotes += 1
        i += 1
    return quotes % 2 == 1


def bare(src, name):
    for match in re.finditer(r"\b" + re.escape(name) + r"\b", src):
        if in_sql_string(src, match.start()):
            continue
        pre = src[:match.start()]
        if pre.endswith("public.") or pre.endswith("pg_catalog."):
            continue
        return src[max(0, match.start() - 24):match.end() + 12]
    return None


def owner_insert(cur, sid, payload_sql, params, seq, source=None):
    sql = f"""
      WITH p AS (SELECT {payload_sql} AS payload)
      INSERT INTO events (session_id, seq, event_id, type, payload, payload_hash, source_effect_id)
      SELECT %s, %s, %s, 'control/handoff', p.payload,
             encode(digest(p.payload::text, 'sha256'), 'hex'), %s
        FROM p
    """
    return raise_msg(cur, sql, params + (sid, seq, u(), source))


def legal_object(delivery, transcript, up_expr):
    return (
        "jsonb_build_object("
        "'schema_version', 1, "
        "'delivery_id', %s, "
        "'transcript_hash', %s, "
        "'up_to_seq', " + up_expr + ")",
        (delivery, transcript),
    )


def main() -> int:
    sql_text = (ROOT / "v13_handoff.sql").read_text()
    readme = (ROOT / "README.md").read_text()
    low = sql_text.lower()
    for needle in (
        "v13_fork", "insert into sessions", "insert into public.sessions",
        "insert into artifacts", "insert into public.artifacts",
        "pg_read_file", "pg_terminate_backend", "create view", "on conflict",
        "create or replace function v13_state_hash",
        "create or replace function public.v13_state_hash",
        "create or replace function v13_advance",
        "create or replace function public.v13_advance",
    ):
        check(f"sql lacks {needle}", needle not in low)
    check("sql lacks xml", "xml" not in low)
    check("sql lacks LISTEN", "listen" not in low)
    check("sql lacks control_actor", "v13.control_actor" not in sql_text)
    check("sql lacks current_setting", "current_setting" not in sql_text)
    check("canon sql does not call helper", "v13_transcript_hash" not in CANON_SQL)
    grants = [ln for ln in sql_text.splitlines() if ln.strip().upper().startswith("GRANT")]
    check("grant lines avoid other roles",
          grants != [] and all(
              "v13_worker" not in ln and "v13_recall" not in ln
              and "v13_resolve" not in ln and "v13_spawn_owner" not in ln
              for ln in grants))
    check("load order handoff is 25",
          STAGE_THROUGH.get("handoff") == 25
          and SQL_LOAD_ORDER[STAGE_THROUGH["handoff"] - 1].name == "v13_handoff.sql"
          and STAGE_THROUGH.get("observe") == 24)
    check("readme names prefix and helper",
          "前缀" in readme and "v13_handoff_emit" in readme and "v13_route" in readme)

    server = get_server()
    prepare(server)
    conn = connect(server)
    cur = conn.cursor()
    hash_def = q1(cur, "SELECT pg_get_functiondef('public.v13_state_hash(uuid)'::regprocedure)")
    check("probe state_hash exclusion",
          "type NOT IN ('session/completed', 'session/failed', 'session/cancelled')" in hash_def
          and "control/handoff" not in hash_def)
    check("probe zero handoff rows",
          q1(cur, "SELECT count(*) FROM events WHERE type='control/handoff'") == 0)
    check("probe policy name free",
          q1(cur, "SELECT count(*) FROM v13_policies WHERE name='handoff_policy'") == 0)
    check("probe route policies select",
          q1(cur, "SELECT has_table_privilege('v13_route','v13_policies','SELECT')") is True)
    for sig in FUNCS:
        check(f"probe absent {sig}",
              q1(cur, "SELECT to_regprocedure(%s) IS NULL", ("public." + sig,)) is True)
    probe_sid = open_session(cur)
    prefix(cur, probe_sid, "immut")
    cur.execute("SELECT session_id, seq FROM events WHERE session_id=%s LIMIT 1", (probe_sid,))
    sample = cur.fetchone()
    check("probe events sample", sample is not None)
    msg, code, _ = raise_msg(
        cur, "UPDATE events SET payload = payload WHERE session_id=%s AND seq=%s", sample)
    check("probe payload update refused",
          code == "P0001" and msg is not None and "append-only" in msg, msg)
    msg, code, _ = raise_msg(
        cur, "DELETE FROM events WHERE session_id=%s AND seq=%s", sample)
    check("probe payload delete refused",
          code == "P0001" and msg is not None and "append-only" in msg, msg)
    keys = q1(cur, """
      SELECT v13_json_keys(
        '{"up_to_seq":1,"schema_version":1,"transcript_hash":"ab","delivery_id":"cd"}'::jsonb)
    """)
    check("probe json_keys alpha",
          list(keys) == ["delivery_id", "schema_version", "transcript_hash", "up_to_seq"], keys)
    check("probe digest overloads",
          q1(cur, "SELECT to_regprocedure('public.digest(text,text)') IS NOT NULL") is True
          and q1(cur, "SELECT to_regprocedure('public.digest(bytea,text)') IS NOT NULL") is True)
    check("probe no handoff trigger yet",
          q1(cur, """
            SELECT count(*) FROM pg_trigger
             WHERE tgrelid = 'public.events'::regclass AND NOT tgisinternal
               AND pg_get_triggerdef(oid) LIKE '%%control/handoff%%'
          """) == 0)
    conn.rollback()
    conn.close()

    apply_handoff(server)
    conn = connect(server)
    cur = conn.cursor()
    bodies = {sig: prosrc(cur, sig) for sig in FUNCS}
    for sig, src in bodies.items():
        check(f"{sig} no control_actor", "v13.control_actor" not in src)
        check(f"{sig} no current_setting", "current_setting" not in src)
        for name in QUAL_NAMES:
            found = bare(src, name)
            check(f"{sig} qualifies {name}", found is None, found)
    check("emit reads policies", "v13_policies" in bodies[FUNCS[1]])
    check("emit and extract lack EXCEPTION",
          "EXCEPTION" not in bodies[FUNCS[1]] and "EXCEPTION" not in bodies[FUNCS[3]])
    check("emit is the append call",
          bodies[FUNCS[1]].count("v13_append_event") == 1
          and "pg_catalog.gen_random_uuid()" in bodies[FUNCS[1]])
    guard = bodies[FUNCS[2]]
    order = [WRITER, SOURCE, KEYS, SCHEMA, DELIVERY, DIGEST, WATERMARK, HASH_MISMATCH]
    positions = [guard.index(item) for item in order]
    check("guard check order", positions == sorted(positions), positions)
    check("guard source predicate", "NEW.source_effect_id IS NOT NULL" in guard)
    extract_src = bodies[FUNCS[3]]
    check("extract auth before lock",
          extract_src.index("v13_control_authorized") < extract_src.index("FOR UPDATE"))
    check("extract calls emit", "v13_handoff_emit" in extract_src)
    check("emit definer guard invoker",
          q1(cur, "SELECT prosecdef FROM pg_proc WHERE oid=%s::regprocedure", (FUNCS[1],)) is True
          and q1(cur, "SELECT prosecdef FROM pg_proc WHERE oid=%s::regprocedure", (FUNCS[2],)) is False
          and q1(cur, "SELECT prosecdef FROM pg_proc WHERE oid=%s::regprocedure", (FUNCS[0],)) is False
          and q1(cur, "SELECT prosecdef FROM pg_proc WHERE oid=%s::regprocedure", (FUNCS[3],)) is False)
    check("emit owner",
          q1(cur, "SELECT proowner::regrole::text FROM pg_proc WHERE oid=%s::regprocedure",
             (FUNCS[1],)) == "v13_handoff_owner")
    for sig in FUNCS:
        cfg = q1(cur, "SELECT proconfig::text FROM pg_proc WHERE oid=%s::regprocedure", (sig,))
        check(f"{sig} search_path", cfg is not None and "search_path=pg_catalog, public" in cfg, cfg)
    check("hash stable extract volatile",
          q1(cur, "SELECT provolatile FROM pg_proc WHERE oid=%s::regprocedure", (FUNCS[0],)) == "s"
          and q1(cur, "SELECT provolatile FROM pg_proc WHERE oid=%s::regprocedure", (FUNCS[3],)) == "v")
    check("extract default null",
          "DEFAULT NULL" in q1(cur, "SELECT pg_get_function_arguments(%s::regprocedure)", (FUNCS[3],)))
    check("owner role attributes",
          q1(cur, """
            SELECT NOT rolcanlogin AND NOT rolsuper AND NOT rolcreatedb
               AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls
              FROM pg_roles WHERE rolname='v13_handoff_owner'
          """) is True)
    check("owner has no members",
          q1(cur, """
            SELECT count(*) FROM pg_auth_members m
              JOIN pg_roles r ON r.oid = m.roleid
             WHERE r.rolname='v13_handoff_owner'
          """) == 0)
    check("schema create direct acl",
          q1(cur, """
            SELECT count(*) FROM pg_namespace n, aclexplode(n.nspacl) a
             WHERE n.nspname='public'
               AND a.grantee='v13_handoff_owner'::regrole
               AND a.privilege_type='CREATE'
          """) >= 1)
    for role in ("v13_worker", "v13_recall", "v13_resolve", "v13_spawn_owner"):
        for sig in FUNCS:
            check(f"{role} no {sig}",
                  q1(cur, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, sig,)) is False)
    for sig in (FUNCS[0], FUNCS[1], FUNCS[3]):
        check(f"route has {sig}",
              q1(cur, "SELECT has_function_privilege('v13_route', %s, 'EXECUTE')", (sig,)) is True)
    check("public execute revoked",
          q1(cur, """
            SELECT count(*) FROM pg_proc p, aclexplode(p.proacl) a
             WHERE p.oid = ANY(%s::regprocedure[])
               AND a.grantee = 0 AND a.privilege_type = 'EXECUTE'
          """, (list(FUNCS),)) == 0)
    cur.execute("""
      SELECT c.relname, i.indisunique, pg_get_indexdef(i.indexrelid)
        FROM pg_index i
        JOIN pg_class c ON c.oid = i.indexrelid
        JOIN pg_class t ON t.oid = i.indrelid
       WHERE t.relname = 'events'
         AND pg_get_indexdef(i.indexrelid) LIKE '%%control/handoff%%'
       ORDER BY c.relname
    """)
    indexes = cur.fetchall()
    check("exactly two handoff indexes",
          [row[0] for row in indexes] == [
              "ux_events_handoff_delivery", "ux_events_handoff_snapshot"], indexes)
    delivery_def = indexes[0][2]
    snapshot_def = indexes[1][2]
    check("delivery index shape",
          indexes[0][1] is True and "UNIQUE" in delivery_def
          and "delivery_id" in delivery_def and "control/handoff" in delivery_def)
    check("snapshot index shape",
          indexes[1][1] is True and "UNIQUE" in snapshot_def
          and "session_id" in snapshot_def and "up_to_seq" in snapshot_def
          and "transcript_hash" in snapshot_def and "control/handoff" in snapshot_def)
    check("state_hash not replaced", "control/handoff" not in hash_def)

    parent = open_session(cur)
    child = insert_child(cur, parent)
    grand = insert_child(cur, child)
    unrelated = open_session(cur)
    prefix(cur, child, "kin")
    before_child = event_count(cur, child)
    before_parent = event_count(cur, parent)
    before_sessions = q1(cur, "SELECT count(*) FROM sessions")
    before_artifacts = q1(cur, "SELECT count(*) FROM artifacts")
    before_forked = q1(cur, "SELECT count(*) FROM events WHERE type='forked'")
    msgs = []
    codes = []
    for label, actor, target, cutoff in (
        ("self", child, child, None),
        ("grandchild", parent, grand, None),
        ("unrelated", parent, unrelated, None),
        ("unknown target", parent, u(), None),
        ("unknown actor", u(), child, None),
        ("unauth illegal cutoff", child, child, -5),
    ):
        msg, code, _ = raise_msg(
            cur, "SELECT v13_extract_handoff(%s, %s, %s)", (actor, target, cutoff))
        msgs.append(msg)
        codes.append(code)
        check(label, msg == NOT_FOUND and code == codes[0], (msg, code))
    check("auth texts identical", len(set(msgs)) == 1 and msgs[0] == NOT_FOUND, msgs)
    check("auth sqlstates identical", len(set(codes)) == 1, codes)
    check("auth text has no uuid",
          child not in NOT_FOUND and parent not in NOT_FOUND and grand not in NOT_FOUND)
    check("unauth wrote nothing", event_count(cur, child) == before_child)

    cur.execute("SAVEPOINT sp_pol")
    cur.execute("""
      INSERT INTO v13_policies (name, version, value, active)
      VALUES ('handoff_policy', 2, '{"schema_version":1,"enabled":false}'::jsonb, false)
    """)
    cur.execute("UPDATE v13_policies SET active=false WHERE name='handoff_policy' AND version=1")
    cur.execute("UPDATE v13_policies SET active=true WHERE name='handoff_policy' AND version=2")
    msg, code, _ = raise_msg(
        cur, "SELECT v13_extract_handoff(%s, %s, NULL)", (child, child))
    check("unauth ignores disabled policy", msg == NOT_FOUND and DISABLED not in (msg or ""), msg)
    cur.execute("ROLLBACK TO SAVEPOINT sp_pol")
    check("unauth still zero events", event_count(cur, child) == before_child)

    h_before = state_hash(cur, child)
    turn_before = q1(cur, "SELECT turn_no FROM sessions WHERE session_id=%s", (child,))
    status_before = q1(cur, "SELECT status FROM sessions WHERE session_id=%s", (child,))
    seq_before = next_seq(cur, child)
    latest = q1(cur, """
      SELECT max(seq) FROM events
       WHERE session_id=%s AND type <> 'control/handoff'
    """, (child,))
    cur.execute("SELECT v13_extract_handoff(%s, %s, NULL)::text", (parent, child))
    returned_text = cur.fetchone()[0]
    payload = json.loads(returned_text)
    check("four keys", set(payload) == {
        "schema_version", "delivery_id", "transcript_hash", "up_to_seq"})
    check("schema version 1", payload["schema_version"] == 1)
    check("delivery canonical", UUID_RE.match(payload["delivery_id"]) is not None)
    check("hash lowercase 64", HASH_RE.match(payload["transcript_hash"]) is not None)
    check("up_to_seq is prior event", payload["up_to_seq"] == latest)
    stored = q1(cur, """
      SELECT payload::text FROM events
       WHERE session_id=%s AND type='control/handoff'
    """, (child,))
    check("payload text equals return", stored == returned_text, (stored, returned_text))
    check("source null", q1(cur, """
      SELECT source_effect_id IS NULL FROM events
       WHERE session_id=%s AND type='control/handoff'
    """, (child,)) is True)
    receipt_seq = q1(cur, """
      SELECT seq FROM events WHERE session_id=%s AND type='control/handoff'
    """, (child,))
    check("receipt seq greater", receipt_seq > payload["up_to_seq"])
    check("one receipt", event_count(cur, child, "control/handoff") == 1)
    check("next_seq advanced once", next_seq(cur, child) == seq_before + 1)
    check("status and turn unchanged",
          q1(cur, "SELECT status FROM sessions WHERE session_id=%s", (child,)) == status_before
          and q1(cur, "SELECT turn_no FROM sessions WHERE session_id=%s", (child,)) == turn_before)
    check("no fork side effects",
          event_count(cur, parent) == before_parent
          and q1(cur, "SELECT count(*) FROM sessions") == before_sessions
          and q1(cur, "SELECT count(*) FROM artifacts") == before_artifacts
          and q1(cur, "SELECT count(*) FROM events WHERE type='forked'") == before_forked
          and q1(cur, "SELECT count(*) FROM sessions WHERE parent_session_id=%s", (child,)) == 1)
    independent = canon(cur, child, payload["up_to_seq"])
    check("independent hash matches", independent == payload["transcript_hash"], independent)
    again = q1(cur, "SELECT v13_transcript_hash(%s, %s)", (child, payload["up_to_seq"]))
    third = q1(cur, "SELECT v13_transcript_hash(%s, %s)", (child, payload["up_to_seq"]))
    check("helper stable and matches canon", again == third == independent)
    h_after = state_hash(cur, child)
    check("state_hash moves on first receipt", h_before != h_after)
    replay = extract(cur, parent, child, None)
    check("replay same delivery", replay["delivery_id"] == payload["delivery_id"])
    check("replay event count 1", event_count(cur, child, "control/handoff") == 1)
    check("replay next_seq unchanged", next_seq(cur, child) == seq_before + 1)
    check("state_hash stable on replay", state_hash(cur, child) == h_after)
    two = extract(cur, parent, child, two_arg=True)
    check("two-arg default matches", two == replay)

    second_seq = prefix(cur, child, "second")
    second = extract(cur, parent, child, None)
    check("new event new delivery",
          second["delivery_id"] != payload["delivery_id"]
          and second["up_to_seq"] == second_seq
          and event_count(cur, child, "control/handoff") == 2)
    old = extract(cur, parent, child, payload["up_to_seq"])
    check("explicit old cutoff returns first", old == payload)
    check("old cutoff did not add a receipt", event_count(cur, child, "control/handoff") == 2)

    empty = open_session(cur)
    empty_seq = next_seq(cur, empty)
    empty_n = event_count(cur, empty)
    fails_exact(cur, "SELECT v13_extract_handoff(NULL::uuid, %s, NULL)", (empty,),
                EMPTY, "empty null cutoff")
    fails_exact(cur, "SELECT v13_extract_handoff(NULL::uuid, %s, 0)", (empty,),
                WATERMARK, "empty explicit 0")
    check("empty and watermark differ", EMPTY != WATERMARK)
    check("empty wrote nothing",
          event_count(cur, empty) == empty_n and next_seq(cur, empty) == empty_seq)
    fails_exact(cur, "SELECT v13_extract_handoff(NULL::uuid, %s, -1)", (child,),
                WATERMARK, "negative cutoff")
    fails_exact(cur, "SELECT v13_extract_handoff(NULL::uuid, %s, 99)", (child,),
                WATERMARK, "missing seq")
    handoff_seq = q1(cur, """
      SELECT min(seq) FROM events WHERE session_id=%s AND type='control/handoff'
    """, (child,))
    fails_exact(cur, "SELECT v13_extract_handoff(NULL::uuid, %s, %s)", (child, handoff_seq),
                WATERMARK, "cutoff pointing at handoff")
    fails_exact(cur, "SELECT v13_transcript_hash(%s, -1)", (child,),
                WATERMARK, "helper rejects negative")
    check("negative helper wrote nothing", event_count(cur, child, "control/handoff") == 2)

    sealed = open_session(cur)
    prefix(cur, sealed, "seal")
    cur.execute("SELECT v13_closeout(%s, 'completed', 'done', false)", (sealed,))
    cur.fetchone()
    check("sealed status",
          q1(cur, "SELECT status FROM sessions WHERE session_id=%s", (sealed,)) == "completed")
    check("seal event present", event_count(cur, sealed, "session/completed") == 1)
    sealed_payload = extract(cur, None, sealed, None)
    check("terminal session extracts",
          sealed_payload["up_to_seq"] >= 1
          and canon(cur, sealed, sealed_payload["up_to_seq"]) == sealed_payload["transcript_hash"])
    check("terminal event inside window",
          q1(cur, """
            SELECT count(*) FROM events
             WHERE session_id=%s AND type='session/completed' AND seq <= %s
          """, (sealed, sealed_payload["up_to_seq"])) == 1)

    cur.execute("SAVEPOINT sp_dis")
    cur.execute("""
      INSERT INTO v13_policies (name, version, value, active)
      VALUES ('handoff_policy', 2, '{"schema_version":1,"enabled":false}'::jsonb, false)
    """)
    cur.execute("UPDATE v13_policies SET active=false WHERE name='handoff_policy' AND version=1")
    cur.execute("UPDATE v13_policies SET active=true WHERE name='handoff_policy' AND version=2")
    disabled_replay = extract(cur, parent, child, payload["up_to_seq"])
    check("disabled replay returns original", disabled_replay == payload)
    prefix(cur, child, "disabled-new")
    dis_seq = next_seq(cur, child)
    dis_n = event_count(cur, child, "control/handoff")
    fails_exact(cur, "SELECT v13_extract_handoff(%s, %s, NULL)", (parent, child),
                DISABLED, "disabled new identity")
    check("disabled new identity zero write",
          next_seq(cur, child) == dis_seq
          and event_count(cur, child, "control/handoff") == dis_n)
    cur.execute("ROLLBACK TO SAVEPOINT sp_dis")

    cur.execute("SAVEPOINT sp_zero")
    cur.execute("UPDATE v13_policies SET active=false WHERE name='handoff_policy' AND version=1")
    zero_replay = extract(cur, parent, child, payload["up_to_seq"])
    check("zero-active replay returns original", zero_replay == payload)
    prefix(cur, child, "zero-active-new")
    z_seq = next_seq(cur, child)
    z_n = event_count(cur, child, "control/handoff")
    fails_exact(cur, "SELECT v13_extract_handoff(%s, %s, NULL)", (parent, child),
                POLICY, "zero-active new extract")
    fresh = open_session(cur)
    prefix(cur, fresh, "emit-pol")
    cutoff = q1(cur, """
      SELECT max(seq) FROM events WHERE session_id=%s AND type <> 'control/handoff'
    """, (fresh,))
    fresh_hash = canon(cur, fresh, cutoff)
    built = q1(cur, """
      SELECT jsonb_build_object(
        'schema_version', 1, 'delivery_id', %s, 'transcript_hash', %s,
        'up_to_seq', to_jsonb(%s::bigint))::text
    """, (u(), fresh_hash, cutoff))
    cur.execute("SET LOCAL ROLE v13_route")
    fails_exact(cur, "SELECT v13_handoff_emit(%s, %s::jsonb)", (fresh, built),
                POLICY, "zero-active route emit")
    cur.execute("RESET ROLE")
    check("zero-active wrote nothing",
          next_seq(cur, child) == z_seq
          and event_count(cur, child, "control/handoff") == z_n
          and event_count(cur, fresh, "control/handoff") == 0)
    cur.execute("ROLLBACK TO SAVEPOINT sp_zero")

    for label, value in (
        ("extra key", '{"schema_version":1,"enabled":true,"extra":1}'),
        ("enabled type", '{"schema_version":1,"enabled":"yes"}'),
    ):
        cur.execute("SAVEPOINT sp_shape")
        cur.execute(
            "INSERT INTO v13_policies (name, version, value, active) "
            "VALUES ('handoff_policy', 2, %s::jsonb, false)", (value,))
        cur.execute("UPDATE v13_policies SET active=false WHERE name='handoff_policy' AND version=1")
        cur.execute("UPDATE v13_policies SET active=true WHERE name='handoff_policy' AND version=2")
        shape_sid = open_session(cur)
        prefix(cur, shape_sid, label)
        shape_cut = q1(cur, """
          SELECT max(seq) FROM events
           WHERE session_id=%s AND type <> 'control/handoff'
        """, (shape_sid,))
        fails_exact(cur, "SELECT v13_extract_handoff(NULL::uuid, %s, NULL)", (shape_sid,),
                    POLICY, f"shape extract {label}")
        shape_body = q1(cur, """
          SELECT jsonb_build_object(
            'schema_version', 1, 'delivery_id', %s, 'transcript_hash', %s,
            'up_to_seq', to_jsonb(%s::bigint))::text
        """, (u(), canon(cur, shape_sid, shape_cut), shape_cut))
        cur.execute("SET LOCAL ROLE v13_route")
        fails_exact(cur, "SELECT v13_handoff_emit(%s, %s::jsonb)", (shape_sid, shape_body),
                    POLICY, f"shape emit {label}")
        cur.execute("RESET ROLE")
        check(f"shape {label} zero write", event_count(cur, shape_sid, "control/handoff") == 0)
        cur.execute("ROLLBACK TO SAVEPOINT sp_shape")

    conn.rollback()
    conn.close()

    setup = connect(server)
    sc = setup.cursor()
    route_parent = open_session(sc)
    route_child = insert_child(sc, route_parent)
    prefix(sc, route_child, "route-commit")
    setup.commit()
    setup.close()
    route = connect(server)
    rc = route.cursor()
    rc.execute("SET ROLE v13_route")
    committed = extract(rc, route_parent, route_child, None)
    route.commit()
    route.close()
    verify = connect(server)
    vc = verify.cursor()
    vc.execute("SET ROLE v13_route")
    seen = q1(vc, """
      SELECT payload->>'delivery_id' FROM events
       WHERE session_id=%s AND type='control/handoff'
    """, (route_child,))
    check("route commit kept receipt", seen == committed["delivery_id"], seen)
    verify.commit()
    verify.close()

    conn = connect(server)
    cur = conn.cursor()
    gsid = open_session(cur)
    for i in range(3):
        prefix(cur, gsid, f"g{i}")
    check("fixture seq 2 exists",
          q1(cur, "SELECT count(*) FROM events WHERE session_id=%s AND seq=2 AND type <> 'control/handoff'",
             (gsid,)) == 1)
    check("fixture seq 1 exists",
          q1(cur, "SELECT count(*) FROM events WHERE session_id=%s AND seq=1 AND type <> 'control/handoff'",
             (gsid,)) == 1)
    h2 = canon(cur, gsid, 2)
    h1 = canon(cur, gsid, 1)
    cur.execute("SET LOCAL ROLE v13_handoff_owner")

    def guard_fail(up_literal, transcript, cutoff_note, seq, label, needle, source=None):
        expr, params = legal_object(u(), transcript, "%s::jsonb")
        msg, code, _cname = owner_insert(cur, gsid, expr, params + (up_literal,), seq, source)
        check(label, msg == needle and code != "22003", (msg, code, cutoff_note))
        return msg

    up15 = q1(cur, "SELECT (jsonb_build_object('up_to_seq', '1.5'::jsonb) -> 'up_to_seq')::text")
    check("1.5 stored text", up15 == "1.5", up15)
    guard_fail("1.5", h2, "cutoff-2", 1000, "guard 1.5", WATERMARK)
    up10 = q1(cur, "SELECT (jsonb_build_object('up_to_seq', '1.0'::jsonb) -> 'up_to_seq')::text")
    check("1.0 stored text", up10 == "1.0", up10)
    guard_fail("1.0", h1, "cutoff-1", 1001, "guard 1.0", WATERMARK)
    guard_fail("9223372036854775808", h2, "overflow", 1002, "guard overflow", WATERMARK)
    guard_fail("99", "a" * 64, "gap", 1003, "guard missing seq", WATERMARK)
    expr, params = legal_object(u(), "ab", "0")
    msg, code, _ = owner_insert(cur, gsid, expr, params, 1004)
    check("guard short hash", msg == DIGEST, (msg, code))
    expr, params = legal_object("NOT-A-UUID", "a" * 64, "0")
    msg, code, _ = owner_insert(cur, gsid, expr, params, 1005)
    check("guard bad delivery", msg == DELIVERY, (msg, code))
    expr = (
        "jsonb_build_object('schema_version', '1', 'delivery_id', %s, "
        "'transcript_hash', %s, 'up_to_seq', 0)"
    )
    msg, code, _ = owner_insert(cur, gsid, expr, (u(), "a" * 64), 1006)
    check("guard schema string", msg == SCHEMA, (msg, code))
    expr = "jsonb_build_object('schema_version', 1, 'delivery_id', %s)"
    msg, code, _ = owner_insert(cur, gsid, expr, (u(),), 1007)
    check("guard missing key", msg == KEYS, (msg, code))
    expr = (
        "jsonb_build_object('schema_version', 1, 'delivery_id', %s, "
        "'transcript_hash', %s, 'up_to_seq', 0, 'extra', 1)"
    )
    msg, code, _ = owner_insert(cur, gsid, expr, (u(), "a" * 64), 1008)
    check("guard extra key", msg == KEYS, (msg, code))
    wrong = "b" * 64
    check("mismatch hash differs", wrong != h1)
    expr, params = legal_object(u(), wrong, "1")
    msg, code, _ = owner_insert(cur, gsid, expr, params, 1009)
    check("guard hash mismatch", msg == HASH_MISMATCH, (msg, code))
    expr, params = legal_object(u(), h1, "1")
    msg, code, _ = owner_insert(cur, gsid, expr, params, 1010, u())
    check("guard source", msg == SOURCE, (msg, code))
    cur.execute("RESET ROLE")
    cur.execute("SET LOCAL ROLE v13_route")
    fails_exact(
        cur, "SELECT v13_append_event(%s, %s, 'control/handoff', '{}'::jsonb, NULL)",
        (gsid, u()), WRITER, "route append writer")
    cur.execute("RESET ROLE")
    check("guard negatives wrote nothing", event_count(cur, gsid, "control/handoff") == 0)
    conn.rollback()

    conn = connect(server)
    cur = conn.cursor()
    esid = open_session(cur)
    prefix(cur, esid, "e0")
    prefix(cur, esid, "e1")
    cut = q1(cur, """
      SELECT max(seq) FROM events WHERE session_id=%s AND type <> 'control/handoff'
    """, (esid,))
    body = q1(cur, """
      SELECT jsonb_build_object(
        'schema_version', 1, 'delivery_id', %s, 'transcript_hash', %s,
        'up_to_seq', to_jsonb(%s::bigint))::text
    """, (u(), canon(cur, esid, cut), cut))
    cur.execute("SET LOCAL ROLE v13_route")
    emitted = q1(cur, "SELECT v13_handoff_emit(%s, %s::jsonb)", (esid, body))
    check("route emit success", emitted == cut + 1, emitted)
    check("route emit row", event_count(cur, esid, "control/handoff") == 1)
    new_body = q1(cur, """
      SELECT jsonb_build_object(
        'schema_version', 1, 'delivery_id', %s, 'transcript_hash', %s,
        'up_to_seq', to_jsonb(%s::bigint))::text
    """, (u(), canon(cur, esid, cut), cut))
    _msg, cname = fails_code(
        cur, "SELECT v13_handoff_emit(%s, %s::jsonb)", (esid, new_body),
        "23505", "route emit same snapshot")
    check("snapshot constraint name", cname == "ux_events_handoff_snapshot", cname)
    cur.execute("RESET ROLE")
    cur.execute("SAVEPOINT sp_edis")
    cur.execute("""
      INSERT INTO v13_policies (name, version, value, active)
      VALUES ('handoff_policy', 2, '{"schema_version":1,"enabled":false}'::jsonb, false)
    """)
    cur.execute("UPDATE v13_policies SET active=false WHERE name='handoff_policy' AND version=1")
    cur.execute("UPDATE v13_policies SET active=true WHERE name='handoff_policy' AND version=2")
    prefix(cur, esid, "e2")
    cut2 = q1(cur, """
      SELECT max(seq) FROM events WHERE session_id=%s AND type <> 'control/handoff'
    """, (esid,))
    dis_body = q1(cur, """
      SELECT jsonb_build_object(
        'schema_version', 1, 'delivery_id', %s, 'transcript_hash', %s,
        'up_to_seq', to_jsonb(%s::bigint))::text
    """, (u(), canon(cur, esid, cut2), cut2))
    dis_n = event_count(cur, esid, "control/handoff")
    dis_seq = next_seq(cur, esid)
    cur.execute("SET LOCAL ROLE v13_route")
    fails_exact(cur, "SELECT v13_handoff_emit(%s, %s::jsonb)", (esid, dis_body),
                DISABLED, "route emit disabled")
    cur.execute("RESET ROLE")
    check("disabled emit zero write",
          event_count(cur, esid, "control/handoff") == dis_n
          and next_seq(cur, esid) == dis_seq)
    cur.execute("ROLLBACK TO SAVEPOINT sp_edis")

    first = extract(cur, None, esid, 0)
    reused = first["delivery_id"]
    other = q1(cur, """
      SELECT jsonb_build_object(
        'schema_version', 1, 'delivery_id', %s, 'transcript_hash', %s,
        'up_to_seq', to_jsonb(1::bigint))::text
    """, (reused, canon(cur, esid, 1)))
    cur.execute("SET LOCAL ROLE v13_handoff_owner")
    _msg, cname = fails_code(cur, """
      WITH p AS (SELECT %s::jsonb AS payload)
      INSERT INTO events (session_id, seq, event_id, type, payload, payload_hash)
      SELECT %s, 1100, %s, 'control/handoff', p.payload,
             encode(digest(p.payload::text, 'sha256'), 'hex')
        FROM p
    """, (other, esid, u()), "23505", "reused delivery")
    check("delivery constraint name", cname == "ux_events_handoff_delivery", cname)
    cur.execute("RESET ROLE")
    conn.rollback()
    conn.close()

    run_race(server)
    run_cancel(server)
    run_wall(server)
    run_six(server)

    print(f"[handoff] ALL PASS ({N})")
    return 0


def run_race(server):
    setup = connect(server)
    sc = setup.cursor()
    parent = open_session(sc)
    child = insert_child(sc, parent)
    prefix(sc, child, "race")
    setup.commit()
    setup.close()
    hold = connect(server)
    h = hold.cursor()
    h.execute("SET ROLE v13_route")
    h.execute("SELECT v13_extract_handoff(%s, %s, NULL)::text", (parent, child))
    first = json.loads(h.fetchone()[0])
    box = {"pid": None, "payload": None, "msg": None}
    ready = threading.Event()

    def _run():
        c = connect(server)
        k = c.cursor()
        try:
            k.execute("SET statement_timeout = '20000'")
            k.execute("SET ROLE v13_route")
            k.execute("SELECT pg_backend_pid()")
            box["pid"] = k.fetchone()[0]
            ready.set()
            k.execute("SELECT v13_extract_handoff(%s, %s, NULL)::text", (parent, child))
            box["payload"] = json.loads(k.fetchone()[0])
            c.commit()
        except psycopg2.Error as exc:
            box["msg"] = exc.diag.message_primary
            c.rollback()
        finally:
            c.close()

    obs = connect_obs(server)
    thread = threading.Thread(target=_run)
    thread.start()
    check("race backend started", ready.wait(5), box)
    seen = False
    for _ in range(50):
        if box["pid"] is not None:
            nwait = q1(obs.cursor(),
                       "SELECT count(*) FROM pg_locks WHERE pid=%s AND NOT granted",
                       (box["pid"],))
            if nwait >= 1:
                seen = True
                break
        if box["msg"] is not None or box["payload"] is not None:
            break
        time.sleep(0.1)
    check("race blocked on session lock", seen, box)
    hold.commit()
    thread.join(timeout=20)
    hold.close()
    obs.close()
    check("race same payload", box["payload"] == first, box)
    verify = connect(server)
    vc = verify.cursor()
    check("race one receipt",
          q1(vc, "SELECT count(*) FROM events WHERE session_id=%s AND type='control/handoff'",
             (child,)) == 1)
    verify.rollback()
    verify.close()


def run_cancel(server):
    admin = connect(server)
    ac = admin.cursor()
    ac.execute("""
      CREATE FUNCTION v13_handoff_test_block() RETURNS trigger
      LANGUAGE plpgsql AS $fn$
      BEGIN
        PERFORM pg_catalog.pg_advisory_lock(25, 4242);
        RETURN NEW;
      END
      $fn$
    """)
    ac.execute("""
      CREATE TRIGGER trg_handoff_test_block
        BEFORE INSERT ON events
        FOR EACH ROW
        WHEN (NEW.type = 'control/handoff')
        EXECUTE FUNCTION v13_handoff_test_block()
    """)
    parent = open_session(ac)
    child = insert_child(ac, parent)
    prefix(ac, child, "cancel-me")
    before_n = event_count(ac, child)
    before_seq = next_seq(ac, child)
    admin.commit()
    holder = connect(server)
    hc = holder.cursor()
    hc.execute("SELECT pg_catalog.pg_advisory_lock(25, 4242)")
    holder.commit()
    box = {"conn": None, "pid": None, "msg": None, "code": None}
    ready = threading.Event()

    def _run():
        c = connect(server)
        box["conn"] = c
        k = c.cursor()
        try:
            k.execute("SET ROLE v13_route")
            k.execute("SELECT pg_backend_pid()")
            box["pid"] = k.fetchone()[0]
            ready.set()
            k.execute("SELECT v13_extract_handoff(%s, %s, NULL)", (parent, child))
            k.fetchone()
            c.commit()
            box["msg"] = "committed"
        except psycopg2.Error as exc:
            box["msg"] = exc.diag.message_primary
            box["code"] = exc.pgcode
            c.rollback()
        finally:
            c.close()

    obs = connect_obs(server)
    thread = threading.Thread(target=_run)
    thread.start()
    check("cancel backend started", ready.wait(5), box)
    seen = False
    try:
        for _ in range(50):
            if box["pid"] is not None:
                nwait = q1(obs.cursor(), """
                  SELECT count(*) FROM pg_locks
                   WHERE pid=%s AND locktype='advisory' AND NOT granted
                     AND classid=25 AND objid=4242
                """, (box["pid"],))
                if nwait >= 1:
                    seen = True
                    break
            if box["msg"] is not None:
                break
            time.sleep(0.1)
        check("cancel blocked in insert trigger", seen, box)
        box["conn"].cancel()
        thread.join(timeout=20)
        check("cancel sqlstate", box["code"] == "57014", box)
        verify = connect(server)
        vc = verify.cursor()
        check("cancel rolled back events", event_count(vc, child) == before_n)
        check("cancel rolled back next_seq", next_seq(vc, child) == before_seq)
        verify.rollback()
        verify.close()
    finally:
        obs.close()
        hc.execute("SELECT pg_catalog.pg_advisory_unlock(25, 4242)")
        holder.commit()
        holder.close()
        ac.execute("DROP TRIGGER trg_handoff_test_block ON events")
        ac.execute("DROP FUNCTION v13_handoff_test_block()")
        admin.commit()
        admin.close()


def run_wall(server):
    conn = connect(server)
    cur = conn.cursor()
    sid = open_session(cur)
    prefix(cur, sid, "wall")
    cur.execute(
        "SELECT v13_enqueue_effect(%s, 'tool', %s::jsonb, %s)",
        (sid, json.dumps({
            "tool": "send_summary_email", "params": {},
            "handler": "worker:send_summary_email", "tools_revision": 1,
        }), "send_summary_email"))
    eid = cur.fetchone()[0]
    cur.execute(
        "UPDATE effects SET status='claimed', attempt_no=1, fence=1 WHERE effect_id=%s",
        (eid,))
    word = q1(cur, "SELECT v13_complete(%s, 1, 1, 'unknown', %s::jsonb)",
              (eid, json.dumps({"x": 1})))
    check("wall fixture accepted", word == "accepted", word)
    check("wall fixture blocked",
          q1(cur, "SELECT status FROM sessions WHERE session_id=%s", (sid,)) == "blocked_unknown")
    conn.commit()
    cutoff = q1(cur, """
      SELECT max(seq) FROM events WHERE session_id=%s AND type <> 'control/handoff'
    """, (sid,))
    body = q1(cur, """
      SELECT jsonb_build_object(
        'schema_version', 1, 'delivery_id', %s, 'transcript_hash', %s,
        'up_to_seq', to_jsonb(%s::bigint))::text
    """, (u(), canon(cur, sid, cutoff), cutoff))
    cur.execute("SET ROLE v13_handoff_owner")
    try:
        cur.execute("SELECT v13_handoff_emit(%s, %s::jsonb)", (sid, body))
        emitted = cur.fetchone()[0]
        conn.commit()
    except psycopg2.Error as exc:
        check("blocked_unknown wall did not raise", False,
              (exc.pgcode, exc.diag.message_primary))
        return
    check("blocked_unknown owner emit committed", emitted > cutoff, emitted)
    conn.close()


def run_six(server):
    setup = connect(server)
    sc = setup.cursor()
    parent = open_session(sc)
    observed = insert_child(sc, parent)
    prefix(sc, observed, "six")
    human = insert_child(sc, parent)
    prefix(sc, human, "human")
    ref = "ix-handoff-six"
    hid = enqueue_human(sc, human, ref)
    attempt, fence = claim(sc, hid)
    cancelled = insert_child(sc, parent)
    prefix(sc, cancelled, "cancel")
    setup.commit()
    setup.close()
    route = connect(server)
    rc = route.cursor()
    rc.execute("SET ROLE v13_route")
    auth = q1(rc, "SELECT v13_control_authorized(%s, %s)", (parent, observed))
    check("six authorized", auth is True)
    rc.execute("SELECT count(*) FROM v13_observe(%s, %s::uuid[])", (parent, [observed]))
    check("six observe", rc.fetchone()[0] == 1)
    rc.execute("SELECT count(*) FROM v13_session_log(%s, %s)", (parent, observed))
    check("six session_log", rc.fetchone()[0] >= 1)
    rc.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (observed, u(), json.dumps({"text": "inject"})))
    check("six inject", rc.fetchone()[0] >= 0)
    rc.execute(
        "SELECT v13_complete(%s, %s, %s, %s, 'succeeded', %s::jsonb)",
        (parent, hid, attempt, fence,
         json.dumps({"schema_version": 1, "interaction_ref": ref, "response": "yes"})))
    check("six respond", rc.fetchone()[0] == "accepted")
    rc.execute("SELECT v13_cancel(%s, %s)", (parent, cancelled))
    check("six cancel", rc.fetchone()[0] == "accepted")
    handed = extract(rc, parent, observed, None)
    check("six extract", set(handed) == {
        "schema_version", "delivery_id", "transcript_hash", "up_to_seq"})
    route.commit()
    route.close()
    verify = connect(server)
    vc = verify.cursor()
    check("six inject kept",
          q1(vc, """
            SELECT count(*) FROM events
             WHERE session_id=%s AND type='user/message' AND payload->>'text'='inject'
          """, (observed,)) == 1)
    check("six respond kept",
          q1(vc, "SELECT status FROM effects WHERE effect_id=%s", (hid,)) == "succeeded")
    check("six cancel kept",
          q1(vc, """
            SELECT count(*) FROM events WHERE session_id=%s AND type='cancel/requested'
          """, (cancelled,)) == 1)
    check("six extract kept",
          q1(vc, """
            SELECT payload->>'delivery_id' FROM events
             WHERE session_id=%s AND type='control/handoff'
          """, (observed,)) == handed["delivery_id"])
    verify.rollback()
    verify.close()
    print("[phase-b] observe=ok log=ok inject=ok respond=ok cancel=ok authorized=ok extract=ok")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"[handoff] FAIL {exc}")
        raise SystemExit(1)
    except Exception as exc:
        print(f"[handoff] FAIL {exc}")
        raise SystemExit(1)
