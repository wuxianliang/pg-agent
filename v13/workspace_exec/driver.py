"""Workspace tool driver. SQL calls are only the three admit functions."""
from __future__ import annotations

import json
import uuid

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_READ_COMMITTED, TRANSACTION_STATUS_IDLE

from v13.workspace_exec.adapter import Adapter, AmbiguousOutcome, Escape, WorkerFail


def as_obj(value):
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


class Driver:
    def __init__(self, conn, session, root, allowed_roots, adapter=None):
        self.conn = conn
        self.session = session
        self.root = root
        self.allowed_roots = list(allowed_roots)
        self.adapter = adapter
        self.policy = None
        self.adapter_calls = 0
        self.accept_calls = 0

    def load_policy(self):
        cur = self.conn.cursor()
        cur.execute("SELECT v13_workspace_policy()")
        self.policy = as_obj(cur.fetchone()[0])
        self.conn.commit()
        if self.adapter is None:
            self.adapter = Adapter(
                self.root,
                self.policy["bash_verbs"],
                self.policy["result_text_cap_bytes"],
                self.policy["find_depth_cap"],
            )
        return self.policy

    def execute(self, label, request, attempts=1, hooks=None, workspace_root=None,
                allowed_roots=None):
        hooks = hooks or {}
        cap = int(self.policy["tool_open_attempts"])
        n = min(int(attempts), cap)
        used = 0
        last = None
        fixed = "attempt_key" in request
        for _ in range(n):
            used += 1
            req = dict(request)
            req["label"] = label
            if not fixed:
                req["attempt_key"] = str(uuid.uuid4())
            try:
                opened = self._open(label, req, workspace_root, allowed_roots)
            except psycopg2.Error:
                self.conn.rollback()
                raise
            self.conn.commit()
            public = self._public(opened, used)
            if opened["replayed"] or opened["status"] != "claimed":
                return public
            if self.conn.info.transaction_status != TRANSACTION_STATUS_IDLE:
                raise RuntimeError("io inside transaction")
            if hooks.get("on_io"):
                hooks["on_io"](self.conn)
            try:
                outcome = self.adapter.run(
                    req["tool"], req["paths"], req["payload"], req["attempt_key"], hooks)
                self.adapter_calls += 1
            except AmbiguousOutcome:
                self.adapter_calls += 1
                return {**public, "status": "claimed", "result": None, "ambiguous": True}
            except Escape:
                self.adapter_calls += 1
                outcome = self._failed(req["tool"], "escape")
            except WorkerFail as exc:
                self.adapter_calls += 1
                outcome = self._failed(req["tool"], exc.token)
            except Exception:
                self.adapter_calls += 1
                return {**public, "status": "claimed", "result": None, "ambiguous": True}
            if hooks.get("before_accept"):
                hooks["before_accept"](self.conn, opened)
            try:
                self._accept(opened, outcome)
            except psycopg2.Error:
                self.conn.rollback()
                raise
            self.conn.commit()
            last = {
                **public,
                "status": outcome["status"],
                "result": outcome["result"],
                "replayed": False,
            }
            if outcome["status"] == "succeeded" or n == 1:
                return last
        return last

    def _open(self, label, req, workspace_root, allowed_roots):
        root = self.root if workspace_root is None else workspace_root
        allowed = self.allowed_roots if allowed_roots is None else list(allowed_roots)
        self.conn.set_isolation_level(ISOLATION_LEVEL_READ_COMMITTED)
        cur = self.conn.cursor()
        cur.execute(
            "SELECT v13_tool_effect_open(%s::uuid, %s::uuid, %s, %s, %s::text[], %s::jsonb)",
            (None, self.session, label, root, allowed, json.dumps(req)),
        )
        return as_obj(cur.fetchone()[0])

    def _accept(self, opened, outcome):
        cur = self.conn.cursor()
        cur.execute(
            "SELECT v13_tool_result_accept(%s::uuid, %s, %s, %s, %s::jsonb)",
            (
                opened["effect_id"],
                opened["attempt_no"],
                opened["fence"],
                outcome["status"],
                json.dumps(outcome["result"]),
            ),
        )
        self.accept_calls += 1
        cur.fetchone()

    def _failed(self, tool, token):
        return {
            "ambiguous": False,
            "status": "failed",
            "result": {
                "schema_version": 1,
                "ok": False,
                "tool": tool,
                "truncated": False,
                "depth_limited": False,
                "byte_length": 0,
                "text": "",
                "error_token": token,
            },
        }

    def _public(self, opened, used):
        return {
            "effect_id": opened["effect_id"],
            "attempt_no": opened["attempt_no"],
            "fence": opened["fence"],
            "replayed": opened["replayed"],
            "tool": opened["tool"],
            "status": opened["status"],
            "result": opened["result"],
            "attempts_used": used,
        }
