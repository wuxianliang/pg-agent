"""First real chain. Calls loop_driver. Does not copy the exit machine.

Production caller of v13_workflow_resolve and v13_child_pointer.
Does not spawn. Does not join the four layers into one line.
"""
from __future__ import annotations

import hashlib
import json
import uuid

import psycopg2.extensions

from v13.loop_driver.driver import (
    LAYER_ORDER,
    PROVIDER_ATTEMPT_CAP,
    LoopDriver,
    as_obj,
)

EXCERPT_CAP = 1024
SPEC = {"route_policy_name": "default", "version": 2}
DENIED = ("edit", "write", "bash")
PLAN_KEYS = {"text", "task_class", "status", "verb", "due", "todo_id"}
SPAWN_CALL_KEYS = {"args", "id", "name"}


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _plan_answer_ok(answer):
    if not isinstance(answer, dict):
        return False
    todos = answer.get("todos")
    if not isinstance(todos, list) or len(todos) != 1 or not isinstance(todos[0], dict):
        return False
    item = todos[0]
    if not {"text", "task_class", "status", "verb", "due"} <= set(item) or not set(item) <= PLAN_KEYS:
        return False
    text = item.get("text")
    if not isinstance(text, str) or text == "" or len(text) > 1024:
        return False
    if item.get("task_class") != "advancement_task" or item.get("status") != "runnable":
        return False
    if item.get("verb") != "add_new" or item.get("due") is not None:
        return False
    if "todo_id" in item and not isinstance(item.get("todo_id"), str):
        return False
    return True


def _spawn_answer_ok(answer):
    if not isinstance(answer, dict) or "result_kind" in answer:
        return False
    text = answer.get("text")
    calls = answer.get("tool_calls")
    if not isinstance(text, str) or not text.strip():
        return False
    if not isinstance(calls, list) or len(calls) != 1 or not isinstance(calls[0], dict):
        return False
    call = calls[0]
    if set(call) != SPAWN_CALL_KEYS or call.get("name") != "spawn_subsession":
        return False
    args = call.get("args")
    task = None if not isinstance(args, dict) else args.get("task")
    ident = call.get("id")
    if not isinstance(args, dict) or set(args) != {"task"}:
        return False
    if not isinstance(task, str) or not 1 <= len(task) <= 1024:
        return False
    if not isinstance(ident, str) or not 1 <= len(ident) <= 128:
        return False
    return True


