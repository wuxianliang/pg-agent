"""Phase D fair_driver gate.

Run: UV_FROZEN=1 uv run python v13/fair_driver/test_fair_driver.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg2
from psycopg2.extensions import TRANSACTION_STATUS_IDLE, TRANSACTION_STATUS_INTRANS

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.fair_driver.driver import claim_one
from v13.fair_driver.setup_db import DB, main as setup_db
import v13.fair_driver.setup_db as setup_mod
from v13.load import run_psql

N = 0
DRV = (ROOT / "driver.py").read_text()
SRC = (ROOT / "test_fair_driver.py").read_text()
README = (ROOT / "README.md").read_text()
SIX = ("attempt_no", "effect_id", "fence", "kind", "request", "root_session_id")
README_NEEDLES = (
    "加速夹具不是多日生产运行。真实多日运营仍未授权。",
    "v13_quota_eligible 使用 transaction_timestamp()，不可注入。本 soak 不证明配额窗口。",
    "fair_claim 在政策不存在时插入 claimed_cap=2。这个种子不是产品并发能力证明，也不是 spawn_budget 的 8/4/8。已有不相等行则装载 RAISE，不覆盖。",
    "公平不写入事件。v13_goal_fingerprint 不改。",
    "活体 v13_claim 不看 global_concurrency。帽只约束 v13_claim_fair。",
    "not_single_tree 仍在打开者里。跨根 path_busy 不经过打开者。",
    "PC-4 保持关闭。",
    "C4 多 lane 不在本期实现。",
    "有限租约过期后，席位只有在外部调用未改过的 v13_requeue_stale 时才释放；fair_driver 不是这个调用者。",
    "本驱动器不是无人值守监督进程，也不授权离开生产终端。",
)
STAGE_PATHS = [
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
    "v13/goal_supervise", "v13/goal_supervisor", "v13/fair_claim",
]


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


def strip_hash_comments(text):
    out = []
    for line in text.splitlines():
        if "#" in line:
            in_s = None
            buf = []
            i = 0
            while i < len(line):
                ch = line[i]
                if in_s:
                    buf.append(ch)
                    if ch == in_s and line[i - 1] != "\\":
                        in_s = None
                    i += 1
                    continue
                if ch in ("'", '"'):
                    in_s = ch
                    buf.append(ch)
                    i += 1
                    continue
                if ch == "#":
                    break
                buf.append(ch)
                i += 1
            out.append("".join(buf))
        else:
            out.append(line)
    return "\n".join(out)


class DeadlockErr(Exception):
    pgcode = "40P01"


class FakeConn:
    def __init__(self, fail_times):
        self.autocommit = True
        self.fail_times = fail_times
        self.calls = 0
        self.sql = []
        self.commits = 0
        self.rollbacks = 0
        self._status = TRANSACTION_STATUS_IDLE
        self._row = None

    def get_transaction_status(self):
        return self._status

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        self.sql.append(sql)
        if sql.startswith("SET TRANSACTION"):
            self._status = TRANSACTION_STATUS_INTRANS
            return
        if "v13_claim_fair" in sql:
            self.calls += 1
            if self.calls <= self.fail_times:
                self._status = TRANSACTION_STATUS_INTRANS
                raise DeadlockErr("deadlock detected")
            self._row = (None,)
            return
        raise AssertionError("unexpected sql: %s" % sql)

    def fetchone(self):
        return self._row

    def commit(self):
        self.commits += 1
        self._status = TRANSACTION_STATUS_IDLE

    def rollback(self):
        self.rollbacks += 1
        self._status = TRANSACTION_STATUS_IDLE


class Wrap:
    def __init__(self, conn, fail_times=0):
        self._conn = conn
        self.sql = []
        self.calls = 0
        self.fail_times = fail_times

    def get_transaction_status(self):
        return self._conn.get_transaction_status()

    @property
    def autocommit(self):
        return self._conn.autocommit

    @autocommit.setter
    def autocommit(self, value):
        self._conn.autocommit = value

    def cursor(self):
        return WrapCursor(self)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()


class WrapCursor:
    def __init__(self, wrap):
        self._wrap = wrap
        self._cur = wrap._conn.cursor()

    def execute(self, sql, params=None):
        self._wrap.sql.append(sql)
        if "v13_claim_fair" in sql:
            self._wrap.calls += 1
            if self._wrap.calls <= self._wrap.fail_times:
                raise DeadlockErr("deadlock detected")
        return self._cur.execute(sql, params)

    def fetchone(self):
        return self._cur.fetchone()


def test_stage_bytes():
    diff = subprocess.check_output(["git", "diff", "HEAD", "--", *STAGE_PATHS], cwd=AGENT_ROOT)
    load = subprocess.check_output(["git", "diff", "HEAD", "--", "v13/load.py"], cwd=AGENT_ROOT)
    check("stage_bytes", diff == b"" and load == b"", (len(diff), len(load)))


def test_static():
    body = strip_hash_comments(DRV)
    names = set(re.findall(r"\bv13_[A-Za-z0-9_]+\b", body))
    banned_insert = tuple("INSERT INTO " + t for t in ("effects", "events", "sessions", "artifacts"))
    missing = [s for s in README_NEEDLES if s not in README]
    check("soak_not_multiday", missing == [], missing)
    check(
        "static_check",
        names <= {"v13_claim_fair"}
        and "v13_claim_fair" in names
        and "INSERT INTO " + "effects" not in body
        and "INSERT INTO " + "events" not in body
        and "INSERT INTO " + "sessions" not in body
        and "INSERT INTO " + "artifacts" not in body
        and "UPDATE " not in body
        and "turn/" + "material_spent" not in body
        and "pg_" + "cron" not in body
        and "pg_" + "sleep" not in body
        and "api_key" not in body.lower()
        and list(ROOT.glob("*.sql")) == [],
        names)
    check(
        "no_insert_in_driver_or_test",
        all(b not in DRV and b not in SRC for b in banned_insert),
        None)
    check("driver_does_not_update", "UPDATE " not in DRV)
    check(
        "no_material_spent",
        "turn/" + "material_spent" not in DRV
        and "Fake" + "LLM" not in DRV and "Fake" + "Tool" not in DRV)
    check(
        "no_real_provider",
        "urllib" not in DRV and "httpx" not in DRV and "openai" not in DRV.lower()
        and "socket" not in DRV
        and os.environ.get("V13_REAL_PROVIDER_AUTHORIZATION") != "1")
    check(
        "no_sleep_no_cron",
        "pg_" + "sleep" not in DRV and "pg_" + "cron" not in DRV
        and "time." + "sleep" not in DRV and "time." + "sleep" not in SRC)
    check(
        "no_fake_llm_required",
        "Fake" + "LLM" not in DRV and "Fake" + "LLM" not in SRC
        and "Fake" + "Tool" not in DRV and "Fake" + "Tool" not in SRC)
    check("attention_not_referenced", "attention_rank" not in DRV and "v13_attention" not in DRV)
    check("hint_not_called", "v13_scheduler_hint" not in DRV)
    check(
        "live_claim_not_called_by_driver",
        re.search(r"\bv13_claim\b", body) is None)
    sup = subprocess.check_output(
        ["git", "diff", "HEAD", "--", "v13/goal_supervisor"], cwd=AGENT_ROOT)
    check(
        "supervisor_allowlist_not_edited",
        (AGENT_ROOT / "v13" / "goal_supervisor").is_dir() and sup == b"",
        len(sup))
    blob_drv_readme = DRV + README
    check(
        "c4_multilane_absent",
        "multi" + "lane" not in DRV
        and "lane_id" not in DRV
        and "C4 多 lane 不在本期实现。" in README)
    check(
        "pc4_not_reopened",
        "PC-4 保持关闭。" in README
        and "should_run version " + "4" not in blob_drv_readme)
    soak_blob = SRC[SRC.find("def soak_run"):SRC.find("\ndef test_runtime")]
    static_def = SRC[SRC.find("def test_static"):SRC.find("\ndef test_deadlock_unit")]
    needle = "UPDATE effects SET " + "created_at"
    created = [m.group(0) for m in re.finditer(r"UPDATE effects SET \w+", SRC)]
    rest = SRC.count(needle) - static_def.count(needle)
    check(
        "update_effects_whitelist",
        set(part.split()[-1] for part in created) <= {"created_at"}
        and rest >= 1 and rest == soak_blob.count(needle),
        (created, rest, soak_blob.count(needle)))


def test_deadlock_unit():
    once = FakeConn(1)
    got = claim_one(once, "inj-1", 60000)
    check(
        "deadlock_retries_once",
        got is None and once.calls == 2 and once.commits == 1 and once.rollbacks == 1,
        (once.calls, once.commits, once.rollbacks, got))
    twice = FakeConn(2)
    raised = None
    try:
        claim_one(twice, "inj-2", 60000)
    except DeadlockErr as exc:
        raised = exc
    check(
        "deadlock_retries_at_most_2",
        raised is not None and twice.calls == 2 and twice.commits == 0 and twice.rollbacks == 2,
        (twice.calls, twice.commits, twice.rollbacks, raised))


def open_session(cur, spec=None):
    return str(q1(cur, "SELECT v13_open_session(%s::jsonb)", (json.dumps(spec or {}),)))


def prefix(cur, sid, text="hello fair"):
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": text})))


def enqueue(cur, sid, kind, request):
    return str(q1(
        cur, "SELECT v13_enqueue_effect(%s, %s, %s::jsonb)",
        (sid, kind, json.dumps(request))))


def llm_req(tag):
    return {"route": {"action": "llm", "reason": tag}}


def n_events(cur, typ=None):
    if typ:
        return int(q1(cur, "SELECT count(*) FROM events WHERE type=%s", (typ,)))
    return int(q1(cur, "SELECT count(*) FROM events"))


def n_effects(cur):
    return int(q1(cur, "SELECT count(*) FROM effects"))


def n_sessions(cur):
    return int(q1(cur, "SELECT count(*) FROM sessions"))


def claimed_count(cur):
    return int(q1(cur, "SELECT count(*) FROM effects WHERE status='claimed'"))


def quota_value(cur):
    return q1(cur, "SELECT value FROM v13_policies WHERE name='quota_window' AND active")


def complete_failed(cur, row):
    return q1(
        cur, "SELECT v13_complete(%s::uuid, %s, %s, 'failed', NULL)",
        (row["effect_id"], row["attempt_no"], row["fence"]))


def soak_run(conn, obs):
    oc = obs.cursor()
    ev0 = n_events(oc)
    fx0 = n_effects(oc)
    se0 = n_sessions(oc)
    done0 = n_events(oc, "effect_done")
    quota0 = as_obj(quota_value(oc))
    cur = conn.cursor()
    roots = []
    eids = []
    for i in range(4):
        sid = open_session(cur)
        prefix(cur, sid, "soak-%s" % i)
        eid = enqueue(cur, sid, "llm", llm_req("soak-%s-%s" % (i, u())))
        roots.append(sid)
        eids.append(eid)
    stamps = [
        "2000-01-01 00:00:00+00",
        "2000-01-02 00:00:00+00",
        "2000-01-03 00:00:00+00",
        "2000-01-04 00:00:00+00",
    ]
    for eid, ts in zip(eids, stamps):
        cur.execute(
            "UPDATE effects SET created_at = timestamptz %s WHERE effect_id=%s",
            (ts, eid))
    conn.commit()
    oc = obs.cursor()
    ev_fix = n_events(oc)
    seq = []
    caps = []
    event_deltas = []

    def tick(worker):
        if conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
            conn.commit()
        oc2 = obs.cursor()
        ev_b = n_events(oc2)
        row = claim_one(conn, worker, 60000)
        oc3 = obs.cursor()
        ev_a = n_events(oc3)
        cap = claimed_count(oc3)
        event_deltas.append(ev_a - ev_b)
        caps.append(cap)
        if row is not None:
            seq.append(row)
        return row

    r1 = tick("soak-1")
    r2 = tick("soak-2")
    n3 = tick("soak-3")
    oc = obs.cursor()
    check(
        "soak_ticks_1_2",
        r1 is not None and r2 is not None
        and r1["root_session_id"] == roots[0]
        and r2["root_session_id"] == roots[1]
        and sorted(r1.keys()) == sorted(SIX)
        and claimed_count(oc) == 2,
        (r1, r2))
    check("tick3_null", n3 is None, n3)
    ready34 = int(q1(
        oc,
        "SELECT count(*) FROM effects WHERE effect_id IN (%s, %s) AND status='ready'",
        (eids[2], eids[3])))
    check("tick3_ready_stays", ready34 == 2, ready34)
    complete_failed(conn.cursor(), r1)
    conn.commit()
    r3 = tick("soak-4")
    check("tick4_r3", r3 is not None and r3["root_session_id"] == roots[2], r3)
    n5 = tick("soak-5")
    check("tick5_null", n5 is None, n5)
    complete_failed(conn.cursor(), r2)
    conn.commit()
    r4 = tick("soak-6")
    check("tick6_r4", r4 is not None and r4["root_session_id"] == roots[3], r4)
    complete_failed(conn.cursor(), r3)
    complete_failed(conn.cursor(), r4)
    conn.commit()
    cur = conn.cursor()
    new_eid = enqueue(cur, roots[0], "llm", llm_req("soak-r1-again-%s" % u()))
    cur.execute(
        "UPDATE effects SET created_at = timestamptz %s WHERE effect_id=%s",
        ("2000-01-05 00:00:00+00", new_eid))
    conn.commit()
    r1b = tick("soak-7")
    check(
        "tick7_r1_new",
        r1b is not None and r1b["root_session_id"] == roots[0]
        and r1b["effect_id"] == new_eid,
        r1b)
    n8 = tick("soak-8")
    check("tick8_null", n8 is None, n8)
    got_roots = [row["root_session_id"] for row in seq]
    check(
        "soak_sequence_r1_r2_r3_r4_r1",
        got_roots == [roots[0], roots[1], roots[2], roots[3], roots[0]],
        got_roots)
    first_four = got_roots[:4]
    check(
        "no_second_claim_before_each_root_once",
        sorted(first_four) == sorted(roots) and len(set(first_four)) == 4,
        first_four)
    check("soak_cap_never_exceeded", all(c <= 2 for c in caps), caps)
    check("soak_claim_adds_no_event", all(d == 0 for d in event_deltas), event_deltas)
    oc = obs.cursor()
    se = n_sessions(oc)
    fx = n_effects(oc)
    ev = n_events(oc)
    done = n_events(oc, "effect_done") - done0
    check(
        "soak_row_counts",
        se == se0 + 4 and fx == fx0 + 5
        and ev == ev0 + (ev_fix - ev0) + done and done == 4,
        (se0, se, fx0, fx, ev0, ev_fix, ev, done))
    quota1 = as_obj(quota_value(oc))
    check("soak_quota_policy_unchanged", quota0 == quota1, (quota0, quota1))
    spent = n_events(oc, "turn/" + "material_spent")
    check("no_material_spent_runtime", spent == 0, spent)


def test_runtime(server):
    conn = connect(server)
    obs = psycopg2.connect(server.get_uri(DB))
    obs.autocommit = True
    try:
        wrap_empty = Wrap(conn)
        got = claim_one(wrap_empty, "empty-w", 60000)
        check(
            "empty_pool_null_once",
            got is None and wrap_empty.calls == 1,
            wrap_empty.calls)
        check("null_does_not_retry", wrap_empty.calls == 1, wrap_empty.calls)
        check(
            "claim_one_read_committed",
            wrap_empty.sql and wrap_empty.sql[0] == "SET TRANSACTION ISOLATION LEVEL READ COMMITTED",
            wrap_empty.sql)
        cur = conn.cursor()
        cur.execute("SELECT 1")
        raised = None
        wrap_busy = Wrap(conn)
        try:
            claim_one(wrap_busy, "busy-w", 60000)
        except RuntimeError as exc:
            raised = str(exc)
        check(
            "already_in_transaction_rejected",
            raised is not None and "v13: claim fair: canonical" in raised
            and wrap_busy.calls == 0,
            (raised, wrap_busy.calls))
        conn.rollback()
        cur = conn.cursor()
        ver = q1(
            cur,
            "SELECT version FROM v13_policies WHERE name='should_run' AND active "
            "ORDER BY version DESC LIMIT 1")
        check("pc4_should_run_still_3", ver == 3, ver)
        conn.commit()
        soak_run(conn, obs)
    finally:
        try:
            obs.close()
        except Exception:
            pass
        conn.close()


def main() -> int:
    print("[db]", DB)
    test_stage_bytes()
    test_static()
    test_deadlock_unit()
    if setup_db() != 0:
        return 1
    server = get_server()
    try:
        test_runtime(server)
    finally:
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
