"""Phase A plan_arm gate.

Run: UV_FROZEN=1 uv run python v13/plan_arm/test_plan_arm.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.load import run_psql
from v13.plan_arm.setup_db import DB, main as setup_db
import v13.plan_arm.setup_db as setup_mod

N = 0
SQL = (ROOT / "v13_plan_arm.sql").read_text()
FINISH = {"result_kind": "finish", "delivery_kind": "LOUD-BUT-BLIND"}
PROGRESS = {"result_kind": "progress"}
WAIT = {"result_kind": "wait", "wait_reason": "evidence",
       "wake": {"kind": "not_before", "at": "2099-01-01T00:00:00Z"}}
CALL = [{"id": "tc1", "name": "spawn_subsession", "args": {"task": "one"}}]


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


def open_root(cur, version=1):
    spec = {"route_policy_name": "default", "version": version}
    return str(q1(cur, "SELECT v13_plan_commit_entry(%s::jsonb)", (json.dumps(spec),)))


def prefix(cur, sid, text="hello goal"):
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": text})))


def max_seq(cur, sid):
    return q1(cur, "SELECT max(seq) FROM events WHERE session_id=%s", (sid,))


def plan_n(cur, sid):
    return q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id=%s "
        "AND type IN ('plan/committed','todo/delta')",
        (sid,))


def n_effects(cur, sid=None):
    if sid is None:
        return q1(cur, "SELECT count(*) FROM effects")
    return q1(cur, "SELECT count(*) FROM effects WHERE session_id=%s", (sid,))


def todo(tid, text, cls, status, verb="add_new", due=None):
    return {
        "todo_id": tid,
        "text": text,
        "text_hash": sha(text),
        "task_class": cls,
        "status": status,
        "due": due,
        "verb": verb,
    }


def plan_body(todos, based):
    return {
        "schema_version": 1,
        "call_kind": "plan_commit",
        "based_on_seq": based,
        "supersedes": None,
        "todos": todos,
    }


def writer(cur, sid, canonical, now=None):
    cur.execute(
        "SELECT v13_plan_writer(%s::uuid, %s::uuid, %s::uuid, %s, %s::jsonb, %s::timestamptz)",
        (None, sid, u(), canonical["call_kind"], json.dumps(canonical), now))
    return as_obj(cur.fetchone()[0])


def seed(cur, specs, text="anchor"):
    sid = open_root(cur)
    prefix(cur, sid, text)
    ids = [spec[0] for spec in specs]
    cur.execute("SELECT id::text FROM unnest(%s::uuid[]) AS id ORDER BY id", (ids,))
    ordered = [row[0] for row in cur.fetchall()]
    by_id = {spec[0]: spec for spec in specs}
    body = plan_body([todo(*by_id[tid]) for tid in ordered], max_seq(cur, sid))
    writer(cur, sid, body)
    return sid, ordered


def fresh(cur):
    sid = open_root(cur)
    prefix(cur, sid)
    return sid


def snap_of(cur, sid, remaining=0, include_failed=True, failed=False):
    cur.execute(
        "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
        "WHERE session_id=%s",
        (sid,))
    cur.execute("SELECT v13_probe(%s)", (sid,))
    probe = cur.fetchone()[0]
    probe["sid"] = sid
    snap = {"snap": probe, "envelope": {"sid": sid}, "remaining": remaining, "abandon": False}
    if include_failed:
        snap["failed"] = failed
    return snap


def advance(cur, sid, remaining=0, include_failed=True, failed=False):
    snap = snap_of(cur, sid, remaining=remaining, include_failed=include_failed, failed=failed)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid, json.dumps(snap)))
    return cur.fetchone()[0]


def enqueue(cur, sid, kind, request, tool_name=None):
    if tool_name:
        return str(q1(
            cur, "SELECT v13_enqueue_effect(%s, %s, %s::jsonb, %s)",
            (sid, kind, json.dumps(request), tool_name)))
    return str(q1(
        cur, "SELECT v13_enqueue_effect(%s, %s, %s::jsonb)",
        (sid, kind, json.dumps(request))))


def settle(cur, eid, result):
    cur.execute(
        "UPDATE effects SET status='claimed', attempt_no=attempt_no+1, fence=fence+1, "
        "lease_owner='w', lease_until=clock_timestamp()+interval '1 hour' "
        "WHERE effect_id=%s RETURNING attempt_no, fence",
        (eid,))
    attempt, fence = cur.fetchone()
    cur.execute(
        "SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
        (eid, attempt, fence, json.dumps(result)))
    return cur.fetchone()[0]


def bind(cur, sid, tid, text, effect_id, status="runnable"):
    canonical = {
        "schema_version": 1,
        "call_kind": "todo_delta",
        "verb": "update",
        "todo_id": tid,
        "status_from": status,
        "status_to": status,
        "binding": {"effect_id": effect_id, "child_session_id": None},
        "due": None,
        "quarantine": None,
        "text_hash": sha(text),
        "link": None,
    }
    writer(cur, sid, canonical)


def fn_hash(cur, sig):
    return q1(
        cur,
        "SELECT encode(digest(convert_to(pg_get_functiondef(%s::regprocedure), 'UTF8'), 'sha256'), 'hex')",
        (sig,))


def load_arm(server):
    run_psql(server, DB, SQL)


def test_hashes_and_source(cur, before):
    after = (
        fn_hash(cur, "public.v13_recover_idle()"),
        fn_hash(cur, "public.v13_goal_fingerprint(uuid)"),
    )
    src = q1(cur, "SELECT pg_get_functiondef('public.v13_advance(uuid,jsonb)'::regprocedure)")
    prefix = q1(cur, "SELECT pg_get_functiondef('public.v13_plan_advance_prefix(uuid)'::regprocedure)")
    check("recover_idle_and_fingerprint_unmodified", before == after, (before, after))
    check(
        "spawn_arm_still_calls_spawn_subsession",
        "v13_spawn_subsession" in src and src.count("v13_spawn_subsession") >= 1)
    check(
        "plan_arm_does_not_call_child_pointer",
        "v13_child_pointer" not in src and "v13_child_pointer" not in prefix and "v13_child_pointer" not in SQL)
    check(
        "live_approval",
        "approval human exists" in src and "v13: approval human exists" in src)
    check(
        "live_continuation",
        "harness_continuation" in src)
    ver = q1(
        cur,
        "SELECT version FROM v13_policies WHERE name = 'should_run' AND active ORDER BY version DESC LIMIT 1")
    check("policy_version_unchanged", ver == 3, ver)
    check(
        "stage_bytes",
        SQL.count("CREATE OR REPLACE FUNCTION public.v13_advance") == 1
        and "CREATE OR REPLACE FUNCTION public.v13_recover_idle" not in SQL
        and "CREATE OR REPLACE FUNCTION public.v13_goal_fingerprint" not in SQL)


def test_stage_bytes():
    paths = [
        "v13/schema", "v13/resolve", "v13/loop", "v13/twophase", "v13/envelope",
        "v13/manifest", "v13/chunks", "v13/recall", "v13/characterize", "v13/filter",
        "v13/memory", "v13/economy", "v13/summary", "v13/periphery", "v13/mgraph",
        "v13/mgraph_assembly", "v13/control", "v13/spawn", "v13/fanout", "v13/triage",
        "v13/seam", "v13/catalog", "v13/acl", "v13/observe", "v13/handoff",
        "v13/should_run", "v13/quota_window", "v13/attention", "v13/govern",
        "docs/plans/v13-long-loop-phase-a-plan-2026-09-29.md",
    ]
    diff = subprocess.check_output(["git", "diff", "HEAD", "--", *paths], cwd=AGENT_ROOT)
    load = subprocess.check_output(["git", "diff", "HEAD", "--", "v13/load.py"], cwd=AGENT_ROOT).decode()
    head_load = subprocess.check_output(
        ["git", "show", "HEAD:v13/load.py"], cwd=AGENT_ROOT).decode()
    removed = [
        line for line in load.splitlines()
        if line.startswith("-") and not line.startswith("---")
    ]
    check(
        "stage_bytes",
        diff == b"" and removed == [] and "plan_arm" in (load + head_load),
        (removed, load, "plan_arm" in head_load))
    check("r0_source_scope", r0_source_scope() == "fb295ac6c7459bb98dac57e37883af549d2d8a4c")


def r1_driver_restore(current, original):
    """Strip the unique R1 settle_once sentinel pair; remainder must equal fb295ac."""
    import re
    start, end = b"# R1_SETTLE_ONCE_BEGIN", b"# R1_SETTLE_ONCE_END"
    assert current.count(start) == current.count(end) == 1, "r1 sentinel pair"
    assert start not in original and end not in original
    pattern = rb"(?m)^[ \t]*" + start + rb"\n.*?^[ \t]*" + end + rb"\n"
    match = re.search(pattern, current, re.S)
    assert match, "r1 sentinel block"
    block = match.group()
    assert b"def settle_once" in block, "settle_once must live inside the R1 sentinel"
    sess_lock = b"FROM sessions WHERE session_id = %s FOR UPDATE"
    assert block.count(sess_lock) == 1, "sessions FOR UPDATE once in sentinel"
    restored = current[:match.start()] + current[match.end():]
    assert restored == original, "R1 removal must restore ALL baseline driver.py bytes"
    assert b"FOR UPDATE" not in restored, "FOR UPDATE only inside the R1 sentinel"
    return restored, block


def r1_freeze_positive_proof():
    """Mutated copies must fail the R1 restore; the live tree must pass."""
    base = "fb295ac6c7459bb98dac57e37883af549d2d8a4c"
    original = subprocess.check_output(
        ["git", "show", base + ":v13/loop_driver/driver.py"], cwd=AGENT_ROOT)
    current = (AGENT_ROOT / "v13/loop_driver/driver.py").read_bytes()
    r1_driver_restore(current, original)
    empty = original + b"    # R1_SETTLE_ONCE_BEGIN\n    # R1_SETTLE_ONCE_END\n"
    empty_failed = False
    try:
        r1_driver_restore(empty, original)
    except AssertionError:
        empty_failed = True
    assert empty_failed, "empty R1 sentinel must fail"
    mutated = current.replace(b"def run_turn", b"def run_turn_x", 1)
    run_turn_failed = False
    try:
        r1_driver_restore(mutated, original)
    except AssertionError:
        run_turn_failed = True
    assert run_turn_failed, "run_turn edit outside sentinel must fail"
    leaked = current + (
        b"\n    def _r1_leak(self, sid):\n"
        b"        self._sql('v13_advance', 'SELECT v13_advance(%s::uuid, %s::jsonb)',"
        b" (sid, '{}'), sid)\n")
    leak_failed = False
    try:
        r1_driver_restore(leaked, original)
    except AssertionError:
        leak_failed = True
    assert leak_failed, "v13_advance outside sentinel must fail"


def r1_load_append_ok(base_text, current_text, tracked):
    """Accept only a canonical tail append of v13/load.py. Inputs stay in memory."""
    import difflib
    import re

    sql_line = re.compile(
        r'^V13_ROOT / "([A-Za-z_][A-Za-z0-9_]*)" / "([A-Za-z_][A-Za-z0-9_]*\.sql)",$')
    stage_line = re.compile(r'^"([A-Za-z_][A-Za-z0-9_]*)": ([0-9]+),$')
    order_names = ("workspace_admit", "frontier_gap", "goal_supervise", "fair_claim")

    def block(text, opener, closer):
        start = text.find(opener)
        assert start >= 0, "missing " + opener
        start += len(opener)
        end = text.find(closer, start)
        assert end >= 0, "missing closer after " + opener
        return text[start:end]

    def items(text, opener, closer, pattern, label):
        found = []
        for raw in block(text, opener, closer).splitlines():
            line = raw.strip()
            if not line:
                continue
            match = pattern.match(line)
            assert match, "noncanonical " + label + " line: " + line
            found.append(match.groups())
        return found

    def parse(text):
        sql = items(
            text, "SQL_LOAD_ORDER: list[Path] = [", "\n]", sql_line, "SQL_LOAD_ORDER")
        stage = [
            (key, int(number)) for key, number in items(
                text, "STAGE_THROUGH = {", "\n}", stage_line, "STAGE_THROUGH")]
        return sql, stage

    diff = difflib.unified_diff(
        base_text.splitlines(), current_text.splitlines(),
        fromfile="v13/load.py", tofile="v13/load.py", lineterm="")
    plus = []
    for line in diff:
        if line.startswith("--- ") or line.startswith("+++ ") or line.startswith("@@"):
            continue
        assert not line.startswith("-"), "load diff deletes a line"
        if line.startswith("+"):
            body = line[1:].strip()
            assert sql_line.match(body) or stage_line.match(body), (
                "load diff plus line is not a canonical append: " + body)
            plus.append(body)
    base_sql, base_stage = parse(base_text)
    cur_sql, cur_stage = parse(current_text)
    assert cur_sql[:len(base_sql)] == base_sql, "SQL_LOAD_ORDER is not a pure tail append"
    assert cur_stage[:len(base_stage)] == base_stage, "STAGE_THROUGH is not a pure tail append"
    appended_sql = cur_sql[len(base_sql):]
    appended_stage = cur_stage[len(base_stage):]
    paths = [stage + "/" + filename for stage, filename in cur_sql]
    assert len(paths) == len(set(paths)), "duplicate SQL path"
    keys = [key for key, _number in cur_stage]
    assert len(keys) == len(set(keys)), "duplicate stage key"
    numbers = [number for _key, number in cur_stage]
    assert len(numbers) == len(set(numbers)), "duplicate stage number"
    expect = base_stage[-1][1] if base_stage else 0
    for _key, number in appended_stage:
        expect += 1
        assert number == expect, "stage number is not the next contiguous value"
    assert [stage for stage, _filename in appended_sql] == [key for key, _number in appended_stage], (
        "STAGE_THROUGH keys do not match SQL append items")
    for stage, _filename in appended_sql:
        prefix = "v13/" + stage + "/"
        assert any(path.startswith(prefix) for path in tracked), "append stage is not tracked: " + stage
    positions = []
    stages = [stage for stage, _filename in cur_sql]
    for name in order_names:
        assert name in stages, "missing ordered stage: " + name
        positions.append(stages.index(name))
    assert positions == sorted(positions) and len(set(positions)) == len(positions), "stage order"
    expected = ['V13_ROOT / "%s" / "%s",' % item for item in appended_sql]
    expected += ['"%s": %d,' % item for item in appended_stage]
    assert plus == expected, "plus lines do not match append items"
    approved = [
        ("fair_claim", "v13_fair_claim.sql", "fair_claim", 39),
        ("agentctl", "v13_agentctl.sql", "agentctl", 40),
        ("agentctl_verbs", "v13_agentctl_verbs.sql", "agentctl_verbs", 41),
    ]
    got = [
        (stage, filename, key, number)
        for (stage, filename), (key, number) in zip(appended_sql, appended_stage)]
    assert got == approved, (
        "append is not fair_claim/39 then agentctl/40 then agentctl_verbs/41: " + str(got))


def r1_phase_d_prefix_allowance():
    """Path closure, known-byte pins, and the in-memory failure proofs."""
    import ast
    import re

    phase_d = "78e77c710bf06a0a1c771b822a3837c5db4c66d0"
    base = "fb295ac6c7459bb98dac57e37883af549d2d8a4c"
    prefixes = ("v13/goal_supervisor/", "v13/fair_claim/", "v13/fair_driver/")
    fresh_ok = {"v13/goal_supervisor/accept_unattended.py"}
    stage40 = {
        "v13/agentctl/v13_agentctl.sql",
        "v13/agentctl/setup_db.py",
        "v13/agentctl/test_agentctl.py",
        "v13/agentctl/README.md",
    }
    stage41 = {
        "v13/agentctl_verbs/v13_agentctl_verbs.sql",
        "v13/agentctl_verbs/setup_db.py",
        "v13/agentctl_verbs/test_agentctl_verbs.py",
        "v13/agentctl_verbs/README.md",
    }
    subprocess.check_call(["git", "cat-file", "-e", phase_d + "^{commit}"], cwd=AGENT_ROOT)
    subprocess.check_call(["git", "cat-file", "-e", base + "^{commit}"], cwd=AGENT_ROOT)

    def git_text(rev, path):
        return subprocess.check_output(["git", "show", rev + ":" + path], cwd=AGENT_ROOT).decode()

    def tree(rev):
        return set(subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", rev, "--", "v13"],
            cwd=AGENT_ROOT).decode().splitlines())

    def goal_test_ok(before, after):
        old_tree, new_tree = ast.parse(before), ast.parse(after)
        old_functions = {n.name: n for n in old_tree.body if isinstance(n, ast.FunctionDef)}
        new_functions = {n.name: n for n in new_tree.body if isinstance(n, ast.FunctionDef)}
        for func, old_node in old_functions.items():
            assert func in new_functions, func
            if func == "test_stage_bytes":
                continue
            old_text = "\n".join(before.splitlines()[old_node.lineno - 1:old_node.end_lineno])
            new_node = new_functions[func]
            new_text = "\n".join(after.splitlines()[new_node.lineno - 1:new_node.end_lineno])
            if func == "run":
                new_text = "\n".join(
                    line for line in new_text.splitlines()
                    if not re.match(r"\s+unattended_[A-Za-z0-9_]+\(.*\)$", line))
            assert old_text == new_text, "changed goal_supervisor test: " + func
        normalize = lambda tree: [
            ast.dump(n, include_attributes=False) for n in tree.body
            if not isinstance(n, ast.FunctionDef)]
        assert normalize(old_tree) == normalize(new_tree), "changed goal_supervisor module setup"

    def fair_test_ok(before, after):
        old_tree, new_tree = ast.parse(before), ast.parse(after)
        old_functions = {n.name: n for n in old_tree.body if isinstance(n, ast.FunctionDef)}
        new_functions = {n.name: n for n in new_tree.body if isinstance(n, ast.FunctionDef)}
        assert set(new_functions) == set(old_functions), "fair_claim test added or dropped a function"
        for func, old_node in old_functions.items():
            if func == "test_stage_bytes":
                continue
            new_node = new_functions[func]
            old_text = "\n".join(before.splitlines()[old_node.lineno - 1:old_node.end_lineno])
            new_text = "\n".join(after.splitlines()[new_node.lineno - 1:new_node.end_lineno])
            assert old_text == new_text, "changed fair_claim test: " + func
        normalize = lambda tree: [
            ast.dump(n, include_attributes=False) for n in tree.body
            if not isinstance(n, ast.FunctionDef)]
        assert normalize(old_tree) == normalize(new_tree), "changed fair_claim module setup"

    def readme_ok(before, after):
        assert after.startswith(before), "README is not a pure append"
        suffix = after[len(before):].lstrip("\n")
        assert suffix == "" or suffix.startswith("## 授权验收"), (
            "README append is not the authorization section")

    def allow(extra, known_names, blobs, current, load_base, load_current, tracked):
        for name in extra:
            assert name.startswith(prefixes) or name in stage40 or name in stage41, (
                "outside the three prefixes: " + name)
        assert extra - known_names - stage40 - stage41 <= fresh_ok, (
            "fresh file outside accept_unattended.py")
        missing = stage40 - set(tracked)
        assert not missing, "stage 40 path is not tracked: " + str(sorted(missing))
        missing41 = stage41 - set(tracked)
        assert not missing41, "stage 41 path is not tracked: " + str(sorted(missing41))
        for name in known_names & extra:
            blob, now = blobs[name], current[name]
            if name == "v13/goal_supervisor/README.md":
                readme_ok(blob.decode(), now.decode())
            elif name == "v13/goal_supervisor/test_goal_supervisor.py":
                goal_test_ok(blob.decode(), now.decode())
            elif name == "v13/fair_claim/test_fair_claim.py":
                fair_test_ok(blob.decode(), now.decode())
            else:
                assert now == blob, "known bytes changed: " + name
        r1_load_append_ok(load_base, load_current, tracked)

    def must_reject(call):
        failed = False
        try:
            call()
        except AssertionError:
            failed = True
        assert failed, "synthetic case must reject"

    protected = tree(base)
    phase_files = tree(phase_d)
    tracked = set(subprocess.check_output(
        ["git", "ls-files", "--", "v13"], cwd=AGENT_ROOT).decode().splitlines())
    extra = tracked - protected
    known_names = extra & phase_files
    blobs = {
        name: subprocess.check_output(["git", "show", phase_d + ":" + name], cwd=AGENT_ROOT)
        for name in known_names}
    current = {name: (AGENT_ROOT / name).read_bytes() for name in known_names}
    load_base = git_text(base, "v13/load.py")
    load_current = (AGENT_ROOT / "v13/load.py").read_text()
    allow(extra, known_names, blobs, current, load_base, load_current, tracked)

    goal_name = "v13/goal_supervisor/test_goal_supervisor.py"
    fair_name = "v13/fair_claim/test_fair_claim.py"
    readme_name = "v13/goal_supervisor/README.md"
    driver_name = "v13/goal_supervisor/driver.py"
    setup_name = "v13/goal_supervisor/setup_db.py"
    fair_sql = "v13/fair_claim/v13_fair_claim.sql"
    goal_before = blobs[goal_name].decode()
    fair_before = blobs[fair_name].decode()

    def reject_bytes(name):
        mutated = dict(current)
        mutated[name] = blobs[name] + b"\n"
        must_reject(lambda: allow(
            extra, known_names, blobs, mutated, load_base, load_current, tracked))

    reject_bytes(driver_name)
    reject_bytes(setup_name)
    reject_bytes(fair_sql)
    reject_bytes("v13/fair_driver/driver.py")
    must_reject(lambda: allow(
        extra | {"v13/not_allowed/x.py"}, known_names, blobs, current,
        load_base, load_current, tracked))
    accept_name = "v13/goal_supervisor/accept_unattended.py"
    allow(extra | {accept_name}, known_names, blobs, current, load_base, load_current, tracked)
    must_reject(lambda: allow(
        extra | {accept_name, "v13/goal_supervisor/second_new.py"}, known_names, blobs, current,
        load_base, load_current, tracked))
    goal_mut = dict(current)
    goal_mut[goal_name] = goal_before.replace("def test_static(", "def test_staticX(", 1).encode()
    must_reject(lambda: allow(
        extra, known_names, blobs, goal_mut, load_base, load_current, tracked))
    goal_run = dict(current)
    goal_run[goal_name] = goal_before.replace("    test_static()\n", "", 1).encode()
    must_reject(lambda: allow(
        extra, known_names, blobs, goal_run, load_base, load_current, tracked))
    readme_mut = dict(current)
    readme_mut[readme_name] = blobs[readme_name].replace(b"Gate", b"Gatf", 1)
    must_reject(lambda: allow(
        extra, known_names, blobs, readme_mut, load_base, load_current, tracked))
    readme_ok_map = dict(current)
    readme_ok_map[readme_name] = blobs[readme_name] + "\n## 授权验收\n".encode()
    allow(extra, known_names, blobs, readme_ok_map, load_base, load_current, tracked)
    fair_mut = dict(current)
    fair_mut[fair_name] = fair_before.replace(
        "def test_static_source(", "def test_static_sourceX(", 1).encode()
    must_reject(lambda: allow(
        extra, known_names, blobs, fair_mut, load_base, load_current, tracked))

    live = load_current
    must_reject(lambda: r1_load_append_ok(
        load_base, live.replace('"""Cumulative SQL load order', '"""Cumulative SQL', 1), tracked))
    inserted = live.replace(
        "def load_stage(server, database: str, stage: str) -> None:\n",
        "def load_stage(server, database: str, stage: str) -> None:\n"
        "    note = 'inserted'\n",
        1)
    must_reject(lambda: r1_load_append_ok(load_base, inserted, tracked))
    canonical = live.replace(
        "def load_stage(server, database: str, stage: str) -> None:\n",
        "def load_stage(server, database: str, stage: str) -> None:\n"
        '    V13_ROOT / "fair_claim" / "v13_fair_claim.sql",\n',
        1)
    must_reject(lambda: r1_load_append_ok(load_base, canonical, tracked))
    must_reject(lambda: r1_load_append_ok(load_base, live + "\ndef r1_extra():\n    return 1\n", tracked))
    inverted = load_base.replace(
        '    V13_ROOT / "goal_supervise" / "v13_goal_supervise.sql",\n',
        '    V13_ROOT / "fair_claim" / "v13_fair_claim.sql",\n'
        '    V13_ROOT / "goal_supervise" / "v13_goal_supervise.sql",\n',
        1).replace(
        '    "goal_supervise": 38,\n',
        '    "goal_supervise": 38,\n    "fair_claim": 39,\n',
        1)
    must_reject(lambda: r1_load_append_ok(load_base, inverted, tracked))
    must_reject(lambda: r1_load_append_ok(load_base, live, tracked - {p for p in tracked if p.startswith("v13/fair_claim/")}))
    key_only = live.replace(
        '    "fair_claim": 39,\n',
        '    "fair_claim": 39,\n    "ghost": 40,\n',
        1)
    must_reject(lambda: r1_load_append_ok(load_base, key_only, tracked | {"v13/ghost/v13_ghost.sql"}))
    sql_only = live.replace(
        '    V13_ROOT / "fair_claim" / "v13_fair_claim.sql",\n',
        '    V13_ROOT / "fair_claim" / "v13_fair_claim.sql",\n'
        '    V13_ROOT / "fair_driver" / "v13_fair_driver.sql",\n',
        1)
    must_reject(lambda: r1_load_append_ok(load_base, sql_only, tracked))
    must_reject(lambda: r1_load_append_ok(
        load_base, live.replace('    "fair_claim": 39,\n', '    "fair_claim": 39,\n    "fair_claim": 40,\n', 1),
        tracked))
    skipped = load_base.replace(
        '    V13_ROOT / "goal_supervise" / "v13_goal_supervise.sql",\n',
        '    V13_ROOT / "goal_supervise" / "v13_goal_supervise.sql",\n'
        '    V13_ROOT / "fair_claim" / "v13_fair_claim.sql",\n',
        1).replace('    "goal_supervise": 38,\n', '    "goal_supervise": 38,\n    "fair_claim": 41,\n', 1)
    must_reject(lambda: r1_load_append_ok(load_base, skipped, tracked))
    regressed = skipped.replace('"fair_claim": 41,', '"fair_claim": 10,', 1)
    must_reject(lambda: r1_load_append_ok(load_base, regressed, tracked))
    same_number = load_base.replace(
        '    V13_ROOT / "goal_supervise" / "v13_goal_supervise.sql",\n',
        '    V13_ROOT / "goal_supervise" / "v13_goal_supervise.sql",\n'
        '    V13_ROOT / "fair_claim" / "v13_fair_claim.sql",\n'
        '    V13_ROOT / "fair_driver" / "v13_fair_driver.sql",\n',
        1).replace(
        '    "goal_supervise": 38,\n',
        '    "goal_supervise": 38,\n    "fair_claim": 39,\n    "fair_driver": 39,\n',
        1)
    must_reject(lambda: r1_load_append_ok(load_base, same_number, tracked))
    twice = load_base.replace(
        '    V13_ROOT / "goal_supervise" / "v13_goal_supervise.sql",\n',
        '    V13_ROOT / "goal_supervise" / "v13_goal_supervise.sql",\n'
        '    V13_ROOT / "fair_claim" / "v13_fair_claim.sql",\n'
        '    V13_ROOT / "fair_claim" / "v13_fair_claim.sql",\n',
        1).replace('    "goal_supervise": 38,\n', '    "goal_supervise": 38,\n    "fair_claim": 39,\n', 1)
    must_reject(lambda: r1_load_append_ok(load_base, twice, tracked))
    missing = load_base.replace(
        '    V13_ROOT / "goal_supervise" / "v13_goal_supervise.sql",\n',
        '    V13_ROOT / "goal_supervise" / "v13_goal_supervise.sql",\n'
        '    V13_ROOT / "missing_stage" / "v13_missing_stage.sql",\n',
        1).replace(
        '    "goal_supervise": 38,\n',
        '    "goal_supervise": 38,\n    "missing_stage": 39,\n',
        1)
    must_reject(lambda: r1_load_append_ok(load_base, missing, tracked))

    def reject_reason(call, needle):
        try:
            call()
        except AssertionError as exc:
            assert needle in str(exc), str(exc)
            return
        raise AssertionError("synthetic case must reject: " + needle)

    live = load_current
    reject_reason(
        lambda: allow(
            extra | {"v13/not_allowed/x.py"}, known_names, blobs, current,
            load_base, load_current, tracked),
        "outside the three prefixes")
    reject_reason(
        lambda: allow(
            extra | {"v13/agentctl/extra.py"}, known_names, blobs, current,
            load_base, load_current, tracked),
        "outside the three prefixes")
    reject_reason(
        lambda: allow(
            extra, known_names, blobs, current, load_base, load_current,
            tracked - {"v13/agentctl/v13_agentctl.sql"}),
        "stage 40 path is not tracked")
    reject_reason(
        lambda: allow(
            (extra - {"v13/agentctl/test_agentctl.py"}) | {"v13/agentctl/extra.py"},
            known_names, blobs, current, load_base, load_current, tracked),
        "outside the three prefixes")
    reject_reason(
        lambda: r1_load_append_ok(
            load_base, live.replace('    "agentctl": 40,\n', '    "agentctl": 40a,\n', 1), tracked),
        "load diff plus line is not a canonical append")
    reject_reason(
        lambda: r1_load_append_ok(
            load_base, live.replace('    "agentctl": 40,\n', '    "agentctl": 41,\n', 1), tracked),
        "duplicate stage number")
    reject_reason(
        lambda: r1_load_append_ok(
            load_base,
            live.replace("v13_agentctl.sql", "v13_agentctl_extra.sql", 1),
            tracked),
        "append is not fair_claim/39 then agentctl/40 then agentctl_verbs/41")
    reject_reason(
        lambda: r1_load_append_ok(
            load_base,
            live.replace('    "agentctl": 40,\n', '    "agentctl_verbs": 40,\n', 1),
            tracked),
        "duplicate stage key")
    reject_reason(
        lambda: allow(
            extra | {"v13/agentctl_verbs/extra.py"}, known_names, blobs, current,
            load_base, load_current, tracked),
        "outside the three prefixes")
    reject_reason(
        lambda: allow(
            extra | {"v13/goal_workflow/test_goal_workflow.py"}, known_names, blobs, current,
            load_base, load_current, tracked),
        "outside the three prefixes")
    reject_reason(
        lambda: allow(
            extra, known_names, blobs, current, load_base, load_current,
            tracked - {"v13/agentctl_verbs/v13_agentctl_verbs.sql"}),
        "stage 41 path is not tracked")
    reject_reason(
        lambda: r1_load_append_ok(
            load_base, live.replace('    "agentctl_verbs": 41,\n', '    "agentctl_verbs": 42,\n', 1), tracked),
        "stage number is not the next contiguous value")
    reject_reason(
        lambda: r1_load_append_ok(
            load_base, live.replace('    "agentctl_verbs": 41,\n', '    "agentctl_verbs": 41a,\n', 1), tracked),
        "load diff plus line is not a canonical append")
    future = live.replace(
        '    V13_ROOT / "agentctl_verbs" / "v13_agentctl_verbs.sql",\n',
        '    V13_ROOT / "agentctl_verbs" / "v13_agentctl_verbs.sql",\n'
        '    V13_ROOT / "goal_workflow" / "v13_goal_workflow.sql",\n',
        1).replace(
        '    "agentctl_verbs": 41,\n',
        '    "agentctl_verbs": 41,\n    "goal_workflow": 42,\n',
        1)
    reject_reason(
        lambda: r1_load_append_ok(
            load_base, future, tracked | {"v13/goal_workflow/v13_goal_workflow.sql"}),
        "append is not fair_claim/39 then agentctl/40 then agentctl_verbs/41")


def r0_source_scope():
    """Fixed-base positive proof, shared by the affected stage gates."""
    import ast
    import re

    base = "fb295ac6c7459bb98dac57e37883af549d2d8a4c"
    subprocess.check_call(["git", "cat-file", "-e", base + "^{commit}"], cwd=AGENT_ROOT)

    def original(path):
        return subprocess.check_output(["git", "show", base + ":" + path], cwd=AGENT_ROOT)

    path = "v13/plan_arm/v13_plan_arm.sql"
    old = original(path)
    current = (AGENT_ROOT / path).read_bytes()
    restored = current
    blocks = {}
    for kind in ("DECL", "RECEIPT"):
        start, end = ("-- R0_" + kind + "_BEGIN").encode(), ("-- R0_" + kind + "_END").encode()
        assert current.count(start) == current.count(end) == 1, kind
        assert start not in old and end not in old
        pattern = rb"(?m)^[ \t]*" + start + rb"\n.*?^[ \t]*" + end + rb"\n"
        match = re.search(pattern, restored, re.S)
        assert match, kind
        blocks[kind] = match.group()
        restored = restored[:match.start()] + restored[match.end():]
    assert restored == old, "R0 removal must restore ALL baseline SQL bytes"
    assert current.count(b"CREATE OR REPLACE FUNCTION public.v13_advance") == 1
    declare_anchor = b"  v_plan_word text;\n"
    assert current.index(declare_anchor) + len(declare_anchor) == current.index(blocks["DECL"])
    assert current[current.index(blocks["DECL"]) + len(blocks["DECL"]):].startswith(b"BEGIN\n")
    anchor = b"  IF EXISTS (SELECT 1 FROM effects WHERE session_id = p_sid AND status IN ('ready', 'claimed')) THEN\n"
    assert current.count(anchor) == 1
    assert current.index(anchor) + len(anchor) == current.index(blocks["RECEIPT"])
    assert blocks["RECEIPT"].count(b"v13_append_event(") == 1
    for token in (b"v13_plan_map_root", b"v13_unpaid_harness_turn", b"v13_harness_settle",
                  b"v13_harness_tail_gap", b"v13_enqueue", b"v13_send_work", b"v13_closeout",
                  b"v13_plan_advance_prefix", b"v13_spawn", b"v13_route(", b"EXCEPTION"):
        assert token not in blocks["RECEIPT"], token
    tests = {"v13/plan_arm/test_plan_arm.py", "v13/frontier_gap/test_frontier_gap.py",
             "v13/goal_supervise/test_goal_supervise.py",
             "v13/loop_driver/test_loop_driver.py"}
    readmes = {"v13/plan_arm/README.md", "v13/frontier_gap/README.md",
               "v13/goal_supervise/README.md", "v13/loop_driver/README.md"}
    driver_path = "v13/loop_driver/driver.py"
    protected = subprocess.check_output([
        "git", "ls-tree", "-r", "--name-only", base, "--", "v13",
        "docs/plans/v13-long-loop-plan-2026-09-28.md",
        "docs/plans/v13-long-loop-phase-a-plan-2026-09-29.md",
        "docs/plans/v13-long-loop-phase-b-plan-2026-09-29.md",
        "docs/plans/v13-long-loop-phase-c-plan-2026-09-29.md"], cwd=AGENT_ROOT).decode().splitlines()
    for name in protected:
        if name not in tests | readmes | {path, driver_path, "v13/load.py"}:
            assert (AGENT_ROOT / name).read_bytes() == original(name), "protected bytes: " + name
    r1_phase_d_prefix_allowance()
    r1_driver_restore((AGENT_ROOT / driver_path).read_bytes(), original(driver_path))
    r1_freeze_positive_proof()
    # Keep existing functions byte-for-byte; only stage guards and added r0_/r1_ calls are exceptions.
    for name in tests:
        before = original(name).decode()
        after = (AGENT_ROOT / name).read_text()
        old_tree, new_tree = ast.parse(before), ast.parse(after)
        old_functions = {n.name: n for n in old_tree.body if isinstance(n, ast.FunctionDef)}
        new_functions = {n.name: n for n in new_tree.body if isinstance(n, ast.FunctionDef)}
        for func, old_node in old_functions.items():
            assert func in new_functions, (name, func)
            new_node = new_functions[func]
            if func == "test_stage_bytes":
                continue
            old_text = "\n".join(before.splitlines()[old_node.lineno - 1:old_node.end_lineno])
            new_text = "\n".join(after.splitlines()[new_node.lineno - 1:new_node.end_lineno])
            if func in ("main", "run"):
                new_text = "\n".join(
                    line for line in new_text.splitlines()
                    if not re.match(r"\s+r[01]_[a-z_]+\(.*\)$", line))
            assert old_text == new_text, "changed existing test: " + name + ":" + func
        # Also freeze imports, constants, and top-level exception/entry handling.
        normalize = lambda tree: [ast.dump(n, include_attributes=False) for n in tree.body
                                  if not isinstance(n, ast.FunctionDef)]
        assert normalize(old_tree) == normalize(new_tree), "changed module setup: " + name
        assert all(n in old_functions or n.startswith("r0_") or n.startswith("r1_")
                   for n in new_functions), name
    return base


def harness_req(cur, sid):
    rev = int(q1(cur, "SELECT (v13_probe(%s)->>'tools_revision')::bigint", (sid,)))
    return {
        "tool": "harness_turn",
        "params": {},
        "handler": "worker:harness_turn",
        "tools_revision": rev,
        "logical_turn_id": u(),
        "continuation_index": 0,
    }


def test_live_arms_runtime(cur):
    sid = fresh(cur)
    eid = enqueue(cur, sid, "tool", harness_req(cur, sid), "harness_turn")
    settle(cur, eid, {
        "result_kind": "wait",
        "wait_reason": "approval",
        "interaction_id": "ix-approval-1",
        "delivery_kind": "USER_ACTION_REQUIRED",
    })
    word = advance(cur, sid)
    href = as_obj(q1(
        cur,
        "SELECT request FROM effects WHERE session_id=%s AND kind='human'",
        (sid,)))
    check(
        "live_approval",
        word == "waiting" and href == {"schema_version": 1, "interaction_ref": "ix-approval-1"},
        (word, href))
    sid = fresh(cur)
    eid = enqueue(cur, sid, "tool", harness_req(cur, sid), "harness_turn")
    settle(cur, eid, {"result_kind": "progress", "signals": ["repair/required"]})
    word = advance(cur, sid)
    reason = q1(
        cur,
        "SELECT payload->>'reason' FROM events WHERE session_id=%s AND type='turn/route' "
        "ORDER BY seq DESC LIMIT 1",
        (sid,))
    check("live_continuation", word == "waiting" and reason == "harness_continuation", (word, reason))


def test_no_plan(cur):
    sid = fresh(cur)
    before = plan_n(cur, sid)
    effects = n_effects(cur, sid)
    word = advance(cur, sid)
    sel = q1(
        cur,
        "SELECT count(*) FROM effects WHERE session_id=%s AND request::text LIKE %s",
        (sid, "%selected_todo%"))
    check(
        "no_plan_no_new_effect",
        plan_n(cur, sid) == before and sel == 0 and word in ("waiting", "progressed", "terminal"),
        (word, effects, n_effects(cur, sid)))


def test_live_stop_and_receipt(cur):
    sid = fresh(cur)
    eid = enqueue(cur, sid, "llm", {"route": {"action": "llm", "reason": "answer"}})
    settle(cur, eid, {"text": "ok", "tool_calls": CALL})
    cur.execute("SELECT v13_goal_stop(%s, %s)", (sid, "pause"))
    effects = n_effects(cur, sid)
    word = advance(cur, sid)
    check("live_spawn_stopped", word == "waiting" and n_effects(cur, sid) == effects, word)

    sid = fresh(cur)
    eid = enqueue(
        cur, sid, "tool",
        {
            "tool": "harness_turn",
            "params": {},
            "handler": "worker:harness_turn",
            "tools_revision": 1,
            "logical_turn_id": u(),
            "continuation_index": 0,
        },
        "harness_turn")
    settle(cur, eid, PROGRESS)
    cur.execute("SELECT v13_goal_stop(%s, %s)", (sid, "pause"))
    materials = q1(
        cur, "SELECT count(*) FROM events WHERE session_id=%s AND type='turn/material_spent'", (sid,))
    plans = plan_n(cur, sid)
    word = advance(cur, sid, include_failed=False)
    check(
        "live_receipt",
        word == "waiting"
        and q1(cur, "SELECT count(*) FROM events WHERE session_id=%s AND type='turn/material_spent'", (sid,))
        == materials + 1
        and plan_n(cur, sid) == plans,
        word)
    sid = fresh(cur)
    eid = enqueue(
        cur, sid, "tool",
        {
            "tool": "harness_turn",
            "params": {},
            "handler": "worker:harness_turn",
            "tools_revision": 1,
            "logical_turn_id": u(),
            "continuation_index": 0,
        },
        "harness_turn")
    settle(cur, eid, FINISH)
    cur.execute("SELECT v13_goal_stop(%s, %s)", (sid, "pause"))
    plans = plan_n(cur, sid)
    word = advance(cur, sid, include_failed=False)
    check(
        "live_finish_stopped_without_failed_key",
        word == "terminal" and plan_n(cur, sid) == plans,
        word)


def test_dispatch_and_bind(cur):
    tid = u()
    sid, _ids = seed(cur, [(tid, "do work", "advancement_task", "runnable")])
    before = n_effects(cur, sid)
    word = advance(cur, sid)
    kind = q1(
        cur,
        "SELECT kind FROM effects WHERE session_id=%s AND request::text LIKE %s",
        (sid, "%selected_todo%"))
    check(
        "dispatch_kind",
        word == "waiting" and kind == "llm" and n_effects(cur, sid) == before + 1,
        (word, kind))
    again = n_effects(cur, sid)
    word2 = advance(cur, sid)
    check("bind_once", word2 == "waiting" and n_effects(cur, sid) == again, word2)

    ot = u()
    sid, _ids = seed(cur, [(ot, "ask", "user_gate", "runnable")])
    advance(cur, sid)
    okind = q1(
        cur,
        "SELECT kind FROM effects WHERE session_id=%s AND request::text LIKE %s",
        (sid, "%selected_todo%"))
    check("dispatch_kind", okind == "human", okind)

    nt = u()
    sid, _ids = seed(cur, [(nt, "later", "advancement_task", "pending")])
    before = n_effects(cur, sid)
    advance(cur, sid)
    sel = q1(
        cur,
        "SELECT count(*) FROM effects WHERE session_id=%s AND request::text LIKE %s",
        (sid, "%selected_todo%"))
    check("dispatch_kind", sel == 0, (before, n_effects(cur, sid), sel))


def test_archive_and_child(cur):
    tid = u()
    sid, ids = seed(cur, [(tid, "chain", "advancement_task", "runnable")])
    eid = enqueue(cur, sid, "llm", {"route": {"action": "llm", "reason": "answer"}})
    settle(cur, eid, {"text": "ok", "tool_calls": CALL})
    plans = plan_n(cur, sid)
    cur.execute("SET ROLE v13_route")
    word = advance(cur, sid)
    cur.execute("RESET ROLE")
    check("archive_child_excerpt_done", word == "progressed" and plan_n(cur, sid) == plans, word)
    cur.execute("SELECT session_id::text FROM sessions WHERE parent_session_id=%s", (sid,))
    child = cur.fetchone()[0]
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'workflow/pointer', %s::jsonb)",
        (child, u(), json.dumps({
            "schema_version": 1,
            "parent_session_id": sid,
            "root_session_id": sid,
            "todo_id": ids[0],
            "up_to_seq": 0,
        })))
    plans_before_child = plan_n(cur, sid)
    word = advance(cur, child)
    read_id = q1(
        cur,
        "SELECT effect_id::text FROM effects WHERE session_id=%s AND tool_name='read_file_py'",
        (child,))
    calls = q1(cur, "SELECT count(*) FROM events WHERE session_id=%s AND type='tool/call'", (child,))
    check(
        "child_read_effect_not_tool_call",
        word == "waiting" and read_id is not None and calls == 0 and plan_n(cur, sid) == plans_before_child,
        (word, read_id, calls))
    check("child_skips_arm", plan_n(cur, child) == 0 and plan_n(cur, sid) == plans_before_child)
    settle(cur, read_id, {"excerpt": "bounded text"})
    effects = n_effects(cur, sid)
    word = advance(cur, sid)
    status = q1(cur, "SELECT status FROM v13_plan_todo_fold(%s) WHERE todo_id=%s", (sid, ids[0]))
    deltas = q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id=%s AND type='todo/delta' "
        "AND payload->'canonical'->>'status_to'='done'",
        (sid,))
    check(
        "archive_child_excerpt_done",
        word == "waiting" and status == "done" and deltas == 1 and n_effects(cur, sid) == effects,
        (word, status, deltas))

    tid = u()
    text = "progress me"
    sid, ids = seed(cur, [(tid, text, "advancement_task", "runnable")])
    eid = enqueue(
        cur, sid, "tool",
        {
            "tool": "harness_turn",
            "params": {},
            "handler": "worker:harness_turn",
            "tools_revision": 1,
            "logical_turn_id": u(),
            "continuation_index": 0,
        },
        "harness_turn")
    settle(cur, eid, PROGRESS)
    bind(cur, sid, ids[0], text, eid)
    effects = n_effects(cur, sid)
    word = advance(cur, sid)
    status = q1(cur, "SELECT status FROM v13_plan_todo_fold(%s) WHERE todo_id=%s", (sid, ids[0]))
    check("archive_progress", status == "done" and word in ("waiting", "terminal", "progressed"), (word, status))

    tid = u()
    text = "finish me"
    sid, ids = seed(cur, [(tid, text, "advancement_task", "runnable")])
    eid = enqueue(
        cur, sid, "tool",
        {
            "tool": "harness_turn",
            "params": {},
            "handler": "worker:harness_turn",
            "tools_revision": 1,
            "logical_turn_id": u(),
            "continuation_index": 0,
        },
        "harness_turn")
    settle(cur, eid, FINISH)
    bind(cur, sid, ids[0], text, eid)
    effects = n_effects(cur, sid)
    word = advance(cur, sid)
    status = q1(cur, "SELECT status FROM v13_plan_todo_fold(%s) WHERE todo_id=%s", (sid, ids[0]))
    check(
        "archive_when_not_reselected",
        status == "done" and n_effects(cur, sid) == effects and word == "terminal",
        (word, status, effects, n_effects(cur, sid)))
    tid = u()
    text = "wait me"
    sid, ids = seed(cur, [(tid, text, "advancement_task", "runnable")])
    eid = enqueue(
        cur, sid, "tool",
        {
            "tool": "harness_turn",
            "params": {},
            "handler": "worker:harness_turn",
            "tools_revision": 1,
            "logical_turn_id": u(),
            "continuation_index": 0,
        },
        "harness_turn")
    settle(cur, eid, WAIT)
    bind(cur, sid, ids[0], text, eid)
    plans = plan_n(cur, sid)
    advance(cur, sid)
    check("archive_when_not_reselected", plan_n(cur, sid) == plans)

    mid = u()
    sid, ids = seed(cur, [(mid, "watch", "continuous_monitor", "waiting", "add_new", "2099-01-01T00:00:00Z")])
    plans = plan_n(cur, sid)
    advance(cur, sid)
    status = q1(cur, "SELECT status FROM v13_plan_todo_fold(%s) WHERE todo_id=%s", (sid, ids[0]))
    check("monitor_due_not_guessed", plan_n(cur, sid) == plans and status == "waiting", status)


def test_reenable(cur):
    tid = u()
    text = "again"
    sid, ids = seed(cur, [(tid, text, "advancement_task", "runnable")])
    eid = enqueue(cur, sid, "llm", {"route": {"action": "llm", "reason": "old"}})
    settle(cur, eid, {"text": "no"})
    cur.execute("UPDATE effects SET status='failed' WHERE effect_id=%s", (eid,))
    bind(cur, sid, ids[0], text, eid)
    writer(cur, sid, {
        "schema_version": 1,
        "call_kind": "todo_delta",
        "verb": "update",
        "todo_id": ids[0],
        "status_from": "runnable",
        "status_to": "blocked",
        "binding": None,
        "due": None,
        "quarantine": {"effect_id": eid, "cleared": False},
        "text_hash": sha(text),
        "link": None,
    })
    writer(cur, sid, {
        "schema_version": 1,
        "call_kind": "todo_delta",
        "verb": "update",
        "todo_id": ids[0],
        "status_from": "blocked",
        "status_to": "runnable",
        "binding": {"clear_binding": True},
        "due": None,
        "quarantine": {"effect_id": eid, "cleared": True},
        "text_hash": sha(text),
        "link": None,
    })
    before = {
        row[0] for row in q1_all(cur, "SELECT effect_id::text FROM effects WHERE session_id=%s", (sid,))
    }
    word = advance(cur, sid)
    new_id = q1(
        cur,
        "SELECT effect_id::text FROM effects WHERE session_id=%s AND request::text LIKE %s",
        (sid, "%selected_todo%"))
    check(
        "reenable_binds_new_effect",
        word == "waiting" and new_id is not None and new_id not in before,
        (word, new_id))


def q1_all(cur, sql, params=None):
    cur.execute(sql, params)
    return cur.fetchall()


def fold_of(cur, sid, tid):
    cur.execute(
        "SELECT status, due, quarantine FROM v13_plan_todo_fold(%s) WHERE todo_id=%s",
        (sid, tid))
    status, due, quarantine = cur.fetchone()
    return status, due, as_obj(quarantine)


def open_session(cur, status="ready"):
    sid = str(q1(cur, "SELECT v13_open_session(%s::jsonb)", ('{"version":1}',)))
    if status != "ready":
        cur.execute("UPDATE sessions SET status=%s WHERE session_id=%s", (status, sid))
    return sid


def insert_effect(cur, sid, eid, kind, status, result=None, tool_name=None):
    cur.execute(
        "INSERT INTO effects (effect_id, session_id, kind, tool_name, request, request_hash, "
        "origin_user_seq, status, result) "
        "VALUES (%s, %s, %s, %s, %s::jsonb, %s, 0, %s, %s::jsonb)",
        (eid, sid, kind, tool_name, '{"fixture":true}', "fixture", status,
         None if result is None else json.dumps(result)))


def bind_child(cur, sid, tid, text, child, status="runnable"):
    writer(cur, sid, {
        "schema_version": 1,
        "call_kind": "todo_delta",
        "verb": "update",
        "todo_id": tid,
        "status_from": status,
        "status_to": status,
        "binding": {"effect_id": None, "child_session_id": child},
        "due": None,
        "quarantine": None,
        "text_hash": sha(text),
        "link": None,
    })


def promote_monitor(cur, sid, tid, text):
    writer(cur, sid, {
        "schema_version": 1,
        "call_kind": "todo_delta",
        "verb": "update",
        "todo_id": tid,
        "status_from": "waiting",
        "status_to": "runnable",
        "binding": None,
        "due": None,
        "quarantine": None,
        "text_hash": sha(text),
        "link": None,
    }, now="2026-09-30T00:00:00Z")


def test_p1_fixes(cur):
    noop_id = "00000000-0000-4000-8000-000000000001"
    hold_id = "00000000-0000-4000-8000-000000000002"
    other = open_session(cur)
    insert_effect(cur, other, hold_id, "llm", "ready")
    tid_noop, tid_arch, tid_hold = u(), u(), u()
    text_noop, text_arch, text_hold = "noop", "archive", "hold"
    sid, ids = seed(cur, [
        (tid_noop, text_noop, "advancement_task", "runnable"),
        (tid_arch, text_arch, "advancement_task", "runnable"),
        (tid_hold, text_hold, "advancement_task", "runnable"),
    ])
    by = {tid_noop: text_noop, tid_arch: text_arch, tid_hold: text_hold}
    insert_effect(
        cur, sid, noop_id, "llm", "succeeded",
        {"text": "x", "result_kind": "progress"})
    eid = enqueue(cur, sid, "tool", harness_req(cur, sid), "harness_turn")
    settle(cur, eid, FINISH)
    check("bound_scan_effect_order", noop_id < eid and hold_id < eid, (noop_id, hold_id, eid))
    bind(cur, sid, tid_noop, by[tid_noop], noop_id)
    bind(cur, sid, tid_arch, by[tid_arch], eid)
    bind(cur, sid, tid_hold, by[tid_hold], hold_id)
    effects = n_effects(cur, sid)
    word = advance(cur, sid)
    st_noop, _, _ = fold_of(cur, sid, tid_noop)
    st_arch, _, _ = fold_of(cur, sid, tid_arch)
    st_hold, _, _ = fold_of(cur, sid, tid_hold)
    sel = q1(
        cur,
        "SELECT count(*) FROM effects WHERE session_id=%s AND request::text LIKE %s",
        (sid, "%selected_todo%"))
    check("bound_scan_past_noop", st_arch == "done" and st_noop == "runnable", (st_arch, st_noop))
    check("non_harness_not_archive_pair", st_noop == "runnable", st_noop)
    check(
        "archive_skips_inflight_waiting",
        word == "terminal" and sel == 0 and n_effects(cur, sid) == effects and st_hold == "runnable",
        (word, sel, effects, n_effects(cur, sid), st_hold))

    tid = u()
    text = "fail me"
    sid, ids = seed(cur, [(tid, text, "advancement_task", "runnable")])
    eid = enqueue(cur, sid, "llm", {"route": {"action": "llm", "reason": "old"}})
    settle(cur, eid, {"text": "no"})
    cur.execute("UPDATE effects SET status='failed' WHERE effect_id=%s", (eid,))
    bind(cur, sid, ids[0], text, eid)
    plans = plan_n(cur, sid)
    advance(cur, sid)
    status, _, quarantine = fold_of(cur, sid, ids[0])
    check(
        "isolate_runnable_failed",
        status == "blocked" and quarantine == {"cleared": False, "effect_id": eid}
        and plan_n(cur, sid) == plans + 1,
        (status, quarantine, plan_n(cur, sid), plans))
    plans = plan_n(cur, sid)
    advance(cur, sid)
    check("isolate_skips_uncleared", plan_n(cur, sid) == plans, plan_n(cur, sid))

    tid = u()
    text = "stay blocked"
    sid, ids = seed(cur, [(tid, text, "advancement_task", "runnable")])
    eid = enqueue(cur, sid, "llm", {"route": {"action": "llm", "reason": "old"}})
    settle(cur, eid, {"text": "no"})
    cur.execute("UPDATE effects SET status='cancelled' WHERE effect_id=%s", (eid,))
    bind(cur, sid, ids[0], text, eid)
    writer(cur, sid, {
        "schema_version": 1,
        "call_kind": "todo_delta",
        "verb": "update",
        "todo_id": ids[0],
        "status_from": "runnable",
        "status_to": "blocked",
        "binding": None,
        "due": None,
        "quarantine": None,
        "text_hash": sha(text),
        "link": None,
    })
    plans = plan_n(cur, sid)
    advance(cur, sid)
    status, _, quarantine = fold_of(cur, sid, ids[0])
    check(
        "isolate_blocked_same_status",
        status == "blocked" and quarantine == {"cleared": False, "effect_id": eid}
        and plan_n(cur, sid) == plans + 1,
        (status, quarantine))

    tid = u()
    text = "stay pending"
    sid, ids = seed(cur, [(tid, text, "advancement_task", "pending")])
    eid = enqueue(cur, sid, "llm", {"route": {"action": "llm", "reason": "old"}})
    settle(cur, eid, {"text": "no"})
    cur.execute("UPDATE effects SET status='failed' WHERE effect_id=%s", (eid,))
    plan_id = q1(
        cur,
        "SELECT payload->>'plan_id' FROM events WHERE session_id=%s AND type='plan/committed'",
        (sid,))
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'todo/delta', %s::jsonb)",
        (sid, u(), json.dumps({
            "apply_id": u(),
            "call_kind": "todo_delta",
            "canonical": {
                "schema_version": 1,
                "call_kind": "todo_delta",
                "verb": "update",
                "todo_id": ids[0],
                "status_from": "pending",
                "status_to": "pending",
                "binding": {"effect_id": eid, "child_session_id": None},
                "due": None,
                "quarantine": None,
                "text_hash": sha(text),
                "link": None,
            },
            "plan_id": plan_id,
            "todo_id": ids[0],
        })))
    plans = plan_n(cur, sid)
    advance(cur, sid)
    status, _, quarantine = fold_of(cur, sid, ids[0])
    check(
        "isolate_pending_same_status",
        status == "pending" and quarantine == {"cleared": False, "effect_id": eid}
        and plan_n(cur, sid) == plans + 1,
        (status, quarantine, plan_n(cur, sid), plans))

    tid = u()
    text = "watch fail"
    due = "2020-01-01T00:00:00Z"
    sid, ids = seed(cur, [(tid, text, "continuous_monitor", "waiting", "add_new", due)])
    promote_monitor(cur, sid, ids[0], text)
    eid = enqueue(cur, sid, "llm", {"route": {"action": "llm", "reason": "old"}})
    settle(cur, eid, {"text": "no"})
    cur.execute("UPDATE effects SET status='failed' WHERE effect_id=%s", (eid,))
    bind(cur, sid, ids[0], text, eid)
    plans = plan_n(cur, sid)
    advance(cur, sid)
    status, due_now, quarantine = fold_of(cur, sid, ids[0])
    check(
        "isolate_monitor_failed",
        status == "blocked" and quarantine == {"cleared": False, "effect_id": eid}
        and due_now == due and plan_n(cur, sid) == plans + 1,
        (status, due_now, quarantine))

    tid = u()
    text = "watch ok"
    sid, ids = seed(cur, [(tid, text, "continuous_monitor", "waiting", "add_new", due)])
    promote_monitor(cur, sid, ids[0], text)
    eid = enqueue(cur, sid, "tool", harness_req(cur, sid), "harness_turn")
    settle(cur, eid, PROGRESS)
    bind(cur, sid, ids[0], text, eid)
    plans = plan_n(cur, sid)
    advance(cur, sid)
    status, due_now, quarantine = fold_of(cur, sid, ids[0])
    check(
        "monitor_success_writes_nothing",
        status == "runnable" and due_now == due and quarantine is None and plan_n(cur, sid) == plans,
        (status, due_now, quarantine, plan_n(cur, sid), plans))

    tid = u()
    text = "already done"
    sid, ids = seed(cur, [(tid, text, "advancement_task", "runnable")])
    eid = enqueue(cur, sid, "llm", {"route": {"action": "llm", "reason": "old"}})
    settle(cur, eid, {"text": "no"})
    bind(cur, sid, ids[0], text, eid)
    writer(cur, sid, {
        "schema_version": 1,
        "call_kind": "todo_delta",
        "verb": "update",
        "todo_id": ids[0],
        "status_from": "runnable",
        "status_to": "done",
        "binding": None,
        "due": None,
        "quarantine": None,
        "text_hash": sha(text),
        "link": None,
    })
    cur.execute("UPDATE effects SET status='failed' WHERE effect_id=%s", (eid,))
    plans = plan_n(cur, sid)
    advance(cur, sid)
    status, _, quarantine = fold_of(cur, sid, ids[0])
    check(
        "isolate_skips_done",
        status == "done" and quarantine is None and plan_n(cur, sid) == plans,
        (status, quarantine, plan_n(cur, sid), plans))

    done_id, live_id = u(), u()
    sid, ids = seed(cur, [
        (done_id, "old excerpt", "advancement_task", "runnable"),
        (live_id, "new excerpt", "advancement_task", "runnable"),
    ])
    writer(cur, sid, {
        "schema_version": 1,
        "call_kind": "todo_delta",
        "verb": "update",
        "todo_id": done_id,
        "status_from": "runnable",
        "status_to": "done",
        "binding": None,
        "due": None,
        "quarantine": None,
        "text_hash": sha("old excerpt"),
        "link": None,
    })
    spawned = as_obj(q1(
        cur,
        "SELECT v13_spawn_subsession(%s, %s::jsonb)",
        (sid, json.dumps({
            "schema_version": 1,
            "children": [
                {"tool_call_id": "old", "task": "old"},
                {"tool_call_id": "new", "task": "new"},
            ],
        }))))
    by_call = {row["tool_call_id"]: row["session_id"] for row in spawned["children"]}
    old_child, new_child = by_call["old"], by_call["new"]
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'workflow/pointer', %s::jsonb)",
        (old_child, u(), json.dumps({
            "schema_version": 1, "parent_session_id": sid, "root_session_id": sid,
            "todo_id": done_id, "up_to_seq": 0,
        })))
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'fixture/pad', %s::jsonb)",
        (new_child, u(), json.dumps({"n": 1})))
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'workflow/pointer', %s::jsonb)",
        (new_child, u(), json.dumps({
            "schema_version": 1, "parent_session_id": sid, "root_session_id": sid,
            "todo_id": live_id, "up_to_seq": 0,
        })))
    insert_effect(cur, old_child, u(), "tool", "succeeded", {"excerpt": "old"}, "read_file_py")
    insert_effect(cur, new_child, u(), "tool", "succeeded", {"excerpt": "new"}, "read_file_py")
    effects = n_effects(cur, sid)
    word = advance(cur, sid)
    status, _, _ = fold_of(cur, sid, live_id)
    check(
        "child_excerpt_skips_historical_pointer",
        word == "waiting" and status == "done" and n_effects(cur, sid) == effects,
        (word, status, effects, n_effects(cur, sid)))

    small, large = sorted((u(), u()))
    sid, ids = seed(cur, [
        (small, "bound child", "advancement_task", "runnable"),
        (large, "free", "advancement_task", "runnable"),
    ])
    child = open_session(cur, "completed")
    bind_child(cur, sid, small, "bound child", child)
    word = advance(cur, sid)
    picked = q1(
        cur,
        "SELECT request->>'todo_id' FROM effects WHERE session_id=%s AND request::text LIKE %s",
        (sid, "%selected_todo%"))
    check("selector_excludes_terminal_child", word == "waiting" and picked == large, (word, picked, large))
    for child_status in ("failed", "cancelled", "ready"):
        tid = u()
        text = "only " + child_status
        sid, ids = seed(cur, [(tid, text, "advancement_task", "runnable")])
        child = open_session(cur, child_status)
        bind_child(cur, sid, ids[0], text, child)
        nsel = q1(cur, "SELECT count(*) FROM v13_selected_todo(%s)", (sid,))
        check("selector_excludes_terminal_child", nsel == 0, (child_status, nsel))


def r0_fixture(cur, result=None, stopped=False, human_status="ready"):
    sid = fresh(cur)
    q1(cur, "SELECT v13_submit_override(%s,%s::jsonb)", (sid, json.dumps({
        "schema_version": 1, "intent": "direct", "reason": "", "source_principal": "operator"})))
    eid = enqueue(cur, sid, "tool", harness_req(cur, sid), "harness_turn")
    settle(cur, eid, PROGRESS if result is None else result)
    if stopped:
        q1(cur, "SELECT v13_goal_stop(%s,%s)", (sid, "r0"))
    hid = enqueue(cur, sid, "human", {"schema_version": 1, "interaction_ref": "r0-" + u()})
    if human_status == "claimed":
        cur.execute("UPDATE effects SET status='claimed', lease_owner='r0', "
                    "lease_until='infinity' WHERE effect_id=%s", (hid,))
    return sid, eid, hid


def r0_spent(cur, eid):
    return q1(cur, "SELECT count(*) FROM events WHERE source_effect_id=%s "
              "AND type='turn/material_spent'", (eid,))


def r0_effect_state(cur):
    return q1(cur, "SELECT coalesce(jsonb_agg(to_jsonb(e) ORDER BY effect_id), '[]'::jsonb) FROM effects e")


def r0_attempt(cur, sid, eid, expected, label):
    effects0 = r0_effect_state(cur)
    seq0 = max_seq(cur, sid)
    queue0 = q1(cur, "SELECT count(*) FROM pgmq.q_v13_work")
    spent0 = r0_spent(cur, eid)
    word = advance(cur, sid, include_failed=False)
    cur.execute("SELECT type, source_effect_id::text, payload FROM events "
                "WHERE session_id=%s AND seq>%s ORDER BY seq", (sid, seq0))
    extra = cur.fetchall()
    expected_events = [] if not expected else [(
        "turn/material_spent", eid, {"schema_version": 1, "effect_id": eid})]
    check(label, word == "waiting" and r0_spent(cur, eid) == spent0 + expected
          and extra == expected_events and r0_effect_state(cur) == effects0
          and q1(cur, "SELECT count(*) FROM pgmq.q_v13_work") == queue0,
          (word, r0_spent(cur, eid) - spent0, extra))


def r0_direct_cases(cur):
    for result in (PROGRESS, FINISH):
        for status in ("ready", "claimed"):
            cur.execute("SAVEPOINT r0_case")
            try:
                sid, eid, hid = r0_fixture(cur, result, human_status=status)
                r0_attempt(cur, sid, eid, 1, "r0_root_human_" + status + "_receipt")
                r0_attempt(cur, sid, eid, 0, "r0_idempotent_same_source")
                check("r0_no_dispatch", q1(cur, "SELECT status FROM effects WHERE effect_id=%s", (hid,)) == status
                      and q1(cur, "SELECT status FROM sessions WHERE session_id=%s", (sid,)) == "waiting")
            finally:
                cur.execute("ROLLBACK TO SAVEPOINT r0_case")
    for stopped in (True, False):
        for value in (False, 0, "", "bad", None, "MISSING"):
            cur.execute("SAVEPOINT r0_failed")
            try:
                sid, eid, _ = r0_fixture(cur, stopped=stopped)
                if value != "MISSING":
                    cur.execute("UPDATE effects SET result=result || %s::jsonb WHERE effect_id=%s",
                                (json.dumps({"failed": value}), eid))
                expected = int(not stopped or value is None or value == "MISSING")
                r0_attempt(cur, sid, eid, expected,
                           "r0_stopped_failed_direct" if stopped else "r0_running_failed_direct")
            finally:
                cur.execute("ROLLBACK TO SAVEPOINT r0_failed")
    negatives = (None, [], 7, "scalar", {"result_kind": "wait"}, {"result_kind": "reject"},
                 {"result_kind": "progress", "signals": None},
                 {"result_kind": "progress", "signals": 7},
                 {"result_kind": "progress", "signals": {}},
                 {"result_kind": "progress", "signals": [1]},
                 {"result_kind": "progress", "signals": ["repair/required"]})
    for value in negatives:
        cur.execute("SAVEPOINT r0_invalid")
        try:
            sid, eid, _ = r0_fixture(cur)
            cur.execute("UPDATE effects SET result=%s::jsonb WHERE effect_id=%s", (json.dumps(value), eid))
            r0_attempt(cur, sid, eid, 0, "r0_signals_mismatch_waits")
        finally:
            cur.execute("ROLLBACK TO SAVEPOINT r0_invalid")
    for change in ("old_origin", "non_harness", "bad_request", "ready", "claimed", "failed", "other_session"):
        cur.execute("SAVEPOINT r0_pred")
        try:
            sid, eid, hid = r0_fixture(cur)
            if change in ("ready", "claimed"):
                # Preserve the single-active index: make the human inactive, then
                # make the current harness predecessor itself the blocking row.
                cur.execute("UPDATE effects SET status='succeeded' WHERE effect_id=%s", (hid,))
                cur.execute("UPDATE effects SET status=%s WHERE effect_id=%s", (change, eid))
            elif change == "old_origin":
                prefix(cur, sid, "new user turn")
            elif change == "non_harness":
                cur.execute("UPDATE effects SET tool_name='read_file_py' WHERE effect_id=%s", (eid,))
            elif change == "bad_request":
                cur.execute("UPDATE effects SET request=request || '{\"extra\":true}'::jsonb WHERE effect_id=%s", (eid,))
            elif change == "other_session":
                other = fresh(cur)
                cur.execute("UPDATE effects SET session_id=%s WHERE effect_id=%s", (other, eid))
            else:
                cur.execute("UPDATE effects SET status=%s WHERE effect_id=%s", (change, eid))
            if change in ("ready", "claimed"):
                cur.execute("SELECT effect_id::text, status FROM effects WHERE session_id=%s "
                            "AND status IN ('ready','claimed')", (sid,))
                check("r0_active_predecessor_is_blocker", cur.fetchall() == [(eid, change)]
                      and str(q1(cur, "SELECT v13_harness_predecessor(%s)", (sid,))) == eid)
            r0_attempt(cur, sid, eid, 0, "r0_current_predecessor_only")
        finally:
            cur.execute("ROLLBACK TO SAVEPOINT r0_pred")
    cur.execute("SAVEPOINT r0_signal_event")
    try:
        sid, eid, _ = r0_fixture(cur, {"result_kind": "progress", "signals": ["replan/required"]})
        cur.execute("UPDATE effects SET result='{}'::jsonb || %s::jsonb WHERE effect_id=%s", (json.dumps(PROGRESS), eid))
        r0_attempt(cur, sid, eid, 0, "r0_signals_event_mismatch_waits")
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT r0_signal_event")
    cur.execute("SAVEPOINT r0_collision")
    try:
        sid, first, hid = r0_fixture(cur)
        r0_attempt(cur, sid, first, 1, "r0_direct_advance_receipt")
        cur.execute("UPDATE effects SET status='succeeded' WHERE effect_id=%s", (hid,))
        req = q1(cur, "SELECT request FROM effects WHERE effect_id=%s", (first,))
        req["continuation_index"] = 1
        second = enqueue(cur, sid, "tool", req, "harness_turn")
        settle(cur, second, PROGRESS)
        enqueue(cur, sid, "human", {"schema_version": 1, "interaction_ref": "collision-" + u()})
        r0_attempt(cur, sid, second, 0, "r0_material_collision_waits")
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT r0_collision")
    cur.execute("SAVEPOINT r0_two_unpaid")
    try:
        sid, first, hid = r0_fixture(cur)
        cur.execute("UPDATE effects SET status='succeeded' WHERE effect_id=%s", (hid,))
        second = enqueue(cur, sid, "tool", harness_req(cur, sid), "harness_turn")
        settle(cur, second, PROGRESS)
        enqueue(cur, sid, "human", {"schema_version": 1, "interaction_ref": "two-" + u()})
        winner = str(q1(cur, "SELECT v13_harness_predecessor(%s)", (sid,)))
        r0_attempt(cur, sid, winner, 1, "r0_current_predecessor_only")
        loser = first if winner == second else second
        check("r0_old_unpaid_not_selected", r0_spent(cur, loser) == 0)
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT r0_two_unpaid")


def r0_preceding_walls(cur):
    for wall in ("unknown", "cancel", "terminal", "stale"):
        cur.execute("SAVEPOINT r0_wall")
        try:
            sid, eid, hid = r0_fixture(cur, human_status="claimed")
            if wall == "unknown":
                cur.execute("UPDATE effects SET status='unknown' WHERE effect_id=%s", (hid,))
                cur.execute("UPDATE sessions SET status='blocked_unknown' WHERE session_id=%s", (sid,))
            elif wall == "cancel":
                q1(cur, "SELECT v13_cancel(%s)", (sid,))
            elif wall == "terminal":
                cur.execute("UPDATE sessions SET status='completed' WHERE session_id=%s", (sid,))
            snap = snap_of(cur, sid, include_failed=False)
            if wall == "stale":
                snap["snap"]["max_event_seq"] = -1
            word = q1(cur, "SELECT v13_advance(%s,%s::jsonb)", (sid, json.dumps(snap)))
            expected = {"unknown": "waiting", "cancel": "waiting", "terminal": "terminal", "stale": "stale"}[wall]
            check("r0_unknown_cancel_terminal_stale_unchanged", word == expected and r0_spent(cur, eid) == 0,
                  (wall, word, r0_spent(cur, eid)))
        finally:
            cur.execute("ROLLBACK TO SAVEPOINT r0_wall")
    print("[r0 advance hash]", fn_hash(cur, "public.v13_advance(uuid,jsonb)"))
    src = q1(cur, "SELECT pg_get_functiondef('public.v13_material_spent_guard()'::regprocedure)")
    check("r0_receipt_guard_no_dispatch", "v13_send_work" not in src and "v13_enqueue_effect" not in src
          and "INSERT" not in src and "UPDATE effects" not in src)


def r0_quota_boundary(cur):
    """Real receipts in committed transactions, followed by a legal human response."""
    original = q1(cur, "SELECT value FROM v13_policies WHERE name='quota_window' AND active")
    original_version = q1(cur, "SELECT version FROM v13_policies WHERE name='quota_window' AND active")
    try:
        for allowed in (1, 1000000):
            sid, eid, hid = r0_fixture(cur)
            tid = u()
            writer(cur, sid, plan_body([todo(tid, "quota-bound", "advancement_task", "runnable")], max_seq(cur, sid)))
            next_version = q1(cur, "SELECT max(version)+1 FROM v13_policies WHERE name='quota_window'")
            cur.execute("UPDATE v13_policies SET active=false WHERE name='quota_window' AND active")
            cur.execute("INSERT INTO v13_policies(name,version,value,active) VALUES ('quota_window',%s,%s::jsonb,true)",
                        (next_version, json.dumps(dict(original, allowed=allowed))))
            cur.connection.commit()
            before = q1(cur, "SELECT v13_quota_eligible(%s)", (sid,))
            r0_attempt(cur, sid, eid, 1, "r0_quota_time_honesty")
            cur.connection.commit()
            after = q1(cur, "SELECT v13_quota_eligible(%s)", (sid,))
            ref = q1(cur, "SELECT request->>'interaction_ref' FROM effects WHERE effect_id=%s", (hid,))
            word = settle(cur, hid, {"schema_version": 1, "interaction_ref": ref, "response": "approved by fixture operator"})
            check("r0_quota_human_legally_completed", word == "accepted"
                  and q1(cur, "SELECT status FROM effects WHERE effect_id=%s", (hid,)) == "succeeded", word)
            cur.connection.commit()
            eff0, plans0 = n_effects(cur, sid), plan_n(cur, sid)
            routes0 = q1(cur, "SELECT count(*) FROM events WHERE session_id=%s AND type='turn/route'", (sid,))
            gate = q1(cur, "SELECT v13_should_run_gate(%s)", (sid,))
            should = q1(cur, "SELECT v13_should_run(%s)", (sid,))
            result = advance(cur, sid, include_failed=False)
            if allowed == 1:
                check("r0_next_turn_quota_boundary", before is True and after is False and should is False
                      and gate == "quota_window" and n_effects(cur, sid) == eff0
                      and plan_n(cur, sid) == plans0 and r0_spent(cur, eid) == 1
                      and q1(cur, "SELECT count(*) FROM events WHERE session_id=%s AND type='turn/route'", (sid,)) == routes0,
                      (allowed, before, after, gate, result))
            else:
                check("r0_next_turn_quota_control", before is True and after is True and should is True
                      and n_effects(cur, sid) == eff0 + 1 and plan_n(cur, sid) == plans0 + 1
                      and r0_spent(cur, eid) == 1,
                      (allowed, gate, result, eff0, n_effects(cur, sid)))
            cur.connection.commit()
    finally:
        cur.connection.rollback()
        cur.execute("UPDATE v13_policies SET active=false WHERE name='quota_window' AND active")
        cur.execute("UPDATE v13_policies SET active=true WHERE name='quota_window' AND version=%s", (original_version,))
        cur.connection.commit()


def run(cur, server):
    before = (
        fn_hash(cur, "public.v13_recover_idle()"),
        fn_hash(cur, "public.v13_goal_fingerprint(uuid)"),
    )
    load_arm(server)
    test_hashes_and_source(cur, before)
    test_stage_bytes()
    test_live_arms_runtime(cur)
    test_no_plan(cur)
    test_live_stop_and_receipt(cur)
    test_dispatch_and_bind(cur)
    test_archive_and_child(cur)
    test_reenable(cur)
    test_p1_fixes(cur)
    r0_direct_cases(cur)
    r0_preceding_walls(cur)
    cur.execute("COMMIT")
    r0_quota_boundary(cur)


def main() -> int:
    print("[db]", DB)
    if setup_db() != 0:
        return 1
    server = get_server()
    conn = connect(server)
    try:
        run(conn.cursor(), server)
    finally:
        conn.close()
        if setup_mod.CREATED:
            run_psql(server, "postgres", f'DROP DATABASE "{DB}" WITH (FORCE);')
            setup_mod.CREATED = False
            print("[dropped]", DB)
    print(f"[ok] {N} checks")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[FAIL] {exc}")
        if setup_mod.CREATED:
            try:
                run_psql(get_server(), "postgres", f'DROP DATABASE "{DB}" WITH (FORCE);')
                print("[dropped]", DB)
            except Exception as drop_exc:
                print("[cleanup-fail]", drop_exc)
        raise SystemExit(1)