class RealChain:
    def __init__(self, connect, llm, tools, on_ready=None):
        self._connect = connect
        self.llm = llm
        self.tools = dict(tools or {})
        self.on_ready = on_ready
        self.driver = None
        self.root = None
        self.child = None
        self.todo_id = None
        self.apply_id = None
        self.read_effect = None
        self.layers = None
        self.prelude_delta = None
        self.selected = None
        self.spawn_plan_delta = None
        self.child_plan_delta = None
        self.archive_word = None
        self.plan_io_idle = None
        self.spawn_io_idle = None
        self.read_io_idle = None
        self.bound_before_spawn_io = None
        self.up_to_seq = None

    def run(self):
        self.driver = LoopDriver(
            self._connect, llm=self._guarded_llm, tools=self.tools)
        try:
            return self._run()
        except Exception:
            self.driver.close()
            raise

    def _run(self):
        if self.on_ready is not None:
            self.on_ready(self.driver)
        self.layers = self._resolve_layers()
        self.driver.layers = self.layers
        before = self._counts()
        self.driver.plan_prelude(SPEC)
        after = self._counts()
        self.prelude_delta = tuple(a - b for a, b in zip(after, before))
        self.root = self.driver.plan_commit_entry(SPEC)
        self.driver.submit_override(self.root)
        admitted = self.driver.plan_admit(None, self.root)
        if admitted is not True:
            raise RuntimeError("v13: real chain: admit")
        self.apply_id = str(uuid.uuid4())
        proposal = self._plan_io()
        canonical = self._canonical(proposal)
        self.driver.plan_writer(self.root, self.apply_id, "plan_commit", canonical)
        self.selected = self._selected()
        if self.selected != ["provider"]:
            raise RuntimeError("v13: real chain: selected")
        self.todo_id = self._todo_id()
        word = self.driver.advance(self.root)
        if word != "waiting":
            raise RuntimeError("v13: real chain: arm word %s" % word)
        self.bound_before_spawn_io = self._bound()
        before_plan = self._plan_n(self.root)
        self._assert_idle()
        self.spawn_io_idle = True
        state, _outcome = self.driver.serve(self.root)
        if state != "served":
            raise RuntimeError("v13: real chain: spawn serve %s" % state)
        self.spawn_plan_delta = self._plan_n(self.root) - before_plan
        self.child = self._child()
        self._pointer()
        before_child = self._plan_n(self.child)
        child_word = self.driver.advance(self.child)
        self.child_plan_delta = self._plan_n(self.child) - before_child
        if child_word != "waiting":
            raise RuntimeError("v13: real chain: child word %s" % child_word)
        self._read_once()
        self.archive_word = self._settle_root()
        return self

    def _guarded_llm(self, layers, peek):
        answer = self.llm(layers, peek)
        if peek.get("kind") == "plan":
            return answer
        if not _spawn_answer_ok(answer):
            raise RuntimeError("v13: real chain: spawn shape")
        return answer

    def _resolve_layers(self):
        rows = self.driver._read(
            "SELECT v13_workflow_resolve('workflow_template', 1)", ())
        obj = as_obj(rows[0][0])
        return {name: obj[name] for name in LAYER_ORDER}

    def _plan_io(self):
        proposal = None
        for _ in range(PROVIDER_ATTEMPT_CAP):
            self._assert_idle()
            self.plan_io_idle = True
            answer = self.llm(self.driver.four_layers(), {"kind": "plan"})
            if _plan_answer_ok(answer):
                proposal = answer
                break
            self.driver.attempts_used += 1
        if proposal is None:
            raise RuntimeError("v13: real chain: plan attempts")
        return proposal

    def _canonical(self, proposal):
        seq = self._q1(
            "SELECT max(seq) FROM events WHERE session_id=%s::uuid", (self.root,))
        if seq is None:
            raise RuntimeError("v13: real chain: waterline")
        todos = []
        for item in proposal["todos"]:
            text = item["text"]
            tid = item.get("todo_id") or str(uuid.uuid4())
            todos.append({
                "todo_id": str(tid),
                "text": text,
                "text_hash": text_hash(text),
                "task_class": item["task_class"],
                "status": item["status"],
                "due": item.get("due"),
                "verb": item["verb"],
            })
        todos.sort(key=lambda row: uuid.UUID(row["todo_id"]).bytes)
        return {
            "schema_version": 1,
            "call_kind": "plan_commit",
            "based_on_seq": int(seq),
            "supersedes": None,
            "todos": todos,
        }

    def _selected(self):
        conn = self.driver.connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT dispatch FROM v13_selected_todo(%s::uuid)", (self.root,))
        rows = [row[0] for row in cur.fetchall()]
        conn.commit()
        return rows

    def _todo_id(self):
        return self._q1(
            "SELECT todo_id::text FROM v13_plan_todo_fold(%s::uuid) "
            "WHERE task_class='advancement_task'",
            (self.root,))

    def _bound(self):
        return self._q1(
            "SELECT effect_id IS NOT NULL FROM v13_plan_todo_fold(%s::uuid) "
            "WHERE todo_id=%s::uuid",
            (self.root, self.todo_id))

    def _child(self):
        conn = self.driver.connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT session_id::text FROM sessions WHERE parent_session_id=%s::uuid",
            (self.root,))
        rows = [row[0] for row in cur.fetchall()]
        conn.commit()
        if len(rows) != 1:
            raise RuntimeError("v13: real chain: child count %s" % len(rows))
        return rows[0]

    def _pointer(self):
        parent = self._q1(
            "SELECT parent_session_id::text FROM sessions WHERE session_id=%s::uuid",
            (self.child,))
        root = self._q1(
            "SELECT v13_plan_map_root(%s::uuid)::text", (self.child,))
        todo = self._q1(
            "SELECT todo_id::text FROM v13_plan_todo_fold(%s::uuid) "
            "WHERE task_class='advancement_task' AND effect_id IS NOT NULL",
            (root,))
        up_to = self._q1(
            "SELECT max(seq) FROM events WHERE session_id=%s::uuid", (root,))
        self.up_to_seq = up_to
        self._q1(
            "SELECT v13_child_pointer(%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s)",
            (self.child, parent, root, todo, up_to))

    def _read_once(self):
        row = self._row(
            "SELECT effect_id::text, tool_name, request FROM effects "
            "WHERE session_id=%s::uuid AND tool_name='read_file_py' AND status='ready'",
            (self.child,))
        if row is None:
            raise RuntimeError("v13: real chain: read missing")
        effect_id, tool_name, request = row
        if tool_name in DENIED or tool_name != "read_file_py":
            raise RuntimeError("v13: real chain: denied tool")
        handler = self.tools.get(tool_name)
        if handler is None:
            raise RuntimeError("v13: real chain: no handler")
        self._assert_idle()
        self.read_io_idle = True
        excerpt = handler({
            "effect_id": effect_id,
            "kind": "tool",
            "tool_name": tool_name,
            "request": as_obj(request),
        })
        if not isinstance(excerpt, str) or len(excerpt) > EXCERPT_CAP or excerpt == "":
            raise RuntimeError("v13: real chain: excerpt cap")
        self.read_effect = effect_id
        self._complete_read(effect_id, {"excerpt": excerpt})

    def _complete_read(self, effect_id, result):
        conn = self.driver.connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE effects SET status='claimed', attempt_no=attempt_no+1, "
                "fence=fence+1, lease_owner=%s, "
                "lease_until=clock_timestamp()+interval '1 hour' "
                "WHERE effect_id=%s::uuid AND status='ready' "
                "RETURNING attempt_no, fence",
                (self.driver.worker, effect_id))
            claimed = cur.fetchone()
            if claimed is None:
                conn.rollback()
                raise RuntimeError("v13: real chain: read not ready")
            attempt, fence = claimed
            cur.execute(
                "SELECT v13_complete(%s::uuid, %s, %s, %s, %s::jsonb)",
                (effect_id, attempt, fence, "succeeded", json.dumps(result)))
            outcome = cur.fetchone()[0]
            conn.commit()
            self.driver.calls.append(("v13_complete", self.child))
            return outcome
        except Exception:
            conn.rollback()
            raise

    def _settle_root(self):
        conn = self.driver.connection()
        cur = conn.cursor()
        try:
            word = self.driver._settlement_advance(cur, self.root)
            conn.commit()
            return word
        except Exception:
            conn.rollback()
            raise

    def _assert_idle(self):
        status = self.driver.connection().get_transaction_status()
        if status != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
            raise RuntimeError("v13: real chain: io inside txn")

    def _counts(self):
        return self._row(
            "SELECT (SELECT count(*) FROM sessions), "
            "(SELECT count(*) FROM events), (SELECT count(*) FROM effects)")

    def _plan_n(self, sid):
        return self._q1(
            "SELECT count(*) FROM events WHERE session_id=%s::uuid "
            "AND type IN ('plan/committed', 'todo/delta')",
            (sid,))

    def _q1(self, sql, params=None):
        row = self._row(sql, params)
        return None if row is None else row[0]

    def _row(self, sql, params=None):
        conn = self.driver.connection()
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        conn.commit()
        return row
