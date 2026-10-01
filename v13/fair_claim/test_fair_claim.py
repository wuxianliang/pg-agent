"""Phase D fair_claim gate.

Run: UV_FROZEN=1 uv run python v13/fair_claim/test_fair_claim.py
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_REPEATABLE_READ

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.load import SQL_LOAD_ORDER, STAGE_THROUGH, files_through, run_psql
from v13.fair_claim.setup_db import DB, main as setup_db
import v13.fair_claim.setup_db as setup_mod

N = 0
SQL = (ROOT / "v13_fair_claim.sql").read_text()
README = (ROOT / "README.md").read_text()
SRC = (ROOT / "test_fair_claim.py").read_text()
WS = "/tmp/ws"
ASK = "v13: claim fair: ask_user"
HASH_FNS = (
    "public.v13_claim(text,integer)",
    "public.v13_advance(uuid,jsonb)",
    "public.v13_goal_fingerprint(uuid)",
    "public.v13_scheduler_hint(uuid)",
    "public.v13_recover_idle()",
    "public.v13_requeue_stale()",
    "public.v13_enqueue_effect(uuid,text,jsonb,text)",
    "public.v13_should_run(uuid)",
    "public.v13_should_run_gate(uuid)",
    "public.v13_quota_eligible(uuid)",
    "public.v13_advisory_class(text)",
    "public.v13_spawn_subsession(uuid,jsonb)",
    "public.v13_spawn_occupancy(uuid)",
    "public.v13_tool_effect_open(uuid,uuid,text,text,text[],jsonb)",
    "public.v13_goal_lifecycle(uuid)",
    "public.v13_goal_stop(uuid,text)",
    "public.v13_attempt_ok(text,integer)",
    "public.v13_requires_worktree(text)",
)
SIX = ("attempt_no", "effect_id", "fence", "kind", "request", "root_session_id")
README_NEEDLES = (
    "fair_claim 在政策不存在时插入 claimed_cap=2",
    "已有不相等行则装载 RAISE，不覆盖",
    '{"max_nonterminal":8,"max_depth":4,"max_fanout":8}',
    "LANGUAGE sql STABLE",
    "接受夹具 llm 请求",
    "13002",
    "13003",
    "帽不约束活体 `v13_claim`",
    "`infinity` 占席且本期不释放",
    "`cap=1` 连续领用残留只指仍回到 ready 的路径，不是过期 claimed 转 unknown，也不是 attempt 耗尽转 failed",
    "根会话 FOR UPDATE 之后、任何 effect 行锁之前，若 effect 所在会话不是该根，再锁这一把子会话；顺序先根后子，不得反过来，不得再锁第三把会话；不得在已持有 effect 行锁后再锁 sessions",
    "13002 在会话行锁之前取得；排头的会话锁等待会阻塞所有后续公平领用；活体 v13_claim 不取 13002",
    "path_guard_execute_reaches_recheck 的 SET ROLE 证明只覆盖直接 enqueue 路径",
    "打开者路径上触发器嵌套函数的运行时身份是调用时的有效身份",
    "未证明产品角色",
    "未证明 material 已扣",
    "64 只是上溯守卫",
    "有限租约过期后，席位只有在外部调用未改过的 v13_requeue_stale 时才释放；fair_driver 不是这个调用者",
    "只跑 `stopped_root_not_fair_claimed`",
    "§7.1 其余断言仍须通过才允许整个 fair_claim gate 标 exit_0",
)


def check(label, condition, detail=""):
    global N
    N += 1
    mark = "PASS" if condition else "FAIL"
    extra = f": {detail}" if detail and (not condition or len(str(detail)) < 240) else ""
    print(f"[{mark}] {label}{extra}")
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u():
    return str(uuid.uuid4())


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def as_obj(value):
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


def connect(server):
    conn = psycopg2.connect(server.get_uri(DB))
    conn.autocommit = False
    return conn


def q1(cur, sql, params=None):
    cur.execute(sql, params)
    row = cur.fetchone()
    return None if row is None else row[0]


def fails(cur, sql, params, needle, label):
    cur.execute("SAVEPOINT sp")
    try:
        cur.execute(sql, params)
    except psycopg2.Error as exc:
        msg = exc.diag.message_primary or str(exc).splitlines()[0]
        check(label, needle in msg, msg)
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        return msg
    cur.execute("ROLLBACK TO SAVEPOINT sp")
    raise AssertionError(f"{label}: expected failure")


def fn_hash(cur, sig):
    return q1(
        cur,
        "SELECT encode(digest(convert_to(pg_get_functiondef(%s::regprocedure), 'UTF8'), 'sha256'), 'hex')",
        (sig,))


def fn_src(cur, sig):
    return q1(cur, "SELECT pg_get_functiondef(%s::regprocedure)", (sig,))


def hashes(cur):
    missing = [sig for sig in HASH_FNS if q1(cur, "SELECT to_regprocedure(%s)", (sig,)) is None]
    if missing:
        raise AssertionError(f"{ASK}: missing {missing}")
    return tuple(fn_hash(cur, sig) for sig in HASH_FNS)


def open_session(cur, spec=None):
    return str(q1(cur, "SELECT v13_open_session(%s::jsonb)", (json.dumps(spec or {}),)))


def prefix(cur, sid, text="hello fair"):
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": text})))


def max_seq(cur, sid):
    return q1(cur, "SELECT max(seq) FROM events WHERE session_id=%s", (sid,))


def writer(cur, sid, canonical):
    cur.execute(
        "SELECT v13_plan_writer(%s::uuid, %s::uuid, %s::uuid, %s, %s::jsonb, %s::timestamptz)",
        (None, sid, u(), canonical["call_kind"], json.dumps(canonical), None))
    return as_obj(cur.fetchone()[0])


def plant(cur, sid):
    tid = u()
    text = "pending advancement"
    body = {
        "schema_version": 1,
        "call_kind": "plan_commit",
        "based_on_seq": max_seq(cur, sid),
        "supersedes": None,
        "todos": [{
            "todo_id": tid,
            "text": text,
            "text_hash": sha(text),
            "task_class": "advancement_task",
            "status": "pending",
            "due": None,
            "verb": "add_new",
        }],
    }
    writer(cur, sid, body)
    return tid


def enqueue(cur, sid, kind, request, tool_name=None):
    if tool_name:
        return str(q1(
            cur, "SELECT v13_enqueue_effect(%s, %s, %s::jsonb, %s)",
            (sid, kind, json.dumps(request), tool_name)))
    return str(q1(
        cur, "SELECT v13_enqueue_effect(%s, %s, %s::jsonb)",
        (sid, kind, json.dumps(request))))


def llm_req(tag):
    return {"route": {"action": "llm", "reason": tag}}


def ws_req(tool, paths, payload, label="workspace_edit"):
    return {
        "schema_version": 1,
        "tool": tool,
        "label": label,
        "paths": paths,
        "attempt_key": u(),
        "payload": payload,
    }


def claim_fair(cur, worker=None, lease=60000):
    worker = worker or ("w-" + u()[:8])
    return as_obj(q1(cur, "SELECT v13_claim_fair(%s, %s)", (worker, lease)))


def live_claim(cur, worker=None, lease=60000):
    worker = worker or ("live-" + u()[:8])
    return as_obj(q1(cur, "SELECT v13_claim(%s, %s)", (worker, lease)))


def complete_failed(cur, row):
    if not row:
        return None
    return q1(
        cur, "SELECT v13_complete(%s::uuid, %s, %s, 'failed', NULL)",
        (row["effect_id"], row["attempt_no"], row["fence"]))


def snapshot(cur):
    return as_obj(q1(cur, "SELECT v13_fair_snapshot()"))


def n_events(cur):
    return int(q1(cur, "SELECT count(*) FROM events"))


def n_effects(cur):
    return int(q1(cur, "SELECT count(*) FROM effects"))


def n_sessions(cur):
    return int(q1(cur, "SELECT count(*) FROM sessions"))


def claimed_count(cur):
    return int(q1(cur, "SELECT count(*) FROM effects WHERE status='claimed'"))


def effect_status(cur, eid):
    return q1(cur, "SELECT status FROM effects WHERE effect_id=%s", (eid,))


def four_arm(cur, eid):
    return bool(q1(cur, """
        SELECT e.status = 'ready'
           AND v13_attempt_ok(e.kind, e.attempt_no)
           AND (e.op_seq IS NULL OR e.op_seq = (
                SELECT min(x.op_seq) FROM effects x
                 WHERE x.session_id = e.session_id
                   AND x.mutation_scope = e.mutation_scope
                   AND x.status <> 'succeeded'))
           AND NOT (
             v13_requires_worktree(e.tool_name)
             AND NOT EXISTS (
               SELECT 1 FROM latches l
                WHERE l.session_id = e.session_id AND l.name = 'worktree'))
          FROM effects e WHERE e.effect_id = %s
    """, (eid,)))


def spawn_one(cur, sid, task="child-task"):
    spec = {"schema_version": 1, "children": [{"tool_call_id": u(), "task": task}]}
    out = as_obj(q1(cur, "SELECT v13_spawn_subsession(%s, %s::jsonb)",
                    (sid, json.dumps(spec))))
    return str(out["children"][0]["session_id"])


def opener(cur, sid, root=WS):
    req = ws_req("ls", ["dir"], {"path": "dir"})
    return as_obj(q1(
        cur,
        "SELECT v13_tool_effect_open(%s::uuid, %s::uuid, %s, %s, %s::text[], %s::jsonb)",
        (None, sid, "workspace_edit", root, [root, "/tmp/ws/sub"], json.dumps(req))))


def isolated(cur, fn):
    cur.execute("SAVEPOINT iso")
    try:
        fn()
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT iso")


def drain_pool(server):
    conn = connect(server)
    try:
        cur = conn.cursor()
        for _ in range(32):
            row = claim_fair(cur, "drain")
            if row is None:
                row = live_claim(cur, "drain-live")
            if row is None:
                break
            complete_failed(cur, row)
        conn.commit()
    finally:
        conn.close()


def wait_ungranted(server, pid, classid=None, timeout=8.0):
    obs = psycopg2.connect(server.get_uri(DB))
    obs.autocommit = True
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if classid is None:
                n = q1(
                    obs.cursor(),
                    "SELECT count(*) FROM pg_locks WHERE pid=%s AND NOT granted",
                    (pid,))
            else:
                n = q1(
                    obs.cursor(),
                    "SELECT count(*) FROM pg_locks WHERE pid=%s AND locktype='advisory' "
                    "AND classid=%s AND NOT granted",
                    (pid, classid))
            if n:
                return True
            time.sleep(0.05)
        return False
    finally:
        obs.close()


def test_stage_bytes():
    paths = [
        "v13/schema", "v13/resolve", "v13/loop", "v13/twophase", "v13/envelope",
        "v13/manifest", "v13/chunks", "v13/recall", "v13/characterize", "v13/filter",
        "v13/memory", "v13/economy", "v13/summary", "v13/periphery", "v13/mgraph",
        "v13/mgraph_assembly", "v13/control", "v13/spawn", "v13/fanout", "v13/triage",
        "v13/seam", "v13/catalog", "v13/acl", "v13/observe", "v13/handoff",
        "v13/should_run", "v13/quota_window", "v13/attention", "v13/govern",
        "docs/plans/v13-long-loop-plan-2026-09-28.md",
        "docs/plans/v13-long-loop-phase-a-plan-2026-09-29.md",
        "docs/plans/v13-long-loop-phase-b-plan-2026-09-29.md",
        "docs/plans/v13-long-loop-phase-c-plan-2026-09-29.md",
        "v13/workspace_admit", "v13/workspace_exec", "v13/plan_arm",
        "v13/loop_driver", "v13/real_chain", "v13/workflow_bind",
        "v13/plan_contract", "v13/plan_read", "v13/frontier_gap",
        "v13/goal_supervise", "v13/goal_supervisor",
    ]
    diff = subprocess.check_output(["git", "diff", "HEAD", "--", *paths], cwd=AGENT_ROOT)
    load = subprocess.check_output(
        ["git", "diff", "HEAD", "--", "v13/load.py"], cwd=AGENT_ROOT).decode()
    removed = [
        line for line in load.splitlines()
        if line.startswith("-") and not line.startswith("---")
    ]
    text = (AGENT_ROOT / "v13/load.py").read_text()
    order = text.split("STAGE_THROUGH", 1)[0]
    through = text.split("STAGE_THROUGH", 1)[1]
    tail_ok = (
        order.rfind("goal_supervise") < order.rfind("fair_claim")
        and through.rfind('"goal_supervise": 38') < through.rfind('"fair_claim": 39')
        and "fair_claim" not in order[:order.rfind("goal_supervise")]
        and files_through("fair_claim")[-1].name == "v13_fair_claim.sql"
        and len(files_through("fair_claim")) == 39
        and len(SQL_LOAD_ORDER) == 39
        and STAGE_THROUGH["fair_claim"] == 39
    )
    load_ok = "fair_claim" in load and removed == [] and tail_ok
    check("stage_bytes", diff == b"" and load_ok, (removed, tail_ok, bool(load.strip())))


def test_static_source():
    low = SQL.lower()
    check(
        "no_table_no_column",
        re.search(r"(?im)^\s*CREATE\s+TABLE\b", SQL) is None
        and re.search(r"(?im)^\s*ALTER\s+TABLE\b", SQL) is None,
        None)
    check(
        "no_second_advance_replace",
        re.search(
            r"(?im)^\s*CREATE\s+(OR\s+REPLACE\s+)?FUNCTION\s+(public\.)?v13_claim\s*\(",
            SQL) is None
        and re.search(
            r"(?im)^\s*CREATE\s+(OR\s+REPLACE\s+)?FUNCTION\s+(public\.)?v13_advance\s*\(",
            SQL) is None,
        None)
    check(
        "snapshot_does_not_raise_on_occupancy",
        "v13_spawn_occupancy" not in SQL,
        None)
    check("no_new_event_type", "INSERT INTO " + "events" not in SQL and "insert into events" not in low)
    banned_insert = tuple("INSERT INTO " + t for t in ("effects", "events", "sessions", "artifacts"))
    check(
        "no_insert_in_test",
        all(b not in SRC for b in banned_insert),
        None)
    created = [m.group(0) for m in re.finditer(r"UPDATE effects SET \w+", SRC)]
    allowed_set = {"created_at", "lease_until", "attempt_no"}
    sets = {part.split()[-1] for part in created}
    check("update_effects_whitelist", sets <= allowed_set, sets)
    static_def = SRC.split("def test_static_source", 1)[-1].split("\ndef ", 1)[0]
    defs = {}
    for name in (
        "tie_oldest_created_at",
        "peer_idle_beats_older_sibling_backlog",
        "root_should_run_false_does_not_block_other_ready",
        "unknown_does_not_consume_cap",
        "requeue_wall_unchanged_frees_cap",
        "attempt_not_ok_skipped",
        "test_reread",
    ):
        defs[name] = SRC.split("def " + name, 1)[-1].split("\ndef ", 1)[0]
    for needle, names in (
        ("UPDATE effects SET created_at", (
            "tie_oldest_created_at",
            "peer_idle_beats_older_sibling_backlog",
            "root_should_run_false_does_not_block_other_ready",
            "test_reread",
        )),
        ("UPDATE effects SET lease_until", (
            "unknown_does_not_consume_cap",
            "requeue_wall_unchanged_frees_cap",
            "test_reread",
        )),
        ("UPDATE effects SET attempt_no", ("attempt_not_ok_skipped",)),
    ):
        allowed_blob = "\n".join(defs[n] for n in names)
        rest = SRC.count(needle) - static_def.count(needle)
        check(
            needle.replace(" ", "_") + "_sites",
            rest >= 1 and rest == allowed_blob.count(needle),
            (rest, allowed_blob.count(needle)))
    missing = [s for s in README_NEEDLES if s not in README]
    check("readme_needles", missing == [], missing)
    check(
        "opener_invoker_sentence_only",
        "打开者路径上触发器嵌套函数的运行时身份是调用时的有效身份" in README
        and "打开者路径上触发器嵌套函数的运行时身份是打开者 owner" not in README,
        None)
    check("stannum_absent", "stannum" not in SQL.lower())
    check("no_grant_claim_fair", "GRANT EXECUTE ON FUNCTION\n  public.v13_claim_fair" not in SQL
          and "GRANT EXECUTE ON FUNCTION public.v13_claim_fair" not in SQL)


def test_reread(cur):
    check(
        "load_tail_goal_supervise",
        SQL_LOAD_ORDER[-2].name == "v13_goal_supervise.sql"
        and SQL_LOAD_ORDER[-1].name == "v13_fair_claim.sql",
        SQL_LOAD_ORDER[-2].name)
    names = (
        "v13_claim_fair", "v13_fair_root", "v13_fair_eligible",
        "v13_fair_snapshot", "v13_path_conflict_locked",
        "v13_workspace_path_guard")
    for name in names:
        n = int(q1(cur, "SELECT count(*) FROM pg_proc WHERE proname=%s", (name,)))
        check(f"reread_name_absent_{name}", n == 0, n)
    n_pol = int(q1(cur, "SELECT count(*) FROM v13_policies WHERE name='global_concurrency'"))
    check("reread_policy_absent", n_pol == 0, n_pol)
    body = fn_src(cur, "public.v13_claim(text,integer)")
    check(
        "live_claim_body_unchanged",
        "v13_attempt_ok(kind, attempt_no)" in body
        and "op_seq IS NULL" in body
        and "v13_requires_worktree(tool_name)" in body
        and "status='ready'" in body,
        body[body.find("UPDATE"):body.find("UPDATE") + 400] if body else None)
    adv = fn_src(cur, "public.v13_advisory_class(text)")
    check(
        "advisory_class_function_unmodified",
        "spawn_budget" in adv and "13001" in adv
        and "13002" not in adv and "13003" not in adv,
        adv)
    life = q1(cur, """
        SELECT p.provolatile::text || ' ' || pg_get_function_result(p.oid)::text
          FROM pg_proc p
         WHERE p.oid = 'public.v13_goal_lifecycle(uuid)'::regprocedure
    """)
    check("lifecycle_stable_text", life == "s text", life)
    q1(cur, "SELECT v13_reject_bad_harness_request('llm', NULL, %s::jsonb)",
       (json.dumps(llm_req("reread")),))
    check("harness_accepts_llm_fixture", True)
    definer = q1(cur, """
        SELECT prosecdef FROM pg_proc
         WHERE oid = 'public.v13_tool_effect_open(uuid,uuid,text,text,text[],jsonb)'::regprocedure
    """)
    check("opener_invoker", definer is False, definer)
    open_src = fn_src(cur, "public.v13_tool_effect_open(uuid,uuid,text,text,text[],jsonb)")
    check("opener_source_still_has_not_single_tree", "not_single_tree" in open_src)
    sid = open_session(cur)
    prefix(cur, sid)
    eid = enqueue(cur, sid, "llm", llm_req("reread-ts"))
    cur.execute(
        "UPDATE effects SET created_at = now() - interval '1 hour', "
        "lease_until = now() + interval '1 minute' WHERE effect_id=%s",
        (eid,))
    ok = q1(cur, "SELECT created_at < now() AND lease_until IS NOT NULL FROM effects WHERE effect_id=%s",
            (eid,))
    check("reread_update_timestamps", bool(ok), ok)
    sid2 = open_session(cur)
    prefix(cur, sid2)
    q1(cur, "SELECT v13_goal_stop(%s, %s)", (sid2, "reread"))
    cur.execute("SAVEPOINT reread_enq")
    try:
        enqueue(cur, sid2, "llm", llm_req("after-stop"))
        cur.execute("RELEASE SAVEPOINT reread_enq")
        stop_fork = "enqueue_ok"
    except psycopg2.Error as exc:
        cur.execute("ROLLBACK TO SAVEPOINT reread_enq")
        stop_fork = "enqueue_raise:" + (exc.diag.message_primary or str(exc))
    check("reread_stop_fork_recorded", stop_fork in ("enqueue_ok",) or stop_fork.startswith("enqueue_raise"),
          stop_fork)
    print("[reread] stop_fork", stop_fork)
    return stop_fork


def test_policy(cur, server, before_hashes, after_hashes):
    check("hashes_unmodified", before_hashes == after_hashes)
    check("fingerprint_function_unmodified", before_hashes[2] == after_hashes[2])
    check("hint_unmodified", before_hashes[3] == after_hashes[3])
    check("advisory_hash_unmodified", before_hashes[10] == after_hashes[10])
    pol = as_obj(q1(
        cur,
        "SELECT value FROM v13_policies WHERE name='global_concurrency' AND version=1 AND active"))
    keys = q1(cur, "SELECT v13_json_keys(value) FROM v13_policies WHERE name='global_concurrency' AND version=1 AND active")
    check("policy_keys_closed", list(keys) == ["claimed_cap", "schema_version"], keys)
    check("cap_seed_is_2", pol["claimed_cap"] == 2 and pol["schema_version"] == 1, pol)
    n1 = int(q1(cur, "SELECT count(*) FROM v13_policies WHERE name='global_concurrency'"))
    run_psql(server, DB, SQL)
    n2 = int(q1(cur, "SELECT count(*) FROM v13_policies WHERE name='global_concurrency'"))
    pol2 = as_obj(q1(
        cur,
        "SELECT value FROM v13_policies WHERE name='global_concurrency' AND version=1 AND active"))
    check("policy_seed_idempotent", n1 == 1 and n2 == 1 and pol == pol2, (n1, n2, pol2))
    cur.execute(
        "UPDATE v13_policies SET active=false WHERE name='global_concurrency' AND version=1")
    cur.connection.commit()
    conn_msg = None
    try:
        run_psql(server, DB, SQL)
        conn_msg = "no-raise"
    except RuntimeError as exc:
        conn_msg = str(exc)
    cur.execute(
        "UPDATE v13_policies SET active=true WHERE name='global_concurrency' AND version=1")
    cur.connection.commit()
    check("policy_rejects_unequal", conn_msg and "v13: claim fair: policy" in conn_msg, conn_msg)
    spawn = as_obj(q1(
        cur, "SELECT value FROM v13_policies WHERE name='spawn_budget' AND active"))
    check(
        "spawn_budget_seed_unchanged",
        spawn == {"max_nonterminal": 8, "max_depth": 4, "max_fanout": 8},
        spawn)
    ver = q1(cur, "SELECT version FROM v13_policies WHERE name='should_run' AND active")
    check("should_run_version_still_3", ver == 3, ver)
    gates = as_obj(q1(cur, "SELECT value FROM v13_policies WHERE name='should_run' AND active"))
    ids = [g["id"] for g in gates["gates"]]
    check(
        "no_new_should_run_block",
        ids == ["human_pending", "unknown_wall", "unconsumed_cancel", "duty_cycle",
                "quota_window", "capabilities", "goal_stopped"]
        and "global_concurrency" not in fn_src(cur, "public.v13_should_run_gate(uuid)"),
        ids)
    quota = as_obj(q1(
        cur, "SELECT value FROM v13_policies WHERE name='quota_window' AND active"))
    check(
        "quota_policy_unchanged",
        quota["window_hours"] == 8760 and quota["allowed"] == 1000000
        and quota["slot_minutes"] == 0,
        quota)
    revoked = q1(cur, """
        SELECT NOT has_function_privilege('public',
          'public.v13_claim_fair(text,integer)', 'EXECUTE')
    """)
    check("claim_fair_revoked_public", bool(revoked), revoked)
    path_grant = q1(cur, """
        SELECT has_function_privilege('v13_route',
          'public.v13_path_conflict_locked(jsonb)', 'EXECUTE')
         AND has_function_privilege('v13_route',
          'public.v13_workspace_path_guard()', 'EXECUTE')
         AND NOT has_function_privilege('v13_route',
          'public.v13_claim_fair(text,integer)', 'EXECUTE')
    """)
    check("path_grant_route_only", bool(path_grant), path_grant)


def empty_pool_returns_null(cur):
    check("empty_pool_returns_null", claim_fair(cur) is None)


def fair_claim_happy(cur):
    sid = open_session(cur)
    prefix(cur, sid)
    before_ev = n_events(cur)
    before_fx = n_effects(cur)
    eid = enqueue(cur, sid, "llm", llm_req("happy"))
    row = q1(cur, "SELECT attempt_no FROM effects WHERE effect_id=%s", (eid,))
    fence0 = q1(cur, "SELECT fence FROM effects WHERE effect_id=%s", (eid,))
    ev1 = n_events(cur)
    got = claim_fair(cur, "worker-a", 5000)
    check("fair_claim_returns_six_keys", got is not None and sorted(got.keys()) == sorted(SIX), got)
    check("fair_claim_root", got["root_session_id"] == sid, got)
    check("fair_claim_bumps_attempt_once", got["attempt_no"] == row + 1, got)
    check("fair_claim_bumps_fence_once", got["fence"] == fence0 + 1, got)
    until = q1(cur, "SELECT lease_until FROM effects WHERE effect_id=%s", (eid,))
    inf = q1(cur, "SELECT lease_until = 'infinity' FROM effects WHERE effect_id=%s", (eid,))
    check("fair_claim_lease_finite", until is not None and inf is False, (until, inf))
    check("fair_claim_adds_no_event", n_events(cur) == ev1, (before_ev, ev1, n_events(cur)))
    check("effect_inserted_once", n_effects(cur) == before_fx + 1, n_effects(cur))
    fails(cur, "SELECT v13_claim_fair(%s, 60000)", ("v13_workspace_opener",),
          "v13: claim fair: canonical", "fair_claim_rejects_opener_owner")
    fails(cur, "SELECT v13_claim_fair(%s, 600001)", ("worker-a",),
          "v13: claim fair: canonical", "lease_above_600000_rejected")


def cap_and_live_hole(cur):
    sids = []
    eids = []
    for i in range(4):
        sid = open_session(cur)
        prefix(cur, sid, f"cap-{i}")
        sids.append(sid)
        eids.append(enqueue(cur, sid, "llm", llm_req(f"cap-{i}-{u()}")))
    ready_n = int(q1(cur, "SELECT count(*) FROM effects WHERE status='ready'"))
    check("enqueue_not_capped", ready_n >= 4, ready_n)
    snap0 = snapshot(cur)
    check("ready_does_not_consume_cap", snap0["claimed_count"] == 0, snap0)
    a = claim_fair(cur, "c1")
    b = claim_fair(cur, "c2")
    c = claim_fair(cur, "c3")
    check("cap_blocks_third_claim", a is not None and b is not None and c is None, (a, b, c))
    third_ready = int(q1(cur, "SELECT count(*) FROM effects WHERE status='ready'"))
    check("third_stays_ready", third_ready >= 1, third_ready)
    live = live_claim(cur, "hole")
    check("live_claim_still_claims_when_cap_full", live is not None, live)
    snap = snapshot(cur)
    check("cap_hole_claimed_count", snap["claimed_count"] >= 3, snap)


def infinity_claim_holds_cap(cur):
    sid = open_session(cur)
    prefix(cur, sid)
    plant(cur, sid)
    row = opener(cur, sid)
    eid = row["effect_id"]
    until = q1(cur, "SELECT lease_until FROM effects WHERE effect_id=%s", (eid,))
    st = effect_status(cur, eid)
    before = q1(cur, "SELECT status, lease_until, attempt_no, fence FROM effects WHERE effect_id=%s", (eid,))
    snap = snapshot(cur)
    got = claim_fair(cur)
    after = q1(cur, "SELECT status, lease_until, attempt_no, fence FROM effects WHERE effect_id=%s", (eid,))
    check(
        "infinity_claim_holds_cap",
        st == "claimed" and until is not None
        and q1(cur, "SELECT lease_until = 'infinity' FROM effects WHERE effect_id=%s", (eid,))
        and snap["claimed_count"] >= 1
        and before == after
        and got is None,
        (st, until, snap, got, before, after))


def eligible_matches_live_claim_on_shared_arms(cur):
    sid = open_session(cur)
    prefix(cur, sid)
    eid = enqueue(cur, sid, "llm", llm_req("elig-ok"))
    fair = bool(q1(cur, "SELECT v13_fair_eligible(%s::uuid)", (eid,)))
    arm = four_arm(cur, eid)
    check("eligible_positive_subset", (not fair) or arm, (fair, arm))
    term = open_session(cur)
    prefix(cur, term)
    teid = enqueue(cur, term, "llm", llm_req("elig-term"))
    cur.execute("UPDATE sessions SET status='completed' WHERE session_id=%s", (term,))
    fair_t = bool(q1(cur, "SELECT v13_fair_eligible(%s::uuid)", (teid,)))
    arm_t = four_arm(cur, teid)
    check(
        "eligible_matches_live_claim_on_shared_arms",
        arm_t is True and fair_t is False and ((not fair) or arm),
        (arm_t, fair_t, fair, arm))


def peer_idle_beats_older_sibling_backlog(cur):
    a = open_session(cur)
    prefix(cur, a)
    child = spawn_one(cur, a)
    claimed_eid = enqueue(cur, a, "llm", llm_req("peer-a-claimed"))
    got = claim_fair(cur, "peer-a")
    check("peer_claimed", got is not None and got["effect_id"] == claimed_eid, got)
    old = enqueue(cur, child, "llm", llm_req("peer-a-old"))
    b = open_session(cur)
    prefix(cur, b)
    young = enqueue(cur, b, "llm", llm_req("peer-b-young"))
    cur.execute(
        "UPDATE effects SET created_at = timestamptz '2000-01-01 00:00:00+00' WHERE effect_id=%s",
        (old,))
    cur.execute(
        "UPDATE effects SET created_at = timestamptz '2000-01-02 00:00:00+00' WHERE effect_id=%s",
        (young,))
    got2 = claim_fair(cur, "peer-b")
    check(
        "peer_idle_beats_older_sibling_backlog",
        got2 is not None and got2["effect_id"] == young and got2["root_session_id"] == b,
        got2)


def tie_oldest_created_at(cur):
    a = open_session(cur)
    prefix(cur, a)
    ea = enqueue(cur, a, "llm", llm_req("tie-old-a"))
    b = open_session(cur)
    prefix(cur, b)
    eb = enqueue(cur, b, "llm", llm_req("tie-old-b"))
    cur.execute(
        "UPDATE effects SET created_at = timestamptz '2001-01-01 00:00:00+00' WHERE effect_id=%s",
        (ea,))
    cur.execute(
        "UPDATE effects SET created_at = timestamptz '2001-01-01 00:00:01+00' WHERE effect_id=%s",
        (eb,))
    got = claim_fair(cur, "tie-old")
    check("tie_oldest_created_at", got is not None and got["effect_id"] == ea, got)


def tie_effect_id(cur):
    a = open_session(cur)
    prefix(cur, a)
    ea = enqueue(cur, a, "llm", llm_req("tie-id-a"))
    b = open_session(cur)
    prefix(cur, b)
    eb = enqueue(cur, b, "llm", llm_req("tie-id-b"))
    winner = ea if ea < eb else eb
    got = claim_fair(cur, "tie-id")
    check("tie_effect_id", got is not None and got["effect_id"] == winner, (got, ea, eb))


def stopped_root_not_fair_claimed(cur, stop_fork):
    sid = open_session(cur)
    prefix(cur, sid)
    q1(cur, "SELECT v13_goal_stop(%s, %s)", (sid, "d-stop"))
    if stop_fork != "enqueue_ok":
        cur.execute("SAVEPOINT stopped_enq")
        try:
            enqueue(cur, sid, "llm", llm_req("stopped-raise"))
            cur.execute("ROLLBACK TO SAVEPOINT stopped_enq")
            check("stopped_enqueue_raises", False, "enqueue succeeded after recorded raise")
        except psycopg2.Error as exc:
            cur.execute("ROLLBACK TO SAVEPOINT stopped_enq")
            check("stopped_enqueue_raises", True, exc.diag.message_primary)
        return
    eid = enqueue(cur, sid, "llm", llm_req("stopped-ok"))
    got = claim_fair(cur, "stopped")
    live = live_claim(cur, "stopped-live")
    check(
        "stopped_root_not_fair_claimed",
        got is None and live is not None and live["effect_id"] == eid
        and effect_status(cur, eid) == "claimed",
        (got, live))


def root_should_run_false_does_not_block_other_ready(cur):
    root = open_session(cur)
    prefix(cur, root)
    child = spawn_one(cur, root)
    hid = enqueue(cur, root, "human", {"reason": "ask"})
    lid = enqueue(cur, child, "llm", llm_req("sr-child"))
    cur.execute(
        "UPDATE effects SET created_at = timestamptz '2002-01-01 00:00:00+00' WHERE effect_id=%s",
        (lid,))
    cur.execute(
        "UPDATE effects SET created_at = timestamptz '2002-01-02 00:00:00+00' WHERE effect_id=%s",
        (hid,))
    sr = q1(cur, "SELECT v13_should_run(%s::uuid)", (root,))
    got = claim_fair(cur, "sr")
    hst = effect_status(cur, hid)
    check(
        "root_should_run_false_does_not_block_other_ready",
        sr is False and got is not None and got["effect_id"] == lid and hst == "ready",
        (sr, got, hst))


def worktree_without_latch_skipped(cur):
    sid = open_session(cur)
    prefix(cur, sid)
    rev = int(q1(cur, "SELECT (v13_probe(%s)->>'tools_revision')::bigint", (sid,)))
    req = {
        "tool": "worktree_merge",
        "params": {"binding_artifact_id": u()},
        "handler": "worker:worktree_merge",
        "tools_revision": rev,
    }
    eid = enqueue(cur, sid, "tool", req, "worktree_merge")
    got = claim_fair(cur, "wt")
    check(
        "worktree_without_latch_skipped",
        got is None and effect_status(cur, eid) == "ready"
        and four_arm(cur, eid) is False,
        (got, effect_status(cur, eid)))


def attempt_not_ok_skipped(cur):
    sid = open_session(cur)
    prefix(cur, sid)
    eid = enqueue(cur, sid, "llm", llm_req("att"))
    cur.execute("UPDATE effects SET attempt_no = 3 WHERE effect_id=%s", (eid,))
    ok = q1(cur, "SELECT v13_attempt_ok('llm', attempt_no) FROM effects WHERE effect_id=%s", (eid,))
    got = claim_fair(cur, "att")
    check(
        "attempt_not_ok_skipped",
        ok is False and got is None and effect_status(cur, eid) == "ready",
        (ok, got))


def unknown_does_not_consume_cap(cur):
    a = open_session(cur)
    prefix(cur, a)
    ea = enqueue(cur, a, "llm", llm_req("unk-a"))
    b = open_session(cur)
    prefix(cur, b)
    eb = enqueue(cur, b, "llm", llm_req("unk-b"))
    got = claim_fair(cur, "unk")
    check("unk_claimed", got is not None, got)
    claimed_id = got["effect_id"]
    other = eb if claimed_id == ea else ea
    cur.execute(
        "UPDATE effects SET lease_until = now() - interval '1 second' WHERE effect_id=%s",
        (claimed_id,))
    q1(cur, "SELECT v13_requeue_stale()")
    st = effect_status(cur, claimed_id)
    snap = snapshot(cur)
    got2 = claim_fair(cur, "unk2")
    wall = q1(cur, "SELECT status FROM sessions WHERE session_id=%s", (a if claimed_id == ea else b,))
    check(
        "unknown_does_not_consume_cap",
        st == "unknown" and snap["claimed_count"] == 0
        and got2 is not None and got2["effect_id"] == other,
        (st, snap, got2, wall, claimed_id, other))


def requeue_wall_unchanged_frees_cap(cur):
    a = open_session(cur)
    prefix(cur, a)
    ea = enqueue(cur, a, "llm", llm_req("wall-a"))
    b = open_session(cur)
    prefix(cur, b)
    eb = enqueue(cur, b, "llm", llm_req("wall-b"))
    got = claim_fair(cur, "wall")
    check("wall_claimed", got is not None, got)
    claimed_id = got["effect_id"]
    other = eb if claimed_id == ea else ea
    owner = a if claimed_id == ea else b
    cur.execute(
        "UPDATE effects SET lease_until = now() - interval '1 second' WHERE effect_id=%s",
        (claimed_id,))
    q1(cur, "SELECT v13_requeue_stale()")
    st = effect_status(cur, claimed_id)
    sess = q1(cur, "SELECT status FROM sessions WHERE session_id=%s", (owner,))
    snap = snapshot(cur)
    got2 = claim_fair(cur, "wall2")
    sess2 = q1(cur, "SELECT status FROM sessions WHERE session_id=%s", (owner,))
    check(
        "requeue_wall_unchanged_frees_cap",
        st == "unknown" and sess == "blocked_unknown" and sess2 == "blocked_unknown"
        and snap["claimed_count"] == 0
        and got2 is not None and got2["effect_id"] == other,
        (st, sess, sess2, snap, got2))


def snapshot_checks(cur):
    ev = n_events(cur)
    fx = n_effects(cur)
    se = n_sessions(cur)
    s1 = snapshot(cur)
    s2 = snapshot(cur)
    check("snapshot_zero_write", n_events(cur) == ev and n_effects(cur) == fx and n_sessions(cur) == se,
          (ev, fx, se))
    check("snapshot_two_calls_identical", s1 == s2, (s1, s2))
    check(
        "snapshot_keys",
        sorted(s1.keys()) == sorted([
            "schema_version", "claimed_cap", "claimed_count", "omitted_count",
            "omitted_complete", "unresolved_count", "roots"]),
        s1.keys())
    a = open_session(cur)
    prefix(cur, a)
    b = open_session(cur)
    prefix(cur, b)
    snap = snapshot(cur)
    roots = [r["root_session_id"] for r in snap["roots"]]
    ordered = sorted(roots)
    check("snapshot_orders_by_root_id", roots == ordered, roots)
    ids = []
    for i in range(33):
        ids.append(open_session(cur))
    snap33 = snapshot(cur)
    check(
        "snapshot_cap_33",
        len(snap33["roots"]) == 32 and snap33["omitted_count"] == 1
        and snap33["omitted_complete"] is False
        and snap33["claimed_count"] == claimed_count(cur),
        (len(snap33["roots"]), snap33["omitted_count"], snap33["claimed_count"]))
    r1 = open_session(cur)
    prefix(cur, r1)
    spawn_one(cur, r1, "occ-1")
    r2 = open_session(cur)
    prefix(cur, r2)
    spawn_one(cur, r2, "occ-2")
    n1 = int(q1(cur, "SELECT v13_spawn_occupancy(%s::uuid)", (r1,)))
    n2 = int(q1(cur, "SELECT v13_spawn_occupancy(%s::uuid)", (r2,)))
    check("occupancy_counts_one_root", n1 == 1 and n2 == 1, (n1, n2))


def path_distinct_and_overlap(cur):
    a = open_session(cur)
    prefix(cur, a)
    b = open_session(cur)
    prefix(cur, b)
    enqueue(cur, a, "tool", {"workspace_root": WS, "paths": ["a/file.txt"], "t": "d1"}, "ls")
    enqueue(cur, b, "tool", {"workspace_root": WS, "paths": ["b/file.txt"], "t": "d2"}, "ls")
    n = int(q1(cur, "SELECT count(*) FROM effects WHERE kind='tool' AND request ? 'workspace_root'"))
    check("path_distinct_ab_not_busy", n == 2, n)
    c = open_session(cur)
    prefix(cur, c)
    d = open_session(cur)
    prefix(cur, d)
    enqueue(cur, c, "tool", {"workspace_root": WS, "paths": ["sub/file.txt"], "t": "o1"}, "ls")
    fails(
        cur,
        "SELECT v13_enqueue_effect(%s, 'tool', %s::jsonb, %s)",
        (d, json.dumps({"workspace_root": "/tmp/ws/sub", "paths": ["file.txt"], "t": "o2"}), "ls"),
        "v13: workspace open: path_busy",
        "overlapping_root_strings_are_busy")


def two_roots_opener_still_not_single_tree(cur):
    a = open_session(cur)
    prefix(cur, a)
    b = open_session(cur)
    prefix(cur, b)
    n = int(q1(cur, "SELECT count(*) FROM sessions WHERE parent_session_id IS NULL"))
    fails(
        cur,
        "SELECT v13_tool_effect_open(%s::uuid, %s::uuid, %s, %s, %s::text[], %s::jsonb)",
        (None, a, "workspace_edit", WS, [WS, "/tmp/ws/sub"],
         json.dumps(ws_req("ls", ["dir"], {"path": "dir"}))),
        "v13: workspace open: not_single_tree",
        "two_roots_opener_still_not_single_tree")
    check("two_roots_present", n >= 2, n)


def isolation_not_read_committed_rejected(conn):
    conn.rollback()
    cur = conn.cursor()
    cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
    try:
        cur.execute("SELECT v13_claim_fair(%s, 60000)", ("iso-w",))
        conn.rollback()
        check("isolation_not_read_committed_rejected", False, "expected raise")
    except psycopg2.Error as exc:
        msg = exc.diag.message_primary or str(exc)
        conn.rollback()
        check("isolation_not_read_committed_rejected", "v13: claim fair: canonical" in msg, msg)


def path_guard_rejects_non_read_committed(server):
    conn = connect(server)
    try:
        cur = conn.cursor()
        sid = open_session(cur)
        prefix(cur, sid)
        conn.commit()
    finally:
        conn.close()
    conn = connect(server)
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        try:
            cur.execute(
                "SELECT v13_enqueue_effect(%s, 'tool', %s::jsonb, %s)",
                (sid, json.dumps({"workspace_root": WS, "paths": ["x.txt"], "t": "rr"}), "ls"))
            conn.rollback()
            check("path_guard_rejects_non_read_committed", False, "expected raise")
        except psycopg2.Error as exc:
            msg = exc.diag.message_primary or str(exc)
            conn.rollback()
            check(
                "path_guard_rejects_non_read_committed",
                "v13: workspace open: canonical" in msg, msg)
    finally:
        conn.close()


def path_guard_execute_reaches_recheck(server):
    setup = connect(server)
    try:
        cur = setup.cursor()
        sid = open_session(cur)
        prefix(cur, sid)
        setup.commit()
    finally:
        setup.close()
    conn = psycopg2.connect(server.get_uri(DB))
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SET ROLE v13_route")
        cur.execute("SET search_path = pg_catalog, public")
        who = q1(cur, "SELECT current_user")
        conn.autocommit = False
        cur.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        eid = q1(
            cur,
            "SELECT v13_enqueue_effect(%s, 'tool', %s::jsonb, %s)",
            (sid, json.dumps({
                "workspace_root": "/tmp/ws-role",
                "paths": ["a.txt"],
                "t": "role",
            }), "ls"))
        conn.commit()
        check(
            "path_guard_execute_reaches_recheck",
            eid is not None and who == "v13_route",
            (eid, who))
    except psycopg2.Error as exc:
        msg = exc.diag.message_primary or str(exc)
        code = exc.pgcode
        try:
            conn.rollback()
        except Exception:
            pass
        check(
            "path_guard_execute_reaches_recheck",
            code != "42501" and "path_busy" in msg,
            (code, msg))
        if code == "42501":
            raise
    finally:
        try:
            conn.autocommit = True
            conn.cursor().execute("RESET ROLE")
        except Exception:
            pass
        conn.close()


def nowait_does_not_wait(server):
    conn = connect(server)
    try:
        cur = conn.cursor()
        sid = open_session(cur)
        prefix(cur, sid)
        eid = enqueue(cur, sid, "llm", llm_req("nowait"))
        conn.commit()
    finally:
        conn.close()
    hold = connect(server)
    try:
        hc = hold.cursor()
        hc.execute("SELECT 1 FROM effects WHERE effect_id=%s FOR UPDATE", (eid,))
        hc.fetchone()
        box = {}

        def worker():
            c = psycopg2.connect(server.get_uri(DB))
            try:
                c.autocommit = True
                c.cursor().execute("SET statement_timeout = '4000ms'")
                c.autocommit = False
                t0 = time.monotonic()
                cur2 = c.cursor()
                cur2.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                cur2.execute("SELECT v13_claim_fair(%s, 60000)", ("nowait-w",))
                box["row"] = cur2.fetchone()[0]
                box["dt"] = time.monotonic() - t0
                c.commit()
            except Exception as exc:
                box["err"] = exc
                box["dt"] = time.monotonic() - t0
                try:
                    c.rollback()
                except Exception:
                    pass
            finally:
                c.close()

        th = threading.Thread(target=worker)
        th.start()
        th.join(6)
        check("nowait_thread_done", not th.is_alive() and "dt" in box, box)
        check(
            "nowait_does_not_wait",
            box.get("row") is None and box.get("err") is None and box["dt"] < 2.0,
            box)
        st = q1(hold.cursor(), "SELECT status FROM effects WHERE effect_id=%s", (eid,))
        check("nowait_row_unclaimed", st == "ready", st)
    finally:
        hold.rollback()
        hold.close()


def two_fair_claimers_respect_cap(server):
    conn = connect(server)
    try:
        cur = conn.cursor()
        eids = []
        for i in range(3):
            sid = open_session(cur)
            prefix(cur, sid, f"two-{i}")
            eids.append(enqueue(cur, sid, "llm", llm_req(f"two-{i}-{u()}")))
        conn.commit()
    finally:
        conn.close()
    boxes = [{}, {}]
    barrier = threading.Barrier(2)

    def worker(i):
        c = connect(server)
        try:
            barrier.wait(5)
            cur2 = c.cursor()
            cur2.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            cur2.execute("SELECT v13_claim_fair(%s, 60000)", (f"two-w-{i}",))
            boxes[i]["row"] = as_obj(cur2.fetchone()[0])
            c.commit()
        except Exception as exc:
            boxes[i]["err"] = exc
            c.rollback()
        finally:
            c.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(10)
    rows = [b.get("row") for b in boxes]
    ok = sum(1 for r in rows if r is not None)
    check("two_fair_claimers_respect_cap", ok == 2 and all("err" not in b for b in boxes), boxes)
    conn = connect(server)
    try:
        cur = conn.cursor()
        third = claim_fair(cur, "two-third")
        check("two_claimers_third_null", third is None, third)
        conn.commit()
    finally:
        conn.close()


def path_busy_two_roots_two_connections(server):
    conn = connect(server)
    try:
        cur = conn.cursor()
        a = open_session(cur)
        prefix(cur, a)
        b = open_session(cur)
        prefix(cur, b)
        conn.commit()
    finally:
        conn.close()
    hold = connect(server)
    try:
        hc = hold.cursor()
        hc.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        hc.execute(
            "SELECT v13_enqueue_effect(%s, 'tool', %s::jsonb, %s)",
            (a, json.dumps({"workspace_root": WS, "paths": ["sub/file.txt"], "t": "busy-a"}), "ls"))
        hc.fetchone()
        box = {}

        def worker():
            c = connect(server)
            try:
                cur2 = c.cursor()
                cur2.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                box["pid"] = q1(cur2, "SELECT pg_backend_pid()")
                cur2.execute(
                    "SELECT v13_path_conflict_locked(%s::jsonb)",
                    (json.dumps({"workspace_root": "/tmp/ws/sub", "paths": ["file.txt"]}),))
                box["ok"] = True
                c.commit()
            except Exception as exc:
                box["err"] = exc.diag.message_primary if hasattr(exc, "diag") else str(exc)
                c.rollback()
            finally:
                c.close()

        th = threading.Thread(target=worker)
        th.start()
        deadline = time.monotonic() + 5
        while "pid" not in box and time.monotonic() < deadline:
            time.sleep(0.05)
        waited = wait_ungranted(server, box.get("pid"), 13003, timeout=5.0) if box.get("pid") else False
        hold.commit()
        th.join(6)
        check("path_busy_waited", waited, box)
        check(
            "path_busy_two_roots_two_connections",
            box.get("ok") is not True
            and box.get("err") is not None
            and "v13: workspace open: path_busy" in str(box.get("err")),
            box)
    finally:
        try:
            hold.rollback()
        except Exception:
            pass
        hold.close()


def types_unchanged(cur, before_types):
    types = q1(cur, "SELECT array_agg(DISTINCT type ORDER BY type) FROM events")
    check("no_new_event_type_runtime", types == before_types or before_types is None, (before_types, types))


def main() -> int:
    print("[db]", DB)
    test_stage_bytes()
    test_static_source()
    if setup_db() != 0:
        return 1
    server = get_server()
    conn = connect(server)
    stop_fork = "enqueue_ok"
    try:
        cur = conn.cursor()
        stop_fork = test_reread(cur)
        conn.rollback()
        cur = conn.cursor()
        before = hashes(cur)
        conn.commit()
        run_psql(server, DB, SQL)
        after = hashes(cur)
        test_policy(cur, server, before, after)
        types0 = q1(cur, "SELECT array_agg(DISTINCT type ORDER BY type) FROM events")
        isolated(cur, lambda: empty_pool_returns_null(cur))
        isolated(cur, lambda: fair_claim_happy(cur))
        isolated(cur, lambda: cap_and_live_hole(cur))
        isolated(cur, lambda: infinity_claim_holds_cap(cur))
        isolated(cur, lambda: eligible_matches_live_claim_on_shared_arms(cur))
        isolated(cur, lambda: peer_idle_beats_older_sibling_backlog(cur))
        isolated(cur, lambda: tie_oldest_created_at(cur))
        isolated(cur, lambda: tie_effect_id(cur))
        isolated(cur, lambda: stopped_root_not_fair_claimed(cur, stop_fork))
        isolated(cur, lambda: root_should_run_false_does_not_block_other_ready(cur))
        isolated(cur, lambda: worktree_without_latch_skipped(cur))
        isolated(cur, lambda: attempt_not_ok_skipped(cur))
        isolated(cur, lambda: unknown_does_not_consume_cap(cur))
        isolated(cur, lambda: requeue_wall_unchanged_frees_cap(cur))
        isolated(cur, lambda: snapshot_checks(cur))
        isolated(cur, lambda: path_distinct_and_overlap(cur))
        isolated(cur, lambda: two_roots_opener_still_not_single_tree(cur))
        isolation_not_read_committed_rejected(conn)
        types_unchanged(conn.cursor(), types0)
        conn.commit()
        path_guard_rejects_non_read_committed(server)
        path_guard_execute_reaches_recheck(server)
        drain_pool(server)
        nowait_does_not_wait(server)
        drain_pool(server)
        two_fair_claimers_respect_cap(server)
        path_busy_two_roots_two_connections(server)
    finally:
        try:
            conn.close()
        except Exception:
            pass
        if setup_mod.CREATED:
            run_psql(server, "postgres", 'DROP DATABASE "%s" WITH (FORCE);' % DB)
            setup_mod.CREATED = False
            print("[dropped]", DB)
    print("[ok] %s checks" % N)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("[FAIL]", exc)
        if setup_mod.CREATED:
            try:
                run_psql(get_server(), "postgres", 'DROP DATABASE "%s" WITH (FORCE);' % DB)
                print("[dropped]", DB)
            except Exception as drop_exc:
                print("[cleanup-fail]", drop_exc)
        raise SystemExit(1)
