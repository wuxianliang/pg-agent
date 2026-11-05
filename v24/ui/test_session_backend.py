"""Adapter gate: AgentRuntimeBackend maps one session to one scope without DB."""
from __future__ import annotations

import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v24.ui import catalog
from v24.ui.session_backend import AgentRuntimeBackend


def check(condition, message):
    if not condition:
        raise AssertionError(message)


class FakeRuntime:
    def __init__(self):
        self.caches = {}
        self.scopes = {}
        self.fibers = {}
        self.starts = []
        self.rehydrated = []
        self.runs = {}
        self.cancelled = []
        self.steered = []
        self.limits = catalog.LEGACY_UI_LIMITS

    def create_scope(self, realm):
        scope = "scope-" + uuid.uuid4().hex[:8]
        self.scopes[scope] = realm
        return scope

    def install_tools(self, scope, families):
        self.caches[scope] = {("fiber",): (scope, "fiber-1")}
        return {family.identity: "install" for family in families}

    def fiber_for(self, scope, identity):
        return "fiber-1"

    def start_run(self, scope, owner, messages, *, toolset="exec", budget=None, key=None):
        run_id = str(uuid.uuid4())
        self.starts.append((scope, owner, messages, toolset, budget, key))
        self.runs[run_id] = {"run_id": run_id, "status": "running", "revision": 1,
                             "epoch_no": 1, "registration_generation": 1,
                             "driving_generation": 1, "created_at": "",
                             "updated_at": "", "interaction": None,
                             "pending_steer": None, "result": None}
        return (run_id,)

    def run_state(self, run_id, after_revision=0):
        return {"v": 1, "run": dict(self.runs[run_id]), "events": [], "revision": 1,
                "changed": True}

    def rehydrate(self, scope, realm, workspace_root, toolset):
        self.rehydrated.append((scope, realm, workspace_root, toolset))
        self.scopes[scope] = realm
        self.fibers[scope] = "fiber-1"
        self.caches[scope] = {("fiber",): (scope, "fiber-1")}

    def cancel(self, run_id, key):
        self.cancelled.append((run_id, key))
        self.runs[run_id]["status"] = "cancelled"
        return {"disposition": "committed", "emitted": [run_id]}

    def steer(self, run_id, message, key):
        self.steered.append((run_id, message, key))
        return {"disposition": "committed", "emitted": [run_id]}


def main():
    with tempfile.TemporaryDirectory(prefix="v24-session-adapter-") as temp:
        env = type("Env", (), {"workspace_root": Path(temp)})()
        runtime = FakeRuntime()
        backend = AgentRuntimeBackend(runtime, env, mode="real", toolset="read")
        session_id = str(uuid.uuid4())
        result = backend.start(session_id=session_id, message="hello", toolset="read",
                               budget={"steps": 3}, run_key="k-start",
                               workspace_root=temp, model="fake")
        check(result.run_id and result.scope_id, result)
        check(result.binding["realm"] == "ui-" + session_id, result.binding)
        check(runtime.starts[-1][2][-1]["content"] == "hello", runtime.starts)
        check(result.run["status"] == "running", result.run)
        polled = backend.poll(result.run_id)
        check(polled["run"]["run_id"] == result.run_id, polled)

        # A terminal steer after a process restart rehydrates the persisted scope.
        runtime.caches.clear()
        seed = [{"role": "system", "content": "h"}, {"role": "user", "content": "next"}]
        second = backend.start(session_id=session_id, message="next", toolset="read",
                               budget={"steps": 3}, run_key="k-steer",
                               workspace_root=temp, model="fake", seed=seed,
                               binding=result.binding)
        check(second.binding["scope_id"] == result.binding["scope_id"], second.binding)
        check(runtime.starts[-1][2] == seed, runtime.starts[-1])
        check(runtime.rehydrated, runtime.rehydrated)

        backend.steer(second.run_id, "more", 1, "s-key")
        check(runtime.steered[-1][1] == "more", runtime.steered)
        backend.cancel(second.run_id, "c-key")
        check(runtime.cancelled[-1][0] == second.run_id, runtime.cancelled)
        try:
            backend.respond(second.run_id, "i", {"text": "x"}, 1, "r-key")
        except RuntimeError as exc:
            check(str(exc) == "waiting_unsupported", exc)
        else:
            raise AssertionError("real respond claimed success")
    print("[passed] v24 session backend adapter")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
