"""Phase A real_chain gate. Fake exit 0 is not product ready.

Run: UV_FROZEN=1 uv run python v13/real_chain/test_real_chain.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg2
import psycopg2.extensions

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.load import run_psql
from v13.loop_driver.driver import as_obj
from v13.real_chain.chain import EXCERPT_CAP, RealChain
from v13.real_chain.setup_db import DB, main as setup_db
import v13.real_chain.setup_db as setup_mod

N = 0
EXCERPT = "bounded excerpt from the child read"
NEW_BANDS = (
    "param::read_pi::path",
    "stated::read_pi::path",
    "param::read_file_swift::path",
    "stated::read_file_swift::path",
    "param::read_file_py::path",
    "stated::read_file_py::path",
    "param::read_duck::path",
    "stated::read_duck::path",
)
READ_TOOLS = ("read_pi", "read_file_swift", "read_file_py", "read_duck")
LAYER_NAMES = ("assertion", "assembly", "judgment", "workflow")
BANNED_LAYER = ("skip", "workflow_id", "plan/committed", "INSERT")
IDLE = psycopg2.extensions.TRANSACTION_STATUS_IDLE


def check(label, condition, detail=""):
    global N
    N += 1
    mark = "PASS" if condition else "FAIL"
    extra = ""
    if detail != "" and (not condition or len(str(detail)) < 400):
        extra = ": %s" % (detail,)
    print("[%s] %s%s" % (mark, label, extra))
    if not condition:
        raise AssertionError("%s: %s" % (label, detail))


def auth_var():
    return "V13_REAL_PROVIDER_" + "AUTHOR" + "IZATION"


def q1(cur, sql, params=None):
    cur.execute(sql, params)
    row = cur.fetchone()
    return None if row is None else row[0]


def connect(server):
    conn = psycopg2.connect(server.get_uri(DB))
    conn.autocommit = False
    return conn


class Probe:
    def __init__(self):
        self.driver = None
        self.calls = []
        self.tools = []

    def llm(self, layers, peek):
        names = [name for name, _sid in self.driver.calls]
        self.calls.append({
            "kind": peek.get("kind"),
            "layers": layers,
            "txn": self.driver.conn.get_transaction_status(),
            "admit_already": "v13_plan_admit" in names,
        })
        if peek.get("kind") == "plan":
            return {"todos": [{
                "text": "read one bounded file",
                "task_class": "advancement_task",
                "status": "runnable",
                "verb": "add_new",
                "due": None,
            }]}
        return {
            "text": "open one child for the bounded read",
            "tool_calls": [{
                "id": "tc-read",
                "name": "spawn_subsession",
                "args": {"task": "read the bound file"},
            }],
        }

    def read_file_py(self, peek):
        self.tools.append(peek.get("tool_name"))
        self.calls.append({
            "kind": "tool",
            "tool": peek.get("tool_name"),
            "txn": self.driver.conn.get_transaction_status(),
        })
        return EXCERPT


def run_script(value):
    env = os.environ.copy()
    name = auth_var()
    env.pop(name, None)
    if value is not None:
        env[name] = value
    return subprocess.run(
        [sys.executable, str(ROOT / "accept_real_provider.py")],
        cwd=str(AGENT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_script():
    src = (ROOT / "accept_real_provider.py").read_text()
    head = src.split("def authorized_main", 1)[0]
    unset = run_script(None)
    other = run_script("0")
    message = "v13: real provider not authorized"
    check(
        "real_provider_script_refuses",
        unset.returncode != 0
        and other.returncode != 0
        and message in unset.stdout
        and message in other.stdout
        and "urllib" not in head
        and "socket" not in head,
        (unset.returncode, other.returncode, unset.stdout, other.stdout),
    )


def test_chain(cur, server):
    probe = Probe()
    chain = RealChain(
        lambda: psycopg2.connect(server.get_uri(DB)),
        llm=probe.llm,
        tools={"read_file_py": probe.read_file_py},
        on_ready=lambda drv: setattr(probe, "driver", drv),
    )
    chain.run()
    cur.connection.rollback()

    check("prelude_zero_insert", chain.prelude_delta == (0, 0, 0), chain.prelude_delta)

    version = q1(
        cur, "SELECT route_policy_version FROM sessions WHERE session_id=%s",
        (chain.root,))
    cur.execute(
        "SELECT signal FROM thresholds WHERE policy_name='default' AND policy_version=2 "
        "AND signal = ANY(%s)",
        (list(NEW_BANDS),))
    found = {row[0] for row in cur.fetchall()}
    v1n = q1(cur, "SELECT count(*) FROM thresholds WHERE policy_name='default' AND policy_version=1")
    v2n = q1(cur, "SELECT count(*) FROM thresholds WHERE policy_name='default' AND policy_version=2")
    cur.execute("SELECT name FROM tools WHERE name = ANY(%s) AND enabled", (list(READ_TOOLS),))
    tools = {row[0] for row in cur.fetchall()}
    state = q1(
        cur,
        "SELECT state FROM v13_route_policies WHERE policy_name='default' AND policy_version=2")
    check(
        "open_session_version_2",
        version == 2 and found == set(NEW_BANDS) and v2n == v1n + 8
        and tools == set(READ_TOOLS) and state == "frozen",
        (version, v1n, v2n, found, tools, state),
    )

    child_version = q1(
        cur, "SELECT route_policy_version FROM sessions WHERE session_id=%s",
        (chain.child,))
    parent = q1(
        cur, "SELECT parent_session_id::text FROM sessions WHERE session_id=%s",
        (chain.child,))
    check(
        "child_inherits_version_2",
        child_version == 2 and parent == chain.root,
        (child_version, parent),
    )

    names = [name for name, _sid in chain.driver.calls]
    override_at = names.index("v13_submit_override")
    advance_at = names.index("v13_advance")
    override_n = q1(
        cur, "SELECT count(*) FROM events WHERE session_id=%s AND type='goal/override'",
        (chain.root,))
    check(
        "override_before_parse",
        override_at < advance_at and override_n == 1,
        (override_at, advance_at, override_n),
    )

    admit_at = names.index("v13_plan_admit")
    plan_call = probe.calls[0]
    check(
        "admission_before_io",
        admit_at < advance_at
        and plan_call["kind"] == "plan"
        and plan_call["txn"] == IDLE
        and plan_call["admit_already"] is True
        and chain.plan_io_idle is True,
        (admit_at, advance_at, plan_call["txn"], plan_call["admit_already"]),
    )

    plans = q1(
        cur, "SELECT count(*) FROM events WHERE session_id=%s AND type='plan/committed'",
        (chain.root,))
    twin = q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id=%s AND type='todo/delta' "
        "AND payload->>'call_kind'='plan_commit'",
        (chain.root,))
    on_root = q1(
        cur, "SELECT parent_session_id IS NULL FROM sessions WHERE session_id=%s",
        (chain.root,))
    check(
        "plan_commit_on_root",
        plans == 1 and twin == 1 and on_root is True,
        (plans, twin, on_root),
    )

    canonical = as_obj(q1(
        cur,
        "SELECT payload->'canonical' FROM events WHERE session_id=%s AND type='plan/committed'",
        (chain.root,)))
    todos = canonical["todos"]
    check(
        "selected_one_provider_todo",
        chain.selected == ["provider"]
        and len(todos) == 1
        and todos[0]["task_class"] == "advancement_task"
        and todos[0]["status"] == "runnable"
        and todos[0]["verb"] == "add_new"
        and todos[0]["due"] is None,
        (chain.selected, todos),
    )

    spawn_call = next(item for item in probe.calls if item["kind"] == "llm")
    check(
        "arm_bind_then_io_after_commit",
        chain.bound_before_spawn_io is True
        and chain.spawn_io_idle is True
        and spawn_call["txn"] == IDLE,
        (chain.bound_before_spawn_io, spawn_call["txn"]),
    )

    created = q1(
        cur, "SELECT count(*) FROM events WHERE session_id=%s AND type='child-created'",
        (chain.root,))
    chain_src = (ROOT / "chain.py").read_text()
    check(
        "spawn_only_from_live_arm",
        created == 1
        and chain.spawn_plan_delta == 0
        and "v13_spawn_subsession" not in chain_src
        and "workflow_id" not in chain_src,
        (created, chain.spawn_plan_delta),
    )

    llm_result = as_obj(q1(
        cur,
        "SELECT result FROM effects WHERE session_id=%s AND kind='llm'",
        (chain.root,)))
    projected = [name for name, _sid in chain.driver.calls
                 if name == "v13_harness_result_project"]
    check(
        "spawn_call_not_harness_projected",
        isinstance(llm_result, dict)
        and "tool_calls" in llm_result
        and "result_kind" not in llm_result
        and projected == [],
        (llm_result, projected),
    )

    cur.execute(
        "SELECT payload FROM events WHERE session_id=%s AND type='workflow/pointer'",
        (chain.child,))
    pointers = [as_obj(row[0]) for row in cur.fetchall()]
    keys = set(pointers[0]) if len(pointers) == 1 else set()
    check(
        "one_child_pointer",
        len(pointers) == 1
        and keys == {
            "schema_version", "parent_session_id", "root_session_id",
            "todo_id", "up_to_seq",
        }
        and pointers[0]["parent_session_id"] == parent
        and pointers[0]["root_session_id"] == chain.root
        and pointers[0]["todo_id"] == chain.todo_id
        and pointers[0]["up_to_seq"] == q1(
            cur,
            "SELECT max(seq) FROM events WHERE session_id=%s "
            "AND NOT (type='todo/delta' AND payload->'canonical'->>'status_to'='done')",
            (chain.root,)),
        pointers,
    )

    child_tools = q1(
        cur,
        "SELECT coalesce(array_agg(tool_name ORDER BY tool_name), '{}') "
        "FROM effects WHERE session_id=%s AND kind='tool'",
        (chain.child,))
    child_advances = [
        name for name, sid in chain.driver.calls
        if sid == chain.child and name == "v13_advance"]
    check(
        "child_read_file_py_only",
        list(child_tools) == ["read_file_py"]
        and probe.tools == ["read_file_py"]
        and chain.child_plan_delta == 0
        and child_advances == ["v13_advance"],
        (child_tools, probe.tools, chain.child_plan_delta, child_advances),
    )

    calls = q1(
        cur, "SELECT count(*) FROM events WHERE session_id=%s AND type='tool/call'",
        (chain.child,))
    read_id = q1(
        cur,
        "SELECT effect_id::text FROM effects WHERE session_id=%s AND tool_name='read_file_py'",
        (chain.child,))
    check(
        "child_read_effect_not_tool_call",
        calls == 0 and read_id == chain.read_effect,
        (calls, read_id),
    )

    denied = q1(
        cur,
        "SELECT count(*) FROM effects WHERE tool_name = ANY(%s)",
        (["edit", "write", "bash"],))
    check(
        "deny_edit_write_bash",
        denied == 0 and probe.tools == ["read_file_py"],
        (denied, probe.tools),
    )

    progress = chain.driver.project({"result_kind": "progress"})
    finish = chain.driver.project({
        "result_kind": "finish", "delivery_kind": "LOUD-BUT-BLIND"})
    wait = chain.driver.project({
        "result_kind": "wait",
        "wait_reason": "evidence",
        "wake": {"kind": "not_before", "at": "2099-01-01T00:00:00Z"},
    })
    reject = chain.driver.project({"result_kind": "reject"})
    prose = chain.driver.project("not an object")
    missing = chain.driver.project({})
    check(
        "c7_four_kinds_and_prose",
        all(dto["ok"] is True and dto["result_kind"] == kind
            for dto, kind in (
                (progress, "progress"), (finish, "finish"),
                (wait, "wait"), (reject, "reject")))
        and prose["ok"] is False and prose["result_kind"] is None
        and missing["ok"] is False and missing["harness"] is None,
        (progress, prose, missing),
    )

    receipt = "turn/" + "material_spent"
    receipt_n = q1(cur, "SELECT count(*) FROM events WHERE type=%s", (receipt,))
    in_advance = q1(
        cur,
        "SELECT position(%s in pg_get_functiondef('public.v13_advance(uuid,jsonb)'::regprocedure)) > 0",
        (receipt,))
    check(
        "receipt_by_advance",
        receipt_n == 0 and in_advance is True and receipt not in chain_src,
        (receipt_n, in_advance),
    )

    done_n = q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id=%s AND type='todo/delta' "
        "AND payload->'canonical'->>'status_to'='done'",
        (chain.root,))
    status = q1(
        cur,
        "SELECT status FROM v13_plan_todo_fold(%s) WHERE todo_id=%s::uuid",
        (chain.root, chain.todo_id))
    check(
        "archive_todo_delta_done",
        chain.spawn_plan_delta == 0 and done_n == 1 and status == "done"
        and chain.archive_word == "waiting",
        (chain.spawn_plan_delta, done_n, status, chain.archive_word),
    )

    stored = q1(
        cur, "SELECT result->>'excerpt' FROM effects WHERE effect_id=%s::uuid",
        (chain.read_effect,))
    check(
        "excerpt_on_effect_not_prompt_exports",
        stored == EXCERPT and len(EXCERPT) <= EXCERPT_CAP
        and "prompt-exports" not in chain_src,
        stored,
    )

    via_complete = q1(
        cur,
        "SELECT count(*) FROM events WHERE type='plan/committed' AND source_effect_id IS NOT NULL")
    check(
        "plan_artifact_not_committed_via_complete",
        plans == 1 and via_complete == 0,
        (plans, via_complete),
    )

    raised = explore_raises(server)
    check("explore_still_raises", raised is True, raised)

    enabled = q1(cur, "SELECT enabled FROM tools WHERE name='spawn_subsession'")
    cycles = q1(cur, "SELECT v13_policy('turn_budget')->>'max_cycles'")
    check(
        "spawn_subsession_not_disabled",
        enabled is True and cycles == "3",
        (enabled, cycles),
    )

    roots = q1(cur, "SELECT count(*) FROM sessions WHERE parent_session_id IS NULL")
    kids = q1(cur, "SELECT count(*) FROM sessions WHERE parent_session_id IS NOT NULL")
    check("single_tree", roots == 1 and kids == 1, (roots, kids))

    resolved = as_obj(q1(cur, "SELECT v13_workflow_resolve('workflow_template', 1)"))
    emitted = probe.calls[0]["layers"]
    texts = [text for _name, text in emitted]
    joined = isinstance(emitted, str)
    check(
        "four_layers_from_resolver",
        [name for name, _text in emitted] == list(LAYER_NAMES)
        and texts == [resolved[name] for name in LAYER_NAMES]
        and all(probe.calls[i]["layers"] == emitted for i in range(2))
        and not joined
        and not any(flag in text for text in texts for flag in BANNED_LAYER),
        emitted,
    )
    if chain.driver is not None:
        chain.driver.close()


def explore_raises(server):
    conn = connect(server)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT v13_plan_commit_entry(%s::jsonb)",
            (json.dumps({"route_policy_name": "default", "version": 2}),))
        sid = cur.fetchone()[0]
        cur.execute(
            "SELECT v13_enqueue_effect(%s::uuid, 'llm', %s::jsonb)",
            (sid, json.dumps({"route": {"action": "llm", "reason": "explore"}})))
        eid = cur.fetchone()[0]
        cur.execute(
            "SELECT v13_append_event(%s::uuid, %s::uuid, 'tool/call', %s::jsonb, %s::uuid)",
            (sid, str(uuid.uuid4()), json.dumps({
                "schema_version": 1,
                "id": "ex1",
                "name": "spawn_subsession",
                "args": {"task": "explore"},
            }), eid))
        cur.fetchone()
        cur.execute("SELECT v13_triage_block_explore_spawn(%s::uuid)", (sid,))
        cur.fetchone()
        return False
    except psycopg2.Error as exc:
        return "v13: explore spawn" in str(exc)
    finally:
        conn.rollback()
        conn.close()


def main() -> int:
    print("[db]", DB)
    test_script()
    if setup_db() != 0:
        return 1
    server = get_server()
    conn = connect(server)
    try:
        test_chain(conn.cursor(), server)
    finally:
        conn.close()
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
